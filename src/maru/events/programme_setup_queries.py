"""Platform-admitted dormant setup previews and exact original-actor receipts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError

from maru.audit.services import AuditRecord, append_audit
from maru.events.adoption import adoption_profile
from maru.events.models import EventEdition, ProgrammeAdoptionSetupReceipt
from maru.events.programme_setup_inputs import ProgrammeSetupMode
from maru.events.queries import EditionRouteIdentity, resolve_edition_route_identity
from maru.identity.models import Account
from maru.identity.queries import current_platform_administrator_is_available
from maru.organizations.programme_setup_references import (
    ProgrammeFoundationChoice,
    ProgrammeSetupFoundationReference,
    programme_setup_organization_choices,
    programme_setup_series_choices,
    resolve_programme_setup_foundation,
)
from maru.workforce.queries import resolve_current_department_label_reference

if TYPE_CHECKING:
    from datetime import date

_PREVIEW_UNAVAILABLE = (
    "Programme setup information is unavailable; no partial choices are shown."
)


@dataclass(frozen=True, slots=True)
class ProgrammeSetupChoices:
    """Describe only the current admitted stage, without a personnel directory.

    Attributes
    ----------
    organizations, series
        Complete bounded choices for this stage; unused inventories are empty.
    foundation
        Exact selected original-source candidate, not authority or locked state.
    """

    organizations: tuple[ProgrammeFoundationChoice, ...] = ()
    series: tuple[ProgrammeFoundationChoice, ...] = ()
    foundation: ProgrammeSetupFoundationReference | None = None


@dataclass(frozen=True, slots=True)
class ProgrammeSetupReceiptView:
    """Read original creation separately from current accountable-root status.

    Attributes
    ----------
    receipt_id, edition_id, department_id
        Exact original locators, not effective authority.
    foundation
        Currently coherent parent and representation facts, with no people.
    edition_name, department_name, starts_on, ends_on, time_zone
        Current independently admitted owner labels and edition dates/time zone.
    route
        Exact coherent owner slugs for the independently authorizing handoff.
    mode
        Original create/reuse choice, not inferred from today's parent state.
    """

    receipt_id: UUID
    edition_id: UUID
    department_id: UUID
    foundation: ProgrammeSetupFoundationReference
    edition_name: str
    department_name: str
    starts_on: date
    ends_on: date
    time_zone: str
    route: EditionRouteIdentity
    mode: ProgrammeSetupMode


def require_programme_setup_actor(actor: Account) -> None:
    """Admit a current platform principal only under the exact dormant profile.

    Parameters
    ----------
    actor : Account
        Actual authenticated platform account, never an alternate submitted actor.

    Raises
    ------
    PermissionDenied
        Before owner reads if the profile or current Identity authority is absent.
    """
    profile = adoption_profile("programme_operations", 1)
    if (
        profile is None
        or profile.key != ("programme_operations", 1)
        or not isinstance(actor, Account)
        or not actor.is_active
        or not actor.is_platform_administrator
        or not current_platform_administrator_is_available(account_id=actor.id)
    ):
        raise PermissionDenied("Programme setup is unavailable.")


def _trace(value: UUID) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise ValidationError("Use a non-empty trace.", code="programme_setup_trace")


def _audit(
    actor: Account,
    trace: UUID,
    organization_id: UUID | None,
    edition_id: UUID | None = None,
    receipt_id: UUID | None = None,
) -> None:
    require_programme_setup_actor(actor)
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code="events.create",
            operation="events.programme_adoption.setup.review",
            target_type="events.programme_setup_receipt",
            target_id=receipt_id,
            outcome="allow",
            reason_code="platform_administration",
            correlation_id=trace,
            source_channel="html",
            obligations=("audit_sensitive_read",),
            retention_class="security-standard",
        )
    )


def load_programme_setup_choices(
    *,
    actor: Account,
    correlation_id: UUID,
    mode: ProgrammeSetupMode | None = None,
    organization_id: UUID | None = None,
    series_id: UUID | None = None,
) -> ProgrammeSetupChoices:
    """Load one bounded labelled stage after current platform admission.

    Parameters
    ----------
    actor : Account
        Actual current platform principal.
    correlation_id : UUID
        Server-generated non-nil disclosure trace.
    mode : ProgrammeSetupMode | None, default=None
        Closed route-owned create/reuse mode, or the initial organization selector.
    organization_id : UUID | None, default=None
        Exact route-owned reused parent, never inferred from a foreign series.
    series_id : UUID | None, default=None
        Exact active same-parent series selected by the route.

    Returns
    -------
    ProgrammeSetupChoices
        Complete current stage after final admission and audit, never partial data.

    Raises
    ------
    PermissionDenied
        For absent authority/profile, invalid stage or unavailable exact foundation.
    ValidationError
        For invalid trace or bounded inventory overflow.
    """
    require_programme_setup_actor(actor)
    _trace(correlation_id)
    if mode in (None, ProgrammeSetupMode.NEW_FOUNDATION):
        if organization_id is not None or series_id is not None:
            raise PermissionDenied
        organizations = (
            () if mode is not None else programme_setup_organization_choices()
        )
        if organizations is None:
            raise ValidationError(
                _PREVIEW_UNAVAILABLE, code="programme_setup_preview_unavailable"
            )
        result = ProgrammeSetupChoices(organizations=organizations)
    else:
        if (
            mode
            not in (
                ProgrammeSetupMode.EXISTING_ORGANIZATION,
                ProgrammeSetupMode.EXISTING_SERIES,
            )
            or not isinstance(organization_id, UUID)
            or organization_id.int == 0
            or (
                mode == ProgrammeSetupMode.EXISTING_ORGANIZATION
                and series_id is not None
            )
            or (
                mode == ProgrammeSetupMode.EXISTING_SERIES
                and (not isinstance(series_id, UUID) or series_id.int == 0)
            )
        ):
            raise PermissionDenied
        foundation = resolve_programme_setup_foundation(
            organization_id=organization_id, series_id=series_id
        )
        if foundation is None:
            raise PermissionDenied("Programme setup is unavailable.")
        series = (
            programme_setup_series_choices(organization_id=organization_id)
            if mode == ProgrammeSetupMode.EXISTING_ORGANIZATION
            else ()
        )
        if series is None:
            raise ValidationError(
                _PREVIEW_UNAVAILABLE, code="programme_setup_preview_unavailable"
            )
        result = ProgrammeSetupChoices(series=series, foundation=foundation)
    _audit(actor, correlation_id, organization_id)
    return result


def load_programme_setup_receipt(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    receipt_id: UUID,
    correlation_id: UUID,
) -> ProgrammeSetupReceiptView:
    """Read only this original actor's exact retained result under current admission.

    Parameters
    ----------
    actor : Account
        Actual current platform principal who originally performed this setup.
    organization_id : UUID
        Exact original parent; another organization is never substituted.
    series_id : UUID
        Exact original convention in that parent.
    edition_id : UUID
        Exact Programme edition originally created by this setup.
    receipt_id : UUID
        Original actor-bound receipt; knowing its ID is not authority.
    correlation_id : UUID
        Server-generated non-nil disclosure trace.

    Returns
    -------
    ProgrammeSetupReceiptView
        Current minimized labels and root status, not operational readiness.

    Raises
    ------
    PermissionDenied
        For unavailable authority, original relationship or coherent exact scope.
    ValidationError
        For invalid trace or unavailable owner metadata without partial output.
    """
    require_programme_setup_actor(actor)
    _trace(correlation_id)
    if any(
        not isinstance(value, UUID) or value.int == 0
        for value in (organization_id, series_id, edition_id, receipt_id)
    ):
        raise PermissionDenied
    row = ProgrammeAdoptionSetupReceipt.objects.filter(
        id=receipt_id,
        actor_id=actor.id,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    ).first()
    if row is None:
        raise PermissionDenied("Programme setup is unavailable.")
    if row.mode not in tuple(ProgrammeSetupMode):
        raise ValidationError(
            _PREVIEW_UNAVAILABLE, code="programme_setup_preview_unavailable"
        )
    edition = EventEdition.objects.filter(
        id=edition_id,
        organization_id=organization_id,
        series_id=series_id,
        adoption_profile_code="programme_operations",
        adoption_profile_version=1,
    ).first()
    if edition is None:
        raise ValidationError(
            _PREVIEW_UNAVAILABLE, code="programme_setup_preview_unavailable"
        )
    foundation = resolve_programme_setup_foundation(
        organization_id=organization_id, series_id=series_id
    )
    route = resolve_edition_route_identity(
        organization_id=organization_id, series_id=series_id, edition_id=edition_id
    )
    department = resolve_current_department_label_reference(
        organization_id=organization_id,
        edition_id=edition_id,
        department_id=row.department_id,
    )
    if (
        foundation is None
        or route is None
        or foundation.representation_id != row.representation_id
    ):
        raise ValidationError(
            _PREVIEW_UNAVAILABLE, code="programme_setup_preview_unavailable"
        )
    result = ProgrammeSetupReceiptView(
        row.id,
        edition.id,
        row.department_id,
        foundation,
        edition.name,
        department.label if department else "Original Department currently unavailable",
        edition.starts_on,
        edition.ends_on,
        edition.time_zone,
        route,
        ProgrammeSetupMode(row.mode),
    )
    _audit(actor, correlation_id, organization_id, edition_id, receipt_id)
    return result
