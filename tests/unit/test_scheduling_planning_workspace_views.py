"""Canonical planner rendering and late-disclosure tests, never native SQL proof."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from bs4 import BeautifulSoup
from django.db import DatabaseError
from django.test import RequestFactory
from django.urls import resolve, reverse

from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.scheduling import planning_disclosure as disclosure
from maru.scheduling import planning_workspace_views as views
from maru.scheduling.command_support import (
    SchedulingCommandResult,
    SchedulingVersionConflictError,
)
from maru.scheduling.planning_queries import SchedulingReadRequest
from maru.scheduling.workspace_navigation import ProgrammeWorkspaceLink
from tests.unit import test_programme_workbench as workbench_helpers
from tests.unit import test_scheduling_planning_views as planning_helpers

board_inputs = planning_helpers.board_inputs
controls = planning_helpers.controls
http_world = planning_helpers.http_world
shell = workbench_helpers.shell


@pytest.fixture
def canonical_world(http_world, monkeypatch):
    world = http_world
    world["series_id"] = uuid4()
    world["admission"] = Mock()
    world["parent"] = Mock(return_value=world["series_id"])
    world["links"] = Mock(
        return_value=(
            ProgrammeWorkspaceLink("items", "Programme items", "/synthetic-items/"),
        )
    )
    monkeypatch.setattr(views, "authorize_timetable_workspace", world["admission"])
    monkeypatch.setattr(views, "resolve_edition_series_identity", world["parent"])
    monkeypatch.setattr(views, "programme_workspace_links", world["links"])
    monkeypatch.setattr(
        disclosure,
        "load_scheduling_planning",
        planning_helpers.views.load_scheduling_planning,
    )
    return world


def request_workspace(
    world,
    data=None,
    *,
    method=None,
    csrf=False,
    anonymous=False,
    series=None,
    suffix="",
):
    route = reverse(
        "programme-timetable-workspace",
        kwargs={
            "organization_id": world["organization_id"],
            "series_id": world["series_id"],
            "edition_id": world["edition_id"],
        },
        urlconf="maru.scheduling.planning_urls",
    )
    request = RequestFactory().generic(
        method or ("POST" if data is not None else "GET"),
        route + suffix,
        data=data.urlencode() if data is not None else "",
        content_type="application/x-www-form-urlencoded",
    )
    request.user = SimpleNamespace(
        pk=world["actor_id"],
        is_authenticated=not anonymous,
        is_active=True,
        is_staff=False,
        is_superuser=False,
    )
    request._dont_enforce_csrf_checks = not csrf
    return views.programme_timetable_workspace(
        request,
        organization_id=world["organization_id"],
        series_id=series or world["series_id"],
        edition_id=world["edition_id"],
    )


def test_canonical_route_renders_one_real_shell_with_native_selection(canonical_world):
    world = canonical_world
    response = request_workspace(world)
    assert response.status_code == 200
    assert response.is_rendered
    soup = BeautifulSoup(response.content, "html.parser")
    assert len(soup.select("main")) == len(soup.select("h1")) == 1
    assert soup.find("h1").get_text() == "Timetable planning"
    assert (
        soup.find("nav", attrs={"aria-label": "Programme workflow"}).find("a")["href"]
        == "/synthetic-items/"
    )
    assert str(world["edition_id"]) in soup.get_text()
    assert "Opening workshop" in soup.get_text()
    assert (
        response.context_data["baseline_admin_parent_template"]
        == "admin/base_site.html"
    )
    assert "no-store" in response["Cache-Control"]
    assert "frame-ancestors 'none'" in response["Content-Security-Policy"]
    assert world["admission"].call_count == 2
    assert world["parent"].call_count == 2
    assert len(world["reads"]) == 2


@pytest.mark.parametrize(
    ("kind", "status"),
    [
        ("anonymous", 403),
        ("csrf", 403),
        ("method", 405),
        ("foreign_series", 403),
        ("denied", 403),
    ],
)
def test_route_security_fails_before_native_source_or_command(
    canonical_world, kind, status
):
    world = canonical_world
    options = {}
    data = None
    if kind == "anonymous":
        options["anonymous"] = True
    elif kind == "csrf":
        data = planning_helpers.selected_post(world)
        options["csrf"] = True
    elif kind == "method":
        options["method"] = "DELETE"
    elif kind == "foreign_series":
        options["series"] = uuid4()
    else:
        world["admission"].side_effect = ProgrammeAuthorizationDeniedError
    response = request_workspace(world, data, **options)
    assert response.status_code == status
    assert "Opening workshop" not in response.content.decode()
    assert world["reads"] == []


@pytest.mark.parametrize(
    "failure", ["permission", "source", "scope", "dependency", "output"]
)
def test_post_render_change_discards_all_private_content(
    canonical_world, monkeypatch, failure
):
    world = canonical_world

    def after_render(*args, **kwargs):
        if world["links"].call_count == 2:
            if failure == "permission":
                world["denied"].add("scheduling.view_planning")
            elif failure == "source":
                world["snapshot"] = replace(
                    world["snapshot"],
                    control_version=world["snapshot"].control_version + 1,
                )
            elif failure == "scope":
                world["parent"].return_value = uuid4()
            elif failure == "dependency":
                monkeypatch.setattr(
                    disclosure,
                    "load_scheduling_planning",
                    Mock(side_effect=DatabaseError("private failure")),
                )
            else:
                monkeypatch.setattr(views, "_MAX_OUTPUT_BYTES", 1)
        return ()

    world["links"].side_effect = after_render
    response = request_workspace(world)
    assert response.status_code == (403 if failure in {"permission", "scope"} else 503)
    assert "Opening workshop" not in response.content.decode()
    assert "private failure" not in response.content.decode()


def test_moving_optional_navigation_is_omitted_without_losing_workspace(
    canonical_world,
):
    world = canonical_world
    world["links"].side_effect = [world["links"].return_value, ()]
    response = request_workspace(world)
    assert response.status_code == 200
    assert "Opening workshop" in response.content.decode()
    assert "/synthetic-items/" not in response.content.decode()


@pytest.mark.parametrize("navigation", ["available", "denied", "moved"])
def test_current_binding_link_is_optional_and_does_not_mutate_source_rows(
    canonical_world, monkeypatch, navigation
):
    world = canonical_world
    demand_id = uuid4()
    requirement = SimpleNamespace(
        requirement_id=uuid4(),
        occurrence_id=uuid4(),
        version=2,
        lifecycle="active",
        expectation=SimpleNamespace(
            title="Synthetic staffing need", required_headcount=2
        ),
    )
    row = {
        "requirement": requirement,
        "binding": SimpleNamespace(
            demand_id=demand_id,
            version=3,
            demand_version=1,
            source=SimpleNamespace(requirement_version=2),
        ),
        "actions": (),
        "state": {},
    }
    original = views.scheduling_planning_view

    def native(*args, **kwargs):
        result = original(*args, **kwargs)
        result.context_data.update(staffing_active=True, staffing_rows=(row,))
        return result

    dispatcher = Mock(side_effect=native)
    monkeypatch.setattr(views, "scheduling_planning_view", dispatcher)
    # This test isolates the optional renderer. Real source movement has separate
    # verify_planning_workspace tests and remains mandatory in native #102 proof.
    verify = Mock()
    monkeypatch.setattr(views, "verify_planning_workspace", verify)
    links = {demand_id: f"/synthetic-shift/{demand_id}/"}
    admitted = Mock(
        side_effect=[links, {}] if navigation == "moved" else None,
        return_value=links if navigation == "available" else {},
    )
    monkeypatch.setattr(views, "programme_shift_links", admitted)
    response = request_workspace(world)
    assert response.status_code == 200
    html = response.content.decode()
    assert "Synthetic staffing need" in html
    assert str(demand_id) in html
    assert ("Open this bound Shift" in html) is (navigation == "available")
    assert response.context_data["staffing_rows"] == (row,)
    assert "shift_url" not in row
    assert admitted.call_count == 2
    assert admitted.call_args.kwargs["demand_ids"] == (demand_id,)
    assert admitted.call_args.kwargs["series_id"] == world["series_id"]
    dispatcher.assert_called_once()
    verify.assert_called_once()


def test_stale_native_command_keeps_original_input_and_runs_only_once(
    canonical_world, monkeypatch
):
    world = canonical_world
    data = planning_helpers.command_post(world, confirm="confirmed")
    writer = Mock(side_effect=SchedulingVersionConflictError("Private exception"))
    monkeypatch.setattr(
        planning_helpers.planning_record_actions, "archive_scheduling_candidate", writer
    )
    response = request_workspace(world, data)
    assert response.status_code == 409
    form = response.context_data["control"].form
    assert form.data["retry_key"] == data["retry_key"]
    assert form.data["expected_version"] == data["expected_version"]
    assert form.data["reason"] == data["reason"]
    assert "Private exception" not in response.content.decode()
    writer.assert_called_once()


def test_successful_native_command_is_not_repeated_by_final_read_checks(
    canonical_world, monkeypatch
):
    world = canonical_world
    data = planning_helpers.command_post(world, confirm="confirmed")
    result = SchedulingCommandResult(uuid4(), world["selection"].candidate_id, 2, 20)
    writer = Mock(return_value=result)
    monkeypatch.setattr(
        planning_helpers.planning_record_actions, "archive_scheduling_candidate", writer
    )
    response = request_workspace(world, data)
    assert response.status_code == 200
    writer.assert_called_once()
    assert "Command completed" in response.content.decode()


def test_unmounted_production_route_remains_closed(canonical_world):
    world = canonical_world
    url = reverse(
        "programme-timetable-workspace",
        kwargs={
            "organization_id": world["organization_id"],
            "series_id": world["series_id"],
            "edition_id": world["edition_id"],
        },
        urlconf="maru.scheduling.planning_urls",
    )
    assert (
        resolve(url, urlconf="maru.urls").func
        is not views.programme_timetable_workspace
    )


def test_final_source_check_rejects_changed_owner_label(canonical_world, monkeypatch):
    world = canonical_world
    _, response = planning_helpers.request_page(world)
    original = planning_helpers.workspace.list_programme_timetable_items.return_value
    monkeypatch.setattr(
        planning_helpers.workspace,
        "list_programme_timetable_items",
        Mock(
            return_value=(
                replace(original[0], internal_title="Changed title"),
                *original[1:],
            )
        ),
    )
    scope = SchedulingReadRequest(
        world["actor_id"], world["organization_id"], world["edition_id"], uuid4()
    )
    with pytest.raises(RuntimeError):
        disclosure.verify_planning_workspace(scope, response.context_data)


@pytest.mark.parametrize(
    "mode",
    [
        "overview",
        "history",
        "review",
        "reservation",
        "placement",
        "create_day",
        "candidate_create",
        "staffing",
    ],
)
def test_canonical_selected_modes_survive_read_only_recomposition(
    canonical_world, mode
):
    data = planning_helpers.selected_post(
        canonical_world,
        mode=mode,
        **({"item_id": None, "occurrence_id": None} if mode == "staffing" else {}),
    )
    response = request_workspace(canonical_world, data)
    assert response.status_code == 200, response.content.decode()
    assert response.context_data["selection"].mode == mode


def test_native_placement_preview_preserves_original_bound_input(
    canonical_world, monkeypatch
):
    world = canonical_world
    data = planning_helpers.command_post(world, mode="placement")
    preview = world["sources"]["review"].current
    monkeypatch.setattr(
        planning_helpers.planning_actions,
        "preview_scheduling_candidate",
        Mock(return_value=preview),
    )
    writer = Mock()
    monkeypatch.setattr(
        planning_helpers.planning_actions, "set_scheduling_placement", writer
    )
    response = request_workspace(world, data)
    assert response.status_code == 200
    assert response.context_data["preview"] is preview
    bound = response.context_data["control"].form.data
    assert dict(bound) == {
        key: data.getlist(key) for key in data if not key.startswith("ui_")
    }
    writer.assert_not_called()


@pytest.mark.parametrize(
    "changed",
    [
        "inspector",
        "review",
        "hosts",
        "reservation",
        "history",
        "staffing_rows",
        "choices",
    ],
)
def test_final_disclosure_compares_rich_sources_and_owner_form_choices(
    canonical_world, monkeypatch, changed
):
    world = canonical_world
    _, response = planning_helpers.request_page(
        world, planning_helpers.selected_post(world, mode="placement")
    )
    original = disclosure.compose_planning_workspace

    def moved(*args, **kwargs):
        context = original(*args, **kwargs)
        if changed == "choices":
            form = context["control"].form
            field = next(
                field
                for field in form.fields.values()
                if hasattr(field.widget, "choices")
            )
            field.widget.choices = [("new", "Changed protected choice")]
        else:
            context[changed] = ("Changed protected source",)
        return context

    monkeypatch.setattr(disclosure, "compose_planning_workspace", moved)
    scope = SchedulingReadRequest(
        world["actor_id"], world["organization_id"], world["edition_id"], uuid4()
    )
    with pytest.raises(RuntimeError):
        disclosure.verify_planning_workspace(scope, response.context_data)
