"""Unit coverage for strict Programme call and proposal inputs."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.applications import programme_inputs
from maru.applications.programme_inputs import (
    ProgrammeCallClassification,
    ProgrammeCallConditionOperator,
    ProgrammeCallDefinitionInput,
    ProgrammeCallQuestionConditionInput,
    ProgrammeCallQuestionInput,
    ProgrammeCallQuestionOptionInput,
    ProgrammeCallQuestionType,
    ProgrammeCallSectionInput,
    ProgrammeProposalContributorProfileInput,
    ProgrammeProposalSelectionInput,
    canonical_programme_digest,
    canonical_programme_json,
)


def test_public_input_surface_exports_complete_call_form_graph() -> None:
    """Let clients construct the complete dedicated call without private imports."""
    expected = {
        "ProgrammeCallClassification",
        "ProgrammeCallConditionOperator",
        "ProgrammeCallConfigurationInput",
        "ProgrammeCallContributorFieldInput",
        "ProgrammeCallDefinitionInput",
        "ProgrammeCallFormatInput",
        "ProgrammeCallQuestionConditionInput",
        "ProgrammeCallQuestionInput",
        "ProgrammeCallQuestionOptionInput",
        "ProgrammeCallQuestionType",
        "ProgrammeCallSectionInput",
        "ProgrammeCallTrackInput",
    }

    assert expected <= set(programme_inputs.__all__)
    assert all(hasattr(programme_inputs, name) for name in expected)


def _question(
    *,
    key: str = "title",
    position: int = 1,
    classification: str = ProgrammeCallClassification.PERSONAL,
    condition: ProgrammeCallQuestionConditionInput | None = None,
    retention_policy_code: str = "",
) -> ProgrammeCallQuestionInput:
    return ProgrammeCallQuestionInput(
        key=key,
        field_type=ProgrammeCallQuestionType.SHORT_TEXT,
        label="Session title",
        help_text="A concise title.",
        position=position,
        required=True,
        options=(),
        minimum_length=3,
        maximum_length=160,
        minimum_value=None,
        maximum_value=None,
        maximum_choices=None,
        reference_kind="",
        condition=condition,
        purpose="Collect the title used to identify this proposal.",
        classification=classification,
        retention_policy_code=retention_policy_code,
    )


def _definition(
    *,
    classification: str = ProgrammeCallClassification.PERSONAL,
    questions: tuple[ProgrammeCallQuestionInput, ...] | None = None,
    retention_policy_code: str = "",
    audience_policy_code: str = "",
) -> ProgrammeCallDefinitionInput:
    section = ProgrammeCallSectionInput(
        key="proposal",
        title="Proposal",
        help_text="Tell the Programme team about the session.",
        position=1,
        questions=questions or (_question(classification=classification),),
    )
    return ProgrammeCallDefinitionInput(
        code="programme-call-2027",
        name="Programme call 2027",
        description="A collaborative Programme proposal call.",
        purpose="Collect complete session proposals for scheduling review.",
        classification=classification,
        maximum_submissions_per_person=4,
        opens_at=datetime(2027, 1, 1, tzinfo=UTC),
        applicant_edit_until=datetime(2027, 2, 1, tzinfo=UTC),
        closes_at=datetime(2027, 3, 1, tzinfo=UTC),
        audience_policy_code=audience_policy_code,
        retention_policy_code=retention_policy_code,
        sections=(section,),
    )


def _typed_question(
    *,
    key: str,
    position: int,
    field_type: ProgrammeCallQuestionType,
    condition: ProgrammeCallQuestionConditionInput | None = None,
) -> ProgrammeCallQuestionInput:
    choices = (
        ProgrammeCallQuestionOptionInput(code="talk", label="Talk"),
        ProgrammeCallQuestionOptionInput(code="panel", label="Panel"),
    )
    text_types = {
        ProgrammeCallQuestionType.SHORT_TEXT,
        ProgrammeCallQuestionType.LONG_TEXT,
        ProgrammeCallQuestionType.EMAIL,
        ProgrammeCallQuestionType.PHONE,
        ProgrammeCallQuestionType.URL,
    }
    return ProgrammeCallQuestionInput(
        key=key,
        field_type=field_type,
        label=key.replace("-", " ").title(),
        help_text="",
        position=position,
        required=False,
        options=(
            choices
            if field_type
            in {
                ProgrammeCallQuestionType.SINGLE_CHOICE,
                ProgrammeCallQuestionType.MULTIPLE_CHOICE,
            }
            else ()
        ),
        minimum_length=0 if field_type in text_types else None,
        maximum_length=160 if field_type in text_types else None,
        minimum_value=None,
        maximum_value=None,
        maximum_choices=(
            2 if field_type is ProgrammeCallQuestionType.MULTIPLE_CHOICE else None
        ),
        reference_kind=(
            "programme.person"
            if field_type
            in {
                ProgrammeCallQuestionType.PERSON_REFERENCE,
                ProgrammeCallQuestionType.DOMAIN_REFERENCE,
            }
            else ""
        ),
        condition=condition,
        purpose="Exercise typed condition semantics.",
        classification=ProgrammeCallClassification.PERSONAL,
        retention_policy_code="",
    )


def test_complete_call_definition_freezes_dedicated_nonlegacy_rules() -> None:
    """Carry a usable form graph without reopening generic target settings."""
    definition = _definition()
    question = definition.sections[0].questions[0]

    assert definition.target_adapter_kind == "programme_item"
    assert definition.eligibility_kind == "authenticated_person"
    assert definition.minimum_age == 0
    assert question.source_binding == ""
    assert question.public_after_approval is False
    assert question.applicant_visible is True
    assert question.applicant_writable is True
    assert question.staff_visible is False
    assert question.staff_writable is False
    assert question.reviewer_visible is False
    assert question.api_projection is False
    assert question.key == "title"


def test_call_definition_rejects_forward_conditions_and_classification_drift() -> None:
    """Keep conditions acyclic and every question within the definition ceiling."""
    forward_condition = ProgrammeCallQuestionConditionInput(
        question_key="later",
        operator=ProgrammeCallConditionOperator.EQUALS,
        value=True,
    )
    with pytest.raises(ValidationError) as forward_error:
        _definition(
            questions=(
                _question(condition=forward_condition),
                _question(key="later", position=2),
            )
        )
    assert forward_error.value.error_dict["condition"][0].code == (
        "applications_programme_condition_dependency_invalid"
    )

    with pytest.raises(ValidationError) as classification_error:
        _definition(
            classification=ProgrammeCallClassification.PERSONAL,
            questions=(
                _question(classification=ProgrammeCallClassification.RESTRICTED),
            ),
        )
    assert classification_error.value.error_dict["classification"][0].code == (
        "applications_programme_question_classification_invalid"
    )


@pytest.mark.parametrize(
    ("field_type", "operator", "value"),
    [
        (ProgrammeCallQuestionType.BOOLEAN, "equals", True),
        (ProgrammeCallQuestionType.INTEGER, "not_equals", 42),
        (ProgrammeCallQuestionType.SINGLE_CHOICE, "equals", "talk"),
        (ProgrammeCallQuestionType.MULTIPLE_CHOICE, "contains", "panel"),
        (ProgrammeCallQuestionType.SHORT_TEXT, "equals", "Caf\u0065\u0301"),
        (ProgrammeCallQuestionType.LONG_TEXT, "not_equals", "Draft"),
        (ProgrammeCallQuestionType.EMAIL, "equals", "person@example.invalid"),
        (ProgrammeCallQuestionType.PHONE, "equals", "+36 1 555 0100"),
        (ProgrammeCallQuestionType.URL, "equals", "https://example.invalid"),
    ],
)
def test_call_condition_catalog_accepts_only_canonical_scalar_sources(
    field_type: ProgrammeCallQuestionType,
    operator: str,
    value: str | bool | int,
) -> None:
    """Accept the service-owned scalar and multiple-choice condition catalog."""
    condition = ProgrammeCallQuestionConditionInput(
        question_key="source",
        operator=operator,
        value=value,
    )
    definition = _definition(
        questions=(
            _typed_question(key="source", position=1, field_type=field_type),
            _typed_question(
                key="dependent",
                position=2,
                field_type=ProgrammeCallQuestionType.SHORT_TEXT,
                condition=condition,
            ),
        )
    )

    stored = definition.sections[0].questions[1].condition
    assert stored is not None
    if field_type is ProgrammeCallQuestionType.SHORT_TEXT:
        assert stored.value == "Caf\u00e9"


@pytest.mark.parametrize(
    ("field_type", "operator", "value"),
    [
        (ProgrammeCallQuestionType.DECIMAL, "equals", "1.0"),
        (ProgrammeCallQuestionType.DATE, "equals", "2027-01-01"),
        (ProgrammeCallQuestionType.TIME, "equals", "10:00:00"),
        (ProgrammeCallQuestionType.INSTANT, "equals", "2027-01-01T10:00:00Z"),
        (ProgrammeCallQuestionType.ADDRESS, "equals", "Budapest"),
        (ProgrammeCallQuestionType.PERSON_REFERENCE, "equals", str(UUID(int=1))),
        (ProgrammeCallQuestionType.SAFE_FILE, "equals", str(UUID(int=1))),
        (ProgrammeCallQuestionType.MULTIPLE_CHOICE, "equals", "talk"),
        (ProgrammeCallQuestionType.SINGLE_CHOICE, "equals", "missing"),
        (ProgrammeCallQuestionType.BOOLEAN, "equals", "true"),
        (ProgrammeCallQuestionType.INTEGER, "equals", True),
        (ProgrammeCallQuestionType.SHORT_TEXT, "contains", "text"),
    ],
)
def test_call_condition_catalog_rejects_structured_or_incompatible_sources(
    field_type: ProgrammeCallQuestionType,
    operator: str,
    value: str | bool | int,
) -> None:
    """Reject conditions whose runtime semantics cannot match the source type."""
    condition = ProgrammeCallQuestionConditionInput(
        question_key="source",
        operator=operator,
        value=value,
    )

    with pytest.raises(ValidationError) as raised:
        _definition(
            questions=(
                _typed_question(key="source", position=1, field_type=field_type),
                _typed_question(
                    key="dependent",
                    position=2,
                    field_type=ProgrammeCallQuestionType.SHORT_TEXT,
                    condition=condition,
                ),
            )
        )

    assert raised.value.error_dict["condition"][0].code == (
        "applications_programme_condition_semantics_invalid"
    )


def test_sensitive_definition_requires_explicit_audience_and_retention() -> None:
    """Never activate a restricted proposal graph on implicit policies."""
    with pytest.raises(ValidationError) as raised:
        _definition(classification=ProgrammeCallClassification.RESTRICTED)

    assert raised.value.error_dict["retention_policy_code"][0].code == (
        "applications_programme_sensitive_policy_required"
    )
    definition = _definition(
        classification=ProgrammeCallClassification.RESTRICTED,
        audience_policy_code="programme.proposal-audience:v1",
        retention_policy_code="programme.proposal-retention:v1",
    )
    assert definition.retention_policy_code == "programme.proposal-retention:v1"


def test_choice_and_duration_inputs_are_bounded_and_typed() -> None:
    """Reject incomplete choices and out-of-range proposed durations."""
    option = ProgrammeCallQuestionOptionInput(code="talk", label="Talk")
    with pytest.raises(ValidationError):
        ProgrammeCallQuestionInput(
            key="format",
            field_type=ProgrammeCallQuestionType.SINGLE_CHOICE,
            label="Format",
            help_text="",
            position=1,
            required=True,
            options=(option,),
            minimum_length=None,
            maximum_length=None,
            minimum_value=None,
            maximum_value=None,
            maximum_choices=None,
            reference_kind="",
            condition=None,
            purpose="Choose a delivery format.",
            classification=ProgrammeCallClassification.PERSONAL,
            retention_policy_code="",
        )

    selection = ProgrammeProposalSelectionInput(
        track_id=uuid4(),
        format_id=uuid4(),
        requested_duration_minutes=90,
    )
    assert selection.requested_duration_minutes == 90
    with pytest.raises(ValidationError):
        ProgrammeProposalSelectionInput(
            track_id=uuid4(),
            format_id=uuid4(),
            requested_duration_minutes=1_441,
        )


def test_subject_profile_requires_explicit_consent_and_blank_opt_out() -> None:
    """Keep proposed-public values subject-owned and policy-specific."""
    with pytest.raises(ValidationError) as consent_error:
        ProgrammeProposalContributorProfileInput(
            public_name="Speaker",
            biography="Biography",
            pronouns="they/them",
            website="https://example.invalid",
            proposed_for_publication=True,
            consent_acknowledged=False,
            consent_policy_code="programme.contributor-consent:v1",
        )
    assert consent_error.value.error_dict["consent_acknowledged"][0].code == (
        "applications_programme_public_consent_required"
    )

    with pytest.raises(ValidationError) as privacy_error:
        ProgrammeProposalContributorProfileInput(
            public_name="Hidden speaker",
            biography="",
            pronouns="",
            website="",
            proposed_for_publication=False,
            consent_acknowledged=False,
            consent_policy_code="programme.contributor-consent:v1",
        )
    assert privacy_error.value.error_dict["proposed_for_publication"][0].code == (
        "applications_programme_unpublished_profile_not_blank"
    )


def test_canonical_digest_is_strict_unicode_and_lowercase_uuid_json() -> None:
    """Hash only deterministic supported JSON values without string fallbacks."""
    identifier = UUID("ABCDEFAB-CDEF-ABCD-EFAB-CDEFABCDEFAB")
    payload = {
        "label": "Cafe\u0301",
        "identifier": identifier,
        "number": Decimal("12.3400"),
    }

    encoded = canonical_programme_json(payload)
    assert encoded == (
        b'{"identifier":"abcdefab-cdef-abcd-efab-cdefabcdefab",'
        b'"label":"Caf\xc3\xa9","number":"12.3400"}'
    )
    assert canonical_programme_digest(payload) == canonical_programme_digest(
        dict(reversed(tuple(payload.items())))
    )
    with pytest.raises(TypeError):
        canonical_programme_json({"unsupported": object()})
