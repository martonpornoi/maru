"""Keep Events configuration inside independent source and bulk-purpose ceilings."""

import json
from contextlib import nullcontext
from dataclasses import replace
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from jsonschema import Draft202012Validator

from maru.authorization.catalog import EDITION_BASIC_FIELD_CEILING
from maru.authorization.policy import PolicyDecision
from maru.events import programme_exit_queries as queries
from maru.programme.authorization import ProgrammeAuthorizationDeniedError


@pytest.fixture
def source(monkeypatch):
    args = dict(
        zip(
            ("actor_id", "organization_id", "edition_id", "correlation_id"),
            (UUID(int=i) for i in range(1, 5)),
            strict=True,
        )
    )
    row = {
        "id": args["edition_id"],
        "organization_id": args["organization_id"],
        "series_id": UUID(int=5),
        "slug": "synthetic",
        "name": "Synthetic édition",
        "lifecycle": "preparing",
        "aggregate_version": 2,
        "adoption_profile_code": "programme_operations",
        "adoption_profile_version": 1,
        "time_zone": "Europe/Budapest",
        "language_codes": ["hu", "en"],
        "starts_on": date(2030, 1, 1),
        "ends_on": date(2030, 1, 2),
    }
    owned = Mock()
    owned.return_value.values.return_value.first.return_value = row
    monkeypatch.setattr(queries.EventEdition.objects, "filter", owned)
    purpose, lock, audit = Mock(), Mock(return_value=True), Mock()
    decision = PolicyDecision(
        allowed=True,
        fields=queries._FIELDS,
        obligations=frozenset(),
        reason_code="synthetic",
    )
    policy = Mock(return_value=decision)
    monkeypatch.setattr(queries, "authorize_programme_archive_scope", purpose)
    monkeypatch.setattr(queries, "decide_verified_principal_exact_edition", policy)
    monkeypatch.setattr(queries, "lock_edition_ownership", lock)
    monkeypatch.setattr(queries, "append_audit", audit)
    monkeypatch.setattr(queries.transaction, "atomic", nullcontext)
    return SimpleNamespace(
        args=args,
        row=row,
        owned=owned,
        purpose=purpose,
        lock=lock,
        audit=audit,
        decision=decision,
        policy=policy,
    )


def test_exact_current_configuration_closed_schema_scope_and_audit(source):
    result = queries.load_programme_exit_configuration(**source.args)
    data, schema = json.loads(result.data), json.loads(result.schema)
    assert set(data) == queries._FIELDS < EDITION_BASIC_FIELD_CEILING
    assert data["language_codes"] == ["hu", "en"]
    assert data["starts_on"] == "2030-01-01"
    assert data["id"] == str(source.args["edition_id"])
    assert data["name"] == "Synthetic édition"
    assert result.owner == "events"
    assert result.contract == "events.programme-exit@1"
    Draft202012Validator.check_schema(schema)
    assert Draft202012Validator(schema).is_valid(data)
    assert not Draft202012Validator(schema).is_valid({**data, "receipt": "forbidden"})
    source.owned.assert_called_once_with(
        id=source.args["edition_id"],
        organization_id=source.args["organization_id"],
        series__organization_id=source.args["organization_id"],
    )
    source.owned.return_value.values.assert_called_once_with(*sorted(queries._FIELDS))
    assert source.purpose.call_count == source.policy.call_count == 3
    assert all(
        call.kwargs["capability_code"] == "events.view_basic"
        for call in source.policy.call_args_list
    )
    record = source.audit.call_args.args[0]
    assert record.outcome == "allow"
    assert record.target_id == source.args["edition_id"]
    assert record.obligations == ("audit_sensitive_read",)
    assert "Synthetic" not in repr(record.safe_metadata)


@pytest.mark.parametrize("boundary", ["purpose", "policy"])
@pytest.mark.parametrize("final", [False, True])
def test_either_initial_or_final_independent_denial_refuses_section(
    source, boundary, final
):
    guard = getattr(source, boundary)
    denial = (
        ProgrammeAuthorizationDeniedError()
        if boundary == "purpose"
        else replace(source.decision, allowed=False)
    )
    guard.side_effect = [source.decision] * (2 if final else 0) + [denial]
    with pytest.raises(PermissionDenied, match="unavailable"):
        queries.load_programme_exit_configuration(**source.args)
    assert source.audit.call_args.args[0].outcome == "deny"
    assert source.audit.call_args.args[0].target_id is None
    if not final:
        source.owned.assert_not_called()


@pytest.mark.parametrize("decision", [True, None, "allow", frozenset()])
def test_non_policy_decision_is_never_authority(source, decision):
    source.policy.return_value = decision
    with pytest.raises(PermissionDenied):
        queries.load_programme_exit_configuration(**source.args)
    source.owned.assert_not_called()


@pytest.mark.parametrize("field", sorted(queries._FIELDS))
def test_each_missing_source_field_is_independently_required(source, field):
    source.policy.return_value = replace(
        source.decision, fields=queries._FIELDS - {field}
    )
    with pytest.raises(PermissionDenied):
        queries.load_programme_exit_configuration(**source.args)
    source.owned.assert_not_called()


@pytest.mark.parametrize("where", ["lock", "row"])
def test_unavailable_coherent_ownership_returns_no_partial_result(source, where):
    if where == "lock":
        source.lock.return_value = False
    else:
        source.owned.return_value.values.return_value.first.return_value = None
    with pytest.raises(PermissionDenied):
        queries.load_programme_exit_configuration(**source.args)
    assert source.audit.call_args.args[0].outcome == "deny"


def test_audit_failure_withholds_all_bytes(source):
    source.audit.side_effect = RuntimeError("synthetic audit outage")
    with pytest.raises(RuntimeError, match="synthetic audit outage"):
        queries.load_programme_exit_configuration(**source.args)


@pytest.mark.parametrize(
    "field", ["actor_id", "organization_id", "edition_id", "correlation_id"]
)
@pytest.mark.parametrize("value", [None, True, "not-uuid", UUID(int=0)])
def test_scope_requires_non_nil_identifiers_before_any_disclosure(source, field, value):
    with pytest.raises(ValidationError):
        queries.load_programme_exit_configuration(**{**source.args, field: value})
    source.purpose.assert_not_called()
    source.owned.assert_not_called()
    source.audit.assert_not_called()
