"""Genuine connected-role delivery field and revocation checks, not human proof."""

import json
from dataclasses import asdict
from itertools import combinations
from urllib.parse import urlencode

from tests.rehearsals.programme_change_scenario import SOURCE_KEYS, change_sources
from tests.rehearsals.programme_delivery_authority import change_delivery_authority
from tests.rehearsals.programme_http_session import ProgrammeHttpSession
from tests.rehearsals.programme_items_scenario import PRIVATE_NOTE
from tests.rehearsals.programme_onsite_scenario import _page, _read, _require
from tests.rehearsals.programme_runtime_environment import (
    require_programme_rehearsal_request,
)

# Independent expected bytes, not values echoed from the output under test.
INSTRUCTIONS = {
    "technical": "One handheld microphone and one optional projector.",
    "accessibility": (
        "Keep clear wheelchair access and a quiet exit; check seating before entry."
    ),
    "media": "No photography or recording in this fictional session.",
}


def _document(session, path, *, layers, forbidden, planning, changed):
    text = _read(
        session,
        path + "?" + urlencode(dict.fromkeys(layers, "1") | {"format": "json"}),
        forbidden=forbidden,
        mime="application/json",
    )
    document = json.loads(text)
    _require(
        document["release_state"] == "available"
        and document["release_id"] == str(changed.release_id)
        and document["pointer_version"] == changed.pointer_version
        and document["scope_kind"] == "room"
        and document["scope_id"] == str(planning.room_ids[0])
        and document["requested_layers"] == sorted(layers)
        and document["staffing"] is None
        and len(document["entries"]) == 2
        and {row["placement"]["occurrence_id"] for row in document["entries"]}
        == set(map(str, planning.occurrence_ids[:2])),
        "fixture_delivery_output_changed",
    )
    for row in document["entries"]:
        delivery = row["delivery"]
        if not layers:
            _require(delivery is None, "fixture_delivery_unrequested_layer")
            continue
        _require(
            delivery is not None
            and delivery["item_id"] == row["placement"]["item_id"]
            and delivery["version"] == 2
            and delivery["revision_id"] is not None
            and delivery["occurred_at"] is not None
            and delivery["checked_at"] is not None
            and set(delivery)
            == {"item_id", "revision_id", "version", "occurred_at", "checked_at"}
            | set(layers)
            and all(delivery[field] == INSTRUCTIONS[field] for field in layers),
            "fixture_delivery_fields_changed",
        )
    return document


def verify_delivery_isolation_http(
    fixture, proposal, review, items, planning, physical, staffing, release, changed
):
    """Check all seven field subsets and exact live grant loss in the same session."""
    require_programme_rehearsal_request()
    sources = {
        key: json.loads(json.dumps(asdict(value), default=str))
        for key, value in zip(
            SOURCE_KEYS,
            (
                fixture.scenario,
                proposal,
                review,
                items,
                planning,
                physical,
                staffing,
                release,
            ),
            strict=True,
        )
    }
    setup, _, _, items, planning, physical, staffing, _ = change_sources(sources)
    _require(
        (changed.organization_id, changed.edition_id)
        == (setup.organization_id, setup.edition_id),
        "fixture_delivery_source_scope",
    )
    scope = f"{setup.organization_id}/{setup.edition_id}/"
    root = "/admin/programme/run-sheets/" + scope
    path = root + f"room/{planning.room_ids[0]}/"
    forbidden = (
        PRIVATE_NOTE,
        *(
            p.password
            for p in (physical.reviewer, items.ceremony_host, staffing.volunteer)
        ),
        items.ceremony_host.email,
        staffing.volunteer.email,
    )
    all_private = (*forbidden, *INSTRUCTIONS.values())
    fixture.refresh_workers()
    session = ProgrammeHttpSession(fixture)
    session.login(physical.reviewer, destination=path)
    try:
        _document(
            session,
            path,
            layers=(),
            forbidden=all_private,
            planning=planning,
            changed=changed,
        )
        for field in INSTRUCTIONS:
            _read(session, path + f"?{field}=1", forbidden=all_private, status=404)
        assignment = change_delivery_authority(fixture, sources)
        for size in (1, 2, 3):
            for layers in combinations(INSTRUCTIONS, size):
                excluded = (
                    *forbidden,
                    *(v for k, v in INSTRUCTIONS.items() if k not in layers),
                )
                _document(
                    session,
                    path,
                    layers=layers,
                    forbidden=excluded,
                    planning=planning,
                    changed=changed,
                )
                _page(
                    session,
                    path
                    + "?"
                    + urlencode(dict.fromkeys(layers, "1") | {"format": "print"}),
                    forbidden=excluded,
                    required=tuple(INSTRUCTIONS[field] for field in layers),
                )
        # The delivery grant is not general private-item or other-purpose access.
        for denied in (
            root + f"room/{planning.room_ids[1]}/?technical=1",
            root + f"department/{setup.department_id}/?technical=1",
            root + f"edition/{setup.edition_id}/?technical=1",
        ):
            _read(session, denied, forbidden=all_private, status=404)
        _document(
            session,
            path,
            layers=(),
            forbidden=all_private,
            planning=planning,
            changed=changed,
        )
        change_delivery_authority(fixture, sources, assignment_id=assignment)
        # No logout, worker restart or credential change: the very next request
        # must observe revocation while the independent base purpose still works.
        for field in INSTRUCTIONS:
            _read(session, path + f"?{field}=1", forbidden=all_private, status=404)
        _document(
            session,
            path,
            layers=(),
            forbidden=all_private,
            planning=planning,
            changed=changed,
        )
    finally:
        session.logout()
    _read(
        session,
        "/programme/" + scope + "timetable/?format=json",
        forbidden=all_private,
        mime="application/json",
    )
    fixture.verify_excluded_state()
