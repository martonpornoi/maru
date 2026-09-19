"""P09 response/identity assertions; simulated transport is not native acceptance."""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.rehearsals import programme_onsite_scenario as onsite
from tests.rehearsals.programme_change_scenario import ProgrammeChangeScenarioError
from tests.rehearsals.programme_http_session import ProgrammeHttpResponse
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRehearsalEnvironmentError,
)
from tests.unit.test_programme_change_scenario import _result, _sources


def _response(text, *, status=200, mime="text/html"):
    return ProgrammeHttpResponse(
        status,
        {
            "Content-Type": mime + "; charset=utf-8",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
        text.encode(),
    )


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "status",
        "cache",
        "mime",
        "nosniff",
        "private",
        "utf8",
        "h1",
        "main",
        "text",
    ],
)
def test_actual_response_boundary_and_html_structure(fault):
    text = "<main><h1>Programme</h1><p>Europe/Budapest release-version</p></main>"
    response = _response(text)
    if fault in {"cache", "mime", "nosniff"}:
        key = {
            "cache": "Cache-Control",
            "mime": "Content-Type",
            "nosniff": "X-Content-Type-Options",
        }[fault]
        response.headers[key] = "wrong"
    elif fault == "status":
        response = replace(response, status=503)
    elif fault == "private":
        response = _response(text + onsite.PRIVATE_NOTE)
    elif fault == "utf8":
        response = replace(response, body=b"\xff")
    elif fault == "h1":
        response = _response(text + "<h1>Duplicate</h1>")
    elif fault == "main":
        response = _response(text + '<div role="main"></div>')
    elif fault == "text":
        response = _response(text.replace("release-version", "older"))
    session = Mock()
    session.request.return_value = response
    args = (session, "/programme/")
    kwargs = {"forbidden": (onsite.PRIVATE_NOTE,), "required": ("release-version",)}
    if fault:
        with pytest.raises(onsite.ProgrammeHttpsError):
            onsite._page(*args, **kwargs)
    else:
        assert "release-version" in onsite._page(*args, **kwargs)


@pytest.mark.parametrize(
    "fault",
    [None, "warning", "controls", "release", "calendar", "private_calendar", "zone"],
)
def test_all_six_fresh_formats_preserve_layer_request_and_warning(fault):
    release = "exact-release"
    session = Mock()
    normal = "<main><h1>Programme</h1><p>Europe/Budapest exact-release</p></main>"
    now = normal.replace(
        "</main>",
        "<p>Source checked: Replace/dispose no later than: "
        "Saved copies are historical Complete run sheet "
        "It does not prove attendance</p></main>",
    )
    calendar = (
        "BEGIN:VCALENDAR\r\nX-MARU-RELEASE-ID:exact-release\r\n"
        "CLASS:PRIVATE\r\nEND:VCALENDAR\r\n"
    )
    if fault == "warning":
        now = now.replace("Replace/dispose no later than:", "")
    elif fault == "controls":
        now += "Download signed snapshot"
    elif fault == "release":
        normal = normal.replace(release, "older")
    elif fault == "calendar":
        calendar = calendar.replace(release, "older")
    elif fault == "private_calendar":
        calendar = calendar.replace("CLASS:PRIVATE", "CLASS:PUBLIC")

    def request(path):
        assert "staffing=1" in path
        if "format=calendar" in path:
            return _response(calendar, mime="text/calendar")
        if "format=json" in path:
            return _response(
                json.dumps(
                    {"zone_name": "wrong" if fault == "zone" else "Europe/Budapest"}
                ),
                mime="application/json",
            )
        return _response(now if path.startswith("/now/") else normal)

    session.request.side_effect = request
    kwargs = {
        "forbidden": (),
        "release_id": release,
        "private": True,
        "layers": ("staffing",),
    }
    if fault:
        with pytest.raises(onsite.ProgrammeHttpsError):
            onsite._copies(session, "/timetable/", "/now/", **kwargs)
    else:
        onsite._copies(session, "/timetable/", "/now/", **kwargs)
        assert session.request.call_count == 6
        assert len({call.args[0] for call in session.request.call_args_list}) == 6


def test_deferral_precedes_all_source_or_transport_access(monkeypatch):
    monkeypatch.setattr(
        onsite,
        "require_programme_rehearsal_request",
        Mock(side_effect=ProgrammeRehearsalEnvironmentError("deferred")),
    )
    with pytest.raises(ProgrammeRehearsalEnvironmentError, match="deferred"):
        onsite.verify_onsite_http(*([None] * 9))


