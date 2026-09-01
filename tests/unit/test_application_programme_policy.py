"""Database-free coverage for exact Department and self policy adapters."""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from maru.authorization import policy
from maru.authorization.policy import PolicyDecision


def _denied(reason_code: str) -> PolicyDecision:
    return PolicyDecision(
        allowed=False,
        fields=frozenset(),
        obligations=frozenset(),
        reason_code=reason_code,
    )


@pytest.mark.parametrize("unavailable_state", ["inactive", "unverified", "non_person"])
def test_exact_department_adapter_rejects_unusable_identity_before_target(
    monkeypatch,
    unavailable_state: str,
) -> None:
    """Use one minimized denial for revoked or non-person principals."""
    principal_resolver = MagicMock(return_value=None)
    target_resolver = MagicMock()
    monkeypatch.setattr(
        policy,
        "_active_verified_person_principal",
        principal_resolver,
    )
    monkeypatch.setattr(policy, "resolve_department_target", target_resolver)

    decision = policy.decide_verified_principal_exact_department(
        principal_id=uuid4(),
        organization_id=uuid4(),
        edition_id=uuid4(),
        department_id=uuid4(),
        capability_code="applications.manage_programme_calls",
    )

    assert decision == _denied("account_inactive"), unavailable_state
    target_resolver.assert_not_called()


def test_exact_department_adapter_preserves_target_and_complete_denial(
    monkeypatch,
) -> None:
    """Do not substitute edition authority or reporting-tree inheritance."""
    principal = SimpleNamespace(id=uuid4())
    target = object()
    decision = _denied("permission_absent")
    target_resolver = MagicMock(return_value=target)
    decide = MagicMock(return_value=decision)
    monkeypatch.setattr(
        policy,
        "_active_verified_person_principal",
        MagicMock(return_value=principal),
    )
    monkeypatch.setattr(policy, "resolve_department_target", target_resolver)
    monkeypatch.setattr(policy, "decide", decide)
    organization_id = uuid4()
    edition_id = uuid4()
    department_id = uuid4()

    assert (
        policy.decide_verified_principal_exact_department(
            principal_id=principal.id,
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=department_id,
            capability_code="applications.manage_programme_calls",
        )
        == decision
    )
    target_resolver.assert_called_once_with(
        organization_id=organization_id,
        edition_id=edition_id,
        department_id=department_id,
    )
    assert decide.call_args.kwargs["resource"] is target


def test_exact_self_adapter_rejects_wrong_owner_without_resolving_target(
    monkeypatch,
) -> None:
    """Construct self only when Applications' proven owner is the principal."""
    principal = SimpleNamespace(id=uuid4())
    target_resolver = MagicMock()
    decide = MagicMock(return_value=_denied("target_unavailable"))
    monkeypatch.setattr(
        policy,
        "_active_verified_person_principal",
        MagicMock(return_value=principal),
    )
    monkeypatch.setattr(policy, "resolve_self_target", target_resolver)
    monkeypatch.setattr(policy, "decide", decide)

    decision = policy.decide_verified_principal_exact_self(
        principal_id=principal.id,
        owner_account_id=uuid4(),
        organization_id=uuid4(),
        edition_id=uuid4(),
        capability_code="applications.view_programme_proposal_self",
    )

    assert decision == _denied("target_unavailable")
    target_resolver.assert_not_called()
    assert decide.call_args.kwargs["resource"] is None


def test_person_principal_query_requires_active_verified_person(monkeypatch) -> None:
    """Keep the reusable policy entry point stricter than edition staff scope."""
    principal_id = uuid4()
    manager = MagicMock()
    manager.filter.return_value.first.return_value = SimpleNamespace(id=principal_id)
    monkeypatch.setattr(
        policy,
        "Account",
        SimpleNamespace(
            Kind=SimpleNamespace(PERSON="person"),
            objects=manager,
        ),
    )

    resolved = policy._active_verified_person_principal(principal_id)

    assert resolved is not None
    manager.filter.assert_called_once_with(
        id=principal_id,
        is_active=True,
        email_verified_at__isnull=False,
        account_kind="person",
    )
