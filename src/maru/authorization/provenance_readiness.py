"""Privacy-minimized deployment readiness for ADR 0044 authority lineage.

This module deliberately reports aggregate counts only.  It is a read-only
reconciliation aid: it never chooses a likely historical source, repairs a
target, or exposes an authority, person, capability, or tenant identifier.
The catalog proof is intentionally bound to Maru's supported PostgreSQL
``public`` schema; another effective schema ahead of it is rejected before
graph data is read.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from django.conf import settings
from django.db import DatabaseError, connection
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.authorization.database_role_safety import (
    RuntimeDatabaseRoleProbeError,
    probe_runtime_database_role_safety,
)
from maru.authorization.models import (
    AUTHORITY_PROVENANCE_ACTIVATION_POLICY_VERSION,
    AUTHORITY_PROVENANCE_ACTIVE_GENERATION,
    AUTHORITY_PROVENANCE_CONTRACT_VERSION,
    AUTHORITY_PROVENANCE_INACTIVE_GENERATION,
    AuthorityControl,
    AuthorityIssuance,
    AuthorityProvenanceActivation,
    AuthorityProvenanceActivationLatch,
    CapabilityGrant,
    RoleAssignment,
    RoleBundle,
)
from maru.authorization.policy import (
    EXACT_LINEAGE_POLICY_CONTRACT_VERSION,
    EXACT_LINEAGE_POLICY_VERSION,
    ResolvedAuthorizationTarget,
    exact_lineage_policy_is_active,
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

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from datetime import datetime
    from uuid import UUID

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
_ACTIVATION_MIGRATIONS = (
    ("audit", "0005_authority_activation_evidence_guards"),
    ("audit", "0006_reserved_authority_activation_audit_guard"),
    ("authorization", "0007_authority_provenance_activation_guards"),
    ("authorization", "0008_runtime_latch_lock_helper"),
    ("authorization", "0009_runtime_executable_function_contract"),
    ("authorization", "0010_retired_department_authority_guards"),
    ("authorization", "0011_registration_profile_extension_capabilities"),
    ("organizations", "0013_runtime_executable_function_hardening"),
    ("workforce", "0005_runtime_executable_function_hardening"),
    ("workforce", "0006_edition_structure_schema"),
    ("workforce", "0007_structure_write_integrity"),
    ("workforce", "0008_department_fk_contract_successor"),
    ("workforce", "0009_reconcile_fictional_structure_template"),
)
_ACTIVATION_AUDIT_INDEX = "authorization_provenance_activation_audit_unique"
_SUPPORTED_DATABASE_SCHEMA = "public"
_SUPPORTED_POSTGRESQL_SERVER_MAJOR = 17
_ACTIVATION_AUDIT_INDEX_PREDICATES = frozenset(
    {
        "operation = 'authorization.authority_provenance.activate'::text",
        "operation::text = 'authorization.authority_provenance.activate'::text",
        "(operation)::text = 'authorization.authority_provenance.activate'::text",
        "((operation)::text = 'authorization.authority_provenance.activate'::text)",
    }
)
_GATE_UNRESOLVED = "unresolved"
_GATE_RESOLVED = "resolved"
_PRODUCTION_GATE_KEYS = (
    "postgresql_server_major",
    "runtime_database_role",
    "activation_marker",
    "exact_lineage_policy_cutover",
    "database_completeness_guards",
    "provenance_write_downgrade_fence",
)


@dataclass(frozen=True, slots=True)
class _TriggerContract:
    name: str
    table: str
    function: str
    trigger_type: int
    deferrable: bool = False
    initially_deferred: bool = False
    columns: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _CatalogState:
    server_version_supported: bool
    marker_table_installed: bool
    latch_table_installed: bool
    migration_applied: bool
    audit_index_installed: bool
    guards_installed: bool
    downgrade_fence_installed: bool


@dataclass(frozen=True, slots=True)
class _CutoverState:
    server_version_supported: bool
    marker_absent: bool
    marker_valid: bool
    policy_contract_installed: bool
    policy_active: bool
    guards_installed: bool
    downgrade_fence_installed: bool


_ROW_AFTER_INSERT = 1 | 4
_ROW_AFTER_UPDATE = 1 | 16
_ROW_AFTER_INSERT_UPDATE = 1 | 4 | 16
_ROW_AFTER_INSERT_UPDATE_DELETE = 1 | 4 | 8 | 16
_ROW_BEFORE_INSERT = 1 | 2 | 4
_ROW_BEFORE_UPDATE = 1 | 2 | 16
_ROW_BEFORE_DELETE = 1 | 2 | 8
_ROW_BEFORE_INSERT_UPDATE = 1 | 2 | 4 | 16
_ROW_BEFORE_UPDATE_DELETE = 1 | 2 | 8 | 16
_ROW_BEFORE_INSERT_UPDATE_DELETE = 1 | 2 | 4 | 8 | 16
_STATEMENT_AFTER_TRUNCATE = 32
_STATEMENT_BEFORE_INSERT = 2 | 4
_STATEMENT_BEFORE_UPDATE = 2 | 16
_STATEMENT_BEFORE_INSERT_UPDATE = 2 | 4 | 16
_STATEMENT_BEFORE_UPDATE_DELETE = 2 | 8 | 16
_STATEMENT_BEFORE_INSERT_UPDATE_DELETE = 2 | 4 | 8 | 16
_STATEMENT_BEFORE_INSERT_UPDATE_DELETE_TRUNCATE = 2 | 4 | 8 | 16 | 32
_STATEMENT_BEFORE_TRUNCATE = 2 | 32

_TRIGGER_CONTRACTS = (
    _TriggerContract(
        "authorization_capability_grant_guard",
        "authorization_capabilitygrant",
        "maru_validate_capability_grant()",
        _ROW_BEFORE_INSERT_UPDATE,
    ),
    _TriggerContract(
        "authorization_capability_grant_no_delete",
        "authorization_capabilitygrant",
        "maru_prevent_authority_record_delete()",
        _ROW_BEFORE_DELETE,
    ),
    _TriggerContract(
        "authorization_role_assignment_guard",
        "authorization_roleassignment",
        "maru_validate_role_assignment()",
        _ROW_BEFORE_INSERT_UPDATE,
    ),
    _TriggerContract(
        "authorization_role_assignment_no_delete",
        "authorization_roleassignment",
        "maru_prevent_authority_record_delete()",
        _ROW_BEFORE_DELETE,
    ),
    _TriggerContract(
        "authorization_role_bundle_catalog_guard",
        "authorization_rolebundle",
        "maru_validate_role_bundle_catalog()",
        _ROW_BEFORE_INSERT,
    ),
    _TriggerContract(
        "authorization_role_bundle_immutable",
        "authorization_rolebundle",
        "maru_prevent_role_bundle_mutation()",
        _ROW_BEFORE_UPDATE_DELETE,
    ),
    _TriggerContract(
        "authorization_scoped_resource_binding_guard",
        "authorization_scopedresourcebinding",
        "maru_validate_scoped_resource_binding()",
        _ROW_BEFORE_INSERT_UPDATE,
    ),
    _TriggerContract(
        "authorization_scoped_resource_binding_immutable",
        "authorization_scopedresourcebinding",
        "maru_prevent_scoped_resource_binding_mutation()",
        _ROW_BEFORE_UPDATE_DELETE,
    ),
    _TriggerContract(
        "authorization_retired_binding_guard",
        "authorization_scopedresourcebinding",
        "maru_reject_retired_authority_target()",
        _ROW_BEFORE_INSERT,
    ),
    _TriggerContract(
        "authorization_retired_capability_guard",
        "authorization_capabilitygrant",
        "maru_reject_retired_authority_target()",
        _ROW_BEFORE_INSERT_UPDATE,
    ),
    _TriggerContract(
        "authorization_retired_role_guard",
        "authorization_roleassignment",
        "maru_reject_retired_authority_target()",
        _ROW_BEFORE_INSERT_UPDATE,
    ),
    _TriggerContract(
        "authorization_retired_department_authority_guard",
        "workforce_department",
        "maru_guard_department_retirement_authority()",
        _ROW_BEFORE_UPDATE,
        columns=("retired_at",),
    ),
    _TriggerContract(
        "authorization_retired_binding_writer_lock",
        "authorization_scopedresourcebinding",
        "maru_lock_retired_department_authority_writer()",
        _STATEMENT_BEFORE_INSERT,
    ),
    _TriggerContract(
        "authorization_retired_capability_writer_lock",
        "authorization_capabilitygrant",
        "maru_lock_retired_department_authority_writer()",
        _STATEMENT_BEFORE_INSERT_UPDATE,
    ),
    _TriggerContract(
        "authorization_retired_role_writer_lock",
        "authorization_roleassignment",
        "maru_lock_retired_department_authority_writer()",
        _STATEMENT_BEFORE_INSERT_UPDATE,
    ),
    _TriggerContract(
        "authorization_retired_department_writer_lock",
        "workforce_department",
        "maru_lock_retired_department_authority_writer()",
        _STATEMENT_BEFORE_UPDATE,
        columns=("retired_at",),
    ),
    _TriggerContract(
        "authorization_authority_issuance_insert_guard",
        "authorization_authorityissuance",
        "maru_validate_authority_issuance_insert()",
        _ROW_BEFORE_INSERT,
    ),
    _TriggerContract(
        "authorization_authority_issuance_immutable",
        "authorization_authorityissuance",
        "maru_prevent_authority_issuance_mutation()",
        _ROW_BEFORE_UPDATE_DELETE,
    ),
    _TriggerContract(
        "authorization_authority_control_insert_guard",
        "authorization_authoritycontrol",
        "maru_validate_authority_control_insert()",
        _ROW_BEFORE_INSERT,
    ),
    _TriggerContract(
        "authorization_authority_control_immutable",
        "authorization_authoritycontrol",
        "maru_prevent_authority_control_mutation()",
        _ROW_BEFORE_UPDATE_DELETE,
    ),
    _TriggerContract(
        "audit_event_append_only",
        "audit_auditevent",
        "maru_guard_audit_event()",
        _ROW_BEFORE_INSERT_UPDATE_DELETE,
    ),
    _TriggerContract(
        "authorization_capability_grant_provenance_lock",
        "authorization_capabilitygrant",
        "maru_lock_authority_provenance_writer()",
        _STATEMENT_BEFORE_INSERT_UPDATE_DELETE,
    ),
    _TriggerContract(
        "authorization_role_bundle_provenance_lock",
        "authorization_rolebundle",
        "maru_lock_authority_provenance_writer()",
        _STATEMENT_BEFORE_INSERT_UPDATE_DELETE,
    ),
    _TriggerContract(
        "authorization_role_assignment_provenance_lock",
        "authorization_roleassignment",
        "maru_lock_authority_provenance_writer()",
        _STATEMENT_BEFORE_INSERT_UPDATE_DELETE,
    ),
    _TriggerContract(
        "authorization_authority_issuance_provenance_lock",
        "authorization_authorityissuance",
        "maru_lock_authority_provenance_writer()",
        _STATEMENT_BEFORE_INSERT,
    ),
    _TriggerContract(
        "authorization_authority_control_provenance_lock",
        "authorization_authoritycontrol",
        "maru_lock_authority_provenance_writer()",
        _STATEMENT_BEFORE_INSERT,
    ),
    _TriggerContract(
        "authorization_identity_account_provenance_lock",
        "identity_account",
        "maru_lock_authority_provenance_writer()",
        _STATEMENT_BEFORE_UPDATE_DELETE,
    ),
    _TriggerContract(
        "authorization_organization_provenance_lock",
        "organizations_organization",
        "maru_lock_authority_provenance_writer()",
        _STATEMENT_BEFORE_UPDATE_DELETE,
    ),
    _TriggerContract(
        "authorization_membership_provenance_lock",
        "organizations_organizationmembership",
        "maru_lock_authority_provenance_writer()",
        _STATEMENT_BEFORE_INSERT_UPDATE_DELETE,
    ),
    _TriggerContract(
        "authorization_representation_provenance_lock",
        "organizations_organizationrepresentation",
        "maru_lock_authority_provenance_writer()",
        _STATEMENT_BEFORE_INSERT_UPDATE_DELETE,
    ),
    _TriggerContract(
        "authorization_appointment_provenance_lock",
        "organizations_representationappointment",
        "maru_lock_authority_provenance_writer()",
        _STATEMENT_BEFORE_INSERT_UPDATE_DELETE,
    ),
    _TriggerContract(
        "authorization_event_edition_provenance_lock",
        "events_eventedition",
        "maru_lock_authority_provenance_writer()",
        _STATEMENT_BEFORE_UPDATE_DELETE,
    ),
    _TriggerContract(
        "authorization_department_provenance_lock",
        "workforce_department",
        "maru_lock_authority_provenance_writer()",
        _STATEMENT_BEFORE_UPDATE_DELETE,
    ),
    _TriggerContract(
        "authorization_resource_binding_provenance_lock",
        "authorization_scopedresourcebinding",
        "maru_lock_authority_provenance_writer()",
        _STATEMENT_BEFORE_INSERT_UPDATE_DELETE,
    ),
    _TriggerContract(
        "authorization_provenance_latch_guard",
        "authorization_provenanceactivationlatch",
        "maru_guard_authority_provenance_latch()",
        _ROW_BEFORE_INSERT_UPDATE_DELETE,
    ),
    _TriggerContract(
        "authorization_provenance_activation_guard",
        "authorization_authorityprovenanceactivation",
        "maru_guard_authority_provenance_activation()",
        _ROW_BEFORE_INSERT_UPDATE_DELETE,
    ),
    _TriggerContract(
        "authorization_capability_grant_provenance_complete",
        "authorization_capabilitygrant",
        "maru_deferred_validate_authority_grant()",
        _ROW_AFTER_INSERT,
        deferrable=True,
        initially_deferred=True,
    ),
    _TriggerContract(
        "authorization_role_bundle_provenance_complete",
        "authorization_rolebundle",
        "maru_deferred_validate_authority_bundle()",
        _ROW_AFTER_INSERT,
        deferrable=True,
        initially_deferred=True,
    ),
    _TriggerContract(
        "authorization_role_assignment_provenance_complete",
        "authorization_roleassignment",
        "maru_deferred_validate_authority_assignment()",
        _ROW_AFTER_INSERT,
        deferrable=True,
        initially_deferred=True,
    ),
    _TriggerContract(
        "authorization_authority_issuance_complete",
        "authorization_authorityissuance",
        "maru_deferred_validate_authority_issuance()",
        _ROW_AFTER_INSERT,
        deferrable=True,
        initially_deferred=True,
    ),
    _TriggerContract(
        "authorization_authority_control_complete",
        "authorization_authoritycontrol",
        "maru_deferred_validate_authority_control()",
        _ROW_AFTER_INSERT,
        deferrable=True,
        initially_deferred=True,
    ),
    _TriggerContract(
        "authorization_provenance_activation_complete",
        "authorization_authorityprovenanceactivation",
        "maru_deferred_validate_provenance_activation()",
        _ROW_AFTER_INSERT,
        deferrable=True,
        initially_deferred=True,
    ),
    _TriggerContract(
        "authorization_provenance_latch_complete",
        "authorization_provenanceactivationlatch",
        "maru_deferred_validate_provenance_latch()",
        _ROW_AFTER_UPDATE,
        deferrable=True,
        initially_deferred=True,
    ),
    _TriggerContract(
        "authorization_capability_grant_provenance_no_truncate",
        "authorization_capabilitygrant",
        "maru_prevent_authority_provenance_truncate()",
        _STATEMENT_BEFORE_TRUNCATE,
    ),
    _TriggerContract(
        "authorization_role_bundle_provenance_no_truncate",
        "authorization_rolebundle",
        "maru_prevent_authority_provenance_truncate()",
        _STATEMENT_BEFORE_TRUNCATE,
    ),
    _TriggerContract(
        "authorization_role_assignment_provenance_no_truncate",
        "authorization_roleassignment",
        "maru_prevent_authority_provenance_truncate()",
        _STATEMENT_BEFORE_TRUNCATE,
    ),
    _TriggerContract(
        "authorization_authority_issuance_provenance_no_truncate",
        "authorization_authorityissuance",
        "maru_prevent_authority_provenance_truncate()",
        _STATEMENT_BEFORE_TRUNCATE,
    ),
    _TriggerContract(
        "authorization_authority_control_provenance_no_truncate",
        "authorization_authoritycontrol",
        "maru_prevent_authority_provenance_truncate()",
        _STATEMENT_BEFORE_TRUNCATE,
    ),
    _TriggerContract(
        "authorization_provenance_activation_no_truncate",
        "authorization_authorityprovenanceactivation",
        "maru_prevent_authority_provenance_truncate()",
        _STATEMENT_BEFORE_TRUNCATE,
    ),
    _TriggerContract(
        "authorization_provenance_latch_no_truncate",
        "authorization_provenanceactivationlatch",
        "maru_prevent_authority_provenance_truncate()",
        _STATEMENT_BEFORE_TRUNCATE,
    ),
    _TriggerContract(
        "authorization_activation_audit_provenance_no_truncate",
        "audit_auditevent",
        "maru_prevent_audit_event_truncate()",
        _STATEMENT_BEFORE_TRUNCATE,
    ),
    _TriggerContract(
        "authorization_activation_audit_reserved_guard",
        "audit_auditevent",
        "maru_guard_authority_provenance_activation_audit()",
        _ROW_BEFORE_INSERT,
    ),
    _TriggerContract(
        "authorization_provenance_latch_reseed",
        "authorization_provenanceactivationlatch",
        "maru_reseed_authority_provenance_latch()",
        _STATEMENT_AFTER_TRUNCATE,
    ),
    _TriggerContract(
        "organizations_representation_membership_provenance",
        "organizations_organizationrepresentation",
        "maru_deferred_validate_board_membership_from_representation()",
        _ROW_AFTER_INSERT_UPDATE_DELETE,
        deferrable=True,
        initially_deferred=True,
    ),
    _TriggerContract(
        "organizations_appointment_membership_provenance",
        "organizations_representationappointment",
        "maru_deferred_validate_board_membership_from_appointment()",
        _ROW_AFTER_INSERT_UPDATE_DELETE,
        deferrable=True,
        initially_deferred=True,
    ),
    _TriggerContract(
        "organizations_membership_board_provenance",
        "organizations_organizationmembership",
        "maru_deferred_validate_board_membership()",
        _ROW_AFTER_INSERT_UPDATE_DELETE,
        deferrable=True,
        initially_deferred=True,
    ),
    _TriggerContract(
        "organizations_representation_deferred_integrity",
        "organizations_organizationrepresentation",
        "maru_deferred_validate_representation()",
        _ROW_AFTER_INSERT_UPDATE_DELETE,
        deferrable=True,
        initially_deferred=True,
    ),
    _TriggerContract(
        "organizations_appointment_deferred_integrity",
        "organizations_representationappointment",
        "maru_deferred_validate_appointment()",
        _ROW_AFTER_INSERT_UPDATE_DELETE,
        deferrable=True,
        initially_deferred=True,
    ),
    _TriggerContract(
        "authorization_role_assignment_deferred_board_integrity",
        "authorization_roleassignment",
        "maru_deferred_validate_role_assignment()",
        _ROW_AFTER_INSERT_UPDATE_DELETE,
        deferrable=True,
        initially_deferred=True,
    ),
    _TriggerContract(
        "authorization_role_bundle_deferred_board_integrity",
        "authorization_rolebundle",
        "maru_deferred_validate_role_bundle()",
        _ROW_AFTER_INSERT_UPDATE_DELETE,
        deferrable=True,
        initially_deferred=True,
    ),
    _TriggerContract(
        "organizations_membership_deferred_board_integrity",
        "organizations_organizationmembership",
        "maru_deferred_validate_membership()",
        _ROW_AFTER_INSERT_UPDATE_DELETE,
        deferrable=True,
        initially_deferred=True,
    ),
    _TriggerContract(
        "identity_account_deferred_board_integrity",
        "identity_account",
        "maru_deferred_validate_board_account()",
        _ROW_AFTER_UPDATE,
        deferrable=True,
        initially_deferred=True,
        columns=("is_active", "email_verified_at", "account_kind"),
    ),
    _TriggerContract(
        "organizations_parent_deferred_board_integrity",
        "organizations_organization",
        "maru_deferred_validate_board_organization()",
        _ROW_AFTER_UPDATE,
        deferrable=True,
        initially_deferred=True,
        columns=("lifecycle",),
    ),
    _TriggerContract(
        "workforce_position_guard",
        "workforce_position",
        "maru_guard_workforce_position()",
        _ROW_BEFORE_INSERT_UPDATE_DELETE,
    ),
    _TriggerContract(
        "workforce_assignment_guard",
        "workforce_positionassignment",
        "maru_guard_workforce_assignment()",
        _ROW_BEFORE_INSERT_UPDATE_DELETE,
    ),
    _TriggerContract(
        "aa_workforce_page9_department_barrier",
        "workforce_department",
        "maru_workforce_page9_writer_barrier()",
        _STATEMENT_BEFORE_INSERT_UPDATE_DELETE_TRUNCATE,
    ),
    _TriggerContract(
        "aa_workforce_page9_control_barrier",
        "workforce_editionstructurecontrol",
        "maru_workforce_page9_writer_barrier()",
        _STATEMENT_BEFORE_INSERT_UPDATE_DELETE_TRUNCATE,
    ),
    _TriggerContract(
        "aa_workforce_page9_receipt_barrier",
        "workforce_editionstructurecommandreceipt",
        "maru_workforce_page9_writer_barrier()",
        _STATEMENT_BEFORE_INSERT_UPDATE_DELETE_TRUNCATE,
    ),
    _TriggerContract(
        "aa_workforce_page9_position_barrier",
        "workforce_position",
        "maru_workforce_page9_writer_barrier()",
        _STATEMENT_BEFORE_INSERT_UPDATE_DELETE_TRUNCATE,
    ),
    _TriggerContract(
        "aa_workforce_page9_assignment_barrier",
        "workforce_positionassignment",
        "maru_workforce_page9_writer_barrier()",
        _STATEMENT_BEFORE_INSERT_UPDATE_DELETE_TRUNCATE,
    ),
    _TriggerContract(
        "aa_workforce_page9_binding_barrier",
        "authorization_scopedresourcebinding",
        "maru_workforce_page9_writer_barrier()",
        _STATEMENT_BEFORE_INSERT_UPDATE_DELETE_TRUNCATE,
    ),
    _TriggerContract(
        "aa_workforce_page9_capability_barrier",
        "authorization_capabilitygrant",
        "maru_workforce_page9_writer_barrier()",
        _STATEMENT_BEFORE_INSERT_UPDATE_DELETE_TRUNCATE,
    ),
    _TriggerContract(
        "aa_workforce_page9_role_barrier",
        "authorization_roleassignment",
        "maru_workforce_page9_writer_barrier()",
        _STATEMENT_BEFORE_INSERT_UPDATE_DELETE_TRUNCATE,
    ),
    _TriggerContract(
        "ab_workforce_page9_department_scope",
        "workforce_department",
        "maru_workforce_page9_scope_mutex()",
        _ROW_BEFORE_INSERT_UPDATE_DELETE,
    ),
    _TriggerContract(
        "ab_workforce_page9_control_scope",
        "workforce_editionstructurecontrol",
        "maru_workforce_page9_scope_mutex()",
        _ROW_BEFORE_INSERT_UPDATE_DELETE,
    ),
    _TriggerContract(
        "ab_workforce_page9_receipt_scope",
        "workforce_editionstructurecommandreceipt",
        "maru_workforce_page9_scope_mutex()",
        _ROW_BEFORE_INSERT_UPDATE_DELETE,
    ),
    _TriggerContract(
        "ab_workforce_page9_position_scope",
        "workforce_position",
        "maru_workforce_page9_scope_mutex()",
        _ROW_BEFORE_INSERT_UPDATE_DELETE,
    ),
    _TriggerContract(
        "ab_workforce_page9_assignment_scope",
        "workforce_positionassignment",
        "maru_workforce_page9_scope_mutex()",
        _ROW_BEFORE_INSERT_UPDATE_DELETE,
    ),
    _TriggerContract(
        "ab_workforce_page9_binding_scope",
        "authorization_scopedresourcebinding",
        "maru_workforce_page9_scope_mutex()",
        _ROW_BEFORE_INSERT_UPDATE_DELETE,
    ),
    _TriggerContract(
        "ab_workforce_page9_capability_scope",
        "authorization_capabilitygrant",
        "maru_workforce_page9_scope_mutex()",
        _ROW_BEFORE_INSERT_UPDATE_DELETE,
    ),
    _TriggerContract(
        "ab_workforce_page9_role_scope",
        "authorization_roleassignment",
        "maru_workforce_page9_scope_mutex()",
        _ROW_BEFORE_INSERT_UPDATE_DELETE,
    ),
    _TriggerContract(
        "ac_workforce_page9_control_guard",
        "workforce_editionstructurecontrol",
        "maru_validate_edition_structure_control()",
        _ROW_BEFORE_INSERT_UPDATE,
    ),
    _TriggerContract(
        "ac_workforce_page9_control_no_delete",
        "workforce_editionstructurecontrol",
        "maru_prevent_edition_structure_control_mutation()",
        _ROW_BEFORE_DELETE,
    ),
    _TriggerContract(
        "ac_workforce_page9_control_no_truncate",
        "workforce_editionstructurecontrol",
        "maru_prevent_edition_structure_control_mutation()",
        _STATEMENT_BEFORE_TRUNCATE,
    ),
    _TriggerContract(
        "ac_workforce_page9_receipt_guard",
        "workforce_editionstructurecommandreceipt",
        "maru_validate_edition_structure_receipt()",
        _ROW_BEFORE_INSERT,
    ),
    _TriggerContract(
        "ac_workforce_page9_receipt_immutable",
        "workforce_editionstructurecommandreceipt",
        "maru_prevent_edition_structure_receipt_mutation()",
        _ROW_BEFORE_UPDATE_DELETE,
    ),
    _TriggerContract(
        "ac_workforce_page9_receipt_no_truncate",
        "workforce_editionstructurecommandreceipt",
        "maru_prevent_edition_structure_receipt_mutation()",
        _STATEMENT_BEFORE_TRUNCATE,
    ),
    _TriggerContract(
        "ac_workforce_page9_department_guard",
        "workforce_department",
        "maru_validate_department_structure_write()",
        _ROW_BEFORE_INSERT_UPDATE_DELETE,
    ),
    _TriggerContract(
        "ac_workforce_page9_department_no_truncate",
        "workforce_department",
        "maru_prevent_department_structure_truncate()",
        _STATEMENT_BEFORE_TRUNCATE,
    ),
    _TriggerContract(
        "ac_workforce_page9_position_retired_guard",
        "workforce_position",
        "maru_guard_position_retired_department()",
        _ROW_BEFORE_INSERT_UPDATE,
        columns=("department_id", "organization_id", "edition_id", "status"),
    ),
    _TriggerContract(
        "ac_workforce_page9_assignment_retired_guard",
        "workforce_positionassignment",
        "maru_guard_assignment_retired_department()",
        _ROW_BEFORE_INSERT_UPDATE,
        columns=("position_id", "organization_id", "edition_id", "status"),
    ),
    _TriggerContract(
        "workforce_page9_control_evidence",
        "workforce_editionstructurecontrol",
        "maru_assert_edition_structure_control_evidence()",
        _ROW_AFTER_INSERT_UPDATE,
        deferrable=True,
        initially_deferred=True,
    ),
    _TriggerContract(
        "workforce_page9_department_evidence",
        "workforce_department",
        "maru_assert_department_structure_evidence()",
        _ROW_AFTER_INSERT_UPDATE_DELETE,
        deferrable=True,
        initially_deferred=True,
    ),
)

_CORE_FUNCTIONS = (
    "maru_assert_active_board_membership_provenance(uuid)",
    "maru_assert_active_executive_board(uuid)",
    "maru_assert_active_executive_board_v0009(uuid)",
    ("maru_workforce_role_evidence_matches_position(uuid,uuid,uuid,uuid,uuid,uuid)"),
    "maru_deferred_validate_board_membership_from_representation()",
    "maru_deferred_validate_board_membership_from_appointment()",
    "maru_deferred_validate_board_membership()",
    "maru_deferred_validate_representation()",
    "maru_deferred_validate_appointment()",
    "maru_deferred_validate_role_assignment()",
    "maru_deferred_validate_role_bundle()",
    "maru_deferred_validate_membership()",
    "maru_deferred_validate_board_account()",
    "maru_deferred_validate_board_organization()",
    "maru_guard_workforce_position()",
    "maru_guard_workforce_assignment()",
    "maru_authorization_capability_min_scope(text)",
    "maru_authorization_scope_rank(uuid,uuid,uuid)",
    "maru_authorization_scope_contains(uuid,uuid,uuid,uuid,uuid,uuid,uuid,uuid)",
    "maru_validate_capability_grant()",
    "maru_prevent_authority_record_delete()",
    "maru_validate_role_assignment()",
    "maru_validate_role_bundle_catalog()",
    "maru_prevent_role_bundle_mutation()",
    "maru_validate_scoped_resource_binding()",
    "maru_prevent_scoped_resource_binding_mutation()",
    "maru_reject_retired_authority_target()",
    "maru_guard_department_retirement_authority()",
    "maru_lock_retired_department_authority_writer()",
    "maru_validate_authority_issuance_insert()",
    "maru_prevent_authority_issuance_mutation()",
    "maru_validate_authority_control_insert()",
    "maru_prevent_authority_control_mutation()",
    "maru_guard_audit_event()",
    "maru_guard_authority_provenance_activation_audit()",
    "maru_audit_test_reset_allowed()",
    "maru_prevent_audit_event_truncate()",
    "maru_authority_provenance_test_reset_allowed()",
    "maru_authority_provenance_is_active()",
    "maru_lock_authority_provenance_latch()",
    "maru_lock_authority_provenance_writer()",
    "maru_guard_authority_provenance_latch()",
    "maru_guard_authority_provenance_activation()",
    "maru_prevent_authority_provenance_truncate()",
    "maru_reseed_authority_provenance_latch()",
    "maru_authority_scope_is_current_v1(uuid,uuid,uuid,uuid)",
    "maru_authority_scope_contains_v1(uuid,uuid,uuid,uuid,uuid,uuid,uuid,uuid)",
    "maru_assert_authority_issuance_complete_internal(bigint,bigint[],integer)",
    "maru_assert_authority_issuance_complete(bigint)",
    "maru_assert_authority_target_complete(character varying,uuid)",
    "maru_authority_bundle_historical_v1(uuid,timestamptz,uuid,bigint[],integer)",
    (
        "maru_authority_issuance_valid_v1(bigint,uuid,character varying,uuid,uuid,"
        "uuid,uuid,timestamptz,timestamptz,timestamptz,boolean,boolean,bigint[],"
        "integer)"
    ),
    "maru_assert_authority_provenance_activation()",
    "maru_deferred_validate_authority_grant()",
    "maru_deferred_validate_authority_bundle()",
    "maru_deferred_validate_authority_assignment()",
    "maru_deferred_validate_authority_issuance()",
    "maru_deferred_validate_authority_control()",
    "maru_deferred_validate_provenance_activation()",
    "maru_deferred_validate_provenance_latch()",
    "maru_workforce_page9_writer_barrier()",
    "maru_workforce_page9_try_scope_mutex(bigint)",
    "maru_workforce_page9_scope_mutex()",
    "maru_validate_edition_structure_control()",
    "maru_assert_edition_structure_control_evidence()",
    "maru_prevent_edition_structure_control_mutation()",
    "maru_validate_edition_structure_receipt()",
    "maru_prevent_edition_structure_receipt_mutation()",
    "maru_workforce_department_fk_contract_is_current()",
    "maru_validate_department_structure_write()",
    "maru_assert_department_structure_evidence()",
    "maru_prevent_department_structure_truncate()",
    "maru_guard_position_retired_department()",
    "maru_guard_assignment_retired_department()",
)

_FUNCTION_DEFINITION_SHA256 = {
    "maru_lock_retired_department_authority_writer()": (
        "159e4167b0d335bd0733ca60bc9bfdf6a5bb4b31c527b590152a7f584818d2fc"
    ),
    "maru_guard_department_retirement_authority()": (
        "32786c0653be2c3cce55e3fba2f6e6630e282355e4ceac601133496fa40b13e3"
    ),
    "maru_reject_retired_authority_target()": (
        "3f48371907ea1a45e56bbebf69a92f695fa27dcf95032d55e39afdd6f4158a15"
    ),
    "maru_assert_active_board_membership_provenance(uuid)": (
        "b585585ccd82abf19501694426c707bb641526115aa87b5bb12c9cfb4fbf93e0"
    ),
    "maru_assert_active_executive_board(uuid)": (
        "75a8dffee39937aff7be7ecc5477ca55391aea9851c97ef506d25feacb5b95ab"
    ),
    "maru_assert_active_executive_board_v0009(uuid)": (
        "40715e8c46e578175cc095c4ea912396e9243d20a00d63ff83bb108e815be482"
    ),
    (
        "maru_workforce_role_evidence_matches_position(uuid,uuid,uuid,uuid,uuid,uuid)"
    ): "cfa63e39f924a09176eda1d03103f39d793ea1601e1fd193bce08f55f9dae5cd",
    "maru_deferred_validate_board_membership_from_representation()": (
        "ea5db7867bc509bead453f3789556d32074bea18e1cf53df501b8c700770177f"
    ),
    "maru_deferred_validate_board_membership_from_appointment()": (
        "322f1472e1718a9e8a7550dcab47612e78126508cc1418ef415bf0a0bf3b8f28"
    ),
    "maru_deferred_validate_board_membership()": (
        "e98fafe853659f41868c9aba6c3837166537e9c21290920269048b367ef048fa"
    ),
    "maru_deferred_validate_representation()": (
        "2eafc2cee9b36f5cf95db607c122af61560d090daa7cb8ef52165b03991038a8"
    ),
    "maru_deferred_validate_appointment()": (
        "04ca3d32b7e277ecc8e6b385b12d77268c1aa8afc75b5bd9ce8af2f793ebde61"
    ),
    "maru_deferred_validate_role_assignment()": (
        "e5a4118f50a8482902b0e8a9a2d6e608a56a19f6bd3845e09baf0c248f9dcd7d"
    ),
    "maru_deferred_validate_role_bundle()": (
        "4b09b43b7a1852efcfbd34534c2344c4f26dd346e5cad60b8b6d2736c55a1052"
    ),
    "maru_deferred_validate_membership()": (
        "59ca335c5c3d83e35aeccc45877745b022af3528d3921838a5ce516b50f12c8a"
    ),
    "maru_deferred_validate_board_account()": (
        "e7fd618cf206f6cc6b025f9dadc566a864fce609c7d246ed583b067cbb3ecbcc"
    ),
    "maru_deferred_validate_board_organization()": (
        "16aa2c2b9919a6f142df23889df69c57788fad5ee15d2655bcc61d87baa6efc7"
    ),
    "maru_guard_workforce_position()": (
        "1dda9acafc97a1c2e682d5cd75127cde2064022bfbfc686677140ac1ec6baad6"
    ),
    "maru_guard_workforce_assignment()": (
        "49970385f303dbce1c2f3134a06dfdae94db6a306582d7a8bb225e6ad6bb2eca"
    ),
    "maru_authorization_capability_min_scope(text)": (
        "d3b1413dbc598953038ba3acfa8c6339eb0a0b75f143b3d5cabf9e8c00fd581e"
    ),
    "maru_authorization_scope_contains(uuid,uuid,uuid,uuid,uuid,uuid,uuid,uuid)": (
        "093a2f3a81a16d7a09bc782c23711aa4b108274ee7a9baf8fa955e52d82cc481"
    ),
    "maru_authorization_scope_rank(uuid,uuid,uuid)": (
        "bf12c6786fb67ea0610d0ecff7f628288d43431c46650eef1d17d11c30c31919"
    ),
    "maru_assert_authority_issuance_complete(bigint)": (
        "17766670063a235c5c45dffd4bbf8c1339e434dd5056bc2ae0628825c07f3375"
    ),
    "maru_assert_authority_issuance_complete_internal(bigint,bigint[],integer)": (
        "e094e76364a1a24f204f858f8b7e50f5112b3010a6681070edbe20f0b96c7963"
    ),
    "maru_assert_authority_provenance_activation()": (
        "1677e1c5de59ca5e884ffbc0bba0036e656900962caaad0375d1569cda6bf779"
    ),
    "maru_assert_authority_target_complete(character varying,uuid)": (
        "3d0373275ecaa3362b820ac6b3d18acc70b287120aa1d2efecab2f0af6c866ee"
    ),
    "maru_audit_test_reset_allowed()": (
        "798326146c48661860bff7c4d7441ac5f03b624557d4f23d003b36cd9d2310b3"
    ),
    "maru_authority_bundle_historical_v1(uuid,timestamptz,uuid,bigint[],integer)": (
        "99c48835597a25b37560a94104921008380a2ea9dc9543a8cf50ede6ee871e2c"
    ),
    (
        "maru_authority_issuance_valid_v1(bigint,uuid,character varying,uuid,uuid,"
        "uuid,uuid,timestamptz,timestamptz,timestamptz,boolean,boolean,bigint[],"
        "integer)"
    ): "b9e6aed373ea09fa3c2095c9711b5c1443d65e022aa3b68d2ec06b41e449f666",
    "maru_authority_provenance_is_active()": (
        "9af8bca6b827ec9e97f8046d0089d6885cc6655aac333570e5246f1516113da4"
    ),
    "maru_authority_provenance_test_reset_allowed()": (
        "798326146c48661860bff7c4d7441ac5f03b624557d4f23d003b36cd9d2310b3"
    ),
    "maru_authority_scope_contains_v1(uuid,uuid,uuid,uuid,uuid,uuid,uuid,uuid)": (
        "d1a2ecdb25f3f3f7ce9c61de85540d75f397e063cf0b1fda5c72a2cf67e26670"
    ),
    "maru_authority_scope_is_current_v1(uuid,uuid,uuid,uuid)": (
        "a06a85ac5244acd056b5667d87f9016f26f2b19de1424739317eae57708dd9ae"
    ),
    "maru_deferred_validate_authority_assignment()": (
        "5bff4e2fe7d4124de7ed004fbe60412b86a9b7bf19d92c89652095e210915df2"
    ),
    "maru_deferred_validate_authority_bundle()": (
        "4590061d27f26b45107bb395f2ebd2efd38b8c86f699a4bd3decbea29d81cad8"
    ),
    "maru_deferred_validate_authority_control()": (
        "9c50996db73e739960f1fec019c73c56b29f49ed70b1373eb4ee04874c16485e"
    ),
    "maru_deferred_validate_authority_grant()": (
        "de049379cd390308df489473ef0242ffeccdb7ca5838fce738228220cfab862d"
    ),
    "maru_deferred_validate_authority_issuance()": (
        "58766b6323f17d5d16ffb0d5ef8738358ec34180326711ce1b03349e321890fa"
    ),
    "maru_deferred_validate_provenance_activation()": (
        "61b0855414b2b877119dbc6232d59817cf9ba696efb1d674c29d4a7be8a6ca2e"
    ),
    "maru_deferred_validate_provenance_latch()": (
        "c30ab3a203ab5395b0b044093a53d610716c74189b4fb9bcac8c4ae77d99c88e"
    ),
    "maru_guard_audit_event()": (
        "92479ea4458dbabd8d0d0500a4012b13d0c2dd167b87826b3d29a22f051c2214"
    ),
    "maru_guard_authority_provenance_activation_audit()": (
        "6af148c2e6ebf1a094eb39cc5013561e45d4957a53153986524b167130b7b479"
    ),
    "maru_guard_authority_provenance_activation()": (
        "0ca22182fa32f699f51dc7da88cd99f7c09cc6531fda2bc6f2fad4a7a56afa52"
    ),
    "maru_guard_authority_provenance_latch()": (
        "7bf9cbbbb9d468b709bd5fcc7da275681539be722b41639c4ddb9e3a82f091a3"
    ),
    "maru_lock_authority_provenance_latch()": (
        "66f9ec6680be94188a0c5265bb07bdf30eed6670696ff706a59cd00f60a7b148"
    ),
    "maru_lock_authority_provenance_writer()": (
        "a9a21f49f934babaec4cc2c4641d98177de55da2dc4dc066bfcc817daef36f36"
    ),
    "maru_prevent_audit_event_truncate()": (
        "953dd2f8b2e27377a9c51a7c4e475c13316b8705ae2bf5903b3696661e8da0fb"
    ),
    "maru_prevent_authority_control_mutation()": (
        "c9ca39e15f1ae4af9f912d638f58f5cdaf73593d387517b7f7cbe3faf425d1cc"
    ),
    "maru_prevent_authority_record_delete()": (
        "5befa0dd6fb4ad61886a5bcbe268ec105c2beb450d51491fe61b8ae1a254debe"
    ),
    "maru_prevent_authority_issuance_mutation()": (
        "87930925db61a2f1dba4c902084eadc0f93a8dcbfa486f04fb0afa8cc4cafb70"
    ),
    "maru_prevent_authority_provenance_truncate()": (
        "1286e8a441b389d067686c2cd38da37108fbd243b02a487dfa9908f5c2b59ddd"
    ),
    "maru_prevent_role_bundle_mutation()": (
        "a9aaf9d6c38826c04860bdbb1dee0aeea5a8373c4fe52e605db30cd7980ed5e9"
    ),
    "maru_prevent_scoped_resource_binding_mutation()": (
        "a243ba4cc476dadfcf6c5d7468dddd622389e0d90832e0566a44f9d9a826e2fa"
    ),
    "maru_reseed_authority_provenance_latch()": (
        "199f6fed15e24d855f070adf990494410999bb6c60f6a9423f6c6c6f10e0ed93"
    ),
    "maru_validate_authority_control_insert()": (
        "d0d90f0e3ba495244011c1f1b436aa11c0be8c9cb001b5fb693b29f9b0aaa22e"
    ),
    "maru_validate_authority_issuance_insert()": (
        "be7ca045f7f38b30c2d65002cd8c50a4e9c2408008f15273d4f823e48132ff40"
    ),
    "maru_validate_capability_grant()": (
        "8df9e28605db2edfedcd7cc3f5c5a2563c0a6ae243970a71a722679ee9425350"
    ),
    "maru_validate_role_assignment()": (
        "a656e41a4ac5864f3089a2f1894d28ad769e4afaaa04df877398e23cdb3982c8"
    ),
    "maru_validate_role_bundle_catalog()": (
        "1699be8a8d6178919ba7f14e354c9df2341dcc0da9d5bd4dae2e56aab7e69a34"
    ),
    "maru_validate_scoped_resource_binding()": (
        "897719f79a1638425810dc7b47a7c872b831b9fea670c834ece7b1aea20f4223"
    ),
    "maru_assert_department_structure_evidence()": (
        "7887c7c42b9770b592af5743b74f2ac47891e1d021aed3c9de45db3c5fe0a3bf"
    ),
    "maru_assert_edition_structure_control_evidence()": (
        "1c37f07d8fa5b7b6765ddeb2fccc0f852c21b0e55e1ed6b27e432d0559fb60f8"
    ),
    "maru_guard_assignment_retired_department()": (
        "e6265228b38fd359960c4e5e3506265b221f6bfb29628873f8d9df0e206611da"
    ),
    "maru_guard_position_retired_department()": (
        "6518f7456d68cd68fba7bf3eb3b2056de1c9a2308c49160bfcca7e052834c19d"
    ),
    "maru_prevent_department_structure_truncate()": (
        "747cdf967ed6a518d641beed4abba918ae69938ad5f4ae4c5b99e3129b8cce1f"
    ),
    "maru_prevent_edition_structure_control_mutation()": (
        "3f765a5c19d7da7c2796b15ef175251492fe5302f0590c6ded011b9f048a282f"
    ),
    "maru_prevent_edition_structure_receipt_mutation()": (
        "f5f6dc38198cf2978e3c7613152b869375f1d26232ebcd4560986104e00f11fa"
    ),
    "maru_validate_department_structure_write()": (
        "e4a44adc84bce76b97a4e6d0f8fef19825b891d94bf41dc17f92225d1808f22a"
    ),
    "maru_validate_edition_structure_control()": (
        "52daa0c470438ca34cdd2a00e1b0aa5e61b9bed98a9cfc320b21a92fc6911686"
    ),
    "maru_validate_edition_structure_receipt()": (
        "0856108aaf1bf9fd11092d908fd289542e36faeb815a47e7d5de5680f2abd5a4"
    ),
    "maru_workforce_department_fk_contract_is_current()": (
        "83e5707405156ec49bd70059a1cdcdf78c7d6472a198ea0151bc63efd84fa935"
    ),
    "maru_workforce_page9_scope_mutex()": (
        "75e5f8a98fd059d1e5d2de0db420e77beec79f3c6eb12b051388ab66c85790c6"
    ),
    "maru_workforce_page9_try_scope_mutex(bigint)": (
        "4ebf99f0177936704c44598ee63a058e57bf6aaca130c51b8a8fa4fb799cb86f"
    ),
    "maru_workforce_page9_writer_barrier()": (
        "a5ca2897e19293a78e805a1a8fb4484f6822def7713c35141c0e7f2fbb4ad429"
    ),
}

_DOWNGRADE_FENCE_TRIGGER_NAMES = frozenset(
    {
        "authorization_capability_grant_guard",
        "authorization_capability_grant_no_delete",
        "authorization_role_assignment_guard",
        "authorization_role_assignment_no_delete",
        "authorization_role_bundle_catalog_guard",
        "authorization_role_bundle_immutable",
        "authorization_scoped_resource_binding_guard",
        "authorization_scoped_resource_binding_immutable",
        "authorization_retired_binding_guard",
        "authorization_retired_capability_guard",
        "authorization_retired_role_guard",
        "authorization_retired_department_authority_guard",
        "authorization_retired_binding_writer_lock",
        "authorization_retired_capability_writer_lock",
        "authorization_retired_role_writer_lock",
        "authorization_retired_department_writer_lock",
        "authorization_authority_issuance_insert_guard",
        "authorization_authority_issuance_immutable",
        "authorization_authority_control_insert_guard",
        "authorization_authority_control_immutable",
        "audit_event_append_only",
        "authorization_provenance_latch_guard",
        "authorization_provenance_activation_guard",
        "authorization_provenance_activation_complete",
        "authorization_provenance_latch_complete",
        "authorization_capability_grant_provenance_no_truncate",
        "authorization_role_bundle_provenance_no_truncate",
        "authorization_role_assignment_provenance_no_truncate",
        "authorization_authority_issuance_provenance_no_truncate",
        "authorization_authority_control_provenance_no_truncate",
        "authorization_provenance_activation_no_truncate",
        "authorization_provenance_latch_no_truncate",
        "authorization_activation_audit_provenance_no_truncate",
        "authorization_activation_audit_reserved_guard",
        "organizations_representation_membership_provenance",
        "organizations_appointment_membership_provenance",
        "organizations_membership_board_provenance",
        "organizations_representation_deferred_integrity",
        "organizations_appointment_deferred_integrity",
        "authorization_role_assignment_deferred_board_integrity",
        "authorization_role_bundle_deferred_board_integrity",
        "organizations_membership_deferred_board_integrity",
        "identity_account_deferred_board_integrity",
        "organizations_parent_deferred_board_integrity",
        "workforce_position_guard",
        "workforce_assignment_guard",
        "aa_workforce_page9_department_barrier",
        "aa_workforce_page9_control_barrier",
        "aa_workforce_page9_receipt_barrier",
        "aa_workforce_page9_position_barrier",
        "aa_workforce_page9_assignment_barrier",
        "aa_workforce_page9_binding_barrier",
        "aa_workforce_page9_capability_barrier",
        "aa_workforce_page9_role_barrier",
        "ab_workforce_page9_department_scope",
        "ab_workforce_page9_control_scope",
        "ab_workforce_page9_receipt_scope",
        "ab_workforce_page9_position_scope",
        "ab_workforce_page9_assignment_scope",
        "ab_workforce_page9_binding_scope",
        "ab_workforce_page9_capability_scope",
        "ab_workforce_page9_role_scope",
        "ac_workforce_page9_control_guard",
        "ac_workforce_page9_control_no_delete",
        "ac_workforce_page9_control_no_truncate",
        "ac_workforce_page9_receipt_guard",
        "ac_workforce_page9_receipt_immutable",
        "ac_workforce_page9_receipt_no_truncate",
        "ac_workforce_page9_department_guard",
        "ac_workforce_page9_department_no_truncate",
        "ac_workforce_page9_position_retired_guard",
        "ac_workforce_page9_assignment_retired_guard",
        "workforce_page9_control_evidence",
        "workforce_page9_department_evidence",
    }
)
_DOWNGRADE_FENCE_FUNCTIONS = frozenset(
    {
        "maru_assert_active_board_membership_provenance(uuid)",
        "maru_assert_active_executive_board(uuid)",
        "maru_assert_active_executive_board_v0009(uuid)",
        (
            "maru_workforce_role_evidence_matches_position(uuid,uuid,uuid,uuid,"
            "uuid,uuid)"
        ),
        "maru_deferred_validate_board_membership_from_representation()",
        "maru_deferred_validate_board_membership_from_appointment()",
        "maru_deferred_validate_board_membership()",
        "maru_deferred_validate_representation()",
        "maru_deferred_validate_appointment()",
        "maru_deferred_validate_role_assignment()",
        "maru_deferred_validate_role_bundle()",
        "maru_deferred_validate_membership()",
        "maru_deferred_validate_board_account()",
        "maru_deferred_validate_board_organization()",
        "maru_guard_workforce_position()",
        "maru_guard_workforce_assignment()",
        "maru_authorization_capability_min_scope(text)",
        "maru_authorization_scope_rank(uuid,uuid,uuid)",
        "maru_authorization_scope_contains(uuid,uuid,uuid,uuid,uuid,uuid,uuid,uuid)",
        "maru_validate_capability_grant()",
        "maru_prevent_authority_record_delete()",
        "maru_validate_role_assignment()",
        "maru_validate_role_bundle_catalog()",
        "maru_prevent_role_bundle_mutation()",
        "maru_validate_scoped_resource_binding()",
        "maru_prevent_scoped_resource_binding_mutation()",
        "maru_reject_retired_authority_target()",
        "maru_guard_department_retirement_authority()",
        "maru_lock_retired_department_authority_writer()",
        "maru_validate_authority_issuance_insert()",
        "maru_prevent_authority_issuance_mutation()",
        "maru_validate_authority_control_insert()",
        "maru_prevent_authority_control_mutation()",
        "maru_guard_audit_event()",
        "maru_guard_authority_provenance_activation_audit()",
        "maru_audit_test_reset_allowed()",
        "maru_prevent_audit_event_truncate()",
        "maru_authority_provenance_test_reset_allowed()",
        "maru_lock_authority_provenance_latch()",
        "maru_lock_authority_provenance_writer()",
        "maru_guard_authority_provenance_latch()",
        "maru_guard_authority_provenance_activation()",
        "maru_prevent_authority_provenance_truncate()",
        "maru_assert_authority_provenance_activation()",
        "maru_deferred_validate_provenance_activation()",
        "maru_deferred_validate_provenance_latch()",
        "maru_workforce_page9_writer_barrier()",
        "maru_workforce_page9_try_scope_mutex(bigint)",
        "maru_workforce_page9_scope_mutex()",
        "maru_validate_edition_structure_control()",
        "maru_assert_edition_structure_control_evidence()",
        "maru_prevent_edition_structure_control_mutation()",
        "maru_validate_edition_structure_receipt()",
        "maru_prevent_edition_structure_receipt_mutation()",
        "maru_workforce_department_fk_contract_is_current()",
        "maru_validate_department_structure_write()",
        "maru_assert_department_structure_evidence()",
        "maru_prevent_department_structure_truncate()",
        "maru_guard_position_retired_department()",
        "maru_guard_assignment_retired_department()",
    }
)


def _function_definition_fingerprint(definition: tuple[object, ...]) -> str:
    """Hash behavior-bearing pg_proc fields without exposing function bodies.

    Parameters
    ----------
    definition : tuple[object, ...]
        The versioned definition governing the requested behavior.

    Returns
    -------
    str
        The normalized text for function definition fingerprint.
    """
    configuration = definition[9]
    if configuration is not None:
        configuration = list(cast("Iterable[object]", configuration))
    payload = {
        "source": definition[0],
        "language": definition[1],
        "volatility": definition[2],
        "parallel": definition[3],
        "security_definer": definition[4],
        "leakproof": definition[5],
        "strict": definition[6],
        "returns_set": definition[7],
        "kind": definition[8],
        "config": configuration,
        "result": definition[10],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _supported_database_schema_is_active() -> bool:
    """Check the effective schema order before any authority graph is loaded.

    PostgreSQL searches an initialized temporary schema implicitly ahead of
    the configured ``search_path`` for relations.  ``current_schema()`` alone
    therefore cannot prove that an unqualified ORM read will resolve to
    ``public``.  Permit only ``pg_catalog`` ahead of ``public`` in the
    effective order and fail closed unless the exact safe prefix is present.

    Returns
    -------
    bool
        `True` when Check the effective schema order before any authority graph
        is loaded; otherwise `False`.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_catalog.current_schemas(TRUE)")
        effective_schemas = tuple(cast("Iterable[str]", cursor.fetchone()[0]))
    return effective_schemas[:2] == ("pg_catalog", _SUPPORTED_DATABASE_SCHEMA)


