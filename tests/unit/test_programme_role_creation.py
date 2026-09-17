"""Database-free original-selection, purpose admission and failure-boundary checks."""

from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from django.core import signing
from django.core.exceptions import ValidationError

from maru.authorization import programme_role_boundary as boundary
from maru.authorization import programme_role_creation as queries
from maru.authorization import programme_role_selection as selection
from maru.authorization.catalog import ScopeLevel
from maru.authorization.programme_role_inputs import ProgrammeRoleScope
from maru.authorization.programme_role_recipes import PROGRAMME_ROLE_RECIPES
from maru.authorization.services import AuthorizationDenied
from maru.identity.models import Account

NOW = datetime(2026, 9, 18, tzinfo=UTC)
RECIPE = PROGRAMME_ROLE_RECIPES[("coverage-reader", 1)]
ACTOR = UUID(int=3)
RECIPIENT = UUID(int=4)
APPROVER = UUID(int=5)
SCOPE = ProgrammeRoleScope(UUID(int=1), UUID(int=2), ScopeLevel.EDITION)


def draft(**changes):
    return replace(
        selection.ProgrammeRoleRequestDraft(
            RECIPE.code,
            1,
            "recipient@example.invalid",
            "approver@example.invalid",
            NOW,
            NOW + timedelta(days=3),
            "Synthetic bounded coverage access.",
            UUID(int=6),
        ),
        **changes,
    )


def signed(value=None, scope=SCOPE, actor_id=ACTOR):
    return selection._sign_selection(
        actor_id, scope, value or draft(), RECIPIENT, APPROVER
    )


def verify(value=None, *, proof=None, scope=SCOPE, actor_id=ACTOR):
    return selection.verify_programme_role_selection(
        actor_id=actor_id,
        scope=scope,
        draft=value or draft(),
        proof=proof or signed().proof,
    )


def test_original_selection_verifies_without_identity_or_database_access():
    result = verify()
    assert result.details.recipient_id == RECIPIENT
    assert result.details.approver_id == APPROVER
    assert result.details.reason == draft().reason
    assert len(result.proof.encode()) < selection.MAX_PROGRAMME_ROLE_SELECTION_BYTES
    payload = signing.loads(result.proof, salt=selection._SALT)
    assert set(payload) == {"recipient_id", "approver_id", "intent"}
    assert "example.invalid" not in str(payload)


@pytest.mark.parametrize(
    "changes",
    [
        {"recipe_code": "planner"},
        {"recipe_version": 2},
        {"recipe_version": True},
        {"recipient_email": "other@example.invalid"},
        {"approver_email": "other@example.invalid"},
        {"not_before": NOW + timedelta(minutes=1)},
        {"not_before": None},
        {"expires_at": None},
        {"expires_at": NOW + timedelta(days=4)},
        {"reason": "Different intent"},
        {"idempotency_key": uuid4()},
        {"idempotency_key": UUID(int=0)},
        {"recipient_email": "bad"},
        {"approver_email": "x" * 255},
        {"not_before": NOW.replace(tzinfo=None)},
    ],
)
def test_changed_original_terms_cannot_verify(changes):
    with pytest.raises(ValidationError, match="original person selection"):
        verify(draft(**changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"organization_id": UUID(int=11)},
        {"programme_edition_id": UUID(int=12)},
        {"department_id": UUID(int=13)},
        {"level": ScopeLevel.ORGANIZATION},
        {"resource_kind": "venue.edition_space"},
    ],
)
def test_changed_scope_never_verifies(changes):
    with pytest.raises(ValidationError):
        verify(scope=replace(SCOPE, **changes))


@pytest.mark.parametrize("actor_id", [UUID(int=10), UUID(int=0), APPROVER, "3"])
def test_foreign_or_invalid_author_never_verifies(actor_id):
    with pytest.raises(ValidationError):
        verify(actor_id=actor_id)


@pytest.mark.parametrize("proof", ["broken", "x" * 2049, None, 3, "\ud800"])
def test_malformed_proof_has_uniform_safe_error(proof):
    with pytest.raises(ValidationError, match="original person selection"):
        selection.verify_programme_role_selection(
            actor_id=ACTOR, scope=SCOPE, draft=draft(), proof=proof
        )


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {
            "recipient_id": str(RECIPIENT),
            "approver_id": str(APPROVER),
            "intent": "wrong",
        },
        {
            "recipient_id": str(RECIPIENT),
            "approver_id": str(APPROVER),
            "intent": [],
            "extra": "x",
        },
        {"recipient_id": None, "approver_id": str(APPROVER), "intent": "x"},
    ],
)
def test_even_signed_malformed_payload_cannot_verify(payload):
    with pytest.raises(ValidationError):
        verify(proof=signing.dumps(payload, salt=selection._SALT))


