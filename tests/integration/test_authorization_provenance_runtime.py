"""Dynamic, source-bearing ADR 0044 authorization provenance coverage."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from django.db import transaction
from django.utils import timezone

from maru.authorization import provenance
from maru.authorization.issuance import (
    create_delegated_grant_issuance,
    create_persistent_dual_control_issuance,
)
from maru.authorization.models import (
    AuthorityControl,
    AuthorityIssuance,
    CapabilityGrant,
    RoleAssignment,
    RoleBundle,
)
from maru.authorization.policy import (
    ResolvedAuthorizationTarget,
    resolve_edition_target,
    resolve_organization_target,
)
from maru.authorization.provenance import (
    ControlHorizonMode,
    PersistentSourceKind,
    authority_issuance_is_current,
    authorized_control_is_current,
    role_bundle_provenance_is_historical,
    select_authorized_control_source,
)
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import (
    Organization,
    OrganizationRepresentation,
    RepresentationAppointment,
)
from maru.organizations.representation import (
    activate_executive_board,
    invite_representation_controller,
    provision_executive_board,
    respond_to_representation_invitation,
)
from tests.factories import AccountFactory, EventEditionFactory, OrganizationFactory

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _required_target(
    target: ResolvedAuthorizationTarget | None,
) -> ResolvedAuthorizationTarget:
    assert target is not None
    return target


def _activate_board() -> tuple[
    Account,
    OrganizationRepresentation,
    tuple[RepresentationAppointment, RepresentationAppointment],
]:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    representation = provision_executive_board(
        actor=administrator,
        organization_id=organization.id,
        reason="Create a synthetic provenance trust root.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    accepted: list[RepresentationAppointment] = []
    for _index in range(2):
        controller = AccountFactory()
        invitation = invite_representation_controller(
            actor=administrator,
            representation_id=representation.id,
            account_id=controller.id,
            reason="Invite a synthetic provenance controller.",
            correlation_id=uuid4(),
            source_channel="test",
        )
        accepted.append(
            respond_to_representation_invitation(
                actor=controller,
                appointment_id=invitation.id,
                expected_version=invitation.invitation_version,
                accept=True,
                correlation_id=uuid4(),
                source_channel="test",
            )
        )
    representation.refresh_from_db()
    result = activate_executive_board(
        actor=administrator,
        representation_id=representation.id,
        expected_version=representation.aggregate_version,
        reason="Activate the synthetic provenance trust root.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    appointments = tuple(
        RepresentationAppointment.objects.filter(representation=result.representation)
        .select_related("account", "role_assignment")
        .order_by("responded_at", "id")
    )
    assert len(appointments) == 2
    return administrator, result.representation, (appointments[0], appointments[1])


def _board_source(appointment: RepresentationAppointment) -> AuthorityIssuance:
    assert appointment.role_assignment_id is not None
    return AuthorityIssuance.objects.get(
        role_assignment_id=appointment.role_assignment_id
    )


def _issue_grant(
    *,
    representation: OrganizationRepresentation,
    appointments: tuple[RepresentationAppointment, RepresentationAppointment],
    principal: Account,
    capability_code: str,
    edition: EventEdition | None = None,
    expires_at: datetime | None = None,
) -> tuple[CapabilityGrant, AuthorityIssuance]:
    evaluated_at = timezone.now()
    actor, approver = appointments
    grant = CapabilityGrant.objects.create(
        organization=representation.organization,
        edition=edition,
        principal=principal,
        capability_code=capability_code,
        effective_from=evaluated_at,
        expires_at=expires_at,
        granted_by=actor.account,
        approved_by=approver.account,
        reason="Issue a synthetic source-bearing grant.",
    )
    issuance = create_persistent_dual_control_issuance(
        target=grant,
        actor_source=_board_source(actor),
        approver_source=_board_source(approver),
        evaluated_at=evaluated_at,
    )
    return grant, issuance


def _select(
    *,
    principal: Account,
    capability_code: str,
    target: ResolvedAuthorizationTarget,
    requested_expires_at: datetime | None = None,
    requested_effective_from: datetime | None = None,
    evaluated_at: datetime | None = None,
    horizon_mode: ControlHorizonMode = ControlHorizonMode.PERSISTENT,
) -> provenance.AuthorizedControl | None:
    effective_evaluation = evaluated_at or timezone.now()
    with transaction.atomic():
        return select_authorized_control_source(
            principal=principal,
            role=AuthorityControl.Role.ACTOR,
            capability_code=capability_code,
            target=target,
            requested_effective_from=(requested_effective_from or effective_evaluation),
            requested_expires_at=requested_expires_at,
            evaluated_at=effective_evaluation,
            horizon_mode=horizon_mode,
        )


def _issue_role_assignment(
    *,
    representation: OrganizationRepresentation,
    appointments: tuple[RepresentationAppointment, RepresentationAppointment],
    principal: Account,
    code: str,
    expires_at: datetime,
) -> tuple[RoleAssignment, AuthorityIssuance]:
    actor, approver = appointments
    evaluated_at = timezone.now()
    bundle = RoleBundle.objects.create(
        organization=representation.organization,
        code=code,
        name=f"Synthetic {code}",
        version=1,
        capability_codes=["events.view_basic"],
        created_by=actor.account,
        approved_by=approver.account,
        reason="Create a source-ranked synthetic role definition.",
    )
    create_persistent_dual_control_issuance(
        target=bundle,
        actor_source=_board_source(actor),
        approver_source=_board_source(approver),
        evaluated_at=evaluated_at,
    )
    assignment = RoleAssignment.objects.create(
        organization=representation.organization,
        principal=principal,
        role_bundle=bundle,
        effective_from=evaluated_at,
        expires_at=expires_at,
        granted_by=actor.account,
        approved_by=approver.account,
        reason="Create a source-ranked synthetic role assignment.",
    )
    issuance = create_persistent_dual_control_issuance(
        target=assignment,
        actor_source=_board_source(actor),
        approver_source=_board_source(approver),
        evaluated_at=evaluated_at,
    )
    return assignment, issuance


def test_board_assignment_is_an_exact_current_source_but_platform_admin_is_not() -> (
    None
):
    administrator, representation, appointments = _activate_board()
    controller = appointments[0].account
    target = _required_target(
        resolve_organization_target(organization_id=representation.organization_id)
    )
    evaluated_at = timezone.now()
    assert representation.activated_at is not None

    selected = _select(
        principal=controller,
        capability_code="authorization.grant_direct",
        target=target,
        requested_effective_from=representation.activated_at,
        evaluated_at=evaluated_at,
    )

    assert selected is not None
    assert selected.source_kind is PersistentSourceKind.ROLE_ASSIGNMENT
    assert selected.source_issuance_ordinal == _board_source(appointments[0]).ordinal
    assert authorized_control_is_current(
        control=selected,
        target=target,
        requested_effective_from=representation.activated_at,
        requested_expires_at=None,
        evaluated_at=evaluated_at,
    )
    assert (
        _select(
            principal=administrator,
            capability_code="authorization.grant_direct",
            target=target,
            evaluated_at=evaluated_at,
        )
        is None
    )


def test_point_in_time_mode_uses_bounded_direct_source_without_weakening_horizon() -> (
    None
):
    _administrator, representation, appointments = _activate_board()
    controller = appointments[0].account
    evaluated_at = timezone.now()
    expires_at = evaluated_at + timedelta(hours=1)
    grant, issuance = _issue_grant(
        representation=representation,
        appointments=appointments,
        principal=controller,
        capability_code="authorization.manage_roles",
        expires_at=expires_at,
    )
    evaluated_at = timezone.now()
    target = _required_target(
        resolve_organization_target(organization_id=representation.organization_id)
    )

    point_source = _select(
        principal=controller,
        capability_code="authorization.manage_roles",
        target=target,
        evaluated_at=evaluated_at,
        horizon_mode=ControlHorizonMode.POINT_IN_TIME,
    )
    persistent_source = _select(
        principal=controller,
        capability_code="authorization.manage_roles",
        target=target,
        evaluated_at=evaluated_at,
    )

    assert point_source is not None
    assert point_source.source_kind is PersistentSourceKind.CAPABILITY_GRANT
    assert point_source.source_authority_id == grant.id
    assert point_source.source_issuance_ordinal == issuance.ordinal
    assert persistent_source is not None
    assert persistent_source.source_kind is PersistentSourceKind.ROLE_ASSIGNMENT


def test_role_bundle_wrapper_accepts_proven_board_and_rejects_unproven_bundle() -> None:
    _administrator, representation, appointments = _activate_board()
    board_bundle = RoleBundle.objects.get(
        organization=representation.organization,
        code="executive-board",
    )
    with transaction.atomic():
        assert role_bundle_provenance_is_historical(
            bundle=board_bundle,
            lock=True,
        )

    with transaction.atomic():
        unproven = RoleBundle.objects.create(
            organization=representation.organization,
            code="unproven-legacy-role",
            name="Unproven legacy role",
            version=1,
            capability_codes=["events.view_basic"],
            created_by=appointments[0].account,
            approved_by=appointments[1].account,
            reason="Exercise fail-closed legacy bundle handling.",
        )
        assert not role_bundle_provenance_is_historical(
            bundle=unproven,
            lock=True,
        )
        transaction.set_rollback(True)


def test_ordinary_bundle_keeps_historical_direct_grant_control_proof() -> None:
    _administrator, representation, appointments = _activate_board()
    evaluated_at = timezone.now()
    controllers = (AccountFactory(), AccountFactory())
    source_issuances: list[AuthorityIssuance] = []
    source_grants: list[CapabilityGrant] = []
    for controller in controllers:
        source = CapabilityGrant.objects.create(
            organization=representation.organization,
            principal=controller,
            capability_code="authorization.manage_roles",
            effective_from=evaluated_at,
            granted_by=appointments[0].account,
            approved_by=appointments[1].account,
            reason="Issue synthetic delegated role-management authority.",
        )
        source_grants.append(source)
        source_issuances.append(
            create_persistent_dual_control_issuance(
                target=source,
                actor_source=_board_source(appointments[0]),
                approver_source=_board_source(appointments[1]),
                evaluated_at=evaluated_at,
            )
        )
    bundle = RoleBundle.objects.create(
        organization=representation.organization,
        code="historically-proven-direct-controls",
        name="Historically proven direct controls",
        version=1,
        capability_codes=["events.view_basic"],
        created_by=controllers[0],
        approved_by=controllers[1],
        reason="Exercise historical ordinary grant controls.",
    )
    bundle_issuance = create_persistent_dual_control_issuance(
        target=bundle,
        actor_source=source_issuances[0],
        approver_source=source_issuances[1],
        evaluated_at=evaluated_at,
    )

    assert role_bundle_provenance_is_historical(bundle=bundle)

    for source in source_grants:
        source.revoked_at = bundle_issuance.evaluated_at + timedelta(microseconds=1)
        source.revoked_by = appointments[0].account
        source.revocation_reason = "End synthetic authority after bundle creation."
        source.save(
            update_fields=(
                "revoked_at",
                "revoked_by",
                "revocation_reason",
                "updated_at",
            )
        )

    assert role_bundle_provenance_is_historical(
        bundle=bundle,
        evaluated_at=bundle_issuance.evaluated_at + timedelta(seconds=1),
    )


def test_ordinary_bundle_recurses_through_role_assignment_control_proof() -> None:
    _administrator, representation, appointments = _activate_board()
    evaluated_at = timezone.now()
    controller_bundle = RoleBundle.objects.create(
        organization=representation.organization,
        code="historical-role-controllers",
        name="Historical role controllers",
        version=1,
        capability_codes=["authorization.manage_roles"],
        created_by=appointments[0].account,
        approved_by=appointments[1].account,
        reason="Create a proven role-management definition.",
    )
    create_persistent_dual_control_issuance(
        target=controller_bundle,
        actor_source=_board_source(appointments[0]),
        approver_source=_board_source(appointments[1]),
        evaluated_at=evaluated_at,
    )
    controllers = (AccountFactory(), AccountFactory())
    assignment_issuances: list[AuthorityIssuance] = []
    assignments: list[RoleAssignment] = []
    for controller in controllers:
        assignment = RoleAssignment.objects.create(
            organization=representation.organization,
            principal=controller,
            role_bundle=controller_bundle,
            effective_from=evaluated_at,
            granted_by=appointments[0].account,
            approved_by=appointments[1].account,
            reason="Assign synthetic historical role-management authority.",
        )
        assignments.append(assignment)
        assignment_issuances.append(
            create_persistent_dual_control_issuance(
                target=assignment,
                actor_source=_board_source(appointments[0]),
                approver_source=_board_source(appointments[1]),
                evaluated_at=evaluated_at,
            )
        )
    downstream_bundle = RoleBundle.objects.create(
        organization=representation.organization,
        code="historically-proven-role-controls",
        name="Historically proven role controls",
        version=1,
        capability_codes=["events.view_basic"],
        created_by=controllers[0],
        approved_by=controllers[1],
        reason="Exercise recursive historical role controls.",
    )
    downstream_issuance = create_persistent_dual_control_issuance(
        target=downstream_bundle,
        actor_source=assignment_issuances[0],
        approver_source=assignment_issuances[1],
        evaluated_at=evaluated_at,
    )

    assert role_bundle_provenance_is_historical(bundle=downstream_bundle)

    assignments[0].revoked_at = downstream_issuance.evaluated_at + timedelta(
        microseconds=1
    )
    assignments[0].revoked_by = appointments[0].account
    assignments[0].revocation_reason = "End role authority after bundle creation."
    assignments[0].save(
        update_fields=(
            "revoked_at",
            "revoked_by",
            "revocation_reason",
            "updated_at",
        )
    )

    assert role_bundle_provenance_is_historical(
        bundle=downstream_bundle,
        evaluated_at=downstream_issuance.evaluated_at + timedelta(seconds=1),
    )


def test_selection_prefers_narrow_scope_then_direct_grant() -> None:
    _administrator, representation, appointments = _activate_board()
    principal = AccountFactory()
    edition = EventEditionFactory(
        organization=representation.organization,
        series__organization=representation.organization,
    )
    _organization_grant, _organization_issuance = _issue_grant(
        representation=representation,
        appointments=appointments,
        principal=principal,
        capability_code="events.view_basic",
    )
    edition_grant, edition_issuance = _issue_grant(
        representation=representation,
        appointments=appointments,
        principal=principal,
        capability_code="events.view_basic",
        edition=edition,
    )
    target = _required_target(
        resolve_edition_target(
            organization_id=representation.organization_id,
            edition_id=edition.id,
        )
    )

    selected = _select(
        principal=principal,
        capability_code="events.view_basic",
        target=target,
        evaluated_at=timezone.now(),
    )

    assert selected is not None
    assert selected.source_kind is PersistentSourceKind.CAPABILITY_GRANT
    assert selected.source_authority_id == edition_grant.id
    assert selected.source_issuance_ordinal == edition_issuance.ordinal


def test_role_selection_uses_least_surplus_expiry_then_issuance_ordinal() -> None:
    _administrator, representation, appointments = _activate_board()
    principal = AccountFactory()
    now = timezone.now()
    _long_assignment, _long_issuance = _issue_role_assignment(
        representation=representation,
        appointments=appointments,
        principal=principal,
        code="long-role-source",
        expires_at=now + timedelta(days=3),
    )
    short_assignment, short_issuance = _issue_role_assignment(
        representation=representation,
        appointments=appointments,
        principal=principal,
        code="first-short-role-source",
        expires_at=now + timedelta(days=1),
    )
    _later_short_assignment, _later_short_issuance = _issue_role_assignment(
        representation=representation,
        appointments=appointments,
        principal=principal,
        code="second-short-role-source",
        expires_at=now + timedelta(days=1),
    )
    target = _required_target(
        resolve_organization_target(organization_id=representation.organization_id)
    )

    selected = _select(
        principal=principal,
        capability_code="events.view_basic",
        target=target,
        requested_expires_at=now + timedelta(hours=12),
        evaluated_at=timezone.now(),
    )

    assert selected is not None
    assert selected.source_kind is PersistentSourceKind.ROLE_ASSIGNMENT
    assert selected.source_authority_id == short_assignment.id
    assert selected.source_issuance_ordinal == short_issuance.ordinal


def test_delegated_source_recurses_and_does_not_rebind_after_parent_revocation() -> (
    None
):
    _administrator, representation, appointments = _activate_board()
    delegator = AccountFactory()
    delegate = AccountFactory()
    root, root_issuance = _issue_grant(
        representation=representation,
        appointments=appointments,
        principal=delegator,
        capability_code="events.view_basic",
    )
    evaluated_at = timezone.now()
    delegated = CapabilityGrant.objects.create(
        organization=representation.organization,
        principal=delegate,
        capability_code=root.capability_code,
        effective_from=evaluated_at,
        granted_by=delegator,
        delegated_from=root,
        reason="Create a synthetic delegated lineage.",
    )
    delegated_issuance = create_delegated_grant_issuance(
        grant=delegated,
        evaluated_at=evaluated_at,
    )
    target = _required_target(
        resolve_organization_target(organization_id=representation.organization_id)
    )
    assert authority_issuance_is_current(
        issuance_ordinal=root_issuance.ordinal,
        principal_id=delegator.id,
        capability_code=root.capability_code,
        target=target,
        requested_effective_from=delegated.effective_from,
        requested_expires_at=delegated.expires_at,
        evaluated_at=evaluated_at,
    )
    selected = _select(
        principal=delegate,
        capability_code=root.capability_code,
        target=target,
        evaluated_at=evaluated_at,
    )
    assert selected is not None
    assert selected.source_issuance_ordinal == delegated_issuance.ordinal

    root.revoked_at = evaluated_at + timedelta(seconds=1)
    root.revoked_by = appointments[0].account
    root.revocation_reason = "Revoke the synthetic parent source."
    root.save(update_fields=("revoked_at", "revoked_by", "revocation_reason"))

    assert not authorized_control_is_current(
        control=selected,
        target=target,
        requested_effective_from=evaluated_at,
        requested_expires_at=None,
        evaluated_at=evaluated_at + timedelta(seconds=2),
    )
    assert not authority_issuance_is_current(
        issuance_ordinal=root_issuance.ordinal,
        principal_id=delegator.id,
        capability_code=root.capability_code,
        target=target,
        requested_effective_from=delegated.effective_from,
        requested_expires_at=delegated.expires_at,
        evaluated_at=evaluated_at + timedelta(seconds=2),
    )
    assert (
        _select(
            principal=delegate,
            capability_code=root.capability_code,
            target=target,
            evaluated_at=evaluated_at + timedelta(seconds=2),
        )
        is None
    )


def test_revalidation_is_pinned_and_board_current_state_fails_closed() -> None:
    _administrator, representation, appointments = _activate_board()
    controller = appointments[0].account
    target = _required_target(
        resolve_organization_target(organization_id=representation.organization_id)
    )
    evaluated_at = timezone.now()
    selected = _select(
        principal=controller,
        capability_code="authorization.manage_roles",
        target=target,
        evaluated_at=evaluated_at,
    )
    assert selected is not None

    assert not authorized_control_is_current(
        control=replace(selected, source_authority_id=uuid4()),
        target=target,
        requested_expires_at=None,
        evaluated_at=evaluated_at,
    )
    with transaction.atomic():
        Account.objects.filter(pk=controller.id).update(is_active=False)
        assert not authorized_control_is_current(
            control=selected,
            target=target,
            requested_expires_at=None,
            evaluated_at=evaluated_at,
        )
        transaction.set_rollback(True)


def test_selector_rejects_foreign_scope_and_invalid_window() -> None:
    _administrator, representation, appointments = _activate_board()
    controller = appointments[0].account
    foreign = OrganizationFactory()
    foreign_target = _required_target(
        resolve_organization_target(organization_id=foreign.id)
    )
    now = timezone.now()

    assert (
        _select(
            principal=controller,
            capability_code="authorization.grant_direct",
            target=foreign_target,
            evaluated_at=now,
        )
        is None
    )
    own_target = _required_target(
        resolve_organization_target(organization_id=representation.organization_id)
    )
    with transaction.atomic():
        assert (
            select_authorized_control_source(
                principal=controller,
                role=AuthorityControl.Role.ACTOR,
                capability_code="authorization.grant_direct",
                target=own_target,
                requested_effective_from=now,
                requested_expires_at=now,
                evaluated_at=now,
            )
            is None
        )


def test_public_provenance_boundaries_fail_closed_on_invalid_inputs() -> None:
    _administrator, representation, appointments = _activate_board()
    target = _required_target(
        resolve_organization_target(organization_id=representation.organization_id)
    )
    principal = AccountFactory()
    _grant, issuance = _issue_grant(
        representation=representation,
        appointments=appointments,
        principal=principal,
        capability_code="events.view_basic",
    )
    unsaved_bundle = RoleBundle(
        organization=representation.organization,
        code="unsaved-provenance-boundary",
        name="Unsaved provenance boundary",
        version=1,
        capability_codes=["events.view_basic"],
        created_by=appointments[0].account,
        approved_by=appointments[1].account,
    )

    assert not role_bundle_provenance_is_historical(bundle=unsaved_bundle)
    assert not role_bundle_provenance_is_historical(
        bundle=RoleBundle.objects.get(code="executive-board"),
        evaluated_at=datetime.now(),  # noqa: DTZ005 - invalid naive input.
    )
    assert not authority_issuance_is_current(
        issuance_ordinal=0,
        principal_id=principal.id,
        capability_code="events.view_basic",
        target=target,
        requested_effective_from=timezone.now(),
        requested_expires_at=None,
    )
    assert not authority_issuance_is_current(
        issuance_ordinal=issuance.ordinal,
        principal_id=principal.id,
        capability_code="",
        target=target,
        requested_effective_from=timezone.now(),
        requested_expires_at=None,
    )
    assert not authority_issuance_is_current(
        issuance_ordinal=issuance.ordinal,
        principal_id=principal.id,
        capability_code="events.view_basic",
        target=target,
        requested_effective_from=datetime.now(),  # noqa: DTZ005
        requested_expires_at=None,
    )

    with transaction.atomic():
        with pytest.raises(ValueError, match="actor or approver"):
            select_authorized_control_source(
                principal=principal,
                role="observer",
                capability_code="events.view_basic",
                target=target,
                requested_expires_at=None,
            )
        assert (
            select_authorized_control_source(
                principal=principal,
                role=AuthorityControl.Role.ACTOR,
                capability_code="",
                target=target,
                requested_expires_at=None,
            )
            is None
        )
        inactive = AccountFactory(is_active=False)
        assert (
            select_authorized_control_source(
                principal=inactive,
                role=AuthorityControl.Role.ACTOR,
                capability_code="events.view_basic",
                target=target,
                requested_expires_at=None,
            )
            is None
        )

    selected = _select(
        principal=principal,
        capability_code="events.view_basic",
        target=target,
    )
    assert selected is not None
    assert not authorized_control_is_current(
        control=replace(selected, role="observer"),
        target=target,
        requested_expires_at=None,
    )
    assert not authorized_control_is_current(
        control=replace(selected, source_issuance_ordinal=2**63 - 1),
        target=target,
        requested_expires_at=None,
    )


def test_cycle_and_depth_guards_fail_closed_without_rebinding() -> None:
    _administrator, representation, appointments = _activate_board()
    controller = appointments[0].account
    target = _required_target(
        resolve_organization_target(organization_id=representation.organization_id)
    )
    scope = provenance._scope_from_target(target)
    assert scope is not None
    evaluated_at = timezone.now()
    issuance = _board_source(appointments[0])
    expectation = provenance._Expectation(
        principal_id=controller.id,
        capability_code="authorization.manage_roles",
        target_scope=scope,
        requested_effective_from=evaluated_at,
        requested_expires_at=None,
        evaluated_at=evaluated_at,
    )

    assert not provenance._validate_issuance_current(
        context=provenance._LineageContext(lock=False),
        ordinal=issuance.ordinal,
        expectation=expectation,
        path=frozenset({issuance.ordinal}),
    )
    assert not provenance._validate_issuance_current(
        context=provenance._LineageContext(lock=False),
        ordinal=issuance.ordinal,
        expectation=expectation,
        depth=provenance.MAX_AUTHORITY_LINEAGE_DEPTH,
    )


def test_historical_bundle_validation_rejects_malformed_deep_lineage() -> None:
    _administrator, representation, appointments = _activate_board()
    evaluated_at = timezone.now()
    bundle = RoleBundle.objects.create(
        organization=representation.organization,
        code="deep-lineage-role",
        name="Deep lineage role",
        version=1,
        capability_codes=["events.view_basic"],
        created_by=appointments[0].account,
        approved_by=appointments[1].account,
        reason="Exercise recursive historical provenance.",
    )
    create_persistent_dual_control_issuance(
        target=bundle,
        actor_source=_board_source(appointments[0]),
        approver_source=_board_source(appointments[1]),
        evaluated_at=evaluated_at,
    )
    context = provenance._LineageContext(lock=False)
    malformed_ancestor = _board_source(appointments[0])
    context.controls[malformed_ancestor.ordinal] = ()

    assert not provenance._bundle_ceremony_is_historical(
        context=context,
        bundle=bundle,
        evaluated_at=evaluated_at,
    )
