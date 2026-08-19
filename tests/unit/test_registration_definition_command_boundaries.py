from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.events.models import EventEdition
from maru.organizations.models import Organization
from maru.registration import setup_definition_commands as commands
from maru.registration.models import (
    ProfileExtensionAudience,
    ProfileExtensionReviewStatus,
    ProfileExtensionStatus,
    ProfileExtensionWriter,
    QuestionFieldType,
    QuestionVisibility,
)
from maru.registration.setup_commands import RegistrationSetupLifecycleConflictError
from maru.registration.setup_definition_commands import (
    RegistrationSetupLimitExceededError,
    RegistrationSetupProductUnavailableError,
    RegistrationSetupProfileFieldUnavailableError,
    RegistrationSetupQuestionUnavailableError,
)


def _validation_code(error: ValidationError) -> str:
    if error.error_dict:
        return next(iter(error.error_dict.values()))[0].code
    return error.error_list[0].code


@pytest.mark.parametrize("value", [None, 0, 1, "true", [], object()])
def test_boolean_command_input_requires_a_real_json_boolean(value: object) -> None:
    with pytest.raises(ValidationError) as error:
        commands._strict_boolean(value, field="enabled")
    assert _validation_code(error.value) == "registration_setup_boolean_invalid"


@pytest.mark.parametrize("value", [False, True])
def test_boolean_command_input_preserves_the_exact_value(value: bool) -> None:
    assert commands._strict_boolean(value, field="enabled") is value


def test_integer_command_input_distinguishes_optional_absence_from_falsy_values() -> (
    None
):
    assert (
        commands._strict_integer(
            None,
            field="capacity_ceiling",
            minimum=1,
            maximum=10,
            optional=True,
        )
        is None
    )
    assert commands._strict_integer(1, field="capacity", minimum=1, maximum=10) == 1
    for value in (None, False, 0, 11, 1.0, "1"):
        with pytest.raises(ValidationError) as error:
            commands._strict_integer(
                value,
                field="capacity",
                minimum=1,
                maximum=10,
            )
        assert _validation_code(error.value) == "registration_setup_integer_invalid"


def test_closed_choice_accepts_only_documented_string_values() -> None:
    choices = frozenset({"draft", "active"})
    assert commands._closed_choice("draft", field="status", choices=choices) == "draft"
    for value in ("Draft", "retired", 1, None):
        with pytest.raises(ValidationError) as error:
            commands._closed_choice(value, field="status", choices=choices)
        assert _validation_code(error.value) == "registration_setup_choice_invalid"


@pytest.mark.parametrize(
    "value",
    [None, "", " Upper", "two--hyphens", "ends-", "a" * 81],
)
def test_definition_keys_are_bounded_canonical_lowercase(value: object) -> None:
    with pytest.raises(ValidationError) as error:
        commands._normalized_key(value, field="key")
    assert _validation_code(error.value) == "registration_setup_key_invalid"


def test_definition_keys_are_nfc_normalized_and_trimmed() -> None:
    assert commands._normalized_key("  arrival-note  ", field="key") == "arrival-note"


def test_question_options_are_bounded_unique_labels() -> None:
    with pytest.raises(ValidationError) as error:
        commands._normalized_options("one")
    assert (
        _validation_code(error.value) == "registration_setup_question_options_invalid"
    )

    with pytest.raises(RegistrationSetupLimitExceededError):
        commands._normalized_options(
            [str(index) for index in range(commands.MAX_QUESTION_OPTIONS + 1)]
        )

    with pytest.raises(ValidationError) as error:
        commands._normalized_options([" One ", "One"])
    assert (
        _validation_code(error.value) == "registration_setup_question_options_duplicate"
    )
    assert commands._normalized_options([" One ", "Two"]) == ["One", "Two"]


@pytest.mark.parametrize(
    ("field_type", "options", "code"),
    [
        (
            QuestionFieldType.SINGLE_CHOICE,
            ["Only one"],
            "registration_setup_question_options_required",
        ),
        (
            QuestionFieldType.SHORT_TEXT,
            ["Unexpected", "Values"],
            "registration_setup_question_options_not_allowed",
        ),
    ],
)
def test_question_options_match_the_field_type(
    field_type: str,
    options: list[str],
    code: str,
) -> None:
    with pytest.raises(ValidationError) as error:
        commands._validate_options_for_type(field_type=field_type, options=options)
    assert _validation_code(error.value) == code
    commands._validate_options_for_type(
        field_type=QuestionFieldType.MULTIPLE_CHOICE,
        options=["One", "Two"],
    )


