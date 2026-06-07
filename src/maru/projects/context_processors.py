from __future__ import annotations

from maru.accounts.models import UserProfile
from maru.accounts.permissions import has_permission, label_map
from maru.domain import PermissionKey
from maru.projects.models import Project
from maru.projects.review import (
    can_claim_volunteer_shifts,
    can_manage_accounts,
    can_manage_project_setup,
    can_review_applications,
)


def review_permissions(request):
    current_user_profile = None
    current_sidebar_project = None
    sidebar_projects = []
    if request.user.is_authenticated:
        current_user_profile = UserProfile.objects.filter(user=request.user).first()
        sidebar_projects = Project.objects.order_by("opens_at", "name")
        current_sidebar_project = _current_sidebar_project(request)
    can_open_setup = can_manage_project_setup(request.user)
    if request.user.is_authenticated and current_sidebar_project:
        can_open_setup = can_open_setup or any(
            has_permission(request.user, permission, current_sidebar_project)
            for permission in (
                PermissionKey.PROJECT_FORMS_MANAGE,
                PermissionKey.PROJECT_LABELS_MANAGE,
                PermissionKey.PROJECT_ROLES_MANAGE,
                PermissionKey.PROJECT_STATUSES_MANAGE,
            )
        )
    return {
        "can_claim_volunteer_shifts": can_claim_volunteer_shifts(request.user),
        "can_manage_accounts": can_manage_accounts(request.user),
        "can_manage_project_setup": can_manage_project_setup(request.user),
        "can_open_setup": can_open_setup,
        "can_review_applications": can_review_applications(request.user),
        "current_sidebar_project": current_sidebar_project,
        "current_user_profile": current_user_profile,
        "sidebar_projects": sidebar_projects,
        "ui_labels": label_map(current_sidebar_project),
    }


def _current_sidebar_project(request):
    resolver_match = getattr(request, "resolver_match", None)
    if not resolver_match:
        return None
    kwargs = resolver_match.kwargs
    slug = kwargs.get("slug") or kwargs.get("project_slug")
    if not slug:
        return None
    return Project.objects.filter(slug=slug).first()
