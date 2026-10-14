"""Guidance forms keep required decisions visible and retain exact retry intent."""

from dataclasses import replace
from datetime import date
from uuid import UUID

import pytest
from django.http import QueryDict

from maru.knowledge.contracts import GuidanceActions, GuidanceOptions
from maru.knowledge.forms import DraftForm, ResumeForm, ReviewForm, SettingsForm


@pytest.fixture
def guidance_options():
    return GuidanceOptions(
        settings_version=2,
        control_version=7,
        configured=True,
        stopped=False,
        rules_current=True,
        language_codes=("en", "hu"),
        time_zone="Europe/Budapest",
        placement_codes=("knowledge.compose", "announcements.compose"),
        owner_label="Guidance operators for this event",
        audience_label="People with Guidance access for this event",
        purpose="internal convention guidance",
        actions=GuidanceActions(
            can_view_current=True,
            can_view_working=True,
            can_compose=True,
            can_review=True,
            can_withdraw=True,
            can_manage_settings=True,
            can_export_evidence=True,
        ),
    )


def draft_data(**updates):
    data = {
        "idempotency_key": str(UUID(int=1)),
        "expected_version": "3",
        "expected_settings_version": "2",
        "title": "Synthetic lounge guide",
        "body": "Ask the synthetic lounge lead to confirm reopening information.",
        "language_code": "en",
        "review_by": "",
        "placements": [],
        "reason": "",
    }
    data.update(updates)
    return data


def test_draft_can_wait_for_review_date_but_never_invents_one(guidance_options):
    form = DraftForm(draft_data(), options=guidance_options)
    assert form.is_valid(), form.errors
    assert form.draft_input().review_by is None
    assert form.draft_input().placements == ()
    assert "owner" not in form.fields
    assert "audience" not in form.fields


def test_fixed_owner_audience_and_actor_cannot_be_submitted(guidance_options):
    form = DraftForm(
        draft_data(owner="Someone else", audience="public", actor_id=str(UUID(int=50))),
        options=guidance_options,
    )
    assert not form.is_valid()
    assert "unsupported input" in str(form.non_field_errors())


def test_language_is_an_explicit_human_choice_when_several_exist(guidance_options):
    form = DraftForm(draft_data(language_code=""), options=guidance_options)
    assert not form.is_valid()
    assert "language_code" in form.errors
    choices = dict(form.fields["language_code"].choices)
    assert choices["en"] != "en"
    assert choices["hu"] != "hu"


def test_one_language_and_existing_item_language_are_fixed_visible_metadata(
    guidance_options,
):
    one = DraftForm(options=replace(guidance_options, language_codes=("en",)))
    assert one.initial["language_code"] == "en"
    assert one.fields["language_code"].widget.is_hidden
    existing = DraftForm(
        options=guidance_options, editing=True, initial={"language_code": "hu"}
    )
    assert existing.fields["language_code"].widget.is_hidden
    assert existing.initial["language_code"] == "hu"


def test_changed_configuration_retains_original_form_choices_for_owner_replay(
    guidance_options,
):
    data = draft_data(language_code="hu", placements=["announcements.compose"])
    form = DraftForm(
        data,
        options=replace(
            guidance_options,
            language_codes=("en",),
            placement_codes=("knowledge.compose",),
        ),
    )
    assert form.is_valid(), form.errors
    assert form.draft_input().language_code == "hu"
    assert form.draft_input().placements == ("announcements.compose",)
    assert form.cleaned_data["expected_settings_version"] == 2


@pytest.mark.parametrize(
    "placements", [["unowned.task"], ["knowledge.compose", "knowledge.compose"]]
)
def test_invalid_or_duplicate_placements_are_not_discarded(
    guidance_options, placements
):
    form = DraftForm(draft_data(placements=placements), options=guidance_options)
    assert not form.is_valid()
    assert "placements" in form.errors


def test_multiple_native_checkboxes_reach_the_exact_draft(guidance_options):
    data = QueryDict("", mutable=True)
    data.update(
        {
            key: value
            for key, value in draft_data(review_by="2027-06-18").items()
            if key != "placements"
        }
    )
    data.setlist("placements", ["knowledge.compose", "announcements.compose"])
    form = DraftForm(data, options=guidance_options)
    assert form.is_valid(), form.errors
    assert form.draft_input().review_by == date(2027, 6, 18)
    assert form.draft_input().placements == (
        "knowledge.compose",
        "announcements.compose",
    )


def test_revision_requires_a_reason(guidance_options):
    form = DraftForm(draft_data(), options=guidance_options, editing=True)
    assert not form.is_valid()
    assert "reason" in form.errors


def test_rules_need_a_reference_or_explanation_and_actual_confirmation():
    data = {
        "idempotency_key": str(UUID(int=1)),
        "expected_version": "0",
        "policy_name": "Synthetic rules",
        "record_owner": "Synthetic records team",
        "review_on": "2027-06-18",
        "confirmed": "on",
    }
    form = SettingsForm(data)
    assert not form.is_valid()
    assert "policy_description" in form.errors
    data["policy_description"] = "Synthetic fixture rules, not a real policy approval."
    form = SettingsForm(data)
    assert form.is_valid(), form.errors
    assert form.settings_input().confirmed is True
    data.pop("confirmed")
    assert not SettingsForm(data).is_valid()


def test_review_has_no_automatic_decision_and_needs_feedback_for_changes():
    data = {
        "idempotency_key": str(UUID(int=1)),
        "expected_version": "3",
        "revision_id": str(UUID(int=2)),
        "confirmed": "on",
    }
    assert not ReviewForm(data).is_valid()
    form = ReviewForm({**data, "decision": "changes_requested"})
    assert not form.is_valid()
    assert "note" in form.errors


def test_resume_binds_exact_preview_and_requires_explicit_confirmation():
    data = {
        "idempotency_key": str(UUID(int=1)),
        "expected_control_version": "7",
        "preview_digest": "a" * 64,
        "reason": "Synthetic resumed work",
    }
    assert not ResumeForm(data).is_valid()
    form = ResumeForm({**data, "confirmed": "on"})
    assert form.is_valid(), form.errors
    assert form.cleaned_data["expected_control_version"] == 7
    assert form.cleaned_data["preview_digest"] == "a" * 64
