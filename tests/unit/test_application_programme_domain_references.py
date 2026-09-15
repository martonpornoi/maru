"""Exact-question domain choices, signed retry identity and same-call viewers."""

from dataclasses import asdict, replace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.core import signing
from django.db import DatabaseError

from maru.applications import programme_domain_references as refs
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from maru.applications.programme_commands import (
    ApplicationsProgrammeVersionConflictError as Conflict,
)
from maru.applications.programme_domain_targets import ProgrammeDomainOption
from tests.unit import test_application_programme_person_references as person

page, shell, work = person.page, person.shell, person.work


@pytest.fixture
def world(work, monkeypatch):
    world = person.world.__wrapped__(work, monkeypatch)
    world.answer = replace(
        world.answer,
        question=replace(
            world.answer.question,
            field_type="domain_reference",
            reference_kind="programme.call-track",
        ),
    )
    world.source_detail = replace(world.source_detail, answers=(world.answer,))
    world.frozen = replace(world.frozen, answers=(world.answer,))
    world.option = ProgrammeDomainOption(
        UUID(int=40), "culture", "Culture", "Other suitable topic"
    )
    world.options = Mock(return_value=(world.option,))
    world.target = Mock(return_value=world.option)
    world.domain_audit = Mock()
    monkeypatch.setattr(refs, "_domain_options", world.options)
    monkeypatch.setattr(refs, "_domain_target", world.target)
    monkeypatch.setattr(refs, "_append_sensitive_read", world.domain_audit)
    for name in (
        "get_programme_domain_choices",
        "prepare_programme_domain_selection",
        "read_programme_domain_selection",
        "get_self_programme_domain_reference",
    ):
        monkeypatch.setattr(refs, name, getattr(refs, name).__wrapped__)
    return world


def prepare(world, **changes):
    return refs.prepare_programme_domain_selection(
        **{
            "request": world.request,
            "intent": world.intent,
            "target_id": world.option.target_id,
        }
        | changes
    )


def read(world, token, **changes):
    return refs.read_programme_domain_selection(
        **{
            "request": world.request,
            "intent": world.intent,
            "token": token,
        }
        | changes
    )


def view(world, **changes):
    return refs.get_self_programme_domain_reference(request=world.request, **changes)


@pytest.mark.parametrize("kind", ["programme.call-track", "programme.call-format"])
def test_same_call_choices_bind_original_target_without_identity_or_relationship(
    world, kind
):
    world.answer = replace(
        world.answer, question=replace(world.answer.question, reference_kind=kind)
    )
    world.source_detail = replace(world.source_detail, answers=(world.answer,))
    selected = prepare(world)
    assert selected.kind == kind
    assert selected.option == world.option
    payload = signing.loads(selected.token, salt=refs._SALT)
    assert payload == refs._binding(world.request) | {
        name: str(value) if isinstance(value, UUID) else value
        for name, value in asdict(world.intent).items()
    } | {
        "target": str(world.option.target_id),
        "kind": kind,
        "call": str(world.context.summary.call_id),
    }
    assert "Other suitable topic" not in selected.token
    assert read(world, selected.token) == selected
    assert world.options.call_args.kwargs == {
        "organization_id": world.organization,
        "edition_id": world.edition,
        "call_id": world.context.summary.call_id,
        "kind": kind,
    }
    world.person.assert_not_called()
    world.labels.assert_not_called()
    assert world.domain_audit.call_count == 2


def test_collaborator_receives_only_dedicated_question_catalog(world):
    world.context = replace(
        world.context,
        tracks=(),
        formats=(),
        summary=replace(world.context.summary, relationship="collaborator"),
    )
    world.source_detail = replace(world.source_detail, summary=world.context.summary)
    # Existing owner fixture derives authorization from this current scope.
    choices = refs.get_programme_domain_choices(
        request=world.request, intent=world.intent
    )
    assert choices.options == (world.option,)
    assert choices.source[0].tracks == ()
    assert choices.source[0].formats == ()


def test_clear_is_explicit_without_target_lookup(world):
    selected = prepare(world, target_id=None)
    assert selected.target_id is None
    assert selected.option is None
    assert read(world, selected.token) == selected
    world.target.assert_not_called()


@pytest.mark.parametrize(
    ("field", "value"),
    [("field_type", "person_reference"), ("reference_kind", "other.domain")],
)
def test_unknown_meaning_never_reads_any_catalog(world, field, value):
    world.answer = replace(
        world.answer, question=replace(world.answer.question, **{field: value})
    )
    world.source_detail = replace(world.source_detail, answers=(world.answer,))
    with pytest.raises(Denied):
        prepare(world)
    world.options.assert_not_called()
    world.target.assert_not_called()


