"""Activate ADR 0041 exact department and typed-resource authority.

This migration runs after the additive authorization schema and workforce
integrity guards.  It validates existing authority, creates reproducible
position bindings, replaces the authority triggers with exact containment
guards, and refuses a downgrade after the first department/resource-scoped
authority write.

The migration is a stopped-writer operation.  Existing organization- and
edition-scoped records intentionally retain their original broad meaning.
"""

from __future__ import annotations

from typing import Any, ClassVar
from uuid import NAMESPACE_URL, UUID, uuid5

from django.db import migrations, models

WORKFORCE_POSITION_KIND = "workforce.position"
WORKFORCE_POSITION_BINDING_NAME_PREFIX = (
    "https://maru.invalid/authorization/workforce.position/"
)


def workforce_position_binding_id(position_id: UUID) -> UUID:
    """Return the stable scope-binding identifier for a workforce position."""

    return uuid5(
        NAMESPACE_URL,
        f"{WORKFORCE_POSITION_BINDING_NAME_PREFIX}{position_id}",
    )


INSTALL_SCOPE_HELPERS_SQL = r"""
CREATE FUNCTION maru_authorization_capability_min_scope(capability_code text)
RETURNS smallint AS $$
BEGIN
    -- The catalog is code-owned and versioned with this migration.  Adding a
    -- persistable capability requires a matching migration, which prevents an
    -- application/database version mismatch from silently granting authority.
    IF capability_code = ANY (ARRAY[
        'organizations.view_basic',
        'organizations.change_profile',
        'organizations.create_series',
        'organizations.change_series',
        'organizations.manage_representation',
        'events.view_basic',
        'events.create',
        'authorization.delegate',
        'authorization.grant_direct',
        'authorization.revoke',
        'authorization.manage_roles',
        'effects.replay',
        'privacy.manage_requests',
        'audit.view_security'
    ]) THEN
        RETURN 0;
    END IF;

    IF capability_code = ANY (ARRAY[
        'events.change_profile',
        'events.transition',
        'participation.view_staff_summary',
        'identity.manage_restrictions',
        'registration.manage_configuration',
        'registration.view_service_summary',
        'registration.view_attendee_reporting',
        'registration.view_payment_summary',
        'registration.manage_exceptions',
        'registration.register_on_behalf',
        'registration.manage_finance',
        'registration.check_in',
        'accreditation.issue',
        'accreditation.revoke',
        'accreditation.manage_offline',
        'registration.moderate_public_profile',
        'workforce.view_structure',
        'workforce.manage_structure',
        'workforce.manage_applications',
        'workforce.manage_documents',
        'workforce.manage_assignments'
    ]) THEN
        RETURN 1;
    END IF;

    -- Unknown codes and relationship-derived self capabilities are both
    -- intentionally non-persistable.  The readiness command distinguishes
    -- those two operator-facing categories without storing personal data.
    RETURN -1;
END;
$$ LANGUAGE plpgsql IMMUTABLE STRICT;

CREATE FUNCTION maru_authorization_scope_rank(
    edition_id uuid,
    department_id uuid,
    resource_binding_id uuid
)
RETURNS smallint AS $$
    SELECT CASE
        WHEN resource_binding_id IS NOT NULL THEN 3
        WHEN department_id IS NOT NULL THEN 2
        WHEN edition_id IS NOT NULL THEN 1
        ELSE 0
    END::smallint;
$$ LANGUAGE sql IMMUTABLE;

CREATE FUNCTION maru_authorization_scope_contains(
    parent_organization_id uuid,
    parent_edition_id uuid,
    parent_department_id uuid,
    parent_resource_binding_id uuid,
    child_organization_id uuid,
    child_edition_id uuid,
    child_department_id uuid,
    child_resource_binding_id uuid
)
RETURNS boolean AS $$
    SELECT parent_organization_id = child_organization_id
       AND (
           parent_edition_id IS NULL
           OR (
               parent_edition_id = child_edition_id
               AND (
                   parent_department_id IS NULL
                   OR (
                       parent_department_id = child_department_id
                       AND (
                           parent_resource_binding_id IS NULL
                           OR parent_resource_binding_id = child_resource_binding_id
                       )
                   )
               )
           )
       );
$$ LANGUAGE sql IMMUTABLE;

CREATE FUNCTION maru_validate_scoped_resource_binding()
RETURNS trigger AS $$
DECLARE
    position_organization uuid;
    position_edition uuid;
    position_department uuid;
BEGIN
    -- The schema-phase immutability trigger owns every UPDATE failure.  Let it
    -- produce the stable immutable-identity error before resolving a changed
    -- resource identifier here.
    IF TG_OP = 'UPDATE' THEN
        RETURN NEW;
    END IF;

    IF NEW.resource_kind <> 'workforce.position' THEN
        RAISE EXCEPTION 'unknown scoped resource binding kind'
            USING ERRCODE = '23514';
    END IF;

    -- A row lock serializes binding creation with a concurrent position move.
    -- Once the binding exists, the workforce trigger freezes this scope.
    SELECT organization_id, edition_id, department_id
      INTO position_organization, position_edition, position_department
      FROM workforce_position
     WHERE id = NEW.resource_id
     FOR UPDATE;

    IF position_organization IS NULL
       OR position_organization IS DISTINCT FROM NEW.organization_id
       OR position_edition IS DISTINCT FROM NEW.edition_id
       OR position_department IS DISTINCT FROM NEW.department_id
    THEN
        RAISE EXCEPTION 'scoped resource binding does not match its exact position'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER authorization_scoped_resource_binding_guard
BEFORE INSERT OR UPDATE
ON authorization_scopedresourcebinding
FOR EACH ROW EXECUTE FUNCTION maru_validate_scoped_resource_binding();
"""


