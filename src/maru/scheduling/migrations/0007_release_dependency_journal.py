"""Retain immutable native dependency identity and consecutive change evidence."""

import uuid
from typing import ClassVar

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Install source tracking without granting release or runtime write authority."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("audit", "0008_identity_retention_audit_uniqueness"),
        ("events", "0010_workforce_adoption_profile"),
        ("organizations", "0014_purpose_bounded_representation"),
        ("scheduling", "0006_scheduling_downgrade_fence"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.CreateModel(
            name="SchedulingReleaseDependencyKey",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("edition_operational", "Edition Operational"),
                            ("programme_item", "Programme Item"),
                            (
                                "programme_host_operational",
                                "Programme Host Operational",
                            ),
                            ("programme_host_disclosure", "Programme Host Disclosure"),
                            ("programme_public_copy", "Programme Public Copy"),
                            ("workforce_demand", "Workforce Demand"),
                            ("workforce_assignment", "Workforce Assignment"),
                            ("workforce_availability", "Workforce Availability"),
                            ("venue_property", "Venue Property"),
                            ("venue_member", "Venue Member"),
                            ("venue_selection", "Venue Selection"),
                            ("venue_booking", "Venue Booking"),
                            ("identity_account", "Identity Account"),
                        ],
                        max_length=40,
                    ),
                ),
                ("source_id", models.UUIDField()),
                ("generation", models.PositiveBigIntegerField(default=1)),
                (
                    "edition",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="scheduling_release_dependency_keys",
                        to="events.eventedition",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="scheduling_release_dependency_keys",
                        to="organizations.organization",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="SchedulingReleaseDependencyChange",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("generation", models.PositiveBigIntegerField()),
                ("recorded_at", models.DateTimeField()),
                (
                    "edition",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="scheduling_release_dependency_changes",
                        to="events.eventedition",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="scheduling_release_dependency_changes",
                        to="organizations.organization",
                    ),
                ),
                (
                    "source_audit",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="scheduling_release_dependency_changes",
                        to="audit.auditevent",
                    ),
                ),
                (
                    "dependency",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="changes",
                        to="scheduling.schedulingreleasedependencykey",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="schedulingreleasedependencykey",
            constraint=models.UniqueConstraint(
                fields=("kind", "source_id"), name="sch_release_dependency_source_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="schedulingreleasedependencykey",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("generation__gt", 0), ("generation__lt", 9223372036854775807)
                ),
                name="sch_release_dependency_gen",
            ),
        ),
        migrations.AddConstraint(
            model_name="schedulingreleasedependencykey",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("edition__isnull", True),
                        ("kind__in", ("identity_account",)),
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
        migrations.AddConstraint(
            model_name="schedulingreleasedependencychange",
            constraint=models.UniqueConstraint(
                fields=("dependency", "generation"),
                name="sch_release_change_generation_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="schedulingreleasedependencychange",
            constraint=models.UniqueConstraint(
                fields=("dependency", "source_audit"),
                name="sch_release_change_audit_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="schedulingreleasedependencychange",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("generation__gt", 1), ("generation__lt", 9223372036854775807)
                ),
                name="sch_release_change_generation",
            ),
        ),
    ]
