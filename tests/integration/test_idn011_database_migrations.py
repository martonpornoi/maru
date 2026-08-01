from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from django.db import IntegrityError, connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.representation import (
    invite_representation_controller,
    provision_executive_board,
    respond_to_representation_invitation,
)
from maru.participation.models import Participation
from maru.registration.models import (
    AttendeeFursuit,
    AttendeeRegistrationProfile,
    ConfigurationStatus,
    Registration,
)
from maru.workforce.models import (
    Department,
    OnboardingDocumentRequest,
    OnboardingDocumentType,
    Position,
    PositionAssignment,
    PositionTemplate,
    VolunteerApplication,
    VolunteerOpportunity,
)
from tests.factories import (
    AccountFactory,
    AdmissionProductFactory,
    EventEditionFactory,
    OrganizationFactory,
    ParticipationFactory,
    RegistrationConfigurationFactory,
    RoleBundleFactory,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("restores_current_migration_graph"),
]

ORGANIZATIONS_BEFORE = (
    "organizations",
    "0011_emergency_controller_removal_integrity",
)
ORGANIZATIONS_AFTER = (
    "organizations",
    "0012_idn011_convention_subject_guards",
)
PARTICIPATION_BEFORE = (
    "participation",
    "0003_alter_participationcapacity_options",
)
PARTICIPATION_AFTER = (
    "participation",
    "0004_idn011_convention_subject_guards",
)
REGISTRATION_BEFORE = (
    "registration",
    "0030_profile_extension_provenance_guard",
)
REGISTRATION_AFTER = (
    "registration",
    "0031_idn011_convention_subject_guards",
)
WORKFORCE_BEFORE = ("workforce", "0002_integrity_guards")
WORKFORCE_AFTER = ("workforce", "0003_idn011_convention_subject_guards")


