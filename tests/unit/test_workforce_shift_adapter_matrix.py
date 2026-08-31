"""Stable translation and strict-input contracts for Workforce Shift adapters."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.exceptions import ValidationError as ApiValidationError

from maru.identity.models import Account
from maru.workforce import shift_api, shift_views
from maru.workforce.shift_commands import (
    ShiftAuthorizationDeniedError,
    ShiftAvailabilityConflictError,
    ShiftCapacityConflictError,
    ShiftCommandError,
    ShiftCommitmentCommandResult,
    ShiftDemandCommandResult,
    ShiftLifecycleConflictError,
    ShiftOverlapConflictError,
    ShiftQualificationConflictError,
    ShiftRetryConflictError,
    ShiftStateConflictError,
    ShiftUnavailableError,
    ShiftVersionConflictError,
)


def test_idempotency_header_requires_one_canonical_uuid() -> None:
    valid_key = uuid4()

    assert shift_api._idempotency_key(
        SimpleNamespace(headers={"Idempotency-Key": str(valid_key)})
    ) == UUID(str(valid_key))
    for raw_value in (None, " ", "x" * 37, "not-a-uuid", str(valid_key).upper()):
        headers = {} if raw_value is None else {"Idempotency-Key": raw_value}
        with pytest.raises(ApiValidationError):
            shift_api._idempotency_key(SimpleNamespace(headers=headers))


def test_account_boundary_rejects_missing_or_inactive_maru_identity() -> None:
    active = Account(is_active=True)

    assert shift_api._account(SimpleNamespace(user=active)) is active
    for user in (SimpleNamespace(is_active=True), Account(is_active=False)):
        with pytest.raises(PermissionDenied, match="authority is unavailable"):
            shift_api._account(SimpleNamespace(user=user))


def test_personal_shift_scope_rejects_unknown_profile_before_policy_queries() -> None:
    """Fail closed on an unsupported exact pair before relationship discovery."""
    account = Account(is_active=True)
    edition = SimpleNamespace(
        adoption_profile_code="workforce_only",
        adoption_profile_version=2,
    )
    with (
        patch.object(shift_api, "_account", return_value=account),
        patch.object(shift_api, "_edition", return_value=edition),
        patch.object(shift_api, "resolve_self_target") as resolve_target,
        patch.object(shift_api, "decide") as decide,
        pytest.raises(PermissionDenied, match="personal Shift access"),
    ):
        shift_api._personal_scope(
            request=SimpleNamespace(),
            organization_id=uuid4(),
            edition_id=uuid4(),
            manage=False,
        )

    resolve_target.assert_not_called()
    decide.assert_not_called()


@pytest.mark.parametrize(
    ("error", "exception_type"),
    [
        (ShiftAuthorizationDeniedError(), PermissionDenied),
        (ShiftUnavailableError(), NotFound),
    ],
)
def test_command_translation_hides_undisclosable_targets(
    error: Exception,
    exception_type: type[Exception],
) -> None:
    with pytest.raises(exception_type):
        shift_api._raise_command_error(error)


@pytest.mark.parametrize(
    ("error", "field"),
    [
        (ShiftVersionConflictError(), "expected_version"),
        (ShiftRetryConflictError(), "Idempotency-Key"),
        (ShiftAvailabilityConflictError(), "non_field_errors"),
        (ShiftQualificationConflictError(), "non_field_errors"),
        (ShiftCapacityConflictError("No suitable places remain."), "non_field_errors"),
        (ShiftOverlapConflictError(), "non_field_errors"),
        (ShiftLifecycleConflictError(), "non_field_errors"),
        (ShiftStateConflictError("The Shift is already locked."), "non_field_errors"),
    ],
)
def test_command_translation_returns_stable_recovery_fields(
    error: ShiftCommandError,
    field: str,
) -> None:
    with pytest.raises(shift_api.WorkforceShiftConflict) as raised:
        shift_api._raise_command_error(error)

    detail = raised.value.detail
    assert str(detail["code"]) == error.reason_code
    assert field in detail["errors"]


def test_validation_translation_discloses_only_closed_shift_fields() -> None:
    with pytest.raises(ApiValidationError) as raised:
        shift_api._raise_command_error(
            DjangoValidationError(
                {
                    "title": ["Use a recognizable Shift name."],
                    "private_internal_field": ["Must never cross the adapter."],
                }
            )
        )

    assert set(raised.value.detail) == {"title"}
    with pytest.raises(shift_api.WorkforceShiftDependencyUnavailable):
        shift_api._raise_command_error(
            DjangoValidationError({"private_internal_field": ["hidden"]})
        )
    with pytest.raises(shift_api.WorkforceShiftDependencyUnavailable):
        shift_api._raise_command_error(DjangoValidationError("invalid state"))


@pytest.mark.parametrize(
    "error",
    [DatabaseError(), ShiftCommandError(), RuntimeError()],
)
def test_unclassified_operational_failures_fail_closed(error: Exception) -> None:
    with pytest.raises(shift_api.WorkforceShiftDependencyUnavailable):
        shift_api._raise_command_error(error)

    unexpected = ValueError("programmer defect")
    with pytest.raises(ValueError, match="programmer defect"):
        shift_api._raise_command_error(unexpected)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ShiftVersionConflictError(), "changed"),
        (ShiftRetryConflictError(), "retry key"),
        (ShiftAvailabilityConflictError(), "Availability"),
        (ShiftQualificationConflictError(), "Position assignment"),
        (ShiftCapacityConflictError("Coverage is full."), "Coverage is full."),
        (ShiftOverlapConflictError(), "overlap"),
        (ShiftLifecycleConflictError(), "read-only"),
        (ShiftStateConflictError("Already locked."), "Already locked."),
        (ShiftUnavailableError("No longer available."), "No longer available."),
        (DjangoValidationError("invalid"), "Review the submitted"),
    ],
)
def test_browser_conflicts_give_human_recovery_guidance(
    error: Exception,
    expected: str,
) -> None:
    assert expected in shift_views._shift_conflict_message(error)


def test_minimized_command_payloads_preserve_only_receipt_evidence() -> None:
    demand_id = uuid4()
    commitment_id = uuid4()
    demand_receipt_id = uuid4()
    commitment_receipt_id = uuid4()

    assert shift_api._demand_result_payload(
        ShiftDemandCommandResult(
            demand_id=demand_id,
            receipt_id=demand_receipt_id,
            resulting_version=2,
            status="open",
            replayed=False,
        )
    ) == {
        "id": demand_id,
        "receipt_id": demand_receipt_id,
        "resulting_version": 2,
        "status": "open",
        "replayed": False,
    }
    assert shift_api._commitment_result_payload(
        ShiftCommitmentCommandResult(
            commitment_id=commitment_id,
            demand_id=demand_id,
            receipt_id=commitment_receipt_id,
            resulting_version=3,
            status="confirmed",
            replayed=True,
        )
    ) == {
        "id": commitment_id,
        "demand_id": demand_id,
        "receipt_id": commitment_receipt_id,
        "resulting_version": 3,
        "status": "confirmed",
        "replayed": True,
    }
