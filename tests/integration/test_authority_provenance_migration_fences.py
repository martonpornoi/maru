"""Migration ownership and lock-order regressions for ADR 0044 cutover."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from threading import Event
from time import monotonic
from uuid import UUID, uuid4

import pytest
from django.apps import apps as django_apps
from django.core.exceptions import ValidationError
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import override_settings
from django.utils import timezone

from maru.audit.services import AuditRecord, append_audit
from maru.authorization import catalog as authorization_catalog
from maru.authorization.activation import activate_authority_provenance
from maru.authorization.commands import grant_capability_direct
from maru.authorization.models import (
    AUTHORITY_PROVENANCE_ACTIVATION_POLICY_VERSION,
    AUTHORITY_PROVENANCE_CONTRACT_VERSION,
    AuthorityProvenanceActivation,
    AuthorityProvenanceActivationLatch,
)
from maru.authorization.policy import resolve_organization_target
from tests.factories import AccountFactory, OrganizationFactory
from tests.support.authority import activate_synthetic_board

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("restores_current_migration_graph"),
    pytest.mark.usefixtures("proves_safe_runtime_database_role"),
]

AUDIT_BEFORE_GUARDS = ("audit", "0004_alter_auditevent_safe_metadata")
AUDIT_WITH_GUARDS = ("audit", "0005_authority_activation_evidence_guards")
AUDIT_WITH_RESERVED_GUARD = (
    "audit",
    "0006_reserved_authority_activation_audit_guard",
)
AUTHORIZATION_BEFORE_ACTIVATION = (
    "authorization",
    "0006_authority_issuance_schema",
)
AUTHORIZATION_WITH_BASE_ACTIVATION = (
    "authorization",
    "0007_authority_provenance_activation_guards",
)
AUTHORIZATION_WITH_ACTIVATION = (
    "authorization",
    "0008_runtime_latch_lock_helper",
)


def _migrate(*targets: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate(list(targets))
    return executor


def _regobjects() -> tuple[object, ...]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                to_regclass('authorization_authorityprovenanceactivation'),
                to_regclass('authorization_provenanceactivationlatch'),
                to_regprocedure('maru_lock_authority_provenance_writer()'),
                to_regclass('authorization_provenance_activation_audit_unique'),
                to_regprocedure('maru_prevent_audit_event_truncate()')
            """
        )
        return tuple(cursor.fetchone())


def _reciprocal_guard_objects() -> tuple[object, ...]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                to_regprocedure(
                    'maru_guard_authority_provenance_activation_audit()'
                ),
                to_regprocedure('maru_lock_authority_provenance_latch()'),
                (
                    SELECT COUNT(*)
                      FROM pg_trigger
                     WHERE tgname =
                           'authorization_activation_audit_reserved_guard'
                       AND NOT tgisinternal
                )
            """
        )
        return tuple(cursor.fetchone())


def _function_definition_contract(signature: str) -> tuple[str, list[str] | None]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT pg_get_functiondef(procedure.oid),
                   procedure.proconfig
              FROM pg_proc AS procedure
             WHERE procedure.oid = to_regprocedure(%s)
            """,
            [signature],
        )
        row = cursor.fetchone()
    assert row is not None
    return row[0], row[1]


