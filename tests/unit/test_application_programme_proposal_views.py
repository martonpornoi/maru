"""Database-free personal intake with real forms, templates and request fences."""

from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID

import pytest
from bs4 import BeautifulSoup
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import QueryDict
from django.test import RequestFactory
from django.urls import Resolver404, resolve

from maru.applications import programme_proposal_views as views
from maru.applications import programme_queries as queries
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError,
)
from maru.applications.programme_proposal_forms import ProgrammeProposalStartForm
from maru.scheduling.personal_navigation import PersonalProgrammeTaskLink
from tests.unit.test_application_programme_call_editor import _graph, _projection


def source():
    full = _projection(_graph())
    return queries.AvailableProgrammeCallProjection(
        replace(full.summary, status="active"),
        full.purpose,
        full.classification,
        full.contributor_consent_policy_code,
        full.contributor_fields,
        full.tracks,
        full.formats,
    )


def data(call):
    return {
        "retry_key": str(UUID(int=500)),
        "expected_version": "0",
        "expected_call_version": str(call.summary.aggregate_version),
        "expected_definition_version": str(call.summary.version),
        "track": str(call.tracks[0].track_id),
        "format": str(call.formats[0].format_id),
        "duration": "30",
        "publication_choice": "no",
        "reason": "Start my draft",
        "confirm": "on",
    }


@pytest.fixture(autouse=True)
def shell():
    with (
        patch.object(views.admin.site, "each_context", return_value={}),
        patch(
            "maru.events.templatetags.admin_edition_context.admin_shell_access",
            return_value={"workspace_available": False},
        ),
        patch(
            "maru.events.templatetags.admin_edition_context.project_shell_navigation",
            return_value={},
        ),
    ):
        yield


@pytest.fixture
def page(monkeypatch):
    call = source()
    summary = queries.ProgrammeProposalSummaryProjection(
        UUID(int=40),
        UUID(int=41),
        call.summary.call_id,
        call.summary.name,
        "draft",
        1,
        "lead",
        None,
        None,
    )
    selection = queries.ProgrammeSelectionProjection(
        UUID(int=42),
        call.tracks[0].track_id,
        "culture",
        "Culture",
        call.formats[0].format_id,
        "talk",
        "Talk",
        30,
        1,
    )
    detail = queries.ProgrammeProposalDetailProjection(
        views._OWN_PROFILE,
        summary,
        selection,
        None,
        None,
        call.contributor_fields,
        call.contributor_consent_policy_code,
        None,
        None,
        None,
        None,
    )
    entry = Mock(return_value=SimpleNamespace(accepts_private_planning_writes=True))
    auth = Mock(return_value=SimpleNamespace(**asdict(summary)))
    monkeypatch.setattr(views, "authorize_programme_self_entry_scope", entry)
    monkeypatch.setattr(views, "authorize_programme_proposal_scope", auth)
    readers = {}
    for name, value in {
        "available_programme_calls": (call,),
        "list_self_programme_proposals": (
            queries.ProgrammeProposalListItem(summary, selection, None),
        ),
        "get_self_programme_proposal_detail": detail,
    }.items():
        readers[name] = Mock(return_value=value)
        monkeypatch.setattr(queries, name, readers[name])
    writer = Mock(return_value=SimpleNamespace(target_id=summary.proposal_id))
    monkeypatch.setattr(views.commands, "start_programme_proposal", writer)
    return SimpleNamespace(
        call=call,
        summary=summary,
        detail=detail,
        entry=entry,
        auth=auth,
        readers=readers,
        writer=writer,
        actor=UUID(int=1),
        organization=UUID(int=2),
        edition=UUID(int=3),
    )


def request(page, task="inventory", payload=None, *, query="", csrf=False, **kwargs):
    root = f"/my/applications/programme/{page.organization}/{page.edition}/"
    path = {
        "inventory": root,
        "calls": root + "calls/",
        "start": root + f"calls/{page.call.summary.call_id}/start/",
        "detail": root + f"{page.summary.proposal_id}/",
    }.get(task, root)
    factory = RequestFactory()
    if payload is None:
        incoming = factory.get(path + query)
    else:
        encoded = payload if isinstance(payload, QueryDict) else QueryDict(mutable=True)
        if not isinstance(payload, QueryDict):
            encoded.update(payload)
        incoming = factory.post(
            path + query,
            data=encoded.urlencode(),
            content_type="application/x-www-form-urlencoded",
        )
    incoming.user = SimpleNamespace(
        pk=page.actor, is_authenticated=True, is_staff=False
    )
    incoming._dont_enforce_csrf_checks = not csrf
    parameters = {"task": task}
    if task == "start":
        parameters["call_id"] = page.call.summary.call_id
    if task == "detail":
        parameters["proposal_id"] = page.summary.proposal_id
    parameters.update(kwargs)
    return views.programme_proposals(
        incoming, page.organization, page.edition, **parameters
    )


