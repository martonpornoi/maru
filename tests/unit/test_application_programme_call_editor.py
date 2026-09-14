"""Lossless form-task composition without database access or authority mocks."""

from dataclasses import asdict, fields, replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.http import QueryDict

from maru.applications import programme_call_editor as editor
from maru.applications import programme_call_forms as forms
from maru.applications import programme_inputs as inputs
from maru.applications import programme_queries as queries


def _question(
    kind: inputs.ProgrammeCallQuestionType, position: int
) -> inputs.ProgrammeCallQuestionInput:
    choices = kind in ("single_choice", "multiple_choice")
    numeric = kind in ("integer", "decimal")
    text = kind in ("short_text", "long_text", "email", "phone", "url")
    return inputs.ProgrammeCallQuestionInput(
        key=kind.replace("_", "-"),
        field_type=kind,
        label=f"Question {position}",
        help_text="Specific guidance\nSecond line",
        position=position,
        required=True,
        options=(
            (
                inputs.ProgrammeCallQuestionOptionInput("talk", "Talk"),
                inputs.ProgrammeCallQuestionOptionInput("panel", "Panel"),
            )
            if choices
            else ()
        ),
        minimum_length=3 if text else None,
        maximum_length=160 if text else None,
        minimum_value=Decimal(-12) if numeric else None,
        maximum_value=Decimal(24) if numeric else None,
        maximum_choices=2 if kind == "multiple_choice" else None,
        reference_kind="programme.person" if kind.endswith("reference") else "",
        condition=None,
        purpose="Review proposed Programme content.",
        classification="C3",
        retention_policy_code="programme.question.v1",
    )


def _graph() -> editor.ProgrammeCallEditorInputs:
    return editor.ProgrammeCallEditorInputs(
        inputs.ProgrammeCallDefinitionInput(
            code="programme-2027",
            name="Programme proposals",
            description="Tell us about the proposed session.",
            purpose="Assess proposals for the convention Programme.",
            classification="C3",
            maximum_submissions_per_person=7,
            opens_at=datetime(2027, 1, 1, tzinfo=UTC),
            closes_at=datetime(2027, 3, 1, tzinfo=UTC),
            applicant_edit_until=datetime(2027, 2, 1, tzinfo=UTC),
            audience_policy_code="programme.audience.v1",
            retention_policy_code="programme.retention.v2",
            sections=(
                inputs.ProgrammeCallSectionInput(
                    "proposal",
                    "Proposed session",
                    "Section guidance",
                    1,
                    tuple(
                        _question(kind, position)
                        for position, kind in enumerate(
                            inputs.ProgrammeCallQuestionType, 1
                        )
                    ),
                ),
            ),
        ),
        inputs.ProgrammeCallConfigurationInput(
            owner_department_id=uuid4(),
            maximum_collaborators=4,
            content_policy_code="programme.content.v1",
            contributor_consent_policy_code="programme.consent.v2",
            collaboration_retention_policy_code="programme.collaboration.v3",
            tracks=(
                inputs.ProgrammeCallTrackInput("culture", "Culture", "Guidance", 1),
                inputs.ProgrammeCallTrackInput("science", "Science", "Other", 2),
            ),
            formats=(
                inputs.ProgrammeCallFormatInput(
                    "talk", "Talk", "Spoken", 1, 15, 30, 60
                ),
                inputs.ProgrammeCallFormatInput(
                    "panel", "Panel", "Group", 2, 30, 60, 90
                ),
            ),
            contributor_fields=tuple(
                inputs.ProgrammeCallContributorFieldInput(
                    code,
                    "required" if position == 1 else "optional",
                    "optional",
                    position,
                )
                for position, code in enumerate(inputs.ProgrammeContributorFieldCode, 1)
            ),
        ),
    )


