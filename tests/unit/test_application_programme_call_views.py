"""Database-free request acceptance against real call forms and templates."""

from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID

import pytest
from bs4 import BeautifulSoup
from django.db import DatabaseError
from django.http import QueryDict
from django.test import RequestFactory
from django.urls import Resolver404, resolve

from maru.applications import programme_call_views as views
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError,
)
from maru.events.scheduling_queries import SchedulingEditionReference
from maru.workforce.queries import CurrentDepartmentLabelReference
from tests.unit.test_application_programme_call_editor import (
    _details_data,
    _evidence,
    _graph,
    _projection,
    _window_data,
)


@pytest.fixture(autouse=True)
def shell():
    with (
        patch.object(views.admin.site, "each_context", return_value={}),
        patch(
            "maru.events.templatetags.admin_edition_context.admin_shell_access",
            return_value={"workspace_available": False},
        ),
        patch(
            "maru.events.templatetags.admin_edition_context.project_shell_navigation",
            return_value={},
        ),
    ):
        yield


@pytest.fixture
def page(monkeypatch):
    actor, organization, edition = (UUID(int=i) for i in range(1, 4))
    graph = _graph()
    source = _projection(graph)
    auth = Mock(return_value=SimpleNamespace(accepts_private_planning_writes=True))
    monkeypatch.setattr(views, "authorize_programme_call_scope", auth)
    readers = {}
    for name, value in {
        "get_managed_programme_call_department": CurrentDepartmentLabelReference(
            graph.configuration.owner_department_id, "Programme Department"
        ),
        "get_managed_programme_call_configuration": source,
        "list_managed_programme_calls": (source.summary,),
    }.items():
        readers[name] = Mock(return_value=value)
        monkeypatch.setattr(views.queries, name, readers[name])
    edition_query = Mock(
        return_value=SchedulingEditionReference(
            organization_id=organization,
            edition_id=edition,
            version=3,
            accepts_scheduling_writes=True,
            zone_name="Europe/Budapest",
        )
    )
    monkeypatch.setattr(views, "resolve_scheduling_edition_reference", edition_query)
    writers = {}
    for name in (
        "configure_programme_call",
        "activate_programme_call",
        "retire_programme_call",
        "create_programme_call_successor",
    ):
        writers[name] = Mock(
            return_value=SimpleNamespace(target_id=source.summary.call_id)
        )
        monkeypatch.setattr(views.commands, name, writers[name])
    lock = Mock()
    monkeypatch.setattr(views, "lock_programme_edition_write_scope", lock)
    monkeypatch.setattr(views.transaction, "atomic", nullcontext)
    return SimpleNamespace(
        actor=actor,
        organization=organization,
        edition=edition,
        department=graph.configuration.owner_department_id,
        source=source,
        graph=graph,
        readers=readers,
        auth=auth,
        writers=writers,
        edition_query=edition_query,
        lock=lock,
    )


