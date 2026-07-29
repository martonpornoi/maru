from django.db import migrations

FORWARD_SQL = """
CREATE FUNCTION maru_prevent_accreditation_evidence_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'accreditation evidence is append-only'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER accreditation_credential_event_append_only
BEFORE UPDATE OR DELETE ON accreditation_credentialevent
FOR EACH ROW EXECUTE FUNCTION maru_prevent_accreditation_evidence_mutation();

CREATE TRIGGER accreditation_offline_manifest_append_only
BEFORE UPDATE OR DELETE ON accreditation_offlinecredentialmanifest
FOR EACH ROW EXECUTE FUNCTION maru_prevent_accreditation_evidence_mutation();

CREATE TRIGGER accreditation_offline_operation_append_only
BEFORE UPDATE OR DELETE ON accreditation_offlinecheckinoperation
FOR EACH ROW EXECUTE FUNCTION maru_prevent_accreditation_evidence_mutation();

CREATE FUNCTION maru_guard_credential_state()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'credentials are revoked or replaced, never deleted'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.status = 'issued'
       AND NEW.status IN ('revoked', 'replaced')
       AND NEW.revoked_at IS NOT NULL
       AND NEW.revoked_by_id IS NOT NULL
       AND NEW.revocation_reason != ''
       AND (
           to_jsonb(NEW)
               - ARRAY[
                   'status', 'revoked_at', 'revoked_by_id',
                   'revocation_reason', 'updated_at'
               ]
           =
           to_jsonb(OLD)
               - ARRAY[
                   'status', 'revoked_at', 'revoked_by_id',
                   'revocation_reason', 'updated_at'
               ]
       )
    THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'invalid credential transition'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER accreditation_credential_state_guard
BEFORE UPDATE OR DELETE ON accreditation_credential
FOR EACH ROW EXECUTE FUNCTION maru_guard_credential_state();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS accreditation_credential_state_guard
    ON accreditation_credential;
DROP FUNCTION IF EXISTS maru_guard_credential_state();
DROP TRIGGER IF EXISTS accreditation_offline_operation_append_only
    ON accreditation_offlinecheckinoperation;
DROP TRIGGER IF EXISTS accreditation_offline_manifest_append_only
    ON accreditation_offlinecredentialmanifest;
DROP TRIGGER IF EXISTS accreditation_credential_event_append_only
    ON accreditation_credentialevent;
DROP FUNCTION IF EXISTS maru_prevent_accreditation_evidence_mutation();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("accreditation", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
