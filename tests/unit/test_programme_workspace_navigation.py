"""Exact-scope navigation admission without protected inventories or runtime grants."""

from types import ModuleType, SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from django.db import DatabaseError
from django.http import HttpResponse
from django.urls import path, resolve

from maru.authorization.policy import PolicyDecision
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.scheduling import workspace_navigation as navigation
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.planning_queries import PLANNING_FIELDS, SchedulingReadRequest
from maru.venues.timetable_queries import TIMETABLE_SPACE_FIELDS


def destination(request, **kwargs):
    return HttpResponse("Synthetic destination, not an owner read")


@pytest.mark.parametrize("admitted", [True, False, None, 1])
def test_operator_entry_link_requires_exact_true_metadata(
    links_world, monkeypatch, admitted
):
    world = links_world
    world.urlconf.urlpatterns.append(
        path(
            "admin/programme/run-sheets/<uuid:organization_id>/<uuid:edition_id>/",
            destination,
            name="programme-operator-entry",
        )
    )
    check = Mock(return_value=admitted)
    monkeypatch.setattr(navigation, "can_enter_operator_tasks", check)
    offered = links(world)
    assert any(row.code == "operators" for row in offered) is (admitted is True)
    check.assert_called_once_with(world.scope)
    for row in offered:
        if row.code == "operators":
            assert resolve(row.url, urlconf=world.urlconf).kwargs == {
                "organization_id": world.scope.organization_id,
                "edition_id": world.scope.edition_id,
            }


def test_unmounted_operator_entry_does_no_optional_metadata_read(
    links_world, monkeypatch
):
    check = Mock(side_effect=AssertionError("unmounted entry must not query"))
    monkeypatch.setattr(navigation, "can_enter_operator_tasks", check)
    assert all(row.code != "operators" for row in links(links_world))
    check.assert_not_called()


def routes(*, shadow=False):
    config = ModuleType(f"synthetic_programme_links_{uuid4().hex}")
    base = (
        "admin/platform/organizations/<uuid:organization_id>/series/"
        "<uuid:series_id>/editions/<uuid:edition_id>/programme/"
    )
    config.urlpatterns = [
        path(
            "admin/programme/items/<uuid:organization_id>/<uuid:edition_id>/",
            destination,
            name="programme-items",
        ),
        path(base + "timetable/", destination, name="programme-timetable-workspace"),
        path(base + "release/", destination, name="programme-release-workspace"),
    ]
    if shadow:
        config.urlpatterns.insert(0, path("<path:rest>", destination, name="shadow"))
    return config


@pytest.fixture
def links_world(monkeypatch):
    scope = SchedulingReadRequest(*(uuid4() for _ in range(4)))
    series = uuid4()
    programme = Mock()
    scheduling = Mock()
    release = Mock()
    venue = Mock(
        return_value=PolicyDecision(
            allowed=True,
            fields=TIMETABLE_SPACE_FIELDS,
            obligations=frozenset(),
            reason_code="synthetic_exact_fields",
        )
    )
    parent = Mock(return_value=series)
    monkeypatch.setattr(navigation, "authorize_programme_scope", programme)
    monkeypatch.setattr(navigation, "authorize_scheduling_scope", scheduling)
    monkeypatch.setattr(navigation, "authorize_release_task", release)
    monkeypatch.setattr(navigation, "decide_verified_principal_exact_edition", venue)
    monkeypatch.setattr(navigation, "resolve_edition_series_identity", parent)
    return SimpleNamespace(
        scope=scope,
        series=series,
        programme=programme,
        scheduling=scheduling,
        release=release,
        venue=venue,
        parent=parent,
        urlconf=routes(),
    )


def links(world, current="items", **kwargs):
    return navigation.programme_workspace_links(
        world.scope, current=current, urlconf=world.urlconf, **kwargs
    )


