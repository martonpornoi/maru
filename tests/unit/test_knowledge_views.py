"""Current-reader pages cannot load private work or disclose stale reader copy."""

from dataclasses import replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError
from django.http import QueryDict
from django.test import RequestFactory

from maru.identity.models import Account
from maru.knowledge import views
from maru.knowledge.contracts import (
    GuidanceCommandResult,
    GuidanceCurrentPage,
    GuidanceCurrentSummary,
    GuidanceCurrentView,
    GuidanceDownload,
    GuidanceResumePreview,
    GuidanceRevisionView,
    GuidanceSettingsView,
    GuidanceWorkingDetail,
    GuidanceWorkingPage,
)
from maru.knowledge.errors import (
    GuidanceDeniedError,
    GuidanceNotAvailableError,
    GuidanceVersionConflictError,
)
from tests.unit.test_knowledge_forms import draft_data
from tests.unit.test_knowledge_forms import (
    guidance_options as guidance_options,  # noqa: PLC0414 - shared pytest fixture
)


@pytest.fixture
def page(guidance_options, monkeypatch):
    now = datetime(2026, 10, 9, 12, tzinfo=UTC)
    summary = GuidanceCurrentSummary(
        UUID(int=30),
        UUID(int=31),
        "Synthetic lounge guidance",
        "en",
        1,
        now,
        date(2027, 6, 18),
        review_due=False,
        owner_label=guidance_options.owner_label,
    )
    current = GuidanceCurrentView(
        summary,
        "APPROVED CURRENT TEXT",
        guidance_options.purpose,
        guidance_options.audience_label,
        ("announcements.compose",),
    )
    draft = GuidanceRevisionView(
        UUID(int=32),
        2,
        summary.title,
        "PRIVATE WORKING TEXT",
        "en",
        date(2027, 6, 19),
        ("knowledge.compose",),
        now,
    )
    detail = GuidanceWorkingDetail(
        summary.id,
        3,
        "draft",
        withdrawn=False,
        draft=draft,
        last_approved=draft,
        current=current,
        review_note="PRIVATE FEEDBACK",
        history=(),
        options=guidance_options,
        actions=guidance_options.actions,
    )
    reference = SimpleNamespace(
        organization_id=UUID(int=20),
        edition_id=UUID(int=21),
        organization_name="Synthetic team",
        series_name="Synthetic convention",
        edition_name="Synthetic 2027",
        time_zone="Europe/Budapest",
        profile_code="announcements_guidance",
        profile_version=1,
    )
    authorize = Mock()
    monkeypatch.setattr(views, "authorize_guidance_scope", authorize)
    monkeypatch.setattr(
        views, "require_guidance_access_actor", Mock(side_effect=PermissionDenied)
    )
    monkeypatch.setattr(
        views, "knowledge_workspace_reference", Mock(return_value=reference)
    )
    current_query = Mock(return_value=current)
    private_query = Mock(return_value=detail)
    settings_query = Mock(
        return_value=GuidanceSettingsView(guidance_options, UUID(int=5))
    )
    monkeypatch.setattr(views, "load_current_guidance", current_query)
    monkeypatch.setattr(views, "load_working_guidance", private_query)
    monkeypatch.setattr(views, "load_guidance_settings", settings_query)
    monkeypatch.setattr(
        views, "load_guidance_options", Mock(return_value=guidance_options)
    )
    monkeypatch.setattr(
        views,
        "list_current_guidance",
        Mock(
            return_value=GuidanceCurrentPage((summary,), None, guidance_options.actions)
        ),
    )
    monkeypatch.setattr(
        views,
        "list_working_guidance",
        Mock(return_value=GuidanceWorkingPage((), None, guidance_options)),
    )
    monkeypatch.setattr(
        views,
        "load_context_guidance",
        Mock(return_value=GuidanceCurrentPage((), None, guidance_options.actions)),
    )
    monkeypatch.setattr(
        views,
        "load_guidance_resume_preview",
        Mock(
            return_value=GuidanceResumePreview(7, "a" * 64, (summary,), can_resume=True)
        ),
    )
    monkeypatch.setattr(
        views,
        "download_current_guidance",
        Mock(
            return_value=GuidanceDownload(
                "untrusted\r\nname",
                "untrusted/type",
                b'{"current":true}',
                content_fingerprint="c" * 64,
            )
        ),
    )
    monkeypatch.setattr(
        views,
        "export_guidance_evidence",
        Mock(
            return_value=GuidanceDownload(
                "private.json", "application/json", b'{"private":true}'
            )
        ),
    )
    commands = {}
    for name in (
        "create_guidance",
        "revise_guidance",
        "request_guidance_review",
        "review_guidance",
        "withdraw_guidance",
        "update_guidance_settings",
        "stop_guidance",
        "resume_guidance",
    ):
        commands[name] = Mock(
            return_value=GuidanceCommandResult(UUID(int=33), summary.id, 4, summary.id)
        )
        monkeypatch.setattr(views.services, name, commands[name])
    monkeypatch.setattr(views, "resolve_edition_target", lambda **_kwargs: None)
    monkeypatch.setattr(views.admin.site, "each_context", lambda _request: {})
    monkeypatch.setattr(
        "maru.events.templatetags.admin_edition_context.admin_shell_access",
        lambda _request: {"workspace_available": False},
    )
    monkeypatch.setattr(
        "maru.events.templatetags.admin_edition_context.admin_edition_options",
        lambda _request: {},
    )
    monkeypatch.setattr(
        "maru.events.templatetags.admin_edition_context.project_shell_navigation",
        lambda *_args, **_kwargs: {},
    )
    return SimpleNamespace(
        reference=reference,
        options=guidance_options,
        current=current,
        detail=detail,
        authorize=authorize,
        current_query=current_query,
        private_query=private_query,
        settings_query=settings_query,
        commands=commands,
    )


