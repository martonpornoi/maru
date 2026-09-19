"""Real-route P09 preparation; no native execution or browser acceptance implied."""

import json
import re
from dataclasses import asdict
from html.parser import HTMLParser
from urllib.parse import urlencode

from tests.rehearsals.programme_change_scenario import (
    SOURCE_KEYS,
    change_from_document,
    change_sources,
)
from tests.rehearsals.programme_http_session import ProgrammeHttpSession
from tests.rehearsals.programme_https import ProgrammeHttpsError
from tests.rehearsals.programme_items_scenario import PRIVATE_NOTE
from tests.rehearsals.programme_runtime_environment import (
    require_programme_rehearsal_request,
)


def _require(condition, code="fixture_onsite_output_changed"):
    if not condition:
        raise ProgrammeHttpsError(code)


class _Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.h1 = 0
        self.main = 0
        self.text = []

    def handle_starttag(self, tag, attrs):
        self.h1 += tag == "h1"
        self.main += tag == "main" or dict(attrs).get("role") == "main"

    def handle_data(self, data):
        self.text.append(data)


def _read(session, path, *, forbidden, status=200, mime="text/html"):
    response = session.request(path)
    _require(response.status == status, "fixture_onsite_status_changed")
    _require(
        "no-store" in response.headers.get("Cache-Control", "")
        and response.headers.get("X-Content-Type-Options") == "nosniff"
        and response.headers.get("Content-Type", "").split(";")[0] == mime,
        "fixture_onsite_transport_contract_changed",
    )
    try:
        text = response.body.decode("utf-8")
    except UnicodeError:
        raise ProgrammeHttpsError("fixture_onsite_encoding_invalid") from None
    _require(not any(value in text for value in forbidden), "fixture_onsite_disclosure")
    return text


def _page(session, path, *, forbidden, required):
    text = _read(session, path, forbidden=forbidden)
    page = _Page()
    page.feed(text)
    visible = " ".join(" ".join(page.text).split())
    _require(page.h1 == 1 and page.main == 1, "fixture_onsite_landmarks_changed")
    _require(all(value in visible for value in required))
    return visible


def _copies(
    session,
    path,
    now,
    *,
    forbidden,
    release_id,
    private=False,
    layers=(),
    now_rows=None,
):
    def route(base, output_format):
        return (
            base
            + "?"
            + urlencode(dict.fromkeys(layers, "1") | {"format": output_format})
        )

    for output_format in ("html", "print"):
        required = ("Europe/Budapest",)
        if release_id is not None:
            required += (str(release_id),)
        _page(
            session, route(path, output_format), forbidden=forbidden, required=required
        )
        visible = _page(
            session,
            route(now, output_format),
            forbidden=forbidden,
            required=(
                *required,
                "Source checked:",
                "Replace/dispose no later than:",
                "Saved copies are historical",
                "Complete run sheet",
                "It does not prove attendance",
            ),
        )
        if output_format == "print":
            _require("Download signed snapshot" not in visible)
        if now_rows is not None:
            rows = re.findall(r"Source row: ([a-z]+:[a-z0-9:-]+)", visible)
            _require(len(rows) == len(now_rows) and set(rows) == set(now_rows))
    document = json.loads(
        _read(
            session, route(path, "json"), forbidden=forbidden, mime="application/json"
        )
    )
    calendar = _read(
        session, route(path, "calendar"), forbidden=forbidden, mime="text/calendar"
    )
    _require(calendar.startswith("BEGIN:VCALENDAR\r\n"))
    if release_id is not None:
        _require(f"X-MARU-RELEASE-ID:{release_id}" in calendar)
    if private:
        _require("CLASS:PRIVATE" in calendar)
    _require(document["zone_name"] == "Europe/Budapest")
    return document


def _release(document, changed, *, state_key="state"):
    _require(
        document[state_key] == "available"
        and document["release_id"] == str(changed.release_id)
        and document["pointer_version"] == 2
    )


