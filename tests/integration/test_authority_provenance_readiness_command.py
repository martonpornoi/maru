"""Privacy and deployment-readiness evidence for ADR 0044 provenance."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from io import StringIO
from itertools import pairwise
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.test import override_settings
from django.utils import timezone

from maru.audit.services import seal_pending_audit_events, verify_audit_integrity
from maru.authorization import provenance_readiness
from maru.authorization.activation import (
    AuthorityProvenanceActivationBlockedError,
    activate_authority_provenance,
)
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.issuance import (
    create_delegated_grant_issuance,
    create_persistent_dual_control_issuance,
)
from maru.authorization.models import (
    AuthorityControl,
    AuthorityIssuance,
    AuthorityProvenanceActivation,
    CapabilityGrant,
    RoleAssignment,
    RoleBundle,
)
from maru.authorization.provenance_readiness import BLOCKER_KEYS, REVIEW_KEYS
from tests.factories import AccountFactory, EventEditionFactory, OrganizationFactory
from tests.support.authority import activate_synthetic_board

if TYPE_CHECKING:
    from maru.identity.models import Account

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("proves_safe_runtime_database_role"),
]


def _run_readiness(*, no_fail: bool = True) -> tuple[str, dict[str, Any]]:
    output = StringIO()
    arguments = ("--no-fail",) if no_fail else ()
    call_command(
        "check_authority_provenance_readiness",
        *arguments,
        stdout=output,
    )
    rendered = output.getvalue()
    return rendered, json.loads(rendered)


def _empty_report(*, activated: bool = False) -> dict[str, object]:
    gate_state = "resolved" if activated else "unresolved"
    return {
        "status": "ready",
        "activation_status": "blocked" if activated else "ready",
        "production_status": "ready" if activated else "blocked",
        "blocker_counts": dict.fromkeys(BLOCKER_KEYS, 0),
        "blocker_total": 0,
        "review_counts": dict.fromkeys(REVIEW_KEYS, 0),
        "known_production_gates": {
            "postgresql_server_major": "resolved",
            "runtime_database_role": "resolved",
            "activation_marker": gate_state,
            "exact_lineage_policy_cutover": gate_state,
            "database_completeness_guards": gate_state,
            "provenance_write_downgrade_fence": gate_state,
        },
    }


def _board() -> tuple[object, Account, Account]:
    organization = OrganizationFactory()
    actor, approver = activate_synthetic_board(organization)
    return organization, actor, approver


def _board_source(controller: Account) -> AuthorityIssuance:
    return AuthorityIssuance.objects.get(
        role_assignment__principal=controller,
        role_assignment__role_bundle__code="executive-board",
    )


def _activate_provenance(
    *, actor: Account | None = None
) -> AuthorityProvenanceActivation:
    administrator = actor or AccountFactory(is_staff=True, is_superuser=True)
    correlation_id = uuid4()
    with override_settings(REQUIRE_EXACT_AUTHORITY_PROVENANCE=True):
        result = activate_authority_provenance(
            actor=administrator,
            reason="Private synthetic cutover evidence.",
            correlation_id=correlation_id,
            acknowledge_processes_stopped=True,
            source_channel="integration-test",
        )
    assert result.activated
    assert result.correlation_id == correlation_id
    return AuthorityProvenanceActivation.objects.get(singleton=True)


def _assert_catalog_tamper_blocked(
    rendered: str,
    report: dict[str, Any],
    *,
    downgrade_fence_resolved: bool = False,
) -> None:
    assert report["status"] == "ready"
    assert report["activation_status"] == "blocked"
    assert report["production_status"] == "blocked"
    assert report["known_production_gates"] == {
        "postgresql_server_major": "resolved",
        "runtime_database_role": "resolved",
        "activation_marker": "resolved",
        "exact_lineage_policy_cutover": "resolved",
        "database_completeness_guards": "unresolved",
        "provenance_write_downgrade_fence": (
            "resolved" if downgrade_fence_resolved else "unresolved"
        ),
    }
    assert "trigger" not in rendered.lower()
    assert "function" not in rendered.lower()


_FOUNDATIONAL_TRIGGER_CONTRACTS = (
    (
        "authorization_capabilitygrant",
        "authorization_capability_grant_guard",
    ),
    (
        "authorization_capabilitygrant",
        "authorization_capability_grant_no_delete",
    ),
    (
        "authorization_roleassignment",
        "authorization_role_assignment_guard",
    ),
    (
        "authorization_roleassignment",
        "authorization_role_assignment_no_delete",
    ),
    (
        "authorization_rolebundle",
        "authorization_role_bundle_catalog_guard",
    ),
    (
        "authorization_rolebundle",
        "authorization_role_bundle_immutable",
    ),
    (
        "authorization_scopedresourcebinding",
        "authorization_scoped_resource_binding_guard",
    ),
    (
        "authorization_scopedresourcebinding",
        "authorization_scoped_resource_binding_immutable",
    ),
    (
        "authorization_authorityissuance",
        "authorization_authority_issuance_insert_guard",
    ),
    (
        "authorization_authorityissuance",
        "authorization_authority_issuance_immutable",
    ),
    (
        "authorization_authoritycontrol",
        "authorization_authority_control_insert_guard",
    ),
    (
        "authorization_authoritycontrol",
        "authorization_authority_control_immutable",
    ),
    ("audit_auditevent", "audit_event_append_only"),
    (
        "audit_auditevent",
        "authorization_activation_audit_reserved_guard",
    ),
)

_FOUNDATIONAL_FUNCTION_CONTRACTS = (
    "maru_validate_capability_grant",
    "maru_prevent_authority_record_delete",
    "maru_validate_role_assignment",
    "maru_validate_role_bundle_catalog",
    "maru_prevent_role_bundle_mutation",
    "maru_validate_scoped_resource_binding",
    "maru_prevent_scoped_resource_binding_mutation",
    "maru_validate_authority_issuance_insert",
    "maru_prevent_authority_issuance_mutation",
    "maru_validate_authority_control_insert",
    "maru_prevent_authority_control_mutation",
    "maru_guard_audit_event",
    "maru_guard_authority_provenance_activation_audit",
    "maru_lock_authority_provenance_writer",
)


def test_clean_executive_board_graph_is_data_ready_but_activation_blocked() -> None:
    _organization, _actor, _approver = _board()

    first_rendered, first = _run_readiness()
    second_rendered, second = _run_readiness()

    assert first == _empty_report()
    assert second == first
    assert second_rendered == first_rendered
    assert "@" not in first_rendered
    assert "principal" not in first_rendered
    assert "capability_code" not in first_rendered


def test_unsupported_postgresql_major_blocks_activation_without_disclosure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _organization, _actor, _approver = _board()
    catalog = provenance_readiness._inspect_cutover_catalog()
    monkeypatch.setattr(
        provenance_readiness,
        "_inspect_cutover_catalog",
        lambda: replace(catalog, server_version_supported=False),
    )

    rendered, report = _run_readiness()

    assert report["status"] == "ready"
    assert report["activation_status"] == "blocked"
    assert report["production_status"] == "blocked"
    assert report["known_production_gates"] == {
        "postgresql_server_major": "unresolved",
        "runtime_database_role": "resolved",
        "activation_marker": "unresolved",
        "exact_lineage_policy_cutover": "unresolved",
        "database_completeness_guards": "unresolved",
        "provenance_write_downgrade_fence": "unresolved",
    }
    assert "version" not in rendered.lower()
    assert "17" not in rendered
    with pytest.raises(AuthorityProvenanceActivationBlockedError):
        _activate_provenance()
    assert not AuthorityProvenanceActivation.objects.exists()


@override_settings(RUNTIME_DATABASE_ROLE="synthetic-private-runtime-role")
def test_unsafe_runtime_database_role_blocks_irreversible_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _organization, _actor, _approver = _board()
    monkeypatch.setattr(
        provenance_readiness,
        "_configured_runtime_database_role_is_safe",
        lambda: False,
    )

    rendered, report = _run_readiness()
    expected = _empty_report()
    expected["activation_status"] = "blocked"
    expected["known_production_gates"]["runtime_database_role"] = "unresolved"

    assert report == expected
    assert "synthetic-private-runtime-role" not in rendered
    with pytest.raises(AuthorityProvenanceActivationBlockedError):
        _activate_provenance()
    assert not AuthorityProvenanceActivation.objects.exists()


@pytest.mark.parametrize(
    ("search_path_sql", "private_schema"),
    [
        (
            "SET LOCAL search_path TO information_schema, public",
            "information_schema",
        ),
        ("SET LOCAL search_path TO public, pg_catalog", "pg_catalog"),
    ],
)
def test_unsafe_effective_schema_is_blocked_before_authority_graph_read(
    monkeypatch: pytest.MonkeyPatch,
    search_path_sql: str,
    private_schema: str,
) -> None:
    def unexpected_graph_read(*_args: object, **_kwargs: object) -> None:
        pytest.fail("The authority graph must not be read under another schema.")

    monkeypatch.setattr(provenance_readiness, "_AuthorityGraph", unexpected_graph_read)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(search_path_sql)
        report = provenance_readiness.build_authority_provenance_readiness_report()
        expected = _empty_report()
        expected["status"] = "blocked"
        expected["activation_status"] = "blocked"
        expected["known_production_gates"]["postgresql_server_major"] = "unresolved"
        expected["known_production_gates"]["runtime_database_role"] = "unresolved"
        assert report == expected

        output = StringIO()
        with pytest.raises(CommandError, match="provenance blockers detected") as error:
            call_command(
                "check_authority_provenance_readiness",
                stdout=output,
            )
        rendered = output.getvalue()
        assert json.loads(rendered) == expected
        assert private_schema not in rendered
        assert "search_path" not in rendered
        assert private_schema not in str(error.value)
        assert "search_path" not in str(error.value)


def test_temporary_schema_shadow_is_blocked_before_authority_graph_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_graph_read(*_args: object, **_kwargs: object) -> None:
        pytest.fail("The authority graph must not be read under a temporary shadow.")

    isolated_connection = connection.copy(alias="provenance_pg_temp_shadow_test")
    try:
        with isolated_connection.cursor() as cursor:
            cursor.execute(
                "CREATE TEMPORARY TABLE django_migrations "
                "(app text NOT NULL, name text NOT NULL)"
            )
            cursor.execute("SET search_path TO public")
            cursor.execute("SELECT pg_catalog.current_schemas(TRUE)")
            effective_schemas = tuple(cursor.fetchone()[0])
        public_position = effective_schemas.index("public")
        assert any(
            schema.startswith("pg_temp_")
            for schema in effective_schemas[:public_position]
        )

        monkeypatch.setattr(provenance_readiness, "connection", isolated_connection)
        monkeypatch.setattr(
            provenance_readiness,
            "_AuthorityGraph",
            unexpected_graph_read,
        )
        report = provenance_readiness.build_authority_provenance_readiness_report()
    finally:
        isolated_connection.close()

    expected = _empty_report()
    expected["status"] = "blocked"
    expected["activation_status"] = "blocked"
    expected["known_production_gates"]["postgresql_server_major"] = "unresolved"
    expected["known_production_gates"]["runtime_database_role"] = "unresolved"
    assert report == expected


def test_activation_pins_supported_schema_over_unsafe_session_path() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    with connection.cursor() as cursor:
        cursor.execute("SET search_path TO information_schema, public")
    try:
        marker = _activate_provenance(actor=administrator)
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SET search_path TO public")

    assert marker.activated_by == administrator
    assert _run_readiness()[1] == _empty_report(activated=True)


def test_cutover_status_rechecks_marker_and_guard_catalog_without_cache() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)

    before_rendered, before = _run_readiness()
    assert before == _empty_report()
    failing_output = StringIO()
    with pytest.raises(
        CommandError,
        match="production gates are unresolved",
    ):
        call_command(
            "check_authority_provenance_readiness",
            stdout=failing_output,
        )
    assert json.loads(failing_output.getvalue()) == before

    marker = _activate_provenance(actor=administrator)
    active_rendered, active = _run_readiness()
    repeated_rendered, repeated = _run_readiness()

    assert active == _empty_report(activated=True)
    assert repeated == active
    assert repeated_rendered == active_rendered
    assert active_rendered != before_rendered
    assert administrator.email not in active_rendered
    assert str(administrator.id) not in active_rendered
    assert marker.reason not in active_rendered
    assert str(marker.correlation_id) not in active_rendered

    successful_output = StringIO()
    call_command(
        "check_authority_provenance_readiness",
        stdout=successful_output,
    )
    assert json.loads(successful_output.getvalue()) == active

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE authorization_capabilitygrant DISABLE TRIGGER "
                "authorization_capability_grant_provenance_complete"
            )
        disabled_rendered, disabled = _run_readiness()
        assert disabled["status"] == "ready"
        assert disabled["activation_status"] == "blocked"
        assert disabled["production_status"] == "blocked"
        assert disabled["known_production_gates"] == {
            "postgresql_server_major": "resolved",
            "runtime_database_role": "resolved",
            "activation_marker": "resolved",
            "exact_lineage_policy_cutover": "resolved",
            "database_completeness_guards": "unresolved",
            "provenance_write_downgrade_fence": "resolved",
        }
        assert "capability_grant" not in disabled_rendered
        disabled_output = StringIO()
        with pytest.raises(
            CommandError,
            match="production gates are unresolved",
        ):
            call_command(
                "check_authority_provenance_readiness",
                stdout=disabled_output,
            )
        assert json.loads(disabled_output.getvalue()) == disabled
        transaction.set_rollback(True)

    restored_rendered, restored = _run_readiness()
    assert restored == active
    assert restored_rendered == active_rendered


def test_lightweight_runtime_contract_probe_rejects_tampered_guard_without_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _activate_provenance()

    def unexpected_graph_load(*_args: object, **_kwargs: object) -> None:
        pytest.fail("The lightweight runtime contract must not load authority data.")

    monkeypatch.setattr(
        provenance_readiness,
        "_AuthorityGraph",
        unexpected_graph_load,
    )
    assert provenance_readiness.authority_provenance_runtime_contract_is_ready()

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE public.authorization_capabilitygrant
                DISABLE TRIGGER authorization_capability_grant_guard
                """
            )
        assert not provenance_readiness.authority_provenance_runtime_contract_is_ready()
        transaction.set_rollback(True)

    assert provenance_readiness.authority_provenance_runtime_contract_is_ready()