@pytest.mark.parametrize("task", ["inventory", "calls", "start", "detail"])
def test_real_personal_shell_one_heading_and_protected_headers(page, task):
    response = request(page, task)
    assert response.status_code == 200
    soup = BeautifulSoup(response.content, "html.parser")
    assert len(soup.find_all("h1")) == 1
    assert len(soup.find_all("main")) == 1
    assert "no-store" in response["Cache-Control"]
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "form-action 'self'" in response["Content-Security-Policy"]
    assert "not yet connected" in soup.get_text()
    assert not soup.select('a[href*="/admin/applications/"]')


def test_form_only_collects_visible_profile_values_without_preselected_consent(page):
    call = replace(page.call, contributor_fields=(page.call.contributor_fields[0],))
    form = ProgrammeProposalStartForm(source=call)
    assert "public_name" in form.fields
    assert "biography" not in form.fields
    assert form["publication_choice"].value() is None
    assert form["consent_acknowledged"].value() is None
    assert form["track"].value() is None
    assert form["format"].value() is None
    assert form["duration"].value() is None
    assert (
        call.contributor_consent_policy_code
        in form.fields["consent_acknowledged"].label
    )


def test_blank_nonpublic_draft_uses_exact_owner_and_original_evidence(page):
    response = request(page, "start", data(page.call))
    assert response.status_code == 302
    assert response["Location"].endswith(f"/{page.summary.proposal_id}/")
    values = page.writer.call_args.kwargs
    assert values["actor_id"] == page.actor
    assert values["organization_id"] == page.organization
    assert values["edition_id"] == page.edition
    assert values["call_id"] == page.call.summary.call_id
    assert values["expected_version"] == 0
    assert values["retry_key"] == UUID(int=500)
    assert values["source_channel"] == "programme-proposal-workspace"
    assert values["lead_profile"].proposed_for_publication is False
    assert values["lead_profile"].consent_acknowledged is False
    assert values["lead_profile"].public_name == ""


def test_explicit_public_profile_keeps_owner_normalization(page):
    payload = {
        **data(page.call),
        "publication_choice": "yes",
        "consent_acknowledged": "on",
        "public_name": "  Synthetic   person  ",
        "biography": "Two\nlines",
    }
    assert request(page, "start", payload).status_code == 302
    profile = page.writer.call_args.kwargs["lead_profile"]
    assert profile.public_name == "Synthetic person"
    assert profile.biography == "Two\nlines"
    assert profile.consent_policy_code == page.call.contributor_consent_policy_code


@pytest.mark.parametrize(
    "updates",
    [
        {"publication_choice": ""},
        {"confirm": ""},
        {"reason": ""},
        {"public_name": "Retain this", "publication_choice": "no"},
        {"public_name": "Name", "publication_choice": "yes"},
        {"publication_choice": "yes", "consent_acknowledged": "on"},
        {"track": str(UUID(int=900))},
        {"format": str(UUID(int=900))},
        {"duration": "14"},
        {"duration": "61"},
        {"duration": "30.0"},
        {"duration": "030"},
        {"expected_version": "1"},
        {"retry_key": "bad"},
        {"expected_call_version": "1.0"},
        {"expected_definition_version": "0"},
    ],
)
def test_invalid_input_never_calls_writer_and_retains_bound_input(page, updates):
    response = request(page, "start", {**data(page.call), **updates})
    assert response.status_code == 400
    page.writer.assert_not_called()
    soup = BeautifulSoup(response.content, "html.parser")
    assert soup.select_one('[role="alert"][autofocus]')
    assert soup.select_one('[data-call-pending="true"]')
    assert soup.select_one('input[name="retry_key"]')["value"] == updates.get(
        "retry_key", str(UUID(int=500))
    )


def test_hidden_profile_injection_is_not_silently_dropped(page):
    call = replace(page.call, contributor_fields=(page.call.contributor_fields[0],))
    form = ProgrammeProposalStartForm(
        {**data(call), "biography": "Secret"}, source=call
    )
    assert not form.is_valid()
    assert "unsupported" in str(form.errors)


