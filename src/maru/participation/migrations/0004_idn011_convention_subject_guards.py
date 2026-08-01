from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION maru_guard_participation_idn011_subject()
RETURNS trigger AS $$
DECLARE
    subject_kind varchar;
BEGIN
    SELECT account_kind INTO subject_kind
      FROM identity_account
     WHERE id = NEW.account_id
     FOR UPDATE;

    IF subject_kind IS DISTINCT FROM 'person' THEN
        RAISE EXCEPTION
            'platform accounts cannot hold edition participation'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER participation_idn011_subject_guard
BEFORE INSERT OR UPDATE
ON participation_participation
FOR EACH ROW EXECUTE FUNCTION maru_guard_participation_idn011_subject();

CREATE FUNCTION maru_deferred_validate_participation_idn011_account()
RETURNS trigger AS $$
BEGIN
    IF NEW.account_kind IS DISTINCT FROM 'person'
       AND EXISTS (
           SELECT 1
             FROM participation_participation
            WHERE account_id = NEW.id
       )
    THEN
        RAISE EXCEPTION
            'platform account cannot retain edition participation'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER identity_idn011_participation_subject_guard
AFTER UPDATE OF account_kind
ON identity_account
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION maru_deferred_validate_participation_idn011_account();

DO $$
DECLARE
    invalid_participation_count bigint;
BEGIN
    SELECT COUNT(*) INTO invalid_participation_count
      FROM participation_participation AS participation
      JOIN identity_account AS subject
        ON subject.id = participation.account_id
     WHERE subject.account_kind IS DISTINCT FROM 'person';

    IF invalid_participation_count > 0 THEN
        RAISE EXCEPTION
            'cannot install IDN-011 participation guards: participations %',
            invalid_participation_count
            USING ERRCODE = '23514';
    END IF;
END;
$$;
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS identity_idn011_participation_subject_guard
    ON identity_account;
DROP FUNCTION IF EXISTS maru_deferred_validate_participation_idn011_account();
DROP TRIGGER IF EXISTS participation_idn011_subject_guard
    ON participation_participation;
DROP FUNCTION IF EXISTS maru_guard_participation_idn011_subject();
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("identity", "0010_account_kind"),
        ("participation", "0003_alter_participationcapacity_options"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
