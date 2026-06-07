from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse

from maru.accounts.models import (
    AccessGrant,
    AccessRole,
    UserConventionProfile,
    UserProfile,
)
from maru.domain import SEED_ACCESS_EMAIL, Role, VolunteerType
from maru.projects.models import Application, Subproject


@pytest.mark.django_db
def test_allowlisted_user_can_edit_profile_before_approval(client) -> None:
    _allow_user("lockeduser@gmail.com")
    client.post(reverse("accounts:login"), {"email": "lockeduser@gmail.com"})

    response = client.get(reverse("accounts:profile_edit"))

    assert response.status_code == 200
    assert "Edit lockeduser@gmail.com" in response.content.decode()


@pytest.mark.django_db
def test_admin_can_edit_locked_profile_settings(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    profile = UserProfile.objects.get(user__email=SEED_ACCESS_EMAIL)
    profile.profile_unlocked = False
    profile.save(update_fields=["profile_unlocked"])

    response = client.get(reverse("accounts:profile_edit"))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Edit Maru Admin" in content
    assert "Profile Settings" not in content


@pytest.mark.django_db
def test_profile_settings_are_not_global_sidebar_links(client) -> None:
    _allow_user("lockeduser@gmail.com")
    client.post(reverse("accounts:login"), {"email": "lockeduser@gmail.com"})

    response = client.get(reverse("accounts:my_events"))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Profile Settings" not in content


@pytest.mark.django_db
def test_admin_sidebar_does_not_show_profile_settings(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})

    response = client.get(reverse("accounts:my_profile"))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Profile Settings" not in content


