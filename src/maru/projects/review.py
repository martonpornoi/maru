from __future__ import annotations

from django.contrib.auth.models import AnonymousUser

from maru.accounts.models import AccessGrant
from maru.accounts.permissions import has_permission
from maru.domain import PermissionKey, Role


def can_manage_accounts(user) -> bool:
    return has_permission(user, PermissionKey.ACCOUNTS_MANAGE)


def can_review_applications(user) -> bool:
    return has_permission(user, PermissionKey.PROJECT_APPLICATIONS_REVIEW)


def can_manage_project_setup(user) -> bool:
    return has_permission(user, PermissionKey.PROJECT_SETUP_MANAGE)


def can_claim_volunteer_shifts(user) -> bool:
    if isinstance(user, AnonymousUser) or not user.is_authenticated:
        return False
    grant = AccessGrant.objects.filter(email=user.email, active=True).first()
    if not grant:
        return False
    return (
        has_permission(user, PermissionKey.PROJECT_VOLUNTEERS_MANAGE)
        or has_permission(user, PermissionKey.PROJECT_APPLICATIONS_REVIEW)
        or Role.VOLUNTEER.value in grant.role_names
    )
