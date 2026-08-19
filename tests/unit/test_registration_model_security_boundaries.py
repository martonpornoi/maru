from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from django.core.exceptions import ValidationError

from maru.registration import models

ORG = UUID(int=1)
OTHER_ORG = UUID(int=2)
EDITION = UUID(int=3)
OTHER_EDITION = UUID(int=4)
CONFIGURATION = UUID(int=5)
OTHER_CONFIGURATION = UUID(int=6)
ACCOUNT = UUID(int=7)


def _bind(
    instance: models.Model,
    name: str,
    related: object,
    identifier: UUID | None = None,
) -> None:
    setattr(instance, f"{name}_id", identifier or UUID(int=90))
    instance._state.fields_cache[name] = related


def _error_code(error: ValidationError) -> str | None:
    if hasattr(error, "error_dict"):
        return next(iter(error.error_dict.values()))[0].code
    return error.error_list[0].code


def _assert_clean_error(instance: models.Model, code: str | None = None) -> None:
    with pytest.raises(ValidationError) as raised:
        instance.clean()
    if code is not None:
        actual_code = _error_code(raised.value)
        if actual_code is None:
            assert raised.value.message_dict
        else:
            assert actual_code == code


def _configuration() -> models.RegistrationConfiguration:
    return models.RegistrationConfiguration(
        name="Registration",
        version=1,
        status=models.ConfigurationStatus.DRAFT,
        capacity=100,
        capacity_ceiling=200,
        currency="EUR",
        origin=models.RegistrationSetupOrigin.LEGACY_EXISTING,
        provenance_status=models.RegistrationProvenanceStatus.LEGACY_UNKNOWN,
        opens_at=datetime(2026, 8, 1, tzinfo=UTC),
        closes_at=datetime(2026, 8, 31, tzinfo=UTC),
        created_by_id=ACCOUNT,
    )


def _profile() -> models.AttendeeRegistrationProfile:
    return models.AttendeeRegistrationProfile(
        real_name="Example Attendee",
        date_of_birth=date(2000, 1, 1),
        address_line_1="Example road 1",
        locality="Budapest",
        postal_code="1000",
        region="Budapest",
        country_code="HU",
        emergency_contact_name="Example Contact",
        emergency_contact_phone="+360000000",
        phone_number="+360000001",
        pronoun_code="they_them",
        pronouns="they/them",
        collection_notice_version="registration-profile-v1",
    )


def _profile_field() -> models.RegistrationProfileExtensionField:
    return models.RegistrationProfileExtensionField(
        key="custom_fact",
        version=1,
        label="Custom fact",
        field_type=models.QuestionFieldType.SHORT_TEXT,
        options=[],
        purpose="Collect an optional attendee profile fact.",
        writer_policy=models.ProfileExtensionWriter.REGISTRATION_STAFF,
        audience_policy=models.ProfileExtensionAudience.SELF,
        attendee_visible=True,
        review_status=models.ProfileExtensionReviewStatus.PENDING,
        status=models.ProfileExtensionStatus.DRAFT,
    )


def test_template_scope_and_complete_provenance_are_validated_before_use() -> None:
    template = models.RegistrationTemplate(
        organization_id=ORG,
        code="template",
        name="Template",
        version=1,
        created_by_id=ACCOUNT,
    )
    _bind(
        template,
        "series",
        SimpleNamespace(organization_id=OTHER_ORG),
        UUID(int=10),
    )
    _assert_clean_error(template)

    template.series_id = None
    template._state.fields_cache.pop("series", None)
    template.provenance_status = models.RegistrationProvenanceStatus.COMPLETE
    _assert_clean_error(
        template,
        "registration_template_complete_provenance_incomplete",
    )


@pytest.mark.parametrize(
    "instance",
    [
        models.RegistrationTemplateSection(
            template=models.RegistrationTemplate(status=models.TemplateStatus.PUBLISHED)
        ),
        models.RegistrationTemplateQuestion(
            template=models.RegistrationTemplate(status=models.TemplateStatus.RETIRED)
        ),
        models.RegistrationTemplateProduct(
            template=models.RegistrationTemplate(status=models.TemplateStatus.PUBLISHED)
        ),
    ],
)
def test_non_draft_template_children_fail_before_any_write(
    instance: models.Model,
) -> None:
    with pytest.raises(ValidationError) as raised:
        instance.save()
    assert _error_code(raised.value) == "immutable_registration_template"


