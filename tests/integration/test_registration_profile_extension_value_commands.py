import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import (
    DatabaseError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.services import AuthorizationDenied
from maru.effects.models import DomainEvent, OutboxMessage
from maru.identity.models import Account
from maru.registration.models import (
    AttendeeRegistrationProfile,
    ConfigurationStatus,
    ProfileExtensionAudience,
    ProfileExtensionReviewStatus,
    ProfileExtensionStatus,
    ProfileExtensionValueWriterKind,
    ProfileExtensionWriter,
    QuestionClassification,
    QuestionFieldType,
    Registration,
    RegistrationProfileExtensionField,
    RegistrationProfileExtensionValueCommandReceipt,
    RegistrationProfileExtensionValueControl,
    RegistrationProfileExtensionValueRevision,
)
from maru.registration.profile_extension_values import (
    MAX_PROFILE_EXTENSION_FIELDS,
    ProfileExtensionValueEvidenceConflictError,
    ProfileExtensionValueLimitExceededError,
    ProfileExtensionValueRetryConflictError,
    ProfileExtensionValueSequenceConflictError,
    ProfileExtensionValueUnavailableError,
    append_profile_extension_value,
    read_directory_profile_extension_values,
    read_profile_extension_values,
)
from maru.registration.profile_policy import DIRECTORY_CONSENT_VERSION
from maru.registration.services import AttendeeProfileInput, update_attendee_profile
from maru.workforce.models import Department
from tests.factories import (
    AccountFactory,
    AdmissionProductFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    ParticipationFactory,
    RegistrationConfigurationFactory,
)
from tests.workforce_helpers import create_department_for_test

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


def _registration_world() -> tuple[Registration, Account]:
    owner = AccountFactory()
    edition = EventEditionFactory()
    participation = ParticipationFactory(
        account=owner,
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
        account=owner,
        configuration=configuration,
        product=product,
        reference=f"PV-{uuid4().hex[:12]}",
        state=Registration.State.CONFIRMED,
        product_name_snapshot=product.name,
        price_minor_snapshot=product.price_minor,
        currency_snapshot=configuration.currency,
        submitted_at=timezone.now(),
        confirmed_at=timezone.now(),
        confirmation_basis=Registration.ConfirmationBasis.PROVIDER,
    )
    return registration, owner


def _field(
    registration: Registration,
    *,
    actor: Account,
    key: str,
    writer_policy: str = ProfileExtensionWriter.ATTENDEE_AND_STAFF,
    attendee_visible: bool = True,
    audience_policy: str | None = None,
    audience_department: Department | None = None,
    field_type: str = QuestionFieldType.SHORT_TEXT,
    options: list[str] | None = None,
    required: bool = False,
    position: int = 0,
) -> RegistrationProfileExtensionField:
    return RegistrationProfileExtensionField.objects.create(
        organization=registration.organization,
        edition=registration.edition,
        key=key,
        version=1,
        label=f"Synthetic {key}",
        help_text="Provide one current synthetic profile detail.",
        field_type=field_type,
        options=options or [],
        purpose="Maintain a current synthetic registration profile detail.",
        classification=QuestionClassification.PERSONAL,
        attendee_visible=attendee_visible,
        audience_policy=(
            audience_policy
            if audience_policy is not None
            else (
                ProfileExtensionAudience.SELF
                if attendee_visible
                else ProfileExtensionAudience.REGISTRATION_STAFF
            )
        ),
        audience_department=audience_department,
        writer_policy=writer_policy,
        required=required,
        position=position,
        review_status=ProfileExtensionReviewStatus.APPROVED,
        status=ProfileExtensionStatus.ACTIVE,
        created_by=actor,
        approved_by=actor,
        approved_at=timezone.now() - timedelta(minutes=1),
    )


def _grant(actor: Account, registration: Registration, capability: str) -> None:
    CapabilityGrantFactory(
        organization=registration.organization,
        edition=registration.edition,
        principal=actor,
        capability_code=capability,
        effective_from=timezone.now() - timedelta(minutes=1),
    )


def _append_values(
    *,
    actor: Account,
    registration: Registration,
    field: RegistrationProfileExtensionField,
    value: object = "Synthetic current detail",
    expected_sequence: int = 0,
    retry_key: UUID | None = None,
    correlation_id: UUID | None = None,
    reason: str = "",
) -> dict[str, object]:
    return {
        "actor": actor,
        "organization_id": registration.organization_id,
        "edition_id": registration.edition_id,
        "registration_id": registration.id,
        "field_id": field.id,
        "value": value,
        "expected_sequence": expected_sequence,
        "retry_key": retry_key or uuid4(),
        "correlation_id": correlation_id or uuid4(),
        "request_id": uuid4(),
        "source_channel": "test",
        "reason": reason,
    }


def _read_values(
    *,
    actor: Account,
    registration: Registration,
    correlation_id: UUID | None = None,
) -> dict[str, object]:
    return {
        "actor": actor,
        "organization_id": registration.organization_id,
        "edition_id": registration.edition_id,
        "registration_id": registration.id,
        "correlation_id": correlation_id or uuid4(),
        "source_channel": "test",
    }


def _directory_profile(
    registration: Registration,
) -> AttendeeRegistrationProfile:
    return AttendeeRegistrationProfile.objects.create(
        registration=registration,
        organization=registration.organization,
        edition=registration.edition,
        account=registration.account,
        real_name="Synthetic Directory Attendee",
        date_of_birth=date(1990, 1, 1),
        address_line_1="1 Synthetic Street",
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
        directory_visible=True,
        directory_country_code="HU",
        directory_consent_version=DIRECTORY_CONSENT_VERSION,
        directory_consent_at=timezone.now(),
        collection_notice_version="synthetic-profile-v1",
    )


def _profile_value_counts() -> dict[str, int]:
    return {
        "controls": RegistrationProfileExtensionValueControl.objects.count(),
        "revisions": RegistrationProfileExtensionValueRevision.objects.count(),
        "receipts": RegistrationProfileExtensionValueCommandReceipt.objects.count(),
        "audits": AuditEvent.objects.filter(
            operation="registration.profile_extension.value_append"
        ).count(),
        "events": DomainEvent.objects.filter(
            event_name="registration.profile_extension.value_appended.v1"
        ).count(),
        "outbox": OutboxMessage.objects.filter(
            event__event_name="registration.profile_extension.value_appended.v1"
        ).count(),
    }


def _truncate_with_test_escape_disabled(table: str) -> None:
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL maru.authority_provenance_test_reset = 'off'")
        cursor.execute(f"TRUNCATE {table} CASCADE")


def test_owner_append_commits_exact_minimized_evidence_and_replays() -> None:
    registration, owner = _registration_world()
    field = _field(registration, actor=owner, key="arrival-note")
    retry_key = uuid4()
    correlation_id = uuid4()
    private_value = "Highly Sensitive Synthetic Answer"
    values = _append_values(
        actor=owner,
        registration=registration,
        field=field,
        value=private_value,
        retry_key=retry_key,
        correlation_id=correlation_id,
    )

    created = append_profile_extension_value(**values)
    replayed = append_profile_extension_value(
        **{**values, "correlation_id": uuid4(), "request_id": uuid4()}
    )

    assert created.replayed is False
    assert replayed.replayed is True
    assert replayed.revision_id == created.revision_id
    assert replayed.receipt_id == created.receipt_id
    assert replayed.result_sequence == created.result_sequence == 1
    assert _profile_value_counts() == {
        "controls": 1,
        "revisions": 1,
        "receipts": 1,
        "audits": 1,
        "events": 1,
        "outbox": 1,
    }

    control = RegistrationProfileExtensionValueControl.objects.get()
    revision = RegistrationProfileExtensionValueRevision.objects.get()
    receipt = RegistrationProfileExtensionValueCommandReceipt.objects.get()
    audit = AuditEvent.objects.get(
        operation="registration.profile_extension.value_append"
    )
    event = DomainEvent.objects.get(
        event_name="registration.profile_extension.value_appended.v1"
    )
    assert control.latest_revision_id == revision.id
    assert control.current_sequence == revision.sequence == 1
    assert receipt.control_id == control.id
    assert receipt.revision_id == revision.id
    assert receipt.writer_kind == ProfileExtensionValueWriterKind.OWNER
    assert receipt.correlation_id == correlation_id
    assert revision.value == private_value
    assert revision.reason == ""
    assert audit.changed_fields == ["current_value"]
    assert audit.safe_metadata == {"policy_version": POLICY_VERSION}
    assert event.payload == {
        "field_id": str(field.id),
        "field_version": "1",
        "registration_id": str(registration.id),
        "sequence": "1",
        "writer_kind": ProfileExtensionValueWriterKind.OWNER,
    }
    serialized_evidence = json.dumps(
        {
            "audit": audit.safe_metadata,
            "event": event.payload,
            "digest": receipt.request_digest,
        },
        sort_keys=True,
    )
    assert private_value not in serialized_evidence


def test_retry_conflict_and_exact_sequence_fence_preserve_first_result() -> None:
    registration, owner = _registration_world()
    field = _field(registration, actor=owner, key="travel-note")
    retry_key = uuid4()
    first_values = _append_values(
        actor=owner,
        registration=registration,
        field=field,
        value="Train",
        retry_key=retry_key,
    )
    first = append_profile_extension_value(**first_values)

    with pytest.raises(ProfileExtensionValueRetryConflictError):
        append_profile_extension_value(**{**first_values, "value": "Car"})
    with pytest.raises(ProfileExtensionValueSequenceConflictError):
        append_profile_extension_value(
            **_append_values(
                actor=owner,
                registration=registration,
                field=field,
                value="Car",
                expected_sequence=0,
            )
        )

    second = append_profile_extension_value(
        **_append_values(
            actor=owner,
            registration=registration,
            field=field,
            value="Car",
            expected_sequence=1,
        )
    )
    assert first.result_sequence == 1
    assert second.result_sequence == 2
    assert list(
        RegistrationProfileExtensionValueRevision.objects.values_list(
            "sequence", "value"
        )
    ) == [(1, "Train"), (2, "Car")]
    assert RegistrationProfileExtensionValueControl.objects.get().current_sequence == 2


def test_two_sequential_appends_commit_inside_one_outer_transaction() -> None:
    registration, owner = _registration_world()
    field = _field(registration, actor=owner, key="batched-sequence")

    with transaction.atomic():
        first = append_profile_extension_value(
            **_append_values(
                actor=owner,
                registration=registration,
                field=field,
                value="first in batch",
                expected_sequence=0,
            )
        )
        second = append_profile_extension_value(
            **_append_values(
                actor=owner,
                registration=registration,
                field=field,
                value="second in batch",
                expected_sequence=1,
            )
        )

    assert (first.result_sequence, second.result_sequence) == (1, 2)
    assert list(
        RegistrationProfileExtensionValueRevision.objects.values_list(
            "sequence", "value"
        )
    ) == [(1, "first in batch"), (2, "second in batch")]
    assert list(
        RegistrationProfileExtensionValueCommandReceipt.objects.values_list(
            "expected_sequence", "result_sequence"
        )
    ) == [(0, 1), (1, 2)]
    assert RegistrationProfileExtensionValueControl.objects.get().current_sequence == 2


def test_historical_retry_replays_after_the_control_has_advanced() -> None:
    registration, owner = _registration_world()
    field = _field(registration, actor=owner, key="historical-retry")
    first_retry_key = uuid4()
    first_values = _append_values(
        actor=owner,
        registration=registration,
        field=field,
        value="first result",
        expected_sequence=0,
        retry_key=first_retry_key,
    )
    first = append_profile_extension_value(**first_values)
    second = append_profile_extension_value(
        **_append_values(
            actor=owner,
            registration=registration,
            field=field,
            value="current result",
            expected_sequence=1,
        )
    )

    replay = append_profile_extension_value(
        **{**first_values, "correlation_id": uuid4(), "request_id": uuid4()}
    )

    assert first.result_sequence == 1
    assert second.result_sequence == 2
    assert replay.replayed is True
    assert replay.revision_id == first.revision_id
    assert replay.result_sequence == 1
    assert RegistrationProfileExtensionValueControl.objects.get().current_sequence == 2
    assert RegistrationProfileExtensionValueRevision.objects.count() == 2
    assert RegistrationProfileExtensionValueCommandReceipt.objects.count() == 2


def test_owner_and_staff_have_separate_capabilities_and_writer_policies() -> None:
    registration, owner = _registration_world()
    attendee_field = _field(
        registration,
        actor=owner,
        key="attendee-note",
        writer_policy=ProfileExtensionWriter.ATTENDEE,
    )
    staff_field = _field(
        registration,
        actor=owner,
        key="internal-review",
        writer_policy=ProfileExtensionWriter.REGISTRATION_STAFF,
        attendee_visible=False,
        position=10,
    )
    staff = AccountFactory()
    _grant(staff, registration, "registration.register_on_behalf")

    with pytest.raises(AuthorizationDenied):
        append_profile_extension_value(
            **_append_values(
                actor=staff,
                registration=registration,
                field=staff_field,
                reason="A broad legacy capability must not authorize this write.",
            )
        )
    with pytest.raises(ProfileExtensionValueUnavailableError):
        read_profile_extension_values(
            **_read_values(actor=staff, registration=registration)
        )

    _grant(staff, registration, "registration.update_profile_extensions")
    with pytest.raises(ValidationError, match="Staff changes require a reason"):
        append_profile_extension_value(
            **_append_values(
                actor=staff,
                registration=registration,
                field=staff_field,
            )
        )
    with pytest.raises(AuthorizationDenied):
        append_profile_extension_value(
            **_append_values(
                actor=staff,
                registration=registration,
                field=attendee_field,
                reason="Staff must not override an attendee-managed field.",
            )
        )

    staff_result = append_profile_extension_value(
        **_append_values(
            actor=staff,
            registration=registration,
            field=staff_field,
            value="reviewed",
            reason="Checked the synthetic registration evidence.",
        )
    )
    assert staff_result.result_sequence == 1
    assert (
        RegistrationProfileExtensionValueCommandReceipt.objects.get(
            pk=staff_result.receipt_id
        ).writer_kind
        == ProfileExtensionValueWriterKind.STAFF
    )

    with pytest.raises(AuthorizationDenied):
        append_profile_extension_value(
            **_append_values(
                actor=owner,
                registration=registration,
                field=staff_field,
            )
        )
    with pytest.raises(ValidationError, match="does not accept a staff reason"):
        append_profile_extension_value(
            **_append_values(
                actor=owner,
                registration=registration,
                field=attendee_field,
                reason="Owner-supplied reason is not staff evidence.",
            )
        )

    owner_workspace = read_profile_extension_values(
        **_read_values(actor=owner, registration=registration)
    )
    assert [item.field_key for item in owner_workspace.fields] == ["attendee-note"]
    _grant(staff, registration, "registration.view_profile_extensions")
    staff_workspace = read_profile_extension_values(
        **_read_values(actor=staff, registration=registration)
    )
    assert [item.field_key for item in staff_workspace.fields] == [
        "internal-review",
    ]
    assert staff_workspace.fields[0].can_write is True
    assert staff_workspace.fields[0].current_value == "reviewed"


def test_department_audience_uses_exact_scope_and_platform_admin_is_not_a_reader() -> (
    None
):
    registration, owner = _registration_world()
    department = create_department_for_test(
        edition=registration.edition,
        name="Registration Help Desk",
        expected_code="registration-help-desk",
    )
    sibling = create_department_for_test(
        edition=registration.edition,
        name="Convention Programme",
        expected_code="convention-programme",
    )
    field = _field(
        registration,
        actor=owner,
        key="help-desk-note",
        writer_policy=ProfileExtensionWriter.REGISTRATION_STAFF,
        attendee_visible=False,
        audience_policy=ProfileExtensionAudience.DEPARTMENT,
        audience_department=department,
    )
    exact_reader = AccountFactory()
    CapabilityGrantFactory(
        organization=registration.organization,
        edition=registration.edition,
        department=department,
        principal=exact_reader,
        capability_code="registration.view_profile_extensions",
        effective_from=timezone.now() - timedelta(minutes=1),
    )
    sibling_reader = AccountFactory()
    CapabilityGrantFactory(
        organization=registration.organization,
        edition=registration.edition,
        department=sibling,
        principal=sibling_reader,
        capability_code="registration.view_profile_extensions",
        effective_from=timezone.now() - timedelta(minutes=1),
    )

    workspace = read_profile_extension_values(
        **_read_values(actor=exact_reader, registration=registration)
    )
    assert [item.field_id for item in workspace.fields] == [field.id]
    assert workspace.fields[0].audience_department_id == department.id
    with pytest.raises(ProfileExtensionValueUnavailableError):
        read_profile_extension_values(
            **_read_values(actor=sibling_reader, registration=registration)
        )
    platform_admin = AccountFactory(is_staff=True, is_superuser=True)
    with pytest.raises(ProfileExtensionValueUnavailableError):
        read_profile_extension_values(
            **_read_values(actor=platform_admin, registration=registration)
        )

    foreign_registration, foreign_owner = _registration_world()
    with pytest.raises(ValidationError):
        _field(
            foreign_registration,
            actor=foreign_owner,
            key="foreign-help-desk-note",
            attendee_visible=False,
            audience_policy=ProfileExtensionAudience.DEPARTMENT,
            audience_department=department,
        )


def test_directory_audiences_are_minimized_and_withdrawal_is_immediate() -> None:
    registration, owner = _registration_world()
    public_field = _field(
        registration,
        actor=owner,
        key="public-bio-note",
        audience_policy=ProfileExtensionAudience.PUBLIC,
    )
    attendee_field = _field(
        registration,
        actor=owner,
        key="attendee-only-note",
        audience_policy=ProfileExtensionAudience.CONFIRMED_ATTENDEES,
        position=10,
    )
    append_profile_extension_value(
        **_append_values(
            actor=owner,
            registration=registration,
            field=public_field,
            value="Public synthetic note",
        )
    )
    append_profile_extension_value(
        **_append_values(
            actor=owner,
            registration=registration,
            field=attendee_field,
            value="Confirmed synthetic note",
        )
    )
    profile = _directory_profile(registration)

    anonymous = read_directory_profile_extension_values(
        actor=None,
        organization_id=registration.organization_id,
        edition_id=registration.edition_id,
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert [(item.label, item.value) for item in anonymous[registration.id]] == [
        (public_field.label, "Public synthetic note")
    ]
    confirmed = read_directory_profile_extension_values(
        actor=owner,
        organization_id=registration.organization_id,
        edition_id=registration.edition_id,
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert [item.audience_policy for item in confirmed[registration.id]] == [
        ProfileExtensionAudience.PUBLIC,
        ProfileExtensionAudience.CONFIRMED_ATTENDEES,
    ]
    assert not hasattr(confirmed[registration.id][0], "field_key")
    assert not hasattr(confirmed[registration.id][0], "classification")

    update_attendee_profile(
        organization_id=registration.organization_id,
        edition_id=registration.edition_id,
        actor=owner,
        profile_input=AttendeeProfileInput(
            real_name=profile.real_name,
            date_of_birth=profile.date_of_birth,
            address_line_1=profile.address_line_1,
            address_line_2=profile.address_line_2,
            locality=profile.locality,
            postal_code=profile.postal_code,
            region=profile.region,
            country_code=profile.country_code,
            emergency_contact_name=profile.emergency_contact_name,
            emergency_contact_phone=profile.emergency_contact_phone,
            phone_number=profile.phone_number,
            telegram_handle=profile.telegram_handle,
            pronoun_code=profile.pronoun_code,
            other_pronouns=profile.other_pronouns,
            bio=profile.bio,
            spoken_language_codes=tuple(profile.spoken_language_codes),
            profile_photo=None,
            reuse_profile_photo_id=None,
            keep_profile_photo=True,
            brings_fursuits=False,
            fursuits=(),
            directory_visible=False,
        ),
        correlation_id=uuid4(),
        source_channel="test",
    )
    withdrawn = read_directory_profile_extension_values(
        actor=owner,
        organization_id=registration.organization_id,
        edition_id=registration.edition_id,
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert withdrawn == {}
    audits = AuditEvent.objects.filter(
        operation="registration.profile_extension.directory_read"
    )
    assert audits.count() == 3
    assert (
        "synthetic note"
        not in json.dumps(list(audits.values_list("safe_metadata", flat=True))).lower()
    )


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"organization_id": "not-a-uuid"}, "canonical UUID"),
        ({"edition_id": uuid4().hex}, "canonical UUID"),
        ({"expected_sequence": True}, "whole number"),
        ({"expected_sequence": -1}, "whole number"),
        ({"retry_key": str(uuid4())}, "canonical UUID"),
        ({"source_channel": "API"}, "registered source channel"),
        ({"source_channel": "x" * 33}, "registered source channel"),
        ({"value": {"not-json"}}, "valid JSON value"),
        ({"value": float("nan")}, "valid JSON value"),
        ({"value": "x" * 16_383}, "16 KiB"),
    ],
)
def test_closed_command_validation_rejects_ambiguous_or_unbounded_inputs(
    override: dict[str, object],
    message: str,
) -> None:
    registration, owner = _registration_world()
    field = _field(registration, actor=owner, key="strict-input")
    values = _append_values(actor=owner, registration=registration, field=field)

    with pytest.raises(ValidationError, match=message):
        append_profile_extension_value(**{**values, **override})

    assert _profile_value_counts() == {
        "controls": 0,
        "revisions": 0,
        "receipts": 0,
        "audits": 0,
        "events": 0,
        "outbox": 0,
    }


