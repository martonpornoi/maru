"""Real operator native forms, signatures and selection flow through HTTP views."""

from dataclasses import replace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from bs4 import BeautifulSoup

from maru.scheduling import change_notice_views as views
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.change_catalogs import ChangeRecipientPurpose
from maru.scheduling.change_inputs import ChangeRecipientSelection
from maru.scheduling.command_support import SchedulingUnavailableError
from tests.unit.test_operator_notice_selection import (
    operator_world as operator_world,  # noqa: PLC0414
)
from tests.unit.test_programme_change_notice_views import call
from tests.unit.test_programme_change_notice_views import page as page  # noqa: PLC0414
from tests.unit.test_programme_change_notice_views import (
    shell as shell,  # noqa: PLC0414
)
from tests.unit.test_programme_change_notice_views import (
    world as world,  # noqa: PLC0414
)


@pytest.fixture
def operator_page(page, operator_world, monkeypatch):
    monkeypatch.setattr(views, "programme_workspace_links", Mock(return_value=()))
    page.operator = operator_world
    return page


def query(page):
    w = page.operator
    return (
        f"?task=operators&occurrence={w.intent.occurrence_id}"
        f"&operator_kind=room&operator_target={w.room.id}"
    )


def form_data(response, action):
    soup = BeautifulSoup(response.content, "html.parser")
    form = soup.select_one(f'input[name="action"][value="{action}"]').find_parent(
        "form"
    )
    return {node["name"]: node.get("value", "") for node in form.select("input[name]")}


def lookup(page):
    response = call(page, query=query(page))
    assert response.status_code == 200
    data = form_data(response, "operator_lookup")
    data["email"] = "known@example.invalid"
    return call(page, data=data)


def test_actual_labelled_lookup_signed_preview_and_original_native_prepare(
    operator_page,
):
    page = operator_page
    w = page.operator
    first = call(page, query=query(page))
    soup = BeautifulSoup(first.content, "html.parser")
    assert len(soup.select("h1")) == len(soup.select("main")) == 1
    identifiers = [node["id"] for node in soup.select("[id]")]
    assert len(identifiers) == len(set(identifiers))
    assert (
        soup.select_one('select[name="operator_target"] option[selected]').get_text()
        == f"{w.room.venue_label} / {w.room.label} · {w.room.configuration_label}"
    )
    assert b"<one>" not in first.content
    assert b"<ceremony>" not in first.content
    w.lookup.assert_not_called()
    selected = lookup(page)
    assert selected.status_code == 200
    assert b"Synthetic &lt;operator&gt;" in selected.content
    assert b"Selected current occurrence:" in selected.content
    assert b"Selected operator scope:" in selected.content
    assert b"Stage &lt;one&gt;" in selected.content
    assert b"known@example.invalid" not in selected.content
    assert b'name="operator_account_id"' not in selected.content
    token_data = form_data(selected, "operator_preview")
    recipient = ChangeRecipientSelection(
        ChangeRecipientPurpose.ROOM, w.room.id, w.person.account_id
    )
    page.preview.return_value = replace(
        page.world.preview,
        release_id=w.source.release_id,
        occurrence_id=w.intent.occurrence_id,
        pointer_version=2,
        recipient=recipient,
    )
    w.lookup.reset_mock()
    result = call(page, data=token_data)
    assert result.status_code == 200
    assert page.preview.call_args.kwargs == {
        "release_id": w.source.release_id,
        "occurrence_id": w.intent.occurrence_id,
        "recipient": recipient,
    }
    assert page.preview.call_count == 2
    w.lookup.assert_not_called()
    pending = form_data(result, "prepare")
    assert pending["operator_account_id"] == str(w.person.account_id)
    assert pending["expected_pointer_version"] == "2"
    assert pending["snapshot_digest"] == page.world.preview.snapshot_digest
    assert "token" not in pending
    assert "email" not in pending
    for command in page.submit.values():
        command.assert_not_called()


