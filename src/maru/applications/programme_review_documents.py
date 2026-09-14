"""Closed, bounded decoding of proposed and retained review policy documents."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError

from .programme_review_inputs import (
    DECISION_OUTCOMES,
    MAX_REVIEW_STAGES,
    MAX_RUBRIC_CRITERIA,
    ProgrammeDecisionTemplateInput,
    ProgrammeReviewCriterionInput,
    ProgrammeReviewPolicyInput,
    ProgrammeReviewStageInput,
    _stage,
)


def _object(value: object, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValidationError("Use the complete closed review policy document.")
    return value


def _rows(value: object, maximum: int) -> list[Any]:
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        raise ValidationError("Use a nonempty bounded review policy list.")
    return value


def decode_review_stage(value: object) -> ProgrammeReviewStageInput:
    """Decode one complete stage without inventing quorum or score defaults.

    Parameters
    ----------
    value : object
        Untrusted JSON-compatible stage object with only the declared fields.

    Returns
    -------
    ProgrammeReviewStageInput
        Deeply immutable validated stage.
    """
    row = _object(
        value,
        {
            "code",
            "required_reviews",
            "criteria",
            "question_keys",
            "anonymous",
            "discussion",
        },
    )
    criteria = tuple(
        ProgrammeReviewCriterionInput(
            **_object(item, {"code", "label", "minimum", "maximum"})
        )
        for item in _rows(row["criteria"], MAX_RUBRIC_CRITERIA)
    )
    stage = ProgrammeReviewStageInput(
        **(
            row
            | {
                "criteria": criteria,
                "question_keys": tuple(_rows(row["question_keys"], 500)),
            }
        )
    )
    # The same owner normalization is used by preview and canonical writes.
    return _stage(stage)


def decode_review_policy(value: object) -> ProgrammeReviewPolicyInput:
    """Decode complete persisted or proposed policy through canonical validation.

    Parameters
    ----------
    value : object
        Closed JSON-compatible stages/templates object; no authority is implied.

    Returns
    -------
    ProgrammeReviewPolicyInput
        Immutable normalized policy with all four deliberate outcome templates.
    """
    row = _object(value, {"stages", "templates"})
    return ProgrammeReviewPolicyInput(
        tuple(
            decode_review_stage(item)
            for item in _rows(row["stages"], MAX_REVIEW_STAGES)
        ),
        tuple(
            ProgrammeDecisionTemplateInput(
                **_object(item, {"outcome", "text", "acknowledgement_required"})
            )
            for item in _rows(row["templates"], len(DECISION_OUTCOMES))
        ),
    ).normalized()