@pytest.mark.parametrize(
    "message", ["Signed export is not configured", "Source unavailable"]
)
def test_missing_signing_key_requires_its_own_failure_not_any_503(monkeypatch, message):
    sources = _sources()
    fixture = SimpleNamespace(scenario=sources[0], continuity_trust_policy=None)
    session = Mock()
    session.request.return_value = _response(message, status=503)
    monkeypatch.setattr(onsite, "ProgrammeHttpSession", Mock(return_value=session))
    monkeypatch.setattr(onsite, "require_programme_rehearsal_request", Mock())
    if message == "Source unavailable":
        with pytest.raises(onsite.ProgrammeHttpsError):
            onsite.verify_unsigned_continuity(fixture)
    else:
        onsite.verify_unsigned_continuity(fixture)
    session.cookies.clear.assert_called_once()


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "source",
        "release",
        "public",
        "actor",
        "host",
        "removed",
        "demand",
        "version",
        "work",
        "room",
        "layers",
        "disclosure",
        "logout",
    ],
)
def test_complete_guarded_person_and_exact_scope_composition(monkeypatch, fault):
    sources = _sources()
    setup, _, _, items, planning, physical, staffing, _ = sources
    changed = _result(sources)
    fixture = SimpleNamespace(
        scenario=setup, refresh_workers=Mock(), continuity_trust_policy=None
    )
    session, state = _login_session(physical, fault)
    monkeypatch.setattr(onsite, "require_programme_rehearsal_request", Mock())
    constructor = Mock(return_value=session)
    monkeypatch.setattr(onsite, "ProgrammeHttpSession", constructor)

    def copies(
        _session,
        path,
        now,
        *,
        forbidden,
        release_id,
        private=False,
        layers=(),
        now_rows=None,
    ):
        person = state.person
        assert _session is session
        assert onsite.PRIVATE_NOTE in forbidden
        assert all(
            p.password in forbidden
            for p in (
                items.ceremony_host,
                staffing.volunteer,
                physical.reviewer,
                planning.planner,
            )
        )
        if person is not None:
            assert person.email not in forbidden  # legitimate own shell greeting
        assert now.endswith(("now/", "/"))
        assert now_rows
        result = {
            "state": "available",
            "release_state": "available",
            "release_id": str(changed.release_id),
            "pointer_version": 9 if fault == "release" else 2,
        }
        if path.startswith("/programme/"):
            assert not private
            result["entries"] = [
                {"occurrence_id": str(value)} for value in planning.occurrence_ids
            ]
            if fault == "public":
                result["entries"].pop()
        elif path.startswith("/my/"):
            assert private
            _personal_document(result, sources, changed, person, release_id, fault)
        else:
            assert private
            _operator_document(result, sources, changed, path, layers, fault)
        return result

    copy = Mock(side_effect=copies)
    monkeypatch.setattr(onsite, "_copies", copy)
    if fault == "source":
        changed = replace(changed, edition_id=setup.organization_id)
    if fault:
        with pytest.raises((onsite.ProgrammeHttpsError, ProgrammeChangeScenarioError)):
            onsite.verify_onsite_http(fixture, *sources[1:], changed)
    else:
        onsite.verify_onsite_http(fixture, *sources[1:], changed)
        assert copy.call_count == 6
        assert session.login.call_count == 5
        assert session.logout.call_count == 5
    if fault == "source":
        constructor.assert_not_called()
        fixture.refresh_workers.assert_not_called()
    else:
        session.cookies.clear.assert_called_once()


def _login_session(physical, fault):
    session = Mock()
    state = SimpleNamespace(person=None)

    def login(value, *, destination):
        state.person = value

    def logout():
        state.person = None

    def request(path):
        if path.startswith("/my/") and state.person is None:
            return _response("", status=200 if fault == "logout" else 302)
        status = 503 if "format=pack" in path else 400
        if "technical=1" in path or (
            "/edition/" in path and state.person == physical.reviewer
        ):
            status = 404
        return _response(
            "Signed export is not configured" if status == 503 else "", status=status
        )

    session.login.side_effect = login
    session.logout.side_effect = logout
    session.request.side_effect = request
    return session, state


