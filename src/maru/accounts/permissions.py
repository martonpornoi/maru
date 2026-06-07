from __future__ import annotations

from django.contrib.auth.models import AnonymousUser

from maru.accounts.access_config import DEFAULT_LABELS
from maru.accounts.models import (
    AccessGrant,
    LabelOverride,
    RoleAssignment,
    StatusBenefitGrant,
    UserConventionProfile,
)
from maru.domain import FursuiterStatus, PermissionKey, Role, TicketLevel

LEGACY_EVENT_MANAGER_PERMISSIONS = {
    PermissionKey.PROJECT_APPLICATIONS_REVIEW.value,
    PermissionKey.PROJECT_SOCIAL_MANAGE.value,
    PermissionKey.PROJECT_SIGNAGE_MANAGE.value,
    PermissionKey.PROFILES_PRIVATE_VIEW.value,
}


def has_permission(user, permission: PermissionKey | str, project=None) -> bool:
    if isinstance(user, AnonymousUser) or not user.is_authenticated:
        return False
    permission_value = _permission_value(permission)
    grant = AccessGrant.objects.filter(email=user.email, active=True).first()
    if not grant:
        return False
    if _legacy_grant_has_permission(grant, permission_value):
        return True
    return _assigned_role_has_permission(user, permission_value, project)


def has_any_project_role(user, project) -> bool:
    if isinstance(user, AnonymousUser) or not user.is_authenticated:
        return False
    return RoleAssignment.objects.filter(
        project=project,
        role_definition__active=True,
        user=user,
    ).exists()


def label_for(key: str, project=None) -> str:
    normalized_key = normalize_label_key(key)
    if project:
        override = LabelOverride.objects.filter(
            project=project,
            key=normalized_key,
        ).first()
        if override:
            return override.label
    override = LabelOverride.objects.filter(project=None, key=normalized_key).first()
    if override:
        return override.label
    return DEFAULT_LABELS.get(key, key)


def label_map(project=None) -> dict[str, str]:
    labels: dict[str, str | dict] = {}
    for key in DEFAULT_LABELS:
        parts = key.split(".")
        target = labels
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = label_for(key, project=project)
    return labels


def normalize_label_key(key: str) -> str:
    return key.replace(".", "-").replace("_", "-")


def user_benefit_keys(user, project) -> list[str]:
    profile = UserConventionProfile.objects.filter(user=user, project=project).first()
    if not profile:
        return []
    status_filters = []
    if profile.ticket_level_verified:
        status_filters.append(
            {
                "status_type": StatusBenefitGrant.TICKET_LEVEL,
                "status_value": profile.ticket_level_verified,
            }
        )
    if profile.fursuiter_status == FursuiterStatus.APPROVED.value:
        status_filters.append(
            {
                "status_type": StatusBenefitGrant.FURSUITER_STATUS,
                "status_value": FursuiterStatus.APPROVED.value,
            }
        )
    benefit_keys = set()
    for status_filter in status_filters:
        grants = StatusBenefitGrant.objects.filter(project=project, **status_filter)
        if not grants.exists():
            grants = StatusBenefitGrant.objects.filter(project=None, **status_filter)
        benefit_keys.update(
            grant.benefit.key for grant in grants.select_related("benefit")
            if grant.benefit.active
        )
    return sorted(benefit_keys)


def can_set_verified_ticket_level(*, actor, current_level: str, new_level: str) -> bool:
    if current_level == new_level:
        return True
    if has_permission(actor, PermissionKey.ACCOUNTS_MANAGE):
        return True
    current_rank = _ticket_rank(current_level)
    new_rank = _ticket_rank(new_level)
    return new_rank >= current_rank


def _permission_value(permission: PermissionKey | str) -> str:
    return permission.value if isinstance(permission, PermissionKey) else permission


def _legacy_grant_has_permission(grant: AccessGrant, permission: str) -> bool:
    role_names = grant.role_names
    if permission == PermissionKey.ACCOUNTS_MANAGE.value:
        return Role.ADMIN.value in role_names
    if Role.ADMIN.value in role_names or Role.BOARD.value in role_names:
        return permission != PermissionKey.ACCOUNTS_MANAGE.value
    if Role.EVENT_MANAGER.value in role_names:
        return permission in LEGACY_EVENT_MANAGER_PERMISSIONS
    return False


def _assigned_role_has_permission(user, permission: str, project=None) -> bool:
    assignments = RoleAssignment.objects.filter(
        role_definition__active=True,
        user=user,
    ).select_related("role_definition")
    if project:
        assignments = assignments.filter(project=project)
    for assignment in assignments:
        if permission in set(assignment.role_definition.permissions or []):
            return True
    return False


def _ticket_rank(level: str) -> int:
    ranks = {
        "": -1,
        TicketLevel.PENDING.value: 0,
        TicketLevel.PAID.value: 1,
        TicketLevel.SPONSOR.value: 2,
        TicketLevel.SUPER_SPONSOR.value: 3,
        TicketLevel.INFINITY.value: 4,
    }
    return ranks.get(level, -1)
