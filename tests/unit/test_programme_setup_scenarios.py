"""Pure/mocked genuine-owner composition contracts; no native acceptance claim."""

import io
import json
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from django.contrib import auth
from django.core import mail
from django.test import override_settings

from maru.authorization import programme_role_commands
from maru.authorization.catalog import ScopeLevel
from maru.events import programme_setup
from maru.identity import queries as identity_queries
from maru.identity import services as identity_services
from maru.organizations import programme_setup_references, representation, services
from tests.rehearsals import programme_runtime
from tests.rehearsals import programme_setup_scenarios as scenarios
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRehearsalEnvironmentError,
)

RUN = "1234567890abcdef1234567890abcdef"
ORIGIN = "https://127.0.0.1:55443"


def _person(label):
    return scenarios.SyntheticProgrammePerson(
        uuid4(), f"{label}@example.invalid", "a" * 43
    )


def _document():
    value = scenarios.ProgrammeSetupScenario(
        "new_foundation",
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        "maru_operators",
        uuid4(),
        (_person("a"), _person("b")),
        _person("intake"),
        (uuid4(), uuid4()),
    )
    return json.loads(json.dumps(asdict(value), default=str))


def test_fixed_child_result_roundtrip_keeps_secret_handles_out_of_repr():
    result = scenarios.scenario_from_document(_document(), mode="new_foundation")
    assert len(result.role_assignment_ids) == 2
    assert "a" * 43 not in repr(result)
    assert "a" * 43 not in repr(result.controllers[0])


@pytest.mark.parametrize(
    "change",
    ["foreign_mode", "shared_person", "extra", "root", "password", "grant", "uuid"],
)
def test_fixed_child_result_rejects_contract_drift(change):
    document = _document()
    if change == "foreign_mode":
        document["mode"] = "existing_series"
    elif change == "shared_person":
        document["controllers"][1] = document["controllers"][0]
    elif change == "extra":
        document["extra"] = "unexpected"
    elif change == "root":
        document["representation_code"] = "executive_board"
    elif change == "password":
        document["intake_person"]["password"] = "short"
    elif change == "grant":
        document["role_assignment_ids"] = []
    else:
        document["edition_id"] = "foreign"
    with pytest.raises(scenarios.ProgrammeSetupScenarioError, match="result_invalid"):
        scenarios.scenario_from_document(document, mode="new_foundation")


@pytest.mark.parametrize(
    "link",
    [
        ORIGIN + "/accounts/verify-email/?token=real-token",
        "https://foreign.invalid/accounts/verify-email/?token=secret",
        ORIGIN + "/accounts/recover-account/?token=secret",
        ORIGIN + "/accounts/verify-email/?token=one&token=two",
        ORIGIN + "/accounts/verify-email/?malformed",
        ORIGIN + "/accounts/verify-email/?token=one#fragment",
    ],
)
def test_only_own_recipient_same_origin_purpose_single_token_mail_is_consumed(link):
    messages = [SimpleNamespace(to=["own@example.invalid"], body=f"Hello\n\n{link}\n")]
    if link.endswith("real-token"):
        assert (
            scenarios._verification_token(
                messages, email="own@example.invalid", origin=ORIGIN
            )
            == "real-token"
        )
    else:
        with pytest.raises(
            scenarios.ProgrammeSetupScenarioError, match="link_unavailable"
        ):
            scenarios._verification_token(
                messages, email="own@example.invalid", origin=ORIGIN
            )
    with pytest.raises(scenarios.ProgrammeSetupScenarioError, match="mail_unavailable"):
        scenarios._verification_token(
            messages, email="foreign@example.invalid", origin=ORIGIN
        )


def test_create_person_consumes_actual_delivered_token_without_exposing_test_token(
    monkeypatch,
):
    account_id = uuid4()
    unverified = SimpleNamespace(id=account_id, has_verified_email=False)
    verified = SimpleNamespace(
        id=account_id,
        has_verified_email=True,
        is_active=True,
        is_platform_administrator=False,
    )
    monkeypatch.setattr(mail, "outbox", [], raising=False)

    def bootstrap(**kwargs):
        mail.outbox.append(
            SimpleNamespace(
                to=[kwargs["email"]],
                body=ORIGIN + "/accounts/verify-email/?token=delivered-only",
            )
        )
        return unverified, SimpleNamespace(raw_token=None)

    bootstrap_mock = Mock(side_effect=bootstrap)
    monkeypatch.setattr(identity_services, "bootstrap_account", bootstrap_mock)
    consume = Mock(return_value=verified)
    monkeypatch.setattr(identity_services, "consume_identity_challenge", consume)
    authenticate = Mock(return_value=verified)
    monkeypatch.setattr(auth, "authenticate", authenticate)
    with override_settings(MARU_PUBLIC_BASE_URL=ORIGIN):
        result = scenarios._create_person("intake", run_id=RUN)
    assert result.account_id == account_id
    assert consume.call_args.kwargs["raw_token"] == "delivered-only"
    assert consume.call_args.kwargs["purpose"] == "verify_email"
    assert bootstrap_mock.call_args.kwargs["password"] == result.password
    authenticate.assert_called_once_with(
        username=result.email, password=result.password
    )


