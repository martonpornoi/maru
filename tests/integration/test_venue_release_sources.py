"""Release capture retains the complete authorized physical lock closure."""

from dataclasses import asdict, replace
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext

from maru.audit.models import AuditEvent
from maru.scheduling.models import SchedulingReleaseDependencyKey
from maru.venues import release_queries as sources
from maru.venues import scheduling_queries
from maru.venues.scheduling_queries import (
    VenueSchedulingSourceDeniedError,
    VenueSchedulingSourceUnavailableError,
)
from tests.integration.test_venue_scheduling_source import (
    admitted as admitted,  # noqa: PLC0414
)
from tests.integration.test_venue_scheduling_source import (
    world as world,  # noqa: PLC0414
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def collect(world, **overrides):
    scope, space = world
    return sources.lock_venue_release_sources(
        **(
            {
                "actor_id": scope.scheduler.id,
                "organization_id": scope.edition.organization_id,
                "edition_id": scope.edition.id,
                "selection_ids": (space.id,),
                "placement_ids": (),
                "correlation_id": uuid4(),
            }
            | overrides
        )
    )


def test_capture_requires_enclosing_transaction(world, admitted):
    with pytest.raises(VenueSchedulingSourceUnavailableError):
        collect(world)


def test_repeatable_read_cannot_miss_newly_committed_sources(world, admitted):
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        with pytest.raises(VenueSchedulingSourceUnavailableError):
            collect(world)


def test_capture_preserves_dormant_profile_boundary(world):
    with transaction.atomic(), pytest.raises(VenueSchedulingSourceUnavailableError):
        collect(world)


@pytest.mark.parametrize("mismatch", ["organization", "edition", "selection"])
def test_capture_denies_foreign_or_partial_closure_before_physical_locks(
    world, admitted, mismatch
):
    overrides = {
        "organization": {"organization_id": uuid4()},
        "edition": {"edition_id": uuid4()},
        "selection": {"selection_ids": (world[1].id, uuid4())},
    }
    with (
        transaction.atomic(),
        patch.object(sources, "_lock_physical_scope") as physical_lock,
        pytest.raises(VenueSchedulingSourceDeniedError),
    ):
        collect(world, **overrides[mismatch])
    physical_lock.assert_not_called()


def test_capture_returns_only_native_selected_identities_in_canonical_lock_order(
    world, admitted
):
    with transaction.atomic(), CaptureQueriesContext(connection) as captured:
        result = collect(world)
    selection = result.selections[0]
    assert selection.selection_id == world[1].id
    assert selection.member_properties == (
        (world[1].source_space_id, world[1].venue_selection.property_id),
    )
    assert result.snapshot.reservations == ()
    assert len(result.snapshot.spaces) == 1
    assert not SchedulingReleaseDependencyKey.objects.exists()
    lock_queries = [row["sql"] for row in captured if "FOR UPDATE" in row["sql"]]
    first_locks = [
        next(
            index for index, sql in enumerate(lock_queries) if f'FROM "{table}"' in sql
        )
        for table in (
            "organizations_organization",
            "organizations_conventionseries",
            "events_eventedition",
            "identity_account",
            "venues_venueproperty",
            "venues_venuespace",
            "venues_editionspaceselection",
        )
    ]
    assert first_locks == sorted(first_locks)
    assert len(set(first_locks)) == len(first_locks)
    assert (
        AuditEvent.objects.filter(
            operation="venues.query.scheduling_dependencies", outcome="allow"
        ).count()
        == 3
    )
    assert all(
        secret not in str(asdict(result))
        for secret in ("Private restriction", "Main Stage", "Private provider contact")
    )


def test_moved_post_lock_snapshot_returns_no_partial_references(world, admitted):
    original = sources.load_venue_scheduling_dependencies
    calls = 0

    def moved(**arguments):
        nonlocal calls
        result = original(**arguments)
        calls += 1
        if calls == 3:
            return replace(result, edition_version=result.edition_version + 1)
        return result

    with (
        transaction.atomic(),
        patch.object(sources, "load_venue_scheduling_dependencies", moved),
        pytest.raises(VenueSchedulingSourceUnavailableError),
    ):
        collect(world)
    assert not AuditEvent.objects.filter(
        operation="venues.query.scheduling_dependencies", outcome="allow"
    ).exists()
    assert not SchedulingReleaseDependencyKey.objects.exists()


def test_late_audit_failure_rolls_back_source_reads(world, admitted):
    original = scheduling_queries.append_audit
    calls = 0

    def fail(record, **arguments):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("Synthetic late release source audit failure")
        return original(record, **arguments)

    with (
        transaction.atomic(),
        patch.object(scheduling_queries, "append_audit", fail),
        pytest.raises(RuntimeError, match="late release source audit"),
    ):
        collect(world)
    assert not AuditEvent.objects.filter(
        operation="venues.query.scheduling_dependencies", outcome="allow"
    ).exists()
