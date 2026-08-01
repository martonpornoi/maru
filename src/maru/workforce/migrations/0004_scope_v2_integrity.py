"""Harden workforce containment for ADR 0041 scope-v2 authority.

This is a stopped-writer migration.  It replaces the original workforce row
guards before running a count-only preflight, so a concurrent compatible
writer cannot enter between validation and protection.  Existing workforce
role evidence intentionally remains edition-wide unless an explicit later
command narrows it to the exact department or position binding.

Once authorization scope-v2 writes exist, keep compatible code and fix
forward.  The final authorization migration owns the milestone downgrade
fence; reversing only this integrity layer after that point is unsafe.
"""

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION maru_workforce_role_evidence_matches_position(
    evidence_id uuid,
    expected_position_id uuid,
    expected_organization_id uuid,
    expected_edition_id uuid,
    expected_department_id uuid,
    expected_account_id uuid
)
RETURNS boolean AS $$
    SELECT EXISTS (
        SELECT 1
          FROM authorization_roleassignment AS evidence
          LEFT JOIN authorization_scopedresourcebinding AS binding
            ON binding.id = evidence.resource_binding_id
         WHERE evidence.id = evidence_id
           AND evidence.organization_id = expected_organization_id
           AND evidence.edition_id = expected_edition_id
           AND evidence.principal_id = expected_account_id
           AND (
               (
                   evidence.department_id IS NULL
                   AND evidence.resource_binding_id IS NULL
               )
               OR (
                   evidence.department_id = expected_department_id
                   AND evidence.resource_binding_id IS NULL
               )
               OR (
                   evidence.department_id = expected_department_id
                   AND binding.resource_kind = 'workforce.position'
                   AND binding.resource_id = expected_position_id
                   AND binding.organization_id = expected_organization_id
                   AND binding.edition_id = expected_edition_id
                   AND binding.department_id = expected_department_id
               )
           )
    );
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION maru_guard_workforce_department()
RETURNS trigger AS $$
DECLARE
    edition_organization uuid;
    parent_organization uuid;
    parent_edition uuid;
    hierarchy_cycle boolean;
    old_scope_lock bigint;
    new_scope_lock bigint;
