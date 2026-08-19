"""Install the approved Page 10 invitation retention evidence boundary."""

import uuid

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_invitation_provisioning_origin(apps, schema_editor):  # type: ignore[no-untyped-def]
    """Backfill only provenance already proved by the invitation receipt graph."""

    del apps
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "LOCK TABLE identity_account, identity_platformaccountinvitation, "
            "identity_platformaccountinvitationtransition, "
            "identity_platformaccountinvitationcommandreceipt "
            "IN SHARE ROW EXCLUSIVE MODE"
        )
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                  FROM identity_platformaccountinvitation AS invitation
                  LEFT JOIN identity_platformaccountinvitationtransition AS transition
                    ON transition.invitation_id = invitation.id
                   AND transition.version = 1
                   AND transition.operation = 'created'
                  LEFT JOIN identity_platformaccountinvitationcommandreceipt AS receipt
                    ON receipt.invitation_id = invitation.id
                   AND receipt.operation = 'create'
                   AND receipt.expected_version = 0
                   AND receipt.result_version = 1
                 WHERE transition.id IS NULL
                    OR receipt.id IS NULL
                    OR transition.actor_id IS DISTINCT FROM invitation.created_by_id
                    OR receipt.actor_id IS DISTINCT FROM invitation.created_by_id
                    OR transition.correlation_id IS DISTINCT FROM receipt.correlation_id
                    OR transition.source_channel IS DISTINCT FROM receipt.source_channel
            )
            """
        )
        malformed = cursor.fetchone()
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT account_id
                  FROM identity_platformaccountinvitation
                 GROUP BY account_id
                HAVING count(*) <> 1
            )
            """
        )
        duplicate = cursor.fetchone()
        if (
            malformed is None
            or bool(malformed[0])
            or duplicate is None
            or bool(duplicate[0])
        ):
            raise RuntimeError(
                "Cannot prove exact invitation provisioning origin for existing rows."
            )
        cursor.execute(
            """
            UPDATE identity_account AS account
               SET invitation_provisioning_origin_id = invitation.id
              FROM identity_platformaccountinvitation AS invitation
             WHERE invitation.account_id = account.id
               AND account.invitation_provisioning_origin_id IS NULL
            """
        )


def refuse_invitation_provenance_downgrade(apps, schema_editor):  # type: ignore[no-untyped-def]
    """Do not silently discard live retention/provisioning provenance."""

    del apps
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS (SELECT 1 FROM identity_platformaccountinvitation)
                OR EXISTS (SELECT 1 FROM identity_platforminvitationretentionhold)
                OR EXISTS (SELECT 1 FROM identity_platforminvitationretentionreceipt)
            """
        )
        populated = cursor.fetchone()
    if populated is None or bool(populated[0]):
        raise RuntimeError(
            "Refusing to discard invitation provisioning and retention provenance."
        )


INSTALL_RETENTION_GUARDS = r"""
CREATE FUNCTION identity_page10_retention_policy_control_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'TRUNCATE')
       AND public.maru_authority_provenance_test_reset_allowed() THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NULL;
    END IF;
    IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
        RAISE EXCEPTION 'invitation retention policy control is protected'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.singleton IS DISTINCT FROM TRUE
       OR NEW.generation IS DISTINCT FROM 'retention-policy-v1'
       OR NEW.policy_digest !~ '^[0-9a-f]{64}$'
       OR NEW.policy_id !~ '^[a-z0-9][a-z0-9_.:-]{0,119}$'
       OR NEW.policy_approved_by_reference !~
            '^[a-z0-9][a-z0-9_.:-]{0,119}$'
       OR NEW.jurisdiction_code !~ '^[A-Z0-9][A-Z0-9_.:-]{0,39}$'
       OR NEW.trigger IS DISTINCT FROM 'terminal_transition'
       OR NEW.retention_period_days > 36500
       OR NEW.action IS DISTINCT FROM
            'anonymize_abandoned_invitation_contact'
       OR NEW.policy_approved_at > NEW.activated_at
       OR NEW.activated_at > clock_timestamp() + interval '1 second' THEN
        RAISE EXCEPTION 'invitation retention policy progression is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' AND (
        NEW.singleton IS DISTINCT FROM OLD.singleton
        OR NEW.policy_version <= OLD.policy_version
        OR NEW.activated_at <= OLD.activated_at
    ) THEN
        RAISE EXCEPTION 'invitation retention policy progression is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION identity_page10_token_digest_key_guard()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    retention_receipt_exists boolean := false;
