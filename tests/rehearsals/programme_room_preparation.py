"""Real Venue owner composition, with configuration discovery through its own form."""

from __future__ import annotations

from dataclasses import asdict
from html.parser import HTMLParser
from uuid import UUID, uuid4

from tests.rehearsals.programme_setup_scenarios import approve_synthetic_role

REASON = "Synthetic room planning only; no real venue safety or release approval."


class ProgrammeRoomPreparationError(RuntimeError):
    """Retain a stable failure without disclosing an authenticated page."""


class _Configurations(HTMLParser):
    def __init__(self):
        super().__init__()
        self.selects = 0
        self.active = False
        self.value = None
        self.label = []
        self.options = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "select":
            self.active = attributes.get("name") == "selected_configuration_id"
            self.selects += int(self.active)
        elif tag == "option" and self.active:
            self.value = attributes.get("value")
            self.label = []

    def handle_data(self, data):
        if self.active and self.value is not None:
            self.label.append(data)

    def handle_endtag(self, tag):
        if tag == "option" and self.active:
            if self.value:
                self.options.append((self.value, "".join(self.label).strip()))
            self.value = None
        elif tag == "select":
            self.active = False


def configuration_from_html(content, *, room_name):
    """Require one exact visible choice; never infer a configuration identifier."""
    if not isinstance(content, bytes) or len(content) > 1_048_576:
        raise ProgrammeRoomPreparationError("room_configuration_unavailable")
    try:
        parser = _Configurations()
        parser.feed(content.decode("utf-8", errors="strict"))
        choices = [
            UUID(value)
            for value, label in parser.options
            if label == f"{room_name} / Seated v1"
        ]
    except (ValueError, TypeError, UnicodeError):
        raise ProgrammeRoomPreparationError("room_configuration_unavailable") from None
    if parser.selects != 1 or len(choices) != 1 or not choices[0].int:
        raise ProgrammeRoomPreparationError("room_configuration_unavailable")
    return choices[0]


def _configuration(setup, person, room_name):
    from django.test import Client  # noqa: PLC0415
    from django.urls import reverse  # noqa: PLC0415

    from maru.events.queries import resolve_edition_route_identity  # noqa: PLC0415
    from maru.venues.queries import list_venue_workspace  # noqa: PLC0415

    # Genuine backend login, not force_login/force_authenticate or a fabricated user.
    # This in-process HTTP adapter is not actual TLS/browser acceptance.
    client = Client(enforce_csrf_checks=True, HTTP_HOST="127.0.0.1")
    person.authenticate()
    if not client.login(username=person.email, password=person.password):
        raise ProgrammeRoomPreparationError("room_person_login_failed")
    try:
        scope = {
            "organization_id": setup.organization_id,
            "edition_id": setup.edition_id,
        }
        list_venue_workspace(actor=person.authenticate(), **scope)
        route = resolve_edition_route_identity(series_id=setup.series_id, **scope)
        if route is None:
            raise ProgrammeRoomPreparationError("room_route_unavailable")
        response = client.get(
            reverse("venue-workspace", kwargs=asdict(route)), secure=True
        )
        if (
            response.status_code != 200
            or "no-store" not in response.headers.get("Cache-Control", "")
            or "text/html" not in response.headers.get("Content-Type", "")
        ):
            raise ProgrammeRoomPreparationError("room_form_unavailable")
        result = configuration_from_html(response.content, room_name=room_name)
        list_venue_workspace(actor=person.authenticate(), **scope)
        if resolve_edition_route_identity(series_id=setup.series_id, **scope) != route:
            raise ProgrammeRoomPreparationError("room_route_changed")
        return result
    finally:
        client.logout()


def _venue_command(command, setup, person, **values):
    return command(
        actor=person.authenticate(),
        organization_id=setup.organization_id,
        reason=REASON,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="programme_rehearsal",
        **values,
    )


