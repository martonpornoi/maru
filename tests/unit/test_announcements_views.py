"""Native pages keep current authority, exact copy and manual reports separate."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError
from django.http import QueryDict
from django.test import RequestFactory

from maru.announcements import views
from maru.announcements.contracts import (
    AnnouncementCommandResult,
    AnnouncementDetail,
    AnnouncementDownload,
    AnnouncementPage,
    AnnouncementPublicationReportView,
    AnnouncementRevisionView,
    AnnouncementVariantView,
)
from maru.announcements.errors import (
    AnnouncementDeniedError,
    AnnouncementVersionConflictError,
)
from maru.events import announcements_setup_views as setup_views
from maru.events.announcements_setup_queries import AnnouncementsSetupChoices
from maru.events.announcements_workspace_queries import AnnouncementsWorkspaceReference
from maru.identity.models import Account
from tests.unit.test_announcements_forms import (
    announcement_settings as announcement_settings,  # noqa: PLC0414
)
from tests.unit.test_announcements_forms import draft_data


@pytest.fixture
def page(announcement_settings, monkeypatch):
    now = datetime(2026, 10, 8, 12, tzinfo=UTC)
    variant = AnnouncementVariantView(
        UUID(int=30),
        "news",
        "Synthetic news",
        "",
        "en",
        "Synthetic public headline",
        "Synthetic public body.",
        "reported",
        UUID(int=31),
        "https://example.test/post",
        now,
        now,
        "Synthetic reporter",
        "Synthetic public headline",
        "Synthetic public body.",
    )
    revision = AnnouncementRevisionView(
        UUID(int=32), 1, variant.headline, variant.body, "en", (variant,), now
    )
    detail = AnnouncementDetail(
        UUID(int=33),
        "approved",
        3,
        revision,
        revision,
        "PRIVATE REVIEW NOTE",
        can_compose=True,
        can_review=True,
        can_record_publication=True,
        can_export_evidence=True,
        stopped=False,
        publication_history=(
            AnnouncementPublicationReportView(
                id=UUID(int=31),
                variant_id=variant.id,
                revision_id=revision.id,
                revision_number=revision.number,
                channel_code=variant.channel_code,
                channel_label=variant.channel_label,
                channel_url=variant.channel_url,
                language_code=variant.language_code,
                publication_url=variant.publication_url,
                publication_published_at=now,
                publication_recorded_at=now,
                publication_reporter_label="Synthetic reporter",
                withdrawn=False,
                supersedes_report_id=None,
                reason="",
                can_correct=True,
            ),
        ),
    )
    reference = AnnouncementsWorkspaceReference(
        UUID(int=20),
        UUID(int=21),
        "Synthetic organizer",
        "Synthetic convention",
        "Synthetic edition",
        "announcements_only",
        1,
    )
    authorize = Mock()
    monkeypatch.setattr(views, "authorize_announcements_scope", authorize)
    settings_query = Mock(return_value=announcement_settings)
    detail_query = Mock(return_value=detail)
    monkeypatch.setattr(views, "load_announcement_settings", settings_query)
    monkeypatch.setattr(views, "load_announcement", detail_query)
    monkeypatch.setattr(
        views, "announcements_workspace_reference", Mock(return_value=reference)
    )
    monkeypatch.setattr(
        views,
        "list_announcements",
        Mock(
            return_value=AnnouncementPage(
                (),
                None,
                can_compose=True,
                can_manage_settings=True,
                settings_ready=True,
            )
        ),
    )
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
    commands = {}
    for name in (
        "create_announcement",
        "revise_announcement",
        "request_announcement_review",
        "review_announcement",
        "record_announcement_publication",
        "correct_announcement_publication",
        "cancel_announcement",
        "update_announcement_settings",
        "set_announcements_stopped",
    ):
        commands[name] = Mock(
            return_value=AnnouncementCommandResult(
                UUID(int=34), detail.id, 4, detail.id
            )
        )
        monkeypatch.setattr(views.services, name, commands[name])
    download = Mock(
        return_value=AnnouncementDownload(
            "untrusted-title.json", "application/json", b'{"public":"copy"}'
        )
    )
    monkeypatch.setattr(views, "load_approved_announcement_copy", download)
    monkeypatch.setattr(
        views, "load_approved_announcement_preview", Mock(return_value=revision)
    )
    monkeypatch.setattr(
        views,
        "export_announcement_evidence",
        Mock(
            return_value=AnnouncementDownload(
                "evidence.json", "application/json", b'{"private":"evidence"}'
            )
        ),
    )
    return SimpleNamespace(
        detail=detail,
        reference=reference,
        settings=announcement_settings,
        settings_query=settings_query,
        detail_query=detail_query,
        authorize=authorize,
        commands=commands,
        download=download,
    )


def call(page, action="detail", data=None, query="", report_id=None, *, csrf=False):
    path = views._url(
        SimpleNamespace(
            organization_id=page.reference.organization_id,
            edition_id=page.reference.edition_id,
        ),
        action,
        page.detail.id
        if action not in {"inventory", "new", "settings", "stop", "resume"}
        else None,
        report_id,
    )
    if data is None:
        request = RequestFactory().get(path + query)
    else:
        encoded = QueryDict("", mutable=True)
        encoded.update(data)
        request = RequestFactory().post(
            path + query,
            data=encoded.urlencode(),
            content_type="application/x-www-form-urlencoded",
        )
    request.user = Account(
        id=UUID(int=22), email="synthetic@example.test", is_active=True
    )
    request._dont_enforce_csrf_checks = not csrf
    request.session = {}
    request._messages = FallbackStorage(request)
    page.last_request = request
    return views.announcements_workspace(
        request,
        page.reference.organization_id,
        page.reference.edition_id,
        action=action,
        announcement_id=page.detail.id
        if action not in {"inventory", "new", "settings", "stop", "resume"}
        else None,
        report_id=report_id,
    )


def test_detail_has_one_shared_landmark_and_truthful_separate_states(page):
    response = call(page)
    assert response.status_code == 200
    assert response.content.count(b"<h1>") == 1
    assert response.content.count(b"<main ") == 1
    for phrase in (
        b"Writing status",
        b"Ready to publish",
        b"Publication reported",
        b"Record publication",
        b"English",
    ):
        assert phrase in response.content
    assert b">Publish<" not in response.content
    assert "no-store" in response["Cache-Control"]
    assert "form-action 'self'" in response["Content-Security-Policy"]


def test_copy_and_download_never_expose_private_feedback_or_mutate(page):
    for action in ("copy", "text-download", "download"):
        response = call(page, action)
        assert response.status_code == 200
        assert b"PRIVATE REVIEW NOTE" not in response.content
        assert b"Synthetic reporter" not in response.content
    for command in page.commands.values():
        command.assert_not_called()
    page.detail_query.assert_not_called()
    page.settings_query.assert_not_called()
    response = call(page, "text-download")
    assert (
        response["Content-Disposition"]
        == f'attachment; filename="announcement-{page.detail.id}.txt"'
    )
    assert response["X-Content-Type-Options"] == "nosniff"


def test_copy_field_permission_does_not_require_private_history(page):
    def admit(_scope, *, capability, fields=frozenset()):
        if capability != "announcements.view" or fields != frozenset({"approved_copy"}):
            raise AnnouncementDeniedError

    page.authorize.side_effect = admit
    for action in ("copy", "text-download", "download"):
        assert call(page, action).status_code == 200
    page.detail_query.assert_not_called()
    page.settings_query.assert_not_called()


def test_download_rechecks_before_releasing_bytes(page):
    page.download.side_effect = [
        AnnouncementDownload(
            "copy.json", "application/json", b"private-protected-by-revocation"
        ),
        AnnouncementDeniedError(),
    ]
    response = call(page, "download")
    assert response.status_code == 404
    assert b"protected-by-revocation" not in response.content


def test_download_post_cannot_mutate(page):
    assert call(page, "download", data={}).status_code == 400
    page.download.assert_not_called()


def test_correction_keeps_old_approved_copy_and_compares_only_changed_posted_text(page):
    changed = replace(
        page.detail.draft, id=UUID(int=40), number=2, body="Pending correction"
    )
    page.detail_query.return_value = replace(
        page.detail, status="in_review", draft=changed
    )
    response = call(page)
    assert b"correction is being prepared" in response.content
    assert b"Publication reported" in response.content
    assert b"Update needed" not in response.content
    variant = replace(
        changed.variants[0],
        body="Approved correction",
        publication_status="update_needed",
    )
    changed = replace(changed, variants=(variant,))
    page.detail_query.return_value = replace(
        page.detail, draft=changed, approved=changed
    )
    response = call(page)
    assert b"Previously posted text" in response.content
    assert b"New approved text" in response.content
    assert b"Update needed" in response.content


def test_invalid_draft_retains_answers_tokens_and_visible_error_links(page):
    data = draft_data(copy_0_channel="")
    response = call(page, "new", data=data)
    assert response.status_code == 400
    assert b'role="alert"' in response.content
    assert b'href="#id_copy_0_channel"' in response.content
    assert b"Synthetic public copy." in response.content
    assert str(UUID(int=11)).encode() in response.content
    page.commands["create_announcement"].assert_not_called()


def test_add_copy_without_javascript_retains_answers_and_does_not_save(page):
    response = call(page, "new", data=draft_data(add_copy="1"))
    assert response.status_code == 200
    assert b'name="copy_1_channel"' in response.content
    assert b"Synthetic public copy." in response.content
    assert str(UUID(int=11)).encode() in response.content
    page.commands["create_announcement"].assert_not_called()


def test_edit_preserves_main_message_reuse_for_exact_matching_copy(page):
    request = RequestFactory().get("/synthetic/edit/")
    loaded = views._Page(page.settings, page.reference, page.detail)
    form = views._form(request, "edit", loaded)
    assert form.initial["copy_0_mode"] == "main"
    assert form.initial["copy_0_body"] == ""
    assert form.initial["body"] == "Synthetic public body."


def test_post_routes_to_owner_with_actual_actor_scope_and_original_retry(page):
    response = call(page, "new", data=draft_data())
    assert response.status_code == 302
    call_args = page.commands["create_announcement"].call_args
    assert call_args.args[0].actor_id == UUID(int=22)
    assert call_args.args[0].organization_id == page.reference.organization_id
    assert call_args.args[0].idempotency_key == UUID(int=11)
    assert call_args.kwargs["expected_settings_version"] == 2
    assert [str(message) for message in get_messages(page.last_request)] == [
        "Draft saved."
    ]


def test_report_uses_actual_selected_copy_and_convention_time_zone(page):
    response = call(
        page,
        "report",
        data={
            "expected_version": "3",
            "idempotency_key": str(UUID(int=11)),
            "variant_id": str(page.detail.approved.variants[0].id),
            "published_at": "2026-10-08T12:30",
            "publication_url": "https://example.test/post",
            "confirmed": "on",
        },
    )
    assert response.status_code == 302
    arguments = page.commands["record_announcement_publication"].call_args.kwargs
    assert arguments["published_at"].utcoffset() == timedelta(hours=2)
    assert arguments["variant_id"] == page.detail.approved.variants[0].id


def test_stale_submission_preserves_original_version_and_body(page):
    page.commands["create_announcement"].side_effect = AnnouncementVersionConflictError
    response = call(page, "new", data=draft_data())
    assert response.status_code == 409
    assert b"original answers are retained" in response.content
    assert b'value="1"' in response.content
    assert b"Synthetic public copy." in response.content


def test_denied_action_precedes_private_input_and_labels(page):
    page.authorize.side_effect = AnnouncementDeniedError
    response = call(page, "new", data={"unexpected": "private"}, query="?bad=input")
    assert response.status_code == 404
    assert b"Synthetic" not in response.content
    page.settings_query.assert_not_called()


def test_final_revocation_releases_no_prepared_private_bytes(page):
    page.detail_query.side_effect = [page.detail, AnnouncementDeniedError()]
    response = call(page)
    assert response.status_code == 404
    assert b"Synthetic public" not in response.content
    assert b"PRIVATE" not in response.content


def test_dependency_failure_is_not_an_empty_inventory(page):
    page.settings_query.side_effect = DatabaseError
    response = call(page, "inventory")
    assert response.status_code == 503
    assert b"No announcements yet" not in response.content


def test_foreign_report_is_not_a_correction_form(page):
    response = call(page, "correct-report", report_id=UUID(int=999))
    assert response.status_code == 404
    assert b"Synthetic" not in response.content


@pytest.mark.parametrize(
    ("stopped", "status"), [(True, "approved"), (False, "cancelled")]
)
def test_stop_and_cancel_keep_retrospective_reporting_and_correction_links(
    page, stopped, status
):
    page.detail_query.return_value = replace(
        page.detail, stopped=stopped, status=status, can_compose=False
    )
    response = call(page)
    assert response.status_code == 200
    assert b"Record publication" in response.content
    assert b"Correct this report" in response.content
    assert b"record an earlier publication" in response.content
    assert b"does not reopen writing or review" in response.content


def correction_data():
    return {
        "expected_version": "3",
        "idempotency_key": str(UUID(int=11)),
        "confirmed": "on",
        "reason": "Correct the mistaken link.",
        "withdrawn": "no",
        "published_at": "2026-10-08T13:00",
        "publication_url": "https://example.test/correct",
    }


def test_correct_report_exact_post_retry_reaches_owner_after_report_was_superseded(
    page,
):
    original = replace(page.detail.publication_history[0], can_correct=False)
    replacement = replace(
        original, id=UUID(int=38), can_correct=True, supersedes_report_id=original.id
    )
    page.detail_query.return_value = replace(
        page.detail, publication_history=(original, replacement)
    )
    page.commands[
        "correct_announcement_publication"
    ].return_value = AnnouncementCommandResult(
        UUID(int=34), replacement.id, 4, page.detail.id, replayed=True
    )
    response = call(
        page, "correct-report", data=correction_data(), report_id=original.id
    )
    assert response.status_code == 302
    invocation = page.commands["correct_announcement_publication"].call_args
    assert invocation.kwargs["report_id"] == original.id
    assert invocation.args[0].idempotency_key == UUID(int=11)
    assert [str(message) for message in get_messages(page.last_request)] == [
        "This change was already saved."
    ]
    assert call(page, "correct-report", report_id=original.id).status_code == 409


def test_retained_report_stays_visible_and_correctable_after_channel_removal(page):
    current = replace(page.detail.approved, id=UUID(int=50), number=2, variants=())
    page.detail_query.return_value = replace(
        page.detail, draft=current, approved=current
    )
    response = call(page)
    assert response.status_code == 200
    assert b"Publication history and earlier reports" in response.content
    assert b"Correct this retained report" in response.content
    report = page.detail.publication_history[0]
    response = call(page, "correct-report", report_id=report.id)
    assert response.status_code == 200
    assert b"copy version 1" in response.content
    assert report.publication_url.encode() in response.content


def test_removed_channel_retry_reaches_owner_with_original_values(page):
    page.settings_query.return_value = replace(
        page.settings, version=3, channels=(), language_codes=("hu",)
    )
    page.commands["create_announcement"].return_value = AnnouncementCommandResult(
        UUID(int=34), page.detail.id, 1, page.detail.id, replayed=True
    )
    response = call(page, "new", data=draft_data())
    assert response.status_code == 302
    invocation = page.commands["create_announcement"].call_args
    assert invocation.kwargs["expected_settings_version"] == 2
    assert invocation.kwargs["draft"].variants[0].channel_code == "news"
    assert invocation.kwargs["draft"].language_code == "en"


def test_stale_edit_passes_original_settings_cursor_and_keeps_answers(page):
    page.settings_query.return_value = replace(page.settings, version=3)
    page.commands["revise_announcement"].side_effect = AnnouncementVersionConflictError
    response = call(page, "edit", data=draft_data(reason="Keep this correction."))
    assert response.status_code == 409
    assert (
        page.commands["revise_announcement"].call_args.kwargs[
            "expected_settings_version"
        ]
        == 2
    )
    assert b"Synthetic public copy." in response.content
    assert b'name="expected_settings_version" value="2"' in response.content


def test_requested_changes_explain_edit_first_without_dead_end_review_link(page):
    page.detail_query.return_value = replace(page.detail, status="changes_requested")
    response = call(page)
    assert b"Edit the draft and save a new version" in response.content
    assert b"/request-review/" not in response.content


def test_required_marker_is_inside_the_label_before_the_input(page):
    response = call(page, "new")
    assert (
        b'<label for="id_headline">Headline <span>(required)</span></label>'
        in response.content
    )


def test_mutation_requires_csrf(page):
    response = call(page, "new", data=draft_data(), csrf=True)
    assert response.status_code == 403
    page.commands["create_announcement"].assert_not_called()


def test_setup_denial_precedes_foundation_choices(page, monkeypatch):
    monkeypatch.setattr(
        setup_views,
        "require_announcements_setup_actor",
        Mock(side_effect=PermissionDenied),
    )
    choices = Mock()
    monkeypatch.setattr(setup_views, "load_announcements_setup_choices", choices)
    request = RequestFactory().get("/admin/platform/setup/announcements/")
    request.user = Account(
        id=UUID(int=22), email="synthetic@example.test", is_active=True
    )
    response = setup_views.announcements_setup_workspace(request)
    assert response.status_code == 404
    choices.assert_not_called()


def test_setup_preserves_explicit_multilanguage_input_and_hands_off_acceptance(
    page, monkeypatch
):
    monkeypatch.setattr(setup_views, "require_announcements_setup_actor", Mock())
    monkeypatch.setattr(
        setup_views,
        "load_announcements_setup_choices",
        Mock(return_value=AnnouncementsSetupChoices()),
    )
    command = Mock(return_value=SimpleNamespace(organization_slug="synthetic"))
    monkeypatch.setattr(setup_views, "set_up_announcements_adoption", command)
    data = QueryDict("", mutable=True)
    data.update(
        {
            "organization_name": "Synthetic organizer",
            "series_name": "Synthetic convention",
            "edition_name": "Synthetic 2027",
            "starts_on": "2027-01-01",
            "ends_on": "2027-01-02",
            "time_zone": "Europe/Budapest",
            "reason": "Test standalone adoption",
            "confirmed": "on",
            "idempotency_key": str(UUID(int=11)),
        }
    )
    data.setlist("language_codes", ["en", "hu"])
    request = RequestFactory().post(
        "/admin/platform/setup/announcements/new/",
        data=data.urlencode(),
        content_type="application/x-www-form-urlencoded",
    )
    request.user = Account(
        id=UUID(int=22), email="synthetic@example.test", is_active=True
    )
    request._dont_enforce_csrf_checks = True
    response = setup_views.announcements_setup_workspace(request, mode="new_foundation")
    assert response.status_code == 302
    assert command.call_args.kwargs["details"].language_codes == ("en", "hu")
    assert "representation" in response["Location"]
