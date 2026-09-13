"""Bind immutable notice facts to exact sources and native Scheduling evidence."""

from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations

_schema = import_module("maru.scheduling.migrations.0021_change_notice_schema")
_release = import_module("maru.scheduling.migrations.0017_atomic_release_graph")
_release_fence = import_module("maru.scheduling.migrations.0020_release_recovery_fence")
_authority_fence = import_module(
    "maru.authorization.migrations.0031_programme_change_communication_capabilities"
)
_old_graph = _release._graph  # noqa: SLF001 - frozen installed definition
_marker = "        CASE\n        WHEN NEW.operation = 'release_publish'"
if _old_graph.count(_marker) != 1:
    raise RuntimeError("The frozen Scheduling receipt dispatch changed.")
_graph = _old_graph.replace(
    _marker,
    """        CASE
        WHEN NEW.operation = 'change_prepare' AND NEW.resulting_version = 1 THEN
            SELECT to_jsonb(row) AS body INTO result_row
            FROM public.scheduling_schedulingchangenotice row
            WHERE row.id = NEW.result_object_id AND row.command_receipt_id = NEW.id;
            expected_capability := 'scheduling.prepare_change_notices';
        WHEN NEW.operation IN ('change_approve', 'change_reject',
                               'change_handoff', 'change_acknowledge') THEN
            SELECT to_jsonb(row) AS body INTO result_row
            FROM public.scheduling_schedulingchangenoticeevidence row
            WHERE row.id = NEW.result_object_id AND row.command_receipt_id = NEW.id
              AND row.sequence = NEW.resulting_version
              AND NEW.operation = 'change_' || row.action;
            expected_capability := CASE NEW.operation
                WHEN 'change_approve' THEN 'scheduling.review_change_notices'
                WHEN 'change_reject' THEN 'scheduling.review_change_notices'
                WHEN 'change_handoff' THEN 'scheduling.handoff_change_notices'
                WHEN 'change_acknowledge' THEN 'scheduling.acknowledge_change_self'
            END;
        WHEN NEW.operation = 'release_publish'""",
)
_event_marker = (
    "THEN 'scheduling.release.changed.v1' ELSE 'scheduling.planning.changed.v1' END"
)
if _graph.count(_event_marker) != 1:
    raise RuntimeError("The frozen Scheduling event family dispatch changed.")
_graph = _graph.replace(
    _event_marker,
    "THEN 'scheduling.release.changed.v1' "
    "WHEN NEW.operation IN ('change_prepare', 'change_approve', 'change_reject', "
    "'change_handoff', 'change_acknowledge') "
    "THEN 'scheduling.change_notice.changed.v1' "
    "ELSE 'scheduling.planning.changed.v1' END",
)

TABLES = ("schedulingchangenotice", "schedulingchangenoticeevidence")
FUNCTIONS = (
    "maru_scheduling_change_notice_source_valid(uuid)",
    "maru_scheduling_change_notice_graph()",
)

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_scheduling_change_notice_source_valid(selected uuid)
RETURNS boolean AS $$
DECLARE
    notice public.scheduling_schedulingchangenotice;
    publication public.scheduling_schedulingrelease;
    pointer public.scheduling_schedulingreleasepointer;
    occurrence public.scheduling_schedulingoccurrence;
    approval_ids uuid[];
