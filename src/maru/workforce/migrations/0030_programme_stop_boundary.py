"""Preserve retained work while refusing new writes in stopped Programme scope."""

# ruff: noqa: S608 -- generated identifiers are frozen owner-owned model names.

from typing import Any, ClassVar

from django.db import migrations

DIRECT_MODELS = (
    "programmestarterrequest",
    "department",
    "editionstructurecontrol",
    "editionstructurecommandreceipt",
    "onboardingdocumenttype",
    "position",
    "onboardingdocumentrequest",
    "positionassignment",
    "positionassignmentcommandreceipt",
    "personavailabilityplan",
    "personavailabilitycommandreceipt",
    "shiftdemand",
    "shiftdemandcommandreceipt",
    "shiftcommitment",
    "shiftcommitmentcommandreceipt",
    "programmeshiftbinding",
    "programmeshiftbindingrevision",
)
DERIVED_MODELS = (
    "programmestarterdecision",
    "positiondocumentrequirement",
    "volunteeropportunity",
    "volunteerapplication",
    "personavailabilitywindow",
)
GUARDED_MODELS = (*DIRECT_MODELS, *DERIVED_MODELS)

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_workforce_programme_stop_guard()
RETURNS trigger AS $$
DECLARE
    rows jsonb := '[]'::jsonb;
    scopes jsonb := '[]'::jsonb;
    body jsonb;
    parent_id uuid;
    organization_id uuid;
    scope record;
    edition record;
BEGIN
    IF TG_OP <> 'INSERT' THEN rows := rows || jsonb_build_array(to_jsonb(OLD)); END IF;
    IF TG_OP <> 'DELETE' THEN rows := rows || jsonb_build_array(to_jsonb(NEW)); END IF;
    FOR body IN SELECT value FROM jsonb_array_elements(rows) LOOP
        parent_id := NULL;
        organization_id := NULL;
        CASE TG_TABLE_NAME
        WHEN 'workforce_programmestarterdecision' THEN
            SELECT r.edition_id, r.organization_id INTO parent_id, organization_id
              FROM public.workforce_programmestarterrequest r
             WHERE r.id = (body->>'request_id')::uuid;
        WHEN 'workforce_positiondocumentrequirement',
             'workforce_volunteeropportunity' THEN
            SELECT p.edition_id, p.organization_id INTO parent_id, organization_id
              FROM public.workforce_position p
             WHERE p.id = (body->>'position_id')::uuid;
        WHEN 'workforce_volunteerapplication' THEN
            SELECT p.edition_id, p.organization_id INTO parent_id, organization_id
              FROM public.workforce_volunteeropportunity o
              JOIN public.workforce_position p ON p.id = o.position_id
             WHERE o.id = (body->>'opportunity_id')::uuid;
        WHEN 'workforce_personavailabilitywindow' THEN
            SELECT p.edition_id, p.organization_id INTO parent_id, organization_id
              FROM public.workforce_personavailabilityplan p
             WHERE p.id = (body->>'plan_id')::uuid;
        ELSE
            parent_id := (body->>'edition_id')::uuid;
            organization_id := (body->>'organization_id')::uuid;
        END CASE;
        IF parent_id IS NULL OR organization_id IS NULL THEN
            RAISE EXCEPTION 'Workforce stop boundary requires an exact parent scope'
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
            RAISE EXCEPTION 'Workforce stop boundary requires an exact edition scope'
                USING ERRCODE = '23514';
        END IF;
        IF edition.adoption_profile_code = 'programme_operations' THEN
            IF edition.adoption_profile_version <> 1
               OR current_setting('transaction_isolation') <> 'read committed' THEN
                RAISE EXCEPTION 'Workforce Programme requires current exact scope'
                    USING ERRCODE = '23514';
            END IF;
            IF edition.lifecycle IN ('archived', 'cancelled') THEN
                RAISE EXCEPTION 'Stopped Programme refuses ordinary Workforce writes'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
    END LOOP;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION public.maru_workforce_programme_stop_guard() FROM PUBLIC;
""" + "\n".join(
    f"CREATE TRIGGER a00_workforce_programme_stop_{index} "
    f"BEFORE INSERT OR UPDATE OR DELETE ON public.workforce_{model} "
    "FOR EACH ROW EXECUTE FUNCTION public.maru_workforce_programme_stop_guard();"
    for index, model in enumerate(GUARDED_MODELS)
)

REVERSE_SQL = (
    "\n".join(
        f"DROP TRIGGER a00_workforce_programme_stop_{index} "
        f"ON public.workforce_{model};"
        for index, model in reversed(tuple(enumerate(GUARDED_MODELS)))
    )
    + "\nDROP FUNCTION public.maru_workforce_programme_stop_guard();"
)


def refuse_used_stop_boundary_downgrade(apps: Any, schema_editor: Any) -> None:
    """Retain native terminal admission once stop evidence is in use."""
    schema_editor.execute(
        "LOCK TABLE public.events_programmestopreceipt IN ACCESS EXCLUSIVE MODE"
    )
    if apps.get_model("events", "ProgrammeStopReceipt").objects.exists():
        raise RuntimeError(
            "Programme stop evidence exists; retain guards and fix forward."
        )


class Migration(migrations.Migration):
    """Freeze exact adopted work, leaving shared templates and other editions alone."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("workforce", "0029_programme_assignment_adoption"),
        ("events", "0015_programme_stop_receipt"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_used_stop_boundary_downgrade
        ),
    ]
