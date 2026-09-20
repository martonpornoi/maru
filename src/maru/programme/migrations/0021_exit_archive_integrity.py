"""Guard requester-bound tasks, immutable phase evidence and expiring ZIP custody."""

from importlib import import_module
from typing import ClassVar

from django.db import migrations
from django.db.migrations.operations.base import Operation

_schema = import_module("maru.programme.migrations.0020_exit_archive_records")
UNUSED_PREFLIGHT = _schema.UNUSED_PREFLIGHT

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_programme_archive_task_guard() RETURNS trigger AS $$
DECLARE
    observed timestamptz := clock_timestamp();
    retained_count bigint;
    active_count bigint;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Programme archive task evidence is retained' USING ERRCODE =
        '23514';
    END IF;
    IF NEW.id = '00000000-0000-0000-0000-000000000000'::uuid
       OR NEW.request_key = '00000000-0000-0000-0000-000000000000'::uuid
       OR NEW.contract <> 'programme.exit-archive@1'
       OR NEW.expires_at <> NEW.requested_at + interval '24 hours'
       OR NEW.requested_at > observed
       OR NOT EXISTS (
           SELECT 1 FROM public.events_eventedition edition
           JOIN public.organizations_conventionseries series ON series.id =
        edition.series_id
           WHERE edition.id = NEW.edition_id
             AND edition.organization_id = NEW.organization_id
             AND series.organization_id = NEW.organization_id
       ) THEN
        RAISE EXCEPTION 'Programme archive scope or request is incoherent' USING
        ERRCODE = '23514';
    END IF;
    IF (NEW.state = 'failed' AND NEW.failure_code NOT IN (
            'source_unavailable', 'source_changed', 'integrity_failed',
            'resource_limit', 'worker_failed', 'worker_deadline'))
       OR (NEW.state <> 'failed' AND NEW.failure_code <> '')
       OR (NEW.state IN ('queued', 'running') AND NEW.finished_at IS NOT NULL)
       OR (NEW.state NOT IN ('queued', 'running') AND
           (NEW.finished_at IS NULL OR NEW.finished_at < NEW.requested_at
            OR NEW.finished_at > observed))
       OR (NEW.state = 'expired' AND NEW.expires_at > observed)
       OR (NEW.state IN ('running', 'ready') AND NEW.expires_at <= observed)
       OR ((NEW.started_at IS NULL) <> (NEW.generation_correlation_id IS NULL))
       OR (NEW.started_at IS NOT NULL AND
           (NEW.started_at < NEW.requested_at OR NEW.started_at > observed
            OR NEW.generation_correlation_id =
        '00000000-0000-0000-0000-000000000000'::uuid))
       OR (NEW.state IN ('running', 'ready') AND NEW.started_at IS NULL) THEN
        RAISE EXCEPTION 'Programme archive phase or clock is incoherent' USING ERRCODE
        = '23514';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.state <> 'queued' OR NEW.version <> 1 OR NEW.started_at IS NOT NULL
           OR NEW.expires_at <= observed OR NEW.requested_at < transaction_timestamp()
           OR NEW.source_digest <> '' OR NEW.artifact_digest <> '' OR NEW.chunk_root
        <> ''
           OR NEW.artifact_bytes <> 0 OR NEW.chunk_count <> 0 THEN
            RAISE EXCEPTION 'Programme archive requests start empty and queued' USING
        ERRCODE = '23514';
        END IF;
        IF NEW.previous_task_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.programme_programmearchivetask previous
            WHERE previous.id = NEW.previous_task_id AND previous.actor_id =
        NEW.actor_id
              AND previous.organization_id = NEW.organization_id AND
        previous.edition_id = NEW.edition_id
              AND previous.state IN ('failed', 'cancelled', 'expired')
        ) THEN
            RAISE EXCEPTION 'Programme archive replacement source is unavailable'
        USING ERRCODE = '23514';
        END IF;
        PERFORM pg_advisory_xact_lock(hashtextextended('programme:exit:capacity@1', 0));
        SELECT count(*) INTO retained_count FROM public.programme_programmearchivetask
          WHERE edition_id = NEW.edition_id;
        SELECT count(*) INTO active_count FROM public.programme_programmearchivetask
          WHERE state IN ('queued', 'running', 'ready') AND expires_at > observed;
        IF retained_count >= 1000 OR active_count >= 4 OR EXISTS (
            SELECT 1 FROM public.programme_programmearchivetask
            WHERE edition_id = NEW.edition_id AND state IN ('queued', 'running',
        'ready')
              AND expires_at > observed
        ) THEN
            RAISE EXCEPTION 'Programme archive capacity is unavailable' USING ERRCODE
        = '23514';
        END IF;
    ELSE
        IF ROW(NEW.id, NEW.organization_id, NEW.edition_id, NEW.actor_id,
               NEW.request_key, NEW.contract, NEW.previous_task_id,
               NEW.requested_at, NEW.expires_at, NEW.created_at)
           IS DISTINCT FROM ROW(OLD.id, OLD.organization_id, OLD.edition_id,
        OLD.actor_id,
               OLD.request_key, OLD.contract, OLD.previous_task_id,
               OLD.requested_at, OLD.expires_at, OLD.created_at)
           OR NEW.version <> OLD.version + 1
           OR NOT (
               (OLD.state = 'queued' AND NEW.state IN ('running', 'failed',
        'cancelled', 'expired'))
               OR (OLD.state = 'running' AND NEW.state IN ('ready', 'failed',
        'cancelled', 'expired'))
               OR (OLD.state = 'ready' AND NEW.state IN ('failed', 'cancelled',
        'expired'))
           ) THEN
            RAISE EXCEPTION 'Programme archive transition is unavailable' USING
        ERRCODE = '23514';
        END IF;
        IF OLD.state <> 'queued' AND ROW(NEW.started_at, NEW.generation_correlation_id)
           IS DISTINCT FROM ROW(OLD.started_at, OLD.generation_correlation_id) THEN
            RAISE EXCEPTION 'Programme archive generation identity is immutable' USING
        ERRCODE = '23514';
        END IF;
        IF OLD.state = 'queued' AND NEW.state <> 'running'
           AND (NEW.started_at IS NOT NULL OR NEW.generation_correlation_id IS NOT
        NULL) THEN
            RAISE EXCEPTION 'Unclaimed archive cannot invent generation identity'
        USING ERRCODE = '23514';
        END IF;
        IF NOT (OLD.state = 'running' AND NEW.state = 'ready') AND
           ROW(NEW.source_digest, NEW.artifact_digest, NEW.chunk_root,
        NEW.artifact_bytes, NEW.chunk_count)
           IS DISTINCT FROM
           ROW(OLD.source_digest, OLD.artifact_digest, OLD.chunk_root,
        OLD.artifact_bytes, OLD.chunk_count) THEN
            RAISE EXCEPTION
        'Programme archive byte identity changes only at completion' USING ERRCODE =
        '23514';
        END IF;
    END IF;
    IF NEW.state = 'ready' AND (
        NEW.source_digest !~ '^[0-9a-f]{64}$' OR NEW.artifact_digest !~ '^[0-9a-f]{64}$'
        OR NEW.chunk_root !~ '^[0-9a-f]{64}$' OR NEW.artifact_bytes < 1 OR
        NEW.chunk_count < 1
    ) THEN
        RAISE EXCEPTION 'Programme archive completion identity is invalid' USING
        ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_programme_archive_event_guard() RETURNS trigger AS $$
