"""PostgreSQL cutover, completeness, and stale-writer evidence for ADR 0044."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Event
from time import monotonic, sleep
from uuid import UUID, uuid4

import pytest
from django.db import (
    DatabaseError,
    close_old_connections,
    connection,
    transaction,
)
from django.db.migrations.executor import MigrationExecutor
from django.test import override_settings
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.authorization.activation import activate_authority_provenance
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.commands import (
    create_role_bundle_version,
    grant_capability_direct,
)
from maru.authorization.models import (
    AUTHORITY_PROVENANCE_ACTIVATION_LOCK_KEY,
    AUTHORITY_PROVENANCE_ACTIVATION_POLICY_VERSION,
    AUTHORITY_PROVENANCE_CONTRACT_VERSION,
    AuthorityControl,
    AuthorityIssuance,
    AuthorityProvenanceActivation,
    AuthorityProvenanceActivationLatch,
    CapabilityGrant,
    RoleAssignment,
    RoleBundle,
)
from maru.authorization.policy import resolve_organization_target
from maru.identity.models import Account
from maru.organizations.models import Organization
from tests.factories import AccountFactory, CapabilityGrantFactory, OrganizationFactory
from tests.support.authority import activate_synthetic_board

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("proves_safe_runtime_database_role"),
]

AUTHORIZATION_BEFORE_ACTIVATION = (
    "authorization",
    "0006_authority_issuance_schema",
)
AUTHORIZATION_BEFORE_ISSUANCE = (
    "authorization",
    "0005_scope_v2_activation",
)
AUTHORIZATION_AFTER_ACTIVATION = (
    "authorization",
    "0008_runtime_latch_lock_helper",
)

PRIOR_ISSUANCE_FUNCTIONS = (
    "maru_prevent_authority_control_mutation()",
    "maru_prevent_authority_issuance_mutation()",
    "maru_validate_authority_control_insert()",
    "maru_validate_authority_issuance_insert()",
)
PRIOR_FOUNDATIONAL_AUTHORIZATION_FUNCTIONS = (
    "maru_authorization_capability_min_scope(text)",
    "maru_authorization_scope_contains(uuid,uuid,uuid,uuid,uuid,uuid,uuid,uuid)",
    "maru_authorization_scope_rank(uuid,uuid,uuid)",
    "maru_prevent_authority_record_delete()",
    "maru_prevent_role_bundle_mutation()",
    "maru_prevent_scoped_resource_binding_mutation()",
    "maru_validate_capability_grant()",
    "maru_validate_role_assignment()",
    "maru_validate_role_bundle_catalog()",
    "maru_validate_scoped_resource_binding()",
)


def _trigger_contract(
    table: str,
    function: str,
    trigger_type: int,
    *,
    deferrable: bool = False,
    initially_deferred: bool = False,
    columns: tuple[str, ...] = (),
) -> tuple[str, str, int, str, bool, bool, tuple[str, ...]]:
    return (
        table,
        function,
        trigger_type,
        "O",
        deferrable,
        initially_deferred,
        columns,
    )


EXPECTED_TRIGGER_CONTRACTS = {
    "authorization_capability_grant_guard": _trigger_contract(
        "authorization_capabilitygrant",
        "maru_validate_capability_grant",
        23,
    ),
    "authorization_capability_grant_no_delete": _trigger_contract(
        "authorization_capabilitygrant",
        "maru_prevent_authority_record_delete",
        11,
    ),
    "authorization_role_assignment_guard": _trigger_contract(
        "authorization_roleassignment",
        "maru_validate_role_assignment",
        23,
    ),
    "authorization_role_assignment_no_delete": _trigger_contract(
        "authorization_roleassignment",
        "maru_prevent_authority_record_delete",
        11,
    ),
    "authorization_role_bundle_catalog_guard": _trigger_contract(
        "authorization_rolebundle",
        "maru_validate_role_bundle_catalog",
        7,
    ),
    "authorization_role_bundle_immutable": _trigger_contract(
        "authorization_rolebundle",
        "maru_prevent_role_bundle_mutation",
        27,
    ),
    "authorization_scoped_resource_binding_guard": _trigger_contract(
        "authorization_scopedresourcebinding",
        "maru_validate_scoped_resource_binding",
        23,
    ),
    "authorization_scoped_resource_binding_immutable": _trigger_contract(
        "authorization_scopedresourcebinding",
        "maru_prevent_scoped_resource_binding_mutation",
        27,
    ),
    "authorization_retired_binding_guard": _trigger_contract(
        "authorization_scopedresourcebinding",
        "maru_reject_retired_authority_target",
        7,
    ),
    "authorization_retired_capability_guard": _trigger_contract(
        "authorization_capabilitygrant",
        "maru_reject_retired_authority_target",
        23,
    ),
    "authorization_retired_role_guard": _trigger_contract(
        "authorization_roleassignment",
        "maru_reject_retired_authority_target",
        23,
    ),
    "authorization_retired_department_authority_guard": _trigger_contract(
        "workforce_department",
        "maru_guard_department_retirement_authority",
        19,
        columns=("retired_at",),
    ),
    "authorization_retired_binding_writer_lock": _trigger_contract(
        "authorization_scopedresourcebinding",
        "maru_lock_retired_department_authority_writer",
        6,
    ),
    "authorization_retired_capability_writer_lock": _trigger_contract(
        "authorization_capabilitygrant",
        "maru_lock_retired_department_authority_writer",
        22,
    ),
    "authorization_retired_role_writer_lock": _trigger_contract(
        "authorization_roleassignment",
        "maru_lock_retired_department_authority_writer",
        22,
    ),
    "authorization_retired_department_writer_lock": _trigger_contract(
        "workforce_department",
        "maru_lock_retired_department_authority_writer",
        18,
        columns=("retired_at",),
    ),
    "authorization_capability_grant_provenance_lock": _trigger_contract(
        "authorization_capabilitygrant",
        "maru_lock_authority_provenance_writer",
        30,
    ),
    "authorization_role_bundle_provenance_lock": _trigger_contract(
        "authorization_rolebundle",
        "maru_lock_authority_provenance_writer",
        30,
    ),
    "authorization_role_assignment_provenance_lock": _trigger_contract(
        "authorization_roleassignment",
        "maru_lock_authority_provenance_writer",
        30,
    ),
    "authorization_authority_issuance_provenance_lock": _trigger_contract(
        "authorization_authorityissuance",
        "maru_lock_authority_provenance_writer",
        6,
    ),
    "authorization_authority_control_provenance_lock": _trigger_contract(
        "authorization_authoritycontrol",
        "maru_lock_authority_provenance_writer",
        6,
    ),
    "authorization_identity_account_provenance_lock": _trigger_contract(
        "identity_account",
        "maru_lock_authority_provenance_writer",
        26,
    ),
    "authorization_organization_provenance_lock": _trigger_contract(
        "organizations_organization",
        "maru_lock_authority_provenance_writer",
        26,
    ),
    "authorization_membership_provenance_lock": _trigger_contract(
        "organizations_organizationmembership",
        "maru_lock_authority_provenance_writer",
        30,
    ),
    "authorization_representation_provenance_lock": _trigger_contract(
        "organizations_organizationrepresentation",
        "maru_lock_authority_provenance_writer",
        30,
    ),
    "authorization_appointment_provenance_lock": _trigger_contract(
        "organizations_representationappointment",
        "maru_lock_authority_provenance_writer",
        30,
    ),
    "authorization_event_edition_provenance_lock": _trigger_contract(
        "events_eventedition",
        "maru_lock_authority_provenance_writer",
        26,
    ),
    "authorization_department_provenance_lock": _trigger_contract(
        "workforce_department",
        "maru_lock_authority_provenance_writer",
        26,
    ),
    "authorization_resource_binding_provenance_lock": _trigger_contract(
        "authorization_scopedresourcebinding",
        "maru_lock_authority_provenance_writer",
        30,
    ),
    "authorization_provenance_latch_guard": _trigger_contract(
        "authorization_provenanceactivationlatch",
        "maru_guard_authority_provenance_latch",
        31,
    ),
    "authorization_provenance_activation_guard": _trigger_contract(
        "authorization_authorityprovenanceactivation",
        "maru_guard_authority_provenance_activation",
        31,
    ),
    "authorization_capability_grant_provenance_complete": _trigger_contract(
        "authorization_capabilitygrant",
        "maru_deferred_validate_authority_grant",
        5,
        deferrable=True,
        initially_deferred=True,
    ),
    "authorization_role_bundle_provenance_complete": _trigger_contract(
        "authorization_rolebundle",
        "maru_deferred_validate_authority_bundle",
        5,
        deferrable=True,
        initially_deferred=True,
    ),
    "authorization_role_assignment_provenance_complete": _trigger_contract(
        "authorization_roleassignment",
        "maru_deferred_validate_authority_assignment",
        5,
        deferrable=True,
        initially_deferred=True,
    ),
    "authorization_authority_issuance_complete": _trigger_contract(
        "authorization_authorityissuance",
        "maru_deferred_validate_authority_issuance",
        5,
        deferrable=True,
        initially_deferred=True,
    ),
    "authorization_authority_control_complete": _trigger_contract(
        "authorization_authoritycontrol",
        "maru_deferred_validate_authority_control",
        5,
        deferrable=True,
        initially_deferred=True,
    ),
    "authorization_provenance_activation_complete": _trigger_contract(
        "authorization_authorityprovenanceactivation",
        "maru_deferred_validate_provenance_activation",
        5,
        deferrable=True,
        initially_deferred=True,
    ),
    "authorization_provenance_latch_complete": _trigger_contract(
        "authorization_provenanceactivationlatch",
        "maru_deferred_validate_provenance_latch",
        17,
        deferrable=True,
        initially_deferred=True,
    ),
    "authorization_capability_grant_provenance_no_truncate": _trigger_contract(
        "authorization_capabilitygrant",
        "maru_prevent_authority_provenance_truncate",
        34,
    ),
    "authorization_role_bundle_provenance_no_truncate": _trigger_contract(
        "authorization_rolebundle",
        "maru_prevent_authority_provenance_truncate",
        34,
    ),
    "authorization_role_assignment_provenance_no_truncate": _trigger_contract(
        "authorization_roleassignment",
        "maru_prevent_authority_provenance_truncate",
        34,
    ),
    "authorization_authority_issuance_provenance_no_truncate": _trigger_contract(
        "authorization_authorityissuance",
        "maru_prevent_authority_provenance_truncate",
        34,
    ),
    "authorization_authority_control_provenance_no_truncate": _trigger_contract(
        "authorization_authoritycontrol",
        "maru_prevent_authority_provenance_truncate",
        34,
    ),
    "authorization_provenance_activation_no_truncate": _trigger_contract(
        "authorization_authorityprovenanceactivation",
        "maru_prevent_authority_provenance_truncate",
        34,
    ),
    "authorization_provenance_latch_no_truncate": _trigger_contract(
        "authorization_provenanceactivationlatch",
        "maru_prevent_authority_provenance_truncate",
        34,
    ),
    "authorization_activation_audit_provenance_no_truncate": _trigger_contract(
        "audit_auditevent",
        "maru_prevent_audit_event_truncate",
        34,
    ),
    "authorization_activation_audit_reserved_guard": _trigger_contract(
        "audit_auditevent",
        "maru_guard_authority_provenance_activation_audit",
        7,
    ),
    "authorization_provenance_latch_reseed": _trigger_contract(
        "authorization_provenanceactivationlatch",
        "maru_reseed_authority_provenance_latch",
        32,
    ),
    "organizations_representation_membership_provenance": _trigger_contract(
        "organizations_organizationrepresentation",
        "maru_deferred_validate_board_membership_from_representation",
        29,
        deferrable=True,
        initially_deferred=True,
    ),
    "organizations_appointment_membership_provenance": _trigger_contract(
        "organizations_representationappointment",
        "maru_deferred_validate_board_membership_from_appointment",
        29,
        deferrable=True,
        initially_deferred=True,
    ),
    "organizations_membership_board_provenance": _trigger_contract(
        "organizations_organizationmembership",
        "maru_deferred_validate_board_membership",
        29,
        deferrable=True,
        initially_deferred=True,
    ),
    "organizations_representation_deferred_integrity": _trigger_contract(
        "organizations_organizationrepresentation",
        "maru_deferred_validate_representation",
        29,
        deferrable=True,
        initially_deferred=True,
    ),
    "organizations_appointment_deferred_integrity": _trigger_contract(
        "organizations_representationappointment",
        "maru_deferred_validate_appointment",
        29,
        deferrable=True,
        initially_deferred=True,
    ),
    "authorization_role_assignment_deferred_board_integrity": _trigger_contract(
        "authorization_roleassignment",
        "maru_deferred_validate_role_assignment",
        29,
        deferrable=True,
        initially_deferred=True,
    ),
    "authorization_role_bundle_deferred_board_integrity": _trigger_contract(
        "authorization_rolebundle",
        "maru_deferred_validate_role_bundle",
        29,
        deferrable=True,
        initially_deferred=True,
    ),
    "organizations_membership_deferred_board_integrity": _trigger_contract(
        "organizations_organizationmembership",
        "maru_deferred_validate_membership",
        29,
        deferrable=True,
        initially_deferred=True,
    ),
    "identity_account_deferred_board_integrity": _trigger_contract(
        "identity_account",
        "maru_deferred_validate_board_account",
        17,
        deferrable=True,
        initially_deferred=True,
        columns=("is_active", "email_verified_at", "account_kind"),
    ),
    "organizations_parent_deferred_board_integrity": _trigger_contract(
        "organizations_organization",
        "maru_deferred_validate_board_organization",
        17,
        deferrable=True,
        initially_deferred=True,
        columns=("lifecycle",),
    ),
    "workforce_position_guard": _trigger_contract(
        "workforce_position",
        "maru_guard_workforce_position",
        31,
    ),
    "workforce_assignment_guard": _trigger_contract(
        "workforce_positionassignment",
        "maru_guard_workforce_assignment",
        31,
    ),
}

EXPECTED_FUNCTIONS = {
    "maru_assert_active_board_membership_provenance",
    "maru_assert_active_executive_board",
    "maru_assert_active_executive_board_v0009",
    "maru_workforce_role_evidence_matches_position",
    "maru_deferred_validate_board_membership_from_representation",
    "maru_deferred_validate_board_membership_from_appointment",
    "maru_deferred_validate_board_membership",
    "maru_deferred_validate_representation",
    "maru_deferred_validate_appointment",
    "maru_deferred_validate_role_assignment",
    "maru_deferred_validate_role_bundle",
    "maru_deferred_validate_membership",
    "maru_deferred_validate_board_account",
    "maru_deferred_validate_board_organization",
    "maru_guard_workforce_position",
    "maru_guard_workforce_assignment",
    "maru_authorization_capability_min_scope",
    "maru_authorization_scope_rank",
    "maru_authorization_scope_contains",
    "maru_validate_capability_grant",
    "maru_prevent_authority_record_delete",
    "maru_validate_role_assignment",
    "maru_validate_role_bundle_catalog",
    "maru_prevent_role_bundle_mutation",
    "maru_validate_scoped_resource_binding",
    "maru_prevent_scoped_resource_binding_mutation",
    "maru_reject_retired_authority_target",
    "maru_guard_department_retirement_authority",
    "maru_lock_retired_department_authority_writer",
    "maru_guard_audit_event",
    "maru_guard_authority_provenance_activation_audit",
    "maru_audit_test_reset_allowed",
    "maru_prevent_audit_event_truncate",
    "maru_validate_authority_issuance_insert",
    "maru_validate_authority_control_insert",
    "maru_prevent_authority_issuance_mutation",
    "maru_prevent_authority_control_mutation",
    "maru_authority_provenance_test_reset_allowed",
    "maru_authority_provenance_is_active",
    "maru_lock_authority_provenance_latch",
    "maru_lock_authority_provenance_writer",
    "maru_guard_authority_provenance_latch",
    "maru_guard_authority_provenance_activation",
    "maru_prevent_authority_provenance_truncate",
    "maru_reseed_authority_provenance_latch",
    "maru_authority_scope_is_current_v1",
    "maru_authority_scope_contains_v1",
    "maru_assert_authority_issuance_complete_internal",
    "maru_assert_authority_issuance_complete",
    "maru_assert_authority_target_complete",
    "maru_authority_bundle_historical_v1",
    "maru_authority_issuance_valid_v1",
    "maru_assert_authority_provenance_activation",
    "maru_deferred_validate_authority_grant",
    "maru_deferred_validate_authority_bundle",
    "maru_deferred_validate_authority_assignment",
    "maru_deferred_validate_authority_issuance",
    "maru_deferred_validate_authority_control",
    "maru_deferred_validate_provenance_activation",
    "maru_deferred_validate_provenance_latch",
}


def _migrate(target: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate([target])
    return executor


def _function_definition_contract(
    signatures: tuple[str, ...],
) -> dict[str, tuple[str, list[str] | None]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT signature,
                   pg_get_functiondef(to_regprocedure(signature)),
                   procedure.proconfig
              FROM unnest(%s::text[]) AS signatures(signature)
              JOIN pg_proc AS procedure
                ON procedure.oid = to_regprocedure(signature)
             ORDER BY signature
            """,
            [list(signatures)],
        )
        return {row[0]: (row[1], row[2]) for row in cursor.fetchall()}


