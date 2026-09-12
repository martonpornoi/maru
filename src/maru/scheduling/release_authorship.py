"""Private Scheduling-owned retained authorship closure for independent approval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import transaction

from .candidate_commands import _load_manifest
from .catalogs import MAX_CANDIDATE_REVISIONS, MAX_CANDIDATES
from .command_support import SchedulingUnavailableError
from .inputs import scheduling_digest
from .models import SchedulingCandidateRevision, SchedulingPlacementRevision

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class _ReleaseAuthorship:
    candidate_revision_id: UUID
    author_ids: frozenset[UUID]
    provenance_digest: str


def _history(
    head: SchedulingCandidateRevision,
    *,
    remaining: int,
) -> tuple[SchedulingCandidateRevision, ...]:
    if not 1 <= head.sequence <= remaining:
        raise SchedulingUnavailableError
    rows = tuple(
        SchedulingCandidateRevision.objects.filter(
            organization_id=head.organization_id,
            edition_id=head.edition_id,
            candidate_id=head.candidate_id,
            candidate__organization_id=head.organization_id,
            candidate__edition_id=head.edition_id,
            candidate__aggregate_version__gte=head.sequence,
            sequence__lte=head.sequence,
        )
        .order_by("sequence")
        .only(
            "id",
            "candidate_id",
            "sequence",
            "actor_id",
            "operation",
            "source_revision_id",
        )[: remaining + 1]
    )
    if (
        len(rows) != head.sequence
        or rows[-1].id != head.id
        or rows[0].actor_id != head.candidate.created_by_id
    ):
        raise SchedulingUnavailableError
    earlier = set()
    for sequence, row in enumerate(rows, 1):
        if row.sequence != sequence:
            raise SchedulingUnavailableError
        if sequence == 1:
            valid = (
                row.operation == "candidate_create" and row.source_revision_id is None
            ) or (
                row.operation == "candidate_copy" and row.source_revision_id is not None
            )
        elif row.operation == "candidate_restore":
            valid = row.source_revision_id in earlier
        else:
            valid = (
                row.operation
                in {"placement_set", "placement_remove", "candidate_archive"}
                and row.source_revision_id is None
            )
        if not valid:
            raise SchedulingUnavailableError
        earlier.add(row.id)
    return rows


def _scoped_revision(
    *, organization_id: UUID, edition_id: UUID, revision_id: UUID
) -> SchedulingCandidateRevision:
    row = (
        SchedulingCandidateRevision.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            id=revision_id,
            candidate__organization_id=organization_id,
            candidate__edition_id=edition_id,
        )
        .select_related("candidate")
        .only(
            "id",
            "organization_id",
            "edition_id",
            "candidate_id",
            "sequence",
            "placement_count",
            "manifest_digest",
            "candidate__created_by_id",
        )
        .first()
    )
    if row is None:
        raise SchedulingUnavailableError
    return row


def _load_release_authorship(
    *, organization_id: UUID, edition_id: UUID, candidate_revision_id: UUID
) -> _ReleaseAuthorship:
    """Collect bounded exact ancestry inside the admitted owner's locked transaction.

    Parameters
    ----------
    organization_id : UUID
        Exact already admitted organization scope.
    edition_id : UUID
        Exact already admitted and parent-locked edition.
    candidate_revision_id : UUID
        Immutable manifest independently selected by the release command.

    Returns
    -------
    _ReleaseAuthorship
        Private actor exclusions and a complete exact ancestry fingerprint.

    Raises
    ------
    SchedulingUnavailableError
        If outside a transaction or scope, membership, ancestry or bounds fail.

    Notes
    -----
    Only Scheduling's separately authorized release command may use this private
    collector. It grants no read authority and emits no public identity list.
    It retains all candidate contributors through each exact copied source,
    including removed/restored work and original selected-placement authors.
    Later edits to a source candidate are not retroactive authorship. Former
    contributors need not be active. Complete ancestry is bounded by the existing
    candidate count and a total MAX_CANDIDATE_REVISIONS metadata budget; overflow
    is unavailable, never a truncated independent-approval success.
    """
    if not transaction.get_connection().in_atomic_block:
        raise SchedulingUnavailableError
    root = _scoped_revision(
        organization_id=organization_id,
        edition_id=edition_id,
        revision_id=candidate_revision_id,
    )
    head = root
    seen_candidates: set[UUID] = set()
    history: dict[UUID, SchedulingCandidateRevision] = {}
    while True:
        if (
            head.candidate_id in seen_candidates
            or len(seen_candidates) >= MAX_CANDIDATES
        ):
            raise SchedulingUnavailableError
        seen_candidates.add(head.candidate_id)
        rows = _history(head, remaining=MAX_CANDIDATE_REVISIONS - len(history))
        history.update((row.id, row) for row in rows)
        source = rows[0].source_revision_id
        if source is None:
            break
        head = _scoped_revision(
            organization_id=organization_id, edition_id=edition_id, revision_id=source
        )
    manifest = _load_manifest(root)
    placement_ids = {placement for _, placement in manifest}
    introduced = dict(
        SchedulingPlacementRevision.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            id__in=placement_ids,
        ).values_list("id", "introduced_in_id")
    )
    if (
        set(introduced) != placement_ids
        or not set(introduced.values()) <= history.keys()
    ):
        raise SchedulingUnavailableError
    return _ReleaseAuthorship(
        root.id,
        frozenset(row.actor_id for row in history.values()),
        scheduling_digest(
            {
                "contract": "programme.release.authorship@1",
                "organization_id": str(organization_id),
                "edition_id": str(edition_id),
                "candidate_revision_id": str(root.id),
                "history": [
                    {
                        "revision_id": str(row.id),
                        "candidate_id": str(row.candidate_id),
                        "sequence": row.sequence,
                        "actor_id": str(row.actor_id),
                        "operation": row.operation,
                        "source_revision_id": str(row.source_revision_id)
                        if row.source_revision_id is not None
                        else None,
                    }
                    for row in sorted(history.values(), key=lambda row: str(row.id))
                ],
                "placements": [
                    {
                        "placement_id": str(identifier),
                        "introduced_in": str(introduced[identifier]),
                    }
                    for identifier in sorted(introduced, key=str)
                ],
            }
        ),
    )
