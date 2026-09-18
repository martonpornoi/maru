"""Database-free helper source/ACL expectations, never native execution evidence."""

import re
from dataclasses import asdict, replace
from importlib import import_module
from unittest.mock import Mock

import pytest

from tests.rehearsals import programme_function_acl as acl
from tests.rehearsals import programme_function_contract as contract
from tests.rehearsals.programme_runtime_privileges import _FUNCTIONS


def test_all_baselines_are_source_current_and_only_expected_acl_is_projected():
    changes = contract.candidate_function_contracts()
    assert len(changes) == 5
    assert len(contract.HELPERS) == 14
    seen = {contract.MUTEX_IDENTITY}
    for module, attribute, original, projected in changes:
        assert getattr(module, attribute) is original
        helpers = contract.HELPERS.keys() & original.functions.keys()
        assert helpers
        seen.update(helpers)
        assert projected.runtime_executable_functions == (
            original.runtime_executable_functions | helpers
        )
        original_fields = asdict(original)
        projected_fields = asdict(projected)
        original_fields.pop("runtime_executable_functions")
        projected_fields.pop("runtime_executable_functions")
        assert original_fields == projected_fields
    assert seen == contract.HELPERS.keys()
    assert not {"public." + identity for identity in seen} & set(_FUNCTIONS)


@pytest.mark.parametrize("index", range(5))
@pytest.mark.parametrize("defect", ["source", "trigger", "migration", "acl"])
def test_each_owner_baseline_refuses_drift_without_mutation(index, defect, monkeypatch):
    module_name, attribute, _digest = contract.OWNER_CONTRACTS[index]
    module = import_module(module_name)
    original = getattr(module, attribute)
    values = {
        "source": {"source_contract_current": False},
        "trigger": {"triggers": {}},
        "migration": {
            "supporting_migrations": (
                *original.supporting_migrations,
                ("unknown", "9999"),
            )
        },
        "acl": {"runtime_executable_functions": frozenset(contract.HELPERS)},
    }
    changed = replace(original, **values[defect])
    monkeypatch.setattr(module, attribute, changed)
    with pytest.raises(contract.ProgrammeFunctionError, match="contract_changed"):
        contract.candidate_function_contracts()
    assert getattr(module, attribute) is changed


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_sha256", "0" * 64),
        ("result", "trigger"),
        ("language", "sql"),
        ("volatility", "i"),
        ("strict", True),
        ("returns_set", True),
        ("security_definer", True),
    ],
)
def test_helper_spec_drift_is_not_silently_adopted(field, value, monkeypatch):
    key = "maru_scheduling_release_artifact_is_exact(uuid)"
    changed = dict(contract.HELPERS)
    changed[key] = replace(changed[key], **{field: value})
    monkeypatch.setattr(contract, "HELPERS", changed)
    with pytest.raises(contract.ProgrammeFunctionError, match="metadata_changed"):
        contract.candidate_function_contracts()


def test_unknown_helper_does_not_gain_execution(monkeypatch):
    changed = dict(contract.HELPERS)
    changed["maru_unknown()"] = next(iter(changed.values()))
    monkeypatch.setattr(contract, "HELPERS", changed)
    with pytest.raises(contract.ProgrammeFunctionError, match="inventory_incomplete"):
        contract.candidate_function_contracts()


def test_legacy_mutex_is_exact_lock_only_source_and_cannot_silently_change(monkeypatch):
    module = import_module("maru.workforce.migrations.0007_structure_write_integrity")
    assert "pg_try_advisory_xact_lock(target_lock)" in contract.MUTEX_DECLARATION
    assert "USING ERRCODE = '40001'" in contract.MUTEX_DECLARATION
    assert not re.search(
        r"\b(INSERT|UPDATE|DELETE|EXECUTE)\b", contract.MUTEX_DECLARATION
    )
    monkeypatch.setattr(
        module,
        "INSTALL_BARRIER_FUNCTIONS_SQL",
        module.INSTALL_BARRIER_FUNCTIONS_SQL.replace(
            "pg_try_advisory_xact_lock(target_lock)",
            "pg_try_advisory_lock(target_lock)",
        ),
    )
    with pytest.raises(contract.ProgrammeFunctionError, match="mutex_source_changed"):
        contract.candidate_function_contracts()


def test_mutex_cannot_silently_gain_other_attributes(monkeypatch):
    changed = dict(contract.HELPERS)
    changed[contract.MUTEX_IDENTITY] = replace(
        changed[contract.MUTEX_IDENTITY], result="boolean"
    )
    monkeypatch.setattr(contract, "HELPERS", changed)
    with pytest.raises(contract.ProgrammeFunctionError, match="mutex_metadata_changed"):
        contract.candidate_function_contracts()


