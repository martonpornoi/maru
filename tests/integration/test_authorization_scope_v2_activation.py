"""Migration and database-boundary evidence for ADR 0041 activation."""

from __future__ import annotations

from datetime import timedelta
from importlib import import_module
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from maru.authorization.models import (
    AuthorizationScopeWriteFence,
    CapabilityGrant,
    RoleAssignment,
    RoleBundle,
)
from maru.workforce.models import Position, PositionTemplate
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    RoleAssignmentFactory,
    RoleBundleFactory,
    ScopedResourceBindingFactory,
)
from tests.workforce_helpers import (
    create_department_for_test,
    save_position_for_test,
)

if TYPE_CHECKING:
    from uuid import UUID

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("restores_current_migration_graph"),
]

activation_migration = import_module(
    "maru.authorization.migrations.0005_scope_v2_activation"
)


def _create_runtime_scope(suffix: str) -> SimpleNamespace:
    edition = EventEditionFactory()
    creator = AccountFactory()
    role_bundle = RoleBundleFactory(organization=edition.organization)
    department = create_department_for_test(
        edition=edition,
        name=f"Operations {suffix}",
        expected_code=f"operations-{suffix}",
    )
    template = PositionTemplate.objects.create(
        organization=edition.organization,
        code=f"operations-lead-{suffix}",
        name=f"Operations lead {suffix}",
        description="Synthetic activation-test template.",
        default_capacity_codes=["volunteer"],
        role_bundle=role_bundle,
        created_by=creator,
    )
    position = save_position_for_test(
        position=Position(
            organization=edition.organization,
            edition=edition,
            template=template,
            department=department,
            role_bundle=role_bundle,
            code=f"operations-lead-{suffix}",
            title=f"Operations lead {suffix}",
            description="Synthetic activation-test position.",
            capacity_codes=["volunteer"],
            created_by=creator,
        )
    )
    binding = ScopedResourceBindingFactory(
        department=department,
        resource_id=position.id,
    )
    return SimpleNamespace(
        edition=edition,
        organization=edition.organization,
        department=department,
        position=position,
        binding=binding,
        role_bundle=role_bundle,
    )


def _raw_grant(
    *,
    scope: SimpleNamespace,
    capability_code: str = "events.view_basic",
    edition_id: UUID | None = None,
    department_id: UUID | None = None,
    resource_binding_id: UUID | None = None,
    principal: Any | None = None,
    granted_by: Any | None = None,
    effective_from: Any | None = None,
    expires_at: Any | None = None,
    delegated_from: CapabilityGrant | None = None,
) -> CapabilityGrant:
    return CapabilityGrant(
        organization=scope.organization,
        edition_id=edition_id,
        department_id=department_id,
        resource_binding_id=resource_binding_id,
        principal=principal or AccountFactory(),
        capability_code=capability_code,
        effective_from=effective_from or timezone.now(),
        expires_at=expires_at,
        granted_by=granted_by or AccountFactory(),
        delegated_from=delegated_from,
        reason="Synthetic database-boundary grant.",
    )


