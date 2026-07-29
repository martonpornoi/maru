from uuid import UUID, uuid4

import pytest
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _append_event(
    *,
    organization_id: UUID,
    edition_id: UUID,
    principal_id: UUID,
    outcome: str = AuditEvent.Outcome.ALLOW,
) -> AuditEvent:
    return append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=principal_id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code="events.transition",
            operation="events.edition.transition",
            target_type="events.event_edition",
            target_id=edition_id,
            outcome=outcome,
            reason_code="direct_grant",
            correlation_id=uuid4(),
            source_channel="api",
            changed_fields=("lifecycle",),
        )
    )


def _url(organization_id: UUID) -> str:
    return f"/api/v1/organizations/{organization_id}/audit-events"


def test_audit_query_is_tenant_scoped_minimized_and_self_auditing() -> None:
    edition = EventEditionFactory()
    other_edition = EventEditionFactory()
    account = AccountFactory()
    CapabilityGrantFactory(
        principal=account,
        organization=edition.organization,
        capability_code="audit.view_security",
    )
    own = _append_event(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        principal_id=account.id,
    )
    other = _append_event(
        organization_id=other_edition.organization_id,
        edition_id=other_edition.id,
        principal_id=AccountFactory().id,
    )
    request_id = uuid4()
    client = APIClient()
    client.force_authenticate(account)

    response = client.get(
        _url(edition.organization_id),
        {"purpose": "security_investigation"},
        HTTP_X_REQUEST_ID=str(request_id),
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["id"] == str(own.id)
    assert str(other.id) not in str(payload)
    assert "safe_metadata" not in payload[0]
    assert "obligations" not in payload[0]
    access = AuditEvent.objects.get(
        correlation_id=request_id,
        operation="audit.event.search",
    )
    assert access.outcome == AuditEvent.Outcome.ALLOW
    assert access.safe_metadata["access_purpose"] == "security_investigation"
    assert access.safe_metadata["target_count"] == 1


def test_audit_query_filters_only_inside_authorized_tenant() -> None:
    edition = EventEditionFactory()
    account = AccountFactory()
    CapabilityGrantFactory(
        principal=account,
        organization=edition.organization,
        capability_code="audit.view_security",
    )
    allowed = _append_event(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        principal_id=account.id,
        outcome=AuditEvent.Outcome.DENY,
    )
    _append_event(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        principal_id=AccountFactory().id,
    )
    client = APIClient()
    client.force_authenticate(account)

    response = client.get(
        _url(edition.organization_id),
        {
            "purpose": "compliance_review",
            "principal_id": str(account.id),
            "outcome": "deny",
            "limit": 1,
        },
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(allowed.id)]


def test_audit_query_denies_before_revealing_scope_or_count() -> None:
    edition = EventEditionFactory()
    account = AccountFactory()
    request_id = uuid4()
    _append_event(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        principal_id=AccountFactory().id,
    )
    client = APIClient()
    client.force_authenticate(account)

    response = client.get(
        _url(edition.organization_id),
        {"purpose": "security_investigation"},
        HTTP_X_REQUEST_ID=str(request_id),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "permission_absent"
    assert "count" not in str(response.json())
    denial = AuditEvent.objects.get(correlation_id=request_id)
    assert denial.outcome == AuditEvent.Outcome.DENY
    assert "target_count" not in denial.safe_metadata


def test_authorized_audit_query_requires_a_bounded_purpose() -> None:
    edition = EventEditionFactory()
    account = AccountFactory()
    CapabilityGrantFactory(
        principal=account,
        organization=edition.organization,
        capability_code="audit.view_security",
    )
    client = APIClient()
    client.force_authenticate(account)

    missing = client.get(_url(edition.organization_id))
    invented = client.get(
        _url(edition.organization_id),
        {"purpose": "curiosity"},
    )

    assert missing.status_code == 400
    assert invented.status_code == 400