def test_command_datetimes_require_explicit_time_zone_offsets() -> None:
    aware = datetime(2027, 8, 1, 10, tzinfo=UTC)
    assert commands._aware_datetime(None, field="opens_at") is None
    assert commands._aware_datetime(aware, field="opens_at") is aware
    for value in (
        "2027-08-01T10:00:00Z",
        datetime(2027, 8, 1, 10),  # noqa: DTZ001 - deliberate naive input
    ):
        with pytest.raises(ValidationError) as error:
            commands._aware_datetime(value, field="opens_at")
        assert _validation_code(error.value) == "registration_setup_datetime_invalid"


@pytest.mark.parametrize(
    "value",
    ["attendee", " Volunteer ", "stage.tech", "front-desk_2"],
)
def test_product_capacity_codes_are_normalized(value: str) -> None:
    assert commands._normalized_capacity_codes([value]) == [value.strip().lower()]


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ("attendee", "registration_setup_product_capacity_codes_invalid"),
        ([1], "registration_setup_product_capacity_codes_invalid"),
        (["Bad value"], "registration_setup_product_capacity_codes_invalid"),
        (
            ["attendee", " attendee "],
            "registration_setup_product_capacity_codes_duplicate",
        ),
    ],
)
def test_product_capacity_codes_reject_ambiguous_inputs(
    value: object,
    code: str,
) -> None:
    with pytest.raises(ValidationError) as error:
        commands._normalized_capacity_codes(value)
    assert _validation_code(error.value) == code


def _product_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "code": "supporter",
        "name": "Supporter",
        "description": "Supporter admission.",
        "price_minor": 12_000,
        "capacity": 50,
        "capacity_ceiling": 60,
        "entitlement_code": "supporter",
        "entitlement_name": "Supporter",
        "sales_open_at": None,
        "sales_close_at": None,
        "required_capacity_codes": [],
        "eligibility_explanation": "",
        "waitlist_enabled": True,
        "payment_window_minutes": 30,
    }
    values.update(overrides)
    return commands._product_values(**values)


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        (
            {"capacity": 50, "capacity_ceiling": 49},
            "registration_setup_product_capacity_ceiling_invalid",
        ),
        (
            {"sales_open_at": datetime(2027, 8, 1, tzinfo=UTC)},
            "registration_setup_product_sales_window_invalid",
        ),
        (
            {
                "sales_open_at": datetime(2027, 8, 2, tzinfo=UTC),
                "sales_close_at": datetime(2027, 8, 1, tzinfo=UTC),
            },
            "registration_setup_product_sales_window_invalid",
        ),
        (
            {"required_capacity_codes": ["volunteer"]},
            "registration_setup_product_eligibility_explanation_required",
        ),
    ],
)
def test_product_definition_rejects_incoherent_capacity_window_and_eligibility(
    overrides: dict[str, object],
    code: str,
) -> None:
    with pytest.raises(ValidationError) as error:
        _product_values(**overrides)
    assert _validation_code(error.value) == code


def test_product_definition_preserves_zero_price_and_optional_absence() -> None:
    values = _product_values(
        price_minor=0,
        capacity_ceiling=None,
        payment_window_minutes=None,
    )
    assert values["price_minor"] == 0
    assert values["capacity_ceiling"] is None
    assert values["payment_window_minutes"] is None


def _question(
    key: str,
    *,
    condition_question_key: str = "",
    condition_value: str = "",
    field_type: str = QuestionFieldType.SHORT_TEXT,
    options: list[str] | None = None,
    visibility: str = QuestionVisibility.ATTENDEE_AND_STAFF,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        key=key,
        condition_question_key=condition_question_key,
        condition_value=condition_value,
        field_type=field_type,
        options=[] if options is None else options,
        visibility=visibility,
        position=10,
        last_changed_in_setup_version=1,
        updated_at=None,
        _state=SimpleNamespace(adding=False),
    )


