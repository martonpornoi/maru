"""Backstop explicit host state, personal availability and reciprocal evidence."""

from __future__ import annotations

import importlib
import re
from typing import ClassVar

from django.db import migrations

_base = importlib.import_module("maru.programme.migrations.0002_integrity_guards")
_accepted = importlib.import_module("maru.programme.migrations.0005_accepted_item_integrity")


def _function(name: str) -> str:
    for source in (_accepted.FORWARD_SQL, _base.FORWARD_SQL):
        match = re.search(
            rf"CREATE (?:OR REPLACE )?FUNCTION public\.{re.escape(name)}\(\).*?"
            r"SET search_path = pg_catalog, public, pg_temp;", source, re.DOTALL,
        )
        if match is not None:
            return match.group().replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
    raise RuntimeError(f"Missing pinned Programme function: {name}")


REPLACED_FUNCTIONS = (
    "maru_guard_programme_item", "maru_guard_programme_receipt",
    "maru_validate_programme_item_evidence", "maru_guard_programme_requirement",
    "maru_validate_programme_dependency_cursors",
)
TABLES = (
    "programme_programmehostrelationship", "programme_programmehostinvitation",
    "programme_programmehostrevision", "programme_programmehostavailabilitywindow",
)
NEW_FUNCTIONS = (
    "maru_guard_programme_host", "maru_guard_programme_host_record",
    "maru_guard_programme_host_window", "maru_validate_programme_host_evidence",
)

# A closed edition admits only a later, independently checked personal exit.
# All ordinary commands retain their planning fence through the receipt guard.
_item = _function("maru_guard_programme_item").replace(
    "IF edition_lifecycle NOT IN ('draft', 'preparing') THEN",
    "IF TG_OP = 'INSERT' AND edition_lifecycle NOT IN ('draft', 'preparing') THEN",
)
_receipt = _function("maru_guard_programme_receipt").replace(
    "    ELSIF NEW.operation = 'working_revise' THEN",
    """    ELSIF NEW.operation IN ('host_invite', 'host_respond', 'host_remove', 'host_availability') THEN
        SELECT EXISTS (
            SELECT 1 FROM public.programme_programmehostrevision r
            WHERE r.id = NEW.result_object_id AND r.operation = NEW.operation
              AND r.item_id = NEW.item_id AND r.organization_id = NEW.organization_id
              AND r.edition_id = NEW.edition_id AND r.item_version = NEW.resulting_item_version
              AND r.actor_id = NEW.actor_id AND r.reason = NEW.reason
        ) INTO result_matches;
    ELSIF NEW.operation = 'working_revise' THEN""",
).replace(
    "'item_create', 'item_accept', 'working_revise'",
    "'host_invite', 'host_respond', 'host_remove', 'host_availability', 'item_create', 'item_accept', 'working_revise'",
).replace(
    "    RETURN NEW;",
    """    IF NOT EXISTS (
        SELECT 1 FROM public.events_eventedition e WHERE e.id = NEW.edition_id
          AND e.lifecycle IN ('draft', 'preparing')
    ) AND NOT EXISTS (
        SELECT 1 FROM public.programme_programmehostrevision r
        JOIN public.programme_programmehostrelationship h ON h.id = r.host_id
        WHERE r.id = NEW.result_object_id AND r.operation = NEW.operation
          AND r.actor_id = h.account_id AND r.period_count = 0
          AND r.availability_state = 'withdrawn'
          AND ((r.operation = 'host_respond' AND r.state IN ('declined', 'withdrawn'))
               OR (r.operation = 'host_availability' AND r.state = 'confirmed'))
    ) THEN
        RAISE EXCEPTION 'Closed Programme planning admits only exact personal withdrawal'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;""",
)
_evidence = _function("maru_validate_programme_item_evidence").replace(
    "    ELSIF TG_TABLE_NAME = 'programme_programmecommandreceipt' THEN",
    """        IF NOT EXISTS (
            SELECT 1 FROM public.events_eventedition e WHERE e.id = NEW.edition_id
              AND e.lifecycle IN ('draft', 'preparing')
        ) AND NOT EXISTS (
            SELECT 1 FROM public.programme_programmehostrevision r
            JOIN public.programme_programmehostrelationship h ON h.id = r.host_id
            WHERE r.item_id = NEW.id AND r.item_version = NEW.aggregate_version
              AND r.actor_id = NEW.last_modified_by_id AND r.actor_id = h.account_id
              AND r.period_count = 0 AND r.availability_state = 'withdrawn'
              AND ((r.operation = 'host_respond' AND r.state IN ('declined', 'withdrawn'))
                   OR (r.operation = 'host_availability' AND r.state = 'confirmed'))
              AND NEW.lifecycle = 'active'
        ) THEN
            RAISE EXCEPTION 'Closed Programme item mutation lacks personal exit evidence'
                USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'programme_programmecommandreceipt' THEN""",
)
_requirement = _function("maru_guard_programme_requirement").replace(
    "        expected_dependency_version := COALESCE(expected_dependency_version, 0);",
    """        IF NEW.concern IN ('host_confirmation', 'schedule_availability') THEN
            SELECT COALESCE(MAX(r.item_version), 0) INTO expected_dependency_version
            FROM public.programme_programmehostrevision r WHERE r.item_id = NEW.item_id
              AND (NEW.concern = 'schedule_availability' OR r.operation <> 'host_availability');
        END IF;
        expected_dependency_version := COALESCE(expected_dependency_version, 0);""",
)
_dependencies = _function("maru_validate_programme_dependency_cursors").replace(
    "('working_revise', 'delivery_revise')",
    "('working_revise', 'delivery_revise', 'host_invite', 'host_respond', 'host_remove', 'host_availability')",
).replace(
    "               (command_operation = 'working_revise'",
    """               (command_operation IN ('host_invite', 'host_respond', 'host_remove')
                AND NEW.concern IN ('host_confirmation', 'schedule_availability'))
               OR (command_operation = 'host_availability' AND NEW.concern = 'schedule_availability')
               OR (command_operation = 'working_revise'""",
).replace(
    "    RETURN NULL;\nEND;",
    """    IF command_operation IN ('host_invite', 'host_respond', 'host_remove', 'host_availability')
       AND EXISTS (
        SELECT 1 FROM public.programme_programmereadinessrequirement r
        WHERE r.item_id = checked_item_id
          AND (r.concern = 'schedule_availability' OR (
               r.concern = 'host_confirmation' AND command_operation <> 'host_availability'))
          AND (r.dependency_version <> checked_item_version OR r.item_version <> checked_item_version
               OR r.last_modified_by_id <> command_actor_id)
    ) THEN
        RAISE EXCEPTION 'Programme host change left dependency evidence stale' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;""",
)

