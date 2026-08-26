"""Purpose-built organization governance pages inside the Maru admin shell."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from django.contrib import admin, messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.views.decorators.http import require_POST

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import decide, resolve_organization_target
from maru.events.admin_context import authorized_admin_organization_ids
from maru.identity.models import Account
from maru.organizations.forms import (
    RepresentationActivationForm,
    RepresentationInviteForm,
    RepresentationProvisionForm,
    RepresentationResponseForm,
)
from maru.organizations.models import (
    Organization,
    OrganizationRepresentation,
    RepresentationAppointment,
)
from maru.organizations.representation import (
    activate_representation,
    invite_representation_controller,
    provision_representation,
    respond_to_representation_invitation,
)
from maru.organizations.representation_catalog import (
    REPRESENTATION_DEFINITIONS,
    representation_definition,
)

if TYPE_CHECKING:
    from django import forms

logger = logging.getLogger(__name__)

_OPEN_APPOINTMENT_STATES = (
    RepresentationAppointment.State.INVITED,
    RepresentationAppointment.State.ACCEPTED,
    RepresentationAppointment.State.ACTIVE,
)
_REPRESENTATION_APPOINTMENT_HISTORY_LIMIT = 100
_GENERIC_ACCOUNT_INELIGIBLE = (
    "No eligible active account matches that exact email address."
)
_ACCOUNT_INELIGIBILITY_CODES = frozenset(
    {
        "representation_account_ineligible",
        "representation_appointment_exists",
        "representation_membership_ended",
        "representation_membership_incompatible",
        "representation_membership_suspended",
    }
)
_REPRESENTATION_CONFLICT_CODES = frozenset(
    {
        "executive_board_role_conflict",
        "maru_operator_role_conflict",
        "representation_appointment_exists",
        "representation_controller_ineligible",
        "representation_controllers_incomplete",
        "representation_exists",
        "representation_invitation_answered",
        "representation_invitations_pending",
        "representation_membership_incompatible",
        "representation_not_provisioning",
        "representation_parent_not_draft",
        "stale_representation",
        "stale_representation_invitation",
    }
)


def _account(request: HttpRequest) -> Account:
    if not isinstance(request.user, Account) or not request.user.is_active:
        raise PermissionDenied
    return request.user


def _decision_allowed(
    *, actor: Account, organization: Organization, capability_code: str
) -> bool:
    return decide(
        principal=actor,
        capability_code=capability_code,
        resource=resolve_organization_target(organization_id=organization.id),
    ).allowed


def _append_page_access_audit(
    *,
    request: HttpRequest,
    actor: Account,
    organization_id: UUID | None,
    capability_code: str,
    operation: str,
    target_type: str,
    target_id: UUID | None,
    outcome: str,
    reason_code: str,
    obligations: tuple[str, ...] = (),
    target_count: int | None = None,
) -> None:
    """Retain value-minimized evidence for sensitive reads and denials.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID | None
        The organization identifier that owns the requested resource.
    capability_code : str
        The stable capability code required by the operation.
    operation : str
        The stable operation code recorded in audit evidence.
    target_type : str
        The closed target type discriminator defined by the domain catalog.
    target_id : UUID | None
        The target identifier within the requested scope.
    outcome : str
        The outcome resolved from the authorized request.
    reason_code : str
        The stable reason code from the relevant closed catalog.
    obligations : tuple[str, ...], default=()
        The obligations resolved from the authorized request.
    target_count : int | None, default=None
        The bounded number of target records.
    """
    route_name = (
        request.resolver_match.url_name
        if request.resolver_match is not None
        else "organization-representation"
    )
    safe_metadata: dict[str, object] = {
        "policy_version": POLICY_VERSION,
        "route_name": route_name,
        "http_method": request.method,
    }
    if target_count is not None:
        safe_metadata["target_count"] = target_count
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=None,
            capability_code=capability_code,
            operation=operation,
            target_type=target_type,
            target_id=target_id,
            outcome=outcome,
            reason_code=reason_code,
            correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            request_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            source_channel="web",
            obligations=obligations,
            changed_fields=(),
            safe_metadata=safe_metadata,
            retention_class="security-extended",
        )
    )


def _audit_denied_route(
    *,
    request: HttpRequest,
    actor: Account,
    organization_slug: str,
    capability_code: str,
    operation: str,
) -> None:
    organization_id = (
        Organization.objects.filter(slug__iexact=organization_slug)
        .values_list("id", flat=True)
        .first()
    )
    _append_page_access_audit(
        request=request,
        actor=actor,
        organization_id=organization_id,
        capability_code=capability_code,
        operation=operation,
        target_type="organizations.organization_representation",
        target_id=None,
        outcome=AuditEvent.Outcome.DENY,
        reason_code="permission_absent",
        obligations=("audit",),
    )


def _audit_denied_appointment(
    *,
    request: HttpRequest,
    actor: Account,
    appointment_id: UUID,
    reason_code: str = "self_relationship_absent",
) -> None:
    organization_id = (
        RepresentationAppointment.objects.filter(id=appointment_id)
        .values_list("representation__organization_id", flat=True)
        .first()
    )
    _append_page_access_audit(
        request=request,
        actor=actor,
        organization_id=organization_id,
        capability_code="organizations.manage_representation",
        operation="organizations.representation.invitation.respond",
        target_type="organizations.representation_appointment",
        target_id=appointment_id if organization_id is not None else None,
        outcome=AuditEvent.Outcome.DENY,
        reason_code=reason_code,
        obligations=("audit",),
    )


def _own_open_appointment(
    *, actor: Account, representation: OrganizationRepresentation | None
) -> RepresentationAppointment | None:
    if representation is None:
        return None
    return (
        representation.appointments.select_related("account")
        .filter(
            account=actor,
            state__in=_OPEN_APPOINTMENT_STATES,
        )
        .first()
    )


def _validation_codes(error: ValidationError) -> set[str | None]:
    if hasattr(error, "error_dict"):
        return {
            item.code
            for field_errors in error.error_dict.values()
            for item in field_errors
        }
    return {item.code for item in error.error_list}


def _validation_status(error: ValidationError) -> int:
    if _validation_codes(error).intersection(_REPRESENTATION_CONFLICT_CODES):
        return 409
    return 400


def _add_invitation_validation_errors(
    form: RepresentationInviteForm,
    error: ValidationError,
) -> None:
    if _validation_codes(error).intersection(_ACCOUNT_INELIGIBILITY_CODES):
        form.add_error("account_email", _GENERIC_ACCOUNT_INELIGIBLE)
        return
    _add_validation_errors(form, error)


def _authorized_organization_for_route(
    *,
    request: HttpRequest,
    actor: Account,
    organization_slug: str,
    capability_codes: tuple[str, ...],
) -> Organization:
    """Resolve a tenant only inside authority already scoped to the actor.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    actor : Account
        The authenticated account authorizing the operation.
    organization_slug : str
        The stable URL slug identifying the organization.
    capability_codes : tuple[str, ...]
        The capability codes resolved from the authorized request.

    Returns
    -------
    Organization
        The resolved Organization for authorized organization for route.

    Raises
    ------
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    if actor.is_platform_administrator:
        return get_object_or_404(Organization, slug__iexact=organization_slug)

    candidate_ids = authorized_admin_organization_ids(
        request,
        capability_codes=frozenset(capability_codes),
    )
    organization = (
        Organization.objects.filter(
            id__in=candidate_ids,
            slug__iexact=organization_slug,
        )
        .order_by("id")
        .first()
    )
    if organization is None or not any(
        _decision_allowed(
            actor=actor,
            organization=organization,
            capability_code=capability_code,
        )
        for capability_code in capability_codes
    ):
        _audit_denied_route(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            capability_code=capability_codes[0],
            operation="organizations.representation.route.authorize",
        )
        raise PermissionDenied
    return organization


