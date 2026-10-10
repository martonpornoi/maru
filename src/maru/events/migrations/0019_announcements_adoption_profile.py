"""Add persisted Announcements profile choices, constraint and setup receipts."""

import uuid
from typing import ClassVar

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Support announcements_only@1 and retain immutable setup receipt storage."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("audit", "0009_native_mutation_witness"),
        ("events", "0018_programme_retained_recovery_fence"),
        ("organizations", "0015_announcements_representation"),
        ("authorization", "0042_announcements_operator_lineage"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RemoveConstraint(
            model_name="eventedition", name="edition_adoption_profile_supported"
        ),
        migrations.AlterField(
            model_name="eventedition",
            name="adoption_profile_code",
            field=models.CharField(
                choices=[
                    ("full_convention", "Full convention"),
                    ("workforce_only", "Workforce only"),
                    ("announcements_only", "Announcements only"),
                ],
                db_default="full_convention",
                default="full_convention",
                editable=False,
                max_length=40,
            ),
        ),
        migrations.AddConstraint(
            model_name="eventedition",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    adoption_profile_code="full_convention", adoption_profile_version=1
                )
                | models.Q(
                    adoption_profile_code="workforce_only", adoption_profile_version=1
                )
                | models.Q(
                    adoption_profile_code="announcements_only",
                    adoption_profile_version=1,
                ),
                name="edition_adoption_profile_supported",
            ),
        ),
        migrations.CreateModel(
            name="AnnouncementsAdoptionSetupReceipt",
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
                ("organization_slug", models.SlugField(max_length=80)),
                ("correlation_id", models.UUIDField()),
                ("source_channel", models.CharField(max_length=32)),
                (
                    "actor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="announcements_setup_receipts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "edition",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="announcements_setup_receipt",
                        to="events.eventedition",
                    ),
                ),
                (
                    "edition_creation",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="announcements_setup_receipt",
                        to="events.editioncreationreceipt",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="announcements_setup_receipts",
                        to="organizations.organization",
                    ),
                ),
                (
                    "representation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="announcements_setup_receipts",
                        to="organizations.organizationrepresentation",
                    ),
                ),
                (
                    "series",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="announcements_setup_receipts",
                        to="organizations.conventionseries",
                    ),
                ),
                (
                    "source_audit",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="announcements_setup_receipt",
                        to="audit.auditevent",
                    ),
                ),
            ],
            options={
                "ordering": ("created_at", "id"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("actor", "idempotency_key"),
                        name="announcements_setup_actor_key_unique",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(representation_version__gte=1),
                        name="announcements_setup_representation_version_positive",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(mode="new_foundation", foundation_fingerprint="")
                            | models.Q(
                                mode__in=("existing_organization", "existing_series"),
                                foundation_fingerprint__regex=r"^[0-9a-f]{64}$",
                            )
                        ),
                        name="announcements_setup_mode_source_shape",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(request_digest__regex=r"^[0-9a-f]{64}$"),
                        name="announcements_setup_request_digest_shape",
                    ),
                    models.CheckConstraint(
                        condition=~models.Q(reason=""),
                        name="announcements_setup_reason_nonempty",
                    ),
                ],
            },
        ),
    ]