@pytest.mark.parametrize(
    "invalid", [None, "inactive", "unverified", "platform", "other"]
)
def test_person_reauthenticates_and_refuses_changed_identity(monkeypatch, invalid):
    person = _person("person")
    account = SimpleNamespace(
        id=person.account_id,
        is_active=True,
        has_verified_email=True,
        is_platform_administrator=False,
    )
    if invalid == "inactive":
        account.is_active = False
    elif invalid == "unverified":
        account.has_verified_email = False
    elif invalid == "platform":
        account.is_platform_administrator = True
    elif invalid == "other":
        account.id = uuid4()
    else:
        account = None
    monkeypatch.setattr(auth, "authenticate", Mock(return_value=account))
    with pytest.raises(
        scenarios.ProgrammeSetupScenarioError, match="person_unavailable"
    ):
        person.authenticate()


def test_deferred_policy_precedes_startup_and_all_owner_work(monkeypatch):
    monkeypatch.setattr(
        scenarios,
        "require_programme_runtime_environment",
        Mock(side_effect=ProgrammeRehearsalEnvironmentError("postgresql_deferred")),
    )
    startup = Mock()
    monkeypatch.setattr(programme_runtime, "build_candidate_application", startup)
    with pytest.raises(ProgrammeRehearsalEnvironmentError, match="postgresql_deferred"):
        scenarios.prepare_setup_scenario(
            mode="new_foundation", administrator_password="private"
        )
    startup.assert_not_called()


@pytest.fixture
def setup_owners(monkeypatch):
    monkeypatch.setattr(
        scenarios,
        "require_programme_runtime_environment",
        lambda: SimpleNamespace(run_id=RUN),
    )
    monkeypatch.setattr(programme_runtime, "build_candidate_application", Mock())
    administrator = SimpleNamespace(
        id=uuid4(), is_active=True, is_platform_administrator=True
    )
    monkeypatch.setattr(auth, "authenticate", Mock(return_value=administrator))
    monkeypatch.setattr(
        identity_queries,
        "current_platform_administrator_is_available",
        Mock(return_value=True),
    )
    monkeypatch.setattr(scenarios, "_require_fresh_database", Mock())
    people = [_person("a"), _person("b"), _person("intake")]
    monkeypatch.setattr(scenarios, "_create_person", Mock(side_effect=people))
    activate = Mock()
    monkeypatch.setattr(scenarios, "_activate_root", activate)
    assignments = (uuid4(), uuid4())
    approve = Mock(return_value=assignments)
    monkeypatch.setattr(scenarios, "_approve_initial_roles", approve)
    result = SimpleNamespace(
        organization_id=uuid4(),
        series_id=uuid4(),
        edition_id=uuid4(),
        department_id=uuid4(),
        representation_id=uuid4(),
        receipt_id=uuid4(),
        replayed=False,
    )
    replay = SimpleNamespace(**(vars(result) | {"replayed": True}))
    setup = Mock(side_effect=[result, replay])
    monkeypatch.setattr(programme_setup, "setup_programme_foundation", setup)
    root = SimpleNamespace(
        representation_id=result.representation_id,
        representation_code="maru_operators",
        representation_version=5,
        representation_state="active",
        fingerprint="f" * 64,
    )
    resolve = Mock(return_value=root)
    monkeypatch.setattr(
        programme_setup_references, "resolve_programme_setup_foundation", resolve
    )
    monkeypatch.setattr(
        services,
        "create_draft_organization",
        Mock(return_value=SimpleNamespace(id=result.organization_id)),
    )
    monkeypatch.setattr(
        services,
        "create_convention_series",
        Mock(return_value=SimpleNamespace(id=result.series_id)),
    )
    for name in ("provision_executive_board", "provision_maru_operators"):
        monkeypatch.setattr(
            representation,
            name,
            Mock(return_value=SimpleNamespace(id=result.representation_id)),
        )
    return SimpleNamespace(
        administrator=administrator,
        setup=setup,
        root=root,
        resolve=resolve,
        activate=activate,
        approve=approve,
        result=result,
    )


