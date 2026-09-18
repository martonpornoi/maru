"""Pure owner-form/room composition checks, not actual room safety or HTTP proof."""

from types import SimpleNamespace
from unittest.mock import Mock, create_autospec
from uuid import uuid4

import pytest
from django import test as django_test

from maru.authorization import programme_role_commands, programme_role_scope_choices
from maru.authorization.catalog import ScopeLevel
from maru.authorization.programme_role_inputs import ProgrammeRoleScope
from maru.events import queries as event_queries
from maru.venues import queries, services
from maru.venues.bindings import edition_space_binding_id
from maru.venues.models import VenueSpace
from tests.rehearsals import programme_room_preparation as rooms
from tests.rehearsals import programme_setup_scenarios as setup_scenarios
from tests.unit.test_programme_planning_scenario import _sources
from tests.unit.test_programme_review_scenario import _authentication
from tests.unit.test_programme_setup_scenarios import _person


def test_shared_role_helper_preserves_exact_binding_for_both_controllers(monkeypatch):
    _authentication(monkeypatch)
    setup, _, _, _ = _sources()
    recipient, binding, assignment = _person("planner"), uuid4(), uuid4()
    request = create_autospec(
        programme_role_commands.request_programme_role,
        return_value=SimpleNamespace(request_id=uuid4()),
    )
    decision = create_autospec(
        programme_role_commands.decide_programme_role,
        return_value=SimpleNamespace(role_assignment_id=assignment),
    )
    monkeypatch.setattr(programme_role_commands, "request_programme_role", request)
    monkeypatch.setattr(programme_role_commands, "decide_programme_role", decision)
    assert (
        setup_scenarios.approve_synthetic_role(
            setup,
            people=setup.controllers,
            recipient=recipient,
            code="room-planning",
            level=ScopeLevel.RESOURCE,
            department_id=setup.department_id,
            resource_binding_id=binding,
            resource_kind="venue.edition_space",
        )
        == assignment
    )
    scope = request.call_args.kwargs["scope"]
    assert scope.resource_binding_id == binding
    assert scope.resource_kind == "venue.edition_space"
    assert decision.call_args.kwargs["scope"] == scope
    assert request.call_args.kwargs["actor"].id == setup.controllers[0].account_id
    assert decision.call_args.kwargs["actor"].id == setup.controllers[1].account_id


def _html(identifier):
    return (
        f'<select name="selected_configuration_id"><option value="">None</option>'
        f'<option value="{identifier}">Main stage / Seated v1</option></select>'
    ).encode()


def test_exact_visible_configuration_selected_without_private_model_read():
    identifier = uuid4()
    assert (
        rooms.configuration_from_html(_html(identifier), room_name="Main stage")
        == identifier
    )


@pytest.mark.parametrize(
    "content",
    [b"", b"x" * 1_048_577, b"\xff", _html(uuid4()) * 2, _html("not-a-uuid")],
    ids=["absent", "oversized", "encoding", "duplicate-select", "invalid-id"],
)
def test_invalid_form_choices_fail_without_echoing_html(content):
    with pytest.raises(
        rooms.ProgrammeRoomPreparationError, match="configuration_unavailable"
    ):
        rooms.configuration_from_html(content, room_name="Main stage")


@pytest.mark.parametrize("failure", [None, "login", "redirect", "cache", "route"])
def test_form_discovery_uses_real_login_and_closes_session(monkeypatch, failure):
    _authentication(monkeypatch)
    setup, _, _, _ = _sources()
    person = _person("venue")
    identifier = uuid4()
    client = Mock()
    client.login.return_value = failure != "login"
    client.get.return_value = SimpleNamespace(
        status_code=302 if failure == "redirect" else 200,
        headers={
            "Cache-Control": "public" if failure == "cache" else "private, no-store",
            "Content-Type": "text/html",
        },
        content=_html(identifier),
    )
    factory = Mock(return_value=client)
    monkeypatch.setattr(django_test, "Client", factory)
    route = event_queries.EditionRouteIdentity("organizer", "series", "edition")
    lookup = create_autospec(
        event_queries.resolve_edition_route_identity,
        side_effect=(route, None if failure == "route" else route),
    )
    monkeypatch.setattr(event_queries, "resolve_edition_route_identity", lookup)
    workspace = create_autospec(queries.list_venue_workspace, return_value=())
    monkeypatch.setattr(queries, "list_venue_workspace", workspace)
    if failure is None:
        assert rooms._configuration(setup, person, "Main stage") == identifier
        assert workspace.call_count == 2
    else:
        with pytest.raises(rooms.ProgrammeRoomPreparationError):
            rooms._configuration(setup, person, "Main stage")
    factory.assert_called_once_with(enforce_csrf_checks=True, HTTP_HOST="127.0.0.1")
    client.login.assert_called_once_with(
        username=person.email, password=person.password
    )
    if failure != "login":
        client.logout.assert_called_once()
        assert client.get.call_args.kwargs == {"secure": True}
        assert workspace.call_args.kwargs["actor"].id == person.account_id
    else:
        client.get.assert_not_called()


