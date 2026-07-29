from django.db import migrations

PROFILE_GUARD_SQL = """
CREATE OR REPLACE FUNCTION maru_guard_attendee_registration_profile()
RETURNS trigger AS $$
DECLARE
    registration_organization uuid;
    registration_edition uuid;
    registration_account uuid;
    edition_organization uuid;
    edition_lifecycle varchar;
    retention_workflow boolean :=
        current_setting('maru.retention_workflow', true) = 'on';
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'registration profiles require minimization, not deletion'
            USING ERRCODE = '23514';
    END IF;
    SELECT organization_id, edition_id, account_id
      INTO registration_organization, registration_edition, registration_account
      FROM registration_registration WHERE id = NEW.registration_id;
    SELECT organization_id, lifecycle
      INTO edition_organization, edition_lifecycle
      FROM events_eventedition WHERE id = NEW.edition_id;
    IF registration_organization IS NULL
       OR registration_organization != NEW.organization_id
       OR registration_edition != NEW.edition_id
       OR registration_account != NEW.account_id
       OR edition_organization != NEW.organization_id
    THEN
        RAISE EXCEPTION 'registration profile scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF edition_lifecycle IN ('archived', 'cancelled')
       AND NOT retention_workflow
    THEN
        RAISE EXCEPTION 'registration profile is closed for this edition'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.aggregate_version != 1 THEN
            RAISE EXCEPTION 'new registration profile requires version one'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.registration_id != NEW.registration_id
       OR OLD.organization_id != NEW.organization_id
       OR OLD.edition_id != NEW.edition_id
       OR OLD.account_id != NEW.account_id
    THEN
        RAISE EXCEPTION 'registration profile scope is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.aggregate_version != OLD.aggregate_version + 1 THEN
        RAISE EXCEPTION 'registration profile update must increment version'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

FURSUIT_GUARD_SQL = """
CREATE OR REPLACE FUNCTION maru_guard_attendee_fursuit()
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
    retention_workflow boolean :=
        current_setting('maru.retention_workflow', true) = 'on';
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'attendee fursuits require minimization, not deletion'
            USING ERRCODE = '23514';
    END IF;
    SELECT registration_id, organization_id, edition_id, account_id
      INTO profile_registration, profile_organization, profile_edition,
           profile_account
      FROM registration_attendeeregistrationprofile WHERE id = NEW.profile_id;
    SELECT organization_id, edition_id, account_id
      INTO registration_organization, registration_edition, registration_account
      FROM registration_registration WHERE id = NEW.registration_id;
    SELECT organization_id, lifecycle
      INTO edition_organization, edition_lifecycle
      FROM events_eventedition WHERE id = NEW.edition_id;
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
    IF edition_lifecycle IN ('archived', 'cancelled')
       AND NOT retention_workflow
    THEN
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
"""


class Migration(migrations.Migration):
    dependencies = [("registration", "0017_registrationlifecyclerun")]

    operations = [
        migrations.RunSQL(PROFILE_GUARD_SQL, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(FURSUIT_GUARD_SQL, reverse_sql=migrations.RunSQL.noop),
    ]