DECLARE
    task public.programme_programmearchivetask%ROWTYPE;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Programme archive lifecycle evidence is append-only' USING
        ERRCODE = '23514';
    END IF;
    SELECT * INTO task FROM public.programme_programmearchivetask WHERE id =
        NEW.task_id;
    IF NOT FOUND OR NEW.version > task.version OR NEW.occurred_at > clock_timestamp()
       OR NEW.occurred_at < transaction_timestamp()
       OR NEW.correlation_id = '00000000-0000-0000-0000-000000000000'::uuid
       OR (NEW.version = 1 AND (NEW.state <> 'queued' OR NEW.occurred_at <>
        task.requested_at))
       OR (NEW.version > 1 AND NOT EXISTS (
           SELECT 1 FROM public.programme_programmearchivetaskevent prior
           WHERE prior.task_id = NEW.task_id AND prior.version = NEW.version - 1
             AND prior.occurred_at <= NEW.occurred_at
             AND ((prior.state = 'queued' AND NEW.state IN ('running', 'failed',
        'cancelled', 'expired'))
               OR (prior.state = 'running' AND NEW.state IN ('ready', 'failed',
        'cancelled', 'expired'))
               OR (prior.state = 'ready' AND NEW.state IN ('failed', 'cancelled',
        'expired')))
       )) OR NOT EXISTS (
           SELECT 1 FROM public.audit_auditevent audit
           JOIN public.audit_auditnativemutationwitness witness ON
        witness.audit_event_id = audit.id
           WHERE audit.id = NEW.audit_event_id AND audit.principal_kind = 'account'
             AND audit.principal_id = task.actor_id AND audit.organization_id =
        task.organization_id
             AND audit.event_edition_id = task.edition_id
             AND audit.capability_code = 'programme.export_archive'
             AND audit.operation = 'programme.exit.task.' || NEW.state
             AND audit.target_type = 'programme.archive_task' AND audit.target_id =
        task.id
             AND audit.outcome = 'allow' AND audit.correlation_id = NEW.correlation_id
             AND audit.occurred_at = NEW.occurred_at AND 'audit' =
        ANY(audit.obligations)
             AND audit.source_channel IN ('programme-exit', 'programme-exit-worker')
             AND witness.transaction_stamp =
        public.maru_audit_current_native_transaction_stamp()
       ) THEN
        RAISE EXCEPTION
        'Programme archive lifecycle lacks exact current audit evidence' USING ERRCODE
        = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_programme_archive_task_evidence() RETURNS trigger AS $$