def call(page, action="current", data=None, query="", *, csrf=False):
    scope = SimpleNamespace(
        organization_id=page.reference.organization_id,
        edition_id=page.reference.edition_id,
    )
    item_id = (
        page.detail.id
        if action
        not in {"inventory", "library", "work", "new", "settings", "stop", "resume"}
        else None
    )
    path = views._url(scope, action, item_id)
    if data is None:
        request = RequestFactory().get(path + query)
    else:
        encoded = QueryDict("", mutable=True)
        for key, value in data.items():
            encoded.setlist(key, value if isinstance(value, list) else [value])
        request = RequestFactory().post(
            path + query,
            data=encoded.urlencode(),
            content_type="application/x-www-form-urlencoded",
        )
    request.user = Account(
        id=UUID(int=22), email="synthetic@example.invalid", is_active=True
    )
    request._dont_enforce_csrf_checks = not csrf
    request.session = {}
    request._messages = FallbackStorage(request)
    page.last_request = request
    return views.guidance_workspace(
        request, scope.organization_id, scope.edition_id, action=action, item_id=item_id
    )


def test_current_reader_never_loads_working_copy_or_rules(page):
    page.private_query.side_effect = AssertionError("Private draft query forbidden")
    page.settings_query.side_effect = AssertionError("Private rules query forbidden")
    response = call(page)
    assert response.status_code == 200
    assert b"APPROVED CURRENT TEXT" in response.content
    assert b"PRIVATE WORKING TEXT" not in response.content
    assert b"PRIVATE FEEDBACK" not in response.content
    page.private_query.assert_not_called()
    page.settings_query.assert_not_called()
    assert "no-store" in response["Cache-Control"]


def test_admission_precedes_labels_input_and_current_copy(page, monkeypatch):
    page.authorize.side_effect = GuidanceDeniedError
    reference = Mock(side_effect=AssertionError("Labels loaded before admission"))
    monkeypatch.setattr(views, "knowledge_workspace_reference", reference)
    response = call(page, query="?unexpected=private")
    assert response.status_code == 404
    assert response.content == b"Guides are unavailable."
    reference.assert_not_called()
    page.current_query.assert_not_called()