def test_template_question_rejects_a_section_from_another_template() -> None:
    question = models.RegistrationTemplateQuestion(
        template_id=UUID(int=20),
        key="question",
        label="Question",
        field_type=models.QuestionFieldType.SHORT_TEXT,
        purpose="Collect one answer.",
    )
    _bind(
        question,
        "section",
        SimpleNamespace(template_id=UUID(int=21)),
        UUID(int=22),
    )
    _assert_clean_error(question)


def test_product_capacity_codes_are_bounded_when_other_fields_are_valid() -> None:
    product = models.AdmissionProduct(
        code="standard",
        name="Standard",
        price_minor=0,
        capacity=10,
        capacity_ceiling=10,
        entitlement_code="standard",
        entitlement_name="Standard",
        required_capacity_codes=["x" * (models.MAX_CAPACITY_CODE_LENGTH + 1)],
        eligibility_explanation="Restricted capacity.",
    )
    _assert_clean_error(product, "product_capacity_code_too_long")


def test_template_command_receipt_enforces_scope_retry_pairing_and_immutability() -> (
    None
):
    receipt = models.RegistrationTemplateCatalogCommandReceipt(
        organization_id=ORG,
        retry_key=None,
        request_digest="",
    )
    _bind(receipt, "catalog", SimpleNamespace(organization_id=OTHER_ORG))
    _assert_clean_error(receipt, "registration_template_receipt_scope_mismatch")

    receipt.catalog_id = None
    receipt._state.fields_cache.pop("catalog", None)
    receipt.retry_key = UUID(int=23)
    _assert_clean_error(receipt, "registration_template_retry_evidence_incomplete")

    receipt._state.adding = False
    with pytest.raises(ValidationError) as immutable:
        receipt.save()
    assert _error_code(immutable.value) == (
        "immutable_registration_template_command_receipt"
    )


def test_template_command_target_is_append_only() -> None:
    target = models.RegistrationTemplateCatalogCommandTarget()
    target._state.adding = False
    with pytest.raises(ValidationError) as raised:
        target.save()
    assert _error_code(raised.value) == (
        "immutable_registration_template_command_target"
    )


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (
            lambda value: setattr(value, "capacity", 0),
            "registration_capacity_out_of_range",
        ),
        (
            lambda value: setattr(value, "capacity_ceiling", 99),
            "registration_capacity_ceiling_out_of_range",
        ),
        (
            lambda value: _bind(
                value,
                "edition",
                SimpleNamespace(organization_id=OTHER_ORG, lifecycle="planning"),
                EDITION,
            ),
            None,
        ),
        (
            lambda value: _bind(
                value,
                "edition",
                SimpleNamespace(organization_id=ORG, lifecycle="archived"),
                EDITION,
            ),
            "edition_registration_closed",
        ),
        (
            lambda value: _bind(
                value,
                "source_template",
                SimpleNamespace(organization_id=OTHER_ORG),
            ),
            None,
        ),
        (
            lambda value: _bind(
                value,
                "source_edition",
                SimpleNamespace(organization_id=OTHER_ORG),
            ),
            None,
        ),
        (
            lambda value: _bind(
                value,
                "source_configuration",
                SimpleNamespace(
                    id=OTHER_CONFIGURATION,
                    organization_id=OTHER_ORG,
                    edition_id=OTHER_EDITION,
                ),
                OTHER_CONFIGURATION,
            ),
            "registration_source_configuration_mismatch",
        ),
        (
            lambda value: setattr(
                value,
                "source_imported_at",
                datetime(2026, 8, 1, tzinfo=UTC),
            ),
            "registration_import_evidence_incomplete",
        ),
        (
            lambda value: setattr(value, "source_version", 1),
            "registration_source_evidence_without_source",
        ),
    ],
)
def test_configuration_rejects_cross_scope_and_incomplete_source_evidence(
    mutate: Any,
    code: str | None,
) -> None:
    configuration = _configuration()
    configuration.organization_id = ORG
    mutate(configuration)
    _assert_clean_error(configuration, code)


def _complete_configuration(origin: str) -> models.RegistrationConfiguration:
    configuration = _configuration()
    configuration.organization_id = ORG
    configuration.origin = origin
    configuration.provenance_status = models.RegistrationProvenanceStatus.COMPLETE
    configuration.content_digest = "a" * 64
    configuration.created_in_setup_version = 1
    configuration.last_changed_in_setup_version = 1
    return configuration


