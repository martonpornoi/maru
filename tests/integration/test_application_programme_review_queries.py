"""Exact-object, field, anonymity, and recipient-only Programme review reads."""

from __future__ import annotations

import json
from dataclasses import replace
from uuid import uuid4

import pytest

from maru.applications import programme_review_queries as queries
from maru.applications.models import ProgrammeReviewAction as Action
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError,
)
from maru.applications.programme_inputs import ProgrammeCallClassification
from maru.applications.programme_review_authorization import (
    MANAGE_REVIEW,
    REVIEW,
    SENSITIVE_REVIEW,
    VIEW_DECISION_SELF,
)
from maru.applications.programme_review_inputs import (
    ProgrammeReviewCommandInput as Intent,
)
from maru.applications.programme_review_queries import (
    get_programme_review_detail,
    list_self_programme_decisions,
)
from maru.audit.models import AuditEvent
from maru.authorization.policy import PolicyDecision
from tests.integration import test_application_programme_services as source_worlds
from tests.integration.test_application_programme_services import (
    _AUTHORIZER,
    _admit_future_programme_effects,
    _AllowExactProgrammeAuthorizer,
)
from tests.support.programme_review import assign_and_score, create_review_world
from tests.unit.test_application_programme_review_inputs import review_policy

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures(_admit_future_programme_effects.__name__),
]


@pytest.mark.parametrize("field", ["organization_id", "edition_id", "department_id"])
def test_detail_refuses_foreign_scope_before_content_or_version_disclosure(field):
    world = create_review_world()
    assign_and_score(world, world.reviewer.id)
    request = replace(world.read(world.reviewer.id, REVIEW), **{field: uuid4()})
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        get_programme_review_detail(
            request=request, case_id=world.case_id, authorizer=_AUTHORIZER
        )


def test_unknown_and_foreign_case_ids_have_the_same_denial():
    world = create_review_world()
    foreign = create_review_world()
    assign_and_score(world, world.reviewer.id)
    request = world.read(world.reviewer.id, REVIEW)
    for case_id in (uuid4(), foreign.case_id):
        with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
            get_programme_review_detail(
                request=request, case_id=case_id, authorizer=_AUTHORIZER
            )


def test_peer_discussion_requires_own_score_and_never_exposes_peer_scores():
    world = create_review_world()
    peer = assign_and_score(world, world.peer.id)
    world.command(
        world.peer.id,
        Intent(
            Action.DISCUSSED,
            world.case_id,
            reference_id=peer,
            text="A deliberate peer discussion note.",
        ),
    )
    assigned = world.command(
        world.call.manager.id,
        Intent(Action.REVIEWER_ASSIGNED, world.case_id, reference_id=world.reviewer.id),
    )
    world.command(
        world.reviewer.id,
        Intent(Action.CONFLICT_CLEARED, world.case_id, reference_id=assigned.target_id),
    )
    request = world.read(world.reviewer.id, REVIEW)
    before = get_programme_review_detail(
        request=request, case_id=world.case_id, authorizer=_AUTHORIZER
    )
    assert "peer discussion note" not in before.evidence_json
    world.command(
        world.reviewer.id,
        Intent(
            Action.SCORED,
            world.case_id,
            reference_id=assigned.target_id,
            scores=(("fit", 3),),
        ),
    )
    after = get_programme_review_detail(
        request=request, case_id=world.case_id, authorizer=_AUTHORIZER
    )
    assert "peer discussion note" in after.evidence_json
    assert str(world.peer.id) not in after.evidence_json
    assert str(peer) not in after.evidence_json
    assert [
        entry["payload"]["scores"]
        for entry in json.loads(after.evidence_json)
        if entry["action"] == "scored"
    ] == [{"fit": 3}]


def test_evidence_pagination_neither_leaks_peers_nor_silently_truncates_history():
    world = create_review_world()
    assign_and_score(world, world.reviewer.id)
    request = world.read(
        world.reviewer.id, REVIEW, fields=frozenset({"review_evidence"})
    )
    cursor = 0
    versions = []
    while True:
        page = get_programme_review_detail(
            request=request,
            case_id=world.case_id,
            after_version=cursor,
            limit=1,
            authorizer=_AUTHORIZER,
        )
        assert page.answers_json is None
        assert page.context_json is None
        entries = json.loads(page.evidence_json)
        versions.extend(entry["version"] for entry in entries)
        if page.next_evidence_version is None:
            break
        assert page.next_evidence_version > cursor
        cursor = page.next_evidence_version
    assert versions == [2, 3, 4]