BEGIN
    SELECT * INTO notice FROM public.scheduling_schedulingchangenotice
    WHERE id = selected;
    SELECT * INTO publication FROM public.scheduling_schedulingrelease
    WHERE id = notice.release_id AND organization_id = notice.organization_id
      AND edition_id = notice.edition_id;
    SELECT * INTO pointer FROM public.scheduling_schedulingreleasepointer
    WHERE organization_id = notice.organization_id AND edition_id = notice.edition_id;
    SELECT * INTO occurrence FROM public.scheduling_schedulingoccurrence
    WHERE id = notice.occurrence_id AND organization_id = notice.organization_id
      AND edition_id = notice.edition_id;
    IF notice.id IS NULL OR publication.id IS NULL OR pointer.id IS NULL
       OR occurrence.id IS NULL OR pointer.version <> notice.pointer_version
       OR NOT EXISTS (
        SELECT 1 FROM public.identity_account person WHERE person.id = notice.recipient_id
          AND person.is_active AND person.email_verified_at IS NOT NULL
          AND person.account_kind = 'person'
       ) THEN RETURN FALSE; END IF;
    IF notice.source_state = 'withdrawn' THEN
        IF pointer.active_release_id IS NOT NULL OR NOT EXISTS (
            SELECT 1 FROM public.scheduling_schedulingreleasewithdrawal withdrawal
            WHERE withdrawal.organization_id = notice.organization_id
              AND withdrawal.edition_id = notice.edition_id
              AND withdrawal.release_id = publication.id
              AND withdrawal.pointer_version = pointer.version
        ) THEN RETURN FALSE; END IF;
    ELSIF pointer.active_release_id IS DISTINCT FROM publication.id THEN
        RETURN FALSE;
    END IF;
    -- The application independently verifies serving generations, current owner
    -- permissions and the complete preview digest. These native guards prove
    -- exact retained source membership, not an authorization or serving token.
    IF public.maru_scheduling_release_artifact_is_exact(publication.id)
       IS DISTINCT FROM TRUE THEN RETURN FALSE; END IF;
    SELECT array_agg(release.approval_id) INTO approval_ids
    FROM public.scheduling_schedulingrelease release
    WHERE release.id IN (publication.id, publication.previous_release_id)
      AND release.organization_id = notice.organization_id
      AND release.edition_id = notice.edition_id;
    IF NOT EXISTS (
        SELECT 1 FROM public.scheduling_schedulingreleaseapprovalplacement chosen
        WHERE chosen.approval_id = ANY(approval_ids)
          AND chosen.organization_id = notice.organization_id
          AND chosen.edition_id = notice.edition_id
          AND chosen.occurrence_id = notice.occurrence_id
    ) THEN RETURN FALSE; END IF;
    CASE notice.recipient_purpose
    WHEN 'host' THEN
        RETURN EXISTS (
            SELECT 1 FROM public.programme_programmehostrelationship host
            JOIN public.scheduling_schedulingplacementhostpresence presence
              ON presence.host_relationship_id = host.id
             AND presence.organization_id = host.organization_id
             AND presence.edition_id = host.edition_id
            JOIN public.scheduling_schedulingreleaseapprovalplacement chosen
              ON chosen.placement_id = presence.placement_id
             AND chosen.organization_id = presence.organization_id
             AND chosen.edition_id = presence.edition_id
            WHERE host.id = notice.recipient_target_id
              AND host.organization_id = notice.organization_id
              AND host.edition_id = notice.edition_id
              AND host.account_id = notice.recipient_id AND host.state = 'confirmed'
              AND host.item_id = occurrence.programme_item_id
              AND chosen.occurrence_id = notice.occurrence_id
              AND chosen.approval_id = ANY(approval_ids)
        );
    WHEN 'work' THEN
        RETURN EXISTS (
            SELECT 1 FROM public.workforce_shiftcommitment work
            JOIN public.workforce_programmeshiftbindingrevision revision
              ON revision.demand_id = work.demand_id
             AND revision.organization_id = work.organization_id
             AND revision.edition_id = work.edition_id
            JOIN public.workforce_programmeshiftbinding binding
              ON binding.id = revision.binding_id
             AND binding.organization_id = revision.organization_id
             AND binding.edition_id = revision.edition_id
            WHERE work.id = notice.recipient_target_id
              AND work.organization_id = notice.organization_id
              AND work.edition_id = notice.edition_id
              AND work.account_id = notice.recipient_id
              AND work.status IN ('claimed', 'confirmed')
              AND binding.occurrence_id = notice.occurrence_id
              AND binding.item_id = occurrence.programme_item_id
        );
    WHEN 'room' THEN
        RETURN EXISTS (
            SELECT 1 FROM public.venues_editionspaceselection room
            JOIN public.workforce_department department
              ON department.id = room.responsible_department_id
             AND department.organization_id = room.organization_id
             AND department.edition_id = room.edition_id
            JOIN public.scheduling_schedulingplacementrevision placement
              ON placement.space_selection_id = room.id
             AND placement.organization_id = room.organization_id
             AND placement.edition_id = room.edition_id
            JOIN public.scheduling_schedulingreleaseapprovalplacement chosen
              ON chosen.placement_id = placement.id
             AND chosen.organization_id = placement.organization_id
             AND chosen.edition_id = placement.edition_id
            WHERE room.id = notice.recipient_target_id
              AND room.organization_id = notice.organization_id
              AND room.edition_id = notice.edition_id
              AND room.lifecycle = 'active' AND department.retired_at IS NULL
              AND chosen.occurrence_id = notice.occurrence_id
              AND chosen.approval_id = ANY(approval_ids)
        );
    WHEN 'department' THEN
        -- Actual affected room/work membership and its independently authorized
        -- owner versions remain mandatory in the application preview/command.
        RETURN EXISTS (
            SELECT 1 FROM public.workforce_department department
            WHERE department.id = notice.recipient_target_id
              AND department.organization_id = notice.organization_id
              AND department.edition_id = notice.edition_id
              AND department.retired_at IS NULL
        );
    WHEN 'edition' THEN
        RETURN notice.recipient_target_id = notice.edition_id;
    ELSE
        RETURN FALSE;
    END CASE;
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_scheduling_change_notice_graph()
RETURNS trigger AS $$
DECLARE
    body jsonb := to_jsonb(NEW);
    notice public.scheduling_schedulingchangenotice;
    review public.scheduling_schedulingchangenoticeevidence;
    expected_operation text;
    expected_version bigint;
    evidence_count bigint;
    last_sequence integer;
