from django.db import migrations


FORWARD_SQL = """
CREATE OR REPLACE FUNCTION maru_guard_registration_profile_extension_provenance()
RETURNS trigger AS $$
DECLARE
    target_organization uuid;
    target_series uuid;
    target_start date;
    template_organization uuid;
    template_series uuid;
    template_status varchar;
    source_organization uuid;
    source_start date;
BEGIN
    IF NEW.source_template_id IS NOT NULL
       AND NEW.source_prior_edition_id IS NOT NULL
    THEN
        RAISE EXCEPTION 'profile extension provenance must use one source'
            USING ERRCODE = '23514';
    END IF;

    SELECT organization_id, series_id, starts_on
      INTO target_organization, target_series, target_start
      FROM events_eventedition
     WHERE id = NEW.edition_id;

    IF NEW.source_template_id IS NOT NULL THEN
        SELECT organization_id, series_id, status
          INTO template_organization, template_series, template_status
          FROM registration_registrationtemplate
         WHERE id = NEW.source_template_id;
        IF template_organization IS NULL
           OR template_organization != target_organization
           OR (
               template_series IS NOT NULL
               AND template_series != target_series
           )
           OR template_status != 'published'
        THEN
            RAISE EXCEPTION 'invalid profile extension template provenance'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF NEW.source_prior_edition_id IS NOT NULL THEN
        SELECT organization_id, starts_on
          INTO source_organization, source_start
          FROM events_eventedition
         WHERE id = NEW.source_prior_edition_id;
        IF source_organization IS NULL
           OR source_organization != target_organization
           OR NEW.source_prior_edition_id = NEW.edition_id
           OR source_start >= target_start
        THEN
            RAISE EXCEPTION 'invalid profile extension edition provenance'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS registration_profile_extension_provenance_guard
ON registration_registrationprofileextensionfield;
CREATE TRIGGER registration_profile_extension_provenance_guard
BEFORE INSERT OR UPDATE
ON registration_registrationprofileextensionfield
FOR EACH ROW
EXECUTE FUNCTION maru_guard_registration_profile_extension_provenance();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS registration_profile_extension_provenance_guard
ON registration_registrationprofileextensionfield;
DROP FUNCTION IF EXISTS maru_guard_registration_profile_extension_provenance();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("registration", "0029_profile_extension_integrity_guards"),
    ]

    operations = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