def _projection(
    graph: editor.ProgrammeCallEditorInputs,
) -> queries.ProgrammeCallConfigurationProjection:
    definition, configuration = graph.definition, graph.configuration
    sections = []
    for section in definition.sections:
        questions = []
        for question in section.questions:
            values = asdict(question)
            values["options"] = tuple(
                queries.ProgrammeQuestionOptionProjection(option.code, option.label)
                for option in question.options
            )
            values["condition"] = (
                tuple(sorted(asdict(question.condition).items()))
                if question.condition
                else ()
            )
            questions.append(
                queries.ProgrammeQuestionProjection(question_id=uuid4(), **values)
            )
        sections.append(
            queries.ProgrammeSectionProjection(
                uuid4(),
                section.key,
                section.title,
                section.help_text,
                section.position,
                tuple(questions),
            )
        )
    return queries.ProgrammeCallConfigurationProjection(
        summary=queries.ProgrammeCallSummary(
            call_id=uuid4(),
            definition_id=uuid4(),
            code=definition.code,
            version=3,
            aggregate_version=12,
            status="draft",
            name=definition.name,
            description=definition.description,
            opens_at=definition.opens_at,
            closes_at=definition.closes_at,
            applicant_edit_until=definition.applicant_edit_until,
            owner_department_id=configuration.owner_department_id,
        ),
        purpose=definition.purpose,
        classification=str(definition.classification),
        eligibility_kind="authenticated_person",
        maximum_submissions_per_person=definition.maximum_submissions_per_person,
        audience_policy_code=definition.audience_policy_code,
        retention_policy_code=definition.retention_policy_code,
        maximum_collaborators=configuration.maximum_collaborators,
        content_policy_code=configuration.content_policy_code,
        contributor_consent_policy_code=configuration.contributor_consent_policy_code,
        collaboration_retention_policy_code=configuration.collaboration_retention_policy_code,
        tracks=tuple(
            queries.ProgrammeTrackProjection(track_id=uuid4(), **asdict(row))
            for row in configuration.tracks
        ),
        formats=tuple(
            queries.ProgrammeFormatProjection(format_id=uuid4(), **asdict(row))
            for row in configuration.formats
        ),
        contributor_fields=tuple(
            queries.ProgrammeContributorFieldProjection(**asdict(row))
            for row in configuration.contributor_fields
        ),
        sections=tuple(sections),
    )


def test_round_trip_preserves_every_question_type_policy_and_bound() -> None:
    """Retain the complete typed graph, not a convenient text-question subset."""
    graph = _graph()
    source = _projection(graph)
    assert editor.programme_call_editor_inputs(source, expected_version=12) == graph
    assert len(graph.definition.sections[0].questions) == 17
    assert {field.name for field in fields(queries.ProgrammeQuestionProjection)} == {
        field.name for field in fields(inputs.ProgrammeCallQuestionInput)
    } | {"question_id"}


@pytest.mark.parametrize(
    ("key", "operator", "value"),
    [
        ("short-text", "equals", "A title"),
        ("integer", "equals", 2),
        ("boolean", "equals", False),
        ("single-choice", "equals", "panel"),
        ("multiple-choice", "contains", "talk"),
    ],
)
def test_round_trip_preserves_typed_condition_semantics(
    key: str, operator: str, value: str | int | bool
) -> None:
    """Keep false, integer, text and choice comparisons distinct."""
    graph = _graph()
    section = graph.definition.sections[0]
    conditional = replace(
        section.questions[0],
        key="follow-up",
        position=len(section.questions) + 1,
        condition=inputs.ProgrammeCallQuestionConditionInput(key, operator, value),
    )
    graph = replace(
        graph,
        definition=replace(
            graph.definition,
            sections=(replace(section, questions=(*section.questions, conditional)),),
        ),
    )
    assert (
        editor.programme_call_editor_inputs(_projection(graph), expected_version=12)
        == graph
    )


