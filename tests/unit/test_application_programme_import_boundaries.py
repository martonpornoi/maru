"""Boundary coverage for Programme import authority, evidence, and retention."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import connection as django_connection
from django.test import override_settings

from maru.applications import programme_import_authorization as import_authorization
from maru.applications import programme_import_commands
from maru.applications import programme_import_writer_boundary as writer_boundary
from maru.applications.programme_authorization import (
    APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
)
from maru.applications.programme_import_authorization import (
    APPLICATIONS_DISPOSE_PROGRAMME_IMPORT,
    APPLICATIONS_IMPORT_PROGRAMME,
    ApplicationsProgrammeImportAuthorizationDeniedError,
    ExactPolicyApplicationsProgrammeImportAuthorizer,
    authorize_programme_import_department_scope,
    authorize_programme_import_disposal_scope,
    authorize_programme_import_retry_scope,
    authorize_programme_import_self_scope,
    require_current_programme_import_owner,
)
from maru.applications.programme_import_events import (
    programme_import_changed_payload,
    validate_programme_import_changed_payload,
)
from maru.applications.programme_import_retention import (
    MAX_PROGRAMME_IMPORT_RETENTION_POLICY_BYTES,
    PROGRAMME_IMPORT_RETENTION_POLICY_SETTING,
    ConfiguredProgrammeImportRetentionPolicyProvider,
    ProgrammeImportRetentionConfigurationError,
)
from maru.authorization.policy import PolicyDecision
from maru.events.queries import PrivatePlanningEditionReference
from maru.identity.queries import ActiveVerifiedPersonReference
from maru.workforce.queries import CurrentDepartmentReference


@dataclass(frozen=True, slots=True)
class _ScopeIdentifiers:
    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    department_id: UUID


@dataclass(slots=True)
class _RecordingAuthorizer:
    granted_fields: frozenset[str] | None = None
    calls: list[tuple[str, str, frozenset[str] | None]] = field(
        default_factory=list,
    )

    def _decision(
        self,
        *,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        fields = (
            requested_fields if self.granted_fields is None else self.granted_fields
        )
        return PolicyDecision(
            allowed=True,
            fields=fields or frozenset(),
            obligations=frozenset({"audit"}),
            reason_code="programme_import_boundary_test",
        )

    def authorize_department(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        department_id: UUID,
        capability_code: str,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        del principal_id, organization_id, edition_id, department_id
        self.calls.append(("department", capability_code, requested_fields))
        return self._decision(requested_fields=requested_fields)

    def authorize_edition(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        capability_code: str,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        del principal_id, organization_id, edition_id
        self.calls.append(("edition", capability_code, requested_fields))
        return self._decision(requested_fields=requested_fields)

    def authorize_self(
        self,
        *,
        principal_id: UUID,
        owner_account_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        capability_code: str,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        assert principal_id == owner_account_id
        del organization_id, edition_id
        self.calls.append(("self", capability_code, requested_fields))
        return self._decision(requested_fields=requested_fields)

    def authorize_retry(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
    ) -> PolicyDecision:
        del principal_id, organization_id, edition_id
        self.calls.append(("retry", "", frozenset()))
        return self._decision(requested_fields=frozenset())


def _mount_scope_references(
    monkeypatch: pytest.MonkeyPatch,
    *,
    accepts_private_planning_writes: bool = True,
) -> _ScopeIdentifiers:
    identifiers = _ScopeIdentifiers(
        actor_id=uuid4(),
        organization_id=uuid4(),
        edition_id=uuid4(),
        department_id=uuid4(),
    )

    def resolve_actor(**_kwargs: object) -> ActiveVerifiedPersonReference:
        return ActiveVerifiedPersonReference(account_id=identifiers.actor_id)

    def resolve_edition(**_kwargs: object) -> PrivatePlanningEditionReference:
        return PrivatePlanningEditionReference(
            edition_id=identifiers.edition_id,
            organization_id=identifiers.organization_id,
            accepts_private_planning_writes=accepts_private_planning_writes,
        )

    def resolve_department(**_kwargs: object) -> CurrentDepartmentReference:
        return CurrentDepartmentReference(
            organization_id=identifiers.organization_id,
            edition_id=identifiers.edition_id,
            department_id=identifiers.department_id,
        )

    monkeypatch.setattr(
        import_authorization,
        "resolve_active_verified_person_reference",
        resolve_actor,
    )
    monkeypatch.setattr(
        import_authorization,
        "resolve_private_planning_edition_reference",
        resolve_edition,
    )
    monkeypatch.setattr(
        import_authorization,
        "resolve_current_department_reference",
        resolve_department,
    )
    monkeypatch.setitem(
        django_connection.settings_dict,
        "NAME",
        "test_programme_import_boundaries",
    )
    return identifiers


def _reviewed_policy(*, period_seconds: int = 37) -> str:
    return json.dumps(
        {
            "approved_at": "2026-09-01T08:00:00Z",
            "approved_by_reference": "privacy-review.2026-09",
            "period_seconds": period_seconds,
            "policy_code": "applications.programme-import-staging.v1",
        },
    )


def _mock_connection(
    *,
    in_atomic_block: bool,
    previous: str | None = None,
) -> SimpleNamespace:
    cursor = MagicMock()
    cursor.fetchone.return_value = (previous,)
    cursor_context = MagicMock()
    cursor_context.__enter__.return_value = cursor
    return SimpleNamespace(
        in_atomic_block=in_atomic_block,
        needs_rollback=False,
        cursor=MagicMock(return_value=cursor_context),
        _cursor=cursor,
    )


@pytest.mark.parametrize(
    ("import_adopted", "expected_allowed"),
    [(False, False), (True, True)],
)
def test_exact_department_authority_requires_only_import_adoption(
    monkeypatch: pytest.MonkeyPatch,
    *,
    import_adopted: bool,
    expected_allowed: bool,
) -> None:
    """Keep staging independent from the separately pinned target adapter."""
    expected = PolicyDecision(
        allowed=True,
        fields=frozenset({"preview"}),
        obligations=frozenset({"audit"}),
        reason_code="exact_department",
    )
    monkeypatch.setattr(
        import_authorization,
        "edition_adoption_profile_reference",
        lambda **_kwargs: SimpleNamespace(code="future", version=1),
    )
    monkeypatch.setattr(
        import_authorization,
        "profile_allows_application_programme_import",
        lambda *_args: import_adopted,
    )
    decide = MagicMock(return_value=expected)
    monkeypatch.setattr(
        import_authorization,
        "decide_verified_principal_exact_department",
        decide,
    )

    decision = ExactPolicyApplicationsProgrammeImportAuthorizer().authorize_department(
        principal_id=uuid4(),
        organization_id=uuid4(),
        edition_id=uuid4(),
        department_id=uuid4(),
        capability_code=APPLICATIONS_IMPORT_PROGRAMME,
        requested_fields=frozenset({"preview"}),
    )

    assert decision.allowed is expected_allowed
    assert decide.call_count == int(expected_allowed)


def test_department_scope_retains_exact_references_and_complete_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return only the resolved exact scope after a complete field decision."""
    identifiers = _mount_scope_references(monkeypatch)
    authorizer = _RecordingAuthorizer()

    with override_settings(
        MARU_ALLOW_APPLICATIONS_PROGRAMME_IMPORT_TEST_AUTHORIZER=True,
    ):
        scope = authorize_programme_import_department_scope(
            actor_id=identifiers.actor_id,
            organization_id=identifiers.organization_id,
            edition_id=identifiers.edition_id,
            department_id=identifiers.department_id,
            requested_fields=frozenset({"preview"}),
            authorizer=authorizer,
            lock=True,
        )

    assert scope.actor_id == identifiers.actor_id
    assert scope.organization_id == identifiers.organization_id
    assert scope.edition_id == identifiers.edition_id
    assert scope.department_id == identifiers.department_id
    assert scope.decision.fields == frozenset({"preview"})
    assert authorizer.calls == [
        ("department", APPLICATIONS_IMPORT_PROGRAMME, frozenset({"preview"})),
    ]


