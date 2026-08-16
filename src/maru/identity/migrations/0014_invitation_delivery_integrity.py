"""Close additive Page 10 invitation and delivery database integrity gaps."""

from __future__ import annotations

from django.db import migrations, models

INSTALL_HARDENED_GUARDS = r"""
CREATE FUNCTION identity_page10_hardened_challenge_guard() RETURNS trigger
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

CREATE FUNCTION identity_page10_hardened_transition_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    invitation_record record;
    actor_record record;
    previous_occurred_at timestamptz;
BEGIN
    SELECT account_id, created_by_id, status, aggregate_version,
           last_transition_at
      INTO invitation_record
      FROM identity_platformaccountinvitation WHERE id = NEW.invitation_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'invitation transition parent is unavailable'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.version IS DISTINCT FROM invitation_record.aggregate_version
       OR NEW.occurred_at IS DISTINCT FROM invitation_record.last_transition_at
       OR NEW.reason IS NULL
       OR btrim(NEW.reason) = ''
       OR NEW.reason IS DISTINCT FROM btrim(NEW.reason)
       OR NEW.source_channel IS NULL
       OR NEW.source_channel !~ '^[a-z][a-z0-9_-]{0,39}$'
       OR NOT (
           (NEW.operation IN ('created', 'reissued')
               AND invitation_record.status = 'pending')
           OR (NEW.operation = 'revoked'
               AND invitation_record.status = 'revoked')
           OR (NEW.operation = 'expired'
               AND invitation_record.status = 'expired')
           OR (NEW.operation = 'accepted'
               AND invitation_record.status = 'accepted')
       ) THEN
        RAISE EXCEPTION 'invitation transition does not match aggregate state'
            USING ERRCODE = '23514';
    END IF;
    IF (NEW.operation = 'created') IS DISTINCT FROM (NEW.version = 1) THEN
        RAISE EXCEPTION 'invitation created transition must be version one'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.version > 1 THEN
        SELECT occurred_at INTO previous_occurred_at
          FROM identity_platformaccountinvitationtransition
         WHERE invitation_id = NEW.invitation_id
           AND version = NEW.version - 1;
        IF NOT FOUND OR NEW.occurred_at <= previous_occurred_at THEN
            RAISE EXCEPTION 'invitation transition chronology is inconsistent'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF NEW.created_at < NEW.occurred_at THEN
        RAISE EXCEPTION 'invitation transition evidence predates its event'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.actor_id IS NULL THEN
        IF NEW.operation <> 'expired' THEN
            RAISE EXCEPTION 'invitation transition actor is required'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    SELECT account_kind, is_active INTO actor_record
      FROM identity_account WHERE id = NEW.actor_id;
    IF NOT FOUND OR actor_record.is_active IS DISTINCT FROM true THEN
        RAISE EXCEPTION 'invitation transition actor is unavailable'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.operation = 'accepted' THEN
        IF NEW.actor_id IS DISTINCT FROM invitation_record.account_id THEN
            RAISE EXCEPTION 'only the invited subject may accept'
                USING ERRCODE = '23514';
        END IF;
    ELSIF actor_record.account_kind IS DISTINCT FROM 'platform_administrator' THEN
        RAISE EXCEPTION 'administrative invitation actor is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION identity_page10_hardened_receipt_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    invitation_record record;
    actor_record record;
    transition_record record;
    expected_transition text;
    inventory_exists boolean;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM identity_platformaccountinventorycontrol
         WHERE singleton = NEW.inventory_control_id
    ) INTO inventory_exists;
    SELECT account_id, created_by_id, aggregate_version
      INTO invitation_record
      FROM identity_platformaccountinvitation WHERE id = NEW.invitation_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'invitation receipt parent is unavailable'
            USING ERRCODE = '23514';
    END IF;
    SELECT account_kind, is_active INTO actor_record
      FROM identity_account WHERE id = NEW.actor_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'invitation receipt actor is unavailable'
            USING ERRCODE = '23514';
    END IF;
    expected_transition := CASE NEW.operation
        WHEN 'create' THEN 'created'
        WHEN 'reissue' THEN 'reissued'
        WHEN 'revoke' THEN 'revoked'
        WHEN 'accept' THEN 'accepted'
        ELSE NULL
    END;
    SELECT operation, actor_id, occurred_at, correlation_id, source_channel
      INTO transition_record
      FROM identity_platformaccountinvitationtransition
     WHERE invitation_id = NEW.invitation_id
       AND version = NEW.result_version;
    IF NOT FOUND
       OR inventory_exists IS DISTINCT FROM true
       OR NEW.inventory_control_id IS DISTINCT FROM true
       OR actor_record.is_active IS DISTINCT FROM true
       OR NEW.result_version IS DISTINCT FROM invitation_record.aggregate_version
       OR expected_transition IS NULL
       OR transition_record.operation IS DISTINCT FROM expected_transition
       OR transition_record.actor_id IS DISTINCT FROM NEW.actor_id
       OR transition_record.correlation_id IS DISTINCT FROM NEW.correlation_id
       OR transition_record.source_channel IS DISTINCT FROM NEW.source_channel
       OR NEW.created_at < transition_record.occurred_at
       OR NEW.request_digest IS NULL
       OR NEW.request_digest !~ '^[0-9a-f]{64}$'
       OR NEW.source_channel IS NULL
       OR NEW.source_channel !~ '^[a-z][a-z0-9_-]{0,39}$' THEN
        RAISE EXCEPTION 'invitation receipt provenance is inconsistent'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.operation = 'create' THEN
        IF NEW.expected_version IS DISTINCT FROM 0
           OR NEW.result_version IS DISTINCT FROM 1
           OR NEW.actor_id IS DISTINCT FROM invitation_record.created_by_id THEN
            RAISE EXCEPTION 'invitation creation receipt is inconsistent'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.expected_version < 1
          OR NEW.result_version IS DISTINCT FROM NEW.expected_version + 1 THEN
        RAISE EXCEPTION 'invitation receipt version is inconsistent'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.operation = 'accept' THEN
        IF NEW.actor_id IS DISTINCT FROM invitation_record.account_id THEN
            RAISE EXCEPTION 'acceptance receipt subject is inconsistent'
                USING ERRCODE = '23514';
        END IF;
    ELSIF actor_record.account_kind IS DISTINCT FROM 'platform_administrator' THEN
        RAISE EXCEPTION 'administrative invitation receipt actor is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION identity_page10_hardened_attempt_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    delivery_record record;
BEGIN
    SELECT * INTO delivery_record
      FROM identity_platformidentitydelivery WHERE id = NEW.delivery_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'identity delivery attempt parent is unavailable'
            USING ERRCODE = '23514';
    END IF;
    IF delivery_record.status IS DISTINCT FROM 'processing'
       OR NEW.attempt_number IS DISTINCT FROM delivery_record.attempt_count
       OR NEW.attempt_number < 1
       OR NEW.attempt_number > delivery_record.max_attempts
       OR NEW.lease_token IS DISTINCT FROM delivery_record.lease_token
       OR NEW.started_at IS DISTINCT FROM delivery_record.claimed_at
       OR NEW.started_at < delivery_record.created_at
       OR NEW.finished_at < NEW.started_at
       OR NEW.provider_reference ~ '[[:cntrl:]]'
       OR (NEW.safe_error_code <> ''
           AND NEW.safe_error_code !~ '^[a-z0-9][a-z0-9_.-]{0,119}$') THEN
        RAISE EXCEPTION 'identity delivery attempt lineage is inconsistent'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.outcome = 'delivered' THEN
        IF NEW.provider_reference = '' OR NEW.safe_error_code <> ''
           OR NEW.next_retry_at IS NOT NULL THEN
            RAISE EXCEPTION 'delivered attempt evidence is inconsistent'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.provider_reference <> '' THEN
        RAISE EXCEPTION 'failed attempt cannot claim a provider reference'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.outcome = 'transient_failure' THEN
        IF NEW.next_retry_at IS NULL OR NEW.next_retry_at <= NEW.finished_at THEN
            RAISE EXCEPTION 'identity delivery retry chronology is inconsistent'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.next_retry_at IS NOT NULL THEN
        RAISE EXCEPTION 'non-retry attempt cannot schedule a retry'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.outcome = 'lease_lost' AND (
        delivery_record.lease_expires_at IS NULL
        OR NEW.finished_at < delivery_record.lease_expires_at
        OR NEW.safe_error_code IS DISTINCT FROM 'delivery_lease_expired'
    ) THEN
        RAISE EXCEPTION 'lost lease attempt evidence is inconsistent'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION identity_page10_hardened_late_outcome_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    delivery_record record;
    attempt_record record;
    expected_classification text;
BEGIN
    SELECT * INTO delivery_record
      FROM identity_platformidentitydelivery WHERE id = NEW.delivery_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'late delivery outcome parent is unavailable'
            USING ERRCODE = '23514';
    END IF;
    SELECT outcome, finished_at INTO attempt_record
      FROM identity_platformidentitydeliveryattempt
     WHERE delivery_id = NEW.delivery_id
       AND attempt_number = NEW.attempt_number
       AND lease_token = NEW.lease_token;
    IF NOT FOUND OR attempt_record.outcome IS DISTINCT FROM 'lease_lost' THEN
        RAISE EXCEPTION 'late delivery outcome lacks lost-lease lineage'
            USING ERRCODE = '23514';
    END IF;
    expected_classification := CASE
        WHEN delivery_record.cancellation_requested_at IS NOT NULL
            THEN 'lifecycle_cancelled'
        ELSE 'lease_superseded'
    END;
    IF NEW.attempt_number > delivery_record.attempt_count
       OR NEW.observed_at < attempt_record.finished_at
       OR NEW.classification IS DISTINCT FROM expected_classification
       OR NEW.provider_reference ~ '[[:cntrl:]]'
       OR (NEW.safe_error_code <> ''
           AND NEW.safe_error_code !~ '^[a-z0-9][a-z0-9_.-]{0,119}$') THEN
        RAISE EXCEPTION 'late delivery outcome lineage is inconsistent'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.outcome = 'delivered' THEN
        IF NEW.provider_reference = '' OR NEW.safe_error_code <> '' THEN
            RAISE EXCEPTION 'late delivered evidence is inconsistent'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.provider_reference <> '' OR NEW.safe_error_code = '' THEN
        RAISE EXCEPTION 'late failed evidence is inconsistent'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION identity_page10_hardened_delivery_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    challenge_record record;
    invitation_record record;
    attempt_record record;
    reconciliation_evidence_exists boolean;
BEGIN
    SELECT purpose, invitation_id, created_at, expires_at,
           consumed_at, invalidated_at
      INTO challenge_record
      FROM identity_identitychallenge WHERE id = NEW.challenge_id;
    IF NOT FOUND
       OR challenge_record.purpose IS DISTINCT FROM 'account_invitation'
       OR challenge_record.invitation_id IS DISTINCT FROM NEW.invitation_id THEN
        RAISE EXCEPTION 'identity delivery challenge lineage is unavailable'
            USING ERRCODE = '23514';
    END IF;
    SELECT status, current_challenge_id, expires_at
      INTO invitation_record
      FROM identity_platformaccountinvitation WHERE id = NEW.invitation_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'identity delivery invitation parent is unavailable'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.safe_error_code <> ''
       AND NEW.safe_error_code !~ '^[a-z0-9][a-z0-9_.-]{0,119}$' THEN
        RAISE EXCEPTION 'identity delivery error code is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.reconciliation_code <> ''
       AND NEW.reconciliation_code !~ '^[a-z0-9][a-z0-9_.-]{0,119}$' THEN
        RAISE EXCEPTION 'identity delivery reconciliation code is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.cancellation_code <> ''
       AND NEW.cancellation_code !~ '^[a-z0-9][a-z0-9_.-]{0,119}$' THEN
        RAISE EXCEPTION 'identity delivery cancellation code is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.provider_reference ~ '[[:cntrl:]]'
       OR (NEW.claimed_at IS NOT NULL AND NEW.claimed_at < NEW.created_at)
       OR (NEW.last_attempt_at IS NOT NULL
           AND NEW.last_attempt_at < NEW.created_at)
       OR (NEW.next_retry_at IS NOT NULL
           AND NEW.last_attempt_at IS NOT NULL
           AND NEW.next_retry_at <= NEW.last_attempt_at)
       OR (NEW.delivered_at IS NOT NULL
           AND NEW.last_attempt_at IS NOT NULL
           AND NEW.delivered_at < NEW.last_attempt_at)
       OR (NEW.reconciliation_required_at IS NOT NULL
           AND NEW.reconciliation_required_at < NEW.created_at)
       OR (NEW.reconciled_at IS NOT NULL
           AND (NEW.reconciliation_required_at IS NULL
                OR NEW.reconciled_at < NEW.reconciliation_required_at))
       OR (NEW.cancellation_requested_at IS NOT NULL
           AND NEW.cancellation_requested_at < NEW.created_at)
       OR (NEW.cancelled_at IS NOT NULL
           AND (NEW.cancellation_requested_at IS NULL
                OR NEW.cancelled_at < NEW.cancellation_requested_at))
       OR (NEW.payload_destroyed_at IS NOT NULL
           AND NEW.payload_destroyed_at < NEW.created_at) THEN
        RAISE EXCEPTION 'identity delivery chronology is inconsistent'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'INSERT' THEN
        IF NEW.aggregate_version IS DISTINCT FROM 1
           OR NEW.status IS DISTINCT FROM 'pending'
           OR NEW.attempt_count IS DISTINCT FROM 0
           OR NEW.max_attempts IS DISTINCT FROM 8
           OR NEW.claimed_at IS NOT NULL
           OR NEW.lease_expires_at IS NOT NULL
           OR NEW.lease_token IS NOT NULL
           OR NEW.last_attempt_at IS NOT NULL
           OR NEW.next_retry_at IS NOT NULL
           OR NEW.delivered_at IS NOT NULL
           OR NEW.provider_reference <> ''
           OR NEW.safe_error_code <> ''
           OR NEW.reconciliation_state IS DISTINCT FROM 'not_required'
           OR NEW.reconciliation_required_at IS NOT NULL
           OR NEW.reconciled_at IS NOT NULL
           OR NEW.reconciliation_code <> ''
           OR NEW.cancellation_requested_at IS NOT NULL
           OR NEW.cancellation_code <> ''
           OR NEW.cancelled_at IS NOT NULL
           OR NEW.payload_destroyed_at IS NOT NULL
           OR NEW.payload_destruction_reason <> '' THEN
            RAISE EXCEPTION 'identity delivery initial state is inconsistent'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.invitation_id IS DISTINCT FROM OLD.invitation_id
       OR NEW.challenge_id IS DISTINCT FROM OLD.challenge_id
       OR NEW.provider_idempotency_key IS DISTINCT FROM OLD.provider_idempotency_key
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'identity delivery lineage is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.max_attempts < OLD.max_attempts
       OR NEW.max_attempts > OLD.max_attempts + 1
       OR NEW.attempt_count < OLD.attempt_count
       OR NEW.attempt_count > OLD.attempt_count + 1 THEN
        RAISE EXCEPTION 'identity delivery attempt progression is inconsistent'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.max_attempts IS DISTINCT FROM OLD.max_attempts AND NOT (
        OLD.status IN ('retrying', 'permanent_failed')
        AND NEW.status = 'retrying'
        AND NEW.reconciliation_state = 'resolved'
        AND NEW.reconciliation_code = 'operator_confirmed_retry'
    ) THEN
        RAISE EXCEPTION
            'identity delivery attempt limit requires retry reconciliation'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.provider_reference IS DISTINCT FROM OLD.provider_reference AND NOT (
        OLD.status = 'processing'
        OR (
            NEW.status = 'delivered'
            AND NEW.reconciliation_state = 'resolved'
            AND NEW.reconciliation_code = 'operator_confirmed_delivered'
        )
    ) THEN
        RAISE EXCEPTION
            'identity delivery provider reference lacks result provenance'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.payload_destroyed_at IS NULL
       AND NEW.payload_destroyed_at IS NOT NULL
       AND NOT (
            (OLD.status = 'processing' AND NEW.status = 'delivered')
            OR (
                NEW.status = 'delivered'
                AND NEW.reconciliation_state = 'resolved'
                AND NEW.reconciliation_code = 'operator_confirmed_delivered'
            )
            OR NEW.cancellation_requested_at IS NOT NULL
       ) THEN
        RAISE EXCEPTION
            'identity delivery payload destruction lacks lifecycle provenance'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.attempt_count = OLD.attempt_count + 1 THEN
        IF OLD.status NOT IN ('pending', 'retrying')
           OR NEW.status IS DISTINCT FROM 'processing'
           OR NEW.claimed_at IS NULL
           OR NEW.last_attempt_at IS DISTINCT FROM NEW.claimed_at
           OR NEW.lease_expires_at IS NULL
           OR NEW.lease_expires_at <= NEW.claimed_at
           OR NEW.lease_token IS NULL
           OR NEW.next_retry_at IS NOT NULL
           OR NEW.safe_error_code <> ''
           OR NEW.reconciliation_state = 'required'
           OR NEW.cancellation_requested_at IS NOT NULL THEN
            RAISE EXCEPTION 'identity delivery claim is inconsistent'
                USING ERRCODE = '23514';
        END IF;
    ELSIF OLD.status <> 'processing' AND NEW.status = 'processing' THEN
        RAISE EXCEPTION 'identity delivery claim did not advance its attempt'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.status IN ('pending', 'retrying') AND NEW.status = 'processing' AND (
        NEW.available_at IS DISTINCT FROM OLD.available_at
        OR NEW.max_attempts IS DISTINCT FROM OLD.max_attempts
        OR NEW.delivered_at IS DISTINCT FROM OLD.delivered_at
        OR NEW.provider_reference IS DISTINCT FROM OLD.provider_reference
        OR NEW.reconciliation_state IS DISTINCT FROM OLD.reconciliation_state
        OR NEW.reconciliation_required_at IS DISTINCT FROM
            OLD.reconciliation_required_at
        OR NEW.reconciled_at IS DISTINCT FROM OLD.reconciled_at
        OR NEW.reconciliation_code IS DISTINCT FROM OLD.reconciliation_code
        OR NEW.cancellation_requested_at IS DISTINCT FROM
            OLD.cancellation_requested_at
        OR NEW.cancellation_code IS DISTINCT FROM OLD.cancellation_code
        OR NEW.cancelled_at IS DISTINCT FROM OLD.cancelled_at
        OR NEW.payload_destroyed_at IS DISTINCT FROM OLD.payload_destroyed_at
        OR NEW.payload_destruction_reason IS DISTINCT FROM
            OLD.payload_destruction_reason
    ) THEN
        RAISE EXCEPTION 'identity delivery claim changed unrelated state'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.status = 'processing' AND NEW.status = 'processing' THEN
        IF NEW.attempt_count IS DISTINCT FROM OLD.attempt_count
           OR NEW.claimed_at IS DISTINCT FROM OLD.claimed_at
           OR NEW.lease_expires_at IS DISTINCT FROM OLD.lease_expires_at
           OR NEW.lease_token IS DISTINCT FROM OLD.lease_token
           OR NEW.last_attempt_at IS DISTINCT FROM OLD.last_attempt_at THEN
            RAISE EXCEPTION 'in-flight identity delivery lease is immutable'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.available_at IS DISTINCT FROM OLD.available_at
           OR NEW.max_attempts IS DISTINCT FROM OLD.max_attempts
           OR NEW.delivered_at IS DISTINCT FROM OLD.delivered_at
           OR NEW.provider_reference IS DISTINCT FROM OLD.provider_reference
           OR NEW.safe_error_code IS DISTINCT FROM OLD.safe_error_code THEN
            RAISE EXCEPTION
                'in-flight identity delivery changed unrelated result state'
                USING ERRCODE = '23514';
        END IF;
    ELSIF OLD.status = 'processing' THEN
        SELECT outcome, started_at, finished_at, provider_reference,
               safe_error_code, next_retry_at
          INTO attempt_record
          FROM identity_platformidentitydeliveryattempt
         WHERE delivery_id = OLD.id
           AND attempt_number = OLD.attempt_count
           AND lease_token = OLD.lease_token;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'identity delivery result lacks leased attempt evidence'
                USING ERRCODE = '23514';
        END IF;
        IF attempt_record.started_at IS DISTINCT FROM OLD.claimed_at THEN
            RAISE EXCEPTION 'identity delivery result lease chronology is inconsistent'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.status = 'delivered' THEN
            IF attempt_record.outcome IS DISTINCT FROM 'delivered'
               OR NEW.delivered_at IS DISTINCT FROM attempt_record.finished_at
               OR NEW.provider_reference IS DISTINCT FROM
                    attempt_record.provider_reference
               OR NEW.safe_error_code <> ''
               OR NEW.next_retry_at IS NOT NULL
               OR NEW.payload_destroyed_at IS DISTINCT FROM
                    attempt_record.finished_at
               OR NEW.payload_destruction_reason IS DISTINCT FROM 'delivered' THEN
                RAISE EXCEPTION
                    'delivered state does not match leased attempt evidence'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.status = 'permanent_failed' THEN
            IF attempt_record.outcome IS DISTINCT FROM 'permanent_failure'
               OR NEW.safe_error_code IS DISTINCT FROM
                    attempt_record.safe_error_code
               OR NEW.next_retry_at IS NOT NULL
               OR NEW.provider_reference IS DISTINCT FROM OLD.provider_reference THEN
                RAISE EXCEPTION
                    'failed state does not match leased attempt evidence'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.status = 'retrying' THEN
            IF NEW.safe_error_code IS DISTINCT FROM attempt_record.safe_error_code
               OR NEW.available_at IS DISTINCT FROM NEW.next_retry_at
               OR (
                    attempt_record.outcome = 'transient_failure'
                    AND NEW.next_retry_at IS DISTINCT FROM
                        attempt_record.next_retry_at
               )
               OR (
                    attempt_record.outcome = 'uncertain'
                    AND (
                        NEW.next_retry_at IS NULL
                        OR NEW.next_retry_at <= attempt_record.finished_at
                        OR NEW.reconciliation_state IS DISTINCT FROM 'required'
                        OR NEW.reconciliation_required_at IS DISTINCT FROM
                            attempt_record.finished_at
                    )
               )
               OR (
                    attempt_record.outcome = 'lease_lost'
                    AND (
                        NEW.next_retry_at IS DISTINCT FROM
                            attempt_record.finished_at
                        OR NEW.available_at IS DISTINCT FROM
                            attempt_record.finished_at
                    )
               )
               OR attempt_record.outcome NOT IN (
                    'transient_failure', 'uncertain', 'lease_lost'
               ) THEN
                RAISE EXCEPTION
                    'retry state does not match leased attempt evidence'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.status = 'cancelled' THEN
            IF NEW.cancellation_requested_at IS NULL
               OR NEW.cancellation_code = ''
               OR NEW.cancelled_at IS DISTINCT FROM attempt_record.finished_at
               OR NEW.safe_error_code IS DISTINCT FROM NEW.cancellation_code
               OR NEW.next_retry_at IS NOT NULL
               OR (
                    attempt_record.outcome = 'delivered'
                    AND NEW.provider_reference IS DISTINCT FROM
                        attempt_record.provider_reference
               )
               OR (
                    attempt_record.outcome <> 'delivered'
                    AND NEW.provider_reference IS DISTINCT FROM
                        OLD.provider_reference
               ) THEN
                RAISE EXCEPTION
                    'cancelled state does not match leased attempt evidence'
                    USING ERRCODE = '23514';
            END IF;
        ELSE
            RAISE EXCEPTION 'leased attempt result state is invalid'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.max_attempts IS DISTINCT FROM OLD.max_attempts THEN
            RAISE EXCEPTION 'leased attempt result changed its attempt limit'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF OLD.status = 'retrying' AND NEW.status = 'retrying'
       AND NOT (
            OLD.reconciliation_state = 'required'
            AND NEW.reconciliation_state = 'resolved'
            AND NEW.reconciliation_code = 'operator_confirmed_retry'
       )
       AND (
            NEW.available_at IS DISTINCT FROM OLD.available_at
            OR NEW.next_retry_at IS DISTINCT FROM OLD.next_retry_at
            OR NEW.safe_error_code IS DISTINCT FROM OLD.safe_error_code
            OR NEW.max_attempts IS DISTINCT FROM OLD.max_attempts
            OR NEW.provider_reference IS DISTINCT FROM OLD.provider_reference
            OR NEW.delivered_at IS DISTINCT FROM OLD.delivered_at
            OR NEW.cancellation_requested_at IS DISTINCT FROM
                OLD.cancellation_requested_at
            OR NEW.cancellation_code IS DISTINCT FROM OLD.cancellation_code
            OR NEW.cancelled_at IS DISTINCT FROM OLD.cancelled_at
            OR NEW.payload_destroyed_at IS DISTINCT FROM OLD.payload_destroyed_at
            OR NEW.payload_destruction_reason IS DISTINCT FROM
                OLD.payload_destruction_reason
       ) THEN
        RAISE EXCEPTION 'retrying delivery changed state without reconciliation'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.status = 'retrying' AND NEW.status = 'permanent_failed' THEN
        SELECT outcome, finished_at INTO attempt_record
          FROM identity_platformidentitydeliveryattempt
         WHERE delivery_id = NEW.id
           AND attempt_number = NEW.attempt_count;
        IF NOT FOUND
           OR attempt_record.outcome IS DISTINCT FROM 'lease_lost'
           OR NEW.next_retry_at IS NOT NULL
           OR NOT (
                (
                    NEW.attempt_count = NEW.max_attempts
                    AND NEW.safe_error_code = 'delivery_attempts_exhausted'
                    AND NEW.reconciliation_state = 'required'
                    AND NEW.reconciliation_required_at IS NOT DISTINCT FROM
                        attempt_record.finished_at
                )
                OR (
                    NEW.safe_error_code = 'invitation_not_deliverable'
                    AND NEW.reconciliation_state IS NOT DISTINCT FROM
                        OLD.reconciliation_state
                    AND NEW.reconciliation_required_at IS NOT DISTINCT FROM
                        OLD.reconciliation_required_at
                    AND NEW.reconciled_at IS NOT DISTINCT FROM OLD.reconciled_at
                    AND NEW.reconciliation_code IS NOT DISTINCT FROM
                        OLD.reconciliation_code
                    AND (
                        invitation_record.status <> 'pending'
                        OR invitation_record.current_challenge_id IS DISTINCT FROM
                            NEW.challenge_id
                        OR invitation_record.expires_at <=
                            attempt_record.finished_at
                        OR challenge_record.expires_at <=
                            attempt_record.finished_at
                        OR challenge_record.consumed_at IS NOT NULL
                        OR challenge_record.invalidated_at IS NOT NULL
                        OR NEW.payload_destroyed_at IS NOT NULL
                    )
                )
           ) THEN
            RAISE EXCEPTION
                'terminal lease result lacks exact attempt evidence'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF NEW.status <> 'processing' AND (
        NEW.claimed_at IS NOT NULL
        OR NEW.lease_expires_at IS NOT NULL
        OR NEW.lease_token IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'non-processing identity delivery retains a lease'
            USING ERRCODE = '23514';
    END IF;
    IF NOT (
        (OLD.status = 'pending' AND NEW.status IN ('processing', 'cancelled'))
        OR (OLD.status = 'retrying'
            AND NEW.status IN (
                'processing', 'retrying', 'delivered',
                'permanent_failed', 'cancelled'
            ))
        OR (OLD.status = 'processing'
            AND NEW.status IN ('processing', 'retrying', 'delivered',
                               'permanent_failed', 'cancelled'))
        OR (OLD.status = 'permanent_failed'
            AND NEW.status IN (
                'permanent_failed', 'retrying', 'delivered', 'cancelled'
            ))
        OR (OLD.status = 'delivered' AND NEW.status = 'delivered')
        OR (OLD.status = 'cancelled' AND NEW.status = 'cancelled')
    ) THEN
        RAISE EXCEPTION 'identity delivery status transition is not allowed'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.payload_destroyed_at IS NOT NULL AND (
        NEW.payload_destroyed_at IS DISTINCT FROM OLD.payload_destroyed_at
        OR NEW.payload_destruction_reason IS DISTINCT FROM
            OLD.payload_destruction_reason
    ) THEN
        RAISE EXCEPTION 'destroyed delivery payload evidence is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.delivered_at IS NOT NULL
       AND NEW.delivered_at IS DISTINCT FROM OLD.delivered_at THEN
        RAISE EXCEPTION 'delivered timestamp is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.cancelled_at IS NOT NULL
       AND NEW.cancelled_at IS DISTINCT FROM OLD.cancelled_at THEN
        RAISE EXCEPTION 'cancelled timestamp is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.provider_reference <> ''
       AND NEW.provider_reference IS DISTINCT FROM OLD.provider_reference THEN
        RAISE EXCEPTION 'provider delivery reference is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.cancellation_requested_at IS NOT NULL AND (
        NEW.cancellation_requested_at IS DISTINCT FROM OLD.cancellation_requested_at
        OR NEW.cancellation_code IS DISTINCT FROM OLD.cancellation_code
    ) THEN
        RAISE EXCEPTION 'identity delivery cancellation evidence is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.cancellation_requested_at IS NULL
       AND NEW.cancellation_requested_at IS NOT NULL THEN
        IF NEW.payload_destroyed_at IS DISTINCT FROM
                NEW.cancellation_requested_at THEN
            RAISE EXCEPTION
                'delivery cancellation must destroy its payload atomically'
                USING ERRCODE = '23514';
        END IF;
        IF OLD.status = 'processing' THEN
            IF NEW.status IS DISTINCT FROM 'processing'
               OR NEW.safe_error_code <> ''
               OR NEW.cancelled_at IS NOT NULL THEN
                RAISE EXCEPTION
                    'in-flight delivery cancellation request is inconsistent'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.status IS DISTINCT FROM 'cancelled'
              OR NEW.cancelled_at IS DISTINCT FROM
                    NEW.cancellation_requested_at
              OR NEW.safe_error_code IS DISTINCT FROM NEW.cancellation_code THEN
            RAISE EXCEPTION
                'queued delivery cancellation result is inconsistent'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF OLD.reconciliation_state = 'resolved' THEN
        IF NEW.reconciliation_state = 'resolved' THEN
            IF NEW.reconciliation_required_at IS DISTINCT FROM
                    OLD.reconciliation_required_at
               OR NEW.reconciled_at IS DISTINCT FROM OLD.reconciled_at
               OR NEW.reconciliation_code IS DISTINCT FROM
                    OLD.reconciliation_code THEN
                RAISE EXCEPTION
                    'resolved reconciliation evidence is immutable'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.reconciliation_state = 'required' THEN
            SELECT EXISTS (
                SELECT 1
                  FROM identity_platformidentitydeliveryattempt
                 WHERE delivery_id = NEW.id
                   AND outcome = 'uncertain'
                   AND finished_at = NEW.reconciliation_required_at
                UNION ALL
                SELECT 1
                  FROM identity_platformidentitydeliverylateoutcome
                 WHERE delivery_id = NEW.id
                   AND outcome = 'delivered'
                   AND observed_at = NEW.reconciliation_required_at
                UNION ALL
                SELECT 1
                  FROM identity_platformidentitydeliveryattempt
                 WHERE delivery_id = NEW.id
                   AND outcome = 'lease_lost'
                   AND finished_at = NEW.reconciliation_required_at
                   AND NEW.status = 'permanent_failed'
                   AND NEW.attempt_count = NEW.max_attempts
            ) INTO reconciliation_evidence_exists;
            IF NEW.reconciliation_required_at IS NULL
               OR OLD.reconciled_at IS NULL
               OR NEW.reconciliation_required_at <= OLD.reconciled_at
               OR NEW.reconciled_at IS NOT NULL
               OR NEW.reconciliation_code <> ''
               OR reconciliation_evidence_exists IS DISTINCT FROM true THEN
                RAISE EXCEPTION
                    'reopening reconciliation requires exact uncertainty evidence'
                    USING ERRCODE = '23514';
            END IF;
        ELSE
            RAISE EXCEPTION 'resolved reconciliation cannot be discarded'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF OLD.status IN ('delivered', 'cancelled') AND (
        NEW.status IS DISTINCT FROM OLD.status
        OR NEW.available_at IS DISTINCT FROM OLD.available_at
        OR NEW.attempt_count IS DISTINCT FROM OLD.attempt_count
        OR NEW.max_attempts IS DISTINCT FROM OLD.max_attempts
        OR NEW.last_attempt_at IS DISTINCT FROM OLD.last_attempt_at
        OR NEW.next_retry_at IS DISTINCT FROM OLD.next_retry_at
        OR NEW.delivered_at IS DISTINCT FROM OLD.delivered_at
        OR NEW.provider_reference IS DISTINCT FROM OLD.provider_reference
        OR NEW.safe_error_code IS DISTINCT FROM OLD.safe_error_code
        OR NEW.cancellation_requested_at IS DISTINCT FROM OLD.cancellation_requested_at
        OR NEW.cancellation_code IS DISTINCT FROM OLD.cancellation_code
        OR NEW.cancelled_at IS DISTINCT FROM OLD.cancelled_at
    ) THEN
        RAISE EXCEPTION 'terminal identity delivery state is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.status = 'permanent_failed' AND NEW.status = 'permanent_failed' AND (
        NEW.available_at IS DISTINCT FROM OLD.available_at
        OR NEW.attempt_count IS DISTINCT FROM OLD.attempt_count
        OR NEW.max_attempts IS DISTINCT FROM OLD.max_attempts
        OR NEW.last_attempt_at IS DISTINCT FROM OLD.last_attempt_at
        OR NEW.next_retry_at IS DISTINCT FROM OLD.next_retry_at
        OR NEW.provider_reference IS DISTINCT FROM OLD.provider_reference
        OR NEW.safe_error_code IS DISTINCT FROM OLD.safe_error_code
        OR NEW.cancellation_requested_at IS DISTINCT FROM OLD.cancellation_requested_at
        OR NEW.cancellation_code IS DISTINCT FROM OLD.cancellation_code
        OR NEW.cancelled_at IS DISTINCT FROM OLD.cancelled_at
    ) THEN
        RAISE EXCEPTION 'failed identity delivery state is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION identity_page10_hardened_reconcile_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    actor_record record;
    delivery_record record;
    inventory_exists boolean;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM identity_platformaccountinventorycontrol
         WHERE singleton = NEW.inventory_control_id
    ) INTO inventory_exists;
    SELECT account_kind, is_active INTO actor_record
      FROM identity_account WHERE id = NEW.actor_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'delivery reconciliation actor is unavailable'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO delivery_record
      FROM identity_platformidentitydelivery WHERE id = NEW.delivery_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'delivery reconciliation parent is unavailable'
            USING ERRCODE = '23514';
    END IF;
    IF inventory_exists IS DISTINCT FROM true
       OR NEW.inventory_control_id IS DISTINCT FROM true
       OR actor_record.is_active IS DISTINCT FROM true
       OR actor_record.account_kind IS DISTINCT FROM 'platform_administrator'
       OR delivery_record.aggregate_version IS DISTINCT FROM NEW.result_version
       OR NEW.expected_version < 1
       OR NEW.result_version IS DISTINCT FROM NEW.expected_version + 1
       OR NEW.request_digest IS NULL
       OR NEW.request_digest !~ '^[0-9a-f]{64}$'
       OR NEW.reason IS NULL
       OR btrim(NEW.reason) = ''
       OR NEW.reason IS DISTINCT FROM btrim(NEW.reason)
       OR NEW.source_channel IS NULL
       OR NEW.source_channel !~ '^[a-z][a-z0-9_-]{0,39}$'
       OR delivery_record.reconciliation_state IS DISTINCT FROM 'resolved'
       OR delivery_record.reconciled_at IS NULL
       THEN
        RAISE EXCEPTION 'identity delivery reconciliation receipt is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.operation = 'resolve_delivered' THEN
        IF delivery_record.status IS DISTINCT FROM 'delivered'
           OR delivery_record.reconciliation_code IS DISTINCT FROM
                'operator_confirmed_delivered'
           OR delivery_record.delivered_at IS NULL
           OR delivery_record.provider_reference = ''
           OR delivery_record.payload_destroyed_at IS NULL
           OR delivery_record.payload_destruction_reason IS DISTINCT FROM
                'delivered' THEN
            RAISE EXCEPTION 'delivered reconciliation result is inconsistent'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.operation = 'resolve_retry' THEN
        IF delivery_record.status IS DISTINCT FROM 'retrying'
           OR delivery_record.reconciliation_code IS DISTINCT FROM
                'operator_confirmed_retry'
           OR delivery_record.payload_destroyed_at IS NOT NULL
           OR delivery_record.safe_error_code IS DISTINCT FROM
                'delivery_reconciliation_retry'
           OR delivery_record.next_retry_at IS DISTINCT FROM
                delivery_record.reconciled_at
           OR delivery_record.available_at IS DISTINCT FROM
                delivery_record.reconciled_at THEN
            RAISE EXCEPTION 'retry reconciliation result is inconsistent'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        RAISE EXCEPTION 'identity delivery reconciliation operation is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION identity_page10_hardened_assert_reconciliation_receipt(
    receipt_uuid uuid
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    receipt_record record;
    audit_count bigint;
BEGIN
    SELECT * INTO receipt_record
      FROM identity_platformidentitydeliveryreconciliationreceipt
     WHERE id = receipt_uuid;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    SELECT count(*) INTO audit_count
      FROM audit_auditevent event
     WHERE event.principal_kind = 'account'
       AND event.principal_id = receipt_record.actor_id
       AND event.principal_context_id IS NULL
       AND event.organization_id IS NULL
       AND event.event_edition_id IS NULL
       AND event.capability_code =
            'identity.reconcile_account_invitation_delivery'
       AND event.operation = 'identity.account_invitation.delivery_reconcile'
       AND event.target_type = 'identity.platform_identity_delivery'
       AND event.target_id = receipt_record.delivery_id
       AND event.outcome = 'allow'
       AND event.reason_code = receipt_record.operation
       AND event.correlation_id = receipt_record.correlation_id
       AND event.source_channel = receipt_record.source_channel
       AND event.obligations = ARRAY['audit']::varchar[]
       AND event.changed_fields =
            ARRAY['delivery', 'reconciliation', 'receipt']::varchar[]
       AND event.safe_metadata = jsonb_build_object(
            'contract_version',
            'page10-invitation-delivery-reconciliation-v1'
       )
       AND event.retention_class = 'identity-restricted'
       AND event.idempotency_key_hash = encode(
            sha256(uuid_send(receipt_record.retry_key)),
            'hex'
       )
       AND event.created_at >= receipt_record.created_at;
    IF audit_count IS DISTINCT FROM 1 THEN
        RAISE EXCEPTION
            'identity delivery reconciliation receipt lacks exact audit evidence'
            USING ERRCODE = '23514';
    END IF;
END;
$$;

CREATE FUNCTION identity_page10_hardened_assert_delivery(delivery_uuid uuid)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    delivery_record record;
    challenge_record record;
    invitation_record record;
    attempt_count bigint;
    minimum_attempt integer;
    maximum_attempt integer;
    latest_started_at timestamptz;
    latest_reconciliation_evidence_at timestamptz;
    cancellation_attempt_finished_at timestamptz;
    lifecycle_transition_exists boolean;
BEGIN
    SELECT * INTO delivery_record
      FROM identity_platformidentitydelivery WHERE id = delivery_uuid;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    SELECT purpose, invitation_id, consumed_at, invalidated_at
      INTO challenge_record
      FROM identity_identitychallenge WHERE id = delivery_record.challenge_id;
    IF NOT FOUND
       OR challenge_record.purpose IS DISTINCT FROM 'account_invitation'
       OR challenge_record.invitation_id IS DISTINCT FROM
            delivery_record.invitation_id THEN
        RAISE EXCEPTION 'identity delivery graph lineage is incomplete'
            USING ERRCODE = '23514';
    END IF;
    SELECT current_challenge_id INTO invitation_record
      FROM identity_platformaccountinvitation
     WHERE id = delivery_record.invitation_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'identity delivery invitation parent is unavailable'
            USING ERRCODE = '23514';
    END IF;
    IF delivery_record.cancellation_requested_at IS NOT NULL THEN
        SELECT finished_at INTO cancellation_attempt_finished_at
          FROM identity_platformidentitydeliveryattempt
         WHERE delivery_id = delivery_uuid
           AND attempt_number = delivery_record.attempt_count
           AND started_at <= delivery_record.cancellation_requested_at
           AND finished_at >= delivery_record.cancellation_requested_at;
        SELECT EXISTS (
            SELECT 1
              FROM identity_platformaccountinvitationtransition transition
             WHERE transition.invitation_id = delivery_record.invitation_id
               AND transition.occurred_at =
                    delivery_record.cancellation_requested_at
               AND transition.operation = (
                   CASE delivery_record.cancellation_code
                    WHEN 'invitation_superseded' THEN 'reissued'
                    WHEN 'invitation_revoked' THEN 'revoked'
                    WHEN 'invitation_consumed' THEN 'accepted'
                    WHEN 'invitation_expired' THEN 'expired'
                    ELSE NULL
                   END
               )
        ) INTO lifecycle_transition_exists;
        IF invitation_record.current_challenge_id IS NOT DISTINCT FROM
                delivery_record.challenge_id
           OR NOT (
                challenge_record.consumed_at IS NOT DISTINCT FROM
                    delivery_record.cancellation_requested_at
                OR challenge_record.invalidated_at IS NOT DISTINCT FROM
                    delivery_record.cancellation_requested_at
           )
           OR lifecycle_transition_exists IS DISTINCT FROM true
           OR delivery_record.payload_destroyed_at IS DISTINCT FROM
                delivery_record.cancellation_requested_at
           OR delivery_record.payload_destruction_reason IS DISTINCT FROM (
                CASE delivery_record.cancellation_code
                    WHEN 'invitation_superseded' THEN 'superseded'
                    WHEN 'invitation_revoked' THEN 'revoked'
                    WHEN 'invitation_consumed' THEN 'superseded'
                    WHEN 'invitation_expired' THEN 'expired'
                    ELSE NULL
                END
           )
           OR (
                delivery_record.status = 'processing'
                AND (
                    delivery_record.safe_error_code <> ''
                    OR delivery_record.cancelled_at IS NOT NULL
                )
           )
           OR (
                delivery_record.status = 'cancelled'
                AND (
                    delivery_record.safe_error_code IS DISTINCT FROM
                        delivery_record.cancellation_code
                    OR delivery_record.cancelled_at IS DISTINCT FROM
                        COALESCE(
                            cancellation_attempt_finished_at,
                            delivery_record.cancellation_requested_at
                        )
                )
           ) THEN
            RAISE EXCEPTION
                'identity delivery cancellation lacks invitation lifecycle evidence'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    SELECT count(*), min(attempt_number), max(attempt_number)
      INTO attempt_count, minimum_attempt, maximum_attempt
      FROM identity_platformidentitydeliveryattempt
     WHERE delivery_id = delivery_uuid;
    IF delivery_record.status = 'processing' THEN
        IF attempt_count IS DISTINCT FROM delivery_record.attempt_count - 1
           OR (attempt_count > 0 AND (
                minimum_attempt IS DISTINCT FROM 1
                OR maximum_attempt IS DISTINCT FROM delivery_record.attempt_count - 1
           )) THEN
            RAISE EXCEPTION 'processing delivery attempt history is incomplete'
                USING ERRCODE = '23514';
        END IF;
    ELSIF attempt_count IS DISTINCT FROM delivery_record.attempt_count
          OR (attempt_count > 0 AND (
               minimum_attempt IS DISTINCT FROM 1
               OR maximum_attempt IS DISTINCT FROM delivery_record.attempt_count
          )) THEN
        RAISE EXCEPTION 'identity delivery attempt history is incomplete'
            USING ERRCODE = '23514';
    END IF;
    IF delivery_record.attempt_count > 0 THEN
        IF delivery_record.status = 'processing' THEN
            latest_started_at := delivery_record.claimed_at;
        ELSE
            SELECT started_at INTO latest_started_at
              FROM identity_platformidentitydeliveryattempt
             WHERE delivery_id = delivery_uuid
               AND attempt_number = delivery_record.attempt_count;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'identity delivery latest attempt is unavailable'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
        IF delivery_record.last_attempt_at IS DISTINCT FROM latest_started_at THEN
            RAISE EXCEPTION 'identity delivery last-attempt timestamp is inconsistent'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF EXISTS (
        SELECT 1
          FROM identity_platformidentitydeliveryattempt later
          JOIN identity_platformidentitydeliveryattempt earlier
            ON earlier.delivery_id = later.delivery_id
           AND earlier.attempt_number = later.attempt_number - 1
         WHERE later.delivery_id = delivery_uuid
           AND later.started_at < earlier.finished_at
    ) THEN
        RAISE EXCEPTION 'identity delivery attempts overlap'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM identity_platformidentitydeliverylateoutcome late
          LEFT JOIN identity_platformidentitydeliveryattempt attempt
            ON attempt.delivery_id = late.delivery_id
           AND attempt.attempt_number = late.attempt_number
           AND attempt.lease_token = late.lease_token
         WHERE late.delivery_id = delivery_uuid
           AND (attempt.id IS NULL
                OR attempt.outcome <> 'lease_lost'
                OR late.observed_at < attempt.finished_at)
    ) THEN
        RAISE EXCEPTION 'late delivery outcome history is inconsistent'
            USING ERRCODE = '23514';
    END IF;
    SELECT max(evidence_at) INTO latest_reconciliation_evidence_at
      FROM (
        SELECT finished_at AS evidence_at
          FROM identity_platformidentitydeliveryattempt
         WHERE delivery_id = delivery_uuid AND outcome = 'uncertain'
        UNION ALL
        SELECT observed_at AS evidence_at
          FROM identity_platformidentitydeliverylateoutcome
         WHERE delivery_id = delivery_uuid AND outcome = 'delivered'
        UNION ALL
        SELECT finished_at AS evidence_at
          FROM identity_platformidentitydeliveryattempt
         WHERE delivery_id = delivery_uuid
           AND outcome = 'lease_lost'
           AND finished_at = delivery_record.reconciliation_required_at
      ) reconciliation_evidence;
    IF delivery_record.cancellation_requested_at IS NOT NULL THEN
        IF delivery_record.reconciliation_state = 'required' THEN
            RAISE EXCEPTION
                'cancelled delivery cannot retain unresolved reconciliation'
                USING ERRCODE = '23514';
        END IF;
    ELSIF delivery_record.reconciliation_state = 'not_required' THEN
        IF latest_reconciliation_evidence_at IS NOT NULL THEN
            RAISE EXCEPTION
                'identity delivery uncertainty lacks reconciliation state'
                USING ERRCODE = '23514';
        END IF;
    ELSIF delivery_record.reconciliation_state = 'required' THEN
        IF delivery_record.reconciliation_required_at IS DISTINCT FROM
                latest_reconciliation_evidence_at THEN
            RAISE EXCEPTION
                'identity delivery reconciliation requirement lacks exact evidence'
                USING ERRCODE = '23514';
        END IF;
    ELSIF latest_reconciliation_evidence_at IS NULL
          OR delivery_record.reconciled_at IS NULL
          OR latest_reconciliation_evidence_at > delivery_record.reconciled_at THEN
        RAISE EXCEPTION
            'resolved delivery reconciliation does not cover its evidence'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT result_version
          FROM identity_platformidentitydeliveryreconciliationreceipt
         WHERE delivery_id = delivery_uuid
         GROUP BY result_version HAVING count(*) <> 1
    ) THEN
        RAISE EXCEPTION 'identity delivery reconciliation versions are ambiguous'
            USING ERRCODE = '23514';
    END IF;
END;
$$;

CREATE FUNCTION identity_page10_hardened_assert_transition(
    invitation_uuid uuid,
    transition_version bigint
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    transition_record record;
    expected_operation text;
    receipt_count bigint;
BEGIN
    SELECT operation, actor_id, correlation_id, source_channel
      INTO transition_record
      FROM identity_platformaccountinvitationtransition
     WHERE invitation_id = invitation_uuid
       AND version = transition_version;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    IF transition_record.operation = 'expired' THEN
        RETURN;
    END IF;
    expected_operation := CASE transition_record.operation
        WHEN 'created' THEN 'create'
        WHEN 'reissued' THEN 'reissue'
        WHEN 'revoked' THEN 'revoke'
        WHEN 'accepted' THEN 'accept'
        ELSE NULL
    END;
    SELECT count(*)
      INTO receipt_count
      FROM identity_platformaccountinvitationcommandreceipt
     WHERE invitation_id = invitation_uuid
       AND result_version = transition_version
       AND operation = expected_operation
       AND actor_id IS NOT DISTINCT FROM transition_record.actor_id
       AND correlation_id IS NOT DISTINCT FROM transition_record.correlation_id
       AND source_channel IS NOT DISTINCT FROM transition_record.source_channel;
    IF expected_operation IS NULL OR receipt_count IS DISTINCT FROM 1 THEN
        RAISE EXCEPTION
            'non-expiry invitation transition lacks exact command receipt'
            USING ERRCODE = '23514';
    END IF;
END;
$$;

CREATE FUNCTION identity_page10_hardened_delivery_complete() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    receipt_exists boolean;
    expected_operation text;
    transition_operation text;
    resolution_changed boolean;
    lifecycle_resolution boolean;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        transition_operation := CASE
            WHEN NEW.max_attempts IS DISTINCT FROM OLD.max_attempts
                THEN 'resolve_retry'
            WHEN OLD.status IN ('retrying', 'permanent_failed')
                 AND NEW.status = 'delivered' THEN 'resolve_delivered'
            WHEN OLD.status = 'permanent_failed'
                 AND NEW.status = 'retrying' THEN 'resolve_retry'
            ELSE NULL
        END;
        expected_operation := CASE NEW.reconciliation_code
            WHEN 'operator_confirmed_delivered' THEN 'resolve_delivered'
            WHEN 'operator_confirmed_retry' THEN 'resolve_retry'
            ELSE NULL
        END;
        resolution_changed := (
            OLD.reconciliation_state IS DISTINCT FROM 'resolved'
            AND NEW.reconciliation_state = 'resolved'
        );
        lifecycle_resolution := (
            resolution_changed
            AND OLD.reconciliation_state = 'required'
            AND NEW.status IN ('processing', 'cancelled')
            AND NEW.cancellation_requested_at IS NOT NULL
            AND NEW.cancellation_code <> ''
            AND NEW.reconciliation_code IS NOT DISTINCT FROM
                NEW.cancellation_code
            AND NEW.reconciled_at IS NOT DISTINCT FROM
                NEW.cancellation_requested_at
            AND NEW.payload_destroyed_at IS NOT NULL
            AND NEW.payload_destruction_reason IN (
                'revoked', 'superseded', 'expired'
            )
        );

        IF resolution_changed
           AND OLD.reconciliation_state IS DISTINCT FROM 'required' THEN
            RAISE EXCEPTION
                'delivery reconciliation cannot resolve absent evidence'
                USING ERRCODE = '23514';
        END IF;

        IF transition_operation IS NOT NULL
           AND OLD.reconciliation_state IS DISTINCT FROM 'required' THEN
            RAISE EXCEPTION
                'operator delivery transition requires unresolved evidence'
                USING ERRCODE = '23514';
        END IF;

        IF transition_operation IS NOT NULL AND (
            NEW.reconciliation_state IS DISTINCT FROM 'resolved'
            OR expected_operation IS DISTINCT FROM transition_operation
        ) THEN
            RAISE EXCEPTION
                'operator delivery transition has inconsistent reconciliation state'
                USING ERRCODE = '23514';
        END IF;

        IF transition_operation IS NOT NULL
           OR (resolution_changed AND lifecycle_resolution IS DISTINCT FROM true)
        THEN
            SELECT EXISTS (
                SELECT 1
                  FROM identity_platformidentitydeliveryreconciliationreceipt
                 WHERE delivery_id = NEW.id
                   AND result_version = NEW.aggregate_version
                   AND operation = expected_operation
            ) INTO receipt_exists;
            IF expected_operation IS NULL
               OR receipt_exists IS DISTINCT FROM true THEN
                RAISE EXCEPTION
                    'operator reconciliation lacks exact receipt evidence'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
    END IF;
    PERFORM identity_page10_hardened_assert_delivery(NEW.id);
    RETURN NULL;
END;
$$;

CREATE FUNCTION identity_page10_hardened_transition_complete() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
    PERFORM identity_page10_hardened_assert_transition(
        NEW.invitation_id,
        NEW.version
    );
    RETURN NULL;
END;
$$;

CREATE FUNCTION identity_page10_hardened_receipt_complete() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
    PERFORM identity_page10_hardened_assert_transition(
        NEW.invitation_id,
        NEW.result_version
    );
    RETURN NULL;
END;
$$;

CREATE FUNCTION identity_page10_hardened_reconcile_audit_complete()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
    PERFORM identity_page10_hardened_assert_reconciliation_receipt(NEW.id);
    RETURN NULL;
END;
$$;

CREATE FUNCTION identity_page10_hardened_delivery_child_complete() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
    PERFORM identity_page10_hardened_assert_delivery(NEW.delivery_id);
    RETURN NULL;
END;
$$;

REVOKE ALL ON FUNCTION identity_page10_hardened_challenge_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION identity_page10_hardened_transition_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION identity_page10_hardened_receipt_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION identity_page10_hardened_attempt_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION identity_page10_hardened_late_outcome_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION identity_page10_hardened_delivery_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION identity_page10_hardened_reconcile_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION
    identity_page10_hardened_assert_reconciliation_receipt(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION identity_page10_hardened_assert_delivery(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION
    identity_page10_hardened_assert_transition(uuid, bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION identity_page10_hardened_delivery_complete() FROM PUBLIC;
REVOKE ALL ON FUNCTION
    identity_page10_hardened_transition_complete() FROM PUBLIC;
REVOKE ALL ON FUNCTION identity_page10_hardened_receipt_complete() FROM PUBLIC;
REVOKE ALL ON FUNCTION
    identity_page10_hardened_reconcile_audit_complete() FROM PUBLIC;
REVOKE ALL ON FUNCTION identity_page10_hardened_delivery_child_complete() FROM PUBLIC;

CREATE TRIGGER identity_page10_hardened_challenge_write
BEFORE INSERT OR UPDATE OR DELETE ON identity_identitychallenge
FOR EACH ROW EXECUTE FUNCTION identity_page10_hardened_challenge_guard();
CREATE TRIGGER identity_page10_hardened_transition_insert
BEFORE INSERT ON identity_platformaccountinvitationtransition
FOR EACH ROW EXECUTE FUNCTION identity_page10_hardened_transition_guard();
CREATE TRIGGER identity_page10_hardened_receipt_insert
BEFORE INSERT ON identity_platformaccountinvitationcommandreceipt
FOR EACH ROW EXECUTE FUNCTION identity_page10_hardened_receipt_guard();
CREATE TRIGGER identity_page10_hardened_attempt_insert
BEFORE INSERT ON identity_platformidentitydeliveryattempt
FOR EACH ROW EXECUTE FUNCTION identity_page10_hardened_attempt_guard();
CREATE TRIGGER identity_page10_hardened_late_outcome_insert
BEFORE INSERT ON identity_platformidentitydeliverylateoutcome
FOR EACH ROW EXECUTE FUNCTION identity_page10_hardened_late_outcome_guard();
CREATE TRIGGER identity_page10_hardened_delivery_write
BEFORE INSERT OR UPDATE ON identity_platformidentitydelivery
FOR EACH ROW EXECUTE FUNCTION identity_page10_hardened_delivery_guard();
CREATE TRIGGER identity_page10_hardened_reconcile_insert
BEFORE INSERT ON identity_platformidentitydeliveryreconciliationreceipt
FOR EACH ROW EXECUTE FUNCTION identity_page10_hardened_reconcile_guard();

CREATE CONSTRAINT TRIGGER identity_page10_hardened_delivery_complete
AFTER INSERT OR UPDATE ON identity_platformidentitydelivery
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION identity_page10_hardened_delivery_complete();
CREATE CONSTRAINT TRIGGER identity_page10_hardened_transition_complete
AFTER INSERT ON identity_platformaccountinvitationtransition
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION identity_page10_hardened_transition_complete();
CREATE CONSTRAINT TRIGGER identity_page10_hardened_receipt_complete
AFTER INSERT ON identity_platformaccountinvitationcommandreceipt
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION identity_page10_hardened_receipt_complete();
CREATE CONSTRAINT TRIGGER identity_page10_hardened_attempt_complete
AFTER INSERT ON identity_platformidentitydeliveryattempt
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION identity_page10_hardened_delivery_child_complete();
CREATE CONSTRAINT TRIGGER identity_page10_hardened_late_complete
AFTER INSERT ON identity_platformidentitydeliverylateoutcome
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION identity_page10_hardened_delivery_child_complete();
CREATE CONSTRAINT TRIGGER identity_page10_hardened_reconcile_complete
AFTER INSERT ON identity_platformidentitydeliveryreconciliationreceipt
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION identity_page10_hardened_delivery_child_complete();
CREATE CONSTRAINT TRIGGER identity_page10_hardened_reconcile_audit_complete
AFTER INSERT ON identity_platformidentitydeliveryreconciliationreceipt
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION
    identity_page10_hardened_reconcile_audit_complete();
"""


