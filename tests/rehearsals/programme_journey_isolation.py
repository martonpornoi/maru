"""Populated-route scope and purpose probes, separate from browser/human proof."""

from dataclasses import dataclass

from tests.rehearsals.programme_http_session import ProgrammeHttpSession
from tests.rehearsals.programme_https import ProgrammeHttpsError
from tests.rehearsals.programme_isolation_scopes import prepare_isolation_scopes
from tests.rehearsals.programme_items_scenario import PRIVATE_NOTE


@dataclass(frozen=True)
class JourneyProbe:
    """One actual authorized person and literal owning-route pattern."""

    code: str
    person: object
    pattern: str
    anonymous_status: int = 302
    denied_status: int = 404

    def path(self, organization, series, edition, department):
        return self.pattern.format(
            organization=organization,
            series=series,
            edition=edition,
            department=department,
        )


def journey_probes(setup, proposal, review, items, planning, physical, staffing):
    """Retain each real owning purpose; controller status is not a substitute."""
    scope = "{organization}/{edition}/"
    reviews = "/admin/applications/programme-review/" + scope + "{department}/"
    operators = "/admin/programme/run-sheets/" + scope
    return (
        JourneyProbe(
            "proposal",
            proposal.lead,
            "/my/applications/programme/" + scope + f"{proposal.proposal_id}/",
        ),
        JourneyProbe(
            "decision",
            review.people[4],
            reviews + f"decisions/{review.case_id}/",
        ),
        JourneyProbe(
            "working_item",
            review.people[5],
            "/admin/programme/items/" + scope + f"{items.accepted.item_id}/working/",
        ),
        JourneyProbe(
            "timetable",
            planning.planner,
            "/admin/platform/organizations/{organization}/series/{series}/"
            "editions/{edition}/programme/timetable/",
            anonymous_status=403,
            denied_status=403,
        ),
        JourneyProbe(
            "starter",
            setup.controllers[0],
            "/admin/programme/volunteer-starter/{organization}/{series}/{edition}/"
            f"{staffing.starter_request_id}/",
        ),
        JourneyProbe(
            "room_output",
            physical.reviewer,
            operators + f"room/{planning.room_ids[0]}/",
        ),
        JourneyProbe(
            "department_output",
            planning.planner,
            operators + "department/{department}/",
        ),
    )


def _check(response, *, expected, code, forbidden=()):
    if response.status != expected:
        raise ProgrammeHttpsError(
            f"fixture_journey_isolation_{code}_status_{response.status}"
        )
    if expected == 302:
        return
    if (
        "no-store" not in response.headers.get("Cache-Control", "")
        or response.headers.get("X-Content-Type-Options") != "nosniff"
    ):
        raise ProgrammeHttpsError(f"fixture_journey_isolation_{code}_cache")
    try:
        body = response.body.decode("utf-8")
    except UnicodeError:
        raise ProgrammeHttpsError("fixture_journey_isolation_encoding") from None
    if any(value in body for value in forbidden):
        raise ProgrammeHttpsError(f"fixture_journey_isolation_{code}_disclosure")


def verify_journey_isolation_http(
    fixture, proposal, review, items, planning, physical, staffing
):
    """Probe actual existing scopes and wrong purposes against populated sources."""
    setup = fixture.scenario
    for source in (proposal, review, items, planning, physical, staffing):
        if (source.organization_id, source.edition_id) != (
            setup.organization_id,
            setup.edition_id,
        ):
            raise ProgrammeHttpsError("fixture_journey_isolation_source_scope")
    scopes = prepare_isolation_scopes(fixture)
    fixture.refresh_workers()
    original = (
        setup.organization_id,
        setup.series_id,
        setup.edition_id,
        setup.department_id,
    )
    targets = (
        (
            scopes.organization_id,
            scopes.series_id,
            scopes.edition_id,
            scopes.department_id,
        ),
        (
            setup.organization_id,
            setup.series_id,
            scopes.sibling_edition_id,
            scopes.sibling_department_id,
        ),
        (scopes.organization_id, *original[1:]),
        (original[0], scopes.series_id, scopes.edition_id, scopes.department_id),
    )
    probes = journey_probes(
        setup, proposal, review, items, planning, physical, staffing
    )
    people = (
        *setup.controllers,
        setup.intake_person,
        proposal.lead,
        proposal.collaborator,
        *review.people,
        items.public_reviewer,
        items.ceremony_host,
        planning.planner,
        planning.catalog_person,
        physical.reviewer,
        staffing.volunteer,
    )
    secrets = tuple(person.password for person in people)
    private = (
        *secrets,
        PRIVATE_NOTE,
        "Fictional convention opening workshop",
        "Private organizer preparation, not public wording.",
        "Synthetic foreign isolation organizer",
        "Synthetic foreign isolation edition",
        "Synthetic sibling isolation edition",
    )
    session = ProgrammeHttpSession(fixture)
    try:
        for probe in probes:
            path = probe.path(*original)
            _check(
                session.request(path),
                expected=probe.anonymous_status,
                code=probe.code,
                forbidden=private,
            )
            session.login(probe.person, destination=path)
            _check(
                session.request(path), expected=200, code=probe.code, forbidden=secrets
            )
            for index, target in enumerate(targets):
                _check(
                    session.request(probe.path(*target)),
                    expected=probe.denied_status,
                    code=f"{probe.code}_scope_{index}",
                    forbidden=private,
                )
            session.logout()
        # A genuine confirmed volunteer still has none of these organizer,
        # proposal-owner, decision-maker or source-item purposes.
        session.login(staffing.volunteer, destination=probes[0].path(*original))
        for probe in probes:
            _check(
                session.request(probe.path(*original)),
                expected=probe.denied_status,
                code=probe.code + "_volunteer",
                forbidden=private,
            )
        session.logout()
    finally:
        session.cookies.clear()
    fixture.verify_excluded_state()
