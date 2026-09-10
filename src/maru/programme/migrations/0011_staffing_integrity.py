"""Guard staffing scope, immutable terms and reciprocal command evidence."""

from __future__ import annotations

import importlib
import re
from typing import ClassVar

from django.db import migrations

_host = importlib.import_module("maru.programme.migrations.0008_host_integrity")


def _previous_receipt() -> str:
    match = re.search(
        r"CREATE OR REPLACE FUNCTION public\.maru_guard_programme_receipt\(\).*?"
        r"SET search_path = pg_catalog, public, pg_temp;", _host.FORWARD_SQL, re.DOTALL,
    )
    if match is None:
        raise RuntimeError("Missing pinned Programme receipt function.")
    return match.group()


_receipt = _previous_receipt().replace(
    "    ELSIF NEW.operation = 'working_revise' THEN",
    """    ELSIF NEW.operation IN ('staffing_create', 'staffing_revise', 'staffing_retire') THEN
        SELECT EXISTS (
            SELECT 1 FROM public.programme_programmestaffingrevision r
            WHERE r.id = NEW.result_object_id AND r.operation = NEW.operation
              AND r.item_id = NEW.item_id AND r.organization_id = NEW.organization_id
              AND r.edition_id = NEW.edition_id AND r.item_version = NEW.resulting_item_version
              AND r.actor_id = NEW.actor_id AND r.reason = NEW.reason
        ) INTO result_matches;
    ELSIF NEW.operation = 'working_revise' THEN""",
).replace(
    "'host_invite', 'host_respond', 'host_remove', 'host_availability', 'item_create'",
    "'staffing_create', 'staffing_revise', 'staffing_retire', 'host_invite', 'host_respond', 'host_remove', 'host_availability', 'item_create'",
)

TABLES = ("programme_programmestaffingrequirement", "programme_programmestaffingrevision")
NEW_FUNCTIONS = (
    "maru_guard_programme_staffing", "maru_guard_programme_staffing_revision",
    "maru_validate_programme_staffing_evidence",
)

