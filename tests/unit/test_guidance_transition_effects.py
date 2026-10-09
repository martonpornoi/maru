"""Exact retained transition routing without a database or current human authority."""

from dataclasses import replace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.db import DatabaseError

from maru.effects import adoption as routes
from maru.effects.adoption import EffectEventIdentity
from maru.effects.checks import check_governed_effect_routes
from maru.events import guidance_effects as owner
from maru.events import queries
from maru.events.adoption import adoption_profile, profile_allows_effect
from maru.events.guidance_activation_references import guidance_manifest_digest
from maru.events.queries import EditionAdoptionProfileReference

ORG, EDITION, OBJECT, ACTOR, AUDIT, TRACE, OTHER = (UUID(int=i) for i in range(1, 8))
EVENT = "events.guidance_adoption.changed.v1"
IDENTITY = EffectEventIdentity(
    1, owner._REQUEST, OBJECT, 1, "account", ACTOR, AUDIT, TRACE
)
REFERENCE = owner.GuidanceAdoptionEffectReference("proposed", ACTOR, AUDIT, TRACE)


@pytest.fixture
def route(monkeypatch):
    monkeypatch.setattr(
        queries,
        "edition_adoption_profile_reference",
        lambda **_kw: EditionAdoptionProfileReference("announcements_only", 1),
    )
    resolver = Mock(return_value=REFERENCE)
    monkeypatch.setattr(owner, "guidance_adoption_effect_reference", resolver)
    return resolver


def allowed(**changes):
    values = {
        "organization_id": ORG,
        "event_edition_id": EDITION,
        "event_name": EVENT,
        "destination": "internal",
        "payload": {"operation": "proposed"},
        "identity": IDENTITY,
    }
    values.update(changes)
    return routes.effect_delivery_is_allowed(**values)


def test_only_retained_proof_admits_pre_adoption_fact(route):
    assert not profile_allows_effect("announcements_only", 1, EVENT, "internal")
    assert not allowed(identity=None)
    assert allowed()
    route.assert_called_once_with(
        organization_id=ORG,
        edition_id=EDITION,
        aggregate_type=owner._REQUEST,
        aggregate_id=OBJECT,
    )
    route.return_value = None
    assert not allowed()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 2),
        ("schema_version", True),
        ("aggregate_version", 2),
        ("aggregate_version", True),
        ("actor_kind", "system"),
        ("actor_id", OTHER),
        ("actor_id", None),
        ("causation_id", OTHER),
        ("causation_id", None),
        ("correlation_id", OTHER),
        ("aggregate_id", "not-a-uuid"),
        ("aggregate_type", []),
    ],
)
def test_altered_envelope_is_denied(route, field, value):
    assert not allowed(identity=replace(IDENTITY, **{field: value}))


@pytest.mark.parametrize(
    "changes",
    [
        {"event_edition_id": None},
        {"destination": "notifications"},
        {"event_name": "knowledge.changed.v1"},
        {"event_name": "authorization.guidance_access.changed.v1"},
        {"payload": {"operation": "accepted"}},
        {"payload": {"operation": "proposed", "extra": True}},
    ],
)
def test_exception_never_widens_other_routes_or_payloads(route, changes):
    assert not allowed(**changes)


@pytest.mark.parametrize(
    "profile", [None, ("announcements_only", 2), ("workforce_only", 1)]
)
def test_unsupported_current_profile_cannot_use_retained_fallback(
    route, monkeypatch, profile
):
    monkeypatch.setattr(
        queries,
        "edition_adoption_profile_reference",
        lambda **_kw: (
            None if profile is None else EditionAdoptionProfileReference(*profile)
        ),
    )
    assert not allowed()
    route.assert_not_called()


def test_existing_manifest_route_remains_ordinary(route, monkeypatch):
    monkeypatch.setattr(
        queries,
        "edition_adoption_profile_reference",
        lambda **_kw: EditionAdoptionProfileReference("guidance_only", 1),
    )
    assert allowed(identity=None)
    route.assert_not_called()


def row(family):
    plan = {
        "organization_id": ORG,
        "edition_id": EDITION,
        "purpose": "initial",
        "source_profile_code": "announcements_only",
        "source_profile_version": 1,
        "target_profile_code": "announcements_guidance",
        "target_profile_version": 1,
        "source_manifest_digest": guidance_manifest_digest(
            adoption_profile("announcements_only", 1)
        ),
        "target_manifest_digest": guidance_manifest_digest(
            adoption_profile("announcements_guidance", 1)
        ),
        "request_digest": "a" * 64,
        "operator_a_id": ACTOR,
        "operator_b_id": OTHER,
        "expected_edition_version": 8,
        "expected_adoption_revision": 0,
    }
    prefix = "" if family == owner._REQUEST else "request__"
    values = {f"{prefix}{key}": value for key, value in plan.items()}
    values.update(source_audit_id=AUDIT, correlation_id=TRACE)
    if family == owner._REQUEST:
        values["proposed_by_id"] = ACTOR
    elif family == owner._DECISION:
        values.update(actor_id=ACTOR, accepted=True, request_digest="a" * 64)
    else:
        values.update(
            applied_by_id=ACTOR, result_edition_version=9, result_adoption_revision=1
        )
    return values


