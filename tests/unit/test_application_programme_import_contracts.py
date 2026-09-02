"""Focused contracts for dormant Programme import support modules."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings

from maru.applications import programme_import_commands
from maru.applications.adoption import APPLICATIONS_ADOPTION_ADAPTERS
from maru.applications.programme_adoption import (
    APPLICATION_PROGRAMME_IMPORT_ADAPTER,
    profile_allows_application_programme_import,
)
from maru.applications.programme_import_events import (
    programme_import_changed_payload,
    validate_programme_import_changed_payload,
)
from maru.applications.programme_import_retention import (
    MAX_PROGRAMME_IMPORT_STAGING_SECONDS,
    PROGRAMME_IMPORT_RETENTION_POLICY_SETTING,
    ConfiguredProgrammeImportRetentionPolicyProvider,
    ProgrammeImportRetentionConfigurationError,
)
from maru.settings import base as base_settings


def _policy(**overrides: object) -> str:
    values: dict[str, object] = {
        "approved_at": "2026-08-31T12:00:00Z",
        "approved_by_reference": "privacy-review.2026-08",
        "period_seconds": 86_400,
        "policy_code": "applications.programme-import-staging.v1",
    }
    values.update(overrides)
    return json.dumps(values)


def test_import_adapter_is_declared_but_not_pinned_by_current_profiles() -> None:
    """Catalog growth must not widen either exact current manifest."""

    descriptor = APPLICATIONS_ADOPTION_ADAPTERS[APPLICATION_PROGRAMME_IMPORT_ADAPTER]
    assert descriptor.owner_module == "applications"
    assert descriptor.kind == "preview-first-import"
    assert not profile_allows_application_programme_import("full_convention", 1)
    assert not profile_allows_application_programme_import("workforce_only", 1)


@pytest.mark.parametrize("source_channel", ["service.v1", "service:v1"])
def test_import_source_channel_matches_the_receipt_contract(
    source_channel: str,
) -> None:
    """Reject channel punctuation that persistence cannot retain."""

    with pytest.raises(ValidationError):
        programme_import_commands._normalize_source_channel(source_channel)


def test_retention_provider_has_no_default_duration() -> None:
    """Staging fails closed when deployment policy is absent."""

    with (
        override_settings(
            **{PROGRAMME_IMPORT_RETENTION_POLICY_SETTING: ""},
        ),
        pytest.raises(ProgrammeImportRetentionConfigurationError),
    ):
        ConfiguredProgrammeImportRetentionPolicyProvider().resolve(
            staged_at=datetime(2026, 9, 1, tzinfo=UTC)
        )


def test_retention_setting_is_wired_from_the_exact_environment_name() -> None:
    """Expose the fail-closed deployment setting through shared base settings."""

    assert os.environ.get(PROGRAMME_IMPORT_RETENTION_POLICY_SETTING, "") == (
        base_settings.MARU_APPLICATIONS_PROGRAMME_IMPORT_RETENTION_POLICY_JSON
    )


def test_retention_provider_derives_expiry_from_reviewed_configuration() -> None:
    """The configured duration is applied to the server-owned staging time."""

    staged_at = datetime(2026, 9, 1, tzinfo=UTC)
    with override_settings(
        **{PROGRAMME_IMPORT_RETENTION_POLICY_SETTING: _policy()},
    ):
        decision = ConfiguredProgrammeImportRetentionPolicyProvider().resolve(
            staged_at=staged_at
        )
    assert decision.policy_code == "applications.programme-import-staging.v1"
    assert decision.expires_at == staged_at + timedelta(days=1)


def test_retention_provider_accepts_the_exact_one_year_ceiling() -> None:
    """Keep the reviewed lifetime closed at the documented maximum."""

    staged_at = datetime(2026, 9, 1, tzinfo=UTC)
    with override_settings(
        **{
            PROGRAMME_IMPORT_RETENTION_POLICY_SETTING: _policy(
                period_seconds=MAX_PROGRAMME_IMPORT_STAGING_SECONDS,
            )
        },
    ):
        decision = ConfiguredProgrammeImportRetentionPolicyProvider().resolve(
            staged_at=staged_at
        )

    assert decision.expires_at == staged_at + timedelta(
        seconds=MAX_PROGRAMME_IMPORT_STAGING_SECONDS
    )


@pytest.mark.parametrize(
    "raw",
    [
        '{"policy_code":"applications.programme-import-staging.v1",'
        '"policy_code":"applications.programme-import-staging.v2",'
        '"period_seconds":1,"approved_by_reference":"review.v1",'
        '"approved_at":"2026-08-31T00:00:00Z"}',
        _policy(period_seconds=0),
        _policy(period_seconds=True),
        _policy(period_seconds=MAX_PROGRAMME_IMPORT_STAGING_SECONDS + 1),
        _policy(approved_at="2026-09-02T00:00:00Z"),
        _policy(approved_at="2026-08-31T12:00:00"),
        _policy(approved_at="not-an-instant"),
        _policy(approved_by_reference="1invalid-review"),
        _policy(policy_code="1invalid-policy"),
        _policy(policy_code="applications/programme-import@v1"),
        _policy(extra="not-closed"),
    ],
)
def test_retention_provider_rejects_ambiguous_or_unreviewed_policy(raw: str) -> None:
    """Duplicate, unknown, future, and out-of-range policy facts fail closed."""

    with (
        override_settings(**{PROGRAMME_IMPORT_RETENTION_POLICY_SETTING: raw}),
        pytest.raises(ProgrammeImportRetentionConfigurationError),
    ):
        ConfiguredProgrammeImportRetentionPolicyProvider().resolve(
            staged_at=datetime(2026, 9, 1, tzinfo=UTC)
        )


def test_import_event_is_minimized_and_closed() -> None:
    """Event payloads contain only stable state and opaque identifiers."""

    payload = programme_import_changed_payload(
        action="call_committed",
        batch_id=uuid4(),
        batch_state="staged",
        batch_version=1,
        item_id=uuid4(),
        item_state="applied",
        item_version=2,
    )
    validate_programme_import_changed_payload(payload)
    assert set(payload) == {
        "action",
        "batch_id",
        "batch_state",
        "batch_version",
        "item_id",
        "item_state",
        "item_version",
    }
    assert not ({"email", "payload", "digest", "reason"} & set(payload))


def test_import_event_rejects_extra_or_inconsistent_values() -> None:
    """No source value can be smuggled through an unregistered event field."""

    payload = programme_import_changed_payload(
        action="batch_staged",
        batch_id=uuid4(),
        batch_state="staged",
        batch_version=1,
    )
    payload["lead_email"] = "private@example.invalid"
    with pytest.raises(ValidationError):
        validate_programme_import_changed_payload(payload)
