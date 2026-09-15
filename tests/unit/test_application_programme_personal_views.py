"""Real personal HTTP adapters with synthetic authority and owner-command seams."""

from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, create_autospec
from uuid import UUID

import pytest
from bs4 import BeautifulSoup
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import QueryDict
from django.test import RequestFactory
from django.urls import Resolver404, resolve

from maru.applications import programme_personal_views as views
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from tests.unit import test_application_programme_proposal_views as intake
from tests.unit.test_application_programme_personal_forms import question

page = intake.page
shell = intake.shell
NOW = datetime(2027, 1, 15, 12, tzinfo=UTC)


@pytest.fixture
def work(page, monkeypatch):
    context = views.personal.ProgrammePersonalWorkflow(
        page.summary,
        2,
        1,
        "active",
        NOW - timedelta(days=1),
        NOW + timedelta(days=1),
        NOW + timedelta(days=2),
        planning=True,
        tracks=page.call.tracks,
        formats=page.call.formats,
        maximum_collaborators=4,
    )
    answer = views.queries.ProgrammeAnswerProjection(
        question("short_text"), UUID(int=701), "My current answer", page.actor, 1
    )
    contributor = views.queries.ProgrammeContributorProjection(
        UUID(int=900),
        "Synthetic collaborator",
        "collaborator",
        UUID(int=901),
        "accepted",
        1,
        invitation_expired=False,
    )
    profile = views.queries.ProgrammeOwnProfileProjection(
        UUID(int=800),
        (("public_name", "My frozen name"),),
        proposed_for_publication=True,
        consent_acknowledged=True,
        consent_policy_code="consent@1",
        resulting_version=1,
    )
    revision = views.queries.ProgrammeRevisionProjection(
        UUID(int=810),
        1,
        None,
        1,
        page.detail.selection.revision_id,
        1,
        "a" * 64,
        NOW - timedelta(hours=1),
        current=True,
        submitted=False,
    )
    frozen = views.personal.ProgrammePersonalFrozenRevision(
        page.summary,
        revision,
        page.detail.selection,
        (replace(answer, value="Exact sealed answer"),),
        UUID(int=820),
        profile,
    )
    detail = replace(
        page.detail,
        answers=(answer,),
        contributors=(contributor,),
        responses=(),
        own_profile=profile,
    )
    state = SimpleNamespace(
        **vars(page),
        context=context,
        answer=answer,
        contributor=contributor,
        frozen=frozen,
        source_detail=detail,
    )

    def read_detail(**values):
        fields = values["requested_fields"]
        return replace(
            state.source_detail,
            requested_fields=fields,
            summary=state.context.summary,
            selection=state.source_detail.selection if "selection" in fields else None,
            answers=state.source_detail.answers if "answers" in fields else None,
            contributors=state.source_detail.contributors
            if "contributors" in fields
            else None,
            own_profile=profile if "contributor_profiles" in fields else None,
            own_profile_requirements=(
                page.call.contributor_fields
                if "contributor_profiles" in fields
                else None
            ),
            contributor_consent_policy_code=(
                page.call.contributor_consent_policy_code
                if "contributor_profiles" in fields
                else None
            ),
            responses=state.source_detail.responses
            if "revision_responses" in fields
            else None,
        )

    state.workflow_reader = Mock(side_effect=lambda **_: state.context)
    state.detail_reader = Mock(side_effect=read_detail)
    state.frozen_reader = Mock(
        side_effect=lambda **_: replace(state.frozen, summary=state.context.summary)
    )
    state.write_auth = Mock(
        side_effect=lambda **_: SimpleNamespace(
            **asdict(state.context.summary),
            accepts_private_planning_writes=state.context.planning,
        )
    )
    state.read_auth = Mock(
        side_effect=lambda **_: SimpleNamespace(**asdict(state.context.summary))
    )
    monkeypatch.setattr(
        views.personal, "get_self_programme_workflow", state.workflow_reader
    )
    monkeypatch.setattr(
        views.queries, "get_self_programme_proposal_detail", state.detail_reader
    )
    monkeypatch.setattr(
        views.personal, "get_self_programme_frozen_revision", state.frozen_reader
    )
    monkeypatch.setattr(views, "authorize_programme_proposal_scope", state.write_auth)
    monkeypatch.setattr(
        intake.views, "authorize_programme_proposal_scope", state.read_auth
    )
    monkeypatch.setattr(views.timezone, "now", lambda: NOW)
    names = {
        *views._SIMPLE_COMMANDS.values(),
        "revise_programme_proposal_selection",
        "revise_programme_contributor_profile",
        "append_programme_proposal_answer",
        "invite_programme_proposal_collaborator",
        "reinvite_programme_proposal_collaborator",
        "remove_programme_proposal_collaborator",
        "respond_to_programme_proposal_revision",
    }
    state.writers = {}
    for name in names:
        writer = create_autospec(
            getattr(views.commands, name),
            return_value=SimpleNamespace(target_id=UUID(int=999)),
        )
        monkeypatch.setattr(views.commands, name, writer)
        state.writers[name] = writer
    return state


