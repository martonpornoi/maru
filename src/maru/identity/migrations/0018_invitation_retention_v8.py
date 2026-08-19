"""Close invitation-retention tombstones and add fair bounded progress."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid

import django.core.validators
import django.db.models.deletion
import django.db.models.expressions
from django.db import migrations, models

_PROVIDER_TOMBSTONE_PATTERN = r"^disposed-provider-[0-9a-f]{32}$"


def preflight_retention_v8(apps, schema_editor):  # type: ignore[no-untyped-def]
    """Refuse ambiguous lineage or already-corrupted v7 receipt evidence."""

    del apps
    schema_editor.execute(
        "LOCK TABLE identity_account, identity_identitychallenge, "
        "identity_platformaccountinvitation, "
        "identity_platformidentitydelivery, "
        "identity_platformidentitydeliveryattempt, "
        "identity_platformidentitydeliverylateoutcome, "
        "identity_platforminvitationretentionreceipt "
        "IN SHARE ROW EXCLUSIVE MODE"
    )
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                  FROM identity_platformaccountinvitation
                 GROUP BY account_id
                HAVING count(*) <> 1
            )
            """
        )
        duplicate = cursor.fetchone()
        if duplicate is None or bool(duplicate[0]):
            raise RuntimeError(
                "Cannot install retention v8 while a reserved account has "
                "multiple invitation origins. Reconcile lineage and retry."
            )
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                  FROM identity_platforminvitationretentionreceipt AS receipt
                  JOIN identity_platformaccountinvitation AS invitation
                    ON invitation.id = receipt.invitation_id
                  JOIN identity_account AS account
                    ON account.id = invitation.account_id
                 WHERE invitation.status NOT IN ('revoked', 'expired')
                    OR receipt.terminal_version <> invitation.aggregate_version
                    OR account.invitation_provisioning_origin_id IS DISTINCT FROM
                        invitation.id
                    OR account.email !~
                        '^disposed-[0-9a-f]{32}@account[.]invalid$'
                    OR account.login_handle <> ''
                    OR account.display_name <> ''
                    OR account.account_kind <> 'person'
                    OR account.is_active
                    OR account.is_staff
                    OR account.is_superuser
                    OR account.email_verified_at IS NOT NULL
                    OR account.last_login IS NOT NULL
                    OR left(account.password, 1) <> '!'
                    OR EXISTS (
                        SELECT 1 FROM identity_account_groups AS membership
                         WHERE membership.account_id = account.id
                    )
                    OR EXISTS (
                        SELECT 1
                          FROM identity_account_user_permissions AS membership
                         WHERE membership.account_id = account.id
                    )
                    OR NOT EXISTS (
                        SELECT 1 FROM identity_identitychallenge AS challenge
                         WHERE challenge.invitation_id = invitation.id
                           AND challenge.purpose = 'account_invitation'
                    )
                    OR EXISTS (
                        SELECT 1 FROM identity_identitychallenge AS challenge
                         WHERE challenge.invitation_id = invitation.id
                           AND (
                                challenge.account_id <> account.id
                                OR challenge.purpose <> 'account_invitation'
                                OR challenge.email_snapshot <> account.email
                                OR challenge.token_digest_key_id <> ''
                                OR challenge.token_digest !~ '^[0-9a-f]{64}$'
                                OR challenge.request_fingerprint !~
                                    '^[0-9a-f]{64}$'
                                OR challenge.consumed_at IS NOT NULL
                                OR challenge.invalidated_at IS NULL
                           )
                    )
                    OR NOT EXISTS (
                        SELECT 1
                          FROM identity_platformidentitydelivery AS delivery
                         WHERE delivery.invitation_id = invitation.id
                    )
                    OR EXISTS (
                        SELECT 1
                          FROM identity_platformidentitydelivery AS delivery
                         WHERE delivery.invitation_id = invitation.id
                           AND (
                                delivery.payload_destroyed_at IS NULL
                                OR delivery.status = 'processing'
                                OR delivery.reconciliation_state = 'required'
                           )
                    )
            )
            """
        )
        invalid_receipt = cursor.fetchone()
    if invalid_receipt is None or bool(invalid_receipt[0]):
        raise RuntimeError(
            "Cannot install retention v8 over a receipt whose v7 tombstone is "
            "no longer complete. Restore reviewed state and retry."
        )


def anonymize_existing_provider_references(apps, schema_editor):  # type: ignore[no-untyped-def]
    """Upgrade committed v7 receipts without retaining their raw provider material."""

    receipt_model = apps.get_model("identity", "PlatformInvitationRetentionReceipt")
    delivery_model = apps.get_model("identity", "PlatformIdentityDelivery")
    attempt_model = apps.get_model("identity", "PlatformIdentityDeliveryAttempt")
    late_model = apps.get_model("identity", "PlatformIdentityDeliveryLateOutcome")
    for receipt in receipt_model.objects.order_by("id").iterator(chunk_size=128):
        disposal_key = secrets.token_bytes(32)
        for delivery in (
            delivery_model.objects.filter(invitation_id=receipt.invitation_id)
            .order_by("id")
            .iterator(chunk_size=128)
        ):
            provider_digest = hmac.new(
                disposal_key,
                b"provider-reference:" + delivery.id.bytes,
                hashlib.sha256,
            ).hexdigest()
            tombstone = f"disposed-provider-{provider_digest[:32]}"
            if delivery.provider_reference:
                delivery_model.objects.filter(id=delivery.id).update(
                    provider_reference=tombstone,
                    updated_at=receipt.applied_at,
                )
            attempt_model.objects.filter(delivery_id=delivery.id).exclude(
                provider_reference=""
            ).update(
                provider_reference=tombstone,
                updated_at=receipt.applied_at,
            )
            late_model.objects.filter(delivery_id=delivery.id).exclude(
                provider_reference=""
            ).update(
                provider_reference=tombstone,
                updated_at=receipt.applied_at,
            )
    schema_editor.execute(
        """
        WITH evidence AS MATERIALIZED (
            SELECT clock_timestamp() AS evidence_at
        )
        INSERT INTO identity_platforminvitationretentionassessment (
            id, created_at, updated_at, policy_digest, terminal_version,
            assessment_version, safe_result_code, assessed_at, invitation_id
        )
        SELECT gen_random_uuid(), evidence.evidence_at, evidence.evidence_at,
               receipt.policy_digest, receipt.terminal_version, 1,
               'disposed', evidence.evidence_at, receipt.invitation_id
          FROM identity_platforminvitationretentionreceipt AS receipt
         CROSS JOIN evidence
        ON CONFLICT (invitation_id) DO NOTHING
        """
    )


def refuse_retention_v8_downgrade(apps, schema_editor):  # type: ignore[no-untyped-def]
    """Require fix-forward recovery once v8 privacy or cursor evidence exists."""

    del apps
    schema_editor.execute(
        "LOCK TABLE identity_platforminvitationretentionreceipt, "
        "identity_platforminvitationretentionassessment, "
        "identity_platforminvitationschedulerrun IN ACCESS EXCLUSIVE MODE"
    )
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                EXISTS (
                    SELECT 1 FROM identity_platforminvitationretentionreceipt
                )
                OR EXISTS (
                    SELECT 1 FROM identity_platforminvitationretentionassessment
                )
                OR EXISTS (
                    SELECT 1 FROM identity_platforminvitationschedulerrun
                     WHERE generation = 'retention-v2'
                )
            """
        )
        live = cursor.fetchone()
    if live is None or bool(live[0]):
        raise RuntimeError(
            "Cannot remove retention v8 after disposition, assessment, or fair-cursor "
            "evidence exists. Keep compatible code and fix forward, or restore the "
            "complete database to a reviewed pre-v8 point."
        )


