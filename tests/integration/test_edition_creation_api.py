from uuid import uuid4

import pytest
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.authorization.services import AuthorizationDenied
from maru.effects.models import DomainEvent, OutboxMessage
from maru.events.models import EditionCreationReceipt, EventEdition
from maru.events.serializers import EditionBasicSerializer
from maru.organizations.models import Organization
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    ConventionSeriesFactory,
    OrganizationFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _url(organization: Organization) -> str:
    return f"/api/v1/organizations/{organization.id}/editions"


def _payload(*, series_id: object, **changes: object):
    payload: dict[str, object] = {
        "series_id": str(series_id),
        "name": "Synthetic Convention 2031",
        "starts_on": "2031-08-14",
        "ends_on": "2031-08-17",
        "time_zone": "Europe/Vienna",
        "language_codes": ["en", "de"],
        "currency_codes": ["EUR"],
    }
    payload.update(changes)
    return payload


def _client(account: object) -> APIClient:
    client = APIClient()
    client.force_authenticate(account)
    return client


def test_creation_api_returns_201_then_idempotent_200() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    series = ConventionSeriesFactory()
    key = uuid4()
    request_id = uuid4()
    client = _client(administrator)
    payload = _payload(series_id=series.id)

    created = client.post(
        _url(series.organization),
        payload,
        format="json",
        HTTP_X_REQUEST_ID=str(request_id),
        HTTP_IDEMPOTENCY_KEY=str(key),
    )
    replayed = client.post(
        _url(series.organization),
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(key),
    )

    assert created.status_code == 201
    assert replayed.status_code == 200
    assert replayed.json() == created.json()
    assert created.headers["X-Request-ID"] == str(request_id)
    assert created.json()["organization_id"] == str(series.organization_id)
    assert created.json()["series_id"] == str(series.id)
    assert created.json()["slug"] == "synthetic-convention-2031"
    assert created.json()["lifecycle"] == "draft"
    assert created.json()["aggregate_version"] == 1
    assert EventEdition.objects.count() == 1
    assert EditionCreationReceipt.objects.count() == 1
    assert AuditEvent.objects.count() == 1
    assert DomainEvent.objects.count() == 1
    assert OutboxMessage.objects.count() == 1


def test_creation_api_direct_grant_has_an_explicit_complete_response_ceiling() -> None:
    organizer = AccountFactory()
    series = ConventionSeriesFactory()
    CapabilityGrantFactory(
        organization=series.organization,
        principal=organizer,
        capability_code="events.create",
    )

    response = _client(organizer).post(
        _url(series.organization),
        _payload(series_id=series.id),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )

    assert response.status_code == 201
    assert set(response.json()) == set(EditionBasicSerializer.Meta.fields)
    assert response.json()["organization_id"] == str(series.organization_id)
    assert response.json()["series_id"] == str(series.id)


