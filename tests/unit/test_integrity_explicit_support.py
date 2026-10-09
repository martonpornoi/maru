"""Purpose-specific catalog proofs explicitly name same-owner support attachments."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from maru.core import database_integrity_readiness as integrity


@pytest.fixture
def contract(monkeypatch):
    monkeypatch.setattr(
        integrity,
        "bounded_context_relation_names",
        lambda _label: ("synthetic_evidence", "synthetic_head", "synthetic_other"),
    )
    triggers, _functions = integrity.parse_database_integrity_sql_contracts("""
CREATE TRIGGER synthetic_evidence_guard BEFORE INSERT ON public.synthetic_evidence
FOR EACH ROW EXECUTE FUNCTION public.synthetic_guard();
""")
    primary = triggers["synthetic_evidence_guard"]
    support = replace(primary, name="synthetic_head_guard", table="synthetic_head")
    return integrity.DatabaseIntegrityContract(
        status_key="synthetic_integrity",
        app_label="synthetic",
        source_migration=("synthetic", "0002"),
        terminal_migration=("synthetic", "0003"),
        source_migration_module="synthetic.0002",
        triggers=triggers,
        functions={},
        source_contract_current=True,
        owned_relations=("synthetic_evidence",),
        supporting_triggers={support.name: support},
    )


def test_same_owner_support_must_be_explicit_and_does_not_certify_the_old_table(
    contract,
):
    with pytest.raises(ValueError, match="relation scope"):
        integrity._contract_relation_names(contract)
    declared = replace(contract, supporting_owned_relations=("synthetic_head",))
    assert integrity._contract_relation_names(declared) == ("synthetic_evidence",)
    assert declared.supporting_triggers == contract.supporting_triggers


@pytest.mark.parametrize(
    "names",
    [
        [],
        ("synthetic_head", "synthetic_head"),
        ("synthetic_evidence",),
        ("synthetic_other",),
        ("foreign_head",),
        (None,),
    ],
)
def test_support_declaration_rejects_ambiguous_foreign_or_unattached_relations(
    contract, names
):
    with pytest.raises(ValueError, match="relation scope"):
        integrity._contract_relation_names(
            replace(contract, supporting_owned_relations=names)
        )


@pytest.mark.parametrize("names", [("synthetic_head",), [], "", None])
def test_support_opt_in_cannot_change_an_existing_whole_app_contract(contract, names):
    with pytest.raises(ValueError, match="explicit subset"):
        integrity._contract_relation_names(
            replace(
                contract,
                owned_relations=None,
                supporting_owned_relations=names,
            )
        )
    assert integrity._contract_relation_names(
        replace(contract, owned_relations=None)
    ) == ("synthetic_evidence", "synthetic_head", "synthetic_other")


def test_other_owner_support_retains_its_existing_explicit_trigger_contract(contract):
    primary = next(iter(contract.triggers.values()))
    support = replace(primary, name="foreign_guard", table="foreign_head")
    foreign = replace(contract, supporting_triggers={support.name: support})
    assert integrity._contract_relation_names(foreign) == ("synthetic_evidence",)


def test_array_result_is_exactly_pinned_without_becoming_set_returning():
    _triggers, functions = integrity.parse_database_integrity_sql_contracts("""
CREATE FUNCTION public.synthetic_recipe(value character varying)
RETURNS character varying[] AS $body$
BEGIN RETURN ARRAY[value]; END;
$body$ LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public, pg_temp;
""")
    definition = functions["synthetic_recipe(character varying)"]
    assert definition.result == "character varying[]"
    assert definition.returns_set is False
    assert definition.security_definer is False
    assert definition.volatility == "s"
    assert definition.configuration == ("search_path=pg_catalog, public, pg_temp",)


@pytest.fixture
def catalog(contract, monkeypatch, settings):
    _triggers, functions = integrity.parse_database_integrity_sql_contracts("""