def test_value_and_reason_domain_validation_rolls_back_cleanly() -> None:
    registration, owner = _registration_world()
    required_field = _field(
        registration,
        actor=owner,
        key="required-note",
        required=True,
    )
    with pytest.raises(ValidationError, match="required"):
        append_profile_extension_value(
            **_append_values(
                actor=owner,
                registration=registration,
                field=required_field,
                value="",
            )
        )

    staff = AccountFactory()
    _grant(staff, registration, "registration.update_profile_extensions")
    staff_field = _field(
        registration,
        actor=owner,
        key="staff-note",
        writer_policy=ProfileExtensionWriter.REGISTRATION_STAFF,
        attendee_visible=False,
    )
    with pytest.raises(ValidationError, match="no more than 500"):
        append_profile_extension_value(
            **_append_values(
                actor=staff,
                registration=registration,
                field=staff_field,
                reason="x" * 501,
            )
        )
    assert not RegistrationProfileExtensionValueRevision.objects.exists()


def test_all_supported_value_types_use_the_closed_normalization_contract() -> None:
    registration, owner = _registration_world()
    cases = (
        (
            "typed-short-text",
            QuestionFieldType.SHORT_TEXT,
            [],
            42,
            "  normalized text  ",
            "normalized text",
        ),
        (
            "typed-long-text",
            QuestionFieldType.LONG_TEXT,
            [],
            "x" * 5_001,
            "current long text",
            "current long text",
        ),
        (
            "typed-boolean",
            QuestionFieldType.BOOLEAN,
            [],
            "yes",
            True,
            True,
        ),
        (
            "typed-integer",
            QuestionFieldType.INTEGER,
            [],
            True,
            -(2**31),
            -(2**31),
        ),
        (
            "typed-single-choice",
            QuestionFieldType.SINGLE_CHOICE,
            ["alpha", "beta"],
            "gamma",
            "alpha",
            "alpha",
        ),
        (
            "typed-multiple-choice",
            QuestionFieldType.MULTIPLE_CHOICE,
            ["alpha", "beta"],
            ["alpha", "alpha"],
            ["alpha", "beta"],
            ["alpha", "beta"],
        ),
    )

    for key, field_type, options, invalid, valid, normalized in cases:
        field = _field(
            registration,
            actor=owner,
            key=key,
            field_type=field_type,
            options=options,
        )
        with pytest.raises(ValidationError):
            append_profile_extension_value(
                **_append_values(
                    actor=owner,
                    registration=registration,
                    field=field,
                    value=invalid,
                )
            )
        result = append_profile_extension_value(
            **_append_values(
                actor=owner,
                registration=registration,
                field=field,
                value=valid,
            )
        )
        assert (
            RegistrationProfileExtensionValueRevision.objects.get(
                pk=result.revision_id
            ).value
            == normalized
        )

    assert RegistrationProfileExtensionValueControl.objects.count() == len(cases)
    assert RegistrationProfileExtensionValueRevision.objects.count() == len(cases)
    assert RegistrationProfileExtensionValueCommandReceipt.objects.count() == len(cases)


