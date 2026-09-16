"""Real file task forms/templates and late attachment checks over owner seams."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from bs4 import BeautifulSoup
from django.db import DatabaseError
from django.http import QueryDict
from django.test import RequestFactory
from django.urls import Resolver404, resolve

from maru.applications import programme_file_task_views as tasks
from maru.applications import programme_file_views as views
from maru.applications.programme_file_forms import _decode, _encode
from maru.applications.programme_file_queries import ProgrammeFileProjection
from maru.applications.programme_reference_sources import (
    ProgrammeAnswerReferenceIntent,
    ProgrammeAnswerReferenceRequest,
)
from tests.unit import test_application_programme_person_references as contracts

page, shell, work = contracts.page, contracts.shell, contracts.work


@pytest.fixture
def world(work, monkeypatch):
    question = replace(work.answer.question, field_type="safe_file", reference_kind="")
    detail = replace(
        work.source_detail, answers=(replace(work.answer, question=question),)
    )
    source = ProgrammeAnswerReferenceRequest(
        work.actor,
        work.organization,
        work.edition,
        work.context.summary.proposal_id,
        question.question_id,
        uuid4(),
        "programme-file-upload",
    )
    intent = ProgrammeAnswerReferenceIntent(
        work.context.summary.aggregate_version,
        work.context.call_version,
        work.context.definition_version,
        uuid4(),
    )
    admitted = (work.context, detail)
    admit = Mock(return_value=admitted)
    monkeypatch.setattr(tasks, "_source", admit)
    monkeypatch.setattr(tasks, "_question", Mock())
    outcome = Mock(return_value=None)
    monkeypatch.setattr(tasks.commands, "get_programme_file_upload_result", outcome)
    projection = ProgrammeFileProjection(
        source=admitted,
        question_label=question.label,
        present=True,
        size_bytes=14,
        data=None,
    )
    reader = Mock(
        side_effect=lambda **kw: replace(
            projection, data=b"Synthetic PDF!" if kw["include_bytes"] else None
        )
    )
    monkeypatch.setattr(views, "get_self_programme_file", reader)
    return SimpleNamespace(
        source=source,
        intent=intent,
        work=work,
        admit=admit,
        outcome=outcome,
        reader=reader,
        projection=projection,
    )


def incoming(
    world,
    *,
    task="upload",
    payload=None,
    query="",
    viewer=False,
    download=False,
    revision_id=None,
    csrf=False,
):
    scope = world.source
    path = (
        f"/my/applications/programme/{scope.organization_id}/{scope.edition_id}/"
        f"{scope.proposal_id}/work/answer/{scope.question_id}/file/"
    )
    if payload is None:
        request = RequestFactory().get(path + query)
    else:
        data = QueryDict(mutable=True)
        for name, value in payload.items():
            data.setlist(name, value if isinstance(value, list) else [value])
        request = RequestFactory().post(
            path + query,
            data.urlencode(),
            content_type="application/x-www-form-urlencoded",
        )
    request.user = SimpleNamespace(
        pk=scope.actor_id, is_authenticated=True, is_staff=False
    )
    request._dont_enforce_csrf_checks = not csrf
    args = (
        request,
        scope.organization_id,
        scope.edition_id,
        scope.proposal_id,
        scope.question_id,
    )
    return (
        views.programme_file_view(*args, download=download, revision_id=revision_id)
        if viewer
        else tasks.programme_file_task(*args, task=task)
    )


def soup(response):
    return BeautifulSoup(response.content, "html.parser")


def test_fresh_upload_has_original_proof_native_control_guidance_and_no_receipt(world):
    response = incoming(world)
    assert response.status_code == 200
    doc = soup(response)
    root = doc.select_one("[data-file-upload]")
    assert "connect-src 'self'" in response["Content-Security-Policy"]
    assert "default-src 'none'" in response["Content-Security-Policy"]
    intent = _decode(world.source, root["data-file-intent"], purpose="upload")
    assert intent.expected_version == world.intent.expected_version
    assert root["data-file-recovery"] == "false"
    assert doc.select_one('input[type="file"]')["accept"] == "application/pdf,.pdf"
    assert doc.select_one('input[name="csrfmiddlewaretoken"]')
    assert "64 MiB" in doc.get_text()
    assert "10 MiB" in doc.get_text()
    assert "JavaScript" in doc.select_one("noscript").get_text()
    assert "My current answer" not in doc.get_text()
    world.outcome.assert_not_called()
    assert world.admit.call_count >= 3


def test_retained_upload_is_only_recovery_not_new_edit_admission(world):
    token = _encode(world.source, world.intent, purpose="upload")
    world.admit.side_effect = tasks.Denied
    response = incoming(world, query="?intent=" + token)
    assert response.status_code == 200
    doc = soup(response)
    assert doc.select_one("[data-file-upload]")["data-file-recovery"] == "true"
    assert not doc.select_one('input[type="file"]')
    assert doc.select_one("[data-file-check]")
    assert not doc.select_one("[data-file-send]")
    world.admit.assert_not_called()
    assert world.outcome.call_count >= 2
    assert world.outcome.call_args.kwargs["intent"] == world.intent


@pytest.mark.parametrize(
    "query",
    ["?intent=", "?intent=a&intent=b", "?receipt=arbitrary", "?intent=tampered"],
)
def test_bad_upload_query_is_closed(world, query):
    assert incoming(world, query=query).status_code in {400, 404}
    world.admit.assert_not_called()
    world.outcome.assert_not_called()


def test_upload_page_does_not_accept_form_post(world):
    assert incoming(world, payload={}).status_code == 400
    world.admit.assert_not_called()


def test_clear_is_explicit_original_confirmation_not_file_deletion(world):
    response = incoming(world, task="clear")
    assert response.status_code == 200
    assert "connect-src" not in response["Content-Security-Policy"]
    doc = soup(response)
    assert not doc.select_one('input[name="confirm"]').has_attr("checked")
    token = doc.select_one('input[name="token"]')["value"]
    original = _decode(world.source, token, purpose="clear")
    response = incoming(world, task="clear", payload={"token": token, "confirm": "on"})
    assert response.status_code == 302
    command = world.work.writers["append_programme_proposal_answer"]
    values = command.call_args.kwargs
    assert values["value"] is None
    assert values["expected_version"] == original.expected_version
    assert values["retry_key"] == original.retry_key
    assert values["question_id"] == world.source.question_id
    assert values["reason"] == "Clear this supporting-file answer."
    assert "does not delete" in doc.get_text()


@pytest.mark.parametrize(
    "payload",
    [{}, {"token": "x"}, {"token": ["x", "y"], "confirm": "on"}, {"receipt": "other"}],
)
def test_clear_rejects_missing_confirmation_duplicate_or_extra_values(world, payload):
    assert incoming(world, task="clear", payload=payload).status_code == 400
    world.work.writers["append_programme_proposal_answer"].assert_not_called()


def test_clear_csrf_protection_before_command(world):
    token = _encode(world.source, world.intent, purpose="clear")
    assert (
        incoming(
            world, task="clear", payload={"token": token, "confirm": "on"}, csrf=True
        ).status_code
        == 403
    )
    world.work.writers["append_programme_proposal_answer"].assert_not_called()


@pytest.mark.parametrize(
    ("error", "status"), [(tasks._CONFLICTS[0], 409), (DatabaseError, 503)]
)
def test_uncertain_clear_keeps_original_token_and_confirmation(world, error, status):
    token = _encode(world.source, world.intent, purpose="clear")
    world.work.writers["append_programme_proposal_answer"].side_effect = error
    response = incoming(world, task="clear", payload={"token": token, "confirm": "on"})
    assert response.status_code == status
    doc = soup(response)
    assert doc.select_one('input[name="token"]')["value"] == token
    assert doc.select_one('input[name="confirm"]').has_attr("checked")
    assert doc.select_one('[data-call-pending="true"]')


def test_late_personal_authority_change_withholds_whole_page(world):
    world.admit.side_effect = [world.admit.return_value, tasks.Denied()]
    response = incoming(world)
    assert response.status_code == 404
    assert b"data-file-intent" not in response.content


@pytest.mark.parametrize("revision", [None, "sealed"])
def test_metadata_never_loads_bytes_and_uses_exact_seal(world, revision):
    revision_id = uuid4() if revision else None
    response = incoming(world, viewer=True, revision_id=revision_id)
    assert response.status_code == 200
    assert "Download supporting PDF as an attachment" in soup(response).get_text()
    assert all(not call.kwargs["include_bytes"] for call in world.reader.call_args_list)
    assert world.reader.call_args.kwargs["revision_id"] == revision_id


def test_download_prepares_fixed_attachment_then_rechecks_without_bytes(world):
    response = incoming(world, viewer=True, download=True)
    assert response.status_code == 200
    assert response.content == b"Synthetic PDF!"
    assert response["Content-Type"] == "application/pdf"
    assert (
        response["Content-Disposition"]
        == 'attachment; filename="programme-supporting-file.pdf"'
    )
    assert response["Content-Length"] == str(len(response.content))
    assert "no-store" in response["Cache-Control"]
    assert response["X-Content-Type-Options"] == "nosniff"
    assert [call.kwargs["include_bytes"] for call in world.reader.call_args_list] == [
        True,
        False,
    ]


@pytest.mark.parametrize("late", ["changed", "denied", "unavailable"])
def test_late_attachment_failure_withholds_all_bytes(world, late):
    second = (
        replace(world.projection, source="changed")
        if late == "changed"
        else (views.Denied() if late == "denied" else DatabaseError())
    )
    world.reader.side_effect = [replace(world.projection, data=b"PRIVATE PDF"), second]
    response = incoming(world, viewer=True, download=True)
    assert response.status_code in {404, 503}
    assert b"PRIVATE PDF" not in response.content
    assert not response.has_header("Content-Disposition")


def test_empty_answer_has_no_download_link(world):
    world.reader.side_effect = None
    world.reader.return_value = replace(
        world.projection, present=False, size_bytes=None
    )
    response = incoming(world, viewer=True)
    assert response.status_code == 200
    assert not soup(response).select_one('a[href$="download/"]')
    assert incoming(world, viewer=True, download=True).status_code == 503


def test_file_routes_remain_reserved_not_production(world):
    scope = world.source
    path = (
        f"/my/applications/programme/{scope.organization_id}/{scope.edition_id}/"
        f"{scope.proposal_id}/work/answer/{scope.question_id}/file/intake/"
    )
    assert (
        resolve(path, urlconf="maru.applications.programme_proposal_urls").url_name
        == "my-programme-file-intake"
    )
    with pytest.raises(Resolver404):
        resolve(path)
