from __future__ import annotations

import csv
import io
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from maru.accounts.auth import GoogleIdentity, is_google_email
from maru.accounts.models import (
    AccessGrant,
    AccessGrantAuditLog,
    AccessRole,
    ArchivedParticipation,
    Notification,
    UserProfile,
)
from maru.domain import SEED_ACCESS_EMAIL, Role
from maru.projects.models import Application, ApplicationVersion, Subproject


@pytest.mark.django_db
def test_seed_maru_creates_admin_access_grant() -> None:
    call_command("seed_maru")

    grant = AccessGrant.objects.get(email=SEED_ACCESS_EMAIL)

    assert grant.active
    assert grant.can_start_project
    assert grant.role_names == {
        Role.ADMIN.value,
        Role.BOARD.value,
        Role.EVENT_MANAGER.value,
    }


def test_google_email_validation() -> None:
    assert is_google_email("Marton.Pornoi@gmail.com")
    assert is_google_email("person@googlemail.com")
    assert not is_google_email("person@example.org")


@pytest.mark.django_db
def test_seeded_user_can_log_in(client) -> None:
    call_command("seed_maru")

    response = client.post(
        reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL}, follow=True
    )

    assert response.status_code == 200
    assert "My Events" in response.content.decode()
    assert get_user_model().objects.filter(email=SEED_ACCESS_EMAIL).exists()


@pytest.mark.django_db
def test_non_allowlisted_google_user_cannot_log_in(client) -> None:
    response = client.post(
        reverse("accounts:login"), {"email": "someone@gmail.com"}, follow=True
    )

    assert response.status_code == 200
    assert "not on the access list" in response.content.decode()


@pytest.mark.django_db
def test_non_google_user_cannot_log_in(client) -> None:
    response = client.post(
        reverse("accounts:login"), {"email": "someone@example.org"}, follow=True
    )

    assert response.status_code == 200
    assert "Use a Gmail or Googlemail address" in response.content.decode()


@pytest.mark.django_db
@override_settings(
    MARU_DEV_LOGIN_ENABLED=False,
)
def test_development_login_can_be_disabled(client) -> None:
    call_command("seed_maru")

    response = client.post(
        reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL}, follow=True
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert "Development email login is disabled" in content
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
@override_settings(
    MARU_GOOGLE_OAUTH_CLIENT_ID="client-id",
    MARU_GOOGLE_OAUTH_CLIENT_SECRET="client-secret",
    MARU_GOOGLE_OAUTH_REDIRECT_URI="http://testserver/oauth/google/callback/",
)
def test_google_oauth_start_redirects_to_google_and_stores_state(client) -> None:
    response = client.get(reverse("accounts:google_login_start"))

    assert response.status_code == 302
    redirect = urlparse(response["Location"])
    params = parse_qs(redirect.query)
    assert redirect.scheme == "https"
    assert redirect.netloc == "accounts.google.com"
    assert params["client_id"] == ["client-id"]
    assert params["redirect_uri"] == ["http://testserver/oauth/google/callback/"]
    assert params["response_type"] == ["code"]
    assert params["scope"] == ["openid email profile"]
    assert params["state"] == [client.session["google_oauth_state"]]


@pytest.mark.django_db
@override_settings(
    MARU_GOOGLE_OAUTH_CLIENT_ID="client-id",
    MARU_GOOGLE_OAUTH_CLIENT_SECRET="client-secret",
)
def test_allowlisted_google_oauth_identity_can_log_in(client) -> None:
    call_command("seed_maru")
    _set_google_oauth_state(client, "state-token")

    with patch(
        "maru.accounts.views.exchange_google_code_for_identity",
        return_value=GoogleIdentity(email=SEED_ACCESS_EMAIL, email_verified=True),
    ) as exchange:
        response = client.get(
            reverse("accounts:google_oauth_callback"),
            {"code": "auth-code", "state": "state-token"},
            follow=True,
        )

    assert response.status_code == 200
    assert "My Events" in response.content.decode()
    assert get_user_model().objects.filter(email=SEED_ACCESS_EMAIL).exists()
    exchange.assert_called_once()


