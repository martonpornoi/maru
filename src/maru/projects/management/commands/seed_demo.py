from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_datetime

from maru.accounts.access_config import ensure_default_access_configuration
from maru.accounts.models import (
    AccessGrant,
    AccessRole,
    ArchivedParticipation,
    Notification,
    UserProfile,
)
from maru.domain import SEED_ACCESS_EMAIL, ApplicationStatus, AssignmentStatus, Role
from maru.project_import import ProjectImportError, load_project_yaml
from maru.projects.importer import ProjectSetupImportError, import_project_setup
from maru.projects.models import (
    Application,
    ApplicationVersion,
    EventGroup,
    Panel,
    Project,
    Room,
    TimetablePlacement,
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

DEMO_USERS = {
    "dance.helper@gmail.com": {
        "roles": [Role.REGISTERED_USER.value, Role.VOLUNTEER.value],
        "profile": {
            "display_name": "Dance Helper",
            "telegram": "@dancehelper",
            "discord": "dance.helper",
            "bio": "Backstage runner and dance competition helper.",
            "show_profile_publicly": True,
            "show_contact_handles": True,
        },
    },
    "stage.runner@gmail.com": {
        "roles": [Role.REGISTERED_USER.value, Role.VOLUNTEER.value],
        "profile": {
            "display_name": "Stage Runner",
            "telegram": "@stagerunner",
            "bio": "Stage door volunteer with a checklist.",
            "show_profile_publicly": True,
        },
    },
    "cooling.host@gmail.com": {
        "roles": [Role.REGISTERED_USER.value, Role.HOST.value],
        "profile": {
            "display_name": "Cooling Host",
            "fursuit_name": "Frostbyte",
            "telegram": "@frostbyte",
            "discord": "frostbyte.cool",
            "bio": "Runs practical fursuit cooling and headless-lounge panels.",
            "profile_picture": "",
            "fursuit_picture": "",
            "show_profile_publicly": True,
            "show_contact_handles": True,
            "show_fursuit_picture": True,
        },
    },
    "crafts.host@gmail.com": {
        "roles": [Role.REGISTERED_USER.value, Role.HOST.value],
        "profile": {
            "display_name": "Crafts Host",
            "fursuit_name": "Patchwork",
            "bio": "Teaches tiny repair tricks for busy convention weekends.",
            "profile_picture": "",
            "fursuit_picture": "",
            "show_profile_publicly": True,
            "show_fursuit_picture": True,
        },
    },
    "neon.dj@gmail.com": {
        "roles": [Role.REGISTERED_USER.value, Role.HOST.value],
        "profile": {
            "display_name": "DJ Neon Trail",
            "bio": "High-energy dance floor opener.",
            "show_profile_publicly": True,
        },
    },
    "lounge.host@gmail.com": {
        "roles": [Role.REGISTERED_USER.value, Role.HOST.value],
        "profile": {
            "display_name": "Lounge Host",
            "bio": "Keeps low-pressure social spaces moving.",
        },
    },
}

DEMO_SHIFTS = (
    {
        "title": "Registration Desk Morning Support",
        "role": "Check-in",
        "room": "Volunteer Office",
        "starts_at": "2026-07-22T10:00:00+02:00",
        "ends_at": "2026-07-22T13:00:00+02:00",
        "needed_volunteers": 2,
        "assignments": [
            {
                "email": "dance.helper@gmail.com",
                "status": AssignmentStatus.CONFIRMED.value,
                "notes": "Knows the registration checklist.",
            },
            {
                "email": "stage.runner@gmail.com",
                "status": AssignmentStatus.CLAIMED.value,
                "notes": "Can cover the first hour.",
            },
        ],
    },
    {
        "title": "Fursuit Lounge Water Run",
        "role": "Fursuit Support",
        "room": "Quiet Den",
        "starts_at": "2026-07-22T14:00:00+02:00",
        "ends_at": "2026-07-22T16:00:00+02:00",
        "needed_volunteers": 1,
        "assignments": [
            {
                "email": "stage.runner@gmail.com",
                "status": AssignmentStatus.CONFIRMED.value,
                "notes": "Bring water crates from the office.",
            }
        ],
    },
    {
        "title": "Dance Competition Backstage Check-in",
        "role": "Backstage",
        "room": "Main Stage",
        "starts_at": "2026-07-23T18:00:00+02:00",
        "ends_at": "2026-07-23T21:00:00+02:00",
        "needed_volunteers": 3,
        "assignments": [
            {
                "email": "dance.helper@gmail.com",
                "status": AssignmentStatus.CLAIMED.value,
                "notes": "Prefers backstage roles.",
            }
        ],
    },
    {
        "title": "Quiet Den Evening Reset",
        "role": "Room Reset",
        "room": "Quiet Den",
        "starts_at": "2026-07-24T20:00:00+02:00",
        "ends_at": "2026-07-24T21:00:00+02:00",
        "needed_volunteers": 2,
        "assignments": [],
    },
)

DEMO_PANELS = (
    {
        "email": "cooling.host@gmail.com",
        "title": "Fursuit Cooling 101",
        "subtitle": "Practical breaks, airflow, and safe pacing",
        "abstract": "A friendly survival guide for warm convention days.",
        "description": "Fans, hydration, room planning, and spotting early fatigue.",
        "duration": "60 minutes",
        "tags": ["Fursuiter-Friendly", "Chill"],
        "headcount": "M",
        "layout": ["Theater"],
        "tech": "Projector and one handheld microphone.",
        "needs": "Water station nearby.",
        "status": ApplicationStatus.APPROVED.value,
        "group": "Fursuit Wellness Track",
        "group_slug": "fursuit-wellness-track",
        "group_description": "Practical fursuit care and safety sessions.",
        "group_order": 1,
        "recurrence_label": "Day 1",
        "room": "Panel Room A",
        "starts_at": "2026-07-22T11:00:00+02:00",
        "ends_at": "2026-07-22T12:00:00+02:00",
    },
    {
        "email": "crafts.host@gmail.com",
        "title": "Emergency Plush and Paw Repairs",
        "subtitle": "Tiny fixes before the photoshoot",
        "abstract": "Needles, seams, glue choices, and calm triage.",
        "description": "A hands-on workshop for small costume and plush fixes.",
        "duration": "90 minutes",
        "tags": ["Creative Exchange"],
        "headcount": "S",
        "layout": ["Activity"],
        "tech": "Workshop tables and washable floor.",
        "needs": "Access to sink and spare paper towels.",
        "status": ApplicationStatus.APPROVED.value,
        "group": "Fursuit Wellness Track",
        "group_slug": "fursuit-wellness-track",
        "group_description": "Practical fursuit care and safety sessions.",
        "group_order": 2,
        "recurrence_label": "Day 2 repeat",
        "room": "Workshop Suite",
        "starts_at": "2026-07-23T13:00:00+02:00",
        "ends_at": "2026-07-23T14:30:00+02:00",
    },
    {
        "email": "neon.dj@gmail.com",
        "title": "Dance Floor Safety Briefing",
        "subtitle": "Fast orientation for performers and helpers",
        "abstract": "A short all-hands safety session before the dance block.",
        "description": "Covers stage access, water, exits, and backstage traffic.",
        "duration": "30 minutes",
        "tags": ["Core Event", "Lights Warning"],
        "headcount": "L",
        "layout": ["Theater"],
        "tech": "Main stage microphone.",
        "needs": "Security and dance leads present.",
        "status": ApplicationStatus.APPROVED.value,
        "room": "Main Stage",
        "starts_at": "2026-07-23T17:00:00+02:00",
        "ends_at": "2026-07-23T17:30:00+02:00",
    },
    {
        "email": "lounge.host@gmail.com",
        "title": "Late Night Board Game Lounge",
        "subtitle": "Low-pressure tabletop meetup",
        "abstract": "A calmer evening space for small groups.",
        "description": "Board games, quiet introductions, and flexible tables.",
        "duration": "120 minutes",
        "tags": ["Chill"],
        "headcount": "M",
        "layout": ["Cabaret"],
        "tech": "No AV needed.",
        "needs": "A few spare tables.",
        "status": ApplicationStatus.REOPENED.value,
    },
    {
        "email": "neon.dj@gmail.com",
        "title": "DJ Neon Trail Opening Set",
        "subtitle": "Dance floor warmup",
        "abstract": "A sample DJ application waiting for review.",
        "description": "Energetic dance opening with clean transitions.",
        "duration": "60 minutes",
        "tags": ["Core Event", "Lights Warning"],
        "headcount": "XXXL",
        "layout": ["Theater"],
        "tech": "DJ booth and main PA.",
        "needs": "Sound check slot.",
        "status": ApplicationStatus.SUBMITTED.value,
    },
)


class Command(BaseCommand):
    help = "Load educational demo data for local maru development."

    @transaction.atomic
    def handle(self, *args, **options):
        ensure_default_access_configuration()
        try:
            results = [
                import_project_setup(load_project_yaml(BASE_DIR / path))
                for path in DEMO_FILES
            ]
        except (OSError, ProjectImportError, ProjectSetupImportError) as exc:
            raise CommandError(str(exc)) from exc

        user = _get_or_create_demo_user()
        _create_archive_entries(user)
        demo_users = {
            email: _get_or_create_user(email, data["roles"], data.get("profile", {}))
            for email, data in DEMO_USERS.items()
        }
        _create_demo_applications_and_panels(demo_users)
        _create_demo_volunteer_shifts(demo_users, assigned_by=user)
        _create_demo_notifications({SEED_ACCESS_EMAIL: user, **demo_users})

        project_slugs = ", ".join(result.project.slug for result in results)
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded demo projects: {project_slugs}. "
                f"Demo account: {SEED_ACCESS_EMAIL}"
            )
        )


