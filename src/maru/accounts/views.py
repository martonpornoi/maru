from __future__ import annotations

import csv
import io
import secrets

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from maru.accounts.access_config import (
    clone_access_configuration_to_project,
    ensure_default_access_configuration,
)
from maru.accounts.auth import (
    GoogleIdentity,
    GoogleOAuthError,
    build_google_authorization_url,
    exchange_google_code_for_identity,
    is_google_email,
    is_google_oauth_configured,
    normalize_email,
)
from maru.accounts.forms import (
    AccessBenefitForm,
    AccessGrantForm,
    AccessGrantImportForm,
    CloneAccessConfigurationForm,
    LabelOverrideForm,
    RoleAssignmentForm,
    RoleDefinitionForm,
    StatusBenefitGrantForm,
    UserConventionProfileForm,
    UserProfileForm,
    UserTileColorRuleForm,
)
from maru.accounts.models import (
    AccessBenefit,
    AccessConfigurationAuditLog,
    AccessGrant,
    AccessGrantAuditLog,
    AccessRole,
    ArchivedParticipation,
    LabelOverride,
    Notification,
    RoleAssignment,
    RoleDefinition,
    StatusBenefitGrant,
    UserConventionProfile,
    UserProfile,
    UserTileColorRule,
)
from maru.accounts.permissions import has_permission, user_benefit_keys
from maru.domain import (
    ApplicationStatus,
    FursuiterStatus,
    PermissionKey,
    Role,
    VolunteerType,
)
from maru.projects.models import Application, Project, VolunteerShiftAssignment
from maru.projects.review import (
    can_manage_accounts,
    can_manage_project_setup,
    can_review_applications,
)

ACTIVE_APPLICATION_STATUSES = {
    ApplicationStatus.DRAFT.value,
    ApplicationStatus.SUBMITTED.value,
    ApplicationStatus.REOPENED.value,
}

PROFILE_STATE_CHOICES = {
    "no_user": "No user yet",
    "locked": "Locked",
    "unlocked": "Unlocked",
}
AUDIT_LOGS_PER_PAGE = 25
DEFAULT_USER_TILE_BORDER_COLOR = "#d0d5dd"
DEFAULT_ATTENDEE_BORDER_COLORS = {
    "Attendee": "#98a2b3",
    "Sponsor": "#f97316",
    "Super Sponsor": "#eab308",
    "Fursuiter": "#6366f1",
}
DEFAULT_VOLUNTEER_TILE_STYLES = {
    "None": "background: #f4f7fb; color: #1f2937;",
    "Volunteer": "background: #e8f5ff; color: #17324d;",
    "Deputy": "background: #ecfdf5; color: #14532d;",
    "Lead": "background: #f5f3ff; color: #4c1d95;",
    "Board Member": "background: #fff7ed; color: #7c2d12;",
}


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect("accounts:my_profile")

    if request.method == "POST":
        if not _is_dev_login_enabled():
            messages.error(request, "Development email login is disabled.")
        elif _login_with_email(request, request.POST.get("email", "")):
            return redirect("accounts:my_profile")

    return render(
        request,
        "accounts/login.html",
        {
            "dev_login_enabled": _is_dev_login_enabled(),
            "google_oauth_configured": is_google_oauth_configured(),
        },
    )


def google_login_start_view(request):
    if request.user.is_authenticated:
        return redirect("accounts:my_profile")
    if not is_google_oauth_configured():
        messages.error(request, "Google OAuth is not configured yet.")
        return redirect("accounts:login")

    state = secrets.token_urlsafe(32)
    request.session["google_oauth_state"] = state
    return HttpResponseRedirect(build_google_authorization_url(request, state))


def google_oauth_callback_view(request):
    if request.user.is_authenticated:
        return redirect("accounts:my_profile")

    if request.GET.get("error"):
        messages.error(request, "Google sign-in was cancelled or denied.")
        return redirect("accounts:login")

    expected_state = request.session.pop("google_oauth_state", "")
    if not expected_state or request.GET.get("state") != expected_state:
        messages.error(request, "Could not verify Google sign-in state.")
        return redirect("accounts:login")

    code = request.GET.get("code")
    if not code:
        messages.error(request, "Google did not return an authorization code.")
        return redirect("accounts:login")

    try:
        identity = exchange_google_code_for_identity(code, request)
    except GoogleOAuthError:
        messages.error(request, "Google sign-in failed. Please try again.")
        return redirect("accounts:login")

    if not identity.email_verified:
        messages.error(request, "Google did not verify this email address.")
        return redirect("accounts:login")
    if _login_with_google_identity(request, identity):
        return redirect("accounts:my_profile")
    return redirect("accounts:login")


@login_required
def my_events_view(request):
    return my_profile_view(request)


def _personal_dashboard_context(user) -> dict:
    archived = ArchivedParticipation.objects.filter(user=user).order_by(
        "-year", "project_name", "panel_title"
    )
    applications = (
        Application.objects.filter(applicant=user)
        .select_related("subproject__project")
        .annotate(version_count=Count("versions"))
        .order_by("-updated_at", "-submitted_at", "title")
    )
    active_applications = [
        application
        for application in applications
        if application.status in ACTIVE_APPLICATION_STATUSES
    ]
    historical_applications = [
        application
        for application in applications
        if application.status not in ACTIVE_APPLICATION_STATUSES
    ]
    volunteer_assignments = (
        VolunteerShiftAssignment.objects.filter(user=user)
        .select_related(
            "shift__project",
            "shift__placement__room",
            "shift__placement__room_combination",
        )
        .order_by("shift__placement__starts_at", "shift__title")
    )
    unread_notifications = Notification.objects.filter(
        user=user,
        read_at__isnull=True,
    )[:10]
    read_notifications = Notification.objects.filter(
        user=user,
        read_at__isnull=False,
    )[:10]
    grant = AccessGrant.objects.filter(email=user.email, active=True).first()
    return {
        "active_applications": active_applications,
        "archived_groups": _archived_groups(archived),
        "historical_applications": historical_applications,
        "read_notifications": read_notifications,
        "grant": grant,
        "unread_notifications": unread_notifications,
        "volunteer_assignments": volunteer_assignments,
    }


