"""Add scoped archive requests, immutable lifecycle evidence and disposable chunks."""

import uuid
from typing import Any, ClassVar

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.migrations.operations.base import Operation

UNUSED_PREFLIGHT = """
LOCK TABLE public.programme_programmearchivetask,
    public.programme_programmearchivetaskevent,
    public.programme_programmearchivechunk IN ACCESS EXCLUSIVE MODE;
DO $archive_unused$
BEGIN
    IF EXISTS (SELECT 1 FROM public.programme_programmearchivetask LIMIT 1)
       OR EXISTS (SELECT 1 FROM public.programme_programmearchivetaskevent LIMIT 1)
       OR EXISTS (SELECT 1 FROM public.programme_programmearchivechunk LIMIT 1) THEN
        RAISE EXCEPTION 'Programme archive request evidence exists; fix forward';
    END IF;
END;
$archive_unused$;
"""


def refuse_used_archive_downgrade(apps: Any, schema_editor: Any) -> None:
    """Keep any retained archive request, event or custody row on attempted reversal."""
    del apps
    schema_editor.execute(UNUSED_PREFLIGHT)


class Migration(migrations.Migration):
    """Install dormant archive custody with an unused-only reversal fence."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("audit", "0009_native_mutation_witness"),
        ("events", "0014_programme_setup_downgrade_fence"),
        ("organizations", "0014_purpose_bounded_representation"),
        ("programme", "0019_public_copy_withdrawal_integrity"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations: ClassVar[list[Operation]] = [
        migrations.CreateModel(
            name="ProgrammeArchiveTask",
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
                ("request_key", models.UUIDField()),
                ("contract", models.CharField(max_length=64)),
                ("version", models.PositiveBigIntegerField()),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("queued", "Queued"),
                            ("running", "Running"),
                            ("ready", "Ready"),
                            ("failed", "Failed"),
                            ("cancelled", "Cancelled"),
                            ("expired", "Expired"),
                        ],
                        max_length=16,
                    ),
                ),
                ("requested_at", models.DateTimeField()),
                ("expires_at", models.DateTimeField()),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("generation_correlation_id", models.UUIDField(blank=True, null=True)),
                (
                    "source_digest",
                    models.CharField(
                        blank=True,
                        max_length=64,
                        validators=[
                            django.core.validators.RegexValidator(
                                code="invalid_programme_digest",
                                message="Use a lower-case SHA-256 digest.",
                                regex="^[0-9a-f]{64}\\Z",
                            )
                        ],
                    ),
                ),
                (
                    "artifact_digest",
                    models.CharField(
                        blank=True,
                        max_length=64,
                        validators=[
                            django.core.validators.RegexValidator(
                                code="invalid_programme_digest",
                                message="Use a lower-case SHA-256 digest.",
                                regex="^[0-9a-f]{64}\\Z",
                            )
                        ],
                    ),
                ),
                (
                    "chunk_root",
                    models.CharField(
                        blank=True,
                        max_length=64,
                        validators=[
                            django.core.validators.RegexValidator(
                                code="invalid_programme_digest",
                                message="Use a lower-case SHA-256 digest.",
                                regex="^[0-9a-f]{64}\\Z",
                            )
                        ],
                    ),
                ),
                ("artifact_bytes", models.PositiveBigIntegerField(default=0)),
                ("chunk_count", models.PositiveIntegerField(default=0)),
                ("failure_code", models.CharField(blank=True, max_length=32)),
                (
                    "actor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_archive_tasks",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "edition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_archive_tasks",
                        to="events.eventedition",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_archive_tasks",
                        to="organizations.organization",
                    ),
                ),
                (
                    "previous_task",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="replacement_requests",
                        to="programme.programmearchivetask",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="ProgrammeArchiveChunk",
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
                ("sequence", models.PositiveIntegerField()),
                ("size_bytes", models.PositiveIntegerField()),
                (
                    "sha256",
                    models.CharField(
                        max_length=64,
                        validators=[
                            django.core.validators.RegexValidator(
                                code="invalid_programme_digest",
                                message="Use a lower-case SHA-256 digest.",
                                regex="^[0-9a-f]{64}\\Z",
                            )
                        ],
                    ),
                ),
                ("payload", models.BinaryField(max_length=1048576)),
                (
                    "task",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="artifact_chunks",
                        to="programme.programmearchivetask",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="ProgrammeArchiveTaskEvent",
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
                ("version", models.PositiveBigIntegerField()),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("queued", "Queued"),
                            ("running", "Running"),
                            ("ready", "Ready"),
                            ("failed", "Failed"),
                            ("cancelled", "Cancelled"),
                            ("expired", "Expired"),
                        ],
                        max_length=16,
                    ),
                ),
                ("occurred_at", models.DateTimeField()),
                ("correlation_id", models.UUIDField()),
                ("failure_code", models.CharField(blank=True, max_length=32)),
                (
                    "audit_event",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_archive_lifecycle_event",
                        to="audit.auditevent",
                    ),
                ),
                (
                    "task",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="lifecycle_events",
                        to="programme.programmearchivetask",
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="programmearchivetask",
            index=models.Index(
                fields=["organization", "edition", "actor"],
                name="prg_archive_scope_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="programmearchivetask",
            index=models.Index(
                fields=["state", "expires_at"], name="prg_archive_worker_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="programmearchivetask",
            constraint=models.UniqueConstraint(
                fields=("edition", "actor", "request_key"),
                name="programme_archive_request_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmearchivetask",
            constraint=models.CheckConstraint(
                condition=models.Q(("version__gte", 1)),
                name="programme_archive_version_pos",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmearchivetask",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    (
                        "state__in",
                        (
                            "queued",
                            "running",
                            "ready",
                            "failed",
                            "cancelled",
                            "expired",
                        ),
                    )
                ),
                name="programme_archive_state_closed",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmearchivetask",
            constraint=models.CheckConstraint(
                condition=models.Q(("contract", "programme.exit-archive@1")),
                name="programme_archive_contract",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmearchivetask",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("artifact_bytes__lte", 1075838976), ("chunk_count__lte", 1026)
                ),
                name="programme_archive_byte_limits",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmearchivechunk",
            constraint=models.UniqueConstraint(
                fields=("task", "sequence"), name="programme_archive_chunk_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="programmearchivechunk",
            constraint=models.CheckConstraint(
                condition=models.Q(("sequence__gte", 1), ("sequence__lte", 1026)),
                name="programme_archive_chunk_seq",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmearchivechunk",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("size_bytes__gte", 1), ("size_bytes__lte", 1048576)
                ),
                name="programme_archive_chunk_size",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmearchivetaskevent",
            constraint=models.UniqueConstraint(
                fields=("task", "version"), name="programme_archive_event_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="programmearchivetaskevent",
            constraint=models.CheckConstraint(
                condition=models.Q(("version__gte", 1)),
                name="programme_archive_event_pos",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmearchivetaskevent",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    (
                        "state__in",
                        (
                            "queued",
                            "running",
                            "ready",
                            "failed",
                            "cancelled",
                            "expired",
                        ),
                    )
                ),
                name="programme_archive_event_state",
            ),
        ),
        migrations.RunPython(migrations.RunPython.noop, refuse_used_archive_downgrade),
    ]
