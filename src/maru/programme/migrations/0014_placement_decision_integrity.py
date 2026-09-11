"""Guard exact placement decisions and their independent evidence streams."""

from __future__ import annotations

import importlib
import re
from typing import ClassVar

from django.db import migrations

_staffing = importlib.import_module("maru.programme.migrations.0011_staffing_integrity")
_hosts = importlib.import_module("maru.programme.migrations.0008_host_integrity")


def _previous_function(name: str) -> str:
    for source in (_staffing.FORWARD_SQL, _hosts.FORWARD_SQL):
        match = re.search(
            rf"CREATE (?:OR REPLACE )?FUNCTION public\.{re.escape(name)}\(\).*?"
            r"SET search_path = pg_catalog, public, pg_temp;",
            source,
            re.DOTALL,
        )
        if match is not None:
            return match.group().replace(
                "CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1
            )
    raise RuntimeError("Missing pinned Programme evidence function.")


_operations = "'accessibility_fit_record', 'staffing_absence_record'"
_independent = "'public_rendition_record', " + _operations
_receipt = (
    _previous_function("maru_guard_programme_receipt")
    .replace(
        "    ELSIF NEW.operation = 'working_revise' THEN",
        """    ELSIF NEW.operation IN ('accessibility_fit_record', 'staffing_absence_record') THEN
        SELECT EXISTS (
            SELECT 1 FROM public.programme_programmeplacementdecision d
            WHERE d.id = NEW.result_object_id AND d.item_id = NEW.item_id
              AND d.organization_id = NEW.organization_id AND d.edition_id = NEW.edition_id
              AND d.item_version = NEW.resulting_item_version
              AND d.actor_id = NEW.actor_id AND d.reason = NEW.reason
              AND NEW.operation = CASE d.kind WHEN 'accessibility_fit' THEN 'accessibility_fit_record'
                  WHEN 'staffing_not_required' THEN 'staffing_absence_record' END
        ) INTO result_matches;
    ELSIF NEW.operation = 'working_revise' THEN""",
    )
    .replace(
        "'public_rendition_record'\n       )",
        _independent + "\n       )",
    )
    .replace(
        "ELSIF NEW.operation = 'public_rendition_record' THEN\n        IF NEW.resulting_control_version",
        "ELSIF NEW.operation IN ("
        + _independent
        + ") THEN\n        IF NEW.resulting_control_version",
    )
    .replace(
        "    ) THEN\n        RAISE EXCEPTION 'Closed Programme planning admits only exact personal withdrawal'",
        """    ) AND NOT (
        NEW.operation IN ('accessibility_fit_record', 'staffing_absence_record')
        AND EXISTS (SELECT 1 FROM public.events_eventedition e WHERE e.id = NEW.edition_id
          AND e.lifecycle IN ('draft', 'preparing', 'ready', 'live'))
    ) THEN
        RAISE EXCEPTION 'Closed Programme planning admits only exact personal withdrawal'""",
    )
)
_evidence = (
    _previous_function("maru_validate_programme_item_evidence")
    .replace(
        "receipt.operation <> 'public_rendition_record'",
        "receipt.operation NOT IN (" + _independent + ")",
    )
    .replace(
        "IF NEW.operation = 'public_rendition_record' THEN",
        "IF NEW.operation IN (" + _independent + ") THEN",
    )
)

TABLE = "programme_programmeplacementdecision"
NEW_FUNCTIONS = (
    "maru_guard_programme_placement_decision",
    "maru_validate_programme_placement_decision_evidence",
)
REPLACED_FUNCTIONS = (
    "maru_guard_programme_receipt",
    "maru_validate_programme_item_evidence",
)

