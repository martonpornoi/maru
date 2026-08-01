from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION maru_guard_capability_grant_subject()
RETURNS trigger AS $$
DECLARE
    principal_kind varchar;
BEGIN
    SELECT account_kind INTO principal_kind
      FROM identity_account
     WHERE id = NEW.principal_id;
    IF principal_kind IS DISTINCT FROM 'person' THEN
        RAISE EXCEPTION 'platform accounts cannot receive convention capability grants'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER authorization_capability_grant_subject_guard
BEFORE INSERT OR UPDATE
ON authorization_capabilitygrant
FOR EACH ROW EXECUTE FUNCTION maru_guard_capability_grant_subject();

CREATE FUNCTION maru_deferred_validate_platform_authority_principal()
RETURNS trigger AS $$
BEGIN
    IF NEW.account_kind = 'platform_administrator'
       AND (
           EXISTS (
               SELECT 1
                 FROM authorization_capabilitygrant
                WHERE principal_id = NEW.id
           )
           OR EXISTS (
               SELECT 1
                 FROM authorization_roleassignment
                WHERE principal_id = NEW.id
           )
       )
    THEN
        RAISE EXCEPTION 'platform account cannot retain convention authority'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER identity_platform_authority_principal_guard
AFTER UPDATE OF account_kind
ON identity_account
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION maru_deferred_validate_platform_authority_principal();

CREATE FUNCTION maru_assert_active_board_membership_provenance(
    target_representation_id uuid
)
RETURNS void AS $$
DECLARE
    representation_organization_id uuid;
    representation_state varchar;
BEGIN
    SELECT organization_id, state
      INTO representation_organization_id, representation_state
      FROM organizations_organizationrepresentation
     WHERE id = target_representation_id;

    IF NOT FOUND OR representation_state != 'active' THEN
        RETURN;
    END IF;

    IF EXISTS (
        SELECT 1
          FROM organizations_representationappointment AS appointment
         WHERE appointment.representation_id = target_representation_id
           AND appointment.state = 'active'
           AND NOT EXISTS (
               SELECT 1
                 FROM organizations_organizationmembership AS membership
                WHERE membership.organization_id = representation_organization_id
                  AND membership.account_id = appointment.account_id
                  AND membership.state = 'active'
                  AND membership.relationship_label =
                      'Executive Board controller'
                  AND membership.started_at IS NOT NULL
                  AND membership.ended_at IS NULL
           )
    ) THEN
        RAISE EXCEPTION 'active Executive Board membership evidence is incomplete'
            USING ERRCODE = '23514';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM organizations_organizationmembership AS membership
         WHERE membership.organization_id = representation_organization_id
           AND membership.state = 'active'
           AND membership.relationship_label = 'Executive Board controller'
           AND NOT EXISTS (
               SELECT 1
                 FROM organizations_representationappointment AS appointment
                WHERE appointment.representation_id = target_representation_id
                  AND appointment.account_id = membership.account_id
                  AND appointment.state = 'active'
           )
    ) THEN
        RAISE EXCEPTION 'active Executive Board membership lacks an active appointment'
            USING ERRCODE = '23514';
    END IF;
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION maru_deferred_validate_board_membership_from_representation()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM maru_assert_active_board_membership_provenance(OLD.id);
    ELSE
        PERFORM maru_assert_active_board_membership_provenance(NEW.id);
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER organizations_representation_membership_provenance
AFTER INSERT OR UPDATE OR DELETE
ON organizations_organizationrepresentation
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION maru_deferred_validate_board_membership_from_representation();

CREATE FUNCTION maru_deferred_validate_board_membership_from_appointment()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM maru_assert_active_board_membership_provenance(
            OLD.representation_id
        );
    ELSE
        PERFORM maru_assert_active_board_membership_provenance(
            NEW.representation_id
        );
        IF TG_OP = 'UPDATE'
           AND OLD.representation_id IS DISTINCT FROM NEW.representation_id
        THEN
            PERFORM maru_assert_active_board_membership_provenance(
                OLD.representation_id
            );
        END IF;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER organizations_appointment_membership_provenance
AFTER INSERT OR UPDATE OR DELETE
ON organizations_representationappointment
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION maru_deferred_validate_board_membership_from_appointment();