def test_route_scope_and_field_scope_are_tenant_isolated() -> None:
    registration, owner = _registration_world()
    field = _field(registration, actor=owner, key="tenant-detail")
    other_registration, other_owner = _registration_world()
    other_field = _field(
        other_registration,
        actor=other_owner,
        key="tenant-detail",
    )

    base = _append_values(actor=owner, registration=registration, field=field)
    for override in (
        {"organization_id": other_registration.organization_id},
        {"edition_id": other_registration.edition_id},
        {"field_id": other_field.id},
    ):
        with pytest.raises(ProfileExtensionValueUnavailableError):
            append_profile_extension_value(**{**base, **override})

    foreign_staff = AccountFactory()
    _grant(
        foreign_staff,
        other_registration,
        "registration.update_profile_extensions",
    )
    with pytest.raises(AuthorizationDenied):
        append_profile_extension_value(
            **_append_values(
                actor=foreign_staff,
                registration=registration,
                field=field,
                reason="A foreign grant cannot cross the tenant boundary.",
            )
        )
    assert not RegistrationProfileExtensionValueRevision.objects.exists()


@pytest.mark.parametrize("operation", ["append", "read"])
def test_a_stale_deactivated_actor_cannot_use_self_profile_authority(
    operation: str,
) -> None:
    registration, owner = _registration_world()
    field = _field(registration, actor=owner, key=f"inactive-{operation}")
    assert owner.is_active is True
    Account.objects.filter(pk=owner.pk).update(is_active=False)
    assert Account.objects.filter(pk=owner.pk, is_active=False).exists()

    def invoke() -> None:
        if operation == "append":
            append_profile_extension_value(
                **_append_values(
                    actor=owner,
                    registration=registration,
                    field=field,
                )
            )
        else:
            read_profile_extension_values(
                **_read_values(actor=owner, registration=registration)
            )

    with pytest.raises(ProfileExtensionValueUnavailableError) as error:
        invoke()
    assert error.value.reason_code == "profile_extension_value_unavailable"

    assert not RegistrationProfileExtensionValueRevision.objects.exists()