BEGIN
    IF NEW.purpose <> 'account_invitation' THEN
        IF NEW.token_digest_key_id <> '' THEN
            RAISE EXCEPTION 'non-invitation challenge has an invitation digest key'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'UPDATE'
       AND NEW.token_digest_key_id IS DISTINCT FROM OLD.token_digest_key_id THEN
        SELECT EXISTS (
            SELECT 1
              FROM identity_platforminvitationretentionreceipt AS receipt
              JOIN identity_platformaccountinvitation AS invitation
                ON invitation.id = receipt.invitation_id
             WHERE receipt.invitation_id = OLD.invitation_id
               AND receipt.terminal_version = invitation.aggregate_version
               AND invitation.status IN ('revoked', 'expired')
        ) INTO retention_receipt_exists;
        IF retention_receipt_exists IS DISTINCT FROM true
           OR OLD.token_digest_key_id !~
                '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'
           OR NEW.token_digest_key_id <> ''
           OR OLD.consumed_at IS NOT NULL
           OR OLD.invalidated_at IS NULL
           OR NEW.consumed_at IS DISTINCT FROM OLD.consumed_at
           OR NEW.invalidated_at IS DISTINCT FROM OLD.invalidated_at THEN
            RAISE EXCEPTION 'invitation challenge digest-key lineage is immutable'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF NEW.token_digest_key_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$' THEN
        RETURN NEW;
    END IF;
    IF TG_OP = 'INSERT'
       OR (NEW.consumed_at IS NULL AND NEW.invalidated_at IS NULL) THEN
        RAISE EXCEPTION 'active invitation challenge lacks a versioned digest key'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION identity_page10_challenge_guard()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    invitation_record record;
    account_email text;
    retention_receipt_exists boolean := false;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.purpose = 'account_invitation' THEN
            RAISE EXCEPTION 'invitation challenges require controlled retention'
                USING ERRCODE = '23514';
        END IF;
        RETURN OLD;
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.purpose = 'account_invitation' AND (
        NEW.id IS DISTINCT FROM OLD.id
        OR NEW.account_id IS DISTINCT FROM OLD.account_id
        OR NEW.purpose IS DISTINCT FROM OLD.purpose
        OR NEW.token_digest IS DISTINCT FROM OLD.token_digest
        OR NEW.token_digest_key_id IS DISTINCT FROM OLD.token_digest_key_id
        OR NEW.email_snapshot IS DISTINCT FROM OLD.email_snapshot
        OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
        OR NEW.invitation_id IS DISTINCT FROM OLD.invitation_id
        OR NEW.invitation_version IS DISTINCT FROM OLD.invitation_version
        OR NEW.request_fingerprint IS DISTINCT FROM OLD.request_fingerprint
        OR NEW.created_at IS DISTINCT FROM OLD.created_at
    ) THEN
        SELECT EXISTS (
            SELECT 1
              FROM identity_platforminvitationretentionreceipt AS receipt
              JOIN identity_platformaccountinvitation AS invitation
                ON invitation.id = receipt.invitation_id
             WHERE receipt.invitation_id = OLD.invitation_id
               AND receipt.terminal_version = invitation.aggregate_version
               AND invitation.status IN ('revoked', 'expired')
        ) INTO retention_receipt_exists;
        IF retention_receipt_exists IS DISTINCT FROM true
           OR NEW.id IS DISTINCT FROM OLD.id
           OR NEW.account_id IS DISTINCT FROM OLD.account_id
           OR NEW.purpose IS DISTINCT FROM OLD.purpose
           OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
           OR NEW.consumed_at IS DISTINCT FROM OLD.consumed_at
           OR NEW.invalidated_at IS DISTINCT FROM OLD.invalidated_at
           OR NEW.invalidation_reason IS DISTINCT FROM OLD.invalidation_reason
           OR NEW.invitation_id IS DISTINCT FROM OLD.invitation_id
           OR NEW.invitation_version IS DISTINCT FROM OLD.invitation_version
           OR NEW.attempt_count IS DISTINCT FROM OLD.attempt_count
           OR NEW.delivery_status IS DISTINCT FROM OLD.delivery_status
           OR NEW.delivery_attempt_count IS DISTINCT FROM OLD.delivery_attempt_count
           OR NEW.last_delivery_attempt_at IS DISTINCT FROM OLD.last_delivery_attempt_at
           OR NEW.delivered_at IS DISTINCT FROM OLD.delivered_at
           OR NEW.delivery_error_code IS DISTINCT FROM OLD.delivery_error_code
           OR NEW.created_at IS DISTINCT FROM OLD.created_at
           OR OLD.consumed_at IS NOT NULL
           OR OLD.invalidated_at IS NULL
           OR NEW.token_digest !~ '^[0-9a-f]{64}$'
           OR NEW.token_digest_key_id <> ''
           OR NEW.request_fingerprint !~ '^[0-9a-f]{64}$'
           OR NEW.email_snapshot !~
                '^disposed-[0-9a-f]{32}@account[.]invalid$' THEN
            RAISE EXCEPTION
                'invitation challenge origin and digest-key lineage is immutable'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF NEW.purpose <> 'account_invitation' THEN
        RETURN NEW;
    END IF;
    SELECT account_id, aggregate_version INTO invitation_record
      FROM identity_platformaccountinvitation WHERE id = NEW.invitation_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'invitation challenge parent is unavailable'
            USING ERRCODE = '23514';
    END IF;
    SELECT email INTO account_email
      FROM identity_account WHERE id = NEW.account_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'invitation challenge account is unavailable'
            USING ERRCODE = '23514';
    END IF;
    IF invitation_record.account_id IS DISTINCT FROM NEW.account_id
       OR NEW.invitation_version IS NULL
       OR NEW.invitation_version > invitation_record.aggregate_version
       OR lower(NEW.email_snapshot) IS DISTINCT FROM lower(account_email) THEN
        RAISE EXCEPTION 'invitation challenge lineage is inconsistent'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION identity_page10_hardened_challenge_guard()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    invitation_record record;
    account_email text;
    retention_receipt_exists boolean := false;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.purpose = 'account_invitation' THEN
            RAISE EXCEPTION 'invitation challenge origin is permanently protected'
                USING ERRCODE = '23514';
        END IF;
        RETURN OLD;
    END IF;

    IF TG_OP = 'UPDATE' AND OLD.purpose = 'account_invitation' AND (
        NEW.id IS DISTINCT FROM OLD.id
        OR NEW.account_id IS DISTINCT FROM OLD.account_id
        OR NEW.purpose IS DISTINCT FROM OLD.purpose
        OR NEW.token_digest IS DISTINCT FROM OLD.token_digest
        OR NEW.token_digest_key_id IS DISTINCT FROM OLD.token_digest_key_id
        OR NEW.email_snapshot IS DISTINCT FROM OLD.email_snapshot
        OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
        OR NEW.invitation_id IS DISTINCT FROM OLD.invitation_id
        OR NEW.invitation_version IS DISTINCT FROM OLD.invitation_version
        OR NEW.request_fingerprint IS DISTINCT FROM OLD.request_fingerprint
        OR NEW.created_at IS DISTINCT FROM OLD.created_at
    ) THEN
        SELECT EXISTS (
            SELECT 1
              FROM identity_platforminvitationretentionreceipt AS receipt
              JOIN identity_platformaccountinvitation AS invitation
                ON invitation.id = receipt.invitation_id
             WHERE receipt.invitation_id = OLD.invitation_id
               AND receipt.terminal_version = invitation.aggregate_version
               AND invitation.status IN ('revoked', 'expired')
        ) INTO retention_receipt_exists;
        IF retention_receipt_exists IS DISTINCT FROM true
           OR NEW.id IS DISTINCT FROM OLD.id
           OR NEW.account_id IS DISTINCT FROM OLD.account_id
           OR NEW.purpose IS DISTINCT FROM OLD.purpose
           OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
           OR NEW.consumed_at IS DISTINCT FROM OLD.consumed_at
           OR NEW.invalidated_at IS DISTINCT FROM OLD.invalidated_at
           OR NEW.invalidation_reason IS DISTINCT FROM OLD.invalidation_reason
           OR NEW.invitation_id IS DISTINCT FROM OLD.invitation_id
           OR NEW.invitation_version IS DISTINCT FROM OLD.invitation_version
           OR NEW.attempt_count IS DISTINCT FROM OLD.attempt_count
           OR NEW.delivery_status IS DISTINCT FROM OLD.delivery_status
           OR NEW.delivery_attempt_count IS DISTINCT FROM OLD.delivery_attempt_count
           OR NEW.last_delivery_attempt_at IS DISTINCT FROM OLD.last_delivery_attempt_at
           OR NEW.delivered_at IS DISTINCT FROM OLD.delivered_at
           OR NEW.delivery_error_code IS DISTINCT FROM OLD.delivery_error_code
           OR NEW.created_at IS DISTINCT FROM OLD.created_at
           OR OLD.consumed_at IS NOT NULL
           OR OLD.invalidated_at IS NULL
           OR NEW.token_digest !~ '^[0-9a-f]{64}$'
           OR NEW.token_digest_key_id <> ''
           OR NEW.request_fingerprint !~ '^[0-9a-f]{64}$'
           OR NEW.email_snapshot !~
                '^disposed-[0-9a-f]{32}@account[.]invalid$' THEN
            RAISE EXCEPTION
                'invitation challenge origin and digest-key lineage is immutable'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF NEW.purpose <> 'account_invitation' THEN
        RETURN NEW;
    END IF;
    SELECT account_id, aggregate_version INTO invitation_record
      FROM identity_platformaccountinvitation WHERE id = NEW.invitation_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'invitation challenge parent is unavailable'
            USING ERRCODE = '23514';
    END IF;
    SELECT email INTO account_email
      FROM identity_account WHERE id = NEW.account_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'invitation challenge account is unavailable'
            USING ERRCODE = '23514';
    END IF;
    IF invitation_record.account_id IS DISTINCT FROM NEW.account_id
       OR NEW.invitation_version IS NULL
       OR NEW.invitation_version > invitation_record.aggregate_version
       OR lower(NEW.email_snapshot) IS DISTINCT FROM lower(account_email) THEN
        RAISE EXCEPTION 'invitation challenge lineage is inconsistent'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION identity_page10_invitation_origin_complete() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    lineage_count bigint;
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.invitation_provisioning_origin_id IS NOT NULL
       AND NEW.invitation_provisioning_origin_id IS DISTINCT FROM
            OLD.invitation_provisioning_origin_id THEN
        RAISE EXCEPTION 'invitation provisioning origin is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.invitation_provisioning_origin_id IS NULL THEN
        RETURN NULL;
    END IF;
    SELECT count(*) INTO lineage_count
      FROM identity_platformaccountinvitation AS invitation
      JOIN identity_platformaccountinvitationtransition AS transition
        ON transition.invitation_id = invitation.id
       AND transition.version = 1
       AND transition.operation = 'created'
      JOIN identity_platformaccountinvitationcommandreceipt AS receipt
        ON receipt.invitation_id = invitation.id
       AND receipt.operation = 'create'
       AND receipt.expected_version = 0
       AND receipt.result_version = 1
     WHERE invitation.id = NEW.invitation_provisioning_origin_id
       AND invitation.account_id = NEW.id
       AND transition.actor_id = invitation.created_by_id
       AND receipt.actor_id = invitation.created_by_id
       AND receipt.correlation_id = transition.correlation_id
       AND receipt.source_channel = transition.source_channel
       AND NOT EXISTS (
            SELECT 1 FROM identity_platformaccountinvitation AS sibling
             WHERE sibling.account_id = NEW.id
               AND sibling.id <> invitation.id
       );
    IF lineage_count <> 1 THEN
        RAISE EXCEPTION 'invitation provisioning origin lacks exact creation lineage'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION identity_page10_retention_hold_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    actor_record record;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'invitation retention holds are protected'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.reference_code !~ '^[a-z0-9][a-z0-9_.:-]{0,119}$'
       OR NEW.reason_code !~ '^[a-z0-9][a-z0-9_.:-]{0,119}$'
       OR NEW.placed_at < (
            SELECT created_at FROM identity_platformaccountinvitation
             WHERE id = NEW.invitation_id
       )
       OR NEW.created_at < NEW.placed_at
       OR NEW.placed_at > clock_timestamp() + interval '1 second'
       OR NEW.created_at > clock_timestamp() + interval '1 second' THEN
        RAISE EXCEPTION 'invitation retention hold evidence is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1 FROM identity_platforminvitationretentionreceipt
         WHERE invitation_id = NEW.invitation_id
    ) THEN
        RAISE EXCEPTION 'disposed invitation contact cannot be held later'
            USING ERRCODE = '23514';
    END IF;
    SELECT account_kind, is_active INTO actor_record
      FROM identity_account WHERE id = NEW.placed_by_id;
    IF NOT FOUND OR actor_record.account_kind <> 'platform_administrator'
       OR actor_record.is_active IS DISTINCT FROM true THEN
        RAISE EXCEPTION 'retention hold actor is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.active IS DISTINCT FROM true
           OR NEW.released_at IS NOT NULL OR NEW.released_by_id IS NOT NULL
           OR NEW.release_reason_code <> ''
           OR NEW.release_correlation_id IS NOT NULL THEN
            RAISE EXCEPTION 'new invitation retention hold must be active'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.invitation_id IS DISTINCT FROM OLD.invitation_id
       OR NEW.reference_code IS DISTINCT FROM OLD.reference_code
       OR NEW.reason_code IS DISTINCT FROM OLD.reason_code
       OR NEW.placed_at IS DISTINCT FROM OLD.placed_at
       OR NEW.placed_by_id IS DISTINCT FROM OLD.placed_by_id
       OR NEW.place_correlation_id IS DISTINCT FROM OLD.place_correlation_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR OLD.active IS DISTINCT FROM true OR NEW.active IS DISTINCT FROM false
       OR NEW.released_at IS NULL OR NEW.released_at < NEW.placed_at
       OR NEW.released_at > clock_timestamp() + interval '1 second'
       OR NEW.released_by_id IS NULL
       OR NEW.release_reason_code !~ '^[a-z0-9][a-z0-9_.:-]{0,119}$'
       OR NEW.release_correlation_id IS NULL THEN
        RAISE EXCEPTION 'retention hold release is invalid'
            USING ERRCODE = '23514';
    END IF;
    SELECT account_kind, is_active INTO actor_record
      FROM identity_account WHERE id = NEW.released_by_id;
    IF NOT FOUND OR actor_record.account_kind <> 'platform_administrator'
       OR actor_record.is_active IS DISTINCT FROM true THEN
        RAISE EXCEPTION 'retention hold release actor is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION identity_page10_retention_hold_complete() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    audit_count bigint;
