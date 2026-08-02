from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.db import DatabaseError
from django.test import Client
from django.urls import resolve, reverse

from maru.audit.models import AuditEvent
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.models import CapabilityGrant
from maru.events.admin_context import ADMIN_EDITION_SESSION_KEY
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import OrganizationMembership
from maru.participation.models import Participation
from maru.registration.models import Registration
from maru.workforce.models import Department, PositionAssignment
from tests.factories import AccountFactory, CapabilityGrantFactory, EventEditionFactory
from tests.support.authority import activate_synthetic_board

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _url(edition: EventEdition) -> str:
    return reverse(
        "organization-structure",
        args=[
            edition.organization.slug,
            edition.series.slug,
            edition.slug,
        ],
    )


def _client(account: Account) -> Client:
    client = Client()
    client.force_login(account)
    return client


def _grant(
    *,
    account: Account,
    edition: EventEdition,
    capability_code: str = "workforce.view_structure",
    department: Department | None = None,
) -> CapabilityGrant:
    return CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        department=department,
        principal=account,
        capability_code=capability_code,
    )


def _relationship_counts(account: Account) -> dict[str, int]:
    return {
        "memberships": OrganizationMembership.objects.filter(account=account).count(),
        "participations": Participation.objects.filter(account=account).count(),
        "registrations": Registration.objects.filter(account=account).count(),
        "workforce_assignments": PositionAssignment.objects.filter(
            account=account
        ).count(),
        "received_grants": CapabilityGrant.objects.filter(principal=account).count(),
    }


def test_page_09_has_one_canonical_collision_safe_route() -> None:
    edition = EventEditionFactory()
    expected = (
        f"/admin/platform/organizations/{edition.organization.slug}/series/"
        f"{edition.series.slug}/editions/{edition.slug}/structure/"
    )

    assert _url(edition) == expected
    assert resolve(expected).url_name == "organization-structure"
    assert resolve("/admin/workforce/department/").url_name.endswith(
        "workforce_department_changelist"
    )


def test_platform_oversight_sees_an_honest_empty_tree_without_participating() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    edition = EventEditionFactory(name="Synthetic Empty Structure Edition")
    before = _relationship_counts(administrator)

    response = _client(administrator).get(_url(edition))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'data-page="organization-structure"' in content
    assert content.count('class="maru-admin-brand"') == 1
    assert "Organization structure" in content
    assert "Synthetic Empty Structure Edition" in content
    assert "Executive Board" in content
    assert "Absent" in content
    assert "No operational Departments yet" in content
    assert "Platform oversight" in content
    assert "Structure manager" in content
    assert "not a Department" in content
    assert content.count('aria-current="page"') == 1
    assert "?view=structure" not in content
    assert _relationship_counts(administrator) == before
    audit = AuditEvent.objects.get(operation="workforce.structure.read")
    assert audit.principal_id == administrator.id
    assert audit.organization_id == edition.organization_id
    assert audit.event_edition_id == edition.id
    assert audit.target_id == edition.id
    assert audit.source_channel == "web"
    assert audit.outcome == AuditEvent.Outcome.ALLOW
    assert audit.safe_metadata == {
        "policy_version": POLICY_VERSION,
        "route_name": "organization-structure",
        "http_method": "GET",
    }
    assert "audit_sensitive_read" in audit.obligations


def test_page_09_renders_the_persisted_tree_beneath_separate_governance() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    edition = EventEditionFactory(name="Synthetic Nested Structure Edition")
    helper = Department.objects.create(
        organization=edition.organization,
        edition=edition,
        code="helper-board",
        name="Helper Board",
        description="Coordinates the edition Departments.",
        position=0,
    )
    Department.objects.create(
        organization=edition.organization,
        edition=edition,
        parent=helper,
        code="registration",
        name="Registration",
        description="Runs attendee registration.",
        position=20,
    )
    Department.objects.create(
        organization=edition.organization,
        edition=edition,
        parent=helper,
        code="executive-board",
        name="Executive Board",
        description="A deliberately same-named legacy operational Department.",
        position=10,
    )

    response = _client(administrator).get(_url(edition))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Complete bounded tree" in content
    assert "Helper Board" in content
    assert "Registration" in content
    assert "Runs attendee registration." in content
    # The fixed governance anchor and same-named operational record remain
    # separate and truthful; the read projector does not repair or infer either.
    assert content.count("Executive Board") >= 2
    assert content.index("Executive Board") < content.index("Helper Board")
    assert content.index("A deliberately same-named") > content.index("Helper Board")
    assert str(helper.id) not in content