def test_management_context_does_not_imply_any_review_content():
    world = create_review_world()
    assignment = assign_and_score(world, world.reviewer.id)
    request = world.read(
        world.call.manager.id, MANAGE_REVIEW, fields=frozenset({"review_context"})
    )
    detail = get_programme_review_detail(
        request=request, case_id=world.case_id, authorizer=_AUTHORIZER
    )
    assert detail.answers_json is None
    assert detail.evidence_json is None
    assert "contributors" not in json.loads(detail.context_json)
    assert "selection" not in json.loads(detail.context_json)
    assert json.loads(detail.context_json)["assignments"] == [
        {
            "assignment_id": str(assignment),
            "account_id": str(world.reviewer.id),
            "stage": 0,
            "state": "active",
        }
    ]


@pytest.mark.parametrize("anonymous", [True, False])
def test_structured_contributor_projection_follows_the_pinned_anonymity_policy(
    anonymous,
):
    policy = review_policy()
    world = create_review_world(
        policy=replace(policy, stages=(replace(policy.stages[0], anonymous=anonymous),))
    )
    assign_and_score(world, world.reviewer.id)
    detail = get_programme_review_detail(
        request=world.read(world.reviewer.id, REVIEW),
        case_id=world.case_id,
        authorizer=_AUTHORIZER,
    )
    context = json.loads(detail.context_json)
    assert set(context["selection"]) == {
        "track_code",
        "format_code",
        "requested_duration_minutes",
    }
    assert ("contributors" not in context) is anonymous
    assert str(world.lead.id) not in detail.context_json
    if not anonymous:
        assert context["contributors"][0]["public_name"] == "Programme lead"


class _DenySensitive(_AllowExactProgrammeAuthorizer):
    def authorize_department(self, **kwargs):
        if kwargs["capability_code"] == SENSITIVE_REVIEW:
            return PolicyDecision(
                allowed=False,
                fields=frozenset(),
                obligations=frozenset(),
                reason_code="sensitive_test_denial",
            )
        return super().authorize_department(**kwargs)


def test_sensitive_definition_requires_independent_review_authority(monkeypatch):
    original = source_worlds._definition

    def restricted(now, *, code):
        return replace(
            original(now, code=code),
            classification=ProgrammeCallClassification.RESTRICTED,
        )

    monkeypatch.setattr(source_worlds, "_definition", restricted)
    world = create_review_world()
    assign_and_score(world, world.reviewer.id)
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        get_programme_review_detail(
            request=world.read(world.reviewer.id, REVIEW),
            case_id=world.case_id,
            authorizer=_DenySensitive(),
        )
    allowed = get_programme_review_detail(
        request=world.read(world.reviewer.id, REVIEW),
        case_id=world.case_id,
        authorizer=_AUTHORIZER,
    )
    assert (
        json.loads(allowed.answers_json)[0]["value"] == "A sealed session description"
    )


def test_outsiders_get_no_recipient_history_or_acknowledgement_authority():
    world = create_review_world()
    assign_and_score(world, world.reviewer.id)
    assign_and_score(world, world.peer.id)
    world.command(world.moderator.id, Intent(Action.MODERATED, world.case_id))
    decision = world.command(
        world.decider.id,
        Intent(
            Action.DECIDED,
            world.case_id,
            outcome="accepted",
            text="Addressed only to exact contributors.",
        ),
    )
    request = world.read(
        world.peer.id,
        VIEW_DECISION_SELF,
        fields=frozenset({"decision_message", "own_acknowledgement"}),
        self_access=True,
    )
    assert (
        list_self_programme_decisions(request=request, authorizer=_AUTHORIZER).items
        == ()
    )
    for decision_id in (decision.target_id, uuid4()):
        with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
            world.command(
                world.peer.id,
                Intent(Action.ACKNOWLEDGED, world.case_id, reference_id=decision_id),
                expected_version=0,
                self_access=True,
            )


def test_failed_read_audit_prevents_disclosure_and_rolls_back_its_partial_audit(
    monkeypatch,
):
    world = create_review_world()
    assign_and_score(world, world.reviewer.id)

    before = AuditEvent.objects.count()
    real = queries.append_audit

    def unavailable(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("Synthetic audited disclosure failure")

    monkeypatch.setattr(queries, "append_audit", unavailable)
    with pytest.raises(RuntimeError, match="audited disclosure failure"):
        get_programme_review_detail(
            request=world.read(world.reviewer.id, REVIEW),
            case_id=world.case_id,
            authorizer=_AUTHORIZER,
        )
    assert AuditEvent.objects.count() == before
