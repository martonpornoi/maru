"""Exercise independent archive configuration/audit boundaries without a database."""

import json
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.core.exceptions import PermissionDenied
from jsonschema import Draft202012Validator

from maru.audit import programme_exit_queries as audit
from maru.authorization import programme_exit_queries as authority
from maru.authorization.policy import PolicyDecision
from maru.authorization.programme_role_recipes import PROGRAMME_ROLE_RECIPES
from maru.events.queries import EditionAdoptionProfileReference
from maru.programme.authorization import ProgrammeAuthorizationDeniedError


@pytest.fixture(params=[audit, authority], ids=["audit", "authorization"])
def source(request, monkeypatch):
    module = request.param
    args = dict(
        zip(
            ("actor_id", "organization_id", "edition_id", "correlation_id"),
            (UUID(int=i) for i in range(1, 5)),
            strict=True,
        )
    )
    query = (
        module.load_programme_exit_audit
        if module is audit
        else module.load_programme_exit_authorization
    )
    unavailable = (
        audit.ProgrammeExitAuditUnavailableError
        if module is audit
        else authority.ProgrammeExitAuthorizationUnavailableError
    )
    decision = PolicyDecision(
        allowed=True,
        fields=frozenset(module.FIELDS),
        obligations=frozenset(),
        reason_code="synthetic",
    )
    policy, purpose, lock, append = Mock(return_value=decision), Mock(), Mock(), Mock()
    monkeypatch.setattr(module, "decide_verified_principal_exact_edition", policy)
    monkeypatch.setattr(module, "authorize_programme_archive_scope", purpose)
    monkeypatch.setattr(module, "lock_programme_staffing_scope", lock)
    monkeypatch.setattr(module, "append_audit", append)
    monkeypatch.setattr(module.transaction, "atomic", nullcontext)
    if module is audit:
        rows = tuple(
            {
                "id": UUID(int=number),
                "occurred_at": datetime(2030, 1, 1, tzinfo=UTC),
                "capability_code": "synthetic.read",
                "operation": operation,
                "outcome": "allow",
            }
            for number, operation in enumerate(sorted(audit.GENERATION_OPERATIONS), 10)
        )
        manager = Mock()
        manager.return_value.order_by.return_value.values.return_value.__getitem__ = (
            Mock(return_value=rows)
        )
        # Magic methods on a plain Mock are configured explicitly.
        monkeypatch.setattr(audit.AuditEvent.objects, "filter", manager)
        owned = manager
    else:
        rows = EditionAdoptionProfileReference("full_convention", 1)
        owned = Mock(return_value=rows)
        monkeypatch.setattr(authority, "edition_adoption_profile_reference", owned)
    return SimpleNamespace(
        module=module,
        args=args,
        query=query,
        unavailable=unavailable,
        policy=policy,
        purpose=purpose,
        lock=lock,
        audit=append,
        decision=decision,
        owned=owned,
        rows=rows,
    )


def test_exact_scope_closed_schema_and_mandatory_audit(source):
    section = source.query(**source.args)
    data, schema = json.loads(section.data), json.loads(section.schema)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(data)
    assert section.contract == f"{section.owner}.programme-exit@1"
    assert not Draft202012Validator(schema).is_valid({**data, "private": "forbidden"})
    assert source.purpose.call_count == source.policy.call_count == 3
    record = source.audit.call_args.args[0]
    assert record.principal_id == source.args["actor_id"]
    assert record.event_edition_id == source.args["edition_id"]
    assert record.correlation_id == source.args["correlation_id"]
    assert record.outcome == "allow"
    if source.module is audit:
        source.owned.assert_called_once_with(
            organization_id=source.args["organization_id"],
            event_edition_id=source.args["edition_id"],
            principal_kind="account",
            principal_id=source.args["actor_id"],
            correlation_id=source.args["correlation_id"],
            outcome="allow",
            operation__in=audit.GENERATION_OPERATIONS,
        )
        assert len(data["receipts"]) == 7
        assert all(set(row) == set(audit.FIELDS) for row in data["receipts"])
    else:
        assert data["recipes"] == []  # Current profiles admit no dormant recipes.
        assert data["profile_code"] == "full_convention"