def test_complete_configuration_requires_command_and_source_provenance() -> None:
    missing_command = _complete_configuration(models.RegistrationSetupOrigin.BLANK)
    missing_command.content_digest = ""
    _assert_clean_error(
        missing_command,
        "registration_complete_provenance_incomplete",
    )

    blank_conflict = _complete_configuration(models.RegistrationSetupOrigin.BLANK)
    _bind(blank_conflict, "source_template", SimpleNamespace(organization_id=ORG))
    _assert_clean_error(blank_conflict, "registration_blank_source_conflict")

    template_copy = _complete_configuration(
        models.RegistrationSetupOrigin.PUBLISHED_TEMPLATE
    )
    _assert_clean_error(template_copy, "registration_template_provenance_incomplete")

    starter = _complete_configuration(models.RegistrationSetupOrigin.PLATFORM_STARTER)
    _bind(starter, "source_edition", SimpleNamespace(organization_id=ORG))
    _assert_clean_error(starter, "registration_starter_provenance_incomplete")

    prior = _complete_configuration(models.RegistrationSetupOrigin.PRIOR_EDITION)
    _assert_clean_error(
        prior,
        "registration_configuration_provenance_incomplete",
    )

    legacy = _complete_configuration(models.RegistrationSetupOrigin.LEGACY_EXISTING)
    _assert_clean_error(legacy, "registration_legacy_provenance_conflict")


def test_setup_control_enforces_exact_scope_and_immutable_source_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control = models.RegistrationSetupControl(
        organization_id=ORG,
        origin=models.RegistrationSetupOrigin.BLANK,
        provenance_status=models.RegistrationProvenanceStatus.LEGACY_UNKNOWN,
        aggregate_version=1,
    )
    _bind(control, "edition", SimpleNamespace(organization_id=OTHER_ORG), EDITION)
    _assert_clean_error(control, "registration_setup_control_scope_mismatch")

    control._state.adding = False
    monkeypatch.setattr(
        models.RegistrationSetupControl.objects,
        "filter",
        lambda **_kwargs: SimpleNamespace(
            values=lambda *_args: SimpleNamespace(
                first=lambda: {
                    "organization_id": OTHER_ORG,
                    "edition_id": EDITION,
                    "origin": control.origin,
                    "provenance_status": control.provenance_status,
                }
            )
        ),
    )
    with pytest.raises(ValidationError) as immutable:
        control.save()
    assert _error_code(immutable.value) == "immutable_registration_setup_provenance"


def test_setup_receipt_retry_pairing_and_retention_guards() -> None:
    receipt = models.RegistrationSetupCommandReceipt(
        retry_key=UUID(int=24),
        request_digest="",
    )
    _assert_clean_error(receipt, "registration_setup_retry_evidence_incomplete")
    with pytest.raises(ValidationError) as protected:
        receipt.delete()
    assert _error_code(protected.value) == (
        "protected_registration_setup_command_receipt"
    )

    with pytest.raises(ValidationError) as target_protected:
        models.RegistrationSetupCommandTarget().delete()
    assert _error_code(target_protected.value) == (
        "protected_registration_setup_command_target"
    )


def test_registration_question_rejects_a_section_from_another_configuration() -> None:
    question = models.RegistrationQuestion(
        configuration_id=CONFIGURATION,
        key="question",
        label="Question",
        field_type=models.QuestionFieldType.SHORT_TEXT,
        purpose="Collect one answer.",
    )
    _bind(
        question,
        "section",
        SimpleNamespace(configuration_id=OTHER_CONFIGURATION),
    )
    _assert_clean_error(question)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: _bind(
            value,
            "edition",
            SimpleNamespace(organization_id=OTHER_ORG),
            EDITION,
        ),
        lambda value: _bind(
            value,
            "participation",
            SimpleNamespace(
                organization_id=OTHER_ORG,
                edition_id=EDITION,
                account_id=None,
            ),
        ),
        lambda value: _bind(
            value,
            "configuration",
            SimpleNamespace(organization_id=OTHER_ORG, edition_id=EDITION),
            CONFIGURATION,
        ),
        lambda value: _bind(
            value,
            "product",
            SimpleNamespace(configuration_id=OTHER_CONFIGURATION),
        ),
        lambda value: (
            setattr(
                value, "submission_source", models.Registration.SubmissionSource.SELF
            ),
            setattr(value, "submitted_by_id", ACCOUNT),
        ),
        lambda value: (
            setattr(
                value,
                "submission_source",
                models.Registration.SubmissionSource.STAFF_ASSISTED,
            ),
            setattr(value, "submitted_by_id", None),
            setattr(value, "staff_submission_reason", ""),
        ),
    ],
)
def test_registration_rejects_mixed_tenant_state_and_ambiguous_writer_evidence(
    mutate: Any,
) -> None:
    registration = models.Registration(
        organization_id=ORG,
        edition_id=EDITION,
        configuration_id=CONFIGURATION,
        submission_source=models.Registration.SubmissionSource.SELF,
    )
    _bind(
        registration,
        "edition",
        SimpleNamespace(organization_id=ORG),
        EDITION,
    )
    _bind(
        registration,
        "configuration",
        SimpleNamespace(organization_id=ORG, edition_id=EDITION),
        CONFIGURATION,
    )
    mutate(registration)
    _assert_clean_error(registration)


