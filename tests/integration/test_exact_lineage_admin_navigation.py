"""Exact-lineage fences for every tenant-name projection in the admin shell."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from django.db import connection, transaction
from django.test import Client, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from maru.authorization import policy
from maru.authorization.activation import activate_authority_provenance
from maru.authorization.commands import (
    assign_role,
    create_role_bundle_version,
    grant_capability_direct,
    revoke_capability_grant,
)
from maru.authorization.models import (
    AuthorityControl,
    CapabilityGrant,
    RoleAssignment,
    ScopedResourceBinding,
)
from maru.authorization.policy import (
    resolve_department_target,
    resolve_edition_target,
    resolve_organization_target,
    resolve_resource_target,
)
from maru.authorization.provenance import (
    AuthorityIssuanceCurrentCheck,
    ControlHorizonMode,
    authority_issuance_is_current,
    authority_issuances_are_current,
)
from maru.events.admin_context import ADMIN_EDITION_SESSION_KEY
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import Organization
from maru.organizations.representation import EXECUTIVE_BOARD_ROLE_CODE
from maru.workforce.models import Department, Position, PositionTemplate
from tests.factories import (
    AccountFactory,
    EventEditionFactory,
    OrganizationFactory,
    RoleAssignmentFactory,
    RoleBundleFactory,
)
from tests.support.authority import activate_synthetic_board

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("proves_safe_runtime_database_role"),
]


@dataclass(frozen=True, slots=True)
class _ExactNavigationGraph:
    organization: Organization
    edition: EventEdition
    actor: Account
    approver: Account
    direct_recipient: Account
    role_recipient: Account
    direct_source: CapabilityGrant | None
    role_source: CapabilityGrant | None
    direct_grants: tuple[CapabilityGrant, ...]
    role_assignment: RoleAssignment | None


def _client(account: Account) -> Client:
    client = Client()
    client.force_login(account)
    return client


def _selector_edition_ids(response: object) -> set[UUID]:
    return {
        UUID(value)
        for value in re.findall(
            r'<option\s+value="([0-9a-f-]{36})"',
            response.content.decode(),
        )
    }


def _store_selected_edition(client: Client, edition: EventEdition) -> None:
    session = client.session
    session[ADMIN_EDITION_SESSION_KEY] = str(edition.id)
    session.save()


def test_name_free_scope_resolution_has_a_constant_query_ceiling() -> None:
    organizations = OrganizationFactory.create_batch(257)
    edition = EventEditionFactory()
    organization = edition.organization
    department = Department.objects.create(
        organization=organization,
        edition=edition,
        code="bounded-scope-resolution",
        name="Bounded scope resolution",
    )
    creator = AccountFactory()
    role_bundle = RoleBundleFactory(
        organization=organization,
        capability_codes=["workforce.view_structure"],
    )
    template = PositionTemplate.objects.create(
        organization=organization,
        code="bounded-scope-position",
        name="Bounded scope position",
        description="Synthetic target-resolution evidence.",
        default_capacity_codes=["volunteer"],
        role_bundle=role_bundle,
        created_by=creator,
    )
    position = Position.objects.create(
        organization=organization,
        edition=edition,
        template=template,
        department=department,
        role_bundle=role_bundle,
        code="bounded-scope-position",
        title="Bounded scope position",
        description="Synthetic target-resolution evidence.",
        capacity_codes=["volunteer"],
        created_by=creator,
    )
    binding = ScopedResourceBinding.objects.create(
        organization=organization,
        edition=edition,
        department=department,
        resource_kind=ScopedResourceBinding.ResourceKind.WORKFORCE_POSITION,
        resource_id=position.id,
    )
    foreign_edition = EventEditionFactory()

    scope_keys: set[tuple[UUID, UUID | None, UUID | None, UUID | None]] = {
        (item.id, None, None, None) for item in organizations
    }
    organization_key = (organization.id, None, None, None)
    edition_key = (organization.id, edition.id, None, None)
    department_key = (organization.id, edition.id, department.id, None)
    resource_key = (organization.id, edition.id, department.id, binding.id)
    malformed_key = (organization.id, None, department.id, None)
    cross_tenant_key = (
        foreign_edition.organization_id,
        edition.id,
        department.id,
        binding.id,
    )
    scope_keys.update(
        {
            organization_key,
            edition_key,
            department_key,
            resource_key,
            malformed_key,
            cross_tenant_key,
        }
    )

    with CaptureQueriesContext(connection) as queries:
        targets = policy._bulk_authority_projection_targets(scope_keys)

    assert set(targets) == scope_keys - {malformed_key, cross_tenant_key}
    assert targets[organization_key] == resolve_organization_target(
        organization_id=organization.id,
    )
    assert targets[edition_key] == resolve_edition_target(
        organization_id=organization.id,
        edition_id=edition.id,
    )
    assert targets[department_key] == resolve_department_target(
        organization_id=organization.id,
        edition_id=edition.id,
        department_id=department.id,
    )
    assert targets[resource_key] == resolve_resource_target(
        organization_id=organization.id,
        edition_id=edition.id,
        department_id=department.id,
        resource_binding_id=binding.id,
    )
    assert len(queries) == 5
    for query in queries:
        sql = query["sql"].lower()
        assert "order by" not in sql
        for protected_column in (
            '"name"',
            '"slug"',
            '"title"',
            '"code"',
            '"starts_on"',
            '"ends_on"',
            '"position"',
        ):
            assert f".{protected_column}" not in sql


def _activate_exact_contract() -> None:
    activate_authority_provenance(
        actor=AccountFactory(is_staff=True, is_superuser=True),
        reason="Select exact lineage for admin-navigation integration evidence.",
        correlation_id=uuid4(),
        acknowledge_processes_stopped=True,
        source_channel="test",
    )


def _exact_navigation_graph() -> _ExactNavigationGraph:
    edition = EventEditionFactory(
        name="Exact Navigation Convention",
    )
    organization = edition.organization
    actor, approver = activate_synthetic_board(organization)
    target = resolve_organization_target(organization_id=organization.id)
    assert target is not None

    role_source = grant_capability_direct(
        actor=actor,
        approver=approver,
        recipient=actor,
        capability_code="authorization.manage_roles",
        target=target,
        effective_from=timezone.now(),
        expires_at=None,
        reason="Create the exact source for the navigation role assignment.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    direct_source = grant_capability_direct(
        actor=actor,
        approver=approver,
        recipient=actor,
        capability_code="authorization.grant_direct",
        target=target,
        effective_from=timezone.now(),
        expires_at=None,
        reason="Create the exact source for navigation grants.",
        correlation_id=uuid4(),
        source_channel="test",
    )

    direct_recipient = AccountFactory()
    direct_grants = tuple(
        grant_capability_direct(
            actor=actor,
            approver=approver,
            recipient=direct_recipient,
            capability_code=capability_code,
            target=target,
            effective_from=timezone.now(),
            expires_at=None,
            reason="Grant exact synthetic navigation access.",
            correlation_id=uuid4(),
            source_channel="test",
        )
        for capability_code in (
            "organizations.view_basic",
            "events.view_basic",
        )
    )
    for grant in direct_grants:
        actor_control = AuthorityControl.objects.get(
            issuance=grant.authority_issuance,
            role=AuthorityControl.Role.ACTOR,
        )
        assert (
            actor_control.source_issuance_id == direct_source.authority_issuance.ordinal
        )

    role = create_role_bundle_version(
        actor=actor,
        approver=approver,
        target=target,
        code="exact-navigation-reader",
        name="Exact navigation reader",
        capability_codes=(
            "organizations.view_basic",
            "events.view_basic",
        ),
        reason="Create a provenance-backed navigation role.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    role_recipient = AccountFactory()
    assignment = assign_role(
        actor=actor,
        approver=approver,
        recipient=role_recipient,
        target=target,
        role_bundle_id=role.id,
        effective_from=timezone.now(),
        expires_at=None,
        reason="Assign the exact synthetic navigation role.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    actor_control = AuthorityControl.objects.get(
        issuance=assignment.authority_issuance,
        role=AuthorityControl.Role.ACTOR,
    )
    assert actor_control.source_issuance_id == role_source.authority_issuance.ordinal

    return _ExactNavigationGraph(
        organization=organization,
        edition=edition,
        actor=actor,
        approver=approver,
        direct_recipient=direct_recipient,
        role_recipient=role_recipient,
        direct_source=direct_source,
        role_source=role_source,
        direct_grants=direct_grants,
        role_assignment=assignment,
    )


def _assert_scoped_shell_visible(
    *,
    client: Client,
    graph: _ExactNavigationGraph,
) -> None:
    response = client.get(reverse("admin:index"))
    content = response.content.decode()
    assert response.status_code == 200
    assert graph.organization.name in content
    assert graph.edition.name in content
    assert _selector_edition_ids(response) == {graph.edition.id}
    assert f'href="{reverse("management-console")}"' in content
    assert (
        client.get(
            reverse(
                "baseline-organization-record",
                args=[graph.organization.slug],
            )
        ).status_code
        == 200
    )


def _assert_scoped_shell_hidden(
    *,
    client: Client,
    graph: _ExactNavigationGraph,
) -> None:
    _store_selected_edition(client, graph.edition)
    response = client.get(reverse("admin:index"))
    content = response.content.decode()
    assert response.status_code == 200
    assert graph.organization.name not in content
    assert graph.organization.slug not in content
    assert graph.edition.name not in content
    assert not _selector_edition_ids(response)
    assert f'href="{reverse("management-console")}"' not in content
    assert ADMIN_EDITION_SESSION_KEY not in client.session
    assert client.get(reverse("management-console")).status_code == 403

    organization_url = reverse(
        "baseline-organization-record",
        args=[graph.organization.slug],
    )
    organization_response = client.get(organization_url)
    assert organization_response.status_code == 403
    assert graph.organization.name not in organization_response.content.decode()
    assert (
        client.get(
            reverse(
                "organization-representation",
                args=[graph.organization.slug],
            )
        ).status_code
        == 403
    )
    assert (
        client.post(
            reverse("admin-edition-context"),
            {
                "edition_id": str(graph.edition.id),
                "next": reverse("admin:index"),
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            reverse(
                "baseline-select-event-edition",
                args=[
                    graph.organization.slug,
                    graph.edition.series.slug,
                    graph.edition.slug,
                ],
            ),
        ).status_code
        == 403
    )
    assert ADMIN_EDITION_SESSION_KEY not in client.session


@pytest.mark.parametrize("contract_state", ["missing", "malformed"])
@override_settings(REQUIRE_EXACT_AUTHORITY_PROVENANCE=True)
def test_required_invalid_contract_hides_every_tenant_projection(
    monkeypatch: pytest.MonkeyPatch,
    contract_state: str,
) -> None:
    edition = EventEditionFactory(name="Contract-hidden Convention")
    account = AccountFactory()
    role = RoleBundleFactory(
        organization=edition.organization,
        capability_codes=["organizations.view_basic", "events.view_basic"],
    )
    RoleAssignmentFactory(
        principal=account,
        organization=edition.organization,
        role_bundle=role,
    )
    if contract_state == "malformed":
        monkeypatch.setattr(
            policy,
            "_exact_lineage_policy_state",
            lambda: (True, False),
        )
    graph = _ExactNavigationGraph(
        organization=edition.organization,
        edition=edition,
        actor=account,
        approver=account,
        direct_recipient=account,
        role_recipient=account,
        direct_source=None,
        role_source=None,
        direct_grants=(),
        role_assignment=None,
    )

    _assert_scoped_shell_hidden(client=_client(account), graph=graph)


@override_settings(REQUIRE_EXACT_AUTHORITY_PROVENANCE=True)
def test_platform_administrator_keeps_oversight_when_contract_is_missing() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    edition = EventEditionFactory(name="Platform Oversight Convention")
    client = _client(administrator)

    with CaptureQueriesContext(connection) as queries:
        response = client.get(reverse("admin:index"))
    assert len(queries) <= 50

    assert response.status_code == 200
    assert edition.name in response.content.decode()
    assert _selector_edition_ids(response) == {edition.id}
    selected = client.post(
        reverse("admin-edition-context"),
        {"edition_id": str(edition.id), "next": reverse("admin:index")},
    )
    assert selected.status_code == 302
    assert client.session[ADMIN_EDITION_SESSION_KEY] == str(edition.id)


def test_revoked_pinned_grant_and_role_sources_leave_no_navigation_access(
    settings: object,
) -> None:
    graph = _exact_navigation_graph()
    with CaptureQueriesContext(connection) as dormant_queries:
        assert _client(graph.actor).get(reverse("admin:index")).status_code == 200
    assert len(dormant_queries) <= 50
    settings.REQUIRE_EXACT_AUTHORITY_PROVENANCE = True  # type: ignore[attr-defined]
    _activate_exact_contract()
    with CaptureQueriesContext(connection) as queries:
        assert _client(graph.actor).get(reverse("admin:index")).status_code == 200
    # Django's session, authentication, app-list, and audit-log shell accounts
    # for most of this budget. Exact lineage adds one batch contract query.
    assert len(queries) <= 50
    direct_client = _client(graph.direct_recipient)
    role_client = _client(graph.role_recipient)
    _assert_scoped_shell_visible(client=direct_client, graph=graph)
    _assert_scoped_shell_visible(client=role_client, graph=graph)

    target = resolve_organization_target(organization_id=graph.organization.id)
    assert target is not None
    assert graph.direct_source is not None
    revoke_capability_grant(
        actor=graph.actor,
        target=target,
        grant_id=graph.direct_source.id,
        reason="End the exact source pinned by the navigation grants.",
        correlation_id=uuid4(),
        source_channel="test",
    )

    _assert_scoped_shell_hidden(client=direct_client, graph=graph)
    _assert_scoped_shell_visible(client=role_client, graph=graph)

    assert graph.role_source is not None
    revoke_capability_grant(
        actor=graph.actor,
        target=target,
        grant_id=graph.role_source.id,
        reason="End the exact source pinned by the navigation assignment.",
        correlation_id=uuid4(),
        source_channel="test",
    )

    _assert_scoped_shell_hidden(client=role_client, graph=graph)
    assert RoleAssignment.objects.filter(
        principal=graph.role_recipient,
        revoked_at__isnull=True,
    ).exists()


def test_edition_selector_and_routes_require_target_matching_capabilities(
    settings: object,
) -> None:
    graph = _exact_navigation_graph()
    settings.REQUIRE_EXACT_AUTHORITY_PROVENANCE = True  # type: ignore[attr-defined]
    _activate_exact_contract()
    organization_target = resolve_organization_target(
        organization_id=graph.organization.id
    )
    edition_target = resolve_edition_target(
        organization_id=graph.organization.id,
        edition_id=graph.edition.id,
    )
    assert organization_target is not None
    assert edition_target is not None
    department = Department.objects.create(
        organization=graph.organization,
        edition=graph.edition,
        code="selector-containment",
        name="Selector containment",
    )
    department_target = resolve_department_target(
        organization_id=graph.organization.id,
        edition_id=graph.edition.id,
        department_id=department.id,
    )
    assert department_target is not None

    unrelated_direct_recipient = AccountFactory()
    grant_capability_direct(
        actor=graph.actor,
        approver=graph.approver,
        recipient=unrelated_direct_recipient,
        capability_code="events.create",
        target=edition_target,
        effective_from=timezone.now(),
        expires_at=None,
        reason="Prove edition-scoped create authority does not flow upward.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    audit_role = create_role_bundle_version(
        actor=graph.actor,
        approver=graph.approver,
        target=organization_target,
        code="selector-unrelated-auditor",
        name="Selector unrelated auditor",
        capability_codes=("audit.view_security",),
        reason="Prove an unrelated role does not expose edition names.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    unrelated_role_recipient = AccountFactory()
    assign_role(
        actor=graph.actor,
        approver=graph.approver,
        recipient=unrelated_role_recipient,
        target=organization_target,
        role_bundle_id=audit_role.id,
        effective_from=timezone.now(),
        expires_at=None,
        reason="Assign unrelated exact audit authority.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    edition_role = create_role_bundle_version(
        actor=graph.actor,
        approver=graph.approver,
        target=organization_target,
        code="exact-edition-reader",
        name="Exact edition reader",
        capability_codes=("events.view_basic",),
        reason="Create exact-edition selector authority.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    edition_role_recipient = AccountFactory()
    assign_role(
        actor=graph.actor,
        approver=graph.approver,
        recipient=edition_role_recipient,
        target=edition_target,
        role_bundle_id=edition_role.id,
        effective_from=timezone.now(),
        expires_at=None,
        reason="Assign exact-edition selector authority.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    department_recipient = AccountFactory()
    grant_capability_direct(
        actor=graph.actor,
        approver=graph.approver,
        recipient=department_recipient,
        capability_code="events.view_basic",
        target=department_target,
        effective_from=timezone.now(),
        expires_at=None,
        reason="Prove department authority does not flow up to its edition.",
        correlation_id=uuid4(),
        source_channel="test",
    )

    for account in (unrelated_direct_recipient, unrelated_role_recipient):
        client = _client(account)
        response = client.get(reverse("admin:index"))
        content = response.content.decode()
        assert response.status_code == 200
        assert f'href="{reverse("management-console")}"' in content
        assert graph.edition.name not in content
        assert not _selector_edition_ids(response)
        assert client.post(
            reverse("admin-edition-context"),
            {
                "edition_id": str(graph.edition.id),
                "next": reverse("admin:index"),
            },
        ).status_code in {403, 404}

    create_route_response = _client(unrelated_direct_recipient).get(
        reverse(
            "baseline-create-event-edition",
            args=[graph.organization.slug, graph.edition.series.slug],
        )
    )
    assert create_route_response.status_code in {403, 404}
    assert graph.organization.name not in create_route_response.content.decode()

    edition_client = _client(edition_role_recipient)
    edition_shell = edition_client.get(reverse("admin:index"))
    assert _selector_edition_ids(edition_shell) == {graph.edition.id}
    assert graph.edition.name in edition_shell.content.decode()
    edition_record_url = reverse(
        "baseline-event-edition-record",
        args=[
            graph.organization.slug,
            graph.edition.series.slug,
            graph.edition.slug,
        ],
    )
    assert edition_client.get(edition_record_url).status_code == 200

    department_client = _client(department_recipient)
    department_shell = department_client.get(reverse("admin:index"))
    department_content = department_shell.content.decode()
    assert department_shell.status_code == 200
    assert f'href="{reverse("management-console")}"' in department_content
    assert graph.edition.name not in department_content
    assert not _selector_edition_ids(department_shell)
    department_record = department_client.get(edition_record_url)
    assert department_record.status_code in {403, 404}
    assert graph.organization.name not in department_record.content.decode()
    assert graph.edition.name not in department_record.content.decode()


def _python_current_results(
    checks: tuple[AuthorityIssuanceCurrentCheck, ...],
    *,
    evaluated_at: datetime,
) -> tuple[bool, ...]:
    return tuple(
        authority_issuance_is_current(
            issuance_ordinal=check.issuance_ordinal,
            principal_id=check.principal_id,
            capability_code=check.capability_code,
            target=check.target,
            requested_effective_from=check.requested_effective_from,
            requested_expires_at=check.requested_expires_at,
            evaluated_at=evaluated_at,
            horizon_mode=check.horizon_mode,
        )
        for check in checks
    )


def test_database_batch_matches_python_for_exact_mixed_scope_lineage(
    settings: object,
) -> None:
    """The shell fast path preserves exact Python-validator semantics."""

    graph = _exact_navigation_graph()
    settings.REQUIRE_EXACT_AUTHORITY_PROVENANCE = True  # type: ignore[attr-defined]
    _activate_exact_contract()
    assert graph.role_assignment is not None

    department = Department.objects.create(
        organization=graph.organization,
        edition=graph.edition,
        code="lineage-parity",
        name="Lineage parity",
    )
    role_bundle = graph.role_assignment.role_bundle
    template = PositionTemplate.objects.create(
        organization=graph.organization,
        code="lineage-parity-position",
        name="Lineage parity position",
        description="Synthetic exact-lineage parity position.",
        default_capacity_codes=["volunteer"],
        role_bundle=role_bundle,
        created_by=graph.actor,
    )
    position = Position.objects.create(
        organization=graph.organization,
        edition=graph.edition,
        template=template,
        department=department,
        role_bundle=role_bundle,
        code="lineage-parity-position",
        title="Lineage parity position",
        description="Synthetic exact-lineage parity position.",
        capacity_codes=["volunteer"],
        created_by=graph.actor,
    )
    binding = ScopedResourceBinding.objects.create(
        organization=graph.organization,
        edition=graph.edition,
        department=department,
        resource_kind=ScopedResourceBinding.ResourceKind.WORKFORCE_POSITION,
        resource_id=position.id,
    )

    organization_target = resolve_organization_target(
        organization_id=graph.organization.id
    )
    edition_target = resolve_edition_target(
        organization_id=graph.organization.id,
        edition_id=graph.edition.id,
    )
    department_target = resolve_department_target(
        organization_id=graph.organization.id,
        edition_id=graph.edition.id,
        department_id=department.id,
    )
    resource_target = resolve_resource_target(
        organization_id=graph.organization.id,
        edition_id=graph.edition.id,
        department_id=department.id,
        resource_binding_id=binding.id,
    )
    other_organization = OrganizationFactory()
    other_organization_target = resolve_organization_target(
        organization_id=other_organization.id
    )
    assert all(
        target is not None
        for target in (
            organization_target,
            edition_target,
            department_target,
            resource_target,
            other_organization_target,
        )
    )
    assert organization_target is not None
    assert edition_target is not None
    assert department_target is not None
    assert resource_target is not None
    assert other_organization_target is not None

    direct_grant = next(
        grant
        for grant in graph.direct_grants
        if grant.capability_code == "events.view_basic"
    )
    direct_ordinal = direct_grant.authority_issuance.ordinal
    role_ordinal = graph.role_assignment.authority_issuance.ordinal
    evaluated_at = timezone.now()

    def current_check(
        *,
        ordinal: int,
        principal_id: UUID,
        capability_code: str,
        target: object,
    ) -> AuthorityIssuanceCurrentCheck:
        return AuthorityIssuanceCurrentCheck(
            issuance_ordinal=ordinal,
            principal_id=principal_id,
            capability_code=capability_code,
            target=target,  # type: ignore[arg-type]
            requested_effective_from=evaluated_at,
            requested_expires_at=None,
            horizon_mode=ControlHorizonMode.POINT_IN_TIME,
        )

    direct_organization_check = current_check(
        ordinal=direct_ordinal,
        principal_id=graph.direct_recipient.id,
        capability_code="events.view_basic",
        target=organization_target,
    )
    checks = (
        direct_organization_check,
        current_check(
            ordinal=direct_ordinal,
            principal_id=graph.direct_recipient.id,
            capability_code="events.view_basic",
            target=edition_target,
        ),
        current_check(
            ordinal=direct_ordinal,
            principal_id=graph.direct_recipient.id,
            capability_code="events.view_basic",
            target=department_target,
        ),
        current_check(
            ordinal=direct_ordinal,
            principal_id=graph.direct_recipient.id,
            capability_code="events.view_basic",
            target=resource_target,
        ),
        current_check(
            ordinal=direct_ordinal,
            principal_id=graph.direct_recipient.id,
            capability_code="events.view_basic",
            target=other_organization_target,
        ),
        current_check(
            ordinal=direct_ordinal,
            principal_id=graph.direct_recipient.id,
            capability_code="events.view_basic",
            target=SimpleNamespace(
                organization_id=other_organization.id,
                edition_id=graph.edition.id,
                department_id=None,
                resource_binding_id=None,
            ),
        ),
        direct_organization_check,
        direct_organization_check,
        current_check(
            ordinal=role_ordinal,
            principal_id=graph.role_recipient.id,
            capability_code="events.view_basic",
            target=organization_target,
        ),
        current_check(
            ordinal=role_ordinal,
            principal_id=graph.role_recipient.id,
            capability_code="organizations.view_basic",
            target=organization_target,
        ),
        current_check(
            ordinal=0,
            principal_id=graph.direct_recipient.id,
            capability_code="events.view_basic",
            target=organization_target,
        ),
    )

    expected = _python_current_results(checks, evaluated_at=evaluated_at)
    with CaptureQueriesContext(connection) as batch_queries:
        actual = authority_issuances_are_current(
            checks=checks,
            evaluated_at=evaluated_at,
        )

    assert actual == expected
    assert actual == (
        True,
        True,
        True,
        True,
        False,
        False,
        True,
        True,
        True,
        True,
        False,
    )
    assert (
        sum(
            "public.maru_authority_issuance_valid_v1" in query["sql"]
            for query in batch_queries
        )
        == 1
    )

    oversized_batch = (direct_organization_check,) * 257
    with CaptureQueriesContext(connection) as oversized_queries:
        oversized_results = authority_issuances_are_current(
            checks=oversized_batch,
            evaluated_at=evaluated_at,
        )
    assert oversized_results == (True,) * len(oversized_batch)
    assert (
        sum(
            "public.maru_authority_issuance_valid_v1" in query["sql"]
            for query in oversized_queries
        )
        == 2
    )

    future_start = evaluated_at + timedelta(hours=1)
    future_expiry = future_start + timedelta(hours=1)
    future_grant = grant_capability_direct(
        actor=graph.actor,
        approver=graph.approver,
        recipient=AccountFactory(),
        capability_code="events.view_basic",
        target=organization_target,
        effective_from=future_start,
        expires_at=future_expiry,
        reason="Create future and expiry differential evidence.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    for boundary_time in (timezone.now(), future_expiry):
        boundary_check = AuthorityIssuanceCurrentCheck(
            issuance_ordinal=future_grant.authority_issuance.ordinal,
            principal_id=future_grant.principal_id,
            capability_code=future_grant.capability_code,
            target=organization_target,
            requested_effective_from=boundary_time,
            requested_expires_at=None,
            horizon_mode=ControlHorizonMode.POINT_IN_TIME,
        )
        assert (
            authority_issuances_are_current(
                checks=(boundary_check,),
                evaluated_at=boundary_time,
            )
            == _python_current_results(
                (boundary_check,),
                evaluated_at=boundary_time,
            )
            == (False,)
        )

    assert graph.direct_source is not None
    revoke_capability_grant(
        actor=graph.actor,
        target=organization_target,
        grant_id=graph.direct_source.id,
        reason="Invalidate the exact ancestor used by the parity grant.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    revoked_evaluation = timezone.now()
    revoked_check = AuthorityIssuanceCurrentCheck(
        issuance_ordinal=direct_ordinal,
        principal_id=graph.direct_recipient.id,
        capability_code="events.view_basic",
        target=organization_target,
        requested_effective_from=revoked_evaluation,
        requested_expires_at=None,
        horizon_mode=ControlHorizonMode.POINT_IN_TIME,
    )
    assert (
        authority_issuances_are_current(
            checks=(revoked_check,),
            evaluated_at=revoked_evaluation,
        )
        == _python_current_results(
            (revoked_check,),
            evaluated_at=revoked_evaluation,
        )
        == (False,)
    )


def test_expanded_executive_board_bundle_fails_closed_in_shell_and_validators(
    settings: object,
) -> None:
    graph = _exact_navigation_graph()
    settings.REQUIRE_EXACT_AUTHORITY_PROVENANCE = True  # type: ignore[attr-defined]
    _activate_exact_contract()
    direct_grant = next(
        grant
        for grant in graph.direct_grants
        if grant.capability_code == "events.view_basic"
    )
    target = resolve_organization_target(organization_id=graph.organization.id)
    assert target is not None
    evaluated_at = timezone.now()
    check = AuthorityIssuanceCurrentCheck(
        issuance_ordinal=direct_grant.authority_issuance.ordinal,
        principal_id=graph.direct_recipient.id,
        capability_code=direct_grant.capability_code,
        target=target,
        requested_effective_from=evaluated_at,
        requested_expires_at=None,
        horizon_mode=ControlHorizonMode.POINT_IN_TIME,
    )
    board_bundle_id = RoleAssignment.objects.values_list(
        "role_bundle_id",
        flat=True,
    ).get(
        organization=graph.organization,
        principal=graph.actor,
        role_bundle__code=EXECUTIVE_BOARD_ROLE_CODE,
    )

    # Simulate storage corruption behind the normal immutability guards. Both
    # independent validators and every name-bearing shell path must still deny.
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE public.authorization_rolebundle DISABLE TRIGGER USER"
            )
            cursor.execute(
                """
                UPDATE public.authorization_rolebundle
                   SET capability_codes = capability_codes || %s::varchar[]
                 WHERE id = %s::uuid
                """,
                (["events.edit"], board_bundle_id),
            )
            cursor.execute(
                "ALTER TABLE public.authorization_rolebundle ENABLE TRIGGER USER"
            )

        assert authority_issuances_are_current(
            checks=(check,),
            evaluated_at=evaluated_at,
        ) == (False,)
        assert _python_current_results(
            (check,),
            evaluated_at=evaluated_at,
        ) == (False,)
        _assert_scoped_shell_hidden(client=_client(graph.direct_recipient), graph=graph)
        transaction.set_rollback(True)
