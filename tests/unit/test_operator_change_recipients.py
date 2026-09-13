"""Real sender admission, independently checked subject purpose and minimized audit."""

from contextlib import nullcontext
from dataclasses import asdict, replace
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.db import DatabaseError

from maru.authorization.catalog import CAPABILITIES, ScopeLevel
from maru.authorization.policy import PolicyDecision
from maru.events.adoption import ADOPTION_PROFILES
from maru.scheduling import change_recipient_queries as queries
from maru.scheduling import planning_queries
from maru.scheduling.authorization import (
    DEFAULT_SCHEDULING_AUTHORIZER,
    VIEW_CHANGE_RECIPIENTS,
    SchedulingAuthorizationDeniedError,
)
from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.operator_scope import OperatorScopeKind


@pytest.fixture
def world(monkeypatch):
    sender = planning_queries.SchedulingReadRequest(
        *(UUID(int=n) for n in range(10, 14))
    )
    request = queries.OperatorChangeRecipientRequest(
        sender, UUID(int=1), OperatorScopeKind.DEPARTMENT, UUID(int=14)
    )
    policy = Mock(
        side_effect=lambda _request, **kwargs: PolicyDecision(
            allowed=True,
            fields=kwargs["fields"],
            obligations=frozenset(),
            reason_code="synthetic_subject_scope",
        )
    )
    people = Mock(return_value=object())
    labels = Mock(return_value={request.account_id: "Selected operator"})
    staffing = Mock(return_value=True)
    sender_authority = Mock(return_value=object())
    audit = Mock()
    for name, mock in (
        ("authorize_operator_scope", policy),
        ("resolve_active_verified_person_reference", people),
        ("active_verified_person_account_display_labels", labels),
        ("operator_staffing_adopted", staffing),
    ):
        monkeypatch.setattr(queries, name, mock)
    monkeypatch.setattr(planning_queries.transaction, "atomic", nullcontext)
    monkeypatch.setattr(planning_queries, "_lock_edition", Mock())
    monkeypatch.setattr(planning_queries, "_authorize", sender_authority)
    monkeypatch.setattr(planning_queries, "_audit", audit)
    return SimpleNamespace(
        request=request,
        sender=sender,
        policy=policy,
        people=people,
        labels=labels,
        staffing=staffing,
        sender_authority=sender_authority,
        audit=audit,
    )


@pytest.mark.parametrize("kind", list(OperatorScopeKind))
def test_sender_read_and_subject_eligibility_have_distinct_attribution(world, kind):
    request = replace(world.request, kind=kind)
    result = queries.load_operator_change_recipient(request)
    assert result.account_id == request.account_id != world.sender.actor_id
    assert result.kind is kind
    assert result.target_id == request.target_id
    assert result.staffing_adopted is (kind is OperatorScopeKind.DEPARTMENT)
    assert set(asdict(result)) == {
        "account_id",
        "display_label",
        "kind",
        "target_id",
        "staffing_adopted",
        "policy_version",
    }
    for call in world.sender_authority.call_args_list:
        assert call.args == (
            world.sender,
            VIEW_CHANGE_RECIPIENTS,
            frozenset({"operator_recipients"}),
            DEFAULT_SCHEDULING_AUTHORIZER,
        )
    assert world.sender_authority.call_args.kwargs == {"lock": True}
    expected = ["scheduling.view_operator_output", "venues.view_operator_wayfinding"]
    if kind is OperatorScopeKind.DEPARTMENT:
        expected.append("workforce.view_operator_staffing")
    assert [
        call.kwargs["capability"] for call in world.policy.call_args_list
    ] == expected * 2
    for call in world.policy.call_args_list:
        assert call.args[0].actor_id == request.account_id
        assert call.args[0].organization_id == world.sender.organization_id
        assert call.args[0].edition_id == world.sender.edition_id
        assert call.args[0].kind is kind
        assert call.args[0].target_id == request.target_id
    assert [call.kwargs["account_id"] for call in world.people.call_args_list] == [
        request.account_id,
        world.sender.actor_id,
    ]
    assert all(call.kwargs["lock"] for call in world.people.call_args_list)
    world.labels.assert_called_once_with({request.account_id})
    assert world.audit.call_args.args == (
        world.sender,
        VIEW_CHANGE_RECIPIENTS,
        "operator_change_recipient",
    )
    assert "Selected operator" not in repr(world.audit.call_args)


