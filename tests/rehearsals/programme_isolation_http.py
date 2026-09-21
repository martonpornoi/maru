"""Real scoped-route denials against existing foreign and sibling foundations."""

from bs4 import BeautifulSoup

from tests.rehearsals.programme_http_session import ProgrammeHttpSession
from tests.rehearsals.programme_https import ProgrammeHttpsError
from tests.rehearsals.programme_isolation_scopes import prepare_isolation_scopes


def _require(condition):
    if not condition:
        raise ProgrammeHttpsError("fixture_isolation_http_failed")


def _text(response):
    try:
        return response.body.decode("utf-8")
    except UnicodeError:
        raise ProgrammeHttpsError("fixture_isolation_encoding_invalid") from None


def _sibling_stop(response, *, organization_id, edition_id, original_edition_id):
    # Maru operators genuinely hold Organization-scoped Events transition and
    # role-control rights. Preserve that accepted boundary, not a false denial.
    _require(response.status == 200)
    document = BeautifulSoup(response.body, "html.parser")
    access = document.select_one(".programme-workbench .maru-access-summary")
    _require(access is not None)
    visible = access.get_text()
    _require(str(organization_id) in visible and str(edition_id) in visible)
    _require(str(original_edition_id) not in visible)


def _paths(organization_id, edition_id, task_id):
    archive = f"/admin/programme/archive/{organization_id}/{edition_id}/"
    return (
        archive,
        archive + f"{task_id}/",
        archive + f"{task_id}/download/",
        f"/admin/programme/stop/{organization_id}/{edition_id}/",
    )


def verify_isolation_http(fixture, archive):
    """Exercise real owner admission, not random missing-scope-only negatives."""
    setup = fixture.scenario
    _require(
        archive.organization_id == setup.organization_id
        and archive.edition_id == setup.edition_id
        and archive.requester_id == setup.controllers[0].account_id
    )
    scopes = prepare_isolation_scopes(fixture)
    fixture.refresh_workers()
    original = _paths(setup.organization_id, setup.edition_id, archive.task_id)
    forbidden = (
        "Synthetic foreign isolation organizer",
        "Synthetic foreign isolation edition",
        "Synthetic sibling isolation edition",
        *(person.password for person in (*setup.controllers, setup.intake_person)),
    )
    session = ProgrammeHttpSession(fixture)
    try:
        for path in original:
            _require(session.request(path).status == 302)
        session.login(setup.controllers[0], destination=original[0])
        # Positive controls distinguish actual owner admission from a dead route.
        _require(session.request(original[0]).status == 200)
        _require(session.request(original[1]).status == 200)
        _require(session.request(original[3]).status == 200)
        for scope_index, (organization_id, edition_id) in enumerate(
            (
                (scopes.organization_id, scopes.edition_id),
                (setup.organization_id, scopes.sibling_edition_id),
                (scopes.organization_id, setup.edition_id),
                (setup.organization_id, scopes.edition_id),
            )
        ):
            for path_index, path in enumerate(
                _paths(organization_id, edition_id, archive.task_id)
            ):
                response = session.request(path)
                if scope_index == 1 and path_index == 3:
                    _sibling_stop(
                        response,
                        organization_id=organization_id,
                        edition_id=edition_id,
                        original_edition_id=setup.edition_id,
                    )
                    continue
                if response.status != 404:
                    raise ProgrammeHttpsError(
                        f"fixture_isolation_http_scope_{scope_index}"
                        f"_path_{path_index}_status_{response.status}"
                    )
                _require("no-store" in response.headers.get("Cache-Control", ""))
                text = _text(response)
                _require(not any(value in text for value in forbidden))
        session.logout()
        for person in (setup.controllers[1], setup.intake_person):
            session.login(person, destination=original[0])
            # Controller status or Department intake responsibility cannot become
            # another requester's private archive authority or bearer download.
            for path in original[1:3]:
                response = session.request(path)
                _require(response.status == 404)
                _require(not any(value in _text(response) for value in forbidden))
            session.logout()
    finally:
        session.cookies.clear()
    fixture.verify_excluded_state()
