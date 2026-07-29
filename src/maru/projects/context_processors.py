from __future__ import annotations

from django.utils import timezone

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

SIDEBAR_ARCHIVE_PROJECT_SESSION_KEY = "maru_sidebar_archive_project_slug"
SIDEBAR_PROJECT_SESSION_KEY = "maru_sidebar_project_slug"


def review_permissions(request):
    current_archive_project = None
    current_user_profile = None
    current_sidebar_project = None
    archived_sidebar_projects = []
    sidebar_projects = []
    if request.user.is_authenticated:
        current_user_profile = UserProfile.objects.filter(user=request.user).first()
        now = timezone.now()
        sidebar_projects = Project.objects.filter(closes_at__gt=now).order_by(
            "opens_at", "name"
        )
        archived_sidebar_projects = Project.objects.filter(closes_at__lte=now).order_by(
            "-closes_at", "name"
        )
        current_archive_project = _current_archive_project(request)
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
        "archived_sidebar_projects": archived_sidebar_projects,
        "current_archive_project": current_archive_project,
        "current_sidebar_project": current_sidebar_project,
        "current_user_profile": current_user_profile,
        "sidebar_projects": sidebar_projects,
        "ui_labels": label_map(current_sidebar_project),
    }


def _current_sidebar_project(request):
    if _current_archive_project(request):
        return None
    resolver_match = getattr(request, "resolver_match", None)
    kwargs = resolver_match.kwargs if resolver_match else {}
    slug = kwargs.get("slug") or kwargs.get("project_slug")
    if not slug:
        return _session_sidebar_project(request)
    project = Project.objects.filter(slug=slug, closes_at__gt=timezone.now()).first()
    if project:
        request.session.pop(SIDEBAR_ARCHIVE_PROJECT_SESSION_KEY, None)
        request.session[SIDEBAR_PROJECT_SESSION_KEY] = project.slug
        return project
    return _session_sidebar_project(request)


def _session_sidebar_project(request):
    slug = request.session.get(SIDEBAR_PROJECT_SESSION_KEY)
    if not slug:
        return None
    project = Project.objects.filter(slug=slug, closes_at__gt=timezone.now()).first()
    if not project:
        request.session.pop(SIDEBAR_PROJECT_SESSION_KEY, None)
        return None
    return project


def _current_archive_project(request):
    resolver_match = getattr(request, "resolver_match", None)
    if not resolver_match:
        return None
    slug = resolver_match.kwargs.get("slug")
    if not slug:
        return _session_archive_project(request)
    if not _is_archive_route(request) and resolver_match.view_name != "projects:detail":
        return None
    project = Project.objects.filter(slug=slug, closes_at__lte=timezone.now()).first()
    if project:
        request.session.pop(SIDEBAR_PROJECT_SESSION_KEY, None)
        request.session[SIDEBAR_ARCHIVE_PROJECT_SESSION_KEY] = project.slug
    return project


def _session_archive_project(request):
    slug = request.session.get(SIDEBAR_ARCHIVE_PROJECT_SESSION_KEY)
    if not slug:
        return None
    project = Project.objects.filter(slug=slug, closes_at__lte=timezone.now()).first()
    if not project:
        request.session.pop(SIDEBAR_ARCHIVE_PROJECT_SESSION_KEY, None)
        return None
    return project


def _is_archive_route(request) -> bool:
    resolver_match = getattr(request, "resolver_match", None)
    return bool(
        resolver_match
        and resolver_match.view_name
        and resolver_match.view_name.startswith("projects:archive")
    )
