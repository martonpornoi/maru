from django.db import migrations

FORWARD_SQL = """
CREATE TRIGGER registration_template_section_version_guard
BEFORE INSERT OR UPDATE OR DELETE
ON registration_registrationtemplatesection
FOR EACH ROW EXECUTE FUNCTION maru_guard_registration_template_child();

CREATE TRIGGER registration_section_configuration_guard
BEFORE INSERT OR UPDATE OR DELETE
ON registration_registrationsection
FOR EACH ROW EXECUTE FUNCTION maru_guard_registration_configuration_child();

CREATE FUNCTION maru_guard_attendee_registration_profile()
RETURNS trigger AS $$
DECLARE
    registration_organization uuid;
    registration_edition uuid;
    registration_account uuid;
    edition_organization uuid;
    edition_lifecycle varchar;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'registration profiles require retention workflow'
            USING ERRCODE = '23514';
    END IF;

    SELECT organization_id, edition_id, account_id
      INTO registration_organization, registration_edition, registration_account
      FROM registration_registration
     WHERE id = NEW.registration_id;
    SELECT organization_id, lifecycle
      INTO edition_organization, edition_lifecycle
      FROM events_eventedition
     WHERE id = NEW.edition_id;

    IF registration_organization IS NULL
       OR registration_organization != NEW.organization_id
       OR registration_edition != NEW.edition_id
       OR registration_account != NEW.account_id
       OR edition_organization != NEW.organization_id
    THEN
        RAISE EXCEPTION 'registration profile scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF edition_lifecycle IN ('archived', 'cancelled') THEN
        RAISE EXCEPTION 'registration profile is closed for this edition'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' AND (
        OLD.registration_id != NEW.registration_id
        OR OLD.organization_id != NEW.organization_id
        OR OLD.edition_id != NEW.edition_id
        OR OLD.account_id != NEW.account_id
    ) THEN
        RAISE EXCEPTION 'registration profile scope is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER attendee_registration_profile_scope_guard
BEFORE INSERT OR UPDATE OR DELETE
ON registration_attendeeregistrationprofile
FOR EACH ROW EXECUTE FUNCTION maru_guard_attendee_registration_profile();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS attendee_registration_profile_scope_guard
    ON registration_attendeeregistrationprofile;
DROP FUNCTION IF EXISTS maru_guard_attendee_registration_profile();
DROP TRIGGER IF EXISTS registration_section_configuration_guard
    ON registration_registrationsection;
DROP TRIGGER IF EXISTS registration_template_section_version_guard
    ON registration_registrationtemplatesection;
"""


class Migration(migrations.Migration):
    dependencies = [
        (
            "registration",
            "0003_attendeeregistrationprofile_registrationsection_and_more",
        ),
    ]

    operations = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
