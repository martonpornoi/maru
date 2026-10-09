"""Closed Guidance inputs and deny-before-read field admission without database use."""

from dataclasses import replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.db.migrations.loader import MigrationLoader

from maru.knowledge import authorization, commands, readiness
from maru.knowledge.catalog import CAPABILITY_FIELDS
from maru.knowledge.contracts import (
    GuidanceDraftInput,
    GuidanceReadRequest,
    GuidanceSettingsInput,
)
from maru.knowledge.errors import GuidanceDeniedError, GuidanceSettingsRequiredError
from maru.knowledge.inputs import (
    digest,
    identifier,
    normalize_draft,
    normalize_settings,
    safe_url,
    version,
)
from maru.knowledge.models import GuidanceItem


def rules():
    return GuidanceSettingsInput(
        policy_name="Synthetic record rules",
        record_owner="Synthetic Guides team",
        review_on=date(2090, 1, 1),
        confirmed=True,
        policy_description="Fictional isolated test records only.",
    )


def draft(**changes):
    return replace(
        GuidanceDraftInput("Finding help", "Ask the event help desk.", "en"), **changes
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"confirmed": False},
        {"confirmed": 1},
        {"review_on": "2090-01-01"},
        {"review_on": datetime(2090, 1, 1, tzinfo=UTC)},
        {"record_owner": ""},
        {"policy_name": ""},
        {"policy_description": "", "policy_url": ""},
        {"policy_url": "javascript:alert(1)"},
    ],
)
def test_rules_require_actual_confirmation_and_readable_reference(changes):
    with pytest.raises(ValidationError):
        normalize_settings(replace(rules(), **changes))


def test_unfinished_draft_does_not_invent_review_date_or_placements():
    value = normalize_draft(draft())
    assert value.review_by is None
    assert value.placements == ()
    assert normalize_settings(rules()).review_on == date(2090, 1, 1)


@pytest.mark.parametrize(
    "changes",
    [
        {"review_by": "2090-01-01"},
        {"review_by": datetime(2090, 1, 1, tzinfo=UTC)},
        {"title": ""},
        {"body": ""},
        {"language_code": ""},
        {"placements": ["knowledge.compose"]},
        {"placements": ("knowledge.compose", "knowledge.compose")},
        {"placements": ("https://example.test/private",)},
        {"placements": ("announcements.review",)},
    ],
)
def test_draft_metadata_is_closed_without_authorizing_current_choices(changes):
    with pytest.raises(ValidationError):
        normalize_draft(draft(**changes))


def test_normalized_retry_retains_removed_language_until_owner_decides():
    value = normalize_draft(draft(language_code="removed-language"))
    assert value.language_code == "removed-language"
    assert normalize_draft(draft(placements=("announcements.compose",))).placements == (
        "announcements.compose",
    )


def test_multilingual_plain_text_and_placement_order_have_stable_intent():
    value = normalize_draft(
        draft(
            title=" Segítség ",
            body="  Kezdés: 10:00.\r\nÜdv!  ",
            language_code="hu",
            placements=("knowledge.compose", "announcements.compose"),
        )
    )
    assert value.title == "Segítség"
    assert value.body == "Kezdés: 10:00.\nÜdv!"
    assert value.placements == ("announcements.compose", "knowledge.compose")
    assert digest({"body": value.body, "title": value.title}) == digest(
        {"title": value.title, "body": value.body}
    )
    assert digest({"review_by": None}) != digest({"review_by": date(2090, 1, 1)})


@pytest.mark.parametrize("value", [True, 1, "1", None, UUID(int=0)])
def test_identifiers_do_not_coerce(value):
    with pytest.raises(ValidationError):
        identifier(value)


@pytest.mark.parametrize("value", [True, 0, -1, "1", 2**63])
def test_versions_do_not_coerce_or_wrap(value):
    with pytest.raises(ValidationError):
        version(value)


@pytest.mark.parametrize(
    "value",
    [
        "http://example.test",
        "https://name:password@example.test",
        "javascript:alert(1)",
    ],
)
def test_rule_references_need_https_without_embedded_credentials(value):
    with pytest.raises(ValidationError):
        safe_url(value)


def test_model_writer_boundary_refuses_an_ordinary_save():
    with pytest.raises(ValidationError):
        GuidanceItem(
            organization_id=uuid4(), edition_id=uuid4(), language_code="en"
        ).save()


def test_field_denial_happens_before_scope_or_content_lookup(monkeypatch):
    request = GuidanceReadRequest(uuid4(), uuid4(), uuid4(), uuid4())
    decide = Mock(
        return_value=SimpleNamespace(
            allowed=True, fields=frozenset({"current_summary"})
        )
    )
    scope = Mock()
    monkeypatch.setattr(
        authorization, "decide_verified_principal_exact_edition", decide
    )
    monkeypatch.setattr(authorization, "resolve_knowledge_edition_scope", scope)
    with pytest.raises(GuidanceDeniedError):
        authorization.authorize_guidance_scope(
            request,
            capability="knowledge.view_current",
            fields=frozenset({"current_copy"}),
        )
    scope.assert_not_called()
    assert decide.call_args.kwargs["requested_fields"] == frozenset({"current_copy"})


