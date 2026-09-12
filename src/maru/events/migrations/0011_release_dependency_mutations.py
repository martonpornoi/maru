"""Keep edition operational changes atomic with tracked release invalidation."""

from typing import Any, ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_events_release_change_valid(
    source uuid, organization_scope uuid, edition_scope uuid, audit_id uuid
) RETURNS boolean AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.audit_auditevent event
        JOIN public.events_eventedition edition ON edition.id = event.target_id
        WHERE event.id = audit_id AND event.outcome = 'allow'
          AND event.principal_kind = 'account' AND event.principal_context_id IS NULL
          AND event.target_type = 'events.event_edition'
          AND event.target_id = source AND edition.id = edition_scope
          AND edition.organization_id = organization_scope
          AND event.organization_id = organization_scope
          AND event.event_edition_id = edition_scope
          AND (
            (event.operation = 'events.edition.update'
             AND event.capability_code = 'events.change_profile'
             AND event.changed_fields && ARRAY[
                 'starts_on', 'ends_on', 'time_zone']::varchar[])
            OR
            (event.operation = 'events.edition.transition'
             AND event.capability_code = 'events.transition'
             AND edition.lifecycle IN ('cancelled', 'closing', 'archived')
             AND event.changed_fields @> ARRAY[
                 'lifecycle', 'lifecycle_version', 'aggregate_version']::varchar[]
             AND EXISTS (
                 SELECT 1 FROM public.events_editionlifecycletransition history
                 WHERE history.edition_id = edition.id
                   AND history.to_state = edition.lifecycle
                   AND history.actor_id = event.principal_id
             ))
          )
    );
$$ LANGUAGE sql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_events_release_source_guard()
RETURNS trigger AS $$
DECLARE
    required_fields varchar[];
    tracked_dependency_id uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF EXISTS (SELECT 1 FROM public.scheduling_schedulingreleasedependencykey
                   WHERE kind = 'edition_operational' AND source_id = OLD.id) THEN
            RAISE EXCEPTION 'release-tracked editions must be retained'
                USING ERRCODE = '23514';
        END IF;
        RETURN OLD;
    END IF;
    required_fields := array_remove(ARRAY[
        CASE WHEN NEW.starts_on IS DISTINCT FROM OLD.starts_on THEN 'starts_on' END,
        CASE WHEN NEW.ends_on IS DISTINCT FROM OLD.ends_on THEN 'ends_on' END,
        CASE WHEN NEW.time_zone IS DISTINCT FROM OLD.time_zone THEN 'time_zone' END,
        CASE WHEN NEW.lifecycle IS DISTINCT FROM OLD.lifecycle
                   AND NEW.lifecycle IN ('cancelled', 'closing', 'archived')
             THEN 'lifecycle' END
    ]::varchar[], NULL);
    IF cardinality(required_fields) = 0 THEN RETURN NEW; END IF;
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'edition release source writes require READ COMMITTED'
            USING ERRCODE = '23514';
    END IF;
    IF TG_WHEN = 'BEFORE' THEN RETURN NEW; END IF;
    SELECT id INTO tracked_dependency_id
    FROM public.scheduling_schedulingreleasedependencykey
        WHERE kind = 'edition_operational' AND source_id = NEW.id;
    IF tracked_dependency_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.scheduling_schedulingreleasedependencychange change
        JOIN public.audit_auditnativemutationwitness witness
          ON witness.audit_event_id = change.source_audit_id
        JOIN public.audit_auditevent event ON event.id = witness.audit_event_id
        WHERE change.dependency_id = tracked_dependency_id
          AND witness.transaction_stamp =
              public.maru_audit_current_native_transaction_stamp()
          AND event.changed_fields @> required_fields
          AND public.maru_events_release_change_valid(
              NEW.id, NEW.organization_id, NEW.id, event.id)
    ) THEN
        RAISE EXCEPTION 'edition source change requires its native release invalidation'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

CREATE TRIGGER events_release_source_shape
BEFORE UPDATE OR DELETE ON public.events_eventedition
FOR EACH ROW EXECUTE FUNCTION public.maru_events_release_source_guard();
CREATE TRIGGER events_release_source_identity
BEFORE UPDATE OR DELETE ON public.events_eventedition
FOR EACH ROW EXECUTE FUNCTION
public.maru_scheduling_release_source_identity_guard('edition_operational');
CREATE CONSTRAINT TRIGGER events_release_source_evidence
AFTER UPDATE ON public.events_eventedition
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_events_release_source_guard();
"""

REVERSE_SQL = r"""
DROP TRIGGER events_release_source_identity ON public.events_eventedition;
DROP TRIGGER events_release_source_evidence ON public.events_eventedition;
DROP TRIGGER events_release_source_shape ON public.events_eventedition;
DROP FUNCTION public.maru_events_release_source_guard();
DROP FUNCTION public.maru_events_release_change_valid(uuid, uuid, uuid, uuid);
"""


def refuse_tracked_edition_downgrade(apps: Any, schema_editor: Any) -> None:
    """Retain native edition consequences once used by release source tracking."""
    key = apps.get_model("scheduling", "SchedulingReleaseDependencyKey")
    schema_editor.execute(
        "LOCK TABLE public.scheduling_schedulingreleasedependencykey "
        "IN ACCESS EXCLUSIVE MODE"
    )
    if key.objects.filter(kind="edition_operational").exists():
        raise RuntimeError(
            "Release-tracked editions exist; retain guards and fix forward."
        )


class Migration(migrations.Migration):
    """Preserve ordinary Ready/Live progression while governing unsafe ending."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("events", "0010_workforce_adoption_profile"),
        ("scheduling", "0008_release_dependency_guards"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_tracked_edition_downgrade
        ),
    ]
