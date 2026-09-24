import json
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import PermissionDenied
from jsonschema import Draft202012Validator
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.audit.programme_exit_queries import (
    GENERATION_OPERATIONS,
    load_programme_exit_audit,
)
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.programme_exit_queries import load_programme_exit_authorization
from maru.programme import archive_authorization
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
)
from tests.integration.test_programme_queries import _TrustedAuthorizer

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


@pytest.mark.django_db(transaction=True)
def test_native_exit_foundations_keep_independent_real_rights_and_exact_receipts(
    monkeypatch,
):
    edition, other_edition = EventEditionFactory(), EventEditionFactory()
    actor, other_actor = AccountFactory(), AccountFactory()
    for code in ("audit.view_security", "events.view_basic"):
        CapabilityGrantFactory(
            principal=actor, organization=edition.organization, capability_code=code
        )
    monkeypatch.setattr(
        archive_authorization, "profile_allows_adapter", lambda *_: True
    )
    correlation = uuid4()
    args = {
        "actor_id": actor.id,
        "organization_id": edition.organization_id,
        "edition_id": edition.id,
        "correlation_id": correlation,
        "programme_authorizer": _TrustedAuthorizer(),
    }
    configuration = load_programme_exit_authorization(**args)
    assert json.loads(configuration.data)["recipes"] == []
    Draft202012Validator(json.loads(configuration.schema)).validate(
        json.loads(configuration.data)
    )
    base = AuditRecord(
        principal_kind="account",
        principal_id=actor.id,
        principal_context_id=None,
        organization_id=edition.organization_id,
        event_edition_id=edition.id,
        capability_code="events.view_basic",
        operation="events.query.programme_exit",
        target_type="events.event_edition",
        target_id=edition.id,
        outcome="allow",
        reason_code="synthetic",
        correlation_id=correlation,
        source_channel="test",
        safe_metadata={"access_purpose": "Do not export this private rationale"},
    )
    included = [
        append_audit(replace(base, operation=operation)).id
        for operation in sorted(
            GENERATION_OPERATIONS - {"authorization.programme_exit.read"}
        )
    ]
    excluded = [
        append_audit(replace(base, **changed)).id
        for changed in (
            {"principal_id": other_actor.id},
            {"correlation_id": uuid4()},
            {
                "event_edition_id": other_edition.id,
                "organization_id": other_edition.organization_id,
            },
            {"outcome": "deny"},
            {"operation": "synthetic.other-operation"},
        )
    ]
    result = load_programme_exit_audit(**args)
    data = json.loads(result.data)
    Draft202012Validator(json.loads(result.schema)).validate(data)
    identities = {row["id"] for row in data["receipts"]}
    assert len(identities) == 7
    assert set(map(str, included)) <= identities
    assert not identities.intersection(map(str, excluded))
    assert b"rationale" not in result.data
    assert b"target_id" not in result.data
    assert (
        AuditEvent.objects.filter(
            operation="audit.programme_exit.read", correlation_id=correlation
        ).count()
        == 1
    )
    for query in (load_programme_exit_audit, load_programme_exit_authorization):
        with pytest.raises(PermissionDenied):
            query(**{**args, "actor_id": other_actor.id})
        with pytest.raises(ProgrammeAuthorizationDeniedError):
            query(**{**args, "edition_id": other_edition.id})


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
