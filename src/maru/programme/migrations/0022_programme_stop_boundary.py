"""Freeze ordinary Programme writes while retaining exact personal privacy exits."""

# ruff: noqa: S608 -- Frozen, literal owner relation inventory.

from typing import Any, ClassVar

from django.db import migrations

GUARDED_MODELS = (
    "programmeeditioncontrol",
    "programmeitem",
    "programmeitemsourcebinding",
    "programmeworkingrevision",
    "programmedeliveryrevision",
    "programmedepartmentdiscussionentry",
    "programmereadinessrequirement",
    "programmereadinessrequirementrevision",
    "programmereadinessevidence",
    "programmepublicrendition",
    "programmepublicrenditionwithdrawal",
    "programmecommandreceipt",
    "programmehostrelationship",
    "programmehostinvitation",
    "programmehostrevision",
    "programmehostavailabilitywindow",
    "programmestaffingrequirement",
    "programmestaffingrevision",
    "programmeplacementdecision",
)
PRIVACY_MODELS = (
    "programmeitem",
    "programmereadinessrequirement",
    "programmehostrelationship",
    "programmehostrevision",
    "programmehostavailabilitywindow",
    "programmepublicrenditionwithdrawal",
    "programmecommandreceipt",
)
ARCHIVE_MODELS = (
    "programmearchivetask",
    "programmearchivetaskevent",
    "programmearchivechunk",
)