CREATE FUNCTION public.synthetic_guard()
RETURNS trigger AS $$
BEGIN RETURN NEW; END;
$$ LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, public, pg_temp;
CREATE FUNCTION public.synthetic_recipe(value character varying)
RETURNS character varying[] AS $$
BEGIN RETURN ARRAY[value]; END;
$$ LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public, pg_temp;
""")
    recipe = "synthetic_recipe(character varying)"
    declared = replace(
        contract,
        supporting_owned_relations=("synthetic_head",),
        functions=functions,
        runtime_executable_functions=frozenset({recipe}),
    )
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.fetchone.return_value = (True, True)
    connection = SimpleNamespace(cursor=MagicMock(return_value=cursor))
    monkeypatch.setattr(integrity, "connection", connection)
    settings.RUNTIME_DATABASE_ROLE = "synthetic_runtime"
    functions_rows = [
        (
            identity,
            True,
            definition.source,
            definition.language,
            definition.volatility,
            definition.parallel,
            definition.security_definer,
            definition.leakproof,
            definition.strict,
            definition.returns_set,
            definition.kind,
            list(definition.configuration),
            definition.result,
            identity != recipe,
            True,
            True,
        )
        for identity, definition in functions.items()
    ]
    return SimpleNamespace(
        contract=declared,
        cursor=cursor,
        connection=connection,
        primary=declared.triggers["synthetic_evidence_guard"],
        support=declared.supporting_triggers["synthetic_head_guard"],
        functions_rows=functions_rows,
        recipe=recipe,
    )


def _inspect(catalog, *, trigger_rows=None, functions_rows=None):
    catalog.cursor.fetchall.side_effect = [
        list(catalog.contract.required_migrations),
        trigger_rows
        if trigger_rows is not None
        else [catalog.primary.catalog_row, catalog.support.catalog_row],
        functions_rows if functions_rows is not None else catalog.functions_rows,
    ]
    return integrity.inspect_database_integrity_catalog(catalog.contract)


def test_catalog_inspects_only_selected_relations_and_exact_support_names(catalog):
    result = _inspect(catalog)
    assert result.ready
    # A declared runtime helper is valid without making every function executable.
    assert not result.function_execute_owner_only
    assert result.function_execute_boundary_closed
    calls = catalog.cursor.execute.call_args_list
    assert len(calls) == 4
    assert calls[1].args[1] == [1, ["synthetic_evidence"]]
    trigger_sql, trigger_parameters = calls[2].args
    assert trigger_parameters == [["synthetic_evidence"], ["synthetic_head_guard"]]
    compact_sql = " ".join(trigger_sql.split())
    assert (
        "(relation.relname = ANY(%s::text[]) OR trigger.tgname = ANY(%s::text[]))"
        in compact_sql
    )
    assert calls[3].args[1] == [
        "synthetic_evidence",
        [catalog.recipe],
        "synthetic_runtime",
        [catalog.recipe],
        list(catalog.contract.functions),
        "synthetic_runtime",
    ]


@pytest.mark.parametrize(
    "drift",
    [
        "missing_primary",
        "missing_support",
        "extra_primary",
        "extra_matching_support",
        "duplicate_support",
        "misattached_support",
        "disabled_support",
    ],
)
def test_catalog_rejects_incomplete_or_extra_exact_trigger_rows(catalog, drift):
    primary, support = catalog.primary.catalog_row, catalog.support.catalog_row
    wrong_table = replace(catalog.support, table="synthetic_other").catalog_row
    disabled = list(support)
    disabled[4] = "D"
    cases = {
        "missing_primary": [support],
        "missing_support": [primary],
        "extra_primary": [
            primary,
            support,
            replace(catalog.primary, name="undeclared_guard").catalog_row,
        ],
        "extra_matching_support": [primary, support, wrong_table],
        "duplicate_support": [primary, support, support],
        "misattached_support": [primary, wrong_table],
        "disabled_support": [primary, tuple(disabled)],
    }
    result = _inspect(catalog, trigger_rows=cases[drift])
    assert result.relations_installed
    assert result.function_contract_current
    assert not result.trigger_contract_current
    assert not result.ready


def test_whole_app_catalog_still_inspects_every_owned_relation(catalog):
    catalog.contract = replace(
        catalog.contract, owned_relations=None, supporting_owned_relations=()
    )
    assert _inspect(catalog).ready
    relations = ["synthetic_evidence", "synthetic_head", "synthetic_other"]
    calls = catalog.cursor.execute.call_args_list
    assert calls[1].args[1] == [3, relations]
    assert calls[2].args[1] == [relations, ["synthetic_head_guard"]]


def test_undeclared_same_owner_support_fails_before_catalog_access(catalog):
    invalid = replace(catalog.contract, supporting_owned_relations=())
    assert not integrity.database_integrity_contract_is_ready(invalid)
    catalog.connection.cursor.assert_not_called()


@pytest.mark.parametrize(
    ("column", "changed", "failed_proof"),
    [
        pytest.param(12, "character varying", "definition", id="scalar-result"),
        pytest.param(12, "text[]", "definition", id="different-array-type"),
        pytest.param(9, True, "definition", id="set-returning"),
        pytest.param(6, True, "definition", id="security-definer"),
        pytest.param(7, True, "definition", id="leakproof"),
        pytest.param(11, ["search_path=public"], "definition", id="search-path"),
        pytest.param(14, False, "owner", id="foreign-owner"),
        pytest.param(15, False, "acl", id="open-execute-boundary"),
    ],
)
def test_array_function_drift_cannot_hide_behind_valid_trigger_rows(
    catalog, column, changed, failed_proof
):
    rows = [list(row) for row in catalog.functions_rows]
    recipe_row = next(row for row in rows if row[0] == catalog.recipe)
    recipe_row[column] = changed
    result = _inspect(catalog, functions_rows=rows)
    assert result.trigger_contract_current
    assert result.function_contract_current is (failed_proof != "definition")
    assert result.function_ownership_current is (failed_proof != "owner")
    assert result.function_execute_boundary_closed is (failed_proof != "acl")
    assert not result.ready
