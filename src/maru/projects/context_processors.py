from __future__ import annotations

from maru.projects.review import (
    can_claim_volunteer_shifts,
    can_manage_accounts,
    can_review_applications,
)


def review_permissions(request):
    return {
        "can_claim_volunteer_shifts": can_claim_volunteer_shifts(request.user),
        "can_manage_accounts": can_manage_accounts(request.user),
        "can_review_applications": can_review_applications(request.user),
    }
