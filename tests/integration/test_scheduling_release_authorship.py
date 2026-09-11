from dataclasses import replace
from uuid import uuid4

import pytest
from django.db import connection, transaction

from maru.identity.models import Account
from maru.scheduling import release_authorship
from maru.scheduling.candidate_commands import (
    copy_scheduling_candidate,
    remove_scheduling_placement,
    restore_scheduling_candidate,
)
from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.release_authorship import _load_release_authorship
from tests.factories import AccountFactory
from tests.integration import test_scheduling_candidates as candidates
from tests.integration import test_scheduling_placements as placements

world = candidates.world
planning_world = placements.world

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def _collect(request, revision_id):
    with transaction.atomic():
        result = _load_release_authorship(
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            candidate_revision_id=revision_id,
        )
        outsider = uuid4()
        with connection.cursor() as cursor:
            for person_id in (*result.author_ids, outsider):
                cursor.execute(
                    "SELECT public.maru_scheduling_release_independent(%s, %s, %s, %s)",
                    [
                        revision_id,
                        person_id,
                        request.organization_id,
                        request.edition_id,
                    ],
                )
                assert cursor.fetchone() == (person_id == outsider,)
        return result


def _copy(world, source, *, actor, control):
    return copy_scheduling_candidate(
        replace(candidates.request(world), actor_id=actor.id),
        source_revision_id=source.id,
        label="Synthetic independent alternative",
        expected_control_version=control,
        authorizer=world[1],
    )


def test_original_and_copy_chain_authors_are_retained_without_requiring_activity(world):
    original = candidates.revision(candidates.create(world))
    second_actor, third_actor = AccountFactory(), AccountFactory()
    second = candidates.revision(_copy(world, original, actor=second_actor, control=1))
    third = candidates.revision(_copy(world, second, actor=third_actor, control=2))
    before = _collect(world[0], third.id)
    assert before.author_ids == {world[2].id, second_actor.id, third_actor.id}
    Account.objects.filter(id=world[2].id).update(is_active=False)
    assert _collect(world[0], third.id) == before


def test_later_source_edit_is_not_retroactive_copy_authorship(world):
    original = candidates.revision(candidates.create(world))
    copier, later_editor = AccountFactory(), AccountFactory()
    copied = candidates.revision(_copy(world, original, actor=copier, control=1))
    before = _collect(world[0], copied.id)
    restored = restore_scheduling_candidate(
        replace(candidates.request(world), actor_id=later_editor.id),
        candidate_id=original.candidate_id,
        source_revision_id=original.id,
        expected_version=1,
        authorizer=world[1],
    )
    assert _collect(world[0], copied.id) == before
    assert _collect(world[0], candidates.revision(restored).id).author_ids == {
        world[2].id,
        later_editor.id,
    }


def test_restore_keeps_intervening_candidate_contributors(world):
    original = candidates.revision(candidates.create(world))
    second_actor, third_actor = AccountFactory(), AccountFactory()
    for version, actor in ((1, second_actor), (2, third_actor)):
        restored = restore_scheduling_candidate(
            replace(candidates.request(world), actor_id=actor.id),
            candidate_id=original.candidate_id,
            source_revision_id=original.id,
            expected_version=version,
            authorizer=world[1],
        )
    result = _collect(world[0], candidates.revision(restored).id)
    assert result.author_ids == {world[2].id, second_actor.id, third_actor.id}
    assert len(result.provenance_digest) == 64


def test_removed_then_restored_placement_keeps_its_original_author(planning_world):
    planner, remover, restorer = AccountFactory(), AccountFactory(), AccountFactory()
    placed = placements.place(
        planning_world,
        request=replace(placements.next_request(planning_world), actor_id=planner.id),
    )
    selected = placements.candidate_revision(placed)
    removed = remove_scheduling_placement(
        replace(placements.next_request(planning_world), actor_id=remover.id),
        candidate_id=placed.object_id,
        occurrence_id=planning_world.occurrence.object_id,
        expected_version=placed.version,
        authorizer=planning_world.policy,
    )
    restored = restore_scheduling_candidate(
        replace(placements.next_request(planning_world), actor_id=restorer.id),
        candidate_id=placed.object_id,
        source_revision_id=selected.id,
        expected_version=removed.version,
        authorizer=planning_world.policy,
    )
    result = _collect(
        planning_world.request, placements.candidate_revision(restored).id
    )
    assert result.author_ids == {
        planning_world.request.actor_id,
        planner.id,
        remover.id,
        restorer.id,
    }


@pytest.mark.parametrize("field", ["organization_id", "edition_id"])
def test_foreign_scope_does_not_disclose_authorship(world, field):
    original = candidates.revision(candidates.create(world))
    with pytest.raises(SchedulingUnavailableError):
        _collect(replace(world[0], **{field: uuid4()}), original.id)


def test_missing_revision_and_absent_transaction_are_unavailable(world):
    with pytest.raises(SchedulingUnavailableError):
        _collect(world[0], uuid4())
    original = candidates.revision(candidates.create(world))
    with pytest.raises(SchedulingUnavailableError):
        _load_release_authorship(
            organization_id=world[0].organization_id,
            edition_id=world[0].edition_id,
            candidate_revision_id=original.id,
        )


@pytest.mark.parametrize("bound", ["MAX_CANDIDATES", "MAX_CANDIDATE_REVISIONS"])
def test_complete_ancestry_budget_overflow_is_not_partial_success(
    world, monkeypatch, bound
):
    original = candidates.revision(candidates.create(world))
    copier = AccountFactory()
    copied = candidates.revision(_copy(world, original, actor=copier, control=1))
    monkeypatch.setattr(release_authorship, bound, 1)
    with pytest.raises(SchedulingUnavailableError):
        _collect(world[0], copied.id)
