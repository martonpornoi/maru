"""Close stopped Programme intake/review while retaining exact cleanup evidence."""

# ruff: noqa: S608 -- SQL identifiers and scope paths are literal frozen inventory.

from typing import Any, ClassVar

from django.db import migrations

DIRECT_MODELS = (
    "applicationdefinition",
    "applicationsubmission",
    "applicationfilereceipt",
    "applicationcommandreceipt",
    "programmecall",
    "programmecalltrack",
    "programmecallformat",
    "programmecallcontributorfield",
    "programmeproposal",
    "programmeproposalselectionrevision",
    "programmeproposalcollaborator",
    "programmeproposalcollaboratortransition",
    "programmeproposalcontributorprofilerevision",
    "programmeproposalrevision",
    "programmeproposalrevisionanswer",
    "programmeproposalrevisioncontributor",
    "programmeproposalrevisionresponse",
    "programmecommandreceipt",
    "programmeimportbatch",
    "programmeimportitem",
    "programmeimportpreviewrevision",
    "programmeimportpreviewitemresult",
    "programmeimportsourcebinding",
    "programmeimportappliedcommand",
    "programmeimportcommandreceipt",
    "programmereviewreceipt",
    "programmefileintake",
    "programmeacceptedtransition",
)
DEFINITION_CHILDREN = (
    "applicationownerdepartment",
    "applicationreviewerrole",
    "applicationreviewerperson",
    "applicationsection",
    "applicationquestion",
)
SUBMISSION_CHILDREN = (
    "applicationanswerrevision",
    "applicationreviewdecision",
    "applicationtargetrecord",
)
REVIEW_CHILDREN = (
    "programmereviewpolicy",
    "programmereviewcase",
    "programmereviewassignment",
    "programmereviewentry",
    "programmereviewdecision",
    "programmedecisionacknowledgement",
    "programmefilecontent",
)
GUARDED_MODELS = (
    DIRECT_MODELS + DEFINITION_CHILDREN + SUBMISSION_CHILDREN + REVIEW_CHILDREN
)
CLEANUP_MODELS = (
    "applicationdefinition",
    "applicationownerdepartment",
    "programmecall",
    "applicationsubmission",
    "programmeproposal",
    "programmecommandreceipt",
    "programmeimportbatch",
    "programmeimportitem",
    "programmeimportcommandreceipt",
)

_SCOPE_SQL = """
        CASE TG_TABLE_NAME
        WHEN {definition_tables} THEN
            SELECT d.organization_id, d.edition_id INTO owner
              FROM public.applications_applicationdefinition d
             WHERE d.id = (body->>'definition_id')::uuid;
        WHEN {submission_tables} THEN
            SELECT s.organization_id, s.edition_id INTO owner
              FROM public.applications_applicationsubmission s
             WHERE s.id = (body->>'submission_id')::uuid;
        WHEN 'applications_programmereviewpolicy' THEN
            SELECT c.organization_id, c.edition_id INTO owner
              FROM public.applications_programmecall c
             WHERE c.id = (body->>'call_id')::uuid;
        WHEN 'applications_programmereviewcase' THEN
            SELECT p.organization_id, p.edition_id INTO owner
              FROM public.applications_programmeproposal p
             WHERE p.id = (body->>'proposal_id')::uuid;
        WHEN 'applications_programmereviewassignment',
             'applications_programmereviewentry' THEN
            SELECT p.organization_id, p.edition_id INTO owner
              FROM public.applications_programmereviewcase c
              JOIN public.applications_programmeproposal p ON p.id = c.proposal_id
             WHERE c.id = (body->>'case_id')::uuid;
        WHEN 'applications_programmereviewdecision' THEN
            SELECT p.organization_id, p.edition_id INTO owner
              FROM public.applications_programmereviewentry e
              JOIN public.applications_programmereviewcase c ON c.id = e.case_id
              JOIN public.applications_programmeproposal p ON p.id = c.proposal_id
             WHERE e.id = (body->>'entry_id')::uuid;
        WHEN 'applications_programmedecisionacknowledgement' THEN
            SELECT p.organization_id, p.edition_id INTO owner
              FROM public.applications_programmereviewdecision d
              JOIN public.applications_programmereviewentry e ON e.id = d.entry_id
              JOIN public.applications_programmereviewcase c ON c.id = e.case_id
              JOIN public.applications_programmeproposal p ON p.id = c.proposal_id
             WHERE d.id = (body->>'decision_id')::uuid;
        WHEN 'applications_programmefilecontent' THEN
            SELECT i.organization_id, i.edition_id INTO owner
              FROM public.applications_programmefileintake i
             WHERE i.id = (body->>'intake_id')::uuid;
        ELSE
            SELECT (body->>'organization_id')::uuid AS organization_id,
                   (body->>'edition_id')::uuid AS edition_id INTO owner;
        END CASE;
        IF NOT FOUND OR owner.organization_id IS NULL OR owner.edition_id IS NULL THEN
            RAISE EXCEPTION 'Applications stop requires an exact owner scope'
                USING ERRCODE = '23514';
        END IF;
        scopes := scopes || jsonb_build_array(jsonb_build_object(
            'organization_id', owner.organization_id, 'edition_id', owner.edition_id));
""".format(
    definition_tables=", ".join(
        f"'applications_{name}'" for name in DEFINITION_CHILDREN
    ),
    submission_tables=", ".join(
        f"'applications_{name}'" for name in SUBMISSION_CHILDREN
    ),
)

