"""Fence ordinary Scheduling writes at the exact terminal Programme parent."""

# ruff: noqa: S608 -- SQL identifiers come only from the frozen owner inventory.

from typing import Any, ClassVar

from django.db import migrations

# Frozen owner inventory. Dependency key/change retain their independent native
# source guards: global security changes must still invalidate retained releases.
GUARDED_MODELS = (
    "schedulingeditioncontrol",
    "schedulingserviceday",
    "schedulingservicedayrevision",
    "schedulingoccurrence",
    "schedulingoccurrencerevision",
    "schedulingcandidate",
    "schedulingcandidaterevision",
    "schedulingplacementrevision",
    "schedulingcandidatemember",
    "schedulingplacementhostpresence",
    "schedulingevaluation",
    "schedulingconflict",
    "schedulingwarningacknowledgement",
    "schedulingreservationintent",
    "schedulingcommandreceipt",
    "schedulingchangenotice",
    "schedulingchangenoticeevidence",
    "schedulingreleasewarningacknowledgement",
    "schedulingreleaseapproval",
    "schedulingreleaseapprovalplacement",
    "schedulingreleaseapprovaldependency",
    "schedulingrelease",
    "schedulingreleaseartifact",
    "schedulingreleasewithdrawal",
    "schedulingreleasepointer",
)

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_scheduling_programme_stop_guard()
RETURNS trigger AS $$
DECLARE
    scopes jsonb := '[]'::jsonb;
    scope record;
    edition record;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        scopes := scopes || jsonb_build_array(to_jsonb(OLD));
    END IF;
    IF TG_OP <> 'DELETE' THEN
        scopes := scopes || jsonb_build_array(to_jsonb(NEW));
    END IF;
    FOR scope IN
        SELECT DISTINCT (value->>'edition_id')::uuid AS edition_id,
                        (value->>'organization_id')::uuid AS organization_id
        FROM jsonb_array_elements(scopes)
        ORDER BY edition_id, organization_id
    LOOP
        -- Both source and destination parents participate, even for raw moves.
        SELECT e.adoption_profile_code, e.adoption_profile_version, e.lifecycle
          INTO edition FROM public.events_eventedition e
         WHERE e.id = scope.edition_id AND e.organization_id = scope.organization_id
         FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Scheduling stop boundary requires an exact edition scope'
                USING ERRCODE = '23514';
        END IF;
        IF edition.adoption_profile_code = 'programme_operations' THEN
            IF edition.adoption_profile_version <> 1
               OR current_setting('transaction_isolation') <> 'read committed' THEN
                RAISE EXCEPTION 'Scheduling Programme requires current exact scope'
                    USING ERRCODE = '23514';
            END IF;
            IF edition.lifecycle IN ('archived', 'cancelled') THEN
                RAISE EXCEPTION 'Stopped Programme refuses ordinary Scheduling writes'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
    END LOOP;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION public.maru_scheduling_programme_stop_guard() FROM PUBLIC;
""" + "\n".join(
    f"CREATE TRIGGER a00_sch_programme_stop_{index} "
    f"BEFORE INSERT OR UPDATE OR DELETE ON public.scheduling_{model} "
    "FOR EACH ROW EXECUTE FUNCTION public.maru_scheduling_programme_stop_guard();"
    for index, model in enumerate(GUARDED_MODELS)
)

REVERSE_SQL = (
    "\n".join(
        f"DROP TRIGGER a00_sch_programme_stop_{index} ON public.scheduling_{model};"
        for index, model in reversed(tuple(enumerate(GUARDED_MODELS)))
    )
    + "\nDROP FUNCTION public.maru_scheduling_programme_stop_guard();"
)


def refuse_used_stop_boundary_downgrade(apps: Any, schema_editor: Any) -> None:
    """Keep the terminal writer fence once any accountable stop is retained."""
    schema_editor.execute(
        "LOCK TABLE public.events_programmestopreceipt IN ACCESS EXCLUSIVE MODE"
    )
    if apps.get_model("events", "ProgrammeStopReceipt").objects.exists():
        raise RuntimeError(
            "Programme stop evidence exists; retain guards and fix forward."
        )


class Migration(migrations.Migration):
    """Install native parent locks without enabling an Events terminal command."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("scheduling", "0022_change_notice_integrity"),
        ("events", "0015_programme_stop_receipt"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_used_stop_boundary_downgrade
        ),
    ]
