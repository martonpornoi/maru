"""Complete owner-controlled Programme stop preview under canonical shared locks."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import connection, transaction

from maru.applications.programme_stop_queries import load_programme_stop_applications
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.programme_stop_authorization import (
    require_programme_stop_controller,
    require_programme_stop_preflight,
)
from maru.authorization.programme_stop_queries import (
    ProgrammeStopAuthorityImpact,
    load_programme_stop_authority,
)
from maru.authorization.retired_targets import (
    lock_retired_department_authority_boundaries,
)
from maru.authorization.services import AuthorizationDenied
from maru.effects.programme_stop_queries import load_programme_stop_effects
from maru.identity.queries import lock_account_references_for_evidence
from maru.organizations.programme_setup_references import (
    lock_programme_setup_foundation,
    resolve_programme_setup_foundation,
)
from maru.programme.programme_stop_queries import load_programme_stop_content
from maru.scheduling.programme_stop_queries import (
    ProgrammeStopSchedulingImpact,
    load_programme_stop_scheduling,
)
from maru.scheduling.programme_stop_references import (
    resolve_programme_stop_release_people,
)
from maru.venues.programme_stop_queries import load_programme_stop_venues
from maru.workforce.programme_references import lock_programme_staffing_scope
from maru.workforce.programme_stop_queries import load_programme_stop_workforce

from .models import EventEdition
from .programme_stop_readiness import programme_stop_preparation_is_ready

if TYPE_CHECKING:
    from collections.abc import Iterator

    from .programme_stop_inventory import ProgrammeStopInventory

MAX_STOP_PREVIEW_BYTES = 4_194_304


def _unavailable() -> ValidationError:
    return ValidationError(
        "Programme stop is unavailable.", code="programme_stop_source"
    )


def _uuid_scalar(value: object) -> str:
    if type(value) is UUID:
        return str(value)
    raise TypeError("Unsupported stop preview value.")


@dataclass(frozen=True, slots=True)
class ProgrammeStopPreview:
    """Bind complete minimized consequences to the actual actor and Events version.

    Attributes
    ----------
    actor_id, organization_id, edition_id
        Exact actual requester and tenant context; identifiers grant no authority.
    lifecycle, aggregate_version, lifecycle_version
        Original active edition state that must still match at confirmation.
    authority
        Exact retained grant dispositions and unapproved intent counts.
    scheduling
        Actual release pointer and independent withdrawal prerequisite.
    inventories
        Complete Applications, Programme, Workforce, Venues and Effects metadata.
    """

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    lifecycle: str
    aggregate_version: int
    lifecycle_version: int
    authority: ProgrammeStopAuthorityImpact
    scheduling: ProgrammeStopSchedulingImpact
    inventories: tuple[ProgrammeStopInventory, ...]

    def canonical_bytes(self) -> bytes:
        """Encode one complete bounded purpose-versioned confirmation snapshot.

        Returns
        -------
        bytes
            Deterministic UTF-8 JSON without private source rows or release bytes.

        Raises
        ------
        ValidationError
            If the complete owner snapshot exceeds its retained evidence bound.
        """
        encoded = json.dumps(
            {"contract": "events.programme-stop-preview@1", **asdict(self)},
            default=_uuid_scalar,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        if len(encoded) > MAX_STOP_PREVIEW_BYTES:
            raise ValidationError(
                "Programme stop is unavailable.", code="programme_stop_source"
            )
        return encoded

    @property
    def fingerprint(self) -> str:
        """Return the complete original preview digest, never an authorization token."""
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def document(self) -> dict[str, Any]:
        """Copy the JSON-compatible minimized snapshot for immutable receipt storage.

        Returns
        -------
        dict[str, Any]
            Fresh independent JSON data; mutating it cannot change this preview.
        """
        return json.loads(self.canonical_bytes())  # type: ignore[no-any-return]


@contextmanager
def _locked_stop_scope(
    *, actor_id: UUID, organization_id: UUID, edition_id: UUID
) -> Iterator[EventEdition]:
    scope = {
        "actor_id": actor_id,
        "organization_id": organization_id,
        "edition_id": edition_id,
    }
    require_programme_stop_preflight(**scope)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_isolation")
            if cursor.fetchone() != ("read committed",):
                raise _unavailable()
        lock_retired_department_authority_boundaries()
        foundation = resolve_programme_setup_foundation(organization_id=organization_id)
        if foundation is None:
            raise _unavailable()
        retained = lock_programme_setup_foundation(
            organization_id=organization_id, expected_fingerprint=foundation.fingerprint
        )
        if (
            retained is None
            or retained.organization_lifecycle != "active"
            or retained.representation_state != "active"
        ):
            raise _unavailable()
        lock_programme_staffing_scope(
            organization_id=organization_id, edition_id=edition_id
        )
        people = resolve_programme_stop_release_people(**scope)
        if lock_account_references_for_evidence(account_ids=people) != people:
            raise _unavailable()
        require_programme_stop_controller(**scope)
        if not programme_stop_preparation_is_ready():
            raise _unavailable()
        yield EventEdition.objects.get(id=edition_id, organization_id=organization_id)


def _collect_locked_preview(
    *, actor_id: UUID, edition: EventEdition, correlation_id: UUID
) -> ProgrammeStopPreview:
    if edition.lifecycle not in {"draft", "preparing", "ready", "live", "closing"}:
        raise ValidationError(
            "Programme is already stopped.", code="programme_stop_lifecycle_conflict"
        )
    scope = {
        "actor_id": actor_id,
        "organization_id": edition.organization_id,
        "edition_id": edition.id,
        "correlation_id": correlation_id,
    }
    authority = load_programme_stop_authority(**scope)
    scheduling = load_programme_stop_scheduling(**scope)
    inventories = (
        load_programme_stop_applications(**scope),
        load_programme_stop_content(**scope),
        load_programme_stop_workforce(**scope),
        load_programme_stop_venues(**scope),
        load_programme_stop_effects(**scope),
    )
    require_programme_stop_controller(
        actor_id=actor_id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
    )
    preview = ProgrammeStopPreview(
        actor_id,
        edition.organization_id,
        edition.id,
        edition.lifecycle,
        edition.aggregate_version,
        edition.lifecycle_version,
        authority,
        scheduling,
        inventories,
    )
    preview.canonical_bytes()
    return preview


def load_programme_stop_preview(
    *, actor_id: UUID, organization_id: UUID, edition_id: UUID, correlation_id: UUID
) -> ProgrammeStopPreview:
    """Return a complete accountable stop preview without performing any consequence.

    Parameters
    ----------
    actor_id : UUID
        Actual ordinary controller with independent Events transition authority.
    organization_id, edition_id : UUID
        Exact Programme context, never discovered through private identifiers.
    correlation_id : UUID
        Trusted non-nil trace for minimized read evidence.

    Returns
    -------
    ProgrammeStopPreview
        All seven owner projections under retained canonical scope/person locks.

    Raises
    ------
    ValidationError
        If trace, complete source, bounds or active lifecycle is unavailable.

    Notes
    -----
    Each owner independently admits, rechecks and audits its own field ceiling.
    Missing withdrawal authority is an explicit prerequisite, not permission to
    substitute another actor. Confirmation must rebuild the whole snapshot and
    reject changed impact; the preview never changes a pointer, grant or lifecycle.
    """
    if type(correlation_id) is not UUID or not correlation_id.int:
        raise ValidationError("Use an exact audit trace.", code="programme_stop_trace")
    scope = {
        "actor_id": actor_id,
        "organization_id": organization_id,
        "edition_id": edition_id,
    }

    def audit(*, allowed: bool) -> None:
        append_audit(
            AuditRecord(
                principal_kind="account",
                principal_id=actor_id,
                principal_context_id=None,
                organization_id=organization_id,
                event_edition_id=edition_id,
                capability_code="events.transition",
                operation="events.query.programme_stop",
                target_type="events.event_edition",
                target_id=edition_id if allowed else None,
                outcome="allow" if allowed else "deny",
                reason_code="programme_stop_preview"
                if allowed
                else "programme_stop_unavailable",
                correlation_id=correlation_id,
                source_channel="programme-stop",
                obligations=("audit_sensitive_read",),
                retention_class="programme-restricted",
            )
        )

    try:
        with _locked_stop_scope(**scope) as edition:
            preview = _collect_locked_preview(
                actor_id=actor_id, edition=edition, correlation_id=correlation_id
            )
            audit(allowed=True)
    except AuthorizationDenied:
        audit(allowed=False)
        raise
    return preview