@pytest.mark.parametrize("status", ["active", "retired", "unknown"])
def test_non_draft_configuration_cannot_be_composed(status: str) -> None:
    """A form adapter cannot quietly make active or retired content editable."""
    source = _projection(_graph())
    source = replace(source, summary=replace(source.summary, status=status))
    with pytest.raises(editor.ProgrammeCallEditorConflictError):
        editor.programme_call_editor_inputs(source, expected_version=12)


@pytest.mark.parametrize("version", [0, 11, 13])
def test_source_cursor_never_rebases_to_latest_version(version: int) -> None:
    """A small task form does not overwrite unseen intervening graph changes."""
    with pytest.raises(editor.ProgrammeCallEditorConflictError):
        editor.programme_call_editor_inputs(
            _projection(_graph()), expected_version=version
        )


@pytest.mark.parametrize("version", [True, -1, "12", 12.0, None])
def test_source_cursor_uses_owner_strict_type_contract(version: object) -> None:
    """Reject numeric aliases before constructing input intent."""
    with pytest.raises(ValidationError):
        editor.programme_call_editor_inputs(
            _projection(_graph()), expected_version=version
        )  # type: ignore[arg-type]


def test_unsupported_eligibility_is_not_silently_normalized() -> None:
    """Keep legacy eligibility paths closed instead of stripping their policy."""
    source = replace(_projection(_graph()), eligibility_kind="registered_attendee")
    with pytest.raises(ValidationError):
        editor.programme_call_editor_inputs(source, expected_version=12)


@pytest.mark.parametrize(
    "condition",
    [
        (("question_key", "short-text"),),
        (("question_key", "short-text"), ("operator", "equals"), ("value", {})),
        (("question_key", "short-text"), ("operator", "equals"), ("value", 1.0)),
        (
            ("question_key", "short-text"),
            ("operator", "equals"),
            ("value", "x"),
            ("extra", True),
        ),
        (
            ("question_key", "short-text"),
            ("operator", "equals"),
            ("operator", "equals"),
        ),
    ],
)
def test_malformed_stored_condition_never_loses_fields(condition: tuple) -> None:
    """Fail closed on unsupported source shape instead of dropping metadata."""
    source = _projection(_graph())
    section = source.sections[0]
    source = replace(
        source,
        sections=(
            replace(
                section,
                questions=(
                    replace(section.questions[0], condition=condition),
                    *section.questions[1:],
                ),
            ),
        ),
    )
    with pytest.raises(ValidationError):
        editor.programme_call_editor_inputs(source, expected_version=12)


@pytest.mark.parametrize(
    ("operation", "catalog"),
    [
        (editor.edit_programme_call_track, "tracks"),
        (editor.edit_programme_call_format, "formats"),
        (editor.edit_programme_call_contributor_field, "contributor_fields"),
    ],
)
def test_one_catalog_edit_preserves_unrelated_graph(operation, catalog: str) -> None:
    """Explicit form movement is stable and changes only the named catalog."""
    graph = _graph()
    rows = getattr(graph.configuration, catalog)
    moved = replace(rows[-1], position=1)
    changed = operation(graph, index=len(rows) - 1, value=moved)
    assert changed.definition == graph.definition
    expected = (
        moved,
        *(replace(row, position=i + 2) for i, row in enumerate(rows[:-1])),
    )
    assert changed.configuration == replace(graph.configuration, **{catalog: expected})
    assert getattr(graph.configuration, catalog) == rows


def test_add_then_remove_track_has_no_unrelated_effect() -> None:
    """A labelled new track and explicit removal round-trip without graph drift."""
    graph = _graph()
    value = inputs.ProgrammeCallTrackInput("arts", "Arts", "New track", 2)
    changed = editor.edit_programme_call_track(graph, index=None, value=value)
    assert [row.code for row in changed.configuration.tracks] == [
        "culture",
        "arts",
        "science",
    ]
    assert editor.edit_programme_call_track(changed, index=1, value=None) == graph


