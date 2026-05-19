import pytest

from maru.domain import Role, SubprojectKind
from maru.project_import import ProjectImportError, parse_project_yaml


def test_parse_project_yaml_preserves_google_form_labels() -> None:
    config = parse_project_yaml(
        """
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
  - name: Main Hotel
    rooms:
      - name: Panel Room A
        capacity: 80
        properties: [projector, movable_wall]
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
"""
    )

    assert config.project.slug == "awoostria-2026"
    assert config.accounts[0].roles == frozenset(
        {Role.ADMIN, Role.BOARD, Role.EVENT_MANAGER}
    )
    assert config.hotels[0].rooms[0].properties == ("projector", "movable_wall")
    assert config.hotels[0].combinations == ()
    assert config.event_groups[0].name == "Cooling Track"
    assert config.event_groups[0].requires_order
    assert config.subprojects[0].subproject.kind == SubprojectKind.EVENT_SUBMISSION
    assert config.subprojects[0].fields[0].google_forms_key == "Display - Title"


def test_parse_project_yaml_rejects_missing_project() -> None:
    with pytest.raises(ProjectImportError, match="project"):
        parse_project_yaml("accounts: []")