REMOVE_SCOPE_HELPERS_SQL = r"""
DROP TRIGGER IF EXISTS authorization_scoped_resource_binding_guard
ON authorization_scopedresourcebinding;
DROP FUNCTION IF EXISTS maru_validate_scoped_resource_binding();
DROP FUNCTION IF EXISTS maru_authorization_scope_contains(
    uuid, uuid, uuid, uuid, uuid, uuid, uuid, uuid
);
DROP FUNCTION IF EXISTS maru_authorization_scope_rank(uuid, uuid, uuid);
DROP FUNCTION IF EXISTS maru_authorization_capability_min_scope(text);
"""


PREFLIGHT_SQL = r"""
DO $$
DECLARE
    malformed_grant_scope_count bigint;
    malformed_assignment_scope_count bigint;
    invalid_grant_capability_count bigint;
    invalid_role_capability_count bigint;
    invalid_delegation_edge_count bigint;
    delegation_cycle_count bigint;
    invalid_grant_revocation_count bigint;
    invalid_role_revocation_count bigint;
    retained_workforce_edition_role_count bigint;
BEGIN
    SELECT COUNT(*)
      INTO malformed_grant_scope_count
      FROM authorization_capabilitygrant AS authority
      LEFT JOIN events_eventedition AS edition
        ON edition.id = authority.edition_id
      LEFT JOIN workforce_department AS department
        ON department.id = authority.department_id
      LEFT JOIN authorization_scopedresourcebinding AS binding
        ON binding.id = authority.resource_binding_id
     WHERE (
            authority.edition_id IS NULL
            AND (
                authority.department_id IS NOT NULL
                OR authority.resource_binding_id IS NOT NULL
            )
        )
        OR (
            authority.department_id IS NULL
            AND authority.resource_binding_id IS NOT NULL
        )
        OR (
            authority.edition_id IS NOT NULL
            AND edition.organization_id IS DISTINCT FROM authority.organization_id
        )
        OR (
            authority.department_id IS NOT NULL
            AND (
                department.organization_id IS DISTINCT FROM authority.organization_id
                OR department.edition_id IS DISTINCT FROM authority.edition_id
            )
        )
        OR (
            authority.resource_binding_id IS NOT NULL
            AND (
                binding.organization_id IS DISTINCT FROM authority.organization_id
                OR binding.edition_id IS DISTINCT FROM authority.edition_id
                OR binding.department_id IS DISTINCT FROM authority.department_id
            )
        );

    SELECT COUNT(*)
      INTO malformed_assignment_scope_count
      FROM authorization_roleassignment AS authority
      LEFT JOIN authorization_rolebundle AS bundle
        ON bundle.id = authority.role_bundle_id
      LEFT JOIN events_eventedition AS edition
        ON edition.id = authority.edition_id
      LEFT JOIN workforce_department AS department
        ON department.id = authority.department_id
      LEFT JOIN authorization_scopedresourcebinding AS binding
        ON binding.id = authority.resource_binding_id
     WHERE bundle.organization_id IS DISTINCT FROM authority.organization_id
        OR (
            authority.edition_id IS NULL
            AND (
                authority.department_id IS NOT NULL
                OR authority.resource_binding_id IS NOT NULL
            )
        )
        OR (
            authority.department_id IS NULL
            AND authority.resource_binding_id IS NOT NULL
        )
        OR (
            authority.edition_id IS NOT NULL
            AND edition.organization_id IS DISTINCT FROM authority.organization_id
        )
        OR (
            authority.department_id IS NOT NULL
            AND (
                department.organization_id IS DISTINCT FROM authority.organization_id
                OR department.edition_id IS DISTINCT FROM authority.edition_id
            )
        )
        OR (
            authority.resource_binding_id IS NOT NULL
            AND (
                binding.organization_id IS DISTINCT FROM authority.organization_id
                OR binding.edition_id IS DISTINCT FROM authority.edition_id
                OR binding.department_id IS DISTINCT FROM authority.department_id
            )
        );

    SELECT COUNT(*)
      INTO invalid_grant_capability_count
      FROM authorization_capabilitygrant AS authority
     WHERE maru_authorization_capability_min_scope(authority.capability_code) < 0
        OR maru_authorization_scope_rank(
               authority.edition_id,
               authority.department_id,
               authority.resource_binding_id
           ) < maru_authorization_capability_min_scope(authority.capability_code);

    SELECT COUNT(*)
      INTO invalid_role_capability_count
      FROM authorization_rolebundle AS bundle
     WHERE cardinality(bundle.capability_codes) = 0
        OR array_ndims(bundle.capability_codes) IS DISTINCT FROM 1
        OR array_position(bundle.capability_codes, NULL) IS NOT NULL
        OR cardinality(bundle.capability_codes) <> (
            SELECT COUNT(DISTINCT code.value)
              FROM unnest(bundle.capability_codes) AS code(value)
        )
        OR EXISTS (
            SELECT 1
              FROM unnest(bundle.capability_codes) AS code(value)
             WHERE code.value IS NULL
                OR maru_authorization_capability_min_scope(code.value) < 0
        )
        OR EXISTS (
            SELECT 1
              FROM authorization_roleassignment AS authority
              CROSS JOIN LATERAL unnest(bundle.capability_codes) AS code(value)
             WHERE authority.role_bundle_id = bundle.id
               AND maru_authorization_scope_rank(
                       authority.edition_id,
                       authority.department_id,
                       authority.resource_binding_id
                   ) < maru_authorization_capability_min_scope(code.value)
        );

    SELECT COUNT(*)
      INTO invalid_delegation_edge_count
      FROM authorization_capabilitygrant AS child
      JOIN authorization_capabilitygrant AS parent
        ON parent.id = child.delegated_from_id
     WHERE parent.principal_id IS DISTINCT FROM child.granted_by_id
        OR parent.capability_code IS DISTINCT FROM child.capability_code
        OR NOT maru_authorization_scope_contains(
            parent.organization_id,
            parent.edition_id,
            parent.department_id,
            parent.resource_binding_id,
            child.organization_id,
            child.edition_id,
            child.department_id,
            child.resource_binding_id
        )
        OR child.effective_from < parent.effective_from
        OR (
            parent.expires_at IS NOT NULL
            AND (
                child.expires_at IS NULL
                OR child.expires_at > parent.expires_at
            )
        );

    SELECT COUNT(*)
      INTO invalid_grant_revocation_count
      FROM authorization_capabilitygrant
     WHERE (
            revoked_at IS NULL
            AND (
                revoked_by_id IS NOT NULL
                OR revocation_reason <> ''
            )
        )
        OR (
            revoked_at IS NOT NULL
            AND (
                revoked_by_id IS NULL
                OR revocation_reason !~ '[^[:space:]]'
            )
        );

    SELECT COUNT(*)
      INTO invalid_role_revocation_count
      FROM authorization_roleassignment
     WHERE (
            revoked_at IS NULL
            AND (
                revoked_by_id IS NOT NULL
                OR revocation_reason <> ''
            )
        )
        OR (
            revoked_at IS NOT NULL
            AND (
                revoked_by_id IS NULL
                OR revocation_reason !~ '[^[:space:]]'
            )
        );

    WITH RECURSIVE delegation_walk AS (
        SELECT authority.id AS start_id,
               authority.delegated_from_id AS next_id,
               ARRAY[authority.id] AS path,
               false AS cycle
          FROM authorization_capabilitygrant AS authority
         WHERE authority.delegated_from_id IS NOT NULL
        UNION ALL
        SELECT delegation_walk.start_id,
               parent.delegated_from_id,
               delegation_walk.path || parent.id,
               parent.id = ANY(delegation_walk.path) AS cycle
          FROM delegation_walk
          JOIN authorization_capabilitygrant AS parent
            ON parent.id = delegation_walk.next_id
         WHERE NOT delegation_walk.cycle
           AND delegation_walk.next_id IS NOT NULL
    )
    SELECT COUNT(DISTINCT start_id)
      INTO delegation_cycle_count
      FROM delegation_walk
     WHERE cycle;

    SELECT COUNT(*)
      INTO retained_workforce_edition_role_count
      FROM workforce_positionassignment AS workforce_assignment
      JOIN authorization_roleassignment AS authority
        ON authority.id = workforce_assignment.role_assignment_id
     WHERE authority.edition_id = workforce_assignment.edition_id
       AND authority.department_id IS NULL
       AND authority.resource_binding_id IS NULL;

    RAISE NOTICE
        'ADR 0041 retained edition-wide workforce-linked role assignments: %',
        retained_workforce_edition_role_count;

    IF malformed_grant_scope_count > 0
       OR malformed_assignment_scope_count > 0
       OR invalid_grant_capability_count > 0
       OR invalid_role_capability_count > 0
       OR invalid_delegation_edge_count > 0
       OR delegation_cycle_count > 0
       OR invalid_grant_revocation_count > 0
       OR invalid_role_revocation_count > 0
    THEN
        RAISE EXCEPTION
            'ADR 0041 blockers: G %, R %, C %, B %, E %, Y %, GR %, RR %',
            malformed_grant_scope_count,
            malformed_assignment_scope_count,
            invalid_grant_capability_count,
            invalid_role_capability_count,
            invalid_delegation_edge_count,
            delegation_cycle_count,
            invalid_grant_revocation_count,
            invalid_role_revocation_count
            USING ERRCODE = '23514';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM authorization_capabilitygrant
         WHERE department_id IS NOT NULL OR resource_binding_id IS NOT NULL
    ) OR EXISTS (
        SELECT 1
          FROM authorization_roleassignment
         WHERE department_id IS NOT NULL OR resource_binding_id IS NOT NULL
    ) THEN
        INSERT INTO authorization_scopev2writefence(
            singleton,
            first_written_at
        )
        VALUES (true, statement_timestamp())
        ON CONFLICT (singleton) DO NOTHING;
    END IF;
END;
$$;
"""


