import pytest
from django.core.exceptions import ValidationError

from maru.applications.models import (
    ApplicationClassification,
    ApplicationSourceBinding,
    ApplicationTargetKind,
)
from maru.applications.starters import application_starter, starter_catalog
from maru.authorization.catalog import capability
from maru.effects.registry import validate_event_payload


def test_application_starter_catalog_keeps_registration_external_and_is_closed() -> (
    None
):
    starters = {starter.code: starter for starter in starter_catalog()}

    assert set(starters) == {
        "registration",
        "merch-submission",
        "dj-application",
        "fursuit-dance-competition",
        "maid-cafe",
        "adult-fursuit-striptease",
        "volunteer-application",
        "feedback",
        "idea-submission",
        "damage-report",
        "helper-application",
    }
    assert starters["registration"].owner_module == "registration"
    assert starters["registration"].is_external
    assert all(
        starter.owner_module == "applications" and not starter.is_external
        for code, starter in starters.items()
        if code != "registration"
    )


def test_sensitive_and_helper_starters_force_edition_specific_policy() -> None:
    adult = application_starter("adult-fursuit-striptease")
    damage = application_starter("damage-report")
    helper = application_starter("helper-application")

    assert adult is not None
    assert damage is not None
    assert helper is not None
    assert adult.target_adapter_kind == ApplicationTargetKind.ADULT_FURSUIT_STRIPTEASE
    assert adult.classification == ApplicationClassification.RESTRICTED
    assert adult.minimum_age == 18
    assert not adult.audience_policy_code
    assert not adult.retention_policy_code
    assert not adult.age_policy_code
    assert damage.target_adapter_kind == ApplicationTargetKind.DAMAGE_REPORT
    assert not damage.audience_policy_code
    assert not damage.retention_policy_code
    bindings = {question.key: question.source_binding for question in helper.questions}
    assert bindings["name"] == ApplicationSourceBinding.ACCOUNT_DISPLAY_NAME
    assert bindings["telegram"] == ApplicationSourceBinding.REGISTRATION_TELEGRAM
    assert {"available-from", "available-until"} <= set(bindings)


def test_application_capabilities_are_closed_and_self_grants_are_not_persistable() -> (
    None
):
    expected = {
        "applications.manage_definitions",
        "applications.review",
        "applications.review_sensitive",
        "applications.view_self",
        "applications.apply_self",
    }

    assert all(capability(code) is not None for code in expected)
    assert capability("applications.view_self").allow_self is True
    assert capability("applications.view_self").persistable is False
    assert capability("applications.apply_self").allow_self is True
    assert capability("applications.apply_self").persistable is False
    assert capability("applications.review_sensitive").delegable is False


def test_application_domain_events_reject_open_payloads() -> None:
    validate_event_payload(
        event_name="applications.definition.changed.v1",
        schema_version=1,
        payload={
            "action": "definition_activated",
            "definition_code": "dj-application",
            "definition_version": "1",
        },
    )
    validate_event_payload(
        event_name="applications.submission.changed.v1",
        schema_version=1,
        payload={
            "action": "review_decided",
            "state": "accepted",
            "target_adapter_kind": "dj_set",
        },
    )

    with pytest.raises(ValidationError):
        validate_event_payload(
            event_name="applications.submission.changed.v1",
            schema_version=1,
            payload={
                "action": "review_decided",
                "state": "accepted",
                "target_adapter_kind": "dj_set",
                "answers": "must-not-enter-the-envelope",
            },
        )
