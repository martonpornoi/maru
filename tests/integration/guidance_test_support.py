"""Public-command synthetic Guides foundation shared by native owner tests."""

from datetime import date
from uuid import uuid4

import pytest

from maru.authorization.activation import activate_authority_provenance
from maru.events.guidance_activation import (
    apply_guidance_activation,
    propose_guidance_activation,
    respond_to_guidance_activation,
)
from maru.events.guidance_adoption import set_up_guidance_adoption
from maru.events.guidance_setup_inputs import (
    GuidanceAdoptionSetupInput,
    GuidanceSetupMode,
)
from maru.events.models import EventEdition
from maru.organizations.models import OrganizationRepresentation
from maru.organizations.representation import (
    activate_representation,
    invite_representation_controller,
    respond_to_representation_invitation,
)
from tests.factories import AccountFactory


@pytest.fixture
def guidance_runtime(settings, proves_safe_runtime_database_role):
    """Select actual exact provenance before any public Guides setup command."""
    settings.REQUIRE_EXACT_AUTHORITY_PROVENANCE = True
    platform = AccountFactory(is_staff=True, is_superuser=True)
    activate_authority_provenance(
        actor=platform,
        reason="Activate exact lineage in the isolated synthetic test.",
        correlation_id=uuid4(),
        acknowledge_processes_stopped=True,
        source_channel="test",
    )
    return platform


def guidance_setup_details():
    return GuidanceAdoptionSetupInput(
        mode=GuidanceSetupMode.NEW_FOUNDATION,
        organization_name="Synthetic Guides organizers",
        series_name="Synthetic Guides convention",
        edition_name="Synthetic Guides event",
        starts_on=date(2032, 8, 12),
        ends_on=date(2032, 8, 15),
        time_zone="Europe/Budapest",
        language_codes=("en", "hu"),
        reason="Prepare the synthetic internal Guides workspace.",
    )


def create_guidance_foundation(*, platform=None):
    platform = platform or AccountFactory(is_staff=True, is_superuser=True)
    setup = set_up_guidance_adoption(
        actor=platform,
        details=guidance_setup_details(),
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    representation = OrganizationRepresentation.objects.get(id=setup.representation_id)
    operators = (AccountFactory(), AccountFactory())
    for person in operators:
        invitation = invite_representation_controller(
            actor=platform,
            representation_id=representation.id,
            account_id=person.id,
            reason="Invite an accountable synthetic workspace operator.",
            correlation_id=uuid4(),
            source_channel="test",
        )
        respond_to_representation_invitation(
            actor=person,
            appointment_id=invitation.id,
            expected_version=invitation.invitation_version,
            accept=True,
            correlation_id=uuid4(),
            source_channel="test",
        )
    representation.refresh_from_db()
    activate_representation(
        actor=platform,
        representation_id=representation.id,
        expected_version=representation.aggregate_version,
        reason="Activate the synthetic two-person workspace foundation.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    return platform, EventEdition.objects.get(id=setup.edition_id), *operators


def propose_and_accept_guidance(platform, edition, operator_a, operator_b):
    proposal = propose_guidance_activation(
        actor=platform,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        expected_edition_version=edition.aggregate_version,
        operator_ids=(operator_a.id, operator_b.id),
        reason="Accept own Guides duties and approve the other named operator.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
    )
    for person in (operator_a, operator_b):
        respond_to_guidance_activation(
            actor=person,
            request_id=proposal.request_id,
            expected_version=proposal.version,
            accept=True,
            correlation_id=uuid4(),
        )
    return proposal


def create_guidance_workspace(*, platform=None):
    """Return platform, edition and two accepted ordinary Guides operators."""
    platform, edition, operator_a, operator_b = create_guidance_foundation(
        platform=platform
    )
    proposal = propose_and_accept_guidance(platform, edition, operator_a, operator_b)
    apply_guidance_activation(
        actor=platform,
        request_id=proposal.request_id,
        expected_version=proposal.version,
        correlation_id=uuid4(),
    )
    edition.refresh_from_db()
    return platform, edition, operator_a, operator_b
