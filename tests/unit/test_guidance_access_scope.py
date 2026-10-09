"""Access removal distinguishes inactive parents from a terminal event lifecycle."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied

from maru.authorization import (
    guidance_access,
    guidance_access_queries,
    guidance_readiness,
)


@pytest.fixture
def admission(monkeypatch):
    actor = SimpleNamespace(id=uuid4())
    scope = SimpleNamespace(parents_active=True, accepts_writes=False)
    resolver = Mock(return_value=scope)
    target = object()
    monkeypatch.setattr(
        guidance_readiness, "require_guidance_authority_integrity", lambda: None
    )
    monkeypatch.setattr(guidance_access, "resolve_knowledge_edition_scope", resolver)
    monkeypatch.setattr(
        guidance_access_queries, "resolve_knowledge_edition_scope", resolver
    )
    monkeypatch.setattr(
        guidance_access, "resolve_edition_target", Mock(return_value=target)
    )
    policy = Mock(
        return_value=SimpleNamespace(
            allowed=True, fields=frozenset({"guidance_access"})
        )
    )
    monkeypatch.setattr(
        guidance_access_queries, "decide_verified_principal_exact_edition", policy
    )
    return SimpleNamespace(
        actor=actor,
        organization_id=uuid4(),
        edition_id=uuid4(),
        scope=scope,
        resolver=resolver,
        target=target,
        policy=policy,
    )


@pytest.mark.parametrize("allow_read_only", [False, True])
def test_inactive_parent_denies_before_access_command_authority(
    admission, allow_read_only
):
    admission.scope.parents_active = False
    with pytest.raises(PermissionDenied, match="unavailable"):
        guidance_access._scope(
            admission.organization_id,
            admission.edition_id,
            allow_read_only=allow_read_only,
        )
    admission.resolver.assert_called_once_with(
        organization_id=admission.organization_id,
        edition_id=admission.edition_id,
        for_update=True,
    )


def test_terminal_edition_allows_removal_but_not_new_assignments(admission):
    assert (
        guidance_access._scope(
            admission.organization_id, admission.edition_id, allow_read_only=True
        )
        is admission.target
    )
    with pytest.raises(PermissionDenied, match="unavailable"):
        guidance_access._scope(admission.organization_id, admission.edition_id)
    guidance_access_queries.require_guidance_access_actor(
        actor=admission.actor,
        organization_id=admission.organization_id,
        edition_id=admission.edition_id,
    )


def test_inactive_parent_hides_access_workspace_before_owner_labels(
    admission, monkeypatch
):
    admission.scope.parents_active = False
    labels = Mock(side_effect=AssertionError("No owner labels may be loaded"))
    monkeypatch.setattr(
        guidance_access_queries, "knowledge_workspace_reference", labels
    )
    with pytest.raises(PermissionDenied, match="unavailable"):
        guidance_access_queries.load_guidance_access_workspace(
            actor=admission.actor,
            organization_id=admission.organization_id,
            edition_id=admission.edition_id,
            correlation_id=uuid4(),
        )
    labels.assert_not_called()
    admission.policy.assert_called_once()
