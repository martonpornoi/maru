"""Add the dormant, preview-first Programme-import persistence schema."""

# ruff: noqa: E501 -- Migration state is intentionally explicit and immutable.

from __future__ import annotations

import uuid
from typing import ClassVar

import django.core.validators
import django.db.models.deletion
import django.db.models.expressions
from django.conf import settings
from django.db import migrations, models

REVERSE_PREFLIGHT_SQL = r"""
LOCK TABLE
    public.applications_programmeimportappliedcommand,
    public.applications_programmeimportcommandreceipt,
    public.applications_programmeimportsourcebinding,
    public.applications_programmeimportpreviewitemresult,
    public.applications_programmeimportpreviewrevision,
    public.applications_programmeimportitem,
    public.applications_programmeimportbatch
IN ACCESS EXCLUSIVE MODE;

DO $applications_0007_reverse_preflight$
BEGIN
    IF EXISTS (SELECT 1 FROM public.applications_programmeimportappliedcommand LIMIT 1)
       OR EXISTS (SELECT 1 FROM public.applications_programmeimportcommandreceipt LIMIT 1)
       OR EXISTS (SELECT 1 FROM public.applications_programmeimportsourcebinding LIMIT 1)
       OR EXISTS (SELECT 1 FROM public.applications_programmeimportpreviewitemresult LIMIT 1)
       OR EXISTS (SELECT 1 FROM public.applications_programmeimportpreviewrevision LIMIT 1)
       OR EXISTS (SELECT 1 FROM public.applications_programmeimportitem LIMIT 1)
       OR EXISTS (SELECT 1 FROM public.applications_programmeimportbatch LIMIT 1)
    THEN
        RAISE EXCEPTION
            'Cannot remove Applications Programme-import schema while retained evidence exists'
            USING ERRCODE = '23514';
    END IF;
END;
$applications_0007_reverse_preflight$;
"""

_DIGEST_VALIDATOR = django.core.validators.RegexValidator(
    code="invalid_programme_application_digest",
    message="Use a lower-case SHA-256 digest.",
    regex=r"^[0-9a-f]{64}\Z",
)
_POLICY_VALIDATOR = django.core.validators.RegexValidator(
    code="invalid_application_policy_code",
    message="Use a stable versioned policy code.",
    regex=r"^[a-z][a-z0-9_.:-]{2,119}$",
)
_SOURCE_CHANNEL_VALIDATOR = django.core.validators.RegexValidator(
    code="invalid_programme_application_source_channel",
    message="Use a registered lower-case source channel.",
    regex=r"^[a-z][a-z0-9_-]*\Z",
)
_SOURCE_SYSTEM_VALIDATOR = django.core.validators.RegexValidator(
    code="invalid_programme_import_source_system",
    message="Use a registered lower-case import source system.",
    regex=r"^[a-z][a-z0-9_.:-]{0,79}\Z",
)
_SOURCE_KEY_VALIDATOR = django.core.validators.RegexValidator(
    code="invalid_programme_import_source_key",
    message="Use a bounded ASCII Programme-import source key.",
    regex=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}\Z",
)