def test_registration_and_guardian_records_require_reasoned_retention_workflows() -> (
    None
):
    with pytest.raises(ValidationError) as protected:
        models.Registration().delete()
    assert _error_code(protected.value) == "protected_registration"

    consent = models.GuardianConsent(
        organization_id=ORG,
        edition_id=EDITION,
    )
    _bind(
        consent,
        "registration",
        SimpleNamespace(
            organization_id=OTHER_ORG,
            edition_id=EDITION,
            configuration_id=CONFIGURATION,
        ),
    )
    _bind(
        consent,
        "policy",
        SimpleNamespace(configuration_id=CONFIGURATION),
    )
    _assert_clean_error(consent, "guardian_consent_scope_mismatch")


def test_media_safety_receipts_are_append_only() -> None:
    receipt = models.MediaSafetyReceipt()
    receipt._state.adding = False
    with pytest.raises(ValidationError) as raised:
        receipt.save()
    assert _error_code(raised.value) == "immutable_media_safety_receipt"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: _bind(
            value,
            "registration",
            SimpleNamespace(
                organization_id=OTHER_ORG,
                edition_id=EDITION,
                account_id=ACCOUNT,
            ),
        ),
        lambda value: setattr(value, "pronoun_code", "unknown"),
        lambda value: setattr(value, "pronoun_code", "other"),
        lambda value: setattr(value, "other_pronouns", "xe/xem"),
        lambda value: setattr(value, "pronouns", "mismatched"),
        lambda value: setattr(
            value,
            "profile_photo_status",
            models.MediaReviewStatus.PENDING,
        ),
        lambda value: (
            setattr(value, "profile_photo", "profile.webp"),
            setattr(
                value,
                "profile_photo_status",
                models.MediaReviewStatus.APPROVED,
            ),
        ),
        lambda value: setattr(value, "directory_consent_version", "directory-v1"),
        lambda value: (
            setattr(value, "directory_visible", True),
            setattr(value, "directory_country_code", "1"),
        ),
    ],
)
def test_profile_integrity_rejects_scope_pronoun_media_and_consent_mismatches(
    mutate: Any,
) -> None:
    profile = _profile()
    profile.organization_id = ORG
    profile.edition_id = EDITION
    profile.account_id = ACCOUNT
    mutate(profile)
    _assert_clean_error(profile)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: _bind(
            value,
            "profile",
            SimpleNamespace(
                registration_id=UUID(int=88),
                organization_id=ORG,
                edition_id=EDITION,
                account_id=ACCOUNT,
            ),
        ),
        lambda value: setattr(value, "photo_status", models.MediaReviewStatus.PENDING),
        lambda value: (
            setattr(value, "photo", "fursuit.webp"),
            setattr(value, "photo_status", models.MediaReviewStatus.APPROVED),
        ),
    ],
)
def test_fursuit_integrity_rejects_scope_and_moderation_evidence_mismatches(
    mutate: Any,
) -> None:
    fursuit = models.AttendeeFursuit(
        registration_id=UUID(int=89),
        organization_id=ORG,
        edition_id=EDITION,
        account_id=ACCOUNT,
        name="Fursuit",
    )
    mutate(fursuit)
    _assert_clean_error(fursuit)


