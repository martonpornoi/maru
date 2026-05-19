from __future__ import annotations

from django.contrib.auth.models import AnonymousUser

from maru.accounts.models import AccessGrant
from maru.domain import Role


def can_manage_accounts(user) -> bool:
    if isinstance(user, AnonymousUser) or not user.is_authenticated:
        return False
    grant = AccessGrant.objects.filter(email=user.email, active=True).first()
    return bool(grant and Role.ADMIN.value in grant.role_names)


def can_review_applications(user) -> bool:
    if isinstance(user, AnonymousUser) or not user.is_authenticated:
        return False
    grant = AccessGrant.objects.filter(email=user.email, active=True).first()
    return bool(grant and grant.can_review_applications)


def can_claim_volunteer_shifts(user) -> bool:
    if isinstance(user, AnonymousUser) or not user.is_authenticated:
        return False
    grant = AccessGrant.objects.filter(email=user.email, active=True).first()
    if not grant:
        return False
    return grant.can_review_applications or Role.VOLUNTEER.value in grant.role_names