def _administrator() -> Account:
    return AccountFactory(is_staff=True, is_superuser=True)


def _activate(administrator: Account | None = None) -> AuthorityProvenanceActivation:
    actor = administrator or _administrator()
    with override_settings(REQUIRE_EXACT_AUTHORITY_PROVENANCE=True):
        result = activate_authority_provenance(
            actor=actor,
            reason="Select exact authority provenance for the schema test.",
            correlation_id=uuid4(),
            acknowledge_processes_stopped=True,
            source_channel="test",
        )
    assert result.production_status == "ready"
    return AuthorityProvenanceActivation.objects.get(singleton=True)


def _append_matching_activation_audit(
    *,
    actor_id: UUID,
    correlation_id: UUID,
    activated_at: datetime,
    operation: str = "authorization.authority_provenance.activate",
    source_channel: str = "test",
    schema_version: int = 1,
) -> AuditEvent:
    return AuditEvent.objects.create(
        schema_version=schema_version,
        occurred_at=activated_at,
        principal_kind=Account.Kind.PLATFORM_ADMINISTRATOR,
        principal_id=actor_id,
        principal_context_id=None,
        organization_id=None,
        event_edition_id=None,
        capability_code="authorization.manage_roles",
        operation=operation,
        target_type="authorization.authority_provenance_activation",
        target_id=None,
        outcome=AuditEvent.Outcome.ALLOW,
        reason_code="exact_lineage_cutover",
        obligations=["reason", "audit", "stopped_processes"],
        changed_fields=["authority_provenance_activation"],
        correlation_id=correlation_id,
        source_channel=source_channel,
        delegated=False,
        elevated=True,
        break_glass=False,
        safe_metadata={
            "contract_version": AUTHORITY_PROVENANCE_CONTRACT_VERSION,
            "policy_version": AUTHORITY_PROVENANCE_ACTIVATION_POLICY_VERSION,
        },
        retention_class="security-extended",
    )


def _insert_raw_activation_with_audit(
    *,
    actor_id: UUID,
    correlation_id: UUID,
    caller_timestamp: datetime | None = None,
    marker_reason: str = "Prove the database-owned cutover instant.",
    audit_source_channel: str = "test",
    audit_schema_version: int = 1,
) -> datetime:
    supplied_timestamp = caller_timestamp or timezone.now()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO authorization_authorityprovenanceactivation(
                singleton,
                contract_version,
                policy_version,
                reason,
                correlation_id,
                activated_at,
                activated_by_id
            )
            VALUES (TRUE, %s, %s, %s, %s, %s, %s)
            RETURNING activated_at
            """,
            [
                AUTHORITY_PROVENANCE_CONTRACT_VERSION,
                AUTHORITY_PROVENANCE_ACTIVATION_POLICY_VERSION,
                marker_reason,
                correlation_id,
                supplied_timestamp,
                actor_id,
            ],
        )
        row = cursor.fetchone()
    assert row is not None
    database_timestamp = row[0]
    _append_matching_activation_audit(
        actor_id=actor_id,
        correlation_id=correlation_id,
        activated_at=database_timestamp,
        source_channel=audit_source_channel,
        schema_version=audit_schema_version,
    )
    return database_timestamp


def _raw_issuance_for_grant(*, grant_id: UUID, evaluated_at: datetime) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO authorization_authorityissuance(
                public_id,
                policy_version,
                evaluated_at,
                capability_grant_id,
                role_bundle_id,
                role_assignment_id,
                created_at
            )
            VALUES (%s, %s, %s, %s, NULL, NULL, %s)
            RETURNING ordinal
            """,
            [uuid4(), POLICY_VERSION, evaluated_at, grant_id, timezone.now()],
        )
        row = cursor.fetchone()
    assert row is not None
    return int(row[0])