FORWARD_SQL = (
    r"""
CREATE FUNCTION public.maru_programme_stop_guard()
RETURNS trigger AS $$
DECLARE
    rows jsonb := '[]'::jsonb;
    body jsonb;
    scope record;
    edition record;
    stopped boolean := FALSE;
    privacy boolean := FALSE;
BEGIN
    IF TG_OP <> 'INSERT' THEN rows := rows || jsonb_build_array(to_jsonb(OLD)); END IF;
    IF TG_OP <> 'DELETE' THEN rows := rows || jsonb_build_array(to_jsonb(NEW)); END IF;
    FOR body IN SELECT value FROM jsonb_array_elements(rows) LOOP
        IF body->>'edition_id' IS NULL OR body->>'organization_id' IS NULL THEN
            RAISE EXCEPTION 'Programme stop boundary requires exact scope'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;
    FOR scope IN
        SELECT DISTINCT (value->>'edition_id')::uuid AS edition_id,
                        (value->>'organization_id')::uuid AS organization_id
        FROM jsonb_array_elements(rows) ORDER BY edition_id, organization_id
    LOOP
        SELECT e.adoption_profile_code, e.adoption_profile_version, e.lifecycle
          INTO edition FROM public.events_eventedition e
         WHERE e.id = scope.edition_id AND e.organization_id = scope.organization_id
         FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Programme stop boundary requires exact edition'
                USING ERRCODE = '23514';
        END IF;
        IF edition.adoption_profile_code = 'programme_operations' THEN
            IF edition.adoption_profile_version <> 1
               OR current_setting('transaction_isolation') <> 'read committed' THEN
                RAISE EXCEPTION 'Programme writes require current exact scope'
                    USING ERRCODE = '23514';
            END IF;
            stopped := stopped OR edition.lifecycle IN ('archived', 'cancelled');
        END IF;
    END LOOP;
    IF stopped THEN
        CASE TG_TABLE_NAME
        WHEN 'programme_programmeitem' THEN
            IF TG_OP = 'UPDATE' THEN
                privacy := NEW.aggregate_version = OLD.aggregate_version + 1
                    AND to_jsonb(NEW) - ARRAY[
                        'aggregate_version', 'last_modified_by_id', 'updated_at'
                    ] = to_jsonb(OLD) - ARRAY[
                        'aggregate_version', 'last_modified_by_id', 'updated_at'];
            END IF;
        WHEN 'programme_programmereadinessrequirement' THEN
            IF TG_OP = 'UPDATE' THEN
                privacy := NEW.concern IN ('host_confirmation', 'schedule_availability')
                    AND NEW.item_version > OLD.item_version
                    AND NEW.dependency_version = NEW.item_version
                    AND to_jsonb(NEW) - ARRAY[
                        'item_version', 'dependency_version',
                        'last_modified_by_id', 'updated_at'
                    ] = to_jsonb(OLD) - ARRAY[
                        'item_version', 'dependency_version',
                        'last_modified_by_id', 'updated_at'];
            END IF;
        WHEN 'programme_programmehostrelationship' THEN
            IF TG_OP = 'UPDATE' THEN
                privacy := NEW.version = OLD.version + 1
                    AND NEW.availability_version = OLD.availability_version + 1
                    AND NEW.item_version > OLD.item_version
                    AND NEW.last_modified_by_id = OLD.account_id
                    AND NEW.availability_state = 'withdrawn'
                    AND ((OLD.state = 'invited' AND NEW.state = 'declined')
                         OR (OLD.state = 'confirmed' AND NEW.state = 'withdrawn')
                         OR (OLD.state = 'confirmed' AND NEW.state = 'confirmed'
                             AND OLD.availability_state <> 'withdrawn'))
                    AND to_jsonb(NEW) - ARRAY[
                        'state', 'version', 'availability_state',
                        'availability_version', 'item_version',
                        'last_modified_by_id', 'updated_at'
                    ] = to_jsonb(OLD) - ARRAY[
                        'state', 'version', 'availability_state',
                        'availability_version', 'item_version',
                        'last_modified_by_id', 'updated_at'];
            END IF;
        WHEN 'programme_programmehostrevision' THEN
            IF TG_OP = 'INSERT' THEN
                privacy := NEW.period_count = 0
                    AND NEW.availability_state = 'withdrawn'
                    AND ((NEW.operation = 'host_respond'
                          AND NEW.state IN ('declined', 'withdrawn'))
                         OR (NEW.operation = 'host_availability'
                             AND NEW.state = 'confirmed'));
            END IF;
        WHEN 'programme_programmehostavailabilitywindow' THEN
            privacy := TG_OP = 'DELETE';
        WHEN 'programme_programmepublicrenditionwithdrawal' THEN
            privacy := TG_OP = 'INSERT';
        WHEN 'programme_programmecommandreceipt' THEN
            IF TG_OP = 'INSERT' THEN
                privacy := NEW.operation IN (
                    'host_respond', 'host_availability', 'public_rendition_withdraw');
            END IF;
        ELSE privacy := FALSE;
        END CASE;
        IF privacy IS DISTINCT FROM TRUE THEN
            RAISE EXCEPTION 'Stopped Programme refuses ordinary content writes'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_programme_stop_privacy_evidence()
RETURNS trigger AS $$
DECLARE
    body jsonb;
    checked_item_id uuid;
    checked_item_version bigint;
    checked_actor_id uuid;
    checked_host_id uuid;
    checked_host_version bigint;
    checked_result_id uuid;
    checked_receipt_id uuid;
    host public.programme_programmehostrelationship%ROWTYPE;
BEGIN
    IF TG_OP = 'DELETE' THEN body := to_jsonb(OLD); ELSE body := to_jsonb(NEW); END IF;
    PERFORM 1 FROM public.events_eventedition e
     WHERE e.id = (body->>'edition_id')::uuid
       AND e.organization_id = (body->>'organization_id')::uuid
       AND e.adoption_profile_code = 'programme_operations'
       AND e.adoption_profile_version = 1
       AND e.lifecycle IN ('archived', 'cancelled') FOR UPDATE;
    IF NOT FOUND THEN RETURN NULL; END IF;

    checked_item_id := (body->>'item_id')::uuid;
    checked_item_version := (body->>'item_version')::bigint;
    checked_actor_id := COALESCE(body->>'actor_id', body->>'last_modified_by_id')::uuid;
    CASE TG_TABLE_NAME
    WHEN 'programme_programmeitem' THEN
        checked_item_id := NEW.id; checked_item_version := NEW.aggregate_version;
    WHEN 'programme_programmehostrelationship' THEN
        checked_host_id := NEW.id; checked_host_version := NEW.version;
    WHEN 'programme_programmehostrevision' THEN
        checked_result_id := NEW.id;
        checked_host_id := NEW.host_id; checked_host_version := NEW.sequence;
    WHEN 'programme_programmehostavailabilitywindow' THEN
        SELECT h.* INTO host FROM public.programme_programmehostrelationship h
         WHERE h.id = OLD.host_id AND h.item_id = OLD.item_id
           AND h.organization_id = OLD.organization_id
           AND h.edition_id = OLD.edition_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Stopped privacy exit requires exact retained host'
                USING ERRCODE = '23514';
        END IF;
        checked_host_id := host.id; checked_host_version := host.version;
        checked_item_version := host.item_version;
        checked_actor_id := host.last_modified_by_id;
    WHEN 'programme_programmepublicrenditionwithdrawal' THEN
        checked_result_id := NEW.id;
    WHEN 'programme_programmecommandreceipt' THEN
        checked_receipt_id := NEW.id; checked_result_id := NEW.result_object_id;
        checked_item_version := NEW.resulting_item_version;
    ELSE NULL;
    END CASE;

    IF NOT EXISTS (
        SELECT 1 FROM public.programme_programmecommandreceipt c
          JOIN public.audit_auditevent a
            ON a.operation = 'programme.command.' || c.operation
           AND a.organization_id = c.organization_id
           AND a.event_edition_id = c.edition_id
           AND a.principal_kind = 'account' AND a.principal_context_id IS NULL
           AND a.principal_id = c.actor_id AND a.outcome = 'allow'
           AND a.target_type = 'programme.item' AND a.target_id = c.item_id
           AND a.correlation_id = c.correlation_id
           AND a.source_channel = c.source_channel
           AND a.idempotency_key_hash = encode(
               sha256(convert_to(c.idempotency_key::text, 'UTF8')), 'hex')
           AND a.retention_class = 'programme-restricted'
          JOIN public.audit_auditnativemutationwitness w ON w.audit_event_id = a.id
           AND w.transaction_stamp =
               public.maru_audit_current_native_transaction_stamp()
          LEFT JOIN public.programme_programmehostrevision r
            ON r.id = c.result_object_id
           AND r.item_id = c.item_id AND r.item_version = c.resulting_item_version
           AND r.organization_id = c.organization_id AND r.edition_id = c.edition_id
           AND r.actor_id = c.actor_id AND r.operation = c.operation
           AND r.reason = c.reason
          LEFT JOIN public.programme_programmehostrelationship h ON h.id = r.host_id
           AND h.item_id = r.item_id AND h.organization_id = r.organization_id
           AND h.edition_id = r.edition_id AND h.account_id = r.actor_id
         WHERE c.organization_id = (body->>'organization_id')::uuid
           AND c.edition_id = (body->>'edition_id')::uuid
           AND c.item_id = checked_item_id
           AND c.resulting_item_version = checked_item_version
           AND c.actor_id = checked_actor_id AND c.resulting_control_version IS NULL
           AND (checked_receipt_id IS NULL OR c.id = checked_receipt_id)
           AND (checked_result_id IS NULL OR c.result_object_id = checked_result_id)
           AND (
             (c.operation IN ('host_respond', 'host_availability')
              AND TG_TABLE_NAME <> 'programme_programmepublicrenditionwithdrawal'
              AND c.expected_version = c.resulting_item_version - 1
              AND h.id IS NOT NULL AND r.availability_state = 'withdrawn'
              AND r.period_count = 0
              AND (checked_host_id IS NULL OR r.host_id = checked_host_id)
              AND (checked_host_version IS NULL OR r.sequence = checked_host_version)
              AND ((c.operation = 'host_respond'
                    AND r.state IN ('declined', 'withdrawn')
                    AND a.capability_code = 'programme.respond_host_self'
                    AND a.changed_fields = ARRAY['host_relationship']::varchar[])
                   OR (c.operation = 'host_availability' AND r.state = 'confirmed'
                       AND a.capability_code = 'programme.manage_host_availability_self'
                       AND a.changed_fields = ARRAY['host_availability']::varchar[]))
              AND (TG_TABLE_NAME <> 'programme_programmereadinessrequirement'
                   OR body->>'concern' = 'schedule_availability'
                   OR (body->>'concern' = 'host_confirmation'
                       AND c.operation = 'host_respond')))
             OR (c.operation = 'public_rendition_withdraw'
                 AND TG_TABLE_NAME IN ('programme_programmepublicrenditionwithdrawal',
                                      'programme_programmecommandreceipt')
                 AND a.capability_code = 'programme.approve_public_copy'
                 AND a.changed_fields = ARRAY['public_rendition_withdrawal']::varchar[]
                 AND c.expected_version = c.resulting_item_version)
           )
    ) THEN
        RAISE EXCEPTION 'Stopped Programme privacy exit requires exact native evidence'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION public.maru_programme_stop_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_programme_stop_privacy_evidence() FROM PUBLIC;
"""
    + "\n".join(
        f"CREATE TRIGGER a00_programme_stop_{index} "
        f"BEFORE INSERT OR UPDATE OR DELETE ON public.programme_{model} "
        "FOR EACH ROW EXECUTE FUNCTION public.maru_programme_stop_guard();"
        for index, model in enumerate(GUARDED_MODELS)
    )
    + "\n"
    + "\n".join(
        f"CREATE CONSTRAINT TRIGGER programme_stop_privacy_{index} "
        f"AFTER INSERT OR UPDATE OR DELETE ON public.programme_{model} "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION public.maru_programme_stop_privacy_evidence();"
        for index, model in enumerate(PRIVACY_MODELS)
    )
)

