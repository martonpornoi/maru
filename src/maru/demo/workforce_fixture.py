"""Prepare isolated Workforce practice through existing, auditable owner commands."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from maru.authorization.commands import grant_capability_direct
from maru.authorization.database_role_safety import probe_runtime_database_role_safety
from maru.authorization.policy import resolve_edition_target
from maru.demo.convention_fixture import (
    ConventionDemoConflictError,
    _actors,
    _lock_empty_foundation,
    require_demo_environment,
)
from maru.demo.convention_plan import DEMO_ZONE, PREPARATION_REASON, DemoEdition
from maru.demo.workforce_plan import ROLES, edition_plan, shift_period
from maru.events.services import transition_edition
from maru.events.workforce_adoption import (
    WorkforceAdoptionSetupInput,
    WorkforceAdoptionSetupResult,
    set_up_workforce_adoption,
)
from maru.organizations.representation import (
    activate_representation,
    invite_representation_controller,
    respond_to_representation_invitation,
)
from maru.workforce.assignment_commands import (
    approve_position_assignment,
    propose_position_assignment,
)
from maru.workforce.availability_commands import save_person_availability
from maru.workforce.availability_inputs import AvailabilityWindowInput
from maru.workforce.models import EditionStructureControl, Position, ShiftDemand
from maru.workforce.services import submit_volunteer_application
from maru.workforce.shift_commands import (
    claim_shift,
    confirm_shift_commitment,
    create_shift_demand,
    lock_shift_demand,
    open_shift_demand,
)
from maru.workforce.starter_templates import provision_workforce_starter_template
from maru.workforce.structure_commands import (
    create_department,
    create_position,
    update_position_opportunity,
)

if TYPE_CHECKING:
    from datetime import date, datetime

    from maru.events.models import EventEdition
    from maru.identity.models import Account

CHANNEL = "synthetic-workforce-demo"
_WORK_CAPABILITIES = (
    "events.view_basic",
    "workforce.view_structure",
    "workforce.manage_assignments",
    "authorization.manage_roles",
    "authorization.revoke",
    "workforce.view_availability",
    "workforce.view_shifts",
    "workforce.manage_shifts",
)


def _foundation(
    actors: dict[str, Account], plans: tuple[DemoEdition, DemoEdition]
) -> tuple[WorkforceAdoptionSetupResult, ...]:
    results: list[WorkforceAdoptionSetupResult] = []
    for plan in plans:
        previous = results[0].edition if results else None
        results.append(
            set_up_workforce_adoption(
                actor=actors["platform"],
                details=WorkforceAdoptionSetupInput(
                    mode="existing_series" if previous else "new_foundation",
                    organization_id=previous.organization_id if previous else None,
                    series_id=previous.series_id if previous else None,
                    organization_name="MaruCon practice team",
                    series_name="MaruCon team",
                    edition_name=plan.name,
                    starts_on=plan.starts_on,
                    ends_on=plan.ends_on,
                    time_zone=DEMO_ZONE,
                ),
                idempotency_key=uuid4(),
                correlation_id=uuid4(),
                source_channel=CHANNEL,
            )
        )
    representation = results[0].representation
    for key in ("operator-a", "operator-b"):
        invitation = invite_representation_controller(
            actor=actors["platform"],
            representation_id=representation.id,
            account_id=actors[key].id,
            reason=PREPARATION_REASON,
            correlation_id=uuid4(),
            source_channel=CHANNEL,
        )
        respond_to_representation_invitation(
            actor=actors[key],
            appointment_id=invitation.id,
            expected_version=invitation.invitation_version,
            accept=True,
            correlation_id=uuid4(),
            source_channel=CHANNEL,
        )
    representation.refresh_from_db()
    activate_representation(
        actor=actors["platform"],
        representation_id=representation.id,
        expected_version=representation.aggregate_version,
        reason=PREPARATION_REASON,
        correlation_id=uuid4(),
        source_channel=CHANNEL,
    )
    return tuple(results)


def _grant_roles(actors: dict[str, Account], edition: EventEdition, key: str) -> None:
    target = resolve_edition_target(
        organization_id=edition.organization_id, edition_id=edition.id
    )
    if target is None:
        raise ConventionDemoConflictError(
            "The Workforce practice edition is unavailable."
        )
    for role in ROLES:
        codes = ("events.view_basic",) if role == "volunteer" else _WORK_CAPABILITIES
        if role == "manager":
            codes = (*codes, "workforce.manage_structure")
        for code in codes:
            grant_capability_direct(
                actor=actors["operator-a"],
                approver=actors["operator-b"],
                recipient=actors[f"{key}-{role}"],
                capability_code=code,
                target=target,
                effective_from=timezone.now(),
                expires_at=None,
                reason=PREPARATION_REASON,
                correlation_id=uuid4(),
                source_channel=CHANNEL,
            )


def _structure_version(edition: EventEdition) -> int:
    return (
        EditionStructureControl.objects.filter(edition=edition)
        .values_list("aggregate_version", flat=True)
        .first()
        or 0
    )


def _structure(actors: dict[str, Account], edition: EventEdition, key: str) -> Position:
    scope = {
        "organization_id": edition.organization_id,
        "series_id": edition.series_id,
        "edition_id": edition.id,
    }
    starter = provision_workforce_starter_template(
        actor=actors["operator-a"],
        **scope,
        approver_email=actors["operator-b"].email,
        reason=PREPARATION_REASON,
        correlation_id=uuid4(),
        source_channel=CHANNEL,
    )
    manager = actors[f"{key}-manager"]
    department = create_department(
        actor=manager,
        **scope,
        name="Volunteer welcome",
        description="Fictional team practice.",
        parent_department_id=None,
        display_order=0,
        expected_version=_structure_version(edition),
        reason=PREPARATION_REASON,
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel=CHANNEL,
    )
    result = create_position(
        actor=manager,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        template_id=starter.template.id,
        department_id=department.department_id,
        reports_to_id=None,
        title="Welcome helper",
        description="Help fictional volunteers find their work.",
        headcount=2,
        expected_version=_structure_version(edition),
        reason=PREPARATION_REASON,
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel=CHANNEL,
    )
    position = Position.objects.get(pk=result.position_id)
    update_position_opportunity(
        actor=manager,
        **scope,
        position_id=position.id,
        status="published",
        headline="Help the MaruCon team",
        description="Try a fictional welcome-helper responsibility.",
        applications_open_at=timezone.now() - timedelta(seconds=1),
        applications_close_at=None,
        visible_when_filled=True,
        expected_version=_structure_version(edition),
        reason=PREPARATION_REASON,
        correlation_id=uuid4(),
        source_channel=CHANNEL,
    )
    return position


def _assignment(
    actors: dict[str, Account], edition: EventEdition, position: Position, key: str
) -> str:
    person, manager, reviewer = (
        actors[f"{key}-{role}"] for role in ("volunteer", "manager", "reviewer")
    )
    submit_volunteer_application(
        actor=person,
        opportunity_id=position.opportunity.id,
        motivation="I am trying the fictional welcome-helper workflow.",
        correlation_id=uuid4(),
    )
    scope = {
        "organization_id": edition.organization_id,
        "series_id": edition.series_id,
        "edition_id": edition.id,
    }
    proposal = propose_position_assignment(
        actor=manager,
        **scope,
        position_id=position.id,
        account_id=person.id,
        effective_from=timezone.now(),
        expires_at=None,
        reason=PREPARATION_REASON,
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel=CHANNEL,
    )
    if key == "ongoing":
        approve_position_assignment(
            actor=reviewer,
            **scope,
            assignment_id=proposal.assignment_id,
            expected_version=1,
            reason=PREPARATION_REASON,
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel=CHANNEL,
        )
    return str(proposal.assignment_id)


def _create_demand(
    manager: Account,
    edition: EventEdition,
    position: Position,
    interval: tuple[datetime, datetime],
    title: str,
) -> ShiftDemand:
    result = create_shift_demand(
        actor=manager,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        position_id=position.id,
        title=title,
        location_label="Fictional welcome desk",
        briefing="Use only the fictional practice instructions.",
        supervision_note="Ask the practice organizer if anything is unclear.",
        starts_at=interval[0],
        ends_at=interval[1],
        required_headcount=1,
        break_minutes=0,
        minimum_rest_minutes=0,
        reason=PREPARATION_REASON,
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel=CHANNEL,
    )
    return ShiftDemand.objects.get(pk=result.demand_id)


def _open_and_claim(
    actors: dict[str, Account],
    edition: EventEdition,
    demand: ShiftDemand,
    *,
    locked: bool,
) -> None:
    scope = {
        "organization_id": edition.organization_id,
        "series_id": edition.series_id,
        "edition_id": edition.id,
    }
    manager = actors["ongoing-manager"]
    open_shift_demand(
        actor=manager,
        **scope,
        demand_id=demand.id,
        expected_version=demand.command_version,
        reason=PREPARATION_REASON,
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel=CHANNEL,
    )
    demand.refresh_from_db()
    claim = claim_shift(
        actor=actors["ongoing-volunteer"],
        organization_id=edition.organization_id,
        edition_id=edition.id,
        demand_id=demand.id,
        expected_version=demand.command_version,
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel=CHANNEL,
    )
    if locked:
        confirm_shift_commitment(
            actor=actors["ongoing-reviewer"],
            **scope,
            commitment_id=claim.commitment_id,
            expected_version=1,
            reason=PREPARATION_REASON,
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel=CHANNEL,
        )
        demand.refresh_from_db()
        lock_shift_demand(
            actor=manager,
            **scope,
            demand_id=demand.id,
            expected_version=demand.command_version,
            allow_understaffed=False,
            reason=PREPARATION_REASON,
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel=CHANNEL,
        )


def _content(
    actors: dict[str, Account], edition: EventEdition, plan: DemoEdition
) -> dict[str, str]:
    _grant_roles(actors, edition, plan.key)
    position = _structure(actors, edition, plan.key)
    assignment = _assignment(actors, edition, position, plan.key)
    start, end = shift_period(plan, timezone.now())
    save_person_availability(
        actor=actors[f"{plan.key}-volunteer"],
        organization_id=edition.organization_id,
        edition_id=edition.id,
        expected_version=0,
        status="submitted" if plan.key == "ongoing" else "draft",
        windows=(
            AvailabilityWindowInput(
                starts_at=start - timedelta(hours=1),
                ends_at=end + timedelta(hours=3),
                preference="available",
            ),
        ),
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel=CHANNEL,
    )
    manager = actors[f"{plan.key}-manager"]
    demand = _create_demand(
        manager,
        edition,
        position,
        (start, end),
        "Short closeout practice" if plan.key == "ongoing" else "Future welcome desk",
    )
    references = {"assignment": assignment, "shift": str(demand.id)}
    if plan.key == "ongoing":
        _open_and_claim(actors, edition, demand, locked=True)
        pending = _create_demand(
            manager,
            edition,
            position,
            (end + timedelta(minutes=25), end + timedelta(minutes=55)),
            "Welcome desk - claim awaiting review",
        )
        _open_and_claim(actors, edition, pending, locked=False)
        references["pending_shift"] = str(pending.id)
    return references


def seed_workforce_demo(anchor: date) -> dict[str, Any]:
    """Prepare a separate two-edition Workforce-only scenario atomically.

    Parameters
    ----------
    anchor : date
        Creation date captured once in Europe/Budapest.

    Returns
    -------
    dict[str, Any]
        Non-secret fixed timelines and command-backed record references.

    Raises
    ------
    ConventionDemoConflictError
        If the local guard, exact provenance, runtime role or empty foundation differs.
    """
    require_demo_environment()
    if (
        settings.REQUIRE_EXACT_AUTHORITY_PROVENANCE is not True
        or not probe_runtime_database_role_safety(
            role_name=settings.RUNTIME_DATABASE_ROLE
        ).current_session_is_safe
    ):
        raise ConventionDemoConflictError(
            "Use the proved runtime login and exact provenance."
        )
    plans = edition_plan(anchor)
    with transaction.atomic():
        _lock_empty_foundation()
        actors = _actors(scenario="workforce")
        scopes = _foundation(actors, plans)
        result: dict[str, Any] = {
            "schema_version": 1,
            "scenario": "workforce",
            "synthetic_only": True,
            "anchor": anchor.isoformat(),
            "time_zone": DEMO_ZONE,
            "editions": [],
        }
        for plan, scope in zip(plans, scopes, strict=True):
            edition = scope.edition
            references = _content(actors, edition, plan)
            for state in (
                ("preparing", "ready", "live")
                if plan.key == "ongoing"
                else ("preparing",)
            ):
                transition_edition(
                    actor=actors["operator-a"],
                    organization_id=edition.organization_id,
                    edition_id=edition.id,
                    to_state=state,
                    reason=PREPARATION_REASON,
                    correlation_id=uuid4(),
                    source_channel=CHANNEL,
                )
            result["editions"].append(
                {
                    "key": plan.key,
                    "name": plan.name,
                    "starts_on": plan.starts_on.isoformat(),
                    "ends_on": plan.ends_on.isoformat(),
                    "organization_id": str(edition.organization_id),
                    "edition_id": str(edition.id),
                    "organization_slug": edition.organization.slug,
                    "series_slug": edition.series.slug,
                    "edition_slug": edition.slug,
                    "items": references,
                }
            )
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    return result