def test_registration_submissions_are_immutable_and_retained() -> None:
    submission = models.RegistrationSubmission()
    submission._state.adding = False
    with pytest.raises(ValidationError) as immutable:
        submission.save()
    assert _error_code(immutable.value) == "immutable_registration_submission"
    with pytest.raises(ValidationError) as protected:
        submission.delete()
    assert _error_code(protected.value) == "protected_registration_submission"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: _bind(
            value,
            "edition",
            SimpleNamespace(organization_id=OTHER_ORG, series_id=UUID(int=30)),
            EDITION,
        ),
        lambda value: (
            setattr(
                value, "audience_policy", models.ProfileExtensionAudience.DEPARTMENT
            ),
            _bind(
                value,
                "audience_department",
                SimpleNamespace(
                    organization_id=OTHER_ORG,
                    edition_id=EDITION,
                    retired_at=None,
                ),
            ),
        ),
        lambda value: _bind(
            value,
            "audience_department",
            SimpleNamespace(
                organization_id=ORG,
                edition_id=EDITION,
                retired_at=None,
            ),
        ),
        lambda value: (
            _bind(value, "source_template", SimpleNamespace(organization_id=ORG)),
            _bind(value, "source_prior_edition", SimpleNamespace(organization_id=ORG)),
        ),
        lambda value: (
            setattr(value, "organization_id", ORG),
            _bind(
                value,
                "source_template",
                SimpleNamespace(
                    organization_id=OTHER_ORG,
                    series_id=None,
                    status=models.TemplateStatus.PUBLISHED,
                ),
            ),
        ),
        lambda value: (
            setattr(value, "organization_id", ORG),
            _bind(
                value,
                "edition",
                SimpleNamespace(
                    organization_id=ORG,
                    series_id=UUID(int=31),
                    starts_on=date(2026, 8, 1),
                ),
                EDITION,
            ),
            _bind(
                value,
                "source_prior_edition",
                SimpleNamespace(
                    id=OTHER_EDITION,
                    organization_id=ORG,
                    starts_on=date(2026, 9, 1),
                ),
                OTHER_EDITION,
            ),
        ),
        lambda value: (
            setattr(
                value,
                "writer_policy",
                models.ProfileExtensionWriter.ATTENDEE,
            ),
            setattr(
                value,
                "audience_policy",
                models.ProfileExtensionAudience.REGISTRATION_STAFF,
            ),
        ),
        lambda value: setattr(
            value,
            "review_status",
            models.ProfileExtensionReviewStatus.APPROVED,
        ),
        lambda value: (
            setattr(value, "approved_by_id", ACCOUNT),
            setattr(value, "approved_at", datetime(2026, 8, 1, tzinfo=UTC)),
        ),
        lambda value: setattr(value, "status", models.ProfileExtensionStatus.ACTIVE),
        lambda value: _bind(
            value,
            "supersedes",
            SimpleNamespace(
                edition_id=OTHER_EDITION,
                key=value.key,
                version=0,
                status=models.ProfileExtensionStatus.ACTIVE,
            ),
        ),
        lambda value: _bind(
            value,
            "supersedes",
            SimpleNamespace(
                edition_id=None,
                key=value.key,
                version=0,
                status=models.ProfileExtensionStatus.DRAFT,
            ),
        ),
        lambda value: setattr(value, "key", "payment_reference"),
    ],
)
def test_profile_field_definition_fails_closed_on_scope_provenance_and_policy(
    mutate: Any,
) -> None:
    field = _profile_field()
    mutate(field)
    _assert_clean_error(field)


def test_profile_field_and_value_records_use_retention_workflows() -> None:
    with pytest.raises(ValidationError) as field_error:
        _profile_field().delete()
    assert _error_code(field_error.value) == "protected_profile_extension_field"

    revision = models.RegistrationProfileExtensionValueRevision()
    with pytest.raises(ValidationError) as revision_error:
        revision.delete()
    assert _error_code(revision_error.value) == (
        "protected_profile_extension_value_revision"
    )

    control = models.RegistrationProfileExtensionValueControl()
    with pytest.raises(ValidationError) as control_error:
        control.delete()
    assert _error_code(control_error.value) == "protected_profile_value_control"


def test_profile_value_revision_control_and_receipt_enforce_exact_scope() -> None:
    revision = models.RegistrationProfileExtensionValueRevision(
        organization_id=ORG,
        edition_id=EDITION,
        field_key="custom_fact",
    )
    _bind(
        revision,
        "registration",
        SimpleNamespace(organization_id=OTHER_ORG, edition_id=EDITION),
    )
    _assert_clean_error(revision)

    revision.registration_id = None
    revision._state.fields_cache.pop("registration", None)
    _bind(
        revision,
        "field",
        SimpleNamespace(
            organization_id=ORG,
            edition_id=OTHER_EDITION,
            key="custom_fact",
        ),
    )
    _assert_clean_error(revision)

    control = models.RegistrationProfileExtensionValueControl(
        organization_id=ORG,
        edition_id=EDITION,
        field_key="custom_fact",
        current_sequence=1,
    )
    _bind(
        control,
        "registration",
        SimpleNamespace(organization_id=OTHER_ORG, edition_id=EDITION),
    )
    _assert_clean_error(control, "profile_value_control_scope_mismatch")

    control.registration_id = UUID(int=40)
    control._state.fields_cache["registration"] = SimpleNamespace(
        organization_id=ORG,
        edition_id=EDITION,
    )
    _bind(
        control,
        "latest_revision",
        SimpleNamespace(
            registration_id=UUID(int=41),
            organization_id=ORG,
            edition_id=EDITION,
            field_key="custom_fact",
            sequence=1,
        ),
    )
    _assert_clean_error(control, "profile_value_control_revision_mismatch")

    receipt = models.RegistrationProfileExtensionValueCommandReceipt(
        organization_id=ORG,
        edition_id=EDITION,
    )
    _bind(
        receipt,
        "registration",
        SimpleNamespace(organization_id=OTHER_ORG, edition_id=EDITION),
    )
    _assert_clean_error(receipt, "profile_value_receipt_scope_mismatch")