@pytest.mark.parametrize(
    "field", ["expected_call_version", "expected_definition_version"]
)
def test_stale_source_retains_original_cursor_without_write(page, field):
    response = request(page, "start", {**data(page.call), field: "999"})
    assert response.status_code == 409
    page.writer.assert_not_called()
    soup = BeautifulSoup(response.content, "html.parser")
    assert soup.select_one(f'input[name="{field}"]')["value"] == "999"
    assert "may already have committed" in soup.get_text()


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (views.commands.ApplicationsProgrammeVersionConflictError, 409),
        (views.commands.ApplicationsProgrammeStateConflictError, 409),
        (views.commands.ApplicationsProgrammeIdempotencyConflictError, 409),
        (ValidationError({"duration": "Use a permitted duration."}), 400),
        (ApplicationsProgrammeAuthorizationDeniedError, 404),
        (DatabaseError, 503),
    ],
)
def test_owner_failure_is_honest_and_never_a_success_redirect(page, error, status):
    page.writer.side_effect = error
    response = request(page, "start", data(page.call))
    assert response.status_code == status
    assert "Location" not in response
    if status in {404, 503}:
        assert page.call.summary.name.encode() not in response.content


@pytest.mark.parametrize("task", ["inventory", "calls", "start"])
def test_entry_denial_precedes_all_private_queries(page, task):
    page.entry.side_effect = ApplicationsProgrammeAuthorizationDeniedError
    assert request(page, task).status_code == 404
    for reader in page.readers.values():
        reader.assert_not_called()


def test_existing_detail_never_uses_new_call_discovery_or_manager(page):
    page.readers["available_programme_calls"].side_effect = AssertionError(
        "No new-call lookup"
    )
    page.entry.side_effect = AssertionError("No new-entry gate on existing history")
    assert request(page, "detail").status_code == 200
    assert (
        page.readers["get_self_programme_proposal_detail"].call_args.kwargs[
            "requested_fields"
        ]
        == views._OWN_PROFILE
    )


def test_invitee_requests_only_minimal_projection_not_profiles(page):
    summary = replace(page.summary, relationship="invited")
    page.auth.return_value = SimpleNamespace(**asdict(summary))
    page.readers["get_self_programme_proposal_detail"].return_value = replace(
        page.detail,
        requested_fields=views._MINIMAL,
        summary=summary,
        own_profile_requirements=None,
        contributor_consent_policy_code=None,
    )
    response = request(page, "detail")
    assert response.status_code == 200
    assert (
        page.readers["get_self_programme_proposal_detail"].call_args.kwargs[
            "requested_fields"
        ]
        == views._MINIMAL
    )
    assert "My proposed public profile" not in response.content.decode()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("aggregate_version", 2),
        ("relationship", "collaborator"),
        ("state", "sealed"),
        ("call_id", UUID(int=99)),
        ("submission_id", UUID(int=99)),
    ],
)
def test_changed_authority_suppresses_prepared_detail(page, field, value):
    original = SimpleNamespace(**asdict(page.summary))
    changed = SimpleNamespace(**{**asdict(page.summary), field: value})
    page.auth.side_effect = [original, original, changed]
    response = request(page, "detail")
    assert response.status_code == 404
    assert page.call.summary.name.encode() not in response.content


def test_inventory_rechecks_each_relationship_before_releasing_cards(page):
    page.auth.side_effect = ApplicationsProgrammeAuthorizationDeniedError
    response = request(page)
    assert response.status_code == 404
    assert page.summary.call_name.encode() not in response.content


def test_closed_planning_preserves_history_but_disallows_creation(page):
    page.entry.return_value.accepts_private_planning_writes = False
    assert request(page).status_code == 200
    response = request(page, "calls")
    assert response.status_code == 200
    assert "creation is closed" in response.content.decode()
    assert request(page, "start").status_code == 404
    page.readers["available_programme_calls"].assert_not_called()


def test_changed_available_source_suppresses_prepared_form(page):
    page.readers["available_programme_calls"].side_effect = [
        (page.call,),
        (page.call,),
        (),
    ]
    response = request(page, "start")
    assert response.status_code == 404
    assert "earlier attempt" in response.content.decode()
    assert page.call.summary.name.encode() not in response.content


