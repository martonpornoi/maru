"""Protect exact immutable release-review membership and native command evidence."""

from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations

_planning = import_module("maru.scheduling.migrations.0005_integrity_guards")
_start = _planning.FORWARD_SQL.index(
    "CREATE FUNCTION public.maru_validate_scheduling_graph()"
)
_end_marker = "SET search_path = pg_catalog, public, pg_temp;"
_end = _planning.FORWARD_SQL.index(_end_marker, _start) + len(_end_marker)
_old_graph = _planning.FORWARD_SQL[_start:_end].replace(
    "CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1
)
_receipt_marker = "        CASE\n        WHEN NEW.operation IN ('day_create'"
if _old_graph.count(_receipt_marker) != 1:
    raise RuntimeError("The frozen Scheduling receipt branch changed.")
_release_receipts = """        CASE
        WHEN NEW.operation = 'release_warning_acknowledge'
             AND NEW.resulting_version = 1 THEN
            SELECT to_jsonb(row) AS body INTO result_row
            FROM public.scheduling_schedulingreleasewarningacknowledgement row
            WHERE row.id = NEW.result_object_id AND row.command_receipt_id = NEW.id;
            expected_capability := 'scheduling.acknowledge_release_warnings';
        WHEN NEW.operation = 'release_approve' AND NEW.resulting_version = 1 THEN
            SELECT to_jsonb(row) AS body INTO result_row
            FROM public.scheduling_schedulingreleaseapproval row
            WHERE row.id = NEW.result_object_id AND row.command_receipt_id = NEW.id;
            expected_capability := 'scheduling.approve_release';
        WHEN NEW.operation IN ('day_create'"""
_graph = _old_graph.replace(_receipt_marker, _release_receipts)
_event_marker = "event.event_name = 'scheduling.planning.changed.v1'"
if _graph.count(_event_marker) != 1:
    raise RuntimeError("The frozen Scheduling event family changed.")
_graph = _graph.replace(
    _event_marker,
    "event.event_name = CASE WHEN NEW.operation IN "
    "('release_warning_acknowledge', 'release_approve') "
    "THEN 'scheduling.release.changed.v1' ELSE 'scheduling.planning.changed.v1' END",
)

