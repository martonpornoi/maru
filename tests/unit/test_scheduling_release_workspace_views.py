"""Real native release templates and dispatch; owner substitutions do not prove SQL."""

from dataclasses import replace
from datetime import UTC, datetime
from html import escape
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from django.db import DatabaseError
from django.test import RequestFactory

from maru.scheduling import release_workspace as workspace
from maru.scheduling import release_workspace_views as views
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.catalogs import SchedulingConflictSeverity as Severity
from maru.scheduling.command_support import (
    SchedulingCommandResult,
    SchedulingIdempotencyConflictError,
    SchedulingUnavailableError,
    SchedulingVersionConflictError,
)
from maru.scheduling.planning_queries import PlanningCandidate
from maru.scheduling.release_eligibility import (
    ReleaseCheck,
    ReleaseCheckEvidence,
    ReleaseCheckState,
    ReleaseEligibility,
)
from maru.scheduling.release_preflight import (
    ReleasePreflightFinding,
    SchedulingReleasePreflight,
)
from maru.scheduling.release_workspace_queries import (
    ReleaseApprovalChoice,
    ReleaseApprovalPage,
    ReleaseHistoryPage,
    ReleasePointerObservation,
    ReleaseWarningChoice,
)
from maru.scheduling.workspace_navigation import ProgrammeWorkspaceLink
from tests.unit.test_scheduling_release_workspace_forms import release_post


@pytest.fixture
def release_http(monkeypatch):
    actor, organization, series, edition = (uuid4() for _ in range(4))
    candidate = PlanningCandidate(
        uuid4(), uuid4(), 3, "<script>Private draft</script>", "draft", 1
    )
    digest = "a" * 64
    preflight = SchedulingReleasePreflight(
        candidate.revision_id,
        digest,
        tuple(
            ReleaseCheckEvidence(digest, check, ReleaseCheckState.SATISFIED)
            for check in ReleaseCheck
        ),
        (),
        ReleaseEligibility(digest, (), (), (), (), (), ()),
    )
    now = datetime(2030, 8, 1, 10, tzinfo=UTC)
    approval = ReleaseApprovalChoice(
        uuid4(), candidate, digest, uuid4(), "Reviewed <script>unsafe</script>", now
    )
    denied = set()
    policies = []
    state = SimpleNamespace(writable=True)

    def authorize(**kwargs):
        policies.append(kwargs)
        if (
            kwargs["capability_code"] in denied
            or (kwargs["capability_code"], kwargs.get("requested_fields")) in denied
        ):
            raise SchedulingAuthorizationDeniedError
        return SimpleNamespace(accepts_writes=state.writable)

    monkeypatch.setattr(workspace, "authorize_scheduling_scope", authorize)
    monkeypatch.setattr(
        views, "resolve_edition_series_identity", Mock(return_value=series)
    )
    monkeypatch.setattr(views.admin.site, "each_context", lambda _request: {})
    sources = {}
    for name, value in {
        "list_release_candidates": (candidate,),
        "load_release_preflight": preflight,
        "list_release_warning_evidence": (),
        "list_release_approvals": ReleaseApprovalPage((approval,), None),
        "load_release_approval": approval,
        "load_release_pointer": ReleasePointerObservation(uuid4(), 4),
        "list_release_history": ReleaseHistoryPage((), None),
    }.items():
        sources[name] = Mock(return_value=value)
        monkeypatch.setattr(workspace, name, sources[name])
    result = SchedulingCommandResult(uuid4(), uuid4(), 5, 20)
    commands = {}
    for action, name in {
        "acknowledge": "acknowledge_programme_release_warning",
        "approve": "approve_programme_release",
        "publish": "publish_programme_release",
        "withdraw": "withdraw_programme_release",
    }.items():
        commands[action] = Mock(return_value=result)
        monkeypatch.setattr(views, name, commands[action])
    return SimpleNamespace(
        actor=actor,
        organization=organization,
        series=series,
        edition=edition,
        candidate=candidate,
        preflight=preflight,
        approval=approval,
        now=now,
        denied=denied,
        policies=policies,
        state=state,
        sources=sources,
        result=result,
        commands=commands,
    )


