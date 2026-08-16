from datetime import timedelta
from uuid import uuid4

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.authorization.models import CapabilityGrant, RoleAssignment
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    RoleAssignmentFactory,
    RoleBundleFactory,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]


def _grant(account: object, organization: object, capability_code: str) -> None:
    CapabilityGrantFactory(
        principal=account,
        organization=organization,
        capability_code=capability_code,
        effective_from=timezone.now() - timedelta(minutes=1),
    )


def _client(account: object) -> APIClient:
    client = APIClient()
    client.force_login(account)
    return client


def _preview_url(edition: object) -> str:
    return reverse(
        "api-edition-access-preview",
        kwargs={
            "organization_id": edition.organization_id,
            "edition_id": edition.id,
        },
    )


def _workspace_url(edition: object) -> str:
    return reverse(
        "api-edition-access-workspace",
        kwargs={
            "organization_id": edition.organization_id,
            "edition_id": edition.id,
        },
    )


def test_exact_person_preview_is_audited_capped_and_session_safe() -> None:
    edition = EventEditionFactory(name="Synthetic Gathering 2031")
    manager = AccountFactory(display_name="Access Manager")
    person = AccountFactory(
        email="helper@example.invalid",
        display_name="Helpful Person",
    )
    _grant(manager, edition.organization, "authorization.manage_roles")
    front_desk = RoleBundleFactory(
        organization=edition.organization,
        code="front-desk-preview",
        name="Front Desk Preview",
        capability_codes=["participation.view_staff_summary"],
    )
    RoleAssignmentFactory(
        organization=edition.organization,
        edition=edition,
        principal=person,
        role_bundle=front_desk,
    )
    assignment_count = RoleAssignment.objects.count()
    grant_count = CapabilityGrant.objects.count()

    client = _client(manager)
    response = client.post(
        _preview_url(edition),
        {"mode": "person", "person_email": "HELPER@example.invalid"},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["mode"] == "person"
    assert response.data["subject_label"] == "Helpful Person"
    assert response.data["scope_label"] == "Synthetic Gathering 2031"
    assert response.data["session_unchanged"] is True
    assert response.data["mutation_allowed"] is False
    capability = next(
        item
        for item in response.data["capabilities"]
        if item["capability_code"] == "participation.view_staff_summary"
    )
    assert capability["source_category"] == "immutable_role"
    assert capability["data_preview_available"] is False
    assert capability["visible_fields"] == []
    assert capability["disclosure_limited"] is True
    assert RoleAssignment.objects.count() == assignment_count
    assert CapabilityGrant.objects.count() == grant_count
    assert str(client.session["_auth_user_id"]) == str(manager.id)

    audit = AuditEvent.objects.get(
        principal_id=manager.id,
        operation="authorization.access_preview.view",
    )
    assert audit.outcome == AuditEvent.Outcome.ALLOW
    assert audit.target_id == person.id
    assert audit.safe_metadata["access_purpose"] == (
        "access-preview:person:session-unchanged"
    )
    assert "helper@example.invalid" not in str(audit.safe_metadata)


def test_person_preview_discloses_only_fields_the_viewer_can_also_read() -> None:
    edition = EventEditionFactory()
    manager = AccountFactory()
    person = AccountFactory(email="field-preview@example.invalid")
    _grant(manager, edition.organization, "authorization.manage_roles")
    CapabilityGrantFactory(
        principal=manager,
        organization=edition.organization,
        edition=edition,
        capability_code="participation.view_staff_summary",
        effective_from=timezone.now() - timedelta(minutes=1),
    )
    role = RoleBundleFactory(
        organization=edition.organization,
        code="staff-summary-preview",
        capability_codes=["participation.view_staff_summary"],
    )
    RoleAssignmentFactory(
        organization=edition.organization,
        edition=edition,
        principal=person,
        role_bundle=role,
    )

    response = _client(manager).post(
        _preview_url(edition),
        {"mode": "person", "person_email": person.email},
        format="json",
    )

    assert response.status_code == 200
    capability = next(
        item
        for item in response.data["capabilities"]
        if item["capability_code"] == "participation.view_staff_summary"
    )
    assert capability["data_preview_available"] is True
    assert set(capability["visible_fields"]) == {
        "account_id",
        "capacity_labels",
        "display_name",
        "participation_status",
    }
    assert capability["disclosure_limited"] is False


def test_role_preview_uses_the_exact_immutable_version_without_assigning_it() -> None:
    edition = EventEditionFactory()
    manager = AccountFactory()
    _grant(manager, edition.organization, "authorization.manage_roles")
    old_role = RoleBundleFactory(
        organization=edition.organization,
        code="registration-preview",
        name="Registration",
        version=1,
        capability_codes=["events.view_basic"],
    )
    RoleBundleFactory(
        organization=edition.organization,
        code="registration-preview",
        name="Registration",
        version=2,
        capability_codes=["registration.view_service_summary"],
    )
    assignment_count = RoleAssignment.objects.count()

    response = _client(manager).post(
        _preview_url(edition),
        {"mode": "role", "role_version_id": str(old_role.id)},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["mode"] == "role"
    assert response.data["subject_label"] == "Registration v1"
    assert {item["capability_code"] for item in response.data["capabilities"]} == {
        "events.view_basic"
    }
    assert response.data["capabilities"][0]["source_category"] == ("hypothetical_role")
    assert RoleAssignment.objects.count() == assignment_count


def test_preview_rejects_cross_tenant_role_and_unknown_input_fields() -> None:
    edition = EventEditionFactory()
    foreign_edition = EventEditionFactory()
    manager = AccountFactory()
    _grant(manager, edition.organization, "authorization.manage_roles")
    foreign_role = RoleBundleFactory(
        organization=foreign_edition.organization,
        capability_codes=["events.view_basic"],
    )
    client = _client(manager)

    foreign_response = client.post(
        _preview_url(edition),
        {"mode": "role", "role_version_id": str(foreign_role.id)},
        format="json",
    )
    unknown_response = client.post(
        _preview_url(edition),
        {
            "mode": "person",
            "person_email": "missing@example.invalid",
            "is_superuser": True,
        },
        format="json",
    )

    assert foreign_response.status_code == 400
    assert foreign_response.data["errors"]["role_version_id"] == (
        "Choose an available immutable role version."
    )
    assert unknown_response.status_code == 400
    assert unknown_response.data["errors"]["is_superuser"] == "Unexpected field."
    assert not RoleAssignment.objects.filter(
        organization=edition.organization,
        principal=manager,
    ).exists()


def test_preview_denial_does_not_disclose_subject_or_role() -> None:
    edition = EventEditionFactory()
    viewer = AccountFactory()
    hidden_person = AccountFactory(
        email="hidden-preview@example.invalid",
        display_name="Hidden Preview Person",
    )
    role = RoleBundleFactory(
        organization=edition.organization,
        name="Hidden Preview Role",
        capability_codes=["events.view_basic"],
    )

    person_response = _client(viewer).post(
        _preview_url(edition),
        {"mode": "person", "person_email": hidden_person.email},
        format="json",
    )
    role_response = _client(viewer).post(
        _preview_url(edition),
        {"mode": "role", "role_version_id": str(role.id)},
        format="json",
    )

    assert person_response.status_code == 403
    assert role_response.status_code == 403
    combined = person_response.content.decode() + role_response.content.decode()
    assert "hidden-preview@example.invalid" not in combined
    assert "Hidden Preview Person" not in combined
    assert "Hidden Preview Role" not in combined
    denials = AuditEvent.objects.filter(
        principal_id=viewer.id,
        operation="authorization.access_preview.view",
        outcome=AuditEvent.Outcome.DENY,
    )
    assert denials.count() == 2


def test_preview_endpoint_supports_no_mutating_http_verbs() -> None:
    edition = EventEditionFactory()
    manager = AccountFactory()
    _grant(manager, edition.organization, "authorization.manage_roles")
    client = _client(manager)
    url = _preview_url(edition)

    assert client.get(url).status_code == 405
    assert client.patch(url, {}, format="json").status_code == 405
    assert client.put(url, {}, format="json").status_code == 405
    assert client.delete(url, {}, format="json").status_code == 405


def test_access_workspace_exposes_computed_scope_and_exact_role_version() -> None:
    edition = EventEditionFactory(name="Exact Edition")
    manager = AccountFactory()
    _grant(manager, edition.organization, "authorization.manage_roles")
    role = RoleBundleFactory(
        organization=edition.organization,
        code=f"preview-{uuid4().hex[:12]}",
        version=3,
        capability_codes=["events.view_basic"],
    )

    response = _client(manager).get(_workspace_url(edition))

    assert response.status_code == 200
    assert response.data["effective_access"]["scope_level"] == "edition"
    assert response.data["effective_access"]["scope_label"] == "Exact Edition"
    assert response.data["effective_access"]["can_manage_access"] is True
    manage_action = next(
        action
        for action in response.data["effective_access"]["actions"]
        if action["capability_code"] == "authorization.manage_roles"
    )
    assert manage_action["allowed"] is True
    assert manage_action["source_category"] in {
        "direct_grant",
        "immutable_role",
        "platform_oversight",
    }
    group = next(
        group for group in response.data["groups"] if group["code"] == role.code
    )
    assert group["role_version_id"] == str(role.id)
    assert group["version"] == 3
