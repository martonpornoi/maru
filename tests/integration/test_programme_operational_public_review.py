"""Operational public review does not reopen frozen working-information editing."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import IntegrityError

from maru.events.services import transition_edition
from maru.programme import commands
from maru.programme.authorization import ProgrammeAuthorizationDenied
from maru.programme.models import ProgrammeItem, ProgrammePublicRendition
from tests.factories import AccountFactory, CapabilityGrantFactory, EventEditionFactory
from tests.integration.test_programme_commands import (
    _create,
    _TrustedProgrammeAuthorizer,
)
from tests.integration.test_programme_commands import (
    admits_exact_effect as admits_exact_effect,  # noqa: PLC0414
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def review_world(admits_exact_effect):
    actor, reviewer, edition = AccountFactory(), AccountFactory(), EventEditionFactory()
    policy = _TrustedProgrammeAuthorizer()
    created, _, _ = _create(actor=actor, edition=edition, authorizer=policy)
    item = ProgrammeItem.objects.get(id=created.item_id)
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=actor,
        capability_code="events.transition",
    )
    return SimpleNamespace(
        actor=actor,
        reviewer=reviewer,
        edition=edition,
        policy=policy,
        item=item,
        source=item.working_revisions.get(),
    )


def advance(scope, state):
    for next_state in ("preparing", "ready", "live", "closing", "archived"):
        scope.edition = transition_edition(
            organization_id=scope.edition.organization_id,
            edition_id=scope.edition.id,
            to_state=next_state,
            actor=scope.actor,
            reason="Advance the synthetic copy-review scope",
            correlation_id=uuid4(),
        )
        if next_state == state:
            return


def review(scope, *, actor=None):
    return commands.approve_programme_public_rendition(
        actor_id=(actor or scope.reviewer).id,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        item_id=scope.item.id,
        source_working_revision_id=scope.source.id,
        public_title="Independently reviewed public opening",
        expected_version=1,
        reason="Review public copy without reopening private edits",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        authorizer=scope.policy,
    )


@pytest.mark.parametrize("state", ["ready", "live"])
def test_independent_public_review_preserves_frozen_working_copy(review_world, state):
    advance(review_world, state)
    result = review(review_world)
    rendition = ProgrammePublicRendition.objects.get(id=result.result_object_id)
    assert rendition.source_working_revision_id == review_world.source.id
    assert rendition.reviewed_by_id == review_world.reviewer.id
    review_world.item.refresh_from_db()
    assert review_world.item.aggregate_version == 1
    assert review_world.item.working_revisions.count() == 1
    with pytest.raises(commands.ProgrammeLifecycleConflictError):
        commands.revise_programme_working(
            actor_id=review_world.actor.id,
            organization_id=review_world.edition.organization_id,
            edition_id=review_world.edition.id,
            item_id=review_world.item.id,
            internal_title="Forbidden private rewrite",
            expected_version=1,
            reason="Verify the private planning fence remains closed",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            authorizer=review_world.policy,
        )


@pytest.mark.parametrize("state", ["ready", "live"])
def test_working_author_cannot_supply_operational_independent_review(
    review_world, state
):
    advance(review_world, state)
    with pytest.raises(ProgrammeAuthorizationDenied):
        review(review_world, actor=review_world.actor)
    assert not ProgrammePublicRendition.objects.exists()


def test_database_rejects_self_review_despite_wrong_application_lifecycle_fact(
    review_world,
):
    advance(review_world, "ready")
    original = commands._postauthorize

    def misclassified(**arguments):
        return replace(original(**arguments), accepts_private_planning_writes=True)

    with (
        patch.object(commands, "_postauthorize", misclassified),
        pytest.raises(IntegrityError, match="public rendition evidence mismatch"),
    ):
        review(review_world, actor=review_world.actor)
    assert not ProgrammePublicRendition.objects.exists()


def test_draft_self_curation_remains_history_after_independent_operational_review(
    review_world,
):
    original = review(review_world, actor=review_world.actor)
    advance(review_world, "ready")
    independent = review(review_world)
    current = ProgrammePublicRendition.objects.get(id=independent.result_object_id)
    assert current.supersedes_id == original.result_object_id
    assert ProgrammePublicRendition.objects.count() == 2


@pytest.mark.parametrize("state", ["closing", "archived"])
def test_ended_editions_cannot_accept_new_public_copy(review_world, state):
    advance(review_world, state)
    with pytest.raises(commands.ProgrammeLifecycleConflictError):
        review(review_world)
    assert not ProgrammePublicRendition.objects.exists()
