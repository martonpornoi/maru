"""Validation and fail-closed edge coverage for workforce records and commands."""

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import RequestFactory
from django.utils import timezone

from maru.authorization.services import AuthorizationDenied
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.participation.models import ParticipationCapacity
from maru.workforce.admin import (
    OnboardingDocumentRequestAdmin,
    OnboardingDocumentTypeAdmin,
    PositionAdmin,
    PositionAssignmentAdmin,
)
from maru.workforce.bootstrap import bootstrap_organization_workforce
from maru.workforce.models import (
    Department,
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
    submit_volunteer_application,
    upload_onboarding_document,
)
from maru.workforce.structure_commands import (
    create_position,
    update_position_opportunity,
)
from tests.factories import (
    AccountFactory,
    EventEditionFactory,
    ParticipationCapacityFactory,
    ParticipationFactory,
    RoleBundleFactory,
)
from tests.support.authority import (
    create_provenance_backed_role_bundle,
    grant_board_controllers_edition_capability,
)
from tests.workforce_helpers import (
    create_department_for_test,
    save_position_assignment_for_test,
    save_position_for_test,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]


def _model_world() -> tuple[
    object,
    object,
    object,
    Department,
    PositionTemplate,
    Position,
]:
    edition = EventEditionFactory()
    actor = AccountFactory()
    role = RoleBundleFactory(organization=edition.organization)
    department = create_department_for_test(
        edition=edition,
        name="Operations",
        expected_code="operations",
    )
    template = PositionTemplate.objects.create(
        organization=edition.organization,
        code="staff-member",
        name="Staff Member",
        version=1,
        description="Supports convention operations.",
        default_headcount=3,
        default_capacity_codes=["staff"],
        role_bundle=role,
        created_by=actor,
    )
    position = save_position_for_test(
        position=Position(
            organization=edition.organization,
            edition=edition,
            template=template,
            department=department,
            role_bundle=role,
            code="staff-member",
            title="Staff Member",
            description=template.description,
            headcount=3,
            capacity_codes=["staff"],
            created_by=actor,
        )
    )
    return edition, edition.organization, actor, department, template, position


