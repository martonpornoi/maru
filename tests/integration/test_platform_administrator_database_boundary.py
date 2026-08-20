from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Event
from typing import TYPE_CHECKING

import pytest
from django.db import (
    IntegrityError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.utils import timezone

from maru.identity.models import Account
from maru.organizations.models import (
    OrganizationMembership,
    RepresentationAppointment,
)
from maru.participation.models import Participation
from maru.registration.models import (
    AttendeeFursuit,
    AttendeeRegistrationProfile,
    ConfigurationStatus,
    Registration,
)
from maru.workforce.models import (
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
    OrganizationMembershipFactory,
    OrganizationRepresentationFactory,
    ParticipationFactory,
    RegistrationConfigurationFactory,
    RepresentationAppointmentFactory,
    RoleBundleFactory,
)
from tests.workforce_helpers import create_department_for_test, save_position_for_test

if TYPE_CHECKING:
    from collections.abc import Callable

    from maru.events.models import EventEdition

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]

ORGANIZATIONS_RECLASSIFICATION_GUARD = "identity_idn011_organizations_subject_guard"
PARTICIPATION_RECLASSIFICATION_GUARD = "identity_idn011_participation_subject_guard"
REGISTRATION_RECLASSIFICATION_GUARD = "identity_idn011_registration_subject_guard"
WORKFORCE_RECLASSIFICATION_GUARD = "identity_idn011_workforce_subject_guard"


def _platform_administrator() -> Account:
    return AccountFactory(is_staff=True, is_superuser=True)


def _reclassify_as_platform_administrator(account: Account) -> None:
    Account.objects.filter(pk=account.pk).update(
        account_kind=Account.Kind.PLATFORM_ADMINISTRATOR,
        is_staff=True,
        is_superuser=True,
    )


def _force_constraint(constraint_name: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(f"SET CONSTRAINTS {constraint_name} IMMEDIATE")


def _registration_world(
    *,
    account: Account | None = None,
    staff_actor: Account | None = None,
) -> tuple[Registration, Account]:
    attendee = account or AccountFactory()
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
        reference=f"IDN-{str(attendee.id)[:8].upper()}",
        state=Registration.State.CONFIRMED,
        product_name_snapshot=product.name,
        price_minor_snapshot=product.price_minor,
        currency_snapshot=configuration.currency,
        submitted_at=timezone.now(),
        confirmed_at=timezone.now(),
        confirmation_basis=Registration.ConfirmationBasis.PROVIDER,
        submission_source=(
            Registration.SubmissionSource.STAFF_ASSISTED
            if staff_actor is not None
            else Registration.SubmissionSource.SELF
        ),
        submitted_by=staff_actor,
        staff_submission_reason=(
            "Synthetic accessibility assistance." if staff_actor is not None else ""
        ),
    )
    return registration, attendee


def _profile_values(registration: Registration) -> dict[str, object]:
    return {
        "registration": registration,
        "organization": registration.organization,
        "edition": registration.edition,
        "account": registration.account,
        "real_name": "Synthetic Attendee",
        "date_of_birth": date(1990, 1, 1),
        "address_line_1": "1 Synthetic Street",
        "locality": "Test City",
        "postal_code": "1000",
        "region": "Test Region",
        "country_code": "HU",
        "emergency_contact_name": "Synthetic Contact",
        "emergency_contact_phone": "+3610000000",
        "phone_number": "+3610000001",
        "pronoun_code": "they_them",
        "pronouns": "They/them",
        "spoken_language_codes": ["en"],
        "collection_notice_version": "synthetic-idn011-v1",
    }


def _create_profile(registration: Registration) -> AttendeeRegistrationProfile:
    return AttendeeRegistrationProfile.objects.create(**_profile_values(registration))


def _create_fursuit(profile: AttendeeRegistrationProfile) -> AttendeeFursuit:
    return AttendeeFursuit.objects.create(
        profile=profile,
        registration=profile.registration,
        organization=profile.organization,
        edition=profile.edition,
        account=profile.account,
        position=0,
        name="Synthetic Fox",
        species="Fox",
    )


