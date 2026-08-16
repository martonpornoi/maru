from datetime import timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.effects.models import DomainEvent, OutboxMessage
from maru.registration.models import (
    ConfigurationStatus,
    QuestionFieldType,
    QuestionVisibility,
    RegistrationConfiguration,
    RegistrationQuestion,
    RegistrationSection,
    RegistrationTemplate,
    RegistrationTemplateProduct,
    RegistrationTemplateQuestion,
    RegistrationTemplateSection,
    TemplateStatus,
)
from maru.registration.services import (
    activate_configuration,
    create_configuration_draft,
)
from tests.factories import (
    AccountFactory,
    AdmissionProductFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    RegistrationConfigurationFactory,
    RegistrationTemplateFactory,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]


def _published_template():
    edition = EventEditionFactory()
    actor = AccountFactory()
    template = RegistrationTemplateFactory(
        organization=edition.organization,
        series=edition.series,
        code="attendee-registration",
        name="Attendee registration",
        created_by_id=actor.id,
    )
    section = RegistrationTemplateSection.objects.create(
        template=template,
        key="attendee-details",
        title="Attendee details",
        description="Reusable profile questions.",
        position=10,
    )
    RegistrationTemplateQuestion.objects.create(
        template=template,
        section=section,
        key="badge-name",
        label="Badge name",
        field_type=QuestionFieldType.SHORT_TEXT,
        required=True,
        position=10,
        purpose="Print the attendee badge.",
    )
    RegistrationTemplateProduct.objects.create(
        template=template,
        code="weekend",
        name="Weekend admission",
        price_minor=10_000,
        capacity=120,
        position=10,
        entitlement_code="event-admission",
        entitlement_name="Event admission",
    )
    template.status = TemplateStatus.PUBLISHED
    template.published_at = timezone.now()
    template.save(update_fields=("status", "published_at", "updated_at"))
    return edition, actor, template


def test_template_import_is_copy_on_write_reviewed_and_audited() -> None:
    source_edition, actor, template = _published_template()
    target = EventEditionFactory(
        organization=source_edition.organization,
        series=source_edition.series,
    )
    CapabilityGrantFactory(
        organization=target.organization,
        edition=target,
        principal=actor,
        capability_code="registration.manage_configuration",
    )
    correlation_id = uuid4()

    draft = create_configuration_draft(
        organization_id=target.organization_id,
        edition_id=target.id,
        actor=actor,
        name="Target registration",
        reason="Start from the reviewed annual setup.",
        correlation_id=correlation_id,
        source_template_id=template.id,
        opens_at=timezone.now() - timedelta(days=1),
        closes_at=timezone.now() + timedelta(days=30),
        capacity=200,
        currency="EUR",
    )

    assert draft.status == ConfigurationStatus.DRAFT
    assert draft.review_required is True
    assert draft.source_template_id == template.id
    assert draft.sections.get().title == "Attendee details"
    assert draft.questions.get().label == "Badge name"
    assert draft.questions.get().section == draft.sections.get()
    assert draft.products.get().name == "Weekend admission"
    assert AuditEvent.objects.get(correlation_id=correlation_id).outcome == "allow"
    event = DomainEvent.objects.get(correlation_id=correlation_id)
    assert event.event_name == "registration.configuration.draft_created.v1"
    assert OutboxMessage.objects.get(event=event).status == "pending"

    target_question = draft.questions.get()
    target_question.label = "Name printed on badge"
    target_question.save()
    assert template.questions.get().label == "Badge name"


