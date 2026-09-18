"""Pure owner-composition checks, explicitly not native P02 acceptance."""

import io
import json
from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import Mock, create_autospec
from uuid import uuid4

import pytest

from maru.applications import programme_commands as commands
from maru.applications import programme_file_commands as files
from maru.applications import programme_personal_queries as personal
from maru.applications import programme_queries as queries
from tests.rehearsals import programme_proposal_scenario as scenario
from tests.rehearsals import programme_runtime
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRehearsalEnvironmentError,
)
from tests.rehearsals.programme_setup_scenarios import (
    SyntheticProgrammePerson,
    scenario_from_document,
)
from tests.unit.test_programme_setup_scenarios import RUN, _document, _person


def _setup():
    return scenario_from_document(_document(), mode="new_foundation")


def _result(setup):
    return scenario.ProgrammeProposalScenario(
        setup.organization_id,
        setup.edition_id,
        setup.department_id,
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        10,
        uuid4(),
        _person("lead"),
        _person("collaborator"),
    )


def test_pdf_has_real_offsets_single_page_and_no_external_content():
    data = scenario.synthetic_supporting_pdf()
    offset = int(data.split(b"startxref\n")[1].splitlines()[0])
    assert data[offset:].startswith(b"xref\n0 6\n")
    for number, line in enumerate(data[offset:].splitlines()[3:8], start=1):
        assert data[int(line[:10]) :].startswith(f"{number} 0 obj\n".encode())
    stream = data.split(b"stream\n", 1)[1].split(b"endstream", 1)[0]
    assert b"/Length " + str(len(stream)).encode() + b" >>" in data
    assert b"/Count 1" in data
    assert data.endswith(b"%%EOF\n")
    assert len(data) < 1024
    assert not any(
        value in data
        for value in (b"/URI", b"/JavaScript", b"/Launch", b"/EmbeddedFile")
    )


def test_actual_typed_call_inputs_remain_private_and_complete():
    setup = _setup()
    definition, configuration = scenario._definition_and_configuration(setup)
    assert configuration.owner_department_id == setup.department_id
    assert configuration.contributor_consent_policy_code == scenario.CONSENT
    assert [q.field_type.value for q in definition.sections[0].questions] == [
        "short_text",
        "safe_file",
    ]
    assert all(
        q.required and not q.staff_visible and not q.reviewer_visible
        for q in definition.sections[0].questions
    )
    assert definition.opens_at < definition.applicant_edit_until < definition.closes_at


def test_policy_precedes_application_and_any_owner_action(monkeypatch):
    monkeypatch.setattr(
        scenario,
        "require_programme_runtime_environment",
        Mock(side_effect=ProgrammeRehearsalEnvironmentError("postgresql_deferred")),
    )
    build, compose = Mock(), Mock()
    monkeypatch.setattr(programme_runtime, "build_candidate_application", build)
    monkeypatch.setattr(scenario, "_compose_proposal", compose)
    with pytest.raises(ProgrammeRehearsalEnvironmentError, match="deferred"):
        scenario.prepare_proposal_scenario(_setup())
    build.assert_not_called()
    compose.assert_not_called()


def test_actual_guarded_build_precedes_composition_and_failure_stops_it(monkeypatch):
    order = []
    monkeypatch.setattr(
        scenario,
        "require_programme_runtime_environment",
        lambda: SimpleNamespace(run_id=RUN),
    )
    monkeypatch.setattr(
        programme_runtime,
        "build_candidate_application",
        lambda: order.append("native-guard"),
    )
    compose = Mock(side_effect=lambda *_args, **_kwargs: order.append("compose"))
    monkeypatch.setattr(scenario, "_compose_proposal", compose)
    setup = _setup()
    scenario.prepare_proposal_scenario(setup)
    assert order == ["native-guard", "compose"]
    compose.assert_called_once_with(setup, run_id=RUN)
    compose.reset_mock()
    monkeypatch.setattr(
        programme_runtime,
        "build_candidate_application",
        Mock(side_effect=RuntimeError("unready")),
    )
    with pytest.raises(RuntimeError, match="unready"):
        scenario.prepare_proposal_scenario(setup)
    compose.assert_not_called()


