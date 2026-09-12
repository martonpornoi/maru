"""Retain account identity behind global person-work source tracking."""

from typing import Any, ClassVar

from django.db import migrations

_DROP = "DROP TRIGGER identity_release_source_identity ON public.identity_account;"
_CREATE = """
CREATE TRIGGER identity_release_source_identity
BEFORE UPDATE OR DELETE ON public.identity_account
FOR EACH ROW EXECUTE FUNCTION
public.maru_scheduling_release_source_identity_guard('identity_account'{extra});
"""
FORWARD_SQL = _DROP + _CREATE.format(extra=", 'workforce_person_obligations'")
REVERSE_SQL = _DROP + _CREATE.format(extra="")


def refuse_tracked_person_work_downgrade(apps: Any, schema_editor: Any) -> None:
    """Keep the exact global source identity once a release has tracked it."""
    schema_editor.execute(
        "LOCK TABLE public.scheduling_schedulingreleasedependencykey "
        "IN ACCESS EXCLUSIVE MODE"
    )
    if (
        apps.get_model("scheduling", "SchedulingReleaseDependencyKey")
        .objects.filter(kind="workforce_person_obligations")
        .exists()
    ):
        raise RuntimeError("Person-work source identities are retained; fix forward.")


class Migration(migrations.Migration):
    """Add no account permission or person eligibility bypass."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("identity", "0021_release_dependency_deactivation"),
        ("scheduling", "0013_person_obligation_dependency_kind"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_tracked_person_work_downgrade
        ),
    ]
