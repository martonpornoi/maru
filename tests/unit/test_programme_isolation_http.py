"""Isolation observer failures cannot silently turn into acceptance evidence."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from tests.rehearsals import programme_isolation_http as probe


@pytest.fixture
def journey(monkeypatch):
    people = tuple(
        SimpleNamespace(account_id=uuid4(), password=f"private-password-{index}")
        for index in range(3)
    )
    setup = SimpleNamespace(
        organization_id=uuid4(),
        edition_id=uuid4(),
        controllers=people[:2],
        intake_person=people[2],
    )
    archive = SimpleNamespace(
        organization_id=setup.organization_id,
        edition_id=setup.edition_id,
        requester_id=people[0].account_id,
        task_id=uuid4(),
    )
    targets = SimpleNamespace(
        organization_id=uuid4(), edition_id=uuid4(), sibling_edition_id=uuid4()
    )
    fixture = SimpleNamespace(
        scenario=setup, refresh_workers=Mock(), verify_excluded_state=Mock()
    )
    original = probe._paths(setup.organization_id, setup.edition_id, archive.task_id)
    sibling = probe._paths(
        setup.organization_id, targets.sibling_edition_id, archive.task_id
    )[3]
    session = Mock()
    state = {"person": None, "fault": None}

    def respond(path):
        status, body = 404, b"Not found"
        if state["person"] is None:
            status = 302
        elif state["person"] is people[0]:
            if path in original:
                status, body = 200, b"Original scope"
            elif path == sibling:
                status = 200
                body = (
                    '<main class="programme-workbench"><div '
                    'class="maru-access-summary">'
                    f"{setup.organization_id} {targets.sibling_edition_id}"
                    "</div></main>"
                ).encode()
        if status == 404:
            if state["fault"] == "admitted":
                status = 200
            elif state["fault"] == "secret":
                body = people[1].password.encode()
            elif state["fault"] == "encoding":
                body = b"\xff"
        return SimpleNamespace(
            status=status,
            body=body,
            headers={
                "Cache-Control": ""
                if state["fault"] == "cache"
                else "private, no-store"
            },
        )

    session.request.side_effect = respond
    session.login.side_effect = lambda person, **_: state.update(person=person)
    session.logout.side_effect = lambda: state.update(person=None)
    monkeypatch.setattr(probe, "ProgrammeHttpSession", lambda _: session)
    monkeypatch.setattr(probe, "prepare_isolation_scopes", lambda _: targets)
    return fixture, archive, state, session


def test_positive_and_denial_observers_preserve_accepted_sibling_authority(journey):
    fixture, archive, _, session = journey
    probe.verify_isolation_http(fixture, archive)
    assert session.request.call_count == 27
    assert session.login.call_count == session.logout.call_count == 3
    session.cookies.clear.assert_called_once_with()
    fixture.verify_excluded_state.assert_called_once_with()


@pytest.mark.parametrize("fault", ["admitted", "secret", "encoding", "cache"])
def test_unexpected_disclosure_or_admission_refuses_acceptance(journey, fault):
    fixture, archive, state, session = journey
    state["fault"] = fault
    with pytest.raises(probe.ProgrammeHttpsError, match=r"^fixture_isolation_"):
        probe.verify_isolation_http(fixture, archive)
    session.cookies.clear.assert_called_once_with()
    fixture.verify_excluded_state.assert_not_called()


@pytest.mark.parametrize("field", ["organization_id", "edition_id", "requester_id"])
def test_changed_original_archive_never_becomes_an_isolation_probe(journey, field):
    fixture, archive, _, session = journey
    setattr(archive, field, uuid4())
    with pytest.raises(
        probe.ProgrammeHttpsError, match=r"^fixture_isolation_http_failed$"
    ):
        probe.verify_isolation_http(fixture, archive)
    session.login.assert_not_called()
    session.request.assert_not_called()


@pytest.mark.parametrize("fault", ["status", "missing", "wrong", "original"])
def test_sibling_positive_control_requires_exact_visible_scope(fault):
    organization, edition, original = uuid4(), uuid4(), uuid4()
    content = f"{organization} {edition}"
    if fault == "wrong":
        content = str(uuid4())
    elif fault == "original":
        content += str(original)
    body = (
        '<main class="programme-workbench"><div class="maru-access-summary">'
        f"{content}</div></main>"
    ).encode()
    response = SimpleNamespace(
        status=404 if fault == "status" else 200,
        body=b"No scope" if fault == "missing" else body,
    )
    with pytest.raises(
        probe.ProgrammeHttpsError, match=r"^fixture_isolation_http_failed$"
    ):
        probe._sibling_stop(
            response,
            organization_id=organization,
            edition_id=edition,
            original_edition_id=original,
        )
