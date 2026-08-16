from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse
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
        # The database owns the strict no-future-evidence boundary. Keep
        # fixtures clearly in the past so host/database clock skew cannot make
        # a legitimate historical approval appear future-dated.
        approved_at=timezone.now() - timezone.timedelta(minutes=1),
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
            "registration.view_profile_extensions",
            "registration.update_profile_extensions",
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
        {
            "field_id": str(address.id),
            "value": "12 Example Street",
            "expected_sequence": 0,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert first_write.status_code == 200
    assert first_write.json()["fields"][0]["current_value"] == "12 Example Street"
    assert first_write.json()["fields"][0]["current_sequence"] == 1
    assert first_write.headers["Idempotent-Replay"] == "false"
    assert (
        attendee_client.post(
            self_url,
            {
                "field_id": str(internal.id),
                "value": "yes",
                "expected_sequence": 0,
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        ).status_code
        == 404
    )

    staff_client = APIClient()
    staff_client.force_authenticate(staff)
    staff_workspace = staff_client.get(staff_url)
    assert staff_workspace.status_code == 200
    assert {item["key"] for item in staff_workspace.json()["fields"]} == {
        "internal-id-verified",
    }
    missing_reason = staff_client.post(
        staff_url,
        {
            "field_id": str(internal.id),
            "value": "verified",
            "expected_sequence": 0,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert missing_reason.status_code == 400
    staff_write = staff_client.post(
        staff_url,
        {
            "field_id": str(internal.id),
            "value": "verified",
            "expected_sequence": 0,
            "reason": "Checked the synthetic local rehearsal record.",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
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


def test_profile_extension_write_rejects_unknown_scope_and_evidence_fields() -> None:
    registration, attendee = _registration_world()
    field = _field(
        registration,
        actor=attendee,
        key="strict-current-detail",
        attendee_visible=True,
        writer_policy=ProfileExtensionWriter.ATTENDEE,
    )
    client = APIClient()
    client.force_authenticate(attendee)
    url = (
        f"/api/v1/organizations/{registration.organization_id}/"
        f"editions/{registration.edition_id}/registrations/me/profile-extensions"
    )

    response = client.post(
        url,
        {
            "field_id": str(field.id),
            "value": "Synthetic current detail",
            "expected_sequence": 0,
            "account_id": str(attendee.id),
            "field_key": field.key,
            "actor_id": str(attendee.id),
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )

    assert response.status_code == 400
    assert set(response.json()["errors"]) >= {
        "account_id",
        "field_key",
        "actor_id",
    }
    assert not registration.profile_extension_value_revisions.exists()


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

    invalid_source = RegistrationProfileExtensionField(
        organization=registration.organization,
        edition=registration.edition,
        key="foreign-source",
        version=1,
        label="Foreign source",
        help_text="Reject a source from another organization.",
        field_type="short_text",
        purpose="Exercise exact source scope.",
        attendee_visible=True,
        writer_policy=ProfileExtensionWriter.ATTENDEE_AND_STAFF,
        source_template=other_template,
        created_by=administrator,
    )
    with pytest.raises(ValidationError, match="applicable published template"):
        invalid_source.full_clean()

    with (
        pytest.raises(IntegrityError, match="source binding is immutable"),
        transaction.atomic(),
    ):
        RegistrationProfileExtensionField.objects.filter(id=field.id).update(
            source_template_id=other_template.id
        )


@pytest.mark.parametrize(
    ("field_type", "options", "invalid_value", "valid_value"),
    [
        ("long_text", [], "x" * 5_001, "Current arrival details"),
        ("boolean", [], "yes", True),
        ("integer", [], True, 42),
        ("integer", [], 2**31, -(2**31)),
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
        {
            "field_id": str(field.id),
            "value": invalid_value,
            "expected_sequence": 0,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    valid = client.post(
        url,
        {
            "field_id": str(field.id),
            "value": valid_value,
            "expected_sequence": 0,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )

    assert invalid.status_code == 400
    assert valid.status_code == 200
    assert valid.json()["fields"][0]["current_value"] == valid_value


def test_profile_extension_api_requires_canonical_idempotency_and_sequences() -> None:
    registration, attendee = _registration_world()
    field = _field(
        registration,
        actor=attendee,
        key="sequenced-current-detail",
        attendee_visible=True,
        writer_policy=ProfileExtensionWriter.ATTENDEE,
    )
    url = (
        f"/api/v1/organizations/{registration.organization_id}/"
        f"editions/{registration.edition_id}/registrations/me/profile-extensions"
    )
    client = APIClient()
    client.force_authenticate(attendee)
    body = {
        "field_id": str(field.id),
        "value": "First exact value",
        "expected_sequence": 0,
    }

    missing = client.post(url, body, format="json")
    malformed = client.post(
        url,
        body,
        format="json",
        HTTP_IDEMPOTENCY_KEY=" NOT-A-CANONICAL-UUID ",
    )
    assert missing.status_code == 400
    assert malformed.status_code == 400
    assert "Idempotency-Key" in missing.json()["errors"]
    assert "Idempotency-Key" in malformed.json()["errors"]
    assert not registration.profile_extension_value_revisions.exists()

    retry_key = uuid4()
    created = client.post(
        url,
        body,
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(retry_key),
    )
    replay = client.post(
        url,
        body,
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(retry_key),
    )
    changed_retry = client.post(
        url,
        {**body, "value": "Changed retry intent"},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(retry_key),
    )
    stale_sequence = client.post(
        url,
        {**body, "value": "Second value"},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    advanced = client.post(
        url,
        {
            **body,
            "value": "Second exact value",
            "expected_sequence": 1,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )

    assert created.status_code == 200
    assert created.headers["Idempotent-Replay"] == "false"
    assert replay.status_code == 200
    assert replay.headers["Idempotent-Replay"] == "true"
    assert replay.json()["snapshot_digest"] == created.json()["snapshot_digest"]
    assert changed_retry.status_code == 409
    assert stale_sequence.status_code == 409
    assert advanced.status_code == 200
    assert advanced.json()["snapshot_digest"] != created.json()["snapshot_digest"]
    assert advanced.json()["fields"][0]["current_sequence"] == 2
    assert registration.profile_extension_value_revisions.count() == 2


def test_staff_write_rolls_back_when_the_workspace_read_is_not_authorized() -> None:
    registration, _attendee = _registration_world()
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    field = _field(
        registration,
        actor=administrator,
        key="staff-atomic-current-detail",
        attendee_visible=False,
        writer_policy=ProfileExtensionWriter.REGISTRATION_STAFF,
    )
    staff = AccountFactory()
    update_only_role = RoleBundleFactory(
        organization=registration.organization,
        capability_codes=["registration.update_profile_extensions"],
    )
    RoleAssignmentFactory(
        organization=registration.organization,
        edition=registration.edition,
        principal=staff,
        role_bundle=update_only_role,
        granted_by=administrator,
    )
    url = (
        f"/api/v1/organizations/{registration.organization_id}/"
        f"editions/{registration.edition_id}/registrations/"
        f"{registration.id}/profile-extensions"
    )
    client = APIClient()
    client.force_authenticate(staff)

    response = client.post(
        url,
        {
            "field_id": str(field.id),
            "value": "Synthetic staff-only detail",
            "expected_sequence": 0,
            "reason": "Exercise response authorization rollback.",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )

    assert response.status_code == 404
    assert not registration.profile_extension_value_revisions.exists()
    assert not registration.profile_extension_value_controls.exists()
    assert not registration.profile_extension_value_command_receipts.exists()


def test_profile_extension_openapi_declares_closed_sequence_contract() -> None:
    client = APIClient()
    client.force_authenticate(AccountFactory(is_staff=True, is_superuser=True))
    response = client.get(
        reverse("api-schema"),
        HTTP_ACCEPT="application/vnd.oai.openapi+json",
    )
    assert response.status_code == 200
    schema = response.json()
    schemas = schema["components"]["schemas"]
    paths = (
        "/api/v1/organizations/{organization_id}/editions/{edition_id}/"
        "registrations/me/profile-extensions",
        "/api/v1/organizations/{organization_id}/editions/{edition_id}/"
        "registrations/{registration_id}/profile-extensions",
    )

    for path in paths:
        operation = schema["paths"][path]["post"]
        parameter_names = {
            parameter["name"]
            for parameter in operation["parameters"]
            if parameter["in"] == "header"
        }
        assert "Idempotency-Key" in parameter_names
        request_schema = operation["requestBody"]["content"]["application/json"][
            "schema"
        ]
        if "$ref" in request_schema:
            request_schema = schemas[request_schema["$ref"].rsplit("/", 1)[-1]]
        assert {"field_id", "value", "expected_sequence"} <= set(
            request_schema["required"]
        )
        assert "Idempotent-Replay" in operation["responses"]["200"]["headers"]
        for status_code in ("400", "404", "409", "503"):
            assert (
                "application/problem+json"
                in operation["responses"][status_code]["content"]
            )
        for method in ("get", "post"):
            response_schema = schema["paths"][path][method]["responses"]["200"][
                "content"
            ]["application/json"]["schema"]
            assert response_schema == {
                "$ref": "#/components/schemas/ProfileExtensionWorkspace"
            }

    workspace = schemas["ProfileExtensionWorkspace"]
    assert {"registration_id", "snapshot_digest", "fields"} <= set(
        workspace["required"]
    )
    field_schema = schemas["ProfileExtensionField"]
    assert "current_sequence" in field_schema["required"]