def test_exact_view_and_manage_decisions_are_independent_and_discoverable() -> None:
    edition = EventEditionFactory(name="Synthetic Scoped Structure Edition")
    viewer = AccountFactory(is_staff=False, is_superuser=False)
    manager = AccountFactory(is_staff=False, is_superuser=False)
    manage_only = AccountFactory(is_staff=False, is_superuser=False)
    _grant(account=viewer, edition=edition)
    _grant(account=manager, edition=edition)
    _grant(
        account=manager,
        edition=edition,
        capability_code="workforce.manage_structure",
    )
    _grant(
        account=manage_only,
        edition=edition,
        capability_code="workforce.manage_structure",
    )

    viewer_response = _client(viewer).get(_url(edition))
    manager_response = _client(manager).get(_url(edition))
    denied_response = _client(manage_only).get(_url(edition))

    assert viewer_response.status_code == 200
    assert "Exact edition capability" in viewer_response.content.decode()
    assert "Structure manager" not in viewer_response.content.decode()
    assert manager_response.status_code == 200
    assert "Structure manager" in manager_response.content.decode()
    assert denied_response.status_code in {403, 404}
    assert edition.name not in denied_response.content.decode()

    viewer_client = _client(viewer)
    selected = viewer_client.post(
        reverse("admin-edition-context"),
        {
            "edition_id": str(edition.id),
            "next": reverse("admin:index"),
        },
        follow=True,
    )
    selected_content = selected.content.decode()
    assert selected.status_code == 200
    assert viewer_client.session[ADMIN_EDITION_SESSION_KEY] == str(edition.id)
    assert edition.name in selected_content
    assert selected_content.count(f'href="{_url(edition)}"') == 1
    assert "?view=structure" not in selected_content


def test_board_staff_department_and_session_context_do_not_imply_page_access() -> None:
    edition = EventEditionFactory(name="Protected Structure Edition")
    foreign_name = edition.organization.name
    controller, _approver = activate_synthetic_board(edition.organization)
    department_user = AccountFactory()
    staff_only = AccountFactory(is_staff=True, is_superuser=False)
    selected_only = AccountFactory()
    department = Department.objects.create(
        organization=edition.organization,
        edition=edition,
        code="narrow-department",
        name="Narrow Department",
    )
    _grant(account=department_user, edition=edition, department=department)

    selected_client = _client(selected_only)
    session = selected_client.session
    session[ADMIN_EDITION_SESSION_KEY] = str(edition.id)
    session.save()

    for account_or_client in (
        controller,
        department_user,
        staff_only,
        selected_client,
    ):
        client = (
            account_or_client
            if isinstance(account_or_client, Client)
            else _client(account_or_client)
        )
        response = client.get(_url(edition))
        assert response.status_code in {403, 404}
        assert foreign_name not in response.content.decode()
        assert edition.name not in response.content.decode()


def test_anonymous_inactive_foreign_and_unknown_routes_disclose_no_scope() -> None:
    edition = EventEditionFactory(name="Hidden Exact Structure Edition")
    viewer = AccountFactory()
    inactive = AccountFactory(is_active=False)
    foreign = EventEditionFactory(name="Foreign Structure Edition")
    _grant(account=viewer, edition=edition)

    anonymous = Client().get(_url(edition))
    inactive_response = _client(inactive).get(_url(edition))
    mismatched = _client(viewer).get(
        reverse(
            "organization-structure",
            args=[
                foreign.organization.slug,
                foreign.series.slug,
                edition.slug,
            ],
        )
    )
    unknown = _client(viewer).get(
        reverse(
            "organization-structure",
            args=[
                edition.organization.slug,
                edition.series.slug,
                "unknown-structure-edition",
            ],
        )
    )

    assert anonymous.status_code == 302
    assert anonymous.url.startswith("/accounts/login/")
    assert inactive_response.status_code == 302
    assert inactive_response.url.startswith("/accounts/login/")
    for response in (mismatched, unknown):
        assert response.status_code in {403, 404}
        content = response.content.decode()
        assert edition.name not in content
        assert foreign.name not in content


def test_projection_overflow_is_explicit_and_never_renders_partial_rows() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    edition = EventEditionFactory()
    overflow = SimpleNamespace(
        state="structure_limit_exceeded",
        departments=(),
    )

    with patch(
        "maru.workforce.views.project_edition_structure",
        return_value=overflow,
    ):
        response = _client(administrator).get(_url(edition))

    content = response.content.decode()
    assert response.status_code == 200
    assert "complete hierarchy is too large" in content
    assert "did not truncate" in content
    assert "Department hierarchy" not in content


def test_dependency_failure_is_generic_and_contains_no_partial_scope() -> None:
    viewer = AccountFactory()
    edition = EventEditionFactory(name="Private Failure Structure Edition")
    _grant(account=viewer, edition=edition)

    with patch(
        "maru.workforce.views.project_edition_structure",
        side_effect=DatabaseError("private database detail"),
    ):
        response = _client(viewer).get(_url(edition))

    content = response.content.decode()
    assert response.status_code == 503
    assert "Organization structure unavailable" in content
    assert "private database detail" not in content
    assert edition.name not in content
    assert edition.organization.name not in content
    assert "did not show a partial" in content
    assert "hierarchy" in content


def test_audit_failure_prevents_html_projection_release() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    edition = EventEditionFactory(name="Private unaudited HTML edition")

    with patch(
        "maru.workforce.views.append_structure_read_audit",
        side_effect=DatabaseError("private audit detail"),
    ):
        response = _client(administrator).get(_url(edition))

    content = response.content.decode()
    assert response.status_code == 503
    assert "Organization structure unavailable" in content
    assert "Private unaudited HTML edition" not in content
    assert "private audit detail" not in content
