from __future__ import annotations

import pytest
from django.core.management import call_command
from django.urls import reverse

from maru.accounts.models import AccessGrant, AccessRole
from maru.domain import SEED_ACCESS_EMAIL, Role, TimetableRound
from maru.projects.models import (
    Application,
    EventGroup,
    Panel,
    Project,
    Room,
    Subproject,
    TimetablePlacement,
    VolunteerShift,
    VolunteerShiftPlacement,
)


@pytest.mark.django_db
def test_approving_event_application_creates_panel_once(client) -> None:
    application = _submit_application(client, SEED_ACCESS_EMAIL, "Cooling 101")

    client.post(
        reverse(
            "projects:review_application_decision",
            args=[application.pk, "approve"],
        )
    )
    client.post(
        reverse(
            "projects:review_application_decision",
            args=[application.pk, "approve"],
        )
    )

    assert Panel.objects.count() == 1
    panel = Panel.objects.get()
    assert panel.title == "Cooling 101"
    assert panel.owner.email == SEED_ACCESS_EMAIL
    assert panel.project.slug == "awoostria-2026"


@pytest.mark.django_db
def test_host_can_place_own_panel_in_private_round(client) -> None:
    application = _submit_application(client, "hostone@gmail.com", "Cooling 101")
    _approve_as_staff(client, application)
    client.post(reverse("accounts:logout"))
    client.post(reverse("accounts:login"), {"email": "hostone@gmail.com"})
    panel = Panel.objects.get(application=application)
    room = Room.objects.get(hotel__project=panel.project, name="Panel Room A")

    response = client.post(
        reverse("projects:place_panel", args=[panel.pk]),
        {
            "location": f"room:{room.pk}",
            "starts_at": "2026-07-22T11:00",
            "ends_at": "2026-07-22T12:00",
        },
        follow=True,
    )

    assert response.status_code == 200
    assert "Panel placement saved" in response.content.decode()
    placement = TimetablePlacement.objects.get(panel=panel)
    assert placement.room == room
    assert placement.location_name == "Panel Room A"


@pytest.mark.django_db
def test_private_round_shows_host_only_their_own_panels(client) -> None:
    own = _submit_application(client, "hostone@gmail.com", "Cooling 101")
    other = _submit_application(client, "hosttwo@gmail.com", "Dance Meetup")
    _approve_as_staff(client, own)
    _approve_as_staff(client, other)
    client.post(reverse("accounts:logout"))
    client.post(reverse("accounts:login"), {"email": "hostone@gmail.com"})
    project = Project.objects.get(slug="awoostria-2026")

    response = client.get(reverse("projects:timetable", args=[project.slug]))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Cooling 101" in content
    assert "Dance Meetup" not in content


@pytest.mark.django_db
def test_host_cannot_place_another_hosts_panel(client) -> None:
    application = _submit_application(client, "hostone@gmail.com", "Cooling 101")
    _approve_as_staff(client, application)
    _allow_user("hosttwo@gmail.com")
    client.post(reverse("accounts:logout"))
    client.post(reverse("accounts:login"), {"email": "hosttwo@gmail.com"})
    panel = Panel.objects.get(application=application)

    response = client.get(reverse("projects:place_panel", args=[panel.pk]))

    assert response.status_code == 403


@pytest.mark.django_db
def test_staff_can_see_all_panels_in_private_round(client) -> None:
    _submit_application(client, "hostone@gmail.com", "Cooling 101")
    _submit_application(client, "hosttwo@gmail.com", "Dance Meetup")
    for application in Application.objects.all():
        _approve_as_staff(client, application)
    project = Project.objects.get(slug="awoostria-2026")

    response = client.get(reverse("projects:timetable", args=[project.slug]))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Cooling 101" in content
    assert "Dance Meetup" in content


