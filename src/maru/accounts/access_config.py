from __future__ import annotations

from collections.abc import Iterable

from django.db import transaction

from maru.domain import BenefitTarget, FursuiterStatus, PermissionKey, Role, TicketLevel

PROJECT_PERMISSION_VALUES = [
    PermissionKey.PROJECTS_CREATE.value,
    PermissionKey.PROJECT_SETUP_MANAGE.value,
    PermissionKey.PROJECT_ROLES_MANAGE.value,
    PermissionKey.PROJECT_ROLES_ASSIGN.value,
    PermissionKey.PROJECT_LABELS_MANAGE.value,
    PermissionKey.PROJECT_FORMS_MANAGE.value,
    PermissionKey.PROJECT_APPLICATIONS_REVIEW.value,
    PermissionKey.PROJECT_TIMETABLE_MANAGE.value,
    PermissionKey.PROJECT_VOLUNTEERS_MANAGE.value,
    PermissionKey.PROJECT_SPACES_MANAGE.value,
    PermissionKey.PROJECT_STATUSES_MANAGE.value,
    PermissionKey.PROJECT_FURSUITERS_VALIDATE.value,
    PermissionKey.PROJECT_REGISTRATION_MANAGE.value,
    PermissionKey.PROJECT_EXPORTS_MANAGE.value,
    PermissionKey.PROJECT_SOCIAL_MANAGE.value,
    PermissionKey.PROJECT_SIGNAGE_MANAGE.value,
    PermissionKey.PROFILES_PRIVATE_VIEW.value,
]

FULL_PERMISSION_VALUES = [
    PermissionKey.ACCOUNTS_MANAGE.value,
    *PROJECT_PERMISSION_VALUES,
]

DEFAULT_ROLE_PRESETS = [
    {
        "key": "admin",
        "name": Role.ADMIN.value,
        "description": "Technical and account-level owner.",
        "permissions": FULL_PERMISSION_VALUES,
    },
    {
        "key": "board",
        "name": Role.BOARD.value,
        "description": "Full project owner without login allowlist management.",
        "permissions": PROJECT_PERMISSION_VALUES,
    },
    {
        "key": "project-lead",
        "name": "Project Lead",
        "description": "Day-to-day owner for one convention project.",
        "permissions": PROJECT_PERMISSION_VALUES,
    },
    {
        "key": "department-lead",
        "name": "Department Lead",
        "description": "Lead for a scoped convention department.",
        "permissions": [
            PermissionKey.PROJECT_ROLES_ASSIGN.value,
            PermissionKey.PROJECT_FORMS_MANAGE.value,
            PermissionKey.PROJECT_APPLICATIONS_REVIEW.value,
            PermissionKey.PROJECT_TIMETABLE_MANAGE.value,
            PermissionKey.PROJECT_VOLUNTEERS_MANAGE.value,
            PermissionKey.PROJECT_SPACES_MANAGE.value,
            PermissionKey.PROFILES_PRIVATE_VIEW.value,
        ],
    },
    {
        "key": "registration",
        "name": "Registration",
        "description": "Ticket, check-in, and attendee status handling.",
        "permissions": [
            PermissionKey.PROJECT_REGISTRATION_MANAGE.value,
            PermissionKey.PROJECT_STATUSES_MANAGE.value,
            PermissionKey.PROFILES_PRIVATE_VIEW.value,
        ],
    },
    {
        "key": "volunteer-coordinator",
        "name": "Volunteer Coordinator",
        "description": "Volunteer shift and staffing coordination.",
        "permissions": [
            PermissionKey.PROJECT_VOLUNTEERS_MANAGE.value,
            PermissionKey.PROFILES_PRIVATE_VIEW.value,
        ],
    },
    {
        "key": "scheduler",
        "name": "Scheduler",
        "description": "Timetable and placement coordination.",
        "permissions": [
            PermissionKey.PROJECT_TIMETABLE_MANAGE.value,
            PermissionKey.PROJECT_APPLICATIONS_REVIEW.value,
        ],
    },
    {
        "key": "security",
        "name": Role.SECURITY.value,
        "description": "Security operations and private profile visibility.",
        "permissions": [
            PermissionKey.PROJECT_SPACES_MANAGE.value,
            PermissionKey.PROFILES_PRIVATE_VIEW.value,
        ],
    },
    {
        "key": "fursuit-support",
        "name": Role.FURSUIT_SUPPORT.value,
        "description": "Fursuiter validation and lounge access handling.",
        "permissions": [
            PermissionKey.PROJECT_FURSUITERS_VALIDATE.value,
            PermissionKey.PROJECT_SPACES_MANAGE.value,
            PermissionKey.PROFILES_PRIVATE_VIEW.value,
        ],
    },
    {
        "key": "theming",
        "name": Role.THEMEING.value,
        "description": "Theme and signage support.",
        "permissions": [
            PermissionKey.PROJECT_SIGNAGE_MANAGE.value,
            PermissionKey.PROJECT_SPACES_MANAGE.value,
        ],
    },
    {
        "key": "social-media",
        "name": "Social Media",
        "description": "Public social post publishing.",
        "permissions": [PermissionKey.PROJECT_SOCIAL_MANAGE.value],
    },
    {
        "key": "host",
        "name": Role.HOST.value,
        "description": "Approved host without staff authority.",
        "permissions": [],
    },
]

