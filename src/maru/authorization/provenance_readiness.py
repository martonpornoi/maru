"""Privacy-minimized deployment readiness for ADR 0044 authority lineage.

This module deliberately reports aggregate counts only.  It is a read-only
reconciliation aid: it never chooses a likely historical source, repairs a
target, or exposes an authority, person, capability, or tenant identifier.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, cast

from django.utils import timezone

from maru.authorization.models import (
    AuthorityControl,
    AuthorityIssuance,
    CapabilityGrant,
    RoleAssignment,
    RoleBundle,
)
from maru.authorization.policy import (
    ResolvedAuthorizationTarget,
    resolve_department_target,
    resolve_edition_target,
    resolve_organization_target,
    resolve_resource_target,
)
from maru.authorization.provenance import (
    MAX_AUTHORITY_LINEAGE_DEPTH,
    authority_issuance_is_current,
    role_bundle_provenance_is_historical,
)
from maru.identity.models import Account
from maru.organizations.models import (
    OrganizationRepresentation,
    RepresentationAppointment,
)

BLOCKER_KEYS = (
    "effective_or_future_root_grant_missing_issuance",
    "effective_or_future_delegated_grant_missing_issuance",
    "effective_or_future_role_assignment_missing_issuance",
    "referenced_or_assignable_role_bundle_missing_issuance",
    "delegated_grant_parent_missing_issuance",
    "delegated_grant_excess_controls",
    "target_issuance_shape_mismatch",
    "incomplete_control_set",
    "duplicate_control_role",
    "control_identity_mismatch",
    "control_metadata_mismatch",
    "control_source_not_earlier",
    "control_source_foreign",
    "control_source_capability_mismatch",
    "control_source_scope_mismatch",
    "control_source_horizon_mismatch",
    "control_source_not_current",
    "invalid_board_ceremony_basis",
    "lineage_cycle",
    "lineage_depth_exceeded",
    "malformed_lineage",
)

REVIEW_KEYS = (
    "expired_or_revoked_root_grant_missing_issuance",
    "expired_or_revoked_delegated_grant_missing_issuance",
    "expired_or_revoked_role_assignment_missing_issuance",
    "unused_role_bundle_missing_issuance",
    "preserved_broad_workforce_bootstrap_signature",
)

_ACTOR = AuthorityControl.Role.ACTOR
_APPROVER = AuthorityControl.Role.APPROVER
_PERSISTENT = AuthorityControl.Basis.PERSISTENT_AUTHORITY
_PLATFORM_BOOTSTRAP = AuthorityControl.Basis.PLATFORM_REPRESENTATION_BOOTSTRAP
_REPRESENTATION_ACCEPTANCE = AuthorityControl.Basis.REPRESENTATION_ACCEPTANCE
_BOARD_CODE = "executive-board"
_GRANT_CONTROL_CAPABILITY = "authorization.grant_direct"
_ROLE_CONTROL_CAPABILITY = "authorization.manage_roles"


def _rows_by(
    rows: Iterable[Mapping[str, Any]],
    key: str,
) -> dict[object, dict[str, Any]]:
    return {row[key]: dict(row) for row in rows}


def _has_open_horizon(row: Mapping[str, Any], *, at: datetime) -> bool:
    expires_at = row["expires_at"]
    return row["revoked_at"] is None and (expires_at is None or expires_at > at)


def _target_scope(row: Mapping[str, Any]) -> tuple[object, object, object, object]:
    return (
        row["organization_id"],
        row.get("edition_id"),
        row.get("department_id"),
        row.get("resource_binding_id"),
    )


def _scope_contains(
    *,
    source: tuple[object, object, object, object],
    target: tuple[object, object, object, object],
) -> bool:
    source_organization, source_edition, source_department, source_resource = source
    target_organization, target_edition, target_department, target_resource = target
    if source_organization != target_organization:
        return False
    if source_resource is not None:
        return source_resource == target_resource
    if source_department is not None:
        return (
            source_edition == target_edition and source_department == target_department
        )
    if source_edition is not None:
        return source_edition == target_edition
    return True


def _resolved_target(
    row: Mapping[str, Any],
) -> ResolvedAuthorizationTarget | None:
    organization_id = row["organization_id"]
    edition_id = row.get("edition_id")
    department_id = row.get("department_id")
    resource_binding_id = row.get("resource_binding_id")
    if resource_binding_id is not None:
        if edition_id is None or department_id is None:
            return None
        return resolve_resource_target(
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=department_id,
            resource_binding_id=resource_binding_id,
        )
    if department_id is not None:
        if edition_id is None:
            return None
        return resolve_department_target(
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=department_id,
        )
    if edition_id is not None:
        return resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        )
    return resolve_organization_target(organization_id=organization_id)


class _AuthorityGraph:
    """One request-local, identifier-bearing graph whose output is counts only."""

    def __init__(self, *, at: datetime) -> None:
        self.at = at
        self.grants = _rows_by(
            CapabilityGrant.objects.values(
                "id",
                "organization_id",
                "edition_id",
                "department_id",
                "resource_binding_id",
                "principal_id",
                "capability_code",
                "effective_from",
                "expires_at",
                "revoked_at",
                "granted_by_id",
                "approved_by_id",
                "delegated_from_id",
            ).iterator(chunk_size=500),
            "id",
        )
        self.bundles = _rows_by(
            RoleBundle.objects.values(
                "id",
                "organization_id",
                "code",
                "version",
                "capability_codes",
                "created_by_id",
                "approved_by_id",
            ).iterator(chunk_size=500),
            "id",
        )
        self.assignments = _rows_by(
            RoleAssignment.objects.values(
                "id",
                "organization_id",
                "edition_id",
                "department_id",
                "resource_binding_id",
                "principal_id",
                "role_bundle_id",
                "effective_from",
                "expires_at",
                "revoked_at",
                "granted_by_id",
                "approved_by_id",
            ).iterator(chunk_size=500),
            "id",
        )
        self.issuances = _rows_by(
            AuthorityIssuance.objects.values(
                "ordinal",
                "policy_version",
                "evaluated_at",
                "capability_grant_id",
                "role_bundle_id",
                "role_assignment_id",
            ).iterator(chunk_size=500),
            "ordinal",
        )
        self.controls = [
            dict(row)
            for row in AuthorityControl.objects.values(
                "id",
                "issuance_id",
                "role",
                "principal_id",
                "basis",
                "source_issuance_id",
                "representation_id",
                "appointment_id",
                "policy_version",
                "evaluated_at",
            )
            .order_by("issuance_id", "role", "id")
            .iterator(chunk_size=500)
        ]
        self.controls_by_issuance: dict[object, list[dict[str, Any]]] = defaultdict(
            list
        )
        for control in self.controls:
            self.controls_by_issuance[control["issuance_id"]].append(control)
        self.accounts = _rows_by(
            Account.objects.values("id", "account_kind", "is_active").iterator(
                chunk_size=500
            ),
            "id",
        )
        self.representations = _rows_by(
            OrganizationRepresentation.objects.values(
                "id",
                "organization_id",
                "state",
                "activated_by_id",
                "activated_at",
            ).iterator(chunk_size=500),
            "id",
        )
        self.appointments = _rows_by(
            RepresentationAppointment.objects.values(
                "id",
                "representation_id",
                "account_id",
                "role",
                "state",
                "responded_at",
                "role_assignment_id",
            ).iterator(chunk_size=500),
            "id",
        )

        self.open_grant_ids = {
            grant_id
            for grant_id, grant in self.grants.items()
            if _has_open_horizon(grant, at=at)
        }
        self.open_assignment_ids = {
            assignment_id
            for assignment_id, assignment in self.assignments.items()
            if _has_open_horizon(assignment, at=at)
        }
        latest_bundle_ids: set[object] = set()
        latest: dict[tuple[object, object], tuple[int, object]] = {}
        for bundle_id, bundle in self.bundles.items():
            key = (bundle["organization_id"], bundle["code"])
            candidate = (int(bundle["version"]), bundle_id)
            if key not in latest or candidate[0] > latest[key][0]:
                latest[key] = candidate
        latest_bundle_ids.update(bundle_id for _version, bundle_id in latest.values())
        referenced_bundle_ids = {
            self.assignments[assignment_id]["role_bundle_id"]
            for assignment_id in self.open_assignment_ids
        }
        self.reachable_bundle_ids = latest_bundle_ids | referenced_bundle_ids

        issuance_groups: dict[str, dict[object, list[object]]] = {
            "capability_grant_id": defaultdict(list),
            "role_bundle_id": defaultdict(list),
            "role_assignment_id": defaultdict(list),
        }
        for ordinal, row in self.issuances.items():
            for field, groups in issuance_groups.items():
                target_id = row[field]
                if target_id is not None:
                    groups[target_id].append(ordinal)

        reachable_target_ids = {
            "capability_grant_id": self.open_grant_ids,
            "role_bundle_id": self.reachable_bundle_ids,
            "role_assignment_id": self.open_assignment_ids,
        }
        self.duplicate_target_issuance_ordinals: set[object] = set()
        for field, groups in issuance_groups.items():
            for target_id, ordinals in groups.items():
                if len(ordinals) > 1 and target_id in reachable_target_ids[field]:
                    self.duplicate_target_issuance_ordinals.update(ordinals)

        def deterministic_index(field: str) -> dict[object, object]:
            return {
                target_id: min(ordinals, key=lambda value: cast(int, value))
                for target_id, ordinals in issuance_groups[field].items()
            }

        self.issuance_by_grant = deterministic_index("capability_grant_id")
        self.issuance_by_bundle = deterministic_index("role_bundle_id")
        self.issuance_by_assignment = deterministic_index("role_assignment_id")
        self.reachable_issuances = self._reachable_issuance_ordinals()

    def _reachable_issuance_ordinals(self) -> set[object]:
        reachable = {
            ordinal
            for target_id in self.open_grant_ids
            if (ordinal := self.issuance_by_grant.get(target_id)) is not None
        }
        reachable.update(
            ordinal
            for target_id in self.open_assignment_ids
            if (ordinal := self.issuance_by_assignment.get(target_id)) is not None
        )
        reachable.update(
            ordinal
            for target_id in self.reachable_bundle_ids
            if (ordinal := self.issuance_by_bundle.get(target_id)) is not None
        )
        changed = True
        while changed:
            changed = False
            for ordinal in tuple(reachable):
                for control in self.controls_by_issuance.get(ordinal, ()):
                    source = control["source_issuance_id"]
                    if source is not None and source not in reachable:
                        reachable.add(source)
                        changed = True
                resolved = self._issuance_target(ordinal)
                if resolved is None or resolved[0] != "grant":
                    continue
                parent_id = resolved[1]["delegated_from_id"]
                parent_issuance = self.issuance_by_grant.get(parent_id)
                if parent_issuance is not None and parent_issuance not in reachable:
                    reachable.add(parent_issuance)
                    changed = True
        return reachable

    def _issuance_target(self, ordinal: object) -> tuple[str, dict[str, Any]] | None:
        issuance = self.issuances.get(ordinal)
        if issuance is None:
            return None
        target_ids = (
            ("grant", issuance["capability_grant_id"], self.grants),
            ("bundle", issuance["role_bundle_id"], self.bundles),
            ("assignment", issuance["role_assignment_id"], self.assignments),
        )
        present = [item for item in target_ids if item[1] is not None]
        if len(present) != 1:
            return None
        kind, target_id, records = present[0]
        target = records.get(target_id)
        return (kind, target) if target is not None else None

    def missing_and_review_counts(self) -> tuple[dict[str, int], dict[str, int]]:
        root_open = {
            grant_id
            for grant_id in self.open_grant_ids
            if self.grants[grant_id]["delegated_from_id"] is None
        }
        delegated_open = self.open_grant_ids - root_open
        root_closed = {
            grant_id
            for grant_id, grant in self.grants.items()
            if grant["delegated_from_id"] is None
            and not _has_open_horizon(grant, at=self.at)
        }
        delegated_closed = set(self.grants) - root_open - delegated_open - root_closed
        blockers = {
            "effective_or_future_root_grant_missing_issuance": sum(
                grant_id not in self.issuance_by_grant for grant_id in root_open
            ),
            "effective_or_future_delegated_grant_missing_issuance": sum(
                grant_id not in self.issuance_by_grant for grant_id in delegated_open
            ),
            "effective_or_future_role_assignment_missing_issuance": sum(
                assignment_id not in self.issuance_by_assignment
                for assignment_id in self.open_assignment_ids
            ),
            "referenced_or_assignable_role_bundle_missing_issuance": sum(
                bundle_id not in self.issuance_by_bundle
                for bundle_id in self.reachable_bundle_ids
            ),
        }
        reviews = {
            "expired_or_revoked_root_grant_missing_issuance": sum(
                grant_id not in self.issuance_by_grant for grant_id in root_closed
            ),
            "expired_or_revoked_delegated_grant_missing_issuance": sum(
                grant_id not in self.issuance_by_grant for grant_id in delegated_closed
            ),
            "expired_or_revoked_role_assignment_missing_issuance": sum(
                assignment_id not in self.issuance_by_assignment
                for assignment_id in set(self.assignments) - self.open_assignment_ids
            ),
            "unused_role_bundle_missing_issuance": sum(
                bundle_id not in self.issuance_by_bundle
                for bundle_id in set(self.bundles) - self.reachable_bundle_ids
            ),
            "preserved_broad_workforce_bootstrap_signature": (
                self._broad_bootstrap_signature_count()
            ),
        }
        return blockers, reviews

    def _broad_bootstrap_signature_count(self) -> int:
        platform_ids = {
            account_id
            for account_id, account in self.accounts.items()
            if account["account_kind"] == Account.Kind.PLATFORM_ADMINISTRATOR
        }
        organizations: set[object] = set()
        for bundle_id, bundle in self.bundles.items():
            creator_id = bundle["created_by_id"]
            if (
                bundle["code"] != "authority-controller"
                or creator_id not in platform_ids
            ):
                continue
            if any(
                assignment["role_bundle_id"] == bundle_id
                and assignment["granted_by_id"] == creator_id
                and assignment["approved_by_id"] == creator_id
                for assignment in self.assignments.values()
            ):
                organizations.add(bundle["organization_id"])
        return len(organizations)

    def _ordinary_attribution(
        self,
        kind: str,
        target: Mapping[str, Any],
    ) -> tuple[object, object, object, str]:
        if kind == "bundle":
            return (
                target["created_by_id"],
                target["approved_by_id"],
                None,
                _ROLE_CONTROL_CAPABILITY,
            )
        required = (
            _GRANT_CONTROL_CAPABILITY if kind == "grant" else _ROLE_CONTROL_CAPABILITY
        )
        return (
            target["granted_by_id"],
            target["approved_by_id"],
            target["principal_id"],
            required,
        )

    def _source_target(
        self, source_ordinal: object
    ) -> tuple[str, dict[str, Any]] | None:
        resolved = self._issuance_target(source_ordinal)
        if resolved is None or resolved[0] not in {"grant", "assignment"}:
            return None
        return resolved

    def _source_capabilities(
        self,
        source_kind: str,
        source: Mapping[str, Any],
    ) -> set[str]:
        if source_kind == "grant":
            return {str(source["capability_code"])}
        bundle = self.bundles.get(source["role_bundle_id"])
        if bundle is None:
            return set()
        return {str(code) for code in bundle["capability_codes"] if code is not None}

    def _board_target(self, kind: str, target: Mapping[str, Any]) -> bool:
        if kind == "bundle":
            return bool(target["code"] == _BOARD_CODE)
        if kind != "assignment":
            return False
        bundle = self.bundles.get(target["role_bundle_id"])
        return bundle is not None and bundle["code"] == _BOARD_CODE

    def _board_basis_valid(
        self,
        *,
        kind: str,
        target: Mapping[str, Any],
        issuance: Mapping[str, Any],
        controls: Mapping[str, Mapping[str, Any]],
    ) -> bool:
        if not self._board_target(kind, target) or set(controls) != {
            _ACTOR,
            _APPROVER,
        }:
            return False
        actor = controls[_ACTOR]
        approver = controls[_APPROVER]
        if (
            actor["basis"] != _PLATFORM_BOOTSTRAP
            or actor["source_issuance_id"] is not None
            or actor["representation_id"] is None
            or actor["appointment_id"] is not None
            or approver["basis"] != _REPRESENTATION_ACCEPTANCE
            or approver["source_issuance_id"] is not None
            or approver["representation_id"] is not None
            or approver["appointment_id"] is None
        ):
            return False
        representation = self.representations.get(actor["representation_id"])
        appointment = self.appointments.get(approver["appointment_id"])
        platform_actor = self.accounts.get(actor["principal_id"])
        if representation is None or appointment is None or platform_actor is None:
            return False
        actor_id, approver_id, recipient_id, _required = self._ordinary_attribution(
            kind, target
        )
        evaluated_at = issuance["evaluated_at"]
        valid = (
            actor_id == actor["principal_id"]
            and approver_id == approver["principal_id"]
            and actor["principal_id"] != approver["principal_id"]
            and approver["principal_id"] != recipient_id
            and representation["organization_id"] == target["organization_id"]
            and representation["activated_by_id"] == actor["principal_id"]
            and representation["activated_at"] == evaluated_at
            and platform_actor["account_kind"] == Account.Kind.PLATFORM_ADMINISTRATOR
            and appointment["representation_id"] == representation["id"]
            and appointment["account_id"] == approver["principal_id"]
            and appointment["role"] == RepresentationAppointment.Role.CONTROLLER
            and appointment["state"]
            in {
                RepresentationAppointment.State.ACCEPTED,
                RepresentationAppointment.State.ACTIVE,
                RepresentationAppointment.State.ENDED,
            }
            and appointment["responded_at"] is not None
            and appointment["responded_at"] <= evaluated_at
        )
        if kind == "assignment":
            valid = valid and (
                target["edition_id"] is None
                and target["department_id"] is None
                and target["resource_binding_id"] is None
                and target["effective_from"] == evaluated_at
                and target["expires_at"] is None
            )
        return valid

    def structural_blocker_counts(self) -> dict[str, int]:  # noqa: PLR0912, PLR0915
        affected: dict[str, set[object]] = {
            key: set()
            for key in BLOCKER_KEYS
            if key
            not in {
                "effective_or_future_root_grant_missing_issuance",
                "effective_or_future_delegated_grant_missing_issuance",
                "effective_or_future_role_assignment_missing_issuance",
                "referenced_or_assignable_role_bundle_missing_issuance",
                "delegated_grant_parent_missing_issuance",
                "delegated_grant_excess_controls",
            }
        }
        delegated_parent_missing: set[object] = set()
        delegated_excess: set[object] = set()
        affected["target_issuance_shape_mismatch"].update(
            self.duplicate_target_issuance_ordinals
        )

        for grant_id in self.open_grant_ids:
            grant = self.grants[grant_id]
            if grant["delegated_from_id"] is None:
                continue
            issuance_ordinal = self.issuance_by_grant.get(grant_id)
            if issuance_ordinal is not None and self.controls_by_issuance.get(
                issuance_ordinal
            ):
                delegated_excess.add(grant_id)
            parent_id = grant["delegated_from_id"]
            if parent_id not in self.issuance_by_grant:
                delegated_parent_missing.add(grant_id)

        graph_edges: dict[object, set[object]] = defaultdict(set)
        for ordinal in self.reachable_issuances:
            issuance = self.issuances.get(ordinal)
            resolved = self._issuance_target(ordinal)
            if issuance is None or resolved is None:
                affected["target_issuance_shape_mismatch"].add(ordinal)
                affected["malformed_lineage"].add(ordinal)
                continue
            kind, target = resolved
            target_ids = (
                issuance["capability_grant_id"],
                issuance["role_bundle_id"],
                issuance["role_assignment_id"],
            )
            if sum(target_id is not None for target_id in target_ids) != 1:
                affected["target_issuance_shape_mismatch"].add(ordinal)
            if not issuance["policy_version"]:
                affected["control_metadata_mismatch"].add(ordinal)
                affected["malformed_lineage"].add(ordinal)

            controls = self.controls_by_issuance.get(ordinal, [])
            if kind == "grant" and target["delegated_from_id"] is not None:
                parent_id = target["delegated_from_id"]
                parent_issuance = self.issuance_by_grant.get(parent_id)
                if parent_issuance is None:
                    affected["malformed_lineage"].add(ordinal)
                else:
                    graph_edges[ordinal].add(parent_issuance)
                    parent = self.grants.get(parent_id)
                    if (
                        cast(int, parent_issuance) >= cast(int, ordinal)
                        or parent is None
                        or parent["principal_id"] != target["granted_by_id"]
                        or parent["capability_code"] != target["capability_code"]
                        or not _scope_contains(
                            source=_target_scope(parent),
                            target=_target_scope(target),
                        )
                        or target["effective_from"] < parent["effective_from"]
                        or (
                            parent["expires_at"] is not None
                            and (
                                target["expires_at"] is None
                                or target["expires_at"] > parent["expires_at"]
                            )
                        )
                    ):
                        affected["malformed_lineage"].add(ordinal)
                    if cast(int, parent_issuance) >= cast(int, ordinal):
                        affected["control_source_not_earlier"].add(ordinal)
                continue

            role_counts = Counter(str(control["role"]) for control in controls)
            if len(controls) != len({_ACTOR, _APPROVER}) or set(role_counts) != {
                _ACTOR,
                _APPROVER,
            }:
                affected["incomplete_control_set"].add(ordinal)
            if any(count > 1 for count in role_counts.values()):
                affected["duplicate_control_role"].add(ordinal)
            by_role = {
                str(control["role"]): control
                for control in controls
                if control["role"] in {_ACTOR, _APPROVER}
            }
            actor_id, approver_id, recipient_id, required_capability = (
                self._ordinary_attribution(kind, target)
            )
            if (
                actor_id is None
                or approver_id is None
                or approver_id in {actor_id, recipient_id}
                or (_ACTOR in by_role and by_role[_ACTOR]["principal_id"] != actor_id)
                or (
                    _APPROVER in by_role
                    and by_role[_APPROVER]["principal_id"] != approver_id
                )
            ):
                affected["control_identity_mismatch"].add(ordinal)

            uses_special_basis = any(
                control["basis"] in {_PLATFORM_BOOTSTRAP, _REPRESENTATION_ACCEPTANCE}
                for control in controls
            )
            if (
                uses_special_basis or self._board_target(kind, target)
            ) and not self._board_basis_valid(
                kind=kind,
                target=target,
                issuance=issuance,
                controls=by_role,
            ):
                affected["invalid_board_ceremony_basis"].add(ordinal)

            for control in controls:
                if (
                    control["policy_version"] != issuance["policy_version"]
                    or control["evaluated_at"] != issuance["evaluated_at"]
                ):
                    affected["control_metadata_mismatch"].add(ordinal)
                if control["basis"] != _PERSISTENT:
                    if control["basis"] not in {
                        _PLATFORM_BOOTSTRAP,
                        _REPRESENTATION_ACCEPTANCE,
                    }:
                        affected["malformed_lineage"].add(ordinal)
                    continue
                source_ordinal = control["source_issuance_id"]
                if (
                    source_ordinal is None
                    or control["representation_id"] is not None
                    or control["appointment_id"] is not None
                ):
                    affected["malformed_lineage"].add(ordinal)
                    continue
                graph_edges[ordinal].add(source_ordinal)
                if source_ordinal >= ordinal:
                    affected["control_source_not_earlier"].add(ordinal)
                source_resolved = self._source_target(source_ordinal)
                if source_resolved is None:
                    affected["control_source_foreign"].add(ordinal)
                    affected["malformed_lineage"].add(ordinal)
                    continue
                source_kind, source = source_resolved
                if (
                    source["principal_id"] != control["principal_id"]
                    or source["organization_id"] != target["organization_id"]
                ):
                    affected["control_source_foreign"].add(ordinal)
                if required_capability not in self._source_capabilities(
                    source_kind, source
                ):
                    affected["control_source_capability_mismatch"].add(ordinal)
                if not _scope_contains(
                    source=_target_scope(source),
                    target=(
                        (target["organization_id"], None, None, None)
                        if kind == "bundle"
                        else _target_scope(target)
                    ),
                ):
                    affected["control_source_scope_mismatch"].add(ordinal)
                evaluated_at = issuance["evaluated_at"]
                revoked_at = source["revoked_at"]
                if (
                    source["effective_from"] > evaluated_at
                    or (
                        source["expires_at"] is not None
                        and source["expires_at"] <= evaluated_at
                    )
                    or (revoked_at is not None and revoked_at <= evaluated_at)
                ):
                    affected["control_source_horizon_mismatch"].add(ordinal)
                if kind != "bundle" and (
                    target["effective_from"] < source["effective_from"]
                    or (
                        source["expires_at"] is not None
                        and (
                            target["expires_at"] is None
                            or target["expires_at"] > source["expires_at"]
                        )
                    )
                ):
                    affected["control_source_horizon_mismatch"].add(ordinal)

            if kind == "bundle":
                try:
                    bundle = RoleBundle.objects.get(pk=target["id"])
                    historical = role_bundle_provenance_is_historical(
                        bundle=bundle,
                        evaluated_at=self.at,
                    )
                except (RoleBundle.DoesNotExist, TypeError, ValueError):
                    historical = False
                if not historical:
                    affected["malformed_lineage"].add(ordinal)
            elif target["id"] in (
                self.open_grant_ids if kind == "grant" else self.open_assignment_ids
            ):
                if not self._runtime_target_is_current(
                    ordinal=ordinal,
                    kind=kind,
                    target=target,
                ):
                    affected["control_source_not_current"].add(ordinal)

        cycles, too_deep, malformed_graph = self._recursive_graph_issues(graph_edges)
        affected["lineage_cycle"].update(cycles)
        affected["lineage_depth_exceeded"].update(too_deep)
        affected["malformed_lineage"].update(malformed_graph)
        counts = {key: len(value) for key, value in affected.items()}
        counts["delegated_grant_parent_missing_issuance"] = len(
            delegated_parent_missing
        )
        counts["delegated_grant_excess_controls"] = len(delegated_excess)
        return counts

    def _runtime_target_is_current(
        self,
        *,
        ordinal: object,
        kind: str,
        target: Mapping[str, Any],
    ) -> bool:
        resolved = _resolved_target(target)
        if resolved is None:
            return False
        evaluated_at = max(self.at, target["effective_from"])
        capabilities: tuple[str, ...]
        if kind == "grant":
            capabilities = (str(target["capability_code"]),)
        else:
            bundle = self.bundles.get(target["role_bundle_id"])
            if bundle is None:
                return False
            capabilities = tuple(
                str(code) for code in bundle["capability_codes"] if code is not None
            )
            if not capabilities:
                return False
        return all(
            authority_issuance_is_current(
                issuance_ordinal=cast(int, ordinal),
                principal_id=target["principal_id"],
                capability_code=capability_code,
                target=resolved,
                requested_effective_from=target["effective_from"],
                requested_expires_at=target["expires_at"],
                evaluated_at=evaluated_at,
            )
            for capability_code in capabilities
        )

    def _recursive_graph_issues(
        self,
        edges: Mapping[object, set[object]],
    ) -> tuple[set[object], set[object], set[object]]:
        cycles: set[object] = set()
        too_deep: set[object] = set()
        malformed: set[object] = set()
        for start in self.reachable_issuances:
            stack: list[tuple[object, tuple[object, ...]]] = [(start, ())]
            while stack:
                node, path = stack.pop()
                if node in path:
                    cycles.add(start)
                    continue
                if len(path) >= MAX_AUTHORITY_LINEAGE_DEPTH:
                    too_deep.add(start)
                    continue
                if node not in self.issuances:
                    malformed.add(start)
                    continue
                next_path = (*path, node)
                stack.extend((child, next_path) for child in edges.get(node, ()))
        return cycles, too_deep, malformed


def build_authority_provenance_readiness_report(
    *,
    at: datetime | None = None,
) -> dict[str, object]:
    """Return deterministic aggregate-only ADR 0044 readiness evidence."""

    effective_at = at or timezone.now()
    graph = _AuthorityGraph(at=effective_at)
    missing, reviews = graph.missing_and_review_counts()
    blockers = {**missing, **graph.structural_blocker_counts()}
    ordered_blockers = {key: int(blockers.get(key, 0)) for key in BLOCKER_KEYS}
    ordered_reviews = {key: int(reviews.get(key, 0)) for key in REVIEW_KEYS}
    blocker_total = sum(ordered_blockers.values())
    status = "blocked" if blocker_total else "ready"
    return {
        "status": status,
        # ADR 0044 deliberately separates data reconciliation from the final
        # fail-closed cutover.  A zero-blocker graph is necessary, but it is
        # not production-ready until the completeness guards, policy switch,
        # and downgrade fence are installed by a later migration stage.
        "production_status": "blocked",
        "blocker_counts": ordered_blockers,
        "blocker_total": blocker_total,
        "review_counts": ordered_reviews,
        "known_production_gates": {
            "exact_lineage_policy_cutover": "unresolved",
            "database_completeness_guards": "unresolved",
            "provenance_write_downgrade_fence": "unresolved",
        },
    }
