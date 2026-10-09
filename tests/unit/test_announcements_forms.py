"""Native inputs preserve deliberate channels, languages and manual evidence."""

from dataclasses import replace
from datetime import date
from uuid import UUID

import pytest
from django.http import QueryDict

from maru.announcements.contracts import AnnouncementSettingsView, ManualChannel
from maru.announcements.forms import (
    CorrectReportForm,
    DraftForm,
    PublicationForm,
    ReviewForm,
    SettingsForm,
)
from maru.events.announcements_setup_forms import AnnouncementsSetupForm


@pytest.fixture
def announcement_settings():
    return AnnouncementSettingsView(
        version=2,
        revision_id=UUID(int=10),
        configured=True,
        stopped=False,
        rules_current=True,
        policy_name="Synthetic records rules",
        record_owner="Synthetic owner",
        review_on=date(2030, 1, 1),
        policy_url="",
        policy_description="Keep synthetic records for the test.",
        channels=(
            ManualChannel("news", "Synthetic news"),
            ManualChannel("website", "Synthetic website"),
        ),
        language_codes=("en", "hu"),
        time_zone="Europe/Budapest",
        can_manage=True,
    )


def draft_data(**changes):
    data = {
        "headline": "Synthetic announcement",
        "body": "Synthetic public copy.",
        "language_code": "en",
        "expected_version": "1",
        "expected_settings_version": "2",
        "idempotency_key": str(UUID(int=11)),
        "copy_count": "1",
        "reason": "",
        "copy_0_channel": "news",
        "copy_0_language": "en",
        "copy_0_mode": "main",
        "copy_0_headline": "",
        "copy_0_body": "",
    }
    data.update(changes)
    return data


def test_draft_reuses_exact_main_copy_only_for_deliberately_selected_channel(
    announcement_settings,
):
    form = DraftForm(draft_data(), settings=announcement_settings, copy_count=1)
    assert form.is_valid(), form.errors
    draft = form.draft_input()
    assert [
        (row.channel_code, row.language_code, row.body) for row in draft.variants
    ] == [("news", "en", "Synthetic public copy.")]
    assert ("en", "English") in form.fields["language_code"].choices


def test_only_one_configured_language_is_defaulted(announcement_settings):
    ambiguous = DraftForm(settings=announcement_settings, copy_count=1)
    assert "language_code" not in ambiguous.initial
    single = DraftForm(
        settings=replace(announcement_settings, language_codes=("en",)), copy_count=1
    )
    assert single.initial["language_code"] == "en"
    assert single.initial["copy_0_language"] == "en"
    assert "copy_0_channel" not in single.initial


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"copy_0_channel": ""}, "copy_0_channel"),
        ({"copy_0_language": "hu"}, "copy_0_mode"),
        ({"copy_0_body": "Unsaved alternate text"}, "copy_0_mode"),
        ({"copy_0_mode": "custom", "copy_0_body": ""}, "copy_0_body"),
        ({"copy_0_channel": "not a canonical channel"}, "copy_0_channel"),
        ({"actor_id": str(UUID(int=999))}, "__all__"),
    ],
)
def test_draft_rejects_implicit_selection_translation_or_discarded_input(
    announcement_settings, changes, field
):
    form = DraftForm(
        draft_data(**changes), settings=announcement_settings, copy_count=1
    )
    assert not form.is_valid()
    assert field in form.errors
    assert form.data["body"] == "Synthetic public copy."


def test_draft_retains_removed_channel_and_language_for_exact_owner_retry(
    announcement_settings,
):
    current = replace(announcement_settings, channels=(), language_codes=("hu",))
    form = DraftForm(draft_data(), settings=current, copy_count=1)
    assert form.is_valid(), form.errors
    assert form.draft_input().variants[0].channel_code == "news"
    assert form.draft_input().language_code == "en"
    assert form.cleaned_data["expected_settings_version"] == 2
    assert "Previous channel (no longer configured)" in str(form["copy_0_channel"])
    expanded = DraftForm(settings=current, copy_count=2, initial=draft_data())
    assert 'value="news" selected' in str(expanded["copy_0_channel"])