def _personal(
    session,
    paths,
    *,
    person,
    forbidden,
    changed,
    work=None,
    occurrence=None,
    host_id=None,
):
    timetable, now = paths
    # The shared authenticated shell legitimately identifies its own viewer.
    forbidden = tuple(value for value in forbidden if value != person.email)
    session.login(person, destination=timetable)
    try:
        document = _copies(
            session,
            timetable,
            now,
            forbidden=forbidden,
            release_id=changed.release_id if occurrence is not None else None,
            private=True,
            now_rows=(f"host:{host_id}:{occurrence}",)
            if occurrence is not None
            else (
                *(f"work:{row.commitment_id}" for row in work),
                f"work:{changed.predecessor_commitment_id}",
            ),
        )
        _require(document["actor_id"] == str(person.account_id))
        if occurrence is not None:
            _release(document["hosting"], changed)
            presences = document["hosting"]["presences"]
            _require(
                len(presences) == 1
                and presences[0]["occurrence_id"] == str(occurrence)
                and document["shifts"] == []
            )
        else:
            _require(
                document["hosting"]["release_id"] is None
                and document["hosting"]["presences"] == []
            )
            shifts = {row["commitment_id"]: row for row in document["shifts"]}
            expected = {str(row.commitment_id): row for row in work}
            _require(
                set(shifts) == set(expected) | {str(changed.predecessor_commitment_id)}
            )
            old = shifts[str(changed.predecessor_commitment_id)]
            _require(
                old["status"] == "removed"
                and old["instructions"]["status"] == "cancelled"
            )
            for identifier, original in expected.items():
                row = shifts[identifier]
                _require(
                    row["status"] == "confirmed"
                    and row["version"] == original.commitment_version
                    and row["instructions"]["demand_id"] == str(original.demand_id)
                    and row["instructions"]["version"] == original.demand_version
                )
        _read(
            session,
            timetable + "?actor_id=" + str(person.account_id),
            forbidden=forbidden,
            status=400,
        )
    finally:
        session.logout()
    _require(
        session.request(timetable).status == 302, "fixture_onsite_logout_not_enforced"
    )


def _operator(
    session,
    *,
    person,
    root,
    now_root,
    kind,
    target,
    changed,
    occurrences,
    forbidden,
    layers=(),
    work=(),
):
    suffix = f"{kind}/{target}/"
    path = root + suffix
    forbidden = tuple(value for value in forbidden if value != person.email)
    session.login(person, destination=path)
    try:
        document = _copies(
            session,
            path,
            now_root + suffix,
            forbidden=forbidden,
            release_id=changed.release_id,
            private=True,
            layers=layers,
            now_rows=(
                *(f"operator:{value}" for value in occurrences),
                *(_demand_rows(changed, work) if layers else ()),
            ),
        )
        _release(document, changed, state_key="release_state")
        _require(
            document["scope_kind"] == kind
            and document["scope_id"] == str(target)
            and document["requested_layers"] == list(layers)
            and len(document["entries"]) == len(occurrences)
            and {row["placement"]["occurrence_id"] for row in document["entries"]}
            == set(map(str, occurrences))
            and all(row["delivery"] is None for row in document["entries"])
        )
        if not layers:
            _require(document["staffing"] is None)
            _read(session, path + "?technical=1", forbidden=forbidden, status=404)
            _read(
                session,
                root + f"edition/{changed.edition_id}/",
                forbidden=forbidden,
                status=404,
            )
        else:
            _operator_work(document["staffing"], changed, work)
        _read(
            session, path + "?format=json&format=print", forbidden=forbidden, status=400
        )
    finally:
        session.logout()


