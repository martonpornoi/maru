"""Protect source generations independently of release application commands."""

from typing import Any, ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_scheduling_lock_release_source(
    dependency_kind text, source uuid, organization uuid, edition uuid
) RETURNS boolean AS $$
DECLARE
    owner_table text;
    owner_organization uuid;
    owner_edition uuid;
    owner_id uuid;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'release source tracking requires READ COMMITTED'
            USING ERRCODE = '23514';
    END IF;
    owner_table := CASE dependency_kind
        WHEN 'identity_account' THEN 'identity_account'
        WHEN 'edition_operational' THEN 'events_eventedition'
        WHEN 'programme_item' THEN 'programme_programmeitem'
        WHEN 'programme_host_operational' THEN 'programme_programmehostrelationship'
        WHEN 'programme_host_disclosure' THEN 'programme_programmehostrelationship'
        WHEN 'programme_public_copy' THEN 'programme_programmepublicrendition'
        WHEN 'workforce_demand' THEN 'workforce_shiftdemand'
        WHEN 'workforce_assignment' THEN 'workforce_positionassignment'
        WHEN 'workforce_availability' THEN 'workforce_personavailabilityplan'
        WHEN 'venue_property' THEN 'venues_venueproperty'
        WHEN 'venue_member' THEN 'venues_venuespace'
        WHEN 'venue_selection' THEN 'venues_editionspaceselection'
        WHEN 'venue_booking' THEN 'venues_venuebooking'
    END;
    IF owner_table IS NULL THEN RETURN FALSE; END IF;
    IF dependency_kind = 'identity_account' THEN
        SELECT id INTO owner_id FROM public.identity_account
            WHERE id = source FOR UPDATE;
        RETURN owner_id IS NOT NULL AND organization IS NULL AND edition IS NULL;
    ELSIF dependency_kind = 'edition_operational' THEN
        SELECT id, organization_id INTO owner_id, owner_organization
          FROM public.events_eventedition WHERE id = source FOR UPDATE;
        RETURN owner_id IS NOT NULL
            AND organization IS NOT DISTINCT FROM owner_organization
            AND edition IS NOT DISTINCT FROM owner_id;
    ELSIF dependency_kind IN ('venue_property', 'venue_member') THEN
        EXECUTE format(
            'SELECT id, organization_id FROM public.%I WHERE id = $1 FOR UPDATE',
            owner_table
        )
            INTO owner_id, owner_organization USING source;
        RETURN owner_id IS NOT NULL
            AND organization IS NOT DISTINCT FROM owner_organization
            AND edition IS NULL;
    END IF;
    EXECUTE format(
        'SELECT id, organization_id, edition_id FROM public.%I '
        'WHERE id = $1 FOR UPDATE', owner_table
    )
        INTO owner_id, owner_organization, owner_edition USING source;
    RETURN owner_id IS NOT NULL AND organization IS NOT DISTINCT FROM owner_organization
        AND edition IS NOT DISTINCT FROM owner_edition;
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_scheduling_release_native_change_valid(
    dependency_kind text, source uuid, organization uuid, edition uuid, audit_id uuid
) RETURNS boolean AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.audit_auditnativemutationwitness witness
        JOIN public.audit_auditevent event ON event.id = witness.audit_event_id
        WHERE event.id = audit_id AND event.outcome = 'allow'
          AND witness.transaction_stamp =
              public.maru_audit_current_native_transaction_stamp()
          AND event.organization_id IS NOT DISTINCT FROM organization
          AND event.event_edition_id IS NOT DISTINCT FROM edition
    ) THEN RETURN FALSE; END IF;
    -- Each subsequent owner migration installs its closed native proof. No
    -- unsupported owner is made writable merely by accepting its source UUID.
    IF dependency_kind = 'identity_account' THEN
        RETURN public.maru_identity_release_deactivation_valid(source, audit_id);
    ELSIF dependency_kind IN ('programme_item', 'programme_host_operational',
                             'programme_host_disclosure', 'programme_public_copy') THEN
        RETURN public.maru_programme_release_change_valid(
            dependency_kind, source, organization, edition, audit_id
        );
    ELSIF dependency_kind IN
        ('workforce_demand', 'workforce_assignment', 'workforce_availability') THEN
        RETURN public.maru_workforce_release_change_valid(
            dependency_kind, source, organization, edition, audit_id
        );
    ELSIF dependency_kind IN (
        'venue_property', 'venue_member', 'venue_selection', 'venue_booking'
    ) THEN
        RETURN public.maru_venues_release_change_valid(
            dependency_kind, source, organization, edition, audit_id
        );
    ELSIF dependency_kind = 'edition_operational' THEN
        RETURN public.maru_events_release_change_valid(
            source, organization, edition, audit_id
        );
    END IF;
    RETURN FALSE;
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_scheduling_release_key_guard()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'release dependency identities are retained'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.generation <> 1 OR public.maru_scheduling_lock_release_source(
            NEW.kind, NEW.source_id, NEW.organization_id, NEW.edition_id
        ) IS DISTINCT FROM TRUE THEN
            RAISE EXCEPTION 'release dependency requires its locked native source'
                USING ERRCODE = '23514';
        END IF;
        NEW.created_at := clock_timestamp();
    ELSE
        IF (NEW.id, NEW.kind, NEW.source_id, NEW.organization_id,
            NEW.edition_id, NEW.created_at)
             IS DISTINCT FROM
           (OLD.id, OLD.kind, OLD.source_id, OLD.organization_id,
            OLD.edition_id, OLD.created_at)
           OR NEW.generation <> OLD.generation + 1 THEN
            RAISE EXCEPTION
                'release dependency requires one immutable-identity advance'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    NEW.updated_at := clock_timestamp();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_scheduling_release_source_identity_guard()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND
       (to_jsonb(NEW)->'id', to_jsonb(NEW)->'organization_id',
        to_jsonb(NEW)->'edition_id', to_jsonb(NEW)->'series_id',
        to_jsonb(NEW)->'account_id', to_jsonb(NEW)->'item_id',
        to_jsonb(NEW)->'position_id')
          IS NOT DISTINCT FROM
       (to_jsonb(OLD)->'id', to_jsonb(OLD)->'organization_id',
        to_jsonb(OLD)->'edition_id', to_jsonb(OLD)->'series_id',
        to_jsonb(OLD)->'account_id', to_jsonb(OLD)->'item_id',
        to_jsonb(OLD)->'position_id') THEN
        RETURN NEW;
    END IF;
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'release source identity changes require READ COMMITTED'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.scheduling_schedulingreleasedependencykey
        WHERE kind = ANY(TG_ARGV) AND source_id = OLD.id
    ) THEN
        RAISE EXCEPTION
            'tracked release source identity and ownership must be retained'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_scheduling_release_change_guard()