@pytest.mark.parametrize("operation", ["append", "read"])
def test_a_stale_deactivated_staff_actor_cannot_use_persisted_authority(
    operation: str,
) -> None:
    registration, owner = _registration_world()
    field = _field(
        registration,
        actor=owner,
        key=f"inactive-staff-{operation}",
        writer_policy=ProfileExtensionWriter.REGISTRATION_STAFF,
        attendee_visible=False,
    )
    staff = AccountFactory()
    capability = (
        "registration.update_profile_extensions"
        if operation == "append"
        else "registration.view_profile_extensions"
    )
    _grant(staff, registration, capability)
    assert staff.is_active is True
    Account.objects.filter(pk=staff.pk).update(is_active=False)
    assert Account.objects.filter(pk=staff.pk, is_active=False).exists()

    def invoke() -> None:
        if operation == "append":
            append_profile_extension_value(
                **_append_values(
                    actor=staff,
                    registration=registration,
                    field=field,
                    reason="An inactive staff actor must be denied.",
                )
            )
        else:
            read_profile_extension_values(
                **_read_values(actor=staff, registration=registration)
            )

    with pytest.raises(ProfileExtensionValueUnavailableError) as error:
        invoke()
    assert error.value.reason_code == "profile_extension_value_unavailable"

    assert not RegistrationProfileExtensionValueRevision.objects.exists()


