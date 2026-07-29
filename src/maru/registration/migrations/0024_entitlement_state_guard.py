from django.db import migrations


FORWARD_SQL = """
DROP TRIGGER IF EXISTS registration_entitlement_append_guard
    ON registration_entitlement;

CREATE FUNCTION maru_guard_registration_entitlement()
RETURNS trigger AS $$
DECLARE
    registration_organization uuid;
    registration_edition uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'registration entitlements cannot be deleted'
            USING ERRCODE = '23514';
    END IF;

    SELECT organization_id, edition_id
      INTO registration_organization, registration_edition
      FROM registration_registration
     WHERE id = NEW.registration_id;
    IF registration_organization IS NULL
       OR registration_organization != NEW.organization_id
       OR registration_edition != NEW.edition_id
    THEN
        RAISE EXCEPTION 'registration entitlement scope mismatch'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'INSERT' THEN
        RETURN NEW;
    END IF;

    IF OLD.status = 'active'
       AND NEW.status = 'revoked'
       AND (
           to_jsonb(NEW) - ARRAY['status', 'updated_at']
           =
           to_jsonb(OLD) - ARRAY['status', 'updated_at']
       )
    THEN
        RETURN NEW;
    END IF;

    RAISE EXCEPTION 'invalid registration entitlement transition'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER registration_entitlement_state_guard
BEFORE INSERT OR UPDATE OR DELETE
ON registration_entitlement
FOR EACH ROW EXECUTE FUNCTION maru_guard_registration_entitlement();
"""


REVERSE_SQL = """
DROP TRIGGER IF EXISTS registration_entitlement_state_guard
    ON registration_entitlement;
DROP FUNCTION IF EXISTS maru_guard_registration_entitlement();

CREATE TRIGGER registration_entitlement_append_guard
BEFORE INSERT OR UPDATE OR DELETE
ON registration_entitlement
FOR EACH ROW EXECUTE FUNCTION maru_guard_registration_append_record();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("registration", "0023_finance_evidence_integrity_guards"),
    ]

    operations = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
