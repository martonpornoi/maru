from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
)
from tests.support.isolation import (
    EndpointIsolationCase,
    assert_endpoint_isolation,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _client(account: object | None = None) -> APIClient:
    client = APIClient()
    if account is not None:
        client.force_authenticate(account)
    return client


def test_reference_read_endpoints_use_the_reusable_isolation_matrix() -> None:
    first = EventEditionFactory(name="Pawprint Spring")
    second = EventEditionFactory(
        organization=first.organization,
        series=first.series,
        name="Pawprint Autumn",
    )
    protected = EventEditionFactory(name="Protected Other Organizer Edition")
    authorized = AccountFactory()
    CapabilityGrantFactory(
        principal=authorized,
        organization=first.organization,
    )
    edition_only = AccountFactory()
    CapabilityGrantFactory(
        principal=edition_only,
        organization=first.organization,
        edition=first,
    )
    wrong_tenant = AccountFactory()
    CapabilityGrantFactory(
        principal=wrong_tenant,
        organization=protected.organization,
    )
    inactive = AccountFactory()
    now = timezone.now()
    CapabilityGrantFactory(
        principal=inactive,
        organization=first.organization,
        effective_from=now - timedelta(days=2),
        expires_at=now - timedelta(days=1),
    )
    CapabilityGrantFactory(
        principal=inactive,
        organization=first.organization,
        effective_from=now - timedelta(days=1),
        revoked_at=now,
    )
    unauthorized = AccountFactory()
    list_url = f"/api/v1/organizations/{first.organization_id}/editions"
    detail_url = f"{list_url}/{first.id}"
    protected_values = (str(protected.id), protected.name)

    assert_endpoint_isolation(
        [
            EndpointIsolationCase(
                name="anonymous list",
                request=lambda: _client().get(list_url, {"search": "Pawprint"}),
                expected_status=403,
                expected_code="not_authenticated",
                forbidden_values=protected_values,
            ),
            EndpointIsolationCase(
                name="authorized tenant list, search, and count",
                request=lambda: _client(authorized).get(
                    list_url,
                    {"search": "Autumn"},
                ),
                expected_status=200,
                forbidden_values=protected_values,
            ),
            EndpointIsolationCase(
                name="edition grant cannot broaden into a list",
                request=lambda: _client(edition_only).get(list_url),
                expected_status=403,
                expected_code="permission_absent",
                forbidden_values=protected_values,
            ),
            EndpointIsolationCase(
                name="ordinary same-tenant account list",
                request=lambda: _client(unauthorized).get(list_url),
                expected_status=403,
                expected_code="permission_absent",
                forbidden_values=protected_values,
            ),
            EndpointIsolationCase(
                name="similarly privileged other-tenant list",
                request=lambda: _client(wrong_tenant).get(list_url),
                expected_status=403,
                expected_code="permission_absent",
                forbidden_values=protected_values,
            ),
            EndpointIsolationCase(
                name="expired and revoked list authority",
                request=lambda: _client(inactive).get(list_url),
                expected_status=403,
                expected_code="permission_absent",
                forbidden_values=protected_values,
            ),
            EndpointIsolationCase(
                name="authorized exact detail",
                request=lambda: _client(authorized).get(detail_url),
                expected_status=200,
                forbidden_values=protected_values,
            ),
        ]
    )

    search = _client(authorized).get(list_url, {"search": "Autumn"})
    assert search.json()["count"] == 1
    assert search.json()["results"][0]["id"] == str(second.id)


def test_cross_tenant_and_unknown_detail_have_the_same_safe_shape() -> None:
    first = EventEditionFactory()
    protected = EventEditionFactory(name="Protected Other Organizer Edition")
    account = AccountFactory()
    CapabilityGrantFactory(
        principal=account,
        organization=first.organization,
    )
    base_url = f"/api/v1/organizations/{first.organization_id}/editions"
    client = _client(account)

    cross_tenant = client.get(f"{base_url}/{protected.id}")
    unknown = client.get(f"{base_url}/{uuid4()}")

    assert cross_tenant.status_code == 404
    assert unknown.status_code == 404
    cross_body = cross_tenant.json()
    unknown_body = unknown.json()
    cross_body.pop("request_id")
    unknown_body.pop("request_id")
    assert cross_body == unknown_body
    assert str(protected.id) not in cross_tenant.content.decode()
    assert protected.name not in cross_tenant.content.decode()
