"""Pure fixed-template meaning and retry identities, without native acceptance."""

from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.workforce.programme_starter_inputs import (
    PROGRAMME_STARTER_DEFINITION,
    ProgrammeStarterAction,
    ProgrammeStarterIntent,
    ProgrammeStarterScope,
    _validate_context,
    normalize_programme_starter_intent,
    programme_starter_decision_digest,
    programme_starter_intent_digest,
)
from maru.workforce.starter_templates import (
    WORKFORCE_VOLUNTEER_CAPACITY_CODES,
    WORKFORCE_VOLUNTEER_CATALOG_ENTRY,
    WORKFORCE_VOLUNTEER_ROLE_CAPABILITIES,
    WORKFORCE_VOLUNTEER_TEMPLATE_CODE,
    WORKFORCE_VOLUNTEER_TEMPLATE_NAME,
)

SCOPE = ProgrammeStarterScope(UUID(int=1), UUID(int=2), UUID(int=3))
INTENT = ProgrammeStarterIntent(UUID(int=4), "Prepare staffing.")


def test_fixed_definition_matches_legacy_meaning_and_frozen_native_pin():
    definition = PROGRAMME_STARTER_DEFINITION
    assert definition.code == WORKFORCE_VOLUNTEER_TEMPLATE_CODE
    assert definition.name == WORKFORCE_VOLUNTEER_TEMPLATE_NAME
    assert definition.catalog_entry == WORKFORCE_VOLUNTEER_CATALOG_ENTRY
    assert definition.capability_codes == WORKFORCE_VOLUNTEER_ROLE_CAPABILITIES
    assert definition.capacity_codes == WORKFORCE_VOLUNTEER_CAPACITY_CODES
    assert definition.digest == (
        "13823da0315a8f4c1bbaf1b465662e0896a894508e8bef8e1a45d36d6da63b6a"
    )


@pytest.mark.parametrize(
    "change",
    [
        {"name": "Changed"},
        {"description": "Changed"},
        {"version": 2},
        {"code": "changed"},
        {"capability_codes": ("events.view_basic",)},
        {"capacity_codes": ()},
        {"default_headcount": 2},
    ],
)
def test_every_definition_field_is_digest_bound(change):
    assert replace(PROGRAMME_STARTER_DEFINITION, **change).digest != (
        PROGRAMME_STARTER_DEFINITION.digest
    )


def test_normalization_is_stable_and_never_changes_person():
    result = normalize_programme_starter_intent(
        replace(INTENT, reason="  Cafe\u0301  day ")
    )
    assert result == replace(INTENT, reason="Café day")
    assert programme_starter_intent_digest(scope=SCOPE, details=INTENT) == (
        programme_starter_intent_digest(
            scope=SCOPE, details=replace(INTENT, reason=" Prepare   staffing. ")
        )
    )


@pytest.mark.parametrize(
    "reason", [None, "", " ", "x" * 241, " " * 4097, "a\nb", "a\x00b", "a\u200bb"]
)
def test_invalid_reason_cannot_be_retained(reason):
    with pytest.raises(ValidationError):
        normalize_programme_starter_intent(replace(INTENT, reason=reason))


@pytest.mark.parametrize("value", [None, "not-uuid", str(UUID(int=4)), UUID(int=0)])
def test_closed_nonzero_person_identifier(value):
    with pytest.raises(ValidationError):
        normalize_programme_starter_intent(replace(INTENT, approver_id=value))


@pytest.mark.parametrize("field", ["organization_id", "series_id", "edition_id"])
def test_every_scope_dimension_is_bound_and_validated(field):
    first = programme_starter_intent_digest(scope=SCOPE, details=INTENT)
    assert (
        programme_starter_intent_digest(
            scope=replace(SCOPE, **{field: uuid4()}), details=INTENT
        )
        != first
    )
    with pytest.raises(ValidationError):
        programme_starter_intent_digest(
            scope=replace(SCOPE, **{field: UUID(int=0)}), details=INTENT
        )


@pytest.mark.parametrize("change", [{"approver_id": UUID(int=5)}, {"reason": "Other"}])
def test_changed_request_intent_changes_retry_identity(change):
    assert programme_starter_intent_digest(
        scope=SCOPE, details=replace(INTENT, **change)
    ) != (programme_starter_intent_digest(scope=SCOPE, details=INTENT))


def test_decision_binds_action_reason_request_and_scope():
    values = {
        "scope": SCOPE,
        "request_id": UUID(int=9),
        "action": ProgrammeStarterAction.APPROVE,
        "reason": "Reviewed",
    }
    original = programme_starter_decision_digest(**values)
    for change in (
        {"action": ProgrammeStarterAction.DECLINE},
        {"action": ProgrammeStarterAction.CANCEL},
        {"reason": "Other"},
        {"request_id": uuid4()},
        {"scope": replace(SCOPE, edition_id=uuid4())},
    ):
        assert programme_starter_decision_digest(**(values | change)) != original
    for invalid in ("approve", "delete", None):
        with pytest.raises(ValidationError):
            programme_starter_decision_digest(**(values | {"action": invalid}))


@pytest.mark.parametrize("channel", [None, "", "UPPER", "a b", "a\n", "a" * 33])
def test_invalid_trace_channel(channel):
    with pytest.raises(ValidationError):
        _validate_context(uuid4(), uuid4(), channel)


def test_trace_context_requires_two_real_uuid_values():
    _validate_context(uuid4(), uuid4(), "staff_console")
    for key, correlation in (
        (UUID(int=0), uuid4()),
        (uuid4(), UUID(int=0)),
        ("key", uuid4()),
    ):
        with pytest.raises(ValidationError):
            _validate_context(key, correlation, "service")
