"""Integration evidence for provable-only ADR 0044 reconciliation."""

from __future__ import annotations

import json
import traceback
from datetime import timedelta
from io import StringIO
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone

from maru.authorization import provenance_backfill
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.issuance import (
    create_executive_board_issuance,
    create_persistent_dual_control_issuance,
)
from maru.authorization.models import (
    AuthorityControl,
    AuthorityIssuance,
    CapabilityGrant,
    RoleBundle,
)
from maru.identity.models import Account
from maru.organizations.models import (
    Organization,
    OrganizationRepresentation,
    RepresentationAppointment,
)
from maru.organizations.representation import (
    EXECUTIVE_BOARD_ROLE_CODE,
    activate_executive_board,
    emergency_remove_executive_board_controller,
    invite_representation_controller,
    provision_executive_board,
    respond_to_representation_invitation,
)
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    OrganizationFactory,
    RoleAssignmentFactory,
    RoleBundleFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _read_report(*arguments: str) -> dict[str, object]:
    output = StringIO()
    call_command(
        "backfill_provable_authority_provenance",
        *arguments,
        stdout=output,
    )
    return json.loads(output.getvalue())


def _accepted_board(
    *,
    controller_count: int = 2,
) -> tuple[Account, OrganizationRepresentation]:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    representation = provision_executive_board(
        actor=administrator,
        organization_id=organization.id,
        reason="Provision synthetic reconciliation evidence.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    for _index in range(controller_count):
        controller = AccountFactory()
        appointment = invite_representation_controller(
            actor=administrator,
            representation_id=representation.id,
            account_id=controller.id,
            reason="Invite a synthetic reconciliation controller.",
            correlation_id=uuid4(),
            source_channel="test",
        )
        respond_to_representation_invitation(
            actor=controller,
            appointment_id=appointment.id,
            expected_version=appointment.invitation_version,
            accept=True,
            correlation_id=uuid4(),
            source_channel="test",
        )
    representation.refresh_from_db()
    return administrator, representation


def _activate_board_without_provenance(
    monkeypatch: pytest.MonkeyPatch,
    *,
    controller_count: int = 2,
) -> tuple[OrganizationRepresentation, RoleBundle, list[RepresentationAppointment]]:
    administrator, representation = _accepted_board(controller_count=controller_count)
    monkeypatch.setattr(
        "maru.organizations.representation.create_executive_board_issuance",
        lambda **_kwargs: None,
    )
    result = activate_executive_board(
        actor=administrator,
        representation_id=representation.id,
        expected_version=representation.aggregate_version,
        reason="Activate synthetic reconciliation evidence.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    active = list(
        RepresentationAppointment.objects.filter(representation=result.representation)
        .select_related("account", "role_assignment")
        .order_by("responded_at", "id")
    )
    bundle = RoleBundle.objects.get(
        organization=result.organization,
        code=EXECUTIVE_BOARD_ROLE_CODE,
    )
    return result.representation, bundle, active


def _activate_board_with_provenance() -> tuple[
    OrganizationRepresentation,
    RoleBundle,
    list[RepresentationAppointment],
]:
    administrator, representation = _accepted_board()
    result = activate_executive_board(
        actor=administrator,
        representation_id=representation.id,
        expected_version=representation.aggregate_version,
        reason="Activate exact synthetic authority.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    active = list(
        RepresentationAppointment.objects.filter(representation=result.representation)
        .select_related("account", "role_assignment")
        .order_by("responded_at", "id")
    )
    bundle = RoleBundle.objects.get(
        organization=result.organization,
        code=EXECUTIVE_BOARD_ROLE_CODE,
    )
    return result.representation, bundle, active


def test_default_is_a_read_only_count_only_dry_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _representation, _bundle, appointments = _activate_board_without_provenance(
        monkeypatch
    )

    report = _read_report()

    assert report == {
        "applied_counts": {
            "delegated_grant": 0,
            "executive_board_assignment": 0,
            "executive_board_bundle": 0,
        },
        "blocker_counts": {
            "delegated_chain_unresolvable": 0,
            "delegated_parent_issuance_missing": 0,
            "delegated_relationship_mismatch": 0,
            "invalid_executive_board_ceremony": 0,
            "invalid_existing_issuance": 0,
        },
        "blocker_total": 0,
        "mode": "dry_run",
        "planned_counts": {
            "delegated_grant": 0,
            "executive_board_assignment": len(appointments),
            "executive_board_bundle": 1,
        },
        "preserved_counts": {
            "delegated_grant": 0,
            "executive_board_assignment": 0,
            "executive_board_bundle": 0,
        },
        "review_counts": {
            "expired_or_revoked_delegated_grant_untouched": 0,
            "ordinary_role_assignment_untouched": 0,
            "ordinary_role_bundle_untouched": 0,
            "ordinary_root_grant_untouched": 0,
        },
        "schema_version": 1,
        "status": "ready",
    }
    assert not AuthorityIssuance.objects.exists()
    assert not AuthorityControl.objects.exists()


def test_normal_provisioning_representation_without_bundle_is_not_a_blocker() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    provision_executive_board(
        actor=administrator,
        organization_id=organization.id,
        reason="Provision an unfinished synthetic Board.",
        correlation_id=uuid4(),
        source_channel="test",
    )

    report = _read_report()

    assert report["status"] == "ready"
    assert report["blocker_total"] == 0
    assert report["planned_counts"] == {
        "delegated_grant": 0,
        "executive_board_assignment": 0,
        "executive_board_bundle": 0,
    }


def test_apply_requires_explicit_stopped_writer_acknowledgement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _activate_board_without_provenance(monkeypatch)

    with pytest.raises(CommandError, match="acknowledge-writers-stopped") as captured:
        _read_report("--apply")

    assert captured.value.__cause__ is None
    assert captured.value.__suppress_context__ is True
    assert not AuthorityIssuance.objects.exists()
    assert not AuthorityControl.objects.exists()


def test_apply_backfills_active_board_and_rerun_preserves_exact_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    representation, bundle, appointments = _activate_board_without_provenance(
        monkeypatch,
        controller_count=3,
    )

    applied = _read_report("--apply", "--acknowledge-writers-stopped")

    assert applied["status"] == "ready"
    assert applied["applied_counts"] == {
        "delegated_grant": 0,
        "executive_board_assignment": len(appointments),
        "executive_board_bundle": 1,
    }
    assert AuthorityIssuance.objects.filter(role_bundle=bundle).exists()
    for appointment in appointments:
        issuance = AuthorityIssuance.objects.get(
            role_assignment=appointment.role_assignment_id
        )
        controls = {
            control.role: control
            for control in AuthorityControl.objects.filter(issuance=issuance)
        }
        assert controls[AuthorityControl.Role.ACTOR].representation == representation
        assert (
            controls[AuthorityControl.Role.APPROVER].appointment.account_id
            == issuance.role_assignment.approved_by_id
        )

    issuance_count = AuthorityIssuance.objects.count()
    control_count = AuthorityControl.objects.count()
    repeated = _read_report("--apply", "--acknowledge-writers-stopped")
    assert repeated["planned_counts"] == {
        "delegated_grant": 0,
        "executive_board_assignment": 0,
        "executive_board_bundle": 0,
    }
    assert repeated["preserved_counts"] == {
        "delegated_grant": 0,
        "executive_board_assignment": len(appointments),
        "executive_board_bundle": 1,
    }
    assert AuthorityIssuance.objects.count() == issuance_count
    assert AuthorityControl.objects.count() == control_count


def test_delegated_chain_is_backfilled_parent_first() -> None:
    representation, _bundle, appointments = _activate_board_with_provenance()
    actor = appointments[0].account
    approver = appointments[1].account
    recipient = AccountFactory()
    evaluated_at = timezone.now()
    with transaction.atomic():
        root = CapabilityGrant.objects.create(
            organization=representation.organization,
            principal=recipient,
            capability_code="events.view_basic",
            effective_from=evaluated_at,
            granted_by=actor,
            approved_by=approver,
            reason="Create a synthetic proven delegation root.",
        )
        root_issuance = create_persistent_dual_control_issuance(
            target=root,
            actor_source=AuthorityIssuance.objects.get(
                role_assignment=appointments[0].role_assignment_id
            ),
            approver_source=AuthorityIssuance.objects.get(
                role_assignment=appointments[1].role_assignment_id
            ),
            evaluated_at=evaluated_at,
        )
        child = CapabilityGrant.objects.create(
            organization=representation.organization,
            principal=AccountFactory(),
            capability_code=root.capability_code,
            effective_from=evaluated_at,
            granted_by=recipient,
            delegated_from=root,
            reason="Create a synthetic first delegation.",
        )
        grandchild = CapabilityGrant.objects.create(
            organization=representation.organization,
            principal=AccountFactory(),
            capability_code=root.capability_code,
            effective_from=evaluated_at,
            granted_by=child.principal,
            delegated_from=child,
            reason="Create a synthetic second delegation.",
        )

    report = _read_report("--apply", "--acknowledge-writers-stopped")

    child_issuance = AuthorityIssuance.objects.get(capability_grant=child)
    grandchild_issuance = AuthorityIssuance.objects.get(capability_grant=grandchild)
    assert report["applied_counts"]["delegated_grant"] == 2
    assert root_issuance.ordinal < child_issuance.ordinal < grandchild_issuance.ordinal
    assert not AuthorityControl.objects.filter(
        issuance__in=(child_issuance, grandchild_issuance)
    ).exists()


def test_closed_delegations_are_review_debt_while_future_gap_blocks() -> None:
    at = timezone.now()
    organization = OrganizationFactory()
    delegator = AccountFactory()
    parent = CapabilityGrant.objects.create(
        organization=organization,
        principal=delegator,
        capability_code="events.view_basic",
        effective_from=at - timedelta(days=10),
        granted_by=AccountFactory(),
        reason="Create an unproven synthetic legacy root.",
    )
    CapabilityGrant.objects.create(
        organization=organization,
        principal=AccountFactory(),
        capability_code=parent.capability_code,
        effective_from=at - timedelta(days=9),
        expires_at=at - timedelta(days=8),
        granted_by=delegator,
        delegated_from=parent,
        reason="Create an expired synthetic legacy delegation.",
    )
    CapabilityGrant.objects.create(
        organization=organization,
        principal=AccountFactory(),
        capability_code=parent.capability_code,
        effective_from=at - timedelta(days=7),
        revoked_at=at - timedelta(days=6),
        revoked_by=delegator,
        revocation_reason="Revoke the synthetic legacy delegation.",
        granted_by=delegator,
        delegated_from=parent,
        reason="Create a revoked synthetic legacy delegation.",
    )
    CapabilityGrant.objects.create(
        organization=organization,
        principal=AccountFactory(),
        capability_code=parent.capability_code,
        effective_from=at + timedelta(days=1),
        granted_by=delegator,
        delegated_from=parent,
        reason="Create a future synthetic legacy delegation.",
    )

    report = _read_report("--no-fail")

    assert report["review_counts"]["expired_or_revoked_delegated_grant_untouched"] == 2
    assert report["blocker_counts"]["delegated_parent_issuance_missing"] == 1
    assert report["planned_counts"]["delegated_grant"] == 0
    assert not AuthorityIssuance.objects.filter(
        capability_grant__delegated_from=parent
    ).exists()


def test_orphan_board_and_malformed_delegation_report_stable_blockers() -> None:
    organization = OrganizationFactory()
    RoleBundleFactory(
        organization=organization,
        code=EXECUTIVE_BOARD_ROLE_CODE,
    )
    delegator = AccountFactory()
    parent = CapabilityGrant.objects.create(
        organization=organization,
        principal=delegator,
        capability_code="events.view_basic",
        effective_from=timezone.now(),
        granted_by=AccountFactory(),
        reason="Create a synthetic malformed-delegation parent.",
    )
    CapabilityGrant.objects.create(
        organization=organization,
        principal=AccountFactory(),
        capability_code=parent.capability_code,
        effective_from=parent.effective_from,
        granted_by=delegator,
        approved_by=AccountFactory(),
        delegated_from=parent,
        reason="Create malformed synthetic delegated attribution.",
    )

    report = _read_report("--no-fail")

    assert report["blocker_total"] == 2
    assert report["blocker_counts"] == {
        "delegated_chain_unresolvable": 0,
        "delegated_parent_issuance_missing": 0,
        "delegated_relationship_mismatch": 1,
        "invalid_executive_board_ceremony": 1,
        "invalid_existing_issuance": 0,
    }
    assert report["planned_counts"] == {
        "delegated_grant": 0,
        "executive_board_assignment": 0,
        "executive_board_bundle": 0,
    }


def test_ordinary_legacy_authority_is_counted_and_never_inferred() -> None:
    organization = OrganizationFactory()
    root = CapabilityGrantFactory(organization=organization)
    bundle = RoleBundleFactory(organization=organization)
    assignment = RoleAssignmentFactory(
        organization=organization,
        role_bundle=bundle,
    )

    report = _read_report("--apply", "--acknowledge-writers-stopped")

    assert report["review_counts"] == {
        "expired_or_revoked_delegated_grant_untouched": 0,
        "ordinary_role_assignment_untouched": 1,
        "ordinary_role_bundle_untouched": 1,
        "ordinary_root_grant_untouched": 1,
    }
    assert not AuthorityIssuance.objects.filter(capability_grant=root).exists()
    assert not AuthorityIssuance.objects.filter(role_bundle=bundle).exists()
    assert not AuthorityIssuance.objects.filter(role_assignment=assignment).exists()


def test_partial_existing_ledger_blocks_apply_without_appending_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _representation, bundle, _appointments = _activate_board_without_provenance(
        monkeypatch
    )
    partial = AuthorityIssuance.objects.create(
        role_bundle=bundle,
        policy_version=POLICY_VERSION,
        evaluated_at=bundle.organization.representation.activated_at,
    )

    output = StringIO()
    with pytest.raises(CommandError, match="blocked"):
        call_command(
            "backfill_provable_authority_provenance",
            "--apply",
            "--acknowledge-writers-stopped",
            stdout=output,
        )

    report = json.loads(output.getvalue())
    assert report["blocker_counts"]["invalid_existing_issuance"] == 1
    assert list(AuthorityIssuance.objects.values_list("ordinal", flat=True)) == [
        partial.ordinal
    ]
    assert not AuthorityControl.objects.exists()


def test_assignment_issuance_cannot_precede_or_outlive_bundle_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    representation, bundle, appointments = _activate_board_without_provenance(
        monkeypatch
    )
    assignment = appointments[0].role_assignment
    assert assignment is not None
    approver_appointment = next(
        appointment
        for appointment in appointments
        if appointment.account_id == assignment.approved_by_id
    )
    assert representation.activated_at is not None
    create_executive_board_issuance(
        target=assignment,
        representation=representation,
        actor=Account.objects.get(pk=representation.activated_by_id),
        approver_appointment=approver_appointment,
        evaluated_at=representation.activated_at,
    )

    output = StringIO()
    with pytest.raises(CommandError, match="blocked"):
        call_command(
            "backfill_provable_authority_provenance",
            "--apply",
            "--acknowledge-writers-stopped",
            stdout=output,
        )

    report = json.loads(output.getvalue())
    assert report["blocker_counts"]["invalid_existing_issuance"] == 1
    assert not AuthorityIssuance.objects.filter(role_bundle=bundle).exists()
    assert AuthorityIssuance.objects.count() == 1


def test_plausible_but_wrong_board_appointment_is_never_preserved() -> None:
    _representation, bundle, _appointments = _activate_board_with_provenance()
    state = provenance_backfill._load_state(lock=False)
    bundle_ordinal = state.issuance_by_bundle[bundle.id]
    approver_control = next(
        control
        for control in state.controls_by_issuance[bundle_ordinal]
        if control["role"] == AuthorityControl.Role.APPROVER
    )
    exact_appointment = state.appointments[approver_control["appointment_id"]]
    plausible_appointment = dict(exact_appointment)
    plausible_appointment["id"] = uuid4()
    plausible_appointment["role_assignment_id"] = None
    state.appointments[plausible_appointment["id"]] = plausible_appointment
    approver_control["appointment_id"] = plausible_appointment["id"]

    plan = provenance_backfill._build_plan(
        state=state,
        mode="dry_run",
        at=timezone.now(),
    )
    report = plan.report

    assert report["blocker_counts"]["invalid_existing_issuance"] == 1
    assert report["preserved_counts"]["executive_board_bundle"] == 0
    assert report["planned_counts"] == {
        "delegated_grant": 0,
        "executive_board_assignment": 0,
        "executive_board_bundle": 0,
    }


@pytest.mark.parametrize(
    "tamper",
    [
        "bundle_profile",
        "controller_quorum",
        "assignment_set",
        "bundle_approver",
        "assignment_attribution",
        "active_term_end",
        "ended_term_mismatch",
    ],
)
def test_board_snapshot_tampering_never_yields_a_backfill_plan(tamper: str) -> None:
    _representation, bundle, _appointments = _activate_board_with_provenance()
    state = provenance_backfill._load_state(lock=False)
    bundle_row = state.bundles[bundle.id]
    appointment_rows = sorted(
        (
            appointment
            for appointment in state.appointments.values()
            if appointment["representation_id"] == bundle.organization.representation.id
            and appointment["role_assignment_id"] is not None
        ),
        key=lambda appointment: (
            appointment["responded_at"],
            str(appointment["id"]),
        ),
    )
    appointment = appointment_rows[0]
    assignment_id = appointment["role_assignment_id"]
    assignment = state.assignments[assignment_id]

    if tamper == "bundle_profile":
        bundle_row["name"] = "Tampered Board"
    elif tamper == "controller_quorum":
        appointment["role_assignment_id"] = None
    elif tamper == "assignment_set":
        state.assignments.pop(assignment_id)
    elif tamper == "bundle_approver":
        bundle_row["approved_by_id"] = uuid4()
    elif tamper == "assignment_attribution":
        assignment["reason"] = "Tampered activation reason"
    elif tamper == "active_term_end":
        appointment["ended_at"] = timezone.now()
    else:
        appointment["state"] = RepresentationAppointment.State.ENDED
        appointment["ended_at"] = timezone.now()
        assignment["revoked_at"] = None

    plan = provenance_backfill._build_plan(
        state=state,
        mode="dry_run",
        at=timezone.now(),
    )

    assert plan.report["blocker_counts"]["invalid_executive_board_ceremony"] == 1
    assert plan.board_writes == ()
    assert plan.report["planned_counts"] == {
        "delegated_grant": 0,
        "executive_board_assignment": 0,
        "executive_board_bundle": 0,
    }


def test_invalid_board_root_transitively_invalidates_assignment_issuances() -> None:
    _representation, bundle, appointments = _activate_board_with_provenance()
    state = provenance_backfill._load_state(lock=False)
    bundle_ordinal = state.issuance_by_bundle[bundle.id]
    actor_control = next(
        control
        for control in state.controls_by_issuance[bundle_ordinal]
        if control["role"] == AuthorityControl.Role.ACTOR
    )
    actor_control["representation_id"] = uuid4()

    plan = provenance_backfill._build_plan(
        state=state,
        mode="dry_run",
        at=timezone.now(),
    )

    assert plan.report["blocker_counts"]["invalid_existing_issuance"] == (
        len(appointments) + 1
    )
    assert plan.report["preserved_counts"] == {
        "delegated_grant": 0,
        "executive_board_assignment": 0,
        "executive_board_bundle": 0,
    }


def test_cyclic_delegation_snapshot_reports_unresolvable_chain() -> None:
    organization = OrganizationFactory()
    delegator = AccountFactory()
    parent = CapabilityGrant.objects.create(
        organization=organization,
        principal=delegator,
        capability_code="events.view_basic",
        effective_from=timezone.now(),
        granted_by=AccountFactory(),
        reason="Create a synthetic cycle parent.",
    )
    first = CapabilityGrant.objects.create(
        organization=organization,
        principal=AccountFactory(),
        capability_code=parent.capability_code,
        effective_from=parent.effective_from,
        granted_by=delegator,
        delegated_from=parent,
        reason="Create a first synthetic delegation.",
    )
    second = CapabilityGrant.objects.create(
        organization=organization,
        principal=AccountFactory(),
        capability_code=parent.capability_code,
        effective_from=parent.effective_from,
        granted_by=delegator,
        delegated_from=parent,
        reason="Create a second synthetic delegation.",
    )
    state = provenance_backfill._load_state(lock=False)
    state.grants[first.id]["delegated_from_id"] = second.id
    state.grants[first.id]["granted_by_id"] = second.principal_id
    state.grants[second.id]["delegated_from_id"] = first.id
    state.grants[second.id]["granted_by_id"] = first.principal_id

    plan = provenance_backfill._build_plan(
        state=state,
        mode="dry_run",
        at=timezone.now(),
    )

    assert plan.report["blocker_counts"]["delegated_chain_unresolvable"] == 2
    assert plan.report["blocker_counts"]["delegated_parent_issuance_missing"] == 0
    assert plan.delegated_writes == ()


def test_historical_suspended_board_and_inactive_activator_remain_provable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    representation, bundle, appointments = _activate_board_without_provenance(
        monkeypatch
    )
    administrator = Account.objects.get(pk=representation.activated_by_id)
    removal = emergency_remove_executive_board_controller(
        actor=administrator,
        representation_id=representation.id,
        appointment_id=appointments[0].id,
        expected_version=representation.aggregate_version,
        reason="Contain synthetic controller authority.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    administrator.is_active = False
    administrator.save(update_fields=("is_active",))
    representation.refresh_from_db()
    assert removal.quorum_preserved is False
    assert representation.state == OrganizationRepresentation.State.SUSPENDED
    assert all(
        appointment.state == RepresentationAppointment.State.ENDED
        for appointment in RepresentationAppointment.objects.filter(
            representation=representation
        )
        if appointment.role_assignment_id is not None
    )

    report = _read_report("--apply", "--acknowledge-writers-stopped")

    assert report["blocker_total"] == 0
    assert report["applied_counts"] == {
        "delegated_grant": 0,
        "executive_board_assignment": len(appointments),
        "executive_board_bundle": 1,
    }
    assert AuthorityIssuance.objects.filter(role_bundle=bundle).exists()


def test_unexpected_failure_rolls_back_the_whole_apply_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _activate_board_without_provenance(monkeypatch, controller_count=3)
    calls = 0
    create_control = AuthorityControl.objects.create

    def fail_during_second_issuance(**kwargs: object) -> AuthorityControl:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("synthetic private failure context")
        return create_control(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        AuthorityControl.objects,
        "create",
        fail_during_second_issuance,
    )
    with pytest.raises(CommandError, match="transaction was rolled back") as captured:
        _read_report("--apply", "--acknowledge-writers-stopped")

    assert "synthetic private failure context" not in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__suppress_context__ is True
    rendered_traceback = "".join(traceback.format_exception(captured.value))
    assert "synthetic private failure context" not in rendered_traceback
    assert not AuthorityIssuance.objects.exists()
    assert not AuthorityControl.objects.exists()


def test_post_apply_verification_tamper_rolls_back_and_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _activate_board_without_provenance(monkeypatch)
    build_plan = provenance_backfill._build_plan
    calls = 0

    def tamper_verification(**kwargs: object) -> object:
        nonlocal calls
        calls += 1
        plan = build_plan(**kwargs)  # type: ignore[arg-type]
        if calls == 2:
            plan.report["status"] = "blocked"
        return plan

    monkeypatch.setattr(provenance_backfill, "_build_plan", tamper_verification)
    with pytest.raises(CommandError, match="transaction was rolled back") as captured:
        _read_report("--apply", "--acknowledge-writers-stopped")

    assert calls == 2
    assert captured.value.__cause__ is None
    assert captured.value.__suppress_context__ is True
    assert not AuthorityIssuance.objects.exists()
    assert not AuthorityControl.objects.exists()


def test_report_and_errors_disclose_no_record_values() -> None:
    secret_email = "private-controller-marker@example.invalid"
    secret_reason = "private-reason-marker"
    secret_slug = "private-organization-marker"
    account = AccountFactory(email=secret_email)
    organization = OrganizationFactory(slug=secret_slug)
    grant = CapabilityGrantFactory(
        organization=organization,
        principal=account,
        capability_code="organizations.view_basic",
        reason=secret_reason,
    )
    AuthorityIssuance.objects.create(
        capability_grant=grant,
        policy_version=POLICY_VERSION,
        evaluated_at=timezone.now(),
    )
    output = StringIO()
    with pytest.raises(CommandError) as captured:
        call_command(
            "backfill_provable_authority_provenance",
            stdout=output,
        )

    rendered = output.getvalue() + str(captured.value)
    for private_value in (
        secret_email,
        secret_reason,
        secret_slug,
        str(account.id),
        str(organization.id),
        str(grant.id),
        grant.capability_code,
    ):
        assert private_value not in rendered
