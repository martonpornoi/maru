"""Exact-scope and evidence order for the minimized call Department name."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest
from django.db import DatabaseError

from maru.applications import programme_queries as queries
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError,
)
from maru.workforce import queries as workforce


@pytest.fixture
def scope(monkeypatch):
    values = {
        name: uuid4()
        for name in (
            "actor_id",
            "organization_id",
            "edition_id",
            "department_id",
            "correlation_id",
        )
    }
    values["source_channel"] = "programme-call-workspace"
    trace = []
    admitted = SimpleNamespace(
        **{
            name: values[name]
            for name in ("actor_id", "organization_id", "edition_id", "department_id")
        },
        decision=SimpleNamespace(obligations=frozenset({"audit"}), reason_code="test"),
    )
    auth = Mock(side_effect=lambda **_kwargs: (trace.append("authorize"), admitted)[1])
    label = workforce.CurrentDepartmentLabelReference(
        values["department_id"], "Programme"
    )
    read = Mock(side_effect=lambda **_kwargs: (trace.append("label"), label)[1])
    audit = Mock(side_effect=lambda *_args, **_kwargs: trace.append("audit"))
    monkeypatch.setattr(queries, "authorize_programme_call_scope", auth)
    monkeypatch.setattr(queries, "resolve_current_department_label_reference", read)
    monkeypatch.setattr(queries, "append_audit", audit)
    monkeypatch.setattr(queries.transaction, "atomic", nullcontext)
    return SimpleNamespace(
        values=values,
        trace=trace,
        admitted=admitted,
        auth=auth,
        read=read,
        audit=audit,
        label=label,
    )


def test_exact_authority_precedes_name_and_required_audit_precedes_return(
    scope,
) -> None:
    assert queries.get_managed_programme_call_department(**scope.values) == scope.label
    assert scope.trace == ["authorize", "label", "authorize", "audit"]
    scope.read.assert_called_once_with(
        **{
            name: scope.values[name]
            for name in ("organization_id", "edition_id", "department_id")
        }
    )
    record = scope.audit.call_args.args[0]
    assert record.safe_metadata == {"target_count": 1}
    assert record.target_id == scope.values["department_id"]
    assert record.obligations == ("audit", "audit_sensitive_read")
    assert record.operation == "applications.programme.query.managed_department_label"
    assert record.target_type == "workforce.department"
    assert record.capability_code == "applications.manage_programme_calls"
    assert "Programme" not in repr(record)


def test_denied_department_never_loads_a_label(scope) -> None:
    scope.auth.side_effect = ApplicationsProgrammeAuthorizationDeniedError
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        queries.get_managed_programme_call_department(**scope.values)
    scope.read.assert_not_called()
    record = scope.audit.call_args.args[0]
    assert record.outcome == "deny"
    assert record.target_id is None
    assert record.safe_metadata is None


@pytest.mark.parametrize(
    "label", [None, workforce.CurrentDepartmentLabelReference(uuid4(), "Foreign")]
)
def test_absent_or_incoherent_owner_reference_cannot_escape(scope, label) -> None:
    scope.read.side_effect = None
    scope.read.return_value = label
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        queries.get_managed_programme_call_department(**scope.values)
    assert scope.audit.call_args.args[0].outcome == "deny"


def test_authority_revocation_discards_label_before_release(scope) -> None:
    scope.auth.side_effect = [
        scope.admitted,
        ApplicationsProgrammeAuthorizationDeniedError,
    ]
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        queries.get_managed_programme_call_department(**scope.values)
    assert scope.audit.call_args.args[0].outcome == "deny"


def test_required_audit_outage_is_not_a_successful_name_read(scope) -> None:
    scope.audit.side_effect = DatabaseError("Synthetic audit outage")
    with pytest.raises(DatabaseError):
        queries.get_managed_programme_call_department(**scope.values)


def test_missing_mandatory_obligation_cannot_be_manufactured(scope) -> None:
    scope.admitted.decision.obligations = frozenset()
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        queries.get_managed_programme_call_department(**scope.values)
    assert scope.audit.call_args.args[0].outcome == "deny"


def test_invalid_audit_transport_precedes_scope_or_label(scope) -> None:
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        queries.get_managed_programme_call_department(
            **{**scope.values, "source_channel": "Invalid channel"}
        )
    scope.auth.assert_not_called()
    scope.read.assert_not_called()
    scope.audit.assert_not_called()


def test_workforce_label_query_selects_only_exact_current_name(monkeypatch) -> None:
    organization, edition, department = (uuid4() for _ in range(3))
    manager = MagicMock()
    manager.filter.return_value.values.return_value.first.return_value = {
        "id": department,
        "name": "Programme",
    }
    monkeypatch.setattr(workforce, "Department", SimpleNamespace(objects=manager))
    result = workforce.resolve_current_department_label_reference(
        organization_id=organization, edition_id=edition, department_id=department
    )
    assert result == workforce.CurrentDepartmentLabelReference(department, "Programme")
    assert tuple(result.__dataclass_fields__) == ("department_id", "label")
    manager.filter.assert_called_once_with(
        id=department,
        organization_id=organization,
        edition_id=edition,
        retired_at__isnull=True,
    )
    manager.filter.return_value.values.assert_called_once_with("id", "name")


@pytest.mark.parametrize(
    "failure", [None, ValueError("Bad scope"), TypeError("Bad scope")]
)
def test_workforce_label_unavailability_has_one_shape(monkeypatch, failure) -> None:
    manager = MagicMock()
    selected = manager.filter.return_value.values.return_value.first
    if failure is None:
        selected.return_value = None
    else:
        selected.side_effect = failure
    monkeypatch.setattr(workforce, "Department", SimpleNamespace(objects=manager))
    assert (
        workforce.resolve_current_department_label_reference(
            organization_id=uuid4(), edition_id=uuid4(), department_id=uuid4()
        )
        is None
    )
