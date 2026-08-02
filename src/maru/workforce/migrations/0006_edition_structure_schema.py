"""Add the Page 9 edition-structure aggregate schema."""

from __future__ import annotations

from typing import ClassVar
from uuid import uuid4

import django.contrib.postgres.fields
import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import maru.core.validators


def refuse_populated_structure_schema_downgrade(
    apps: object,
    schema_editor: object,
) -> None:
    """Refuse to discard Page 9 aggregate evidence or Department metadata."""

    # The reverse operation drops immutable command evidence and narrows the
    # physical order column.  Hold write-blocking locks before the first
    # inspection so a concurrent writer cannot cross the downgrade fence.
    schema_editor.execute(  # type: ignore[attr-defined]
        """
        LOCK TABLE workforce_editionstructurecontrol,
                   workforce_editionstructurecommandreceipt,
                   workforce_department
          IN ACCESS EXCLUSIVE MODE
        """
    )
    alias = schema_editor.connection.alias  # type: ignore[attr-defined]
    structure_control = apps.get_model(  # type: ignore[attr-defined]
        "workforce", "EditionStructureControl"
    )
    command_receipt = apps.get_model(  # type: ignore[attr-defined]
        "workforce", "EditionStructureCommandReceipt"
    )
    department = apps.get_model("workforce", "Department")  # type: ignore[attr-defined]

    has_structure_data = (
        structure_control.objects.using(alias).exists()
        or command_receipt.objects.using(alias).exists()
        or department.objects.using(alias)
        .filter(
            models.Q(created_in_structure_version__isnull=False)
            | models.Q(last_changed_in_structure_version__isnull=False)
            | models.Q(retired_at__isnull=False)
            | models.Q(retired_by__isnull=False)
            | models.Q(retired_in_structure_version__isnull=False)
            # The previous PositiveSmallInteger column cannot represent the
            # upper half of Page 9's accepted 0..65535 display-order range.
            | models.Q(display_order__gt=32_767)
        )
        .exists()
    )
    if has_structure_data:
        raise RuntimeError(
            "Cannot reverse the edition-structure schema while aggregate evidence "
            "or non-representable Department structure data exists."
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0009_runtime_executable_function_contract"),
        ("workforce", "0005_runtime_executable_function_hardening"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.SeparateDatabaseAndState(
            # Keep the physical column named ``position`` so binaries from the
            # previous release remain compatible during migration-first
            # deployment.  Only the Django state adopts ``display_order``.
            database_operations=[],
            state_operations=[
                migrations.RenameField(
                    model_name="department",
                    old_name="position",
                    new_name="display_order",
                ),
                migrations.AlterField(
                    model_name="department",
                    name="display_order",
                    field=models.PositiveIntegerField(
                        db_column="position",
                        default=0,
                        validators=[
                            django.core.validators.MinValueValidator(0),
                            django.core.validators.MaxValueValidator(65_535),
                        ],
                    ),
                ),
            ],
        ),
        migrations.RunSQL(
            sql=(
                "ALTER TABLE workforce_department "
                "ALTER COLUMN position TYPE integer USING position::integer"
            ),
            reverse_sql=(
                "ALTER TABLE workforce_department "
                "ALTER COLUMN position TYPE smallint USING position::smallint"
            ),
        ),
        migrations.AddField(
            model_name="department",
            name="created_in_structure_version",
            field=models.PositiveBigIntegerField(
                blank=True,
                editable=False,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="department",
            name="last_changed_in_structure_version",
            field=models.PositiveBigIntegerField(
                blank=True,
                editable=False,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="department",
            name="retired_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="department",
            name="retired_by",
            field=models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="workforce_departments_retired",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="department",
            name="retired_in_structure_version",
            field=models.PositiveBigIntegerField(
                blank=True,
                editable=False,
                null=True,
            ),
        ),
        migrations.AlterModelOptions(
            name="department",
            options={"ordering": ("edition_id", "display_order", "name", "id")},
        ),
        migrations.AlterModelOptions(
            name="position",
            options={
                "ordering": (
                    "edition_id",
                    "department__display_order",
                    "title",
                    "id",
                )
            },
        ),
        migrations.AddConstraint(
            model_name="department",
            constraint=models.CheckConstraint(
                condition=models.Q(display_order__lte=65_535),
                name="workforce_department_display_order_bounded",
            ),
        ),
        migrations.AddConstraint(
            model_name="department",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(created_in_structure_version__isnull=True)
                    | models.Q(
                        created_in_structure_version__isnull=False,
                        last_changed_in_structure_version__isnull=False,
                        last_changed_in_structure_version__gte=models.F(
                            "created_in_structure_version"
                        ),
                    )
                ),
                name="workforce_department_structure_versions_consistent",
            ),
        ),
        migrations.AddConstraint(
            model_name="department",
            constraint=models.CheckConstraint(
                condition=(
                    (
                        models.Q(created_in_structure_version__isnull=True)
                        | models.Q(created_in_structure_version__gt=0)
                    )
                    & (
                        models.Q(last_changed_in_structure_version__isnull=True)
                        | models.Q(last_changed_in_structure_version__gt=0)
                    )
                    & (
                        models.Q(retired_in_structure_version__isnull=True)
                        | models.Q(retired_in_structure_version__gt=0)
                    )
                ),
                name="workforce_department_structure_versions_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="department",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        retired_at__isnull=True,
                        retired_by__isnull=True,
                        retired_in_structure_version__isnull=True,
                    )
                    | models.Q(
                        retired_at__isnull=False,
                        retired_by__isnull=False,
                        retired_in_structure_version__isnull=False,
                        last_changed_in_structure_version__isnull=False,
                        retired_in_structure_version=models.F(
                            "last_changed_in_structure_version"
                        ),
                    )
                ),
                name="workforce_department_retirement_complete",
            ),
        ),
        migrations.CreateModel(
            name="EditionStructureControl",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "origin",
                    models.CharField(
                        choices=[
                            ("legacy_existing", "Legacy existing"),
                            ("manual", "Manual"),
                            ("builtin_template", "Built-in template"),
                        ],
                        max_length=24,
                    ),
                ),
                ("aggregate_version", models.PositiveBigIntegerField()),
                (
                    "edition",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workforce_structure_control",
                        to="events.eventedition",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workforce_structure_controls",
                        to="organizations.organization",
                    ),
                ),
            ],
            options={
                "ordering": ("organization_id", "edition_id"),
                "indexes": [
                    models.Index(
                        fields=["organization", "edition"],
                        name="workforce_structure_scope_idx",
                    )
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(aggregate_version__gt=0),
                        name="workforce_structure_version_positive",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="EditionStructureCommandReceipt",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("template_applied", "Template applied"),
                            ("department_created", "Department created"),
                            ("department_updated", "Department updated"),
                            ("department_retired", "Department retired"),
                            ("department_deleted", "Department deleted"),
                        ],
                        max_length=24,
                    ),
                ),
                ("resulting_version", models.PositiveBigIntegerField()),
                ("reason", models.CharField(max_length=240)),
                ("correlation_id", models.UUIDField()),
                ("source_channel", models.CharField(max_length=32)),
                (
                    "changed_fields",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.CharField(max_length=80),
                        default=list,
                        size=16,
                    ),
                ),
                (
                    "affected_department_ids",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.UUIDField(),
                        default=list,
                        size=256,
                    ),
                ),
                ("retry_key", models.UUIDField(blank=True, null=True)),
                (
                    "request_digest",
                    models.CharField(
                        blank=True,
                        max_length=64,
                        validators=[
                            django.core.validators.RegexValidator(
                                code="invalid_structure_digest",
                                message="Use a lowercase SHA-256 digest.",
                                regex="^[0-9a-f]{64}$",
                            )
                        ],
                    ),
                ),
                (
                    "template_code",
                    models.SlugField(
                        blank=True,
                        max_length=80,
                        validators=[maru.core.validators.validate_lowercase_slug],
                    ),
                ),
                (
                    "template_version",
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                (
                    "template_digest",
                    models.CharField(
                        blank=True,
                        max_length=64,
                        validators=[
                            django.core.validators.RegexValidator(
                                code="invalid_structure_digest",
                                message="Use a lowercase SHA-256 digest.",
                                regex="^[0-9a-f]{64}$",
                            )
                        ],
                    ),
                ),
                (
                    "deleted_name_snapshot",
                    models.CharField(blank=True, max_length=160),
                ),
                (
                    "actor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workforce_structure_commands_acted",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "edition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workforce_structure_command_receipts",
                        to="events.eventedition",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workforce_structure_command_receipts",
                        to="organizations.organization",
                    ),
                ),
                (
                    "structure",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="command_receipts",
                        to="workforce.editionstructurecontrol",
                    ),
                ),
            ],
            options={
                "ordering": ("edition_id", "resulting_version", "id"),
                "indexes": [
                    models.Index(
                        fields=["organization", "edition", "resulting_version"],
                        name="wrk_receipt_scope_ver_idx",
                    ),
                    models.Index(
                        fields=["edition", "action", "created_at"],
                        name="wrk_receipt_action_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("structure", "resulting_version"),
                        name="workforce_structure_receipt_version_unique",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(retry_key__isnull=False),
                        fields=("edition", "actor", "retry_key"),
                        name="workforce_structure_retry_key_unique",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(resulting_version__gt=0),
                        name="workforce_structure_receipt_version_positive",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(changed_fields__len__lte=16),
                        name="workforce_structure_changed_fields_bounded",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(affected_department_ids__len__lte=256),
                        name="workforce_structure_affected_ids_bounded",
                    ),
                    models.CheckConstraint(
                        condition=(
                            ~models.Q(reason="")
                            & ~models.Q(source_channel="")
                        ),
                        name="workforce_structure_receipt_evidence_nonblank",
                    ),
                ],
            },
        ),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_populated_structure_schema_downgrade,
        ),
    ]