def _database_error_sqlstate(error: BaseException) -> str | None:
    candidate: BaseException | None = error
    while candidate is not None:
        sqlstate = getattr(candidate, "sqlstate", None)
        if isinstance(sqlstate, str):
            return sqlstate
        candidate = candidate.__cause__
    return None


def _execute_statements(*statements: str) -> None:
    with transaction.atomic(), connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)


def _insert_raw_marker_at_isolation(
    *,
    actor: Account,
    isolation_level: str,
) -> None:
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(f"SET TRANSACTION ISOLATION LEVEL {isolation_level}")
        AuthorityProvenanceActivation.objects.create(
            singleton=True,
            contract_version=AUTHORITY_PROVENANCE_CONTRACT_VERSION,
            policy_version=AUTHORITY_PROVENANCE_ACTIVATION_POLICY_VERSION,
            activated_by=actor,
            reason="Reject a cutover under a stale-snapshot isolation level.",
            correlation_id=uuid4(),
        )


def _wait_for_advisory_block(
    *,
    waiting_pid: int,
    blocking_pid: int,
    timeout: float = 10.0,
) -> None:
    deadline = monotonic() + timeout
    last_observation: tuple[object, ...] | None = None
    while monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT activity.wait_event_type,
                       activity.wait_event,
                       %s = ANY(pg_blocking_pids(activity.pid))
                  FROM pg_stat_activity AS activity
                 WHERE activity.pid = %s
                """,
                [blocking_pid, waiting_pid],
            )
            last_observation = cursor.fetchone()
        if (
            last_observation is not None
            and last_observation[0] == "Lock"
            and str(last_observation[1]).lower() == "advisory"
            and last_observation[2] is True
        ):
            return
        sleep(0.025)
    raise AssertionError(
        "Backend did not reach the expected advisory-lock wait; "
        f"last observation was {last_observation!r}."
    )


def test_catalog_contract_is_exact_and_enabled() -> None:
    names = sorted(EXPECTED_TRIGGER_CONTRACTS)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT trigger.tgname::text,
                   relation.relname::text,
                   procedure.proname::text,
                   trigger.tgtype,
                   trigger.tgenabled,
                   trigger.tgdeferrable,
                   trigger.tginitdeferred,
                   ARRAY(
                       SELECT attribute.attname::text
                         FROM unnest(
                                  trigger.tgattr::smallint[]
                              ) WITH ORDINALITY AS selected(attnum, position)
                         JOIN pg_attribute AS attribute
                           ON attribute.attrelid = trigger.tgrelid
                          AND attribute.attnum = selected.attnum
                        ORDER BY selected.position
                   )
              FROM pg_trigger AS trigger
              JOIN pg_class AS relation ON relation.oid = trigger.tgrelid
              JOIN pg_proc AS procedure ON procedure.oid = trigger.tgfoid
             WHERE NOT trigger.tgisinternal
               AND trigger.tgname::text = ANY(%s::text[])
             ORDER BY trigger.tgname
            """,
            [names],
        )
        installed = {
            row[0]: (*tuple(row[1:7]), tuple(row[7] or ())) for row in cursor.fetchall()
        }
        cursor.execute(
            """
            SELECT DISTINCT procedure.proname::text
              FROM pg_proc AS procedure
              JOIN pg_namespace AS namespace
                ON namespace.oid = procedure.pronamespace
             WHERE namespace.nspname = ANY(current_schemas(FALSE))
               AND procedure.proname::text = ANY(%s::text[])
            """,
            [sorted(EXPECTED_FUNCTIONS)],
        )
        functions = {row[0] for row in cursor.fetchall()}
        cursor.execute(
            """
            SELECT procedure.proname::text,
                   procedure.proconfig
              FROM pg_proc AS procedure
              JOIN pg_namespace AS namespace
                ON namespace.oid = procedure.pronamespace
             WHERE namespace.nspname = 'public'
               AND procedure.proname::text = ANY(%s::text[])
             ORDER BY procedure.proname
            """,
            [sorted(EXPECTED_FUNCTIONS)],
        )
        function_settings = {row[0]: row[1] for row in cursor.fetchall()}
        cursor.execute(
            """
            SELECT procedure.proname::text,
                   procedure.prosecdef,
                   NOT EXISTS (
                       SELECT 1
                         FROM aclexplode(
                             COALESCE(
                                 procedure.proacl,
                                 acldefault('f', procedure.proowner)
                             )
                         ) AS privilege
                        WHERE privilege.grantee = 0
                          AND privilege.privilege_type = 'EXECUTE'
                   )
              FROM pg_proc AS procedure
              JOIN pg_namespace AS namespace
                ON namespace.oid = procedure.pronamespace
             WHERE namespace.nspname = 'public'
               AND procedure.proname IN (
                   'maru_guard_authority_provenance_activation_audit',
                   'maru_lock_authority_provenance_latch'
               )
             ORDER BY procedure.proname
            """
        )
        privileged_function_contract = {
            row[0]: tuple(row[1:]) for row in cursor.fetchall()
        }
        cursor.execute(
            """
            SELECT table_relation.relname::text,
                   access_method.amname::text,
                   catalog.indisunique,
                   catalog.indisvalid,
                   catalog.indisready,
                   catalog.indislive,
                   catalog.indnkeyatts,
                   catalog.indnatts,
                   catalog.indexprs IS NULL,
                   ARRAY(
                       SELECT pg_get_indexdef(
                           catalog.indexrelid,
                           key_position,
                           TRUE
                       )
                         FROM generate_series(
                             1,
                             catalog.indnkeyatts
                         ) AS key_position
                        ORDER BY key_position
                   ),
                   pg_get_expr(catalog.indpred, catalog.indrelid, TRUE)
              FROM pg_index AS catalog
              JOIN pg_class AS index_relation
                ON index_relation.oid = catalog.indexrelid
              JOIN pg_class AS table_relation
                ON table_relation.oid = catalog.indrelid
              JOIN pg_am AS access_method
                ON access_method.oid = index_relation.relam
             WHERE index_relation.relname =
                   'authorization_provenance_activation_audit_unique'
            """
        )
        audit_index = cursor.fetchone()

    assert installed == EXPECTED_TRIGGER_CONTRACTS
    assert functions == EXPECTED_FUNCTIONS
    assert function_settings == {
        name: ["search_path=pg_catalog, public, pg_temp"] for name in EXPECTED_FUNCTIONS
    }
    assert privileged_function_contract == {
        "maru_guard_authority_provenance_activation_audit": (False, True),
        "maru_lock_authority_provenance_latch": (True, True),
    }
    assert audit_index is not None
    assert tuple(audit_index[:9]) == (
        "audit_auditevent",
        "btree",
        True,
        True,
        True,
        True,
        2,
        2,
        True,
    )
    assert tuple(audit_index[9]) == ("operation", "correlation_id")
    assert audit_index[10] in {
        "operation = 'authorization.authority_provenance.activate'::text",
        "operation::text = 'authorization.authority_provenance.activate'::text",
        "(operation)::text = 'authorization.authority_provenance.activate'::text",
    }


def test_fresh_schema_preseeds_one_dormant_latch() -> None:
    assert list(
        AuthorityProvenanceActivationLatch.objects.values_list(
            "singleton",
            "generation",
        )
    ) == [(True, 0)]
    assert not AuthorityProvenanceActivation.objects.exists()


