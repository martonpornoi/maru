from django.db import migrations

FORWARD_SQL = """
CREATE FUNCTION maru_validate_convention_series_profile_version()
RETURNS trigger AS $$
DECLARE
    profile_changed boolean;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.profile_version != 1 THEN
            RAISE EXCEPTION 'new convention series must start at profile version one'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.organization_id IS DISTINCT FROM OLD.organization_id
       OR NEW.slug IS DISTINCT FROM OLD.slug
    THEN
        RAISE EXCEPTION 'convention series ownership and stable slug are immutable'
            USING ERRCODE = '23514';
    END IF;

    profile_changed :=
        NEW.name IS DISTINCT FROM OLD.name
        OR NEW.description IS DISTINCT FROM OLD.description
        OR NEW.website_url IS DISTINCT FROM OLD.website_url
        OR NEW.contact_email IS DISTINCT FROM OLD.contact_email
        OR NEW.is_active IS DISTINCT FROM OLD.is_active;

    IF profile_changed THEN
        IF NEW.profile_version != OLD.profile_version + 1 THEN
            RAISE EXCEPTION 'series profile change must increment profile version'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.profile_version != OLD.profile_version THEN
        RAISE EXCEPTION 'series profile version changes only with profile facts'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER organizations_series_profile_version_guard
BEFORE INSERT OR UPDATE
ON organizations_conventionseries
FOR EACH ROW EXECUTE FUNCTION maru_validate_convention_series_profile_version();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS organizations_series_profile_version_guard
    ON organizations_conventionseries;
DROP FUNCTION IF EXISTS maru_validate_convention_series_profile_version();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0005_conventionseries_profile_version"),
    ]

    operations = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
