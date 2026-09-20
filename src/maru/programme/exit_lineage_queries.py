"""Read explicitly ceilinged Programme archive lineage without foreign disclosure."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from maru.workforce.programme_references import lock_programme_staffing_scope

from . import models
from .archive_authorization import authorize_programme_archive_scope
from .authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_EXPORT_ARCHIVE,
    authorize_programme_scope,
)
from .exit_item_queries import _FIELDS
from .inputs import require_uuid
from .placement_queries import ProgrammePlacementReadRequest, _admit
from .queries import ProgrammeQueryUnavailableError, _authorized_query
from .release_inputs import ProgrammePlacementDecisionKind

if TYPE_CHECKING:
    from uuid import UUID

    from django.db.models import Model

    from .authorization import ProgrammeAuthorizer
    from .exit_core_queries import _Scope

type LineageValue = UUID | int | str | None

LINEAGE_CONTRACT: Final = "programme.exit-lineage@1"
MAX_LINEAGE_COLLECTION_ROWS: Final = 20_000
MAX_LINEAGE_ITEM_ROWS: Final = 50_000
_PURPOSE_FIELDS: Final = frozenset({"source_lineage"})


@dataclass(frozen=True, slots=True)
class ProgrammeExitLineageCollection:
    """Explicit owner-approved columns and restricted immutable identifier rows.

    Attributes
    ----------
    name, columns
        Closed archive schema keys, never names discovered from model metadata.
    rows
        Scoped original IDs, natural keys and versions; no authority to follow
        foreign references. Nullable references remain explicit nulls.
    """

    name: str
    columns: tuple[str, ...]
    rows: tuple[tuple[LineageValue, ...], ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class ProgrammeExitLineage:
    """One item's restricted lineage, not an independently complete exit archive.

    Attributes
    ----------
    item_id, item_version
        Exact selected item and its current aggregate version. Independent
        placement and withdrawal histories are included, not inferred from it.
    collections
        Complete bounded identifier-only collections in the declared schema order.
    """

    item_id: UUID = field(repr=False)
    item_version: int
    collections: tuple[ProgrammeExitLineageCollection, ...] = field(repr=False)


# This is an explicit owner schema, not introspection or a configurable ORM dump.
_COLLECTIONS: Final[tuple[tuple[str, type[Model], tuple[str, ...]], ...]] = (
    (
        "source_bindings",
        models.ProgrammeItemSourceBinding,
        ("id", "binding_code", "source_object_id", "source_version"),
    ),
    ("working", models.ProgrammeWorkingRevision, ("id", "sequence", "item_version")),
    ("delivery", models.ProgrammeDeliveryRevision, ("id", "sequence", "item_version")),
    (
        "discussion",
        models.ProgrammeDepartmentDiscussionEntry,
        ("id", "sequence", "item_version"),
    ),
    (
        "readiness_requirements",
        models.ProgrammeReadinessRequirement,
        ("id", "concern", "requirement_version", "dependency_version", "item_version"),
    ),
    (
        "readiness_revisions",
        models.ProgrammeReadinessRequirementRevision,
        ("id", "requirement_id", "sequence", "item_version"),
    ),
    (
        "readiness_evidence",
        models.ProgrammeReadinessEvidence,
        (
            "id",
            "requirement_id",
            "sequence",
            "item_version",
            "requirement_version",
            "dependency_version",
            "source_code",
            "source_object_id",
            "source_version",
        ),
    ),
    (
        "renditions",
        models.ProgrammePublicRendition,
        (
            "id",
            "rendition_number",
            "source_item_version",
            "source_working_revision_id",
            "supersedes_id",
        ),
    ),
    (
        "withdrawals",
        models.ProgrammePublicRenditionWithdrawal,
        ("id", "rendition_id", "item_version"),
    ),
    (
        "hosts",
        models.ProgrammeHostRelationship,
        (
            "id",
            "account_id",
            "version",
            "invitation_sequence",
            "availability_version",
            "item_version",
        ),
    ),
    (
        "host_revisions",
        models.ProgrammeHostRevision,
        ("id", "host_id", "sequence", "invitation_sequence", "item_version"),
    ),
    (
        "staffing_requirements",
        models.ProgrammeStaffingRequirement,
        ("id", "occurrence_id", "version", "item_version"),
    ),
    (
        "staffing_revisions",
        models.ProgrammeStaffingRevision,
        (
            "id",
            "requirement_id",
            "sequence",
            "item_version",
            "occurrence_version",
            "position_id",
        ),
    ),
    (
        "placement_decisions",
        models.ProgrammePlacementDecision,
        (
            "id",
            "occurrence_id",
            "candidate_revision_id",
            "placement_id",
            "kind",
            "sequence",
            "item_version",
            "delivery_revision_id",
            "space_selection_version",
        ),
    ),
)


def _admit_lineage(scope: _Scope, request: ProgrammePlacementReadRequest) -> None:
    authorize_programme_archive_scope(**scope, requested_fields=_PURPOSE_FIELDS)
    for capability, fields in _FIELDS:
        authorize_programme_scope(
            **scope, capability_code=capability, requested_fields=fields
        )
    for kind in ProgrammePlacementDecisionKind:
        _admit(request, kind, scope["authorizer"], history=True)


def load_programme_exit_lineage(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
    correlation_id: UUID,
    reason: str,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeExitLineage:
    """Collect explicit lineage under additional purpose and independent histories.

    Parameters
    ----------
    actor_id : UUID
        Actual authenticated requester, never a task-supplied substitute.
    organization_id : UUID
        Exact expected tenant, applied to every owned query.
    edition_id : UUID
        Exact expected edition, applied to every owned query.
    item_id : UUID
        Known item in that scope; no cross-scope discovery is performed.
    correlation_id : UUID
        Trusted trace for the required sensitive-read audit.
    reason : str
        Bounded sensitive-read rationale, validated by the ordinary query boundary.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Current owner policy with the existing sealed test replacement guard.

    Returns
    -------
    ProgrammeExitLineage
        All declared lineage collections, or refusal without partial disclosure.

    Notes
    -----
    Canonical parent/edition locks fence owned mutations, including independent
    placement and withdrawal changes. No person locks or foreign model reads are
    added. The composed archive must establish whole-edition person lock order
    before any content reader and recheck every source before later retrieval.
    Missing items, required evidence or supported complete bounds raise
    ProgrammeQueryUnavailableError from the protected loader.
    """
    item_id = require_uuid(item_id, field="item_id")
    scope: _Scope = {
        "actor_id": actor_id,
        "organization_id": organization_id,
        "edition_id": edition_id,
        "authorizer": authorizer,
    }
    request = ProgrammePlacementReadRequest(
        actor_id, organization_id, edition_id, correlation_id, "programme-exit"
    )

    def admit() -> None:
        _admit_lineage(scope, request)

    def collect() -> ProgrammeExitLineage:
        admit()
        lock_programme_staffing_scope(
            organization_id=organization_id, edition_id=edition_id
        )
        admit()
        item = (
            models.ProgrammeItem.objects.filter(
                id=item_id, organization_id=organization_id, edition_id=edition_id
            )
            .only("aggregate_version")
            .first()
        )
        if item is None:
            raise ProgrammeQueryUnavailableError
        collections = []
        total = 0
        for name, model, columns in _COLLECTIONS:
            rows = tuple(
                model._default_manager.filter(  # noqa: SLF001 - explicit owned models only
                    item_id=item_id,
                    organization_id=organization_id,
                    edition_id=edition_id,
                )
                .order_by("id")
                .values_list(*columns)[
                    : min(MAX_LINEAGE_COLLECTION_ROWS, MAX_LINEAGE_ITEM_ROWS - total)
                    + 1
                ]
            )
            total += len(rows)
            if (
                len(rows) > MAX_LINEAGE_COLLECTION_ROWS
                or total > MAX_LINEAGE_ITEM_ROWS
                or (name == "source_bindings" and len(rows) != 1)
                or (name == "working" and not rows)
            ):
                raise ProgrammeQueryUnavailableError
            collections.append(ProgrammeExitLineageCollection(name, columns, rows))
        admit()
        return ProgrammeExitLineage(item_id, item.aggregate_version, tuple(collections))

    return _authorized_query(
        **scope,
        capability_code=PROGRAMME_EXPORT_ARCHIVE,
        requested_fields=_PURPOSE_FIELDS,
        operation="programme.query.exit_lineage",
        loader=collect,
        target_type="programme.item",
        target_id=item_id,
        target_count=lambda result: sum(
            len(group.rows) for group in result.collections
        ),
        reason=reason,
        correlation_id=correlation_id,
        source_channel="programme-exit",
    )
