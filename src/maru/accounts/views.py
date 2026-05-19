from __future__ import annotations

import csv
import io
import secrets

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

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
    AccessGrantForm,
    AccessGrantImportForm,
    UserProfileForm,
)
from maru.accounts.models import (
    AccessGrant,
    AccessGrantAuditLog,
    AccessRole,
    ArchivedParticipation,
    Notification,
    UserProfile,
)
from maru.domain import ApplicationStatus, Role
from maru.projects.models import Application, VolunteerShiftAssignment
from maru.projects.review import can_manage_accounts, can_review_applications

ACTIVE_APPLICATION_STATUSES = {
    ApplicationStatus.DRAFT.value,
    ApplicationStatus.SUBMITTED.value,
    ApplicationStatus.REOPENED.value,
}


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect("accounts:my_events")

    if request.method == "POST":
        if not _is_dev_login_enabled():
            messages.error(request, "Development email login is disabled.")
        elif _login_with_email(request, request.POST.get("email", "")):
            return redirect("accounts:my_events")

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
        return redirect("accounts:my_events")
    if not is_google_oauth_configured():
        messages.error(request, "Google OAuth is not configured yet.")
        return redirect("accounts:login")

    state = secrets.token_urlsafe(32)
    request.session["google_oauth_state"] = state
    return HttpResponseRedirect(build_google_authorization_url(request, state))


def google_oauth_callback_view(request):
    if request.user.is_authenticated:
        return redirect("accounts:my_events")

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
        return redirect("accounts:my_events")
    return redirect("accounts:login")


@login_required
def my_events_view(request):
    archived = ArchivedParticipation.objects.filter(user=request.user).order_by(
        "-year", "project_name", "panel_title"
    )
    applications = (
        Application.objects.filter(applicant=request.user)
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
        VolunteerShiftAssignment.objects.filter(user=request.user)
        .select_related(
            "shift__project",
            "shift__placement__room",
            "shift__placement__room_combination",
        )
        .order_by("shift__placement__starts_at", "shift__title")
    )
    unread_notifications = Notification.objects.filter(
        user=request.user,
        read_at__isnull=True,
    )[:10]
    read_notifications = Notification.objects.filter(
        user=request.user,
        read_at__isnull=False,
    )[:10]
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    grant = AccessGrant.objects.filter(email=request.user.email, active=True).first()
    return render(
        request,
        "accounts/my_events.html",
        {
            "active_applications": active_applications,
            "archived_groups": _archived_groups(archived),
            "historical_applications": historical_applications,
            "profile": profile,
            "read_notifications": read_notifications,
            "grant": grant,
            "unread_notifications": unread_notifications,
            "volunteer_assignments": volunteer_assignments,
        },
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
    return redirect("accounts:my_events")


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
        rows.append(
            {
                "grant": grant,
                "last_login": user.last_login if user else None,
                "profile_unlocked": (
                    user.userprofile.profile_unlocked
                    if user and hasattr(user, "userprofile")
                    else False
                ),
                "user_exists": user is not None,
            }
        )
    audit_logs = AccessGrantAuditLog.objects.select_related("actor", "grant")
    if audit_filters["account"]:
        audit_logs = audit_logs.filter(target_email__icontains=audit_filters["account"])
    if audit_filters["actor"]:
        audit_logs = audit_logs.filter(actor_email__icontains=audit_filters["actor"])
    if audit_filters["action"]:
        audit_logs = audit_logs.filter(action=audit_filters["action"])
    audit_logs = audit_logs[:25]
    return render(
        request,
        "accounts/access_grant_list.html",
        {
            "audit_action_choices": AccessGrantAuditLog.ACTION_CHOICES,
            "audit_filters": audit_filters,
            "audit_logs": audit_logs,
            "filters": filters,
            "rows": rows,
            "role_choices": [role.value for role in Role],
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
    errors = []
    if request.method == "POST" and form.is_valid():
        rows, errors = _parse_access_grant_import(form.cleaned_data["csv_file"])
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
    return render(
        request,
        "accounts/access_grant_import.html",
        {"errors": errors, "form": form},
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
def profile_detail_view(request, pk: int):
    viewed_profile = get_object_or_404(
        UserProfile.objects.select_related("user"),
        pk=pk,
    )
    can_manage = can_review_applications(request.user)
    if not can_manage and not _is_public_profile(viewed_profile):
        raise Http404
    return render(
        request,
        "accounts/profile_detail.html",
        {
            "can_manage": can_manage,
            "show_contact": can_manage or viewed_profile.show_contact_handles,
            "viewed_profile": viewed_profile,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def profile_edit_view(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.profile_unlocked:
        raise PermissionDenied

    form = UserProfileForm(
        request.POST or None,
        request.FILES or None,
        instance=profile,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profile updated.")
        return redirect("accounts:my_events")

    return render(request, "accounts/profile_edit.html", {"form": form})


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
    return {
        "active": active,
        "query": request.GET.get("q", "").strip(),
        "role": role,
    }


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


def _parse_access_grant_import(uploaded_file) -> tuple[list[dict], list[str]]:
    try:
        decoded = uploaded_file.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return [], ["CSV file must be UTF-8 encoded."]

    reader = csv.DictReader(io.StringIO(decoded))
    required_fields = {"email", "active", "roles"}
    if not reader.fieldnames or not required_fields <= set(reader.fieldnames):
        return [], ["CSV must include email, active, and roles columns."]

    rows = []
    errors = []
    seen_emails = set()
    valid_roles = {role.value for role in Role}
    for line_number, row in enumerate(reader, start=2):
        email = normalize_email(row.get("email", ""))
        active = _parse_import_bool(row.get("active", ""))
        roles = _parse_import_roles(row.get("roles", ""))

        if not email:
            errors.append(f"Line {line_number}: email is required.")
        elif not is_google_email(email):
            errors.append(f"Line {line_number}: use a Gmail or Googlemail address.")
        elif email in seen_emails:
            errors.append(f"Line {line_number}: duplicate email {email}.")
        seen_emails.add(email)

        if active is None:
            errors.append(f"Line {line_number}: active must be true or false.")
        invalid_roles = sorted(set(roles) - valid_roles)
        if invalid_roles:
            errors.append(
                f"Line {line_number}: invalid roles: {', '.join(invalid_roles)}."
            )
        rows.append(
            {
                "active": active,
                "email": email,
                "notes": row.get("notes", "").strip(),
                "roles": roles,
            }
        )

    return rows, errors


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