BEGIN
    IF TG_TABLE_NAME = 'scheduling_schedulingchangenotice' THEN
        SELECT * INTO notice FROM public.scheduling_schedulingchangenotice
        WHERE id = NEW.id;
        expected_operation := 'change_prepare';
        expected_version := 1;
        IF (SELECT count(*) FROM public.scheduling_schedulingchangenotice
            WHERE edition_id = notice.edition_id) > 65536 THEN
            RAISE EXCEPTION 'Programme notice history bound exceeded'
              USING ERRCODE = '23514';
        END IF;
    ELSE
        SELECT * INTO notice FROM public.scheduling_schedulingchangenotice
        WHERE id = NEW.notice_id;
        expected_operation := 'change_' || NEW.action;
        expected_version := NEW.sequence;
        SELECT count(*), max(sequence) INTO evidence_count, last_sequence
        FROM public.scheduling_schedulingchangenoticeevidence
        WHERE notice_id = notice.id;
        SELECT * INTO review FROM public.scheduling_schedulingchangenoticeevidence
        WHERE notice_id = notice.id AND action IN ('approve', 'reject');
        IF evidence_count NOT BETWEEN 1 AND 3
           OR last_sequence <> 1 + evidence_count OR review.id IS NULL
           OR review.sequence <> 2 OR review.actor_id = notice.actor_id
           OR review.organization_id <> notice.organization_id
           OR review.edition_id <> notice.edition_id
           OR (NEW.action IN ('handoff', 'acknowledge') AND review.action <> 'approve')
           OR (NEW.action = 'acknowledge' AND NEW.actor_id <> notice.recipient_id)
           OR review.occurred_at < notice.occurred_at
           OR NEW.occurred_at < review.occurred_at
           OR (review.action = 'reject' AND evidence_count <> 1) THEN
            RAISE EXCEPTION 'Programme notice facts require independent exact evidence'
              USING ERRCODE = '23514';
        END IF;
    END IF;
    IF notice.id IS NULL
       OR notice.organization_id <> NEW.organization_id
       OR notice.edition_id <> NEW.edition_id
       OR public.maru_scheduling_change_notice_source_valid(notice.id)
          IS DISTINCT FROM TRUE
       OR NOT EXISTS (
        SELECT 1 FROM public.scheduling_schedulingcommandreceipt receipt
        JOIN public.audit_auditevent audit
          ON audit.organization_id = receipt.organization_id
         AND audit.event_edition_id = receipt.edition_id
         AND audit.operation = 'scheduling.command.' || expected_operation
         AND audit.target_id = receipt.result_object_id
         AND audit.principal_id = receipt.actor_id
         AND audit.principal_kind = 'account'
         AND audit.occurred_at = receipt.occurred_at AND audit.outcome = 'allow'
         AND audit.correlation_id = receipt.correlation_id
         AND audit.idempotency_key_hash = encode(sha256(convert_to(
             receipt.idempotency_key::text, 'UTF8')), 'hex')
        JOIN public.effects_domainevent event ON event.causation_id = audit.id
         AND event.event_name = 'scheduling.change_notice.changed.v1'
         AND event.organization_id = receipt.organization_id
         AND event.event_edition_id = receipt.edition_id
         AND event.aggregate_type = 'scheduling.edition'
         AND event.aggregate_id = receipt.edition_id
         AND event.aggregate_version = receipt.control_version
         AND event.payload = jsonb_build_object('operation', expected_operation)
        JOIN public.audit_auditnativemutationwitness witness
          ON witness.audit_event_id = audit.id
         AND witness.transaction_stamp =
             public.maru_audit_current_native_transaction_stamp()
        WHERE receipt.id = (body->>'command_receipt_id')::uuid
          AND receipt.operation = expected_operation
          AND receipt.organization_id = NEW.organization_id
          AND receipt.edition_id = NEW.edition_id
          AND receipt.result_object_id = NEW.id
          AND receipt.resulting_version = expected_version
          AND receipt.actor_id = NEW.actor_id AND receipt.reason = NEW.reason
          AND receipt.occurred_at = NEW.occurred_at
       ) THEN
        RAISE EXCEPTION 'Programme notice requires its exact new native command'
          USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;
