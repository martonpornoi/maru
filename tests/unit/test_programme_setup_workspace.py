"""Real form/template adapter feedback with owning reads and writes isolated."""

from dataclasses import replace
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.http import QueryDict
from django.test import RequestFactory
from django.urls import Resolver404, resolve

from maru.events import programme_setup_views as views
from maru.events.programme_setup import ProgrammeSetupResult
from maru.events.programme_setup_forms import ProgrammeSetupForm
from maru.events.programme_setup_inputs import ProgrammeSetupMode as Mode
from maru.events.programme_setup_queries import (
    ProgrammeSetupChoices,
    ProgrammeSetupReceiptView,
)
from maru.events.queries import EditionRouteIdentity
from maru.identity.models import Account
from maru.organizations.programme_setup_references import ProgrammeFoundationChoice
from tests.unit.test_programme_setup_workspace_queries import foundation

URLCONF = "maru.events.programme_setup_urls"


def payload(mode=Mode.NEW_FOUNDATION):
    return {
        "organization_name": "Synthetic organizers"
        if mode == Mode.NEW_FOUNDATION
        else "",
        "series_name": "Synthetic convention" if mode != Mode.EXISTING_SERIES else "",
        "edition_name": "Synthetic 2030",
        "department_name": "Programme",
        "starts_on": "2030-09-01",
        "ends_on": "2030-09-03",
        "time_zone": "UTC",
        "reason": "Synthetic accountable setup",
        "confirmed": "on",
        "foundation_fingerprint": "" if mode == Mode.NEW_FOUNDATION else "a" * 64,
        "idempotency_key": str(UUID(int=8)),
    }


def form_for(mode, data=None):
    return ProgrammeSetupForm(
        payload(mode) if data is None else data,
        mode=mode,
        organization_id=UUID(int=2) if mode != Mode.NEW_FOUNDATION else None,
        series_id=UUID(int=3) if mode == Mode.EXISTING_SERIES else None,
    )


@pytest.mark.parametrize("mode", list(Mode))
def test_form_uses_route_owned_explicit_original_intent(mode):
    form = form_for(mode)
    assert form.is_valid(), form.errors
    details = form.setup_input()
    assert details.mode == mode
    assert details.starts_on == date(2030, 9, 1)
    assert details.department_name == "Programme"
    assert details.foundation_fingerprint == payload(mode)["foundation_fingerprint"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("confirmed", ""),
        ("reason", ""),
        ("reason", "private\nline"),
        ("edition_name", "x" * 161),
        ("ends_on", "2029-09-01"),
        ("time_zone", "Unknown/Zone"),
        ("idempotency_key", "not-uuid"),
        ("idempotency_key", str(UUID(int=0))),
        ("foundation_fingerprint", "a" * 64),
        ("actor_id", str(UUID(int=99))),
    ],
)
def test_form_rejects_unconfirmed_malformed_or_extra_intent(field, value):
    form = form_for(Mode.NEW_FOUNDATION, {**payload(), field: value})
    assert not form.is_valid()


@pytest.mark.parametrize(
    ("mode", "field", "value"),
    [
        (Mode.EXISTING_ORGANIZATION, "organization_name", "Rename parent"),
        (Mode.EXISTING_SERIES, "series_name", "Rename series"),
        (Mode.EXISTING_SERIES, "foundation_fingerprint", ""),
        (Mode.EXISTING_ORGANIZATION, "foundation_fingerprint", "A" * 64),
    ],
)
def test_reuse_rejects_hidden_rename_or_substituted_source(mode, field, value):
    assert not form_for(mode, {**payload(mode), field: value}).is_valid()


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
    source = foundation()
    choices = ProgrammeSetupChoices()
    result = ProgrammeSetupResult(
        UUID(int=6),
        UUID(int=2),
        UUID(int=3),
        UUID(int=4),
        UUID(int=5),
        UUID(int=7),
        replayed=False,
        created_organization=True,
        created_series=True,
    )
    receipt = ProgrammeSetupReceiptView(
        UUID(int=6),
        UUID(int=4),
        UUID(int=5),
        source,
        "Synthetic 2030",
        "Programme",
        date(2030, 9, 1),
        date(2030, 9, 3),
        "UTC",
        EditionRouteIdentity("synthetic", "con", "2030"),
        Mode.NEW_FOUNDATION,
    )
    loader, reader, command, admission = (
        Mock(return_value=choices),
        Mock(return_value=receipt),
        Mock(return_value=result),
        Mock(),
    )
    monkeypatch.setattr(views, "load_programme_setup_choices", loader)
    monkeypatch.setattr(views, "load_programme_setup_receipt", reader)
    monkeypatch.setattr(views, "setup_programme_foundation", command)
    monkeypatch.setattr(views, "require_programme_setup_actor", admission)
    return SimpleNamespace(
        source=source,
        choices=choices,
        result=result,
        receipt=receipt,
        loader=loader,
        reader=reader,
        command=command,
        admission=admission,
    )