@pytest.mark.parametrize(
    "failure", ["source_move", "person_move", "revoked", "dependency"]
)
def test_after_render_changes_suppress_labels_and_forms(
    operator_page, monkeypatch, failure
):
    page = operator_page
    w = page.operator
    original = views.render_to_string

    def render(*args, **kwargs):
        result = original(*args, **kwargs)
        if not args[1].get("unavailable"):
            if failure == "source_move":
                w.mocks["load_notice_source_selection"].return_value = replace(
                    w.source, pointer_version=3
                )
            elif failure == "person_move":
                w.loader.return_value = replace(
                    w.recipient, display_label="Moved operator"
                )
            elif failure == "revoked":
                w.mocks[
                    "authorize_scheduling_scope"
                ].side_effect = SchedulingAuthorizationDeniedError
            else:
                w.loader.side_effect = SchedulingUnavailableError
        return result

    if failure in {"person_move", "dependency"}:
        first = call(page, query=query(page))
        data = form_data(first, "operator_lookup")
        data["email"] = "known@example.invalid"
    else:
        data = None
    monkeypatch.setattr(views, "render_to_string", render)
    response = call(page, data=data, query="" if data else query(page))
    assert (
        response.status_code
        == {"source_move": 409, "person_move": 409, "revoked": 404, "dependency": 503}[
            failure
        ]
    )
    assert b"Synthetic" not in response.content
    assert b'name="token"' not in response.content
    assert b'name="email"' not in response.content


@pytest.mark.parametrize("empty", ["invalid", "unknown"])
def test_final_recipient_field_required_even_without_successful_selection(
    operator_page, monkeypatch, empty
):
    page = operator_page
    first = call(page, query=query(page))
    data = form_data(first, "operator_lookup")
    data["email"] = "not-an-email" if empty == "invalid" else "unknown@example.invalid"
    page.operator.lookup.return_value = None
    original = views.render_to_string

    def render(*args, **kwargs):
        result = original(*args, **kwargs)
        if not args[1].get("unavailable"):
            page.operator.mocks[
                "authorize_scheduling_scope"
            ].side_effect = SchedulingAuthorizationDeniedError
        return result

    monkeypatch.setattr(views, "render_to_string", render)
    response = call(page, data=data)
    assert response.status_code == 404
    assert b'name="email"' not in response.content
    assert b"No currently eligible" not in response.content


@pytest.mark.parametrize(
    "extra", ["operator_account_id", "email", "release_id", "retry_key"]
)
def test_signed_preview_rejects_account_or_source_overrides(operator_page, extra):
    selected = lookup(operator_page)
    data = form_data(selected, "operator_preview")
    data[extra] = str(uuid4())
    result = call(operator_page, data=data)
    assert result.status_code == 400
    operator_page.preview.assert_not_called()


@pytest.mark.parametrize("task", ["", "hosts", "work"])
def test_operator_get_fields_are_closed_to_the_operator_task(operator_page, task):
    response = call(operator_page, query=f"?task={task}&operator_kind=room")
    assert response.status_code == 400
    operator_page.operator.lookup.assert_not_called()


def test_personal_page_cannot_offer_lookup_or_signed_operator_preview(operator_page):
    page = operator_page
    assert call(page, query=query(page), personal=True).status_code == 400
    assert (
        call(page, data={"action": "operator_lookup"}, personal=True).status_code == 400
    )
    assert (
        call(
            page, data={"action": "operator_preview", "token": "x"}, personal=True
        ).status_code
        == 400
    )
    page.operator.lookup.assert_not_called()


def test_unknown_operator_is_truthful_empty_without_replaying_lookup_form(
    operator_page,
):
    page = operator_page
    page.operator.lookup.return_value = None
    response = lookup(page)
    assert response.status_code == 200
    assert b"No currently eligible operator" in response.content
    assert b'name="token"' not in response.content
    assert b'name="email"' not in response.content
    page.preview.assert_not_called()
