"""Real native staffing forms reuse exact owner commands without runtime activation."""

from dataclasses import asdict, replace
from functools import partial

import pytest

from maru.programme import authorization as programme_policy
from maru.programme import queries as programme_queries
from maru.programme.models import (
    ProgrammeStaffingRequirement,
    ProgrammeStaffingRevision,
)
from maru.scheduling import planning_staffing_workspace as staffing
from maru.scheduling import planning_views as views
from maru.scheduling import planning_workspace as workspace
from maru.workforce import programme_queries as coverage_queries
from maru.workforce import programme_staffing_choices as choices
from maru.workforce.models import ProgrammeShiftBinding, ShiftDemand
from maru.workforce.programme_staffing_queries import ProgrammeStaffingUnavailableError
from maru.workforce.shift_commands import create_shift_demand, open_shift_demand
from tests.factories import CapabilityGrantFactory
from tests.integration.test_programme_staffing_selection import (
    selection as selection,  # noqa: PLC0414
)
from tests.integration.test_scheduling_candidates import (
    native_http_intent,
    native_http_request,
    native_http_selection,
)
from tests.integration.test_scheduling_placements import moved, place
from tests.integration.test_scheduling_placements import world as world  # noqa: PLC0414
from tests.integration.test_workforce_programme_binding import (
    binding_world as binding_world,  # noqa: PLC0414
)
from tests.integration.test_workforce_programme_binding import shift_attribution

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def staffing_http_world(binding_world, monkeypatch):
    scope = binding_world
    for capability in ("venues.view_workspace", "workforce.view_structure"):
        CapabilityGrantFactory(
            principal=scope.actor,
            organization=scope.edition.organization,
            edition=scope.edition,
            capability_code=capability,
        )
    policy = scope.selection.policy
    monkeypatch.setattr(
        workspace,
        "list_programme_timetable_items",
        partial(
            programme_queries.list_programme_timetable_items,
            authorizer=policy,
        ),
    )
    for name in (
        "load_programme_staffing_requirements",
        "load_programme_staffing_history",
        "load_programme_bindings",
        "load_programme_binding_history",
    ):
        monkeypatch.setattr(
            staffing, name, partial(getattr(staffing, name), authorizer=policy)
        )
    monkeypatch.setattr(
        staffing,
        "authorize_programme_scope",
        partial(
            programme_policy.authorize_programme_scope,
            authorizer=policy,
        ),
    )
    monkeypatch.setattr(
        staffing,
        "load_planning_staffing",
        partial(
            staffing.load_planning_staffing,
            programme_authorizer=policy,
        ),
    )
    for name in (
        "submit_planning_staffing_requirement",
        "submit_planning_staffing_binding",
    ):
        monkeypatch.setattr(
            views, name, partial(getattr(views, name), programme_authorizer=policy)
        )
    monkeypatch.setattr(choices, "profile_allows_adapter", lambda *_args: True)
    monkeypatch.setattr(coverage_queries, "profile_allows_adapter", lambda *_args: True)
    return scope


def open_task(scope, mode, **kwargs):
    world = scope.selection.world
    return native_http_request(world, native_http_selection(world, mode=mode, **kwargs))


def selected_requirement(scope):
    return {"requirement_id": scope.selection.source.requirement_id}


def test_native_requirement_create_replay_revise_and_retire_keep_history(
    staffing_http_world,
):
    scope = staffing_http_world
    world = scope.selection.world
    opened = open_task(scope, "staffing_create")
    terms = asdict(scope.selection.terms)
    terms.update(
        title="Separate stage clean-up",
        starts_at=scope.selection.terms.starts_at.isoformat(timespec="minutes"),
        ends_at=scope.selection.terms.ends_at.isoformat(timespec="minutes"),
    )
    payload = native_http_intent(opened, action="staffing_create", **terms)
    saved = native_http_request(world, payload)
    assert saved.status_code == 200, saved.content.decode()
    created = saved.context_data["selection"].requirement_id
    assert created != scope.selection.source.requirement_id
    assert ProgrammeStaffingRequirement.objects.count() == 2
    replay = native_http_request(world, payload)
    assert replay.status_code == 200, replay.content.decode()
    assert "no duplicate change" in replay.context_data["status_message"]
    revised = open_task(scope, "staffing_revise", requirement_id=created)
    payload = native_http_intent(
        revised, action="staffing_revise", title="Revised clean-up instructions"
    )
    assert native_http_request(world, payload).status_code == 200
    retired = open_task(scope, "staffing_retire", requirement_id=created)
    payload = native_http_intent(retired, action="staffing_retire", confirm="on")
    response = native_http_request(world, payload)
    assert response.status_code == 200, response.content.decode()
    requirement = ProgrammeStaffingRequirement.objects.get(id=created)
    assert (requirement.version, requirement.lifecycle) == (3, "retired")
    assert ProgrammeStaffingRevision.objects.filter(requirement_id=created).count() == 3
    assert not ShiftDemand.objects.exists()
    history = open_task(
        scope,
        "staffing_requirement_history",
        requirement_id=created,
        staffing_through_version=3,
    )
    assert history.status_code == 200, history.content.decode()
    assert len(history.context_data["staffing_history"].entries) == 3
    assert b"Fixed inclusive ceiling: version 3" in history.content