def test_temp_marker_and_latch_cannot_forge_dormant_activation() -> None:
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TEMP TABLE authorization_provenanceactivationlatch
            (LIKE public.authorization_provenanceactivationlatch INCLUDING DEFAULTS)
            ON COMMIT DROP
            """
        )
        cursor.execute(
            """
            CREATE TEMP TABLE authorization_authorityprovenanceactivation
            (LIKE public.authorization_authorityprovenanceactivation
                INCLUDING DEFAULTS)
            ON COMMIT DROP
            """
        )
        cursor.execute(
            """
            INSERT INTO pg_temp.authorization_provenanceactivationlatch(
                singleton,
                generation
            ) VALUES (TRUE, 1)
            """
        )
        cursor.execute(
            """
            INSERT INTO pg_temp.authorization_authorityprovenanceactivation(
                singleton,
                contract_version,
                policy_version,
                reason,
                correlation_id,
                activated_at,
                activated_by_id
            ) VALUES (TRUE, %s, %s, %s, %s, %s, %s)
            """,
            [
                "forged-contract",
                "forged-policy",
                "Temp shadow must not select activation.",
                uuid4(),
                timezone.now(),
                uuid4(),
            ],
        )
        cursor.execute("SET LOCAL search_path = pg_temp, public, pg_catalog")
        cursor.execute("SELECT public.maru_authority_provenance_is_active()")
        assert cursor.fetchone() == (False,)


def test_temp_relations_and_reset_helpers_cannot_bypass_exact_guards() -> None:
    organization = OrganizationFactory()
    actor, approver = activate_synthetic_board(organization)
    target = resolve_organization_target(organization_id=organization.id)
    assert target is not None
    recipient = AccountFactory()
    evaluated_at = timezone.now()
    grant = grant_capability_direct(
        actor=actor,
        approver=approver,
        recipient=recipient,
        capability_code="events.view_basic",
        target=target,
        effective_from=evaluated_at,
        expires_at=evaluated_at + timedelta(hours=2),
        reason="Create exact public lineage before shadow regression.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    issuance = AuthorityIssuance.objects.get(capability_grant=grant)
    incomplete_grant_id = uuid4()
    incomplete_principal = AccountFactory()
    administrator = _administrator()
    with transaction.atomic():
        _insert_raw_activation_with_audit(
            actor_id=administrator.id,
            correlation_id=uuid4(),
        )

    shadow_relations = (
        "identity_account",
        "authorization_capabilitygrant",
        "authorization_rolebundle",
        "authorization_roleassignment",
        "authorization_authorityissuance",
        "authorization_authoritycontrol",
        "authorization_provenanceactivationlatch",
        "authorization_authorityprovenanceactivation",
        "organizations_organization",
        "organizations_organizationmembership",
        "organizations_organizationrepresentation",
        "organizations_representationappointment",
    )
    with transaction.atomic(), connection.cursor() as cursor:
        for relation in shadow_relations:
            cursor.execute(
                f"CREATE TEMP TABLE {relation} "
                f"(LIKE public.{relation} INCLUDING DEFAULTS) ON COMMIT DROP"
            )
        cursor.execute(
            """
            INSERT INTO pg_temp.authorization_provenanceactivationlatch(
                singleton,
                generation
            ) VALUES (TRUE, 0)
            """
        )
        cursor.execute(
            """
            CREATE FUNCTION pg_temp.maru_authority_provenance_test_reset_allowed()
            RETURNS boolean LANGUAGE sql AS 'SELECT TRUE'
            """
        )
        cursor.execute(
            """
            CREATE FUNCTION pg_temp.maru_audit_test_reset_allowed()
            RETURNS boolean LANGUAGE sql AS 'SELECT TRUE'
            """
        )
        cursor.execute("SET LOCAL search_path = pg_temp, public, pg_catalog")
        cursor.execute("SELECT public.maru_authority_provenance_is_active()")
        assert cursor.fetchone() == (True,)
        cursor.execute(
            """
            SELECT public.maru_authority_issuance_valid_v1(
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, TRUE, TRUE, ARRAY[]::bigint[], 0
            )
            """,
            [
                issuance.ordinal,
                grant.principal_id,
                grant.capability_code,
                grant.organization_id,
                grant.edition_id,
                grant.department_id,
                grant.resource_binding_id,
                grant.effective_from,
                grant.expires_at,
                timezone.now(),
            ],
        )
        assert cursor.fetchone() == (True,)

        with (  # noqa: PT012
            pytest.raises(DatabaseError),
            transaction.atomic(),
            connection.cursor() as nested_cursor,
        ):
            nested_cursor.execute(
                """
                    INSERT INTO public.authorization_capabilitygrant(
                        id,
                        created_at,
                        updated_at,
                        organization_id,
                        edition_id,
                        department_id,
                        resource_binding_id,
                        principal_id,
                        capability_code,
                        effective_from,
                        expires_at,
                        revoked_at,
                        granted_by_id,
                        approved_by_id,
                        delegated_from_id,
                        reason,
                        revoked_by_id,
                        revocation_reason
                    ) VALUES (
                        %s, %s, %s, %s, NULL, NULL, NULL, %s, %s, %s,
                        NULL, NULL, %s, %s, NULL, %s, NULL, ''
                    )
                    """,
                [
                    incomplete_grant_id,
                    timezone.now(),
                    timezone.now(),
                    organization.id,
                    incomplete_principal.id,
                    "events.view_basic",
                    timezone.now(),
                    actor.id,
                    approver.id,
                    "Temp latch and marker cannot make completeness dormant.",
                ],
            )
            nested_cursor.execute(
                """
                SET CONSTRAINTS
                    authorization_capability_grant_provenance_complete
                IMMEDIATE
                """
            )

        for truncate_statement in (
            "TRUNCATE public.authorization_capabilitygrant CASCADE",
            "TRUNCATE public.audit_auditevent CASCADE",
        ):
            with (  # noqa: PT012
                pytest.raises(DatabaseError),
                transaction.atomic(),
                connection.cursor() as nested_cursor,
            ):
                nested_cursor.execute(
                    "SET LOCAL maru.authority_provenance_test_reset = 'off'"
                )
                nested_cursor.execute(truncate_statement)

    assert CapabilityGrant.objects.filter(pk=grant.pk).exists()
    assert AuthorityIssuance.objects.filter(pk=issuance.pk).exists()
    assert AuthorityProvenanceActivation.objects.filter(singleton=True).exists()
    assert not CapabilityGrant.objects.filter(pk=incomplete_grant_id).exists()


def test_temp_authority_tables_cannot_bypass_delegated_issuance_guard() -> None:
    evaluated_at = timezone.now()
    parent = CapabilityGrantFactory(
        effective_from=evaluated_at - timedelta(hours=1),
        expires_at=evaluated_at + timedelta(hours=2),
    )
    child = _delegated_child(
        parent=parent,
        recipient=AccountFactory(),
        effective_from=evaluated_at,
        expires_at=evaluated_at + timedelta(hours=1),
    )
    CapabilityGrant.objects.bulk_create([child])

    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TEMP TABLE authorization_capabilitygrant
            (LIKE public.authorization_capabilitygrant INCLUDING DEFAULTS)
            ON COMMIT DROP
            """
        )
        cursor.execute(
            """
            CREATE TEMP TABLE authorization_authorityissuance
            (LIKE public.authorization_authorityissuance INCLUDING DEFAULTS)
            ON COMMIT DROP
            """
        )
        cursor.execute("SET LOCAL search_path = pg_temp, public, pg_catalog")
        with (
            pytest.raises(DatabaseError),
            transaction.atomic(),
            connection.cursor() as nested_cursor,
        ):
            nested_cursor.execute(
                """
                    INSERT INTO public.authorization_authorityissuance(
                        public_id,
                        policy_version,
                        evaluated_at,
                        capability_grant_id,
                        created_at
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                [uuid4(), POLICY_VERSION, evaluated_at, child.id, evaluated_at],
            )

    assert not AuthorityIssuance.objects.filter(capability_grant_id=child.id).exists()


def test_temp_authority_tables_cannot_rebind_control_principal() -> None:
    organization = OrganizationFactory()
    actor, approver = activate_synthetic_board(organization)
    evaluated_at = timezone.now()
    target_grant = CapabilityGrant(
        organization=organization,
        principal=AccountFactory(),
        capability_code="events.view_basic",
        effective_from=evaluated_at,
        expires_at=evaluated_at + timedelta(hours=1),
        granted_by=actor,
        approved_by=approver,
        reason="Keep the public target actor immutable during control validation.",
    )
    CapabilityGrant.objects.bulk_create([target_grant])
    target_ordinal = _raw_issuance_for_grant(
        grant_id=target_grant.id,
        evaluated_at=evaluated_at,
    )
    forged_source = AuthorityIssuance.objects.get(
        role_assignment__principal=approver,
        role_assignment__role_bundle__code="executive-board",
    )
    forged_control_id = uuid4()

    shadow_relations = (
        "identity_account",
        "authorization_capabilitygrant",
        "authorization_rolebundle",
        "authorization_roleassignment",
        "authorization_authorityissuance",
        "authorization_authoritycontrol",
    )
    with transaction.atomic(), connection.cursor() as cursor:
        for relation in shadow_relations:
            cursor.execute(
                f"CREATE TEMP TABLE {relation} ON COMMIT DROP "
                f"AS TABLE public.{relation}"
            )
        cursor.execute(
            """
            UPDATE pg_temp.authorization_capabilitygrant
               SET granted_by_id = %s
             WHERE id = %s
            """,
            [approver.id, target_grant.id],
        )
        cursor.execute("SET LOCAL search_path = pg_temp, public, pg_catalog")
        with (
            pytest.raises(DatabaseError),
            transaction.atomic(),
            connection.cursor() as nested_cursor,
        ):
            nested_cursor.execute(
                """
                    INSERT INTO public.authorization_authoritycontrol(
                        id,
                        created_at,
                        updated_at,
                        role,
                        basis,
                        policy_version,
                        evaluated_at,
                        appointment_id,
                        issuance_id,
                        principal_id,
                        representation_id,
                        source_issuance_id
                    ) VALUES (
                        %s, %s, %s, 'actor', 'persistent_authority',
                        %s, %s, NULL, %s, %s, NULL, %s
                    )
                    """,
                [
                    forged_control_id,
                    timezone.now(),
                    timezone.now(),
                    POLICY_VERSION,
                    evaluated_at,
                    target_ordinal,
                    approver.id,
                    forged_source.ordinal,
                ],
            )

    assert not AuthorityControl.objects.filter(pk=forged_control_id).exists()


def test_clean_reverse_and_forward_are_symmetric(
    restores_current_migration_graph: None,
) -> None:
    del restores_current_migration_graph
    _migrate(AUTHORIZATION_BEFORE_ACTIVATION)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT to_regclass('authorization_authorityprovenanceactivation'),
                   to_regclass('authorization_provenanceactivationlatch'),
                   to_regprocedure('maru_lock_authority_provenance_writer()')
            """
        )
        assert cursor.fetchone() == (None, None, None)

    executor = _migrate(AUTHORIZATION_AFTER_ACTIVATION)
    apps = executor.loader.project_state([AUTHORIZATION_AFTER_ACTIVATION]).apps
    latch_model = apps.get_model(
        "authorization",
        "AuthorityProvenanceActivationLatch",
    )
    assert list(latch_model.objects.values_list("singleton", "generation")) == [
        (True, 0)
    ]


def test_reverse_restores_prior_owned_issuance_function_definitions(
    restores_current_migration_graph: None,
) -> None:
    del restores_current_migration_graph
    _migrate(AUTHORIZATION_BEFORE_ISSUANCE)
    _migrate(AUTHORIZATION_BEFORE_ACTIVATION)
    baseline = _function_definition_contract(PRIOR_ISSUANCE_FUNCTIONS)
    assert baseline.keys() == set(PRIOR_ISSUANCE_FUNCTIONS)
    assert all(settings is None for _, settings in baseline.values())

    _migrate(AUTHORIZATION_AFTER_ACTIVATION)
    hardened = _function_definition_contract(PRIOR_ISSUANCE_FUNCTIONS)
    assert all(
        settings == ["search_path=pg_catalog, public, pg_temp"]
        for _, settings in hardened.values()
    )

    _migrate(AUTHORIZATION_BEFORE_ACTIVATION)
    assert _function_definition_contract(PRIOR_ISSUANCE_FUNCTIONS) == baseline
    _migrate(AUTHORIZATION_AFTER_ACTIVATION)


def test_reverse_restores_foundational_authorization_function_definitions(
    restores_current_migration_graph: None,
) -> None:
    del restores_current_migration_graph
    _migrate(AUTHORIZATION_BEFORE_ACTIVATION)
    baseline = _function_definition_contract(PRIOR_FOUNDATIONAL_AUTHORIZATION_FUNCTIONS)
    assert baseline.keys() == set(PRIOR_FOUNDATIONAL_AUTHORIZATION_FUNCTIONS)
    assert all(settings is None for _, settings in baseline.values())

    _migrate(AUTHORIZATION_AFTER_ACTIVATION)
    hardened = _function_definition_contract(PRIOR_FOUNDATIONAL_AUTHORIZATION_FUNCTIONS)
    assert all(
        settings == ["search_path=pg_catalog, public, pg_temp"]
        for _, settings in hardened.values()
    )

    _migrate(AUTHORIZATION_BEFORE_ACTIVATION)
    assert (
        _function_definition_contract(PRIOR_FOUNDATIONAL_AUTHORIZATION_FUNCTIONS)
        == baseline
    )
    _migrate(AUTHORIZATION_AFTER_ACTIVATION)


def test_reverse_refuses_an_activated_latch(
    restores_current_migration_graph: None,
) -> None:
    del restores_current_migration_graph
    _activate()

    with pytest.raises(RuntimeError, match=r"Cannot (?:remove|reverse)"):
        _migrate(AUTHORIZATION_BEFORE_ACTIVATION)

    assert AuthorityProvenanceActivation.objects.count() == 1
    assert AuthorityProvenanceActivationLatch.objects.get().generation == 1


