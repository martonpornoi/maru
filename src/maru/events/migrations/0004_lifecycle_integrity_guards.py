from django.db import migrations

FORWARD_SQL = """
CREATE FUNCTION maru_validate_edition_lifecycle_version()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.lifecycle != 'draft' OR NEW.lifecycle_version != 0 THEN
            RAISE EXCEPTION 'new editions must start at draft lifecycle version zero'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.lifecycle = OLD.lifecycle THEN
        IF NEW.lifecycle_version != OLD.lifecycle_version THEN
            RAISE EXCEPTION 'lifecycle version changes only with lifecycle'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.lifecycle_version != OLD.lifecycle_version + 1 THEN
        RAISE EXCEPTION 'lifecycle change must increment lifecycle version'
            USING ERRCODE = '23514';
    END IF;

    IF (OLD.lifecycle = 'draft' AND NEW.lifecycle IN ('preparing', 'cancelled'))
       OR (
           OLD.lifecycle = 'preparing'
           AND NEW.lifecycle IN ('draft', 'ready', 'cancelled')
       )
       OR (
           OLD.lifecycle = 'ready'
           AND NEW.lifecycle IN ('preparing', 'live', 'cancelled')
       )
       OR (OLD.lifecycle = 'live' AND NEW.lifecycle = 'closing')
       OR (OLD.lifecycle = 'closing' AND NEW.lifecycle = 'archived')
    THEN
        RETURN NEW;
    END IF;

    RAISE EXCEPTION 'invalid event edition lifecycle transition'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER events_lifecycle_version_guard
BEFORE INSERT OR UPDATE OF lifecycle, lifecycle_version
ON events_eventedition
FOR EACH ROW EXECUTE FUNCTION maru_validate_edition_lifecycle_version();

CREATE FUNCTION maru_prevent_lifecycle_transition_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'edition lifecycle transitions are append-only'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER events_lifecycle_transition_append_only
BEFORE UPDATE OR DELETE
ON events_editionlifecycletransition
FOR EACH ROW EXECUTE FUNCTION maru_prevent_lifecycle_transition_mutation();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS events_lifecycle_transition_append_only
    ON events_editionlifecycletransition;
DROP FUNCTION IF EXISTS maru_prevent_lifecycle_transition_mutation();
DROP TRIGGER IF EXISTS events_lifecycle_version_guard
    ON events_eventedition;
DROP FUNCTION IF EXISTS maru_validate_edition_lifecycle_version();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0003_eventedition_lifecycle_version"),
    ]

    operations = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
