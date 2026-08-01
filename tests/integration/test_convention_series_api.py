from uuid import uuid4

import pytest
from django.db import DatabaseError
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.effects.models import DomainEvent, OutboxMessage
from maru.identity.models import Account
from maru.organizations.models import ConventionSeries, Organization
from tests.factories import (
    AccountFactory,
    ConventionSeriesFactory,
    OrganizationFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _client(account: object) -> APIClient:
    client = APIClient()
    client.force_authenticate(account)
    return client


def _administrator() -> Account:
    return AccountFactory(is_staff=True, is_superuser=True)


def _list_url(organization: Organization) -> str:
    return f"/api/v1/organizations/{organization.id}/series"


def _detail_url(
    series: ConventionSeries,
    *,
    organization: Organization | None = None,
) -> str:
    scope = organization or series.organization
    return f"/api/v1/organizations/{scope.id}/series/{series.id}"


def _payload(
    series: ConventionSeries,
    **changes: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": series.name,
        "description": series.description,
        "website_url": series.website_url,
        "contact_email": series.contact_email,
        "is_active": series.is_active,
        "expected_profile_version": series.profile_version,
    }
    payload.update(changes)
    return payload


def test_series_collection_is_paginated_ordered_and_exactly_tenant_scoped() -> None:
    organization = OrganizationFactory()
    second = ConventionSeriesFactory(
        organization=organization,
        name="MaruCon Winter",
        slug="marucon-winter",
    )
    first = ConventionSeriesFactory(
        organization=organization,
        name="MaruCon Summer",
        slug="marucon-summer",
    )
    foreign = ConventionSeriesFactory(name="Confidential Other Convention")
    client = _client(_administrator())

    response = client.get(_list_url(organization), {"page_size": 1})

    assert response.status_code == 200
    assert response.json()["count"] == 2
    assert response.json()["results"][0]["id"] == str(first.id)
    assert response.json()["results"][0]["organization_id"] == str(organization.id)
    assert str(second.id) not in str(response.json()["results"])
    assert str(foreign.id) not in response.content.decode()
    assert foreign.name not in response.content.decode()


def test_series_collection_rejects_unknown_scope_and_unbounded_query_input() -> None:
    client = _client(_administrator())

    unknown = client.get(
        f"/api/v1/organizations/{uuid4()}/series",
    )
    oversized = client.get(
        _list_url(OrganizationFactory()),
        {"page_size": 101},
    )
    undeclared = client.get(
        _list_url(OrganizationFactory()),
        {"include_private": "true"},
    )

    assert unknown.status_code == 404
    assert unknown.json()["code"] == "organization_not_found"
    assert oversized.status_code == 400
    assert "page_size" in oversized.json()["errors"]
    assert undeclared.status_code == 400
    assert undeclared.json()["code"] == "unknown_input_field"
    assert "include_private" in str(undeclared.json()["errors"])


def test_series_detail_returns_the_complete_stable_read_projection() -> None:
    series = ConventionSeriesFactory(
        description="A recurring synthetic convention.",
        website_url="https://marucon.example.invalid",
        contact_email="hello@example.invalid",
        is_active=False,
    )

    response = _client(_administrator()).get(_detail_url(series))

    assert response.status_code == 200
    assert response.json() == {
        "id": str(series.id),
        "organization_id": str(series.organization_id),
        "slug": series.slug,
        "name": series.name,
        "description": series.description,
        "website_url": series.website_url,
        "contact_email": series.contact_email,
        "is_active": False,
        "profile_version": 1,
        "created_at": series.created_at.isoformat().replace("+00:00", "Z"),
        "updated_at": series.updated_at.isoformat().replace("+00:00", "Z"),
    }


def test_series_detail_rejects_undeclared_query_input() -> None:
    series = ConventionSeriesFactory()

    response = _client(_administrator()).get(
        _detail_url(series),
        {"include_private": "true"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "unknown_input_field"
    assert "include_private" in str(response.json()["errors"])


def test_series_detail_mismatch_is_a_stable_404_without_foreign_data() -> None:
    series = ConventionSeriesFactory(name="Foreign Series Name")
    other = OrganizationFactory()

    response = _client(_administrator()).get(_detail_url(series, organization=other))

    assert response.status_code == 404
    assert response.json()["code"] == "convention_series_not_found"
    assert series.name not in response.content.decode()


def test_series_detail_lookup_failure_is_a_safe_stable_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    series = ConventionSeriesFactory()

    def unavailable(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise DatabaseError("synthetic private series lookup failure")

    monkeypatch.setattr(ConventionSeries.objects, "get", unavailable)
    response = _client(_administrator()).get(_detail_url(series))

    assert response.status_code == 503
    assert response.headers["Content-Type"].startswith("application/problem+json")
    assert response.json()["code"] == "service_unavailable"
    assert "synthetic private" not in response.content.decode()


def test_platform_boundary_precedes_collection_detail_and_update_lookup() -> None:
    ordinary = AccountFactory()
    organization = OrganizationFactory()
    series = ConventionSeriesFactory(organization=organization)
    client = _client(ordinary)

    responses = (
        client.get(_list_url(organization)),
        client.get(_detail_url(series)),
        client.get(
            f"/api/v1/organizations/{uuid4()}/series/{uuid4()}",
        ),
        client.put(
            f"/api/v1/organizations/{uuid4()}/series/{uuid4()}",
            _payload(series),
            format="json",
        ),
    )

    assert {response.status_code for response in responses} == {403}
    assert {response.json()["code"] for response in responses} == {
        "platform_administration_required"
    }
    assert not AuditEvent.objects.exists()
    assert not DomainEvent.objects.exists()
    assert not OutboxMessage.objects.exists()


def test_inactive_platform_administrator_is_denied() -> None:
    administrator = _administrator()
    administrator.is_active = False
    administrator.save(update_fields=("is_active",))
    series = ConventionSeriesFactory()

    response = _client(administrator).get(_detail_url(series))

    assert response.status_code == 403
    assert response.json()["code"] == "platform_administration_required"


def test_complete_put_normalizes_and_uses_the_audited_update_service() -> None:
    series = ConventionSeriesFactory()
    administrator = _administrator()
    request_id = uuid4()

    response = _client(administrator).put(
        _detail_url(series),
        _payload(
            series,
            name="  MaruCon    International  ",
            description="  A recurring synthetic convention brand.  ",
            website_url="marucon.example.invalid",
            contact_email="  hello@example.invalid  ",
            is_active=False,
        ),
        format="json",
        HTTP_X_REQUEST_ID=str(request_id),
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == str(request_id)
    assert response.json()["organization_id"] == str(series.organization_id)
    assert response.json()["slug"] == series.slug
    assert response.json()["name"] == "MaruCon International"
    assert response.json()["description"] == ("A recurring synthetic convention brand.")
    assert response.json()["website_url"] == ("https://marucon.example.invalid")
    assert response.json()["contact_email"] == "hello@example.invalid"
    assert response.json()["is_active"] is False
    assert response.json()["profile_version"] == 2

    series.refresh_from_db()
    assert str(series.organization_id) == response.json()["organization_id"]
    assert series.slug == response.json()["slug"]
    assert series.profile_version == 2

    audit = AuditEvent.objects.get()
    event = DomainEvent.objects.get()
    outbox = OutboxMessage.objects.get()
    assert audit.principal_id == administrator.id
    assert audit.organization_id == series.organization_id
    assert audit.target_id == series.id
    assert audit.operation == "organizations.convention_series.update"
    assert audit.capability_code == "organizations.change_series"
    assert audit.source_channel == "api"
    assert audit.correlation_id == request_id
    assert audit.request_id == request_id
    assert audit.changed_fields == [
        "name",
        "description",
        "website_url",
        "contact_email",
        "is_active",
        "profile_version",
    ]
    assert event.event_name == "organizations.convention_series.updated.v1"
    assert event.organization_id == series.organization_id
    assert event.aggregate_id == series.id
    assert event.aggregate_version == 2
    assert event.payload == {
        "availability": "inactive",
        "changed_fields": ("name,description,website_url,contact_email,is_active"),
        "profile_version": "2",
    }
    assert event.causation_id == audit.id
    assert event.correlation_id == request_id
    assert outbox.event_id == event.id
    assert outbox.organization_id == series.organization_id


def test_unchanged_put_is_a_true_no_op() -> None:
    series = ConventionSeriesFactory(
        description="Already complete.",
        website_url="https://example.invalid",
        contact_email="hello@example.invalid",
    )

    response = _client(_administrator()).put(
        _detail_url(series),
        _payload(series),
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["profile_version"] == 1
    series.refresh_from_db()
    assert series.profile_version == 1
    assert not AuditEvent.objects.exists()
    assert not DomainEvent.objects.exists()
    assert not OutboxMessage.objects.exists()


def test_stale_put_is_a_stable_409_and_changes_nothing() -> None:
    series = ConventionSeriesFactory()

    response = _client(_administrator()).put(
        _detail_url(series),
        _payload(
            series,
            name="Should Not Be Stored",
            expected_profile_version=2,
        ),
        format="json",
    )

    assert response.status_code == 409
    assert response.headers["Content-Type"].startswith("application/problem+json")
    assert response.json()["code"] == "stale_series_profile"
    assert response.json()["status"] == 409
    assert response.json()["type"].endswith("/stale_series_profile")
    assert "expected_profile_version" in response.json()["errors"]
    series.refresh_from_db()
    assert series.name != "Should Not Be Stored"
    assert series.profile_version == 1
    assert not AuditEvent.objects.exists()
    assert not DomainEvent.objects.exists()
    assert not OutboxMessage.objects.exists()


def test_closed_parent_put_is_a_stable_409_and_changes_nothing() -> None:
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.CLOSED)
    series = ConventionSeriesFactory(organization=organization)

    response = _client(_administrator()).put(
        _detail_url(series),
        _payload(series, name="Should Not Be Stored"),
        format="json",
    )

    assert response.status_code == 409
    assert response.json()["code"] == "series_parent_closed"
    series.refresh_from_db()
    assert series.name != "Should Not Be Stored"
    assert series.profile_version == 1
    assert not AuditEvent.objects.exists()
    assert not DomainEvent.objects.exists()
    assert not OutboxMessage.objects.exists()


def test_series_put_rolls_back_and_returns_safe_503_on_effect_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    series = ConventionSeriesFactory(name="Original Synthetic Series")

    def unavailable(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("synthetic private series dependency failure")

    monkeypatch.setattr(
        "maru.organizations.services.publish_domain_event",
        unavailable,
    )
    response = _client(_administrator()).put(
        _detail_url(series),
        _payload(series, name="Must Roll Back"),
        format="json",
    )

    assert response.status_code == 503
    assert response.headers["Content-Type"].startswith("application/problem+json")
    assert response.json()["code"] == "service_unavailable"
    assert "synthetic private" not in response.content.decode()
    series.refresh_from_db()
    assert series.name == "Original Synthetic Series"
    assert series.profile_version == 1
    assert not AuditEvent.objects.exists()
    assert not DomainEvent.objects.exists()
    assert not OutboxMessage.objects.exists()


def test_put_cannot_cross_scope_or_replace_stable_identity() -> None:
    series = ConventionSeriesFactory()
    other = OrganizationFactory()
    original_slug = series.slug

    mismatch = _client(_administrator()).put(
        _detail_url(series, organization=other),
        _payload(series, name="Forged Name"),
        format="json",
    )
    forged_identity = _client(_administrator()).put(
        _detail_url(series),
        _payload(
            series,
            id=str(uuid4()),
            organization=str(other.id),
            organization_id=str(other.id),
            series_id=str(uuid4()),
            slug="forged-slug",
            profile_version=99,
            aggregate_version=99,
            version=99,
        ),
        format="json",
    )

    assert mismatch.status_code == 404
    assert mismatch.json()["code"] == "convention_series_not_found"
    assert forged_identity.status_code == 400
    assert forged_identity.json()["code"] == "unknown_input_field"
    forged_errors = str(forged_identity.json()["errors"])
    assert "aggregate_version" in forged_errors
    assert "organization_id" in forged_errors
    assert "and 3 more" in forged_errors
    series.refresh_from_db()
    assert series.organization_id != other.id
    assert series.slug == original_slug
    assert series.name != "Forged Name"
    assert not AuditEvent.objects.exists()
    assert not DomainEvent.objects.exists()


@pytest.mark.parametrize(
    "missing_field",
    [
        "name",
        "description",
        "website_url",
        "contact_email",
        "is_active",
        "expected_profile_version",
    ],
)
def test_put_requires_the_complete_profile(missing_field: str) -> None:
    series = ConventionSeriesFactory()
    payload = _payload(series)
    del payload[missing_field]

    response = _client(_administrator()).put(
        _detail_url(series),
        payload,
        format="json",
    )

    assert response.status_code == 400
    assert missing_field in response.json()["errors"]
    assert not AuditEvent.objects.exists()
    assert not DomainEvent.objects.exists()


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("name", " "),
        ("name", "x" * 161),
        ("description", "x" * 2001),
        ("website_url", "not a valid host"),
        ("contact_email", "not-an-email"),
        ("is_active", "sometimes"),
        ("expected_profile_version", 0),
    ],
)
def test_put_rejects_invalid_bounded_profile_fields(
    field_name: str,
    invalid_value: object,
) -> None:
    series = ConventionSeriesFactory()

    response = _client(_administrator()).put(
        _detail_url(series),
        _payload(series, **{field_name: invalid_value}),
        format="json",
    )

    assert response.status_code == 400
    assert field_name in response.json()["errors"]
    assert not AuditEvent.objects.exists()
    assert not DomainEvent.objects.exists()
    assert not OutboxMessage.objects.exists()


def test_series_api_mounts_no_unaudited_mutation_methods() -> None:
    series = ConventionSeriesFactory()
    client = _client(_administrator())

    responses = (
        client.post(_list_url(series.organization), {}, format="json"),
        client.post(_detail_url(series), {}, format="json"),
        client.patch(_detail_url(series), {}, format="json"),
        client.delete(_detail_url(series)),
    )

    assert {response.status_code for response in responses} == {405}
    assert ConventionSeries.objects.filter(id=series.id).exists()
    assert not AuditEvent.objects.exists()
    assert not DomainEvent.objects.exists()


def test_openapi_contract_describes_only_list_retrieve_and_complete_put() -> None:
    response = _client(_administrator()).get(
        "/api/v1/schema",
        HTTP_ACCEPT="application/vnd.oai.openapi+json",
    )

    assert response.status_code == 200
    schema = response.json()
    collection_path = "/api/v1/organizations/{organization_id}/series"
    detail_path = "/api/v1/organizations/{organization_id}/series/{series_id}"
    assert set(schema["paths"][collection_path]) == {"get"}
    assert set(schema["paths"][detail_path]) == {"get", "put"}
    assert schema["paths"][collection_path]["get"]["operationId"] == (
        "organizations_list_convention_series"
    )
    page_size = next(
        parameter
        for parameter in schema["paths"][collection_path]["get"]["parameters"]
        if parameter["name"] == "page_size"
    )
    assert page_size["schema"]["maximum"] == 100
    collection_get = schema["paths"][collection_path]["get"]
    detail_get = schema["paths"][detail_path]["get"]
    assert set(collection_get["responses"]) == {"200", "400", "403", "404", "503"}
    assert set(detail_get["responses"]) == {"200", "400", "403", "404", "503"}
    put = schema["paths"][detail_path]["put"]
    assert put["operationId"] == "organizations_update_convention_series"
    assert set(put["responses"]) == {"200", "400", "403", "404", "409", "503"}
    component = schema["components"]["schemas"]["ConventionSeriesUpdate"]
    assert set(component["required"]) == {
        "name",
        "description",
        "website_url",
        "contact_email",
        "is_active",
        "expected_profile_version",
    }
    assert component["properties"]["name"]["maxLength"] == 160
    assert component["properties"]["description"]["maxLength"] == 2000
    assert component["properties"]["expected_profile_version"]["minimum"] == 1
    conflict_schema = put["responses"]["409"]["content"]["application/problem+json"][
        "schema"
    ]
    assert conflict_schema["$ref"].endswith("/ConventionSeriesProblem")
    problem_component = schema["components"]["schemas"]["ConventionSeriesProblem"]
    assert "request_id" not in problem_component["required"]
    assert "errors" not in problem_component["required"]
    denied = _client(AccountFactory()).get(_detail_url(ConventionSeriesFactory()))
    denied_body = denied.json()
    assert denied.status_code == 403
    assert "errors" not in denied_body
    assert set(problem_component["required"]) <= set(denied_body)
    assert set(denied_body) <= set(problem_component["properties"])
