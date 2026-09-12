"""Modular exact-person composition keeps retained work independent of Programme."""

from dataclasses import replace
from unittest.mock import patch

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from maru.scheduling import personal_output_queries as outputs
from maru.scheduling import personal_output_rendering as formats
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.command_support import SchedulingUnavailableError
from maru.workforce.shift_commands import (
    ShiftAuthorizationDeniedError,
    ShiftUnavailableError,
)
from tests.integration.test_workforce_programme_personal_inputs import excluded_counts
from tests.integration.test_workforce_timetable_outputs import accepted_work, arguments
from tests.integration.test_workforce_timetable_outputs import (
    scope as scope,  # noqa: PLC0414
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def test_real_workforce_only_composition_has_no_programme_queries_or_side_effects(
    scope,
):
    demand, commitment = accepted_work(scope)
    before = excluded_counts()
    assert all(value == 0 for value in before.values())
    with CaptureQueriesContext(connection) as captured:
        result = outputs.load_personal_timetable(**arguments(scope))
    assert result.hosting is None
    assert result.actor_id == scope.person.id
    assert result.edition_id == scope.edition.id
    assert result.zone_name == scope.edition.time_zone
    assert result.edition_label.name == scope.edition.name
    assert result.edition_label.version == scope.edition.aggregate_version
    assert len(result.shifts) == 1
    (work,) = result.shifts
    assert work.commitment_id == commitment.id
    assert work.starts_at == commitment.starts_at
    assert work.ends_at == commitment.ends_at
    assert work.instructions.demand_id == demand.id
    assert work.status == "confirmed"
    assert b'"hosting":null' in formats.render_personal_timetable_json(result)
    assert (
        b"X-MARU-HOST-RELEASE-STATE:unadopted"
        in formats.render_personal_timetable_calendar(result)
    )
    assert excluded_counts() == before
    statements = "\n".join(row["sql"] for row in captured)
    for excluded in (
        'FROM "programme_',
        'FROM "scheduling_',
        'FROM "participation_',
        'FROM "registration_',
    ):
        assert excluded not in statements


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ShiftAuthorizationDeniedError, SchedulingAuthorizationDeniedError),
        (ShiftUnavailableError, SchedulingUnavailableError),
    ],
)
def test_adopted_work_failure_is_not_silently_labeled_unadopted_or_empty(
    scope, error, expected
):
    with (
        patch.object(outputs, "load_personal_shift_timetable", side_effect=error),
        pytest.raises(expected),
    ):
        outputs.load_personal_timetable(**arguments(scope))


def test_changed_retained_work_withholds_complete_composition(scope):
    accepted_work(scope)
    original = outputs.load_personal_shift_timetable
    count = 0

    def changing(**kwargs):
        nonlocal count
        count += 1
        rows = original(**kwargs)
        return rows if count == 1 else (replace(rows[0], version=rows[0].version + 1),)

    with (
        patch.object(outputs, "load_personal_shift_timetable", side_effect=changing),
        pytest.raises(SchedulingUnavailableError),
    ):
        outputs.load_personal_timetable(**arguments(scope))


def test_empty_personal_scope_does_not_discover_an_edition_label(scope):
    with patch.object(outputs, "resolve_personal_timetable_edition_label") as label:
        result = outputs.load_personal_timetable(**arguments(scope))
    assert result.shifts == ()
    assert result.edition_label is None
    label.assert_not_called()


def test_missing_edition_context_withholds_nonempty_personal_timetable(scope):
    accepted_work(scope)
    with (
        patch.object(
            outputs, "resolve_personal_timetable_edition_label", return_value=None
        ),
        pytest.raises(SchedulingUnavailableError),
    ):
        outputs.load_personal_timetable(**arguments(scope))


def test_partial_host_adoption_is_unavailable_not_a_silently_missing_layer(
    scope, monkeypatch
):
    original = outputs.profile_allows_capability
    monkeypatch.setattr(
        outputs,
        "profile_allows_capability",
        lambda code, version, capability: (
            capability == "scheduling.view_host_self"
            or original(code, version, capability)
        ),
    )
    with pytest.raises(SchedulingUnavailableError):
        outputs.load_personal_timetable(**arguments(scope))
