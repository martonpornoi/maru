"""Fail-closed complete choices without granting Workforce directory authority."""

from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import UUID, uuid4

import pytest
from django.db import DatabaseError

from maru.applications import programme_call_departments as choices
from maru.applications import programme_queries
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError,
    authorize_programme_call_scope,
)
from maru.authorization.policy import PolicyDecision
from maru.workforce import queries as workforce

_ALLOW = PolicyDecision(
    allowed=True,
    fields=frozenset(),
    obligations=frozenset({"reason", "audit"}),
    reason_code="direct_grant",
)
_DENY = PolicyDecision(
    allowed=False,
    fields=frozenset(),
    obligations=frozenset(),
    reason_code="permission_absent",
)


@pytest.fixture
def scope(monkeypatch):
    values = {
        name: uuid4()
        for name in ("actor_id", "organization_id", "edition_id", "correlation_id")
    }
    values.update(department_id=UUID(int=10), source_channel="programme-call-workspace")
    ids = tuple(UUID(int=i) for i in (10, 20, 30))
    trace = []
    policies = {ids[0]: _ALLOW, ids[1]: _ALLOW, ids[2]: _DENY}
    refs = {
        ids[0]: workforce.CurrentDepartmentChoiceReference(
            ids[0], "programme", "Programme"
        ),
        ids[1]: workforce.CurrentDepartmentChoiceReference(
            ids[1], "stage", "Programme"
        ),
    }
    authorizer = SimpleNamespace(
        authorize_department=Mock(
            side_effect=lambda **kw: (
                trace.append(("policy", kw["department_id"])),
                policies[kw["department_id"]],
            )[1]
        )
    )
    values["authorizer"] = authorizer

    def auth(**kw):
        trace.append(("authorize", kw["department_id"]))
        return SimpleNamespace(
            **{key: val for key, val in kw.items() if key != "authorizer"},
            decision=policies[kw["department_id"]],
        )

    authorize = Mock(side_effect=auth)
    members = workforce.CurrentDepartmentSetReference(
        values["organization_id"], values["edition_id"], ids
    )
    listing = Mock(side_effect=lambda **_kw: (trace.append(("set", None)), members)[1])
    lookup = Mock(
        side_effect=lambda **kw: (
            trace.append(("label", kw["department_id"])),
            refs[kw["department_id"]],
        )[1]
    )
    audit = Mock(
        side_effect=lambda record, **_kw: trace.append(("audit", record.target_id))
    )
    monkeypatch.setattr(choices, "authorize_programme_call_scope", authorize)
    monkeypatch.setattr(choices, "resolve_current_department_set_reference", listing)
    monkeypatch.setattr(choices, "resolve_current_department_choice_reference", lookup)
    monkeypatch.setattr(programme_queries, "append_audit", audit)
    monkeypatch.setattr(choices.transaction, "atomic", nullcontext)
    return SimpleNamespace(
        values=values,
        ids=ids,
        trace=trace,
        policies=policies,
        refs=refs,
        authorizer=authorizer,
        authorize=authorize,
        members=members,
        listing=listing,
        lookup=lookup,
        audit=audit,
    )


def test_complete_independent_authority_precedes_labels_and_audit_precedes_release(
    scope,
):
    result = choices.list_managed_programme_call_departments(**scope.values)
    assert result == tuple(scope.refs.values())
    assert scope.trace[0] == ("authorize", scope.ids[0])
    assert scope.trace.index(("policy", scope.ids[2])) < scope.trace.index(
        ("label", scope.ids[0])
    )
    assert ("label", scope.ids[2]) not in scope.trace
    assert scope.authorizer.authorize_department.call_count == 6
    assert scope.listing.call_count == 2
    for call in scope.authorizer.authorize_department.call_args_list:
        assert call.kwargs == {
            "principal_id": scope.values["actor_id"],
            "organization_id": scope.values["organization_id"],
            "edition_id": scope.values["edition_id"],
            "department_id": call.kwargs["department_id"],
            "capability_code": "applications.manage_programme_calls",
            "requested_fields": None,
        }
    for call in scope.audit.call_args_list:
        record = call.args[0]
        assert record.target_id in scope.refs
        assert record.safe_metadata == {"target_count": 1}
        assert record.obligations == ("audit", "audit_sensitive_read", "reason")
        assert (
            record.operation
            == "applications.programme.query.managed_department_choices"
        )
        assert "Programme" not in repr(record)


