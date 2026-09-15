"""Real reference HTTP, forms and templates over audited database-free owner seams."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID

import pytest
from bs4 import BeautifulSoup
from django.db import DatabaseError
from django.http import QueryDict
from django.test import RequestFactory
from django.urls import Resolver404, resolve

from maru.applications import programme_person_reference_views as views
from maru.applications import programme_person_references as refs
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from maru.applications.programme_commands import (
    ApplicationsProgrammeVersionConflictError,
)
from tests.unit import test_application_programme_person_references as contracts

page, shell, work, world = (
    contracts.page,
    contracts.shell,
    contracts.work,
    contracts.world,
)


@pytest.fixture(autouse=True)
def owner_queries_without_database(monkeypatch):
    for name in (
        "prepare_programme_person_selection",
        "read_programme_person_selection",
        "get_self_programme_person_reference",
    ):
        monkeypatch.setattr(refs, name, getattr(refs, name).__wrapped__)


def incoming(world, payload=None, *, edit=True, query="", csrf=False, revision_id=None):
    root = (
        f"/my/applications/programme/{world.organization}/{world.edition}/"
        f"{world.context.summary.proposal_id}/"
    )
    path = root + f"work/answer/{world.answer.question.question_id}/person/"
    factory = RequestFactory()
    if payload is None:
        request = factory.get(path + query)
    else:
        values = QueryDict(mutable=True)
        for key, value in payload.items():
            values.setlist(key, value if isinstance(value, list) else [value])
        request = factory.post(
            path + query,
            values.urlencode(),
            content_type="application/x-www-form-urlencoded",
        )
    request.user = SimpleNamespace(
        pk=world.actor, is_authenticated=True, is_staff=False
    )
    request._dont_enforce_csrf_checks = not csrf
    return views.programme_person_reference(
        request,
        world.organization,
        world.edition,
        world.context.summary.proposal_id,
        world.answer.question.question_id,
        edit=edit,
        revision_id=revision_id,
    )


def evidence(world, **changes):
    return {
        "expected_version": str(world.intent.expected_version),
        "expected_call_version": str(world.intent.expected_call_version),
        "expected_definition_version": str(world.intent.expected_definition_version),
        "retry_key": str(world.intent.retry_key),
        "phase": "prepare",
        "mode": "select",
        "email": "known@maru.invalid",
        "reason": "",
        "confirm": "",
        "token": "",
    } | changes


def selected(world):
    response = incoming(world, evidence(world))
    assert response.status_code == 200, [
        node.get_text()
        for node in BeautifulSoup(response.content, "html.parser").select(
            '[role="alert"]'
        )
    ]
    return BeautifulSoup(response.content, "html.parser").select_one(
        'input[name="token"]'
    )["value"]


def confirmation(world, token, **changes):
    return (
        evidence(
            world,
            phase="confirm",
            token=token,
            email="",
            reason="Mention the known person",
            confirm="on",
        )
        | changes
    )


def test_lookup_is_separate_from_confirmation_and_uses_one_real_accessible_form(world):
    response = incoming(world)
    assert response.status_code == 200
    soup = BeautifulSoup(response.content, "html.parser")
    assert len(soup.select("h1")) == len(soup.select("main")) == 1
    ids = [node["id"] for node in soup.select("[id]")]
    assert len(ids) == len(set(ids))
    assert "no-store" in response["Cache-Control"]
    token = selected(world)
    assert token
    world.writers["append_programme_proposal_answer"].assert_not_called()


def test_confirmation_dispatches_only_original_person_and_source_versions(world):
    token = selected(world)
    world.person.side_effect = AssertionError("No repeat email discovery")
    response = incoming(world, confirmation(world, token))
    assert response.status_code == 302
    call = world.writers["append_programme_proposal_answer"].call_args.kwargs
    assert call["value"] == str(UUID(int=40))
    assert call["retry_key"] == world.intent.retry_key
    assert call["expected_call_version"] == world.intent.expected_call_version
    assert (
        call["expected_definition_version"] == world.intent.expected_definition_version
    )
    assert "email" not in call


@pytest.mark.parametrize("raw", ["False", "false", "on", "True", ""])
def test_new_selection_never_preselects_confirmation_from_hidden_or_prior_input(
    world, raw
):
    response = incoming(world, evidence(world, confirm=raw))
    assert response.status_code == 200
    soup = BeautifulSoup(response.content, "html.parser")
    assert not soup.select_one('input[name="confirm"]').has_attr("checked")
    world.writers["append_programme_proposal_answer"].assert_not_called()


def test_clear_requires_two_deliberate_posts_and_writes_none(world):
    response = incoming(world, evidence(world, mode="clear", email=""))
    assert response.status_code == 200
    token = BeautifulSoup(response.content, "html.parser").select_one(
        'input[name="token"]'
    )["value"]
    world.writers["append_programme_proposal_answer"].assert_not_called()
    result = incoming(world, confirmation(world, token, mode="clear"))
    assert result.status_code == 302
    assert (
        world.writers["append_programme_proposal_answer"].call_args.kwargs["value"]
        is None
    )
    world.person.assert_not_called()
    world.labels.assert_not_called()


@pytest.mark.parametrize("changes", [{"confirm": ""}, {"reason": ""}])
def test_invalid_confirmation_preserves_original_proof_and_selected_label(
    world, changes
):
    token = selected(world)
    response = incoming(world, confirmation(world, token, **changes))
    assert response.status_code == 400
    soup = BeautifulSoup(response.content, "html.parser")
    assert soup.select_one('input[name="token"]')["value"] == token
    assert "Synthetic referenced person" in soup.get_text()
    world.writers["append_programme_proposal_answer"].assert_not_called()


def test_changed_version_is_not_rebased_before_canonical_receipt_recovery(world):
    token = selected(world)
    world.context = replace(
        world.context, summary=replace(world.context.summary, aggregate_version=99)
    )
    response = incoming(world, confirmation(world, token))
    assert response.status_code == 302
    assert (
        world.writers["append_programme_proposal_answer"].call_args.kwargs[
            "expected_version"
        ]
        == world.intent.expected_version
    )


def test_stale_fresh_writer_retains_reason_confirmation_and_original_proof(world):
    token = selected(world)
    world.writers[
        "append_programme_proposal_answer"
    ].side_effect = ApplicationsProgrammeVersionConflictError
    response = incoming(world, confirmation(world, token))
    assert response.status_code == 409
    soup = BeautifulSoup(response.content, "html.parser")
    assert soup.select_one('input[name="token"]')["value"] == token
    assert soup.select_one('input[name="confirm"]').has_attr("checked")
    assert "Mention the known person" in soup.get_text()
    world.writers["append_programme_proposal_answer"].assert_called_once()


def test_closed_get_has_readable_conflict_instead_of_an_unhandled_form_error(world):
    world.context = replace(world.context, planning=False)
    assert incoming(world).status_code == 409
    world.person.assert_not_called()


def test_response_failure_after_owner_success_never_redispatches_the_writer(
    world, monkeypatch
):
    token = selected(world)
    secure = views._secure

    def response_failure(response, *args):
        if response.status_code == 302:
            raise DatabaseError("Synthetic failure after the owner returned success")
        return secure(response, *args)

    monkeypatch.setattr(views, "_secure", response_failure)
    response = incoming(world, confirmation(world, token))
    assert response.status_code == 503
    assert b"may have committed" in response.content
    world.writers["append_programme_proposal_answer"].assert_called_once()


@pytest.mark.parametrize(
    "payload",
    [
        {"account_id": str(UUID(int=99))},
        {"phase": ["prepare", "confirm"]},
        {"email": ["known@maru.invalid", "other@maru.invalid"]},
        {"reason": "a" * 6001},
        {"phase": "unknown"},
    ],
)
def test_closed_post_transport_prevents_lookup_and_writes(world, payload):
    assert incoming(world, evidence(world, **payload)).status_code == 400
    world.person.assert_not_called()
    world.writers["append_programme_proposal_answer"].assert_not_called()


def test_real_csrf_and_query_override_are_refused_before_lookup(world):
    assert incoming(world, evidence(world), csrf=True).status_code == 403
    assert incoming(world, query="?account_id=anything").status_code == 400
    world.person.assert_not_called()


@pytest.mark.parametrize("frozen", [False, True])
def test_current_and_frozen_viewers_render_minimal_label_without_raw_person_id(
    world, frozen
):
    response = incoming(
        world,
        edit=False,
        revision_id=world.frozen.revision.revision_id if frozen else None,
    )
    assert response.status_code == 200
    text = BeautifulSoup(response.content, "html.parser").get_text()
    assert "Synthetic referenced person" in text
    assert "not the contributor names frozen" in text
    assert "known@" not in text


def test_label_loss_during_real_render_withholds_all_original_bytes(world, monkeypatch):
    original = views._html.__globals__["render_to_string"]

    def render(*args, **kwargs):
        content = original(*args, **kwargs)
        world.labels.return_value = {}
        return content

    monkeypatch.setitem(views._html.__globals__, "render_to_string", render)
    response = incoming(world, edit=False)
    assert response.status_code == 404
    assert b"Synthetic referenced person" not in response.content


@pytest.mark.parametrize(("error", "status"), [(Denied, 404), (DatabaseError, 503)])
def test_dependency_and_authority_failures_never_disclose_person(world, error, status):
    world.write_auth.side_effect = error
    response = incoming(world)
    assert response.status_code == status
    world.person.assert_not_called()


def test_registered_routes_remain_dormant(world):
    path = (
        f"/my/applications/programme/{world.organization}/{world.edition}/"
        f"{world.context.summary.proposal_id}/references/person/"
        f"{world.answer.question.question_id}/"
    )
    assert (
        resolve(path, urlconf="maru.applications.programme_proposal_urls").url_name
        == "my-programme-person-reference"
    )
    with pytest.raises(Resolver404):
        resolve(path)
