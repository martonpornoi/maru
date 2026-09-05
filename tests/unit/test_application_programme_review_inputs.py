"""Closed policy, command, and event input regressions for Programme review."""

from dataclasses import replace
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.applications.models import ProgrammeReviewAction
from maru.applications.programme_review_events import (
    PROGRAMME_REVIEW_EVENT_ACTIONS,
    validate_programme_review_event,
)
from maru.applications.programme_review_inputs import (
    DECISION_OUTCOMES,
    ProgrammeDecisionTemplateInput,
    ProgrammeReviewCommandInput,
    ProgrammeReviewCriterionInput,
    ProgrammeReviewPolicyInput,
    ProgrammeReviewStageInput,
)


def review_policy():
    """Return explicit synthetic policy, not an application-level default quorum."""
    return ProgrammeReviewPolicyInput(
        stages=(
            ProgrammeReviewStageInput(
                code="content",
                required_reviews=2,
                criteria=(ProgrammeReviewCriterionInput("fit", "Programme fit", 0, 5),),
                question_keys=("session-title",),
                anonymous=True,
                discussion=True,
            ),
        ),
        templates=tuple(
            ProgrammeDecisionTemplateInput(
                outcome=outcome,
                text=f"Programme decision: {outcome}.",
                acknowledgement_required=True,
            )
            for outcome in sorted(DECISION_OUTCOMES)
        ),
    )


def test_review_policy_is_normalized_and_template_order_independent():
    policy = review_policy()
    reordered = replace(policy, templates=tuple(reversed(policy.templates)))
    assert policy.normalized() == reordered.normalized()
    assert policy.digest == reordered.digest
    assert (
        replace(policy, stages=(replace(policy.stages[0], required_reviews=3),)).digest
        != policy.digest
    )


@pytest.mark.parametrize("reviews", [0, 17, True, 1.0, "2"])
def test_review_quorum_requires_explicit_bounded_integer(reviews):
    policy = review_policy()
    with pytest.raises(ValidationError):
        replace(
            policy, stages=(replace(policy.stages[0], required_reviews=reviews),)
        ).normalized()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("stages", ()),
        ("templates", ()),
        ("stages", (review_policy().stages[0],) * 2),
        ("templates", (review_policy().templates[0],) * 4),
    ],
)
def test_review_policy_rejects_missing_or_duplicate_closed_parts(field, value):
    with pytest.raises(ValidationError):
        replace(review_policy(), **{field: value}).normalized()


@pytest.mark.parametrize(
    "criterion",
    [
        ProgrammeReviewCriterionInput("fit", "Fit", 5, 4),
        ProgrammeReviewCriterionInput("fit", "Fit", 0, 10_001),
        ProgrammeReviewCriterionInput("fit", "Fit", minimum=False, maximum=5),
        ProgrammeReviewCriterionInput("unsafe key", "Fit", 0, 5),
    ],
)
def test_review_criteria_reject_ambiguous_or_unbounded_values(criterion):
    policy = review_policy()
    with pytest.raises(ValidationError):
        replace(
            policy, stages=(replace(policy.stages[0], criteria=(criterion,)),)
        ).normalized()


@pytest.mark.parametrize(
    "scores", [(("fit", True),), (("fit", 2), ("fit", 3)), (), (("fit", 1, 2),)]
)
def test_review_scoring_requires_unique_typed_pairs(scores):
    with pytest.raises(ValidationError):
        ProgrammeReviewCommandInput(
            ProgrammeReviewAction.SCORED,
            uuid4(),
            reference_id=uuid4(),
            scores=scores,
        ).normalized()


def test_review_command_rejects_cross_action_data_and_normalizes_text():
    command = ProgrammeReviewCommandInput(
        ProgrammeReviewAction.ACKNOWLEDGED,
        uuid4(),
        reference_id=uuid4(),
    )
    assert command.normalized() == command
    with pytest.raises(ValidationError):
        replace(
            command, text="Do not smuggle a public decision through receipt."
        ).normalized()
    discussion = replace(
        command, action=ProgrammeReviewAction.DISCUSSED, text="  A bounded note.  "
    )
    assert discussion.normalized().text == "A bounded note."


def test_review_event_actions_match_the_model_vocabulary():
    assert set(ProgrammeReviewAction.values) == PROGRAMME_REVIEW_EVENT_ACTIONS


@pytest.mark.parametrize(
    "keys", [(), ("session-title",) * 2, ([],), (None,), ("unsafe key",)]
)
def test_stage_question_allowlist_rejects_empty_duplicate_or_untyped_keys(keys):
    policy = review_policy()
    with pytest.raises(ValidationError):
        replace(
            policy, stages=(replace(policy.stages[0], question_keys=keys),)
        ).normalized()


@pytest.mark.parametrize(
    "change",
    [
        {"action": "auto_accept"},
        {"resulting_version": True},
        {"resulting_version": "0"},
        {"resulting_version": "01"},
        {"resulting_version": "-1"},
        {"resulting_version": str(2**63)},
        {"resulting_version": "1.0"},
        {"aggregate_id": "unknown"},
        {"message": "Private decision text must not enter event payloads."},
    ],
)
def test_review_event_rejects_unknown_or_private_fields(change):
    payload = {
        "action": "scored",
        "aggregate_id": str(uuid4()),
        "resulting_version": "1",
    }
    validate_programme_review_event(payload)
    with pytest.raises(ValidationError):
        validate_programme_review_event(payload | change)