def _mock_composition(monkeypatch, *, submitted=True):
    setup, lead, collaborator = _setup(), _person("lead"), _person("collaborator")
    authenticated = []

    def authenticate(self):
        authenticated.append(self.account_id)
        return SimpleNamespace(id=self.account_id)

    monkeypatch.setattr(SyntheticProgrammePerson, "authenticate", authenticate)
    monkeypatch.setattr(
        scenario, "_create_person", Mock(side_effect=[lead, collaborator])
    )
    names = (
        "create_programme_call",
        "activate_programme_call",
        "start_programme_proposal",
        "append_programme_proposal_answer",
        "invite_programme_proposal_collaborator",
        "accept_programme_proposal_invitation",
        "revise_programme_contributor_profile",
        "seal_programme_proposal",
        "respond_to_programme_proposal_revision",
        "submit_programme_proposal",
    )
    definition_id, submission_id = uuid4(), uuid4()
    events = []

    def result(name, **kwargs):
        events.append((name, kwargs))
        return commands.ProgrammeCommandResult(
            uuid4(),
            name,
            definition_id,
            submission_id,
            uuid4(),
            "mock",
            kwargs["expected_version"] + 1,
            replayed=False,
        )

    mocks = {}
    for name in names:
        mock = create_autospec(
            getattr(commands, name),
            side_effect=lambda _name=name, **kw: result(_name, **kw),
        )
        monkeypatch.setattr(commands, name, mock)
        mocks[name] = mock
    track, fmt = uuid4(), uuid4()
    title, pdf = uuid4(), uuid4()
    configured = SimpleNamespace(
        summary=SimpleNamespace(aggregate_version=2, version=1),
        sections=(
            SimpleNamespace(
                questions=(
                    SimpleNamespace(key="session-title", question_id=title),
                    SimpleNamespace(key="supporting-pdf", question_id=pdf),
                )
            ),
        ),
    )
    monkeypatch.setattr(
        queries,
        "get_managed_programme_call_configuration",
        create_autospec(
            queries.get_managed_programme_call_configuration, return_value=configured
        ),
    )

    def available(**_kwargs):
        return (
            SimpleNamespace(
                summary=SimpleNamespace(
                    call_id=mocks["activate_programme_call"].call_args.kwargs["call_id"]
                ),
                tracks=(SimpleNamespace(track_id=track),),
                formats=(SimpleNamespace(format_id=fmt),),
            ),
        )

    monkeypatch.setattr(
        queries,
        "available_programme_calls",
        create_autospec(queries.available_programme_calls, side_effect=available),
    )
    upload_result = commands.ProgrammeCommandResult(
        uuid4(),
        "upload",
        definition_id,
        submission_id,
        uuid4(),
        "mock",
        3,
        replayed=False,
    )

    def upload(**kwargs):
        assert kwargs["read_bytes"]() == scenario.synthetic_supporting_pdf()
        return upload_result

    monkeypatch.setattr(
        files,
        "upload_and_use_programme_file",
        create_autospec(files.upload_and_use_programme_file, side_effect=upload),
    )
    monkeypatch.setattr(
        files,
        "get_programme_file_upload_result",
        create_autospec(
            files.get_programme_file_upload_result,
            return_value=replace(upload_result, replayed=True),
        ),
    )
    frozen_values = {}

    def frozen(**kwargs):
        value = frozen_values.setdefault(kwargs["actor_id"], (uuid4(), uuid4()))
        return SimpleNamespace(
            own_contributor_id=value[0],
            own_profile=SimpleNamespace(profile_revision_id=value[1]),
            revision=SimpleNamespace(submitted=submitted),
            summary=SimpleNamespace(aggregate_version=10),
        )

    monkeypatch.setattr(
        personal,
        "get_self_programme_frozen_revision",
        create_autospec(
            personal.get_self_programme_frozen_revision, side_effect=frozen
        ),
    )
    return setup, lead, collaborator, events, frozen_values, authenticated


