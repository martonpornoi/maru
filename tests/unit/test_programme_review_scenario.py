"""Database-free composition checks, never native review or human acceptance."""

import io
import json
from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import Mock, create_autospec
from uuid import uuid4

import pytest

from maru.applications import programme_conversion_commands as conversion
from maru.applications import programme_conversion_queries as sources
from maru.applications import programme_review_commands as commands
from maru.applications import programme_review_queries as queries
from maru.applications.models import ProgrammeReviewAction as Action
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError,
)
from maru.authorization.catalog import ScopeLevel
from maru.programme import creation_queries
from tests.rehearsals import programme_review_scenario as scenario
from tests.rehearsals import programme_runtime
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRehearsalEnvironmentError,
)
from tests.rehearsals.programme_setup_scenarios import SyntheticProgrammePerson
from tests.unit.test_programme_proposal_scenario import _result as proposal_result
from tests.unit.test_programme_proposal_scenario import _setup
from tests.unit.test_programme_setup_scenarios import RUN, _person


def _result(setup, proposal):
    return scenario.ProgrammeReviewScenario(
        setup.organization_id,
        setup.edition_id,
        setup.department_id,
        proposal.proposal_id,
        proposal.revision_id,
        uuid4(),
        uuid4(),
        19,
        uuid4(),
        uuid4(),
        1,
        1,
        tuple(_person(label) for label, _ in scenario.PERSON_ROLES),
        tuple(uuid4() for _ in range(7)),
    )


def _authentication(monkeypatch):
    log = []

    def authenticate(self):
        log.append(self.account_id)
        return SimpleNamespace(id=self.account_id)

    monkeypatch.setattr(SyntheticProgrammePerson, "authenticate", authenticate)
    return log


def test_policy_is_explicit_two_stage_with_four_recipient_templates():
    policy = scenario._policy()
    assert len(policy.stages) == 2
    assert [s.anonymous for s in policy.stages] == [True, False]
    assert all(s.required_reviews == 1 for s in policy.stages)
    assert all(
        s.question_keys == ("session-title", "supporting-pdf") for s in policy.stages
    )
    assert {t.outcome for t in policy.templates} == {
        "accepted",
        "rejected",
        "waitlisted",
        "revision_requested",
    }
    assert all(t.acknowledgement_required for t in policy.templates)
    assert len(policy.digest) == 64


def test_each_staff_person_gets_only_explicit_independently_approved_recipe(
    monkeypatch,
):
    setup = _setup()
    people = tuple(_person(label) for label, _ in scenario.PERSON_ROLES)
    monkeypatch.setattr(scenario, "_create_person", Mock(side_effect=people))
    approve = Mock(side_effect=lambda *_args, **_kwargs: uuid4())
    monkeypatch.setattr(scenario, "approve_synthetic_role", approve)
    actual, grants = scenario._people(setup, RUN)
    assert actual == people
    assert len(grants) == 7
    for call, person, (_, recipe) in zip(
        approve.call_args_list[:6], people, scenario.PERSON_ROLES, strict=True
    ):
        assert call.args == (setup,)
        assert call.kwargs == {
            "people": setup.controllers,
            "recipient": person,
            "code": recipe,
            "level": ScopeLevel.DEPARTMENT,
            "department_id": setup.department_id,
        }
    final = approve.call_args_list[-1].kwargs
    assert final["code"] == "content"
    assert final["level"] == ScopeLevel.EDITION
    assert final["recipient"] == people[-1]
    assert "department_id" not in final


def _review_mocks(monkeypatch, *, disclosure_drift=False):
    setup = _setup()
    proposal = proposal_result(setup)
    people = _result(setup, proposal).people
    _authentication(monkeypatch)
    events = []
    case_id = uuid4()

    def command(**kw):
        events.append(kw)
        intent = kw["command"]
        intent.normalized()
        return commands.ProgrammeReviewResult(
            uuid4(),
            case_id if intent.action == Action.CASE_OPENED else uuid4(),
            None if intent.action == Action.POLICY_CREATED else case_id,
            kw["expected_version"] + 1,
            replayed=False,
        )

    monkeypatch.setattr(
        commands,
        "apply_programme_review_command",
        create_autospec(commands.apply_programme_review_command, side_effect=command),
    )

    def detail(**kw):
        if events[-1]["command"].action in {
            Action.REVIEWER_ASSIGNED,
            Action.REVIEWER_RECUSED,
        }:
            raise ApplicationsProgrammeAuthorizationDeniedError
        stage = sum(row["command"].action == Action.STAGE_ADVANCED for row in events)
        context = {"contributors": []} if stage or disclosure_drift else {}
        answers = [{"key": "session-title"}]
        if stage:
            answers.append({"key": "supporting-pdf"})
        assert kw["request"].actor_id == people[2].account_id
        return SimpleNamespace(
            version=events[-1]["expected_version"] + 1,
            context_json=json.dumps(context),
            answers_json=json.dumps(answers),
        )

    monkeypatch.setattr(
        queries,
        "get_programme_review_detail",
        create_autospec(queries.get_programme_review_detail, side_effect=detail),
    )

    def decision(**kw):
        own = any(
            row["command"].action == Action.ACKNOWLEDGED
            and row["actor_id"] == kw["request"].actor_id
            for row in events
        )
        return SimpleNamespace(
            decision_id=kw["decision_id"],
            case_version=events[-1]["expected_version"] + 1,
            outcome="accepted",
            source=SimpleNamespace(revision_id=proposal.revision_id),
            own_acknowledged=own,
            acknowledgement_required=True,
            message="Fictional acceptance.",
        )

    monkeypatch.setattr(
        queries,
        "get_self_programme_decision",
        create_autospec(queries.get_self_programme_decision, side_effect=decision),
    )
    return setup, proposal, people, events, case_id