def _workforce_world() -> tuple[
    EventEdition,
    Account,
    Position,
    VolunteerOpportunity,
    OnboardingDocumentType,
]:
    edition = EventEditionFactory()
    actor = AccountFactory()
    role = RoleBundleFactory(organization=edition.organization)
    department = create_department_for_test(
        edition=edition,
        name="IDN-011 Operations",
        expected_code="idn-011-operations",
    )
    template = PositionTemplate.objects.create(
        organization=edition.organization,
        code="idn011-volunteer",
        name="IDN-011 Volunteer",
        version=1,
        description="Synthetic IDN-011 boundary position.",
        default_headcount=3,
        default_capacity_codes=["volunteer"],
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
            code="idn011-volunteer",
            title="IDN-011 Volunteer",
            description=template.description,
            headcount=3,
            capacity_codes=["volunteer"],
            created_by=actor,
        )
    )
    opportunity = VolunteerOpportunity.objects.get(position=position)
    document_type = OnboardingDocumentType.objects.create(
        organization=edition.organization,
        edition=edition,
        code="idn011-agreement",
        name="IDN-011 Agreement",
        description="Synthetic agreement.",
        created_by=actor,
    )
    return edition, actor, position, opportunity, document_type


@pytest.mark.parametrize("relationship", ["membership", "appointment"])
def test_organization_bulk_create_rejects_platform_subjects(
    relationship: str,
) -> None:
    administrator = _platform_administrator()
    if relationship == "membership":
        records = [
            OrganizationMembership(
                organization=OrganizationFactory(),
                account=administrator,
                state=OrganizationMembership.State.INVITED,
            )
        ]
        writer = OrganizationMembership.objects.bulk_create
    else:
        representation = OrganizationRepresentationFactory()
        records = [
            RepresentationAppointment(
                representation=representation,
                account=administrator,
                invited_by=representation.provisioned_by,
                invited_at=timezone.now(),
                reason="Synthetic forbidden appointment.",
            )
        ]
        writer = RepresentationAppointment.objects.bulk_create

    with (
        pytest.raises(
            IntegrityError,
            match="platform accounts cannot be organization subjects",
        ),
        transaction.atomic(),
    ):
        writer(records)


def test_participation_bulk_create_rejects_platform_subject() -> None:
    administrator = _platform_administrator()
    edition = EventEditionFactory()

    with (
        pytest.raises(IntegrityError, match="cannot hold edition participation"),
        transaction.atomic(),
    ):
        Participation.objects.bulk_create(
            [
                Participation(
                    account=administrator,
                    organization=edition.organization,
                    edition=edition,
                    status=Participation.Status.PENDING,
                    edition_name_snapshot=edition.name,
                    series_name_snapshot=edition.series.name,
                )
            ]
        )


@pytest.mark.parametrize("subject_table", ["registration", "profile", "fursuit"])
def test_registration_bulk_create_rejects_platform_subject_records(
    subject_table: str,
) -> None:
    registration, attendee = _registration_world()
    profile = _create_profile(registration) if subject_table == "fursuit" else None

    def write_subject() -> None:
        with transaction.atomic():
            _reclassify_as_platform_administrator(attendee)
            if subject_table == "registration":
                Registration.objects.bulk_update([registration], ["reference"])
            elif subject_table == "profile":
                AttendeeRegistrationProfile.objects.bulk_create(
                    [AttendeeRegistrationProfile(**_profile_values(registration))]
                )
            else:
                assert profile is not None
                AttendeeFursuit.objects.bulk_create(
                    [
                        AttendeeFursuit(
                            profile=profile,
                            registration=registration,
                            organization=registration.organization,
                            edition=registration.edition,
                            account=attendee,
                            position=0,
                            name="Forbidden platform fursuit",
                        )
                    ]
                )

    with pytest.raises(
        IntegrityError,
        match="platform accounts cannot hold registration subject records",
    ):
        write_subject()