TABLES = (
    "schedulingreleasewarningacknowledgement",
    "schedulingreleaseapproval",
    "schedulingreleaseapprovalplacement",
    "schedulingreleaseapprovaldependency",
)
FORWARD_SQL = r"""
CREATE FUNCTION public.maru_scheduling_release_independent(
    selected_revision uuid, reviewer uuid, organization uuid, edition uuid
) RETURNS boolean AS $$
DECLARE
    head record;
    first_row record;
    seen uuid[] := ARRAY[]::uuid[];
    history uuid[] := ARRAY[]::uuid[];
    segment uuid[];
    authors uuid[];
BEGIN
    LOOP
        SELECT revision.* INTO head
        FROM public.scheduling_schedulingcandidaterevision revision
        JOIN public.scheduling_schedulingcandidate candidate
          ON candidate.id = revision.candidate_id
         AND candidate.organization_id = organization AND candidate.edition_id = edition
        WHERE revision.id = selected_revision
          AND revision.organization_id = organization AND revision.edition_id = edition
          AND candidate.aggregate_version >= revision.sequence;
        IF NOT FOUND OR head.candidate_id = ANY(seen) OR cardinality(seen) >= 100
           OR cardinality(history) + head.sequence > 10000 THEN
            RETURN FALSE;
        END IF;
        seen := array_append(seen, head.candidate_id);
        SELECT array_agg(id ORDER BY sequence), array_agg(actor_id ORDER BY sequence)
          INTO segment, authors
        FROM public.scheduling_schedulingcandidaterevision
        WHERE candidate_id = head.candidate_id AND sequence <= head.sequence
          AND organization_id = organization AND edition_id = edition;
        IF cardinality(segment) IS DISTINCT FROM head.sequence
           OR reviewer = ANY(authors) THEN RETURN FALSE; END IF;
        history := history || segment;
        SELECT * INTO first_row FROM public.scheduling_schedulingcandidaterevision
        WHERE id = segment[1];
        IF first_row.operation = 'candidate_create'
           AND first_row.source_revision_id IS NULL THEN EXIT; END IF;
        IF first_row.operation IS DISTINCT FROM 'candidate_copy'
           OR first_row.source_revision_id IS NULL THEN RETURN FALSE; END IF;
        selected_revision := first_row.source_revision_id;
    END LOOP;
    RETURN TRUE;
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_scheduling_validate_release_approval(selected uuid)
RETURNS void AS $$
DECLARE
    approval public.scheduling_schedulingreleaseapproval;
    candidate record;
BEGIN
    SELECT * INTO approval FROM public.scheduling_schedulingreleaseapproval
    WHERE id = selected;
    SELECT revision.*, parent.aggregate_version, parent.lifecycle INTO candidate
    FROM public.scheduling_schedulingcandidaterevision revision
    JOIN public.scheduling_schedulingcandidate parent
      ON parent.id = revision.candidate_id
    WHERE revision.id = approval.candidate_revision_id
      AND parent.organization_id = approval.organization_id
      AND parent.edition_id = approval.edition_id;
    IF approval.id IS NULL OR candidate.id IS NULL
       OR candidate.organization_id IS DISTINCT FROM approval.organization_id
       OR candidate.edition_id IS DISTINCT FROM approval.edition_id
       OR candidate.lifecycle IS DISTINCT FROM 'draft'
       OR candidate.sequence IS DISTINCT FROM candidate.aggregate_version
       OR candidate.manifest_digest IS DISTINCT FROM approval.manifest_digest
       OR candidate.placement_count IS DISTINCT FROM approval.placement_count
       OR approval.eligibility_policy <> 'scheduling.release-eligibility@1'
       OR public.maru_scheduling_release_independent(
           candidate.id, approval.actor_id, approval.organization_id,
           approval.edition_id
       ) IS DISTINCT FROM TRUE THEN
        RAISE EXCEPTION 'release approval requires an independent current manifest'
          USING ERRCODE = '23514';
    END IF;
    IF (SELECT count(*) FROM public.scheduling_schedulingreleaseapprovalplacement
        WHERE approval_id = selected) <> approval.placement_count
       OR EXISTS (
        SELECT 1 FROM public.scheduling_schedulingreleaseapprovalplacement chosen
        LEFT JOIN public.scheduling_schedulingcandidatemember member
          ON member.revision_id = candidate.id
         AND member.placement_id = chosen.placement_id
         AND member.occurrence_id = chosen.occurrence_id
         AND member.organization_id = approval.organization_id
         AND member.edition_id = approval.edition_id
        JOIN public.scheduling_schedulingoccurrence occurrence
          ON occurrence.id = chosen.occurrence_id
        JOIN public.programme_programmepublicrendition copy
          ON copy.id = chosen.public_rendition_id
        WHERE chosen.approval_id = selected AND (
            member.id IS NULL OR chosen.organization_id <> approval.organization_id
            OR chosen.edition_id <> approval.edition_id
            OR copy.organization_id <> approval.organization_id
            OR copy.edition_id <> approval.edition_id
            OR copy.item_id <> occurrence.programme_item_id
            OR copy.rendition_number <> (
                SELECT max(rendition_number)
                FROM public.programme_programmepublicrendition
                WHERE item_id = occurrence.programme_item_id
            )
        )
    ) THEN
        RAISE EXCEPTION 'release approval requires exact placements and current copies'
          USING ERRCODE = '23514';
    END IF;
    IF (SELECT count(*) FROM public.scheduling_schedulingreleaseapprovaldependency
        WHERE approval_id = selected) <> approval.dependency_count
       OR EXISTS (
        SELECT 1 FROM public.scheduling_schedulingreleaseapprovaldependency capture
        JOIN public.scheduling_schedulingreleasedependencykey dependency
          ON dependency.id = capture.dependency_id
        LEFT JOIN public.scheduling_schedulingreleaseapprovalplacement placement
          ON placement.id = capture.approval_placement_id
        WHERE capture.approval_id = selected AND (
            capture.organization_id <> approval.organization_id
            OR capture.edition_id <> approval.edition_id
            OR capture.captured_generation <> dependency.generation
            OR (dependency.organization_id IS NOT NULL
                AND dependency.organization_id <> approval.organization_id)
            OR (dependency.edition_id IS NOT NULL
                AND dependency.edition_id <> approval.edition_id)
            OR (capture.approval_placement_id IS NOT NULL
                AND placement.approval_id IS DISTINCT FROM selected)
        )
    ) OR EXISTS (
        WITH expected AS (
            SELECT * FROM public.maru_scheduling_expected_release_dependencies(
                candidate.id, approval.actor_id, approval.organization_id,
                approval.edition_id
            )
        ), actual AS (
            SELECT dependency.kind::text, dependency.source_id, placement.placement_id,
                capture.horizon::text, capture.operational_ends_at
            FROM public.scheduling_schedulingreleaseapprovaldependency capture
            JOIN public.scheduling_schedulingreleasedependencykey dependency
              ON dependency.id = capture.dependency_id
            LEFT JOIN public.scheduling_schedulingreleaseapprovalplacement placement
              ON placement.id = capture.approval_placement_id
            WHERE capture.approval_id = selected
        )
        (SELECT * FROM expected EXCEPT ALL SELECT * FROM actual)
        UNION ALL
        (SELECT * FROM actual EXCEPT ALL SELECT * FROM expected)
    ) THEN
        RAISE EXCEPTION 'release approval requires complete current native dependencies'
          USING ERRCODE = '23514';
    END IF;
    IF cardinality(approval.warning_ids) > 10000
       OR cardinality(approval.warning_ids) <> (
           SELECT count(DISTINCT warning.finding_fingerprint)
           FROM public.scheduling_schedulingreleasewarningacknowledgement warning
           WHERE warning.id = ANY(approval.warning_ids)
             AND warning.organization_id = approval.organization_id
             AND warning.edition_id = approval.edition_id
             AND warning.candidate_revision_id = candidate.id
             AND warning.source_snapshot_digest = approval.source_snapshot_digest
       ) THEN
        RAISE EXCEPTION 'release approval warning selection is not exact and complete'
          USING ERRCODE = '23514';
    END IF;
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_scheduling_release_review_graph()
RETURNS trigger AS $$
DECLARE
    body jsonb := to_jsonb(NEW);
    parent jsonb;
    receipt_id uuid;
    expected_operation text;
    approval_id uuid;
BEGIN
    IF TG_TABLE_NAME IN ('scheduling_schedulingreleaseapprovalplacement',
                         'scheduling_schedulingreleaseapprovaldependency') THEN
        approval_id := (body->>'approval_id')::uuid;
        SELECT to_jsonb(row) INTO parent
        FROM public.scheduling_schedulingreleaseapproval row WHERE id = approval_id;
        expected_operation := 'release_approve';
    ELSE
        parent := body;
        expected_operation := CASE TG_TABLE_NAME
            WHEN 'scheduling_schedulingreleaseapproval' THEN 'release_approve'
            WHEN 'scheduling_schedulingreleasewarningacknowledgement'
                THEN 'release_warning_acknowledge' END;
    END IF;
    receipt_id := (parent->>'command_receipt_id')::uuid;
    IF parent IS NULL OR expected_operation IS NULL
       OR parent->>'organization_id' IS DISTINCT FROM body->>'organization_id'
       OR parent->>'edition_id' IS DISTINCT FROM body->>'edition_id'
       OR parent->>'source_snapshot_digest' !~ '^[0-9a-f]{64}$'
       OR NOT EXISTS (
        SELECT 1 FROM public.scheduling_schedulingcommandreceipt receipt
        JOIN public.audit_auditevent audit
          ON audit.organization_id = receipt.organization_id
         AND audit.event_edition_id = receipt.edition_id
         AND audit.operation = 'scheduling.command.' || expected_operation
         AND audit.target_id = receipt.result_object_id
         AND audit.principal_id = receipt.actor_id
         AND audit.occurred_at = receipt.occurred_at AND audit.outcome = 'allow'
         AND audit.correlation_id = receipt.correlation_id
         AND audit.idempotency_key_hash = encode(sha256(convert_to(
             receipt.idempotency_key::text, 'UTF8')), 'hex')
        JOIN public.effects_domainevent event ON event.causation_id = audit.id
         AND event.event_name = 'scheduling.release.changed.v1'
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
        WHERE receipt.id = receipt_id AND receipt.operation = expected_operation
          AND receipt.organization_id::text = parent->>'organization_id'
          AND receipt.edition_id::text = parent->>'edition_id'
          AND receipt.result_object_id::text = parent->>'id'
          AND receipt.resulting_version = 1
          AND receipt.actor_id::text = parent->>'actor_id'
          AND receipt.reason = parent->>'reason'
          AND receipt.occurred_at = (parent->>'occurred_at')::timestamptz
    ) THEN
        RAISE EXCEPTION 'release review rows require their exact new native command'
          USING ERRCODE = '23514';
    END IF;
    IF TG_TABLE_NAME = 'scheduling_schedulingreleaseapproval' THEN
        PERFORM public.maru_scheduling_validate_release_approval(NEW.id);
    ELSIF TG_TABLE_NAME = 'scheduling_schedulingreleasewarningacknowledgement' THEN
        IF (NEW.check_code, NEW.finding_code) NOT IN (
            ('hosts', 'host_outside_preference'),
            ('physical_constraints', 'turnover_overlap')
        ) OR NEW.occurrence_id IS NULL
           OR NOT EXISTS (
            SELECT 1 FROM public.scheduling_schedulingcandidatemember member
            JOIN public.scheduling_schedulingcandidaterevision revision
              ON revision.id = member.revision_id
            JOIN public.scheduling_schedulingcandidate candidate
              ON candidate.id = revision.candidate_id
            WHERE member.revision_id = NEW.candidate_revision_id
              AND member.occurrence_id = NEW.occurrence_id
              AND candidate.lifecycle = 'draft'
              AND candidate.aggregate_version = revision.sequence
           ) OR NEW.finding_fingerprint IS DISTINCT FROM encode(sha256(convert_to(
               public.maru_scheduling_canonical_json(jsonb_build_object(
                   'snapshot', NEW.source_snapshot_digest,
                   'finding', jsonb_build_object(
                       'check', NEW.check_code, 'code', NEW.finding_code,
                       'severity', 'warning', 'occurrence_id', NEW.occurrence_id,
                       'other_occurrence_id', NEW.other_occurrence_id
                   )
               )), 'UTF8')), 'hex') THEN
            RAISE EXCEPTION 'release acknowledgement requires a closed exact warning'
              USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;
"""
FUNCTIONS = (
    "maru_scheduling_release_independent(uuid,uuid,uuid,uuid)",
    "maru_scheduling_validate_release_approval(uuid)",
    "maru_scheduling_release_review_graph()",
)
FORWARD_SQL += (
    _graph
    + "\n"
    + "\n".join(
        f"""
CREATE TRIGGER sch_review_{index}_row_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.scheduling_{table}
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_scheduling_row();
CREATE CONSTRAINT TRIGGER sch_review_{index}_graph_guard
AFTER INSERT ON public.scheduling_{table}
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_scheduling_release_review_graph();
CREATE TRIGGER sch_review_{index}_no_truncate
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
        f"DROP TRIGGER sch_review_{index}_{kind} ON public.scheduling_{table};"
        for index, table in enumerate(TABLES)
        for kind in ("row_guard", "graph_guard", "no_truncate")
    )
    + _old_graph
    + "\n".join(
        f"DROP FUNCTION public.{signature};" for signature in reversed(FUNCTIONS)
    )
)


def refuse_used_review_graph_downgrade(apps: Any, schema_editor: Any) -> None:
    """Retain review containment once either independent evidence stream is used."""
    for name in (
        "SchedulingReleaseApproval",
        "SchedulingReleaseWarningAcknowledgement",
    ):
        model = apps.get_model("scheduling", name)
        schema_editor.execute(
            "LOCK TABLE "
            + schema_editor.quote_name(model._meta.db_table)  # noqa: SLF001
            + " IN ACCESS EXCLUSIVE MODE"
        )
        if model.objects.exists():
            raise RuntimeError("Retained release review evidence exists; fix forward.")


class Migration(migrations.Migration):
    """Keep dormant review graph immutable without granting runtime DML."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("scheduling", "0015_release_dependency_membership"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_used_review_graph_downgrade
        ),
    ]
