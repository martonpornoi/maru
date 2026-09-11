"""Trusted complete native collection precedes private release generation capture."""

from dataclasses import replace
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext

from maru.audit.models import AuditEvent
from maru.scheduling import release_capture as capture
from maru.scheduling.command_support import (
    SchedulingLimitError,
    SchedulingUnavailableError,
)
from maru.scheduling.models import (
    SchedulingReleaseApproval,
    SchedulingReleaseDependencyKey,
)
from maru.scheduling.planning_queries import SchedulingReadRequest
from maru.scheduling.release_catalogs import ReleaseDependencyKind as Kind
from maru.scheduling.release_dependency_rules import ReleaseDependencyHorizon as Horizon
from maru.scheduling.release_inputs import ReleaseCandidateSelection
from maru.scheduling.writer_boundary import scheduling_writer
from maru.workforce.programme_release_queries import ProgrammeReleaseSourceDeniedError
from tests.factories import AccountFactory, CapabilityGrantFactory
from tests.integration.test_programme_current_release_sources import (
    release_scope as release_scope,  # noqa: PLC0414
)
from tests.integration.test_programme_placement_decisions import (
    assessed as assessed,  # noqa: PLC0414
)
from tests.integration.test_programme_release_sources import (
    admitted as admitted,  # noqa: PLC0414
)
from tests.integration.test_scheduling_placements import world as world  # noqa: PLC0414
from tests.integration.test_scheduling_release_preflight import load, ready
from tests.integration.test_scheduling_release_preflight import (
    preflight_scope as preflight_scope,  # noqa: PLC0414
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def capture_scope(preflight_scope):
    return capture_ready_scope(preflight_scope)


def capture_ready_scope(preflight_scope):
    ready(preflight_scope)
    selection = preflight_scope.selection
    preflight_scope.release_selection = ReleaseCandidateSelection(
        selection.candidate_id,
        selection.candidate_revision_id,
        selection.expected_candidate_version,
        load(preflight_scope).snapshot_digest,
    )
    return preflight_scope


def collect(scope, *, request=None, approval_actor_id=None, selection=None):
    request = request or SchedulingReadRequest(
        scope.request.actor_id,
        scope.request.organization_id,
        scope.request.edition_id,
        uuid4(),
    )
    return capture._load_release_sources(
        request,
        selection or scope.release_selection,
        approval_actor_id=approval_actor_id or request.actor_id,
        programme_authorizer=scope.policy,
        scheduling_authorizer=scope.world.policy,
    )


def test_complete_sources_capture_each_native_generation_once_without_approval(
    capture_scope,
):
    with transaction.atomic(), scheduling_writer():
        sources = collect(capture_scope)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM public.maru_scheduling_expected_release_dependencies"
                "(%s, %s, %s, %s)",
                [
                    capture_scope.release_selection.candidate_revision_id,
                    capture_scope.request.actor_id,
                    capture_scope.request.organization_id,
                    capture_scope.request.edition_id,
                ],
            )
            native_references = set(cursor.fetchall())
        assert native_references == {
            (
                row.kind.value,
                row.source_id,
                row.placement_id,
                row.horizon.value,
                row.operational_ends_at,
            )
            for row in sources.references
        }
        assert sources.preflight.eligibility.eligible_for_review
        assert not SchedulingReleaseDependencyKey.objects.exists()
        generations = capture._capture_release_generations(sources)
        repeated = capture._capture_release_generations(sources)
        assert repeated == generations
    assert not SchedulingReleaseApproval.objects.exists()
    assert len(generations) == len(sources.references)
    assert {row.generation for row in generations} == {1}
    assert SchedulingReleaseDependencyKey.objects.count() == len(
        {(row.reference.kind, row.reference.source_id) for row in generations}
    )
    assert {row.reference.kind for row in generations} == {
        Kind.EDITION_OPERATIONAL,
        Kind.PROGRAMME_ITEM,
        Kind.PROGRAMME_HOST_OPERATIONAL,
        Kind.PROGRAMME_HOST_DISCLOSURE,
        Kind.PROGRAMME_PUBLIC_COPY,
        Kind.IDENTITY_ACCOUNT,
        Kind.WORKFORCE_PERSON_OBLIGATIONS,
        Kind.VENUE_PROPERTY,
        Kind.VENUE_MEMBER,
        Kind.VENUE_SELECTION,
        Kind.VENUE_BOOKING,
    }
    assert all(
        row.reference.operational_ends_at is not None
        for row in generations
        if row.reference.horizon is Horizon.OPERATIONAL
    )


