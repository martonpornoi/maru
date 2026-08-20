"""Reusable synthetic authority roots for provenance-aware integration tests."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from django.utils import timezone

from maru.authorization.commands import (
    create_role_bundle_version,
    grant_capability_direct,
)
from maru.authorization.policy import (
    resolve_edition_target,
    resolve_organization_target,
)
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
from tests.factories import AccountFactory

if TYPE_CHECKING:
    from maru.authorization.models import RoleBundle
    from maru.events.models import EventEdition
    from maru.identity.models import Account


def activate_synthetic_board(
    organization: Organization,
) -> tuple[Account, Account]:
    """Return two controllers established by the real Board ceremony.

    Broad legacy factories create an Active organization without representation.
    This isolated test helper rewinds only that synthetic parent to Draft, then
    uses the production provision/invite/accept/activate commands. Repeated calls
    return the same two active controllers and never mint parallel authority.
    """

    active = list(
        RepresentationAppointment.objects.select_related("account")
        .filter(
            representation__organization=organization,
            state=RepresentationAppointment.State.ACTIVE,
            role=RepresentationAppointment.Role.CONTROLLER,
            role_assignment__isnull=False,
        )
        .order_by("responded_at", "id")[:2]
    )
    if len(active) == 2:
        return active[0].account, active[1].account

    if OrganizationRepresentation.objects.filter(organization=organization).exists():
        raise AssertionError(
            "Synthetic organization has incomplete representation state."
        )
    Organization.objects.filter(pk=organization.pk).update(
        lifecycle=Organization.Lifecycle.DRAFT
    )
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    representation = provision_executive_board(
        actor=administrator,
        organization_id=organization.id,
        reason="Establish exact synthetic governance.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    for _index in range(2):
        controller = AccountFactory()
        invitation = invite_representation_controller(
            actor=administrator,
            representation_id=representation.id,
            account_id=controller.id,
            reason="Invite an exact synthetic controller.",
            correlation_id=uuid4(),
            source_channel="test",
        )
        respond_to_representation_invitation(
            actor=controller,
            appointment_id=invitation.id,
            expected_version=invitation.invitation_version,
            accept=True,
            correlation_id=uuid4(),
            source_channel="test",
        )
    representation.refresh_from_db()
    result = activate_executive_board(
        actor=administrator,
        representation_id=representation.id,
        expected_version=representation.aggregate_version,
        reason="Activate exact synthetic governance.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    if len(result.appointments) != 2:
        raise AssertionError(
            "Synthetic Board activation did not create two controllers."
        )
    first, second = result.appointments
    organization.refresh_from_db()
    return first.account, second.account


def create_provenance_backed_role_bundle(
    organization: Organization,
    *,
    code: str,
    name: str,
    capability_codes: tuple[str, ...],
) -> tuple[Account, Account, RoleBundle]:
    """Authorize one synthetic immutable role through the real Board root."""

    actor, approver = activate_synthetic_board(organization)
    target = resolve_organization_target(organization_id=organization.id)
    if target is None:
        raise AssertionError("Synthetic organization target is unavailable.")
    role = create_role_bundle_version(
        actor=actor,
        approver=approver,
        target=target,
        code=code,
        name=name,
        capability_codes=capability_codes,
        reason="Create an issuance-backed synthetic role definition.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    return actor, approver, role


def grant_board_controllers_edition_capability(
    edition: EventEdition,
    capability_code: str,
) -> tuple[Account, Account]:
    """Give both synthetic Board controllers exact edition-scoped authority."""

    first, second = activate_synthetic_board(edition.organization)
    target = resolve_edition_target(
        organization_id=edition.organization_id,
        edition_id=edition.id,
    )
    if target is None:
        raise AssertionError("Synthetic edition target is unavailable.")
    effective_from = timezone.now()
    for actor, approver in ((first, second), (second, first)):
        grant_capability_direct(
            actor=actor,
            approver=approver,
            recipient=actor,
            capability_code=capability_code,
            target=target,
            effective_from=effective_from,
            expires_at=None,
            reason="Establish exact synthetic edition authority.",
            correlation_id=uuid4(),
            source_channel="test",
        )
    return first, second
