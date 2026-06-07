from __future__ import annotations

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from PIL import Image

from maru.accounts.models import (
    AccessGrant,
    AccessRole,
    Notification,
    UserProfile,
)
from maru.domain import SEED_ACCESS_EMAIL, Role
from maru.projects.models import Application, EventGroup, Panel, Subproject


@pytest.mark.django_db
def test_event_manager_can_approve_application_and_unlock_profile(client) -> None:
    application = _submit_demo_application(client)

    response = client.post(
        reverse(
            "projects:review_application_decision",
            args=[application.pk, "approve"],
        ),
        follow=True,
    )

    application.refresh_from_db()
    profile = UserProfile.objects.get(user=application.applicant)
    assert response.status_code == 200
    assert application.status == "approved"
    assert profile.profile_unlocked
    assert Notification.objects.filter(
        user=application.applicant,
        title="Application approved",
        body__contains="Intro to Fursuit Cooling",
    ).exists()


@pytest.mark.django_db
def test_event_manager_can_reject_application_without_unlocking_profile(client) -> None:
    application = _submit_demo_application(client)

    response = client.post(
        reverse(
            "projects:review_application_decision",
            args=[application.pk, "reject"],
        ),
        follow=True,
    )

    application.refresh_from_db()
    profile = UserProfile.objects.get(user=application.applicant)
    assert response.status_code == 200
    assert application.status == "rejected"
    assert not profile.profile_unlocked
    assert Notification.objects.filter(
        user=application.applicant,
        title="Application rejected",
    ).exists()


@pytest.mark.django_db
def test_regular_user_cannot_access_review_queue(client) -> None:
    call_command("seed_demo")
    _allow_user("regularhost@gmail.com", Role.REGISTERED_USER)
    client.post(reverse("accounts:login"), {"email": "regularhost@gmail.com"})

    response = client.get(reverse("projects:review_application_list"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_notifications_show_in_my_events_after_approval(client) -> None:
    application = _submit_demo_application(client)
    client.post(
        reverse(
            "projects:review_application_decision",
            args=[application.pk, "approve"],
        )
    )

    response = client.get(reverse("accounts:my_events"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Application approved" in content
    assert "Your profile is unlocked" in content


@pytest.mark.django_db
def test_review_detail_shows_panel_group_and_recurrence_metadata(client) -> None:
    application = _submit_demo_application(client)
    client.post(
        reverse(
            "projects:review_application_decision",
            args=[application.pk, "approve"],
        )
    )
    panel = Panel.objects.get(application=application)
    group = EventGroup.objects.create(
        project=panel.project,
        name="Cooling Track",
        slug="cooling-track",
    )
    panel.event_group = group
    panel.group_order = 2
    panel.recurrence_label = "Day 2 repeat"
    panel.save(update_fields=["event_group", "group_order", "recurrence_label"])

    response = client.get(
        reverse("projects:review_application_detail", args=[application.pk])
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert "Panel Scheduling Metadata" in content
    assert "Cooling Track" in content
    assert "Day 2 repeat" in content


@pytest.mark.django_db
def test_review_detail_shows_event_header_image(client, tmp_path) -> None:
    call_command("seed_demo")
    _allow_user("reviewhost@gmail.com", Role.REGISTERED_USER)
    client.post(reverse("accounts:login"), {"email": "reviewhost@gmail.com"})
    subproject = Subproject.objects.get(
        project__slug="awoostria-2026", slug="events"
    )
    payload = _submission_payload(subproject)
    payload["event_header_image"] = _image_upload("stage-header.png", 1920, 1080)
    with override_settings(MEDIA_ROOT=tmp_path):
        client.post(
            reverse(
                "projects:submit_application",
                args=[subproject.project.slug, subproject.slug],
            ),
            payload,
        )
        application = Application.objects.get(title="Intro to Fursuit Cooling")
        client.post(reverse("accounts:logout"))
        client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})

        response = client.get(
            reverse("projects:review_application_detail", args=[application.pk])
        )

    content = response.content.decode()
    assert response.status_code == 200
    assert "Event Header Image" in content
    assert application.event_header_image.url in content


def _submit_demo_application(client) -> Application:
    call_command("seed_demo")
    _allow_user("reviewhost@gmail.com", Role.REGISTERED_USER)
    client.post(reverse("accounts:login"), {"email": "reviewhost@gmail.com"})
    subproject = Subproject.objects.get(
        project__slug="awoostria-2026", slug="events"
    )
    client.post(
        reverse(
            "projects:submit_application",
            args=[subproject.project.slug, subproject.slug],
        ),
        _submission_payload(subproject),
    )
    application = Application.objects.get(title="Intro to Fursuit Cooling")
    client.post(reverse("accounts:logout"))
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    return application


def _submission_payload(subproject: Subproject) -> dict[str, str | list[str]]:
    values = {
        "Display - Title": "Intro to Fursuit Cooling",
        "Display - Subtitle (optional)": "Keeping cool safely",
        "Display - Abstract": "Practical tips for safer fursuiting.",
        "Display - Description": "Fans, water, breaks, and room planning.",
        "Display - Duration": "60 minutes",
        "Display - Tags": ["Chill", "Fursuiter-Friendly"],
        "Mapping - Estimated Headcount": "M",
        "Mapping - Room Layout": ["Theater"],
        "Mapping - Technical Description": "Projector and one microphone.",
        "Mapping - Things you would need from us": "Water station nearby.",
    }
    payload = {}
    for field in subproject.form_fields.all():
        payload[f"field_{field.pk}"] = values.get(field.label, "")
    return payload


def _allow_user(email: str, role: Role) -> None:
    grant = AccessGrant.objects.create(email=email)
    AccessRole.objects.create(grant=grant, role=role.value)


def _image_upload(name: str, width: int, height: int) -> SimpleUploadedFile:
    image_file = io.BytesIO()
    image = Image.new("RGB", (width, height), color="#5f6c8a")
    image.save(image_file, format="PNG")
    return SimpleUploadedFile(
        name,
        image_file.getvalue(),
        content_type="image/png",
    )