class Migration(migrations.Migration):
    """Create seven empty import-owned relations and their static constraints."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("applications", "0006_programme_populated_downgrade_fence"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.CreateModel(
            name="ProgrammeImportBatch",
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
                    "source_system",
                    models.CharField(
                        max_length=80, validators=[_SOURCE_SYSTEM_VALIDATOR]
                    ),
                ),
                (
                    "schema_version",
                    models.PositiveSmallIntegerField(default=1, editable=False),
                ),
                (
                    "source_digest",
                    models.CharField(max_length=64, validators=[_DIGEST_VALIDATOR]),
                ),
                (
                    "item_count",
                    models.PositiveIntegerField(
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(1000),
                        ]
                    ),
                ),
                (
                    "retention_policy_code",
                    models.CharField(max_length=120, validators=[_POLICY_VALIDATOR]),
                ),
                ("expires_at", models.DateTimeField()),
                (
                    "state",
                    models.CharField(
                        choices=[("staged", "Staged"), ("discarded", "Discarded")],
                        default="staged",
                        max_length=16,
                    ),
                ),
                (
                    "aggregate_version",
                    models.PositiveBigIntegerField(default=1, editable=False),
                ),
                (
                    "discarded_at",
                    models.DateTimeField(blank=True, editable=False, null=True),
                ),
                (
                    "discard_reason",
                    models.CharField(blank=True, editable=False, max_length=500),
                ),
                (
                    "discarded_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_import_batches_discarded",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "edition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_import_batches",
                        to="events.eventedition",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_import_batches",
                        to="organizations.organization",
                    ),
                ),
                (
                    "owner_department",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_import_batches_owned",
                        to="workforce.department",
                    ),
                ),
                (
                    "staged_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_import_batches_staged",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ("edition_id", "created_at", "id")},
        ),
        migrations.CreateModel(
            name="ProgrammeImportItem",
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
                (
                    "kind",
                    models.CharField(
                        choices=[("call", "Call"), ("proposal", "Proposal")],
                        max_length=8,
                    ),
                ),
                (
                    "source_key",
                    models.CharField(
                        max_length=200, validators=[_SOURCE_KEY_VALIDATOR]
                    ),
                ),
                (
                    "source_digest",
                    models.CharField(max_length=64, validators=[_DIGEST_VALIDATOR]),
                ),
                ("canonical_payload", models.BinaryField(blank=True, null=True)),
                ("payload_size_bytes", models.PositiveIntegerField()),
                (
                    "dependency_source_system",
                    models.CharField(
                        blank=True, max_length=80, validators=[_SOURCE_SYSTEM_VALIDATOR]
                    ),
                ),
                (
                    "dependency_source_key",
                    models.CharField(
                        blank=True, max_length=200, validators=[_SOURCE_KEY_VALIDATOR]
                    ),
                ),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("staged", "Staged"),
                            ("applied", "Applied"),
                            ("discarded", "Discarded"),
                        ],
                        default="staged",
                        max_length=16,
                    ),
                ),
                (
                    "aggregate_version",
                    models.PositiveBigIntegerField(default=1, editable=False),
                ),
                (
                    "batch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="items",
                        to="applications.programmeimportbatch",
                    ),
                ),
                (
                    "edition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_import_items",
                        to="events.eventedition",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_import_items",
                        to="organizations.organization",
                    ),
                ),
            ],
            options={"ordering": ("batch_id", "sequence", "id")},
        ),
        migrations.CreateModel(
            name="ProgrammeImportPreviewRevision",
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
                ("revision_number", models.PositiveBigIntegerField()),
                (
                    "source_batch_version",
                    models.PositiveBigIntegerField(default=1, editable=False),
                ),
                (
                    "preview_digest",
                    models.CharField(max_length=64, validators=[_DIGEST_VALIDATOR]),
                ),
                (
                    "item_count",
                    models.PositiveIntegerField(
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(1000),
                        ]
                    ),
                ),
                (
                    "actor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_import_preview_revisions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "batch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="preview_revisions",
                        to="applications.programmeimportbatch",
                    ),
                ),
                (
                    "edition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_import_preview_revisions",
                        to="events.eventedition",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_import_preview_revisions",
                        to="organizations.organization",
                    ),
                ),
            ],
            options={"ordering": ("batch_id", "revision_number", "id")},
        ),
        migrations.CreateModel(
            name="ProgrammeImportPreviewItemResult",
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
                ("item_version", models.PositiveBigIntegerField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("ready", "Ready"),
                            ("blocked", "Blocked"),
                            ("no_op", "No operation"),
                            ("conflict", "Conflict"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("commit_call", "Commit call"),
                            ("claim_proposal", "Claim proposal"),
                            ("none", "None"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "dependency_state",
                    models.CharField(
                        choices=[
                            ("none", "None"),
                            ("missing", "Missing"),
                            ("draft", "Draft"),
                            ("active", "Active"),
                            ("retired", "Retired"),
                        ],
                        max_length=8,
                    ),
                ),
                (
                    "dependency_digest",
                    models.CharField(
                        blank=True, max_length=64, validators=[_DIGEST_VALIDATOR]
                    ),
                ),
                (
                    "dependency_version",
                    models.PositiveBigIntegerField(blank=True, null=True),
                ),
                ("safe_field_keys", models.JSONField(blank=True)),
                ("reason_codes", models.JSONField(blank=True)),
                (
                    "result_digest",
                    models.CharField(max_length=64, validators=[_DIGEST_VALIDATOR]),
                ),
                (
                    "edition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_import_preview_item_results",
                        to="events.eventedition",
                    ),
                ),
                (
                    "item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="preview_results",
                        to="applications.programmeimportitem",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_import_preview_item_results",
                        to="organizations.organization",
                    ),
                ),
                (
                    "preview",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="item_results",
                        to="applications.programmeimportpreviewrevision",
                    ),
                ),
            ],
            options={"ordering": ("preview_id", "item_id")},
        ),
        migrations.CreateModel(
            name="ProgrammeImportSourceBinding",
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
                    "source_system",
                    models.CharField(
                        max_length=80, validators=[_SOURCE_SYSTEM_VALIDATOR]
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[("call", "Call"), ("proposal", "Proposal")],
                        max_length=8,
                    ),
                ),
                (
                    "source_key",
                    models.CharField(
                        max_length=200, validators=[_SOURCE_KEY_VALIDATOR]
                    ),
                ),
                (
                    "source_digest",
                    models.CharField(max_length=64, validators=[_DIGEST_VALIDATOR]),
                ),
                (
                    "call",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="import_source_binding",
                        to="applications.programmecall",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_import_source_bindings_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "edition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_import_source_bindings",
                        to="events.eventedition",
                    ),
                ),
                (
                    "item",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="source_binding",
                        to="applications.programmeimportitem",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_import_source_bindings",
                        to="organizations.organization",
                    ),
                ),
                (
                    "proposal",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="import_source_binding",
                        to="applications.programmeproposal",
                    ),
                ),
            ],
            options={"ordering": ("edition_id", "source_system", "kind", "source_key")},
        ),
        migrations.CreateModel(
            name="ProgrammeImportCommandReceipt",
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
                    "aggregate_kind",
                    models.CharField(
                        choices=[
                            ("batch", "Batch"),
                            ("preview", "Preview"),
                            ("item", "Item"),
                        ],
                        max_length=8,
                    ),
                ),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("batch_staged", "Batch staged"),
                            ("batch_previewed", "Batch previewed"),
                            ("call_committed", "Call committed"),
                            ("proposal_claimed", "Proposal claimed"),
                            ("batch_discarded", "Batch discarded"),
                        ],
                        max_length=20,
                    ),
                ),
                ("retry_key", models.UUIDField()),
                (
                    "request_digest",
                    models.CharField(max_length=64, validators=[_DIGEST_VALIDATOR]),
                ),
                ("reason", models.CharField(blank=True, max_length=500)),
                ("correlation_id", models.UUIDField()),
                (
                    "source_channel",
                    models.CharField(
                        max_length=32, validators=[_SOURCE_CHANNEL_VALIDATOR]
                    ),
                ),
                (
                    "adopted_preview_digest",
                    models.CharField(
                        blank=True, max_length=64, validators=[_DIGEST_VALIDATOR]
                    ),
                ),
                (
                    "result_kind",
                    models.CharField(
                        choices=[
                            ("batch", "Batch"),
                            ("preview", "Preview"),
                            ("call_binding", "Call binding"),
                            ("proposal_binding", "Proposal binding"),
                            ("discard", "Discard"),
                        ],
                        max_length=20,
                    ),
                ),
                ("expected_version", models.PositiveBigIntegerField()),
                ("resulting_version", models.PositiveBigIntegerField()),
                (
                    "applied_command_count",
                    models.PositiveSmallIntegerField(default=0, editable=False),
                ),
                (
                    "actor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_import_command_receipts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "batch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="command_receipts",
                        to="applications.programmeimportbatch",
                    ),
                ),
                (
                    "edition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_import_command_receipts",
                        to="events.eventedition",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_import_command_receipts",
                        to="organizations.organization",
                    ),
                ),
                (
                    "item",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="command_receipts",
                        to="applications.programmeimportitem",
                    ),
                ),
                (
                    "preview_item_result",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="command_receipts",
                        to="applications.programmeimportpreviewitemresult",
                    ),
                ),
                (
                    "preview_revision",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="command_receipts",
                        to="applications.programmeimportpreviewrevision",
                    ),
                ),
                (
                    "source_binding",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="command_receipts",
                        to="applications.programmeimportsourcebinding",
                    ),
                ),
            ],
            options={"ordering": ("edition_id", "created_at", "id")},
        ),
        migrations.CreateModel(
            name="ProgrammeImportAppliedCommand",
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
                (
                    "edition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_import_applied_commands",
                        to="events.eventedition",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_import_applied_commands",
                        to="organizations.organization",
                    ),
                ),
                (
                    "programme_receipt",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="import_applied_command",
                        to="applications.programmecommandreceipt",
                    ),
                ),
                (
                    "import_receipt",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="applied_commands",
                        to="applications.programmeimportcommandreceipt",
                    ),
                ),
                (
                    "binding",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="applied_commands",
                        to="applications.programmeimportsourcebinding",
                    ),
                ),
            ],
            options={"ordering": ("import_receipt_id", "sequence", "id")},
        ),
        migrations.AddIndex(
            model_name="programmeimportbatch",
            index=models.Index(
                fields=["organization", "edition", "owner_department", "state"],
                name="app_prg_imp_batch_scope_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="programmeimportbatch",
            index=models.Index(
                fields=["state", "expires_at"], name="app_prg_imp_batch_expiry_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="programmeimportbatch",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("schema_version", 1),
                    ("item_count__gte", 1),
                    ("item_count__lte", 1000),
                    ("aggregate_version__gt", 0),
                    models.Q(("source_system", ""), _negated=True),
                    models.Q(("retention_policy_code", ""), _negated=True),
                    ("expires_at__gt", models.F("created_at")),
                ),
                name="applications_prg_imp_batch_bounds",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmeimportbatch",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("aggregate_version", 1),
                        ("discard_reason", ""),
                        ("discarded_at__isnull", True),
                        ("discarded_by__isnull", True),
                        ("state", "staged"),
                    ),
                    models.Q(
                        ("aggregate_version", 2),
                        ("discarded_at__isnull", False),
                        ("discarded_by__isnull", False),
                        ("state", "discarded"),
                        models.Q(("discard_reason", ""), _negated=True),
                    ),
                    _connector="OR",
                ),
                name="applications_prg_imp_batch_state",
            ),
        ),
        migrations.AddIndex(
            model_name="programmeimportitem",
            index=models.Index(
                fields=["organization", "edition", "batch", "state", "sequence"],
                name="app_prg_imp_item_scope_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="programmeimportitem",
            index=models.Index(
                fields=["organization", "edition", "kind", "source_key"],
                name="app_prg_imp_item_source_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmeimportitem",
            constraint=models.UniqueConstraint(
                fields=("batch", "sequence"),
                name="applications_prg_imp_item_sequence_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmeimportitem",
            constraint=models.UniqueConstraint(
                fields=("batch", "kind", "source_key"),
                name="applications_prg_imp_item_source_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmeimportitem",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("sequence__gt", 0),
                    ("payload_size_bytes__gt", 0),
                    models.Q(("source_key", ""), _negated=True),
                ),
                name="applications_prg_imp_item_bounds",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmeimportitem",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("dependency_source_key", ""),
                        ("dependency_source_system", ""),
                        ("kind", "call"),
                    ),
                    models.Q(
                        ("kind", "proposal"),
                        models.Q(("dependency_source_system", ""), _negated=True),
                        models.Q(("dependency_source_key", ""), _negated=True),
                    ),
                    _connector="OR",
                ),
                name="applications_prg_imp_item_dependency",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmeimportitem",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("aggregate_version", 1),
                        ("canonical_payload__isnull", False),
                        ("state", "staged"),
                    ),
                    models.Q(
                        ("aggregate_version", 2),
                        ("canonical_payload__isnull", True),
                        ("state__in", ("applied", "discarded")),
                    ),
                    _connector="OR",
                ),
                name="applications_prg_imp_item_state",
            ),
        ),
        migrations.AddIndex(
            model_name="programmeimportpreviewrevision",
            index=models.Index(
                fields=["organization", "edition", "batch", "revision_number"],
                name="app_prg_imp_preview_scope_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmeimportpreviewrevision",
            constraint=models.UniqueConstraint(
                fields=("batch", "revision_number"),
                name="applications_prg_imp_preview_revision_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmeimportpreviewrevision",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("revision_number__gt", 0),
                    ("source_batch_version", 1),
                    ("item_count__gte", 1),
                    ("item_count__lte", 1000),
                ),
                name="applications_prg_imp_preview_bounds",
            ),
        ),
        migrations.AddIndex(
            model_name="programmeimportpreviewitemresult",
            index=models.Index(
                fields=["organization", "edition", "preview", "status"],
                name="app_prg_imp_result_scope_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmeimportpreviewitemresult",
            constraint=models.UniqueConstraint(
                fields=("preview", "item"), name="applications_prg_imp_preview_item_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="programmeimportpreviewitemresult",
            constraint=models.CheckConstraint(
                condition=models.Q(("item_version__gt", 0)),
                name="applications_prg_imp_preview_item_version",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmeimportpreviewitemresult",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("dependency_digest", ""),
                        ("dependency_state__in", ("none", "missing")),
                        ("dependency_version__isnull", True),
                    ),
                    models.Q(
                        ("dependency_state__in", ("draft", "active", "retired")),
                        ("dependency_version__isnull", False),
                        models.Q(("dependency_digest", ""), _negated=True),
                    ),
                    _connector="OR",
                ),
                name="applications_prg_imp_preview_dependency",
            ),
        ),
        migrations.AddIndex(
            model_name="programmeimportsourcebinding",
            index=models.Index(
                fields=["organization", "edition", "kind", "created_at"],
                name="app_prg_imp_binding_scope_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmeimportsourcebinding",
            constraint=models.UniqueConstraint(
                fields=(
                    "organization",
                    "edition",
                    "source_system",
                    "kind",
                    "source_key",
                ),
                name="applications_prg_imp_binding_source_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmeimportsourcebinding",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        models.Q(
                            ("call__isnull", False),
                            ("kind", "call"),
                            ("proposal__isnull", True),
                        ),
                        models.Q(
                            ("call__isnull", True),
                            ("kind", "proposal"),
                            ("proposal__isnull", False),
                        ),
                        _connector="OR",
                    ),
                    models.Q(("source_system", ""), _negated=True),
                    models.Q(("source_key", ""), _negated=True),
                ),
                name="applications_prg_imp_binding_target",
            ),
        ),
        migrations.AddIndex(
            model_name="programmeimportcommandreceipt",
            index=models.Index(
                fields=["organization", "edition", "action", "created_at"],
                name="app_prg_imp_command_scope_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmeimportcommandreceipt",
            constraint=models.UniqueConstraint(
                fields=("edition", "actor", "retry_key"),
                name="applications_prg_imp_command_retry_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmeimportcommandreceipt",
            constraint=models.UniqueConstraint(
                condition=models.Q(("item__isnull", True)),
                fields=("batch", "aggregate_kind", "resulting_version"),
                name="applications_prg_imp_batch_result_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmeimportcommandreceipt",
            constraint=models.UniqueConstraint(
                condition=models.Q(("item__isnull", False)),
                fields=("item", "aggregate_kind", "resulting_version"),
                name="applications_prg_imp_item_result_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmeimportcommandreceipt",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("expected_version__gte", 0),
                    (
                        "resulting_version",
                        django.db.models.expressions.CombinedExpression(
                            models.F("expected_version"), "+", models.Value(1)
                        ),
                    ),
                    models.Q(("source_channel", ""), _negated=True),
                ),
                name="applications_prg_imp_command_version",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmeimportcommandreceipt",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("action__in", ("call_committed", "proposal_claimed")),
                        ("applied_command_count__gte", 1),
                        ("applied_command_count__lte", 1001),
                    ),
                    models.Q(
                        (
                            "action__in",
                            ("batch_staged", "batch_previewed", "batch_discarded"),
                        ),
                        ("applied_command_count", 0),
                    ),
                    _connector="OR",
                ),
                name="applications_prg_imp_command_applied_count",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmeimportcommandreceipt",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("aggregate_kind", "batch"), ("item__isnull", True)),
                    models.Q(("aggregate_kind", "preview"), ("item__isnull", True)),
                    models.Q(("aggregate_kind", "item"), ("item__isnull", False)),
                    _connector="OR",
                ),
                name="applications_prg_imp_command_aggregate",
            ),
        ),
        migrations.AddIndex(
            model_name="programmeimportappliedcommand",
            index=models.Index(
                fields=["organization", "edition", "binding", "sequence"],
                name="app_prg_imp_applied_scope_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmeimportappliedcommand",
            constraint=models.UniqueConstraint(
                fields=("import_receipt", "sequence"),
                name="applications_prg_imp_applied_sequence_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmeimportappliedcommand",
            constraint=models.CheckConstraint(
                condition=models.Q(("sequence__gt", 0)),
                name="applications_prg_imp_applied_sequence",
            ),
        ),
        migrations.RunSQL(migrations.RunSQL.noop, reverse_sql=REVERSE_PREFLIGHT_SQL),
    ]
