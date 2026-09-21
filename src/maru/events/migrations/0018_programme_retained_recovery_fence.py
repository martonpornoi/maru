"""Preserve every retained Programme boundary before joined successor reversal."""

from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations

# Frozen migration preflights only: no current registry, inferred namespace,
# runtime command, data rewrite or replacement of the original owner checks.
# Native evidence remains first, preserving its established recovery contract.
PREFLIGHTS = (
    (
        "events.0017_programme_exit_recovery_fence",
        "refuse_used_exit_generation_downgrade",
    ),
    (
        "workforce.0028_programme_starter_execution_fence",
        "refuse_used_starter_execution_downgrade",
    ),
    ("events.0016_programme_stop_integrity", "refuse_used_stop_downgrade"),
    ("programme.0020_exit_archive_records", "refuse_used_archive_downgrade"),
    (
        "authorization.0037_programme_archive_capability",
        "refuse_used_archive_capability_downgrade",
    ),
    (
        "authorization.0034_programme_role_approval_downgrade_fence",
        "refuse_used_approval_guard_downgrade",
    ),
    (
        "events.0014_programme_setup_downgrade_fence",
        "refuse_used_setup_guard_downgrade",
    ),
    (
        "authorization.0029_programme_release_capabilities",
        "refuse_used_release_capability_downgrade",
    ),
    (
        "authorization.0028_programme_staffing_capabilities",
        "refuse_used_staffing_capability_downgrade",
    ),
    (
        "authorization.0027_scheduling_capabilities",
        "refuse_used_scheduling_capability_downgrade",
    ),
    (
        "authorization.0026_programme_host_capabilities",
        "refuse_used_host_capability_downgrade",
    ),
    (
        "authorization.0025_programme_conversion_capability",
        "refuse_used_conversion_capability_downgrade",
    ),
    (
        "authorization.0024_programme_review_capabilities",
        "refuse_used_review_capability_downgrade",
    ),
    (
        "authorization.0023_programme_department_ownership_recovery",
        "refuse_used_recovery_capability_downgrade",
    ),
    (
        "authorization.0022_programme_import_capabilities",
        "refuse_used_programme_import_capability_downgrade",
    ),
    (
        "authorization.0021_applications_programme_capabilities",
        "refuse_used_applications_programme_capability_downgrade",
    ),
    (
        "authorization.0020_programme_capabilities",
        "refuse_used_programme_capability_downgrade",
    ),
    (
        "applications.0021_programme_file_downgrade_fence",
        "refuse_populated_programme_file_downgrade",
    ),
    (
        "applications.0018_programme_conversion_downgrade_fence",
        "refuse_populated_programme_conversion_downgrade",
    ),
    (
        "applications.0015_programme_review_downgrade_fence",
        "refuse_populated_programme_review_downgrade",
    ),
    (
        "applications.0012_programme_department_ownership_downgrade_fence",
        "refuse_populated_ownership_continuity_downgrade",
    ),
    (
        "applications.0009_programme_import_populated_downgrade_fence",
        "refuse_used_programme_import_downgrade",
    ),
    (
        "applications.0006_programme_populated_downgrade_fence",
        "refuse_used_applications_programme_downgrade",
    ),
    (
        "programme.0015_placement_decision_downgrade_fence",
        "refuse_used_placement_decision_downgrade",
    ),
    ("programme.0012_staffing_downgrade_fence", "refuse_used_staffing_downgrade"),
    ("programme.0009_host_downgrade_fence", "refuse_used_host_downgrade"),
    (
        "programme.0006_accepted_item_downgrade_fence",
        "refuse_populated_accepted_item_downgrade",
    ),
    ("programme.0003_downgrade_fence", "refuse_used_programme_downgrade"),
    ("scheduling.0006_scheduling_downgrade_fence", "refuse_used_scheduling_downgrade"),
    (
        "workforce.0021_programme_binding_downgrade_fence",
        "refuse_used_programme_binding_downgrade",
    ),
)


def refuse_retained_programme_downgrade(apps: Any, schema_editor: Any) -> None:
    """Run the frozen owner preflights atomically before any successor can reverse.

    The starter execution preflight includes notice rows, retained notice/operator
    authority and the complete reviewed-copy/release fence. All preflights retain
    their original locks, queries and refusal messages. Recovery is an offline
    maintenance operation, never concurrent with live application writers.
    """
    for reference, name in PREFLIGHTS:
        owner, migration = reference.split(".", 1)
        boundary = import_module(f"maru.{owner}.migrations.{migration}")
        getattr(boundary, name)(apps, schema_editor)


class Migration(migrations.Migration):
    """Permit unused reversal while retaining all used joined Programme guards."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("events", "0017_programme_exit_recovery_fence"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunPython(
            migrations.RunPython.noop, refuse_retained_programme_downgrade
        ),
    ]