@pytest.mark.django_db
@override_settings(
    MARU_GOOGLE_OAUTH_CLIENT_ID="client-id",
    MARU_GOOGLE_OAUTH_CLIENT_SECRET="client-secret",
)
def test_non_allowlisted_google_oauth_identity_cannot_log_in(client) -> None:
    _set_google_oauth_state(client, "state-token")

    with patch(
        "maru.accounts.views.exchange_google_code_for_identity",
        return_value=GoogleIdentity(email="someone@gmail.com", email_verified=True),
    ):
        response = client.get(
            reverse("accounts:google_oauth_callback"),
            {"code": "auth-code", "state": "state-token"},
            follow=True,
        )

    content = response.content.decode()
    assert response.status_code == 200
    assert "not on the access list" in content
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
@override_settings(
    MARU_GOOGLE_OAUTH_CLIENT_ID="client-id",
    MARU_GOOGLE_OAUTH_CLIENT_SECRET="client-secret",
)
def test_google_oauth_callback_rejects_invalid_state(client) -> None:
    _set_google_oauth_state(client, "state-token")

    response = client.get(
        reverse("accounts:google_oauth_callback"),
        {"code": "auth-code", "state": "wrong-token"},
        follow=True,
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert "Could not verify Google sign-in state" in content
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
@override_settings(
    MARU_GOOGLE_OAUTH_CLIENT_ID="client-id",
    MARU_GOOGLE_OAUTH_CLIENT_SECRET="client-secret",
)
def test_google_oauth_callback_rejects_unverified_email(client) -> None:
    _set_google_oauth_state(client, "state-token")

    with patch(
        "maru.accounts.views.exchange_google_code_for_identity",
        return_value=GoogleIdentity(email=SEED_ACCESS_EMAIL, email_verified=False),
    ):
        response = client.get(
            reverse("accounts:google_oauth_callback"),
            {"code": "auth-code", "state": "state-token"},
            follow=True,
        )

    content = response.content.decode()
    assert response.status_code == 200
    assert "Google did not verify this email address" in content
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_admin_can_view_access_grants_with_statuses(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    user = get_user_model().objects.get(email=SEED_ACCESS_EMAIL)
    user.last_login = timezone.now()
    user.save(update_fields=["last_login"])
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.profile_unlocked = True
    profile.save(update_fields=["profile_unlocked"])

    response = client.get(reverse("accounts:access_grant_list"))

    content = response.content.decode()
    assert response.status_code == 200
    assert SEED_ACCESS_EMAIL in content
    assert "Admin" in content
    assert "Unlocked" in content
    assert "Accounts" in content


@pytest.mark.django_db
def test_admin_can_filter_audit_logs_by_account(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    _access_audit_log("alpha.target@gmail.com", actor_email=SEED_ACCESS_EMAIL)
    _access_audit_log("beta.target@gmail.com", actor_email=SEED_ACCESS_EMAIL)

    response = client.get(
        reverse("accounts:access_grant_list"),
        {"audit_account": "alpha"},
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert "alpha.target@gmail.com" in content
    assert "beta.target@gmail.com" not in content


@pytest.mark.django_db
def test_admin_can_filter_audit_logs_by_actor(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    _access_audit_log("alpha.target@gmail.com", actor_email="first.admin@gmail.com")
    _access_audit_log("beta.target@gmail.com", actor_email="second.admin@gmail.com")

    response = client.get(
        reverse("accounts:access_grant_list"),
        {"audit_actor": "second"},
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert "second.admin@gmail.com" in content
    assert "first.admin@gmail.com" not in content


@pytest.mark.django_db
def test_admin_can_filter_audit_logs_by_action(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    _access_audit_log(
        "created.target@gmail.com",
        action=AccessGrantAuditLog.ACTION_CREATED,
    )
    _access_audit_log(
        "locked.target@gmail.com",
        action=AccessGrantAuditLog.ACTION_PROFILE_LOCKED,
    )

    response = client.get(
        reverse("accounts:access_grant_list"),
        {"audit_action": AccessGrantAuditLog.ACTION_PROFILE_LOCKED},
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert "locked.target@gmail.com" in content
    assert "created.target@gmail.com" not in content
    assert "Profile locked" in content


@pytest.mark.django_db
def test_admin_can_filter_access_grants_by_email(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    _create_access_user("host.alpha@gmail.com", [Role.HOST.value])
    _create_access_user("volunteer.beta@gmail.com", [Role.VOLUNTEER.value])

    response = client.get(reverse("accounts:access_grant_list"), {"q": "alpha"})

    content = response.content.decode()
    assert response.status_code == 200
    assert "host.alpha@gmail.com" in content
    assert "volunteer.beta@gmail.com" not in content


@pytest.mark.django_db
def test_admin_can_filter_access_grants_by_active_status(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    active_grant = _create_access_user("open.host@gmail.com", [Role.HOST.value])
    inactive_grant = _create_access_user(
        "closed.host@gmail.com", [Role.HOST.value]
    )
    inactive_grant.active = False
    inactive_grant.save(update_fields=["active"])

    response = client.get(
        reverse("accounts:access_grant_list"), {"active": "inactive"}
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert inactive_grant.email in content
    assert active_grant.email not in content


@pytest.mark.django_db
def test_admin_can_filter_access_grants_by_role(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    _create_access_user("host.alpha@gmail.com", [Role.HOST.value])
    _create_access_user("volunteer.beta@gmail.com", [Role.VOLUNTEER.value])

    response = client.get(
        reverse("accounts:access_grant_list"), {"role": Role.VOLUNTEER.value}
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert "volunteer.beta@gmail.com" in content
    assert "host.alpha@gmail.com" not in content


@pytest.mark.django_db
def test_admin_can_export_access_grants_as_csv(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    _create_access_user("host.alpha@gmail.com", [Role.HOST.value])

    response = client.get(reverse("accounts:export_access_grants"))

    rows = list(csv.DictReader(io.StringIO(response.content.decode())))
    host_row = next(row for row in rows if row["email"] == "host.alpha@gmail.com")
    seed_row = next(row for row in rows if row["email"] == SEED_ACCESS_EMAIL)
    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv"
    assert "maru-accounts.csv" in response["Content-Disposition"]
    assert host_row == {
        "active": "true",
        "email": "host.alpha@gmail.com",
        "notes": "",
        "roles": Role.HOST.value,
    }
    assert seed_row["active"] == "true"
    assert Role.ADMIN.value in seed_row["roles"]


@pytest.mark.django_db
def test_board_user_cannot_export_access_grants(client) -> None:
    _create_access_user("boarduser@gmail.com", [Role.BOARD.value])
    client.post(reverse("accounts:login"), {"email": "boarduser@gmail.com"})

    response = client.get(reverse("accounts:export_access_grants"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_admin_can_import_access_grants_from_csv(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    existing = _create_access_user("helper@gmail.com", [Role.REGISTERED_USER.value])

    response = client.post(
        reverse("accounts:import_access_grants"),
        {
            "csv_file": _account_csv(
                "\n".join(
                    [
                        "email,active,roles,notes",
                        "newhost@gmail.com,true,Host;Volunteer,Stage lead",
                        "helper@gmail.com,false,Volunteer,Check availability",
                    ]
                )
            )
        },
        follow=True,
    )

    new_grant = AccessGrant.objects.get(email="newhost@gmail.com")
    existing.refresh_from_db()
    content = response.content.decode()
    assert response.status_code == 200
    assert "1 created, 1 updated, 0 unchanged" in content
    assert new_grant.active
    assert new_grant.notes == "Stage lead"
    assert new_grant.role_names == {Role.HOST.value, Role.VOLUNTEER.value}
    assert not existing.active
    assert existing.notes == "Check availability"
    assert existing.role_names == {Role.VOLUNTEER.value}
    assert AccessGrantAuditLog.objects.filter(
        target_email="newhost@gmail.com",
        action=AccessGrantAuditLog.ACTION_CREATED,
    ).exists()
    assert AccessGrantAuditLog.objects.filter(
        target_email="helper@gmail.com",
        action=AccessGrantAuditLog.ACTION_UPDATED,
    ).exists()


@pytest.mark.django_db
def test_account_csv_import_validation_blocks_all_changes(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})

    response = client.post(
        reverse("accounts:import_access_grants"),
        {
            "csv_file": _account_csv(
                "\n".join(
                    [
                        "email,active,roles",
                        "validhost@gmail.com,true,Host",
                        "person@example.org,true,Host",
                        "badrole@gmail.com,true,Made Up",
                        "dupe@gmail.com,true,Host",
                        "dupe@gmail.com,false,Volunteer",
                    ]
                )
            )
        },
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert "Import blocked" in content
    assert "use a Gmail or Googlemail address" in content
    assert "invalid roles: Made Up" in content
    assert "duplicate email dupe@gmail.com" in content
    assert not AccessGrant.objects.filter(email="validhost@gmail.com").exists()
    assert not AccessGrantAuditLog.objects.exclude(
        target_email=SEED_ACCESS_EMAIL
    ).exists()


@pytest.mark.django_db
def test_board_user_cannot_import_access_grants(client) -> None:
    _create_access_user("boarduser@gmail.com", [Role.BOARD.value])
    client.post(reverse("accounts:login"), {"email": "boarduser@gmail.com"})

    response = client.get(reverse("accounts:import_access_grants"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_admin_can_unlock_profile_from_access_list(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    grant = _create_access_user("host.profile@gmail.com", [Role.HOST.value])
    user = get_user_model().objects.get(email=grant.email)
    profile = user.userprofile
    profile.profile_unlocked = False
    profile.save(update_fields=["profile_unlocked"])

    response = client.post(
        reverse("accounts:unlock_access_grant_profile", args=[grant.pk]),
        follow=True,
    )

    profile.refresh_from_db()
    audit_log = AccessGrantAuditLog.objects.get(target_email=grant.email)
    content = response.content.decode()
    assert response.status_code == 200
    assert profile.profile_unlocked
    assert "Profile unlocked" in content
    assert audit_log.action == AccessGrantAuditLog.ACTION_PROFILE_UNLOCKED
    assert audit_log.before["profile_unlocked"] is False
    assert audit_log.after["profile_unlocked"] is True
    assert Notification.objects.filter(
        user=user,
        title="Profile unlocked",
        link_url="/profile/edit/",
    ).exists()


@pytest.mark.django_db
def test_admin_can_lock_profile_from_access_list(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    grant = _create_access_user("host.profile@gmail.com", [Role.HOST.value])
    user = get_user_model().objects.get(email=grant.email)
    profile = user.userprofile
    profile.profile_unlocked = True
    profile.save(update_fields=["profile_unlocked"])

    response = client.post(
        reverse("accounts:lock_access_grant_profile", args=[grant.pk]),
        follow=True,
    )

    profile.refresh_from_db()
    audit_log = AccessGrantAuditLog.objects.get(target_email=grant.email)
    assert response.status_code == 200
    assert not profile.profile_unlocked
    assert audit_log.action == AccessGrantAuditLog.ACTION_PROFILE_LOCKED
    assert audit_log.before["profile_unlocked"] is True
    assert audit_log.after["profile_unlocked"] is False


@pytest.mark.django_db
def test_admin_cannot_unlock_profile_before_user_exists(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    grant = AccessGrant.objects.create(email="notloggedin@gmail.com")

    response = client.post(
        reverse("accounts:unlock_access_grant_profile", args=[grant.pk]),
        follow=True,
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert "has not logged in yet" in content
    assert not AccessGrantAuditLog.objects.filter(target_email=grant.email).exists()


@pytest.mark.django_db
def test_board_user_cannot_unlock_profiles(client) -> None:
    board_grant = _create_access_user("boarduser@gmail.com", [Role.BOARD.value])
    target_grant = _create_access_user("host.profile@gmail.com", [Role.HOST.value])
    client.post(reverse("accounts:login"), {"email": board_grant.email})

    response = client.post(
        reverse("accounts:unlock_access_grant_profile", args=[target_grant.pk])
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_board_user_cannot_manage_access_grants(client) -> None:
    _create_access_user("boarduser@gmail.com", [Role.BOARD.value])
    client.post(reverse("accounts:login"), {"email": "boarduser@gmail.com"})

    response = client.get(reverse("accounts:access_grant_list"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_admin_can_create_access_grant_with_roles_and_audit_log(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})

    response = client.post(
        reverse("accounts:create_access_grant"),
        {
            "email": "NewHost@gmail.com",
            "active": "on",
            "notes": "Good fit for late-night events.",
            "roles": [Role.HOST.value, Role.VOLUNTEER.value],
        },
        follow=True,
    )

    grant = AccessGrant.objects.get(email="newhost@gmail.com")
    audit_log = AccessGrantAuditLog.objects.get(target_email="newhost@gmail.com")
    assert response.status_code == 200
    assert grant.active
    assert grant.notes == "Good fit for late-night events."
    assert grant.role_names == {Role.HOST.value, Role.VOLUNTEER.value}
    assert audit_log.action == AccessGrantAuditLog.ACTION_CREATED
    assert audit_log.actor_email == SEED_ACCESS_EMAIL
    assert audit_log.before is None
    assert audit_log.after == {
        "active": True,
        "email": "newhost@gmail.com",
        "notes": "Good fit for late-night events.",
        "roles": [Role.HOST.value, Role.VOLUNTEER.value],
    }


@pytest.mark.django_db
def test_admin_can_update_access_grant_roles_and_audit_log(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    grant = _create_access_user("helper@gmail.com", [Role.REGISTERED_USER.value])

    response = client.post(
        reverse("accounts:edit_access_grant", args=[grant.pk]),
        {
            "email": "helper@gmail.com",
            "notes": "Prefers short shifts.",
            "roles": [Role.VOLUNTEER.value],
        },
        follow=True,
    )

    grant.refresh_from_db()
    audit_log = AccessGrantAuditLog.objects.get(target_email="helper@gmail.com")
    assert response.status_code == 200
    assert not grant.active
    assert grant.notes == "Prefers short shifts."
    assert grant.role_names == {Role.VOLUNTEER.value}
    assert audit_log.action == AccessGrantAuditLog.ACTION_UPDATED
    assert audit_log.before == {
        "active": True,
        "email": "helper@gmail.com",
        "notes": "",
        "roles": [Role.REGISTERED_USER.value],
    }
    assert audit_log.after == {
        "active": False,
        "email": "helper@gmail.com",
        "notes": "Prefers short shifts.",
        "roles": [Role.VOLUNTEER.value],
    }


@pytest.mark.django_db
def test_access_grant_form_requires_google_email(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})

    response = client.post(
        reverse("accounts:create_access_grant"),
        {
            "email": "person@example.org",
            "active": "on",
            "roles": [Role.HOST.value],
        },
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert "Use a Gmail or Googlemail address" in content
    assert not AccessGrant.objects.filter(email="person@example.org").exists()


@pytest.mark.django_db
def test_admin_can_view_access_grant_audit_detail(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    grant = _create_access_user("helper@gmail.com", [Role.REGISTERED_USER.value])
    actor = get_user_model().objects.get(email=SEED_ACCESS_EMAIL)
    audit_log = AccessGrantAuditLog.objects.create(
        grant=grant,
        actor=actor,
        actor_email=actor.email,
        target_email=grant.email,
        action=AccessGrantAuditLog.ACTION_UPDATED,
        before={
            "active": True,
            "email": grant.email,
            "notes": "",
            "roles": [Role.REGISTERED_USER.value],
        },
        after={
            "active": True,
            "email": grant.email,
            "notes": "",
            "roles": [Role.VOLUNTEER.value],
        },
    )

    response = client.get(
        reverse("accounts:access_grant_audit_log_detail", args=[audit_log.pk])
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert "Account Change" in content
    assert "helper@gmail.com" in content
    assert "Registered User" in content
    assert "Volunteer" in content


@pytest.mark.django_db
def test_board_user_cannot_view_access_grant_audit_detail(client) -> None:
    grant = _create_access_user("boarduser@gmail.com", [Role.BOARD.value])
    audit_log = AccessGrantAuditLog.objects.create(
        grant=grant,
        actor_email="marton.pornoi@gmail.com",
        target_email=grant.email,
        action=AccessGrantAuditLog.ACTION_CREATED,
        after={
            "active": True,
            "email": grant.email,
            "notes": "",
            "roles": [Role.BOARD.value],
        },
    )
    client.post(reverse("accounts:login"), {"email": "boarduser@gmail.com"})

    response = client.get(
        reverse("accounts:access_grant_audit_log_detail", args=[audit_log.pk])
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_my_events_splits_current_applications_from_history(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    subproject = Subproject.objects.get(
        project__slug="awoostria-2026", slug="events"
    )
    submitted = _application(subproject, "Active Cooling", "submitted")
    approved = _application(subproject, "Approved Dance Panel", "approved")

    response = client.get(reverse("accounts:my_events"))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Current Applications" in content
    assert "Application History" in content
    assert _appears_after(content, "Current Applications", submitted.title)
    assert _appears_after(content, "Application History", approved.title)
    assert _appears_after(content, approved.title, "approved")
    assert _appears_after(content, approved.title, "1")


@pytest.mark.django_db
def test_my_events_groups_archived_participation_by_year_and_project(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    user = get_user_model().objects.get(email=SEED_ACCESS_EMAIL)
    ArchivedParticipation.objects.create(
        user=user,
        year=2025,
        project_name="Cozy Furcon",
        panel_title="Fursuit Lounge Basics",
    )
    ArchivedParticipation.objects.create(
        user=user,
        year=2025,
        project_name="Cozy Furcon",
        panel_title="Dance Floor Etiquette",
    )

    response = client.get(reverse("accounts:my_events"))

    content = response.content.decode()
    assert response.status_code == 200
    assert "2025 · Cozy Furcon" in content
    assert "Fursuit Lounge Basics" in content
    assert "Dance Floor Etiquette" in content


@pytest.mark.django_db
def test_user_can_mark_notification_read_from_my_events(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    user = get_user_model().objects.get(email=SEED_ACCESS_EMAIL)
    notification = Notification.objects.create(
        user=user,
        title="Application approved",
        body="Your application was approved.",
        link_url="/my-events/",
        link_label="Open My Events",
    )

    response = client.get(reverse("accounts:my_events"))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Unread" in content
    assert "Application approved" in content
    assert "Open My Events" in content
    assert "Mark read" in content

    response = client.post(
        reverse("accounts:mark_notification_read", args=[notification.pk]),
        follow=True,
    )

    notification.refresh_from_db()
    content = response.content.decode()
    assert response.status_code == 200
    assert notification.read_at is not None
    assert "Read" in content
    assert "Open My Events" in content


@pytest.mark.django_db
def test_user_cannot_mark_another_users_notification_read(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    other = get_user_model().objects.create(username="other", email="other@gmail.com")
    notification = Notification.objects.create(
        user=other,
        title="Private notice",
    )

    response = client.post(
        reverse("accounts:mark_notification_read", args=[notification.pk])
    )

    notification.refresh_from_db()
    assert response.status_code == 404
    assert notification.read_at is None


def _application(subproject: Subproject, title: str, status: str) -> Application:
    user = get_user_model().objects.get(email=SEED_ACCESS_EMAIL)
    application = Application.objects.create(
        subproject=subproject,
        applicant=user,
        title=title,
        status=status,
    )
    ApplicationVersion.objects.create(
        application=application,
        version=1,
        answers={"Display - Title": title},
    )
    return application


def _appears_after(content: str, first: str, second: str) -> bool:
    first_index = content.find(first)
    second_index = content.find(second, first_index + len(first))
    return first_index != -1 and second_index != -1


def _set_google_oauth_state(client, state: str) -> None:
    session = client.session
    session["google_oauth_state"] = state
    session.save()


def _create_access_user(email: str, roles: list[str]) -> AccessGrant:
    grant = AccessGrant.objects.create(email=email)
    for role in roles:
        AccessRole.objects.create(grant=grant, role=role)
    user = get_user_model().objects.create(username=email, email=email)
    UserProfile.objects.get_or_create(user=user)
    return grant


def _access_audit_log(
    target_email: str,
    *,
    action: str = AccessGrantAuditLog.ACTION_UPDATED,
    actor_email: str = "marton.pornoi@gmail.com",
) -> AccessGrantAuditLog:
    return AccessGrantAuditLog.objects.create(
        actor_email=actor_email,
        target_email=target_email,
        action=action,
        before={"active": True, "email": target_email, "notes": "", "roles": []},
        after={"active": True, "email": target_email, "notes": "", "roles": []},
    )


def _account_csv(content: str) -> SimpleUploadedFile:
    return SimpleUploadedFile(
        "accounts.csv",
        f"{content}\n".encode(),
        content_type="text/csv",
    )
