import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from maru.identity.models import Account
from maru.registration.models import (
    ConfigurationStatus,
    ProfileExtensionReviewStatus,
    ProfileExtensionStatus,
    ProfileExtensionWriter,
    Registration,
    RegistrationProfileExtensionField,
    RegistrationSubmission,
)
from tests.factories import (
    AccountFactory,
    AdmissionProductFactory,
    EventEditionFactory,
    ParticipationFactory,
    RegistrationConfigurationFactory,
    RegistrationTemplateFactory,
    RoleAssignmentFactory,
    RoleBundleFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _registration_world() -> tuple[Registration, Account]:
    attendee = AccountFactory(login_handle="SyntheticAttendee")
    edition = EventEditionFactory(name="Marucon 2031")
    participation = ParticipationFactory(
        account=attendee,
        organization=edition.organization,
        edition=edition,
    )
    configuration = RegistrationConfigurationFactory(edition=edition)
    product = AdmissionProductFactory(configuration=configuration)
    type(configuration).objects.filter(id=configuration.id).update(
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
        reference="MARU-EXT-001",
        state=Registration.State.CONFIRMED,
        product_name_snapshot=product.name,
        price_minor_snapshot=product.price_minor,
        currency_snapshot=configuration.currency,
        submitted_at=timezone.now(),
        confirmed_at=timezone.now(),
        confirmation_basis=Registration.ConfirmationBasis.PROVIDER,
    )
    RegistrationSubmission.objects.create(
        registration=registration,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        configuration_version=configuration.version,
        schema_snapshot=[
            {
                "key": "original",
                "label": "Original answer",
                "field_type": "short_text",
                "purpose": "Preserve the submitted snapshot.",
            }
        ],
        answers={"original": "unchanged"},
        submitted_at=registration.submitted_at,
    )
    return registration, attendee


def _field(
    registration: Registration,
    *,
    actor: Account,
    key: str,
    attendee_visible: bool,
    writer_policy: str,
    field_type: str = "short_text",
    options: list[str] | None = None,
) -> RegistrationProfileExtensionField:
    return RegistrationProfileExtensionField.objects.create(
        organization=registration.organization,
        edition=registration.edition,
        key=key,
        version=1,
        label=key.replace("-", " ").title(),
        help_text="Supply the currently missing detail.",
        field_type=field_type,
        options=options or [],
        purpose="Complete the current registration service profile.",
        attendee_visible=attendee_visible,
        writer_policy=writer_policy,
        review_status=ProfileExtensionReviewStatus.APPROVED,
        status=ProfileExtensionStatus.ACTIVE,
        created_by=actor,
        approved_by=actor,
        approved_at=timezone.now(),
    )


def test_extension_values_are_writer_scoped_append_only_and_keep_submission() -> None:
    registration, attendee = _registration_world()
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    address = _field(
        registration,
        actor=administrator,
        key="missing-address-detail",
        attendee_visible=True,
        writer_policy=ProfileExtensionWriter.ATTENDEE_AND_STAFF,
    )
    internal = _field(
        registration,
        actor=administrator,
        key="internal-id-verified",
        attendee_visible=False,
        writer_policy=ProfileExtensionWriter.REGISTRATION_STAFF,
    )
    staff = AccountFactory()
    staff_role = RoleBundleFactory(
        organization=registration.organization,
        capability_codes=[
            "registration.view_service_summary",
            "registration.register_on_behalf",
        ],
    )
    RoleAssignmentFactory(
        organization=registration.organization,
        edition=registration.edition,
        principal=staff,
        role_bundle=staff_role,
        granted_by=administrator,
    )
    self_url = (
        f"/api/v1/organizations/{registration.organization_id}/"
        f"editions/{registration.edition_id}/registrations/me/profile-extensions"
    )
    staff_url = (
        f"/api/v1/organizations/{registration.organization_id}/"
        f"editions/{registration.edition_id}/registrations/"
        f"{registration.id}/profile-extensions"
    )

    attendee_client = APIClient()
    attendee_client.force_authenticate(attendee)
    self_workspace = attendee_client.get(self_url)
    assert self_workspace.status_code == 200
    assert [item["key"] for item in self_workspace.json()["fields"]] == [
        "missing-address-detail"
    ]
    first_write = attendee_client.post(
        self_url,
        {"field_id": str(address.id), "value": "12 Example Street"},
        format="json",
    )
    assert first_write.status_code == 200
    assert first_write.json()["fields"][0]["current_value"] == "12 Example Street"
    assert (
        attendee_client.post(
            self_url,
            {"field_id": str(internal.id), "value": "yes"},
            format="json",
        ).status_code
        == 404
    )

    staff_client = APIClient()
    staff_client.force_authenticate(staff)
    staff_workspace = staff_client.get(staff_url)
    assert staff_workspace.status_code == 200
    assert {item["key"] for item in staff_workspace.json()["fields"]} == {
        "missing-address-detail",
        "internal-id-verified",
    }
    missing_reason = staff_client.post(
        staff_url,
        {"field_id": str(internal.id), "value": "verified"},
        format="json",
    )
    assert missing_reason.status_code == 400
    staff_write = staff_client.post(
        staff_url,
        {
            "field_id": str(internal.id),
            "value": "verified",
            "reason": "Checked the synthetic local rehearsal record.",
        },
        format="json",
    )
    assert staff_write.status_code == 200
    internal_payload = next(
        item
        for item in staff_write.json()["fields"]
        if item["key"] == "internal-id-verified"
    )
    assert internal_payload["current_value"] == "verified"

    submission = RegistrationSubmission.objects.get(registration=registration)
    assert submission.answers == {"original": "unchanged"}
    revision = registration.profile_extension_value_revisions.get(
        field_key="internal-id-verified"
    )
    revision.value = "rewritten"
    with pytest.raises(ValidationError, match="append-only"):
        revision.save()


def test_authoritative_infinity_ticket_cannot_become_an_extension_checkbox() -> None:
    registration, attendee = _registration_world()
    field = RegistrationProfileExtensionField(
        organization=registration.organization,
        edition=registration.edition,
        key="infinity-ticket-holder",
        version=1,
        label="Infinity ticket holder",
        field_type="boolean",
        purpose="Incorrectly duplicate an authoritative entitlement.",
        attendee_visible=False,
        writer_policy=ProfileExtensionWriter.REGISTRATION_STAFF,
        created_by=attendee,
    )

    with pytest.raises(ValidationError, match="authoritative Maru domain record"):
        field.full_clean()


def test_extension_provenance_is_reviewed_and_tenant_scoped_in_postgresql() -> None:
    registration, administrator = _registration_world()
    other_template = RegistrationTemplateFactory(
        status="published",
        published_at=timezone.now(),
    )
    field = _field(
        registration,
        actor=administrator,
        key="reviewed-source",
        attendee_visible=True,
        writer_policy=ProfileExtensionWriter.ATTENDEE_AND_STAFF,
    )

    field.source_template = other_template
    with pytest.raises(ValidationError, match="applicable published template"):
        field.full_clean()

    with pytest.raises(IntegrityError), transaction.atomic():
        RegistrationProfileExtensionField.objects.filter(id=field.id).update(
            source_template_id=other_template.id
        )


@pytest.mark.parametrize(
    ("field_type", "options", "invalid_value", "valid_value"),
    [
        ("long_text", [], "x" * 5_001, "Current arrival details"),
        ("boolean", [], "yes", True),
        ("integer", [], True, 42),
        ("single_choice", ["alpha", "beta"], "gamma", "alpha"),
        (
            "multiple_choice",
            ["alpha", "beta"],
            ["alpha", "alpha"],
            ["alpha", "beta"],
        ),
    ],
)
def test_profile_extension_types_validate_through_the_self_api(
    field_type: str,
    options: list[str],
    invalid_value: object,
    valid_value: object,
) -> None:
    registration, attendee = _registration_world()
    field = _field(
        registration,
        actor=attendee,
        key=f"typed-{field_type.replace('_', '-')}",
        attendee_visible=True,
        writer_policy=ProfileExtensionWriter.ATTENDEE,
        field_type=field_type,
        options=options,
    )
    url = (
        f"/api/v1/organizations/{registration.organization_id}/"
        f"editions/{registration.edition_id}/registrations/me/profile-extensions"
    )
    client = APIClient()
    client.force_authenticate(attendee)

    invalid = client.post(
        url,
        {"field_id": str(field.id), "value": invalid_value},
        format="json",
    )
    valid = client.post(
        url,
        {"field_id": str(field.id), "value": valid_value},
        format="json",
    )

    assert invalid.status_code == 400
    assert valid.status_code == 200
    assert valid.json()["fields"][0]["current_value"] == valid_value
