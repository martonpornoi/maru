"""Pending internal effect accounting, never worker shutdown or payload disclosure."""

from collections.abc import Iterator
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.programme_stop_authorization import (
    require_programme_stop_controller,
)
from maru.authorization.services import AuthorizationDenied
from maru.events.programme_stop_inventory import (
    MAX_STOP_SOURCE_ROWS,
    ProgrammeStopInventory,
    ProgrammeStopMetadataSource,
    build_programme_stop_inventory,
)
from maru.events.programme_stop_readiness import programme_stop_preparation_is_ready

from . import models

# Event-envelope scope only. Payloads, lease tokens and errors are never selected.
STOP_METADATA_SOURCES = (
    ("DomainEvent", "", None, ("aggregate_version",)),
    (
        "OutboxMessage",
        "event__",
        "status",
        (
            "attempt_count",
            "max_attempts",
            "replay_count",
            "available_at",
            "lease_expires_at",
        ),
    ),
    ("EffectAttempt", "outbox_message__event__", "outcome", ("attempt_number",)),
    (
        "EffectReplayReceipt",
        "outbox_message__event__",
        None,
        ("replay_count", "new_max_attempts"),
    ),
)


def load_programme_stop_effects(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
) -> ProgrammeStopInventory:
    """Count edition-owned internal delivery evidence without invoking any worker.

    Parameters
    ----------
    actor_id : UUID
        Current ordinary accountable controller with Events transition authority.
    organization_id, edition_id : UUID
        Exact independently selected Programme context, never inferred from a file.
    correlation_id : UUID
        Trusted non-nil trace for mandatory minimized disclosure evidence.

    Returns
    -------
    ProgrammeStopInventory
        Complete counts and metadata fingerprint, without row identities, event
        payloads, lease tokens, handler errors or independently owned identity data.

    Raises
    ------
    ValidationError
        If the audit trace or native source integrity is unavailable.
    AuthorizationDenied
        If the actual controller lacks either independent stop prerequisite.

    Notes
    -----
    Overflow, source failure or audit failure returns no partial inventory. The
    composer must retain its outer canonical ownership/person transaction and
    rebuild this projection before stop. This purpose admits no source detail,
    export, review, retirement, withdrawal or payload-disposal command.
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
                operation="effects.query.programme_stop",
                target_type="events.event_edition",
                target_id=edition_id if allowed else None,
                outcome="allow" if allowed else "deny",
                reason_code="programme_stop_impact"
                if allowed
                else "programme_stop_unavailable",
                correlation_id=correlation_id,
                source_channel="programme-stop",
                obligations=("audit_sensitive_read",),
                retention_class="programme-restricted",
            )
        )

    try:
        with transaction.atomic():
            require_programme_stop_controller(**scope)
            if not programme_stop_preparation_is_ready():
                raise ValidationError(
                    "Programme stop source is unavailable.",
                    code="programme_stop_source",
                )

            def sources() -> Iterator[ProgrammeStopMetadataSource]:
                for name, parent, state_field, versions in STOP_METADATA_SOURCES:
                    model = getattr(models, name)
                    fields = (
                        "id",
                        "updated_at",
                        *((state_field,) if state_field else ()),
                        *versions,
                    )
                    query = model.objects.filter(
                        **{
                            f"{parent}organization_id": organization_id,
                            f"{parent}event_edition_id": edition_id,
                        }
                    )
                    if name in {"OutboxMessage", "EffectReplayReceipt"}:
                        query = query.filter(organization_id=organization_id)
                    if name == "OutboxMessage":
                        # Claim, completion and replay use these same owner rows.
                        # Workers resume after commit; no queue state is changed here.
                        query = query.select_for_update(of=("self",))
                    rows = tuple(
                        query.order_by("id").values_list(*fields)[
                            : MAX_STOP_SOURCE_ROWS + 1
                        ]
                    )
                    yield (
                        ProgrammeStopMetadataSource(
                            name.lower(), fields, rows, state_field
                        )
                    )

            result = build_programme_stop_inventory(
                owner="effects",
                organization_id=organization_id,
                edition_id=edition_id,
                sources=sources(),
            )
            require_programme_stop_controller(**scope)
            audit(allowed=True)
            return result
    except AuthorizationDenied:
        audit(allowed=False)
        raise