@pytest.mark.parametrize(
    ("questions", "code"),
    [
        (
            (_question("same"), _question("same")),
            "registration_setup_question_key_duplicate",
        ),
        (
            (_question("source"), _question("target", condition_question_key="source")),
            "registration_setup_question_condition_incomplete",
        ),
        (
            (
                _question(
                    "target", condition_question_key="missing", condition_value="yes"
                ),
            ),
            "registration_setup_question_condition_source_missing",
        ),
        (
            (
                _question(
                    "target", condition_question_key="source", condition_value="yes"
                ),
                _question("source", field_type=QuestionFieldType.BOOLEAN),
            ),
            "registration_setup_question_condition_forward_reference",
        ),
        (
            (
                _question(
                    "source",
                    field_type=QuestionFieldType.SINGLE_CHOICE,
                    options=["One", "Two"],
                ),
                _question(
                    "target", condition_question_key="source", condition_value="Three"
                ),
            ),
            "registration_setup_question_condition_value_invalid",
        ),
        (
            (
                _question(
                    "source",
                    field_type=QuestionFieldType.BOOLEAN,
                    visibility=QuestionVisibility.REGISTRATION_STAFF,
                ),
                _question(
                    "target", condition_question_key="source", condition_value="true"
                ),
            ),
            "registration_setup_question_condition_hidden_source",
        ),
    ],
)
def test_question_graph_rejects_ambiguous_or_hidden_conditions(
    questions: tuple[SimpleNamespace, ...],
    code: str,
) -> None:
    with pytest.raises(ValidationError) as error:
        commands._validate_question_graph(questions)
    assert _validation_code(error.value) == code


def test_question_graph_accepts_a_prior_visible_compatible_source() -> None:
    commands._validate_question_graph(
        (
            _question("source", field_type=QuestionFieldType.BOOLEAN),
            _question(
                "target", condition_question_key="source", condition_value="true"
            ),
        )
    )


def test_question_and_product_lookup_and_order_are_exact() -> None:
    first = _question("first")
    second = _question("second")
    scope = SimpleNamespace(questions=(first, second), products=())
    assert commands._question_by_id(scope, first.id) is first
    with pytest.raises(RegistrationSetupQuestionUnavailableError):
        commands._question_by_id(scope, uuid4())
    assert commands._ordered_questions(
        questions=scope.questions,
        question=second,
        after_question_id=None,
    ) == (second, first)
    with pytest.raises(ValidationError):
        commands._ordered_questions(
            questions=scope.questions,
            question=first,
            after_question_id=first.id,
        )
    with pytest.raises(RegistrationSetupQuestionUnavailableError):
        commands._ordered_questions(
            questions=scope.questions,
            question=first,
            after_question_id=uuid4(),
        )
    with pytest.raises(RegistrationSetupProductUnavailableError):
        commands._product_by_id(scope, uuid4())


def _profile_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "key": "arrival-note",
        "label": "Arrival note",
        "help_text": "A minimized current detail.",
        "field_type": QuestionFieldType.SHORT_TEXT,
        "options": [],
        "purpose": "Coordinate arrival.",
        "classification": "C2",
        "audience_policy": ProfileExtensionAudience.SELF,
        "audience_department_id": None,
        "attendee_visible": None,
        "writer_policy": ProfileExtensionWriter.ATTENDEE_AND_STAFF,
        "required": False,
    }
    values.update(overrides)
    return commands._profile_values(**values)


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        (
            {"key": "payment-status"},
            "registration_setup_profile_field_authoritative_key",
        ),
        (
            {"attendee_visible": True},
            "registration_setup_profile_field_audience_conflict",
        ),
        (
            {"audience_policy": ProfileExtensionAudience.DEPARTMENT},
            "registration_setup_profile_field_department_required",
        ),
        (
            {"audience_department_id": uuid4()},
            "registration_setup_profile_field_department_unexpected",
        ),
        (
            {
                "audience_policy": ProfileExtensionAudience.REGISTRATION_STAFF,
                "writer_policy": ProfileExtensionWriter.ATTENDEE,
            },
            "registration_setup_profile_field_writer_audience_conflict",
        ),
    ],
)
def test_profile_definition_rejects_authoritative_and_incoherent_policies(
    overrides: dict[str, object],
    code: str,
) -> None:
    with pytest.raises(ValidationError) as error:
        _profile_values(**overrides)
    assert _validation_code(error.value) == code