def test_department_scope_rejects_incomplete_field_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not reinterpret an allow decision as authority for omitted fields."""
    identifiers = _mount_scope_references(monkeypatch)
    authorizer = _RecordingAuthorizer(granted_fields=frozenset())

    with (
        override_settings(
            MARU_ALLOW_APPLICATIONS_PROGRAMME_IMPORT_TEST_AUTHORIZER=True,
        ),
        pytest.raises(ApplicationsProgrammeImportAuthorizationDeniedError),
    ):
        authorize_programme_import_department_scope(
            actor_id=identifiers.actor_id,
            organization_id=identifiers.organization_id,
            edition_id=identifiers.edition_id,
            department_id=identifiers.department_id,
            requested_fields=frozenset({"preview"}),
            authorizer=authorizer,
        )


def test_current_owner_guard_denies_a_retired_staging_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep exact-self staging reads closed after owner retirement."""
    resolver = MagicMock(return_value=None)
    monkeypatch.setattr(
        import_authorization,
        "resolve_current_department_reference",
        resolver,
    )
    organization_id = uuid4()
    edition_id = uuid4()
    department_id = uuid4()

    with pytest.raises(ApplicationsProgrammeImportAuthorizationDeniedError):
        require_current_programme_import_owner(
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=department_id,
            lock=True,
        )

    resolver.assert_called_once_with(
        organization_id=organization_id,
        edition_id=edition_id,
        department_id=department_id,
        lock=True,
    )


