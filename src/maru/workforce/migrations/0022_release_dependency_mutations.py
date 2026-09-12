"""Require native release consequences for current staffing source receipts."""

from typing import Any, ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_workforce_release_mutation_sources(audit_id uuid)
RETURNS TABLE(receipt_kind text, receipt_id uuid, kind text, source_id uuid,
              organization_id uuid, edition_id uuid) AS $$
    WITH native AS (
        SELECT * FROM public.audit_auditevent event
        WHERE event.id = audit_id AND event.outcome = 'allow'
          AND event.principal_kind = 'account' AND event.principal_context_id IS NULL
    ), receipts AS (
        SELECT 'demand'::text AS receipt_kind, receipt.id AS receipt_id,
               'workforce_demand'::text AS kind, receipt.demand_id AS source_id,
               receipt.organization_id, receipt.edition_id,
               receipt.actor_id, receipt.retry_key, receipt.correlation_id,
               receipt.source_channel, receipt.demand_id AS target_id,
               'workforce.shift_demand'::text AS target_type,
               'workforce.shift_demand.' || receipt.action AS operation
        FROM public.workforce_shiftdemandcommandreceipt receipt
        WHERE receipt.action IN (
            'created', 'updated', 'opened', 'locked', 'reopened',
            'completed', 'cancelled'
        )
        UNION ALL
        SELECT 'commitment', receipt.id, 'workforce_demand', receipt.demand_id,
               receipt.organization_id, receipt.edition_id,
               receipt.actor_id, receipt.retry_key, receipt.correlation_id,
               receipt.source_channel,
               receipt.commitment_id, 'workforce.shift_commitment',
               'workforce.shift_commitment.' || receipt.action
        FROM public.workforce_shiftcommitmentcommandreceipt receipt
        JOIN public.workforce_shiftcommitment commitment
          ON commitment.id = receipt.commitment_id
          AND commitment.demand_id = receipt.demand_id
          AND commitment.organization_id = receipt.organization_id
          AND commitment.edition_id = receipt.edition_id
        WHERE receipt.action IN (
            'claimed', 'confirmed', 'withdrawn', 'removed', 'completed', 'cancelled'
        )
        UNION ALL
        SELECT 'availability', receipt.id, 'workforce_availability', receipt.plan_id,
               receipt.organization_id, receipt.edition_id,
               receipt.actor_id, receipt.retry_key, receipt.correlation_id,
               receipt.source_channel,
               receipt.plan_id, 'workforce.person_availability_plan',
               'workforce.person_availability.' || receipt.action
        FROM public.workforce_personavailabilitycommandreceipt receipt
        WHERE receipt.action IN ('draft_saved', 'submitted', 'withdrawn')
        UNION ALL
        SELECT 'assignment', receipt.id, 'workforce_assignment', receipt.assignment_id,
               receipt.organization_id, receipt.edition_id,
               receipt.actor_id, receipt.retry_key, receipt.correlation_id,
               receipt.source_channel,
               receipt.assignment_id, 'workforce.position_assignment',
               'workforce.position_assignment.end'
        FROM public.workforce_positionassignmentcommandreceipt receipt
        WHERE receipt.action = 'ended'
    )
    SELECT receipt.receipt_kind, receipt.receipt_id, receipt.kind, receipt.source_id,
           receipt.organization_id, receipt.edition_id
    FROM receipts receipt JOIN native event
      ON event.target_id = receipt.target_id AND event.target_type = receipt.target_type
     AND event.operation = receipt.operation AND event.principal_id = receipt.actor_id
     AND event.organization_id = receipt.organization_id
     AND event.event_edition_id = receipt.edition_id
     AND event.correlation_id = receipt.correlation_id
     AND event.source_channel = receipt.source_channel
     AND event.idempotency_key_hash = encode(
         sha256(convert_to(receipt.retry_key::text, 'UTF8')), 'hex'
     );
$$ LANGUAGE sql VOLATILE
SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER workforce_release_demand_identity
BEFORE UPDATE OR DELETE ON public.workforce_shiftdemand
FOR EACH ROW EXECUTE FUNCTION public.maru_scheduling_release_source_identity_guard(
    'workforce_demand'
);
CREATE TRIGGER workforce_release_assignment_identity
BEFORE UPDATE OR DELETE ON public.workforce_positionassignment
FOR EACH ROW EXECUTE FUNCTION public.maru_scheduling_release_source_identity_guard(
    'workforce_assignment'
);
CREATE TRIGGER workforce_release_availability_identity
BEFORE UPDATE OR DELETE ON public.workforce_personavailabilityplan
FOR EACH ROW EXECUTE FUNCTION public.maru_scheduling_release_source_identity_guard(
    'workforce_availability'
);