@pytest.mark.parametrize("error_type", [KeyError, TypeError, ValueError])
def test_lightweight_runtime_contract_probe_fails_closed_on_malformed_shape(
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
) -> None:
    def malformed_cutover_state() -> None:
        raise error_type("malformed restored catalog shape")

    monkeypatch.setattr(
        provenance_readiness,
        "_inspect_cutover_state",
        malformed_cutover_state,
    )

    assert not provenance_readiness.authority_provenance_runtime_contract_is_ready()


def test_sealed_activation_audit_remains_exact_production_ready_evidence() -> None:
    _activate_provenance()
    before_rendered, before = _run_readiness()
    assert before == _empty_report(activated=True)

    batch = seal_pending_audit_events()

    assert batch is not None
    assert verify_audit_integrity()
    after_rendered, after = _run_readiness()
    assert after == before
    assert after_rendered == before_rendered


@pytest.mark.parametrize(
    ("table", "trigger_name", "mutation_sql"),
    [
        (
            "public.authorization_authorityprovenanceactivation",
            "authorization_provenance_activation_guard",
            """
            UPDATE public.authorization_authorityprovenanceactivation
               SET reason = '   '
            """,
        ),
        (
            "public.audit_auditevent",
            "audit_event_append_only",
            """
            UPDATE public.audit_auditevent
               SET source_channel = '   '
             WHERE operation = 'authorization.authority_provenance.activate'
            """,
        ),
        (
            "public.audit_auditevent",
            "audit_event_append_only",
            """
            UPDATE public.audit_auditevent
               SET schema_version = 2
             WHERE operation = 'authorization.authority_provenance.activate'
            """,
        ),
        (
            "public.audit_auditevent",
            "audit_event_append_only",
            """
            UPDATE public.audit_auditevent
               SET causation_id = '00000000-0000-0000-0000-000000000001'
             WHERE operation = 'authorization.authority_provenance.activate'
            """,
        ),
        (
            "public.audit_auditevent",
            "audit_event_append_only",
            """
            UPDATE public.audit_auditevent
               SET request_id = '00000000-0000-0000-0000-000000000001'
             WHERE operation = 'authorization.authority_provenance.activate'
            """,
        ),
        (
            "public.audit_auditevent",
            "audit_event_append_only",
            """
            UPDATE public.audit_auditevent
               SET idempotency_key_hash = repeat('0', 64)
             WHERE operation = 'authorization.authority_provenance.activate'
            """,
        ),
    ],
)
def test_runtime_rejects_malformed_durable_activation_evidence(
    table: str,
    trigger_name: str,
    mutation_sql: str,
) -> None:
    _activate_provenance()

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {table} DISABLE TRIGGER {trigger_name}")
            cursor.execute(mutation_sql)
            cursor.execute(f"ALTER TABLE {table} ENABLE TRIGGER {trigger_name}")
        rendered, report = _run_readiness()
        assert report["status"] == "ready"
        assert report["activation_status"] == "blocked"
        assert report["production_status"] == "blocked"
        assert report["known_production_gates"] == {
            "postgresql_server_major": "resolved",
            "runtime_database_role": "resolved",
            "activation_marker": "unresolved",
            "exact_lineage_policy_cutover": "unresolved",
            "database_completeness_guards": "unresolved",
            "provenance_write_downgrade_fence": "unresolved",
        }
        assert "source_channel" not in rendered.lower()
        assert "schema_version" not in rendered.lower()
        transaction.set_rollback(True)

    assert _run_readiness()[1] == _empty_report(activated=True)