@pytest.mark.parametrize("mode", scenarios.SETUP_MODES)
def test_three_modes_preserve_source_root_and_exact_retry_before_narrow_roles(
    setup_owners, mode
):
    owners = setup_owners
    owners.root.representation_code = (
        "executive_board" if mode == "existing_organization" else "maru_operators"
    )
    result = scenarios.prepare_setup_scenario(
        mode=mode, administrator_password="synthetic"
    )
    assert result.mode == mode
    assert result.representation_code == owners.root.representation_code
    first, retry = owners.setup.call_args_list
    assert first.kwargs["details"] == retry.kwargs["details"]
    assert first.kwargs["idempotency_key"] == retry.kwargs["idempotency_key"]
    assert first.kwargs["correlation_id"] != retry.kwargs["correlation_id"]
    details = first.kwargs["details"]
    assert details.mode == mode
    assert (details.organization_id is None) == (mode == "new_foundation")
    assert (details.series_id is not None) == (mode == "existing_series")
    assert details.foundation_fingerprint == (
        "" if mode == "new_foundation" else "f" * 64
    )
    assert owners.activate.call_count == 1
    assert owners.approve.call_count == 1
    assert representation.provision_executive_board.call_count == (
        mode == "existing_organization"
    )
    assert representation.provision_maru_operators.call_count == (
        mode == "existing_series"
    )


def test_actual_controller_persons_accept_their_own_invitations(monkeypatch):
    people = (_person("a"), _person("b"))
    actors = {
        person.email: SimpleNamespace(
            id=person.account_id,
            is_active=True,
            has_verified_email=True,
            is_platform_administrator=False,
        )
        for person in people
    }
    monkeypatch.setattr(
        auth, "authenticate", lambda **kwargs: actors[kwargs["username"]]
    )
    appointments = [SimpleNamespace(id=uuid4(), invitation_version=n) for n in (1, 2)]
    invite = Mock(side_effect=appointments)
    accept = Mock()
    activate = Mock()
    monkeypatch.setattr(representation, "invite_representation_controller", invite)
    monkeypatch.setattr(representation, "respond_to_representation_invitation", accept)
    monkeypatch.setattr(representation, "activate_representation", activate)
    root_id = uuid4()
    monkeypatch.setattr(
        programme_setup_references,
        "resolve_programme_setup_foundation",
        Mock(
            return_value=SimpleNamespace(
                representation_id=root_id, representation_version=5
            )
        ),
    )
    administrator = object()
    scenarios._activate_root(
        administrator, organization_id=uuid4(), representation_id=root_id, people=people
    )
    for n, call in enumerate(accept.call_args_list):
        assert call.kwargs["actor"].id == people[n].account_id
        assert call.kwargs["appointment_id"] == appointments[n].id
        assert call.kwargs["accept"] is True
    activate.assert_called_once()
    assert activate.call_args.kwargs["expected_version"] == 5


def test_initial_roles_require_distinct_actual_approver_and_exact_scopes(monkeypatch):
    people = (_person("a"), _person("b"))
    intake = _person("intake")
    actors = {
        person.email: SimpleNamespace(
            id=person.account_id,
            is_active=True,
            has_verified_email=True,
            is_platform_administrator=False,
        )
        for person in people
    }
    monkeypatch.setattr(
        auth, "authenticate", lambda **kwargs: actors[kwargs["username"]]
    )
    request = Mock(
        side_effect=[
            SimpleNamespace(request_id=uuid4()),
            SimpleNamespace(request_id=uuid4()),
        ]
    )
    decide = Mock(
        side_effect=[
            SimpleNamespace(role_assignment_id=uuid4()),
            SimpleNamespace(role_assignment_id=uuid4()),
        ]
    )
    monkeypatch.setattr(programme_role_commands, "request_programme_role", request)
    monkeypatch.setattr(programme_role_commands, "decide_programme_role", decide)
    result = SimpleNamespace(
        organization_id=uuid4(), edition_id=uuid4(), department_id=uuid4()
    )
    assignments = scenarios._approve_initial_roles(
        result, people=people, intake_person=intake
    )
    assert len(assignments) == 2
    for n, (author, approval) in enumerate(
        zip(request.call_args_list, decide.call_args_list, strict=True)
    ):
        assert author.kwargs["actor"].id == people[0].account_id
        assert approval.kwargs["actor"].id == people[1].account_id
        assert author.kwargs["scope"] == approval.kwargs["scope"]
        assert author.kwargs["scope"].level == (
            ScopeLevel.EDITION if n == 0 else ScopeLevel.DEPARTMENT
        )
        assert author.kwargs["scope"].department_id == (
            None if n == 0 else result.department_id
        )
        assert author.kwargs["details"].recipe_code == (
            "edition-coordination" if n == 0 else "intake"
        )


@pytest.mark.parametrize(
    "raw",
    ["{}", "null", "x" * 4097, '{"mode":"foreign","administrator_password":"private"}'],
)
def test_child_protocol_refuses_bad_input_without_secret_output(
    monkeypatch, capsys, raw
):
    monkeypatch.setattr(scenarios, "require_programme_runtime_environment", Mock())
    monkeypatch.setattr(scenarios.sys, "stdin", io.StringIO(raw))
    prepare = Mock()
    monkeypatch.setattr(scenarios, "prepare_setup_scenario", prepare)
    with pytest.raises(SystemExit) as error:
        scenarios._main()
    assert error.value.code == 2
    prepare.assert_not_called()
    assert capsys.readouterr().out == ""