BEGIN
    -- Authorization scope writes lock editions before taking this advisory
    -- hierarchy lock.  Keep that global order to avoid an edition/advisory
    -- deadlock while a department is reparented concurrently.
    IF TG_OP = 'UPDATE' THEN
        PERFORM edition.id
          FROM events_eventedition AS edition
         WHERE edition.id IN (OLD.edition_id, NEW.edition_id)
         ORDER BY edition.id
         FOR KEY SHARE;
    ELSE
        PERFORM edition.id
          FROM events_eventedition AS edition
         WHERE edition.id = NEW.edition_id
         FOR KEY SHARE;
    END IF;

    -- Serialize hierarchy writes within a scope.  Row locks alone cannot stop
    -- two concurrent reparenting transactions from creating a write-skew cycle.
    new_scope_lock := hashtextextended(
        'maru.workforce.department:'
        || NEW.organization_id::text
        || ':'
        || NEW.edition_id::text,
        0
    );
    IF TG_OP = 'UPDATE' THEN
        old_scope_lock := hashtextextended(
            'maru.workforce.department:'
            || OLD.organization_id::text
            || ':'
            || OLD.edition_id::text,
            0
        );
        PERFORM pg_advisory_xact_lock(LEAST(old_scope_lock, new_scope_lock));
        IF old_scope_lock <> new_scope_lock THEN
            PERFORM pg_advisory_xact_lock(GREATEST(old_scope_lock, new_scope_lock));
        END IF;
    ELSE
        PERFORM pg_advisory_xact_lock(new_scope_lock);
    END IF;

    SELECT organization_id
      INTO edition_organization
      FROM events_eventedition
     WHERE id = NEW.edition_id;
    IF edition_organization IS DISTINCT FROM NEW.organization_id THEN
        RAISE EXCEPTION 'workforce department edition scope mismatch'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.parent_id IS NOT NULL THEN
        SELECT organization_id, edition_id
          INTO parent_organization, parent_edition
          FROM workforce_department
         WHERE id = NEW.parent_id
         FOR KEY SHARE;
        IF parent_organization IS DISTINCT FROM NEW.organization_id
           OR parent_edition IS DISTINCT FROM NEW.edition_id
           OR NEW.parent_id = NEW.id
        THEN
            RAISE EXCEPTION 'workforce department parent scope mismatch'
                USING ERRCODE = '23514';
        END IF;

        WITH RECURSIVE ancestors AS (
            SELECT department.id,
                   department.parent_id,
                   ARRAY[department.id] AS path,
                   false AS cycle
              FROM workforce_department AS department
             WHERE department.id = NEW.parent_id
            UNION ALL
            SELECT parent.id,
                   parent.parent_id,
                   ancestors.path || parent.id,
                   parent.id = ANY(ancestors.path) AS cycle
              FROM ancestors
              JOIN workforce_department AS parent
                ON parent.id = ancestors.parent_id
             WHERE NOT ancestors.cycle
        )
        SELECT COALESCE(bool_or(id = NEW.id OR cycle), false)
          INTO hierarchy_cycle
          FROM ancestors;
        IF hierarchy_cycle THEN
            RAISE EXCEPTION 'workforce department hierarchy cannot contain a cycle'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF TG_OP = 'UPDATE' THEN
        IF EXISTS (
            SELECT 1
              FROM workforce_department AS child
             WHERE child.parent_id = OLD.id
               AND (
                   child.organization_id IS DISTINCT FROM NEW.organization_id
                   OR child.edition_id IS DISTINCT FROM NEW.edition_id
               )
        ) THEN
            RAISE EXCEPTION 'workforce department move would orphan a child scope'
                USING ERRCODE = '23514';
        END IF;
        IF EXISTS (
            SELECT 1
              FROM workforce_position AS position
             WHERE position.department_id = OLD.id
               AND (
                   position.organization_id IS DISTINCT FROM NEW.organization_id
                   OR position.edition_id IS DISTINCT FROM NEW.edition_id
               )
        ) THEN
            RAISE EXCEPTION 'workforce department move would orphan a position scope'
                USING ERRCODE = '23514';
        END IF;
        IF EXISTS (
            SELECT 1
              FROM authorization_scopedresourcebinding AS binding
             WHERE binding.department_id = OLD.id
               AND (
                   binding.organization_id IS DISTINCT FROM NEW.organization_id
                   OR binding.edition_id IS DISTINCT FROM NEW.edition_id
               )
        ) THEN
            RAISE EXCEPTION 'workforce department move would orphan an authority scope'
                USING ERRCODE = '23514';
        END IF;
        IF EXISTS (
            SELECT 1
              FROM authorization_capabilitygrant AS authority
             WHERE authority.department_id = OLD.id
               AND (
                   authority.organization_id IS DISTINCT FROM NEW.organization_id
                   OR authority.edition_id IS DISTINCT FROM NEW.edition_id
               )
        ) OR EXISTS (
            SELECT 1
              FROM authorization_roleassignment AS authority
             WHERE authority.department_id = OLD.id
               AND (
                   authority.organization_id IS DISTINCT FROM NEW.organization_id
                   OR authority.edition_id IS DISTINCT FROM NEW.edition_id
               )
        ) THEN
            RAISE EXCEPTION 'workforce department move would orphan scoped authority'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION maru_guard_workforce_position()