def _get_or_create_demo_user():
    return _get_or_create_user(
        SEED_ACCESS_EMAIL,
        [Role.ADMIN.value, Role.BOARD.value, Role.EVENT_MANAGER.value],
        {
            "display_name": "Maru Admin",
            "bio": "Demo administrator account for local testing.",
            "show_profile_publicly": True,
        },
    )


def _get_or_create_user(
    email: str,
    roles: list[str] | None = None,
    profile_data: dict | None = None,
):
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
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile_data = profile_data or {}
    if profile_data:
        for field, value in profile_data.items():
            setattr(profile, field, value)
        profile.profile_unlocked = True
        profile.save(update_fields=[*profile_data, "profile_unlocked"])
    _ensure_registered_access(email, roles or [Role.REGISTERED_USER.value])
    return user


def _create_archive_entries(user) -> None:
    for entry in ARCHIVE_ENTRIES:
        ArchivedParticipation.objects.get_or_create(user=user, **entry)


def _ensure_registered_access(email: str, roles: list[str]) -> None:
    grant, _ = AccessGrant.objects.update_or_create(
        email=email, defaults={"active": True}
    )
    for role in roles:
        AccessRole.objects.get_or_create(grant=grant, role=role)


def _create_demo_applications_and_panels(users: dict[str, object]) -> None:
    project = Project.objects.get(slug="awoostria-2026")
    subproject = project.subprojects.get(slug="events")
    for item in DEMO_PANELS:
        application, _ = Application.objects.update_or_create(
            subproject=subproject,
            applicant=users[item["email"]],
            title=item["title"],
            defaults={"status": item["status"]},
        )
        ApplicationVersion.objects.update_or_create(
            application=application,
            version=1,
            defaults={"answers": _panel_answers(item)},
        )
        if item["status"] != ApplicationStatus.APPROVED.value:
            continue
        event_group = None
        if item.get("group"):
            event_group, _ = EventGroup.objects.update_or_create(
                project=project,
                slug=item["group_slug"],
                defaults={
                    "description": item["group_description"],
                    "name": item["group"],
                    "requires_order": True,
                },
            )
        panel, _ = Panel.objects.update_or_create(
            application=application,
            defaults={
                "event_group": event_group,
                "group_order": item.get("group_order"),
                "owner": users[item["email"]],
                "project": project,
                "recurrence_label": item.get("recurrence_label", ""),
                "title": item["title"],
            },
        )
        room = Room.objects.get(hotel__projects=project, name=item["room"])
        TimetablePlacement.objects.update_or_create(
            panel=panel,
            defaults={
                "room": room,
                "room_combination": None,
                "starts_at": parse_datetime(item["starts_at"]),
                "ends_at": parse_datetime(item["ends_at"]),
            },
        )