def test_rooms_use_owned_configuration_active_property_and_exact_room_roles(
    monkeypatch,
):
    _authentication(monkeypatch)
    setup, _, _, items = _sources()
    catalog_person, planner = _person("catalog"), _person("planner")
    property_id, venue_id = uuid4(), uuid4()
    selected_ids = (uuid4(), uuid4())
    source_ids = (uuid4(), uuid4())
    configurations = (uuid4(), uuid4())
    events = []
    results = {
        "create_venue_property": iter((property_id,)),
        "update_venue_property": iter((property_id,)),
        "select_venue_for_edition": iter((venue_id,)),
        "create_venue_space_catalog_path": iter(source_ids),
        "select_space_for_edition": iter(selected_ids),
        "set_edition_space_availability": iter(selected_ids),
    }

    def invoke(name, **values):
        events.append((name, values))
        return services.VenueCommandResult(
            next(results[name]), uuid4(), 1, replayed=False
        )

    for name in results:
        monkeypatch.setattr(
            services,
            name,
            create_autospec(
                getattr(services, name),
                side_effect=lambda _name=name, **kw: invoke(_name, **kw),
            ),
        )
    monkeypatch.setattr(rooms, "_configuration", Mock(side_effect=configurations))
    choices = SimpleNamespace(
        choices=tuple(
            SimpleNamespace(
                scope=ProgrammeRoleScope(
                    setup.organization_id,
                    setup.edition_id,
                    ScopeLevel.RESOURCE,
                    setup.department_id,
                    edition_space_binding_id(identifier),
                    "venue.edition_space",
                )
            )
            for identifier in selected_ids
        )
    )
    query = create_autospec(
        programme_role_scope_choices.load_programme_role_scope_choices,
        return_value=choices,
    )
    monkeypatch.setattr(
        programme_role_scope_choices, "load_programme_role_scope_choices", query
    )
    grants = Mock(side_effect=(uuid4(), uuid4()))
    monkeypatch.setattr(rooms, "approve_synthetic_role", grants)
    selected, assignments = rooms.prepare_rooms(setup, items, catalog_person, planner)
    assert selected == selected_ids
    assert len(assignments) == 2
    assert events[1][0] == "update_venue_property"
    assert events[1][1]["changes"] == {"lifecycle": "active"}
    for index, call in enumerate(grants.call_args_list):
        assert call.kwargs["resource_binding_id"] == edition_space_binding_id(
            selected_ids[index]
        )
        assert call.kwargs["resource_kind"] == "venue.edition_space"
        assert call.kwargs["department_id"] == setup.department_id
        assert call.kwargs["level"] == ScopeLevel.RESOURCE
        assert call.kwargs["recipient"] == planner
    selection_calls = [kw for name, kw in events if name == "select_space_for_edition"]
    assert (
        tuple(kw["selected_configuration_id"] for kw in selection_calls)
        == configurations
    )
    for name, values in events:
        assert values["organization_id"] == setup.organization_id
        assert (
            values["actor"].id
            == (
                planner if name == "set_edition_space_availability" else catalog_person
            ).account_id
        )
        if name == "create_venue_space_catalog_path":
            assert values["catalog"].space_kind in VenueSpace.Kind.values
        if name == "set_edition_space_availability":
            assert values["intervals"][0].starts_at == items.availability_starts_at
            assert values["intervals"][0].ends_at == items.availability_ends_at
