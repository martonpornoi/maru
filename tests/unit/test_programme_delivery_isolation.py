"""P12 verifier fault injection is not native or representative-person evidence."""

import ast
import io
import json
from itertools import combinations
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest

from tests.rehearsals import programme_delivery_authority as authority
from tests.rehearsals import programme_delivery_isolation as isolation
from tests.rehearsals.programme_http_session import ProgrammeHttpResponse
from tests.rehearsals.programme_https import ProgrammeHttpsError
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRehearsalEnvironmentError,
)
from tests.unit.test_programme_change_scenario import _result, _sources


def _output(planning, changed, *, layers=("technical",)):
    return {
        "release_state": "available",
        "release_id": str(changed.release_id),
        "pointer_version": changed.pointer_version,
        "scope_kind": "room",
        "scope_id": str(planning.room_ids[0]),
        "requested_layers": sorted(layers),
        "staffing": None,
        "entries": [
            {
                "placement": {"occurrence_id": str(occurrence), "item_id": str(item)},
                "delivery": {
                    "item_id": str(item),
                    "revision_id": str(uuid4()),
                    "version": 2,
                    "occurred_at": "2026-09-21T12:00:00+00:00",
                    "checked_at": "2026-09-21T12:01:00+00:00",
                    **{field: isolation.INSTRUCTIONS[field] for field in layers},
                }
                if layers
                else None,
            }
            for occurrence, item in zip(
                planning.occurrence_ids[:2], planning.item_ids, strict=True
            )
        ],
    }


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "state",
        "release",
        "pointer",
        "scope",
        "layers",
        "staffing",
        "extra_row",
        "missing_row",
        "wrong_occurrence",
        "private",
        "extra_field",
        "missing_field",
        "wrong_text",
        "item",
        "version",
        "revision",
        "time",
        "unrequested",
    ],
)
def test_current_exact_scope_and_field_contract_rejects_corruption(fault):
    sources = _sources()
    planning, changed = sources[4], _result(sources)
    layers = () if fault == "unrequested" else ("technical",)
    document = _output(planning, changed, layers=layers)
    delivery = document["entries"][0]["delivery"]
    if fault in {"state", "release", "pointer", "scope", "layers", "staffing"}:
        key, value = {
            "state": ("release_state", "withdrawn"),
            "release": ("release_id", str(uuid4())),
            "pointer": ("pointer_version", 1),
            "scope": ("scope_id", str(planning.room_ids[1])),
            "layers": ("requested_layers", []),
            "staffing": ("staffing", {}),
        }[fault]
        document[key] = value
    elif fault == "extra_row":
        document["entries"].append(document["entries"][0])
    elif fault == "missing_row":
        document["entries"].pop()
    elif fault == "wrong_occurrence":
        document["entries"][0]["placement"]["occurrence_id"] = str(uuid4())
    elif fault == "private":
        document["hidden"] = isolation.PRIVATE_NOTE
    elif fault == "extra_field":
        delivery["media"] = isolation.INSTRUCTIONS["media"]
    elif fault == "missing_field":
        delivery.pop("technical")
    elif fault in {"wrong_text", "item", "version", "revision", "time"}:
        key, value = {
            "wrong_text": ("technical", "unverified current instruction"),
            "item": ("item_id", str(uuid4())),
            "version": ("version", 1),
            "revision": ("revision_id", None),
            "time": ("checked_at", None),
        }[fault]
        delivery[key] = value
    elif fault == "unrequested":
        document["entries"][0]["delivery"] = {}
    session = Mock()
    session.request.return_value = ProgrammeHttpResponse(
        200,
        {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
        json.dumps(document).encode(),
    )
    kwargs = {
        "layers": layers,
        "forbidden": (isolation.PRIVATE_NOTE,),
        "planning": planning,
        "changed": changed,
    }
    if fault:
        with pytest.raises(ProgrammeHttpsError):
            isolation._document(session, "/room/", **kwargs)
    else:
        assert isolation._document(session, "/room/", **kwargs) == document


@pytest.mark.parametrize("revoke", [False, True])
@pytest.mark.parametrize(
    "fault",
    [
        None,
        "exit",
        "size",
        "json",
        "action",
        "extra",
        "nil",
        "changed",
        "os",
        "timeout",
    ],
)
def test_authority_child_is_bounded_private_and_exact(monkeypatch, revoke, fault):
    identifier = uuid4()
    action = "revoke" if revoke else "grant"
    fixture = SimpleNamespace(
        refresh_workers=Mock(),
        verify_excluded_state=Mock(),
        _application_environment={"runtime": "private"},
        deadline=100,
    )
    document = {"action": action, "assignment_id": str(identifier)}
    if fault == "action":
        document["action"] = "invalid"
    elif fault == "extra":
        document["private"] = "secret"
    elif fault == "nil":
        document["assignment_id"] = str(UUID(int=0))
    elif fault == "changed":
        document["assignment_id"] = "not-an-id" if not revoke else str(uuid4())
    output = json.dumps(document)
    if fault == "json":
        output = "private invalid json"
    elif fault == "size":
        output = "x" * 257
    child = Mock(
        return_value=SimpleNamespace(
            returncode=2 if fault == "exit" else 0, stdout=output
        )
    )
    if fault == "os":
        child.side_effect = OSError("private")
    elif fault == "timeout":
        child.side_effect = authority.subprocess.TimeoutExpired("private", 7)
    monkeypatch.setattr(authority, "require_programme_rehearsal_request", Mock())
    monkeypatch.setattr(authority, "remaining_lease", lambda _: 7)
    monkeypatch.setattr(authority.subprocess, "run", child)
    kwargs = {"assignment_id": identifier} if revoke else {}
    if fault:
        with pytest.raises(authority.ProgrammeHttpsError):
            authority.change_delivery_authority(
                fixture, {"secret": "private"}, **kwargs
            )
        fixture.verify_excluded_state.assert_not_called()
    else:
        assert (
            authority.change_delivery_authority(
                fixture, {"secret": "private"}, **kwargs
            )
            == identifier
        )
        fixture.verify_excluded_state.assert_called_once_with()
    args, options = child.call_args
    assert args[0] == [authority.sys.executable, "-m", authority.__name__]
    assert options["timeout"] == 7
    assert options["env"] is fixture._application_environment
    assert options["stderr"] == authority.subprocess.DEVNULL
    assert json.loads(options["input"])["action"] == action
    assert "private" not in " ".join(args[0])


@pytest.mark.parametrize(
    "function",
    [authority.change_delivery_authority, isolation.verify_delivery_isolation_http],
)
def test_guard_precedes_any_source_or_transport(monkeypatch, function):
    module = authority if function is authority.change_delivery_authority else isolation
    monkeypatch.setattr(
        module,
        "require_programme_rehearsal_request",
        Mock(side_effect=ProgrammeRehearsalEnvironmentError("denied")),
    )
    with pytest.raises(ProgrammeRehearsalEnvironmentError, match="denied"):
        function(*([None] * (2 if module is authority else 9)))


@pytest.mark.parametrize("fault", [None, "environment", "size", "json", "change"])
def test_child_failure_never_echoes_private_input(monkeypatch, fault):
    guard, change = (
        Mock(),
        Mock(return_value={"action": "grant", "assignment_id": str(uuid4())}),
    )
    raw = b'{"secret":"private"}'
    if fault == "environment":
        guard.side_effect = RuntimeError("private credentials")
    elif fault == "size":
        raw = b"x" * 131073
    elif fault == "json":
        raw = b"private invalid input"
    elif fault == "change":
        change.side_effect = RuntimeError("private authority")
    output = io.StringIO()
    monkeypatch.setattr(authority, "require_programme_runtime_environment", guard)
    monkeypatch.setattr(authority, "_change", change)
    monkeypatch.setattr(authority.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(raw)))
    monkeypatch.setattr(authority.sys, "stdout", output)
    assert authority._main() == (2 if fault else 0)
    assert "private" not in output.getvalue()
    if fault:
        assert output.getvalue() == ""


