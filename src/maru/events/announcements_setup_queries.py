"""Platform-admitted standalone setup previews and exact original-actor receipts."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError

from maru.audit.services import AuditRecord, append_audit
from maru.events.adoption import adoption_profile
from maru.events.announcements_setup_inputs import AnnouncementsSetupMode
from maru.identity.models import Account
from maru.identity.queries import current_platform_administrator_is_available
from maru.organizations.announcements_setup_references import (
    AnnouncementsFoundationChoice,
    AnnouncementsSetupFoundationReference,
    announcements_setup_organization_choices,
    announcements_setup_series_choices,
    resolve_announcements_setup_foundation,
)

_PREVIEW_UNAVAILABLE = (
    "Announcements setup information is unavailable; no partial choices are shown."
)


@dataclass(frozen=True, slots=True)
class AnnouncementsSetupChoices:
    """Describe only the current admitted stage, without a personnel directory.

    Attributes
    ----------
    organizations, series
        Complete bounded choices for this stage; unused inventories are empty.
    foundation
        Exact selected original-source candidate, not authority or locked state.
    """

    organizations: tuple[AnnouncementsFoundationChoice, ...] = ()
    series: tuple[AnnouncementsFoundationChoice, ...] = ()
    foundation: AnnouncementsSetupFoundationReference | None = None


def require_announcements_setup_actor(actor: Account) -> None:
    """Admit a current platform principal only under the exact standalone profile.

    Parameters
    ----------
    actor : Account
        Actual authenticated platform account, never an alternate submitted actor.

    Raises
    ------
    PermissionDenied
        Before owner reads if the profile or current Identity authority is absent.
    """
    profile = adoption_profile("announcements_only", 1)
    if (
        profile is None
        or profile.key != ("announcements_only", 1)
        or not isinstance(actor, Account)
        or not actor.is_active
        or not actor.is_platform_administrator
        or not current_platform_administrator_is_available(account_id=actor.id)
    ):
        raise PermissionDenied("Announcements setup is unavailable.")


def _trace(value: UUID) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise ValidationError(
            "Use a non-empty trace.", code="announcements_setup_trace"
        )


def _audit(
    actor: Account,
    trace: UUID,
    organization_id: UUID | None,
    edition_id: UUID | None = None,
    receipt_id: UUID | None = None,
) -> None:
    require_announcements_setup_actor(actor)
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code="events.create",
            operation="events.announcements_adoption.setup.review",
            target_type="events.announcements_setup_receipt",
            target_id=receipt_id,
            outcome="allow",
            reason_code="platform_administration",
            correlation_id=trace,
            source_channel="html",
            obligations=("audit_sensitive_read",),
            retention_class="security-standard",
        )
    )


def load_announcements_setup_choices(
    *,
    actor: Account,
    correlation_id: UUID,
    mode: AnnouncementsSetupMode | None = None,
    organization_id: UUID | None = None,
    series_id: UUID | None = None,
) -> AnnouncementsSetupChoices:
    """Load one bounded labelled stage after current platform admission.

    Parameters
    ----------
    actor : Account
        Actual current platform principal.
    correlation_id : UUID
        Server-generated non-nil disclosure trace.
    mode : AnnouncementsSetupMode | None, default=None
        Closed route-owned create/reuse mode, or the initial organization selector.
    organization_id : UUID | None, default=None
        Exact route-owned reused parent, never inferred from a foreign series.
    series_id : UUID | None, default=None
        Exact active same-parent series selected by the route.

    Returns
    -------
    AnnouncementsSetupChoices
        Complete current stage after final admission and audit, never partial data.

    Raises
    ------
    PermissionDenied
        For absent authority/profile, invalid stage or unavailable exact foundation.
    ValidationError
        For invalid trace or bounded inventory overflow.
    """
    require_announcements_setup_actor(actor)
    _trace(correlation_id)
    if mode in (None, AnnouncementsSetupMode.NEW_FOUNDATION):
        if organization_id is not None or series_id is not None:
            raise PermissionDenied
        organizations = (
            () if mode is not None else announcements_setup_organization_choices()
        )
        if organizations is None:
            raise ValidationError(
                _PREVIEW_UNAVAILABLE, code="announcements_setup_preview_unavailable"
            )
        result = AnnouncementsSetupChoices(organizations=organizations)
    else:
        if (
            mode
            not in (
                AnnouncementsSetupMode.EXISTING_ORGANIZATION,
                AnnouncementsSetupMode.EXISTING_SERIES,
            )
            or not isinstance(organization_id, UUID)
            or organization_id.int == 0
            or (
                mode == AnnouncementsSetupMode.EXISTING_ORGANIZATION
                and series_id is not None
            )
            or (
                mode == AnnouncementsSetupMode.EXISTING_SERIES
                and (not isinstance(series_id, UUID) or series_id.int == 0)
            )
        ):
            raise PermissionDenied
        foundation = resolve_announcements_setup_foundation(
            organization_id=organization_id, series_id=series_id
        )
        if foundation is None:
            raise PermissionDenied("Announcements setup is unavailable.")
        series = (
            announcements_setup_series_choices(organization_id=organization_id)
            if mode == AnnouncementsSetupMode.EXISTING_ORGANIZATION
            else ()
        )
        if series is None:
            raise ValidationError(
                _PREVIEW_UNAVAILABLE, code="announcements_setup_preview_unavailable"
            )
        result = AnnouncementsSetupChoices(series=series, foundation=foundation)
    _audit(actor, correlation_id, organization_id)
    return result
