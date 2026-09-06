"""Closed conversion intent, minimized evidence and additive capability contracts."""

from dataclasses import FrozenInstanceError, replace
from importlib import import_module
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.applications.programme_conversion_events import (
    validate_programme_conversion_event,
)
from maru.applications.programme_conversion_inputs import ProgrammeConversionInput
from maru.authorization.catalog import CAPABILITIES, ScopeLevel


def intent():
    return ProgrammeConversionInput(uuid4(), uuid4(), 1, 0, "Deliberate private title")


def test_normalized_private_copy_is_immutable_and_no_source_text_is_inferred():
    value = replace(
        intent(), internal_title="  Private   title ", working_summary="Line 1\nLine 2"
    )
    normalized = value.normalized()
    assert normalized.internal_title == "Private title"
    assert normalized.working_summary == "Line 1\nLine 2"
    assert normalized.normalized() == normalized
    with pytest.raises(FrozenInstanceError):
        normalized.internal_title = "Changed"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("decision_id", "not-a-uuid"),
        ("revision_id", None),
        ("expected_review_version", 0),
        ("expected_review_version", True),
        ("expected_review_version", 2**63 - 1),
        ("expected_programme_version", -1),
        ("expected_programme_version", False),
        ("expected_programme_version", 1.0),
        ("internal_title", " "),
        ("internal_title", "x" * 241),
        ("internal_title", None),
        ("working_summary", "x" * 2001),
        ("working_summary", "Hidden\x00control"),
    ],
)
def test_conversion_rejects_malformed_exact_intent(field, value):
    with pytest.raises(ValidationError):
        replace(intent(), **{field: value}).normalized()


@pytest.mark.parametrize(
    "change",
    [
        {"private_title": "Do not disclose"},
        {"transition_id": "broken"},
        {"programme_item_id": None},
        {"programme_item_id": uuid4()},
        {"transition_id": str(uuid4()).upper()},
    ],
)
def test_conversion_event_rejects_extra_or_noncanonical_identifiers(change):
    payload = {"transition_id": str(uuid4()), "programme_item_id": str(uuid4())}
    validate_programme_conversion_event(payload)
    with pytest.raises(ValidationError):
        validate_programme_conversion_event({**payload, **change})


def test_conversion_capability_is_additive_exact_department_nondelegable():
    previous = import_module(
        "maru.authorization.migrations.0024_programme_review_capabilities"
    )
    current = import_module(
        "maru.authorization.migrations.0025_programme_conversion_capability"
    )
    code = "applications.convert_programme_acceptance"
    assert (*previous.DEPARTMENT_CAPABILITIES, code) == current.DEPARTMENT_CAPABILITIES
    assert current.ORGANIZATION_CAPABILITIES == previous.ORGANIZATION_CAPABILITIES
    assert current.EDITION_CAPABILITIES == previous.EDITION_CAPABILITIES
    assert current.RESOURCE_CAPABILITIES == previous.RESOURCE_CAPABILITIES
    assert {
        code for code, capability in CAPABILITIES.items() if capability.persistable
    } == {
        *current.ORGANIZATION_CAPABILITIES,
        *current.EDITION_CAPABILITIES,
        *current.DEPARTMENT_CAPABILITIES,
        *current.RESOURCE_CAPABILITIES,
    }
    assert CAPABILITIES[code].maximum_scope == ScopeLevel.DEPARTMENT
    assert not CAPABILITIES[code].delegable
