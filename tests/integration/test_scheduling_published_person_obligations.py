"""Operative host time survives visibility loss, but not deliberate withdrawal."""

import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from queue import Queue
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import IntegrityError, connection, transaction
from psycopg import sql

from maru.identity.models import Account
from maru.programme.models import ProgrammeHostRelationship, ProgrammeItem
from maru.programme.public_copy_commands import withdraw_programme_public_rendition
from maru.scheduling import release_publication_commands
from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.models import SchedulingPlacementHostPresence
from maru.scheduling.person_obligation_references import (
    resolve_published_person_conflict,
)
from maru.workforce.availability_inputs import AvailabilityWindowInput
from maru.workforce.models import ShiftCommitment
from maru.workforce.shift_commands import ShiftOverlapConflictError, _require_no_overlap
from tests.integration import test_workforce_shifts as shifts
from tests.integration.test_database_role_safety import (
    _create_role,
    _password_authenticated_default_database,
    _prepare_least_privilege_boundary,
    _provision_runtime_role,
    _public_privilege_snapshot,
    _restore_public_privileges,
)
from tests.integration.test_programme_current_release_sources import (
    configure_release_scope,
)
from tests.integration.test_programme_placement_decisions import assess_world
from tests.integration.test_scheduling_placements import planning_world
from tests.integration.test_scheduling_release_capture import capture_ready_scope
from tests.integration.test_scheduling_release_identity_races import (
    _observe_lock_wait,
    _worker,
)
from tests.integration.test_scheduling_release_preflight import (
    configure_preflight_scope,
)
from tests.integration.test_scheduling_release_queries import (
    admitted as admitted,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_queries import (
    approve,
    load,
    publish,
    withdraw,
)
from tests.integration.test_scheduling_release_queries import (
    assessed as assessed,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_queries import (
    capture_scope as capture_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_queries import (
    preflight_scope as preflight_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_queries import (
    release_scope as release_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_queries import (
    review_scope as review_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_queries import (
    world as world,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_review_commands import reviewable_scope

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def host_source(scope):
    presence = SchedulingPlacementHostPresence.objects.get(
        placement_id=scope.selection.placement_id
    )
    host = ProgrammeHostRelationship.objects.get(id=presence.host_relationship_id)
    return SimpleNamespace(
        account_id=host.account_id,
        starts_at=presence.starts_at,
        ends_at=presence.ends_at,
        rest_ends_at=presence.ends_at,
    )


def check(source, **overrides):
    with transaction.atomic():
        return resolve_published_person_conflict(**(vars(source) | overrides))


@pytest.mark.parametrize("rollback_first", [False, True])
def test_two_foreign_programme_publications_serialize_the_same_host(
    review_scope, monkeypatch, rollback_first
):
    source = host_source(review_scope)
    foreign_world = planning_world(
        monkeypatch, host_account=Account.objects.get(id=source.account_id)
    )
    foreign = reviewable_scope(
        capture_ready_scope(
            configure_preflight_scope(
                configure_release_scope(
                    assess_world(foreign_world, monkeypatch), monkeypatch
                ),
                monkeypatch,
            )
        )
    )
    assert foreign.request.organization_id != review_scope.request.organization_id
    first_approval = approve(review_scope)
    second_approval = approve(foreign)
    backends = Queue()
    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            first = publish(review_scope, first_approval)
            future = executor.submit(
                _worker, lambda: publish(foreign, second_approval), backends
            )
            _observe_lock_wait(backends.get(timeout=5))
            assert not future.done()
            if rollback_first:
                transaction.set_rollback(True)
        if rollback_first:
            future.result(timeout=12)
        else:
            with pytest.raises(SchedulingUnavailableError):
                future.result(timeout=12)
    assert load(review_scope).state == ("absent" if rollback_first else "available")
    assert load(foreign).state == ("available" if rollback_first else "absent")
    if not rollback_first:
        withdraw(review_scope, first)
        # An exact old approval cannot silently accept the publish/withdraw ABA.
        with pytest.raises(SchedulingUnavailableError):
            publish(foreign, second_approval)


def test_private_draft_is_not_operative_and_release_withdrawal_retains_freshness(
    review_scope,
):
    source = host_source(review_scope)
    initial = check(source)
    assert not initial.overlap
    released = publish(review_scope, approve(review_scope))
    published = check(source)
    assert published.overlap
    assert not published.rest
    assert published.evidence_digest != initial.evidence_digest
    excluded = check(source, replaced_edition_id=review_scope.request.edition_id)
    assert not excluded.overlap
    withdraw(review_scope, released)
    withdrawn = check(source)
    assert not withdrawn.overlap
    assert withdrawn.evidence_digest not in {
        initial.evidence_digest,
        published.evidence_digest,
    }


def test_host_obligation_is_half_open_and_preserves_incoming_work_rest(review_scope):
    source = host_source(review_scope)
    publish(review_scope, approve(review_scope))
    assert not check(
        source,
        starts_at=source.ends_at,
        ends_at=source.ends_at + timedelta(hours=1),
        rest_ends_at=source.ends_at + timedelta(hours=1),
    ).overlap
    adjacent = {
        "starts_at": source.starts_at - timedelta(hours=1),
        "ends_at": source.starts_at,
    }
    assert not check(source, **adjacent, rest_ends_at=source.starts_at).rest
    resting = check(
        source, **adjacent, rest_ends_at=source.starts_at + timedelta(minutes=1)
    )
    assert resting.rest
    assert not resting.overlap


def test_invalidated_copy_does_not_cancel_host_commitment(review_scope):
    source = host_source(review_scope)
    publish(review_scope, approve(review_scope))
    selected = load(review_scope).selections[0]
    item = ProgrammeItem.objects.get(id=review_scope.selection.item_id)
    withdraw_programme_public_rendition(
        actor_id=review_scope.request.actor_id,
        organization_id=review_scope.request.organization_id,
        edition_id=review_scope.request.edition_id,
        item_id=item.id,
        rendition_id=selected.public_rendition_id,
        expected_version=item.aggregate_version,
        reason="Stop disclosure without cancelling the hosting commitment",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        authorizer=review_scope.policy,
    )
    assert load(review_scope).state == "invalidated"
    assert check(source).overlap


def test_workforce_guard_consults_published_host_obligation(review_scope):
    source = host_source(review_scope)
    publish(review_scope, approve(review_scope))
    with transaction.atomic(), pytest.raises(ShiftOverlapConflictError):
        _require_no_overlap(
            account_id=source.account_id,
            demand=SimpleNamespace(
                starts_at=source.starts_at,
                ends_at=source.ends_at,
                minimum_rest_minutes=0,
            ),
        )


def test_genuine_runtime_rejects_work_conflicting_with_a_populated_foreign_release(
    review_scope, monkeypatch
):
    source = host_source(review_scope)
    foreign, person, demand = foreign_work(review_scope, monkeypatch)
    publish(review_scope, approve(review_scope))
    snapshot = _public_privilege_snapshot()
    password = secrets.token_urlsafe(36)
    role = _create_role(password=password)
    try:
        with transaction.atomic():
            _prepare_least_privilege_boundary()
            _provision_runtime_role(role)
        with _password_authenticated_default_database(
            role_name=role, password=password
        ):
            assert check(source).overlap
            with pytest.raises(ShiftOverlapConflictError):
                shifts._claim(foreign, demand, person=person)
            assert not ShiftCommitment.objects.filter(demand=demand).exists()
    finally:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
            _restore_public_privileges(snapshot)


def foreign_work(scope, monkeypatch):
    source = host_source(scope)
    monkeypatch.setattr(
        shifts,
        "_windows",
        lambda: (
            AvailabilityWindowInput(
                source.starts_at - timedelta(hours=1),
                source.ends_at + timedelta(hours=2),
                "preferred",
            ),
        ),
    )
    foreign = shifts._shift_world()
    person = Account.objects.get(id=source.account_id)
    shifts._activate_person(
        edition=foreign.edition,
        planner=foreign.planner,
        reviewer=foreign.reviewer,
        position=foreign.position,
        person=person,
    )
    demand = shifts._create_demand(
        foreign,
        title="Undisclosed foreign synthetic duty",
        starts_at=source.starts_at.isoformat(),
        ends_at=source.ends_at.isoformat(),
        minimum_rest_minutes=0,
    )
    shifts._open(foreign, demand)
    return foreign, person, demand


def test_real_foreign_claim_and_native_bypass_cannot_double_book_published_host(
    review_scope,
    monkeypatch,
):
    foreign, person, demand = foreign_work(review_scope, monkeypatch)
    released = publish(review_scope, approve(review_scope))
    with pytest.raises(ShiftOverlapConflictError):
        shifts._claim(foreign, demand, person=person)
    with (
        patch("maru.workforce.shift_commands._require_no_overlap"),
        pytest.raises(IntegrityError, match="operative published person obligations"),
    ):
        shifts._claim(foreign, demand, person=person)
    assert not ShiftCommitment.objects.filter(demand=demand).exists()
    withdraw(review_scope, released)
    shifts._claim(foreign, demand, person=person)
    assert ShiftCommitment.objects.filter(
        demand=demand, account=person, status="claimed"
    ).exists()


def test_pointer_guard_rejects_work_inserted_after_application_preparation(
    review_scope,
    monkeypatch,
):
    foreign, person, demand = foreign_work(review_scope, monkeypatch)
    approved = approve(review_scope)
    original = release_publication_commands._advance_pointer

    def introduce_conflict(*args):
        shifts._claim(foreign, demand, person=person)
        return original(*args)

    with (
        patch.object(
            release_publication_commands, "_advance_pointer", introduce_conflict
        ),
        pytest.raises(IntegrityError, match="operative person work or rest"),
    ):
        publish(review_scope, approved)
    assert load(review_scope).state == "absent"
    assert not ShiftCommitment.objects.filter(demand=demand).exists()


@pytest.mark.parametrize("rollback_publication", [False, True])
def test_real_claim_waits_for_uncommitted_publication_then_rechecks(
    review_scope,
    monkeypatch,
    rollback_publication,
):
    foreign, person, demand = foreign_work(review_scope, monkeypatch)
    approved = approve(review_scope)
    backends = Queue()
    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            publish(review_scope, approved)
            future = executor.submit(
                _worker, lambda: shifts._claim(foreign, demand, person=person), backends
            )
            _observe_lock_wait(backends.get(timeout=5))
            assert not future.done()
            if rollback_publication:
                transaction.set_rollback(True)
        if rollback_publication:
            future.result(timeout=12)
        else:
            with pytest.raises(ShiftOverlapConflictError):
                future.result(timeout=12)
    assert (
        ShiftCommitment.objects.filter(demand=demand, status="claimed").exists()
        is rollback_publication
    )
    assert load(review_scope).state == (
        "absent" if rollback_publication else "available"
    )


@pytest.mark.parametrize("rollback_claim", [False, True])
def test_real_publication_waits_for_native_claim_then_rechecks(
    review_scope,
    monkeypatch,
    rollback_claim,
):
    foreign, person, demand = foreign_work(review_scope, monkeypatch)
    approved = approve(review_scope)
    backends = Queue()
    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            shifts._claim(foreign, demand, person=person)
            future = executor.submit(
                _worker, lambda: publish(review_scope, approved), backends
            )
            _observe_lock_wait(backends.get(timeout=5))
            assert not future.done()
            if rollback_claim:
                transaction.set_rollback(True)
        if rollback_claim:
            future.result(timeout=12)
        else:
            with pytest.raises(SchedulingUnavailableError):
                future.result(timeout=12)
    assert (
        ShiftCommitment.objects.filter(demand=demand, status="claimed").exists()
        is not rollback_claim
    )
    assert load(review_scope).state == ("available" if rollback_claim else "absent")
