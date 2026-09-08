"""HTTP dispatch and native workspace contracts, not provisioned runtime proof."""

from dataclasses import replace
from html.parser import HTMLParser
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import QueryDict
from django.template.loader import render_to_string
from django.test import RequestFactory

from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.scheduling import planning_actions, planning_record_actions
from maru.scheduling import planning_views as views
from maru.scheduling import planning_workspace as workspace
from maru.scheduling.authorization import (
    MANAGE_CANDIDATES,
    VIEW_CONFLICTS,
    VIEW_HISTORY,
    VIEW_PLANNING,
    SchedulingAuthorizationDeniedError,
)
from maru.scheduling.catalogs import SchedulingConflictCode, SchedulingConflictSeverity
from maru.scheduling.catalogs import SchedulingOperation as Op
from maru.scheduling.command_support import (
    SchedulingCommandResult,
    SchedulingIdempotencyConflictError,
    SchedulingLifecycleConflictError,
    SchedulingLimitError,
    SchedulingUnavailableError,
    SchedulingVersionConflictError,
)
from maru.scheduling.conflicts import SchedulingFinding
from maru.scheduling.planning_inspector import PlanningItemInspector, PlanningItemLayer
from maru.scheduling.planning_presentation import describe_planning_findings
from maru.scheduling.planning_preview import PREVIEW_FIELDS
from maru.scheduling.planning_queries import (
    HISTORY_FIELDS,
    PLANNING_FIELDS,
    PlanningHistoryPage,
)
from maru.scheduling.planning_selection import PlanningSelection
from maru.venues.scheduling_queries import (
    VenueSchedulingSourceDeniedError,
    VenueSchedulingSourceUnavailableError,
)
from maru.venues.services import (
    VenueAuthorizationDeniedError,
    VenueAvailabilityConflictError,
    VenueBookingOverlapError,
    VenueCapacityConflictError,
    VenueRetryConflictError,
    VenueStateConflictError,
    VenueVersionConflictError,
)
from maru.venues.timetable_queries import VenueTimetableQueryDeniedError
from tests.unit import test_scheduling_planning_board as board_helpers
from tests.unit import test_scheduling_planning_controls as control_helpers

board_inputs = board_helpers.board_inputs
controls = control_helpers.controls


@pytest.fixture
def http_world(controls, monkeypatch):
    snapshot, board, selection, sources = controls
    world = {
        "snapshot": snapshot,
        "actor_id": uuid4(),
        "organization_id": uuid4(),
        "edition_id": uuid4(),
        "selection": replace(selection, history_id=None, conflict_id=None),
        "sources": sources,
        "denied": set(),
        "reads": [],
        "policies": [],
    }

    def planning_read(scope, *, candidate_id=None, authorizer=None):
        world["reads"].append((scope, candidate_id))
        current = world["snapshot"]
        if candidate_id is None:
            return replace(current, selected_candidate_id=None, placements=())
        if candidate_id not in {candidate.id for candidate in current.candidates}:
            raise SchedulingUnavailableError
        return replace(current, selected_candidate_id=candidate_id)

    def authorize(**kwargs):
        world["policies"].append(kwargs)
        if kwargs["capability_code"] in world["denied"]:
            raise SchedulingAuthorizationDeniedError

    monkeypatch.setattr(views, "load_scheduling_planning", planning_read)
    monkeypatch.setattr(workspace, "authorize_scheduling_scope", authorize)
    items = tuple({entry.item.item.id: entry.item for entry in board.entries}.values())
    monkeypatch.setattr(
        workspace, "list_programme_timetable_items", Mock(return_value=items)
    )
    monkeypatch.setattr(
        workspace, "list_venue_timetable_spaces", Mock(return_value=board.spaces)
    )
    monkeypatch.setattr(
        workspace,
        "load_scheduling_host_requirements",
        Mock(return_value=sources["hosts"]),
    )
    monkeypatch.setattr(
        workspace,
        "load_scheduling_candidate_review",
        Mock(return_value=sources["review"]),
    )
    monkeypatch.setattr(
        workspace,
        "load_scheduling_reservation_review",
        Mock(return_value=sources["reservation"]),
    )
    monkeypatch.setattr(
        workspace, "load_scheduling_item_inspector", Mock(return_value=None)
    )
    monkeypatch.setattr(
        workspace,
        "load_scheduling_historical_manifest",
        Mock(return_value=sources["history"]),
    )
    monkeypatch.setattr(
        workspace, "list_scheduling_candidate_history", Mock(return_value=None)
    )
    monkeypatch.setattr(planning_actions, "_authorize", Mock())
    monkeypatch.setattr(planning_record_actions, "_authorize", Mock())
    return world


