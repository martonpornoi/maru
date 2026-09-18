"""Database-free candidate ACL preparation, never native permission evidence."""

from types import SimpleNamespace
from unittest.mock import Mock

import psycopg
import pytest

from tests.rehearsals import programme_candidate_acl as acl
from tests.rehearsals import programme_runtime_privileges as contract
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRehearsalEnvironmentError,
)


def test_literal_inventory_preserves_all_unrelated_native_limits():
    projected = contract.candidate_relation_classes()
    assert len(contract.PRIVILEGES) == 82
    assert set(projected[0]) == {
        "public.django_migrations",
        "public.authorization_authorityprovenanceactivation",
        "public.authorization_provenanceactivationlatch",
        "public.identity_platforminvitationretentionpolicycontrol",
        "public.audit_auditnativemutationwitness",
        "public.scheduling_schedulingreleasedependencychange",
    }
    assert set(projected[1]) - set(contract._BASELINE[1]) == contract.INSERT
    assert projected[2] is contract._BASELINE[2]
    assert set(projected[3]) - set(contract._BASELINE[3]) == contract.INSERT_UPDATE
    assert set(projected[4]) - set(contract._BASELINE[4]) == contract.INSERT_DELETE
    assert set(contract.INSERT_UPDATE_DELETE) == {
        "public.applications_programmecalltrack",
        "public.applications_programmecallformat",
    }
    for name, original in zip(contract._NAMES, contract._BASELINE, strict=True):
        assert getattr(contract.owner, name) is original
    assert "public.applications_applicationcommandreceipt" not in contract.PRIVILEGES
    assert contract.PRIVILEGES[
        "public.applications_programmeproposalcontributorprofilerevision"
    ] == ("INSERT", "UPDATE")


@pytest.mark.parametrize("defect", ["unknown", "overlap", "other_class"])
def test_changed_inventory_is_rejected(defect, monkeypatch):
    if defect == "unknown":
        monkeypatch.setattr(contract, "PRIVILEGES", {"public.unknown": ("INSERT",)})
    elif defect == "overlap":
        monkeypatch.setattr(
            contract, "INSERT", contract.INSERT | contract.INSERT_UPDATE
        )
    else:
        monkeypatch.setattr(
            contract,
            "_BASELINE",
            (
                contract._BASELINE[0],
                (*contract._BASELINE[1], *contract.INSERT),
                *contract._BASELINE[2:],
            ),
        )
    with pytest.raises(contract.ProgrammePrivilegeError):
        contract.candidate_relation_classes()


@pytest.fixture
def isolated_contract(monkeypatch):
    baseline_owner = contract.owner
    fake_owner = SimpleNamespace(
        **dict(zip(contract._NAMES, contract._BASELINE, strict=True)),
        _RUNTIME_DATABASE_ROLE_SAFETY_QUERY=contract._QUERY,
        RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V4=contract._FUNCTIONS,
    )
    monkeypatch.setattr(contract, "owner", fake_owner)
    monkeypatch.setattr(contract, "require_programme_runtime_environment", Mock())
    monkeypatch.setattr(
        contract,
        "adoption",
        SimpleNamespace(
            ADOPTION_PROFILES={
                contract.PROGRAMME_REHEARSAL_PROFILE.key: (
                    contract.PROGRAMME_REHEARSAL_PROFILE
                )
            }
        ),
    )
    return fake_owner, baseline_owner


def test_installation_changes_only_declared_input_classes_not_probe(isolated_contract):
    fake_owner, original = isolated_contract
    contract.install_isolated_candidate_privilege_contract()
    for name, projected, baseline in zip(
        contract._NAMES,
        contract.candidate_relation_classes(),
        contract._BASELINE,
        strict=True,
    ):
        assert getattr(fake_owner, name) == projected
        assert getattr(original, name) is baseline
    assert fake_owner._RUNTIME_DATABASE_ROLE_SAFETY_QUERY is contract._QUERY
    assert (
        fake_owner.RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V4 is contract._FUNCTIONS
    )
    with pytest.raises(contract.ProgrammePrivilegeError, match="baseline_changed"):
        contract.install_isolated_candidate_privilege_contract()


@pytest.mark.parametrize("defect", ["profile", "classes", "query", "functions"])
def test_changed_baseline_cannot_be_overwritten(defect, isolated_contract):
    fake_owner, _original = isolated_contract
    if defect == "profile":
        contract.adoption.ADOPTION_PROFILES.clear()
    elif defect == "classes":
        setattr(fake_owner, contract._NAMES[0], ())
    elif defect == "query":
        fake_owner._RUNTIME_DATABASE_ROLE_SAFETY_QUERY = "SELECT true"
    else:
        fake_owner.RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V4 = ()
    before = vars(fake_owner).copy()
    with pytest.raises(contract.ProgrammePrivilegeError):
        contract.install_isolated_candidate_privilege_contract()
    assert vars(fake_owner) == before


