from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from maru.accounts.models import (
    AccessGrant,
    AccessRole,
    UserConventionProfile,
    UserProfile,
    UserTileColorRule,
)
from maru.domain import Role, TimetableRound
from maru.projects.models import Project, ProjectArchiveSnapshot
from maru.social.models import SocialPost


@pytest.mark.django_db
def test_regular_user_sees_closed_project_archive_snapshot(client) -> None:
    call_command("seed_demo")
    project = _closed_project()
    archived_user = _create_user("archived.host@gmail.com", [Role.HOST.value])
    profile, _ = UserProfile.objects.get_or_create(user=archived_user)
    profile.display_name = "Archived Host"
    profile.save(update_fields=["display_name"])
    UserConventionProfile.objects.create(
        user=archived_user,
        project=project,
        attendee_type="Sponsor",
        roles=[Role.HOST.value],
    )
    UserTileColorRule.objects.create(
        target_type=UserTileColorRule.ATTENDEE_TYPE,
        target_value="Sponsor",
        applies_to=UserTileColorRule.EDGE,
        background_color="#112233",
    )
    SocialPost.objects.create(
        author=archived_user,
        project=project,
        title="Archived post",
        body="Frozen announcement.",
        status=SocialPost.PUBLISHED,
        published_at=timezone.now(),
    )
    _create_user("archive.viewer@gmail.com", [Role.REGISTERED_USER.value])
    client.post(reverse("accounts:login"), {"email": "archive.viewer@gmail.com"})

    response = client.get(reverse("projects:archive_detail", args=[project.slug]))

    snapshot = ProjectArchiveSnapshot.objects.get(project=project)
    content = response.content.decode()
    assert response.status_code == 200
    assert snapshot.snapshot["project"]["name"] == project.name
    assert "Cozy Furcon 2025 Archive" in content
    assert "Archived Host" in content
    assert "Archived post" in content
    assert "#112233" in content
    assert "global default" in content
    assert "archived.host@gmail.com" not in content
    assert "Refresh archive snapshot" not in content


@pytest.mark.django_db
def test_regular_user_project_detail_for_closed_project_renders_archive(client) -> None:
    call_command("seed_demo")
    project = _closed_project()
    _create_user("archive.viewer@gmail.com", [Role.REGISTERED_USER.value])
    client.post(reverse("accounts:login"), {"email": "archive.viewer@gmail.com"})

    response = client.get(reverse("projects:detail", args=[project.slug]))

    content = response.content.decode()
    switcher_button = _project_switcher_button_html(content)
    assert response.status_code == 200
    assert "Cozy Furcon 2025 Archive" in content
    assert "Cozy Furcon 2025" in switcher_button
    assert "Exit archive" in switcher_button
    assert reverse("projects:list") in switcher_button


@pytest.mark.django_db
def test_archive_detail_uses_exit_button_and_projects_restores_dropdown(client) -> None:
    call_command("seed_demo")
    project = _closed_project()
    _create_user("archive.viewer@gmail.com", [Role.REGISTERED_USER.value])
    client.post(reverse("accounts:login"), {"email": "archive.viewer@gmail.com"})
    client.get(reverse("projects:detail", args=["awoostria-2026"]))

    response = client.get(reverse("projects:archive_detail", args=[project.slug]))

    content = response.content.decode()
    switcher_button = _project_switcher_button_html(content)
    assert response.status_code == 200
    assert "project-switcher-exit" in switcher_button
    assert "Cozy Furcon 2025" in switcher_button
    assert "Exit archive" in switcher_button
    assert reverse("projects:list") in switcher_button
    assert '<details class="project-switcher">' not in content

    response = client.get(reverse("projects:list"))

    content = response.content.decode()
    switcher_button = _project_switcher_button_html(content)
    assert response.status_code == 200
    assert '<a class="project-switcher-button project-switcher-exit"' not in content
    assert "Projects" in switcher_button
    assert "Awoostria 2026" not in switcher_button


