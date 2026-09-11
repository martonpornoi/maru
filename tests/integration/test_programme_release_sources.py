"""Real owner projections retain exact sources without granting release authority."""

from dataclasses import asdict, replace
from uuid import uuid4

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from maru.audit.models import AuditEvent
from maru.authorization.policy import PolicyDecision
from maru.effects.models import DomainEvent
from maru.programme.models import ProgrammePlacementDecision
from maru.scheduling import release_candidate_queries as candidates
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.planning_queries import SchedulingReadRequest
from maru.venues import accessibility_queries as physical
from maru.venues.scheduling_queries import VenueSchedulingSourceDeniedError
from tests.integration.test_scheduling_placements import (
    candidate_revision,
    member,
    place,
)
from tests.integration.test_scheduling_placements import world as world  # noqa: PLC0414

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def admitted(world, monkeypatch):
    monkeypatch.setattr(candidates, "profile_allows_adapter", lambda *_args: True)
    monkeypatch.setattr(physical, "profile_allows_adapter", lambda *_args: True)
    monkeypatch.setattr(
        physical,
        "decide_verified_principal_exact_resource",
        lambda **kwargs: PolicyDecision(
            allowed=True,
            fields=kwargs["requested_fields"],
            obligations=frozenset({"audit_sensitive_read"}),
            reason_code="synthetic_exact_release_source",
        ),
    )


def _request(world):
    return SchedulingReadRequest(
        world.request.actor_id,
        world.request.organization_id,
        world.request.edition_id,
        uuid4(),
    )


def _candidate(world, placed, **overrides):
    arguments = {
        "candidate_id": placed.object_id,
        "candidate_revision_id": candidate_revision(placed).id,
        "expected_candidate_version": placed.version,
        "authorizer": world.policy,
    }
    return candidates.load_release_candidate_source(
        _request(world), **(arguments | overrides)
    )


def _physical(world, **overrides):
    return physical.load_venue_accessibility_sources(
        **(
            {
                "actor_id": world.request.actor_id,
                "organization_id": world.request.organization_id,
                "edition_id": world.request.edition_id,
                "selection_ids": (world.placement.space_selection_id,),
                "correlation_id": uuid4(),
            }
            | overrides
        )
    )


def test_exact_sources_are_complete_audited_and_do_not_write_decisions(world, admitted):
    placed = place(world)
    before = DomainEvent.objects.count()
    source = _candidate(world, placed)
    assert source.revision_id == candidate_revision(placed).id
    assert tuple(row.id for row in source.placements) == (member(placed).placement_id,)
    assert source.placements[0].occurrence.id == world.occurrence.object_id
    assert source.placements[0].envelope == world.placement.envelope
    with CaptureQueriesContext(connection) as queries:
        (physical_source,) = _physical(world)
    assert physical_source.selection_id == world.placement.space_selection_id
    assert physical_source.members
    assert len(physical_source.evidence_digest) == 64
    assert physical_source == _physical(world)[0]
    serialized = str(asdict(physical_source))
    assert "contact_email" not in serialized
    assert "internal_description" not in serialized
    assert all("internal_description" not in q["sql"] for q in queries)
    assert not ProgrammePlacementDecision.objects.exists()
    assert DomainEvent.objects.count() == before
    assert AuditEvent.objects.filter(
        operation="scheduling.query.release_candidate_source"
    ).exists()
    assert AuditEvent.objects.filter(
        operation="venues.query.accessibility_configuration"
    ).exists()


@pytest.mark.parametrize("field", ["candidate_id", "candidate_revision_id"])
def test_unknown_candidate_identity_is_unavailable(world, admitted, field):
    placed = place(world)
    with pytest.raises(SchedulingUnavailableError):
        _candidate(world, placed, **{field: uuid4()})


def test_source_requires_exact_current_candidate_version(world, admitted):
    placed = place(world)
    with pytest.raises(SchedulingUnavailableError):
        _candidate(world, placed, expected_candidate_version=placed.version + 1)


def test_current_profiles_do_not_admit_either_new_source(world):
    placed = place(world)
    with pytest.raises(SchedulingAuthorizationDeniedError):
        _candidate(world, placed)
    with pytest.raises(VenueSchedulingSourceDeniedError):
        _physical(world)


def test_physical_conflict_field_does_not_grant_accessibility_details(
    world, admitted, monkeypatch
):
    monkeypatch.setattr(
        physical,
        "decide_verified_principal_exact_resource",
        lambda **_kwargs: PolicyDecision(
            allowed=True,
            fields=frozenset({"physical_dependencies"}),
            obligations=frozenset(),
            reason_code="synthetic_insufficient_field_ceiling",
        ),
    )
    with pytest.raises(VenueSchedulingSourceDeniedError):
        _physical(world)


def test_missing_or_mixed_physical_selection_never_returns_partial(world, admitted):
    for ids in ((uuid4(),), (world.placement.space_selection_id, uuid4())):
        with pytest.raises(VenueSchedulingSourceDeniedError):
            _physical(world, selection_ids=ids)


def test_foreign_candidate_scope_is_denied_before_disclosure(world, admitted):
    placed = place(world)
    with pytest.raises(SchedulingAuthorizationDeniedError):
        candidates.load_release_candidate_source(
            replace(_request(world), organization_id=uuid4()),
            candidate_id=placed.object_id,
            candidate_revision_id=candidate_revision(placed).id,
            expected_candidate_version=placed.version,
            authorizer=world.policy,
        )


def test_required_physical_audit_failure_releases_no_source(
    world, admitted, monkeypatch
):
    def unavailable(*_args, **_kwargs):
        raise RuntimeError("synthetic required audit failure")

    monkeypatch.setattr(physical, "append_audit", unavailable)
    with pytest.raises(RuntimeError, match="synthetic required audit failure"):
        _physical(world)
