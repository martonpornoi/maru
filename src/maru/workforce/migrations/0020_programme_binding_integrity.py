"""Guard exact staffing source selection and reciprocal retained Shift lineage."""

from typing import ClassVar

from django.db import migrations

TABLES = ("workforce_programmeshiftbinding", "workforce_programmeshiftbindingrevision")
FUNCTIONS = (
    "maru_guard_workforce_programme_binding",
    "maru_guard_workforce_programme_binding_revision",
    "maru_validate_workforce_programme_binding_evidence",
)

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_guard_workforce_programme_binding()
RETURNS trigger AS $binding_guard$
DECLARE
    req record;
    work record;
    edition_lifecycle text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Programme demand bindings are retained' USING ERRCODE = '23514';
    END IF;
    SELECT lifecycle INTO edition_lifecycle FROM public.events_eventedition
      WHERE id = NEW.edition_id AND organization_id = NEW.organization_id FOR UPDATE;
    SELECT * INTO req FROM public.programme_programmestaffingrequirement WHERE id = NEW.requirement_id FOR SHARE;
    SELECT * INTO work FROM public.workforce_shiftdemand WHERE id = NEW.demand_id FOR UPDATE;
    IF edition_lifecycle IS NULL OR edition_lifecycle NOT IN ('draft', 'preparing')
       OR (req.organization_id, req.edition_id, req.item_id, req.occurrence_id, req.lifecycle)
          IS DISTINCT FROM (NEW.organization_id, NEW.edition_id, NEW.item_id, NEW.occurrence_id, 'active'::varchar)
       OR (work.organization_id, work.edition_id, work.status)
          IS DISTINCT FROM (NEW.organization_id, NEW.edition_id, 'draft'::varchar)
       OR NEW.version < 1 OR NEW.version > 1000
       OR NOT EXISTS (SELECT 1 FROM public.identity_account WHERE id = NEW.last_modified_by_id AND is_active)
       OR EXISTS (SELECT 1 FROM public.workforce_programmeshiftbinding b
                  WHERE (b.requirement_id = NEW.requirement_id OR b.demand_id = NEW.demand_id) AND b.id <> NEW.id)
       OR EXISTS (SELECT 1 FROM public.workforce_programmeshiftbindingrevision r
                  WHERE r.demand_id = NEW.demand_id AND r.binding_id <> NEW.id)
    THEN
        RAISE EXCEPTION 'Programme binding scope or target is invalid' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.version <> 1 THEN
            RAISE EXCEPTION 'A binding starts at its first revision' USING ERRCODE = '23514';
        END IF;
    ELSIF (NEW.id, NEW.organization_id, NEW.edition_id, NEW.requirement_id, NEW.item_id, NEW.occurrence_id, NEW.created_at)
          IS DISTINCT FROM (OLD.id, OLD.organization_id, OLD.edition_id, OLD.requirement_id, OLD.item_id, OLD.occurrence_id, OLD.created_at)
       OR NEW.version <> OLD.version + 1
    THEN
        RAISE EXCEPTION 'Programme binding identity and sequence are retained' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$binding_guard$ LANGUAGE plpgsql VOLATILE CALLED ON NULL INPUT SECURITY INVOKER PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guard_workforce_programme_binding_revision()