@pytest.fixture
def retained(monkeypatch):
    ready = Mock(return_value=True)
    monkeypatch.setattr(owner, "guidance_setup_database_integrity_is_ready", ready)
    managers = {}
    for family, model in (
        (owner._REQUEST, owner.GuidanceActivationRequest),
        (owner._DECISION, owner.GuidanceActivationDecision),
        (owner._RECEIPT, owner.GuidanceActivationReceipt),
    ):
        manager = Mock()
        manager.filter.return_value.values.return_value.first.return_value = row(family)
        monkeypatch.setattr(model, "objects", manager)
        managers[family] = manager
    return ready, managers


def reference(family=owner._REQUEST, **changes):
    values = {
        "organization_id": ORG,
        "edition_id": EDITION,
        "aggregate_type": family,
        "aggregate_id": OBJECT,
    }
    values.update(changes)
    return owner.guidance_adoption_effect_reference(**values)


@pytest.mark.parametrize(
    ("family", "operation"),
    [
        (owner._REQUEST, "proposed"),
        (owner._DECISION, "accepted"),
        (owner._RECEIPT, "activated"),
    ],
)
def test_owner_reads_scoped_minimized_immutable_metadata(retained, family, operation):
    _ready, managers = retained
    assert reference(family) == replace(REFERENCE, operation=operation)
    filters = managers[family].filter.call_args.kwargs
    assert filters["id"] == OBJECT
    prefix = "" if family == owner._REQUEST else "request__"
    assert filters[f"{prefix}organization_id"] == ORG
    assert filters[f"{prefix}edition_id"] == EDITION
    selected = managers[family].filter.return_value.values.call_args.args
    assert not any(
        word in field
        for field in selected
        for word in ("reason", "expires", "email", "name", "lifecycle", "revoked")
    )


def test_decline_is_a_historical_fact_not_an_adoption_permission(retained):
    _ready, managers = retained
    managers[
        owner._DECISION
    ].filter.return_value.values.return_value.first.return_value["accepted"] = False
    assert reference(owner._DECISION).operation == "declined"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("purpose", "recovery"),
        ("source_profile_code", "guidance_only"),
        ("source_profile_version", 2),
        ("target_profile_code", "guidance_only"),
        ("target_profile_version", 2),
        ("source_manifest_digest", "f" * 64),
        ("target_manifest_digest", "f" * 64),
    ],
)
def test_wrong_original_edge_or_manifest_is_not_proof(retained, field, value):
    _ready, managers = retained
    managers[owner._REQUEST].filter.return_value.values.return_value.first.return_value[
        field
    ] = value
    assert reference() is None


@pytest.mark.parametrize(
    ("family", "field", "value"),
    [
        (owner._DECISION, "actor_id", UUID(int=99)),
        (owner._DECISION, "request_digest", "b" * 64),
        (owner._DECISION, "accepted", 1),
        (owner._RECEIPT, "result_edition_version", 8),
        (owner._RECEIPT, "result_adoption_revision", 0),
    ],
)
def test_decision_and_receipt_linkage_must_match(retained, family, field, value):
    _ready, managers = retained
    managers[family].filter.return_value.values.return_value.first.return_value[
        field
    ] = value
    assert reference(family) is None


def test_missing_drifted_or_unavailable_evidence_denies(retained):
    ready, managers = retained
    ready.return_value = False
    assert reference() is None
    managers[owner._REQUEST].filter.assert_not_called()
    ready.return_value = True
    managers[
        owner._REQUEST
    ].filter.return_value.values.return_value.first.return_value = None
    assert reference() is None
    managers[owner._REQUEST].filter.side_effect = DatabaseError(
        "Synthetic unavailable owner"
    )
    assert reference() is None
    assert reference(aggregate_type="events.unrelated") is None


@pytest.mark.parametrize("field", ["organization_id", "edition_id", "aggregate_id"])
def test_exact_scope_and_identity_are_query_constraints(retained, field):
    _ready, managers = retained
    manager = managers[owner._REQUEST]

    # The fake implements absence for a different tenant, edition or identity.
    def scoped(**filters):
        expected = {"organization_id": ORG, "edition_id": EDITION, "id": OBJECT}
        query = Mock()
        query.values.return_value.first.return_value = (
            row(owner._REQUEST) if filters == expected else None
        )
        return query

    manager.filter.side_effect = scoped
    assert reference(**{field: OTHER}) is None


def test_transition_catalog_is_checked_for_missing_handler(monkeypatch):
    monkeypatch.setattr(routes, "TRANSITION_EFFECT_ROUTES", {(EVENT, "unregistered")})
    assert [message.id for message in check_governed_effect_routes()] == [
        "effects.E001"
    ]
