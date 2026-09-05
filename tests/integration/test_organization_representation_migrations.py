from __future__ import annotations

from importlib import import_module
from uuid import uuid4

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from maru.authorization.models import CapabilityGrant
from maru.identity.models import Account
from maru.organizations.models import (
    Organization,
    OrganizationMembership,
)
from maru.organizations.representation import (
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
)
from tests.support.migrations import restore_current_migration_graph

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("restores_current_migration_graph"),
]

ORGANIZATIONS_AFTER_HARDENING = (
    "organizations",
    "0011_emergency_controller_removal_integrity",
)


def _restore_current_graph() -> MigrationExecutor:
    """Restore all leaves before current-model assertions or test handoff."""

    return restore_current_migration_graph()


def test_emergency_integrity_downgrade_fence_rejects_surviving_evidence() -> None:
    _restore_current_graph()
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    representation = provision_executive_board(
        actor=administrator,
        organization_id=organization.id,
        reason="Establish synthetic governance before the downgrade exercise.",
        correlation_id=uuid4(),
    )
    controllers = [AccountFactory(), AccountFactory()]
    appointments = []
    for controller in controllers:
        appointment = invite_representation_controller(
            actor=administrator,
            representation_id=representation.id,
            account_id=controller.id,
            reason="Invite a synthetic controller for downgrade-fence coverage.",
            correlation_id=uuid4(),
        )
        respond_to_representation_invitation(
            actor=controller,
            appointment_id=appointment.id,
            expected_version=appointment.invitation_version,
            accept=True,
            correlation_id=uuid4(),
        )
        appointments.append(appointment)
    representation.refresh_from_db()
    activation = activate_executive_board(
        actor=administrator,
        representation_id=representation.id,
        expected_version=representation.aggregate_version,
        reason="Activate synthetic governance for downgrade-fence coverage.",
        correlation_id=uuid4(),
    )
    emergency_remove_executive_board_controller(
        actor=administrator,
        representation_id=activation.representation.id,
        appointment_id=appointments[0].id,
        expected_version=activation.representation.aggregate_version,
        reason="Synthetic platform emergency used only to verify the fence.",
        correlation_id=uuid4(),
    )

    try:
        migration = import_module(
            "maru.organizations.migrations.0011_emergency_controller_removal_integrity"
        )
        historical_apps = (
            MigrationExecutor(connection)
            .loader.project_state([ORGANIZATIONS_AFTER_HARDENING])
            .apps
        )
        # The later authority-provenance migration has its own non-empty
        # downgrade fence and is reversed first by a whole-graph plan. Exercise
        # this migration's independent reverse preflight directly.
        with (
            pytest.raises(
                RuntimeError,
                match="Cannot reverse emergency Executive Board integrity",
            ),
            connection.schema_editor() as schema_editor,
        ):
            migration.refuse_emergency_governance_downgrade(
                historical_apps,
                schema_editor,
            )
    finally:
        _restore_current_graph()


def test_fix_forward_rejects_raw_platform_capability_grants() -> None:
    _restore_current_graph()
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)

    with (
        transaction.atomic(),
        pytest.raises(
            IntegrityError,
            match="platform accounts cannot receive convention capability grants",
        ),
    ):
        CapabilityGrant.objects.bulk_create(
            [
                CapabilityGrant(
                    organization=organization,
                    principal=administrator,
                    capability_code="events.view_basic",
                    effective_from=timezone.now(),
                    granted_by=administrator,
                    reason="Forbidden raw platform authority.",
                )
            ]
        )


@pytest.mark.parametrize("authority_kind", ["grant", "assignment"])
def test_fix_forward_blocks_reclassification_while_authority_remains(
    authority_kind: str,
) -> None:
    _restore_current_graph()
    person = AccountFactory()
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    if authority_kind == "grant":
        CapabilityGrantFactory(
            organization=organization,
            principal=person,
            capability_code="events.view_basic",
        )
    else:
        RoleAssignmentFactory(
            principal=person,
            edition=None,
        )

    def reclassify_with_authority() -> None:
        with transaction.atomic():
            Account.objects.filter(pk=person.pk).update(
                account_kind=Account.Kind.PLATFORM_ADMINISTRATOR,
                is_staff=True,
                is_superuser=True,
            )
            with connection.cursor() as cursor:
                cursor.execute(
                    "SET CONSTRAINTS identity_platform_authority_principal_guard "
                    "IMMEDIATE"
                )

    with pytest.raises(
        IntegrityError,
        match="platform account cannot retain convention authority",
    ):
        reclassify_with_authority()

    person.refresh_from_db()
    assert person.account_kind == Account.Kind.PERSON


@pytest.mark.parametrize(
    "membership_changes",
    [
        {"relationship_label": "Unrelated relationship"},
        {"started_at": None},
        {"ended_at": "now"},
    ],
)
def test_fix_forward_freezes_active_board_membership_provenance(
    membership_changes: dict[str, object],
) -> None:
    _restore_current_graph()
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    representation = provision_executive_board(
        actor=administrator,
        organization_id=organization.id,
        reason="Establish synthetic governance.",
        correlation_id=uuid4(),
    )
    controllers = [AccountFactory(), AccountFactory()]
    for controller in controllers:
        appointment = invite_representation_controller(
            actor=administrator,
            representation_id=representation.id,
            account_id=controller.id,
            reason="Invite a synthetic controller.",
            correlation_id=uuid4(),
        )
        respond_to_representation_invitation(
            actor=controller,
            appointment_id=appointment.id,
            expected_version=appointment.invitation_version,
            accept=True,
            correlation_id=uuid4(),
        )
    representation.refresh_from_db()
    activate_executive_board(
        actor=administrator,
        representation_id=representation.id,
        expected_version=representation.aggregate_version,
        reason="Activate synthetic governance.",
        correlation_id=uuid4(),
    )
    changes = dict(membership_changes)
    if changes.get("ended_at") == "now":
        changes["ended_at"] = timezone.now()
    membership = OrganizationMembership.objects.get(
        organization=organization,
        account=controllers[0],
    )

    def tamper_with_membership() -> None:
        with transaction.atomic():
            OrganizationMembership.objects.filter(pk=membership.pk).update(**changes)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SET CONSTRAINTS organizations_membership_board_provenance "
                    "IMMEDIATE"
                )

    with pytest.raises(
        IntegrityError,
        match="active representation membership evidence is incomplete",
    ):
        tamper_with_membership()