@pytest.mark.django_db
def test_approved_user_can_edit_profile(client) -> None:
    _submit_and_approve_application(client)

    response = client.post(
        reverse("accounts:profile_edit"),
        {
            "display_name": "Minute",
            "fursuit_name": "Mew",
            "pronouns": "they/them",
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
    assert profile.pronouns == "they/them"
    assert profile.telegram == "@minute"
    assert profile.discord == "minute.dev"
    assert profile.show_profile_publicly
    assert profile.show_contact_handles


@pytest.mark.django_db
def test_user_can_save_profile_contact_and_address_details(client) -> None:
    _submit_and_approve_application(client)

    response = client.post(
        reverse("accounts:profile_edit"),
        {
            "display_name": "Minute",
            "fursuit_name": "Mew",
            "telegram": "@minute",
            "discord": "minute.dev",
            "phone_number": "+36 30 123 4567",
            "personal_email": "minute.personal@example.com",
            "convention_email": "minute@awoostria.example",
            "country": "HU",
            "postal_code": "1111",
            "city": "Budapest",
            "region": "Pest",
            "street_address": "Example Street 1",
            "address_extra": "Door 5",
            "bio": "Event host and helper.",
            "show_profile_publicly": "on",
            "show_contact_handles": "on",
            "show_fursuit_picture": "on",
        },
        follow=True,
    )

    profile = UserProfile.objects.get(user__email=SEED_ACCESS_EMAIL)
    content = response.content.decode()
    assert response.status_code == 200
    assert profile.phone_number == "+36 30 123 4567"
    assert profile.personal_email == "minute.personal@example.com"
    assert profile.convention_email == "minute@awoostria.example"
    assert profile.country == "HU"
    assert profile.postal_code == "1111"
    assert profile.city == "Budapest"
    assert "Hungary" in content
    assert "minute.personal@example.com" in content


@pytest.mark.django_db
def test_admin_can_assign_convention_profile_roles(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    profile = UserProfile.objects.get(user__email="cooling.host@gmail.com")
    project = profile.user.panels.first().project

    response = client.post(
        reverse("accounts:profile_edit_detail", args=[profile.pk]),
        {
            "display_name": "Cooling Host",
            "fursuit_name": "Frostbyte",
            "telegram": "@frostbyte",
            "discord": "frostbyte.cool",
            "bio": "Runs cooling panels.",
            "show_profile_publicly": "on",
            "show_contact_handles": "on",
            "show_fursuit_picture": "on",
            f"convention_{project.pk}-attendee_type": "Fursuiter",
            f"convention_{project.pk}-volunteer_type": VolunteerType.DEPUTY.value,
            f"convention_{project.pk}-roles": [
                Role.HOST.value,
                Role.FURSUIT_SUPPORT.value,
            ],
        },
        follow=True,
    )

    convention_profile = UserConventionProfile.objects.get(
        user=profile.user,
        project=project,
    )
    content = response.content.decode()
    assert response.status_code == 200
    assert convention_profile.attendee_type == "Fursuiter"
    assert convention_profile.volunteer_type == VolunteerType.DEPUTY.value
    assert convention_profile.roles == [
        Role.HOST.value,
        Role.FURSUIT_SUPPORT.value,
    ]
    assert "Awoostria 2026" in content
    assert "Fursuiter" in content
    assert "Deputy" in content
    assert "Fursuit Support" in content


@pytest.mark.django_db
def test_my_profile_links_to_profile_edit_after_unlock(client) -> None:
    _submit_and_approve_application(client)

    response = client.get(reverse("accounts:my_profile"))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Edit profile" in content
    assert f'class="button" href="{reverse("accounts:profile_edit")}"' in content
    assert reverse("accounts:profile_edit") in content


@pytest.mark.django_db
def test_admin_can_edit_another_users_profile_from_profile_page(client) -> None:
    call_command("seed_maru")
    target = _allow_user("targethost@gmail.com")
    target_profile, _ = UserProfile.objects.get_or_create(user=target)
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})

    response = client.get(reverse("accounts:profile_detail", args=[target_profile.pk]))

    content = response.content.decode()
    edit_url = reverse("accounts:profile_edit_detail", args=[target_profile.pk])
    assert response.status_code == 200
    assert edit_url in content
    assert "Edit profile" in content
    assert f'class="button" href="{edit_url}"' in content

    response = client.post(
        edit_url,
        {
            "display_name": "Updated Target",
            "fursuit_name": "",
            "telegram": "",
            "discord": "",
            "bio": "Updated by admin.",
            "show_profile_publicly": "on",
            "show_fursuit_picture": "on",
        },
        follow=True,
    )

    target_profile.refresh_from_db()
    content = response.content.decode()
    assert response.status_code == 200
    assert target_profile.display_name == "Updated Target"
    assert target_profile.bio == "Updated by admin."
    assert "Profile updated" in content
    assert "Updated Target" in content


@pytest.mark.django_db
def test_regular_user_cannot_edit_another_users_profile(client) -> None:
    owner = _allow_user("ownerhost@gmail.com")
    viewer = _allow_user("viewer@gmail.com")
    owner_profile, _ = UserProfile.objects.get_or_create(user=owner)
    owner_profile.profile_unlocked = True
    owner_profile.show_profile_publicly = True
    owner_profile.save(update_fields=["profile_unlocked", "show_profile_publicly"])
    client.post(reverse("accounts:login"), {"email": viewer.email})

    response = client.get(
        reverse("accounts:profile_edit_detail", args=[owner_profile.pk])
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_user_can_view_own_profile_page_with_pictures(client) -> None:
    _submit_and_approve_application(client)
    profile = UserProfile.objects.get(user__email=SEED_ACCESS_EMAIL)
    profile.display_name = "Picture Host"
    profile.fursuit_name = "Frostbyte"
    profile.profile_picture = "profiles/profile-pictures/host.png"
    profile.fursuit_picture = "profiles/fursuit-pictures/frostbyte.png"
    profile.show_profile_publicly = False
    profile.show_contact_handles = False
    profile.show_fursuit_picture = False
    profile.save()

    response = client.get(reverse("accounts:my_profile"))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Picture Host" in content
    assert (
        "Your profile, notifications, applications, archive, and shifts"
        in content
    )
    assert "Profile picture" in content
    assert "Fursuit picture" in content
    assert "/media/profiles/profile-pictures/host.png" in content
    assert "/media/profiles/fursuit-pictures/frostbyte.png" in content
    assert reverse("accounts:profile_edit") in content


@pytest.mark.django_db
def test_sidebar_links_to_own_profile(client) -> None:
    _allow_user("viewer@gmail.com")
    client.post(reverse("accounts:login"), {"email": "viewer@gmail.com"})
    profile = UserProfile.objects.get(user__email="viewer@gmail.com")
    profile.display_name = "Viewer Host"
    profile.profile_picture = "profiles/profile-pictures/viewer.png"
    profile.save(update_fields=["display_name", "profile_picture"])

    response = client.get(reverse("accounts:my_events"))

    content = response.content.decode()
    profile_card = content.split('class="sidebar-profile"', 1)[1].split("</a>", 1)[0]
    assert response.status_code == 200
    assert "Viewer Host" in content
    assert "viewer@gmail.com" not in profile_card
    assert "/media/profiles/profile-pictures/viewer.png" in content
    assert reverse("accounts:my_profile") in content


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
    assert (
        "Your profile, notifications, applications, archive, and shifts"
        in content
    )
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