def test_disabled_marker_truncate_fence_fails_closed_without_catalog_names() -> None:
    _activate_provenance()
    active_rendered, active = _run_readiness()
    assert active == _empty_report(activated=True)

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE authorization_authorityprovenanceactivation "
                "DISABLE TRIGGER authorization_provenance_activation_no_truncate"
            )
        unfenced_rendered, unfenced = _run_readiness()
        assert unfenced["status"] == "ready"
        assert unfenced["activation_status"] == "blocked"
        assert unfenced["production_status"] == "blocked"
        assert unfenced["known_production_gates"] == {
            "postgresql_server_major": "resolved",
            "runtime_database_role": "resolved",
            "activation_marker": "resolved",
            "exact_lineage_policy_cutover": "resolved",
            "database_completeness_guards": "unresolved",
            "provenance_write_downgrade_fence": "unresolved",
        }
        assert "truncate" not in unfenced_rendered.lower()
        unfenced_output = StringIO()
        with pytest.raises(
            CommandError,
            match="production gates are unresolved",
        ):
            call_command(
                "check_authority_provenance_readiness",
                stdout=unfenced_output,
            )
        assert json.loads(unfenced_output.getvalue()) == unfenced
        transaction.set_rollback(True)

    final_rendered, final = _run_readiness()
    assert final == active
    assert final_rendered == active_rendered


