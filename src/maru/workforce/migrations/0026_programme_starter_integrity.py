"""Guard retained own-person Programme starter approval and exact shared output."""

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_workforce_starter_request_guard()
RETURNS trigger AS $$
DECLARE person_id uuid;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Programme starter requests are append-only' USING ERRCODE = '23514';
    END IF;
    IF '00000000-0000-0000-0000-000000000000'::uuid = ANY(ARRAY[
        NEW.id, NEW.organization_id, NEW.series_id, NEW.edition_id,
        NEW.author_id, NEW.approver_id, NEW.idempotency_key,
        NEW.correlation_id, NEW.source_audit_id
    ]) OR NEW.author_id = NEW.approver_id
       OR NEW.request_digest !~ '^[0-9a-f]{64}$'
       OR NEW.definition_code <> 'workforce-volunteer' OR NEW.definition_version <> 1
       OR NEW.definition_digest <> '13823da0315a8f4c1bbaf1b465662e0896a894508e8bef8e1a45d36d6da63b6a'
       OR btrim(NEW.reason) = '' OR NEW.reason ~ '[[:cntrl:]]'
       OR NEW.source_channel !~ '^[a-z][a-z0-9_-]{0,31}$'
       OR NEW.source_channel ~ '[[:cntrl:]]'
       OR NEW.requested_at < transaction_timestamp()
       OR NEW.requested_at > clock_timestamp()
       OR NEW.approval_deadline <> NEW.requested_at + interval '7 days' THEN
        RAISE EXCEPTION 'Programme starter request intent is invalid' USING ERRCODE = '23514';
    END IF;
    IF public.maru_programme_role_scope_current(
        NEW.organization_id, NEW.edition_id, NULL, NULL
    ) IS DISTINCT FROM TRUE OR NOT EXISTS (
        SELECT 1 FROM public.events_eventedition edition
        JOIN public.organizations_conventionseries series ON series.id = edition.series_id
        WHERE edition.id = NEW.edition_id AND edition.organization_id = NEW.organization_id
          AND edition.series_id = NEW.series_id AND series.organization_id = NEW.organization_id
          AND edition.lifecycle IN ('draft', 'preparing')
          AND series.is_active
    ) THEN
        RAISE EXCEPTION 'Programme starter request scope is unavailable' USING ERRCODE = '23514';
    END IF;
    FOR person_id IN SELECT person FROM unnest(ARRAY[NEW.author_id, NEW.approver_id]) person ORDER BY person LOOP
        PERFORM 1 FROM public.identity_account account WHERE account.id = person_id
          AND account.is_active AND account.account_kind = 'person'
          AND account.email_verified_at IS NOT NULL FOR SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Programme starter requests require verified people' USING ERRCODE = '23514';
        END IF;
    END LOOP;
    IF NOT EXISTS (
        SELECT 1 FROM public.audit_auditevent audit
        WHERE audit.id = NEW.source_audit_id AND audit.principal_kind = 'account'
          AND audit.principal_id = NEW.author_id AND audit.principal_context_id IS NULL
          AND audit.organization_id = NEW.organization_id AND audit.event_edition_id = NEW.edition_id
          AND audit.capability_code = 'workforce.manage_structure'
          AND audit.operation = 'workforce.programme_starter.request'
          AND audit.target_type = 'workforce.programme_starter_request' AND audit.target_id = NEW.id
          AND audit.outcome = 'allow' AND audit.reason_code = 'own_person_action'
          AND audit.correlation_id = NEW.correlation_id AND audit.source_channel = NEW.source_channel
          AND audit.retention_class = 'security-extended'
    ) THEN
        RAISE EXCEPTION 'Programme starter request audit does not match' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_workforce_starter_decision_guard()
