"""Close Programme terminal transitions over exact receipts and all owner fences."""

from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations


def refuse_used_stop_downgrade(apps: Any, schema_editor: Any) -> None:
    """Retain completed terminal evidence and its reciprocal native admission."""
    schema_editor.execute(
        "LOCK TABLE public.events_programmestopreceipt IN ACCESS EXCLUSIVE MODE"
    )
    if apps.get_model("events", "ProgrammeStopReceipt").objects.exists():
        raise RuntimeError("Programme stop evidence exists; retain it and fix forward.")


FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_validate_edition_lifecycle_version()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.lifecycle <> 'draft' OR NEW.lifecycle_version <> 0 THEN
            RAISE EXCEPTION 'new editions must start at draft lifecycle version zero'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.lifecycle = OLD.lifecycle THEN
        IF NEW.lifecycle_version <> OLD.lifecycle_version THEN
            RAISE EXCEPTION 'lifecycle version changes only with lifecycle'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.lifecycle_version <> OLD.lifecycle_version + 1 THEN
        RAISE EXCEPTION 'lifecycle change must increment lifecycle version'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.adoption_profile_code = 'programme_operations'
       AND NEW.lifecycle IN ('archived', 'cancelled') THEN
        IF OLD.adoption_profile_version <> 1 OR NEW.lifecycle <> 'archived'
           OR OLD.lifecycle NOT IN ('draft', 'preparing', 'ready', 'live', 'closing')
           OR NEW.aggregate_version <> OLD.aggregate_version + 1
           OR current_setting('transaction_isolation') <> 'read committed'
           OR (to_jsonb(NEW) - ARRAY['lifecycle', 'lifecycle_version',
                                    'aggregate_version', 'updated_at'])
              IS DISTINCT FROM
              (to_jsonb(OLD) - ARRAY['lifecycle', 'lifecycle_version',
                                    'aggregate_version', 'updated_at']) THEN
            RAISE EXCEPTION 'Programme requires its exact accountable stop transition'
                USING ERRCODE = '23514';
        END IF;
        -- The deferred reciprocal guard requires the complete same-transaction
        -- receipt. This shape check alone cannot commit a terminal transition.
        RETURN NEW;
    END IF;
    IF (OLD.lifecycle = 'draft' AND NEW.lifecycle IN ('preparing', 'cancelled'))
       OR (OLD.lifecycle = 'preparing' AND NEW.lifecycle IN ('draft', 'ready',
        'cancelled'))
       OR (OLD.lifecycle = 'ready' AND NEW.lifecycle IN ('preparing', 'live',
        'cancelled'))
       OR (OLD.lifecycle = 'live' AND NEW.lifecycle = 'closing')
       OR (OLD.lifecycle = 'closing' AND NEW.lifecycle = 'archived') THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'invalid event edition lifecycle transition'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;

DROP TRIGGER events_lifecycle_version_guard ON public.events_eventedition;
CREATE TRIGGER events_lifecycle_version_guard
BEFORE INSERT OR UPDATE ON public.events_eventedition
FOR EACH ROW EXECUTE FUNCTION public.maru_validate_edition_lifecycle_version();

CREATE FUNCTION public.maru_programme_stop_transition_guard()
RETURNS trigger AS $$
BEGIN
    IF OLD.adoption_profile_code <> 'programme_operations'
       OR NEW.lifecycle NOT IN ('archived', 'cancelled')
       OR NEW.lifecycle = OLD.lifecycle THEN RETURN NULL; END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.events_programmestopreceipt r
        JOIN public.audit_auditnativemutationwitness w ON w.audit_event_id =
        r.source_audit_id
        WHERE r.edition_id = NEW.id AND r.organization_id = NEW.organization_id
          AND NEW.lifecycle = 'archived' AND NEW.adoption_profile_version = 1
          AND r.previous_lifecycle = OLD.lifecycle
          AND r.expected_aggregate_version = OLD.aggregate_version
          AND r.expected_lifecycle_version = OLD.lifecycle_version
          AND w.transaction_stamp = public.maru_audit_current_native_transaction_stamp()
    ) THEN
        RAISE EXCEPTION 'Programme terminal transition requires its exact stop receipt'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;

CREATE CONSTRAINT TRIGGER events_programme_stop_transition
AFTER UPDATE ON public.events_eventedition
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_programme_stop_transition_guard();

