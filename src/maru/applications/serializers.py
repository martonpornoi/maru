"""Closed request and purpose-limited response schemas for applications."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar, Literal, cast
from uuid import UUID

from django_stubs_ext import StrOrPromise
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from maru.applications.models import (
    ApplicationClassification,
    ApplicationEligibilityKind,
    ApplicationQuestionType,
    ApplicationSubmission,
)
from maru.core.openapi import CANONICAL_UUID_SCHEMA

MAX_REPORTED_NESTED_UNKNOWN_FIELDS = 5


def _reject_unknown_nested_fields(
    data: object,
    *,
    allowed_fields: frozenset[str],
) -> None:
    if not isinstance(data, Mapping):
        return
    unknown = sorted(
        str(field_name) for field_name in data if field_name not in allowed_fields
    )
    if not unknown:
        return
    visible = ", ".join(unknown[:MAX_REPORTED_NESTED_UNKNOWN_FIELDS])
    if len(unknown) > MAX_REPORTED_NESTED_UNKNOWN_FIELDS:
        visible = (
            f"{visible}, and {len(unknown) - MAX_REPORTED_NESTED_UNKNOWN_FIELDS} more"
        )
    raise serializers.ValidationError(
        {"non_field_errors": [f"Remove unsupported input fields: {visible}."]},
        code="unknown_input_field",
    )


@extend_schema_field(CANONICAL_UUID_SCHEMA)
class CanonicalUUIDField(serializers.UUIDField):
    default_error_messages: ClassVar[dict[str, StrOrPromise]] = {
        "invalid": "Enter a canonical lower-case hyphenated UUID."
    }

    def to_internal_value(self, data: object) -> UUID:
        value = super().to_internal_value(cast(UUID | str | int, data))
        if not isinstance(data, str) or str(value) != data:
            self.fail("invalid")
        return value


class StarterCreateSerializer(serializers.Serializer[dict[str, Any]]):
    starter_code = serializers.SlugField(max_length=80)
    opens_at = serializers.DateTimeField()
    closes_at = serializers.DateTimeField()
    applicant_edit_until = serializers.DateTimeField()


class DefinitionConfigureSerializer(serializers.Serializer[dict[str, Any]]):
    operation = serializers.ChoiceField(choices=("definition.configure",))
    expected_version = serializers.IntegerField(min_value=1)
    name = serializers.CharField(max_length=160)
    description = serializers.CharField(max_length=4_000, allow_blank=True)
    purpose = serializers.CharField(max_length=500)
    classification = serializers.ChoiceField(choices=ApplicationClassification.choices)
    eligibility_kind = serializers.ChoiceField(
        choices=ApplicationEligibilityKind.choices
    )
    maximum_submissions = serializers.IntegerField(min_value=1, max_value=100)
    opens_at = serializers.DateTimeField()
    closes_at = serializers.DateTimeField()
    applicant_edit_until = serializers.DateTimeField()
    minimum_age = serializers.IntegerField(min_value=0, max_value=120)
    audience_policy_code = serializers.RegexField(
        r"^[a-z][a-z0-9_.:-]{2,119}$", allow_blank=True
    )
    retention_policy_code = serializers.RegexField(
        r"^[a-z][a-z0-9_.:-]{2,119}$", allow_blank=True
    )
    age_policy_code = serializers.RegexField(
        r"^[a-z][a-z0-9_.:-]{2,119}$", allow_blank=True
    )
    owner_department_ids = serializers.ListField(
        child=CanonicalUUIDField(), max_length=32
    )
    reviewer_role_bundle_ids = serializers.ListField(
        child=CanonicalUUIDField(), max_length=32
    )
    reviewer_account_ids = serializers.ListField(
        child=CanonicalUUIDField(), max_length=32
    )
    reason = serializers.CharField(max_length=240)


class SectionAddSerializer(serializers.Serializer[dict[str, Any]]):
    operation = serializers.ChoiceField(choices=("section.add",))
    expected_version = serializers.IntegerField(min_value=1)
    key = serializers.SlugField(max_length=80)
    title = serializers.CharField(max_length=160)
    help_text = cast(
        StrOrPromise | None,
        serializers.CharField(max_length=2_000, allow_blank=True),
    )
    reason = serializers.CharField(max_length=240)


class QuestionOptionSerializer(serializers.Serializer[dict[str, str]]):
    code = serializers.RegexField(r"^[a-z][a-z0-9_-]{0,79}$")
    label = cast(StrOrPromise | None, serializers.CharField(max_length=160))

    def to_internal_value(self, data: object) -> dict[str, str]:
        _reject_unknown_nested_fields(
            data,
            allowed_fields=frozenset(self.fields),
        )
        return cast(dict[str, str], super().to_internal_value(data))


class QuestionConditionSerializer(serializers.Serializer[dict[str, Any]]):
    question_key = serializers.SlugField(max_length=80)
    operator = serializers.ChoiceField(choices=("equals", "not_equals", "contains"))
    value = serializers.JSONField()

    def to_internal_value(self, data: object) -> dict[str, Any]:
        _reject_unknown_nested_fields(
            data,
            allowed_fields=frozenset(self.fields),
        )
        return cast(dict[str, Any], super().to_internal_value(data))


class QuestionAddSerializer(serializers.Serializer[dict[str, Any]]):
    operation = serializers.ChoiceField(choices=("question.add",))
    expected_version = serializers.IntegerField(min_value=1)
    section_id = CanonicalUUIDField()
    key = serializers.SlugField(max_length=80)
    field_type = serializers.ChoiceField(choices=ApplicationQuestionType.choices)
    label = cast(StrOrPromise | None, serializers.CharField(max_length=200))
    help_text = cast(
        StrOrPromise | None,
        serializers.CharField(max_length=2_000, allow_blank=True),
    )
    required = cast(bool, serializers.BooleanField())
    options = QuestionOptionSerializer(many=True, required=False, default=list)
    minimum_length = serializers.IntegerField(
        min_value=0, allow_null=True, required=False, default=None
    )
    maximum_length = serializers.IntegerField(
        min_value=1, max_value=65_536, allow_null=True, required=False, default=None
    )
    minimum_value = serializers.DecimalField(
        max_digits=18, decimal_places=4, allow_null=True, required=False, default=None
    )
    maximum_value = serializers.DecimalField(
        max_digits=18, decimal_places=4, allow_null=True, required=False, default=None
    )
    maximum_choices = serializers.IntegerField(
        min_value=1, max_value=100, allow_null=True, required=False, default=None
    )
    reference_kind = serializers.RegexField(
        r"^[a-z][a-z0-9_.:-]{0,79}$", allow_blank=True, required=False, default=""
    )
    condition = QuestionConditionSerializer(
        allow_null=False, required=False, default=dict
    )
    purpose = serializers.CharField(max_length=500)
    classification = serializers.ChoiceField(choices=ApplicationClassification.choices)
    applicant_visible = serializers.BooleanField(default=True)
    applicant_writable = serializers.BooleanField(default=True)
    staff_visible = serializers.BooleanField(default=True)
    staff_writable = serializers.BooleanField(default=False)
    reviewer_visible = serializers.BooleanField(default=True)
    public_after_approval = serializers.BooleanField(default=False)
    api_projection = serializers.BooleanField(default=True)
    retention_policy_code = serializers.RegexField(
        r"^[a-z][a-z0-9_.:-]{2,119}$", allow_blank=True, required=False, default=""
    )
    reason = serializers.CharField(max_length=240)


class DefinitionLifecycleSerializer(serializers.Serializer[dict[str, Any]]):
    operation = serializers.ChoiceField(
        choices=("definition.activate", "definition.retire")
    )
    expected_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=240)


class DefinitionSuccessorSerializer(serializers.Serializer[dict[str, Any]]):
    operation = serializers.ChoiceField(choices=("definition.successor",))
    reason = serializers.CharField(max_length=240)


DEFINITION_COMMAND_SERIALIZERS = {
    "definition.configure": DefinitionConfigureSerializer,
    "section.add": SectionAddSerializer,
    "question.add": QuestionAddSerializer,
    "definition.activate": DefinitionLifecycleSerializer,
    "definition.retire": DefinitionLifecycleSerializer,
    "definition.successor": DefinitionSuccessorSerializer,
}


class SubmissionAnswerSerializer(serializers.Serializer[dict[str, Any]]):
    question_id = CanonicalUUIDField()
    expected_version = serializers.IntegerField(min_value=1)
    value = serializers.JSONField(allow_null=True)


class SubmissionTransitionSerializer(serializers.Serializer[dict[str, Any]]):
    expected_version = serializers.IntegerField(min_value=1)


class ReviewDecisionSerializer(serializers.Serializer[dict[str, Any]]):
    expected_version = serializers.IntegerField(min_value=1)
    decision = serializers.ChoiceField(
        choices=("start_review", "request_changes", "accept", "reject")
    )
    reason = serializers.CharField(max_length=500)


class ApplicationCommandResultSerializer(serializers.Serializer[dict[str, object]]):
    receipt_id = serializers.UUIDField()
    definition_id = serializers.UUIDField(allow_null=True)
    submission_id = serializers.UUIDField(allow_null=True)
    target_id = serializers.UUIDField(allow_null=True)
    resulting_version = serializers.IntegerField(min_value=1)


class ApplicationStarterSummarySerializer(serializers.Serializer[dict[str, object]]):
    code = serializers.SlugField()
    name = serializers.CharField()
    description = serializers.CharField()
    owner_module = serializers.CharField()
    target_adapter_kind = serializers.CharField()
    classification = serializers.CharField()
    requires_local_policy = serializers.BooleanField()


class ApplicationQuestionConditionProjectionSerializer(
    serializers.Serializer[dict[str, object]]
):
    question_key = serializers.SlugField(required=False)
    operator = serializers.CharField(required=False)
    value = serializers.JSONField(required=False)


class ApplicationQuestionProjectionSerializer(
    serializers.Serializer[dict[str, object]]
):
    id = serializers.UUIDField()
    key = serializers.SlugField()
    field_type = serializers.CharField()
    label = cast(StrOrPromise | None, serializers.CharField())
    help_text = cast(
        StrOrPromise | None,
        serializers.CharField(allow_blank=True),
    )
    required = cast(bool, serializers.BooleanField())
    options = QuestionOptionSerializer(many=True)
    minimum_length = serializers.IntegerField(allow_null=True)
    maximum_length = serializers.IntegerField(allow_null=True)
    minimum_value = serializers.DecimalField(
        max_digits=18,
        decimal_places=4,
        allow_null=True,
    )
    maximum_value = serializers.DecimalField(
        max_digits=18,
        decimal_places=4,
        allow_null=True,
    )
    maximum_choices = serializers.IntegerField(allow_null=True)
    condition = ApplicationQuestionConditionProjectionSerializer()
    applicant_writable = serializers.BooleanField()
    source_binding = serializers.CharField(allow_blank=True)


class ApplicationStaffQuestionProjectionSerializer(
    ApplicationQuestionProjectionSerializer
):
    purpose = serializers.CharField()
    classification = serializers.CharField()
    applicant_visible = serializers.BooleanField()
    staff_visible = serializers.BooleanField()
    staff_writable = serializers.BooleanField()
    reviewer_visible = serializers.BooleanField()
    public_after_approval = serializers.BooleanField()
    api_projection = serializers.BooleanField()
    retention_policy_code = serializers.CharField(allow_blank=True)


class ApplicationApplicantSectionSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    key = serializers.SlugField()
    title = serializers.CharField()
    help_text = cast(
        StrOrPromise | None,
        serializers.CharField(allow_blank=True),
    )
    questions = ApplicationQuestionProjectionSerializer(many=True)


class ApplicationStaffSectionSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    key = serializers.SlugField()
    title = serializers.CharField()
    help_text = cast(
        StrOrPromise | None,
        serializers.CharField(allow_blank=True),
    )
    questions = ApplicationStaffQuestionProjectionSerializer(many=True)


class ApplicationOwnerDepartmentSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    name = serializers.CharField()


class ApplicationReviewerRoleSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    version = serializers.IntegerField(min_value=1)


class ApplicationReviewerPersonSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    display_name = serializers.CharField()


class ApplicationApplicantDefinitionSerializer(
    serializers.Serializer[dict[str, object]]
):
    id = serializers.UUIDField()
    code = serializers.SlugField()
    version = serializers.IntegerField(min_value=1)
    aggregate_version = serializers.IntegerField(min_value=1)
    status = serializers.CharField()
    target_adapter_kind = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    purpose = serializers.CharField()
    eligibility_kind = serializers.CharField()
    maximum_submissions = serializers.IntegerField(min_value=1)
    opens_at = serializers.DateTimeField()
    closes_at = serializers.DateTimeField()
    applicant_edit_until = serializers.DateTimeField()
    minimum_age = serializers.IntegerField(min_value=0)
    sections = ApplicationApplicantSectionSerializer(many=True)


class ApplicationDefinitionSerializer(ApplicationApplicantDefinitionSerializer):
    classification = serializers.CharField()
    audience_policy_code = serializers.CharField(allow_blank=True)
    retention_policy_code = serializers.CharField(allow_blank=True)
    age_policy_code = serializers.CharField(allow_blank=True)
    owner_departments = ApplicationOwnerDepartmentSerializer(many=True)
    reviewer_roles = ApplicationReviewerRoleSerializer(many=True)
    reviewer_people = ApplicationReviewerPersonSerializer(many=True)
    sections = ApplicationStaffSectionSerializer(many=True)  # type: ignore[assignment]


class ApplicationAnswerProjectionSerializer(serializers.Serializer[dict[str, object]]):
    question_id = serializers.UUIDField()
    key = serializers.SlugField()
    question_type = serializers.CharField()
    value = serializers.JSONField(allow_null=True)
    sequence = serializers.IntegerField(min_value=1)
    updated_at = serializers.DateTimeField()


class ApplicationReviewerAnswerProjectionSerializer(
    ApplicationAnswerProjectionSerializer
):
    classification = serializers.CharField()
    source = serializers.CharField()  # type: ignore[assignment]


class ApplicationDecisionProjectionSerializer(
    serializers.Serializer[dict[str, object]]
):
    sequence = serializers.IntegerField(min_value=1)
    decision = serializers.CharField()
    from_state = serializers.CharField()
    to_state = serializers.CharField()
    reason = serializers.CharField()
    decided_at = serializers.DateTimeField()


class ApplicationSubmissionProjectionSerializer(
    serializers.Serializer[dict[str, object]]
):
    id = serializers.UUIDField()
    definition_id = serializers.UUIDField()
    definition_name = serializers.CharField()
    definition_version = serializers.IntegerField(min_value=1)
    target_adapter_kind = serializers.CharField()
    ordinal = serializers.IntegerField(min_value=1)
    state = serializers.CharField()
    aggregate_version = serializers.IntegerField(min_value=1)
    submitted_at = serializers.DateTimeField(allow_null=True)
    decided_at = serializers.DateTimeField(allow_null=True)
    answers = ApplicationAnswerProjectionSerializer(many=True)
    decisions = ApplicationDecisionProjectionSerializer(many=True)


class ApplicationReviewSubmissionProjectionSerializer(
    ApplicationSubmissionProjectionSerializer
):
    applicant = ApplicationReviewerPersonSerializer()
    answers = ApplicationReviewerAnswerProjectionSerializer(many=True)


class MyApplicationWorkspaceSerializer(serializers.Serializer[dict[str, object]]):
    available = ApplicationApplicantDefinitionSerializer(many=True)
    submissions = ApplicationSubmissionProjectionSerializer(many=True)


def latest_answers(
    submission: ApplicationSubmission,
    *,
    audience: Literal["applicant", "reviewer"],
) -> list[dict[str, object]]:
    values: dict[str, dict[str, object]] = {}
    for revision in submission.answer_revisions.all():
        question = revision.question
        if audience == "applicant" and not question.applicant_visible:
            continue
        if audience == "reviewer" and not (
            question.staff_visible and question.reviewer_visible
        ):
            continue
        current = values.get(revision.question_key)
        if current is None or cast(int, current["sequence"]) < revision.sequence:
            item: dict[str, object] = {
                "question_id": str(revision.question_id),
                "key": revision.question_key,
                "question_type": revision.question_type,
                "value": revision.value,
                "sequence": revision.sequence,
                "updated_at": revision.created_at,
            }
            if audience == "reviewer":
                item.update(
                    classification=revision.classification,
                    source=revision.source,
                )
            values[revision.question_key] = item
    return [values[key] for key in sorted(values)]


def decision_history(submission: ApplicationSubmission) -> list[dict[str, object]]:
    return [
        {
            "sequence": decision.sequence,
            "decision": decision.decision,
            "from_state": decision.from_state,
            "to_state": decision.to_state,
            "reason": decision.reason,
            "decided_at": decision.created_at,
        }
        for decision in submission.review_decisions.all()
    ]