def test_weakened_activation_audit_index_fails_closed_without_definition() -> None:
    _activate_provenance()
    active_rendered, active = _run_readiness()
    assert active == _empty_report(activated=True)

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "DROP INDEX authorization_provenance_activation_audit_unique"
            )
            cursor.execute(
                "CREATE UNIQUE INDEX "
                "authorization_provenance_activation_audit_unique "
                "ON audit_auditevent (correlation_id, operation) "
                "WHERE operation = "
                "'authorization.authority_provenance.activate'"
            )
        weakened_rendered, weakened = _run_readiness()
        assert weakened["status"] == "ready"
        assert weakened["activation_status"] == "blocked"
        assert weakened["production_status"] == "blocked"
        assert weakened["known_production_gates"] == {
            "postgresql_server_major": "resolved",
            "runtime_database_role": "resolved",
            "activation_marker": "resolved",
            "exact_lineage_policy_cutover": "resolved",
            "database_completeness_guards": "unresolved",
            "provenance_write_downgrade_fence": "unresolved",
        }
        assert "index" not in weakened_rendered.lower()
        assert "correlation" not in weakened_rendered.lower()
        transaction.set_rollback(True)

    final_rendered, final = _run_readiness()
    assert final == active
    assert final_rendered == active_rendered


def test_same_name_stubbed_fence_function_fails_closed_without_source() -> None:
    _activate_provenance()
    active_rendered, active = _run_readiness()
    assert active == _empty_report(activated=True)

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE OR REPLACE FUNCTION
                    maru_prevent_authority_provenance_truncate()
                RETURNS trigger AS $$
                BEGIN
                    RETURN NULL;
                END;
                $$ LANGUAGE plpgsql
                """
            )
        stubbed_rendered, stubbed = _run_readiness()
        assert stubbed["status"] == "ready"
        assert stubbed["activation_status"] == "blocked"
        assert stubbed["production_status"] == "blocked"
        assert stubbed["known_production_gates"] == {
            "postgresql_server_major": "resolved",
            "runtime_database_role": "resolved",
            "activation_marker": "resolved",
            "exact_lineage_policy_cutover": "resolved",
            "database_completeness_guards": "unresolved",
            "provenance_write_downgrade_fence": "unresolved",
        }
        assert "function" not in stubbed_rendered.lower()
        assert "truncate" not in stubbed_rendered.lower()
        transaction.set_rollback(True)

    final_rendered, final = _run_readiness()
    assert final == active
    assert final_rendered == active_rendered


@pytest.mark.parametrize(("table", "trigger_name"), _FOUNDATIONAL_TRIGGER_CONTRACTS)
def test_disabled_foundational_guard_fails_closed(
    table: str,
    trigger_name: str,
) -> None:
    _activate_provenance()

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {table} DISABLE TRIGGER {trigger_name}")
        rendered, report = _run_readiness()
        _assert_catalog_tamper_blocked(rendered, report)
        transaction.set_rollback(True)

    assert _run_readiness()[1] == _empty_report(activated=True)


@pytest.mark.parametrize("function_name", _FOUNDATIONAL_FUNCTION_CONTRACTS)
def test_stubbed_foundational_function_fails_closed(function_name: str) -> None:
    _activate_provenance()

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                CREATE OR REPLACE FUNCTION {function_name}()
                RETURNS trigger AS $$
                BEGIN
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
                """
            )
        rendered, report = _run_readiness()
        _assert_catalog_tamper_blocked(rendered, report)
        transaction.set_rollback(True)

    assert _run_readiness()[1] == _empty_report(activated=True)