def test_active_guards_reject_scope_forgery_mutation_and_catalog_bypass() -> None:
    first = _create_runtime_scope("first")
    second = _create_runtime_scope("second")

    with (
        pytest.raises(IntegrityError, match="department scope mismatch"),
        transaction.atomic(),
    ):
        CapabilityGrant.objects.bulk_create(
            [
                _raw_grant(
                    scope=first,
                    edition_id=first.edition.id,
                    department_id=second.department.id,
                )
            ]
        )

    with (
        pytest.raises(IntegrityError, match="resource scope mismatch"),
        transaction.atomic(),
    ):
        RoleAssignment.objects.bulk_create(
            [
                RoleAssignment(
                    organization=first.organization,
                    edition=first.edition,
                    department=first.department,
                    resource_binding=second.binding,
                    principal=AccountFactory(),
                    role_bundle=first.role_bundle,
                    effective_from=timezone.now(),
                    granted_by=AccountFactory(),
                    reason="Synthetic forged role scope.",
                )
            ]
        )

    valid_grant = CapabilityGrantFactory(
        organization=first.organization,
        edition=first.edition,
        department=first.department,
    )
    other_department = create_department_for_test(
        edition=first.edition,
        name="Registration first",
        expected_code="registration-first",
    )
    with (
        pytest.raises(IntegrityError, match="immutable"),
        transaction.atomic(),
    ):
        CapabilityGrant.objects.filter(pk=valid_grant.pk).update(
            department=other_department
        )

    valid_assignment = RoleAssignmentFactory(
        organization=first.organization,
        edition=first.edition,
        department=first.department,
        role_bundle=first.role_bundle,
    )
    with (
        pytest.raises(IntegrityError, match="immutable"),
        transaction.atomic(),
    ):
        RoleAssignment.objects.filter(pk=valid_assignment.pk).update(
            resource_binding=first.binding
        )

    with (
        pytest.raises(IntegrityError, match="cannot be persisted"),
        transaction.atomic(),
    ):
        CapabilityGrant.objects.bulk_create(
            [
                _raw_grant(
                    scope=first,
                    capability_code="workforce.view_self",
                    edition_id=first.edition.id,
                    department_id=first.department.id,
                    resource_binding_id=first.binding.id,
                )
            ]
        )

    with pytest.raises(IntegrityError, match="non-persistable"), transaction.atomic():
        RoleBundle.objects.bulk_create(
            [
                RoleBundle(
                    organization=first.organization,
                    code="forged-self-role",
                    name="Forged self role",
                    version=1,
                    capability_codes=["workforce.view_self"],
                )
            ]
        )

    edition_only_bundle = RoleBundleFactory(
        organization=first.organization,
        capability_codes=["events.change_profile"],
    )
    with (
        pytest.raises(
            IntegrityError,
            match="purpose-bound role authority requires exact edition scope",
        ),
        transaction.atomic(),
    ):
        RoleAssignment.objects.bulk_create(
            [
                RoleAssignment(
                    organization=first.organization,
                    principal=AccountFactory(),
                    role_bundle=edition_only_bundle,
                    effective_from=timezone.now(),
                    granted_by=AccountFactory(),
                    reason="Synthetic too-broad role assignment.",
                )
            ]
        )


def test_revocation_requires_complete_evidence_and_is_one_way() -> None:
    scope = _create_runtime_scope("revocation")
    grant = CapabilityGrantFactory(organization=scope.organization)
    assignment = RoleAssignmentFactory(
        organization=scope.organization,
        role_bundle=scope.role_bundle,
    )
    revoker = AccountFactory()
    revoked_at = timezone.now()

    for authority, label in (
        (grant, "capability grant"),
        (assignment, "role assignment"),
    ):
        queryset = type(authority).objects.filter(pk=authority.pk)
        with (
            pytest.raises(IntegrityError, match=f"{label} revocation evidence"),
            transaction.atomic(),
        ):
            queryset.update(revoked_at=revoked_at)

        assert (
            queryset.update(
                revoked_at=revoked_at,
                revoked_by=revoker,
                revocation_reason="Synthetic complete revocation evidence.",
            )
            == 1
        )
        with (
            pytest.raises(IntegrityError, match=f"{label} revocation is immutable"),
            transaction.atomic(),
        ):
            queryset.update(revocation_reason="Rewritten revocation evidence.")
        with (
            pytest.raises(IntegrityError, match="must be revoked, not deleted"),
            transaction.atomic(),
        ):
            queryset.delete()