RETURNS trigger AS $$
DECLARE
    original public.workforce_programmestarterrequest%ROWTYPE;
    chosen public.workforce_positiontemplate%ROWTYPE;
    bundle public.authorization_rolebundle%ROWTYPE;
    person_id uuid;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Programme starter decisions are append-only' USING ERRCODE = '23514';
    END IF;
    IF '00000000-0000-0000-0000-000000000000'::uuid = ANY(ARRAY[
        NEW.id, NEW.request_id, NEW.actor_id, NEW.idempotency_key,
        NEW.correlation_id, NEW.source_audit_id, NEW.template_id, NEW.role_bundle_id
    ]) OR NEW.request_digest !~ '^[0-9a-f]{64}$'
       OR btrim(NEW.reason) = '' OR NEW.reason ~ '[[:cntrl:]]'
       OR NEW.source_channel !~ '^[a-z][a-z0-9_-]{0,31}$'
       OR NEW.source_channel ~ '[[:cntrl:]]'
       OR NEW.decided_at < transaction_timestamp()
       OR NEW.decided_at > clock_timestamp() THEN
        RAISE EXCEPTION 'Programme starter decision intent is invalid' USING ERRCODE = '23514';
    END IF;
    SELECT * INTO original FROM public.workforce_programmestarterrequest WHERE id = NEW.request_id;
    IF NOT FOUND OR NEW.decided_at < original.requested_at THEN
        RAISE EXCEPTION 'Programme starter decision intent is unavailable' USING ERRCODE = '23514';
    END IF;
    IF (NEW.action = 'cancel' AND NEW.actor_id <> original.author_id)
       OR (NEW.action IN ('approve', 'decline') AND NEW.actor_id <> original.approver_id) THEN
        RAISE EXCEPTION 'Programme starter decision must be the exact person own action' USING ERRCODE = '23514';
    END IF;
    IF NEW.action = 'approve' AND (
        NEW.decided_at >= original.approval_deadline
        OR clock_timestamp() >= original.approval_deadline
        OR public.maru_programme_role_scope_current(
            original.organization_id, original.edition_id, NULL, NULL
        ) IS DISTINCT FROM TRUE
        OR NOT EXISTS (
            SELECT 1 FROM public.events_eventedition edition
            JOIN public.organizations_conventionseries series ON series.id = edition.series_id
            WHERE edition.id = original.edition_id AND edition.organization_id = original.organization_id
              AND edition.series_id = original.series_id AND series.organization_id = original.organization_id
              AND edition.lifecycle IN ('draft', 'preparing') AND series.is_active
        )
    ) THEN
        RAISE EXCEPTION 'Programme starter approval scope or deadline is unavailable' USING ERRCODE = '23514';
    END IF;
    PERFORM 1 FROM public.workforce_programmestarterrequest WHERE id = NEW.request_id FOR UPDATE;
    FOR person_id IN SELECT person FROM unnest(ARRAY[original.author_id, original.approver_id]) person
        WHERE NEW.action = 'approve' OR person = NEW.actor_id ORDER BY person LOOP
        PERFORM 1 FROM public.identity_account account WHERE account.id = person_id
          AND account.is_active AND account.account_kind = 'person'
          AND account.email_verified_at IS NOT NULL FOR SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Programme starter decisions require verified people' USING ERRCODE = '23514';
        END IF;
    END LOOP;
    IF NEW.action = 'approve' THEN
        IF clock_timestamp() >= original.approval_deadline THEN
            RAISE EXCEPTION 'Programme starter approval expired while locking' USING ERRCODE = '23514';
        END IF;
        SELECT * INTO chosen FROM public.workforce_positiontemplate WHERE id = NEW.template_id FOR SHARE;
        SELECT * INTO bundle FROM public.authorization_rolebundle WHERE id = NEW.role_bundle_id FOR SHARE;
        IF chosen.id IS NULL OR bundle.id IS NULL
           OR chosen.organization_id <> original.organization_id OR bundle.organization_id <> original.organization_id
           OR chosen.role_bundle_id <> bundle.id
           OR chosen.code <> 'workforce-volunteer' OR bundle.code <> 'workforce-volunteer'
           OR chosen.version <> 1 OR bundle.version <> 1
           OR chosen.name <> 'Workforce volunteer' OR bundle.name <> 'Workforce volunteer'
           OR chosen.description <> 'Contributes to one convention without organizer or attendee authority.'
           OR chosen.default_headcount <> 1 OR chosen.status <> 'published'
           OR to_jsonb(chosen.default_capacity_codes) <> '["volunteer"]'::jsonb
           OR to_jsonb(bundle.capability_codes) <> '["events.view_basic", "workforce.view_structure"]'::jsonb
           OR (SELECT count(*) FROM public.workforce_positiontemplate WHERE organization_id = original.organization_id AND code = 'workforce-volunteer') <> 1
           OR (SELECT count(*) FROM public.authorization_rolebundle WHERE organization_id = original.organization_id AND code = 'workforce-volunteer') <> 1
           OR NOT EXISTS (SELECT 1 FROM public.authorization_authorityissuance issuance WHERE issuance.role_bundle_id = bundle.id)
           OR NEW.created_output IS DISTINCT FROM (chosen.created_at >= NEW.decided_at)
        THEN
            RAISE EXCEPTION 'Programme starter approval requires the exact shared definition' USING ERRCODE = '23514';
        END IF;
        IF NEW.created_output AND (
            chosen.created_by_id <> original.author_id OR bundle.created_by_id <> original.author_id
            OR bundle.approved_by_id <> original.approver_id OR bundle.reason <> original.reason
            OR bundle.created_at < NEW.decided_at
            OR NOT EXISTS (
                SELECT 1 FROM public.audit_auditevent audit
                WHERE audit.principal_id = original.approver_id AND audit.principal_kind = 'account'
                  AND audit.principal_context_id IS NULL AND audit.organization_id = original.organization_id
                  AND audit.event_edition_id IS NULL
                  AND audit.operation = 'authorization.role_bundle.version_create.approve'
                  AND audit.capability_code = 'authorization.manage_roles'
                  AND audit.target_type = 'authorization.role_bundle' AND audit.target_id = bundle.id
                  AND audit.outcome = 'allow' AND audit.reason_code = 'independent_approval'
                  AND audit.correlation_id = NEW.correlation_id AND audit.source_channel = NEW.source_channel
            )
        ) THEN
            RAISE EXCEPTION 'Programme starter output requires canonical independent evidence' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.audit_auditevent audit
        WHERE audit.id = NEW.source_audit_id AND audit.principal_kind = 'account'
          AND audit.principal_id = NEW.actor_id AND audit.principal_context_id IS NULL
          AND audit.organization_id = original.organization_id AND audit.event_edition_id = original.edition_id
          AND audit.capability_code = 'workforce.manage_structure'
          AND audit.operation = 'workforce.programme_starter.' || NEW.action
          AND audit.target_type = 'workforce.programme_starter_decision' AND audit.target_id = NEW.id
          AND audit.outcome = 'allow' AND audit.reason_code = 'own_person_action'
          AND audit.correlation_id = NEW.correlation_id AND audit.source_channel = NEW.source_channel
          AND audit.retention_class = 'security-extended'
    ) THEN
        RAISE EXCEPTION 'Programme starter decision audit does not match' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_workforce_starter_refuse_truncate()
