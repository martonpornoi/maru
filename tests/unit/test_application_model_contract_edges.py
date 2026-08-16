"""Model-level lifecycle and provenance invariants for typed Applications."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import models as django_models

from maru.applications import models
from maru.applications.models import (
    AnswerSource,
    ApplicationAnswerRevision,
    ApplicationClassification,
    ApplicationCommandReceipt,
    ApplicationDefinition,
    ApplicationDefinitionStatus,
    ApplicationEligibilityKind,
    ApplicationFileReceipt,
    ApplicationOwnerDepartment,
    ApplicationQuestion,
    ApplicationQuestionType,
    ApplicationReviewDecision,
    ApplicationReviewerPerson,
    ApplicationReviewerRole,
    ApplicationSection,
    ApplicationSourceBinding,
    ApplicationState,
    ApplicationSubmission,
    ApplicationTargetKind,
    ApplicationTargetRecord,
)
from maru.authorization.models import RoleBundle
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import Organization
from maru.workforce.models import Department


def _account() -> Account:
    return Account(id=uuid4(), email="model-contract@example.invalid")


def _scope() -> tuple[Organization, EventEdition]:
    organization = Organization(id=uuid4(), name="Synthetic Organizer")
    edition = EventEdition(id=uuid4(), organization=organization)
    return organization, edition


def _definition(**overrides: object) -> ApplicationDefinition:
    organization, edition = _scope()
    opened = datetime(2031, 8, 1, tzinfo=UTC)
    values: dict[str, object] = {
        "id": uuid4(),
        "organization": organization,
        "edition": edition,
        "code": "volunteer-application",
        "version": 1,
        "status": ApplicationDefinitionStatus.DRAFT,
        "target_adapter_kind": ApplicationTargetKind.VOLUNTEER,
        "name": "Volunteer application",
        "description": "Help the event.",
        "purpose": "Volunteer intake",
        "classification": ApplicationClassification.PERSONAL,
        "eligibility_kind": ApplicationEligibilityKind.AUTHENTICATED_PERSON,
        "max_submissions_per_person": 1,
        "opens_at": opened,
        "closes_at": opened + timedelta(days=10),
        "applicant_edit_until": opened + timedelta(days=9),
        "minimum_age": 0,
        "audience_policy_code": "",
        "retention_policy_code": "",
        "age_policy_code": "",
        "created_by": _account(),
    }
    values.update(overrides)
    return ApplicationDefinition(**values)


def _question(
    *,
    definition: ApplicationDefinition | None = None,
    **overrides: object,
) -> ApplicationQuestion:
    definition = definition or _definition()
    section = ApplicationSection(
        id=uuid4(),
        definition=definition,
        key="main",
        title="Main",
        position=1,
    )
    values: dict[str, object] = {
        "id": uuid4(),
        "definition": definition,
        "section": section,
        "key": "motivation",
        "field_type": ApplicationQuestionType.LONG_TEXT,
        "label": "Motivation",
        "position": 1,
        "options": [],
        "purpose": "Volunteer review",
        "classification": ApplicationClassification.PERSONAL,
        "applicant_visible": True,
        "applicant_writable": True,
        "staff_visible": True,
        "staff_writable": False,
        "reviewer_visible": True,
        "public_after_approval": False,
        "api_projection": True,
        "condition": {},
        "source_binding": "",
        "reference_kind": "",
    }
    values.update(overrides)
    return ApplicationQuestion(**values)


@pytest.mark.parametrize(
    ("classification", "target_kind", "sensitive"),
    [
        (ApplicationClassification.INTERNAL, ApplicationTargetKind.VOLUNTEER, False),
        (ApplicationClassification.RESTRICTED, ApplicationTargetKind.VOLUNTEER, True),
        (
            ApplicationClassification.PERSONAL,
            ApplicationTargetKind.DAMAGE_REPORT,
            True,
        ),
        (
            ApplicationClassification.PERSONAL,
            ApplicationTargetKind.ADULT_FURSUIT_STRIPTEASE,
            True,
        ),
    ],
)
def test_definition_sensitive_discriminator_is_closed(
    classification: str,
    target_kind: str,
    sensitive: bool,
) -> None:
    definition = _definition(
        classification=classification,
        target_adapter_kind=target_kind,
    )
    assert definition.is_sensitive is sensitive
    assert definition.requires_explicit_age_policy is (
        target_kind == ApplicationTargetKind.ADULT_FURSUIT_STRIPTEASE
    )


def test_definition_clean_requires_exact_scope_and_ordered_windows() -> None:
    definition = _definition()
    definition.clean()

    foreign = Organization(id=uuid4())
    definition.edition.organization = foreign
    with pytest.raises(ValidationError, match="match its edition"):
        definition.clean()

    definition = _definition()
    definition.closes_at = definition.opens_at
    with pytest.raises(ValidationError) as caught:
        definition.clean()
    assert "closes_at" in caught.value.message_dict

    definition = _definition()
    definition.applicant_edit_until = definition.closes_at + timedelta(seconds=1)
    with pytest.raises(ValidationError) as caught:
        definition.clean()
    assert "applicant_edit_until" in caught.value.message_dict


def test_adult_and_sensitive_activation_require_explicit_policies() -> None:
    adult = _definition(
        status=ApplicationDefinitionStatus.ACTIVE,
        target_adapter_kind=ApplicationTargetKind.ADULT_FURSUIT_STRIPTEASE,
        classification=ApplicationClassification.RESTRICTED,
        minimum_age=17,
    )
    with pytest.raises(ValidationError) as caught:
        adult.clean()
    assert "minimum_age" in caught.value.error_dict

    adult.minimum_age = 18
    for audience, retention in (
        ("", ""),
        ("default", "policy.v1"),
        ("policy.v1", "generic"),
    ):
        adult.audience_policy_code = audience
        adult.retention_policy_code = retention
        with pytest.raises(ValidationError) as caught:
            adult.clean()
        assert caught.value.code == "explicit_sensitive_application_policy_required"

    adult.audience_policy_code = "adult.audience.v1"
    adult.retention_policy_code = "adult.retention.v1"
    adult.age_policy_code = "standard"
    with pytest.raises(ValidationError) as caught:
        adult.clean()
    assert "age_policy_code" in caught.value.error_dict

    adult.age_policy_code = "adult.age.v1"
    adult.clean()


def test_owner_department_requires_current_exact_edition_and_draft() -> None:
    definition = _definition()
    department = Department(
        id=uuid4(),
        organization=definition.organization,
        edition=definition.edition,
        name="Human Resources",
    )
    link = ApplicationOwnerDepartment(definition=definition, department=department)
    link.clean()

    department.retired_at = datetime(2031, 8, 1, tzinfo=UTC)
    with pytest.raises(ValidationError):
        link.clean()
    department.retired_at = None
    department.organization = Organization(id=uuid4())
    with pytest.raises(ValidationError):
        link.clean()

    department.organization = definition.organization
    definition.status = ApplicationDefinitionStatus.ACTIVE
    with pytest.raises(ValidationError, match="frozen"):
        link.clean()


def test_reviewer_role_requires_owner_scope_and_capability_set() -> None:
    definition = _definition()
    role = RoleBundle(
        id=uuid4(),
        organization=definition.organization,
        name="Reviewers",
        version=1,
        capability_codes=["applications.review"],
    )
    link = ApplicationReviewerRole(definition=definition, role_bundle=role)
    link.clean()

    role.organization = Organization(id=uuid4())
    with pytest.raises(ValidationError):
        link.clean()
    role.organization = definition.organization
    role.capability_codes = []
    with pytest.raises(ValidationError):
        link.clean()

    definition.classification = ApplicationClassification.RESTRICTED
    role.capability_codes = ["applications.review"]
    with pytest.raises(ValidationError):
        link.clean()
    role.capability_codes = ["applications.review", "applications.review_sensitive"]
    link.clean()

    definition.status = ApplicationDefinitionStatus.ACTIVE
    with pytest.raises(ValidationError, match="frozen"):
        link.clean()


def test_named_reviewer_validates_subject_and_freezes_on_activation() -> None:
    definition = _definition()
    reviewer = _account()
    link = ApplicationReviewerPerson(definition=definition, account=reviewer)
    with patch.object(models, "validate_convention_subject") as validate:
        link.clean()
    validate.assert_called_once_with(reviewer, field_name="account")

    definition.status = ApplicationDefinitionStatus.ACTIVE
    with pytest.raises(ValidationError, match="frozen"):
        link.clean()


def test_sections_freeze_after_activation() -> None:
    definition = _definition(status=ApplicationDefinitionStatus.ACTIVE)
    section = ApplicationSection(
        definition=definition, key="main", title="Main", position=1
    )
    with pytest.raises(ValidationError, match="immutable"):
        section.clean()


@pytest.mark.parametrize(
    ("field_type", "options"),
    [
        (ApplicationQuestionType.LONG_TEXT, "not-a-list"),
        (ApplicationQuestionType.SINGLE_CHOICE, []),
        (ApplicationQuestionType.LONG_TEXT, [{"code": "one", "label": "One"}]),
        (ApplicationQuestionType.SINGLE_CHOICE, [{"code": "one"}, {"code": "two"}]),
        (
            ApplicationQuestionType.SINGLE_CHOICE,
            [{"code": "", "label": "One"}, {"code": "two", "label": "Two"}],
        ),
        (
            ApplicationQuestionType.SINGLE_CHOICE,
            [{"code": "one", "label": "One"}, {"code": "one", "label": "Again"}],
        ),
    ],
)
def test_question_option_validation_rejects_open_or_invalid_shapes(
    field_type: str,
    options: object,
) -> None:
    with pytest.raises(ValidationError):
        models._validate_options(field_type, options)


def test_question_option_validation_accepts_two_unique_bounded_choices() -> None:
    models._validate_options(
        ApplicationQuestionType.SINGLE_CHOICE,
        [{"code": "one", "label": "One"}, {"code": "two", "label": "Two"}],
    )


def test_question_clean_enforces_schema_relations_and_closed_constraints() -> None:
    question = _question()
    question.clean()

    foreign_section = ApplicationSection(
        id=uuid4(),
        definition=_definition(),
        key="foreign",
        title="Foreign",
        position=1,
    )
    question.section = foreign_section
    with pytest.raises(ValidationError):
        question.clean()

    cases = (
        {"minimum_length": 5, "maximum_length": 4},
        {"minimum_value": 2, "maximum_value": 1},
        {
            "field_type": ApplicationQuestionType.MULTIPLE_CHOICE,
            "options": [
                {"code": "one", "label": "One"},
                {"code": "two", "label": "Two"},
            ],
            "maximum_choices": None,
        },
        {"maximum_choices": 1},
        {"field_type": ApplicationQuestionType.PERSON_REFERENCE, "reference_kind": ""},
        {"field_type": ApplicationQuestionType.LONG_TEXT, "reference_kind": "person"},
        {
            "source_binding": ApplicationSourceBinding.ACCOUNT_DISPLAY_NAME,
            "applicant_writable": True,
        },
        {"condition": []},
        {"condition": {"question_key": "kind"}},
        {
            "condition": {
                "question_key": "kind",
                "operator": "future",
                "value": "one",
            }
        },
        {
            "public_after_approval": True,
            "classification": ApplicationClassification.PERSONAL,
        },
    )
    for overrides in cases:
        invalid = _question(**overrides)
        with pytest.raises(ValidationError):
            invalid.clean()

    active = _definition(
        status=ApplicationDefinitionStatus.ACTIVE,
        retention_policy_code="",
    )
    sensitive = _question(
        definition=active,
        classification=ApplicationClassification.RESTRICTED,
        retention_policy_code="",
    )
    with pytest.raises(ValidationError):
        sensitive.clean()

    active.status = ApplicationDefinitionStatus.ACTIVE
    ordinary = _question(definition=active)
    with pytest.raises(ValidationError, match="immutable"):
        ordinary.clean()


def test_submission_scope_and_subject_are_validated() -> None:
    definition = _definition()
    submission = ApplicationSubmission(
        organization=definition.organization,
        edition=definition.edition,
        definition=definition,
        account=_account(),
        ordinal=1,
    )
    with patch.object(models, "validate_convention_subject") as validate:
        submission.clean()
    validate.assert_called_once_with(submission.account, field_name="account")

    submission.organization = Organization(id=uuid4())
    with pytest.raises(ValidationError, match="definition scope"):
        submission.clean()
    submission.organization = definition.organization
    submission.edition.organization = Organization(id=uuid4())
    with pytest.raises(ValidationError, match="edition scope"):
        submission.clean()


def test_file_receipt_scope_digest_and_retention_are_closed() -> None:
    organization, edition = _scope()
    receipt = ApplicationFileReceipt(
        organization=organization,
        edition=edition,
        account=_account(),
        status=ApplicationFileReceipt.Status.CLEAN,
        sha256="a" * 64,
        size_bytes=1,
        media_type="application/pdf",
        storage_key="synthetic/file",
        scanner_receipt="scanner-1",
    )
    with patch.object(models, "validate_convention_subject"):
        receipt.clean()
    receipt.sha256 = "A" * 64
    with pytest.raises(ValidationError):
        receipt.clean()
    receipt.edition.organization = Organization(id=uuid4())
    with pytest.raises(ValidationError, match="edition scope"):
        receipt.clean()
    with pytest.raises(ValidationError, match="retention"):
        receipt.delete()
    receipt._state.adding = False
    with pytest.raises(ValidationError, match="immutable"):
        receipt.save()


def test_answer_revision_snapshots_and_append_only_boundary() -> None:
    definition = _definition()
    submission = ApplicationSubmission(
        id=uuid4(),
        organization=definition.organization,
        edition=definition.edition,
        definition=definition,
        account=_account(),
        ordinal=1,
    )
    question = _question(definition=definition)
    revision = ApplicationAnswerRevision(
        submission=submission,
        question=question,
        sequence=1,
        question_key=question.key,
        question_type=question.field_type,
        classification=question.classification,
        value="Help",
        source=AnswerSource.APPLICANT,
        actor=submission.account,
    )
    revision.clean()
    revision.question_key = "forged"
    with pytest.raises(ValidationError, match="authoritative"):
        revision.clean()
    revision.question_key = question.key
    question.definition = _definition()
    with pytest.raises(ValidationError):
        revision.clean()
    revision._state.adding = False
    with pytest.raises(ValidationError) as caught:
        revision.save()
    assert caught.value.code == "immutable_application_answer"
    with pytest.raises(ValidationError) as caught:
        revision.delete()
    assert caught.value.code == "protected_application_answer"


def test_review_target_and_command_evidence_are_append_only() -> None:
    decision = ApplicationReviewDecision()
    decision._state.adding = False
    with pytest.raises(ValidationError) as caught:
        decision.save()
    assert caught.value.code == "immutable_application_review"
    with pytest.raises(ValidationError) as caught:
        decision.delete()
    assert caught.value.code == "protected_application_review"

    definition = _definition()
    submission = ApplicationSubmission(
        definition=definition,
        organization=definition.organization,
        edition=definition.edition,
        account=_account(),
        ordinal=1,
        state=ApplicationState.ACCEPTED,
    )
    target = ApplicationTargetRecord(
        submission=submission,
        adapter_kind=definition.target_adapter_kind,
        created_by=_account(),
    )
    target.clean()
    target.adapter_kind = ApplicationTargetKind.DJ_SET
    with pytest.raises(ValidationError):
        target.clean()
    target._state.adding = False
    with pytest.raises(ValidationError, match="immutable"):
        target.save()
    with pytest.raises(ValidationError, match="retained"):
        target.delete()

    receipt = ApplicationCommandReceipt()
    receipt._state.adding = False
    with pytest.raises(ValidationError, match="append-only"):
        receipt.save()
    with pytest.raises(ValidationError, match="retained"):
        receipt.delete()


def test_key_and_code_saves_normalize_before_model_boundary() -> None:
    definition = _definition(code="VOLUNTEER-APPLICATION")
    section = ApplicationSection(
        definition=definition,
        key="MAIN",
        title="Main",
        position=1,
    )
    question = _question(definition=definition, key="MOTIVATION")
    with (
        patch.object(django_models.Model, "save"),
        patch.object(definition, "full_clean"),
    ):
        definition.save()
    assert definition.code == "volunteer-application"
    with (
        patch.object(django_models.Model, "save"),
        patch.object(section, "full_clean"),
    ):
        section.save()
    assert section.key == "main"
    with (
        patch.object(django_models.Model, "save"),
        patch.object(question, "full_clean"),
    ):
        question.save()
    assert question.key == "motivation"


def test_unsaved_named_reviewer_without_account_has_no_subject_to_validate() -> None:
    reviewer = ApplicationReviewerPerson()
    with patch.object(models, "validate_convention_subject") as validate:
        reviewer.clean()
    validate.assert_not_called()


def test_new_file_receipt_crosses_the_validated_save_boundary() -> None:
    receipt = ApplicationFileReceipt()
    receipt._state.adding = True
    with (
        patch.object(receipt, "full_clean") as full_clean,
        patch.object(django_models.Model, "save") as save,
    ):
        receipt.save()
    full_clean.assert_called_once_with()
    save.assert_called_once()