def test_delegation_guard_enforces_ancestry_scope_and_horizon() -> None:
    scope = _create_runtime_scope("delegation")
    sibling_department = create_department_for_test(
        edition=scope.edition,
        name="Registration delegation",
        expected_code="registration-delegation",
    )
    now = timezone.now()
    parent_principal = AccountFactory()
    parent = CapabilityGrantFactory(
        organization=scope.organization,
        edition=scope.edition,
        department=scope.department,
        principal=parent_principal,
        effective_from=now,
        expires_at=now + timedelta(days=10),
    )

    with (
        pytest.raises(IntegrityError, match="delegation containment"),
        transaction.atomic(),
    ):
        CapabilityGrant.objects.bulk_create(
            [
                _raw_grant(
                    scope=scope,
                    edition_id=scope.edition.id,
                    department_id=sibling_department.id,
                    granted_by=parent_principal,
                    effective_from=now,
                    expires_at=now + timedelta(days=5),
                    delegated_from=parent,
                )
            ]
        )

    with (
        pytest.raises(IntegrityError, match="delegation containment"),
        transaction.atomic(),
    ):
        CapabilityGrant.objects.bulk_create(
            [
                _raw_grant(
                    scope=scope,
                    edition_id=scope.edition.id,
                    department_id=scope.department.id,
                    granted_by=parent_principal,
                    effective_from=now - timedelta(seconds=1),
                    expires_at=now + timedelta(days=5),
                    delegated_from=parent,
                )
            ]
        )

    with (
        pytest.raises(IntegrityError, match="delegation containment"),
        transaction.atomic(),
    ):
        CapabilityGrant.objects.bulk_create(
            [
                _raw_grant(
                    scope=scope,
                    edition_id=scope.edition.id,
                    department_id=scope.department.id,
                    granted_by=parent_principal,
                    effective_from=now,
                    expires_at=now + timedelta(days=11),
                    delegated_from=parent,
                )
            ]
        )


@pytest.mark.parametrize("authority_kind", ["grant", "role"])
def test_downgrade_fence_refuses_any_scoped_authority(authority_kind: str) -> None:
    # Later migrations have their own downgrade fences. A whole-graph reversal
    # hits those first and cannot prove this migration's independent protection.
    # Execute the actual wired reverse operation, including a clean control.
    reverse_fence = activation_migration.Migration(
        "0005_scope_v2_activation", "authorization"
    ).operations[-1]
    assert not AuthorizationScopeWriteFence.objects.exists()
    with connection.schema_editor() as editor:
        reverse_fence.database_backwards("authorization", editor, None, None)

    scope = _create_runtime_scope(f"fence-{authority_kind}")
    if authority_kind == "grant":
        authority = CapabilityGrantFactory(
            organization=scope.organization,
            edition=scope.edition,
            department=scope.department,
        )
    else:
        authority = RoleAssignmentFactory(
            organization=scope.organization,
            edition=scope.edition,
            department=scope.department,
            role_bundle=scope.role_bundle,
        )

    if authority_kind == "grant":
        disable_sql = (
            "ALTER TABLE authorization_capabilitygrant DISABLE TRIGGER "
            "authorization_capability_grant_no_delete"
        )
        delete_sql = "DELETE FROM authorization_capabilitygrant WHERE id = %s"
        enable_sql = (
            "ALTER TABLE authorization_capabilitygrant ENABLE TRIGGER "
            "authorization_capability_grant_no_delete"
        )
    else:
        disable_sql = (
            "ALTER TABLE authorization_roleassignment DISABLE TRIGGER "
            "authorization_role_assignment_no_delete"
        )
        delete_sql = "DELETE FROM authorization_roleassignment WHERE id = %s"
        enable_sql = (
            "ALTER TABLE authorization_roleassignment ENABLE TRIGGER "
            "authorization_role_assignment_no_delete"
        )
    with connection.cursor() as cursor:
        cursor.execute(disable_sql)
        try:
            cursor.execute(delete_sql, [authority.id])
        finally:
            cursor.execute(enable_sql)
    assert not type(authority).objects.filter(pk=authority.pk).exists()
    assert AuthorizationScopeWriteFence.objects.filter(singleton=True).exists()

    with (
        pytest.raises(IntegrityError, match="ADR 0041 downgrade refused after scoped"),
        connection.schema_editor() as editor,
    ):
        reverse_fence.database_backwards("authorization", editor, None, None)
