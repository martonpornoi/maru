"""Guides history stays explicit without deferring current ACL protection."""

from scripts.ci_test_policy import (
    build_groups,
    case_group,
    load_history_inventory,
    select_groups,
)

_FOUNDATION = "tests/integration/test_guidance_foundation_migrations.py"
_KNOWLEDGE = "tests/integration/test_knowledge_migrations.py"


def test_guides_history_inventory_names_only_actual_reversal_cases_and_owners():
    inventory = load_history_inventory()
    assert inventory[_FOUNDATION].owners == frozenset(
        {"announcements", "authorization", "events", "knowledge", "organizations"}
    )
    assert inventory[_FOUNDATION].tests == frozenset(
        {
            "test_bare_used_foundation_refuses_before_any_successor_recorder_changes",
            "test_unused_guidance_reverse_reapply_preserves_hardened_predecessor",
        }
    )
    assert inventory[_KNOWLEDGE].owners == frozenset(
        {"announcements", "authorization", "events", "knowledge"}
    )
    assert inventory[_KNOWLEDGE].tests == frozenset(
        {
            "test_unused_knowledge_fully_reverses_and_reapplies_native_contract",
            "test_unused_owner_still_fences_retained_foundation_before_successor_reversal",
            "test_used_knowledge_refuses_before_any_migration_or_owner_evidence_changes",
        }
    )
    # These fixtures are function-scoped. Each complete parameter group stays
    # indivisible, without requiring unrelated historical cases to share a DB.
    assert not inventory[_FOUNDATION].shared_baseline
    assert not inventory[_KNOWLEDGE].shared_baseline


def test_current_acl_checks_remain_selected_while_historical_cases_follow_owners():
    inventory = load_history_inventory()
    groups = build_groups()
    current = {group.key for group in select_groups(groups, inventory, "current")}
    for function in (
        "test_fresh_guidance_migration_hardens_aggregate_before_any_setup",
        "test_aggregate_public_execute_drift_denies_guidance_setup",
    ):
        assert case_group(_FOUNDATION, function, inventory) == _FOUNDATION + "::current"
    assert _FOUNDATION + "::current" in current
    for file in (_FOUNDATION, _KNOWLEDGE):
        history = {case_group(file, name, inventory) for name in inventory[file].tests}
        assert not history & current
        for owner in inventory[file].owners:
            selected = select_groups(groups, inventory, "affected", frozenset({owner}))
            assert history <= {group.key for group in selected}
