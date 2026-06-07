from __future__ import annotations

import hashlib
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse

from maru.accounts.models import AccessGrant, AccessRole, UserProfile
from maru.domain import AssignmentStatus, ExportType, Role, TimetableRound
from maru.projects.models import (
    Application,
    EventGroup,
    ExportAccessLog,
    ExportToken,
    Panel,
    Project,
    Room,
    Subproject,
    TimetablePlacement,
    VolunteerShift,
    VolunteerShiftAssignment,
    VolunteerShiftPlacement,
)


@pytest.mark.django_db
def test_public_timetable_export_requires_valid_token(client) -> None:
    response = client.get(
        reverse("projects:public_timetable_export", args=["not-a-token"])
    )

    log = ExportAccessLog.objects.get()
    assert response.status_code == 404
    assert not log.success
    assert log.status_code == 404
    assert log.export_type == ExportType.PUBLIC_TIMETABLE.value
    assert log.export_token is None
    assert log.token_hash == _token_hash("not-a-token")
    assert log.token_hash != "not-a-token"


@pytest.mark.django_db
def test_public_timetable_export_requires_matching_token_type(client) -> None:
    call_command("seed_demo")
    project = Project.objects.get(slug="awoostria-2026")
    token = ExportToken.objects.create(
        project=project,
        name="Volunteer feed",
        export_type=ExportType.VOLUNTEER_SHIFTS.value,
    )

    response = client.get(
        reverse("projects:public_timetable_export", args=[token.token])
    )

    log = ExportAccessLog.objects.get()
    assert response.status_code == 404
    assert not log.success
    assert log.export_token == token
    assert log.project == project
    assert log.export_type == ExportType.PUBLIC_TIMETABLE.value


@pytest.mark.django_db
def test_public_timetable_export_emits_public_panel_data_without_host_email(
    client,
) -> None:
    application = _submit_application(client, "hostone@gmail.com", "Cooling 101")
    application.event_header_image = "events/header-images/cooling-101.png"
    application.save(update_fields=["event_header_image"])
    _approve_as_staff(client, application)
    panel = Panel.objects.get(application=application)
    _place_panel(panel)
    project = panel.project
    project.timetable_round = TimetableRound.PUBLIC.value
    project.save(update_fields=["timetable_round"])
    token = ExportToken.objects.create(
        project=project,
        name="Website timetable",
        export_type=ExportType.PUBLIC_TIMETABLE.value,
    )

    response = client.get(
        reverse("projects:public_timetable_export", args=[token.token])
    )

    payload = response.json()
    log = ExportAccessLog.objects.get()
    assert response.status_code == 200
    assert log.success
    assert log.status_code == 200
    assert log.export_token == token
    assert log.project == project
    assert log.token_hash == _token_hash(token.token)
    assert log.token_hash != token.token
    assert payload["export_type"] == ExportType.PUBLIC_TIMETABLE.value
    assert payload["project"]["slug"] == "awoostria-2026"
    assert payload["entries"][0]["title"] == "Cooling 101"
    assert (
        payload["entries"][0]["header_image"]
        == "/media/events/header-images/cooling-101.png"
    )
    assert payload["entries"][0]["location"] == "Panel Room A"
    assert "hostone@gmail.com" not in response.content.decode()


@pytest.mark.django_db
def test_public_timetable_export_is_empty_before_public_round(client) -> None:
    application = _submit_application(client, "hostone@gmail.com", "Cooling 101")
    _approve_as_staff(client, application)
    panel = Panel.objects.get(application=application)
    _place_panel(panel)
    token = ExportToken.objects.create(
        project=panel.project,
        name="Website timetable",
        export_type=ExportType.PUBLIC_TIMETABLE.value,
    )

    response = client.get(
        reverse("projects:public_timetable_export", args=[token.token])
    )

    assert response.status_code == 200
    assert response.json()["entries"] == []


