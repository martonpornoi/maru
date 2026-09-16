"""Install dormant retained setup evidence without adding an adoption profile."""

import uuid
from typing import Any, ClassVar

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def refuse_used_setup_receipt_downgrade(apps: Any, schema_editor: Any) -> None:
    """Serialize the unused downgrade check and retain any completed setup."""
    schema_editor.execute(
        "LOCK TABLE public.events_programmeadoptionsetupreceipt "
        "IN ACCESS EXCLUSIVE MODE"
    )
    if apps.get_model("events", "ProgrammeAdoptionSetupReceipt").objects.exists():
        raise RuntimeError(
            "Programme setup evidence exists; retain it and fix forward."
        )


class Migration(migrations.Migration):
    """Add immutable receipt storage, not setup permission or a current writer."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("audit", "0009_native_mutation_witness"),
        ("events", "0011_release_dependency_mutations"),
        ("organizations", "0014_purpose_bounded_representation"),
        ("workforce", "0024_published_host_obligation_guard"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations: ClassVar[list[object]] = [
        migrations.CreateModel(
            name="ProgrammeAdoptionSetupReceipt",
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
                ("idempotency_key", models.UUIDField()),
                (
                    "request_digest",
                    models.CharField(
                        max_length=64,
                        validators=[
                            django.core.validators.RegexValidator(
                                r"^[0-9a-f]{64}\Z", "Use a SHA-256 digest."
                            )
                        ],
                    ),
                ),
                (
                    "mode",
                    models.CharField(
                        choices=[
                            (
                                "new_foundation",
                                "Create organization, series and edition",
                            ),
                            ("existing_organization", "Reuse an organization"),
                            ("existing_series", "Reuse an organization and series"),
                        ],
                        max_length=40,
                    ),
                ),
                ("foundation_fingerprint", models.CharField(blank=True, max_length=64)),
                ("representation_version", models.PositiveBigIntegerField()),
                ("reason", models.CharField(max_length=240)),
                (
                    "actor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_setup_receipts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "department",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_setup_receipts",
                        to="workforce.department",
                    ),
                ),
                (
                    "department_creation",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_setup_receipt",
                        to="workforce.editionstructurecommandreceipt",
                    ),
                ),
                (
                    "edition",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_setup_receipt",
                        to="events.eventedition",
                    ),
                ),
                (
                    "edition_creation",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_setup_receipt",
                        to="events.editioncreationreceipt",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_setup_receipts",
                        to="organizations.organization",
                    ),
                ),
                (
                    "representation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_setup_receipts",
                        to="organizations.organizationrepresentation",
                    ),
                ),
                (
                    "series",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_setup_receipts",
                        to="organizations.conventionseries",
                    ),
                ),
                (
                    "source_audit",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_setup_receipt",
                        to="audit.auditevent",
                    ),
                ),
            ],
            options={
                "ordering": ("created_at", "id"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("actor", "idempotency_key"),
                        name="programme_setup_actor_key_unique",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(representation_version__gte=1),
                        name="programme_setup_representation_version_positive",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(mode="new_foundation", foundation_fingerprint="")
                            | models.Q(
                                mode__in=("existing_organization", "existing_series"),
                                foundation_fingerprint__regex=r"^[0-9a-f]{64}$",
                            )
                        ),
                        name="programme_setup_mode_source_shape",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(request_digest__regex=r"^[0-9a-f]{64}$"),
                        name="programme_setup_request_digest_shape",
                    ),
                    models.CheckConstraint(
                        condition=~models.Q(reason=""),
                        name="programme_setup_reason_nonempty",
                    ),
                ],
            },
        ),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_used_setup_receipt_downgrade
        ),
    ]
