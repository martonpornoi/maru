from django.db import migrations

FORWARD_SQL = """
CREATE FUNCTION maru_validate_edition_scope()
RETURNS trigger AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM organizations_conventionseries series
        WHERE series.id = NEW.series_id
          AND series.organization_id = NEW.organization_id
    ) THEN
        RAISE EXCEPTION 'event edition organization does not match series'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER events_edition_scope_guard
BEFORE INSERT OR UPDATE OF organization_id, series_id
ON events_eventedition
FOR EACH ROW EXECUTE FUNCTION maru_validate_edition_scope();

CREATE FUNCTION maru_prevent_archived_edition_mutation()
RETURNS trigger AS $$
BEGIN
    IF OLD.lifecycle = 'archived' THEN
        RAISE EXCEPTION 'archived event editions are immutable'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER events_archived_edition_guard
BEFORE UPDATE OR DELETE
ON events_eventedition
FOR EACH ROW EXECUTE FUNCTION maru_prevent_archived_edition_mutation();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS events_archived_edition_guard ON events_eventedition;
DROP FUNCTION IF EXISTS maru_prevent_archived_edition_mutation();
DROP TRIGGER IF EXISTS events_edition_scope_guard ON events_eventedition;
DROP FUNCTION IF EXISTS maru_validate_edition_scope();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