def _add_validation_errors(form: forms.BaseForm, error: ValidationError) -> None:
    if hasattr(error, "message_dict"):
        for field_name, field_errors in error.message_dict.items():
            target = field_name if field_name in form.fields else None
            for field_error in field_errors:
                form.add_error(target, field_error)
        return
    for message in error.messages:
        form.add_error(None, message)


def _representation_dependency_failure(
    request: HttpRequest,
    *,
    organization: Organization | None = None,
) -> TemplateResponse:
    context = admin.site.each_context(request)
    context.update(
        {
            "title": "Representation & access unavailable",
            "has_permission": True,
            "baseline_admin_parent_template": "admin/base_site.html",
            "baseline_use_admin_shell": True,
            "baseline_page_id": "organization-representation",
            "baseline_page_class": "baseline-page--form",
            "baseline_can_view_organization": False,
            "baseline_can_manage_representation": False,
            "baseline_can_create_series": False,
            "baseline_can_create_edition": False,
            "organization": organization,
            "representation_load_failed": True,
        }
    )
    return TemplateResponse(
        request,
        "organizations/organization_representation.html",
        context,
        status=503,
    )


def _representation_page(
    request: HttpRequest,
    *,
    organization: Organization,
    provision_form: RepresentationProvisionForm | None = None,
    invite_form: RepresentationInviteForm | None = None,
    response_form: RepresentationResponseForm | None = None,
    activation_form: RepresentationActivationForm | None = None,
    status: int = 200,
) -> TemplateResponse:
    actor = _account(request)
    try:
        representation = (
            OrganizationRepresentation.objects.select_related("organization")
            .filter(organization=organization)
            .first()
        )
        own_appointment = _own_open_appointment(
            actor=actor,
            representation=representation,
        )
        view_decision = decide(
            principal=actor,
            capability_code="organizations.view_basic",
            resource=resolve_organization_target(organization_id=organization.id),
        )
        manage_decision = decide(
            principal=actor,
            capability_code="organizations.manage_representation",
            resource=resolve_organization_target(organization_id=organization.id),
        )
        can_view_organization = view_decision.allowed
        can_manage = manage_decision.allowed
        can_create_series = can_view_organization and _decision_allowed(
            actor=actor,
            organization=organization,
            capability_code="organizations.create_series",
        )
        can_create_edition = can_view_organization and _decision_allowed(
            actor=actor,
            organization=organization,
            capability_code="events.create",
        )
        if not (can_view_organization or can_manage or own_appointment is not None):
            _append_page_access_audit(
                request=request,
                actor=actor,
                organization_id=organization.id,
                capability_code="organizations.view_basic",
                operation="organizations.representation.page.view",
                target_type="organizations.organization_representation",
                target_id=representation.id if representation is not None else None,
                outcome=AuditEvent.Outcome.DENY,
                reason_code="permission_absent",
                obligations=("audit",),
            )
            raise PermissionDenied
        show_appointment_directory = can_manage or own_appointment is not None
        appointments: tuple[RepresentationAppointment, ...] = ()
        appointment_history_truncated = False
        if representation is not None and show_appointment_directory:
            appointment_query = RepresentationAppointment.objects.select_related(
                "account", "role_assignment"
            ).filter(representation_id=representation.id)
            if not can_manage:
                appointment_query = appointment_query.filter(account=actor)
            appointment_rows = list(
                appointment_query.order_by("-invited_at", "id")[
                    : _REPRESENTATION_APPOINTMENT_HISTORY_LIMIT + 1
                ]
            )
            appointment_history_truncated = (
                len(appointment_rows) > _REPRESENTATION_APPOINTMENT_HISTORY_LIMIT
            )
            appointments = tuple(
                appointment_rows[:_REPRESENTATION_APPOINTMENT_HISTORY_LIMIT]
            )
            if can_manage:
                _append_page_access_audit(
                    request=request,
                    actor=actor,
                    organization_id=organization.id,
                    capability_code="organizations.manage_representation",
                    operation=(
                        "organizations.representation.appointment_directory.read"
                    ),
                    target_type="organizations.organization_representation",
                    target_id=representation.id,
                    outcome=AuditEvent.Outcome.ALLOW,
                    reason_code=manage_decision.reason_code,
                    obligations=("audit_sensitive_read",),
                    target_count=len(appointments),
                )
    except DatabaseError:
        logger.exception("Unable to load organization representation")
        return _representation_dependency_failure(
            request,
            organization=organization,
        )

    can_provision = (
        actor.is_platform_administrator
        and organization.lifecycle == Organization.Lifecycle.DRAFT
        and representation is None
    )
    can_invite = (
        can_manage
        and organization.lifecycle == Organization.Lifecycle.DRAFT
        and representation is not None
        and representation.state == OrganizationRepresentation.State.PROVISIONING
    )
    can_activate = (
        actor.is_platform_administrator
        and organization.lifecycle == Organization.Lifecycle.DRAFT
        and representation is not None
        and representation.state == OrganizationRepresentation.State.PROVISIONING
    )
    definition = (
        representation_definition(representation.code)
        if representation is not None
        else None
    )
    if definition is None and provision_form is not None:
        selected_code = provision_form.data.get("representation_code")
        if isinstance(selected_code, str):
            definition = representation_definition(selected_code)
    context = admin.site.each_context(request)
    context.update(
        {
            "title": (
                f"{definition.name} — {organization.name}"
                if definition is not None
                else f"Representation and access — {organization.name}"
            ),
            "has_permission": True,
            "baseline_admin_parent_template": "admin/base_site.html",
            "baseline_use_admin_shell": True,
            "baseline_page_id": "organization-representation",
            "baseline_page_class": "baseline-page--form",
            "baseline_can_view_organization": can_view_organization,
            "baseline_can_manage_representation": can_manage,
            "baseline_can_create_series": can_create_series,
            "baseline_can_create_edition": can_create_edition,
            "organization": organization,
            "representation": representation,
            "representation_definition": definition,
            "representation_definitions": tuple(REPRESENTATION_DEFINITIONS.values()),
            "representation_load_failed": False,
            "appointments": appointments,
            "appointment_history_limit": _REPRESENTATION_APPOINTMENT_HISTORY_LIMIT,
            "appointment_history_truncated": appointment_history_truncated,
            "show_appointment_directory": show_appointment_directory,
            "own_appointment": own_appointment,
            "can_view_organization": can_view_organization,
            "can_manage_representation": can_manage,
            "can_provision_representation": can_provision,
            "can_invite_representation": can_invite,
            "can_activate_representation": can_activate,
            "provision_form": provision_form or RepresentationProvisionForm(),
            "invite_form": invite_form or RepresentationInviteForm(),
            "response_form": response_form
            or (
                RepresentationResponseForm(
                    initial={
                        "expected_version": own_appointment.invitation_version,
                        "decision": "accept",
                    }
                )
                if own_appointment is not None
                and own_appointment.state == RepresentationAppointment.State.INVITED
                else None
            ),
            "activation_form": activation_form
            or (
                RepresentationActivationForm(
                    organization=organization,
                    initial={
                        "expected_version": representation.aggregate_version,
                    },
                )
                if representation is not None
                else None
            ),
        }
    )

    return TemplateResponse(
        request,
        "organizations/organization_representation.html",
        context,
        status=status,
    )


