"""Database-free immutable Programme recipes and closed approval-intent contracts."""

import hashlib
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from django.core.exceptions import ValidationError

from maru.authorization import programme_role_recipes as recipes
from maru.authorization.catalog import ScopeLevel, capability
from maru.authorization.programme_role_inputs import (
    PROGRAMME_ROLE_APPROVAL_DAYS,
    ProgrammeRoleDecision,
    ProgrammeRoleIntent,
    ProgrammeRoleScope,
    normalize_programme_role_intent,
    programme_role_decision_digest,
    programme_role_intent_digest,
)
from maru.events.adoption import ADOPTION_PROFILES, profile_allows_catalog_entry
from maru.events.checks import current_adoption_catalog_snapshot

START = datetime(2027, 1, 1, tzinfo=UTC)


def intent(**changes):
    return replace(
        ProgrammeRoleIntent(
            recipe_code="planner",
            recipe_version=1,
            recipient_id=UUID(int=3),
            approver_id=UUID(int=4),
            not_before=START,
            expires_at=START + timedelta(days=1),
            reason=" Synthetic timetable preparation ",
        ),
        **changes,
    )


def scope(level=ScopeLevel.EDITION, **changes):
    return replace(
        ProgrammeRoleScope(
            organization_id=UUID(int=1),
            programme_edition_id=UUID(int=2),
            level=level,
            department_id=UUID(int=5)
            if level in {ScopeLevel.DEPARTMENT, ScopeLevel.RESOURCE}
            else None,
            resource_binding_id=UUID(int=6) if level == ScopeLevel.RESOURCE else None,
            resource_kind="venue.edition_space" if level == ScopeLevel.RESOURCE else "",
        ),
        **changes,
    )


def digest(details=None, target=None):
    return programme_role_intent_digest(
        scope=target or scope(), details=details or intent()
    )


def test_exact_recipe_contents_are_frozen_and_registered_without_profile_activation():
    definitions = tuple(recipes.PROGRAMME_ROLE_RECIPES.values())
    assert len(definitions) == 27
    # Updating v1 contents is not a cosmetic edit: retained intent pins this identity.
    assert (
        hashlib.sha256(
            "\n".join(f"{r.catalog_entry}:{r.digest}" for r in definitions).encode()
        ).hexdigest()
        == "773a3d563ada738ee5f57b4f1061e92772440075f6725764869ffc119ec71017"
    )
    snapshot = current_adoption_catalog_snapshot()
    assert snapshot.registry_problem_codes == ()
    assert set(recipes.PROGRAMME_ROLE_CATALOG_ENTRIES) <= snapshot.catalog_entry_codes
    assert ("programme_operations", 1) not in ADOPTION_PROFILES
    for code, version in ADOPTION_PROFILES:
        for recipe in definitions:
            assert not profile_allows_catalog_entry(code, version, recipe.catalog_entry)
    with pytest.raises(TypeError):
        recipes.PROGRAMME_ROLE_RECIPES[("planner", 1)] = definitions[0]
    with pytest.raises(FrozenInstanceError):
        definitions[0].name = "Silently broadened"


@pytest.mark.parametrize("recipe", recipes.PROGRAMME_ROLE_RECIPES.values())
def test_each_recipe_has_only_known_persistent_owner_capabilities_at_legal_scopes(
    recipe,
):
    depth = {level: index for index, level in enumerate(ScopeLevel)}
    assert recipe.role_code not in {"executive-board", "maru-operators"}
    for code in recipe.capability_codes:
        definition = capability(code)
        assert definition is not None
        assert definition.persistable
        assert not definition.allow_self
        assert code.split(".")[0] in {
            "events",
            "applications",
            "programme",
            "scheduling",
            "venues",
            "workforce",
        }
        assert code != "applications.recover_programme_department_ownership"
        assert all(
            depth[level] >= depth[definition.maximum_scope]
            for level in recipe.target_scopes
        )
    for level in recipe.target_scopes:
        result = digest(intent(recipe_code=recipe.code), scope(level))
        assert len(result) == 64
    for level in set(ScopeLevel) - set(recipe.target_scopes):
        with pytest.raises(ValidationError):
            digest(intent(recipe_code=recipe.code), scope(level))


@pytest.mark.parametrize(
    ("code", "version"),
    [
        ("planner", True),
        ("planner", 0),
        ("planner", 2),
        ("planner", "1"),
        (" planner", 1),
        ("PLANNER", 1),
        (None, 1),
        ([], 1),
        ("planner", []),
    ],
)
def test_no_unknown_or_coerced_recipe_identity(code, version):
    assert recipes.programme_role_recipe(code, version) is None
    with pytest.raises(ValidationError):
        normalize_programme_role_intent(
            intent(recipe_code=code, recipe_version=version)
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"code": None},
        {"code": "x" * 80},
        {"version": True},
        {"version": "1"},
        {"version": 0},
        {"name": " "},
        {"name": "x" * 121},
        {"purpose": None},
        {"capability_codes": []},
        {"capability_codes": ([],)},
        {"capability_codes": ("programme.view_private",) * 2},
        {"capability_codes": ("invented.capability",)},
        {"capability_codes": ("authorization.manage_roles",)},
        {"capability_codes": ("applications.recover_programme_department_ownership",)},
        {"target_scopes": ("edition",)},
        {"target_scopes": ()},
        {"target_scopes": (ScopeLevel.ORGANIZATION,)},
        {"target_scopes": (ScopeLevel.EDITION,) * 2},
        {"resource_kind": "venue.edition_space"},
        {"resource_kind": None},
        {"target_scopes": (ScopeLevel.RESOURCE,), "resource_kind": "other.resource"},
    ],
)
def test_definition_validation_rejects_widening_and_malformed_literals(changes):
    with pytest.raises(ValueError, match="Programme role recipe"):
        recipes._validate(
            replace(recipes.programme_role_recipe("planner", 1), **changes)
        )