RETURNS trigger AS $$
DECLARE
    scoped_organization uuid;
    scoped_edition uuid;
    reporting_cycle boolean;
    old_scope_lock bigint;
    new_scope_lock bigint;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'workforce positions cannot be deleted'
            USING ERRCODE = '23514';
    END IF;

    -- Reporting-line writes need the same serialization as department-tree
    -- writes; otherwise two concurrent updates can both miss a new cycle.
    new_scope_lock := hashtextextended(
        'maru.workforce.position:'
        || NEW.organization_id::text
        || ':'
        || NEW.edition_id::text,
        0
    );
    IF TG_OP = 'UPDATE' THEN
        old_scope_lock := hashtextextended(
            'maru.workforce.position:'
            || OLD.organization_id::text
            || ':'
            || OLD.edition_id::text,
            0
        );
        PERFORM pg_advisory_xact_lock(LEAST(old_scope_lock, new_scope_lock));
        IF old_scope_lock <> new_scope_lock THEN
            PERFORM pg_advisory_xact_lock(GREATEST(old_scope_lock, new_scope_lock));
        END IF;
    ELSE
        PERFORM pg_advisory_xact_lock(new_scope_lock);
    END IF;

    SELECT organization_id
      INTO scoped_organization
      FROM events_eventedition
     WHERE id = NEW.edition_id
     FOR KEY SHARE;
    IF scoped_organization IS DISTINCT FROM NEW.organization_id THEN
        RAISE EXCEPTION 'workforce position edition scope mismatch'
            USING ERRCODE = '23514';
    END IF;

    SELECT organization_id, edition_id
      INTO scoped_organization, scoped_edition
      FROM workforce_department
     WHERE id = NEW.department_id
     FOR KEY SHARE;
    IF scoped_organization IS DISTINCT FROM NEW.organization_id
       OR scoped_edition IS DISTINCT FROM NEW.edition_id
    THEN
        RAISE EXCEPTION 'workforce position department scope mismatch'
            USING ERRCODE = '23514';
    END IF;

    SELECT organization_id
      INTO scoped_organization
      FROM workforce_positiontemplate
     WHERE id = NEW.template_id
     FOR KEY SHARE;
    IF scoped_organization IS DISTINCT FROM NEW.organization_id THEN
        RAISE EXCEPTION 'workforce position template scope mismatch'
            USING ERRCODE = '23514';
    END IF;

    SELECT organization_id
      INTO scoped_organization
      FROM authorization_rolebundle
     WHERE id = NEW.role_bundle_id
     FOR KEY SHARE;
    IF scoped_organization IS DISTINCT FROM NEW.organization_id THEN
        RAISE EXCEPTION 'workforce position role scope mismatch'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.reports_to_id IS NOT NULL THEN
        SELECT organization_id, edition_id
          INTO scoped_organization, scoped_edition
          FROM workforce_position
         WHERE id = NEW.reports_to_id
         FOR KEY SHARE;
        IF scoped_organization IS DISTINCT FROM NEW.organization_id
           OR scoped_edition IS DISTINCT FROM NEW.edition_id
           OR NEW.reports_to_id = NEW.id
        THEN
            RAISE EXCEPTION 'workforce reporting line scope mismatch'
                USING ERRCODE = '23514';
        END IF;

        WITH RECURSIVE managers AS (
            SELECT position.id,
                   position.reports_to_id,
                   ARRAY[position.id] AS path,
                   false AS cycle
              FROM workforce_position AS position
             WHERE position.id = NEW.reports_to_id
            UNION ALL
            SELECT manager.id,
                   manager.reports_to_id,
                   managers.path || manager.id,
                   manager.id = ANY(managers.path) AS cycle
              FROM managers
              JOIN workforce_position AS manager
                ON manager.id = managers.reports_to_id
             WHERE NOT managers.cycle
        )
        SELECT COALESCE(bool_or(id = NEW.id OR cycle), false)
          INTO reporting_cycle
          FROM managers;
        IF reporting_cycle THEN
            RAISE EXCEPTION 'workforce reporting hierarchy cannot contain a cycle'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF TG_OP = 'UPDATE'
       AND (
           NEW.organization_id IS DISTINCT FROM OLD.organization_id
           OR NEW.edition_id IS DISTINCT FROM OLD.edition_id
           OR NEW.department_id IS DISTINCT FROM OLD.department_id
       )
       AND EXISTS (
           SELECT 1
             FROM authorization_scopedresourcebinding AS binding
            WHERE binding.resource_kind = 'workforce.position'
              AND binding.resource_id = OLD.id
       )
    THEN
        RAISE EXCEPTION
            'workforce position scope is immutable after resource binding'
            USING ERRCODE = '23514';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM authorization_scopedresourcebinding AS binding
         WHERE binding.resource_kind = 'workforce.position'
           AND binding.resource_id = NEW.id
           AND (
               binding.organization_id IS DISTINCT FROM NEW.organization_id
               OR binding.edition_id IS DISTINCT FROM NEW.edition_id
               OR binding.department_id IS DISTINCT FROM NEW.department_id
           )
    ) THEN
        RAISE EXCEPTION 'workforce position resource binding scope mismatch'
            USING ERRCODE = '23514';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM workforce_position AS report
         WHERE report.reports_to_id = NEW.id
           AND (
               report.organization_id IS DISTINCT FROM NEW.organization_id
               OR report.edition_id IS DISTINCT FROM NEW.edition_id
           )
    ) THEN
        RAISE EXCEPTION 'workforce position move would orphan a reporting line'
            USING ERRCODE = '23514';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM workforce_positionassignment AS assignment
         WHERE assignment.position_id = NEW.id
           AND (
               assignment.organization_id IS DISTINCT FROM NEW.organization_id
               OR assignment.edition_id IS DISTINCT FROM NEW.edition_id
               OR (
                   assignment.role_assignment_id IS NOT NULL
                   AND NOT maru_workforce_role_evidence_matches_position(
                       assignment.role_assignment_id,
                       NEW.id,
                       NEW.organization_id,
                       NEW.edition_id,
                       NEW.department_id,
                       assignment.account_id
                   )
               )
           )
    ) THEN
        RAISE EXCEPTION 'workforce position move would orphan assignment evidence'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION maru_guard_workforce_assignment()