def request_page(
    world,
    data=None,
    *,
    method=None,
    path="/synthetic-planning/",
    authenticated=True,
    csrf=True,
):
    verb = method or ("POST" if data is not None else "GET")
    request = RequestFactory().generic(
        verb,
        path,
        data=data.urlencode() if data is not None else "",
        content_type="application/x-www-form-urlencoded",
    )
    request.user = SimpleNamespace(pk=world["actor_id"], is_authenticated=authenticated)
    request._dont_enforce_csrf_checks = csrf
    response = views.scheduling_planning_view(
        request,
        organization_id=world["organization_id"],
        edition_id=world["edition_id"],
        edition_label="Synthetic private edition",
    )
    return request, response


def selected_post(world, *, mode="overview", action="select", **changes):
    selection = replace(world["selection"], mode=mode, **changes)
    data = QueryDict(mutable=True)
    for name, value in selection.hidden_values():
        data[name] = value
    data["action"] = action
    return data


def command_post(world, *, mode=Op.CANDIDATE_ARCHIVE, **changes):
    _request, response = request_page(world, selected_post(world, mode=mode))
    assert response.status_code == 200
    form = response.context_data["control"].form
    action = "preview_placement" if mode == "placement" else mode
    data = control_helpers.submitted(
        form, action, reason="Explicit synthetic action", **changes
    )
    for name, value in response.context_data["selection_state"]:
        data[name] = value
    return data


def rendered(response):
    return render_to_string(
        response.template_name, {**response.context_data, "csrf_token": "synthetic"}
    )


def test_get_has_no_implicit_candidate_or_writer_and_computes_field_ceiling_access(
    http_world,
):
    request, response = request_page(http_world)
    assert response.status_code == 200
    assert response.context_data["selection"] == PlanningSelection()
    assert response.context_data["control"] is None
    assert response.context_data["board"].candidate is None
    assert len(http_world["reads"]) == 1
    assert request.sensitive_post_parameters == "__ALL__"
    assert "no-store" in response.headers["Cache-Control"]
    assert views.scheduling_planning_view._non_atomic_requests == {"default"}
    policy = {
        value["capability_code"]: value["requested_fields"]
        for value in http_world["policies"]
    }
    assert policy[VIEW_PLANNING] == PLANNING_FIELDS
    assert policy[VIEW_HISTORY] == HISTORY_FIELDS
    assert policy[VIEW_CONFLICTS] == PREVIEW_FIELDS
    workspace.load_scheduling_host_requirements.assert_not_called()
    workspace.load_scheduling_item_inspector.assert_not_called()
    workspace.load_scheduling_candidate_review.assert_not_called()
    workspace.load_scheduling_reservation_review.assert_not_called()
    planning_record_actions._authorize.assert_not_called()


def test_native_workspace_selection_retains_filtered_out_target_and_complete_choices(
    http_world,
):
    data = selected_post(http_world, mode="placement", text="No such title")
    _request, response = request_page(http_world, data)
    assert response.status_code == 200
    context = response.context_data
    assert context["board"].entries == ()
    assert len(context["complete_board"].entries) == 4
    assert context["selection_hidden"]
    assert (
        context["control"].form["occurrence_id"].value()
        == http_world["selection"].occurrence_id
    )
    html = rendered(response)
    assert "outside the visible filters" in html
    assert "Clear filters" in html
    assert "No entries match these filters" in html
    elements = board_helpers.Elements(html).elements
    assert sum(tag == "h1" for tag, _ in elements) == 1
    assert sum(tag == "main" for tag, _ in elements) == 1
    ids = [attrs["id"] for _, attrs in elements if "id" in attrs]
    assert len(ids) == len(set(ids))
    assert 'name="actor_id"' not in html
    assert 'name="organization_id"' not in html
    assert 'name="edition_id"' not in html