FORWARD_SQL = (
    r"""
CREATE FUNCTION public.maru_applications_programme_stop_guard()
RETURNS trigger AS $$
DECLARE
    rows jsonb := '[]'::jsonb;
    scopes jsonb := '[]'::jsonb;
    body jsonb;
    owner record;
    scope record;
    edition record;
    stopped boolean := FALSE;
    cleanup boolean := FALSE;
BEGIN
    IF TG_OP <> 'INSERT' THEN rows := rows || jsonb_build_array(to_jsonb(OLD)); END IF;
    IF TG_OP <> 'DELETE' THEN rows := rows || jsonb_build_array(to_jsonb(NEW)); END IF;
    FOR body IN SELECT value FROM jsonb_array_elements(rows) LOOP
"""
    + _SCOPE_SQL
    + r"""
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
            RAISE EXCEPTION 'Applications stop requires exact edition'
                USING ERRCODE = '23514';
        END IF;
        IF edition.adoption_profile_code = 'programme_operations' THEN
            IF edition.adoption_profile_version <> 1
               OR current_setting('transaction_isolation') <> 'read committed' THEN
                RAISE EXCEPTION 'Programme Applications requires current exact scope'
                    USING ERRCODE = '23514';
            END IF;
            stopped := stopped OR edition.lifecycle IN ('archived', 'cancelled');
        END IF;
    END LOOP;
    IF stopped THEN
        CASE TG_TABLE_NAME
        WHEN 'applications_applicationdefinition' THEN
            IF TG_OP = 'UPDATE' THEN
                cleanup := NEW.aggregate_version = OLD.aggregate_version + 1 AND (
                    (OLD.status = 'active' AND NEW.status = 'retired'
                     AND NEW.retired_at IS NOT NULL AND NEW.retired_by_id IS NOT NULL
                     AND to_jsonb(NEW) - ARRAY[
                         'status', 'retired_at', 'retired_by_id',
                         'aggregate_version', 'updated_at'
                     ] = to_jsonb(OLD) - ARRAY[
                         'status', 'retired_at', 'retired_by_id',
                         'aggregate_version', 'updated_at'])
                    OR (OLD.status = 'draft' AND NEW.status = 'draft'
                        AND to_jsonb(NEW) - ARRAY['aggregate_version', 'updated_at']
                            = to_jsonb(OLD) - ARRAY['aggregate_version', 'updated_at'])
                );
            END IF;
        WHEN 'applications_applicationownerdepartment' THEN
            IF TG_OP = 'UPDATE' THEN
                cleanup := OLD.department_id <> NEW.department_id
                    AND to_jsonb(NEW) - ARRAY['department_id', 'updated_at']
                        = to_jsonb(OLD) - ARRAY['department_id', 'updated_at'];
            END IF;
        WHEN 'applications_programmecall' THEN
            IF TG_OP = 'UPDATE' THEN
                cleanup := OLD.owner_department_id <> NEW.owner_department_id
                    AND to_jsonb(NEW) - ARRAY['owner_department_id', 'updated_at']
                        = to_jsonb(OLD) - ARRAY['owner_department_id', 'updated_at'];
            END IF;
        WHEN 'applications_applicationsubmission' THEN
            IF TG_OP = 'UPDATE' THEN
                cleanup := OLD.state IN ('draft', 'submitted')
                    AND NEW.state = 'withdrawn'
                    AND NEW.withdrawn_at IS NOT NULL
                    AND NEW.aggregate_version = OLD.aggregate_version + 1
                    AND to_jsonb(NEW) - ARRAY[
                        'state', 'withdrawn_at', 'aggregate_version', 'updated_at'
                    ] = to_jsonb(OLD) - ARRAY[
                        'state', 'withdrawn_at', 'aggregate_version', 'updated_at'];
            END IF;
        WHEN 'applications_programmeproposal' THEN
            IF TG_OP = 'UPDATE' THEN
                cleanup := OLD.state IN ('draft', 'sealed', 'submitted')
                    AND NEW.state = 'withdrawn'
                    AND to_jsonb(NEW) - ARRAY['state', 'updated_at']
                        = to_jsonb(OLD) - ARRAY['state', 'updated_at'];
            END IF;
        WHEN 'applications_programmecommandreceipt' THEN
            IF TG_OP = 'INSERT' THEN
                cleanup := NEW.action IN ('call_retired', 'recovery_call_retired',
                    'recovery_call_reassigned', 'proposal_withdrawn');
            END IF;
        WHEN 'applications_programmeimportbatch' THEN
            IF TG_OP = 'UPDATE' THEN
                cleanup := OLD.state = 'staged' AND NEW.state = 'discarded'
                    AND NEW.aggregate_version = OLD.aggregate_version + 1
                    AND NEW.discarded_at IS NOT NULL AND NEW.discarded_by_id IS NOT NULL
                    AND btrim(NEW.discard_reason) <> ''
                    AND to_jsonb(NEW) - ARRAY[
                        'state', 'aggregate_version', 'discarded_by_id',
                        'discarded_at', 'discard_reason', 'updated_at'
                    ] = to_jsonb(OLD) - ARRAY[
                        'state', 'aggregate_version', 'discarded_by_id',
                        'discarded_at', 'discard_reason', 'updated_at'];
            END IF;
        WHEN 'applications_programmeimportitem' THEN
            IF TG_OP = 'UPDATE' THEN
                cleanup := OLD.state = 'staged' AND NEW.state = 'discarded'
                    AND OLD.aggregate_version = 1 AND NEW.aggregate_version = 2
                    AND NEW.canonical_payload IS NULL
                    AND to_jsonb(NEW) - ARRAY[
                        'state', 'aggregate_version', 'canonical_payload', 'updated_at'
                    ] = to_jsonb(OLD) - ARRAY[
                        'state', 'aggregate_version', 'canonical_payload', 'updated_at'
                    ];
            END IF;
        WHEN 'applications_programmeimportcommandreceipt' THEN
            IF TG_OP = 'INSERT' THEN cleanup := NEW.action = 'batch_discarded'; END IF;
        ELSE cleanup := FALSE;
        END CASE;
        IF cleanup IS DISTINCT FROM TRUE THEN
            RAISE EXCEPTION 'Stopped Programme refuses ordinary Applications writes'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION public.maru_applications_programme_stop_guard() FROM PUBLIC;
"""
)

