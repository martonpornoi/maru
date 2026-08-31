"""Minimal same-shell logistics workspace and My Maru offer pages."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, cast
from urllib.parse import urlencode
from uuid import UUID, uuid4

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.signing import BadSignature, SignatureExpired
from django.db import DatabaseError
from django.db.models import F
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from maru.audit.models import AuditEvent
from maru.authorization.access import AccessIntent
from maru.authorization.page_access import (
    PageAccessSpec,
    fixed_page_access,
    scoped_page_access,
)
from maru.authorization.policy import resolve_edition_target
from maru.events.models import EventEdition
from maru.identity.models import Account

from .authorization import resolve_logistics_manifest_target
from .forms import EquipmentOfferForm
from .html_commands import (
    STAFF_COMMAND_BY_ACTION,
    configure_staff_form_choices,
    execute_staff_command,
    manifest_line_forms,
    manifest_state_forms,
    offer_review_forms,
    staff_command_forms,
)
from .queries import (
    ManifestProjection,
    NamedLogisticsChoice,
    authorize_logistics_api_scope,
    authorize_personal_logistics_index_scope,
    authorize_self_offer_history_api_scope,
    can_submit_equipment_offer,
    list_logistics_workspace,
    list_self_offers,
    manifest_for_workspace,
    my_equipment_offer_editions,
    prepare_restricted_contact_request,
    read_restricted_logistics_contact,
    stage_tech_receiving_manifests,
)
from .services import (
    CATALOG_MANAGE_CAPABILITY,
    MANIFEST_MANAGE_CAPABILITY,
    MANIFEST_VIEW_CAPABILITY,
    OFFER_REVIEW_CAPABILITY,
    OFFLINE_RECONCILE_CAPABILITY,
    OPERATIONS_MANAGE_CAPABILITY,
    RESTRICTED_CONTACT_CAPABILITY,
    WORKSPACE_VIEW_CAPABILITY,
    LogisticsAuthorizationDeniedError,
    LogisticsCommandError,
    LogisticsResourceUnavailableError,
    OfferItemInput,
    record_manifest_receipt,
    submit_equipment_offer,
)
from .staff_forms import ManifestReceiptForm, RestrictedContactReadForm

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime


def _actor(request: HttpRequest) -> Account:
    if not isinstance(request.user, Account) or not request.user.is_active:
        raise PermissionDenied("The logistics workspace is unavailable.")
    return request.user


@dataclass(frozen=True, slots=True)
class _EditionRouteScope:
    organization_id: UUID
    edition_id: UUID


def _edition_route_scope(
    *, organization_slug: str, series_slug: str, edition_slug: str
) -> _EditionRouteScope:
    row = (
        EventEdition.objects.filter(
            organization__slug=organization_slug,
            series__slug=series_slug,
            slug=edition_slug,
            series__organization_id=F("organization_id"),
        )
        .order_by()
        .values("id", "organization_id")
        .first()
    )
    if row is None:
        raise LogisticsAuthorizationDeniedError
    return _EditionRouteScope(
        organization_id=row["organization_id"],
        edition_id=row["id"],
    )


def _edition_route(
    *,
    scope: _EditionRouteScope,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> EventEdition:
    edition = (
        EventEdition.objects.select_related("organization", "series")
        .filter(
            id=scope.edition_id,
            organization_id=scope.organization_id,
            organization__slug=organization_slug,
            series__slug=series_slug,
            slug=edition_slug,
            series__organization_id=F("organization_id"),
        )
        .first()
    )
    if edition is None:
        raise LogisticsAuthorizationDeniedError
    return edition


def _page_context(
    request: HttpRequest,
    edition: EventEdition,
    *,
    personal: bool = False,
    access_spec: PageAccessSpec | None = None,
) -> dict[str, object]:
    context = admin.site.each_context(request)
    context.update(
        {
            "organization": edition.organization,
            "convention_series": edition.series,
            "edition": edition,
            "maru_personal_surface": personal,
        }
    )
    if personal:
        context["has_permission"] = True
    if access_spec is not None:
        context["maru_page_access_spec"] = access_spec
    elif personal:
        context["maru_page_access_spec"] = _personal_access_spec()
    return context


def _personal_access_spec() -> PageAccessSpec:
    return fixed_page_access(
        policy="self",
        scope_label="Your own equipment offers",
        explanation=(
            "This page uses your signed-in own-record relationship. It cannot be "
            "shared with a staff role or another person."
        ),
        audience_labels=("You",),
    )


def _edition_access_spec(
    *,
    edition: EventEdition,
    scope_label: str,
    intents: tuple[AccessIntent, ...],
) -> PageAccessSpec:
    return scoped_page_access(
        target=resolve_edition_target(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        ),
        scope_label=scope_label,
        intents=intents,
    )


def _manifest_access_spec(
    *, edition: EventEdition, manifest_id: UUID, title: str
) -> PageAccessSpec:
    return scoped_page_access(
        target=resolve_logistics_manifest_target(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            manifest_id=manifest_id,
        ),
        scope_label=f"{edition.name} / {title}",
        intents=(
            AccessIntent(
                capability_code=MANIFEST_VIEW_CAPABILITY,
                label="View this Logistics manifest",
            ),
            AccessIntent(
                capability_code=MANIFEST_MANAGE_CAPABILITY,
                label="Manage this Logistics manifest",
            ),
        ),
    )


def _authorize_manifest_page(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    manifest_id: UUID,
) -> None:
    try:
        authorize_logistics_api_scope(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            manifest_id=manifest_id,
            capability_code=MANIFEST_VIEW_CAPABILITY,
        )
    except LogisticsAuthorizationDeniedError:
        authorize_logistics_api_scope(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            manifest_id=manifest_id,
            capability_code=MANIFEST_MANAGE_CAPABILITY,
        )


def _manifest_receipt_rows(
    *, manifest: ManifestProjection, zone_name: str, can_manage: bool
) -> tuple[dict[str, object], ...]:
    receipt_enabled = (
        can_manage
        and manifest.kind in {"inbound", "stage_receiving"}
        and (manifest.status in {"sealed", "completed"})
    )
    rows: list[dict[str, object]] = []
    for line in manifest.lines:
        form = None
        if receipt_enabled and line.current_sequence == 0:
            form = ManifestReceiptForm(
                initial={
                    "idempotency_key": uuid4(),
                    "expected_sequence": 0,
                    "occurred_at": timezone.now(),
                    "condition_after": "Received as described",
                    "reason": "Receive this manifest line from the team.",
                },
                zone_name=zone_name,
            )
        rows.append({"line": asdict(line), "receipt_form": form})
    return tuple(rows)


def _can_manage_manifest(
    *, actor: Account, edition: EventEdition, manifest_id: UUID
) -> bool:
    try:
        authorize_logistics_api_scope(
            actor=actor,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            manifest_id=manifest_id,
            capability_code=MANIFEST_MANAGE_CAPABILITY,
        )
    except LogisticsAuthorizationDeniedError:
        return False
    return True


def _can_run_staff_action(
    *,
    actor: Account,
    scope: _EditionRouteScope,
    action: str,
    object_id: UUID | None = None,
) -> bool:
    try:
        _preauthorize_staff_action(
            actor=actor,
            scope=scope,
            action=action,
            object_id=object_id,
        )
    except LogisticsAuthorizationDeniedError:
        return False
    return True


def _restricted_contact_form(
    *,
    address_id: UUID,
    address_label: str,
    zone_name: str,
    data: Mapping[str, object] | None = None,
) -> RestrictedContactReadForm:
    form = RestrictedContactReadForm(
        data,
        zone_name=zone_name,
        initial={"address_id": address_id},
    )
    address_field = form.fields["address_id"]
    if not isinstance(address_field, forms.ChoiceField):
        raise TypeError("Restricted address field must remain a closed choice.")
    address_field.choices = ((str(address_id), address_label),)
    return form


def _restricted_contact_rows(
    *,
    actor: Account,
    edition: EventEdition,
    addresses: tuple[NamedLogisticsChoice, ...],
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for address in addresses:
        try:
            authorize_logistics_api_scope(
                actor=actor,
                organization_id=edition.organization_id,
                edition_id=edition.id,
                address_id=address.value,
                capability_code=RESTRICTED_CONTACT_CAPABILITY,
            )
        except LogisticsAuthorizationDeniedError:
            continue
        rows.append(
            {
                "address_id": address.value,
                "label": address.label,
                "form": _restricted_contact_form(
                    address_id=address.value,
                    address_label=address.label,
                    zone_name=edition.time_zone,
                ),
            }
        )
    return tuple(rows)


_CATALOG_STAFF_ACTIONS = frozenset(
    {
        "party-create",
        "address-create",
        "node-create",
        "asset-create",
        "stock-create",
        "key-create",
        "keyholder-assign",
        "label-create",
        "agreement-create",
        "kit-create",
    }
)


def _preauthorize_staff_action(
    *,
    actor: Account,
    scope: _EditionRouteScope,
    action: str,
    object_id: UUID | None,
) -> None:
    if action == "offer-review" and object_id is not None:
        authorize_logistics_api_scope(
            actor=actor,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            offer_id=object_id,
            capability_code=OFFER_REVIEW_CAPABILITY,
        )
        return
    if action in {"manifest-state", "manifest-line-add"} and object_id is not None:
        authorize_logistics_api_scope(
            actor=actor,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            manifest_id=object_id,
            capability_code=MANIFEST_MANAGE_CAPABILITY,
        )
        return
    if object_id is not None:
        raise LogisticsAuthorizationDeniedError
    if action in _CATALOG_STAFF_ACTIONS:
        try:
            authorize_logistics_api_scope(
                actor=actor,
                organization_id=scope.organization_id,
                edition_id=scope.edition_id,
                capability_code=CATALOG_MANAGE_CAPABILITY,
            )
        except LogisticsAuthorizationDeniedError:
            authorize_logistics_api_scope(
                actor=actor,
                organization_id=scope.organization_id,
                capability_code=CATALOG_MANAGE_CAPABILITY,
            )
        return
    capability = {
        "manifest-create": OPERATIONS_MANAGE_CAPABILITY,
        "event-record": OPERATIONS_MANAGE_CAPABILITY,
        "offline-reconcile": OFFLINE_RECONCILE_CAPABILITY,
    }.get(action)
    if capability is None:
        raise LogisticsAuthorizationDeniedError
    authorize_logistics_api_scope(
        actor=actor,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        capability_code=capability,
    )


@never_cache
@login_required(login_url="staff-login")
@require_http_methods(("GET",))
def logistics_workspace(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    """Render logistics workspace.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    series_slug : str
        The URL slug identifying the convention series.
    edition_slug : str
        The URL slug identifying the event edition.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.

    Raises
    ------
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    try:
        actor = _actor(request)
        scope = _edition_route_scope(
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        authorize_logistics_api_scope(
            actor=actor,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            capability_code=WORKSPACE_VIEW_CAPABILITY,
        )
        if request.GET:
            return HttpResponse("Unsupported query parameters.", status=400)
        edition = _edition_route(
            scope=scope,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        workspace = list_logistics_workspace(
            actor=actor,
            organization_id=edition.organization_id,
            edition_id=edition.id,
        )
    except LogisticsAuthorizationDeniedError as error:
        raise PermissionDenied("The logistics workspace is unavailable.") from error
    except DatabaseError:
        return HttpResponse(
            "Logistics records are temporarily unavailable.", status=503
        )
    authorized_staff_command_forms = tuple(
        (definition, form)
        for definition, form in staff_command_forms(
            zone_name=edition.time_zone,
            choices=workspace.choices,
        )
        if _can_run_staff_action(
            actor=actor,
            scope=scope,
            action=definition.action,
        )
    )
    context = _page_context(
        request,
        edition,
        access_spec=_edition_access_spec(
            edition=edition,
            scope_label=f"{edition.name} / Logistics workspace",
            intents=(
                AccessIntent(
                    capability_code=WORKSPACE_VIEW_CAPABILITY,
                    label="View Logistics workspace",
                ),
                AccessIntent(
                    capability_code=OPERATIONS_MANAGE_CAPABILITY,
                    label="Manage Logistics operations",
                ),
            ),
        ),
    )
    context.update(
        {
            "title": "Logistics",
            "workspace": asdict(workspace),
            "staff_command_forms": authorized_staff_command_forms,
            "offer_review_forms": tuple(
                row
                for row in offer_review_forms(
                    offers=workspace.offers,
                    choices=workspace.choices,
                    zone_name=edition.time_zone,
                )
                if _can_run_staff_action(
                    actor=actor,
                    scope=scope,
                    action="offer-review",
                    object_id=row[0].id,
                )
            ),
            "manifest_state_forms": tuple(
                row
                for row in manifest_state_forms(
                    manifests=workspace.manifests,
                    zone_name=edition.time_zone,
                )
                if _can_run_staff_action(
                    actor=actor,
                    scope=scope,
                    action="manifest-state",
                    object_id=row[0].id,
                )
            ),
            "manifest_line_forms": tuple(
                row
                for row in manifest_line_forms(
                    manifests=workspace.manifests,
                    choices=workspace.choices,
                    zone_name=edition.time_zone,
                )
                if _can_run_staff_action(
                    actor=actor,
                    scope=scope,
                    action="manifest-line-add",
                    object_id=row[0].id,
                )
            ),
            "restricted_contact_rows": _restricted_contact_rows(
                actor=actor,
                edition=edition,
                addresses=workspace.choices.addresses,
            ),
        }
    )
    return TemplateResponse(request, "logistics/workspace.html", context)


@never_cache
@login_required(login_url="staff-login")
@require_http_methods(("GET",))
def logistics_manifest_detail(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    manifest_id: UUID,
) -> HttpResponse:
    """Render logistics manifest detail.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    series_slug : str
        The URL slug identifying the convention series.
    edition_slug : str
        The URL slug identifying the event edition.
    manifest_id : UUID
        The identifier of the manifest.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    try:
        actor = _actor(request)
        scope = _edition_route_scope(
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        _authorize_manifest_page(
            actor=actor,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            manifest_id=manifest_id,
        )
        if request.GET:
            return HttpResponse("Unsupported query parameters.", status=400)
        edition = _edition_route(
            scope=scope,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        manifest = manifest_for_workspace(
            actor=actor,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            manifest_id=manifest_id,
        )
    except LogisticsAuthorizationDeniedError as error:
        raise PermissionDenied("The logistics manifest is unavailable.") from error
    except LogisticsResourceUnavailableError as error:
        raise Http404 from error
    except DatabaseError:
        return HttpResponse("The manifest is temporarily unavailable.", status=503)
    context = _page_context(
        request,
        edition,
        access_spec=_manifest_access_spec(
            edition=edition,
            manifest_id=manifest.id,
            title=manifest.title,
        ),
    )
    context.update(
        {
            "title": manifest.title,
            "manifest": asdict(manifest),
            "receipt_rows": _manifest_receipt_rows(
                manifest=manifest,
                zone_name=edition.time_zone,
                can_manage=_can_manage_manifest(
                    actor=actor,
                    edition=edition,
                    manifest_id=manifest.id,
                ),
            ),
        }
    )
    return TemplateResponse(request, "logistics/manifest_detail.html", context)


@never_cache
@login_required(login_url="staff-login")
@require_http_methods(("POST",))
def logistics_staff_command(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    action: str,
    object_id: UUID | None = None,
) -> HttpResponse:
    """Render logistics staff command.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    series_slug : str
        The URL slug identifying the convention series.
    edition_slug : str
        The URL slug identifying the event edition.
    action : str
        The requested lifecycle action.
    object_id : UUID | None, default=None
        The identifier of the object.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    definition = STAFF_COMMAND_BY_ACTION.get(action)
    if definition is None:
        raise Http404
    actor = _actor(request)
    try:
        scope = _edition_route_scope(
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        _preauthorize_staff_action(
            actor=actor,
            scope=scope,
            action=action,
            object_id=object_id,
        )
        edition = _edition_route(
            scope=scope,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        workspace = list_logistics_workspace(
            actor=actor,
            organization_id=edition.organization_id,
            edition_id=edition.id,
        )
    except LogisticsAuthorizationDeniedError as error:
        raise PermissionDenied("The logistics command is unavailable.") from error
    form = configure_staff_form_choices(
        definition.form_class(request.POST, zone_name=edition.time_zone),
        choices=workspace.choices,
    )
    if not form.is_valid():
        messages.error(request, "Check the submitted logistics command fields.")
    else:
        route_field = {
            "offer-review": "offer_id",
            "manifest-state": "manifest_id",
            "manifest-line-add": "manifest_id",
        }.get(action)
        if route_field is not None and form.cleaned_data.get(route_field) != object_id:
            messages.error(request, "The submitted logistics object is unavailable.")
            return redirect(
                "logistics-workspace",
                organization_slug,
                series_slug,
                edition_slug,
            )
        try:
            result = execute_staff_command(
                action=action,
                actor=actor,
                organization_id=edition.organization_id,
                edition_id=edition.id,
                data=form.cleaned_data,
                correlation_id=uuid4(),
            )
        except LogisticsAuthorizationDeniedError as error:
            raise PermissionDenied("The logistics command is unavailable.") from error
        except LogisticsCommandError as error:
            messages.error(
                request,
                f"The command could not be applied ({error.reason_code}).",
            )
        except ValidationError:
            messages.error(request, "The command input is not valid.")
        except DatabaseError:
            messages.error(request, "Logistics is temporarily unavailable.")
        else:
            state = "replayed" if result.replayed else "completed"
            messages.success(request, f"{definition.title} {state}.")
    return redirect(
        "logistics-workspace",
        organization_slug,
        series_slug,
        edition_slug,
    )


@never_cache
@login_required(login_url="staff-login")
@require_http_methods(("POST",))
def logistics_manifest_receipt(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    manifest_id: UUID,
    line_id: UUID,
) -> HttpResponse:
    """Render logistics manifest receipt.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    series_slug : str
        The URL slug identifying the convention series.
    edition_slug : str
        The URL slug identifying the event edition.
    manifest_id : UUID
        The identifier of the manifest.
    line_id : UUID
        The identifier of the line.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.

    Raises
    ------
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    actor = _actor(request)
    try:
        scope = _edition_route_scope(
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        authorize_logistics_api_scope(
            actor=actor,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            manifest_id=manifest_id,
            manifest_line_id=line_id,
            capability_code=MANIFEST_MANAGE_CAPABILITY,
        )
    except LogisticsAuthorizationDeniedError as error:
        raise PermissionDenied("The manifest receipt is unavailable.") from error
    edition = _edition_route(
        scope=scope,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
    form = ManifestReceiptForm(request.POST, zone_name=edition.time_zone)
    if not form.is_valid():
        messages.error(request, "Check the manifest receipt fields.")
    else:
        try:
            result = record_manifest_receipt(
                actor=actor,
                organization_id=edition.organization_id,
                edition_id=edition.id,
                manifest_id=manifest_id,
                line_id=line_id,
                expected_sequence=cast("int", form.cleaned_data["expected_sequence"]),
                occurred_at=cast("datetime", form.cleaned_data["occurred_at"]),
                condition_after=cast("str", form.cleaned_data["condition_after"]),
                reason=cast("str", form.cleaned_data["reason"]),
                idempotency_key=cast("UUID", form.cleaned_data["idempotency_key"]),
                correlation_id=uuid4(),
                source_channel="browser",
            )
        except LogisticsAuthorizationDeniedError as error:
            raise PermissionDenied("The manifest receipt is unavailable.") from error
        except (LogisticsCommandError, ValidationError):
            messages.error(request, "The manifest line could not be received.")
        except DatabaseError:
            messages.error(request, "Logistics is temporarily unavailable.")
        else:
            state = "replayed" if result.replayed else "recorded"
            messages.success(request, f"Manifest receipt {state}.")
    return redirect(
        "logistics-manifest-detail-page",
        organization_slug,
        series_slug,
        edition_slug,
        manifest_id,
    )


@never_cache
@login_required(login_url="staff-login")
@require_http_methods(("GET",))
def stage_tech_receiving_page(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    """Render stage tech receiving page.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    series_slug : str
        The URL slug identifying the convention series.
    edition_slug : str
        The URL slug identifying the event edition.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.

    Raises
    ------
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    try:
        actor = _actor(request)
        scope = _edition_route_scope(
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        authorize_logistics_api_scope(
            actor=actor,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            capability_code=WORKSPACE_VIEW_CAPABILITY,
        )
        if request.GET:
            return HttpResponse("Unsupported query parameters.", status=400)
        edition = _edition_route(
            scope=scope,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        manifests = stage_tech_receiving_manifests(
            actor=actor,
            organization_id=edition.organization_id,
            edition_id=edition.id,
        )
    except LogisticsAuthorizationDeniedError as error:
        raise PermissionDenied("Stage Tech receiving is unavailable.") from error
    except DatabaseError:
        return HttpResponse(
            "Stage Tech receiving is temporarily unavailable.", status=503
        )
    context = _page_context(
        request,
        edition,
        access_spec=_edition_access_spec(
            edition=edition,
            scope_label=f"{edition.name} / Stage Tech receiving",
            intents=(
                AccessIntent(
                    capability_code=WORKSPACE_VIEW_CAPABILITY,
                    label="View Stage Tech receiving",
                ),
                AccessIntent(
                    capability_code=OPERATIONS_MANAGE_CAPABILITY,
                    label="Manage Logistics operations",
                ),
            ),
        ),
    )
    context.update(
        {
            "title": "Stage Tech receiving",
            "manifests": tuple(
                {
                    "manifest": asdict(manifest),
                    "receipt_rows": _manifest_receipt_rows(
                        manifest=manifest,
                        zone_name=edition.time_zone,
                        can_manage=_can_manage_manifest(
                            actor=actor,
                            edition=edition,
                            manifest_id=manifest.id,
                        ),
                    ),
                }
                for manifest in manifests
            ),
        }
    )
    return TemplateResponse(request, "logistics/stage_receiving.html", context)


CONTACT_SIGNING_NAMESPACE = "maru.logistics.restricted-contact.v1"
CONTACT_TOKEN_MAX_AGE_SECONDS = 60


@never_cache
@login_required(login_url="staff-login")
@require_http_methods(("POST",))
def restricted_contact_request(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    address_id: UUID,
) -> HttpResponse:
    """Render restricted contact request.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    series_slug : str
        The URL slug identifying the convention series.
    edition_slug : str
        The URL slug identifying the event edition.
    address_id : UUID
        The identifier of the address.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.

    Raises
    ------
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    actor = _actor(request)
    try:
        scope = _edition_route_scope(
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        authorize_logistics_api_scope(
            actor=actor,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            address_id=address_id,
            capability_code=RESTRICTED_CONTACT_CAPABILITY,
        )
        edition = _edition_route(
            scope=scope,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
    except LogisticsAuthorizationDeniedError as error:
        raise PermissionDenied("The restricted contact is unavailable.") from error
    form = _restricted_contact_form(
        address_id=address_id,
        address_label="Selected restricted contact",
        zone_name=edition.time_zone,
        data=request.POST,
    )
    if not form.is_valid():
        messages.error(request, "Check the restricted-contact request fields.")
        return redirect(
            "logistics-workspace",
            organization_slug,
            series_slug,
            edition_slug,
        )
    try:
        access_request_id = prepare_restricted_contact_request(
            actor=actor,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            address_id=address_id,
            purpose=form.cleaned_data["purpose"],
            access_purpose=form.cleaned_data["access_purpose"],
            correlation_id=uuid4(),
            source_channel="browser",
        )
    except LogisticsAuthorizationDeniedError as error:
        raise PermissionDenied("The restricted contact is unavailable.") from error
    except LogisticsResourceUnavailableError:
        messages.error(request, "The restricted contact is unavailable.")
        return redirect(
            "logistics-workspace",
            organization_slug,
            series_slug,
            edition_slug,
        )
    token = signing.dumps(
        str(access_request_id),
        salt=CONTACT_SIGNING_NAMESPACE,
        compress=False,
    )
    target = reverse(
        "logistics-restricted-contact-result",
        args=(organization_slug, series_slug, edition_slug),
    )
    return redirect(f"{target}?{urlencode({'token': token})}")


@never_cache
@login_required(login_url="staff-login")
@require_http_methods(("GET",))
def restricted_contact_result(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    """Render restricted contact result.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    series_slug : str
        The URL slug identifying the convention series.
    edition_slug : str
        The URL slug identifying the event edition.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    actor = _actor(request)
    try:
        scope = _edition_route_scope(
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        authorize_logistics_api_scope(
            actor=actor,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            capability_code=RESTRICTED_CONTACT_CAPABILITY,
        )
    except LogisticsAuthorizationDeniedError as error:
        raise PermissionDenied("The restricted contact is unavailable.") from error
    if set(request.GET) != {"token"} or len(request.GET.getlist("token")) != 1:
        return HttpResponse("Unsupported query parameters.", status=400)
    edition = _edition_route(
        scope=scope,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
    try:
        token_value = signing.loads(
            request.GET["token"],
            salt=CONTACT_SIGNING_NAMESPACE,
            max_age=CONTACT_TOKEN_MAX_AGE_SECONDS,
        )
    except (BadSignature, SignatureExpired):
        raise Http404 from None
    try:
        access_request_id = UUID(str(token_value))
    except ValueError:
        raise Http404 from None
    access_request = (
        AuditEvent.objects.filter(
            id=access_request_id,
            principal_kind="account",
            principal_id=actor.id,
            organization_id=edition.organization_id,
            event_edition_id=edition.id,
            capability_code="logistics.view_restricted_contacts",
            operation__startswith="logistics.restricted_contact.request.",
            target_type="logistics.restricted_address",
            target_id__isnull=False,
            outcome=AuditEvent.Outcome.ALLOW,
        )
        .only(
            "id",
            "target_id",
            "operation",
            "safe_metadata",
            "correlation_id",
        )
        .first()
    )
    if access_request is None or access_request.target_id is None:
        raise Http404
    purpose = access_request.operation.rsplit(".", maxsplit=1)[-1]
    access_purpose = access_request.safe_metadata.get("access_purpose")
    if not isinstance(access_purpose, str):
        raise Http404
    try:
        projection = read_restricted_logistics_contact(
            actor=actor,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            address_id=access_request.target_id,
            purpose=purpose,
            access_purpose=access_purpose,
            access_request_id=access_request.id,
            correlation_id=access_request.correlation_id,
            source_channel="browser",
        )
    except LogisticsAuthorizationDeniedError as error:
        raise PermissionDenied("The restricted contact is unavailable.") from error
    except (LogisticsResourceUnavailableError, ValueError) as error:
        raise Http404 from error
    except DatabaseError:
        return HttpResponse(
            "The restricted contact is temporarily unavailable.", status=503
        )
    context = _page_context(
        request,
        edition,
        access_spec=_edition_access_spec(
            edition=edition,
            scope_label=f"{edition.name} / Restricted logistics contacts",
            intents=(
                AccessIntent(
                    capability_code=RESTRICTED_CONTACT_CAPABILITY,
                    label="View restricted Logistics contacts",
                ),
            ),
        ),
    )
    context.update(
        {
            "title": "Restricted logistics contact",
            "contact": asdict(projection),
        }
    )
    response = TemplateResponse(
        request,
        "logistics/restricted_contact.html",
        context,
    )
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["Pragma"] = "no-cache"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


@never_cache
@login_required(login_url="staff-login")
@require_http_methods(("GET",))
def my_logistics_offers_index(request: HttpRequest) -> HttpResponse:
    """Render my logistics offers index.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.

    Raises
    ------
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    try:
        actor = _actor(request)
        authorize_personal_logistics_index_scope(actor=actor)
        if request.GET:
            return HttpResponse("Unsupported query parameters.", status=400)
        editions = my_equipment_offer_editions(actor=actor)
    except LogisticsAuthorizationDeniedError as error:
        raise PermissionDenied("Equipment offers are unavailable.") from error
    except DatabaseError:
        return HttpResponse("Equipment offers are temporarily unavailable.", status=503)
    context = admin.site.each_context(request)
    context.update(
        {
            "title": "My equipment offers",
            "maru_personal_surface": True,
            "has_permission": True,
            "maru_page_access_spec": _personal_access_spec(),
            "offer_editions": tuple(asdict(edition) for edition in editions),
            "maru_personal_profile_pairs": tuple(
                sorted(
                    {
                        (
                            edition.adoption_profile_code,
                            edition.adoption_profile_version,
                        )
                        for edition in editions
                    }
                )
            ),
        }
    )
    return TemplateResponse(request, "logistics/my_offer_index.html", context)


@never_cache
@login_required(login_url="staff-login")
@require_http_methods(("GET", "POST"))
def my_logistics_offers(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    """Render my logistics offers.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    series_slug : str
        The URL slug identifying the convention series.
    edition_slug : str
        The URL slug identifying the event edition.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.

    Raises
    ------
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    try:
        actor = _actor(request)
        scope = _edition_route_scope(
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        authorize_self_offer_history_api_scope(
            actor=actor,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
        )
        if request.GET:
            return HttpResponse("Unsupported query parameters.", status=400)
        edition = _edition_route(
            scope=scope,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        can_submit = can_submit_equipment_offer(
            actor=actor,
            organization_id=edition.organization_id,
            edition_id=edition.id,
        )
        form: EquipmentOfferForm | None
        if request.method == "POST":
            if not can_submit:
                raise PermissionDenied("New equipment offers are unavailable.")
            form = EquipmentOfferForm(request.POST, zone_name=edition.time_zone)
            if form.is_valid():
                data = form.cleaned_data
                try:
                    submit_equipment_offer(
                        actor=actor,
                        organization_id=edition.organization_id,
                        edition_id=edition.id,
                        title=cast("str", data["title"]),
                        description=cast("str", data["description"]),
                        pickup_label=cast("str", data["pickup_label"]),
                        pickup_recipient_name=cast(
                            "str", data["pickup_recipient_name"]
                        ),
                        pickup_postal_address=cast(
                            "str", data["pickup_postal_address"]
                        ),
                        pickup_access_instructions=cast(
                            "str", data["pickup_access_instructions"]
                        ),
                        pickup_retention_until=data["pickup_retention_until"],
                        available_from=data["available_from"],
                        available_until=data["available_until"],
                        requested_return_at=data["requested_return_at"],
                        items=(
                            OfferItemInput(
                                kind=cast("str", data["item_kind"]),
                                name=cast("str", data["item_name"]),
                                description=cast("str", data["item_description"]),
                                quantity=cast("int", data["item_quantity"]),
                                manufacturer=cast("str", data["manufacturer"]),
                                model_name=cast("str", data["model_name"]),
                                serial_number=cast("str", data["serial_number"]),
                                condition=cast("str", data["condition"]),
                                value_class=cast("str", data["value_class"]),
                                ownership_statement=cast(
                                    "str", data["ownership_statement"]
                                ),
                            ),
                        ),
                        reason=cast("str", data["reason"]),
                        idempotency_key=cast("UUID", data["idempotency_key"]),
                        correlation_id=uuid4(),
                        source_channel="browser",
                    )
                except (ValidationError, LogisticsCommandError) as error:
                    form.add_error(None, str(error))
                else:
                    messages.success(request, "Your equipment offer was submitted.")
                    return redirect(
                        "my-logistics-offers",
                        organization_slug,
                        series_slug,
                        edition_slug,
                    )
        else:
            form = (
                EquipmentOfferForm(
                    initial={"idempotency_key": uuid4()},
                    zone_name=edition.time_zone,
                )
                if can_submit
                else None
            )
        offers = list_self_offers(
            actor=actor,
            organization_id=edition.organization_id,
            edition_id=edition.id,
        )
    except LogisticsAuthorizationDeniedError as error:
        raise PermissionDenied("Equipment offers are unavailable.") from error
    except DatabaseError:
        return HttpResponse("Equipment offers are temporarily unavailable.", status=503)
    context = _page_context(request, edition, personal=True)
    context.update(
        {
            "title": "My equipment offers",
            "form": form,
            "offers": tuple(asdict(offer) for offer in offers),
            "can_submit": can_submit,
        }
    )
    return TemplateResponse(request, "logistics/my_offers.html", context)
