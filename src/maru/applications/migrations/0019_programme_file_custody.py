"""Add dormant exact Programme file provenance and isolated private bytes."""

import uuid
from typing import ClassVar

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Separate bounded supporting bytes from immutable purpose metadata."""

    dependencies: ClassVar[list[object]] = [
        ("applications", "0018_programme_conversion_downgrade_fence"),
        ("events", "0011_release_dependency_mutations"),
        ("organizations", "0014_purpose_bounded_representation"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations: ClassVar[list[object]] = [
        migrations.CreateModel(
            name="ProgrammeFileIntake",
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
                ("source_version", models.PositiveBigIntegerField()),
                ("call_version", models.PositiveBigIntegerField()),
                ("definition_version", models.PositiveBigIntegerField()),
                ("retry_key", models.UUIDField()),
                ("scanned_at", models.DateTimeField()),
                (
                    "actor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "edition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="events.eventedition",
                    ),
                ),
                (
                    "file_receipt",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="applications.applicationfilereceipt",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="organizations.organization",
                    ),
                ),
                (
                    "proposal",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="applications.programmeproposal",
                    ),
                ),
                (
                    "question",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="applications.applicationquestion",
                    ),
                ),
            ],
            options={
                "ordering": ("proposal_id", "source_version"),
            },
        ),
        migrations.CreateModel(
            name="ProgrammeFileContent",
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
                ("payload", models.BinaryField(max_length=10485760)),
                (
                    "intake",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="applications.programmefileintake",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.AddConstraint(
            model_name="programmefileintake",
            constraint=models.UniqueConstraint(
                fields=("proposal", "source_version"), name="app_prg_file_source_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="programmefileintake",
            constraint=models.UniqueConstraint(
                fields=("edition", "actor", "retry_key"), name="app_prg_file_retry_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="programmefileintake",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("source_version__gte", 1),
                    ("source_version__lte", 9223372036854775806),
                    ("call_version__gte", 1),
                    ("definition_version__gte", 1),
                ),
                name="app_prg_file_versions",
            ),
        ),
    ]
