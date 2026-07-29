from django.db import migrations

FORWARD_SQL = """
CREATE FUNCTION maru_validate_participation_scope_and_state()
RETURNS trigger AS $$
DECLARE
    edition_organization uuid;
    edition_lifecycle varchar;
BEGIN
    SELECT organization_id, lifecycle
      INTO edition_organization, edition_lifecycle
      FROM events_eventedition
     WHERE id = COALESCE(NEW.edition_id, OLD.edition_id);

    IF edition_organization IS NULL
       OR edition_organization != COALESCE(NEW.organization_id, OLD.organization_id)
    THEN
        RAISE EXCEPTION 'participation organization does not match edition'
            USING ERRCODE = '23514';
    END IF;

    IF edition_lifecycle = 'archived' THEN
        RAISE EXCEPTION 'archived event participation is immutable'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER participation_scope_and_archive_guard
BEFORE INSERT OR UPDATE OR DELETE
ON participation_participation
FOR EACH ROW EXECUTE FUNCTION maru_validate_participation_scope_and_state();

CREATE FUNCTION maru_prevent_archived_capacity_mutation()
RETURNS trigger AS $$
DECLARE
    edition_lifecycle varchar;
BEGIN
    SELECT edition.lifecycle
      INTO edition_lifecycle
      FROM participation_participation participation
      JOIN events_eventedition edition ON edition.id = participation.edition_id
     WHERE participation.id = COALESCE(NEW.participation_id, OLD.participation_id);

    IF edition_lifecycle = 'archived' THEN
        RAISE EXCEPTION 'archived participation capacity is immutable'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER participation_capacity_archive_guard
BEFORE INSERT OR UPDATE OR DELETE
ON participation_participationcapacity
FOR EACH ROW EXECUTE FUNCTION maru_prevent_archived_capacity_mutation();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS participation_capacity_archive_guard
    ON participation_participationcapacity;
DROP FUNCTION IF EXISTS maru_prevent_archived_capacity_mutation();
DROP TRIGGER IF EXISTS participation_scope_and_archive_guard
    ON participation_participation;
DROP FUNCTION IF EXISTS maru_validate_participation_scope_and_state();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("participation", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