def test_native_preview_apply_and_same_intent_replay_never_duplicate_work(
    staffing_http_world,
):
    scope = staffing_http_world
    world = scope.selection.world
    opened = open_task(scope, "staffing_create_work", **selected_requirement(scope))
    preview_input = native_http_intent(opened, action="staffing_preview")
    preview = native_http_request(world, preview_input)
    assert preview.status_code == 200, preview.content.decode()
    assert preview.context_data["staffing_preview"].impact.action == "create"
    assert b"Review exact work impact" in preview.content
    assert not ShiftDemand.objects.exists()
    apply_input = native_http_intent(preview, action="staffing_apply", confirm="on")
    saved = native_http_request(world, apply_input)
    assert saved.status_code == 200, saved.content.decode()
    assert ShiftDemand.objects.count() == ProgrammeShiftBinding.objects.count() == 1
    assert ShiftDemand.objects.get().status == "draft"
    replay = native_http_request(world, apply_input)
    assert replay.status_code == 200, replay.content.decode()
    assert "no duplicate change" in replay.context_data["status_message"]
    assert ShiftDemand.objects.count() == 1
    binding = ProgrammeShiftBinding.objects.get()
    history = open_task(
        scope,
        "staffing_binding_history",
        binding_id=binding.id,
        staffing_through_version=1,
        **selected_requirement(scope),
    )
    assert history.status_code == 200, history.content.decode()
    assert (
        history.context_data["staffing_history"].entries[0].binding.demand_id
        == binding.demand_id
    )


def test_native_missing_impact_confirmation_is_recoverable_without_writes(
    staffing_http_world,
):
    scope = staffing_http_world
    opened = open_task(scope, "staffing_create_work", **selected_requirement(scope))
    preview = native_http_request(
        scope.selection.world, native_http_intent(opened, action="staffing_preview")
    )
    payload = native_http_intent(preview, action="staffing_apply", confirm="")
    denied = native_http_request(scope.selection.world, payload)
    assert denied.status_code == 400, denied.content.decode()
    assert "confirm" in denied.context_data["control"].form.errors
    assert denied.context_data["control"].form.data["retry_key"] == payload["retry_key"]
    assert not ShiftDemand.objects.exists()


def test_native_movement_rejects_old_source_without_rebasing_or_writing(
    staffing_http_world,
):
    scope = staffing_http_world
    world = scope.selection.world
    opened = open_task(scope, "staffing_create_work", **selected_requirement(scope))
    payload = native_http_intent(opened, action="staffing_preview")
    place(world, intent=moved(world), version=scope.selection.placed.version)
    rejected = native_http_request(world, payload)
    assert rejected.status_code == 409, rejected.content.decode()
    form = rejected.context_data["control"].form
    assert form.data["candidate_revision_id"] == payload["candidate_revision_id"]
    assert form.data["retry_key"] == payload["retry_key"]
    assert not ShiftDemand.objects.exists()


def test_native_read_authority_can_preview_but_not_apply_work(
    staffing_http_world, monkeypatch
):
    scope = staffing_http_world
    original = scope.selection.policy.authorize

    def read_only(**kwargs):
        decision = original(**kwargs)
        return (
            replace(decision, allowed=False)
            if kwargs["capability_code"] == "programme.manage_staffing"
            else decision
        )

    monkeypatch.setattr(scope.selection.policy, "authorize", read_only)
    opened = open_task(scope, "staffing_create_work", **selected_requirement(scope))
    preview = native_http_request(
        scope.selection.world, native_http_intent(opened, action="staffing_preview")
    )
    assert preview.status_code == 200, preview.content.decode()
    assert not preview.context_data["staffing_can_apply"]
    assert b'value="staffing_apply"' not in preview.content
    forbidden = native_http_request(
        scope.selection.world,
        native_http_intent(preview, action="staffing_apply", confirm="on"),
    )
    assert forbidden.status_code == 403
    assert not ShiftDemand.objects.exists()


