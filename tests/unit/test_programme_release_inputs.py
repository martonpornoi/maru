"""Exact typed placement decisions reject forged or unbounded input shapes."""

from dataclasses import FrozenInstanceError, asdict, replace
from itertools import product
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.programme.release_inputs import (
    MAX_PLACEMENT_DECISIONS,
    ProgrammePlacementDecisionIntent,
    ProgrammePlacementDecisionKind,
    ProgrammePlacementDecisionState,
    ProgrammePlacementSelection,
)


def _intent() -> ProgrammePlacementDecisionIntent:
    return ProgrammePlacementDecisionIntent(
        item_id=uuid4(),
        occurrence_id=uuid4(),
        candidate_id=uuid4(),
        candidate_revision_id=uuid4(),
        placement_id=uuid4(),
        expected_item_version=1,
        expected_candidate_version=2,
        expected_decision_sequence=1,
        source_digest="a" * 64,
        kind=ProgrammePlacementDecisionKind.ACCESSIBILITY_FIT,
        state=ProgrammePlacementDecisionState.SATISFIED,
    )


@pytest.mark.parametrize(
    ("kind", "state"),
    tuple(product(ProgrammePlacementDecisionKind, ProgrammePlacementDecisionState)),
)
def test_decision_preserves_exact_typed_intent(kind, state):
    intent = replace(_intent(), kind=kind, state=state)
    assert intent.validated() is intent
    with pytest.raises(FrozenInstanceError):
        intent.source_digest = "b" * 64


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (field, value)
        for field in (
            "item_id",
            "occurrence_id",
            "candidate_id",
            "candidate_revision_id",
            "placement_id",
        )
        for value in (None, "secret-do-not-disclose", 1)
    ]
    + [
        (field, value)
        for field in ("expected_item_version", "expected_candidate_version")
        for value in (None, True, 0, -1, "1", 1.5)
    ]
    + [
        ("expected_decision_sequence", value)
        for value in (None, True, -1, "1", 1.5, MAX_PLACEMENT_DECISIONS)
    ]
    + [("source_digest", value) for value in (None, "", "A" * 64, "a" * 63)]
    + [("kind", value) for value in (None, "accessibility_fit", "unknown")]
    + [("state", value) for value in (None, "satisfied", "unknown")],
)
def test_decision_rejects_invalid_shapes(field, value):
    with pytest.raises(ValidationError) as caught:
        replace(_intent(), **{field: value}).validated()
    assert "secret-do-not-disclose" not in str(caught.value)


def test_first_decision_and_last_available_sequence_are_explicit():
    assert replace(_intent(), expected_decision_sequence=0).validated()
    assert replace(
        _intent(), expected_decision_sequence=MAX_PLACEMENT_DECISIONS - 1
    ).validated()
    with pytest.raises(ValidationError):
        replace(
            _intent(),
            expected_decision_sequence=0,
            state=ProgrammePlacementDecisionState.WITHDRAWN,
        ).validated()


def test_history_limit_retains_one_terminal_withdrawal_slot():
    withdrawal = replace(
        _intent(),
        expected_decision_sequence=MAX_PLACEMENT_DECISIONS,
        state=ProgrammePlacementDecisionState.WITHDRAWN,
    )
    assert withdrawal.validated() is withdrawal
    with pytest.raises(ValidationError):
        replace(
            withdrawal, expected_decision_sequence=MAX_PLACEMENT_DECISIONS + 1
        ).validated()


@pytest.mark.parametrize("kind", list(ProgrammePlacementDecisionKind))
def test_preview_selection_is_strict_immutable_and_not_a_decision(kind):
    intent = _intent()
    selection = ProgrammePlacementSelection(
        **{
            key: value
            for key, value in asdict(intent).items()
            if key in ProgrammePlacementSelection.__dataclass_fields__
        }
    )
    selection = replace(selection, kind=kind)
    assert selection.validated() is selection
    with pytest.raises(FrozenInstanceError):
        selection.kind = kind
    for field, value in (
        ("item_id", "secret-do-not-disclose"),
        ("expected_item_version", True),
        ("expected_candidate_version", 0),
        ("kind", kind.value),
    ):
        with pytest.raises(ValidationError):
            replace(selection, **{field: value}).validated()
