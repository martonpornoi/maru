"""P10 actual HTTPS-to-offline preparation, not native or device acceptance."""

import base64
import json
from dataclasses import asdict, replace
from datetime import timedelta

from maru.scheduling.continuity_offline import (
    decode_continuity_trust_policy,
    verify_continuity_files,
)
from maru.scheduling.continuity_protocol import ContinuityInvalidError, ContinuityScope
from tests.rehearsals.programme_change_scenario import (
    SOURCE_KEYS,
    change_from_document,
    change_sources,
)
from tests.rehearsals.programme_continuity_download import (
    continuity_path,
    download_continuity_pack,
)
from tests.rehearsals.programme_continuity_offline import isolated_continuity_files
from tests.rehearsals.programme_http_session import ProgrammeHttpSession
from tests.rehearsals.programme_https import ProgrammeHttpsError
from tests.rehearsals.programme_items_scenario import PRIVATE_NOTE
from tests.rehearsals.programme_runtime_environment import (
    require_programme_rehearsal_request,
)


def _require(condition):
    if not condition:
        raise ProgrammeHttpsError("fixture_continuity_evidence_changed")


def _purposes(sources, changed):
    setup, _, _, items, planning, physical, staffing, _ = sources
    base = ContinuityScope(setup.organization_id, setup.edition_id, "public")
    yield "public", None, base, tuple(f"public:{x}" for x in planning.occurrence_ids)
    for name, person, rows in (
        (
            "host",
            items.ceremony_host,
            (f"host:{items.ceremony.host_id}:{planning.occurrence_ids[0]}",),
        ),
        (
            "volunteer",
            staffing.volunteer,
            tuple(
                f"work:{x}"
                for x in (
                    changed.work.commitment_id,
                    changed.predecessor_commitment_id,
                    *(row.commitment_id for row in staffing.work[1:]),
                )
            ),
        ),
    ):
        yield (
            name,
            person,
            replace(
                base,
                audience="exact_person",
                actor_id=person.account_id,
                kind="personal",
            ),
            rows,
        )
    for kind, target, person, occurrences, layers in (
        (
            "room",
            planning.room_ids[0],
            physical.reviewer,
            planning.occurrence_ids[:2],
            (),
        ),
        (
            "department",
            setup.department_id,
            planning.planner,
            planning.occurrence_ids,
            ("staffing",),
        ),
        (
            "edition",
            setup.edition_id,
            planning.planner,
            planning.occurrence_ids,
            ("staffing",),
        ),
    ):
        rows = tuple(f"operator:{x}" for x in occurrences)
        if layers:
            rows += tuple(
                f"demand:{x}"
                for x in (
                    changed.work.demand_id,
                    changed.predecessor_demand_id,
                    *(row.demand_id for row in staffing.work[1:]),
                )
            )
        yield (
            kind,
            person,
            replace(
                base,
                audience="private_operator",
                actor_id=person.account_id,
                kind=kind,
                target_id=target,
                layers=layers,
            ),
            rows,
        )


def _download(fixture, person, scope, trust):
    session = ProgrammeHttpSession(fixture)
    logged_in = False
    try:
        if person is not None:
            session.login(person, destination=continuity_path(scope).split("?")[0])
            logged_in = True
        return download_continuity_pack(session, scope=scope, trust=trust)
    finally:
        try:
            if logged_in:
                session.logout()
        finally:
            session.cookies.clear()


def _snapshot(workspace, name, pack, *, scope, initialize=False):
    workspace.write(name + ".json", pack.package)
    path = workspace.verify(
        name + ".json",
        purpose=scope.kind if scope.audience != "exact_person" else name,
        output_name=name + ".html",
        scope=scope,
        initialize=initialize,
    )
    text = path.read_text(encoding="utf-8")
    _require(
        all(
            value in text
            for value in (
                "Historical / degraded",
                "cannot know newer releases",
                "Replace/dispose",
            )
        )
    )
    return text


