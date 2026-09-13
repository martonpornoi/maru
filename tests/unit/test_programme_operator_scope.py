"""Operator purpose admission cannot borrow planner, public or wider authority."""

from contextlib import nullcontext
from dataclasses import replace
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from django.db import DatabaseError

import maru.scheduling.operator_scope as scope
from maru.authorization.catalog import CAPABILITIES, ScopeLevel
from maru.authorization.policy import PolicyDecision
from maru.events.adoption import ADOPTION_PROFILES
from maru.scheduling.adoption import (
    SCHEDULING_ADOPTION_ADAPTERS,
    SCHEDULING_OPERATOR_RELEASE_ADAPTER,
)
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.command_support import SchedulingUnavailableError

CAPABILITY = "scheduling.view_operator_output"
FIELDS = frozenset({"released_geometry"})


@pytest.fixture
def request_scope():
    edition = uuid4()
    return scope.OperatorReadRequest(
        uuid4(), uuid4(), edition, uuid4(), scope.OperatorScopeKind.EDITION, edition
    )


@pytest.fixture
def policy(monkeypatch):
    decision = PolicyDecision(
        allowed=True, fields=FIELDS, obligations=frozenset(), reason_code="grant"
    )
    edition = MagicMock(return_value=decision)
    department = MagicMock(return_value=decision)
    resource = MagicMock(return_value=decision)
    target = SimpleNamespace(department_id=uuid4(), resource_binding_id=uuid4())
    monkeypatch.setattr(scope, "decide_verified_principal_exact_edition", edition)
    monkeypatch.setattr(scope, "decide_verified_principal_exact_department", department)
    monkeypatch.setattr(scope, "decide_verified_principal_exact_resource", resource)
    monkeypatch.setattr(
        scope, "resolve_edition_space_target", MagicMock(return_value=target)
    )
    monkeypatch.setattr(
        scope,
        "edition_adoption_profile_reference",
        MagicMock(return_value=SimpleNamespace(code="fixture", version=1)),
    )
    monkeypatch.setattr(scope, "profile_allows_adapter", MagicMock(return_value=True))
    return SimpleNamespace(
        edition=edition,
        department=department,
        resource=resource,
        decision=decision,
        target=target,
    )


def test_native_operator_catalog_is_additive_dormant_and_independently_ceilinged():
    current = import_module(
        "maru.authorization.migrations.0030_programme_operator_capabilities"
    )
    previous = import_module(
        "maru.authorization.migrations.0029_programme_release_capabilities"
    )
    assert set(current.OPERATOR_CAPABILITIES) == scope.OPERATOR_CAPABILITIES
    assert (
        *previous.EDITION_CAPABILITIES,
        *current.OPERATOR_CAPABILITIES,
    ) == current.EDITION_CAPABILITIES
    assert current.ORGANIZATION_CAPABILITIES == previous.ORGANIZATION_CAPABILITIES
    assert current.DEPARTMENT_CAPABILITIES == previous.DEPARTMENT_CAPABILITIES
    assert current.RESOURCE_CAPABILITIES == previous.RESOURCE_CAPABILITIES
    assert current.REVERSE_SQL == previous.FORWARD_SQL
    assert {
        *current.ORGANIZATION_CAPABILITIES,
        *current.EDITION_CAPABILITIES,
        *current.DEPARTMENT_CAPABILITIES,
        *current.RESOURCE_CAPABILITIES,
    } == {code for code, definition in CAPABILITIES.items() if definition.persistable}
    for code in scope.OPERATOR_CAPABILITIES:
        definition = CAPABILITIES[code]
        assert definition.maximum_scope is ScopeLevel.EDITION
        assert definition.persistable
        assert definition.delegable
        assert not definition.allow_self
        assert definition.obligations == frozenset({"audit_sensitive_read"})
        assert definition.field_ceiling
    assert SCHEDULING_OPERATOR_RELEASE_ADAPTER in SCHEDULING_ADOPTION_ADAPTERS
    for profile in ADOPTION_PROFILES.values():
        assert not profile.capability_codes & scope.OPERATOR_CAPABILITIES
        assert SCHEDULING_OPERATOR_RELEASE_ADAPTER not in profile.adapter_codes


@pytest.mark.parametrize("used", ["none", "grant", "role"])
def test_native_operator_downgrade_fences_retained_role_or_grant_use(used):
    migration = import_module(
        "maru.authorization.migrations.0030_programme_operator_capabilities"
    )
    grant, bundle, editor, apps = MagicMock(), MagicMock(), MagicMock(), MagicMock()
    grant.objects.filter.return_value.exists.return_value = used == "grant"
    bundle.objects.filter.return_value.exists.return_value = used == "role"
    apps.get_model.side_effect = [grant, bundle]
    operation = migration.Migration.operations[-1]
    assert operation.reverse_code is migration.refuse_used_operator_capability_downgrade
    if used == "none":
        operation.reverse_code(apps, editor)
    else:
        with pytest.raises(RuntimeError, match="fix forward"):
            operation.reverse_code(apps, editor)
    editor.execute.assert_called_once_with(
        "LOCK TABLE public.authorization_capabilitygrant, "
        "public.authorization_rolebundle IN ACCESS EXCLUSIVE MODE"
    )