def test_creation_api_denies_an_inactive_direct_grant_holder() -> None:
    organizer = AccountFactory()
    series = ConventionSeriesFactory()
    CapabilityGrantFactory(
        organization=series.organization,
        principal=organizer,
        capability_code="events.create",
    )
    organizer.is_active = False
    organizer.save(update_fields=("is_active",))

    response = _client(organizer).post(
        _url(series.organization),
        _payload(series_id=series.id),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "account_inactive"
    assert not EventEdition.objects.exists()
    assert not EditionCreationReceipt.objects.exists()
    assert not AuditEvent.objects.exists()
    assert not DomainEvent.objects.exists()
    assert not OutboxMessage.objects.exists()


def test_creation_api_does_not_expose_domain_denial_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    series = ConventionSeriesFactory()

    def deny_creation(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AuthorizationDenied(
            "private authorization implementation detail",
            reason_code="synthetic_denial",
        )

    monkeypatch.setattr("maru.events.api.create_event_edition", deny_creation)
    response = _client(administrator).post(
        _url(series.organization),
        _payload(series_id=series.id),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "synthetic_denial"
    assert "private authorization" not in response.content.decode()
    assert "cannot create an edition" in response.content.decode()


def test_creation_api_rolls_back_and_returns_safe_503_on_effect_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    series = ConventionSeriesFactory()

    def unavailable(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("synthetic private event dependency failure")

    monkeypatch.setattr("maru.events.services.publish_domain_event", unavailable)
    response = _client(administrator).post(
        _url(series.organization),
        _payload(series_id=series.id),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )

    assert response.status_code == 503
    assert response.headers["Content-Type"].startswith("application/problem+json")
    assert response.json()["code"] == "service_unavailable"
    assert "synthetic private" not in response.content.decode()
    assert not EventEdition.objects.exists()
    assert not EditionCreationReceipt.objects.exists()
    assert not AuditEvent.objects.exists()
    assert not DomainEvent.objects.exists()
    assert not OutboxMessage.objects.exists()


def test_creation_api_reports_idempotency_conflict_as_409() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    series = ConventionSeriesFactory()
    key = uuid4()
    client = _client(administrator)

    first = client.post(
        _url(series.organization),
        _payload(series_id=series.id),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(key),
    )
    conflict = client.post(
        _url(series.organization),
        _payload(
            series_id=series.id,
            name="Different Synthetic Convention 2031",
        ),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(key),
    )

    assert first.status_code == 201
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "edition_creation_idempotency_conflict"
    assert EventEdition.objects.count() == 1
    assert EditionCreationReceipt.objects.count() == 1
    assert AuditEvent.objects.count() == 1
    assert DomainEvent.objects.count() == 1


def test_creation_api_hides_cross_tenant_series_and_denies_before_lookup() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory()
    foreign_series = ConventionSeriesFactory()

    mismatch = _client(administrator).post(
        _url(organization),
        _payload(series_id=foreign_series.id),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )

    ordinary = AccountFactory()
    denied = _client(ordinary).post(
        _url(foreign_series.organization),
        _payload(series_id=foreign_series.id),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )

    assert mismatch.status_code == 404
    assert mismatch.json()["code"] == "edition_parent_not_found"
    assert denied.status_code == 403
    assert denied.json()["code"] == "permission_absent"
    assert not EventEdition.objects.exists()
    assert not EditionCreationReceipt.objects.exists()


def test_creation_api_denies_before_parsing_unknown_or_malformed_input() -> None:
    ordinary = AccountFactory()
    organization = OrganizationFactory()
    client = _client(ordinary)

    response = client.post(
        _url(organization),
        {
            "organization_id": str(organization.id),
            "slug": "forged",
            "name": 42,
        },
        format="json",
    )

    assert response.status_code == 403
    assert response.json()["code"] == "permission_absent"
    assert not EventEdition.objects.exists()


def test_creation_api_requires_a_valid_idempotency_header_and_rejects_body_key() -> (
    None
):
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    series = ConventionSeriesFactory()
    client = _client(administrator)

    missing = client.post(
        _url(series.organization),
        _payload(series_id=series.id),
        format="json",
    )
    invalid = client.post(
        _url(series.organization),
        _payload(series_id=series.id),
        format="json",
        HTTP_IDEMPOTENCY_KEY="not-a-uuid",
    )
    body_key = client.post(
        _url(series.organization),
        _payload(series_id=series.id, idempotency_key=str(uuid4())),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )

    assert missing.status_code == 400
    assert missing.json()["code"] == "missing_idempotency_key"
    assert "Idempotency-Key" in missing.json()["errors"]
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "invalid_idempotency_key"
    assert body_key.status_code == 400
    assert body_key.json()["code"] == "unknown_input_field"
    assert "idempotency_key" in str(body_key.json()["errors"])
    assert not EventEdition.objects.exists()
    assert not EditionCreationReceipt.objects.exists()


@pytest.mark.parametrize(
    ("organization_lifecycle", "series_active", "expected_code"),
    [
        (Organization.Lifecycle.CLOSED, True, "edition_parent_closed"),
        (Organization.Lifecycle.ACTIVE, False, "edition_series_inactive"),
    ],
)
def test_creation_api_reports_parent_conflict_as_409(
    organization_lifecycle: str,
    series_active: bool,
    expected_code: str,
) -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(lifecycle=organization_lifecycle)
    series = ConventionSeriesFactory(
        organization=organization,
        is_active=series_active,
    )

    response = _client(administrator).post(
        _url(organization),
        _payload(series_id=series.id),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )

    assert response.status_code == 409
    assert response.json()["code"] == expected_code
    assert not EventEdition.objects.exists()
    assert not EditionCreationReceipt.objects.exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "x" * 161},
        {"starts_on": "2031-08-18", "ends_on": "2031-08-17"},
        {"ends_on": "2031-09-15"},
        {"time_zone": "Mars/Olympus"},
        {"time_zone": "../etc/passwd"},
        {"language_codes": []},
        {"language_codes": ["en", "en"]},
        {"currency_codes": ["ZZZ"]},
        {
            "currency_codes": [
                "EUR",
                "USD",
                "GBP",
                "HUF",
                "CAD",
                "AUD",
                "JPY",
                "CHF",
                "SEK",
            ]
        },
    ],
)
def test_creation_api_rejects_invalid_bounded_fields(
    changes: dict[str, object],
) -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    series = ConventionSeriesFactory()

    response = _client(administrator).post(
        _url(series.organization),
        _payload(
            series_id=series.id,
            **changes,
        ),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )

    assert response.status_code == 400
    assert not EventEdition.objects.exists()
    assert not EditionCreationReceipt.objects.exists()
    assert not AuditEvent.objects.exists()
    assert not DomainEvent.objects.exists()
    assert not OutboxMessage.objects.exists()


def test_edition_management_openapi_declares_problem_responses() -> None:
    response = _client(AccountFactory(is_staff=True, is_superuser=True)).get(
        "/api/v1/schema",
        HTTP_ACCEPT="application/vnd.oai.openapi+json",
    )

    assert response.status_code == 200
    schema = response.json()
    collection_get = schema["paths"][
        "/api/v1/organizations/{organization_id}/editions"
    ]["get"]
    collection = schema["paths"]["/api/v1/organizations/{organization_id}/editions"][
        "post"
    ]
    autocomplete_get = schema["paths"][
        "/api/v1/organizations/{organization_id}/editions/autocomplete"
    ]["get"]
    detail_get = schema["paths"][
        "/api/v1/organizations/{organization_id}/editions/{edition_id}"
    ]["get"]
    detail = schema["paths"][
        "/api/v1/organizations/{organization_id}/editions/{edition_id}"
    ]["put"]
    assert set(collection_get["responses"]) == {"200", "400", "403", "503"}
    assert set(autocomplete_get["responses"]) == {"200", "400", "403", "503"}
    assert set(detail_get["responses"]) == {"200", "400", "403", "404", "503"}
    assert set(collection["responses"]) == {
        "200",
        "201",
        "400",
        "403",
        "404",
        "409",
        "503",
    }
    assert set(detail["responses"]) == {
        "200",
        "400",
        "403",
        "404",
        "409",
        "503",
    }
    idempotency_header = next(
        parameter
        for parameter in collection["parameters"]
        if parameter["name"] == "Idempotency-Key"
    )
    assert idempotency_header["in"] == "header"
    assert idempotency_header["required"] is True
    assert idempotency_header["schema"]["format"] == "uuid"
    create_schema = schema["components"]["schemas"]["EditionCreateRequest"]
    assert "idempotency_key" not in create_schema["properties"]
    for operation in (collection, detail):
        conflict_schema = operation["responses"]["409"]["content"][
            "application/problem+json"
        ]["schema"]
        assert conflict_schema["$ref"].endswith("/EditionProblem")

    problem_component = schema["components"]["schemas"]["EditionProblem"]
    assert "request_id" not in problem_component["required"]
    assert "errors" not in problem_component["required"]
    denied = _client(AccountFactory()).get(
        _url(ConventionSeriesFactory().organization),
    )
    denied_body = denied.json()
    assert denied.status_code == 403
    assert "errors" not in denied_body
    assert set(problem_component["required"]) <= set(denied_body)
    assert set(denied_body) <= set(problem_component["properties"])