def test_profile_definition_supports_legacy_visibility_without_weakening_policy() -> (
    None
):
    values = _profile_values(
        audience_policy=None,
        attendee_visible=False,
        writer_policy=ProfileExtensionWriter.REGISTRATION_STAFF,
    )
    assert values["attendee_visible"] is False
    assert values["audience_policy"] == ProfileExtensionAudience.REGISTRATION_STAFF


def test_profile_definition_requires_exact_department_and_staff_writer() -> None:
    department_id = uuid4()
    values = _profile_values(
        audience_policy=ProfileExtensionAudience.DEPARTMENT,
        audience_department_id=department_id,
        writer_policy=ProfileExtensionWriter.REGISTRATION_STAFF,
    )
    assert values["audience_department_id"] == department_id
    assert values["attendee_visible"] is False


def test_profile_source_copying_remains_explicitly_fail_closed() -> None:
    scope = SimpleNamespace()
    assert commands._profile_source(
        scope=scope,
        source_template_id=None,
        source_prior_edition_id=None,
    ) == (None, None)
    with pytest.raises(ValidationError) as error:
        commands._profile_source(
            scope=scope,
            source_template_id=uuid4(),
            source_prior_edition_id=uuid4(),
        )
    assert (
        _validation_code(error.value)
        == "registration_setup_profile_field_source_conflict"
    )
    with pytest.raises(ValidationError) as error:
        commands._profile_source(
            scope=scope,
            source_template_id=uuid4(),
            source_prior_edition_id=None,
        )
    assert (
        _validation_code(error.value)
        == "registration_setup_profile_field_source_unsupported"
    )


def test_profile_lifecycle_and_exact_lookup_fail_closed() -> None:
    field = SimpleNamespace(id=uuid4())
    scope = SimpleNamespace(
        organization=SimpleNamespace(lifecycle=Organization.Lifecycle.ACTIVE),
        edition=SimpleNamespace(lifecycle=EventEdition.Lifecycle.DRAFT),
        fields=(field,),
    )
    commands._require_profile_lifecycle(scope)
    assert commands._profile_field_by_id(scope, field.id) is field
    with pytest.raises(RegistrationSetupProfileFieldUnavailableError):
        commands._profile_field_by_id(scope, uuid4())
    scope.edition.lifecycle = EventEdition.Lifecycle.LIVE
    with pytest.raises(RegistrationSetupLifecycleConflictError):
        commands._require_profile_lifecycle(scope)


def _profile_field(
    *,
    status: str,
    position: int,
    review_status: str = ProfileExtensionReviewStatus.APPROVED,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        status=status,
        position=position,
        review_status=review_status,
        approved_by=SimpleNamespace(id=uuid4()),
        approved_at=datetime(2027, 7, 1, tzinfo=UTC),
        last_changed_in_setup_version=1,
        updated_at=None,
        _state=SimpleNamespace(adding=False),
    )


def test_profile_ordering_keeps_fixed_history_and_invalidates_moved_review() -> None:
    fixed = _profile_field(status=ProfileExtensionStatus.ACTIVE, position=20)
    first = _profile_field(status=ProfileExtensionStatus.DRAFT, position=30)
    second = _profile_field(status=ProfileExtensionStatus.DRAFT, position=40)
    ordered = commands._ordered_profile_fields(
        fields=(first, second),
        field=second,
        after_field_id=None,
    )
    assert ordered == (second, first)
    changed_at = datetime(2027, 7, 2, tzinfo=UTC)
    changed = commands._renumber_profile_fields(
        all_fields=(fixed, first, second),
        ordered_drafts=ordered,
        resulting_version=8,
        changed_at=changed_at,
    )
    assert changed == ordered
    assert [item.position for item in ordered] == [30, 40]
    assert all(
        item.review_status == ProfileExtensionReviewStatus.PENDING for item in ordered
    )
    assert all(
        item.approved_by is None and item.approved_at is None for item in ordered
    )
    assert all(item.last_changed_in_setup_version == 8 for item in ordered)
    with pytest.raises(ValidationError):
        commands._ordered_profile_fields(
            fields=(first, second),
            field=first,
            after_field_id=first.id,
        )
    with pytest.raises(RegistrationSetupProfileFieldUnavailableError):
        commands._ordered_profile_fields(
            fields=(first, second),
            field=first,
            after_field_id=uuid4(),
        )
