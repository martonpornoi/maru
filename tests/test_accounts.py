from __future__ import annotations

import csv
import io
from datetime import timedelta
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
    UserConventionProfile,
    UserProfile,
    UserTileColorRule,
)
from maru.domain import SEED_ACCESS_EMAIL, Role, VolunteerType
from maru.projects.models import Application, ApplicationVersion, Project, Subproject


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
    assert (
        "Your profile, notifications, applications, archive, and shifts"
        in response.content.decode()
    )
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
    assert (
        "Your profile, notifications, applications, archive, and shifts"
        in response.content.decode()
    )
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
def test_admin_can_view_user_directory_with_images_and_names_only(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    host_grant = _create_access_user(
        "hostpicture@gmail.com",
        [Role.HOST.value, Role.VOLUNTEER.value],
    )
    host_user = get_user_model().objects.get(email=host_grant.email)
    host_profile = UserProfile.objects.get(user=host_user)
    host_profile.display_name = "Picture Host"
    host_profile.profile_picture = "profiles/profile-pictures/picture-host.png"
    host_profile.profile_unlocked = True
    host_profile.save(
        update_fields=["display_name", "profile_picture", "profile_unlocked"]
    )
    pending_grant = AccessGrant.objects.create(email="pendinguser@gmail.com")
    AccessRole.objects.create(grant=pending_grant, role=Role.SECURITY.value)

    response = client.get(reverse("accounts:user_directory"))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Users" in content
    assert "Admin" in content
    assert "Manage accounts" in content
    assert reverse("accounts:access_grant_list") in content
    assert reverse("accounts:create_access_grant") in content
    assert reverse("accounts:import_access_grants") in content
    assert reverse("accounts:export_access_grants") in content
    assert "Picture Host" in content
    assert "hostpicture@gmail.com" not in content
    assert "Volunteer" not in content
    assert "/media/profiles/profile-pictures/picture-host.png" in content
    assert "pendinguser@gmail.com" not in content
    assert "Security" not in content
    assert "Pending user" in content
    assert "/static/accounts/default-avatar.svg" in content
    assert reverse("accounts:profile_detail", args=[host_profile.pk]) in content


@pytest.mark.django_db
def test_regular_user_can_view_user_directory_under_public_navigation(client) -> None:
    _create_access_user("regularuser@gmail.com", [Role.REGISTERED_USER.value])
    host_grant = _create_access_user("hostuser@gmail.com", [Role.HOST.value])
    host_profile = UserProfile.objects.get(user__email=host_grant.email)
    host_profile.display_name = "Host User"
    host_profile.save(update_fields=["display_name"])
    client.post(reverse("accounts:login"), {"email": "regularuser@gmail.com"})

    response = client.get(reverse("accounts:user_directory"))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Users" in content
    assert "Statistics" in content
    assert "Manage accounts" not in content
    assert "Host User" in content
    assert "hostuser@gmail.com" not in content
    assert "Host</span>" not in content


@pytest.mark.django_db
def test_project_user_directory_only_shows_users_attached_to_project(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    awoostria = Project.objects.get(slug="awoostria-2026")
    cozy = Project.objects.get(slug="cozy-furcon-2025")
    awoostria_grant = _create_access_user(
        "awoostria.user@gmail.com",
        [Role.REGISTERED_USER.value],
    )
    cozy_grant = _create_access_user(
        "cozy.user@gmail.com",
        [Role.REGISTERED_USER.value],
    )
    awoostria_user = get_user_model().objects.get(email=awoostria_grant.email)
    cozy_user = get_user_model().objects.get(email=cozy_grant.email)
    UserProfile.objects.filter(user=awoostria_user).update(
        display_name="Awoostria User"
    )
    UserProfile.objects.filter(user=cozy_user).update(display_name="Cozy User")
    UserConventionProfile.objects.create(user=awoostria_user, project=awoostria)
    UserConventionProfile.objects.create(user=cozy_user, project=cozy)

    response = client.get(
        reverse("accounts:project_user_directory", args=[awoostria.slug])
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert "Awoostria 2026 Users" in content
    assert "Awoostria User" in content
    assert "Cozy User" not in content
    assert "All users ever registered" not in content


@pytest.mark.django_db
def test_user_directory_renders_square_tiles_with_layered_colors(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    project = Project.objects.get(slug="awoostria-2026")
    host = get_user_model().objects.get(email="cooling.host@gmail.com")
    UserConventionProfile.objects.update_or_create(
        user=host,
        project=project,
        defaults={
            "attendee_type": "Fursuiter",
            "volunteer_type": VolunteerType.LEAD.value,
            "roles": [Role.VOLUNTEER.value],
        },
    )
    UserTileColorRule.objects.create(
        target_type=UserTileColorRule.ATTENDEE_TYPE,
        target_value="Fursuiter",
        applies_to=UserTileColorRule.EDGE,
        background_color="#654321",
        priority=100,
    )
    UserTileColorRule.objects.create(
        target_type=UserTileColorRule.VOLUNTEER_TYPE,
        target_value=VolunteerType.LEAD.value,
        applies_to=UserTileColorRule.INTERIOR,
        background_color="#123456",
        priority=100,
    )

    response = client.get(reverse("accounts:user_directory"))

    content = response.content.decode()
    assert response.status_code == 200
    assert "user-tile" in content
    assert "border-color: #654321;" in content
    assert "background: #123456; color: #ffffff;" in content
    assert "Lead" not in content
    assert "Volunteer" not in content
    assert "Fursuiter" not in content


@pytest.mark.django_db
def test_setup_users_can_manage_user_tile_color_rules(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})

    response = client.post(
        reverse("accounts:user_tile_color_rules"),
        {
            "target": "attendee_type:Fursuiter",
            "applies_to": UserTileColorRule.EDGE,
            "background_color": "#112233",
            "priority": "5",
            "active": "on",
        },
        follow=True,
    )

    rule = UserTileColorRule.objects.get(target_value="Fursuiter")
    content = response.content.decode()
    assert response.status_code == 200
    assert rule.target_type == UserTileColorRule.ATTENDEE_TYPE
    assert rule.applies_to == UserTileColorRule.EDGE
    assert rule.background_color == "#112233"
    assert "User tile color rule saved" in content
    assert "Edge #112233" in content
    assert "Color Codes" in content

    response = client.post(
        reverse("accounts:user_tile_color_rules"),
        {
            "target": f"volunteer_type:{VolunteerType.DEPUTY.value}",
            "applies_to": UserTileColorRule.INTERIOR,
            "background_color": "#ddffee",
            "priority": "3",
            "active": "on",
        },
        follow=True,
    )

    rule = UserTileColorRule.objects.get(target_value=VolunteerType.DEPUTY.value)
    assert response.status_code == 200
    assert rule.target_type == UserTileColorRule.VOLUNTEER_TYPE
    assert rule.applies_to == UserTileColorRule.INTERIOR


@pytest.mark.django_db
def test_regular_user_cannot_manage_user_tile_color_rules(client) -> None:
    _create_access_user("regularuser@gmail.com", [Role.REGISTERED_USER.value])
    client.post(reverse("accounts:login"), {"email": "regularuser@gmail.com"})

    response = client.get(reverse("accounts:user_tile_color_rules"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_statistics_show_attendee_counts_by_project_country_and_type(client) -> None:
    call_command("seed_demo")
    viewer_grant = _create_access_user(
        "statsviewer@gmail.com",
        [Role.REGISTERED_USER.value],
    )
    project = Project.objects.get(slug="awoostria-2026")
    host = get_user_model().objects.get(email="cooling.host@gmail.com")
    host_profile = UserProfile.objects.get(user=host)
    host_profile.country = "HU"
    host_profile.save(update_fields=["country"])
    UserConventionProfile.objects.create(
        user=host,
        project=project,
        attendee_type="Fursuiter",
        roles=[Role.HOST.value],
    )
    client.post(reverse("accounts:login"), {"email": viewer_grant.email})

    response = client.get(reverse("accounts:statistics"))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Awoostria 2026" in content
    assert "Fursuiter" in content
    assert "Hungary" in content


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
def test_admin_account_audit_logs_are_paginated(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    base_time = timezone.now()
    for index in range(30):
        audit_log = _access_audit_log(f"page-{index:02d}.target@gmail.com")
        AccessGrantAuditLog.objects.filter(pk=audit_log.pk).update(
            created_at=base_time + timedelta(minutes=index)
        )

    response = client.get(
        reverse("accounts:access_grant_list"),
        {"audit_page": "2"},
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert "Page 2 of 2" in content
    assert "page-04.target@gmail.com" in content
    assert "page-05.target@gmail.com" not in content
    assert "Previous" in content


@pytest.mark.django_db
def test_admin_account_audit_pagination_preserves_filters(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    for index in range(26):
        _access_audit_log(
            f"filtered-{index:02d}.target@gmail.com",
            actor_email="audit.admin@gmail.com",
        )
    _access_audit_log(
        "other.target@gmail.com",
        actor_email="other.admin@gmail.com",
    )

    response = client.get(
        reverse("accounts:access_grant_list"),
        {"audit_actor": "audit.admin@gmail.com"},
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert "audit_actor=audit.admin%40gmail.com&amp;audit_page=2" in content
    assert "other.admin@gmail.com" not in content


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
def test_admin_can_filter_access_grants_by_unlocked_profiles(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    locked_grant = _create_access_user("closed.host@gmail.com", [Role.HOST.value])
    unlocked_grant = _create_access_user("open.host@gmail.com", [Role.HOST.value])
    user = get_user_model().objects.get(email=unlocked_grant.email)
    profile = UserProfile.objects.get(user=user)
    profile.profile_unlocked = True
    profile.save(update_fields=["profile_unlocked"])

    response = client.get(
        reverse("accounts:access_grant_list"), {"profile_state": "unlocked"}
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert unlocked_grant.email in content
    assert locked_grant.email not in content


@pytest.mark.django_db
def test_admin_can_filter_access_grants_by_locked_profiles(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    locked_grant = _create_access_user("closed.host@gmail.com", [Role.HOST.value])
    unlocked_grant = _create_access_user("open.host@gmail.com", [Role.HOST.value])
    user = get_user_model().objects.get(email=unlocked_grant.email)
    profile = UserProfile.objects.get(user=user)
    profile.profile_unlocked = True
    profile.save(update_fields=["profile_unlocked"])

    response = client.get(
        reverse("accounts:access_grant_list"), {"profile_state": "locked"}
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert locked_grant.email in content
    assert unlocked_grant.email not in content


@pytest.mark.django_db
def test_admin_can_filter_access_grants_by_missing_user_profiles(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    user_grant = _create_access_user("known.host@gmail.com", [Role.HOST.value])
    pending_grant = AccessGrant.objects.create(email="pending.host@gmail.com")
    AccessRole.objects.create(grant=pending_grant, role=Role.HOST.value)

    response = client.get(
        reverse("accounts:access_grant_list"), {"profile_state": "no_user"}
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert pending_grant.email in content
    assert user_grant.email not in content


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
    csv_content = "\n".join(
        [
            "email,active,roles,notes",
            "newhost@gmail.com,true,Host;Volunteer,Stage lead",
            "helper@gmail.com,false,Volunteer,Check availability",
        ]
    )

    response = client.post(
        reverse("accounts:import_access_grants"),
        {"csv_file": _account_csv(csv_content)},
    )

    content = response.content.decode()
    existing.refresh_from_db()
    assert response.status_code == 200
    assert "Validation Report" in content
    assert "Created: 1" in content
    assert "Updated: 1" in content
    assert "Changes" in content
    assert "Active: true -> false" in content
    assert "Roles: Registered User -> Volunteer" in content
    assert "Notes: - -> Check availability" in content
    assert "Apply import" in content
    assert not AccessGrant.objects.filter(email="newhost@gmail.com").exists()
    assert existing.active
    assert existing.notes == ""

    response = client.post(
        reverse("accounts:import_access_grants"),
        {
            "action": "apply",
            "csv_content": f"{csv_content}\n",
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
    assert "Rejected: 3" in content
    assert "Apply import" not in content
    assert "Download rejected rows" in content
    assert not AccessGrant.objects.filter(email="validhost@gmail.com").exists()
    assert not AccessGrantAuditLog.objects.exclude(
        target_email=SEED_ACCESS_EMAIL
    ).exists()


@pytest.mark.django_db
def test_admin_can_download_rejected_account_import_rows(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    csv_content = "\n".join(
        [
            "email,active,roles,notes",
            "validhost@gmail.com,true,Host,Ready",
            "person@example.org,true,Host,Bad domain",
            "badrole@gmail.com,true,Made Up,Bad role",
        ]
    )

    response = client.post(
        reverse("accounts:import_access_grants"),
        {
            "action": "download_rejected",
            "csv_content": csv_content,
        },
    )

    rows = list(csv.DictReader(io.StringIO(response.content.decode())))
    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv"
    assert "maru-rejected-accounts.csv" in response["Content-Disposition"]
    assert rows == [
        {
            "active": "true",
            "email": "person@example.org",
            "issues": "use a Gmail or Googlemail address",
            "line": "3",
            "notes": "Bad domain",
            "roles": Role.HOST.value,
        },
        {
            "active": "true",
            "email": "badrole@gmail.com",
            "issues": "invalid roles: Made Up",
            "line": "4",
            "notes": "Bad role",
            "roles": "Made Up",
        },
    ]
    assert not AccessGrant.objects.filter(email="validhost@gmail.com").exists()


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
def test_admin_can_view_access_grant_history_grouped_by_account(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    grant = _create_access_user("history.target@gmail.com", [Role.HOST.value])
    first_log = _access_audit_log(
        grant.email,
        action=AccessGrantAuditLog.ACTION_CREATED,
        actor_email=SEED_ACCESS_EMAIL,
        grant=grant,
    )
    second_log = _access_audit_log(
        grant.email,
        action=AccessGrantAuditLog.ACTION_UPDATED,
        actor_email="other.admin@gmail.com",
        grant=grant,
    )
    _access_audit_log("other.target@gmail.com", actor_email=SEED_ACCESS_EMAIL)

    response = client.get(reverse("accounts:access_grant_history", args=[grant.pk]))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Account History" in content
    assert grant.email in content
    assert first_log.action in content
    assert second_log.action in content
    assert "other.admin@gmail.com" in content
    assert "other.target@gmail.com" not in content


@pytest.mark.django_db
def test_account_list_links_to_access_grant_history(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    grant = _create_access_user("history.target@gmail.com", [Role.HOST.value])
    _access_audit_log(grant.email, grant=grant)

    response = client.get(reverse("accounts:access_grant_list"))

    content = response.content.decode()
    history_url = reverse("accounts:access_grant_history", args=[grant.pk])
    assert response.status_code == 200
    assert history_url in content
    assert "History" in content


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
def test_board_user_cannot_view_access_grant_history(client) -> None:
    board_grant = _create_access_user("boarduser@gmail.com", [Role.BOARD.value])
    target_grant = _create_access_user("history.target@gmail.com", [Role.HOST.value])
    client.post(reverse("accounts:login"), {"email": board_grant.email})

    response = client.get(
        reverse("accounts:access_grant_history", args=[target_grant.pk])
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
    first_archive = ArchivedParticipation.objects.create(
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
    assert reverse(
        "accounts:archived_participation_detail", args=[first_archive.pk]
    ) in content


@pytest.mark.django_db
def test_user_can_open_own_archived_participation_detail(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    user = get_user_model().objects.get(email=SEED_ACCESS_EMAIL)
    item = ArchivedParticipation.objects.create(
        user=user,
        year=2025,
        project_name="Cozy Furcon",
        panel_title="Fursuit Lounge Basics",
    )

    response = client.get(
        reverse("accounts:archived_participation_detail", args=[item.pk])
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert "Archived panel record" in content
    assert "Cozy Furcon" in content
    assert "Fursuit Lounge Basics" in content


@pytest.mark.django_db
def test_user_cannot_open_another_users_archived_participation_detail(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    other = get_user_model().objects.create(username="other", email="other@gmail.com")
    item = ArchivedParticipation.objects.create(
        user=other,
        year=2025,
        project_name="Cozy Furcon",
        panel_title="Private Archive Panel",
    )

    response = client.get(
        reverse("accounts:archived_participation_detail", args=[item.pk])
    )

    assert response.status_code == 404


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
    grant: AccessGrant | None = None,
) -> AccessGrantAuditLog:
    return AccessGrantAuditLog.objects.create(
        grant=grant,
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
