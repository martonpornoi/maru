"""Provable-only ADR 0044 authority-provenance reconciliation.

The reconciler is intentionally narrower than the general readiness report.  It
may append evidence only for the code-owned initial Executive Board ceremony
and for grants whose exact ``delegated_from`` relationship already exists.  It
never chooses controls for an ordinary legacy grant, role definition, or role
assignment.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.issuance import create_delegated_grant_issuance
from maru.authorization.models import (
    AuthorityControl,
    AuthorityIssuance,
    CapabilityGrant,
    RoleAssignment,
    RoleBundle,
)
from maru.identity.models import Account
from maru.organizations.models import (
    Organization,
    OrganizationRepresentation,
    RepresentationAppointment,
)
from maru.organizations.representation import (
    EXECUTIVE_BOARD_CAPABILITIES,
    EXECUTIVE_BOARD_ROLE_CODE,
    MINIMUM_EXECUTIVE_BOARD_CONTROLLERS,
)

BACKFILL_REPORT_SCHEMA_VERSION = 1

BLOCKER_KEYS = (
    "invalid_existing_issuance",
    "invalid_executive_board_ceremony",
    "delegated_relationship_mismatch",
    "delegated_parent_issuance_missing",
    "delegated_chain_unresolvable",
)

TARGET_KEYS = (
    "executive_board_bundle",
    "executive_board_assignment",
    "delegated_grant",
)

REVIEW_KEYS = (
    "expired_or_revoked_delegated_grant_untouched",
    "ordinary_root_grant_untouched",
    "ordinary_role_bundle_untouched",
    "ordinary_role_assignment_untouched",
)

_ACTOR = AuthorityControl.Role.ACTOR
_APPROVER = AuthorityControl.Role.APPROVER
_PERSISTENT = AuthorityControl.Basis.PERSISTENT_AUTHORITY
_PLATFORM_BOOTSTRAP = AuthorityControl.Basis.PLATFORM_REPRESENTATION_BOOTSTRAP
_REPRESENTATION_ACCEPTANCE = AuthorityControl.Basis.REPRESENTATION_ACCEPTANCE
_CONTROL_COUNT = 2


class WritersStoppedAcknowledgementRequiredError(ValueError):
    """Raised when a caller requests mutation without the maintenance promise."""


@dataclass(frozen=True, slots=True)
class _BoardWrite:
    target_kind: str
    target_id: UUID
    representation_id: UUID
    actor_id: UUID
    approver_appointment_id: UUID
    evaluated_at: datetime


@dataclass(frozen=True, slots=True)
class _DelegatedWrite:
    grant_id: UUID


@dataclass(frozen=True, slots=True)
class _Plan:
    report: dict[str, object]
    board_writes: tuple[_BoardWrite, ...]
    delegated_writes: tuple[_DelegatedWrite, ...]


@dataclass(slots=True)
class _State:
    accounts: dict[UUID, dict[str, Any]]
    organizations: dict[UUID, dict[str, Any]]
    representations: dict[UUID, dict[str, Any]]
    appointments: dict[UUID, dict[str, Any]]
    grants: dict[UUID, dict[str, Any]]
    bundles: dict[UUID, dict[str, Any]]
    assignments: dict[UUID, dict[str, Any]]
    issuances: dict[int, dict[str, Any]]
    controls_by_issuance: dict[int, list[dict[str, Any]]]
    issuance_by_grant: dict[UUID, int]
    issuance_by_bundle: dict[UUID, int]
    issuance_by_assignment: dict[UUID, int]
    duplicate_issuance_ordinals: set[int]


def _ordered_counts(keys: Iterable[str], values: Mapping[str, int]) -> dict[str, int]:
    return {key: int(values.get(key, 0)) for key in keys}


def _rows_by(
    rows: Iterable[Mapping[str, Any]],
    key: str,
) -> dict[Any, dict[str, Any]]:
    return {row[key]: dict(row) for row in rows}


def _values(
    model: type[Any],
    *fields: str,
    lock: bool,
    ordering: tuple[str, ...],
) -> list[dict[str, Any]]:
    queryset = model.objects.order_by(*ordering)
    if lock:
        queryset = queryset.select_for_update()
    return [dict(row) for row in queryset.values(*fields)]


def _load_state(*, lock: bool) -> _State:
    """Load one identifier-bearing snapshot; identifiers never leave this module."""

    # Apply mode acknowledges stopped writers and takes locks in this fixed order.
    # The broad locks are deliberate: reconciliation must not mix two authority
    # graph versions, and this command is not a live-traffic operation.
    accounts = _rows_by(
        _values(
            Account,
            "id",
            "account_kind",
            "is_active",
            lock=lock,
            ordering=("id",),
        ),
        "id",
    )
    organizations = _rows_by(
        _values(
            Organization,
            "id",
            "lifecycle",
            lock=lock,
            ordering=("id",),
        ),
        "id",
    )
    representations = _rows_by(
        _values(
            OrganizationRepresentation,
            "id",
            "organization_id",
            "state",
            "activated_by_id",
            "activated_at",
            "activation_reason",
            lock=lock,
            ordering=("id",),
        ),
        "id",
    )
    appointments = _rows_by(
        _values(
            RepresentationAppointment,
            "id",
            "representation_id",
            "account_id",
            "role",
            "state",
            "responded_at",
            "activated_at",
            "ended_at",
            "role_assignment_id",
            lock=lock,
            ordering=("id",),
        ),
        "id",
    )
    grants = _rows_by(
        _values(
            CapabilityGrant,
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
            lock=lock,
            ordering=("id",),
        ),
        "id",
    )
    bundles = _rows_by(
        _values(
            RoleBundle,
            "id",
            "organization_id",
            "code",
            "name",
            "version",
            "capability_codes",
            "created_by_id",
            "approved_by_id",
            "reason",
            lock=lock,
            ordering=("id",),
        ),
        "id",
    )
    assignments = _rows_by(
        _values(
            RoleAssignment,
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
            "reason",
            lock=lock,
            ordering=("id",),
        ),
        "id",
    )
    issuance_rows = _values(
        AuthorityIssuance,
        "ordinal",
        "policy_version",
        "evaluated_at",
        "capability_grant_id",
        "role_bundle_id",
        "role_assignment_id",
        lock=lock,
        ordering=("ordinal",),
    )
    issuances = _rows_by(issuance_rows, "ordinal")
    controls = _values(
        AuthorityControl,
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
        lock=lock,
        ordering=("issuance_id", "role", "id"),
    )
    controls_by_issuance: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for control in controls:
        controls_by_issuance[int(control["issuance_id"])].append(control)
    issuance_maps: dict[str, dict[UUID, int]] = {}
    duplicate_issuance_ordinals: set[int] = set()
    for target_field in (
        "capability_grant_id",
        "role_bundle_id",
        "role_assignment_id",
    ):
        ordinals_by_target: dict[UUID, list[int]] = defaultdict(list)
        for row in issuance_rows:
            target_id = row[target_field]
            if target_id is not None:
                ordinals_by_target[target_id].append(int(row["ordinal"]))
        issuance_maps[target_field] = {
            target_id: min(ordinals)
            for target_id, ordinals in ordinals_by_target.items()
        }
        duplicate_issuance_ordinals.update(
            ordinal
            for ordinals in ordinals_by_target.values()
            if len(ordinals) > 1
            for ordinal in ordinals
        )
    return _State(
        accounts=accounts,
        organizations=organizations,
        representations=representations,
        appointments=appointments,
        grants=grants,
        bundles=bundles,
        assignments=assignments,
        issuances=issuances,
        controls_by_issuance=dict(controls_by_issuance),
        issuance_by_grant=issuance_maps["capability_grant_id"],
        issuance_by_bundle=issuance_maps["role_bundle_id"],
        issuance_by_assignment=issuance_maps["role_assignment_id"],
        duplicate_issuance_ordinals=duplicate_issuance_ordinals,
    )


def _scope(row: Mapping[str, Any]) -> tuple[Any, Any, Any, Any]:
    return (
        row["organization_id"],
        row.get("edition_id"),
        row.get("department_id"),
        row.get("resource_binding_id"),
    )


def _scope_contains(
    *,
    parent: tuple[Any, Any, Any, Any],
    child: tuple[Any, Any, Any, Any],
) -> bool:
    parent_organization, parent_edition, parent_department, parent_resource = parent
    child_organization, child_edition, child_department, child_resource = child
    return parent_organization == child_organization and (
        parent_edition is None
        or (
            parent_edition == child_edition
            and (
                parent_department is None
                or (
                    parent_department == child_department
                    and (parent_resource is None or parent_resource == child_resource)
                )
            )
        )
    )


def _delegation_relationship_valid(
    grant: Mapping[str, Any],
    state: _State,
) -> bool:
    parent_id = grant["delegated_from_id"]
    parent = state.grants.get(parent_id)
    if parent is None or parent_id == grant["id"]:
        return False
    return bool(
        grant["approved_by_id"] is None
        and parent["principal_id"] == grant["granted_by_id"]
        and parent["capability_code"] == grant["capability_code"]
        and _scope_contains(parent=_scope(parent), child=_scope(grant))
        and grant["effective_from"] >= parent["effective_from"]
        and (
            parent["expires_at"] is None
            or (
                grant["expires_at"] is not None
                and grant["expires_at"] <= parent["expires_at"]
            )
        )
    )


def _issuance_target(
    issuance: Mapping[str, Any],
    state: _State,
) -> tuple[str, dict[str, Any]] | None:
    candidates = (
        ("grant", issuance["capability_grant_id"], state.grants),
        ("bundle", issuance["role_bundle_id"], state.bundles),
        ("assignment", issuance["role_assignment_id"], state.assignments),
    )
    present = [candidate for candidate in candidates if candidate[1] is not None]
    if len(present) != 1:
        return None
    kind, target_id, records = present[0]
    target = records.get(target_id)
    return (kind, target) if target is not None else None


def _attribution(
    kind: str,
    target: Mapping[str, Any],
) -> tuple[Any, Any, Any, str]:
    if kind == "bundle":
        return (
            target["created_by_id"],
            target["approved_by_id"],
            None,
            "authorization.manage_roles",
        )
    return (
        target["granted_by_id"],
        target["approved_by_id"],
        target["principal_id"],
        (
            "authorization.grant_direct"
            if kind == "grant"
            else "authorization.manage_roles"
        ),
    )


def _is_board_target(kind: str, target: Mapping[str, Any], state: _State) -> bool:
    if kind == "bundle":
        return bool(target["code"] == EXECUTIVE_BOARD_ROLE_CODE)
    if kind != "assignment":
        return False
    bundle = state.bundles.get(target["role_bundle_id"])
    return bool(bundle is not None and bundle["code"] == EXECUTIVE_BOARD_ROLE_CODE)


def _controls_by_role(
    controls: Iterable[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]] | None:
    rows = list(controls)
    if len(rows) != _CONTROL_COUNT or {row["role"] for row in rows} != {
        _ACTOR,
        _APPROVER,
    }:
        return None
    by_role = {str(row["role"]): row for row in rows}
    return by_role if len(by_role) == _CONTROL_COUNT else None


def _metadata_and_identity_valid(
    *,
    kind: str,
    target: Mapping[str, Any],
    issuance: Mapping[str, Any],
    controls: Mapping[str, Mapping[str, Any]],
) -> bool:
    actor_id, approver_id, recipient_id, _required = _attribution(kind, target)
    actor = controls[_ACTOR]
    approver = controls[_APPROVER]
    return bool(
        issuance["policy_version"]
        and actor_id is not None
        and approver_id is not None
        and approver_id not in {actor_id, recipient_id}
        and actor["principal_id"] == actor_id
        and approver["principal_id"] == approver_id
        and actor["policy_version"] == issuance["policy_version"]
        and approver["policy_version"] == issuance["policy_version"]
        and actor["evaluated_at"] == issuance["evaluated_at"]
        and approver["evaluated_at"] == issuance["evaluated_at"]
    )


def _board_issuance_valid(
    *,
    kind: str,
    target: Mapping[str, Any],
    issuance: Mapping[str, Any],
    controls: Mapping[str, Mapping[str, Any]],
    state: _State,
) -> bool:
    actor = controls[_ACTOR]
    approver = controls[_APPROVER]
    representation = state.representations.get(actor["representation_id"])
    appointment = state.appointments.get(approver["appointment_id"])
    actor_account = state.accounts.get(actor["principal_id"])
    evaluated_at = issuance["evaluated_at"]
    if (
        actor["basis"] != _PLATFORM_BOOTSTRAP
        or actor["source_issuance_id"] is not None
        or actor["representation_id"] is None
        or actor["appointment_id"] is not None
        or approver["basis"] != _REPRESENTATION_ACCEPTANCE
        or approver["source_issuance_id"] is not None
        or approver["representation_id"] is not None
        or approver["appointment_id"] is None
        or representation is None
        or appointment is None
        or actor_account is None
    ):
        return False
    if not (
        representation["organization_id"] == target["organization_id"]
        and representation["activated_by_id"] == actor["principal_id"]
        and representation["activated_at"] == evaluated_at
        and actor_account["account_kind"] == Account.Kind.PLATFORM_ADMINISTRATOR
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
    ):
        return False
    if kind == "bundle":
        return True
    return bool(
        target["edition_id"] is None
        and target["department_id"] is None
        and target["resource_binding_id"] is None
        and target["effective_from"] == evaluated_at
        and target["expires_at"] is None
    )


def _source_target(
    source_ordinal: int,
    state: _State,
) -> tuple[str, dict[str, Any]] | None:
    source = state.issuances.get(source_ordinal)
    if source is None:
        return None
    resolved = _issuance_target(source, state)
    if resolved is None or resolved[0] not in {"grant", "assignment"}:
        return None
    return resolved


def _ordinary_control_valid(
    *,
    kind: str,
    target: Mapping[str, Any],
    issuance: Mapping[str, Any],
    control: Mapping[str, Any],
    required_capability: str,
    state: _State,
) -> bool:
    source_ordinal = control["source_issuance_id"]
    if (
        control["basis"] != _PERSISTENT
        or source_ordinal is None
        or source_ordinal >= issuance["ordinal"]
        or control["representation_id"] is not None
        or control["appointment_id"] is not None
    ):
        return False
    resolved = _source_target(int(source_ordinal), state)
    if resolved is None:
        return False
    source_kind, source = resolved
    capabilities = (
        {source["capability_code"]}
        if source_kind == "grant"
        else set(
            state.bundles.get(source["role_bundle_id"], {}).get("capability_codes", ())
        )
    )
    evaluated_at = issuance["evaluated_at"]
    target_scope = (
        (target["organization_id"], None, None, None)
        if kind == "bundle"
        else _scope(target)
    )
    if not (
        source["principal_id"] == control["principal_id"]
        and required_capability in capabilities
        and _scope_contains(parent=_scope(source), child=target_scope)
        and source["effective_from"] <= evaluated_at
        and (source["expires_at"] is None or source["expires_at"] > evaluated_at)
        and (source["revoked_at"] is None or source["revoked_at"] > evaluated_at)
    ):
        return False
    return bool(
        kind == "bundle"
        or (
            target["effective_from"] >= source["effective_from"]
            and (
                source["expires_at"] is None
                or (
                    target["expires_at"] is not None
                    and target["expires_at"] <= source["expires_at"]
                )
            )
        )
    )


def _locally_valid_existing_issuance(ordinal: int, state: _State) -> bool:
    issuance = state.issuances[ordinal]
    resolved = _issuance_target(issuance, state)
    if resolved is None or not issuance["policy_version"]:
        return False
    kind, target = resolved
    if kind == "assignment":
        bundle_ordinal = state.issuance_by_bundle.get(target["role_bundle_id"])
        if bundle_ordinal is None or bundle_ordinal >= ordinal:
            return False
    controls = state.controls_by_issuance.get(ordinal, [])
    if kind == "grant" and target["delegated_from_id"] is not None:
        parent_ordinal = state.issuance_by_grant.get(target["delegated_from_id"])
        return bool(
            not controls
            and _delegation_relationship_valid(target, state)
            and parent_ordinal is not None
            and parent_ordinal < ordinal
        )
    by_role = _controls_by_role(controls)
    if by_role is None or not _metadata_and_identity_valid(
        kind=kind,
        target=target,
        issuance=issuance,
        controls=by_role,
    ):
        return False
    if _is_board_target(kind, target, state) or any(
        control["basis"] in {_PLATFORM_BOOTSTRAP, _REPRESENTATION_ACCEPTANCE}
        for control in controls
    ):
        return _is_board_target(kind, target, state) and _board_issuance_valid(
            kind=kind,
            target=target,
            issuance=issuance,
            controls=by_role,
            state=state,
        )
    _actor_id, _approver_id, _recipient_id, required = _attribution(kind, target)
    return all(
        _ordinary_control_valid(
            kind=kind,
            target=target,
            issuance=issuance,
            control=control,
            required_capability=required,
            state=state,
        )
        for control in by_role.values()
    )


def _invalid_existing_issuances(state: _State) -> set[int]:
    invalid = set(state.duplicate_issuance_ordinals)
    invalid.update(
        ordinal
        for ordinal in state.issuances
        if not _locally_valid_existing_issuance(ordinal, state)
    )
    changed = True
    while changed:
        changed = False
        for ordinal, issuance in state.issuances.items():
            if ordinal in invalid:
                continue
            resolved = _issuance_target(issuance, state)
            if resolved is None:
                invalid.add(ordinal)
                changed = True
                continue
            kind, target = resolved
            dependencies: set[int] = set()
            if kind == "assignment":
                bundle = state.issuance_by_bundle.get(target["role_bundle_id"])
                if bundle is not None:
                    dependencies.add(bundle)
            if kind == "grant" and target["delegated_from_id"] is not None:
                parent = state.issuance_by_grant.get(target["delegated_from_id"])
                if parent is not None:
                    dependencies.add(parent)
            dependencies.update(
                int(control["source_issuance_id"])
                for control in state.controls_by_issuance.get(ordinal, ())
                if control["source_issuance_id"] is not None
            )
            if dependencies & invalid:
                invalid.add(ordinal)
                changed = True
    return invalid


def _board_evidence(  # noqa: PLR0911
    *,
    representation: Mapping[str, Any],
    bundle: Mapping[str, Any],
    state: _State,
) -> tuple[_BoardWrite, ...] | None:
    activated_at = representation["activated_at"]
    actor_id = representation["activated_by_id"]
    actor = state.accounts.get(actor_id)
    organization = state.organizations.get(representation["organization_id"])
    if not (
        representation["state"]
        in {
            OrganizationRepresentation.State.ACTIVE,
            OrganizationRepresentation.State.SUSPENDED,
        }
        and activated_at is not None
        and actor is not None
        and actor["account_kind"] == Account.Kind.PLATFORM_ADMINISTRATOR
        and organization is not None
        and organization["lifecycle"]
        in {
            Organization.Lifecycle.ACTIVE,
            Organization.Lifecycle.SUSPENDED,
            Organization.Lifecycle.CLOSED,
        }
        and (
            organization["lifecycle"] == Organization.Lifecycle.CLOSED
            or (
                representation["state"] == OrganizationRepresentation.State.ACTIVE
                and organization["lifecycle"] == Organization.Lifecycle.ACTIVE
            )
            or (
                representation["state"] == OrganizationRepresentation.State.SUSPENDED
                and organization["lifecycle"] == Organization.Lifecycle.SUSPENDED
            )
        )
        and bundle["organization_id"] == representation["organization_id"]
        and bundle["code"] == EXECUTIVE_BOARD_ROLE_CODE
        and bundle["name"] == "Executive Board"
        and bundle["version"] == 1
        and tuple(bundle["capability_codes"]) == tuple(EXECUTIVE_BOARD_CAPABILITIES)
        and bundle["created_by_id"] == actor_id
        and bundle["reason"] == representation["activation_reason"]
    ):
        return None
    controllers = sorted(
        (
            appointment
            for appointment in state.appointments.values()
            if appointment["representation_id"] == representation["id"]
            and appointment["state"]
            in {
                RepresentationAppointment.State.ACTIVE,
                RepresentationAppointment.State.ENDED,
            }
            and appointment["role_assignment_id"] is not None
        ),
        key=lambda appointment: (
            appointment["responded_at"],
            str(appointment["id"]),
        ),
    )
    if (
        len(controllers) < MINIMUM_EXECUTIVE_BOARD_CONTROLLERS
        or len({item["account_id"] for item in controllers}) != len(controllers)
        or any(
            item["role"] != RepresentationAppointment.Role.CONTROLLER
            or item["responded_at"] is None
            or item["responded_at"] > activated_at
            or item["activated_at"] != activated_at
            for item in controllers
        )
    ):
        return None
    assignment_ids = {
        assignment["id"]
        for assignment in state.assignments.values()
        if assignment["role_bundle_id"] == bundle["id"]
    }
    if assignment_ids != {item["role_assignment_id"] for item in controllers}:
        return None
    if bundle["approved_by_id"] != controllers[0]["account_id"]:
        return None
    writes = [
        _BoardWrite(
            target_kind="executive_board_bundle",
            target_id=bundle["id"],
            representation_id=representation["id"],
            actor_id=actor_id,
            approver_appointment_id=controllers[0]["id"],
            evaluated_at=activated_at,
        )
    ]
    for index, controller in enumerate(controllers):
        assignment = state.assignments.get(controller["role_assignment_id"])
        approver = controllers[(index + 1) % len(controllers)]
        if assignment is None or not (
            assignment["organization_id"] == representation["organization_id"]
            and assignment["edition_id"] is None
            and assignment["department_id"] is None
            and assignment["resource_binding_id"] is None
            and assignment["principal_id"] == controller["account_id"]
            and assignment["role_bundle_id"] == bundle["id"]
            and assignment["effective_from"] == activated_at
            and assignment["expires_at"] is None
            and assignment["granted_by_id"] == actor_id
            and assignment["approved_by_id"] == approver["account_id"]
            and assignment["reason"] == representation["activation_reason"]
        ):
            return None
        if controller["state"] == RepresentationAppointment.State.ACTIVE:
            if (
                controller["ended_at"] is not None
                or assignment["revoked_at"] is not None
            ):
                return None
        elif not (
            controller["ended_at"] is not None
            and controller["ended_at"] >= activated_at
            and assignment["revoked_at"] == controller["ended_at"]
        ):
            return None
        writes.append(
            _BoardWrite(
                target_kind="executive_board_assignment",
                target_id=assignment["id"],
                representation_id=representation["id"],
                actor_id=actor_id,
                approver_appointment_id=approver["id"],
                evaluated_at=activated_at,
            )
        )
    return tuple(writes)


def _existing_matches_board_write(
    *,
    write: _BoardWrite,
    ordinal: int,
    state: _State,
) -> bool:
    """Require the stored special controls to match the deterministic plan."""

    issuance = state.issuances.get(ordinal)
    if issuance is None or issuance["evaluated_at"] != write.evaluated_at:
        return False
    if write.target_kind == "executive_board_bundle":
        target_matches = bool(
            issuance["role_bundle_id"] == write.target_id
            and issuance["role_assignment_id"] is None
            and issuance["capability_grant_id"] is None
        )
    else:
        target_matches = bool(
            issuance["role_assignment_id"] == write.target_id
            and issuance["role_bundle_id"] is None
            and issuance["capability_grant_id"] is None
        )
    controls = _controls_by_role(state.controls_by_issuance.get(ordinal, ()))
    appointment = state.appointments.get(write.approver_appointment_id)
    if not target_matches or controls is None or appointment is None:
        return False
    actor = controls[_ACTOR]
    approver = controls[_APPROVER]
    return bool(
        actor["principal_id"] == write.actor_id
        and actor["basis"] == _PLATFORM_BOOTSTRAP
        and actor["source_issuance_id"] is None
        and actor["representation_id"] == write.representation_id
        and actor["appointment_id"] is None
        and actor["policy_version"] == issuance["policy_version"]
        and actor["evaluated_at"] == write.evaluated_at
        and approver["principal_id"] == appointment["account_id"]
        and approver["basis"] == _REPRESENTATION_ACCEPTANCE
        and approver["source_issuance_id"] is None
        and approver["representation_id"] is None
        and approver["appointment_id"] == write.approver_appointment_id
        and approver["policy_version"] == issuance["policy_version"]
        and approver["evaluated_at"] == write.evaluated_at
    )


def _plan_board(  # noqa: PLR0912
    *,
    state: _State,
    invalid_issuances: set[int],
    blockers: dict[str, int],
    planned: dict[str, int],
    preserved: dict[str, int],
) -> list[_BoardWrite]:
    board_bundles_by_organization: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    for bundle in state.bundles.values():
        if bundle["code"] == EXECUTIVE_BOARD_ROLE_CODE:
            board_bundles_by_organization[bundle["organization_id"]].append(bundle)
    representations_by_organization = {
        row["organization_id"]: row for row in state.representations.values()
    }
    writes: list[_BoardWrite] = []
    for organization_id in sorted(
        set(board_bundles_by_organization) | set(representations_by_organization),
        key=str,
    ):
        bundles = sorted(
            board_bundles_by_organization.get(organization_id, ()),
            key=lambda row: str(row["id"]),
        )
        representation = representations_by_organization.get(organization_id)
        if (
            representation is not None
            and representation["state"] == OrganizationRepresentation.State.PROVISIONING
            and not bundles
        ):
            continue
        if representation is None or len(bundles) != 1:
            blockers["invalid_executive_board_ceremony"] += 1
            continue
        bundle = bundles[0]
        evidence = _board_evidence(
            representation=representation,
            bundle=bundle,
            state=state,
        )
        if evidence is None:
            blockers["invalid_executive_board_ceremony"] += 1
            continue
        existing_by_write: list[tuple[_BoardWrite, int | None]] = []
        for write in evidence:
            existing = (
                state.issuance_by_bundle.get(write.target_id)
                if write.target_kind == "executive_board_bundle"
                else state.issuance_by_assignment.get(write.target_id)
            )
            existing_by_write.append((write, existing))
        conflict = False
        for write, existing in existing_by_write:
            if existing is None:
                continue
            if existing in invalid_issuances:
                conflict = True
            elif not _existing_matches_board_write(
                write=write,
                ordinal=existing,
                state=state,
            ):
                blockers["invalid_existing_issuance"] += 1
                conflict = True
        if conflict:
            continue
        for write, existing in existing_by_write:
            if existing is None:
                planned[write.target_kind] += 1
                writes.append(write)
            else:
                preserved[write.target_kind] += 1
    return writes


def _plan_delegated(
    *,
    state: _State,
    invalid_issuances: set[int],
    blockers: dict[str, int],
    planned: dict[str, int],
    preserved: dict[str, int],
    reviews: dict[str, int],
    at: datetime,
) -> list[_DelegatedWrite]:
    delegated = sorted(
        (
            grant
            for grant in state.grants.values()
            if grant["delegated_from_id"] is not None
        ),
        key=lambda row: str(row["id"]),
    )
    available = {
        grant_id
        for grant_id, ordinal in state.issuance_by_grant.items()
        if ordinal not in invalid_issuances
    }
    pending: dict[UUID, dict[str, Any]] = {}
    for grant in delegated:
        ordinal = state.issuance_by_grant.get(grant["id"])
        if ordinal is None and (
            grant["revoked_at"] is not None
            or (grant["expires_at"] is not None and grant["expires_at"] <= at)
        ):
            reviews["expired_or_revoked_delegated_grant_untouched"] += 1
            continue
        if not _delegation_relationship_valid(grant, state):
            blockers["delegated_relationship_mismatch"] += 1
            continue
        if ordinal is not None:
            if ordinal not in invalid_issuances:
                preserved["delegated_grant"] += 1
            continue
        pending[grant["id"]] = grant

    writes: list[_DelegatedWrite] = []
    while pending:
        ready = sorted(
            (
                grant
                for grant in pending.values()
                if grant["delegated_from_id"] in available
            ),
            key=lambda row: str(row["id"]),
        )
        if not ready:
            break
        for grant in ready:
            pending.pop(grant["id"])
            available.add(grant["id"])
            planned["delegated_grant"] += 1
            writes.append(_DelegatedWrite(grant_id=grant["id"]))

    for grant in pending.values():
        seen: set[UUID] = set()
        current = grant
        cycle = False
        while current["delegated_from_id"] in pending:
            current_id = current["id"]
            if current_id in seen:
                cycle = True
                break
            seen.add(current_id)
            current = pending[current["delegated_from_id"]]
        blockers[
            "delegated_chain_unresolvable"
            if cycle
            else "delegated_parent_issuance_missing"
        ] += 1
    return writes


def _build_plan(*, state: _State, mode: str, at: datetime) -> _Plan:
    blockers = dict.fromkeys(BLOCKER_KEYS, 0)
    planned = dict.fromkeys(TARGET_KEYS, 0)
    preserved = dict.fromkeys(TARGET_KEYS, 0)
    reviews = dict.fromkeys(REVIEW_KEYS, 0)
    invalid_issuances = _invalid_existing_issuances(state)
    blockers["invalid_existing_issuance"] = len(invalid_issuances)
    board_writes = _plan_board(
        state=state,
        invalid_issuances=invalid_issuances,
        blockers=blockers,
        planned=planned,
        preserved=preserved,
    )
    delegated_writes = _plan_delegated(
        state=state,
        invalid_issuances=invalid_issuances,
        blockers=blockers,
        planned=planned,
        preserved=preserved,
        reviews=reviews,
        at=at,
    )
    board_bundle_ids = {
        bundle["id"]
        for bundle in state.bundles.values()
        if bundle["code"] == EXECUTIVE_BOARD_ROLE_CODE
    }
    reviews["ordinary_root_grant_untouched"] = sum(
        grant["delegated_from_id"] is None
        and grant["id"] not in state.issuance_by_grant
        for grant in state.grants.values()
    )
    reviews["ordinary_role_bundle_untouched"] = sum(
        bundle["id"] not in board_bundle_ids
        and bundle["id"] not in state.issuance_by_bundle
        for bundle in state.bundles.values()
    )
    reviews["ordinary_role_assignment_untouched"] = sum(
        assignment["role_bundle_id"] not in board_bundle_ids
        and assignment["id"] not in state.issuance_by_assignment
        for assignment in state.assignments.values()
    )
    blocker_counts = _ordered_counts(BLOCKER_KEYS, blockers)
    blocker_total = sum(blocker_counts.values())
    report: dict[str, object] = {
        "schema_version": BACKFILL_REPORT_SCHEMA_VERSION,
        "mode": mode,
        "status": "blocked" if blocker_total else "ready",
        "blocker_counts": blocker_counts,
        "blocker_total": blocker_total,
        "planned_counts": _ordered_counts(TARGET_KEYS, planned),
        "preserved_counts": _ordered_counts(TARGET_KEYS, preserved),
        "applied_counts": _ordered_counts(TARGET_KEYS, {}),
        "review_counts": _ordered_counts(REVIEW_KEYS, reviews),
    }
    return _Plan(
        report=report,
        board_writes=tuple(board_writes),
        delegated_writes=tuple(delegated_writes),
    )


def _append_board_write(board_write: _BoardWrite) -> AuthorityIssuance:
    """Append one already-validated current or historical Board target."""

    target: RoleBundle | RoleAssignment
    if board_write.target_kind == "executive_board_bundle":
        target = RoleBundle.objects.get(pk=board_write.target_id)
    else:
        target = RoleAssignment.objects.get(pk=board_write.target_id)
    representation = OrganizationRepresentation.objects.get(
        pk=board_write.representation_id
    )
    actor = Account.objects.get(pk=board_write.actor_id)
    approver_appointment = RepresentationAppointment.objects.get(
        pk=board_write.approver_appointment_id
    )
    target_field = (
        "role_bundle"
        if board_write.target_kind == "executive_board_bundle"
        else "role_assignment"
    )
    issuance = AuthorityIssuance.objects.create(
        **{
            target_field: target,
            "policy_version": POLICY_VERSION,
            "evaluated_at": board_write.evaluated_at,
        }
    )
    AuthorityControl.objects.create(
        issuance=issuance,
        role=_ACTOR,
        principal=actor,
        basis=_PLATFORM_BOOTSTRAP,
        representation=representation,
        policy_version=POLICY_VERSION,
        evaluated_at=board_write.evaluated_at,
    )
    AuthorityControl.objects.create(
        issuance=issuance,
        role=_APPROVER,
        principal_id=approver_appointment.account_id,
        basis=_REPRESENTATION_ACCEPTANCE,
        appointment=approver_appointment,
        policy_version=POLICY_VERSION,
        evaluated_at=board_write.evaluated_at,
    )
    return issuance


def _apply_plan(plan: _Plan) -> dict[str, int]:
    applied = dict.fromkeys(TARGET_KEYS, 0)
    for board_write in plan.board_writes:
        _append_board_write(board_write)
        applied[board_write.target_kind] += 1
    for delegated_write in plan.delegated_writes:
        create_delegated_grant_issuance(
            grant=CapabilityGrant.objects.get(pk=delegated_write.grant_id)
        )
        applied["delegated_grant"] += 1
    return applied


def reconcile_provable_authority_provenance(
    *,
    apply: bool = False,
    acknowledge_writers_stopped: bool = False,
) -> dict[str, object]:
    """Plan or atomically apply the narrow, evidence-preserving backfill.

    The returned structure contains only stable category counts.  Target and
    evidence identifiers remain request-local and are never included in the
    report or in command errors.
    """

    if apply and not acknowledge_writers_stopped:
        raise WritersStoppedAcknowledgementRequiredError(
            "Applying provenance reconciliation requires explicit stopped-writer "
            "acknowledgement."
        )
    mode = "apply" if apply else "dry_run"
    evaluated_at = timezone.now()
    with transaction.atomic():
        plan = _build_plan(
            state=_load_state(lock=apply),
            mode=mode,
            at=evaluated_at,
        )
        if not apply or plan.report["status"] == "blocked":
            return plan.report
        applied = _apply_plan(plan)
        verification = _build_plan(
            state=_load_state(lock=False),
            mode=mode,
            at=evaluated_at,
        )
        remaining = verification.report["planned_counts"]
        if not isinstance(remaining, Mapping):
            raise TypeError(
                "Authority provenance reconciliation produced an invalid report."
            )
        if verification.report["status"] == "blocked" or any(remaining.values()):
            raise RuntimeError(
                "Authority provenance reconciliation failed closed verification."
            )
        plan.report["applied_counts"] = _ordered_counts(TARGET_KEYS, applied)
        return plan.report
