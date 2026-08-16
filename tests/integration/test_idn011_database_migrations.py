from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from django.db import IntegrityError, connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from maru.identity.models import Account
from maru.organizations.representation import (
    invite_representation_controller,
    provision_executive_board,
    respond_to_representation_invitation,
)
from maru.participation.models import Participation
from tests.factories import (
    AccountFactory,
    EventEditionFactory,
    OrganizationFactory,
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


def _restore_person(account_id: UUID) -> None:
    Account.objects.filter(pk=account_id).update(
        account_kind=Account.Kind.PERSON,
        is_staff=False,
        is_superuser=False,
    )


def _registration_graph(
    apps: Any,
    *,
    attendee_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    edition_name: str,
    series_name: str,
) -> None:
    participation_model = apps.get_model("participation", "Participation")
    configuration_model = apps.get_model("registration", "RegistrationConfiguration")
    product_model = apps.get_model("registration", "AdmissionProduct")
    registration_model = apps.get_model("registration", "Registration")
    profile_model = apps.get_model("registration", "AttendeeRegistrationProfile")
    fursuit_model = apps.get_model("registration", "AttendeeFursuit")
    now = timezone.now()
    participation = participation_model.objects.create(
        account_id=attendee_id,
        organization_id=organization_id,
        edition_id=edition_id,
        status="interested",
        edition_name_snapshot=edition_name,
        series_name_snapshot=series_name,
    )
    configuration = configuration_model.objects.create(
        organization_id=organization_id,
        edition_id=edition_id,
        name="Synthetic attendee registration",
        version=1,
        status="draft",
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=30),
        capacity=100,
        currency="EUR",
        created_by_id=uuid4(),
    )
    product = product_model.objects.create(
        configuration_id=configuration.id,
        code="admission-idn-migration",
        name="Weekend admission",
        description="",
        price_minor=10_000,
        capacity=100,
        position=10,
        entitlement_code="event-admission",
        entitlement_name="Event admission",
    )
    configuration_model.objects.filter(pk=configuration.pk).update(
        status="active",
        activated_at=now,
    )
    registration = registration_model.objects.create(
        organization_id=organization_id,
        edition_id=edition_id,
        participation_id=participation.id,
        account_id=attendee_id,
        configuration_id=configuration.id,
        product_id=product.id,
        reference="IDN-MIGRATION",
        state="confirmed",
        product_name_snapshot=product.name,
        price_minor_snapshot=product.price_minor,
        currency_snapshot=configuration.currency,
        submitted_at=now,
        confirmed_at=now,
        confirmation_basis="provider",
    )
    profile = profile_model.objects.create(
        registration_id=registration.id,
        organization_id=organization_id,
        edition_id=edition_id,
        account_id=attendee_id,
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
    fursuit_model.objects.create(
        profile_id=profile.id,
        registration_id=registration.id,
        organization_id=organization_id,
        edition_id=edition_id,
        account_id=attendee_id,
        position=0,
        name="Migration Fox",
    )


def _workforce_parents(
    apps: Any,
    *,
    organization_id: UUID,
    edition_id: UUID,
    actor_id: UUID,
    role_bundle_id: UUID,
) -> tuple[Any, Any, Any]:
    department_model = apps.get_model("workforce", "Department")
    position_template_model = apps.get_model("workforce", "PositionTemplate")
    position_model = apps.get_model("workforce", "Position")
    opportunity_model = apps.get_model("workforce", "VolunteerOpportunity")
    document_type_model = apps.get_model("workforce", "OnboardingDocumentType")
    department = department_model.objects.create(
        organization_id=organization_id,
        edition_id=edition_id,
        code="migration-operations",
        name="Migration Operations",
    )
    template = position_template_model.objects.create(
        organization_id=organization_id,
        code="migration-volunteer",
        name="Migration Volunteer",
        version=1,
        description="Synthetic migration position.",
        default_headcount=2,
        default_capacity_codes=["volunteer"],
        role_bundle_id=role_bundle_id,
        created_by_id=actor_id,
    )
    position = position_model.objects.create(
        organization_id=organization_id,
        edition_id=edition_id,
        template_id=template.id,
        department_id=department.id,
        role_bundle_id=role_bundle_id,
        code="migration-volunteer",
        title="Migration Volunteer",
        description=template.description,
        headcount=2,
        capacity_codes=["volunteer"],
        created_by_id=actor_id,
    )
    opportunity = opportunity_model.objects.create(
        position_id=position.id,
        headline=position.title,
        description=position.description,
    )
    document_type = document_type_model.objects.create(
        organization_id=organization_id,
        edition_id=edition_id,
        code="migration-agreement",
        name="Migration Agreement",
        description="Synthetic migration agreement.",
        created_by_id=actor_id,
    )
    return position, opportunity, document_type


def test_organization_preflight_rejects_all_legacy_subjects() -> None:
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
    person_id = person.id
    _migrate(ORGANIZATIONS_BEFORE)
    Account.objects.filter(pk=person_id).update(
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
        _restore_person(person_id)
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
    attendee = AccountFactory()
    edition = EventEditionFactory()
    attendee_id = attendee.id
    executor = _migrate(REGISTRATION_BEFORE, PARTICIPATION_BEFORE)
    historical_apps = executor.loader.project_state(
        [REGISTRATION_BEFORE, PARTICIPATION_BEFORE]
    ).apps
    _registration_graph(
        historical_apps,
        attendee_id=attendee_id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        edition_name=edition.name,
        series_name=edition.series.name,
    )
    Account.objects.filter(pk=attendee_id).update(
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
        _restore_person(attendee_id)
        _migrate(REGISTRATION_AFTER, PARTICIPATION_AFTER)


def test_workforce_preflight_rejects_every_legacy_platform_subject_table() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    role = RoleBundleFactory(organization=edition.organization)
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization_id = edition.organization_id
    edition_id = edition.id
    actor_id = actor.id
    role_bundle_id = role.id
    administrator_id = administrator.id

    executor = _migrate(WORKFORCE_BEFORE)
    historical_apps = executor.loader.project_state([WORKFORCE_BEFORE]).apps
    position, opportunity, document_type = _workforce_parents(
        historical_apps,
        organization_id=organization_id,
        edition_id=edition_id,
        actor_id=actor_id,
        role_bundle_id=role_bundle_id,
    )
    application_model = historical_apps.get_model("workforce", "VolunteerApplication")
    document_request_model = historical_apps.get_model(
        "workforce", "OnboardingDocumentRequest"
    )
    assignment_model = historical_apps.get_model("workforce", "PositionAssignment")
    application_model.objects.bulk_create(
        [
            application_model(
                opportunity_id=opportunity.id,
                account_id=administrator_id,
                motivation="Synthetic legacy application.",
                submitted_at=timezone.now(),
            )
        ]
    )
    document_request_model.objects.bulk_create(
        [
            document_request_model(
                organization_id=organization_id,
                edition_id=edition_id,
                document_type_id=document_type.id,
                account_id=administrator_id,
                requested_by_id=actor_id,
                requested_at=timezone.now(),
            )
        ]
    )
    assignment_model.objects.bulk_create(
        [
            assignment_model(
                position_id=position.id,
                organization_id=organization_id,
                edition_id=edition_id,
                account_id=administrator_id,
                effective_from=timezone.now(),
                proposed_by_id=actor_id,
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
        _restore_person(administrator_id)
        _migrate(WORKFORCE_AFTER)