HOST_SQL = r"""
CREATE FUNCTION public.maru_guard_programme_host()
RETURNS trigger AS $host_guard$
DECLARE
    item_row record;
    actor_valid boolean;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Programme host relationships are retained' USING ERRCODE = '23514';
    END IF;
    SELECT * INTO item_row FROM public.programme_programmeitem WHERE id = NEW.item_id FOR UPDATE;
    SELECT is_active AND email_verified_at IS NOT NULL AND account_kind = 'person'
      INTO actor_valid FROM public.identity_account WHERE id = NEW.last_modified_by_id FOR SHARE;
    IF item_row.organization_id IS DISTINCT FROM NEW.organization_id
       OR item_row.edition_id IS DISTINCT FROM NEW.edition_id
       OR item_row.aggregate_version IS DISTINCT FROM NEW.item_version
       OR item_row.last_modified_by_id IS DISTINCT FROM NEW.last_modified_by_id
       OR item_row.lifecycle IS DISTINCT FROM 'active' OR actor_valid IS DISTINCT FROM TRUE
       OR NEW.role NOT IN ('host', 'co_host')
       OR NEW.state NOT IN ('invited', 'confirmed', 'declined', 'withdrawn', 'removed')
       OR NEW.availability_state NOT IN ('unknown', 'draft', 'shared', 'withdrawn')
       OR NEW.version < 1 OR NEW.version > 1002 OR NEW.availability_version < 0
       OR NEW.invitation_sequence < 1 OR NEW.invitation_sequence > NEW.version
       OR (NEW.state <> 'confirmed' AND NEW.availability_state IN ('draft', 'shared'))
    THEN
        RAISE EXCEPTION 'Programme host scope or current state is invalid' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.version <> 1 OR NEW.invitation_sequence <> 1 OR NEW.state <> 'invited'
           OR NEW.availability_state <> 'unknown' OR NEW.availability_version <> 0
           OR (SELECT count(*) FROM public.programme_programmehostrelationship WHERE item_id = NEW.item_id) >= 100
        THEN
            RAISE EXCEPTION 'Programme host must start with bounded explicit invitation' USING ERRCODE = '23514';
        END IF;
    ELSIF (NEW.id, NEW.item_id, NEW.organization_id, NEW.edition_id, NEW.account_id, NEW.created_at)
          IS DISTINCT FROM (OLD.id, OLD.item_id, OLD.organization_id, OLD.edition_id, OLD.account_id, OLD.created_at)
       OR NEW.version <> OLD.version + 1 OR NEW.item_version <= OLD.item_version
    THEN
        RAISE EXCEPTION 'Programme host identity or version is invalid' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$host_guard$ LANGUAGE plpgsql VOLATILE CALLED ON NULL INPUT SECURITY INVOKER PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guard_programme_host_record()
RETURNS trigger AS $host_record_guard$
DECLARE
    h record;
    p record;
    person_valid boolean;
    count_periods integer;
    digest_periods text;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Programme host evidence is immutable' USING ERRCODE = '23514';
    END IF;
    SELECT * INTO h FROM public.programme_programmehostrelationship WHERE id = NEW.host_id FOR UPDATE;
    IF h.item_id IS DISTINCT FROM NEW.item_id OR h.organization_id IS DISTINCT FROM NEW.organization_id
       OR h.edition_id IS DISTINCT FROM NEW.edition_id OR h.item_version IS DISTINCT FROM NEW.item_version
       OR h.last_modified_by_id IS DISTINCT FROM NEW.actor_id OR h.role IS DISTINCT FROM NEW.role
       OR btrim(NEW.reason) = '' OR length(NEW.reason) > 1000 OR NEW.occurred_at IS NULL
    THEN
        RAISE EXCEPTION 'Programme host evidence scope mismatch' USING ERRCODE = '23514';
    END IF;
    IF TG_TABLE_NAME = 'programme_programmehostinvitation' THEN
        IF NEW.sequence IS DISTINCT FROM h.invitation_sequence OR NEW.host_version IS DISTINCT FROM h.version
           OR h.state <> 'invited' OR btrim(NEW.title) = '' OR length(NEW.title) > 240
           OR length(NEW.briefing) > 2000 OR NEW.title ~ '[[:cntrl:]]'
           OR replace(NEW.briefing, E'\n', '') ~ '[[:cntrl:]]'
           OR NEW.sequence <> 1 + (SELECT COALESCE(MAX(sequence), 0) FROM public.programme_programmehostinvitation WHERE host_id = NEW.host_id)
        THEN
            RAISE EXCEPTION 'Programme host invitation does not match new invitation state' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    SELECT * INTO p FROM public.programme_programmehostrevision
      WHERE host_id = NEW.host_id ORDER BY sequence DESC LIMIT 1;
    SELECT is_active AND email_verified_at IS NOT NULL AND account_kind = 'person'
      INTO person_valid FROM public.identity_account WHERE id = h.account_id FOR SHARE;
    SELECT count(*), encode(sha256(convert_to(COALESCE(string_agg(
        extract(epoch FROM starts_at)::bigint::text || ':' || extract(epoch FROM ends_at)::bigint::text || ':' || kind,
        E'\n' ORDER BY starts_at, id), ''), 'UTF8')), 'hex')
      INTO count_periods, digest_periods FROM public.programme_programmehostavailabilitywindow WHERE host_id = h.id;
    IF NEW.sequence IS DISTINCT FROM h.version OR NEW.sequence <> COALESCE(p.sequence, 0) + 1
       OR (NEW.invitation_sequence, NEW.state, NEW.availability_state, NEW.availability_version)
          IS DISTINCT FROM (h.invitation_sequence, h.state, h.availability_state, h.availability_version)
       OR NEW.period_count IS DISTINCT FROM count_periods OR NEW.periods_digest IS DISTINCT FROM digest_periods
       OR NEW.period_count > 128 OR NEW.period_count < 0
       OR (NEW.availability_state NOT IN ('draft', 'shared') AND NEW.period_count <> 0)
       OR (NEW.operation <> 'host_remove' AND person_valid IS DISTINCT FROM TRUE)
    THEN
        RAISE EXCEPTION 'Programme host revision does not match complete current state' USING ERRCODE = '23514';
    END IF;
    IF NEW.operation = 'host_invite' THEN
        IF NEW.state <> 'invited' OR NEW.availability_state <> 'unknown'
           OR (p.sequence IS NOT NULL AND p.state NOT IN ('declined', 'withdrawn', 'removed'))
           OR NEW.invitation_sequence <> COALESCE(p.invitation_sequence, 0) + 1
           OR NEW.availability_version <> (CASE WHEN p.sequence IS NULL THEN 0 ELSE p.availability_version + 1 END)
           OR NEW.sequence >= 1000 OR NOT EXISTS (
               SELECT 1 FROM public.programme_programmehostinvitation i WHERE i.host_id = h.id
               AND i.sequence = NEW.invitation_sequence AND i.host_version = NEW.sequence
               AND i.actor_id = NEW.actor_id AND i.reason = NEW.reason AND i.item_version = NEW.item_version
           )
        THEN
            RAISE EXCEPTION 'Programme reinvitation must be explicit and newly confirmable' USING ERRCODE = '23514';
        END IF;
    ELSE
        IF p.sequence IS NULL OR NEW.invitation_sequence IS DISTINCT FROM p.invitation_sequence
           OR NEW.role IS DISTINCT FROM p.role THEN
            RAISE EXCEPTION 'Programme hosting decision cannot change invitation or role' USING ERRCODE = '23514';
        END IF;
        IF NEW.operation = 'host_respond' THEN
            IF NEW.actor_id <> h.account_id OR NOT (
                (p.state = 'invited' AND NEW.state IN ('confirmed', 'declined'))
                OR (p.state = 'confirmed' AND NEW.state = 'withdrawn')
            ) OR (NEW.state = 'confirmed' AND (
                NEW.availability_version <> p.availability_version OR NEW.availability_state <> 'unknown' OR NEW.sequence > 1000
            )) OR (NEW.state <> 'confirmed' AND (
                NEW.availability_version <> p.availability_version + 1 OR NEW.availability_state <> 'withdrawn'
            )) OR NEW.reason IS DISTINCT FROM (CASE NEW.state
                WHEN 'confirmed' THEN 'Person confirmed their Programme hosting invitation.'
                WHEN 'declined' THEN 'Person declined their Programme hosting invitation.'
                WHEN 'withdrawn' THEN 'Person withdrew from their Programme hosting relationship.' END)
            THEN
                RAISE EXCEPTION 'Programme response must be the exact person current invitation decision' USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.operation = 'host_remove' THEN
            IF p.state NOT IN ('invited', 'confirmed') OR NEW.state <> 'removed'
               OR NEW.availability_state <> 'withdrawn' OR NEW.availability_version <> p.availability_version + 1
            THEN
                RAISE EXCEPTION 'Programme removal must end current hosting and availability' USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.operation = 'host_availability' THEN
            IF NEW.actor_id <> h.account_id OR NEW.state <> 'confirmed' OR p.state <> 'confirmed'
               OR NEW.availability_state NOT IN ('draft', 'shared', 'withdrawn')
               OR NEW.availability_version <> p.availability_version + 1
               OR (NEW.availability_state = 'withdrawn' AND p.availability_state = 'withdrawn')
               OR (NEW.availability_state <> 'withdrawn' AND NEW.sequence > 1000)
               OR NEW.reason IS DISTINCT FROM 'Person set their Programme host availability to ' || NEW.availability_state || '.'
            THEN
                RAISE EXCEPTION 'Programme availability belongs only to the confirmed person' USING ERRCODE = '23514';
            END IF;
        ELSE
            RAISE EXCEPTION 'Unknown Programme host command' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$host_record_guard$ LANGUAGE plpgsql VOLATILE CALLED ON NULL INPUT SECURITY INVOKER PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guard_programme_host_window()
RETURNS trigger AS $host_window_guard$
DECLARE
    row_data record;
    h record;
    e record;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'Replace Programme availability through a new host revision' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN row_data := OLD; ELSE row_data := NEW; END IF;
    SELECT * INTO h FROM public.programme_programmehostrelationship WHERE id = row_data.host_id FOR UPDATE;
    IF h.item_id IS DISTINCT FROM row_data.item_id OR h.organization_id IS DISTINCT FROM row_data.organization_id
       OR h.edition_id IS DISTINCT FROM row_data.edition_id OR EXISTS (
           SELECT 1 FROM public.programme_programmehostrevision r WHERE r.host_id = h.id AND r.sequence = h.version
       ) THEN
        RAISE EXCEPTION 'Programme availability requires new exact host revision' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    SELECT * INTO e FROM public.events_eventedition WHERE id = row_data.edition_id FOR SHARE;
    IF h.state <> 'confirmed' OR h.availability_state NOT IN ('draft', 'shared')
       OR h.last_modified_by_id <> h.account_id OR e.lifecycle NOT IN ('draft', 'preparing')
       OR NEW.kind NOT IN ('available', 'preferred') OR NEW.ends_at <= NEW.starts_at
       OR NOT isfinite(NEW.starts_at) OR NOT isfinite(NEW.ends_at)
       OR date_trunc('minute', NEW.starts_at) <> NEW.starts_at OR date_trunc('minute', NEW.ends_at) <> NEW.ends_at
       OR NEW.starts_at < (e.starts_on::timestamp AT TIME ZONE e.time_zone)
       OR NEW.ends_at > ((e.ends_on + 1)::timestamp AT TIME ZONE e.time_zone)
       OR (SELECT count(*) FROM public.programme_programmehostavailabilitywindow w WHERE w.host_id = h.id) >= 128
       OR EXISTS (SELECT 1 FROM public.programme_programmehostavailabilitywindow w WHERE w.host_id = h.id
                  AND w.starts_at < NEW.ends_at AND w.ends_at > NEW.starts_at)
    THEN
        RAISE EXCEPTION 'Programme availability interval is invalid for this exact purpose' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$host_window_guard$ LANGUAGE plpgsql VOLATILE CALLED ON NULL INPUT SECURITY INVOKER PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_validate_programme_host_evidence()
RETURNS trigger AS $host_evidence_guard$
DECLARE
    host_id uuid;
    checked_version bigint;
    h record;
    r record;
    receipt record;
    expected_action text;
    expected_capability text;
    count_periods integer;
    digest_periods text;
BEGIN
    IF TG_TABLE_NAME = 'programme_programmehostrelationship' THEN
        host_id := NEW.id; checked_version := NEW.version;
    ELSIF TG_TABLE_NAME = 'programme_programmehostrevision' THEN
        host_id := NEW.host_id; checked_version := NEW.sequence;
    ELSIF TG_TABLE_NAME = 'programme_programmehostinvitation' THEN
        host_id := NEW.host_id; checked_version := NEW.host_version;
    ELSE
        IF TG_OP = 'DELETE' THEN host_id := OLD.host_id; ELSE host_id := NEW.host_id; END IF;
    END IF;
    SELECT * INTO h FROM public.programme_programmehostrelationship WHERE id = host_id;
    SELECT * INTO r FROM public.programme_programmehostrevision v
      WHERE v.host_id = h.id AND v.sequence = COALESCE(checked_version, h.version);
    SELECT * INTO receipt FROM public.programme_programmecommandreceipt c
      WHERE c.result_object_id = r.id AND c.operation = r.operation AND c.item_id = r.item_id
        AND c.organization_id = r.organization_id AND c.edition_id = r.edition_id
        AND c.resulting_item_version = r.item_version AND c.actor_id = r.actor_id AND c.reason = r.reason;
    IF r.id IS NULL OR receipt.id IS NULL THEN
        RAISE EXCEPTION 'Programme host state lacks reciprocal command evidence' USING ERRCODE = '23514';
    END IF;
    IF TG_TABLE_NAME = 'programme_programmehostrelationship' THEN
        IF (r.role, r.state, r.availability_state, r.availability_version, r.invitation_sequence, r.item_version, r.actor_id)
           IS DISTINCT FROM (NEW.role, NEW.state, NEW.availability_state, NEW.availability_version,
                             NEW.invitation_sequence, NEW.item_version, NEW.last_modified_by_id) THEN
            RAISE EXCEPTION 'Programme host state lacks exact revision' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF TG_TABLE_NAME = 'programme_programmehostinvitation' AND r.operation <> 'host_invite' THEN
        RAISE EXCEPTION 'Programme invitation requires its explicit invitation receipt' USING ERRCODE = '23514';
    END IF;
    IF r.sequence = h.version THEN
        SELECT count(*), encode(sha256(convert_to(COALESCE(string_agg(
            extract(epoch FROM starts_at)::bigint::text || ':' || extract(epoch FROM ends_at)::bigint::text || ':' || kind,
            E'\n' ORDER BY starts_at, id), ''), 'UTF8')), 'hex')
          INTO count_periods, digest_periods FROM public.programme_programmehostavailabilitywindow w WHERE w.host_id = h.id;
        IF r.period_count IS DISTINCT FROM count_periods OR r.periods_digest IS DISTINCT FROM digest_periods THEN
            RAISE EXCEPTION 'Programme availability lacks complete revision evidence' USING ERRCODE = '23514';
        END IF;
    END IF;
    expected_action := CASE r.operation WHEN 'host_invite' THEN 'invite_host'
        WHEN 'host_respond' THEN 'respond_host' WHEN 'host_remove' THEN 'remove_host'
        WHEN 'host_availability' THEN 'change_host_availability' END;
    expected_capability := CASE r.operation WHEN 'host_respond' THEN 'programme.respond_host_self'
        WHEN 'host_availability' THEN 'programme.manage_host_availability_self' ELSE 'programme.manage_hosts' END;
    IF NOT EXISTS (
        SELECT 1 FROM public.audit_auditevent a JOIN public.effects_domainevent e ON e.causation_id = a.id
        JOIN public.programme_programmeitem i ON i.id = r.item_id
        WHERE a.principal_kind = 'account' AND a.principal_id = r.actor_id
          AND a.organization_id = r.organization_id AND a.event_edition_id = r.edition_id
          AND a.operation = 'programme.command.' || r.operation AND a.outcome = 'allow'
          AND a.capability_code = expected_capability AND a.target_type = 'programme.item' AND a.target_id = r.item_id
          AND a.correlation_id = receipt.correlation_id AND a.source_channel = receipt.source_channel
          AND a.retention_class = 'programme-restricted' AND e.retention_class = a.retention_class
          AND e.organization_id = r.organization_id AND e.event_edition_id = r.edition_id
          AND e.actor_kind = 'account' AND e.actor_id = r.actor_id AND e.correlation_id = receipt.correlation_id
          AND e.aggregate_type = 'programme.item' AND e.aggregate_id = r.item_id AND e.aggregate_version = r.item_version
          AND e.event_name = 'programme.item.changed.v1' AND e.schema_version = 1
          AND e.payload = jsonb_build_object('action', expected_action, 'layer', 'hosts', 'item_kind', i.kind,
                  'provenance', i.provenance_kind, 'lifecycle', 'active', 'concern', 'none')
          AND EXISTS (SELECT 1 FROM public.effects_outboxmessage b WHERE b.event_id = e.id AND b.organization_id = r.organization_id)
    ) THEN
        RAISE EXCEPTION 'Programme host command lacks minimized audit event and outbox' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$host_evidence_guard$ LANGUAGE plpgsql VOLATILE CALLED ON NULL INPUT SECURITY INVOKER PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""

_triggers = []
_reverse_triggers = []
for _table, _guard in zip(TABLES, (
    "maru_guard_programme_host", "maru_guard_programme_host_record",
    "maru_guard_programme_host_record", "maru_guard_programme_host_window",
), strict=True):
    _short = _table.removeprefix("programme_programme")
    _triggers.append(f"""