def test_settings_require_explicit_policy_and_named_channels():
    data = {
        "expected_version": "0",
        "idempotency_key": str(UUID(int=12)),
        "policy_name": "Synthetic rules",
        "record_owner": "Synthetic owner",
        "review_on": "2030-01-01",
        "policy_url": "",
        "policy_description": "",
        "confirmed": "on",
        "channel_count": "1",
        "channel_0_code": "news",
        "channel_0_label": "",
        "channel_0_url": "https://example.test/news",
    }
    form = SettingsForm(data, channel_count=1)
    assert not form.is_valid()
    assert {"policy_description", "channel_0_label"} <= set(form.errors)
    data.update(
        policy_description="Keep records for this synthetic rehearsal.",
        channel_0_label="Synthetic news",
    )
    form = SettingsForm(data, channel_count=1)
    assert form.is_valid(), form.errors
    assert form.settings_input().channels == (
        ManualChannel("news", "Synthetic news", "https://example.test/news"),
    )


def test_renaming_an_unlinked_destination_creates_retry_stable_new_identity():
    data = {
        "expected_version": "1",
        "idempotency_key": str(UUID(int=12)),
        "policy_name": "Synthetic rules",
        "record_owner": "Synthetic owner",
        "review_on": "2030-01-01",
        "policy_description": "Retain synthetic records.",
        "confirmed": "on",
        "channel_count": "1",
        "channel_0_code": "news",
        "channel_0_label": "New synthetic destination",
        "channel_0_url": "",
        "channel_0_original_label": "Original destination",
        "channel_0_original_url": "",
    }
    first = SettingsForm(data, channel_count=1)
    retry = SettingsForm(data, channel_count=1)
    assert first.is_valid()
    assert retry.is_valid()
    assert first.settings_input() == retry.settings_input()
    assert first.settings_input().channels[0].code != "news"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.test/news",
        "https://operator:password@example.test/news",
        "javascript:alert(1)",
    ],
)
def test_publication_rejects_unsafe_or_credential_bearing_links(url):
    form = PublicationForm(
        {
            "expected_version": "3",
            "idempotency_key": str(UUID(int=13)),
            "variant_id": str(UUID(int=14)),
            "published_at": "2026-10-08T12:30",
            "publication_url": url,
            "confirmed": "on",
        },
        choices=[(str(UUID(int=14)), "Synthetic news · English")],
    )
    assert not form.is_valid()
    assert "publication_url" in form.errors


def test_review_requires_an_explicit_decision_confirmation_and_useful_feedback():
    form = ReviewForm(
        {
            "expected_version": "3",
            "idempotency_key": str(UUID(int=13)),
            "revision_id": str(UUID(int=14)),
            "decision": "changes_requested",
            "confirmed": "on",
            "note": "",
        }
    )
    assert not form.is_valid()
    assert "note" in form.errors


def test_correcting_a_real_report_requires_actual_time():
    form = CorrectReportForm(
        {
            "expected_version": "3",
            "idempotency_key": str(UUID(int=13)),
            "withdrawn": "no",
            "reason": "Correcting synthetic report",
            "confirmed": "on",
            "publication_url": "https://example.test/post",
        }
    )
    assert not form.is_valid()
    assert "published_at" in form.errors


def test_setup_uses_human_language_choices_and_rejects_renaming_reused_foundation():
    data = QueryDict("", mutable=True)
    data.update(
        {
            "edition_name": "Synthetic 2027",
            "organization_name": "Wrong rename",
            "series_name": "Synthetic convention",
            "starts_on": "2027-01-01",
            "ends_on": "2027-01-02",
            "time_zone": "Europe/Budapest",
            "reason": "Test standalone setup",
            "confirmed": "on",
            "foundation_fingerprint": "a" * 64,
            "idempotency_key": str(UUID(int=1)),
        }
    )
    data.setlist("language_codes", ["en", "hu"])
    form = AnnouncementsSetupForm(
        data, mode="existing_organization", organization_id=UUID(int=2)
    )
    assert not form.is_valid()
    assert "cannot be renamed" in str(form.errors)
    data["organization_name"] = ""
    form = AnnouncementsSetupForm(
        data, mode="existing_organization", organization_id=UUID(int=2)
    )
    assert form.is_valid(), form.errors
    assert form.setup_input().language_codes == ("en", "hu")
    assert ("en", "English") in form.fields["language_codes"].choices