def test_published_template_and_active_configuration_are_database_immutable() -> None:
    source_edition, actor, template = _published_template()
    target = EventEditionFactory(
        organization=source_edition.organization,
        series=source_edition.series,
    )
    CapabilityGrantFactory(
        organization=target.organization,
        edition=target,
        principal=actor,
        capability_code="registration.manage_configuration",
    )
    draft = create_configuration_draft(
        organization_id=target.organization_id,
        edition_id=target.id,
        actor=actor,
        name="Target registration",
        reason="Prepare the target.",
        correlation_id=uuid4(),
        source_template_id=template.id,
        opens_at=timezone.now() - timedelta(days=1),
        closes_at=timezone.now() + timedelta(days=30),
        capacity=200,
        currency="EUR",
    )
    activation_id = uuid4()
    active = activate_configuration(
        organization_id=target.organization_id,
        edition_id=target.id,
        configuration_id=draft.id,
        actor=actor,
        reason="Questions, prices, dates, capacity, and wording reviewed.",
        correlation_id=activation_id,
    )

    assert active.status == ConfigurationStatus.ACTIVE
    assert active.review_required is False
    assert (
        DomainEvent.objects.get(correlation_id=activation_id).event_name
        == "registration.configuration.activated.v1"
    )
    with transaction.atomic(), pytest.raises(IntegrityError):
        RegistrationQuestion.objects.filter(configuration=active).update(
            label="Silently changed"
        )
    with transaction.atomic(), pytest.raises(IntegrityError):
        RegistrationTemplateQuestion.objects.filter(template=template).update(
            label="Silently changed"
        )
    with transaction.atomic(), pytest.raises(IntegrityError):
        RegistrationSection.objects.filter(configuration=active).update(
            title="Silently changed"
        )
    with transaction.atomic(), pytest.raises(IntegrityError):
        RegistrationTemplateSection.objects.filter(template=template).update(
            title="Silently changed"
        )


def test_configuration_with_zero_custom_questions_can_be_activated() -> None:
    source_edition, actor, template = _published_template()
    target = EventEditionFactory(
        organization=source_edition.organization,
        series=source_edition.series,
    )
    CapabilityGrantFactory(
        organization=target.organization,
        edition=target,
        principal=actor,
        capability_code="registration.manage_configuration",
    )
    draft = create_configuration_draft(
        organization_id=target.organization_id,
        edition_id=target.id,
        actor=actor,
        name="Typed-profile-only registration",
        reason="Use the typed profile without convention-specific questions.",
        correlation_id=uuid4(),
        source_template_id=template.id,
        opens_at=timezone.now() - timedelta(days=1),
        closes_at=timezone.now() + timedelta(days=30),
        capacity=200,
        currency="EUR",
    )
    draft.questions.all().delete()

    active = activate_configuration(
        organization_id=target.organization_id,
        edition_id=target.id,
        configuration_id=draft.id,
        actor=actor,
        reason="Typed profile, admission product, dates, and policy reviewed.",
        correlation_id=uuid4(),
    )

    assert active.status == ConfigurationStatus.ACTIVE
    assert active.questions.count() == 0


