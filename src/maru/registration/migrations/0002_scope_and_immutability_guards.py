from django.db import migrations

FORWARD_SQL = """
CREATE FUNCTION maru_guard_registration_template()
RETURNS trigger AS $$
DECLARE
    series_organization uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'registration templates use retirement'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.series_id IS NOT NULL THEN
        SELECT organization_id INTO series_organization
          FROM organizations_conventionseries
         WHERE id = NEW.series_id;
        IF series_organization IS NULL
           OR series_organization != NEW.organization_id
        THEN
            RAISE EXCEPTION 'registration template series scope mismatch'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF TG_OP = 'UPDATE' AND OLD.status IN ('published', 'retired') THEN
        IF OLD.status = 'published'
           AND NEW.status = 'retired'
           AND (
               to_jsonb(NEW) - ARRAY['status', 'updated_at']
               = to_jsonb(OLD) - ARRAY['status', 'updated_at']
           )
        THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'published registration templates are immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER registration_template_scope_and_version_guard
BEFORE INSERT OR UPDATE OR DELETE
ON registration_registrationtemplate
FOR EACH ROW EXECUTE FUNCTION maru_guard_registration_template();

CREATE FUNCTION maru_guard_registration_template_child()
RETURNS trigger AS $$
DECLARE
    template_status varchar;
BEGIN
    SELECT status INTO template_status
      FROM registration_registrationtemplate
     WHERE id = COALESCE(NEW.template_id, OLD.template_id);
    IF template_status IS NULL OR template_status != 'draft' THEN
        RAISE EXCEPTION 'published registration template content is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER registration_template_question_version_guard
BEFORE INSERT OR UPDATE OR DELETE
ON registration_registrationtemplatequestion
FOR EACH ROW EXECUTE FUNCTION maru_guard_registration_template_child();

CREATE TRIGGER registration_template_product_version_guard
BEFORE INSERT OR UPDATE OR DELETE
ON registration_registrationtemplateproduct
FOR EACH ROW EXECUTE FUNCTION maru_guard_registration_template_child();

CREATE FUNCTION maru_guard_registration_configuration()
RETURNS trigger AS $$
DECLARE
    edition_organization uuid;
    edition_lifecycle varchar;
    template_organization uuid;
    source_organization uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'registration configurations use retirement'
            USING ERRCODE = '23514';
    END IF;

    SELECT organization_id, lifecycle
      INTO edition_organization, edition_lifecycle
      FROM events_eventedition
     WHERE id = NEW.edition_id;
    IF edition_organization IS NULL
       OR edition_organization != NEW.organization_id
    THEN
        RAISE EXCEPTION 'registration configuration edition scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF edition_lifecycle IN ('archived', 'cancelled') THEN
        RAISE EXCEPTION 'registration configuration is closed for this edition'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.source_template_id IS NOT NULL THEN
        SELECT organization_id INTO template_organization
          FROM registration_registrationtemplate
         WHERE id = NEW.source_template_id;
        IF template_organization IS NULL
           OR template_organization != NEW.organization_id
        THEN
            RAISE EXCEPTION 'registration template source scope mismatch'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF NEW.source_edition_id IS NOT NULL THEN
        SELECT organization_id INTO source_organization
          FROM events_eventedition
         WHERE id = NEW.source_edition_id;
        IF source_organization IS NULL
           OR source_organization != NEW.organization_id
        THEN
            RAISE EXCEPTION 'registration edition source scope mismatch'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF TG_OP = 'UPDATE' AND OLD.status IN ('active', 'retired') THEN
        IF OLD.status = 'active'
           AND NEW.status = 'retired'
           AND (
               to_jsonb(NEW) - ARRAY['status', 'updated_at']
               = to_jsonb(OLD) - ARRAY['status', 'updated_at']
           )
        THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'active registration configuration is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER registration_configuration_scope_and_version_guard
BEFORE INSERT OR UPDATE OR DELETE
ON registration_registrationconfiguration
FOR EACH ROW EXECUTE FUNCTION maru_guard_registration_configuration();

CREATE FUNCTION maru_guard_registration_configuration_child()
RETURNS trigger AS $$
DECLARE
    configuration_status varchar;
BEGIN
    SELECT status INTO configuration_status
      FROM registration_registrationconfiguration
     WHERE id = COALESCE(NEW.configuration_id, OLD.configuration_id);
    IF configuration_status IS NULL OR configuration_status != 'draft' THEN
        RAISE EXCEPTION 'active registration configuration content is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER registration_question_configuration_guard
BEFORE INSERT OR UPDATE OR DELETE
ON registration_registrationquestion
FOR EACH ROW EXECUTE FUNCTION maru_guard_registration_configuration_child();

CREATE TRIGGER registration_product_configuration_guard
BEFORE INSERT OR UPDATE OR DELETE
ON registration_admissionproduct
FOR EACH ROW EXECUTE FUNCTION maru_guard_registration_configuration_child();

CREATE FUNCTION maru_guard_registration_record()
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

CREATE FUNCTION maru_guard_registration_append_record()
RETURNS trigger AS $$
DECLARE
    registration_organization uuid;
    registration_edition uuid;
BEGIN
    IF TG_OP != 'INSERT' THEN
        RAISE EXCEPTION 'registration history is append-only'
            USING ERRCODE = '23514';
    END IF;
    SELECT organization_id, edition_id
      INTO registration_organization, registration_edition
      FROM registration_registration
     WHERE id = NEW.registration_id;
    IF registration_organization IS NULL
       OR registration_organization != NEW.organization_id
       OR registration_edition != NEW.edition_id
    THEN
        RAISE EXCEPTION 'registration history scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER registration_submission_append_guard
BEFORE INSERT OR UPDATE OR DELETE
ON registration_registrationsubmission
FOR EACH ROW EXECUTE FUNCTION maru_guard_registration_append_record();

CREATE TRIGGER registration_payment_append_guard
BEFORE INSERT OR UPDATE OR DELETE
ON registration_paymentattempt
FOR EACH ROW EXECUTE FUNCTION maru_guard_registration_append_record();

CREATE TRIGGER registration_entitlement_append_guard
BEFORE INSERT OR UPDATE OR DELETE
ON registration_entitlement
FOR EACH ROW EXECUTE FUNCTION maru_guard_registration_append_record();

CREATE TRIGGER registration_check_in_append_guard
BEFORE INSERT OR UPDATE OR DELETE
ON registration_checkinrecord
FOR EACH ROW EXECUTE FUNCTION maru_guard_registration_append_record();

CREATE TRIGGER registration_timeline_append_guard
BEFORE INSERT OR UPDATE OR DELETE
ON registration_registrationtimelineentry
FOR EACH ROW EXECUTE FUNCTION maru_guard_registration_append_record();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS registration_timeline_append_guard
    ON registration_registrationtimelineentry;
DROP TRIGGER IF EXISTS registration_check_in_append_guard
    ON registration_checkinrecord;
DROP TRIGGER IF EXISTS registration_entitlement_append_guard
    ON registration_entitlement;
DROP TRIGGER IF EXISTS registration_payment_append_guard
    ON registration_paymentattempt;
DROP TRIGGER IF EXISTS registration_submission_append_guard
    ON registration_registrationsubmission;
DROP FUNCTION IF EXISTS maru_guard_registration_append_record();
DROP TRIGGER IF EXISTS registration_record_scope_and_lifecycle_guard
    ON registration_registration;
DROP FUNCTION IF EXISTS maru_guard_registration_record();
DROP TRIGGER IF EXISTS registration_product_configuration_guard
    ON registration_admissionproduct;
DROP TRIGGER IF EXISTS registration_question_configuration_guard
    ON registration_registrationquestion;
DROP FUNCTION IF EXISTS maru_guard_registration_configuration_child();
DROP TRIGGER IF EXISTS registration_configuration_scope_and_version_guard
    ON registration_registrationconfiguration;
DROP FUNCTION IF EXISTS maru_guard_registration_configuration();
DROP TRIGGER IF EXISTS registration_template_product_version_guard
    ON registration_registrationtemplateproduct;
DROP TRIGGER IF EXISTS registration_template_question_version_guard
    ON registration_registrationtemplatequestion;
DROP FUNCTION IF EXISTS maru_guard_registration_template_child();
DROP TRIGGER IF EXISTS registration_template_scope_and_version_guard
    ON registration_registrationtemplate;
DROP FUNCTION IF EXISTS maru_guard_registration_template();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("registration", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
