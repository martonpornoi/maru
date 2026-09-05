"""Real connection races for review cursors, retries, and ownership mutexes."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import uuid4

import pytest
from django.db import DatabaseError, connection, connections, transaction

from maru.applications import programme_commands, programme_review_commands
from maru.applications.models import (
    ProgrammeProposal,
    ProgrammeReviewAssignment,
    ProgrammeReviewCase,
    ProgrammeReviewDecision,
    ProgrammeReviewReceipt,
)
from maru.applications.models import (
    ProgrammeReviewAction as Action,
)
from maru.applications.programme_review_inputs import (
    ProgrammeReviewCommandInput as Intent,
)
from maru.applications.programme_review_rules import (
    ProgrammeReviewConflictError,
    accepted_review_is_effective,
)
from maru.applications.programme_writer_boundary import (
    programme_application_database_writer,
)
from maru.workforce.writer_boundary import lock_edition_structure_mutex
from tests.integration.test_application_programme_services import (
    _AUTHORIZER,
    _admit_future_programme_effects,
)
from tests.support.programme_review import assign_and_score, create_review_world

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures(_admit_future_programme_effects.__name__),
]


@pytest.mark.parametrize("same_retry", [False, True])
def test_concurrent_review_intents_have_one_atomic_winner_or_exact_replay(same_retry):
    world = create_review_world()
    expected = world.version
    start = Barrier(2)
    shared_key = uuid4()

    def contender(index):
        try:
            start.wait(timeout=10)
            actor = world.reviewer if same_retry or index == 0 else world.peer
            try:
                return world.command(
                    world.call.manager.id,
                    Intent(
                        Action.REVIEWER_ASSIGNED, world.case_id, reference_id=actor.id
                    ),
                    expected_version=expected,
                    retry_key=shared_key if same_retry else uuid4(),
                )
            except ProgrammeReviewConflictError:
                return None
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(contender, index) for index in range(2)]
        results = [future.result(timeout=20) for future in futures]
    assert world.version == expected + 1
    assert ProgrammeReviewAssignment.objects.filter(case_id=world.case_id).count() == 1
    assert (
        ProgrammeReviewReceipt.objects.filter(
            case_id=world.case_id, action=Action.REVIEWER_ASSIGNED
        ).count()
        == 1
    )
    if same_retry:
        assert sorted(result.replayed for result in results) == [False, True]
        assert results[0].receipt_id == results[1].receipt_id
    else:
        assert sum(result is None for result in results) == 1


def test_raw_review_write_rejects_inverted_retirement_lock_without_deadlock():
    world = create_review_world()
    locked, release = Event(), Event()

    def hold_retirement_mutex():
        try:
            with transaction.atomic():
                lock_edition_structure_mutex(
                    organization_id=world.call.edition.organization_id,
                    edition_id=world.call.edition.id,
                )
                locked.set()
                assert release.wait(timeout=15)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as pool:
        holder = pool.submit(hold_retirement_mutex)
        try:
            assert locked.wait(timeout=10)
            with (
                pytest.raises(DatabaseError) as error,
                transaction.atomic(),
                programme_application_database_writer(),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    "UPDATE public.applications_programmereviewcase "
                    "SET version = version + 1 WHERE id = %s",
                    [world.case_id],
                )
            assert error.value.__cause__.sqlstate == "40001"
        finally:
            release.set()
        holder.result(timeout=10)
    assert world.version == 1


@pytest.mark.parametrize("source_action", ["withdraw", "reopen"])
@pytest.mark.parametrize("source_first", [True, False])
def test_decision_and_source_change_serialize_in_both_orders(
    monkeypatch, source_action, source_first
):
    world = create_review_world()
    assign_and_score(world, world.reviewer.id)
    assign_and_score(world, world.peer.id)
    world.command(world.moderator.id, Intent(Action.MODERATED, world.case_id))
    proposal = ProgrammeProposal.objects.select_related("submission").get(
        id=world.proposal_id
    )
    old_revision = proposal.submitted_revision_id
    review_version = world.version
    acquired, attempted = Event(), Event()
    boundaries = (
        (programme_commands, "_proposal_preflight"),
        (programme_review_commands, "lock_programme_edition_write_scope"),
    )
    first, second = boundaries if source_first else tuple(reversed(boundaries))
    first_lock = getattr(*first)
    second_lock = getattr(*second)

    def hold_first(**kwargs):
        result = first_lock(**kwargs)
        if kwargs.get("lock", True):
            acquired.set()
            assert attempted.wait(timeout=10)
        return result

    def contend_second(**kwargs):
        if kwargs.get("lock", True):
            assert acquired.wait(timeout=10)
            attempted.set()
        return second_lock(**kwargs)

    monkeypatch.setattr(*first, hold_first)
    monkeypatch.setattr(*second, contend_second)

    def change_source():
        try:
            command = (
                programme_commands.withdraw_programme_proposal
                if source_action == "withdraw"
                else programme_commands.reopen_programme_proposal
            )
            return command(
                actor_id=world.lead.id,
                organization_id=world.call.edition.organization_id,
                edition_id=world.call.edition.id,
                proposal_id=world.proposal_id,
                expected_version=proposal.submission.aggregate_version,
                reason="Synthetic source change competing with a final decision.",
                retry_key=uuid4(),
                correlation_id=uuid4(),
                source_channel="test",
                authorizer=_AUTHORIZER,
            )
        finally:
            connections.close_all()

    def decide():
        try:
            try:
                return world.command(
                    world.decider.id,
                    Intent(
                        Action.DECIDED,
                        world.case_id,
                        outcome="accepted",
                        text="A deliberate competing decision.",
                    ),
                    expected_version=review_version,
                )
            except ProgrammeReviewConflictError:
                return None
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        source_future = pool.submit(change_source)
        decision_future = pool.submit(decide)
        assert source_future.result(timeout=20) is not None
        assert (decision_future.result(timeout=20) is None) is source_first
    case = ProgrammeReviewCase.objects.select_related("proposal", "policy").get(
        id=world.case_id
    )
    assert case.revision_id == old_revision
    assert not accepted_review_is_effective(case)
    decisions = ProgrammeReviewDecision.objects.filter(entry__case=case)
    assert decisions.count() == (0 if source_first else 1)
    if not source_first:
        assert decisions.get().revision_id == old_revision
