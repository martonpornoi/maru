from django.db import migrations


FIELD_GUARD_SQL = """
CREATE OR REPLACE FUNCTION maru_guard_registration_profile_extension_field()
RETURNS trigger AS $$
DECLARE
    edition_organization uuid;
    prior_edition uuid;
    prior_key varchar;
    prior_version integer;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'profile extension fields use retirement, not deletion'
            USING ERRCODE = '23514';
    END IF;
    SELECT organization_id INTO edition_organization
      FROM events_eventedition WHERE id = NEW.edition_id;
    IF edition_organization IS NULL
       OR edition_organization != NEW.organization_id
    THEN
        RAISE EXCEPTION 'profile extension field scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.supersedes_id IS NOT NULL THEN
        SELECT edition_id, key, version
          INTO prior_edition, prior_key, prior_version
          FROM registration_registrationprofileextensionfield
         WHERE id = NEW.supersedes_id;
        IF prior_edition IS NULL
           OR prior_edition != NEW.edition_id
           OR prior_key != NEW.key
           OR prior_version >= NEW.version
        THEN
            RAISE EXCEPTION 'invalid superseded profile extension field'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF NEW.status = 'active'
       AND (
           NEW.review_status != 'approved'
           OR NEW.approved_by_id IS NULL
           OR NEW.approved_at IS NULL
       )
    THEN
        RAISE EXCEPTION 'active profile extension field lacks approval'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.status = 'active' THEN
        IF NEW.status != 'retired'
           OR (
               to_jsonb(NEW) - 'status' - 'updated_at'
               != to_jsonb(OLD) - 'status' - 'updated_at'
           )
        THEN
            RAISE EXCEPTION 'active profile extension fields are immutable'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS registration_profile_extension_field_guard
ON registration_registrationprofileextensionfield;
CREATE TRIGGER registration_profile_extension_field_guard
BEFORE INSERT OR UPDATE OR DELETE
ON registration_registrationprofileextensionfield
FOR EACH ROW EXECUTE FUNCTION maru_guard_registration_profile_extension_field();
"""

VALUE_GUARD_SQL = """
CREATE OR REPLACE FUNCTION maru_guard_registration_profile_extension_value()
RETURNS trigger AS $$
DECLARE
    registration_organization uuid;
    registration_edition uuid;
    field_organization uuid;
    field_edition uuid;
    stable_key varchar;
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        RAISE EXCEPTION 'profile extension value revisions are append-only'
            USING ERRCODE = '23514';
    END IF;
    SELECT organization_id, edition_id
      INTO registration_organization, registration_edition
      FROM registration_registration WHERE id = NEW.registration_id;
    SELECT organization_id, edition_id, key
      INTO field_organization, field_edition, stable_key
      FROM registration_registrationprofileextensionfield WHERE id = NEW.field_id;
    IF registration_organization IS NULL
       OR registration_organization != NEW.organization_id
       OR registration_edition != NEW.edition_id
       OR field_organization != NEW.organization_id
       OR field_edition != NEW.edition_id
       OR stable_key != NEW.field_key
    THEN
        RAISE EXCEPTION 'profile extension value scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS registration_profile_extension_value_guard
ON registration_registrationprofileextensionvaluerevision;
CREATE TRIGGER registration_profile_extension_value_guard
BEFORE INSERT OR UPDATE OR DELETE
ON registration_registrationprofileextensionvaluerevision
FOR EACH ROW EXECUTE FUNCTION maru_guard_registration_profile_extension_value();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS registration_profile_extension_value_guard
ON registration_registrationprofileextensionvaluerevision;
DROP FUNCTION IF EXISTS maru_guard_registration_profile_extension_value();
DROP TRIGGER IF EXISTS registration_profile_extension_field_guard
ON registration_registrationprofileextensionfield;
DROP FUNCTION IF EXISTS maru_guard_registration_profile_extension_field();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("registration", "0028_registration_profile_extensions"),
    ]

    operations = [
        migrations.RunSQL(FIELD_GUARD_SQL, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(VALUE_GUARD_SQL, reverse_sql=REVERSE_SQL),
    ]