BEGIN
    IF NEW.active THEN
        SELECT count(*) INTO audit_count FROM audit_auditevent AS event
         WHERE event.operation =
                    'identity.account_invitation.retention_hold.place'
           AND event.target_type =
                    'identity.platform_invitation_retention_hold'
           AND event.target_id = NEW.id
           AND event.principal_kind = 'account'
           AND event.principal_id = NEW.placed_by_id
           AND event.correlation_id = NEW.place_correlation_id
           AND event.occurred_at = NEW.placed_at
           AND event.capability_code = 'identity.manage_account_invitations'
           AND event.outcome = 'allow';
    ELSE
        SELECT count(*) INTO audit_count FROM audit_auditevent AS event
         WHERE event.operation =
                    'identity.account_invitation.retention_hold.release'
           AND event.target_type =
                    'identity.platform_invitation_retention_hold'
           AND event.target_id = NEW.id
           AND event.principal_kind = 'account'
           AND event.principal_id = NEW.released_by_id
           AND event.correlation_id = NEW.release_correlation_id
           AND event.occurred_at = NEW.released_at
           AND event.capability_code = 'identity.manage_account_invitations'
           AND event.outcome = 'allow';
    END IF;
    IF audit_count <> 1 THEN
        RAISE EXCEPTION 'retention hold lacks exact audit evidence'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION identity_page10_retention_account_is_unrelated(
    target_account_id uuid,
    target_invitation_id uuid
) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    foreign_key record;
    relationship_exists boolean;