def backfill_workforce_position_bindings(
    apps: Any,
    schema_editor: Any,
) -> None:
    """Create one deterministic typed binding for every current position."""

    Position = apps.get_model("workforce", "Position")
    ScopedResourceBinding = apps.get_model(
        "authorization",
        "ScopedResourceBinding",
    )
    alias = schema_editor.connection.alias
    positions = (
        Position.objects.using(alias)
        .values("id", "organization_id", "edition_id", "department_id")
        .order_by("id")
    )
    for position in positions.iterator(chunk_size=500):
        ScopedResourceBinding.objects.using(alias).get_or_create(
            resource_kind=WORKFORCE_POSITION_KIND,
            resource_id=position["id"],
            defaults={
                "id": workforce_position_binding_id(position["id"]),
                "organization_id": position["organization_id"],
                "edition_id": position["edition_id"],
                "department_id": position["department_id"],
            },
        )


def remove_reproducible_workforce_position_bindings(
    apps: Any,
    schema_editor: Any,
) -> None:
    """Remove only bindings whose IDs prove this migration created them."""

    Position = apps.get_model("workforce", "Position")
    ScopedResourceBinding = apps.get_model(
        "authorization",
        "ScopedResourceBinding",
    )
    alias = schema_editor.connection.alias
    schema_editor.execute(
        "DROP TRIGGER IF EXISTS "
        "authorization_scoped_resource_binding_immutable "
        "ON authorization_scopedresourcebinding;"
    )
    try:
        position_ids = (
            Position.objects.using(alias).values_list("id", flat=True).order_by("id")
        )
        for position_id in position_ids.iterator(chunk_size=500):
            ScopedResourceBinding.objects.using(alias).filter(
                id=workforce_position_binding_id(position_id),
                resource_kind=WORKFORCE_POSITION_KIND,
                resource_id=position_id,
            ).delete()
    finally:
        schema_editor.execute(
            "CREATE TRIGGER authorization_scoped_resource_binding_immutable "
            "BEFORE UPDATE OR DELETE ON authorization_scopedresourcebinding "
            "FOR EACH ROW EXECUTE FUNCTION "
            "maru_prevent_scoped_resource_binding_mutation();"
        )


