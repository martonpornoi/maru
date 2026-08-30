"""Owner-safe Position-assignment command and database evidence coverage."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.authorization.commands import (
    grant_capability_direct,
    revoke_capability_grant,
)
from maru.authorization.models import CapabilityGrant, RoleAssignment
from maru.authorization.policy import resolve_edition_target
from maru.effects.models import DomainEvent, OutboxMessage
from maru.events.adoption import AdoptionProfileCode
from maru.identity.models import AccountSession
from maru.identity.services import session_key_digest
from maru.participation.models import Participation, ParticipationCapacity
from maru.workforce.assignment_commands import (
    AssignmentAuthorityIntervalConflictError,
    AssignmentAuthorizationDeniedError,
    AssignmentCandidateUnavailableError,
    AssignmentHeadcountConflictError,
    AssignmentReadinessConflictError,
    AssignmentRetryConflictError,
    AssignmentStateConflictError,
    approve_position_assignment,
    end_position_assignment,
    propose_position_assignment,
    reject_position_assignment,
)
from maru.workforce.assignment_queries import my_assignment_items
from maru.workforce.models import (
    OnboardingDocumentType,
    Position,
    PositionAssignment,
    PositionAssignmentCommandReceipt,
    PositionDocumentRequirement,
    PositionTemplate,
)
from tests.factories import (
    AccountFactory,
    EventEditionFactory,
    OrganizationMembershipFactory,
    ParticipationFactory,
)
from tests.support.authority import (
    activate_synthetic_board,
    create_provenance_backed_role_bundle,
    grant_board_controllers_edition_capability,
)
from tests.workforce_helpers import create_department_for_test, save_position_for_test

if TYPE_CHECKING:
    from maru.events.models import EventEdition
    from maru.identity.models import Account

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]


@dataclass(frozen=True, slots=True)
class _AssignmentWorld:
    """Synthetic exact-edition assignment command scope."""

    edition: EventEdition
    proposer: Account
    approver: Account
    position: Position


def _assignment_world(
    *,
    headcount: int = 1,
    adoption_profile_code: str = AdoptionProfileCode.FULL_CONVENTION,
) -> _AssignmentWorld:
    edition = EventEditionFactory(adoption_profile_code=adoption_profile_code)
    proposer: Account | None = None
    approver: Account | None = None
    for capability_code in (
        "workforce.view_structure",
        "workforce.manage_assignments",
        "authorization.manage_roles",
        "authorization.revoke",
    ):
        proposer, approver = grant_board_controllers_edition_capability(
            edition,
            capability_code,
        )
    assert proposer is not None
    assert approver is not None
    _role_actor, _role_approver, role_bundle = create_provenance_backed_role_bundle(
        edition.organization,
        code="assignment-member",
        name="Assignment member",
        capability_codes=("workforce.view_structure",),
    )
    department = create_department_for_test(
        edition=edition,
        name="Guest services",
        expected_code="guest-services",
    )
    template = PositionTemplate.objects.create(
        organization=edition.organization,
        code="assignment-member",
        name="Assignment member",
        description="Synthetic assignment role.",
        default_headcount=headcount,
        default_capacity_codes=["volunteer"],
        role_bundle=role_bundle,
        status=PositionTemplate.Status.PUBLISHED,
        created_by=proposer,
    )
    position = save_position_for_test(
        position=Position(
            organization=edition.organization,
            edition=edition,
            template=template,
            department=department,
            role_bundle=role_bundle,
            code="guest-services-member",
            title="Guest Services Member",
            description="Help guests find the right place.",
            headcount=headcount,
            capacity_codes=["volunteer"],
            status=Position.Status.OPEN,
            created_by=proposer,
        )
    )
    return _AssignmentWorld(
        edition=edition,
        proposer=proposer,
        approver=approver,
        position=position,
    )


def _known_candidate(world: _AssignmentWorld) -> Account:
    candidate = AccountFactory()
    ParticipationFactory(
        account=candidate,
        organization=world.edition.organization,
        edition=world.edition,
    )
    return candidate


def _delegated_assignment_world(
    *,
    proposer_role_expires_at: datetime | None = None,
) -> _AssignmentWorld:
    """Return a world whose controllers have only exact-edition authority."""

    base = _assignment_world()
    board_actor, board_approver = activate_synthetic_board(base.edition.organization)
    target = resolve_edition_target(
        organization_id=base.edition.organization_id,
        edition_id=base.edition.id,
    )
    assert target is not None
    proposer = AccountFactory()
    approver = AccountFactory()
    for principal in (proposer, approver):
        for capability_code in (
            "workforce.view_structure",
            "workforce.manage_assignments",
            "authorization.manage_roles",
            "authorization.revoke",
        ):
            grant_capability_direct(
                actor=board_actor,
                approver=board_approver,
                recipient=principal,
                capability_code=capability_code,
                target=target,
                effective_from=timezone.now(),
                expires_at=(
                    proposer_role_expires_at
                    if principal == proposer
                    and capability_code == "authorization.manage_roles"
                    else None
                ),
                reason="Establish isolated assignment-controller authority.",
                correlation_id=uuid4(),
                source_channel="test",
            )
    return _AssignmentWorld(
        edition=base.edition,
        proposer=proposer,
        approver=approver,
        position=base.position,
    )


def _active_role_control_grant(
    world: _AssignmentWorld,
    *,
    principal: Account,
) -> CapabilityGrant:
    return CapabilityGrant.objects.get(
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        department__isnull=True,
        resource_binding__isnull=True,
        principal=principal,
        capability_code="authorization.manage_roles",
        revoked_at__isnull=True,
    )


def _replace_role_control_grant(
    world: _AssignmentWorld,
    *,
    principal: Account,
    effective_from: datetime,
    expires_at: datetime | None,
) -> CapabilityGrant:
    """Replace one exact source through the real revoke and grant commands."""

    target = resolve_edition_target(
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
    )
    assert target is not None
    source = _active_role_control_grant(world, principal=principal)
    board_actor, board_approver = activate_synthetic_board(world.edition.organization)
    revoke_capability_grant(
        actor=board_actor,
        target=target,
        grant_id=source.id,
        reason="Replace the controller's exact authority interval.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    return grant_capability_direct(
        actor=board_actor,
        approver=board_approver,
        recipient=principal,
        capability_code="authorization.manage_roles",
        target=target,
        effective_from=effective_from,
        expires_at=expires_at,
        reason="Issue replacement exact assignment-controller authority.",
        correlation_id=uuid4(),
        source_channel="test",
    )


def _propose(
    world: _AssignmentWorld,
    *,
    candidate: Account,
    retry_key=None,
    reason: str = "The applicant matches this responsibility.",
    effective_from=None,
    expires_at=None,
):
    return propose_position_assignment(
        actor=world.proposer,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        position_id=world.position.id,
        account_id=candidate.id,
        effective_from=effective_from or timezone.now(),
        expires_at=expires_at,
        reason=reason,
        retry_key=retry_key or uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )


def _browser_url(
    name: str,
    world: _AssignmentWorld,
    *,
    position_id=None,
    assignment_id=None,
) -> str:
    kwargs = {
        "organization_slug": world.edition.organization.slug,
        "series_slug": world.edition.series.slug,
        "edition_slug": world.edition.slug,
    }
    if position_id is not None:
        kwargs["position_id"] = position_id
    if assignment_id is not None:
        kwargs["assignment_id"] = assignment_id
    return reverse(name, kwargs=kwargs)


def _mark_current_session_step_up(client: Client, *, actor: Account) -> None:
    session_key = client.session.session_key
    assert session_key is not None
    account_session = AccountSession.objects.get(
        account=actor,
        session_key_digest=session_key_digest(session_key),
    )
    account_session.step_up_verified_at = timezone.now()
    account_session.save(update_fields=("step_up_verified_at", "updated_at"))


def _assert_private_no_store(response) -> None:
    directives = {
        item.strip().casefold() for item in response["Cache-Control"].split(",")
    }
    assert {"private", "no-store"}.issubset(directives)


@pytest.mark.parametrize(
    ("field_name", "reason_code"),
    [
        ("effective_from", "authority_effective_from_too_early"),
        ("expires_at", "authority_expiry_too_early"),
    ],
)
def test_proposal_rejects_interval_outside_proposer_exact_authority_without_effects(
    field_name: str,
    reason_code: str,
) -> None:
    bounded_end = timezone.now() + timedelta(days=1)
    world = _delegated_assignment_world(
        proposer_role_expires_at=(bounded_end if field_name == "expires_at" else None)
    )
    candidate = _known_candidate(world)
    source = _active_role_control_grant(world, principal=world.proposer)
    requested_start = source.effective_from
    requested_end = None
    if field_name == "effective_from":
        requested_start -= timedelta(microseconds=1)
    else:
        assert source.expires_at is not None
        requested_end = source.expires_at + timedelta(microseconds=1)
    before = (
        PositionAssignment.objects.count(),
        PositionAssignmentCommandReceipt.objects.count(),
        RoleAssignment.objects.count(),
        ParticipationCapacity.objects.count(),
        Participation.objects.count(),
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    )

    with pytest.raises(ValidationError) as captured:
        _propose(
            world,
            candidate=candidate,
            effective_from=requested_start,
            expires_at=requested_end,
        )

    assert set(captured.value.error_dict) == {field_name}
    assert captured.value.error_dict[field_name][0].code == reason_code
    assert (
        PositionAssignment.objects.count(),
        PositionAssignmentCommandReceipt.objects.count(),
        RoleAssignment.objects.count(),
        ParticipationCapacity.objects.count(),
        Participation.objects.count(),
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    ) == before
    world.position.refresh_from_db()
    assert world.position.status == Position.Status.OPEN


@pytest.mark.parametrize("controller", ["proposer", "approver"])
@pytest.mark.parametrize("boundary", ["start", "end"])
def test_approval_rechecks_each_controller_interval_without_partial_activation(
    controller: str,
    boundary: str,
) -> None:
    world = _delegated_assignment_world()
    candidate = _known_candidate(world)
    initial_source = _active_role_control_grant(
        world,
        principal=world.proposer,
    )
    if boundary == "start":
        intended_start = initial_source.effective_from
        intended_end = None
    else:
        intended_start = timezone.now() + timedelta(hours=1)
        intended_end = intended_start + timedelta(days=2)
    proposed = _propose(
        world,
        candidate=candidate,
        effective_from=intended_start,
        expires_at=intended_end,
    )
    affected = getattr(world, controller)
    replacement_start = timezone.now()
    replacement_end = intended_start + timedelta(days=1) if boundary == "end" else None
    replacement = _replace_role_control_grant(
        world,
        principal=affected,
        effective_from=replacement_start,
        expires_at=replacement_end,
    )
    before = (
        RoleAssignment.objects.count(),
        ParticipationCapacity.objects.count(),
        Participation.objects.count(),
        PositionAssignmentCommandReceipt.objects.count(),
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    )

    with pytest.raises(AssignmentAuthorityIntervalConflictError) as captured:
        approve_position_assignment(
            actor=world.approver,
            organization_id=world.edition.organization_id,
            series_id=world.edition.series_id,
            edition_id=world.edition.id,
            assignment_id=proposed.assignment_id,
            expected_version=1,
            reason="Approve only while both exact controller sources cover it.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )

    assert captured.value.reason_code == "assignment_authority_interval_conflict"
    safe_error = str(captured.value)
    for undisclosed in (
        str(world.proposer.id),
        str(world.approver.id),
        str(replacement.id),
        replacement.effective_from.isoformat(),
    ):
        assert undisclosed not in safe_error
    assert (
        RoleAssignment.objects.count(),
        ParticipationCapacity.objects.count(),
        Participation.objects.count(),
        PositionAssignmentCommandReceipt.objects.count(),
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    ) == before
    assignment = PositionAssignment.objects.get(pk=proposed.assignment_id)
    assert assignment.status == PositionAssignment.Status.PROPOSED
    assert assignment.command_version == 1
    assert assignment.role_assignment_id is None
    assert assignment.participation_capacity_id is None
    assert assignment.decision_by_id is None
    assert assignment.command_receipts.count() == 1
    assert (
        PositionAssignment.objects.filter(
            position=world.position,
            status=PositionAssignment.Status.PROPOSED,
        ).count()
        == world.position.headcount
    )
    reservation_actor = world.approver if controller == "proposer" else world.proposer
    reservation_world = _AssignmentWorld(
        edition=world.edition,
        proposer=reservation_actor,
        approver=affected,
        position=world.position,
    )
    with pytest.raises(AssignmentHeadcountConflictError):
        _propose(
            reservation_world,
            candidate=_known_candidate(world),
        )


@pytest.mark.parametrize("source_loss", ["revoked", "expired"])
def test_approval_treats_unavailable_proposer_source_as_name_free_denial(
    source_loss: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bounded_end = timezone.now() + timedelta(days=1)
    world = _delegated_assignment_world(
        proposer_role_expires_at=bounded_end if source_loss == "expired" else None
    )
    candidate = _known_candidate(world)
    source = _active_role_control_grant(world, principal=world.proposer)
    proposed = _propose(
        world,
        candidate=candidate,
        effective_from=source.effective_from,
        expires_at=source.expires_at,
    )
    if source_loss == "revoked":
        target = resolve_edition_target(
            organization_id=world.edition.organization_id,
            edition_id=world.edition.id,
        )
        assert target is not None
        board_actor, _board_approver = activate_synthetic_board(
            world.edition.organization
        )
        revoke_capability_grant(
            actor=board_actor,
            target=target,
            grant_id=source.id,
            reason="Remove the proposer's exact role-control source.",
            correlation_id=uuid4(),
            source_channel="test",
        )
    else:
        assert source.expires_at is not None
        evaluated_after_expiry = source.expires_at + timedelta(microseconds=1)
        monkeypatch.setattr(timezone, "now", lambda: evaluated_after_expiry)
    before = (
        RoleAssignment.objects.count(),
        ParticipationCapacity.objects.count(),
        PositionAssignmentCommandReceipt.objects.count(),
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    )

    with pytest.raises(AssignmentAuthorizationDeniedError) as captured:
        approve_position_assignment(
            actor=world.approver,
            organization_id=world.edition.organization_id,
            series_id=world.edition.series_id,
            edition_id=world.edition.id,
            assignment_id=proposed.assignment_id,
            expected_version=1,
            reason="Do not activate without both current exact sources.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )

    assert captured.value.reason_code == "assignment_authorization_denied"
    safe_error = str(captured.value)
    for undisclosed in (
        str(world.proposer.id),
        str(world.approver.id),
        str(source.id),
        source.effective_from.isoformat(),
    ):
        assert undisclosed not in safe_error
    assert (
        RoleAssignment.objects.count(),
        ParticipationCapacity.objects.count(),
        PositionAssignmentCommandReceipt.objects.count(),
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    ) == before
    assignment = PositionAssignment.objects.get(pk=proposed.assignment_id)
    assert assignment.status == PositionAssignment.Status.PROPOSED
    assert assignment.command_version == 1
    assert assignment.role_assignment_id is None
    assert assignment.participation_capacity_id is None
    assert assignment.command_receipts.count() == 1


def test_proposal_replay_precedes_rechecking_a_replaced_controller_source() -> None:
    world = _delegated_assignment_world()
    candidate = _known_candidate(world)
    retry_key = uuid4()
    initial_source = _active_role_control_grant(
        world,
        principal=world.proposer,
    )
    intended_start = initial_source.effective_from
    proposed = _propose(
        world,
        candidate=candidate,
        retry_key=retry_key,
        effective_from=intended_start,
    )
    replacement = _replace_role_control_grant(
        world,
        principal=world.proposer,
        effective_from=timezone.now(),
        expires_at=None,
    )
    assert replacement.effective_from > intended_start

    replayed = _propose(
        world,
        candidate=candidate,
        retry_key=retry_key,
        effective_from=intended_start,
    )
    assert replayed.replayed
    assert replayed.receipt_id == proposed.receipt_id
    with pytest.raises(AssignmentRetryConflictError):
        _propose(
            world,
            candidate=candidate,
            retry_key=retry_key,
            reason="Changed retries remain conflicts before source validation.",
            effective_from=intended_start,
        )
    assert PositionAssignment.objects.count() == 1
    assert PositionAssignmentCommandReceipt.objects.count() == 1


def test_assignment_journey_preserves_dual_control_authority_and_history() -> None:  # noqa: PLR0915
    world = _assignment_world()
    candidate = _known_candidate(world)
    proposal_retry = uuid4()
    intended_start = timezone.now()

    proposed = _propose(
        world,
        candidate=candidate,
        retry_key=proposal_retry,
        effective_from=intended_start,
    )

    assignment = PositionAssignment.objects.get(pk=proposed.assignment_id)
    assert proposed.status == PositionAssignment.Status.PROPOSED
    assert proposed.resulting_version == 1
    assert assignment.command_version == 1
    assert assignment.role_assignment_id is None
    assert assignment.participation_capacity_id is None
    assert (
        PositionAssignmentCommandReceipt.objects.filter(
            assignment=assignment,
            action=PositionAssignmentCommandReceipt.Action.PROPOSED,
        ).count()
        == 1
    )

    replay = _propose(
        world,
        candidate=candidate,
        retry_key=proposal_retry,
        effective_from=intended_start,
    )
    assert replay == proposed.__class__(
        assignment_id=proposed.assignment_id,
        receipt_id=proposed.receipt_id,
        resulting_version=1,
        status=PositionAssignment.Status.PROPOSED,
        replayed=True,
    )
    with pytest.raises(AssignmentRetryConflictError):
        _propose(
            world,
            candidate=candidate,
            retry_key=proposal_retry,
            reason="A different command must use a different retry key.",
            effective_from=intended_start,
        )
    with pytest.raises(AssignmentAuthorizationDeniedError):
        approve_position_assignment(
            actor=world.proposer,
            organization_id=world.edition.organization_id,
            series_id=world.edition.series_id,
            edition_id=world.edition.id,
            assignment_id=assignment.id,
            expected_version=1,
            reason="Self-approval must remain impossible.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )

    approval_retry = uuid4()
    approved = approve_position_assignment(
        actor=world.approver,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        assignment_id=assignment.id,
        expected_version=1,
        reason="A second controller verified readiness and responsibility.",
        retry_key=approval_retry,
        correlation_id=uuid4(),
        source_channel="test",
    )

    assignment.refresh_from_db()
    world.position.refresh_from_db()
    assert approved.resulting_version == 2
    assert assignment.status == PositionAssignment.Status.ACTIVE
    assert assignment.decision_by == world.approver
    assert assignment.approved_by == world.approver
    assert assignment.decision_reason == (
        "A second controller verified readiness and responsibility."
    )
    assert assignment.role_assignment is not None
    assert assignment.role_assignment.revoked_at is None
    assert assignment.participation_capacity is not None
    assert (
        assignment.participation_capacity.status == ParticipationCapacity.Status.ACTIVE
    )
    assert world.position.status == Position.Status.FILLED

    approval_replay = approve_position_assignment(
        actor=world.approver,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        assignment_id=assignment.id,
        expected_version=1,
        reason="A second controller verified readiness and responsibility.",
        retry_key=approval_retry,
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert approval_replay.replayed
    assert approval_replay.receipt_id == approved.receipt_id

    ended = end_position_assignment(
        actor=world.proposer,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        assignment_id=assignment.id,
        expected_version=2,
        reason="The responsibility has been handed back after the event.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )

    assignment.refresh_from_db()
    world.position.refresh_from_db()
    assignment.role_assignment.refresh_from_db()
    assignment.participation_capacity.refresh_from_db()
    assert ended.resulting_version == 3
    assert assignment.status == PositionAssignment.Status.ENDED
    assert assignment.ended_by == world.proposer
    assert assignment.role_assignment.revoked_at is not None
    assert (
        assignment.participation_capacity.status
        == ParticipationCapacity.Status.COMPLETED
    )
    assert world.position.status == Position.Status.OPEN
    assert list(
        PositionAssignmentCommandReceipt.objects.filter(assignment=assignment)
        .order_by("resulting_version")
        .values_list("action", flat=True)
    ) == ["proposed", "approved", "ended"]
    assert (
        AuditEvent.objects.filter(
            target_id=assignment.id,
            outcome=AuditEvent.Outcome.ALLOW,
        ).count()
        == 4
    )
    assert set(
        DomainEvent.objects.filter(aggregate_id=assignment.id).values_list(
            "event_name",
            flat=True,
        )
    ) >= {
        "workforce.position_assignment.proposed.v1",
        "workforce.position_assignment.activated.v1",
        "workforce.position_assignment.ended.v1",
    }
    self_items = my_assignment_items(
        account=candidate,
        permitted_scopes=frozenset({(world.edition.organization_id, world.edition.id)}),
    )
    assert len(self_items) == 1
    assert self_items[0].state_label == "Ended"
    with pytest.raises(IntegrityError, match="governed ending evidence is invalid"):
        PositionAssignment.objects.filter(pk=assignment.pk).update(
            participation_capacity=None
        )


def test_workforce_only_assignment_never_creates_participation_evidence() -> None:
    world = _assignment_world(
        adoption_profile_code=AdoptionProfileCode.WORKFORCE_ONLY,
    )
    candidate = AccountFactory()
    OrganizationMembershipFactory(
        organization=world.edition.organization,
        account=candidate,
        relationship_label="Workforce volunteer",
    )
    assert not Participation.objects.filter(
        account=candidate,
        edition=world.edition,
    ).exists()

    browser = Client()
    browser.force_login(world.proposer)
    proposal_page = browser.get(
        _browser_url(
            "organization-workforce-assignment-proposal",
            world,
            position_id=world.position.id,
        )
    )
    proposal_content = proposal_page.content.decode()
    assert proposal_page.status_code == 200
    assert "Workforce labels" in proposal_content
    assert "Participation labels" not in proposal_content
    assert "creates no active Workforce assignment" in proposal_content

    proposed = _propose(world, candidate=candidate)
    approved = approve_position_assignment(
        actor=world.approver,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        assignment_id=proposed.assignment_id,
        expected_version=1,
        reason="A second controller verified this Workforce responsibility.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )

    assignment = PositionAssignment.objects.get(pk=approved.assignment_id)
    assert assignment.status == PositionAssignment.Status.ACTIVE
    assert assignment.role_assignment_id is not None
    assert assignment.participation_capacity_id is None
    assert not Participation.objects.filter(
        account=candidate,
        edition=world.edition,
    ).exists()

    personal = Client()
    personal.force_login(candidate)
    personal_page = personal.get(reverse("my-workforce-assignments"))
    personal_content = personal_page.content.decode()
    assert personal_page.status_code == 200
    assert "My Workforce" in personal_content
    assert "Registration &amp; tickets" not in personal_content
    assert "Shop &amp; orders" not in personal_content
    assert "My schedule" not in personal_content
    assert "Equipment offers" not in personal_content
    assert "Convention workspace" in personal_content
    assert ">Administration<" not in personal_content

    ended = end_position_assignment(
        actor=world.proposer,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        assignment_id=assignment.id,
        expected_version=2,
        reason="The bounded Workforce responsibility ended.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )

    assignment.refresh_from_db()
    assignment.role_assignment.refresh_from_db()
    assert ended.status == PositionAssignment.Status.ENDED
    assert assignment.role_assignment.revoked_at is not None
    assert assignment.participation_capacity_id is None
    assert not Participation.objects.filter(
        account=candidate,
        edition=world.edition,
    ).exists()


def test_readiness_candidate_and_headcount_conflicts_do_not_partially_write() -> None:
    world = _assignment_world()
    candidate = _known_candidate(world)
    outsider = AccountFactory()
    document_type = OnboardingDocumentType.objects.create(
        organization=world.edition.organization,
        edition=world.edition,
        code="assignment-agreement",
        name="Assignment agreement",
        description="Synthetic approval prerequisite.",
        status=OnboardingDocumentType.Status.ACTIVE,
        created_by=world.proposer,
    )
    PositionDocumentRequirement.objects.create(
        position=world.position,
        document_type=document_type,
    )
    proposed = _propose(world, candidate=candidate)

    with pytest.raises(AssignmentReadinessConflictError):
        approve_position_assignment(
            actor=world.approver,
            organization_id=world.edition.organization_id,
            series_id=world.edition.series_id,
            edition_id=world.edition.id,
            assignment_id=proposed.assignment_id,
            expected_version=1,
            reason="Approval must wait for onboarding.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
    assignment = PositionAssignment.objects.get(pk=proposed.assignment_id)
    assert assignment.status == PositionAssignment.Status.PROPOSED
    assert assignment.command_receipts.count() == 1
    assert not AuditEvent.objects.filter(
        target_id=assignment.id,
        operation="workforce.position_assignment.approve",
    ).exists()

    rejected = reject_position_assignment(
        actor=world.approver,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        assignment_id=assignment.id,
        expected_version=1,
        reason="The required agreement is not ready.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    assignment.refresh_from_db()
    assert rejected.status == PositionAssignment.Status.REJECTED
    assert assignment.status == PositionAssignment.Status.REJECTED
    assert assignment.decision_by == world.approver
    assert assignment.role_assignment_id is None

    with pytest.raises(AssignmentCandidateUnavailableError):
        _propose(world, candidate=outsider)
    assert not PositionAssignment.objects.filter(account=outsider).exists()

    replacement = _known_candidate(world)
    replacement_proposal = _propose(world, candidate=replacement)
    assert replacement_proposal.status == PositionAssignment.Status.PROPOSED
    overflow_candidate = _known_candidate(world)
    with pytest.raises(AssignmentHeadcountConflictError):
        _propose(world, candidate=overflow_candidate)
    assert not PositionAssignment.objects.filter(account=overflow_candidate).exists()


def test_browser_authority_interval_conflict_is_action_local_and_recoverable() -> None:  # noqa: PLR0915
    world = _delegated_assignment_world()
    candidate = _known_candidate(world)
    initial_source = _active_role_control_grant(
        world,
        principal=world.proposer,
    )
    proposed = _propose(
        world,
        candidate=candidate,
        effective_from=initial_source.effective_from,
    )
    replacement = _replace_role_control_grant(
        world,
        principal=world.proposer,
        effective_from=timezone.now(),
        expires_at=None,
    )
    client = Client()
    client.force_login(world.approver)
    detail_url = _browser_url(
        "organization-workforce-assignment",
        world,
        assignment_id=proposed.assignment_id,
    )
    detail = client.get(detail_url)
    assert detail.status_code == 200
    approval_form = detail.context["approve_form"]
    _mark_current_session_step_up(client, actor=world.approver)

    failed = client.post(
        _browser_url(
            "approve-organization-workforce-assignment",
            world,
            assignment_id=proposed.assignment_id,
        ),
        {
            "expected_version": str(approval_form["expected_version"].value()),
            "retry_key": str(approval_form["retry_key"].value()),
            "reason": "Attempt approval after the proposer source changed.",
        },
    )

    recovery = (
        "This immutable proposal is outside current controlling authority. "
        "Reload it, reject it, and create a new proposal within current authority."
    )
    assert failed.status_code == 409
    assert failed.context["active_action"] == "approve"
    assert failed.context["reload_required"] is False
    assert failed.context["interval_recovery_available"] is True
    assert failed.context["can_decide_assignment"] is True
    assert failed.context["can_approve_assignment"] is False
    assert failed.context["action_error"] == recovery
    failed_content = failed.content.decode()
    assert recovery in strip_tags(failed_content)
    assert "Reload the latest assignment" in strip_tags(failed_content)
    approve_button = re.search(
        r'<button type="submit"([^>]*)>Approve and activate</button>',
        failed_content,
    )
    reject_button = re.search(
        r'<button type="submit"([^>]*)>Reject proposal</button>',
        failed_content,
    )
    assert approve_button is not None
    assert "disabled" in approve_button.group(1)
    assert reject_button is not None
    assert "disabled" not in reject_button.group(1)
    for undisclosed in (
        str(initial_source.id),
        str(replacement.id),
        initial_source.effective_from.isoformat(),
        replacement.effective_from.isoformat(),
    ):
        assert undisclosed not in failed.context["action_error"]
    assignment = PositionAssignment.objects.get(pk=proposed.assignment_id)
    assert assignment.status == PositionAssignment.Status.PROPOSED
    assert assignment.command_version == 1
    assert assignment.role_assignment_id is None
    assert assignment.participation_capacity_id is None

    rejection_form = failed.context["reject_form"]
    assert rejection_form.is_bound is False
    assert str(rejection_form["expected_version"].value()) == "1"
    assert rejection_form["retry_key"].value() != approval_form["retry_key"].value()
    with patch(
        "maru.workforce.views.approve_position_assignment",
        side_effect=AssignmentStateConflictError,
    ):
        generic = client.post(
            _browser_url(
                "approve-organization-workforce-assignment",
                world,
                assignment_id=proposed.assignment_id,
            ),
            {
                "expected_version": "1",
                "retry_key": str(uuid4()),
                "reason": "A generic conflict must still require reload.",
            },
        )
    generic_content = generic.content.decode()
    generic_approve_button = re.search(
        r'<button type="submit"([^>]*)>Approve and activate</button>',
        generic_content,
    )
    generic_reject_button = re.search(
        r'<button type="submit"([^>]*)>Reject proposal</button>',
        generic_content,
    )
    assert generic.status_code == 409
    assert generic.context["reload_required"] is True
    assert generic.context["interval_recovery_available"] is False
    assert generic_approve_button is not None
    assert "disabled" in generic_approve_button.group(1)
    assert generic_reject_button is not None
    assert "disabled" in generic_reject_button.group(1)
    rejected = client.post(
        _browser_url(
            "reject-organization-workforce-assignment",
            world,
            assignment_id=proposed.assignment_id,
        ),
        {
            "expected_version": str(rejection_form["expected_version"].value()),
            "retry_key": str(rejection_form["retry_key"].value()),
            "reason": "Reject the immutable proposal before recreating it.",
        },
    )
    assert rejected.status_code == 302
    assignment.refresh_from_db()
    assert assignment.status == PositionAssignment.Status.REJECTED
    recreated = _propose(
        world,
        candidate=candidate,
        effective_from=replacement.effective_from,
    )
    assert recreated.assignment_id != assignment.id
    assert recreated.status == PositionAssignment.Status.PROPOSED


@pytest.mark.parametrize(
    ("local_effective_from", "expected_code"),
    [
        ("2026-03-29T02:30", "nonexistent"),
        ("2026-10-25T02:30", "ambiguous"),
    ],
    ids=("iana-dst-gap", "iana-dst-fold"),
)
def test_browser_proposal_rejects_dst_gap_and_fold_without_creating_assignment(
    local_effective_from: str,
    expected_code: str,
) -> None:
    world = _assignment_world()
    assert world.edition.time_zone == "Europe/Budapest"
    candidate = _known_candidate(world)
    client = Client()
    client.force_login(world.proposer)

    response = client.post(
        _browser_url(
            "propose-organization-workforce-assignment",
            world,
            position_id=world.position.id,
        ),
        {
            "account_id": str(candidate.id),
            "effective_from": local_effective_from,
            "expires_at": "",
            "reason": "Reject a local minute that does not identify one instant.",
            "retry_key": str(uuid4()),
        },
    )

    assert response.status_code == 400
    form = response.context["form"]
    assert set(form.errors) == {"effective_from"}
    assert form.errors.as_data()["effective_from"][0].code == expected_code
    assert form["effective_from"].value() == local_effective_from
    assert not PositionAssignment.objects.filter(account=candidate).exists()
    assert not PositionAssignmentCommandReceipt.objects.filter(
        assignment__account=candidate,
    ).exists()


def test_browser_dual_control_and_self_privacy() -> None:  # noqa: PLR0915
    world = _assignment_world()
    candidate = _known_candidate(world)
    proposer_client = Client()
    proposer_client.force_login(world.proposer)
    overview_url = _browser_url("organization-workforce-assignments", world)
    proposal_url = _browser_url(
        "organization-workforce-assignment-proposal",
        world,
        position_id=world.position.id,
    )

    overview = proposer_client.get(overview_url)
    proposal_page = proposer_client.get(proposal_url)

    assert overview.status_code == 200
    assert proposal_page.status_code == 200
    _assert_private_no_store(overview)
    overview_text = strip_tags(overview.content.decode())
    assert "Workforce assignments" in overview_text
    assert "Availability" in overview_text
    assert "Shifts" in overview_text
    form = proposal_page.context["form"]
    submitted = proposer_client.post(
        _browser_url(
            "propose-organization-workforce-assignment",
            world,
            position_id=world.position.id,
        ),
        {
            "account_id": str(candidate.id),
            "effective_from": str(form["effective_from"].value()),
            "expires_at": "",
            "reason": "The known participant is prepared for this role.",
            "retry_key": str(form["retry_key"].value()),
        },
    )
    assert submitted.status_code == 302
    assignment = PositionAssignment.objects.get(account=candidate)
    detail_url = _browser_url(
        "organization-workforce-assignment",
        world,
        assignment_id=assignment.id,
    )
    assert submitted["Location"] == detail_url
    proposer_detail = proposer_client.get(detail_url)
    proposer_text = strip_tags(proposer_detail.content.decode())
    assert "Waiting for another controller" in proposer_text
    assert "Approve and activate" not in proposer_text

    approver_client = Client()
    approver_client.force_login(world.approver)
    approver_detail = approver_client.get(detail_url)
    assert approver_detail.status_code == 200
    approval_form = approver_detail.context["approve_form"]
    sentinel = "private-body-must-not-be-parsed-before-step-up"
    gated = approver_client.post(
        _browser_url(
            "approve-organization-workforce-assignment",
            world,
            assignment_id=assignment.id,
        ),
        {sentinel: sentinel},
    )
    assert gated.status_code == 302
    assert gated["Location"].startswith(reverse("account-step-up"))
    assert sentinel not in gated["Location"]
    assignment.refresh_from_db()
    assert assignment.status == PositionAssignment.Status.PROPOSED

    _mark_current_session_step_up(approver_client, actor=world.approver)
    approved = approver_client.post(
        _browser_url(
            "approve-organization-workforce-assignment",
            world,
            assignment_id=assignment.id,
        ),
        {
            "expected_version": str(approval_form["expected_version"].value()),
            "retry_key": str(approval_form["retry_key"].value()),
            "reason": "A second controller verified the complete proposal.",
        },
    )
    assert approved.status_code == 302, approved.context.get("action_error")
    assert approved["Location"] == detail_url
    assignment.refresh_from_db()
    assert assignment.status == PositionAssignment.Status.ACTIVE
    decision_page = approver_client.get(detail_url)
    decision_text = strip_tags(decision_page.content.decode())
    assert "Assignment decision history" in decision_text
    assert "A second controller verified the complete proposal." in decision_text

    self_client = Client()
    self_client.force_login(candidate)
    self_page = self_client.get(reverse("my-workforce-assignments"))
    self_text = strip_tags(self_page.content.decode())
    assert self_page.status_code == 200
    _assert_private_no_store(self_page)
    assert "Guest Services Member" in self_text
    assert "Status: Active" in self_text
    assert "The known participant is prepared for this role." not in self_text
    assert "A second controller verified the complete proposal." not in self_text
    assert (
        self_client.get(
            reverse("my-workforce-assignments"),
            {"unknown": "1"},
        ).status_code
        == 400
    )


def test_assignment_api_is_strict_idempotent_and_step_up_gated() -> None:
    world = _assignment_world()
    candidate = _known_candidate(world)
    proposal_url = reverse(
        "api-workforce-position-assignments",
        args=[
            world.edition.organization_id,
            world.edition.id,
            world.position.id,
        ],
    )
    payload = {
        "account_id": str(candidate.id),
        "effective_from": timezone.now().isoformat(),
        "expires_at": None,
        "reason": "Prepare a known participant for independent approval.",
    }
    api_client = APIClient()
    api_client.force_authenticate(world.proposer)
    retry_key = uuid4()
    unknown = api_client.post(
        proposal_url,
        {**payload, "unexpected": "not accepted"},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(retry_key),
    )
    created = api_client.post(
        proposal_url,
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(retry_key),
    )
    replayed = api_client.post(
        proposal_url,
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(retry_key),
    )

    assert unknown.status_code == 400
    assert unknown.json()["code"] == "unknown_input_field"
    assert created.status_code == 201
    assert replayed.status_code == 200
    assert replayed.json() == created.json()
    assignment = PositionAssignment.objects.get(pk=created.json()["assignment_id"])
    approve_url = reverse(
        "api-workforce-assignment-approve",
        args=[world.edition.organization_id, world.edition.id, assignment.id],
    )

    approver_api = APIClient()
    approver_api.force_login(world.approver)
    gated = approver_api.post(
        approve_url,
        {"private_sentinel": "must not be parsed"},
        format="json",
    )
    assert gated.status_code == 403
    assert gated.json()["code"] == "step_up_required"
    _mark_current_session_step_up(approver_api, actor=world.approver)
    approved = approver_api.post(
        approve_url,
        {
            "expected_version": 1,
            "reason": "Approve the exact proposal after fresh authentication.",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert approved.status_code == 200
    assert approved.json() == {
        "assignment_id": str(assignment.id),
        "assignment_version": 2,
        "status": PositionAssignment.Status.ACTIVE,
    }


def test_assignment_api_returns_field_local_proposer_interval_validation() -> None:
    world = _delegated_assignment_world()
    candidate = _known_candidate(world)
    source = _active_role_control_grant(world, principal=world.proposer)
    proposal_url = reverse(
        "api-workforce-position-assignments",
        args=[
            world.edition.organization_id,
            world.edition.id,
            world.position.id,
        ],
    )
    api_client = APIClient()
    api_client.force_authenticate(world.proposer)

    response = api_client.post(
        proposal_url,
        {
            "account_id": str(candidate.id),
            "effective_from": (
                source.effective_from - timedelta(microseconds=1)
            ).isoformat(),
            "expires_at": None,
            "reason": "Reject the interval before reserving this Position.",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )

    payload = response.json()
    assert response.status_code == 400
    assert payload["code"] == "authority_effective_from_too_early"
    assert set(payload["errors"]) == {"effective_from"}
    assert payload["errors"]["effective_from"] == [
        "The assignment cannot start before current controlling authority."
    ]
    serialized = response.content.decode()
    assert str(source.id) not in serialized
    assert str(world.proposer.id) not in serialized
    assert not PositionAssignment.objects.filter(account=candidate).exists()
    assert not PositionAssignmentCommandReceipt.objects.filter(
        assignment__account=candidate
    ).exists()


def test_assignment_api_returns_typed_non_disclosing_approval_interval_conflict() -> (
    None
):
    world = _delegated_assignment_world()
    candidate = _known_candidate(world)
    intended_start = timezone.now() + timedelta(hours=1)
    intended_end = intended_start + timedelta(days=2)
    proposed = _propose(
        world,
        candidate=candidate,
        effective_from=intended_start,
        expires_at=intended_end,
    )
    replacement = _replace_role_control_grant(
        world,
        principal=world.approver,
        effective_from=timezone.now(),
        expires_at=intended_start + timedelta(days=1),
    )
    approve_url = reverse(
        "api-workforce-assignment-approve",
        args=[world.edition.organization_id, world.edition.id, proposed.assignment_id],
    )
    api_client = APIClient()
    api_client.force_login(world.approver)
    gated = api_client.post(
        approve_url,
        {"private_sentinel": "must not be parsed before step-up"},
        format="json",
    )
    assert gated.status_code == 403
    assert gated.json()["code"] == "step_up_required"
    _mark_current_session_step_up(api_client, actor=world.approver)

    response = api_client.post(
        approve_url,
        {
            "expected_version": 1,
            "reason": "Recheck both exact controller intervals at approval.",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )

    payload = response.json()
    assert response.status_code == 409
    assert payload["code"] == "assignment_authority_interval_conflict"
    assert payload["errors"] == {
        "non_field_errors": [
            "Reload the assignment, reject this immutable proposal, and recreate "
            "it within current controlling authority."
        ]
    }
    serialized = response.content.decode()
    for undisclosed in (
        str(world.proposer.id),
        str(world.approver.id),
        str(replacement.id),
        replacement.effective_from.isoformat(),
        replacement.expires_at.isoformat() if replacement.expires_at else "",
    ):
        assert undisclosed not in serialized
    assignment = PositionAssignment.objects.get(pk=proposed.assignment_id)
    assert assignment.status == PositionAssignment.Status.PROPOSED
    assert assignment.command_version == 1
    assert assignment.role_assignment_id is None
    assert assignment.participation_capacity_id is None
    assert assignment.command_receipts.count() == 1


def test_database_requires_exact_receipt_and_keeps_receipts_immutable() -> None:
    world = _assignment_world()
    candidate = _known_candidate(world)

    with (
        pytest.raises(IntegrityError, match="exact immutable command evidence"),
        transaction.atomic(),
    ):
        PositionAssignment.objects.create(
            position=world.position,
            organization=world.edition.organization,
            edition=world.edition,
            account=candidate,
            status=PositionAssignment.Status.PROPOSED,
            effective_from=timezone.now(),
            proposed_by=world.proposer,
            reason="A governed row without a receipt must roll back.",
            command_version=1,
        )
    assert not PositionAssignment.objects.filter(account=candidate).exists()

    proposed = _propose(world, candidate=candidate)
    assignment = PositionAssignment.objects.get(pk=proposed.assignment_id)
    receipt = assignment.command_receipts.get(resulting_version=1)
    receipt.reason = "Rewritten evidence is forbidden."
    with pytest.raises(ValidationError, match="immutable"):
        receipt.save()
    with pytest.raises(ValidationError, match="immutable"):
        receipt.delete()
    with pytest.raises(IntegrityError, match="receipts are immutable"):
        PositionAssignmentCommandReceipt.objects.filter(pk=receipt.pk).update(
            reason="Bulk rewriting is also forbidden."
        )