RETURNS trigger AS $$
DECLARE
    scoped_organization uuid;
    scoped_edition uuid;
    scoped_department uuid;
    scoped_account uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'workforce assignments cannot be deleted'
            USING ERRCODE = '23514';
    END IF;
    SELECT organization_id, edition_id, department_id
      INTO scoped_organization, scoped_edition, scoped_department
      FROM workforce_position
     WHERE id = NEW.position_id
     FOR KEY SHARE;
    IF scoped_organization IS DISTINCT FROM NEW.organization_id
       OR scoped_edition IS DISTINCT FROM NEW.edition_id
    THEN
        RAISE EXCEPTION 'workforce assignment position scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.approved_by_id IS NOT NULL
       AND NEW.approved_by_id = NEW.proposed_by_id
    THEN
        RAISE EXCEPTION 'workforce assignment requires independent approval'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.role_assignment_id IS NOT NULL
       AND NOT maru_workforce_role_evidence_matches_position(
           NEW.role_assignment_id,
           NEW.position_id,
           NEW.organization_id,
           NEW.edition_id,
           scoped_department,
           NEW.account_id
       )
    THEN
        RAISE EXCEPTION 'workforce assignment role evidence scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.participation_capacity_id IS NOT NULL THEN
        SELECT participation.organization_id,
               participation.edition_id,
               participation.account_id
          INTO scoped_organization, scoped_edition, scoped_account
          FROM participation_participationcapacity AS capacity
          JOIN participation_participation AS participation
            ON participation.id = capacity.participation_id
         WHERE capacity.id = NEW.participation_capacity_id;
        IF scoped_organization IS DISTINCT FROM NEW.organization_id
           OR scoped_edition IS DISTINCT FROM NEW.edition_id
           OR scoped_account IS DISTINCT FROM NEW.account_id
        THEN
            RAISE EXCEPTION 'workforce assignment capacity evidence scope mismatch'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF NEW.status = 'active' AND (
        NEW.approved_by_id IS NULL
        OR NEW.role_assignment_id IS NULL
        OR NEW.participation_capacity_id IS NULL
    ) THEN
        RAISE EXCEPTION 'active workforce assignment lacks approval evidence'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF OLD.status = 'active' AND NEW.status = 'active'
           AND NEW IS DISTINCT FROM OLD
        THEN
            RAISE EXCEPTION 'active workforce assignments are immutable'
                USING ERRCODE = '23514';
        END IF;
        IF OLD.status <> NEW.status AND NOT (
            (OLD.status = 'proposed' AND NEW.status = 'active')
            OR (OLD.status = 'active' AND NEW.status = 'ended')
        ) THEN
            RAISE EXCEPTION 'invalid workforce assignment status transition'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION maru_guard_workforce_role_assignment_evidence()
