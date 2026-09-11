"""Closed exact-source intent for accountable Programme placement decisions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from django.core.exceptions import ValidationError

from .inputs import (
    require_expected_version,
    require_positive_version,
    require_sha256,
    require_uuid,
)

if TYPE_CHECKING:
    from uuid import UUID

MAX_PLACEMENT_DECISIONS: Final = 1_000


class ProgrammePlacementDecisionKind(StrEnum):
    """Owner decisions that a generic readiness tick cannot establish."""

    ACCESSIBILITY_FIT = "accessibility_fit"
    STAFFING_NOT_REQUIRED = "staffing_not_required"


class ProgrammePlacementDecisionState(StrEnum):
    """Explicit assessment or withdrawal, never inferred from missing rows."""

    SATISFIED = "satisfied"
    BLOCKED = "blocked"
    WITHDRAWN = "withdrawn"


@dataclass(frozen=True, slots=True)
class ProgrammePlacementSelection:
    """Exact placement selection before an owner has produced a decision preview.

    Attributes
    ----------
    item_id
        Programme item requiring independent owner authority.
    occurrence_id
        Exact item-linked Scheduling occurrence.
    candidate_id
        Explicit alternative, never discovered from recent modification.
    candidate_revision_id
        Exact immutable selected manifest.
    placement_id
        Exact selected immutable placement.
    expected_item_version
        Current Programme item version.
    expected_candidate_version
        Current Scheduling candidate version.
    kind
        Closed accessibility-fit or no-staffing purpose.
    """

    item_id: UUID
    occurrence_id: UUID
    candidate_id: UUID
    candidate_revision_id: UUID
    placement_id: UUID
    expected_item_version: int
    expected_candidate_version: int
    kind: ProgrammePlacementDecisionKind

    def validated(self) -> ProgrammePlacementSelection:
        """Validate selection shape without granting access or interpreting sources.

        Returns
        -------
        ProgrammePlacementSelection
            The unchanged exact selection.

        Raises
        ------
        ValidationError
            If identity, versions or the closed purpose are invalid.
        """
        for field in (
            "item_id",
            "occurrence_id",
            "candidate_id",
            "candidate_revision_id",
            "placement_id",
        ):
            require_uuid(getattr(self, field), field=field)
        for field in ("expected_item_version", "expected_candidate_version"):
            require_positive_version(getattr(self, field), field=field)
        if type(self.kind) is not ProgrammePlacementDecisionKind:
            raise ValidationError(
                "Use a closed placement purpose.",
                code="programme_placement_decision_invalid",
            )
        return self


@dataclass(frozen=True, slots=True)
class ProgrammePlacementDecisionIntent:
    """Select an exact placement and compare a current owner-derived preview.

    Attributes
    ----------
    item_id
        Explicit Programme item whose owner authority must be checked.
    occurrence_id
        Exact Scheduling occurrence belonging to that item.
    candidate_id
        Explicit authorized alternative, not whichever draft changed last.
    candidate_revision_id
        Exact selected immutable manifest, retained as decision provenance.
    placement_id
        Exact immutable placement selected by the manifest.
    expected_item_version
        Current Programme item command version before the new intent.
    expected_candidate_version
        Current Scheduling alternative version before source comparison.
    expected_decision_sequence
        Current placement/kind decision sequence; zero means no prior decision.
    source_digest
        Owner-derived dependency fingerprint, not caller-supplied success facts.
    kind
        Closed placement assessment purpose.
    state
        Explicit owner conclusion or retained withdrawal.
    """

    item_id: UUID
    occurrence_id: UUID
    candidate_id: UUID
    candidate_revision_id: UUID
    placement_id: UUID
    expected_item_version: int
    expected_candidate_version: int
    expected_decision_sequence: int
    source_digest: str
    kind: ProgrammePlacementDecisionKind
    state: ProgrammePlacementDecisionState

    def validated(self) -> ProgrammePlacementDecisionIntent:
        """Validate typed bounded intent without reading or granting authority.

        Returns
        -------
        ProgrammePlacementDecisionIntent
            The unchanged immutable intent after strict structural validation.

        Raises
        ------
        ValidationError
            If identifiers, versions, digest or closed enum values are invalid.
        """
        for field in (
            "item_id",
            "occurrence_id",
            "candidate_id",
            "candidate_revision_id",
            "placement_id",
        ):
            require_uuid(getattr(self, field), field=field)
        require_positive_version(
            self.expected_item_version, field="expected_item_version"
        )
        require_positive_version(
            self.expected_candidate_version, field="expected_candidate_version"
        )
        require_expected_version(
            self.expected_decision_sequence, field="expected_decision_sequence"
        )
        require_sha256(self.source_digest, field="source_digest")
        if (
            type(self.kind) is not ProgrammePlacementDecisionKind
            or type(self.state) is not ProgrammePlacementDecisionState
            or self.expected_decision_sequence > MAX_PLACEMENT_DECISIONS
            or (
                self.expected_decision_sequence == MAX_PLACEMENT_DECISIONS
                and self.state != ProgrammePlacementDecisionState.WITHDRAWN
            )
            or (
                self.state == ProgrammePlacementDecisionState.WITHDRAWN
                and self.expected_decision_sequence == 0
            )
        ):
            raise ValidationError(
                "Use a closed bounded Programme placement decision.",
                code="programme_placement_decision_invalid",
            )
        return self
