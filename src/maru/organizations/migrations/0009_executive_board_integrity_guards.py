from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION maru_guard_representation_identity()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'organization representation history is durable'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'INSERT' THEN
        IF NEW.aggregate_version != 1 THEN
            RAISE EXCEPTION 'organization representation must start at version 1'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
       OR NEW.code IS DISTINCT FROM OLD.code
       OR NEW.name IS DISTINCT FROM OLD.name
       OR NEW.provisioned_by_id IS DISTINCT FROM OLD.provisioned_by_id
       OR NEW.provisioning_reason IS DISTINCT FROM OLD.provisioning_reason
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION 'organization representation identity is immutable'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.activated_by_id IS NOT NULL
       AND (
           NEW.activated_by_id IS DISTINCT FROM OLD.activated_by_id
           OR NEW.activated_at IS DISTINCT FROM OLD.activated_at
           OR NEW.activation_reason IS DISTINCT FROM OLD.activation_reason
       )
    THEN
        RAISE EXCEPTION 'organization representation activation provenance is immutable'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.activated_by_id IS NULL
       AND NEW.activated_by_id IS NOT NULL
       AND NOT (OLD.state = 'provisioning' AND NEW.state = 'active')
    THEN
        RAISE EXCEPTION 'activation provenance requires the activation transition'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.aggregate_version < OLD.aggregate_version
       OR NEW.aggregate_version > OLD.aggregate_version + 1
    THEN
        RAISE EXCEPTION 'invalid organization representation aggregate version'
            USING ERRCODE = '23514';
    END IF;

    IF (
        NEW.state IS DISTINCT FROM OLD.state
        OR NEW.activated_by_id IS DISTINCT FROM OLD.activated_by_id
        OR NEW.activated_at IS DISTINCT FROM OLD.activated_at
        OR NEW.activation_reason IS DISTINCT FROM OLD.activation_reason
       )
       AND NEW.aggregate_version != OLD.aggregate_version + 1
    THEN
        RAISE EXCEPTION 'representation change must advance aggregate version once'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER organizations_representation_identity_guard
BEFORE INSERT OR UPDATE OR DELETE
ON organizations_organizationrepresentation
FOR EACH ROW EXECUTE FUNCTION maru_guard_representation_identity();

