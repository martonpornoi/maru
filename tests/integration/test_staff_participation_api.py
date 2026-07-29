from uuid import uuid4

import pytest
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    ParticipationCapacityFactory,
    ParticipationFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _authorized_world():
    edition = EventEditionFactory()
    staff = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=staff,
        capability_code="participation.view_staff_summary",
    )
    participant = ParticipationFactory(edition=edition)
    ParticipationCapacityFactory(
        participation=participant,
        code="volunteer",
        label_snapshot="Volunteer",
    )
    return edition, staff, participant


def test_staff_participation_list_is_minimized_filterable_and_audited() -> None:
    edition, staff, participation = _authorized_world()
    other = ParticipationFactory(edition=edition)
    ParticipationCapacityFactory(
        participation=other,
        code="attendee",
        label_snapshot="Attendee",
    )
    client = APIClient()
    client.force_authenticate(staff)

    request_id = uuid4()
    response = client.get(
        f"/api/v1/organizations/{edition.organization_id}/"
        f"editions/{edition.id}/participations",
        {"search": participation.account.display_name, "capacity": "Volunteer"},
        HTTP_X_REQUEST_ID=str(request_id),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["results"] == [
        {
            "account_id": str(participation.account_id),
            "display_name": participation.account.display_name,
            "participation_status": participation.status,
            "capacity_labels": ["Volunteer"],
        }
    ]
    serialized = str(payload)
    assert participation.account.email not in serialized
    assert str(participation.id) not in serialized
    assert response["X-Request-ID"] == str(request_id)
    audit = AuditEvent.objects.get(correlation_id=request_id)
    assert audit.outcome == AuditEvent.Outcome.ALLOW
    assert audit.safe_metadata["target_count"] == 1


def test_staff_participation_detail_queries_tenant_before_target() -> None:
    edition, staff, participation = _authorized_world()
    other = ParticipationFactory()
    client = APIClient()
    client.force_authenticate(staff)
    base = (
        f"/api/v1/organizations/{edition.organization_id}/"
        f"editions/{edition.id}/participations"
    )

    allowed = client.get(f"{base}/{participation.account_id}")
    request_id = uuid4()
    hidden = client.get(
        f"{base}/{other.account_id}",
        HTTP_X_REQUEST_ID=str(request_id),
    )

    assert allowed.status_code == 200
    assert allowed.json()["display_name"] == participation.account.display_name
    assert hidden.status_code == 404
    assert str(other.account_id) not in str(hidden.json())
    hidden_audit = AuditEvent.objects.get(correlation_id=request_id)
    assert hidden_audit.reason_code == "participation_unavailable"


def test_staff_participation_access_does_not_cross_edition_or_tenant() -> None:
    edition, staff, participation = _authorized_world()
    same_organization_other_edition = EventEditionFactory(
        organization=edition.organization,
        series=edition.series,
    )
    other_tenant = EventEditionFactory()
    client = APIClient()
    client.force_authenticate(staff)

    for target in (same_organization_other_edition, other_tenant):
        request_id = uuid4()
        response = client.get(
            f"/api/v1/organizations/{target.organization_id}/"
            f"editions/{target.id}/participations",
            HTTP_X_REQUEST_ID=str(request_id),
        )
        assert response.status_code == 403
        assert participation.account.display_name not in str(response.json())
        audit = AuditEvent.objects.get(correlation_id=request_id)
        assert audit.outcome == AuditEvent.Outcome.DENY


def test_staff_participation_unknown_target_and_anonymous_are_safe() -> None:
    edition, staff, _participation = _authorized_world()
    base = (
        f"/api/v1/organizations/{edition.organization_id}/"
        f"editions/{edition.id}/participations"
    )

    assert APIClient().get(base).status_code in {401, 403}
    client = APIClient()
    client.force_authenticate(staff)
    response = client.get(f"{base}/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["code"] == "participation_unavailable"
