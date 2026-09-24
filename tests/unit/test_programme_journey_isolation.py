"""Closed populated-route observer tests; no synthetic native pass is implied."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from tests.rehearsals import programme_journey_isolation as journey


def _person():
    return SimpleNamespace(account_id=uuid4(), password=uuid4().hex)


@pytest.fixture
def sources():
    scope = {"organization_id": uuid4(), "edition_id": uuid4()}
    setup = SimpleNamespace(
        **scope,
        series_id=uuid4(),
        department_id=uuid4(),
        controllers=(_person(), _person()),
        intake_person=_person(),
    )
    proposal = SimpleNamespace(
        **scope, lead=_person(), collaborator=_person(), proposal_id=uuid4()
    )
    review = SimpleNamespace(
        **scope, people=tuple(_person() for _ in range(6)), case_id=uuid4()
    )
    items = SimpleNamespace(
        **scope,
        accepted=SimpleNamespace(item_id=uuid4()),
        public_reviewer=_person(),
        ceremony_host=_person(),
    )
    planning = SimpleNamespace(
        **scope,
        planner=_person(),
        catalog_person=_person(),
        room_ids=(uuid4(), uuid4()),
    )
    physical = SimpleNamespace(**scope, reviewer=_person())
    staffing = SimpleNamespace(**scope, volunteer=_person(), starter_request_id=uuid4())
    return setup, proposal, review, items, planning, physical, staffing


def test_literal_probe_inventory_retains_each_independent_actor(sources):
    setup, proposal, review, items, planning, physical, staffing = sources
    probes = journey.journey_probes(*sources)
    assert [probe.code for probe in probes] == [
        "proposal",
        "decision",
        "working_item",
        "timetable",
        "starter",
        "room_output",
        "department_output",
    ]
    assert [probe.person for probe in probes] == [
        proposal.lead,
        review.people[4],
        review.people[5],
        planning.planner,
        setup.controllers[0],
        physical.reviewer,
        planning.planner,
    ]
    original = (
        setup.organization_id,
        setup.series_id,
        setup.edition_id,
        setup.department_id,
    )
    paths = [probe.path(*original) for probe in probes]
    assert len(set(paths)) == 7
    for probe, path in zip(probes, paths, strict=True):
        assert path.startswith("/")
        assert str(setup.organization_id) in path
        assert str(setup.edition_id) in path
        assert "{" not in path
        assert probe.denied_status == (403 if probe.code == "timetable" else 404)
        assert probe.anonymous_status == (403 if probe.code == "timetable" else 302)
    assert str(proposal.proposal_id) in paths[0]
    assert str(review.case_id) in paths[1]
    assert str(items.accepted.item_id) in paths[2]
    assert str(staffing.starter_request_id) in paths[4]


@pytest.mark.parametrize(
    "fault", [None, "status", "cache", "mime", "encoding", "secret"]
)
def test_response_observer_is_fail_closed(fault):
    response = SimpleNamespace(
        status=200 if fault == "status" else 404,
        headers={
            "Cache-Control": "public" if fault == "cache" else "private, no-store",
            "X-Content-Type-Options": "" if fault == "mime" else "nosniff",
        },
        body=b"\xff" if fault == "encoding" else b"Safe refusal",
    )
    if fault == "secret":
        response.body = b"private synthetic credential"
    if fault:
        with pytest.raises(
            journey.ProgrammeHttpsError, match=r"^fixture_journey_isolation_"
        ):
            journey._check(
                response, expected=404, code="test", forbidden=("private synthetic",)
            )
    else:
        journey._check(response, expected=404, code="test")


@pytest.mark.parametrize("source_index", range(1, 7))
def test_crossed_predecessor_scope_refuses_before_any_setup(
    sources, monkeypatch, source_index
):
    prepare = Mock()
    monkeypatch.setattr(journey, "prepare_isolation_scopes", prepare)
    sources[source_index].edition_id = uuid4()
    with pytest.raises(
        journey.ProgrammeHttpsError, match=r"^fixture_journey_isolation_source_scope$"
    ):
        journey.verify_journey_isolation_http(
            SimpleNamespace(scenario=sources[0]), *sources[1:]
        )
    prepare.assert_not_called()


@pytest.mark.parametrize("fail_request", [False, True])
def test_supervisor_probes_four_existing_scopes_and_clears_session(
    sources, monkeypatch, fail_request
):
    fixture = SimpleNamespace(
        scenario=sources[0], refresh_workers=Mock(), verify_excluded_state=Mock()
    )
    target = SimpleNamespace(
        **{
            name: uuid4()
            for name in (
                "organization_id",
                "series_id",
                "edition_id",
                "department_id",
                "sibling_edition_id",
                "sibling_department_id",
            )
        }
    )
    prepare, check, session = Mock(return_value=target), Mock(), Mock()
    if fail_request:
        session.request.side_effect = journey.ProgrammeHttpsError("closed")
    monkeypatch.setattr(journey, "prepare_isolation_scopes", prepare)
    monkeypatch.setattr(journey, "ProgrammeHttpSession", lambda _: session)
    monkeypatch.setattr(journey, "_check", check)
    if fail_request:
        with pytest.raises(journey.ProgrammeHttpsError, match="closed"):
            journey.verify_journey_isolation_http(fixture, *sources[1:])
        fixture.verify_excluded_state.assert_not_called()
    else:
        journey.verify_journey_isolation_http(fixture, *sources[1:])
        assert session.request.call_count == 49
        assert session.login.call_count == session.logout.call_count == 8
        assert check.call_count == 49
        fixture.verify_excluded_state.assert_called_once_with()
        paths = [call.args[0] for call in session.request.call_args_list]
        assert any(str(target.organization_id) in path for path in paths)
        assert any(str(target.sibling_edition_id) in path for path in paths)
    session.cookies.clear.assert_called_once_with()
    prepare.assert_called_once_with(fixture)
