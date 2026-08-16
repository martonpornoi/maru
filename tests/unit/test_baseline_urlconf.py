from uuid import UUID

import pytest
from django.test import override_settings
from django.urls import Resolver404, resolve, reverse


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_baseline_mounts_the_shipped_platform_workflows() -> None:
    invitation_id = UUID("11111111-1111-4111-8111-111111111111")
    delivery_id = UUID("22222222-2222-4222-8222-222222222222")
    cases = (
        (
            "accept-platform-account-invitation",
            {},
            "/accounts/invitations/accept/",
        ),
        ("account-step-up", {}, "/admin/account/step-up/"),
        (
            "page-access-workspace",
            {"scope_token": "synthetic-scope"},
            "/admin/access/synthetic-scope/",
        ),
        ("platform-account-inventory", {}, "/admin/platform/accounts/"),
        ("platform-account-invite", {}, "/admin/platform/accounts/invite/"),
        (
            "platform-account-invitation-detail",
            {"invitation_id": invitation_id},
            f"/admin/platform/accounts/invitations/{invitation_id}/",
        ),
        (
            "platform-account-invitation-reissue",
            {"invitation_id": invitation_id},
            f"/admin/platform/accounts/invitations/{invitation_id}/reissue/",
        ),
        (
            "platform-account-invitation-revoke",
            {"invitation_id": invitation_id},
            f"/admin/platform/accounts/invitations/{invitation_id}/revoke/",
        ),
        (
            "platform-identity-delivery-resolve-delivered",
            {"invitation_id": invitation_id, "delivery_id": delivery_id},
            (
                f"/admin/platform/accounts/invitations/{invitation_id}/"
                f"deliveries/{delivery_id}/resolve-delivered/"
            ),
        ),
        (
            "platform-identity-delivery-resolve-retry",
            {"invitation_id": invitation_id, "delivery_id": delivery_id},
            (
                f"/admin/platform/accounts/invitations/{invitation_id}/"
                f"deliveries/{delivery_id}/resolve-retry/"
            ),
        ),
    )

    for route_name, kwargs, expected_path in cases:
        assert reverse(route_name, kwargs=kwargs) == expected_path
        assert resolve(expected_path).url_name == route_name


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_baseline_keeps_interactive_api_documentation_unmounted() -> None:
    for path in ("/api/v1/docs/", "/api/v1/redoc/"):
        with pytest.raises(Resolver404):
            resolve(path)
