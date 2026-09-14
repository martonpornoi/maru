"""Database-free invitation, person-response and native-minute form contracts."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from django.core.exceptions import ValidationError

from maru.programme.host_forms import (
    ProgrammeHostAvailabilityForm,
    ProgrammeHostAvailabilityFormSet,
    ProgrammeHostAvailabilityWithdrawalForm,
    ProgrammeHostInvitationForm,
    ProgrammeHostLocalMinuteField,
    ProgrammeHostReinvitationForm,
    ProgrammeHostResponseForm,
)


def own_versions():
    return {
        "expected_item_version": "7",
        "expected_host_version": "3",
        "idempotency_key": str(UUID(int=90)),
    }


def test_invitation_and_reinvitation_require_explicit_copy_not_private_defaults():
    fresh = ProgrammeHostInvitationForm()
    repeated = ProgrammeHostReinvitationForm()
    for form in (fresh, repeated):
        assert form["title"].value() is None
        assert form["briefing"].value() is None
        assert "actor_id" not in form.fields
        assert "account_id" not in form.fields
    assert "recipient_email" in fresh.fields
    assert "recipient_email" not in repeated.fields
    assert "expected_host_version" in repeated.fields
    assert list(repeated.fields)[:4] == ["role", "title", "briefing", "reason"]


@pytest.mark.parametrize(
    "form_class",
    [
        ProgrammeHostResponseForm,
        ProgrammeHostAvailabilityForm,
        ProgrammeHostAvailabilityWithdrawalForm,
    ],
)
def test_person_forms_never_ask_for_private_explanations_or_another_subject(form_class):
    assert (
        not {
            "reason",
            "account_id",
            "actor_id",
            "host_id",
            "organization_id",
            "edition_id",
        }
        & form_class.base_fields.keys()
    )
    assert form_class.base_fields["expected_host_version"].widget.is_hidden


def test_person_response_retains_exact_invitation_and_versions():
    form = ProgrammeHostResponseForm(
        {**own_versions(), "invitation_sequence": "2", "response": "decline"}
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data == {
        "expected_item_version": 7,
        "expected_host_version": 3,
        "invitation_sequence": 2,
        "response": "decline",
        "idempotency_key": UUID(int=90),
    }


@pytest.mark.parametrize("value", ["unknown", "withdrawn", "", "SHARED"])
def test_period_replacement_requires_draft_or_deliberate_sharing(value):
    form = ProgrammeHostAvailabilityForm(
        {**own_versions(), "expected_edition_version": "2", "state": value}
    )
    assert not form.is_valid()
    assert "state" in form.errors


def test_availability_withdrawal_has_no_period_or_edition_dependency_input():
    form = ProgrammeHostAvailabilityWithdrawalForm(
        {**own_versions(), "confirm_withdrawal": "on"}
    )
    assert form.is_valid(), form.errors
    assert "expected_edition_version" not in form.fields
    assert "periods" not in form.fields


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2030-08-02T10:00", datetime(2030, 8, 2, 8, 0, tzinfo=UTC)),
        ("2030-01-02T10:00", datetime(2030, 1, 2, 9, 0, tzinfo=UTC)),
    ],
)
def test_native_local_minute_resolves_the_edition_zone(value, expected):
    field = ProgrammeHostLocalMinuteField(zone_name="Europe/Budapest")
    assert field.clean(value) == expected
    assert field.prepare_value(expected) == value
    assert field.widget.input_type == "datetime-local"


@pytest.mark.parametrize(
    "value",
    [
        "2026-03-29T02:30",
        "2026-10-25T02:30",
        "2030-08-02T10:00:01",
        "2030-08-02T10:00Z",
        "2030-13-01T10:00",
        "2030-08-02",
        "",
        "9" * 5000,
    ],
)
def test_native_controls_reject_ambiguous_nonexistent_or_nonminute_input(value):
    field = ProgrammeHostLocalMinuteField(zone_name="Europe/Budapest")
    with pytest.raises(ValidationError):
        field.clean(value)


def period_data(total="1"):
    return {
        "periods-TOTAL_FORMS": total,
        "periods-INITIAL_FORMS": "0",
        "periods-MIN_NUM_FORMS": "0",
        "periods-MAX_NUM_FORMS": "128",
        "periods-0-starts_at": "2030-08-02T10:00",
        "periods-0-ends_at": "2030-08-02T11:00",
        "periods-0-kind": "preferred",
    }


def test_native_period_rows_preserve_original_text_and_explicit_kind():
    formset = ProgrammeHostAvailabilityFormSet(
        period_data(), prefix="periods", form_kwargs={"zone_name": "Europe/Budapest"}
    )
    assert formset.is_valid(), formset.errors
    row = formset.cleaned_data[0]
    assert row["starts_at"] == datetime(2030, 8, 2, 8, 0, tzinfo=UTC)
    assert row["kind"] == "preferred"
    assert formset.forms[0]["starts_at"].value() == "2030-08-02T10:00"


def test_deleted_period_is_an_explicit_complete_replacement_choice():
    formset = ProgrammeHostAvailabilityFormSet(
        {**period_data(), "periods-0-DELETE": "on"},
        prefix="periods",
        form_kwargs={"zone_name": "UTC"},
    )
    assert formset.is_valid(), formset.errors
    assert len(formset.deleted_forms) == 1


def test_huge_formset_count_is_capped_and_rejected_before_owner_work():
    formset = ProgrammeHostAvailabilityFormSet(
        period_data("1000000"), prefix="periods", form_kwargs={"zone_name": "UTC"}
    )
    assert len(formset.forms) == 128
    assert not formset.is_valid()
    assert formset.non_form_errors()