def test_complete_person_union_precedes_every_physical_lock(capture_scope):
    approver = AccountFactory()
    original = capture.lock_account_references_for_evidence
    person_sets = []

    def observe(*, account_ids):
        person_sets.append(account_ids)
        return original(account_ids=account_ids)

    with (
        transaction.atomic(),
        CaptureQueriesContext(connection) as captured,
        patch.object(capture, "lock_account_references_for_evidence", observe),
    ):
        collect(capture_scope, approval_actor_id=approver.id)
    assert len(person_sets) == 1
    assert approver.id in person_sets[0]
    assert capture_scope.request.actor_id in person_sets[0]
    assert len(person_sets[0]) >= 4  # Actor, independent reviewer, host, approver.
    sql = [row["sql"] for row in captured if "FOR UPDATE" in row["sql"]]
    first_identity = next(
        i for i, query in enumerate(sql) if 'FROM "identity_account"' in query
    )
    first_physical = next(
        i for i, query in enumerate(sql) if 'FROM "venues_venueproperty"' in query
    )
    assert first_identity < first_physical
    assert all(
        identifier.hex in sql[first_identity].replace("-", "")
        for identifier in person_sets[0]
    ), (person_sets[0], sql[first_identity])


def test_publisher_only_identity_does_not_change_approval_source_membership(
    capture_scope,
):
    publisher = AccountFactory()
    CapabilityGrantFactory(
        organization_id=capture_scope.request.organization_id,
        edition_id=capture_scope.request.edition_id,
        principal=publisher,
        capability_code="workforce.view_shifts",
    )
    with transaction.atomic():
        approved = collect(capture_scope)
    request = SchedulingReadRequest(
        publisher.id,
        capture_scope.request.organization_id,
        capture_scope.request.edition_id,
        uuid4(),
    )
    with transaction.atomic():
        publication = collect(
            capture_scope,
            request=request,
            approval_actor_id=capture_scope.request.actor_id,
        )
    assert publication == approved
    assert publisher.id not in {row.source_id for row in publication.references}


def test_stale_preflight_never_creates_tracking_or_returns_release_sources(
    capture_scope,
):
    with pytest.raises(SchedulingUnavailableError), transaction.atomic():
        collect(
            capture_scope,
            selection=replace(
                capture_scope.release_selection, source_snapshot_digest="0" * 64
            ),
        )
    assert not SchedulingReleaseDependencyKey.objects.exists()


def test_missing_workforce_reference_permission_precedes_person_or_physical_locks(
    capture_scope,
):
    with (
        pytest.raises(ProgrammeReleaseSourceDeniedError),
        transaction.atomic(),
        patch.object(
            capture,
            "collect_programme_release_work_references",
            side_effect=ProgrammeReleaseSourceDeniedError,
        ),
        patch.object(capture, "lock_account_references_for_evidence") as people,
        patch.object(capture, "lock_venue_release_sources") as venues,
    ):
        collect(capture_scope)
    people.assert_not_called()
    venues.assert_not_called()


def test_moved_person_set_cannot_acquire_a_late_new_lock(capture_scope):
    original = capture.collect_programme_release_person_references
    calls = 0

    def moved(*args, **kwargs):
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        return (
            replace(result, account_ids=(*result.account_ids, uuid4()))
            if calls == 2
            else result
        )

    with (
        pytest.raises(SchedulingUnavailableError),
        transaction.atomic(),
        patch.object(capture, "collect_programme_release_person_references", moved),
        patch.object(capture, "lock_venue_release_sources") as venues,
    ):
        collect(capture_scope)
    venues.assert_not_called()
    assert not SchedulingReleaseDependencyKey.objects.exists()


def test_dependency_bound_aborts_complete_collection_without_partial_state(
    capture_scope,
):
    with (
        pytest.raises(SchedulingLimitError),
        transaction.atomic(),
        patch.object(capture, "MAX_RELEASE_DEPENDENCY_USES", 1),
    ):
        collect(capture_scope)
    assert not SchedulingReleaseDependencyKey.objects.exists()


def test_generation_capture_and_all_read_audits_roll_back_together(capture_scope):
    before = AuditEvent.objects.count()

    def fail_after_capture():
        capture._capture_release_generations(collect(capture_scope))
        assert SchedulingReleaseDependencyKey.objects.exists()
        raise RuntimeError("Synthetic release failure")

    with (
        pytest.raises(RuntimeError, match="Synthetic release failure"),
        transaction.atomic(),
        scheduling_writer(),
    ):
        fail_after_capture()
    assert not SchedulingReleaseDependencyKey.objects.exists()
    assert AuditEvent.objects.count() == before
