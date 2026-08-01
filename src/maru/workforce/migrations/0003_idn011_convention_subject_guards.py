from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION maru_guard_workforce_idn011_subject()
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
            'platform accounts cannot hold workforce subject records'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER workforce_idn011_application_subject_guard
BEFORE INSERT OR UPDATE
ON workforce_volunteerapplication
FOR EACH ROW EXECUTE FUNCTION maru_guard_workforce_idn011_subject();

CREATE TRIGGER workforce_idn011_document_request_subject_guard
BEFORE INSERT OR UPDATE
ON workforce_onboardingdocumentrequest
FOR EACH ROW EXECUTE FUNCTION maru_guard_workforce_idn011_subject();

CREATE TRIGGER workforce_idn011_assignment_subject_guard
BEFORE INSERT OR UPDATE
ON workforce_positionassignment
FOR EACH ROW EXECUTE FUNCTION maru_guard_workforce_idn011_subject();

CREATE FUNCTION maru_deferred_validate_workforce_idn011_account()
RETURNS trigger AS $$
BEGIN
    IF NEW.account_kind IS DISTINCT FROM 'person'
       AND (
           EXISTS (
               SELECT 1
                 FROM workforce_volunteerapplication
                WHERE account_id = NEW.id
           )
           OR EXISTS (
               SELECT 1
                 FROM workforce_onboardingdocumentrequest
                WHERE account_id = NEW.id
           )
           OR EXISTS (
               SELECT 1
                 FROM workforce_positionassignment
                WHERE account_id = NEW.id
           )
       )
    THEN
        RAISE EXCEPTION
            'platform account cannot retain workforce subject records'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER identity_idn011_workforce_subject_guard
AFTER UPDATE OF account_kind
ON identity_account
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION maru_deferred_validate_workforce_idn011_account();

DO $$
DECLARE
    invalid_application_count bigint;
    invalid_document_request_count bigint;
    invalid_assignment_count bigint;
BEGIN
    SELECT COUNT(*) INTO invalid_application_count
      FROM workforce_volunteerapplication AS application
      JOIN identity_account AS subject
        ON subject.id = application.account_id
     WHERE subject.account_kind IS DISTINCT FROM 'person';

    SELECT COUNT(*) INTO invalid_document_request_count
      FROM workforce_onboardingdocumentrequest AS document_request
      JOIN identity_account AS subject
        ON subject.id = document_request.account_id
     WHERE subject.account_kind IS DISTINCT FROM 'person';

    SELECT COUNT(*) INTO invalid_assignment_count
      FROM workforce_positionassignment AS assignment
      JOIN identity_account AS subject
        ON subject.id = assignment.account_id
     WHERE subject.account_kind IS DISTINCT FROM 'person';

    IF invalid_application_count > 0
       OR invalid_document_request_count > 0
       OR invalid_assignment_count > 0
    THEN
        RAISE EXCEPTION
            'IDN-011 workforce blockers: applications %, onboarding %, assignments %',
            invalid_application_count,
            invalid_document_request_count,
            invalid_assignment_count
            USING ERRCODE = '23514';
    END IF;
END;
$$;
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS identity_idn011_workforce_subject_guard
    ON identity_account;
DROP FUNCTION IF EXISTS maru_deferred_validate_workforce_idn011_account();
DROP TRIGGER IF EXISTS workforce_idn011_assignment_subject_guard
    ON workforce_positionassignment;
DROP TRIGGER IF EXISTS workforce_idn011_document_request_subject_guard
    ON workforce_onboardingdocumentrequest;
DROP TRIGGER IF EXISTS workforce_idn011_application_subject_guard
    ON workforce_volunteerapplication;
DROP FUNCTION IF EXISTS maru_guard_workforce_idn011_subject();
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("identity", "0010_account_kind"),
        ("workforce", "0002_integrity_guards"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
