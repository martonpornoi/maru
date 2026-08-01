from django.db import migrations

FORWARD_SQL = """
CREATE FUNCTION maru_validate_edition_aggregate_version()
RETURNS trigger AS $$
DECLARE
    profile_changed boolean;
    lifecycle_changed boolean;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.aggregate_version != 1 THEN
            RAISE EXCEPTION 'new editions must start at aggregate version one'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.organization_id IS DISTINCT FROM OLD.organization_id
       OR NEW.series_id IS DISTINCT FROM OLD.series_id
       OR NEW.slug IS DISTINCT FROM OLD.slug
    THEN
        RAISE EXCEPTION 'edition ownership and stable slug are immutable'
            USING ERRCODE = '23514';
    END IF;

    profile_changed :=
        NEW.name IS DISTINCT FROM OLD.name
        OR NEW.time_zone IS DISTINCT FROM OLD.time_zone
        OR NEW.language_codes IS DISTINCT FROM OLD.language_codes
        OR NEW.currency_codes IS DISTINCT FROM OLD.currency_codes
        OR NEW.starts_on IS DISTINCT FROM OLD.starts_on
        OR NEW.ends_on IS DISTINCT FROM OLD.ends_on;
    lifecycle_changed :=
        NEW.lifecycle IS DISTINCT FROM OLD.lifecycle
        OR NEW.lifecycle_version IS DISTINCT FROM OLD.lifecycle_version;

    IF profile_changed AND lifecycle_changed THEN
        RAISE EXCEPTION 'edition profile and lifecycle require separate commands'
            USING ERRCODE = '23514';
    END IF;

    IF profile_changed AND OLD.lifecycle NOT IN ('draft', 'preparing') THEN
        RAISE EXCEPTION 'edition profile is read-only in this lifecycle'
            USING ERRCODE = '23514';
    END IF;

    IF profile_changed OR lifecycle_changed THEN
        IF NEW.aggregate_version != OLD.aggregate_version + 1 THEN
            RAISE EXCEPTION 'edition change must increment aggregate version'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.aggregate_version != OLD.aggregate_version THEN
        RAISE EXCEPTION 'aggregate version changes only with edition facts'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER events_aggregate_version_guard
BEFORE INSERT OR UPDATE
ON events_eventedition
FOR EACH ROW EXECUTE FUNCTION maru_validate_edition_aggregate_version();

CREATE FUNCTION maru_validate_edition_creation_receipt()
RETURNS trigger AS $$
BEGIN
    IF TG_OP != 'INSERT' THEN
        RAISE EXCEPTION 'edition creation receipts are append-only'
            USING ERRCODE = '23514';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM events_eventedition edition
        WHERE edition.id = NEW.edition_id
          AND edition.organization_id = NEW.organization_id
          AND edition.series_id = NEW.series_id
    ) THEN
        RAISE EXCEPTION 'edition creation receipt scope does not match'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER events_edition_creation_receipt_guard
BEFORE INSERT OR UPDATE OR DELETE
ON events_editioncreationreceipt
FOR EACH ROW EXECUTE FUNCTION maru_validate_edition_creation_receipt();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS events_edition_creation_receipt_guard
    ON events_editioncreationreceipt;
DROP FUNCTION IF EXISTS maru_validate_edition_creation_receipt();
DROP TRIGGER IF EXISTS events_aggregate_version_guard ON events_eventedition;
DROP FUNCTION IF EXISTS maru_validate_edition_aggregate_version();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0006_editioncreationreceipt_and_more"),
    ]

    operations = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