def test_signature_is_purpose_bound_and_changed_people_fail():
    good = signed()
    payload = signing.loads(good.proof, salt=selection._SALT)
    with pytest.raises(ValidationError):
        verify(proof=signing.dumps(payload, salt="different-purpose"))
    payload["recipient_id"] = str(UUID(int=100))
    with pytest.raises(ValidationError):
        verify(proof=signing.dumps(payload, salt=selection._SALT))


def test_author_can_be_recipient_but_not_approver():
    value = draft()
    own = selection._sign_selection(ACTOR, SCOPE, value, ACTOR, APPROVER)
    assert verify(proof=own.proof).details.recipient_id == ACTOR
    with pytest.raises(ValidationError):
        selection._sign_selection(ACTOR, SCOPE, value, RECIPIENT, ACTOR)
    with pytest.raises(ValidationError):
        selection._sign_selection(ACTOR, SCOPE, value, RECIPIENT, RECIPIENT)


@pytest.fixture
def world(monkeypatch):
    actor = Account(id=ACTOR, is_active=True, email_verified_at=NOW)
    monkeypatch.setattr(queries.transaction, "atomic", nullcontext)
    mocks = {}
    for name, value in {
        "_require_profile": None,
        "_require_actor": None,
        "_require_integrity": None,
        "_resolve_scope": object(),
        "_lock_scope": object(),
        "_lock_people": {ACTOR: actor},
        "_require_current_controller": None,
        "lock_retired_department_authority_boundaries": None,
        "resolve_edition_target": object(),
        "page_access_scope_label": "Synthetic Programme scope",
        "profile_allows_capabilities": True,
        "profile_allows_catalog_entry": True,
        "active_verified_person_account_display_labels": {
            RECIPIENT: "Synthetic recipient",
            APPROVER: "Synthetic approver",
        },
        "append_audit": None,
    }.items():
        mocks[name] = Mock(return_value=value)
        monkeypatch.setattr(queries, name, mocks[name])
    people = {
        "recipient@example.invalid": SimpleNamespace(account_id=RECIPIENT),
        "approver@example.invalid": SimpleNamespace(account_id=APPROVER),
    }
    resolver = Mock(side_effect=lambda *, email: people.get(email))
    monkeypatch.setattr(
        queries, "resolve_active_verified_person_reference_by_email", resolver
    )
    return SimpleNamespace(actor=actor, mocks=mocks, resolver=resolver, people=people)


def load(world, **changes):
    return queries.load_programme_role_creation(
        actor=world.actor, scope=SCOPE, correlation_id=uuid4(), **changes
    )


def prepare(world, value=None):
    return queries.prepare_programme_role_creation(
        actor=world.actor, scope=SCOPE, draft=value or draft(), correlation_id=uuid4()
    )


def test_bare_choices_are_exact_and_audited_without_people(world):
    result = load(world)
    assert RECIPE in result.recipes
    assert all(ScopeLevel.EDITION in item.target_scopes for item in result.recipes)
    assert not result.selection
    world.resolver.assert_not_called()
    world.mocks["active_verified_person_account_display_labels"].assert_not_called()
    audit = world.mocks["append_audit"].call_args.args[0]
    assert audit.safe_metadata == {"target_count": 0}
    assert audit.principal_id == ACTOR
    assert audit.organization_id == SCOPE.organization_id
    assert audit.event_edition_id == SCOPE.programme_edition_id
    assert audit.retention_class == "security-extended"
    assert audit.obligations == ("audit_sensitive_read",)


@pytest.mark.parametrize("level", list(ScopeLevel))
def test_recipe_choices_keep_scope_including_multi_scope_onsite_tasks(world, level):
    scope = replace(
        SCOPE,
        level=level,
        resource_kind="venue.edition_space" if level is ScopeLevel.RESOURCE else "",
    )
    result = queries._recipes(scope)
    assert result == tuple(
        recipe
        for recipe in PROGRAMME_ROLE_RECIPES.values()
        if level in recipe.target_scopes
    )


