"""Explicit work impact never rewrites or transfers retained volunteer decisions."""

from dataclasses import replace
from uuid import uuid4

import pytest

from maru.workforce.programme_impact import (
    ProgrammeStaffingAction as Action,
)
from maru.workforce.programme_impact import (
    ProgrammeStaffingDemandState,
    ProgrammeStaffingImpactError,
    evaluate_programme_staffing_impact,
)
from tests.unit.test_programme_staffing_inputs import expectation


@pytest.fixture
def demand():
    return ProgrammeStaffingDemandState(
        uuid4(), 4, "draft", expectation().normalized(), 0, 0, 0
    )


def impact(demand, action, **changes):
    return evaluate_programme_staffing_impact(
        action=action, expectation=replace(demand.expectation, **changes), demand=demand
    )


def test_creation_requires_no_existing_demand(demand):
    result = evaluate_programme_staffing_impact(
        action=Action.CREATE, expectation=demand.expectation, demand=None
    )
    assert (
        result.changed_fields,
        result.cancel_predecessor,
        result.retained_commitments,
    ) == ((), False, 0)
    with pytest.raises(ProgrammeStaffingImpactError):
        impact(demand, Action.CREATE)


@pytest.mark.parametrize("action", [Action.LINK, Action.RECONCILE, Action.SUCCESSOR])
def test_existing_actions_require_complete_demand(demand, action):
    with pytest.raises(ProgrammeStaffingImpactError):
        evaluate_programme_staffing_impact(
            action=action, expectation=demand.expectation, demand=None
        )


def test_link_never_changes_work_terms(demand):
    assert impact(demand, Action.LINK).changed_fields == ()
    with pytest.raises(ProgrammeStaffingImpactError):
        impact(demand, Action.LINK, briefing="Different work")


def test_reconciliation_lists_all_changed_person_facing_fields(demand):
    result = impact(
        demand,
        Action.RECONCILE,
        title="New title",
        required_headcount=3,
        minimum_rest_minutes=120,
        briefing="New explicit briefing",
    )
    assert result.changed_fields == (
        "title",
        "briefing",
        "required_headcount",
        "minimum_rest_minutes",
    )
    assert not result.cancel_predecessor
    assert (
        result.retained_commitments
        == result.claims_affected
        == result.confirmations_affected
        == 0
    )


@pytest.mark.parametrize("action", [Action.LINK, Action.RECONCILE])
@pytest.mark.parametrize("status", ["open", "locked", "cancelled", "completed"])
def test_non_draft_cannot_be_linked_or_reconciled_even_with_no_active_claims(
    demand, action, status
):
    with pytest.raises(ProgrammeStaffingImpactError):
        impact(replace(demand, status=status), action)


@pytest.mark.parametrize("action", [Action.LINK, Action.RECONCILE])
def test_removed_history_alone_prevents_link_or_reconcile(demand, action):
    with pytest.raises(ProgrammeStaffingImpactError):
        impact(replace(demand, retained_commitments=1), action)


def test_position_change_requires_successor_even_for_empty_draft(demand):
    with pytest.raises(ProgrammeStaffingImpactError):
        impact(demand, Action.RECONCILE, position_id=uuid4())
    result = impact(demand, Action.SUCCESSOR, position_id=uuid4())
    assert result.changed_fields == ("position_id",)
    assert result.cancel_predecessor


@pytest.mark.parametrize(
    ("status", "claimed", "confirmed", "cancel"),
    [
        ("draft", 0, 0, True),
        ("open", 1, 1, True),
        ("locked", 0, 2, True),
        ("cancelled", 0, 0, False),
        ("completed", 0, 0, False),
    ],
)
def test_successor_preserves_every_retained_decision_and_explains_cancellation(
    demand, status, claimed, confirmed, cancel
):
    original = replace(
        demand,
        status=status,
        retained_commitments=4,
        claimed=claimed,
        confirmed=confirmed,
    )
    result = impact(original, Action.SUCCESSOR, briefing="Separate successor work")
    assert result.cancel_predecessor is cancel
    assert result.retained_commitments == 4
    assert result.claims_affected == claimed
    assert result.confirmations_affected == confirmed
    assert original.expectation == demand.expectation
    assert original.claimed == claimed


@pytest.mark.parametrize("version", [1, 2, 100])
def test_lifecycle_version_alone_does_not_imply_changed_work_terms(demand, version):
    assert (
        impact(replace(demand, version=version), Action.RECONCILE).changed_fields == ()
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("demand_id", "not-uuid"),
        ("version", True),
        ("version", 0),
        ("version", 2**63 - 1),
        ("status", []),
        ("status", "unknown"),
        ("expectation", None),
        ("retained_commitments", True),
        ("retained_commitments", -1),
        ("retained_commitments", 4097),
        ("claimed", True),
        ("claimed", -1),
        ("confirmed", True),
        ("confirmed", -1),
    ],
)
def test_invalid_or_incomplete_demand_evidence_fails_closed(demand, field, value):
    with pytest.raises(ProgrammeStaffingImpactError):
        impact(
            replace(demand, **{field: value}), Action.SUCCESSOR
        ) if field != "expectation" else evaluate_programme_staffing_impact(
            action=Action.SUCCESSOR,
            expectation=demand.expectation,
            demand=replace(demand, expectation=None),
        )


@pytest.mark.parametrize(
    ("status", "retained", "claimed", "confirmed"),
    [
        ("draft", 1, 1, 0),
        ("draft", 1, 0, 1),
        ("locked", 1, 1, 0),
        ("cancelled", 1, 0, 1),
        ("completed", 1, 1, 0),
        ("open", 0, 1, 0),
        ("open", 3, 1, 2),
    ],
)
def test_inconsistent_state_or_counts_never_become_a_successful_preview(
    demand, status, retained, claimed, confirmed
):
    with pytest.raises(ProgrammeStaffingImpactError):
        impact(
            replace(
                demand,
                status=status,
                retained_commitments=retained,
                claimed=claimed,
                confirmed=confirmed,
            ),
            Action.SUCCESSOR,
        )


@pytest.mark.parametrize("action", ["create", "reconcile", "transfer", None, True])
def test_actions_must_be_explicit_closed_values(demand, action):
    with pytest.raises(ProgrammeStaffingImpactError):
        impact(demand, action)


def test_non_normalized_terms_are_not_silently_substituted(demand):
    with pytest.raises(ProgrammeStaffingImpactError):
        impact(demand, Action.RECONCILE, title="  silently trimmed  ")