def call(
    page,
    data=None,
    *,
    mode=Mode.NEW_FOUNDATION,
    receipt=False,
    anonymous=False,
    csrf=False,
    query="",
    method=None,
):
    path = "/admin/platform/setup/programme-operations/"
    kwargs = {}
    if receipt:
        kwargs = {
            "organization_id": UUID(int=2),
            "series_id": UUID(int=3),
            "edition_id": UUID(int=4),
            "receipt_id": UUID(int=6),
        }
        path += "receipt/" + "/".join(str(value) for value in kwargs.values()) + "/"
    elif mode is not None:
        kwargs = {"mode": mode.value if isinstance(mode, Mode) else mode}
        if mode == Mode.NEW_FOUNDATION:
            path += "new/"
        else:
            kwargs["organization_id"] = UUID(int=2)
            path += f"organization/{UUID(int=2)}/"
            if mode == Mode.EXISTING_SERIES:
                kwargs["series_id"] = UUID(int=3)
                path += f"series/{UUID(int=3)}/"
    factory = RequestFactory()
    request = (
        factory.post(path + query, data)
        if data is not None
        else factory.generic(method or "GET", path + query)
    )
    if isinstance(data, QueryDict):
        request = factory.post(
            path + query,
            data.urlencode(),
            content_type="application/x-www-form-urlencoded",
        )
    request.user = (
        AnonymousUser()
        if anonymous
        else Account(
            id=UUID(int=1),
            account_kind=Account.Kind.PLATFORM_ADMINISTRATOR,
            is_active=True,
        )
    )
    request.urlconf = URLCONF
    request._dont_enforce_csrf_checks = not csrf
    request.correlation_id = str(UUID(int=9))
    response = (
        views.programme_setup_receipt if receipt else views.programme_setup_workspace
    )(request, **kwargs)
    return response, request


def test_initial_inventory_uses_labels_and_never_offers_mutation(page):
    page.loader.return_value = ProgrammeSetupChoices(
        organizations=(
            ProgrammeFoundationChoice(UUID(int=2), "Synthetic organizers", "synthetic"),
        )
    )
    response, _ = call(page, mode=None)
    assert response.status_code == 200
    assert b"Synthetic organizers" in response.content
    assert b"Start a new organization" in response.content
    assert b"Create this Programme foundation" not in response.content
    page.command.assert_not_called()


def test_create_get_is_labelled_explicit_and_never_executes_owner(page):
    response, _ = call(page)
    assert response.status_code == 200
    assert response.content.count(b"<h1>") == 1
    assert b"Create a new foundation" in response.content
    assert b"This does not grant Programme access" in response.content
    assert b'name="csrfmiddlewaretoken"' in response.content
    assert "no-store" in response["Cache-Control"]
    assert response["X-Content-Type-Options"] == "nosniff"
    assert page.loader.call_count == 2
    page.command.assert_not_called()


@pytest.mark.parametrize("mode", [Mode.EXISTING_ORGANIZATION, Mode.EXISTING_SERIES])
def test_selected_foundation_is_labelled_with_original_fingerprint(page, mode):
    page.loader.return_value = ProgrammeSetupChoices(
        foundation=page.source,
        series=(ProgrammeFoundationChoice(UUID(int=3), "Synthetic convention", "con"),)
        if mode == Mode.EXISTING_ORGANIZATION
        else (),
    )
    response, _ = call(page, mode=mode)
    assert response.status_code == 200
    assert b"Synthetic organizers" in response.content
    assert ('value="' + "a" * 64 + '"').encode() in response.content
    if mode == Mode.EXISTING_ORGANIZATION:
        assert b"Reuse a convention in this organization" in response.content


@pytest.mark.parametrize("mode", list(Mode))
def test_success_calls_owner_once_then_redirects_without_requery_or_regrant(page, mode):
    response, request = call(page, payload(mode), mode=mode)
    assert response.status_code == 302
    assert str(page.result.receipt_id) in response["Location"]
    assert str(UUID(int=8)) not in response["Location"]
    page.command.assert_called_once()
    values = page.command.call_args.kwargs
    assert values["actor"] is request.user
    assert values["idempotency_key"] == UUID(int=8)
    assert values["details"].mode == mode
    page.loader.assert_not_called()


@pytest.mark.parametrize(
    ("fault", "status"),
    [
        (ValidationError("Original source changed"), 409),
        (DatabaseError("private database detail"), 503),
    ],
)
def test_command_failure_preserves_original_input_and_key_without_repeat(
    page, fault, status
):
    page.command.side_effect = fault
    response, _ = call(page, payload())
    assert response.status_code == status
    assert b"Synthetic accountable setup" in response.content
    assert str(UUID(int=8)).encode() in response.content
    assert b'data-programme-pending="true"' in response.content
    assert b'role="alert"' in response.content
    assert b"private database detail" not in response.content
    page.command.assert_called_once()


def test_changed_current_foundation_never_replaces_original_retry_snapshot(page):
    page.loader.return_value = ProgrammeSetupChoices(
        foundation=replace(page.source, fingerprint="b" * 64)
    )
    page.command.side_effect = ValidationError("Original source changed")
    response, _ = call(page, payload(Mode.EXISTING_SERIES), mode=Mode.EXISTING_SERIES)
    assert response.status_code == 409
    assert b"differs from your original snapshot" in response.content
    assert ('value="' + "a" * 64 + '"').encode() in response.content
    assert ('value="' + "b" * 64 + '"').encode() not in response.content


