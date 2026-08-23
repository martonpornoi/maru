import json
from datetime import UTC, datetime
from io import StringIO
from uuid import UUID, uuid4

import pytest
from django.contrib import admin
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client
from django.urls import reverse

from maru.authorization.models import RoleBundle, ScopedResourceBinding
from maru.authorization.policy import decide, resolve_edition_target
from maru.demo.constants import DEMO_ACCOUNT_PASSWORD
from maru.demo.operational_examples import seed_workforce_examples
from maru.events.models import EventEdition
from maru.events.services import transition_edition
from maru.identity.models import Account, PlatformInvitationSchedulerRun
from maru.organizations.models import (
    ConventionSeries,
    Organization,
    OrganizationMembership,
    OrganizationRepresentation,
    RepresentationAppointment,
)
from maru.participation.models import Participation, ParticipationCapacity
from maru.registration.models import (
    AttendeeFursuit,
    AttendeeRegistrationProfile,
    Entitlement,
    FinancialLedgerEntry,
    Registration,
    RegistrationConfiguration,
    RegistrationProvenanceStatus,
    RegistrationSection,
    RegistrationSetupControl,
    RegistrationSetupOrigin,
    RegistrationSubmission,
    RegistrationTemplate,
    RegistrationTemplateSection,
    RegistrationTimelineEntry,
)
from maru.workforce.models import (
    Department,
    EditionStructureCommandReceipt,
    EditionStructureControl,
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
    assert result["totals"]["role_bundles"] == 30
    assert result["totals"]["role_assignments"] == 162
    assert result["totals"]["capability_grants"] == 66
    assert result["totals"]["participations"] >= 150
    assert result["totals"]["participation_capacities"] >= 400
    assert result["totals"]["lifecycle_transitions"] == 12
    assert result["totals"]["audit_events"] == 34
    assert result["totals"]["domain_events"] == 30
    assert result["totals"]["outbox_messages"] == 30
    assert result["totals"]["registration_templates"] == 2
    assert result["totals"]["registration_configurations"] == 8
    assert result["totals"]["registration_setup_controls"] == 6
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
    assert (
        OrganizationRepresentation.objects.filter(
            state=OrganizationRepresentation.State.ACTIVE
        ).count()
        == 2
    )
    assert (
        RepresentationAppointment.objects.filter(
            state=RepresentationAppointment.State.ACTIVE
        ).count()
        == 4
    )
    marucon_organization = Organization.objects.get(slug="maru-community-events-demo")
    assert marucon_organization.country_code == "HU"
    assert marucon_organization.default_language_codes == ["en", "hu", "de"]
    assert marucon_organization.legal_name
    assert marucon_organization.contact_email
    assert marucon_organization.website_url
    marucon_series = ConventionSeries.objects.get(slug="marucon")
    assert marucon_series.description
    assert marucon_series.contact_email
    assert marucon_series.website_url
    assert set(EventEdition.objects.values_list("lifecycle", flat=True)) == {
        EventEdition.Lifecycle.ARCHIVED,
        EventEdition.Lifecycle.PREPARING,
        EventEdition.Lifecycle.DRAFT,
    }
    structure_receipts = EditionStructureCommandReceipt.objects.filter(
        action=EditionStructureCommandReceipt.Action.DEPARTMENT_CREATED,
        source_channel="demo_seed",
    )
    assert structure_receipts.count() == 2
    assert all(
        receipt.retry_key is not None
        and receipt.request_digest
        and len(receipt.affected_department_ids) == 1
        for receipt in structure_receipts
    )
    assert (
        EditionStructureControl.objects.filter(
            origin=EditionStructureControl.Origin.MANUAL,
            aggregate_version=1,
        ).count()
        == 2
    )
    assert (
        Department.objects.filter(
            created_in_structure_version=1,
            last_changed_in_structure_version=1,
        ).count()
        == 2
    )
    assert (
        ScopedResourceBinding.objects.filter(
            resource_kind=ScopedResourceBinding.ResourceKind.WORKFORCE_POSITION,
        ).count()
        == 2
    )
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

    marucon_chair = Account.objects.get(
        email="marucon.convention-chair@demo.maru.invalid"
    )
    marucon_current = EventEdition.objects.get(slug="marucon-2026")
    decision = decide(
        principal=marucon_chair,
        capability_code="events.transition",
        resource=resolve_edition_target(
            organization_id=marucon_current.organization_id,
            edition_id=marucon_current.id,
        ),
    )
    assert decision.allowed
    assert decision.reason_code == "role_assignment"
    for capability_code in (
        "authorization.manage_roles",
        "authorization.revoke",
    ):
        access_decision = decide(
            principal=marucon_chair,
            capability_code=capability_code,
            resource=resolve_edition_target(
                organization_id=marucon_current.organization_id,
                edition_id=marucon_current.id,
            ),
        )
        assert access_decision.allowed
    assert RoleBundle.objects.filter(
        organization=marucon_current.organization,
        code="demo-director",
    ).exists()
    marucon_configuration = RegistrationConfiguration.objects.get(
        edition=marucon_current,
        status="active",
    )
    assert marucon_configuration.source_template_id is not None
    assert marucon_configuration.questions.count() == 5
    assert marucon_configuration.products.count() == 5
    assert (
        RegistrationSetupControl.objects.filter(
            origin=RegistrationSetupOrigin.LEGACY_EXISTING,
            provenance_status=RegistrationProvenanceStatus.LEGACY_UNKNOWN,
            aggregate_version=1,
        ).count()
        == 6
    )
    assert (
        RegistrationTemplate.objects.filter(
            organization=marucon_current.organization,
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
            registration__edition=marucon_current,
        )
    )

    sponsor = Registration.objects.get(
        edition=marucon_current,
        account__email="marucon.sponsor-attendee@demo.maru.invalid",
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
    assert sponsor.account.email in account_content
    assert "Organizer-managed relationships" not in account_content
    assert "Infinity holder" not in account_content
    assert sponsor.reference not in account_content

    registration_lead = Account.objects.get(
        email="marucon.registration-lead@demo.maru.invalid"
    )
    assert (
        registration_lead.role_assignments.filter(
            edition=marucon_current,
            revoked_at__isnull=True,
        ).count()
        >= 2
    )

    operational_evidence_models = {PlatformInvitationSchedulerRun}
    empty_admin_models = [
        model._meta.label
        for model in admin.site._registry
        if model._meta.app_label != "auth"
        and model not in operational_evidence_models
        and not model._default_manager.exists()
    ]
    assert empty_admin_models == []
    # A synthetic scheduler heartbeat would make readiness report a worker that
    # has never run. The fixture therefore leaves liveness evidence empty.
    assert not PlatformInvitationSchedulerRun.objects.exists()

    totals_before = result["totals"]
    transition_edition(
        organization_id=marucon_current.organization_id,
        edition_id=marucon_current.id,
        to_state=EventEdition.Lifecycle.READY,
        actor=marucon_chair,
        reason="Prove demo workforce replay after the editable lifecycle.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    replay_created: list[str] = []

    def record_replay(
        kind: str,
        _object_id: UUID,
        *,
        created: bool,
    ) -> None:
        if created:
            replay_created.append(kind)

    seed_workforce_examples(
        convention_key="marucon",
        organization=marucon_current.organization,
        edition=EventEdition.objects.get(pk=marucon_current.id),
        accounts={
            key: Account.objects.get(email=f"marucon.{key}@demo.maru.invalid")
            for key in (
                "convention-chair",
                "registration-lead",
                "registration-volunteer",
                "volunteer-applicant",
            )
        },
        own=record_replay,
        happened_at=datetime(2026, 6, 12, 10, 5, tzinfo=UTC),
    )
    assert replay_created == []
    # Exercise the legacy-ID fallback on the second synthetic fursuit. Position
    # zero owns a pinned media-safety receipt, so changing that ID would
    # intentionally create new append-only safety evidence on replay.
    fursuit = AttendeeFursuit.objects.filter(position=1).order_by("id").first()
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
    expected_totals = dict(totals_before)
    for key in (
        "lifecycle_transitions",
        "audit_events",
        "domain_events",
        "outbox_messages",
    ):
        expected_totals[key] += 1
    assert second_result["totals"] == expected_totals
    assert second_result["passwords_reset"] == 80
    marucon_chair.refresh_from_db()
    assert marucon_chair.check_password(DEMO_PASSWORD)
    assert AttendeeFursuit.objects.filter(id=legacy_fursuit_id).exists()

    access_client = Client()
    access_client.force_login(marucon_chair)
    access_response = access_client.get(
        reverse(
            "api-edition-access-workspace",
            kwargs={
                "organization_id": marucon_current.organization_id,
                "edition_id": marucon_current.id,
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
        assignment["person_email"] == "marucon.front-desk-volunteer@demo.maru.invalid"
        and assignment["group_name"] == "Front Desk"
        for assignment in access_payload["assignments"]
    )

    registration_setup_response = access_client.get(
        reverse(
            "registration-setup",
            kwargs={
                "organization_slug": marucon_current.organization.slug,
                "series_slug": marucon_current.series.slug,
                "edition_slug": marucon_current.slug,
            },
        )
    )
    assert registration_setup_response.status_code == 200
    registration_setup_content = registration_setup_response.content.decode()
    assert "<h1>Registration</h1>" in registration_setup_content
    assert "Active registration version" in registration_setup_content
    assert "existing provenance" in registration_setup_content


def test_demo_seed_refuses_nonlocal_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "maru.settings.production")

    with pytest.raises(CommandError, match="only with Maru local or test settings"):
        call_command(
            "seed_demo_data",
            stdout=StringIO(),
        )
