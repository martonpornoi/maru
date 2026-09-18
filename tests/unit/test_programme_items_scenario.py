"""Pure item/hosting composition tests; not native readiness or human consent."""

import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, create_autospec
from uuid import uuid4

import pytest

from maru.events import queries as event_queries
from maru.programme import commands, creation_queries, host_commands, queries
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.catalogs import ProgrammeReadinessConcern
from maru.programme.host_inputs import ProgrammeHostAvailabilityPeriod
from tests.rehearsals import programme_items_scenario as scenario
from tests.rehearsals import programme_runtime
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRehearsalEnvironmentError,
)
from tests.unit.test_programme_proposal_scenario import _result as _proposal
from tests.unit.test_programme_proposal_scenario import _setup
from tests.unit.test_programme_review_scenario import _authentication
from tests.unit.test_programme_review_scenario import _result as _review
from tests.unit.test_programme_setup_scenarios import RUN, _person


def _period():
    return ProgrammeHostAvailabilityPeriod(
        datetime(2030, 9, 20, 7, tzinfo=UTC), datetime(2030, 9, 20, 16, tzinfo=UTC)
    )


def _result(setup, review):
    period = _period()
    return scenario.ProgrammeItemsScenario(
        setup.organization_id,
        setup.edition_id,
        scenario.PreparedProgrammeItem(review.item_id, 20, uuid4(), 4, uuid4(), 1),
        scenario.PreparedProgrammeItem(uuid4(), 20, uuid4(), 4, uuid4(), 1),
        period.starts_at,
        period.ends_at,
        _person("copy-reviewer"),
        _person("ceremony-host"),
        (uuid4(), uuid4(), uuid4()),
    )


def _mock_host(monkeypatch, *, leak=False):
    _authentication(monkeypatch)
    setup, editor, host, item_id, host_id = (
        _setup(),
        _person("editor"),
        _person("host"),
        uuid4(),
        uuid4(),
    )
    events = []

    def invoke(name, **kwargs):
        intent = (
            kwargs.get("invitation") or kwargs.get("response") or kwargs["availability"]
        )
        intent.normalized()
        events.append((name, kwargs))
        return host_commands.ProgrammeHostCommandResult(
            uuid4(),
            item_id,
            host_id,
            uuid4(),
            intent.expected_item_version + 1,
            intent.expected_host_version + 1,
            1,
            replayed=False,
        )

    for name in (
        "invite_programme_host",
        "respond_to_programme_host_invitation",
        "replace_programme_host_availability",
    ):
        monkeypatch.setattr(
            host_commands,
            name,
            create_autospec(
                getattr(host_commands, name),
                side_effect=lambda _name=name, **kw: invoke(_name, **kw),
            ),
        )

    def host_read(_setup, person, _item_id, *, organizer=False):
        if not events:
            raise ProgrammeAuthorizationDeniedError
        if not organizer:
            assert person == host
            return SimpleNamespace(
                item_version=11,
                relationship=SimpleNamespace(
                    host_id=host_id, state="invited", version=1, invitation_sequence=1
                ),
            )
        state = events[-1][1]["availability"].state
        periods = (_period(),) if state == "shared" or leak else ()
        return SimpleNamespace(
            hosts=(
                SimpleNamespace(
                    status="not_shared" if state == "draft" else "shared",
                    periods=periods,
                ),
            )
        )

    monkeypatch.setattr(scenario, "_host_read", host_read)
    denied = Mock(side_effect=ProgrammeAuthorizationDeniedError)
    monkeypatch.setattr(scenario, "_private_item", denied)
    return setup, editor, host, item_id, events, denied


def test_host_confirms_own_invitation_and_draft_periods_remain_private(monkeypatch):
    setup, editor, host, item_id, events, denied = _mock_host(monkeypatch)
    result = scenario._confirm_host(setup, editor, host, item_id, 10, _period())
    assert result.resulting_item_version == 14
    assert events[0][1]["actor_id"] == editor.account_id
    assert all(kw["actor_id"] == host.account_id for _, kw in events[1:])
    assert [kw["availability"].state for _, kw in events if "availability" in kw] == [
        "draft",
        "shared",
    ]
    assert denied.call_count == 2
    for _, kwargs in events:
        assert "authorizer" not in kwargs
        assert "now" not in kwargs
        assert kwargs["edition_id"] == setup.edition_id


def test_leaked_private_availability_prevents_shared_success(monkeypatch):
    setup, editor, host, item_id, events, _denied = _mock_host(monkeypatch, leak=True)
    with pytest.raises(
        scenario.ProgrammeItemsScenarioError, match="disclosure_changed"
    ):
        scenario._confirm_host(setup, editor, host, item_id, 10, _period())
    assert events[-1][1]["availability"].state == "draft"


def test_host_private_item_access_is_not_silently_accepted(monkeypatch):
    monkeypatch.setattr(scenario, "_private_item", Mock(return_value=object()))
    with pytest.raises(scenario.ProgrammeItemsScenarioError, match="not_denied"):
        scenario._require_private_denial(_setup(), _person("host"), uuid4())


