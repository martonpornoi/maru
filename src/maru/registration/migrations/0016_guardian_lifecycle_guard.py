from django.db import migrations

FORWARD_SQL = """
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
        (OLD.state = 'guardian_pending'
            AND NEW.state IN (
                'waitlisted',
                'payment_pending',
                'confirmed',
                'cancelled'
            ))
        OR (OLD.state = 'waitlisted'
            AND NEW.state IN ('payment_pending', 'confirmed', 'cancelled'))
        OR (OLD.state = 'payment_pending'
            AND NEW.state IN ('confirmed', 'expired', 'cancelled'))
        OR (OLD.state = 'confirmed' AND NEW.state IN ('checked_in', 'cancelled'))
       )
       AND NEW.aggregate_version = OLD.aggregate_version + 1
       AND (
           to_jsonb(NEW)
               - ARRAY[
                   'state',
                   'aggregate_version',
                   'waitlisted_at',
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
                   'waitlisted_at',
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
"""


class Migration(migrations.Migration):
    dependencies = [
        ("registration", "0015_alter_registration_state_and_more"),
    ]

    operations = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=migrations.RunSQL.noop),
    ]
