"""Exact-person intent, audited source admission and current/frozen label boundaries."""

from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.core import signing
from django.db import DatabaseError

from maru.applications import programme_person_references as refs
from maru.applications.programme_authorization import (
    APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
)
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from maru.applications.programme_commands import (
    ApplicationsProgrammeVersionConflictError,
)
from tests.unit import test_application_programme_personal_views as personal
from tests.unit.test_application_programme_personal_forms import question

page, shell, work = personal.page, personal.shell, personal.work


@pytest.fixture
def world(work, monkeypatch):
    answer = replace(
        work.answer, question=question("person_reference"), value=str(UUID(int=40))
    )
    work.source_detail = replace(work.source_detail, answers=(answer,))
    work.frozen = replace(work.frozen, answers=(answer,))
    work.answer = answer
    work.request = refs.ProgrammePersonReferenceRequest(
        work.actor,
        work.organization,
        work.edition,
        work.context.summary.proposal_id,
        answer.question.question_id,
        UUID(int=8),
        "test-person-reference",
    )
    work.intent = refs.ProgrammePersonReferenceIntent(
        work.context.summary.aggregate_version,
        work.context.call_version,
        work.context.definition_version,
        UUID(int=50),
    )
    work.person = Mock(return_value=SimpleNamespace(account_id=UUID(int=40)))
    work.labels = Mock(return_value={UUID(int=40): "Synthetic referenced person"})
    work.audit = Mock()
    monkeypatch.setattr(refs, "authorize_programme_proposal_scope", work.write_auth)
    monkeypatch.setattr(
        refs, "resolve_active_verified_person_reference_by_email", work.person
    )
    monkeypatch.setattr(
        refs, "active_verified_person_account_display_labels", work.labels
    )
    monkeypatch.setattr(refs, "_append_sensitive_read", work.audit)
    return work


def prepare(world, **changes):
    return refs.prepare_programme_person_selection.__wrapped__(
        **(
            {
                "request": world.request,
                "intent": world.intent,
                "email": "known@maru.invalid",
            }
            | changes
        )
    )


def read(world, token, **changes):
    return refs.read_programme_person_selection.__wrapped__(
        **(
            {
                "request": world.request,
                "intent": world.intent,
                "token": token,
            }
            | changes
        )
    )


def view(world, **changes):
    return refs.get_self_programme_person_reference.__wrapped__(
        request=world.request, **changes
    )


def test_prepare_binds_only_exact_ids_original_versions_and_retry(world):
    result = prepare(world)
    value = signing.loads(result.token, salt=refs._SALT)
    assert result.account_id == UUID(int=40)
    assert value == refs._binding(world.request) | {
        key: str(item) if isinstance(item, UUID) else item
        for key, item in asdict(world.intent).items()
    } | {"person": str(UUID(int=40))}
    assert "known@" not in str(value)
    assert "Synthetic" not in str(value)
    assert "known@" not in str(world.audit.call_args)
    assert "Synthetic referenced person" not in str(world.audit.call_args)
    assert (
        world.audit.call_args.kwargs["operation"]
        == "applications.programme.query.person_reference"
    )
    capabilities = [
        call.kwargs["capability_code"] for call in world.write_auth.call_args_list
    ]
    assert APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF in capabilities
    assert any(
        call.kwargs["requested_fields"] == frozenset({"proposal_summary", "answers"})
        for call in world.write_auth.call_args_list
    )


@pytest.mark.parametrize("missing", ["identity", "label"])
def test_all_unavailable_people_share_audited_empty_lookup(world, missing):
    if missing == "identity":
        world.person.return_value = None
    else:
        world.labels.return_value = {}
    assert prepare(world) is None
    world.audit.assert_called_once()
    if missing == "identity":
        world.labels.assert_not_called()


def test_explicit_clear_never_resolves_email_or_label(world):
    result = prepare(world, email=None)
    assert result.account_id is None
    assert read(world, result.token) == result
    world.person.assert_not_called()
    world.labels.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"expected_version": 99},
        {"expected_call_version": 99},
        {"expected_definition_version": 99},
    ],
)
def test_stale_original_source_rejects_before_known_person_lookup(world, change):
    with pytest.raises(ApplicationsProgrammeVersionConflictError):
        prepare(world, intent=replace(world.intent, **change))
    world.person.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"planning": False},
        {"call_status": "retired"},
        {"opens_at": personal.NOW + personal.timedelta(seconds=1)},
        {"edit_until": personal.NOW - personal.timedelta(seconds=1)},
    ],
)
def test_closed_edit_context_prevents_discovery(world, change):
    world.context = replace(world.context, **change)
    with pytest.raises(ApplicationsProgrammeVersionConflictError):
        prepare(world)
    world.person.assert_not_called()