DEFAULT_BENEFITS = [
    {
        "key": "fursuit-lounge",
        "label": "Fursuit Lounge Access",
        "target": BenefitTarget.SPACE_ACCESS.value,
        "description": "Access to spaces reserved for validated fursuiters.",
    },
    {
        "key": "sponsor-gifts",
        "label": "Sponsor Gifts",
        "target": BenefitTarget.CHECK_IN.value,
        "description": "Check-in reminder for sponsor-tier gifts.",
    },
    {
        "key": "super-sponsor-gifts",
        "label": "Super Sponsor Gifts",
        "target": BenefitTarget.CHECK_IN.value,
        "description": "Check-in reminder for super sponsor gifts.",
    },
    {
        "key": "priority-check-in",
        "label": "Priority Check-In",
        "target": BenefitTarget.CHECK_IN.value,
        "description": "Can use priority registration lines.",
    },
    {
        "key": "early-access",
        "label": "Early Access",
        "target": BenefitTarget.EXPORT.value,
        "description": "Eligible for project-defined early access windows.",
    },
]

DEFAULT_STATUS_BENEFIT_GRANTS = [
    (TicketLevel.SPONSOR.value, "sponsor-gifts"),
    (TicketLevel.SPONSOR.value, "priority-check-in"),
    (TicketLevel.SUPER_SPONSOR.value, "sponsor-gifts"),
    (TicketLevel.SUPER_SPONSOR.value, "super-sponsor-gifts"),
    (TicketLevel.SUPER_SPONSOR.value, "priority-check-in"),
    (TicketLevel.SUPER_SPONSOR.value, "early-access"),
    (TicketLevel.INFINITY.value, "sponsor-gifts"),
    (TicketLevel.INFINITY.value, "super-sponsor-gifts"),
    (TicketLevel.INFINITY.value, "priority-check-in"),
    (TicketLevel.INFINITY.value, "early-access"),
]

DEFAULT_LABELS = {
    "menu.projects": "Projects",
    "menu.users": "Users",
    "menu.social_media": "Social Media",
    "menu.statistics": "Statistics",
    "menu.forms": "Forms",
    "menu.staff": "Staff",
    "menu.application_review": "Application Review",
    "menu.setup": "Setup",
    "menu.hotels": "Hotels",
    "menu.con_spaces": "Con Spaces",
    "menu.color_codes": "Color Codes",
    "menu.roles_access": "Roles & Access",
    "menu.statuses_benefits": "Statuses & Benefits",
    "menu.labels": "Labels",
    "status.ticket.pending": "Pending",
    "status.ticket.paid": "Paid",
    "status.ticket.sponsor": "Sponsor",
    "status.ticket.super_sponsor": "Super Sponsor",
    "status.ticket.infinity": "Infinity",
    "status.fursuiter.not_requested": "Not requested",
    "status.fursuiter.pending": "Pending validation",
    "status.fursuiter.approved": "Approved",
    "status.fursuiter.rejected": "Rejected",
}


