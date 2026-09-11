"""Require same-transaction release invalidation for tracked person eligibility."""

from typing import Any, ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_identity_release_deactivation_valid(
    source uuid, audit_id uuid)
RETURNS boolean AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.audit_auditevent event
        JOIN public.identity_account subject ON subject.id = event.target_id
        JOIN public.identity_account actor ON actor.id = event.principal_id
        WHERE event.id = audit_id AND event.target_id = source
          AND event.principal_kind = 'account' AND event.principal_context_id IS NULL
          AND event.organization_id IS NULL AND event.event_edition_id IS NULL
          AND event.operation = 'identity.account.emergency_deactivate'
          AND event.target_type = 'identity.account' AND event.outcome = 'allow'
          AND event.capability_code = 'organizations.manage_representation'
          AND event.reason_code = 'platform_emergency_removal'
          AND event.changed_fields @> ARRAY['is_active', 'sessions']::varchar[]
          AND cardinality(event.changed_fields) = 2
          AND NOT subject.is_active AND subject.account_kind = 'person'
          AND actor.is_active AND actor.account_kind = 'platform_administrator'
          AND NOT EXISTS (
              SELECT 1 FROM public.identity_accountsession session
              WHERE session.account_id = source AND session.revoked_at IS NULL
          )
    );
$$ LANGUAGE sql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_identity_release_source_guard()
RETURNS trigger AS $$
DECLARE tracked_dependency_id uuid;
BEGIN
    IF TG_OP = 'UPDATE' AND
       (NEW.is_active, NEW.email_verified_at IS NULL, NEW.account_kind)
       IS NOT DISTINCT FROM
       (OLD.is_active, OLD.email_verified_at IS NULL, OLD.account_kind)
    THEN RETURN NEW; END IF;
    -- Check before testing key visibility: a repeatable-read writer could miss
    -- the first tracking key committed while it waited for this source row.
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'release source eligibility writes require READ COMMITTED'
            USING ERRCODE = '23514';
    END IF;
    IF TG_WHEN = 'BEFORE' THEN
        IF TG_OP = 'DELETE' THEN
            IF EXISTS (SELECT 1 FROM public.scheduling_schedulingreleasedependencykey
                       WHERE kind = 'identity_account' AND source_id = OLD.id) THEN
                RAISE EXCEPTION 'tracked release identities must be retained'
                    USING ERRCODE = '23514';
            END IF;
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;
    SELECT id INTO tracked_dependency_id
    FROM public.scheduling_schedulingreleasedependencykey
        WHERE kind = 'identity_account' AND source_id = NEW.id;
    IF tracked_dependency_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.scheduling_schedulingreleasedependencychange change
        JOIN public.audit_auditnativemutationwitness witness
          ON witness.audit_event_id = change.source_audit_id
        WHERE change.dependency_id = tracked_dependency_id
          AND witness.transaction_stamp =
              public.maru_audit_current_native_transaction_stamp()
          AND public.maru_identity_release_deactivation_valid(
              NEW.id, change.source_audit_id)
    ) THEN
        RAISE EXCEPTION
            'tracked identity change requires its native release invalidation'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

CREATE TRIGGER identity_release_source_shape
BEFORE UPDATE OR DELETE ON public.identity_account
FOR EACH ROW EXECUTE FUNCTION public.maru_identity_release_source_guard();
CREATE TRIGGER identity_release_source_identity
BEFORE UPDATE OR DELETE ON public.identity_account
FOR EACH ROW EXECUTE FUNCTION
public.maru_scheduling_release_source_identity_guard('identity_account');
CREATE CONSTRAINT TRIGGER identity_release_source_evidence
AFTER UPDATE ON public.identity_account
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_identity_release_source_guard();
"""

REVERSE_SQL = r"""
DROP TRIGGER identity_release_source_identity ON public.identity_account;
DROP TRIGGER identity_release_source_evidence ON public.identity_account;
DROP TRIGGER identity_release_source_shape ON public.identity_account;
DROP FUNCTION public.maru_identity_release_source_guard();
DROP FUNCTION public.maru_identity_release_deactivation_valid(uuid, uuid);
"""


def refuse_tracked_identity_downgrade(apps: Any, schema_editor: Any) -> None:
    """Retain native source enforcement once an account is release-tracked."""
    key = apps.get_model("scheduling", "SchedulingReleaseDependencyKey")
    schema_editor.execute(
        "LOCK TABLE public.scheduling_schedulingreleasedependencykey "
        "IN ACCESS EXCLUSIVE MODE"
    )
    if key.objects.filter(kind="identity_account").exists():
        raise RuntimeError(
            "Release-tracked Identity sources exist; retain guards and fix forward."
        )


class Migration(migrations.Migration):
    """Join native eligibility to Scheduling without acquiring foreign pointers."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("identity", "0020_programme_proposal_person_guard"),
        ("scheduling", "0008_release_dependency_guards"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_tracked_identity_downgrade
        ),
    ]
