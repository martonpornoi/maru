"""Pure original-person signature boundaries; no identity or authority substitutes."""

from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from django.core import signing
from django.core.exceptions import ValidationError

from maru.workforce import programme_starter_selection as selection
from maru.workforce.programme_starter_inputs import ProgrammeStarterScope

ACTOR, APPROVER = UUID(int=1), UUID(int=2)
SCOPE = ProgrammeStarterScope(UUID(int=3), UUID(int=4), UUID(int=5))
DRAFT = selection.ProgrammeStarterDraft(
    "approver@example.invalid", "Synthetic staffing.", UUID(int=6)
)


def verify(proof, **changes):
    return selection.verify_programme_starter_selection(
        **(
            {"actor_id": ACTOR, "scope": SCOPE, "draft": DRAFT, "proof": proof}
            | changes
        )
    )


def test_original_signature_retains_selected_uuid_without_lookup():
    original = selection._sign_selection(ACTOR, SCOPE, DRAFT, APPROVER)
    assert verify(original.proof) == original
    assert original.details.approver_id == APPROVER


@pytest.mark.parametrize(
    "change",
    [
        {"actor_id": UUID(int=9)},
        {"scope": replace(SCOPE, organization_id=UUID(int=9))},
        {"scope": replace(SCOPE, series_id=UUID(int=9))},
        {"scope": replace(SCOPE, edition_id=UUID(int=9))},
        {"draft": replace(DRAFT, approver_email="different@example.invalid")},
        {"draft": replace(DRAFT, reason="Different.")},
        {"draft": replace(DRAFT, idempotency_key=UUID(int=9))},
    ],
)
def test_proof_cannot_cross_actor_scope_selector_terms_or_key(change):
    original = selection._sign_selection(ACTOR, SCOPE, DRAFT, APPROVER)
    with pytest.raises(ValidationError, match="original approver"):
        verify(original.proof, **change)


@pytest.mark.parametrize("proof", [None, "", "not-signed", "x" * 2049, "\ud800"])
def test_bounded_malformed_proof_is_non_disclosing(proof):
    with pytest.raises(ValidationError, match="original approver"):
        verify(proof)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"approver_id": str(APPROVER), "intent": "x", "extra": True},
        {"approver_id": "bad", "intent": "x"},
        {"approver_id": str(UUID(int=0)), "intent": "x"},
        {"approver_id": str(APPROVER), "intent": []},
    ],
)
def test_even_signed_payload_requires_closed_shape_and_matching_digest(payload):
    proof = signing.dumps(payload, salt=selection._SALT)
    with pytest.raises(ValidationError):
        verify(proof)


def test_other_purpose_and_self_approver_are_rejected():
    original = selection._sign_selection(ACTOR, SCOPE, DRAFT, APPROVER)
    payload = signing.loads(original.proof, salt=selection._SALT)
    with pytest.raises(ValidationError):
        verify(signing.dumps(payload, salt="another-purpose"))
    with pytest.raises(ValidationError, match="different person"):
        selection._sign_selection(ACTOR, SCOPE, DRAFT, ACTOR)


@pytest.mark.parametrize(
    "draft",
    [
        replace(DRAFT, approver_email="not-email"),
        replace(DRAFT, approver_email="x" * 255),
        replace(DRAFT, idempotency_key=UUID(int=0)),
    ],
)
def test_invalid_original_selector_and_key_do_not_get_a_signature(draft):
    with pytest.raises(ValidationError):
        selection._sign_selection(ACTOR, SCOPE, draft, uuid4())