CREATE FUNCTION maru_guard_representation_appointment_identity()
RETURNS trigger AS $$
DECLARE
    parent_state varchar;
    parent_lifecycle varchar;
    subject_kind varchar;
    subject_active boolean;
    subject_verified_at timestamptz;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'representation appointment history is durable'
            USING ERRCODE = '23514';
    END IF;

    SELECT representation.state, organization.lifecycle
      INTO parent_state, parent_lifecycle
      FROM organizations_organizationrepresentation AS representation
      JOIN organizations_organization AS organization
        ON organization.id = representation.organization_id
     WHERE representation.id = NEW.representation_id;

    SELECT account_kind, is_active, email_verified_at
      INTO subject_kind, subject_active, subject_verified_at
      FROM identity_account
     WHERE id = NEW.account_id;

    IF subject_kind IS DISTINCT FROM 'person'
       OR subject_active IS DISTINCT FROM TRUE
       OR subject_verified_at IS NULL
    THEN
        RAISE EXCEPTION 'representation appointment requires an eligible person'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'INSERT' THEN
        IF NEW.state != 'invited'
           OR NEW.invitation_version != 1
           OR NEW.role_assignment_id IS NOT NULL
           OR parent_state IS DISTINCT FROM 'provisioning'
           OR parent_lifecycle IS DISTINCT FROM 'draft'
        THEN
            RAISE EXCEPTION 'invalid initial representation appointment'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.representation_id IS DISTINCT FROM OLD.representation_id
       OR NEW.account_id IS DISTINCT FROM OLD.account_id
       OR NEW.role IS DISTINCT FROM OLD.role
       OR NEW.invited_by_id IS DISTINCT FROM OLD.invited_by_id
       OR NEW.invited_at IS DISTINCT FROM OLD.invited_at
       OR NEW.reason IS DISTINCT FROM OLD.reason
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION 'representation appointment identity is immutable'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.responded_at IS NOT NULL
       AND NEW.responded_at IS DISTINCT FROM OLD.responded_at
    THEN
        RAISE EXCEPTION 'representation response provenance is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.activated_at IS NOT NULL
       AND NEW.activated_at IS DISTINCT FROM OLD.activated_at
    THEN
        RAISE EXCEPTION 'representation appointment activation is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.ended_at IS NOT NULL
       AND NEW.ended_at IS DISTINCT FROM OLD.ended_at
    THEN
        RAISE EXCEPTION 'representation appointment end provenance is immutable'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.state IS DISTINCT FROM OLD.state
       AND NOT (
           (OLD.state = 'invited' AND NEW.state IN ('accepted', 'declined'))
           OR (OLD.state = 'accepted' AND NEW.state = 'active')
           OR (OLD.state = 'active' AND NEW.state = 'ended')
       )
    THEN
        RAISE EXCEPTION 'invalid representation appointment transition'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.role_assignment_id IS DISTINCT FROM OLD.role_assignment_id
       AND NOT (
           OLD.state = 'accepted'
           AND NEW.state = 'active'
           AND OLD.role_assignment_id IS NULL
           AND NEW.role_assignment_id IS NOT NULL
       )
    THEN
        RAISE EXCEPTION 'representation assignment link is immutable'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.invitation_version < OLD.invitation_version
       OR NEW.invitation_version > OLD.invitation_version + 1
    THEN
        RAISE EXCEPTION 'invalid representation invitation version'
            USING ERRCODE = '23514';
    END IF;

    IF (
        NEW.state IS DISTINCT FROM OLD.state
        OR NEW.responded_at IS DISTINCT FROM OLD.responded_at
        OR NEW.activated_at IS DISTINCT FROM OLD.activated_at
        OR NEW.ended_at IS DISTINCT FROM OLD.ended_at
        OR NEW.role_assignment_id IS DISTINCT FROM OLD.role_assignment_id
       )
       AND NEW.invitation_version != OLD.invitation_version + 1
    THEN
        RAISE EXCEPTION 'appointment change must advance invitation version once'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER organizations_representation_appointment_identity_guard
BEFORE INSERT OR UPDATE OR DELETE
ON organizations_representationappointment
FOR EACH ROW EXECUTE FUNCTION maru_guard_representation_appointment_identity();

CREATE FUNCTION maru_guard_role_assignment_subject_and_provenance()
RETURNS trigger AS $$
DECLARE
    principal_kind varchar;
    linked_to_representation boolean;
BEGIN
    SELECT account_kind INTO principal_kind
      FROM identity_account
     WHERE id = NEW.principal_id;
    IF principal_kind IS DISTINCT FROM 'person' THEN
        RAISE EXCEPTION 'platform accounts cannot receive convention roles'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'UPDATE' THEN
        SELECT EXISTS (
            SELECT 1
              FROM organizations_representationappointment
             WHERE role_assignment_id = OLD.id
        ) INTO linked_to_representation;

        IF linked_to_representation
           AND (
               NEW.id IS DISTINCT FROM OLD.id
               OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
               OR NEW.edition_id IS DISTINCT FROM OLD.edition_id
               OR NEW.principal_id IS DISTINCT FROM OLD.principal_id
               OR NEW.role_bundle_id IS DISTINCT FROM OLD.role_bundle_id
               OR NEW.effective_from IS DISTINCT FROM OLD.effective_from
               OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
               OR NEW.granted_by_id IS DISTINCT FROM OLD.granted_by_id
               OR NEW.approved_by_id IS DISTINCT FROM OLD.approved_by_id
               OR NEW.reason IS DISTINCT FROM OLD.reason
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
           )
        THEN
            RAISE EXCEPTION 'linked Executive Board assignment provenance is immutable'
                USING ERRCODE = '23514';
        END IF;

        IF linked_to_representation
           AND OLD.revoked_at IS NOT NULL
           AND (
               NEW.revoked_at IS DISTINCT FROM OLD.revoked_at
               OR NEW.revoked_by_id IS DISTINCT FROM OLD.revoked_by_id
               OR NEW.revocation_reason IS DISTINCT FROM OLD.revocation_reason
           )
        THEN
            RAISE EXCEPTION 'Executive Board revocation provenance is immutable'
                USING ERRCODE = '23514';
        END IF;

        IF linked_to_representation
           AND (
               (NEW.revoked_at IS NULL AND (
                   NEW.revoked_by_id IS NOT NULL OR NEW.revocation_reason != ''
               ))
               OR (NEW.revoked_at IS NOT NULL AND (
                   NEW.revoked_by_id IS NULL OR NEW.revocation_reason = ''
               ))
           )
        THEN
            RAISE EXCEPTION 'Executive Board revocation evidence is incomplete'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER authorization_role_assignment_subject_and_provenance_guard