@pytest.mark.parametrize(
    "subject_table",
    ["application", "document_request", "assignment"],
)
def test_workforce_bulk_create_rejects_platform_subject_records(
    subject_table: str,
) -> None:
    edition, actor, position, opportunity, document_type = _workforce_world()
    administrator = _platform_administrator()

    if subject_table == "application":
        records = [
            VolunteerApplication(
                opportunity=opportunity,
                account=administrator,
                motivation="Synthetic forbidden application.",
                submitted_at=timezone.now(),
            )
        ]
        writer = VolunteerApplication.objects.bulk_create
    elif subject_table == "document_request":
        records = [
            OnboardingDocumentRequest(
                organization=edition.organization,
                edition=edition,
                document_type=document_type,
                account=administrator,
                requested_by=actor,
                requested_at=timezone.now(),
            )
        ]
        writer = OnboardingDocumentRequest.objects.bulk_create
    else:
        records = [
            PositionAssignment(
                position=position,
                organization=edition.organization,
                edition=edition,
                account=administrator,
                effective_from=timezone.now(),
                proposed_by=actor,
                reason="Synthetic forbidden assignment.",
            )
        ]
        writer = PositionAssignment.objects.bulk_create

    with (
        pytest.raises(
            IntegrityError,
            match="platform accounts cannot hold workforce subject records",
        ),
        transaction.atomic(),
    ):
        writer(records)