@pytest.mark.parametrize("kind", list(scope.OperatorScopeKind))
def test_exact_persisted_purpose_selects_only_matching_policy_seam(
    request_scope, policy, kind
):
    target_id = (
        request_scope.edition_id if kind is scope.OperatorScopeKind.EDITION else uuid4()
    )
    request_scope = replace(request_scope, kind=kind, target_id=target_id)
    assert (
        scope.authorize_operator_scope(
            request_scope, capability=CAPABILITY, fields=FIELDS
        )
        == policy.decision
    )
    expected = {
        "principal_id": request_scope.actor_id,
        "organization_id": request_scope.organization_id,
        "edition_id": request_scope.edition_id,
        "capability_code": CAPABILITY,
        "requested_fields": FIELDS,
    }
    if kind is scope.OperatorScopeKind.ROOM:
        expected.update(
            department_id=policy.target.department_id,
            resource_binding_id=policy.target.resource_binding_id,
        )
        policy.resource.assert_called_once_with(**expected)
        policy.department.assert_not_called()
        policy.edition.assert_not_called()
    elif kind is scope.OperatorScopeKind.DEPARTMENT:
        expected.update(department_id=target_id)
        policy.department.assert_called_once_with(**expected)
        policy.resource.assert_not_called()
        policy.edition.assert_not_called()
    else:
        policy.edition.assert_called_once_with(**expected)
        policy.resource.assert_not_called()
        policy.department.assert_not_called()
    scope.profile_allows_adapter.assert_called_once_with(
        "fixture", 1, SCHEDULING_OPERATOR_RELEASE_ADAPTER
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("actor_id", "actor"),
        ("organization_id", None),
        ("edition_id", 1),
        ("correlation_id", "trace"),
        ("target_id", "id"),
        ("kind", "edition"),
    ],
)
def test_malformed_scope_denies_before_any_profile_or_content_lookup(
    request_scope, policy, field, value
):
    with pytest.raises(SchedulingAuthorizationDeniedError):
        scope.authorize_operator_scope(
            replace(request_scope, **{field: value}),
            capability=CAPABILITY,
            fields=FIELDS,
        )
    scope.edition_adoption_profile_reference.assert_not_called()


@pytest.mark.parametrize(
    ("capability", "fields"),
    [
        ("scheduling.view_planning", FIELDS),
        ("unknown", FIELDS),
        (CAPABILITY, frozenset()),
        (CAPABILITY, frozenset({"personnel"})),
        (CAPABILITY, {"released_geometry"}),
    ],
)
def test_unknown_or_wider_field_requests_cannot_become_operator_authority(
    request_scope, policy, capability, fields
):
    with pytest.raises(SchedulingAuthorizationDeniedError):
        scope.authorize_operator_scope(
            request_scope, capability=capability, fields=fields
        )
    scope.edition_adoption_profile_reference.assert_not_called()


@pytest.mark.parametrize(
    "failure",
    ["profile", "adapter", "target", "edition_id", "denied", "fields", "boolean"],
)
def test_missing_admission_or_incomplete_decision_fails_closed(
    request_scope, policy, failure
):
    if failure == "profile":
        scope.edition_adoption_profile_reference.return_value = None
    elif failure == "adapter":
        scope.profile_allows_adapter.return_value = False
    elif failure == "target":
        request_scope = replace(request_scope, kind=scope.OperatorScopeKind.ROOM)
        scope.resolve_edition_space_target.return_value = None
    elif failure == "edition_id":
        request_scope = replace(request_scope, target_id=uuid4())
    elif failure == "boolean":
        policy.edition.return_value = True
    else:
        policy.edition.return_value = replace(
            policy.decision,
            allowed=failure != "denied",
            fields=frozenset() if failure == "fields" else FIELDS,
        )
    with pytest.raises(SchedulingAuthorizationDeniedError):
        scope.authorize_operator_scope(
            request_scope, capability=CAPABILITY, fields=FIELDS
        )


@pytest.fixture
def guarded(monkeypatch, policy):
    monkeypatch.setattr(scope.transaction, "atomic", nullcontext)
    monkeypatch.setattr(scope, "lock_programme_staffing_scope", MagicMock())
    monkeypatch.setattr(
        scope,
        "resolve_active_verified_person_reference",
        MagicMock(return_value=object()),
    )
    monkeypatch.setattr(scope, "append_audit", MagicMock())


def test_guard_locks_then_rechecks_and_audits_before_return(
    request_scope, guarded, policy
):
    with scope.operator_read(request_scope, capability=CAPABILITY, fields=FIELDS):
        scope.lock_programme_staffing_scope.assert_called_once()
        scope.resolve_active_verified_person_reference.assert_not_called()
        scope.append_audit.assert_not_called()
    assert policy.edition.call_count == 3
    record = scope.append_audit.call_args.args[0]
    assert record.principal_id == request_scope.actor_id
    assert record.target_id == request_scope.target_id
    assert record.capability_code == CAPABILITY
    assert record.outcome == "allow"
    assert record.safe_metadata == {"policy_version": scope.POLICY_VERSION}


@pytest.mark.parametrize("failure", ["actor", "authority", "audit", "database"])
def test_final_failure_never_releases_content(request_scope, guarded, policy, failure):
    error = (
        SchedulingUnavailableError
        if failure in {"audit", "database"}
        else SchedulingAuthorizationDeniedError
    )

    def read_with_failure():
        with scope.operator_read(request_scope, capability=CAPABILITY, fields=FIELDS):
            if failure == "actor":
                scope.resolve_active_verified_person_reference.return_value = None
            elif failure == "authority":
                policy.edition.return_value = replace(policy.decision, allowed=False)
            elif failure == "audit":
                scope.append_audit.side_effect = DatabaseError("unavailable")
            else:
                raise DatabaseError("unavailable")

    with pytest.raises(error):
        read_with_failure()
    assert (
        not any(
            call.args[0].outcome == "allow"
            for call in scope.append_audit.call_args_list
        )
        or failure == "audit"
    )
