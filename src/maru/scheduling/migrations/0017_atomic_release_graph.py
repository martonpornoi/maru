"""Bind canonical artifacts and monotonic pointers to exact native release receipts."""

from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations

_review = import_module("maru.scheduling.migrations.0016_release_review_graph")
_old_graph = _review._graph  # noqa: SLF001 - frozen historical definition
_marker = "        CASE\n        WHEN NEW.operation = 'release_warning_acknowledge'"
if _old_graph.count(_marker) != 1:
    raise RuntimeError("The frozen Scheduling release review branch changed.")
_branches = """        CASE
        WHEN NEW.operation = 'release_publish' THEN
            SELECT to_jsonb(row) AS body INTO result_row
            FROM public.scheduling_schedulingrelease row
            WHERE row.id = NEW.result_object_id AND row.command_receipt_id = NEW.id
              AND row.pointer_version = NEW.resulting_version;
            expected_capability := 'scheduling.publish_release';
        WHEN NEW.operation = 'release_withdraw' THEN
            SELECT to_jsonb(row) AS body INTO result_row
            FROM public.scheduling_schedulingreleasewithdrawal row
            WHERE row.id = NEW.result_object_id AND row.command_receipt_id = NEW.id
              AND row.pointer_version = NEW.resulting_version;
            expected_capability := 'scheduling.withdraw_release';
        WHEN NEW.operation = 'release_warning_acknowledge'"""
_graph = _old_graph.replace(_marker, _branches)
_family = "('release_warning_acknowledge', 'release_approve')"
if _graph.count(_family) != 1:
    raise RuntimeError("The frozen Scheduling release event selection changed.")
_graph = _graph.replace(
    _family,
    "('release_warning_acknowledge', 'release_approve', "
    "'release_publish', 'release_withdraw')",
)