@pytest.mark.parametrize(
    ("allow_test_authorizer", "database_name"),
    [(False, "test_programme_import"), (True, "maru")],
)
def test_nondefault_authorizer_requires_both_isolated_test_guards(
    monkeypatch: pytest.MonkeyPatch,
    *,
    allow_test_authorizer: bool,
    database_name: str,
) -> None:
    """Reject a substituted policy adapter outside an explicit test database."""
    authorizer = _RecordingAuthorizer()
    monkeypatch.setitem(
        django_connection.settings_dict,
        "NAME",
        database_name,
    )

    with (
        override_settings(
            MARU_ALLOW_APPLICATIONS_PROGRAMME_IMPORT_TEST_AUTHORIZER=(
                allow_test_authorizer
            ),
        ),
        pytest.raises(ApplicationsProgrammeImportAuthorizationDeniedError),
    ):
        authorize_programme_import_retry_scope(
            actor_id=uuid4(),
            organization_id=uuid4(),
            edition_id=uuid4(),
            authorizer=authorizer,
        )

    assert authorizer.calls == []


@pytest.mark.parametrize(
    ("allow_test_provider", "database_name"),
    [(False, "test_programme_import"), (True, "maru")],
)
def test_nondefault_retention_provider_requires_both_isolated_test_guards(
    monkeypatch: pytest.MonkeyPatch,
    *,
    allow_test_provider: bool,
    database_name: str,
) -> None:
    """Prevent internal callers from replacing reviewed runtime retention."""
    monkeypatch.setitem(django_connection.settings_dict, "NAME", database_name)

    with (
        override_settings(
            MARU_ALLOW_APPLICATIONS_PROGRAMME_IMPORT_TEST_RETENTION_PROVIDER=(
                allow_test_provider
            ),
        ),
        pytest.raises(ApplicationsProgrammeImportAuthorizationDeniedError),
    ):
        programme_import_commands._require_retention_policy_provider(MagicMock())


def test_nondefault_retention_provider_is_available_only_in_isolated_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the injection seam usable for deterministic expiry tests only."""
    monkeypatch.setitem(
        django_connection.settings_dict,
        "NAME",
        "test_programme_import",
    )

    with override_settings(
        MARU_ALLOW_APPLICATIONS_PROGRAMME_IMPORT_TEST_RETENTION_PROVIDER=True,
    ):
        programme_import_commands._require_retention_policy_provider(MagicMock())


@pytest.mark.parametrize(
    ("allow_test_clock", "database_name"),
    [(False, "test_programme_import"), (True, "maru")],
)
def test_explicit_command_clock_requires_both_isolated_test_guards(
    monkeypatch: pytest.MonkeyPatch,
    *,
    allow_test_clock: bool,
    database_name: str,
) -> None:
    """Prevent callers from overriding the retention clock at runtime."""
    monkeypatch.setitem(django_connection.settings_dict, "NAME", database_name)

    with (
        override_settings(
            MARU_ALLOW_APPLICATIONS_PROGRAMME_IMPORT_TEST_CLOCK=allow_test_clock,
        ),
        pytest.raises(ApplicationsProgrammeImportAuthorizationDeniedError),
    ):
        programme_import_commands._effective_now(
            datetime(2027, 1, 1, tzinfo=UTC),
        )


def test_explicit_command_clock_is_available_only_in_isolated_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep deterministic retention time available to isolated tests only."""
    monkeypatch.setitem(
        django_connection.settings_dict,
        "NAME",
        "test_programme_import",
    )
    requested = datetime(2027, 1, 1, tzinfo=UTC)

    with override_settings(
        MARU_ALLOW_APPLICATIONS_PROGRAMME_IMPORT_TEST_CLOCK=True,
    ):
        assert programme_import_commands._effective_now(requested) == requested