BEFORE INSERT OR UPDATE
ON authorization_roleassignment
FOR EACH ROW EXECUTE FUNCTION maru_guard_role_assignment_subject_and_provenance();

CREATE FUNCTION maru_assert_active_executive_board(target_representation_id uuid)
RETURNS void AS $$
DECLARE
    representation_organization_id uuid;
    representation_state varchar;
    organization_lifecycle varchar;
    representation_activated_by_id uuid;
    representation_activated_at timestamptz;
    representation_activation_reason varchar;
    representation_aggregate_version integer;
    reserved_bundle_id uuid;
    reserved_bundle_count integer;
    reserved_bundle_version integer;
    reserved_bundle_name varchar;
    reserved_bundle_capabilities varchar[];
    reserved_bundle_created_by_id uuid;
    reserved_bundle_approved_by_id uuid;
    reserved_bundle_reason varchar;
    active_controller_count integer;
    activation_audit_id uuid;
    activation_correlation_id uuid;
BEGIN
    SELECT representation.organization_id,
           representation.state,
           organization.lifecycle,
           representation.activated_by_id,
           representation.activated_at,
           representation.activation_reason,
           representation.aggregate_version
      INTO representation_organization_id,
           representation_state,
           organization_lifecycle,
           representation_activated_by_id,
           representation_activated_at,
           representation_activation_reason,
           representation_aggregate_version
      FROM organizations_organizationrepresentation AS representation
      JOIN organizations_organization AS organization
        ON organization.id = representation.organization_id
     WHERE representation.id = target_representation_id;

    IF NOT FOUND OR representation_state != 'active' THEN
        RETURN;
    END IF;

    IF organization_lifecycle IS DISTINCT FROM 'active' THEN
        RAISE EXCEPTION 'active representation requires an active organization'
            USING ERRCODE = '23514';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM identity_account
         WHERE id = representation_activated_by_id
           AND account_kind = 'platform_administrator'
    ) THEN
        RAISE EXCEPTION 'active representation requires platform activation provenance'
            USING ERRCODE = '23514';
    END IF;

    SELECT COUNT(*) INTO reserved_bundle_count
      FROM authorization_rolebundle
     WHERE organization_id = representation_organization_id
       AND code = 'executive-board';
    IF reserved_bundle_count != 1 THEN
        RAISE EXCEPTION 'active representation requires exactly one reserved bundle'
            USING ERRCODE = '23514';
    END IF;

    SELECT id,
           version,
           name,
           capability_codes,
           created_by_id,
           approved_by_id,
           reason
      INTO reserved_bundle_id,
           reserved_bundle_version,
           reserved_bundle_name,
           reserved_bundle_capabilities,
           reserved_bundle_created_by_id,
           reserved_bundle_approved_by_id,
           reserved_bundle_reason
      FROM authorization_rolebundle
     WHERE organization_id = representation_organization_id
       AND code = 'executive-board';

    IF reserved_bundle_version != 1
       OR reserved_bundle_name IS DISTINCT FROM 'Executive Board'
       OR cardinality(reserved_bundle_capabilities) != 12
       OR ARRAY(
           SELECT unnest(reserved_bundle_capabilities) ORDER BY 1
       ) IS DISTINCT FROM ARRAY[
           'audit.view_security',
           'authorization.delegate',
           'authorization.grant_direct',
           'authorization.manage_roles',
           'authorization.revoke',
           'events.create',
           'events.view_basic',
           'organizations.change_profile',
           'organizations.change_series',
           'organizations.create_series',
           'organizations.manage_representation',
           'organizations.view_basic'
       ]::varchar[]
       OR reserved_bundle_created_by_id IS DISTINCT FROM representation_activated_by_id
       OR reserved_bundle_reason IS DISTINCT FROM representation_activation_reason
    THEN
        RAISE EXCEPTION 'reserved Executive Board bundle is invalid'
            USING ERRCODE = '23514';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM organizations_representationappointment
         WHERE representation_id = target_representation_id
           AND state = 'active'
           AND account_id = reserved_bundle_approved_by_id
    ) THEN
        RAISE EXCEPTION 'reserved Executive Board bundle lacks controller approval'
            USING ERRCODE = '23514';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM organizations_representationappointment
         WHERE representation_id = target_representation_id
           AND state IN ('invited', 'accepted')
    ) THEN
        RAISE EXCEPTION 'active representation cannot retain pending appointments'
            USING ERRCODE = '23514';
    END IF;

    SELECT COUNT(*) INTO active_controller_count
      FROM organizations_representationappointment
     WHERE representation_id = target_representation_id
       AND state = 'active';
    IF active_controller_count < 2 THEN
        RAISE EXCEPTION 'active representation requires two active controllers'
            USING ERRCODE = '23514';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM organizations_representationappointment AS appointment
         WHERE appointment.representation_id = target_representation_id
           AND appointment.state = 'active'
           AND (
               appointment.activated_at IS DISTINCT FROM representation_activated_at
               OR NOT EXISTS (
                   SELECT 1
                     FROM identity_account AS subject
                    WHERE subject.id = appointment.account_id
                      AND subject.account_kind = 'person'
                      AND subject.is_active
                      AND subject.email_verified_at IS NOT NULL
               )
               OR NOT EXISTS (
                   SELECT 1
                     FROM organizations_organizationmembership AS membership
                    WHERE membership.organization_id = representation_organization_id
                      AND membership.account_id = appointment.account_id
                      AND membership.state = 'active'
               )
               OR NOT EXISTS (
                   SELECT 1
                     FROM authorization_roleassignment AS assignment
                    WHERE assignment.id = appointment.role_assignment_id
                      AND assignment.organization_id = representation_organization_id
                      AND assignment.edition_id IS NULL
                      AND assignment.principal_id = appointment.account_id
                      AND assignment.role_bundle_id = reserved_bundle_id
                      AND assignment.effective_from = representation_activated_at
                      AND assignment.expires_at IS NULL
                      AND assignment.revoked_at IS NULL
                      AND assignment.granted_by_id = representation_activated_by_id
                      AND assignment.approved_by_id IS NOT NULL
                      AND assignment.approved_by_id != assignment.principal_id
                      AND assignment.reason = representation_activation_reason
                      AND EXISTS (
                          SELECT 1
                            FROM organizations_representationappointment AS approver
                           WHERE approver.representation_id = target_representation_id
                             AND approver.state = 'active'
                             AND approver.account_id = assignment.approved_by_id
                      )
               )
           )
    ) THEN
        RAISE EXCEPTION 'active Executive Board controller evidence is incomplete'
            USING ERRCODE = '23514';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM authorization_roleassignment AS assignment
         WHERE assignment.role_bundle_id = reserved_bundle_id
           AND assignment.revoked_at IS NULL
           AND NOT EXISTS (
               SELECT 1
                 FROM organizations_representationappointment AS appointment
                WHERE appointment.representation_id = target_representation_id
                  AND appointment.state = 'active'
                  AND appointment.role_assignment_id = assignment.id
           )
    ) THEN
        RAISE EXCEPTION 'reserved Executive Board authority lacks an active appointment'
            USING ERRCODE = '23514';
    END IF;

    SELECT id, correlation_id
      INTO activation_audit_id, activation_correlation_id
      FROM audit_auditevent
     WHERE organization_id = representation_organization_id
       AND operation = 'organizations.representation.activate'
       AND target_type = 'organizations.organization_representation'
       AND target_id = target_representation_id
       AND principal_id = representation_activated_by_id
       AND outcome = 'allow'
     ORDER BY occurred_at DESC, id DESC
     LIMIT 1;
    IF activation_audit_id IS NULL THEN
        RAISE EXCEPTION 'active representation lacks activation audit evidence'
            USING ERRCODE = '23514';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM organizations_representationappointment AS appointment
         WHERE appointment.representation_id = target_representation_id
           AND appointment.state = 'active'
           AND NOT EXISTS (
               SELECT 1
                 FROM audit_auditevent AS assignment_audit
                WHERE assignment_audit.organization_id = representation_organization_id
                  AND assignment_audit.operation =
                      'organizations.representation.authority_assign'
                  AND assignment_audit.target_type = 'authorization.role_assignment'
                  AND assignment_audit.target_id = appointment.role_assignment_id
                  AND assignment_audit.principal_id = representation_activated_by_id
                  AND assignment_audit.outcome = 'allow'
                  AND assignment_audit.correlation_id = activation_correlation_id
           )
    ) THEN
        RAISE EXCEPTION 'active representation lacks root-assignment audit evidence'
            USING ERRCODE = '23514';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM effects_domainevent AS event
          JOIN effects_outboxmessage AS message
            ON message.event_id = event.id
         WHERE event.organization_id = representation_organization_id
           AND event.event_name = 'organizations.representation.changed.v1'
           AND event.aggregate_type =
               'organizations.organization_representation'
           AND event.aggregate_id = target_representation_id
           AND event.aggregate_version = representation_aggregate_version
           AND event.correlation_id = activation_correlation_id
           AND event.causation_id = activation_audit_id
           AND event.actor_id = representation_activated_by_id
           AND event.payload ->> 'action' = 'activated'
           AND event.payload ->> 'representation_code' = 'executive_board'
           AND event.payload ->> 'state' = 'active'
           AND message.organization_id = representation_organization_id
    ) THEN
        RAISE EXCEPTION 'active representation lacks event/outbox evidence'
            USING ERRCODE = '23514';
    END IF;
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION maru_deferred_validate_representation()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM maru_assert_active_executive_board(OLD.id);
    ELSE
        PERFORM maru_assert_active_executive_board(NEW.id);
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER organizations_representation_deferred_integrity
AFTER INSERT OR UPDATE OR DELETE
ON organizations_organizationrepresentation
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION maru_deferred_validate_representation();

