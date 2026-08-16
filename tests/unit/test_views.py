from unittest.mock import MagicMock, call, patch

import pytest
from django.db.utils import OperationalError
from django.test import override_settings
from rest_framework.test import APIClient

from maru.authorization.database_role_safety import RuntimeDatabaseRoleSafety
from maru.authorization.models import (
    AUTHORITY_PROVENANCE_ACTIVATION_POLICY_VERSION,
    AUTHORITY_PROVENANCE_ACTIVE_GENERATION,
    AUTHORITY_PROVENANCE_CONTRACT_VERSION,
)
from maru.core import views


@pytest.fixture(autouse=True)
def _default_logistics_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep existing health cases focused unless one integrity gate is under test."""

    monkeypatch.setattr(views, "logistics_current_session_is_ready", lambda: True)
    monkeypatch.setattr(
        views,
        "applications_database_integrity_is_ready",
        lambda: True,
    )
    monkeypatch.setattr(
        views,
        "charities_database_integrity_is_ready",
        lambda: True,
    )
    monkeypatch.setattr(
        views,
        "catalog_database_integrity_is_ready",
        lambda: True,
    )
    monkeypatch.setattr(
        views,
        "venues_database_integrity_is_ready",
        lambda: True,
    )


_READY_BOUNDED_DOMAIN_DEPENDENCIES = {
    "applications_integrity": "ok",
    "charities_integrity": "ok",
    "catalog_integrity": "ok",
    "venues_integrity": "ok",
}


def _runtime_role_safety(
    **overrides: bool,
) -> RuntimeDatabaseRoleSafety:
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


def test_platform_home_is_a_browser_friendly_start_page() -> None:
    response = APIClient().get("/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")
    content = response.content.decode()
    assert "Maru is running." in content
    assert "Use this page to enter the local Maru environment" in content
    assert "For example:" in content
    assert 'href="/health/ready"' in content
    assert 'href="/api/v1/docs/"' in content
    assert 'href="/admin/"' in content
    assert 'href="/admin/records/"' not in content
    assert 'href="/manage/"' not in content


def test_liveness_does_not_touch_dependencies() -> None:
    response = APIClient().get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "X-Request-ID" in response


def test_build_info_contains_only_release_identity(settings: object) -> None:
    settings.BUILD_VERSION = "test-release"  # type: ignore[attr-defined]
    settings.BUILD_COMMIT = "abc123"  # type: ignore[attr-defined]

    response = APIClient().get("/api/v1/meta/build")

    assert response.status_code == 200
    assert response.json() == {
        "service": "maru",
        "version": "test-release",
        "commit": "abc123",
    }


@patch("maru.core.views.connection.cursor")
def test_readiness_checks_database(cursor: MagicMock) -> None:
    cursor.return_value.__enter__.return_value.fetchone.return_value = (False, False)
    response = APIClient().get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "dependencies": {
            "database": "ok",
            **_READY_BOUNDED_DOMAIN_DEPENDENCIES,
            "logistics": "ok",
        },
    }
    cursor.return_value.__enter__.return_value.execute.assert_called_once_with(
        views._AUTHORITY_PROVENANCE_TABLE_HEALTH_QUERY
    )
    assert cursor.call_count == 1


@patch(
    "maru.core.views.connection.cursor",
    side_effect=OperationalError("private connection detail"),
)
def test_readiness_returns_safe_failure(cursor: MagicMock) -> None:
    response = APIClient().get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "dependencies": {"database": "unavailable"},
    }


@override_settings(REQUIRE_EXACT_AUTHORITY_PROVENANCE=True)
@patch("maru.core.views.connection.cursor")
def test_readiness_requires_active_exact_authority_provenance(
    cursor: MagicMock,
) -> None:
    cursor.return_value.__enter__.return_value.fetchone.side_effect = [
        (True, True),
        (17, False, True, True, False),
    ]
    response = APIClient().get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "dependencies": {
            "database": "ok",
            "authority_provenance": "unavailable",
        },
    }
    assert cursor.call_count == 2


@override_settings(
    REQUIRE_EXACT_AUTHORITY_PROVENANCE=True,
    RUNTIME_DATABASE_ROLE="maru_runtime",
)
@patch(
    "maru.core.views.authority_provenance_runtime_contract_is_ready",
    return_value=True,
)
@patch("maru.core.views.probe_runtime_database_role_safety")
@patch("maru.core.views.connection.cursor")
def test_readiness_accepts_active_exact_authority_provenance(
    cursor: MagicMock,
    role_probe: MagicMock,
    runtime_contract: MagicMock,
) -> None:
    role_probe.return_value = _runtime_role_safety()
    cursor.return_value.__enter__.return_value.fetchone.side_effect = [
        (True, True),
        (17, False, True, True, True),
    ]
    response = APIClient().get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "dependencies": {
            "database": "ok",
            "authority_provenance": "ok",
            **_READY_BOUNDED_DOMAIN_DEPENDENCIES,
            "logistics": "ok",
        },
    }
    cursor.return_value.__enter__.return_value.execute.assert_has_calls(
        [
            call(views._AUTHORITY_PROVENANCE_TABLE_HEALTH_QUERY),
            call(
                views._EXACT_AUTHORITY_PROVENANCE_HEALTH_QUERY,
                (
                    AUTHORITY_PROVENANCE_ACTIVE_GENERATION,
                    AUTHORITY_PROVENANCE_CONTRACT_VERSION,
                    AUTHORITY_PROVENANCE_ACTIVATION_POLICY_VERSION,
                ),
            ),
        ]
    )
    role_probe.assert_called_once_with(role_name="maru_runtime")
    runtime_contract.assert_called_once_with()


@override_settings(
    REQUIRE_EXACT_AUTHORITY_PROVENANCE=True,
    RUNTIME_DATABASE_ROLE="maru_runtime",
)
@patch(
    "maru.core.views.authority_provenance_runtime_contract_is_ready",
    return_value=True,
)
@patch("maru.core.views.probe_runtime_database_role_safety")
@patch("maru.core.views.connection.cursor")
def test_readiness_rejects_a_different_or_unsafe_runtime_database_role(
    cursor: MagicMock,
    role_probe: MagicMock,
    runtime_contract: MagicMock,
) -> None:
    cursor.return_value.__enter__.return_value.fetchone.side_effect = [
        (True, True),
        (17, False, True, True, True),
    ]
    role_probe.return_value = _runtime_role_safety(current_user_matches=False)

    response = APIClient().get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "dependencies": {
            "database": "ok",
            "authority_provenance": "unavailable",
        },
    }
    runtime_contract.assert_called_once_with()


@override_settings(
    REQUIRE_EXACT_AUTHORITY_PROVENANCE=True,
    RUNTIME_DATABASE_ROLE="maru_runtime",
)
@patch(
    "maru.core.views.authority_provenance_runtime_contract_is_ready",
    return_value=True,
)
@patch(
    "maru.core.views.probe_runtime_database_role_safety",
    side_effect=OperationalError("private role or ownership detail"),
)
@patch("maru.core.views.connection.cursor")
def test_readiness_minimizes_runtime_database_role_probe_errors(
    cursor: MagicMock,
    role_probe: MagicMock,
    runtime_contract: MagicMock,
) -> None:
    cursor.return_value.__enter__.return_value.fetchone.side_effect = [
        (True, True),
        (17, False, True, True, True),
    ]

    response = APIClient().get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "dependencies": {
            "database": "ok",
            "authority_provenance": "unavailable",
        },
    }
    role_probe.assert_called_once_with(role_name="maru_runtime")
    runtime_contract.assert_called_once_with()


@override_settings(
    REQUIRE_EXACT_AUTHORITY_PROVENANCE=True,
    RUNTIME_DATABASE_ROLE="maru_runtime",
)
@patch(
    "maru.core.views.authority_provenance_runtime_contract_is_ready",
    return_value=False,
)
@patch("maru.core.views.probe_runtime_database_role_safety")
@patch("maru.core.views.connection.cursor")
def test_readiness_requires_the_full_fingerprinted_runtime_contract(
    cursor: MagicMock,
    role_probe: MagicMock,
    runtime_contract: MagicMock,
) -> None:
    cursor.return_value.__enter__.return_value.fetchone.side_effect = [
        (True, True),
        (17, False, True, True, True),
    ]

    response = APIClient().get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "dependencies": {
            "database": "ok",
            "authority_provenance": "unavailable",
        },
    }
    runtime_contract.assert_called_once_with()
    role_probe.assert_not_called()


@override_settings(REQUIRE_EXACT_AUTHORITY_PROVENANCE=True)
@patch("maru.core.views.connection.cursor")
def test_readiness_minimizes_exact_authority_provenance_database_errors(
    cursor: MagicMock,
) -> None:
    cursor.return_value.__enter__.return_value.fetchone.return_value = (True, True)
    cursor.return_value.__enter__.return_value.execute.side_effect = [
        None,
        OperationalError("private marker detail"),
    ]
    response = APIClient().get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "dependencies": {
            "database": "ok",
            "authority_provenance": "unavailable",
        },
    }


@patch("maru.core.views.connection.cursor")
def test_readiness_accepts_an_explicitly_dormant_compatibility_contract(
    cursor: MagicMock,
) -> None:
    cursor.return_value.__enter__.return_value.fetchone.side_effect = [
        (True, True),
        (True, True),
    ]

    response = APIClient().get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "dependencies": {
            "database": "ok",
            **_READY_BOUNDED_DOMAIN_DEPENDENCIES,
            "logistics": "ok",
        },
    }
    cursor.return_value.__enter__.return_value.execute.assert_has_calls(
        [
            call(views._AUTHORITY_PROVENANCE_TABLE_HEALTH_QUERY),
            call(
                views._DORMANT_AUTHORITY_PROVENANCE_HEALTH_QUERY,
                (0,),
            ),
        ]
    )


@patch("maru.core.views.connection.cursor")
def test_readiness_rejects_false_configuration_after_activation(
    cursor: MagicMock,
) -> None:
    cursor.return_value.__enter__.return_value.fetchone.side_effect = [
        (True, True),
        (False, False),
    ]

    response = APIClient().get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "dependencies": {
            "database": "ok",
            "authority_provenance": "unavailable",
        },
    }


@override_settings(REQUIRE_EXACT_AUTHORITY_PROVENANCE=True)
@patch("maru.core.views.connection.cursor")
def test_readiness_rejects_an_unsupported_postgresql_major(
    cursor: MagicMock,
) -> None:
    cursor.return_value.__enter__.return_value.fetchone.side_effect = [
        (True, True),
        (18, False, True, True, True),
    ]
    response = APIClient().get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "dependencies": {
            "database": "ok",
            "authority_provenance": "unavailable",
        },
    }


@override_settings(REQUIRE_EXACT_AUTHORITY_PROVENANCE=True)
@patch("maru.core.views.connection.cursor")
def test_readiness_rejects_runtime_database_temporary_privilege(
    cursor: MagicMock,
) -> None:
    cursor.return_value.__enter__.return_value.fetchone.side_effect = [
        (True, True),
        (17, True, True, True, True),
    ]
    response = APIClient().get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "dependencies": {
            "database": "ok",
            "authority_provenance": "unavailable",
        },
    }


@override_settings(REQUIRE_EXACT_AUTHORITY_PROVENANCE=True)
@patch("maru.core.views.connection.cursor")
def test_readiness_rejects_an_unsafe_effective_database_schema_order(
    cursor: MagicMock,
) -> None:
    cursor.return_value.__enter__.return_value.fetchone.side_effect = [
        (True, True),
        (17, False, False, True, True),
    ]

    response = APIClient().get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "dependencies": {
            "database": "ok",
            "authority_provenance": "unavailable",
        },
    }


@override_settings(
    REQUIRE_EXACT_AUTHORITY_PROVENANCE=False,
    IDENTITY_INVITATION_ENCRYPTION_REQUIRED=True,
)
@patch(
    "maru.core.views.platform_invitation_runtime_contract_is_ready",
    return_value=False,
)
@patch("maru.core.views.connection.cursor")
def test_readiness_rejects_an_unactivated_invitation_runtime_contract(
    cursor: MagicMock,
    invitation_contract: MagicMock,
) -> None:
    cursor.return_value.__enter__.return_value.fetchone.return_value = (False, False)

    response = APIClient().get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "dependencies": {
            "database": "ok",
            "identity_invitations": "unavailable",
            **_READY_BOUNDED_DOMAIN_DEPENDENCIES,
            "logistics": "ok",
        },
    }
    invitation_contract.assert_called_once_with()


@override_settings(
    REQUIRE_EXACT_AUTHORITY_PROVENANCE=False,
    IDENTITY_INVITATION_ENCRYPTION_REQUIRED=True,
)
@patch(
    "maru.core.views.platform_invitation_runtime_contract_is_ready",
    return_value=True,
)
@patch("maru.core.views.connection.cursor")
def test_readiness_reports_a_proved_invitation_runtime_contract(
    cursor: MagicMock,
    invitation_contract: MagicMock,
) -> None:
    cursor.return_value.__enter__.return_value.fetchone.return_value = (False, False)

    response = APIClient().get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "dependencies": {
            "database": "ok",
            "identity_invitations": "ok",
            **_READY_BOUNDED_DOMAIN_DEPENDENCIES,
            "logistics": "ok",
        },
    }
    invitation_contract.assert_called_once_with()


@patch("maru.core.views.connection.cursor")
def test_readiness_requires_logistics_current_session_integrity(
    cursor: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor.return_value.__enter__.return_value.fetchone.return_value = (False, False)
    monkeypatch.setattr(views, "logistics_current_session_is_ready", lambda: False)

    response = APIClient().get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "dependencies": {
            "database": "ok",
            **_READY_BOUNDED_DOMAIN_DEPENDENCIES,
            "logistics": "unavailable",
        },
    }


@patch("maru.core.views.connection.cursor")
def test_readiness_minimizes_logistics_helper_errors(
    cursor: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor.return_value.__enter__.return_value.fetchone.return_value = (False, False)

    def unavailable() -> bool:
        raise OperationalError("private Logistics catalog detail")

    monkeypatch.setattr(views, "logistics_current_session_is_ready", unavailable)

    response = APIClient().get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "dependencies": {
            "database": "ok",
            **_READY_BOUNDED_DOMAIN_DEPENDENCIES,
            "logistics": "unavailable",
        },
    }


@pytest.mark.parametrize(
    ("probe_name", "status_key"),
    [
        ("applications_database_integrity_is_ready", "applications_integrity"),
        ("charities_database_integrity_is_ready", "charities_integrity"),
        ("catalog_database_integrity_is_ready", "catalog_integrity"),
        ("venues_database_integrity_is_ready", "venues_integrity"),
    ],
)
@patch("maru.core.views.connection.cursor")
def test_readiness_requires_each_bounded_domain_integrity_contract(
    cursor: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    probe_name: str,
    status_key: str,
) -> None:
    cursor.return_value.__enter__.return_value.fetchone.return_value = (False, False)
    monkeypatch.setattr(views, probe_name, lambda: False)

    response = APIClient().get("/health/ready")

    expected_domains = dict(_READY_BOUNDED_DOMAIN_DEPENDENCIES)
    expected_domains[status_key] = "unavailable"
    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "dependencies": {
            "database": "ok",
            **expected_domains,
            "logistics": "ok",
        },
    }


@patch("maru.core.views.connection.cursor")
def test_readiness_minimizes_bounded_domain_catalog_errors(
    cursor: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor.return_value.__enter__.return_value.fetchone.return_value = (False, False)

    def unavailable() -> bool:
        raise OperationalError("private bounded-domain catalog detail")

    monkeypatch.setattr(
        views,
        "applications_database_integrity_is_ready",
        unavailable,
    )

    response = APIClient().get("/health/ready")

    expected_domains = dict(_READY_BOUNDED_DOMAIN_DEPENDENCIES)
    expected_domains["applications_integrity"] = "unavailable"
    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "dependencies": {
            "database": "ok",
            **expected_domains,
            "logistics": "ok",
        },
    }