@pytest.mark.parametrize(
    "failure_target",
    [
        "maru.registration.profile_extension_values.append_audit",
        "maru.registration.profile_extension_values.publish_domain_event",
        "maru.registration.profile_extension_values._require_exact_evidence",
    ],
)
def test_required_evidence_failure_rolls_back_the_entire_append(
    failure_target: str,
) -> None:
    registration, owner = _registration_world()
    field = _field(registration, actor=owner, key="atomic-detail")
    before = _profile_value_counts()

    with (
        patch(failure_target, side_effect=RuntimeError("synthetic evidence failure")),
        pytest.raises(RuntimeError, match="synthetic evidence failure"),
    ):
        append_profile_extension_value(
            **_append_values(actor=owner, registration=registration, field=field)
        )

    assert _profile_value_counts() == before


def test_replay_refuses_a_result_whose_exact_evidence_binding_was_tampered() -> None:
    registration, owner = _registration_world()
    field = _field(registration, actor=owner, key="replay-evidence")
    retry_key = uuid4()
    values = _append_values(
        actor=owner,
        registration=registration,
        field=field,
        retry_key=retry_key,
    )
    created = append_profile_extension_value(**values)

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE "
                "registration_registrationprofileextensionvaluecommandreceipt "
                "DISABLE TRIGGER registration_profile_value_receipt_guard"
            )
            try:
                cursor.execute(
                    "UPDATE "
                    "registration_registrationprofileextensionvaluecommandreceipt "
                    "SET correlation_id = %s WHERE id = %s",
                    [uuid4(), created.receipt_id],
                )
            finally:
                cursor.execute(
                    "ALTER TABLE "
                    "registration_registrationprofileextensionvaluecommandreceipt "
                    "ENABLE TRIGGER registration_profile_value_receipt_guard"
                )
        with pytest.raises(ProfileExtensionValueEvidenceConflictError):
            append_profile_extension_value(
                **{**values, "correlation_id": uuid4(), "request_id": uuid4()}
            )
        transaction.set_rollback(True)

    assert RegistrationProfileExtensionValueCommandReceipt.objects.filter(
        pk=created.receipt_id
    ).exists()