CREATE FUNCTION maru_deferred_validate_appointment()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM maru_assert_active_executive_board(OLD.representation_id);
    ELSE
        PERFORM maru_assert_active_executive_board(NEW.representation_id);
        IF TG_OP = 'UPDATE'
           AND OLD.representation_id IS DISTINCT FROM NEW.representation_id
        THEN
            PERFORM maru_assert_active_executive_board(OLD.representation_id);
        END IF;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER organizations_appointment_deferred_integrity
AFTER INSERT OR UPDATE OR DELETE
ON organizations_representationappointment
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION maru_deferred_validate_appointment();

CREATE FUNCTION maru_deferred_validate_role_assignment()
RETURNS trigger AS $$
DECLARE
    assignment_id uuid;
    bundle_id uuid;
    linked_representation_id uuid;
    bundle_organization_id uuid;
    bundle_code varchar;
BEGIN
    IF TG_OP = 'DELETE' THEN
        assignment_id := OLD.id;
        bundle_id := OLD.role_bundle_id;
    ELSE
        assignment_id := NEW.id;
        bundle_id := NEW.role_bundle_id;
    END IF;

    SELECT representation_id INTO linked_representation_id
      FROM organizations_representationappointment
     WHERE role_assignment_id = assignment_id;
    IF FOUND THEN
        PERFORM maru_assert_active_executive_board(linked_representation_id);
    END IF;

    SELECT organization_id, code
      INTO bundle_organization_id, bundle_code
      FROM authorization_rolebundle
     WHERE id = bundle_id;
    IF bundle_code = 'executive-board' THEN
        SELECT id INTO linked_representation_id
          FROM organizations_organizationrepresentation
         WHERE organization_id = bundle_organization_id;
        IF FOUND THEN
            PERFORM maru_assert_active_executive_board(linked_representation_id);
        END IF;
    END IF;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER authorization_role_assignment_deferred_board_integrity
