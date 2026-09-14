"""Database-free acceptance for explicit call creation and structured graph tasks."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from bs4 import BeautifulSoup
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import QueryDict
from django.test import RequestFactory

from maru.applications import programme_call_composer_forms as forms
from maru.applications import programme_call_composer_views as views
from maru.applications.programme_inputs import ProgrammeCallQuestionConditionInput
from tests.unit.test_application_programme_call_editor import (
    _details_data,
    _evidence,
    _graph,
    _projection,
)
from tests.unit.test_application_programme_call_views import call, page, shell

__all__ = ["page", "shell"]


def _new_data():
    return {
        **_details_data(_graph()),
        "expected_version": "0",
        "expected_edition_version": "3",
        "code": "programme-2027",
        "opens_at": "2027-01-01T10:00",
        "applicant_edit_until": "2027-02-01T10:00",
        "closes_at": "2027-03-01T10:00",
        "track_code": "culture",
        "track_label": "Culture",
        "format_code": "talk",
        "format_label": "Talk",
        "minimum_duration_minutes": "15",
        "default_duration_minutes": "30",
        "maximum_duration_minutes": "60",
        "confirm": "on",
    }


def _question_data(question):
    data = {}
    for name in forms.ProgrammeQuestionForm.base_fields:
        value = getattr(question, name, "")
        if value is None:
            value = ""
        if type(value) is bool:
            value = "on" if value else ""
        data[f"question-{name}"] = str(value)
    if question.condition is not None:
        condition = question.condition
        value = (
            str(condition.value).lower()
            if type(condition.value) is bool
            else str(condition.value)
        )
        data.update(
            {
                "question-condition_question": condition.question_key,
                "question-condition_operator": condition.operator,
                "question-condition_value": value,
            }
        )
    data.update(
        {
            "options-TOTAL_FORMS": str(max(2, len(question.options))),
            "options-INITIAL_FORMS": str(len(question.options)),
            "options-MIN_NUM_FORMS": "0",
            "options-MAX_NUM_FORMS": "100",
        }
    )
    for index, option in enumerate(question.options):
        data[f"options-{index}-code"] = option.code
        data[f"options-{index}-label"] = option.label
    return data


def _request(
    page, *, task="create", section=None, row=None, data=None, csrf=False, query=""
):
    root = (
        f"/admin/applications/programme-calls/{page.organization}/"
        f"{page.edition}/{page.department}/"
    )
    path = root + (
        "new/" if task == "create" else f"{page.source.summary.call_id}/compose/{task}/"
    )
    if data is None:
        request = RequestFactory().get(path + query)
    else:
        encoded = data if isinstance(data, QueryDict) else QueryDict(mutable=True)
        if not isinstance(data, QueryDict):
            encoded.update(data)
        request = RequestFactory().post(
            path + query,
            encoded.urlencode(),
            content_type="application/x-www-form-urlencoded",
        )
    request.user = SimpleNamespace(
        pk=page.actor,
        is_authenticated=True,
        is_active=True,
        is_staff=False,
        is_superuser=False,
    )
    request._dont_enforce_csrf_checks = not csrf
    with (
        patch.object(views, "resolve_scheduling_edition_reference", page.edition_query),
        patch.object(views, "lock_programme_edition_write_scope", page.lock),
    ):
        return views.programme_call_composer(
            request,
            page.organization,
            page.edition,
            page.department,
            call_id=None if task == "create" else page.source.summary.call_id,
            task=task,
            section=section,
            row=row,
        )


def test_create_form_is_complete_explicit_and_edition_local():
    form = forms.ProgrammeCallCreationForm(
        _new_data(), edition_time_zone="Europe/Budapest"
    )
    assert form.is_valid(), form.errors
    graph = form.call_inputs(
        owner_department_id=_graph().configuration.owner_department_id
    )
    assert graph.definition.opens_at.hour == 10
    assert graph.definition.opens_at.utcoffset().total_seconds() == 3600
    assert [question.key for question in graph.definition.sections[0].questions] == [
        "title",
        "description",
    ]
    assert all(question.required for question in graph.definition.sections[0].questions)
    assert graph.configuration.contributor_fields[0].lead_requirement == "required"
    assert (
        graph.configuration.contributor_fields[0].collaborator_requirement == "optional"
    )
    assert graph.configuration.formats[0].default_duration_minutes == 30
    assert form.cleaned_data["expected_version"] == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("expected_version", "1"),
        ("expected_version", "00"),
        ("expected_edition_version", "0"),
        ("confirm", ""),
        ("code", "Uppercase"),
        ("track_code", "bad code"),
        ("content_policy_code", ""),
        ("opens_at", "2027-03-28T02:30"),
        ("opens_at", "2027-10-31T02:30"),
    ],
)
def test_creation_refuses_invalid_scalar_or_dst(field, value):
    form = forms.ProgrammeCallCreationForm(
        {**_new_data(), field: value}, edition_time_zone="Europe/Budapest"
    )
    assert not form.is_valid()
    assert field in form.errors


@pytest.mark.parametrize(
    ("field", "value"),
    [("closes_at", "2026-01-01T10:00"), ("minimum_duration_minutes", "90")],
)
def test_creation_rechecks_complete_graph(field, value):
    form = forms.ProgrammeCallCreationForm(
        {**_new_data(), field: value}, edition_time_zone="Europe/Budapest"
    )
    assert form.is_valid(), form.errors
    with pytest.raises(ValidationError):
        form.call_inputs(owner_department_id=_graph().configuration.owner_department_id)


@pytest.mark.parametrize(
    "question", _graph().definition.sections[0].questions, ids=lambda q: q.field_type
)
def test_every_question_type_round_trips_through_controls(question):
    form = forms.ProgrammeQuestionForm(
        _question_data(question), prefix="question", earlier_questions=()
    )
    assert form.is_valid(), form.errors
    assert form.question_input(question.options) == question


@pytest.mark.parametrize(
    ("kind", "value", "expected"),
    [
        ("boolean", "true", True),
        ("boolean", "false", False),
        ("integer", "-12", -12),
        ("short_text", "Exact text", "Exact text"),
    ],
)
def test_condition_type_is_derived_from_earlier_source(kind, value, expected):
    questions = _graph().definition.sections[0].questions
    source = next(q for q in questions if q.field_type == kind)
    question = replace(
        questions[0],
        key="conditional",
        condition=ProgrammeCallQuestionConditionInput(source.key, "equals", expected),
    )
    form = forms.ProgrammeQuestionForm(
        _question_data(question), prefix="question", earlier_questions=(source,)
    )
    assert form.is_valid(), form.errors
    result = form.question_input(())
    assert result.condition.value == expected
    assert type(result.condition.value) is type(expected)


@pytest.mark.parametrize("original", [None, "", "0", "03", "invalid"])
def test_creation_malformed_original_edition_version_is_bound_400_without_write(
    page, original
):
    data = _new_data()
    if original is None:
        data.pop("expected_edition_version")
    else:
        data["expected_edition_version"] = original
    response = _request(page, data=data)
    assert response.status_code == 400
    assert b"Review this request" in response.content
    assert all(not writer.called for writer in page.writers.values())
    soup = BeautifulSoup(response.content, "html.parser")
    assert soup.select_one('[name="code"]')["value"] == data["code"]
    assert soup.select_one('[name="retry_key"]')["value"] == data["retry_key"]
    assert soup.select_one('[name="expected_edition_version"]').get("value", "") == (
        original or ""
    )


def test_creation_get_has_explicit_starting_policy_and_no_mutation(page):
    response = _request(page)
    assert response.status_code == 200
    soup = BeautifulSoup(response.content, "html.parser")
    assert len(soup.select("h1")) == len(soup.select("main")) == 1
    assert "Starting configuration to review" in soup.get_text()
    assert "optional for collaborators" in soup.get_text()
    assert soup.select_one('[name="expected_version"]')["value"] == "0"
    assert all(not writer.called for writer in page.writers.values())


def test_creation_dispatches_existing_owner_inside_zone_fence(page, monkeypatch):
    writer = Mock(return_value=SimpleNamespace(target_id=page.source.summary.call_id))
    monkeypatch.setattr(views.commands, "create_programme_call", writer)
    response = _request(page, data=_new_data())
    assert response.status_code == 302, response.content.decode()
    assert writer.call_count == page.lock.call_count == 1
    assert writer.call_args.kwargs["expected_version"] == 0
    assert (
        writer.call_args.kwargs["configuration"].owner_department_id == page.department
    )
    assert "confirm" not in writer.call_args.kwargs
    assert page.edition_query.call_count == 2


def test_creation_zone_change_refuses_before_writer_and_retains_input(
    page, monkeypatch
):
    original = page.edition_query.return_value
    page.edition_query.side_effect = [
        original,
        replace(original, version=4, zone_name="UTC"),
    ]
    writer = Mock()
    monkeypatch.setattr(views.commands, "create_programme_call", writer)
    data = _new_data()
    response = _request(page, data=data)
    assert response.status_code == 409
    assert not writer.called
    soup = BeautifulSoup(response.content, "html.parser")
    assert soup.select_one('[name="expected_edition_version"]')["value"] == "3"
    assert soup.select_one('[name="retry_key"]')["value"] == data["retry_key"]
    assert soup.select_one('[name="opens_at"]')["value"] == data["opens_at"]


@pytest.mark.parametrize("row", range(17))
def test_question_edit_dispatches_lossless_complete_graph(page, row):
    question = page.graph.definition.sections[0].questions[row]
    data = {
        **_evidence(),
        **_question_data(question),
        "question-label": "Revised label",
    }
    response = _request(page, task="question", section=0, row=row, data=data)
    assert response.status_code == 302, response.content.decode()
    kwargs = page.writers["configure_programme_call"].call_args.kwargs
    expected = list(page.graph.definition.sections[0].questions)
    expected[row] = replace(question, label="Revised label")
    assert kwargs["definition_input"].sections[0].questions == tuple(expected)
    assert kwargs["configuration"] == page.graph.configuration
    assert kwargs["definition_input"].opens_at == page.graph.definition.opens_at


def test_option_row_addition_does_not_dispatch_and_retains_evidence(page):
    question = page.graph.definition.sections[0].questions[5]
    data = {
        **_evidence(),
        **_question_data(question),
        "intent": "add-option",
        "question-label": "Unsaved title",
    }
    response = _request(page, task="question", section=0, row=5, data=data)
    assert response.status_code == 200
    assert not page.writers["configure_programme_call"].called
    soup = BeautifulSoup(response.content, "html.parser")
    assert soup.select_one('[name="options-TOTAL_FORMS"]')["value"] == "3"
    assert soup.select_one('[name="options-2-code"]').has_attr("autofocus")
    assert soup.select_one('[name="question-label"]')["value"] == "Unsaved title"
    assert soup.select_one('[name="retry_key"]')["value"] == data["retry_key"]


def test_stale_question_post_preserves_input_without_rebase(page):
    question = page.graph.definition.sections[0].questions[0]
    data = {
        **_evidence(),
        **_question_data(question),
        "expected_version": "11",
        "question-label": "Stale private title",
    }
    response = _request(page, task="question", section=0, row=0, data=data)
    assert response.status_code == 409
    assert not page.writers["configure_programme_call"].called
    soup = BeautifulSoup(response.content, "html.parser")
    assert soup.select_one('[name="expected_version"]')["value"] == "11"
    assert soup.select_one('[name="question-label"]')["value"] == "Stale private title"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("owner_department_id", "foreign"),
        ("question-source_binding", "identity"),
        ("question-public_after_approval", "on"),
        ("options-100-code", "bad"),
        ("options-TOTAL_FORMS", "101"),
    ],
)
def test_unknown_or_unbounded_transport_is_rejected_before_private_reads(
    page, field, value
):
    question = page.graph.definition.sections[0].questions[0]
    response = _request(
        page,
        task="question",
        section=0,
        row=0,
        data={**_evidence(), **_question_data(question), field: value},
    )
    assert response.status_code == 400
    assert not page.readers["get_managed_programme_call_configuration"].called
    assert all(not writer.called for writer in page.writers.values())


def _section_data(*, key="new-section", position="2"):
    return {
        "section-key": key,
        "section-title": "Additional questions",
        "section-help_text": "Only relevant information.",
        "section-position": position,
    }


def test_section_creation_includes_first_question_atomically(page):
    question = replace(
        page.graph.definition.sections[0].questions[0], key="new-question", position=1
    )
    data = {**_evidence(), **_section_data(), **_question_data(question)}
    response = _request(page, task="section", data=data)
    assert response.status_code == 302
    writer = page.writers["configure_programme_call"]
    assert writer.call_count == 1
    result = writer.call_args.kwargs["definition_input"]
    assert len(result.sections) == 2
    assert result.sections[0] == page.graph.definition.sections[0]
    assert result.sections[1].questions == (question,)


def test_section_metadata_preserves_every_question(page):
    data = {**_evidence(), **_section_data(key="proposal", position="1")}
    response = _request(page, task="section", section=0, data=data)
    assert response.status_code == 302
    result = page.writers["configure_programme_call"].call_args.kwargs[
        "definition_input"
    ]
    assert result.sections[0].questions == page.graph.definition.sections[0].questions
    assert result.sections[0].title == "Additional questions"


def test_question_insertion_and_confirmed_removal(page):
    question = replace(
        page.graph.definition.sections[0].questions[0], key="new-question", position=18
    )
    response = _request(
        page,
        task="question",
        section=0,
        data={**_evidence(), **_question_data(question)},
    )
    assert response.status_code == 302
    writer = page.writers["configure_programme_call"]
    assert (
        writer.call_args.kwargs["definition_input"].sections[0].questions[-1]
        == question
    )
    writer.reset_mock()
    response = _request(
        page,
        task="remove-question",
        section=0,
        row=0,
        data={**_evidence(), "confirm": "on"},
    )
    assert response.status_code == 302
    remaining = writer.call_args.kwargs["definition_input"].sections[0].questions
    assert len(remaining) == 16
    assert remaining[0].position == 1
    assert remaining[0].key == page.graph.definition.sections[0].questions[1].key
    assert "confirm" not in writer.call_args.kwargs


@pytest.mark.parametrize("confirm", ["", None])
def test_removal_requires_deliberate_confirmation(page, confirm):
    data = _evidence()
    if confirm is not None:
        data["confirm"] = confirm
    response = _request(page, task="remove-question", section=0, row=0, data=data)
    assert response.status_code == 400
    assert not page.writers["configure_programme_call"].called


def test_last_section_removal_is_refused_without_partial_graph(page):
    response = _request(
        page, task="remove-section", section=0, data={**_evidence(), "confirm": "on"}
    )
    assert response.status_code == 400
    assert not page.writers["configure_programme_call"].called


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate-option",
        "partial-option",
        "wrong-initial",
        "invalid-bound",
        "later-condition",
        "duplicate-key",
    ],
)
def test_whole_question_graph_errors_retain_original_intent(page, mutation):
    question = page.graph.definition.sections[0].questions[5]
    data = {**_evidence(), **_question_data(question)}
    changes = {
        "duplicate-option": {"options-1-code": data["options-0-code"]},
        "partial-option": {"options-1-label": ""},
        "wrong-initial": {"options-INITIAL_FORMS": "0"},
        "invalid-bound": {"question-maximum_length": "50"},
        "later-condition": {
            "question-condition_question": "email",
            "question-condition_operator": "equals",
            "question-condition_value": "person@example.invalid",
        },
        "duplicate-key": {"question-key": "short-text"},
    }
    data.update(changes[mutation])
    response = _request(page, task="question", section=0, row=5, data=data)
    assert response.status_code == 400
    assert not page.writers["configure_programme_call"].called
    soup = BeautifulSoup(response.content, "html.parser")
    assert soup.select_one('[name="retry_key"]')["value"] == data["retry_key"]


@pytest.mark.parametrize("raw", ["True", "1", "yes", " false "])
def test_boolean_condition_rejects_ambiguous_coercion(raw):
    source = _graph().definition.sections[0].questions[4]
    question = _graph().definition.sections[0].questions[0]
    data = _question_data(question)
    data.update(
        {
            "question-condition_question": source.key,
            "question-condition_operator": "equals",
            "question-condition_value": raw,
        }
    )
    form = forms.ProgrammeQuestionForm(
        data, prefix="question", earlier_questions=(source,)
    )
    assert form.is_valid()
    with pytest.raises(ValidationError):
        form.question_input(())


@pytest.mark.parametrize(
    "raw", ["-0", "+1", "01", "1.0", "1e3", "2147483648", "-2147483649", "\u0661"]
)
def test_integer_condition_rejects_aliases_and_overflow(raw):
    source = _graph().definition.sections[0].questions[2]
    question = _graph().definition.sections[0].questions[0]
    data = _question_data(question)
    data.update(
        {
            "question-condition_question": source.key,
            "question-condition_operator": "equals",
            "question-condition_value": raw,
        }
    )
    form = forms.ProgrammeQuestionForm(
        data, prefix="question", earlier_questions=(source,)
    )
    assert form.is_valid()
    with pytest.raises(ValidationError):
        form.question_input(())


@pytest.mark.parametrize(
    ("section", "row", "version", "expected"),
    [(99, 0, "11", 409), (0, 99, "11", 409), (99, 0, "12", 400), (0, 99, "12", 400)],
)
def test_missing_original_row_never_crashes_or_rebases(
    page, section, row, version, expected
):
    question = page.graph.definition.sections[0].questions[0]
    data = {**_evidence(), **_question_data(question), "expected_version": version}
    response = _request(page, task="question", section=section, row=row, data=data)
    assert response.status_code == expected
    assert not page.writers["configure_programme_call"].called
    soup = BeautifulSoup(response.content, "html.parser")
    assert soup.select_one('[name="expected_version"]')["value"] == version
    assert soup.select_one('[name="question-label"]')["value"] == question.label


def test_csrf_and_repeated_command_evidence_are_rejected(page):
    assert _request(page, data=_new_data(), csrf=True).status_code == 403
    assert not page.readers["get_managed_programme_call_department"].called
    data = QueryDict(mutable=True)
    data.update(_new_data())
    data.appendlist("expected_version", "0")
    assert _request(page, data=data).status_code == 400
    assert not page.readers["get_managed_programme_call_department"].called


@pytest.mark.parametrize("state", ["active", "retired"])
def test_immutable_call_is_read_only_and_refuses_composer_post(page, state):
    source = replace(page.source, summary=replace(page.source.summary, status=state))
    page.readers["get_managed_programme_call_configuration"].return_value = source
    response = _request(page, task="section", section=0)
    assert response.status_code == 200
    assert b"read-only" in response.content
    assert b"data-call-command" not in response.content
    response = _request(
        page,
        task="section",
        section=0,
        data={**_evidence(), **_section_data(position="1")},
    )
    assert response.status_code == 404
    assert not page.writers["configure_programme_call"].called


def test_denied_scope_never_resolves_labels_or_calls(page):
    page.auth.side_effect = views.ApplicationsProgrammeAuthorizationDeniedError
    response = _request(page)
    assert response.status_code == 404
    assert not any(reader.called for reader in page.readers.values())
    assert b"Programme Department" not in response.content


def test_required_read_dependency_failure_is_nondisclosing(page):
    page.readers["get_managed_programme_call_department"].side_effect = DatabaseError(
        "private internal detail"
    )
    response = _request(page)
    assert response.status_code == 503
    assert b"private internal detail" not in response.content


def test_creation_owner_failure_never_claims_success(page, monkeypatch):
    writer = Mock(side_effect=DatabaseError("private failure"))
    monkeypatch.setattr(views.commands, "create_programme_call", writer)
    response = _request(page, data=_new_data())
    assert response.status_code == 503
    assert "Location" not in response
    assert b"private failure" not in response.content


def _two_sections(page, *, dependent=False, single_source=False):
    first = page.graph.definition.sections[0]
    questions = first.questions[:1] if single_source else first.questions
    if dependent:
        questions = (
            questions[0],
            replace(
                questions[1],
                condition=ProgrammeCallQuestionConditionInput(
                    questions[0].key, "equals", "Trigger text"
                ),
            ),
            *questions[2:],
        )
    first = replace(first, questions=questions)
    second = replace(
        first,
        key="second",
        title="Second section",
        position=2,
        questions=(replace(first.questions[0], key="second-title", position=1),),
    )
    graph = replace(
        page.graph, definition=replace(page.graph.definition, sections=(first, second))
    )
    source = _projection(graph)
    source = replace(
        source, summary=replace(source.summary, call_id=page.source.summary.call_id)
    )
    page.graph, page.source = graph, source
    page.readers["get_managed_programme_call_configuration"].return_value = source
    return graph


def test_cross_section_move_is_one_complete_owner_command(page):
    graph = _two_sections(page)
    question = replace(graph.definition.sections[0].questions[0], position=2)
    data = {
        **_evidence(),
        **_question_data(question),
        "question-destination_section": "second",
    }
    response = _request(page, task="question", section=0, row=0, data=data)
    assert response.status_code == 302
    writer = page.writers["configure_programme_call"]
    assert writer.call_count == 1
    result = writer.call_args.kwargs["definition_input"]
    assert len(result.sections[0].questions) == 16
    assert result.sections[1].questions == (
        *graph.definition.sections[1].questions,
        question,
    )


@pytest.mark.parametrize("case", ["dependent", "empty-source", "unknown-destination"])
def test_cross_section_move_preserves_dependency_and_nonempty_guards(page, case):
    graph = _two_sections(
        page, dependent=case == "dependent", single_source=case == "empty-source"
    )
    question = replace(graph.definition.sections[0].questions[0], position=2)
    data = {
        **_evidence(),
        **_question_data(question),
        "question-destination_section": "foreign"
        if case == "unknown-destination"
        else "second",
    }
    response = _request(page, task="question", section=0, row=0, data=data)
    assert response.status_code == 400
    assert not page.writers["configure_programme_call"].called


def test_overview_links_to_exact_section_and_question_tasks(page):
    response = call(page)
    soup = BeautifulSoup(response.content, "html.parser")
    section_link = soup.find("a", string="Add a question to Proposed session")
    question_link = soup.find("a", string="Edit or reorder Question 1")
    assert section_link["href"].endswith("/compose/question/0/")
    assert question_link["href"].endswith("/compose/question/0/0/")


def test_creation_groups_and_all_labels_are_unique(page):
    soup = BeautifulSoup(_request(page).content, "html.parser")
    form = soup.select_one("[data-call-command]")
    ids = [element["id"] for element in soup.select("[id]")]
    assert len(ids) == len(set(ids))
    assert [legend.get_text() for legend in form.select("legend")] == [
        "Call identity and collection",
        "Explicit policy references",
        "Edition-local deadlines",
        "Initial track and format",
        "Confirm this starting draft",
    ]
    for field in form.select("input:not([type=hidden]), select, textarea"):
        assert soup.find("label", attrs={"for": field["id"]}) is not None


def test_partial_option_error_links_to_the_exact_control(page):
    question = page.graph.definition.sections[0].questions[5]
    data = {**_evidence(), **_question_data(question), "options-1-label": ""}
    soup = BeautifulSoup(
        _request(page, task="question", section=0, row=5, data=data).content,
        "html.parser",
    )
    link = soup.select_one('[role="alert"] a[href="#id_options-1-label"]')
    assert link is not None
    assert "Option 2" in link.parent.get_text()
    assert (
        soup.find("label", attrs={"for": "id_options-1-DELETE"}).get_text()
        == "Remove this option from the draft:"
    )
