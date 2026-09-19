"""Closed P10 orchestration and actual crypto/clock refusals, without a database."""

from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, create_autospec

import pytest

from maru.scheduling.continuity_offline import decode_continuity_trust_policy
from tests.rehearsals import programme_continuity_scenario as scenario
from tests.rehearsals.programme_continuity_download import download_continuity_pack
from tests.rehearsals.programme_http_session import (
    ProgrammeHttpResponse,
    ProgrammeHttpSession,
)
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRehearsalEnvironmentError,
)
from tests.unit.test_programme_change_scenario import _result, _sources
from tests.unit.test_programme_continuity_offline_fixture import (
    _put,
)
from tests.unit.test_programme_continuity_offline_fixture import (
    prepared as prepared,  # noqa: PLC0414
)


def test_six_purposes_come_from_known_sources_not_package_contents():
    sources = _sources()
    changed = _result(sources)
    purposes = list(scenario._purposes(sources, changed))
    assert [row[0] for row in purposes] == [
        "public",
        "host",
        "volunteer",
        "room",
        "department",
        "edition",
    ]
    assert [len(row[3]) for row in purposes] == [3, 1, 4, 2, 7, 7]
    for _, person, scope, rows in purposes:
        assert scope.organization_id == sources[0].organization_id
        assert scope.edition_id == sources[0].edition_id
        assert scope.actor_id == (person.account_id if person else None)
        assert len(set(rows)) == len(rows)
    assert purposes[3][2].layers == ()
    assert purposes[4][2].layers == purposes[5][2].layers == ("staffing",)


@pytest.mark.parametrize("person_index", [None, 1])
@pytest.mark.parametrize("failure", [None, "download", "logout"])
def test_real_session_signature_and_cookie_cleanup(monkeypatch, person_index, failure):
    sources = _sources()
    row = list(scenario._purposes(sources, _result(sources)))[person_index or 0]
    _, person, scope, _ = row
    session = create_autospec(ProgrammeHttpSession, instance=True)
    session.cookies = Mock()
    monkeypatch.setattr(scenario, "ProgrammeHttpSession", Mock(return_value=session))
    download = create_autospec(download_continuity_pack, return_value="verified")
    monkeypatch.setattr(scenario, "download_continuity_pack", download)
    if failure == "download":
        download.side_effect = scenario.ProgrammeHttpsError("download failed")
    if failure == "logout":
        session.logout.side_effect = scenario.ProgrammeHttpsError("logout failed")
    if failure == "download" or (failure == "logout" and person):
        with pytest.raises(scenario.ProgrammeHttpsError):
            scenario._download(None, person, scope, ())
    else:
        assert scenario._download(None, person, scope, ()) == "verified"
    if person:
        session.login.assert_called_once_with(
            person, destination=scenario.continuity_path(scope).split("?")[0]
        )
        session.logout.assert_called_once_with()
    else:
        session.login.assert_not_called()
    session.cookies.clear.assert_called_once_with()


