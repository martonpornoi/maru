from django.db import migrations


FORWARD_SQL = """
CREATE OR REPLACE FUNCTION maru_validate_edition_creation_receipt()
RETURNS trigger AS $$
BEGIN
    IF TG_OP != 'INSERT' THEN
        RAISE EXCEPTION 'edition creation receipts are append-only'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.request_digest !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'edition creation receipt digest must be lowercase SHA-256'
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
"""

REVERSE_SQL = """
CREATE OR REPLACE FUNCTION maru_validate_edition_creation_receipt()
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
"""


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0007_edition_creation_integrity_guards"),
    ]

    operations = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
