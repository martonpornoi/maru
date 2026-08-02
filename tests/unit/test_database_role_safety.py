from unittest.mock import MagicMock, patch

import pytest

from maru.authorization import provenance_readiness
from maru.authorization.database_role_safety import (
    RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V1,
    RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V2,
    RUNTIME_DATABASE_SELECT_INSERT_RELATIONS,
    RUNTIME_DATABASE_SELECT_INSERT_UPDATE_RELATIONS,
    RUNTIME_DATABASE_SELECT_ONLY_RELATIONS,
    RuntimeDatabaseRoleProbeError,
    RuntimeDatabaseRoleSafety,
    probe_runtime_database_role_safety,
)


def test_runtime_relation_privilege_profiles_are_exact_and_disjoint() -> None:
    assert RUNTIME_DATABASE_SELECT_INSERT_RELATIONS == (
        "public.workforce_editionstructurecommandreceipt",
    )
    assert RUNTIME_DATABASE_SELECT_INSERT_UPDATE_RELATIONS == (
        "public.workforce_editionstructurecontrol",
    )
    profiles = (
        set(RUNTIME_DATABASE_SELECT_ONLY_RELATIONS),
        set(RUNTIME_DATABASE_SELECT_INSERT_RELATIONS),
        set(RUNTIME_DATABASE_SELECT_INSERT_UPDATE_RELATIONS),
    )
    assert all(
        not left & right
        for index, left in enumerate(profiles)
        for right in profiles[index + 1 :]
    )
    assert "public.workforce_department" not in set().union(*profiles)


def test_v2_function_allowlist_preserves_frozen_v1_and_adds_latch_helper() -> None:
    assert len(RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V1) == 18
    assert RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V2[:-1] == (
        RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V1
    )


def test_every_v2_runtime_function_has_a_readiness_definition_fingerprint() -> None:
    def normalize(identity: str) -> str:
        return identity.removeprefix("public.").replace(
            "timestamp with time zone",
            "timestamptz",
        )

    allowlisted = {
        normalize(identity)
        for identity in RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V2
    }

    assert allowlisted <= set(provenance_readiness._CORE_FUNCTIONS)
    assert allowlisted <= set(provenance_readiness._FUNCTION_DEFINITION_SHA256)
    assert RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V2[-1] == (
        "public.maru_lock_authority_provenance_latch()"
    )


def _result(**overrides: bool) -> RuntimeDatabaseRoleSafety:
    values = {
        "role_exists": True,
        "can_login": True,
        "attributes_safe": True,
        "memberships_safe": True,
        "database_ownership_safe": True,
        "user_schema_ownership_safe": True,
        "user_relation_ownership_safe": True,
        "user_function_ownership_safe": True,
        "database_privileges_safe": True,
        "user_schema_privileges_safe": True,
        "table_privileges_safe": True,
        "parameter_privileges_safe": True,
        "role_settings_safe": True,
        "session_replication_role_is_origin": True,
        "database_connect_available": True,
        "user_schema_usage_available": True,
        "required_relation_privileges_available": True,
        "sequence_privileges_safe": True,
        "required_sequence_privileges_available": True,
        "grant_options_safe": True,
        "function_execute_boundary_safe": True,
        "required_function_execute_available": True,
        "current_user_matches": True,
        "session_user_matches": True,
        "authenticated_user_matches": True,
    }
    values.update(overrides)
    return RuntimeDatabaseRoleSafety(**values)


def test_result_separates_future_role_proof_from_current_session_match() -> None:
    future_role = _result(current_user_matches=False)

    assert future_role.target_role_is_safe
    assert not future_role.current_session_is_safe

    for field in (
        "role_exists",
        "can_login",
        "attributes_safe",
        "memberships_safe",
        "database_ownership_safe",
        "user_schema_ownership_safe",
        "user_relation_ownership_safe",
        "user_function_ownership_safe",
        "database_privileges_safe",
        "user_schema_privileges_safe",
        "table_privileges_safe",
        "parameter_privileges_safe",
        "role_settings_safe",
        "session_replication_role_is_origin",
        "database_connect_available",
        "user_schema_usage_available",
        "required_relation_privileges_available",
        "sequence_privileges_safe",
        "required_sequence_privileges_available",
        "grant_options_safe",
        "function_execute_boundary_safe",
        "required_function_execute_available",
    ):
        assert not _result(**{field: False}).target_role_is_safe

    for field in (
        "current_user_matches",
        "session_user_matches",
        "authenticated_user_matches",
    ):
        assert _result(**{field: False}).target_role_is_safe
        assert not _result(**{field: False}).current_session_is_safe


@patch("maru.authorization.database_role_safety.connections")
def test_probe_binds_the_role_and_required_function_identities(
    configured_connections: MagicMock,
) -> None:
    cursor = configured_connections.__getitem__.return_value.cursor.return_value
    cursor.__enter__.return_value.fetchone.return_value = (True,) * 25
    injected_name = "role' OR TRUE --"

    result = probe_runtime_database_role_safety(
        role_name=injected_name,
        using="security",
    )

    query, parameters = cursor.__enter__.return_value.execute.call_args.args
    assert injected_name not in query
    assert parameters == [
        injected_name,
        list(RUNTIME_DATABASE_SELECT_ONLY_RELATIONS),
        list(RUNTIME_DATABASE_SELECT_INSERT_RELATIONS),
        list(RUNTIME_DATABASE_SELECT_INSERT_UPDATE_RELATIONS),
        list(RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V2),
    ]
    configured_connections.__getitem__.assert_called_once_with("security")
    assert result.current_session_is_safe


@patch("maru.authorization.database_role_safety.connections")
def test_probe_query_covers_identity_integrity_and_nondelegation_boundaries(
    configured_connections: MagicMock,
) -> None:
    cursor = configured_connections.__getitem__.return_value.cursor.return_value
    cursor.__enter__.return_value.fetchone.return_value = (True,) * 25

    probe_runtime_database_role_safety(role_name="maru_runtime")

    query = cursor.__enter__.return_value.execute.call_args.args[0]
    assert "SESSION_USER" in query
    assert "pg_stat_activity" in query
    assert "pg_backend_pid()" in query
    assert "lower(target.rolname) LIKE 'pg\\_%%'" in query
    assert "pg_parameter_acl" in query
    assert "pg_db_role_setting" in query
    assert "current_setting('session_replication_role'" in query
    assert "membership.admin_option" in query
    assert "privilege.is_grantable" in query
    assert "has_sequence_privilege" in query
    assert "'UPDATE'" in query
    assert "'REFERENCES'" in query
    assert "FALSE,\n        FALSE,\n        FALSE,\n        TRUE" in query
    for identity in (
        *RUNTIME_DATABASE_SELECT_ONLY_RELATIONS,
        *RUNTIME_DATABASE_SELECT_INSERT_RELATIONS,
        *RUNTIME_DATABASE_SELECT_INSERT_UPDATE_RELATIONS,
    ):
        assert identity not in query


@patch("maru.authorization.database_role_safety.connections")
def test_probe_rejects_an_unexpected_catalog_shape(
    configured_connections: MagicMock,
) -> None:
    cursor = configured_connections.__getitem__.return_value.cursor.return_value
    cursor.__enter__.return_value.fetchone.return_value = (True, False)

    with pytest.raises(RuntimeDatabaseRoleProbeError, match="invalid"):
        probe_runtime_database_role_safety(role_name="maru_runtime")
