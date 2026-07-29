from django.db import migrations

FORWARD_SQL = """
DROP TRIGGER registration_record_scope_and_lifecycle_guard
    ON registration_registration;

UPDATE registration_registration AS registration
   SET payment_due_at = (
       registration.submitted_at
       + make_interval(
           mins => COALESCE(
               product.payment_window_minutes,
               configuration.default_payment_window_minutes
           )
       )
   )
  FROM registration_admissionproduct AS product,
       registration_registrationconfiguration AS configuration
 WHERE registration.product_id = product.id
   AND registration.configuration_id = configuration.id
   AND registration.state = 'payment_pending'
   AND registration.payment_due_at IS NULL;

UPDATE registration_registration
   SET confirmation_basis = 'free'
 WHERE state IN ('confirmed', 'checked_in')
   AND price_minor_snapshot = 0
   AND confirmation_basis = '';

UPDATE registration_registration AS registration
   SET confirmation_basis = 'provider'
 WHERE registration.state IN ('confirmed', 'checked_in')
   AND registration.confirmation_basis = ''
   AND EXISTS (
       SELECT 1
         FROM registration_paymentattempt AS payment
        WHERE payment.registration_id = registration.id
          AND payment.status = 'succeeded'
   );

CREATE OR REPLACE FUNCTION maru_guard_registration_record()
RETURNS trigger AS $$
DECLARE
    edition_organization uuid;
    edition_lifecycle varchar;
    participation_organization uuid;
    participation_edition uuid;
    participation_account uuid;
    configuration_organization uuid;
    configuration_edition uuid;
    configuration_status varchar;
    product_configuration uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'registrations require cancellation and retention'
            USING ERRCODE = '23514';
    END IF;

    SELECT organization_id, lifecycle
      INTO edition_organization, edition_lifecycle
      FROM events_eventedition
     WHERE id = NEW.edition_id;
    SELECT organization_id, edition_id, account_id
      INTO participation_organization, participation_edition, participation_account
      FROM participation_participation
     WHERE id = NEW.participation_id;
    SELECT organization_id, edition_id, status
      INTO configuration_organization, configuration_edition, configuration_status
      FROM registration_registrationconfiguration
     WHERE id = NEW.configuration_id;
    SELECT configuration_id INTO product_configuration
      FROM registration_admissionproduct
     WHERE id = NEW.product_id;

    IF edition_organization IS NULL
       OR edition_organization != NEW.organization_id
       OR participation_organization != NEW.organization_id
       OR participation_edition != NEW.edition_id
       OR participation_account != NEW.account_id
       OR configuration_organization != NEW.organization_id
       OR configuration_edition != NEW.edition_id
       OR product_configuration != NEW.configuration_id
    THEN
        RAISE EXCEPTION 'registration scope relationships do not match'
            USING ERRCODE = '23514';
    END IF;
    IF edition_lifecycle IN ('archived', 'cancelled') THEN
        RAISE EXCEPTION 'registration records are closed for this edition'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.aggregate_version != 1 OR configuration_status != 'active' THEN
            RAISE EXCEPTION 'new registration requires active version one'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.state = 'waitlisted' AND NEW.waitlisted_at IS NULL THEN
            RAISE EXCEPTION 'waitlisted registration requires queue time'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.state = 'payment_pending' AND NEW.payment_due_at IS NULL THEN
            RAISE EXCEPTION 'payment pending registration requires deadline'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.state = 'confirmed'
           AND (NEW.confirmed_at IS NULL OR NEW.confirmation_basis = '')
        THEN
            RAISE EXCEPTION 'confirmed registration requires evidence basis'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.state = 'payment_pending'
       AND NEW.state = 'payment_pending'
       AND NEW.aggregate_version = OLD.aggregate_version + 1
       AND NEW.payment_due_at IS NOT NULL
       AND (
           to_jsonb(NEW)
               - ARRAY['aggregate_version', 'payment_due_at', 'updated_at']
           = to_jsonb(OLD)
               - ARRAY['aggregate_version', 'payment_due_at', 'updated_at']
       )
    THEN
        RETURN NEW;
    END IF;

    IF (
        (OLD.state = 'waitlisted'
            AND NEW.state IN ('payment_pending', 'confirmed', 'cancelled'))
        OR (OLD.state = 'payment_pending'
            AND NEW.state IN ('confirmed', 'expired', 'cancelled'))
        OR (OLD.state = 'confirmed' AND NEW.state = 'checked_in')
       )
       AND NEW.aggregate_version = OLD.aggregate_version + 1
       AND (
           to_jsonb(NEW)
               - ARRAY[
                   'state',
                   'aggregate_version',
                   'offered_at',
                   'payment_due_at',
                   'confirmed_at',
                   'checked_in_at',
                   'expired_at',
                   'cancelled_at',
                   'confirmation_basis',
                   'updated_at'
               ]
           = to_jsonb(OLD)
               - ARRAY[
                   'state',
                   'aggregate_version',
                   'offered_at',
                   'payment_due_at',
                   'confirmed_at',
                   'checked_in_at',
                   'expired_at',
                   'cancelled_at',
                   'confirmation_basis',
                   'updated_at'
               ]
       )
    THEN
        IF NEW.state = 'payment_pending' AND NEW.payment_due_at IS NULL THEN
            RAISE EXCEPTION 'payment pending registration requires deadline'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.state = 'confirmed'
           AND (NEW.confirmed_at IS NULL OR NEW.confirmation_basis = '')
        THEN
            RAISE EXCEPTION 'confirmed registration requires evidence basis'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.state = 'expired' AND NEW.expired_at IS NULL THEN
            RAISE EXCEPTION 'expired registration requires expiry time'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.state = 'cancelled' AND NEW.cancelled_at IS NULL THEN
            RAISE EXCEPTION 'cancelled registration requires cancellation time'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'invalid registration lifecycle transition'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER registration_record_scope_and_lifecycle_guard
BEFORE INSERT OR UPDATE OR DELETE
ON registration_registration
FOR EACH ROW EXECUTE FUNCTION maru_guard_registration_record();

CREATE TRIGGER registration_adjustment_append_guard
BEFORE INSERT OR UPDATE OR DELETE
ON registration_registrationadjustment
FOR EACH ROW EXECUTE FUNCTION maru_guard_registration_append_record();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS registration_adjustment_append_guard
    ON registration_registrationadjustment;
DROP TRIGGER registration_record_scope_and_lifecycle_guard
    ON registration_registration;

CREATE OR REPLACE FUNCTION maru_guard_registration_record()
RETURNS trigger AS $$
DECLARE
    edition_organization uuid;
    edition_lifecycle varchar;
    participation_organization uuid;
    participation_edition uuid;
    participation_account uuid;
    configuration_organization uuid;
    configuration_edition uuid;
    configuration_status varchar;
    product_configuration uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'registrations require cancellation and retention'
            USING ERRCODE = '23514';
    END IF;

    SELECT organization_id, lifecycle
      INTO edition_organization, edition_lifecycle
      FROM events_eventedition
     WHERE id = NEW.edition_id;
    SELECT organization_id, edition_id, account_id
      INTO participation_organization, participation_edition, participation_account
      FROM participation_participation
     WHERE id = NEW.participation_id;
    SELECT organization_id, edition_id, status
      INTO configuration_organization, configuration_edition, configuration_status
      FROM registration_registrationconfiguration
     WHERE id = NEW.configuration_id;
    SELECT configuration_id INTO product_configuration
      FROM registration_admissionproduct
     WHERE id = NEW.product_id;

    IF edition_organization IS NULL
       OR edition_organization != NEW.organization_id
       OR participation_organization != NEW.organization_id
       OR participation_edition != NEW.edition_id
       OR participation_account != NEW.account_id
       OR configuration_organization != NEW.organization_id
       OR configuration_edition != NEW.edition_id
       OR product_configuration != NEW.configuration_id
    THEN
        RAISE EXCEPTION 'registration scope relationships do not match'
            USING ERRCODE = '23514';
    END IF;
    IF edition_lifecycle IN ('archived', 'cancelled') THEN
        RAISE EXCEPTION 'registration records are closed for this edition'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.aggregate_version != 1 OR configuration_status != 'active' THEN
            RAISE EXCEPTION 'new registration requires active version one'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF (
        (OLD.state = 'payment_pending' AND NEW.state = 'confirmed')
        OR (OLD.state = 'confirmed' AND NEW.state = 'checked_in')
       )
       AND NEW.aggregate_version = OLD.aggregate_version + 1
       AND (
           to_jsonb(NEW)
               - ARRAY[
                   'state',
                   'aggregate_version',
                   'confirmed_at',
                   'checked_in_at',
                   'updated_at'
               ]
           = to_jsonb(OLD)
               - ARRAY[
                   'state',
                   'aggregate_version',
                   'confirmed_at',
                   'checked_in_at',
                   'updated_at'
               ]
       )
    THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'invalid registration lifecycle transition'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER registration_record_scope_and_lifecycle_guard
BEFORE INSERT OR UPDATE OR DELETE
ON registration_registration
FOR EACH ROW EXECUTE FUNCTION maru_guard_registration_record();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("registration", "0005_registrationadjustment_and_more"),
    ]

    operations = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