def test_explicit_zero_capacity_is_rejected_instead_of_inherited() -> None:
    source = EventEditionFactory()
    source_configuration = RegistrationConfigurationFactory(
        edition=source,
        capacity=400,
    )
    RegistrationConfiguration.objects.filter(pk=source_configuration.pk).update(
        status=ConfigurationStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    target = EventEditionFactory(
        organization=source.organization,
        series=source.series,
    )
    actor = AccountFactory()
    CapabilityGrantFactory(
        organization=target.organization,
        edition=target,
        principal=actor,
        capability_code="registration.manage_configuration",
    )

    with pytest.raises(ValidationError, match="between 1 and 1000000"):
        create_configuration_draft(
            organization_id=target.organization_id,
            edition_id=target.id,
            actor=actor,
            name="Invalid inherited registration",
            reason="Prove explicit zero is not treated as omission.",
            correlation_id=uuid4(),
            source_edition_id=source.id,
            capacity=0,
        )

    assert not RegistrationConfiguration.objects.filter(edition=target).exists()


@pytest.mark.parametrize(
    (
        "source_type",
        "source_options",
        "source_visibility",
        "source_position",
        "dependent_position",
        "condition_value",
        "message",
    ),
    [
        (
            QuestionFieldType.BOOLEAN,
            [],
            QuestionVisibility.ATTENDEE_AND_STAFF,
            20,
            10,
            "true",
            "earlier question",
        ),
        (
            QuestionFieldType.BOOLEAN,
            [],
            QuestionVisibility.ATTENDEE_AND_STAFF,
            10,
            20,
            "yes",
            "cannot be produced",
        ),
        (
            QuestionFieldType.SINGLE_CHOICE,
            ["alpha", "beta"],
            QuestionVisibility.ATTENDEE_AND_STAFF,
            10,
            20,
            "gamma",
            "cannot be produced",
        ),
        (
            QuestionFieldType.MULTIPLE_CHOICE,
            ["alpha", "beta"],
            QuestionVisibility.ATTENDEE_AND_STAFF,
            10,
            20,
            "alpha",
            "cannot be produced",
        ),
        (
            QuestionFieldType.BOOLEAN,
            [],
            QuestionVisibility.REGISTRATION_STAFF,
            10,
            20,
            "true",
            "staff-only question",
        ),
    ],
)
def test_activation_rejects_unreachable_conditional_question_graphs(
    source_type: str,
    source_options: list[str],
    source_visibility: str,
    source_position: int,
    dependent_position: int,
    condition_value: str,
    message: str,
) -> None:
    configuration = RegistrationConfigurationFactory()
    AdmissionProductFactory(configuration=configuration)
    RegistrationQuestion.objects.create(
        configuration=configuration,
        key="condition-source",
        label="Condition source",
        field_type=source_type,
        options=source_options,
        position=source_position,
        purpose="Drive a synthetic conditional field.",
        visibility=source_visibility,
    )
    RegistrationQuestion.objects.create(
        configuration=configuration,
        key="conditional-target",
        label="Conditional target",
        field_type=QuestionFieldType.SHORT_TEXT,
        required=True,
        position=dependent_position,
        purpose="Verify conditional graph safety.",
        condition_question_key="condition-source",
        condition_value=condition_value,
    )
    actor = AccountFactory()
    CapabilityGrantFactory(
        organization=configuration.organization,
        edition=configuration.edition,
        principal=actor,
        capability_code="registration.manage_configuration",
    )

    with pytest.raises(ValidationError, match=message):
        activate_configuration(
            organization_id=configuration.organization_id,
            edition_id=configuration.edition_id,
            configuration_id=configuration.id,
            actor=actor,
            reason="Prove the conditional form is reachable before activation.",
            correlation_id=uuid4(),
        )


def test_activation_rejects_an_overflow_instead_of_using_a_partial_form() -> None:
    configuration = RegistrationConfigurationFactory()
    AdmissionProductFactory(configuration=configuration)
    RegistrationQuestion.objects.bulk_create(
        [
            RegistrationQuestion(
                configuration=configuration,
                key=f"bounded-question-{index}",
                label=f"Bounded question {index}",
                field_type=QuestionFieldType.SHORT_TEXT,
                position=index + 1,
                purpose="Prove the setup projection is complete.",
            )
            for index in range(257)
        ]
    )
    actor = AccountFactory()
    CapabilityGrantFactory(
        organization=configuration.organization,
        edition=configuration.edition,
        principal=actor,
        capability_code="registration.manage_configuration",
    )

    with pytest.raises(ValidationError) as captured:
        activate_configuration(
            organization_id=configuration.organization_id,
            edition_id=configuration.edition_id,
            configuration_id=configuration.id,
            actor=actor,
            reason="Reject a form whose complete contents cannot be represented.",
            correlation_id=uuid4(),
        )

    assert (
        captured.value.error_dict["questions"][0].code
        == "registration_setup_limit_exceeded"
    )
    configuration.refresh_from_db()
    assert configuration.status == ConfigurationStatus.DRAFT


def test_registration_template_cannot_cross_tenant_or_series() -> None:
    _source_edition, actor, template = _published_template()
    other_tenant = EventEditionFactory()
    CapabilityGrantFactory(
        organization=other_tenant.organization,
        edition=other_tenant,
        principal=actor,
        capability_code="registration.manage_configuration",
    )

    with pytest.raises(RegistrationTemplate.DoesNotExist):
        create_configuration_draft(
            organization_id=other_tenant.organization_id,
            edition_id=other_tenant.id,
            actor=actor,
            name="Unsafe copy",
            reason="This source is outside the tenant.",
            correlation_id=uuid4(),
            source_template_id=template.id,
            opens_at=timezone.now() - timedelta(days=1),
            closes_at=timezone.now() + timedelta(days=30),
            capacity=100,
            currency="EUR",
        )

    client = APIClient()
    client.force_authenticate(actor)
    response = client.post(
        f"/api/v1/organizations/{other_tenant.organization_id}/"
        f"editions/{other_tenant.id}/registration/configuration/drafts",
        {
            "name": "Unsafe API copy",
            "reason": "This source is outside the tenant.",
            "source_template_id": str(template.id),
            "opens_at": (timezone.now() - timedelta(days=1)).isoformat(),
            "closes_at": (timezone.now() + timedelta(days=30)).isoformat(),
            "capacity": 100,
            "currency": "EUR",
        },
        format="json",
    )
    assert response.status_code == 404
    assert response.json()["code"] == "registration_configuration_source_unavailable"


def test_page10_configuration_inputs_reject_unknown_client_owned_fields() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=actor,
        capability_code="registration.manage_configuration",
    )
    client = APIClient()
    client.force_authenticate(actor)
    base_path = (
        f"/api/v1/organizations/{edition.organization_id}/"
        f"editions/{edition.id}/registration"
    )

    response = client.post(
        f"{base_path}/configuration/drafts",
        {
            "name": "Strict draft",
            "reason": "Prove scope and evidence remain server-owned.",
            "opens_at": (timezone.now() - timedelta(days=1)).isoformat(),
            "closes_at": (timezone.now() + timedelta(days=30)).isoformat(),
            "capacity": 200,
            "currency": "EUR",
            "organization_id": str(uuid4()),
            "status": "active",
            "created_by_id": str(uuid4()),
        },
        format="json",
    )

    assert response.status_code == 400
    assert set(response.json()["errors"]) >= {
        "organization_id",
        "status",
        "created_by_id",
    }
    assert not RegistrationConfiguration.objects.filter(edition=edition).exists()