def test_three_tasks_have_exact_resolvable_links_and_independent_fields(links_world):
    world = links_world
    offered = links(world)
    assert [row.code for row in offered] == ["timetable", "release"]
    for row in offered:
        target = resolve(row.url, urlconf=world.urlconf)
        assert target.kwargs == {
            "organization_id": world.scope.organization_id,
            "series_id": world.series,
            "edition_id": world.scope.edition_id,
        }
        assert "?" not in row.url
    assert world.scheduling.call_args.kwargs["requested_fields"] == PLANNING_FIELDS
    assert world.programme.call_args.kwargs["requested_fields"] == frozenset(
        {"item_summaries", "working_information"}
    )
    assert world.venue.call_args.kwargs == {
        "principal_id": world.scope.actor_id,
        "organization_id": world.scope.organization_id,
        "edition_id": world.scope.edition_id,
        "capability_code": "venues.view_workspace",
        "requested_fields": TIMETABLE_SPACE_FIELDS,
    }
    assert [row.code for row in links(world, "timetable")] == ["items", "release"]
    assert [row.code for row in links(world, "release")] == ["items", "timetable"]
    assert [row.code for row in links(world, "shifts")] == [
        "items",
        "timetable",
        "release",
    ]


@pytest.mark.parametrize("owner", ["programme", "scheduling", "venue"])
def test_planning_link_cannot_borrow_another_owners_authority(links_world, owner):
    world = links_world
    if owner == "venue":
        world.venue.return_value = PolicyDecision(
            allowed=True,
            fields=frozenset(),
            obligations=frozenset(),
            reason_code="missing_fields",
        )
    else:
        getattr(world, owner).side_effect = (
            ProgrammeAuthorizationDeniedError
            if owner == "programme"
            else SchedulingAuthorizationDeniedError
        )
    assert [row.code for row in links(world)] == ["release"]


def test_release_link_needs_one_real_task_not_every_release_role(links_world):
    world = links_world

    def release_task(scope, task):
        if task != "withdraw":
            raise SchedulingAuthorizationDeniedError

    world.release.side_effect = release_task
    assert [row.code for row in links(world)] == ["timetable", "release"]
    world.release.side_effect = SchedulingAuthorizationDeniedError
    assert [row.code for row in links(world)] == ["timetable"]


@pytest.mark.parametrize(
    "cause",
    [
        "unmounted",
        "shadowed",
        "foreign_parent",
        "absent_parent",
        "database",
        "unavailable",
    ],
)
def test_unavailable_destinations_never_appear_as_executable_links(links_world, cause):
    world = links_world
    options = {}
    if cause == "unmounted":
        world.urlconf = ModuleType("empty_programme_destinations")
        world.urlconf.urlpatterns = []
    elif cause == "shadowed":
        world.urlconf = routes(shadow=True)
    elif cause == "foreign_parent":
        options["series_id"] = uuid4()
    elif cause == "absent_parent":
        world.parent.return_value = None
    else:
        world.parent.side_effect = (
            DatabaseError if cause == "database" else RuntimeError
        )
    assert links(world, **options) == ()
    if cause == "unmounted":
        for checker in (
            world.scheduling,
            world.programme,
            world.venue,
            world.release,
            world.parent,
        ):
            checker.assert_not_called()


def test_production_root_has_no_programme_connection_or_optional_reads(links_world):
    world = links_world
    assert (
        navigation.programme_workspace_links(
            world.scope, current="items", urlconf="maru.urls"
        )
        == ()
    )
    world.parent.assert_not_called()
    world.scheduling.assert_not_called()
    world.release.assert_not_called()
    assert links(world, "unknown") == ()


def test_read_only_scope_still_has_read_task_links(links_world):
    world = links_world
    world.scheduling.return_value = SimpleNamespace(accepts_writes=False)
    assert len(links(world)) == 2
    assert all(
        "write" not in call.kwargs["capability_code"]
        for call in world.scheduling.call_args_list
    )