FORWARD_SQL += r"""
CREATE FUNCTION public.maru_applications_programme_stop_cleanup()
RETURNS trigger AS $$
DECLARE
    receipt jsonb;
    checked_definition uuid;
    checked_submission uuid;
    checked_batch uuid;
    checked_receipt uuid;
    checked_version bigint;
    checked_organization uuid;
    checked_edition uuid;
    definition public.applications_applicationdefinition%ROWTYPE;
    batch public.applications_programmeimportbatch%ROWTYPE;
    action text;
    capability text;
    fields varchar[];
    checked_target_type text;
    checked_target_id uuid;
    audit_prefix text;
    retention text;
    values_json text := '{}';
    intent_json text;
BEGIN
    CASE TG_TABLE_NAME
    WHEN 'applications_applicationdefinition' THEN
        checked_definition := NEW.id; checked_version := NEW.aggregate_version;
    WHEN 'applications_applicationownerdepartment', 'applications_programmecall' THEN
        checked_definition := NEW.definition_id;
    WHEN 'applications_applicationsubmission' THEN
        checked_submission := NEW.id; checked_version := NEW.aggregate_version;
    WHEN 'applications_programmeproposal' THEN
        checked_submission := NEW.submission_id;
    WHEN 'applications_programmecommandreceipt' THEN
        checked_receipt := NEW.id; checked_definition := NEW.definition_id;
        checked_submission := NEW.submission_id;
        checked_version := NEW.resulting_version;
    WHEN 'applications_programmeimportbatch' THEN
        checked_batch := NEW.id; checked_version := NEW.aggregate_version;
    WHEN 'applications_programmeimportitem' THEN checked_batch := NEW.batch_id;
    WHEN 'applications_programmeimportcommandreceipt' THEN
        checked_batch := NEW.batch_id; checked_receipt := NEW.id;
        checked_version := NEW.resulting_version;
    ELSE
        RAISE EXCEPTION 'Unknown Applications cleanup relation' USING ERRCODE = '23514';
    END CASE;
    IF checked_batch IS NOT NULL THEN
        SELECT b.* INTO batch FROM public.applications_programmeimportbatch b
         WHERE b.id = checked_batch;
        checked_organization := batch.organization_id;
        checked_edition := batch.edition_id;
        checked_version := COALESCE(checked_version, batch.aggregate_version);
    ELSIF checked_submission IS NOT NULL THEN
        SELECT s.organization_id, s.edition_id, s.definition_id,
               COALESCE(checked_version, s.aggregate_version)
          INTO checked_organization, checked_edition,
               checked_definition, checked_version
          FROM public.applications_applicationsubmission s
         WHERE s.id = checked_submission;
    ELSE
        SELECT d.* INTO definition FROM public.applications_applicationdefinition d
         WHERE d.id = checked_definition;
        checked_organization := definition.organization_id;
        checked_edition := definition.edition_id;
        checked_version := COALESCE(checked_version, definition.aggregate_version);
    END IF;
    PERFORM 1 FROM public.events_eventedition e
     WHERE e.id = checked_edition AND e.organization_id = checked_organization
       AND e.adoption_profile_code = 'programme_operations'
       AND e.adoption_profile_version = 1
       AND e.lifecycle IN ('archived', 'cancelled') FOR UPDATE;
    IF NOT FOUND THEN RETURN NULL; END IF;

    IF checked_batch IS NOT NULL THEN
        SELECT to_jsonb(c) INTO receipt
          FROM public.applications_programmeimportcommandreceipt c
         WHERE c.batch_id = checked_batch AND c.item_id IS NULL
           AND c.organization_id = checked_organization
           AND c.edition_id = checked_edition
           AND c.resulting_version = checked_version AND c.action = 'batch_discarded'
           AND (checked_receipt IS NULL OR c.id = checked_receipt);
        IF NOT FOUND OR batch.state <> 'discarded'
           OR batch.discarded_by_id IS DISTINCT FROM (receipt->>'actor_id')::uuid
           OR batch.discard_reason IS DISTINCT FROM receipt->>'reason' THEN
            RAISE EXCEPTION 'Stopped import cleanup requires exact batch receipt'
                USING ERRCODE = '23514';
        END IF;
        capability := 'applications.dispose_programme_import';
        fields := ARRAY['batch_state', 'item_states', 'private_payload'];
        checked_target_type := 'applications.programme_import_batch';
        checked_target_id := checked_batch;
        audit_prefix := 'applications.programme_import.command.';
        retention := 'applications-programme-import-restricted';
        values_json := '{"batch_id":' || to_json(checked_batch)::text || '}';
    ELSE
        SELECT to_jsonb(c) INTO receipt
          FROM public.applications_programmecommandreceipt c
         WHERE c.definition_id = checked_definition
           AND c.submission_id IS NOT DISTINCT FROM checked_submission
           AND c.organization_id = checked_organization
           AND c.edition_id = checked_edition
           AND c.resulting_version = checked_version
           AND c.action IN ('call_retired', 'recovery_call_retired',
                            'recovery_call_reassigned', 'proposal_withdrawn')
           AND (checked_receipt IS NULL OR c.id = checked_receipt);
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Stopped Applications cleanup requires exact owner receipt'
                USING ERRCODE = '23514';
        END IF;
        action := receipt->>'action';
        audit_prefix := 'applications.programme.command.';
        retention := 'applications-programme-restricted';
        checked_target_id := (receipt->>'target_id')::uuid;
        IF checked_submission IS NOT NULL THEN
            IF action <> 'proposal_withdrawn' OR NOT EXISTS (
                SELECT 1 FROM public.applications_programmeproposal p
                JOIN public.applications_applicationsubmission s
                  ON s.id = p.submission_id
                WHERE p.id = checked_target_id AND s.id = checked_submission
                  AND p.state = 'withdrawn' AND s.state = 'withdrawn'
                  AND s.withdrawn_at IS NOT NULL
                  AND s.account_id = (receipt->>'actor_id')::uuid
            ) THEN
                RAISE EXCEPTION 'Stopped proposal cleanup requires lead withdrawal'
                    USING ERRCODE = '23514';
            END IF;
            capability := 'applications.submit_programme_proposal_self';
            fields := ARRAY['state', 'withdrawn_at'];
            checked_target_type := 'applications.programme_proposal';
        ELSE
            checked_target_type := 'applications.programme_call';
            IF action = 'call_retired' THEN
                capability := 'applications.manage_programme_calls';
                fields := ARRAY['status', 'retired_at', 'retired_by'];
            ELSIF action = 'recovery_call_retired' THEN
                capability := 'applications.recover_programme_department_ownership';
                fields := ARRAY[
                    'status', 'retired_at', 'retired_by', 'aggregate_version'];
                values_json := '{"source_department_id":' ||
                    to_json((receipt->>'source_department_id')::uuid)::text || '}';
            ELSIF action = 'recovery_call_reassigned' THEN
                capability := 'applications.recover_programme_department_ownership';
                fields := ARRAY['owner_department', 'aggregate_version'];
                values_json := '{"destination_department_id":' ||
                    to_json((receipt->>'destination_department_id')::uuid)::text ||
                    ',"source_department_id":' ||
                    to_json((receipt->>'source_department_id')::uuid)::text || '}';
            ELSE
                RAISE EXCEPTION 'Stopped call cleanup is unsupported'
                    USING ERRCODE = '23514';
            END IF;
            IF TG_TABLE_NAME = 'applications_applicationdefinition' THEN
                IF (action = 'recovery_call_reassigned' AND NEW.status <> 'draft')
                   OR (action <> 'recovery_call_reassigned' AND (
                       NEW.status <> 'retired' OR NEW.retired_by_id IS DISTINCT FROM
                           (receipt->>'actor_id')::uuid)) THEN
                    RAISE EXCEPTION 'Stopped call cleanup differs from exact mutation'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF TG_TABLE_NAME = 'applications_applicationownerdepartment' THEN
                IF action <> 'recovery_call_reassigned'
                   OR OLD.department_id IS DISTINCT FROM
                       (receipt->>'source_department_id')::uuid
                   OR NEW.department_id IS DISTINCT FROM
                       (receipt->>'destination_department_id')::uuid THEN
                    RAISE EXCEPTION 'Stopped call owner change lacks exact recovery'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF TG_TABLE_NAME = 'applications_programmecall' THEN
                IF action <> 'recovery_call_reassigned' OR NEW.id <> checked_target_id
                   OR OLD.owner_department_id IS DISTINCT FROM
                       (receipt->>'source_department_id')::uuid
                   OR NEW.owner_department_id IS DISTINCT FROM
                       (receipt->>'destination_department_id')::uuid THEN
                    RAISE EXCEPTION 'Stopped call change lacks exact recovery'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
        END IF;
    END IF;
    action := receipt->>'action';
    intent_json := '{"action":' || to_json(action)::text ||
        ',"actor_id":' || to_json(receipt->>'actor_id')::text ||
        ',"edition_id":' || to_json(receipt->>'edition_id')::text ||
        ',"expected_version":' || (receipt->>'expected_version') ||
        ',"organization_id":' || to_json(receipt->>'organization_id')::text ||
        ',"reason":' || to_json(receipt->>'reason')::text ||
        ',"source_channel":' || to_json(receipt->>'source_channel')::text ||
        CASE WHEN checked_batch IS NULL THEN
            ',"target_id":' || to_json(checked_target_id)::text ELSE '' END ||
        ',"values":' || values_json || '}';
    IF receipt->>'request_digest' IS DISTINCT FROM
       encode(sha256(convert_to(intent_json, 'UTF8')), 'hex') OR NOT EXISTS (
        SELECT 1 FROM public.audit_auditevent a
          JOIN public.audit_auditnativemutationwitness w ON w.audit_event_id = a.id
         WHERE a.organization_id = checked_organization
           AND a.event_edition_id = checked_edition
           AND a.principal_kind = 'account' AND a.principal_context_id IS NULL
           AND a.principal_id = (receipt->>'actor_id')::uuid AND a.outcome = 'allow'
           AND a.operation = audit_prefix || action AND a.capability_code = capability
           AND a.target_type = checked_target_type AND a.target_id = checked_target_id
           AND a.correlation_id = (receipt->>'correlation_id')::uuid
           AND a.source_channel = receipt->>'source_channel'
           AND a.retention_class = retention AND a.changed_fields = fields
           AND a.break_glass = (
               action IN ('recovery_call_retired', 'recovery_call_reassigned'))
           AND a.idempotency_key_hash = encode(
               sha256(convert_to(receipt->>'retry_key', 'UTF8')), 'hex')
           AND w.transaction_stamp =
               public.maru_audit_current_native_transaction_stamp()
    ) THEN
        RAISE EXCEPTION 'Stopped cleanup requires exact native intent and audit'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION public.maru_applications_programme_stop_cleanup() FROM PUBLIC;
"""

