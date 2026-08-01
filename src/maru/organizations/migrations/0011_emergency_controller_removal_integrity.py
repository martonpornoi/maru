from __future__ import annotations

from typing import ClassVar

from django.db import migrations

APPOINTMENT_GUARD_FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION maru_guard_representation_appointment_identity()
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
     WHERE id = NEW.account_id
       FOR UPDATE;

    IF NEW.state IN ('invited', 'accepted', 'active')
       AND (
           subject_kind IS DISTINCT FROM 'person'
           OR subject_active IS DISTINCT FROM TRUE
           OR subject_verified_at IS NULL
       )
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
           OR (
               OLD.state IN ('invited', 'accepted')
               AND NEW.state = 'ended'
           )
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

CREATE FUNCTION maru_deferred_validate_emergency_appointment_transition()
RETURNS trigger AS $$
DECLARE
    representation_organization_id uuid;
    representation_state varchar;
    representation_aggregate_version integer;
BEGIN
    SELECT organization_id, state, aggregate_version
      INTO representation_organization_id,
           representation_state,
           representation_aggregate_version
      FROM organizations_organizationrepresentation
     WHERE id = NEW.representation_id;

    IF EXISTS (
           SELECT 1
             FROM organizations_representationappointment AS current_appointment
            WHERE current_appointment.id = NEW.id
              AND current_appointment.state IN ('invited', 'accepted')
       )
       AND representation_state = 'provisioning'
       AND NOT EXISTS (
           SELECT 1
             FROM identity_account AS subject
            WHERE subject.id = NEW.account_id
              AND subject.account_kind = 'person'
              AND subject.is_active
              AND subject.email_verified_at IS NOT NULL
       )
    THEN
        RAISE EXCEPTION 'open provisioning appointment requires an eligible person'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP != 'UPDATE'
       OR OLD.state NOT IN ('invited', 'accepted')
       OR NEW.state != 'ended'
    THEN
        RETURN NULL;
    END IF;

    IF representation_state IS DISTINCT FROM 'provisioning'
       OR NOT EXISTS (
           SELECT 1
             FROM identity_account AS subject
            WHERE subject.id = NEW.account_id
              AND subject.account_kind = 'person'
              AND NOT subject.is_active
       )
       OR EXISTS (
           SELECT 1
             FROM organizations_organizationmembership AS membership
            WHERE membership.organization_id = representation_organization_id
              AND membership.account_id = NEW.account_id
              AND membership.state = 'invited'
              AND membership.relationship_label = 'Executive Board controller'
       )
       OR NOT EXISTS (
           SELECT 1
             FROM effects_domainevent AS event
             JOIN effects_outboxmessage AS message
               ON message.event_id = event.id
             JOIN audit_auditevent AS current_audit
               ON current_audit.id = event.causation_id
            WHERE event.organization_id = representation_organization_id
              AND event.event_name =
                  'organizations.representation.changed.v1'
              AND event.aggregate_type =
                  'organizations.organization_representation'
              AND event.aggregate_id = NEW.representation_id
              AND event.aggregate_version = representation_aggregate_version
              AND event.payload ->> 'action' =
                  'controller_invitation_ended'
              AND event.payload ->> 'representation_code' = 'executive_board'
              AND event.payload ->> 'state' = 'provisioning'
              AND message.organization_id = representation_organization_id
              AND current_audit.organization_id =
                  representation_organization_id
              AND current_audit.operation =
                  'organizations.representation.emergency_controller_remove'
              AND current_audit.target_type =
                  'organizations.organization_representation'
              AND current_audit.target_id = NEW.representation_id
              AND current_audit.principal_id = event.actor_id
              AND current_audit.outcome = 'allow'
              AND current_audit.reason_code = 'platform_emergency_removal'
              AND 'reason' = ANY(current_audit.obligations)
              AND current_audit.correlation_id = event.correlation_id
              AND EXISTS (
                  SELECT 1
                    FROM identity_account AS operator
                   WHERE operator.id = event.actor_id
                     AND operator.account_kind = 'platform_administrator'
              )
              AND EXISTS (
                  SELECT 1
                    FROM audit_auditevent AS identity_audit
                   WHERE identity_audit.organization_id IS NULL
                     AND identity_audit.operation =
                         'identity.account.emergency_deactivate'
                     AND identity_audit.target_type = 'identity.account'
                     AND identity_audit.target_id = NEW.account_id
                     AND identity_audit.principal_id = event.actor_id
                     AND identity_audit.outcome = 'allow'
                     AND identity_audit.reason_code =
                         'platform_emergency_removal'
                     AND identity_audit.correlation_id = event.correlation_id
              )
       )
    THEN
        RAISE EXCEPTION 'emergency invitation end evidence is incomplete'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER organizations_emergency_appointment_integrity