INSTALL_V8_GUARDS = r"""
CREATE FUNCTION identity_page10_retained_account_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    receipt_exists boolean;
BEGIN
    SELECT EXISTS (
        SELECT 1
          FROM identity_platforminvitationretentionreceipt AS receipt
          JOIN identity_platformaccountinvitation AS invitation
            ON invitation.id = receipt.invitation_id
         WHERE invitation.account_id = OLD.id
    ) INTO receipt_exists;
    IF receipt_exists IS DISTINCT FROM true THEN
        RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'disposed invitation account is permanently retained'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.email ~ '^disposed-[0-9a-f]{32}@account[.]invalid$'
       AND OLD.login_handle = '' AND OLD.display_name = '' THEN
        IF to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD) THEN
            RAISE EXCEPTION 'disposed invitation account tombstone is immutable'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.email !~ '^disposed-[0-9a-f]{32}@account[.]invalid$'
       OR NEW.login_handle <> '' OR NEW.display_name <> ''
       OR NEW.account_kind <> 'person' OR NEW.is_active
       OR NEW.is_staff OR NEW.is_superuser
       OR NEW.email_verified_at IS NOT NULL OR NEW.last_login IS NOT NULL
       OR left(NEW.password, 1) <> '!'
       OR to_jsonb(NEW) - ARRAY['email', 'login_handle', 'display_name']
            IS DISTINCT FROM
          to_jsonb(OLD) - ARRAY['email', 'login_handle', 'display_name'] THEN
        RAISE EXCEPTION 'invitation account disposition is not receipt-bound'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION identity_page10_retained_challenge_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    receipt_record record;
    target_invitation_id uuid;
BEGIN
    target_invitation_id := CASE WHEN TG_OP = 'INSERT'
        THEN NEW.invitation_id ELSE OLD.invitation_id END;
    IF target_invitation_id IS NULL THEN
        RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    END IF;
    SELECT applied_at INTO receipt_record
      FROM identity_platforminvitationretentionreceipt
     WHERE invitation_id = target_invitation_id;
    IF NOT FOUND THEN
        RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    END IF;
    IF TG_OP IN ('INSERT', 'DELETE') THEN
        RAISE EXCEPTION 'disposed invitation challenge set is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.email_snapshot ~ '^disposed-[0-9a-f]{32}@account[.]invalid$'
       AND OLD.token_digest_key_id = '' THEN
        IF to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD) THEN
            RAISE EXCEPTION 'disposed invitation challenge tombstone is immutable'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.email_snapshot !~ '^disposed-[0-9a-f]{32}@account[.]invalid$'
       OR NEW.token_digest !~ '^[0-9a-f]{64}$'
       OR NEW.token_digest_key_id <> ''
       OR NEW.request_fingerprint !~ '^[0-9a-f]{64}$'
       OR NEW.updated_at IS DISTINCT FROM receipt_record.applied_at
       OR to_jsonb(NEW) - ARRAY[
            'email_snapshot', 'token_digest', 'token_digest_key_id',
            'request_fingerprint', 'updated_at'
          ] IS DISTINCT FROM
          to_jsonb(OLD) - ARRAY[
            'email_snapshot', 'token_digest', 'token_digest_key_id',
            'request_fingerprint', 'updated_at'
          ] THEN
        RAISE EXCEPTION 'invitation challenge disposition is not receipt-bound'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION identity_page10_retained_membership_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM identity_platforminvitationretentionreceipt AS receipt
          JOIN identity_platformaccountinvitation AS invitation
            ON invitation.id = receipt.invitation_id
         WHERE invitation.account_id = NEW.account_id
    ) THEN
        RAISE EXCEPTION 'disposed invitation account cannot receive authority'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION identity_page10_retention_provider_delivery_guard()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    receipt_record record;
BEGIN
    SELECT applied_at INTO receipt_record
      FROM identity_platforminvitationretentionreceipt
     WHERE invitation_id = OLD.invitation_id;
    IF NOT FOUND THEN
        IF NEW.provider_reference ~ '^disposed-provider-[0-9a-f]{32}$' THEN
            RAISE EXCEPTION 'provider tombstone namespace is retention-reserved'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.provider_reference = ''
       OR NEW.provider_reference !~ '^disposed-provider-[0-9a-f]{32}$'
       OR NEW.updated_at IS DISTINCT FROM receipt_record.applied_at
       OR to_jsonb(NEW) - ARRAY['provider_reference', 'updated_at']
            IS DISTINCT FROM
          to_jsonb(OLD) - ARRAY['provider_reference', 'updated_at'] THEN
        RAISE EXCEPTION 'provider reference disposition is not receipt-bound'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION identity_page10_retention_provider_child_guard()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    receipt_record record;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'identity delivery evidence is append-only'
            USING ERRCODE = '23514';
    END IF;
    SELECT receipt.applied_at INTO receipt_record
      FROM identity_platformidentitydelivery AS delivery
      JOIN identity_platforminvitationretentionreceipt AS receipt
        ON receipt.invitation_id = delivery.invitation_id
     WHERE delivery.id = OLD.delivery_id;
    IF NOT FOUND
       OR OLD.provider_reference = ''
       OR NEW.provider_reference !~ '^disposed-provider-[0-9a-f]{32}$'
       OR NEW.updated_at IS DISTINCT FROM receipt_record.applied_at
       OR to_jsonb(NEW) - ARRAY['provider_reference', 'updated_at']
            IS DISTINCT FROM
          to_jsonb(OLD) - ARRAY['provider_reference', 'updated_at'] THEN
        RAISE EXCEPTION 'provider child reference disposition is not receipt-bound'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION identity_page10_retained_delivery_insert_guard()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    target_invitation_id uuid;
BEGIN
    IF TG_TABLE_NAME = 'identity_platformidentitydelivery' THEN
        target_invitation_id := NEW.invitation_id;
    ELSE
        SELECT invitation_id INTO target_invitation_id
          FROM identity_platformidentitydelivery WHERE id = NEW.delivery_id;
    END IF;
    IF EXISTS (
        SELECT 1 FROM identity_platforminvitationretentionreceipt
         WHERE invitation_id = target_invitation_id
    ) THEN
        RAISE EXCEPTION 'disposed invitation delivery set is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION identity_page10_retention_assessment_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    invitation_record record;
BEGIN
    IF public.maru_authority_provenance_test_reset_allowed()
       AND TG_OP IN ('DELETE', 'TRUNCATE') THEN
        RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NULL END;
    END IF;
    IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
        RAISE EXCEPTION 'retention assessment evidence is protected'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.safe_result_code = 'disposed' THEN
        RAISE EXCEPTION 'disposed retention assessment is terminal and immutable'
            USING ERRCODE = '23514';
    END IF;
    SELECT status, aggregate_version INTO invitation_record
      FROM identity_platformaccountinvitation WHERE id = NEW.invitation_id;
    IF NOT FOUND OR invitation_record.status NOT IN ('revoked', 'expired')
       OR NEW.terminal_version IS DISTINCT FROM invitation_record.aggregate_version
       OR NEW.policy_digest !~ '^[0-9a-f]{64}$'
       OR NEW.safe_result_code <> ALL (ARRAY[
            'disposed', 'not_due', 'active_hold', 'account_state',
            'security_history', 'challenge_relationship',
            'account_relationship', 'additional_invitation',
            'active_challenge', 'challenge_state', 'delivery_unresolved'
       ])
       OR NEW.assessed_at > clock_timestamp()
       OR NEW.created_at > clock_timestamp()
       OR NEW.updated_at > clock_timestamp()
       OR NEW.updated_at < NEW.created_at
       OR NEW.assessed_at > NEW.updated_at
       OR (
            NEW.safe_result_code = 'disposed'
            AND NOT EXISTS (
                SELECT 1
                  FROM identity_platforminvitationretentionreceipt AS receipt
                 WHERE receipt.invitation_id = NEW.invitation_id
                   AND receipt.policy_digest = NEW.policy_digest
                   AND receipt.terminal_version = NEW.terminal_version
            )
       )
       OR (
            NEW.safe_result_code <> 'disposed'
            AND (
                NOT EXISTS (
                    SELECT 1
                      FROM identity_platforminvitationretentionpolicycontrol
                     WHERE singleton = true
                       AND policy_digest = NEW.policy_digest
                )
                OR EXISTS (
                    SELECT 1
                      FROM identity_platforminvitationretentionreceipt AS receipt
                     WHERE receipt.invitation_id = NEW.invitation_id
                )
            )
       ) THEN
        RAISE EXCEPTION 'retention assessment evidence is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.assessment_version <> 1
           OR NEW.created_at IS DISTINCT FROM NEW.updated_at
           OR NEW.assessed_at > NEW.created_at THEN
            RAISE EXCEPTION 'retention assessment must begin at version one'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.invitation_id IS DISTINCT FROM OLD.invitation_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.assessment_version IS DISTINCT FROM OLD.assessment_version + 1
       OR NEW.assessed_at < OLD.assessed_at
       OR NEW.updated_at <= OLD.updated_at THEN
        RAISE EXCEPTION 'retention assessment progression is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION identity_page10_retention_strict_time_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
    IF TG_TABLE_NAME = 'identity_platforminvitationretentionpolicycontrol' THEN
        IF NEW.policy_approved_at > clock_timestamp()
           OR NEW.activated_at > clock_timestamp() THEN
            RAISE EXCEPTION 'retention policy activation time is in the future'
                USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'identity_platforminvitationretentionhold' THEN
        IF NEW.placed_at > clock_timestamp()
           OR NEW.created_at > clock_timestamp()
           OR NEW.updated_at > clock_timestamp()
           OR NEW.updated_at < NEW.created_at
           OR (TG_OP = 'INSERT' AND
               NEW.created_at IS DISTINCT FROM NEW.updated_at)
           OR (TG_OP = 'UPDATE' AND NEW.updated_at <= OLD.updated_at)
           OR (NOT NEW.active AND (
               NEW.released_at > clock_timestamp()
               OR NEW.released_at > NEW.updated_at
           )) THEN
            RAISE EXCEPTION 'retention hold time is in the future'
                USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'identity_platforminvitationschedulerrun' THEN
        IF NEW.ran_at > clock_timestamp()
           OR NEW.created_at > clock_timestamp()
           OR NEW.updated_at > clock_timestamp()
           OR NEW.updated_at < NEW.created_at
           OR NEW.ran_at > NEW.updated_at
           OR (
                NEW.generation = 'retention-v2'
                AND NEW.retention_cursor_transition_at IS NOT NULL
                AND (
                    NEW.retention_cursor_transition_at > NEW.ran_at
                    OR NOT EXISTS (
                        SELECT 1
                          FROM identity_platformaccountinvitation AS invitation
                         WHERE invitation.id = NEW.retention_cursor_invitation_id
                           AND invitation.last_transition_at =
                               NEW.retention_cursor_transition_at
                           AND invitation.status IN ('revoked', 'expired')
                    )
                )
           ) THEN
            RAISE EXCEPTION 'scheduler heartbeat time or cursor is invalid'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.applied_at > clock_timestamp()
       OR NEW.created_at > clock_timestamp()
       OR NEW.updated_at > clock_timestamp()
       OR NEW.created_at IS DISTINCT FROM NEW.updated_at
       OR NEW.applied_at > NEW.created_at
       OR NEW.source_channel NOT IN ('operator', 'scheduler') THEN
        RAISE EXCEPTION 'retention receipt time or source is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION identity_page10_retention_v8_hold_source_complete()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    source_count bigint;
BEGIN
    SELECT count(*) INTO source_count
      FROM audit_auditevent AS event
     WHERE event.operation = CASE WHEN NEW.active
            THEN 'identity.account_invitation.retention_hold.place'
            ELSE 'identity.account_invitation.retention_hold.release' END
       AND event.target_type = 'identity.platform_invitation_retention_hold'
       AND event.target_id = NEW.id
       AND event.correlation_id = CASE WHEN NEW.active
            THEN NEW.place_correlation_id ELSE NEW.release_correlation_id END
       AND event.occurred_at = CASE WHEN NEW.active
            THEN NEW.placed_at ELSE NEW.released_at END
       AND event.source_channel IN ('operator', 'scheduler');
    IF source_count <> 1 THEN
        RAISE EXCEPTION 'retention hold source evidence is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION identity_page10_retention_v8_receipt_complete()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    account_record record;
    audit_count bigint;
BEGIN
    SELECT account.* INTO account_record
      FROM identity_account AS account
      JOIN identity_platformaccountinvitation AS invitation
        ON invitation.account_id = account.id
     WHERE invitation.id = NEW.invitation_id;
    SELECT count(*) INTO audit_count
      FROM audit_auditevent AS event
     WHERE event.operation = 'identity.account_invitation.retention_apply'
       AND event.target_type = 'identity.platform_account_invitation'
       AND event.target_id = NEW.invitation_id
       AND event.principal_kind = 'system'
       AND event.principal_id IS NULL
       AND event.correlation_id = NEW.correlation_id
       AND event.occurred_at = NEW.applied_at
       AND event.capability_code = 'identity.manage_account_invitations'
       AND event.outcome = 'allow'
       AND event.source_channel = NEW.source_channel
       AND event.source_channel IN ('operator', 'scheduler')
       AND event.safe_metadata ->> 'policy_digest' = NEW.policy_digest;
    IF account_record.email !~ '^disposed-[0-9a-f]{32}@account[.]invalid$'
       OR account_record.login_handle <> '' OR account_record.display_name <> ''
       OR account_record.account_kind <> 'person' OR account_record.is_active
       OR account_record.is_staff OR account_record.is_superuser
       OR account_record.email_verified_at IS NOT NULL
       OR account_record.last_login IS NOT NULL
       OR left(account_record.password, 1) <> '!'
       OR audit_count <> 1
       OR NOT EXISTS (
            SELECT 1
              FROM identity_platforminvitationretentionassessment AS assessment
             WHERE assessment.invitation_id = NEW.invitation_id
               AND assessment.policy_digest = NEW.policy_digest
               AND assessment.terminal_version = NEW.terminal_version
               AND assessment.safe_result_code = 'disposed'
       )
       OR EXISTS (
            SELECT 1 FROM identity_platformidentitydelivery AS delivery
             WHERE delivery.invitation_id = NEW.invitation_id
               AND delivery.provider_reference <> ''
               AND delivery.provider_reference !~
                    '^disposed-provider-[0-9a-f]{32}$'
       )
       OR EXISTS (
            SELECT 1
              FROM identity_platformidentitydeliveryattempt AS attempt
              JOIN identity_platformidentitydelivery AS delivery
                ON delivery.id = attempt.delivery_id
             WHERE delivery.invitation_id = NEW.invitation_id
               AND attempt.provider_reference <> ''
               AND attempt.provider_reference !~
                    '^disposed-provider-[0-9a-f]{32}$'
       )
       OR EXISTS (
            SELECT 1
              FROM identity_platformidentitydeliverylateoutcome AS late
              JOIN identity_platformidentitydelivery AS delivery
                ON delivery.id = late.delivery_id
             WHERE delivery.invitation_id = NEW.invitation_id
               AND late.provider_reference <> ''
               AND late.provider_reference !~
                    '^disposed-provider-[0-9a-f]{32}$'
       ) THEN
        RAISE EXCEPTION 'retention v8 receipt is incomplete'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

REVOKE ALL ON FUNCTION identity_page10_retained_account_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION identity_page10_retained_challenge_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION identity_page10_retained_membership_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION identity_page10_retention_provider_delivery_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION identity_page10_retention_provider_child_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION identity_page10_retained_delivery_insert_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION identity_page10_retention_assessment_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION identity_page10_retention_strict_time_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION identity_page10_retention_v8_hold_source_complete() FROM PUBLIC;
REVOKE ALL ON FUNCTION identity_page10_retention_v8_receipt_complete() FROM PUBLIC;

DROP TRIGGER identity_page10_hardened_delivery_write
    ON identity_platformidentitydelivery;
DROP TRIGGER identity_page10_delivery_version
    ON identity_platformidentitydelivery;
CREATE TRIGGER identity_page10_delivery_version
BEFORE UPDATE ON identity_platformidentitydelivery
FOR EACH ROW WHEN (NOT (
    OLD.provider_reference <> ''
    AND NEW.provider_reference ~ '^disposed-provider-[0-9a-f]{32}$'
))
EXECUTE FUNCTION identity_page10_delivery_version_guard();
CREATE TRIGGER identity_page10_hardened_delivery_insert
BEFORE INSERT ON identity_platformidentitydelivery
FOR EACH ROW EXECUTE FUNCTION identity_page10_hardened_delivery_guard();
CREATE TRIGGER identity_page10_hardened_delivery_update
BEFORE UPDATE ON identity_platformidentitydelivery
FOR EACH ROW WHEN (
    OLD.provider_reference IS NOT DISTINCT FROM NEW.provider_reference
    OR NOT (
        OLD.provider_reference <> ''
        AND NEW.provider_reference ~ '^disposed-provider-[0-9a-f]{32}$'
    )
)
EXECUTE FUNCTION identity_page10_hardened_delivery_guard();
CREATE TRIGGER identity_page10_retention_provider_delivery_update
BEFORE UPDATE ON identity_platformidentitydelivery
FOR EACH ROW
EXECUTE FUNCTION identity_page10_retention_provider_delivery_guard();

DROP TRIGGER identity_page10_attempt_immutable
    ON identity_platformidentitydeliveryattempt;
CREATE TRIGGER identity_page10_attempt_immutable
BEFORE UPDATE OR DELETE ON identity_platformidentitydeliveryattempt
FOR EACH ROW EXECUTE FUNCTION identity_page10_retention_provider_child_guard();
DROP TRIGGER identity_page10_late_outcome_immutable
    ON identity_platformidentitydeliverylateoutcome;
CREATE TRIGGER identity_page10_late_outcome_immutable
BEFORE UPDATE OR DELETE ON identity_platformidentitydeliverylateoutcome
FOR EACH ROW EXECUTE FUNCTION identity_page10_retention_provider_child_guard();

CREATE TRIGGER identity_page10_retained_account_write
BEFORE UPDATE OR DELETE ON identity_account
FOR EACH ROW EXECUTE FUNCTION identity_page10_retained_account_guard();
CREATE TRIGGER identity_page10_retained_challenge_write
BEFORE INSERT OR UPDATE OR DELETE ON identity_identitychallenge
FOR EACH ROW EXECUTE FUNCTION identity_page10_retained_challenge_guard();
CREATE TRIGGER identity_page10_retained_group_membership_write
BEFORE INSERT OR UPDATE ON identity_account_groups
FOR EACH ROW EXECUTE FUNCTION identity_page10_retained_membership_guard();
CREATE TRIGGER identity_page10_retained_permission_membership_write
BEFORE INSERT OR UPDATE ON identity_account_user_permissions
FOR EACH ROW EXECUTE FUNCTION identity_page10_retained_membership_guard();
CREATE TRIGGER identity_page10_retained_delivery_insert
BEFORE INSERT ON identity_platformidentitydelivery
FOR EACH ROW EXECUTE FUNCTION identity_page10_retained_delivery_insert_guard();
CREATE TRIGGER identity_page10_retained_attempt_insert
BEFORE INSERT ON identity_platformidentitydeliveryattempt
FOR EACH ROW EXECUTE FUNCTION identity_page10_retained_delivery_insert_guard();
CREATE TRIGGER identity_page10_retained_late_outcome_insert
BEFORE INSERT ON identity_platformidentitydeliverylateoutcome
FOR EACH ROW EXECUTE FUNCTION identity_page10_retained_delivery_insert_guard();
CREATE TRIGGER identity_page10_retention_assessment_write
BEFORE INSERT OR UPDATE OR DELETE
ON identity_platforminvitationretentionassessment
FOR EACH ROW EXECUTE FUNCTION identity_page10_retention_assessment_guard();
CREATE TRIGGER identity_page10_retention_assessment_no_truncate
BEFORE TRUNCATE ON identity_platforminvitationretentionassessment
FOR EACH STATEMENT EXECUTE FUNCTION identity_page10_retention_assessment_guard();
CREATE TRIGGER identity_page10_retention_policy_strict_time
BEFORE INSERT OR UPDATE ON identity_platforminvitationretentionpolicycontrol
FOR EACH ROW EXECUTE FUNCTION identity_page10_retention_strict_time_guard();
CREATE TRIGGER identity_page10_retention_hold_strict_time
BEFORE INSERT OR UPDATE ON identity_platforminvitationretentionhold
FOR EACH ROW EXECUTE FUNCTION identity_page10_retention_strict_time_guard();
CREATE TRIGGER identity_page10_retention_receipt_strict_time
BEFORE INSERT ON identity_platforminvitationretentionreceipt
FOR EACH ROW EXECUTE FUNCTION identity_page10_retention_strict_time_guard();
CREATE TRIGGER identity_page10_scheduler_run_strict_time
BEFORE INSERT ON identity_platforminvitationschedulerrun
FOR EACH ROW EXECUTE FUNCTION identity_page10_retention_strict_time_guard();
CREATE CONSTRAINT TRIGGER identity_page10_retention_v8_hold_source_complete
AFTER INSERT OR UPDATE ON identity_platforminvitationretentionhold
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION identity_page10_retention_v8_hold_source_complete();
CREATE CONSTRAINT TRIGGER identity_page10_retention_v8_receipt_complete
AFTER INSERT ON identity_platforminvitationretentionreceipt
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION identity_page10_retention_v8_receipt_complete();
"""


