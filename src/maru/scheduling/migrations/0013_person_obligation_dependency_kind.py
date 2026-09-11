"""Retain global person-work freshness without admitting release edits to drafts."""

from typing import Any, ClassVar

from django.conf import settings
from django.db import migrations, models


def refuse_used_person_obligation_downgrade(apps: Any, schema_editor: Any) -> None:
    """Preserve the new source and receipt vocabularies once their evidence exists."""
    schema_editor.execute(
        "LOCK TABLE public.scheduling_schedulingcommandreceipt, "
        "public.scheduling_schedulingreleasedependencykey IN ACCESS EXCLUSIVE MODE"
    )
    key = apps.get_model("scheduling", "SchedulingReleaseDependencyKey")
    receipt = apps.get_model("scheduling", "SchedulingCommandReceipt")
    if (
        key.objects.filter(kind="workforce_person_obligations").exists()
        or receipt.objects.filter(
            operation__in=(
                "release_warning_acknowledge",
                "release_approve",
                "release_publish",
                "release_withdraw",
            )
        ).exists()
    ):
        raise RuntimeError(
            "Person-work or release decision evidence exists; fix forward."
        )


class Migration(migrations.Migration):
    """Add exact receipt and source vocabulary with a populated contraction fence."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("events", "0011_release_dependency_mutations"),
        ("organizations", "0014_purpose_bounded_representation"),
        ("scheduling", "0012_release_native_execution_boundary"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RemoveConstraint(
            model_name="schedulingcommandreceipt",
            name="sch_command_receipt_shape",
        ),
        migrations.RemoveConstraint(
            model_name="schedulingreleasedependencykey",
            name="sch_release_dependency_scope",
        ),
        migrations.AlterField(
            model_name="schedulingcommandreceipt",
            name="operation",
            field=models.CharField(
                choices=[
                    ("day_create", "Day Create"),
                    ("day_revise", "Day Revise"),
                    ("day_retire", "Day Retire"),
                    ("occurrence_create", "Occurrence Create"),
                    ("occurrence_revise", "Occurrence Revise"),
                    ("occurrence_retire", "Occurrence Retire"),
                    ("candidate_create", "Candidate Create"),
                    ("candidate_copy", "Candidate Copy"),
                    ("placement_set", "Placement Set"),
                    ("placement_remove", "Placement Remove"),
                    ("candidate_restore", "Candidate Restore"),
                    ("candidate_archive", "Candidate Archive"),
                    ("evaluation_record", "Evaluation Record"),
                    ("warning_acknowledge", "Warning Acknowledge"),
                    ("reservation_replace", "Reservation Replace"),
                    ("reservation_cancel", "Reservation Cancel"),
                    ("release_warning_acknowledge", "Release Warning Acknowledge"),
                    ("release_approve", "Release Approve"),
                    ("release_publish", "Release Publish"),
                    ("release_withdraw", "Release Withdraw"),
                ],
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="schedulingreleasedependencykey",
            name="kind",
            field=models.CharField(
                choices=[
                    ("edition_operational", "Edition Operational"),
                    ("programme_item", "Programme Item"),
                    ("programme_host_operational", "Programme Host Operational"),
                    ("programme_host_disclosure", "Programme Host Disclosure"),
                    ("programme_public_copy", "Programme Public Copy"),
                    ("workforce_demand", "Workforce Demand"),
                    ("workforce_assignment", "Workforce Assignment"),
                    ("workforce_availability", "Workforce Availability"),
                    ("workforce_person_obligations", "Workforce Person Obligations"),
                    ("venue_property", "Venue Property"),
                    ("venue_member", "Venue Member"),
                    ("venue_selection", "Venue Selection"),
                    ("venue_booking", "Venue Booking"),
                    ("identity_account", "Identity Account"),
                ],
                max_length=40,
            ),
        ),
        migrations.AddConstraint(
            model_name="schedulingcommandreceipt",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("control_version__gt", 0),
                    (
                        "operation__in",
                        (
                            "day_create",
                            "day_revise",
                            "day_retire",
                            "occurrence_create",
                            "occurrence_revise",
                            "occurrence_retire",
                            "candidate_create",
                            "candidate_copy",
                            "placement_set",
                            "placement_remove",
                            "candidate_restore",
                            "candidate_archive",
                            "evaluation_record",
                            "warning_acknowledge",
                            "reservation_replace",
                            "reservation_cancel",
                            "release_warning_acknowledge",
                            "release_approve",
                            "release_publish",
                            "release_withdraw",
                        ),
                    ),
                    ("resulting_version__gt", 0),
                    models.Q(("reason", ""), _negated=True),
                ),
                name="sch_command_receipt_shape",
            ),
        ),
        migrations.AddConstraint(
            model_name="schedulingreleasedependencykey",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("edition__isnull", True),
                        (
                            "kind__in",
                            ("identity_account", "workforce_person_obligations"),
                        ),
                        ("organization__isnull", True),
                    ),
                    models.Q(
                        ("edition__isnull", True),
                        ("kind__in", ("venue_member", "venue_property")),
                        ("organization__isnull", False),
                    ),
                    models.Q(
                        ("edition__isnull", False),
                        (
                            "kind__in",
                            (
                                "edition_operational",
                                "programme_host_disclosure",
                                "programme_host_operational",
                                "programme_item",
                                "programme_public_copy",
                                "venue_booking",
                                "venue_selection",
                                "workforce_assignment",
                                "workforce_availability",
                                "workforce_demand",
                            ),
                        ),
                        ("organization__isnull", False),
                    ),
                    _connector="OR",
                ),
                name="sch_release_dependency_scope",
            ),
        ),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_used_person_obligation_downgrade
        ),
    ]