AFTER INSERT OR UPDATE OR DELETE
ON authorization_roleassignment
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION maru_deferred_validate_role_assignment();

CREATE FUNCTION maru_deferred_validate_role_bundle()
RETURNS trigger AS $$
DECLARE
    bundle_organization_id uuid;
    bundle_code varchar;
    active_representation_id uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        bundle_organization_id := OLD.organization_id;
        bundle_code := OLD.code;
    ELSE
        bundle_organization_id := NEW.organization_id;
        bundle_code := NEW.code;
    END IF;

    IF bundle_code = 'executive-board' THEN
        SELECT id INTO active_representation_id
          FROM organizations_organizationrepresentation
         WHERE organization_id = bundle_organization_id;
        IF FOUND THEN
            PERFORM maru_assert_active_executive_board(active_representation_id);
        END IF;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER authorization_role_bundle_deferred_board_integrity
AFTER INSERT OR UPDATE OR DELETE
ON authorization_rolebundle
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION maru_deferred_validate_role_bundle();

CREATE FUNCTION maru_deferred_validate_membership()
RETURNS trigger AS $$
DECLARE
    membership_organization_id uuid;
    membership_account_id uuid;
    active_representation_id uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        membership_organization_id := OLD.organization_id;
        membership_account_id := OLD.account_id;
    ELSE
        membership_organization_id := NEW.organization_id;
        membership_account_id := NEW.account_id;
    END IF;

    FOR active_representation_id IN
        SELECT representation.id
          FROM organizations_organizationrepresentation AS representation
          JOIN organizations_representationappointment AS appointment
            ON appointment.representation_id = representation.id
         WHERE representation.organization_id = membership_organization_id
           AND representation.state = 'active'
           AND appointment.state = 'active'
           AND appointment.account_id = membership_account_id
    LOOP
        PERFORM maru_assert_active_executive_board(active_representation_id);
    END LOOP;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER organizations_membership_deferred_board_integrity
