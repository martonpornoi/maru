from __future__ import annotations

import importlib
import inspect

from django.contrib.postgres.operations import BtreeGistExtension
from django.db.migrations.loader import MigrationLoader

from maru.logistics import services

_initial_migration = importlib.import_module("maru.logistics.migrations.0001_initial")
_migration = importlib.import_module(
    "maru.logistics.migrations.0002_logistics_write_integrity"
)
_venue_initial_migration = importlib.import_module(
    "maru.venues.migrations.0001_initial"
)


def test_venue_migration_owns_the_shared_btree_gist_extension() -> None:
    assert ("venues", "0001_initial") in _initial_migration.Migration.dependencies
    assert not any(
        isinstance(operation, BtreeGistExtension)
        for operation in _initial_migration.Migration.operations
    )
    assert (
        sum(
            isinstance(operation, BtreeGistExtension)
            for operation in _venue_initial_migration.Migration.operations
        )
        == 1
    )


def test_authorization_history_reverses_logistics_before_extension_owner() -> None:
    loader = MigrationLoader(None, ignore_no_migrations=True)

    plan = loader.graph.backwards_plan(
        ("authorization", "0006_authority_issuance_schema")
    )

    assert plan.index(("logistics", "0001_initial")) < plan.index(
        ("venues", "0001_initial")
    )


def test_logistics_wall_clock_guards_use_actual_trigger_time() -> None:
    sql = _migration.FORWARD_SQL

    assert "CURRENT_TIMESTAMP" not in sql
    assert sql.count("clock_timestamp()") == 6


def test_offline_duplicate_requires_exact_original_operation_inputs() -> None:
    sql = _migration.FORWARD_SQL

    required_correspondence = (
        "prior_operation.sequence = NEW.sequence",
        "prior_operation.expected_subject_sequence =",
        "prior_operation.action = NEW.action",
        "prior_operation.label_code = NEW.label_code",
        "prior_operation.source_label_code = NEW.source_label_code",
        "prior_operation.destination_label_code =",
        "prior_operation.quantity IS NOT DISTINCT FROM NEW.quantity",
        "prior_operation.observed_condition = NEW.observed_condition",
        "prior_operation.occurred_at = NEW.occurred_at",
        "prior_operation.applied_event_id IS NOT DISTINCT FROM",
        "prior_operation.discrepancy_id IS NOT DISTINCT FROM",
    )
    assert all(clause in sql for clause in required_correspondence)


def test_duplicate_discrepancy_marks_the_new_batch_for_review() -> None:
    source = inspect.getsource(services.ingest_offline_scan_batch)

    duplicate_branch = source.split(
        "result = OfflineScanOperation.Result.DUPLICATE", maxsplit=1
    )[1].split("else:", maxsplit=1)[0]
    assert "discrepancy = prior.discrepancy" in duplicate_branch
    assert "if discrepancy is not None:" in duplicate_branch
    assert "needs_review = True" in duplicate_branch


def test_offline_subject_label_lock_excludes_nullable_related_rows() -> None:
    source = inspect.getsource(services.ingest_offline_scan_batch)

    assert (
        'LogisticsLabel.objects.select_for_update(of=("self",))\n'
        '                .select_related("node", "asset", "stock_lot", "physical_key")'
        in source
    )


def test_manifest_receipt_publishes_the_canonical_receive_action() -> None:
    source = inspect.getsource(services.record_manifest_receipt)
    evidence_append = source.split("return _append_evidence(", maxsplit=1)[1]

    assert "action=LogisticsEvent.EventType.RECEIVE" in evidence_append
    assert 'action="received"' not in evidence_append


def test_state_conflict_review_requires_a_concrete_insertion_point_mismatch() -> None:
    sql = _migration.FORWARD_SQL

    assert "offline state-conflict review remains appendable" in sql
    assert "NEW.expected_subject_sequence = COALESCE(state.event_sequence, 0)" in sql
    assert "source_node.id = state.current_node_id" in sql
    assert "WITH RECURSIVE ancestors(id, depth)" in sql
    assert "NEW.quantity = state.quantity_on_hand" in sql