@pytest.mark.parametrize("task", ["inventory", "calls", "detail"])
def test_read_tasks_reject_posts_before_queries(page, task):
    assert request(page, task, {}).status_code == 400
    for reader in page.readers.values():
        reader.assert_not_called()


@pytest.mark.parametrize("kind", ["unknown", "duplicate", "oversized", "query"])
def test_transport_fence_precedes_reads(page, kind):
    payload = QueryDict(mutable=True)
    payload.update(data(page.call))
    if kind == "unknown":
        payload["actor_id"] = str(UUID(int=999))
    elif kind == "duplicate":
        payload.appendlist("reason", "Second")
    elif kind == "oversized":
        payload["reason"] = "x" * 6001
    response = request(
        page, "start", payload, query="?actor_id=foreign" if kind == "query" else ""
    )
    assert response.status_code == 400
    page.entry.assert_not_called()


def test_csrf_and_login_are_not_replaced_by_personal_context(page):
    assert request(page, "start", data(page.call), csrf=True).status_code == 403
    incoming = RequestFactory().get("/my/applications/programme/")
    incoming.user = SimpleNamespace(is_authenticated=False)
    response = views.programme_proposals(incoming, page.organization, page.edition)
    assert response.status_code == 302
    page.entry.assert_not_called()


def test_reserved_urls_resolve_but_production_does_not_mount_adapter(page):
    root = f"/my/applications/programme/{page.organization}/{page.edition}/"
    for suffix in (
        "",
        "calls/",
        f"calls/{page.call.summary.call_id}/start/",
        f"{page.summary.proposal_id}/",
    ):
        match = resolve(
            root + suffix, urlconf="maru.applications.programme_proposal_urls"
        )
        assert match.func is views.programme_proposals
        try:
            production = resolve(root + suffix)
        except Resolver404:
            continue
        assert production.func is not views.programme_proposals


@pytest.mark.parametrize("task", ["inventory", "calls", "start", "detail"])
def test_personal_task_connections_use_actual_proposal_viewer(page, monkeypatch, task):
    links = Mock(
        return_value=(
            PersonalProgrammeTaskLink(
                "hosting",
                "My hosting invitations and availability",
                "/synthetic-hosting/",
            ),
        )
    )
    monkeypatch.setattr(views, "personal_programme_task_links", links)
    response = request(page, task)
    assert response.status_code == 200
    assert b"My Programme connections" in response.content
    assert links.call_count == 2
    for invocation in links.call_args_list:
        assert invocation.kwargs["actor_id"] == page.actor
        assert invocation.kwargs["organization_id"] == page.organization
        assert invocation.kwargs["edition_id"] == page.edition
        assert invocation.kwargs["current"] == "proposals"


def test_optional_link_loss_does_not_repeat_start_or_replace_bound_input(
    page, monkeypatch
):
    links = Mock(
        side_effect=[
            (
                PersonalProgrammeTaskLink(
                    "hosting",
                    "My hosting invitations and availability",
                    "/synthetic-hosting/",
                ),
            ),
            (),
        ]
    )
    monkeypatch.setattr(views, "personal_programme_task_links", links)
    page.writer.side_effect = views.commands.ApplicationsProgrammeVersionConflictError
    payload = data(page.call)
    response = request(page, "start", payload)
    assert response.status_code == 409
    page.writer.assert_called_once()
    soup = BeautifulSoup(response.content, "html.parser")
    for key in ("retry_key", "expected_version", "expected_call_version", "reason"):
        field = soup.select_one(f'[name="{key}"]')
        assert field.get("value", field.get_text().removeprefix("\n")) == payload[key]
    assert b"My Programme connections" not in response.content


def test_proposal_authority_loss_after_link_recovery_render_withholds_source(
    page, monkeypatch
):
    links = Mock(
        side_effect=[
            (
                PersonalProgrammeTaskLink(
                    "hosting",
                    "My hosting invitations and availability",
                    "/synthetic-hosting/",
                ),
            ),
            (),
        ]
    )
    monkeypatch.setattr(views, "personal_programme_task_links", links)
    original = views.render_to_string
    renders = 0

    def render(*args, **kwargs):
        nonlocal renders
        renders += 1
        response = original(*args, **kwargs)
        if renders == 2:
            page.entry.side_effect = ApplicationsProgrammeAuthorizationDeniedError
        return response

    monkeypatch.setattr(views, "render_to_string", render)
    response = request(page)
    assert response.status_code == 404
    assert page.call.summary.name.encode() not in response.content
    assert renders == 2