@transaction.atomic
def ensure_default_access_configuration() -> None:
    from maru.accounts.models import (
        AccessBenefit,
        LabelOverride,
        RoleDefinition,
        StatusBenefitGrant,
    )

    for preset in DEFAULT_ROLE_PRESETS:
        RoleDefinition.objects.update_or_create(
            project=None,
            key=preset["key"],
            defaults={
                "name": preset["name"],
                "description": preset["description"],
                "permissions": list(preset["permissions"]),
                "active": True,
                "system_default": True,
            },
        )

    benefit_by_key = {}
    for benefit in DEFAULT_BENEFITS:
        benefit_obj, _ = AccessBenefit.objects.update_or_create(
            project=None,
            key=benefit["key"],
            defaults={
                "active": True,
                "description": benefit["description"],
                "label": benefit["label"],
                "target": benefit["target"],
            },
        )
        benefit_by_key[benefit_obj.key] = benefit_obj

    for ticket_level, benefit_key in DEFAULT_STATUS_BENEFIT_GRANTS:
        StatusBenefitGrant.objects.get_or_create(
            project=None,
            status_type=StatusBenefitGrant.TICKET_LEVEL,
            status_value=ticket_level,
            benefit=benefit_by_key[benefit_key],
        )
    StatusBenefitGrant.objects.get_or_create(
        project=None,
        status_type=StatusBenefitGrant.FURSUITER_STATUS,
        status_value=FursuiterStatus.APPROVED.value,
        benefit=benefit_by_key["fursuit-lounge"],
    )

    for key, label in DEFAULT_LABELS.items():
        LabelOverride.objects.update_or_create(
            project=None,
            key=key.replace(".", "-").replace("_", "-"),
            defaults={"label": label},
        )


@transaction.atomic
def clone_access_configuration_to_project(
    *,
    project,
    source_project=None,
    actor=None,
) -> None:
    from maru.accounts.models import (
        AccessBenefit,
        AccessConfigurationAuditLog,
        LabelOverride,
        RoleDefinition,
        StatusBenefitGrant,
    )

    ensure_default_access_configuration()
    source_roles = RoleDefinition.objects.filter(project=source_project)
    source_benefits = AccessBenefit.objects.filter(project=source_project)
    source_labels = LabelOverride.objects.filter(project=source_project)
    source_grants = StatusBenefitGrant.objects.filter(project=source_project)

    role_lookup = {}
    for role in source_roles:
        clone, _ = RoleDefinition.objects.update_or_create(
            project=project,
            key=role.key,
            defaults={
                "active": role.active,
                "cloned_from": role,
                "description": role.description,
                "name": role.name,
                "permissions": list(role.permissions),
                "system_default": role.system_default,
            },
        )
        role_lookup[role.key] = clone

    benefit_lookup = {}
    for benefit in source_benefits:
        clone, _ = AccessBenefit.objects.update_or_create(
            project=project,
            key=benefit.key,
            defaults={
                "active": benefit.active,
                "cloned_from": benefit,
                "description": benefit.description,
                "label": benefit.label,
                "target": benefit.target,
            },
        )
        benefit_lookup[benefit.key] = clone

    for grant in source_grants.select_related("benefit"):
        benefit = benefit_lookup.get(grant.benefit.key)
        if not benefit:
            continue
        StatusBenefitGrant.objects.get_or_create(
            project=project,
            status_type=grant.status_type,
            status_value=grant.status_value,
            benefit=benefit,
        )

    for label in source_labels:
        LabelOverride.objects.update_or_create(
            project=project,
            key=label.key,
            defaults={"label": label.label},
        )

    AccessConfigurationAuditLog.objects.create(
        project=project,
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        actor_email=getattr(actor, "email", "") if actor else "",
        action="cloned",
        target_type="access_configuration",
        target_key=source_project.slug if source_project else "global",
        after={
            "benefits": sorted(benefit_lookup),
            "labels": sorted(label.key for label in source_labels),
            "roles": sorted(role_lookup),
        },
    )


def permission_choices() -> list[tuple[str, str]]:
    return [(permission.value, permission.value) for permission in PermissionKey]


def ticket_level_choices(*, include_blank: bool = False) -> list[tuple[str, str]]:
    choices = [(level.value, level.value) for level in TicketLevel]
    if include_blank:
        return [("", "Not verified"), *choices]
    return choices


def fursuiter_status_choices() -> list[tuple[str, str]]:
    return [(status.value, status.value) for status in FursuiterStatus]


def clean_permission_values(values: Iterable[str]) -> list[str]:
    valid = {permission.value for permission in PermissionKey}
    return sorted(value for value in set(values) if value in valid)