RETURNS trigger AS $$
BEGIN
    IF public.maru_authority_provenance_test_reset_allowed() THEN RETURN NULL; END IF;
    RAISE EXCEPTION 'Programme starter evidence cannot be truncated' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, public, pg_temp;

CREATE TRIGGER workforce_programme_starter_request_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.workforce_programmestarterrequest
FOR EACH ROW EXECUTE FUNCTION public.maru_workforce_starter_request_guard();
CREATE TRIGGER workforce_programme_starter_decision_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.workforce_programmestarterdecision
FOR EACH ROW EXECUTE FUNCTION public.maru_workforce_starter_decision_guard();
CREATE TRIGGER workforce_programme_starter_request_no_truncate
BEFORE TRUNCATE ON public.workforce_programmestarterrequest
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_workforce_starter_refuse_truncate();
CREATE TRIGGER workforce_programme_starter_decision_no_truncate
BEFORE TRUNCATE ON public.workforce_programmestarterdecision
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_workforce_starter_refuse_truncate();
REVOKE ALL ON FUNCTION public.maru_workforce_starter_request_guard(),
    public.maru_workforce_starter_decision_guard(),
    public.maru_workforce_starter_refuse_truncate() FROM PUBLIC;
"""
REVERSE_SQL = r"""
DROP TRIGGER workforce_programme_starter_decision_no_truncate ON public.workforce_programmestarterdecision;
DROP TRIGGER workforce_programme_starter_request_no_truncate ON public.workforce_programmestarterrequest;
DROP TRIGGER workforce_programme_starter_decision_guard ON public.workforce_programmestarterdecision;
DROP TRIGGER workforce_programme_starter_request_guard ON public.workforce_programmestarterrequest;
DROP FUNCTION public.maru_workforce_starter_refuse_truncate();
DROP FUNCTION public.maru_workforce_starter_decision_guard();
DROP FUNCTION public.maru_workforce_starter_request_guard();
"""


class Migration(migrations.Migration):
    """Install exact append-only evidence guards without any runtime execution grant."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("workforce", "0025_programme_starter_records"),
    ]
    operations: ClassVar[list[object]] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
