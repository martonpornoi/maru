"""Separate demand-work authority and final disclosure fencing for impact reads."""

from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from maru.authorization.policy import PolicyDecision
from maru.events.adoption import profile_allows_adapter
from maru.workforce import programme_staffing_queries as queries
from maru.workforce.adoption import WORKFORCE_PROGRAMME_STAFFING_ADAPTER


@pytest.fixture
def boundary(monkeypatch):
    decision = PolicyDecision(
        allowed=True,
        fields=queries.PROGRAMME_STAFFING_DEMAND_FIELDS,
        obligations=frozenset(),
        reason_code="synthetic",
    )
    policy = MagicMock(return_value=decision)
    profile = MagicMock(return_value=SimpleNamespace(code="synthetic", version=1))
    adapter = MagicMock(return_value=True)
    loader = MagicMock(return_value=object())
    audit = MagicMock()
    lock = MagicMock()
    monkeypatch.setattr(queries, "decide_verified_principal_exact_edition", policy)
    monkeypatch.setattr(queries, "edition_adoption_profile_reference", profile)
    monkeypatch.setattr(queries, "profile_allows_adapter", adapter)
    monkeypatch.setattr(queries, "_load_demand", loader)
    monkeypatch.setattr(queries, "append_audit", audit)
    monkeypatch.setattr(queries, "lock_programme_staffing_scope", lock)
    monkeypatch.setattr(queries.transaction, "atomic", nullcontext)
    arguments = {
        field: uuid4()
        for field in (
            "actor_id",
            "organization_id",
            "edition_id",
            "demand_id",
            "correlation_id",
        )
    }
    return SimpleNamespace(
        decision=decision,
        policy=policy,
        profile=profile,
        adapter=adapter,
        loader=loader,
        audit=audit,
        lock=lock,
        arguments=arguments,
    )


@pytest.mark.parametrize(
    "code", ["full_convention", "workforce_only", "programme_operations"]
)
def test_current_profiles_do_not_activate_staffing_work_adapter(code):
    assert not profile_allows_adapter(code, 1, WORKFORCE_PROGRAMME_STAFFING_ADAPTER)


def test_success_rechecks_independent_work_fields_and_audits_before_release(boundary):
    assert (
        queries.load_programme_staffing_demand(**boundary.arguments)
        is boundary.loader.return_value
    )
    assert boundary.policy.call_count == 3
    boundary.lock.assert_called_once()
    for call in boundary.policy.call_args_list:
        assert (
            call.kwargs["requested_fields"] == queries.PROGRAMME_STAFFING_DEMAND_FIELDS
        )
        assert call.kwargs["capability_code"] == "workforce.view_shifts"
    record = boundary.audit.call_args.args[0]
    assert record.target_id == boundary.arguments["demand_id"]
    assert record.safe_metadata.keys() == {"policy_version"}
    assert "audit_sensitive_read" in record.obligations


@pytest.mark.parametrize(
    "allowed_fields",
    [frozenset(), frozenset({"shift_demands"}), frozenset({"coverage_states"})],
)
def test_partial_fields_prevent_loading_work(boundary, allowed_fields):
    boundary.policy.return_value = replace(boundary.decision, fields=allowed_fields)
    with pytest.raises(queries.ProgrammeStaffingDeniedError):
        queries.load_programme_staffing_demand(**boundary.arguments)
    boundary.loader.assert_not_called()
    boundary.audit.assert_not_called()


@pytest.mark.parametrize("call_number", [1, 2, 3])
def test_revocation_at_every_admission_point_prevents_disclosure(boundary, call_number):
    boundary.policy.side_effect = [boundary.decision] * (call_number - 1) + [
        replace(boundary.decision, allowed=False)
    ]
    boundary.arguments["demand_id"] = object() if call_number == 1 else uuid4()
    with pytest.raises(queries.ProgrammeStaffingDeniedError):
        queries.load_programme_staffing_demand(**boundary.arguments)
    assert boundary.loader.call_count == (1 if call_number == 3 else 0)
    boundary.audit.assert_not_called()


@pytest.mark.parametrize("field", ["demand_id", "correlation_id"])
def test_malformed_input_after_admission_never_loads_work(boundary, field):
    boundary.arguments[field] = "not-uuid"
    with pytest.raises(queries.ProgrammeStaffingUnavailableError):
        queries.load_programme_staffing_demand(**boundary.arguments)
    boundary.loader.assert_not_called()


def test_write_authority_uses_its_own_capability_without_implicitly_granting_a_read(
    boundary,
):
    scope = {
        key: boundary.arguments[key]
        for key in ("actor_id", "organization_id", "edition_id")
    }
    boundary.policy.return_value = replace(boundary.decision, fields=frozenset())
    queries.authorize_programme_staffing_adapter(**scope, purpose="write")
    assert (
        boundary.policy.call_args.kwargs["capability_code"] == "workforce.manage_shifts"
    )
    assert boundary.policy.call_args.kwargs["requested_fields"] is None
    with pytest.raises(queries.ProgrammeStaffingDeniedError):
        queries.authorize_programme_staffing_adapter(**scope, purpose="read")