@pytest.mark.parametrize("kind", ["domain_reference", "safe_file", "short_text"])
def test_same_kind_string_does_not_admit_another_reference_type(world, kind):
    world.source_detail = replace(
        world.source_detail,
        answers=(
            replace(
                world.answer, question=replace(world.answer.question, field_type=kind)
            ),
        ),
    )
    with pytest.raises(Denied):
        prepare(world)
    world.person.assert_not_called()


def test_unknown_person_kind_and_inapplicable_question_fail_before_lookup(world):
    world.source_detail = replace(world.source_detail, answers=())
    with pytest.raises(Denied):
        prepare(world)
    world.person.assert_not_called()


@pytest.mark.parametrize(
    "field", ["actor_id", "organization_id", "edition_id", "proposal_id", "question_id"]
)
def test_signed_selection_rejects_scope_rebinding_before_target_label(world, field):
    token = prepare(world).token
    world.labels.reset_mock()
    with pytest.raises(Denied):
        read(world, token, request=replace(world.request, **{field: UUID(int=9999)}))
    world.labels.assert_not_called()


@pytest.mark.parametrize(
    "token", ["", ".compressed", "a" * 2049, "é", "tampered:proof"]
)
def test_malformed_proofs_never_resolve_targets(world, token):
    with pytest.raises(Denied):
        read(world, token)
    world.labels.assert_not_called()


def test_retained_intent_survives_new_version_email_reassignment_and_inactive_person(
    world,
):
    selected = prepare(world)
    world.person.side_effect = AssertionError("Never resolve mutable email on retry")
    world.labels.return_value = {}
    world.context = replace(
        world.context, summary=replace(world.context.summary, aggregate_version=99)
    )
    retained = read(world, selected.token)
    assert retained.account_id == selected.account_id
    assert retained.intent == selected.intent
    assert not retained.person_current
    assert "original reference" in retained.display_label


@pytest.mark.parametrize(
    "change",
    [
        {"person": True},
        {"person": str(UUID(int=0))},
        {"expected_version": True},
        {"unexpected": "field"},
    ],
)
def test_even_signed_malformed_payload_has_no_target_resolution(world, change):
    token = prepare(world).token
    value = signing.loads(token, salt=refs._SALT) | change
    world.labels.reset_mock()
    with pytest.raises(Denied):
        read(world, signing.dumps(value, salt=refs._SALT))
    world.labels.assert_not_called()


def test_other_purpose_signature_cannot_be_used_as_person_answer_proof(world):
    token = prepare(world).token
    value = signing.loads(token, salt=refs._SALT)
    world.labels.reset_mock()
    with pytest.raises(Denied):
        read(
            world,
            signing.dumps(value, salt="applications.programme-reviewer-selection.v1"),
        )
    world.labels.assert_not_called()


@pytest.mark.parametrize("failure", ["read", "write", "audit"])
def test_required_authority_and_audit_fail_closed(world, failure):
    if failure == "audit":
        world.audit.side_effect = DatabaseError
        expected = DatabaseError
    else:
        original = world.write_auth.side_effect

        def authorize(**values):
            is_write = (
                values["capability_code"] == APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF
            )
            if is_write == (failure == "write"):
                raise Denied
            return original(**values)

        world.write_auth.side_effect = authorize
        expected = Denied
    with pytest.raises(expected):
        prepare(world)
    if failure != "audit":
        world.person.assert_not_called()


@pytest.mark.parametrize("frozen", [False, True])
def test_viewer_uses_only_actual_authorized_answer_and_current_minimal_label(
    world, frozen
):
    result = view(
        world, **({"revision_id": world.frozen.revision.revision_id} if frozen else {})
    )
    assert result.display_label == "Synthetic referenced person"
    assert result.present
    assert result.person_current
    world.person.assert_not_called()
    world.labels.assert_called_once_with((UUID(int=40),))


def test_frozen_viewer_never_rebases_to_current_answer(world):
    world.source_detail = replace(
        world.source_detail, answers=(replace(world.answer, value=str(UUID(int=41))),)
    )
    result = view(world, revision_id=world.frozen.revision.revision_id)
    assert result.display_label == "Synthetic referenced person"
    world.labels.assert_called_once_with((UUID(int=40),))


def test_changed_source_after_lookup_withholds_result(world):
    def labels(_ids):
        world.context = replace(
            world.context, summary=replace(world.context.summary, aggregate_version=90)
        )
        return {UUID(int=40): "Should not escape"}

    world.labels.side_effect = labels
    with pytest.raises(Denied):
        prepare(world)
