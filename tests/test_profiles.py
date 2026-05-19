from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse

from maru.accounts.models import AccessGrant, AccessRole, UserProfile
from maru.domain import SEED_ACCESS_EMAIL, Role
from maru.projects.models import Application, Subproject


@pytest.mark.django_db
def test_locked_profile_cannot_be_edited(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})

    response = client.get(reverse("accounts:profile_edit"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_approved_user_can_edit_profile(client) -> None:
    _submit_and_approve_application(client)

    response = client.post(
        reverse("accounts:profile_edit"),
        {
            "display_name": "Minute",
            "fursuit_name": "Mew",
            "telegram": "@minute",
            "discord": "minute.dev",
            "bio": "Event host and helper.",
            "show_profile_publicly": "on",
            "show_contact_handles": "on",
            "show_fursuit_picture": "on",
        },
        follow=True,
    )

    profile = UserProfile.objects.get(user__email=SEED_ACCESS_EMAIL)
    assert response.status_code == 200
    assert "Profile updated" in response.content.decode()
    assert profile.display_name == "Minute"
    assert profile.fursuit_name == "Mew"
    assert profile.telegram == "@minute"
    assert profile.discord == "minute.dev"
    assert profile.show_profile_publicly
    assert profile.show_contact_handles


@pytest.mark.django_db
def test_my_events_links_to_profile_edit_after_unlock(client) -> None:
    _submit_and_approve_application(client)

    response = client.get(reverse("accounts:my_events"))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Edit profile" in content
    assert reverse("accounts:profile_edit") in content


@pytest.mark.django_db
def test_staff_can_view_private_profile_with_contact_details(client) -> None:
    _submit_and_approve_application(client)
    profile = UserProfile.objects.get(user__email=SEED_ACCESS_EMAIL)
    profile.display_name = "Staff Host"
    profile.telegram = "@staffhost"
    profile.discord = "staff.host"
    profile.show_profile_publicly = False
    profile.show_contact_handles = False
    profile.save()

    response = client.get(reverse("accounts:profile_detail", args=[profile.pk]))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Staff view" in content
    assert SEED_ACCESS_EMAIL in content
    assert "@staffhost" in content
    assert "staff.host" in content


@pytest.mark.django_db
def test_regular_user_cannot_view_hidden_profile(client) -> None:
    _submit_and_approve_application(client)
    profile = UserProfile.objects.get(user__email=SEED_ACCESS_EMAIL)
    profile.show_profile_publicly = False
    profile.save(update_fields=["show_profile_publicly"])
    _allow_user("viewer@gmail.com")
    client.post(reverse("accounts:logout"))
    client.post(reverse("accounts:login"), {"email": "viewer@gmail.com"})

    response = client.get(reverse("accounts:profile_detail", args=[profile.pk]))

    assert response.status_code == 404


@pytest.mark.django_db
def test_regular_profile_view_respects_contact_privacy(client) -> None:
    _submit_and_approve_application(client)
    profile = UserProfile.objects.get(user__email=SEED_ACCESS_EMAIL)
    profile.display_name = "Public Host"
    profile.telegram = "@publichost"
    profile.discord = "public.host"
    profile.show_profile_publicly = True
    profile.show_contact_handles = False
    profile.save()
    _allow_user("viewer@gmail.com")
    client.post(reverse("accounts:logout"))
    client.post(reverse("accounts:login"), {"email": "viewer@gmail.com"})

    response = client.get(reverse("accounts:profile_detail", args=[profile.pk]))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Public Host" in content
    assert SEED_ACCESS_EMAIL not in content
    assert "@publichost" not in content
    assert "public.host" not in content

    profile.show_contact_handles = True
    profile.save(update_fields=["show_contact_handles"])
    response = client.get(reverse("accounts:profile_detail", args=[profile.pk]))

    content = response.content.decode()
    assert "@publichost" in content
    assert "public.host" in content
    assert SEED_ACCESS_EMAIL not in content


@pytest.mark.django_db
def test_review_detail_links_to_applicant_profile_for_staff(client) -> None:
    application = _submit_and_approve_application(client)
    profile = UserProfile.objects.get(user=application.applicant)

    response = client.get(
        reverse("projects:review_application_detail", args=[application.pk])
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert "View applicant profile" in content
    assert reverse("accounts:profile_detail", args=[profile.pk]) in content


def _submit_and_approve_application(client) -> Application:
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
    client.post(
        reverse(
            "projects:review_application_decision",
            args=[application.pk, "approve"],
        )
    )
    return application


def _allow_user(email: str):
    grant, _ = AccessGrant.objects.get_or_create(email=email)
    AccessRole.objects.get_or_create(grant=grant, role=Role.REGISTERED_USER.value)
    user, created = get_user_model().objects.get_or_create(
        username=email,
        defaults={"email": email},
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return user


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
