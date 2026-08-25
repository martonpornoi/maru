"""The complete clean-database organizer and volunteer onboarding journey."""

import json
from dataclasses import replace
from datetime import date, timedelta
from io import BytesIO, StringIO
from pathlib import Path
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from maru.authorization.models import RoleAssignment
from maru.authorization.policy import decide, resolve_edition_target
from maru.events.models import EventEdition
from maru.organizations.models import OrganizationMembership
from maru.participation.models import Participation
from maru.registration.models import (
    AttendeeFursuit,
    ConfigurationStatus,
    MediaReviewStatus,
    Registration,
    RegistrationQuestion,
)
from maru.registration.services import (
    AttendeeFursuitInput,
    AttendeeProfileInput,
    review_attendee_media,
    submit_public_registration,
    update_attendee_profile,
)
from maru.workforce.bootstrap import bootstrap_organization_workforce
from maru.workforce.models import (
    Department,
    EditionStructureCommandReceipt,
    EditionStructureControl,
    OnboardingDocumentRequest,
    OnboardingDocumentType,
    Position,
    PositionAssignment,
    PositionDocumentRequirement,
    PositionTemplate,
    VolunteerOpportunity,
)
from maru.workforce.services import (
    activate_position_assignment,
    review_onboarding_document,
)
from maru.workforce.structure_commands import (
    create_department,
    create_position,
    update_position_opportunity,
)
from tests.factories import (
    AccountFactory,
    AdmissionProductFactory,
    EventEditionFactory,
    RegistrationConfigurationFactory,
)
from tests.support.authority import (
    create_provenance_backed_role_bundle,
    grant_board_controllers_edition_capability,
)
from tests.workforce_helpers import create_department_for_test

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]


def _profile_input() -> AttendeeProfileInput:
    return AttendeeProfileInput(
        real_name="Taylor Example",
        date_of_birth=date(2000, 5, 20),
        address_line_1="12 Example Street",
        address_line_2="",
        locality="Budapest",
        postal_code="1051",
        region="Budapest",
        country_code="hu",
        emergency_contact_name="River Example",
        emergency_contact_phone="+36 20 555 0199",
        phone_number="+36 30 555 0123",
        telegram_handle="taylor_example",
        pronoun_code="they_them",
        other_pronouns="",
        bio="Registration volunteer and friendly river otter.",
        spoken_language_codes=("en", "hu"),
        profile_photo=None,
        reuse_profile_photo_id=None,
        keep_profile_photo=True,
        brings_fursuits=False,
        fursuits=(),
        directory_visible=True,
        directory_country_code="hu",
    )


def _image(name: str, color: str) -> SimpleUploadedFile:
    output = BytesIO()
    Image.new("RGB", (8, 8), color).save(output, format="PNG")
    return SimpleUploadedFile(name, output.getvalue(), content_type="image/png")


