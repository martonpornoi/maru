from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.core.exceptions import ValidationError

from maru.registration import services
from maru.registration.models import (
    MediaReviewStatus,
    QuestionFieldType,
    Registration,
    RegistrationProfileExtensionField,
    RegistrationQuestion,
)


def _validation_codes(error: ValidationError) -> set[str | None]:
    if hasattr(error, "error_dict"):
        return {item.code for errors in error.error_dict.values() for item in errors}
    return {item.code for item in error.error_list}


def _question(
    field_type: str,
    *,
    key: str = "answer",
    options: list[str] | None = None,
    required: bool = False,
    condition_question_key: str = "",
    condition_value: str = "",
    visibility: str = "attendee_and_staff",
) -> RegistrationQuestion:
    return RegistrationQuestion(
        key=key,
        label=key.title(),
        help_text="",
        field_type=field_type,
        required=required,
        position=1,
        options=options or [],
        purpose="Collect a registration answer.",
        visibility=visibility,
        classification="C2",
        condition_question_key=condition_question_key,
        condition_value=condition_value,
    )


def _profile_field(
    field_type: str,
    *,
    options: list[str] | None = None,
) -> RegistrationProfileExtensionField:
    return RegistrationProfileExtensionField(
        key="profile_field",
        label="Profile field",
        field_type=field_type,
        options=options or [],
        purpose="Collect a current-profile value.",
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, "true"),
        (False, "false"),
        (42, "42"),
        ("  selected  ", "selected"),
        (None, ""),
        (["unsupported"], ""),
    ],
)
def test_condition_values_have_one_canonical_comparison_form(
    value: object,
    expected: str,
) -> None:
    assert services._normalized_condition_value(value) == expected


@pytest.mark.parametrize(
    ("field_type", "value", "expected"),
    [
        (QuestionFieldType.SHORT_TEXT, "  concise  ", "concise"),
        (QuestionFieldType.LONG_TEXT, "  detailed  ", "detailed"),
        (QuestionFieldType.BOOLEAN, True, True),
        (QuestionFieldType.INTEGER, -17, -17),
        (QuestionFieldType.SINGLE_CHOICE, "green", "green"),
        (QuestionFieldType.MULTIPLE_CHOICE, ["green", "blue"], ["green", "blue"]),
    ],
)
def test_registration_answers_preserve_only_the_typed_canonical_value(
    field_type: str,
    value: object,
    expected: object,
) -> None:
    question = _question(field_type, options=["green", "blue"])

    assert services._normalize_answer(question, value) == expected


@pytest.mark.parametrize(
    ("field_type", "value", "code"),
    [
        (QuestionFieldType.SHORT_TEXT, 7, "invalid_registration_answer"),
        (
            QuestionFieldType.SHORT_TEXT,
            "x" * (services.MAX_SHORT_ANSWER_LENGTH + 1),
            "registration_answer_too_long",
        ),
        (
            QuestionFieldType.LONG_TEXT,
            "x" * (services.MAX_LONG_ANSWER_LENGTH + 1),
            "registration_answer_too_long",
        ),
        (QuestionFieldType.BOOLEAN, "yes", "invalid_registration_answer"),
        (QuestionFieldType.INTEGER, True, "invalid_registration_answer"),
        (
            QuestionFieldType.INTEGER,
            services.MAX_SIGNED_32_BIT_INTEGER + 1,
            "registration_integer_answer_out_of_range",
        ),
        (QuestionFieldType.SINGLE_CHOICE, "red", "invalid_registration_answer"),
        (QuestionFieldType.MULTIPLE_CHOICE, "green", "invalid_registration_answer"),
        (
            QuestionFieldType.MULTIPLE_CHOICE,
            ["green", 1],
            "invalid_registration_answer",
        ),
        (
            QuestionFieldType.MULTIPLE_CHOICE,
            ["green", "green"],
            "invalid_registration_answer",
        ),
        (
            QuestionFieldType.MULTIPLE_CHOICE,
            ["red"],
            "invalid_registration_answer",
        ),
        ("retired_type", "value", "unsupported_registration_question"),
    ],
)
def test_registration_answers_reject_type_confusion_and_unbounded_values(
    field_type: str,
    value: object,
    code: str,
) -> None:
    question = _question(field_type, options=["green", "blue"])

    with pytest.raises(ValidationError) as raised:
        services._normalize_answer(question, value)

    assert set(raised.value.message_dict) == {question.key}
    assert code in {
        "invalid_registration_answer",
        "registration_answer_too_long",
        "registration_integer_answer_out_of_range",
        "unsupported_registration_question",
    }