REMOVE_HARDENED_GUARDS = r"""
DROP TRIGGER IF EXISTS identity_page10_hardened_reconcile_audit_complete
    ON identity_platformidentitydeliveryreconciliationreceipt;
DROP TRIGGER IF EXISTS identity_page10_hardened_reconcile_complete
    ON identity_platformidentitydeliveryreconciliationreceipt;
DROP TRIGGER IF EXISTS identity_page10_hardened_late_complete
    ON identity_platformidentitydeliverylateoutcome;
DROP TRIGGER IF EXISTS identity_page10_hardened_attempt_complete
    ON identity_platformidentitydeliveryattempt;
DROP TRIGGER IF EXISTS identity_page10_hardened_transition_complete
    ON identity_platformaccountinvitationtransition;
DROP TRIGGER IF EXISTS identity_page10_hardened_receipt_complete
    ON identity_platformaccountinvitationcommandreceipt;
DROP TRIGGER IF EXISTS identity_page10_hardened_delivery_complete
    ON identity_platformidentitydelivery;
DROP TRIGGER IF EXISTS identity_page10_hardened_reconcile_insert
    ON identity_platformidentitydeliveryreconciliationreceipt;
DROP TRIGGER IF EXISTS identity_page10_hardened_delivery_write
    ON identity_platformidentitydelivery;
DROP TRIGGER IF EXISTS identity_page10_hardened_late_outcome_insert
    ON identity_platformidentitydeliverylateoutcome;
DROP TRIGGER IF EXISTS identity_page10_hardened_attempt_insert
    ON identity_platformidentitydeliveryattempt;
DROP TRIGGER IF EXISTS identity_page10_hardened_receipt_insert
    ON identity_platformaccountinvitationcommandreceipt;
DROP TRIGGER IF EXISTS identity_page10_hardened_transition_insert
    ON identity_platformaccountinvitationtransition;
DROP TRIGGER IF EXISTS identity_page10_hardened_challenge_write
    ON identity_identitychallenge;
DROP FUNCTION IF EXISTS identity_page10_hardened_delivery_child_complete();
DROP FUNCTION IF EXISTS identity_page10_hardened_reconcile_audit_complete();
DROP FUNCTION IF EXISTS identity_page10_hardened_transition_complete();
DROP FUNCTION IF EXISTS identity_page10_hardened_receipt_complete();
DROP FUNCTION IF EXISTS identity_page10_hardened_delivery_complete();
DROP FUNCTION IF EXISTS identity_page10_hardened_assert_transition(uuid, bigint);
DROP FUNCTION IF EXISTS identity_page10_hardened_assert_delivery(uuid);
DROP FUNCTION IF EXISTS
    identity_page10_hardened_assert_reconciliation_receipt(uuid);
DROP FUNCTION IF EXISTS identity_page10_hardened_reconcile_guard();
DROP FUNCTION IF EXISTS identity_page10_hardened_delivery_guard();
DROP FUNCTION IF EXISTS identity_page10_hardened_late_outcome_guard();
DROP FUNCTION IF EXISTS identity_page10_hardened_attempt_guard();
DROP FUNCTION IF EXISTS identity_page10_hardened_receipt_guard();
DROP FUNCTION IF EXISTS identity_page10_hardened_transition_guard();
DROP FUNCTION IF EXISTS identity_page10_hardened_challenge_guard();
"""