CREATE OR REPLACE FUNCTION public.maru_programme_stop_receipt_guard()
RETURNS trigger AS $$
DECLARE
    preview jsonb;
    authority jsonb;
    scheduling jsonb;
    withdrawal jsonb;
    inventory jsonb;
    collection jsonb;
    assignment jsonb;
    state_count jsonb;
    total_states integer;
    expected_owner text;
    expected_count integer;
    position integer;
    intent jsonb;
    pointer public.scheduling_schedulingreleasepointer%ROWTYPE;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Programme stop receipts are immutable' USING ERRCODE = '23514';
    END IF;
    IF COALESCE(current_setting('transaction_isolation') <> 'read committed'
       OR NEW.id = '00000000-0000-0000-0000-000000000000'::uuid
       OR NEW.idempotency_key = '00000000-0000-0000-0000-000000000000'::uuid
       OR NEW.correlation_id = '00000000-0000-0000-0000-000000000000'::uuid
       OR NEW.source_channel !~ '^[a-z][a-z0-9_-]{0,31}$'
       OR btrim(NEW.reason) = '' OR NEW.reason ~ '[[:cntrl:]]'
       OR NEW.reason <> normalize(NEW.reason, NFC)
       OR NEW.reason <> regexp_replace(btrim(NEW.reason), '[[:space:]]+', ' ', 'g')
       OR NOT public.maru_scheduling_exact_keys(
            NEW.impact_document, ARRAY['preview', 'withdrawal'])
       OR octet_length(NEW.impact_document::text) > 8388608, true) THEN
        RAISE EXCEPTION 'Programme stop requires exact bounded intent' USING ERRCODE
        = '23514';
    END IF;
    preview := NEW.impact_document->'preview';
    withdrawal := NEW.impact_document->'withdrawal';
    IF COALESCE(NOT public.maru_scheduling_exact_keys(preview, ARRAY[
        'contract', 'actor_id', 'organization_id', 'edition_id', 'lifecycle',
        'aggregate_version', 'lifecycle_version', 'authority', 'scheduling',
        'inventories'])
       OR preview->>'contract' IS DISTINCT FROM 'events.programme-stop-preview@1'
       OR preview->>'actor_id' IS DISTINCT FROM NEW.actor_id::text
       OR preview->>'organization_id' IS DISTINCT FROM NEW.organization_id::text
       OR preview->>'edition_id' IS DISTINCT FROM NEW.edition_id::text
       OR preview->>'lifecycle' IS DISTINCT FROM NEW.previous_lifecycle
       OR preview->'aggregate_version' IS DISTINCT FROM
        to_jsonb(NEW.expected_aggregate_version)
       OR preview->'lifecycle_version' IS DISTINCT FROM
        to_jsonb(NEW.expected_lifecycle_version)
       OR jsonb_typeof(preview->'inventories') IS DISTINCT FROM 'array'
       OR jsonb_array_length(preview->'inventories') <> 5
       OR NEW.preview_fingerprint IS DISTINCT FROM encode(sha256(convert_to(
           public.maru_scheduling_canonical_json(preview), 'UTF8')), 'hex')
       OR octet_length(convert_to(public.maru_scheduling_canonical_json(preview),
        'UTF8'))
          > 4194304, true) THEN
        RAISE EXCEPTION 'Programme stop preview is incomplete or mismatched'
            USING ERRCODE = '23514';
    END IF;
    authority := preview->'authority';
    scheduling := preview->'scheduling';
    IF COALESCE(NOT public.maru_scheduling_exact_keys(authority, ARRAY[
            'assignments', 'pending_requests', 'expired_requests', 'decided_requests',
            'source_fingerprint'])
       OR authority->>'source_fingerprint' !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(authority->'assignments') IS DISTINCT FROM 'array'
       OR jsonb_array_length(authority->'assignments') > 4000
       OR authority->>'pending_requests' !~ '^(0|[1-9][0-9]{0,3})$'
       OR authority->>'expired_requests' !~ '^(0|[1-9][0-9]{0,3})$'
       OR authority->>'decided_requests' !~ '^(0|[1-9][0-9]{0,3})$'
       OR (authority->>'pending_requests')::integer
          + (authority->>'expired_requests')::integer
          + (authority->>'decided_requests')::integer > 2000
       OR NOT public.maru_scheduling_exact_keys(scheduling, ARRAY[
            'inventory', 'active_release_id', 'pointer_version',
        'withdrawal_authorized'])
       OR jsonb_typeof(scheduling->'withdrawal_authorized') IS DISTINCT FROM 'boolean'
       OR scheduling->>'pointer_version' !~ '^(0|[1-9][0-9]{0,18})$'
       OR jsonb_typeof(scheduling->'pointer_version') <> 'number'
       OR jsonb_typeof(authority->'pending_requests') <> 'number'
       OR jsonb_typeof(authority->'expired_requests') <> 'number'
       OR jsonb_typeof(authority->'decided_requests') <> 'number', true) THEN
        RAISE EXCEPTION 'Programme stop authority or release accounting is incomplete'
            USING ERRCODE = '23514';
    END IF;
    FOR assignment IN SELECT value FROM
        jsonb_array_elements(authority->'assignments') LOOP
        IF COALESCE(NOT public.maru_scheduling_exact_keys(assignment, ARRAY[
            'kind', 'id', 'scope_level', 'department_id', 'resource_binding_id',
            'disposition', 'source_fingerprint'])
           OR assignment->>'kind' NOT IN ('capability_grant', 'role_assignment')
           OR assignment->>'scope_level' NOT IN ('organization', 'edition',
        'department', 'resource')
           OR assignment->>'disposition' NOT IN (
               'retained_historical', 'retained_shared', 'already_inactive',
        'separately_revoked')
           OR assignment->>'source_fingerprint' !~ '^[0-9a-f]{64}$'
           OR (assignment->>'id')::uuid IS NULL, true) THEN
            RAISE EXCEPTION 'Programme stop assignment accounting is invalid'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;
    FOR position IN 0..5 LOOP
        expected_owner := (ARRAY['applications', 'programme', 'workforce', 'venues',
                                 'effects', 'scheduling'])[position + 1];
        expected_count := (ARRAY[43, 22, 22, 9, 4, 27])[position + 1];
        inventory := CASE WHEN position = 5 THEN scheduling->'inventory'
                     ELSE preview->'inventories'->position END;
        IF COALESCE(NOT public.maru_scheduling_exact_keys(inventory, ARRAY[
                'owner', 'collections', 'source_fingerprint'])
           OR inventory->>'owner' IS DISTINCT FROM expected_owner
           OR inventory->>'source_fingerprint' !~ '^[0-9a-f]{64}$'
           OR jsonb_typeof(inventory->'collections') IS DISTINCT FROM 'array'
           OR jsonb_array_length(inventory->'collections') <> expected_count
           OR (SELECT count(DISTINCT item->>'code')
                 FROM jsonb_array_elements(inventory->'collections') item) <>
        expected_count,
           true) THEN
            RAISE EXCEPTION 'Programme stop requires every complete owner inventory'
                USING ERRCODE = '23514';
        END IF;
        FOR collection IN SELECT value FROM
        jsonb_array_elements(inventory->'collections') LOOP
            IF COALESCE(NOT public.maru_scheduling_exact_keys(collection,
        ARRAY['code', 'total', 'states'])
               OR collection->>'code' !~ '^[a-z][a-z0-9_]{0,63}$'
               OR collection->>'total' !~ '^(0|[1-9][0-9]{0,4})$'
               OR (collection->>'total')::integer > 10000
               OR jsonb_typeof(collection->'total') <> 'number'
               OR jsonb_typeof(collection->'states') IS DISTINCT FROM 'array'
               OR jsonb_array_length(collection->'states') > 32, true) THEN
                RAISE EXCEPTION 'Programme stop collection accounting is invalid'
                    USING ERRCODE = '23514';
            END IF;
            total_states := 0;
            FOR state_count IN SELECT value FROM
        jsonb_array_elements(collection->'states') LOOP
                IF COALESCE(jsonb_typeof(state_count) <> 'array'
                   OR jsonb_array_length(state_count) <> 2
                   OR jsonb_typeof(state_count->0) <> 'string'
                   OR state_count->>0 !~ '^[a-z][a-z0-9_]{0,63}$'
                   OR jsonb_typeof(state_count->1) <> 'number'
                   OR state_count->>1 !~ '^[1-9][0-9]{0,4}$', true) THEN
                    RAISE EXCEPTION 'Programme stop state accounting is invalid'
                        USING ERRCODE = '23514';
                END IF;
                total_states := total_states + (state_count->>1)::integer;
            END LOOP;
            IF total_states <> 0 AND total_states <> (collection->>'total')::integer
        THEN
                RAISE EXCEPTION 'Programme stop state counts must be complete'
                    USING ERRCODE = '23514';
            END IF;
        END LOOP;
    END LOOP;
    intent := jsonb_build_object(
        'contract', 'events.programme-stop@1', 'profile',
        jsonb_build_array('programme_operations', 1),
        'actor_id', NEW.actor_id, 'organization_id', NEW.organization_id,
        'edition_id', NEW.edition_id, 'idempotency_key', NEW.idempotency_key,
        'expected_aggregate_version', NEW.expected_aggregate_version,
        'expected_lifecycle_version', NEW.expected_lifecycle_version,
        'preview_fingerprint', NEW.preview_fingerprint, 'reason', NEW.reason);
    IF NEW.request_digest IS DISTINCT FROM encode(sha256(convert_to(
        public.maru_scheduling_canonical_json(intent), 'UTF8')), 'hex') THEN
        RAISE EXCEPTION 'Programme stop requires its original canonical intent'
            USING ERRCODE = '23514';
    END IF;
    PERFORM 1 FROM public.events_eventedition e
      JOIN public.organizations_conventionseries s ON s.id = e.series_id
      JOIN public.organizations_organization o ON o.id = e.organization_id
     WHERE e.id = NEW.edition_id AND e.organization_id = NEW.organization_id
       AND s.organization_id = NEW.organization_id AND s.is_active
       AND o.lifecycle = 'active' AND e.adoption_profile_code = 'programme_operations'
       AND e.adoption_profile_version = 1 AND e.lifecycle = 'archived'
       AND e.aggregate_version = NEW.expected_aggregate_version + 1
       AND e.lifecycle_version = NEW.expected_lifecycle_version + 1;
    IF NOT FOUND OR NOT EXISTS (
        SELECT 1 FROM public.identity_account a WHERE a.id = NEW.actor_id
          AND a.is_active AND a.account_kind = 'person' AND a.email_verified_at IS
        NOT NULL
    ) OR NOT EXISTS (
        SELECT 1 FROM public.events_editionlifecycletransition t
         WHERE t.id = NEW.transition_id AND t.edition_id = NEW.edition_id
           AND t.actor_id = NEW.actor_id AND t.reason = NEW.reason
           AND t.from_state = NEW.previous_lifecycle AND t.to_state = 'archived'
    ) OR NOT EXISTS (
        SELECT 1 FROM public.audit_auditevent a
        JOIN public.audit_auditnativemutationwitness w ON w.audit_event_id = a.id
        WHERE a.id = NEW.source_audit_id AND a.principal_kind = 'account'
          AND a.principal_id = NEW.actor_id AND a.principal_context_id IS NULL
          AND a.organization_id = NEW.organization_id AND a.event_edition_id =
        NEW.edition_id
          AND a.capability_code = 'events.transition' AND a.operation =
        'events.edition.transition'
          AND a.target_type = 'events.event_edition' AND a.target_id = NEW.edition_id
          AND a.outcome = 'allow' AND a.reason_code = 'programme_stop_confirmed'
          AND a.correlation_id = NEW.correlation_id AND a.source_channel =
        NEW.source_channel
          AND a.retention_class = 'programme-restricted' AND NOT a.break_glass
          AND a.changed_fields = ARRAY['lifecycle', 'lifecycle_version',
        'aggregate_version']::varchar[]
          AND a.idempotency_key_hash =
        encode(sha256(convert_to(NEW.idempotency_key::text, 'UTF8')), 'hex')
          AND w.transaction_stamp = public.maru_audit_current_native_transaction_stamp()
    ) OR NOT EXISTS (
        SELECT 1 FROM public.effects_domainevent d
         WHERE d.event_name = 'events.edition.lifecycle_transitioned.v1' AND
        d.schema_version = 1
           AND d.organization_id = NEW.organization_id AND d.event_edition_id =
        NEW.edition_id
           AND d.aggregate_type = 'events.event_edition' AND d.aggregate_id =
        NEW.edition_id
           AND d.aggregate_version = NEW.expected_aggregate_version + 1
           AND d.actor_kind = 'account' AND d.actor_id = NEW.actor_id
           AND d.correlation_id = NEW.correlation_id AND d.causation_id =
        NEW.source_audit_id
           AND d.payload = jsonb_build_object('from_state', NEW.previous_lifecycle,
        'to_state', 'archived')
    ) THEN
        RAISE EXCEPTION 'Programme stop requires exact same-transaction owner evidence'
            USING ERRCODE = '23514';
    END IF;
    SELECT p.* INTO pointer FROM public.scheduling_schedulingreleasepointer p
     WHERE p.organization_id = NEW.organization_id AND p.edition_id = NEW.edition_id;
    IF pointer.active_release_id IS NOT NULL THEN
        RAISE EXCEPTION 'Programme stop cannot retain an active release pointer'
            USING ERRCODE = '23514';
    END IF;
    IF scheduling->'active_release_id' = 'null'::jsonb THEN
        IF withdrawal IS DISTINCT FROM 'null'::jsonb
           OR COALESCE(pointer.version, 0) <>
        (scheduling->>'pointer_version')::bigint THEN
            RAISE EXCEPTION 'Programme stop cannot invent a release withdrawal'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        IF COALESCE(scheduling->'withdrawal_authorized' IS DISTINCT FROM 'true'::jsonb
           OR NOT public.maru_scheduling_exact_keys(withdrawal, ARRAY[
               'receipt_id', 'object_id', 'version', 'control_version'])
           OR NOT EXISTS (
                SELECT 1 FROM public.scheduling_schedulingreleasewithdrawal w
                JOIN public.scheduling_schedulingcommandreceipt r ON r.id =
        w.command_receipt_id
                WHERE w.id = (withdrawal->>'object_id')::uuid
                  AND r.id = (withdrawal->>'receipt_id')::uuid
                  AND r.id = pointer.command_receipt_id AND r.operation =
        'release_withdraw'
                  AND r.organization_id = NEW.organization_id AND r.edition_id =
        NEW.edition_id
                  AND r.actor_id = NEW.actor_id AND r.idempotency_key =
        NEW.idempotency_key
                  AND r.reason = NEW.reason AND r.correlation_id = NEW.correlation_id
                  AND r.source_channel = NEW.source_channel
                  AND w.organization_id = NEW.organization_id AND w.edition_id =
        NEW.edition_id
                  AND w.actor_id = NEW.actor_id AND w.reason = NEW.reason
                  AND w.release_id = (scheduling->>'active_release_id')::uuid
                  AND w.pointer_version = (scheduling->>'pointer_version')::bigint + 1
                  AND w.pointer_version = pointer.version
                  AND r.result_object_id = w.id AND r.resulting_version =
        w.pointer_version
                  AND withdrawal->'version' = to_jsonb(w.pointer_version)
                  AND withdrawal->'control_version' = to_jsonb(r.control_version)
                  AND EXISTS (
                      SELECT 1 FROM public.audit_auditevent a
                      JOIN public.audit_auditnativemutationwitness n ON
        n.audit_event_id = a.id
                      WHERE a.operation = 'scheduling.command.release_withdraw'
                        AND a.outcome = 'allow' AND a.target_id = w.id
                        AND a.principal_id = NEW.actor_id
                        AND a.organization_id = NEW.organization_id
                        AND a.event_edition_id = NEW.edition_id
                        AND a.correlation_id = NEW.correlation_id
                        AND n.transaction_stamp =
        public.maru_audit_current_native_transaction_stamp()
                  )
           ), true) THEN
            RAISE EXCEPTION
        'Programme stop requires its actual authorized release withdrawal'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;

