"""Computed every-page access summaries and server-rendered preview coverage."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.template import Context
from django.test import Client, RequestFactory
from django.urls import resolve, reverse
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.authorization.models import RoleAssignment
from maru.authorization.page_access import (
    decode_page_access_target,
    encode_page_access_target,
)
from maru.authorization.policy import resolve_edition_target
from maru.core.templatetags.page_access import maru_page_access
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    RoleAssignmentFactory,
    RoleBundleFactory,
)
from tests.support.authority import create_provenance_backed_role_bundle
from tests.workforce_helpers import create_department_for_test

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


def _request(path: str, account: object) -> object:
    request = RequestFactory().get(path)
    request.user = account
    request.resolver_match = resolve(path)
    return request


def _summary(
    *,
    path: str,
    account: object,
    **context: object,
) -> object:
    return maru_page_access(Context({"request": _request(path, account), **context}))


def _decoded_manage_target(summary: object) -> object:
    match = resolve(summary.manage_url)
    target = decode_page_access_target(match.kwargs["scope_token"])
    assert target is not None
    return target


def test_component_resolves_all_mounted_management_page_families() -> None:
    edition = EventEditionFactory(name="Access Convention")
    actor = AccountFactory()
    _grant(actor, edition.organization, "authorization.manage_roles")
    organization = edition.organization
    series = edition.series
    edition_context = {
        "organization": organization,
        "convention_series": series,
        "edition": edition,
    }
    routes = (
        (
            reverse(
                "baseline-organization-record",
                kwargs={"organization_slug": organization.slug},
            ),
            {"organization": organization},
            "organization",
        ),
        (
            reverse(
                "baseline-convention-series-record",
                kwargs={
                    "organization_slug": organization.slug,
                    "series_slug": series.slug,
                },
            ),
            {"organization": organization, "convention_series": series},
            "organization",
        ),
        (
            reverse(
                "baseline-event-edition-record",
                kwargs={
                    "organization_slug": organization.slug,
                    "series_slug": series.slug,
                    "edition_slug": edition.slug,
                },
            ),
            edition_context,
            "edition",
        ),
        (
            reverse(
                "registration-setup",
                kwargs={
                    "organization_slug": organization.slug,
                    "series_slug": series.slug,
                    "edition_slug": edition.slug,
                },
            ),
            edition_context,
            "edition",
        ),
        (
            reverse(
                "registration-commerce-workspace",
                args=(organization.slug, series.slug, edition.slug),
            ),
            edition_context,
            "edition",
        ),
        (
            reverse(
                "application-definition-workspace",
                args=(organization.id, edition.id),
            ),
            {"edition": edition},
            "edition",
        ),
        (
            reverse(
                "charity-workspace",
                args=(organization.slug, series.slug, edition.slug),
            ),
            edition_context,
            "edition",
        ),
        (
            reverse(
                "venue-workspace",
                args=(organization.slug, series.slug, edition.slug),
            ),
            edition_context,
            "edition",
        ),
        (
            reverse(
                "catalog-staff-workspace",
                args=(organization.slug, series.slug, edition.slug),
            ),
            edition_context,
            "edition",
        ),
        (
            reverse(
                "organization-structure",
                args=(organization.slug, series.slug, edition.slug),
            ),
            edition_context,
            "edition",
        ),
        (reverse("management-console"), edition_context, "edition"),
    )

    for path, context, expected_scope in routes:
        summary = _summary(path=path, account=actor, **context)
        assert summary.available is True
        assert summary.policy == "scoped"
        assert summary.can_manage is True
        assert summary.manage_url
        target = _decoded_manage_target(summary)
        assert target.scope_level.value == expected_scope
        assert target.organization_id == organization.id


def test_department_page_resolves_exact_department_not_selected_edition() -> None:
    edition = EventEditionFactory()
    department = create_department_for_test(
        edition=edition,
        name="Logistics",
        expected_code="logistics",
    )
    actor = AccountFactory()
    _grant(actor, edition.organization, "authorization.manage_roles")
    path = reverse(
        "organization-structure-department",
        args=(
            edition.organization.slug,
            edition.series.slug,
            edition.slug,
            department.id,
        ),
    )

    summary = _summary(
        path=path,
        account=actor,
        organization=edition.organization,
        convention_series=edition.series,
        edition=edition,
        department=department,
    )

    target = _decoded_manage_target(summary)
    assert target.scope_level.value == "department"
    assert target.department_id == department.id


def test_fixed_policy_pages_explain_audiences_without_mutation_links() -> None:
    edition = EventEditionFactory()
    account = AccountFactory(is_staff=True, is_superuser=True)
    cases = (
        (
            reverse("baseline-admin-home"),
            {},
            "platform",
        ),
        (
            reverse(
                "organization-representation",
                args=(edition.organization.slug,),
            ),
            {"organization": edition.organization},
            "representation",
        ),
        (
            reverse(
                "application-review-workspace",
                args=(edition.organization_id, edition.id),
            ),
            {"edition": edition},
            "safeguarding",
        ),
        (
            reverse("my-applications", args=(edition.organization_id, edition.id)),
            {"edition": edition, "maru_personal_surface": True},
            "self",
        ),
        (
            reverse("paid-attendee-directory", args=(edition.id,)),
            {"edition": edition},
            "attendee_audience",
        ),
        (
            reverse("admin:identity_account_changelist"),
            {"opts": SimpleNamespace(app_label="identity")},
            "security",
        ),
    )

    for path, context, policy in cases:
        summary = _summary(path=path, account=account, **context)
        assert summary.available is True
        assert summary.policy == policy
        assert summary.can_manage is False
        assert summary.manage_url == ""
        assert summary.preview_url == ""
        assert summary.explanation


def test_signed_target_is_tenant_scoped_and_tampering_discloses_nothing() -> None:
    own_edition = EventEditionFactory()
    foreign_edition = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, own_edition.organization, "authorization.manage_roles")
    hidden_person = AccountFactory(
        email="hidden-access@example.invalid",
        display_name="Hidden Access Person",
    )
    hidden_role = RoleBundleFactory(
        organization=foreign_edition.organization,
        name="Hidden Foreign Group",
        capability_codes=["events.view_basic"],
    )
    RoleAssignmentFactory(
        organization=foreign_edition.organization,
        edition=foreign_edition,
        principal=hidden_person,
        role_bundle=hidden_role,
    )
    target = resolve_edition_target(
        organization_id=foreign_edition.organization_id,
        edition_id=foreign_edition.id,
    )
    assert target is not None
    token = encode_page_access_target(target)
    client = Client()
    client.force_login(actor)

    denied = client.get(reverse("page-access-workspace", kwargs={"scope_token": token}))
    tampered = client.get(
        reverse("page-access-workspace", kwargs={"scope_token": f"{token}x"})
    )

    assert denied.status_code == 403
    assert tampered.status_code == 404
    content = denied.content.decode()
    assert "hidden-access@example.invalid" not in content
    assert "Hidden Access Person" not in content
    assert "Hidden Foreign Group" not in content
    denial = AuditEvent.objects.get(
        principal_id=actor.id,
        operation="authorization.page_access.relationships.view",
        outcome=AuditEvent.Outcome.DENY,
    )
    assert denial.organization_id == foreign_edition.organization_id


def test_html_preview_modes_are_audited_capped_and_remove_all_write_controls() -> None:
    edition = EventEditionFactory(name="Preview Convention")
    viewer = AccountFactory(display_name="Real Viewer")
    person = AccountFactory(
        email="preview-person@example.invalid",
        display_name="Preview Person",
    )
    _grant(viewer, edition.organization, "authorization.manage_roles")
    role = RoleBundleFactory(
        organization=edition.organization,
        code="preview-front-desk",
        name="Preview Front Desk",
        capability_codes=["participation.view_staff_summary"],
    )
    RoleAssignmentFactory(
        organization=edition.organization,
        edition=edition,
        principal=person,
        role_bundle=role,
    )
    target = resolve_edition_target(
        organization_id=edition.organization_id,
        edition_id=edition.id,
    )
    assert target is not None
    url = reverse(
        "page-access-workspace",
        kwargs={"scope_token": encode_page_access_target(target)},
    )
    client = Client()
    client.force_login(viewer)
    assignment_count = RoleAssignment.objects.count()

    person_preview = client.post(
        url,
        {"action": "preview_person", "person_email": person.email},
    )
    role_preview = client.post(
        url,
        {"action": "preview_role", "role_version_id": str(role.id)},
    )

    for response, subject in (
        (person_preview, "Preview Person"),
        (role_preview, "Preview Front Desk v1"),
    ):
        assert response.status_code == 200
        assert "Preview only" in response.content.decode()
        assert subject in response.content.decode()
        assert "Details capped" in response.content.decode()
        assert "Assign scoped access" not in response.content.decode()
        assert 'name="action"' not in response.content.decode()
        assert "private" in response["Cache-Control"]
        assert "no-store" in response["Cache-Control"]
    assert RoleAssignment.objects.count() == assignment_count
    assert str(client.session["_auth_user_id"]) == str(viewer.id)
    assert (
        AuditEvent.objects.filter(
            principal_id=viewer.id,
            operation="authorization.access_preview.view",
            outcome=AuditEvent.Outcome.ALLOW,
        ).count()
        == 2
    )


def test_workspace_edits_real_scope_and_never_uses_preview_as_principal() -> None:
    edition = EventEditionFactory()
    recipient = AccountFactory(email="assigned-person@example.invalid")
    actor, approver, role = create_provenance_backed_role_bundle(
        edition.organization,
        code="page-access-event-reader",
        name="Page access event reader",
        capability_codes=("events.view_basic",),
    )
    target = resolve_edition_target(
        organization_id=edition.organization_id,
        edition_id=edition.id,
    )
    assert target is not None
    url = reverse(
        "page-access-workspace",
        kwargs={"scope_token": encode_page_access_target(target)},
    )
    client = Client()
    client.force_login(actor)

    created = client.post(
        url,
        {
            "action": "assign",
            "person_email": recipient.email,
            "role_version_id": str(role.id),
            "approver_email": approver.email,
            "reason": "Exact edition access for synthetic testing.",
        },
    )

    assert created.status_code == 302
    assignment = RoleAssignment.objects.get(
        principal=recipient,
        role_bundle=role,
        revoked_at__isnull=True,
    )
    assert assignment.edition_id == edition.id
    assert assignment.department_id is None
    assert assignment.resource_binding_id is None
    assert assignment.granted_by_id == actor.id
    assert assignment.approved_by_id == approver.id

    count = RoleAssignment.objects.count()
    closed_input = client.post(
        url,
        {
            "action": "assign",
            "person_email": recipient.email,
            "role_version_id": str(role.id),
            "approver_email": approver.email,
            "reason": "Preview state must never select an acting principal.",
            "preview_person_email": approver.email,
        },
    )
    assert closed_input.status_code == 400
    assert RoleAssignment.objects.count() == count
    assert str(client.session["_auth_user_id"]) == str(actor.id)

    outsider = AccountFactory()
    client.force_login(outsider)
    denied = client.post(
        url,
        {
            "action": "revoke",
            "assignment_id": str(assignment.id),
            "reason": "A previewed manager must not authorize this request.",
        },
    )
    assert denied.status_code == 403
    assignment.refresh_from_db()
    assert assignment.revoked_at is None