RETURNS trigger AS $binding_revision_guard$
DECLARE
    b record;
    req record;
    work record;
    previous record;
    predecessor_state text;
    receipt record;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Programme binding revisions are immutable' USING ERRCODE = '23514';
    END IF;
    SELECT * INTO b FROM public.workforce_programmeshiftbinding WHERE id = NEW.binding_id FOR UPDATE;
    SELECT * INTO req FROM public.programme_programmestaffingrevision WHERE id = NEW.requirement_revision_id;
    SELECT * INTO work FROM public.workforce_shiftdemand WHERE id = NEW.demand_id FOR UPDATE;
    SELECT * INTO previous FROM public.workforce_programmeshiftbindingrevision
      WHERE binding_id = NEW.binding_id ORDER BY sequence DESC LIMIT 1;
    IF (b.organization_id, b.edition_id, b.version, b.demand_id, b.last_modified_by_id)
       IS DISTINCT FROM (NEW.organization_id, NEW.edition_id, NEW.sequence, NEW.demand_id, NEW.actor_id)
       OR (req.organization_id, req.edition_id, req.requirement_id, req.item_id, req.sequence, req.occurrence_version, req.lifecycle)
       IS DISTINCT FROM (NEW.organization_id, NEW.edition_id, b.requirement_id, b.item_id, NEW.requirement_version, NEW.occurrence_version, 'active'::varchar)
       OR (work.organization_id, work.edition_id, work.command_version, work.status)
       IS DISTINCT FROM (NEW.organization_id, NEW.edition_id, NEW.demand_version, 'draft'::varchar)
       OR NEW.sequence <> COALESCE(previous.sequence, 0) + 1 OR NEW.sequence > 1000
       OR NEW.operation NOT IN ('create', 'link', 'reconcile', 'successor')
       OR NEW.work_terms_digest !~ '^[0-9a-f]{64}$' OR NEW.source_digest !~ '^[0-9a-f]{64}$'
       OR NEW.preview_digest !~ '^[0-9a-f]{64}$' OR NEW.request_digest !~ '^[0-9a-f]{64}$'
       OR NEW.reason !~ '[^[:space:]]' OR NEW.reason ~ '[[:cntrl:]]'
       OR NEW.source_channel !~ '^[a-z][a-z0-9_-]{0,31}$'
       OR EXISTS (SELECT 1 FROM public.workforce_shiftcommitment WHERE demand_id = NEW.demand_id)
       OR (work.position_id, work.title, work.location_label, work.briefing, work.supervision_note,
           work.starts_at, work.ends_at, work.required_headcount, work.break_minutes, work.minimum_rest_minutes)
          IS DISTINCT FROM (req.position_id, req.title, req.location_label, req.briefing, req.supervision_note,
           req.starts_at, req.ends_at, req.required_headcount, req.break_minutes, req.minimum_rest_minutes)
    THEN
        RAISE EXCEPTION 'Programme binding requires exact uncommitted work evidence' USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.programme_programmestaffingrequirement need
        JOIN public.programme_programmeitem item ON item.id = need.item_id
        JOIN public.scheduling_schedulingoccurrence occ ON occ.id = need.occurrence_id
        JOIN public.scheduling_schedulingoccurrencerevision ov ON ov.occurrence_id = occ.id AND ov.sequence = occ.aggregate_version
        JOIN public.scheduling_schedulingcandidatemember member ON member.occurrence_id = occ.id
        JOIN public.scheduling_schedulingcandidaterevision cv ON cv.id = member.revision_id
        JOIN public.scheduling_schedulingcandidate candidate ON candidate.id = cv.candidate_id
        JOIN public.scheduling_schedulingplacementrevision placement ON placement.id = member.placement_id
        JOIN public.scheduling_schedulingservicedayrevision dv ON dv.id = placement.day_revision_id
        JOIN public.scheduling_schedulingserviceday day ON day.id = dv.day_id
        WHERE need.id = b.requirement_id AND need.version = NEW.requirement_version AND need.lifecycle = 'active'
          AND item.lifecycle = 'active' AND occ.lifecycle = 'active' AND occ.aggregate_version = NEW.occurrence_version
          AND occ.programme_item_id = b.item_id AND ov.id = placement.occurrence_revision_id
          AND candidate.id = NEW.candidate_id AND candidate.lifecycle = 'draft' AND candidate.aggregate_version = cv.sequence
          AND cv.id = NEW.candidate_revision_id AND placement.id = NEW.placement_id
          AND day.lifecycle = 'active' AND day.aggregate_version = dv.sequence
          AND (occ.organization_id, occ.edition_id, candidate.organization_id, candidate.edition_id,
               placement.organization_id, placement.edition_id, day.organization_id, day.edition_id)
            = (NEW.organization_id, NEW.edition_id, NEW.organization_id, NEW.edition_id,
               NEW.organization_id, NEW.edition_id, NEW.organization_id, NEW.edition_id)
    ) THEN
        RAISE EXCEPTION 'Programme binding source is stale or outside its scope' USING ERRCODE = '23514';
    END IF;
    IF NEW.operation IN ('create', 'link') THEN
        IF NEW.sequence <> 1 OR NEW.predecessor_id IS NOT NULL OR NEW.cancellation_receipt_id IS NOT NULL THEN
            RAISE EXCEPTION 'Initial binding cannot replace retained work' USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.operation = 'reconcile' THEN
        IF previous.id IS NULL OR previous.demand_id <> NEW.demand_id
           OR NEW.demand_version <= previous.demand_version
           OR NEW.predecessor_id IS NOT NULL OR NEW.cancellation_receipt_id IS NOT NULL THEN
            RAISE EXCEPTION 'Reconciliation must retain its exact demand' USING ERRCODE = '23514';
        END IF;
    ELSE
        SELECT status INTO predecessor_state FROM public.workforce_shiftdemand
          WHERE id = NEW.predecessor_id AND organization_id = NEW.organization_id AND edition_id = NEW.edition_id;
        IF previous.id IS NULL OR NEW.predecessor_id IS DISTINCT FROM previous.demand_id
           OR NEW.demand_id = NEW.predecessor_id OR predecessor_state NOT IN ('cancelled', 'completed')
           OR predecessor_state IS NULL
           OR EXISTS (SELECT 1 FROM public.workforce_programmeshiftbindingrevision WHERE demand_id = NEW.demand_id)
        THEN
            RAISE EXCEPTION 'A successor preserves a distinct terminal predecessor' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF NEW.operation = 'link' THEN
        IF NEW.shift_receipt_id IS NOT NULL THEN
            RAISE EXCEPTION 'Linking must not mutate its existing draft' USING ERRCODE = '23514';
        END IF;
    ELSE
        SELECT * INTO receipt FROM public.workforce_shiftdemandcommandreceipt WHERE id = NEW.shift_receipt_id;
        IF (receipt.organization_id, receipt.edition_id, receipt.actor_id, receipt.demand_id, receipt.resulting_version,
            receipt.resulting_status, receipt.reason, receipt.correlation_id, receipt.source_channel, receipt.action)
           IS DISTINCT FROM (NEW.organization_id, NEW.edition_id, NEW.actor_id, NEW.demand_id, NEW.demand_version,
            'draft'::varchar, NEW.reason, NEW.correlation_id, NEW.source_channel,
            CASE WHEN NEW.operation = 'reconcile' THEN 'updated'::varchar ELSE 'created'::varchar END)
           OR (NEW.operation <> 'reconcile' AND NEW.demand_version <> 1)
           OR EXISTS (SELECT 1 FROM public.workforce_programmeshiftbindingrevision WHERE shift_receipt_id = NEW.shift_receipt_id)
        THEN
            RAISE EXCEPTION 'Binding requires its exact Workforce command receipt' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF NEW.cancellation_receipt_id IS NOT NULL THEN
        SELECT * INTO receipt FROM public.workforce_shiftdemandcommandreceipt WHERE id = NEW.cancellation_receipt_id;
        IF (receipt.organization_id, receipt.edition_id, receipt.actor_id, receipt.demand_id, receipt.resulting_status,
            receipt.reason, receipt.correlation_id, receipt.source_channel, receipt.action)
           IS DISTINCT FROM (NEW.organization_id, NEW.edition_id, NEW.actor_id, NEW.predecessor_id, 'cancelled'::varchar,
            NEW.reason, NEW.correlation_id, NEW.source_channel, 'cancelled'::varchar)
           OR EXISTS (SELECT 1 FROM public.workforce_programmeshiftbindingrevision WHERE cancellation_receipt_id = NEW.cancellation_receipt_id)
        THEN
            RAISE EXCEPTION 'Successor cancellation requires exact owner evidence' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$binding_revision_guard$ LANGUAGE plpgsql VOLATILE CALLED ON NULL INPUT SECURITY INVOKER PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_validate_workforce_programme_binding_evidence()