def test_composition_uses_every_subset_and_same_session_after_exact_revocation(
    monkeypatch,
):
    sources = _sources()
    setup, _, _, _, planning, physical, _, _ = sources
    changed = _result(sources)
    fixture = SimpleNamespace(
        scenario=setup, refresh_workers=Mock(), verify_excluded_state=Mock()
    )
    state = SimpleNamespace(granted=False, revoked=False)
    assignment = uuid4()
    events = []
    root = f"/admin/programme/run-sheets/{setup.organization_id}/{setup.edition_id}/"
    path = root + f"room/{planning.room_ids[0]}/"

    def change(current, documents, *, assignment_id=None):
        assert current is fixture
        assert set(documents) == set(isolation.SOURCE_KEYS)
        if assignment_id is None:
            assert not state.granted
            assert not state.revoked
            state.granted = True
        else:
            assert assignment_id == assignment
            assert state.granted
            state.granted, state.revoked = False, True
        events.append(("authority", state.granted))
        return assignment

    def request(route):
        parsed = urlsplit(route)
        query = parse_qs(parsed.query)
        layers = tuple(field for field in isolation.INSTRUCTIONS if field in query)
        events.append(("request", parsed.path, layers, state.granted, state.revoked))
        if parsed.path.startswith("/programme/"):
            text, mime, status = "{}", "application/json", 200
        elif parsed.path != path or (layers and not state.granted):
            text, mime, status = "Not found", "text/html", 404
        elif query.get("format") == ["json"]:
            text = json.dumps(_output(planning, changed, layers=layers))
            mime, status = "application/json", 200
        else:
            text = (
                "<main><h1>Room</h1>"
                + " ".join(isolation.INSTRUCTIONS[field] for field in layers)
                + "</main>"
            )
            mime, status = "text/html", 200
        return ProgrammeHttpResponse(
            status,
            {
                "Content-Type": mime,
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
            text.encode(),
        )

    session = Mock()
    session.request.side_effect = request
    constructor = Mock(return_value=session)
    monkeypatch.setattr(isolation, "require_programme_rehearsal_request", Mock())
    monkeypatch.setattr(isolation, "ProgrammeHttpSession", constructor)
    monkeypatch.setattr(isolation, "change_delivery_authority", change)
    isolation.verify_delivery_isolation_http(fixture, *sources[1:], changed)
    constructor.assert_called_once_with(fixture)
    session.login.assert_called_once_with(physical.reviewer, destination=path)
    session.logout.assert_called_once_with()
    _assert_sequence(events, path)
    fixture.verify_excluded_state.assert_called_once_with()


def _assert_sequence(events, path):
    assert [event for event in events if event[0] == "authority"] == [
        ("authority", True),
        ("authority", False),
    ]
    requested = [
        event[2]
        for event in events
        if event[0] == "request" and event[1] == path and event[3] and event[2]
    ]
    expected = [
        layers
        for size in (1, 2, 3)
        for layers in combinations(isolation.INSTRUCTIONS, size)
    ]
    assert requested == [layers for layers in expected for _ in range(2)]
    after_revoke = [
        event
        for event in events
        if event[0] == "request" and event[4] and event[1] == path
    ]
    assert [event[2] for event in after_revoke] == [
        (field,) for field in isolation.INSTRUCTIONS
    ] + [()]
    assert all(not event[3] for event in after_revoke)


def test_native_delivery_observes_successor_before_continuity_publishes_another():
    source = Path(__file__).parents[1] / "rehearsals" / "programme_proposal_native.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    calls = {
        node.args[0].id: node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "prepare"
        and node.args
        and isinstance(node.args[0], ast.Name)
    }
    assert calls["verify_onsite_http"] < calls["verify_delivery_isolation_http"]
    assert calls["verify_delivery_isolation_http"] < calls["verify_continuity_http"]
