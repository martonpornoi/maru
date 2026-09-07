"""Fence the complete joint reservation graph before removing any owner guard."""

from __future__ import annotations

from typing import Any, ClassVar

from django.db import migrations

RETAINED_MODELS = (
    ("scheduling", "schedulingeditioncontrol"),
    ("scheduling", "schedulingserviceday"),
    ("scheduling", "schedulingservicedayrevision"),
    ("scheduling", "schedulingoccurrence"),
    ("scheduling", "schedulingoccurrencerevision"),
    ("scheduling", "schedulingcandidate"),
    ("scheduling", "schedulingcandidaterevision"),
    ("scheduling", "schedulingplacementrevision"),
    ("scheduling", "schedulingcandidatemember"),
    ("scheduling", "schedulingplacementhostpresence"),
    ("scheduling", "schedulingevaluation"),
    ("scheduling", "schedulingconflict"),
    ("scheduling", "schedulingwarningacknowledgement"),
    ("scheduling", "schedulingreservationintent"),
    ("scheduling", "schedulingcommandreceipt"),
    ("venues", "venueschedulingbinding"),
)


def refuse_used_scheduling_downgrade(apps: Any, schema_editor: Any) -> None:
    """Keep both owners' integrity intact after any retained Scheduling history."""
    models = tuple(apps.get_model(app, name) for app, name in RETAINED_MODELS)
    tables = sorted(schema_editor.quote_name(model._meta.db_table) for model in models)
    schema_editor.execute(
        "LOCK TABLE " + ", ".join(tables) + " IN ACCESS EXCLUSIVE MODE"
    )
    if any(model.objects.exists() for model in models):
        raise RuntimeError(
            "Cannot remove Scheduling or reciprocal Venue integrity after retained "
            "planning history exists; retain compatible code and fix forward."
        )


class Migration(migrations.Migration):
    """Refuse populated reversal before either owner's integrity is removed."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("venues", "0004_scheduling_binding_integrity"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_used_scheduling_downgrade,
        ),
    ]
