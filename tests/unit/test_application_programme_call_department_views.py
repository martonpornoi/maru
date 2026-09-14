"""Real dormant forms and HTML against synthetic exact-owner boundaries."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from bs4 import BeautifulSoup
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import QueryDict
from django.test import RequestFactory
from django.urls import Resolver404, resolve

from maru.applications import programme_call_department_views as views
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError,
)
from maru.workforce.queries import CurrentDepartmentChoiceReference
from tests.unit.test_application_programme_call_editor import _evidence
from tests.unit.test_application_programme_call_views import page, shell

__all__ = ["page", "shell"]


@pytest.fixture
def transfer(page, monkeypatch):
    destination = UUID(int=990)
    listing = Mock(
        return_value=(
            CurrentDepartmentChoiceReference(
                page.department, "programme", "Programme Department"
            ),
            CurrentDepartmentChoiceReference(
                destination, "stage", "Programme Department"
            ),
        )
    )
    writer = Mock(return_value=SimpleNamespace(target_id=page.source.summary.call_id))
    monkeypatch.setattr(
        views.departments, "list_managed_programme_call_departments", listing
    )
    monkeypatch.setattr(views.commands, "reassign_programme_call", writer)
    return SimpleNamespace(
        page=page, destination=destination, listing=listing, writer=writer
    )


def _request(
    transfer, data=None, *, chooser=False, csrf=False, query="", anonymous=False
):
    page = transfer.page
    path = (
        f"/admin/applications/programme-calls/{page.organization}/"
        f"{page.edition}/{page.department}/"
    )
    path += "departments/" if chooser else f"{page.source.summary.call_id}/reassign/"
    if data is None:
        request = RequestFactory().get(path + query)
    else:
        if not isinstance(data, QueryDict):
            encoded = QueryDict(mutable=True)
            encoded.update(data)
            data = encoded
        request = RequestFactory().post(
            path + query,
            data=data.urlencode(),
            content_type="application/x-www-form-urlencoded",
        )
    request.user = SimpleNamespace(
        pk=page.actor,
        is_authenticated=not anonymous,
        is_active=True,
        is_staff=False,
        is_superuser=False,
    )
    request._dont_enforce_csrf_checks = not csrf
    return views.programme_call_departments(
        request,
        page.organization,
        page.edition,
        page.department,
        None if chooser else page.source.summary.call_id,
    )


def _data(transfer):
    return {
        **_evidence(),
        "destination_department_id": str(transfer.destination),
        "confirm": "on",
    }


def test_chooser_names_duplicate_labels_with_codes_and_no_writes(transfer):
    response = _request(transfer, chooser=True)
    assert response.status_code == 200
    soup = BeautifulSoup(response.content, "html.parser")
    assert len(soup.select("h1")) == len(soup.select("main")) == 1
    assert "Programme Department (stage)" in soup.get_text()
    assert "Programme Department (programme)" in soup.get_text()
    assert soup.select_one('a[aria-current="true"]')
    assert not soup.select("form[data-call-command]")
    transfer.writer.assert_not_called()
    transfer.page.readers[
        "get_managed_programme_call_configuration"
    ].assert_not_called()
    assert "private, no-store" in response["Cache-Control"]
    assert "nonce-" in response["Content-Security-Policy"]


def test_transfer_has_labelled_destination_original_evidence_and_confirmation(transfer):
    response = _request(transfer)
    assert response.status_code == 200
    soup = BeautifulSoup(response.content, "html.parser")
    form = soup.select_one("form[data-call-command]")
    for field in form.select("input:not([type=hidden]),textarea,select"):
        assert form.select_one(f'label[for="{field["id"]}"]')
    assert form.select_one('[name="expected_version"]')["value"] == "12"
    assert form.select_one('[name="retry_key"]')["value"]
    assert form.select_one('[name="csrfmiddlewaretoken"]')
    options = form.select('select[name="destination_department_id"] option')
    assert [option["value"] for option in options] == ["", str(transfer.destination)]
    assert "retained history will not be rewritten" in form.get_text()
    transfer.writer.assert_not_called()


def test_success_uses_only_dedicated_dual_scope_writer_and_destination_redirect(
    transfer,
):
    data = _data(transfer)
    response = _request(transfer, data)
    assert response.status_code == 302
    assert (
        f"/{transfer.destination}/{transfer.page.source.summary.call_id}/overview/"
        in response["Location"]
    )
    kwargs = transfer.writer.call_args.kwargs
    assert kwargs["source_department_id"] == transfer.page.department
    assert kwargs["destination_department_id"] == transfer.destination
    assert kwargs["organization_id"] == transfer.page.organization
    assert kwargs["edition_id"] == transfer.page.edition
    assert kwargs["actor_id"] == transfer.page.actor
    assert kwargs["expected_version"] == 12
    assert kwargs["retry_key"] == UUID(data["retry_key"])
    assert kwargs["source_channel"] == "programme-call-workspace"
    for writer in transfer.page.writers.values():
        writer.assert_not_called()


@pytest.mark.parametrize(
    "mutation",
    [
        "same",
        "foreign",
        "missing",
        "unconfirmed",
        "bad-version",
        "bad-retry",
        "no-reason",
    ],
)
def test_invalid_choice_or_evidence_retains_bound_form_without_dispatch(
    transfer, mutation
):
    data = _data(transfer)
    if mutation in {"same", "foreign", "missing"}:
        data["destination_department_id"] = {
            "same": str(transfer.page.department),
            "foreign": str(UUID(int=999)),
            "missing": "",
        }[mutation]
    else:
        data[
            {
                "unconfirmed": "confirm",
                "bad-version": "expected_version",
                "bad-retry": "retry_key",
                "no-reason": "reason",
            }[mutation]
        ] = ""
    response = _request(transfer, data)
    assert response.status_code == 400
    soup = BeautifulSoup(response.content, "html.parser")
    assert soup.select_one('[role="alert"][autofocus]')
    assert soup.select_one('form[data-call-pending="true"]')
    transfer.writer.assert_not_called()


@pytest.mark.parametrize("conflict", ["cursor", "version", "state", "retry"])
def test_stale_intent_retains_original_input_without_claiming_no_previous_commit(
    transfer, conflict
):
    data = _data(transfer)
    if conflict == "cursor":
        data["expected_version"] = "11"
    else:
        commands = views.commands
        transfer.writer.side_effect = {
            "version": commands.ApplicationsProgrammeVersionConflictError,
            "state": commands.ApplicationsProgrammeStateConflictError,
            "retry": commands.ApplicationsProgrammeIdempotencyConflictError,
        }[conflict]
    response = _request(transfer, data)
    assert response.status_code == 409
    soup = BeautifulSoup(response.content, "html.parser")
    assert soup.select_one('[name="retry_key"]')["value"] == data["retry_key"]
    assert soup.select_one('[name="expected_version"]')["value"] == str(
        data["expected_version"]
    )
    assert soup.select_one("option[selected]")["value"] == str(transfer.destination)
    assert "may already have succeeded" in soup.get_text()
    if conflict == "cursor":
        transfer.writer.assert_not_called()


@pytest.mark.parametrize("state", ["active", "retired", "planning-closed"])
def test_read_only_does_not_load_other_department_names_or_allow_transfer(
    transfer, state
):
    if state == "planning-closed":
        transfer.page.auth.return_value.accepts_private_planning_writes = False
    else:
        transfer.page.readers[
            "get_managed_programme_call_configuration"
        ].return_value = replace(
            transfer.page.source,
            summary=replace(transfer.page.source.summary, status=state),
        )
    response = _request(transfer)
    assert response.status_code == 200
    assert "read-only" in response.content.decode()
    assert b"data-call-command" not in response.content
    assert _request(transfer, _data(transfer)).status_code == 404
    transfer.listing.assert_not_called()
    transfer.writer.assert_not_called()


def test_closed_planning_still_allows_read_only_navigation(transfer):
    transfer.page.auth.return_value.accepts_private_planning_writes = False
    assert _request(transfer, chooser=True).status_code == 200


def test_no_other_admitted_destination_is_truthful_and_not_a_dead_form(transfer):
    transfer.listing.return_value = transfer.listing.return_value[:1]
    response = _request(transfer)
    assert response.status_code == 200
    assert b"No other current Department" in response.content
    assert b"data-call-command" not in response.content
    assert _request(transfer, _data(transfer)).status_code == 400
    transfer.writer.assert_not_called()


@pytest.mark.parametrize(
    "transport", ["query", "extra", "duplicate", "oversized", "chooser-post"]
)
def test_closed_transport_precedes_private_queries(transfer, transport):
    data = _data(transfer)
    kwargs = {}
    if transport == "query":
        kwargs["query"] = "?scope=foreign"
    elif transport == "extra":
        data["source_department_id"] = str(transfer.destination)
    elif transport == "duplicate":
        encoded = QueryDict(mutable=True)
        encoded.update(data)
        encoded.appendlist("destination_department_id", str(transfer.page.department))
        data = encoded
    elif transport == "oversized":
        data["reason"] = "x" * 6001
    else:
        kwargs["chooser"] = True
    assert _request(transfer, data, **kwargs).status_code == 400
    transfer.page.auth.assert_not_called()
    transfer.listing.assert_not_called()
    transfer.writer.assert_not_called()


def test_login_and_csrf_protect_actual_view(transfer):
    assert _request(transfer, anonymous=True).status_code == 302
    assert _request(transfer, _data(transfer), csrf=True).status_code == 403
    transfer.page.auth.assert_not_called()
    transfer.writer.assert_not_called()


@pytest.mark.parametrize(
    "failure", ["anchor", "choices", "lost-response", "audit", "writer-outage"]
)
def test_dependencies_release_no_prepared_names_or_invented_recovery(transfer, failure):
    if failure == "anchor":
        transfer.page.auth.side_effect = ApplicationsProgrammeAuthorizationDeniedError
    elif failure == "choices":
        transfer.listing.side_effect = ApplicationsProgrammeAuthorizationDeniedError
    elif failure == "lost-response":
        transfer.page.readers[
            "get_managed_programme_call_configuration"
        ].side_effect = ApplicationsProgrammeAuthorizationDeniedError
    elif failure == "audit":
        transfer.listing.side_effect = DatabaseError("private diagnostic")
    else:
        transfer.writer.side_effect = DatabaseError("private diagnostic")
    response = _request(transfer, _data(transfer))
    assert response.status_code == (
        503 if failure in {"audit", "writer-outage"} else 404
    )
    assert b"Programme Department" not in response.content
    assert b"private diagnostic" not in response.content


def test_owner_validation_retains_errors_and_revocation_on_render_suppresses_form(
    transfer,
):
    transfer.writer.side_effect = ValidationError({"reason": "Review this rationale."})
    response = _request(transfer, _data(transfer))
    assert response.status_code == 400
    assert b"Review this rationale." in response.content
    transfer.page.auth.side_effect = [
        SimpleNamespace(accepts_private_planning_writes=True),
        ApplicationsProgrammeAuthorizationDeniedError,
    ]
    response = _request(transfer, _data(transfer))
    assert response.status_code == 404
    assert b"Review this rationale." not in response.content


def test_reserved_routes_are_exact_and_unmounted(transfer):
    page = transfer.page
    root = (
        f"/admin/applications/programme-calls/{page.organization}/"
        f"{page.edition}/{page.department}/"
    )
    for suffix in ("departments/", f"{page.source.summary.call_id}/reassign/"):
        match = resolve(root + suffix, urlconf="maru.applications.programme_call_urls")
        assert match.func is views.programme_call_departments
        try:
            production_match = resolve(root + suffix)
        except Resolver404:
            continue
        assert production_match.func is not views.programme_call_departments
