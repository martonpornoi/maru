"""Scope-before-input, field ceilings and audited Programme coverage release."""

from contextlib import nullcontext
from dataclasses import fields
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from maru.authorization.policy import PolicyDecision
from maru.events.adoption import profile_allows_adapter
from maru.workforce import programme_queries as queries
from maru.workforce.adoption import WORKFORCE_PROGRAMME_COVERAGE_ADAPTER
from maru.workforce.programme_coverage import StaffingCoverageIntegrityError


@pytest.fixture
def source_boundary(monkeypatch):
    decision = PolicyDecision(
        allowed=True,
        fields=queries.PROGRAMME_COVERAGE_FIELDS,
        obligations=frozenset(),
        reason_code="synthetic_exact_scope",
    )
    policy = MagicMock(return_value=decision)
    profile = MagicMock(return_value=SimpleNamespace(code="synthetic", version=1))
    adapter = MagicMock(return_value=True)
    loader = MagicMock(return_value=())
    audit = MagicMock()
    snapshot = MagicMock(side_effect=nullcontext)
    monkeypatch.setattr(queries, "decide_verified_principal_exact_edition", policy)
    monkeypatch.setattr(queries, "edition_adoption_profile_reference", profile)
    monkeypatch.setattr(queries, "profile_allows_adapter", adapter)
    monkeypatch.setattr(queries, "_load_counts", loader)
    monkeypatch.setattr(queries, "append_audit", audit)
    monkeypatch.setattr(queries, "repeatable_read_only_snapshot", snapshot)
    arguments = {
        "actor_id": uuid4(),
        "organization_id": uuid4(),
        "edition_id": uuid4(),
        "demand_ids": (uuid4(),),
        "correlation_id": uuid4(),
    }
    return SimpleNamespace(
        policy=policy,
        profile=profile,
        adapter=adapter,
        loader=loader,
        audit=audit,
        snapshot=snapshot,
        arguments=arguments,
        decision=decision,
    )


def test_current_profiles_do_not_activate_the_new_coverage_adapter():
    for code in ("full_convention", "workforce_only", "programme_operations"):
        assert not profile_allows_adapter(code, 1, WORKFORCE_PROGRAMME_COVERAGE_ADAPTER)


def test_source_checks_independent_fields_and_audits_before_release(source_boundary):
    boundary = source_boundary
    assert queries.load_programme_shift_coverage(**boundary.arguments) == ()
    assert boundary.policy.call_count == 3
    for call in boundary.policy.call_args_list:
        assert call.kwargs["capability_code"] == "workforce.view_shifts"
        assert call.kwargs["requested_fields"] == queries.PROGRAMME_COVERAGE_FIELDS
        assert "holder_display_labels" not in call.kwargs["requested_fields"]
        assert call.kwargs["organization_id"] == boundary.arguments["organization_id"]
        assert call.kwargs["edition_id"] == boundary.arguments["edition_id"]
    boundary.audit.assert_called_once()
    record = boundary.audit.call_args.args[0]
    assert record.operation == "workforce.programme_coverage.read"
    assert record.safe_metadata.keys() == {"policy_version"}
    assert "audit_sensitive_read" in record.obligations


@pytest.mark.parametrize("fields_allowed", [frozenset(), frozenset({"shift_demands"})])
def test_partial_field_authority_cannot_release_or_even_load_counts(
    source_boundary, fields_allowed
):
    boundary = source_boundary
    boundary.policy.return_value = PolicyDecision(
        allowed=True,
        fields=fields_allowed,
        obligations=frozenset(),
        reason_code="partial",
    )
    with pytest.raises(queries.ProgrammeCoverageDeniedError):
        queries.load_programme_shift_coverage(**boundary.arguments)
    boundary.profile.assert_not_called()
    boundary.loader.assert_not_called()
    boundary.audit.assert_not_called()


def test_denied_actor_cannot_probe_malformed_selection(source_boundary):
    boundary = source_boundary
    boundary.policy.return_value = PolicyDecision(
        allowed=False,
        fields=frozenset(),
        obligations=frozenset(),
        reason_code="denied",
    )
    boundary.arguments["demand_ids"] = object()
    with pytest.raises(queries.ProgrammeCoverageDeniedError):
        queries.load_programme_shift_coverage(**boundary.arguments)
    boundary.loader.assert_not_called()


@pytest.mark.parametrize("missing", ["profile", "adapter"])
def test_unknown_or_unpinned_profile_denies_before_read(source_boundary, missing):
    boundary = source_boundary
    getattr(boundary, missing).return_value = None
    with pytest.raises(queries.ProgrammeCoverageDeniedError):
        queries.load_programme_shift_coverage(**boundary.arguments)
    boundary.loader.assert_not_called()


def test_revocation_after_snapshot_withholds_previously_loaded_result(source_boundary):
    boundary = source_boundary
    boundary.policy.side_effect = [
        boundary.decision,
        boundary.decision,
        PolicyDecision(
            allowed=False,
            fields=frozenset(),
            obligations=frozenset(),
            reason_code="revoked",
        ),
    ]
    with pytest.raises(queries.ProgrammeCoverageDeniedError):
        queries.load_programme_shift_coverage(**boundary.arguments)
    boundary.loader.assert_called_once()
    boundary.audit.assert_not_called()


def test_audit_failure_does_not_return_a_successful_source(source_boundary):
    boundary = source_boundary
    boundary.audit.side_effect = RuntimeError("synthetic audit outage")
    with pytest.raises(RuntimeError, match="synthetic audit outage"):
        queries.load_programme_shift_coverage(**boundary.arguments)
    boundary.loader.assert_called_once()


@pytest.mark.parametrize(
    "selection", [(), [], ("not-an-id",), tuple(uuid4() for _ in range(1025))]
)
def test_invalid_or_overflowing_selection_never_starts_snapshot(
    source_boundary, selection
):
    boundary = source_boundary
    boundary.arguments["demand_ids"] = selection
    with pytest.raises(StaffingCoverageIntegrityError):
        queries.load_programme_shift_coverage(**boundary.arguments)
    boundary.snapshot.assert_not_called()


def test_duplicate_selection_is_not_silently_deduplicated(source_boundary):
    boundary = source_boundary
    target = uuid4()
    boundary.arguments["demand_ids"] = (target, target)
    with pytest.raises(StaffingCoverageIntegrityError):
        queries.load_programme_shift_coverage(**boundary.arguments)


def test_result_contract_cannot_carry_personnel_labels_or_private_rationale():
    assert {field.name for field in fields(queries.ProgrammeDemandCoverage)} == {
        "demand_id",
        "demand_version",
        "position_id",
        "starts_at",
        "ends_at",
        "evidence_digest",
        "coverage",
    }