def test_reads_are_policy_filtered_current_bounded_and_audited() -> None:
    registration, owner = _registration_world()
    attendee_field = _field(
        registration,
        actor=owner,
        key="visible-current",
        writer_policy=ProfileExtensionWriter.ATTENDEE_AND_STAFF,
    )
    staff_field = _field(
        registration,
        actor=owner,
        key="staff-current",
        writer_policy=ProfileExtensionWriter.REGISTRATION_STAFF,
        attendee_visible=False,
        position=10,
    )
    append_profile_extension_value(
        **_append_values(
            actor=owner,
            registration=registration,
            field=attendee_field,
            value="first",
        )
    )
    append_profile_extension_value(
        **_append_values(
            actor=owner,
            registration=registration,
            field=attendee_field,
            value="current",
            expected_sequence=1,
        )
    )
    staff = AccountFactory()
    _grant(staff, registration, "registration.view_profile_extensions")

    owner_correlation = uuid4()
    owner_workspace = read_profile_extension_values(
        **_read_values(
            actor=owner,
            registration=registration,
            correlation_id=owner_correlation,
        )
    )
    staff_workspace = read_profile_extension_values(
        **_read_values(actor=staff, registration=registration)
    )

    assert len(owner_workspace.snapshot_digest) == 64
    assert [item.field_key for item in owner_workspace.fields] == ["visible-current"]
    assert owner_workspace.fields[0].current_value == "current"
    assert owner_workspace.fields[0].current_sequence == 2
    assert owner_workspace.fields[0].can_write is True
    assert [item.field_key for item in staff_workspace.fields] == ["staff-current"]
    assert staff_workspace.fields[0].can_write is False
    reads = AuditEvent.objects.filter(
        operation="registration.profile_extension.values_read"
    ).order_by("occurred_at", "id")
    assert reads.count() == 2
    owner_audit = reads.get(correlation_id=owner_correlation)
    assert owner_audit.capability_code == "registration.view_self_profile"
    assert owner_audit.safe_metadata == {
        "policy_version": POLICY_VERSION,
        "target_count": 1,
    }
    assert "current" not in json.dumps(owner_audit.safe_metadata)
    assert staff_field.id not in [item.field_id for item in owner_workspace.fields]


