"""Canonical answer replay and fresh person-reference source fences."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from maru.applications import programme_commands as commands


@pytest.fixture
def writer(monkeypatch):
    scope = SimpleNamespace(relationship="lead")
    question = SimpleNamespace(
        id=UUID(int=6),
        key="person",
        field_type="person_reference",
        reference_kind="programme.person",
        classification="C2",
    )
    definition = SimpleNamespace(aggregate_version=2, version=1)
    proposal = SimpleNamespace(
        submission=SimpleNamespace(aggregate_version=7, definition_id=UUID(int=8)),
        call=SimpleNamespace(definition=definition),
    )
    state = SimpleNamespace(question=question, definition=definition, proposal=proposal)
    patches = {
        "_replay": Mock(return_value=None),
        "authorize_programme_proposal_scope": Mock(return_value=scope),
        "_require_private_writes": Mock(),
        "_locked_proposal": Mock(return_value=proposal),
        "_require_proposal_scope_match": Mock(),
        "_require_draft_edit_window": Mock(),
        "_latest_answer_map": Mock(return_value={}),
        "_question_is_applicable": Mock(return_value=True),
        "normalize_answer_value": Mock(side_effect=lambda **kw: kw["value"]),
        "resolve_active_verified_person_reference": Mock(
            return_value=SimpleNamespace(account_id=UUID(int=40))
        ),
        "programme_application_database_writer": nullcontext,
        "_advance_submission": Mock(),
        "_record_success": Mock(return_value="canonical-result"),
    }
    for name, value in patches.items():
        monkeypatch.setattr(commands, name, value)
        setattr(state, name.lstrip("_"), value)
    questions = Mock()
    questions.select_for_update.return_value.filter.return_value.first.return_value = (
        question
    )
    monkeypatch.setattr(commands.ApplicationQuestion, "objects", questions)
    answers = Mock()
    answers.filter.return_value.aggregate.return_value = {"maximum": 0}
    answers.create.return_value = SimpleNamespace(id=UUID(int=9))
    monkeypatch.setattr(commands.ApplicationAnswerRevision, "objects", answers)
    state.answers = answers
    return state


def append(**changes):
    return commands.append_programme_proposal_answer.__wrapped__.__wrapped__(
        **(
            {
                "actor_id": UUID(int=1),
                "organization_id": UUID(int=2),
                "edition_id": UUID(int=3),
                "proposal_id": UUID(int=4),
                "question_id": UUID(int=6),
                "value": str(UUID(int=40)),
                "expected_version": 7,
                "expected_call_version": 2,
                "expected_definition_version": 1,
                "reason": "Reference the known person",
                "retry_key": UUID(int=50),
                "correlation_id": UUID(int=51),
                "source_channel": "test-person-reference",
            }
            | changes
        )
    )


def test_fresh_person_answer_uses_owner_validation_then_sole_append_writer(writer):
    assert append() == "canonical-result"
    writer.resolve_active_verified_person_reference.assert_called_once_with(
        account_id=UUID(int=40)
    )
    assert writer.answers.create.call_args.kwargs["value"] == str(UUID(int=40))
    assert writer.answers.create.call_args.kwargs["resulting_version"] == 8
    writer.record_success.assert_called_once()


def test_explicit_clear_does_not_resolve_a_person(writer):
    assert append(value=None) == "canonical-result"
    writer.resolve_active_verified_person_reference.assert_not_called()
    assert writer.answers.create.call_args.kwargs["value"] is None


def test_inactive_or_unknown_person_rolls_back_before_answer_append(writer):
    writer.resolve_active_verified_person_reference.return_value = None
    with pytest.raises(commands.ApplicationsProgrammeUnavailableError):
        append()
    writer.answers.create.assert_not_called()
    writer.record_success.assert_not_called()


@pytest.mark.parametrize("value", [None, str(UUID(int=40))])
def test_unknown_registered_person_meaning_never_falls_back_to_uuid_shape(
    writer, value
):
    writer.question.reference_kind = "unknown.person"
    with pytest.raises(commands.ApplicationsProgrammeUnavailableError):
        append(value=value)
    writer.resolve_active_verified_person_reference.assert_not_called()
    writer.answers.create.assert_not_called()


@pytest.mark.parametrize("field", ["aggregate_version", "version"])
def test_call_and_schema_fences_run_inside_locked_fresh_command(writer, field):
    setattr(writer.definition, field, 99)
    with pytest.raises(commands.ApplicationsProgrammeVersionConflictError):
        append()
    writer.resolve_active_verified_person_reference.assert_not_called()
    writer.answers.create.assert_not_called()


@pytest.mark.parametrize(
    "values",
    [
        {"expected_call_version": None},
        {"expected_definition_version": None},
        {"expected_call_version": True},
        {"expected_definition_version": 0},
        {"expected_call_version": "2"},
        {"expected_call_version": 2**63},
    ],
)
def test_malformed_or_unpaired_fences_fail_before_replay_and_writes(writer, values):
    with pytest.raises(commands.ApplicationsProgrammeUnavailableError):
        append(**values)
    writer.replay.assert_not_called()
    writer.answers.create.assert_not_called()


def test_retained_success_precedes_fresh_person_and_call_validation(writer):
    writer.replay.return_value = "original-receipt"
    writer.definition.aggregate_version = 99
    writer.resolve_active_verified_person_reference.side_effect = AssertionError(
        "No fresh identity on replay"
    )
    assert append() == "original-receipt"
    writer.locked_proposal.assert_not_called()
    writer.answers.create.assert_not_called()


def test_original_optional_fences_are_in_digest_but_legacy_shape_is_unchanged(writer):
    writer.replay.return_value = "original-receipt"
    append()
    fenced = writer.replay.call_args.kwargs["request_digest"]
    append(expected_call_version=None, expected_definition_version=None)
    legacy = writer.replay.call_args.kwargs["request_digest"]
    assert legacy != fenced
    append(expected_call_version=3)
    assert writer.replay.call_args.kwargs["request_digest"] not in {legacy, fenced}