def verify_onsite_http(
    fixture, proposal, review, items, planning, physical, staffing, release, changed
):
    """Prepare actual HTTPS/CSRF and output assertions without activating a profile."""
    require_programme_rehearsal_request()
    values = (
        fixture.scenario,
        proposal,
        review,
        items,
        planning,
        physical,
        staffing,
        release,
    )
    documents = {
        key: json.loads(json.dumps(asdict(value), default=str))
        for key, value in zip(SOURCE_KEYS, values, strict=True)
    }
    setup, proposal, review, items, planning, physical, staffing, release = (
        change_sources(documents)
    )
    changed = change_from_document(
        json.loads(json.dumps(asdict(changed), default=str)),
        setup=setup,
        staffing=staffing,
        release=release,
    )
    people = (
        items.ceremony_host,
        staffing.volunteer,
        physical.reviewer,
        planning.planner,
    )
    forbidden = (
        PRIVATE_NOTE,
        *(person.password for person in people),
        *(person.email for person in people),
    )
    scope = f"{setup.organization_id}/{setup.edition_id}/"
    public = f"/programme/{scope}timetable/"
    public_now = f"/programme/{scope}now/"
    personal = f"/my/{scope}timetable/", f"/my/{scope}programme-now/"
    operators = f"/admin/programme/run-sheets/{scope}"
    operator_now = f"/admin/programme/now/{scope}"
    fixture.refresh_workers()
    session = ProgrammeHttpSession(fixture)
    try:
        document = _copies(
            session,
            public,
            public_now,
            forbidden=forbidden,
            release_id=changed.release_id,
            now_rows=tuple(f"public:{value}" for value in planning.occurrence_ids),
        )
        _release(document, changed)
        _require(
            len(document["entries"]) == 3
            and {row["occurrence_id"] for row in document["entries"]}
            == set(map(str, planning.occurrence_ids))
        )
        _require(session.request(personal[0]).status == 302)
        _read(session, public_now + "?format=pack", forbidden=forbidden, status=503)
        _read(
            session,
            public + "?format=json&format=print",
            forbidden=forbidden,
            status=400,
        )
        _personal(
            session,
            personal,
            person=items.ceremony_host,
            forbidden=forbidden,
            changed=changed,
            occurrence=planning.occurrence_ids[0],
            host_id=items.ceremony.host_id,
        )
        _personal(
            session,
            personal,
            person=staffing.volunteer,
            forbidden=forbidden,
            changed=changed,
            work=(changed.work, *staffing.work[1:]),
        )
        for person, kind, target, occurrences, layers in (
            (
                physical.reviewer,
                "room",
                planning.room_ids[0],
                planning.occurrence_ids[:2],
                (),
            ),
            (
                planning.planner,
                "department",
                setup.department_id,
                planning.occurrence_ids,
                ("staffing",),
            ),
            (
                planning.planner,
                "edition",
                setup.edition_id,
                planning.occurrence_ids,
                ("staffing",),
            ),
        ):
            _operator(
                session,
                person=person,
                root=operators,
                now_root=operator_now,
                kind=kind,
                target=target,
                changed=changed,
                occurrences=occurrences,
                forbidden=forbidden,
                layers=layers,
                work=(changed.work, *staffing.work[1:]) if layers else (),
            )
    finally:
        session.cookies.clear()


def _demand_rows(changed, work):
    return (
        *(f"demand:{row.demand_id}" for row in work),
        f"demand:{changed.predecessor_demand_id}",
    )


def _operator_work(layer, changed, work):
    _require(layer is not None and layer["adopted"])
    expected = {str(row.demand_id): row for row in work}
    links, demands = layer["links"], layer["demands"]
    _require(
        len(links) == len(expected) + 1
        and {row["demand_id"] for row in links if row["current"]} == set(expected)
        and {row["demand_id"] for row in links if not row["current"]}
        == {str(changed.predecessor_demand_id)}
        and all(
            row["demand_version"] == expected[row["demand_id"]].demand_version
            for row in links
            if row["current"]
        )
        and len(demands) == len(expected) + 1
        and {row["demand_id"] for row in demands if row["state"] == "locked"}
        == set(expected)
        and {row["demand_id"] for row in demands if row["state"] == "cancelled"}
        == {str(changed.predecessor_demand_id)}
    )
