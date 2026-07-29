from django.db import migrations

FORWARD_SQL = """
CREATE FUNCTION maru_guard_audit_event()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'audit events are append-only'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'INSERT' THEN
        IF NEW.integrity_batch_id IS NOT NULL THEN
            RAISE EXCEPTION 'new audit events cannot join a sealed batch'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.integrity_batch_id IS NULL
       AND NEW.integrity_batch_id IS NOT NULL
       AND (
           to_jsonb(NEW) - 'integrity_batch_id'
           = to_jsonb(OLD) - 'integrity_batch_id'
       )
    THEN
        RETURN NEW;
    END IF;

    RAISE EXCEPTION 'audit events are append-only'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_event_append_only
BEFORE INSERT OR UPDATE OR DELETE
ON audit_auditevent
FOR EACH ROW EXECUTE FUNCTION maru_guard_audit_event();

CREATE FUNCTION maru_guard_audit_integrity_batch()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit integrity batches are immutable'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_integrity_batch_immutable
BEFORE UPDATE OR DELETE
ON audit_auditintegritybatch
FOR EACH ROW EXECUTE FUNCTION maru_guard_audit_integrity_batch();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS audit_integrity_batch_immutable
    ON audit_auditintegritybatch;
DROP FUNCTION IF EXISTS maru_guard_audit_integrity_batch();
DROP TRIGGER IF EXISTS audit_event_append_only
    ON audit_auditevent;
DROP FUNCTION IF EXISTS maru_guard_audit_event();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