def _mock_item(monkeypatch, *, stale=True, complete=True):
    _authentication(monkeypatch)
    setup, editor, reviewer, host = (
        _setup(),
        _person("editor"),
        _person("reviewer"),
        _person("host"),
    )
    item_id, working_id = uuid4(), uuid4()
    events = []

    def invoke(name, **kwargs):
        result = commands.ProgrammeCommandResult(
            uuid4(),
            item_id,
            uuid4(),
            None,
            kwargs["expected_version"]
            + (0 if name == "approve_programme_public_rendition" else 1),
            replayed=False,
        )
        events.append((name, kwargs, result))
        return result

    for name in (
        "revise_programme_working",
        "append_programme_discussion",
        "configure_programme_readiness",
        "revise_programme_delivery",
        "record_programme_readiness_evidence",
        "approve_programme_public_rendition",
    ):
        monkeypatch.setattr(
            commands,
            name,
            create_autospec(
                getattr(commands, name),
                side_effect=lambda _name=name, **kw: invoke(_name, **kw),
            ),
        )

    def private(*_args):
        return SimpleNamespace(
            private=SimpleNamespace(
                item=SimpleNamespace(
                    aggregate_version=events[-1][2].resulting_item_version
                    if events
                    else 1
                )
            ),
            working_revision_id=working_id,
        )

    monkeypatch.setattr(scenario, "_private_item", private)
    final_states = {
        c.value: "not_applicable" if c.value == "required_files" else "satisfied"
        for c in ProgrammeReadinessConcern
    }
    if not complete:
        final_states["host_confirmation"] = "stale"
    monkeypatch.setattr(
        scenario,
        "_readiness",
        Mock(
            side_effect=[
                dict.fromkeys(
                    scenario.DELIVERY_CONCERNS, "stale" if stale else "satisfied"
                ),
                final_states,
            ]
        ),
    )
    hosted = SimpleNamespace(host_id=uuid4(), resulting_host_version=4)
    monkeypatch.setattr(scenario, "_confirm_host", Mock(return_value=hosted))
    public = queries.ProgrammePublicCopyProjection(
        1, "Synthetic public session", "Public summary", "Public content note"
    )
    monkeypatch.setattr(
        queries,
        "load_programme_public_copy",
        create_autospec(queries.load_programme_public_copy, return_value=public),
    )
    monkeypatch.setattr(
        scenario,
        "_host_read",
        Mock(
            return_value=SimpleNamespace(
                public_copy=public, relationship=SimpleNamespace(state="confirmed")
            )
        ),
    )
    return setup, editor, reviewer, host, item_id, events, working_id


def test_item_layers_bind_real_sources_and_separate_copy_review_after_staleness(
    monkeypatch,
):
    setup, editor, reviewer, host, item_id, events, working_id = _mock_item(monkeypatch)
    result = scenario._prepare_item(
        setup, editor, reviewer, host, item_id, "Synthetic public session", _period()
    )
    assert result.item_id == item_id
    approval = next(
        kw for name, kw, _ in events if name == "approve_programme_public_rendition"
    )
    assert approval["actor_id"] == reviewer.account_id
    assert approval["source_working_revision_id"] == working_id
    assert all(
        kw["actor_id"] == editor.account_id
        for name, kw, _ in events
        if name != "approve_programme_public_rendition"
    )
    deliveries = [
        result for name, _kw, result in events if name == "revise_programme_delivery"
    ]
    evidence = [
        kw for name, kw, _ in events if name == "record_programme_readiness_evidence"
    ]
    assert len(deliveries) == 2
    for index, delivery in enumerate(deliveries, start=1):
        linked = [
            kw
            for kw in evidence
            if kw.get("source_object_id") == delivery.result_object_id
        ]
        assert {kw["concern"] for kw in linked} == set(scenario.DELIVERY_CONCERNS)
        assert all(kw["source_version"] == index for kw in linked)
    configured = [
        kw for name, kw, _ in events if name == "configure_programme_readiness"
    ]
    assert len(configured) == 7
    file_policy = next(
        kw for kw in configured if kw["concern"].value == "required_files"
    )
    assert "No on-site file or handout" in file_policy["reason"]
    assert [
        kw["concern"].value
        for kw in configured
        if kw["disposition"] == "not_applicable"
    ] == ["required_files"]
    assert all("authorizer" not in kw and "now" not in kw for _, kw, _ in events)


@pytest.mark.parametrize("failure", ["stale", "incomplete"])
def test_changed_dependency_and_incomplete_readiness_cannot_be_accepted(
    monkeypatch, failure
):
    setup, editor, reviewer, host, item_id, _, _ = _mock_item(
        monkeypatch, stale=failure != "stale", complete=failure != "incomplete"
    )
    with pytest.raises(scenario.ProgrammeItemsScenarioError):
        scenario._prepare_item(
            setup,
            editor,
            reviewer,
            host,
            item_id,
            "Synthetic public session",
            _period(),
        )
    if failure == "stale":
        scenario._confirm_host.assert_not_called()