def test_stubbed_privileged_latch_lock_helper_fails_closed() -> None:
    _activate_provenance()

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE OR REPLACE FUNCTION
                    public.maru_lock_authority_provenance_latch()
                RETURNS smallint AS $$
                    SELECT 0::smallint
                $$ LANGUAGE sql
                SECURITY DEFINER
                SET search_path = pg_catalog, public, pg_temp
                """
            )
        rendered, report = _run_readiness()
        _assert_catalog_tamper_blocked(rendered, report)
        transaction.set_rollback(True)

    assert _run_readiness()[1] == _empty_report(activated=True)


@pytest.mark.parametrize(
    "replacement_sql",
    [
        """
        CREATE OR REPLACE FUNCTION
            public.maru_authorization_capability_min_scope(capability_code text)
        RETURNS smallint AS $$ SELECT 0::smallint $$ LANGUAGE sql
        SET search_path = pg_catalog, public, pg_temp
        """,
        """
        CREATE OR REPLACE FUNCTION
            public.maru_authorization_scope_rank(
                edition_id uuid,
                department_id uuid,
                resource_binding_id uuid
            )
        RETURNS smallint AS $$ SELECT 3::smallint $$ LANGUAGE sql
        SET search_path = pg_catalog, public, pg_temp
        """,
        """
        CREATE OR REPLACE FUNCTION public.maru_authorization_scope_contains(
            parent_organization_id uuid,
            parent_edition_id uuid,
            parent_department_id uuid,
            parent_resource_binding_id uuid,
            child_organization_id uuid,
            child_edition_id uuid,
            child_department_id uuid,
            child_resource_binding_id uuid
        )
        RETURNS boolean AS $$ SELECT TRUE $$ LANGUAGE sql
        SET search_path = pg_catalog, public, pg_temp
        """,
    ],
)
def test_stubbed_foundational_scope_helper_fails_closed(
    replacement_sql: str,
) -> None:
    _activate_provenance()

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(replacement_sql)
        rendered, report = _run_readiness()
        _assert_catalog_tamper_blocked(rendered, report)
        transaction.set_rollback(True)

    assert _run_readiness()[1] == _empty_report(activated=True)


@pytest.mark.parametrize(("table", "trigger_name"), _FOUNDATIONAL_TRIGGER_CONTRACTS)
def test_dropped_foundational_guard_fails_closed(
    table: str,
    trigger_name: str,
) -> None:
    _activate_provenance()

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(f"DROP TRIGGER {trigger_name} ON {table}")
        rendered, report = _run_readiness()
        _assert_catalog_tamper_blocked(rendered, report)
        transaction.set_rollback(True)

    assert _run_readiness()[1] == _empty_report(activated=True)


@pytest.mark.parametrize(
    "replacement_sql",
    [
        """
        DROP TRIGGER audit_event_append_only ON public.audit_auditevent;
        CREATE TRIGGER audit_event_append_only
        BEFORE INSERT OR UPDATE OF reason_code OR DELETE
        ON public.audit_auditevent
        FOR EACH ROW EXECUTE FUNCTION public.maru_guard_audit_event();
        """,
        """
        DROP TRIGGER authorization_capability_grant_guard
        ON public.authorization_capabilitygrant;
        CREATE TRIGGER authorization_capability_grant_guard
        BEFORE INSERT OR UPDATE OF revoked_at, revoked_by_id, revocation_reason
        ON public.authorization_capabilitygrant
        FOR EACH ROW EXECUTE FUNCTION public.maru_validate_capability_grant();
        """,
    ],
)
def test_update_of_narrowed_guard_fails_closed(replacement_sql: str) -> None:
    _activate_provenance()

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(replacement_sql)
        rendered, report = _run_readiness()
        _assert_catalog_tamper_blocked(rendered, report)
        transaction.set_rollback(True)

    assert _run_readiness()[1] == _empty_report(activated=True)


@pytest.mark.parametrize(
    ("replacement_sql", "downgrade_fence_resolved"),
    [
        (
            """
            DROP TRIGGER authorization_provenance_activation_guard
                ON authorization_authorityprovenanceactivation;
            CREATE TRIGGER authorization_provenance_activation_guard
            BEFORE INSERT OR UPDATE OR DELETE
                ON authorization_authorityprovenanceactivation
            FOR EACH ROW WHEN (FALSE)
            EXECUTE FUNCTION maru_guard_authority_provenance_activation();
            """,
            False,
        ),
        (
            """
            DROP TRIGGER authorization_provenance_latch_guard
                ON authorization_provenanceactivationlatch;
            CREATE TRIGGER authorization_provenance_latch_guard
            BEFORE INSERT OR UPDATE OR DELETE
                ON authorization_provenanceactivationlatch
            FOR EACH ROW WHEN (FALSE)
            EXECUTE FUNCTION maru_guard_authority_provenance_latch();
            """,
            False,
        ),
        (
            """
            DROP TRIGGER authorization_capability_grant_provenance_complete
                ON authorization_capabilitygrant;
            CREATE CONSTRAINT TRIGGER
                authorization_capability_grant_provenance_complete
            AFTER INSERT ON authorization_capabilitygrant
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW WHEN (FALSE)
            EXECUTE FUNCTION maru_deferred_validate_authority_grant();
            """,
            True,
        ),
    ],
)
def test_same_shape_trigger_with_false_predicate_fails_closed(
    replacement_sql: str,
    downgrade_fence_resolved: bool,
) -> None:
    _activate_provenance()

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(replacement_sql)
        rendered, report = _run_readiness()
        _assert_catalog_tamper_blocked(
            rendered,
            report,
            downgrade_fence_resolved=downgrade_fence_resolved,
        )
        transaction.set_rollback(True)

    assert _run_readiness()[1] == _empty_report(activated=True)


def test_stubbed_lineage_validator_only_unresolves_completeness_gate() -> None:
    _activate_provenance()
    active_rendered, active = _run_readiness()
    assert active == _empty_report(activated=True)

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE OR REPLACE FUNCTION maru_authority_issuance_valid_v1(
                    target_ordinal bigint,
                    expected_principal uuid,
                    required_capability varchar,
                    target_organization uuid,
                    target_edition uuid,
                    target_department uuid,
                    target_binding uuid,
                    requested_effective_from timestamptz,
                    requested_expires_at timestamptz,
                    effective_evaluation timestamptz,
                    require_current boolean,
                    persistent_horizon boolean,
                    lineage_path bigint[],
                    lineage_depth integer
                )
                RETURNS boolean AS $$
                    SELECT TRUE;
                $$ LANGUAGE sql STABLE
                """
            )
        stubbed_rendered, stubbed = _run_readiness()
        assert stubbed["status"] == "ready"
        assert stubbed["activation_status"] == "blocked"
        assert stubbed["production_status"] == "blocked"
        assert stubbed["known_production_gates"] == {
            "postgresql_server_major": "resolved",
            "runtime_database_role": "resolved",
            "activation_marker": "resolved",
            "exact_lineage_policy_cutover": "resolved",
            "database_completeness_guards": "unresolved",
            "provenance_write_downgrade_fence": "resolved",
        }
        assert "maru_authority_issuance_valid_v1" not in stubbed_rendered
        assert "function" not in stubbed_rendered.lower()
        transaction.set_rollback(True)

    final_rendered, final = _run_readiness()
    assert final == active
    assert final_rendered == active_rendered


def test_post_activation_corruption_fails_closed_with_count_only_json() -> None:
    organization, actor, approver = _board()
    marker = _activate_provenance()
    recipient = AccountFactory()
    private_capability = "events.view_basic"
    private_reason = "Private post-cutover corruption evidence."

    with transaction.atomic():
        incomplete = CapabilityGrant.objects.create(
            organization=organization,
            principal=recipient,
            capability_code=private_capability,
            effective_from=timezone.now(),
            granted_by=actor,
            approved_by=approver,
            reason=private_reason,
        )

        first_rendered, first = _run_readiness()
        second_rendered, second = _run_readiness()

        assert first["status"] == "blocked"
        assert first["activation_status"] == "blocked"
        assert first["production_status"] == "blocked"
        assert (
            first["blocker_counts"]["effective_or_future_root_grant_missing_issuance"]
            == 1
        )
        assert (
            first["known_production_gates"]
            == _empty_report(activated=True)["known_production_gates"]
        )
        assert second == first
        assert second_rendered == first_rendered
        for private_value in (
            recipient.email,
            str(recipient.id),
            str(incomplete.id),
            organization.name,
            private_capability,
            private_reason,
            marker.reason,
            str(marker.correlation_id),
        ):
            assert private_value not in first_rendered

        failing_output = StringIO()
        with pytest.raises(CommandError, match="provenance blockers detected"):
            call_command(
                "check_authority_provenance_readiness",
                stdout=failing_output,
            )
        assert json.loads(failing_output.getvalue()) == first
        transaction.set_rollback(True)


