"""Refuse terminal Programme issuance while retaining exact audited revocation."""

# ruff: noqa: S608 -- identifiers come only from the frozen owner inventory.

from typing import Any, ClassVar

from django.db import migrations

GUARDED_MODELS = (
    "capabilitygrant",
    "roleassignment",
    "scopedresourcebinding",
    "programmerolerequest",
    "programmeroledecisionrecord",
)
REVOCABLE_MODELS = ("capabilitygrant", "roleassignment")

FORWARD_SQL = (
    r"""
CREATE FUNCTION public.maru_authorization_programme_stop_guard()
RETURNS trigger AS $$
DECLARE
    rows jsonb := '[]'::jsonb;
    scopes jsonb := '[]'::jsonb;
    body jsonb;
    parent_id uuid;
    organization_id uuid;
    scope record;
    edition record;
    stopped boolean := FALSE;
    retained_revocation boolean := FALSE;
    expected_operation text;
    expected_target_type text;
BEGIN
    IF TG_OP <> 'INSERT' THEN rows := rows || jsonb_build_array(to_jsonb(OLD)); END IF;
    IF TG_OP <> 'DELETE' THEN rows := rows || jsonb_build_array(to_jsonb(NEW)); END IF;
    FOR body IN SELECT value FROM jsonb_array_elements(rows) LOOP
        parent_id := NULL;
        organization_id := NULL;
        IF TG_TABLE_NAME = 'authorization_programmeroledecisionrecord' THEN
            SELECT r.programme_edition_id, r.organization_id
              INTO parent_id, organization_id
              FROM public.authorization_programmerolerequest r
             WHERE r.id = (body->>'request_id')::uuid;
        ELSE
            organization_id := (body->>'organization_id')::uuid;
            parent_id := (body->>CASE
                WHEN TG_TABLE_NAME = 'authorization_programmerolerequest'
                THEN 'programme_edition_id' ELSE 'edition_id' END)::uuid;
        END IF;
        IF parent_id IS NULL
           AND TG_TABLE_NAME IN ('authorization_capabilitygrant',
                                 'authorization_roleassignment') THEN
            -- The actual grant scope, not a guessed Programme origin, governs.
            -- Existing shape/provenance guards still validate shared authority.
            CONTINUE;
        END IF;
        IF parent_id IS NULL OR organization_id IS NULL THEN
            RAISE EXCEPTION 'Authority stop boundary requires an exact parent scope'
                USING ERRCODE = '23514';
        END IF;
        scopes := scopes || jsonb_build_array(jsonb_build_object(
            'edition_id', parent_id, 'organization_id', organization_id));
    END LOOP;
    FOR scope IN
        SELECT DISTINCT (value->>'edition_id')::uuid AS edition_id,
                        (value->>'organization_id')::uuid AS organization_id
        FROM jsonb_array_elements(scopes) ORDER BY edition_id, organization_id
    LOOP
        SELECT e.adoption_profile_code, e.adoption_profile_version, e.lifecycle
          INTO edition FROM public.events_eventedition e
         WHERE e.id = scope.edition_id AND e.organization_id = scope.organization_id
         FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Authority stop boundary requires an exact edition scope'
                USING ERRCODE = '23514';
        END IF;
        IF edition.adoption_profile_code = 'programme_operations' THEN
            IF edition.adoption_profile_version <> 1
               OR current_setting('transaction_isolation') <> 'read committed' THEN
                RAISE EXCEPTION 'Programme authority requires current exact scope'
                    USING ERRCODE = '23514';
            END IF;
            stopped := stopped OR edition.lifecycle IN ('archived', 'cancelled');
        END IF;
    END LOOP;
    IF stopped THEN
        IF TG_OP = 'UPDATE' AND TG_TABLE_NAME IN (
            'authorization_capabilitygrant', 'authorization_roleassignment'
        ) THEN
            retained_revocation :=
                to_jsonb(OLD)->>'revoked_at' IS NULL
                AND to_jsonb(NEW)->>'revoked_at' IS NOT NULL
                AND to_jsonb(NEW)->>'revoked_by_id' IS NOT NULL
                AND btrim(to_jsonb(NEW)->>'revocation_reason') <> ''
                AND to_jsonb(NEW) - ARRAY[
                    'revoked_at', 'revoked_by_id', 'revocation_reason', 'updated_at'
                ] = to_jsonb(OLD) - ARRAY[
                    'revoked_at', 'revoked_by_id', 'revocation_reason', 'updated_at'
                ];
        END IF;
        IF retained_revocation IS DISTINCT FROM TRUE THEN
            RAISE EXCEPTION 'Stopped Programme refuses fresh or changed authority'
                USING ERRCODE = '23514';
        END IF;
        IF TG_WHEN = 'AFTER' THEN
            expected_operation := CASE TG_TABLE_NAME
                WHEN 'authorization_capabilitygrant'
                THEN 'authorization.capability.revoke'
                ELSE 'authorization.role.revoke' END;
            expected_target_type := CASE TG_TABLE_NAME
                WHEN 'authorization_capabilitygrant'
                THEN 'authorization.capability_grant'
                ELSE 'authorization.role_assignment' END;
            IF NOT EXISTS (
                SELECT 1 FROM public.audit_auditevent a
                  JOIN public.audit_auditnativemutationwitness w
                    ON w.audit_event_id = a.id
                 WHERE a.operation = expected_operation
                   AND a.target_type = expected_target_type
                   AND a.target_id = NEW.id AND a.outcome = 'allow'
                   AND a.principal_kind = 'account'
                   AND a.principal_context_id IS NULL
                   AND a.principal_id = NEW.revoked_by_id
                   AND a.organization_id = NEW.organization_id
                   AND a.event_edition_id = NEW.edition_id
                   AND a.capability_code = 'authorization.revoke'
                   AND a.changed_fields = ARRAY['revoked_at']::varchar[]
                   AND a.retention_class = 'security-extended'
                   AND w.transaction_stamp =
                       public.maru_audit_current_native_transaction_stamp()
            ) THEN
                RAISE EXCEPTION 'Stopped authority revocation requires native audit'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
    END IF;
    IF TG_WHEN = 'AFTER' THEN RETURN NULL; END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION public.maru_authorization_programme_stop_guard() FROM PUBLIC;
"""
    + "\n".join(
        f"CREATE TRIGGER a00_authorization_programme_stop_{index} "
        f"BEFORE INSERT OR UPDATE OR DELETE ON public.authorization_{model} "
        "FOR EACH ROW EXECUTE FUNCTION "
        "public.maru_authorization_programme_stop_guard();"
        for index, model in enumerate(GUARDED_MODELS)
    )
    + "\n"
    + "\n".join(
        f"CREATE CONSTRAINT TRIGGER authorization_programme_stop_revoke_{index} "
        f"AFTER UPDATE ON public.authorization_{model} "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION public.maru_authorization_programme_stop_guard();"
        for index, model in enumerate(REVOCABLE_MODELS)
    )
)

