"""Bounded typed inputs for exact-revision Programme review commands."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, replace
from typing import TYPE_CHECKING, Final

from django.core.exceptions import ValidationError

from maru.applications.models import ProgrammeReviewAction, ProgrammeReviewState
from maru.applications.programme_inputs import (
    canonical_programme_digest,
    normalized_programme_text,
    require_programme_uuid,
)

if TYPE_CHECKING:
    from typing import Never
    from uuid import UUID

MAX_REVIEW_STAGES: Final = 8
MAX_STAGE_REVIEWERS: Final = 16
MAX_RUBRIC_CRITERIA: Final = 16
MAX_RUBRIC_BOUND: Final = 10_000
MAX_REVIEW_REASON: Final = 2_000
MAX_DECISION_TEXT: Final = 3_000
_SCORE_PAIR_LENGTH: Final = 2
_CODE: Final = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
DECISION_OUTCOMES: Final = frozenset(ProgrammeReviewState.values) - {"open"}


def _invalid() -> Never:
    raise ValidationError(
        "Use the complete bounded review input for this action.",
        code="applications_programme_review_input_invalid",
    )


def _integer(value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _invalid()
    return value


def _code(value: str) -> str:
    if not isinstance(value, str) or _CODE.fullmatch(value) is None:
        _invalid()
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        _invalid()
    return value


def _collection(value: tuple[object, ...], maximum: int) -> None:
    if not isinstance(value, tuple) or not 1 <= len(value) <= maximum:
        _invalid()


@dataclass(frozen=True, slots=True)
class ProgrammeReviewCriterionInput:
    """Declare one rubric criterion with explicit, inclusive integer bounds.

    Attributes
    ----------
    code
        Stable criterion identifier within a stage.
    label
        Bounded reviewer-facing criterion text.
    minimum
        Explicit inclusive lower score bound.
    maximum
        Explicit inclusive upper score bound.
    """

    code: str
    label: str
    minimum: int
    maximum: int


@dataclass(frozen=True, slots=True)
class ProgrammeReviewStageInput:
    """Configure an ordered review stage without an implicit scoring policy.

    Attributes
    ----------
    code
        Stable stage identifier within the policy.
    required_reviews
        Explicit required count of independent complete reviews.
    criteria
        Nonempty immutable rubric specification.
    question_keys
        Explicit nonempty allowlist of sealed call questions for this stage.
    anonymous
        Whether structured contributor identity is withheld from reviewers.
    discussion
        Whether scored reviewers may exchange separate peer discussion.
    """

    code: str
    required_reviews: int
    criteria: tuple[ProgrammeReviewCriterionInput, ...]
    question_keys: tuple[str, ...]
    anonymous: bool
    discussion: bool


@dataclass(frozen=True, slots=True)
class ProgrammeDecisionTemplateInput:
    """Pin plain recipient text and acknowledgement policy for one outcome.

    Attributes
    ----------
    outcome
        One closed final or wait-list outcome.
    text
        Plain text without interpolation or private-field substitution.
    acknowledgement_required
        Whether each exact recipient may acknowledge receipt.
    """

    outcome: str
    text: str
    acknowledgement_required: bool


@dataclass(frozen=True, slots=True)
class ProgrammeReviewPolicyInput:
    """Supply the complete immutable policy copied into a review case.

    Attributes
    ----------
    stages
        Explicitly ordered stage definitions.
    templates
        Exactly one template for each supported decision outcome.
    """

    stages: tuple[ProgrammeReviewStageInput, ...]
    templates: tuple[ProgrammeDecisionTemplateInput, ...]

    def normalized(self) -> ProgrammeReviewPolicyInput:
        """Validate and normalize every bounded stage, criterion, and template.

        Returns
        -------
        ProgrammeReviewPolicyInput
            A deeply immutable normalized policy with complete outcome coverage.
        """
        _collection(self.stages, MAX_REVIEW_STAGES)
        stages = tuple(_stage(stage) for stage in self.stages)
        if len({stage.code for stage in stages}) != len(stages):
            _invalid()
        _collection(self.templates, len(DECISION_OUTCOMES))
        templates = tuple(_template(template) for template in self.templates)
        if {template.outcome for template in templates} != DECISION_OUTCOMES:
            _invalid()
        return ProgrammeReviewPolicyInput(
            stages, tuple(sorted(templates, key=lambda template: template.outcome))
        )

    @property
    def digest(self) -> str:
        """Return the canonical digest of the normalized complete policy.

        Returns
        -------
        str
            Lowercase SHA-256 policy identity.
        """
        return canonical_programme_digest(asdict(self.normalized()))


def _stage(stage: ProgrammeReviewStageInput) -> ProgrammeReviewStageInput:
    if not isinstance(stage, ProgrammeReviewStageInput):
        _invalid()
    _collection(stage.criteria, MAX_RUBRIC_CRITERIA)
    criteria = tuple(_criterion(criterion) for criterion in stage.criteria)
    if len({criterion.code for criterion in criteria}) != len(criteria):
        _invalid()
    _collection(stage.question_keys, 500)
    if any(
        not isinstance(key, str) or re.fullmatch(r"[a-z][a-z0-9_-]{0,79}", key) is None
        for key in stage.question_keys
    ) or len(set(stage.question_keys)) != len(stage.question_keys):
        _invalid()
    return ProgrammeReviewStageInput(
        code=_code(stage.code),
        required_reviews=_integer(stage.required_reviews, 1, MAX_STAGE_REVIEWERS),
        criteria=criteria,
        question_keys=tuple(sorted(stage.question_keys)),
        anonymous=_boolean(stage.anonymous),
        discussion=_boolean(stage.discussion),
    )


def _criterion(value: ProgrammeReviewCriterionInput) -> ProgrammeReviewCriterionInput:
    if not isinstance(value, ProgrammeReviewCriterionInput):
        _invalid()
    return ProgrammeReviewCriterionInput(
        code=_code(value.code),
        label=normalized_programme_text(
            value.label, field="criterion", maximum=200, required=True
        ),
        minimum=_integer(value.minimum, 0, MAX_RUBRIC_BOUND),
        maximum=_integer(value.maximum, value.minimum, MAX_RUBRIC_BOUND),
    )


def _template(value: ProgrammeDecisionTemplateInput) -> ProgrammeDecisionTemplateInput:
    if not isinstance(value, ProgrammeDecisionTemplateInput):
        _invalid()
    if not isinstance(value.outcome, str) or value.outcome not in DECISION_OUTCOMES:
        _invalid()
    return ProgrammeDecisionTemplateInput(
        outcome=value.outcome,
        text=normalized_programme_text(
            value.text,
            field="template",
            maximum=MAX_DECISION_TEXT,
            required=True,
            multiline=True,
        ),
        acknowledgement_required=_boolean(value.acknowledgement_required),
    )


@dataclass(frozen=True, slots=True)
class ProgrammeReviewCommandInput:
    """Declare one closed review intent; irrelevant optional fields are rejected.

    Attributes
    ----------
    action
        The exact registered review transition.
    target_id
        Call for policy creation, proposal for case opening, otherwise review case.
    policy
        Complete policy only for policy creation.
    policy_id
        Exact immutable policy only when opening a review case.
    reference_id
        Reviewer account, assignment, or decision for its specific action.
    scores
        Ordered criterion/value pairs only for a scoring action.
    outcome
        Closed outcome only for a decision action.
    text
        Deliberate peer discussion or recipient-visible decision text.
    stage
        Exact earlier stage only for explicit reasoned stage reopening.
    """

    action: ProgrammeReviewAction
    target_id: UUID
    policy: ProgrammeReviewPolicyInput | None = None
    policy_id: UUID | None = None
    reference_id: UUID | None = None
    scores: tuple[tuple[str, int], ...] = ()
    outcome: str = ""
    text: str = ""
    stage: int | None = None

    def normalized(self) -> ProgrammeReviewCommandInput:
        """Reject foreign action fields and normalize the exact intended payload.

        Returns
        -------
        ProgrammeReviewCommandInput
            Validated immutable input suitable for an idempotency digest.
        """
        if not isinstance(self.action, ProgrammeReviewAction):
            _invalid()
        require_programme_uuid(self.target_id, field="target_id")
        allowed = _ACTION_FIELDS[self.action]
        defaults: dict[str, object] = {
            "policy": None,
            "policy_id": None,
            "reference_id": None,
            "scores": (),
            "outcome": "",
            "text": "",
            "stage": None,
        }
        for field, default in defaults.items():
            if field not in allowed and getattr(self, field) != default:
                _invalid()
        for field in {"policy_id", "reference_id"} & allowed:
            require_programme_uuid(getattr(self, field), field=field)
        if "stage" in allowed:
            _integer(self.stage, 0, MAX_REVIEW_STAGES - 1)
        policy = self.policy
        if "policy" in allowed:
            if not isinstance(policy, ProgrammeReviewPolicyInput):
                _invalid()
            policy = policy.normalized()
        scores = self.scores
        if "scores" in allowed:
            _collection(scores, MAX_RUBRIC_CRITERIA)
            for pair in scores:
                if not isinstance(pair, tuple) or len(pair) != _SCORE_PAIR_LENGTH:
                    _invalid()
                _code(pair[0])
                _integer(pair[1], 0, MAX_RUBRIC_BOUND)
            if len({pair[0] for pair in scores}) != len(scores):
                _invalid()
            scores = tuple(sorted(scores))
        if "outcome" in allowed and (
            not isinstance(self.outcome, str) or self.outcome not in DECISION_OUTCOMES
        ):
            _invalid()
        text = normalized_programme_text(
            self.text,
            field="text",
            maximum=MAX_DECISION_TEXT,
            required="text" in allowed,
            multiline=True,
        )
        return replace(self, policy=policy, scores=scores, text=text)


_ACTION_FIELDS: Final = {
    ProgrammeReviewAction.POLICY_CREATED: frozenset({"policy"}),
    ProgrammeReviewAction.CASE_OPENED: frozenset({"policy_id"}),
    ProgrammeReviewAction.REVIEWER_ASSIGNED: frozenset({"reference_id"}),
    ProgrammeReviewAction.CONFLICT_CLEARED: frozenset({"reference_id"}),
    ProgrammeReviewAction.REVIEWER_RECUSED: frozenset({"reference_id"}),
    ProgrammeReviewAction.REVIEWER_REMOVED: frozenset({"reference_id"}),
    ProgrammeReviewAction.SCORED: frozenset({"reference_id", "scores"}),
    ProgrammeReviewAction.DISCUSSED: frozenset({"reference_id", "text"}),
    ProgrammeReviewAction.MODERATED: frozenset(),
    ProgrammeReviewAction.STAGE_ADVANCED: frozenset(),
    ProgrammeReviewAction.STAGE_REOPENED: frozenset({"stage"}),
    ProgrammeReviewAction.DECIDED: frozenset({"outcome", "text"}),
    ProgrammeReviewAction.ACKNOWLEDGED: frozenset({"reference_id"}),
}