def test_unproven_open_authority_blocks_but_dead_unused_legacy_is_review_only() -> None:
    organization = OrganizationFactory()
    actor = AccountFactory()
    approver = AccountFactory()
    recipient = AccountFactory()
    now = timezone.now()
    private_capability = "events.view_basic"
    private_reason = "Readiness must never print this entered reason."

    CapabilityGrant.objects.create(
        organization=organization,
        principal=recipient,
        capability_code=private_capability,
        effective_from=now + timedelta(days=2),
        granted_by=actor,
        approved_by=approver,
        reason=private_reason,
    )
    CapabilityGrant.objects.create(
        organization=organization,
        principal=recipient,
        capability_code=private_capability,
        effective_from=now - timedelta(days=2),
        expires_at=now - timedelta(days=1),
        granted_by=actor,
        approved_by=approver,
        reason=private_reason,
    )
    old_bundle = RoleBundle.objects.create(
        organization=organization,
        code="private-readiness-role",
        name="Private readiness old role",
        version=1,
        capability_codes=[private_capability],
        created_by=actor,
        approved_by=approver,
        reason=private_reason,
    )
    RoleBundle.objects.create(
        organization=organization,
        code="private-readiness-role",
        name="Private readiness current role",
        version=2,
        capability_codes=[private_capability],
        created_by=actor,
        approved_by=approver,
        reason=private_reason,
    )
    RoleAssignment.objects.create(
        organization=organization,
        principal=recipient,
        role_bundle=old_bundle,
        effective_from=now - timedelta(days=2),
        expires_at=now - timedelta(days=1),
        granted_by=actor,
        approved_by=approver,
        reason=private_reason,
    )

    rendered, report = _run_readiness()

    assert report["status"] == "blocked"
    assert report["production_status"] == "blocked"
    assert (
        report["blocker_counts"]["effective_or_future_root_grant_missing_issuance"] == 1
    )
    assert (
        report["blocker_counts"][
            "referenced_or_assignable_role_bundle_missing_issuance"
        ]
        == 1
    )
    assert (
        report["review_counts"]["expired_or_revoked_root_grant_missing_issuance"] == 1
    )
    assert (
        report["review_counts"]["expired_or_revoked_role_assignment_missing_issuance"]
        == 1
    )
    assert report["review_counts"]["unused_role_bundle_missing_issuance"] == 1
    assert recipient.email not in rendered
    assert str(recipient.id) not in rendered
    assert organization.name not in rendered
    assert private_capability not in rendered
    assert private_reason not in rendered

    failing_output = StringIO()
    with pytest.raises(CommandError, match="Authority provenance blockers detected"):
        call_command("check_authority_provenance_readiness", stdout=failing_output)
    assert json.loads(failing_output.getvalue()) == report


def test_delegated_gaps_and_preserved_broad_bootstrap_are_counted() -> None:
    organization = OrganizationFactory()
    platform = AccountFactory(is_staff=True, is_superuser=True)
    chair = AccountFactory()
    recipient = AccountFactory()
    now = timezone.now()
    parent = CapabilityGrant.objects.create(
        organization=organization,
        principal=chair,
        capability_code="events.view_basic",
        effective_from=now,
        granted_by=platform,
        approved_by=chair,
        reason="Synthetic preserved parent.",
    )
    CapabilityGrant.objects.create(
        organization=organization,
        principal=recipient,
        capability_code=parent.capability_code,
        effective_from=now,
        granted_by=chair,
        delegated_from=parent,
        reason="Synthetic delegated gap.",
    )
    broad_bundle = RoleBundle.objects.create(
        organization=organization,
        code="authority-controller",
        name="Synthetic preserved broad bootstrap",
        version=1,
        capability_codes=["authorization.manage_roles"],
        created_by=platform,
        approved_by=chair,
        reason="Synthetic preserved broad bootstrap.",
    )
    RoleAssignment.objects.create(
        organization=organization,
        principal=chair,
        role_bundle=broad_bundle,
        effective_from=now,
        granted_by=platform,
        approved_by=platform,
        reason="Synthetic preserved broad assignment.",
    )

    _rendered, report = _run_readiness()

    assert (
        report["blocker_counts"]["effective_or_future_delegated_grant_missing_issuance"]
        == 1
    )
    assert report["blocker_counts"]["delegated_grant_parent_missing_issuance"] == 1
    assert report["review_counts"]["preserved_broad_workforce_bootstrap_signature"] == 1


def test_incomplete_and_raw_identity_mismatch_are_classified_without_values() -> None:
    organization, actor, approver = _board()
    recipient = AccountFactory()
    evaluated_at = timezone.now()
    incomplete = CapabilityGrant.objects.create(
        organization=organization,
        principal=recipient,
        capability_code="events.view_basic",
        effective_from=evaluated_at,
        granted_by=actor,
        approved_by=approver,
        reason="Private incomplete evidence.",
    )
    AuthorityIssuance.objects.create(
        capability_grant=incomplete,
        policy_version=POLICY_VERSION,
        evaluated_at=evaluated_at,
    )

    complete = CapabilityGrant.objects.create(
        organization=organization,
        principal=AccountFactory(),
        capability_code="organizations.view_basic",
        effective_from=evaluated_at,
        granted_by=actor,
        approved_by=approver,
        reason="Private raw mismatch evidence.",
    )
    complete_issuance = create_persistent_dual_control_issuance(
        target=complete,
        actor_source=_board_source(actor),
        approver_source=_board_source(approver),
        evaluated_at=evaluated_at,
    )
    actor_control = AuthorityControl.objects.get(
        issuance=complete_issuance,
        role=AuthorityControl.Role.ACTOR,
    )

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE authorization_authoritycontrol DISABLE TRIGGER "
                "authorization_authority_control_immutable"
            )
            cursor.execute(
                "ALTER TABLE authorization_authoritycontrol DISABLE TRIGGER "
                "authorization_authority_control_insert_guard"
            )
            cursor.execute(
                "UPDATE authorization_authoritycontrol SET principal_id = %s "
                "WHERE id = %s",
                [recipient.id, actor_control.id],
            )
        rendered, report = _run_readiness()
        assert report["blocker_counts"]["incomplete_control_set"] == 1
        assert report["blocker_counts"]["control_identity_mismatch"] == 1
        assert recipient.email not in rendered
        assert str(recipient.id) not in rendered
        assert complete.capability_code not in rendered
        transaction.set_rollback(True)


def test_raw_non_earlier_delegated_parent_is_a_data_blocker() -> None:
    organization = OrganizationFactory()
    delegator = AccountFactory()
    recipient = AccountFactory()
    controller = AccountFactory()
    evaluated_at = timezone.now()
    parent = CapabilityGrant.objects.create(
        organization=organization,
        principal=delegator,
        capability_code="events.view_basic",
        effective_from=evaluated_at,
        granted_by=controller,
        approved_by=AccountFactory(),
        reason="Synthetic malformed parent order.",
    )
    child = CapabilityGrant.objects.create(
        organization=organization,
        principal=recipient,
        capability_code=parent.capability_code,
        effective_from=evaluated_at,
        granted_by=delegator,
        delegated_from=parent,
        reason="Synthetic malformed child order.",
    )

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE authorization_authorityissuance DISABLE TRIGGER "
                "authorization_authority_issuance_insert_guard"
            )
            cursor.execute(
                "INSERT INTO authorization_authorityissuance "
                "(public_id, policy_version, evaluated_at, capability_grant_id, "
                "role_bundle_id, role_assignment_id, created_at) "
                "VALUES (%s, %s, %s, %s, NULL, NULL, %s) RETURNING ordinal",
                [uuid4(), POLICY_VERSION, evaluated_at, child.id, evaluated_at],
            )
            child_ordinal = cursor.fetchone()[0]
            cursor.execute(
                "INSERT INTO authorization_authorityissuance "
                "(public_id, policy_version, evaluated_at, capability_grant_id, "
                "role_bundle_id, role_assignment_id, created_at) "
                "VALUES (%s, %s, %s, %s, NULL, NULL, %s) RETURNING ordinal",
                [uuid4(), POLICY_VERSION, evaluated_at, parent.id, evaluated_at],
            )
            parent_ordinal = cursor.fetchone()[0]

        _rendered, report = _run_readiness()

        assert parent_ordinal > child_ordinal
        assert report["status"] == "blocked"
        assert report["blocker_counts"]["control_source_not_earlier"] == 1
        assert report["blocker_counts"]["malformed_lineage"] >= 1
        transaction.set_rollback(True)