RETURNS trigger AS $$
DECLARE dependency public.scheduling_schedulingreleasedependencykey%ROWTYPE;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'release dependency changes are append-only'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO dependency FROM public.scheduling_schedulingreleasedependencykey
        WHERE id = NEW.dependency_id FOR UPDATE;
    IF dependency.id IS NULL OR NEW.generation <> dependency.generation
       OR NEW.organization_id IS DISTINCT FROM dependency.organization_id
       OR NEW.edition_id IS DISTINCT FROM dependency.edition_id
       OR public.maru_scheduling_release_native_change_valid(
            dependency.kind, dependency.source_id, dependency.organization_id,
            dependency.edition_id, NEW.source_audit_id
       ) IS DISTINCT FROM TRUE THEN
        RAISE EXCEPTION
            'release change requires exact current native mutation evidence'
            USING ERRCODE = '23514';
    END IF;
    NEW.recorded_at := clock_timestamp();
    NEW.created_at := NEW.recorded_at;
    NEW.updated_at := NEW.recorded_at;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_scheduling_release_key_complete()
RETURNS trigger AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.scheduling_schedulingreleasedependencychange change
        WHERE change.dependency_id = NEW.id AND change.generation = NEW.generation
    ) THEN
        RAISE EXCEPTION 'release generation requires its complete immutable journal'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE TRIGGER scheduling_release_key_shape
BEFORE INSERT OR UPDATE OR DELETE ON public.scheduling_schedulingreleasedependencykey
FOR EACH ROW EXECUTE FUNCTION public.maru_scheduling_release_key_guard();
CREATE CONSTRAINT TRIGGER scheduling_release_key_evidence
AFTER UPDATE ON public.scheduling_schedulingreleasedependencykey
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_scheduling_release_key_complete();
CREATE TRIGGER scheduling_release_change_shape
BEFORE INSERT OR UPDATE OR DELETE ON public.scheduling_schedulingreleasedependencychange
FOR EACH ROW EXECUTE FUNCTION public.maru_scheduling_release_change_guard();
CREATE TRIGGER scheduling_release_key_no_truncate
BEFORE TRUNCATE ON public.scheduling_schedulingreleasedependencykey
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_prevent_audit_event_truncate();
CREATE TRIGGER scheduling_release_change_no_truncate
BEFORE TRUNCATE ON public.scheduling_schedulingreleasedependencychange
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_prevent_audit_event_truncate();
"""

REVERSE_SQL = r"""
DROP TRIGGER scheduling_release_change_no_truncate
    ON public.scheduling_schedulingreleasedependencychange;
DROP TRIGGER scheduling_release_key_no_truncate
    ON public.scheduling_schedulingreleasedependencykey;
DROP TRIGGER scheduling_release_change_shape
    ON public.scheduling_schedulingreleasedependencychange;
DROP TRIGGER scheduling_release_key_evidence
    ON public.scheduling_schedulingreleasedependencykey;
DROP TRIGGER scheduling_release_key_shape
    ON public.scheduling_schedulingreleasedependencykey;
DROP FUNCTION public.maru_scheduling_release_key_complete();
DROP FUNCTION public.maru_scheduling_release_change_guard();
DROP FUNCTION public.maru_scheduling_release_key_guard();
DROP FUNCTION public.maru_scheduling_release_source_identity_guard();
DROP FUNCTION public.maru_scheduling_release_native_change_valid(
    text, uuid, uuid, uuid, uuid
);
DROP FUNCTION public.maru_scheduling_lock_release_source(text, uuid, uuid, uuid);
"""


def refuse_used_dependency_downgrade(apps: Any, schema_editor: Any) -> None:
    """Keep populated source generations and their enforcement together."""
    key = apps.get_model("scheduling", "SchedulingReleaseDependencyKey")
    change = apps.get_model("scheduling", "SchedulingReleaseDependencyChange")
    schema_editor.execute(
        "LOCK TABLE public.scheduling_schedulingreleasedependencykey, "
        "public.scheduling_schedulingreleasedependencychange IN ACCESS EXCLUSIVE MODE"
    )
    if key.objects.exists() or change.objects.exists():
        raise RuntimeError(
            "Release dependency history exists; retain guards and fix forward."
        )


class Migration(migrations.Migration):
    """Install journal integrity before owner-specific transaction joins."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("scheduling", "0007_release_dependency_journal"),
        ("audit", "0009_native_mutation_witness"),
        ("identity", "0020_programme_proposal_person_guard"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_used_dependency_downgrade
        ),
    ]
