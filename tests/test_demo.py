from __future__ import annotations

import pytest
from django.core.management import call_command
from django.urls import reverse

from maru.accounts.models import ArchivedParticipation
from maru.domain import SEED_ACCESS_EMAIL
from maru.projects.models import (
    Project,
    Room,
    Subproject,
    VolunteerShift,
    VolunteerShiftAssignment,
)


@pytest.mark.django_db
def test_seed_demo_loads_educational_projects() -> None:
    call_command("seed_demo")

    assert Project.objects.count() == 3
    assert Project.objects.filter(slug="awoostria-2026").exists()
    assert Project.objects.filter(slug="cozy-furcon-2025").exists()
    assert Project.objects.filter(slug="neon-paws-2027").exists()
    assert Room.objects.filter(name="Quiet Den").exists()
    assert Subproject.objects.filter(name="Dance Competition Volunteers").exists()
    assert VolunteerShift.objects.filter(
        title="Registration Desk Morning Support"
    ).exists()
    assert VolunteerShiftAssignment.objects.filter(
        user__email="dance.helper@gmail.com"
    ).exists()
    assert ArchivedParticipation.objects.filter(
        user__email=SEED_ACCESS_EMAIL
    ).count() == 3


@pytest.mark.django_db
def test_project_pages_show_seeded_demo_data(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})

    response = client.get(reverse("projects:list"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Awoostria 2026" in content
    assert "Cozy Furcon 2025" in content
    assert "Neon Paws 2027" in content

    response = client.get(reverse("projects:detail", args=["awoostria-2026"]))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Main Convention Hotel" in content
    assert "Panel Room A+B" in content
    assert "Display - Title" in content