def test_read_audit_failure_releases_no_workspace_or_audit() -> None:
    registration, owner = _registration_world()
    _field(registration, actor=owner, key="read-failure")

    with (
        patch(
            "maru.registration.profile_extension_values.append_audit",
            side_effect=RuntimeError("synthetic read-audit failure"),
        ),
        pytest.raises(RuntimeError, match="synthetic read-audit failure"),
    ):
        read_profile_extension_values(
            **_read_values(actor=owner, registration=registration)
        )

    assert not AuditEvent.objects.filter(
        operation="registration.profile_extension.values_read"
    ).exists()


def test_read_rejects_limit_plus_one_without_partial_projection_or_audit() -> None:
    registration, owner = _registration_world()
    approved_at = timezone.now() - timedelta(minutes=1)
    RegistrationProfileExtensionField.objects.bulk_create(
        [
            RegistrationProfileExtensionField(
                organization=registration.organization,
                edition=registration.edition,
                key=f"bounded-{number:03d}",
                version=1,
                label=f"Bounded field {number}",
                help_text="Synthetic bounded projection field.",
                field_type=QuestionFieldType.SHORT_TEXT,
                options=[],
                purpose="Exercise the exact profile projection ceiling.",
                classification=QuestionClassification.PERSONAL,
                attendee_visible=True,
                writer_policy=ProfileExtensionWriter.ATTENDEE,
                required=False,
                position=number,
                review_status=ProfileExtensionReviewStatus.APPROVED,
                status=ProfileExtensionStatus.ACTIVE,
                created_by=owner,
                approved_by=owner,
                approved_at=approved_at,
            )
            for number in range(MAX_PROFILE_EXTENSION_FIELDS + 1)
        ]
    )

    with pytest.raises(ProfileExtensionValueLimitExceededError):
        read_profile_extension_values(
            **_read_values(actor=owner, registration=registration)
        )
    assert not AuditEvent.objects.filter(
        operation="registration.profile_extension.values_read"
    ).exists()