STAFFING_SQL = r"""
CREATE FUNCTION public.maru_guard_programme_staffing()
RETURNS trigger AS $staffing_guard$
DECLARE
    i record;
    o record;
    edition_lifecycle text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Programme staffing requirements are retained' USING ERRCODE = '23514';
    END IF;
    SELECT lifecycle INTO edition_lifecycle FROM public.events_eventedition
      WHERE id = NEW.edition_id AND organization_id = NEW.organization_id FOR UPDATE;
    SELECT * INTO i FROM public.programme_programmeitem WHERE id = NEW.item_id FOR UPDATE;
    SELECT * INTO o FROM public.scheduling_schedulingoccurrence WHERE id = NEW.occurrence_id FOR SHARE;
    IF edition_lifecycle IS NULL OR edition_lifecycle NOT IN ('draft', 'preparing')
       OR (i.organization_id, i.edition_id, i.aggregate_version, i.last_modified_by_id, i.lifecycle)
          IS DISTINCT FROM (NEW.organization_id, NEW.edition_id, NEW.item_version, NEW.last_modified_by_id, 'active'::varchar)
       OR (o.organization_id, o.edition_id, o.programme_item_id)
          IS DISTINCT FROM (NEW.organization_id, NEW.edition_id, NEW.item_id)
       OR NEW.version < 1 OR NEW.version > 1001 OR NEW.lifecycle NOT IN ('active', 'retired')
       OR (NEW.lifecycle = 'active' AND (o.lifecycle <> 'active' OR NEW.version > 1000))
    THEN
        RAISE EXCEPTION 'Programme staffing scope or lifecycle is invalid' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.version <> 1 OR NEW.lifecycle <> 'active'
           OR (SELECT count(*) FROM public.programme_programmestaffingrequirement WHERE item_id = NEW.item_id) >= 128
        THEN
            RAISE EXCEPTION 'Programme staffing must begin with a bounded explicit need' USING ERRCODE = '23514';
        END IF;
    ELSIF (NEW.id, NEW.organization_id, NEW.edition_id, NEW.item_id, NEW.occurrence_id, NEW.created_at)
          IS DISTINCT FROM (OLD.id, OLD.organization_id, OLD.edition_id, OLD.item_id, OLD.occurrence_id, OLD.created_at)
       OR OLD.lifecycle <> 'active' OR NEW.version <> OLD.version + 1 OR NEW.item_version <= OLD.item_version
    THEN
        RAISE EXCEPTION 'Programme staffing identity or history is immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$staffing_guard$ LANGUAGE plpgsql VOLATILE CALLED ON NULL INPUT SECURITY INVOKER PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guard_programme_staffing_revision()
RETURNS trigger AS $staffing_revision_guard$
DECLARE
    h record;
    p record;
    o record;
    position_row record;
    e record;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Programme staffing revisions are immutable' USING ERRCODE = '23514';
    END IF;
    SELECT * INTO h FROM public.programme_programmestaffingrequirement WHERE id = NEW.requirement_id FOR UPDATE;
    SELECT * INTO p FROM public.programme_programmestaffingrevision
      WHERE requirement_id = NEW.requirement_id ORDER BY sequence DESC LIMIT 1;
    SELECT * INTO o FROM public.scheduling_schedulingoccurrence WHERE id = h.occurrence_id FOR SHARE;
    SELECT * INTO e FROM public.events_eventedition WHERE id = NEW.edition_id FOR SHARE;
    SELECT w.organization_id, w.edition_id, w.status, d.retired_at,
           d.organization_id AS department_organization_id, d.edition_id AS department_edition_id
      INTO position_row FROM public.workforce_position w JOIN public.workforce_department d ON d.id = w.department_id
      WHERE w.id = NEW.position_id FOR SHARE OF w, d;
    IF (h.organization_id, h.edition_id, h.item_id, h.item_version, h.last_modified_by_id, h.version, h.lifecycle)
       IS DISTINCT FROM (NEW.organization_id, NEW.edition_id, NEW.item_id, NEW.item_version, NEW.actor_id, NEW.sequence, NEW.lifecycle)
       OR NEW.sequence <> COALESCE(p.sequence, 0) + 1
       OR NEW.occurrence_version IS DISTINCT FROM o.aggregate_version
       OR NEW.operation NOT IN ('staffing_create', 'staffing_revise', 'staffing_retire')
       OR (NEW.sequence = 1) IS DISTINCT FROM (NEW.operation = 'staffing_create')
       OR (NEW.lifecycle = 'retired') IS DISTINCT FROM (NEW.operation = 'staffing_retire')
       OR (position_row.organization_id, position_row.edition_id, position_row.department_organization_id, position_row.department_edition_id)
          IS DISTINCT FROM (NEW.organization_id, NEW.edition_id, NEW.organization_id, NEW.edition_id)
       OR NOT isfinite(NEW.starts_at) OR NOT isfinite(NEW.ends_at) OR NOT isfinite(NEW.occurred_at)
       OR NEW.ends_at <= NEW.starts_at
       OR extract(second FROM NEW.starts_at) <> 0 OR extract(second FROM NEW.ends_at) <> 0
       OR NEW.required_headcount NOT BETWEEN 1 AND 1024 OR NEW.break_minutes NOT BETWEEN 0 AND 1440
       OR NEW.minimum_rest_minutes NOT BETWEEN 0 AND 2880
       OR NEW.break_minutes * interval '1 minute' >= NEW.ends_at - NEW.starts_at
       OR btrim(NEW.title) = '' OR btrim(NEW.location_label) = '' OR btrim(NEW.briefing) = '' OR btrim(NEW.reason) = ''
       OR NEW.title ~ '[[:cntrl:]]' OR NEW.location_label ~ '[[:cntrl:]]' OR NEW.briefing ~ '[[:cntrl:]]'
       OR NEW.supervision_note ~ '[[:cntrl:]]' OR NEW.reason ~ '[[:cntrl:]]'
    THEN
        RAISE EXCEPTION 'Programme staffing revision does not match exact bounded source terms' USING ERRCODE = '23514';
    END IF;
    IF NEW.operation = 'staffing_retire' THEN
        IF (NEW.position_id, NEW.title, NEW.location_label, NEW.briefing, NEW.supervision_note,
            NEW.starts_at, NEW.ends_at, NEW.required_headcount, NEW.break_minutes, NEW.minimum_rest_minutes)
           IS DISTINCT FROM (p.position_id, p.title, p.location_label, p.briefing, p.supervision_note,
            p.starts_at, p.ends_at, p.required_headcount, p.break_minutes, p.minimum_rest_minutes)
        THEN
            RAISE EXCEPTION 'Programme staffing retirement must retain original work terms' USING ERRCODE = '23514';
        END IF;
    ELSIF position_row.status = 'closed' OR position_row.retired_at IS NOT NULL OR o.lifecycle <> 'active'
       OR NEW.starts_at < (e.starts_on::timestamp AT TIME ZONE e.time_zone)
       OR NEW.ends_at > ((e.ends_on + 1)::timestamp AT TIME ZONE e.time_zone)
    THEN
        RAISE EXCEPTION 'Programme staffing source no longer accepts this work' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$staffing_revision_guard$ LANGUAGE plpgsql VOLATILE CALLED ON NULL INPUT SECURITY INVOKER PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_validate_programme_staffing_evidence()
RETURNS trigger AS $staffing_evidence_guard$
DECLARE
    r record;
    receipt record;
    expected_action text;
BEGIN
    IF TG_TABLE_NAME = 'programme_programmestaffingrequirement' THEN
        SELECT * INTO r FROM public.programme_programmestaffingrevision
          WHERE requirement_id = NEW.id AND sequence = NEW.version;
        IF (r.organization_id, r.edition_id, r.item_id, r.item_version, r.actor_id, r.lifecycle)
           IS DISTINCT FROM (NEW.organization_id, NEW.edition_id, NEW.item_id, NEW.item_version, NEW.last_modified_by_id, NEW.lifecycle)
        THEN
            RAISE EXCEPTION 'Programme staffing state lacks an exact immutable revision' USING ERRCODE = '23514';
        END IF;
    ELSE
        SELECT * INTO r FROM public.programme_programmestaffingrevision WHERE id = NEW.id;
    END IF;
    SELECT * INTO receipt FROM public.programme_programmecommandreceipt c
      WHERE c.result_object_id = r.id AND c.operation = r.operation AND c.item_id = r.item_id
        AND c.organization_id = r.organization_id AND c.edition_id = r.edition_id
        AND c.resulting_item_version = r.item_version AND c.actor_id = r.actor_id AND c.reason = r.reason;
    IF r.id IS NULL OR receipt.id IS NULL THEN
        RAISE EXCEPTION 'Programme staffing lacks reciprocal command evidence' USING ERRCODE = '23514';
    END IF;
    expected_action := CASE r.operation WHEN 'staffing_create' THEN 'create_staffing'
        WHEN 'staffing_revise' THEN 'revise_staffing' WHEN 'staffing_retire' THEN 'retire_staffing' END;
    IF NOT EXISTS (
        SELECT 1 FROM public.audit_auditevent a JOIN public.effects_domainevent e ON e.causation_id = a.id
        JOIN public.programme_programmeitem i ON i.id = r.item_id
        WHERE a.principal_kind = 'account' AND a.principal_id = r.actor_id
          AND a.organization_id = r.organization_id AND a.event_edition_id = r.edition_id
          AND a.operation = 'programme.command.' || r.operation AND a.outcome = 'allow'
          AND a.capability_code = 'programme.manage_staffing' AND a.target_type = 'programme.item' AND a.target_id = r.item_id
          AND a.correlation_id = receipt.correlation_id AND a.source_channel = receipt.source_channel
          AND a.retention_class = 'programme-restricted' AND e.retention_class = a.retention_class
          AND e.organization_id = r.organization_id AND e.event_edition_id = r.edition_id
          AND e.actor_kind = 'account' AND e.actor_id = r.actor_id AND e.correlation_id = receipt.correlation_id
          AND e.aggregate_type = 'programme.item' AND e.aggregate_id = r.item_id AND e.aggregate_version = r.item_version
          AND e.event_name = 'programme.item.changed.v1' AND e.schema_version = 1
          AND e.payload = jsonb_build_object('action', expected_action, 'layer', 'staffing', 'item_kind', i.kind,
              'provenance', i.provenance_kind, 'lifecycle', 'active', 'concern', 'none')
          AND EXISTS (SELECT 1 FROM public.effects_outboxmessage b WHERE b.event_id = e.id AND b.organization_id = r.organization_id)
    ) THEN
        RAISE EXCEPTION 'Programme staffing requires minimized audit event and outbox evidence' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$staffing_evidence_guard$ LANGUAGE plpgsql VOLATILE CALLED ON NULL INPUT SECURITY INVOKER PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""

_triggers = []
_reverse_triggers = []
for _table, _guard in zip(TABLES, NEW_FUNCTIONS[:2], strict=True):
    _short = _table.removeprefix("programme_programme")
    _triggers.append(f"""