@pytest.mark.parametrize("error", [GuidanceDeniedError, GuidanceNotAvailableError])
def test_withdrawn_stopped_and_denied_reader_copy_share_unavailable_shape(page, error):
    page.current_query.side_effect = error
    response = call(page)
    assert response.status_code == 404
    assert response.content == b"Guides are unavailable."
    page.private_query.assert_not_called()


def test_current_copy_changed_during_render_is_not_released(page):
    page.current_query.side_effect = [
        page.current,
        replace(page.current, body="REPLACED TEXT"),
    ]
    response = call(page)
    assert response.status_code == 409
    assert b"APPROVED CURRENT TEXT" not in response.content


def test_reader_download_has_safe_header_and_never_uses_private_history(page):
    response = call(page, "download")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json; charset=utf-8"
    assert (
        response["Content-Disposition"]
        == f'attachment; filename="guidance-{page.detail.id}.json"'
    )
    assert b"private" not in response.content
    page.private_query.assert_not_called()


def test_plain_text_download_contains_exact_approved_copy_and_review_date(page):
    response = call(page, "text-download")
    assert response.status_code == 200
    assert b"APPROVED CURRENT TEXT" in response.content
    assert b"2027-06-18" in response.content
    assert b"Synthetic 2027" in response.content
    assert b"PRIVATE" not in response.content


def test_current_json_returns_final_generated_artifact_for_the_same_copy(
    page, monkeypatch
):
    first = GuidanceDownload(
        "current.json", "application/json", b"FIRST GENERATION", "a" * 64
    )
    final = replace(first, content=b"FINAL GENERATION")
    monkeypatch.setattr(
        views, "download_current_guidance", Mock(side_effect=(first, final))
    )
    response = call(page, "download")
    assert response.status_code == 200
    assert response.content == final.content


@pytest.mark.parametrize("final_fingerprint", ["", "b" * 64])
def test_current_json_rejects_missing_or_changed_final_copy_fingerprint(
    page, monkeypatch, final_fingerprint
):
    first = GuidanceDownload(
        "current.json", "application/json", b"OLD CONTENT", "a" * 64
    )
    final = replace(first, content_fingerprint=final_fingerprint)
    monkeypatch.setattr(
        views, "download_current_guidance", Mock(side_effect=(first, final))
    )
    response = call(page, "download")
    assert response.status_code == 409
    assert b"OLD CONTENT" not in response.content


def test_private_export_requires_its_independent_permission_before_query(
    page, monkeypatch
):
    def authorize(_scope, *, capability, fields=frozenset()):
        if capability == "knowledge.export_evidence":
            raise GuidanceDeniedError

    page.authorize.side_effect = authorize
    query = Mock(side_effect=AssertionError("Forbidden export query"))
    monkeypatch.setattr(views, "export_guidance_evidence", query)
    assert call(page, "evidence").status_code == 404
    query.assert_not_called()


def test_working_only_actor_can_reach_canonical_landing_without_reader_right(page):
    def authorize(_scope, *, capability, fields=frozenset()):
        if capability == "knowledge.view_current":
            raise GuidanceDeniedError

    page.authorize.side_effect = authorize
    response = call(page, "inventory")
    assert response.status_code == 302
    assert response["Location"].endswith("/work/")
    page.current_query.assert_not_called()


def test_reader_only_actor_lands_in_library(page):
    def authorize(_scope, *, capability, fields=frozenset()):
        if capability != "knowledge.view_current":
            raise GuidanceDeniedError

    page.authorize.side_effect = authorize
    response = call(page, "inventory")
    assert response.status_code == 302
    assert response["Location"].endswith("/current/")
    page.private_query.assert_not_called()


def test_revision_conflict_retains_text_versions_and_retry_key(page):
    page.commands["revise_guidance"].side_effect = GuidanceVersionConflictError
    data = draft_data(reason="Synthetic correction", body="RETAIN THESE ORIGINAL WORDS")
    response = call(page, "edit", data)
    assert response.status_code == 409
    assert b"RETAIN THESE ORIGINAL WORDS" in response.content
    command = page.commands["revise_guidance"].call_args
    assert command.args[0].idempotency_key == UUID(int=1)
    assert command.kwargs["expected_version"] == 3
    assert command.kwargs["expected_settings_version"] == 2


