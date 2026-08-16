"""Non-database contracts for the representation readiness projection."""

from uuid import uuid4

from maru.organizations.management.commands import (
    check_representation_readiness as readiness,
)
from maru.organizations.models import OrganizationRepresentation


def test_active_appointment_projection_is_identity_0010_compatible() -> None:
    representation = OrganizationRepresentation(
        id=uuid4(),
        organization_id=uuid4(),
        state=OrganizationRepresentation.State.ACTIVE,
    )

    query = str(readiness._active_appointments(representation).query)

    assert '"identity_account"."account_kind"' in query
    assert '"identity_account"."is_active"' in query
    assert '"identity_account"."email_verified_at"' in query
    assert '"identity_account"."invitation_provisioning_origin_id"' not in query
