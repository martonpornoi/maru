from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION maru_guard_registration_idn011_subject()
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
            'platform accounts cannot hold registration subject records'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER idn011_registration_subject_guard
BEFORE INSERT OR UPDATE
ON registration_registration
FOR EACH ROW EXECUTE FUNCTION maru_guard_registration_idn011_subject();

CREATE TRIGGER idn011_attendee_profile_subject_guard
BEFORE INSERT OR UPDATE
ON registration_attendeeregistrationprofile
FOR EACH ROW EXECUTE FUNCTION maru_guard_registration_idn011_subject();

CREATE TRIGGER idn011_attendee_fursuit_subject_guard
BEFORE INSERT OR UPDATE
ON registration_attendeefursuit
FOR EACH ROW EXECUTE FUNCTION maru_guard_registration_idn011_subject();

CREATE FUNCTION maru_deferred_validate_registration_idn011_account()
RETURNS trigger AS $$
BEGIN
    IF NEW.account_kind IS DISTINCT FROM 'person'
       AND (
           EXISTS (
               SELECT 1
                 FROM registration_registration
                WHERE account_id = NEW.id
           )
           OR EXISTS (
               SELECT 1
                 FROM registration_attendeeregistrationprofile
                WHERE account_id = NEW.id
           )
           OR EXISTS (
               SELECT 1
                 FROM registration_attendeefursuit
                WHERE account_id = NEW.id
           )
       )
    THEN
        RAISE EXCEPTION
            'platform account cannot retain registration subject records'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER identity_idn011_registration_subject_guard
AFTER UPDATE OF account_kind
ON identity_account
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION maru_deferred_validate_registration_idn011_account();

DO $$
DECLARE
    invalid_registration_count bigint;
    invalid_profile_count bigint;
    invalid_fursuit_count bigint;
BEGIN
    SELECT COUNT(*) INTO invalid_registration_count
      FROM registration_registration AS registration
      JOIN identity_account AS subject
        ON subject.id = registration.account_id
     WHERE subject.account_kind IS DISTINCT FROM 'person';

    SELECT COUNT(*) INTO invalid_profile_count
      FROM registration_attendeeregistrationprofile AS profile
      JOIN identity_account AS subject
        ON subject.id = profile.account_id
     WHERE subject.account_kind IS DISTINCT FROM 'person';

    SELECT COUNT(*) INTO invalid_fursuit_count
      FROM registration_attendeefursuit AS fursuit
      JOIN identity_account AS subject
        ON subject.id = fursuit.account_id
     WHERE subject.account_kind IS DISTINCT FROM 'person';

    IF invalid_registration_count > 0
       OR invalid_profile_count > 0
       OR invalid_fursuit_count > 0
    THEN
        RAISE EXCEPTION
            'IDN-011 registration blockers: registrations %, profiles %, fursuits %',
            invalid_registration_count,
            invalid_profile_count,
            invalid_fursuit_count
            USING ERRCODE = '23514';
    END IF;
END;
$$;
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS identity_idn011_registration_subject_guard
    ON identity_account;
DROP FUNCTION IF EXISTS maru_deferred_validate_registration_idn011_account();
DROP TRIGGER IF EXISTS idn011_attendee_fursuit_subject_guard
    ON registration_attendeefursuit;
DROP TRIGGER IF EXISTS idn011_attendee_profile_subject_guard
    ON registration_attendeeregistrationprofile;
DROP TRIGGER IF EXISTS idn011_registration_subject_guard
    ON registration_registration;
DROP FUNCTION IF EXISTS maru_guard_registration_idn011_subject();
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("identity", "0010_account_kind"),
        ("registration", "0030_profile_extension_provenance_guard"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
