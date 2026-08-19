"""Report ADR 0041 scope-v2 blockers without exposing authority subjects."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connection
from django.db.models import Count

from maru.authorization.catalog import Capability, ScopeLevel, capability
from maru.authorization.models import CapabilityGrant, RoleAssignment, RoleBundle

if TYPE_CHECKING:
    from collections.abc import Iterable

BLOCKER_KEYS = (
    "binding_scope_mismatch",
    "capability_grant_scope_too_broad",
    "delegation_cycle",
    "delegation_edge_mismatch",
    "department_cycle",
    "department_scope_mismatch",
    "malformed_capability_grant_scope",
    "malformed_role_bundle",
    "malformed_role_assignment_scope",
    "missing_position_binding",
    "nonpersistable_capability_grant",
    "nonpersistable_role_bundle",
    "invalid_capability_grant_revocation",
    "invalid_role_assignment_revocation",
    "position_assignment_role_evidence_mismatch",
    "position_scope_mismatch",
    "role_assignment_scope_too_broad",
    "role_bundle_organization_mismatch",
    "unknown_capability_grant",
    "unknown_role_bundle_capability",
)

REVIEW_KEYS = ("legacy_edition_wide_position_role_assignment",)

SCOPE_RANK = {
    ScopeLevel.ORGANIZATION: 0,
    ScopeLevel.EDITION: 1,
    ScopeLevel.DEPARTMENT: 2,
    ScopeLevel.RESOURCE: 3,
}


def _scalar(sql: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()
    return int(row[0]) if row is not None else 0


def _scope_rank(
    *,
    edition_id: object,
    department_id: object,
    resource_binding_id: object,
) -> int:
    if resource_binding_id is not None:
        return 3
    if department_id is not None:
        return 2
    if edition_id is not None:
        return 1
    return 0


def _catalog_grant_counts() -> dict[str, int]:
    unknown = 0
    nonpersistable = 0
    scope_too_broad = 0
    grants = CapabilityGrant.objects.values(
        "capability_code",
        "edition_id",
        "department_id",
        "resource_binding_id",
    ).annotate(record_count=Count("id"))
    for grant in grants.iterator(chunk_size=500):
        definition = capability(str(grant["capability_code"]))
        count = int(grant["record_count"])
        if definition is None:
            unknown += count
            continue
        if not definition.persistable:
            nonpersistable += count
            continue
        rank = _scope_rank(
            edition_id=grant["edition_id"],
            department_id=grant["department_id"],
            resource_binding_id=grant["resource_binding_id"],
        )
        if rank < SCOPE_RANK[definition.maximum_scope]:
            scope_too_broad += count
    return {
        "unknown_capability_grant": unknown,
        "nonpersistable_capability_grant": nonpersistable,
        "capability_grant_scope_too_broad": scope_too_broad,
    }


def _invalid_bundle_categories(codes: Iterable[str | None]) -> tuple[bool, bool]:
    unknown = False
    nonpersistable = False
    for code in codes:
        if code is None:
            continue
        definition = capability(str(code))
        if definition is None:
            unknown = True
        elif not definition.persistable:
            nonpersistable = True
    return unknown, nonpersistable


def _catalog_role_counts() -> dict[str, int]:
    unknown_bundle_ids: set[object] = set()
    nonpersistable_bundle_ids: set[object] = set()
    malformed_bundle_ids: set[object] = set()
    definitions_by_bundle: dict[object, tuple[Capability, ...]] = {}
    for bundle in RoleBundle.objects.values("id", "capability_codes").iterator(
        chunk_size=500
    ):
        raw_codes = tuple(bundle["capability_codes"])
        codes = tuple(str(code) for code in raw_codes if code is not None)
        if (
            not raw_codes
            or any(code is None for code in raw_codes)
            or len(codes) != len(set(codes))
        ):
            malformed_bundle_ids.add(bundle["id"])
        unknown, nonpersistable = _invalid_bundle_categories(raw_codes)
        if unknown:
            unknown_bundle_ids.add(bundle["id"])
        if nonpersistable:
            nonpersistable_bundle_ids.add(bundle["id"])
        definitions_by_bundle[bundle["id"]] = tuple(
            definition
            for code in codes
            if (definition := capability(code)) is not None and definition.persistable
        )

    scope_too_broad = 0
    assignments = RoleAssignment.objects.values(
        "role_bundle_id",
        "edition_id",
        "department_id",
        "resource_binding_id",
    ).annotate(record_count=Count("id"))
    for assignment in assignments.iterator(chunk_size=500):
        rank = _scope_rank(
            edition_id=assignment["edition_id"],
            department_id=assignment["department_id"],
            resource_binding_id=assignment["resource_binding_id"],
        )
        definitions = definitions_by_bundle.get(assignment["role_bundle_id"], ())
        if any(rank < SCOPE_RANK[item.maximum_scope] for item in definitions):
            scope_too_broad += int(assignment["record_count"])

    return {
        "malformed_role_bundle": len(malformed_bundle_ids),
        "unknown_role_bundle_capability": len(unknown_bundle_ids),
        "nonpersistable_role_bundle": len(nonpersistable_bundle_ids),
        "role_assignment_scope_too_broad": scope_too_broad,
    }


def _database_blocker_counts() -> dict[str, int]:
    malformed_capability_grant_scope = _scalar(
        """
        SELECT COUNT(*)
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
                AND edition.organization_id
                    IS DISTINCT FROM authority.organization_id
            )
            OR (
                authority.department_id IS NOT NULL
                AND (
                    department.organization_id
                        IS DISTINCT FROM authority.organization_id
                    OR department.edition_id
                        IS DISTINCT FROM authority.edition_id
                )
            )
            OR (
                authority.resource_binding_id IS NOT NULL
                AND (
                    binding.organization_id
                        IS DISTINCT FROM authority.organization_id
                    OR binding.edition_id IS DISTINCT FROM authority.edition_id
                    OR binding.department_id
                        IS DISTINCT FROM authority.department_id
                )
            )
        """
    )
    malformed_role_assignment_scope = _scalar(
        """
        SELECT COUNT(*)
          FROM authorization_roleassignment AS authority
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
                AND edition.organization_id
                    IS DISTINCT FROM authority.organization_id
            )
            OR (
                authority.department_id IS NOT NULL
                AND (
                    department.organization_id
                        IS DISTINCT FROM authority.organization_id
                    OR department.edition_id
                        IS DISTINCT FROM authority.edition_id
                )
            )
            OR (
                authority.resource_binding_id IS NOT NULL
                AND (
                    binding.organization_id
                        IS DISTINCT FROM authority.organization_id
                    OR binding.edition_id IS DISTINCT FROM authority.edition_id
                    OR binding.department_id
                        IS DISTINCT FROM authority.department_id
                )
            )
        """
    )
    role_bundle_organization_mismatch = _scalar(
        """
        SELECT COUNT(*)
          FROM authorization_roleassignment AS authority
          LEFT JOIN authorization_rolebundle AS bundle
            ON bundle.id = authority.role_bundle_id
         WHERE bundle.organization_id IS DISTINCT FROM authority.organization_id
        """
    )
    delegation_edge_mismatch = _scalar(
        """
        SELECT COUNT(*)
          FROM authorization_capabilitygrant AS child
          LEFT JOIN authorization_capabilitygrant AS parent
            ON parent.id = child.delegated_from_id
         WHERE child.delegated_from_id IS NOT NULL
           AND (
                parent.id IS NULL
                OR parent.principal_id IS DISTINCT FROM child.granted_by_id
                OR parent.capability_code IS DISTINCT FROM child.capability_code
                OR parent.organization_id IS DISTINCT FROM child.organization_id
                OR (
                    parent.edition_id IS NOT NULL
                    AND parent.edition_id IS DISTINCT FROM child.edition_id
                )
                OR (
                    parent.department_id IS NOT NULL
                    AND parent.department_id IS DISTINCT FROM child.department_id
                )
                OR (
                    parent.resource_binding_id IS NOT NULL
                    AND parent.resource_binding_id
                        IS DISTINCT FROM child.resource_binding_id
                )
                OR child.effective_from < parent.effective_from
                OR (
                    parent.expires_at IS NOT NULL
                    AND (
                        child.expires_at IS NULL
                        OR child.expires_at > parent.expires_at
                    )
                )
           )
        """
    )
    delegation_cycle = _scalar(
        """
        WITH RECURSIVE walk AS (
            SELECT authority.id AS start_id,
                   authority.delegated_from_id AS next_id,
                   ARRAY[authority.id] AS path,
                   false AS cycle
              FROM authorization_capabilitygrant AS authority
             WHERE authority.delegated_from_id IS NOT NULL
            UNION ALL
            SELECT walk.start_id,
                   parent.delegated_from_id,
                   walk.path || parent.id,
                   parent.id = ANY(walk.path) AS cycle
              FROM walk
              JOIN authorization_capabilitygrant AS parent
                ON parent.id = walk.next_id
             WHERE NOT walk.cycle
               AND walk.next_id IS NOT NULL
        )
        SELECT COUNT(DISTINCT start_id) FROM walk WHERE cycle
        """
    )
    department_scope_mismatch = _scalar(
        """
        SELECT COUNT(*)
          FROM workforce_department AS department
          LEFT JOIN events_eventedition AS edition
            ON edition.id = department.edition_id
          LEFT JOIN workforce_department AS parent
            ON parent.id = department.parent_id
         WHERE edition.organization_id
                IS DISTINCT FROM department.organization_id
            OR (
                department.parent_id IS NOT NULL
                AND (
                    parent.organization_id
                        IS DISTINCT FROM department.organization_id
                    OR parent.edition_id IS DISTINCT FROM department.edition_id
                )
            )
        """
    )
    department_cycle = _scalar(
        """
        WITH RECURSIVE walk AS (
            SELECT department.id AS start_id,
                   department.parent_id AS next_id,
                   ARRAY[department.id] AS path,
                   false AS cycle
              FROM workforce_department AS department
             WHERE department.parent_id IS NOT NULL
            UNION ALL
            SELECT walk.start_id,
                   parent.parent_id,
                   walk.path || parent.id,
                   parent.id = ANY(walk.path) AS cycle
              FROM walk
              JOIN workforce_department AS parent
                ON parent.id = walk.next_id
             WHERE NOT walk.cycle
               AND walk.next_id IS NOT NULL
        )
        SELECT COUNT(DISTINCT start_id) FROM walk WHERE cycle
        """
    )
    position_scope_mismatch = _scalar(
        """
        SELECT COUNT(*)
          FROM workforce_position AS position
          LEFT JOIN events_eventedition AS edition
            ON edition.id = position.edition_id
          LEFT JOIN workforce_department AS department
            ON department.id = position.department_id
          LEFT JOIN workforce_positiontemplate AS template
            ON template.id = position.template_id
          LEFT JOIN authorization_rolebundle AS bundle
            ON bundle.id = position.role_bundle_id
          LEFT JOIN workforce_position AS manager
            ON manager.id = position.reports_to_id
         WHERE edition.organization_id IS DISTINCT FROM position.organization_id
            OR department.organization_id
                IS DISTINCT FROM position.organization_id
            OR department.edition_id IS DISTINCT FROM position.edition_id
            OR template.organization_id IS DISTINCT FROM position.organization_id
            OR bundle.organization_id IS DISTINCT FROM position.organization_id
            OR (
                position.reports_to_id IS NOT NULL
                AND (
                    manager.organization_id
                        IS DISTINCT FROM position.organization_id
                    OR manager.edition_id IS DISTINCT FROM position.edition_id
                    OR manager.id = position.id
                )
            )
        """
    )
    binding_scope_mismatch = _scalar(
        """
        SELECT COUNT(*)
          FROM authorization_scopedresourcebinding AS binding
          LEFT JOIN workforce_department AS department
            ON department.id = binding.department_id
          LEFT JOIN workforce_position AS position
            ON binding.resource_kind = 'workforce.position'
           AND position.id = binding.resource_id
         WHERE binding.resource_kind <> 'workforce.position'
            OR position.id IS NULL
            OR department.organization_id
                IS DISTINCT FROM binding.organization_id
            OR department.edition_id IS DISTINCT FROM binding.edition_id
            OR position.organization_id IS DISTINCT FROM binding.organization_id
            OR position.edition_id IS DISTINCT FROM binding.edition_id
            OR position.department_id IS DISTINCT FROM binding.department_id
        """
    )
    missing_position_binding = _scalar(
        """
        SELECT COUNT(*)
          FROM workforce_position AS position
         WHERE NOT EXISTS (
             SELECT 1
               FROM authorization_scopedresourcebinding AS binding
              WHERE binding.resource_kind = 'workforce.position'
                AND binding.resource_id = position.id
                AND binding.organization_id = position.organization_id
                AND binding.edition_id = position.edition_id
                AND binding.department_id = position.department_id
         )
        """
    )
    position_assignment_role_evidence_mismatch = _scalar(
        """
        SELECT COUNT(*)
          FROM workforce_positionassignment AS workforce_assignment
          JOIN workforce_position AS position
            ON position.id = workforce_assignment.position_id
          LEFT JOIN authorization_roleassignment AS authority
            ON authority.id = workforce_assignment.role_assignment_id
          LEFT JOIN authorization_scopedresourcebinding AS binding
            ON binding.id = authority.resource_binding_id
         WHERE workforce_assignment.role_assignment_id IS NOT NULL
           AND (
                authority.id IS NULL
                OR authority.organization_id
                    IS DISTINCT FROM position.organization_id
                OR authority.edition_id IS DISTINCT FROM position.edition_id
                OR authority.principal_id
                    IS DISTINCT FROM workforce_assignment.account_id
                OR NOT (
                    (
                        authority.department_id IS NULL
                        AND authority.resource_binding_id IS NULL
                    )
                    OR (
                        authority.department_id = position.department_id
                        AND authority.resource_binding_id IS NULL
                    )
                    OR (
                        authority.department_id = position.department_id
                        AND binding.resource_kind = 'workforce.position'
                        AND binding.resource_id = position.id
                        AND binding.organization_id = position.organization_id
                        AND binding.edition_id = position.edition_id
                        AND binding.department_id = position.department_id
                    )
                )
           )
        """
    )
    invalid_capability_grant_revocation = _scalar(
        """
        SELECT COUNT(*)
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
            )
        """
    )
    invalid_role_assignment_revocation = _scalar(
        """
        SELECT COUNT(*)
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
            )
        """
    )
    return {
        "binding_scope_mismatch": binding_scope_mismatch,
        "delegation_cycle": delegation_cycle,
        "delegation_edge_mismatch": delegation_edge_mismatch,
        "department_cycle": department_cycle,
        "department_scope_mismatch": department_scope_mismatch,
        "malformed_capability_grant_scope": malformed_capability_grant_scope,
        "malformed_role_assignment_scope": malformed_role_assignment_scope,
        "missing_position_binding": missing_position_binding,
        "invalid_capability_grant_revocation": (invalid_capability_grant_revocation),
        "invalid_role_assignment_revocation": invalid_role_assignment_revocation,
        "position_assignment_role_evidence_mismatch": (
            position_assignment_role_evidence_mismatch
        ),
        "position_scope_mismatch": position_scope_mismatch,
        "role_bundle_organization_mismatch": role_bundle_organization_mismatch,
    }


def _review_counts() -> dict[str, int]:
    return {
        "legacy_edition_wide_position_role_assignment": _scalar(
            """
            SELECT COUNT(*)
              FROM workforce_positionassignment AS workforce_assignment
              JOIN authorization_roleassignment AS authority
                ON authority.id = workforce_assignment.role_assignment_id
             WHERE authority.edition_id = workforce_assignment.edition_id
               AND authority.department_id IS NULL
               AND authority.resource_binding_id IS NULL
            """
        )
    }


def _build_report() -> dict[str, object]:
    blockers = {
        **_database_blocker_counts(),
        **_catalog_grant_counts(),
        **_catalog_role_counts(),
    }
    ordered_blockers = {key: blockers[key] for key in BLOCKER_KEYS}
    reviews = _review_counts()
    return {
        "status": "blocked" if any(ordered_blockers.values()) else "ready",
        "production_status": "blocked",
        "blocker_counts": ordered_blockers,
        "blocker_total": sum(ordered_blockers.values()),
        "review_counts": {key: reviews[key] for key in REVIEW_KEYS},
        "known_production_gates": {
            "actor_approver_authority_source_provenance": "unresolved",
        },
    }


class Command(BaseCommand):
    """Execute the Django management command."""

    help = "Inspect ADR 0041 scope-v2 data and emit a privacy-minimized JSON report."

    def add_arguments(self, parser: CommandParser) -> None:
        """Add arguments.

        Parameters
        ----------
        parser : CommandParser
            The parser that converts untrusted input into canonical domain data.
        """
        parser.add_argument(
            "--no-fail",
            action="store_true",
            help=("Return success even when blockers exist; JSON status is unchanged."),
        )

    def handle(self, *_args: Any, **options: Any) -> None:
        """Execute the management command.

        Parameters
        ----------
        *_args : Any
            Positional arguments forwarded to the framework implementation.
        **options : Any
            Management-command options supplied by Django.

        Raises
        ------
        CommandError
            If the command cannot complete safely with the supplied state.
        """
        report = _build_report()
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
        if report["status"] == "blocked" and not options["no_fail"]:
            raise CommandError(
                "Authorization scope-v2 blockers detected; inspect the JSON report."
            )