AFTER INSERT OR UPDATE
ON organizations_representationappointment
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION maru_deferred_validate_emergency_appointment_transition();
"""


APPOINTMENT_GUARD_REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS organizations_emergency_appointment_integrity
    ON organizations_representationappointment;
DROP FUNCTION IF EXISTS maru_deferred_validate_emergency_appointment_transition();

CREATE OR REPLACE FUNCTION maru_guard_representation_appointment_identity()
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

"""


SUBJECT_GUARDS_FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION maru_guard_capability_grant_subject()
RETURNS trigger AS $$
DECLARE
    principal_kind varchar;
BEGIN
    SELECT account_kind INTO principal_kind
      FROM identity_account
     WHERE id = NEW.principal_id
       FOR UPDATE;
    IF principal_kind IS DISTINCT FROM 'person' THEN
        RAISE EXCEPTION 'platform accounts cannot receive convention capability grants'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION maru_guard_role_assignment_subject_and_provenance()
RETURNS trigger AS $$
DECLARE
    principal_kind varchar;
    linked_to_representation boolean;
BEGIN
    SELECT account_kind INTO principal_kind
      FROM identity_account
     WHERE id = NEW.principal_id
       FOR UPDATE;
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

CREATE OR REPLACE FUNCTION maru_deferred_validate_board_account()
RETURNS trigger AS $$
DECLARE
    active_representation_id uuid;
    current_account_kind varchar;
    current_is_active boolean;
    current_email_verified_at timestamptz;
BEGIN
    SELECT account_kind, is_active, email_verified_at
      INTO current_account_kind, current_is_active, current_email_verified_at
      FROM identity_account
     WHERE id = NEW.id;
    IF (
        current_account_kind IS DISTINCT FROM 'person'
        OR current_is_active IS DISTINCT FROM TRUE
        OR current_email_verified_at IS NULL
       )
       AND EXISTS (
           SELECT 1
             FROM organizations_representationappointment AS appointment
             JOIN organizations_organizationrepresentation AS representation
               ON representation.id = appointment.representation_id
            WHERE appointment.account_id = NEW.id
              AND appointment.state IN ('invited', 'accepted')
              AND representation.state = 'provisioning'
       )
    THEN
        RAISE EXCEPTION 'ineligible account cannot retain an open Board invitation'
            USING ERRCODE = '23514';
    END IF;

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
"""


SUBJECT_GUARDS_REVERSE_SQL = r"""
CREATE OR REPLACE FUNCTION maru_guard_capability_grant_subject()
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

CREATE OR REPLACE FUNCTION maru_guard_role_assignment_subject_and_provenance()
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

CREATE OR REPLACE FUNCTION maru_deferred_validate_board_account()
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
"""


FORWARD_SQL = r"""
DO $migration$
DECLARE
    original_body text;
BEGIN
    SELECT procedure.prosrc
      INTO original_body
      FROM pg_proc AS procedure
     WHERE procedure.oid =
           'maru_assert_active_executive_board(uuid)'::regprocedure;
    IF original_body IS NULL THEN
        RAISE EXCEPTION 'original Executive Board validator is unavailable';
    END IF;
    EXECUTE format(
        'CREATE FUNCTION maru_assert_active_executive_board_v0009('
        'target_representation_id uuid) RETURNS void LANGUAGE plpgsql AS %L',
        original_body
    );