def test_invoker_trigger_helper_closure_is_exact_and_definers_remain_unchanged():
    functions = {}
    for (
        _module,
        _attribute,
        original,
        _projected,
    ) in contract.candidate_function_contracts():
        for identity, function in original.functions.items():
            if identity in functions:
                assert functions[identity] == function
            functions[identity] = function
    by_name = {}
    for identity in functions:
        by_name.setdefault(identity.split("(", 1)[0], set()).add(identity)
    pending = [key for key, value in functions.items() if value.result == "trigger"]
    seen = set()
    required = set()
    baseline_names = {
        identity.removeprefix("public.").split("(", 1)[0] for identity in _FUNCTIONS
    }
    while pending:
        identity = pending.pop()
        if identity in seen:
            continue
        seen.add(identity)
        function = functions[identity]
        if function.security_definer:
            continue
        for name in re.findall(r"\b(maru_[a-z0-9_]+)\s*\(", function.source):
            if name == contract.MUTEX_IDENTITY.split("(", 1)[0]:
                # Reviewed legacy definer is a lock-only leaf, not a row writer.
                required.add(contract.MUTEX_IDENTITY)
                continue
            if name not in by_name:
                # Existing authority/reset helpers remain under their canonical
                # production contract, not this candidate's additional grants.
                assert name in baseline_names, name
                continue
            for child in by_name[name]:
                required.add(child)
                pending.append(child)

    def normalized(identity):
        return re.sub(
            r"\s+",
            "",
            identity.removeprefix("public.").replace(
                "timestamptz", "timestamp with time zone"
            ),
        )

    baseline = {normalized(identity) for identity in _FUNCTIONS}
    additions = {
        identity
        for identity in required
        if normalized(identity) not in baseline
        and (
            identity == contract.MUTEX_IDENTITY
            or functions[identity].result != "trigger"
        )
    }
    assert additions == contract.HELPERS.keys()
    assert all(
        not functions[identity].security_definer
        for identity in additions - {contract.MUTEX_IDENTITY}
    )


def _rows():
    sources = {}
    for (
        _module,
        _attribute,
        original,
        _projected,
    ) in contract.candidate_function_contracts():
        sources.update(original.functions)
    source_text = {identity: value.source for identity, value in sources.items()}
    source_text[contract.MUTEX_IDENTITY] = contract.MUTEX_DECLARATION.split(
        "$page9_try_mutex$"
    )[1]
    return [
        (identity, source_text[identity], *spec.metadata[1:], True, True)
        for identity, spec in sorted(contract.HELPERS.items())
    ]


@pytest.mark.parametrize("runtime_granted", [False, True])
def test_catalog_requires_exact_full_metadata_owner_and_acl(runtime_granted):
    connection = Mock()
    connection.execute.return_value.fetchall.return_value = _rows()
    acl.require_helper_catalog(connection, runtime_granted=runtime_granted)
    query, parameters = connection.execute.call_args.args
    assert parameters == [runtime_granted, runtime_granted, sorted(contract.HELPERS)]
    for fragment in (
        "count(DISTINCT privilege.grantee) = count(*)",
        "privilege.grantor = procedure.proowner",
        "NOT privilege.is_grantable",
        "pg_catalog.acldefault",
        "procedure.proowner) = 'maru_migration'",
        "runtime.rolcanlogin AND NOT runtime.rolsuper",
        "NOT runtime.rolcreaterole AND NOT runtime.rolcreatedb",
        "NOT runtime.rolreplication AND NOT runtime.rolbypassrls",
    ):
        assert fragment in query


@pytest.mark.parametrize("column", range(1, 14))
def test_each_changed_native_field_is_rejected(column):
    rows = _rows()
    changed = list(rows[0])
    changed[column] = None
    rows[0] = tuple(changed)
    connection = Mock()
    connection.execute.return_value.fetchall.return_value = rows
    with pytest.raises(contract.ProgrammeFunctionError, match="catalog_changed"):
        acl.require_helper_catalog(connection, runtime_granted=False)


@pytest.mark.parametrize("defect", ["missing", "duplicate", "unknown"])
def test_missing_duplicate_or_unknown_catalog_function_refuses_grants(defect):
    rows = _rows()
    if defect == "missing":
        rows.pop()
    elif defect == "duplicate":
        rows[-1] = rows[0]
    else:
        rows[-1] = ("maru_unknown()", *rows[-1][1:])
    connection = Mock()
    connection.execute.return_value.fetchall.return_value = rows
    with pytest.raises(contract.ProgrammeFunctionError, match="inventory_changed"):
        acl.require_helper_catalog(connection, runtime_granted=False)


def test_grant_is_literal_only_and_verified_before_commit():
    connection = Mock()
    connection.execute.return_value.fetchall.return_value = _rows()
    acl.grant_candidate_helpers(connection)
    calls = connection.execute.call_args_list
    assert len(calls) == 2
    grant = calls[0].args[0].as_string()
    assert grant.startswith("GRANT EXECUTE ON FUNCTION ")
    assert grant.endswith(" TO maru_runtime")
    assert grant.count('"public".') == 14
    assert not any(
        value in grant for value in ("ALL ", "WITH GRANT", "SECURITY DEFINER")
    )
    assert calls[1].args[1] == [True, True, sorted(contract.HELPERS)]
    for identity in contract.HELPERS:
        name, args = identity.split("(", 1)
        assert f'"public"."{name}"({args}' in grant