@pytest.mark.parametrize("after", [0, 1, 2])
@pytest.mark.parametrize("guard", ["purpose", "policy"])
def test_independent_initial_locked_and_final_denial(source, after, guard):
    check = getattr(source, guard)
    check.side_effect = [source.decision] * after + [
        ProgrammeAuthorizationDeniedError()
        if guard == "purpose"
        else replace(source.decision, allowed=False)
    ]
    with pytest.raises((ProgrammeAuthorizationDeniedError, PermissionDenied)):
        source.query(**source.args)
    source.audit.assert_not_called()
    if after < 2:
        source.owned.assert_not_called()


def test_each_independent_field_is_required(source):
    for field in source.module.FIELDS:
        source.policy.return_value = replace(
            source.decision, fields=source.decision.fields - {field}
        )
        with pytest.raises(PermissionDenied):
            source.query(**source.args)
    source.owned.assert_not_called()


@pytest.mark.parametrize("value", [True, None, "allow"])
def test_non_decision_never_admits_source(source, value):
    source.policy.return_value = value
    with pytest.raises(PermissionDenied):
        source.query(**source.args)
    source.owned.assert_not_called()


def test_audit_outage_withholds_bytes(source):
    source.audit.side_effect = RuntimeError("synthetic audit failure")
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        source.query(**source.args)


@pytest.mark.parametrize(
    "field", ["actor_id", "organization_id", "edition_id", "correlation_id"]
)
def test_invalid_scope_is_rejected_before_purpose_or_source(source, field):
    with pytest.raises(source.unavailable):
        source.query(**{**source.args, field: UUID(int=0)})
    source.purpose.assert_not_called()
    source.owned.assert_not_called()


def test_byte_ceiling_is_complete_or_unavailable(source, monkeypatch):
    monkeypatch.setattr(source.module, "MAX_EXIT_JSON_BYTES", 1)
    with pytest.raises(source.unavailable):
        source.query(**source.args)
    source.audit.assert_not_called()


def test_explicit_recipe_fields_and_unknown_admitted_definition(monkeypatch):
    recipe = next(iter(PROGRAMME_ROLE_RECIPES.values()))
    profile = SimpleNamespace(
        key=("synthetic", 1), catalog_entries={recipe.catalog_entry}
    )
    monkeypatch.setattr(authority, "adoption_profile", lambda *_: profile)
    result = authority._section("synthetic", 1)
    data = json.loads(result.data)
    Draft202012Validator(json.loads(result.schema)).validate(data)
    assert data["recipes"][0]["digest"] == recipe.digest
    assert set(data["recipes"][0]) == {
        "code",
        "version",
        "name",
        "purpose",
        "capability_codes",
        "target_scopes",
        "resource_kind",
        "digest",
    }
    profile.catalog_entries.add("authorization.programme_role.unknown@1")
    with pytest.raises(authority.ProgrammeExitAuthorizationUnavailableError):
        authority._section("synthetic", 1)


@pytest.mark.parametrize("kind", ["absent", "drift", "unknown"])
def test_profile_unavailable_or_changed_is_not_a_partial_archive(monkeypatch, kind):
    profile = (
        None
        if kind == "absent"
        else SimpleNamespace(key=("other", 2), catalog_entries=set())
    )
    monkeypatch.setattr(authority, "adoption_profile", lambda *_: profile)
    with pytest.raises(authority.ProgrammeExitAuthorizationUnavailableError):
        authority._section("synthetic", 1)


def test_every_owner_final_receipt_is_required():
    with pytest.raises(audit.ProgrammeExitAuditUnavailableError):
        audit._section(())
    rows = tuple(
        {
            "id": UUID(int=i),
            "occurred_at": datetime(2030, 1, 1, tzinfo=UTC),
            "capability_code": "synthetic",
            "operation": operation,
            "outcome": "allow",
        }
        for i, operation in enumerate(sorted(audit.GENERATION_OPERATIONS), 1)
    )
    for offset in range(len(rows)):
        with pytest.raises(audit.ProgrammeExitAuditUnavailableError):
            audit._section(rows[:offset] + rows[offset + 1 :])
