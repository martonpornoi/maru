"""Native staffing choices are independently authorized, bounded and person-free."""

from dataclasses import asdict, replace
from uuid import uuid4

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from maru.audit.models import AuditEvent
from maru.workforce import programme_staffing_choices as choices
from maru.workforce.programme_impact import ProgrammeStaffingAction
from maru.workforce.programme_staffing_inputs import ProgrammeStaffingBindingChange
from maru.workforce.programme_staffing_queries import (
    ProgrammeStaffingDeniedError,
    ProgrammeStaffingUnavailableError,
)
from maru.workforce.shift_commands import create_shift_demand
from tests.factories import CapabilityGrantFactory
from tests.integration.test_programme_staffing_selection import (
    selection as selection,  # noqa: PLC0414
)
from tests.integration.test_scheduling_placements import world as world  # noqa: PLC0414
from tests.integration.test_workforce_programme_binding import apply, shift_attribution
from tests.integration.test_workforce_programme_binding import (
    binding_world as binding_world,  # noqa: PLC0414
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def choice_world(binding_world, monkeypatch):
    scope = binding_world
    CapabilityGrantFactory(
        organization=scope.edition.organization,
        edition=scope.edition,
        principal=scope.actor,
        capability_code="workforce.view_structure",
    )
    monkeypatch.setattr(choices, "profile_allows_adapter", lambda *_args: True)
    return scope


def arguments(scope):
    return {
        "actor_id": scope.actor.id,
        "organization_id": scope.edition.organization_id,
        "edition_id": scope.edition.id,
        "correlation_id": uuid4(),
    }


def demands(scope):
    return choices.list_programme_linkable_demands(
        **arguments(scope), expectation=scope.selection.terms
    )


def test_position_catalog_contains_only_independently_authorized_owner_labels(
    choice_world,
):
    scope = choice_world
    with CaptureQueriesContext(connection) as captured:
        rows = choices.list_programme_staffing_positions(**arguments(scope))
    assert scope.selection.terms.position_id in {row.id for row in rows}
    assert all(set(asdict(row)) == {"id", "title", "department_label"} for row in rows)
    selects = " ".join(
        q["sql"] for q in captured if q["sql"].lstrip().upper().startswith("SELECT")
    )
    assert '"workforce_positionassignment"' not in selects
    assert '"workforce_shiftcommitment"' not in selects
    assert (
        AuditEvent.objects.filter(
            operation="workforce.programme_staffing.positions"
        ).count()
        == 1
    )


def test_demand_choices_match_all_terms_and_exclude_retained_binding_lineage(
    choice_world,
):
    scope = choice_world
    assert demands(scope) == ()
    exact = create_shift_demand(
        **shift_attribution(scope), **asdict(scope.selection.terms)
    )
    create_shift_demand(
        **shift_attribution(scope),
        **asdict(replace(scope.selection.terms, briefing="Different work")),
    )
    (row,) = demands(scope)
    assert row.id == exact.demand_id
    assert row.version == exact.resulting_version
    assert "briefing" not in asdict(row)
    apply(
        scope,
        ProgrammeStaffingBindingChange(
            ProgrammeStaffingAction.LINK,
            scope.selection.source,
            demand_id=exact.demand_id,
            expected_demand_version=1,
        ),
    )
    assert demands(scope) == ()


def test_position_field_denial_is_not_replaced_by_shift_management(
    choice_world, monkeypatch
):
    original = choices.decide_verified_principal_exact_edition
    monkeypatch.setattr(
        choices,
        "decide_verified_principal_exact_edition",
        lambda **kwargs: replace(original(**kwargs), fields=frozenset({"positions"})),
    )
    with pytest.raises(ProgrammeStaffingDeniedError):
        choices.list_programme_staffing_positions(**arguments(choice_world))


def test_current_profile_denies_position_catalog_before_disclosure(
    choice_world, monkeypatch
):
    monkeypatch.setattr(choices, "profile_allows_adapter", lambda *_args: False)
    with pytest.raises(ProgrammeStaffingDeniedError):
        choices.list_programme_staffing_positions(**arguments(choice_world))


def test_choice_overflow_never_silently_truncates_the_catalog(
    choice_world, monkeypatch
):
    scope = choice_world
    monkeypatch.setattr(choices, "MAX_STRUCTURE_POSITIONS", 0)
    with pytest.raises(ProgrammeStaffingUnavailableError):
        choices.list_programme_staffing_positions(**arguments(scope))
    create_shift_demand(**shift_attribution(scope), **asdict(scope.selection.terms))
    monkeypatch.setattr(choices, "MAX_SHIFT_DEMANDS", 0)
    with pytest.raises(ProgrammeStaffingUnavailableError):
        demands(scope)


def test_choice_audit_failure_prevents_both_catalog_disclosures(
    choice_world, monkeypatch
):
    scope = choice_world
    before = AuditEvent.objects.count()

    def fail(*_args, **_kwargs):
        raise RuntimeError("Synthetic choice audit failure")

    monkeypatch.setattr(choices, "append_audit", fail)
    with pytest.raises(RuntimeError, match="Synthetic choice audit failure"):
        choices.list_programme_staffing_positions(**arguments(scope))
    with pytest.raises(RuntimeError, match="Synthetic choice audit failure"):
        demands(scope)
    assert AuditEvent.objects.count() == before