RETURNS trigger AS $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM workforce_positionassignment AS assignment
          JOIN workforce_position AS position
            ON position.id = assignment.position_id
          LEFT JOIN authorization_scopedresourcebinding AS binding
            ON binding.id = NEW.resource_binding_id
         WHERE assignment.role_assignment_id = NEW.id
           AND (
               NEW.organization_id IS DISTINCT FROM position.organization_id
               OR NEW.edition_id IS DISTINCT FROM position.edition_id
               OR NEW.principal_id IS DISTINCT FROM assignment.account_id
               OR NOT (
                   (
                       NEW.department_id IS NULL
                       AND NEW.resource_binding_id IS NULL
                   )
                   OR (
                       NEW.department_id = position.department_id
                       AND NEW.resource_binding_id IS NULL
                   )
                   OR (
                       NEW.department_id = position.department_id
                       AND binding.resource_kind = 'workforce.position'
                       AND binding.resource_id = position.id
                       AND binding.organization_id = position.organization_id
                       AND binding.edition_id = position.edition_id
                       AND binding.department_id = position.department_id
                   )
               )
           )
    ) THEN
        RAISE EXCEPTION 'role assignment no longer matches workforce evidence'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER workforce_role_assignment_evidence_guard
BEFORE UPDATE
ON authorization_roleassignment
FOR EACH ROW EXECUTE FUNCTION maru_guard_workforce_role_assignment_evidence();

DO $$
DECLARE
    invalid_department_scope_count bigint;
    department_cycle_count bigint;
    invalid_position_scope_count bigint;
    position_cycle_count bigint;
    invalid_binding_scope_count bigint;
    invalid_assignment_role_count bigint;
    retained_edition_role_count bigint;
BEGIN
    SELECT COUNT(*)
      INTO invalid_department_scope_count
      FROM workforce_department AS department
      LEFT JOIN events_eventedition AS edition
        ON edition.id = department.edition_id
      LEFT JOIN workforce_department AS parent
        ON parent.id = department.parent_id
     WHERE edition.organization_id IS DISTINCT FROM department.organization_id
        OR (
            department.parent_id IS NOT NULL
            AND (
                parent.organization_id IS DISTINCT FROM department.organization_id
                OR parent.edition_id IS DISTINCT FROM department.edition_id
            )
        );

    WITH RECURSIVE department_walk AS (
        SELECT department.id AS start_id,
               department.parent_id,
               ARRAY[department.id] AS path,
               false AS cycle
          FROM workforce_department AS department
        UNION ALL
        SELECT department_walk.start_id,
               parent.parent_id,
               department_walk.path || parent.id,
               parent.id = ANY(department_walk.path) AS cycle
          FROM department_walk
          JOIN workforce_department AS parent
            ON parent.id = department_walk.parent_id
         WHERE NOT department_walk.cycle
    )
    SELECT COUNT(DISTINCT start_id)
      INTO department_cycle_count
      FROM department_walk
     WHERE cycle;

    SELECT COUNT(*)
      INTO invalid_position_scope_count
      FROM workforce_position AS position
      LEFT JOIN events_eventedition AS edition
        ON edition.id = position.edition_id
      LEFT JOIN workforce_department AS department
        ON department.id = position.department_id
      LEFT JOIN workforce_positiontemplate AS template
        ON template.id = position.template_id
      LEFT JOIN authorization_rolebundle AS role_bundle
        ON role_bundle.id = position.role_bundle_id
      LEFT JOIN workforce_position AS manager
        ON manager.id = position.reports_to_id
     WHERE edition.organization_id IS DISTINCT FROM position.organization_id
        OR department.organization_id IS DISTINCT FROM position.organization_id
        OR department.edition_id IS DISTINCT FROM position.edition_id
        OR template.organization_id IS DISTINCT FROM position.organization_id
        OR role_bundle.organization_id IS DISTINCT FROM position.organization_id
        OR (
            position.reports_to_id IS NOT NULL
            AND (
                manager.organization_id IS DISTINCT FROM position.organization_id
                OR manager.edition_id IS DISTINCT FROM position.edition_id
                OR manager.id = position.id
            )
        );

    WITH RECURSIVE position_walk AS (
        SELECT position.id AS start_id,
               position.reports_to_id,
               ARRAY[position.id] AS path,
               false AS cycle
          FROM workforce_position AS position
        UNION ALL
        SELECT position_walk.start_id,
               manager.reports_to_id,
               position_walk.path || manager.id,
               manager.id = ANY(position_walk.path) AS cycle
          FROM position_walk
          JOIN workforce_position AS manager
            ON manager.id = position_walk.reports_to_id
         WHERE NOT position_walk.cycle
    )
    SELECT COUNT(DISTINCT start_id)
      INTO position_cycle_count
      FROM position_walk
     WHERE cycle;

    SELECT COUNT(*)
      INTO invalid_binding_scope_count
      FROM authorization_scopedresourcebinding AS binding
      LEFT JOIN workforce_department AS department
        ON department.id = binding.department_id
      LEFT JOIN workforce_position AS position
        ON binding.resource_kind = 'workforce.position'
       AND position.id = binding.resource_id
     WHERE department.organization_id IS DISTINCT FROM binding.organization_id
        OR department.edition_id IS DISTINCT FROM binding.edition_id
        OR position.id IS NULL
        OR position.organization_id IS DISTINCT FROM binding.organization_id
        OR position.edition_id IS DISTINCT FROM binding.edition_id
        OR position.department_id IS DISTINCT FROM binding.department_id;

    SELECT COUNT(*)
      INTO invalid_assignment_role_count
      FROM workforce_positionassignment AS assignment
      JOIN workforce_position AS position
        ON position.id = assignment.position_id
     WHERE assignment.role_assignment_id IS NOT NULL
       AND NOT maru_workforce_role_evidence_matches_position(
           assignment.role_assignment_id,
           position.id,
           position.organization_id,
           position.edition_id,
           position.department_id,
           assignment.account_id
       );

    SELECT COUNT(*)
      INTO retained_edition_role_count
      FROM workforce_positionassignment AS assignment
      JOIN authorization_roleassignment AS evidence
        ON evidence.id = assignment.role_assignment_id
     WHERE evidence.edition_id = assignment.edition_id
       AND evidence.department_id IS NULL
       AND evidence.resource_binding_id IS NULL;

    RAISE NOTICE
        'ADR 0041 retained edition-wide workforce role assignments: %',
        retained_edition_role_count;

    IF invalid_department_scope_count > 0
       OR department_cycle_count > 0
       OR invalid_position_scope_count > 0
       OR position_cycle_count > 0
       OR invalid_binding_scope_count > 0
       OR invalid_assignment_role_count > 0
    THEN
        RAISE EXCEPTION
            'ADR 0041 workforce blockers: d %, dc %, p %, pc %, b %, roles %',
            invalid_department_scope_count,
            department_cycle_count,
            invalid_position_scope_count,
            position_cycle_count,
            invalid_binding_scope_count,
            invalid_assignment_role_count
            USING ERRCODE = '23514';
    END IF;