def test_answer_object_rejects_unknown_inactive_and_missing_required_values() -> None:
    controller = _question(QuestionFieldType.BOOLEAN, key="show_details")
    dependent = _question(
        QuestionFieldType.SHORT_TEXT,
        key="details",
        required=True,
        condition_question_key="show_details",
        condition_value="true",
    )

    with pytest.raises(ValidationError) as malformed:
        services.validate_registration_answers(questions=[], answers=[])
    assert set(malformed.value.message_dict) == {"answers"}

    with pytest.raises(ValidationError) as unknown:
        services.validate_registration_answers(
            questions=[controller],
            answers={"unexpected": True},
        )
    assert set(unknown.value.message_dict) == {"answers"}

    with pytest.raises(ValidationError) as inactive:
        services.validate_registration_answers(
            questions=[controller, dependent],
            answers={"show_details": False, "details": "should stay private"},
        )
    assert set(inactive.value.message_dict) == {"details"}

    with pytest.raises(ValidationError) as missing:
        services.validate_registration_answers(
            questions=[controller, dependent],
            answers={"show_details": True},
        )
    assert set(missing.value.message_dict) == {"details"}

    with pytest.raises(ValidationError) as empty:
        services.validate_registration_answers(
            questions=[controller, dependent],
            answers={"show_details": True, "details": "   "},
        )
    assert set(empty.value.message_dict) == {"details"}


def test_staff_only_answers_are_excluded_unless_the_caller_opts_in() -> None:
    question = _question(
        QuestionFieldType.SHORT_TEXT,
        key="internal_note",
        visibility="registration_staff",
    )

    with pytest.raises(ValidationError) as hidden:
        services.validate_registration_answers(
            questions=[question],
            answers={"internal_note": "internal"},
        )
    assert set(hidden.value.message_dict) == {"answers"}

    normalized, schema = services.validate_registration_answers(
        questions=[question],
        answers={"internal_note": "internal"},
        include_staff_questions=True,
    )
    assert normalized == {"internal_note": "internal"}
    assert schema[0]["key"] == "internal_note"


@pytest.mark.parametrize(
    ("field_type", "value", "expected"),
    [
        (QuestionFieldType.SHORT_TEXT, "  concise  ", "concise"),
        (QuestionFieldType.LONG_TEXT, "  detailed  ", "detailed"),
        (QuestionFieldType.BOOLEAN, False, False),
        (QuestionFieldType.INTEGER, 23, 23),
        (QuestionFieldType.SINGLE_CHOICE, "green", "green"),
        (QuestionFieldType.MULTIPLE_CHOICE, ["green", "blue"], ["green", "blue"]),
        (QuestionFieldType.BOOLEAN, None, None),
        (QuestionFieldType.INTEGER, None, None),
        (QuestionFieldType.SINGLE_CHOICE, None, None),
    ],
)
def test_profile_extension_values_use_typed_values_and_explicit_clear_semantics(
    field_type: str,
    value: object,
    expected: object,
) -> None:
    field = _profile_field(field_type, options=["green", "blue"])

    assert services._normalize_profile_extension_value(field, value) == expected