@pytest.mark.parametrize("index", [True, -1, 2, "0", 0.0])
def test_exact_row_selection_rejects_aliases_and_absent_rows(index: object) -> None:
    """No negative indexing or boolean alias can choose a different row."""
    with pytest.raises(ValidationError):
        editor.edit_programme_call_track(_graph(), index=index, value=None)  # type: ignore[arg-type]


def test_missing_removal_target_is_not_a_noop_success() -> None:
    """Require a real row before reporting explicit removal intent."""
    with pytest.raises(ValidationError):
        editor.edit_programme_call_track(_graph(), index=None, value=None)


def test_invalid_position_is_not_clamped_or_appended() -> None:
    """Do not reinterpret an out-of-range ordering choice."""
    graph = _graph()
    with pytest.raises(ValidationError):
        editor.edit_programme_call_track(
            graph, index=0, value=replace(graph.configuration.tracks[0], position=4)
        )


def test_catalog_limits_and_required_profile_policy_remain_authoritative() -> None:
    """Whole typed configuration validation survives small task edits."""
    graph = _graph()
    with pytest.raises(ValidationError):
        editor.edit_programme_call_contributor_field(graph, index=0, value=None)
    single = replace(
        graph,
        configuration=replace(
            graph.configuration, tracks=(graph.configuration.tracks[0],)
        ),
    )
    with pytest.raises(ValidationError):
        editor.edit_programme_call_track(single, index=0, value=None)
    with pytest.raises(ValidationError):
        editor.edit_programme_call_track(
            graph, index=None, value=replace(graph.configuration.tracks[0], position=3)
        )


def test_question_edit_preserves_all_other_types_and_policies() -> None:
    """An ordinary label edit cannot simplify unrelated fields or visibility."""
    graph = _graph()
    section = graph.definition.sections[0]
    changed_question = replace(section.questions[0], label="Revised title")
    changed = editor.edit_programme_call_question(
        graph, section_index=0, index=0, value=changed_question
    )
    assert changed.configuration == graph.configuration
    assert changed.definition == replace(
        graph.definition,
        sections=(
            replace(section, questions=(changed_question, *section.questions[1:])),
        ),
    )
    assert all(
        not question.staff_writable
        for question in changed.definition.sections[0].questions
    )


def test_remove_or_move_condition_source_is_rejected_without_auto_repair() -> None:
    """Preserve dependent-question semantics; do not silently erase a condition."""
    graph = _graph()
    first = graph.definition.sections[0].questions[0]
    dependent = replace(
        first,
        key="follow-up",
        position=2,
        condition=inputs.ProgrammeCallQuestionConditionInput(
            first.key, "equals", "Talk"
        ),
    )
    graph = replace(
        graph,
        definition=replace(
            graph.definition,
            sections=(
                replace(graph.definition.sections[0], questions=(first, dependent)),
            ),
        ),
    )
    for value in (None, replace(first, position=2)):
        with pytest.raises(ValidationError):
            editor.edit_programme_call_question(
                graph, section_index=0, index=0, value=value
            )
    assert graph.definition.sections[0].questions == (first, dependent)


def test_section_insert_remove_and_question_empty_guard() -> None:
    """Sections stay nonempty and the final form cannot be removed."""
    graph = _graph()
    first = graph.definition.sections[0]
    section = replace(
        first,
        key="additional",
        position=2,
        questions=(replace(first.questions[0], key="additional-title", position=1),),
    )
    changed = editor.edit_programme_call_section(graph, index=None, value=section)
    assert editor.edit_programme_call_section(changed, index=1, value=None) == graph
    with pytest.raises(ValidationError):
        editor.edit_programme_call_question(
            changed, section_index=1, index=0, value=None
        )
    with pytest.raises(ValidationError):
        editor.edit_programme_call_section(graph, index=0, value=None)


