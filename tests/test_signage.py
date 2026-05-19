from __future__ import annotations

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from maru.accounts.models import AccessGrant, AccessRole
from maru.domain import SEED_ACCESS_EMAIL, ExportType, Role
from maru.projects.models import (
    ExportAccessLog,
    ExportToken,
    Project,
    SignageReminder,
)


@pytest.mark.django_db
def test_staff_can_create_signage_reminder(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    project = Project.objects.get(slug="awoostria-2026")

    response = client.post(
        reverse("projects:create_signage_reminder", args=[project.slug]),
        {
            "title": "Dance prelims soon",
            "body": "Dancers should report backstage.",
            "starts_at": "2026-07-22T12:00",
            "ends_at": "2026-07-22T13:00",
            "priority": "5",
            "active": "on",
        },
        follow=True,
    )

    reminder = SignageReminder.objects.get(title="Dance prelims soon")
    assert response.status_code == 200
    assert "Signage reminder created" in response.content.decode()
    assert reminder.project == project
    assert reminder.priority == 5


@pytest.mark.django_db
def test_regular_user_cannot_create_signage_reminder(client) -> None:
    call_command("seed_demo")
    _allow_user("viewer@gmail.com")
    client.post(reverse("accounts:login"), {"email": "viewer@gmail.com"})
    project = Project.objects.get(slug="awoostria-2026")

    response = client.get(
        reverse("projects:create_signage_reminder", args=[project.slug])
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_signage_export_requires_matching_token_type(client) -> None:
    call_command("seed_demo")
    project = Project.objects.get(slug="awoostria-2026")
    token = ExportToken.objects.create(
        project=project,
        name="Website timetable",
        export_type=ExportType.PUBLIC_TIMETABLE.value,
    )

    response = client.get(
        reverse("projects:signage_reminder_export", args=[token.token])
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_signage_export_returns_only_active_window_reminders(client) -> None:
    call_command("seed_demo")
    project = Project.objects.get(slug="awoostria-2026")
    now = timezone.now()
    SignageReminder.objects.create(
        project=project,
        title="Visible high priority",
        body="Head to Main Stage.",
        starts_at=now - timezone.timedelta(minutes=10),
        ends_at=now + timezone.timedelta(minutes=30),
        priority=10,
    )
    SignageReminder.objects.create(
        project=project,
        title="Visible low priority",
        body="Merch is open.",
        starts_at=now - timezone.timedelta(minutes=5),
        ends_at=now + timezone.timedelta(minutes=30),
        priority=1,
    )
    SignageReminder.objects.create(
        project=project,
        title="Future reminder",
        starts_at=now + timezone.timedelta(minutes=5),
        ends_at=now + timezone.timedelta(minutes=30),
    )
    SignageReminder.objects.create(
        project=project,
        title="Inactive reminder",
        starts_at=now - timezone.timedelta(minutes=5),
        ends_at=now + timezone.timedelta(minutes=30),
        active=False,
    )
    token = ExportToken.objects.create(
        project=project,
        name="Hotel signage",
        export_type=ExportType.SIGNAGE_REMINDERS.value,
    )

    response = client.get(
        reverse("projects:signage_reminder_export", args=[token.token])
    )

    payload = response.json()
    log = ExportAccessLog.objects.get()
    titles = [reminder["title"] for reminder in payload["reminders"]]
    assert response.status_code == 200
    assert log.success
    assert log.export_token == token
    assert payload["export_type"] == ExportType.SIGNAGE_REMINDERS.value
    assert titles == ["Visible high priority", "Visible low priority"]
    assert payload["reminders"][0]["body"] == "Head to Main Stage."


@pytest.mark.django_db
def test_inactive_signage_token_is_rejected(client) -> None:
    call_command("seed_demo")
    project = Project.objects.get(slug="awoostria-2026")
    token = ExportToken.objects.create(
        project=project,
        name="Inactive signage",
        export_type=ExportType.SIGNAGE_REMINDERS.value,
        active=False,
    )

    response = client.get(
        reverse("projects:signage_reminder_export", args=[token.token])
    )

    log = ExportAccessLog.objects.get()
    assert response.status_code == 404
    assert not log.success
    assert log.export_token == token


def _allow_user(email: str) -> None:
    grant, _ = AccessGrant.objects.get_or_create(email=email)
    AccessRole.objects.get_or_create(grant=grant, role=Role.REGISTERED_USER.value)