END;
$$;
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS workforce_role_assignment_evidence_guard
ON authorization_roleassignment;
DROP FUNCTION IF EXISTS maru_guard_workforce_role_assignment_evidence();

CREATE OR REPLACE FUNCTION maru_guard_workforce_department()
RETURNS trigger AS $$
DECLARE
    edition_organization uuid;
    parent_organization uuid;
    parent_edition uuid;
BEGIN
    SELECT organization_id INTO edition_organization
      FROM events_eventedition WHERE id = NEW.edition_id;
    IF edition_organization IS NULL OR edition_organization <> NEW.organization_id THEN
        RAISE EXCEPTION 'workforce department edition scope mismatch';
    END IF;
    IF NEW.parent_id IS NOT NULL THEN
        SELECT organization_id, edition_id
          INTO parent_organization, parent_edition
          FROM workforce_department WHERE id = NEW.parent_id;
        IF parent_organization <> NEW.organization_id
           OR parent_edition <> NEW.edition_id
           OR NEW.parent_id = NEW.id THEN
            RAISE EXCEPTION 'workforce department parent scope mismatch';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION maru_guard_workforce_position()
RETURNS trigger AS $$
DECLARE
    scoped_organization uuid;
    scoped_edition uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'workforce positions cannot be deleted';
    END IF;
    SELECT organization_id INTO scoped_organization
      FROM events_eventedition WHERE id = NEW.edition_id;
    IF scoped_organization IS NULL OR scoped_organization <> NEW.organization_id THEN
        RAISE EXCEPTION 'workforce position edition scope mismatch';
    END IF;
    SELECT organization_id, edition_id INTO scoped_organization, scoped_edition
      FROM workforce_department WHERE id = NEW.department_id;
    IF scoped_organization <> NEW.organization_id
       OR scoped_edition <> NEW.edition_id THEN
        RAISE EXCEPTION 'workforce position department scope mismatch';
    END IF;
    SELECT organization_id INTO scoped_organization
      FROM workforce_positiontemplate WHERE id = NEW.template_id;
    IF scoped_organization <> NEW.organization_id THEN
        RAISE EXCEPTION 'workforce position template scope mismatch';
    END IF;
    SELECT organization_id INTO scoped_organization
      FROM authorization_rolebundle WHERE id = NEW.role_bundle_id;
    IF scoped_organization <> NEW.organization_id THEN
        RAISE EXCEPTION 'workforce position role scope mismatch';
    END IF;
    IF NEW.reports_to_id IS NOT NULL THEN
        SELECT organization_id, edition_id
          INTO scoped_organization, scoped_edition
          FROM workforce_position WHERE id = NEW.reports_to_id;
        IF scoped_organization <> NEW.organization_id
           OR scoped_edition <> NEW.edition_id
           OR NEW.reports_to_id = NEW.id THEN
            RAISE EXCEPTION 'workforce reporting line scope mismatch';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION maru_guard_workforce_assignment()