@pytest.mark.parametrize(
    ("field", "value"),
    [("confirmed", ""), ("organization_name", ""), ("ends_on", "invalid")],
)
def test_invalid_form_never_reaches_command(page, field, value):
    response, _ = call(page, {**payload(), field: value})
    assert response.status_code == 400
    page.command.assert_not_called()


@pytest.mark.parametrize(
    "data", [{**payload(), "actor_id": "foreign"}, {**payload(), "reason": "x" * 4097}]
)
def test_unknown_or_oversized_raw_input_precedes_owner_reads(page, data):
    response, _ = call(page, data)
    assert response.status_code == 400
    page.loader.assert_not_called()
    page.command.assert_not_called()


def test_duplicate_raw_values_are_not_collapsed(page):
    data = QueryDict(mutable=True)
    data.update(payload())
    data.setlist("reason", ["First", "Second"])
    response, _ = call(page, data)
    assert response.status_code == 400
    page.loader.assert_not_called()


@pytest.mark.parametrize(
    ("kwargs", "status"),
    [
        ({"data": payload(), "csrf": True}, 403),
        ({"method": "PUT"}, 405),
        ({"query": "?actor=foreign"}, 400),
        ({"data": payload(), "mode": None}, 400),
        ({"anonymous": True}, 302),
    ],
)
def test_transport_guards_precede_private_queries_and_commands(page, kwargs, status):
    response, _ = call(page, **kwargs)
    assert response.status_code == status
    page.loader.assert_not_called()
    page.command.assert_not_called()


@pytest.mark.parametrize("final", [False, True])
@pytest.mark.parametrize(
    ("fault", "status"),
    [
        (PermissionDenied(), 404),
        (DatabaseError("hidden"), 503),
        (ValidationError("overflow"), 503),
    ],
)
def test_failed_admission_or_final_read_withholds_prepared_private_content(
    page, final, fault, status
):
    page.loader.side_effect = [page.choices, fault] if final else fault
    response, _ = call(page)
    assert response.status_code == status
    assert b"Synthetic" not in response.content
    assert b"hidden" not in response.content
    assert b"<form" not in response.content


def test_changed_rendered_source_suppresses_old_page(page):
    page.loader.side_effect = [
        page.choices,
        ProgrammeSetupChoices(foundation=page.source),
    ]
    response, _ = call(page)
    assert response.status_code == 409
    assert b"<form" not in response.content


@pytest.mark.parametrize("active", [False, True])
def test_receipt_continuation_never_implies_acceptance_or_operational_approval(
    page, active
):
    if active:
        page.reader.return_value = replace(
            page.receipt, foundation=replace(page.source, representation_state="active")
        )
    response, _ = call(page, receipt=True)
    assert response.status_code == 200
    assert b"Original setup completed" in response.content
    assert b"Representation &amp; access" in response.content
    assert b"Platform administration cannot approve it for them" in response.content
    assert (
        b"currently active" in response.content
        if active
        else b"still provisioning" in response.content
    )
    assert b"Create this Programme foundation" not in response.content
    page.command.assert_not_called()
    assert page.reader.call_count == 2


def test_changed_receipt_after_render_is_withheld_without_repeating_setup(page):
    page.reader.side_effect = [
        page.receipt,
        replace(page.receipt, edition_name="Changed"),
    ]
    response, _ = call(page, receipt=True)
    assert response.status_code == 409
    assert b"Synthetic" not in response.content
    page.command.assert_not_called()


def test_receipt_rejects_post_before_read(page):
    response, _ = call(page, payload(), receipt=True)
    assert response.status_code == 405
    page.reader.assert_not_called()


@pytest.mark.parametrize(
    ("mode", "wording"),
    [
        (Mode.NEW_FOUNDATION, "created the organization and convention"),
        (
            Mode.EXISTING_ORGANIZATION,
            "reused the organization and created a convention",
        ),
        (Mode.EXISTING_SERIES, "reused the organization and convention"),
    ],
)
def test_receipt_distinguishes_original_creation_from_reuse(page, mode, wording):
    page.reader.return_value = replace(page.receipt, mode=mode)
    response, _ = call(page, receipt=True)
    assert wording.encode() in response.content
    page.command.assert_not_called()


@pytest.mark.parametrize(
    "suffix",
    [
        "",
        "new/",
        f"organization/{UUID(int=2)}/",
        f"organization/{UUID(int=2)}/series/{UUID(int=3)}/",
    ],
)
def test_reserved_setup_routes_resolve_only_in_isolated_urlconf(suffix):
    path = "/admin/platform/setup/programme-operations/" + suffix
    assert resolve(path, urlconf=URLCONF).func is views.programme_setup_workspace
    try:
        current = resolve(path, urlconf="maru.urls")
    except Resolver404:
        return
    assert current.func is not views.programme_setup_workspace
