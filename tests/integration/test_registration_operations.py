from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from tests.factories import EventEditionFactory, OrganizationFactory

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


def test_registration_metrics_are_scoped_and_machine_readable() -> None:
    edition = EventEditionFactory()
    output = StringIO()

    call_command(
        "registration_metrics",
        organization=edition.organization_id,
        edition=edition.id,
        stdout=output,
    )

    values = {
        line.split()[0]: int(line.split()[1]) for line in output.getvalue().splitlines()
    }
    assert values["registration_lifecycle_candidates"] == 0
    assert values["registration_lifecycle_last_success_age_seconds"] == -1
    assert values["registration_capacity_drift"] == 0
    assert values["registration_payment_exceptions_open"] == 0
    assert values["registration_financial_operations_open"] == 0
    assert values["registration_due_restrictions_unapplied"] == 0
    assert values["registration_delivery_failures"] == 0
    assert values["registration_outbox_quarantined"] == 0

    other_organization = OrganizationFactory()
    with pytest.raises(CommandError, match="unavailable"):
        call_command(
            "registration_metrics",
            organization=other_organization.id,
            edition=edition.id,
        )


def test_registration_metrics_reject_an_incompatible_exact_profile() -> None:
    """Do not project retained Registration metrics for an unadopted edition."""
    edition = EventEditionFactory(
        adoption_profile_code="workforce_only",
        adoption_profile_version=1,
    )
    output = StringIO()

    with pytest.raises(CommandError, match="unavailable"):
        call_command(
            "registration_metrics",
            organization=edition.organization_id,
            edition=edition.id,
            stdout=output,
        )

    assert output.getvalue() == ""