def test_raw_sql_cannot_reassign_membership_or_participation_to_platform() -> None:
    administrator = _platform_administrator()
    membership = OrganizationMembershipFactory()
    participation = ParticipationFactory()

    statements = (
        (
            "UPDATE organizations_organizationmembership "
            "SET account_id = %s WHERE id = %s",
            membership.id,
            "organization subjects",
        ),
        (
            "UPDATE participation_participation SET account_id = %s WHERE id = %s",
            participation.id,
            "edition participation",
        ),
    )
    for sql, target_id, message in statements:
        with (
            pytest.raises(IntegrityError, match=message),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(sql, [administrator.id, target_id])


@pytest.mark.parametrize("subject_table", ["registration", "profile", "fursuit"])
def test_raw_registration_subject_update_rechecks_account_kind(
    subject_table: str,
) -> None:
    registration, attendee = _registration_world()
    profile = _create_profile(registration)
    fursuit = _create_fursuit(profile)
    statements = {
        "registration": (
            "UPDATE registration_registration "
            "SET updated_at = updated_at WHERE id = %s",
            registration.id,
        ),
        "profile": (
            "UPDATE registration_attendeeregistrationprofile "
            "SET aggregate_version = aggregate_version + 1 WHERE id = %s",
            profile.id,
        ),
        "fursuit": (
            "UPDATE registration_attendeefursuit "
            "SET updated_at = updated_at WHERE id = %s",
            fursuit.id,
        ),
    }
    sql, target_id = statements[subject_table]

    def write_subject() -> None:
        with transaction.atomic(), connection.cursor() as cursor:
            _reclassify_as_platform_administrator(attendee)
            cursor.execute(sql, [target_id])

    with pytest.raises(
        IntegrityError,
        match="platform accounts cannot hold registration subject records",
    ):
        write_subject()


@pytest.mark.parametrize(
    ("builder", "constraint_name", "error_message"),
    [
        (
            lambda: OrganizationMembershipFactory().account,
            ORGANIZATIONS_RECLASSIFICATION_GUARD,
            "cannot retain organization subjects",
        ),
        (
            lambda: RepresentationAppointmentFactory().account,
            ORGANIZATIONS_RECLASSIFICATION_GUARD,
            "cannot retain organization subjects",
        ),
        (
            lambda: ParticipationFactory().account,
            PARTICIPATION_RECLASSIFICATION_GUARD,
            "cannot retain edition participation",
        ),
    ],
)
def test_account_reclassification_rejects_organization_and_participation_subjects(
    builder: Callable[[], Account],
    constraint_name: str,
    error_message: str,
) -> None:
    account = builder()

    def reclassify() -> None:
        with transaction.atomic():
            _reclassify_as_platform_administrator(account)
            _force_constraint(constraint_name)

    with pytest.raises(IntegrityError, match=error_message):
        reclassify()

    account.refresh_from_db()
    assert account.account_kind == Account.Kind.PERSON


def test_account_reclassification_rejects_complete_registration_subject_graph() -> None:
    registration, attendee = _registration_world()
    profile = _create_profile(registration)
    _create_fursuit(profile)

    def reclassify() -> None:
        with transaction.atomic():
            _reclassify_as_platform_administrator(attendee)
            _force_constraint(REGISTRATION_RECLASSIFICATION_GUARD)

    with pytest.raises(
        IntegrityError,
        match="cannot retain registration subject records",
    ):
        reclassify()

    attendee.refresh_from_db()
    assert attendee.account_kind == Account.Kind.PERSON


@pytest.mark.parametrize(
    "subject_table",
    ["application", "document_request", "assignment"],
)
def test_account_reclassification_rejects_each_workforce_subject(
    subject_table: str,
) -> None:
    edition, actor, position, opportunity, document_type = _workforce_world()
    person = AccountFactory()
    if subject_table == "application":
        VolunteerApplication.objects.create(
            opportunity=opportunity,
            account=person,
            motivation="Synthetic application.",
            submitted_at=timezone.now(),
        )
    elif subject_table == "document_request":
        OnboardingDocumentRequest.objects.create(
            organization=edition.organization,
            edition=edition,
            document_type=document_type,
            account=person,
            requested_by=actor,
            requested_at=timezone.now(),
        )
    else:
        PositionAssignment.objects.create(
            position=position,
            organization=edition.organization,
            edition=edition,
            account=person,
            effective_from=timezone.now(),
            proposed_by=actor,
            reason="Synthetic proposed assignment.",
        )

    def reclassify() -> None:
        with transaction.atomic():
            _reclassify_as_platform_administrator(person)
            _force_constraint(WORKFORCE_RECLASSIFICATION_GUARD)

    with pytest.raises(
        IntegrityError,
        match="cannot retain workforce subject records",
    ):
        reclassify()

    person.refresh_from_db()
    assert person.account_kind == Account.Kind.PERSON


def test_platform_administrator_remains_valid_as_attributed_actor() -> None:
    administrator = _platform_administrator()
    person = AccountFactory()
    registration, _ = _registration_world(
        account=person,
        staff_actor=administrator,
    )

    edition, _, position, _, document_type = _workforce_world()
    document_request = OnboardingDocumentRequest.objects.create(
        organization=edition.organization,
        edition=edition,
        document_type=document_type,
        account=person,
        requested_by=administrator,
        requested_at=timezone.now(),
    )
    assignment = PositionAssignment.objects.create(
        position=position,
        organization=edition.organization,
        edition=edition,
        account=person,
        effective_from=timezone.now(),
        proposed_by=administrator,
        reason="Synthetic attributed platform proposal.",
    )

    assert registration.submitted_by == administrator
    assert document_request.requested_by == administrator
    assert assignment.proposed_by == administrator


@pytest.mark.parametrize("operation", ["insert", "update"])
def test_subject_write_serializes_with_account_reclassification(operation: str) -> None:
    person = AccountFactory()
    organization = OrganizationFactory()
    existing = (
        OrganizationMembershipFactory(organization=organization, account=person)
        if operation == "update"
        else None
    )
    subject_locked = Event()
    release_subject = Event()
    reclassification_started = Event()

    def write_subject() -> str:
        close_old_connections()
        try:
            with transaction.atomic():
                if operation == "insert":
                    OrganizationMembership.objects.bulk_create(
                        [
                            OrganizationMembership(
                                organization_id=organization.id,
                                account_id=person.id,
                                state=OrganizationMembership.State.INVITED,
                            )
                        ]
                    )
                else:
                    assert existing is not None
                    OrganizationMembership.objects.filter(pk=existing.pk).update(
                        relationship_label="Concurrent subject update"
                    )
                subject_locked.set()
                if not release_subject.wait(timeout=10):
                    raise TimeoutError("Timed out holding the identity subject lock.")
            return "subject_committed"
        finally:
            connections.close_all()

    def reclassify() -> str:
        close_old_connections()
        try:
            if not subject_locked.wait(timeout=10):
                raise TimeoutError("Timed out waiting for the subject write.")
            reclassification_started.set()
            try:
                with transaction.atomic():
                    Account.objects.filter(pk=person.pk).update(
                        account_kind=Account.Kind.PLATFORM_ADMINISTRATOR,
                        is_staff=True,
                        is_superuser=True,
                    )
            except IntegrityError:
                return "reclassification_rejected"
            else:
                return "reclassified"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        subject_future = executor.submit(write_subject)
        reclassification_future = executor.submit(reclassify)
        assert subject_locked.wait(timeout=10)
        assert reclassification_started.wait(timeout=10)
        assert not reclassification_future.done()
        release_subject.set()
        assert subject_future.result(timeout=10) == "subject_committed"
        assert reclassification_future.result(timeout=10) == "reclassification_rejected"

    person.refresh_from_db()
    assert person.account_kind == Account.Kind.PERSON
    assert OrganizationMembership.objects.filter(
        organization=organization,
        account=person,
    ).exists()