FORWARD_SQL += "\n".join(
    f"CREATE TRIGGER a00_applications_programme_stop_{index} "
    f"BEFORE INSERT OR UPDATE OR DELETE ON public.applications_{model} "
    "FOR EACH ROW EXECUTE FUNCTION public.maru_applications_programme_stop_guard();"
    for index, model in enumerate(GUARDED_MODELS)
)
FORWARD_SQL += "\n" + "\n".join(
    f"CREATE CONSTRAINT TRIGGER applications_programme_stop_cleanup_{index} "
    f"AFTER INSERT OR UPDATE ON public.applications_{model} "
    "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
    "EXECUTE FUNCTION public.maru_applications_programme_stop_cleanup();"
    for index, model in enumerate(CLEANUP_MODELS)
)

REVERSE_SQL = (
    "\n".join(
        f"DROP TRIGGER applications_programme_stop_cleanup_{index} "
        f"ON public.applications_{model};"
        for index, model in reversed(tuple(enumerate(CLEANUP_MODELS)))
    )
    + "\n"
    + "\n".join(
        f"DROP TRIGGER a00_applications_programme_stop_{index} "
        f"ON public.applications_{model};"
        for index, model in reversed(tuple(enumerate(GUARDED_MODELS)))
    )
    + (
        "\nDROP FUNCTION public.maru_applications_programme_stop_cleanup();"
        "\nDROP FUNCTION public.maru_applications_programme_stop_guard();"
    )
)


def refuse_used_stop_boundary_downgrade(apps: Any, schema_editor: Any) -> None:
    """Refuse to remove Applications stop guards after terminal evidence exists."""
    schema_editor.execute(
        "LOCK TABLE public.events_programmestopreceipt IN ACCESS EXCLUSIVE MODE"
    )
    if apps.get_model("events", "ProgrammeStopReceipt").objects.exists():
        raise RuntimeError(
            "Programme stop evidence exists; retain guards and fix forward."
        )


class Migration(migrations.Migration):
    """Fence adopted roots and derived scope before enabling terminal admission."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("applications", "0022_answer_revision_optional_value"),
        ("events", "0015_programme_stop_receipt"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_used_stop_boundary_downgrade
        ),
    ]