def test_profile_value_receipt_checks_control_field_revision_and_immutability() -> None:
    receipt = models.RegistrationProfileExtensionValueCommandReceipt(
        registration_id=UUID(int=50),
        organization_id=ORG,
        edition_id=EDITION,
        result_sequence=2,
        source_channel="api",
        actor_id=ACCOUNT,
    )
    _bind(
        receipt,
        "registration",
        SimpleNamespace(organization_id=ORG, edition_id=EDITION),
        UUID(int=50),
    )
    _bind(
        receipt,
        "control",
        SimpleNamespace(
            registration_id=UUID(int=51),
            organization_id=ORG,
            edition_id=EDITION,
        ),
    )
    _assert_clean_error(receipt, "profile_value_receipt_control_mismatch")

    receipt.control_id = None
    receipt._state.fields_cache.pop("control", None)
    _bind(
        receipt,
        "field",
        SimpleNamespace(organization_id=OTHER_ORG, edition_id=EDITION),
    )
    _assert_clean_error(receipt, "profile_value_receipt_field_mismatch")

    receipt.field_id = UUID(int=52)
    receipt._state.fields_cache["field"] = SimpleNamespace(
        organization_id=ORG,
        edition_id=EDITION,
    )
    _bind(
        receipt,
        "revision",
        SimpleNamespace(
            registration_id=UUID(int=50),
            field_id=UUID(int=52),
            actor_id=ACCOUNT,
            sequence=99,
            source_channel="api",
        ),
    )
    _assert_clean_error(receipt, "profile_value_receipt_revision_mismatch")

    receipt._state.adding = False
    with pytest.raises(ValidationError) as immutable:
        receipt.save()
    assert _error_code(immutable.value) == "immutable_profile_value_command_receipt"
    with pytest.raises(ValidationError) as protected:
        receipt.delete()
    assert _error_code(protected.value) == "protected_profile_value_command_receipt"


def test_registration_commerce_control_and_receipts_are_scope_bound_and_retained() -> (
    None
):
    control = models.RegistrationCommerceControl(
        organization_id=ORG,
        edition_id=EDITION,
    )
    _bind(
        control,
        "configuration",
        SimpleNamespace(organization_id=OTHER_ORG, edition_id=EDITION),
        CONFIGURATION,
    )
    _assert_clean_error(control, "registration_commerce_control_scope_mismatch")
    with pytest.raises(ValidationError) as protected_control:
        control.delete()
    assert _error_code(protected_control.value) == (
        "protected_registration_commerce_control"
    )

    receipt = models.RegistrationCommerceCommandReceipt()
    receipt._state.adding = False
    with pytest.raises(ValidationError) as immutable:
        receipt.save()
    assert _error_code(immutable.value) == "immutable_registration_commerce_receipt"
    with pytest.raises(ValidationError) as protected_receipt:
        receipt.delete()
    assert _error_code(protected_receipt.value) == (
        "protected_registration_commerce_receipt"
    )


def test_capacity_adjustments_require_one_exact_configuration_scope() -> None:
    adjustment = models.RegistrationCapacityAdjustment(
        organization_id=ORG,
        edition_id=EDITION,
    )
    _bind(
        adjustment,
        "configuration",
        SimpleNamespace(organization_id=OTHER_ORG, edition_id=EDITION),
        CONFIGURATION,
    )
    _assert_clean_error(adjustment, "registration_capacity_adjustment_scope_mismatch")

    adjustment.configuration_id = CONFIGURATION
    adjustment._state.fields_cache["configuration"] = SimpleNamespace(
        organization_id=ORG,
        edition_id=EDITION,
    )
    _bind(
        adjustment,
        "control",
        SimpleNamespace(configuration_id=OTHER_CONFIGURATION),
    )
    _assert_clean_error(adjustment, "registration_capacity_adjustment_control_mismatch")

    adjustment.control_id = None
    adjustment._state.fields_cache.pop("control", None)
    _bind(
        adjustment,
        "product",
        SimpleNamespace(configuration_id=OTHER_CONFIGURATION),
    )
    _assert_clean_error(adjustment, "registration_capacity_adjustment_product_mismatch")

    with pytest.raises(ValidationError) as protected:
        adjustment.delete()
    assert _error_code(protected.value) == (
        "protected_registration_capacity_adjustment"
    )