def test_policy_and_native_readiness_precede_people_and_writes(monkeypatch):
    setup = _setup()
    proposal = _proposal(setup)
    review = _review(setup, proposal)
    create = Mock()
    monkeypatch.setattr(scenario, "_create_person", create)
    monkeypatch.setattr(
        scenario,
        "require_programme_runtime_environment",
        Mock(side_effect=ProgrammeRehearsalEnvironmentError("deferred")),
    )
    with pytest.raises(ProgrammeRehearsalEnvironmentError):
        scenario.prepare_items_scenario(setup, proposal, review)
    create.assert_not_called()

    monkeypatch.setattr(
        scenario,
        "require_programme_runtime_environment",
        lambda: SimpleNamespace(run_id=RUN),
    )
    monkeypatch.setattr(
        programme_runtime,
        "build_candidate_application",
        Mock(side_effect=RuntimeError("unready")),
    )
    with pytest.raises(RuntimeError, match="unready"):
        scenario.prepare_items_scenario(setup, proposal, review)
    create.assert_not_called()


def test_preparation_uses_real_core_signature_and_explicit_extra_roles(monkeypatch):
    _authentication(monkeypatch)
    setup = _setup()
    proposal = _proposal(setup)
    review = _review(setup, proposal)
    expected = _result(setup, review)
    monkeypatch.setattr(
        scenario,
        "require_programme_runtime_environment",
        lambda: SimpleNamespace(run_id=RUN),
    )
    monkeypatch.setattr(programme_runtime, "build_candidate_application", Mock())
    monkeypatch.setattr(
        scenario,
        "_create_person",
        Mock(side_effect=[expected.public_reviewer, expected.ceremony_host]),
    )
    approve = Mock(side_effect=expected.role_assignment_ids)
    monkeypatch.setattr(scenario, "approve_synthetic_role", approve)
    monkeypatch.setattr(
        creation_queries,
        "load_programme_creation_state",
        create_autospec(
            creation_queries.load_programme_creation_state,
            return_value=SimpleNamespace(control_version=1, writable=True),
        ),
    )
    monkeypatch.setattr(
        event_queries,
        "resolve_edition_time_envelope_reference",
        create_autospec(
            event_queries.resolve_edition_time_envelope_reference,
            return_value=SimpleNamespace(
                starts_at=expected.availability_starts_at - timedelta(hours=9)
            ),
        ),
    )
    core = create_autospec(
        commands.create_organizer_core_item,
        return_value=SimpleNamespace(item_id=expected.ceremony.item_id),
    )
    monkeypatch.setattr(commands, "create_organizer_core_item", core)
    prepare = Mock(side_effect=[expected.accepted, expected.ceremony])
    monkeypatch.setattr(scenario, "_prepare_item", prepare)
    result = scenario.prepare_items_scenario(setup, proposal, review)
    assert result == expected
    assert core.call_args.kwargs["kind"] == "ceremony"
    assert core.call_args.kwargs["expected_version"] == 1
    assert "authorizer" not in core.call_args.kwargs
    assert [
        (call.kwargs["recipient"], call.kwargs["code"])
        for call in approve.call_args_list
    ] == [
        (review.people[-1], "hosting"),
        (review.people[-1], "delivery"),
        (expected.public_reviewer, "content"),
    ]
    assert prepare.call_args_list[0].args[3:5] == (proposal.lead, review.item_id)
    assert prepare.call_args_list[1].args[3:5] == (
        expected.ceremony_host,
        expected.ceremony.item_id,
    )


@pytest.mark.parametrize(
    "change",
    [None, "scope", "source", "core", "person", "date", "version", "extra", "grant"],
)
def test_exact_item_results_reject_scope_identity_and_availability_drift(change):
    setup = _setup()
    proposal = _proposal(setup)
    review = _review(setup, proposal)
    result = _result(setup, review)
    document = json.loads(json.dumps(asdict(result), default=str))
    if change == "scope":
        document["organization_id"] = str(uuid4())
    elif change == "source":
        document["accepted"]["item_id"] = str(uuid4())
    elif change == "core":
        document["ceremony"]["item_id"] = document["accepted"]["item_id"]
    elif change == "person":
        document["public_reviewer"]["account_id"] = str(review.people[-1].account_id)
    elif change == "date":
        document["availability_ends_at"] = str(
            result.availability_starts_at - timedelta(hours=1)
        )
    elif change == "version":
        document["accepted"]["version"] = True
    elif change == "extra":
        document["unexpected"] = True
    elif change == "grant":
        document["role_assignment_ids"].pop()
    if change is None:
        assert (
            scenario.items_from_document(
                document, setup=setup, proposal=proposal, review=review
            )
            == result
        )
        assert result.ceremony_host.password not in repr(result)
    else:
        with pytest.raises(
            scenario.ProgrammeItemsScenarioError, match="result_invalid"
        ):
            scenario.items_from_document(
                document, setup=setup, proposal=proposal, review=review
            )
