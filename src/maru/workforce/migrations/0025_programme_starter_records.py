"""Retain exact Programme Volunteer starter intent and one terminal decision."""

import uuid
from typing import ClassVar

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Add dormant approval evidence without creating templates or granting access."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("audit", "0009_native_mutation_witness"),
        ("authorization", "0036_programme_room_operations_recipe"),
        ("events", "0014_programme_setup_downgrade_fence"),
        ("organizations", "0014_purpose_bounded_representation"),
        ("workforce", "0024_published_host_obligation_guard"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations: ClassVar[list[object]] = [
        migrations.CreateModel(
            name="ProgrammeStarterRequest",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("idempotency_key", models.UUIDField()),
                ("request_digest", models.CharField(max_length=64, validators=[django.core.validators.RegexValidator(r"^[0-9a-f]{64}\Z", "Use a SHA-256 digest.")])),
                ("reason", models.CharField(max_length=240)),
                ("correlation_id", models.UUIDField()),
                ("source_channel", models.CharField(max_length=32)),
                ("definition_code", models.CharField(max_length=80)),
                ("definition_version", models.PositiveIntegerField()),
                ("definition_digest", models.CharField(max_length=64, validators=[django.core.validators.RegexValidator(r"^[0-9a-f]{64}\Z", "Use a SHA-256 digest.")])),
                ("requested_at", models.DateTimeField()),
                ("approval_deadline", models.DateTimeField()),
                ("approver", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="assigned_programme_starter_requests", to=settings.AUTH_USER_MODEL)),
                ("author", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="authored_programme_starter_requests", to=settings.AUTH_USER_MODEL)),
                ("edition", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="events.eventedition")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="organizations.organization")),
                ("series", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="organizations.conventionseries")),
                ("source_audit", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="%(class)s_evidence", to="audit.auditevent")),
            ],
            options={"ordering": ("requested_at", "id")},
        ),
        migrations.CreateModel(
            name="ProgrammeStarterDecision",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("idempotency_key", models.UUIDField()),
                ("request_digest", models.CharField(max_length=64, validators=[django.core.validators.RegexValidator(r"^[0-9a-f]{64}\Z", "Use a SHA-256 digest.")])),
                ("reason", models.CharField(max_length=240)),
                ("correlation_id", models.UUIDField()),
                ("source_channel", models.CharField(max_length=32)),
                ("action", models.CharField(choices=[("approve", "Approve"), ("decline", "Decline"), ("cancel", "Cancel")], max_length=16)),
                ("decided_at", models.DateTimeField()),
                ("created_output", models.BooleanField(default=False)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="programme_starter_decisions", to=settings.AUTH_USER_MODEL)),
                ("role_bundle", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="authorization.rolebundle")),
                ("source_audit", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="%(class)s_evidence", to="audit.auditevent")),
                ("template", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="workforce.positiontemplate")),
                ("request", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="decision", to="workforce.programmestarterrequest")),
            ],
            options={"ordering": ("decided_at", "id")},
        ),
        migrations.AddConstraint(
            model_name="programmestarterrequest",
            constraint=models.UniqueConstraint(fields=("author", "idempotency_key"), name="wrk_starter_request_author_key"),
        ),
        migrations.AddConstraint(
            model_name="programmestarterrequest",
            constraint=models.CheckConstraint(condition=~models.Q(author=models.F("approver")), name="wrk_starter_request_independent"),
        ),
        migrations.AddConstraint(
            model_name="programmestarterrequest",
            constraint=models.CheckConstraint(condition=models.Q(definition_code="workforce-volunteer", definition_version=1), name="wrk_starter_request_definition"),
        ),
        migrations.AddConstraint(
            model_name="programmestarterrequest",
            constraint=models.CheckConstraint(condition=models.Q(approval_deadline__gt=models.F("requested_at")), name="wrk_starter_request_deadline"),
        ),
        migrations.AddConstraint(
            model_name="programmestarterdecision",
            constraint=models.UniqueConstraint(fields=("actor", "idempotency_key"), name="wrk_starter_decision_actor_key"),
        ),
        migrations.AddConstraint(
            model_name="programmestarterdecision",
            constraint=models.CheckConstraint(
                condition=models.Q(action="approve", role_bundle__isnull=False, template__isnull=False)
                | models.Q(action__in=("decline", "cancel"), created_output=False, role_bundle__isnull=True, template__isnull=True),
                name="wrk_starter_decision_output",
            ),
        ),
    ]
