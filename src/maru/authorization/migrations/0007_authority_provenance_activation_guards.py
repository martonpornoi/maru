"""Install the dormant ADR 0044 exact-lineage cutover boundary.

The activation singleton is one-way evidence, while the pre-existing generation
latch makes an authority writer with an old MVCC snapshot observe the cutover or
serialization-fail.  All validation triggers remain dormant until activation.
"""

from typing import ClassVar

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

HARDEN_FOUNDATIONAL_AUTHORIZATION_FUNCTIONS_FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_validate_scoped_resource_binding()
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
      FROM public.workforce_position
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
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE OR REPLACE FUNCTION public.maru_validate_role_bundle_catalog()
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
               OR public.maru_authorization_capability_min_scope(code.value) < 0
       )
    THEN
        RAISE EXCEPTION 'role bundle contains an unknown or non-persistable capability'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE OR REPLACE FUNCTION public.maru_validate_capability_grant()
RETURNS trigger AS $$
DECLARE
    scoped_organization uuid;
    scoped_edition uuid;
    scoped_department uuid;
    minimum_scope smallint;
    parent_record public.authorization_capabilitygrant%ROWTYPE;
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
          FROM public.events_eventedition
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
          FROM public.workforce_department
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
          FROM public.authorization_scopedresourcebinding
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

    minimum_scope := public.maru_authorization_capability_min_scope(
        NEW.capability_code
    );
    IF minimum_scope < 0
       OR public.maru_authorization_scope_rank(
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
          FROM public.authorization_capabilitygrant
         WHERE id = NEW.delegated_from_id
         FOR UPDATE;

        IF parent_record.id IS NULL
           OR parent_record.principal_id IS DISTINCT FROM NEW.granted_by_id
           OR parent_record.capability_code IS DISTINCT FROM NEW.capability_code
           OR NOT public.maru_authorization_scope_contains(
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
              FROM public.authorization_capabilitygrant AS parent
             WHERE parent.id = NEW.delegated_from_id
            UNION ALL
            SELECT parent.id,
                   parent.delegated_from_id,
                   ancestors.path || parent.id,
                   parent.id = NEW.id OR parent.id = ANY(ancestors.path) AS cycle
              FROM ancestors
              JOIN public.authorization_capabilitygrant AS parent
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
        INSERT INTO public.authorization_scopev2writefence(
            singleton,
            first_written_at
        )
        VALUES (true, statement_timestamp())
        ON CONFLICT (singleton) DO NOTHING;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE OR REPLACE FUNCTION public.maru_validate_role_assignment()
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
      FROM public.authorization_rolebundle
     WHERE id = NEW.role_bundle_id
     FOR KEY SHARE;
    IF scoped_organization IS DISTINCT FROM NEW.organization_id THEN
        RAISE EXCEPTION 'role bundle belongs to another organization'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.edition_id IS NOT NULL THEN
        SELECT organization_id
          INTO scoped_organization
          FROM public.events_eventedition
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
          FROM public.workforce_department
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
          FROM public.authorization_scopedresourcebinding
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

    authority_scope := public.maru_authorization_scope_rank(
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
               OR public.maru_authorization_capability_min_scope(code.value) < 0
               OR authority_scope
                  < public.maru_authorization_capability_min_scope(code.value)
       )
    THEN
        RAISE EXCEPTION 'role bundle cannot be persisted at this scope'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.department_id IS NOT NULL OR NEW.resource_binding_id IS NOT NULL THEN
        INSERT INTO public.authorization_scopev2writefence(
            singleton,
            first_written_at
        )
        VALUES (true, statement_timestamp())
        ON CONFLICT (singleton) DO NOTHING;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

ALTER FUNCTION public.maru_authorization_capability_min_scope(text)
SET search_path = pg_catalog, public, pg_temp;
ALTER FUNCTION public.maru_authorization_scope_rank(uuid, uuid, uuid)
SET search_path = pg_catalog, public, pg_temp;
ALTER FUNCTION public.maru_authorization_scope_contains(
    uuid, uuid, uuid, uuid, uuid, uuid, uuid, uuid
)
SET search_path = pg_catalog, public, pg_temp;
ALTER FUNCTION public.maru_prevent_scoped_resource_binding_mutation()
SET search_path = pg_catalog, public, pg_temp;
ALTER FUNCTION public.maru_prevent_authority_record_delete()
SET search_path = pg_catalog, public, pg_temp;
ALTER FUNCTION public.maru_prevent_role_bundle_mutation()
SET search_path = pg_catalog, public, pg_temp;
"""


HARDEN_FOUNDATIONAL_AUTHORIZATION_FUNCTIONS_REVERSE_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_validate_scoped_resource_binding()
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

CREATE OR REPLACE FUNCTION public.maru_validate_role_bundle_catalog()
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

CREATE OR REPLACE FUNCTION public.maru_validate_capability_grant()
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

CREATE OR REPLACE FUNCTION public.maru_validate_role_assignment()
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

ALTER FUNCTION public.maru_authorization_capability_min_scope(text) RESET ALL;
ALTER FUNCTION public.maru_authorization_scope_rank(uuid, uuid, uuid) RESET ALL;
ALTER FUNCTION public.maru_authorization_scope_contains(
    uuid, uuid, uuid, uuid, uuid, uuid, uuid, uuid
) RESET ALL;
ALTER FUNCTION public.maru_validate_scoped_resource_binding() RESET ALL;
ALTER FUNCTION public.maru_prevent_scoped_resource_binding_mutation() RESET ALL;
ALTER FUNCTION public.maru_prevent_authority_record_delete() RESET ALL;
ALTER FUNCTION public.maru_validate_role_bundle_catalog() RESET ALL;
ALTER FUNCTION public.maru_validate_capability_grant() RESET ALL;
ALTER FUNCTION public.maru_validate_role_assignment() RESET ALL;
ALTER FUNCTION public.maru_prevent_role_bundle_mutation() RESET ALL;
"""


HARDEN_EXISTING_ISSUANCE_FUNCTIONS_FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_validate_authority_issuance_insert()
RETURNS trigger AS $$
DECLARE
    delegated_parent_id uuid;
    parent_issuance_ordinal bigint;
BEGIN
    IF NEW.capability_grant_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT delegated_from_id INTO delegated_parent_id
      FROM public.authorization_capabilitygrant
     WHERE id = NEW.capability_grant_id;

    IF delegated_parent_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT ordinal INTO parent_issuance_ordinal
      FROM public.authorization_authorityissuance
     WHERE capability_grant_id = delegated_parent_id;

    IF parent_issuance_ordinal IS NULL
       OR parent_issuance_ordinal >= NEW.ordinal THEN
        RAISE EXCEPTION 'delegated grant requires an earlier parent issuance'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE OR REPLACE FUNCTION public.maru_prevent_authority_issuance_mutation()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'authority issuances are immutable'
            USING ERRCODE = '23514';
    END IF;
    RAISE EXCEPTION 'authority issuances cannot be deleted'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE OR REPLACE FUNCTION public.maru_prevent_authority_control_mutation()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'authority controls are immutable'
            USING ERRCODE = '23514';
    END IF;
    RAISE EXCEPTION 'authority controls cannot be deleted'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

ALTER FUNCTION public.maru_validate_authority_control_insert()
SET search_path = pg_catalog, public, pg_temp;
"""


HARDEN_EXISTING_ISSUANCE_FUNCTIONS_REVERSE_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_validate_authority_issuance_insert()
RETURNS trigger AS $$
DECLARE
    delegated_parent_id uuid;
    parent_issuance_ordinal bigint;
BEGIN
    IF NEW.capability_grant_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT delegated_from_id INTO delegated_parent_id
      FROM authorization_capabilitygrant
     WHERE id = NEW.capability_grant_id;

    IF delegated_parent_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT ordinal INTO parent_issuance_ordinal
      FROM authorization_authorityissuance
     WHERE capability_grant_id = delegated_parent_id;

    IF parent_issuance_ordinal IS NULL
       OR parent_issuance_ordinal >= NEW.ordinal THEN
        RAISE EXCEPTION 'delegated grant requires an earlier parent issuance'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION public.maru_prevent_authority_issuance_mutation()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'authority issuances are immutable'
            USING ERRCODE = '23514';
    END IF;
    RAISE EXCEPTION 'authority issuances cannot be deleted'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION public.maru_prevent_authority_control_mutation()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'authority controls are immutable'
            USING ERRCODE = '23514';
    END IF;
    RAISE EXCEPTION 'authority controls cannot be deleted'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

ALTER FUNCTION public.maru_validate_authority_issuance_insert() RESET ALL;
ALTER FUNCTION public.maru_prevent_authority_issuance_mutation() RESET ALL;
ALTER FUNCTION public.maru_prevent_authority_control_mutation() RESET ALL;
ALTER FUNCTION public.maru_validate_authority_control_insert() RESET ALL;
"""

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_authority_provenance_test_reset_allowed()
RETURNS boolean AS $$
    SELECT current_database() LIKE 'test\_%' ESCAPE '\'
       AND current_setting(
               'maru.authority_provenance_test_reset',
               TRUE
           ) = 'on';
$$ LANGUAGE sql STABLE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_authority_provenance_is_active()
RETURNS boolean AS $$
    SELECT
        EXISTS (
            SELECT 1
              FROM public.authorization_provenanceactivationlatch
             WHERE singleton IS TRUE AND generation = 1
        )
        OR EXISTS (
            SELECT 1 FROM public.authorization_authorityprovenanceactivation
        );
$$ LANGUAGE sql STABLE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_lock_authority_provenance_writer()
RETURNS trigger AS $$
DECLARE
    latch_generation smallint;
    cutover_time timestamptz;
BEGIN
    PERFORM pg_advisory_xact_lock_shared(4400440007);

    SELECT generation
      INTO STRICT latch_generation
      FROM public.authorization_provenanceactivationlatch
     WHERE singleton IS TRUE
     FOR SHARE;

    IF latch_generation = 1 THEN
        SELECT activated_at
          INTO cutover_time
          FROM public.authorization_authorityprovenanceactivation
         WHERE singleton IS TRUE;
        IF cutover_time IS NULL THEN
            RAISE EXCEPTION 'authority provenance cutover state is inconsistent'
                USING ERRCODE = '23514';
        END IF;
        IF transaction_timestamp() < cutover_time THEN
            RAISE EXCEPTION
                'authority writer transaction predates provenance activation'
                USING ERRCODE = '40001';
        END IF;
    ELSIF latch_generation != 0 THEN
        RAISE EXCEPTION 'authority provenance latch generation is unknown'
            USING ERRCODE = '23514';
    END IF;

    IF TG_LEVEL = 'ROW' AND TG_OP = 'DELETE' THEN
        RETURN OLD;
    ELSIF TG_LEVEL = 'ROW' THEN
        RETURN NEW;
    END IF;
    RETURN NULL;
EXCEPTION
    WHEN NO_DATA_FOUND THEN
        RAISE EXCEPTION 'authority provenance activation latch is unavailable'
            USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guard_authority_provenance_latch()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'INSERT'
       AND pg_trigger_depth() = 2
       AND NEW.singleton IS TRUE
       AND NEW.generation IN (0, 1)
    THEN
        RETURN NEW;
    ELSIF TG_OP = 'UPDATE'
       AND pg_trigger_depth() = 2
       AND OLD.singleton IS TRUE
       AND NEW.singleton IS TRUE
       AND OLD.generation = 0
       AND NEW.generation = 1
    THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'authority provenance activation latch is immutable'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guard_authority_provenance_activation()
RETURNS trigger AS $$
DECLARE
    actor_kind varchar;
    actor_active boolean;
    transitioned integer;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'authority provenance activation is immutable'
            USING ERRCODE = '23514';
    ELSIF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'authority provenance activation cannot be deleted'
            USING ERRCODE = '23514';
    END IF;
    IF current_setting('transaction_isolation') != 'read committed' THEN
        RAISE EXCEPTION
            'authority provenance activation requires read committed isolation'
            USING ERRCODE = '25000';
    END IF;

    PERFORM pg_advisory_xact_lock(4400440007);

    SELECT account_kind, is_active
      INTO actor_kind, actor_active
      FROM public.identity_account
     WHERE id = NEW.activated_by_id;

    IF actor_kind IS DISTINCT FROM 'platform_administrator'
       OR actor_active IS DISTINCT FROM TRUE
    THEN
        RAISE EXCEPTION
            'authority provenance activation requires an active platform actor'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.singleton IS DISTINCT FROM TRUE
       OR NEW.contract_version IS DISTINCT FROM 'adr-0044-v1'
       OR NEW.policy_version IS DISTINCT FROM '2026-08-01.3'
       OR NEW.reason !~ '[^[:space:]]'
    THEN
        RAISE EXCEPTION 'authority provenance activation evidence is invalid'
            USING ERRCODE = '23514';
    END IF;

    NEW.activated_at := statement_timestamp();
    UPDATE public.authorization_provenanceactivationlatch
       SET generation = 1
     WHERE singleton IS TRUE AND generation = 0;
    GET DIAGNOSTICS transitioned = ROW_COUNT;
    IF transitioned != 1 THEN
        RAISE EXCEPTION 'authority provenance activation latch cannot transition'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_prevent_authority_provenance_truncate()
RETURNS trigger AS $$
BEGIN
    IF public.maru_authority_provenance_test_reset_allowed() THEN
        RETURN NULL;
    END IF;
    RAISE EXCEPTION 'authority provenance evidence cannot be truncated'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_reseed_authority_provenance_latch()
RETURNS trigger AS $$
BEGIN
    INSERT INTO public.authorization_provenanceactivationlatch
        (singleton, generation)
    VALUES (
        TRUE,
        CASE
            WHEN EXISTS (
                SELECT 1 FROM public.authorization_authorityprovenanceactivation
            ) THEN 1
            ELSE 0
        END
    );
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_authority_scope_is_current_v1(
    target_organization uuid,
    target_edition uuid,
    target_department uuid,
    target_binding uuid
)
RETURNS boolean AS $$
BEGIN
    IF target_organization IS NULL THEN
        RETURN FALSE;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.organizations_organization
         WHERE id = target_organization
    ) THEN
        RETURN FALSE;
    END IF;
    IF target_edition IS NULL THEN
        RETURN target_department IS NULL AND target_binding IS NULL;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.events_eventedition
         WHERE id = target_edition
           AND organization_id = target_organization
    ) THEN
        RETURN FALSE;
    END IF;
    IF target_department IS NULL THEN
        RETURN target_binding IS NULL;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.workforce_department
         WHERE id = target_department
           AND organization_id = target_organization
           AND edition_id = target_edition
    ) THEN
        RETURN FALSE;
    END IF;
    IF target_binding IS NULL THEN
        RETURN TRUE;
    END IF;
    RETURN EXISTS (
        SELECT 1 FROM public.authorization_scopedresourcebinding
         WHERE id = target_binding
           AND organization_id = target_organization
           AND edition_id = target_edition
           AND department_id = target_department
    );
