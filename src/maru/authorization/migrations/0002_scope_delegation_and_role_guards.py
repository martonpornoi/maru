from django.db import migrations

FORWARD_SQL = """
CREATE FUNCTION maru_validate_capability_grant()
RETURNS trigger AS $$
DECLARE
    edition_organization uuid;
    parent_record authorization_capabilitygrant%ROWTYPE;
BEGIN
    IF NEW.edition_id IS NOT NULL THEN
        SELECT organization_id INTO edition_organization
          FROM events_eventedition WHERE id = NEW.edition_id;
        IF edition_organization IS NULL
           OR edition_organization != NEW.organization_id
        THEN
            RAISE EXCEPTION 'capability grant edition belongs to another organization'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF NEW.delegated_from_id IS NOT NULL THEN
        SELECT * INTO parent_record
          FROM authorization_capabilitygrant
         WHERE id = NEW.delegated_from_id;

        IF parent_record.id IS NULL
           OR parent_record.principal_id != NEW.granted_by_id
           OR parent_record.capability_code != NEW.capability_code
           OR parent_record.organization_id != NEW.organization_id
           OR (
               parent_record.edition_id IS NOT NULL
               AND parent_record.edition_id IS DISTINCT FROM NEW.edition_id
           )
           OR (
               parent_record.expires_at IS NOT NULL
               AND (
                   NEW.expires_at IS NULL
                   OR NEW.expires_at > parent_record.expires_at
               )
           )
        THEN
            RAISE EXCEPTION 'invalid capability delegation chain'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER authorization_capability_grant_guard
BEFORE INSERT OR UPDATE
ON authorization_capabilitygrant
FOR EACH ROW EXECUTE FUNCTION maru_validate_capability_grant();

CREATE FUNCTION maru_validate_role_assignment()
RETURNS trigger AS $$
DECLARE
    edition_organization uuid;
    bundle_organization uuid;
BEGIN
    SELECT organization_id INTO bundle_organization
      FROM authorization_rolebundle WHERE id = NEW.role_bundle_id;
    IF bundle_organization IS NULL
       OR bundle_organization != NEW.organization_id
    THEN
        RAISE EXCEPTION 'role bundle belongs to another organization'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.edition_id IS NOT NULL THEN
        SELECT organization_id INTO edition_organization
          FROM events_eventedition WHERE id = NEW.edition_id;
        IF edition_organization IS NULL
           OR edition_organization != NEW.organization_id
        THEN
            RAISE EXCEPTION 'role assignment edition belongs to another organization'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER authorization_role_assignment_guard
BEFORE INSERT OR UPDATE
ON authorization_roleassignment
FOR EACH ROW EXECUTE FUNCTION maru_validate_role_assignment();

CREATE FUNCTION maru_prevent_role_bundle_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'role bundle versions are immutable'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER authorization_role_bundle_immutable
BEFORE UPDATE OR DELETE
ON authorization_rolebundle
FOR EACH ROW EXECUTE FUNCTION maru_prevent_role_bundle_mutation();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS authorization_role_bundle_immutable
    ON authorization_rolebundle;
DROP FUNCTION IF EXISTS maru_prevent_role_bundle_mutation();
DROP TRIGGER IF EXISTS authorization_role_assignment_guard
    ON authorization_roleassignment;
DROP FUNCTION IF EXISTS maru_validate_role_assignment();
DROP TRIGGER IF EXISTS authorization_capability_grant_guard
    ON authorization_capabilitygrant;
DROP FUNCTION IF EXISTS maru_validate_capability_grant();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("authorization", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