def test_real_review_signatures_preserve_separation_scopes_and_exact_source(
    monkeypatch,
):
    setup, proposal, people, events, expected_case = _review_mocks(monkeypatch)
    case_id, decision_id, version = scenario._review(setup, proposal, people)
    assert case_id == expected_case
    assert version == events[-1]["expected_version"] + 1
    assert events[1]["command"].reference_id == proposal.revision_id
    by_action = {}
    for row in events:
        by_action.setdefault(row["command"].action, []).append(row)
        assert "authorizer" not in row
        assert row["organization_id"] == setup.organization_id
        assert row["edition_id"] == setup.edition_id
    assert by_action[Action.REVIEWER_RECUSED][0]["actor_id"] == people[1].account_id
    assert all(
        row["actor_id"] == people[2].account_id for row in by_action[Action.SCORED]
    )
    assert all(
        row["actor_id"] == people[3].account_id for row in by_action[Action.MODERATED]
    )
    assert by_action[Action.DECIDED][0]["actor_id"] == people[4].account_id
    assert len(by_action[Action.MODERATED]) == 2
    assert len(by_action[Action.STAGE_ADVANCED]) == 1
    acknowledgements = by_action[Action.ACKNOWLEDGED]
    assert [row["actor_id"] for row in acknowledgements] == [
        proposal.lead.account_id,
        proposal.collaborator.account_id,
    ]
    assert all(
        row["department_id"] is None and row["command"].reference_id == decision_id
        for row in acknowledgements
    )
    assert queries.get_programme_review_detail.call_count == 5
    assert queries.get_self_programme_decision.call_count == 4


def test_anonymous_disclosure_drift_prevents_scoring_and_acceptance(monkeypatch):
    setup, proposal, people, events, _ = _review_mocks(
        monkeypatch, disclosure_drift=True
    )
    with pytest.raises(
        scenario.ProgrammeReviewScenarioError, match="disclosure_changed"
    ):
        scenario._review(setup, proposal, people)
    assert not any(
        row["command"].action in {Action.SCORED, Action.DECIDED} for row in events
    )


def _conversion_mocks(monkeypatch):
    setup = _setup()
    proposal = proposal_result(setup)
    person = _person("converter")
    _authentication(monkeypatch)
    source = SimpleNamespace(
        eligible=True,
        consumed=False,
        writable=True,
        choice=SimpleNamespace(revision_id=proposal.revision_id, review_version=19),
    )
    monkeypatch.setattr(
        sources,
        "get_programme_conversion_source",
        create_autospec(sources.get_programme_conversion_source, return_value=source),
    )
    monkeypatch.setattr(
        creation_queries,
        "load_programme_creation_state",
        create_autospec(
            creation_queries.load_programme_creation_state,
            return_value=SimpleNamespace(control_version=0, writable=True),
        ),
    )
    result = conversion.ProgrammeConversionResult(
        uuid4(), uuid4(), 1, 1, replayed=False
    )
    mock = create_autospec(
        conversion.convert_accepted_programme_proposal,
        side_effect=[result, replace(result, replayed=True)],
    )
    monkeypatch.setattr(conversion, "convert_accepted_programme_proposal", mock)
    return setup, proposal, person, source, result, mock


def test_conversion_uses_both_real_queries_deliberate_copy_and_exact_retry(monkeypatch):
    setup, proposal, person, _, expected, mock = _conversion_mocks(monkeypatch)
    decision = uuid4()
    result = scenario._convert(
        setup, proposal, person, decision_id=decision, review_version=19
    )
    assert result == expected
    first, replay = [call.kwargs for call in mock.call_args_list]
    assert first["command"].revision_id == proposal.revision_id
    assert first["command"].decision_id == decision
    assert first["command"].expected_programme_version == 0
    assert first["command"] is replay["command"]
    assert first["retry_key"] == replay["retry_key"]
    assert first["correlation_id"] != replay["correlation_id"]
    assert "authorizer" not in first
    assert "programme_authorizer" not in first
    assert first["actor_id"] == person.account_id


