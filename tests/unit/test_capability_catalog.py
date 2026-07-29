import pytest
from django.core.exceptions import ValidationError

from maru.authorization.catalog import (
    CAPABILITIES,
    CAPABILITY_DEFINITIONS,
    ScopeLevel,
    capability,
    require_capability,
)
from maru.authorization.models import (
    validate_capability_code,
    validate_capability_codes,
    validate_role_code,
)


def test_capability_catalog_has_unique_namespaced_codes() -> None:
    assert len(CAPABILITIES) == len(CAPABILITY_DEFINITIONS)
    assert all("." in code for code in CAPABILITIES)


def test_require_capability_returns_stable_definition() -> None:
    definition = require_capability("events.view_basic")

    assert definition.maximum_scope is ScopeLevel.ORGANIZATION
    assert definition.delegable
    assert "name" in definition.field_ceiling


def test_authority_management_capabilities_make_control_obligations_explicit() -> None:
    direct_grant = require_capability("authorization.grant_direct")
    role_management = require_capability("authorization.manage_roles")
    revocation = require_capability("authorization.revoke")

    assert not direct_grant.delegable
    assert not role_management.delegable
    assert not revocation.delegable
    assert "approval" in direct_grant.obligations
    assert "approval" in role_management.obligations
    assert "approval" not in revocation.obligations
    assert {"reason", "audit"} <= revocation.obligations


def test_unknown_capability_is_not_silently_created() -> None:
    assert capability("events.become_omnipotent") is None
    with pytest.raises(ValueError, match="Unknown capability"):
        require_capability("events.become_omnipotent")


def test_persistent_capability_validators_reject_unknown_or_duplicate_codes() -> None:
    validate_capability_code("events.view_basic")
    validate_capability_codes(["events.view_basic"])

    with pytest.raises(ValidationError, match="declared"):
        validate_capability_code("events.unknown")
    with pytest.raises(ValidationError, match="unique"):
        validate_capability_codes(["events.view_basic", "events.view_basic"])


@pytest.mark.parametrize("value", ["event-reader", "registration.front_desk"])
def test_role_code_accepts_stable_values(value: str) -> None:
    validate_role_code(value)


@pytest.mark.parametrize("value", ["Director", "two words", "_internal"])
def test_role_code_rejects_display_values(value: str) -> None:
    with pytest.raises(ValidationError):
        validate_role_code(value)