def test_denied_anchor_never_enumerates_or_resolves_names(scope):
    scope.authorize.side_effect = ApplicationsProgrammeAuthorizationDeniedError
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        choices.list_managed_programme_call_departments(**scope.values)
    scope.listing.assert_not_called()
    scope.lookup.assert_not_called()
    record = scope.audit.call_args.args[0]
    assert record.outcome == "deny"
    assert record.target_id is None
    assert record.safe_metadata is None


@pytest.mark.parametrize(
    "decision",
    [
        None,
        True,
        SimpleNamespace(allowed=True),
        replace(_ALLOW, allowed=1),
        replace(_ALLOW, fields=frozenset({"holders"})),
        replace(_ALLOW, fields=set()),
        replace(_ALLOW, obligations=set(_ALLOW.obligations)),
        replace(_ALLOW, obligations=frozenset()),
        replace(_ALLOW, obligations=frozenset({"audit"})),
        replace(_ALLOW, obligations=_ALLOW.obligations | {"unknown"}),
        replace(_ALLOW, reason_code="unknown"),
        replace(_ALLOW, reason_code=[]),
        replace(_ALLOW, policy_version="obsolete"),
        replace(_DENY, reason_code="target_unavailable"),
        replace(_DENY, reason_code="account_inactive"),
        replace(_DENY, reason_code="module_not_adopted"),
        replace(_DENY, reason_code="authority_provenance_contract_invalid"),
        replace(_DENY, reason_code="programme_profile_inactive"),
        replace(_DENY, obligations=frozenset({"audit"})),
    ],
)
def test_incomplete_or_nonordinary_policy_discards_whole_result(scope, decision):
    scope.policies[scope.ids[1]] = decision
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        choices.list_managed_programme_call_departments(**scope.values)
    scope.lookup.assert_not_called()
    assert scope.audit.call_args.args[0].outcome == "deny"


@pytest.mark.parametrize(
    "kind",
    [
        "none",
        "foreign-org",
        "foreign-edition",
        "missing-anchor",
        "duplicate",
        "wrong-type",
        "overflow",
        "list",
    ],
)
def test_incomplete_owner_set_never_becomes_partial_directory(scope, kind):
    members = scope.members
    value = {
        "none": None,
        "foreign-org": replace(members, organization_id=uuid4()),
        "foreign-edition": replace(members, edition_id=uuid4()),
        "missing-anchor": replace(members, department_ids=(scope.ids[1],)),
        "duplicate": replace(members, department_ids=(scope.ids[0], scope.ids[0])),
        "wrong-type": replace(members, department_ids=(scope.ids[0], "foreign")),
        "overflow": replace(
            members, department_ids=tuple(UUID(int=i) for i in range(257))
        ),
        "list": replace(members, department_ids=list(scope.ids)),
    }[kind]
    scope.listing.side_effect = None
    scope.listing.return_value = value
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        choices.list_managed_programme_call_departments(**scope.values)
    scope.lookup.assert_not_called()


