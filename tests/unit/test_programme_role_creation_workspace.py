"""Real forms and shared-shell request HTML with explicitly stubbed owner services."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import urlencode
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from bs4 import BeautifulSoup
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.test import RequestFactory
from django.urls import resolve
from django.utils import timezone

from maru.authorization import programme_role_creation_views as views
from maru.authorization.programme_role_creation import ProgrammeRoleCreation
from maru.authorization.programme_role_creation_forms import (
    ProgrammeRoleCreationForm,
    ProgrammeRoleUTCMinuteField,
)
from maru.identity.models import Account
from tests.unit.test_programme_role_creation import (
    ACTOR,
    NOW,
    RECIPE,
    SCOPE,
    draft,
    signed,
)

URLCONF = "maru.authorization.programme_role_urls"
ROUTE = (
    f"/admin/programme/access/{SCOPE.organization_id}/"
    f"{SCOPE.programme_edition_id}/edition/new/"
)


def data(**changes):
    return {
        "recipe": RECIPE.catalog_entry,
        "recipient_email": draft().recipient_email,
        "approver_email": draft().approver_email,
        "not_before": "2026-09-18T00:00",
        "expires_at": "2026-09-21T00:00",
        "reason": draft().reason,
        "idempotency_key": str(draft().idempotency_key),
        "action": "preview",
        "selection_proof": "",
        **changes,
    }


def confirmation(**changes):
    return data(
        action="confirm", selection_proof=signed().proof, confirmed="on", **changes
    )


@pytest.mark.parametrize("zone", ["UTC", "Europe/Budapest", "America/Los_Angeles"])
def test_form_minutes_mean_explicit_utc_in_every_active_zone(zone):
    with timezone.override(ZoneInfo(zone)):
        form = ProgrammeRoleCreationForm(data(), recipes=(RECIPE,))
        assert form.is_valid(), form.errors
        assert form.draft.not_before == NOW
        assert form.draft.idempotency_key == draft().idempotency_key
        assert form.draft.intent(UUID(int=4), UUID(int=5)) == draft().intent(
            UUID(int=4), UUID(int=5)
        )


@pytest.mark.parametrize(
    "value",
    [
        "2026-09-18T00:00Z",
        "2026-09-18T00:00+02:00",
        "2026-02-30T10:00",
        "2026-09-18 00:00",
        "2026-09-18T24:00",
        "2026-09-18T00:00:00",
        "bad",
        3,
    ],
)
def test_utc_field_rejects_ambiguous_transport_and_impossible_minutes(value):
    with pytest.raises(ValidationError):
        ProgrammeRoleUTCMinuteField(required=False).clean(value)


def test_optional_utc_fields_retain_none():
    form = ProgrammeRoleCreationForm(
        data(not_before="", expires_at=""), recipes=(RECIPE,)
    )
    assert form.is_valid()
    assert form.draft.not_before is form.draft.expires_at is None


@pytest.mark.parametrize(
    "changes",
    [
        {"recipe": "unknown"},
        {"actor_id": str(ACTOR)},
        {"reason": "bad\nreason"},
        {"expires_at": "2026-09-18T00:00"},
        {"recipient_email": "not-an-email"},
        {"idempotency_key": str(UUID(int=0))},
        {"idempotency_key": "no"},
        {"action": "confirm"},
        {"selection_proof": "replace-existing-preview"},
    ],
)
def test_form_rejects_invalid_or_silently_replaced_original_intent(changes):
    form = ProgrammeRoleCreationForm(data(**changes), recipes=(RECIPE,))
    assert not form.is_valid()
    assert form.draft is None


def test_confirmation_is_required_and_original_terms_are_hidden_not_dropped():
    values = confirmation()
    values.pop("confirmed")
    form = ProgrammeRoleCreationForm(values, recipes=(RECIPE,), confirming=True)
    assert not form.is_valid()
    assert "confirmed" in form.errors
    assert form["reason"].is_hidden
    assert form["idempotency_key"].value() == str(draft().idempotency_key)
    nonconfirming_form = ProgrammeRoleCreationForm(values, recipes=(RECIPE,))
    assert not nonconfirming_form.is_valid()


@pytest.fixture(autouse=True)
def shell():
    with (
        patch.object(views.admin.site, "each_context", return_value={}),
        patch(
            "maru.events.templatetags.admin_edition_context.admin_edition_options",
            return_value={},
        ),
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
    workspace = ProgrammeRoleCreation(
        "Synthetic exact scope", "Synthetic edition", (RECIPE,)
    )
    preview = replace(
        workspace,
        selection=signed(),
        recipient_name="Synthetic recipient",
        approver_name="Synthetic approver",
    )
    loader = Mock(
        side_effect=lambda **kwargs: preview if kwargs.get("original") else workspace
    )
    prepare = Mock(return_value=preview)
    command = Mock(return_value=SimpleNamespace(request_id=UUID(int=100)))
    monkeypatch.setattr(views, "load_programme_role_creation", loader)
    monkeypatch.setattr(views, "prepare_programme_role_creation", prepare)
    monkeypatch.setattr(views, "request_programme_role", command)
    return SimpleNamespace(
        workspace=workspace,
        preview=preview,
        loader=loader,
        prepare=prepare,
        command=command,
    )


def call(
    values=None,
    *,
    method=None,
    query="",
    csrf=False,
    anonymous=False,
    encoded=False,
    level="edition",
):
    factory = RequestFactory()
    if values is None:
        request = factory.generic(method or "GET", ROUTE + query)
    elif encoded:
        request = factory.post(
            ROUTE + query,
            urlencode(values),
            content_type="application/x-www-form-urlencoded",
        )
    else:
        request = factory.post(ROUTE + query, values)
    request.user = (
        AnonymousUser()
        if anonymous
        else Account(id=ACTOR, is_active=True, email_verified_at=NOW)
    )
    request._dont_enforce_csrf_checks = not csrf
    request.urlconf = URLCONF
    return views.programme_role_creation(
        request, SCOPE.organization_id, SCOPE.programme_edition_id, level=level
    )


def test_get_has_shared_shell_labels_consequences_and_no_person_lookup_or_command(page):
    response = call()
    assert response.status_code == 200
    soup = BeautifulSoup(response.content, "html.parser")
    assert len(soup.find_all("h1")) == len(soup.find_all("main")) == 1
    assert "Synthetic exact scope" in soup.get_text()
    assert "workforce.view_shifts" in soup.get_text()
    assert "All date/time inputs are explicitly UTC" in soup.get_text()
    assert soup.select_one('input[name="recipient_email"][type="email"]')
    assert not soup.select(
        'input[name="recipient_id"],input[name="approver_id"],input[name="actor_id"]'
    )
    for control in soup.select("input:not([type=hidden]),select,textarea"):
        assert soup.find("label", attrs={"for": control["id"]})
    assert "private" in response["Cache-Control"]
    assert "no-store" in response["Cache-Control"]
    assert "frame-ancestors 'none'" in response["Content-Security-Policy"]
    assert page.loader.call_count == 2
    page.prepare.assert_not_called()
    page.command.assert_not_called()


def test_preview_shows_original_people_and_terms_then_requires_own_confirmation(page):
    response = call(data())
    assert response.status_code == 200
    soup = BeautifulSoup(response.content, "html.parser")
    text = soup.get_text()
    assert "Synthetic recipient" in text
    assert "Synthetic approver" in text
    assert "2026-09-18 00:00 UTC" in text
    assert draft().reason in text
    assert (
        soup.select_one('input[name="selection_proof"]')["value"]
        == page.preview.selection.proof
    )
    assert soup.select_one('input[name="idempotency_key"]')["value"] == str(
        draft().idempotency_key
    )
    assert soup.select_one('input[name="confirmed"][type="checkbox"]').has_attr(
        "required"
    )
    assert not soup.select_one('input[name="confirmed"]').has_attr("checked")
    assert soup.select_one("form[data-programme-pending=true]")
    page.prepare.assert_called_once()
    assert page.prepare.call_args.kwargs["actor"].id == ACTOR
    assert page.prepare.call_args.kwargs["scope"] == SCOPE
    page.command.assert_not_called()


def test_confirmation_calls_owner_once_and_redirects_before_render_or_refresh(page):
    response = call(confirmation())
    assert response.status_code == 302
    assert response["Location"] == ROUTE.removesuffix("new/") + f"{UUID(int=100)}/"
    assert str(draft().idempotency_key) not in response["Location"]
    assert "?" not in response["Location"]
    page.prepare.assert_not_called()
    page.command.assert_called_once()
    args = page.command.call_args.kwargs
    assert args["actor"].id == ACTOR
    assert args["scope"] == SCOPE
    assert args["details"] == signed().details
    assert args["idempotency_key"] == draft().idempotency_key
    assert page.loader.call_count == 1


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (ValidationError("Original intent conflict"), 409),
        (DatabaseError("unavailable"), 503),
    ],
)
def test_uncertain_or_conflicting_submission_retains_signed_original_input(
    page, error, status
):
    page.command.side_effect = error
    response = call(confirmation())
    assert response.status_code == status
    soup = BeautifulSoup(response.content, "html.parser")
    assert "Synthetic recipient" in soup.get_text()
    for field in (
        "reason",
        "idempotency_key",
        "recipient_email",
        "approver_email",
        "not_before",
        "expires_at",
    ):
        assert soup.select_one(f'input[name="{field}"]')["value"] == data()[field]
    assert soup.select_one('input[name="selection_proof"]')["value"]
    assert soup.select_one("form[data-programme-pending=true]")
    assert soup.select_one("[role=alert][autofocus]")
    page.command.assert_called_once()
    page.prepare.assert_not_called()


def test_missing_confirmation_renders_verified_original_preview_without_submission(
    page,
):
    values = confirmation()
    values.pop("confirmed")
    response = call(values)
    assert response.status_code == 400
    assert b"Synthetic recipient" in response.content
    page.command.assert_not_called()
    page.prepare.assert_not_called()


def test_tampered_preview_is_not_submitted_or_silently_replaced(page):
    values = confirmation()
    values["reason"] = "Changed intent"
    response = call(values)
    assert response.status_code == 400
    assert b"cannot be verified" in response.content
    assert b"Synthetic recipient" not in response.content
    page.command.assert_not_called()
    page.prepare.assert_not_called()


def test_empty_match_is_actionable_without_partial_person_data(page):
    page.prepare.return_value = page.workspace
    response = call(data())
    assert response.status_code == 400
    assert b"two exact people cannot be prepared" in response.content
    assert b"Synthetic recipient" not in response.content
    assert b"recipient@example.invalid" in response.content
    page.command.assert_not_called()


def test_no_admitted_recipes_has_no_creation_form(page):
    page.loader.side_effect = None
    page.loader.return_value = replace(page.workspace, recipes=())
    response = call()
    assert response.status_code == 200
    assert b"No supported operational task" in response.content
    assert not BeautifulSoup(response.content, "html.parser").select_one(
        "form[data-programme-command]"
    )


@pytest.mark.parametrize(
    ("failure", "status"), [(PermissionDenied(), 404), (DatabaseError(), 503)]
)
def test_denied_or_unavailable_admission_discloses_no_names(page, failure, status):
    page.loader.side_effect = failure
    response = call()
    assert response.status_code == status
    assert b"Synthetic" not in response.content
    page.command.assert_not_called()


@pytest.mark.parametrize("final", ["changed", "denied", "unavailable"])
def test_final_render_source_or_access_change_suppresses_private_html(page, final):
    ending = (
        replace(page.workspace, context_label="Changed")
        if final == "changed"
        else PermissionDenied()
        if final == "denied"
        else DatabaseError()
    )
    page.loader.side_effect = [page.workspace, ending]
    response = call()
    assert (
        response.status_code
        == {"changed": 409, "denied": 404, "unavailable": 503}[final]
    )
    assert b"Synthetic" not in response.content


def test_changed_selected_person_after_preview_suppresses_prepared_html(page):
    page.loader.side_effect = [
        page.workspace,
        replace(page.preview, recipient_name="Changed person"),
    ]
    response = call(data())
    assert response.status_code == 409
    assert b"Synthetic recipient" not in response.content


@pytest.mark.parametrize(
    "changes",
    [
        {"actor_id": str(ACTOR)},
        {"scope": "organization"},
        {"recipient_id": str(UUID(int=4))},
        {"reason": "x" * 4097},
    ],
)
def test_closed_transport_precedes_owner_reads(page, changes):
    response = call(data(**changes))
    assert response.status_code == 400
    page.loader.assert_not_called()


def test_duplicate_fields_are_rejected_before_owner_reads(page):
    values = [*data().items(), ("reason", "second")]
    assert call(values, encoded=True).status_code == 400
    page.loader.assert_not_called()


def test_query_fields_are_rejected_before_owner_reads(page):
    assert call(query="?actor=other").status_code == 400
    page.loader.assert_not_called()


def test_csrf_method_and_anonymous_boundaries(page):
    assert call(data(), csrf=True).status_code == 403
    assert call(method="PUT").status_code == 405
    assert call(anonymous=True).status_code == 302
    page.loader.assert_not_called()


def test_organization_scope_warns_about_shared_venue_consequences(page):
    response = call(level="organization")
    assert response.status_code == 200
    assert b"broader than this edition" in response.content


def test_reserved_creation_resolves_only_in_isolated_urlconf():
    assert resolve(ROUTE, urlconf=URLCONF).url_name == "programme-access-edition-new"
    assert resolve(ROUTE, urlconf="maru.urls").func is not views.programme_role_creation


@pytest.mark.parametrize(
    ("level", "tail"),
    [
        ("organization", "organization/"),
        ("department", f"department/{UUID(int=7)}/"),
        ("resource", f"room/{UUID(int=7)}/{UUID(int=8)}/"),
    ],
)
def test_narrow_and_broader_creation_routes_keep_code_owned_scope(level, tail):
    url = ROUTE.removesuffix("edition/new/") + tail + "new/"
    match = resolve(url, urlconf=URLCONF)
    assert match.func is views.programme_role_creation
    assert match.kwargs["level"] == level
    assert resolve(url, urlconf="maru.urls").func is not views.programme_role_creation
