from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from maru.accounts.access_config import ensure_default_access_configuration
from maru.accounts.models import (
    AccessGrant,
    AccessRole,
    UserProfile,
    VolunteerGroup,
    VolunteerMembership,
)
from maru.domain import Role, seeded_accounts

SEEDED_VOLUNTEER_GROUPS = (
    ("Board", "board", "Highest-level convention leadership."),
    ("Chairman", "chairman", "Board chair and final escalation point."),
    ("Deputy Chairman", "deputy-chairman", "Deputy board leadership."),
    ("Secretary", "secretary", "Board documentation and administrative records."),
    ("Finance", "finance", "Budget, cashflow, and finance approvals."),
    ("Helper Board", "helper-board", "Volunteer leadership and helper coordination."),
    ("Orga", "orga", "Core convention organization teams."),
    ("Crew", "crew", "On-site operational crew teams."),
    ("Helpers", "helpers", "General helper pool."),
    ("Attendees", "attendees", "Registered event attendees."),
    ("Events", "events", "Event programming and schedule coordination."),
    ("Story", "story", "Narrative, theme, and story content."),
    ("Art", "art", "Art direction and illustration work."),
    ("Design", "design", "Visual design and layout work."),
    ("Decorations", "decorations", "Venue decoration planning and execution."),
    ("Security", "security", "Safety, security, and incident response."),
    ("HR", "hr", "People operations and volunteer care."),
    ("Social Media", "social-media", "Public social media planning and posting."),
    ("Graphics", "graphics", "Production graphics and visual assets."),
    ("IT", "it", "Systems, tooling, and technical operations."),
    ("Maid Café", "maid-cafe", "Maid cafe program operations."),
    ("Stage Tech", "stage-tech", "Stage technical planning and operations."),
    ("Lights", "lights", "Lighting setup and show operation."),
    ("Audio", "audio", "Audio setup and show operation."),
    ("Video", "video", "Video capture, playback, and streaming."),
    ("Logistics", "logistics", "Transport, storage, and material flow."),
    ("Front Desk", "front-desk", "Front desk and information desk operations."),
    ("ConOps", "conops", "Convention operations control."),
    ("Dealers' Den", "dealers-den", "Dealer room planning and support."),
    ("Charity", "charity", "Charity programming and fundraising."),
    ("Party", "party", "Party and dance event coordination."),
    ("Fursuit Support", "fursuit-support", "Fursuiter spaces and support operations."),
    ("Registration", "registration", "Registration and check-in operations."),
    ("PEER", "peer", "Peer support and attendee care."),
)

SEEDED_VOLUNTEER_PARENTS = {
    "chairman": ["board"],
    "deputy-chairman": ["board"],
    "secretary": ["board"],
    "finance": ["board"],
    "helper-board": ["board"],
    "orga": ["board"],
    "crew": ["orga"],
    "helpers": ["helper-board", "crew"],
    "attendees": ["helpers"],
    "events": ["orga"],
    "story": ["orga"],
    "art": ["orga"],
    "design": ["orga"],
    "decorations": ["orga"],
    "security": ["orga"],
    "hr": ["orga"],
    "social-media": ["orga"],
    "graphics": ["orga"],
    "it": ["orga"],
    "maid-cafe": ["orga"],
    "stage-tech": ["orga"],
    "lights": ["stage-tech", "crew"],
    "audio": ["stage-tech", "crew"],
    "video": ["stage-tech", "crew"],
    "logistics": ["orga", "crew"],
    "front-desk": ["orga", "crew"],
    "conops": ["orga", "crew"],
    "dealers-den": ["orga"],
    "charity": ["orga"],
    "party": ["orga", "crew"],
    "fursuit-support": ["orga", "helpers"],
    "registration": ["orga", "crew"],
    "peer": ["orga", "helpers"],
}

MULTI_LEAD_GROUPS = {
    "conops",
    "events",
    "it",
    "registration",
    "stage-tech",
}
MULTI_DEPUTY_GROUPS = {
    "events",
    "front-desk",
    "helpers",
    "logistics",
    "security",
}