BEGIN
    IF target_account_id IS NULL OR target_invitation_id IS NULL THEN
        RETURN false;
    END IF;

    IF EXISTS (
        SELECT 1 FROM public.identity_platformaccountinvitation
         WHERE account_id = target_account_id
           AND id <> target_invitation_id
    ) OR EXISTS (
        SELECT 1 FROM public.identity_identitychallenge
         WHERE account_id = target_account_id
           AND (
                purpose <> 'account_invitation'
                OR invitation_id IS DISTINCT FROM target_invitation_id
           )
    ) OR EXISTS (
        SELECT 1 FROM public.identity_accountsecurityevent
         WHERE account_id = target_account_id
           AND event_type NOT IN (
                'account_invitation_created',
                'account_invitation_reissued',
                'account_invitation_revoked',
                'account_invitation_expired'
           )
    ) THEN
        RETURN false;
    END IF;

    FOR foreign_key IN
        SELECT namespace.nspname AS schema_name,
               relation.relname AS relation_name,
               attribute.attname AS column_name,
               pg_catalog.array_length(constraint_record.conkey, 1) AS key_count,
               referenced_attribute.attname AS referenced_column_name
          FROM pg_catalog.pg_constraint AS constraint_record
          JOIN pg_catalog.pg_class AS relation
            ON relation.oid = constraint_record.conrelid
          JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
          LEFT JOIN pg_catalog.pg_attribute AS attribute
            ON attribute.attrelid = constraint_record.conrelid
           AND attribute.attnum = constraint_record.conkey[1]
          LEFT JOIN pg_catalog.pg_attribute AS referenced_attribute
            ON referenced_attribute.attrelid = constraint_record.confrelid
           AND referenced_attribute.attnum = constraint_record.confkey[1]
         WHERE constraint_record.contype = 'f'
           AND constraint_record.confrelid =
                'public.identity_account'::pg_catalog.regclass
         ORDER BY namespace.nspname, relation.relname, constraint_record.oid
    LOOP
        IF foreign_key.key_count IS DISTINCT FROM 1
           OR foreign_key.column_name IS NULL
           OR foreign_key.referenced_column_name IS DISTINCT FROM 'id' THEN
            RETURN false;
        END IF;
        IF foreign_key.schema_name = 'public'
           AND (
                (
                    foreign_key.relation_name =
                        'identity_platformaccountinvitation'
                    AND foreign_key.column_name = 'account_id'
                ) OR (
                    foreign_key.relation_name = 'identity_identitychallenge'
                    AND foreign_key.column_name = 'account_id'
                ) OR (
                    foreign_key.relation_name = 'identity_accountsecurityevent'
                    AND foreign_key.column_name = 'account_id'
                )
           ) THEN
            CONTINUE;
        END IF;
        EXECUTE pg_catalog.format(
            'SELECT EXISTS (SELECT 1 FROM %I.%I WHERE %I = $1)',
            foreign_key.schema_name,
            foreign_key.relation_name,
            foreign_key.column_name
        ) INTO relationship_exists USING target_account_id;
        IF relationship_exists THEN
            RETURN false;
        END IF;
    END LOOP;
    RETURN true;
EXCEPTION WHEN OTHERS THEN
    RETURN false;
END;
$$;

CREATE FUNCTION identity_page10_retention_receipt_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    invitation_record record;
    account_record record;
    policy_record record;
    terminal_at timestamptz;
BEGIN
    SELECT * INTO invitation_record
      FROM identity_platformaccountinvitation WHERE id = NEW.invitation_id;
    SELECT * INTO policy_record
      FROM identity_platforminvitationretentionpolicycontrol
     WHERE singleton = true;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'activated invitation retention policy is unavailable'
            USING ERRCODE = '23514';
    END IF;
    SELECT account_kind, is_active, is_staff, is_superuser,
           email_verified_at, password, invitation_provisioning_origin_id
      INTO account_record
      FROM identity_account WHERE id = invitation_record.account_id;
    terminal_at := CASE invitation_record.status
        WHEN 'revoked' THEN invitation_record.revoked_at
        WHEN 'expired' THEN invitation_record.expired_at
        ELSE NULL
    END;
    IF invitation_record.id IS NULL OR account_record.account_kind IS NULL
       OR NEW.inventory_control_id IS DISTINCT FROM true
       OR NOT EXISTS (
            SELECT 1 FROM identity_platformaccountinventorycontrol
             WHERE singleton = true
       )
       OR invitation_record.status NOT IN ('revoked', 'expired')
       OR invitation_record.current_challenge_id IS NOT NULL
       OR terminal_at IS NULL OR NEW.trigger_at IS DISTINCT FROM terminal_at
       OR NEW.terminal_version IS DISTINCT FROM invitation_record.aggregate_version
       OR account_record.invitation_provisioning_origin_id IS DISTINCT FROM
            invitation_record.id
       OR account_record.account_kind <> 'person' OR account_record.is_active
       OR account_record.is_staff OR account_record.is_superuser
       OR account_record.email_verified_at IS NOT NULL
       OR left(account_record.password, 1) <> '!' THEN
        RAISE EXCEPTION 'invitation retention target is not abandoned'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.policy_id IS DISTINCT FROM policy_record.policy_id
       OR NEW.policy_version IS DISTINCT FROM policy_record.policy_version
       OR NEW.policy_digest IS DISTINCT FROM policy_record.policy_digest
       OR NEW.jurisdiction_code IS DISTINCT FROM policy_record.jurisdiction_code
       OR NEW.policy_approved_by_reference IS DISTINCT FROM
            policy_record.policy_approved_by_reference
       OR NEW.policy_approved_at IS DISTINCT FROM policy_record.policy_approved_at
       OR NEW.trigger IS DISTINCT FROM policy_record.trigger
       OR NEW.retention_period_days IS DISTINCT FROM
            policy_record.retention_period_days
       OR NEW.action IS DISTINCT FROM policy_record.action THEN
        RAISE EXCEPTION 'invitation retention policy selection is inconsistent'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.due_at IS DISTINCT FROM
            NEW.trigger_at + (NEW.retention_period_days * interval '1 day') THEN
        RAISE EXCEPTION 'invitation retention due time is inconsistent'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.applied_at < NEW.due_at THEN
        RAISE EXCEPTION 'invitation retention was applied before it was due'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.policy_approved_at > NEW.applied_at THEN
        RAISE EXCEPTION 'invitation retention predates policy approval'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.created_at < NEW.applied_at THEN
        RAISE EXCEPTION 'invitation retention receipt predates application'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.applied_at > clock_timestamp() + interval '1 second' THEN
        RAISE EXCEPTION 'invitation retention application time is in the future'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.created_at > clock_timestamp() + interval '1 second' THEN
        RAISE EXCEPTION 'invitation retention receipt time is in the future'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.source_channel !~ '^[a-z][a-z0-9_-]{0,39}$'
       OR NEW.safe_result_code IS DISTINCT FROM
            'abandoned_invitation_contact_anonymized' THEN
        RAISE EXCEPTION 'invitation retention result evidence is inconsistent'
            USING ERRCODE = '23514';
    END IF;
    IF NOT identity_page10_retention_account_is_unrelated(
        invitation_record.account_id,
        invitation_record.id
    ) OR EXISTS (
        SELECT 1 FROM identity_platforminvitationretentionhold
         WHERE invitation_id = NEW.invitation_id AND active
    ) OR EXISTS (
        SELECT 1 FROM identity_platformaccountinvitation
         WHERE account_id = invitation_record.account_id
           AND id <> invitation_record.id
    ) OR NOT EXISTS (
        SELECT 1 FROM identity_identitychallenge
         WHERE invitation_id = invitation_record.id
           AND purpose = 'account_invitation'
    ) OR EXISTS (
        SELECT 1 FROM identity_identitychallenge
         WHERE invitation_id = invitation_record.id
           AND (purpose <> 'account_invitation'
                OR consumed_at IS NOT NULL OR invalidated_at IS NULL)
    ) OR NOT EXISTS (
        SELECT 1 FROM identity_platformidentitydelivery
         WHERE invitation_id = invitation_record.id
    ) OR EXISTS (
        SELECT 1 FROM identity_platformidentitydelivery
         WHERE invitation_id = invitation_record.id
           AND (payload_destroyed_at IS NULL OR status = 'processing'
                OR reconciliation_state = 'required')
    ) THEN
        RAISE EXCEPTION 'invitation retention dependencies are not closed'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION identity_page10_retention_receipt_complete() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    account_record record;
    audit_count bigint;
