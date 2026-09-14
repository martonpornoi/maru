"""Exact signed intent, independent readiness and private preview boundaries."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.core import signing
from django.core.exceptions import ValidationError
from django.test import override_settings

from maru.applications import programme_decider_preview as previews
from maru.applications import programme_decider_queries as queries
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from maru.applications.programme_review_authorization import DECIDE
from maru.applications.programme_review_queries import ProgrammeReviewDetail
from maru.applications.programme_review_rules import ProgrammeReviewConflictError
from tests.unit.test_application_programme_review_inputs import review_policy
from tests.unit.test_application_programme_review_management_views import (
    context as manager_context,
)
from tests.unit.test_application_programme_reviewer_selection import (
    request as manager_request,
)


def request(**changes):
    return replace(manager_request(), **({"capability_code": DECIDE} | changes))


def work(**changes):
    policy = review_policy()
    policy = replace(
        policy, stages=(*policy.stages, replace(policy.stages[0], code="quality"))
    )
    return replace(
        queries.DecisionWork(
            manager_context().case,
            policy,
            ProgrammeReviewDetail(UUID(int=20), 5, "{}", None, None, None),
            writable=True,
        ),
        **changes,
    )


def evidence(**changes):
    return replace(
        queries.DecisionEvidence(
            ProgrammeReviewDetail(UUID(int=20), 5, None, None, "[]", None),
            tuple(
                queries.DecisionStage(stage.code, 2, 2, ready=True)
                for stage in work().policy.stages
            ),
        ),
        **changes,
    )


def intent(**changes):
    return replace(
        previews.DecisionIntent(
            5, UUID(int=60), "accepted", "Recipient explanation", "Private rationale"
        ),
        **changes,
    )


@pytest.fixture
def world(monkeypatch):
    source, facts, audit = (
        Mock(return_value=work()),
        Mock(return_value=evidence()),
        Mock(),
    )
    monkeypatch.setattr(previews, "get_programme_decision_work", source)
    monkeypatch.setattr(previews, "get_programme_decision_evidence", facts)
    monkeypatch.setattr(previews, "_audit", audit)
    return SimpleNamespace(source=source, facts=facts, audit=audit)


def prepare(**changes):
    return previews.prepare_programme_decision_preview.__wrapped__(
        **(
            {"request": request(), "case_id": UUID(int=20), "intent": intent()}
            | changes
        )
    )


def verify(proof, **changes):
    return previews.verify_programme_decision_preview(
        **(
            {
                "request": request(),
                "case_id": UUID(int=20),
                "intent": intent(),
                "proof": proof,
            }
            | changes
        )
    )


def test_exact_message_and_digest_only_proof_keep_rationale_private(world):
    result = prepare()
    assert result.message == "Programme decision: accepted.\n\nRecipient explanation"
    assert result.intent.reason not in result.message
    assert result.template.acknowledgement_required
    payload = signing.loads(result.proof, salt=previews._SALT)
    assert set(payload) == {"intent"}
    assert len(payload["intent"]) == 64
    assert result.intent.text not in str(payload)
    assert result.intent.reason not in str(payload)
    assert world.source.call_args.kwargs["request"].requested_fields == frozenset(
        {"review_context"}
    )
    assert world.facts.call_args.kwargs["request"].requested_fields == frozenset(
        {"review_evidence"}
    )
    world.audit.assert_called_once()
    world.source.reset_mock()
    world.facts.reset_mock()
    world.audit.reset_mock()
    assert verify(result.proof) == intent()
    world.source.assert_not_called()
    world.facts.assert_not_called()
    world.audit.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"version": 6},
        {"current_revision": False},
        {"stage": 0},
        {"state": "accepted"},
        {"state": "rejected"},
        {"state": "revision_requested"},
    ],
)
def test_stale_or_final_case_cannot_preview(world, change):
    world.source.return_value = work(case=replace(work().case, **change))
    with pytest.raises(ProgrammeReviewConflictError):
        prepare()
    world.audit.assert_not_called()


def test_readonly_and_any_incomplete_stage_cannot_preview(world):
    world.source.return_value = work(writable=False)
    with pytest.raises(ProgrammeReviewConflictError):
        prepare()
    world.source.return_value = work()
    world.facts.return_value = evidence(
        stages=(replace(evidence().stages[0], ready=False), evidence().stages[1])
    )
    with pytest.raises(ProgrammeReviewConflictError):
        prepare()
    world.facts.return_value = evidence(stages=evidence().stages[1:])
    with pytest.raises(ProgrammeReviewConflictError):
        prepare()
    world.facts.return_value = evidence(detail=replace(evidence().detail, version=6))
    with pytest.raises(ProgrammeReviewConflictError):
        prepare()


@pytest.mark.parametrize(
    "outcome", ["accepted", "rejected", "revision_requested", "waitlisted"]
)
def test_waitlist_successors_are_explicit_and_cannot_repeat_waitlist(world, outcome):
    world.source.return_value = work(case=replace(work().case, state="waitlisted"))
    if outcome == "waitlisted":
        with pytest.raises(ProgrammeReviewConflictError):
            prepare(intent=intent(outcome=outcome))
    else:
        assert prepare(intent=intent(outcome=outcome)).template.outcome == outcome


@pytest.mark.parametrize("field", ["source", "facts", "audit"])
def test_missing_private_authority_or_failed_audit_releases_no_preview(world, field):
    getattr(world, field).side_effect = Denied
    with pytest.raises(Denied):
        prepare()


@pytest.mark.parametrize(
    "field", ["actor_id", "organization_id", "edition_id", "department_id"]
)
def test_signature_binds_every_scope_identifier(world, field):
    with pytest.raises(ValidationError):
        verify(prepare().proof, request=request(**{field: UUID(int=99)}))


@pytest.mark.parametrize(
    "change",
    [
        {"expected_version": 6},
        {"retry_key": UUID(int=61)},
        {"outcome": "rejected"},
        {"text": "Different recipient text"},
        {"reason": "Different private reason"},
    ],
)
def test_signature_binds_every_original_intent_field(world, change):
    with pytest.raises(ValidationError):
        verify(prepare().proof, intent=intent(**change))


def test_signature_binds_case_and_purpose(world):
    proof = prepare().proof
    with pytest.raises(ValidationError):
        verify(proof, case_id=UUID(int=21))
    with pytest.raises(Denied):
        verify(
            proof, request=request(capability_code="applications.moderate_programme")
        )
    with pytest.raises(Denied):
        verify(proof, request=request(requested_fields=frozenset({"review_evidence"})))


@pytest.mark.parametrize("proof", ["", "invalid", "é", "x" * 2049, None, 7])
def test_malformed_or_oversized_proof_is_safe_validation(proof):
    with pytest.raises(ValidationError):
        verify(proof)


@pytest.mark.parametrize(
    "payload", [[], {"intent": 1}, {"intent": "é"}, {"intent": "wrong", "extra": "x"}]
)
def test_signed_but_wrong_payload_is_not_accepted(payload):
    with pytest.raises(ValidationError):
        verify(signing.dumps(payload, salt=previews._SALT))


def test_rotation_fallback_and_no_time_expiry_preserve_original_receipt(
    world, monkeypatch
):
    with override_settings(SECRET_KEY="synthetic-old-key"):
        proof = prepare().proof
    monkeypatch.setattr(signing.time, "time", lambda: 10**12)
    with override_settings(
        SECRET_KEY="synthetic-new-key", SECRET_KEY_FALLBACKS=["synthetic-old-key"]
    ):
        assert verify(proof) == intent()
    with (
        override_settings(SECRET_KEY="synthetic-new-key", SECRET_KEY_FALLBACKS=[]),
        pytest.raises(ValidationError),
    ):
        verify(proof)


def test_canonical_multiline_unicode_normalization_and_private_separation(world):
    original = intent(text="  Cafe\u0301\r\nNext  ", reason="  Private\rReason  ")
    result = prepare(intent=original)
    assert result.intent.text == "Café\nNext"
    assert result.intent.reason == "Private\nReason"
    assert verify(result.proof, intent=original) == result.intent


@pytest.mark.parametrize(
    "change",
    [
        {"expected_version": True},
        {"expected_version": 0},
        {"expected_version": 2**63 - 1},
        {"retry_key": "not-a-UUID-object"},
        {"text": ""},
        {"reason": ""},
        {"text": "x" * 3001},
        {"reason": "x" * 2001},
        {"text": "a\x00b"},
        {"outcome": "automatic"},
    ],
)
def test_original_intent_bounds_precede_private_reads(world, change):
    with pytest.raises(ValidationError):
        prepare(intent=intent(**change))
    world.source.assert_not_called()