def request_release(
    world, *, task=None, data=None, path="/rehearsal/release/", csrf=False
):
    request = (
        RequestFactory().post(path, data)
        if data is not None
        else RequestFactory().get(path)
    )
    request.user = SimpleNamespace(
        pk=world.actor, is_authenticated=True, is_active=True, is_staff=True
    )
    request._dont_enforce_csrf_checks = not csrf
    return views.programme_release_workspace(
        request,
        organization_id=world.organization,
        series_id=world.series,
        edition_id=world.edition,
        task=task,
    )


def inspect_post(world):
    return {"action": "inspect", "candidate_id": str(world.candidate.id)}


def test_task_navigation_is_independently_admitted_and_has_one_shell(release_http):
    world = release_http
    response = request_release(world)
    text = response.content.decode()
    assert response.status_code == 200
    assert text.count("<h1>") == 1
    assert text.count("<main ") == 1
    assert "Review a private candidate" in text
    assert "Release and withdrawal history" in text
    assert "no-store" in response["Cache-Control"]
    assert "frame-ancestors 'none'" in response["Content-Security-Policy"]
    for source in world.sources.values():
        source.assert_not_called()
    world.denied.add("scheduling.view_history")
    text = request_release(world).content.decode()
    assert "Review a private candidate</a>" not in text
    assert "Publish an approved timetable</a>" not in text
    assert "Withdraw the active timetable</a>" in text


def test_complete_preflight_uses_exact_current_candidate_and_escapes_it(release_http):
    world = release_http
    response = request_release(world, task="review", data=inspect_post(world))
    text = response.content.decode()
    assert response.status_code == 200
    assert "&lt;script&gt;Private draft&lt;/script&gt;" in text
    assert "<script>Private draft" not in text
    assert "Approve this exact timetable" in text
    assert text.count("<h1>") == 1
    for label, _guidance in workspace.CHECK_GUIDANCE.values():
        assert escape(label) in text
    assert world.sources["load_release_preflight"].call_count == 2
    selection = world.sources["load_release_preflight"].call_args.kwargs
    assert selection == {
        "candidate_id": world.candidate.id,
        "candidate_revision_id": world.candidate.revision_id,
        "expected_candidate_version": 3,
    }
    assert f'value="{world.preflight.snapshot_digest}"' in text
    for command in world.commands.values():
        command.assert_not_called()


@pytest.mark.parametrize(
    "state",
    [ReleaseCheckState.BLOCKED, ReleaseCheckState.UNAVAILABLE, ReleaseCheckState.STALE],
)
def test_unresolved_category_never_offers_approval(release_http, state):
    world = release_http
    checks = list(world.preflight.checks)
    checks[0] = replace(checks[0], state=state)
    world.sources["load_release_preflight"].return_value = replace(
        world.preflight, checks=tuple(checks)
    )
    response = request_release(world, task="review", data=inspect_post(world))
    assert response.status_code == 200
    assert "Approve this exact timetable</button>" not in response.content.decode()
    assert "Independent approval is not available" in response.content.decode()


def test_exact_warning_reason_is_required_before_approval(release_http):
    world = release_http
    finding = ReleasePreflightFinding(
        ReleaseCheck.HOSTS,
        "host_outside_preference",
        Severity.WARNING,
        uuid4(),
        None,
        "b" * 64,
    )
    world.sources["load_release_preflight"].return_value = replace(
        world.preflight, findings=(finding,)
    )
    response = request_release(world, task="review", data=inspect_post(world))
    assert "Acknowledge this release warning</button>" in response.content.decode()
    assert "Approve this exact timetable</button>" not in response.content.decode()
    evidence = ReleaseWarningChoice(
        uuid4(),
        finding.fingerprint,
        finding.check.value,
        finding.code,
        world.actor,
        "<img src=x> agreed exception",
        world.now,
    )
    world.sources["list_release_warning_evidence"].return_value = (evidence,)
    response = request_release(world, task="review", data=inspect_post(world))
    assert response.status_code == 200
    assert "Approve this exact timetable</button>" in response.content.decode()
    assert "&lt;img src=x&gt; agreed exception" in response.content.decode()
    assert str(evidence.id) in response.content.decode()
    world.sources["list_release_warning_evidence"].return_value = (
        replace(evidence, code="wrong"),
    )
    response = request_release(world, task="review", data=inspect_post(world))
    assert response.status_code == 503
    assert b"agreed exception" not in response.content


