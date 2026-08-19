"""Browser parity for Page 10 question, product, minor, and profile editors."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.registration.configuration_lifecycle import (
    activate_registration_configuration,
    review_registration_configuration,
)
from maru.registration.models import (
    ConfigurationStatus,
    ProfileExtensionWriter,
    QuestionClassification,
    QuestionFieldType,
    QuestionVisibility,
    RegistrationConfiguration,
    RegistrationProfileExtensionField,
    RegistrationSetupControl,
    RegistrationSetupOrigin,
)
from maru.registration.setup_commands import start_registration_setup
from maru.registration.setup_definition_commands import (
    create_admission_product,
    create_registration_question,
)
from tests.factories import AccountFactory, CapabilityGrantFactory, EventEditionFactory

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _grant(actor: Account, edition: EventEdition) -> None:
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=actor,
        capability_code="registration.manage_configuration",
    )


def _start(
    actor: Account,
    edition: EventEdition,
) -> tuple[RegistrationSetupControl, RegistrationConfiguration]:
    result = start_registration_setup(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        source_kind=RegistrationSetupOrigin.BLANK,
        source_id=None,
        name="Synthetic browser registration",
        opens_at=timezone.now() + timedelta(days=1),
        closes_at=timezone.now() + timedelta(days=30),
        capacity=500,
        currency="EUR",
        minimum_age=18,
        default_payment_window_minutes=1_440,
        waitlist_enabled=True,
        automatic_waitlist_promotion=True,
        expected_version=0,
        reason="Start the governed browser fixture.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return (
        RegistrationSetupControl.objects.get(pk=result.setup_id),
        RegistrationConfiguration.objects.get(pk=result.configuration_id),
    )


def _client(actor: Account, *, csrf: bool = False) -> Client:
    client = Client(enforce_csrf_checks=csrf)
    client.force_login(actor)
    return client


def _url(
    name: str,
    edition: EventEdition,
    *identifiers: UUID,
) -> str:
    return reverse(
        name,
        args=[
            edition.organization.slug,
            edition.series.slug,
            edition.slug,
            *identifiers,
        ],
    )


def _form_value(form: Any, field_name: str) -> str:
    value = form[field_name].value()
    return "" if value is None else str(value)


def _assert_private(response: Any) -> None:
    directives = {
        item.strip().casefold()
        for item in response.headers.get("Cache-Control", "").split(",")
    }
    assert {"private", "no-store"}.issubset(directives)


def _question_data(form: Any) -> dict[str, object]:
    return {
        "key": "arrival-note",
        "label": "Arrival note",
        "help_text": "Share a current arrival preference.",
        "field_type": QuestionFieldType.SHORT_TEXT,
        "required": "false",
        "options": "",
        "purpose": "Coordinate attendee arrival support.",
        "visibility": QuestionVisibility.ATTENDEE_AND_STAFF,
        "classification": QuestionClassification.PERSONAL,
        "condition_question_key": "",
        "condition_value": "",
        "section_id": "",
        "after_question_id": "",
        "expected_version": _form_value(form, "expected_version"),
        "reason": "Create a governed browser question.",
        "retry_key": _form_value(form, "retry_key"),
    }


def _product_data(form: Any) -> dict[str, object]:
    return {
        "code": "weekend",
        "name": "Weekend admission",
        "description": "Synthetic admission for browser parity.",
        "price_minor": "12000",
        "capacity": "100",
        "entitlement_code": "weekend-admission",
        "entitlement_name": "Weekend admission",
        "sales_open_at": "",
        "sales_close_at": "",
        "required_capacity_codes": [],
        "eligibility_explanation": "",
        "waitlist_enabled": "true",
        "payment_window_minutes": "1440",
        "after_product_id": "",
        "expected_version": _form_value(form, "expected_version"),
        "reason": "Create a governed browser product.",
        "retry_key": _form_value(form, "retry_key"),
    }


def _profile_data(form: Any) -> dict[str, object]:
    return {
        "key": "diet-note",
        "label": "Diet note",
        "help_text": "Maintain the attendee's current preference.",
        "field_type": QuestionFieldType.SHORT_TEXT,
        "options": "",
        "purpose": "Coordinate attendee catering support.",
        "classification": QuestionClassification.PERSONAL,
        "required": "false",
        "attendee_visible": "true",
        "writer_policy": ProfileExtensionWriter.ATTENDEE_AND_STAFF,
        "source_template_id": "",
        "source_prior_edition_id": "",
        "after_field_id": "",
        "expected_version": _form_value(form, "expected_version"),
        "reason": "Create a governed current-profile field.",
        "retry_key": _form_value(form, "retry_key"),
    }


def test_browser_definition_create_forms_are_closed_and_share_the_builder() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, edition)
    control, configuration = _start(actor, edition)
    client = _client(actor)
    configuration_path = _url(
        "registration-setup-configuration",
        edition,
        configuration.id,
    )

    question_page = client.get(
        _url("registration-setup-question-create", edition, configuration.id)
    )
    assert question_page.status_code == 200
    _assert_private(question_page)
    question_data = _question_data(question_page.context["form"])
    rejected = client.post(
        _url("create-registration-setup-question", edition, configuration.id),
        {**question_data, "server_owned_status": "active"},
    )
    assert rejected.status_code == 400
    assert "server_owned_status" in " ".join(
        rejected.context["form"].non_field_errors()
    )
    created_question = client.post(
        _url("create-registration-setup-question", edition, configuration.id),
        question_data,
    )
    assert created_question.status_code == 302
    assert created_question.headers["Location"] == configuration_path

    product_page = client.get(
        _url("registration-setup-product-create", edition, configuration.id)
    )
    created_product = client.post(
        _url("create-registration-setup-product", edition, configuration.id),
        _product_data(product_page.context["form"]),
    )
    assert created_product.status_code == 302
    assert created_product.headers["Location"] == configuration_path

    minor_path = _url(
        "registration-setup-minor-policy",
        edition,
        configuration.id,
    )
    minor_page = client.get(minor_path)
    minor_form = minor_page.context["form"]
    minor_data = {
        "enabled": "false",
        "minor_age_threshold": "19",
        "guardian_notice_version": "",
        "jurisdiction_code": "",
        "review_reference": "",
        "expected_version": _form_value(minor_form, "expected_version"),
        "reason": "Record that minors are not enabled.",
        "retry_key": _form_value(minor_form, "retry_key"),
    }
    created_minor = client.post(minor_path, minor_data)
    assert created_minor.status_code == 302
    assert created_minor.headers["Location"] == configuration_path
    replayed_minor = client.post(minor_path, minor_data)
    assert replayed_minor.status_code == 302
    assert replayed_minor.headers["Location"] == configuration_path

    builder = client.get(configuration_path)
    content = builder.content.decode()
    assert builder.status_code == 200
    assert "Arrival note" in content
    assert "Weekend admission" in content
    assert "Minor registration policy" in content
    question = configuration.questions.get(key="arrival-note")
    product = configuration.products.get(code="weekend")
    for action_name, identifier in (
        ("update-registration-setup-question", question.id),
        ("move-registration-setup-question", question.id),
        ("remove-registration-setup-question", question.id),
        ("update-registration-setup-product", product.id),
        ("move-registration-setup-product", product.id),
        ("remove-registration-setup-product", product.id),
    ):
        assert (
            _url(
                action_name,
                edition,
                configuration.id,
                identifier,
            )
            in content
        )
    control.refresh_from_db()
    assert control.aggregate_version == 4


def test_browser_rejects_question_conditions_activation_cannot_satisfy() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, edition)
    control, configuration = _start(actor, edition)
    common = {
        "actor": actor,
        "organization_id": edition.organization_id,
        "series_id": edition.series_id,
        "edition_id": edition.id,
        "configuration_id": configuration.id,
        "required": False,
        "purpose": "Exercise browser condition validation.",
        "visibility": QuestionVisibility.ATTENDEE_AND_STAFF,
        "classification": QuestionClassification.PERSONAL,
        "condition_question_key": "",
        "condition_value": "",
        "section_id": None,
        "reason": "Create a browser condition source.",
        "correlation_id": uuid4(),
        "source_channel": "test",
    }
    multiple = create_registration_question(
        **common,
        key="interests",
        label="Interests",
        help_text="Choose interests.",
        field_type=QuestionFieldType.MULTIPLE_CHOICE,
        options=["Panels", "Dance"],
        after_question_id=None,
        expected_version=1,
        retry_key=uuid4(),
    )
    integer = create_registration_question(
        **{
            **common,
            "correlation_id": uuid4(),
            "key": "party-size",
            "label": "Party size",
            "help_text": "Enter party size.",
            "field_type": QuestionFieldType.INTEGER,
            "options": [],
            "after_question_id": multiple.target_id,
            "expected_version": 2,
            "retry_key": uuid4(),
        }
    )
    client = _client(actor)
    create_url = _url(
        "create-registration-setup-question",
        edition,
        configuration.id,
    )
    page_url = _url(
        "registration-setup-question-create",
        edition,
        configuration.id,
    )

    multiple_form = client.get(page_url).context["form"]
    multiple_data = {
        **_question_data(multiple_form),
        "key": "panel-detail",
        "label": "Panel detail",
        "condition_question_key": "interests",
        "condition_value": "Panels",
        "after_question_id": str(integer.target_id),
    }
    rejected_multiple = client.post(create_url, multiple_data)
    assert rejected_multiple.status_code == 400
    assert (
        "incompatible"
        in " ".join(
            rejected_multiple.context["form"]["condition_value"].errors
        ).casefold()
    )

    integer_form = client.get(page_url).context["form"]
    integer_data = {
        **_question_data(integer_form),
        "key": "party-detail",
        "label": "Party detail",
        "condition_question_key": "party-size",
        "condition_value": "-0",
        "after_question_id": str(integer.target_id),
    }
    rejected_integer = client.post(create_url, integer_data)
    assert rejected_integer.status_code == 400
    assert (
        "incompatible"
        in " ".join(
            rejected_integer.context["form"]["condition_value"].errors
        ).casefold()
    )
    control.refresh_from_db()
    assert control.aggregate_version == 3
    assert configuration.questions.count() == 2


def test_profile_browser_remains_available_with_active_configuration() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, edition)
    control, configuration = _start(actor, edition)
    product = create_admission_product(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        configuration_id=configuration.id,
        code="profile-fixture-admission",
        name="Profile fixture admission",
        description="Governed activation fixture for the profile editor.",
        price_minor=0,
        capacity=500,
        entitlement_code="profile-fixture-attendee",
        entitlement_name="Profile fixture attendee",
        sales_open_at=None,
        sales_close_at=None,
        required_capacity_codes=[],
        eligibility_explanation="",
        waitlist_enabled=True,
        payment_window_minutes=None,
        after_product_id=None,
        expected_version=control.aggregate_version,
        reason="Add the governed profile-editor activation fixture product.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    configuration.refresh_from_db()
    reviewed = review_registration_configuration(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        configuration_id=configuration.id,
        content_digest=configuration.content_digest,
        review_note="",
        expected_version=product.resulting_version,
        reason="Review the governed profile-editor activation fixture.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    activate_registration_configuration(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        configuration_id=configuration.id,
        content_digest=configuration.content_digest,
        edition_name_confirmation=edition.name,
        expected_version=reviewed.resulting_version,
        reason="Activate the governed profile-editor fixture.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    control.refresh_from_db()
    configuration.refresh_from_db()
    assert configuration.status == ConfigurationStatus.ACTIVE
    client = _client(actor)

    create_page = client.get(_url("registration-setup-profile-field-create", edition))
    content = create_page.content.decode()
    assert create_page.status_code == 200
    assert "Create profile field" in content
    assert "disabled aria-disabled" not in content
    created = client.post(
        _url("registration-setup-profile-fields", edition),
        _profile_data(create_page.context["form"]),
    )
    catalog_path = _url("registration-setup-profile-fields", edition)
    assert created.status_code == 302
    assert created.headers["Location"] == catalog_path

    field = RegistrationProfileExtensionField.objects.get(key="diet-note")
    catalog = client.get(catalog_path)
    catalog_content = catalog.content.decode()
    assert "definitions only and never attendee values" in catalog_content
    assert "Diet note" in catalog_content
    assert (
        _url(
            "update-registration-setup-profile-field",
            edition,
            field.id,
        )
        in catalog_content
    )
    assert (
        _url(
            "move-registration-setup-profile-field",
            edition,
            field.id,
        )
        in catalog_content
    )
    assert (
        _url(
            "retire-registration-setup-profile-field",
            edition,
            field.id,
        )
        in catalog_content
    )
    detail = client.get(
        _url("registration-setup-profile-field-detail", edition, field.id)
    )
    assert detail.status_code == 200
    assert "Attendee values are intentionally absent" in detail.content.decode()

    retire_form = catalog.context["profile_field_editors"][0].retire_form
    retired = client.post(
        _url("retire-registration-setup-profile-field", edition, field.id),
        {
            "expected_version": _form_value(retire_form, "expected_version"),
            "reason": "Retire the obsolete synthetic field.",
            "retry_key": _form_value(retire_form, "retry_key"),
        },
    )
    assert retired.status_code == 302
    field.refresh_from_db()
    control.refresh_from_db()
    assert field.status == "retired"
    assert control.aggregate_version == 6


def test_definition_posts_enforce_csrf_and_authorize_before_form_parsing() -> None:
    edition = EventEditionFactory()
    manager = AccountFactory()
    unauthorized = AccountFactory()
    _grant(manager, edition)
    _, configuration = _start(manager, edition)
    path = _url("create-registration-setup-question", edition, configuration.id)

    with patch(
        "maru.registration.setup_definition_views._question_create_form",
        side_effect=AssertionError("form body parsed before authorization"),
    ):
        denied = _client(unauthorized).post(path, {"unknown": "input"})
    assert denied.status_code == 403

    csrf_denied = _client(manager, csrf=True).post(path, {"unknown": "input"})
    assert csrf_denied.status_code == 403
    assert not configuration.questions.exists()