@pytest.mark.parametrize(
    ("field_type", "value", "code"),
    [
        (
            QuestionFieldType.SHORT_TEXT,
            None,
            "invalid_profile_extension_clear_value",
        ),
        (QuestionFieldType.SHORT_TEXT, 7, "invalid_profile_extension_value"),
        (
            QuestionFieldType.SHORT_TEXT,
            "x" * (services.MAX_SHORT_ANSWER_LENGTH + 1),
            "profile_extension_value_too_long",
        ),
        (QuestionFieldType.BOOLEAN, "false", "invalid_profile_extension_value"),
        (QuestionFieldType.INTEGER, True, "invalid_profile_extension_value"),
        (
            QuestionFieldType.INTEGER,
            services.MIN_SIGNED_32_BIT_INTEGER - 1,
            "profile_extension_integer_out_of_range",
        ),
        (QuestionFieldType.SINGLE_CHOICE, "red", "invalid_profile_extension_value"),
        (
            QuestionFieldType.MULTIPLE_CHOICE,
            ["green", "green"],
            "invalid_profile_extension_value",
        ),
        (
            "retired_type",
            "value",
            "unsupported_profile_extension_field",
        ),
    ],
)
def test_profile_extension_values_reject_ambiguous_or_out_of_policy_input(
    field_type: str,
    value: object,
    code: str,
) -> None:
    field = _profile_field(field_type, options=["green", "blue"])

    with pytest.raises(ValidationError) as raised:
        services._normalize_profile_extension_value(field, value)

    assert set(raised.value.message_dict) == {"value"}
    assert code in {
        "invalid_profile_extension_clear_value",
        "invalid_profile_extension_value",
        "profile_extension_integer_out_of_range",
        "profile_extension_value_too_long",
        "unsupported_profile_extension_field",
    }


class _MediaQuery:
    def __init__(self, result: object) -> None:
        self.result = result

    def filter(self, **_kwargs: object) -> _MediaQuery:
        return self

    def exclude(self, **_kwargs: object) -> _MediaQuery:
        return self

    def first(self) -> object:
        return self.result


@pytest.mark.parametrize(
    ("lookup", "code"),
    [
        ("profile", "profile_photo_reuse_denied"),
        ("fursuit", "fursuit_photo_reuse_denied"),
    ],
)
def test_media_reuse_lookups_fail_closed_without_exposing_which_guard_failed(
    monkeypatch: pytest.MonkeyPatch,
    lookup: str,
    code: str,
) -> None:
    model = (
        services.AttendeeRegistrationProfile
        if lookup == "profile"
        else services.AttendeeFursuit
    )
    monkeypatch.setattr(
        model.objects,
        "select_for_update",
        lambda: _MediaQuery(None),
    )
    function = (
        services._reusable_profile_photo
        if lookup == "profile"
        else services._reusable_fursuit_photo
    )

    with pytest.raises(ValidationError) as raised:
        function(
            source_id=UUID(int=2),
            account=SimpleNamespace(id=UUID(int=3)),
            organization_id=UUID(int=4),
        )

    assert code in _validation_codes(raised.value)


@pytest.mark.parametrize("lookup", ["profile", "fursuit"])
def test_media_reuse_lookups_return_only_the_prevalidated_owned_source(
    monkeypatch: pytest.MonkeyPatch,
    lookup: str,
) -> None:
    source = SimpleNamespace(id=UUID(int=5))
    model = (
        services.AttendeeRegistrationProfile
        if lookup == "profile"
        else services.AttendeeFursuit
    )
    monkeypatch.setattr(
        model.objects,
        "select_for_update",
        lambda: _MediaQuery(source),
    )
    function = (
        services._reusable_profile_photo
        if lookup == "profile"
        else services._reusable_fursuit_photo
    )

    assert (
        function(
            source_id=UUID(int=2),
            account=SimpleNamespace(id=UUID(int=3)),
            organization_id=UUID(int=4),
        )
        is source
    )


def test_profile_photo_reuse_copies_review_evidence_without_reprocessing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed_at = datetime(2026, 8, 1, tzinfo=UTC)
    source = SimpleNamespace(
        id=UUID(int=2),
        profile_photo="approved/profile.webp",
        profile_photo_reviewed_by_id=UUID(int=3),
        profile_photo_reviewed_at=reviewed_at,
        profile_photo_review_note="Approved after review.",
    )
    monkeypatch.setattr(services, "_reusable_profile_photo", lambda **_kwargs: source)
    profile = SimpleNamespace(organization_id=UUID(int=4))
    profile_input = SimpleNamespace(
        profile_photo=None,
        reuse_profile_photo_id=source.id,
        keep_profile_photo=False,
    )

    processed, reused = services._apply_profile_photo(
        profile=profile,
        profile_input=profile_input,
        account=SimpleNamespace(id=UUID(int=5)),
    )

    assert processed is None
    assert reused is source
    assert profile.profile_photo == source.profile_photo
    assert profile.profile_photo_status == MediaReviewStatus.APPROVED
    assert profile.profile_photo_reused_from_id == source.id
    assert profile.profile_photo_reviewed_at == reviewed_at


