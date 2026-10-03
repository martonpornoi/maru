"""Strict actual forms and shared-shell HTML, separate from native/browser proof."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
from bs4 import BeautifulSoup
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import QueryDict
from django.test import RequestFactory
from django.urls import resolve

from maru.authorization.services import AuthorizationDenied
from maru.events import programme_stop_views as views
from maru.events.programme_stop_forms import ProgrammeStopForm
from maru.events.programme_stop_inventory import ProgrammeStopCollectionCount
from maru.events.programme_stop_receipt_queries import ProgrammeStopReceiptDetail
from tests.unit.test_programme_stop_composition import (
    preview as preview,  # noqa: PLC0414
)


@pytest.fixture
def page(monkeypatch, preview):
    preview = replace(
        preview,
        scheduling=replace(
            preview.scheduling,
            inventory=replace(
                preview.scheduling.inventory,
                collections=(
                    ProgrammeStopCollectionCount(
                        "schedulingcandidate", 3, (("draft", 3),)
                    ),
                ),
            ),
        ),
    )
    auth, read, stop = (
        Mock(),
        Mock(return_value=preview),
        Mock(return_value=SimpleNamespace(receipt_id=uuid4())),
    )
    receipt = ProgrammeStopReceiptDetail(
        uuid4(),
        preview.organization_id,
        preview.edition_id,
        "Own synthetic reason",
        4,
        2,
        release_withdrawn=True,
    )
    history = Mock(return_value=receipt)
    monkeypatch.setattr(views, "require_programme_stop_preflight", auth)
    monkeypatch.setattr(views, "load_programme_stop_preview", read)
    monkeypatch.setattr(views, "stop_programme", stop)
    monkeypatch.setattr(views, "load_programme_stop_receipt", history)
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
        yield SimpleNamespace(
            preview=preview,
            auth=auth,
            read=read,
            stop=stop,
            history=history,
            receipt=receipt,
        )


def data():
    return {
        "expected_aggregate_version": "3",
        "expected_lifecycle_version": "1",
        "preview_fingerprint": "a" * 64,
        "idempotency_key": str(uuid4()),
        "reason": "Synthetic stop reason.",
        "confirm": "on",
    }


def call(page, *, submitted=None, query="", anonymous=False, csrf=False, receipt=False):
    preview = page.preview
    path = f"/admin/programme/stop/{preview.organization_id}/{preview.edition_id}/"
    factory = RequestFactory()
    if submitted is None:
        request = factory.get(path + query)
    else:
        encoded = (
            submitted
            if isinstance(submitted, QueryDict)
            else QueryDict("", mutable=True)
        )
        if not isinstance(submitted, QueryDict):
            encoded.update(submitted)
        request = factory.post(
            path + query,
            encoded.urlencode(),
            content_type="application/x-www-form-urlencoded",
        )
    request.user = (
        AnonymousUser()
        if anonymous
        else SimpleNamespace(
            pk=preview.actor_id,
            is_authenticated=True,
            is_active=True,
            is_staff=False,
            is_superuser=False,
        )
    )
    request._dont_enforce_csrf_checks = not csrf
    return views.programme_stop(
        request,
        preview.organization_id,
        preview.edition_id,
        page.receipt.receipt_id if receipt else None,
    )


def test_actual_preview_html_binds_complete_original_identity_and_counts(page):
    response = call(page)
    assert response.status_code == 200
    html = BeautifulSoup(response.content, "html.parser")
    assert len(html.select("h1")) == 1
    assert "schedulingcandidate: 3; draft 3" in html.get_text()
    assert (
        html.select_one('input[name="preview_fingerprint"]')["value"]
        == page.preview.fingerprint
    )
    assert html.select_one('input[name="confirm"][required]')
    assert "private, no-store" in response["Cache-Control"]
    assert response["Referrer-Policy"] == "same-origin"
    page.stop.assert_not_called()


def test_active_release_without_actual_withdrawal_authority_offers_no_confirmation(
    page,
):
    page.read.return_value = replace(
        page.preview,
        scheduling=replace(
            page.preview.scheduling,
            active_release_id=uuid4(),
            pointer_version=4,
            withdrawal_authorized=False,
        ),
    )
    html = BeautifulSoup(call(page).content, "html.parser")
    assert not html.select('.programme-workbench button[type="submit"]')
    assert "current withdrawal authority" in html.get_text()


def test_post_uses_only_actual_actor_route_and_original_input_not_a_new_preview(page):
    original = data()
    response = call(page, submitted=original)
    assert response.status_code == 302
    sent = page.stop.call_args.kwargs
    assert (sent["actor_id"], sent["organization_id"], sent["edition_id"]) == (
        page.preview.actor_id,
        page.preview.organization_id,
        page.preview.edition_id,
    )
    assert sent["details"].preview_fingerprint == original["preview_fingerprint"]
    assert sent["details"].expected_aggregate_version == 3
    assert sent["idempotency_key"] == UUID(original["idempotency_key"])
    page.read.assert_not_called()


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (ValidationError("PRIVATE", code="programme_stop_preview_conflict"), 409),
        (ValidationError("PRIVATE", code="programme_stop_source"), 503),
        (DatabaseError("PRIVATE"), 503),
    ],
)
def test_uncertain_or_stale_result_preserves_original_form_and_key(page, error, status):
    original = data()
    page.stop.side_effect = error
    response = call(page, submitted=original)
    assert response.status_code == status
    assert response["Referrer-Policy"] == "same-origin"
    html = BeautifulSoup(response.content, "html.parser")
    for key in (
        "idempotency_key",
        "preview_fingerprint",
        "expected_aggregate_version",
        "reason",
    ):
        assert html.select_one(f'input[name="{key}"]')["value"] == original[key]
    assert "PRIVATE" not in html.get_text()
    page.read.assert_not_called()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("expected_aggregate_version", "0"),
        ("expected_aggregate_version", "2147483648"),
        ("expected_aggregate_version", "1.0"),
        ("expected_aggregate_version", "abc1"),
        ("expected_lifecycle_version", "-1"),
        ("expected_lifecycle_version", "01"),
        ("expected_lifecycle_version", " 1"),
        ("preview_fingerprint", "a" * 63),
        ("preview_fingerprint", "A" * 64),
        ("idempotency_key", str(UUID(int=0))),
        ("reason", ""),
        ("reason", "x" * 241),
        ("reason", "private\ntext"),
        ("confirm", ""),
    ],
)
def test_strict_original_input_refuses_without_a_command(page, field, value):
    values = {**data(), field: value}
    assert not ProgrammeStopForm(values).is_valid()
    assert call(page, submitted=values).status_code == 400
    page.stop.assert_not_called()


@pytest.mark.parametrize(
    "field", ["actor_id", "organization_id", "edition_id", "unexpected"]
)
def test_posted_scope_and_extra_fields_are_not_authority(page, field):
    assert call(page, submitted={**data(), field: str(uuid4())}).status_code == 400
    page.stop.assert_not_called()


def test_duplicate_fields_cannot_change_original_intent(page):
    values = QueryDict("", mutable=True)
    values.update(data())
    values.appendlist("reason", "replacement")
    assert call(page, submitted=values).status_code == 400
    page.stop.assert_not_called()


def test_anonymous_and_csrf_fail_before_private_reads_or_commands(page):
    assert call(page, anonymous=True).status_code == 302
    assert call(page, submitted=data(), csrf=True).status_code == 403
    page.auth.assert_not_called()
    page.read.assert_not_called()
    page.stop.assert_not_called()


def test_denial_is_non_disclosing_and_precedes_input(page):
    page.auth.side_effect = AuthorizationDenied("PRIVATE", reason_code="denied")
    response = call(page, submitted={"unexpected": "PRIVATE"})
    assert response.status_code == 404
    assert b"PRIVATE" not in response.content
    page.stop.assert_not_called()


def test_terminal_context_and_original_receipt_offer_no_operational_controls(page):
    page.read.side_effect = ValidationError(
        "stopped", code="programme_stop_lifecycle_conflict"
    )
    for receipt in (False, True):
        html = BeautifulSoup(call(page, receipt=receipt).content, "html.parser")
        assert "Programme is stopped" in html.get_text()
        assert not html.select('.programme-workbench button[type="submit"]')
    assert page.history.call_args.kwargs["actor_id"] == page.preview.actor_id


def test_reserved_owner_route_is_not_a_production_handler(page):
    path = (
        f"/admin/programme/stop/{page.preview.organization_id}/"
        f"{page.preview.edition_id}/"
    )
    assert (
        resolve(path, urlconf="maru.events.programme_stop_urls").func
        == views.programme_stop
    )
    assert resolve(path, urlconf="maru.urls").func != views.programme_stop
