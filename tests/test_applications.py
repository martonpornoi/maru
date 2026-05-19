from __future__ import annotations

import pytest
from django.core.management import call_command
from django.urls import reverse

from maru.accounts.models import AccessGrant, AccessRole, Notification
from maru.domain import SEED_ACCESS_EMAIL, Role
from maru.projects.models import Application, ApplicationVersion, Subproject


@pytest.mark.django_db
def test_user_can_submit_application_from_imported_form(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    subproject = Subproject.objects.get(
        project__slug="awoostria-2026", slug="events"
    )

    response = client.post(
        reverse(
            "projects:submit_application",
            args=[subproject.project.slug, subproject.slug],
        ),
        _submission_payload(subproject),
        follow=True,
    )

    assert response.status_code == 200
    assert "Application submitted" in response.content.decode()
    application = Application.objects.get(title="Intro to Fursuit Cooling")
    assert application.applicant.email == SEED_ACCESS_EMAIL
    assert application.status == "submitted"
    version = ApplicationVersion.objects.get(application=application, version=1)
    assert version.answers["Display - Title"] == "Intro to Fursuit Cooling"
    assert version.answers["Display - Tags"] == ["Chill", "Fursuiter-Friendly"]


@pytest.mark.django_db
def test_submitted_application_appears_in_my_events(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
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

    response = client.get(reverse("accounts:my_events"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Current Applications" in content
    assert "Intro to Fursuit Cooling" in content
    assert "Event Submissions" in content


@pytest.mark.django_db
def test_user_cannot_view_another_users_application(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
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
    _allow_user("otherhost@gmail.com")
    client.post(reverse("accounts:login"), {"email": "otherhost@gmail.com"})

    response = client.get(reverse("projects:application_detail", args=[application.pk]))

    assert response.status_code == 404


@pytest.mark.django_db
def test_staff_can_reopen_application_and_notify_applicant(client) -> None:
    application = _submit_demo_application(client)

    response = client.post(
        reverse("projects:reopen_application", args=[application.pk]),
        follow=True,
    )

    application.refresh_from_db()
    assert response.status_code == 200
    assert "Application reopened for applicant edits" in response.content.decode()
    assert application.status == "reopened"
    assert Notification.objects.filter(
        user=application.applicant,
        title="Application reopened",
        body__contains="Please update and resubmit it",
    ).exists()


@pytest.mark.django_db
def test_reopened_application_can_be_edited_as_new_version(client) -> None:
    application = _submit_demo_application(client)
    client.post(reverse("projects:reopen_application", args=[application.pk]))

    edit_response = client.get(
        reverse("projects:edit_application", args=[application.pk])
    )
    assert edit_response.status_code == 200
    assert "Intro to Fursuit Cooling" in edit_response.content.decode()

    response = client.post(
        reverse("projects:edit_application", args=[application.pk]),
        _submission_payload(application.subproject, title="Updated Cooling Workshop"),
        follow=True,
    )

    application.refresh_from_db()
    versions = list(application.versions.order_by("version"))
    content = response.content.decode()
    assert response.status_code == 200
    assert "Application resubmitted" in content
    assert "Edit and resubmit application" not in content
    assert application.status == "submitted"
    assert application.title == "Updated Cooling Workshop"
    assert [version.version for version in versions] == [1, 2]
    assert versions[0].answers["Display - Title"] == "Intro to Fursuit Cooling"
    assert versions[1].answers["Display - Title"] == "Updated Cooling Workshop"


@pytest.mark.django_db
def test_resubmitted_application_notifies_staff_reviewers(client) -> None:
    call_command("seed_demo")
    _allow_user("hostone@gmail.com")
    client.post(reverse("accounts:login"), {"email": "hostone@gmail.com"})
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
    client.post(reverse("projects:reopen_application", args=[application.pk]))
    client.post(reverse("accounts:logout"))
    client.post(reverse("accounts:login"), {"email": "hostone@gmail.com"})

    client.post(
        reverse("projects:edit_application", args=[application.pk]),
        _submission_payload(subproject, title="Updated Cooling Workshop"),
    )

    notification = Notification.objects.get(
        user__email=SEED_ACCESS_EMAIL,
        title="Application resubmitted",
    )
    assert "Updated Cooling Workshop" in notification.body
    assert notification.link_url == reverse(
        "projects:review_application_detail",
        args=[application.pk],
    )
    assert notification.link_label == "Review application"


@pytest.mark.django_db
def test_application_detail_shows_all_versions_read_only(client) -> None:
    application = _submit_demo_application(client)
    client.post(reverse("projects:reopen_application", args=[application.pk]))
    client.post(
        reverse("projects:edit_application", args=[application.pk]),
        _submission_payload(application.subproject, title="Updated Cooling Workshop"),
    )

    response = client.get(reverse("projects:application_detail", args=[application.pk]))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Application Versions" in content
    assert "Version 2" in content
    assert "Version 1" in content
    assert "Updated Cooling Workshop" in content
    assert "Intro to Fursuit Cooling" in content
    assert "Edit and resubmit application" not in content


@pytest.mark.django_db
def test_submitted_application_cannot_be_edited(client) -> None:
    application = _submit_demo_application(client)

    response = client.get(reverse("projects:edit_application", args=[application.pk]))

    assert response.status_code == 403


@pytest.mark.django_db
def test_regular_user_cannot_reopen_application(client) -> None:
    application = _submit_demo_application(client)
    client.post(reverse("accounts:logout"))
    _allow_user("regularhost@gmail.com")
    client.post(reverse("accounts:login"), {"email": "regularhost@gmail.com"})

    response = client.post(
        reverse("projects:reopen_application", args=[application.pk])
    )

    assert response.status_code == 403


def _submit_demo_application(client) -> Application:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
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
    return Application.objects.get(title="Intro to Fursuit Cooling")


def _submission_payload(
    subproject: Subproject,
    title: str = "Intro to Fursuit Cooling",
) -> dict[str, str | list[str]]:
    values = {
        "Display - Title": title,
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


def _allow_user(email: str) -> None:
    grant = AccessGrant.objects.create(email=email)
    AccessRole.objects.create(grant=grant, role=Role.REGISTERED_USER.value)