def test_reserved_activation_audit_requires_same_transaction_marker() -> None:
    actor = _administrator()
    correlation_id = uuid4()
    occurred_at = timezone.now()

    with (
        pytest.raises(DatabaseError),
        transaction.atomic(),
    ):
        _append_matching_activation_audit(
            actor_id=actor.id,
            correlation_id=correlation_id,
            activated_at=occurred_at,
        )

    _append_matching_activation_audit(
        actor_id=actor.id,
        correlation_id=correlation_id,
        activated_at=occurred_at,
        operation="authorization.authority_provenance.preview",
    )
    assert AuditEvent.objects.filter(correlation_id=correlation_id).count() == 1


def test_reserved_activation_audit_requires_same_transaction_latch_transition() -> None:
    actor = _administrator()
    correlation_id = uuid4()

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE public.authorization_authorityprovenanceactivation
                DISABLE TRIGGER authorization_provenance_activation_guard
                """
            )
        with pytest.raises(DatabaseError), transaction.atomic():
            _insert_raw_activation_with_audit(
                actor_id=actor.id,
                correlation_id=correlation_id,
            )
        transaction.set_rollback(True)

    assert not AuthorityProvenanceActivation.objects.exists()
    assert AuthorityProvenanceActivationLatch.objects.get().generation == 0
    assert not AuditEvent.objects.filter(correlation_id=correlation_id).exists()


def test_database_owns_marker_timestamp_and_accepts_one_exact_raw_audit() -> None:
    actor = _administrator()
    correlation_id = uuid4()
    caller_timestamp = timezone.now() + timedelta(days=3650)

    with transaction.atomic():
        database_timestamp = _insert_raw_activation_with_audit(
            actor_id=actor.id,
            correlation_id=correlation_id,
            caller_timestamp=caller_timestamp,
        )

    marker = AuthorityProvenanceActivation.objects.get(singleton=True)
    assert marker.activated_at == database_timestamp
    assert marker.activated_at < caller_timestamp - timedelta(days=3000)
    assert AuthorityProvenanceActivationLatch.objects.get().generation == 1
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT marker.xmin::text, event.xmin::text
              FROM authorization_authorityprovenanceactivation AS marker
              JOIN audit_auditevent AS event
                ON event.correlation_id = marker.correlation_id
               AND event.operation =
                   'authorization.authority_provenance.activate'
             WHERE marker.singleton IS TRUE
            """
        )
        transaction_ids = cursor.fetchone()
    assert transaction_ids is not None
    assert transaction_ids[0] == transaction_ids[1]

    with pytest.raises(DatabaseError), transaction.atomic():
        _append_matching_activation_audit(
            actor_id=actor.id,
            correlation_id=uuid4(),
            activated_at=database_timestamp,
        )
    assert (
        AuditEvent.objects.filter(
            operation="authorization.authority_provenance.activate",
        ).count()
        == 1
    )


def test_raw_marker_without_exact_audit_rolls_marker_and_latch_back() -> None:
    actor = _administrator()

    with pytest.raises(DatabaseError), transaction.atomic():
        AuthorityProvenanceActivation.objects.create(
            singleton=True,
            contract_version=AUTHORITY_PROVENANCE_CONTRACT_VERSION,
            policy_version=AUTHORITY_PROVENANCE_ACTIVATION_POLICY_VERSION,
            activated_by=actor,
            reason="Reject a marker that has no security audit.",
            correlation_id=uuid4(),
        )

    assert not AuthorityProvenanceActivation.objects.exists()
    assert AuthorityProvenanceActivationLatch.objects.get().generation == 0


@pytest.mark.parametrize(
    ("marker_reason", "audit_source_channel", "audit_schema_version"),
    [
        ("   ", "test", 1),
        ("Exact marker with malformed audit channel.", "   ", 1),
        ("Exact marker with malformed audit schema.", "test", 2),
    ],
)
def test_raw_activation_rejects_malformed_exact_evidence(
    marker_reason: str,
    audit_source_channel: str,
    audit_schema_version: int,
) -> None:
    actor = _administrator()
    correlation_id = uuid4()

    with pytest.raises(DatabaseError), transaction.atomic():
        _insert_raw_activation_with_audit(
            actor_id=actor.id,
            correlation_id=correlation_id,
            marker_reason=marker_reason,
            audit_source_channel=audit_source_channel,
            audit_schema_version=audit_schema_version,
        )

    assert not AuthorityProvenanceActivation.objects.exists()
    assert AuthorityProvenanceActivationLatch.objects.get().generation == 0
    assert not AuditEvent.objects.filter(correlation_id=correlation_id).exists()


@pytest.mark.parametrize(
    "mutation_sql",
    [
        "UPDATE public.authorization_rolebundle "
        "SET name = 'Executive Council' WHERE id = %s",
        "UPDATE public.authorization_rolebundle SET version = 2 WHERE id = %s",
        "UPDATE public.authorization_rolebundle "
        "SET capability_codes = array_append(capability_codes, 'events.create') "
        "WHERE id = %s",
    ],
)
def test_raw_activation_rejects_malformed_executive_board_bundle(
    mutation_sql: str,
) -> None:
    organization = OrganizationFactory()
    activate_synthetic_board(organization)
    bundle = RoleBundle.objects.get(
        organization=organization,
        code="executive-board",
    )
    administrator = _administrator()

    with pytest.raises(DatabaseError), transaction.atomic():  # noqa: PT012
        with connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE public.authorization_rolebundle
                DISABLE TRIGGER authorization_role_bundle_immutable
                """
            )
            cursor.execute(
                """
                ALTER TABLE public.authorization_rolebundle
                DISABLE TRIGGER
                    authorization_role_bundle_deferred_board_integrity
                """
            )
            cursor.execute(mutation_sql, [bundle.id])
            cursor.execute(
                """
                ALTER TABLE public.authorization_rolebundle
                ENABLE TRIGGER authorization_role_bundle_immutable
                """
            )
            cursor.execute(
                """
                ALTER TABLE public.authorization_rolebundle
                ENABLE TRIGGER
                    authorization_role_bundle_deferred_board_integrity
                """
            )
        _insert_raw_activation_with_audit(
            actor_id=administrator.id,
            correlation_id=uuid4(),
        )

    bundle.refresh_from_db()
    assert bundle.name == "Executive Board"
    assert bundle.version == 1
    assert len(bundle.capability_codes) == 12
    assert not AuthorityProvenanceActivation.objects.exists()
    assert AuthorityProvenanceActivationLatch.objects.get().generation == 0


@pytest.mark.parametrize(
    "mutation_sql",
    [
        "UPDATE public.authorization_rolebundle "
        "SET name = 'Executive Council' WHERE id = %s",
        "UPDATE public.authorization_rolebundle SET version = 2 WHERE id = %s",
        "UPDATE public.authorization_rolebundle "
        "SET capability_codes = array_append(capability_codes, 'events.create') "
        "WHERE id = %s",
    ],
)
def test_sql_lineage_rejects_malformed_executive_board_bundle(
    mutation_sql: str,
) -> None:
    organization = OrganizationFactory()
    activate_synthetic_board(organization)
    bundle = RoleBundle.objects.get(
        organization=organization,
        code="executive-board",
    )
    _activate()

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE public.authorization_rolebundle
                DISABLE TRIGGER authorization_role_bundle_immutable
                """
            )
            cursor.execute(
                """
                ALTER TABLE public.authorization_rolebundle
                DISABLE TRIGGER
                    authorization_role_bundle_deferred_board_integrity
                """
            )
            cursor.execute(mutation_sql, [bundle.id])
            cursor.execute(
                """
                ALTER TABLE public.authorization_rolebundle
                ENABLE TRIGGER authorization_role_bundle_immutable
                """
            )
            cursor.execute(
                """
                ALTER TABLE public.authorization_rolebundle
                ENABLE TRIGGER
                    authorization_role_bundle_deferred_board_integrity
                """
            )
            cursor.execute(
                """
                SELECT public.maru_authority_bundle_historical_v1(
                    %s, %s, NULL, ARRAY[]::bigint[], 0
                )
                """,
                [bundle.id, timezone.now()],
            )
            assert cursor.fetchone() == (False,)
        transaction.set_rollback(True)

    bundle.refresh_from_db()
    assert bundle.name == "Executive Board"
    assert bundle.version == 1
    assert len(bundle.capability_codes) == 12


