from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.authorization.policy import PolicyDecision
from maru.effects.models import DomainEvent, OutboxMessage
from maru.events import services as event_services
from maru.events.models import EditionLifecycleTransition, EventEdition
from maru.events.services import bulk_transition_editions, transition_edition
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


def _autocomplete_url(edition: EventEdition) -> str:
    return f"/api/v1/organizations/{edition.organization_id}/editions/autocomplete"


def _bulk_url(edition: EventEdition) -> str:
    return f"/api/v1/organizations/{edition.organization_id}/editions/bulk-transition"


def _same_organization_edition(
    edition: EventEdition,
    *,
    name: str,
    lifecycle: str = EventEdition.Lifecycle.DRAFT,
) -> EventEdition:
    return EventEditionFactory(
        organization=edition.organization,
        series=edition.series,
        name=name,
        lifecycle=lifecycle,
    )


def _client(account: object | None = None) -> APIClient:
    client = APIClient()
    if account is not None:
        client.force_authenticate(account)
    return client


def _grant_transition(account: object, edition: EventEdition) -> None:
    CapabilityGrantFactory(
        principal=account,
        organization=edition.organization,
        edition=edition,
        capability_code="events.transition",
    )


def test_autocomplete_isolation_matrix_is_tenant_first() -> None:
    first = EventEditionFactory(name="Pawprint Spring")
    _same_organization_edition(first, name="Pawprint Autumn")
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
    url = _autocomplete_url(first)
    protected_values = (str(protected.id), protected.name)

    assert_endpoint_isolation(
        [
            EndpointIsolationCase(
                name="anonymous",
                request=lambda: _client().get(url, {"search": "Pawprint"}),
                expected_status=403,
                expected_code="not_authenticated",
                forbidden_values=protected_values,
            ),
            EndpointIsolationCase(
                name="authorized organization",
                request=lambda: _client(authorized).get(
                    url,
                    {"search": "Pawprint"},
                ),
                expected_status=200,
                forbidden_values=protected_values,
            ),
            EndpointIsolationCase(
                name="edition grant cannot broaden into suggestions",
                request=lambda: _client(edition_only).get(
                    url,
                    {"search": "Pawprint"},
                ),
                expected_status=403,
                expected_code="permission_absent",
                forbidden_values=protected_values,
            ),
            EndpointIsolationCase(
                name="ordinary same-tenant account",
                request=lambda: _client(unauthorized).get(
                    url,
                    {"search": "Pawprint"},
                ),
                expected_status=403,
                expected_code="permission_absent",
                forbidden_values=protected_values,
            ),
            EndpointIsolationCase(
                name="similarly privileged other tenant",
                request=lambda: _client(wrong_tenant).get(
                    url,
                    {"search": "Pawprint"},
                ),
                expected_status=403,
                expected_code="permission_absent",
                forbidden_values=protected_values,
            ),
            EndpointIsolationCase(
                name="expired and revoked grants",
                request=lambda: _client(inactive).get(
                    url,
                    {"search": "Pawprint"},
                ),
                expected_status=403,
                expected_code="permission_absent",
                forbidden_values=protected_values,
            ),
        ]
    )