def test_service_failure_retains_form_without_partial_reader_fallback(page):
    page.commands["create_guidance"].side_effect = DatabaseError(
        "PRIVATE DATABASE DETAIL"
    )
    response = call(page, "new", draft_data())
    assert response.status_code == 503
    assert b"PRIVATE DATABASE DETAIL" not in response.content
    assert b"Synthetic lounge guide" in response.content


def test_resume_submits_original_preview_even_after_it_changed(page):
    page.commands["resume_guidance"].side_effect = GuidanceVersionConflictError
    data = {
        "idempotency_key": str(UUID(int=1)),
        "expected_control_version": "6",
        "preview_digest": "b" * 64,
        "confirmed": "on",
        "reason": "Synthetic resume",
    }
    response = call(page, "resume", data)
    assert response.status_code == 409
    command = page.commands["resume_guidance"].call_args
    assert command.kwargs["expected_control_version"] == 6
    assert command.kwargs["preview_digest"] == "b" * 64
    assert b"The list changed" in response.content
    assert b"Synthetic lounge guidance" not in response.content


def test_missing_csrf_prevents_a_command(page):
    response = call(page, "new", draft_data(), csrf=True)
    assert response.status_code == 403
    page.commands["create_guidance"].assert_not_called()


@pytest.mark.parametrize(
    "query", ["?q=one&q=two", "?after=not-a-uuid", "?after=", "?unowned=1"]
)
def test_bad_search_transport_does_not_reach_content_query(page, query):
    assert call(page, "library", query=query).status_code == 400


def test_get_never_requests_review_or_records_acknowledgement(page):
    response = call(page, "request-review")
    assert response.status_code == 200
    assert b"Version for review" in response.content
    for command in page.commands.values():
        command.assert_not_called()


def test_blocked_writer_get_explains_actual_owner_blocker_without_fake_save_form(
    page, monkeypatch
):
    options = replace(
        page.options, rules_current=False, blocking_reasons=("team_unavailable",)
    )
    monkeypatch.setattr(views, "load_guidance_options", Mock(return_value=options))
    response = call(page, "new")
    assert response.status_code == 200
    assert b"approved replacement" in response.content
    assert b">Save draft</button>" not in response.content
    assert b"record-keeping rules need" not in response.content


def test_contextual_guide_includes_human_language_without_private_text(
    page, monkeypatch
):
    monkeypatch.setattr(
        views,
        "load_context_guidance",
        Mock(
            return_value=GuidanceCurrentPage(
                (page.current.summary,), None, page.options.actions
            )
        ),
    )
    response = call(page, "new")
    assert b"Guides for this task" in response.content
    assert b"English" in response.content
    assert b"APPROVED CURRENT TEXT" not in response.content


def test_unconfigured_guides_do_not_offer_an_unusable_stop_action(page, monkeypatch):
    options = replace(page.options, configured=False, control_version=0)
    monkeypatch.setattr(views, "load_guidance_options", Mock(return_value=options))
    monkeypatch.setattr(
        views,
        "load_guidance_settings",
        Mock(return_value=GuidanceSettingsView(options, None, "", "", None, "", "")),
    )
    settings = call(page, "settings")
    assert settings.status_code == 200
    assert b">Stop using Guides</a>" not in settings.content
    stop = call(page, "stop")
    assert stop.status_code == 200
    assert b"There is no content to hide" in stop.content
    assert b">Stop using Guides</button>" not in stop.content
    page.commands["stop_guidance"].assert_not_called()


@pytest.mark.parametrize("action", ["edit", "request-review", "review"])
def test_removed_language_get_explains_correction_without_an_unusable_form(
    page, action
):
    options = replace(page.options, language_codes=("hu",))
    detail = replace(page.detail, options=options)
    page.private_query.return_value = detail
    response = call(page, action)
    assert response.status_code == 200
    assert b"Ask an event organizer to restore the language" in response.content
    assert b"Its already approved version remains available" in response.content
    assert b'name="idempotency_key"' not in response.content