@pytest.mark.parametrize(
    "gate", ["profile_allows_catalog_entry", "profile_allows_capabilities"]
)
def test_unpinned_recipes_are_not_substituted(world, gate):
    world.mocks[gate].return_value = False
    assert load(world).recipes == ()
    with pytest.raises(AuthorizationDenied):
        prepare(world)
    world.resolver.assert_not_called()


def test_preview_is_exact_audited_selection_and_refresh_never_resolves_emails(world):
    result = prepare(world)
    assert result.selection.details.recipient_id == RECIPIENT
    assert result.recipient_name == "Synthetic recipient"
    assert result.approver_name == "Synthetic approver"
    assert world.resolver.call_count == 2
    audit = world.mocks["append_audit"].call_args.args[0]
    assert audit.safe_metadata == {"target_count": 2}
    assert "example.invalid" not in str(audit)
    world.resolver.reset_mock()
    world.people.clear()
    refreshed = load(world, original=(draft(), result.selection.proof))
    assert refreshed == result
    world.resolver.assert_not_called()


@pytest.mark.parametrize(
    "missing", ["recipient@example.invalid", "approver@example.invalid"]
)
def test_empty_exact_match_is_neutral_audited_and_discloses_no_partial_people(
    world, missing
):
    world.people.pop(missing)
    result = prepare(world)
    assert result.selection is None
    assert result.recipient_name == result.approver_name == ""
    world.mocks["active_verified_person_account_display_labels"].assert_not_called()
    assert world.mocks["append_audit"].call_args.args[0].safe_metadata == {
        "target_count": 0
    }


def test_people_lost_during_initial_preview_are_not_partially_released(world):
    world.mocks["active_verified_person_account_display_labels"].return_value = {
        APPROVER: "Approver"
    }
    assert prepare(world).selection is None


def test_original_person_loss_does_not_retarget_or_preclude_owner_retry(world):
    world.mocks["active_verified_person_account_display_labels"].return_value = {}
    result = load(world, original=(draft(), signed().proof))
    assert result.selection.details.recipient_id == RECIPIENT
    assert result.recipient_name == result.approver_name == "Unavailable person"
    world.resolver.assert_not_called()


@pytest.mark.parametrize(
    "gate",
    [
        "_require_profile",
        "_require_actor",
        "_require_integrity",
        "_lock_scope",
        "_require_current_controller",
    ],
)
def test_admission_failure_precedes_person_selection(world, gate):
    world.mocks[gate].side_effect = AuthorizationDenied(
        "Unavailable", reason_code="test"
    )
    with pytest.raises(AuthorizationDenied):
        prepare(world)
    world.resolver.assert_not_called()
    world.mocks["append_audit"].assert_not_called()


def test_current_profile_denies_before_any_database_boundary(world, monkeypatch):
    monkeypatch.setattr(queries, "_require_profile", boundary._require_profile)
    with pytest.raises(AuthorizationDenied):
        prepare(world)
    world.mocks["_resolve_scope"].assert_not_called()
    world.resolver.assert_not_called()


def test_final_controller_loss_withholds_output_and_audit(world):
    world.mocks["_require_current_controller"].side_effect = [
        None,
        AuthorizationDenied("Lost", reason_code="test"),
    ]
    with pytest.raises(AuthorizationDenied):
        prepare(world)
    world.mocks["append_audit"].assert_not_called()


def test_missing_canonical_context_withholds_output(world):
    world.mocks["resolve_edition_target"].return_value = None
    with pytest.raises(AuthorizationDenied):
        prepare(world)
    world.mocks["append_audit"].assert_not_called()


def test_audit_failure_withholds_the_preview(world):
    world.mocks["append_audit"].side_effect = RuntimeError("Audit unavailable")
    with pytest.raises(RuntimeError, match="Audit unavailable"):
        prepare(world)


def test_invalid_original_proof_precedes_person_label_reads(world):
    with pytest.raises(ValidationError):
        load(world, original=(draft(), "tampered"))
    world.resolver.assert_not_called()
    world.mocks["active_verified_person_account_display_labels"].assert_not_called()
    world.mocks["append_audit"].assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [
        {"idempotency_key": UUID(int=0)},
        {"reason": "bad\nreason"},
        {"expires_at": NOW},
        {"recipient_email": "invalid"},
    ],
)
def test_invalid_complete_terms_precede_exact_address_lookup(world, changes):
    with pytest.raises(ValidationError):
        prepare(world, draft(**changes))
    world.resolver.assert_not_called()
