from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_datetime

from maru.accounts.models import (
    AccessGrant,
    AccessRole,
    ArchivedParticipation,
    UserProfile,
)
from maru.domain import SEED_ACCESS_EMAIL, AssignmentStatus, Role
from maru.project_import import ProjectImportError, load_project_yaml
from maru.projects.importer import ProjectSetupImportError, import_project_setup
from maru.projects.models import (
    Project,
    Room,
    VolunteerShift,
    VolunteerShiftAssignment,
    VolunteerShiftPlacement,
)
from maru.settings import BASE_DIR

DEMO_FILES = (
    "docs/demo/cozy-furcon-2025.yml",
    "docs/demo/awoostria-2026.yml",
    "docs/demo/neon-paws-2027.yml",
)

ARCHIVE_ENTRIES = (
    {
        "year": 2024,
        "project_name": "Awoostria 2024",
        "panel_title": "Fursuit Cooling and Headless Lounge Basics",
    },
    {
        "year": 2025,
        "project_name": "Cozy Furcon 2025",
        "panel_title": "Late Night Chillout Playlist Exchange",
    },
    {
        "year": 2025,
        "project_name": "Awoostria 2025",
        "panel_title": "Volunteer Radio Etiquette for Busy Hallways",
    },
)

DEMO_VOLUNTEERS = (
    "dance.helper@gmail.com",
    "stage.runner@gmail.com",
)

DEMO_SHIFTS = (
    {
        "title": "Registration Desk Morning Support",
        "role": "Check-in",
        "room": "Volunteer Office",
        "starts_at": "2026-07-22T10:00:00+02:00",
        "ends_at": "2026-07-22T13:00:00+02:00",
        "needed_volunteers": 2,
        "assignments": ["dance.helper@gmail.com"],
    },
    {
        "title": "Fursuit Lounge Water Run",
        "role": "Fursuit Support",
        "room": "Quiet Den",
        "starts_at": "2026-07-22T14:00:00+02:00",
        "ends_at": "2026-07-22T16:00:00+02:00",
        "needed_volunteers": 1,
        "assignments": ["stage.runner@gmail.com"],
    },
)


class Command(BaseCommand):
    help = "Load educational demo data for local maru development."

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            results = [
                import_project_setup(load_project_yaml(BASE_DIR / path))
                for path in DEMO_FILES
            ]
        except (OSError, ProjectImportError, ProjectSetupImportError) as exc:
            raise CommandError(str(exc)) from exc

        user = _get_or_create_demo_user()
        _create_archive_entries(user)
        volunteers = {email: _get_or_create_user(email) for email in DEMO_VOLUNTEERS}
        _create_demo_volunteer_shifts(volunteers, assigned_by=user)

        project_slugs = ", ".join(result.project.slug for result in results)
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded demo projects: {project_slugs}. "
                f"Demo account: {SEED_ACCESS_EMAIL}"
            )
        )


def _get_or_create_demo_user():
    return _get_or_create_user(SEED_ACCESS_EMAIL)


def _get_or_create_user(email: str):
    user_model = get_user_model()
    user, created = user_model.objects.get_or_create(
        username=email, defaults={"email": email}
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    elif user.email != email:
        user.email = email
        user.save(update_fields=["email"])
    UserProfile.objects.get_or_create(user=user)
    _ensure_registered_access(email)
    return user


def _create_archive_entries(user) -> None:
    for entry in ARCHIVE_ENTRIES:
        ArchivedParticipation.objects.get_or_create(user=user, **entry)


def _ensure_registered_access(email: str) -> None:
    grant, _ = AccessGrant.objects.update_or_create(
        email=email, defaults={"active": True}
    )
    AccessRole.objects.get_or_create(grant=grant, role=Role.REGISTERED_USER.value)
    if email in DEMO_VOLUNTEERS:
        AccessRole.objects.get_or_create(grant=grant, role=Role.VOLUNTEER.value)


def _create_demo_volunteer_shifts(volunteers: dict[str, object], assigned_by) -> None:
    project = Project.objects.get(slug="awoostria-2026")
    for item in DEMO_SHIFTS:
        shift, _ = VolunteerShift.objects.update_or_create(
            project=project,
            title=item["title"],
            defaults={
                "role": item["role"],
                "needed_volunteers": item["needed_volunteers"],
            },
        )
        room = Room.objects.get(hotel__project=project, name=item["room"])
        VolunteerShiftPlacement.objects.update_or_create(
            shift=shift,
            defaults={
                "room": room,
                "room_combination": None,
                "starts_at": parse_datetime(item["starts_at"]),
                "ends_at": parse_datetime(item["ends_at"]),
            },
        )
        for email in item["assignments"]:
            VolunteerShiftAssignment.objects.get_or_create(
                shift=shift,
                user=volunteers[email],
                defaults={
                    "assigned_by": assigned_by,
                    "status": AssignmentStatus.CONFIRMED.value,
                },
            )
