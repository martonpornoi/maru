from __future__ import annotations

import pytest
from django.core.management import call_command

from maru.accounts.models import AccessGrant
from maru.project_import import parse_project_yaml
from maru.projects.importer import import_project_setup
from maru.projects.models import (
    EventGroup,
    FormField,
    Hotel,
    Project,
    Room,
    RoomCombination,
    Subproject,
)

PROJECT_YAML = """
project:
  name: Awoostria 2026
  slug: awoostria-2026
  timezone: Europe/Vienna
  opens_at: "2026-07-22T10:00:00+02:00"
  closes_at: "2026-07-25T23:00:00+02:00"
accounts:
  - email: marton.pornoi@gmail.com
    roles: [Admin, Board, Event Manager]
hotels:
  - name: Main Convention Hotel
    rooms:
      - name: Panel Room A
        capacity: 80
        properties: [projector, movable_wall]
      - name: Panel Room B
        capacity: 75
        properties: [projector, movable_wall]
    combinations:
      - name: Panel Room A+B
        rooms: [Panel Room A, Panel Room B]
        capacity: 160
event_groups:
  - name: Cooling Track
    slug: cooling-track
    description: Ordered cooling panels.
    requires_order: true
subprojects:
  - name: Event Submissions
    slug: events
    kind: event_submission
    form:
      sections:
        - title: Display
          fields:
            - label: Display - Title
              type: short_text
              required: true
            - label: Display - Abstract
              type: long_text
  - name: Dance Competition Volunteers
    slug: dance-volunteers
    kind: volunteer_registration
    form:
      sections:
        - title: Volunteer Details
          fields:
            - label: Preferred Role
              type: single_choice
              options: [Check-in, Backstage]
"""


@pytest.mark.django_db
def test_import_project_setup_creates_project_structure() -> None:
    result = import_project_setup(parse_project_yaml(PROJECT_YAML))

    assert result.project.slug == "awoostria-2026"
    assert result.accounts == 1
    assert result.hotels == 1
    assert result.rooms == 2
    assert result.room_combinations == 1
    assert result.event_groups == 1
    assert result.subprojects == 2
    assert result.form_fields == 3

    project = Project.objects.get(slug="awoostria-2026")
    assert project.subprojects.count() == 2
    assert AccessGrant.objects.filter(email="marton.pornoi@gmail.com").exists()

    hotel = Hotel.objects.get(projects=project, name="Main Convention Hotel")
    assert Room.objects.get(hotel=hotel, name="Panel Room A").properties == [
        "projector",
        "movable_wall",
    ]
    combination = RoomCombination.objects.get(hotel=hotel, name="Panel Room A+B")
    assert set(combination.rooms.values_list("name", flat=True)) == {
        "Panel Room A",
        "Panel Room B",
    }
    group = EventGroup.objects.get(project=project, slug="cooling-track")
    assert group.name == "Cooling Track"
    assert group.requires_order

    subproject = Subproject.objects.get(project=project, slug="events")
    assert FormField.objects.get(
        subproject=subproject, label="Display - Title"
    ).required


@pytest.mark.django_db
def test_import_project_setup_is_repeatable_and_updates_existing_records() -> None:
    import_project_setup(parse_project_yaml(PROJECT_YAML))
    updated_yaml = PROJECT_YAML.replace("capacity: 80", "capacity: 90", 1)

    import_project_setup(parse_project_yaml(updated_yaml))

    assert Project.objects.count() == 1
    assert Hotel.objects.count() == 1
    assert Room.objects.count() == 2
    assert EventGroup.objects.count() == 1
    assert Subproject.objects.count() == 2
    assert FormField.objects.count() == 3
    assert Room.objects.get(name="Panel Room A").capacity == 90


@pytest.mark.django_db
def test_import_project_management_command(tmp_path) -> None:
    path = tmp_path / "project.yml"
    path.write_text(PROJECT_YAML, encoding="utf-8")

    call_command("import_project", str(path))

    assert Project.objects.filter(slug="awoostria-2026").exists()