SEEDED_VOLUNTEER_USERS = (
    {
        "display_name": "Chairman Test",
        "email": "board.chairman@gmail.com",
        "memberships": [
            (
                "board",
                VolunteerMembership.Role.LEAD,
                "Board Chair",
                "Owns final board decisions and organization-wide escalation.",
            ),
            (
                "chairman",
                VolunteerMembership.Role.LEAD,
                "Chairman",
                "Coordinates the chair office and final approvals.",
            ),
            (
                "orga",
                VolunteerMembership.Role.LEAD,
                "Orga Steering Lead",
                "Keeps core organizing departments aligned.",
            ),
        ],
        "roles": [Role.BOARD.value],
    },
    {
        "display_name": "Deputy Chairman Test",
        "email": "board.deputy@gmail.com",
        "memberships": [
            (
                "board",
                VolunteerMembership.Role.DEPUTY,
                "Deputy Board Chair",
                "Backs up the chair and handles delegated board decisions.",
            ),
            (
                "deputy-chairman",
                VolunteerMembership.Role.LEAD,
                "Deputy Chairman",
                "Leads deputy chair coordination.",
            ),
            (
                "helper-board",
                VolunteerMembership.Role.LEAD,
                "Helper Board Lead",
                "Owns helper leadership and volunteer escalation.",
            ),
        ],
        "roles": [Role.BOARD.value, Role.VOLUNTEER.value],
    },
    {
        "display_name": "Lead Tester",
        "email": "volunteer.lead@gmail.com",
        "memberships": [
            (
                "it",
                VolunteerMembership.Role.LEAD,
                "Systems Lead",
                "Owns production systems and incident handoff.",
            ),
            (
                "logistics",
                VolunteerMembership.Role.LEAD,
                "Logistics Lead",
                "Coordinates transport, storage, and venue material flow.",
            ),
            (
                "conops",
                VolunteerMembership.Role.DEPUTY,
                "ConOps Deputy",
                "Keeps the operations desk covered during lead handoffs.",
            ),
        ],
        "roles": [Role.EVENT_MANAGER.value, Role.VOLUNTEER.value],
    },
    {
        "display_name": "Deputy Tester",
        "email": "volunteer.deputy@gmail.com",
        "memberships": [
            (
                "front-desk",
                VolunteerMembership.Role.DEPUTY,
                "Front Desk Deputy",
                "Supports shift leads and handles information desk handoffs.",
            ),
            (
                "registration",
                VolunteerMembership.Role.DEPUTY,
                "Registration Deputy",
                "Backs up check-in operations and badge issue escalation.",
            ),
            (
                "it",
                VolunteerMembership.Role.DEPUTY,
                "IT Deputy",
                "Handles routine technical requests when the lead is unavailable.",
            ),
        ],
        "roles": [Role.VOLUNTEER.value],
    },
    {
        "display_name": "Helper Tester",
        "email": "volunteer.helper@gmail.com",
        "memberships": [
            (
                "helpers",
                VolunteerMembership.Role.VOLUNTEER,
                "General Helper",
                "Covers flexible helper tasks assigned by the helper board.",
            ),
            (
                "front-desk",
                VolunteerMembership.Role.VOLUNTEER,
                "Front Desk Helper",
                "Answers attendee questions and escalates issues.",
            ),
            (
                "registration",
                VolunteerMembership.Role.VOLUNTEER,
                "Registration Helper",
                "Supports check-in queue flow and badge pickup.",
            ),
        ],
        "roles": [Role.REGISTERED_USER.value, Role.VOLUNTEER.value],
    },
)


class Command(BaseCommand):
    help = "Seed baseline maru access accounts and roles."

    @transaction.atomic
    def handle(self, *args, **options):
        ensure_default_access_configuration()
        for account in seeded_accounts():
            grant, _ = AccessGrant.objects.update_or_create(
                email=account.email, defaults={"active": account.active}
            )
            for role in account.roles:
                AccessRole.objects.get_or_create(grant=grant, role=role.value)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Seeded {grant.email} with roles: "
                    f"{', '.join(sorted(role.value for role in account.roles))}"
                )
            )
        groups = _seed_volunteer_groups()
        seeded_user_count = _seed_volunteer_users(groups)
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(groups)} volunteer groups and "
                f"{seeded_user_count} volunteer test accounts."
            )
        )


def _seed_volunteer_groups() -> dict[str, VolunteerGroup]:
    groups = {}
    for title, slug, description in SEEDED_VOLUNTEER_GROUPS:
        group, _ = VolunteerGroup.objects.update_or_create(
            slug=slug,
            defaults={"description": description, "title": title},
        )
        groups[slug] = group
    for slug, parent_slugs in SEEDED_VOLUNTEER_PARENTS.items():
        groups[slug].parents.set(groups[parent_slug] for parent_slug in parent_slugs)
    return groups


