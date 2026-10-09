"""Immutable Guides evidence owns its event identity, independently of parent rows."""

from importlib import import_module
from uuid import uuid4

import pytest

from maru.authorization import guidance_access, guidance_audit
from maru.authorization.models import GuidanceAccessDecision, GuidanceAccessRequest
from maru.events import guidance_activation
from maru.events.models import (
    GuidanceActivationDecision,
    GuidanceActivationReceipt,
    GuidanceActivationRequest,
)
from maru.identity.models import Account


def _assert_envelope(event, row, actor, aggregate_type, operation, request):
    assert (event.aggregate_type, event.aggregate_id, event.aggregate_version) == (
        aggregate_type,
        row.id,
        1,
    )
    assert event.schema_version == 1
    assert event.payload == {"operation": operation}
    assert event.organization_id == request.organization_id
    assert event.event_edition_id == request.edition_id
    assert event.actor_kind == "account"
    assert event.actor_id == actor.id
    assert event.causation_id == row.source_audit_id
    assert event.correlation_id == row.correlation_id


@pytest.mark.parametrize("completion", ["activated", "recovered"])
def test_proposal_both_people_and_application_have_distinct_exact_row_events(
    monkeypatch, completion
):
    events = []
    monkeypatch.setattr(guidance_audit, "publish_domain_event", events.append)
    platform, first, second = (Account(id=uuid4()) for _ in range(3))
    request = GuidanceActivationRequest(
        organization_id=uuid4(),
        edition_id=uuid4(),
        proposed_by=platform,
        source_audit_id=uuid4(),
        correlation_id=uuid4(),
    )
    decisions = tuple(
        GuidanceActivationDecision(
            request=request,
            actor=actor,
            accepted=True,
            source_audit_id=uuid4(),
            correlation_id=uuid4(),
        )
        for actor in (first, second)
    )
    receipt = GuidanceActivationReceipt(
        request=request,
        applied_by=platform,
        source_audit_id=uuid4(),
        correlation_id=uuid4(),
    )
    sources = (
        (platform, request, "proposed", "events.guidance_activation_request"),
        (first, decisions[0], "accepted", "events.guidance_activation_decision"),
        (second, decisions[1], "accepted", "events.guidance_activation_decision"),
        (platform, receipt, completion, "events.guidance_activation_receipt"),
    )
    for actor, row, operation, aggregate_type in sources:
        guidance_activation._event(
            actor, row, operation, row.source_audit_id, row.correlation_id
        )
        _assert_envelope(events[-1], row, actor, aggregate_type, operation, request)
    assert (
        len(
            {
                (event.aggregate_type, event.aggregate_id, event.aggregate_version)
                for event in events
            }
        )
        == 4
    )
    assert {event.event_name for event in events} == {
        "events.guidance_adoption.changed.v1"
    }


def test_declined_activation_event_belongs_to_actual_decision(monkeypatch):
    events = []
    monkeypatch.setattr(guidance_audit, "publish_domain_event", events.append)
    actor = Account(id=uuid4())
    request = GuidanceActivationRequest(organization_id=uuid4(), edition_id=uuid4())
    decision = GuidanceActivationDecision(
        request=request,
        actor=actor,
        accepted=False,
        source_audit_id=uuid4(),
        correlation_id=uuid4(),
    )
    guidance_activation._event(
        actor, decision, "declined", decision.source_audit_id, decision.correlation_id
    )
    _assert_envelope(
        events[0],
        decision,
        actor,
        "events.guidance_activation_decision",
        "declined",
        request,
    )