def test_raw_control_metadata_mismatch_is_classified() -> None:
    organization, actor, approver = _board()
    target = CapabilityGrant.objects.create(
        organization=organization,
        principal=AccountFactory(),
        capability_code="events.view_basic",
        effective_from=timezone.now(),
        granted_by=actor,
        approved_by=approver,
        reason="Synthetic metadata mismatch.",
    )
    issuance = create_persistent_dual_control_issuance(
        target=target,
        actor_source=_board_source(actor),
        approver_source=_board_source(approver),
        evaluated_at=target.effective_from,
    )

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE authorization_authoritycontrol DISABLE TRIGGER "
                "authorization_authority_control_immutable"
            )
            cursor.execute(
                "ALTER TABLE authorization_authoritycontrol DISABLE TRIGGER "
                "authorization_authority_control_insert_guard"
            )
            cursor.execute(
                "UPDATE authorization_authoritycontrol "
                "SET policy_version = %s WHERE issuance_id = %s AND role = %s",
                [
                    "synthetic-mismatched-policy",
                    issuance.ordinal,
                    AuthorityControl.Role.ACTOR,
                ],
            )

        _rendered, report = _run_readiness()

        assert report["status"] == "blocked"
        assert report["blocker_counts"]["control_metadata_mismatch"] == 1
        transaction.set_rollback(True)


def test_corrupt_legacy_snapshots_are_classified_without_mutating_evidence() -> None:  # noqa: PLR0915
    organization, actor, approver = _board()
    evaluated_at = timezone.now()
    actor_board = _board_source(actor)
    approver_board = _board_source(approver)

    def issue(
        *,
        principal: Account,
        capability_code: str,
        granted_by: Account,
        approved_by: Account,
        actor_source: AuthorityIssuance,
        approver_source: AuthorityIssuance,
        edition=None,  # type: ignore[no-untyped-def]
        expires_at=None,  # type: ignore[no-untyped-def]
    ) -> tuple[CapabilityGrant, AuthorityIssuance]:
        grant = CapabilityGrant.objects.create(
            organization=organization,
            edition=edition,
            principal=principal,
            capability_code=capability_code,
            effective_from=evaluated_at,
            expires_at=expires_at,
            granted_by=granted_by,
            approved_by=approved_by,
            reason="Synthetic readiness graph evidence.",
        )
        issuance = create_persistent_dual_control_issuance(
            target=grant,
            actor_source=actor_source,
            approver_source=approver_source,
            evaluated_at=evaluated_at,
        )
        return grant, issuance

    actor_root, actor_root_issuance = issue(
        principal=actor,
        capability_code="authorization.grant_direct",
        granted_by=actor,
        approved_by=approver,
        actor_source=actor_board,
        approver_source=approver_board,
    )
    _approver_root, approver_root_issuance = issue(
        principal=approver,
        capability_code="authorization.grant_direct",
        granted_by=approver,
        approved_by=actor,
        actor_source=approver_board,
        approver_source=actor_board,
    )
    _wrong_capability, wrong_capability_issuance = issue(
        principal=actor,
        capability_code="events.view_basic",
        granted_by=actor,
        approved_by=approver,
        actor_source=actor_board,
        approver_source=approver_board,
    )
    edition = EventEditionFactory(series__organization=organization)
    _edition_source, edition_source_issuance = issue(
        principal=actor,
        capability_code="authorization.grant_direct",
        granted_by=actor,
        approved_by=approver,
        actor_source=actor_board,
        approver_source=approver_board,
        edition=edition,
    )
    _bounded_source, bounded_source_issuance = issue(
        principal=actor,
        capability_code="authorization.grant_direct",
        granted_by=actor,
        approved_by=approver,
        actor_source=actor_board,
        approver_source=approver_board,
        expires_at=evaluated_at + timedelta(days=1),
    )
    target, target_issuance = issue(
        principal=AccountFactory(),
        capability_code="events.view_basic",
        granted_by=actor,
        approved_by=approver,
        actor_source=actor_root_issuance,
        approver_source=approver_root_issuance,
    )
    delegated = CapabilityGrant.objects.create(
        organization=organization,
        principal=AccountFactory(),
        capability_code=target.capability_code,
        effective_from=evaluated_at,
        granted_by=target.principal,
        delegated_from=target,
        reason="Synthetic delegated readiness evidence.",
    )
    delegated_issuance = create_delegated_grant_issuance(
        grant=delegated,
        evaluated_at=evaluated_at,
    )

    base = provenance_readiness._AuthorityGraph(
        at=evaluated_at + timedelta(microseconds=1)
    )
    assert not {
        key: value for key, value in base.structural_blocker_counts().items() if value
    }

    target_ordinal = target_issuance.ordinal

    def target_actor_control(candidate):  # type: ignore[no-untyped-def]
        return next(
            control
            for control in candidate.controls_by_issuance[target_ordinal]
            if control["role"] == AuthorityControl.Role.ACTOR
        )

    cases: list[tuple[str, provenance_readiness._AuthorityGraph, dict[str, int]]] = []

    candidate = deepcopy(base)
    target_actor_control(candidate)["source_issuance_id"] = (
        approver_root_issuance.ordinal
    )
    cases.append(("foreign source", candidate, {"control_source_foreign": 1}))

    candidate = deepcopy(base)
    target_actor_control(candidate)["source_issuance_id"] = (
        wrong_capability_issuance.ordinal
    )
    cases.append(
        (
            "wrong capability",
            candidate,
            {"control_source_capability_mismatch": 1},
        )
    )

    candidate = deepcopy(base)
    target_actor_control(candidate)["source_issuance_id"] = (
        edition_source_issuance.ordinal
    )
    cases.append(("narrow scope", candidate, {"control_source_scope_mismatch": 1}))

    candidate = deepcopy(base)
    candidate.grants[target.id]["resource_binding_id"] = uuid4()
    cases.append(
        (
            "resource without department",
            candidate,
            {"control_source_not_current": 1, "malformed_lineage": 1},
        )
    )

    candidate = deepcopy(base)
    candidate.grants[target.id]["department_id"] = uuid4()
    cases.append(
        (
            "department without edition",
            candidate,
            {"control_source_not_current": 1, "malformed_lineage": 1},
        )
    )

    candidate = deepcopy(base)
    target_actor_control(candidate)["source_issuance_id"] = (
        bounded_source_issuance.ordinal
    )
    cases.append(("short horizon", candidate, {"control_source_horizon_mismatch": 1}))

    candidate = deepcopy(base)
    target_actor_control(candidate)["policy_version"] = "synthetic-mismatch"
    cases.append(("control metadata", candidate, {"control_metadata_mismatch": 1}))

    candidate = deepcopy(base)
    candidate.issuances[target_ordinal]["policy_version"] = ""
    cases.append(
        (
            "issuance metadata",
            candidate,
            {"control_metadata_mismatch": 1, "malformed_lineage": 1},
        )
    )

    candidate = deepcopy(base)
    board_actor_control = next(
        control
        for control in candidate.controls_by_issuance[actor_board.ordinal]
        if control["role"] == AuthorityControl.Role.ACTOR
    )
    board_actor_control["representation_id"] = uuid4()
    cases.append(
        (
            "Board ceremony",
            candidate,
            {"invalid_board_ceremony_basis": 1},
        )
    )

    candidate = deepcopy(base)
    excess_control = deepcopy(target_actor_control(candidate))
    excess_control.update(id=uuid4(), issuance_id=delegated_issuance.ordinal)
    candidate.controls_by_issuance[delegated_issuance.ordinal].append(excess_control)
    cases.append(
        (
            "delegated excess controls",
            candidate,
            {"delegated_grant_excess_controls": 1},
        )
    )

    candidate = deepcopy(base)
    candidate.issuance_by_grant.pop(target.id)
    cases.append(
        (
            "delegated parent missing",
            candidate,
            {
                "delegated_grant_parent_missing_issuance": 1,
                "malformed_lineage": 1,
            },
        )
    )

    candidate = deepcopy(base)
    duplicate_ordinal = max(int(value) for value in candidate.issuances) + 1
    duplicate_issuance = deepcopy(candidate.issuances[target_ordinal])
    duplicate_issuance["ordinal"] = duplicate_ordinal
    candidate.issuances[duplicate_ordinal] = duplicate_issuance
    candidate.duplicate_target_issuance_ordinals.update(
        {target_ordinal, duplicate_ordinal}
    )
    cases.append(
        (
            "duplicate target issuance",
            candidate,
            {"target_issuance_shape_mismatch": 2},
        )
    )

    candidate = deepcopy(base)
    duplicate_control = deepcopy(target_actor_control(candidate))
    duplicate_control["id"] = uuid4()
    candidate.controls_by_issuance[target_ordinal].append(duplicate_control)
    cases.append(
        (
            "duplicate control role",
            candidate,
            {"incomplete_control_set": 1, "duplicate_control_role": 1},
        )
    )

    target_scope = (organization.id, None, None, None)
    assert not provenance_readiness._scope_contains(
        source=(uuid4(), None, None, None),
        target=target_scope,
    )
    assert not provenance_readiness._scope_contains(
        source=(organization.id, edition.id, uuid4(), uuid4()),
        target=target_scope,
    )
    assert not provenance_readiness._scope_contains(
        source=(organization.id, edition.id, uuid4(), None),
        target=target_scope,
    )
    assert not provenance_readiness._scope_contains(
        source=(organization.id, edition.id, None, None),
        target=target_scope,
    )

    for label, candidate, expected in cases:
        observed = {
            key: value
            for key, value in candidate.structural_blocker_counts().items()
            if value
        }
        assert observed == expected, label

    assert (
        AuthorityIssuance.objects.get(pk=target_ordinal).policy_version
        == POLICY_VERSION
    )
    assert not AuthorityControl.objects.filter(
        issuance_id=delegated_issuance.ordinal
    ).exists()
    assert actor_root.capability_code == "authorization.grant_direct"