def _seed_volunteer_users(groups: dict[str, VolunteerGroup]) -> int:
    accounts = [*SEEDED_VOLUNTEER_USERS, *_department_membership_accounts()]
    for account in accounts:
        user = _get_or_create_seed_user(account["email"], account["display_name"])
        _ensure_registered_access(account["email"], account["roles"])
        for membership in account["memberships"]:
            group_slug, defaults = _membership_defaults(membership)
            VolunteerMembership.objects.update_or_create(
                group=groups[group_slug],
                user=user,
                defaults=defaults,
            )
    return len(accounts)


def _department_membership_accounts() -> list[dict]:
    accounts = []
    for title, slug, _description in SEEDED_VOLUNTEER_GROUPS:
        for level in (
            VolunteerMembership.Role.LEAD,
            VolunteerMembership.Role.DEPUTY,
            VolunteerMembership.Role.VOLUNTEER,
        ):
            accounts.append(_department_account(title, slug, level))
        if slug in MULTI_LEAD_GROUPS:
            accounts.append(
                _department_account(title, slug, VolunteerMembership.Role.LEAD, 2)
            )
        if slug in MULTI_DEPUTY_GROUPS:
            accounts.append(
                _department_account(title, slug, VolunteerMembership.Role.DEPUTY, 2)
            )
    return accounts


def _department_account(
    title: str,
    slug: str,
    level: VolunteerMembership.Role,
    index: int = 1,
) -> dict:
    level_key = level.lower().replace(" ", ".")
    slug_key = slug.replace("-", ".")
    suffix = "" if index == 1 else f".{index}"
    return {
        "display_name": _department_display_name(title, level, index),
        "email": f"volunteer.{slug_key}.{level_key}{suffix}@gmail.com",
        "memberships": [
            (
                slug,
                level,
                _department_custom_title(title, slug, level, index),
                _department_responsibilities(title, slug, level, index),
            )
        ],
        "roles": _department_access_roles(level),
    }


def _department_display_name(
    title: str,
    level: VolunteerMembership.Role,
    index: int,
) -> str:
    extra = f" {index}" if index > 1 else ""
    return f"{title} {level} Test{extra}"


def _department_custom_title(
    title: str,
    slug: str,
    level: VolunteerMembership.Role,
    index: int,
) -> str:
    if slug == "events" and level == VolunteerMembership.Role.LEAD and index == 1:
        return "Generalist Lead"
    if index > 1:
        return f"Second {title} {level}"
    return f"{title} {level}"


def _department_responsibilities(
    title: str,
    slug: str,
    level: VolunteerMembership.Role,
    index: int,
) -> str:
    if slug == "events" and level == VolunteerMembership.Role.LEAD and index == 1:
        return "Coordinates cross-event coverage and general event team priorities."
    if level == VolunteerMembership.Role.LEAD:
        return f"Owns {title} planning, priorities, and final shift decisions."
    if level == VolunteerMembership.Role.DEPUTY:
        return f"Backs up {title} leads and keeps handoffs moving."
    return f"Supports {title} tasks during assigned shifts."


def _department_access_roles(level: VolunteerMembership.Role) -> list[str]:
    if level == VolunteerMembership.Role.LEAD:
        return [Role.EVENT_MANAGER.value, Role.VOLUNTEER.value]
    return [Role.REGISTERED_USER.value, Role.VOLUNTEER.value]


def _membership_defaults(membership: tuple) -> tuple[str, dict]:
    group_slug, role, custom_title, responsibilities = membership
    return group_slug, {
        "custom_title": custom_title,
        "responsibilities": responsibilities,
        "role": role,
    }


def _get_or_create_seed_user(email: str, display_name: str):
    user_model = get_user_model()
    user, created = user_model.objects.get_or_create(
        username=email,
        defaults={"email": email},
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    elif user.email != email:
        user.email = email
        user.save(update_fields=["email"])
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.display_name = display_name
    profile.profile_unlocked = True
    profile.show_profile_publicly = True
    profile.save(
        update_fields=[
            "display_name",
            "profile_unlocked",
            "show_profile_publicly",
        ]
    )
    return user


def _ensure_registered_access(email: str, roles: list[str]) -> None:
    grant, _ = AccessGrant.objects.update_or_create(
        email=email,
        defaults={"active": True, "notes": "Volunteer hierarchy test account."},
    )
    for role in roles:
        AccessRole.objects.get_or_create(grant=grant, role=role)