def incoming(
    work, action="work", payload=None, *, selected_id=None, query="", csrf=False
):
    path = (
        f"/my/applications/programme/{work.organization}/{work.edition}/"
        f"{work.summary.proposal_id}/work/"
    )
    factory = RequestFactory()
    if payload is None:
        request = factory.get(path + query)
    else:
        values = payload if isinstance(payload, QueryDict) else QueryDict(mutable=True)
        if not isinstance(payload, QueryDict):
            for name, value in payload.items():
                values.setlist(name, value if isinstance(value, list) else [value])
        request = factory.post(
            path + query,
            values.urlencode(),
            content_type="application/x-www-form-urlencoded",
        )
    request.user = SimpleNamespace(pk=work.actor, is_authenticated=True, is_staff=False)
    request._dont_enforce_csrf_checks = not csrf
    return views.programme_personal_tasks(
        request,
        work.organization,
        work.edition,
        work.summary.proposal_id,
        action=action,
        selected_id=selected_id,
    )


def evidence(work, **extra):
    return {
        "expected_version": str(work.context.summary.aggregate_version),
        "expected_call_version": str(work.context.call_version),
        "expected_definition_version": str(work.context.definition_version),
        "retry_key": str(UUID(int=9999)),
        "reason": "My deliberate change",
        "confirm": "on",
    } | extra


def set_state(work, *, role="lead", state="draft", **context):
    work.context = replace(
        work.context,
        summary=replace(
            work.context.summary,
            relationship=role,
            state=state,
            sealed_revision_id=work.frozen.revision.revision_id
            if state != "draft"
            else None,
        ),
        **context,
    )


CASES = [
    ("selection", "lead", "draft", "revise_programme_proposal_selection"),
    ("profile", "lead", "draft", "revise_programme_contributor_profile"),
    ("answer", "collaborator", "draft", "append_programme_proposal_answer"),
    ("invite", "lead", "draft", "invite_programme_proposal_collaborator"),
    ("reinvite", "lead", "draft", "reinvite_programme_proposal_collaborator"),
    ("remove", "lead", "draft", "remove_programme_proposal_collaborator"),
    ("accept-invitation", "invited", "draft", "accept_programme_proposal_invitation"),
    ("decline-invitation", "invited", "draft", "decline_programme_proposal_invitation"),
    ("leave", "collaborator", "draft", "leave_programme_proposal"),
    ("seal", "lead", "draft", "seal_programme_proposal"),
    ("reopen", "lead", "sealed", "reopen_programme_proposal"),
    ("acknowledge", "collaborator", "sealed", "respond_to_programme_proposal_revision"),
    (
        "decline-revision",
        "collaborator",
        "sealed",
        "respond_to_programme_proposal_revision",
    ),
    ("submit", "lead", "sealed", "submit_programme_proposal"),
    ("withdraw", "lead", "submitted", "withdraw_programme_proposal"),
]


def task_input(work, action):
    extra, selected_id = {}, None
    if action == "selection":
        extra = {
            "track": str(work.call.tracks[0].track_id),
            "format": str(work.call.formats[0].format_id),
            "duration": "30",
        }
    if action == "profile":
        extra = {"publication_choice": "no"}
    if action in {"invite", "reinvite"}:
        extra = {
            "email": "known@example.invalid",
            "expires_at": "2027-01-15T18:00+02:00",
        }
    if action == "answer":
        extra, selected_id = (
            {"value": "My revised answer"},
            work.answer.question.question_id,
        )
    if action == "remove":
        selected_id = work.contributor.collaborator_id
    if action in views._RESPONSE_TASKS:
        extra = {
            name: str(value)
            for name, value in views._response_proofs(work.frozen).items()
        }
    if action == "submit":
        extra = {"revision_id": str(work.frozen.revision.revision_id)}
    return evidence(work, **extra), selected_id