@pytest.mark.parametrize("index", [True, -1, 1, "0", 0.0])
def test_question_task_requires_exact_section(index: object) -> None:
    """Reject absent and aliased sections before any graph transformation."""
    with pytest.raises(ValidationError):
        editor.edit_programme_call_question(
            _graph(), section_index=index, index=0, value=None
        )  # type: ignore[arg-type]


def _evidence() -> dict[str, str]:
    return {
        "retry_key": str(uuid4()),
        "expected_version": "12",
        "reason": "Reviewed call configuration.",
    }


def _details_data(graph: editor.ProgrammeCallEditorInputs) -> dict[str, str]:
    form = forms.ProgrammeCallDetailsForm(inputs=graph)
    return {**_evidence(), **{name: str(value) for name, value in form.initial.items()}}


def test_details_preserve_graph_owner_and_deadline_precision() -> None:
    """Changing a title cannot round an unrelated deadline or alter ownership."""
    graph = _graph()
    graph = replace(
        graph,
        definition=replace(
            graph.definition,
            opens_at=graph.definition.opens_at.replace(second=29, microsecond=123),
        ),
    )
    data = {**_details_data(graph), "name": "  Revised   call name  "}
    form = forms.ProgrammeCallDetailsForm(data, inputs=graph)
    assert form.is_valid(), form.errors
    assert form.result == replace(
        graph, definition=replace(graph.definition, name="Revised call name")
    )
    assert form.cleaned_data["expected_version"] == 12
    assert str(form.cleaned_data["retry_key"]) == data["retry_key"]


@pytest.mark.parametrize(
    "field",
    [
        "owner_department_id",
        "department_id",
        "edition_id",
        "organization_id",
        "actor_id",
        "code",
        "sections",
        "source_binding",
        "opens_at",
        "eligibility_kind",
        "reviewer_visible",
    ],
)
def test_details_reject_scope_graph_and_legacy_overrides(field: str) -> None:
    """Task-specific forms cannot widen their documented input purpose."""
    graph = _graph()
    form = forms.ProgrammeCallDetailsForm(
        {**_details_data(graph), field: "injected"}, inputs=graph
    )
    assert not form.is_valid()
    assert form.result is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("classification", ""),
        ("classification", "C4"),
        ("classification", "C1"),
        ("maximum_collaborators", "17"),
        ("maximum_collaborators", "00"),
        ("maximum_submissions_per_person", "0"),
        ("retention_policy_code", ""),
        ("audience_policy_code", ""),
        ("reason", "bad\x01control"),
    ],
)
def test_details_revalidate_whole_graph_policy(field: str, value: str) -> None:
    """Owner policy applies even when individual fields look valid."""
    graph = _graph()
    form = forms.ProgrammeCallDetailsForm(
        {**_details_data(graph), field: value}, inputs=graph
    )
    assert not form.is_valid()
    assert form.result is None


def test_duplicate_fields_retain_original_input() -> None:
    """Refuse duplicate scalars without refreshing command evidence."""
    graph = _graph()
    data = QueryDict(mutable=True)
    data.update(_details_data(graph))
    data.appendlist("name", "Second name")
    form = forms.ProgrammeCallDetailsForm(data, inputs=graph)
    assert not form.is_valid()
    assert form["expected_version"].value() == "12"
    assert form["retry_key"].value() == data["retry_key"]
    assert form.result is None


def _window_data() -> dict[str, str]:
    return {
        **_evidence(),
        "expected_edition_version": "3",
        "opens_at": "2027-01-01T10:00",
        "applicant_edit_until": "2027-02-01T10:00",
        "closes_at": "2027-03-01T10:00",
        "confirm": "on",
    }