@login_required
def archived_participation_detail_view(request, pk: int):
    item = get_object_or_404(
        ArchivedParticipation,
        pk=pk,
        user=request.user,
    )
    return render(
        request,
        "accounts/archived_participation_detail.html",
        {"item": item},
    )


@login_required
@require_http_methods(["POST"])
def mark_notification_read_view(request, pk: int):
    notification = get_object_or_404(
        Notification,
        pk=pk,
        user=request.user,
    )
    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at"])
    return redirect("accounts:my_profile")


@login_required
def access_grant_list_view(request):
    _require_account_admin(request.user)
    filters = _access_grant_filters(request)
    audit_filters = _access_grant_audit_filters(request)
    grants = AccessGrant.objects.prefetch_related("roles").order_by("email")
    if filters["query"]:
        grants = grants.filter(email__icontains=filters["query"])
    if filters["active"] == "active":
        grants = grants.filter(active=True)
    elif filters["active"] == "inactive":
        grants = grants.filter(active=False)
    if filters["role"]:
        grants = grants.filter(roles__role=filters["role"]).distinct()

    users_by_email = {
        user.email.lower(): user
        for user in get_user_model()
        .objects.filter(email__in=[grant.email for grant in grants])
        .select_related("userprofile")
    }
    rows = []
    for grant in grants:
        user = users_by_email.get(grant.email)
        profile_unlocked = (
            user.userprofile.profile_unlocked
            if user and hasattr(user, "userprofile")
            else False
        )
        user_exists = user is not None
        rows.append(
            {
                "grant": grant,
                "last_login": user.last_login if user else None,
                "profile_state": _access_grant_profile_state(
                    user_exists=user_exists,
                    profile_unlocked=profile_unlocked,
                ),
                "profile_unlocked": profile_unlocked,
                "user_exists": user_exists,
            }
        )
    if filters["profile_state"]:
        rows = [
            row
            for row in rows
            if row["profile_state"] == filters["profile_state"]
        ]
    audit_logs = AccessGrantAuditLog.objects.select_related("actor", "grant")
    if audit_filters["account"]:
        audit_logs = audit_logs.filter(target_email__icontains=audit_filters["account"])
    if audit_filters["actor"]:
        audit_logs = audit_logs.filter(actor_email__icontains=audit_filters["actor"])
    if audit_filters["action"]:
        audit_logs = audit_logs.filter(action=audit_filters["action"])
    audit_page = Paginator(audit_logs, AUDIT_LOGS_PER_PAGE).get_page(
        request.GET.get("audit_page")
    )
    return render(
        request,
        "accounts/access_grant_list.html",
        {
            "audit_action_choices": AccessGrantAuditLog.ACTION_CHOICES,
            "audit_filters": audit_filters,
            "audit_logs": audit_page.object_list,
            "audit_page": audit_page,
            "audit_querystring": _querystring_without(request, "audit_page"),
            "filters": filters,
            "profile_state_choices": PROFILE_STATE_CHOICES.items(),
            "rows": rows,
            "role_choices": [role.value for role in Role],
        },
    )


@login_required
def user_directory_view(request, slug: str | None = None):
    project = None
    project_user_emails: set[str] | None = None
    if slug:
        project = get_object_or_404(Project, slug=slug)
        project_user_emails = _project_user_emails(project)
    grants = AccessGrant.objects.prefetch_related("roles").order_by("email")
    if project_user_emails is not None:
        grants = grants.filter(email__in=project_user_emails)
    users_by_email = {
        user.email.lower(): user
        for user in get_user_model()
        .objects.filter(email__in=[grant.email for grant in grants])
        .select_related("userprofile")
    }
    convention_profiles_by_user = _convention_profiles_by_user(
        users_by_email.values(),
        project=project,
    )
    tile_rules = list(UserTileColorRule.objects.filter(active=True))
    rows = []
    for grant in grants:
        user = users_by_email.get(grant.email)
        profile = user.userprofile if user and hasattr(user, "userprofile") else None
        convention_profiles = (
            convention_profiles_by_user.get(user.pk, []) if user else []
        )
        convention_roles = sorted(
            {
                role
                for convention_profile in convention_profiles
                for role in convention_profile.role_labels
            }
        )
        attendee_types = sorted(
            {
                convention_profile.attendee_type
                for convention_profile in convention_profiles
                if convention_profile.attendee_type
            }
        )
        volunteer_types = sorted(
            {
                convention_profile.volunteer_type
                for convention_profile in convention_profiles
                if convention_profile.volunteer_type
                and convention_profile.volunteer_type != VolunteerType.NONE.value
            }
        )
        tile_styles = _user_tile_styles(
            attendee_types=attendee_types,
            rules=tile_rules,
            volunteer_types=volunteer_types,
        )
        rows.append(
            {
                "attendee_types": attendee_types,
                "convention_profiles": convention_profiles,
                "convention_roles": convention_roles,
                "display_name": _directory_display_name(grant, user, profile),
                "grant": grant,
                "profile": profile,
                "roles": sorted(grant.role_names),
                "show_profile_link": profile
                and (
                    can_manage_accounts(request.user)
                    or user == request.user
                    or _is_public_profile(profile)
                ),
                "tile_border_style": tile_styles["border"],
                "tile_inner_style": tile_styles["inner"],
                "user": user,
                "volunteer_types": volunteer_types,
            }
        )
    return render(
        request,
        "accounts/user_directory.html",
        {
            "can_manage_accounts": can_manage_accounts(request.user),
            "project": project,
            "rows": rows,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def user_tile_color_rule_list_view(request):
    if not can_manage_project_setup(request.user):
        raise PermissionDenied
    form = UserTileColorRuleForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "User tile color rule saved.")
        return redirect("accounts:user_tile_color_rules")
    rules = UserTileColorRule.objects.all()
    return render(
        request,
        "accounts/user_tile_color_rules.html",
        {"form": form, "rules": rules},
    )


@login_required
@require_http_methods(["GET", "POST"])
def edit_user_tile_color_rule_view(request, pk: int):
    if not can_manage_project_setup(request.user):
        raise PermissionDenied
    rule = get_object_or_404(UserTileColorRule, pk=pk)
    form = UserTileColorRuleForm(request.POST or None, instance=rule)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "User tile color rule updated.")
        return redirect("accounts:user_tile_color_rules")
    return render(
        request,
        "accounts/user_tile_color_rule_form.html",
        {"form": form, "heading": f"Edit {rule}", "rule": rule},
    )


