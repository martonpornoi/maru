from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from importlib import import_module

from django.db import migrations

from maru.applications.readiness import APPLICATIONS_INTEGRITY_CONTRACT
from maru.catalog.readiness import CATALOG_INTEGRITY_CONTRACT
from maru.charities.readiness import CHARITIES_INTEGRITY_CONTRACT
from maru.core import database_integrity_readiness as integrity
from maru.venues.readiness import VENUES_INTEGRITY_CONTRACT

CONTRACTS = (
    APPLICATIONS_INTEGRITY_CONTRACT,
    CHARITIES_INTEGRITY_CONTRACT,
    CATALOG_INTEGRITY_CONTRACT,
    VENUES_INTEGRITY_CONTRACT,
)


def test_bounded_context_contracts_are_closed_and_derived_from_migrations() -> None:
    assert [
        (
            contract.status_key,
            contract.source_contract_current,
            len(contract.triggers),
            len(contract.functions),
            len(contract.required_migrations),
        )
        for contract in CONTRACTS
    ] == [
        ("applications_integrity", True, 12, 7, 2),
        ("charities_integrity", True, 7, 5, 1),
        ("catalog_integrity", True, 7, 2, 1),
        ("venues_integrity", True, 13, 9, 1),
    ]
    for contract in CONTRACTS:
        relations = set(integrity.bounded_context_relation_names(contract.app_label))
        assert {trigger.table for trigger in contract.triggers.values()} <= relations
        assert contract.source_migration in contract.required_migrations
        assert contract.terminal_migration in contract.required_migrations


def test_trigger_contracts_pin_events_timing_attachment_and_constraint_shape() -> None:
    definition = APPLICATIONS_INTEGRITY_CONTRACT.triggers[
        "applications_definition_guard"
    ]
    assert definition.trigger_type == 31
    assert definition.function_identity == (
        "public.maru_applications_guard_definition()"
    )
    assert not definition.is_constraint
    assert not definition.deferrable

    charity_binding = CHARITIES_INTEGRITY_CONTRACT.triggers[
        "charity_selection_binding_required"
    ]
    assert charity_binding.trigger_type == 5
    assert charity_binding.is_constraint
    assert charity_binding.deferrable
    assert charity_binding.initially_deferred

    venue_binding = VENUES_INTEGRITY_CONTRACT.triggers["venue_space_binding_required"]
    assert venue_binding.trigger_type == 5
    assert venue_binding.is_constraint
    assert venue_binding.deferrable
    assert venue_binding.initially_deferred

    active_product = CATALOG_INTEGRITY_CONTRACT.triggers[
        "catalog_active_product_immutable"
    ]
    assert active_product.trigger_type == 27


def test_function_contracts_pin_body_invoker_search_path_and_behavior() -> None:
    for contract in CONTRACTS:
        assert all(
            function.language == "plpgsql"
            and not function.security_definer
            and function.configuration == ("search_path=pg_catalog, public, pg_temp",)
            and function.result == "trigger"
            and len(function.source_sha256) == 64
            for function in contract.functions.values()
        )

    function = next(iter(APPLICATIONS_INTEGRITY_CONTRACT.functions.values()))
    weakened = replace(function, source=function.source + "\n-- weakened")
    assert weakened.source_sha256 != function.source_sha256


def test_trigger_catalog_comparison_rejects_catalog_drift() -> None:
    contracts = CHARITIES_INTEGRITY_CONTRACT.triggers
    rows = [contract.catalog_row for contract in contracts.values()]
    assert integrity._trigger_rows_are_current(rows, contracts)

    disabled = list(rows)
    disabled_row = list(disabled[0])
    disabled_row[4] = "D"
    disabled[0] = tuple(disabled_row)
    assert not integrity._trigger_rows_are_current(disabled, contracts)

    misattached = list(rows)
    misattached_row = list(misattached[0])
    misattached_row[2] = "public.maru_guard_charity_selection_mutation()"
    misattached[0] = tuple(misattached_row)
    assert not integrity._trigger_rows_are_current(misattached, contracts)

    assert not integrity._trigger_rows_are_current(
        [*rows, rows[0]],
        contracts,
    )


def _function_catalog_rows(
    functions: Mapping[str, integrity.FunctionContract],
) -> list[tuple[object, ...]]:
    return [
        (
            identity,
            True,
            function.source,
            function.language,
            function.volatility,
            function.parallel,
            function.security_definer,
            function.leakproof,
            function.strict,
            function.returns_set,
            function.kind,
            list(function.configuration),
            function.result,
            True,
            True,
        )
        for identity, function in functions.items()
    ]


def test_function_catalog_comparison_separates_definition_acl_and_owner_drift() -> None:
    contracts = CATALOG_INTEGRITY_CONTRACT.functions
    rows = _function_catalog_rows(contracts)
    assert integrity._function_rows_are_current(rows, contracts) == (
        True,
        True,
        True,
    )

    changed_body = [list(row) for row in rows]
    changed_body[0][2] = f"{changed_body[0][2]}\n-- weakened"
    assert integrity._function_rows_are_current(changed_body, contracts) == (
        False,
        True,
        True,
    )

    public_execute = [list(row) for row in rows]
    public_execute[0][13] = False
    assert integrity._function_rows_are_current(public_execute, contracts) == (
        True,
        False,
        True,
    )

    foreign_owner = [list(row) for row in rows]
    foreign_owner[0][14] = False
    assert integrity._function_rows_are_current(foreign_owner, contracts) == (
        True,
        True,
        False,
    )


def test_database_integrity_wrapper_fails_closed_on_catalog_error(monkeypatch) -> None:
    def fail(_contract):  # type: ignore[no-untyped-def]
        raise RuntimeError("private catalog detail")

    monkeypatch.setattr(integrity, "inspect_database_integrity_catalog", fail)

    assert not integrity.database_integrity_contract_is_ready(
        APPLICATIONS_INTEGRITY_CONTRACT
    )


def test_applications_acl_migration_is_additive_exact_and_reversible() -> None:
    migration = import_module(
        "maru.applications.migrations.0003_integrity_function_execute_boundary"
    )
    assert tuple(migration.Migration.dependencies) == (
        ("applications", "0002_integrity_guards"),
    )
    assert len(migration.Migration.operations) == 1
    operation = migration.Migration.operations[0]
    assert isinstance(operation, migrations.RunSQL)
    assert operation.sql == migration.FORWARD_SQL
    assert operation.reverse_sql == migration.REVERSE_SQL
    assert migration.FORWARD_SQL.count("REVOKE ALL ON FUNCTION") == 7
    assert migration.REVERSE_SQL.count("GRANT EXECUTE ON FUNCTION") == 7
    for identity in APPLICATIONS_INTEGRITY_CONTRACT.functions:
        assert f"public.{identity} FROM PUBLIC" in migration.FORWARD_SQL
        assert f"public.{identity} TO PUBLIC" in migration.REVERSE_SQL