def _create_governed_position(
    *,
    actor: Account,
    edition: EventEdition,
    department: Department,
    template: PositionTemplate,
    title: str,
    headcount: int,
) -> tuple[Position, int]:
    current_version = EditionStructureControl.objects.values_list(
        "aggregate_version", flat=True
    ).get(
        organization_id=edition.organization_id,
        edition_id=edition.id,
    )
    result = create_position(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        template_id=template.id,
        department_id=department.id,
        reports_to_id=None,
        title=title,
        description=template.description,
        headcount=headcount,
        expected_version=current_version,
        reason="Create a governed Position for the Workforce integration rehearsal.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return Position.objects.get(id=result.position_id), result.resulting_version


def test_workforce_models_reject_invalid_scope_cycles_versions_and_evidence() -> None:  # noqa: PLR0915
    edition, organization, actor, department, template, position = _model_world()
    other_edition = EventEditionFactory()
    other_department = create_department_for_test(
        edition=other_edition,
        name="Other",
        expected_code="other",
    )
    other_role = RoleBundleFactory(organization=other_edition.organization)

    invalid_department = Department(
        organization=organization,
        edition=other_edition,
        code="invalid",
        name="Invalid",
    )
    with pytest.raises(ValidationError, match="edition scope"):
        invalid_department.clean()
    self_parent = Department(
        organization=organization,
        edition=edition,
        code="self-parent",
        name="Self parent",
    )
    self_parent.parent = self_parent
    with pytest.raises(ValidationError, match="cannot contain itself"):
        self_parent.clean()
    cross_parent = Department(
        organization=organization,
        edition=edition,
        parent=other_department,
        code="cross-parent",
        name="Cross parent",
    )
    with pytest.raises(ValidationError, match="same edition"):
        cross_parent.clean()
    child = create_department_for_test(
        edition=edition,
        parent=department,
        name="Child",
        expected_code="child",
    )
    department.parent = child
    with pytest.raises(ValidationError, match="cycle"):
        department.clean()

    cross_document_type = OnboardingDocumentType(
        organization=organization,
        edition=other_edition,
        code="nda",
        name="NDA",
        description="Agreement",
        created_by=actor,
    )
    with pytest.raises(ValidationError, match="edition scope"):
        cross_document_type.clean()
    immutable_type = OnboardingDocumentType.objects.create(
        organization=organization,
        edition=edition,
        code="immutable-nda",
        name="Immutable NDA",
        description="Agreement",
        status=OnboardingDocumentType.Status.ACTIVE,
        created_by=actor,
    )
    immutable_type.description = "Rewritten"
    with pytest.raises(ValidationError, match="immutable"):
        immutable_type.save()

    cross_template = PositionTemplate(
        organization=organization,
        code="cross-template",
        name="Cross template",
        version=1,
        description="Invalid role scope.",
        default_capacity_codes=["staff"],
        role_bundle=other_role,
        created_by=actor,
    )
    with pytest.raises(ValidationError, match="organization"):
        cross_template.clean()
    empty_codes = PositionTemplate(
        organization=organization,
        code="empty-codes",
        name="Empty codes",
        version=1,
        description="Missing capacity.",
        default_capacity_codes=[],
        role_bundle=template.role_bundle,
        created_by=actor,
    )
    with pytest.raises(ValidationError, match="at least one"):
        empty_codes.clean()
    empty_codes.default_capacity_codes = ["staff", "staff"]
    with pytest.raises(ValidationError, match="unique"):
        empty_codes.clean()
    empty_codes.default_capacity_codes = ["not valid"]
    with pytest.raises(ValidationError):
        empty_codes.clean()
    template.status = PositionTemplate.Status.PUBLISHED
    template.save(update_fields=("status", "updated_at"))
    template.description = "Rewritten"
    with pytest.raises(ValidationError, match="immutable"):
        template.save()

    invalid_position = Position(
        organization=organization,
        edition=other_edition,
        template=template,
        department=department,
        role_bundle=template.role_bundle,
        code="invalid-position",
        title="Invalid",
        description="Invalid",
        capacity_codes=["staff"],
        created_by=actor,
    )
    with pytest.raises(ValidationError, match="edition scope"):
        invalid_position.clean()
    invalid_position.edition = edition
    invalid_position.department = other_department
    with pytest.raises(ValidationError, match="same edition"):
        invalid_position.clean()
    invalid_position.department = department
    invalid_position.template = PositionTemplate(
        organization=other_edition.organization,
        role_bundle=other_role,
    )
    with pytest.raises(ValidationError, match="template"):
        invalid_position.clean()
    invalid_position.template = template
    invalid_position.role_bundle = other_role
    with pytest.raises(ValidationError, match="role bundle"):
        invalid_position.clean()
    invalid_position.role_bundle = template.role_bundle
    invalid_position.reports_to = invalid_position
    with pytest.raises(ValidationError, match="report to itself"):
        invalid_position.clean()
    invalid_position.reports_to = None
    invalid_position.capacity_codes = []
    with pytest.raises(ValidationError, match="at least one"):
        invalid_position.clean()
    invalid_position.capacity_codes = ["staff", "staff"]
    with pytest.raises(ValidationError, match="unique"):
        invalid_position.clean()
    invalid_position.capacity_codes = ["not valid"]
    with pytest.raises(ValidationError):
        invalid_position.clean()
    with pytest.raises(ValidationError, match="instead of being deleted"):
        position.delete()

    other_document_type = OnboardingDocumentType.objects.create(
        organization=other_edition.organization,
        edition=other_edition,
        code="other-nda",
        name="Other NDA",
        description="Other agreement",
        created_by=actor,
    )
    invalid_requirement = PositionDocumentRequirement(
        position=position,
        document_type=other_document_type,
    )
    with pytest.raises(ValidationError, match="same edition"):
        invalid_requirement.clean()
    opportunity = VolunteerOpportunity.objects.get(position=position)
    opportunity.applications_open_at = timezone.now()
    opportunity.applications_close_at = timezone.now() - timedelta(minutes=1)
    with pytest.raises(ValidationError, match="after opening"):
        opportunity.clean()

    cross_request = OnboardingDocumentRequest(
        organization=organization,
        edition=other_edition,
        document_type=other_document_type,
        account=actor,
        requested_by=actor,
        requested_at=timezone.now(),
    )
    with pytest.raises(ValidationError, match="match its edition"):
        cross_request.clean()
    cross_request.edition = edition
    with pytest.raises(ValidationError, match="same edition"):
        cross_request.clean()
    valid_request = OnboardingDocumentRequest.objects.create(
        organization=organization,
        edition=edition,
        document_type=immutable_type,
        account=actor,
        requested_by=actor,
        requested_at=timezone.now(),
    )
    with pytest.raises(ValidationError, match="retention workflow"):
        valid_request.delete()

    assignment = PositionAssignment(
        position=position,
        organization=other_edition.organization,
        edition=other_edition,
        account=actor,
        effective_from=timezone.now(),
        proposed_by=actor,
        reason="Invalid scope",
    )
    with pytest.raises(ValidationError, match="position scope"):
        assignment.clean()
    assignment.organization = organization
    assignment.edition = edition
    assignment.expires_at = assignment.effective_from
    with pytest.raises(ValidationError, match="follow activation"):
        assignment.clean()
    assignment.expires_at = None
    assignment.approved_by = actor
    with pytest.raises(ValidationError, match="different controller"):
        assignment.clean()
    assignment.approved_by = None
    assignment.status = PositionAssignment.Status.ACTIVE
    with pytest.raises(ValidationError, match="profile-matched evidence"):
        assignment.clean()
    assignment.status = PositionAssignment.Status.PROPOSED
    with pytest.raises(ValidationError, match="retained evidence"):
        assignment.delete()


def test_workforce_services_fail_closed_and_activate_proposed_assignment() -> None:  # noqa: PLR0915
    controller = AccountFactory(is_staff=True, is_superuser=True)
    chair = AccountFactory()
    person = AccountFactory()
    edition = EventEditionFactory()
    organization = edition.organization
    bootstrap_organization_workforce(
        organization=organization,
        edition=edition,
        controller=controller,
        chair=chair,
        reason="Set up service edge tests.",
        correlation_id=uuid4(),
    )
    authority_actor, authority_approver = grant_board_controllers_edition_capability(
        edition,
        "workforce.manage_assignments",
    )
    department = create_department_for_test(
        edition=edition,
        name="Registration",
        expected_code="registration",
        actor=controller,
    )
    starter_template = PositionTemplate.objects.get(
        organization=organization,
        code="registration-lead",
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
    position, position_version = _create_governed_position(
        actor=controller,
        edition=edition,
        department=department,
        template=template,
        title="Registration Lead",
        headcount=1,
    )
    opportunity = VolunteerOpportunity.objects.get(position=position)
    with pytest.raises(ValidationError, match="why this position"):
        submit_volunteer_application(
            actor=person,
            opportunity_id=opportunity.id,
            motivation="",
            correlation_id=uuid4(),
        )
    with pytest.raises(ValidationError, match="not accepting"):
        submit_volunteer_application(
            actor=person,
            opportunity_id=opportunity.id,
            motivation="I can help.",
            correlation_id=uuid4(),
        )
    published = update_position_opportunity(
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
        expected_version=position_version,
        reason="Open this governed Position to volunteer applications.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert published.resulting_version == position_version + 1
    opportunity.refresh_from_db()
    inactive = AccountFactory(is_active=False)
    with pytest.raises(ValidationError, match="not accepting"):
        submit_volunteer_application(
            actor=inactive,
            opportunity_id=opportunity.id,
            motivation="I can help.",
            correlation_id=uuid4(),
        )
    submit_volunteer_application(
        actor=person,
        opportunity_id=opportunity.id,
        motivation="I can help.",
        correlation_id=uuid4(),
    )
    with pytest.raises(IntegrityError):
        submit_volunteer_application(
            actor=person,
            opportunity_id=opportunity.id,
            motivation="Duplicate application.",
            correlation_id=uuid4(),
        )

    document_type = OnboardingDocumentType.objects.create(
        organization=organization,
        edition=edition,
        code="nda",
        name="NDA",
        description="Required agreement.",
        status=OnboardingDocumentType.Status.ACTIVE,
        created_by=controller,
    )
    document_request = OnboardingDocumentRequest.objects.create(
        organization=organization,
        edition=edition,
        document_type=document_type,
        account=person,
        requested_by=controller,
        requested_at=timezone.now(),
    )
    PositionDocumentRequirement.objects.create(
        position=position,
        document_type=document_type,
    )
    with pytest.raises(ValidationError, match="approve or reject"):
        review_onboarding_document(
            actor=chair,
            request_id=document_request.id,
            decision="unknown",
            reason="Reviewed",
            correlation_id=uuid4(),
        )
    with pytest.raises(ValidationError, match="reason"):
        review_onboarding_document(
            actor=chair,
            request_id=document_request.id,
            decision=OnboardingDocumentRequest.Status.APPROVED,
            reason="",
            correlation_id=uuid4(),
        )
    with pytest.raises(AuthorizationDenied):
        review_onboarding_document(
            actor=AccountFactory(),
            request_id=document_request.id,
            decision=OnboardingDocumentRequest.Status.APPROVED,
            reason="Unauthorized",
            correlation_id=uuid4(),
        )
    with pytest.raises(ValidationError, match="Only a submitted"):
        review_onboarding_document(
            actor=chair,
            request_id=document_request.id,
            decision=OnboardingDocumentRequest.Status.APPROVED,
            reason="Too early",
            correlation_id=uuid4(),
        )
    with pytest.raises(ValidationError, match="approved first"):
        activate_position_assignment(
            position_id=position.id,
            account=person,
            actor=authority_actor,
            approver=authority_approver,
            effective_from=timezone.now(),
            expires_at=None,
            reason="Missing NDA",
            correlation_id=uuid4(),
        )
    uploaded = upload_onboarding_document(
        actor=person,
        request_id=document_request.id,
        upload=SimpleUploadedFile(
            "nda.pdf",
            b"%PDF-1.4\nsynthetic\n%%EOF\n",
            content_type="application/pdf",
        ),
        correlation_id=uuid4(),
    )
    assert uploaded.status == OnboardingDocumentRequest.Status.SUBMITTED
    with pytest.raises(ValidationError, match="not accepting another"):
        upload_onboarding_document(
            actor=person,
            request_id=document_request.id,
            upload=SimpleUploadedFile(
                "nda-again.pdf",
                b"%PDF-1.4\nsynthetic\n%%EOF\n",
                content_type="application/pdf",
            ),
            correlation_id=uuid4(),
        )
    review_onboarding_document(
        actor=chair,
        request_id=document_request.id,
        decision=OnboardingDocumentRequest.Status.APPROVED,
        reason="Current signed agreement verified.",
        correlation_id=uuid4(),
    )

    participation = ParticipationFactory(
        account=person,
        organization=organization,
        edition=edition,
    )
    for code in ("staff", "volunteer"):
        ParticipationCapacityFactory(
            participation=participation,
            code=code,
            status=ParticipationCapacity.Status.WITHDRAWN,
        )
    proposed = save_position_assignment_for_test(
        assignment=PositionAssignment(
            position=position,
            organization=organization,
            edition=edition,
            account=person,
            effective_from=timezone.now(),
            proposed_by=controller,
            reason="Await independent approval.",
        )
    )
    with pytest.raises(ValidationError, match="reason"):
        activate_position_assignment(
            position_id=position.id,
            account=person,
            actor=controller,
            approver=chair,
            effective_from=timezone.now(),
            expires_at=None,
            reason="",
            correlation_id=uuid4(),
        )
    with pytest.raises(ValidationError, match="different controller"):
        activate_position_assignment(
            position_id=position.id,
            account=person,
            actor=authority_actor,
            approver=authority_actor,
            effective_from=timezone.now(),
            expires_at=None,
            reason="Same controller",
            correlation_id=uuid4(),
        )
    activated = activate_position_assignment(
        position_id=position.id,
        account=person,
        actor=authority_actor,
        approver=authority_approver,
        effective_from=proposed.effective_from,
        expires_at=proposed.expires_at,
        reason="Approved registration lead.",
        correlation_id=uuid4(),
        proposed_assignment_id=proposed.id,
    )
    assert activated.id == proposed.id
    assert set(
        participation.capacities.filter(
            status=ParticipationCapacity.Status.ACTIVE
        ).values_list("code", flat=True)
    ) >= {"staff", "volunteer", "position.registration-lead"}
    with pytest.raises(ValidationError, match="headcount"):
        activate_position_assignment(
            position_id=position.id,
            account=AccountFactory(),
            actor=authority_actor,
            approver=authority_approver,
            effective_from=timezone.now(),
            expires_at=None,
            reason="Position is full.",
            correlation_id=uuid4(),
        )

    closed = save_position_for_test(
        position=Position(
            organization=organization,
            edition=edition,
            template=template,
            department=department,
            role_bundle=template.role_bundle,
            code="closed-registration-role",
            title="Closed Registration Role",
            description=template.description,
            headcount=1,
            capacity_codes=["staff"],
            status=Position.Status.CLOSED,
            created_by=controller,
        )
    )
    with pytest.raises(ValidationError, match="closed position"):
        activate_position_assignment(
            position_id=closed.id,
            account=AccountFactory(),
            actor=authority_actor,
            approver=authority_approver,
            effective_from=timezone.now(),
            expires_at=None,
            reason="Closed role.",
            correlation_id=uuid4(),
        )


def test_workforce_admin_inspection_and_onboarding_review(
    settings: object,
    tmp_path: Path,
) -> None:
    settings.MEDIA_ROOT = tmp_path  # type: ignore[attr-defined]
    controller = AccountFactory(is_staff=True, is_superuser=True)
    chair = AccountFactory(is_staff=True)
    candidate = AccountFactory()
    edition = EventEditionFactory()
    organization = edition.organization
    bootstrap_organization_workforce(
        organization=organization,
        edition=edition,
        controller=controller,
        chair=chair,
        reason="Verify the organizer admin workflow.",
        correlation_id=uuid4(),
    )
    department = Department.objects.get(
        edition=edition,
        code="convention-leadership",
    )
    starter_template = PositionTemplate.objects.get(
        organization=organization,
        code="registration-lead",
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

    request = RequestFactory().post("/admin/workforce/")
    request.user = controller
    request.correlation_id = str(uuid4())  # type: ignore[attr-defined]
    position_admin = PositionAdmin(Position, admin.site)
    assert not position_admin.has_add_permission(request)
    assert not position_admin.has_change_permission(request)
    assert not position_admin.has_delete_permission(request)
    position, _position_version = _create_governed_position(
        actor=controller,
        edition=edition,
        department=department,
        template=template,
        title="Admin-rehearsal Role",
        headcount=2,
    )
    assert position.created_by == controller

    document_type = OnboardingDocumentType(
        organization=organization,
        edition=edition,
        code="admin-nda",
        name="Admin NDA",
        version=1,
        description="Agreement reviewed through the organizer admin.",
        status=OnboardingDocumentType.Status.ACTIVE,
    )
    OnboardingDocumentTypeAdmin(OnboardingDocumentType, admin.site).save_model(
        request,
        document_type,
        SimpleNamespace(),  # type: ignore[arg-type]
        change=False,
    )
    assert document_type.created_by == controller

    document_request = OnboardingDocumentRequest(
        organization=organization,
        edition=edition,
        document_type=document_type,
        account=candidate,
        instructions="Sign and upload this agreement.",
    )
    document_admin = OnboardingDocumentRequestAdmin(
        OnboardingDocumentRequest,
        admin.site,
    )
    assert document_admin.document_download(document_request) == "No document submitted"
    document_admin.save_model(
        request,
        document_request,
        SimpleNamespace(),  # type: ignore[arg-type]
        change=False,
    )
    assert document_request.requested_by == controller
    upload_onboarding_document(
        actor=candidate,
        request_id=document_request.id,
        upload=SimpleUploadedFile(
            "admin-signed-nda.pdf",
            b"%PDF-1.4\n% admin review\n%%EOF\n",
            content_type="application/pdf",
        ),
        correlation_id=uuid4(),
    )
    document_request.refresh_from_db()
    request.user = chair
    document_request.status = OnboardingDocumentRequest.Status.APPROVED
    document_request.review_reason = "Signature and version verified."
    document_admin.save_model(
        request,
        document_request,
        SimpleNamespace(),  # type: ignore[arg-type]
        change=True,
    )
    assert document_request.status == OnboardingDocumentRequest.Status.APPROVED
    document_request.status = OnboardingDocumentRequest.Status.REJECTED
    document_admin.save_model(
        request,
        document_request,
        SimpleNamespace(),  # type: ignore[arg-type]
        change=True,
    )
    assert document_request.status == OnboardingDocumentRequest.Status.APPROVED

    assignment_admin = PositionAssignmentAdmin(PositionAssignment, admin.site)
    request.user = controller
    assert assignment_admin.has_view_permission(request)
    assert not assignment_admin.has_add_permission(request)
    assert not assignment_admin.has_change_permission(request)
    assert not assignment_admin.has_delete_permission(request)
    assert position.created_by == controller
