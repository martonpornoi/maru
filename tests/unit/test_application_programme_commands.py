"""Database-free command contract coverage for Applications Programme."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.applications import programme_commands
from maru.applications.models import (
    ApplicationDefinitionStatus,
    ProgrammeCommandAction,
    ProgrammeContributorRole,
    ProgrammeProposalState,
)
from maru.applications.programme_authorization import (
    APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
    ApplicationsProgrammeAuthorizationDeniedError,
)
from maru.applications.programme_commands import (
    ApplicationsProgrammeCompletenessError,
    ApplicationsProgrammeStateConflictError,
)
from maru.applications.programme_inputs import (
    ProgrammeProposalContributorProfileInput,
)


def test_every_public_command_audits_outside_its_atomic_transaction() -> None:
    """Keep failure evidence outside the transaction it describes."""
    path = Path(programme_commands.__file__)
    module = ast.parse(path.read_text(encoding="utf-8"))
    functions = {
        node.name: node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    public_commands = {
        name
        for name in programme_commands.__all__
        if callable(getattr(programme_commands, name, None))
        and name.endswith(
            (
                "call",
                "reassignment",
                "retirement",
                "successor",
                "proposal",
                "selection",
                "answer",
                "profile",
                "collaborator",
                "invitation",
                "revision",
            )
        )
    }

    assert len(public_commands) == 23
    for name in public_commands:
        decorators = functions[name].decorator_list
        assert isinstance(decorators[0], ast.Call), name
        assert isinstance(decorators[0].func, ast.Name), name
        assert decorators[0].func.id == "_audit_command_errors", name
        assert isinstance(decorators[1], ast.Attribute), name
        assert decorators[1].attr == "atomic", name


@pytest.mark.parametrize(
    ("error", "outcome", "reason_code"),
    [
        (
            ApplicationsProgrammeAuthorizationDeniedError(),
            "deny",
            "applications_programme_authorization_denied",
        ),
        (
            ApplicationsProgrammeStateConflictError(),
            "error",
            "applications_programme_state_conflict",
        ),
        (
            ValidationError("Bad input.", code="applications_programme_text_invalid"),
            "error",
            "applications_programme_input_invalid",
        ),
        (
            ValidationError("Effect failed.", code="effect_profile_not_allowed"),
            "error",
            "applications_programme_dependency_error",
        ),
        (
            RuntimeError("database unavailable"),
            "error",
            "applications_programme_dependency_error",
        ),
    ],
)
def test_failure_audit_is_minimized_and_classified(
    monkeypatch,
    error: Exception,
    outcome: str,
    reason_code: str,
) -> None:
    """Retain no target or content identity when a command fails."""
    records = []
    monkeypatch.setattr(
        programme_commands,
        "append_audit",
        records.append,
    )

    def fail(**_kwargs: object) -> programme_commands.ProgrammeCommandResult:
        raise error

    wrapped = programme_commands._audit_command_errors(
        capability_code=APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
        operation=ProgrammeCommandAction.PROPOSAL_ANSWER_REVISED,
    )(fail)
    actor_id = uuid4()
    organization_id = uuid4()
    edition_id = uuid4()
    correlation_id = uuid4()

    with pytest.raises(type(error)):
        wrapped(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            proposal_id=uuid4(),
            correlation_id=correlation_id,
            source_channel="service",
        )

    assert len(records) == 1
    record = records[0]
    assert record.principal_id == actor_id
    assert record.organization_id == organization_id
    assert record.event_edition_id == edition_id
    assert record.outcome == outcome
    assert record.reason_code == reason_code
    assert record.target_type == "applications.programme.scope"
    assert record.target_id is None
    assert record.changed_fields == ()
    assert record.safe_metadata == {
        "policy_version": programme_commands.POLICY_VERSION,
    }


def test_recovery_failure_audit_is_marked_break_glass(monkeypatch) -> None:
    """Keep denied recovery attempts visibly distinct without target details."""
    records = []
    monkeypatch.setattr(programme_commands, "append_audit", records.append)

    def fail(**_kwargs: object) -> programme_commands.ProgrammeCommandResult:
        raise ApplicationsProgrammeAuthorizationDeniedError

    wrapped = programme_commands._audit_command_errors(
        capability_code="applications.recover_programme_department_ownership",
        operation=ProgrammeCommandAction.RECOVERY_CALL_RETIRED,
        break_glass=True,
    )(fail)

    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        wrapped(
            actor_id=uuid4(),
            organization_id=uuid4(),
            edition_id=uuid4(),
            call_id=uuid4(),
            correlation_id=uuid4(),
            source_channel="service",
        )

    assert len(records) == 1
    assert records[0].break_glass is True
    assert records[0].target_id is None


def test_failure_audit_normalizes_unsafe_identifiers_and_channel(monkeypatch) -> None:
    """Never copy malformed command input into retained failure evidence."""
    records = []
    monkeypatch.setattr(
        programme_commands,
        "append_audit",
        records.append,
    )

    programme_commands._append_failure_audit_best_effort(
        error=ValueError("bad request"),
        actor_id="not-a-uuid",
        organization_id="not-a-uuid",
        edition_id=object(),
        capability_code=APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
        operation=ProgrammeCommandAction.PROPOSAL_ANSWER_REVISED,
        correlation_id="not-a-uuid",
        source_channel="Bad channel containing content",
    )

    record = records[0]
    assert record.principal_id is None
    assert record.organization_id is None
    assert record.event_edition_id is None
    assert record.source_channel == "service"
    assert record.correlation_id is not None


def test_active_edit_window_is_inclusive_and_requires_active_call() -> None:
    """Allow work at the exact deadline but never after it or after retirement."""
    opens_at = datetime(2027, 1, 1, tzinfo=UTC)
    deadline = opens_at + timedelta(days=1)
    definition = SimpleNamespace(
        status=ApplicationDefinitionStatus.ACTIVE,
        opens_at=opens_at,
        applicant_edit_until=deadline,
    )
    call = SimpleNamespace(definition=definition)

    programme_commands._require_active_edit_window(
        call=call,
        effective_now=deadline,
    )
    with pytest.raises(ApplicationsProgrammeStateConflictError):
        programme_commands._require_active_edit_window(
            call=call,
            effective_now=deadline + timedelta(microseconds=1),
        )
    definition.status = ApplicationDefinitionStatus.RETIRED
    with pytest.raises(ApplicationsProgrammeStateConflictError):
        programme_commands._require_active_edit_window(
            call=call,
            effective_now=deadline,
        )


def test_hidden_profile_values_are_rejected_for_each_role() -> None:
    """Treat absent contributor-field configuration as hidden, not optional."""
    call = SimpleNamespace(
        contributor_consent_policy_code="programme.contributor-consent.v1",
        contributor_fields=SimpleNamespace(all=lambda: ()),
    )
    profile = ProgrammeProposalContributorProfileInput(
        public_name="Visible name",
        biography="",
        pronouns="",
        website="",
        proposed_for_publication=True,
        consent_acknowledged=True,
        consent_policy_code="programme.contributor-consent.v1",
    )

    for role in (ProgrammeContributorRole.LEAD, ProgrammeContributorRole.COLLABORATOR):
        with pytest.raises(ValidationError) as raised:
            programme_commands._require_profile_policy(
                call=call,
                profile=profile,
                role=role,
            )
        assert {
            error.code
            for errors in raised.value.error_dict.values()
            for error in errors
        } == {"applications_programme_hidden_profile_value"}


@pytest.mark.parametrize("blank", [None, "", [], {}])
def test_required_answer_blank_values_fail_before_snapshot(
    monkeypatch,
    blank: object,
) -> None:
    """Match the deferred database completeness guard with a stable domain error."""
    question = SimpleNamespace(key="title", required=True, condition={})
    answer = None if blank is None else SimpleNamespace(value=blank)
    monkeypatch.setattr(
        programme_commands,
        "_latest_answer_map",
        lambda **_kwargs: {} if answer is None else {"title": answer},
    )
    proposal = SimpleNamespace(
        submission=object(),
        call=SimpleNamespace(
            definition=SimpleNamespace(
                questions=SimpleNamespace(order_by=lambda *_args: (question,))
            )
        ),
        state=ProgrammeProposalState.DRAFT,
    )

    with pytest.raises(ApplicationsProgrammeCompletenessError):
        programme_commands._applicable_questions(
            proposal=proposal,
            through_version=1,
        )