def test_clear_filters_keeps_selected_candidate_and_occurrence(http_world):
    data = selected_post(
        http_world,
        action="clear_filters",
        text="hidden",
        state="unplaced",
        space_id=http_world["snapshot"].placements[0].space_id,
    )
    _request, response = request_page(http_world, data)
    selection = response.context_data["selection"]
    assert (selection.text, selection.state, selection.day_id, selection.space_id) == (
        "",
        "all",
        None,
        None,
    )
    assert selection.candidate_id == http_world["selection"].candidate_id
    assert selection.occurrence_id == http_world["selection"].occurrence_id


@pytest.mark.parametrize(
    "attack",
    [
        "query_url",
        "unknown_selection",
        "repeat_selection",
        "repeat_action",
        "unknown_action",
        "action_mode",
        "query_command_fields",
    ],
)
def test_invalid_request_never_reaches_owner_labels_or_commands(http_world, attack):
    data = selected_post(http_world)
    path = "/synthetic-planning/"
    if attack == "query_url":
        path += "?ui_text=private"
    elif attack == "unknown_selection":
        data["ui_actor_id"] = str(uuid4())
    elif attack == "repeat_selection":
        data.appendlist("ui_item_id", str(uuid4()))
    elif attack == "repeat_action":
        data.appendlist("action", "candidate_create")
    elif attack == "unknown_action":
        data["action"] = "publish"
    elif attack == "action_mode":
        data["action"] = "save_placement"
    else:
        data["expected_version"] = "1"
    _request, response = request_page(http_world, data, path=path)
    assert response.status_code == 400
    assert "board" not in response.context_data
    workspace.list_programme_timetable_items.assert_not_called()
    planning_record_actions._authorize.assert_not_called()


@pytest.mark.parametrize("kind", ["anonymous", "csrf", "base_denied", "method"])
def test_authentication_csrf_base_scope_and_method_fail_before_post_selection(
    http_world, monkeypatch, kind
):
    parser = Mock(side_effect=AssertionError("Private POST selection was parsed"))
    monkeypatch.setattr(views, "_selection", parser)
    if kind == "base_denied":
        monkeypatch.setattr(
            views,
            "load_scheduling_planning",
            Mock(side_effect=SchedulingAuthorizationDeniedError),
        )
    _request, response = request_page(
        http_world,
        selected_post(http_world),
        authenticated=kind != "anonymous",
        csrf=kind != "csrf",
        method="DELETE" if kind == "method" else "POST",
    )
    assert response.status_code == (405 if kind == "method" else 403)
    assert "no-store" in response.headers["Cache-Control"]
    parser.assert_not_called()
    workspace.list_programme_timetable_items.assert_not_called()


@pytest.mark.parametrize(
    ("source", "error"),
    [
        ("list_programme_timetable_items", ProgrammeAuthorizationDeniedError),
        ("list_venue_timetable_spaces", VenueTimetableQueryDeniedError),
        ("load_scheduling_host_requirements", SchedulingAuthorizationDeniedError),
    ],
)
def test_late_owner_denial_withholds_all_previously_loaded_private_context(
    http_world, source, error
):
    getattr(workspace, source).side_effect = error(
        "Private failure details must stay hidden"
    )
    _request, response = request_page(
        http_world, selected_post(http_world, mode="placement")
    )
    assert response.status_code == 403
    assert set(response.context_data) == {"failure_message"}
    html = rendered(response)
    assert "Opening workshop" not in html
    assert "Synthetic private edition" not in html
    assert "Private failure details" not in html
    assert "Synthetic host" not in html


