"""Real task forms preserve typed values, choice provenance and subject consent."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from django.core.exceptions import ValidationError

from maru.applications import programme_personal_forms as forms
from tests.unit import test_application_programme_proposal_views as intake
from tests.unit.test_application_answer_values import _normalize
from tests.unit.test_application_programme_call_editor import _graph, _projection

page = intake.page


def evidence(**extra):
    return {
        "retry_key": str(UUID(int=500)),
        "expected_version": "7",
        "expected_call_version": "2",
        "expected_definition_version": "1",
        "reason": "Update this exact proposal",
        "confirm": "on",
    } | extra


def question(kind):
    return next(
        row
        for row in _projection(_graph()).sections[0].questions
        if row.field_type == kind
    )


@pytest.mark.parametrize(
    ("kind", "raw", "expected"),
    [
        ("short_text", "A talk", "A talk"),
        ("long_text", "Detailed proposal", "Detailed proposal"),
        ("integer", "12", 12),
        ("decimal", "12.5000", "12.5000"),
        ("boolean", "false", False),
        ("single_choice", "talk", "talk"),
        ("multiple_choice", ["talk", "panel"], ["talk", "panel"]),
        ("date", "2027-01-15", "2027-01-15"),
        ("time", "12:30", "12:30:00"),
        ("instant", "2027-01-15T12:30:00+02:00", "2027-01-15T12:30:00+02:00"),
        ("email", "person@example.invalid", "person@example.invalid"),
        ("phone", "+36123456789", "+36123456789"),
        ("url", "https://example.invalid/proposal", "https://example.invalid/proposal"),
    ],
)
def test_typed_task_values_preserve_existing_owner_semantics(kind, raw, expected):
    spec = question(kind)
    form = forms.ProgrammePersonalAnswerForm(evidence(value=raw), question=spec)
    assert form.is_valid(), form.errors
    assert form.answer == expected
    assert (
        _normalize(
            kind,
            form.answer,
            options=[{"code": row.code, "label": row.label} for row in spec.options],
            maximum_choices=spec.maximum_choices,
            minimum_value=spec.minimum_value,
            maximum_value=spec.maximum_value,
            minimum_length=spec.minimum_length,
            maximum_length=spec.maximum_length,
        )
        == expected
    )


def test_address_is_labelled_fields_without_json_or_silent_data_loss():
    address = {
        "line_1": "Main street 1",
        "line_2": "",
        "locality": "Budapest",
        "region": "",
        "postal_code": "1000",
        "country_code": "HU",
    }
    form = forms.ProgrammePersonalAnswerForm(
        evidence(**address), question=question("address")
    )
    assert "value" not in form.fields
    assert form.is_valid(), form.errors
    assert form.answer == address
    assert _normalize("address", form.answer) == address


@pytest.mark.parametrize("kind", ["person_reference", "domain_reference", "safe_file"])
def test_unavailable_reference_choices_do_not_turn_into_uuid_entry(kind):
    with pytest.raises(ValueError, match="chooser"):
        forms.ProgrammePersonalAnswerForm(question=question(kind))


@pytest.mark.parametrize(
    "kind", ["short_text", "integer", "boolean", "single_choice", "instant", "address"]
)
def test_required_answer_can_remain_blank_in_draft(kind):
    form = forms.ProgrammePersonalAnswerForm(evidence(), question=question(kind))
    assert form.is_valid(), form.errors
    assert form.answer is None


def test_integer_form_retains_rejected_value_and_original_proofs():
    original = evidence(value="25")
    form = forms.ProgrammePersonalAnswerForm(original, question=question("integer"))
    assert not form.is_valid()
    assert "value" in form.errors
    assert form["value"].value() == "25"
    assert form["expected_version"].value() == "7"
    assert form["retry_key"].value() == original["retry_key"]


def test_single_choice_has_explicit_blank_not_implicit_first_answer():
    form = forms.ProgrammePersonalAnswerForm(question=question("single_choice"))
    assert next(iter(form.fields["value"].choices)) == ("", "Not answered")
    assert form["value"].value() is None


def test_unzoned_instant_is_never_silently_interpreted():
    form = forms.ProgrammePersonalAnswerForm(
        evidence(value="2027-01-15T12:30"), question=question("instant")
    )
    assert form.is_valid()
    assert form.answer == "2027-01-15T12:30"
    with pytest.raises(ValidationError):
        _normalize("instant", form.answer)


def test_profile_revision_does_not_preselect_publication_or_consent(page):
    form = forms.ProgrammePersonalProfileForm(detail=page.detail)
    assert form["publication_choice"].value() is None
    assert not form["consent_acknowledged"].value()
    assert "public_name" in form.fields


def test_profile_rejects_nonpublic_populated_values_without_clearing(page):
    form = forms.ProgrammePersonalProfileForm(
        evidence(publication_choice="no", public_name="Retain my input"),
        detail=page.detail,
    )
    assert not form.is_valid()
    assert form["public_name"].value() == "Retain my input"
    assert form.profile is None


def test_profile_uses_exact_subject_policy_and_explicit_acknowledgement(page):
    form = forms.ProgrammePersonalProfileForm(
        evidence(
            publication_choice="yes",
            public_name="My proposal name",
            consent_acknowledged="on",
        ),
        detail=page.detail,
    )
    assert form.is_valid(), form.errors
    assert form.profile.public_name == "My proposal name"
    assert (
        form.profile.consent_policy_code == page.detail.contributor_consent_policy_code
    )


def test_hidden_profile_field_override_is_refused(page):
    requirements = tuple(
        replace(row, lead_requirement="hidden")
        for row in page.detail.own_profile_requirements
    )
    detail = replace(page.detail, own_profile_requirements=requirements)
    form = forms.ProgrammePersonalProfileForm(
        evidence(publication_choice="no", public_name="Hidden override"), detail=detail
    )
    assert "public_name" not in form.fields
    assert not form.is_valid()


@pytest.mark.parametrize("expiry", ["2027-01-15T12:30", "not a date"])
def test_invitation_requires_explicit_offset(expiry):
    form = forms.ProgrammePersonalInvitationForm(
        evidence(email="person@example.invalid", expires_at=expiry)
    )
    assert not form.is_valid()
    assert "expires_at" in form.errors


def test_invitation_normalizes_only_explicit_offset():
    form = forms.ProgrammePersonalInvitationForm(
        evidence(email="person@example.invalid", expires_at="2027-01-15T12:30+02:00")
    )
    assert form.is_valid(), form.errors
    assert form.invitation().expires_at == datetime(2027, 1, 15, 10, 30, tzinfo=UTC)


def test_selection_uses_only_current_labelled_catalog_and_format_bounds(page):
    context = SimpleNamespace(tracks=page.call.tracks, formats=page.call.formats)
    values = evidence(
        track=str(page.call.tracks[0].track_id),
        format=str(page.call.formats[0].format_id),
        duration="30",
    )
    form = forms.ProgrammePersonalSelectionForm(values, context=context)
    assert form.is_valid(), form.errors
    assert form.selection.requested_duration_minutes == 30
    invalid = forms.ProgrammePersonalSelectionForm(
        values | {"track": str(UUID(int=999))}, context=context
    )
    assert not invalid.is_valid()
    invalid_duration = forms.ProgrammePersonalSelectionForm(
        values | {"duration": "1440"}, context=context
    )
    assert not invalid_duration.is_valid()
