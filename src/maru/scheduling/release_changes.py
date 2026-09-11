"""Native same-transaction source joins, not a public invalidation endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import connection, transaction

from maru.audit.mutation_evidence import AuditedMutation, require_audited_mutation

from .release_catalogs import ReleaseDependencyKind

if TYPE_CHECKING:
    from uuid import UUID


def record_identity_release_deactivation(evidence: AuditedMutation) -> None:
    """Join Identity's native emergency deactivation without foreign pointer locks.

    Parameters
    ----------
    evidence : AuditedMutation
        Exact live evidence from the already authorized Identity command.

    Raises
    ------
    ValidationError
        If native scope, target, operation or live transaction evidence is invalid.

    Notes
    -----
    Identity retains the account row lock before calling. No tracking row is
    created for an unused account. Database owner guards independently require
    the journal consequence before a tracked source change can commit.
    """
    require_audited_mutation(evidence)
    if (
        evidence.operation != "identity.account.emergency_deactivate"
        or evidence.target_type != "identity.account"
        or evidence.target_id is None
        or evidence.organization_id is not None
        or evidence.event_edition_id is not None
        or set(evidence.changed_fields) != {"is_active", "sessions"}
    ):
        raise ValidationError("Exact Identity deactivation evidence is required.")
    _record_change(
        kind=ReleaseDependencyKind.IDENTITY_ACCOUNT,
        source_id=evidence.target_id,
        evidence=evidence,
    )


def _record_change(
    *, kind: ReleaseDependencyKind, source_id: UUID, evidence: AuditedMutation
) -> None:
    require_audited_mutation(evidence)
    if not transaction.get_connection().in_atomic_block:
        raise ValidationError("Release source changes require their owner transaction.")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT public.maru_scheduling_record_native_release_change(%s, %s, %s)",
            [kind.value, source_id, evidence.audit_id],
        )


def record_programme_release_change(
    evidence: AuditedMutation, *, receipt_id: UUID
) -> None:
    """Join closed Programme source references from its exact native receipt.

    Parameters
    ----------
    evidence : AuditedMutation
        Live native Programme audit evidence, not a prior audit identifier.
    receipt_id : UUID
        Receipt just created by Programme; its owning SQL seam resolves sources.

    Raises
    ------
    ValidationError
        If native evidence is unavailable or source identity is unsupported.

    Notes
    -----
    Programme owns the closed receipt-to-source mapping and its database proof.
    Private working information, discussion and a new approved rendition do not
    withdraw an older exact release. No tracked source means no Scheduling write.
    """
    require_audited_mutation(evidence)
    if evidence.target_type != "programme.item" or not evidence.operation.startswith(
        "programme.command."
    ):
        raise ValidationError("Exact native Programme mutation evidence is required.")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT kind, source_id FROM "
            "public.maru_programme_release_mutation_sources(%s) "
            "ORDER BY kind, source_id",
            [receipt_id],
        )
        references = cursor.fetchall()
    for kind, source_id in references:
        _record_change(
            kind=ReleaseDependencyKind(kind), source_id=source_id, evidence=evidence
        )


def record_workforce_release_change(evidence: AuditedMutation) -> None:
    """Join exact Workforce receipts that affect retained future coverage.

    Parameters
    ----------
    evidence : AuditedMutation
        Exact live native Shift, availability or assignment-ending audit.

    Raises
    ------
    ValidationError
        If native attribution is unavailable or the owner identity is unsupported.

    Notes
    -----
    The Workforce SQL seam proves the exact receipt using native retry hash,
    actor, operation, target and scope. A commitment changes its own demand's
    generation; unrelated demand/edition pointers are never enumerated.
    """
    require_audited_mutation(evidence)
    if not evidence.operation.startswith("workforce."):
        raise ValidationError("Exact native Workforce mutation evidence is required.")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT DISTINCT kind, source_id FROM "
            "public.maru_workforce_release_mutation_sources(%s) "
            "ORDER BY kind, source_id",
            [evidence.audit_id],
        )
        references = cursor.fetchall()
    for kind, source_id in references:
        _record_change(
            kind=ReleaseDependencyKind(kind), source_id=source_id, evidence=evidence
        )


def record_venues_release_change(evidence: AuditedMutation) -> None:
    """Join native Venue physical changes without enumerating release pointers.

    Parameters
    ----------
    evidence : AuditedMutation
        Exact live Venue audit after its authorized source change and receipt.

    Raises
    ------
    ValidationError
        If native evidence or its closed source identity is unavailable.

    Notes
    -----
    Venue owns receipt attribution and physical-change classification. Its
    independent public booking projection does not withdraw Programme release
    evidence. The native command already holds canonical parent/source locks.
    """
    require_audited_mutation(evidence)
    if not evidence.operation.startswith("venues."):
        raise ValidationError("Exact native Venue mutation evidence is required.")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT DISTINCT kind, source_id FROM "
            "public.maru_venues_release_mutation_sources(%s) "
            "ORDER BY kind, source_id",
            [evidence.audit_id],
        )
        references = cursor.fetchall()
    for kind, source_id in references:
        _record_change(
            kind=ReleaseDependencyKind(kind), source_id=source_id, evidence=evidence
        )


def record_events_release_change(evidence: AuditedMutation) -> None:
    """Join native edition envelope changes or operational ending.

    Parameters
    ----------
    evidence : AuditedMutation
        Exact live Events audit after the authorized edition mutation.

    Raises
    ------
    ValidationError
        If native attribution or edition scope is unavailable.

    Notes
    -----
    The Events-owned classifier excludes ordinary Ready/Live progression and
    unrelated profile labels. The native source lock precedes its dependency.
    """
    require_audited_mutation(evidence)
    if (
        evidence.target_type != "events.event_edition"
        or evidence.target_id is None
        or evidence.target_id != evidence.event_edition_id
        or evidence.organization_id is None
    ):
        raise ValidationError("Exact native edition mutation evidence is required.")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT public.maru_events_release_change_valid(%s, %s, %s, %s)",
            [
                evidence.target_id,
                evidence.organization_id,
                evidence.event_edition_id,
                evidence.audit_id,
            ],
        )
        relevant = cursor.fetchone()[0]
    if relevant:
        _record_change(
            kind=ReleaseDependencyKind.EDITION_OPERATIONAL,
            source_id=evidence.target_id,
            evidence=evidence,
        )