REVOKE ALL ON FUNCTION public.maru_validate_edition_lifecycle_version() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_programme_stop_transition_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_programme_stop_receipt_guard() FROM PUBLIC;
"""

_LEGACY = import_module("maru.events.migrations.0004_lifecycle_integrity_guards")
_DORMANT = import_module("maru.events.migrations.0015_programme_stop_receipt")
REVERSE_SQL = (
    "DROP TRIGGER events_programme_stop_transition ON public.events_eventedition;\n"
    "DROP FUNCTION public.maru_programme_stop_transition_guard();\n"
    "DROP TRIGGER events_lifecycle_version_guard ON public.events_eventedition;\n"
    "DROP FUNCTION public.maru_validate_edition_lifecycle_version();\n"
    + _LEGACY.FORWARD_SQL.split(
        "CREATE FUNCTION maru_prevent_lifecycle_transition_mutation"
    )[0]
    + _DORMANT.FORWARD_SQL.split("CREATE TRIGGER events_programme_stop_receipt_guard")[
        0
    ].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
)


class Migration(migrations.Migration):
    """Require every native owner fence before admitting an accountable stop."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("events", "0015_programme_stop_receipt"),
        ("applications", "0023_programme_stop_boundary"),
        ("authorization", "0040_programme_stop_boundary"),
        ("programme", "0022_programme_stop_boundary"),
        ("scheduling", "0023_programme_stop_boundary"),
        ("venues", "0009_programme_stop_boundary"),
        ("workforce", "0030_programme_stop_boundary"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(migrations.RunPython.noop, refuse_used_stop_downgrade),
    ]