ACTIVATE_AUTHORITY_GUARDS_SQL = r"""
CREATE FUNCTION maru_prevent_authority_record_delete()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'authority records must be revoked, not deleted'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER authorization_capability_grant_no_delete
BEFORE DELETE
ON authorization_capabilitygrant
FOR EACH ROW EXECUTE FUNCTION maru_prevent_authority_record_delete();

CREATE TRIGGER authorization_role_assignment_no_delete
BEFORE DELETE
ON authorization_roleassignment
FOR EACH ROW EXECUTE FUNCTION maru_prevent_authority_record_delete();

CREATE FUNCTION maru_validate_role_bundle_catalog()
RETURNS trigger AS $$
BEGIN
    IF cardinality(NEW.capability_codes) = 0
       OR array_ndims(NEW.capability_codes) IS DISTINCT FROM 1
       OR array_position(NEW.capability_codes, NULL) IS NOT NULL
       OR cardinality(NEW.capability_codes) <> (
           SELECT COUNT(DISTINCT code.value)
             FROM unnest(NEW.capability_codes) AS code(value)
       )
       OR EXISTS (
           SELECT 1
             FROM unnest(NEW.capability_codes) AS code(value)
            WHERE code.value IS NULL
               OR maru_authorization_capability_min_scope(code.value) < 0
       )
    THEN
        RAISE EXCEPTION 'role bundle contains an unknown or non-persistable capability'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER authorization_role_bundle_catalog_guard
BEFORE INSERT
ON authorization_rolebundle
FOR EACH ROW EXECUTE FUNCTION maru_validate_role_bundle_catalog();

CREATE OR REPLACE FUNCTION maru_validate_capability_grant()
RETURNS trigger AS $$
DECLARE
    scoped_organization uuid;
    scoped_edition uuid;
    scoped_department uuid;
    minimum_scope smallint;
    parent_record authorization_capabilitygrant%ROWTYPE;
    delegation_cycle boolean;
BEGIN
    -- Authority issuance is append-only.  Replacement creates a new record;
    -- the only supported in-place transition is the revocation triplet.
    IF TG_OP = 'UPDATE' AND (
        NEW.id IS DISTINCT FROM OLD.id
        OR NEW.created_at IS DISTINCT FROM OLD.created_at
        OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
        OR NEW.edition_id IS DISTINCT FROM OLD.edition_id
        OR NEW.department_id IS DISTINCT FROM OLD.department_id
        OR NEW.resource_binding_id IS DISTINCT FROM OLD.resource_binding_id
        OR NEW.principal_id IS DISTINCT FROM OLD.principal_id
        OR NEW.capability_code IS DISTINCT FROM OLD.capability_code
        OR NEW.effective_from IS DISTINCT FROM OLD.effective_from
        OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
        OR NEW.granted_by_id IS DISTINCT FROM OLD.granted_by_id
        OR NEW.approved_by_id IS DISTINCT FROM OLD.approved_by_id
        OR NEW.delegated_from_id IS DISTINCT FROM OLD.delegated_from_id
        OR NEW.reason IS DISTINCT FROM OLD.reason
    ) THEN
        RAISE EXCEPTION 'capability grant issuance is immutable'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'UPDATE'
       AND OLD.revoked_at IS NOT NULL
       AND (
           NEW.revoked_at IS DISTINCT FROM OLD.revoked_at
           OR NEW.revoked_by_id IS DISTINCT FROM OLD.revoked_by_id
           OR NEW.revocation_reason IS DISTINCT FROM OLD.revocation_reason
       )
    THEN
        RAISE EXCEPTION 'capability grant revocation is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF (
        NEW.revoked_at IS NULL
        AND (
            NEW.revoked_by_id IS NOT NULL
            OR NEW.revocation_reason <> ''
        )
    ) OR (
        NEW.revoked_at IS NOT NULL
        AND (
            NEW.revoked_by_id IS NULL
            OR NEW.revocation_reason !~ '[^[:space:]]'
        )
    ) THEN
        RAISE EXCEPTION 'capability grant revocation evidence is incomplete'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.edition_id IS NULL AND (
        NEW.department_id IS NOT NULL OR NEW.resource_binding_id IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'capability grant has a malformed scope tuple'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.department_id IS NULL AND NEW.resource_binding_id IS NOT NULL THEN
        RAISE EXCEPTION 'resource scope requires an exact department'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.edition_id IS NOT NULL THEN
        SELECT organization_id
          INTO scoped_organization
          FROM events_eventedition
         WHERE id = NEW.edition_id
         FOR UPDATE;
        IF scoped_organization IS DISTINCT FROM NEW.organization_id THEN
            RAISE EXCEPTION 'capability grant edition scope mismatch'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF NEW.department_id IS NOT NULL THEN
        PERFORM pg_advisory_xact_lock(
            hashtextextended(
                'maru.workforce.department:'
                || NEW.organization_id::text
                || ':'
                || NEW.edition_id::text,
                0
            )
        );
        SELECT organization_id, edition_id
          INTO scoped_organization, scoped_edition
          FROM workforce_department
         WHERE id = NEW.department_id
         FOR UPDATE;
        IF scoped_organization IS DISTINCT FROM NEW.organization_id
           OR scoped_edition IS DISTINCT FROM NEW.edition_id
        THEN
            RAISE EXCEPTION 'capability grant department scope mismatch'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF NEW.resource_binding_id IS NOT NULL THEN
        SELECT organization_id, edition_id, department_id
          INTO scoped_organization, scoped_edition, scoped_department
          FROM authorization_scopedresourcebinding
         WHERE id = NEW.resource_binding_id
         FOR KEY SHARE;
        IF scoped_organization IS DISTINCT FROM NEW.organization_id
           OR scoped_edition IS DISTINCT FROM NEW.edition_id
           OR scoped_department IS DISTINCT FROM NEW.department_id
        THEN
            RAISE EXCEPTION 'capability grant resource scope mismatch'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    minimum_scope := maru_authorization_capability_min_scope(NEW.capability_code);
    IF minimum_scope < 0
       OR maru_authorization_scope_rank(
           NEW.edition_id,
           NEW.department_id,
           NEW.resource_binding_id
       ) < minimum_scope
    THEN
        RAISE EXCEPTION 'capability cannot be persisted at this scope'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.delegated_from_id IS NOT NULL THEN
        SELECT *
          INTO parent_record
          FROM authorization_capabilitygrant
         WHERE id = NEW.delegated_from_id
         FOR UPDATE;

        IF parent_record.id IS NULL
           OR parent_record.principal_id IS DISTINCT FROM NEW.granted_by_id
           OR parent_record.capability_code IS DISTINCT FROM NEW.capability_code
           OR NOT maru_authorization_scope_contains(
               parent_record.organization_id,
               parent_record.edition_id,
               parent_record.department_id,
               parent_record.resource_binding_id,
               NEW.organization_id,
               NEW.edition_id,
               NEW.department_id,
               NEW.resource_binding_id
           )
           OR NEW.effective_from < parent_record.effective_from
           OR (
               parent_record.expires_at IS NOT NULL
               AND (
                   NEW.expires_at IS NULL
                   OR NEW.expires_at > parent_record.expires_at
               )
           )
        THEN
            RAISE EXCEPTION 'invalid capability delegation containment'
                USING ERRCODE = '23514';
        END IF;

        WITH RECURSIVE ancestors AS (
            SELECT parent.id,
                   parent.delegated_from_id,
                   ARRAY[parent.id] AS path,
                   parent.id = NEW.id AS cycle
              FROM authorization_capabilitygrant AS parent
             WHERE parent.id = NEW.delegated_from_id
            UNION ALL
            SELECT parent.id,
                   parent.delegated_from_id,
                   ancestors.path || parent.id,
                   parent.id = NEW.id OR parent.id = ANY(ancestors.path) AS cycle
              FROM ancestors
              JOIN authorization_capabilitygrant AS parent
                ON parent.id = ancestors.delegated_from_id
             WHERE NOT ancestors.cycle
        )
        SELECT COALESCE(bool_or(cycle), false)
          INTO delegation_cycle
          FROM ancestors;
        IF delegation_cycle THEN
            RAISE EXCEPTION 'capability delegation cannot contain a cycle'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF NEW.department_id IS NOT NULL OR NEW.resource_binding_id IS NOT NULL THEN
        INSERT INTO authorization_scopev2writefence(
            singleton,
            first_written_at
        )
        VALUES (true, statement_timestamp())
        ON CONFLICT (singleton) DO NOTHING;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION maru_validate_role_assignment()
RETURNS trigger AS $$
DECLARE
    scoped_organization uuid;
    scoped_edition uuid;
    scoped_department uuid;
    bundle_capability_codes text[];
    authority_scope smallint;
BEGIN
    IF TG_OP = 'UPDATE' AND (
        NEW.id IS DISTINCT FROM OLD.id
        OR NEW.created_at IS DISTINCT FROM OLD.created_at
        OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
        OR NEW.edition_id IS DISTINCT FROM OLD.edition_id
        OR NEW.department_id IS DISTINCT FROM OLD.department_id
        OR NEW.resource_binding_id IS DISTINCT FROM OLD.resource_binding_id
        OR NEW.principal_id IS DISTINCT FROM OLD.principal_id
        OR NEW.role_bundle_id IS DISTINCT FROM OLD.role_bundle_id
        OR NEW.effective_from IS DISTINCT FROM OLD.effective_from
        OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
        OR NEW.granted_by_id IS DISTINCT FROM OLD.granted_by_id
        OR NEW.approved_by_id IS DISTINCT FROM OLD.approved_by_id
        OR NEW.reason IS DISTINCT FROM OLD.reason
    ) THEN
        RAISE EXCEPTION 'role assignment issuance is immutable'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'UPDATE'
       AND OLD.revoked_at IS NOT NULL
       AND (
           NEW.revoked_at IS DISTINCT FROM OLD.revoked_at
           OR NEW.revoked_by_id IS DISTINCT FROM OLD.revoked_by_id
           OR NEW.revocation_reason IS DISTINCT FROM OLD.revocation_reason
       )
    THEN
        RAISE EXCEPTION 'role assignment revocation is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF (
        NEW.revoked_at IS NULL
        AND (
            NEW.revoked_by_id IS NOT NULL
            OR NEW.revocation_reason <> ''
        )
    ) OR (
        NEW.revoked_at IS NOT NULL
        AND (
            NEW.revoked_by_id IS NULL
            OR NEW.revocation_reason !~ '[^[:space:]]'
        )
    ) THEN
        RAISE EXCEPTION 'role assignment revocation evidence is incomplete'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.edition_id IS NULL AND (
        NEW.department_id IS NOT NULL OR NEW.resource_binding_id IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'role assignment has a malformed scope tuple'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.department_id IS NULL AND NEW.resource_binding_id IS NOT NULL THEN
        RAISE EXCEPTION 'resource scope requires an exact department'
            USING ERRCODE = '23514';
    END IF;

    SELECT organization_id, capability_codes
      INTO scoped_organization, bundle_capability_codes
      FROM authorization_rolebundle
     WHERE id = NEW.role_bundle_id
     FOR KEY SHARE;
    IF scoped_organization IS DISTINCT FROM NEW.organization_id THEN
        RAISE EXCEPTION 'role bundle belongs to another organization'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.edition_id IS NOT NULL THEN
        SELECT organization_id
          INTO scoped_organization
          FROM events_eventedition
         WHERE id = NEW.edition_id
         FOR UPDATE;
        IF scoped_organization IS DISTINCT FROM NEW.organization_id THEN
            RAISE EXCEPTION 'role assignment edition scope mismatch'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF NEW.department_id IS NOT NULL THEN
        PERFORM pg_advisory_xact_lock(
            hashtextextended(
                'maru.workforce.department:'
                || NEW.organization_id::text
                || ':'
                || NEW.edition_id::text,
                0
            )
        );
        SELECT organization_id, edition_id
          INTO scoped_organization, scoped_edition
          FROM workforce_department
         WHERE id = NEW.department_id
         FOR UPDATE;
        IF scoped_organization IS DISTINCT FROM NEW.organization_id
           OR scoped_edition IS DISTINCT FROM NEW.edition_id
        THEN
            RAISE EXCEPTION 'role assignment department scope mismatch'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF NEW.resource_binding_id IS NOT NULL THEN
        SELECT organization_id, edition_id, department_id
          INTO scoped_organization, scoped_edition, scoped_department
          FROM authorization_scopedresourcebinding
         WHERE id = NEW.resource_binding_id
         FOR KEY SHARE;
        IF scoped_organization IS DISTINCT FROM NEW.organization_id
           OR scoped_edition IS DISTINCT FROM NEW.edition_id
           OR scoped_department IS DISTINCT FROM NEW.department_id
        THEN
            RAISE EXCEPTION 'role assignment resource scope mismatch'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    authority_scope := maru_authorization_scope_rank(
        NEW.edition_id,
        NEW.department_id,
        NEW.resource_binding_id
    );
    IF cardinality(bundle_capability_codes) = 0
       OR array_ndims(bundle_capability_codes) IS DISTINCT FROM 1
       OR array_position(bundle_capability_codes, NULL) IS NOT NULL
       OR cardinality(bundle_capability_codes) <> (
           SELECT COUNT(DISTINCT code.value)
             FROM unnest(bundle_capability_codes) AS code(value)
       )
       OR EXISTS (
           SELECT 1
             FROM unnest(bundle_capability_codes) AS code(value)
            WHERE code.value IS NULL
               OR maru_authorization_capability_min_scope(code.value) < 0
               OR authority_scope
                  < maru_authorization_capability_min_scope(code.value)
       )
    THEN
        RAISE EXCEPTION 'role bundle cannot be persisted at this scope'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.department_id IS NOT NULL OR NEW.resource_binding_id IS NOT NULL THEN
        INSERT INTO authorization_scopev2writefence(
            singleton,
            first_written_at
        )
        VALUES (true, statement_timestamp())
        ON CONFLICT (singleton) DO NOTHING;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


RESTORE_LEGACY_AUTHORITY_GUARDS_SQL = r"""
DROP TRIGGER IF EXISTS authorization_role_assignment_no_delete
ON authorization_roleassignment;
DROP TRIGGER IF EXISTS authorization_capability_grant_no_delete
ON authorization_capabilitygrant;
DROP FUNCTION IF EXISTS maru_prevent_authority_record_delete();