CREATE FUNCTION public.maru_workforce_release_change_valid(
    dependency_kind text, source uuid, organization uuid, edition uuid, audit_id uuid
) RETURNS boolean AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.maru_workforce_release_mutation_sources(audit_id) reference
        WHERE reference.kind = dependency_kind AND reference.source_id = source
          AND
            reference.organization_id = organization AND reference.edition_id = edition
    );
$$ LANGUAGE sql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_workforce_release_receipt_guard()
RETURNS trigger AS $$
DECLARE
    source_kind text;
    source uuid;
    tracked_dependency_id uuid;
BEGIN
    IF TG_ARGV[0] = 'assignment' AND NEW.action <> 'ended' THEN RETURN NEW; END IF;
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'Workforce release source writes require READ COMMITTED'
            USING ERRCODE = '23514';
    END IF;
    IF TG_WHEN = 'BEFORE' THEN RETURN NEW; END IF;
    CASE TG_ARGV[0]
        WHEN 'demand', 'commitment' THEN
            source_kind := 'workforce_demand'; source := NEW.demand_id;
        WHEN 'availability' THEN
            source_kind := 'workforce_availability'; source := NEW.plan_id;
        WHEN 'assignment' THEN
            source_kind := 'workforce_assignment'; source := NEW.assignment_id;
        ELSE RAISE EXCEPTION 'unsupported Workforce release receipt'
            USING ERRCODE = '23514';
    END CASE;
    SELECT id INTO tracked_dependency_id
        FROM public.scheduling_schedulingreleasedependencykey
        WHERE kind = source_kind AND source_id = source;
    IF tracked_dependency_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.scheduling_schedulingreleasedependencychange change
        JOIN public.audit_auditnativemutationwitness witness
          ON witness.audit_event_id = change.source_audit_id
        CROSS JOIN LATERAL public.maru_workforce_release_mutation_sources(
            witness.audit_event_id
        ) reference
        WHERE change.dependency_id = tracked_dependency_id
          AND witness.transaction_stamp =
              public.maru_audit_current_native_transaction_stamp()
          AND reference.receipt_kind = TG_ARGV[0] AND reference.receipt_id = NEW.id
          AND reference.kind = source_kind AND reference.source_id = source
          AND reference.organization_id = NEW.organization_id
          AND reference.edition_id = NEW.edition_id
    ) THEN
        RAISE EXCEPTION
            'Workforce source receipt requires its native release invalidation'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;
"""

RECEIPTS = (
    ("demand", "workforce_shiftdemandcommandreceipt"),
    ("commitment", "workforce_shiftcommitmentcommandreceipt"),
    ("availability", "workforce_personavailabilitycommandreceipt"),
    ("assignment", "workforce_positionassignmentcommandreceipt"),
)
for kind, table in RECEIPTS:
    FORWARD_SQL += f"""
CREATE TRIGGER workforce_release_{kind}_isolation
BEFORE INSERT ON public.{table}
FOR EACH ROW EXECUTE FUNCTION public.maru_workforce_release_receipt_guard('{kind}');
CREATE CONSTRAINT TRIGGER workforce_release_{kind}_evidence
AFTER INSERT ON public.{table}
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_workforce_release_receipt_guard('{kind}');
"""

REVERSE_SQL = (
    "\n".join(
        f"DROP TRIGGER workforce_release_{kind}_{suffix} ON public.{table};"
        for kind, table in reversed(RECEIPTS)
        for suffix in ("evidence", "isolation")
    )
    + r"""
DROP TRIGGER workforce_release_availability_identity
    ON public.workforce_personavailabilityplan;
DROP TRIGGER workforce_release_assignment_identity
    ON public.workforce_positionassignment;
DROP TRIGGER workforce_release_demand_identity ON public.workforce_shiftdemand;
DROP FUNCTION public.maru_workforce_release_receipt_guard();
DROP FUNCTION public.maru_workforce_release_change_valid(text, uuid, uuid, uuid, uuid);
DROP FUNCTION public.maru_workforce_release_mutation_sources(uuid);
"""
)


def refuse_tracked_workforce_downgrade(apps: Any, schema_editor: Any) -> None:
    """Retain native staffing consequences after release source tracking."""
    key = apps.get_model("scheduling", "SchedulingReleaseDependencyKey")
    schema_editor.execute(
        "LOCK TABLE public.scheduling_schedulingreleasedependencykey "
        "IN ACCESS EXCLUSIVE MODE"
    )
    if key.objects.filter(kind__startswith="workforce_").exists():
        raise RuntimeError(
            "Release-tracked Workforce sources exist; retain guards and fix forward."
        )


class Migration(migrations.Migration):
    """Join demand, commitments, shared availability and assignment ending."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("workforce", "0021_programme_binding_downgrade_fence"),
        ("scheduling", "0008_release_dependency_guards"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_tracked_workforce_downgrade
        ),
    ]