RETURNS trigger AS $binding_evidence_guard$
DECLARE
    r record;
BEGIN
    IF TG_TABLE_NAME = 'workforce_programmeshiftbinding' THEN
        SELECT * INTO r FROM public.workforce_programmeshiftbindingrevision WHERE binding_id = NEW.id AND sequence = NEW.version;
        IF (r.organization_id, r.edition_id, r.demand_id, r.actor_id)
           IS DISTINCT FROM (NEW.organization_id, NEW.edition_id, NEW.demand_id, NEW.last_modified_by_id)
        THEN
            RAISE EXCEPTION 'Binding requires its exact immutable revision' USING ERRCODE = '23514';
        END IF;
    ELSE
        SELECT * INTO r FROM public.workforce_programmeshiftbindingrevision WHERE id = NEW.id;
    END IF;
    IF r.id IS NULL OR NOT EXISTS (
        SELECT 1 FROM public.audit_auditevent a JOIN public.effects_domainevent e ON e.causation_id = a.id
        WHERE a.id = r.audit_event_id AND e.id = r.domain_event_id
          AND a.principal_kind = 'account' AND a.principal_id = r.actor_id
          AND a.organization_id = r.organization_id AND a.event_edition_id = r.edition_id
          AND a.operation = 'workforce.programme_binding.' || r.operation AND a.outcome = 'allow'
          AND a.capability_code = 'workforce.manage_shifts' AND a.target_type = 'workforce.programme_binding' AND a.target_id = r.binding_id
          AND a.correlation_id = r.correlation_id AND a.source_channel = r.source_channel
          AND a.retention_class = 'workforce-restricted' AND e.retention_class = a.retention_class
          AND e.organization_id = r.organization_id AND e.event_edition_id = r.edition_id
          AND e.actor_kind = 'account' AND e.actor_id = r.actor_id AND e.correlation_id = r.correlation_id
          AND e.aggregate_type = 'workforce.programme_binding' AND e.aggregate_id = r.binding_id AND e.aggregate_version = r.sequence
          AND e.event_name = 'workforce.programme_staffing.changed.v1' AND e.schema_version = 1
          AND e.payload = jsonb_build_object('action', r.operation)
          AND EXISTS (SELECT 1 FROM public.effects_outboxmessage o WHERE o.event_id = e.id AND o.organization_id = r.organization_id)
    ) THEN
        RAISE EXCEPTION 'Binding requires reciprocal audit event and outbox evidence' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$binding_evidence_guard$ LANGUAGE plpgsql VOLATILE CALLED ON NULL INPUT SECURITY INVOKER PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""