INSTALL_RECEIPT_UNIQUENESS = r"""
ALTER TABLE identity_platformaccountinvitationcommandreceipt
ADD CONSTRAINT identity_invitation_result_receipt_unique UNIQUE (
    invitation_id,
    result_version
);
ALTER TABLE identity_platformidentitydeliveryreconciliationreceipt
ADD CONSTRAINT identity_reconcile_result_receipt_unique UNIQUE (
    delivery_id,
    result_version
);
"""

REMOVE_RECEIPT_UNIQUENESS = r"""
ALTER TABLE identity_platformidentitydeliveryreconciliationreceipt
DROP CONSTRAINT IF EXISTS identity_reconcile_result_receipt_unique;
ALTER TABLE identity_platformaccountinvitationcommandreceipt
DROP CONSTRAINT IF EXISTS identity_invitation_result_receipt_unique;
"""

EXISTING_HISTORY_CHECKS = (
    (
        "invitation challenge lineage is inconsistent",
        """
        SELECT EXISTS (
            SELECT 1
              FROM identity_identitychallenge challenge
              LEFT JOIN identity_platformaccountinvitation invitation
                ON invitation.id = challenge.invitation_id
              LEFT JOIN identity_account account
                ON account.id = challenge.account_id
             WHERE challenge.purpose = 'account_invitation'
               AND (
                    invitation.id IS NULL
                    OR account.id IS NULL
                    OR invitation.account_id IS DISTINCT FROM challenge.account_id
                    OR challenge.invitation_version IS NULL
                    OR challenge.invitation_version > invitation.aggregate_version
                    OR lower(challenge.email_snapshot) IS DISTINCT FROM
                        lower(account.email)
               )
        )
        """,
    ),
    (
        "invitation transition chronology or provenance is inconsistent",
        """
        SELECT EXISTS (
            SELECT 1
              FROM identity_platformaccountinvitationtransition transition
              JOIN identity_platformaccountinvitation invitation
                ON invitation.id = transition.invitation_id
              LEFT JOIN identity_platformaccountinvitationtransition previous
                ON previous.invitation_id = transition.invitation_id
               AND previous.version = transition.version - 1
              LEFT JOIN identity_account actor ON actor.id = transition.actor_id
             WHERE transition.reason IS NULL
                OR btrim(transition.reason) = ''
                OR transition.reason IS DISTINCT FROM btrim(transition.reason)
                OR transition.source_channel IS NULL
                OR transition.source_channel !~ '^[a-z][a-z0-9_-]{0,39}$'
                OR transition.created_at < transition.occurred_at
                OR (transition.operation = 'created') IS DISTINCT FROM
                    (transition.version = 1)
                OR (
                    transition.version > 1
                    AND (
                        previous.id IS NULL
                        OR transition.occurred_at <= previous.occurred_at
                    )
                )
                OR (
                    transition.operation = 'accepted'
                    AND transition.actor_id IS DISTINCT FROM invitation.account_id
                )
                OR (
                    transition.operation IN ('created', 'reissued', 'revoked')
                    AND (
                        actor.id IS NULL
                        OR actor.account_kind IS DISTINCT FROM
                            'platform_administrator'
                    )
                )
        )
        """,
    ),
    (
        "invitation command receipt result versions are not unique",
        """
        SELECT EXISTS (
            SELECT 1
              FROM identity_platformaccountinvitationcommandreceipt
             GROUP BY invitation_id, result_version
            HAVING count(*) > 1
        )
        """,
    ),
    (
        "invitation command receipt provenance is inconsistent",
        """
        SELECT EXISTS (
            SELECT 1
              FROM identity_platformaccountinvitationcommandreceipt receipt
              JOIN identity_platformaccountinvitation invitation
                ON invitation.id = receipt.invitation_id
              LEFT JOIN identity_platformaccountinvitationtransition transition
                ON transition.invitation_id = receipt.invitation_id
               AND transition.version = receipt.result_version
              LEFT JOIN identity_account actor ON actor.id = receipt.actor_id
             WHERE receipt.inventory_control_id IS DISTINCT FROM true
                OR transition.id IS NULL
                OR receipt.operation IS DISTINCT FROM CASE transition.operation
                    WHEN 'created' THEN 'create'
                    WHEN 'reissued' THEN 'reissue'
                    WHEN 'revoked' THEN 'revoke'
                    WHEN 'accepted' THEN 'accept'
                    ELSE NULL
                END
                OR receipt.actor_id IS DISTINCT FROM transition.actor_id
                OR receipt.correlation_id IS DISTINCT FROM
                    transition.correlation_id
                OR receipt.source_channel IS DISTINCT FROM
                    transition.source_channel
                OR receipt.created_at < transition.occurred_at
                OR receipt.request_digest IS NULL
                OR receipt.request_digest !~ '^[0-9a-f]{64}$'
                OR receipt.source_channel IS NULL
                OR receipt.source_channel !~ '^[a-z][a-z0-9_-]{0,39}$'
                OR (
                    receipt.operation = 'create'
                    AND receipt.actor_id IS DISTINCT FROM invitation.created_by_id
                )
                OR (
                    receipt.operation = 'accept'
                    AND receipt.actor_id IS DISTINCT FROM invitation.account_id
                )
                OR (
                    receipt.operation <> 'accept'
                    AND (
                        actor.id IS NULL
                        OR actor.account_kind IS DISTINCT FROM
                            'platform_administrator'
                    )
                )
        )
        """,
    ),
    (
        "delivery attempt chronology or outcome evidence is inconsistent",
        """
        SELECT EXISTS (
            SELECT 1
              FROM identity_platformidentitydeliveryattempt attempt
              JOIN identity_platformidentitydelivery delivery
                ON delivery.id = attempt.delivery_id
             WHERE attempt.started_at < delivery.created_at
                OR attempt.finished_at < attempt.started_at
                OR attempt.provider_reference ~ '[[:cntrl:]]'
                OR (
                    attempt.safe_error_code <> ''
                    AND attempt.safe_error_code !~
                        '^[a-z0-9][a-z0-9_.-]{0,119}$'
                )
                OR (
                    attempt.outcome = 'delivered'
                    AND (
                        attempt.provider_reference = ''
                        OR attempt.safe_error_code <> ''
                        OR attempt.next_retry_at IS NOT NULL
                    )
                )
                OR (
                    attempt.outcome <> 'delivered'
                    AND attempt.provider_reference <> ''
                )
                OR (
                    attempt.outcome = 'transient_failure'
                    AND (
                        attempt.next_retry_at IS NULL
                        OR attempt.next_retry_at <= attempt.finished_at
                    )
                )
                OR (
                    attempt.outcome <> 'transient_failure'
                    AND attempt.next_retry_at IS NOT NULL
                )
                OR (
                    attempt.outcome = 'lease_lost'
                    AND attempt.safe_error_code IS DISTINCT FROM
                        'delivery_lease_expired'
                )
        )
        """,
    ),
    (
        "unattempted delivery does not use the code-owned attempt limit",
        """
        SELECT EXISTS (
            SELECT 1
              FROM identity_platformidentitydelivery
             WHERE attempt_count = 0 AND max_attempts <> 8
        )
        """,
    ),
    (
        "current delivery result contradicts its latest attempt",
        """
        SELECT EXISTS (
            SELECT 1
              FROM identity_platformidentitydelivery delivery
             LEFT JOIN identity_platformidentitydeliveryattempt attempt
                ON attempt.delivery_id = delivery.id
               AND attempt.attempt_number = delivery.attempt_count
             WHERE (
                delivery.status = 'delivered'
                AND (
                    (
                        attempt.outcome = 'delivered'
                        AND delivery.delivered_at IS NOT DISTINCT FROM
                            attempt.finished_at
                        AND delivery.provider_reference IS NOT DISTINCT FROM
                            attempt.provider_reference
                    )
                    OR EXISTS (
                        SELECT 1
                          FROM identity_platformidentitydeliveryreconciliationreceipt
                               receipt
                         WHERE receipt.delivery_id = delivery.id
                           AND receipt.operation = 'resolve_delivered'
                           AND (
                                receipt.result_version =
                                    delivery.aggregate_version
                                OR EXISTS (
                                    SELECT 1
                                      FROM identity_platformidentitydeliverylateoutcome
                                           late
                                     WHERE late.delivery_id = delivery.id
                                       AND late.created_at >= receipt.created_at
                                )
                           )
                    )
                ) IS DISTINCT FROM true
             ) OR (
                delivery.status = 'retrying'
                AND (
                    (
                        attempt.outcome = 'transient_failure'
                        AND delivery.safe_error_code IS NOT DISTINCT FROM
                            attempt.safe_error_code
                        AND delivery.next_retry_at IS NOT DISTINCT FROM
                            attempt.next_retry_at
                        AND delivery.available_at IS NOT DISTINCT FROM
                            attempt.next_retry_at
                    )
                    OR (
                        attempt.outcome = 'uncertain'
                        AND delivery.safe_error_code IS NOT DISTINCT FROM
                            attempt.safe_error_code
                        AND delivery.reconciliation_required_at IS NOT DISTINCT FROM
                            attempt.finished_at
                        AND delivery.next_retry_at > attempt.finished_at
                        AND delivery.available_at IS NOT DISTINCT FROM
                            delivery.next_retry_at
                    )
                    OR (
                        attempt.outcome = 'lease_lost'
                        AND delivery.safe_error_code = 'delivery_lease_expired'
                        AND delivery.next_retry_at IS NOT DISTINCT FROM
                            attempt.finished_at
                        AND delivery.available_at IS NOT DISTINCT FROM
                            attempt.finished_at
                    )
                    OR EXISTS (
                        SELECT 1
                          FROM identity_platformidentitydeliveryreconciliationreceipt
                               receipt
                         WHERE receipt.delivery_id = delivery.id
                           AND receipt.operation = 'resolve_retry'
                           AND (
                                receipt.result_version =
                                    delivery.aggregate_version
                                OR EXISTS (
                                    SELECT 1
                                      FROM identity_platformidentitydeliverylateoutcome
                                           late
                                     WHERE late.delivery_id = delivery.id
                                       AND late.created_at >= receipt.created_at
                                )
                           )
                    )
                ) IS DISTINCT FROM true
             ) OR (
                delivery.status = 'permanent_failed'
                AND (
                    (
                        attempt.outcome = 'permanent_failure'
                        AND delivery.safe_error_code IS NOT DISTINCT FROM
                            attempt.safe_error_code
                    )
                    OR (
                        attempt.outcome = 'lease_lost'
                        AND (
                            (
                                delivery.safe_error_code =
                                    'delivery_attempts_exhausted'
                                AND delivery.attempt_count = delivery.max_attempts
                                AND delivery.reconciliation_required_at
                                    IS NOT DISTINCT FROM attempt.finished_at
                            )
                            OR delivery.safe_error_code =
                                'invitation_not_deliverable'
                        )
                    )
                ) IS DISTINCT FROM true
             )
        )
        """,
    ),
    (
        "late delivery outcome provenance is inconsistent",
        """
        SELECT EXISTS (
            SELECT 1
              FROM identity_platformidentitydeliverylateoutcome late
             JOIN identity_platformidentitydelivery delivery
                ON delivery.id = late.delivery_id
             WHERE late.classification NOT IN (
                    'lease_superseded', 'lifecycle_cancelled'
                )
                OR (
                    late.classification = 'lifecycle_cancelled'
                    AND delivery.cancellation_requested_at IS NULL
                )
                OR late.provider_reference ~ '[[:cntrl:]]'
                OR (
                    late.safe_error_code <> ''
                    AND late.safe_error_code !~
                        '^[a-z0-9][a-z0-9_.-]{0,119}$'
                )
        )
        """,
    ),
    (
        "delivery reconciliation receipt result versions are not unique",
        """
        SELECT EXISTS (
            SELECT 1
              FROM identity_platformidentitydeliveryreconciliationreceipt
             GROUP BY delivery_id, result_version
            HAVING count(*) > 1
        )
        """,
    ),
    (
        "historical reconciliation receipt cannot be proven at the current version",
        """
        SELECT EXISTS (
            SELECT 1
              FROM identity_platformidentitydeliveryreconciliationreceipt receipt
             JOIN identity_platformidentitydelivery delivery
                ON delivery.id = receipt.delivery_id
             LEFT JOIN identity_account actor ON actor.id = receipt.actor_id
             WHERE receipt.operation NOT IN ('resolve_delivered', 'resolve_retry')
                OR receipt.inventory_control_id IS DISTINCT FROM true
                OR actor.id IS NULL
                OR actor.account_kind IS DISTINCT FROM 'platform_administrator'
                OR receipt.request_digest IS NULL
                OR receipt.request_digest !~ '^[0-9a-f]{64}$'
                OR receipt.reason IS NULL
                OR btrim(receipt.reason) = ''
                OR receipt.reason IS DISTINCT FROM btrim(receipt.reason)
                OR receipt.source_channel IS NULL
                OR receipt.source_channel !~ '^[a-z][a-z0-9_-]{0,39}$'
                OR (
                    receipt.result_version = delivery.aggregate_version
                    AND (
                        delivery.reconciliation_state IS DISTINCT FROM 'resolved'
                        OR delivery.reconciled_at IS NULL
                        OR (
                            receipt.operation = 'resolve_delivered'
                            AND (
                                delivery.status IS DISTINCT FROM 'delivered'
                                OR delivery.reconciliation_code IS DISTINCT FROM
                                    'operator_confirmed_delivered'
                                OR delivery.delivered_at IS NULL
                                OR delivery.provider_reference = ''
                                OR delivery.payload_destroyed_at IS NULL
                                OR delivery.payload_destruction_reason IS DISTINCT FROM
                                    'delivered'
                            )
                        )
                        OR (
                            receipt.operation = 'resolve_retry'
                            AND (
                                delivery.status IS DISTINCT FROM 'retrying'
                                OR delivery.reconciliation_code IS DISTINCT FROM
                                    'operator_confirmed_retry'
                                OR delivery.payload_destroyed_at IS NOT NULL
                                OR delivery.safe_error_code IS DISTINCT FROM
                                    'delivery_reconciliation_retry'
                                OR delivery.next_retry_at IS DISTINCT FROM
                                    delivery.reconciled_at
                                OR delivery.available_at IS DISTINCT FROM
                                    delivery.reconciled_at
                            )
                        )
                    )
                )
        )
        """,
    ),
)