def _my_invitations_page(
    request: HttpRequest,
    *,
    status: int = 200,
    action_error: str = "",
) -> TemplateResponse:
    actor = _account(request)
    load_failed = False
    try:
        appointments = tuple(
            RepresentationAppointment.objects.select_related(
                "representation",
                "representation__organization",
            )
            .filter(account=actor, state__in=_OPEN_APPOINTMENT_STATES)
            .order_by("-invited_at", "id")
        )
    except DatabaseError:
        logger.exception("Unable to load governance invitations")
        appointments = ()
        load_failed = True
        status = 503
    context = admin.site.each_context(request)
    context.update(
        {
            "title": "My governance invitations",
            "has_permission": True,
            "baseline_admin_parent_template": "admin/base_site.html",
            "baseline_use_admin_shell": True,
            "baseline_page_id": "my-representation-invitations",
            "baseline_page_class": "",
            "appointments": appointments,
            "invitation_load_failed": load_failed,
            "invitation_action_error": action_error,
        }
    )
    return TemplateResponse(
        request,
        "organizations/my_representation_invitations.html",
        context,
        status=status,
    )


@login_required(login_url="staff-login")
def my_representation_invitations(request: HttpRequest) -> HttpResponse:
    """List the authenticated person's own open representation terms.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.
    """
    return _my_invitations_page(request)


