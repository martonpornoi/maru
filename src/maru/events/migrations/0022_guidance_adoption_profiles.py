"""Retain the exact Guidance human decision graph without granting authority."""

import uuid
from typing import ClassVar

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("events", "0021_announcements_setup_downgrade_fence"),
        ("announcements", "0003_downgrade_fence"),
        ("authorization", "0044_workspace_operator_lineage"),
        ("organizations", "0016_workspace_representation"),
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
                    ("guidance_only", "Guides only"),
                    ("announcements_guidance", "Announcements and Guides"),
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
                )
                | models.Q(
                    adoption_profile_code="guidance_only", adoption_profile_version=1
                )
                | models.Q(
                    adoption_profile_code="announcements_guidance",
                    adoption_profile_version=1,
                ),
                name="edition_adoption_profile_supported",
            ),
        ),
        migrations.AddField(
            model_name="eventedition",
            name="adoption_revision",
            field=models.PositiveBigIntegerField(default=0, editable=False),
        ),
        migrations.CreateModel(
            name="GuidanceAdoptionSetupReceipt",
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
                    "edition",
                    models.OneToOneField(
                        "events.EventEdition",
                        on_delete=models.PROTECT,
                        related_name="guidance_setup_receipt",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        "organizations.Organization",
                        on_delete=models.PROTECT,
                        related_name="guidance_setup_receipts",
                    ),
                ),
                (
                    "series",
                    models.ForeignKey(
                        "organizations.ConventionSeries",
                        on_delete=models.PROTECT,
                        related_name="guidance_setup_receipts",
                    ),
                ),
                (
                    "representation",
                    models.ForeignKey(
                        "organizations.OrganizationRepresentation",
                        on_delete=models.PROTECT,
                        related_name="guidance_setup_receipts",
                    ),
                ),
                (
                    "actor",
                    models.ForeignKey(
                        settings.AUTH_USER_MODEL,
                        on_delete=models.PROTECT,
                        related_name="guidance_setup_receipts",
                    ),
                ),
                (
                    "source_audit",
                    models.OneToOneField(
                        "audit.AuditEvent",
                        on_delete=models.PROTECT,
                        related_name="guidance_setup_receipt",
                    ),
                ),
                (
                    "edition_creation",
                    models.OneToOneField(
                        "events.EditionCreationReceipt",
                        on_delete=models.PROTECT,
                        related_name="guidance_setup_receipt",
                    ),
                ),
                ("idempotency_key", models.UUIDField()),
                (
                    "request_digest",
                    models.CharField(
                        max_length=64,
                        validators=[
                            RegexValidator("^[0-9a-f]{64}\\Z", "Use a SHA-256 digest.")
                        ],
                    ),
                ),
                (
                    "mode",
                    models.CharField(
                        max_length=40,
                        choices=(
                            (
                                "new_foundation",
                                "Create organization, series and edition",
                            ),
                            ("existing_organization", "Reuse an organization"),
                            ("existing_series", "Reuse an organization and series"),
                        ),
                    ),
                ),
                ("foundation_fingerprint", models.CharField(max_length=64, blank=True)),
                ("representation_version", models.PositiveBigIntegerField()),
                ("reason", models.CharField(max_length=240)),
                ("organization_slug", models.SlugField(max_length=80)),
                ("correlation_id", models.UUIDField()),
                ("source_channel", models.CharField(max_length=32)),
            ],
            options={
                "ordering": ("created_at", "id"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("actor", "idempotency_key"),
                        name="guidance_setup_actor_key_unique",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(representation_version__gte=1),
                        name="guidance_setup_representation_version_positive",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            mode="new_foundation", foundation_fingerprint=""
                        )
                        | models.Q(
                            mode__in=("existing_organization", "existing_series"),
                            foundation_fingerprint__regex="^[0-9a-f]{64}$",
                        ),
                        name="guidance_setup_mode_source_shape",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(request_digest__regex="^[0-9a-f]{64}$"),
                        name="guidance_setup_request_digest_shape",
                    ),
                    models.CheckConstraint(
                        condition=~models.Q(reason=""),
                        name="guidance_setup_reason_nonempty",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="GuidanceActivationRequest",
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
                    "organization",
                    models.ForeignKey(
                        "organizations.Organization", on_delete=models.PROTECT
                    ),
                ),
                (
                    "edition",
                    models.ForeignKey("events.EventEdition", on_delete=models.PROTECT),
                ),
                (
                    "representation",
                    models.ForeignKey(
                        "organizations.OrganizationRepresentation",
                        on_delete=models.PROTECT,
                    ),
                ),
                (
                    "proposed_by",
                    models.ForeignKey(
                        settings.AUTH_USER_MODEL,
                        on_delete=models.PROTECT,
                        related_name="guidance_activation_requests_proposed",
                    ),
                ),
                (
                    "operator_a",
                    models.ForeignKey(
                        settings.AUTH_USER_MODEL,
                        on_delete=models.PROTECT,
                        related_name="guidance_activation_requests_as_a",
                    ),
                ),
                (
                    "operator_b",
                    models.ForeignKey(
                        settings.AUTH_USER_MODEL,
                        on_delete=models.PROTECT,
                        related_name="guidance_activation_requests_as_b",
                    ),
                ),
                (
                    "source_audit",
                    models.OneToOneField("audit.AuditEvent", on_delete=models.PROTECT),
                ),
                ("idempotency_key", models.UUIDField()),
                ("request_digest", models.CharField(max_length=64)),
                ("expected_edition_version", models.PositiveBigIntegerField()),
                ("expected_adoption_revision", models.PositiveBigIntegerField()),
                ("source_profile_code", models.CharField(max_length=40)),
                ("source_profile_version", models.PositiveIntegerField()),
                ("target_profile_code", models.CharField(max_length=40)),
                ("target_profile_version", models.PositiveIntegerField()),
                ("source_manifest_digest", models.CharField(max_length=64)),
                ("target_manifest_digest", models.CharField(max_length=64)),
                ("representation_version", models.PositiveBigIntegerField()),
                (
                    "purpose",
                    models.CharField(
                        max_length=16,
                        choices=(
                            ("initial", "Start Guidance"),
                            ("recovery", "Restore Guidance responsibility"),
                        ),
                    ),
                ),
                ("reason", models.CharField(max_length=240)),
                ("expires_at", models.DateTimeField()),
                ("correlation_id", models.UUIDField()),
            ],
            options={
                "ordering": ("created_at", "id"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("proposed_by", "idempotency_key"),
                        name="guidance_activation_request_key_unique",
                    ),
                    models.CheckConstraint(
                        condition=~models.Q(operator_a=models.F("operator_b")),
                        name="guidance_activation_distinct_operators",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(request_digest__regex="^[0-9a-f]{64}$"),
                        name="guidance_activation_request_digest",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(purpose__in=("initial", "recovery")),
                        name="guidance_activation_request_purpose",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(expected_edition_version__gte=1),
                        name="guidance_activation_source_version",
                    ),
                    models.CheckConstraint(
                        condition=~models.Q(reason=""),
                        name="guidance_activation_request_reason",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="GuidanceActivationDecision",
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
                    "request",
                    models.ForeignKey(
                        "events.guidanceactivationrequest",
                        on_delete=models.PROTECT,
                        related_name="decisions",
                    ),
                ),
                (
                    "actor",
                    models.ForeignKey(
                        settings.AUTH_USER_MODEL, on_delete=models.PROTECT
                    ),
                ),
                ("accepted", models.BooleanField()),
                ("request_digest", models.CharField(max_length=64)),
                (
                    "source_audit",
                    models.OneToOneField("audit.AuditEvent", on_delete=models.PROTECT),
                ),
                ("correlation_id", models.UUIDField()),
            ],
            options={
                "ordering": ("created_at", "id"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("request", "actor"),
                        name="guidance_activation_one_answer",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="GuidanceActivationReceipt",
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
                    "request",
                    models.OneToOneField(
                        "events.guidanceactivationrequest",
                        on_delete=models.PROTECT,
                        related_name="receipt",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        "organizations.Organization", on_delete=models.PROTECT
                    ),
                ),
                (
                    "edition",
                    models.ForeignKey("events.EventEdition", on_delete=models.PROTECT),
                ),
                (
                    "applied_by",
                    models.ForeignKey(
                        settings.AUTH_USER_MODEL, on_delete=models.PROTECT
                    ),
                ),
                (
                    "source_audit",
                    models.OneToOneField("audit.AuditEvent", on_delete=models.PROTECT),
                ),
                ("result_edition_version", models.PositiveBigIntegerField()),
                ("result_adoption_revision", models.PositiveBigIntegerField()),
                ("correlation_id", models.UUIDField()),
            ],
            options={
                "ordering": ("created_at", "id"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("edition", "result_adoption_revision"),
                        name="guidance_activation_revision_unique",
                    )
                ],
            },
        ),
    ]
