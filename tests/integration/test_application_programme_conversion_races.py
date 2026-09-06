"""Separate-connection conversion races against retries and source mutations."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import uuid4

import pytest
from django.db import connections

from maru.applications import (
    programme_commands,
    programme_conversion_commands,
    programme_review_commands,
)
from maru.applications.models import (
    ProgrammeAcceptedTransition,
    ProgrammeProposal,
    ProgrammeReviewAction,
)
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError,
)
from maru.applications.programme_conversion_commands import (
    convert_accepted_programme_proposal,
)
from maru.applications.programme_conversion_sources import (
    ProgrammeConversionConflictError,
)
from maru.applications.programme_review_inputs import ProgrammeReviewCommandInput
from maru.programme.models import ProgrammeItem
from maru.workforce import structure_commands
from tests.factories import AccountFactory
from tests.integration.test_application_programme_conversion import accepted
from tests.integration.test_application_programme_services import (
    _AUTHORIZER,
    _admit_future_programme_effects,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.django_db(transaction=True),
    pytest.mark.usefixtures(
        _admit_future_programme_effects.__name__, accepted.__name__
    ),
]


@pytest.mark.parametrize("same_retry", [True, False])
def test_two_connections_create_one_target_or_replay_one_intent(accepted, same_retry):
    _, _, kwargs = accepted
    barrier = Barrier(2)

    def convert(index):
        try:
            barrier.wait(timeout=10)
            try:
                return convert_accepted_programme_proposal(
                    **{
                        **kwargs,
                        "retry_key": kwargs["retry_key"]
                        if same_retry or index == 0
                        else uuid4(),
                    }
                )
            except ProgrammeConversionConflictError:
                return None
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(convert, index) for index in range(2)]
        results = [future.result(timeout=25) for future in futures]
    assert (
        ProgrammeAcceptedTransition.objects.count()
        == ProgrammeItem.objects.count()
        == 1
    )
    if same_retry:
        assert results[0].programme_item_id == results[1].programme_item_id
        assert sorted(result.replayed for result in results) == [False, True]
    else:
        assert results.count(None) == 1


@pytest.mark.parametrize("source_action", ["withdraw", "reopen", "recuse", "retire"])
@pytest.mark.parametrize("source_first", [True, False])
def test_source_mutation_and_conversion_serialize_in_both_orders(
    accepted, monkeypatch, source_action, source_first
):
    world, assignment, kwargs = accepted
    proposal = ProgrammeProposal.objects.select_related("submission").get(
        id=world.proposal_id
    )
    review_version = world.version
    retiring_actor = None
    if source_action == "retire":
        programme_commands.retire_programme_call(
            actor_id=world.call.manager.id,
            organization_id=kwargs["organization_id"],
            edition_id=kwargs["edition_id"],
            call_id=world.call.call_id,
            owner_department_id=world.call.department_id,
            expected_version=2,
            reason="Close the call before historic Department retirement.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            authorizer=_AUTHORIZER,
        )
        retiring_actor = AccountFactory(is_staff=True, is_superuser=True)
    acquired, attempted = Event(), Event()
    source_boundary = (
        (programme_review_commands, "lock_programme_edition_write_scope")
        if source_action == "recuse"
        else (programme_commands, "_proposal_preflight")
    )
    target_boundary = (
        programme_conversion_commands,
        "lock_programme_edition_write_scope",
    )
    if source_action == "retire":
        source_boundary = (structure_commands, "_lock_scope")
    first, second = (
        (source_boundary, target_boundary)
        if source_first
        else (target_boundary, source_boundary)
    )
    first_lock, second_lock = getattr(*first), getattr(*second)

    def hold_first(**values):
        result = first_lock(**values)
        if values.get("lock", True):
            acquired.set()
            assert attempted.wait(timeout=10)
        return result

    def contend_second(**values):
        if values.get("lock", True):
            assert acquired.wait(timeout=10)
            attempted.set()
        return second_lock(**values)

    monkeypatch.setattr(*first, hold_first)
    monkeypatch.setattr(*second, contend_second)

    def mutate():
        try:
            if source_action == "retire":
                return structure_commands.retire_department(
                    actor=retiring_actor,
                    organization_id=kwargs["organization_id"],
                    series_id=world.call.edition.series_id,
                    edition_id=kwargs["edition_id"],
                    department_id=world.call.department_id,
                    expected_version=1,
                    reason="Retirement competing with exact accepted conversion.",
                    correlation_id=uuid4(),
                    source_channel="test",
                )
            if source_action == "recuse":
                return world.command(
                    world.reviewer.id,
                    ProgrammeReviewCommandInput(
                        action=ProgrammeReviewAction.REVIEWER_RECUSED,
                        target_id=world.case_id,
                        reference_id=assignment,
                    ),
                    expected_version=review_version,
                )
            command = (
                programme_commands.withdraw_programme_proposal
                if source_action == "withdraw"
                else programme_commands.reopen_programme_proposal
            )
            return command(
                actor_id=world.lead.id,
                organization_id=kwargs["organization_id"],
                edition_id=kwargs["edition_id"],
                proposal_id=world.proposal_id,
                expected_version=proposal.submission.aggregate_version,
                reason="Source mutation competing with conversion.",
                retry_key=uuid4(),
                correlation_id=uuid4(),
                source_channel="test",
                authorizer=_AUTHORIZER,
            )
        finally:
            connections.close_all()

    def convert():
        try:
            try:
                return convert_accepted_programme_proposal(**kwargs)
            except (
                ProgrammeConversionConflictError,
                ApplicationsProgrammeAuthorizationDeniedError,
            ):
                return None
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        changed, converted = pool.submit(mutate), pool.submit(convert)
        assert changed.result(timeout=25) is not None
        result = converted.result(timeout=25)
    assert (result is None) is source_first
    assert (
        ProgrammeAcceptedTransition.objects.count()
        == ProgrammeItem.objects.count()
        == (0 if source_first else 1)
    )
