"""Install dormant Programme role intent/decision storage without granting access."""

import uuid
from typing import Any, ClassVar

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def refuse_used_programme_role_downgrade(apps: Any, schema_editor: Any) -> None:
    """Lock both relations before permitting unused-only removal."""
    schema_editor.execute(
        "LOCK TABLE public.authorization_programmerolerequest, "
        "public.authorization_programmeroledecisionrecord IN ACCESS EXCLUSIVE MODE"
    )
    if (
        apps.get_model("authorization", "ProgrammeRoleRequest").objects.exists()
        or apps.get_model(
            "authorization", "ProgrammeRoleDecisionRecord"
        ).objects.exists()
    ):
        raise RuntimeError("Programme role evidence exists; retain it and fix forward.")


class Migration(migrations.Migration):
    """Retain exact proposed scope and a single separately attributable outcome."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("audit", "0009_native_mutation_witness"),
        ("authorization", "0031_programme_change_communication_capabilities"),
        ("events", "0014_programme_setup_downgrade_fence"),
        ("organizations", "0014_purpose_bounded_representation"),
        ("workforce", "0024_published_host_obligation_guard"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations: ClassVar[list[object]] = [
        migrations.CreateModel(
            name="ProgrammeRoleRequest",
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
                                "^[0-9a-f]{64}\\Z", "Use a SHA-256 digest."
                            )
                        ],
                    ),
                ),
                ("reason", models.CharField(max_length=240)),
                ("correlation_id", models.UUIDField()),
                ("source_channel", models.CharField(max_length=32)),
                (
                    "scope_level",
                    models.CharField(
                        choices=[
                            ("organization", "Organization"),
                            ("edition", "Edition"),
                            ("department", "Department"),
                            ("resource", "Resource"),
                        ],
                        max_length=16,
                    ),
                ),
                ("recipe_code", models.CharField(max_length=64)),
                ("recipe_version", models.PositiveIntegerField()),
                (
                    "recipe_digest",
                    models.CharField(
                        max_length=64,
                        validators=[
                            django.core.validators.RegexValidator(
                                "^[0-9a-f]{64}\\Z", "Use a SHA-256 digest."
                            )
                        ],
                    ),
                ),
                ("requested_at", models.DateTimeField()),
                ("approval_deadline", models.DateTimeField()),
                ("not_before", models.DateTimeField(blank=True, null=True)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                (
                    "approver",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="assigned_programme_role_requests",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "author",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="authored_programme_role_requests",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "department",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="workforce.department",
                    ),
                ),
                (
                    "edition",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="targeted_programme_role_requests",
                        to="events.eventedition",
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
                    "programme_edition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_role_requests",
                        to="events.eventedition",
                    ),
                ),
                (
                    "recipient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="recipient_programme_role_requests",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "resource_binding",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="authorization.scopedresourcebinding",
                    ),
                ),
                (
                    "source_audit",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(class)s_evidence",
                        to="audit.auditevent",
                    ),
                ),
            ],
            options={
                "ordering": ("requested_at", "id"),
            },
        ),
        migrations.CreateModel(
            name="ProgrammeRoleDecisionRecord",
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
                                "^[0-9a-f]{64}\\Z", "Use a SHA-256 digest."
                            )
                        ],
                    ),
                ),
                ("reason", models.CharField(max_length=240)),
                ("correlation_id", models.UUIDField()),
                ("source_channel", models.CharField(max_length=32)),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("approve", "Approve"),
                            ("decline", "Decline"),
                            ("cancel", "Cancel"),
                        ],
                        max_length=16,
                    ),
                ),
                ("decided_at", models.DateTimeField()),
                (
                    "actor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_role_decisions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "role_assignment",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_approval_decision",
                        to="authorization.roleassignment",
                    ),
                ),
                (
                    "role_bundle",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="authorization.rolebundle",
                    ),
                ),
                (
                    "source_audit",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(class)s_evidence",
                        to="audit.auditevent",
                    ),
                ),
                (
                    "request",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="decision",
                        to="authorization.programmerolerequest",
                    ),
                ),
            ],
            options={
                "ordering": ("decided_at", "id"),
            },
        ),
        migrations.AddConstraint(
            model_name="programmerolerequest",
            constraint=models.UniqueConstraint(
                fields=("author", "idempotency_key"),
                name="programme_role_request_author_key",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmerolerequest",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("approver", models.F("author")), _negated=True),
                    models.Q(("approver", models.F("recipient")), _negated=True),
                ),
                name="programme_role_request_independent",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmerolerequest",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("department__isnull", True),
                        ("edition__isnull", True),
                        ("resource_binding__isnull", True),
                        ("scope_level", "organization"),
                    ),
                    models.Q(
                        ("department__isnull", True),
                        ("edition__isnull", False),
                        ("resource_binding__isnull", True),
                        ("scope_level", "edition"),
                    ),
                    models.Q(
                        ("department__isnull", False),
                        ("edition__isnull", False),
                        ("resource_binding__isnull", True),
                        ("scope_level", "department"),
                    ),
                    models.Q(
                        ("department__isnull", False),
                        ("edition__isnull", False),
                        ("resource_binding__isnull", False),
                        ("scope_level", "resource"),
                    ),
                    _connector="OR",
                ),
                name="programme_role_request_scope_shape",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmerolerequest",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("edition__isnull", True),
                    ("edition", models.F("programme_edition")),
                    _connector="OR",
                ),
                name="programme_role_request_context",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmerolerequest",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("expires_at__isnull", True),
                    ("not_before__isnull", True),
                    ("expires_at__gt", models.F("not_before")),
                    _connector="OR",
                ),
                name="programme_role_request_interval",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmerolerequest",
            constraint=models.CheckConstraint(
                condition=models.Q(("approval_deadline__gt", models.F("requested_at"))),
                name="programme_role_request_deadline",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmerolerequest",
            constraint=models.CheckConstraint(
                condition=models.Q(("recipe_version__gte", 1)),
                name="programme_role_recipe_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmeroledecisionrecord",
            constraint=models.UniqueConstraint(
                fields=("actor", "idempotency_key"),
                name="programme_role_decision_actor_key",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmeroledecisionrecord",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("action", "approve"),
                        ("role_assignment__isnull", False),
                        ("role_bundle__isnull", False),
                    ),
                    models.Q(
                        ("action__in", ("decline", "cancel")),
                        ("role_assignment__isnull", True),
                        ("role_bundle__isnull", True),
                    ),
                    _connector="OR",
                ),
                name="programme_role_decision_output",
            ),
        ),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_used_programme_role_downgrade
        ),
    ]