@pytest.mark.parametrize("capability", [MANAGE_CANDIDATES, VIEW_CONFLICTS])
def test_edit_permission_does_not_imply_read_permission_or_vice_versa(
    http_world, capability
):
    http_world["denied"].add(capability)
    _request, response = request_page(
        http_world, selected_post(http_world, mode="placement")
    )
    assert response.status_code == 403
    workspace.list_programme_timetable_items.assert_not_called()
    workspace.load_scheduling_host_requirements.assert_not_called()


def test_copy_of_current_draft_still_requires_independent_history_permission(
    http_world,
):
    http_world["denied"].add(VIEW_HISTORY)
    _request, response = request_page(http_world)
    modes = {mode for mode, _label in response.context_data["mode_choices"]}
    assert Op.CANDIDATE_COPY not in modes
    workspace.list_programme_timetable_items.reset_mock()
    _request, response = request_page(
        http_world, selected_post(http_world, mode=Op.CANDIDATE_COPY)
    )
    assert response.status_code == 403
    workspace.list_programme_timetable_items.assert_not_called()


def test_uncertain_command_result_never_claims_that_no_change_completed(
    http_world, monkeypatch
):
    data = command_post(http_world, confirm="confirmed")
    monkeypatch.setattr(
        planning_record_actions,
        "archive_scheduling_candidate",
        Mock(side_effect=DatabaseError("private connection detail")),
    )
    _request, response = request_page(http_world, data)
    html = rendered(response)
    assert response.status_code == 503
    assert "Action needs attention" in html
    assert "Completion could not be confirmed" in html
    assert "do not assume the change failed" in html
    assert "Action not completed" not in html
    assert (
        response.context_data["control"].form["retry_key"].value() == data["retry_key"]
    )


def test_record_post_uses_actual_strict_adapter_and_trusted_actor_scope(
    http_world, monkeypatch
):
    data = command_post(http_world, confirm="confirmed")
    submitted_key = data["retry_key"]
    old = http_world["snapshot"].candidates[0]
    calls = []

    def archive(command, **kwargs):
        calls.append((command, kwargs))
        http_world["snapshot"] = replace(
            http_world["snapshot"],
            candidates=(replace(old, version=4, lifecycle="archived"),),
        )
        return SchedulingCommandResult(uuid4(), old.id, 4, 9)

    monkeypatch.setattr(
        planning_record_actions, "archive_scheduling_candidate", archive
    )
    _request, response = request_page(http_world, data)
    assert response.status_code == 200
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command.actor_id == http_world["actor_id"]
    assert command.organization_id == http_world["organization_id"]
    assert command.edition_id == http_world["edition_id"]
    assert str(command.idempotency_key) == submitted_key
    assert kwargs["expected_version"] == 3
    assert response.context_data["board"].candidate.version == 4
    assert response.context_data["board"].candidate.lifecycle == "archived"
    assert response.context_data["control"] is None
    assert "Command completed" in response.context_data["status_message"]


@pytest.mark.parametrize(
    "attack", ["actor_id", "organization_id", "edition_id", "unexpected"]
)
def test_command_scope_injection_stays_invalid_without_any_writer(
    http_world, monkeypatch, attack
):
    data = command_post(http_world, confirm="confirmed")
    data[attack] = str(uuid4())
    writer = Mock()
    monkeypatch.setattr(planning_record_actions, "archive_scheduling_candidate", writer)
    _request, response = request_page(http_world, data)
    assert response.status_code == 400
    form = response.context_data["control"].form
    assert form.errors
    assert attack in str(form.non_field_errors())
    assert form.data[attack] == data[attack]
    writer.assert_not_called()
    assert "status_message" not in response.context_data


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (SchedulingVersionConflictError, 409),
        (SchedulingIdempotencyConflictError, 409),
        (SchedulingLifecycleConflictError, 409),
        (SchedulingLimitError, 409),
        (SchedulingUnavailableError, 503),
        (DatabaseError, 503),
        (ValidationError, 400),
    ],
)
def test_command_failures_keep_pending_input_and_never_expose_raw_errors(
    http_world, monkeypatch, error, status
):
    data = command_post(http_world, confirm="confirmed")
    writer = Mock(side_effect=error("Secret internal record details"))
    monkeypatch.setattr(planning_record_actions, "archive_scheduling_candidate", writer)
    _request, response = request_page(http_world, data)
    assert response.status_code == status
    form = response.context_data["control"].form
    assert form["retry_key"].value() == data["retry_key"]
    assert form["expected_version"].value() == "3"
    assert form["reason"].value() == data["reason"]
    assert form.initial == {}
    assert "Secret internal" not in rendered(response)
    assert "status_message" not in response.context_data
    writer.assert_called_once()


