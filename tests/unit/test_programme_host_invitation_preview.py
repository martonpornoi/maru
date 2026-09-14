"""Exact invitation selection integrity and audited preparation without storage."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import DatabaseError

from maru.programme import host_invitation_preview as selections
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from tests.unit.test_programme_workbench_queries import query as query_fixture


@pytest.fixture
def selection(monkeypatch):
    base = query_fixture.__wrapped__(monkeypatch)
    base.admitted.accepts_private_planning_writes = True
    monkeypatch.setattr(selections, "authorize_programme_scope", base.auth)
    base.person_id = UUID(int=70)

    def resolve(**_kwargs):
        base.events.append("resolve")
        return SimpleNamespace(account_id=base.person_id)

    base.address = Mock(side_effect=resolve)
    monkeypatch.setattr(
        selections, "resolve_active_verified_person_reference_by_email", base.address
    )
    base.intent = selections.HostInvitationIntent(
        "river@example.test", 7, UUID(int=90), "host", "Invitation", "Brief", "Reason"
    )
    return base


def prepare(selection):
    return selections.prepare_host_invitation_preview(
        selection.scope, item_id=selection.item.id, intent=selection.intent
    )


def verify(selection, proof, **overrides):
    arguments = {
        "scope": selection.scope,
        "item_id": selection.item.id,
        "intent": selection.intent,
        "proof": proof,
    }
    return selections.verify_host_invitation_preview(**(arguments | overrides))


def test_preparation_is_locked_reauthorized_minimized_and_audited(selection):
    result = prepare(selection)
    assert selection.events == ["authorize", "lock", "resolve", "authorize", "audit"]
    selection.address.assert_called_once_with(email="river@example.test")
    record = selection.audit.call_args.args[0]
    assert record.target_id == selection.item.id
    assert record.safe_metadata["target_count"] == 1
    assert "river@example.test" not in repr(record)
    payload = signing.loads(result.proof, salt=selections._SALT)
    assert set(payload) == {"person_id", "intent"}
    assert payload["person_id"] == str(selection.person_id)
    assert len(payload["intent"]) == 64
    selection.address.reset_mock()
    assert verify(selection, result.proof) == result
    selection.address.assert_not_called()


@pytest.mark.parametrize("denial_at", [1, 2, 3])
def test_admission_revocation_returns_no_selection(selection, denial_at):
    selection.auth.side_effect = [selection.admitted] * (denial_at - 1) + [
        ProgrammeAuthorizationDeniedError
    ]
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        prepare(selection)
    if denial_at < 3:
        selection.address.assert_not_called()


def test_closed_planning_does_not_resolve_address(selection):
    selection.admitted.accepts_private_planning_writes = False
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        prepare(selection)
    selection.address.assert_not_called()


def test_audit_failure_releases_no_proof(selection):
    selection.audit.side_effect = DatabaseError("Synthetic audit failure")
    with pytest.raises(DatabaseError):
        prepare(selection)


@pytest.mark.parametrize(
    "changes",
    [
        {"recipient_email": "invalid"},
        {"recipient_email": "x" * 255},
        {"role": "owner"},
        {"title": ""},
        {"reason": ""},
        {"expected_version": 0},
        {"idempotency_key": "invalid"},
    ],
)
def test_invalid_complete_intent_is_rejected_before_lookup(selection, changes):
    selection.intent = replace(selection.intent, **changes)
    with pytest.raises(ValidationError):
        prepare(selection)
    selection.address.assert_not_called()


@pytest.mark.parametrize("field", ["actor_id", "organization_id", "edition_id"])
def test_proof_is_bound_to_principal_and_tenant(selection, field):
    proof = prepare(selection).proof
    with pytest.raises(ValidationError):
        verify(
            selection, proof, scope=replace(selection.scope, **{field: UUID(int=99)})
        )


def test_proof_binds_item_but_not_new_request_correlation(selection):
    proof = prepare(selection).proof
    with pytest.raises(ValidationError):
        verify(selection, proof, item_id=UUID(int=99))
    assert (
        verify(
            selection,
            proof,
            scope=replace(selection.scope, correlation_id=UUID(int=99)),
        ).person_id
        == selection.person_id
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"recipient_email": "other@example.test"},
        {"role": "co_host"},
        {"title": "Changed"},
        {"briefing": "Changed"},
        {"reason": "Changed"},
        {"expected_version": 8},
        {"idempotency_key": UUID(int=99)},
    ],
)
def test_each_original_intent_component_is_bound(selection, changes):
    proof = prepare(selection).proof
    with pytest.raises(ValidationError):
        verify(selection, proof, intent=replace(selection.intent, **changes))


@pytest.mark.parametrize(
    "payload", [None, [], {}, {"person_id": "invalid", "intent": "x"}]
)
def test_malformed_signed_payload_is_refused(selection, payload):
    with pytest.raises(ValidationError):
        verify(selection, signing.dumps(payload, salt=selections._SALT))


@pytest.mark.parametrize("kind", ["person", "extra", "purpose", "tamper", "oversize"])
def test_person_tampering_unknown_fields_and_wrong_purpose_fail(selection, kind):
    proof = prepare(selection).proof
    payload = signing.loads(proof, salt=selections._SALT)
    if kind == "person":
        payload["person_id"] = str(UUID(int=99))
    elif kind == "extra":
        payload["email"] = "river@example.test"
    proof = signing.dumps(
        payload, salt="other" if kind == "purpose" else selections._SALT
    )
    if kind == "tamper":
        proof += "x"
    elif kind == "oversize":
        proof = "x" * (selections.MAX_HOST_SELECTION_BYTES + 1)
    with pytest.raises(ValidationError):
        verify(selection, proof)


def test_configured_fallback_recovers_original_proof_without_age_expiry(
    selection, settings, monkeypatch
):
    settings.SECRET_KEY = "synthetic-original-key"
    with monkeypatch.context() as old_clock:
        old_clock.setattr(signing.time, "time", lambda: 1)
        proof = prepare(selection).proof
    settings.SECRET_KEY = "synthetic-rotated-key"
    settings.SECRET_KEY_FALLBACKS = ["synthetic-original-key"]
    assert verify(selection, proof).person_id == selection.person_id
    settings.SECRET_KEY_FALLBACKS = []
    with pytest.raises(ValidationError):
        verify(selection, proof)