def test_self_authority_requires_both_import_and_self_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep imported proposal self-rights narrower than import capability."""
    monkeypatch.setattr(
        import_authorization,
        "edition_adoption_profile_reference",
        lambda **_kwargs: SimpleNamespace(code="future", version=1),
    )
    monkeypatch.setattr(
        import_authorization,
        "profile_allows_application_programme_import",
        lambda *_args: True,
    )
    monkeypatch.setattr(
        import_authorization,
        "profile_allows_application_programme_self",
        lambda *_args: False,
    )
    decide = MagicMock()
    monkeypatch.setattr(
        import_authorization,
        "decide_verified_principal_exact_self",
        decide,
    )

    decision = ExactPolicyApplicationsProgrammeImportAuthorizer().authorize_self(
        principal_id=uuid4(),
        owner_account_id=uuid4(),
        organization_id=uuid4(),
        edition_id=uuid4(),
        capability_code=APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
        requested_fields=frozenset({"proposal_summary"}),
    )

    assert decision.allowed is False
    decide.assert_not_called()


def test_disposal_and_retry_do_not_require_department_or_planning_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve exact-edition continuity after planning writes stop."""
    identifiers = _mount_scope_references(
        monkeypatch,
        accepts_private_planning_writes=False,
    )
    authorizer = _RecordingAuthorizer()

    with override_settings(
        MARU_ALLOW_APPLICATIONS_PROGRAMME_IMPORT_TEST_AUTHORIZER=True,
    ):
        disposal = authorize_programme_import_disposal_scope(
            actor_id=identifiers.actor_id,
            organization_id=identifiers.organization_id,
            edition_id=identifiers.edition_id,
            authorizer=authorizer,
        )
        retry = authorize_programme_import_retry_scope(
            actor_id=identifiers.actor_id,
            organization_id=identifiers.organization_id,
            edition_id=identifiers.edition_id,
            authorizer=authorizer,
        )

    assert disposal.department_id is None
    assert disposal.accepts_private_planning_writes is False
    assert retry.department_id is None
    assert retry.accepts_private_planning_writes is False
    assert authorizer.calls == [
        ("edition", APPLICATIONS_DISPOSE_PROGRAMME_IMPORT, None),
        ("retry", "", frozenset()),
    ]