def test_fursuit_photo_reuse_copies_review_evidence_without_reprocessing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed_at = datetime(2026, 8, 1, tzinfo=UTC)
    source = SimpleNamespace(
        id=UUID(int=2),
        photo="approved/fursuit.webp",
        photo_reviewed_by_id=UUID(int=3),
        photo_reviewed_at=reviewed_at,
        photo_review_note="Approved after review.",
    )
    monkeypatch.setattr(services, "_reusable_fursuit_photo", lambda **_kwargs: source)
    fursuit = SimpleNamespace(organization_id=UUID(int=4))
    fursuit_input = SimpleNamespace(
        photo=None,
        reuse_from_id=source.id,
        keep_photo=False,
    )

    processed, reused = services._apply_fursuit_photo(
        fursuit=fursuit,
        fursuit_input=fursuit_input,
        account=SimpleNamespace(id=UUID(int=5)),
    )

    assert processed is None
    assert reused is source
    assert fursuit.photo == source.photo
    assert fursuit.photo_status == MediaReviewStatus.APPROVED
    assert fursuit.photo_reused_from_id == source.id
    assert fursuit.photo_reviewed_at == reviewed_at


def test_configuration_source_classification_distinguishes_exact_source_kinds() -> None:
    assert (
        services._configuration_source_kind(
            SimpleNamespace(source_template_id=UUID(int=1), source_edition_id=None)
        )
        == "template"
    )
    assert (
        services._configuration_source_kind(
            SimpleNamespace(source_template_id=None, source_edition_id=UUID(int=2))
        )
        == "edition"
    )
    assert (
        services._configuration_source_kind(
            SimpleNamespace(source_template_id=None, source_edition_id=None)
        )
        == "blank"
    )


def test_reason_boundary_strips_valid_evidence_and_rejects_blank_evidence() -> None:
    assert services._require_reason("  Operational exception  ") == (
        "Operational exception"
    )
    with pytest.raises(ValidationError) as raised:
        services._require_reason("   ")
    assert raised.value.message_dict == {"reason": ["A reason is required."]}


def test_lifecycle_transition_returns_none_for_open_active_registration() -> None:
    now = datetime(2026, 8, 11, 12, tzinfo=UTC)
    registration = SimpleNamespace(
        account=SimpleNamespace(is_active=True),
        state=Registration.State.WAITLISTED,
        configuration=SimpleNamespace(closes_at=now + timedelta(days=1)),
        product=SimpleNamespace(sales_close_at=None),
        payment_due_at=None,
    )

    assert (
        services._lifecycle_transition_for(
            registration=registration,
            processed_at=now,
        )
        is None
    )


def test_waitlist_promotion_stops_before_querying_when_automation_is_disabled() -> None:
    product = SimpleNamespace(
        configuration=SimpleNamespace(automatic_waitlist_promotion=False)
    )

    assert (
        services._promote_waitlist_for_product(
            product=product,
            offered_at=datetime(2026, 8, 11, tzinfo=UTC),
            correlation_id=UUID(int=1),
        )
        is None
    )


class _OccupiedQuery:
    def count(self) -> int:
        return 1

    def filter(self, **_kwargs: object) -> _OccupiedQuery:
        return self


def test_waitlist_promotion_respects_global_capacity_before_selecting_an_attendee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 11, tzinfo=UTC)
    configuration = SimpleNamespace(
        automatic_waitlist_promotion=True,
        closes_at=now + timedelta(days=1),
    )
    product = SimpleNamespace(configuration=configuration, sales_close_at=None)
    monkeypatch.setattr(
        services.Registration.objects,
        "filter",
        lambda **_kwargs: _OccupiedQuery(),
    )
    monkeypatch.setattr(services, "effective_configuration_capacity", lambda _c: 1)

    assert (
        services._promote_waitlist_for_product(
            product=product,
            offered_at=now,
            correlation_id=UUID(int=1),
        )
        is None
    )


def test_payment_deadline_uses_product_override_before_configuration_default() -> None:
    starts_at = datetime(2026, 8, 11, tzinfo=UTC)
    configuration = SimpleNamespace(default_payment_window_minutes=60)

    assert services._payment_deadline(
        configuration=configuration,
        product=SimpleNamespace(payment_window_minutes=15),
        starts_at=starts_at,
    ) == starts_at + timedelta(minutes=15)
    assert services._payment_deadline(
        configuration=configuration,
        product=SimpleNamespace(payment_window_minutes=None),
        starts_at=starts_at,
    ) == starts_at + timedelta(minutes=60)


