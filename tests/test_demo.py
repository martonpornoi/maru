from __future__ import annotations

import pytest
from django.core.management import call_command
from django.urls import reverse

from maru.accounts.models import ArchivedParticipation, Notification, UserProfile
from maru.domain import SEED_ACCESS_EMAIL, ApplicationStatus, AssignmentStatus
from maru.projects.models import (
    Application,
    Panel,
    Project,
    Room,
    Subproject,
    TimetablePlacement,
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
    assert Application.objects.filter(
        title="DJ Neon Trail Opening Set",
        status=ApplicationStatus.SUBMITTED.value,
    ).exists()
    assert Panel.objects.filter(title="Fursuit Cooling 101").exists()
    assert TimetablePlacement.objects.filter(
        panel__title="Emergency Plush and Paw Repairs",
        room__name="Workshop Suite",
    ).exists()
    assert VolunteerShiftAssignment.objects.filter(
        user__email="stage.runner@gmail.com",
        status=AssignmentStatus.CLAIMED.value,
    ).exists()
    assert UserProfile.objects.filter(
        user__email="cooling.host@gmail.com",
        display_name="Cooling Host",
        profile_picture="",
        fursuit_picture="",
    ).exists()
    assert Notification.objects.filter(
        user__email="cooling.host@gmail.com",
        title="Panel scheduled",
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
    assert "Cozy Furcon 2025" not in content
    assert "Neon Paws 2027" in content

    response = client.get(reverse("projects:archives"))
    content = response.content.decode()
    assert response.status_code == 200
    assert "Cozy Furcon 2025" in content

    response = client.get(reverse("projects:detail", args=["awoostria-2026"]))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Main Convention Hotel" in content
    assert "Panel Room A+B" in content
    assert "Display - Title" in content


@pytest.mark.django_db
def test_sidebar_project_selector_replaces_project_menu_links(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})

    response = client.get(reverse("accounts:my_profile"))

    content = response.content.decode()
    assert response.status_code == 200
    assert "project-switcher" in content
    assert "Awoostria 2026" in content
    assert "26.07.22 - 26.07.25" in content
    assert reverse("projects:detail", args=["awoostria-2026"]) in content
    assert "Project Operations" not in content
    assert "Project Setup" not in content

    response = client.get(reverse("projects:detail", args=["awoostria-2026"]))

    content = response.content.decode()
    switcher_button = content.split("project-switcher-button", 1)[1].split(
        "</summary>",
        1,
    )[0]
    assert response.status_code == 200
    assert "Awoostria 2026" in switcher_button
    assert "Con Spaces" in content
    assert reverse("projects:list") in content
    assert (
        reverse("accounts:project_user_directory", args=["awoostria-2026"])
        in content
    )
    assert reverse("projects:project_room_settings", args=["awoostria-2026"]) in content

    response = client.get(
        reverse("accounts:project_user_directory", args=["awoostria-2026"])
    )

    content = response.content.decode()
    switcher_button = content.split("project-switcher-button", 1)[1].split(
        "</summary>",
        1,
    )[0]
    assert response.status_code == 200
    assert "Awoostria 2026" in switcher_button
    assert reverse("social:project_list", args=["awoostria-2026"]) in content
    assert reverse("accounts:project_statistics", args=["awoostria-2026"]) in content


@pytest.mark.django_db
def test_sidebar_project_selection_persists_across_menu_items(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    client.get(reverse("projects:detail", args=["awoostria-2026"]))

    menu_urls = [
        reverse("accounts:my_profile"),
        reverse("accounts:project_user_directory", args=["awoostria-2026"]),
        reverse("social:project_list", args=["awoostria-2026"]),
        reverse("accounts:project_statistics", args=["awoostria-2026"]),
        reverse("projects:project_form_list", args=["awoostria-2026"]),
        reverse("projects:review_application_list"),
        reverse("projects:project_room_settings", args=["awoostria-2026"]),
        reverse("accounts:project_roles_access", args=["awoostria-2026"]),
        reverse("accounts:project_statuses_benefits", args=["awoostria-2026"]),
        reverse("accounts:project_labels", args=["awoostria-2026"]),
        reverse("accounts:project_user_tile_color_rules", args=["awoostria-2026"]),
        reverse("projects:archives"),
    ]

    for url in menu_urls:
        response = client.get(url)
        content = response.content.decode()
        switcher_button = _project_switcher_button_html(content)
        assert response.status_code == 200, url
        assert "Awoostria 2026" in switcher_button, url
        assert "project-switcher-exit" not in switcher_button, url


@pytest.mark.django_db
def test_projects_list_intentionally_exits_selected_project(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    client.get(reverse("projects:detail", args=["awoostria-2026"]))

    response = client.get(reverse("projects:list"))

    content = response.content.decode()
    switcher_button = _project_switcher_button_html(content)
    assert response.status_code == 200
    assert "Projects" in switcher_button
    assert "Awoostria 2026" not in switcher_button


def _project_switcher_button_html(content: str) -> str:
    archive_button = '<a class="project-switcher-button project-switcher-exit"'
    if archive_button in content:
        start = content.index(archive_button)
        return content[start : content.index("</a>", start)]
    summary_button = '<summary class="project-switcher-button">'
    start = content.index(summary_button)
    return content[start : content.index("</summary>", start)]