CREATE TRIGGER programme_{_short}_guard BEFORE INSERT OR UPDATE OR DELETE ON public.{_table}
FOR EACH ROW EXECUTE FUNCTION public.{_guard}();
CREATE TRIGGER programme_{_short}_truncate BEFORE TRUNCATE ON public.{_table}
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_refuse_programme_truncate();
CREATE CONSTRAINT TRIGGER programme_{_short}_evidence AFTER INSERT OR UPDATE OR DELETE ON public.{_table}
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.maru_validate_programme_host_evidence();
""")
    _reverse_triggers.extend(f"DROP TRIGGER programme_{_short}_{suffix} ON public.{_table};" for suffix in ("guard", "truncate", "evidence"))

FORWARD_SQL = "\n".join((
    _item, _receipt, _evidence, _requirement, _dependencies, HOST_SQL, *_triggers,
    "REVOKE ALL ON FUNCTION " + ", ".join(f"public.{name}()" for name in NEW_FUNCTIONS) + " FROM PUBLIC;",
))
REVERSE_SQL = "\n".join((
    *_reverse_triggers, *(f"DROP FUNCTION public.{name}();" for name in NEW_FUNCTIONS),
    *(_function(name) for name in REPLACED_FUNCTIONS),
))


class Migration(migrations.Migration):
    """Install host integrity while preserving accepted-item and layer guarantees."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("programme", "0007_host_relationships"),
        ("authorization", "0026_programme_host_capabilities"),
    ]
    operations: ClassVar[list[object]] = [migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL)]