DROP TRIGGER IF EXISTS authorization_role_bundle_catalog_guard
ON authorization_rolebundle;
DROP FUNCTION IF EXISTS maru_validate_role_bundle_catalog();

CREATE OR REPLACE FUNCTION maru_validate_capability_grant()
RETURNS trigger AS $$
DECLARE
    edition_organization uuid;
    parent_record authorization_capabilitygrant%ROWTYPE;
BEGIN
    IF NEW.edition_id IS NOT NULL THEN
        SELECT organization_id INTO edition_organization
          FROM events_eventedition WHERE id = NEW.edition_id;
        IF edition_organization IS NULL
           OR edition_organization != NEW.organization_id
        THEN
            RAISE EXCEPTION 'capability grant edition belongs to another organization'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF NEW.delegated_from_id IS NOT NULL THEN
        SELECT * INTO parent_record
          FROM authorization_capabilitygrant
         WHERE id = NEW.delegated_from_id;
        IF parent_record.id IS NULL
           OR parent_record.principal_id != NEW.granted_by_id
           OR parent_record.capability_code != NEW.capability_code
           OR parent_record.organization_id != NEW.organization_id
           OR (
               parent_record.edition_id IS NOT NULL
               AND parent_record.edition_id IS DISTINCT FROM NEW.edition_id
           )
           OR (
               parent_record.expires_at IS NOT NULL
               AND (
                   NEW.expires_at IS NULL
                   OR NEW.expires_at > parent_record.expires_at
               )
           )
        THEN
            RAISE EXCEPTION 'invalid capability delegation chain'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION maru_validate_role_assignment()