# During the populated-v7 data migration every non-empty provider value must
# change, including a legitimate historical value that happens to match the
# reserved v8 tombstone shape.  INSTALL_V8_GUARDS therefore permits that exact
# receipt-timed transition while the migration transaction is in flight.  This
# second step terminally closes the transition before 0018 can commit.
FINALIZE_V8_PROVIDER_GUARDS = r"""
CREATE OR REPLACE FUNCTION identity_page10_retention_provider_delivery_guard()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    receipt_record record;
BEGIN
    SELECT applied_at INTO receipt_record
      FROM identity_platforminvitationretentionreceipt
     WHERE invitation_id = OLD.invitation_id;
    IF NOT FOUND THEN
        IF NEW.provider_reference ~ '^disposed-provider-[0-9a-f]{32}$' THEN
            RAISE EXCEPTION 'provider tombstone namespace is retention-reserved'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.provider_reference <> ''
       AND OLD.provider_reference !~ '^disposed-provider-[0-9a-f]{32}$' THEN
        IF NEW.provider_reference !~ '^disposed-provider-[0-9a-f]{32}$'
           OR NEW.updated_at IS DISTINCT FROM receipt_record.applied_at
           OR to_jsonb(NEW) - ARRAY['provider_reference', 'updated_at']
                IS DISTINCT FROM
              to_jsonb(OLD) - ARRAY['provider_reference', 'updated_at'] THEN
            RAISE EXCEPTION 'provider reference disposition is not receipt-bound'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD) THEN
        RAISE EXCEPTION 'disposed invitation delivery evidence is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION identity_page10_retention_provider_child_guard()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    receipt_record record;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'identity delivery evidence is append-only'
            USING ERRCODE = '23514';
    END IF;
    SELECT receipt.applied_at INTO receipt_record
      FROM identity_platformidentitydelivery AS delivery
      JOIN identity_platforminvitationretentionreceipt AS receipt
        ON receipt.invitation_id = delivery.invitation_id
     WHERE delivery.id = OLD.delivery_id;
    IF NOT FOUND
       OR OLD.provider_reference = ''
       OR OLD.provider_reference ~ '^disposed-provider-[0-9a-f]{32}$'
       OR NEW.provider_reference !~ '^disposed-provider-[0-9a-f]{32}$'
       OR NEW.updated_at IS DISTINCT FROM receipt_record.applied_at
       OR to_jsonb(NEW) - ARRAY['provider_reference', 'updated_at']
            IS DISTINCT FROM
          to_jsonb(OLD) - ARRAY['provider_reference', 'updated_at'] THEN
        RAISE EXCEPTION 'provider child reference disposition is not receipt-bound'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION identity_page10_retention_provider_delivery_guard()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION identity_page10_retention_provider_child_guard()
    FROM PUBLIC;

DROP TRIGGER identity_page10_delivery_version
    ON identity_platformidentitydelivery;
CREATE TRIGGER identity_page10_delivery_version
BEFORE UPDATE ON identity_platformidentitydelivery
FOR EACH ROW WHEN (NOT (
    OLD.provider_reference <> ''
    AND OLD.provider_reference !~ '^disposed-provider-[0-9a-f]{32}$'
    AND NEW.provider_reference ~ '^disposed-provider-[0-9a-f]{32}$'
))
EXECUTE FUNCTION identity_page10_delivery_version_guard();
DROP TRIGGER identity_page10_hardened_delivery_update
    ON identity_platformidentitydelivery;
CREATE TRIGGER identity_page10_hardened_delivery_update
BEFORE UPDATE ON identity_platformidentitydelivery
FOR EACH ROW WHEN (
    OLD.provider_reference IS NOT DISTINCT FROM NEW.provider_reference
    OR NOT (
        OLD.provider_reference <> ''
        AND OLD.provider_reference !~ '^disposed-provider-[0-9a-f]{32}$'
        AND NEW.provider_reference ~ '^disposed-provider-[0-9a-f]{32}$'
    )
)
EXECUTE FUNCTION identity_page10_hardened_delivery_guard();
"""


