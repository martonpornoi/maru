from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from maru.registration.models import (
    AdmissionProduct,
    ConfigurationStatus,
    MinorRegistrationPolicy,
    QuestionFieldType,
    RegistrationQuestion,
    RegistrationSection,
    RegistrationTemplateProduct,
    RegistrationTemplateQuestion,
    RegistrationTemplateSection,
    TemplateStatus,
)
from tests.factories import (
    AccountFactory,
    AdmissionProductFactory,
    RegistrationConfigurationFactory,
    RegistrationTemplateFactory,
)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


def test_published_template_and_active_configuration_children_are_immutable() -> None:
    template = RegistrationTemplateFactory()
    template_section = RegistrationTemplateSection.objects.create(
        template=template,
        key="identity",
        title="Identity",
        position=10,
    )
    template_question = RegistrationTemplateQuestion.objects.create(
        template=template,
        section=template_section,
        key="badge-name",
        label="Badge name",
        field_type=QuestionFieldType.SHORT_TEXT,
        required=True,
        position=10,
        purpose="Print the credential.",
    )
    template_product = RegistrationTemplateProduct.objects.create(
        template=template,
        code="weekend",
        name="Weekend",
        price_minor=10_000,
        capacity=100,
        position=10,
        entitlement_code="admission",
        entitlement_name="Admission",
    )
    assert "Identity" in str(template_section)
    assert "Badge name" in str(template_question)
    assert "Weekend" in str(template_product)
    template.status = TemplateStatus.PUBLISHED
    template.published_at = timezone.now()
    template.save()

    template.name = "Rewritten published template"
    with pytest.raises(ValidationError, match="immutable"):
        template.save()
    with pytest.raises(ValidationError, match="versioning"):
        template.delete()
    for child in (template_section, template_question, template_product):
        with pytest.raises(ValidationError, match=r"immutable|draft"):
            child.save()
        with pytest.raises(ValidationError, match="immutable"):
            child.delete()

    configuration = RegistrationConfigurationFactory()
    section = RegistrationSection.objects.create(
        configuration=configuration,
        key="identity",
        title="Identity",
        position=10,
    )
    question = RegistrationQuestion.objects.create(
        configuration=configuration,
        section=section,
        key="badge-name",
        label="Badge name",
        field_type=QuestionFieldType.SHORT_TEXT,
        required=True,
        position=10,
        purpose="Print the credential.",
    )
    product = AdmissionProductFactory(configuration=configuration)
    configuration.status = ConfigurationStatus.ACTIVE
    configuration.review_required = False
    configuration.review_note = "Reviewed for activation."
    configuration.activated_at = timezone.now()
    configuration.save()

    configuration.name = "Rewritten active version"
    with pytest.raises(ValidationError, match="immutable"):
        configuration.save()
    with pytest.raises(ValidationError, match="versioning"):
        configuration.delete()
    for child in (section, question, product):
        with pytest.raises(ValidationError, match=r"immutable|draft"):
            child.save()
        with pytest.raises(ValidationError, match="immutable"):
            child.delete()


def test_product_and_minor_policy_validation_explain_invalid_configuration() -> None:
    configuration = RegistrationConfigurationFactory(minimum_age=13)

    def product(**overrides):
        values = {
            "configuration": configuration,
            "code": f"product-{uuid4()}",
            "name": "Synthetic",
            "price_minor": 100,
            "capacity": 10,
            "position": 10,
            "entitlement_code": f"entitlement-{uuid4()}",
            "entitlement_name": "Synthetic",
        }
        values.update(overrides)
        return AdmissionProduct(**values)

    now = timezone.now()
    with pytest.raises(ValidationError, match="close after"):
        product(sales_open_at=now, sales_close_at=now).full_clean()
    with pytest.raises(ValidationError, match="stable codes"):
        product(required_capacity_codes="not-a-list").full_clean()
    with pytest.raises(ValidationError, match="unique"):
        product(required_capacity_codes=["volunteer", "volunteer"]).full_clean()
    with pytest.raises(ValidationError, match="explanation"):
        product(required_capacity_codes=["volunteer"]).full_clean()

    reviewer = AccountFactory()
    invalid_age = MinorRegistrationPolicy(
        configuration=configuration,
        enabled=True,
        minor_age_threshold=13,
        guardian_notice_version="guardian-v1",
        jurisdiction_code="synthetic",
        review_reference="LEGAL-1",
        reviewed_by=reviewer,
        reviewed_at=now,
    )
    with pytest.raises(ValidationError, match="above"):
        invalid_age.full_clean()
    missing_review = MinorRegistrationPolicy(
        configuration=configuration,
        enabled=True,
        minor_age_threshold=18,
        guardian_notice_version="",
        jurisdiction_code="",
        review_reference="",
        reviewed_by=reviewer,
        reviewed_at=now,
    )
    with pytest.raises(ValidationError, match="jurisdiction evidence"):
        missing_review.full_clean()

    policy = MinorRegistrationPolicy.objects.create(
        configuration=configuration,
        enabled=True,
        minor_age_threshold=18,
        guardian_notice_version="guardian-v1",
        jurisdiction_code="synthetic",
        review_reference="LEGAL-1",
        reviewed_by=reviewer,
        reviewed_at=now,
    )
    configuration.status = ConfigurationStatus.ACTIVE
    configuration.review_required = False
    configuration.review_note = "Reviewed with guardian policy."
    configuration.activated_at = now
    configuration.save()
    with pytest.raises(ValidationError, match="before form activation"):
        policy.full_clean()