@login_required(login_url="staff-login")
def organization_representation(
    request: HttpRequest,
    organization_slug: str,
) -> HttpResponse:
    """Render organization representation.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    actor = _account(request)
    try:
        own_appointment = None
        if not actor.is_platform_administrator:
            own_appointment = (
                RepresentationAppointment.objects.select_related(
                    "representation__organization"
                )
                .filter(
                    account=actor,
                    state__in=_OPEN_APPOINTMENT_STATES,
                    representation__organization__slug__iexact=organization_slug,
                )
                .first()
            )
        organization = (
            own_appointment.representation.organization
            if own_appointment is not None
            else _authorized_organization_for_route(
                request=request,
                actor=actor,
                organization_slug=organization_slug,
                capability_codes=(
                    "organizations.view_basic",
                    "organizations.manage_representation",
                ),
            )
        )
    except DatabaseError:
        logger.exception("Unable to resolve organization representation scope")
        return _representation_dependency_failure(request)
    return _representation_page(request, organization=organization)


@login_required(login_url="staff-login")
@require_POST
def provision_organization_representation(
    request: HttpRequest,
    organization_slug: str,
) -> HttpResponse:
    """Render provision organization representation.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.

    Raises
    ------
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    actor = _account(request)
    if not actor.is_platform_administrator:
        _audit_denied_route(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            capability_code="organizations.manage_representation",
            operation="organizations.representation.provision",
        )
        raise PermissionDenied
    try:
        organization = get_object_or_404(
            Organization,
            slug__iexact=organization_slug,
        )
    except DatabaseError:
        logger.exception("Unable to resolve representation provisioning scope")
        return _representation_dependency_failure(request)
    form = RepresentationProvisionForm(request.POST)
    if not form.is_valid():
        return _representation_page(
            request,
            organization=organization,
            provision_form=form,
            status=400,
        )
    try:
        provision_representation(
            actor=actor,
            organization_id=organization.id,
            representation_code=str(form.cleaned_data["representation_code"]),
            reason=str(form.cleaned_data["reason"]),
            correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            source_channel="web",
        )
    except ValidationError as error:
        _add_validation_errors(form, error)
        return _representation_page(
            request,
            organization=organization,
            provision_form=form,
            status=_validation_status(error),
        )
    except DatabaseError:
        logger.exception("Unable to provision organization representation")
        form.add_error(
            None, "Governance could not be saved. No partial change was kept."
        )
        return _representation_page(
            request,
            organization=organization,
            provision_form=form,
            status=503,
        )
    created_definition = representation_definition(
        str(form.cleaned_data["representation_code"])
    )
    messages.success(
        request,
        (
            f"The {created_definition.name} representation was created."
            if created_definition is not None
            else "The accountable representation was created."
        ),
    )
    return redirect("organization-representation", organization_slug=organization.slug)