def test_no_staffing_adoption_does_not_query_workforce_subject_authority(world):
    world.staffing.return_value = False
    assert not queries.load_operator_change_recipient(world.request).staffing_adopted
    assert all(
        call.kwargs["capability"] != "workforce.view_operator_staffing"
        for call in world.policy.call_args_list
    )


def test_sender_denial_precedes_subject_or_label_lookup(world):
    world.sender_authority.side_effect = SchedulingAuthorizationDeniedError
    with pytest.raises(SchedulingAuthorizationDeniedError):
        queries.load_operator_change_recipient(world.request)
    world.people.assert_not_called()
    world.labels.assert_not_called()
    world.policy.assert_not_called()


def test_sender_can_select_own_operator_purpose_without_duplicate_person_locks(world):
    request = replace(world.request, account_id=world.sender.actor_id)
    world.labels.return_value = {request.account_id: "Current sender"}
    result = queries.load_operator_change_recipient(request)
    assert result.account_id == world.sender.actor_id
    world.people.assert_called_once_with(account_id=world.sender.actor_id, lock=True)


@pytest.mark.parametrize(
    "field", ["actor_id", "organization_id", "edition_id", "correlation_id"]
)
def test_invalid_trusted_attribution_never_reaches_owner_lookup(world, field):
    request = replace(
        world.request, sender=replace(world.sender, **{field: "untrusted"})
    )
    with pytest.raises(SchedulingAuthorizationDeniedError):
        queries.load_operator_change_recipient(request)
    world.people.assert_not_called()
    world.sender_authority.assert_not_called()


@pytest.mark.parametrize("kind", [None, "room", "edition", object()])
def test_scope_kind_requires_the_closed_typed_purpose(world, kind):
    with pytest.raises(SchedulingAuthorizationDeniedError):
        queries.load_operator_change_recipient(replace(world.request, kind=kind))
    world.people.assert_not_called()


@pytest.mark.parametrize("owner", [0, 1, 2])
def test_each_required_subject_owner_denial_precedes_label_disclosure(world, owner):
    decision = PolicyDecision(
        allowed=True,
        fields=frozenset(),
        obligations=frozenset(),
        reason_code="synthetic",
    )
    world.policy.side_effect = [decision] * owner + [
        SchedulingAuthorizationDeniedError()
    ]
    with pytest.raises(SchedulingUnavailableError):
        queries.load_operator_change_recipient(world.request)
    world.labels.assert_not_called()
    world.audit.assert_not_called()


@pytest.mark.parametrize("subject", ["sender", "recipient"])
def test_inactive_identity_never_returns_a_recipient(world, subject):
    selected = (
        world.sender.actor_id if subject == "sender" else world.request.account_id
    )
    world.people.side_effect = lambda **kwargs: (
        None if kwargs["account_id"] == selected else object()
    )
    error = (
        SchedulingAuthorizationDeniedError
        if subject == "sender"
        else SchedulingUnavailableError
    )
    with pytest.raises(error):
        queries.load_operator_change_recipient(world.request)
    world.policy.assert_not_called()
    world.labels.assert_not_called()


@pytest.mark.parametrize(
    "fault",
    ["labels_missing", "labels_foreign", "adoption", "policy", "final_sender", "audit"],
)
def test_moving_or_unavailable_evidence_cannot_escape_final_boundary(world, fault):
    if fault.startswith("labels"):
        world.labels.return_value = (
            {} if fault == "labels_missing" else {UUID(int=99): "Foreign"}
        )
    elif fault == "adoption":
        world.staffing.side_effect = [True, False]
    elif fault == "policy":
        decision = PolicyDecision(
            allowed=True,
            fields=frozenset(),
            obligations=frozenset(),
            reason_code="synthetic",
        )
        world.policy.side_effect = [decision] * 3 + [
            SchedulingAuthorizationDeniedError()
        ]
    elif fault == "final_sender":
        world.sender_authority.side_effect = [
            object(),
            SchedulingAuthorizationDeniedError(),
        ]
    else:
        world.audit.side_effect = DatabaseError("synthetic audit failure")
    error = (
        SchedulingAuthorizationDeniedError
        if fault == "final_sender"
        else SchedulingUnavailableError
    )
    with pytest.raises(error):
        queries.load_operator_change_recipient(world.request)


