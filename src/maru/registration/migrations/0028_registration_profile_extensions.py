from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid

import maru.core.validators


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0005_editionclosuremanifest_editionreadinessgate"),
        ("registration", "0027_registration_staff_submission_reason_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RegistrationProfileExtensionField",
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
                    "key",
                    models.SlugField(
                        max_length=80,
                        validators=[maru.core.validators.validate_lowercase_slug],
                    ),
                ),
                ("version", models.PositiveIntegerField(default=1)),
                ("label", models.CharField(max_length=200)),
                ("help_text", models.TextField(blank=True)),
                (
                    "field_type",
                    models.CharField(
                        choices=[
                            ("short_text", "Short text"),
                            ("long_text", "Long text"),
                            ("boolean", "Yes or no"),
                            ("single_choice", "Single choice"),
                            ("multiple_choice", "Multiple choice"),
                            ("integer", "Whole number"),
                        ],
                        max_length=24,
                    ),
                ),
                ("options", models.JSONField(blank=True, default=list)),
                ("purpose", models.CharField(max_length=240)),
                (
                    "classification",
                    models.CharField(
                        choices=[("C1", "Internal"), ("C2", "Personal")],
                        default="C2",
                        max_length=2,
                    ),
                ),
                ("attendee_visible", models.BooleanField(default=True)),
                (
                    "writer_policy",
                    models.CharField(
                        choices=[
                            ("attendee", "Attendee"),
                            ("registration_staff", "Registration staff"),
                            ("attendee_and_staff", "Attendee and registration staff"),
                        ],
                        default="attendee_and_staff",
                        max_length=30,
                    ),
                ),
                ("required", models.BooleanField(default=False)),
                ("position", models.PositiveIntegerField(default=0)),
                (
                    "review_status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending review"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("active", "Active"),
                            ("retired", "Retired"),
                        ],
                        default="draft",
                        max_length=16,
                    ),
                ),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                (
                    "approved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="registration_profile_extension_fields_approved",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="registration_profile_extension_fields_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "edition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="registration_profile_extension_fields",
                        to="events.eventedition",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="registration_profile_extension_fields",
                        to="organizations.organization",
                    ),
                ),
                (
                    "source_prior_edition",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="profile_extension_field_copies",
                        to="events.eventedition",
                    ),
                ),
                (
                    "source_template",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="profile_extension_field_copies",
                        to="registration.registrationtemplate",
                    ),
                ),
                (
                    "supersedes",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="superseded_by",
                        to="registration.registrationprofileextensionfield",
                    ),
                ),
            ],
            options={
                "ordering": ("edition_id", "position", "key", "-version", "id"),
            },
        ),
        migrations.CreateModel(
            name="RegistrationProfileExtensionValueRevision",
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
                ("organization_id", models.UUIDField()),
                ("edition_id", models.UUIDField()),
                (
                    "field_key",
                    models.SlugField(
                        max_length=80,
                        validators=[maru.core.validators.validate_lowercase_slug],
                    ),
                ),
                ("sequence", models.PositiveIntegerField()),
                ("value", models.JSONField()),
                ("source_channel", models.CharField(max_length=40)),
                ("reason", models.CharField(blank=True, max_length=500)),
                (
                    "actor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="registration_profile_extension_value_revisions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "field",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="value_revisions",
                        to="registration.registrationprofileextensionfield",
                    ),
                ),
                (
                    "registration",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="profile_extension_value_revisions",
                        to="registration.registration",
                    ),
                ),
            ],
            options={
                "ordering": ("registration_id", "field_key", "sequence", "id"),
            },
        ),
        migrations.AddConstraint(
            model_name="registrationprofileextensionfield",
            constraint=models.UniqueConstraint(
                fields=("edition", "key", "version"),
                name="registration_profile_extension_field_version_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="registrationprofileextensionfield",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status", "active")),
                fields=("edition", "key"),
                name="registration_one_active_profile_extension_field",
            ),
        ),
        migrations.AddConstraint(
            model_name="registrationprofileextensionvaluerevision",
            constraint=models.UniqueConstraint(
                fields=("registration", "field_key", "sequence"),
                name="registration_profile_extension_value_revision_unique",
            ),
        ),
    ]