RESTORE_V7_GUARDS = r"""
DROP TRIGGER IF EXISTS identity_page10_scheduler_run_strict_time
    ON identity_platforminvitationschedulerrun;
DROP TRIGGER IF EXISTS identity_page10_retention_v8_receipt_complete
    ON identity_platforminvitationretentionreceipt;
DROP TRIGGER IF EXISTS identity_page10_retention_v8_hold_source_complete
    ON identity_platforminvitationretentionhold;
DROP TRIGGER IF EXISTS identity_page10_retention_receipt_strict_time
    ON identity_platforminvitationretentionreceipt;
DROP TRIGGER IF EXISTS identity_page10_retention_hold_strict_time
    ON identity_platforminvitationretentionhold;
DROP TRIGGER IF EXISTS identity_page10_retention_policy_strict_time
    ON identity_platforminvitationretentionpolicycontrol;
DROP TRIGGER IF EXISTS identity_page10_retention_assessment_no_truncate
    ON identity_platforminvitationretentionassessment;
DROP TRIGGER IF EXISTS identity_page10_retention_assessment_write
    ON identity_platforminvitationretentionassessment;
DROP TRIGGER IF EXISTS identity_page10_retained_late_outcome_insert
    ON identity_platformidentitydeliverylateoutcome;
DROP TRIGGER IF EXISTS identity_page10_retained_attempt_insert
    ON identity_platformidentitydeliveryattempt;
DROP TRIGGER IF EXISTS identity_page10_retained_delivery_insert
    ON identity_platformidentitydelivery;
DROP TRIGGER IF EXISTS identity_page10_retained_permission_membership_write
    ON identity_account_user_permissions;
DROP TRIGGER IF EXISTS identity_page10_retained_group_membership_write
    ON identity_account_groups;
DROP TRIGGER IF EXISTS identity_page10_retained_challenge_write
    ON identity_identitychallenge;
DROP TRIGGER IF EXISTS identity_page10_retained_account_write
    ON identity_account;

DROP TRIGGER IF EXISTS identity_page10_retention_provider_delivery_update
    ON identity_platformidentitydelivery;
DROP TRIGGER IF EXISTS identity_page10_hardened_delivery_update
    ON identity_platformidentitydelivery;
DROP TRIGGER IF EXISTS identity_page10_hardened_delivery_insert
    ON identity_platformidentitydelivery;
DROP TRIGGER IF EXISTS identity_page10_delivery_version
    ON identity_platformidentitydelivery;
CREATE TRIGGER identity_page10_delivery_version
BEFORE UPDATE ON identity_platformidentitydelivery
FOR EACH ROW EXECUTE FUNCTION identity_page10_delivery_version_guard();
CREATE TRIGGER identity_page10_hardened_delivery_write
BEFORE INSERT OR UPDATE ON identity_platformidentitydelivery
FOR EACH ROW EXECUTE FUNCTION identity_page10_hardened_delivery_guard();

DROP TRIGGER IF EXISTS identity_page10_attempt_immutable
    ON identity_platformidentitydeliveryattempt;
CREATE TRIGGER identity_page10_attempt_immutable
BEFORE UPDATE OR DELETE ON identity_platformidentitydeliveryattempt
FOR EACH ROW EXECUTE FUNCTION identity_page10_append_only_guard();
DROP TRIGGER IF EXISTS identity_page10_late_outcome_immutable
    ON identity_platformidentitydeliverylateoutcome;
CREATE TRIGGER identity_page10_late_outcome_immutable
BEFORE UPDATE OR DELETE ON identity_platformidentitydeliverylateoutcome
FOR EACH ROW EXECUTE FUNCTION identity_page10_append_only_guard();

DROP FUNCTION IF EXISTS identity_page10_retention_v8_receipt_complete();
DROP FUNCTION IF EXISTS identity_page10_retention_v8_hold_source_complete();
DROP FUNCTION IF EXISTS identity_page10_retention_strict_time_guard();
DROP FUNCTION IF EXISTS identity_page10_retention_assessment_guard();
DROP FUNCTION IF EXISTS identity_page10_retained_delivery_insert_guard();
DROP FUNCTION IF EXISTS identity_page10_retention_provider_child_guard();
DROP FUNCTION IF EXISTS identity_page10_retention_provider_delivery_guard();
DROP FUNCTION IF EXISTS identity_page10_retained_membership_guard();
DROP FUNCTION IF EXISTS identity_page10_retained_challenge_guard();
DROP FUNCTION IF EXISTS identity_page10_retained_account_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("identity", "0017_invitation_retention_workflow")]  # noqa: RUF012

    operations = [  # noqa: RUF012
        migrations.RunPython(
            preflight_retention_v8,
            migrations.RunPython.noop,
        ),
        migrations.CreateModel(
            name="PlatformInvitationRetentionAssessment",
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
                ("terminal_version", models.PositiveBigIntegerField()),
                (
                    "assessment_version",
                    models.PositiveBigIntegerField(default=1, editable=False),
                ),
                (
                    "safe_result_code",
                    models.CharField(
                        choices=[
                            ("disposed", "Disposed"),
                            ("not_due", "Not due"),
                            ("active_hold", "Active hold"),
                            ("account_state", "Account state blocks disposition"),
                            (
                                "security_history",
                                "Security history blocks disposition",
                            ),
                            (
                                "challenge_relationship",
                                "Another challenge relationship blocks disposition",
                            ),
                            (
                                "account_relationship",
                                "Another account relationship blocks disposition",
                            ),
                            (
                                "additional_invitation",
                                "Another invitation blocks disposition",
                            ),
                            (
                                "active_challenge",
                                "An active challenge blocks disposition",
                            ),
                            (
                                "challenge_state",
                                "Challenge state blocks disposition",
                            ),
                            (
                                "delivery_unresolved",
                                "Delivery state blocks disposition",
                            ),
                        ],
                        max_length=64,
                    ),
                ),
                ("assessed_at", models.DateTimeField()),
            ],
            options={"ordering": ("assessed_at", "id")},
        ),
        migrations.RemoveConstraint(
            model_name="platforminvitationschedulerrun",
            name="identity_inv_scheduler_kind_evidence",
        ),
        migrations.AddField(
            model_name="platforminvitationschedulerrun",
            name="blocked_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="platforminvitationschedulerrun",
            name="held_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="platforminvitationschedulerrun",
            name="inspected_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="platforminvitationschedulerrun",
            name="retention_cursor_invitation_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="platforminvitationschedulerrun",
            name="retention_cursor_transition_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="platforminvitationschedulerrun",
            name="generation",
            field=models.CharField(
                choices=[
                    ("delivery-v1", "Delivery worker v1"),
                    ("expiry-v1", "Expiry scheduler v1"),
                    ("retention-v1", "Retention scheduler v1 (historical)"),
                    ("retention-v2", "Retention scheduler v2"),
                ],
                max_length=24,
            ),
        ),
        migrations.AddConstraint(
            model_name="platformaccountinvitation",
            constraint=models.UniqueConstraint(
                fields=("account",),
                name="identity_one_invitation_per_account",
            ),
        ),
        migrations.AddConstraint(
            model_name="platforminvitationschedulerrun",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("blocked_count", 0),
                        ("generation", "delivery-v1"),
                        ("held_count", 0),
                        ("inspected_count", 0),
                        ("kind", "delivery"),
                        ("policy_digest", ""),
                        ("private_key_coverage_complete", True),
                        ("retention_cursor_invitation_id__isnull", True),
                        ("retention_cursor_transition_at__isnull", True),
                    ),
                    models.Q(
                        ("blocked_count", 0),
                        ("generation", "expiry-v1"),
                        ("held_count", 0),
                        ("inspected_count", 0),
                        ("kind", "expiry"),
                        ("policy_digest", ""),
                        ("private_key_coverage_complete", False),
                        ("retention_cursor_invitation_id__isnull", True),
                        ("retention_cursor_transition_at__isnull", True),
                    ),
                    models.Q(
                        ("blocked_count", 0),
                        ("generation", "retention-v1"),
                        ("held_count", 0),
                        ("inspected_count", 0),
                        ("kind", "retention"),
                        ("private_key_coverage_complete", False),
                        ("retention_cursor_invitation_id__isnull", True),
                        ("retention_cursor_transition_at__isnull", True),
                        ("policy_digest__regex", "^[0-9a-f]{64}$"),
                    ),
                    models.Q(
                        ("blocked_count__lte", models.F("inspected_count")),
                        ("generation", "retention-v2"),
                        ("held_count__lte", models.F("inspected_count")),
                        ("inspected_count__lte", 100),
                        ("kind", "retention"),
                        ("private_key_coverage_complete", False),
                        ("processed_count__lte", models.F("inspected_count")),
                        ("policy_digest__regex", "^[0-9a-f]{64}$"),
                        models.Q(
                            models.Q(
                                ("inspected_count", 0),
                                ("retention_cursor_invitation_id__isnull", True),
                                ("retention_cursor_transition_at__isnull", True),
                            ),
                            models.Q(
                                ("inspected_count__gt", 0),
                                ("retention_cursor_invitation_id__isnull", False),
                                ("retention_cursor_transition_at__isnull", False),
                            ),
                            _connector="OR",
                        ),
                    ),
                    _connector="OR",
                ),
                name="identity_inv_scheduler_kind_evidence",
            ),
        ),
        migrations.AddConstraint(
            model_name="platforminvitationschedulerrun",
            constraint=models.CheckConstraint(
                condition=(
                    ~models.Q(kind="retention")
                    | models.Q(generation="retention-v1")
                    | models.Q(
                        inspected_count__gte=django.db.models.expressions.CombinedExpression(
                            django.db.models.expressions.CombinedExpression(
                                models.F("processed_count"),
                                "+",
                                models.F("blocked_count"),
                            ),
                            "+",
                            models.F("held_count"),
                        )
                    )
                ),
                name="identity_inv_ret_run_count_consistency",
            ),
        ),
        migrations.AddField(
            model_name="platforminvitationretentionassessment",
            name="invitation",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="retention_assessment",
                to="identity.platformaccountinvitation",
            ),
        ),
        migrations.AddIndex(
            model_name="platforminvitationretentionassessment",
            index=models.Index(
                fields=["safe_result_code", "assessed_at", "id"],
                name="id_inv_ret_assess_code_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="platforminvitationretentionassessment",
            constraint=models.CheckConstraint(
                condition=models.Q(terminal_version__gt=0),
                name="identity_inv_ret_assess_terminal_pos",
            ),
        ),
        migrations.AddConstraint(
            model_name="platforminvitationretentionassessment",
            constraint=models.CheckConstraint(
                condition=models.Q(assessment_version__gt=0),
                name="identity_inv_ret_assess_version_pos",
            ),
        ),
        migrations.AddConstraint(
            model_name="platforminvitationretentionassessment",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    safe_result_code__in=(
                        "disposed",
                        "not_due",
                        "active_hold",
                        "account_state",
                        "security_history",
                        "challenge_relationship",
                        "account_relationship",
                        "additional_invitation",
                        "active_challenge",
                        "challenge_state",
                        "delivery_unresolved",
                    )
                ),
                name="identity_inv_ret_assess_result_code",
            ),
        ),
        migrations.RunSQL(
            sql=INSTALL_V8_GUARDS,
            reverse_sql=RESTORE_V7_GUARDS,
        ),
        migrations.RunPython(
            anonymize_existing_provider_references,
            migrations.RunPython.noop,
        ),
        migrations.RunSQL(
            sql=FINALIZE_V8_PROVIDER_GUARDS,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_retention_v8_downgrade,
        ),
    ]
