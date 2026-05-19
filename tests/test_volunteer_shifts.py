from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse

from maru.accounts.models import AccessGrant, AccessRole
from maru.domain import SEED_ACCESS_EMAIL, AssignmentStatus, Role
from maru.projects.models import (
    Project,
    Room,
    VolunteerShift,
    VolunteerShiftAssignment,
    VolunteerShiftPlacement,
)


@pytest.mark.django_db
def test_staff_can_create_and_place_volunteer_shift(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    project = Project.objects.get(slug="awoostria-2026")

    response = client.post(
        reverse("projects:create_volunteer_shift", args=[project.slug]),
        {
            "title": "Main Stage Door Watch",
            "role": "Stage Door",
            "needed_volunteers": "2",
            "notes": "Keep performers moving safely.",
        },
        follow=True,
    )

    assert response.status_code == 200
    shift = VolunteerShift.objects.get(title="Main Stage Door Watch")
    assert shift.needed_volunteers == 2
    room = Room.objects.get(hotel__project=project, name="Main Stage")

    response = client.post(
        reverse("projects:place_volunteer_shift", args=[shift.pk]),
        {
            "location": f"room:{room.pk}",
            "starts_at": "2026-07-22T13:00",
            "ends_at": "2026-07-22T15:00",
        },
        follow=True,
    )

    assert response.status_code == 200
    assert "Volunteer shift placement saved" in response.content.decode()
    placement = VolunteerShiftPlacement.objects.get(shift=shift)
    assert placement.room == room


@pytest.mark.django_db
def test_regular_user_cannot_create_volunteer_shift(client) -> None:
    call_command("seed_demo")
    _allow_user("helper@gmail.com")
    client.post(reverse("accounts:login"), {"email": "helper@gmail.com"})
    project = Project.objects.get(slug="awoostria-2026")

    response = client.get(
        reverse("projects:create_volunteer_shift", args=[project.slug])
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_timetable_shows_volunteer_shift_layer_to_staff(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    project = Project.objects.get(slug="awoostria-2026")
    shift = VolunteerShift.objects.create(
        project=project,
        title="Dance Competition Check-in",
        role="Check-in",
    )
    room = Room.objects.get(hotel__project=project, name="Main Stage")
    VolunteerShiftPlacement.objects.create(
        shift=shift,
        room=room,
        starts_at="2026-07-22T14:00:00+02:00",
        ends_at="2026-07-22T16:00:00+02:00",
    )

    response = client.get(reverse("projects:timetable", args=[project.slug]))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Volunteer Shifts" in content
    assert "Dance Competition Check-in" in content
    assert "Check-in" in content


@pytest.mark.django_db
def test_timetable_hides_volunteer_shift_layer_from_regular_users(client) -> None:
    call_command("seed_demo")
    project = Project.objects.get(slug="awoostria-2026")
    VolunteerShift.objects.create(
        project=project,
        title="Dance Competition Check-in",
        role="Check-in",
    )
    _allow_user("viewer@gmail.com")
    client.post(reverse("accounts:login"), {"email": "viewer@gmail.com"})

    response = client.get(reverse("projects:timetable", args=[project.slug]))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Volunteer Shifts" not in content
    assert "Dance Competition Check-in" not in content


@pytest.mark.django_db
def test_volunteer_shift_layer_marks_same_room_overlap_conflicts(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    project = Project.objects.get(slug="awoostria-2026")
    room = Room.objects.get(hotel__project=project, name="Main Stage")
    first = VolunteerShift.objects.create(
        project=project,
        title="Main Stage Door Watch",
        role="Stage Door",
    )
    second = VolunteerShift.objects.create(
        project=project,
        title="Main Stage Runner",
        role="Runner",
    )
    VolunteerShiftPlacement.objects.create(
        shift=first,
        room=room,
        starts_at="2026-07-22T14:00:00+02:00",
        ends_at="2026-07-22T16:00:00+02:00",
    )
    VolunteerShiftPlacement.objects.create(
        shift=second,
        room=room,
        starts_at="2026-07-22T15:00:00+02:00",
        ends_at="2026-07-22T17:00:00+02:00",
    )

    response = client.get(reverse("projects:timetable", args=[project.slug]))

    assert response.status_code == 200
    assert "Conflict" in response.content.decode()


@pytest.mark.django_db
def test_staff_can_assign_registered_user_to_volunteer_shift(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    project = Project.objects.get(slug="awoostria-2026")
    helper = _allow_user("helper@gmail.com")
    shift = VolunteerShift.objects.create(
        project=project,
        title="Dance Competition Check-in",
        role="Check-in",
        needed_volunteers=2,
    )

    response = client.post(
        reverse("projects:assign_volunteer_shift", args=[shift.pk]),
        {"user": helper.pk, "notes": "Prefers afternoon shifts."},
        follow=True,
    )

    assert response.status_code == 200
    assert "Volunteer assigned" in response.content.decode()
    assignment = VolunteerShiftAssignment.objects.get(shift=shift, user=helper)
    assert assignment.notes == "Prefers afternoon shifts."
    assert assignment.assigned_by.email == SEED_ACCESS_EMAIL
    assert assignment.status == AssignmentStatus.CONFIRMED.value


@pytest.mark.django_db
def test_regular_user_cannot_assign_volunteer_shift(client) -> None:
    call_command("seed_demo")
    viewer = _allow_user("viewer@gmail.com")
    client.post(reverse("accounts:login"), {"email": viewer.email})
    project = Project.objects.get(slug="awoostria-2026")
    helper = _allow_user("helper@gmail.com")
    shift = VolunteerShift.objects.create(
        project=project,
        title="Dance Competition Check-in",
        role="Check-in",
    )

    response = client.post(
        reverse("projects:assign_volunteer_shift", args=[shift.pk]),
        {"user": helper.pk},
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_assigned_shift_appears_in_my_events(client) -> None:
    call_command("seed_demo")
    helper = _allow_user("helper@gmail.com")
    project = Project.objects.get(slug="awoostria-2026")
    room = Room.objects.get(hotel__project=project, name="Main Stage")
    shift = VolunteerShift.objects.create(
        project=project,
        title="Dance Competition Check-in",
        role="Check-in",
    )
    VolunteerShiftPlacement.objects.create(
        shift=shift,
        room=room,
        starts_at="2026-07-22T14:00:00+02:00",
        ends_at="2026-07-22T16:00:00+02:00",
    )
    VolunteerShiftAssignment.objects.create(shift=shift, user=helper)
    client.post(reverse("accounts:login"), {"email": helper.email})

    response = client.get(reverse("accounts:my_events"))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Volunteer Shifts" in content
    assert "Dance Competition Check-in" in content
    assert "Main Stage" in content


@pytest.mark.django_db
def test_volunteer_can_claim_open_shift(client) -> None:
    call_command("seed_demo")
    volunteer = _allow_user("claimant@gmail.com", roles=[Role.VOLUNTEER.value])
    project = Project.objects.get(slug="awoostria-2026")
    shift = _placed_shift(
        project=project,
        title="Late Night Door Watch",
        starts_at="2026-07-22T20:00:00+02:00",
        ends_at="2026-07-22T22:00:00+02:00",
    )
    client.post(reverse("accounts:login"), {"email": volunteer.email})

    response = client.post(
        reverse("projects:claim_volunteer_shift", args=[shift.pk]),
        follow=True,
    )

    assert response.status_code == 200
    assert "Volunteer shift claimed" in response.content.decode()
    assignment = VolunteerShiftAssignment.objects.get(shift=shift, user=volunteer)
    assert assignment.assigned_by is None
    assert assignment.status == AssignmentStatus.CLAIMED.value
    assert reverse("projects:volunteer_shift_detail", args=[shift.pk]) in (
        response.redirect_chain[-1][0]
    )


@pytest.mark.django_db
def test_volunteer_shift_list_links_to_detail_page(client) -> None:
    call_command("seed_demo")
    volunteer = _allow_user("claimant@gmail.com", roles=[Role.VOLUNTEER.value])
    project = Project.objects.get(slug="awoostria-2026")
    shift = _placed_shift(
        project=project,
        title="Detail Linked Door Watch",
        starts_at="2026-07-22T20:00:00+02:00",
        ends_at="2026-07-22T22:00:00+02:00",
    )
    client.post(reverse("accounts:login"), {"email": volunteer.email})

    response = client.get(reverse("projects:volunteer_shift_list", args=[project.slug]))

    content = response.content.decode()
    assert response.status_code == 200
    assert reverse("projects:volunteer_shift_detail", args=[shift.pk]) in content
    assert "Claim shift" not in content


@pytest.mark.django_db
def test_volunteer_shift_detail_shows_claim_action_and_notes(client) -> None:
    call_command("seed_demo")
    volunteer = _allow_user("claimant@gmail.com", roles=[Role.VOLUNTEER.value])
    project = Project.objects.get(slug="awoostria-2026")
    shift = _placed_shift(
        project=project,
        title="Detailed Door Watch",
        starts_at="2026-07-22T20:00:00+02:00",
        ends_at="2026-07-22T22:00:00+02:00",
    )
    shift.notes = "Keep the doorway clear and call staff if queues build up."
    shift.save(update_fields=["notes"])
    client.post(reverse("accounts:login"), {"email": volunteer.email})

    response = client.get(reverse("projects:volunteer_shift_detail", args=[shift.pk]))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Detailed Door Watch" in content
    assert "Keep the doorway clear" in content
    assert "Claim shift" in content


@pytest.mark.django_db
def test_volunteer_shift_detail_hides_other_volunteers_from_volunteer(client) -> None:
    call_command("seed_demo")
    volunteer = _allow_user("claimant@gmail.com", roles=[Role.VOLUNTEER.value])
    other = _allow_user("otherhelper@gmail.com", roles=[Role.VOLUNTEER.value])
    project = Project.objects.get(slug="awoostria-2026")
    shift = _placed_shift(
        project=project,
        title="Private Door Watch",
        starts_at="2026-07-22T20:00:00+02:00",
        ends_at="2026-07-22T22:00:00+02:00",
    )
    VolunteerShiftAssignment.objects.create(
        shift=shift,
        user=other,
        status=AssignmentStatus.CONFIRMED.value,
    )
    client.post(reverse("accounts:login"), {"email": volunteer.email})

    response = client.get(reverse("projects:volunteer_shift_detail", args=[shift.pk]))

    content = response.content.decode()
    assert response.status_code == 200
    assert "otherhelper@gmail.com" not in content


@pytest.mark.django_db
def test_staff_shift_detail_shows_assignment_list(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    volunteer = _allow_user("claimant@gmail.com", roles=[Role.VOLUNTEER.value])
    project = Project.objects.get(slug="awoostria-2026")
    shift = _placed_shift(
        project=project,
        title="Staff Visible Door Watch",
        starts_at="2026-07-22T20:00:00+02:00",
        ends_at="2026-07-22T22:00:00+02:00",
    )
    VolunteerShiftAssignment.objects.create(
        shift=shift,
        user=volunteer,
        status=AssignmentStatus.CONFIRMED.value,
    )

    response = client.get(reverse("projects:volunteer_shift_detail", args=[shift.pk]))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Staff View" in content
    assert "claimant@gmail.com" in content


@pytest.mark.django_db
def test_regular_user_cannot_view_open_volunteer_shifts(client) -> None:
    call_command("seed_demo")
    viewer = _allow_user("viewer@gmail.com")
    client.post(reverse("accounts:login"), {"email": viewer.email})

    response = client.get(
        reverse("projects:volunteer_shift_list", args=["awoostria-2026"])
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_volunteer_cannot_claim_full_shift(client) -> None:
    call_command("seed_demo")
    volunteer = _allow_user("claimant@gmail.com", roles=[Role.VOLUNTEER.value])
    other = _allow_user("otherhelper@gmail.com", roles=[Role.VOLUNTEER.value])
    project = Project.objects.get(slug="awoostria-2026")
    shift = _placed_shift(
        project=project,
        title="Full Door Watch",
        starts_at="2026-07-22T20:00:00+02:00",
        ends_at="2026-07-22T22:00:00+02:00",
        needed_volunteers=1,
    )
    VolunteerShiftAssignment.objects.create(shift=shift, user=other)
    client.post(reverse("accounts:login"), {"email": volunteer.email})

    response = client.post(
        reverse("projects:claim_volunteer_shift", args=[shift.pk]),
        follow=True,
    )

    assert response.status_code == 200
    assert "Shift is full" in response.content.decode()
    assert not VolunteerShiftAssignment.objects.filter(
        shift=shift, user=volunteer
    ).exists()


@pytest.mark.django_db
def test_volunteer_cannot_claim_overlapping_shift(client) -> None:
    call_command("seed_demo")
    volunteer = _allow_user("claimant@gmail.com", roles=[Role.VOLUNTEER.value])
    project = Project.objects.get(slug="awoostria-2026")
    first = _placed_shift(
        project=project,
        title="First Door Watch",
        starts_at="2026-07-22T20:00:00+02:00",
        ends_at="2026-07-22T22:00:00+02:00",
    )
    second = _placed_shift(
        project=project,
        title="Overlapping Door Watch",
        starts_at="2026-07-22T21:00:00+02:00",
        ends_at="2026-07-22T23:00:00+02:00",
    )
    VolunteerShiftAssignment.objects.create(shift=first, user=volunteer)
    client.post(reverse("accounts:login"), {"email": volunteer.email})

    response = client.post(
        reverse("projects:claim_volunteer_shift", args=[second.pk]),
        follow=True,
    )

    assert response.status_code == 200
    assert "Conflicts with one of your assigned shifts" in response.content.decode()
    assert not VolunteerShiftAssignment.objects.filter(
        shift=second, user=volunteer
    ).exists()


@pytest.mark.django_db
def test_staff_can_confirm_claimed_volunteer_shift(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    volunteer = _allow_user("claimant@gmail.com", roles=[Role.VOLUNTEER.value])
    project = Project.objects.get(slug="awoostria-2026")
    shift = _placed_shift(
        project=project,
        title="Claimed Door Watch",
        starts_at="2026-07-22T20:00:00+02:00",
        ends_at="2026-07-22T22:00:00+02:00",
    )
    assignment = VolunteerShiftAssignment.objects.create(
        shift=shift,
        user=volunteer,
        status=AssignmentStatus.CLAIMED.value,
    )

    response = client.post(
        reverse(
            "projects:change_volunteer_assignment_status",
            args=[assignment.pk, AssignmentStatus.CONFIRMED.value],
        ),
        follow=True,
    )

    assignment.refresh_from_db()
    assert response.status_code == 200
    assert "marked confirmed" in response.content.decode()
    assert assignment.status == AssignmentStatus.CONFIRMED.value


@pytest.mark.django_db
def test_staff_can_remove_claim_and_free_capacity(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    volunteer = _allow_user("claimant@gmail.com", roles=[Role.VOLUNTEER.value])
    project = Project.objects.get(slug="awoostria-2026")
    shift = _placed_shift(
        project=project,
        title="Removable Door Watch",
        starts_at="2026-07-22T20:00:00+02:00",
        ends_at="2026-07-22T22:00:00+02:00",
        needed_volunteers=1,
    )
    assignment = VolunteerShiftAssignment.objects.create(
        shift=shift,
        user=volunteer,
        status=AssignmentStatus.CONFIRMED.value,
    )

    response = client.post(
        reverse(
            "projects:change_volunteer_assignment_status",
            args=[assignment.pk, AssignmentStatus.REMOVED.value],
        ),
        follow=True,
    )

    assignment.refresh_from_db()
    shift.refresh_from_db()
    assert response.status_code == 200
    assert assignment.status == AssignmentStatus.REMOVED.value
    assert shift.assignment_count == 0
    assert shift.open_spots == 1


@pytest.mark.django_db
def test_locked_shift_cannot_be_claimed(client) -> None:
    call_command("seed_demo")
    volunteer = _allow_user("claimant@gmail.com", roles=[Role.VOLUNTEER.value])
    project = Project.objects.get(slug="awoostria-2026")
    shift = _placed_shift(
        project=project,
        title="Locked Door Watch",
        starts_at="2026-07-22T20:00:00+02:00",
        ends_at="2026-07-22T22:00:00+02:00",
    )
    shift.locked = True
    shift.save(update_fields=["locked"])
    client.post(reverse("accounts:login"), {"email": volunteer.email})

    response = client.post(
        reverse("projects:claim_volunteer_shift", args=[shift.pk]),
        follow=True,
    )

    assert response.status_code == 200
    assert "Shift is locked" in response.content.decode()
    assert not VolunteerShiftAssignment.objects.filter(
        shift=shift,
        user=volunteer,
    ).exists()


@pytest.mark.django_db
def test_staff_can_lock_and_reopen_shift(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    project = Project.objects.get(slug="awoostria-2026")
    shift = _placed_shift(
        project=project,
        title="Lockable Door Watch",
        starts_at="2026-07-22T20:00:00+02:00",
        ends_at="2026-07-22T22:00:00+02:00",
    )

    response = client.post(
        reverse("projects:lock_volunteer_shift", args=[shift.pk]),
        {"locked": "1"},
        follow=True,
    )

    shift.refresh_from_db()
    assert response.status_code == 200
    assert shift.locked

    client.post(
        reverse("projects:lock_volunteer_shift", args=[shift.pk]),
        {"locked": "0"},
        follow=True,
    )

    shift.refresh_from_db()
    assert not shift.locked


@pytest.mark.django_db
def test_assignment_status_appears_in_my_events(client) -> None:
    call_command("seed_demo")
    volunteer = _allow_user("claimant@gmail.com", roles=[Role.VOLUNTEER.value])
    project = Project.objects.get(slug="awoostria-2026")
    shift = _placed_shift(
        project=project,
        title="Visible Status Door Watch",
        starts_at="2026-07-22T20:00:00+02:00",
        ends_at="2026-07-22T22:00:00+02:00",
    )
    VolunteerShiftAssignment.objects.create(
        shift=shift,
        user=volunteer,
        status=AssignmentStatus.CONFIRMED.value,
    )
    client.post(reverse("accounts:login"), {"email": volunteer.email})

    response = client.get(reverse("accounts:my_events"))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Visible Status Door Watch" in content
    assert "confirmed" in content


def _placed_shift(
    *,
    project: Project,
    title: str,
    starts_at: str,
    ends_at: str,
    needed_volunteers: int = 2,
) -> VolunteerShift:
    room = Room.objects.get(hotel__project=project, name="Main Stage")
    shift = VolunteerShift.objects.create(
        project=project,
        title=title,
        role="Stage Door",
        needed_volunteers=needed_volunteers,
    )
    VolunteerShiftPlacement.objects.create(
        shift=shift,
        room=room,
        starts_at=starts_at,
        ends_at=ends_at,
    )
    return shift


def _allow_user(email: str, *, roles: list[str] | None = None):
    grant, _ = AccessGrant.objects.get_or_create(email=email)
    role_values = roles or [Role.REGISTERED_USER.value]
    for role in role_values:
        AccessRole.objects.get_or_create(grant=grant, role=role)
    user_model = get_user_model()
    user, _ = user_model.objects.get_or_create(
        username=email, defaults={"email": email}
    )
    return user
