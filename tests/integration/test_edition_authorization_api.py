from uuid import uuid4

import pytest
from rest_framework.test import APIClient

from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _url(edition: object) -> str:
    return f"/api/v1/organizations/{edition.organization_id}/editions/{edition.id}"


def _list_url(edition: object) -> str:
    return f"/api/v1/organizations/{edition.organization_id}/editions"


def test_edition_list_search_count_and_pagination_are_tenant_first() -> None:
    first = EventEditionFactory(name="Pawprint Spring")
    second = EventEditionFactory(
        organization=first.organization,
        series__organization=first.organization,
        name="Pawprint Autumn",
    )
    other = EventEditionFactory(name="Other Organizer Event")
    account = AccountFactory()
    CapabilityGrantFactory(
        principal=account,
        organization=first.organization,
    )
    client = APIClient()
    client.force_authenticate(account)

    page = client.get(_list_url(first), {"page_size": 1})
    search = client.get(_list_url(first), {"search": "Autumn"})

    assert page.status_code == 200
    assert page.json()["count"] == 2
    assert len(page.json()["results"]) == 1
    assert search.status_code == 200
    assert search.json()["count"] == 1
    assert search.json()["results"][0]["id"] == str(second.id)
    assert str(other.id) not in str(page.json())
    assert str(other.id) not in str(search.json())


def test_edition_scoped_grant_allows_detail_but_not_organization_list() -> None:
    edition = EventEditionFactory()
    account = AccountFactory()
    CapabilityGrantFactory(
        principal=account,
        organization=edition.organization,
        edition=edition,
    )
    client = APIClient()
    client.force_authenticate(account)

    detail = client.get(_url(edition))
    listing = client.get(_list_url(edition))

    assert detail.status_code == 200
    assert listing.status_code == 403
    assert listing.json()["code"] == "permission_absent"
    assert "count" not in listing.json()


def test_edition_reads_reject_unbounded_and_undeclared_query_input() -> None:
    edition = EventEditionFactory()
    account = AccountFactory()
    CapabilityGrantFactory(
        principal=account,
        organization=edition.organization,
    )
    client = APIClient()
    client.force_authenticate(account)

    oversized = client.get(_list_url(edition), {"page_size": 101})
    undeclared_list = client.get(
        _list_url(edition),
        {"include_private": "true"},
    )
    undeclared_detail = client.get(
        _url(edition),
        {"include_private": "true"},
    )

    assert oversized.status_code == 400
    assert undeclared_list.status_code == 400
    assert undeclared_list.json()["code"] == "unknown_input_field"
    assert undeclared_detail.status_code == 400
    assert undeclared_detail.json()["code"] == "unknown_input_field"


def test_basic_edition_api_requires_exact_scoped_capability() -> None:
    edition = EventEditionFactory()
    account = AccountFactory()
    CapabilityGrantFactory(
        principal=account,
        organization=edition.organization,
    )
    client = APIClient()
    client.force_authenticate(account)

    response = client.get(_url(edition))

    assert response.status_code == 200
    assert response.json() == {
        "id": str(edition.id),
        "organization_id": str(edition.organization_id),
        "series_id": str(edition.series_id),
        "slug": edition.slug,
        "name": edition.name,
        "lifecycle": edition.lifecycle,
        "aggregate_version": edition.aggregate_version,
        "adoption_profile_code": edition.adoption_profile_code,
        "adoption_profile_version": edition.adoption_profile_version,
        "time_zone": edition.time_zone,
        "language_codes": edition.language_codes,
        "currency_codes": edition.currency_codes,
        "starts_on": edition.starts_on.isoformat(),
        "ends_on": edition.ends_on.isoformat(),
    }
    assert "email" not in response.content.decode()


def test_basic_edition_api_denies_ordinary_membership_and_other_tenant() -> None:
    edition = EventEditionFactory()
    other_edition = EventEditionFactory()
    account = AccountFactory()
    CapabilityGrantFactory(
        principal=account,
        organization=edition.organization,
    )
    client = APIClient()
    client.force_authenticate(account)

    other_response = client.get(_url(other_edition))
    unknown_response = client.get(
        f"/api/v1/organizations/{other_edition.organization_id}/editions/{edition.id}"
    )
    absent_response = client.get(
        f"/api/v1/organizations/{other_edition.organization_id}/editions/{uuid4()}"
    )

    assert other_response.status_code == 403
    assert other_response.json()["code"] == "permission_absent"
    assert unknown_response.status_code == 403
    assert unknown_response.json()["code"] == "target_unavailable"
    assert absent_response.status_code == 403
    assert absent_response.json()["code"] == "target_unavailable"


def test_transition_api_uses_scoped_capability_and_request_correlation() -> None:
    edition = EventEditionFactory()
    account = AccountFactory()
    CapabilityGrantFactory(
        principal=account,
        organization=edition.organization,
        edition=edition,
        capability_code="events.transition",
    )
    request_id = uuid4()
    client = APIClient()
    client.force_authenticate(account)

    response = client.post(
        f"{_url(edition)}/transition",
        {
            "to_state": "preparing",
            "reason": "Begin event preparation.",
        },
        format="json",
        HTTP_X_REQUEST_ID=str(request_id),
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": str(edition.id),
        "lifecycle": "preparing",
        "lifecycle_version": 1,
    }
    assert response.headers["X-Request-ID"] == str(request_id)


def test_transition_api_denies_without_cross_tenant_existence_leak() -> None:
    edition = EventEditionFactory()
    other = EventEditionFactory()
    account = AccountFactory()
    CapabilityGrantFactory(
        principal=account,
        organization=edition.organization,
        edition=edition,
        capability_code="events.transition",
    )
    client = APIClient()
    client.force_authenticate(account)

    response = client.post(
        f"{_url(other)}/transition",
        {
            "to_state": "preparing",
            "reason": "Attempt another tenant.",
        },
        format="json",
    )

    assert response.status_code == 403
    assert response.json()["code"] == "permission_absent"
