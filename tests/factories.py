"""Synthetic factories shared by integration and workflow tests."""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from uuid import uuid4

import factory
from django.utils import timezone

from maru.authorization.models import CapabilityGrant, RoleAssignment, RoleBundle
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import (
    ConventionSeries,
    Organization,
    OrganizationMembership,
    OrganizationRepresentation,
    RepresentationAppointment,
)
from maru.participation.models import Participation, ParticipationCapacity
from maru.registration.models import (
    AdmissionProduct,
    RegistrationConfiguration,
    RegistrationQuestion,
    RegistrationTemplate,
)


class AccountFactory(factory.django.DjangoModelFactory[Account]):
    class Meta:
        model = Account

    email = factory.Sequence(lambda number: f"person-{number}@example.invalid")
    display_name = factory.Faker("name")
    preferred_language = "en"
    password = "synthetic-password"
    email_verified_at = factory.LazyFunction(timezone.now)

    @classmethod
    def _create(
        cls,
        model_class: type[Account],
        *args: Any,
        **kwargs: Any,
    ) -> Account:
        if kwargs.get("is_superuser") and "account_kind" not in kwargs:
            kwargs["account_kind"] = Account.Kind.PLATFORM_ADMINISTRATOR
        return model_class.objects.create_user(*args, **kwargs)


class OrganizationFactory(factory.django.DjangoModelFactory[Organization]):
    class Meta:
        model = Organization

    slug = factory.Sequence(lambda number: f"organizer-{number}")
    name = factory.Sequence(lambda number: f"Synthetic Organizer {number}")
    lifecycle = Organization.Lifecycle.ACTIVE
    default_language_codes = factory.LazyFunction(lambda: ["en"])
    default_time_zone = "Europe/Budapest"


class ConventionSeriesFactory(factory.django.DjangoModelFactory[ConventionSeries]):
    class Meta:
        model = ConventionSeries

    organization = factory.SubFactory(OrganizationFactory)
    slug = factory.Sequence(lambda number: f"convention-{number}")
    name = factory.Sequence(lambda number: f"Synthetic Convention {number}")


class EventEditionFactory(factory.django.DjangoModelFactory[EventEdition]):
    class Meta:
        model = EventEdition

    organization = factory.SelfAttribute("series.organization")
    series = factory.SubFactory(ConventionSeriesFactory)
    slug = factory.Sequence(lambda number: f"edition-{number}")
    name = factory.Sequence(lambda number: f"Synthetic Convention {2030 + number}")
    time_zone = "Europe/Budapest"
    language_codes = factory.LazyFunction(lambda: ["en"])
    currency_codes = factory.LazyFunction(lambda: ["EUR"])
    starts_on = date(2030, 8, 1)
    ends_on = date(2030, 8, 4)


class OrganizationMembershipFactory(
    factory.django.DjangoModelFactory[OrganizationMembership]
):
    class Meta:
        model = OrganizationMembership

    organization = factory.SubFactory(OrganizationFactory)
    account = factory.SubFactory(AccountFactory)
    state = OrganizationMembership.State.ACTIVE
    relationship_label = "Staff"


class OrganizationRepresentationFactory(
    factory.django.DjangoModelFactory[OrganizationRepresentation]
):
    class Meta:
        model = OrganizationRepresentation

    organization = factory.SubFactory(
        OrganizationFactory,
        lifecycle=Organization.Lifecycle.DRAFT,
    )
    provisioning_reason = "Synthetic Executive Board provisioning."
    provisioned_by = factory.SubFactory(
        AccountFactory,
        is_staff=True,
        is_superuser=True,
    )


class RepresentationAppointmentFactory(
    factory.django.DjangoModelFactory[RepresentationAppointment]
):
    class Meta:
        model = RepresentationAppointment

    representation = factory.SubFactory(OrganizationRepresentationFactory)
    account = factory.SubFactory(AccountFactory)
    invited_by = factory.LazyAttribute(
        lambda appointment: appointment.representation.provisioned_by
    )
    invited_at = factory.LazyFunction(timezone.now)
    reason = "Synthetic Executive Board invitation."


class ParticipationFactory(factory.django.DjangoModelFactory[Participation]):
    class Meta:
        model = Participation

    account = factory.SubFactory(AccountFactory)
    edition = factory.SubFactory(EventEditionFactory)
    organization = factory.SelfAttribute("edition.organization")
    status = Participation.Status.CONFIRMED
    edition_name_snapshot = ""
    series_name_snapshot = ""


class ParticipationCapacityFactory(
    factory.django.DjangoModelFactory[ParticipationCapacity]
):
    class Meta:
        model = ParticipationCapacity

    participation = factory.SubFactory(ParticipationFactory)
    code = factory.Sequence(lambda number: f"volunteer-{number}")
    label_snapshot = "Volunteer"
    status = ParticipationCapacity.Status.ACTIVE


class CapabilityGrantFactory(factory.django.DjangoModelFactory[CapabilityGrant]):
    class Meta:
        model = CapabilityGrant

    organization = factory.SubFactory(OrganizationFactory)
    edition = None
    principal = factory.SubFactory(AccountFactory)
    capability_code = "events.view_basic"
    effective_from = factory.LazyFunction(timezone.now)
    granted_by = factory.SubFactory(AccountFactory)
    reason = "Synthetic test grant."