END;
$$ LANGUAGE plpgsql STABLE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_authority_scope_contains_v1(
    source_organization uuid,
    source_edition uuid,
    source_department uuid,
    source_binding uuid,
    target_organization uuid,
    target_edition uuid,
    target_department uuid,
    target_binding uuid
)
RETURNS boolean AS $$
BEGIN
    IF source_organization IS DISTINCT FROM target_organization
       OR NOT public.maru_authority_scope_is_current_v1(
           source_organization,
           source_edition,
           source_department,
           source_binding
       )
       OR NOT public.maru_authority_scope_is_current_v1(
           target_organization,
           target_edition,
           target_department,
           target_binding
       )
    THEN
        RETURN FALSE;
    END IF;
    IF source_binding IS NOT NULL THEN
        RETURN source_binding = target_binding;
    ELSIF source_department IS NOT NULL THEN
        RETURN source_edition = target_edition
           AND source_department = target_department;
    ELSIF source_edition IS NOT NULL THEN
        RETURN source_edition = target_edition;
    END IF;
    RETURN TRUE;
END;
$$ LANGUAGE plpgsql STABLE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_assert_authority_issuance_complete_internal(
    target_ordinal bigint,
    lineage_path bigint[],
    lineage_depth integer
)
RETURNS void AS $$
DECLARE
    grant_id uuid;
    bundle_id uuid;
    assignment_id uuid;
    delegated_parent_id uuid;
    assignment_bundle_id uuid;
    target_actor uuid;
    target_approver uuid;
    target_recipient uuid;
    issuance_policy varchar;
    issuance_evaluation timestamptz;
    target_count integer;
    target_is_delegated boolean := FALSE;
    target_is_board boolean := FALSE;
    control_count integer;
    actor_count integer;
    approver_count integer;
    principal_count integer;
    attribution_count integer;
    metadata_count integer;
    persistent_count integer;
    bootstrap_count integer;
    acceptance_count integer;
    related_ordinal bigint;
    source_record record;
    next_path bigint[];
BEGIN
    IF lineage_depth >= 64 THEN
        RAISE EXCEPTION 'authority lineage exceeds the supported depth'
            USING ERRCODE = '23514';
    END IF;
    IF target_ordinal = ANY(lineage_path) THEN
        RAISE EXCEPTION 'authority lineage contains a cycle'
            USING ERRCODE = '23514';
    END IF;
    next_path := array_append(lineage_path, target_ordinal);

    SELECT
        issuance.capability_grant_id,
        issuance.role_bundle_id,
        issuance.role_assignment_id,
        issuance.policy_version,
        issuance.evaluated_at,
        capability_grant.delegated_from_id,
        role_assignment.role_bundle_id,
        CASE
            WHEN issuance.capability_grant_id IS NOT NULL
                THEN capability_grant.granted_by_id
            WHEN issuance.role_bundle_id IS NOT NULL
                THEN role_bundle.created_by_id
            ELSE role_assignment.granted_by_id
        END,
        CASE
            WHEN issuance.capability_grant_id IS NOT NULL
                THEN capability_grant.approved_by_id
            WHEN issuance.role_bundle_id IS NOT NULL
                THEN role_bundle.approved_by_id
            ELSE role_assignment.approved_by_id
        END,
        COALESCE(capability_grant.principal_id, role_assignment.principal_id),
        COALESCE(role_bundle.code, assignment_bundle.code) = 'executive-board'
      INTO
        grant_id,
        bundle_id,
        assignment_id,
        issuance_policy,
        issuance_evaluation,
        delegated_parent_id,
        assignment_bundle_id,
        target_actor,
        target_approver,
        target_recipient,
        target_is_board
      FROM public.authorization_authorityissuance AS issuance
      LEFT JOIN public.authorization_capabilitygrant AS capability_grant
        ON capability_grant.id = issuance.capability_grant_id
      LEFT JOIN public.authorization_rolebundle AS role_bundle
        ON role_bundle.id = issuance.role_bundle_id
      LEFT JOIN public.authorization_roleassignment AS role_assignment
        ON role_assignment.id = issuance.role_assignment_id
      LEFT JOIN public.authorization_rolebundle AS assignment_bundle
        ON assignment_bundle.id = role_assignment.role_bundle_id
     WHERE issuance.ordinal = target_ordinal;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'authority issuance completeness target is unavailable'
            USING ERRCODE = '23514';
    END IF;
    target_count :=
        (grant_id IS NOT NULL)::integer
        + (bundle_id IS NOT NULL)::integer
        + (assignment_id IS NOT NULL)::integer;
    IF target_count != 1 OR issuance_policy !~ '[^[:space:]]' THEN
        RAISE EXCEPTION 'authority issuance has malformed target or metadata'
            USING ERRCODE = '23514';
    END IF;
    target_is_delegated := grant_id IS NOT NULL
        AND delegated_parent_id IS NOT NULL;

    SELECT
        COUNT(*),
        COUNT(*) FILTER (WHERE role = 'actor'),
        COUNT(*) FILTER (WHERE role = 'approver'),
        COUNT(DISTINCT principal_id),
        COUNT(*) FILTER (
            WHERE (role = 'actor' AND principal_id = target_actor)
               OR (role = 'approver' AND principal_id = target_approver)
        ),
        COUNT(*) FILTER (
            WHERE policy_version = issuance_policy
              AND evaluated_at = issuance_evaluation
        ),
        COUNT(*) FILTER (WHERE basis = 'persistent_authority'),
        COUNT(*) FILTER (WHERE basis = 'platform_representation_bootstrap'),
        COUNT(*) FILTER (WHERE basis = 'representation_acceptance')
      INTO
        control_count,
        actor_count,
        approver_count,
        principal_count,
        attribution_count,
        metadata_count,
        persistent_count,
        bootstrap_count,
        acceptance_count
      FROM public.authorization_authoritycontrol
     WHERE issuance_id = target_ordinal;

    IF target_is_delegated THEN
        IF control_count != 0 THEN
            RAISE EXCEPTION 'delegated authority issuance must have zero controls'
                USING ERRCODE = '23514';
        END IF;
        SELECT ordinal INTO related_ordinal
          FROM public.authorization_authorityissuance
         WHERE capability_grant_id = delegated_parent_id;
        IF related_ordinal IS NULL OR related_ordinal >= target_ordinal THEN
            RAISE EXCEPTION
                'delegated authority requires an earlier complete parent issuance'
                USING ERRCODE = '23514';
        END IF;
        PERFORM public.maru_assert_authority_issuance_complete_internal(
            related_ordinal,
            next_path,
            lineage_depth + 1
        );
    ELSE
        IF target_actor IS NULL
           OR target_approver IS NULL
           OR target_actor = target_approver
           OR target_approver = target_recipient
           OR control_count != 2
           OR actor_count != 1
           OR approver_count != 1
           OR principal_count != 2
           OR attribution_count != 2
           OR metadata_count != 2
        THEN
            RAISE EXCEPTION
                'authority issuance requires exact distinct actor and approver controls'
                USING ERRCODE = '23514';
        END IF;
        IF target_is_board THEN
            IF bootstrap_count != 1 OR acceptance_count != 1 THEN
                RAISE EXCEPTION
                    'Executive Board issuance requires exact ceremony controls'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF persistent_count != 2 THEN
            RAISE EXCEPTION
                'ordinary authority issuance requires persistent controls'
                USING ERRCODE = '23514';
        END IF;

        FOR source_record IN
            SELECT source_issuance_id
              FROM public.authorization_authoritycontrol
             WHERE issuance_id = target_ordinal
               AND basis = 'persistent_authority'
             ORDER BY role
        LOOP
            IF source_record.source_issuance_id IS NULL
               OR source_record.source_issuance_id >= target_ordinal
            THEN
                RAISE EXCEPTION
                    'persistent control requires an earlier source issuance'
                    USING ERRCODE = '23514';
            END IF;
            PERFORM public.maru_assert_authority_issuance_complete_internal(
                source_record.source_issuance_id,
                next_path,
                lineage_depth + 1
            );
        END LOOP;
    END IF;

    IF assignment_id IS NOT NULL THEN
        SELECT ordinal INTO related_ordinal
          FROM public.authorization_authorityissuance
         WHERE role_bundle_id = assignment_bundle_id;
        IF related_ordinal IS NULL OR related_ordinal >= target_ordinal THEN
            RAISE EXCEPTION
                'role assignment requires an earlier complete bundle issuance'
                USING ERRCODE = '23514';
        END IF;
        PERFORM public.maru_assert_authority_issuance_complete_internal(
            related_ordinal,
            next_path,
            lineage_depth + 1
        );
    END IF;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_assert_authority_issuance_complete(target_ordinal bigint)