def _configured_runtime_database_role_is_safe() -> bool:
    """Prove the future service role without requiring this owner session to use it.

    Returns
    -------
    bool
        `True` when Prove the future service role without requiring this owner
        session to use it; otherwise `False`.
    """
    role_name = settings.RUNTIME_DATABASE_ROLE
    if not isinstance(role_name, str) or not role_name:
        return False
    try:
        return probe_runtime_database_role_safety(
            role_name=role_name,
        ).target_role_is_safe
    except (DatabaseError, RuntimeDatabaseRoleProbeError):
        return False


def _inspect_cutover_catalog() -> _CatalogState:
    """Read the exact installed cutover contract without process-local caching.

    Returns
    -------
    _CatalogState
        The resolved _CatalogState for inspect cutover catalog.
    """
    trigger_names = [contract.name for contract in _TRIGGER_CONTRACTS]
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_catalog.current_setting('server_version_num')::integer / 10000"
        )
        server_major = cast("int", cursor.fetchone()[0])
        server_version_supported = server_major == _SUPPORTED_POSTGRESQL_SERVER_MAJOR
        cursor.execute(
            "SELECT to_regclass(%s), to_regclass(%s)",
            [
                (
                    f"{_SUPPORTED_DATABASE_SCHEMA}."
                    f"{AuthorityProvenanceActivation._meta.db_table}"  # noqa: SLF001
                ),
                (
                    f"{_SUPPORTED_DATABASE_SCHEMA}."
                    f"{AuthorityProvenanceActivationLatch._meta.db_table}"  # noqa: SLF001
                ),
            ],
        )
        marker_table, latch_table = cursor.fetchone()
        marker_table_installed = marker_table is not None
        latch_table_installed = latch_table is not None
        cursor.execute(
            """
            SELECT trigger.tgname::text,
                   relation.relname::text,
                   procedure.oid::regprocedure::text,
                   trigger.tgtype,
                   trigger.tgenabled,
                   trigger.tgdeferrable,
                   trigger.tginitdeferred,
                   trigger.tgqual IS NULL,
                   trigger.tgnargs,
                   ARRAY(
                       SELECT attribute.attname::text
                         FROM unnest(
                                  trigger.tgattr::smallint[]
                              ) WITH ORDINALITY AS selected(attnum, position)
                         JOIN pg_attribute AS attribute
                           ON attribute.attrelid = trigger.tgrelid
                          AND attribute.attnum = selected.attnum
                        ORDER BY selected.position
                   )
              FROM pg_trigger AS trigger
              JOIN pg_class AS relation ON relation.oid = trigger.tgrelid
              JOIN pg_namespace AS relation_namespace
                ON relation_namespace.oid = relation.relnamespace
              JOIN pg_proc AS procedure ON procedure.oid = trigger.tgfoid
              JOIN pg_namespace AS procedure_namespace
                ON procedure_namespace.oid = procedure.pronamespace
             WHERE NOT trigger.tgisinternal
               AND relation_namespace.nspname = %s
               AND procedure_namespace.nspname = %s
               AND trigger.tgname::text = ANY(%s::text[])
            """,
            [
                _SUPPORTED_DATABASE_SCHEMA,
                _SUPPORTED_DATABASE_SCHEMA,
                trigger_names,
            ],
        )
        trigger_rows = cursor.fetchall()
        trigger_counts = Counter(row[0] for row in trigger_rows)
        installed_triggers = {
            row[0]: (*tuple(row[1:9]), tuple(row[9] or ())) for row in trigger_rows
        }
        cursor.execute(
            """
            SELECT required.identity,
                   procedure.oid IS NOT NULL
                       AND namespace.nspname = %s,
                   procedure.prosrc,
                   language.lanname::text,
                   procedure.provolatile::text,
                   procedure.proparallel::text,
                   procedure.prosecdef,
                   procedure.proleakproof,
                   procedure.proisstrict,
                   procedure.proretset,
                   procedure.prokind::text,
                   procedure.proconfig,
                   pg_get_function_result(procedure.oid)
              FROM unnest(%s::text[]) AS required(identity)
              LEFT JOIN pg_proc AS procedure
                ON procedure.oid = to_regprocedure(%s || '.' || required.identity)
              LEFT JOIN pg_namespace AS namespace
                ON namespace.oid = procedure.pronamespace
              LEFT JOIN pg_language AS language
                ON language.oid = procedure.prolang
            """,
            [
                _SUPPORTED_DATABASE_SCHEMA,
                list(_CORE_FUNCTIONS),
                _SUPPORTED_DATABASE_SCHEMA,
            ],
        )
        installed_functions = {
            str(row[0]): (
                bool(row[1])
                and _function_definition_fingerprint(tuple(row[2:]))
                == _FUNCTION_DEFINITION_SHA256.get(str(row[0]))
            )
            for row in cursor.fetchall()
        }
        cursor.execute(
            """
            SELECT table_relation.relname::text,
                   access_method.amname::text,
                   index_record.indisunique,
                   index_record.indisvalid,
                   index_record.indisready,
                   index_record.indislive,
                   index_record.indnkeyatts,
                   index_record.indnatts,
                   index_record.indexprs IS NULL,
                   ARRAY(
                       SELECT pg_get_indexdef(
                           index_record.indexrelid,
                           key_position,
                           TRUE
                       )
                         FROM generate_series(
                             1,
                             index_record.indnkeyatts
                         ) AS key_position
                        ORDER BY key_position
                   ),
                   pg_get_expr(
                       index_record.indpred,
                       index_record.indrelid,
                       TRUE
                   )
              FROM pg_index AS index_record
              JOIN pg_class AS index_relation
                ON index_relation.oid = index_record.indexrelid
              JOIN pg_namespace AS index_namespace
                ON index_namespace.oid = index_relation.relnamespace
              JOIN pg_class AS table_relation
                ON table_relation.oid = index_record.indrelid
              JOIN pg_namespace AS table_namespace
                ON table_namespace.oid = table_relation.relnamespace
              JOIN pg_am AS access_method
                ON access_method.oid = index_relation.relam
             WHERE index_namespace.nspname = %s
               AND table_namespace.nspname = %s
               AND index_relation.relname = %s
            """,
            [
                _SUPPORTED_DATABASE_SCHEMA,
                _SUPPORTED_DATABASE_SCHEMA,
                _ACTIVATION_AUDIT_INDEX,
            ],
        )
        index_rows = cursor.fetchall()
        activation_apps, activation_names = zip(*_ACTIVATION_MIGRATIONS, strict=True)
        cursor.execute(
            """
            SELECT migration.app, migration.name
              FROM public.django_migrations AS migration
              JOIN unnest(%s::text[], %s::text[]) AS required(app, name)
                ON required.app = migration.app
               AND required.name = migration.name
             ORDER BY migration.app, migration.name
            """,
            [list(activation_apps), list(activation_names)],
        )
        migration_applied = tuple(cursor.fetchall()) == _ACTIVATION_MIGRATIONS

    def trigger_matches(contract: _TriggerContract) -> bool:
        return trigger_counts[contract.name] == 1 and installed_triggers.get(
            contract.name
        ) == (
            contract.table,
            contract.function,
            contract.trigger_type,
            "O",
            contract.deferrable,
            contract.initially_deferred,
            True,
            0,
            contract.columns,
        )

    functions_installed = (
        set(_FUNCTION_DEFINITION_SHA256) == set(_CORE_FUNCTIONS)
        and len(installed_functions) == len(_CORE_FUNCTIONS)
        and all(installed_functions.values())
    )
    audit_index_installed = (
        len(index_rows) == 1
        and tuple(index_rows[0][:9])
        == (
            "audit_auditevent",
            "btree",
            True,
            True,
            True,
            True,
            2,
            2,
            True,
        )
        and tuple(index_rows[0][9]) == ("operation", "correlation_id")
        and index_rows[0][10] in _ACTIVATION_AUDIT_INDEX_PREDICATES
    )
    guards_installed = (
        marker_table_installed
        and latch_table_installed
        and migration_applied
        and audit_index_installed
        and functions_installed
        and len(installed_triggers) == len(_TRIGGER_CONTRACTS)
        and all(trigger_matches(contract) for contract in _TRIGGER_CONTRACTS)
    )
    downgrade_fence_installed = (
        marker_table_installed
        and latch_table_installed
        and migration_applied
        and audit_index_installed
        and all(
            installed_functions.get(identity, False)
            for identity in _DOWNGRADE_FENCE_FUNCTIONS
        )
        and all(
            trigger_matches(contract)
            for contract in _TRIGGER_CONTRACTS
            if contract.name in _DOWNGRADE_FENCE_TRIGGER_NAMES
        )
    )
    return _CatalogState(
        server_version_supported=server_version_supported,
        marker_table_installed=marker_table_installed,
        latch_table_installed=latch_table_installed,
        migration_applied=migration_applied,
        audit_index_installed=audit_index_installed,
        guards_installed=guards_installed,
        downgrade_fence_installed=downgrade_fence_installed,
    )