def test_normalization_is_pure_immutable_and_canonical():
    original = intent(reason="  Cafe\u0301  planning  ")
    result = normalize_programme_role_intent(original)
    assert result.reason == "Café planning"
    assert original.reason != result.reason
    assert normalize_programme_role_intent(result) == result
    assert digest(original) == digest(result)
    local = START.astimezone(timezone(timedelta(hours=2)))
    assert digest(intent(not_before=local)) == digest()
    with pytest.raises(FrozenInstanceError):
        result.reason = "Changed"
    assert PROGRAMME_ROLE_APPROVAL_DAYS == 7


@pytest.mark.parametrize("field", ["recipient_id", "approver_id"])
@pytest.mark.parametrize("value", [None, UUID(int=0), "person", 1, True])
def test_principal_identifiers_are_exact_nonempty_uuids(field, value):
    with pytest.raises(ValidationError):
        normalize_programme_role_intent(intent(**{field: value}))


def test_self_approval_and_untyped_intent_are_rejected():
    with pytest.raises(ValidationError, match="cannot approve"):
        normalize_programme_role_intent(intent(approver_id=UUID(int=3)))
    with pytest.raises(ValidationError):
        normalize_programme_role_intent({"recipe_code": "planner"})


@pytest.mark.parametrize("field", ["not_before", "expires_at"])
@pytest.mark.parametrize("value", [START.replace(tzinfo=None), "2027-01-01", True])
def test_instants_are_aware_not_coerced(field, value):
    with pytest.raises(ValidationError):
        normalize_programme_role_intent(intent(**{field: value}))


@pytest.mark.parametrize("end", [START, START - timedelta(seconds=1)])
def test_empty_or_negative_interval_is_rejected(end):
    with pytest.raises(ValidationError):
        normalize_programme_role_intent(intent(expires_at=end))


def test_nullable_horizons_are_distinct_intent_not_permission():
    variants = [
        intent(),
        intent(not_before=None),
        intent(expires_at=None),
        intent(not_before=None, expires_at=None),
    ]
    assert len({digest(value) for value in variants}) == 4
    # Current-time/authority expiry validation belongs to the later locked command.
    assert normalize_programme_role_intent(intent()).not_before == START


@pytest.mark.parametrize(
    "reason",
    [
        None,
        1,
        "",
        " ",
        "x" * 241,
        " " * 4097,
        "bad\nreason",
        "bad\x00reason",
        "bad\u202ereason",
    ],
)
def test_reason_is_bounded_control_free_text(reason):
    with pytest.raises(ValidationError):
        normalize_programme_role_intent(intent(reason=reason))
    with pytest.raises(ValidationError):
        programme_role_decision_digest(
            request_id=UUID(int=7),
            decision=ProgrammeRoleDecision.APPROVE,
            reason=reason,
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"organization_id": UUID(int=0)},
        {"programme_edition_id": "2"},
        {"department_id": UUID(int=5)},
        {"resource_binding_id": UUID(int=6)},
        {"resource_kind": "venue.edition_space"},
        {"level": "edition"},
    ],
)
def test_scope_rejects_missing_typed_or_inapplicable_facts(changes):
    with pytest.raises(ValidationError):
        digest(target=replace(scope(), **changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"department_id": None},
        {"department_id": UUID(int=0)},
        {"resource_binding_id": None},
        {"resource_binding_id": "6"},
        {"resource_kind": "other.resource"},
    ],
)
def test_room_intent_requires_complete_typed_chain(changes):
    with pytest.raises(ValidationError):
        digest(intent(recipe_code="run-sheet"), scope(ScopeLevel.RESOURCE, **changes))


def test_retry_digest_binds_every_scope_and_intent_fact():
    original = intent(recipe_code="run-sheet")
    target = scope(ScopeLevel.RESOURCE)
    fingerprints = {digest(original, target)}
    for field in (
        "organization_id",
        "programme_edition_id",
        "department_id",
        "resource_binding_id",
    ):
        fingerprints.add(digest(original, replace(target, **{field: UUID(int=99)})))
    for change in [
        {"recipe_code": "run-sheet-delivery"},
        {"recipient_id": UUID(int=99)},
        {"approver_id": UUID(int=99)},
        {"not_before": START + timedelta(seconds=1)},
        {"expires_at": START + timedelta(days=2)},
        {"reason": "Different intent"},
    ]:
        fingerprints.add(digest(replace(original, **change), target))
    assert len(fingerprints) == 11
    assert (
        len(
            {
                digest(original, scope(level))
                for level in (
                    ScopeLevel.EDITION,
                    ScopeLevel.DEPARTMENT,
                    ScopeLevel.RESOURCE,
                )
            }
        )
        == 3
    )


def test_terminal_digest_binds_request_action_reason_but_never_executes_it():
    def decision(**changes):
        values = {
            "request_id": UUID(int=7),
            "decision": ProgrammeRoleDecision.APPROVE,
            "reason": " Review complete ",
        }
        return programme_role_decision_digest(**(values | changes))

    assert decision() == decision(reason="Review complete")
    assert (
        len(
            {
                decision(),
                decision(request_id=UUID(int=8)),
                decision(reason="Different reason"),
                decision(decision=ProgrammeRoleDecision.DECLINE),
                decision(decision=ProgrammeRoleDecision.CANCEL),
            }
        )
        == 5
    )
    for invalid in [None, True, "approve", "unknown"]:
        with pytest.raises(ValidationError):
            decision(decision=invalid)
    with pytest.raises(ValidationError):
        decision(request_id=UUID(int=0))