@pytest.mark.django_db
def test_public_timetable_export_includes_safe_group_metadata(client) -> None:
    first = _submit_application(client, "hostone@gmail.com", "Part One")
    second = _submit_application(client, "hosttwo@gmail.com", "Part Two")
    _approve_as_staff(client, first)
    _approve_as_staff(client, second)
    first_panel = Panel.objects.get(application=first)
    second_panel = Panel.objects.get(application=second)
    group = EventGroup.objects.create(
        project=first_panel.project,
        name="Story Arc",
        slug="story-arc",
        requires_order=True,
    )
    first_panel.event_group = group
    first_panel.group_order = 1
    first_panel.recurrence_label = "Daily"
    first_panel.save(update_fields=["event_group", "group_order", "recurrence_label"])
    second_panel.event_group = group
    second_panel.group_order = 2
    second_panel.save(update_fields=["event_group", "group_order"])
    _place_panel(first_panel)
    _place_panel(
        second_panel,
        room_name="Panel Room B",
        starts_at="2026-07-22T12:00:00+02:00",
        ends_at="2026-07-22T13:00:00+02:00",
    )
    project = first_panel.project
    project.timetable_round = TimetableRound.PUBLIC.value
    project.save(update_fields=["timetable_round"])
    token = ExportToken.objects.create(
        project=project,
        name="Website timetable",
        export_type=ExportType.PUBLIC_TIMETABLE.value,
    )

    response = client.get(
        reverse("projects:public_timetable_export", args=[token.token])
    )

    payload = response.json()
    first_entry = next(
        entry for entry in payload["entries"] if entry["title"] == "Part One"
    )
    second_entry = next(
        entry for entry in payload["entries"] if entry["title"] == "Part Two"
    )
    content = response.content.decode()
    assert response.status_code == 200
    assert first_entry["group"] == {
        "name": "Story Arc",
        "slug": "story-arc",
        "order": 1,
        "recurrence_label": "Daily",
    }
    assert second_entry["group"]["order"] == 2
    assert "Group order warning" not in content
    assert "requires_order" not in content
    assert "hostone@gmail.com" not in content
    assert "hosttwo@gmail.com" not in content


@pytest.mark.django_db
def test_inactive_export_token_is_rejected(client) -> None:
    call_command("seed_demo")
    project = Project.objects.get(slug="awoostria-2026")
    token = ExportToken.objects.create(
        project=project,
        name="Inactive timetable",
        export_type=ExportType.PUBLIC_TIMETABLE.value,
        active=False,
    )

    response = client.get(
        reverse("projects:public_timetable_export", args=[token.token])
    )

    log = ExportAccessLog.objects.get()
    assert response.status_code == 404
    assert not log.success
    assert log.export_token == token
    assert log.project == project


@pytest.mark.django_db
def test_check_export_tokens_reports_health_without_raw_token(client) -> None:
    call_command("seed_demo")
    project = Project.objects.get(slug="awoostria-2026")
    token = ExportToken.objects.create(
        project=project,
        name="Website timetable",
        export_type=ExportType.PUBLIC_TIMETABLE.value,
    )
    project.timetable_round = TimetableRound.PUBLIC.value
    project.save(update_fields=["timetable_round"])
    client.get(reverse("projects:public_timetable_export", args=[token.token]))
    out = StringIO()

    call_command("check_export_tokens", stdout=out)

    output = out.getvalue()
    assert "project=awoostria-2026" in output
    assert "name=Website timetable" in output
    assert "type=public_timetable" in output
    assert "status=active" in output
    assert "last_success=never" not in output
    assert token.token not in output


@pytest.mark.django_db
def test_check_export_tokens_can_filter_by_project() -> None:
    call_command("seed_demo")
    first = Project.objects.get(slug="awoostria-2026")
    second = Project.objects.get(slug="cozy-furcon-2025")
    ExportToken.objects.create(
        project=first,
        name="Awoostria feed",
        export_type=ExportType.PUBLIC_TIMETABLE.value,
    )
    ExportToken.objects.create(
        project=second,
        name="Cozy feed",
        export_type=ExportType.PUBLIC_TIMETABLE.value,
    )
    out = StringIO()

    call_command("check_export_tokens", "--project", "cozy-furcon-2025", stdout=out)

    output = out.getvalue()
    assert "project=cozy-furcon-2025" in output
    assert "project=awoostria-2026" not in output