def _function_acl_contract(signature: str) -> tuple[str | None, bool] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT procedure.proacl::text,
                   EXISTS (
                       SELECT 1
                         FROM pg_catalog.aclexplode(
                             COALESCE(
                                 procedure.proacl,
                                 pg_catalog.acldefault(
                                     'f'::pg_catalog."char",
                                     procedure.proowner
                                 )
                             )
                         ) AS privilege
                        WHERE privilege.grantee = 0
                          AND privilege.privilege_type = 'EXECUTE'
                   )
              FROM pg_catalog.pg_proc AS procedure
             WHERE procedure.oid = pg_catalog.to_regprocedure(%s)
            """,
            [signature],
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return row[0], row[1]


def _set_latch_row(*, present: bool) -> None:
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            """
            ALTER TABLE authorization_provenanceactivationlatch
            DISABLE TRIGGER authorization_provenance_latch_guard
            """
        )
        try:
            cursor.execute("DELETE FROM authorization_provenanceactivationlatch")
            if present:
                cursor.execute(
                    """
                    INSERT INTO authorization_provenanceactivationlatch(
                        singleton,
                        generation
                    ) VALUES (TRUE, 0)
                    """
                )
        finally:
            cursor.execute(
                """
                ALTER TABLE authorization_provenanceactivationlatch
                ENABLE TRIGGER authorization_provenance_latch_guard
                """
            )


def _activation_audit_without_marker() -> None:
    correlation_id = uuid4()
    append_audit(
        AuditRecord(
            principal_kind="platform_administrator",
            principal_id=uuid4(),
            principal_context_id=None,
            organization_id=None,
            event_edition_id=None,
            capability_code="authorization.manage_roles",
            operation="authorization.authority_provenance.activate",
            target_type="authorization.authority_provenance_activation",
            target_id=None,
            outcome="allow",
            reason_code="exact_lineage_cutover",
            correlation_id=correlation_id,
            source_channel="test",
            obligations=("reason", "audit", "stopped_processes"),
            changed_fields=("authority_provenance_activation",),
            elevated=True,
            safe_metadata={
                "contract_version": "adr-0044-v1",
                "policy_version": "2026-08-01.3",
            },
            retention_class="security-extended",
        )
    )


def _exact_activation_pair(*, administrator_id: UUID) -> None:
    correlation_id = uuid4()
    with transaction.atomic():
        marker = AuthorityProvenanceActivation.objects.bulk_create(
            [
                AuthorityProvenanceActivation(
                    contract_version=AUTHORITY_PROVENANCE_CONTRACT_VERSION,
                    policy_version=AUTHORITY_PROVENANCE_ACTIVATION_POLICY_VERSION,
                    activated_by_id=administrator_id,
                    reason=(
                        "Prove an exact active database can install the reciprocal "
                        "guard."
                    ),
                    correlation_id=correlation_id,
                )
            ]
        )[0]
        marker.refresh_from_db(fields=("activated_at",))
        append_audit(
            AuditRecord(
                principal_kind="platform_administrator",
                principal_id=administrator_id,
                principal_context_id=None,
                organization_id=None,
                event_edition_id=None,
                capability_code="authorization.manage_roles",
                operation="authorization.authority_provenance.activate",
                target_type="authorization.authority_provenance_activation",
                target_id=None,
                outcome="allow",
                reason_code="exact_lineage_cutover",
                correlation_id=correlation_id,
                source_channel="test",
                obligations=("reason", "audit", "stopped_processes"),
                changed_fields=("authority_provenance_activation",),
                elevated=True,
                safe_metadata={
                    "contract_version": "adr-0044-v1",
                    "policy_version": "2026-08-01.3",
                },
                retention_class="security-extended",
            ),
            occurred_at=marker.activated_at,
        )


def _sqlstate(error: BaseException) -> str | None:
    candidate: BaseException | None = error
    while candidate is not None:
        value = getattr(candidate, "sqlstate", None)
        if isinstance(value, str):
            return value
        candidate = candidate.__cause__
    return None


def test_full_graph_reverse_and_forward_preserve_migration_ownership() -> None:
    marker, latch, writer, audit_index, audit_guard = _regobjects()
    assert all(value is not None for value in (marker, latch, writer))
    assert all(value is not None for value in (audit_index, audit_guard))
    assert _reciprocal_guard_objects()[0:2] != (None, None)
    assert _reciprocal_guard_objects()[2] == 1

    _migrate(AUDIT_BEFORE_GUARDS)
    assert _regobjects() == (None, None, None, None, None)
    assert _reciprocal_guard_objects() == (None, None, 0)

    _migrate(AUTHORIZATION_WITH_ACTIVATION)
    marker, latch, writer, audit_index, audit_guard = _regobjects()
    assert all(value is not None for value in (marker, latch, writer))
    assert all(value is not None for value in (audit_index, audit_guard))
    assert _reciprocal_guard_objects()[0:2] != (None, None)
    assert _reciprocal_guard_objects()[2] == 1
    assert list(
        AuthorityProvenanceActivationLatch.objects.values_list(
            "singleton",
            "generation",
        )
    ) == [(True, 0)]


def test_authorization_reverse_leaves_owned_audit_boundary_installed() -> None:
    _migrate(AUTHORIZATION_BEFORE_ACTIVATION)
    marker, latch, writer, audit_index, audit_guard = _regobjects()
    assert (marker, latch, writer) == (None, None, None)
    assert audit_index is not None
    assert audit_guard is not None
    assert _reciprocal_guard_objects() == (None, None, 0)

    _migrate(AUTHORIZATION_WITH_ACTIVATION)
    assert all(value is not None for value in _regobjects())
    reciprocal_guard, latch_helper, trigger_count = _reciprocal_guard_objects()
    assert reciprocal_guard is not None
    assert latch_helper is not None
    assert trigger_count == 1


def test_audit_reverse_restores_prior_owned_append_only_function() -> None:
    _migrate(AUDIT_BEFORE_GUARDS)
    baseline = _function_definition_contract("maru_guard_audit_event()")
    assert baseline[1] is None

    _migrate(AUTHORIZATION_WITH_ACTIVATION)
    hardened = _function_definition_contract("maru_guard_audit_event()")
    assert hardened[1] == ["search_path=pg_catalog, public, pg_temp"]

    _migrate(AUDIT_BEFORE_GUARDS)
    assert _function_definition_contract("maru_guard_audit_event()") == baseline
    _migrate(AUTHORIZATION_WITH_ACTIVATION)


def test_authorization_function_acl_hardening_preserves_preexisting_acl_state() -> None:
    sentinel = "public.maru_acl_preservation_sentinel()"
    _migrate(AUTHORIZATION_BEFORE_ACTIVATION)
    with connection.cursor() as cursor:
        cursor.execute(
            "DROP FUNCTION IF EXISTS public.maru_acl_preservation_sentinel()"
        )
        cursor.execute(
            """
            CREATE FUNCTION public.maru_acl_preservation_sentinel()
            RETURNS integer
            LANGUAGE sql
            AS 'SELECT 1'
            """
        )
    baseline = _function_acl_contract(sentinel)
    assert baseline == (None, True)

    try:
        _migrate(AUTHORIZATION_WITH_ACTIVATION)
        assert _function_acl_contract(sentinel) == baseline
        exact_policy_acl = _function_acl_contract(
            "public.maru_authority_issuance_valid_v1("
            "bigint,uuid,character varying,uuid,uuid,uuid,uuid,"
            "timestamp with time zone,timestamp with time zone,"
            "timestamp with time zone,boolean,boolean,bigint[],integer)"
        )
        assert exact_policy_acl is not None
        assert exact_policy_acl[1] is False

        _migrate(AUTHORIZATION_BEFORE_ACTIVATION)
        assert _function_acl_contract(sentinel) == baseline
        assert (
            _function_acl_contract(
                "public.maru_authority_issuance_valid_v1("
                "bigint,uuid,character varying,uuid,uuid,uuid,uuid,"
                "timestamp with time zone,timestamp with time zone,"
                "timestamp with time zone,boolean,boolean,bigint[],integer)"
            )
            is None
        )
    finally:
        _migrate(AUTHORIZATION_BEFORE_ACTIVATION)
        with connection.cursor() as cursor:
            cursor.execute(
                "DROP FUNCTION IF EXISTS public.maru_acl_preservation_sentinel()"
            )
        _migrate(AUTHORIZATION_WITH_ACTIVATION)


def test_authorization_reverse_refuses_a_missing_latch() -> None:
    _set_latch_row(present=False)
    try:
        with pytest.raises(RuntimeError, match="Cannot remove"):
            _migrate(AUTHORIZATION_BEFORE_ACTIVATION)
        assert _regobjects()[0] is not None
    finally:
        _set_latch_row(present=True)


def test_reserved_audit_guard_upgrade_rejects_legacy_orphan() -> None:
    _migrate(AUTHORIZATION_WITH_BASE_ACTIVATION, AUDIT_WITH_GUARDS)
    _activation_audit_without_marker()
    try:
        with pytest.raises(RuntimeError, match="Cannot install the reserved"):
            _migrate(AUDIT_WITH_RESERVED_GUARD)
        assert _reciprocal_guard_objects()[0] is None
        assert _reciprocal_guard_objects()[2] == 0

        with pytest.raises(RuntimeError, match="Cannot remove authority activation"):
            _migrate(AUDIT_BEFORE_GUARDS)
        assert _regobjects()[3] is not None
        assert _regobjects()[4] is not None
    finally:
        with connection.cursor() as cursor:
            cursor.execute("TRUNCATE audit_auditevent CASCADE")
        _migrate(AUTHORIZATION_WITH_ACTIVATION)


def test_reserved_audit_guard_accepts_exact_active_upgrade_and_fences_reverse() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    _migrate(AUTHORIZATION_WITH_BASE_ACTIVATION, AUDIT_WITH_GUARDS)
    _exact_activation_pair(administrator_id=administrator.id)

    _migrate(AUDIT_WITH_RESERVED_GUARD)
    reciprocal_guard, _latch_helper, trigger_count = _reciprocal_guard_objects()
    assert reciprocal_guard is not None
    assert trigger_count == 1

    with pytest.raises(RuntimeError, match="Cannot remove the reserved"):
        _migrate(AUDIT_WITH_GUARDS)

    assert _reciprocal_guard_objects()[0] is not None
    assert _reciprocal_guard_objects()[2] == 1
    _migrate(AUTHORIZATION_WITH_ACTIVATION)


def test_activation_model_bounds_a_missing_administrator() -> None:
    marker = AuthorityProvenanceActivation(
        contract_version=AUTHORITY_PROVENANCE_CONTRACT_VERSION,
        policy_version=AUTHORITY_PROVENANCE_ACTIVATION_POLICY_VERSION,
        activated_by_id=uuid4(),
        reason="Reject a missing activation administrator cleanly.",
        correlation_id=uuid4(),
    )

    with pytest.raises(ValidationError) as error:
        marker.full_clean()

    assert "activated_by" in error.value.message_dict


def test_activation_marker_validation_uses_its_frozen_release_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    marker = AuthorityProvenanceActivation(
        contract_version=AUTHORITY_PROVENANCE_CONTRACT_VERSION,
        policy_version=AUTHORITY_PROVENANCE_ACTIVATION_POLICY_VERSION,
        activated_by=administrator,
        reason="Keep immutable activation evidence valid across catalog releases.",
        correlation_id=uuid4(),
    )

    monkeypatch.setattr(
        authorization_catalog,
        "POLICY_VERSION",
        "future-release",
    )

    marker.full_clean()


def test_activation_latch_rejects_every_application_save() -> None:
    latch = AuthorityProvenanceActivationLatch(singleton=True, generation=0)

    with pytest.raises(
        ValidationError,
        match="activation latch is database-managed",
    ):
        latch.save()


def test_authorization_reverse_preflight_holds_public_cutover_tables() -> None:
    migration = import_module(
        "maru.authorization.migrations.0007_authority_provenance_activation_guards"
    )

    def competing_marker_writer() -> tuple[str, str | None]:
        close_old_connections()
        try:
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '500ms'")
                cursor.execute(
                    """
                    LOCK TABLE
                        public.authorization_authorityprovenanceactivation
                    IN ROW EXCLUSIVE MODE
                    """
                )
        except DatabaseError as error:
            return "rejected", _sqlstate(error)
        else:
            return "acquired", None
        finally:
            connection.close()

    with transaction.atomic(), connection.schema_editor() as schema_editor:
        migration.refuse_activated_provenance_downgrade(
            django_apps,
            schema_editor,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            outcome = executor.submit(competing_marker_writer).result(timeout=5)

    assert outcome == ("rejected", "55P03")


def test_controller_row_lock_cannot_deadlock_activation_boundary() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory()
    actor, approver = activate_synthetic_board(organization)
    recipient = AccountFactory()
    target = resolve_organization_target(organization_id=organization.id)
    assert target is not None
    actor_locked = Event()
    activation_finished = Event()

    def authority_writer() -> tuple[str, str | None]:
        close_old_connections()
        try:
            with transaction.atomic():
                type(actor).objects.select_for_update().get(pk=actor.id)
                actor_locked.set()
                if not activation_finished.wait(timeout=10):
                    return "timed_out", None
                grant_capability_direct(
                    actor=actor,
                    approver=approver,
                    recipient=recipient,
                    capability_code="events.view_basic",
                    target=target,
                    effective_from=timezone.now(),
                    expires_at=None,
                    reason="Stale application writer must restart after cutover.",
                    correlation_id=uuid4(),
                    source_channel="test",
                )
        except DatabaseError as error:
            return "rejected", _sqlstate(error)
        else:
            return "committed", None
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=1) as executor:
        writer = executor.submit(authority_writer)
        assert actor_locked.wait(timeout=10)
        started = monotonic()
        try:
            with override_settings(REQUIRE_EXACT_AUTHORITY_PROVENANCE=True):
                result = activate_authority_provenance(
                    actor=administrator,
                    reason="Prove actor-row and advisory lock ordering.",
                    correlation_id=uuid4(),
                    acknowledge_processes_stopped=True,
                    source_channel="test",
                )
            elapsed = monotonic() - started
        finally:
            activation_finished.set()
        outcome, sqlstate = writer.result(timeout=10)

    assert result.activated
    assert elapsed < 10
    assert (outcome, sqlstate) == ("rejected", "40001")