def _inspect_cutover_state() -> _CutoverState:
    catalog = _inspect_cutover_catalog()
    marker_rows: tuple[Mapping[str, object], ...] = ()
    latch_rows: tuple[Mapping[str, object], ...] = ()
    if catalog.marker_table_installed:
        marker_rows = tuple(
            AuthorityProvenanceActivation.objects.order_by("singleton").values(
                "singleton",
                "contract_version",
                "policy_version",
                "activated_by_id",
                "reason",
                "correlation_id",
                "activated_at",
            )[:2]
        )
    if catalog.latch_table_installed:
        latch_rows = tuple(
            AuthorityProvenanceActivationLatch.objects.order_by("singleton").values(
                "singleton",
                "generation",
            )[:2]
        )
    latch_initial = len(latch_rows) == 1 and latch_rows[0] == {
        "singleton": True,
        "generation": AUTHORITY_PROVENANCE_INACTIVE_GENERATION,
    }
    latch_active = len(latch_rows) == 1 and latch_rows[0] == {
        "singleton": True,
        "generation": AUTHORITY_PROVENANCE_ACTIVE_GENERATION,
    }
    marker_absent = catalog.marker_table_installed and not marker_rows and latch_initial
    marker_contract_valid = (
        len(marker_rows) == 1
        and marker_rows[0]["singleton"] is True
        and marker_rows[0]["contract_version"] == AUTHORITY_PROVENANCE_CONTRACT_VERSION
        and marker_rows[0]["policy_version"]
        == AUTHORITY_PROVENANCE_ACTIVATION_POLICY_VERSION
        and isinstance(marker_rows[0]["reason"], str)
        and bool(marker_rows[0]["reason"].strip())
    )
    activation_audit_valid = False
    if marker_contract_valid:
        marker_row = marker_rows[0]
        activated_by_id = cast("UUID", marker_row["activated_by_id"])
        correlation_id = cast("UUID", marker_row["correlation_id"])
        activated_at = cast("datetime", marker_row["activated_at"])
        activation_audit_valid = (
            AuditEvent.objects.filter(
                schema_version=1,
                occurred_at=activated_at,
                principal_kind=Account.Kind.PLATFORM_ADMINISTRATOR,
                principal_id=activated_by_id,
                principal_context_id__isnull=True,
                organization_id__isnull=True,
                event_edition_id__isnull=True,
                capability_code="authorization.manage_roles",
                operation="authorization.authority_provenance.activate",
                target_type="authorization.authority_provenance_activation",
                target_id__isnull=True,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code="exact_lineage_cutover",
                obligations=["reason", "audit", "stopped_processes"],
                changed_fields=["authority_provenance_activation"],
                correlation_id=correlation_id,
                causation_id__isnull=True,
                request_id__isnull=True,
                idempotency_key_hash="",
                source_channel__regex=r"\S",
                delegated=False,
                elevated=True,
                break_glass=False,
                safe_metadata={
                    "contract_version": marker_row["contract_version"],
                    "policy_version": marker_row["policy_version"],
                },
                retention_class="security-extended",
            ).count()
            == 1
        )
    marker_valid = marker_contract_valid and latch_active and activation_audit_valid
    policy_contract_installed = (
        EXACT_LINEAGE_POLICY_CONTRACT_VERSION == AUTHORITY_PROVENANCE_CONTRACT_VERSION
        and EXACT_LINEAGE_POLICY_VERSION
        == AUTHORITY_PROVENANCE_ACTIVATION_POLICY_VERSION
    )
    policy_active = bool(
        marker_valid and policy_contract_installed and exact_lineage_policy_is_active()
    )
    return _CutoverState(
        server_version_supported=catalog.server_version_supported,
        marker_absent=marker_absent,
        marker_valid=marker_valid,
        policy_contract_installed=policy_contract_installed,
        policy_active=policy_active,
        guards_installed=catalog.guards_installed,
        downgrade_fence_installed=(marker_valid and catalog.downgrade_fence_installed),
    )


