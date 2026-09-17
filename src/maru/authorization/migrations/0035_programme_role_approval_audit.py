"""Correct the dormant decision guard to require the canonical approver audit."""

from typing import ClassVar

from django.db import migrations

# Frozen historical body: never import a mutable current command or older migration.
_OLD_FUNCTION_SQL = r"""CREATE FUNCTION public.maru_programme_role_decision_guard()
RETURNS trigger AS $$
DECLARE
    original public.authorization_programmerolerequest%ROWTYPE;
    recipe jsonb;
    person_id uuid;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Programme role decisions are append-only'
            USING ERRCODE = '23514';
    END IF;
    IF '00000000-0000-0000-0000-000000000000'::uuid = ANY(ARRAY[
        NEW.id, NEW.idempotency_key, NEW.correlation_id, NEW.actor_id, NEW.request_id,
        NEW.role_bundle_id, NEW.role_assignment_id, NEW.source_audit_id
    ]) OR NEW.request_digest !~ '^[0-9a-f]{64}$'
       OR btrim(NEW.reason) = '' OR NEW.reason ~ '[[:cntrl:]]'
       OR NEW.source_channel !~ '^[a-z][a-z0-9_-]{0,31}$'
       OR NEW.source_channel ~ '[[:cntrl:]]'
       OR NEW.decided_at < transaction_timestamp()
       OR NEW.decided_at > clock_timestamp()
    THEN
        RAISE EXCEPTION 'Programme role decision intent is invalid'
            USING ERRCODE = '23514';
    END IF;
    -- Resolve immutable identities first; owner locks precede request/person locks.
    SELECT * INTO original FROM public.authorization_programmerolerequest
     WHERE id = NEW.request_id;
    IF NOT FOUND OR NEW.decided_at < original.requested_at THEN
        RAISE EXCEPTION 'Programme role decision request is unavailable'
            USING ERRCODE = '23514';
    END IF;
    IF (NEW.action = 'cancel' AND NEW.actor_id <> original.author_id)
       OR (NEW.action IN ('approve', 'decline')
           AND NEW.actor_id <> original.approver_id)
    THEN
        RAISE EXCEPTION 'Programme role decision must be the exact person own action'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.action = 'approve' THEN
        IF NEW.decided_at >= original.approval_deadline
           OR clock_timestamp() >= original.approval_deadline
           OR original.expires_at <= NEW.decided_at
           OR original.expires_at <= clock_timestamp()
           OR NOT public.maru_programme_role_scope_current(
               original.organization_id, original.programme_edition_id,
               original.department_id, original.resource_binding_id
           )
        THEN
            RAISE EXCEPTION 'Programme role approval scope or interval is unavailable'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    PERFORM 1 FROM public.authorization_programmerolerequest
     WHERE id = NEW.request_id FOR UPDATE;
    FOR person_id IN SELECT DISTINCT person FROM unnest(
        ARRAY[original.author_id, original.approver_id, original.recipient_id]
    ) AS person WHERE NEW.action = 'approve' OR person = NEW.actor_id
      ORDER BY person LOOP
        PERFORM 1 FROM public.identity_account AS account
         WHERE account.id = person_id AND account.is_active
           AND account.account_kind = 'person'
           AND account.email_verified_at IS NOT NULL FOR SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Programme role decision requires current verified people'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;
    IF NEW.action = 'approve' THEN
        -- Request/person locking may have waited past the permitted decision window.
        IF clock_timestamp() >= original.approval_deadline
           OR original.expires_at <= clock_timestamp() THEN
            RAISE EXCEPTION 'Programme role approval expired while locking'
                USING ERRCODE = '23514';
        END IF;
        recipe := public.maru_programme_role_recipe(
            original.recipe_code, original.recipe_version
        );
        IF NOT EXISTS (
            SELECT 1 FROM public.authorization_roleassignment AS assignment
              JOIN public.authorization_rolebundle AS bundle
                ON bundle.id = assignment.role_bundle_id
              JOIN public.authorization_authorityissuance AS issuance
                ON issuance.role_assignment_id = assignment.id
             WHERE assignment.id = NEW.role_assignment_id
               AND assignment.role_bundle_id = NEW.role_bundle_id
               AND assignment.organization_id = original.organization_id
               AND assignment.edition_id IS NOT DISTINCT FROM original.edition_id
               AND assignment.department_id IS NOT DISTINCT FROM original.department_id
               AND assignment.resource_binding_id
                   IS NOT DISTINCT FROM original.resource_binding_id
               AND assignment.principal_id = original.recipient_id
               AND assignment.granted_by_id = original.author_id
               AND assignment.approved_by_id = original.approver_id
               AND assignment.reason = original.reason
               AND assignment.effective_from = greatest(
                   original.not_before, NEW.decided_at
               )
               AND assignment.expires_at IS NOT DISTINCT FROM original.expires_at
               AND assignment.revoked_at IS NULL
               AND assignment.created_at >= NEW.decided_at
               AND issuance.evaluated_at >= NEW.decided_at
               AND bundle.organization_id = original.organization_id
               AND bundle.code = recipe->>'role_code'
               AND bundle.version = original.recipe_version
               AND bundle.name = recipe->>'name'
               AND to_jsonb(bundle.capability_codes) = recipe->'capabilities'
        ) THEN
            RAISE EXCEPTION 'Programme role approval requires its exact new grant'
                USING ERRCODE = '23514';
        END IF;
        -- Existing authority guards retain the complete dual-controller lineage.
        IF NOT EXISTS (
            SELECT 1 FROM public.audit_auditevent AS audit
             WHERE audit.principal_id = original.approver_id
               AND audit.principal_kind = 'account'
               AND audit.principal_context_id IS NULL
               AND audit.organization_id = original.organization_id
               AND audit.event_edition_id IS NOT DISTINCT FROM original.edition_id
               AND audit.operation = 'authorization.role.assign'
               AND audit.capability_code = 'authorization.manage_roles'
               AND audit.target_type = 'authorization.role_assignment'
               AND audit.target_id = NEW.role_assignment_id
               AND audit.outcome = 'allow'
               AND audit.reason_code = 'independent_approval'
               AND audit.correlation_id = NEW.correlation_id
               AND audit.source_channel = NEW.source_channel
        ) THEN
            RAISE EXCEPTION 'Programme role approval assignment audit does not match'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.audit_auditevent AS audit
         WHERE audit.id = NEW.source_audit_id
           AND audit.principal_kind = 'account' AND audit.principal_id = NEW.actor_id
           AND audit.principal_context_id IS NULL
           AND audit.organization_id = original.organization_id
           AND audit.event_edition_id = original.programme_edition_id
           AND audit.operation = 'authorization.programme_role.' || NEW.action
           AND audit.capability_code = 'authorization.manage_roles'
           AND audit.target_type = 'authorization.programme_role_decision'
           AND audit.target_id = NEW.id AND audit.outcome = 'allow'
           AND audit.correlation_id = NEW.correlation_id
           AND audit.source_channel = NEW.source_channel
           AND audit.retention_class = 'security-extended'
    ) THEN
        RAISE EXCEPTION 'Programme role decision audit does not match'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
"""
_LOCKS = """
LOCK TABLE public.authorization_programmerolerequest,
    public.authorization_programmeroledecisionrecord IN ACCESS EXCLUSIVE MODE;
"""
_REVOKE = """
REVOKE ALL ON FUNCTION public.maru_programme_role_decision_guard() FROM PUBLIC;
"""
_PREFLIGHT = """
DO $approval_audit_preflight$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.authorization_programmeroledecisionrecord AS decision
          JOIN public.authorization_programmerolerequest AS original
            ON original.id = decision.request_id
         WHERE decision.action = 'approve' AND NOT EXISTS (
             SELECT 1 FROM public.audit_auditevent AS audit
              WHERE audit.operation = 'authorization.role.assign.approve'
                AND audit.principal_kind = 'account'
                AND audit.principal_id = original.approver_id
                AND audit.principal_context_id IS NULL
                AND audit.organization_id = original.organization_id
                AND audit.event_edition_id IS NOT DISTINCT FROM original.edition_id
                AND audit.capability_code = 'authorization.manage_roles'
                AND audit.target_type = 'authorization.role_assignment'
                AND audit.target_id = decision.role_assignment_id
                AND audit.outcome = 'allow'
                AND audit.reason_code = 'independent_approval'
                AND audit.correlation_id = decision.correlation_id
                AND audit.source_channel = decision.source_channel
         )
    ) THEN
        RAISE EXCEPTION 'Retained Programme approval needs canonical audit review'
            USING ERRCODE = '23514';
    END IF;
END;
$approval_audit_preflight$;
"""
_UNUSED_ONLY = """
DO $unused_approval_audit_reverse$
BEGIN
    IF EXISTS (SELECT 1 FROM public.authorization_programmerolerequest)
       OR EXISTS (SELECT 1 FROM public.authorization_programmeroledecisionrecord)
    THEN
        RAISE EXCEPTION 'Programme role evidence exists; retain it and fix forward'
            USING ERRCODE = '23514';
    END IF;
END;
$unused_approval_audit_reverse$;
"""
_OLD_REPLACEMENT = _OLD_FUNCTION_SQL.replace(
    "CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1
)
FORWARD_SQL = (
    _LOCKS
    + _PREFLIGHT
    + _OLD_REPLACEMENT.replace(
        "audit.operation = 'authorization.role.assign'",
        "audit.operation = 'authorization.role.assign.approve'",
    )
    + _REVOKE
)
REVERSE_SQL = _LOCKS + _UNUSED_ONLY + _OLD_REPLACEMENT + _REVOKE


class Migration(migrations.Migration):
    """Preserve existing evidence and correct only canonical approver attribution."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0034_programme_role_approval_downgrade_fence"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