@pytest.mark.django_db
def test_staff_can_change_timetable_round(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    project = Project.objects.get(slug="awoostria-2026")

    response = client.post(
        reverse(
            "projects:change_timetable_round",
            args=[project.slug, TimetableRound.HOST_NEGOTIATION.value],
        ),
        follow=True,
    )

    project.refresh_from_db()
    assert response.status_code == 200
    assert project.timetable_round == TimetableRound.HOST_NEGOTIATION.value
    assert "Timetable round changed" in response.content.decode()


@pytest.mark.django_db
def test_regular_user_cannot_change_timetable_round(client) -> None:
    call_command("seed_demo")
    _allow_user("hostone@gmail.com")
    client.post(reverse("accounts:login"), {"email": "hostone@gmail.com"})
    project = Project.objects.get(slug="awoostria-2026")

    response = client.post(
        reverse(
            "projects:change_timetable_round",
            args=[project.slug, TimetableRound.PUBLIC.value],
        )
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_host_negotiation_round_shows_other_hosts_panels_to_hosts(client) -> None:
    own = _submit_application(client, "hostone@gmail.com", "Cooling 101")
    other = _submit_application(client, "hosttwo@gmail.com", "Dance Meetup")
    _approve_as_staff(client, own)
    _approve_as_staff(client, other)
    project = Project.objects.get(slug="awoostria-2026")
    project.timetable_round = TimetableRound.HOST_NEGOTIATION.value
    project.save(update_fields=["timetable_round"])
    client.post(reverse("accounts:logout"))
    client.post(reverse("accounts:login"), {"email": "hostone@gmail.com"})

    response = client.get(reverse("projects:timetable", args=[project.slug]))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Cooling 101" in content
    assert "Dance Meetup" in content
    assert "View only" in content


@pytest.mark.django_db
def test_host_negotiation_round_hides_panels_from_non_hosts(client) -> None:
    application = _submit_application(client, "hostone@gmail.com", "Cooling 101")
    _approve_as_staff(client, application)
    project = Project.objects.get(slug="awoostria-2026")
    project.timetable_round = TimetableRound.HOST_NEGOTIATION.value
    project.save(update_fields=["timetable_round"])
    _allow_user("viewer@gmail.com")
    client.post(reverse("accounts:logout"))
    client.post(reverse("accounts:login"), {"email": "viewer@gmail.com"})

    response = client.get(reverse("projects:timetable", args=[project.slug]))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Cooling 101" not in content
    assert "No panels are visible" in content


@pytest.mark.django_db
def test_public_round_shows_panels_to_registered_users(client) -> None:
    application = _submit_application(client, "hostone@gmail.com", "Cooling 101")
    _approve_as_staff(client, application)
    project = Project.objects.get(slug="awoostria-2026")
    project.timetable_round = TimetableRound.PUBLIC.value
    project.save(update_fields=["timetable_round"])
    _allow_user("viewer@gmail.com")
    client.post(reverse("accounts:logout"))
    client.post(reverse("accounts:login"), {"email": "viewer@gmail.com"})

    response = client.get(reverse("projects:timetable", args=[project.slug]))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Cooling 101" in content
    assert "hostone@gmail.com" not in content


@pytest.mark.django_db
def test_public_timetable_links_public_host_profile_without_email(client) -> None:
    application = _submit_application(client, "hostone@gmail.com", "Cooling 101")
    _approve_as_staff(client, application)
    profile = application.applicant.userprofile
    profile.display_name = "Host One"
    profile.show_profile_publicly = True
    profile.save(update_fields=["display_name", "show_profile_publicly"])
    project = Project.objects.get(slug="awoostria-2026")
    project.timetable_round = TimetableRound.PUBLIC.value
    project.save(update_fields=["timetable_round"])
    _allow_user("viewer@gmail.com")
    client.post(reverse("accounts:logout"))
    client.post(reverse("accounts:login"), {"email": "viewer@gmail.com"})

    response = client.get(reverse("projects:timetable", args=[project.slug]))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Host One" in content
    assert reverse("accounts:profile_detail", args=[profile.pk]) in content
    assert "hostone@gmail.com" not in content


@pytest.mark.django_db
def test_timetable_marks_same_room_overlap_conflicts(client) -> None:
    first = _submit_application(client, "hostone@gmail.com", "Cooling 101")
    second = _submit_application(client, "hosttwo@gmail.com", "Dance Meetup")
    _approve_as_staff(client, first)
    _approve_as_staff(client, second)
    first_panel = Panel.objects.get(application=first)
    second_panel = Panel.objects.get(application=second)
    room = Room.objects.get(hotel__project=first_panel.project, name="Panel Room A")
    TimetablePlacement.objects.create(
        panel=first_panel,
        room=room,
        starts_at="2026-07-22T11:00:00+02:00",
        ends_at="2026-07-22T12:00:00+02:00",
    )
    TimetablePlacement.objects.create(
        panel=second_panel,
        room=room,
        starts_at="2026-07-22T11:30:00+02:00",
        ends_at="2026-07-22T12:30:00+02:00",
    )

    response = client.get(
        reverse("projects:timetable", args=[first_panel.project.slug])
    )

    assert response.status_code == 200
    assert "Conflict" in response.content.decode()


@pytest.mark.django_db
def test_timetable_shows_group_and_recurrence_metadata(client) -> None:
    application = _submit_application(client, "hostone@gmail.com", "Cooling 101")
    _approve_as_staff(client, application)
    panel = Panel.objects.get(application=application)
    group = EventGroup.objects.create(
        project=panel.project,
        name="Cooling Track",
        slug="cooling-track",
    )
    panel.event_group = group
    panel.group_order = 1
    panel.recurrence_label = "Daily"
    panel.save(update_fields=["event_group", "group_order", "recurrence_label"])

    response = client.get(reverse("projects:timetable", args=[panel.project.slug]))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Cooling Track" in content
    assert "#1" in content
    assert "Daily" in content


@pytest.mark.django_db
def test_staff_can_edit_panel_group_and_recurrence_metadata(client) -> None:
    application = _submit_application(client, "hostone@gmail.com", "Cooling 101")
    _approve_as_staff(client, application)
    panel = Panel.objects.get(application=application)
    group = EventGroup.objects.create(
        project=panel.project,
        name="Cooling Track",
        slug="cooling-track",
        requires_order=True,
    )

    response = client.post(
        reverse("projects:edit_panel_metadata", args=[panel.pk]),
        {
            "event_group": str(group.pk),
            "group_order": "1",
            "recurrence_label": "Daily",
        },
        follow=True,
    )

    panel.refresh_from_db()
    assert response.status_code == 200
    assert "Panel scheduling metadata saved" in response.content.decode()
    assert panel.event_group == group
    assert panel.group_order == 1
    assert panel.recurrence_label == "Daily"


@pytest.mark.django_db
def test_staff_can_create_and_edit_event_group(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    project = Project.objects.get(slug="awoostria-2026")

    response = client.post(
        reverse("projects:create_event_group", args=[project.slug]),
        {
            "name": "Story Arc",
            "slug": "story-arc",
            "description": "Ordered lore panels.",
            "requires_order": "on",
        },
        follow=True,
    )

    group = EventGroup.objects.get(project=project, slug="story-arc")
    content = response.content.decode()
    assert response.status_code == 200
    assert "Event group created" in content
    assert "Story Arc" in content
    assert group.requires_order

    response = client.post(
        reverse("projects:edit_event_group", args=[group.pk]),
        {
            "name": "Story Arc Updated",
            "slug": "story-arc",
            "description": "Updated description.",
            "requires_order": "",
        },
        follow=True,
    )

    group.refresh_from_db()
    assert response.status_code == 200
    assert "Event group updated" in response.content.decode()
    assert group.name == "Story Arc Updated"
    assert not group.requires_order


@pytest.mark.django_db
def test_regular_user_cannot_manage_event_groups(client) -> None:
    call_command("seed_demo")
    project = Project.objects.get(slug="awoostria-2026")
    group = EventGroup.objects.create(
        project=project,
        name="Story Arc",
        slug="story-arc",
    )
    _allow_user("viewer@gmail.com")
    client.post(reverse("accounts:login"), {"email": "viewer@gmail.com"})

    create_response = client.get(
        reverse("projects:create_event_group", args=[project.slug])
    )
    detail_response = client.get(
        reverse("projects:event_group_detail", args=[group.pk])
    )
    edit_response = client.get(reverse("projects:edit_event_group", args=[group.pk]))

    assert create_response.status_code == 403
    assert detail_response.status_code == 403
    assert edit_response.status_code == 403


@pytest.mark.django_db
def test_event_group_detail_shows_panels_and_missing_order_warning(client) -> None:
    application = _submit_application(client, "hostone@gmail.com", "Cooling 101")
    _approve_as_staff(client, application)
    panel = Panel.objects.get(application=application)
    group = EventGroup.objects.create(
        project=panel.project,
        name="Cooling Track",
        slug="cooling-track",
        requires_order=True,
    )
    panel.event_group = group
    panel.recurrence_label = "Daily"
    panel.save(update_fields=["event_group", "recurrence_label"])

    response = client.get(reverse("projects:event_group_detail", args=[group.pk]))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Cooling Track" in content
    assert "Cooling 101" in content
    assert "Daily" in content
    assert "Missing order" in content
    assert reverse("projects:edit_panel_metadata", args=[panel.pk]) in content


@pytest.mark.django_db
def test_regular_user_cannot_edit_panel_metadata(client) -> None:
    application = _submit_application(client, "hostone@gmail.com", "Cooling 101")
    _approve_as_staff(client, application)
    panel = Panel.objects.get(application=application)
    _allow_user("viewer@gmail.com")
    client.post(reverse("accounts:logout"))
    client.post(reverse("accounts:login"), {"email": "viewer@gmail.com"})

    response = client.get(reverse("projects:edit_panel_metadata", args=[panel.pk]))

    assert response.status_code == 403


@pytest.mark.django_db
def test_panel_metadata_rejects_duplicate_group_order(client) -> None:
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
    first_panel.save(update_fields=["event_group", "group_order"])

    response = client.post(
        reverse("projects:edit_panel_metadata", args=[second_panel.pk]),
        {
            "event_group": str(group.pk),
            "group_order": "1",
            "recurrence_label": "",
        },
    )

    second_panel.refresh_from_db()
    content = response.content.decode()
    assert response.status_code == 200
    assert "already uses this order" in content
    assert second_panel.event_group is None
    assert second_panel.group_order is None


@pytest.mark.django_db
def test_timetable_warns_when_required_group_order_is_broken(client) -> None:
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
    first_panel.save(update_fields=["event_group", "group_order"])
    second_panel.event_group = group
    second_panel.group_order = 2
    second_panel.save(update_fields=["event_group", "group_order"])
    _place_panel(
        first_panel,
        "Panel Room A",
        "2026-07-22T13:00:00+02:00",
        "2026-07-22T14:00:00+02:00",
    )
    _place_panel(
        second_panel,
        "Panel Room B",
        "2026-07-22T11:00:00+02:00",
        "2026-07-22T12:00:00+02:00",
    )

    response = client.get(reverse("projects:timetable", args=[group.project.slug]))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Group order" in content


@pytest.mark.django_db
def test_print_timetable_includes_group_order_warning_for_staff(client) -> None:
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
    first_panel.save(update_fields=["event_group", "group_order"])
    second_panel.event_group = group
    second_panel.group_order = 2
    second_panel.save(update_fields=["event_group", "group_order"])
    _place_panel(
        first_panel,
        "Panel Room A",
        "2026-07-22T13:00:00+02:00",
        "2026-07-22T14:00:00+02:00",
    )
    _place_panel(
        second_panel,
        "Panel Room B",
        "2026-07-22T11:00:00+02:00",
        "2026-07-22T12:00:00+02:00",
    )

    response = client.get(
        reverse("projects:timetable_print", args=[group.project.slug])
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert "Story Arc #1" in content
    assert "Group order warning" in content


@pytest.mark.django_db
def test_print_timetable_uses_private_round_panel_visibility(client) -> None:
    own = _submit_application(client, "hostone@gmail.com", "Cooling 101")
    other = _submit_application(client, "hosttwo@gmail.com", "Dance Meetup")
    _approve_as_staff(client, own)
    _approve_as_staff(client, other)
    own_panel = Panel.objects.get(application=own)
    other_panel = Panel.objects.get(application=other)
    _place_panel(
        own_panel,
        "Panel Room A",
        "2026-07-22T11:00:00+02:00",
        "2026-07-22T12:00:00+02:00",
    )
    _place_panel(
        other_panel,
        "Panel Room B",
        "2026-07-22T12:00:00+02:00",
        "2026-07-22T13:00:00+02:00",
    )
    client.post(reverse("accounts:logout"))
    client.post(reverse("accounts:login"), {"email": "hostone@gmail.com"})

    response = client.get(
        reverse("projects:timetable_print", args=[own_panel.project.slug])
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert "Cooling 101" in content
    assert "Dance Meetup" not in content


@pytest.mark.django_db
def test_print_timetable_public_round_shows_panels_to_registered_users(client) -> None:
    application = _submit_application(client, "hostone@gmail.com", "Cooling 101")
    _approve_as_staff(client, application)
    panel = Panel.objects.get(application=application)
    _place_panel(
        panel,
        "Panel Room A",
        "2026-07-22T11:00:00+02:00",
        "2026-07-22T12:00:00+02:00",
    )
    project = panel.project
    project.timetable_round = TimetableRound.PUBLIC.value
    project.save(update_fields=["timetable_round"])
    _allow_user("viewer@gmail.com")
    client.post(reverse("accounts:logout"))
    client.post(reverse("accounts:login"), {"email": "viewer@gmail.com"})

    response = client.get(reverse("projects:timetable_print", args=[project.slug]))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Cooling 101" in content
    assert "Panel Room A" in content


@pytest.mark.django_db
def test_staff_print_timetable_includes_volunteer_shifts(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    project = Project.objects.get(slug="awoostria-2026")
    room = Room.objects.get(hotel__project=project, name="Main Stage")
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

    response = client.get(reverse("projects:timetable_print", args=[project.slug]))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Volunteer Shift" in content
    assert "Main Stage Door Watch" in content
    assert "0/2 assigned" in content


@pytest.mark.django_db
def test_regular_print_timetable_excludes_volunteer_shifts(client) -> None:
    call_command("seed_demo")
    project = Project.objects.get(slug="awoostria-2026")
    room = Room.objects.get(hotel__project=project, name="Main Stage")
    shift = VolunteerShift.objects.create(
        project=project,
        title="Main Stage Door Watch",
        role="Stage Door",
    )
    VolunteerShiftPlacement.objects.create(
        shift=shift,
        room=room,
        starts_at="2026-07-22T14:00:00+02:00",
        ends_at="2026-07-22T16:00:00+02:00",
    )
    _allow_user("viewer@gmail.com")
    client.post(reverse("accounts:login"), {"email": "viewer@gmail.com"})

    response = client.get(reverse("projects:timetable_print", args=[project.slug]))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Main Stage Door Watch" not in content
    assert "Staff-only volunteer layers are not included" in content


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
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    client.post(
        reverse(
            "projects:review_application_decision",
            args=[application.pk, "approve"],
        )
    )


def _allow_user(email: str) -> None:
    grant, _ = AccessGrant.objects.get_or_create(email=email)
    AccessRole.objects.get_or_create(grant=grant, role=Role.REGISTERED_USER.value)


def _place_panel(panel: Panel, room_name: str, starts_at: str, ends_at: str) -> None:
    room = Room.objects.get(hotel__project=panel.project, name=room_name)
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