@pytest.mark.parametrize(("action", "role", "state", "command"), CASES)
def test_each_task_real_form_and_exact_existing_owner_command(
    work, action, role, state, command
):
    set_state(work, role=role, state=state)
    data, selected = task_input(work, action)
    response = incoming(work, action, selected_id=selected)
    assert response.status_code == 200
    soup = BeautifulSoup(response.content, "html.parser")
    assert len(soup.find_all("h1")) == 1
    assert soup.select_one("form[data-call-command]")
    assert "no-store" in response["Cache-Control"]
    assert "form-action 'self'" in response["Content-Security-Policy"]
    assert not any(writer.called for writer in work.writers.values())
    response = incoming(work, action, data, selected_id=selected)
    assert response.status_code == 302, response.content
    writer = work.writers[command]
    assert writer.call_count == 1
    values = writer.call_args.kwargs
    assert values["actor_id"] == work.actor
    assert values["organization_id"] == work.organization
    assert values["edition_id"] == work.edition
    assert values["proposal_id"] == work.summary.proposal_id
    assert values["retry_key"] == UUID(int=9999)
    assert values["expected_version"] == work.context.summary.aggregate_version
    assert str(UUID(int=999)) not in response["Location"]
    assert response["Location"].endswith(
        f"{work.edition}/"
        if action in {"leave", "decline-invitation"}
        else f"{work.summary.proposal_id}/work/"
    )
    if action in views._RESPONSE_TASKS:
        assert (
            values["response"].profile_revision_id
            == work.frozen.own_profile.profile_revision_id
        )
        assert values["response"].decision == (
            "acknowledged" if action == "acknowledge" else "declined"
        )
    if action == "remove":
        assert values["collaborator_id"] == work.contributor.collaborator_id


@pytest.mark.parametrize(
    "proof",
    ["expected_version", "expected_call_version", "expected_definition_version"],
)
def test_stale_bound_proofs_and_input_are_not_rebased(work, proof):
    data = evidence(work, value="Retain my edit", **{proof: "99"})
    response = incoming(
        work, "answer", data, selected_id=work.answer.question.question_id
    )
    assert response.status_code == 409
    soup = BeautifulSoup(response.content, "html.parser")
    assert soup.select_one(f'[name="{proof}"]')["value"] == "99"
    assert "Retain my edit" in response.content.decode()
    assert soup.select_one('[name="retry_key"]')["value"] == data["retry_key"]
    assert not any(writer.called for writer in work.writers.values())


@pytest.mark.parametrize(
    "proof", ["revision_id", "contributor_id", "profile_revision_id"]
)
def test_response_requires_all_three_original_frozen_identities(work, proof):
    set_state(work, role="collaborator", state="sealed")
    data, _ = task_input(work, "acknowledge")
    data[proof] = str(UUID(int=123456))
    response = incoming(work, "acknowledge", data)
    assert response.status_code == 409
    assert data[proof] in response.content.decode()
    assert not work.writers["respond_to_programme_proposal_revision"].called


def test_exact_seal_not_current_answer_or_other_profile_is_rendered(work):
    set_state(work, role="collaborator", state="sealed")
    response = incoming(work, "acknowledge")
    text = response.content.decode()
    assert response.status_code == 200
    assert "Exact sealed answer" in text
    assert "My current answer" not in text
    assert "My frozen name" in text
    assert "Synthetic collaborator" not in text
    assert str(work.frozen.own_profile.profile_revision_id) in text


@pytest.mark.parametrize(
    ("action", "role"), [("acknowledge", "collaborator"), ("submit", "lead")]
)
def test_response_window_remains_open_after_edit_deadline(work, action, role):
    set_state(work, role=role, state="sealed", edit_until=NOW - timedelta(seconds=1))
    data, _ = task_input(work, action)
    assert incoming(work, action, data).status_code == 302
    set_state(work, role=role, state="sealed", closes_at=NOW)
    assert incoming(work, action, data).status_code == 409


def test_inclusive_edit_and_independent_withdrawal_windows(work):
    set_state(work, edit_until=NOW)
    data, _ = task_input(work, "profile")
    assert incoming(work, "profile", data).status_code == 302
    set_state(work, edit_until=NOW - timedelta(seconds=1))
    assert incoming(work, "profile", data).status_code == 409
    set_state(
        work,
        state="submitted",
        call_status="retired",
        closes_at=NOW - timedelta(days=1),
    )
    assert incoming(work, "withdraw", evidence(work)).status_code == 302