RETURNS void AS $$
BEGIN
    IF NOT public.maru_authority_provenance_is_active() THEN
        RETURN;
    END IF;
    PERFORM public.maru_assert_authority_issuance_complete_internal(
        target_ordinal,
        ARRAY[]::bigint[],
        0
    );
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_assert_authority_target_complete(
    target_kind varchar,
    target_id uuid
)
RETURNS void AS $$
DECLARE
    issuance_count integer;
    issuance_ordinal bigint;
BEGIN
    IF NOT public.maru_authority_provenance_is_active() THEN
        RETURN;
    END IF;
    IF target_kind = 'capability_grant' THEN
        SELECT COUNT(*), MIN(ordinal)
          INTO issuance_count, issuance_ordinal
          FROM public.authorization_authorityissuance
         WHERE capability_grant_id = target_id;
    ELSIF target_kind = 'role_bundle' THEN
        SELECT COUNT(*), MIN(ordinal)
          INTO issuance_count, issuance_ordinal
          FROM public.authorization_authorityissuance
         WHERE role_bundle_id = target_id;
    ELSIF target_kind = 'role_assignment' THEN
        SELECT COUNT(*), MIN(ordinal)
          INTO issuance_count, issuance_ordinal
          FROM public.authorization_authorityissuance
         WHERE role_assignment_id = target_id;
    ELSE
        RAISE EXCEPTION 'authority provenance target kind is unknown'
            USING ERRCODE = '23514';
    END IF;
    IF issuance_count != 1 OR issuance_ordinal IS NULL THEN
        RAISE EXCEPTION 'authority target requires exactly one issuance'
            USING ERRCODE = '23514';
    END IF;
    PERFORM public.maru_assert_authority_issuance_complete_internal(
        issuance_ordinal,
        ARRAY[]::bigint[],
        0
    );
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_authority_bundle_historical_v1(
    target_bundle uuid,
    effective_evaluation timestamptz,
    expected_representation uuid,
    lineage_path bigint[],
    lineage_depth integer
)
RETURNS boolean AS $$
BEGIN
    RETURN FALSE;
END;
$$ LANGUAGE plpgsql STABLE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_authority_issuance_valid_v1(
    target_ordinal bigint,
    expected_principal uuid,
    required_capability varchar,
    target_organization uuid,
    target_edition uuid,
    target_department uuid,
    target_binding uuid,
    requested_effective_from timestamptz,
    requested_expires_at timestamptz,
    effective_evaluation timestamptz,
    require_current boolean,
    persistent_horizon boolean,
    lineage_path bigint[],
    lineage_depth integer
)
RETURNS boolean AS $$
DECLARE
    issuance_policy varchar;
    issuance_evaluation timestamptz;
    grant_id uuid;
    assignment_id uuid;
    bundle_target_id uuid;
    source_kind varchar;
    source_principal uuid;
    source_actor uuid;
    source_approver uuid;
    source_organization uuid;
    source_edition uuid;
    source_department uuid;
    source_binding uuid;
    source_effective_from timestamptz;
    source_expires_at timestamptz;
    source_revoked_at timestamptz;
    source_reason varchar;
    source_capability varchar;
    source_bundle_id uuid;
    source_bundle_code varchar;
    source_bundle_name varchar;
    source_bundle_version integer;
    source_capabilities varchar[];
    delegated_parent_id uuid;
    principal_kind varchar;
    principal_active boolean;
    principal_verified boolean;
    controls_count integer;
    actor_count integer;
    approver_count integer;
    distinct_principals integer;
    parent_ordinal bigint;
    control_record record;
    expected_control_principal uuid;
    next_path bigint[];
    actor_control record;
    approver_control record;
    representation_record record;
    approval_appointment record;
    current_appointment record;
    current_appointment_found boolean;
    membership_valid boolean;
