from django.db import migrations

FORWARD_SQL = """
CREATE FUNCTION maru_prevent_domain_event_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'domain events are append-only'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER effect_domain_event_append_only
BEFORE UPDATE OR DELETE
ON effects_domainevent
FOR EACH ROW EXECUTE FUNCTION maru_prevent_domain_event_mutation();

CREATE FUNCTION maru_prevent_effect_attempt_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'effect attempts are append-only'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER effect_attempt_append_only
BEFORE UPDATE OR DELETE
ON effects_effectattempt
FOR EACH ROW EXECUTE FUNCTION maru_prevent_effect_attempt_mutation();

CREATE FUNCTION maru_guard_outbox_message()
RETURNS trigger AS $$
DECLARE
    event_organization uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'outbox messages require controlled retention'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'INSERT' THEN
        SELECT organization_id INTO event_organization
          FROM effects_domainevent WHERE id = NEW.event_id;
        IF event_organization IS NULL
           OR event_organization != NEW.organization_id
        THEN
            RAISE EXCEPTION 'outbox tenant must match its domain event'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.event_id != OLD.event_id
       OR NEW.organization_id != OLD.organization_id
       OR NEW.destination != OLD.destination
       OR NEW.workload_pool != OLD.workload_pool
    THEN
        RAISE EXCEPTION 'outbox routing envelope is immutable'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.status != 'quarantined'
       AND (
           NEW.max_attempts != OLD.max_attempts
           OR NEW.replay_count != OLD.replay_count
       )
    THEN
        RAISE EXCEPTION 'outbox retry policy is immutable outside replay'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.status = 'pending'
       AND NEW.status IN ('processing', 'cancelled')
    THEN
        IF NEW.status = 'processing'
           AND NEW.attempt_count != OLD.attempt_count + 1
        THEN
            RAISE EXCEPTION 'claim must increment attempt count'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.status = 'cancelled'
           AND NEW.attempt_count != OLD.attempt_count
        THEN
            RAISE EXCEPTION 'cancellation cannot change attempt count'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.status = 'processing'
       AND NEW.status IN ('pending', 'succeeded', 'quarantined')
       AND NEW.attempt_count = OLD.attempt_count
    THEN
        RETURN NEW;
    END IF;

    IF OLD.status = 'processing'
       AND NEW.status = 'processing'
       AND OLD.lease_expires_at <= NEW.claimed_at
       AND NEW.attempt_count = OLD.attempt_count + 1
    THEN
        RETURN NEW;
    END IF;

    IF OLD.status = 'quarantined'
       AND NEW.status = 'pending'
       AND NEW.attempt_count = OLD.attempt_count
       AND NEW.max_attempts > OLD.max_attempts
       AND NEW.replay_count = OLD.replay_count + 1
    THEN
        RETURN NEW;
    END IF;

    RAISE EXCEPTION 'invalid outbox state transition'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER effect_outbox_state_guard
BEFORE INSERT OR UPDATE OR DELETE
ON effects_outboxmessage
FOR EACH ROW EXECUTE FUNCTION maru_guard_outbox_message();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS effect_outbox_state_guard
    ON effects_outboxmessage;
DROP FUNCTION IF EXISTS maru_guard_outbox_message();
DROP TRIGGER IF EXISTS effect_attempt_append_only
    ON effects_effectattempt;
DROP FUNCTION IF EXISTS maru_prevent_effect_attempt_mutation();
DROP TRIGGER IF EXISTS effect_domain_event_append_only
    ON effects_domainevent;
DROP FUNCTION IF EXISTS maru_prevent_domain_event_mutation();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("effects", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