DECLARE
    actual_count bigint;
    actual_size bigint;
    first_sequence integer;
    last_sequence integer;
    actual_root text;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.programme_programmearchivetaskevent event
        JOIN public.audit_auditnativemutationwitness witness ON witness.audit_event_id
        = event.audit_event_id
        WHERE event.task_id = NEW.id AND event.version = NEW.version AND event.state =
        NEW.state
          AND event.failure_code = NEW.failure_code
          AND event.occurred_at = CASE WHEN NEW.state = 'queued' THEN NEW.requested_at
              WHEN NEW.state = 'running' THEN NEW.started_at ELSE NEW.finished_at END
          AND witness.transaction_stamp =
        public.maru_audit_current_native_transaction_stamp()
    ) THEN
        RAISE EXCEPTION
        'Programme archive transition lacks its new lifecycle evidence' USING ERRCODE
        = '23514';
    END IF;
    SELECT count(*), coalesce(sum(size_bytes), 0), min(sequence), max(sequence),
        encode(sha256(convert_to(coalesce(string_agg(
            sequence::text || ':' || size_bytes::text || ':' || sha256 || E'\n',
            '' ORDER BY sequence), ''), 'UTF8')), 'hex')
      INTO actual_count, actual_size, first_sequence, last_sequence, actual_root
      FROM public.programme_programmearchivechunk WHERE task_id = NEW.id;
    IF NEW.state = 'ready' THEN
        IF actual_count <> NEW.chunk_count OR actual_size <> NEW.artifact_bytes
           OR first_sequence <> 1 OR last_sequence <> actual_count OR actual_root <>
        NEW.chunk_root
           OR EXISTS (SELECT 1 FROM public.programme_programmearchivechunk
                      WHERE task_id = NEW.id AND sequence < last_sequence AND
        size_bytes <> 1048576) THEN
            RAISE EXCEPTION 'Programme archive chunks do not prove complete custody'
        USING ERRCODE = '23514';
        END IF;
    ELSIF actual_count <> 0 THEN
        RAISE EXCEPTION 'Non-ready Programme task cannot retain derived chunks' USING
        ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_programme_archive_chunk_guard() RETURNS trigger AS $$
DECLARE
    task public.programme_programmearchivetask%ROWTYPE;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'Programme archive chunks are immutable' USING ERRCODE =
        '23514';
    END IF;
    SELECT * INTO task FROM public.programme_programmearchivetask
      WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.task_id ELSE NEW.task_id END FOR
        UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Programme archive chunk task is unavailable' USING ERRCODE =
        '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN
        IF task.state NOT IN ('failed', 'cancelled', 'expired') THEN
            RAISE EXCEPTION 'Programme archive bytes require terminal disposal' USING
        ERRCODE = '23514';
        END IF;
        RETURN OLD;
    END IF;
    IF task.state <> 'running' OR task.expires_at <= clock_timestamp()
       OR NEW.sequence < 1 OR NEW.sequence > 1026
       OR NEW.size_bytes < 1 OR NEW.size_bytes > 1048576
       OR octet_length(NEW.payload) <> NEW.size_bytes
       OR encode(sha256(NEW.payload), 'hex') <> NEW.sha256 THEN
        RAISE EXCEPTION 'Programme archive chunk identity is invalid' USING ERRCODE =
        '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_programme_archive_chunk_evidence() RETURNS trigger AS $$