def call(
    page, task="overview", data=None, *, row=None, inventory=False, csrf=False, query=""
):
    path = (
        f"/admin/applications/programme-calls/{page.organization}/"
        f"{page.edition}/{page.department}/"
    )
    if not inventory:
        path += f"{page.source.summary.call_id}/{task}/"
        if row is not None:
            path += f"{row}/"
    if data is None:
        request = RequestFactory().get(path + query)
    else:
        encoded = data if isinstance(data, QueryDict) else QueryDict(mutable=True)
        if not isinstance(data, QueryDict):
            encoded.update(data)
        request = RequestFactory().post(
            path + query,
            data=encoded.urlencode(),
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
    return views.programme_calls(
        request,
        page.organization,
        page.edition,
        page.department,
        None if inventory else page.source.summary.call_id,
        task,
        row,
    )


def test_inventory_labels_only_complete_scoped_calls(page) -> None:
    """Scope choices identify real call names without proposal or holder data."""
    response = call(page, inventory=True)
    assert response.status_code == 200
    html = response.content.decode()
    assert "Programme Department" in html
    assert "Programme proposals" in html
    assert page.source.summary.call_id.hex not in html
    page.readers["get_managed_programme_call_configuration"].assert_not_called()
    kwargs = page.readers["list_managed_programme_calls"].call_args.kwargs
    assert kwargs["department_id"] == page.department
    assert kwargs["actor_id"] == page.actor
    assert kwargs["organization_id"] == page.organization
    assert kwargs["edition_id"] == page.edition
    assert kwargs["source_channel"] == "programme-call-workspace"


def test_overview_has_one_main_and_h1_with_complete_typed_configuration(page) -> None:
    """Present every question type, policy and bound without editable answers."""
    response = call(page)
    assert response.status_code == 200
    soup = BeautifulSoup(response.content, "html.parser")
    assert len(soup.select("h1")) == 1
    assert len(soup.select("main")) == 1
    assert not soup.select("form[data-call-command]")
    html = response.content.decode()
    for question in page.graph.definition.sections[0].questions:
        assert question.label in html
        assert str(question.field_type) in html
    assert "programme.collaboration.v3" in html
    assert "minimum 15, default 30, maximum 60" in html
    assert "private, no-store" in response["Cache-Control"]
    assert "nonce-" in response["Content-Security-Policy"]
    assert "nonce-'" not in response["Content-Security-Policy"]


@pytest.mark.parametrize(
    "task", ["details", "window", "track", "format", "contributor-field", "activate"]
)
def test_draft_tasks_have_associated_labels_and_original_evidence(
    page, task: str
) -> None:
    """Shared-shell forms retain current source identity without exposing a writer."""
    response = call(page, task)
    assert response.status_code == 200
    soup = BeautifulSoup(response.content, "html.parser")
    form = soup.select_one("form[data-call-command]")
    assert form is not None
    assert form.select_one('[name="expected_version"]')["value"] == "12"
    assert form.select_one('[name="retry_key"]')["value"]
    assert form.select_one('[name="csrfmiddlewaretoken"]')
    for field in form.select("input:not([type=hidden]), textarea, select"):
        assert form.select_one(f'label[for="{field["id"]}"]') is not None
    for writer in page.writers.values():
        writer.assert_not_called()


@pytest.mark.parametrize(
    "task",
    [
        "track",
        "format",
        "contributor-field",
        "remove-track",
        "remove-format",
        "remove-contributor-field",
    ],
)
def test_existing_row_forms_name_exact_current_selection(page, task: str) -> None:
    response = call(page, task, row=0)
    assert response.status_code == 200
    assert "Selected current entry:" in response.content.decode()


def test_metadata_post_preserves_all_other_graph_values(page) -> None:
    data = {**_details_data(page.graph), "name": "New call name"}
    response = call(page, "details", data)
    assert response.status_code == 302
    kwargs = page.writers["configure_programme_call"].call_args.kwargs
    assert kwargs["configuration"] == page.graph.configuration
    assert kwargs["definition_input"] == replace(
        page.graph.definition, name="New call name"
    )
    assert kwargs["owner_department_id"] == page.department
    assert kwargs["actor_id"] == page.actor
    assert kwargs["expected_version"] == 12
    assert str(kwargs["retry_key"]) == data["retry_key"]


def test_window_holds_canonical_edition_scope_through_owner_dispatch(page) -> None:
    response = call(page, "window", _window_data())
    assert response.status_code == 302
    page.lock.assert_called_once_with(
        actor_id=page.actor,
        organization_id=page.organization,
        edition_id=page.edition,
        department_ids=(page.department,),
    )
    assert page.edition_query.call_count == 2
    kwargs = page.writers["configure_programme_call"].call_args.kwargs
    assert kwargs["definition_input"].opens_at.hour == 10
    assert kwargs["configuration"] == page.graph.configuration
    assert "expected_edition_version" not in kwargs


def test_timezone_change_after_form_validation_refuses_writer(page) -> None:
    first = page.edition_query.return_value
    page.edition_query.side_effect = [first, replace(first, version=4, zone_name="UTC")]
    response = call(page, "window", _window_data())
    assert response.status_code == 409
    page.writers["configure_programme_call"].assert_not_called()
    assert "2027-01-01T10:00" in response.content.decode()


@pytest.mark.parametrize(
    ("task", "status", "writer"),
    [
        ("activate", "draft", "activate_programme_call"),
        ("retire", "active", "retire_programme_call"),
        ("successor", "retired", "create_programme_call_successor"),
    ],
)
def test_lifecycle_dispatch_uses_exact_existing_owner(
    page, task: str, status: str, writer: str
) -> None:
    page.readers["get_managed_programme_call_configuration"].return_value = replace(
        page.source, summary=replace(page.source.summary, status=status)
    )
    response = call(page, task, {**_evidence(), "confirm": "on"})
    assert response.status_code == 302
    page.writers[writer].assert_called_once()
    if writer != "configure_programme_call":
        page.writers["configure_programme_call"].assert_not_called()
    assert "confirm" not in page.writers[writer].call_args.kwargs


@pytest.mark.parametrize("status", ["active", "retired"])
def test_immutable_call_is_read_only_and_crafted_edit_is_denied(
    page, status: str
) -> None:
    page.readers["get_managed_programme_call_configuration"].return_value = replace(
        page.source, summary=replace(page.source.summary, status=status)
    )
    response = call(page, "details")
    assert response.status_code == 200
    assert "read-only" in response.content.decode()
    assert b"data-call-command" not in response.content
    assert call(page, "details", _details_data(page.graph)).status_code == 404
    page.writers["configure_programme_call"].assert_not_called()


@pytest.mark.parametrize("version", ["11", "13"])
def test_stale_input_keeps_original_cursor_retry_and_human_values(
    page, version: str
) -> None:
    data = {
        **_details_data(page.graph),
        "expected_version": version,
        "name": "Unsaved wording",
    }
    response = call(page, "details", data)
    assert response.status_code == 409
    soup = BeautifulSoup(response.content, "html.parser")
    assert soup.select_one('[name="expected_version"]')["value"] == version
    assert soup.select_one('[name="retry_key"]')["value"] == data["retry_key"]
    assert soup.select_one('[name="name"]')["value"] == "Unsaved wording"
    assert "may already have succeeded" in soup.get_text()
    page.writers["configure_programme_call"].assert_not_called()


@pytest.mark.parametrize(
    "field",
    [
        "owner_department_id",
        "actor_id",
        "sections",
        "eligibility_kind",
        "public_after_approval",
    ],
)
def test_closed_post_refuses_overrides_before_any_protected_query(
    page, field: str
) -> None:
    response = call(page, "details", {**_details_data(page.graph), field: "forged"})
    assert response.status_code == 400
    for reader in page.readers.values():
        reader.assert_not_called()


def test_duplicate_and_oversized_transport_is_rejected(page) -> None:
    data = QueryDict(mutable=True)
    data.update(_details_data(page.graph))
    data.appendlist("expected_version", "12")
    assert call(page, "details", data).status_code == 400
    assert (
        call(
            page, "details", {**_details_data(page.graph), "description": "x" * 6001}
        ).status_code
        == 400
    )
    page.auth.assert_not_called()


def test_csrf_is_enforced_before_domain_dispatch(page) -> None:
    assert (
        call(page, "details", _details_data(page.graph), csrf=True).status_code == 403
    )
    page.auth.assert_not_called()


def test_denial_precedes_identifying_labels_and_configuration(page) -> None:
    page.auth.side_effect = ApplicationsProgrammeAuthorizationDeniedError
    response = call(page)
    assert response.status_code == 404
    for reader in page.readers.values():
        reader.assert_not_called()
    assert b"Programme Department" not in response.content


def test_revocation_before_render_discards_prepared_content(page) -> None:
    page.auth.side_effect = [
        SimpleNamespace(accepts_private_planning_writes=True),
        ApplicationsProgrammeAuthorizationDeniedError,
    ]
    response = call(page)
    assert response.status_code == 404
    assert b"Programme proposals" not in response.content


@pytest.mark.parametrize(
    "reader",
    [
        "get_managed_programme_call_department",
        "get_managed_programme_call_configuration",
    ],
)
def test_dependency_failure_never_releases_partial_content(page, reader: str) -> None:
    page.readers[reader].side_effect = DatabaseError("private provider detail")
    response = call(page)
    assert response.status_code == 503
    assert b"private provider detail" not in response.content
    assert b"Programme proposals" not in response.content


def test_empty_inventory_is_truthful_without_executable_creation(page) -> None:
    page.readers["list_managed_programme_calls"].return_value = ()
    response = call(page, inventory=True)
    assert response.status_code == 200
    assert b"No calls are available" in response.content
    assert b"Call creation" in response.content
    assert b"/create/" not in response.content


def test_route_is_reserved_but_not_production_mounted(page) -> None:
    path = (
        f"/admin/applications/programme-calls/{page.organization}/"
        f"{page.edition}/{page.department}/"
    )
    assert (
        resolve(path, urlconf="maru.applications.programme_call_urls").func
        is views.programme_calls
    )
    try:
        match = resolve(path)
    except Resolver404:
        return
    assert match.func is not views.programme_calls


def test_human_task_order_current_navigation_and_action_label(page) -> None:
    soup = BeautifulSoup(call(page, "details").content, "html.parser")
    labels = [
        label.get_text() for label in soup.select("form[data-call-command] label")
    ]
    assert labels[0] == "Call name:"
    assert labels[-1] == "Reason:"
    assert soup.select_one('[aria-current="page"]').get_text() == "Details and policy"
    assert (
        soup.select_one("form[data-call-command] button").get_text()
        == "Save details and policy"
    )


def test_catalog_add_edit_remove_passes_complete_graph_to_owner(page) -> None:
    data = {
        **_evidence(),
        "code": "art",
        "label": "Arts",
        "description": "Art sessions",
        "position": "2",
    }
    assert call(page, "track", data).status_code == 302
    graph = page.writers["configure_programme_call"].call_args.kwargs["configuration"]
    assert [row.code for row in graph.tracks] == ["culture", "art", "science"]
    assert graph.formats == page.graph.configuration.formats
    assert call(page, "track", data, row=0).status_code == 302
    graph = page.writers["configure_programme_call"].call_args.kwargs["configuration"]
    assert [row.code for row in graph.tracks] == ["science", "art"]
    assert (
        call(page, "remove-format", {**_evidence(), "confirm": "on"}, row=0).status_code
        == 302
    )
    graph = page.writers["configure_programme_call"].call_args.kwargs["configuration"]
    assert [row.code for row in graph.formats] == ["panel"]
    assert graph.formats[0].position == 1


def test_removal_cannot_drop_required_lead_name_or_skip_confirmation(page) -> None:
    data = {**_evidence(), "confirm": "on"}
    assert call(page, "remove-contributor-field", data, row=0).status_code == 400
    assert call(page, "remove-track", _evidence(), row=0).status_code == 400
    page.writers["configure_programme_call"].assert_not_called()


def test_closed_planning_is_read_only_without_cross_purpose_privileges(page) -> None:
    page.auth.return_value.accepts_private_planning_writes = False
    assert call(page).status_code == 200
    assert b"/details/" not in call(page).content
    assert call(page, "activate", {**_evidence(), "confirm": "on"}).status_code == 404
    page.writers["activate_programme_call"].assert_not_called()


def test_incomplete_activation_is_an_actionable_bound_form(page) -> None:
    page.writers[
        "activate_programme_call"
    ].side_effect = views.commands.ApplicationsProgrammeCompletenessError(
        "private implementation"
    )
    response = call(page, "activate", {**_evidence(), "confirm": "on"})
    assert response.status_code == 400
    assert b"The call is incomplete" in response.content
    assert b"private implementation" not in response.content
    assert b'data-call-pending="true"' in response.content


def test_overflow_is_not_a_partial_inventory(page) -> None:
    page.readers[
        "list_managed_programme_calls"
    ].side_effect = views.queries.ApplicationsProgrammeProjectionOverflowError
    response = call(page, inventory=True)
    assert response.status_code == 503
    assert b"Programme Department" not in response.content


@pytest.mark.parametrize(
    "failure",
    [
        views.commands.ApplicationsProgrammeVersionConflictError,
        views.commands.ApplicationsProgrammeIdempotencyConflictError,
        views.commands.ApplicationsProgrammeStateConflictError,
    ],
)
def test_owner_conflicts_retain_original_input_without_false_failure_claim(
    page, failure
) -> None:
    page.writers["configure_programme_call"].side_effect = failure
    response = call(
        page, "details", {**_details_data(page.graph), "name": "Retain this title"}
    )
    assert response.status_code == 409
    assert b"Retain this title" in response.content
    assert b"may already have succeeded" in response.content
