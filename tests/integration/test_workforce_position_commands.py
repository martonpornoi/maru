"""Governed Position and volunteer-opportunity command coverage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Never
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.authorization.models import ScopedResourceBinding
from maru.effects.models import DomainEvent, OutboxMessage
from maru.workforce.models import (
    Department,
    EditionStructureCommandReceipt,
    EditionStructureControl,
    Position,
    PositionAssignment,
    PositionTemplate,
    VolunteerOpportunity,
)
from maru.workforce.structure_commands import (
    StructureAuthorizationDeniedError,
    StructureDependencyConflictError,
    StructureStateConflictError,
    close_position,
    create_position,
    update_position,
    update_position_opportunity,
)
from tests.factories import AccountFactory, EventEditionFactory, RoleBundleFactory
from tests.support.authority import create_provenance_backed_role_bundle
from tests.workforce_helpers import (
    create_department_for_test,
    save_position_assignment_for_test,
    save_position_for_test,
)

if TYPE_CHECKING:
    from maru.events.models import EventEdition
    from maru.identity.models import Account

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


@dataclass(frozen=True, slots=True)
class _PositionWorld:
    actor: Account
    edition: EventEdition
    department: Department
    template: PositionTemplate


def _world() -> _PositionWorld:
    actor = AccountFactory(is_staff=True, is_superuser=True)
    edition = EventEditionFactory()
    department = create_department_for_test(
        edition=edition,
        actor=actor,
        name="Volunteer Operations",
        expected_code="volunteer-operations",
    )
    _controller, _approver, role_bundle = create_provenance_backed_role_bundle(
        edition.organization,
        code="volunteer-coordinator",
        name="Volunteer coordinator",
        capability_codes=("workforce.view_structure",),
    )
    template = PositionTemplate.objects.create(
        organization=edition.organization,
        code="volunteer-coordinator",
        name="Volunteer coordinator",
        description="Coordinate volunteer teams and their arrival.",
        default_headcount=2,
        default_capacity_codes=["volunteer"],
        role_bundle=role_bundle,
        status=PositionTemplate.Status.PUBLISHED,
        created_by=actor,
    )
    return _PositionWorld(
        actor=actor,
        edition=edition,
        department=department,
        template=template,
    )


def _create(
    world: _PositionWorld,
    *,
    expected_version: int = 1,
    retry_key: UUID | None = None,
    title: str = "Volunteer Coordinator",
    reports_to_id: UUID | None = None,
    headcount: int = 2,
):
    return create_position(
        actor=world.actor,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        template_id=world.template.id,
        department_id=world.department.id,
        reports_to_id=reports_to_id,
        title=title,
        description="  Coordinate volunteer teams and humane arrival support.  ",
        headcount=headcount,
        expected_version=expected_version,
        reason="  Establish this accountable volunteer responsibility.  ",
        retry_key=retry_key or uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )


def test_create_position_is_idempotent_and_pairs_governed_records() -> None:
    world = _world()
    retry_key = uuid4()

    result = _create(world, retry_key=retry_key)
    replay = _create(world, retry_key=retry_key)

    assert result.replayed is False
    assert replay.replayed is True
    assert replay.position_id == result.position_id
    assert replay.receipt_id == result.receipt_id
    assert result.resulting_version == 2
    position = Position.objects.select_related("opportunity").get(id=result.position_id)
    assert position.code == "volunteer-coordinator"
    assert position.title == "Volunteer Coordinator"
    assert position.description == (
        "Coordinate volunteer teams and humane arrival support."
    )
    assert position.status == Position.Status.PLANNED
    assert position.role_bundle_id == world.template.role_bundle_id
    assert position.capacity_codes == ["volunteer"]
    assert position.created_in_structure_version == 2
    assert position.last_changed_in_structure_version == 2
    assert position.opportunity.status == VolunteerOpportunity.Status.DRAFT
    assert position.opportunity.headline == position.title
    assert position.opportunity.created_in_structure_version == 2
    assert ScopedResourceBinding.objects.filter(
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        department_id=world.department.id,
        resource_kind=ScopedResourceBinding.ResourceKind.WORKFORCE_POSITION,
        resource_id=position.id,
    ).exists()
    receipt = EditionStructureCommandReceipt.objects.get(id=result.receipt_id)
    assert receipt.action == EditionStructureCommandReceipt.Action.POSITION_CREATED
    assert receipt.affected_position_id == position.id
    assert receipt.reason == "Establish this accountable volunteer responsibility."
    assert Position.objects.filter(edition=world.edition).count() == 1
    assert VolunteerOpportunity.objects.filter(position=position).count() == 1
    assert (
        EditionStructureCommandReceipt.objects.filter(
            edition=world.edition,
            action=EditionStructureCommandReceipt.Action.POSITION_CREATED,
        ).count()
        == 1
    )


def test_position_details_and_opportunity_share_versioned_evidence() -> None:
    world = _world()
    created = _create(world)

    updated = update_position(
        actor=world.actor,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        position_id=created.position_id,
        reports_to_id=None,
        title="  Volunteer Experience Lead ",
        description="Make volunteer arrival understandable and welcoming.",
        headcount=3,
        expected_version=2,
        reason="Clarify the responsibility before publishing recruitment.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    published = update_position_opportunity(
        actor=world.actor,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        position_id=created.position_id,
        status=VolunteerOpportunity.Status.PUBLISHED,
        headline="Help volunteers begin with confidence",
        description="Welcome volunteers, answer questions, and coordinate handoffs.",
        applications_open_at=None,
        applications_close_at=None,
        visible_when_filled=True,
        expected_version=3,
        reason="Open the reviewed opportunity for applications.",
        correlation_id=uuid4(),
        source_channel="test",
    )

    position = Position.objects.get(id=created.position_id)
    opportunity = VolunteerOpportunity.objects.get(position=position)
    assert updated.resulting_version == 3
    assert updated.changed_fields == ("description", "headcount", "title")
    assert published.resulting_version == 4
    assert "opportunity.status" in published.changed_fields
    assert "status" in published.changed_fields
    assert position.status == Position.Status.OPEN
    assert position.title == "Volunteer Experience Lead"
    assert position.headcount == 3
    assert position.last_changed_in_structure_version == 4
    assert opportunity.status == VolunteerOpportunity.Status.PUBLISHED
    assert opportunity.headline == "Help volunteers begin with confidence"
    assert opportunity.last_changed_in_structure_version == 4
    history = list(
        EditionStructureCommandReceipt.objects.filter(affected_position=position)
        .order_by("resulting_version")
        .values_list("action", "reason", "resulting_version")
    )
    assert history == [
        (
            EditionStructureCommandReceipt.Action.POSITION_CREATED,
            "Establish this accountable volunteer responsibility.",
            2,
        ),
        (
            EditionStructureCommandReceipt.Action.POSITION_UPDATED,
            "Clarify the responsibility before publishing recruitment.",
            3,
        ),
        (
            EditionStructureCommandReceipt.Action.OPPORTUNITY_UPDATED,
            "Open the reviewed opportunity for applications.",
            4,
        ),
    ]


def test_first_governed_change_adopts_legacy_rows_without_inventing_creation() -> None:
    world = _world()
    position = save_position_for_test(
        position=Position(
            organization=world.edition.organization,
            edition=world.edition,
            template=world.template,
            department=world.department,
            role_bundle=world.template.role_bundle,
            code="legacy-volunteer-coordinator",
            title="Legacy Volunteer Coordinator",
            description="A historically created Position.",
            headcount=2,
            capacity_codes=["volunteer"],
            created_by=world.actor,
        )
    )
    opportunity = VolunteerOpportunity.objects.get(position=position)

    updated = update_position(
        actor=world.actor,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        position_id=position.id,
        reports_to_id=None,
        title="Volunteer Coordinator",
        description="Coordinate a humane volunteer arrival.",
        headcount=2,
        expected_version=1,
        reason="Begin governed history at the first real operational change.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    published = update_position_opportunity(
        actor=world.actor,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        position_id=position.id,
        status=VolunteerOpportunity.Status.PUBLISHED,
        headline="Help welcome volunteers",
        description="Join the volunteer arrival team.",
        applications_open_at=None,
        applications_close_at=None,
        visible_when_filled=True,
        expected_version=updated.resulting_version,
        reason="Publish the first governed applicant-facing opportunity.",
        correlation_id=uuid4(),
        source_channel="test",
    )

    position.refresh_from_db()
    opportunity.refresh_from_db()
    assert position.created_in_structure_version is None
    assert position.last_changed_in_structure_version == published.resulting_version
    assert opportunity.created_in_structure_version is None
    assert opportunity.last_changed_in_structure_version == published.resulting_version
    assert position.status == Position.Status.OPEN
    assert opportunity.status == VolunteerOpportunity.Status.PUBLISHED
    assert (
        EditionStructureCommandReceipt.objects.filter(
            affected_position=position,
            action__in=(
                EditionStructureCommandReceipt.Action.POSITION_UPDATED,
                EditionStructureCommandReceipt.Action.OPPORTUNITY_UPDATED,
            ),
        ).count()
        == 2
    )


def test_closed_opportunity_can_reopen_or_be_finally_withdrawn() -> None:
    world = _world()
    created = _create(world)
    expected_version = created.resulting_version

    for next_status in (
        VolunteerOpportunity.Status.PUBLISHED,
        VolunteerOpportunity.Status.CLOSED,
        VolunteerOpportunity.Status.PUBLISHED,
        VolunteerOpportunity.Status.CLOSED,
        VolunteerOpportunity.Status.WITHDRAWN,
    ):
        result = update_position_opportunity(
            actor=world.actor,
            organization_id=world.edition.organization_id,
            series_id=world.edition.series_id,
            edition_id=world.edition.id,
            position_id=created.position_id,
            status=next_status,
            headline="Help volunteers begin with confidence",
            description="Welcome volunteers and coordinate their handoffs.",
            applications_open_at=None,
            applications_close_at=None,
            visible_when_filled=True,
            expected_version=expected_version,
            reason=f"Move the opportunity to {next_status} after review.",
            correlation_id=uuid4(),
            source_channel="test",
        )
        expected_version = result.resulting_version

    opportunity = VolunteerOpportunity.objects.get(position_id=created.position_id)
    assert opportunity.status == VolunteerOpportunity.Status.WITHDRAWN
    with pytest.raises(ValidationError) as reopened:
        update_position_opportunity(
            actor=world.actor,
            organization_id=world.edition.organization_id,
            series_id=world.edition.series_id,
            edition_id=world.edition.id,
            position_id=created.position_id,
            status=VolunteerOpportunity.Status.PUBLISHED,
            headline=opportunity.headline,
            description=opportunity.description,
            applications_open_at=None,
            applications_close_at=None,
            visible_when_filled=True,
            expected_version=expected_version,
            reason="Attempt to reopen a final withdrawal.",
            correlation_id=uuid4(),
            source_channel="test",
        )
    assert reopened.value.error_dict["status"][0].code == (
        "structure_opportunity_transition_invalid"
    )


def test_reporting_cycles_assignments_and_direct_reports_protect_positions() -> None:
    world = _world()
    manager_result = _create(world, title="Volunteer Lead")
    report_result = _create(
        world,
        expected_version=2,
        title="Volunteer Welcome Coordinator",
        reports_to_id=manager_result.position_id,
        headcount=1,
    )

    with pytest.raises(ValidationError) as cycle:
        update_position(
            actor=world.actor,
            organization_id=world.edition.organization_id,
            series_id=world.edition.series_id,
            edition_id=world.edition.id,
            position_id=manager_result.position_id,
            reports_to_id=report_result.position_id,
            title="Volunteer Lead",
            description="Coordinate volunteer teams and humane arrival support.",
            headcount=2,
            expected_version=3,
            reason="Attempt a cyclic reporting line.",
            correlation_id=uuid4(),
            source_channel="test",
        )
    assert cycle.value.error_dict["reports_to_id"][0].code == (
        "structure_position_reporting_cycle"
    )
    with pytest.raises(StructureDependencyConflictError):
        close_position(
            actor=world.actor,
            organization_id=world.edition.organization_id,
            series_id=world.edition.series_id,
            edition_id=world.edition.id,
            position_id=manager_result.position_id,
            expected_version=3,
            confirmation_name="Volunteer Lead",
            reason="A current direct report must prevent closure.",
            correlation_id=uuid4(),
            source_channel="test",
        )

    report = Position.objects.get(id=report_result.position_id)
    closed_report = close_position(
        actor=world.actor,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        position_id=report.id,
        expected_version=3,
        confirmation_name=report.title,
        reason="Close the dependency-free report while retaining history.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    closed_manager = close_position(
        actor=world.actor,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        position_id=manager_result.position_id,
        expected_version=closed_report.resulting_version,
        confirmation_name="Volunteer Lead",
        reason="Close the now dependency-free manager Position.",
        correlation_id=uuid4(),
        source_channel="test",
    )

    protected_result = _create(
        world,
        expected_version=closed_manager.resulting_version,
        title="Volunteer Assignment Target",
        headcount=1,
    )
    protected_position = Position.objects.get(id=protected_result.position_id)
    save_position_assignment_for_test(
        assignment=PositionAssignment(
            position=protected_position,
            organization=world.edition.organization,
            edition=world.edition,
            account=AccountFactory(),
            status=PositionAssignment.Status.PROPOSED,
            effective_from=timezone.now(),
            proposed_by=world.actor,
            reason="Propose a synthetic volunteer assignment.",
        )
    )
    with pytest.raises(StructureDependencyConflictError):
        close_position(
            actor=world.actor,
            organization_id=world.edition.organization_id,
            series_id=world.edition.series_id,
            edition_id=world.edition.id,
            position_id=protected_position.id,
            expected_version=protected_result.resulting_version,
            confirmation_name=protected_position.title,
            reason="A proposal must protect the Position.",
            correlation_id=uuid4(),
            source_channel="test",
        )
    assert closed_manager.resulting_version == 5
    assert (
        Position.objects.filter(
            id__in=(manager_result.position_id, report_result.position_id),
            status=Position.Status.CLOSED,
            closed_at__isnull=False,
            closed_by=world.actor,
        ).count()
        == 2
    )
    assert (
        VolunteerOpportunity.objects.filter(
            position_id__in=(manager_result.position_id, report_result.position_id),
            status=VolunteerOpportunity.Status.CLOSED,
        ).count()
        == 2
    )


def test_unauthorized_position_request_does_not_reveal_template_availability() -> None:
    world = _world()
    outsider = AccountFactory(is_staff=False, is_superuser=False)

    with pytest.raises(StructureAuthorizationDeniedError):
        create_position(
            actor=outsider,
            organization_id=world.edition.organization_id,
            series_id=world.edition.series_id,
            edition_id=world.edition.id,
            template_id=uuid4(),
            department_id=world.department.id,
            reports_to_id=None,
            title="Hidden template probe",
            description="This request must be denied before catalog lookup.",
            headcount=1,
            expected_version=1,
            reason="Verify the name-free authorization boundary.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )


def test_initial_authority_bootstrap_exception_is_bound_to_exact_chair_state() -> None:
    actor = AccountFactory(is_staff=True, is_superuser=True)
    approver = AccountFactory()
    edition = EventEditionFactory()
    department = create_department_for_test(
        edition=edition,
        actor=actor,
        name="Convention Leadership",
        expected_code="convention-leadership",
    )
    role_bundle = RoleBundleFactory(
        organization=edition.organization,
        code="operations-lead",
        created_by=actor,
        approved_by=approver,
    )
    template = PositionTemplate.objects.create(
        organization=edition.organization,
        code="operations-lead",
        name="Operations Lead",
        description="An ordinary template must retain provenance.",
        default_capacity_codes=["staff"],
        role_bundle=role_bundle,
        status=PositionTemplate.Status.PUBLISHED,
        created_by=actor,
    )

    with pytest.raises(ValidationError, match="available published Position"):
        create_position(
            actor=actor,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            template_id=template.id,
            department_id=department.id,
            reports_to_id=None,
            title="Operations Lead",
            description=template.description,
            headcount=1,
            expected_version=1,
            reason="Prove the bootstrap exception cannot authorize ordinary roles.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            initial_authority_bootstrap=True,
        )

    assert not Position.objects.filter(edition=edition).exists()


def test_position_outbox_failure_rolls_back_every_paired_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _world()
    baseline = {
        "control": EditionStructureControl.objects.get(
            edition=world.edition
        ).aggregate_version,
        "receipts": EditionStructureCommandReceipt.objects.filter(
            edition=world.edition
        ).count(),
        "audits": AuditEvent.objects.count(),
        "events": DomainEvent.objects.count(),
        "outbox": OutboxMessage.objects.count(),
    }

    def fail_publish(*_args: object, **_kwargs: object) -> Never:
        raise RuntimeError("synthetic Position outbox failure")

    monkeypatch.setattr(
        "maru.workforce.structure_commands.publish_domain_event",
        fail_publish,
    )
    with pytest.raises(RuntimeError, match="synthetic Position outbox failure"):
        _create(world)

    assert not Position.objects.filter(edition=world.edition).exists()
    assert not VolunteerOpportunity.objects.filter(
        position__edition=world.edition
    ).exists()
    assert not ScopedResourceBinding.objects.filter(
        edition=world.edition,
        resource_kind=ScopedResourceBinding.ResourceKind.WORKFORCE_POSITION,
    ).exists()
    assert (
        EditionStructureControl.objects.get(edition=world.edition).aggregate_version
        == baseline["control"]
    )
    assert (
        EditionStructureCommandReceipt.objects.filter(edition=world.edition).count()
        == baseline["receipts"]
    )
    assert AuditEvent.objects.count() == baseline["audits"]
    assert DomainEvent.objects.count() == baseline["events"]
    assert OutboxMessage.objects.count() == baseline["outbox"]


def test_closed_position_is_immutable() -> None:
    world = _world()
    created = _create(world)
    closed = close_position(
        actor=world.actor,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        position_id=created.position_id,
        expected_version=2,
        confirmation_name="Volunteer Coordinator",
        reason="Close a role that is no longer part of the operating plan.",
        correlation_id=uuid4(),
        source_channel="test",
    )

    with pytest.raises(StructureStateConflictError):
        update_position(
            actor=world.actor,
            organization_id=world.edition.organization_id,
            series_id=world.edition.series_id,
            edition_id=world.edition.id,
            position_id=created.position_id,
            reports_to_id=None,
            title="Reopened by edit",
            description="Closed Positions cannot be edited back into service.",
            headcount=1,
            expected_version=closed.resulting_version,
            reason="Verify one-way closure.",
            correlation_id=uuid4(),
            source_channel="test",
        )


def test_database_rejects_position_and_opportunity_writes_without_receipts() -> None:
    world = _world()
    created = _create(world)

    with pytest.raises(IntegrityError), transaction.atomic():
        Position.objects.filter(id=created.position_id).update(
            title="Unreceipted Position change",
            last_changed_in_structure_version=3,
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        VolunteerOpportunity.objects.filter(position_id=created.position_id).update(
            headline="Unreceipted opportunity change",
            last_changed_in_structure_version=3,
        )

    position = Position.objects.get(id=created.position_id)
    opportunity = VolunteerOpportunity.objects.get(position=position)
    assert position.title == "Volunteer Coordinator"
    assert opportunity.headline == "Volunteer Coordinator"
    assert (
        EditionStructureControl.objects.get(edition=world.edition).aggregate_version
        == 2
    )