@pytest.mark.parametrize(
    ("action", "task"),
    [
        ("approve", "review"),
        ("acknowledge", "review"),
        ("publish", "publish"),
        ("withdraw", "withdraw"),
    ],
)
def test_original_command_reaches_receipt_without_any_fresh_private_source(
    release_http, action, task, monkeypatch
):
    world = release_http
    links = (
        ProgrammeWorkspaceLink("items", "Programme items", "/optional-items/"),
        ProgrammeWorkspaceLink(
            "applications", "Programme applications", "/application-entry/"
        ),
    )
    monkeypatch.setattr(
        views,
        "programme_workspace_links",
        Mock(side_effect=[links, (), links, ()]),
    )
    for source in world.sources.values():
        source.side_effect = AssertionError("No private source refresh before receipt")
    world.denied.update(
        {
            "scheduling.view_planning",
            "scheduling.view_history",
            "scheduling.view_conflicts",
        }
    )
    world.state.writable = False
    data = release_post(action)
    response = request_release(world, task=task, data=data)
    assert response.status_code == 200, response.content
    command = world.commands[action]
    command.assert_called_once()
    request = command.call_args.args[0]
    assert request.actor_id == world.actor
    assert request.organization_id == world.organization
    assert request.edition_id == world.edition
    assert request.idempotency_key == UUID(data["retry_key"])
    assert request.reason == data["reason"]
    intent = command.call_args.kwargs["intent"]
    if action in {"approve", "acknowledge"}:
        assert intent.selection.expected_candidate_version == 3
        assert intent.selection.candidate_revision_id == UUID(
            data["candidate_revision_id"]
        )
    if action == "publish":
        assert intent.expected_release_version == 0
        assert intent.expected_active_release_id is None
    assert str(world.result.receipt_id).encode() in response.content
    assert b"/optional-items/" not in response.content
    assert b"/application-entry/" not in response.content
    for source in world.sources.values():
        source.assert_not_called()
    command.return_value = replace(world.result, replayed=True)
    repeated = request_release(world, task=task, data=data)
    assert repeated.status_code == 200
    assert b"Previously completed action confirmed" in repeated.content
    assert command.call_args.args[0].idempotency_key == request.idempotency_key


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (SchedulingVersionConflictError(), 409),
        (SchedulingIdempotencyConflictError(), 409),
        (DatabaseError(), 503),
        (SchedulingUnavailableError(), 503),
    ],
)
def test_failure_retains_original_input_without_automatically_rebasing(
    release_http, error, status, monkeypatch
):
    world = release_http
    links = (
        ProgrammeWorkspaceLink(
            "applications", "Programme applications", "/application-entry/"
        ),
    )
    monkeypatch.setattr(
        views, "programme_workspace_links", Mock(side_effect=[links, (), links, ()])
    )
    data = release_post("publish")
    world.commands["publish"].side_effect = error
    response = request_release(world, task="publish", data=data)
    assert response.status_code == status
    assert b"/application-entry/" not in response.content
    text = response.content.decode()
    for value in (
        data["reason"],
        data["retry_key"],
        data["approval_id"],
        data["source_snapshot_digest"],
    ):
        assert value in text
    assert 'data-release-pending="true"' in text
    assert 'name="expected_release_version" value="0"' in text
    for source in world.sources.values():
        source.assert_not_called()


@pytest.mark.parametrize(
    "source",
    [
        "list_release_candidates",
        "load_release_preflight",
        "list_release_warning_evidence",
    ],
)
def test_final_source_or_audit_failure_discards_the_entire_rendered_page(
    release_http, source
):
    world = release_http
    loader = world.sources[source]
    loader.side_effect = [loader.return_value, SchedulingUnavailableError()]
    response = request_release(world, task="review", data=inspect_post(world))
    assert response.status_code == 503
    assert b"Private draft" not in response.content
    assert b"<form" not in response.content


def test_post_render_permission_revocation_discards_receipt_and_private_context(
    release_http, monkeypatch
):
    world = release_http
    original = views._html

    def revoke(*args, **kwargs):
        response = original(*args, **kwargs)
        world.denied.add("scheduling.publish_release")
        return response

    monkeypatch.setattr(views, "_html", revoke)
    response = request_release(world, task="publish", data=release_post("publish"))
    assert response.status_code == 403
    assert str(world.result.receipt_id).encode() not in response.content
    world.commands["publish"].assert_called_once()