@login_required(login_url="staff-login")
@require_POST
def invite_organization_controller(
    request: HttpRequest,
    organization_slug: str,
) -> HttpResponse:
    """Render invite organization controller.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    actor = _account(request)
    try:
        organization = _authorized_organization_for_route(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            capability_codes=("organizations.manage_representation",),
        )
        representation = get_object_or_404(
            OrganizationRepresentation,
            organization=organization,
        )
    except DatabaseError:
        logger.exception("Unable to resolve representation invitation scope")
        return _representation_dependency_failure(request)
    form = RepresentationInviteForm(request.POST)
    if form.is_valid():
        try:
            account = Account.objects.filter(
                email__iexact=str(form.cleaned_data["account_email"]),
            ).first()
            if account is None:
                form.add_error("account_email", _GENERIC_ACCOUNT_INELIGIBLE)
            else:
                invite_representation_controller(
                    actor=actor,
                    representation_id=representation.id,
                    account_id=account.id,
                    reason=str(form.cleaned_data["reason"]),
                    correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
                    source_channel="web",
                )
        except ValidationError as error:
            _add_invitation_validation_errors(form, error)
            return _representation_page(
                request,
                organization=organization,
                invite_form=form,
                status=_validation_status(error),
            )
        except DatabaseError:
            logger.exception("Unable to invite accountable representation controller")
            form.add_error(
                None,
                "The invitation could not be saved. No partial change was kept.",
            )
            return _representation_page(
                request,
                organization=organization,
                invite_form=form,
                status=503,
            )
        else:
            if account is not None:
                messages.success(
                    request,
                    "The exact account was invited. They must sign in and accept.",
                )
                return redirect(
                    "organization-representation",
                    organization_slug=organization.slug,
                )
    return _representation_page(
        request,
        organization=organization,
        invite_form=form,
        status=400,
    )


@login_required(login_url="staff-login")
@require_POST
def respond_organization_controller_invitation(
    request: HttpRequest,
    organization_slug: str,
    appointment_id: UUID,
) -> HttpResponse:
    """Render respond organization controller invitation.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    appointment_id : UUID
        The identifier of the appointment.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    """
    actor = _account(request)
    try:
        appointment = RepresentationAppointment.objects.select_related(
            "representation__organization"
        ).get(id=appointment_id, account=actor)
    except RepresentationAppointment.DoesNotExist as error:
        _audit_denied_appointment(
            request=request,
            actor=actor,
            appointment_id=appointment_id,
        )
        raise Http404 from error
    except DatabaseError:
        logger.exception("Unable to resolve invitation response scope")
        return _representation_dependency_failure(request)
    organization = appointment.representation.organization
    if organization.slug.casefold() != organization_slug.casefold():
        _audit_denied_appointment(
            request=request,
            actor=actor,
            appointment_id=appointment_id,
            reason_code="tenant_scope_mismatch",
        )
        raise Http404
    form = RepresentationResponseForm(request.POST)
    if form.is_valid():
        try:
            respond_to_representation_invitation(
                actor=actor,
                appointment_id=appointment_id,
                expected_version=int(form.cleaned_data["expected_version"]),
                accept=form.cleaned_data["decision"] == "accept",
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
                source_channel="web",
            )
        except ValidationError as error:
            return _my_invitations_page(
                request,
                status=_validation_status(error),
                action_error=(
                    "This invitation changed before your response was saved. "
                    "Review its current state and try again if an action remains."
                ),
            )
        except (RepresentationAppointment.DoesNotExist, PermissionDenied) as error:
            _audit_denied_appointment(
                request=request,
                actor=actor,
                appointment_id=appointment_id,
            )
            raise Http404 from error
        except DatabaseError:
            logger.exception("Unable to answer representation invitation")
            return _my_invitations_page(
                request,
                status=503,
                action_error=(
                    "The response could not be saved. No partial change was kept."
                ),
            )
        else:
            messages.success(
                request,
                "Your accountable-access invitation was updated.",
            )
            return redirect("my-representation-invitations")
    return _representation_page(
        request,
        organization=organization,
        response_form=form,
        status=400,
    )


@login_required(login_url="staff-login")
@require_POST
def activate_organization_representation(
    request: HttpRequest,
    organization_slug: str,
) -> HttpResponse:
    """Activate organization representation.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.

    Raises
    ------
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    actor = _account(request)
    if not actor.is_platform_administrator:
        _audit_denied_route(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            capability_code="organizations.manage_representation",
            operation="organizations.representation.activate",
        )
        raise PermissionDenied
    try:
        organization = get_object_or_404(
            Organization,
            slug__iexact=organization_slug,
        )
        representation = get_object_or_404(
            OrganizationRepresentation,
            organization=organization,
        )
    except DatabaseError:
        logger.exception("Unable to resolve representation activation scope")
        return _representation_dependency_failure(request)
    form = RepresentationActivationForm(
        request.POST,
        organization=organization,
    )
    if form.is_valid():
        try:
            activate_representation(
                actor=actor,
                representation_id=representation.id,
                expected_version=int(form.cleaned_data["expected_version"]),
                reason=str(form.cleaned_data["reason"]),
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
                source_channel="web",
            )
        except ValidationError as error:
            _add_validation_errors(form, error)
            return _representation_page(
                request,
                organization=organization,
                activation_form=form,
                status=_validation_status(error),
            )
        except DatabaseError:
            logger.exception("Unable to activate accountable representation")
            form.add_error(
                None,
                (
                    "Activation failed safely. No membership or authority was "
                    "partially applied."
                ),
            )
            return _representation_page(
                request,
                organization=organization,
                activation_form=form,
                status=503,
            )
        else:
            definition = representation_definition(representation.code)
            messages.success(
                request,
                (
                    f"The {definition.name} and organization authority are now active."
                    if definition is not None
                    else "The representation and organization authority are now active."
                ),
            )
            return redirect(
                "organization-representation",
                organization_slug=organization.slug,
            )
    return _representation_page(
        request,
        organization=organization,
        activation_form=form,
        status=400,
    )