def test_concurrent_first_appends_commit_one_sequence_one_result() -> None:
    registration, owner = _registration_world()
    field = _field(registration, actor=owner, key="concurrent-detail")
    barrier_values = (uuid4(), uuid4())

    def run(retry_key: UUID) -> object:
        close_old_connections()
        try:
            thread_actor = Account.objects.get(pk=owner.pk)
            thread_registration = Registration.objects.get(pk=registration.pk)
            thread_field = RegistrationProfileExtensionField.objects.get(pk=field.pk)
            try:
                return append_profile_extension_value(
                    **_append_values(
                        actor=thread_actor,
                        registration=thread_registration,
                        field=thread_field,
                        value=f"race-{retry_key}",
                        retry_key=retry_key,
                    )
                )
            except ProfileExtensionValueSequenceConflictError as error:
                return error
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, barrier_values))

    assert sum(not isinstance(item, Exception) for item in results) == 1
    assert (
        sum(
            isinstance(item, ProfileExtensionValueSequenceConflictError)
            for item in results
        )
        == 1
    )
    assert RegistrationProfileExtensionValueRevision.objects.count() == 1
    assert RegistrationProfileExtensionValueCommandReceipt.objects.count() == 1
    assert RegistrationProfileExtensionValueControl.objects.get().current_sequence == 1


def test_database_rejects_unevidenced_revision_at_deferred_commit() -> None:
    registration, owner = _registration_world()
    field = _field(registration, actor=owner, key="raw-revision")

    with (
        pytest.raises(DatabaseError, match="lacks command evidence"),
        transaction.atomic(),
    ):
        RegistrationProfileExtensionValueRevision.objects.bulk_create(
            [
                RegistrationProfileExtensionValueRevision(
                    registration=registration,
                    organization_id=registration.organization_id,
                    edition_id=registration.edition_id,
                    field=field,
                    field_key=field.key,
                    sequence=1,
                    value="raw bypass",
                    actor=owner,
                    source_channel="test",
                )
            ]
        )
    assert not RegistrationProfileExtensionValueRevision.objects.exists()


def test_database_guards_reject_raw_update_delete_and_truncate() -> None:
    registration, owner = _registration_world()
    field = _field(registration, actor=owner, key="database-guard")
    result = append_profile_extension_value(
        **_append_values(actor=owner, registration=registration, field=field)
    )
    control = RegistrationProfileExtensionValueControl.objects.get()
    revision = RegistrationProfileExtensionValueRevision.objects.get()
    receipt = RegistrationProfileExtensionValueCommandReceipt.objects.get(
        pk=result.receipt_id
    )
    statements = (
        (
            "UPDATE registration_registrationprofileextensionvaluerevision "
            "SET value = %s WHERE id = %s",
            [json.dumps("rewritten"), revision.id],
            "append-only",
        ),
        (
            "DELETE FROM registration_registrationprofileextensionvaluerevision "
            "WHERE id = %s",
            [revision.id],
            "append-only",
        ),
        (
            "UPDATE registration_registrationprofileextensionvaluecontrol "
            "SET field_key = %s WHERE id = %s",
            ["changed-key", control.id],
            "invalid registration profile-value control transition",
        ),
        (
            "DELETE FROM registration_registrationprofileextensionvaluecontrol "
            "WHERE id = %s",
            [control.id],
            "controls are durable",
        ),
        (
            "UPDATE registration_registrationprofileextensionvaluecommandreceipt "
            "SET request_digest = %s WHERE id = %s",
            ["f" * 64, receipt.id],
            "command receipts are immutable",
        ),
        (
            "DELETE FROM registration_registrationprofileextensionvaluecommandreceipt "
            "WHERE id = %s",
            [receipt.id],
            "command receipts are immutable",
        ),
    )
    for statement, parameters, message in statements:
        with (
            pytest.raises(DatabaseError, match=message),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(statement, parameters)

    truncate_tables = (
        "registration_registrationprofileextensionvaluecommandreceipt",
        "registration_registrationprofileextensionvaluecontrol",
        "registration_registrationprofileextensionvaluerevision",
    )
    for table in truncate_tables:
        with pytest.raises(DatabaseError, match="evidence is append-only"):
            _truncate_with_test_escape_disabled(table)

    assert _profile_value_counts() == {
        "controls": 1,
        "revisions": 1,
        "receipts": 1,
        "audits": 1,
        "events": 1,
        "outbox": 1,
    }