def test_publication_keeps_approval_and_withdrawal_needs_no_content(
    release_http,
):
    world = release_http
    response = request_release(
        world,
        task="publish",
        data={"action": "prepare", "approval_id": str(world.approval.id)},
    )
    assert response.status_code == 200
    assert b"&lt;script&gt;unsafe&lt;/script&gt;" in response.content
    assert f'value="{world.approval.snapshot_digest}"'.encode() in response.content
    world.sources["load_release_preflight"].assert_not_called()
    world.sources["list_release_candidates"].assert_not_called()
    response = request_release(world, task="withdraw")
    assert response.status_code == 200
    assert b"Withdraw this active timetable</button>" in response.content
    assert b"does not verify safe content" in response.content
    world.denied.add("scheduling.withdraw_release")
    response = request_release(world, task="withdraw")
    assert response.status_code == 200
    assert b"Withdraw this active timetable</button>" not in response.content


def test_csrf_wrong_series_and_closed_routing_prevent_dispatch(release_http):
    world = release_http
    assert (
        request_release(
            world, task="publish", data=release_post("publish"), csrf=True
        ).status_code
        == 403
    )
    assert (
        request_release(world, task="review", data=release_post("publish")).status_code
        == 400
    )
    assert (
        request_release(
            world, task="withdraw", path="/rehearsal/?private=secret"
        ).status_code
        == 400
    )
    original_series = world.series
    world.series = uuid4()
    assert request_release(world, task="withdraw").status_code == 403
    world.series = original_series
    for command in world.commands.values():
        command.assert_not_called()


@pytest.mark.parametrize("task", workspace.TASK_LABELS)
def test_each_task_denies_its_exact_field_before_loading_sources(release_http, task):
    world = release_http
    capability, fields = workspace.TASK_READS[task][-1]
    world.denied.add((capability, fields))
    response = request_release(world, task=task)
    assert response.status_code == 403
    for source in world.sources.values():
        source.assert_not_called()
    assert b"Private draft" not in response.content


@pytest.mark.parametrize(
    "problem",
    ["missing_category", "duplicate_category", "wrong_revision", "duplicate_finding"],
)
def test_incomplete_or_incoherent_preflight_is_never_partially_rendered(
    release_http, problem
):
    world = release_http
    preflight = world.preflight
    if problem == "missing_category":
        preflight = replace(preflight, checks=preflight.checks[:-1])
    elif problem == "duplicate_category":
        preflight = replace(
            preflight, checks=(*preflight.checks[:-1], preflight.checks[0])
        )
    elif problem == "wrong_revision":
        preflight = replace(preflight, candidate_revision_id=uuid4())
    else:
        finding = ReleasePreflightFinding(
            ReleaseCheck.HOSTS,
            "host_outside_preference",
            Severity.WARNING,
            None,
            None,
            "b" * 64,
        )
        preflight = replace(preflight, findings=(finding, finding))
    world.sources["load_release_preflight"].return_value = preflight
    response = request_release(world, task="review", data=inspect_post(world))
    assert response.status_code == 503
    assert b"Private draft" not in response.content


@pytest.mark.parametrize(
    ("pointer", "message"),
    [
        (ReleasePointerObservation(None, 0), "No timetable has been published"),
        (ReleasePointerObservation(None, 8), "active timetable was withdrawn"),
    ],
)
def test_absent_and_withdrawn_pointer_offer_no_withdrawal(
    release_http, pointer, message
):
    world = release_http
    world.sources["load_release_pointer"].return_value = pointer
    response = request_release(world, task="withdraw")
    assert response.status_code == 200
    assert message.encode() in response.content
    assert b"Withdraw this active timetable</button>" not in response.content


@pytest.mark.parametrize("change", [{"lifecycle": "archived"}, {"placement_count": 0}])
def test_empty_or_archived_candidate_has_actionable_read_only_state(
    release_http, change
):
    world = release_http
    world.sources["list_release_candidates"].return_value = (
        replace(world.candidate, **change),
    )
    response = request_release(world, task="review", data=inspect_post(world))
    assert response.status_code == 200
    assert b"Select a nonempty current draft" in response.content
    assert b"Approve this exact timetable</button>" not in response.content
    world.sources["load_release_preflight"].assert_not_called()