def test_preview_is_non_mutating_and_retains_form_and_retry(http_world, monkeypatch):
    data = command_post(http_world, mode="placement")
    preview = http_world["sources"]["review"].current
    monkeypatch.setattr(
        planning_actions, "preview_scheduling_candidate", Mock(return_value=preview)
    )
    writer = Mock()
    monkeypatch.setattr(planning_actions, "set_scheduling_placement", writer)
    _request, response = request_page(http_world, data)
    assert response.status_code == 200
    assert response.context_data["preview"] is preview
    assert (
        response.context_data["control"].form["retry_key"].value() == data["retry_key"]
    )
    assert "Preview only" in response.context_data["status_message"]
    writer.assert_not_called()


@pytest.mark.parametrize("layer", list(PlanningItemLayer))
def test_workspace_loads_only_the_explicitly_selected_inspector_layer(
    http_world, layer
):
    _request, response = request_page(
        http_world, selected_post(http_world, layer=layer)
    )
    assert response.status_code == 200
    read = workspace.load_scheduling_item_inspector
    read.assert_called_once()
    assert read.call_args.kwargs["layer"] is layer
    assert read.call_args.kwargs["item_id"] == http_world["selection"].item_id
    workspace.load_scheduling_host_requirements.assert_not_called()
    workspace.load_scheduling_candidate_review.assert_not_called()


def test_history_and_compare_revisions_are_independent_reads_with_exact_cursor(
    http_world,
):
    source = http_world["sources"]["history"].entry.revision_id
    other = uuid4()
    _request, response = request_page(
        http_world,
        selected_post(
            http_world,
            mode="history",
            history_id=source,
            compare_id=other,
            before_version=7,
        ),
    )
    assert response.status_code == 200
    assert (
        workspace.list_scheduling_candidate_history.call_args.kwargs["before_version"]
        == 7
    )
    assert [
        call.kwargs["revision_id"]
        for call in workspace.load_scheduling_historical_manifest.call_args_list
    ] == [source, other]
    assert response.context_data["changes"] == ()


def test_populated_history_retains_exact_selections_and_native_field_cardinality(
    http_world,
):
    source = http_world["sources"]["history"]
    manifest = replace(
        source,
        entry=replace(source.entry, placement_count=1),
        placements=(http_world["snapshot"].placements[0],),
    )
    workspace.load_scheduling_historical_manifest.return_value = manifest
    workspace.list_scheduling_candidate_history.return_value = PlanningHistoryPage(
        (manifest.entry,), 1
    )
    _request, response = request_page(
        http_world,
        selected_post(
            http_world,
            mode="history",
            history_id=manifest.entry.revision_id,
            compare_id=manifest.entry.revision_id,
            before_version=2,
        ),
    )
    assert response.status_code == 200
    html = rendered(response)
    assert "Current item label: Opening workshop" in html
    assert "Unchanged: current item label Opening workshop" in html
    assert "Earlier reason" in html
    assert "Older revisions" in html
    parsed = NativeFormShape(html)
    assert not parsed.nested
    for form in parsed.forms:
        assert len(form["fields"]) == len(set(form["fields"]))
        assert not set(form["buttons"]) & set(form["fields"])


def test_base_permission_revoked_during_composition_withholds_owner_labels(http_world):
    http_world["denied"].add(VIEW_PLANNING)
    _request, response = request_page(http_world)
    assert response.status_code == 403
    assert set(response.context_data) == {"failure_message"}
    workspace.list_programme_timetable_items.assert_not_called()
    workspace.list_venue_timetable_spaces.assert_not_called()