END;
$migration$;

CREATE OR REPLACE FUNCTION maru_assert_active_executive_board(
    target_representation_id uuid
)
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
    current_action varchar;
    current_state varchar;
    current_causation_id uuid;
    current_correlation_id uuid;
    current_actor_id uuid;
    emergency_identity_audit_count integer;
    emergency_subject_id uuid;
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

    IF NOT FOUND OR representation_state NOT IN ('active', 'suspended') THEN
        RETURN;
    END IF;

    SELECT event.payload ->> 'action',
           event.payload ->> 'state',
           event.causation_id,
           event.correlation_id,
           event.actor_id
      INTO current_action,
           current_state,
           current_causation_id,
           current_correlation_id,
           current_actor_id
      FROM effects_domainevent AS event
      JOIN effects_outboxmessage AS message
        ON message.event_id = event.id
     WHERE event.organization_id = representation_organization_id
       AND event.event_name = 'organizations.representation.changed.v1'
       AND event.aggregate_type =
           'organizations.organization_representation'
       AND event.aggregate_id = target_representation_id
       AND event.aggregate_version = representation_aggregate_version
       AND message.organization_id = representation_organization_id
     ORDER BY event.occurred_at DESC, event.id DESC
     LIMIT 1;

    IF representation_state = 'active'
       AND current_action IS DISTINCT FROM 'controller_ended'
    THEN
        PERFORM maru_assert_active_executive_board_v0009(
            target_representation_id
        );
        RETURN;
    END IF;

    IF representation_state = 'active'
       AND organization_lifecycle IS DISTINCT FROM 'active'
    THEN
        RAISE EXCEPTION 'active representation requires an active organization'
            USING ERRCODE = '23514';
    END IF;
    IF representation_state = 'suspended'
       AND organization_lifecycle IS DISTINCT FROM 'suspended'
    THEN
        RAISE EXCEPTION 'suspended representation requires a suspended organization'
            USING ERRCODE = '23514';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM identity_account
         WHERE id = representation_activated_by_id
           AND account_kind = 'platform_administrator'
    ) THEN
        RAISE EXCEPTION 'representation requires platform activation provenance'
            USING ERRCODE = '23514';
    END IF;

    SELECT COUNT(*) INTO reserved_bundle_count
      FROM authorization_rolebundle
     WHERE organization_id = representation_organization_id
       AND code = 'executive-board';
    IF reserved_bundle_count != 1 THEN
        RAISE EXCEPTION 'representation requires exactly one reserved bundle'
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
       OR reserved_bundle_created_by_id IS DISTINCT FROM
          representation_activated_by_id
       OR reserved_bundle_reason IS DISTINCT FROM representation_activation_reason
    THEN
        RAISE EXCEPTION 'reserved Executive Board bundle is invalid'
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
        RAISE EXCEPTION 'representation lacks activation audit evidence'
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
           AND event.aggregate_version <= representation_aggregate_version
           AND event.correlation_id = activation_correlation_id
           AND event.causation_id = activation_audit_id
           AND event.actor_id = representation_activated_by_id
           AND event.payload ->> 'action' = 'activated'
           AND event.payload ->> 'representation_code' = 'executive_board'
           AND event.payload ->> 'state' = 'active'
           AND message.organization_id = representation_organization_id
    ) THEN
        RAISE EXCEPTION 'representation lacks original activation event evidence'
            USING ERRCODE = '23514';
    END IF;

    IF current_action IS NULL
       OR current_causation_id IS NULL
       OR current_correlation_id IS NULL
       OR current_actor_id IS NULL
       OR current_state IS DISTINCT FROM representation_state
    THEN
        RAISE EXCEPTION 'representation lacks current event/outbox evidence'
            USING ERRCODE = '23514';
    END IF;

    SELECT COUNT(*),
           (ARRAY_AGG(
               identity_audit.target_id
               ORDER BY identity_audit.occurred_at, identity_audit.id
           ))[1]
      INTO emergency_identity_audit_count, emergency_subject_id
      FROM audit_auditevent AS identity_audit
     WHERE identity_audit.organization_id IS NULL
       AND identity_audit.operation = 'identity.account.emergency_deactivate'
       AND identity_audit.target_type = 'identity.account'
       AND identity_audit.principal_id = current_actor_id
       AND identity_audit.outcome = 'allow'
       AND identity_audit.reason_code = 'platform_emergency_removal'
       AND identity_audit.correlation_id = current_correlation_id;
    IF emergency_identity_audit_count != 1 OR emergency_subject_id IS NULL THEN
        RAISE EXCEPTION 'representation requires one global identity audit'
            USING ERRCODE = '23514';
    END IF;

    IF current_action NOT IN ('controller_ended', 'representation_suspended')
       OR (representation_state = 'active' AND current_action != 'controller_ended')
       OR (
           representation_state = 'suspended'
           AND current_action != 'representation_suspended'
       )
       OR NOT EXISTS (
           SELECT 1
             FROM audit_auditevent AS current_audit
            WHERE current_audit.id = current_causation_id
              AND current_audit.organization_id = representation_organization_id
              AND current_audit.operation =
                  'organizations.representation.emergency_controller_remove'
              AND current_audit.target_type =
                  'organizations.organization_representation'
              AND current_audit.target_id = target_representation_id
              AND current_audit.principal_id = current_actor_id
               AND current_audit.outcome = 'allow'
               AND current_audit.reason_code = 'platform_emergency_removal'
               AND 'reason' = ANY(current_audit.obligations)
               AND current_audit.correlation_id = current_correlation_id
       )
       OR NOT EXISTS (
           SELECT 1
             FROM identity_account AS operator
            WHERE operator.id = current_actor_id
              AND operator.account_kind = 'platform_administrator'
       )
       OR NOT EXISTS (
           SELECT 1
             FROM identity_account AS removed_subject
            WHERE removed_subject.id = emergency_subject_id
              AND removed_subject.account_kind = 'person'
              AND NOT removed_subject.is_active
       )
       OR NOT EXISTS (
           SELECT 1
             FROM organizations_representationappointment AS removed_term
            WHERE removed_term.representation_id = target_representation_id
              AND removed_term.account_id = emergency_subject_id
              AND removed_term.state = 'ended'
              AND removed_term.ended_at IS NOT NULL
       )
    THEN
        RAISE EXCEPTION 'representation emergency evidence is incomplete'
            USING ERRCODE = '23514';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM authorization_roleassignment AS assignment
         WHERE assignment.role_bundle_id = reserved_bundle_id
           AND assignment.revoked_at IS NOT NULL
           AND NOT EXISTS (
               SELECT 1
                 FROM audit_auditevent AS revocation_audit
                WHERE revocation_audit.organization_id =
                      representation_organization_id
                  AND revocation_audit.operation =
                      'organizations.representation.authority_revoke'
                  AND revocation_audit.target_type =
                      'authorization.role_assignment'
                  AND revocation_audit.target_id = assignment.id
                  AND revocation_audit.outcome = 'allow'
                  AND revocation_audit.reason_code =
                      'platform_emergency_removal'
         )
    ) THEN
        RAISE EXCEPTION 'representation lacks authority-revocation audit evidence'
            USING ERRCODE = '23514';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM organizations_representationappointment AS ended_term
         WHERE ended_term.representation_id = target_representation_id
           AND ended_term.state = 'ended'
           AND ended_term.activated_at IS NOT NULL
           AND NOT EXISTS (
               SELECT 1
                 FROM organizations_organizationmembership AS ended_membership
                WHERE ended_membership.organization_id =
                      representation_organization_id
                  AND ended_membership.account_id = ended_term.account_id
                  AND ended_membership.state = 'ended'
                  AND ended_membership.relationship_label =
                      'Executive Board controller'
                  AND ended_membership.started_at IS NOT NULL
                  AND ended_membership.ended_at IS NOT NULL
           )
    ) THEN
        RAISE EXCEPTION 'ended controller lacks ended membership evidence'
            USING ERRCODE = '23514';
    END IF;

    IF representation_state = 'suspended' THEN
        IF EXISTS (
            SELECT 1
              FROM organizations_representationappointment
             WHERE representation_id = target_representation_id
               AND state IN ('invited', 'accepted', 'active')
        ) THEN
            RAISE EXCEPTION 'suspended representation cannot retain open appointments'
                USING ERRCODE = '23514';
        END IF;
        IF EXISTS (
            SELECT 1
              FROM authorization_roleassignment
             WHERE role_bundle_id = reserved_bundle_id
               AND revoked_at IS NULL
        ) THEN
            RAISE EXCEPTION 'suspended representation cannot retain root authority'
                USING ERRCODE = '23514';
        END IF;
        IF EXISTS (
            SELECT 1
              FROM organizations_organizationmembership
             WHERE organization_id = representation_organization_id
               AND relationship_label = 'Executive Board controller'
               AND state IN ('invited', 'active')
        ) THEN
            RAISE EXCEPTION 'suspended representation retains an open Board membership'
                USING ERRCODE = '23514';
        END IF;
        RETURN;
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

    IF NOT EXISTS (
        SELECT 1
          FROM organizations_representationappointment
         WHERE representation_id = target_representation_id
           AND state IN ('active', 'ended')
           AND account_id = reserved_bundle_approved_by_id
           AND activated_at IS NOT DISTINCT FROM representation_activated_at
           AND (state != 'ended' OR ended_at IS NOT NULL)
    ) THEN
        RAISE EXCEPTION 'reserved Executive Board bundle lacks controller approval'
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
                    WHERE membership.organization_id =
                          representation_organization_id
                      AND membership.account_id = appointment.account_id
                      AND membership.state = 'active'
                      AND membership.relationship_label =
                          'Executive Board controller'
                      AND membership.started_at IS NOT NULL
                      AND membership.ended_at IS NULL
               )
               OR NOT EXISTS (
                   SELECT 1
                     FROM authorization_roleassignment AS assignment
                    WHERE assignment.id = appointment.role_assignment_id
                      AND assignment.organization_id =
                          representation_organization_id
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
                             AND approver.state IN ('active', 'ended')
                             AND approver.account_id = assignment.approved_by_id
                             AND approver.activated_at IS NOT DISTINCT FROM
                                 representation_activated_at
                             AND (
                                 approver.state != 'ended'
                                 OR approver.ended_at IS NOT NULL
                             )
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

    IF EXISTS (
        SELECT 1
          FROM organizations_representationappointment AS appointment
         WHERE appointment.representation_id = target_representation_id
           AND appointment.state = 'active'
           AND NOT EXISTS (
               SELECT 1
                 FROM audit_auditevent AS assignment_audit
                WHERE assignment_audit.organization_id =
                      representation_organization_id
                  AND assignment_audit.operation =
                      'organizations.representation.authority_assign'
                  AND assignment_audit.target_type =
                      'authorization.role_assignment'
                  AND assignment_audit.target_id = appointment.role_assignment_id
                  AND assignment_audit.principal_id =
                      representation_activated_by_id
                  AND assignment_audit.outcome = 'allow'
                  AND assignment_audit.correlation_id = activation_correlation_id
           )
    ) THEN
        RAISE EXCEPTION 'active representation lacks root-assignment audit evidence'
            USING ERRCODE = '23514';
    END IF;
END;
$$ LANGUAGE plpgsql;

LOCK TABLE organizations_organizationrepresentation
    IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE organizations_organization
    IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE organizations_representationappointment
    IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE organizations_organizationmembership
    IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE authorization_roleassignment
    IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE authorization_rolebundle
    IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE identity_account
    IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE audit_auditevent
    IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE effects_domainevent
    IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE effects_outboxmessage
    IN SHARE ROW EXCLUSIVE MODE;

DO $migration$
DECLARE
    invalid_provisioning_subject_count integer;
    representation_id uuid;
BEGIN
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
            'cannot install emergency integrity: % ineligible open invitations exist',
            invalid_provisioning_subject_count
            USING ERRCODE = '23514';
    END IF;

    FOR representation_id IN
        SELECT id
          FROM organizations_organizationrepresentation
         WHERE state IN ('active', 'suspended')
    LOOP
        PERFORM maru_assert_active_executive_board(representation_id);
    END LOOP;
END;
$migration$;
"""


REVERSE_SQL = r"""
DO $migration$
DECLARE
    original_body text;
BEGIN
    SELECT procedure.prosrc
      INTO original_body
      FROM pg_proc AS procedure
     WHERE procedure.oid =
           'maru_assert_active_executive_board_v0009(uuid)'::regprocedure;
    IF original_body IS NULL THEN
        RAISE EXCEPTION 'original Executive Board validator helper is unavailable';
    END IF;
    EXECUTE format(
        'CREATE OR REPLACE FUNCTION maru_assert_active_executive_board('
        'target_representation_id uuid) RETURNS void LANGUAGE plpgsql AS %L',
        original_body
    );
END;
$migration$;
DROP FUNCTION maru_assert_active_executive_board_v0009(uuid);
"""


def refuse_emergency_governance_downgrade(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            LOCK TABLE organizations_organizationrepresentation
                IN SHARE ROW EXCLUSIVE MODE;
            LOCK TABLE organizations_organization
                IN SHARE ROW EXCLUSIVE MODE;
            LOCK TABLE organizations_representationappointment
                IN SHARE ROW EXCLUSIVE MODE;
            LOCK TABLE organizations_organizationmembership
                IN SHARE ROW EXCLUSIVE MODE;
            LOCK TABLE authorization_roleassignment
                IN SHARE ROW EXCLUSIVE MODE;
            LOCK TABLE authorization_rolebundle
                IN SHARE ROW EXCLUSIVE MODE;
            LOCK TABLE identity_account
                IN SHARE ROW EXCLUSIVE MODE;
            LOCK TABLE audit_auditevent
                IN SHARE ROW EXCLUSIVE MODE;
            LOCK TABLE effects_domainevent
                IN SHARE ROW EXCLUSIVE MODE;
            LOCK TABLE effects_outboxmessage
                IN SHARE ROW EXCLUSIVE MODE;
            """
        )
    audit_event = apps.get_model("audit", "AuditEvent")
    domain_event = apps.get_model("effects", "DomainEvent")
    emergency_actions = (
        "controller_ended",
        "controller_invitation_ended",
        "representation_suspended",
    )
    emergency_evidence_exists = (
        domain_event.objects.filter(
            event_name="organizations.representation.changed.v1",
            payload__action__in=emergency_actions,
        ).exists()
        or audit_event.objects.filter(
            operation="organizations.representation.emergency_controller_remove",
            reason_code="platform_emergency_removal",
        ).exists()
        or audit_event.objects.filter(
            operation="identity.account.emergency_deactivate",
            reason_code="platform_emergency_removal",
        ).exists()
    )
    if emergency_evidence_exists:
        raise RuntimeError(
            "Cannot reverse emergency Executive Board integrity after emergency "
            "governance evidence exists. Fix forward, or restore the whole "
            "database to a consistent pre-emergency point."
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("organizations", "0010_executive_board_authority_hardening"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunSQL(
            SUBJECT_GUARDS_FORWARD_SQL,
            reverse_sql=SUBJECT_GUARDS_REVERSE_SQL,
        ),
        migrations.RunSQL(
            APPOINTMENT_GUARD_FORWARD_SQL,
            reverse_sql=APPOINTMENT_GUARD_REVERSE_SQL,
        ),
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_emergency_governance_downgrade,
        ),
    ]