REVERSE_SQL = (
    "\n".join(
        f"DROP TRIGGER authorization_programme_stop_revoke_{index} "
        f"ON public.authorization_{model};"
        for index, model in reversed(tuple(enumerate(REVOCABLE_MODELS)))
    )
    + "\n"
    + "\n".join(
        f"DROP TRIGGER a00_authorization_programme_stop_{index} "
        f"ON public.authorization_{model};"
        for index, model in reversed(tuple(enumerate(GUARDED_MODELS)))
    )
    + "\nDROP FUNCTION public.maru_authorization_programme_stop_guard();"
)


def refuse_used_stop_boundary_downgrade(apps: Any, schema_editor: Any) -> None:
    """Retain issuance and revocation enforcement once stop evidence is used."""
    schema_editor.execute(
        "LOCK TABLE public.events_programmestopreceipt IN ACCESS EXCLUSIVE MODE"
    )
    if apps.get_model("events", "ProgrammeStopReceipt").objects.exists():
        raise RuntimeError(
            "Programme stop evidence exists; retain guards and fix forward."
        )


class Migration(migrations.Migration):
    """Preserve independent shared grants and exact security-only revocation."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0039_accountable_representation_lineage"),
        ("events", "0015_programme_stop_receipt"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_used_stop_boundary_downgrade
        ),
    ]