@pytest.mark.parametrize(
    "mutation_sql",
    [
        "UPDATE public.authorization_roleassignment "
        "SET effective_from = effective_from + INTERVAL '1 second' WHERE id = %s",
        "UPDATE public.authorization_roleassignment "
        "SET expires_at = clock_timestamp() + INTERVAL '1 day' WHERE id = %s",
        "UPDATE public.authorization_roleassignment "
        "SET reason = 'Forged Board assignment' WHERE id = %s",
    ],
)
def test_sql_lineage_rejects_malformed_current_board_assignment(
    mutation_sql: str,
) -> None:
    organization = OrganizationFactory()
    actor, _approver = activate_synthetic_board(organization)
    bundle = RoleBundle.objects.get(
        organization=organization,
        code="executive-board",
    )
    assignment = RoleAssignment.objects.get(
        organization=organization,
        role_bundle=bundle,
        principal=actor,
    )
    issuance = AuthorityIssuance.objects.get(role_assignment=assignment)
    _activate()

    with transaction.atomic():
        with connection.cursor() as cursor:
            for trigger_name in (
                "authorization_role_assignment_guard",
                "authorization_role_assignment_subject_and_provenance_guard",
                "authorization_role_assignment_deferred_board_integrity",
            ):
                cursor.execute(
                    "ALTER TABLE public.authorization_roleassignment "
                    f"DISABLE TRIGGER {trigger_name}"
                )
            cursor.execute(mutation_sql, [assignment.id])
            for trigger_name in (
                "authorization_role_assignment_guard",
                "authorization_role_assignment_subject_and_provenance_guard",
                "authorization_role_assignment_deferred_board_integrity",
            ):
                cursor.execute(
                    "ALTER TABLE public.authorization_roleassignment "
                    f"ENABLE TRIGGER {trigger_name}"
                )
        assignment.refresh_from_db()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT public.maru_authority_issuance_valid_v1(
                    %s, %s, %s, %s, NULL, NULL, NULL,
                    %s, %s, %s, TRUE, TRUE, ARRAY[]::bigint[], 0
                )
                """,
                [
                    issuance.ordinal,
                    assignment.principal_id,
                    "events.view_basic",
                    assignment.organization_id,
                    assignment.effective_from,
                    assignment.expires_at,
                    timezone.now(),
                ],
            )
            assert cursor.fetchone() == (False,)
        transaction.set_rollback(True)

    assignment.refresh_from_db()
    assert assignment.effective_from == issuance.evaluated_at
    assert assignment.expires_at is None


@pytest.mark.parametrize("isolation_level", ["REPEATABLE READ", "SERIALIZABLE"])
def test_raw_marker_rejects_non_read_committed_isolation(
    isolation_level: str,
) -> None:
    actor = _administrator()

    with pytest.raises(DatabaseError) as captured:
        _insert_raw_marker_at_isolation(
            actor=actor,
            isolation_level=isolation_level,
        )

    assert _database_error_sqlstate(captured.value) == "25000"
    assert not AuthorityProvenanceActivation.objects.exists()
    assert AuthorityProvenanceActivationLatch.objects.get().generation == 0


def test_marker_latch_and_truncate_fences_and_test_reset() -> None:
    _activate()

    rejected_statements = (
        "UPDATE authorization_authorityprovenanceactivation "
        "SET reason = 'Forbidden rewrite' WHERE singleton IS TRUE",
        "DELETE FROM authorization_authorityprovenanceactivation "
        "WHERE singleton IS TRUE",
        "UPDATE authorization_provenanceactivationlatch "
        "SET generation = 0 WHERE singleton IS TRUE",
        "DELETE FROM authorization_provenanceactivationlatch WHERE singleton IS TRUE",
    )
    for statement in rejected_statements:
        with pytest.raises(DatabaseError):
            _execute_statements(statement)

    guarded_truncates = (
        "TRUNCATE authorization_capabilitygrant CASCADE",
        "TRUNCATE authorization_rolebundle CASCADE",
        "TRUNCATE authorization_roleassignment CASCADE",
        "TRUNCATE authorization_authorityissuance CASCADE",
        "TRUNCATE authorization_authoritycontrol CASCADE",
        "TRUNCATE authorization_authorityprovenanceactivation CASCADE",
        "TRUNCATE authorization_provenanceactivationlatch CASCADE",
        "TRUNCATE audit_auditevent CASCADE",
    )
    for truncate_statement in guarded_truncates:
        with pytest.raises(DatabaseError):
            _execute_statements(
                "SET LOCAL maru.authority_provenance_test_reset = 'off'",
                truncate_statement,
            )

    with pytest.raises(DatabaseError):
        _execute_statements(
            "SET LOCAL maru.authority_provenance_test_reset = 'off'",
            "TRUNCATE identity_account CASCADE",
        )

    assert AuthorityProvenanceActivation.objects.count() == 1
    assert AuthorityProvenanceActivationLatch.objects.get().generation == 1

    with connection.cursor() as cursor:
        cursor.execute(
            """
            TRUNCATE
                authorization_capabilitygrant,
                authorization_rolebundle,
                authorization_roleassignment,
                authorization_authorityissuance,
                authorization_authoritycontrol,
                authorization_authorityprovenanceactivation,
                authorization_provenanceactivationlatch,
                audit_auditevent
            CASCADE
            """
        )

    assert not AuthorityProvenanceActivation.objects.exists()
    assert list(
        AuthorityProvenanceActivationLatch.objects.values_list(
            "singleton",
            "generation",
        )
    ) == [(True, 0)]
    assert not AuditEvent.objects.exists()


def test_dormant_schema_keeps_raw_target_inserts_compatible() -> None:
    organization = OrganizationFactory()
    actor = AccountFactory()
    approver = AccountFactory()
    principal = AccountFactory()
    now = timezone.now()
    grant = CapabilityGrant(
        organization=organization,
        principal=principal,
        capability_code="events.view_basic",
        effective_from=now,
        granted_by=actor,
        approved_by=approver,
        reason="Dormant compatibility grant.",
    )
    bundle = RoleBundle(
        organization=organization,
        code=f"dormant-reader-{uuid4().hex[:12]}",
        name="Dormant reader",
        version=1,
        capability_codes=["events.view_basic"],
        created_by=actor,
        approved_by=approver,
        reason="Dormant compatibility bundle.",
    )
    assignment = RoleAssignment(
        organization=organization,
        principal=principal,
        role_bundle=bundle,
        effective_from=now,
        granted_by=actor,
        approved_by=approver,
        reason="Dormant compatibility assignment.",
    )

    with transaction.atomic():
        CapabilityGrant.objects.bulk_create([grant])
        RoleBundle.objects.bulk_create([bundle])
        RoleAssignment.objects.bulk_create([assignment])

    assert CapabilityGrant.objects.filter(pk=grant.pk).exists()
    assert RoleBundle.objects.filter(pk=bundle.pk).exists()
    assert RoleAssignment.objects.filter(pk=assignment.pk).exists()
    assert not AuthorityIssuance.objects.exists()


def test_post_activation_bulk_targets_require_complete_provenance() -> None:
    organization = OrganizationFactory()
    actor, approver = activate_synthetic_board(organization)
    target = resolve_organization_target(organization_id=organization.id)
    assert target is not None
    proven_bundle = create_role_bundle_version(
        actor=actor,
        approver=approver,
        target=target,
        code=f"proven-reader-{uuid4().hex[:12]}",
        name="Proven reader",
        capability_codes=("events.view_basic",),
        reason="Create a proven bundle before cutover.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    recipient = AccountFactory()
    now = timezone.now()
    _activate()

    incomplete_grant = CapabilityGrant(
        organization=organization,
        principal=recipient,
        capability_code="events.view_basic",
        effective_from=now,
        granted_by=actor,
        approved_by=approver,
        reason="This raw grant deliberately lacks an issuance.",
    )
    with pytest.raises(DatabaseError), transaction.atomic():
        CapabilityGrant.objects.bulk_create([incomplete_grant])
    assert not CapabilityGrant.objects.filter(pk=incomplete_grant.pk).exists()

    incomplete_bundle = RoleBundle(
        organization=organization,
        code=f"incomplete-reader-{uuid4().hex[:12]}",
        name="Incomplete reader",
        version=1,
        capability_codes=["events.view_basic"],
        created_by=actor,
        approved_by=approver,
        reason="This raw bundle deliberately lacks an issuance.",
    )
    with pytest.raises(DatabaseError), transaction.atomic():
        RoleBundle.objects.bulk_create([incomplete_bundle])
    assert not RoleBundle.objects.filter(pk=incomplete_bundle.pk).exists()

    incomplete_assignment = RoleAssignment(
        organization=organization,
        principal=recipient,
        role_bundle=proven_bundle,
        effective_from=now,
        granted_by=actor,
        approved_by=approver,
        reason="This raw assignment deliberately lacks an issuance.",
    )
    with pytest.raises(DatabaseError), transaction.atomic():
        RoleAssignment.objects.bulk_create([incomplete_assignment])
    assert not RoleAssignment.objects.filter(pk=incomplete_assignment.pk).exists()


@pytest.mark.parametrize("evaluation_offset", [-1, 3600])
def test_post_activation_issuance_evaluation_stays_in_active_era(
    evaluation_offset: int,
) -> None:
    organization = OrganizationFactory()
    actor, approver = activate_synthetic_board(organization)
    administrator = _administrator()
    with transaction.atomic():
        activated_at = _insert_raw_activation_with_audit(
            actor_id=administrator.id,
            correlation_id=uuid4(),
        )
    evaluated_at = activated_at + timedelta(seconds=evaluation_offset)
    target_grant = CapabilityGrant(
        organization=organization,
        principal=AccountFactory(),
        capability_code="events.view_basic",
        effective_from=timezone.now(),
        expires_at=timezone.now() + timedelta(hours=2),
        granted_by=actor,
        approved_by=approver,
        reason="Reject a fabricated issuance evaluation instant.",
    )

    with (  # noqa: PT012
        pytest.raises(DatabaseError, match="within the active era"),
        transaction.atomic(),
    ):
        CapabilityGrant.objects.bulk_create([target_grant])
        AuthorityIssuance.objects.bulk_create(
            [
                AuthorityIssuance(
                    capability_grant=target_grant,
                    policy_version=POLICY_VERSION,
                    evaluated_at=evaluated_at,
                )
            ]
        )
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SET CONSTRAINTS authorization_authority_issuance_complete
                IMMEDIATE
                """
            )

    assert not CapabilityGrant.objects.filter(pk=target_grant.pk).exists()


def _delegated_child(
    *,
    parent: CapabilityGrant,
    recipient: Account,
    effective_from: datetime,
    expires_at: datetime | None = None,
) -> CapabilityGrant:
    return CapabilityGrant(
        organization_id=parent.organization_id,
        edition_id=parent.edition_id,
        department_id=parent.department_id,
        resource_binding_id=parent.resource_binding_id,
        principal=recipient,
        capability_code=parent.capability_code,
        effective_from=effective_from,
        expires_at=expires_at,
        granted_by_id=parent.principal_id,
        approved_by=None,
        delegated_from=parent,
        reason="Exercise deterministic delegated issuance ordering.",
    )


def _raw_insert_delegated_grant_with_issuance(
    *,
    grant: CapabilityGrant,
    evaluated_at: datetime,
) -> None:
    with transaction.atomic():
        _raw_issuance_for_grant(
            grant_id=grant.id,
            evaluated_at=evaluated_at,
        )
        CapabilityGrant.objects.bulk_create([grant])


def _raw_insert_assignment_with_controls(
    *,
    assignment: RoleAssignment,
    evaluated_at: datetime,
    actor: Account,
    approver: Account,
    actor_source: AuthorityIssuance,
    approver_source: AuthorityIssuance,
) -> None:
    with transaction.atomic():
        RoleAssignment.objects.bulk_create([assignment])
        issuance = AuthorityIssuance.objects.bulk_create(
            [
                AuthorityIssuance(
                    role_assignment=assignment,
                    policy_version=POLICY_VERSION,
                    evaluated_at=evaluated_at,
                )
            ]
        )[0]
        AuthorityControl.objects.bulk_create(
            [
                AuthorityControl(
                    issuance=issuance,
                    role=AuthorityControl.Role.ACTOR,
                    principal=actor,
                    basis=AuthorityControl.Basis.PERSISTENT_AUTHORITY,
                    source_issuance=actor_source,
                    policy_version=POLICY_VERSION,
                    evaluated_at=evaluated_at,
                ),
                AuthorityControl(
                    issuance=issuance,
                    role=AuthorityControl.Role.APPROVER,
                    principal=approver,
                    basis=AuthorityControl.Basis.PERSISTENT_AUTHORITY,
                    source_issuance=approver_source,
                    policy_version=POLICY_VERSION,
                    evaluated_at=evaluated_at,
                ),
            ]
        )