RETURNS trigger AS $$
DECLARE
    edition_organization uuid;
    bundle_organization uuid;
BEGIN
    SELECT organization_id INTO bundle_organization
      FROM authorization_rolebundle WHERE id = NEW.role_bundle_id;
    IF bundle_organization IS NULL
       OR bundle_organization != NEW.organization_id
    THEN
        RAISE EXCEPTION 'role bundle belongs to another organization'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.edition_id IS NOT NULL THEN
        SELECT organization_id INTO edition_organization
          FROM events_eventedition WHERE id = NEW.edition_id;
        IF edition_organization IS NULL
           OR edition_organization != NEW.organization_id
        THEN
            RAISE EXCEPTION 'role assignment edition belongs to another organization'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


DOWNGRADE_FENCE_SQL = r"""
SELECT 1;
"""


REVERSE_DOWNGRADE_FENCE_SQL = r"""
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM authorization_scopev2writefence) THEN
        RAISE EXCEPTION
            'ADR 0041 downgrade refused after scoped authority; fix forward'
            USING ERRCODE = '23514';
    END IF;
END;
$$;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0004_scope_v2_schema"),
        ("workforce", "0004_scope_v2_integrity"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.CreateModel(
            name="AuthorizationScopeWriteFence",
            fields=[
                (
                    "singleton",
                    models.BooleanField(
                        default=True,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "first_written_at",
                    models.DateTimeField(auto_now_add=True),
                ),
            ],
            options={
                "db_table": "authorization_scopev2writefence",
                "default_permissions": (),
            },
        ),
        migrations.RunSQL(
            INSTALL_SCOPE_HELPERS_SQL,
            reverse_sql=REMOVE_SCOPE_HELPERS_SQL,
        ),
        migrations.RunSQL(PREFLIGHT_SQL, reverse_sql=migrations.RunSQL.noop),
        migrations.RunPython(
            backfill_workforce_position_bindings,
            reverse_code=remove_reproducible_workforce_position_bindings,
        ),
        migrations.RunSQL(
            ACTIVATE_AUTHORITY_GUARDS_SQL,
            reverse_sql=RESTORE_LEGACY_AUTHORITY_GUARDS_SQL,
        ),
        migrations.RunSQL(
            DOWNGRADE_FENCE_SQL,
            reverse_sql=REVERSE_DOWNGRADE_FENCE_SQL,
        ),
    ]