def test_tier_replacement_and_waitlist_batch_enforce_exact_product_scope() -> None:
    replacement = models.AdmissionTierReplacement(
        organization_id=ORG,
        edition_id=EDITION,
        source_price_minor_snapshot=100,
        target_price_minor_snapshot=200,
        amount_due_minor=100,
    )
    _bind(
        replacement,
        "registration",
        SimpleNamespace(
            organization_id=OTHER_ORG,
            edition_id=EDITION,
            configuration_id=CONFIGURATION,
        ),
    )
    _assert_clean_error(replacement, "tier_replacement_scope_mismatch")

    replacement._state.fields_cache["registration"] = SimpleNamespace(
        organization_id=ORG,
        edition_id=EDITION,
        configuration_id=CONFIGURATION,
    )
    _bind(
        replacement,
        "source_product",
        SimpleNamespace(configuration_id=CONFIGURATION),
        UUID(int=61),
    )
    _bind(
        replacement,
        "target_product",
        SimpleNamespace(configuration_id=OTHER_CONFIGURATION),
        UUID(int=62),
    )
    _assert_clean_error(replacement, "tier_replacement_product_mismatch")

    replacement.source_product_id = None
    replacement.target_product_id = None
    replacement.amount_due_minor = 99
    _assert_clean_error(replacement, "tier_replacement_amount_mismatch")
    with pytest.raises(ValidationError) as protected_replacement:
        replacement.delete()
    assert _error_code(protected_replacement.value) == (
        "protected_admission_tier_replacement"
    )

    batch = models.WaitlistBatchOffer(
        organization_id=ORG,
        edition_id=EDITION,
    )
    _bind(
        batch,
        "configuration",
        SimpleNamespace(organization_id=OTHER_ORG, edition_id=EDITION),
        CONFIGURATION,
    )
    _bind(batch, "product", SimpleNamespace(configuration_id=CONFIGURATION))
    _bind(batch, "control", SimpleNamespace(configuration_id=CONFIGURATION))
    _assert_clean_error(batch, "registration_waitlist_batch_scope_mismatch")
    batch._state.adding = False
    with pytest.raises(ValidationError) as immutable_batch:
        batch.save()
    assert _error_code(immutable_batch.value) == "immutable_waitlist_batch_offer"
    with pytest.raises(ValidationError) as protected_batch:
        batch.delete()
    assert _error_code(protected_batch.value) == "protected_waitlist_batch_offer"


def test_payment_provider_host_policy_is_enforced_for_enabled_adapters(
    settings: Any,
) -> None:
    settings.MARU_PAYMENT_PROVIDER_HOSTS = ("payments.example.test",)
    provider = models.PaymentProviderAccount(
        enabled=True,
        api_base_url="https://attacker.example.test/api",
    )
    _assert_clean_error(provider, "payment_provider_host_not_allowed")


def test_payment_intent_validates_optional_tier_replacement_as_one_atomic_scope() -> (
    None
):
    assert models.PaymentIntent().clean() is None

    intent = models.PaymentIntent(
        registration_id=UUID(int=70),
        organization_id=ORG,
        edition_id=EDITION,
        amount_minor=100,
        currency="EUR",
    )
    _bind(
        intent,
        "registration",
        SimpleNamespace(organization_id=ORG, edition_id=EDITION),
        UUID(int=70),
    )
    _bind(intent, "provider_account", SimpleNamespace(organization_id=ORG))
    _bind(
        intent,
        "tier_replacement",
        SimpleNamespace(
            registration_id=UUID(int=70),
            organization_id=ORG,
            edition_id=EDITION,
            amount_due_minor=100,
            currency="EUR",
        ),
    )
    assert intent.clean() is None

    intent.amount_minor = 99
    _assert_clean_error(intent, "payment_intent_tier_replacement_mismatch")


def test_payment_attempts_are_append_only_and_retained() -> None:
    attempt = models.PaymentAttempt()
    attempt._state.adding = False
    with pytest.raises(ValidationError) as immutable:
        attempt.save()
    assert _error_code(immutable.value) == "immutable_payment_attempt"
    with pytest.raises(ValidationError) as protected:
        attempt.delete()
    assert _error_code(protected.value) == "protected_payment_attempt"


