from django.db import migrations

FORWARD_SQL = """
CREATE FUNCTION maru_guard_attendee_fursuit()
RETURNS trigger AS $$
DECLARE
    profile_registration uuid;
    profile_organization uuid;
    profile_edition uuid;
    profile_account uuid;
    registration_organization uuid;
    registration_edition uuid;
    registration_account uuid;
    edition_organization uuid;
    edition_lifecycle varchar;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'attendee fursuits require profile workflow'
            USING ERRCODE = '23514';
    END IF;

    SELECT registration_id, organization_id, edition_id, account_id
      INTO profile_registration, profile_organization, profile_edition,
           profile_account
      FROM registration_attendeeregistrationprofile
     WHERE id = NEW.profile_id;
    SELECT organization_id, edition_id, account_id
      INTO registration_organization, registration_edition, registration_account
      FROM registration_registration
     WHERE id = NEW.registration_id;
    SELECT organization_id, lifecycle
      INTO edition_organization, edition_lifecycle
      FROM events_eventedition
     WHERE id = NEW.edition_id;

    IF profile_registration IS NULL
       OR profile_registration != NEW.registration_id
       OR profile_organization != NEW.organization_id
       OR profile_edition != NEW.edition_id
       OR profile_account != NEW.account_id
       OR registration_organization != NEW.organization_id
       OR registration_edition != NEW.edition_id
       OR registration_account != NEW.account_id
       OR edition_organization != NEW.organization_id
    THEN
        RAISE EXCEPTION 'attendee fursuit scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF edition_lifecycle IN ('archived', 'cancelled') THEN
        RAISE EXCEPTION 'attendee fursuit is closed for this edition'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' AND (
        OLD.profile_id != NEW.profile_id
        OR OLD.registration_id != NEW.registration_id
        OR OLD.organization_id != NEW.organization_id
        OR OLD.edition_id != NEW.edition_id
        OR OLD.account_id != NEW.account_id
    ) THEN
        RAISE EXCEPTION 'attendee fursuit scope is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER attendee_fursuit_scope_guard
BEFORE INSERT OR UPDATE OR DELETE
ON registration_attendeefursuit
FOR EACH ROW EXECUTE FUNCTION maru_guard_attendee_fursuit();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS attendee_fursuit_scope_guard
    ON registration_attendeefursuit;
DROP FUNCTION IF EXISTS maru_guard_attendee_fursuit();
"""


class Migration(migrations.Migration):
    dependencies = [
        (
            "registration",
            "0007_remove_attendeeregistrationprofile_fursuit_name_and_more",
        ),
    ]

    operations = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