def test_self_scope_rejects_nonself_capability_before_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Admit only the two closed imported-proposal self capabilities."""
    authorizer = _RecordingAuthorizer()
    monkeypatch.setitem(
        django_connection.settings_dict,
        "NAME",
        "test_programme_import_boundaries",
    )

    with (
        override_settings(
            MARU_ALLOW_APPLICATIONS_PROGRAMME_IMPORT_TEST_AUTHORIZER=True,
        ),
        pytest.raises(ApplicationsProgrammeImportAuthorizationDeniedError),
    ):
        authorize_programme_import_self_scope(
            actor_id=uuid4(),
            organization_id=uuid4(),
            edition_id=uuid4(),
            capability_code=APPLICATIONS_IMPORT_PROGRAMME,
            authorizer=authorizer,
        )

    assert authorizer.calls == []


def test_writer_guard_is_context_local_and_restored_after_nesting() -> None:
    """Open and restore the in-process latch without leaking writer authority."""
    with pytest.raises(ValidationError) as before:
        writer_boundary.require_programme_import_writer()

    with writer_boundary.programme_import_writer():
        writer_boundary.require_programme_import_writer()
        with writer_boundary.programme_import_writer():
            writer_boundary.require_programme_import_writer()
        writer_boundary.require_programme_import_writer()

    with pytest.raises(ValidationError) as after:
        writer_boundary.require_programme_import_writer()
    assert before.value.code == "programme_import_writer_required"
    assert after.value.code == "programme_import_writer_required"


def test_database_writer_requires_an_atomic_transaction() -> None:
    """Never set a transaction-local database latch without a transaction."""
    connection = _mock_connection(in_atomic_block=False)

    with (
        patch.object(writer_boundary, "connection", connection),
        pytest.raises(RuntimeError, match="atomic transaction"),
        writer_boundary.programme_import_database_writer(),
    ):
        pytest.fail("The import writer must not open outside a transaction.")


def test_database_writer_sets_and_restores_exact_latch() -> None:
    """Restore the prior database-local setting and process guard on exit."""
    connection = _mock_connection(in_atomic_block=True, previous="prior")

    with patch.object(writer_boundary, "connection", connection):
        with writer_boundary.programme_import_database_writer():
            writer_boundary.require_programme_import_writer()
        with pytest.raises(ValidationError):
            writer_boundary.require_programme_import_writer()

    assert connection._cursor.execute.call_args_list == [
        (
            (
                "SELECT pg_catalog.current_setting(%s, true)",
                [writer_boundary.PROGRAMME_IMPORT_WRITER_SETTING],
            ),
        ),
        (
            (
                "SELECT pg_catalog.set_config(%s, 'on', true)",
                [writer_boundary.PROGRAMME_IMPORT_WRITER_SETTING],
            ),
        ),
        (
            (
                "SELECT pg_catalog.set_config(%s, %s, true)",
                [writer_boundary.PROGRAMME_IMPORT_WRITER_SETTING, "prior"],
            ),
        ),
    ]


def test_database_writer_does_not_restore_inside_broken_transaction() -> None:
    """Let the original database failure escape without masking it on cleanup."""
    connection = _mock_connection(in_atomic_block=True, previous="prior")

    def break_transaction() -> None:
        with writer_boundary.programme_import_database_writer():
            connection.needs_rollback = True
            raise LookupError("original integrity error")

    with (
        patch.object(writer_boundary, "connection", connection),
        pytest.raises(LookupError, match="original integrity error"),
    ):
        break_transaction()

    assert len(connection._cursor.execute.call_args_list) == 2


@pytest.mark.parametrize(
    "setting_value",
    [
        pytest.param(123, id="non-string"),
        pytest.param({"policy_code": "open"}, id="mapping"),
        pytest.param(
            "x" * (MAX_PROGRAMME_IMPORT_RETENTION_POLICY_BYTES + 1),
            id="oversized",
        ),
        pytest.param("\ud800", id="unicode-surrogate"),
    ],
)
def test_retention_rejects_nontext_and_oversized_configuration(
    setting_value: object,
) -> None:
    """Fail closed before parsing an unbounded or wrongly typed setting."""
    with (
        override_settings(
            **{PROGRAMME_IMPORT_RETENTION_POLICY_SETTING: setting_value},
        ),
        pytest.raises(ProgrammeImportRetentionConfigurationError),
    ):
        ConfiguredProgrammeImportRetentionPolicyProvider().resolve(
            staged_at=datetime(2026, 9, 1, tzinfo=UTC),
        )


def test_retention_rejects_naive_server_staging_instant() -> None:
    """Do not derive retention from a timezone-ambiguous server instant."""
    with (
        override_settings(
            **{PROGRAMME_IMPORT_RETENTION_POLICY_SETTING: _reviewed_policy()},
        ),
        pytest.raises(ProgrammeImportRetentionConfigurationError),
    ):
        ConfiguredProgrammeImportRetentionPolicyProvider().resolve(
            staged_at=datetime(2026, 9, 1),  # noqa: DTZ001 - intentional boundary
        )


def test_retention_uses_exact_reviewed_period_with_aware_offset() -> None:
    """Derive expiry from configured seconds without a runtime fallback."""
    staged_at = datetime(
        2026,
        9,
        1,
        12,
        tzinfo=timezone(timedelta(hours=2)),
    )
    with override_settings(
        **{PROGRAMME_IMPORT_RETENTION_POLICY_SETTING: _reviewed_policy()},
    ):
        decision = ConfiguredProgrammeImportRetentionPolicyProvider().resolve(
            staged_at=staged_at,
        )

    assert decision.expires_at == staged_at + timedelta(seconds=37)
    assert decision.expires_at.tzinfo == staged_at.tzinfo


def test_batch_only_event_uses_exact_absence_markers() -> None:
    """Represent no affected item without nulls or a private payload field."""
    payload = programme_import_changed_payload(
        action="batch_discarded",
        batch_id=uuid4(),
        batch_state="discarded",
        batch_version=2,
    )

    assert payload["item_id"] == ""
    assert payload["item_state"] == ""
    assert payload["item_version"] == 0
    assert not ({"source_key", "source_digest", "lead_email"} & set(payload))


def test_reassignment_event_accepts_a_monotonic_batch_version() -> None:
    """Allow ownership transfers to advance beyond the old v1/v2 shape."""
    payload = programme_import_changed_payload(
        action="batch_reassigned",
        batch_id=uuid4(),
        batch_state="staged",
        batch_version=7,
    )

    assert payload["action"] == "batch_reassigned"
    assert payload["batch_version"] == 7


@pytest.mark.parametrize(
    ("item_state", "item_version"),
    [("", 1), ("staged", 0)],
)
def test_event_rejects_inconsistent_item_absence_markers(
    *,
    item_state: str,
    item_version: int,
) -> None:
    """Keep an optional item identifier, state, and version all-or-none."""
    payload = programme_import_changed_payload(
        action="batch_staged",
        batch_id=uuid4(),
        batch_state="staged",
        batch_version=1,
    )
    payload["item_state"] = item_state
    payload["item_version"] = item_version

    with pytest.raises(ValidationError):
        validate_programme_import_changed_payload(payload)