def test_composition_preserves_real_signatures_exact_seal_own_consent_and_upload(
    monkeypatch,
):
    setup, lead, collaborator, events, frozen, authenticated = _mock_composition(
        monkeypatch
    )
    result = scenario._compose_proposal(setup, run_id=RUN)
    assert result.version == 10
    assert result.lead == lead
    assert result.collaborator == collaborator
    for name, kwargs in events:
        assert kwargs["organization_id"] == setup.organization_id
        assert kwargs["edition_id"] == setup.edition_id
        assert "authorizer" not in kwargs
        assert "now" not in kwargs
        if name in {
            "accept_programme_proposal_invitation",
            "revise_programme_contributor_profile",
        }:
            assert kwargs["actor_id"] == collaborator.account_id
    responses = [
        kw for name, kw in events if name == "respond_to_programme_proposal_revision"
    ]
    assert [kw["actor_id"] for kw in responses] == [
        lead.account_id,
        collaborator.account_id,
    ]
    for kw in responses:
        response = kw["response"]
        assert response.revision_id == result.revision_id
        assert (response.contributor_id, response.profile_revision_id) == frozen[
            kw["actor_id"]
        ]
    assert authenticated.count(collaborator.account_id) >= 4
    assert (
        files.upload_and_use_programme_file.call_args.kwargs["intent"]
        is files.get_programme_file_upload_result.call_args.kwargs["intent"]
    )
    assert files.upload_and_use_programme_file.call_count == 1


@pytest.mark.parametrize("failure", ["replay", "submitted"])
def test_changed_upload_receipt_or_unsubmitted_seal_is_not_accepted(
    monkeypatch, failure
):
    setup, *_ = _mock_composition(monkeypatch, submitted=failure != "submitted")
    if failure == "replay":
        files.get_programme_file_upload_result.return_value = None
    with pytest.raises(scenario.ProgrammeProposalScenarioError):
        scenario._compose_proposal(setup, run_id=RUN)
    if failure == "replay":
        commands.invite_programme_proposal_collaborator.assert_not_called()


def test_exact_private_result_roundtrip_redacts_credentials():
    setup = _setup()
    result = _result(setup)
    document = json.loads(json.dumps(asdict(result), default=str))
    assert scenario.proposal_from_document(document, setup=setup) == result
    assert result.lead.password not in repr(result)


@pytest.mark.parametrize(
    "change",
    [
        "org",
        "edition",
        "department",
        "duplicate",
        "staff",
        "secret",
        "version",
        "extra",
        "uuid",
    ],
)
def test_result_decoder_rejects_scope_person_and_schema_drift(change):
    setup = _setup()
    document = json.loads(json.dumps(asdict(_result(setup)), default=str))
    if change in {"org", "edition", "department"}:
        document[
            {
                "org": "organization_id",
                "edition": "edition_id",
                "department": "department_id",
            }[change]
        ] = str(uuid4())
    elif change == "duplicate":
        document["collaborator"] = document["lead"]
    elif change == "staff":
        document["lead"]["account_id"] = str(setup.intake_person.account_id)
    elif change == "secret":
        document["lead"]["password"] = "bad"
    elif change == "version":
        document["version"] = True
    elif change == "extra":
        document["unexpected"] = True
    else:
        document["revision_id"] = "not-uuid"
    with pytest.raises(scenario.ProgrammeProposalScenarioError, match="result_invalid"):
        scenario.proposal_from_document(document, setup=setup)


def test_private_child_policy_precedes_stdin_and_redacts_failure(monkeypatch, capsys):
    stdin = Mock()
    monkeypatch.setattr(scenario.sys, "stdin", stdin)
    monkeypatch.setattr(
        scenario,
        "require_programme_runtime_environment",
        Mock(side_effect=ProgrammeRehearsalEnvironmentError("deferred")),
    )
    with pytest.raises(ProgrammeRehearsalEnvironmentError):
        scenario._main()
    stdin.read.assert_not_called()
    monkeypatch.setattr(scenario, "require_programme_runtime_environment", lambda: None)
    monkeypatch.setattr(scenario.sys, "stdin", io.StringIO("private malformed payload"))
    with pytest.raises(SystemExit) as failure:
        scenario._main()
    assert failure.value.code == 2
    assert capsys.readouterr().out == ""