@pytest.mark.parametrize(
    "kind",
    [
        "none",
        "foreign",
        "empty-label",
        "long-label",
        "control-label",
        "bad-code",
        "long-code",
        "duplicate-code",
    ],
)
def test_incoherent_choice_discards_prepared_names(scope, kind):
    ref = scope.refs[scope.ids[1]]
    scope.refs[scope.ids[1]] = {
        "none": None,
        "foreign": replace(ref, department_id=uuid4()),
        "empty-label": replace(ref, label=" "),
        "long-label": replace(ref, label="x" * 161),
        "control-label": replace(ref, label="Stage\nPrivate"),
        "bad-code": replace(ref, code="INVALID"),
        "long-code": replace(ref, code="x" * 81),
        "duplicate-code": replace(ref, code="programme"),
    }[kind]
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        choices.list_managed_programme_call_departments(**scope.values)
    assert scope.audit.call_args.args[0].outcome == "deny"


@pytest.mark.parametrize(
    "change", ["revoke", "grant", "reason", "membership", "anchor"]
)
def test_changed_decision_or_membership_discards_whole_projection(scope, change):
    if change == "membership":
        scope.listing.side_effect = [
            scope.members,
            replace(scope.members, department_ids=scope.ids[:2]),
        ]
    elif change == "anchor":
        scope.authorize.side_effect = [
            SimpleNamespace(decision=_ALLOW),
            ApplicationsProgrammeAuthorizationDeniedError,
        ]
    else:
        initial = [_ALLOW, _ALLOW, _DENY]
        final = {
            "revoke": [_ALLOW, _DENY, _DENY],
            "grant": [_ALLOW, _ALLOW, _ALLOW],
            "reason": [_ALLOW, replace(_ALLOW, reason_code="role_assignment"), _DENY],
        }[change]
        scope.authorizer.authorize_department.side_effect = initial + final
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        choices.list_managed_programme_call_departments(**scope.values)
    assert scope.audit.call_args.args[0].outcome == "deny"


@pytest.mark.parametrize("dependency", ["listing", "lookup", "audit"])
def test_dependency_failure_is_not_silently_filtered(scope, dependency):
    getattr(scope, dependency).side_effect = DatabaseError("synthetic")
    with pytest.raises(DatabaseError):
        choices.list_managed_programme_call_departments(**scope.values)


def test_malformed_transport_precedes_authority_and_audit(scope):
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        choices.list_managed_programme_call_departments(
            **{**scope.values, "source_channel": "Invalid channel"}
        )
    scope.authorize.assert_not_called()
    scope.listing.assert_not_called()
    scope.audit.assert_not_called()


def test_nondefault_authorizer_still_requires_existing_double_guard(
    scope, monkeypatch, settings
):
    settings.MARU_ALLOW_APPLICATIONS_PROGRAMME_TEST_AUTHORIZER = False
    monkeypatch.setattr(
        choices, "authorize_programme_call_scope", authorize_programme_call_scope
    )
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        choices.list_managed_programme_call_departments(**scope.values)
    scope.listing.assert_not_called()
    scope.authorizer.authorize_department.assert_not_called()


def test_minimal_workforce_choice_does_not_widen_existing_name_reference(monkeypatch):
    organization, edition, department = (uuid4() for _ in range(3))
    manager = MagicMock()
    manager.filter.return_value.values.return_value.first.return_value = {
        "id": department,
        "code": "stage",
        "name": "Programme",
    }
    monkeypatch.setattr(workforce, "Department", SimpleNamespace(objects=manager))
    result = workforce.resolve_current_department_choice_reference(
        organization_id=organization, edition_id=edition, department_id=department
    )
    assert result == workforce.CurrentDepartmentChoiceReference(
        department, "stage", "Programme"
    )
    assert tuple(result.__dataclass_fields__) == ("department_id", "code", "label")
    assert tuple(workforce.CurrentDepartmentLabelReference.__dataclass_fields__) == (
        "department_id",
        "label",
    )
    manager.filter.assert_called_once_with(
        id=department,
        organization_id=organization,
        edition_id=edition,
        retired_at__isnull=True,
    )
    manager.filter.return_value.values.assert_called_once_with("id", "code", "name")