def authority_provenance_runtime_contract_is_ready() -> bool:
    """Prove the exact durable runtime contract without loading authority data.

    Returns
    -------
    bool
        `True` when Prove the exact durable runtime contract without loading
        authority data; otherwise `False`.
    """
    try:
        if not _supported_database_schema_is_active():
            return False
        cutover = _inspect_cutover_state()
    except (DatabaseError, KeyError, TypeError, ValueError):
        return False
    return bool(
        cutover.server_version_supported
        and cutover.marker_valid
        and cutover.policy_contract_installed
        and cutover.policy_active
        and cutover.guards_installed
        and cutover.downgrade_fence_installed
    )


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
        """Initialize the _AuthorityGraph instance.

        Parameters
        ----------
        at : datetime
            The timezone-aware instant at which to evaluate the decision.
        """
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
                target_id: min(ordinals, key=lambda value: cast("int", value))
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
                        cast("int", parent_issuance) >= cast("int", ordinal)
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
                    if cast("int", parent_issuance) >= cast("int", ordinal):
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
                issuance_ordinal=cast("int", ordinal),
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
    """Return deterministic aggregate-only ADR 0044 readiness evidence.

    Parameters
    ----------
    at : datetime | None, default=None
        The timezone-aware instant at which to evaluate the decision.

    Returns
    -------
    dict[str, object]
        A mapping containing the resolved build authority provenance readiness
        report data.
    """
    if not _supported_database_schema_is_active():
        return {
            "status": "blocked",
            "activation_status": "blocked",
            "production_status": "blocked",
            "blocker_counts": dict.fromkeys(BLOCKER_KEYS, 0),
            "blocker_total": 0,
            "review_counts": dict.fromkeys(REVIEW_KEYS, 0),
            "known_production_gates": dict.fromkeys(
                _PRODUCTION_GATE_KEYS,
                _GATE_UNRESOLVED,
            ),
        }
    effective_at = at or timezone.now()
    graph = _AuthorityGraph(at=effective_at)
    missing, reviews = graph.missing_and_review_counts()
    blockers = {**missing, **graph.structural_blocker_counts()}
    ordered_blockers = {key: int(blockers.get(key, 0)) for key in BLOCKER_KEYS}
    ordered_reviews = {key: int(reviews.get(key, 0)) for key in REVIEW_KEYS}
    blocker_total = sum(ordered_blockers.values())
    status = "blocked" if blocker_total else "ready"
    cutover = _inspect_cutover_state()
    runtime_database_role_safe = _configured_runtime_database_role_is_safe()
    activation_status = (
        "ready"
        if (
            status == "ready"
            and cutover.marker_absent
            and cutover.server_version_supported
            and runtime_database_role_safe
            and cutover.policy_contract_installed
            and cutover.guards_installed
        )
        else "blocked"
    )
    production_gates = {
        "postgresql_server_major": (
            _GATE_RESOLVED if cutover.server_version_supported else _GATE_UNRESOLVED
        ),
        "runtime_database_role": (
            _GATE_RESOLVED if runtime_database_role_safe else _GATE_UNRESOLVED
        ),
        "activation_marker": (
            _GATE_RESOLVED if cutover.marker_valid else _GATE_UNRESOLVED
        ),
        "exact_lineage_policy_cutover": (
            _GATE_RESOLVED if cutover.policy_active else _GATE_UNRESOLVED
        ),
        "database_completeness_guards": (
            _GATE_RESOLVED
            if cutover.marker_valid and cutover.guards_installed
            else _GATE_UNRESOLVED
        ),
        "provenance_write_downgrade_fence": (
            _GATE_RESOLVED if cutover.downgrade_fence_installed else _GATE_UNRESOLVED
        ),
    }
    production_status = (
        "ready"
        if status == "ready"
        and all(value == _GATE_RESOLVED for value in production_gates.values())
        else "blocked"
    )
    return {
        "status": status,
        "activation_status": activation_status,
        "production_status": production_status,
        "blocker_counts": ordered_blockers,
        "blocker_total": blocker_total,
        "review_counts": ordered_reviews,
        "known_production_gates": production_gates,
    }
