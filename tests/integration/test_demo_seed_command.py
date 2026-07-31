import json
from io import StringIO
from uuid import uuid4

import pytest
from django.contrib import admin
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client
from django.urls import reverse

from maru.authorization.models import RoleBundle
from maru.authorization.policy import ResourceScope, decide
from maru.demo.constants import DEMO_ACCOUNT_PASSWORD
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import (
    ConventionSeries,
    Organization,
    OrganizationMembership,
)
from maru.participation.models import Participation, ParticipationCapacity
from maru.registration.models import (
    AttendeeFursuit,
    AttendeeRegistrationProfile,
    Entitlement,
    FinancialLedgerEntry,
    Registration,
    RegistrationConfiguration,
    RegistrationSection,
    RegistrationSubmission,
    RegistrationTemplate,
    RegistrationTemplateSection,
    RegistrationTimelineEntry,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

DEMO_PASSWORD = DEMO_ACCOUNT_PASSWORD


def test_demo_seed_is_comprehensive_and_idempotent() -> None:  # noqa: PLR0915
    output = StringIO()
    call_command("seed_demo_data", stdout=output)
    result = json.loads(output.getvalue())

    assert result["synthetic_only"] is True
    assert result["totals"]["accounts"] == 80
    assert result["totals"]["organizations"] == 2
    assert result["totals"]["convention_series"] == 2
    assert result["totals"]["event_editions"] == 6
    assert result["totals"]["role_bundles"] == 28
    assert result["totals"]["role_assignments"] == 158
    assert result["totals"]["capability_grants"] == 58
    assert result["totals"]["participations"] >= 150
    assert result["totals"]["participation_capacities"] >= 400
    assert result["totals"]["lifecycle_transitions"] == 12
    assert result["totals"]["audit_events"] == 14
    assert result["totals"]["domain_events"] == 14
    assert result["totals"]["outbox_messages"] == 14
    assert result["totals"]["registration_templates"] == 2
    assert result["totals"]["registration_configurations"] == 8
    assert result["totals"]["registration_template_sections"] == 6
    assert result["totals"]["registration_sections"] == 24
    assert result["totals"]["registration_questions"] == 40
    assert result["totals"]["admission_products"] == 22
    assert result["totals"]["registrations"] == 16
    assert result["totals"]["attendee_registration_profiles"] == 16
    assert RegistrationTemplateSection.objects.count() == 6
    assert RegistrationSection.objects.count() == 24
    assert AttendeeRegistrationProfile.objects.count() == 16
    assert AttendeeFursuit.objects.count() == 4

    assert Organization.objects.count() == 2
    danube_organization = Organization.objects.get(slug="pannon-paws-foundation")
    assert danube_organization.country_code == "HU"
    assert danube_organization.default_language_codes == ["en", "hu", "de"]
    assert danube_organization.legal_name
    assert danube_organization.contact_email
    assert danube_organization.website_url
    danube_series = ConventionSeries.objects.get(slug="danube-furry-convention")
    assert danube_series.description
    assert danube_series.contact_email
    assert danube_series.website_url
    assert set(EventEdition.objects.values_list("lifecycle", flat=True)) == {
        EventEdition.Lifecycle.ARCHIVED,
        EventEdition.Lifecycle.PREPARING,
        EventEdition.Lifecycle.DRAFT,
    }
    assert set(OrganizationMembership.objects.values_list("state", flat=True)) >= {
        OrganizationMembership.State.ACTIVE,
        OrganizationMembership.State.INVITED,
        OrganizationMembership.State.ENDED,
    }
    assert {
        "attendee",
        "volunteer",
        "staff",
        "board-member",
        "programme-host",
        "dealer",
        "guest-of-honour",
        "performer",
        "security",
        "first-aid",
        "accessibility",
    } <= set(ParticipationCapacity.objects.values_list("code", flat=True))

    administrator = Account.objects.get(email="demo.admin@maru.invalid")
    assert administrator.is_staff
    assert administrator.is_superuser
    assert administrator.check_password(DEMO_PASSWORD)

    shared_host = Account.objects.get(email="shared.circuit-host@demo.maru.invalid")
    assert (
        Participation.objects.filter(account=shared_host)
        .values("organization_id")
        .distinct()
        .count()
        == 2
    )

    danube_chair = Account.objects.get(
        email="danube.convention-chair@demo.maru.invalid"
    )
    danube_current = EventEdition.objects.get(slug="danube-furry-convention-2026")
    decision = decide(
        principal=danube_chair,
        capability_code="events.transition",
        resource=ResourceScope(
            organization_id=danube_current.organization_id,
            edition_id=danube_current.id,
        ),
    )
    assert decision.allowed
    assert decision.reason_code == "role_assignment"
    for capability_code in (
        "authorization.manage_roles",
        "authorization.revoke",
    ):
        access_decision = decide(
            principal=danube_chair,
            capability_code=capability_code,
            resource=ResourceScope(
                organization_id=danube_current.organization_id,
                edition_id=danube_current.id,
            ),
        )
        assert access_decision.allowed
    assert RoleBundle.objects.filter(
        organization=danube_current.organization,
        code="demo-director",
    ).exists()
    danube_configuration = RegistrationConfiguration.objects.get(
        edition=danube_current,
        status="active",
    )
    assert danube_configuration.source_template_id is not None
    assert danube_configuration.questions.count() == 5
    assert danube_configuration.products.count() == 5
    assert (
        RegistrationTemplate.objects.filter(
            organization=danube_current.organization,
            status="published",
        ).count()
        == 1
    )
    assert set(Registration.objects.values_list("state", flat=True)) == set(
        Registration.State.values
    )
    assert all(
        submission.answers
        for submission in RegistrationSubmission.objects.filter(
            registration__edition=danube_current,
        )
    )

    sponsor = Registration.objects.get(
        edition=danube_current,
        account__email="danube.sponsor-attendee@demo.maru.invalid",
    )
    assert sponsor.entitlements.filter(
        code="infinity-ticket",
        status=Entitlement.Status.ACTIVE,
    ).exists()
    assert sponsor.financial_ledger.filter(
        kind=FinancialLedgerEntry.Kind.PAYMENT,
        direction=FinancialLedgerEntry.Direction.INFLOW,
    ).exists()
    assert sponsor.timeline.filter(
        audience=RegistrationTimelineEntry.Audience.STAFF_ONLY,
        kind="internal_note",
    ).exists()

    client = Client()
    client.force_login(administrator)
    registration_page = client.get(
        reverse("admin:registration_registration_change", args=(sponsor.id,))
    )
    registration_content = registration_page.content.decode()
    assert registration_page.status_code == 200
    assert "Submitted registration answers" in registration_content
    assert "Infinity Ticket Holder" in registration_content
    assert "Internal registration comment" in registration_content
    assert "Payment and finance summary" in registration_content
    assert "220.00 EUR received" in registration_content
    assert "Fursuit" in registration_content

    submission_page = client.get(
        reverse(
            "admin:registration_registrationsubmission_change",
            args=(sponsor.submission.id,),
        )
    )
    submission_content = submission_page.content.decode()
    assert submission_page.status_code == 200
    assert "Submitted questions and answers" in submission_content
    assert "Name on your badge" in submission_content

    account_page = client.get(
        reverse(
            "admin:identity_account_change",
            args=(sponsor.account_id,),
        )
    )
    account_content = account_page.content.decode()
    assert account_page.status_code == 200
    assert "Organizer-managed relationships" in account_content
    assert "Infinity holder" in account_content
    assert sponsor.reference in account_content

    registration_lead = Account.objects.get(
        email="danube.registration-lead@demo.maru.invalid"
    )
    assert (
        registration_lead.role_assignments.filter(
            edition=danube_current,
            revoked_at__isnull=True,
        ).count()
        >= 2
    )

    empty_admin_models = [
        model._meta.label
        for model in admin.site._registry
        if model._meta.app_label != "auth" and not model._default_manager.exists()
    ]
    assert empty_admin_models == []

    totals_before = result["totals"]
    fursuit = AttendeeFursuit.objects.order_by("id").first()
    assert fursuit is not None
    legacy_fursuit_id = uuid4()
    AttendeeFursuit.objects.filter(id=fursuit.id).update(id=legacy_fursuit_id)
    second_output = StringIO()
    call_command(
        "seed_demo_data",
        reset_passwords=True,
        stdout=second_output,
    )
    second_result = json.loads(second_output.getvalue())
    assert second_result["created"] == {}
    assert second_result["totals"] == totals_before
    assert second_result["passwords_reset"] == 80
    danube_chair.refresh_from_db()
    assert danube_chair.check_password(DEMO_PASSWORD)
    assert AttendeeFursuit.objects.filter(id=legacy_fursuit_id).exists()

    access_client = Client()
    access_client.force_login(danube_chair)
    access_response = access_client.get(
        reverse(
            "api-edition-access-workspace",
            kwargs={
                "organization_id": danube_current.organization_id,
                "edition_id": danube_current.id,
            },
        )
    )
    assert access_response.status_code == 200
    access_payload = access_response.json()
    assert access_payload["can_revoke_assignments"] is True
    assert {group["name"] for group in access_payload["groups"]} >= {
        "Board",
        "Front Desk",
        "Registration",
        "Treasurer",
    }
    assert any(
        assignment["person_email"] == "danube.front-desk-volunteer@demo.maru.invalid"
        and assignment["group_name"] == "Front Desk"
        for assignment in access_payload["assignments"]
    )


def test_demo_seed_refuses_nonlocal_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "maru.settings.production")

    with pytest.raises(CommandError, match="only with Maru local or test settings"):
        call_command(
            "seed_demo_data",
            stdout=StringIO(),
        )
