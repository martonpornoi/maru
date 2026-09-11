"""Close native release helper ACLs before any application role is provisioned."""

from typing import Any, ClassVar

from django.db import migrations

# Frozen explicit identities, not a live namespace scan or current runtime catalog.
# The journal writer already revoked PUBLIC in 0009 and is deliberately absent.
FUNCTIONS = (
    "maru_audit_capture_native_mutation()",
    "maru_audit_current_native_transaction_stamp()",
    "maru_audit_native_witness_guard()",
    "maru_events_release_change_valid(uuid, uuid, uuid, uuid)",
    "maru_events_release_source_guard()",
    "maru_identity_release_deactivation_valid(uuid, uuid)",
    "maru_identity_release_source_guard()",
    "maru_programme_release_change_valid(text, uuid, uuid, uuid, uuid)",
    "maru_programme_release_mutation_sources(uuid)",
    "maru_programme_release_receipt_guard()",
    "maru_scheduling_lock_release_source(text, uuid, uuid, uuid)",
    "maru_scheduling_release_change_guard()",
    "maru_scheduling_release_key_complete()",
    "maru_scheduling_release_key_guard()",
    "maru_scheduling_release_native_change_valid(text, uuid, uuid, uuid, uuid)",
    "maru_scheduling_release_source_identity_guard()",
    "maru_venues_release_auxiliary_guard()",
    "maru_venues_release_change_valid(text, uuid, uuid, uuid, uuid)",
    "maru_venues_release_mutation_sources(uuid)",
    "maru_venues_release_selected_parent_guard()",
    "maru_venues_release_source_guard()",
    "maru_workforce_release_change_valid(text, uuid, uuid, uuid, uuid)",
    "maru_workforce_release_mutation_sources(uuid)",
    "maru_workforce_release_receipt_guard()",
)
FORWARD_SQL = "\n".join(
    f"REVOKE ALL ON FUNCTION public.{identity} FROM PUBLIC;" for identity in FUNCTIONS
)
REVERSE_SQL = "\n".join(
    f"GRANT EXECUTE ON FUNCTION public.{identity} TO PUBLIC;"
    for identity in reversed(FUNCTIONS)
)


def refuse_used_execution_boundary_downgrade(apps: Any, schema_editor: Any) -> None:
    """Do not reopen privileged function ACLs after native release attribution use."""
    schema_editor.execute(
        "LOCK TABLE public.audit_auditnativemutationwitness, "
        "public.scheduling_schedulingreleasedependencykey IN ACCESS EXCLUSIVE MODE"
    )
    witness = apps.get_model("audit", "AuditNativeMutationWitness")
    key = apps.get_model("scheduling", "SchedulingReleaseDependencyKey")
    if witness.objects.exists() or key.objects.exists():
        raise RuntimeError(
            "Native release evidence exists; retain its execution boundary "
            "and fix forward."
        )


class Migration(migrations.Migration):
    """Revoke defaults only; create no login, grants, profile or feature activation."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("scheduling", "0011_release_source_baseline"),
        ("venues", "0008_release_first_capture"),
        ("authorization", "0029_programme_release_capabilities"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_used_execution_boundary_downgrade
        ),
    ]