def _panel_answers(item: dict) -> dict:
    return {
        "Display - Title": item["title"],
        "Display - Subtitle (optional)": item["subtitle"],
        "Display - Abstract": item["abstract"],
        "Display - Description": item["description"],
        "Display - Duration": item["duration"],
        "Display - Tags": item["tags"],
        "Mapping - Estimated Headcount": item["headcount"],
        "Mapping - Room Layout": item["layout"],
        "Mapping - Technical Description": item["tech"],
        "Mapping - Things you would need from us": item["needs"],
    }


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
        room = Room.objects.get(hotel__projects=project, name=item["room"])
        VolunteerShiftPlacement.objects.update_or_create(
            shift=shift,
            defaults={
                "room": room,
                "room_combination": None,
                "starts_at": parse_datetime(item["starts_at"]),
                "ends_at": parse_datetime(item["ends_at"]),
            },
        )
        for assignment in item["assignments"]:
            VolunteerShiftAssignment.objects.update_or_create(
                shift=shift,
                user=volunteers[assignment["email"]],
                defaults={
                    "assigned_by": assigned_by,
                    "notes": assignment["notes"],
                    "status": assignment["status"],
                },
            )


def _create_demo_notifications(users: dict[str, object]) -> None:
    notifications = (
        {
            "email": "cooling.host@gmail.com",
            "title": "Panel scheduled",
            "body": "Fursuit Cooling 101 is placed in Panel Room A.",
            "link_url": "/projects/awoostria-2026/timetable/",
            "link_label": "Open timetable",
        },
        {
            "email": "dance.helper@gmail.com",
            "title": "Volunteer shift confirmed",
            "body": "Registration Desk Morning Support is confirmed.",
            "link_url": "/projects/awoostria-2026/volunteer-shifts/",
            "link_label": "Open shifts",
        },
        {
            "email": SEED_ACCESS_EMAIL,
            "title": "Demo data loaded",
            "body": (
                "The demo now includes hosts, panels, shifts, profiles, "
                "and notifications."
            ),
            "link_url": "/projects/awoostria-2026/",
            "link_label": "Open project",
        },
    )
    for item in notifications:
        Notification.objects.get_or_create(
            user=users[item["email"]],
            title=item["title"],
            defaults={
                "body": item["body"],
                "link_label": item["link_label"],
                "link_url": item["link_url"],
            },
        )