CREATE TRIGGER programme_{_short}_guard BEFORE INSERT OR UPDATE OR DELETE ON public.{_table}
FOR EACH ROW EXECUTE FUNCTION public.{_guard}();
CREATE TRIGGER programme_{_short}_truncate BEFORE TRUNCATE ON public.{_table}
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_refuse_programme_truncate();
CREATE CONSTRAINT TRIGGER programme_{_short}_evidence AFTER INSERT OR UPDATE ON public.{_table}
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.maru_validate_programme_staffing_evidence();
""")
    _reverse_triggers.extend(f"DROP TRIGGER programme_{_short}_{suffix} ON public.{_table};" for suffix in ("guard", "truncate", "evidence"))

FORWARD_SQL = "\n".join((
    _receipt, STAFFING_SQL, *_triggers,
    "REVOKE ALL ON FUNCTION " + ", ".join(f"public.{name}()" for name in NEW_FUNCTIONS) + " FROM PUBLIC;",
))
REVERSE_SQL = "\n".join((
    *_reverse_triggers, *(f"DROP FUNCTION public.{name}();" for name in NEW_FUNCTIONS), _previous_receipt(),
))


class Migration(migrations.Migration):
    """Install additive staffing integrity without activating a writer role."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("programme", "0010_staffing_requirements"),
        ("authorization", "0028_programme_staffing_capabilities"),
    ]
    operations: ClassVar[list[object]] = [migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL)]