@pytest.mark.parametrize(
    "failure", ["ineligible", "consumed", "closed", "seal", "version", "replay"]
)
def test_conversion_fails_closed_on_source_and_retained_receipt_drift(
    monkeypatch, failure
):
    setup, proposal, person, source, result, mock = _conversion_mocks(monkeypatch)
    if failure == "ineligible":
        source.eligible = False
    elif failure == "consumed":
        source.consumed = True
    elif failure == "closed":
        source.writable = False
    elif failure == "seal":
        source.choice.revision_id = uuid4()
    elif failure == "version":
        source.choice.review_version = 18
    else:
        mock.side_effect = [
            result,
            replace(result, programme_item_id=uuid4(), replayed=True),
        ]
    with pytest.raises(scenario.ProgrammeReviewScenarioError):
        scenario._convert(
            setup, proposal, person, decision_id=uuid4(), review_version=19
        )
    assert mock.call_count == (2 if failure == "replay" else 0)


def test_policy_and_actual_startup_precede_staff_creation(monkeypatch):
    setup = _setup()
    proposal = proposal_result(setup)
    people = Mock()
    monkeypatch.setattr(scenario, "_people", people)
    monkeypatch.setattr(
        scenario,
        "require_programme_runtime_environment",
        Mock(side_effect=ProgrammeRehearsalEnvironmentError("deferred")),
    )
    with pytest.raises(ProgrammeRehearsalEnvironmentError):
        scenario.prepare_review_scenario(setup, proposal)
    people.assert_not_called()
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
        scenario.prepare_review_scenario(setup, proposal)
    people.assert_not_called()


@pytest.mark.parametrize(
    "change", [None, "scope", "source", "person", "grant", "version", "secret", "extra"]
)
def test_private_result_decoder_retains_exact_source_and_separate_people(change):
    setup = _setup()
    proposal = proposal_result(setup)
    result = _result(setup, proposal)
    document = json.loads(json.dumps(asdict(result), default=str))
    if change == "scope":
        document["edition_id"] = str(uuid4())
    elif change == "source":
        document["revision_id"] = str(uuid4())
    elif change == "person":
        document["people"][0]["account_id"] = str(proposal.lead.account_id)
    elif change == "grant":
        document["role_assignment_ids"].pop()
    elif change == "version":
        document["review_version"] = True
    elif change == "secret":
        document["people"][0]["password"] = "bad"
    elif change == "extra":
        document["unknown"] = True
    if change is None:
        assert (
            scenario.review_from_document(document, setup=setup, proposal=proposal)
            == result
        )
        assert result.people[0].password not in repr(result)
    else:
        with pytest.raises(
            scenario.ProgrammeReviewScenarioError, match="result_invalid"
        ):
            scenario.review_from_document(document, setup=setup, proposal=proposal)


def test_child_rejects_extra_fields_and_oversize_without_owner_commands(monkeypatch):
    for raw in ("{}", "private" * 6000):
        monkeypatch.setattr(scenario.sys, "stdin", io.StringIO(raw))
        with pytest.raises(ValueError, match=r"^$"):
            scenario._read_input()


def test_unexpected_private_review_access_is_not_silently_accepted(monkeypatch):
    monkeypatch.setattr(scenario, "_review_detail", Mock(return_value=object()))
    with pytest.raises(scenario.ProgrammeReviewScenarioError, match="not_denied"):
        scenario._require_review_denial(_setup(), _person("reviewer"), uuid4())


@pytest.mark.parametrize("failure", ["private_reason", "wrong_ack", "wrong_seal"])
def test_recipient_projection_drift_fails_closed(monkeypatch, failure):
    setup, proposal, people, _events, _case = _review_mocks(monkeypatch)
    decision_id = uuid4()
    result = SimpleNamespace(
        decision_id=decision_id,
        case_version=10,
        outcome="accepted",
        source=SimpleNamespace(revision_id=proposal.revision_id),
        own_acknowledged=False,
        acknowledgement_required=True,
        message="Synthetic accepted message.",
    )
    if failure == "private_reason":
        result.message = scenario.REASON
    elif failure == "wrong_ack":
        result.own_acknowledged = True
    else:
        result.source.revision_id = uuid4()
    queries.get_self_programme_decision.side_effect = None
    queries.get_self_programme_decision.return_value = result
    with pytest.raises(
        scenario.ProgrammeReviewScenarioError, match="disclosure_changed"
    ):
        scenario._inspect_decision(
            setup,
            proposal,
            people[0],
            decision_id=decision_id,
            version=10,
            acknowledged=False,
        )
