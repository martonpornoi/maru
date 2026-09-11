"""Bind native operational receipts to same-transaction release consequences."""

from typing import Any, ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_programme_release_mutation_sources(receipt_id uuid)
RETURNS TABLE(kind text, source_id uuid) AS $$
    WITH receipt AS (
        SELECT * FROM public.programme_programmecommandreceipt WHERE id = receipt_id
    ), host_revision AS (
        SELECT revision.* FROM public.programme_programmehostrevision revision
        JOIN receipt ON receipt.result_object_id = revision.id
        WHERE receipt.operation IN (
            'host_invite', 'host_respond', 'host_remove', 'host_availability'
        )
          AND revision.item_id = receipt.item_id
          AND revision.organization_id = receipt.organization_id
          AND revision.edition_id = receipt.edition_id
          AND revision.item_version = receipt.resulting_item_version
          AND revision.operation = receipt.operation
          AND revision.actor_id = receipt.actor_id
    )
    SELECT 'programme_item'::text, item_id FROM receipt
    WHERE operation IN (
        'delivery_revise', 'readiness_configure', 'readiness_record',
        'host_invite', 'host_respond', 'host_remove', 'host_availability',
        'staffing_create', 'staffing_revise', 'staffing_retire',
        'accessibility_fit_record', 'staffing_absence_record'
    )
    UNION ALL
    SELECT 'programme_host_operational'::text, host_id FROM host_revision
    UNION ALL
    SELECT 'programme_host_disclosure'::text, host_id FROM host_revision
    WHERE state <> 'confirmed';
$$ LANGUAGE sql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_programme_release_change_valid(
    dependency_kind text, source uuid, organization uuid, edition uuid, audit_id uuid
) RETURNS boolean AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.audit_auditevent event
        JOIN public.programme_programmecommandreceipt receipt
          ON event.target_id = receipt.item_id
         AND event.organization_id = receipt.organization_id
         AND event.event_edition_id = receipt.edition_id
         AND event.principal_id = receipt.actor_id
         AND event.operation = 'programme.command.' || receipt.operation
         AND event.correlation_id = receipt.correlation_id
         AND event.source_channel = receipt.source_channel
         AND event.idempotency_key_hash = encode(
             sha256(convert_to(receipt.idempotency_key::text, 'UTF8')), 'hex'
         )
        CROSS JOIN LATERAL
            public.maru_programme_release_mutation_sources(receipt.id) reference
        WHERE event.id = audit_id AND event.outcome = 'allow'
          AND event.principal_kind = 'account' AND event.principal_context_id IS NULL
          AND event.target_type = 'programme.item'
          AND receipt.organization_id = organization AND receipt.edition_id = edition
          AND reference.kind = dependency_kind AND reference.source_id = source
    );
$$ LANGUAGE sql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_programme_release_receipt_guard()
RETURNS trigger AS $$
DECLARE tracked record;
BEGIN
    IF NEW.operation NOT IN (
        'delivery_revise', 'readiness_configure', 'readiness_record',
        'host_invite', 'host_respond', 'host_remove', 'host_availability',
        'staffing_create', 'staffing_revise', 'staffing_retire',
        'accessibility_fit_record', 'staffing_absence_record'
    ) THEN RETURN NEW; END IF;
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'Programme release source writes require READ COMMITTED'
            USING ERRCODE = '23514';
    END IF;
    IF TG_WHEN = 'BEFORE' THEN RETURN NEW; END IF;
    FOR tracked IN
        SELECT dependency.id, dependency.kind, dependency.source_id
        FROM public.maru_programme_release_mutation_sources(NEW.id) reference
        JOIN public.scheduling_schedulingreleasedependencykey dependency
          ON dependency.kind = reference.kind
         AND dependency.source_id = reference.source_id
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM public.scheduling_schedulingreleasedependencychange change
            JOIN public.audit_auditnativemutationwitness witness
              ON witness.audit_event_id = change.source_audit_id
            JOIN public.audit_auditevent event ON event.id = witness.audit_event_id
            WHERE change.dependency_id = tracked.id
              AND witness.transaction_stamp =
                  public.maru_audit_current_native_transaction_stamp()
              AND event.idempotency_key_hash = encode(
                  sha256(convert_to(NEW.idempotency_key::text, 'UTF8')), 'hex'
              )
              AND public.maru_programme_release_change_valid(
                  tracked.kind, tracked.source_id, NEW.organization_id,
                  NEW.edition_id, event.id
              )
        ) THEN
            RAISE EXCEPTION
                'Programme source receipt requires its native release invalidation'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

CREATE TRIGGER programme_release_receipt_isolation
BEFORE INSERT ON public.programme_programmecommandreceipt
FOR EACH ROW EXECUTE FUNCTION public.maru_programme_release_receipt_guard();
CREATE CONSTRAINT TRIGGER programme_release_receipt_evidence
AFTER INSERT ON public.programme_programmecommandreceipt
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_programme_release_receipt_guard();
CREATE TRIGGER programme_release_item_identity
BEFORE UPDATE OR DELETE ON public.programme_programmeitem
FOR EACH ROW EXECUTE FUNCTION public.maru_scheduling_release_source_identity_guard(
    'programme_item'
);
CREATE TRIGGER programme_release_host_identity
BEFORE UPDATE OR DELETE ON public.programme_programmehostrelationship
FOR EACH ROW EXECUTE FUNCTION public.maru_scheduling_release_source_identity_guard(
    'programme_host_operational', 'programme_host_disclosure'
);
CREATE TRIGGER programme_release_copy_identity
BEFORE UPDATE OR DELETE ON public.programme_programmepublicrendition
FOR EACH ROW EXECUTE FUNCTION public.maru_scheduling_release_source_identity_guard(
    'programme_public_copy'
);
"""

REVERSE_SQL = r"""
DROP TRIGGER programme_release_copy_identity
    ON public.programme_programmepublicrendition;
DROP TRIGGER programme_release_host_identity
    ON public.programme_programmehostrelationship;
DROP TRIGGER programme_release_item_identity ON public.programme_programmeitem;
DROP TRIGGER programme_release_receipt_evidence
    ON public.programme_programmecommandreceipt;
DROP TRIGGER programme_release_receipt_isolation
    ON public.programme_programmecommandreceipt;
DROP FUNCTION public.maru_programme_release_receipt_guard();
DROP FUNCTION public.maru_programme_release_change_valid(text, uuid, uuid, uuid, uuid);
DROP FUNCTION public.maru_programme_release_mutation_sources(uuid);
"""


def refuse_tracked_programme_downgrade(apps: Any, schema_editor: Any) -> None:
    """Keep native invalidation before allowing a populated Programme downgrade."""
    key = apps.get_model("scheduling", "SchedulingReleaseDependencyKey")
    schema_editor.execute(
        "LOCK TABLE public.scheduling_schedulingreleasedependencykey "
        "IN ACCESS EXCLUSIVE MODE"
    )
    if key.objects.filter(kind__startswith="programme_").exists():
        raise RuntimeError(
            "Release-tracked Programme sources exist; retain guards and fix forward."
        )


class Migration(migrations.Migration):
    """Require governing source changes without reading foreign releases."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("programme", "0015_placement_decision_downgrade_fence"),
        ("scheduling", "0008_release_dependency_guards"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_tracked_programme_downgrade
        ),
    ]
