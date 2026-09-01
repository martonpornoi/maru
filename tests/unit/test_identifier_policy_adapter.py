from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from maru.authorization import policy
from maru.authorization.policy import PolicyDecision
from maru.events.adoption import (
    DEFAULT_ADOPTION_PROFILE_VERSION,
    AdoptionProfileCode,
)


def test_identifier_policy_adapter_denies_current_profile_programme(
    monkeypatch,
) -> None:
    principal_id = uuid4()
    organization_id = uuid4()
    edition_id = uuid4()
    principal = SimpleNamespace(
        id=principal_id,
        is_active=True,
        is_platform_administrator=True,
    )
    manager = MagicMock()
    manager.filter.return_value.first.return_value = principal
    target = policy._seal_target(
        organization_id=organization_id,
        edition_id=edition_id,
        adoption_profile_code=AdoptionProfileCode.FULL_CONVENTION.value,
        adoption_profile_version=DEFAULT_ADOPTION_PROFILE_VERSION,
    )
    target_resolver = MagicMock(return_value=target)
    monkeypatch.setattr(policy, "Account", SimpleNamespace(objects=manager))
    monkeypatch.setattr(policy, "resolve_edition_target", target_resolver)

    decision = policy.decide_verified_principal_exact_edition(
        principal_id=principal_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code="programme.manage_items",
        requested_fields=frozenset({"internal_title"}),
    )

    assert decision == PolicyDecision(
        allowed=False,
        fields=frozenset(),
        obligations=frozenset(),
        reason_code="module_not_adopted",
    )
    manager.filter.assert_called_once_with(
        id=principal_id,
        is_active=True,
        email_verified_at__isnull=False,
    )
    target_resolver.assert_called_once_with(
        organization_id=organization_id,
        edition_id=edition_id,
    )


def test_identifier_policy_adapter_returns_complete_minimized_principal_denial(
    monkeypatch,
) -> None:
    principal_id = uuid4()
    manager = MagicMock()
    manager.filter.return_value.first.return_value = None
    target_resolver = MagicMock()
    monkeypatch.setattr(policy, "Account", SimpleNamespace(objects=manager))
    monkeypatch.setattr(policy, "resolve_edition_target", target_resolver)

    decision = policy.decide_verified_principal_exact_edition(
        principal_id=principal_id,
        organization_id=uuid4(),
        edition_id=uuid4(),
        capability_code="programme.view_private",
    )

    assert decision == PolicyDecision(
        allowed=False,
        fields=frozenset(),
        obligations=frozenset(),
        reason_code="account_inactive",
    )
    target_resolver.assert_not_called()