def test_lifecycle_candidate_total_is_the_sum_of_distinct_failure_classes() -> None:
    candidates = services.RegistrationLifecycleCandidates(
        expired=2,
        inactive_cancelled=3,
        closed_waitlist_cancelled=5,
    )

    assert candidates.total == 10


def test_media_clear_paths_remove_stale_review_evidence() -> None:
    profile = SimpleNamespace(
        organization_id=UUID(int=1),
        profile_photo="old.webp",
        profile_photo_status=MediaReviewStatus.APPROVED,
        profile_photo_reviewed_by_id=UUID(int=2),
        profile_photo_reviewed_at=datetime(2026, 8, 1, tzinfo=UTC),
        profile_photo_review_note="Old review",
        profile_photo_reused_from_id=UUID(int=3),
    )
    profile_result = services._apply_profile_photo(
        profile=profile,
        profile_input=SimpleNamespace(
            profile_photo=None,
            reuse_profile_photo_id=None,
            keep_profile_photo=False,
        ),
        account=SimpleNamespace(),
    )
    assert profile_result == (None, None)
    assert profile.profile_photo == ""
    assert profile.profile_photo_reviewed_by_id is None

    fursuit = SimpleNamespace(
        organization_id=UUID(int=1),
        photo="old.webp",
        photo_status=MediaReviewStatus.APPROVED,
        photo_reviewed_by_id=UUID(int=2),
        photo_reviewed_at=datetime(2026, 8, 1, tzinfo=UTC),
        photo_review_note="Old review",
        photo_reused_from_id=UUID(int=3),
    )
    fursuit_result = services._apply_fursuit_photo(
        fursuit=fursuit,
        fursuit_input=SimpleNamespace(
            photo=None,
            reuse_from_id=None,
            keep_photo=False,
        ),
        account=SimpleNamespace(),
    )
    assert fursuit_result == (None, None)
    assert fursuit.photo == ""
    assert fursuit.photo_reviewed_by_id is None


def test_media_keep_paths_leave_existing_values_untouched() -> None:
    profile = SimpleNamespace(organization_id=UUID(int=1), profile_photo="kept.webp")
    assert services._apply_profile_photo(
        profile=profile,
        profile_input=SimpleNamespace(
            profile_photo=None,
            reuse_profile_photo_id=None,
            keep_profile_photo=True,
        ),
        account=SimpleNamespace(),
    ) == (None, None)
    assert profile.profile_photo == "kept.webp"

    fursuit = SimpleNamespace(organization_id=UUID(int=1), photo="kept.webp")
    assert services._apply_fursuit_photo(
        fursuit=fursuit,
        fursuit_input=SimpleNamespace(
            photo=None,
            reuse_from_id=None,
            keep_photo=True,
        ),
        account=SimpleNamespace(),
    ) == (None, None)
    assert fursuit.photo == "kept.webp"


def test_processed_photo_paths_replace_moderation_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processed = SimpleNamespace(content="processed.webp")
    process_image = Mock(return_value=processed)
    monkeypatch.setattr(services, "process_image", process_image)
    upload = object()

    profile = SimpleNamespace(organization_id=UUID(int=1))
    result, reused = services._apply_profile_photo(
        profile=profile,
        profile_input=SimpleNamespace(
            profile_photo=upload,
            reuse_profile_photo_id=None,
            keep_profile_photo=False,
        ),
        account=SimpleNamespace(),
    )
    assert result is processed
    assert reused is None
    assert profile.profile_photo_status == MediaReviewStatus.PENDING

    fursuit = SimpleNamespace(organization_id=UUID(int=1))
    result, reused = services._apply_fursuit_photo(
        fursuit=fursuit,
        fursuit_input=SimpleNamespace(
            photo=upload,
            reuse_from_id=None,
            keep_photo=False,
        ),
        account=SimpleNamespace(),
    )
    assert result is processed
    assert reused is None
    assert fursuit.photo_status == MediaReviewStatus.PENDING
    assert process_image.call_count == 2