def test_configuration_workspace_hides_other_tenants_and_lists_provenance() -> None:
    source_edition, actor, template = _published_template()
    target = EventEditionFactory(
        organization=source_edition.organization,
        series=source_edition.series,
    )
    CapabilityGrantFactory(
        organization=target.organization,
        edition=target,
        principal=actor,
        capability_code="registration.manage_configuration",
    )
    create_configuration_draft(
        organization_id=target.organization_id,
        edition_id=target.id,
        actor=actor,
        name="Target registration",
        reason="Use a reviewed template.",
        correlation_id=uuid4(),
        source_template_id=template.id,
        opens_at=timezone.now() - timedelta(days=1),
        closes_at=timezone.now() + timedelta(days=30),
        capacity=200,
        currency="EUR",
    )
    client = APIClient()
    client.force_authenticate(actor)

    response = client.get(
        f"/api/v1/organizations/{target.organization_id}/"
        f"editions/{target.id}/registration/configuration"
    )
    hidden = client.get(
        f"/api/v1/organizations/{uuid4()}/editions/{uuid4()}/registration/configuration"
    )

    assert response.status_code == 200
    assert response.json()["drafts"][0]["source_summary"]["kind"] == "template"
    assert response.json()["templates"][0]["name"] == template.name
    assert hidden.status_code == 403


