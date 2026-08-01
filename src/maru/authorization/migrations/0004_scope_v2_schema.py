"""Install the additive ADR 0041 authorization scope-v2 schema.

Existing grants and assignments deliberately keep their organization- or
edition-wide meaning: both new references are nullable and this migration does
not infer narrower authority. Cross-table scope agreement, position binding
backfill, delegation containment, and the downgrade fence are activated only
by the ordered workforce and authorization migrations that follow this schema
phase. The binding identity itself is immutable from the moment it exists.
"""

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


RESOURCE_BINDING_IMMUTABILITY_SQL = """
CREATE FUNCTION maru_prevent_scoped_resource_binding_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'scoped resource bindings are immutable'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER authorization_scoped_resource_binding_immutable
BEFORE UPDATE OR DELETE
ON authorization_scopedresourcebinding
FOR EACH ROW EXECUTE FUNCTION maru_prevent_scoped_resource_binding_mutation();
"""

REVERSE_RESOURCE_BINDING_IMMUTABILITY_SQL = """
DROP TRIGGER IF EXISTS authorization_scoped_resource_binding_immutable
    ON authorization_scopedresourcebinding;
DROP FUNCTION IF EXISTS maru_prevent_scoped_resource_binding_mutation();
"""


class Migration(migrations.Migration):

    dependencies = [
        ("authorization", "0003_capabilitygrant_approved_by_and_more"),
        ("events", "0009_edition_workspace_downgrade_fence"),
        ("organizations", "0012_idn011_convention_subject_guards"),
        ("workforce", "0003_idn011_convention_subject_guards"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="capabilitygrant",
            name="department",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="capability_grants",
                to="workforce.department",
            ),
        ),
        migrations.AddField(
            model_name="roleassignment",
            name="department",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="role_assignments",
                to="workforce.department",
            ),
        ),
        migrations.CreateModel(
            name="ScopedResourceBinding",
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
                    "resource_kind",
                    models.CharField(
                        choices=[("workforce.position", "Workforce position")],
                        max_length=80,
                    ),
                ),
                ("resource_id", models.UUIDField()),
                (
                    "department",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="authorization_resource_bindings",
                        to="workforce.department",
                    ),
                ),
                (
                    "edition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="authorization_resource_bindings",
                        to="events.eventedition",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="authorization_resource_bindings",
                        to="organizations.organization",
                    ),
                ),
            ],
            options={
                "ordering": ("organization_id", "edition_id", "department_id", "id"),
            },
        ),
        migrations.AddField(
            model_name="capabilitygrant",
            name="resource_binding",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="capability_grants",
                to="authorization.scopedresourcebinding",
            ),
        ),
        migrations.AddField(
            model_name="roleassignment",
            name="resource_binding",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="role_assignments",
                to="authorization.scopedresourcebinding",
            ),
        ),
        migrations.AddIndex(
            model_name="capabilitygrant",
            index=models.Index(
                fields=["organization", "edition", "department", "resource_binding"],
                name="auth_grant_scope_v2_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="roleassignment",
            index=models.Index(
                fields=["organization", "edition", "department", "resource_binding"],
                name="auth_role_scope_v2_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="capabilitygrant",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("department__isnull", True), ("resource_binding__isnull", True)
                    ),
                    models.Q(("department__isnull", False), ("edition__isnull", False)),
                    _connector="OR",
                ),
                name="authorization_grant_scope_shape_v2",
            ),
        ),
        migrations.AddConstraint(
            model_name="roleassignment",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("department__isnull", True), ("resource_binding__isnull", True)
                    ),
                    models.Q(("department__isnull", False), ("edition__isnull", False)),
                    _connector="OR",
                ),
                name="authorization_role_scope_shape_v2",
            ),
        ),
        migrations.AddIndex(
            model_name="scopedresourcebinding",
            index=models.Index(
                fields=["organization", "edition", "department"],
                name="auth_binding_scope_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="scopedresourcebinding",
            constraint=models.UniqueConstraint(
                fields=("resource_kind", "resource_id"),
                name="authorization_resource_binding_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="scopedresourcebinding",
            constraint=models.CheckConstraint(
                condition=models.Q(("resource_kind", "workforce.position")),
                name="authorization_resource_kind_known",
            ),
        ),
        migrations.RunSQL(
            RESOURCE_BINDING_IMMUTABILITY_SQL,
            reverse_sql=REVERSE_RESOURCE_BINDING_IMMUTABILITY_SQL,
        ),
    ]