CREATE FUNCTION maru_deferred_validate_board_membership()
RETURNS trigger AS $$
DECLARE
    membership_organization_id uuid;
    target_representation_id uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        membership_organization_id := OLD.organization_id;
    ELSE
        membership_organization_id := NEW.organization_id;
    END IF;

    FOR target_representation_id IN
        SELECT representation.id
          FROM organizations_organizationrepresentation AS representation
         WHERE representation.organization_id = membership_organization_id
           AND representation.state = 'active'
    LOOP
        PERFORM maru_assert_active_board_membership_provenance(
            target_representation_id
        );
    END LOOP;

    IF TG_OP = 'UPDATE'
       AND OLD.organization_id IS DISTINCT FROM NEW.organization_id
    THEN
        FOR target_representation_id IN
            SELECT representation.id
              FROM organizations_organizationrepresentation AS representation
             WHERE representation.organization_id = OLD.organization_id
               AND representation.state = 'active'
        LOOP
            PERFORM maru_assert_active_board_membership_provenance(
                target_representation_id
            );
        END LOOP;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER organizations_membership_board_provenance
AFTER INSERT OR UPDATE OR DELETE
ON organizations_organizationmembership
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION maru_deferred_validate_board_membership();

DO $$
DECLARE
    invalid_platform_grant_count integer;
    invalid_platform_assignment_count integer;
    invalid_provisioning_subject_count integer;
    active_representation_id uuid;
BEGIN
    SELECT COUNT(*) INTO invalid_platform_grant_count
      FROM authorization_capabilitygrant AS grant_record
      JOIN identity_account AS principal
        ON principal.id = grant_record.principal_id
     WHERE principal.account_kind = 'platform_administrator';

    SELECT COUNT(*) INTO invalid_platform_assignment_count
      FROM authorization_roleassignment AS assignment
      JOIN identity_account AS principal
        ON principal.id = assignment.principal_id
     WHERE principal.account_kind = 'platform_administrator';

    IF invalid_platform_grant_count > 0
       OR invalid_platform_assignment_count > 0
    THEN
        RAISE EXCEPTION
            'cannot harden: % platform grants and % platform assignments exist',
            invalid_platform_grant_count,
            invalid_platform_assignment_count
            USING ERRCODE = '23514';
    END IF;

    SELECT COUNT(*) INTO invalid_provisioning_subject_count
      FROM organizations_representationappointment AS appointment
      JOIN organizations_organizationrepresentation AS representation
        ON representation.id = appointment.representation_id
      JOIN identity_account AS subject
        ON subject.id = appointment.account_id
     WHERE representation.state = 'provisioning'
       AND appointment.state IN ('invited', 'accepted')
       AND (
           subject.account_kind != 'person'
           OR NOT subject.is_active
           OR subject.email_verified_at IS NULL
       );

    IF invalid_provisioning_subject_count > 0 THEN
        RAISE EXCEPTION
            'cannot harden authority: % ineligible provisioning appointments exist',
            invalid_provisioning_subject_count
            USING ERRCODE = '23514';
    END IF;

    FOR active_representation_id IN
        SELECT id
          FROM organizations_organizationrepresentation
         WHERE state = 'active'
    LOOP
        PERFORM maru_assert_active_board_membership_provenance(
            active_representation_id
        );
    END LOOP;
END;
$$;
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS organizations_membership_board_provenance
    ON organizations_organizationmembership;
DROP FUNCTION IF EXISTS maru_deferred_validate_board_membership();
DROP TRIGGER IF EXISTS organizations_appointment_membership_provenance
    ON organizations_representationappointment;
DROP FUNCTION IF EXISTS maru_deferred_validate_board_membership_from_appointment();
DROP TRIGGER IF EXISTS organizations_representation_membership_provenance
    ON organizations_organizationrepresentation;
DROP FUNCTION IF EXISTS maru_deferred_validate_board_membership_from_representation();
DROP FUNCTION IF EXISTS maru_assert_active_board_membership_provenance(uuid);
DROP TRIGGER IF EXISTS identity_platform_authority_principal_guard
    ON identity_account;
DROP FUNCTION IF EXISTS maru_deferred_validate_platform_authority_principal();
DROP TRIGGER IF EXISTS authorization_capability_grant_subject_guard
    ON authorization_capabilitygrant;
DROP FUNCTION IF EXISTS maru_guard_capability_grant_subject();
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("organizations", "0009_executive_board_integrity_guards"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