@pytest.mark.parametrize("action", ["work", "profile", "answer", "accept-invitation"])
def test_unknown_transport_refused_before_owner_queries(work, action):
    selected = work.answer.question.question_id if action == "answer" else None
    response = incoming(
        work, action, evidence(work, actor_id=str(UUID(int=123))), selected_id=selected
    )
    assert response.status_code == 400
    work.workflow_reader.assert_not_called()


@pytest.mark.parametrize(
    "extra", [{"reason": ["first", "second"]}, {"value": "x" * 65537}]
)
def test_transport_bounds_and_scalar_duplicates_fail_early(work, extra):
    assert (
        incoming(
            work,
            "answer",
            evidence(work, **extra),
            selected_id=work.answer.question.question_id,
        ).status_code
        == 400
    )
    work.workflow_reader.assert_not_called()


def test_multiple_values_only_for_exact_authorized_multiple_choice_question(work):
    data = evidence(work, value=["talk", "panel"])
    assert (
        incoming(
            work, "answer", data, selected_id=work.answer.question.question_id
        ).status_code
        == 400
    )
    spec = question("multiple_choice")
    work.source_detail = replace(
        work.source_detail, answers=(replace(work.answer, question=spec),)
    )
    assert (
        incoming(work, "answer", data, selected_id=spec.question_id).status_code == 302
    )
    assert work.writers["append_programme_proposal_answer"].call_args.kwargs[
        "value"
    ] == ["talk", "panel"]


def test_invitee_never_requests_shared_answers_roster_or_profiles(work):
    set_state(work, role="invited")
    response = incoming(work)
    assert response.status_code == 200
    assert work.detail_reader.call_args.kwargs[
        "requested_fields"
    ] == views._BASE_FIELDS | {"selection", "own_invitation"}
    assert "My current answer" not in response.content.decode()
    assert "Synthetic collaborator" not in response.content.decode()
    work.frozen_reader.assert_not_called()


@pytest.mark.parametrize("stage", ["read", "write", "late-render", "late-source"])
def test_independent_and_late_denial_discards_prepared_private_content(
    work, monkeypatch, stage
):
    if stage == "read":
        work.workflow_reader.side_effect = Denied
    elif stage == "write":
        work.write_auth.side_effect = Denied
    elif stage == "late-source":
        work.workflow_reader.side_effect = [
            work.context,
            replace(work.context, call_version=3),
        ]
    else:
        render = intake.views.render_to_string

        def revoked(*args, **kwargs):
            content = render(*args, **kwargs)
            work.read_auth.side_effect = Denied
            return content

        monkeypatch.setattr(intake.views, "render_to_string", revoked)
    response = incoming(work, "profile")
    assert response.status_code == 404
    assert "My frozen name" not in response.content.decode()
    assert not any(writer.called for writer in work.writers.values())


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (views.commands.ApplicationsProgrammeCompletenessError(), 400),
        (views.commands.ApplicationsProgrammeStateConflictError(), 409),
        (ValidationError("Correct the answer"), 400),
        (DatabaseError(), 503),
        (Denied(), 404),
    ],
)
def test_owner_failures_are_actionable_without_claiming_uncertain_failure(
    work, error, status
):
    work.writers["seal_programme_proposal"].side_effect = error
    response = incoming(work, "seal", evidence(work))
    assert response.status_code == status
    if status in {503, 404}:
        assert "may" in response.content.decode()
        assert "committed" in response.content.decode()
        assert "My current answer" not in response.content.decode()


def test_csrf_and_readonly_gets_cannot_mutate(work):
    assert incoming(work, "withdraw", evidence(work), csrf=True).status_code == 403
    work.workflow_reader.assert_not_called()
    assert incoming(work, "work", evidence(work)).status_code == 400
    assert incoming(work, query="?actor=other").status_code == 400


@pytest.mark.parametrize("kind", ["person_reference", "domain_reference", "safe_file"])
def test_reference_question_never_uses_a_raw_identifier_editor(work, kind):
    spec = question(kind)
    work.source_detail = replace(
        work.source_detail, answers=(replace(work.answer, question=spec),)
    )
    response = incoming(work)
    assert response.status_code == 200
    html = response.content.decode()
    if kind == "person_reference":
        assert f"answer/{spec.question_id}/person/" in html
        assert "Select or clear person" in html
    else:
        assert "An authorized reference or file chooser is still needed" in html
        assert f"answer/{spec.question_id}/" not in html
    assert incoming(work, "answer", selected_id=spec.question_id).status_code == 404