_reverse = []
for _table, _guard, _short in zip(
    TABLES, FUNCTIONS[:2], ("binding", "binding_revision"), strict=True
):
    FORWARD_SQL += f"""
CREATE TRIGGER workforce_programme_{_short}_guard BEFORE INSERT OR UPDATE OR DELETE ON public.{_table}
FOR EACH ROW EXECUTE FUNCTION public.{_guard}();
CREATE TRIGGER workforce_programme_{_short}_truncate BEFORE TRUNCATE ON public.{_table}
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_refuse_workforce_shift_truncate();
CREATE CONSTRAINT TRIGGER workforce_programme_{_short}_evidence AFTER INSERT OR UPDATE ON public.{_table}
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.maru_validate_workforce_programme_binding_evidence();
"""
    _reverse.extend(
        f"DROP TRIGGER workforce_programme_{_short}_{suffix} ON public.{_table};"
        for suffix in ("guard", "truncate", "evidence")
    )
FORWARD_SQL += (
    "REVOKE ALL ON FUNCTION "
    + ", ".join(f"public.{name}()" for name in FUNCTIONS)
    + " FROM PUBLIC;"
)
REVERSE_SQL = "\n".join(
    (*_reverse, *(f"DROP FUNCTION public.{name}();" for name in FUNCTIONS))
)


class Migration(migrations.Migration):
    """Add dormant binding integrity without widening any runtime write grant."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("workforce", "0019_programme_shift_bindings")
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL)
    ]