def test_foreign_target_cannot_be_prepared(world):
    with pytest.raises(Denied):
        prepare(world, target_id=UUID(int=999))
    world.target.assert_not_called()


def test_stale_preparation_never_loads_target_catalog(world):
    with pytest.raises(Conflict):
        prepare(world, intent=replace(world.intent, expected_call_version=999))
    world.options.assert_not_called()


def test_denied_editor_never_loads_catalog(world):
    world.write_auth.side_effect = Denied
    with pytest.raises(Denied):
        prepare(world)
    world.options.assert_not_called()


def test_catalog_change_is_withheld_even_when_base_owner_projection_is_unchanged(world):
    world.options.side_effect = [
        (world.option,),
        (replace(world.option, label="Changed"),),
    ]
    with pytest.raises(Denied):
        prepare(world)
    world.domain_audit.assert_not_called()


def test_required_audit_failure_prevents_selection_disclosure(world):
    world.domain_audit.side_effect = DatabaseError
    with pytest.raises(DatabaseError):
        prepare(world)


@pytest.mark.parametrize(
    "field", ["actor_id", "organization_id", "edition_id", "proposal_id", "question_id"]
)
def test_original_proof_is_bound_to_every_answer_scope(world, field):
    selected = prepare(world)
    with pytest.raises(Denied):
        read(
            world,
            selected.token,
            request=replace(world.request, **{field: UUID(int=888)}),
        )
    world.target.assert_not_called()


@pytest.mark.parametrize(
    "field",
    [
        "expected_version",
        "expected_call_version",
        "expected_definition_version",
        "retry_key",
    ],
)
def test_original_proof_cannot_be_rebased(world, field):
    selected = prepare(world)
    replacement = UUID(int=888) if field == "retry_key" else 99
    with pytest.raises(Denied):
        read(
            world, selected.token, intent=replace(world.intent, **{field: replacement})
        )
    world.target.assert_not_called()


@pytest.mark.parametrize("token", ["", "bad", ".compressed", "x" * 2301, "é"])
def test_malformed_proof_never_resolves_a_target(world, token):
    with pytest.raises(Denied):
        read(world, token)
    world.target.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"target": "not-uuid"},
        {"target": str(UUID(int=0))},
        {"kind": "other.kind"},
        {"call": str(UUID(int=999))},
        {"extra": "forbidden"},
        {"expected_version": True},
    ],
)
def test_signed_but_invalid_payload_is_not_target_authority(world, change):
    selected = prepare(world)
    payload = signing.loads(selected.token, salt=refs._SALT) | change
    with pytest.raises(Denied):
        read(world, signing.dumps(payload, salt=refs._SALT))
    world.target.assert_not_called()


def test_other_purpose_proof_is_rejected(world):
    selected = prepare(world)
    payload = signing.loads(selected.token, salt=refs._SALT)
    with pytest.raises(Denied):
        read(world, signing.dumps(payload, salt=person.refs._SALT))


def test_retained_intent_reads_original_target_after_aggregate_change(world):
    selected = prepare(world)
    world.context = replace(
        world.context, summary=replace(world.context.summary, aggregate_version=2)
    )
    world.source_detail = replace(world.source_detail, summary=world.context.summary)
    world.target.return_value = None
    retained = read(world, selected.token)
    assert retained.intent == selected.intent
    assert retained.target_id == selected.target_id
    assert retained.option is None


@pytest.mark.parametrize("frozen", [False, True])
def test_viewer_derives_target_only_from_authorized_actual_answer(world, frozen):
    result = view(
        world, **({"revision_id": world.frozen.revision.revision_id} if frozen else {})
    )
    assert result.option == world.option
    assert result.present is True
    assert world.target.call_args.kwargs["target_id"] == world.option.target_id
    assert world.target.call_args.kwargs["call_id"] == world.context.summary.call_id
    world.person.assert_not_called()
    world.labels.assert_not_called()


def test_unavailable_target_keeps_neutral_retained_history(world):
    world.target.return_value = None
    result = view(world)
    assert result.present
    assert result.option is None


def test_absent_answer_does_not_resolve_any_target(world):
    world.source_detail = replace(
        world.source_detail, answers=(replace(world.answer, value=None),)
    )
    assert not view(world).present
    world.target.assert_not_called()


@pytest.mark.parametrize(
    "value",
    [42, "garbage", str(UUID(int=0)), str(UUID(int=40)).upper().replace("0", "A", 1)],
)
def test_malformed_historical_reference_does_not_probe_a_catalog(world, value):
    world.source_detail = replace(
        world.source_detail, answers=(replace(world.answer, value=value),)
    )
    with pytest.raises(Denied):
        view(world)
    world.target.assert_not_called()