@pytest.mark.django_db
def test_admin_can_create_export_token_from_project_ui(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": "marton.pornoi@gmail.com"})
    project = Project.objects.get(slug="awoostria-2026")

    response = client.post(
        reverse("projects:export_token_list", args=[project.slug]),
        {
            "active": "on",
            "export_type": ExportType.PUBLIC_TIMETABLE.value,
            "name": "Website timetable",
        },
    )

    token = ExportToken.objects.get(name="Website timetable")
    content = response.content.decode()
    assert response.status_code == 200
    assert token.project == project
    assert token.active
    assert token.token in content
    assert "Copy it now" in content


@pytest.mark.django_db
def test_board_can_rotate_export_token_from_project_ui(client) -> None:
    call_command("seed_demo")
    _allow_user("boarduser@gmail.com", [Role.BOARD.value])
    client.post(reverse("accounts:login"), {"email": "boarduser@gmail.com"})
    project = Project.objects.get(slug="awoostria-2026")
    token = ExportToken.objects.create(
        project=project,
        name="Website timetable",
        export_type=ExportType.PUBLIC_TIMETABLE.value,
    )
    old_token = token.token

    response = client.post(reverse("projects:rotate_export_token", args=[token.pk]))

    token.refresh_from_db()
    content = response.content.decode()
    assert response.status_code == 200
    assert token.active
    assert token.token != old_token
    assert token.token in content
    assert old_token not in content


@pytest.mark.django_db
def test_event_manager_cannot_manage_export_tokens(client) -> None:
    call_command("seed_demo")
    _allow_user("eventmanager@gmail.com", [Role.EVENT_MANAGER.value])
    client.post(reverse("accounts:login"), {"email": "eventmanager@gmail.com"})
    project = Project.objects.get(slug="awoostria-2026")

    response = client.get(reverse("projects:export_token_list", args=[project.slug]))

    assert response.status_code == 403


@pytest.mark.django_db
def test_admin_can_deactivate_and_reactivate_export_token(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": "marton.pornoi@gmail.com"})
    project = Project.objects.get(slug="awoostria-2026")
    token = ExportToken.objects.create(
        project=project,
        name="Website timetable",
        export_type=ExportType.PUBLIC_TIMETABLE.value,
    )

    response = client.post(
        reverse("projects:set_export_token_active", args=[token.pk, "inactive"])
    )
    token.refresh_from_db()
    assert response.status_code == 302
    assert not token.active

    response = client.post(
        reverse("projects:set_export_token_active", args=[token.pk, "active"])
    )
    token.refresh_from_db()
    assert response.status_code == 302
    assert token.active


@pytest.mark.django_db
def test_volunteer_shift_export_exposes_counts_but_not_user_profiles(client) -> None:
    call_command("seed_demo")
    project = Project.objects.get(slug="awoostria-2026")
    volunteer = _allow_user("helper@gmail.com")
    room = Room.objects.get(hotel__projects=project, name="Main Stage")
    shift = VolunteerShift.objects.create(
        project=project,
        title="Main Stage Door Watch",
        role="Stage Door",
        needed_volunteers=2,
    )
    VolunteerShiftPlacement.objects.create(
        shift=shift,
        room=room,
        starts_at="2026-07-22T14:00:00+02:00",
        ends_at="2026-07-22T16:00:00+02:00",
    )
    VolunteerShiftAssignment.objects.create(
        shift=shift,
        user=volunteer,
        status=AssignmentStatus.CONFIRMED.value,
    )
    token = ExportToken.objects.create(
        project=project,
        name="Volunteer staffing",
        export_type=ExportType.VOLUNTEER_SHIFTS.value,
    )

    response = client.get(
        reverse("projects:volunteer_shift_export", args=[token.token])
    )

    payload = response.json()
    entry = next(
        entry
        for entry in payload["entries"]
        if entry["title"] == "Main Stage Door Watch"
    )
    assert response.status_code == 200
    assert entry["confirmed_assignments"] == 1
    assert "helper@gmail.com" not in response.content.decode()


@pytest.mark.django_db
def test_public_profile_export_is_empty_until_project_policy_enables_it(client) -> None:
    application = _submit_application(client, "hostone@gmail.com", "Cooling 101")
    _approve_as_staff(client, application)
    profile = UserProfile.objects.get(user__email="hostone@gmail.com")
    profile.display_name = "Host One"
    profile.show_profile_publicly = True
    profile.save(update_fields=["display_name", "show_profile_publicly"])
    token = ExportToken.objects.create(
        project=application.subproject.project,
        name="Website profiles",
        export_type=ExportType.PUBLIC_PROFILES.value,
    )

    response = client.get(reverse("projects:public_profile_export", args=[token.token]))

    log = ExportAccessLog.objects.get()
    assert response.status_code == 200
    assert response.json()["entries"] == []
    assert log.success
    assert log.export_type == ExportType.PUBLIC_PROFILES.value


@pytest.mark.django_db
def test_public_profile_export_exposes_only_consented_non_contact_fields(
    client,
) -> None:
    application = _submit_application(client, "hostone@gmail.com", "Cooling 101")
    _approve_as_staff(client, application)
    project = application.subproject.project
    project.profile_exports_enabled = True
    project.save(update_fields=["profile_exports_enabled"])
    profile = UserProfile.objects.get(user__email="hostone@gmail.com")
    profile.display_name = "Host One"
    profile.fursuit_name = "Frostbyte"
    profile.bio = "Hosts cooling panels."
    profile.profile_picture = "profiles/profile-pictures/host.png"
    profile.fursuit_picture = "profiles/fursuit-pictures/frostbyte.png"
    profile.telegram = "@hostone"
    profile.discord = "host.one"
    profile.show_profile_publicly = True
    profile.show_contact_handles = True
    profile.show_fursuit_picture = True
    profile.save()
    token = ExportToken.objects.create(
        project=project,
        name="Website profiles",
        export_type=ExportType.PUBLIC_PROFILES.value,
    )

    response = client.get(reverse("projects:public_profile_export", args=[token.token]))

    payload = response.json()
    entry = next(
        item for item in payload["entries"] if item["display_name"] == "Host One"
    )
    content = response.content.decode()
    assert response.status_code == 200
    assert payload["export_type"] == ExportType.PUBLIC_PROFILES.value
    assert entry["display_name"] == "Host One"
    assert entry["fursuit_name"] == "Frostbyte"
    assert entry["bio"] == "Hosts cooling panels."
    assert entry["profile_picture"].endswith(
        "/media/profiles/profile-pictures/host.png"
    )
    assert entry["fursuit_picture"].endswith(
        "/media/profiles/fursuit-pictures/frostbyte.png"
    )
    assert "contact" not in entry
    assert "hostone@gmail.com" not in content
    assert "@hostone" not in content
    assert "host.one" not in content


@pytest.mark.django_db
def test_public_profile_export_contact_requires_project_and_profile_consent(
    client,
) -> None:
    application = _submit_application(client, "hostone@gmail.com", "Cooling 101")
    _approve_as_staff(client, application)
    project = application.subproject.project
    project.profile_exports_enabled = True
    project.profile_contact_exports_enabled = True
    project.save(
        update_fields=[
            "profile_exports_enabled",
            "profile_contact_exports_enabled",
        ]
    )
    profile = UserProfile.objects.get(user__email="hostone@gmail.com")
    profile.display_name = "Host One"
    profile.telegram = "@hostone"
    profile.discord = "host.one"
    profile.show_profile_publicly = True
    profile.show_contact_handles = False
    profile.save()
    token = ExportToken.objects.create(
        project=project,
        name="Website profiles",
        export_type=ExportType.PUBLIC_PROFILES.value,
    )

    response = client.get(reverse("projects:public_profile_export", args=[token.token]))

    entry = next(
        item
        for item in response.json()["entries"]
        if item["display_name"] == "Host One"
    )
    assert "contact" not in entry

    profile.show_contact_handles = True
    profile.save(update_fields=["show_contact_handles"])
    response = client.get(reverse("projects:public_profile_export", args=[token.token]))

    entry = next(
        item
        for item in response.json()["entries"]
        if item["display_name"] == "Host One"
    )
    assert entry["contact"] == {
        "telegram": "@hostone",
        "discord": "host.one",
    }


@pytest.mark.django_db
def test_public_profile_export_excludes_unapproved_or_hidden_profiles(client) -> None:
    application = _submit_application(client, "hostone@gmail.com", "Cooling 101")
    _approve_as_staff(client, application)
    project = application.subproject.project
    project.profile_exports_enabled = True
    project.save(update_fields=["profile_exports_enabled"])
    approved_profile = UserProfile.objects.get(user__email="hostone@gmail.com")
    approved_profile.display_name = "Hidden Host"
    approved_profile.show_profile_publicly = False
    approved_profile.save(update_fields=["display_name", "show_profile_publicly"])
    unapproved = _allow_user("waiting@gmail.com")
    UserProfile.objects.create(
        user=unapproved,
        profile_unlocked=True,
        display_name="Waiting Host",
        show_profile_publicly=True,
    )
    token = ExportToken.objects.create(
        project=project,
        name="Website profiles",
        export_type=ExportType.PUBLIC_PROFILES.value,
    )

    response = client.get(reverse("projects:public_profile_export", args=[token.token]))

    content = response.content.decode()
    assert response.status_code == 200
    display_names = {entry["display_name"] for entry in response.json()["entries"]}
    assert "Hidden Host" not in display_names
    assert "Waiting Host" not in display_names
    assert "Hidden Host" not in content
    assert "Waiting Host" not in content
    assert "waiting@gmail.com" not in content


def _submit_application(client, email: str, title: str) -> Application:
    call_command("seed_demo")
    _allow_user(email)
    client.post(reverse("accounts:logout"))
    client.post(reverse("accounts:login"), {"email": email})
    subproject = Subproject.objects.get(
        project__slug="awoostria-2026", slug="events"
    )
    client.post(
        reverse(
            "projects:submit_application",
            args=[subproject.project.slug, subproject.slug],
        ),
        _submission_payload(subproject, title),
    )
    return Application.objects.get(title=title)


def _approve_as_staff(client, application: Application) -> None:
    client.post(reverse("accounts:logout"))
    client.post(reverse("accounts:login"), {"email": "marton.pornoi@gmail.com"})
    client.post(
        reverse(
            "projects:review_application_decision",
            args=[application.pk, "approve"],
        )
    )


def _allow_user(email: str, roles: list[str] | None = None):
    roles = roles or [Role.REGISTERED_USER.value]
    grant, _ = AccessGrant.objects.get_or_create(email=email)
    for role in roles:
        AccessRole.objects.get_or_create(grant=grant, role=role)
    user, created = get_user_model().objects.get_or_create(
        username=email,
        defaults={"email": email},
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return user


def _place_panel(
    panel: Panel,
    room_name: str = "Panel Room A",
    starts_at: str = "2026-07-22T11:00:00+02:00",
    ends_at: str = "2026-07-22T12:00:00+02:00",
) -> None:
    room = Room.objects.get(hotel__projects=panel.project, name=room_name)
    TimetablePlacement.objects.create(
        panel=panel,
        room=room,
        starts_at=starts_at,
        ends_at=ends_at,
    )


def _submission_payload(
    subproject: Subproject, title: str
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


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