@pytest.mark.parametrize("accepted", [True, False])
def test_access_request_and_answer_keep_distinct_immutable_event_identities(
    monkeypatch, accepted
):
    events = []
    monkeypatch.setattr(guidance_audit, "publish_domain_event", events.append)
    first, second = (Account(id=uuid4()) for _ in range(2))
    request = GuidanceAccessRequest(
        organization_id=uuid4(),
        edition_id=uuid4(),
        requested_by=first,
        source_audit_id=uuid4(),
        correlation_id=uuid4(),
    )
    decision = GuidanceAccessDecision(
        request=request,
        actor=second,
        accepted=accepted,
        source_audit_id=uuid4(),
        correlation_id=uuid4(),
    )
    operation = "accepted" if accepted else "declined"
    for actor, row, action, aggregate_type in (
        (first, request, "requested", "authorization.guidance_access_request"),
        (second, decision, operation, "authorization.guidance_access_decision"),
    ):
        guidance_access._event(
            actor, row, action, row.source_audit_id, row.correlation_id
        )
        _assert_envelope(events[-1], row, actor, aggregate_type, action, request)
    assert events[0].aggregate_id != events[1].aggregate_id
    assert {event.event_name for event in events} == {
        "authorization.guidance_access.changed.v1"
    }


def test_native_graphs_require_own_row_identity_and_unchanged_exact_envelopes():
    activation = import_module(
        "maru.events.migrations.0023_guidance_adoption_integrity"
    ).FORWARD_SQL.split(
        "CREATE FUNCTION public.maru_guidance_activation_graph_guard()", 1
    )[1]
    authority = import_module(
        "maru.authorization.migrations.0046_guidance_authority_integrity"
    ).FORWARD_SQL.split(
        "CREATE FUNCTION public.maru_guidance_authority_graph_guard()", 1
    )[1]
    assert "v_aggregate_id:=NEW.id;" in activation
    assert "v_aggregate_id:=plan.id;" not in activation
    for kind in ("request", "decision", "receipt"):
        assert f"event_type:='events.guidance_activation_{kind}'" in activation
    assert "e.aggregate_type=event_type AND e.aggregate_id=v_aggregate_id" in activation
    for kind in ("request", "decision"):
        assert (
            "event_aggregate:=NEW.id; "
            f"event_type:='authorization.guidance_access_{kind}'"
        ) in authority
    assert "event_aggregate:=NEW.request_id" not in authority
    assert (
        "event_aggregate:=NEW.id; "
        "event_type:='authorization.guidance_revocation_receipt'" in authority
    )
    for source in (activation, authority):
        assert "e.schema_version=1 AND e.aggregate_version=1" in source
        assert "e.actor_kind='account' AND e.actor_id=event_actor" in source
        assert "o.event_id=e.id AND o.destination='internal'" in source
        assert "e.payload=jsonb_build_object('operation'," in source


@pytest.mark.parametrize(
    ("module_name", "probe_name", "guard", "schema_pin", "relations"),
    [
        (
            "maru.events.guidance_setup_readiness",
            "guidance_setup_database_integrity_is_ready",
            "maru_guidance_activation_graph_guard()",
            "GUIDANCE_SETUP_SCHEMA_SHA256",
            "GUIDANCE_SETUP_SCHEMA_RELATIONS",
        ),
        (
            "maru.authorization.guidance_readiness",
            "guidance_authority_database_integrity_is_ready",
            "maru_guidance_authority_graph_guard()",
            "GUIDANCE_AUTHORITY_SCHEMA_SHA256",
            "GUIDANCE_AUTHORITY_RELATIONS",
        ),
    ],
)
def test_repaired_graph_source_pin_is_current_but_still_requires_native_proof(
    monkeypatch, module_name, probe_name, guard, schema_pin, relations
):
    module = import_module(module_name)
    captured = []

    def native_contract(contract):
        captured.append(contract)
        return False

    monkeypatch.setattr(module, "database_integrity_contract_is_ready", native_contract)
    monkeypatch.setattr(module, "relation_schema_is_current", lambda _: True)
    # Exercise the staged state independently of this checkout's real observations.
    monkeypatch.setattr(module, schema_pin, {})
    assert not getattr(module, probe_name)()
    assert not captured
    monkeypatch.setattr(
        module,
        schema_pin,
        dict.fromkeys(getattr(module, relations), "unit-only-hypothetical-observation"),
    )
    assert not getattr(module, probe_name)()
    assert len(captured) == 1
    assert captured[0].source_contract_current
    assert guard in captured[0].functions