def test_actual_offline_negative_matrix_preserves_history(prepared, monkeypatch):
    fixture, scope, projection, policy = prepared
    monkeypatch.setattr(
        "tests.rehearsals.programme_continuity_download.require_programme_rehearsal_request",
        Mock(),
    )
    with scenario.isolated_continuity_files(fixture) as workspace:
        _put(workspace, "incoming.json", projection, policy)
        package = workspace.path("incoming.json").read_bytes()
        session = Mock()
        session.request.return_value = ProgrammeHttpResponse(
            200,
            {
                "Content-Type": "application/json",
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": 'attachment; filename="snapshot.json"',
            },
            package,
        )
        pack = download_continuity_pack(
            session,
            scope=scope,
            trust=decode_continuity_trust_policy(fixture.continuity_trust_policy),
        )
        scenario._snapshot(workspace, "public", pack, scope=scope, initialize=True)
        scenario._negative_offline(workspace, pack, scope)
        assert sorted(path.name for path in workspace.directory.glob("*.html")) == [
            "public.html"
        ]


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "rows",
        "release",
        "scope_source",
        "withdrawn",
        "replacement",
        "volunteer_release",
        "private_copy",
    ],
)
def test_full_sequence_refuses_changed_evidence_and_never_resets_history(
    monkeypatch, fault
):
    monkeypatch.setattr(scenario, "require_programme_rehearsal_request", Mock())
    sources = _sources()
    changed = _result(sources)
    fixture = SimpleNamespace(
        scenario=sources[0],
        refresh_workers=Mock(),
        continuity_trust_policy=b"independent",
        prepare_continuity_transition=Mock(),
    )
    recovered = SimpleNamespace(object_id=sources[7].release_id)
    fixture.prepare_continuity_transition.side_effect = ["withdrawal", recovered]
    monkeypatch.setattr(
        scenario, "decode_continuity_trust_policy", Mock(return_value=())
    )
    workspace = Mock()

    @contextmanager
    def files(_):
        yield workspace

    monkeypatch.setattr(scenario, "isolated_continuity_files", files)
    snapshot = Mock(return_value="safe")
    monkeypatch.setattr(scenario, "_snapshot", snapshot)
    monkeypatch.setattr(scenario, "_negative_offline", Mock())
    # Keep a real frozen projection for asdict while bypassing only transport/signing.
    from datetime import UTC, datetime  # noqa: PLC0415

    from maru.scheduling.continuity_payload import ContinuityProjection  # noqa: PLC0415

    now = datetime.now(UTC)
    packs = []
    for name, _, scope, rows in scenario._purposes(sources, changed):
        projection = ContinuityProjection(
            scope,
            "unused",
            "f" * 64,
            now,
            "Europe/Budapest",
            "available",
            2,
            changed.release_id,
            now,
            "available",
            "available",
            tuple(SimpleNamespace(key=row) for row in rows),
        )
        if name == "volunteer":
            projection = replace(
                projection,
                release_state="unobserved",
                hosting_status="unobserved",
                pointer_version=None,
                release_id=None,
                published_at=None,
            )
        packs.append(SimpleNamespace(projection=projection))
    if fault == "rows":
        packs[0].projection = replace(packs[0].projection, entries=())
    if fault == "release":
        packs[0].projection = replace(packs[0].projection, pointer_version=1)
    if fault == "volunteer_release":
        packs[2].projection = replace(
            packs[2].projection,
            release_state="available",
            pointer_version=2,
            release_id=changed.release_id,
        )
    if fault == "private_copy":
        snapshot.return_value = scenario.PRIVATE_NOTE
    original = packs[0].projection
    packs.extend(
        [
            SimpleNamespace(
                projection=replace(
                    original,
                    release_state="available" if fault == "withdrawn" else "withdrawn",
                    pointer_version=3,
                    release_id=None,
                    entries=(),
                )
            ),
            SimpleNamespace(
                projection=replace(
                    original,
                    pointer_version=3 if fault == "replacement" else 4,
                    release_id=recovered.object_id,
                )
            ),
        ]
    )
    download = Mock(side_effect=packs)
    monkeypatch.setattr(scenario, "_download", download)
    if fault == "scope_source":
        changed = replace(changed, edition_id=sources[0].organization_id)
    values = (*sources[1:], changed)
    if fault:
        with pytest.raises((scenario.ProgrammeHttpsError, ValueError, RuntimeError)):
            scenario.verify_continuity_http(fixture, *values)
    else:
        assert scenario.verify_continuity_http(fixture, *values) == (
            "withdrawal",
            recovered,
        )
        assert download.call_count == 8
        assert snapshot.call_count == 8
        assert (
            sum(
                call.kwargs.get("initialize", False) for call in snapshot.call_args_list
            )
            == 6
        )
        assert [
            call.kwargs["operation"]
            for call in fixture.prepare_continuity_transition.call_args_list
        ] == ["withdraw", "republish"]
        assert all(
            not call.kwargs.get("initialize")
            for call in workspace.verify.call_args_list
        )
    if fault in {
        "scope_source",
        "rows",
        "release",
        "volunteer_release",
        "private_copy",
    }:
        fixture.prepare_continuity_transition.assert_not_called()


def test_guard_precedes_fixture_access(monkeypatch):
    monkeypatch.setattr(
        scenario,
        "require_programme_rehearsal_request",
        Mock(side_effect=ProgrammeRehearsalEnvironmentError("deferred")),
    )
    with pytest.raises(ProgrammeRehearsalEnvironmentError):
        scenario.verify_continuity_http(None)