BEGIN
    SELECT account.email, account.login_handle, account.display_name,
           account.invitation_provisioning_origin_id
      INTO account_record
      FROM identity_account AS account
      JOIN identity_platformaccountinvitation AS invitation
        ON invitation.account_id = account.id
     WHERE invitation.id = NEW.invitation_id;
    SELECT count(*) INTO audit_count FROM audit_auditevent AS event
     WHERE event.operation = 'identity.account_invitation.retention_apply'
       AND event.target_type = 'identity.platform_account_invitation'
       AND event.target_id = NEW.invitation_id
       AND event.principal_kind = 'system'
       AND event.principal_id IS NULL
       AND event.correlation_id = NEW.correlation_id
       AND event.occurred_at = NEW.applied_at
       AND event.capability_code = 'identity.manage_account_invitations'
       AND event.outcome = 'allow'
       AND event.safe_metadata ->> 'policy_digest' = NEW.policy_digest;
    IF account_record.email !~
            '^disposed-[0-9a-f]{32}@account[.]invalid$'
       OR account_record.login_handle <> ''
       OR account_record.display_name <> ''
       OR account_record.invitation_provisioning_origin_id IS DISTINCT FROM
            NEW.invitation_id
       OR audit_count <> 1
       OR EXISTS (
            SELECT 1 FROM identity_identitychallenge
             WHERE invitation_id = NEW.invitation_id
               AND (email_snapshot IS DISTINCT FROM account_record.email
                    OR token_digest_key_id <> ''
                    OR token_digest !~ '^[0-9a-f]{64}$'
                    OR request_fingerprint !~ '^[0-9a-f]{64}$'
                    OR consumed_at IS NOT NULL OR invalidated_at IS NULL)
       ) OR EXISTS (
            SELECT 1 FROM identity_platformidentitydelivery
             WHERE invitation_id = NEW.invitation_id
               AND (payload_destroyed_at IS NULL OR status = 'processing'
                    OR reconciliation_state = 'required')
       ) OR EXISTS (
            SELECT 1 FROM identity_platforminvitationretentionhold
             WHERE invitation_id = NEW.invitation_id AND active
       ) THEN
        RAISE EXCEPTION 'invitation retention receipt is incomplete'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

REVOKE ALL ON FUNCTION
    identity_page10_retention_policy_control_guard(),
    identity_page10_token_digest_key_guard(),
    identity_page10_challenge_guard(),
    identity_page10_hardened_challenge_guard(),
    identity_page10_invitation_origin_complete(),
    identity_page10_retention_hold_guard(),
    identity_page10_retention_hold_complete(),
    identity_page10_retention_account_is_unrelated(uuid, uuid),
    identity_page10_retention_receipt_guard(),
    identity_page10_retention_receipt_complete()
FROM PUBLIC;

CREATE TRIGGER identity_page10_retention_policy_update
BEFORE INSERT OR UPDATE OR DELETE
ON identity_platforminvitationretentionpolicycontrol
FOR EACH ROW EXECUTE FUNCTION identity_page10_retention_policy_control_guard();
CREATE TRIGGER identity_page10_retention_policy_no_truncate
BEFORE TRUNCATE ON identity_platforminvitationretentionpolicycontrol
FOR EACH STATEMENT EXECUTE FUNCTION identity_page10_retention_policy_control_guard();

CREATE CONSTRAINT TRIGGER identity_page10_invitation_origin_insert_complete
AFTER INSERT ON identity_account
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION identity_page10_invitation_origin_complete();

CREATE CONSTRAINT TRIGGER identity_page10_invitation_origin_update_complete
AFTER UPDATE OF invitation_provisioning_origin_id ON identity_account
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION identity_page10_invitation_origin_complete();

CREATE TRIGGER identity_page10_retention_hold_write
BEFORE INSERT OR UPDATE OR DELETE
ON identity_platforminvitationretentionhold
FOR EACH ROW EXECUTE FUNCTION identity_page10_retention_hold_guard();
CREATE TRIGGER identity_page10_retention_hold_no_truncate
BEFORE TRUNCATE ON identity_platforminvitationretentionhold
FOR EACH STATEMENT EXECUTE FUNCTION identity_page10_append_only_guard();
CREATE CONSTRAINT TRIGGER identity_page10_retention_hold_complete
AFTER INSERT OR UPDATE ON identity_platforminvitationretentionhold
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION identity_page10_retention_hold_complete();

CREATE TRIGGER identity_page10_retention_receipt_insert
BEFORE INSERT ON identity_platforminvitationretentionreceipt
FOR EACH ROW EXECUTE FUNCTION identity_page10_retention_receipt_guard();
CREATE TRIGGER identity_page10_retention_receipt_immutable
BEFORE UPDATE OR DELETE ON identity_platforminvitationretentionreceipt
FOR EACH ROW EXECUTE FUNCTION identity_page10_append_only_guard();
CREATE TRIGGER identity_page10_retention_receipt_no_truncate
BEFORE TRUNCATE ON identity_platforminvitationretentionreceipt
FOR EACH STATEMENT EXECUTE FUNCTION identity_page10_append_only_guard();
CREATE CONSTRAINT TRIGGER identity_page10_retention_receipt_complete
AFTER INSERT ON identity_platforminvitationretentionreceipt
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION identity_page10_retention_receipt_complete();
"""


REMOVE_RETENTION_GUARDS = r"""
DROP TRIGGER IF EXISTS identity_page10_retention_receipt_complete
    ON identity_platforminvitationretentionreceipt;