DECLARE
    task public.programme_programmearchivetask%ROWTYPE;
BEGIN
    SELECT * INTO task FROM public.programme_programmearchivetask
      WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.task_id ELSE NEW.task_id END;
    IF NOT FOUND OR (TG_OP = 'INSERT' AND task.state <> 'ready')
       OR (TG_OP = 'DELETE' AND task.state NOT IN ('failed', 'cancelled', 'expired'))
       OR NOT EXISTS (
           SELECT 1 FROM public.programme_programmearchivetaskevent event
           JOIN public.audit_auditnativemutationwitness witness ON
        witness.audit_event_id = event.audit_event_id
           WHERE event.task_id = task.id AND event.version = task.version AND
        event.state = task.state
             AND witness.transaction_stamp =
        public.maru_audit_current_native_transaction_stamp()
       ) THEN
        RAISE EXCEPTION
        'Programme archive custody lacks atomic completion or disposal evidence' USING
        ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, public, pg_temp;

CREATE TRIGGER programme_archive_task_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.programme_programmearchivetask
FOR EACH ROW EXECUTE FUNCTION public.maru_programme_archive_task_guard();
CREATE CONSTRAINT TRIGGER programme_archive_task_evidence
AFTER INSERT OR UPDATE ON public.programme_programmearchivetask
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_programme_archive_task_evidence();
CREATE TRIGGER programme_archive_event_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.programme_programmearchivetaskevent
FOR EACH ROW EXECUTE FUNCTION public.maru_programme_archive_event_guard();
CREATE TRIGGER programme_archive_chunk_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.programme_programmearchivechunk
FOR EACH ROW EXECUTE FUNCTION public.maru_programme_archive_chunk_guard();
CREATE CONSTRAINT TRIGGER programme_archive_chunk_evidence
AFTER INSERT OR DELETE ON public.programme_programmearchivechunk
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_programme_archive_chunk_evidence();
CREATE TRIGGER programme_archive_task_no_truncate
BEFORE TRUNCATE ON public.programme_programmearchivetask
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_refuse_programme_truncate();
CREATE TRIGGER programme_archive_event_no_truncate
BEFORE TRUNCATE ON public.programme_programmearchivetaskevent
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_refuse_programme_truncate();
CREATE TRIGGER programme_archive_chunk_no_truncate
BEFORE TRUNCATE ON public.programme_programmearchivechunk
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_refuse_programme_truncate();
REVOKE ALL ON FUNCTION public.maru_programme_archive_task_guard(),
    public.maru_programme_archive_event_guard(),
        public.maru_programme_archive_task_evidence(),
    public.maru_programme_archive_chunk_guard(),
        public.maru_programme_archive_chunk_evidence() FROM PUBLIC;
"""

REVERSE_SQL = (
    UNUSED_PREFLIGHT
    + """
DROP TRIGGER programme_archive_chunk_no_truncate ON
        public.programme_programmearchivechunk;
DROP TRIGGER programme_archive_event_no_truncate ON
        public.programme_programmearchivetaskevent;
DROP TRIGGER programme_archive_task_no_truncate ON
        public.programme_programmearchivetask;
DROP TRIGGER programme_archive_chunk_evidence ON public.programme_programmearchivechunk;
DROP TRIGGER programme_archive_chunk_guard ON public.programme_programmearchivechunk;
DROP TRIGGER programme_archive_event_guard ON
        public.programme_programmearchivetaskevent;
DROP TRIGGER programme_archive_task_evidence ON public.programme_programmearchivetask;
DROP TRIGGER programme_archive_task_guard ON public.programme_programmearchivetask;
DROP FUNCTION public.maru_programme_archive_chunk_evidence();
DROP FUNCTION public.maru_programme_archive_chunk_guard();
DROP FUNCTION public.maru_programme_archive_task_evidence();
DROP FUNCTION public.maru_programme_archive_event_guard();
DROP FUNCTION public.maru_programme_archive_task_guard();
"""
)


class Migration(migrations.Migration):
    """Keep unused reversal safe and used request/custody evidence fail-forward."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("programme", "0020_exit_archive_records")
    ]
    operations: ClassVar[list[Operation]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