def validate_existing_page10_delivery_history(apps, schema_editor):  # type: ignore[no-untyped-def]
    """Refuse to install guards over an already inconsistent delivery graph."""

    del apps
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            LOCK TABLE
                audit_auditevent,
                identity_account,
                identity_identitychallenge,
                identity_platformaccountinvitation,
                identity_platformaccountinvitationtransition,
                identity_platformaccountinvitationcommandreceipt,
                identity_platformidentitydelivery,
                identity_platformidentitydeliveryattempt,
                identity_platformidentitydeliverylateoutcome,
                identity_platformidentitydeliveryreconciliationreceipt
            IN SHARE ROW EXCLUSIVE MODE
            """
        )
        cursor.execute(
            """
            SELECT identity_page10_hardened_assert_delivery(id)
              FROM identity_platformidentitydelivery
             ORDER BY id
            """
        )
        cursor.execute(
            """
            SELECT identity_page10_hardened_assert_transition(
                       invitation_id,
                       version
                   )
              FROM identity_platformaccountinvitationtransition
             ORDER BY invitation_id, version
            """
        )
        cursor.execute(
            """
            SELECT identity_page10_hardened_assert_reconciliation_receipt(id)
              FROM identity_platformidentitydeliveryreconciliationreceipt
             ORDER BY id
            """
        )
        for message, query in EXISTING_HISTORY_CHECKS:
            cursor.execute(query)
            if bool(cursor.fetchone()[0]):
                raise RuntimeError(
                    "Identity 0014 forward migration refused: " + message + ". "
                    "Repair or quarantine the evidence under a controlled "
                    "migration-owner recovery plan, then retry."
                )


def refuse_live_page10_recovery_rollback(apps, schema_editor):  # type: ignore[no-untyped-def]
    """Never reopen weaker guards after durable invitation evidence exists."""

    del apps
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            LOCK TABLE
                identity_platformaccountinvitation,
                identity_platformaccountinvitationtransition,
                identity_platformaccountinvitationcommandreceipt,
                identity_identitychallenge,
                identity_platformidentitydelivery,
                identity_platformidentitydeliveryattempt,
                identity_platformidentitydeliverylateoutcome,
                identity_platformidentitydeliveryreconciliationreceipt
            IN SHARE ROW EXCLUSIVE MODE
            """
        )
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM identity_platformaccountinvitation
                UNION ALL
                SELECT 1 FROM identity_identitychallenge
                 WHERE purpose = 'account_invitation'
                    OR token_digest_key_id <> ''
                UNION ALL
                SELECT 1 FROM identity_platformidentitydeliveryattempt
                UNION ALL
                SELECT 1 FROM identity_platformidentitydeliverylateoutcome
                UNION ALL
                SELECT 1
                  FROM identity_platformidentitydeliveryreconciliationreceipt
            )
            """
        )
        if bool(cursor.fetchone()[0]):
            raise RuntimeError(
                "Identity 0014 rollback refused: live invitation, digest-key, "
                "delivery-attempt, late-outcome, or reconciliation evidence "
                "depends on the hardened database boundary. Use a controlled "
                "migration-owner recovery plan instead."
            )


class Migration(migrations.Migration):
    dependencies = [  # noqa: RUF012
        ("audit", "0007_identity_reconciliation_audit_uniqueness"),
        ("identity", "0013_invitation_token_digest_keys"),
    ]

    operations = [  # noqa: RUF012
        migrations.RunSQL(
            sql=INSTALL_HARDENED_GUARDS,
            reverse_sql=REMOVE_HARDENED_GUARDS,
        ),
        migrations.RunPython(
            validate_existing_page10_delivery_history,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=INSTALL_RECEIPT_UNIQUENESS,
                    reverse_sql=REMOVE_RECEIPT_UNIQUENESS,
                ),
            ],
            state_operations=[
                migrations.AddConstraint(
                    model_name="platformaccountinvitationcommandreceipt",
                    constraint=models.UniqueConstraint(
                        fields=("invitation", "result_version"),
                        name="identity_invitation_result_receipt_unique",
                    ),
                ),
                migrations.AddConstraint(
                    model_name=(
                        "platformidentitydeliveryreconciliationreceipt"
                    ),
                    constraint=models.UniqueConstraint(
                        fields=("delivery", "result_version"),
                        name="identity_reconcile_result_receipt_unique",
                    ),
                ),
            ],
        ),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_live_page10_recovery_rollback,
        ),
    ]