"""
FORWARD_SQL += (
    _graph
    + "\n"
    + "\n".join(
        f"""
CREATE TRIGGER sch_notice_{index}_row_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.scheduling_{table}
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_scheduling_row();
CREATE CONSTRAINT TRIGGER sch_notice_{index}_graph_guard
AFTER INSERT ON public.scheduling_{table}
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_scheduling_change_notice_graph();
CREATE TRIGGER sch_notice_{index}_no_truncate
BEFORE TRUNCATE ON public.scheduling_{table}
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_refuse_scheduling_truncate();
"""
        for index, table in enumerate(TABLES)
    )
)
FORWARD_SQL += "\n".join(
    f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC;" for signature in FUNCTIONS
)
REVERSE_SQL = (
    "\n".join(
        f"DROP TRIGGER sch_notice_{index}_{kind} ON public.scheduling_{table};"
        for index, table in enumerate(TABLES)
        for kind in ("row_guard", "graph_guard", "no_truncate")
    )
    + _old_graph
    + "\n".join(
        f"DROP FUNCTION public.{signature};" for signature in reversed(FUNCTIONS)
    )
)


def refuse_used_notice_boundary_downgrade(apps: Any, schema_editor: Any) -> None:
    """Preserve the existing whole-boundary fence before removing a successor."""
    _schema.refuse_used_notice_schema_downgrade(apps, schema_editor)
    _authority_fence.refuse_used_change_capability_downgrade(apps, schema_editor)
    _release_fence.refuse_used_release_boundary_downgrade(apps, schema_editor)


class Migration(migrations.Migration):
    """Retain native source/lifecycle/receipt guards without granting runtime writes."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("scheduling", "0021_change_notice_schema"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_used_notice_boundary_downgrade
        ),
    ]