def apply_work_task(scope, mode, **selection):
    opened = open_task(scope, mode, **selected_requirement(scope), **selection)
    preview = native_http_request(
        scope.selection.world, native_http_intent(opened, action="staffing_preview")
    )
    payload = native_http_intent(preview, action="staffing_apply", confirm="on")
    saved = native_http_request(scope.selection.world, payload)
    assert saved.status_code == 200, saved.content.decode()
    return saved


def test_native_link_reconcile_and_explicit_successor_preserve_work_lineage(
    staffing_http_world,
):
    scope = staffing_http_world
    draft = create_shift_demand(
        **shift_attribution(scope), **asdict(scope.selection.terms)
    )
    choices_page = open_task(scope, "staffing_link_work", **selected_requirement(scope))
    assert choices_page.context_data["control"].form is None
    assert [row.id for row in choices_page.context_data["staffing_demand_choices"]] == [
        draft.demand_id
    ]
    apply_work_task(scope, "staffing_link_work", demand_id=draft.demand_id)
    revised = open_task(scope, "staffing_revise", **selected_requirement(scope))
    saved = native_http_request(
        scope.selection.world,
        native_http_intent(revised, action="staffing_revise", briefing="Updated work"),
    )
    assert saved.status_code == 200
    assert saved.context_data["staffing_rows"][0]["coverage"].source_state == "stale"
    apply_work_task(scope, "staffing_reconcile_work")
    predecessor = ShiftDemand.objects.get(id=draft.demand_id)
    assert predecessor.briefing == "Updated work"
    open_shift_demand(
        **shift_attribution(scope),
        demand_id=predecessor.id,
        expected_version=predecessor.command_version,
    )
    opened = open_task(scope, "staffing_successor_work", **selected_requirement(scope))
    preview = native_http_request(
        scope.selection.world, native_http_intent(opened, action="staffing_preview")
    )
    assert b"explicitly cancels the predecessor" in preview.content
    payload = native_http_intent(preview, action="staffing_apply", confirm="on")
    assert native_http_request(scope.selection.world, payload).status_code == 200
    predecessor.refresh_from_db()
    assert predecessor.status == "cancelled"
    binding = ProgrammeShiftBinding.objects.get()
    assert binding.version == 3
    assert binding.demand_id != predecessor.id
    assert ShiftDemand.objects.get(id=binding.demand_id).status == "draft"


def test_native_post_commit_reload_failure_has_exact_retry_recovery(
    staffing_http_world, monkeypatch
):
    scope = staffing_http_world
    opened = open_task(scope, "staffing_create_work", **selected_requirement(scope))
    preview = native_http_request(
        scope.selection.world, native_http_intent(opened, action="staffing_preview")
    )
    payload = native_http_intent(preview, action="staffing_apply", confirm="on")
    original = views._command_response

    def unavailable(*_args, **_kwargs):
        raise ProgrammeStaffingUnavailableError

    monkeypatch.setattr(views, "_command_response", unavailable)
    response = native_http_request(scope.selection.world, payload)
    assert response.status_code == 503
    assert b"Do not assume a submitted change failed" in response.content
    assert ShiftDemand.objects.count() == ProgrammeShiftBinding.objects.count() == 1
    monkeypatch.setattr(views, "_command_response", original)
    replay = native_http_request(scope.selection.world, payload)
    assert replay.status_code == 200
    assert "no duplicate change" in replay.context_data["status_message"]
    assert ShiftDemand.objects.count() == 1


@pytest.mark.parametrize("admitted", [False, True])
def test_native_forged_or_csrf_denied_write_releases_no_staffing_context(
    staffing_http_world, admitted
):
    scope = staffing_http_world
    opened = open_task(scope, "staffing_create_work", **selected_requirement(scope))
    payload = native_http_intent(opened, action="staffing_preview")
    denied = native_http_request(
        scope.selection.world,
        payload,
        admitted=admitted,
        valid_csrf=not admitted,
    )
    assert denied.status_code == 403
    assert scope.selection.terms.briefing.encode() not in denied.content
    assert not ShiftDemand.objects.exists()
