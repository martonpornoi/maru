"""Exact parser support for typed native release guards and helper definitions."""

from dataclasses import replace
from importlib import import_module

import pytest

from maru.catalog.readiness import CATALOG_INTEGRITY_CONTRACT
from maru.core.database_integrity_readiness import (
    _trigger_rows_are_current,
    extend_database_integrity_contract,
    parse_database_integrity_sql_contracts,
)


def test_literal_trigger_arguments_are_retained_and_compared_in_order():
    migration = import_module(
        "maru.programme.migrations.0016_release_dependency_mutations"
    )
    triggers, functions = parse_database_integrity_sql_contracts(migration.FORWARD_SQL)
    trigger = triggers["programme_release_host_identity"]
    assert trigger.arguments == (
        "programme_host_operational",
        "programme_host_disclosure",
    )
    assert trigger.catalog_row[9] == 2
    assert (
        trigger.catalog_row[11]
        == b"programme_host_operational\x00programme_host_disclosure\x00"
    )
    assert _trigger_rows_are_current([trigger.catalog_row], {trigger.name: trigger})
    changed = replace(trigger, arguments=tuple(reversed(trigger.arguments)))
    assert not _trigger_rows_are_current([changed.catalog_row], {trigger.name: trigger})
    source = functions["maru_programme_release_mutation_sources(uuid)"]
    assert source.returns_set
    assert source.result == "TABLE(kind text, source_id uuid)"
    assert source.configuration == ("search_path=pg_catalog, public, pg_temp",)


@pytest.mark.parametrize(
    "argument", ["1", "current_user", "'valid', NULL", "'unterminated"]
)
def test_trigger_argument_expressions_are_not_silently_normalized(argument):
    with pytest.raises(ValueError, match="explicit string literals"):
        parse_database_integrity_sql_contracts(
            "CREATE TRIGGER test_guard BEFORE INSERT ON public.test_table "
            f"FOR EACH ROW EXECUTE FUNCTION public.test_guard({argument});"
        )


def test_trigger_literal_quotes_and_unicode_are_encoded_exactly():
    triggers, _functions = parse_database_integrity_sql_contracts(
        "CREATE TRIGGER test_guard BEFORE INSERT ON public.test_table "
        "FOR EACH ROW EXECUTE FUNCTION public.test_guard('it''s', 'műsor');"
    )
    trigger = triggers["test_guard"]
    assert trigger.arguments == ("it's", "műsor")
    assert trigger.catalog_row[11] == "it's\x00műsor\x00".encode()


def test_narrow_definer_is_fingerprinted_not_assumed_to_be_an_invoker():
    migration = import_module(
        "maru.scheduling.migrations.0009_native_release_journal_writer"
    )
    _triggers, functions = parse_database_integrity_sql_contracts(migration.FORWARD_SQL)
    function = functions[
        "maru_scheduling_record_native_release_change(text, uuid, uuid)"
    ]
    assert function.security_definer
    assert not function.returns_set
    assert function.result == "void"
    assert function.configuration == ("search_path=pg_catalog, public, pg_temp",)


@pytest.mark.parametrize(
    "drift",
    ["none", "source_digest", "missing_definer_opt_in", "unknown_helper", "operation"],
)
def test_composed_source_contract_checks_file_operation_and_exception_set(
    drift, monkeypatch
):
    module_name = "maru.scheduling.migrations.0009_native_release_journal_writer"
    digest = "a69312a334bd49a7f322acb045c9eb6f5016c32d308bc5c3db87abf30353ca04"
    identity = "maru_scheduling_record_native_release_change(text, uuid, uuid)"
    runtime, definers = frozenset({identity}), frozenset({identity})
    if drift == "source_digest":
        digest = "0" * 64
    elif drift == "missing_definer_opt_in":
        definers = frozenset()
    elif drift == "unknown_helper":
        runtime = frozenset({identity, "unreviewed()"})
    elif drift == "operation":
        module = import_module(module_name)
        monkeypatch.setattr(module.Migration, "operations", [])
    contract = extend_database_integrity_contract(
        CATALOG_INTEGRITY_CONTRACT,
        migration_module=module_name,
        source_sha256=digest,
        runtime_executable_functions=runtime,
        security_definer_functions=definers,
    )
    assert contract.source_contract_current is (drift == "none")
    assert contract.functions[identity].security_definer
    assert (
        "scheduling",
        "0009_native_release_journal_writer",
    ) in contract.required_migrations
    assert contract.triggers == CATALOG_INTEGRITY_CONTRACT.triggers