def test_clean_organizer_rehearsal_activates_reviewed_position_authority(  # noqa: PLR0915
    settings: object,
    tmp_path: Path,
) -> None:
    settings.MEDIA_ROOT = tmp_path  # type: ignore[attr-defined]
    controller = AccountFactory(
        email="initial-admin@example.invalid",
        display_name="Initial Administrator",
        is_staff=True,
        is_superuser=True,
    )
    chair = AccountFactory(
        email="chair@example.invalid",
        display_name="Convention Chair",
        is_staff=True,
    )
    attendee = AccountFactory(
        email="volunteer@example.invalid",
        display_name="Taylor Volunteer",
    )
    edition = EventEditionFactory()
    organization = edition.organization

    bootstrap_correlation = uuid4()
    created = bootstrap_organization_workforce(
        organization=organization,
        edition=edition,
        controller=controller,
        chair=chair,
        reason="Establish the first accountable convention leadership.",
        correlation_id=bootstrap_correlation,
    )

    assert created["position_templates"] >= 10
    assert not RoleAssignment.objects.filter(
        organization=organization,
        principal=controller,
    ).exists()
    assert not OrganizationMembership.objects.filter(
        organization=organization,
        account=controller,
    ).exists()
    assert not Participation.objects.filter(
        organization=organization,
        account=controller,
    ).exists()
    assert not PositionAssignment.objects.filter(
        organization=organization,
        account=controller,
    ).exists()
    leadership = Department.objects.get(
        edition=edition,
        code="convention-leadership",
    )
    structure = EditionStructureControl.objects.get(edition=edition)
    receipt = EditionStructureCommandReceipt.objects.get(
        correlation_id=bootstrap_correlation,
        action=EditionStructureCommandReceipt.Action.DEPARTMENT_CREATED,
    )
    assert structure.origin == EditionStructureControl.Origin.MANUAL
    assert structure.aggregate_version == 2
    assert receipt.retry_key == bootstrap_correlation
    assert receipt.actor_id == controller.id
    assert receipt.affected_department_ids == [leadership.id]
    position_receipt = EditionStructureCommandReceipt.objects.get(
        correlation_id=bootstrap_correlation,
        action=EditionStructureCommandReceipt.Action.POSITION_CREATED,
    )
    assert position_receipt.resulting_version == 2
    assert (
        position_receipt.affected_position_id
        == Position.objects.get(
            edition=edition,
            code="convention-chair",
        ).id
    )
    assert RoleAssignment.objects.filter(
        organization=organization,
        principal=chair,
        edition__isnull=True,
    ).exists()
    with pytest.raises(ValidationError, match="already has authority"):
        bootstrap_organization_workforce(
            organization=organization,
            edition=edition,
            controller=controller,
            chair=chair,
            reason="A repeated bootstrap must fail closed.",
            correlation_id=uuid4(),
        )
    authority_actor, authority_approver = grant_board_controllers_edition_capability(
        edition,
        "workforce.manage_assignments",
    )

    configuration = RegistrationConfigurationFactory(
        edition=edition,
        opens_at=timezone.now() + timedelta(days=30),
        closes_at=timezone.now() + timedelta(days=60),
        minimum_age=18,
    )
    product = AdmissionProductFactory(
        configuration=configuration,
        code="weekend",
        name="Weekend admission",
        price_minor=12_000,
        sales_open_at=timezone.now() + timedelta(days=30),
        sales_close_at=timezone.now() + timedelta(days=60),
    )
    RegistrationQuestion.objects.create(
        configuration=configuration,
        key="badge-name",
        label="Name on badge",
        field_type="short_text",
        required=True,
        position=10,
        purpose="Print the attendee badge.",
    )
    configuration.status = ConfigurationStatus.ACTIVE
    configuration.review_required = False
    configuration.review_note = "Reviewed for the clean onboarding rehearsal."
    configuration.activated_at = timezone.now()
    configuration.save(
        update_fields=(
            "status",
            "review_required",
            "review_note",
            "activated_at",
            "updated_at",
        )
    )

    result = submit_public_registration(
        organization_id=organization.id,
        edition_id=edition.id,
        product_id=product.id,
        answers={"badge-name": "Taylor"},
        profile_input=_profile_input(),
        correlation_id=uuid4(),
        account=attendee,
        staff_actor=controller,
        staff_reason=(
            "Attendee requested registration before public sales and will pay "
            "through the ordinary attendee flow."
        ),
        bypass_sale_windows=True,
        source_channel="staff_web",
    )

    assert result.registration.state == Registration.State.PAYMENT_PENDING
    assert (
        result.registration.submission_source
        == Registration.SubmissionSource.STAFF_ASSISTED
    )
    assert result.registration.submitted_by == controller

    client = Client()
    client.force_login(controller)
    assisted_page = client.get(
        reverse("management-assisted-registration", args=(edition.id,))
    )
    assert assisted_page.status_code == 200
    assert b"outside public" in assisted_page.content

    client.force_login(attendee)
    profile_page = client.get(f"/register/{edition.id}/profile/")
    assert profile_page.status_code == 200
    assert b"Simulate payment (local only)" in profile_page.content
    paid = client.post(f"/register/{edition.id}/profile/demo-payment/")
    assert paid.status_code == 302
    result.registration.refresh_from_db()
    assert result.registration.state == Registration.State.CONFIRMED

    nda_type = OnboardingDocumentType.objects.create(
        organization=organization,
        edition=edition,
        code="volunteer-nda",
        name="Volunteer NDA",
        version=1,
        description="Signed confidentiality agreement for registration staff.",
        status=OnboardingDocumentType.Status.ACTIVE,
        created_by=controller,
    )
    nda_request = OnboardingDocumentRequest.objects.create(
        organization=organization,
        edition=edition,
        document_type=nda_type,
        account=attendee,
        instructions="Download, sign, and upload the PDF.",
        requested_by=controller,
        requested_at=timezone.now(),
    )
    client.force_login(attendee)
    documents_web = client.get(f"/volunteer/{edition.id}/documents/")
    assert documents_web.status_code == 200
    upload_form = client.get(
        f"/volunteer/{edition.id}/documents/{nda_request.id}/upload/"
    )
    assert upload_form.status_code == 200
    self_api = APIClient()
    self_api.force_authenticate(attendee)
    documents_path = (
        f"/api/v1/organizations/{organization.id}/editions/{edition.id}/"
        "workforce/documents/me"
    )
    documents = self_api.get(documents_path)
    assert documents.status_code == 200
    assert documents.json()[0]["document_type_code"] == "volunteer-nda"
    submitted = self_api.post(
        f"{documents_path}/{nda_request.id}/upload",
        {
            "document": SimpleUploadedFile(
                "signed-nda.pdf",
                b"%PDF-1.4\n% synthetic signed NDA\n%%EOF\n",
                content_type="application/pdf",
            )
        },
        format="multipart",
    )
    assert submitted.status_code == 200
    submitted_nda = OnboardingDocumentRequest.objects.get(id=nda_request.id)
    assert submitted_nda.status == OnboardingDocumentRequest.Status.SUBMITTED
    approved_nda = review_onboarding_document(
        actor=chair,
        request_id=nda_request.id,
        decision=OnboardingDocumentRequest.Status.APPROVED,
        reason="Signature and current agreement version verified.",
        correlation_id=uuid4(),
    )
    assert approved_nda.status == OnboardingDocumentRequest.Status.APPROVED
    owner_download = client.get(f"/volunteer/documents/{nda_request.id}/download/")
    assert owner_download.status_code == 200
    owner_download.close()
    client.force_login(chair)
    staff_download = client.get(f"/volunteer/documents/{nda_request.id}/download/")
    assert staff_download.status_code == 200
    staff_download.close()
    client.force_login(AccountFactory(display_name="Unrelated Account"))
    denied_download = client.get(f"/volunteer/documents/{nda_request.id}/download/")
    assert denied_download.status_code == 404
    with pytest.raises(DatabaseError), transaction.atomic():
        OnboardingDocumentRequest.objects.filter(id=nda_request.id).update(
            review_reason="Attempted evidence rewrite."
        )

    updated_profile = update_attendee_profile(
        organization_id=organization.id,
        edition_id=edition.id,
        actor=attendee,
        profile_input=replace(
            _profile_input(),
            profile_photo=_image("profile.png", "#446688"),
            brings_fursuits=True,
            fursuits=(
                AttendeeFursuitInput(
                    name="Moss",
                    species="River otter",
                    photo=_image("moss.png", "#884466"),
                ),
            ),
        ),
        correlation_id=uuid4(),
    )
    fursuit = AttendeeFursuit.objects.get(profile=updated_profile, is_active=True)
    assert updated_profile.profile_photo_status == MediaReviewStatus.PENDING
    assert fursuit.photo_status == MediaReviewStatus.PENDING
    review_attendee_media(
        organization_id=organization.id,
        edition_id=edition.id,
        actor=chair,
        media_kind="profile_photo",
        media_id=updated_profile.id,
        decision=MediaReviewStatus.APPROVED,
        reason="Suitable attendee profile image.",
        correlation_id=uuid4(),
    )
    review_attendee_media(
        organization_id=organization.id,
        edition_id=edition.id,
        actor=chair,
        media_kind="fursuit_photo",
        media_id=fursuit.id,
        decision=MediaReviewStatus.APPROVED,
        reason="Suitable fursuit image.",
        correlation_id=uuid4(),
    )

    leadership = Department.objects.get(
        edition=edition,
        code="convention-leadership",
    )
    operations_result = create_department(
        actor=controller,
        organization_id=organization.id,
        series_id=edition.series_id,
        edition_id=edition.id,
        name="Operations",
        description="Attendee-facing convention operations.",
        parent_department_id=leadership.id,
        display_order=10,
        expected_version=2,
        reason="Add the attendee operations test Department.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    operations = Department.objects.get(
        pk=operations_result.department_id,
        organization=organization,
        edition=edition,
    )
    starter_template = PositionTemplate.objects.get(
        organization=organization,
        code="registration-lead",
        status=PositionTemplate.Status.PUBLISHED,
    )
    _role_actor, _role_approver, assignment_role = create_provenance_backed_role_bundle(
        organization,
        code="registration-lead",
        name="Registration Lead",
        capability_codes=tuple(starter_template.role_bundle.capability_codes),
    )
    template = PositionTemplate.objects.create(
        organization=organization,
        code="registration-lead",
        version=2,
        name=starter_template.name,
        description=starter_template.description,
        default_headcount=starter_template.default_headcount,
        default_capacity_codes=starter_template.default_capacity_codes,
        role_bundle=assignment_role,
        status=PositionTemplate.Status.PUBLISHED,
        created_by=controller,
    )
    chair_position = Position.objects.get(
        edition=edition,
        code="convention-chair",
    )
    position_result = create_position(
        actor=controller,
        organization_id=organization.id,
        series_id=edition.series_id,
        edition_id=edition.id,
        template_id=template.id,
        department_id=operations.id,
        reports_to_id=chair_position.id,
        title="Registration Lead",
        description=template.description,
        headcount=1,
        expected_version=operations_result.resulting_version,
        reason="Create the accountable registration Position for this rehearsal.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    position = Position.objects.get(id=position_result.position_id)
    PositionDocumentRequirement.objects.create(
        position=position,
        document_type=nda_type,
    )
    opportunity = VolunteerOpportunity.objects.get(position=position)
    update_position_opportunity(
        actor=controller,
        organization_id=organization.id,
        series_id=edition.series_id,
        edition_id=edition.id,
        position_id=position.id,
        status=VolunteerOpportunity.Status.PUBLISHED,
        headline=opportunity.headline,
        description=opportunity.description,
        applications_open_at=None,
        applications_close_at=None,
        visible_when_filled=True,
        expected_version=position_result.resulting_version,
        reason="Publish the registration volunteer opportunity.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    opportunity.refresh_from_db()
    opportunities_page = client.get(f"/volunteer/{edition.id}/")
    assert opportunities_page.status_code == 200
    web_applicant = AccountFactory(display_name="Web Applicant")
    client.force_login(web_applicant)
    application_form = client.get(f"/volunteer/{edition.id}/{opportunity.id}/apply/")
    assert application_form.status_code == 200
    web_application = client.post(
        f"/volunteer/{edition.id}/{opportunity.id}/apply/",
        {"motivation": "I can help attendees through the reference client."},
    )
    assert web_application.status_code == 302
    applicant = AccountFactory(display_name="Second Volunteer")
    applicant_api = APIClient()
    applicant_api.force_authenticate(applicant)
    applied = applicant_api.post(
        (
            f"/api/v1/organizations/{organization.id}/editions/{edition.id}/"
            f"workforce/opportunities/{opportunity.id}/applications/me"
        ),
        {"motivation": "I would like to help the registration team."},
        format="json",
    )
    assert applied.status_code == 201

    assignment = activate_position_assignment(
        position_id=position.id,
        account=attendee,
        actor=authority_actor,
        approver=authority_approver,
        effective_from=timezone.now(),
        expires_at=None,
        reason="Approved NDA and appointment as registration lead.",
        correlation_id=uuid4(),
    )

    assert assignment.status == PositionAssignment.Status.ACTIVE
    position.refresh_from_db()
    assert position.status == Position.Status.FILLED
    assert opportunity.is_filled
    assert not opportunity.accepts_applications
    assert opportunity.visible_when_filled
    public_opportunities = APIClient().get(
        f"/api/v1/public/editions/{edition.id}/volunteer-opportunities"
    )
    assert public_opportunities.status_code == 200
    public_item = next(
        item
        for item in public_opportunities.json()
        if item["position_code"] == "registration-lead"
    )
    assert public_item["is_filled"] is True
    assert public_item["accepts_applications"] is False
    assert decide(
        principal=attendee,
        capability_code="registration.register_on_behalf",
        resource=resolve_edition_target(
            organization_id=organization.id,
            edition_id=edition.id,
        ),
    ).allowed

    api = APIClient()
    api.force_authenticate(attendee)
    service_list = api.get(
        f"/api/v1/organizations/{organization.id}/editions/{edition.id}/registrations"
    )
    assert service_list.status_code == 200
    admin_client = Client()
    admin_client.force_login(controller)
    for model_name in (
        "department",
        "positiontemplate",
        "position",
        "volunteeropportunity",
        "volunteerapplication",
        "onboardingdocumenttype",
        "onboardingdocumentrequest",
        "positionassignment",
    ):
        response = admin_client.get(reverse(f"admin:workforce_{model_name}_changelist"))
        assert response.status_code == 200
    position_admin = admin_client.get(
        reverse("admin:workforce_position_change", args=(position.id,))
    )
    assert position_admin.status_code == 200
    document_admin = admin_client.get(
        reverse(
            "admin:workforce_onboardingdocumentrequest_change",
            args=(nda_request.id,),
        )
    )
    assert document_admin.status_code == 200
    assignment_add = admin_client.get(reverse("admin:workforce_positionassignment_add"))
    assert assignment_add.status_code == 403
    assignment_management = admin_client.get(
        reverse(
            "organization-workforce-assignments",
            kwargs={
                "organization_slug": organization.slug,
                "series_slug": edition.series.slug,
                "edition_slug": edition.slug,
            },
        )
    )
    assert assignment_management.status_code == 200
    assert b"Workforce assignments" in assignment_management.content


def test_workforce_database_guard_rejects_cross_organization_scope() -> None:
    first_edition = EventEditionFactory()
    other_edition = EventEditionFactory()
    department = create_department_for_test(
        edition=first_edition,
        name="Operations",
        expected_code="operations",
    )

    with pytest.raises(DatabaseError), transaction.atomic():
        Department.objects.filter(id=department.id).update(edition=other_edition)


def test_bootstrap_command_covers_success_and_safe_refusals() -> None:
    controller = AccountFactory(
        email="command-admin@example.invalid",
        is_staff=True,
        is_superuser=True,
    )
    chair = AccountFactory(email="command-chair@example.invalid")
    edition = EventEditionFactory(
        slug="command-2030",
        series__organization__slug="command-organization",
    )
    output = StringIO()
    options = {
        "organization": edition.organization.slug,
        "edition": edition.slug,
        "controller_email": controller.email,
        "chair_email": chair.email,
        "reason": "Exercise the one-shot bootstrap command.",
        "confirm_organization": edition.organization.slug,
    }

    call_command("bootstrap_convention", stdout=output, **options)
    result = json.loads(output.getvalue())
    assert result["created"]["position_templates"] == 10

    with pytest.raises(CommandError, match="already has authority"):
        call_command("bootstrap_convention", **options)
    with pytest.raises(CommandError, match="exactly match"):
        call_command(
            "bootstrap_convention",
            **{**options, "confirm_organization": "wrong-organization"},
        )
    with pytest.raises(CommandError, match="organization is unavailable"):
        call_command(
            "bootstrap_convention",
            **{
                **options,
                "organization": "missing-organization",
                "confirm_organization": "missing-organization",
            },
        )
    other_edition = EventEditionFactory(
        slug="other-command-2030",
        series__organization__slug="other-command-organization",
    )
    ready_edition = EventEditionFactory(
        slug="ready-command-2030",
        series__organization__slug="ready-command-organization",
    )
    EventEdition.objects.filter(pk=ready_edition.pk).update(
        lifecycle=EventEdition.Lifecycle.PREPARING,
        lifecycle_version=1,
        aggregate_version=2,
    )
    EventEdition.objects.filter(pk=ready_edition.pk).update(
        lifecycle=EventEdition.Lifecycle.READY,
        lifecycle_version=2,
        aggregate_version=3,
    )
    with pytest.raises(CommandError, match="Draft or Preparing"):
        call_command(
            "bootstrap_convention",
            **{
                **options,
                "organization": ready_edition.organization.slug,
                "confirm_organization": ready_edition.organization.slug,
                "edition": ready_edition.slug,
            },
        )
    with pytest.raises(CommandError, match="edition is unavailable"):
        call_command(
            "bootstrap_convention",
            **{
                **options,
                "organization": other_edition.organization.slug,
                "confirm_organization": other_edition.organization.slug,
                "edition": "missing-edition",
            },
        )
    with pytest.raises(CommandError, match="must already exist"):
        call_command(
            "bootstrap_convention",
            **{
                **options,
                "organization": other_edition.organization.slug,
                "confirm_organization": other_edition.organization.slug,
                "edition": other_edition.slug,
                "chair_email": "missing-chair@example.invalid",
            },
        )
