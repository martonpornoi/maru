"""Canonical API parity for the governed Page 10 definition builder."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.registration.models import (
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
from maru.registration.starter_catalog import platform_registration_starters
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
        name="Synthetic API registration",
        opens_at=timezone.now() + timedelta(days=1),
        closes_at=timezone.now() + timedelta(days=30),
        capacity=500,
        currency="EUR",
        minimum_age=18,
        default_payment_window_minutes=1_440,
        waitlist_enabled=True,
        automatic_waitlist_promotion=True,
        expected_version=0,
        reason="Start the governed API fixture.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return (
        RegistrationSetupControl.objects.get(pk=result.setup_id),
        RegistrationConfiguration.objects.get(pk=result.configuration_id),
    )


def _client(actor: Account) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=actor)
    return client


def _configuration_url(
    edition: EventEdition,
    configuration: RegistrationConfiguration,
) -> str:
    return reverse(
        "api-registration-configuration-command",
        args=[edition.organization_id, edition.id, configuration.id],
    )


def _setup_start_url(edition: EventEdition) -> str:
    return reverse(
        "api-registration-setup-start",
        args=[edition.organization_id, edition.id],
    )


def _profile_collection_url(edition: EventEdition) -> str:
    return reverse(
        "api-registration-profile-extension-field-list",
        args=[edition.organization_id, edition.id],
    )


def _profile_command_url(edition: EventEdition, field_id: UUID) -> str:
    return reverse(
        "api-registration-profile-extension-field-command",
        args=[edition.organization_id, edition.id, field_id],
    )


def _post(
    client: APIClient,
    url: str,
    payload: dict[str, object],
    *,
    retry_key: UUID | None = None,
) -> Any:
    return client.post(
        url,
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(retry_key or uuid4()),
    )


def _question_payload(
    operation: str,
    version: int,
    **extra: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "operation": operation,
        "key": "arrival-note",
        "label": "Arrival note",
        "help_text": "Share a current arrival preference.",
        "field_type": QuestionFieldType.SHORT_TEXT,
        "required": False,
        "options": [],
        "purpose": "Coordinate attendee arrival support.",
        "visibility": QuestionVisibility.ATTENDEE_AND_STAFF,
        "classification": QuestionClassification.PERSONAL,
        "condition_question_key": "",
        "condition_value": "",
        "section_id": None,
        "expected_version": version,
        "reason": "Exercise the canonical question API.",
    }
    payload.update(extra)
    return payload


def _product_payload(
    operation: str,
    version: int,
    **extra: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "operation": operation,
        "code": "weekend",
        "name": "Weekend admission",
        "description": "Synthetic admission for the API contract.",
        "price_minor": 12_000,
        "capacity": 100,
        "entitlement_code": "weekend-admission",
        "entitlement_name": "Weekend admission",
        "sales_open_at": None,
        "sales_close_at": None,
        "required_capacity_codes": [],
        "eligibility_explanation": "",
        "waitlist_enabled": True,
        "payment_window_minutes": 1_440,
        "expected_version": version,
        "reason": "Exercise the canonical product API.",
    }
    payload.update(extra)
    return payload


def _profile_payload(version: int, *, key: str) -> dict[str, object]:
    return {
        "key": key,
        "label": key.replace("-", " ").title(),
        "help_text": "Synthetic current-profile field.",
        "field_type": QuestionFieldType.SHORT_TEXT,
        "options": [],
        "purpose": "Maintain a current attendee preference.",
        "classification": QuestionClassification.PERSONAL,
        "attendee_visible": True,
        "writer_policy": ProfileExtensionWriter.ATTENDEE_AND_STAFF,
        "required": False,
        "source_template_id": None,
        "source_prior_edition_id": None,
        "after_field_id": None,
        "expected_version": version,
        "reason": "Exercise the canonical profile field API.",
    }


def test_configuration_commands_authorize_first_and_reject_open_input() -> None:
    edition = EventEditionFactory()
    manager = AccountFactory()
    unauthorized = AccountFactory()
    _grant(manager, edition)
    _, configuration = _start(manager, edition)
    url = _configuration_url(edition, configuration)

    denied = _client(unauthorized).generic(
        "POST",
        url,
        data=b'{"operation":',
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert denied.status_code == 403
    assert denied.headers["Content-Type"].startswith("application/problem+json")
    assert denied.json()["code"] == "permission_absent"

    missing_header = _client(manager).post(
        url,
        _question_payload("question.create", 1),
        format="json",
    )
    assert missing_header.status_code == 400
    assert missing_header.json()["code"] == "missing_idempotency_key"

    unknown = _question_payload("question.create", 1, retry_key=str(uuid4()))
    rejected = _post(_client(manager), url, unknown)
    assert rejected.status_code == 400
    assert rejected.headers["Content-Type"].startswith("application/problem+json")
    assert "retry_key" in rejected.json()["errors"]


def test_setup_start_api_lists_and_copies_exact_platform_starter() -> None:
    edition = EventEditionFactory()
    manager = AccountFactory()
    unauthorized = AccountFactory()
    _grant(manager, edition)
    url = _setup_start_url(edition)
    starter = platform_registration_starters()[0]

    denied = _client(unauthorized).generic(
        "POST",
        url,
        data=b'{"source_kind":',
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert denied.status_code == 403

    choices = _client(manager).get(url)
    assert choices.status_code == 200
    assert choices.json()["platform_starters"] == [
        {
            "source_kind": RegistrationSetupOrigin.PLATFORM_STARTER,
            "source_id": str(starter.source_id),
            "name": starter.name,
            "version": starter.version,
            "content_digest": starter.content_digest,
            "source_edition_id": None,
            "source_edition_name": "",
        }
    ]

    payload: dict[str, object] = {
        "source_kind": RegistrationSetupOrigin.PLATFORM_STARTER,
        "source_id": str(starter.source_id),
        "name": "Organizer-owned convention registration",
        "opens_at": (timezone.now() + timedelta(days=1)).isoformat(),
        "closes_at": (timezone.now() + timedelta(days=30)).isoformat(),
        "capacity": 1_000,
        "capacity_ceiling": 1_000,
        "currency": "eur",
        "minimum_age": 18,
        "default_payment_window_minutes": 1_440,
        "waitlist_enabled": True,
        "automatic_waitlist_promotion": True,
        "expected_version": 0,
        "reason": "Copy the reviewed code-owned starter into this edition.",
    }
    rejected = _post(
        _client(manager),
        url,
        {**payload, "retry_key": str(uuid4())},
    )
    assert rejected.status_code == 400
    assert "retry_key" in rejected.json()["errors"]

    retry_key = uuid4()
    created = _post(_client(manager), url, payload, retry_key=retry_key)
    replay = _post(_client(manager), url, payload, retry_key=retry_key)
    assert created.status_code == 201
    assert created.headers["Idempotent-Replay"] == "false"
    assert replay.status_code == 200
    assert replay.headers["Idempotent-Replay"] == "true"
    assert replay.json()["configuration_id"] == created.json()["configuration_id"]
    copied = RegistrationConfiguration.objects.get(
        pk=created.json()["configuration_id"]
    )
    assert copied.origin == RegistrationSetupOrigin.PLATFORM_STARTER
    assert copied.source_version == starter.version
    assert copied.source_content_digest == starter.content_digest
    assert copied.products.get().id != starter.products[0].id


def test_openapi_lists_closed_definition_command_families() -> None:
    client = APIClient()
    client.force_authenticate(AccountFactory(is_staff=True, is_superuser=True))
    response = client.get(
        reverse("api-schema"),
        HTTP_ACCEPT="application/vnd.oai.openapi+json",
    )
    assert response.status_code == 200
    schema = response.json()
    schemas = schema["components"]["schemas"]
    configuration_command = schemas["RegistrationConfigurationDefinitionCommand"]
    profile_command = schemas["RegistrationProfileFieldCommand"]
    configuration_operations = {
        "section.create",
        "section.update",
        "section.move",
        "section.remove",
        "question.create",
        "question.update",
        "question.move",
        "question.remove",
        "product.create",
        "product.update",
        "product.move",
        "product.remove",
        "minor_policy.set",
        "minor_policy.remove",
    }
    profile_operations = {
        "profile_field.update",
        "profile_field.move",
        "profile_field.retire",
    }
    assert set(configuration_command["discriminator"]["mapping"]) == (
        configuration_operations
    )
    assert set(profile_command["discriminator"]["mapping"]) == profile_operations
    for command, operations in (
        (configuration_command, configuration_operations),
        (profile_command, profile_operations),
    ):
        assert len(command["oneOf"]) == len(operations)
        for operation_key, reference in command["discriminator"]["mapping"].items():
            component = schemas[reference.rsplit("/", 1)[-1]]
            assert component["additionalProperties"] is False
            operation_schema = component["properties"]["operation"]
            if "$ref" in operation_schema:
                operation_schema = schemas[operation_schema["$ref"].rsplit("/", 1)[-1]]
            declared_operations = set(operation_schema.get("enum", ()))
            if "const" in operation_schema:
                declared_operations.add(operation_schema["const"])
            assert declared_operations == {operation_key}

    configuration_path = next(
        value
        for key, value in schema["paths"].items()
        if key.endswith("/registration/configuration/{configuration_id}/commands")
    )["post"]
    collection_path = next(
        value
        for key, value in schema["paths"].items()
        if key.endswith("/registration/profile-extension-fields")
    )["post"]
    profile_path = next(
        value
        for key, value in schema["paths"].items()
        if key.endswith("/profile-extension-fields/{field_id}/commands")
    )["post"]
    create_reference = collection_path["requestBody"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    assert schemas[create_reference.rsplit("/", 1)[-1]]["additionalProperties"] is False
    for operation, statuses in (
        (configuration_path, ("200", "201")),
        (collection_path, ("200", "201")),
        (profile_path, ("200",)),
    ):
        for status_code in statuses:
            replay_header = operation["responses"][status_code]["headers"][
                "Idempotent-Replay"
            ]
            assert set(replay_header["schema"]["enum"]) == {"false", "true"}


def test_configuration_api_rejects_unactivatable_question_conditions() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, edition)
    control, configuration = _start(actor, edition)
    client = _client(actor)
    url = _configuration_url(edition, configuration)

    multiple = _post(
        client,
        url,
        _question_payload(
            "question.create",
            1,
            key="interests",
            label="Interests",
            field_type=QuestionFieldType.MULTIPLE_CHOICE,
            options=["Panels", "Dance"],
            after_question_id=None,
        ),
    )
    assert multiple.status_code == 201
    rejected_multiple = _post(
        client,
        url,
        _question_payload(
            "question.create",
            2,
            key="panel-detail",
            label="Panel detail",
            condition_question_key="interests",
            condition_value="Panels",
            after_question_id=multiple.json()["target_id"],
        ),
    )
    assert rejected_multiple.status_code == 400
    assert rejected_multiple.json()["code"] == (
        "registration_setup_question_condition_value_invalid"
    )

    integer = _post(
        client,
        url,
        _question_payload(
            "question.create",
            2,
            key="party-size",
            label="Party size",
            field_type=QuestionFieldType.INTEGER,
            after_question_id=multiple.json()["target_id"],
        ),
    )
    assert integer.status_code == 201
    for invalid_value in ("-0", "2147483648", "-2147483649"):
        rejected_integer = _post(
            client,
            url,
            _question_payload(
                "question.create",
                3,
                key="party-detail",
                label="Party detail",
                condition_question_key="party-size",
                condition_value=invalid_value,
                after_question_id=integer.json()["target_id"],
            ),
        )
        assert rejected_integer.status_code == 400
        assert rejected_integer.json()["code"] == (
            "registration_setup_question_condition_value_invalid"
        )
    control.refresh_from_db()
    assert control.aggregate_version == 3
    assert configuration.questions.count() == 2


def test_configuration_api_dispatches_definition_families_and_replays(  # noqa: PLR0915
) -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, edition)
    control, configuration = _start(actor, edition)
    client = _client(actor)
    url = _configuration_url(edition, configuration)

    section_one = _post(
        client,
        url,
        {
            "operation": "section.create",
            "key": "profile",
            "title": "Profile",
            "description": "Attendee profile details.",
            "after_section_id": None,
            "expected_version": 1,
            "reason": "Add the first API section.",
        },
    )
    assert section_one.status_code == 201
    section_one_id = section_one.json()["target_id"]
    section_two = _post(
        client,
        url,
        {
            "operation": "section.create",
            "key": "preferences",
            "title": "Preferences",
            "description": "Current preferences.",
            "after_section_id": section_one_id,
            "expected_version": 2,
            "reason": "Add the second API section.",
        },
    )
    section_two_id = section_two.json()["target_id"]
    updated_section = _post(
        client,
        url,
        {
            "operation": "section.update",
            "section_id": section_one_id,
            "key": "profile",
            "title": "Attendee profile",
            "description": "Attendee profile details.",
            "expected_version": 3,
            "reason": "Clarify the first API section.",
        },
    )
    assert updated_section.status_code == 200
    moved_section = _post(
        client,
        url,
        {
            "operation": "section.move",
            "section_id": section_two_id,
            "after_section_id": None,
            "expected_version": 4,
            "reason": "Move the preferences section first.",
        },
    )
    assert moved_section.json()["resulting_version"] == 5

    retry_key = uuid4()
    question_body = _question_payload(
        "question.create",
        5,
        section_id=section_one_id,
        after_question_id=None,
    )
    question = _post(client, url, question_body, retry_key=retry_key)
    assert question.status_code == 201
    assert question.headers["Idempotent-Replay"] == "false"
    question_id = question.json()["target_id"]
    replay = _post(client, url, question_body, retry_key=retry_key)
    assert replay.status_code == 200
    assert replay.headers["Idempotent-Replay"] == "true"
    assert replay.json()["receipt_id"] == question.json()["receipt_id"]
    changed_reuse = _post(
        client,
        url,
        {**question_body, "label": "Changed retry"},
        retry_key=retry_key,
    )
    assert changed_reuse.status_code == 409
    assert changed_reuse.json()["code"] == "registration_setup_retry_conflict"

    updated_question = _post(
        client,
        url,
        _question_payload(
            "question.update",
            6,
            question_id=question_id,
            section_id=section_one_id,
            label="Arrival information",
        ),
    )
    assert updated_question.status_code == 200
    second_question = _post(
        client,
        url,
        _question_payload(
            "question.create",
            7,
            key="diet-note",
            label="Diet note",
            section_id=section_two_id,
            after_question_id=question_id,
        ),
    )
    second_question_id = second_question.json()["target_id"]
    moved_question = _post(
        client,
        url,
        {
            "operation": "question.move",
            "question_id": second_question_id,
            "after_question_id": None,
            "expected_version": 8,
            "reason": "Move the diet note first.",
        },
    )
    assert moved_question.json()["resulting_version"] == 9
    removed_question = _post(
        client,
        url,
        {
            "operation": "question.remove",
            "question_id": question_id,
            "expected_version": 9,
            "reason": "Remove the unreferenced arrival question.",
        },
    )
    assert removed_question.status_code == 200

    first_product = _post(client, url, _product_payload("product.create", 10))
    assert first_product.status_code == 201
    first_product_id = first_product.json()["target_id"]
    second_product = _post(
        client,
        url,
        _product_payload(
            "product.create",
            11,
            code="day",
            name="Day admission",
            entitlement_code="day-admission",
            entitlement_name="Day admission",
            after_product_id=first_product_id,
        ),
    )
    second_product_id = second_product.json()["target_id"]
    updated_product = _post(
        client,
        url,
        _product_payload(
            "product.update",
            12,
            product_id=first_product_id,
            name="Full weekend admission",
        ),
    )
    assert updated_product.json()["resulting_version"] == 13
    moved_product = _post(
        client,
        url,
        {
            "operation": "product.move",
            "product_id": second_product_id,
            "after_product_id": None,
            "expected_version": 13,
            "reason": "Move day admission first.",
        },
    )
    assert moved_product.json()["resulting_version"] == 14
    removed_product = _post(
        client,
        url,
        {
            "operation": "product.remove",
            "product_id": first_product_id,
            "expected_version": 14,
            "reason": "Remove the unreferenced weekend product.",
        },
    )
    assert removed_product.status_code == 200

    minor_retry_key = uuid4()
    minor_body = {
        "operation": "minor_policy.set",
        "enabled": False,
        "minor_age_threshold": 19,
        "guardian_notice_version": "",
        "jurisdiction_code": "",
        "review_reference": "",
        "expected_version": 15,
        "reason": "Record that minors are not enabled.",
    }
    minor = _post(
        client,
        url,
        minor_body,
        retry_key=minor_retry_key,
    )
    assert minor.status_code == 201
    minor_replay = _post(client, url, minor_body, retry_key=minor_retry_key)
    assert minor_replay.status_code == 200
    assert minor_replay.headers["Idempotent-Replay"] == "true"
    assert minor_replay.json()["receipt_id"] == minor.json()["receipt_id"]
    remove_retry_key = uuid4()
    remove_body = {
        "operation": "minor_policy.remove",
        "expected_version": 16,
        "reason": "Remove the unreferenced minor policy.",
    }
    removed_minor = _post(
        client,
        url,
        remove_body,
        retry_key=remove_retry_key,
    )
    assert removed_minor.status_code == 200
    removed_minor_replay = _post(
        client,
        url,
        remove_body,
        retry_key=remove_retry_key,
    )
    assert removed_minor_replay.status_code == 200
    assert removed_minor_replay.headers["Idempotent-Replay"] == "true"
    assert (
        removed_minor_replay.json()["receipt_id"]
        == (removed_minor.json()["receipt_id"])
    )
    control.refresh_from_db()
    assert control.aggregate_version == 17


def test_profile_catalog_api_omits_values_and_mutates_definitions() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, edition)
    control, _ = _start(actor, edition)
    client = _client(actor)
    collection_url = _profile_collection_url(edition)

    first = _post(client, collection_url, _profile_payload(1, key="diet-note"))
    assert first.status_code == 201
    first_id = UUID(first.json()["target_id"])
    second_payload = _profile_payload(2, key="arrival-note")
    second_payload["after_field_id"] = str(first_id)
    second = _post(client, collection_url, second_payload)
    second_id = UUID(second.json()["target_id"])

    catalog = client.get(collection_url)
    assert catalog.status_code == 200
    assert "no-store" in catalog.headers["Cache-Control"]
    assert catalog.json()["aggregate_version"] == 3
    assert [item["key"] for item in catalog.json()["fields"]] == [
        "diet-note",
        "arrival-note",
    ]
    assert all("value" not in item for item in catalog.json()["fields"])

    updated_payload = _profile_payload(3, key="diet-note")
    updated_payload.pop("source_template_id")
    updated_payload.pop("source_prior_edition_id")
    updated_payload.pop("after_field_id")
    updated = _post(
        client,
        _profile_command_url(edition, first_id),
        {
            **updated_payload,
            "operation": "profile_field.update",
            "label": "Dietary note",
        },
    )
    assert updated.status_code == 200
    moved = _post(
        client,
        _profile_command_url(edition, second_id),
        {
            "operation": "profile_field.move",
            "after_field_id": None,
            "expected_version": 4,
            "reason": "Move the arrival field first.",
        },
    )
    assert moved.json()["resulting_version"] == 5
    retired = _post(
        client,
        _profile_command_url(edition, first_id),
        {
            "operation": "profile_field.retire",
            "expected_version": 5,
            "reason": "Retire the obsolete dietary field.",
        },
    )
    assert retired.status_code == 200
    control.refresh_from_db()
    assert control.aggregate_version == 6
    assert RegistrationProfileExtensionField.objects.get(pk=first_id).status == (
        "retired"
    )