def _negative_offline(workspace, pack, scope):
    retained = workspace.path("public-known.json").read_bytes()
    document = json.loads(pack.package)
    signature = bytearray(base64.b64decode(document["signature"]))
    signature[0] ^= 1
    document["signature"] = base64.b64encode(signature).decode("ascii")
    workspace.write("tampered.json", json.dumps(document).encode())
    workspace.verify(
        "tampered.json",
        purpose="public",
        output_name="tampered.html",
        scope=scope,
        success=False,
    )
    workspace.verify(
        "public.json",
        purpose="public",
        output_name="foreign.html",
        scope=replace(scope, edition_id=scope.organization_id),
        success=False,
    )
    with workspace.missing_history("public"):
        workspace.verify(
            "public.json",
            purpose="public",
            output_name="missing.html",
            scope=scope,
            success=False,
        )
    # Explicit controlled-clock library checks: no OS clock change or elapsed wait.
    for name, now in (
        ("expired", pack.manifest.expires_at),
        ("early", pack.manifest.issued_at - timedelta(seconds=1)),
    ):
        output = workspace.path(name + ".html")
        try:
            verify_continuity_files(
                package_path=workspace.path("public.json"),
                trust_path=workspace.path("trust.json"),
                known_state_path=workspace.path("public-known.json"),
                output_path=output,
                expected_scope=scope,
                now=now,
            )
        except ContinuityInvalidError:
            pass
        else:
            raise ProgrammeHttpsError("fixture_continuity_clock_refusal_missing")
        _require(not output.exists())
    _require(workspace.path("public-known.json").read_bytes() == retained)


def verify_continuity_http(fixture, *values):
    """Compose real downloads, offline CLI and independent withdrawal/republication."""
    require_programme_rehearsal_request()
    sources = change_sources(
        {
            key: json.loads(json.dumps(asdict(value), default=str))
            for key, value in zip(
                SOURCE_KEYS, (fixture.scenario, *values[:-1]), strict=True
            )
        }
    )
    changed = change_from_document(
        json.loads(json.dumps(asdict(values[-1]), default=str)),
        setup=sources[0],
        staffing=sources[6],
        release=sources[7],
    )
    trust = decode_continuity_trust_policy(fixture.continuity_trust_policy)
    people = (
        sources[3].ceremony_host,
        sources[6].volunteer,
        sources[5].reviewer,
        sources[4].planner,
    )
    forbidden = (
        PRIVATE_NOTE,
        *(person.password for person in people),
        *(person.email for person in people),
    )
    fixture.refresh_workers()
    with isolated_continuity_files(fixture) as workspace:
        public = None
        for name, person, scope, rows in _purposes(sources, changed):
            pack = _download(fixture, person, scope, trust)
            projection = pack.projection
            _require(
                len(projection.entries) == len(rows)
                and {entry.key for entry in projection.entries} == set(rows)
            )
            if name == "volunteer":
                # Own work grants no hosting/publication observation purpose.
                _require(
                    projection.release_state
                    == projection.hosting_status
                    == "unobserved"
                    and projection.pointer_version is None
                    and projection.release_id is None
                    and projection.work_status == "available"
                )
            else:
                _require(
                    projection.release_state == "available"
                    and projection.pointer_version == 2
                    and projection.release_id == changed.release_id
                )
            text = _snapshot(workspace, name, pack, scope=scope, initialize=True)
            # Packages encode payload bytes; inspect decoded data as well as HTML.
            decoded = json.dumps(asdict(projection), default=str)
            _require(not any(value in decoded or value in text for value in forbidden))
            if name == "public":
                public = pack, scope
        _require(public is not None)
        original, scope = public
        workspace.verify(
            "public.json", purpose="public", output_name="repeat.html", scope=scope
        )
        _negative_offline(workspace, original, scope)
        withdrawal = fixture.prepare_continuity_transition(
            values[:-1], changed, operation="withdraw"
        )
        withdrawn = _download(fixture, None, scope, trust)
        _require(
            withdrawn.projection.release_state == "withdrawn"
            and withdrawn.projection.pointer_version == 3
            and withdrawn.projection.release_id is None
            and not withdrawn.projection.entries
        )
        _snapshot(workspace, "withdrawn", withdrawn, scope=scope)
        workspace.verify(
            "public.json",
            purpose="public",
            output_name="stale.html",
            scope=scope,
            success=False,
        )
        recovered = fixture.prepare_continuity_transition(
            values[:-1], changed, operation="republish"
        )
        replacement = _download(fixture, None, scope, trust)
        _require(
            replacement.projection.release_state == "available"
            and replacement.projection.pointer_version == 4
            and replacement.projection.release_id == recovered.object_id
            and {row.key for row in replacement.projection.entries}
            == {row.key for row in original.projection.entries}
        )
        _snapshot(workspace, "replacement", replacement, scope=scope)
        for name in ("public", "withdrawn"):
            workspace.verify(
                name + ".json",
                purpose="public",
                output_name=name + "-old.html",
                scope=scope,
                success=False,
            )
        return withdrawal, recovered