def test_financial_models_reject_cross_tenant_relationships() -> None:
    operation = models.FinancialOperation(
        organization_id=ORG,
        edition_id=EDITION,
        currency="EUR",
    )
    _bind(
        operation,
        "registration",
        SimpleNamespace(
            organization_id=OTHER_ORG,
            edition_id=EDITION,
            currency_snapshot="EUR",
        ),
    )
    _assert_clean_error(operation, "financial_operation_scope_mismatch")

    ledger = models.FinancialLedgerEntry(
        organization_id=ORG,
        edition_id=EDITION,
    )
    _bind(
        ledger,
        "registration",
        SimpleNamespace(organization_id=OTHER_ORG, edition_id=EDITION),
    )
    _assert_clean_error(ledger, "financial_ledger_registration_scope_mismatch")

    ledger.registration_id = UUID(int=71)
    ledger._state.fields_cache["registration"] = SimpleNamespace(
        organization_id=ORG,
        edition_id=EDITION,
    )
    _bind(
        ledger,
        "operation",
        SimpleNamespace(
            organization_id=ORG,
            edition_id=EDITION,
            registration_id=UUID(int=72),
        ),
    )
    _assert_clean_error(ledger, "financial_ledger_operation_scope_mismatch")

    ledger.operation_id = None
    ledger._state.fields_cache.pop("operation", None)
    _bind(ledger, "provider_account", SimpleNamespace(organization_id=OTHER_ORG))
    _assert_clean_error(ledger, "financial_ledger_provider_scope_mismatch")


def test_settlement_allocation_and_receipt_require_matching_ledger_scope() -> None:
    allocation = models.SettlementAllocation()
    _bind(
        allocation,
        "settlement",
        SimpleNamespace(
            organization_id=ORG,
            edition_id=EDITION,
            currency="EUR",
            provider_account_id=UUID(int=80),
        ),
    )
    _bind(
        allocation,
        "ledger_entry",
        SimpleNamespace(
            organization_id=OTHER_ORG,
            edition_id=EDITION,
            currency="EUR",
            provider_account_id=UUID(int=80),
        ),
    )
    with pytest.raises(ValidationError) as allocation_error:
        allocation.save()
    assert _error_code(allocation_error.value) == (
        "settlement_allocation_scope_mismatch"
    )

    receipt = models.ReceiptRecord(
        registration_id=UUID(int=81),
        organization_id=ORG,
        edition_id=EDITION,
    )
    _bind(
        receipt,
        "registration",
        SimpleNamespace(organization_id=ORG, edition_id=EDITION),
        UUID(int=81),
    )
    _bind(
        receipt,
        "ledger_entry",
        SimpleNamespace(
            registration_id=UUID(int=82),
            organization_id=ORG,
            edition_id=EDITION,
        ),
    )
    _assert_clean_error(receipt, "receipt_ledger_scope_mismatch")


def test_string_representations_remain_operator_safe_and_scope_specific() -> None:
    configuration = SimpleNamespace(edition=SimpleNamespace(name="Maru 2026"))
    section = models.RegistrationSection(title="Attendee details")
    _bind(section, "configuration", configuration)
    assert str(section) == "Maru 2026: Attendee details"

    profile = _profile()
    _bind(profile, "registration", SimpleNamespace(reference="REG-2026-0001"))
    assert str(profile) == "REG-2026-0001: registration profile"

    fursuit = models.AttendeeFursuit(name="Aurora")
    _bind(
        fursuit,
        "profile",
        SimpleNamespace(registration=SimpleNamespace(reference="REG-2026-0001")),
    )
    assert str(fursuit) == "REG-2026-0001: Aurora"

    entitlement = models.Entitlement(label_snapshot="Standard admission")
    _bind(entitlement, "registration", SimpleNamespace(reference="REG-2026-0001"))
    assert str(entitlement) == "REG-2026-0001: Standard admission"

    timeline = models.RegistrationTimelineEntry(title="Registration confirmed")
    _bind(timeline, "registration", SimpleNamespace(reference="REG-2026-0001"))
    assert str(timeline) == "REG-2026-0001: Registration confirmed"


def test_check_in_records_are_append_only_and_reconciled_on_delete() -> None:
    check_in = models.CheckInRecord()
    check_in._state.adding = False
    with pytest.raises(ValidationError) as immutable:
        check_in.save()
    assert _error_code(immutable.value) == "immutable_check_in"
    with pytest.raises(ValidationError) as protected:
        check_in.delete()
    assert _error_code(protected.value) == "protected_check_in"