@login_required
@require_http_methods(["POST"])
def delete_user_tile_color_rule_view(request, pk: int):
    if not can_manage_project_setup(request.user):
        raise PermissionDenied
    rule = get_object_or_404(UserTileColorRule, pk=pk)
    rule.delete()
    messages.success(request, "User tile color rule removed.")
    return redirect("accounts:user_tile_color_rules")


@login_required
@require_http_methods(["GET", "POST"])
def roles_access_view(request, slug: str | None = None):
    project = _setup_project(slug)
    _require_access_config_permission(
        request.user,
        project,
        PermissionKey.PROJECT_ROLES_MANAGE,
    )
    ensure_default_access_configuration()
    clone_form = CloneAccessConfigurationForm(
        request.POST or None,
        project=project,
    )
    role_form = RoleDefinitionForm(request.POST or None, project=project)
    assignment_form = (
        RoleAssignmentForm(request.POST or None, project=project) if project else None
    )

    if request.method == "POST":
        action = request.POST.get("action", "")
        if project and action == "clone" and clone_form.is_valid():
            clone_access_configuration_to_project(
                actor=request.user,
                project=project,
                source_project=clone_form.cleaned_data["source_project"],
            )
            messages.success(request, "Access configuration cloned.")
            return redirect(_setup_url("accounts:project_roles_access", project))
        if action == "create_role" and role_form.is_valid():
            role = role_form.save()
            _record_access_configuration_change(
                request=request,
                action="created",
                after=_role_snapshot(role),
                project=project,
                target_key=role.key,
                target_type="role",
            )
            messages.success(request, "Role saved.")
            return redirect(_roles_access_redirect(project))
        if project and action == "assign_role" and assignment_form.is_valid():
            assignment = assignment_form.save()
            _record_access_configuration_change(
                request=request,
                action="assigned",
                after=_assignment_snapshot(assignment),
                project=project,
                target_key=assignment.role_definition.key,
                target_type="role_assignment",
            )
            messages.success(request, "Role assigned.")
            return redirect(_roles_access_redirect(project))

    roles = RoleDefinition.objects.filter(project=project).order_by("name")
    assignments = (
        RoleAssignment.objects.filter(project=project)
        .select_related("role_definition", "user")
        .order_by("role_definition__name", "user__email")
        if project
        else []
    )
    return render(
        request,
        "accounts/roles_access.html",
        {
            "assignment_form": assignment_form,
            "assignments": assignments,
            "clone_form": clone_form,
            "project": project,
            "role_form": role_form,
            "roles": roles,
            "scope_label": _scope_label(project),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def edit_role_definition_view(request, pk: int):
    role = get_object_or_404(RoleDefinition.objects.select_related("project"), pk=pk)
    project = role.project
    _require_access_config_permission(
        request.user,
        project,
        PermissionKey.PROJECT_ROLES_MANAGE,
    )
    before = _role_snapshot(role)
    form = RoleDefinitionForm(request.POST or None, instance=role, project=project)
    if request.method == "POST" and form.is_valid():
        role = form.save()
        _record_access_configuration_change(
            request=request,
            action="updated",
            after=_role_snapshot(role),
            before=before,
            project=project,
            target_key=role.key,
            target_type="role",
        )
        messages.success(request, "Role updated.")
        return redirect(_roles_access_redirect(project))
    return render(
        request,
        "accounts/role_definition_form.html",
        {"form": form, "project": project, "role": role},
    )


@login_required
@require_http_methods(["GET", "POST"])
def statuses_benefits_view(request, slug: str | None = None):
    project = _setup_project(slug)
    _require_access_config_permission(
        request.user,
        project,
        PermissionKey.PROJECT_STATUSES_MANAGE,
    )
    ensure_default_access_configuration()
    benefit_form = AccessBenefitForm(request.POST or None, project=project)
    grant_form = StatusBenefitGrantForm(request.POST or None, project=project)

    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "create_benefit" and benefit_form.is_valid():
            benefit = benefit_form.save()
            _record_access_configuration_change(
                request=request,
                action="created",
                after=_benefit_snapshot(benefit),
                project=project,
                target_key=benefit.key,
                target_type="benefit",
            )
            messages.success(request, "Benefit saved.")
            return redirect(_statuses_benefits_redirect(project))
        if action == "grant_benefit" and grant_form.is_valid():
            grant = grant_form.save()
            _record_access_configuration_change(
                request=request,
                action="granted",
                after=_status_benefit_snapshot(grant),
                project=project,
                target_key=f"{grant.status_type}:{grant.status_value}",
                target_type="status_benefit",
            )
            messages.success(request, "Benefit grant saved.")
            return redirect(_statuses_benefits_redirect(project))
        if project and action in {"approve_fursuiter", "reject_fursuiter"}:
            convention_profile = get_object_or_404(
                UserConventionProfile.objects.select_related("user", "project"),
                pk=request.POST.get("convention_profile"),
                project=project,
            )
            before = _convention_profile_status_snapshot(convention_profile)
            convention_profile.fursuiter_status = (
                FursuiterStatus.APPROVED.value
                if action == "approve_fursuiter"
                else FursuiterStatus.REJECTED.value
            )
            convention_profile.save(update_fields=["fursuiter_status", "updated_at"])
            _record_access_configuration_change(
                request=request,
                action=action,
                after=_convention_profile_status_snapshot(convention_profile),
                before=before,
                project=project,
                target_key=convention_profile.user.email,
                target_type="fursuiter_status",
            )
            messages.success(request, "Fursuiter status updated.")
            return redirect(_statuses_benefits_redirect(project))

    benefits = AccessBenefit.objects.filter(project=project).order_by("label")
    grants = (
        StatusBenefitGrant.objects.filter(project=project)
        .select_related("benefit")
        .order_by("status_type", "status_value", "benefit__label")
    )
    pending_fursuiters = (
        UserConventionProfile.objects.filter(
            fursuiter_status=FursuiterStatus.PENDING.value,
            project=project,
        )
        .select_related("user", "user__userprofile")
        .order_by("user__email")
        if project
        else []
    )
    return render(
        request,
        "accounts/statuses_benefits.html",
        {
            "benefit_form": benefit_form,
            "benefits": benefits,
            "grant_form": grant_form,
            "grants": grants,
            "pending_fursuiters": pending_fursuiters,
            "project": project,
            "scope_label": _scope_label(project),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def labels_view(request, slug: str | None = None):
    project = _setup_project(slug)
    _require_access_config_permission(
        request.user,
        project,
        PermissionKey.PROJECT_LABELS_MANAGE,
    )
    ensure_default_access_configuration()
    form = LabelOverrideForm(request.POST or None, project=project)
    if request.method == "POST" and form.is_valid():
        label = form.save(commit=False)
        before_obj = LabelOverride.objects.filter(
            project=project,
            key=label.key,
        ).first()
        before = _label_snapshot(before_obj) if before_obj else None
        label, _ = LabelOverride.objects.update_or_create(
            project=project,
            key=label.key,
            defaults={"label": label.label},
        )
        _record_access_configuration_change(
            request=request,
            action="updated",
            after=_label_snapshot(label),
            before=before,
            project=project,
            target_key=label.key,
            target_type="label",
        )
        messages.success(request, "Label saved.")
        return redirect(_labels_redirect(project))
    labels = LabelOverride.objects.filter(project=project).order_by("key")
    return render(
        request,
        "accounts/labels.html",
        {
            "form": form,
            "labels": labels,
            "project": project,
            "scope_label": _scope_label(project),
        },
    )


@login_required
def statistics_view(request):
    country_counts = (
        UserProfile.objects.exclude(country="")
        .filter(user__convention_profiles__isnull=False)
        .values("country")
        .annotate(total=Count("user", distinct=True))
        .order_by("country")
    )
    attendee_type_counts = (
        UserConventionProfile.objects.exclude(attendee_type="")
        .values("attendee_type")
        .annotate(total=Count("id"))
        .order_by("attendee_type")
    )
    project_counts = (
        Project.objects.annotate(attendee_count=Count("user_convention_profiles"))
        .filter(attendee_count__gt=0)
        .order_by("opens_at", "name")
    )
    return render(
        request,
        "accounts/statistics.html",
        {
            "attendee_type_counts": attendee_type_counts,
            "country_counts": [
                {
                    "country": dict(UserProfile._meta.get_field("country").choices)[
                        row["country"]
                    ],
                    "total": row["total"],
                }
                for row in country_counts
            ],
            "project_counts": project_counts,
            "total_convention_profiles": UserConventionProfile.objects.count(),
            "total_people": (
                UserProfile.objects.filter(
                    user__convention_profiles__isnull=False
                )
                .distinct()
                .count()
            ),
        },
    )


@login_required
def access_grant_audit_log_detail_view(request, pk: int):
    _require_account_admin(request.user)
    audit_log = get_object_or_404(
        AccessGrantAuditLog.objects.select_related("actor", "grant"),
        pk=pk,
    )
    return render(
        request,
        "accounts/access_grant_audit_log_detail.html",
        {"audit_log": audit_log},
    )


@login_required
def access_grant_history_view(request, pk: int):
    _require_account_admin(request.user)
    grant = get_object_or_404(AccessGrant.objects.prefetch_related("roles"), pk=pk)
    audit_logs = AccessGrantAuditLog.objects.filter(
        target_email=grant.email,
    ).select_related("actor", "grant")
    return render(
        request,
        "accounts/access_grant_history.html",
        {
            "audit_logs": audit_logs,
            "grant": grant,
        },
    )


@login_required
def export_access_grants_view(request):
    _require_account_admin(request.user)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="maru-accounts.csv"'
    writer = csv.writer(response)
    writer.writerow(["email", "active", "roles", "notes"])
    for grant in AccessGrant.objects.prefetch_related("roles").order_by("email"):
        writer.writerow(
            [
                grant.email,
                "true" if grant.active else "false",
                ";".join(sorted(grant.role_names)),
                grant.notes,
            ]
        )
    return response


@login_required
@require_http_methods(["GET", "POST"])
def import_access_grants_view(request):
    _require_account_admin(request.user)
    form = AccessGrantImportForm(request.POST or None, request.FILES or None)
    csv_content = ""
    errors = []
    report = None
    if request.method == "POST" and request.POST.get("action") == "download_rejected":
        csv_content = request.POST.get("csv_content", "")
        rows, _errors, report = _parse_access_grant_import_content(csv_content)
        return _rejected_access_grant_import_response(report["rows"])
    if request.method == "POST" and request.POST.get("action") == "apply":
        csv_content = request.POST.get("csv_content", "")
        rows, errors, report = _parse_access_grant_import_content(csv_content)
        if not errors:
            result = _apply_access_grant_import(rows, request.user)
            messages.success(
                request,
                (
                    "Imported accounts: "
                    f"{result['created']} created, "
                    f"{result['updated']} updated, "
                    f"{result['unchanged']} unchanged."
                ),
            )
            return redirect("accounts:access_grant_list")
    elif request.method == "POST" and form.is_valid():
        csv_content = _read_access_grant_import(form.cleaned_data["csv_file"])
        if csv_content is None:
            errors = ["CSV file must be UTF-8 encoded."]
        else:
            rows, errors, report = _parse_access_grant_import_content(csv_content)
    return render(
        request,
        "accounts/access_grant_import.html",
        {
            "csv_content": csv_content,
            "errors": errors,
            "form": form,
            "report": report,
        },
    )


@login_required
@require_http_methods(["POST"])
def unlock_access_grant_profile_view(request, pk: int):
    return _set_access_grant_profile_unlocked(
        request,
        pk=pk,
        unlocked=True,
    )


@login_required
@require_http_methods(["POST"])
def lock_access_grant_profile_view(request, pk: int):
    return _set_access_grant_profile_unlocked(
        request,
        pk=pk,
        unlocked=False,
    )


@login_required
@require_http_methods(["GET", "POST"])
def create_access_grant_view(request):
    _require_account_admin(request.user)
    form = AccessGrantForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        grant = form.save()
        _sync_access_roles(grant, form.cleaned_data["roles"])
        _write_access_grant_audit(
            grant=grant,
            actor=request.user,
            action=AccessGrantAuditLog.ACTION_CREATED,
            before=None,
            after=_access_grant_snapshot(grant),
        )
        messages.success(request, "Access account created.")
        return redirect("accounts:access_grant_list")
    return render(
        request,
        "accounts/access_grant_form.html",
        {"form": form, "heading": "Add account"},
    )


@login_required
@require_http_methods(["GET", "POST"])
def edit_access_grant_view(request, pk: int):
    _require_account_admin(request.user)
    grant = get_object_or_404(AccessGrant.objects.prefetch_related("roles"), pk=pk)
    before = _access_grant_snapshot(grant)
    form = AccessGrantForm(request.POST or None, instance=grant)
    if request.method == "POST" and form.is_valid():
        grant = form.save()
        _sync_access_roles(grant, form.cleaned_data["roles"])
        grant.refresh_from_db()
        after = _access_grant_snapshot(grant)
        if before != after:
            _write_access_grant_audit(
                grant=grant,
                actor=request.user,
                action=AccessGrantAuditLog.ACTION_UPDATED,
                before=before,
                after=after,
            )
            messages.success(request, "Access account updated.")
        else:
            messages.success(request, "No account changes detected.")
        return redirect("accounts:access_grant_list")
    return render(
        request,
        "accounts/access_grant_form.html",
        {"form": form, "grant": grant, "heading": "Edit account"},
    )


def _archived_groups(archived) -> list[dict]:
    groups = []
    group_lookup = {}
    for item in archived:
        key = (item.year, item.project_name)
        if key not in group_lookup:
            group = {"year": item.year, "project_name": item.project_name, "items": []}
            group_lookup[key] = group
            groups.append(group)
        group_lookup[key]["items"].append(item)
    return groups


@login_required
def my_profile_view(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    return _render_profile_detail(
        request,
        profile,
        personal_dashboard=_personal_dashboard_context(request.user),
    )


@login_required
def profile_detail_view(request, pk: int):
    viewed_profile = get_object_or_404(
        UserProfile.objects.select_related("user"),
        pk=pk,
    )
    return _render_profile_detail(request, viewed_profile)


def _render_profile_detail(
    request,
    viewed_profile: UserProfile,
    personal_dashboard: dict | None = None,
):
    can_manage = can_review_applications(request.user)
    can_admin_profiles = can_manage_accounts(request.user)
    is_owner = viewed_profile.user_id == request.user.id
    if not can_manage and not is_owner and not _is_public_profile(viewed_profile):
        raise Http404
    context = {
        "can_edit_profile": can_admin_profiles
        or (is_owner and viewed_profile.profile_unlocked),
        "can_manage": can_manage,
        "is_owner": is_owner,
        "personal_dashboard": personal_dashboard,
        "show_contact": can_manage or is_owner or viewed_profile.show_contact_handles,
        "show_fursuit_picture": (
            can_manage or is_owner or viewed_profile.show_fursuit_picture
        ),
        "show_private_details": can_manage or is_owner,
        "viewed_profile": viewed_profile,
    }
    convention_profiles = (
        UserConventionProfile.objects.filter(user=viewed_profile.user)
        .select_related("project")
        .order_by("project__opens_at", "project__name")
    )
    context["convention_profiles"] = convention_profiles
    context["convention_profile_rows"] = [
        {
            "benefits": user_benefit_keys(
                viewed_profile.user,
                convention_profile.project,
            ),
            "convention_profile": convention_profile,
        }
        for convention_profile in convention_profiles
    ]
    if personal_dashboard:
        context.update(personal_dashboard)
    return render(request, "accounts/profile_detail.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def profile_edit_view(request, pk: int | None = None):
    if pk is None:
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
    else:
        profile = get_object_or_404(
            UserProfile.objects.select_related("user"),
            pk=pk,
        )
    is_owner = profile.user_id == request.user.id
    if not is_owner and not can_manage_accounts(request.user):
        raise PermissionDenied

    back_url = (
        reverse("accounts:my_profile")
        if is_owner
        else reverse("accounts:profile_detail", args=[profile.pk])
    )
    form = UserProfileForm(
        request.POST or None,
        request.FILES or None,
        instance=profile,
    )
    convention_forms = _profile_convention_forms(
        request=request,
        profile=profile,
        allow_role_edit=can_manage_accounts(request.user),
    )
    if request.method == "POST" and form.is_valid() and all(
        convention_form.is_valid() for convention_form in convention_forms
    ):
        form.save()
        for convention_form in convention_forms:
            convention_form.save()
        messages.success(request, "Profile updated.")
        return redirect(back_url)

    return render(
        request,
        "accounts/profile_edit.html",
        {
            "back_url": back_url,
            "convention_forms": convention_forms,
            "form": form,
            "profile": profile,
        },
    )


def _profile_convention_forms(*, request, profile, allow_role_edit: bool):
    existing = {
        item.project_id: item
        for item in UserConventionProfile.objects.filter(user=profile.user)
    }
    projects = Project.objects.order_by("opens_at", "name")
    return [
        UserConventionProfileForm(
            request.POST or None,
            actor=request.user,
            allow_fursuiter_validation=has_permission(
                request.user,
                PermissionKey.PROJECT_FURSUITERS_VALIDATE,
                project,
            ),
            allow_role_edit=allow_role_edit,
            allow_status_edit=has_permission(
                request.user,
                PermissionKey.PROJECT_STATUSES_MANAGE,
                project,
            ),
            instance=existing.get(project.pk),
            prefix=f"convention_{project.pk}",
            project=project,
            user=profile.user,
        )
        for project in projects
    ]


def _setup_project(slug: str | None):
    if not slug:
        return None
    return get_object_or_404(Project, slug=slug)


def _require_access_config_permission(user, project, permission: PermissionKey) -> None:
    if project:
        if has_permission(user, permission, project) or has_permission(
            user,
            PermissionKey.PROJECT_SETUP_MANAGE,
            project,
        ):
            return
    elif has_permission(user, PermissionKey.PROJECT_SETUP_MANAGE):
        return
    raise PermissionDenied


def _scope_label(project) -> str:
    return project.name if project else "Global defaults"


def _setup_url(name: str, project):
    return reverse(name, args=[project.slug]) if project else reverse(name)


def _roles_access_redirect(project):
    return _setup_url("accounts:project_roles_access", project) if project else reverse(
        "accounts:roles_access",
    )


def _statuses_benefits_redirect(project):
    return (
        _setup_url("accounts:project_statuses_benefits", project)
        if project
        else reverse("accounts:statuses_benefits")
    )


def _labels_redirect(project):
    return _setup_url("accounts:project_labels", project) if project else reverse(
        "accounts:labels",
    )


def _record_access_configuration_change(
    *,
    request,
    action: str,
    target_type: str,
    project=None,
    target_key: str = "",
    before=None,
    after=None,
) -> None:
    AccessConfigurationAuditLog.objects.create(
        project=project,
        actor=request.user,
        actor_email=request.user.email,
        action=action,
        target_type=target_type,
        target_key=target_key,
        before=before,
        after=after,
    )


def _role_snapshot(role: RoleDefinition) -> dict:
    return {
        "active": role.active,
        "description": role.description,
        "key": role.key,
        "name": role.name,
        "permissions": sorted(role.permissions or []),
        "project": role.project.slug if role.project_id else None,
    }


def _assignment_snapshot(assignment: RoleAssignment) -> dict:
    return {
        "project": assignment.project.slug,
        "role": assignment.role_definition.key,
        "scopes": assignment.scopes,
        "user": assignment.user.email,
    }


def _benefit_snapshot(benefit: AccessBenefit) -> dict:
    return {
        "active": benefit.active,
        "description": benefit.description,
        "key": benefit.key,
        "label": benefit.label,
        "project": benefit.project.slug if benefit.project_id else None,
        "target": benefit.target,
    }


def _status_benefit_snapshot(grant: StatusBenefitGrant) -> dict:
    return {
        "benefit": grant.benefit.key,
        "project": grant.project.slug if grant.project_id else None,
        "status_type": grant.status_type,
        "status_value": grant.status_value,
    }


def _label_snapshot(label: LabelOverride) -> dict:
    return {
        "key": label.key,
        "label": label.label,
        "project": label.project.slug if label.project_id else None,
    }


def _convention_profile_status_snapshot(profile: UserConventionProfile) -> dict:
    return {
        "fursuiter_status": profile.fursuiter_status,
        "ticket_level_selected": profile.ticket_level_selected,
        "ticket_level_verified": profile.ticket_level_verified,
        "user": profile.user.email,
    }


def _is_public_profile(profile: UserProfile) -> bool:
    return profile.profile_unlocked and profile.show_profile_publicly


def _login_with_google_identity(request, identity: GoogleIdentity) -> bool:
    return _login_with_email(request, identity.email)


def _login_with_email(request, raw_email: str) -> bool:
    email = normalize_email(raw_email)
    if not is_google_email(email):
        messages.error(request, "Use a Gmail or Googlemail address.")
        return False

    grant = AccessGrant.objects.filter(email=email, active=True).first()
    if not grant:
        messages.error(request, "This Google account is not on the access list.")
        return False

    user = _get_or_create_login_user(email)
    login(request, user)
    return True


def _is_dev_login_enabled() -> bool:
    return settings.MARU_DEV_LOGIN_ENABLED


def _require_account_admin(user) -> None:
    if not can_manage_accounts(user):
        raise PermissionDenied


def _access_grant_filters(request) -> dict[str, str]:
    role = request.GET.get("role", "")
    if role not in {choice.value for choice in Role}:
        role = ""
    active = request.GET.get("active", "")
    if active not in {"", "active", "inactive"}:
        active = ""
    profile_state = request.GET.get("profile_state", "")
    if profile_state not in {"", *PROFILE_STATE_CHOICES}:
        profile_state = ""
    return {
        "active": active,
        "profile_state": profile_state,
        "query": request.GET.get("q", "").strip(),
        "role": role,
    }


def _access_grant_profile_state(
    *,
    user_exists: bool,
    profile_unlocked: bool,
) -> str:
    if not user_exists:
        return "no_user"
    if profile_unlocked:
        return "unlocked"
    return "locked"


def _directory_display_name(grant: AccessGrant, user, profile: UserProfile | None):
    if profile and profile.display_name:
        return profile.display_name
    if profile and profile.fursuit_name:
        return profile.fursuit_name
    if user:
        return user.get_full_name() or "Convention participant"
    return "Pending user"


def _convention_profiles_by_user(
    users,
    *,
    project: Project | None = None,
) -> dict[int, list[UserConventionProfile]]:
    user_ids = [user.pk for user in users if user]
    rows: dict[int, list[UserConventionProfile]] = {}
    if not user_ids:
        return rows
    convention_profiles = (
        UserConventionProfile.objects.filter(user_id__in=user_ids)
        .select_related("project")
        .order_by("project__opens_at", "project__name")
    )
    if project:
        convention_profiles = convention_profiles.filter(project=project)
    for convention_profile in convention_profiles:
        rows.setdefault(convention_profile.user_id, []).append(convention_profile)
    return rows


def _project_user_emails(project: Project) -> set[str]:
    emails = set(
        UserConventionProfile.objects.filter(project=project).values_list(
            "user__email",
            flat=True,
        )
    )
    emails.update(
        Application.objects.filter(subproject__project=project).values_list(
            "applicant__email",
            flat=True,
        )
    )
    emails.update(
        VolunteerShiftAssignment.objects.filter(shift__project=project).values_list(
            "user__email",
            flat=True,
        )
    )
    return {email.lower() for email in emails if email}


def _user_tile_styles(
    *,
    attendee_types: list[str],
    rules: list[UserTileColorRule],
    volunteer_types: list[str],
) -> dict[str, str]:
    attendee_color = _tile_color_for_target(
        rules=rules,
        target_type=UserTileColorRule.ATTENDEE_TYPE,
        values=attendee_types,
        fallback=DEFAULT_USER_TILE_BORDER_COLOR,
    )
    volunteer_style = _tile_volunteer_style(
        rules=rules,
        volunteer_types=volunteer_types,
    )
    return {
        "border": f"border-color: {attendee_color};",
        "inner": volunteer_style,
    }


def _tile_color_for_target(
    *,
    fallback: str,
    rules: list[UserTileColorRule],
    target_type: str,
    values: list[str],
) -> str:
    for rule in rules:
        if (
            rule.applies_to == UserTileColorRule.EDGE
            and rule.target_type == target_type
            and rule.target_value in values
        ):
            return rule.background_color
    for value in values:
        if value in DEFAULT_ATTENDEE_BORDER_COLORS:
            return DEFAULT_ATTENDEE_BORDER_COLORS[value]
    return fallback


def _tile_volunteer_style(
    *,
    rules: list[UserTileColorRule],
    volunteer_types: list[str],
) -> str:
    values = volunteer_types or [VolunteerType.NONE.value]
    for rule in rules:
        if (
            rule.applies_to == UserTileColorRule.INTERIOR
            and rule.target_type == UserTileColorRule.VOLUNTEER_TYPE
            and rule.target_value in values
        ):
            return (
                f"background: {rule.background_color}; "
                f"color: {_text_color_for_background(rule.background_color)};"
            )
    for value in values:
        if value in DEFAULT_VOLUNTEER_TILE_STYLES:
            return DEFAULT_VOLUNTEER_TILE_STYLES[value]
    return DEFAULT_VOLUNTEER_TILE_STYLES[VolunteerType.NONE.value]


def _text_color_for_background(color: str) -> str:
    color = color.lstrip("#")
    if len(color) != 6:
        return "#1f2937"
    try:
        red = int(color[0:2], 16)
        green = int(color[2:4], 16)
        blue = int(color[4:6], 16)
    except ValueError:
        return "#1f2937"
    brightness = (red * 299 + green * 587 + blue * 114) / 1000
    return "#111827" if brightness > 150 else "#ffffff"


def _access_grant_audit_filters(request) -> dict[str, str]:
    action = request.GET.get("audit_action", "")
    valid_actions = {choice for choice, _label in AccessGrantAuditLog.ACTION_CHOICES}
    if action not in valid_actions:
        action = ""
    return {
        "account": request.GET.get("audit_account", "").strip(),
        "action": action,
        "actor": request.GET.get("audit_actor", "").strip(),
    }


def _querystring_without(request, *keys: str) -> str:
    query = request.GET.copy()
    for key in keys:
        query.pop(key, None)
    return query.urlencode()


def _read_access_grant_import(uploaded_file) -> str | None:
    try:
        return uploaded_file.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def _parse_access_grant_import_content(
    content: str,
) -> tuple[list[dict], list[str], dict]:
    reader = csv.DictReader(io.StringIO(content))
    required_fields = {"email", "active", "roles"}
    if not reader.fieldnames or not required_fields <= set(reader.fieldnames):
        errors = ["CSV must include email, active, and roles columns."]
        return [], errors, _access_grant_import_report([], errors)

    rows = []
    errors = []
    seen_emails = set()
    valid_roles = {role.value for role in Role}
    for line_number, row in enumerate(reader, start=2):
        email = normalize_email(row.get("email", ""))
        active = _parse_import_bool(row.get("active", ""))
        roles = _parse_import_roles(row.get("roles", ""))
        row_errors = []

        if not email:
            row_errors.append("email is required")
        elif not is_google_email(email):
            row_errors.append("use a Gmail or Googlemail address")
        elif email in seen_emails:
            row_errors.append(f"duplicate email {email}")
        if email:
            seen_emails.add(email)

        if active is None:
            row_errors.append("active must be true or false")
        invalid_roles = sorted(set(roles) - valid_roles)
        if invalid_roles:
            row_errors.append(f"invalid roles: {', '.join(invalid_roles)}")
        errors.extend(f"Line {line_number}: {error}." for error in row_errors)
        rows.append(
            {
                "active": active,
                "email": email,
                "errors": row_errors,
                "line_number": line_number,
                "notes": row.get("notes", "").strip(),
                "roles": roles,
            }
        )

    return rows, errors, _access_grant_import_report(rows, errors)


def _access_grant_import_report(rows: list[dict], errors: list[str]) -> dict:
    report_rows = []
    summary = {"created": 0, "rejected": 0, "unchanged": 0, "updated": 0}
    existing_grants = {
        grant.email: grant
        for grant in AccessGrant.objects.filter(
            email__in=[row["email"] for row in rows if row["email"]]
        ).prefetch_related("roles")
    }
    for row in rows:
        changes = []
        status = "rejected"
        if not row["errors"]:
            existing = existing_grants.get(row["email"])
            if existing is None:
                status = "created"
            else:
                incoming = {
                    "active": row["active"],
                    "email": row["email"],
                    "notes": row["notes"],
                    "roles": sorted(row["roles"]),
                }
                status = (
                    "unchanged"
                    if _access_grant_snapshot(existing) == incoming
                    else "updated"
                )
                changes = _access_grant_import_changes(
                    _access_grant_snapshot(existing),
                    incoming,
                )
        summary[status] += 1
        report_rows.append({**row, "changes": changes, "status": status})
    return {
        "can_apply": bool(rows) and not errors,
        "rows": report_rows,
        "summary": summary,
    }


def _rejected_access_grant_import_response(rows: list[dict]) -> HttpResponse:
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        'attachment; filename="maru-rejected-accounts.csv"'
    )
    writer = csv.writer(response)
    writer.writerow(["line", "email", "active", "roles", "notes", "issues"])
    for row in rows:
        if row["status"] != "rejected":
            continue
        writer.writerow(
            [
                row["line_number"],
                row["email"],
                _format_access_grant_import_value(row["active"]),
                ";".join(row["roles"]),
                row["notes"],
                "; ".join(row["errors"]),
            ]
        )
    return response


def _access_grant_import_changes(before: dict, after: dict) -> list[dict[str, str]]:
    fields = [
        ("active", "Active"),
        ("roles", "Roles"),
        ("notes", "Notes"),
    ]
    changes = []
    for field, label in fields:
        if before[field] != after[field]:
            changes.append(
                {
                    "after": _format_access_grant_import_value(after[field]),
                    "before": _format_access_grant_import_value(before[field]),
                    "label": label,
                }
            )
    return changes


def _format_access_grant_import_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "; ".join(value) if value else "-"
    return value or "-"


def _parse_import_bool(value: str) -> bool | None:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "active"}:
        return True
    if normalized in {"0", "false", "no", "n", "inactive"}:
        return False
    return None


def _parse_import_roles(value: str) -> list[str]:
    return [role.strip() for role in value.split(";") if role.strip()]


@transaction.atomic
def _apply_access_grant_import(rows: list[dict], actor) -> dict[str, int]:
    result = {"created": 0, "unchanged": 0, "updated": 0}
    for row in rows:
        grant = AccessGrant.objects.filter(email=row["email"]).first()
        if grant is None:
            grant = AccessGrant.objects.create(
                email=row["email"],
                active=row["active"],
                notes=row["notes"],
            )
            _sync_access_roles(grant, row["roles"])
            _write_access_grant_audit(
                grant=grant,
                actor=actor,
                action=AccessGrantAuditLog.ACTION_CREATED,
                before=None,
                after=_access_grant_snapshot(grant),
            )
            result["created"] += 1
            continue

        before = _access_grant_snapshot(grant)
        grant.active = row["active"]
        grant.notes = row["notes"]
        grant.save(update_fields=["active", "notes", "updated_at"])
        _sync_access_roles(grant, row["roles"])
        grant.refresh_from_db()
        after = _access_grant_snapshot(grant)
        if before == after:
            result["unchanged"] += 1
        else:
            _write_access_grant_audit(
                grant=grant,
                actor=actor,
                action=AccessGrantAuditLog.ACTION_UPDATED,
                before=before,
                after=after,
            )
            result["updated"] += 1
    return result


def _set_access_grant_profile_unlocked(request, *, pk: int, unlocked: bool):
    _require_account_admin(request.user)
    grant = get_object_or_404(AccessGrant, pk=pk)
    user = get_user_model().objects.filter(email=grant.email).first()
    if user is None:
        messages.error(request, "This account has not logged in yet.")
        return redirect("accounts:access_grant_list")

    profile, _ = UserProfile.objects.get_or_create(user=user)
    before = _profile_access_snapshot(grant, profile)
    if profile.profile_unlocked == unlocked:
        message = (
            "Profile was already unlocked."
            if unlocked
            else "Profile was already locked."
        )
        messages.success(
            request,
            message,
        )
        return redirect("accounts:access_grant_list")

    profile.profile_unlocked = unlocked
    profile.save(update_fields=["profile_unlocked"])
    after = _profile_access_snapshot(grant, profile)
    _write_access_grant_audit(
        grant=grant,
        actor=request.user,
        action=(
            AccessGrantAuditLog.ACTION_PROFILE_UNLOCKED
            if unlocked
            else AccessGrantAuditLog.ACTION_PROFILE_LOCKED
        ),
        before=before,
        after=after,
    )
    if unlocked:
        Notification.objects.create(
            user=user,
            title="Profile unlocked",
            body="An admin unlocked your profile.",
            link_url="/profile/edit/",
            link_label="Edit profile",
        )
    messages.success(
        request,
        "Profile unlocked." if unlocked else "Profile locked.",
    )
    return redirect("accounts:access_grant_list")


def _profile_access_snapshot(grant: AccessGrant, profile: UserProfile) -> dict:
    snapshot = _access_grant_snapshot(grant)
    snapshot["profile_unlocked"] = profile.profile_unlocked
    return snapshot


def _sync_access_roles(grant: AccessGrant, role_names: list[str]) -> None:
    wanted = set(role_names)
    existing = set(grant.roles.values_list("role", flat=True))
    for role in sorted(wanted - existing):
        AccessRole.objects.create(grant=grant, role=role)
    grant.roles.filter(role__in=existing - wanted).delete()


def _access_grant_snapshot(grant: AccessGrant) -> dict:
    roles = sorted(grant.roles.values_list("role", flat=True))
    return {
        "active": grant.active,
        "email": grant.email,
        "notes": grant.notes,
        "roles": roles,
    }


def _write_access_grant_audit(
    *,
    grant: AccessGrant,
    actor,
    action: str,
    before: dict | None,
    after: dict,
) -> None:
    AccessGrantAuditLog.objects.create(
        grant=grant,
        actor=actor,
        actor_email=actor.email,
        target_email=after["email"],
        action=action,
        before=before,
        after=after,
    )


@transaction.atomic
def _get_or_create_login_user(email: str):
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
    return user