def test_unknown_saved_finding_cannot_become_an_acknowledgement_form(http_world):
    _request, response = request_page(
        http_world,
        selected_post(http_world, mode=Op.WARNING_ACKNOWLEDGE, conflict_id=uuid4()),
    )
    assert response.status_code == 503
    assert set(response.context_data) == {"failure_message"}
    planning_record_actions._authorize.assert_not_called()
    assert "Opening workshop" not in rendered(response)


def test_placement_post_without_selected_context_never_reaches_command_adapter(
    http_world,
):
    _request, response = request_page(
        http_world,
        selected_post(
            http_world,
            mode="placement",
            action="preview_placement",
            candidate_id=None,
        ),
    )
    assert response.status_code == 400
    assert set(response.context_data) == {"failure_message"}
    planning_actions._authorize.assert_not_called()


def test_read_only_workspace_has_no_new_mutation_options(http_world):
    http_world["snapshot"] = replace(http_world["snapshot"], accepts_writes=False)
    _request, response = request_page(http_world)
    assert {mode for mode, _label in response.context_data["mode_choices"]} == {
        "overview",
        "history",
        "review",
        "reservation",
    }
    assert response.context_data["access_label"] == "Read-only edition"


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (VenueAuthorizationDeniedError, 403),
        (VenueSchedulingSourceDeniedError, 403),
        (VenueSchedulingSourceUnavailableError, 503),
        (VenueVersionConflictError, 409),
        (VenueRetryConflictError, 409),
        (VenueStateConflictError, 409),
        (VenueCapacityConflictError, 409),
        (VenueAvailabilityConflictError, 409),
        (VenueBookingOverlapError, 409),
    ],
)
def test_physical_command_errors_do_not_become_uncaught_or_private_denial_pages(
    http_world, monkeypatch, error, status
):
    data = command_post(http_world, mode=Op.RESERVATION_CANCEL, confirm="confirmed")
    writer = Mock(side_effect=error("Secret physical source details"))
    monkeypatch.setattr(
        planning_record_actions, "change_scheduling_reservation", writer
    )
    _request, response = request_page(http_world, data)
    assert response.status_code == status
    assert "Secret physical source" not in rendered(response)
    if status == 403:
        assert set(response.context_data) == {"failure_message"}
    else:
        assert (
            response.context_data["control"].form["retry_key"].value()
            == data["retry_key"]
        )
        assert "status_message" not in response.context_data
    writer.assert_called_once()