DROP TRIGGER IF EXISTS identity_page10_retention_receipt_no_truncate
    ON identity_platforminvitationretentionreceipt;
DROP TRIGGER IF EXISTS identity_page10_retention_receipt_immutable
    ON identity_platforminvitationretentionreceipt;
DROP TRIGGER IF EXISTS identity_page10_retention_receipt_insert
    ON identity_platforminvitationretentionreceipt;
DROP TRIGGER IF EXISTS identity_page10_retention_hold_complete
    ON identity_platforminvitationretentionhold;
DROP TRIGGER IF EXISTS identity_page10_retention_hold_no_truncate
    ON identity_platforminvitationretentionhold;
DROP TRIGGER IF EXISTS identity_page10_retention_hold_write
    ON identity_platforminvitationretentionhold;
DROP TRIGGER IF EXISTS identity_page10_retention_policy_no_truncate
    ON identity_platforminvitationretentionpolicycontrol;
DROP TRIGGER IF EXISTS identity_page10_retention_policy_update
    ON identity_platforminvitationretentionpolicycontrol;
DROP TRIGGER IF EXISTS identity_page10_invitation_origin_update_complete
    ON identity_account;
DROP TRIGGER IF EXISTS identity_page10_invitation_origin_insert_complete
    ON identity_account;

DROP FUNCTION IF EXISTS identity_page10_retention_receipt_complete();
DROP FUNCTION IF EXISTS identity_page10_retention_receipt_guard();
DROP FUNCTION IF EXISTS identity_page10_retention_hold_complete();
DROP FUNCTION IF EXISTS identity_page10_retention_hold_guard();
DROP FUNCTION IF EXISTS identity_page10_retention_policy_control_guard();
DROP FUNCTION IF EXISTS identity_page10_invitation_origin_complete();
DROP FUNCTION IF EXISTS identity_page10_retention_account_is_unrelated(uuid, uuid);

CREATE OR REPLACE FUNCTION identity_page10_token_digest_key_guard()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
    IF NEW.purpose <> 'account_invitation' THEN
        IF NEW.token_digest_key_id <> '' THEN
            RAISE EXCEPTION 'non-invitation challenge has an invitation digest key'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'UPDATE'
       AND NEW.token_digest_key_id IS DISTINCT FROM OLD.token_digest_key_id THEN
        RAISE EXCEPTION 'invitation challenge digest-key lineage is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.token_digest_key_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$' THEN
        RETURN NEW;
    END IF;
    IF TG_OP = 'INSERT'
       OR (NEW.consumed_at IS NULL AND NEW.invalidated_at IS NULL) THEN
        RAISE EXCEPTION 'active invitation challenge lacks a versioned digest key'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION identity_page10_challenge_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    invitation_record record;
    account_email text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.purpose = 'account_invitation' THEN
            RAISE EXCEPTION 'invitation challenges require controlled retention'
                USING ERRCODE = '23514';
        END IF;
        RETURN OLD;
    END IF;
    IF NEW.purpose <> 'account_invitation' THEN
        RETURN NEW;
    END IF;
    SELECT account_id, aggregate_version INTO invitation_record
      FROM identity_platformaccountinvitation WHERE id = NEW.invitation_id;
    SELECT email INTO account_email FROM identity_account WHERE id = NEW.account_id;
    IF invitation_record.account_id IS DISTINCT FROM NEW.account_id
       OR NEW.invitation_version > invitation_record.aggregate_version
       OR lower(NEW.email_snapshot) IS DISTINCT FROM lower(account_email) THEN
        RAISE EXCEPTION 'invitation challenge lineage is inconsistent'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' AND (
        NEW.id IS DISTINCT FROM OLD.id
        OR NEW.account_id IS DISTINCT FROM OLD.account_id
        OR NEW.purpose IS DISTINCT FROM OLD.purpose
        OR NEW.token_digest IS DISTINCT FROM OLD.token_digest
        OR NEW.email_snapshot IS DISTINCT FROM OLD.email_snapshot
        OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
        OR NEW.invitation_id IS DISTINCT FROM OLD.invitation_id
        OR NEW.invitation_version IS DISTINCT FROM OLD.invitation_version
        OR NEW.created_at IS DISTINCT FROM OLD.created_at
        OR (
            OLD.consumed_at IS NOT NULL
            AND NEW.consumed_at IS DISTINCT FROM OLD.consumed_at
        )
        OR (
            OLD.invalidated_at IS NOT NULL AND (
                NEW.invalidated_at IS DISTINCT FROM OLD.invalidated_at
                OR NEW.invalidation_reason IS DISTINCT FROM
                    OLD.invalidation_reason
            )
        )
    ) THEN
        RAISE EXCEPTION 'invitation challenge lineage is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION identity_page10_hardened_challenge_guard()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    invitation_record record;
    account_email text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.purpose = 'account_invitation' THEN
            RAISE EXCEPTION 'invitation challenge origin is permanently protected'
                USING ERRCODE = '23514';
        END IF;
        RETURN OLD;
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.purpose = 'account_invitation' AND (
        NEW.id IS DISTINCT FROM OLD.id
        OR NEW.account_id IS DISTINCT FROM OLD.account_id
        OR NEW.purpose IS DISTINCT FROM OLD.purpose
        OR NEW.token_digest IS DISTINCT FROM OLD.token_digest
        OR NEW.token_digest_key_id IS DISTINCT FROM OLD.token_digest_key_id
        OR NEW.email_snapshot IS DISTINCT FROM OLD.email_snapshot
        OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
        OR NEW.invitation_id IS DISTINCT FROM OLD.invitation_id
        OR NEW.invitation_version IS DISTINCT FROM OLD.invitation_version
        OR NEW.request_fingerprint IS DISTINCT FROM OLD.request_fingerprint
        OR NEW.created_at IS DISTINCT FROM OLD.created_at
    ) THEN
        RAISE EXCEPTION
            'invitation challenge origin and digest-key lineage is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.purpose <> 'account_invitation' THEN
        RETURN NEW;
    END IF;
    SELECT account_id, aggregate_version INTO invitation_record
      FROM identity_platformaccountinvitation WHERE id = NEW.invitation_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'invitation challenge parent is unavailable'
            USING ERRCODE = '23514';
    END IF;
    SELECT email INTO account_email
      FROM identity_account WHERE id = NEW.account_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'invitation challenge account is unavailable'
            USING ERRCODE = '23514';
    END IF;
    IF invitation_record.account_id IS DISTINCT FROM NEW.account_id
       OR NEW.invitation_version IS NULL
       OR NEW.invitation_version > invitation_record.aggregate_version
       OR lower(NEW.email_snapshot) IS DISTINCT FROM lower(account_email) THEN
        RAISE EXCEPTION 'invitation challenge lineage is inconsistent'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION identity_page10_hardened_challenge_guard() FROM PUBLIC;