def _personal_document(result, sources, changed, person, release_id, fault):
    setup, _, _, items, planning, _, staffing, _ = sources
    result["actor_id"] = str(
        setup.edition_id if fault == "actor" else person.account_id
    )
    hosting = dict(result)
    result["hosting"] = hosting
    result["shifts"] = []
    if person == items.ceremony_host:
        hosting["presences"] = [{"occurrence_id": str(planning.occurrence_ids[0])}]
        if fault == "host":
            hosting["presences"] *= 2
        return
    assert release_id is None
    hosting.update(release_id=None, presences=[])
    result["shifts"] = [
        {
            "commitment_id": str(row.commitment_id),
            "version": row.commitment_version,
            "status": "confirmed",
            "instructions": {
                "demand_id": str(row.demand_id),
                "version": row.demand_version,
            },
        }
        for row in (changed.work, *staffing.work[1:])
    ] + [
        {
            "commitment_id": str(changed.predecessor_commitment_id),
            "status": "confirmed" if fault == "removed" else "removed",
            "instructions": {"status": "cancelled"},
        }
    ]
    if fault == "demand":
        result["shifts"][0]["instructions"]["demand_id"] = str(
            changed.predecessor_demand_id
        )
    elif fault == "version":
        result["shifts"][0]["version"] += 1
    elif fault == "work":
        result["shifts"].pop()


def _operator_document(result, sources, changed, path, layers, fault):
    setup, _, _, _, planning, _, staffing, _ = sources
    kind, target = path.rstrip("/").split("/")[-2:]
    occurrences = (
        planning.occurrence_ids[:2] if kind == "room" else planning.occurrence_ids
    )
    result.update(
        scope_kind=kind,
        scope_id=target,
        requested_layers=list(layers),
        staffing=_work_layer(changed, (changed.work, *staffing.work[1:]))
        if layers
        else None,
        entries=[
            {"placement": {"occurrence_id": str(value)}, "delivery": None}
            for value in occurrences
        ],
    )
    if fault == "room":
        result["scope_id"] = str(setup.edition_id)
    elif fault == "layers":
        result["requested_layers"] = ["technical"]
    elif fault == "disclosure":
        result["entries"][0]["delivery"] = {"technical": "private"}


def _work_layer(changed, work):
    return {
        "adopted": True,
        "links": [
            {
                "demand_id": str(row.demand_id),
                "demand_version": row.demand_version,
                "current": True,
            }
            for row in work
        ]
        + [{"demand_id": str(changed.predecessor_demand_id), "current": False}],
        "demands": [
            {"demand_id": str(row.demand_id), "state": "locked"} for row in work
        ]
        + [{"demand_id": str(changed.predecessor_demand_id), "state": "cancelled"}],
    }


@pytest.mark.parametrize(
    "fault", [None, "missing", "unadopted", "link", "version", "history", "state"]
)
def test_explicit_staffing_export_retains_exact_current_and_cancelled_lineage(fault):
    sources = _sources()
    changed = _result(sources)
    work = (changed.work, *sources[6].work[1:])
    layer = _work_layer(changed, work)
    if fault == "missing":
        layer = None
    elif fault == "unadopted":
        layer["adopted"] = False
    elif fault == "link":
        layer["links"].pop()
    elif fault == "version":
        layer["links"][0]["demand_version"] += 1
    elif fault == "history":
        layer["demands"].pop()
    elif fault == "state":
        layer["demands"][-1]["state"] = "locked"
    if fault:
        with pytest.raises(onsite.ProgrammeHttpsError):
            onsite._operator_work(layer, changed, work)
    else:
        onsite._operator_work(layer, changed, work)


@pytest.mark.parametrize(
    "keys", [("public:abc",), ("public:other",), ("public:abc", "public:abc")]
)
def test_continuity_rows_are_exact_not_just_a_release_heading(monkeypatch, keys):
    page = Mock(return_value="Source row: public:abc")
    monkeypatch.setattr(onsite, "_page", page)
    monkeypatch.setattr(
        onsite,
        "_read",
        Mock(
            side_effect=[
                json.dumps({"zone_name": "Europe/Budapest"}),
                "BEGIN:VCALENDAR\r\n",
            ]
        ),
    )
    if keys == ("public:abc",):
        onsite._copies(
            Mock(), "/timetable/", "/now/", forbidden=(), release_id=None, now_rows=keys
        )
    else:
        with pytest.raises(onsite.ProgrammeHttpsError):
            onsite._copies(
                Mock(),
                "/timetable/",
                "/now/",
                forbidden=(),
                release_id=None,
                now_rows=keys,
            )
