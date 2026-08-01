from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION maru_guard_organizations_idn011_subject()
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
            'platform accounts cannot be organization subjects'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER organizations_idn011_membership_subject_guard
BEFORE INSERT OR UPDATE
ON organizations_organizationmembership
FOR EACH ROW EXECUTE FUNCTION maru_guard_organizations_idn011_subject();

CREATE TRIGGER organizations_idn011_appointment_subject_guard
BEFORE INSERT OR UPDATE
ON organizations_representationappointment
FOR EACH ROW EXECUTE FUNCTION maru_guard_organizations_idn011_subject();

CREATE FUNCTION maru_deferred_validate_organizations_idn011_account()
RETURNS trigger AS $$
BEGIN
    IF NEW.account_kind IS DISTINCT FROM 'person'
       AND (
           EXISTS (
               SELECT 1
                 FROM organizations_organizationmembership
                WHERE account_id = NEW.id
           )
           OR EXISTS (
               SELECT 1
                 FROM organizations_representationappointment
                WHERE account_id = NEW.id
           )
       )
    THEN
        RAISE EXCEPTION
            'platform account cannot retain organization subjects'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER identity_idn011_organizations_subject_guard
AFTER UPDATE OF account_kind
ON identity_account
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION maru_deferred_validate_organizations_idn011_account();

DO $$
DECLARE
    invalid_membership_count bigint;
    invalid_appointment_count bigint;
BEGIN
    SELECT COUNT(*) INTO invalid_membership_count
      FROM organizations_organizationmembership AS membership
      JOIN identity_account AS subject
        ON subject.id = membership.account_id
     WHERE subject.account_kind IS DISTINCT FROM 'person';

    SELECT COUNT(*) INTO invalid_appointment_count
      FROM organizations_representationappointment AS appointment
      JOIN identity_account AS subject
        ON subject.id = appointment.account_id
     WHERE subject.account_kind IS DISTINCT FROM 'person';

    IF invalid_membership_count > 0 OR invalid_appointment_count > 0 THEN
        RAISE EXCEPTION
            'cannot install IDN-011 organization guards: memberships %, appointments %',
            invalid_membership_count,
            invalid_appointment_count
            USING ERRCODE = '23514';
    END IF;
END;
$$;
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS identity_idn011_organizations_subject_guard
    ON identity_account;
DROP FUNCTION IF EXISTS maru_deferred_validate_organizations_idn011_account();
DROP TRIGGER IF EXISTS organizations_idn011_appointment_subject_guard
    ON organizations_representationappointment;
DROP TRIGGER IF EXISTS organizations_idn011_membership_subject_guard
    ON organizations_organizationmembership;
DROP FUNCTION IF EXISTS maru_guard_organizations_idn011_subject();
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("identity", "0010_account_kind"),
        ("organizations", "0011_emergency_controller_removal_integrity"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