def test_autocomplete_is_bounded_minimized_and_literal() -> None:
    first = EventEditionFactory(name="Pawprint Spring")
    autumn = _same_organization_edition(first, name="Pawprint Autumn")
    protected = EventEditionFactory(name="Other Organizer Autumn")
    account = AccountFactory()
    CapabilityGrantFactory(
        principal=account,
        organization=first.organization,
    )
    client = _client(account)
    url = _autocomplete_url(first)

    response = client.get(url, {"search": "Autumn", "limit": 1})
    literal = client.get(url, {"search": "["})
    oversized = client.get(url, {"search": "Pawprint", "limit": 21})
    undeclared = client.get(
        url,
        {"search": "Pawprint", "include_private": "true"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "results": [
            {
                "id": str(autumn.id),
                "name": autumn.name,
                "lifecycle": autumn.lifecycle,
                "starts_on": autumn.starts_on.isoformat(),
            }
        ]
    }
    assert "count" not in response.json()
    assert str(protected.id) not in response.content.decode()
    assert literal.status_code == 200
    assert literal.json() == {"results": []}
    assert oversized.status_code == 400
    assert undeclared.status_code == 400
    assert undeclared.json()["code"] == "unknown_input_field"


def test_autocomplete_projection_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    edition = EventEditionFactory()
    account = AccountFactory()

    def incomplete_decision(**_kwargs: object) -> PolicyDecision:
        return PolicyDecision(
            allowed=True,
            fields=frozenset({"id", "name"}),
            obligations=frozenset(),
            reason_code="synthetic_incomplete_projection",
        )

    monkeypatch.setattr("maru.events.api.decide", incomplete_decision)

    response = _client(account).get(
        _autocomplete_url(edition),
        {"search": "Synthetic"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "field_projection_denied"
    assert "results" not in response.json()


def test_bulk_transition_freezes_and_commits_the_exact_authorized_set() -> None:
    first = EventEditionFactory(name="Pawprint Spring")
    second = _same_organization_edition(first, name="Pawprint Autumn")
    actor = AccountFactory()
    _grant_transition(actor, first)
    _grant_transition(actor, second)
    request_id = uuid4()

    response = _client(actor).post(
        _bulk_url(first),
        {
            "edition_ids": [str(second.id), str(first.id)],
            "to_state": EventEdition.Lifecycle.PREPARING,
            "reason": "Begin preparation for both editions.",
        },
        format="json",
        HTTP_X_REQUEST_ID=str(request_id),
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["results"]] == [
        str(second.id),
        str(first.id),
    ]
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.lifecycle == EventEdition.Lifecycle.PREPARING
    assert second.lifecycle == EventEdition.Lifecycle.PREPARING
    assert (
        EditionLifecycleTransition.objects.filter(
            edition_id__in=(first.id, second.id)
        ).count()
        == 2
    )
    audits = AuditEvent.objects.filter(correlation_id=request_id)
    assert audits.count() == 3
    bulk_audit = audits.get(operation="events.edition.bulk_transition")
    assert bulk_audit.outcome == AuditEvent.Outcome.ALLOW
    assert bulk_audit.safe_metadata["target_count"] == 2
    assert bulk_audit.target_id is None
    assert DomainEvent.objects.filter(correlation_id=request_id).count() == 2
    assert OutboxMessage.objects.filter(event__correlation_id=request_id).count() == 2
    assert "Begin preparation" not in str(bulk_audit.safe_metadata)


def test_bulk_transition_mixed_authority_denies_before_any_write() -> None:
    first = EventEditionFactory(name="Pawprint Spring")
    second = _same_organization_edition(first, name="Pawprint Autumn")
    actor = AccountFactory()
    _grant_transition(actor, first)
    request_id = uuid4()

    response = _client(actor).post(
        _bulk_url(first),
        {
            "edition_ids": [str(first.id), str(second.id)],
            "to_state": EventEdition.Lifecycle.PREPARING,
            "reason": "Attempt a mixed-authority transition.",
        },
        format="json",
        HTTP_X_REQUEST_ID=str(request_id),
    )

    assert response.status_code == 404
    assert response.json()["code"] == "bulk_target_unavailable"
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.lifecycle == EventEdition.Lifecycle.DRAFT
    assert second.lifecycle == EventEdition.Lifecycle.DRAFT
    assert not EditionLifecycleTransition.objects.filter(
        edition_id__in=(first.id, second.id)
    ).exists()
    assert not DomainEvent.objects.filter(correlation_id=request_id).exists()
    denial = AuditEvent.objects.get(correlation_id=request_id)
    assert denial.operation == "events.edition.bulk_transition"
    assert denial.outcome == AuditEvent.Outcome.DENY
    assert denial.safe_metadata["target_count"] == 2


def test_bulk_write_isolation_matrix_covers_principal_states() -> None:
    edition = EventEditionFactory()
    protected = EventEditionFactory(name="Protected Other Organizer Edition")
    authorized = AccountFactory()
    _grant_transition(authorized, edition)
    unauthorized = AccountFactory()
    wrong_tenant = AccountFactory()
    _grant_transition(wrong_tenant, protected)
    inactive = AccountFactory()
    now = timezone.now()
    CapabilityGrantFactory(
        principal=inactive,
        organization=edition.organization,
        edition=edition,
        capability_code="events.transition",
        effective_from=now - timedelta(days=2),
        expires_at=now - timedelta(days=1),
    )
    CapabilityGrantFactory(
        principal=inactive,
        organization=edition.organization,
        edition=edition,
        capability_code="events.transition",
        effective_from=now - timedelta(days=1),
        revoked_at=now,
    )
    url = _bulk_url(edition)
    payload = {
        "edition_ids": [str(edition.id)],
        "to_state": EventEdition.Lifecycle.PREPARING,
        "reason": "Exercise the write isolation matrix.",
    }
    protected_values = (str(protected.id), protected.name)

    assert_endpoint_isolation(
        [
            EndpointIsolationCase(
                name="anonymous bulk write",
                request=lambda: _client().post(url, payload, format="json"),
                expected_status=403,
                expected_code="not_authenticated",
                forbidden_values=protected_values,
            ),
            EndpointIsolationCase(
                name="ordinary same-tenant bulk write",
                request=lambda: _client(unauthorized).post(
                    url,
                    payload,
                    format="json",
                ),
                expected_status=404,
                expected_code="bulk_target_unavailable",
                forbidden_values=protected_values,
            ),
            EndpointIsolationCase(
                name="similarly privileged other-tenant bulk write",
                request=lambda: _client(wrong_tenant).post(
                    url,
                    payload,
                    format="json",
                ),
                expected_status=404,
                expected_code="bulk_target_unavailable",
                forbidden_values=protected_values,
            ),
            EndpointIsolationCase(
                name="expired and revoked bulk write authority",
                request=lambda: _client(inactive).post(
                    url,
                    payload,
                    format="json",
                ),
                expected_status=404,
                expected_code="bulk_target_unavailable",
                forbidden_values=protected_values,
            ),
            EndpointIsolationCase(
                name="authorized bulk write",
                request=lambda: _client(authorized).post(
                    url,
                    payload,
                    format="json",
                ),
                expected_status=200,
                forbidden_values=protected_values,
            ),
        ]
    )

    edition.refresh_from_db()
    assert edition.lifecycle == EventEdition.Lifecycle.PREPARING


def test_bulk_cross_tenant_and_unknown_targets_have_the_same_safe_shape() -> None:
    first = EventEditionFactory()
    protected = EventEditionFactory(name="Protected Other Organizer Edition")
    actor = AccountFactory()
    _grant_transition(actor, first)
    client = _client(actor)
    payload = {
        "to_state": EventEdition.Lifecycle.PREPARING,
        "reason": "Resolve an unavailable target.",
    }

    cross_tenant = client.post(
        _bulk_url(first),
        {
            **payload,
            "edition_ids": [str(first.id), str(protected.id)],
        },
        format="json",
    )
    unknown_id = uuid4()
    unknown = client.post(
        _bulk_url(first),
        {
            **payload,
            "edition_ids": [str(first.id), str(unknown_id)],
        },
        format="json",
    )

    assert cross_tenant.status_code == 404
    assert unknown.status_code == 404
    cross_body = cross_tenant.json()
    unknown_body = unknown.json()
    cross_body.pop("request_id")
    unknown_body.pop("request_id")
    assert cross_body == unknown_body
    assert cross_body["code"] == "bulk_target_unavailable"
    assert str(protected.id) not in cross_tenant.content.decode()
    assert protected.name not in cross_tenant.content.decode()
    first.refresh_from_db()
    assert first.lifecycle == EventEdition.Lifecycle.DRAFT
    assert not EditionLifecycleTransition.objects.filter(edition=first).exists()


def test_bulk_invalid_transition_rolls_back_every_target_and_effect() -> None:
    first = EventEditionFactory(name="Pawprint Spring")
    second = _same_organization_edition(first, name="Pawprint Preparing")
    actor = AccountFactory()
    _grant_transition(actor, first)
    _grant_transition(actor, second)
    transition_edition(
        organization_id=second.organization_id,
        edition_id=second.id,
        to_state=EventEdition.Lifecycle.PREPARING,
        actor=actor,
        reason="Prepare the second edition for the rollback fixture.",
        correlation_id=uuid4(),
    )
    transition_count_before = EditionLifecycleTransition.objects.filter(
        edition_id__in=(first.id, second.id)
    ).count()
    request_id = uuid4()

    response = _client(actor).post(
        _bulk_url(first),
        {
            "edition_ids": [str(first.id), str(second.id)],
            "to_state": EventEdition.Lifecycle.PREPARING,
            "reason": "Attempt one invalid lifecycle transition.",
        },
        format="json",
        HTTP_X_REQUEST_ID=str(request_id),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_transition"
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.lifecycle == EventEdition.Lifecycle.DRAFT
    assert first.lifecycle_version == 0
    assert second.lifecycle == EventEdition.Lifecycle.PREPARING
    assert second.lifecycle_version == 1
    assert (
        EditionLifecycleTransition.objects.filter(
            edition_id__in=(first.id, second.id)
        ).count()
        == transition_count_before
    )
    assert not DomainEvent.objects.filter(correlation_id=request_id).exists()
    assert not OutboxMessage.objects.filter(event__correlation_id=request_id).exists()
    failure = AuditEvent.objects.get(correlation_id=request_id)
    assert failure.operation == "events.edition.bulk_transition"
    assert failure.outcome == AuditEvent.Outcome.ERROR
    assert failure.reason_code == "invalid_transition"


def test_bulk_effect_failure_rolls_back_prior_targets_and_records_safe_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = EventEditionFactory(name="Pawprint Spring")
    second = _same_organization_edition(first, name="Pawprint Autumn")
    actor = AccountFactory()
    _grant_transition(actor, first)
    _grant_transition(actor, second)
    correlation_id = uuid4()
    original_publish = event_services.publish_domain_event
    publish_count = 0

    def fail_second_publish(*args: object, **kwargs: object) -> object:
        nonlocal publish_count
        publish_count += 1
        if publish_count == 2:
            raise RuntimeError("synthetic second bulk effect failure")
        return original_publish(*args, **kwargs)

    monkeypatch.setattr(
        "maru.events.services.publish_domain_event",
        fail_second_publish,
    )

    with pytest.raises(RuntimeError, match="second bulk effect failure"):
        bulk_transition_editions(
            organization_id=first.organization_id,
            edition_ids=(first.id, second.id),
            to_state=EventEdition.Lifecycle.PREPARING,
            actor=actor,
            reason="Exercise atomic bulk effect rollback.",
            correlation_id=correlation_id,
        )

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.lifecycle == EventEdition.Lifecycle.DRAFT
    assert second.lifecycle == EventEdition.Lifecycle.DRAFT
    assert not EditionLifecycleTransition.objects.filter(
        edition_id__in=(first.id, second.id)
    ).exists()
    assert not DomainEvent.objects.filter(correlation_id=correlation_id).exists()
    assert not OutboxMessage.objects.filter(
        event__correlation_id=correlation_id
    ).exists()
    failure = AuditEvent.objects.get(correlation_id=correlation_id)
    assert failure.operation == "events.edition.bulk_transition"
    assert failure.outcome == AuditEvent.Outcome.ERROR
    assert failure.reason_code == "bulk_transition_failed"
    assert "effect failure" not in str(failure.safe_metadata)


@pytest.mark.parametrize(
    "edition_ids",
    [
        [],
        [str(uuid4()), str(uuid4())],
        [str(uuid4()) for _ in range(26)],
    ],
    ids=("empty", "duplicate", "over-limit"),
)
def test_bulk_request_shape_is_bounded_before_service_execution(
    edition_ids: list[str],
) -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant_transition(actor, edition)
    if len(edition_ids) == 2:
        edition_ids[1] = edition_ids[0]

    response = _client(actor).post(
        _bulk_url(edition),
        {
            "edition_ids": edition_ids,
            "to_state": EventEdition.Lifecycle.PREPARING,
            "reason": "Malformed bulk target set.",
        },
        format="json",
    )

    assert response.status_code == 400
    assert not AuditEvent.objects.filter(
        operation="events.edition.bulk_transition"
    ).exists()