DECISION_SQL = r"""
CREATE FUNCTION public.maru_guard_programme_placement_decision()
RETURNS trigger AS $placement_decision_guard$
DECLARE
    i record;
    p record;
    placement_row record;
    occurrence_row record;
    candidate_row record;
    delivery_row record;
    selection_row record;
    edition_lifecycle text;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Programme placement decisions are immutable' USING ERRCODE = '23514';
    END IF;
    SELECT lifecycle INTO edition_lifecycle FROM public.events_eventedition
      WHERE id = NEW.edition_id AND organization_id = NEW.organization_id FOR UPDATE;
    SELECT * INTO i FROM public.programme_programmeitem WHERE id = NEW.item_id FOR UPDATE;
    SELECT * INTO p FROM public.programme_programmeplacementdecision
      WHERE placement_id = NEW.placement_id AND kind = NEW.kind ORDER BY sequence DESC LIMIT 1;
    SELECT r.*, o.occurrence_id INTO placement_row
      FROM public.scheduling_schedulingplacementrevision r
      JOIN public.scheduling_schedulingoccurrencerevision o ON o.id = r.occurrence_revision_id
      WHERE r.id = NEW.placement_id;
    SELECT * INTO occurrence_row FROM public.scheduling_schedulingoccurrence WHERE id = NEW.occurrence_id;
    SELECT r.*, c.aggregate_version AS current_version, c.lifecycle AS current_lifecycle
      INTO candidate_row FROM public.scheduling_schedulingcandidaterevision r
      JOIN public.scheduling_schedulingcandidate c ON c.id = r.candidate_id
      WHERE r.id = NEW.candidate_revision_id;
    IF edition_lifecycle IS NULL OR edition_lifecycle NOT IN ('draft', 'preparing', 'ready', 'live')
       OR (i.organization_id, i.edition_id, i.aggregate_version, i.lifecycle)
          IS DISTINCT FROM (NEW.organization_id, NEW.edition_id, NEW.item_version, 'active'::varchar)
       OR (placement_row.organization_id, placement_row.edition_id, placement_row.occurrence_id)
          IS DISTINCT FROM (NEW.organization_id, NEW.edition_id, NEW.occurrence_id)
       OR (occurrence_row.organization_id, occurrence_row.edition_id, occurrence_row.programme_item_id)
          IS DISTINCT FROM (NEW.organization_id, NEW.edition_id, NEW.item_id)
       OR (candidate_row.organization_id, candidate_row.edition_id)
          IS DISTINCT FROM (NEW.organization_id, NEW.edition_id)
       OR NOT EXISTS (
           SELECT 1 FROM public.scheduling_schedulingcandidatemember m
           WHERE m.revision_id = NEW.candidate_revision_id AND m.placement_id = NEW.placement_id
             AND m.occurrence_id = NEW.occurrence_id
             AND m.organization_id = NEW.organization_id AND m.edition_id = NEW.edition_id)
       OR NEW.kind NOT IN ('accessibility_fit', 'staffing_not_required')
       OR NEW.state NOT IN ('satisfied', 'blocked', 'withdrawn')
       OR NEW.sequence <> COALESCE(p.sequence, 0) + 1
       OR NEW.sequence NOT BETWEEN 1 AND 1001
       OR (NEW.sequence = 1001 AND NEW.state <> 'withdrawn')
       OR (NEW.state = 'withdrawn' AND p.id IS NULL)
       OR NEW.source_digest !~ '^[0-9a-f]{64}$'
       OR btrim(NEW.reason) = '' OR NEW.reason ~ '[[:cntrl:]]'
       OR NOT isfinite(NEW.occurred_at)
    THEN
        RAISE EXCEPTION 'Programme placement decision source or history is invalid' USING ERRCODE = '23514';
    END IF;
    IF NEW.state = 'withdrawn' THEN
        IF (NEW.candidate_revision_id, NEW.source_digest, NEW.delivery_revision_id,
            NEW.space_selection_version)
           IS DISTINCT FROM (p.candidate_revision_id, p.source_digest, p.delivery_revision_id,
            p.space_selection_version)
        THEN
            RAISE EXCEPTION 'Withdrawal must retain the exact prior placement proof' USING ERRCODE = '23514';
        END IF;
    ELSE
        IF occurrence_row.lifecycle <> 'active' OR candidate_row.current_lifecycle <> 'draft'
           OR candidate_row.sequence <> candidate_row.current_version
        THEN
            RAISE EXCEPTION 'Programme placement decision requires a current candidate' USING ERRCODE = '23514';
        END IF;
        IF NEW.kind = 'accessibility_fit' THEN
            SELECT * INTO delivery_row FROM public.programme_programmedeliveryrevision
              WHERE item_id = NEW.item_id ORDER BY sequence DESC LIMIT 1;
            SELECT * INTO selection_row FROM public.venues_editionspaceselection
              WHERE id = placement_row.space_selection_id;
            IF (delivery_row.id, delivery_row.organization_id, delivery_row.edition_id)
               IS DISTINCT FROM (NEW.delivery_revision_id, NEW.organization_id, NEW.edition_id)
               OR (selection_row.id, selection_row.organization_id, selection_row.edition_id,
                   selection_row.aggregate_version, selection_row.lifecycle)
               IS DISTINCT FROM (placement_row.space_selection_id, NEW.organization_id, NEW.edition_id,
                   NEW.space_selection_version, 'active'::varchar)
            THEN
                RAISE EXCEPTION 'Accessibility assessment requires exact current delivery and space' USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.state = 'satisfied' AND (EXISTS (
            SELECT 1 FROM public.programme_programmestaffingrequirement r
            WHERE r.occurrence_id = NEW.occurrence_id AND r.lifecycle = 'active'
        ) OR EXISTS (
            SELECT 1 FROM public.workforce_programmeshiftbinding b
            JOIN public.workforce_programmeshiftbindingrevision r ON r.binding_id = b.id
            JOIN public.workforce_shiftdemand d ON d.id = r.demand_id
            WHERE b.occurrence_id = NEW.occurrence_id AND d.status NOT IN ('cancelled', 'completed')
        )) THEN
            RAISE EXCEPTION 'Active staffing requirements cannot become inapplicable' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$placement_decision_guard$ LANGUAGE plpgsql VOLATILE CALLED ON NULL INPUT SECURITY INVOKER PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_validate_programme_placement_decision_evidence()
RETURNS trigger AS $placement_decision_evidence$
DECLARE
    receipt record;
    expected_operation text;
    expected_action text;
    expected_capability text;
    expected_aggregate text;
BEGIN
    expected_operation := CASE NEW.kind WHEN 'accessibility_fit' THEN 'accessibility_fit_record'
        WHEN 'staffing_not_required' THEN 'staffing_absence_record' END;
    expected_action := CASE NEW.kind WHEN 'accessibility_fit' THEN 'record_accessibility_fit'
        WHEN 'staffing_not_required' THEN 'record_staffing_absence' END;
    expected_capability := CASE NEW.kind WHEN 'accessibility_fit' THEN 'programme.manage_delivery'
        WHEN 'staffing_not_required' THEN 'programme.manage_staffing' END;
    expected_aggregate := CASE NEW.kind WHEN 'accessibility_fit' THEN 'programme.accessibility_fit'
        WHEN 'staffing_not_required' THEN 'programme.staffing_absence' END;
    SELECT * INTO receipt FROM public.programme_programmecommandreceipt c
      WHERE c.result_object_id = NEW.id AND c.operation = expected_operation
        AND c.item_id = NEW.item_id AND c.organization_id = NEW.organization_id AND c.edition_id = NEW.edition_id
        AND c.resulting_item_version = NEW.item_version AND c.expected_version = NEW.item_version
        AND c.actor_id = NEW.actor_id AND c.reason = NEW.reason;
    IF receipt.id IS NULL OR NOT EXISTS (
        SELECT 1 FROM public.audit_auditevent a
        JOIN public.effects_domainevent e ON e.causation_id = a.id
        JOIN public.programme_programmeitem i ON i.id = NEW.item_id
        WHERE a.principal_kind = 'account' AND a.principal_id = NEW.actor_id
          AND a.organization_id = NEW.organization_id AND a.event_edition_id = NEW.edition_id
          AND a.operation = 'programme.command.' || expected_operation AND a.outcome = 'allow'
          AND a.capability_code = expected_capability AND a.target_type = 'programme.item' AND a.target_id = NEW.item_id
          AND a.correlation_id = receipt.correlation_id AND a.source_channel = receipt.source_channel
          AND a.retention_class = 'programme-restricted' AND e.retention_class = a.retention_class
          AND e.organization_id = NEW.organization_id AND e.event_edition_id = NEW.edition_id
          AND e.actor_kind = 'account' AND e.actor_id = NEW.actor_id AND e.correlation_id = receipt.correlation_id
          AND e.aggregate_type = expected_aggregate AND e.aggregate_id = NEW.placement_id AND e.aggregate_version = NEW.sequence
          AND e.event_name = 'programme.item.changed.v1' AND e.schema_version = 1
          AND e.payload = jsonb_build_object('action', expected_action, 'layer', 'placement_decisions',
              'item_kind', i.kind, 'provenance', i.provenance_kind, 'lifecycle', 'active', 'concern', 'none')
          AND EXISTS (SELECT 1 FROM public.effects_outboxmessage b WHERE b.event_id = e.id AND b.organization_id = NEW.organization_id)
    ) THEN
        RAISE EXCEPTION 'Programme placement decision requires reciprocal receipt audit event and outbox' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$placement_decision_evidence$ LANGUAGE plpgsql VOLATILE CALLED ON NULL INPUT SECURITY INVOKER PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;

CREATE TRIGGER programme_placement_decision_guard BEFORE INSERT OR UPDATE OR DELETE
ON public.programme_programmeplacementdecision FOR EACH ROW
EXECUTE FUNCTION public.maru_guard_programme_placement_decision();
CREATE TRIGGER programme_placement_decision_truncate BEFORE TRUNCATE
ON public.programme_programmeplacementdecision FOR EACH STATEMENT
EXECUTE FUNCTION public.maru_refuse_programme_truncate();
CREATE CONSTRAINT TRIGGER programme_placement_decision_evidence AFTER INSERT
ON public.programme_programmeplacementdecision DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION public.maru_validate_programme_placement_decision_evidence();
REVOKE ALL ON FUNCTION public.maru_guard_programme_placement_decision(),
    public.maru_validate_programme_placement_decision_evidence() FROM PUBLIC;
"""

UNUSED_PREFLIGHT = r"""
LOCK TABLE public.programme_programmeplacementdecision IN ACCESS EXCLUSIVE MODE;
DO $unused_placement_decisions$
BEGIN
    IF EXISTS (SELECT 1 FROM public.programme_programmeplacementdecision) THEN
        RAISE EXCEPTION 'Retained Programme placement decisions require fix-forward recovery' USING ERRCODE = '23514';
    END IF;
END;
$unused_placement_decisions$;
"""
FORWARD_SQL = "\n".join((_receipt, _evidence, DECISION_SQL))
REVERSE_SQL = "\n".join(
    (
        UNUSED_PREFLIGHT,
        *(
            f"DROP TRIGGER programme_placement_decision_{suffix} ON public.{TABLE};"
            for suffix in ("guard", "truncate", "evidence")
        ),
        *(f"DROP FUNCTION public.{name}();" for name in NEW_FUNCTIONS),
        *(_previous_function(name) for name in REPLACED_FUNCTIONS),
    )
)


class Migration(migrations.Migration):
    """Keep operational decisions separate from private item-write admission."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("programme", "0013_placement_decisions"),
        ("workforce", "0021_programme_binding_downgrade_fence"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL)
    ]