def test_summary_field_is_independent_of_copy_and_private_working_fields(monkeypatch):
    request = GuidanceReadRequest(uuid4(), uuid4(), uuid4(), uuid4())
    decision = SimpleNamespace(allowed=True, fields=frozenset({"current_summary"}))
    scope = object()
    monkeypatch.setattr(
        authorization,
        "decide_verified_principal_exact_edition",
        Mock(return_value=decision),
    )
    monkeypatch.setattr(
        authorization, "resolve_knowledge_edition_scope", Mock(return_value=scope)
    )
    result = authorization.authorize_guidance_scope(
        request,
        capability="knowledge.view_current",
        fields=frozenset({"current_summary"}),
    )
    assert result.edition is scope
    assert CAPABILITY_FIELDS["knowledge.view_current"].isdisjoint(
        CAPABILITY_FIELDS["knowledge.view_working"]
    )


@pytest.mark.parametrize(
    "missing",
    [
        "guidance_setup_database_integrity_is_ready",
        "guidance_authority_database_integrity_is_ready",
        "authority_provenance_runtime_contract_is_ready",
    ],
)
@pytest.mark.parametrize("unavailable", [False, DatabaseError("unavailable")])
def test_owner_readiness_refuses_missing_foundation_before_owner_probe(
    monkeypatch, missing, unavailable
):
    monkeypatch.setattr(
        readiness,
        "KNOWLEDGE_SCHEMA_SHA256",
        dict.fromkeys(readiness.KNOWLEDGE_SCHEMA_RELATIONS, "pin"),
    )
    monkeypatch.setattr(readiness, "_FENCE_SHA256", "pin")
    for name in (
        "guidance_setup_database_integrity_is_ready",
        "guidance_authority_database_integrity_is_ready",
        "authority_provenance_runtime_contract_is_ready",
    ):
        probe = Mock(return_value=True)
        if name == missing:
            if isinstance(unavailable, Exception):
                probe.side_effect = unavailable
            else:
                probe.return_value = unavailable
        monkeypatch.setattr(readiness, name, probe)
    owner_probe = Mock()
    monkeypatch.setattr(readiness, "build_database_integrity_contract", owner_probe)
    assert not readiness.knowledge_database_integrity_is_ready()
    owner_probe.assert_not_called()
    getattr(readiness, missing).assert_called_once_with()


def test_joined_reversal_orders_knowledge_fence_before_supporting_successors():
    graph = MigrationLoader(None).graph
    fence = ("knowledge", "0003_downgrade_fence")
    for ancestor in (
        ("knowledge", "0001_initial"),
        ("events", "0022_guidance_adoption_profiles"),
        ("authorization", "0043_guidance_capabilities"),
        ("authorization", "0046_guidance_authority_integrity"),
        ("authorization", "0047_guidance_qualified_lineage"),
        ("organizations", "0016_workspace_representation"),
        ("announcements", "0004_guidance_combined_admission"),
    ):
        reversal = graph.backwards_plan(ancestor)
        assert reversal.index(fence) < reversal.index(ancestor)


def test_missing_rules_refuse_before_querying_a_nullable_settings_reference(
    monkeypatch,
):
    lookup = Mock()
    monkeypatch.setattr(commands.GuidanceSettingsRevision.objects, "filter", lookup)
    context = SimpleNamespace(
        scope=SimpleNamespace(edition=SimpleNamespace(accepts_writes=True)),
        control=SimpleNamespace(stopped=False, current_settings_id=None),
    )
    with pytest.raises(GuidanceSettingsRequiredError):
        commands._settings(context)
    lookup.assert_not_called()


@pytest.mark.parametrize("shape", ["empty", "missing", "foreign"])
def test_owner_readiness_requires_every_exact_relation_pin_before_native_probe(
    monkeypatch, shape
):
    pins = dict.fromkeys(readiness.KNOWLEDGE_SCHEMA_RELATIONS, "pin")
    if shape == "empty":
        pins.clear()
    elif shape == "missing":
        pins.pop(readiness.KNOWLEDGE_SCHEMA_RELATIONS[-1])
    else:
        pins["foreign_relation"] = "pin"
    monkeypatch.setattr(readiness, "KNOWLEDGE_SCHEMA_SHA256", pins)
    monkeypatch.setattr(readiness, "_FENCE_SHA256", "pin")
    foundation_probe, owner_probe = Mock(), Mock()
    monkeypatch.setattr(
        readiness, "guidance_setup_database_integrity_is_ready", foundation_probe
    )
    monkeypatch.setattr(readiness, "build_database_integrity_contract", owner_probe)
    assert not readiness.knowledge_database_integrity_is_ready()
    foundation_probe.assert_not_called()
    owner_probe.assert_not_called()
