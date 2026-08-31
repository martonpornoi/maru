from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

import maru.programme.authorization as programme_authorization
import maru.programme.commands as programme_commands
import maru.programme.models as programme_models
from maru.authorization.policy import PolicyDecision
from maru.events.queries import PrivatePlanningEditionReference
from maru.identity.queries import ActiveVerifiedAccountReference
from maru.programme.authorization import (
    PROGRAMME_MANAGE_ITEMS,
    AuthorizedProgrammeScope,
    ProgrammeAuthorizationDeniedError,
    authorize_programme_scope,
)
from maru.programme.commands import ProgrammeLifecycleConflictError

_PROGRAMME_SOURCE = Path(__file__).parents[2] / "src" / "maru" / "programme"
_MODEL_IMPORT_ALLOWLIST = frozenset(
    {
        "maru.core.models",
        "maru.programme.models",
    }
)


def test_programme_imports_no_external_domain_models() -> None:
    """Keep private model instances behind owner-defined public contracts."""
    violations: list[tuple[str, int, str]] = []
    for source_path in sorted(_PROGRAMME_SOURCE.glob("*.py")):
        tree = ast.parse(
            source_path.read_text(encoding="utf-8"),
            filename=str(source_path),
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if (
                    module.startswith("maru.")
                    and module.endswith(".models")
                    and module not in _MODEL_IMPORT_ALLOWLIST
                ):
                    violations.append((source_path.name, node.lineno, module))
            elif isinstance(node, ast.Import):
                violations.extend(
                    (source_path.name, node.lineno, alias.name)
                    for alias in node.names
                    if (
                        alias.name.startswith("maru.")
                        and alias.name.endswith(".models")
                        and alias.name not in _MODEL_IMPORT_ALLOWLIST
                    )
                )

    assert violations == []


def test_programme_model_validation_dereferences_no_external_relations() -> None:
    """Keep owner-model objects out of Programme validation code."""
    programme_model_types = (
        programme_models.ProgrammeEditionControl,
        programme_models.ProgrammeItem,
        programme_models.ProgrammeItemSourceBinding,
        programme_models.ProgrammeWorkingRevision,
        programme_models.ProgrammeDeliveryRevision,
        programme_models.ProgrammeDepartmentDiscussionEntry,
        programme_models.ProgrammeReadinessRequirement,
        programme_models.ProgrammeReadinessRequirementRevision,
        programme_models.ProgrammeReadinessEvidence,
        programme_models.ProgrammePublicRendition,
        programme_models.ProgrammeCommandReceipt,
    )
    external_relation_names = {
        field.name
        for model_type in programme_model_types
        for field in model_type._meta.fields
        if field.is_relation and field.remote_field.model._meta.app_label != "programme"
    }
    assert external_relation_names == programme_models._OWNER_MANAGED_RELATION_FIELDS

    tree = ast.parse(
        (_PROGRAMME_SOURCE / "models.py").read_text(encoding="utf-8"),
        filename="models.py",
    )
    dereferences = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and node.attr in external_relation_names
    }
    assert dereferences == set()


def test_programme_authorization_consumes_locked_owner_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flatten owner DTOs without releasing Identity or Events models."""
    actor_id = uuid4()
    organization_id = uuid4()
    edition_id = uuid4()
    actor_resolver = MagicMock(
        return_value=ActiveVerifiedAccountReference(account_id=actor_id)
    )
    edition_resolver = MagicMock(
        return_value=PrivatePlanningEditionReference(
            edition_id=edition_id,
            organization_id=organization_id,
            accepts_private_planning_writes=True,
        )
    )
    decision_adapter = MagicMock(
        return_value=PolicyDecision(
            allowed=True,
            fields=frozenset({"item_summaries"}),
            obligations=frozenset({"audit"}),
            reason_code="synthetic_exact_decision",
        )
    )
    monkeypatch.setattr(
        programme_authorization,
        "resolve_active_verified_account_reference",
        actor_resolver,
    )
    monkeypatch.setattr(
        programme_authorization,
        "resolve_private_planning_edition_reference",
        edition_resolver,
    )
    monkeypatch.setattr(
        programme_authorization,
        "decide_verified_principal_exact_edition",
        decision_adapter,
    )

    scope = authorize_programme_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=PROGRAMME_MANAGE_ITEMS,
        requested_fields=frozenset({"item_summaries"}),
        lock=True,
    )

    assert scope == AuthorizedProgrammeScope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        accepts_private_planning_writes=True,
        decision=decision_adapter.return_value,
    )
    actor_resolver.assert_called_once_with(account_id=actor_id, lock=True)
    edition_resolver.assert_called_once_with(
        organization_id=organization_id,
        edition_id=edition_id,
        lock=True,
    )
    decision_adapter.assert_called_once_with(
        principal_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=PROGRAMME_MANAGE_ITEMS,
        requested_fields=frozenset({"item_summaries"}),
    )


def test_programme_lifecycle_guard_consumes_owner_boolean() -> None:
    """Let Events own lifecycle spelling while Programme owns rejection."""
    scope = AuthorizedProgrammeScope(
        actor_id=uuid4(),
        organization_id=uuid4(),
        edition_id=uuid4(),
        accepts_private_planning_writes=True,
        decision=PolicyDecision(
            allowed=True,
            fields=frozenset(),
            obligations=frozenset(),
            reason_code="synthetic_exact_decision",
        ),
    )

    assert programme_commands._ensure_editable(scope) is None
    with pytest.raises(ProgrammeLifecycleConflictError):
        programme_commands._ensure_editable(
            replace(scope, accepts_private_planning_writes=False)
        )


def test_malformed_principal_is_minimized_before_policy_or_denial_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep malformed principal input from masking the stable denial shape."""
    actor_resolver = MagicMock(return_value=None)
    edition_resolver = MagicMock()
    policy_adapter = MagicMock()
    monkeypatch.setattr(
        programme_authorization,
        "resolve_active_verified_account_reference",
        actor_resolver,
    )
    monkeypatch.setattr(
        programme_authorization,
        "resolve_private_planning_edition_reference",
        edition_resolver,
    )
    monkeypatch.setattr(
        programme_authorization,
        "decide_verified_principal_exact_edition",
        policy_adapter,
    )

    with pytest.raises(ProgrammeAuthorizationDeniedError):
        authorize_programme_scope(
            actor_id="not-a-uuid",  # type: ignore[arg-type]
            organization_id=uuid4(),
            edition_id=uuid4(),
            capability_code=PROGRAMME_MANAGE_ITEMS,
        )

    actor_resolver.assert_called_once_with(account_id="not-a-uuid", lock=False)
    policy_adapter.assert_not_called()
    audit_append = MagicMock()
    monkeypatch.setattr(programme_commands, "append_audit", audit_append)
    programme_commands._append_denial_audit(
        actor_id="not-a-uuid",
        organization_id=uuid4(),
        edition_id=uuid4(),
        capability_code=PROGRAMME_MANAGE_ITEMS,
        operation="item_create",
        correlation_id=uuid4(),
        source_channel="service",
    )
    assert audit_append.call_args.args[0].principal_id is None