@pytest.mark.django_db
def test_archive_selection_persists_across_menu_items(client) -> None:
    call_command("seed_demo")
    project = _closed_project()
    client.post(reverse("accounts:login"), {"email": "marton.pornoi@gmail.com"})
    client.get(reverse("projects:detail", args=["awoostria-2026"]))
    client.get(reverse("projects:archive_detail", args=[project.slug]))

    menu_urls = [
        reverse("accounts:my_profile"),
        reverse("accounts:user_directory"),
        reverse("social:list"),
        reverse("accounts:statistics"),
        reverse("projects:form_list"),
        reverse("projects:review_application_list"),
        reverse("projects:hotel_list"),
        reverse("accounts:roles_access"),
        reverse("accounts:statuses_benefits"),
        reverse("accounts:labels"),
        reverse("accounts:user_tile_color_rules"),
        reverse("projects:archives"),
    ]

    for url in menu_urls:
        response = client.get(url)
        content = response.content.decode()
        switcher_button = _project_switcher_button_html(content)
        assert response.status_code == 200, url
        assert "project-switcher-exit" in switcher_button, url
        assert "Cozy Furcon 2025" in switcher_button, url
        assert "Awoostria 2026" not in switcher_button, url

    response = client.get(reverse("projects:detail", args=["awoostria-2026"]))

    content = response.content.decode()
    switcher_button = _project_switcher_button_html(content)
    assert response.status_code == 200
    assert "Awoostria 2026" in switcher_button
    assert "project-switcher-exit" not in switcher_button


@pytest.mark.django_db
def test_closed_project_live_pages_redirect_to_archive(client) -> None:
    call_command("seed_demo")
    project = _closed_project()
    _create_user("archive.viewer@gmail.com", [Role.REGISTERED_USER.value])
    client.post(reverse("accounts:login"), {"email": "archive.viewer@gmail.com"})

    users_response = client.get(
        reverse("accounts:project_user_directory", args=[project.slug])
    )
    statistics_response = client.get(
        reverse("accounts:project_statistics", args=[project.slug])
    )

    archive_url = reverse("projects:archive_detail", args=[project.slug])
    assert users_response.status_code == 302
    assert users_response["Location"] == archive_url
    assert statistics_response.status_code == 302
    assert statistics_response["Location"] == archive_url


@pytest.mark.django_db
def test_board_cannot_mutate_closed_project_setup(client) -> None:
    call_command("seed_demo")
    project = _closed_project()
    _create_user("board.closed@gmail.com", [Role.BOARD.value])
    client.post(reverse("accounts:login"), {"email": "board.closed@gmail.com"})

    form_response = client.get(
        reverse("projects:project_form_list", args=[project.slug])
    )
    color_response = client.get(
        reverse("accounts:project_user_tile_color_rules", args=[project.slug])
    )
    round_response = client.post(
        reverse(
            "projects:change_timetable_round",
            args=[project.slug, TimetableRound.PUBLIC.value],
        )
    )

    assert form_response.status_code == 403
    assert color_response.status_code == 403
    assert round_response.status_code == 403


def _closed_project() -> Project:
    project = Project.objects.get(slug="cozy-furcon-2025")
    project.closes_at = timezone.now() - timezone.timedelta(days=1)
    project.save(update_fields=["closes_at", "updated_at"])
    return project


def _create_user(email: str, roles: list[str]):
    user_model = get_user_model()
    user, created = user_model.objects.get_or_create(
        username=email,
        defaults={"email": email},
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    grant, _ = AccessGrant.objects.update_or_create(
        email=email,
        defaults={"active": True},
    )
    for role in roles:
        AccessRole.objects.get_or_create(grant=grant, role=role)
    return user


def _project_switcher_button_html(content: str) -> str:
    archive_button = '<a class="project-switcher-button project-switcher-exit"'
    if archive_button in content:
        start = content.index(archive_button)
        return content[start : content.index("</a>", start)]
    summary_button = '<summary class="project-switcher-button">'
    start = content.index(summary_button)
    return content[start : content.index("</summary>", start)]
