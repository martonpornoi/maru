"""Real exact-purpose operator reads preserve native release and owner ceilings."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from maru.audit.models import AuditEvent
from maru.authorization import policy
from maru.authorization.models import ScopedResourceBinding
from maru.programme.models import ProgrammeItem
from maru.programme.operator_queries import (
    load_operator_delivery_instructions,
    load_operator_programme_copy,
)
from maru.programme.staffing_commands import change_programme_staffing_requirement
from maru.programme.staffing_inputs import (
    ProgrammeStaffingChange,
    ProgrammeStaffingExpectation,
    ProgrammeStaffingSource,
)
from maru.programme.staffing_queries import ProgrammeStaffingReadRequest
from maru.scheduling import operator_scope
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.operator_output_queries import load_operator_run_sheet
from maru.scheduling.operator_release_impact import load_operator_release_impact
from maru.scheduling.operator_release_references import load_operator_release_reference
from maru.scheduling.operator_scope import OperatorReadRequest, OperatorScopeKind
from maru.scheduling.release_inputs import ReleaseCandidateSelection
from maru.venues.models import EditionSpaceSelection
from maru.venues.operator_queries import load_operator_wayfinding
from maru.workforce import operator_links as work_links
from maru.workforce.models import ShiftCommitment, ShiftDemand
from maru.workforce.programme_impact import ProgrammeStaffingAction
from maru.workforce.programme_staffing_inputs import ProgrammeStaffingBindingChange
from maru.workforce.shift_commands import open_shift_demand
from tests.factories import AccountFactory, CapabilityGrantFactory
from tests.integration import test_workforce_shifts as shifts
from tests.integration.test_programme_placement_decisions import (
    apply as assess_placement,
)
from tests.integration.test_programme_staffing_commands import staffing_position
from tests.integration.test_scheduling_public_outputs import (
    admitted as admitted,  # noqa: PLC0414
)
from tests.integration.test_scheduling_public_outputs import (
    assessed as assessed,  # noqa: PLC0414
)
from tests.integration.test_scheduling_public_outputs import (
    capture_scope as capture_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_public_outputs import end_copy
from tests.integration.test_scheduling_public_outputs import (
    preflight_scope as preflight_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_public_outputs import (
    release_scope as release_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_public_outputs import (
    review_scope as review_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_public_outputs import (
    world as world,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_preflight import (
    load as release_preflight,
)
from tests.integration.test_scheduling_release_queries import approve, publish, withdraw
from tests.integration.test_workforce_programme_binding import (
    apply as apply_binding,
)
from tests.integration.test_workforce_programme_binding import (
    create as create_binding,
)
from tests.integration.test_workforce_programme_binding import (
    person_for,
    shift_attribution,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]
BASE_CAPABILITIES = (
    "scheduling.view_operator_output",
    "programme.view_operator_copy",
    "venues.view_operator_wayfinding",
)


@pytest.fixture
def operator_world(review_scope, monkeypatch):
    original = policy.profile_allows_capability
    monkeypatch.setattr(
        policy,
        "profile_allows_capability",
        lambda code, version, capability: (
            capability in operator_scope.OPERATOR_CAPABILITIES
            or original(code, version, capability)
        ),
    )
    monkeypatch.setattr(
        operator_scope,
        "profile_allows_adapter",
        lambda _code, _version, adapter: (
            adapter == "scheduling.operator-release-output@1"
        ),
    )
    return review_scope


def operator_request(
    scope, *, kind=OperatorScopeKind.EDITION, capabilities=BASE_CAPABILITIES
):
    actor = AccountFactory()
    target = scope.request.edition_id
    grants = {
        "organization_id": scope.request.organization_id,
        "edition_id": scope.request.edition_id,
        "principal": actor,
    }
    if kind is not OperatorScopeKind.EDITION:
        space = EditionSpaceSelection.objects.get(
            id=scope.world.placement.space_selection_id
        )
        grants["department_id"] = space.responsible_department_id
        target = space.responsible_department_id
        if kind is OperatorScopeKind.ROOM:
            target = space.id
            grants["resource_binding"] = ScopedResourceBinding.objects.get(
                organization_id=scope.request.organization_id,
                resource_kind=ScopedResourceBinding.ResourceKind.VENUE_EDITION_SPACE,
                resource_id=space.id,
            )
    for capability in capabilities:
        CapabilityGrantFactory(**grants, capability_code=capability)
    return OperatorReadRequest(
        actor.id,
        scope.request.organization_id,
        scope.request.edition_id,
        uuid4(),
        kind,
        target,
    )


@pytest.mark.parametrize("kind", list(OperatorScopeKind))
def test_real_owner_scopes_return_exact_approved_phases_and_reviewed_copy(
    operator_world, kind
):
    published = publish(operator_world, approve(operator_world))
    request = operator_request(operator_world, kind=kind)
    with CaptureQueriesContext(connection) as captured:
        result = load_operator_release_reference(request)
        impact = load_operator_release_impact(request)
        copies = load_operator_programme_copy(
            request, expected_release_id=published.object_id
        )
        rooms = load_operator_wayfinding(
            request, expected_release_id=published.object_id
        )
    assert result.state == "available"
    assert result.release_id == published.object_id
    assert impact.release_id == published.object_id
    assert impact.previous_state == "absent"
    assert impact.changes[0].kind == "added"
    assert impact.changes[0].after == result.occurrences[0]
    assert not result.staffing_adopted
    assert len(result.occurrences) == len(copies) == len(rooms) == 1
    assert result.occurrences[0].envelope == operator_world.world.placement.envelope
    assert copies[0].title == "Synthetic public opening"
    assert rooms[0].space_id == operator_world.world.placement.space_selection_id
    for capability in BASE_CAPABILITIES:
        assert AuditEvent.objects.filter(
            principal_id=request.actor_id,
            capability_code=capability,
            outcome="allow",
            target_id=request.target_id,
        ).exists()
    statements = "\n".join(row["sql"] for row in captured)
    for excluded in (
        'FROM "programme_programmedeliveryrevision"',
        'FROM "programme_programmeworkingrevision"',
        'FROM "programme_programmehostrelationship"',
        'FROM "workforce_shiftcommitment"',
        'FROM "applications_',
        'FROM "participation_',
        'FROM "registration_',
    ):
        assert excluded not in statements


@pytest.mark.parametrize("kind", [OperatorScopeKind.ROOM, OperatorScopeKind.DEPARTMENT])
def test_narrow_grants_cannot_be_widened_to_the_edition(operator_world, kind):
    request = operator_request(operator_world, kind=kind)
    with pytest.raises(SchedulingAuthorizationDeniedError):
        load_operator_release_reference(
            replace(
                request, kind=OperatorScopeKind.EDITION, target_id=request.edition_id
            )
        )


def test_exact_operator_grants_reject_foreign_scope_and_person(operator_world):
    request = operator_request(operator_world)
    for changed in (
        replace(request, organization_id=uuid4()),
        replace(request, edition_id=uuid4()),
        replace(request, target_id=uuid4()),
        replace(request, actor_id=AccountFactory().id),
        replace(request, kind=OperatorScopeKind.ROOM, target_id=uuid4()),
        replace(request, kind=OperatorScopeKind.DEPARTMENT, target_id=uuid4()),
    ):
        with pytest.raises(SchedulingAuthorizationDeniedError):
            load_operator_run_sheet(changed)
        with pytest.raises(SchedulingAuthorizationDeniedError):
            load_operator_release_impact(changed)


def test_each_owner_denies_missing_authority_even_before_any_release(operator_world):
    request = operator_request(
        operator_world, capabilities=("scheduling.view_operator_output",)
    )
    with pytest.raises(SchedulingAuthorizationDeniedError):
        load_operator_programme_copy(request, expected_release_id=None)
    with pytest.raises(SchedulingAuthorizationDeniedError):
        load_operator_wayfinding(request, expected_release_id=None)
    with pytest.raises(SchedulingAuthorizationDeniedError):
        load_operator_delivery_instructions(
            request, expected_release_id=None, fields=frozenset({"technical"})
        )


def test_withdrawal_removes_approved_content_without_last_good_fallback(operator_world):
    published = publish(operator_world, approve(operator_world))
    request = operator_request(operator_world)
    assert load_operator_release_reference(request).occurrences
    withdraw(operator_world, published)
    result = load_operator_release_reference(request)
    assert result.state == "withdrawn"
    assert result.occurrences == ()
    assert load_operator_programme_copy(request, expected_release_id=None) == ()
    assert load_operator_wayfinding(request, expected_release_id=None) == ()
    impact = load_operator_release_impact(request)
    assert impact.state == "withdrawn"
    assert impact.changes is None


def test_successful_owner_audit_is_required_before_content_can_return(operator_world):
    published = publish(operator_world, approve(operator_world))
    request = operator_request(operator_world)
    with (
        patch.object(
            operator_scope,
            "append_audit",
            side_effect=RuntimeError("audit unavailable"),
        ),
        pytest.raises(RuntimeError, match="audit unavailable"),
    ):
        load_operator_programme_copy(request, expected_release_id=published.object_id)


def test_requesting_only_technical_never_selects_accessibility_or_media_columns(
    operator_world,
):
    published = publish(operator_world, approve(operator_world))
    request = operator_request(
        operator_world,
        capabilities=(*BASE_CAPABILITIES, "programme.view_operator_delivery"),
    )
    with CaptureQueriesContext(connection) as captured:
        instructions = load_operator_delivery_instructions(
            request,
            expected_release_id=published.object_id,
            fields=frozenset({"technical"}),
        )
    assert len(instructions) == 1
    assert instructions[0].technical is not None
    assert instructions[0].accessibility is None
    assert instructions[0].media is None
    selects = [
        row["sql"]
        for row in captured
        if 'FROM "programme_programmedeliveryrevision"' in row["sql"]
    ]
    assert selects
    for query in selects:
        for excluded in (
            "accessibility_delivery",
            "media_consent_notes",
            "actor_id",
            '"reason"',
        ):
            assert excluded not in query


def _ready_with_retained_work(scope, monkeypatch):
    from maru.events.models import EventEdition  # noqa: PLC0415
    from maru.identity.models import Account  # noqa: PLC0415

    actor = Account.objects.get(id=scope.request.actor_id)
    edition = EventEdition.objects.get(id=scope.request.edition_id)
    item = ProgrammeItem.objects.get(id=scope.selection.item_id)
    position = staffing_position(actor, edition)
    envelope = scope.world.placement.envelope
    terms = ProgrammeStaffingExpectation(
        position.id,
        "Stage handover",
        "Stage entrance",
        "Private handover briefing",
        "Supervisor on duty",
        envelope.setup_starts_at,
        envelope.teardown_ends_at,
        1,
        0,
        30,
    )
    result = change_programme_staffing_requirement(
        **scope.common,
        change=ProgrammeStaffingChange(
            item.id,
            scope.selection.occurrence_id,
            None,
            item.aggregate_version,
            0,
            scope.world.placement.occurrence_version,
            edition.aggregate_version,
            terms,
        ),
        authorizer=scope.policy,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
    )
    source = ProgrammeStaffingSource(
        result.requirement_id,
        result.revision_id,
        1,
        scope.selection.occurrence_id,
        scope.world.placement.occurrence_version,
        scope.selection.candidate_id,
        scope.selection.candidate_revision_id,
        scope.selection.placement_id,
    )
    selected = SimpleNamespace(
        terms=terms,
        source=source,
        request=ProgrammeStaffingReadRequest(
            actor.id, edition.organization_id, edition.id, item.id, uuid4(), "test"
        ),
    )
    work_scope = SimpleNamespace(
        selection=selected,
        actor=actor,
        edition=edition,
        policies={
            "programme_authorizer": scope.policy,
            "scheduling_authorizer": scope.world.policy,
        },
    )
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=actor,
        capability_code="workforce.manage_shifts",
    )
    person = person_for(work_scope, monkeypatch)
    first = create_binding(work_scope)
    opened = open_shift_demand(
        **shift_attribution(work_scope), demand_id=first.demand_id, expected_version=1
    )
    first_claim = shifts._claim(person, ShiftDemand.objects.get(id=first.demand_id))
    commitment = ShiftCommitment.objects.get(id=first_claim.commitment_id)
    shifts._confirm(person, commitment)
    original_interval = (
        commitment.starts_at,
        commitment.ends_at,
        commitment.rest_ends_at,
    )
    successor = apply_binding(
        work_scope,
        ProgrammeStaffingBindingChange(
            ProgrammeStaffingAction.SUCCESSOR,
            source,
            first.binding_id,
            1,
            first.demand_id,
            opened.resulting_version,
        ),
    )
    open_shift_demand(
        **shift_attribution(work_scope),
        demand_id=successor.demand_id,
        expected_version=1,
    )
    claim = shifts._claim(person, ShiftDemand.objects.get(id=successor.demand_id))
    shifts._confirm(person, ShiftCommitment.objects.get(id=claim.commitment_id))
    item.refresh_from_db()
    scope.selection = replace(
        scope.selection, expected_item_version=item.aggregate_version
    )
    assess_placement(scope)
    preflight = release_preflight(scope)
    assert preflight.eligibility.eligible_for_review, preflight.findings
    scope.release_selection = ReleaseCandidateSelection(
        scope.selection.candidate_id,
        scope.selection.candidate_revision_id,
        scope.selection.expected_candidate_version,
        preflight.snapshot_digest,
    )
    return SimpleNamespace(
        position=position,
        first=first,
        successor=successor,
        original_interval=original_interval,
    )


def test_department_without_room_gets_its_linked_work_and_retained_predecessor_only(
    operator_world, monkeypatch
):
    work = _ready_with_retained_work(operator_world, monkeypatch)
    published = publish(operator_world, approve(operator_world))
    monkeypatch.setattr(
        work_links,
        "profile_allows_adapter",
        lambda _code, _version, adapter: adapter == "workforce.programme-staffing@1",
    )
    actor = AccountFactory()
    for capability in (*BASE_CAPABILITIES, "workforce.view_operator_staffing"):
        CapabilityGrantFactory(
            organization_id=operator_world.request.organization_id,
            edition_id=operator_world.request.edition_id,
            department_id=work.position.department_id,
            principal=actor,
            capability_code=capability,
        )
    request = OperatorReadRequest(
        actor.id,
        operator_world.request.organization_id,
        operator_world.request.edition_id,
        uuid4(),
        OperatorScopeKind.DEPARTMENT,
        work.position.department_id,
    )
    assert not EditionSpaceSelection.objects.filter(
        responsible_department_id=work.position.department_id
    ).exists()
    with CaptureQueriesContext(connection) as captured:
        result = load_operator_run_sheet(request, layers=frozenset({"staffing"}))
    assert result.reference.release_id == published.object_id
    assert len(result.entries) == 1
    impact = load_operator_release_impact(request)
    assert impact.room_links == ()
    assert impact.staffing_adopted
    assert impact.changes[0].after == result.entries[0].placement
    assert {row.demand_id for row in impact.work_links} == {
        work.first.demand_id,
        work.successor.demand_id,
    }
    assert result.staffing.adopted
    assert {row.demand_id for row in result.staffing.demands} == {
        work.first.demand_id,
        work.successor.demand_id,
    }
    predecessor = next(
        row for row in result.staffing.demands if row.demand_id == work.first.demand_id
    )
    successor = next(
        row
        for row in result.staffing.demands
        if row.demand_id == work.successor.demand_id
    )
    assert predecessor.state == "cancelled"
    assert predecessor.retained_work[0].state == "removed"
    assert (
        predecessor.retained_work[0].starts_at,
        predecessor.retained_work[0].ends_at,
        predecessor.retained_work[0].rest_ends_at,
    ) == work.original_interval
    assert successor.retained_work[0].state == "confirmed"
    statements = [
        row["sql"]
        for row in captured
        if 'FROM "workforce_shiftcommitment"' in row["sql"]
    ]
    assert statements
    for statement in statements:
        for excluded in (
            "account_id",
            "position_assignment_id",
            "confirmation_reason",
            "availability_plan_id",
        ):
            assert excluded not in statement


def test_department_membership_requires_work_links_without_requested_details(
    operator_world, monkeypatch
):
    published = publish(operator_world, approve(operator_world))
    request = operator_request(operator_world, kind=OperatorScopeKind.DEPARTMENT)
    monkeypatch.setattr(work_links, "profile_allows_adapter", lambda *_args: True)
    with pytest.raises(SchedulingAuthorizationDeniedError):
        load_operator_run_sheet(request)
    CapabilityGrantFactory(
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        department_id=request.target_id,
        principal_id=request.actor_id,
        capability_code="workforce.view_operator_staffing",
    )
    result = load_operator_run_sheet(request)
    assert result.reference.release_id == published.object_id
    assert result.staffing is None


@pytest.mark.parametrize("output_format", ["html", "calendar"])
def test_actual_private_http_rechecks_the_published_release(
    operator_world, settings, client, output_format
):
    from maru.scheduling.output_urls import (  # noqa: PLC0415
        urlpatterns as output_patterns,
    )
    from maru.urls import urlpatterns as production_patterns  # noqa: PLC0415

    class IsolatedOperatorUrls:
        urlpatterns = (*output_patterns, *production_patterns)

    settings.ROOT_URLCONF = IsolatedOperatorUrls
    published = publish(operator_world, approve(operator_world))
    request = operator_request(operator_world)
    from maru.identity.models import Account  # noqa: PLC0415

    client.force_login(Account.objects.get(id=request.actor_id))
    url = (
        f"/admin/programme/run-sheets/{request.organization_id}/"
        f"{request.edition_id}/edition/{request.target_id}/?format={output_format}"
    )
    before = client.get(url)
    assert before.status_code == 200
    assert b"Synthetic public opening" in before.content.replace(b"\r\n ", b"")
    assert "no-store" in before["Cache-Control"]
    released_copy = load_operator_release_reference(request).occurrences[0]
    end_copy(operator_world, released_copy.public_rendition_id)
    invalidated = client.get(url)
    assert invalidated.status_code == (409 if output_format == "calendar" else 200)
    assert b"Synthetic public opening" not in invalidated.content
    withdraw(operator_world, published)
    after = client.get(url)
    assert after.status_code == (409 if output_format == "calendar" else 200)
    assert b"Synthetic public opening" not in after.content