RETURNS trigger AS $$
DECLARE
    scoped_organization uuid;
    scoped_edition uuid;
    scoped_account uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'workforce assignments cannot be deleted';
    END IF;
    SELECT organization_id, edition_id
      INTO scoped_organization, scoped_edition
      FROM workforce_position WHERE id = NEW.position_id;
    IF scoped_organization <> NEW.organization_id
       OR scoped_edition <> NEW.edition_id THEN
        RAISE EXCEPTION 'workforce assignment position scope mismatch';
    END IF;
    IF NEW.approved_by_id IS NOT NULL
       AND NEW.approved_by_id = NEW.proposed_by_id THEN
        RAISE EXCEPTION 'workforce assignment requires independent approval';
    END IF;
    IF NEW.role_assignment_id IS NOT NULL THEN
        SELECT organization_id, edition_id, principal_id
          INTO scoped_organization, scoped_edition, scoped_account
          FROM authorization_roleassignment WHERE id = NEW.role_assignment_id;
        IF scoped_organization <> NEW.organization_id
           OR scoped_edition IS DISTINCT FROM NEW.edition_id
           OR scoped_account <> NEW.account_id THEN
            RAISE EXCEPTION 'workforce assignment role evidence scope mismatch';
        END IF;
    END IF;
    IF NEW.participation_capacity_id IS NOT NULL THEN
        SELECT p.organization_id, p.edition_id, p.account_id
          INTO scoped_organization, scoped_edition, scoped_account
          FROM participation_participationcapacity c
          JOIN participation_participation p ON p.id = c.participation_id
         WHERE c.id = NEW.participation_capacity_id;
        IF scoped_organization <> NEW.organization_id
           OR scoped_edition <> NEW.edition_id
           OR scoped_account <> NEW.account_id THEN
            RAISE EXCEPTION 'workforce assignment capacity evidence scope mismatch';
        END IF;
    END IF;
    IF NEW.status = 'active' AND (
        NEW.approved_by_id IS NULL
        OR NEW.role_assignment_id IS NULL
        OR NEW.participation_capacity_id IS NULL
    ) THEN
        RAISE EXCEPTION 'active workforce assignment lacks approval evidence';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF OLD.status = 'active' AND NEW.status = 'active'
           AND NEW IS DISTINCT FROM OLD THEN
            RAISE EXCEPTION 'active workforce assignments are immutable';
        END IF;
        IF OLD.status <> NEW.status AND NOT (
            (OLD.status = 'proposed' AND NEW.status = 'active')
            OR (OLD.status = 'active' AND NEW.status = 'ended')
        ) THEN
            RAISE EXCEPTION 'invalid workforce assignment status transition';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP FUNCTION IF EXISTS maru_workforce_role_evidence_matches_position(
    uuid,
    uuid,
    uuid,
    uuid,
    uuid,
    uuid
);
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0004_scope_v2_schema"),
        ("workforce", "0003_idn011_convention_subject_guards"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