"""


class Migration(migrations.Migration):
    dependencies = [  # noqa: RUF012
        ("audit", "0008_identity_retention_audit_uniqueness"),
        ("identity", "0016_account_inventory_prefix_indexes"),
    ]

    operations = [  # noqa: RUF012
        migrations.CreateModel(
            name="PlatformInvitationRetentionPolicyControl",
            fields=[
                (
                    "singleton",
                    models.BooleanField(
                        default=True, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "generation",
                    models.CharField(default="retention-policy-v1", max_length=32),
                ),
                (
                    "policy_id",
                    models.CharField(
                        max_length=120,
                        validators=[
                            django.core.validators.RegexValidator(
                                code="invalid_retention_policy_code",
                                message="Use a stable lowercase retention-policy code.",
                                regex="^[a-z0-9][a-z0-9_.:-]{0,119}$",
                            )
                        ],
                    ),
                ),
                ("policy_version", models.PositiveIntegerField()),
                (
                    "policy_digest",
                    models.CharField(
                        max_length=64,
                        validators=[
                            django.core.validators.RegexValidator(
                                code="invalid_digest",
                                message="Use a lowercase SHA-256 hex digest.",
                                regex="^[0-9a-f]{64}$",
                            )
                        ],
                    ),
                ),
                ("jurisdiction_code", models.CharField(max_length=40)),
                (
                    "policy_approved_by_reference",
                    models.CharField(
                        max_length=120,
                        validators=[
                            django.core.validators.RegexValidator(
                                code="invalid_retention_policy_code",
                                message="Use a stable lowercase retention-policy code.",
                                regex="^[a-z0-9][a-z0-9_.:-]{0,119}$",
                            )
                        ],
                    ),
                ),
                ("policy_approved_at", models.DateTimeField()),
                ("trigger", models.CharField(max_length=32)),
                ("retention_period_days", models.PositiveIntegerField()),
                ("action", models.CharField(max_length=48)),
                ("activated_at", models.DateTimeField()),
            ],
        ),
        migrations.AddConstraint(
            model_name="platforminvitationretentionpolicycontrol",
            constraint=models.CheckConstraint(
                condition=models.Q(("singleton", True)),
                name="identity_inv_ret_policy_singleton",
            ),
        ),
        migrations.AddConstraint(
            model_name="platforminvitationretentionpolicycontrol",
            constraint=models.CheckConstraint(
                condition=models.Q(("policy_version__gt", 0)),
                name="identity_inv_ret_control_ver_pos",
            ),
        ),
        migrations.AddConstraint(
            model_name="platforminvitationretentionpolicycontrol",
            constraint=models.CheckConstraint(
                condition=models.Q(("retention_period_days__lte", 36500)),
                name="identity_inv_ret_control_period",
            ),
        ),
        migrations.AddConstraint(
            model_name="platforminvitationretentionpolicycontrol",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        ("action", "anonymize_abandoned_invitation_contact"),
                        ("generation", "retention-policy-v1"),
                        ("jurisdiction_code__regex", "^[A-Z0-9][A-Z0-9_.:-]{0,39}$"),
                        (
                            "policy_approved_by_reference__regex",
                            "^[a-z0-9][a-z0-9_.:-]{0,119}$",
                        ),
                        ("policy_digest__regex", "^[0-9a-f]{64}$"),
                        ("policy_id__regex", "^[a-z0-9][a-z0-9_.:-]{0,119}$"),
                        ("trigger", "terminal_transition"),
                    )
                    & models.Q(("policy_approved_at__lte", models.F("activated_at")))
                ),
                name="identity_inv_ret_control_contract",
            ),
        ),
        migrations.CreateModel(
            name="PlatformInvitationRetentionHold",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "reference_code",
                    models.CharField(
                        max_length=120,
                        validators=[
                            django.core.validators.RegexValidator(
                                code="invalid_retention_policy_code",
                                message="Use a stable lowercase retention-policy code.",
                                regex="^[a-z0-9][a-z0-9_.:-]{0,119}$",
                            )
                        ],
                    ),
                ),
                (
                    "reason_code",
                    models.CharField(
                        max_length=120,
                        validators=[
                            django.core.validators.RegexValidator(
                                code="invalid_retention_policy_code",
                                message="Use a stable lowercase retention-policy code.",
                                regex="^[a-z0-9][a-z0-9_.:-]{0,119}$",
                            )
                        ],
                    ),
                ),
                ("placed_at", models.DateTimeField()),
                ("place_correlation_id", models.UUIDField()),
                ("active", models.BooleanField(default=True)),
                ("released_at", models.DateTimeField(blank=True, null=True)),
                (
                    "release_reason_code",
                    models.CharField(
                        blank=True,
                        max_length=120,
                        validators=[
                            django.core.validators.RegexValidator(
                                code="invalid_retention_policy_code",
                                message="Use a stable lowercase retention-policy code.",
                                regex="^[a-z0-9][a-z0-9_.:-]{0,119}$",
                            )
                        ],
                    ),
                ),
                ("release_correlation_id", models.UUIDField(blank=True, null=True)),
            ],
            options={
                "ordering": ("invitation_id", "placed_at", "id"),
            },
        ),
        migrations.CreateModel(
            name="PlatformInvitationRetentionReceipt",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "policy_id",
                    models.CharField(
                        max_length=120,
                        validators=[
                            django.core.validators.RegexValidator(
                                code="invalid_retention_policy_code",
                                message="Use a stable lowercase retention-policy code.",
                                regex="^[a-z0-9][a-z0-9_.:-]{0,119}$",
                            )
                        ],
                    ),
                ),
                ("policy_version", models.PositiveIntegerField()),
                (
                    "policy_digest",
                    models.CharField(
                        max_length=64,
                        validators=[
                            django.core.validators.RegexValidator(
                                code="invalid_digest",
                                message="Use a lowercase SHA-256 hex digest.",
                                regex="^[0-9a-f]{64}$",
                            )
                        ],
                    ),
                ),
                ("jurisdiction_code", models.CharField(max_length=40)),
                (
                    "policy_approved_by_reference",
                    models.CharField(
                        max_length=120,
                        validators=[
                            django.core.validators.RegexValidator(
                                code="invalid_retention_policy_code",
                                message="Use a stable lowercase retention-policy code.",
                                regex="^[a-z0-9][a-z0-9_.:-]{0,119}$",
                            )
                        ],
                    ),
                ),
                ("policy_approved_at", models.DateTimeField()),
                (
                    "trigger",
                    models.CharField(
                        choices=[("terminal_transition", "Terminal transition")],
                        max_length=32,
                    ),
                ),
                ("retention_period_days", models.PositiveIntegerField()),
                ("terminal_version", models.PositiveBigIntegerField()),
                ("trigger_at", models.DateTimeField()),
                ("due_at", models.DateTimeField()),
                (
                    "action",
                    models.CharField(
                        choices=[
                            (
                                "anonymize_abandoned_invitation_contact",
                                "Anonymize abandoned invitation contact",
                            )
                        ],
                        max_length=48,
                    ),
                ),
                ("applied_at", models.DateTimeField()),
                ("correlation_id", models.UUIDField()),
                (
                    "source_channel",
                    models.CharField(
                        max_length=40,
                        validators=[
                            django.core.validators.RegexValidator(
                                code="invalid_invitation_source_channel",
                                message="Use a stable lowercase source-channel code.",
                                regex="^[a-z][a-z0-9_-]{0,39}$",
                            )
                        ],
                    ),
                ),
                (
                    "safe_result_code",
                    models.CharField(
                        max_length=120,
                        validators=[
                            django.core.validators.RegexValidator(
                                code="invalid_retention_policy_code",
                                message="Use a stable lowercase retention-policy code.",
                                regex="^[a-z0-9][a-z0-9_.:-]{0,119}$",
                            )
                        ],
                    ),
                ),
            ],
            options={
                "ordering": ("applied_at", "id"),
            },
        ),
        migrations.RemoveConstraint(
            model_name="platforminvitationschedulerrun",
            name="identity_inv_scheduler_kind_evidence",
        ),
        migrations.AddField(
            model_name="account",
            name="invitation_provisioning_origin",
            field=models.OneToOneField(
                blank=True,
                editable=False,
                help_text=(
                    "Exact platform invitation that originally reserved this "
                    "identity; blank for accounts created through another "
                    "approved identity flow."
                ),
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="provisioned_account",
                to="identity.platformaccountinvitation",
            ),
        ),
        migrations.AddIndex(
            model_name="platformaccountinvitation",
            index=models.Index(
                fields=["status", "last_transition_at", "id"],
                name="id_inv_retention_due_idx",
            ),
        ),
        migrations.AddField(
            model_name="platforminvitationschedulerrun",
            name="policy_digest",
            field=models.CharField(
                blank=True,
                max_length=64,
                validators=[
                    django.core.validators.RegexValidator(
                        code="invalid_digest",
                        message="Use a lowercase SHA-256 hex digest.",
                        regex="^[0-9a-f]{64}$",
                    )
                ],
            ),
        ),
        migrations.AlterField(
            model_name="platforminvitationschedulerrun",
            name="generation",
            field=models.CharField(
                choices=[
                    ("delivery-v1", "Delivery worker v1"),
                    ("expiry-v1", "Expiry scheduler v1"),
                    ("retention-v1", "Retention scheduler v1"),
                ],
                max_length=24,
            ),
        ),
        migrations.AlterField(
            model_name="platforminvitationschedulerrun",
            name="kind",
            field=models.CharField(
                choices=[
                    ("delivery", "Invitation delivery"),
                    ("expiry", "Invitation expiry"),
                    ("retention", "Invitation retention"),
                ],
                max_length=16,
            ),
        ),
        migrations.AddConstraint(
            model_name="platforminvitationschedulerrun",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("generation", "delivery-v1"),
                        ("kind", "delivery"),
                        ("policy_digest", ""),
                        ("private_key_coverage_complete", True),
                    ),
                    models.Q(
                        ("generation", "expiry-v1"),
                        ("kind", "expiry"),
                        ("policy_digest", ""),
                        ("private_key_coverage_complete", False),
                    ),
                    models.Q(
                        ("generation", "retention-v1"),
                        ("kind", "retention"),
                        ("private_key_coverage_complete", False),
                        ("policy_digest__regex", "^[0-9a-f]{64}$"),
                    ),
                    _connector="OR",
                ),
                name="identity_inv_scheduler_kind_evidence",
            ),
        ),
        migrations.AddField(
            model_name="platforminvitationretentionhold",
            name="invitation",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="retention_holds",
                to="identity.platformaccountinvitation",
            ),
        ),
        migrations.AddField(
            model_name="platforminvitationretentionhold",
            name="placed_by",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="platform_invitation_retention_holds_placed",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="platforminvitationretentionhold",
            name="released_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="platform_invitation_retention_holds_released",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="platforminvitationretentionreceipt",
            name="inventory_control",
            field=models.ForeignKey(
                default=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="invitation_retention_receipts",
                to="identity.platformaccountinventorycontrol",
            ),
        ),
        migrations.AddField(
            model_name="platforminvitationretentionreceipt",
            name="invitation",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="retention_receipt",
                to="identity.platformaccountinvitation",
            ),
        ),
        migrations.AddConstraint(
            model_name="platforminvitationretentionhold",
            constraint=models.UniqueConstraint(
                condition=models.Q(("active", True)),
                fields=("invitation",),
                name="identity_one_active_inv_ret_hold",
            ),
        ),
        migrations.AddConstraint(
            model_name="platforminvitationretentionhold",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("active", True),
                        ("release_correlation_id__isnull", True),
                        ("release_reason_code", ""),
                        ("released_at__isnull", True),
                        ("released_by__isnull", True),
                    ),
                    models.Q(
                        ("active", False),
                        ("release_correlation_id__isnull", False),
                        ("released_at__isnull", False),
                        ("released_by__isnull", False),
                        models.Q(("release_reason_code", ""), _negated=True),
                    ),
                    _connector="OR",
                ),
                name="identity_inv_ret_hold_release_state",
            ),
        ),
        migrations.AddConstraint(
            model_name="platforminvitationretentionreceipt",
            constraint=models.CheckConstraint(
                condition=models.Q(("policy_version__gt", 0)),
                name="identity_inv_ret_policy_version_pos",
            ),
        ),
        migrations.AddConstraint(
            model_name="platforminvitationretentionreceipt",
            constraint=models.CheckConstraint(
                condition=models.Q(("retention_period_days__lte", 36500)),
                name="identity_inv_ret_period_bound",
            ),
        ),
        migrations.AddConstraint(
            model_name="platforminvitationretentionreceipt",
            constraint=models.CheckConstraint(
                condition=models.Q(("terminal_version__gt", 0)),
                name="identity_inv_ret_terminal_ver_pos",
            ),
        ),
        migrations.AddConstraint(
            model_name="platforminvitationretentionreceipt",
            constraint=models.CheckConstraint(
                condition=models.Q(("due_at__gte", models.F("trigger_at"))),
                name="identity_inv_ret_due_after_trigger",
            ),
        ),
        migrations.AddConstraint(
            model_name="platforminvitationretentionreceipt",
            constraint=models.CheckConstraint(
                condition=models.Q(("applied_at__gte", models.F("due_at"))),
                name="identity_inv_ret_apply_after_due",
            ),
        ),
        migrations.RunPython(
            backfill_invitation_provisioning_origin,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.RunSQL(
            sql=INSTALL_RETENTION_GUARDS,
            reverse_sql=REMOVE_RETENTION_GUARDS,
        ),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_invitation_provenance_downgrade,
        ),
    ]
