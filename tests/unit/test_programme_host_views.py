"""Database-free hosting HTTP contracts using real forms, templates and owner DTOs."""

from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime
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

from maru.programme import host_invitation_preview as selections
from maru.programme import host_invitation_views as invitations
from maru.programme import host_personal_views as personal
from maru.programme import host_queries as queries
from maru.programme import host_views as organizer
from maru.programme import queries as item_queries
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.commands import ProgrammeVersionConflictError
from maru.programme.host_commands import ProgrammeHostCommandResult
from maru.programme.queries import (
    ProgrammeItemProjection,
    ProgrammePrivateItemProjection,
    ProgrammeQueryUnavailableError,
    ProgrammeWorkingProjection,
)
from maru.programme.timetable_queries import PersonalHostPurpose
from maru.programme.workbench_queries import ProgrammeWorkbenchItem


@pytest.fixture(autouse=True)
def shell():
    with (
        patch.object(organizer.admin.site, "each_context", return_value={}),
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
def hosting(monkeypatch):
    actor, organization, edition, item_id, source_id, person_id, host_id = (
        UUID(int=i) for i in range(1, 8)
    )
    relationship = queries.ProgrammeHostStateProjection(
        host_id, "host", "invited", 3, 2
    )
    entry = queries.ProgrammeHostRosterEntry(
        relationship, person_id, person_current=True, display_label="River Host"
    )
    roster = queries.ProgrammeHostRosterSnapshot(7, (entry,))
    invitation = queries.ProgrammeHostInvitationProjection(
        2, "host", "Your ceremony invitation", "Deliberate host-only briefing"
    )
    snapshot = queries.ProgrammeHostSelfSnapshot(
        7, relationship, (invitation,), (relationship,), "draft", 1, (), None
    )
    selected = ProgrammeWorkbenchItem(
        ProgrammePrivateItemProjection(
            ProgrammeItemProjection(item_id, "ceremony", "organizer_core", "active", 7),
            ProgrammeWorkingProjection("PRIVATE working title", "PRIVATE summary", 6),
        ),
        source_id,
    )
    auth = Mock(return_value=SimpleNamespace(accepts_private_planning_writes=True))
    monkeypatch.setattr(organizer, "authorize_programme_scope", auth)
    monkeypatch.setattr(selections, "authorize_programme_scope", auth)
    monkeypatch.setattr(item_queries, "authorize_programme_scope", auth)
    monkeypatch.setattr(item_queries.transaction, "atomic", nullcontext)
    monkeypatch.setattr(item_queries, "_append_query_audit", Mock())
    monkeypatch.setattr(item_queries, "_append_query_denial_audit", Mock())
    retry_admission = Mock()
    monkeypatch.setattr(invitations, "authorize_host_retry_scope", retry_admission)
    private = Mock(return_value=selected)
    monkeypatch.setattr(organizer, "load_programme_workbench_item", private)
    readers = {}
    for name, result in {
        "load_programme_host_roster": roster,
        "load_programme_host_self": snapshot,
        "load_programme_host_history": (
            queries.ProgrammeHostHistoryEntry(
                relationship,
                "invited",
                actor,
                "PRIVATE rationale",
                datetime(2026, 9, 14, tzinfo=UTC),
                7,
            ),
        ),
        "load_programme_host_dependencies": queries.ProgrammeHostDependencySnapshot(
            item_id,
            7,
            11,
            "host-contract",
            (
                queries.ProgrammeHostAvailabilityProjection(
                    host_id, 3, 1, "not_shared", ()
                ),
            ),
        ),
    }.items():
        readers[name] = Mock(return_value=result)
        monkeypatch.setattr(queries, name, readers[name])
    purposes = Mock(
        return_value=(
            PersonalHostPurpose(
                host_id,
                item_id,
                "host",
                "invited",
                3,
                2,
                invitation.title,
                invitation.briefing,
            ),
        )
    )
    monkeypatch.setattr(personal, "load_personal_host_purposes", purposes)
    address = Mock(return_value=SimpleNamespace(account_id=person_id))
    monkeypatch.setattr(
        selections, "resolve_active_verified_person_reference_by_email", address
    )
    edition_query = Mock(
        return_value=SimpleNamespace(version=11, zone_name="Europe/Budapest")
    )
    envelope = Mock(
        return_value=SimpleNamespace(
            version=11,
            starts_at=datetime(2026, 9, 14, tzinfo=UTC),
            ends_at=datetime(2026, 9, 20, tzinfo=UTC),
        )
    )
    monkeypatch.setattr(personal, "resolve_scheduling_edition_reference", edition_query)
    monkeypatch.setattr(personal, "resolve_edition_time_envelope_reference", envelope)
    writers = {}
    for name in (
        "invite_programme_host",
        "remove_programme_host",
        "respond_to_programme_host_invitation",
        "replace_programme_host_availability",
    ):
        writers[name] = Mock()
        monkeypatch.setattr(organizer.host_commands, name, writers[name])
    writers["invite_programme_host"].return_value = ProgrammeHostCommandResult(
        UUID(int=80), item_id, host_id, UUID(int=81), 8, 1, 1, replayed=False
    )
    return SimpleNamespace(
        actor=actor,
        organization=organization,
        edition=edition,
        item_id=item_id,
        person_id=person_id,
        host_id=host_id,
        auth=auth,
        retry_admission=retry_admission,
        private=private,
        readers=readers,
        purposes=purposes,
        address=address,
        writers=writers,
        edition_query=edition_query,
        envelope=envelope,
    )


def call(
    page, task="roster", data=None, *, own=False, host_id=None, csrf=False, query=""
):
    root = (
        f"/my/programme/hosting/{page.organization}/{page.edition}/"
        if own
        else (
            f"/admin/programme/hosts/{page.organization}/{page.edition}/{page.item_id}/"
        )
    )
    url = (
        root
        + (f"{page.item_id}/{task}/" if own and task != "inventory" else "")
        + query
    )
    if data is not None:
        encoded = data if isinstance(data, QueryDict) else QueryDict("", mutable=True)
        if not isinstance(data, QueryDict):
            encoded.update(data)
        request = RequestFactory().post(
            url,
            data=encoded.urlencode(),
            content_type="application/x-www-form-urlencoded",
        )
    else:
        request = RequestFactory().get(url)
    request.user = SimpleNamespace(
        pk=page.person_id if own else page.actor,
        is_authenticated=True,
        is_active=True,
        is_staff=False,
        is_superuser=False,
    )
    request._dont_enforce_csrf_checks = not csrf
    kwargs = {
        "organization_id": page.organization,
        "edition_id": page.edition,
        "task": task,
    }
    if own:
        return personal.personal_programme_hosts(
            request, **kwargs, item_id=None if task == "inventory" else page.item_id
        )
    if task == "invite":
        return invitations.programme_host_invitation(
            request, page.organization, page.edition, page.item_id
        )
    return organizer.programme_hosts(
        request, **kwargs, item_id=page.item_id, host_id=host_id
    )


def manager_data(task):
    values = {
        "expected_version": "7",
        "idempotency_key": str(UUID(int=90)),
        "reason": "Deliberate organizer decision",
    }
    if task == "remove":
        return {**values, "expected_host_version": "3", "confirm_removal": "on"}
    values.update(role="host", title="Explicit invitation", briefing="Deliberate brief")
    if task == "invite":
        values["recipient_email"] = "river@example.test"
        values["action"] = "preview"
    else:
        values["expected_host_version"] = "3"
    return values


def own_data(task="invitation"):
    values = {
        "expected_item_version": "7",
        "expected_host_version": "3",
        "idempotency_key": str(UUID(int=91)),
    }
    if task == "invitation":
        return {**values, "invitation_sequence": "2", "response": "confirm"}
    if task == "withdraw-availability":
        return {**values, "confirm_withdrawal": "on"}
    return {
        **values,
        "expected_edition_version": "11",
        "state": "shared",
        "periods-TOTAL_FORMS": "1",
        "periods-INITIAL_FORMS": "0",
        "periods-0-starts_at": "2026-09-15T10:00",
        "periods-0-ends_at": "2026-09-15T11:00",
        "periods-0-kind": "available",
    }


def invitation_confirmation(page, data=None):
    values = manager_data("invite") if data is None else data
    response = call(page, "invite", values | {"action": "preview"})
    assert response.status_code == 200
    html = BeautifulSoup(response.content, "html.parser")
    proof = html.select_one('[name="selection_proof"]')["value"]
    return values | {"action": "confirm", "selection_proof": proof, "confirm": "on"}


def test_preview_never_invites_and_requires_deliberate_confirmation(hosting):
    data = invitation_confirmation(hosting)
    hosting.writers["invite_programme_host"].assert_not_called()
    response = call(hosting, "invite", data | {"confirm": ""})
    assert response.status_code == 400
    hosting.writers["invite_programme_host"].assert_not_called()
    assert data["selection_proof"] in response.content.decode()


@pytest.mark.parametrize("new_person", [None, UUID(int=99)])
def test_original_confirmation_never_resolves_changed_address_again(
    hosting, new_person
):
    data = invitation_confirmation(hosting)
    hosting.address.reset_mock()
    hosting.address.return_value = (
        None if new_person is None else SimpleNamespace(account_id=new_person)
    )
    assert call(hosting, "invite", data).status_code == 200
    hosting.address.assert_not_called()
    supplied = hosting.writers["invite_programme_host"].call_args.kwargs
    assert supplied["invitation"].account_id == hosting.person_id
    assert supplied["source_channel"] == "programme-hosts"
    assert supplied["idempotency_key"] == UUID(int=90)


def test_original_receipt_precedes_fresh_authority_and_private_reads(hosting):
    data = invitation_confirmation(hosting)
    writer = hosting.writers["invite_programme_host"]
    writer.return_value = replace(writer.return_value, replayed=True)
    hosting.private.reset_mock()
    hosting.auth.reset_mock()

    def original_owner(**_kwargs):
        hosting.private.assert_not_called()
        hosting.auth.assert_not_called()
        return writer.return_value

    writer.side_effect = original_owner

    def refused_read(*_args, **_kwargs):
        writer.assert_called_once()
        raise ProgrammeAuthorizationDeniedError

    hosting.private.side_effect = refused_read
    hosting.auth.side_effect = ProgrammeAuthorizationDeniedError
    response = call(hosting, "invite", data)
    assert response.status_code == 200
    text = response.content.decode()
    assert "original invitation receipt was recovered" in text
    assert "PRIVATE working title" not in text
    assert "river@example.test" not in text
    assert "No private roster continuation" in text


def test_optional_roster_link_revocation_falls_back_to_minimal_receipt(hosting):
    data = invitation_confirmation(hosting)
    hosting.private.side_effect = [
        hosting.private.return_value,
        ProgrammeAuthorizationDeniedError,
    ]
    response = call(hosting, "invite", data)
    assert response.status_code == 200
    assert "No private roster continuation" in response.content.decode()
    assert (
        "Open the independently authorized host roster" not in response.content.decode()
    )


def test_current_retry_admission_denial_prevents_owner_call(hosting):
    data = invitation_confirmation(hosting)
    hosting.retry_admission.side_effect = ProgrammeAuthorizationDeniedError
    assert call(hosting, "invite", data).status_code == 404
    hosting.writers["invite_programme_host"].assert_not_called()


def test_retry_admission_revoked_during_render_discards_receipt(hosting, monkeypatch):
    data = invitation_confirmation(hosting)
    render = invitations.render_to_string

    def revoke(*args, **kwargs):
        html = render(*args, **kwargs)
        hosting.retry_admission.side_effect = ProgrammeAuthorizationDeniedError
        return html

    monkeypatch.setattr(invitations, "render_to_string", revoke)
    response = call(hosting, "invite", data)
    assert response.status_code == 404
    assert b"receipt references" not in response.content


def test_fresh_private_authority_revoked_during_render_discards_preview(
    hosting, monkeypatch
):
    render = invitations.render_to_string

    def revoke(*args, **kwargs):
        html = render(*args, **kwargs)
        hosting.auth.side_effect = ProgrammeAuthorizationDeniedError
        return html

    monkeypatch.setattr(invitations, "render_to_string", revoke)
    response = call(hosting, "invite", manager_data("invite"))
    assert response.status_code == 404
    assert b"river@example.test" not in response.content
    hosting.writers["invite_programme_host"].assert_not_called()


def test_foreign_owner_result_is_never_disclosed(hosting):
    data = invitation_confirmation(hosting)
    writer = hosting.writers["invite_programme_host"]
    writer.return_value = replace(writer.return_value, item_id=UUID(int=99))
    response = call(hosting, "invite", data)
    assert response.status_code == 503
    assert str(writer.return_value.receipt_id) not in response.content.decode()


@pytest.mark.parametrize(
    "field", ["selection_proof", "recipient_email", "title", "reason"]
)
def test_changed_or_missing_original_selection_cannot_invoke_owner(hosting, field):
    data = invitation_confirmation(hosting)
    data[field] = "other@example.test" if field == "recipient_email" else ""
    response = call(hosting, "invite", data)
    assert response.status_code == 400
    hosting.writers["invite_programme_host"].assert_not_called()


def test_deliberate_repreview_selects_new_person_without_confirmation(hosting):
    data = invitation_confirmation(hosting)
    hosting.address.return_value = SimpleNamespace(account_id=UUID(int=99))
    response = call(
        hosting,
        "invite",
        data
        | {"action": "preview", "confirm": "", "recipient_email": "other@example.test"},
    )
    assert response.status_code == 200
    assert str(UUID(int=99)) in response.content.decode()
    hosting.writers["invite_programme_host"].assert_not_called()


@pytest.mark.parametrize(
    "failure", [ProgrammeVersionConflictError, ProgrammeQueryUnavailableError]
)
def test_original_selection_survives_stale_or_uncertain_owner_failure(hosting, failure):
    data = invitation_confirmation(hosting)
    hosting.writers["invite_programme_host"].side_effect = failure
    reader = hosting.readers["load_programme_host_roster"]
    reader.return_value = replace(reader.return_value, item_version=8)
    selected = hosting.private.return_value
    hosting.private.return_value = replace(
        selected,
        private=replace(
            selected.private,
            item=replace(selected.private.item, aggregate_version=8),
        ),
    )
    response = call(hosting, "invite", data)
    assert response.status_code == (
        409 if failure is ProgrammeVersionConflictError else 503
    )
    soup = BeautifulSoup(response.content, "html.parser")
    for field in (
        "selection_proof",
        "idempotency_key",
        "expected_version",
        "title",
        "recipient_email",
        "reason",
    ):
        control = soup.select_one(f'[name="{field}"]')
        assert (
            control.get("value", control.get_text().removeprefix("\n")) == data[field]
        )
    assert soup.select_one('[name="confirm"]').has_attr("checked")
    assert soup.select_one('[role="alert"]')["tabindex"] == "-1"


def test_stale_preview_does_not_resolve_person_or_rebase_version(hosting):
    response = call(
        hosting, "invite", manager_data("invite") | {"expected_version": "6"}
    )
    assert response.status_code == 409
    hosting.address.assert_not_called()
    hosting.writers["invite_programme_host"].assert_not_called()


def test_invitation_url_uses_preview_adapter_and_generic_adapter_cannot_bypass(hosting):
    url = (
        f"/admin/programme/hosts/{hosting.organization}/{hosting.edition}/"
        f"{hosting.item_id}/invite/"
    )
    assert (
        resolve(url, urlconf="maru.programme.host_urls").func
        is invitations.programme_host_invitation
    )
    request = RequestFactory().post(url, manager_data("invite"))
    request.user = SimpleNamespace(
        pk=hosting.actor, is_authenticated=True, is_active=True
    )
    request._dont_enforce_csrf_checks = True
    response = organizer.programme_hosts(
        request, hosting.organization, hosting.edition, hosting.item_id, task="invite"
    )
    assert response.status_code == 400
    hosting.writers["invite_programme_host"].assert_not_called()


def confirmed(page):
    reader = page.readers["load_programme_host_self"]
    reader.return_value = replace(
        reader.return_value,
        relationship=replace(reader.return_value.relationship, state="confirmed"),
    )


@pytest.mark.parametrize(
    "task", ["roster", "invite", "history", "availability", "remove"]
)
def test_manager_real_pages_are_labelled_and_not_private_prefills(hosting, task):
    host_id = hosting.host_id if task in {"history", "remove"} else None
    response = call(hosting, task, host_id=host_id)
    assert response.status_code == 200
    soup = BeautifulSoup(response.content, "html.parser")
    assert len(soup.find_all("h1")) == len(soup.find_all("main")) == 1
    ids = [node["id"] for node in soup.select("[id]")]
    assert len(ids) == len(set(ids))
    assert "PRIVATE summary" not in soup.get_text()
    assert "no-store" in response["Cache-Control"]
    assert "'nonce-'" not in response["Content-Security-Policy"]
    if task == "invite":
        assert soup.select_one('[name="title"]').get("value", "") == ""
        assert soup.select_one('[name="briefing"]').get_text().strip() == ""
    if task != "history":
        hosting.readers["load_programme_host_history"].assert_not_called()
    if task != "availability":
        hosting.readers["load_programme_host_dependencies"].assert_not_called()


@pytest.mark.parametrize("task", ["invite", "reinvite", "remove"])
def test_manager_commands_preserve_exact_scope_subject_and_original_versions(
    hosting, task
):
    if task == "reinvite":
        reader = hosting.readers["load_programme_host_roster"]
        entry = reader.return_value.entries[0]
        reader.return_value = replace(
            reader.return_value,
            entries=(
                replace(
                    entry, relationship=replace(entry.relationship, state="declined")
                ),
            ),
        )
    data = invitation_confirmation(hosting) if task == "invite" else manager_data(task)
    response = call(
        hosting,
        task,
        data,
        host_id=hosting.host_id if task != "invite" else None,
    )
    assert response.status_code == (200 if task == "invite" else 302)
    name = "remove_programme_host" if task == "remove" else "invite_programme_host"
    writer = hosting.writers[name]
    writer.assert_called_once()
    kwargs = writer.call_args.kwargs
    for key in ("actor_id", "organization_id", "edition_id", "item_id"):
        assert kwargs[key] == getattr(
            hosting, key.removesuffix("_id") if key != "item_id" else key
        )
    assert kwargs["reason"] == "Deliberate organizer decision"
    assert kwargs["idempotency_key"] == UUID(int=90)
    if task == "remove":
        assert kwargs["host_id"] == hosting.host_id
        assert kwargs["expected_item_version"] == 7
        assert kwargs["expected_host_version"] == 3
        assert "confirm_removal" not in kwargs
    else:
        invitation = kwargs["invitation"]
        assert invitation.account_id == hosting.person_id
        assert invitation.expected_item_version == 7
        assert invitation.expected_host_version == (0 if task == "invite" else 3)
        assert invitation.title == "Explicit invitation"
    if task != "invite":
        hosting.address.assert_not_called()


@pytest.mark.parametrize(
    "field", ["host_roster", "host_history", "shared_host_availability"]
)
def test_independent_roster_field_denials_precede_data_reads(hosting, field):
    def deny(**kwargs):
        if field in (kwargs.get("requested_fields") or ()):
            raise ProgrammeAuthorizationDeniedError
        return SimpleNamespace(accepts_private_planning_writes=True)

    hosting.auth.side_effect = deny
    task = {
        "host_roster": "roster",
        "host_history": "history",
        "shared_host_availability": "availability",
    }[field]
    response = call(
        hosting, task, host_id=hosting.host_id if task == "history" else None
    )
    assert response.status_code == 404
    hosting.private.assert_not_called()
    assert b"PRIVATE" not in response.content


@pytest.mark.parametrize(
    "task",
    ["inventory", "invitation", "history", "availability", "withdraw-availability"],
)
def test_personal_pages_never_query_or_render_organizer_layers(hosting, task):
    confirmed(hosting)
    response = call(hosting, task, own=True)
    assert response.status_code == 200
    assert b"PRIVATE" not in response.content
    assert b"River Host" not in response.content
    hosting.private.assert_not_called()
    hosting.address.assert_not_called()
    for name in (
        "load_programme_host_roster",
        "load_programme_host_history",
        "load_programme_host_dependencies",
    ):
        hosting.readers[name].assert_not_called()
    soup = BeautifulSoup(response.content, "html.parser")
    assert len(soup.find_all("h1")) == len(soup.find_all("main")) == 1
    assert soup.select('[name="reason"], [name="account_id"], [name="actor_id"]') == []
    assert "no-store" in response["Cache-Control"]
    if task == "inventory":
        assert hosting.purposes.call_args.kwargs["purpose"] == "hosting"
        assert hosting.purposes.call_args.kwargs["actor_id"] == hosting.person_id
    else:
        assert (
            hosting.readers["load_programme_host_self"].call_args.args[0].actor_id
            == hosting.person_id
        )
    if task == "availability":
        assert b"2026-09-14T02:00:00+02:00" in response.content
        assert b"Remove this period from the saved set" in response.content


@pytest.mark.parametrize("decision", ["confirm", "decline", "withdraw"])
def test_personal_response_never_impersonates_or_collects_rationale(hosting, decision):
    if decision == "withdraw":
        confirmed(hosting)
    data = {**own_data(), "response": decision}
    response = call(hosting, "invitation", data, own=True)
    assert response.status_code == 302
    kwargs = hosting.writers["respond_to_programme_host_invitation"].call_args.kwargs
    assert kwargs["actor_id"] == hosting.person_id
    assert kwargs["item_id"] == hosting.item_id
    assert "reason" not in kwargs
    assert "account_id" not in kwargs
    intent = kwargs["response"]
    assert intent.host_id == hosting.host_id
    assert intent.response == decision
    assert intent.expected_item_version == 7
    assert intent.expected_host_version == 3
    assert intent.invitation_sequence == 2


@pytest.mark.parametrize(
    ("decision", "expected"), [("confirm", 404), ("decline", 302), ("withdraw", 302)]
)
def test_closed_planning_retains_only_person_owned_privacy_exits(
    hosting, decision, expected
):
    if decision == "withdraw":
        confirmed(hosting)
    hosting.auth.return_value.accepts_private_planning_writes = False
    response = call(
        hosting, "invitation", {**own_data(), "response": decision}, own=True
    )
    assert response.status_code == expected
    if expected == 404:
        hosting.writers["respond_to_programme_host_invitation"].assert_not_called()


def test_availability_uses_explicit_zone_complete_periods_and_no_cross_purpose_subject(
    hosting,
):
    confirmed(hosting)
    response = call(hosting, "availability", own_data("availability"), own=True)
    assert response.status_code == 302
    kwargs = hosting.writers["replace_programme_host_availability"].call_args.kwargs
    assert kwargs["actor_id"] == hosting.person_id
    assert kwargs["item_id"] == hosting.item_id
    intent = kwargs["availability"]
    assert intent.host_id == hosting.host_id
    assert intent.state == "shared"
    assert len(intent.periods) == 1
    assert intent.periods[0].starts_at == datetime(2026, 9, 15, 8, tzinfo=UTC)
    assert intent.periods[0].ends_at == datetime(2026, 9, 15, 9, tzinfo=UTC)


@pytest.mark.parametrize("state", ["draft", "shared"])
def test_untouched_extra_period_permits_deliberate_empty_set(hosting, state):
    confirmed(hosting)
    data = own_data("availability")
    data.update({"state": state, "periods-0-starts_at": "", "periods-0-ends_at": ""})
    response = call(hosting, "availability", data, own=True)
    assert response.status_code == 302
    intent = hosting.writers["replace_programme_host_availability"].call_args.kwargs[
        "availability"
    ]
    assert intent.state == state
    assert intent.periods == ()


def test_withdrawal_after_planning_close_needs_no_envelope_and_clears_periods(hosting):
    confirmed(hosting)
    hosting.auth.return_value.accepts_private_planning_writes = False
    hosting.edition_query.side_effect = AssertionError(
        "privacy exit must not resolve dates"
    )
    hosting.envelope.side_effect = AssertionError("privacy exit must not resolve dates")
    response = call(
        hosting, "withdraw-availability", own_data("withdraw-availability"), own=True
    )
    assert response.status_code == 302
    intent = hosting.writers["replace_programme_host_availability"].call_args.kwargs[
        "availability"
    ]
    assert intent.state == "withdrawn"
    assert intent.periods == ()


def test_changed_edition_version_rejects_before_command_and_retains_original_input(
    hosting,
):
    confirmed(hosting)
    data = {**own_data("availability"), "expected_edition_version": "10"}
    response = call(hosting, "availability", data, own=True)
    assert response.status_code == 409
    hosting.writers["replace_programme_host_availability"].assert_not_called()
    soup = BeautifulSoup(response.content, "html.parser")
    assert soup.select_one('[name="expected_edition_version"]')["value"] == "10"
    assert (
        soup.select_one('[name="periods-0-starts_at"]')["value"]
        == data["periods-0-starts_at"]
    )
    assert soup.select_one('[data-programme-pending="true"]') is not None


@pytest.mark.parametrize("own", [False, True])
@pytest.mark.parametrize(
    "attack",
    ["actor_id", "account_id", "organization_id", "duplicate", "query", "csrf"],
)
def test_closed_transport_rejects_authority_overrides_before_writing(
    hosting, own, attack
):
    task = "invitation" if own else "invite"
    data = own_data() if own else manager_data(task)
    if attack in {"actor_id", "account_id", "organization_id"}:
        data[attack] = str(UUID(int=999))
    if attack == "duplicate":
        querydict = QueryDict("", mutable=True)
        querydict.update(data)
        querydict.appendlist("idempotency_key", str(UUID(int=999)))
        data = querydict
    response = call(
        hosting,
        task,
        data,
        own=own,
        csrf=attack == "csrf",
        query="?override=1" if attack == "query" else "",
    )
    assert response.status_code == (403 if attack == "csrf" else 400)
    for writer in hosting.writers.values():
        writer.assert_not_called()


@pytest.mark.parametrize("own", [False, True])
def test_owner_conflict_preserves_original_version_retry_and_text(hosting, own):
    task = "invitation" if own else "invite"
    writer = hosting.writers[
        "respond_to_programme_host_invitation" if own else "invite_programme_host"
    ]
    writer.side_effect = ProgrammeVersionConflictError
    data = own_data() if own else invitation_confirmation(hosting)
    version = "expected_item_version" if own else "expected_version"
    if own:
        data[version] = "5"
    response = call(hosting, task, data, own=own)
    assert response.status_code == 409
    soup = BeautifulSoup(response.content, "html.parser")
    assert soup.select_one(f'[name="{version}"]')["value"] == ("5" if own else "7")
    assert (
        soup.select_one('[name="idempotency_key"]')["value"] == data["idempotency_key"]
    )
    assert soup.select_one('[role="alert"]') is not None


def test_unknown_address_is_bounded_validation_not_account_creation(hosting):
    hosting.address.return_value = None
    response = call(hosting, "invite", manager_data("invite"))
    assert response.status_code == 400
    assert b"existing active verified person" in response.content
    hosting.writers["invite_programme_host"].assert_not_called()


def test_negative_lookup_audit_failure_does_not_disclose_match_result(
    hosting, monkeypatch
):
    hosting.address.return_value = None
    monkeypatch.setattr(
        item_queries,
        "_append_query_audit",
        Mock(side_effect=DatabaseError("audit unavailable")),
    )
    response = call(hosting, "invite", manager_data("invite"))
    assert response.status_code == 503
    assert b"Person selection is unavailable" in response.content
    assert b"This address cannot receive" not in response.content
    hosting.writers["invite_programme_host"].assert_not_called()


def test_foreign_relationship_has_no_history_or_write(hosting):
    response = call(hosting, "history", host_id=UUID(int=888))
    assert response.status_code == 404
    hosting.readers["load_programme_host_history"].assert_not_called()


@pytest.mark.parametrize("task", ["history", "availability"])
def test_incoherent_roster_composition_is_unavailable_without_partial_data(
    hosting, task
):
    if task == "history":
        hosting.readers["load_programme_host_history"].return_value = ()
    else:
        reader = hosting.readers["load_programme_host_dependencies"]
        reader.return_value = replace(reader.return_value, item_version=8)
    response = call(
        hosting, task, host_id=hosting.host_id if task == "history" else None
    )
    assert response.status_code == 503
    assert b"PRIVATE" not in response.content
    assert b"River Host" not in response.content


@pytest.mark.parametrize("own", [False, True])
def test_dependency_or_mandatory_audit_failure_has_no_partial_content(hosting, own):
    name = "load_programme_host_self" if own else "load_programme_host_roster"
    hosting.readers[name].side_effect = ProgrammeQueryUnavailableError
    response = call(hosting, "invitation" if own else "roster", own=own)
    assert response.status_code == 503
    assert b"PRIVATE" not in response.content
    assert b"Deliberate host" not in response.content


@pytest.mark.parametrize("count", ["129", "1000000", "-1", "1.0", "01"])
def test_hostile_formset_count_never_reaches_writer(hosting, count):
    confirmed(hosting)
    data = {**own_data("availability"), "periods-TOTAL_FORMS": count}
    assert call(hosting, "availability", data, own=True).status_code == 400
    hosting.writers["replace_programme_host_availability"].assert_not_called()


def test_owner_period_validation_is_visible_without_claiming_save(hosting):
    confirmed(hosting)
    hosting.writers[
        "replace_programme_host_availability"
    ].side_effect = ValidationError("overlap")
    response = call(hosting, "availability", own_data("availability"), own=True)
    assert response.status_code == 400
    assert b"not saved" in response.content


def test_dormant_routes_resolve_only_when_explicitly_included(hosting):
    path = f"/my/programme/hosting/{hosting.organization}/{hosting.edition}/"
    assert (
        resolve(path, urlconf="maru.programme.host_urls").func
        == personal.personal_programme_hosts
    )
    with pytest.raises(Resolver404):
        resolve(path)


@pytest.mark.parametrize("own", [False, True])
def test_revocation_after_owner_refusal_does_not_echo_pending_private_input(
    hosting, own
):
    task = "invitation" if own else "invite"
    writer = hosting.writers[
        "respond_to_programme_host_invitation" if own else "invite_programme_host"
    ]

    def refuse(**kwargs):
        hosting.auth.side_effect = ProgrammeAuthorizationDeniedError
        if own:
            hosting.readers[
                "load_programme_host_self"
            ].side_effect = ProgrammeAuthorizationDeniedError
        raise ProgrammeVersionConflictError

    writer.side_effect = refuse
    data = own_data() if own else invitation_confirmation(hosting)
    response = call(hosting, task, data, own=own)
    assert response.status_code == 404
    assert b"Explicit invitation" not in response.content
    assert b"Deliberate" not in response.content
    assert b"expected_" not in response.content


def test_missing_exact_invitation_cannot_fall_back_to_older_copy(hosting):
    reader = hosting.readers["load_programme_host_self"]
    reader.return_value = replace(
        reader.return_value,
        invitations=(replace(reader.return_value.invitations[0], sequence=1),),
    )
    response = call(hosting, "invitation", own=True)
    assert response.status_code == 503
    assert b"Deliberate host" not in response.content


def test_working_label_and_roster_must_share_item_version(hosting):
    reader = hosting.readers["load_programme_host_roster"]
    reader.return_value = replace(reader.return_value, item_version=8)
    response = call(hosting)
    assert response.status_code == 503
    assert b"PRIVATE" not in response.content


@pytest.mark.parametrize("own", [False, True])
def test_explicit_destructive_confirmation_is_required(hosting, own):
    confirmed(hosting)
    task = "withdraw-availability" if own else "remove"
    data = own_data(task) if own else manager_data(task)
    data.pop("confirm_withdrawal" if own else "confirm_removal")
    response = call(
        hosting, task, data, own=own, host_id=None if own else hosting.host_id
    )
    assert response.status_code == 400
    for writer in hosting.writers.values():
        writer.assert_not_called()