class NativeFormShape(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.forms = []
        self.current = None
        self.nested = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "form":
            self.nested |= self.current is not None
            self.current = {"fields": [], "buttons": []}
            self.forms.append(self.current)
        elif self.current is not None and "name" in attributes:
            if tag in {"input", "select", "textarea"}:
                self.current["fields"].append(attributes["name"])
            elif tag == "button":
                self.current["buttons"].append(attributes["name"])

    def handle_endtag(self, tag):
        if tag == "form":
            self.current = None


@pytest.mark.parametrize(
    "mode",
    [
        "overview",
        "placement",
        "history",
        "review",
        Op.WARNING_ACKNOWLEDGE,
        Op.RESERVATION_CANCEL,
    ],
)
def test_rendered_native_forms_have_no_nesting_or_duplicate_successful_fields(
    http_world, mode
):
    changes = {}
    if mode == Op.WARNING_ACKNOWLEDGE:
        changes["conflict_id"] = http_world["sources"]["review"].saved_findings[0].id
    _request, response = request_page(
        http_world, selected_post(http_world, mode=mode, **changes)
    )
    assert response.status_code == 200
    parsed = NativeFormShape(rendered(response))
    assert not parsed.nested
    assert len(parsed.forms) >= 3
    for form in parsed.forms:
        assert len(form["fields"]) == len(set(form["fields"]))
        for clicked in form["buttons"]:
            assert clicked not in form["fields"]


@pytest.mark.parametrize("code", list(SchedulingConflictCode))
def test_every_closed_conflict_has_a_cause_and_safe_next_action(code):
    finding = SchedulingFinding(
        "synthetic-source", code, SchedulingConflictSeverity.BLOCKER
    )
    (row,) = describe_planning_findings((finding,))
    assert row["finding"] is finding
    assert row["explanation"]
    assert row["next_action"]
    assert "_" not in row["explanation"]


def test_read_only_conflict_review_never_offers_acknowledgement(http_world):
    http_world["snapshot"] = replace(http_world["snapshot"], accepts_writes=False)
    _request, response = request_page(
        http_world, selected_post(http_world, mode="review")
    )
    assert response.status_code == 200
    assert not response.context_data["can_acknowledge"]
    assert "Review this warning acknowledgement" not in rendered(response)


def test_shared_availability_template_withholds_unshared_periods_and_contacts(
    http_world,
):
    period = SimpleNamespace(
        starts_at="UNSHARED-SECRET", ends_at="UNSHARED-SECRET", kind="UNSHARED-SECRET"
    )
    data = SimpleNamespace(
        hosts=(
            SimpleNamespace(
                host_id=uuid4(),
                status="not_shared",
                host_version=2,
                availability_version=1,
                periods=(period,),
                email="CONTACT-SECRET",
            ),
        ),
        private_review_text="REVIEW-SECRET",
    )
    workspace.load_scheduling_item_inspector.return_value = PlanningItemInspector(
        http_world["selection"].item_id, PlanningItemLayer.SHARED_AVAILABILITY, data
    )
    _request, response = request_page(
        http_world,
        selected_post(http_world, layer=PlanningItemLayer.SHARED_AVAILABILITY),
    )
    html = rendered(response)
    assert "No shared periods are disclosed" in html
    for value in ("UNSHARED-SECRET", "CONTACT-SECRET", "REVIEW-SECRET"):
        assert value not in html
    workspace.load_scheduling_host_requirements.assert_not_called()


@pytest.mark.parametrize(
    ("layer", "marker"),
    [
        (PlanningItemLayer.WORKING, "WORKING-MARKER"),
        (PlanningItemLayer.PUBLIC_COPY, "PUBLIC-MARKER"),
        (PlanningItemLayer.DELIVERY, "DELIVERY-MARKER"),
    ],
)
def test_rich_inspector_escapes_and_renders_only_its_selected_explicit_fields(
    http_world, layer, marker
):
    data = SimpleNamespace(
        working=SimpleNamespace(
            internal_title="WORKING-MARKER",
            working_summary="<script>WORKING-MARKER</script>",
            item_version=2,
        ),
        public_title="PUBLIC-MARKER",
        public_summary="<script>PUBLIC-MARKER</script>",
        public_content_note="PUBLIC-MARKER",
        rendition_number=1,
        technical_requirements="DELIVERY-MARKER",
        accessibility_delivery="<script>DELIVERY-MARKER</script>",
        media_consent_notes="DELIVERY-MARKER",
        item_version=3,
        email="CONTACT-SECRET",
        proposal_answers="PROPOSAL-SECRET",
        review_text="REVIEW-SECRET",
    )
    workspace.load_scheduling_item_inspector.return_value = PlanningItemInspector(
        http_world["selection"].item_id, layer, data
    )
    _request, response = request_page(
        http_world, selected_post(http_world, layer=layer)
    )
    html = rendered(response)
    assert marker in html
    assert "&lt;script&gt;" in html
    for value in {
        "WORKING-MARKER",
        "PUBLIC-MARKER",
        "DELIVERY-MARKER",
        "CONTACT-SECRET",
        "PROPOSAL-SECRET",
        "REVIEW-SECRET",
    } - {marker}:
        assert value not in html


def test_saved_review_shows_current_cause_sources_and_explicit_acknowledgement_entry(
    http_world,
):
    _request, response = request_page(
        http_world, selected_post(http_world, mode="review")
    )
    html = rendered(response)
    assert "Required presence is outside a stated preference" in html
    assert "Review this warning acknowledgement" in html
    assert "fingerprint" not in html
    assert "acknowledgement rationale" not in html