REVERSE_SQL = (
    "\n".join(
        f"DROP TRIGGER programme_stop_privacy_{index} ON public.programme_{model};"
        for index, model in reversed(tuple(enumerate(PRIVACY_MODELS)))
    )
    + "\n"
    + "\n".join(
        f"DROP TRIGGER a00_programme_stop_{index} ON public.programme_{model};"
        for index, model in reversed(tuple(enumerate(GUARDED_MODELS)))
    )
    + (
        "\nDROP FUNCTION public.maru_programme_stop_privacy_evidence();"
        "\nDROP FUNCTION public.maru_programme_stop_guard();"
    )
)


def refuse_used_stop_boundary_downgrade(apps: Any, schema_editor: Any) -> None:
    """Retain the complete privacy boundary once stop evidence is used."""
    schema_editor.execute(
        "LOCK TABLE public.events_programmestopreceipt IN ACCESS EXCLUSIVE MODE"
    )
    if apps.get_model("events", "ProgrammeStopReceipt").objects.exists():
        raise RuntimeError(
            "Programme stop evidence exists; retain guards and fix forward."
        )


class Migration(migrations.Migration):
    """Install explicit operational closure without weakening archive custody."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("programme", "0021_exit_archive_integrity"),
        ("events", "0015_programme_stop_receipt"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_used_stop_boundary_downgrade
        ),
    ]