def test_deferred_policy_precedes_any_contract_install(isolated_contract, monkeypatch):
    fake_owner, _original = isolated_contract
    monkeypatch.setattr(
        contract,
        "require_programme_runtime_environment",
        Mock(side_effect=ProgrammeRehearsalEnvironmentError("deferred")),
    )
    before = vars(fake_owner).copy()
    with pytest.raises(ProgrammeRehearsalEnvironmentError):
        contract.install_isolated_candidate_privilege_contract()
    assert vars(fake_owner) == before


@pytest.mark.parametrize("result", [(True,), (False,), (None,), None])
def test_reference_guard_uses_complete_table_and_column_boundary(result):
    cursor = Mock()
    cursor.fetchone.return_value = result
    if result == (True,):
        contract.require_candidate_reference_boundary(cursor)
    else:
        with pytest.raises(contract.ProgrammePrivilegeError):
            contract.require_candidate_reference_boundary(cursor)
    query, parameters = cursor.execute.call_args.args
    assert "has_table_privilege" in query
    assert "has_column_privilege" in query
    assert "pg_has_role(current_user, reachable.oid, 'SET')" in query
    assert "reachable.oid, relation.oid" in query
    assert parameters == [82, sorted(contract.PRIVILEGES)]


@pytest.fixture
def grant_plane(monkeypatch):
    lease = SimpleNamespace(
        database_name="synthetic", port=54321, admin_password="private"
    )
    connection = Mock()
    connection.__enter__ = Mock(return_value=connection)
    connection.__exit__ = Mock(return_value=False)
    connection.execute.return_value.fetchone.side_effect = [
        ("synthetic", "postgres", "postgres", 170011),
        (False, True),
        (True,),
    ]
    connect = Mock(return_value=connection)
    verify = Mock()
    monkeypatch.setattr(acl, "require_programme_rehearsal_request", Mock())
    monkeypatch.setattr(acl, "_verify_lease", verify)
    monkeypatch.setattr(acl.psycopg, "connect", connect)
    return SimpleNamespace(
        lease=lease, connection=connection, connect=connect, verify=verify
    )


def test_grant_plane_changes_only_literal_table_operations_after_preflight(grant_plane):
    acl.install_candidate_table_privileges(grant_plane.lease)
    statements = [
        call.args[0] for call in grant_plane.connection.execute.call_args_list
    ]
    assert statements[1].startswith("LOCK TABLE public.events_eventedition")
    grants = [
        statement.as_string()
        for statement in statements
        if not isinstance(statement, str)
    ]
    assert len(grants) == 4
    assert all(
        text.startswith("GRANT ") and text.endswith(" TO maru_runtime")
        for text in grants
    )
    assert sum(text.count('"public".') for text in grants) == 82
    assert not any(
        "ALL " in text or "FUNCTION" in text or "WITH GRANT" in text for text in grants
    )
    grant_plane.verify.assert_called_with(
        grant_plane.lease, acl.require_programme_rehearsal_request()
    )
    assert grant_plane.verify.call_count == 2


@pytest.mark.parametrize("stage", ["identity", "schema", "acl"])
def test_preflight_refusal_never_grants(stage, grant_plane):
    responses = [("synthetic", "postgres", "postgres", 170011), (False, True), (True,)]
    responses[{"identity": 0, "schema": 1, "acl": 2}[stage]] = None
    grant_plane.connection.execute.return_value.fetchone.side_effect = responses
    with pytest.raises(acl.ProgrammeProvisioningError):
        acl.install_candidate_table_privileges(grant_plane.lease)
    assert all(
        isinstance(call.args[0], str)
        for call in grant_plane.connection.execute.call_args_list
    )


def test_failed_lease_and_deferred_policy_prevent_connection(grant_plane, monkeypatch):
    grant_plane.verify.side_effect = acl.ProgrammeProvisioningError("foreign")
    with pytest.raises(acl.ProgrammeProvisioningError):
        acl.install_candidate_table_privileges(grant_plane.lease)
    grant_plane.connect.assert_not_called()
    grant_plane.verify.reset_mock()
    monkeypatch.setattr(
        acl,
        "require_programme_rehearsal_request",
        Mock(side_effect=ProgrammeRehearsalEnvironmentError("deferred")),
    )
    with pytest.raises(ProgrammeRehearsalEnvironmentError):
        acl.install_candidate_table_privileges(grant_plane.lease)
    grant_plane.verify.assert_not_called()


def test_database_failure_is_minimized(grant_plane):
    grant_plane.connection.execute.side_effect = psycopg.Error("private server detail")
    with pytest.raises(
        acl.ProgrammeProvisioningError, match=r"^candidate_acl_installation_failed$"
    ):
        acl.install_candidate_table_privileges(grant_plane.lease)