def test_readiness_graph_closure_and_integrity_fail_closed() -> None:
    graph = provenance_readiness._AuthorityGraph(at=timezone.now())
    child_id = uuid4()
    parent_id = uuid4()
    source_bundle_id = uuid4()
    child_ordinal = 10
    parent_ordinal = 9
    source_ordinal = 8
    graph.grants = {
        child_id: {"id": child_id, "delegated_from_id": parent_id},
        parent_id: {"id": parent_id, "delegated_from_id": None},
    }
    graph.bundles = {source_bundle_id: {"id": source_bundle_id}}
    graph.assignments = {}
    graph.issuances = {
        child_ordinal: {
            "ordinal": child_ordinal,
            "capability_grant_id": child_id,
            "role_bundle_id": None,
            "role_assignment_id": None,
        },
        parent_ordinal: {
            "ordinal": parent_ordinal,
            "capability_grant_id": parent_id,
            "role_bundle_id": None,
            "role_assignment_id": None,
        },
        source_ordinal: {
            "ordinal": source_ordinal,
            "capability_grant_id": None,
            "role_bundle_id": source_bundle_id,
            "role_assignment_id": None,
        },
    }
    graph.controls_by_issuance = {
        child_ordinal: [{"source_issuance_id": source_ordinal}]
    }
    graph.open_grant_ids = {child_id}
    graph.open_assignment_ids = set()
    graph.reachable_bundle_ids = set()
    graph.issuance_by_grant = {
        child_id: child_ordinal,
        parent_id: parent_ordinal,
    }
    graph.issuance_by_assignment = {}
    graph.issuance_by_bundle = {source_bundle_id: source_ordinal}

    assert graph._reachable_issuance_ordinals() == {
        source_ordinal,
        parent_ordinal,
        child_ordinal,
    }

    cycle_start = 1
    cycle_peer = 2
    depth_start = 100
    missing_start = 200
    missing_node = 999
    depth_nodes = tuple(
        range(
            depth_start,
            depth_start + provenance_readiness.MAX_AUTHORITY_LINEAGE_DEPTH + 1,
        )
    )
    graph.reachable_issuances = {cycle_start, depth_start, missing_start}
    graph.issuances = {
        ordinal: {}
        for ordinal in (cycle_start, cycle_peer, missing_start, *depth_nodes)
    }
    edges = {
        cycle_start: {cycle_peer},
        cycle_peer: {cycle_start},
        missing_start: {missing_node},
        **{current: {following} for current, following in pairwise(depth_nodes)},
    }

    cycles, too_deep, malformed = graph._recursive_graph_issues(edges)

    assert cycles == {cycle_start}
    assert too_deep == {depth_start}
    assert malformed == {missing_start}
