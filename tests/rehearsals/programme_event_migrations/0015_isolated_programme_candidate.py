"""Admit one synthetic candidate pair without modifying production migrations."""

# ruff: noqa: N999 -- Django's ordered migration module convention.

from typing import ClassVar

from django.db import migrations, models

from tests.rehearsals.programme_candidate_schema import (
    require_empty_candidate_schema,
    require_empty_current_schema,
)


class Migration(migrations.Migration):
    """Keep native profile enforcement and refuse installation or reversal on use."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("events", "0014_programme_setup_downgrade_fence"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunPython(require_empty_current_schema, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            "eventedition", "edition_adoption_profile_supported"
        ),
        migrations.AddConstraint(
            "eventedition",
            models.CheckConstraint(
                condition=(
                    models.Q(
                        adoption_profile_code="full_convention",
                        adoption_profile_version=1,
                    )
                    | models.Q(
                        adoption_profile_code="workforce_only",
                        adoption_profile_version=1,
                    )
                    | models.Q(
                        adoption_profile_code="programme_operations",
                        adoption_profile_version=1,
                    )
                ),
                name="edition_adoption_profile_supported",
            ),
        ),
        migrations.AlterField(
            "eventedition",
            "adoption_profile_code",
            models.CharField(
                choices=[
                    ("full_convention", "Full convention"),
                    ("workforce_only", "Workforce only"),
                    (
                        "programme_operations",
                        "Programme Operations — isolated candidate, not accepted",
                    ),
                ],
                default="full_convention",
                db_default="full_convention",
                editable=False,
                max_length=40,
            ),
        ),
        migrations.RunPython(migrations.RunPython.noop, require_empty_candidate_schema),
    ]