class RoleBundleFactory(factory.django.DjangoModelFactory[RoleBundle]):
    class Meta:
        model = RoleBundle

    organization = factory.SubFactory(OrganizationFactory)
    code = factory.Sequence(lambda number: f"event-reader-{number}")
    name = "Event reader"
    version = 1
    capability_codes = factory.LazyFunction(lambda: ["events.view_basic"])


class RoleAssignmentFactory(factory.django.DjangoModelFactory[RoleAssignment]):
    class Meta:
        model = RoleAssignment

    organization = factory.SelfAttribute("role_bundle.organization")
    edition = None
    principal = factory.SubFactory(AccountFactory)
    role_bundle = factory.SubFactory(RoleBundleFactory)
    effective_from = factory.LazyFunction(timezone.now)
    granted_by = factory.SubFactory(AccountFactory)
    reason = "Synthetic role assignment."


class RegistrationTemplateFactory(
    factory.django.DjangoModelFactory[RegistrationTemplate]
):
    class Meta:
        model = RegistrationTemplate

    organization = factory.SubFactory(OrganizationFactory)
    series = None
    code = factory.Sequence(lambda number: f"registration-template-{number}")
    name = factory.Sequence(lambda number: f"Registration template {number}")
    version = 1
    created_by_id = factory.LazyFunction(uuid4)


class RegistrationConfigurationFactory(
    factory.django.DjangoModelFactory[RegistrationConfiguration]
):
    class Meta:
        model = RegistrationConfiguration

    organization = factory.SelfAttribute("edition.organization")
    edition = factory.SubFactory(EventEditionFactory)
    name = "Synthetic attendee registration"
    version = 1
    opens_at = factory.LazyFunction(lambda: timezone.now() - timedelta(days=1))
    closes_at = factory.LazyFunction(lambda: timezone.now() + timedelta(days=30))
    capacity = 100
    currency = "EUR"
    created_by_id = factory.LazyFunction(uuid4)


class RegistrationQuestionFactory(
    factory.django.DjangoModelFactory[RegistrationQuestion]
):
    class Meta:
        model = RegistrationQuestion

    configuration = factory.SubFactory(RegistrationConfigurationFactory)
    key = factory.Sequence(lambda number: f"question-{number}")
    label = "Synthetic question"
    field_type = "short_text"
    required = True
    position = 10
    purpose = "Exercise the synthetic registration workflow."


class AdmissionProductFactory(factory.django.DjangoModelFactory[AdmissionProduct]):
    class Meta:
        model = AdmissionProduct

    configuration = factory.SubFactory(RegistrationConfigurationFactory)
    code = factory.Sequence(lambda number: f"admission-{number}")
    name = "Weekend admission"
    price_minor = 10_000
    capacity = 100
    position = 10
    entitlement_code = "event-admission"
    entitlement_name = "Event admission"


@dataclass(frozen=True)
class ReferenceConvention:
    primary_account: Account
    other_account: Account
    primary_organization: Organization
    other_organization: Organization
    current_edition: EventEdition
    other_edition: EventEdition


def create_reference_convention() -> ReferenceConvention:
    primary_account = AccountFactory(
        email="alex.fox@example.invalid",
        display_name="Alex Fox",
    )
    other_account = AccountFactory(
        email="river.wolf@example.invalid",
        display_name="River Wolf",
    )
    primary_organization = OrganizationFactory(
        slug="northstar-events",
        name="Northstar Events",
    )
    other_organization = OrganizationFactory(
        slug="moonrise-community",
        name="Moonrise Community",
    )
    primary_series = ConventionSeriesFactory(
        organization=primary_organization,
        slug="pawprint",
        name="Pawprint Convention",
    )
    other_series = ConventionSeriesFactory(
        organization=other_organization,
        slug="moonrise",
        name="Moonrise Gathering",
    )
    current_edition = EventEditionFactory(
        organization=primary_organization,
        series=primary_series,
        slug="pawprint-2030",
        name="Pawprint Convention 2030",
    )
    other_edition = EventEditionFactory(
        organization=other_organization,
        series=other_series,
        slug="moonrise-2030",
        name="Moonrise Gathering 2030",
    )
    OrganizationMembershipFactory(
        account=primary_account,
        organization=primary_organization,
        relationship_label="Operations volunteer",
    )
    OrganizationMembershipFactory(
        account=other_account,
        organization=other_organization,
        relationship_label="Director",
    )
    ParticipationCapacityFactory(
        participation=ParticipationFactory(
            account=primary_account,
            organization=primary_organization,
            edition=current_edition,
        ),
        code="volunteer",
        label_snapshot="Volunteer",
    )
    ParticipationCapacityFactory(
        participation=ParticipationFactory(
            account=other_account,
            organization=other_organization,
            edition=other_edition,
        ),
        code="director",
        label_snapshot="Director",
    )
    return ReferenceConvention(
        primary_account=primary_account,
        other_account=other_account,
        primary_organization=primary_organization,
        other_organization=other_organization,
        current_edition=current_edition,
        other_edition=other_edition,
    )