@pytest.mark.parametrize(
    "field", ["actor_id", "track", "email", "revision_id", "hidden_biography"]
)
def test_unrelated_or_hidden_input_cannot_be_smuggled_into_answer_task(work, field):
    response = incoming(
        work,
        "answer",
        evidence(work, value="Retain", **{field: "injected"}),
        selected_id=work.answer.question.question_id,
    )
    assert response.status_code == 400
    assert not any(writer.called for writer in work.writers.values())


def test_current_own_profile_values_have_no_implicit_consent(work):
    response = incoming(work, "profile")
    soup = BeautifulSoup(response.content, "html.parser")
    assert soup.select_one('[name="public_name"]')["value"] == "My frozen name"
    assert not soup.select_one('[name="consent_acknowledged"]').has_attr("checked")
    assert (
        soup.select_one('[name="publication_choice"] option[selected]')["value"] == ""
    )


@pytest.mark.parametrize(
    "change", ["summary", "fields", "frozen-summary", "foreign-proposal"]
)
def test_mismatched_owner_projection_is_never_rendered(work, change):
    set_state(work, state="sealed")
    detail = work.detail_reader.side_effect
    if change == "summary":
        work.detail_reader.side_effect = lambda **values: replace(
            detail(**values),
            summary=replace(work.context.summary, aggregate_version=999),
        )
    elif change == "fields":
        work.detail_reader.side_effect = lambda **values: replace(
            detail(**values), requested_fields=frozenset({"answers"})
        )
    elif change == "frozen-summary":
        work.frozen_reader.side_effect = None
        work.frozen_reader.return_value = replace(
            work.frozen,
            summary=replace(work.context.summary, relationship="collaborator"),
        )
    else:
        work.context = replace(
            work.context,
            summary=replace(work.context.summary, proposal_id=UUID(int=456)),
        )
    response = incoming(work, "frozen")
    assert response.status_code == 404
    assert "Exact sealed answer" not in response.content.decode()


def test_submit_rejects_missing_or_changed_exact_seal(work):
    set_state(work, state="sealed")
    assert incoming(work, "submit", evidence(work)).status_code == 400
    assert (
        incoming(
            work, "submit", evidence(work, revision_id=str(UUID(int=333)))
        ).status_code
        == 409
    )
    assert not work.writers["submit_programme_proposal"].called


def test_completed_current_response_is_not_offered_as_a_new_decision(work):
    set_state(work, role="collaborator", state="sealed")
    work.source_detail = replace(
        work.source_detail,
        responses=(
            views.queries.ProgrammeRevisionResponseProjection(
                work.frozen.revision.revision_id,
                work.frozen.own_contributor_id,
                work.actor,
                "acknowledged",
                NOW,
            ),
        ),
    )
    response = incoming(work)
    soup = BeautifulSoup(response.content, "html.parser")
    assert not soup.select('a[href$="/acknowledge/"]')
    assert not soup.select('a[href$="/decline-revision/"]')
    assert "acknowledged" in soup.get_text()
    confirmation = incoming(work, "acknowledge")
    assert (
        BeautifulSoup(confirmation.content, "html.parser")
        .select_one('form[data-call-command] button[type="submit"]')
        .has_attr("disabled")
    )


def test_retired_call_and_closed_planning_keep_readonly_history(work):
    set_state(work, call_status="retired", planning=False)
    response = incoming(work)
    assert response.status_code == 200
    assert "My current answer" in response.content.decode()
    assert "Private planning is closed" in response.content.decode()
    assert not BeautifulSoup(response.content, "html.parser").select(
        'a[href$="withdraw/"]'
    )


def test_html_sensitive_labels_are_escaped(work):
    work.source_detail = replace(
        work.source_detail,
        answers=(replace(work.answer, value='<script>alert("unsafe")</script>'),),
    )
    response = incoming(work)
    assert b"&lt;script&gt;" in response.content
    assert b'<script>alert("unsafe")</script>' not in response.content


@pytest.mark.parametrize("action", [*views._ACTIONS, "work", "frozen"])
def test_explicit_routes_resolve_only_in_dormant_url_module(work, action):
    url = (
        f"/my/applications/programme/{work.organization}/{work.edition}/"
        f"{work.summary.proposal_id}/work/"
    )
    if action != "work":
        url += action + "/"
    if action in {"answer", "remove"}:
        url += str(UUID(int=42)) + "/"
    found = resolve(url, urlconf="maru.applications.programme_proposal_urls")
    assert found.func is views.programme_personal_tasks
    with pytest.raises(Resolver404):
        resolve(url)