def test_notice_connection_needs_its_own_field_without_a_parent_lookup(links_world):
    world = links_world
    world.urlconf.urlpatterns.append(
        path(
            "admin/programme/changes/<uuid:organization_id>/<uuid:edition_id>/",
            destination,
            name="programme-change-notices",
        )
    )
    offered = links(world, "release")
    assert [row.code for row in offered] == ["items", "timetable", "notices"]
    target = resolve(offered[-1].url, urlconf=world.urlconf)
    assert target.kwargs == {
        "organization_id": world.scope.organization_id,
        "edition_id": world.scope.edition_id,
    }
    assert (
        world.scheduling.call_args.kwargs["capability_code"]
        == "scheduling.view_change_notices"
    )
    assert world.scheduling.call_args.kwargs["requested_fields"] == frozenset(
        {"change_notices"}
    )
    assert [row.code for row in links(world, "notices")] == [
        "items",
        "timetable",
        "release",
    ]


def test_notice_denial_does_not_hide_other_admitted_tasks(links_world):
    world = links_world
    world.urlconf.urlpatterns.append(
        path(
            "admin/programme/changes/<uuid:organization_id>/<uuid:edition_id>/",
            destination,
            name="programme-change-notices",
        )
    )

    def authorize(**kwargs):
        if kwargs["capability_code"] == "scheduling.view_change_notices":
            raise SchedulingAuthorizationDeniedError

    world.scheduling.side_effect = authorize
    assert [row.code for row in links(world)] == ["timetable", "release"]


def _application_route(world):
    world.urlconf.urlpatterns.append(
        path(
            "admin/applications/programme-calls/<uuid:organization_id>/<uuid:edition_id>/",
            destination,
            name="programme-department-tasks",
        )
    )


@pytest.mark.parametrize(
    "current", ["items", "timetable", "release", "notices", "shifts"]
)
def test_applications_return_link_requires_its_own_metadata_admission(
    links_world, monkeypatch, current
):
    world = links_world
    _application_route(world)
    admission = Mock(return_value=True)
    monkeypatch.setattr(navigation, "can_enter_programme_tasks", admission)
    offered = links(world, current)
    link = next(item for item in offered if item.code == "applications")
    assert link.label == "Programme calls, review and conversion"
    assert resolve(link.url, urlconf=world.urlconf).kwargs == {
        "organization_id": world.scope.organization_id,
        "edition_id": world.scope.edition_id,
    }
    admission.assert_called_once_with(
        actor_id=world.scope.actor_id,
        organization_id=world.scope.organization_id,
        edition_id=world.scope.edition_id,
    )


@pytest.mark.parametrize("admission", [False, None, 1])
def test_other_owner_grants_cannot_admit_applications(
    links_world, monkeypatch, admission
):
    world = links_world
    _application_route(world)
    monkeypatch.setattr(
        navigation, "can_enter_programme_tasks", Mock(return_value=admission)
    )
    assert [item.code for item in links(world)] == ["timetable", "release"]


@pytest.mark.parametrize("cause", ["unmounted", "shadowed", "database"])
def test_unavailable_applications_entry_never_becomes_a_link(
    links_world, monkeypatch, cause
):
    world = links_world
    admission = Mock(return_value=True)
    monkeypatch.setattr(navigation, "can_enter_programme_tasks", admission)
    if cause != "unmounted":
        _application_route(world)
    if cause == "shadowed":
        world.urlconf.urlpatterns.insert(
            0, path("<path:rest>", destination, name="shadow")
        )
    elif cause == "database":
        admission.side_effect = DatabaseError
    assert not any(item.code == "applications" for item in links(world))
    if cause == "unmounted":
        admission.assert_not_called()


def test_applications_source_uses_existing_independent_destination_proofs(links_world):
    world = links_world
    offered = links(world, "applications")
    assert [item.code for item in offered] == ["items", "timetable", "release"]
    assert all("applications" not in item.url for item in offered)
    world.programme.assert_called()
    world.scheduling.assert_called()
    world.release.assert_called()