BEGIN
    IF target_ordinal IS NULL
       OR expected_principal IS NULL
       OR required_capability !~ '[^[:space:]]'
       OR requested_effective_from IS NULL
       OR effective_evaluation IS NULL
       OR lineage_depth >= 64
       OR target_ordinal = ANY(lineage_path)
    THEN
        RETURN FALSE;
    END IF;
    next_path := array_append(lineage_path, target_ordinal);

    SELECT
        issuance.policy_version,
        issuance.evaluated_at,
        issuance.capability_grant_id,
        issuance.role_assignment_id,
        issuance.role_bundle_id,
        CASE
            WHEN issuance.capability_grant_id IS NOT NULL THEN 'grant'
            WHEN issuance.role_assignment_id IS NOT NULL THEN 'assignment'
            ELSE 'bundle'
        END,
        COALESCE(capability_grant.principal_id, role_assignment.principal_id),
        COALESCE(capability_grant.granted_by_id, role_assignment.granted_by_id),
        COALESCE(capability_grant.approved_by_id, role_assignment.approved_by_id),
        COALESCE(capability_grant.organization_id, role_assignment.organization_id),
        COALESCE(capability_grant.edition_id, role_assignment.edition_id),
        COALESCE(capability_grant.department_id, role_assignment.department_id),
        COALESCE(
            capability_grant.resource_binding_id,
            role_assignment.resource_binding_id
        ),
        COALESCE(capability_grant.effective_from, role_assignment.effective_from),
        COALESCE(capability_grant.expires_at, role_assignment.expires_at),
        COALESCE(capability_grant.revoked_at, role_assignment.revoked_at),
        COALESCE(capability_grant.reason, role_assignment.reason),
        capability_grant.capability_code,
        role_assignment.role_bundle_id,
        assignment_bundle.code,
        assignment_bundle.name,
        assignment_bundle.version,
        assignment_bundle.capability_codes,
        capability_grant.delegated_from_id
      INTO
        issuance_policy,
        issuance_evaluation,
        grant_id,
        assignment_id,
        bundle_target_id,
        source_kind,
        source_principal,
        source_actor,
        source_approver,
        source_organization,
        source_edition,
        source_department,
        source_binding,
        source_effective_from,
        source_expires_at,
        source_revoked_at,
        source_reason,
        source_capability,
        source_bundle_id,
        source_bundle_code,
        source_bundle_name,
        source_bundle_version,
        source_capabilities,
        delegated_parent_id
      FROM public.authorization_authorityissuance AS issuance
      LEFT JOIN public.authorization_capabilitygrant AS capability_grant
        ON capability_grant.id = issuance.capability_grant_id
      LEFT JOIN public.authorization_roleassignment AS role_assignment
        ON role_assignment.id = issuance.role_assignment_id
      LEFT JOIN public.authorization_rolebundle AS assignment_bundle
        ON assignment_bundle.id = role_assignment.role_bundle_id
     WHERE issuance.ordinal = target_ordinal;

    IF NOT FOUND
       OR source_kind = 'bundle'
       OR (grant_id IS NOT NULL)::integer
          + (assignment_id IS NOT NULL)::integer
          + (bundle_target_id IS NOT NULL)::integer != 1
       OR issuance_policy !~ '[^[:space:]]'
       OR issuance_evaluation > effective_evaluation
       OR source_principal IS DISTINCT FROM expected_principal
       OR source_organization IS DISTINCT FROM target_organization
       OR NOT public.maru_authority_scope_contains_v1(
           source_organization,
           source_edition,
           source_department,
           source_binding,
           target_organization,
           target_edition,
           target_department,
           target_binding
       )
    THEN
        RETURN FALSE;
    END IF;

    IF source_kind = 'grant' THEN
        IF source_capability IS DISTINCT FROM required_capability THEN
            RETURN FALSE;
        END IF;
    ELSIF source_capabilities IS NULL
       OR NOT required_capability = ANY(source_capabilities)
    THEN
        RETURN FALSE;
    END IF;

    SELECT account_kind, is_active, email_verified_at IS NOT NULL
      INTO principal_kind, principal_active, principal_verified
      FROM public.identity_account
     WHERE id = source_principal;
    IF principal_kind IS DISTINCT FROM 'person'
       OR (require_current AND principal_active IS DISTINCT FROM TRUE)
       OR source_effective_from > effective_evaluation
       OR source_effective_from > requested_effective_from
       OR (
           source_expires_at IS NOT NULL
           AND source_expires_at <= effective_evaluation
       )
       OR (
           require_current
           AND source_revoked_at IS NOT NULL
       )
       OR (
           NOT require_current
           AND source_revoked_at IS NOT NULL
           AND source_revoked_at <= effective_evaluation
       )
       OR (
           persistent_horizon
           AND source_expires_at IS NOT NULL
           AND (
               requested_expires_at IS NULL
               OR requested_expires_at > source_expires_at
           )
       )
    THEN
        RETURN FALSE;
    END IF;

    SELECT
        COUNT(*),
        COUNT(*) FILTER (WHERE role = 'actor'),
        COUNT(*) FILTER (WHERE role = 'approver'),
        COUNT(DISTINCT principal_id)
      INTO controls_count, actor_count, approver_count, distinct_principals
      FROM public.authorization_authoritycontrol
     WHERE issuance_id = target_ordinal;

    IF source_kind = 'grant' AND delegated_parent_id IS NOT NULL THEN
        IF controls_count != 0 THEN
            RETURN FALSE;
        END IF;
        SELECT ordinal INTO parent_ordinal
          FROM public.authorization_authorityissuance
         WHERE capability_grant_id = delegated_parent_id;
        RETURN parent_ordinal IS NOT NULL
           AND parent_ordinal < target_ordinal
           AND public.maru_authority_issuance_valid_v1(
               parent_ordinal,
               source_actor,
               source_capability,
               source_organization,
               source_edition,
               source_department,
               source_binding,
               source_effective_from,
               source_expires_at,
               effective_evaluation,
               require_current,
               TRUE,
               next_path,
               lineage_depth + 1
           );
    END IF;

    IF source_actor IS NULL
       OR source_approver IS NULL
       OR source_actor = source_approver
       OR source_approver = source_principal
       OR controls_count != 2
       OR actor_count != 1
       OR approver_count != 1
       OR distinct_principals != 2
    THEN
        RETURN FALSE;
    END IF;

    IF source_kind = 'assignment'
       AND source_bundle_code = 'executive-board'
    THEN
        IF source_bundle_name IS DISTINCT FROM 'Executive Board'
           OR source_bundle_version IS DISTINCT FROM 1
           OR source_capabilities IS NULL
           OR cardinality(source_capabilities) != 12
           OR ARRAY(
               SELECT unnest(source_capabilities) ORDER BY 1
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
           OR source_edition IS NOT NULL
           OR source_department IS NOT NULL
           OR source_binding IS NOT NULL
           OR source_effective_from IS DISTINCT FROM issuance_evaluation
           OR source_expires_at IS NOT NULL
        THEN
            RETURN FALSE;
        END IF;
        SELECT * INTO actor_control
          FROM public.authorization_authoritycontrol
         WHERE issuance_id = target_ordinal AND role = 'actor';
        SELECT * INTO approver_control
          FROM public.authorization_authoritycontrol
         WHERE issuance_id = target_ordinal AND role = 'approver';
        IF actor_control.principal_id IS DISTINCT FROM source_actor
           OR approver_control.principal_id IS DISTINCT FROM source_approver
           OR actor_control.basis IS DISTINCT FROM
                'platform_representation_bootstrap'
           OR actor_control.source_issuance_id IS NOT NULL
           OR actor_control.representation_id IS NULL
           OR actor_control.appointment_id IS NOT NULL
           OR approver_control.basis IS DISTINCT FROM
                'representation_acceptance'
           OR approver_control.source_issuance_id IS NOT NULL
           OR approver_control.representation_id IS NOT NULL
           OR approver_control.appointment_id IS NULL
           OR actor_control.policy_version IS DISTINCT FROM issuance_policy
           OR approver_control.policy_version IS DISTINCT FROM issuance_policy
           OR actor_control.evaluated_at IS DISTINCT FROM issuance_evaluation
           OR approver_control.evaluated_at IS DISTINCT FROM issuance_evaluation
        THEN
            RETURN FALSE;
        END IF;
        SELECT
            representation.id,
            representation.organization_id,
            representation.code,
            representation.name,
            representation.state,
            representation.activated_by_id,
            representation.activated_at,
            representation.activation_reason,
            activator.account_kind
          INTO representation_record
          FROM public.organizations_organizationrepresentation AS representation
          JOIN public.identity_account AS activator
            ON activator.id = representation.activated_by_id
         WHERE representation.id = actor_control.representation_id;
        IF NOT FOUND
           OR representation_record.organization_id
                IS DISTINCT FROM source_organization
           OR representation_record.code IS DISTINCT FROM 'executive_board'
           OR representation_record.name IS DISTINCT FROM 'Executive Board'
           OR representation_record.activated_by_id
                IS DISTINCT FROM source_actor
           OR representation_record.account_kind
                IS DISTINCT FROM 'platform_administrator'
           OR representation_record.activated_at
                IS DISTINCT FROM issuance_evaluation
           OR source_reason
                IS DISTINCT FROM representation_record.activation_reason
           OR representation_record.activated_at > effective_evaluation
        THEN
            RETURN FALSE;
        END IF;
        SELECT
            appointment.account_id,
            appointment.representation_id,
            appointment.state,
            appointment.role,
            appointment.responded_at
          INTO approval_appointment
          FROM public.organizations_representationappointment AS appointment
         WHERE appointment.id = approver_control.appointment_id;
        IF NOT FOUND
           OR approval_appointment.account_id
                IS DISTINCT FROM source_approver
           OR approval_appointment.representation_id
                IS DISTINCT FROM representation_record.id
           OR approval_appointment.state NOT IN ('active', 'ended')
           OR approval_appointment.role IS DISTINCT FROM 'controller'
           OR approval_appointment.responded_at IS NULL
           OR approval_appointment.responded_at > issuance_evaluation
        THEN
            RETURN FALSE;
        END IF;

        IF require_current THEN
            SELECT
                appointment.account_id,
                appointment.representation_id,
                appointment.state,
                appointment.role,
                appointment.responded_at,
                appointment.activated_at,
                appointment.ended_at
              INTO current_appointment
              FROM public.organizations_representationappointment AS appointment
             WHERE appointment.role_assignment_id = assignment_id
               AND appointment.representation_id = representation_record.id
               AND appointment.account_id = source_principal;
            IF NOT FOUND
               OR representation_record.state IS DISTINCT FROM 'active'
               OR principal_verified IS DISTINCT FROM TRUE
               OR current_appointment.state IS DISTINCT FROM 'active'
               OR current_appointment.role IS DISTINCT FROM 'controller'
               OR current_appointment.ended_at IS NOT NULL
               OR current_appointment.responded_at IS NULL
               OR current_appointment.responded_at > issuance_evaluation
               OR current_appointment.activated_at
                    IS DISTINCT FROM issuance_evaluation
               OR NOT EXISTS (
                   SELECT 1 FROM public.organizations_organization
                    WHERE id = source_organization AND lifecycle = 'active'
               )
               OR NOT EXISTS (
                   SELECT 1 FROM public.organizations_organizationmembership
                    WHERE organization_id = source_organization
                      AND account_id = source_principal
                      AND state = 'active'
                      AND relationship_label = 'Executive Board controller'
                      AND started_at IS NOT NULL
                      AND ended_at IS NULL
               )
            THEN
                RETURN FALSE;
            END IF;
        ELSE
            SELECT
                appointment.account_id,
                appointment.representation_id,
                appointment.state,
                appointment.role,
                appointment.responded_at,
                appointment.activated_at,
                appointment.ended_at
              INTO current_appointment
              FROM public.organizations_representationappointment AS appointment
             WHERE appointment.role_assignment_id = assignment_id
               AND appointment.representation_id = representation_record.id
               AND appointment.account_id = source_principal
               AND appointment.state IN ('active', 'ended')
               AND appointment.activated_at <= effective_evaluation
               AND (
                   appointment.ended_at IS NULL
                   OR appointment.ended_at > effective_evaluation
               );
            current_appointment_found := FOUND;
            SELECT EXISTS (
                SELECT 1 FROM public.organizations_organizationmembership
                 WHERE organization_id = source_organization
                   AND account_id = source_principal
                   AND started_at IS NOT NULL
                   AND started_at <= effective_evaluation
                   AND (ended_at IS NULL OR ended_at > effective_evaluation)
            ) INTO membership_valid;
            IF NOT current_appointment_found
               OR current_appointment.role IS DISTINCT FROM 'controller'
               OR current_appointment.responded_at IS NULL
               OR current_appointment.responded_at > issuance_evaluation
               OR NOT membership_valid
               OR NOT EXISTS (
                   SELECT 1 FROM public.organizations_organization
                    WHERE id = source_organization
               )
            THEN
                RETURN FALSE;
            END IF;
        END IF;

        RETURN public.maru_authority_bundle_historical_v1(
            source_bundle_id,
            effective_evaluation,
            representation_record.id,
            next_path,
            lineage_depth + 1
        );
    END IF;

    IF source_kind = 'assignment'
       AND NOT public.maru_authority_bundle_historical_v1(
           source_bundle_id,
           effective_evaluation,
           NULL,
           next_path,
           lineage_depth + 1
       )
    THEN
        RETURN FALSE;
    END IF;

    FOR control_record IN
        SELECT *
          FROM public.authorization_authoritycontrol
         WHERE issuance_id = target_ordinal
         ORDER BY role
    LOOP
        expected_control_principal := CASE control_record.role
            WHEN 'actor' THEN source_actor
            WHEN 'approver' THEN source_approver
            ELSE NULL
        END;
        SELECT account_kind, is_active
          INTO principal_kind, principal_active
          FROM public.identity_account
         WHERE id = control_record.principal_id;
        IF expected_control_principal IS NULL
           OR control_record.principal_id
                IS DISTINCT FROM expected_control_principal
           OR control_record.basis IS DISTINCT FROM 'persistent_authority'
           OR control_record.source_issuance_id IS NULL
           OR control_record.source_issuance_id >= target_ordinal
           OR control_record.representation_id IS NOT NULL
           OR control_record.appointment_id IS NOT NULL
           OR control_record.policy_version IS DISTINCT FROM issuance_policy
           OR control_record.evaluated_at IS DISTINCT FROM issuance_evaluation
           OR principal_kind IS DISTINCT FROM 'person'
           OR (require_current AND principal_active IS DISTINCT FROM TRUE)
           OR NOT public.maru_authority_issuance_valid_v1(
               control_record.source_issuance_id,
               expected_control_principal,
               CASE
                   WHEN source_kind = 'grant'
                       THEN 'authorization.grant_direct'
                   ELSE 'authorization.manage_roles'
               END,
               source_organization,
               source_edition,
               source_department,
               source_binding,
               source_effective_from,
               source_expires_at,
               effective_evaluation,
               require_current,
               TRUE,
               next_path,
               lineage_depth + 1
           )
        THEN
            RETURN FALSE;
        END IF;
    END LOOP;
    RETURN TRUE;
END;
$$ LANGUAGE plpgsql STABLE
SET search_path = pg_catalog, public, pg_temp;

CREATE OR REPLACE FUNCTION public.maru_authority_bundle_historical_v1(
    target_bundle uuid,
    effective_evaluation timestamptz,
    expected_representation uuid,
    lineage_path bigint[],
    lineage_depth integer
)
RETURNS boolean AS $$
DECLARE
    issuance_ordinal bigint;
    issuance_policy varchar;
    issuance_evaluation timestamptz;
    bundle_organization uuid;
    bundle_code varchar;
    bundle_name varchar;
    bundle_version integer;
    bundle_capabilities varchar[];
    bundle_actor uuid;
    bundle_approver uuid;
    bundle_reason varchar;
    controls_count integer;
    actor_count integer;
    approver_count integer;
    distinct_principals integer;
    control_record record;
    expected_control_principal uuid;
    actor_control record;
    approver_control record;
    representation_record record;
    appointment_record record;
    principal_kind varchar;
    next_path bigint[];
BEGIN
    SELECT
        issuance.ordinal,
        issuance.policy_version,
        issuance.evaluated_at,
        bundle.organization_id,
        bundle.code,
        bundle.name,
        bundle.version,
        bundle.capability_codes,
        bundle.created_by_id,
        bundle.approved_by_id,
        bundle.reason
      INTO
        issuance_ordinal,
        issuance_policy,
        issuance_evaluation,
        bundle_organization,
        bundle_code,
        bundle_name,
        bundle_version,
        bundle_capabilities,
        bundle_actor,
        bundle_approver,
        bundle_reason
      FROM public.authorization_rolebundle AS bundle
      JOIN public.authorization_authorityissuance AS issuance
        ON issuance.role_bundle_id = bundle.id
     WHERE bundle.id = target_bundle;
    IF NOT FOUND
       OR effective_evaluation IS NULL
       OR issuance_evaluation > effective_evaluation
       OR issuance_policy !~ '[^[:space:]]'
       OR lineage_depth >= 64
       OR issuance_ordinal = ANY(lineage_path)
       OR bundle_actor IS NULL
       OR bundle_approver IS NULL
       OR bundle_actor = bundle_approver
    THEN
        RETURN FALSE;
    END IF;
    next_path := array_append(lineage_path, issuance_ordinal);

    SELECT
        COUNT(*),
        COUNT(*) FILTER (WHERE role = 'actor'),
        COUNT(*) FILTER (WHERE role = 'approver'),
        COUNT(DISTINCT principal_id)
      INTO controls_count, actor_count, approver_count, distinct_principals
      FROM public.authorization_authoritycontrol
     WHERE issuance_id = issuance_ordinal;
    IF controls_count != 2
       OR actor_count != 1
       OR approver_count != 1
       OR distinct_principals != 2
    THEN
        RETURN FALSE;
    END IF;

    IF bundle_code = 'executive-board' THEN
        IF bundle_name IS DISTINCT FROM 'Executive Board'
           OR bundle_version IS DISTINCT FROM 1
           OR bundle_capabilities IS NULL
           OR cardinality(bundle_capabilities) != 12
           OR ARRAY(
               SELECT unnest(bundle_capabilities) ORDER BY 1
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
        THEN
            RETURN FALSE;
        END IF;
        SELECT * INTO actor_control
          FROM public.authorization_authoritycontrol
         WHERE issuance_id = issuance_ordinal AND role = 'actor';
        SELECT * INTO approver_control
          FROM public.authorization_authoritycontrol
         WHERE issuance_id = issuance_ordinal AND role = 'approver';
        IF actor_control.principal_id IS DISTINCT FROM bundle_actor
           OR approver_control.principal_id IS DISTINCT FROM bundle_approver
           OR actor_control.basis IS DISTINCT FROM
                'platform_representation_bootstrap'
           OR actor_control.source_issuance_id IS NOT NULL
           OR actor_control.representation_id IS NULL
           OR actor_control.appointment_id IS NOT NULL
           OR approver_control.basis IS DISTINCT FROM
                'representation_acceptance'
           OR approver_control.source_issuance_id IS NOT NULL
           OR approver_control.representation_id IS NOT NULL
           OR approver_control.appointment_id IS NULL
           OR actor_control.policy_version IS DISTINCT FROM issuance_policy
           OR approver_control.policy_version IS DISTINCT FROM issuance_policy
           OR actor_control.evaluated_at IS DISTINCT FROM issuance_evaluation
           OR approver_control.evaluated_at IS DISTINCT FROM issuance_evaluation
        THEN
            RETURN FALSE;
        END IF;
        SELECT
            representation.id,
            representation.organization_id,
            representation.code,
            representation.name,
            representation.activated_by_id,
            representation.activated_at,
            representation.activation_reason,
            activator.account_kind
          INTO representation_record
          FROM public.organizations_organizationrepresentation AS representation
          JOIN public.identity_account AS activator
            ON activator.id = representation.activated_by_id
         WHERE representation.id = actor_control.representation_id;
        IF NOT FOUND
           OR representation_record.organization_id
                IS DISTINCT FROM bundle_organization
           OR representation_record.code IS DISTINCT FROM 'executive_board'
           OR representation_record.name IS DISTINCT FROM 'Executive Board'
           OR representation_record.activated_by_id
                IS DISTINCT FROM bundle_actor
           OR representation_record.account_kind
                IS DISTINCT FROM 'platform_administrator'
           OR representation_record.activated_at
                IS DISTINCT FROM issuance_evaluation
           OR bundle_reason
                IS DISTINCT FROM representation_record.activation_reason
           OR (
               expected_representation IS NOT NULL
               AND representation_record.id
                    IS DISTINCT FROM expected_representation
           )
        THEN
            RETURN FALSE;
        END IF;
        SELECT
            appointment.account_id,
            appointment.representation_id,
            appointment.state,
            appointment.role,
            appointment.responded_at
          INTO appointment_record
          FROM public.organizations_representationappointment AS appointment
         WHERE appointment.id = approver_control.appointment_id;
        RETURN FOUND
           AND appointment_record.account_id IS NOT DISTINCT FROM bundle_approver
           AND appointment_record.representation_id
                IS NOT DISTINCT FROM representation_record.id
           AND appointment_record.state IN ('active', 'ended')
           AND appointment_record.role = 'controller'
           AND appointment_record.responded_at IS NOT NULL
           AND appointment_record.responded_at <= issuance_evaluation;
    END IF;

    FOR control_record IN
        SELECT *
          FROM public.authorization_authoritycontrol
         WHERE issuance_id = issuance_ordinal
         ORDER BY role
    LOOP
        expected_control_principal := CASE control_record.role
            WHEN 'actor' THEN bundle_actor
            WHEN 'approver' THEN bundle_approver
            ELSE NULL
        END;
        SELECT account_kind INTO principal_kind
          FROM public.identity_account
         WHERE id = control_record.principal_id;
        IF expected_control_principal IS NULL
           OR control_record.principal_id
                IS DISTINCT FROM expected_control_principal
           OR control_record.basis IS DISTINCT FROM 'persistent_authority'
           OR control_record.source_issuance_id IS NULL
           OR control_record.source_issuance_id >= issuance_ordinal
           OR control_record.representation_id IS NOT NULL
           OR control_record.appointment_id IS NOT NULL
           OR control_record.policy_version IS DISTINCT FROM issuance_policy
           OR control_record.evaluated_at IS DISTINCT FROM issuance_evaluation
           OR principal_kind IS DISTINCT FROM 'person'
           OR NOT public.maru_authority_issuance_valid_v1(
               control_record.source_issuance_id,
               expected_control_principal,
               'authorization.manage_roles',
               bundle_organization,
               NULL,
               NULL,
               NULL,
               issuance_evaluation,
               NULL,
               issuance_evaluation,
               FALSE,
               FALSE,
               next_path,
               lineage_depth + 1
           )
        THEN
            RETURN FALSE;
        END IF;
    END LOOP;
    RETURN TRUE;
END;
$$ LANGUAGE plpgsql STABLE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_assert_authority_provenance_activation()
RETURNS void AS $$
DECLARE
    activation_record record;
    activation_count integer;
    latch_count integer;
    audit_count integer;
    target_record record;
    bundle_record record;
    capability_code varchar;
    issuance_ordinal bigint;
BEGIN
    SELECT COUNT(*) INTO activation_count
      FROM public.authorization_authorityprovenanceactivation;
    SELECT COUNT(*) INTO latch_count
      FROM public.authorization_provenanceactivationlatch
     WHERE singleton IS TRUE AND generation = 1;
    IF activation_count != 1 OR latch_count != 1 THEN
        RAISE EXCEPTION 'authority provenance activation state is incomplete'
            USING ERRCODE = '23514';
    END IF;

    SELECT
        marker.contract_version,
        marker.policy_version,
        marker.activated_by_id,
        marker.reason,
        marker.correlation_id,
        marker.activated_at,
        marker.xmin AS marker_xmin,
        actor.account_kind,
        actor.is_active
      INTO STRICT activation_record
      FROM public.authorization_authorityprovenanceactivation AS marker
      JOIN public.identity_account AS actor ON actor.id = marker.activated_by_id
     WHERE marker.singleton IS TRUE;
    IF activation_record.contract_version IS DISTINCT FROM 'adr-0044-v1'
       OR activation_record.policy_version IS DISTINCT FROM '2026-08-01.3'
       OR activation_record.reason !~ '[^[:space:]]'
       OR activation_record.account_kind
            IS DISTINCT FROM 'platform_administrator'
       OR activation_record.is_active IS DISTINCT FROM TRUE
       OR activation_record.marker_xmin
            IS DISTINCT FROM pg_current_xact_id()::xid
    THEN
        RAISE EXCEPTION 'authority provenance activation evidence is invalid'
            USING ERRCODE = '23514';
    END IF;

    SELECT COUNT(*) INTO audit_count
      FROM public.audit_auditevent AS event
     WHERE event.principal_kind = 'platform_administrator'
       AND event.schema_version = 1
       AND event.principal_id = activation_record.activated_by_id
       AND event.principal_context_id IS NULL
       AND event.organization_id IS NULL
       AND event.event_edition_id IS NULL
       AND event.capability_code = 'authorization.manage_roles'
       AND event.operation = 'authorization.authority_provenance.activate'
       AND event.target_type =
            'authorization.authority_provenance_activation'
       AND event.target_id IS NULL
       AND event.outcome = 'allow'
       AND event.reason_code = 'exact_lineage_cutover'
       AND event.correlation_id = activation_record.correlation_id
       AND event.occurred_at = activation_record.activated_at
       AND event.xmin = pg_current_xact_id()::xid
       AND event.source_channel !~ '^[[:space:]]*$'
       AND event.causation_id IS NULL
       AND event.request_id IS NULL
       AND event.idempotency_key_hash = ''
       AND event.obligations = ARRAY[
           'reason',
           'audit',
           'stopped_processes'
       ]::varchar[]
       AND event.changed_fields = ARRAY[
           'authority_provenance_activation'
       ]::varchar[]
       AND event.delegated IS FALSE
       AND event.elevated IS TRUE
       AND event.break_glass IS FALSE
       AND event.safe_metadata = jsonb_build_object(
           'contract_version',
           'adr-0044-v1',
           'policy_version',
           '2026-08-01.3'
       )
       AND event.retention_class = 'security-extended';
    IF audit_count != 1 THEN
        RAISE EXCEPTION
            'authority provenance activation requires one exact audit event'
            USING ERRCODE = '23514';
    END IF;

    FOR target_record IN
        SELECT *
          FROM public.authorization_capabilitygrant
         WHERE revoked_at IS NULL
           AND (
               expires_at IS NULL
               OR expires_at > activation_record.activated_at
           )
         ORDER BY id
    LOOP
        PERFORM public.maru_assert_authority_target_complete(
            'capability_grant',
            target_record.id
        );
        SELECT ordinal INTO issuance_ordinal
          FROM public.authorization_authorityissuance
         WHERE capability_grant_id = target_record.id;
        IF NOT public.maru_authority_issuance_valid_v1(
            issuance_ordinal,
            target_record.principal_id,
            target_record.capability_code,
            target_record.organization_id,
            target_record.edition_id,
            target_record.department_id,
            target_record.resource_binding_id,
            target_record.effective_from,
            target_record.expires_at,
            GREATEST(
                activation_record.activated_at,
                target_record.effective_from
            ),
            TRUE,
            TRUE,
            ARRAY[]::bigint[],
            0
        ) THEN
            RAISE EXCEPTION
                'effective or future capability grant has invalid exact lineage'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;

    FOR target_record IN
        SELECT
            assignment.*,
            bundle.capability_codes
          FROM public.authorization_roleassignment AS assignment
          JOIN public.authorization_rolebundle AS bundle
            ON bundle.id = assignment.role_bundle_id
         WHERE assignment.revoked_at IS NULL
           AND (
               assignment.expires_at IS NULL
               OR assignment.expires_at > activation_record.activated_at
           )
         ORDER BY assignment.id
    LOOP
        PERFORM public.maru_assert_authority_target_complete(
            'role_assignment',
            target_record.id
        );
        IF target_record.capability_codes IS NULL
           OR cardinality(target_record.capability_codes) = 0
        THEN
            RAISE EXCEPTION
                'effective or future role assignment has no capabilities'
                USING ERRCODE = '23514';
        END IF;
        SELECT ordinal INTO issuance_ordinal
          FROM public.authorization_authorityissuance
         WHERE role_assignment_id = target_record.id;
        FOREACH capability_code IN ARRAY target_record.capability_codes
        LOOP
            IF NOT public.maru_authority_issuance_valid_v1(
                issuance_ordinal,
                target_record.principal_id,
                capability_code,
                target_record.organization_id,
                target_record.edition_id,
                target_record.department_id,
                target_record.resource_binding_id,
                target_record.effective_from,
                target_record.expires_at,
                GREATEST(
                    activation_record.activated_at,
                    target_record.effective_from
                ),
                TRUE,
                TRUE,
                ARRAY[]::bigint[],
                0
            ) THEN
                RAISE EXCEPTION
                    'effective or future role assignment has invalid exact lineage'
                    USING ERRCODE = '23514';
            END IF;
        END LOOP;
    END LOOP;

    FOR bundle_record IN
        WITH latest_bundle AS (
            SELECT DISTINCT ON (organization_id, code) id
              FROM public.authorization_rolebundle
             ORDER BY organization_id, code, version DESC, id
        ),
        required_bundle AS (
            SELECT id FROM latest_bundle
            UNION
            SELECT assignment.role_bundle_id
              FROM public.authorization_roleassignment AS assignment
             WHERE assignment.revoked_at IS NULL
               AND (
                   assignment.expires_at IS NULL
                   OR assignment.expires_at > activation_record.activated_at
               )
        )
        SELECT id FROM required_bundle ORDER BY id
    LOOP
        PERFORM public.maru_assert_authority_target_complete(
            'role_bundle',
            bundle_record.id
        );
        IF NOT public.maru_authority_bundle_historical_v1(
            bundle_record.id,
            activation_record.activated_at,
            NULL,
            ARRAY[]::bigint[],
            0
        ) THEN
            RAISE EXCEPTION
                'referenced or assignable role bundle has invalid exact lineage'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_deferred_validate_authority_grant()
RETURNS trigger AS $$
DECLARE
    issuance_ordinal bigint;
    issuance_evaluated_at timestamptz;
    evaluated_at timestamptz;
    require_current boolean;
    validation_now timestamptz;
BEGIN
    IF NOT public.maru_authority_provenance_is_active() THEN
        RETURN NULL;
    END IF;
    PERFORM public.maru_assert_authority_target_complete('capability_grant', NEW.id);
    SELECT ordinal, issuance.evaluated_at
      INTO issuance_ordinal, issuance_evaluated_at
      FROM public.authorization_authorityissuance AS issuance
     WHERE capability_grant_id = NEW.id;
    validation_now := clock_timestamp();
    IF NEW.revoked_at IS NULL
       AND (NEW.expires_at IS NULL OR NEW.expires_at > validation_now)
    THEN
        evaluated_at := GREATEST(validation_now, NEW.effective_from);
        require_current := TRUE;
    ELSE
        evaluated_at := GREATEST(issuance_evaluated_at, NEW.effective_from);
        require_current := FALSE;
    END IF;
    IF NOT public.maru_authority_issuance_valid_v1(
        issuance_ordinal,
        NEW.principal_id,
        NEW.capability_code,
        NEW.organization_id,
        NEW.edition_id,
        NEW.department_id,
        NEW.resource_binding_id,
        NEW.effective_from,
        NEW.expires_at,
        evaluated_at,
        require_current,
        TRUE,
        ARRAY[]::bigint[],
        0
    ) THEN
        RAISE EXCEPTION
            'new capability grant requires exact lineage'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_deferred_validate_authority_bundle()
RETURNS trigger AS $$
BEGIN
    IF NOT public.maru_authority_provenance_is_active() THEN
        RETURN NULL;
    END IF;
    PERFORM public.maru_assert_authority_target_complete('role_bundle', NEW.id);
    IF NOT public.maru_authority_bundle_historical_v1(
        NEW.id,
        clock_timestamp(),
        NULL,
        ARRAY[]::bigint[],
        0
    ) THEN
        RAISE EXCEPTION 'new role bundle requires exact historical lineage'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_deferred_validate_authority_assignment()
RETURNS trigger AS $$
DECLARE
    issuance_ordinal bigint;
    issuance_evaluated_at timestamptz;
    capability_code varchar;
    capability_codes varchar[];
    evaluated_at timestamptz;
    require_current boolean;
    validation_now timestamptz;
BEGIN
    IF NOT public.maru_authority_provenance_is_active() THEN
        RETURN NULL;
    END IF;
    PERFORM public.maru_assert_authority_target_complete('role_assignment', NEW.id);
    SELECT ordinal, issuance.evaluated_at
      INTO issuance_ordinal, issuance_evaluated_at
      FROM public.authorization_authorityissuance AS issuance
     WHERE role_assignment_id = NEW.id;
    validation_now := clock_timestamp();
    IF NEW.revoked_at IS NULL
       AND (NEW.expires_at IS NULL OR NEW.expires_at > validation_now)
    THEN
        evaluated_at := GREATEST(validation_now, NEW.effective_from);
        require_current := TRUE;
    ELSE
        evaluated_at := GREATEST(issuance_evaluated_at, NEW.effective_from);
        require_current := FALSE;
    END IF;
    SELECT bundle.capability_codes INTO capability_codes
      FROM public.authorization_rolebundle AS bundle
     WHERE bundle.id = NEW.role_bundle_id;
    IF capability_codes IS NULL OR cardinality(capability_codes) = 0 THEN
        RAISE EXCEPTION 'new role assignment requires bundle capabilities'
            USING ERRCODE = '23514';
    END IF;
    FOREACH capability_code IN ARRAY capability_codes
    LOOP
        IF NOT public.maru_authority_issuance_valid_v1(
            issuance_ordinal,
            NEW.principal_id,
            capability_code,
            NEW.organization_id,
            NEW.edition_id,
            NEW.department_id,
            NEW.resource_binding_id,
            NEW.effective_from,
            NEW.expires_at,
            evaluated_at,
            require_current,
            TRUE,
            ARRAY[]::bigint[],
            0
        ) THEN
            RAISE EXCEPTION
                'new role assignment requires exact lineage'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_deferred_validate_authority_issuance()
RETURNS trigger AS $$
DECLARE
    activation_time timestamptz;
    validation_now timestamptz;
BEGIN
    IF public.maru_authority_provenance_is_active() THEN
        SELECT activated_at INTO activation_time
          FROM public.authorization_authorityprovenanceactivation
         WHERE singleton IS TRUE;
        validation_now := clock_timestamp();
        IF activation_time IS NULL
           OR NEW.evaluated_at < activation_time
           OR NEW.evaluated_at < validation_now - INTERVAL '5 minutes'
           OR NEW.evaluated_at > validation_now + INTERVAL '5 minutes'
        THEN
            RAISE EXCEPTION
                'new authority issuance evaluation must be within the active era'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    PERFORM public.maru_assert_authority_issuance_complete(NEW.ordinal);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_deferred_validate_authority_control()
RETURNS trigger AS $$
BEGIN
    PERFORM public.maru_assert_authority_issuance_complete(NEW.issuance_id);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_deferred_validate_provenance_activation()
RETURNS trigger AS $$
BEGIN
    PERFORM public.maru_assert_authority_provenance_activation();
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_deferred_validate_provenance_latch()
RETURNS trigger AS $$
BEGIN
    IF NEW.generation = 1 THEN
        PERFORM public.maru_assert_authority_provenance_activation();
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

-- Acquire the cutover boundary before PostgreSQL locks any affected rows.
CREATE TRIGGER authorization_capability_grant_provenance_lock
BEFORE INSERT OR UPDATE OR DELETE ON public.authorization_capabilitygrant
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_lock_authority_provenance_writer();

CREATE TRIGGER authorization_role_bundle_provenance_lock
BEFORE INSERT OR UPDATE OR DELETE ON public.authorization_rolebundle
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_lock_authority_provenance_writer();

CREATE TRIGGER authorization_role_assignment_provenance_lock
BEFORE INSERT OR UPDATE OR DELETE ON public.authorization_roleassignment
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_lock_authority_provenance_writer();

CREATE TRIGGER authorization_authority_issuance_provenance_lock
BEFORE INSERT ON public.authorization_authorityissuance
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_lock_authority_provenance_writer();

CREATE TRIGGER authorization_authority_control_provenance_lock
BEFORE INSERT ON public.authorization_authoritycontrol
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_lock_authority_provenance_writer();

CREATE TRIGGER authorization_identity_account_provenance_lock
BEFORE UPDATE OR DELETE ON public.identity_account
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_lock_authority_provenance_writer();

CREATE TRIGGER authorization_organization_provenance_lock
BEFORE UPDATE OR DELETE ON public.organizations_organization
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_lock_authority_provenance_writer();

CREATE TRIGGER authorization_membership_provenance_lock
BEFORE INSERT OR UPDATE OR DELETE ON public.organizations_organizationmembership
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_lock_authority_provenance_writer();

CREATE TRIGGER authorization_representation_provenance_lock
BEFORE INSERT OR UPDATE OR DELETE
ON public.organizations_organizationrepresentation
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_lock_authority_provenance_writer();

CREATE TRIGGER authorization_appointment_provenance_lock
BEFORE INSERT OR UPDATE OR DELETE
ON public.organizations_representationappointment
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_lock_authority_provenance_writer();

CREATE TRIGGER authorization_event_edition_provenance_lock
BEFORE UPDATE OR DELETE ON public.events_eventedition
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_lock_authority_provenance_writer();

CREATE TRIGGER authorization_department_provenance_lock
BEFORE UPDATE OR DELETE ON public.workforce_department
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_lock_authority_provenance_writer();

CREATE TRIGGER authorization_resource_binding_provenance_lock
BEFORE INSERT OR UPDATE OR DELETE ON public.authorization_scopedresourcebinding
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_lock_authority_provenance_writer();

CREATE TRIGGER authorization_provenance_latch_guard
BEFORE INSERT OR UPDATE OR DELETE
ON public.authorization_provenanceactivationlatch
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_authority_provenance_latch();

CREATE TRIGGER authorization_provenance_activation_guard
BEFORE INSERT OR UPDATE OR DELETE
ON public.authorization_authorityprovenanceactivation
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_authority_provenance_activation();

CREATE CONSTRAINT TRIGGER authorization_capability_grant_provenance_complete
AFTER INSERT ON public.authorization_capabilitygrant
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_deferred_validate_authority_grant();

CREATE CONSTRAINT TRIGGER authorization_role_bundle_provenance_complete
AFTER INSERT ON public.authorization_rolebundle
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_deferred_validate_authority_bundle();

CREATE CONSTRAINT TRIGGER authorization_role_assignment_provenance_complete
AFTER INSERT ON public.authorization_roleassignment
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_deferred_validate_authority_assignment();

CREATE CONSTRAINT TRIGGER authorization_authority_issuance_complete
AFTER INSERT ON public.authorization_authorityissuance
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_deferred_validate_authority_issuance();

CREATE CONSTRAINT TRIGGER authorization_authority_control_complete
AFTER INSERT ON public.authorization_authoritycontrol
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_deferred_validate_authority_control();

CREATE CONSTRAINT TRIGGER authorization_provenance_activation_complete
AFTER INSERT ON public.authorization_authorityprovenanceactivation
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_deferred_validate_provenance_activation();

CREATE CONSTRAINT TRIGGER authorization_provenance_latch_complete
AFTER UPDATE ON public.authorization_provenanceactivationlatch
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_deferred_validate_provenance_latch();

-- The graph and the activation audit are append-only even before cutover.
CREATE TRIGGER authorization_capability_grant_provenance_no_truncate
BEFORE TRUNCATE ON public.authorization_capabilitygrant
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_prevent_authority_provenance_truncate();

CREATE TRIGGER authorization_role_bundle_provenance_no_truncate
BEFORE TRUNCATE ON public.authorization_rolebundle
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_prevent_authority_provenance_truncate();

CREATE TRIGGER authorization_role_assignment_provenance_no_truncate
BEFORE TRUNCATE ON public.authorization_roleassignment
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_prevent_authority_provenance_truncate();

CREATE TRIGGER authorization_authority_issuance_provenance_no_truncate
BEFORE TRUNCATE ON public.authorization_authorityissuance
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_prevent_authority_provenance_truncate();

CREATE TRIGGER authorization_authority_control_provenance_no_truncate
BEFORE TRUNCATE ON public.authorization_authoritycontrol
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_prevent_authority_provenance_truncate();

CREATE TRIGGER authorization_provenance_activation_no_truncate
BEFORE TRUNCATE ON public.authorization_authorityprovenanceactivation
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_prevent_authority_provenance_truncate();

CREATE TRIGGER authorization_provenance_latch_no_truncate
BEFORE TRUNCATE ON public.authorization_provenanceactivationlatch
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_prevent_authority_provenance_truncate();

CREATE TRIGGER authorization_provenance_latch_reseed
AFTER TRUNCATE ON public.authorization_provenanceactivationlatch
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_reseed_authority_provenance_latch();

-- PostgreSQL grants EXECUTE on new functions to PUBLIC by default.  Revoke it
-- only from functions introduced by this migration so a pre-existing custom
-- ACL is neither widened nor destroyed and reversal needs no ACL reconstruction.
REVOKE EXECUTE ON FUNCTION
    public.maru_authority_provenance_test_reset_allowed(),
    public.maru_authority_provenance_is_active(),
    public.maru_lock_authority_provenance_writer(),
    public.maru_guard_authority_provenance_latch(),
    public.maru_guard_authority_provenance_activation(),
    public.maru_prevent_authority_provenance_truncate(),
    public.maru_reseed_authority_provenance_latch(),
    public.maru_authority_scope_is_current_v1(uuid, uuid, uuid, uuid),
    public.maru_authority_scope_contains_v1(
        uuid, uuid, uuid, uuid, uuid, uuid, uuid, uuid
    ),
    public.maru_assert_authority_issuance_complete_internal(
        bigint, bigint[], integer
    ),
    public.maru_assert_authority_issuance_complete(bigint),
    public.maru_assert_authority_target_complete(varchar, uuid),
    public.maru_authority_bundle_historical_v1(
        uuid, timestamptz, uuid, bigint[], integer
    ),
    public.maru_authority_issuance_valid_v1(
        bigint,
        uuid,
        varchar,
        uuid,
        uuid,
        uuid,
        uuid,
        timestamptz,
        timestamptz,
        timestamptz,
        boolean,
        boolean,
        bigint[],
        integer
    ),
    public.maru_assert_authority_provenance_activation(),
    public.maru_deferred_validate_authority_grant(),
    public.maru_deferred_validate_authority_bundle(),
    public.maru_deferred_validate_authority_assignment(),
    public.maru_deferred_validate_authority_issuance(),
    public.maru_deferred_validate_authority_control(),
    public.maru_deferred_validate_provenance_activation(),
    public.maru_deferred_validate_provenance_latch()
FROM PUBLIC;
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS authorization_provenance_latch_reseed
    ON public.authorization_provenanceactivationlatch;
DROP TRIGGER IF EXISTS authorization_provenance_latch_no_truncate
    ON public.authorization_provenanceactivationlatch;
DROP TRIGGER IF EXISTS authorization_provenance_activation_no_truncate
    ON public.authorization_authorityprovenanceactivation;
DROP TRIGGER IF EXISTS authorization_authority_control_provenance_no_truncate
    ON public.authorization_authoritycontrol;
DROP TRIGGER IF EXISTS authorization_authority_issuance_provenance_no_truncate
    ON public.authorization_authorityissuance;
DROP TRIGGER IF EXISTS authorization_role_assignment_provenance_no_truncate
    ON public.authorization_roleassignment;
DROP TRIGGER IF EXISTS authorization_role_bundle_provenance_no_truncate
    ON public.authorization_rolebundle;
DROP TRIGGER IF EXISTS authorization_capability_grant_provenance_no_truncate
    ON public.authorization_capabilitygrant;

DROP TRIGGER IF EXISTS authorization_provenance_latch_complete
    ON public.authorization_provenanceactivationlatch;
DROP TRIGGER IF EXISTS authorization_provenance_activation_complete
    ON public.authorization_authorityprovenanceactivation;
DROP TRIGGER IF EXISTS authorization_authority_control_complete
    ON public.authorization_authoritycontrol;
DROP TRIGGER IF EXISTS authorization_authority_issuance_complete
    ON public.authorization_authorityissuance;
DROP TRIGGER IF EXISTS authorization_role_assignment_provenance_complete
    ON public.authorization_roleassignment;
DROP TRIGGER IF EXISTS authorization_role_bundle_provenance_complete
    ON public.authorization_rolebundle;
DROP TRIGGER IF EXISTS authorization_capability_grant_provenance_complete
    ON public.authorization_capabilitygrant;

DROP TRIGGER IF EXISTS authorization_provenance_activation_guard
    ON public.authorization_authorityprovenanceactivation;
DROP TRIGGER IF EXISTS authorization_provenance_latch_guard
    ON public.authorization_provenanceactivationlatch;
DROP TRIGGER IF EXISTS authorization_resource_binding_provenance_lock
    ON public.authorization_scopedresourcebinding;
DROP TRIGGER IF EXISTS authorization_department_provenance_lock
    ON public.workforce_department;
DROP TRIGGER IF EXISTS authorization_event_edition_provenance_lock
    ON public.events_eventedition;
DROP TRIGGER IF EXISTS authorization_appointment_provenance_lock
    ON public.organizations_representationappointment;
DROP TRIGGER IF EXISTS authorization_representation_provenance_lock
    ON public.organizations_organizationrepresentation;
DROP TRIGGER IF EXISTS authorization_membership_provenance_lock
    ON public.organizations_organizationmembership;
DROP TRIGGER IF EXISTS authorization_organization_provenance_lock
    ON public.organizations_organization;
DROP TRIGGER IF EXISTS authorization_identity_account_provenance_lock
    ON public.identity_account;
DROP TRIGGER IF EXISTS authorization_authority_control_provenance_lock
    ON public.authorization_authoritycontrol;
DROP TRIGGER IF EXISTS authorization_authority_issuance_provenance_lock
    ON public.authorization_authorityissuance;
DROP TRIGGER IF EXISTS authorization_role_assignment_provenance_lock
    ON public.authorization_roleassignment;
DROP TRIGGER IF EXISTS authorization_role_bundle_provenance_lock
    ON public.authorization_rolebundle;
DROP TRIGGER IF EXISTS authorization_capability_grant_provenance_lock
    ON public.authorization_capabilitygrant;

DROP FUNCTION IF EXISTS public.maru_deferred_validate_provenance_latch();
DROP FUNCTION IF EXISTS public.maru_deferred_validate_provenance_activation();
DROP FUNCTION IF EXISTS public.maru_deferred_validate_authority_control();
DROP FUNCTION IF EXISTS public.maru_deferred_validate_authority_issuance();
DROP FUNCTION IF EXISTS public.maru_deferred_validate_authority_assignment();
DROP FUNCTION IF EXISTS public.maru_deferred_validate_authority_bundle();
DROP FUNCTION IF EXISTS public.maru_deferred_validate_authority_grant();
DROP FUNCTION IF EXISTS public.maru_assert_authority_provenance_activation();
DROP FUNCTION IF EXISTS public.maru_authority_bundle_historical_v1(
    uuid,
    timestamptz,
    uuid,
    bigint[],
    integer
);
DROP FUNCTION IF EXISTS public.maru_authority_issuance_valid_v1(
    bigint,
    uuid,
    varchar,
    uuid,
    uuid,
    uuid,
    uuid,
    timestamptz,
    timestamptz,
    timestamptz,
    boolean,
    boolean,
    bigint[],
    integer
);
DROP FUNCTION IF EXISTS public.maru_assert_authority_target_complete(varchar, uuid);
DROP FUNCTION IF EXISTS public.maru_assert_authority_issuance_complete(bigint);
DROP FUNCTION IF EXISTS public.maru_assert_authority_issuance_complete_internal(
    bigint,
    bigint[],
    integer
);
DROP FUNCTION IF EXISTS public.maru_authority_scope_contains_v1(
    uuid,
    uuid,
    uuid,
    uuid,
    uuid,
    uuid,
    uuid,
    uuid
);
DROP FUNCTION IF EXISTS public.maru_authority_scope_is_current_v1(
    uuid,
    uuid,
    uuid,
    uuid
);
DROP FUNCTION IF EXISTS public.maru_reseed_authority_provenance_latch();
DROP FUNCTION IF EXISTS public.maru_prevent_authority_provenance_truncate();
DROP FUNCTION IF EXISTS public.maru_guard_authority_provenance_activation();
DROP FUNCTION IF EXISTS public.maru_guard_authority_provenance_latch();
DROP FUNCTION IF EXISTS public.maru_lock_authority_provenance_writer();
DROP FUNCTION IF EXISTS public.maru_authority_provenance_is_active();
DROP FUNCTION IF EXISTS public.maru_authority_provenance_test_reset_allowed();
"""


def seed_authority_provenance_latch(apps, schema_editor) -> None:  # type: ignore[no-untyped-def]
    """Create the row that must predate every possible cutover snapshot."""

    del apps
    schema_editor.execute(
        """
        INSERT INTO public.authorization_provenanceactivationlatch
            (singleton, generation)
        VALUES (TRUE, 0)
        ON CONFLICT (singleton) DO NOTHING
        """
    )


def remove_dormant_authority_provenance_latch(  # type: ignore[no-untyped-def]
    apps,
    schema_editor,
) -> None:
    """Remove only the untouched compatibility latch during a clean reverse."""

    del apps
    schema_editor.execute(
        """
        DELETE FROM public.authorization_provenanceactivationlatch
         WHERE singleton IS TRUE AND generation = 0
        """
    )


def refuse_activated_provenance_downgrade(apps, schema_editor) -> None:  # type: ignore[no-untyped-def]
    """Once cut over, keep every marker, guard, latch, and ledger table."""

    del apps
    # The lock is held by the migration transaction through every later reverse
    # operation.  It closes the check/DDL race without joining the advisory-lock
    # order used by activation: an activation that already inserted its marker
    # commits first and is observed below; one that has not touched the table
    # loses the race and fails safely after the schema is reversed.
    schema_editor.execute(
        """
        LOCK TABLE
            public.authorization_authorityprovenanceactivation,
            public.authorization_provenanceactivationlatch
        IN ACCESS EXCLUSIVE MODE
        """
    )
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                  FROM public.authorization_authorityprovenanceactivation
            )
            """
        )
        activation_exists = bool(cursor.fetchone()[0])
        cursor.execute(
            """
            SELECT singleton, generation
              FROM public.authorization_provenanceactivationlatch
             ORDER BY singleton
             LIMIT 2
            """
        )
        latch_rows = tuple(cursor.fetchall())
    if activation_exists or latch_rows != ((True, 0),):
        raise RuntimeError(
            "Cannot reverse activated authority provenance. Keep compatible code "
            "and fix forward, or restore the whole database to one consistent "
            "pre-activation point."
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("audit", "0005_authority_activation_evidence_guards"),
        ("authorization", "0006_authority_issuance_schema"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations: ClassVar[list[object]] = [
        migrations.CreateModel(
            name="AuthorityProvenanceActivation",
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
                ("contract_version", models.CharField(editable=False, max_length=40)),
                ("policy_version", models.CharField(editable=False, max_length=40)),
                ("reason", models.CharField(editable=False, max_length=240)),
                ("correlation_id", models.UUIDField(editable=False, unique=True)),
                (
                    "activated_at",
                    models.DateTimeField(auto_now_add=True, editable=False),
                ),
                (
                    "activated_by",
                    models.ForeignKey(
                        editable=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="authority_provenance_activations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"default_permissions": ()},
        ),
        migrations.CreateModel(
            name="AuthorityProvenanceActivationLatch",
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
                    "generation",
                    models.PositiveSmallIntegerField(default=0, editable=False),
                ),
            ],
            options={
                "db_table": "authorization_provenanceactivationlatch",
                "default_permissions": (),
            },
        ),
        migrations.AddConstraint(
            model_name="authorityprovenanceactivation",
            constraint=models.CheckConstraint(
                condition=models.Q(("singleton", True)),
                name="authorization_provenance_activation_singleton_true",
            ),
        ),
        migrations.AddConstraint(
            model_name="authorityprovenanceactivation",
            constraint=models.CheckConstraint(
                condition=models.Q(("contract_version", ""), _negated=True),
                name="authorization_provenance_activation_contract_required",
            ),
        ),
        migrations.AddConstraint(
            model_name="authorityprovenanceactivation",
            constraint=models.CheckConstraint(
                condition=models.Q(("policy_version", ""), _negated=True),
                name="authorization_provenance_activation_policy_required",
            ),
        ),
        migrations.AddConstraint(
            model_name="authorityprovenanceactivation",
            constraint=models.CheckConstraint(
                condition=models.Q(("reason", ""), _negated=True),
                name="authorization_provenance_activation_reason_required",
            ),
        ),
        migrations.AddConstraint(
            model_name="authorityprovenanceactivationlatch",
            constraint=models.CheckConstraint(
                condition=models.Q(("singleton", True)),
                name="authorization_provenance_latch_singleton_true",
            ),
        ),
        migrations.AddConstraint(
            model_name="authorityprovenanceactivationlatch",
            constraint=models.CheckConstraint(
                condition=models.Q(("generation__in", (0, 1))),
                name="authorization_provenance_latch_generation_known",
            ),
        ),
        migrations.RunPython(
            seed_authority_provenance_latch,
            reverse_code=remove_dormant_authority_provenance_latch,
        ),
        migrations.RunSQL(
            HARDEN_FOUNDATIONAL_AUTHORIZATION_FUNCTIONS_FORWARD_SQL,
            reverse_sql=HARDEN_FOUNDATIONAL_AUTHORIZATION_FUNCTIONS_REVERSE_SQL,
        ),
        migrations.RunSQL(
            HARDEN_EXISTING_ISSUANCE_FUNCTIONS_FORWARD_SQL,
            reverse_sql=HARDEN_EXISTING_ISSUANCE_FUNCTIONS_REVERSE_SQL,
        ),
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_activated_provenance_downgrade,
        ),
    ]