@pytest.mark.parametrize("field", ["account_id", "target_id"])
@pytest.mark.parametrize("value", [None, "untrusted", UUID(int=0)])
def test_invalid_person_or_scope_selection_is_denied_before_lookup(world, field, value):
    with pytest.raises(SchedulingAuthorizationDeniedError):
        queries.load_operator_change_recipient(replace(world.request, **{field: value}))
    world.people.assert_not_called()
    world.sender_authority.assert_not_called()


@pytest.mark.parametrize(
    "invalid_request",
    [None, object(), queries.OperatorChangeRecipientRequest(None, None, None, None)],
)
def test_invalid_request_shape_is_denied(world, invalid_request):
    with pytest.raises(SchedulingAuthorizationDeniedError):
        queries.load_operator_change_recipient(invalid_request)
    world.people.assert_not_called()


def test_new_sender_capability_is_dormant_and_native_catalog_is_additive():
    previous = import_module(
        "maru.authorization.migrations.0030_programme_operator_capabilities"
    )
    current = import_module(
        "maru.authorization.migrations.0031_programme_change_communication_capabilities"
    )
    assert current.CHANGE_COMMUNICATION_CAPABILITIES == (
        VIEW_CHANGE_RECIPIENTS,
        "scheduling.view_change_notices",
        "scheduling.prepare_change_notices",
        "scheduling.review_change_notices",
        "scheduling.handoff_change_notices",
    )
    assert (
        *previous.EDITION_CAPABILITIES,
        *current.CHANGE_COMMUNICATION_CAPABILITIES,
    ) == current.EDITION_CAPABILITIES
    for name in (
        "ORGANIZATION_CAPABILITIES",
        "DEPARTMENT_CAPABILITIES",
        "RESOURCE_CAPABILITIES",
    ):
        assert getattr(current, name) == getattr(previous, name)
    assert set(
        current.ORGANIZATION_CAPABILITIES
        + current.EDITION_CAPABILITIES
        + current.DEPARTMENT_CAPABILITIES
        + current.RESOURCE_CAPABILITIES
    ) == {code for code, definition in CAPABILITIES.items() if definition.persistable}
    definition = CAPABILITIES[VIEW_CHANGE_RECIPIENTS]
    assert definition.maximum_scope is ScopeLevel.EDITION
    assert definition.persistable
    assert definition.delegable
    assert not definition.allow_self
    assert definition.field_ceiling == frozenset({"operator_recipients"})
    assert definition.obligations == frozenset({"audit_sensitive_read"})
    assert all(
        VIEW_CHANGE_RECIPIENTS not in profile.capability_codes
        for profile in ADOPTION_PROFILES.values()
    )
    assert current.REVERSE_SQL == previous.FORWARD_SQL


@pytest.mark.parametrize("used", ["none", "grant", "role"])
def test_used_sender_capability_cannot_be_downgraded(used):
    current = import_module(
        "maru.authorization.migrations.0031_programme_change_communication_capabilities"
    )
    grant, bundle, apps, editor = Mock(), Mock(), Mock(), Mock()
    apps.get_model.side_effect = [grant, bundle]
    grant.objects.filter.return_value.exists.return_value = used == "grant"
    bundle.objects.filter.return_value.exists.return_value = used == "role"
    if used == "none":
        current.refuse_used_change_capability_downgrade(apps, editor)
    else:
        with pytest.raises(RuntimeError, match="fix forward"):
            current.refuse_used_change_capability_downgrade(apps, editor)
    editor.execute.assert_called_once_with(
        "LOCK TABLE public.authorization_capabilitygrant, "
        "public.authorization_rolebundle IN ACCESS EXCLUSIVE MODE"
    )
