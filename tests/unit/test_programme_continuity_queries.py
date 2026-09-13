"""Fast orchestration proofs; native lock/audit races remain separately deferred."""

from contextlib import nullcontext
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.db import DatabaseError

from maru.events.queries import EditionAdoptionProfileReference
from maru.scheduling import continuity_queries as queries
from maru.scheduling.adoption import SCHEDULING_CONTINUITY_ADAPTER
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.continuity_protocol import ContinuityScope


@pytest.fixture
def boundary(monkeypatch):
    mocks = {}
    for name in (
        "edition_adoption_profile_reference",
        "profile_allows_adapter",
        "load_public_programme_timetable",
        "load_personal_timetable",
        "load_operator_run_sheet",
        "public_continuity_projection",
        "personal_continuity_projection",
        "operator_continuity_projection",
    ):
        mocks[name] = Mock()
        monkeypatch.setattr(queries, name, mocks[name])
    mocks[
        "edition_adoption_profile_reference"
    ].return_value = EditionAdoptionProfileReference("synthetic", 1)
    mocks["profile_allows_adapter"].return_value = True
    monkeypatch.setattr(queries.transaction, "atomic", nullcontext)
    return mocks


@pytest.fixture(params=["public", "exact_person", "private_operator"])
def scope(request):
    if request.param == "public":
        return ContinuityScope(UUID(int=1), UUID(int=2), "public")
    return ContinuityScope(
        UUID(int=1),
        UUID(int=2),
        request.param,
        UUID(int=3),
        "personal" if request.param == "exact_person" else "room",
        None if request.param == "exact_person" else UUID(int=4),
        () if request.param == "exact_person" else ("technical",),
    )


def test_unpinned_continuity_stops_before_any_owner_lookup(boundary, scope):
    boundary["profile_allows_adapter"].return_value = False
    with pytest.raises(SchedulingAuthorizationDeniedError):
        queries.load_continuity_projection(scope, correlation_id=UUID(int=8))
    for name in (
        "load_public_programme_timetable",
        "load_personal_timetable",
        "load_operator_run_sheet",
    ):
        boundary[name].assert_not_called()
    boundary["profile_allows_adapter"].assert_called_once_with(
        "synthetic", 1, SCHEDULING_CONTINUITY_ADAPTER
    )


def test_exact_owner_routing_and_final_admission(boundary, scope):
    result = queries.load_continuity_projection(scope, correlation_id=UUID(int=8))
    ownership = {
        "organization_id": scope.organization_id,
        "edition_id": scope.edition_id,
    }
    if scope.audience == "public":
        boundary["load_public_programme_timetable"].assert_called_once_with(**ownership)
        boundary["load_personal_timetable"].assert_not_called()
        boundary["load_operator_run_sheet"].assert_not_called()
        assert result is boundary["public_continuity_projection"].return_value
    elif scope.audience == "exact_person":
        boundary["load_personal_timetable"].assert_called_once_with(
            **ownership, actor_id=scope.actor_id, correlation_id=UUID(int=8)
        )
        boundary["load_public_programme_timetable"].assert_not_called()
        boundary["load_operator_run_sheet"].assert_not_called()
        assert result is boundary["personal_continuity_projection"].return_value
    else:
        call = boundary["load_operator_run_sheet"].call_args
        assert call.args[0].actor_id == scope.actor_id
        assert call.args[0].target_id == scope.target_id
        assert call.args[0].correlation_id == UUID(int=8)
        assert call.kwargs == {"layers": frozenset({"technical"})}
        boundary["load_public_programme_timetable"].assert_not_called()
        boundary["load_personal_timetable"].assert_not_called()
        assert result is boundary["operator_continuity_projection"].return_value
    assert boundary["edition_adoption_profile_reference"].call_count == 2


def test_late_adoption_denial_returns_no_snapshot(boundary, scope):
    boundary["profile_allows_adapter"].side_effect = [True, False]
    with pytest.raises(SchedulingAuthorizationDeniedError):
        queries.load_continuity_projection(scope, correlation_id=UUID(int=8))


def test_profile_change_and_database_failure_never_return_last_good(boundary, scope):
    boundary["edition_adoption_profile_reference"].side_effect = [
        EditionAdoptionProfileReference("synthetic", 1),
        EditionAdoptionProfileReference("synthetic", 2),
    ]
    with pytest.raises(SchedulingUnavailableError):
        queries.load_continuity_projection(scope, correlation_id=UUID(int=8))
    boundary["edition_adoption_profile_reference"].side_effect = DatabaseError(
        "synthetic"
    )
    with pytest.raises(SchedulingUnavailableError):
        queries.load_continuity_projection(scope, correlation_id=UUID(int=8))


@pytest.mark.parametrize(
    "error", [SchedulingAuthorizationDeniedError, SchedulingUnavailableError]
)
def test_owner_failure_is_not_replaced_by_another_audience(boundary, scope, error):
    for name in (
        "load_public_programme_timetable",
        "load_personal_timetable",
        "load_operator_run_sheet",
    ):
        boundary[name].side_effect = error
    with pytest.raises(error):
        queries.load_continuity_projection(scope, correlation_id=UUID(int=8))
    for name in (
        "public_continuity_projection",
        "personal_continuity_projection",
        "operator_continuity_projection",
    ):
        boundary[name].assert_not_called()