AFTER INSERT OR UPDATE OR DELETE
ON organizations_organizationmembership
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION maru_deferred_validate_membership();

CREATE FUNCTION maru_deferred_validate_board_account()
RETURNS trigger AS $$
DECLARE
    active_representation_id uuid;
BEGIN
    FOR active_representation_id IN
        SELECT DISTINCT representation.id
          FROM organizations_organizationrepresentation AS representation
          JOIN organizations_representationappointment AS appointment
            ON appointment.representation_id = representation.id
         WHERE representation.state = 'active'
           AND appointment.state = 'active'
           AND appointment.account_id = NEW.id
    LOOP
        PERFORM maru_assert_active_executive_board(active_representation_id);
    END LOOP;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER identity_account_deferred_board_integrity
AFTER UPDATE OF is_active, email_verified_at, account_kind
ON identity_account
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION maru_deferred_validate_board_account();

CREATE FUNCTION maru_deferred_validate_board_organization()
RETURNS trigger AS $$
DECLARE
    active_representation_id uuid;
BEGIN
    SELECT id INTO active_representation_id
      FROM organizations_organizationrepresentation
     WHERE organization_id = NEW.id;
    IF FOUND THEN
        PERFORM maru_assert_active_executive_board(active_representation_id);
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER organizations_parent_deferred_board_integrity
AFTER UPDATE OF lifecycle
ON organizations_organization
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION maru_deferred_validate_board_organization();

DO $$
DECLARE
    invalid_platform_assignment_count integer;
BEGIN
    SELECT COUNT(*) INTO invalid_platform_assignment_count
      FROM authorization_roleassignment AS assignment
      JOIN identity_account AS principal
        ON principal.id = assignment.principal_id
     WHERE principal.account_kind = 'platform_administrator';
    IF invalid_platform_assignment_count > 0 THEN
        RAISE EXCEPTION
            'cannot harden integrity: % platform role assignments exist',
            invalid_platform_assignment_count
            USING ERRCODE = '23514';
    END IF;
END;
$$;

DO $$
DECLARE
    active_representation_id uuid;