def prepare_rooms(setup, items, catalog_person, planner):
    """Create two real selected rooms and independently approve exact-room scopes."""
    from maru.authorization.catalog import ScopeLevel  # noqa: PLC0415
    from maru.authorization.programme_role_scope_choices import (  # noqa: PLC0415
        load_programme_role_scope_choices,
    )
    from maru.venues import services  # noqa: PLC0415
    from maru.venues.bindings import edition_space_binding_id  # noqa: PLC0415

    grants = []
    property_result = _venue_command(
        services.create_venue_property,
        setup,
        catalog_person,
        slug="synthetic-programme-venue",
        profile=services.VenuePropertyProfile(
            kind="venue",
            legal_name="Fictional rehearsal property",
            public_name="Fictional convention venue",
        ),
    )
    _venue_command(
        services.update_venue_property,
        setup,
        catalog_person,
        property_id=property_result.object_id,
        expected_version=property_result.resulting_version,
        changes={"lifecycle": "active"},
    )
    venue = _venue_command(
        services.select_venue_for_edition,
        setup,
        catalog_person,
        edition_id=setup.edition_id,
        property_id=property_result.object_id,
        responsible_department_id=setup.department_id,
        local_name="Fictional convention venue",
        public_description_override="Synthetic rehearsal, not a real venue.",
        public_contact_override="",
        opening_restrictions="Only the explicitly recorded fictional service window.",
    )
    rooms = []
    for code, name in (("main", "Main stage"), ("workshop", "Workshop room")):
        source = _venue_command(
            services.create_venue_space_catalog_path,
            setup,
            catalog_person,
            property_id=property_result.object_id,
            catalog=services.VenueSpaceCatalogInput(
                code,
                f"Fictional {code} site",
                code,
                f"Fictional {code} building",
                code,
                name,
                "function_room",
                "seated",
                "Seated",
                100,
                100,
                40,
                100,
                accessibility_features=(
                    "Fictional level entry and clear wheelchair aisle."
                ),
                equipment_facts="Fictional handheld microphone and projector.",
            ),
        )
        configuration = _configuration(setup, catalog_person, name)
        selected = _venue_command(
            services.select_space_for_edition,
            setup,
            catalog_person,
            edition_id=setup.edition_id,
            venue_selection_id=venue.object_id,
            source_space_id=source.object_id,
            source_combination_id=None,
            selected_configuration_id=configuration,
            local_name=name,
            capacity=None,
            public_access_info="Fictional level entry; keep the aisle clear.",
            opening_restrictions="Use only the recorded service window.",
        )
        scopes = load_programme_role_scope_choices(
            actor=setup.controllers[0].authenticate(),
            organization_id=setup.organization_id,
            edition_id=setup.edition_id,
            correlation_id=uuid4(),
            source_channel="programme_rehearsal",
        )
        matching = [
            choice.scope
            for choice in scopes.choices
            if choice.scope.level == ScopeLevel.RESOURCE
            and choice.scope.department_id == setup.department_id
            and choice.scope.resource_kind == "venue.edition_space"
            and choice.scope.resource_binding_id
            == edition_space_binding_id(selected.object_id)
        ]
        if len(matching) != 1:
            raise ProgrammeRoomPreparationError("room_scope_unavailable")
        scope = matching[0]
        grants.append(
            approve_synthetic_role(
                setup,
                people=setup.controllers,
                recipient=planner,
                code="room-planning",
                level=scope.level,
                department_id=scope.department_id,
                resource_binding_id=scope.resource_binding_id,
                resource_kind=scope.resource_kind,
            )
        )
        _venue_command(
            services.set_edition_space_availability,
            setup,
            planner,
            edition_id=setup.edition_id,
            space_selection_id=selected.object_id,
            expected_version=selected.resulting_version,
            intervals=(
                services.VenueAvailabilityInterval(
                    items.availability_starts_at, items.availability_ends_at
                ),
            ),
        )
        rooms.append(selected.object_id)
    return tuple(rooms), tuple(grants)