def test_configuration_api_copies_activates_and_publishes_a_template() -> None:
    source_edition, actor, template = _published_template()
    target = EventEditionFactory(
        organization=source_edition.organization,
        series=source_edition.series,
    )
    CapabilityGrantFactory(
        organization=target.organization,
        edition=target,
        principal=actor,
        capability_code="registration.manage_configuration",
    )
    client = APIClient()
    client.force_authenticate(actor)
    base_path = (
        f"/api/v1/organizations/{target.organization_id}/"
        f"editions/{target.id}/registration"
    )

    draft_response = client.post(
        f"{base_path}/configuration/drafts",
        {
            "name": "Target attendee registration",
            "reason": "Copy the approved annual template.",
            "source_template_id": str(template.id),
            "opens_at": (timezone.now() - timedelta(days=1)).isoformat(),
            "closes_at": (timezone.now() + timedelta(days=30)).isoformat(),
            "capacity": 240,
            "currency": "EUR",
        },
        format="json",
    )

    assert draft_response.status_code == 201
    draft_payload = draft_response.json()
    assert draft_payload["source_summary"]["kind"] == "template"
    assert draft_payload["review_required"] is True
    assert draft_payload["questions"][0]["label"] == "Badge name"

    activation_response = client.post(
        f"{base_path}/configuration/activate",
        {
            "configuration_id": draft_payload["id"],
            "reason": (
                "Dates, prices, capacity, questions, purpose, and policy reviewed."
            ),
        },
        format="json",
    )

    assert activation_response.status_code == 200
    assert activation_response.json()["status"] == "active"
    assert activation_response.json()["review_required"] is False

    publish_response = client.post(
        f"{base_path}/templates",
        {
            "configuration_id": draft_payload["id"],
            "code": "target-attendee-registration",
            "name": "Target attendee registration",
            "description": "Reviewed annual registration baseline.",
            "series_limited": True,
            "reason": "Publish the reviewed active setup for controlled reuse.",
        },
        format="json",
    )

    assert publish_response.status_code == 201
    assert publish_response.json()["version"] == 1
    assert publish_response.json()["question_count"] == 1
    assert publish_response.json()["product_count"] == 1
    published = RegistrationTemplate.objects.get(
        id=publish_response.json()["id"],
    )
    assert published.status == TemplateStatus.PUBLISHED
    assert published.series_id == target.series_id


def test_active_configuration_cannot_be_edited_through_model() -> None:
    configuration = RegistrationConfiguration(
        organization=EventEditionFactory().organization,
        edition=EventEditionFactory(),
        name="Invalid scope",
        version=1,
        opens_at=timezone.now(),
        closes_at=timezone.now() + timedelta(days=1),
        capacity=1,
        currency="EUR",
        created_by_id=uuid4(),
    )
    with pytest.raises(ValidationError):
        configuration.full_clean()


@pytest.mark.parametrize(
    ("field_type", "options", "condition_key", "condition_value"),
    [
        (QuestionFieldType.SHORT_TEXT, "not-a-list", "", ""),
        (QuestionFieldType.SINGLE_CHOICE, ["same", "same"], "", ""),
        (QuestionFieldType.SINGLE_CHOICE, ["only-one"], "", ""),
        (QuestionFieldType.SINGLE_CHOICE, [f"option-{i}" for i in range(65)], "", ""),
        (QuestionFieldType.BOOLEAN, ["yes", "no"], "", ""),
        (QuestionFieldType.SHORT_TEXT, [], "another-question", ""),
        (QuestionFieldType.SHORT_TEXT, [], "question-under-test", "yes"),
    ],
)
def test_question_configuration_rejects_ambiguous_schema(
    field_type: str,
    options: object,
    condition_key: str,
    condition_value: str,
) -> None:
    configuration = RegistrationConfigurationFactory()
    question = RegistrationQuestion(
        configuration=configuration,
        key="question-under-test",
        label="Question under test",
        field_type=field_type,
        required=False,
        position=10,
        options=options,
        purpose="Verify form configuration safety.",
        condition_question_key=condition_key,
        condition_value=condition_value,
    )

    with pytest.raises(ValidationError):
        question.full_clean()