TABLES = (
    "schedulingrelease",
    "schedulingreleaseartifact",
    "schedulingreleasewithdrawal",
    "schedulingreleasepointer",
)
FORWARD_SQL = r"""
CREATE FUNCTION public.maru_scheduling_release_artifact_is_exact(selected uuid)
RETURNS boolean AS $$
DECLARE
    release public.scheduling_schedulingrelease;
    approval public.scheduling_schedulingreleaseapproval;
    artifact public.scheduling_schedulingreleaseartifact;
    selections jsonb;
    expected bytea;
BEGIN
    SELECT * INTO release FROM public.scheduling_schedulingrelease WHERE id = selected;
    SELECT * INTO approval FROM public.scheduling_schedulingreleaseapproval
    WHERE id = release.approval_id;
    SELECT * INTO artifact FROM public.scheduling_schedulingreleaseartifact
    WHERE release_id = selected AND contract = 'programme.release.canonical@1';
    IF release.id IS NULL OR approval.id IS NULL OR artifact.id IS NULL
       OR release.organization_id <> approval.organization_id
       OR release.edition_id <> approval.edition_id
       OR artifact.organization_id <> release.organization_id
       OR artifact.edition_id <> release.edition_id
       OR (SELECT count(*) FROM public.scheduling_schedulingreleaseartifact
           WHERE release_id = selected) <> 1
       OR (SELECT count(*) FROM public.scheduling_schedulingreleaseapprovalplacement
           WHERE approval_id = approval.id) <> approval.placement_count THEN
        RETURN FALSE;
    END IF;
    SELECT jsonb_agg(jsonb_build_object(
        'occurrence_id', occurrence_id, 'placement_id', placement_id,
        'public_rendition_id', public_rendition_id
    ) ORDER BY occurrence_id) INTO selections
    FROM public.scheduling_schedulingreleaseapprovalplacement
    WHERE approval_id = approval.id AND organization_id = approval.organization_id
      AND edition_id = approval.edition_id;
    IF jsonb_array_length(selections) IS DISTINCT FROM approval.placement_count
       OR approval.placement_count NOT BETWEEN 1 AND 2000 THEN RETURN FALSE; END IF;
    expected := convert_to(public.maru_scheduling_canonical_json(jsonb_build_object(
        'contract', 'programme.release.canonical@1', 'release_id', release.id,
        'approval_id', approval.id,
        'candidate_revision_id', approval.candidate_revision_id,
        'source_snapshot_digest', approval.source_snapshot_digest,
        'selections', selections
    )), 'UTF8');
    RETURN octet_length(expected) BETWEEN 1 AND 2097152
       AND artifact.payload = expected AND artifact.byte_length = octet_length(expected)
       AND artifact.sha256 = encode(sha256(expected), 'hex');
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_scheduling_release_pointer_guard()
RETURNS trigger AS $$
DECLARE
    release public.scheduling_schedulingrelease;
    withdrawal public.scheduling_schedulingreleasewithdrawal;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'release pointers retain their monotonic history'
          USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.events_eventedition edition
        JOIN public.organizations_conventionseries series
          ON series.id = edition.series_id
         AND series.organization_id = edition.organization_id
        WHERE edition.id = NEW.edition_id
          AND edition.organization_id = NEW.organization_id
          AND edition.lifecycle IN ('draft', 'preparing', 'ready', 'live')
        FOR UPDATE OF edition
    ) THEN
        RAISE EXCEPTION 'release pointers require a coherent writable edition'
          USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF to_jsonb(NEW) - ARRAY['version', 'active_release_id', 'command_receipt_id',
                                'updated_at'] IS DISTINCT FROM
           to_jsonb(OLD) - ARRAY['version', 'active_release_id', 'command_receipt_id',
                                'updated_at']
           OR NEW.version <> OLD.version + 1
           OR NEW.active_release_id IS NOT DISTINCT FROM OLD.active_release_id THEN
            RAISE EXCEPTION 'release pointer identity or consecutive transition changed'
              USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.version <> 1 OR NEW.active_release_id IS NULL THEN
        RAISE EXCEPTION 'release pointers start with the first complete publication'
          USING ERRCODE = '23514';
    END IF;
    IF NEW.active_release_id IS NOT NULL THEN
        SELECT * INTO release FROM public.scheduling_schedulingrelease
        WHERE id = NEW.active_release_id;
        IF release.id IS NULL OR release.organization_id <> NEW.organization_id
           OR release.edition_id <> NEW.edition_id
           OR release.pointer_version <> NEW.version
           OR release.command_receipt_id <> NEW.command_receipt_id
           OR release.previous_release_id IS DISTINCT FROM
               (CASE WHEN TG_OP = 'UPDATE' THEN OLD.active_release_id ELSE NULL END)
           OR public.maru_scheduling_release_artifact_is_exact(release.id)
               IS DISTINCT FROM TRUE THEN
            RAISE EXCEPTION 'release pointer requires its verified exact artifact'
              USING ERRCODE = '23514';
        END IF;
    ELSE
        SELECT * INTO withdrawal FROM public.scheduling_schedulingreleasewithdrawal
        WHERE command_receipt_id = NEW.command_receipt_id;
        IF withdrawal.id IS NULL OR withdrawal.organization_id <> NEW.organization_id
           OR withdrawal.edition_id <> NEW.edition_id
           OR withdrawal.release_id IS DISTINCT FROM OLD.active_release_id
           OR withdrawal.pointer_version <> NEW.version THEN
            RAISE EXCEPTION 'release pointer absence requires deliberate withdrawal'
              USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_scheduling_release_publication_graph()
RETURNS trigger AS $$
DECLARE
    body jsonb := to_jsonb(NEW);
    parent jsonb;
    expected_operation text;
    approval public.scheduling_schedulingreleaseapproval;
    release public.scheduling_schedulingrelease;
    receipt public.scheduling_schedulingcommandreceipt;
    prior_approval uuid;
    added bigint;
    changed bigint;
    removed bigint;
BEGIN
    IF TG_TABLE_NAME = 'scheduling_schedulingreleaseartifact' THEN
        SELECT to_jsonb(row) INTO parent FROM public.scheduling_schedulingrelease row
        WHERE id = NEW.release_id;
        expected_operation := 'release_publish';
    ELSIF TG_TABLE_NAME = 'scheduling_schedulingreleasepointer' THEN
        SELECT * INTO receipt FROM public.scheduling_schedulingcommandreceipt
        WHERE id = NEW.command_receipt_id;
        expected_operation := receipt.operation;
        IF expected_operation = 'release_publish' THEN
            SELECT to_jsonb(row) INTO parent
            FROM public.scheduling_schedulingrelease row
            WHERE id = receipt.result_object_id AND id = NEW.active_release_id;
        ELSIF expected_operation = 'release_withdraw'
              AND NEW.active_release_id IS NULL THEN
            SELECT to_jsonb(row) INTO parent
            FROM public.scheduling_schedulingreleasewithdrawal row
            WHERE id = receipt.result_object_id;
        END IF;
        IF (parent->>'pointer_version')::bigint IS DISTINCT FROM NEW.version THEN
            RAISE EXCEPTION 'release pointer lacks its exact publication history'
              USING ERRCODE = '23514';
        END IF;
    ELSE
        parent := body;
        expected_operation := CASE TG_TABLE_NAME
            WHEN 'scheduling_schedulingrelease' THEN 'release_publish'
            WHEN 'scheduling_schedulingreleasewithdrawal' THEN 'release_withdraw' END;
    END IF;
    IF parent IS NULL OR expected_operation IS NULL
       OR parent->>'organization_id' IS DISTINCT FROM body->>'organization_id'
       OR parent->>'edition_id' IS DISTINCT FROM body->>'edition_id'
       OR NOT EXISTS (
        SELECT 1 FROM public.scheduling_schedulingcommandreceipt command
        JOIN public.effects_domainevent event
          ON event.organization_id = command.organization_id
         AND event.event_edition_id = command.edition_id
         AND event.aggregate_type = 'scheduling.edition'
         AND event.aggregate_id = command.edition_id
         AND event.aggregate_version = command.control_version
         AND event.event_name = 'scheduling.release.changed.v1'
         AND event.payload = jsonb_build_object('operation', expected_operation)
        JOIN public.audit_auditnativemutationwitness witness
          ON witness.audit_event_id = event.causation_id
         AND witness.transaction_stamp =
             public.maru_audit_current_native_transaction_stamp()
        WHERE command.id::text = parent->>'command_receipt_id'
          AND command.operation = expected_operation
          AND command.organization_id::text = parent->>'organization_id'
          AND command.edition_id::text = parent->>'edition_id'
          AND command.result_object_id::text = parent->>'id'
          AND command.resulting_version = (parent->>'pointer_version')::bigint
          AND command.actor_id::text = parent->>'actor_id'
          AND command.reason = parent->>'reason'
          AND command.occurred_at = (parent->>'occurred_at')::timestamptz
    ) THEN
        RAISE EXCEPTION 'publication history requires its exact new native command'
          USING ERRCODE = '23514';
    END IF;
    IF TG_TABLE_NAME = 'scheduling_schedulingrelease' THEN
        SELECT * INTO approval FROM public.scheduling_schedulingreleaseapproval
        WHERE id = NEW.approval_id;
        IF approval.id IS NULL OR approval.actor_id = NEW.actor_id
           OR approval.organization_id <> NEW.organization_id
           OR approval.edition_id <> NEW.edition_id
           OR NOT EXISTS (SELECT 1 FROM public.identity_account
               WHERE id = approval.actor_id AND is_active
                 AND email_verified_at IS NOT NULL
                 AND account_kind = 'person') THEN
            RAISE EXCEPTION 'publication requires a distinct current approver'
              USING ERRCODE = '23514';
        END IF;
        PERFORM public.maru_scheduling_validate_release_approval(approval.id);
        IF public.maru_scheduling_release_artifact_is_exact(NEW.id)
              IS DISTINCT FROM TRUE
           OR NOT EXISTS (
            SELECT 1 FROM public.scheduling_schedulingreleasepointer pointer
            WHERE pointer.edition_id = NEW.edition_id
              AND pointer.organization_id = NEW.organization_id
              AND pointer.version >= NEW.pointer_version
           ) THEN
            RAISE EXCEPTION 'publication requires its complete artifact and pointer'
              USING ERRCODE = '23514';
        END IF;
        IF NEW.previous_release_id IS NOT NULL THEN
            SELECT * INTO release FROM public.scheduling_schedulingrelease
            WHERE id = NEW.previous_release_id;
            IF release.id IS NULL OR release.organization_id <> NEW.organization_id
               OR release.edition_id <> NEW.edition_id
               OR release.pointer_version <> NEW.pointer_version - 1 THEN
                RAISE EXCEPTION 'publication predecessor is not the prior release'
                  USING ERRCODE = '23514';
            END IF;
            prior_approval := release.approval_id;
        END IF;
        SELECT count(*) FILTER (WHERE previous.occurrence_id IS NULL),
            count(*) FILTER (WHERE next.occurrence_id IS NOT NULL
                AND previous.occurrence_id IS NOT NULL
                AND (next.placement_id, next.public_rendition_id) IS DISTINCT FROM
                    (previous.placement_id, previous.public_rendition_id)),
            count(*) FILTER (WHERE next.occurrence_id IS NULL)
        INTO added, changed, removed
        FROM (SELECT * FROM public.scheduling_schedulingreleaseapprovalplacement
              WHERE approval_id = NEW.approval_id) next
        FULL JOIN (SELECT * FROM public.scheduling_schedulingreleaseapprovalplacement
                   WHERE approval_id = prior_approval) previous
          ON previous.occurrence_id = next.occurrence_id;
        IF (added, changed, removed) IS DISTINCT FROM
           (NEW.added_count::bigint, NEW.changed_count::bigint,
            NEW.removed_count::bigint) THEN
            RAISE EXCEPTION 'publication change counts differ from exact choices'
              USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'scheduling_schedulingreleasewithdrawal' THEN
        IF NOT EXISTS (
            SELECT 1 FROM public.scheduling_schedulingrelease original
            JOIN public.scheduling_schedulingreleasepointer pointer
              ON pointer.organization_id = original.organization_id
             AND pointer.edition_id = original.edition_id
            WHERE original.id = NEW.release_id
              AND original.organization_id = NEW.organization_id
              AND original.edition_id = NEW.edition_id
              AND original.pointer_version + 1 = NEW.pointer_version
              AND pointer.version >= NEW.pointer_version
        ) THEN
            RAISE EXCEPTION 'release withdrawal lacks its exact active predecessor'
              USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;
"""
FUNCTIONS = (
    "maru_scheduling_release_artifact_is_exact(uuid)",
    "maru_scheduling_release_pointer_guard()",
    "maru_scheduling_release_publication_graph()",
)
FORWARD_SQL += (
    _graph
    + "\n"
    + "\n".join(
        f"""
CREATE TRIGGER sch_publication_{index}_row_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.scheduling_{table}
FOR EACH ROW EXECUTE FUNCTION public.{
            "maru_scheduling_release_pointer_guard"
            if table == "schedulingreleasepointer"
            else "maru_guard_scheduling_row"
        }();
CREATE CONSTRAINT TRIGGER sch_publication_{index}_graph_guard
AFTER INSERT OR UPDATE ON public.scheduling_{table}
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_scheduling_release_publication_graph();
CREATE TRIGGER sch_publication_{index}_no_truncate
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
        f"DROP TRIGGER sch_publication_{index}_{kind} ON public.scheduling_{table};"
        for index, table in enumerate(TABLES)
        for kind in ("row_guard", "graph_guard", "no_truncate")
    )
    + _old_graph
    + "\n".join(
        f"DROP FUNCTION public.{signature};" for signature in reversed(FUNCTIONS)
    )
)


def refuse_used_publication_downgrade(apps: Any, schema_editor: Any) -> None:
    """Retain published history and the artifact-before-pointer boundary."""
    for name in ("SchedulingRelease", "SchedulingReleasePointer"):
        model = apps.get_model("scheduling", name)
        schema_editor.execute(
            "LOCK TABLE "
            + schema_editor.quote_name(model._meta.db_table)  # noqa: SLF001
            + " IN ACCESS EXCLUSIVE MODE"
        )
        if model.objects.exists():
            raise RuntimeError("Programme publication history exists; fix forward.")


class Migration(migrations.Migration):
    """Keep publication dormant and atomic without activating runtime writers."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("scheduling", "0016_release_review_graph"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_used_publication_downgrade
        ),
    ]
