from django.db import migrations

FORWARD_SQL = """
CREATE FUNCTION maru_guard_account_security_event()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'account security history is append-only'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER identity_security_event_append_only
BEFORE UPDATE OR DELETE
ON identity_accountsecurityevent
FOR EACH ROW EXECUTE FUNCTION maru_guard_account_security_event();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS identity_security_event_append_only
    ON identity_accountsecurityevent;
DROP FUNCTION IF EXISTS maru_guard_account_security_event();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0003_accountsecurityevent"),
    ]

    operations = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