def test_window_form_converts_only_explicit_edition_zone_intent() -> None:
    """Native-minute replacement is distinct from metadata changes."""
    graph = _graph()
    form = forms.ProgrammeCallWindowForm(
        _window_data(), inputs=graph, edition_time_zone="Europe/Budapest"
    )
    assert form.is_valid(), form.errors
    assert form.result is not None
    assert form.result.definition.opens_at.astimezone(UTC) == datetime(
        2027, 1, 1, 9, tzinfo=UTC
    )
    assert form.result.configuration == graph.configuration
    assert form.result.definition.sections == graph.definition.sections
    initial = forms.ProgrammeCallWindowForm(
        inputs=graph, edition_time_zone="Europe/Budapest"
    )
    assert initial["opens_at"].value() == "2027-01-01T01:00"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("confirm", ""),
        ("opens_at", "2027-03-28T02:30"),
        ("opens_at", "2027-10-31T02:30"),
        ("opens_at", "2027-01-01T10:00:01"),
        ("opens_at", "2027-01-01T10:00Z"),
        ("applicant_edit_until", "2026-12-01T10:00"),
        ("applicant_edit_until", "2027-04-01T10:00"),
        ("closes_at", "2027-01-01T10:00"),
    ],
)
def test_window_rejects_ambiguous_or_unconfirmed_intent(field: str, value: str) -> None:
    """No guessed DST fold, rounding, reversed window or implicit confirmation."""
    form = forms.ProgrammeCallWindowForm(
        {**_window_data(), field: value},
        inputs=_graph(),
        edition_time_zone="Europe/Budapest",
    )
    assert not form.is_valid()
    assert form.result is None


def test_track_and_format_forms_normalize_owner_inputs() -> None:
    """Human labels coexist with strict codes, positions and durations."""
    data = {
        **_evidence(),
        "code": "new-track",
        "label": "  New   track  ",
        "description": "Guidance\r\nNext line",
        "position": "1",
    }
    track = forms.ProgrammeCallTrackForm(data)
    assert track.is_valid(), track.errors
    assert track.track_input(track.cleaned_data) == inputs.ProgrammeCallTrackInput(
        "new-track", "New track", "Guidance\nNext line", 1
    )
    durations = {
        "minimum_duration_minutes": "15",
        "default_duration_minutes": "30",
        "maximum_duration_minutes": "60",
    }
    format_form = forms.ProgrammeCallFormatForm({**data, **durations})
    assert format_form.is_valid(), format_form.errors
    assert (
        format_form.format_input(format_form.cleaned_data).default_duration_minutes
        == 30
    )
    invalid = forms.ProgrammeCallFormatForm(
        {**data, **durations, "default_duration_minutes": "90"}
    )
    assert not invalid.is_valid()
    assert "default_duration_minutes" in invalid.errors


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("code", "new_track"),
        ("code", "UPPER"),
        ("position", "01"),
        ("position", "0"),
        ("position", "65"),
        ("label", "bad\x01label"),
    ],
)
def test_track_rejects_malformed_codes_and_numeric_aliases(
    field: str, value: str
) -> None:
    """Do not silently rewrite unsupported stable identifiers or ordering."""
    form = forms.ProgrammeCallTrackForm(
        {
            **_evidence(),
            "code": "talk",
            "label": "Talk",
            "description": "",
            "position": "1",
            field: value,
        }
    )
    assert not form.is_valid()


@pytest.mark.parametrize(
    ("lead", "collaborator", "valid"),
    [
        ("required", "optional", True),
        ("optional", "required", True),
        ("hidden", "optional", True),
        ("hidden", "hidden", False),
        ("", "required", False),
        ("required", "", False),
        ("required", "invented", False),
    ],
)
def test_contributor_policy_is_explicit_not_a_person_profile(
    lead: str, collaborator: str, valid: bool
) -> None:
    """Collection policy neither collects nor grants access to personal values."""
    form = forms.ProgrammeCallContributorFieldForm(
        {
            **_evidence(),
            "field_code": "biography",
            "lead_requirement": lead,
            "collaborator_requirement": collaborator,
            "position": "2",
        }
    )
    assert form.is_valid() is valid
    assert "biography" not in form.fields
    assert "account_id" not in form.fields