BEGIN
    FOR active_representation_id IN
        SELECT id
          FROM organizations_organizationrepresentation
         WHERE state = 'active'
    LOOP
        PERFORM maru_assert_active_executive_board(active_representation_id);
    END LOOP;
END;
$$;
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS organizations_parent_deferred_board_integrity
    ON organizations_organization;
DROP FUNCTION IF EXISTS maru_deferred_validate_board_organization();
DROP TRIGGER IF EXISTS identity_account_deferred_board_integrity
    ON identity_account;
DROP FUNCTION IF EXISTS maru_deferred_validate_board_account();
DROP TRIGGER IF EXISTS organizations_membership_deferred_board_integrity
    ON organizations_organizationmembership;
DROP FUNCTION IF EXISTS maru_deferred_validate_membership();
DROP TRIGGER IF EXISTS authorization_role_bundle_deferred_board_integrity
    ON authorization_rolebundle;
DROP FUNCTION IF EXISTS maru_deferred_validate_role_bundle();
DROP TRIGGER IF EXISTS authorization_role_assignment_deferred_board_integrity
    ON authorization_roleassignment;
DROP FUNCTION IF EXISTS maru_deferred_validate_role_assignment();
DROP TRIGGER IF EXISTS organizations_appointment_deferred_integrity
    ON organizations_representationappointment;
DROP FUNCTION IF EXISTS maru_deferred_validate_appointment();
DROP TRIGGER IF EXISTS organizations_representation_deferred_integrity
    ON organizations_organizationrepresentation;
DROP FUNCTION IF EXISTS maru_deferred_validate_representation();
DROP FUNCTION IF EXISTS maru_assert_active_executive_board(uuid);
DROP TRIGGER IF EXISTS authorization_role_assignment_subject_and_provenance_guard
    ON authorization_roleassignment;
DROP FUNCTION IF EXISTS maru_guard_role_assignment_subject_and_provenance();
DROP TRIGGER IF EXISTS organizations_representation_appointment_identity_guard
    ON organizations_representationappointment;
DROP FUNCTION IF EXISTS maru_guard_representation_appointment_identity();
DROP TRIGGER IF EXISTS organizations_representation_identity_guard
    ON organizations_organizationrepresentation;
DROP FUNCTION IF EXISTS maru_guard_representation_identity();
"""


def refuse_governance_artifact_downgrade(apps, schema_editor):
    del schema_editor
    representation = apps.get_model("organizations", "OrganizationRepresentation")
    appointment = apps.get_model("organizations", "RepresentationAppointment")
    membership = apps.get_model("organizations", "OrganizationMembership")
    role_bundle = apps.get_model("authorization", "RoleBundle")
    role_assignment = apps.get_model("authorization", "RoleAssignment")
    audit_event = apps.get_model("audit", "AuditEvent")
    domain_event = apps.get_model("effects", "DomainEvent")
    outbox_message = apps.get_model("effects", "OutboxMessage")

    governance_exists = (
        representation.objects.exists()
        or appointment.objects.exists()
        or role_bundle.objects.filter(code="executive-board").exists()
        or role_assignment.objects.filter(
            role_bundle__code="executive-board"
        ).exists()
        or membership.objects.filter(
            relationship_label="Executive Board controller"
        ).exists()
        or audit_event.objects.filter(
            operation__startswith="organizations.representation."
        ).exists()
        or domain_event.objects.filter(
            event_name="organizations.representation.changed.v1"
        ).exists()
        or domain_event.objects.filter(
            aggregate_type="organizations.organization_representation"
        ).exists()
        or outbox_message.objects.filter(
            event__event_name="organizations.representation.changed.v1"
        ).exists()
    )
    if governance_exists:
        raise RuntimeError(
            "Cannot reverse hardened Executive Board governance while "
            "representation, authority, membership, audit, event, or outbox "
            "artifacts survive. Keep compatible code and fix forward, or restore "
            "the whole database to a consistent pre-write point."
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("audit", "0004_alter_auditevent_safe_metadata"),
        ("effects", "0002_integrity_guards"),
        ("organizations", "0008_organization_representation"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_governance_artifact_downgrade,
        ),
    ]