def _create_direct_control_sources(
    *,
    organization: Organization,
    capability_code: str,
) -> tuple[
    Account,
    Account,
    Account,
    Account,
    CapabilityGrant,
    CapabilityGrant,
]:
    board_actor, board_approver = activate_synthetic_board(organization)
    target = resolve_organization_target(organization_id=organization.id)
    assert target is not None
    control_actor = AccountFactory()
    control_approver = AccountFactory()
    effective_from = timezone.now()
    expires_at = timezone.now() + timedelta(hours=2)
    actor_source = grant_capability_direct(
        actor=board_actor,
        approver=board_approver,
        recipient=control_actor,
        capability_code=capability_code,
        target=target,
        effective_from=effective_from,
        expires_at=expires_at,
        reason="Create the actor's exact control source.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    approver_source = grant_capability_direct(
        actor=board_actor,
        approver=board_approver,
        recipient=control_approver,
        capability_code=capability_code,
        target=target,
        effective_from=effective_from,
        expires_at=expires_at,
        reason="Create the approver's exact control source.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    return (
        board_actor,
        board_approver,
        control_actor,
        control_approver,
        actor_source,
        approver_source,
    )


def test_complete_delegated_target_and_issuance_allow_both_insert_orders() -> None:
    organization = OrganizationFactory()
    actor, approver = activate_synthetic_board(organization)
    target = resolve_organization_target(organization_id=organization.id)
    assert target is not None
    grantor = AccountFactory()
    now = timezone.now()
    parent = grant_capability_direct(
        actor=actor,
        approver=approver,
        recipient=grantor,
        capability_code="events.view_basic",
        target=target,
        effective_from=now,
        expires_at=now + timedelta(hours=2),
        reason="Create a complete delegated parent.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    first_recipient = AccountFactory()
    second_recipient = AccountFactory()
    _activate()
    post_activation_time = timezone.now()

    target_first = _delegated_child(
        parent=parent,
        recipient=first_recipient,
        effective_from=post_activation_time,
        expires_at=post_activation_time + timedelta(hours=1),
    )
    with transaction.atomic():
        CapabilityGrant.objects.bulk_create([target_first])
        issuances = AuthorityIssuance.objects.bulk_create(
            [
                AuthorityIssuance(
                    capability_grant=target_first,
                    policy_version=POLICY_VERSION,
                    evaluated_at=post_activation_time,
                )
            ]
        )
    assert len(issuances) == 1

    issuance_first = _delegated_child(
        parent=parent,
        recipient=second_recipient,
        effective_from=post_activation_time + timedelta(seconds=1),
        expires_at=post_activation_time + timedelta(hours=1),
    )
    with transaction.atomic():
        raw_ordinal = _raw_issuance_for_grant(
            grant_id=issuance_first.id,
            evaluated_at=post_activation_time + timedelta(seconds=1),
        )
        CapabilityGrant.objects.bulk_create([issuance_first])

    assert AuthorityIssuance.objects.filter(
        ordinal=raw_ordinal,
        capability_grant=issuance_first,
    ).exists()
    assert AuthorityControl.objects.filter(issuance_id=raw_ordinal).count() == 0


def test_active_era_allows_bounded_application_clock_skew() -> None:
    organization = OrganizationFactory()
    actor, approver = activate_synthetic_board(organization)
    target = resolve_organization_target(organization_id=organization.id)
    assert target is not None
    now = timezone.now()
    parent = grant_capability_direct(
        actor=actor,
        approver=approver,
        recipient=AccountFactory(),
        capability_code="events.view_basic",
        target=target,
        effective_from=now,
        expires_at=now + timedelta(hours=2),
        reason="Create a complete parent for the clock-skew boundary.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    administrator = _administrator()
    with transaction.atomic():
        _insert_raw_activation_with_audit(
            actor_id=administrator.id,
            correlation_id=uuid4(),
        )
    child = _delegated_child(
        parent=parent,
        recipient=AccountFactory(),
        effective_from=timezone.now(),
        expires_at=timezone.now() + timedelta(hours=1),
    )
    future_evaluation = timezone.now() + timedelta(minutes=4)

    with transaction.atomic():
        CapabilityGrant.objects.bulk_create([child])
        _raw_issuance_for_grant(
            grant_id=child.id,
            evaluated_at=future_evaluation,
        )
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SET CONSTRAINTS authorization_authority_issuance_complete
                IMMEDIATE
                """
            )
        transaction.set_rollback(True)

    assert not CapabilityGrant.objects.filter(pk=child.pk).exists()


def test_active_era_rejects_stale_post_activation_issuance() -> None:
    organization = OrganizationFactory()
    actor, approver = activate_synthetic_board(organization)
    marker = _activate()
    stale_activation = marker.activated_at - timedelta(minutes=10)
    stale_evaluation = marker.activated_at - timedelta(minutes=6)
    child = CapabilityGrant(
        organization=organization,
        principal=AccountFactory(),
        capability_code="events.view_basic",
        effective_from=stale_evaluation,
        expires_at=marker.activated_at + timedelta(hours=1),
        granted_by=actor,
        approved_by=approver,
        reason="Reject an issuance written with a stale application clock.",
    )

    with (  # noqa: PT012
        pytest.raises(DatabaseError, match="within the active era"),
        transaction.atomic(),
    ):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE public.authorization_authorityprovenanceactivation
                DISABLE TRIGGER authorization_provenance_activation_guard
                """
            )
            cursor.execute(
                """
                UPDATE public.authorization_authorityprovenanceactivation
                   SET activated_at = %s
                 WHERE singleton IS TRUE
                """,
                [stale_activation],
            )
            cursor.execute(
                """
                ALTER TABLE public.authorization_authorityprovenanceactivation
                ENABLE TRIGGER authorization_provenance_activation_guard
                """
            )
        CapabilityGrant.objects.bulk_create([child])
        _raw_issuance_for_grant(
            grant_id=child.id,
            evaluated_at=stale_evaluation,
        )
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SET CONSTRAINTS authorization_authority_issuance_complete
                IMMEDIATE
                """
            )

    assert not CapabilityGrant.objects.filter(pk=child.pk).exists()
    marker.refresh_from_db()
    assert marker.activated_at != stale_activation


def test_activation_allows_unreachable_closed_review_debt() -> None:
    now = timezone.now()
    closed = CapabilityGrantFactory(
        effective_from=now - timedelta(days=2),
        expires_at=now - timedelta(days=1),
    )

    marker = _activate()

    assert marker.pk is True
    assert not AuthorityIssuance.objects.filter(capability_grant=closed).exists()


def test_deferred_completeness_rejects_missing_delegated_parent_issuance() -> None:
    now = timezone.now()
    parent = CapabilityGrantFactory(
        effective_from=now - timedelta(days=4),
        expires_at=now - timedelta(days=2),
    )
    child = _delegated_child(
        parent=parent,
        recipient=AccountFactory(),
        effective_from=now - timedelta(days=3),
        expires_at=now - timedelta(days=2, hours=12),
    )
    _activate()

    with pytest.raises(DatabaseError):
        _raw_insert_delegated_grant_with_issuance(
            grant=child,
            evaluated_at=now - timedelta(days=3),
        )

    assert not CapabilityGrant.objects.filter(pk=child.pk).exists()
    assert not AuthorityIssuance.objects.filter(capability_grant_id=child.pk).exists()


def test_deferred_completeness_rejects_assignment_to_unproven_old_bundle() -> None:
    organization = OrganizationFactory()
    actor, approver = activate_synthetic_board(organization)
    target = resolve_organization_target(organization_id=organization.id)
    assert target is not None
    role_code = f"recursive-bundle-{uuid4().hex[:12]}"
    old_bundle = RoleBundle.objects.create(
        organization=organization,
        code=role_code,
        name="Unproven old bundle",
        version=1,
        capability_codes=["events.view_basic"],
        created_by=actor,
        approved_by=approver,
        reason="Preserve one unused legacy bundle as review debt.",
    )
    latest_bundle = create_role_bundle_version(
        actor=actor,
        approver=approver,
        target=target,
        code=role_code,
        name="Proven current bundle",
        capability_codes=("events.view_basic",),
        reason="Replace the legacy bundle with exact provenance.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert latest_bundle.version == 2
    recipient = AccountFactory()
    evaluated_at = timezone.now()
    assignment = RoleAssignment(
        organization=organization,
        principal=recipient,
        role_bundle=old_bundle,
        effective_from=evaluated_at,
        granted_by=actor,
        approved_by=approver,
        reason="Attempt to reuse an unproven historical definition.",
    )
    actor_source = AuthorityIssuance.objects.get(
        role_assignment__principal=actor,
        role_assignment__role_bundle__code="executive-board",
    )
    approver_source = AuthorityIssuance.objects.get(
        role_assignment__principal=approver,
        role_assignment__role_bundle__code="executive-board",
    )
    _activate()

    with pytest.raises(DatabaseError):
        _raw_insert_assignment_with_controls(
            assignment=assignment,
            evaluated_at=evaluated_at,
            actor=actor,
            approver=approver,
            actor_source=actor_source,
            approver_source=approver_source,
        )

    assert not RoleAssignment.objects.filter(pk=assignment.pk).exists()
    assert not AuthorityIssuance.objects.filter(
        role_assignment_id=assignment.pk
    ).exists()


def test_closed_grant_cannot_hide_a_revoked_control_source() -> None:
    organization = OrganizationFactory()
    (
        board_actor,
        _,
        control_actor,
        control_approver,
        actor_source_grant,
        approver_source_grant,
    ) = _create_direct_control_sources(
        organization=organization,
        capability_code="authorization.grant_direct",
    )
    actor_source = AuthorityIssuance.objects.get(capability_grant=actor_source_grant)
    approver_source = AuthorityIssuance.objects.get(
        capability_grant=approver_source_grant
    )
    administrator = _administrator()
    with transaction.atomic():
        _insert_raw_activation_with_audit(
            actor_id=administrator.id,
            correlation_id=uuid4(),
        )

    evaluated_at = timezone.now()
    target_grant = CapabilityGrant(
        organization=organization,
        principal=AccountFactory(),
        capability_code="events.view_basic",
        effective_from=evaluated_at,
        expires_at=evaluated_at + timedelta(hours=1),
        revoked_at=evaluated_at + timedelta(minutes=1),
        revoked_by=board_actor,
        revocation_reason="Close the fabricated target.",
        granted_by=control_actor,
        approved_by=control_approver,
        reason="A closed target must still prove recursive exact lineage.",
    )

    with pytest.raises(DatabaseError), transaction.atomic():  # noqa: PT012
        CapabilityGrant.objects.bulk_create([target_grant])
        target_issuance = AuthorityIssuance.objects.bulk_create(
            [
                AuthorityIssuance(
                    capability_grant=target_grant,
                    policy_version=POLICY_VERSION,
                    evaluated_at=evaluated_at,
                )
            ]
        )[0]
        AuthorityControl.objects.bulk_create(
            [
                AuthorityControl(
                    issuance=target_issuance,
                    role=AuthorityControl.Role.ACTOR,
                    principal=control_actor,
                    basis=AuthorityControl.Basis.PERSISTENT_AUTHORITY,
                    source_issuance=actor_source,
                    policy_version=POLICY_VERSION,
                    evaluated_at=evaluated_at,
                ),
                AuthorityControl(
                    issuance=target_issuance,
                    role=AuthorityControl.Role.APPROVER,
                    principal=control_approver,
                    basis=AuthorityControl.Basis.PERSISTENT_AUTHORITY,
                    source_issuance=approver_source,
                    policy_version=POLICY_VERSION,
                    evaluated_at=evaluated_at,
                ),
            ]
        )
        CapabilityGrant.objects.filter(pk=actor_source_grant.pk).update(
            revoked_at=evaluated_at,
            revoked_by=board_actor,
            revocation_reason="Invalidate the pinned actor source before commit.",
        )

    assert not CapabilityGrant.objects.filter(pk=target_grant.pk).exists()
    actor_source_grant.refresh_from_db()
    assert actor_source_grant.revoked_at is None


def test_closed_assignment_cannot_hide_a_revoked_control_source() -> None:
    organization = OrganizationFactory()
    (
        board_actor,
        board_approver,
        control_actor,
        control_approver,
        actor_source_grant,
        approver_source_grant,
    ) = _create_direct_control_sources(
        organization=organization,
        capability_code="authorization.manage_roles",
    )
    target = resolve_organization_target(organization_id=organization.id)
    assert target is not None
    role_bundle = create_role_bundle_version(
        actor=board_actor,
        approver=board_approver,
        target=target,
        code=f"closed-lineage-{uuid4().hex[:12]}",
        name="Closed lineage",
        capability_codes=("events.view_basic",),
        reason="Create a proven bundle for the closed assignment regression.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    actor_source = AuthorityIssuance.objects.get(capability_grant=actor_source_grant)
    approver_source = AuthorityIssuance.objects.get(
        capability_grant=approver_source_grant
    )
    administrator = _administrator()
    with transaction.atomic():
        _insert_raw_activation_with_audit(
            actor_id=administrator.id,
            correlation_id=uuid4(),
        )

    evaluated_at = timezone.now()
    assignment = RoleAssignment(
        organization=organization,
        principal=AccountFactory(),
        role_bundle=role_bundle,
        effective_from=evaluated_at,
        expires_at=evaluated_at + timedelta(hours=1),
        revoked_at=evaluated_at + timedelta(minutes=1),
        revoked_by=board_actor,
        revocation_reason="Close the fabricated target.",
        granted_by=control_actor,
        approved_by=control_approver,
        reason="A closed assignment must still prove recursive exact lineage.",
    )

    with pytest.raises(DatabaseError), transaction.atomic():  # noqa: PT012
        RoleAssignment.objects.bulk_create([assignment])
        target_issuance = AuthorityIssuance.objects.bulk_create(
            [
                AuthorityIssuance(
                    role_assignment=assignment,
                    policy_version=POLICY_VERSION,
                    evaluated_at=evaluated_at,
                )
            ]
        )[0]
        AuthorityControl.objects.bulk_create(
            [
                AuthorityControl(
                    issuance=target_issuance,
                    role=AuthorityControl.Role.ACTOR,
                    principal=control_actor,
                    basis=AuthorityControl.Basis.PERSISTENT_AUTHORITY,
                    source_issuance=actor_source,
                    policy_version=POLICY_VERSION,
                    evaluated_at=evaluated_at,
                ),
                AuthorityControl(
                    issuance=target_issuance,
                    role=AuthorityControl.Role.APPROVER,
                    principal=control_approver,
                    basis=AuthorityControl.Basis.PERSISTENT_AUTHORITY,
                    source_issuance=approver_source,
                    policy_version=POLICY_VERSION,
                    evaluated_at=evaluated_at,
                ),
            ]
        )
        CapabilityGrant.objects.filter(pk=actor_source_grant.pk).update(
            revoked_at=evaluated_at,
            revoked_by=board_actor,
            revocation_reason="Invalidate the pinned actor source before commit.",
        )

    assert not RoleAssignment.objects.filter(pk=assignment.pk).exists()
    actor_source_grant.refresh_from_db()
    assert actor_source_grant.revoked_at is None


@pytest.mark.parametrize(
    ("isolation_sql", "fixes_snapshot"),
    [
        ("SET TRANSACTION ISOLATION LEVEL READ COMMITTED", False),
        ("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ", True),
    ],
)
def test_preopened_writer_waits_for_activation_then_is_rejected(  # noqa: PLR0915
    isolation_sql: str,
    fixes_snapshot: bool,
) -> None:
    organization = OrganizationFactory()
    principal = AccountFactory()
    actor = AccountFactory()
    administrator = _administrator()
    correlation_id = uuid4()
    grant_id = uuid4()
    transaction_open = Event()
    start_writer_insert = Event()
    activation_exclusive = Event()
    release_activation = Event()
    writer_pids: list[int] = []
    activation_pids: list[int] = []

    def stale_writer() -> tuple[str, str | None]:
        close_old_connections()
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(isolation_sql)
                    cursor.execute("SELECT pg_backend_pid()")
                    writer_pids.append(int(cursor.fetchone()[0]))
                    if fixes_snapshot:
                        cursor.execute(
                            "SELECT generation "
                            "FROM authorization_provenanceactivationlatch"
                        )
                        assert cursor.fetchone() == (0,)
                    else:
                        cursor.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                        cursor.execute("SELECT transaction_timestamp()")
                        assert cursor.fetchone() is not None
                transaction_open.set()
                assert start_writer_insert.wait(timeout=10)
                CapabilityGrant.objects.bulk_create(
                    [
                        CapabilityGrant(
                            id=grant_id,
                            organization_id=organization.id,
                            principal_id=principal.id,
                            capability_code="events.view_basic",
                            effective_from=timezone.now(),
                            granted_by_id=actor.id,
                            reason="Reject a transaction opened before cutover.",
                        )
                    ]
                )
        except DatabaseError as error:
            return "rejected", _database_error_sqlstate(error)
        else:
            return "committed", None
        finally:
            transaction_open.set()
            close_old_connections()

    def raw_activation() -> tuple[str, str | None]:
        close_old_connections()
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    activation_pids.append(int(cursor.fetchone()[0]))
                    cursor.execute(
                        "SELECT pg_advisory_xact_lock(%s)",
                        [AUTHORITY_PROVENANCE_ACTIVATION_LOCK_KEY],
                    )
                activation_exclusive.set()
                assert release_activation.wait(timeout=10)
                _insert_raw_activation_with_audit(
                    actor_id=administrator.id,
                    correlation_id=correlation_id,
                )
        except DatabaseError as error:
            return "rejected", _database_error_sqlstate(error)
        else:
            return "committed", None
        finally:
            activation_exclusive.set()
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        writer_future = executor.submit(stale_writer)
        assert transaction_open.wait(timeout=10)
        assert writer_pids
        activation_future = executor.submit(raw_activation)
        assert activation_exclusive.wait(timeout=10)
        assert activation_pids
        start_writer_insert.set()
        try:
            _wait_for_advisory_block(
                waiting_pid=writer_pids[0],
                blocking_pid=activation_pids[0],
            )
        finally:
            release_activation.set()
        activation_outcome = activation_future.result(timeout=10)
        writer_outcome = writer_future.result(timeout=10)

    assert activation_outcome == ("committed", None)
    assert writer_outcome == ("rejected", "40001")
    assert not CapabilityGrant.objects.filter(pk=grant_id).exists()
    assert AuthorityProvenanceActivation.objects.filter(singleton=True).exists()
    assert AuthorityProvenanceActivationLatch.objects.get().generation == 1


def test_dormant_writer_drains_before_raw_activation_and_blocks_cutover(  # noqa: PLR0915
) -> None:
    organization = OrganizationFactory()
    principal = AccountFactory()
    grant_actor = AccountFactory()
    administrator = _administrator()
    correlation_id = uuid4()
    grant_id = uuid4()
    writer_inserted = Event()
    release_writer = Event()
    activation_attempting = Event()
    writer_pids: list[int] = []
    activation_pids: list[int] = []

    def dormant_writer() -> tuple[str, str | None]:
        close_old_connections()
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    writer_pids.append(int(cursor.fetchone()[0]))
                CapabilityGrant.objects.bulk_create(
                    [
                        CapabilityGrant(
                            id=grant_id,
                            organization_id=organization.id,
                            principal_id=principal.id,
                            capability_code="events.view_basic",
                            effective_from=timezone.now(),
                            granted_by_id=grant_actor.id,
                            reason="Commit dormant compatibility debt.",
                        )
                    ]
                )
                writer_inserted.set()
                assert release_writer.wait(timeout=10)
        except DatabaseError as error:
            return "rejected", _database_error_sqlstate(error)
        else:
            return "committed", None
        finally:
            writer_inserted.set()
            close_old_connections()

    def raw_activation() -> tuple[str, str | None]:
        close_old_connections()
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    activation_pids.append(int(cursor.fetchone()[0]))
                activation_attempting.set()
                _insert_raw_activation_with_audit(
                    actor_id=administrator.id,
                    correlation_id=correlation_id,
                )
        except DatabaseError as error:
            return "rejected", _database_error_sqlstate(error)
        else:
            return "committed", None
        finally:
            activation_attempting.set()
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        writer_future = executor.submit(dormant_writer)
        assert writer_inserted.wait(timeout=10)
        assert writer_pids
        activation_future = executor.submit(raw_activation)
        assert activation_attempting.wait(timeout=10)
        assert activation_pids
        try:
            _wait_for_advisory_block(
                waiting_pid=activation_pids[0],
                blocking_pid=writer_pids[0],
            )
        finally:
            release_writer.set()
        writer_outcome = writer_future.result(timeout=10)
        activation_outcome = activation_future.result(timeout=10)

    assert writer_outcome == ("committed", None)
    assert activation_outcome == ("rejected", "23514")
    assert CapabilityGrant.objects.filter(pk=grant_id).exists()
    assert not AuthorityProvenanceActivation.objects.exists()
    assert AuthorityProvenanceActivationLatch.objects.get().generation == 0
    assert not AuditEvent.objects.filter(
        operation="authorization.authority_provenance.activate",
        correlation_id=correlation_id,
    ).exists()