def _migrate(*targets: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate(list(targets))
    return executor


def _restore_person(account: Account) -> None:
    Account.objects.filter(pk=account.pk).update(
        account_kind=Account.Kind.PERSON,
        is_staff=False,
        is_superuser=False,
    )


def _registration_graph() -> tuple[
    Registration,
    AttendeeRegistrationProfile,
    AttendeeFursuit,
    Account,
]:
    attendee = AccountFactory()
    edition = EventEditionFactory()
    participation = ParticipationFactory(
        account=attendee,
        organization=edition.organization,
        edition=edition,
    )
    configuration = RegistrationConfigurationFactory(edition=edition)
    product = AdmissionProductFactory(configuration=configuration)
    type(configuration).objects.filter(pk=configuration.pk).update(
        status=ConfigurationStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    configuration.refresh_from_db()
    registration = Registration.objects.create(
        organization=edition.organization,
        edition=edition,
        participation=participation,
        account=attendee,
        configuration=configuration,
        product=product,
        reference="IDN-MIGRATION",
        state=Registration.State.CONFIRMED,
        product_name_snapshot=product.name,
        price_minor_snapshot=product.price_minor,
        currency_snapshot=configuration.currency,
        submitted_at=timezone.now(),
        confirmed_at=timezone.now(),
        confirmation_basis=Registration.ConfirmationBasis.PROVIDER,
    )
    profile = AttendeeRegistrationProfile.objects.create(
        registration=registration,
        organization=edition.organization,
        edition=edition,
        account=attendee,
        real_name="Synthetic Migration Attendee",
        date_of_birth=date(1990, 1, 1),
        address_line_1="1 Migration Street",
        locality="Test City",
        postal_code="1000",
        region="Test Region",
        country_code="HU",
        emergency_contact_name="Synthetic Contact",
        emergency_contact_phone="+3610000000",
        phone_number="+3610000001",
        pronoun_code="they_them",
        pronouns="They/them",
        spoken_language_codes=["en"],
        collection_notice_version="synthetic-idn011-v1",
    )
    fursuit = AttendeeFursuit.objects.create(
        profile=profile,
        registration=registration,
        organization=edition.organization,
        edition=edition,
        account=attendee,
        position=0,
        name="Migration Fox",
    )
    return registration, profile, fursuit, attendee


def _workforce_parents() -> tuple[
    EventEdition,
    Account,
    Position,
    VolunteerOpportunity,
    OnboardingDocumentType,
]:
    edition = EventEditionFactory()
    actor = AccountFactory()
    role = RoleBundleFactory(organization=edition.organization)
    department = Department.objects.create(
        organization=edition.organization,
        edition=edition,
        code="migration-operations",
        name="Migration Operations",
    )
    template = PositionTemplate.objects.create(
        organization=edition.organization,
        code="migration-volunteer",
        name="Migration Volunteer",
        version=1,
        description="Synthetic migration position.",
        default_headcount=2,
        default_capacity_codes=["volunteer"],
        role_bundle=role,
        created_by=actor,
    )
    position = Position.objects.create(
        organization=edition.organization,
        edition=edition,
        template=template,
        department=department,
        role_bundle=role,
        code="migration-volunteer",
        title="Migration Volunteer",
        description=template.description,
        headcount=2,
        capacity_codes=["volunteer"],
        created_by=actor,
    )
    document_type = OnboardingDocumentType.objects.create(
        organization=edition.organization,
        edition=edition,
        code="migration-agreement",
        name="Migration Agreement",
        description="Synthetic migration agreement.",
        created_by=actor,
    )
    return (
        edition,
        actor,
        position,
        VolunteerOpportunity.objects.get(position=position),
        document_type,
    )


def test_organization_preflight_rejects_all_legacy_subjects() -> None:
    _migrate(ORGANIZATIONS_BEFORE)
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    person = AccountFactory()
    organization = OrganizationFactory(lifecycle="draft")
    representation = provision_executive_board(
        actor=administrator,
        organization_id=organization.id,
        reason="Synthetic migration preflight setup.",
        correlation_id=uuid4(),
    )
    appointment = invite_representation_controller(
        actor=administrator,
        representation_id=representation.id,
        account_id=person.id,
        reason="Synthetic migration preflight invitation.",
        correlation_id=uuid4(),
    )
    respond_to_representation_invitation(
        actor=person,
        appointment_id=appointment.id,
        expected_version=appointment.invitation_version,
        accept=False,
        correlation_id=uuid4(),
    )
    Account.objects.filter(pk=person.pk).update(
        account_kind=Account.Kind.PLATFORM_ADMINISTRATOR,
        is_staff=True,
        is_superuser=True,
    )

    try:
        with pytest.raises(
            IntegrityError,
            match="memberships 1, appointments 1",
        ):
            _migrate(ORGANIZATIONS_AFTER)
    finally:
        _restore_person(person)
        _migrate(ORGANIZATIONS_AFTER)


def test_participation_preflight_rejects_legacy_platform_subject() -> None:
    _migrate(PARTICIPATION_BEFORE)
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    edition = EventEditionFactory()
    participation = Participation(
        account=administrator,
        organization=edition.organization,
        edition=edition,
        status=Participation.Status.PENDING,
        edition_name_snapshot=edition.name,
        series_name_snapshot=edition.series.name,
    )
    Participation.objects.bulk_create([participation])

    try:
        with pytest.raises(IntegrityError, match="participations 1"):
            _migrate(PARTICIPATION_AFTER)
    finally:
        Participation.objects.filter(pk=participation.pk).delete()
        _migrate(PARTICIPATION_AFTER)


def test_registration_preflight_rejects_complete_legacy_platform_subject_graph() -> (
    None
):
    _migrate(REGISTRATION_BEFORE, PARTICIPATION_BEFORE)
    _, _, _, attendee = _registration_graph()
    Account.objects.filter(pk=attendee.pk).update(
        account_kind=Account.Kind.PLATFORM_ADMINISTRATOR,
        is_staff=True,
        is_superuser=True,
    )

    try:
        with pytest.raises(
            IntegrityError,
            match="registrations 1, profiles 1, fursuits 1",
        ):
            _migrate(REGISTRATION_AFTER, PARTICIPATION_BEFORE)
    finally:
        _restore_person(attendee)
        _migrate(REGISTRATION_AFTER, PARTICIPATION_AFTER)


def test_workforce_preflight_rejects_every_legacy_platform_subject_table() -> None:
    _migrate(WORKFORCE_BEFORE)
    edition, actor, position, opportunity, document_type = _workforce_parents()
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    VolunteerApplication.objects.bulk_create(
        [
            VolunteerApplication(
                opportunity=opportunity,
                account=administrator,
                motivation="Synthetic legacy application.",
                submitted_at=timezone.now(),
            )
        ]
    )
    OnboardingDocumentRequest.objects.bulk_create(
        [
            OnboardingDocumentRequest(
                organization=edition.organization,
                edition=edition,
                document_type=document_type,
                account=administrator,
                requested_by=actor,
                requested_at=timezone.now(),
            )
        ]
    )
    PositionAssignment.objects.bulk_create(
        [
            PositionAssignment(
                position=position,
                organization=edition.organization,
                edition=edition,
                account=administrator,
                effective_from=timezone.now(),
                proposed_by=actor,
                reason="Synthetic legacy assignment.",
            )
        ]
    )

    try:
        with pytest.raises(
            IntegrityError,
            match="applications 1, onboarding 1, assignments 1",
        ):
            _migrate(WORKFORCE_AFTER)
    finally:
        _restore_person(administrator)
        _migrate(WORKFORCE_AFTER)
