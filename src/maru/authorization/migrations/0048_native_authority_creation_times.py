"""Record native authority creation fields without changing the physical schema."""

from typing import ClassVar

from django.db import migrations

from maru.authorization.fields import DatabaseCreatedAtField, ProgrammeRequestTimeField


class Migration(migrations.Migration):
    """Record the creation-clock implementation without changing stored columns."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0047_guidance_qualified_lineage"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AlterField(
                    model_name="roleassignment",
                    name="created_at",
                    field=DatabaseCreatedAtField(auto_now_add=True, editable=False),
                ),
                migrations.AlterField(
                    model_name="programmerolerequest",
                    name="requested_at",
                    field=ProgrammeRequestTimeField(),
                ),
                migrations.AlterField(
                    model_name="programmerolerequest",
                    name="approval_deadline",
                    field=ProgrammeRequestTimeField(deadline=True),
                ),
            ],
        ),
    ]
