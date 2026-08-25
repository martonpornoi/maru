"""Value-minimized readiness for the account-invitation boundary.

Identity migrations ``0011`` through ``0018`` install the additive invitation,
reconciliation, token-digest-key, hardened delivery-integrity, scheduler
heartbeat, and measured account-search boundaries. They deliberately do *not*
activate the later stopped-writer generation. This module proves the complete
reviewed additive catalog and reports that separate cutover honestly.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final, cast

from django.conf import settings
from django.db import DatabaseError, connection, transaction

from maru.identity.invitation_key_config import invitation_encryption_is_ready
from maru.identity.invitation_retention import (
    InvitationRetentionConfigurationError,
    _database_now,
    configured_invitation_retention_policy,
    invitation_retention_policy_control_is_ready,
    terminal_invitation_payloads_are_destroyed,
)
from maru.identity.invitation_token_keys import (
    InvitationTokenKeyConfigurationError,
    invitation_token_keyring,
    invitation_token_keys_are_ready,
)
from maru.identity.models import (
    PlatformAccountInvitation,
    PlatformInvitationSchedulerRun,
)
from maru.settings.environment import normalized_https_origin

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.db.backends.utils import CursorWrapper

PAGE10_INVITATION_ADDITIVE_SCHEMA_GENERATION: Final = "page10-invitations-additive-v10"
# This is intentionally absent. Migration 0011 is additive and cannot provide
# stopped-writer or downgrade-fence evidence for a future canonical cutover.
PAGE10_INVITATION_STOPPED_WRITER_GENERATION: Final[str | None] = None

_SUPPORTED_DATABASE_SCHEMA: Final = "public"
_SUPPORTED_POSTGRESQL_SERVER_MAJOR: Final = 17
_REVIEWED_INTEGRITY_MIGRATION: Final = (
    "identity",
    "0011_platform_account_invitations",
)
_RECONCILIATION_SCHEMA_MIGRATION: Final = (
    "identity",
    "0012_invitation_delivery_reconciliation",
)
_DIGEST_KEY_SCHEMA_MIGRATION: Final = (
    "identity",
    "0013_invitation_token_digest_keys",
)
_HARDENED_INTEGRITY_MIGRATION: Final = (
    "identity",
    "0014_invitation_delivery_integrity",
)
_AUDIT_CARDINALITY_MIGRATION: Final = (
    "audit",
    "0007_identity_reconciliation_audit_uniqueness",
)
_SCHEDULER_HEARTBEAT_MIGRATION: Final = (
    "identity",
    "0015_platform_invitation_scheduler_runs",
)
_PREFIX_INDEX_MIGRATION: Final = (
    "identity",
    "0016_account_inventory_prefix_indexes",
)
_RETENTION_AUDIT_CARDINALITY_MIGRATION: Final = (
    "audit",
    "0008_identity_retention_audit_uniqueness",
)
_RETENTION_WORKFLOW_MIGRATION: Final = (
    "identity",
    "0018_invitation_retention_v8",
)
_RESOLVED: Final = "resolved"
_UNRESOLVED: Final = "unresolved"
_DELIVERY_HEARTBEAT_MAX_AGE: Final = timedelta(minutes=10)
_EXPIRY_HEARTBEAT_MAX_AGE: Final = timedelta(hours=2)
_DELIVERY_BACKLOG_MAX_AGE: Final = timedelta(minutes=15)
_EXPIRY_BACKLOG_MAX_AGE: Final = timedelta(hours=2)
_RETENTION_HEARTBEAT_MAX_AGE: Final = timedelta(hours=26)
_RETENTION_BACKLOG_MAX_AGE: Final = timedelta(hours=24)
_ACCOUNT_PREFIX_INDEX_NAMES: Final = frozenset(
    {
        "id_account_email_prefix_idx",
        "id_account_handle_prefix_idx",
        "id_account_name_prefix_idx",
    }
)


@dataclass(frozen=True, slots=True)
class _TriggerContract:
    table: str
    function: str
    trigger_type: int
    deferrable: bool = False
    initially_deferred: bool = False
    columns: tuple[str, ...] = ()
    when_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class _IndexContract:
    table: str
    keys: tuple[str, ...]
    opclasses: tuple[str, ...]
    options: tuple[int, ...]
    unique: bool = False
    predicate: str | None = None
    has_expressions: bool = False
    constraint: tuple[str, bool, bool, bool] | None = None

    @property
    def constraint_backed(self) -> bool:
        return self.constraint is not None


@dataclass(frozen=True, slots=True)
class PlatformInvitationAdditiveCatalog:
    """Data-free result of one bounded PostgreSQL catalog inspection.

    Attributes
    ----------
    server_version_supported
        The server version supported retained in this immutable projection.
    schema_order_safe
        The schema order safe retained in this immutable projection.
    migration_applied
        The migration applied retained in this immutable projection.
    relations_installed
        The relations installed retained in this immutable projection.
    reconciliation_migration_applied
        The reconciliation migration applied retained in this immutable projection.
    reconciliation_relations_installed
        The reconciliation relations installed retained in this immutable projection.
    digest_key_migration_applied
        The digest key migration applied retained in this immutable projection.
    digest_key_column_installed
        The digest key column installed retained in this immutable projection.
    hardened_integrity_migration_applied
        The hardened integrity migration applied retained in this immutable projection.
    audit_cardinality_migration_applied
        The audit cardinality migration applied retained in this immutable projection.
    scheduler_heartbeat_migration_applied
        The scheduler heartbeat migration applied retained in this immutable projection.
    scheduler_heartbeat_relation_installed
        Whether the scheduler heartbeat relation is installed.
    prefix_index_migration_applied
        The prefix index migration applied retained in this immutable projection.
    retention_audit_cardinality_migration_applied
        Whether the retention-audit cardinality migration is applied.
    retention_workflow_migration_applied
        The retention workflow migration applied retained in this immutable projection.
    retention_relations_installed
        The retention relations installed retained in this immutable projection.
    functions_fingerprinted
        The functions fingerprinted retained in this immutable projection.
    function_execute_boundary_closed
        The function execute boundary closed retained in this immutable projection.
    triggers_attached
        The triggers attached retained in this immutable projection.
    indexes_installed
        The indexes installed retained in this immutable projection.
    uncataloged_function_identities
        The uncataloged function identities retained in this immutable projection.
    uncataloged_trigger_names
        The uncataloged trigger names retained in this immutable projection.
    """

    server_version_supported: bool
    schema_order_safe: bool
    migration_applied: bool
    relations_installed: bool
    reconciliation_migration_applied: bool
    reconciliation_relations_installed: bool
    digest_key_migration_applied: bool
    digest_key_column_installed: bool
    hardened_integrity_migration_applied: bool
    audit_cardinality_migration_applied: bool
    scheduler_heartbeat_migration_applied: bool
    scheduler_heartbeat_relation_installed: bool
    prefix_index_migration_applied: bool
    retention_audit_cardinality_migration_applied: bool
    retention_workflow_migration_applied: bool
    retention_relations_installed: bool
    functions_fingerprinted: bool
    function_execute_boundary_closed: bool
    triggers_attached: bool
    indexes_installed: bool
    uncataloged_function_identities: tuple[str, ...]
    uncataloged_trigger_names: tuple[str, ...]

    @property
    def additive_contract_ready(self) -> bool:
        """Return whether additive contract ready.

        Returns
        -------
        bool
            `True` when Compute additive contract ready; otherwise `False`.
        """
        return all(
            (
                self.server_version_supported,
                self.schema_order_safe,
                self.migration_applied,
                self.relations_installed,
                self.reconciliation_migration_applied,
                self.reconciliation_relations_installed,
                self.digest_key_migration_applied,
                self.digest_key_column_installed,
                self.hardened_integrity_migration_applied,
                self.audit_cardinality_migration_applied,
                self.scheduler_heartbeat_migration_applied,
                self.scheduler_heartbeat_relation_installed,
                self.prefix_index_migration_applied,
                self.retention_audit_cardinality_migration_applied,
                self.retention_workflow_migration_applied,
                self.retention_relations_installed,
                self.functions_fingerprinted,
                self.function_execute_boundary_closed,
                self.triggers_attached,
                self.indexes_installed,
            )
        )


_ROW_AFTER_INSERT = 1 | 4
_ROW_AFTER_UPDATE = 1 | 16
_ROW_AFTER_INSERT_UPDATE = 1 | 4 | 16
_ROW_AFTER_INSERT_UPDATE_DELETE = 1 | 4 | 8 | 16
_ROW_BEFORE_INSERT = 1 | 2 | 4
_ROW_BEFORE_DELETE = 1 | 2 | 8
_ROW_BEFORE_UPDATE = 1 | 2 | 16
_ROW_BEFORE_INSERT_UPDATE = 1 | 2 | 4 | 16
_ROW_BEFORE_UPDATE_DELETE = 1 | 2 | 8 | 16
_ROW_BEFORE_INSERT_UPDATE_DELETE = 1 | 2 | 4 | 8 | 16
_STATEMENT_BEFORE_TRUNCATE = 2 | 32

_TRIGGER_CONTRACTS: Final[dict[str, _TriggerContract]] = {
    "identity_page10_inventory_update": _TriggerContract(
        "identity_platformaccountinventorycontrol",
        "identity_page10_inventory_guard()",
        _ROW_BEFORE_UPDATE_DELETE,
    ),
    "identity_page10_inventory_no_truncate": _TriggerContract(
        "identity_platformaccountinventorycontrol",
        "identity_page10_inventory_guard()",
        _STATEMENT_BEFORE_TRUNCATE,
    ),
    "identity_page10_account_inventory_bump": _TriggerContract(
        "identity_account",
        "identity_page10_account_inventory_bump()",
        _ROW_AFTER_INSERT_UPDATE_DELETE,
        columns=(
            "email",
            "login_handle",
            "display_name",
            "account_kind",
            "is_active",
            "email_verified_at",
            "date_joined",
        ),
    ),
    "identity_page10_invitation_write": _TriggerContract(
        "identity_platformaccountinvitation",
        "identity_page10_invitation_guard()",
        _ROW_BEFORE_INSERT_UPDATE,
    ),
    "identity_page10_invitation_no_delete": _TriggerContract(
        "identity_platformaccountinvitation",
        "identity_page10_protected_guard()",
        _ROW_BEFORE_DELETE,
    ),
    "identity_page10_invitation_no_truncate": _TriggerContract(
        "identity_platformaccountinvitation",
        "identity_page10_protected_guard()",
        _STATEMENT_BEFORE_TRUNCATE,
    ),
    "identity_page10_challenge_write": _TriggerContract(
        "identity_identitychallenge",
        "identity_page10_challenge_guard()",
        _ROW_BEFORE_INSERT_UPDATE_DELETE,
    ),
    "identity_page10_transition_insert": _TriggerContract(
        "identity_platformaccountinvitationtransition",
        "identity_page10_transition_guard()",
        _ROW_BEFORE_INSERT,
    ),
    "identity_page10_transition_immutable": _TriggerContract(
        "identity_platformaccountinvitationtransition",
        "identity_page10_append_only_guard()",
        _ROW_BEFORE_UPDATE_DELETE,
    ),
    "identity_page10_transition_no_truncate": _TriggerContract(
        "identity_platformaccountinvitationtransition",
        "identity_page10_append_only_guard()",
        _STATEMENT_BEFORE_TRUNCATE,
    ),
    "identity_page10_receipt_insert": _TriggerContract(
        "identity_platformaccountinvitationcommandreceipt",
        "identity_page10_receipt_guard()",
        _ROW_BEFORE_INSERT,
    ),
    "identity_page10_receipt_immutable": _TriggerContract(
        "identity_platformaccountinvitationcommandreceipt",
        "identity_page10_append_only_guard()",
        _ROW_BEFORE_UPDATE_DELETE,
    ),
    "identity_page10_receipt_no_truncate": _TriggerContract(
        "identity_platformaccountinvitationcommandreceipt",
        "identity_page10_append_only_guard()",
        _STATEMENT_BEFORE_TRUNCATE,
    ),
    "identity_page10_delivery_write": _TriggerContract(
        "identity_platformidentitydelivery",
        "identity_page10_delivery_guard()",
        _ROW_BEFORE_INSERT_UPDATE,
    ),
    "identity_page10_delivery_no_delete": _TriggerContract(
        "identity_platformidentitydelivery",
        "identity_page10_protected_guard()",
        _ROW_BEFORE_DELETE,
    ),
    "identity_page10_delivery_no_truncate": _TriggerContract(
        "identity_platformidentitydelivery",
        "identity_page10_protected_guard()",
        _STATEMENT_BEFORE_TRUNCATE,
    ),
    "identity_page10_attempt_insert": _TriggerContract(
        "identity_platformidentitydeliveryattempt",
        "identity_page10_attempt_guard()",
        _ROW_BEFORE_INSERT,
    ),
    "identity_page10_attempt_immutable": _TriggerContract(
        "identity_platformidentitydeliveryattempt",
        "identity_page10_retention_provider_child_guard()",
        _ROW_BEFORE_UPDATE_DELETE,
    ),
    "identity_page10_attempt_no_truncate": _TriggerContract(
        "identity_platformidentitydeliveryattempt",
        "identity_page10_append_only_guard()",
        _STATEMENT_BEFORE_TRUNCATE,
    ),
    "identity_page10_invitation_complete": _TriggerContract(
        "identity_platformaccountinvitation",
        "identity_page10_invitation_complete()",
        _ROW_AFTER_INSERT_UPDATE,
        deferrable=True,
        initially_deferred=True,
    ),
    "identity_page10_challenge_complete": _TriggerContract(
        "identity_identitychallenge",
        "identity_page10_challenge_complete()",
        _ROW_AFTER_INSERT_UPDATE,
        deferrable=True,
        initially_deferred=True,
    ),
    "identity_page10_transition_complete": _TriggerContract(
        "identity_platformaccountinvitationtransition",
        "identity_page10_transition_complete()",
        _ROW_AFTER_INSERT,
        deferrable=True,
        initially_deferred=True,
    ),
    "identity_page10_account_complete": _TriggerContract(
        "identity_account",
        "identity_page10_account_complete()",
        _ROW_AFTER_UPDATE,
        deferrable=True,
        initially_deferred=True,
        columns=(
            "account_kind",
            "is_active",
            "is_staff",
            "is_superuser",
            "email_verified_at",
            "password",
            "email",
        ),
    ),
    "identity_page10_delivery_version": _TriggerContract(
        "identity_platformidentitydelivery",
        "identity_page10_delivery_version_guard()",
        _ROW_BEFORE_UPDATE,
        when_sha256=(
            "b18029d0a95dd425ae369dc640458126bacd1c2aab83d391c8254a1a97e8f417"
        ),
    ),
    "identity_page10_late_outcome_immutable": _TriggerContract(
        "identity_platformidentitydeliverylateoutcome",
        "identity_page10_retention_provider_child_guard()",
        _ROW_BEFORE_UPDATE_DELETE,
    ),
    "identity_page10_late_outcome_insert": _TriggerContract(
        "identity_platformidentitydeliverylateoutcome",
        "identity_page10_attempt_guard()",
        _ROW_BEFORE_INSERT,
    ),
    "identity_page10_late_outcome_no_truncate": _TriggerContract(
        "identity_platformidentitydeliverylateoutcome",
        "identity_page10_append_only_guard()",
        _STATEMENT_BEFORE_TRUNCATE,
    ),
    "identity_page10_reconcile_receipt_immutable": _TriggerContract(
        "identity_platformidentitydeliveryreconciliationreceipt",
        "identity_page10_append_only_guard()",
        _ROW_BEFORE_UPDATE_DELETE,
    ),
    "identity_page10_reconcile_receipt_insert": _TriggerContract(
        "identity_platformidentitydeliveryreconciliationreceipt",
        "identity_page10_reconcile_receipt_guard()",
        _ROW_BEFORE_INSERT,
    ),
    "identity_page10_reconcile_receipt_no_truncate": _TriggerContract(
        "identity_platformidentitydeliveryreconciliationreceipt",
        "identity_page10_append_only_guard()",
        _STATEMENT_BEFORE_TRUNCATE,
    ),
    "identity_page10_token_digest_key": _TriggerContract(
        "identity_identitychallenge",
        "identity_page10_token_digest_key_guard()",
        _ROW_BEFORE_INSERT_UPDATE,
    ),
    "identity_page10_hardened_attempt_complete": _TriggerContract(
        "identity_platformidentitydeliveryattempt",
        "identity_page10_hardened_delivery_child_complete()",
        _ROW_AFTER_INSERT,
        deferrable=True,
        initially_deferred=True,
    ),
    "identity_page10_hardened_attempt_insert": _TriggerContract(
        "identity_platformidentitydeliveryattempt",
        "identity_page10_hardened_attempt_guard()",
        _ROW_BEFORE_INSERT,
    ),
    "identity_page10_hardened_challenge_write": _TriggerContract(
        "identity_identitychallenge",
        "identity_page10_hardened_challenge_guard()",
        _ROW_BEFORE_INSERT_UPDATE_DELETE,
    ),
    "identity_page10_hardened_delivery_complete": _TriggerContract(
        "identity_platformidentitydelivery",
        "identity_page10_hardened_delivery_complete()",
        _ROW_AFTER_INSERT_UPDATE,
        deferrable=True,
        initially_deferred=True,
    ),
    "identity_page10_hardened_delivery_insert": _TriggerContract(
        "identity_platformidentitydelivery",
        "identity_page10_hardened_delivery_guard()",
        _ROW_BEFORE_INSERT,
    ),
    "identity_page10_hardened_delivery_update": _TriggerContract(
        "identity_platformidentitydelivery",
        "identity_page10_hardened_delivery_guard()",
        _ROW_BEFORE_UPDATE,
        when_sha256=(
            "c3bccbe822870ad45afcbb96cfc123bf8138ac4f62bcf71a84c43bcf485a6dec"
        ),
    ),
    "identity_page10_retention_provider_delivery_update": _TriggerContract(
        "identity_platformidentitydelivery",
        "identity_page10_retention_provider_delivery_guard()",
        _ROW_BEFORE_UPDATE,
    ),
    "identity_page10_hardened_late_complete": _TriggerContract(
        "identity_platformidentitydeliverylateoutcome",
        "identity_page10_hardened_delivery_child_complete()",
        _ROW_AFTER_INSERT,
        deferrable=True,
        initially_deferred=True,
    ),
    "identity_page10_hardened_late_outcome_insert": _TriggerContract(
        "identity_platformidentitydeliverylateoutcome",
        "identity_page10_hardened_late_outcome_guard()",
        _ROW_BEFORE_INSERT,
    ),
    "identity_page10_hardened_receipt_insert": _TriggerContract(
        "identity_platformaccountinvitationcommandreceipt",
        "identity_page10_hardened_receipt_guard()",
        _ROW_BEFORE_INSERT,
    ),
    "identity_page10_hardened_receipt_complete": _TriggerContract(
        "identity_platformaccountinvitationcommandreceipt",
        "identity_page10_hardened_receipt_complete()",
        _ROW_AFTER_INSERT,
        deferrable=True,
        initially_deferred=True,
    ),
    "identity_page10_hardened_reconcile_complete": _TriggerContract(
        "identity_platformidentitydeliveryreconciliationreceipt",
        "identity_page10_hardened_delivery_child_complete()",
        _ROW_AFTER_INSERT,
        deferrable=True,
        initially_deferred=True,
    ),
    "identity_page10_hardened_reconcile_audit_complete": _TriggerContract(
        "identity_platformidentitydeliveryreconciliationreceipt",
        "identity_page10_hardened_reconcile_audit_complete()",
        _ROW_AFTER_INSERT,
        deferrable=True,
        initially_deferred=True,
    ),
    "identity_page10_hardened_reconcile_insert": _TriggerContract(
        "identity_platformidentitydeliveryreconciliationreceipt",
        "identity_page10_hardened_reconcile_guard()",
        _ROW_BEFORE_INSERT,
    ),
    "identity_page10_hardened_transition_insert": _TriggerContract(
        "identity_platformaccountinvitationtransition",
        "identity_page10_hardened_transition_guard()",
        _ROW_BEFORE_INSERT,
    ),
    "identity_page10_hardened_transition_complete": _TriggerContract(
        "identity_platformaccountinvitationtransition",
        "identity_page10_hardened_transition_complete()",
        _ROW_AFTER_INSERT,
        deferrable=True,
        initially_deferred=True,
    ),
    "identity_page10_scheduler_run_immutable": _TriggerContract(
        "identity_platforminvitationschedulerrun",
        "identity_page10_append_only_guard()",
        _ROW_BEFORE_UPDATE_DELETE,
    ),
    "identity_page10_scheduler_run_no_truncate": _TriggerContract(
        "identity_platforminvitationschedulerrun",
        "identity_page10_append_only_guard()",
        _STATEMENT_BEFORE_TRUNCATE,
    ),
    "identity_page10_scheduler_run_strict_time": _TriggerContract(
        "identity_platforminvitationschedulerrun",
        "identity_page10_retention_strict_time_guard()",
        _ROW_BEFORE_INSERT,
    ),
    "identity_page10_retention_policy_update": _TriggerContract(
        "identity_platforminvitationretentionpolicycontrol",
        "identity_page10_retention_policy_control_guard()",
        _ROW_BEFORE_INSERT_UPDATE_DELETE,
    ),
    "identity_page10_retention_policy_no_truncate": _TriggerContract(
        "identity_platforminvitationretentionpolicycontrol",
        "identity_page10_retention_policy_control_guard()",
        _STATEMENT_BEFORE_TRUNCATE,
    ),
    "identity_page10_invitation_origin_insert_complete": _TriggerContract(
        "identity_account",
        "identity_page10_invitation_origin_complete()",
        _ROW_AFTER_INSERT,
        deferrable=True,
        initially_deferred=True,
    ),
    "identity_page10_invitation_origin_update_complete": _TriggerContract(
        "identity_account",
        "identity_page10_invitation_origin_complete()",
        _ROW_AFTER_UPDATE,
        deferrable=True,
        initially_deferred=True,
        columns=("invitation_provisioning_origin_id",),
    ),
    "identity_page10_retention_hold_write": _TriggerContract(
        "identity_platforminvitationretentionhold",
        "identity_page10_retention_hold_guard()",
        _ROW_BEFORE_INSERT_UPDATE_DELETE,
    ),
    "identity_page10_retention_hold_no_truncate": _TriggerContract(
        "identity_platforminvitationretentionhold",
        "identity_page10_append_only_guard()",
        _STATEMENT_BEFORE_TRUNCATE,
    ),
    "identity_page10_retention_hold_complete": _TriggerContract(
        "identity_platforminvitationretentionhold",
        "identity_page10_retention_hold_complete()",
        _ROW_AFTER_INSERT_UPDATE,
        deferrable=True,
        initially_deferred=True,
    ),
    "identity_page10_retention_receipt_insert": _TriggerContract(
        "identity_platforminvitationretentionreceipt",
        "identity_page10_retention_receipt_guard()",
        _ROW_BEFORE_INSERT,
    ),
    "identity_page10_retention_receipt_immutable": _TriggerContract(
        "identity_platforminvitationretentionreceipt",
        "identity_page10_append_only_guard()",
        _ROW_BEFORE_UPDATE_DELETE,
    ),
    "identity_page10_retention_receipt_no_truncate": _TriggerContract(
        "identity_platforminvitationretentionreceipt",
        "identity_page10_append_only_guard()",
        _STATEMENT_BEFORE_TRUNCATE,
    ),
    "identity_page10_retention_receipt_complete": _TriggerContract(
        "identity_platforminvitationretentionreceipt",
        "identity_page10_retention_receipt_complete()",
        _ROW_AFTER_INSERT,
        deferrable=True,
        initially_deferred=True,
    ),
    "identity_page10_retained_account_write": _TriggerContract(
        "identity_account",
        "identity_page10_retained_account_guard()",
        _ROW_BEFORE_UPDATE_DELETE,
    ),
    "identity_page10_retained_challenge_write": _TriggerContract(
        "identity_identitychallenge",
        "identity_page10_retained_challenge_guard()",
        _ROW_BEFORE_INSERT_UPDATE_DELETE,
    ),
    "identity_page10_retained_group_membership_write": _TriggerContract(
        "identity_account_groups",
        "identity_page10_retained_membership_guard()",
        _ROW_BEFORE_INSERT_UPDATE,
    ),
    "identity_page10_retained_permission_membership_write": _TriggerContract(
        "identity_account_user_permissions",
        "identity_page10_retained_membership_guard()",
        _ROW_BEFORE_INSERT_UPDATE,
    ),
    "identity_page10_retained_delivery_insert": _TriggerContract(
        "identity_platformidentitydelivery",
        "identity_page10_retained_delivery_insert_guard()",
        _ROW_BEFORE_INSERT,
    ),
    "identity_page10_retained_attempt_insert": _TriggerContract(
        "identity_platformidentitydeliveryattempt",
        "identity_page10_retained_delivery_insert_guard()",
        _ROW_BEFORE_INSERT,
    ),
    "identity_page10_retained_late_outcome_insert": _TriggerContract(
        "identity_platformidentitydeliverylateoutcome",
        "identity_page10_retained_delivery_insert_guard()",
        _ROW_BEFORE_INSERT,
    ),
    "identity_page10_retention_assessment_write": _TriggerContract(
        "identity_platforminvitationretentionassessment",
        "identity_page10_retention_assessment_guard()",
        _ROW_BEFORE_INSERT_UPDATE_DELETE,
    ),
    "identity_page10_retention_assessment_no_truncate": _TriggerContract(
        "identity_platforminvitationretentionassessment",
        "identity_page10_retention_assessment_guard()",
        _STATEMENT_BEFORE_TRUNCATE,
    ),
    "identity_page10_retention_policy_strict_time": _TriggerContract(
        "identity_platforminvitationretentionpolicycontrol",
        "identity_page10_retention_strict_time_guard()",
        _ROW_BEFORE_INSERT_UPDATE,
    ),
    "identity_page10_retention_hold_strict_time": _TriggerContract(
        "identity_platforminvitationretentionhold",
        "identity_page10_retention_strict_time_guard()",
        _ROW_BEFORE_INSERT_UPDATE,
    ),
    "identity_page10_retention_receipt_strict_time": _TriggerContract(
        "identity_platforminvitationretentionreceipt",
        "identity_page10_retention_strict_time_guard()",
        _ROW_BEFORE_INSERT,
    ),
    "identity_page10_retention_v8_hold_source_complete": _TriggerContract(
        "identity_platforminvitationretentionhold",
        "identity_page10_retention_v8_hold_source_complete()",
        _ROW_AFTER_INSERT_UPDATE,
        deferrable=True,
        initially_deferred=True,
    ),
    "identity_page10_retention_v8_receipt_complete": _TriggerContract(
        "identity_platforminvitationretentionreceipt",
        "identity_page10_retention_v8_receipt_complete()",
        _ROW_AFTER_INSERT,
        deferrable=True,
        initially_deferred=True,
    ),
}

_FUNCTION_DEFINITION_SHA256: Final[dict[str, str]] = {
    "identity_page10_account_complete()": (
        "655af7fa27798342f6be0980a66c6c48540847d29e64dc397f876b7034bcaf1c"
    ),
    "identity_page10_account_inventory_bump()": (
        "9b4cbd4b1fb3745f09e9d155a7074d596a10d794b886c68adc8d1b2b9426b598"
    ),
    "identity_page10_append_only_guard()": (
        "b1c74de5612d0d3ae8cd2be7f1482d99260036a84a0bcff84281e4938a0f2338"
    ),
    "identity_page10_assert_invitation(uuid)": (
        "da862f7fa3f46d4867ce9dcb1e6adb763e582a5c52a25127ee3f2d24f303750e"
    ),
    "identity_page10_attempt_guard()": (
        "f6838ec5b576c677beef6cac0bab0c973652c48b5dac8d2894940ab9d58d1fea"
    ),
    "identity_page10_challenge_complete()": (
        "06de3ba35c2011ab4d35c56b2f3108854adb0153cdd63a170c606763f78ffe3c"
    ),
    "identity_page10_challenge_guard()": (
        "8ceabdbe6d57a73de63e8c3416f6e47d700a3b83f81a07b6fb5be99c756bc8ec"
    ),
    "identity_page10_delivery_guard()": (
        "22938d77a78c59fc6d471b3c87adf49a73fc99a78d40363ff844dcaa11df2d2b"
    ),
    "identity_page10_inventory_guard()": (
        "d3a809e89546dcc4e0f80335de0f6f4202ca66d402749443df4058a200437f3e"
    ),
    "identity_page10_invitation_complete()": (
        "3cb167804a36218c170f008135881f23ce1fe3e796ce026e2db93aed67fad503"
    ),
    "identity_page10_invitation_guard()": (
        "b86d32cd064090da44c38745995ed82c07eb46178c5aa5a064050294ec2145de"
    ),
    "identity_page10_protected_guard()": (
        "b41997555c1bca69879a849e282a49f3381ab14fe9af81f56560c5f3eaf2d896"
    ),
    "identity_page10_receipt_guard()": (
        "4af7ea83f5c3c5690236739aacf2dad65ea95952424c8b0f6afca3ddc24a74f9"
    ),
    "identity_page10_transition_complete()": (
        "035a9095d7607a1f6186927aee7c8bc9095459694b93926f84def94adbd6fb55"
    ),
    "identity_page10_transition_guard()": (
        "eb38e5c19a18d90620ed84643492badfc9b0100a4c5c9476b20019cb19fdb8a0"
    ),
    "identity_page10_delivery_version_guard()": (
        "ee2315598db3cdffe0f4942755dedb19be989a06055b1a6f3b34252f18ca329d"
    ),
    "identity_page10_reconcile_receipt_guard()": (
        "ba8b85ee396d1b995ab3368d6ef6b0914ec07a85edbe73c987fabf560342fc7c"
    ),
    "identity_page10_token_digest_key_guard()": (
        "a01c06bc1c8f05f90e7f018d7507d986534fe27550e0ba061230713d7219e4e4"
    ),
    "identity_page10_hardened_assert_delivery(uuid)": (
        "4ad556f193a78969a23c57a51f253fdceed6a820add3ffc96be1997988b43f71"
    ),
    "identity_page10_hardened_assert_reconciliation_receipt(uuid)": (
        "4ab78308c54dd17599900dc486ac19faa51d86e835afeec9af2398e3a8d5c74c"
    ),
    "identity_page10_hardened_assert_transition(uuid, bigint)": (
        "53ab1c9ac609780c81a44afad583897499e0e7e0bc9915f6c6b7d220f23fbc43"
    ),
    "identity_page10_hardened_attempt_guard()": (
        "97c664b59d6ff4c41f3c8f54d99b564c8e324d66b65c2f50d84b45473ea4b509"
    ),
    "identity_page10_hardened_challenge_guard()": (
        "52f9792edb07ab337f4831bdda8ac8ba066f12cda14e5db27a142c9293fd6b9c"
    ),
    "identity_page10_hardened_delivery_child_complete()": (
        "351c94fa36a7c907888071c300b47acd606b4af543e9b2cbd7f95a0ebd0f9263"
    ),
    "identity_page10_hardened_delivery_complete()": (
        "71dd38719e700fe368ea50bbe3ae43e6fbd1da7ef5842dd4d828dca441562ae0"
    ),
    "identity_page10_hardened_delivery_guard()": (
        "5cb4aba5fce7d44df250cdd6d1494d24062b9e48c4fa8a0be80eacfe1e0f3059"
    ),
    "identity_page10_hardened_late_outcome_guard()": (
        "8404a82ee6bd785f3ee9b84dbd054d2ecfe34aa660701db372fc0f2a061dc282"
    ),
    "identity_page10_hardened_receipt_guard()": (
        "da925d6aa2935cf24d22c2c10cf7a518f4968b23118f876cb95bd45a5c182d0a"
    ),
    "identity_page10_hardened_receipt_complete()": (
        "7e691d6c38ad47dad95c8d5777a42b2344839a89ccd8b3cf330970b455170035"
    ),
    "identity_page10_hardened_reconcile_audit_complete()": (
        "eacf0cf1a8091f07f4be4a86ec7e035306c1618f017caa967349884da8cdae35"
    ),
    "identity_page10_hardened_reconcile_guard()": (
        "cc21f934a67baac3c4cd893899bc770cbf2da15beff0faf16f21ae41c37ee7b5"
    ),
    "identity_page10_hardened_transition_complete()": (
        "71ec24f37aa5532b3078ccc74e1eb5960f34f92c9ffdf9c6e2f6fc8e2a660d3f"
    ),
    "identity_page10_hardened_transition_guard()": (
        "4d6989a8b9d3dbb32a5bf8af97b1611d57e2ff3fe868d6efbdfe1e6c2b8e8275"
    ),
    "identity_page10_invitation_origin_complete()": (
        "0e6d22111447b6f5c6d9c119e9d8c856414e50fd43926fbe15250fbf28c5112e"
    ),
    "identity_page10_retention_hold_complete()": (
        "19a4bb2b089d83e3e69344a40ceacbfdf6a4bc0ef724ca0c092f859259c9690c"
    ),
    "identity_page10_retention_hold_guard()": (
        "ca7422dad7b3401d5353c7042681532e5a1a502ea5e67d36174ac38644a42f63"
    ),
    "identity_page10_retention_policy_control_guard()": (
        "fecce2fc0266dbbc9f69e1b8aeaacbc8a2d532595adaeb120a7c44038b136811"
    ),
    "identity_page10_retention_receipt_complete()": (
        "58db38c80a63f456b719a577786723da35a8605911b6465290355413ac8e6afd"
    ),
    "identity_page10_retention_receipt_guard()": (
        "1b3ad8f19fb48b1b00bd48304591738d5fb602b4e39d896465e3537fe317a2bc"
    ),
    "identity_page10_retention_account_is_unrelated(uuid, uuid)": (
        "f0e8af299b1912ccf1c3f48cb7bf845dbf26937cb99182217c82f4fc5bf35678"
    ),
    "identity_page10_retained_account_guard()": (
        "173ee8566319f41ee92db1a3ec1d631bf0d30d02309422f1f705cafad828a36f"
    ),
    "identity_page10_retained_challenge_guard()": (
        "c90801ee01b9d926c0c18a1c287d3a91e575b8b3c4a3b55d5a4f0fbf7cc8730b"
    ),
    "identity_page10_retained_delivery_insert_guard()": (
        "350d18f9b37a6831ba2bed590758b6dd40a7993015741a6bebc49a45b400ffaa"
    ),
    "identity_page10_retained_membership_guard()": (
        "45d9e4990f949a6cce15d5e8cc53d323b181a68f21e1041b31041da3b342c665"
    ),
    "identity_page10_retention_assessment_guard()": (
        "a6670dbd5120bb473765bcff144382112b08c319014492c91618e712ff219606"
    ),
    "identity_page10_retention_provider_child_guard()": (
        "952fe6fc154662ece481d0b53529697ba52fb41d0e090d3fa5d3a180a6b465fb"
    ),
    "identity_page10_retention_provider_delivery_guard()": (
        "90a14ae667c1c655905a7f9345187ae09210c8d3ebea1990de955d844fe2159a"
    ),
    "identity_page10_retention_strict_time_guard()": (
        "721c30437e53d726ba9d91a48a9499598c1ee5daa5efb6b9fb8c5038608a53ca"
    ),
    "identity_page10_retention_v8_hold_source_complete()": (
        "c37d9fb830fb9db686f6fca7c22bf24f4129da76ab3e468de1fa7cb8f911e349"
    ),
    "identity_page10_retention_v8_receipt_complete()": (
        "9ee7a51d28b259183243d85e49bca5ddec26f8c8e993aa803f1853e06b2899b6"
    ),
}

_REVIEWED_INTEGRITY_RELATIONS: Final = (
    "identity_account",
    "identity_identitychallenge",
    "identity_platformaccountinventorycontrol",
    "identity_platformaccountinvitation",
    "identity_platformaccountinvitationtransition",
    "identity_platformaccountinvitationcommandreceipt",
    "identity_platformidentitydelivery",
    "identity_platformidentitydeliveryattempt",
)

_RECONCILIATION_RELATIONS: Final = (
    "identity_platformidentitydeliverylateoutcome",
    "identity_platformidentitydeliveryreconciliationreceipt",
)

_SCHEDULER_HEARTBEAT_RELATIONS: Final = ("identity_platforminvitationschedulerrun",)

_RETENTION_RELATIONS: Final = (
    "identity_platforminvitationretentionpolicycontrol",
    "identity_platforminvitationretentionhold",
    "identity_platforminvitationretentionreceipt",
    "identity_platforminvitationretentionassessment",
)

_INDEX_CONTRACTS: Final[dict[str, _IndexContract]] = {
    "id_account_email_prefix_idx": _IndexContract(
        "identity_account",
        ("upper(email::text)",),
        ("pg_catalog.varchar_pattern_ops",),
        (0,),
        has_expressions=True,
    ),
    "id_account_handle_prefix_idx": _IndexContract(
        "identity_account",
        ("upper(login_handle::text)",),
        ("pg_catalog.varchar_pattern_ops",),
        (0,),
        has_expressions=True,
    ),
    "id_account_name_prefix_idx": _IndexContract(
        "identity_account",
        ("upper(display_name::text)",),
        ("pg_catalog.varchar_pattern_ops",),
        (0,),
        has_expressions=True,
    ),
    "identity_account_joined_idx": _IndexContract(
        "identity_account",
        ("date_joined", "id"),
        ("pg_catalog.timestamptz_ops", "pg_catalog.uuid_ops"),
        (0, 0),
    ),
    "id_invite_status_expiry_idx": _IndexContract(
        "identity_platformaccountinvitation",
        ("status", "expires_at", "id"),
        (
            "pg_catalog.text_ops",
            "pg_catalog.timestamptz_ops",
            "pg_catalog.uuid_ops",
        ),
        (0, 0, 0),
    ),
    "id_inv_retention_due_idx": _IndexContract(
        "identity_platformaccountinvitation",
        ("status", "last_transition_at", "id"),
        (
            "pg_catalog.text_ops",
            "pg_catalog.timestamptz_ops",
            "pg_catalog.uuid_ops",
        ),
        (0, 0, 0),
    ),
    "identity_delivery_claim_idx": _IndexContract(
        "identity_platformidentitydelivery",
        ("status", "available_at", "id"),
        (
            "pg_catalog.text_ops",
            "pg_catalog.timestamptz_ops",
            "pg_catalog.uuid_ops",
        ),
        (0, 0, 0),
    ),
    "identity_delivery_lease_idx": _IndexContract(
        "identity_platformidentitydelivery",
        ("status", "lease_expires_at", "id"),
        (
            "pg_catalog.text_ops",
            "pg_catalog.timestamptz_ops",
            "pg_catalog.uuid_ops",
        ),
        (0, 0, 0),
    ),
    "id_delivery_reconcile_idx": _IndexContract(
        "identity_platformidentitydelivery",
        ("reconciliation_state", "created_at", "id"),
        (
            "pg_catalog.text_ops",
            "pg_catalog.timestamptz_ops",
            "pg_catalog.uuid_ops",
        ),
        (0, 0, 0),
    ),
    "id_inv_scheduler_run_idx": _IndexContract(
        "identity_platforminvitationschedulerrun",
        ("kind", "ran_at", "id"),
        (
            "pg_catalog.text_ops",
            "pg_catalog.timestamptz_ops",
            "pg_catalog.uuid_ops",
        ),
        (0, 3, 3),
    ),
    "identity_invitation_result_receipt_unique": _IndexContract(
        "identity_platformaccountinvitationcommandreceipt",
        ("invitation_id", "result_version"),
        ("pg_catalog.uuid_ops", "pg_catalog.int8_ops"),
        (0, 0),
        unique=True,
        constraint=("u", False, False, True),
    ),
    "identity_one_invitation_per_account": _IndexContract(
        "identity_platformaccountinvitation",
        ("account_id",),
        ("pg_catalog.uuid_ops",),
        (0,),
        unique=True,
        constraint=("u", False, False, True),
    ),
    "identity_platforminvitationretentionassessmen_invitation_id_key": (
        _IndexContract(
            "identity_platforminvitationretentionassessment",
            ("invitation_id",),
            ("pg_catalog.uuid_ops",),
            (0,),
            unique=True,
            constraint=("u", False, False, True),
        )
    ),
    "id_inv_ret_assess_code_idx": _IndexContract(
        "identity_platforminvitationretentionassessment",
        ("safe_result_code", "assessed_at", "id"),
        (
            "pg_catalog.text_ops",
            "pg_catalog.timestamptz_ops",
            "pg_catalog.uuid_ops",
        ),
        (0, 0, 0),
    ),
    "identity_reconcile_result_receipt_unique": _IndexContract(
        "identity_platformidentitydeliveryreconciliationreceipt",
        ("delivery_id", "result_version"),
        ("pg_catalog.uuid_ops", "pg_catalog.int8_ops"),
        (0, 0),
        unique=True,
        constraint=("u", False, False, True),
    ),
    "audit_identity_reconcile_retry_unique": _IndexContract(
        "audit_auditevent",
        ("principal_id", "idempotency_key_hash"),
        ("pg_catalog.uuid_ops", "pg_catalog.text_ops"),
        (0, 0),
        unique=True,
        predicate=(
            "capability_code::text = "
            "'identity.reconcile_account_invitation_delivery'::text AND "
            "operation::text = "
            "'identity.account_invitation.delivery_reconcile'::text AND "
            "NOT idempotency_key_hash::text = ''::text"
        ),
    ),
}


def _function_definition_fingerprint(definition: tuple[object, ...]) -> str:
    """Hash behavior-bearing function fields without releasing SQL bodies.

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


def _migration_is_applied(
    cursor: CursorWrapper,
    migration: tuple[str, str],
) -> bool:
    """Return exact recorder evidence for one migration without row data.

    Parameters
    ----------
    cursor : CursorWrapper
        The cursor evaluated by the fail-closed readiness check.
    migration : tuple[str, str]
        The migration evaluated while migration is applied.

    Returns
    -------
    bool
        `True` when Return exact recorder evidence for one migration without row
        data; otherwise `False`.
    """
    cursor.execute(
        """
        SELECT count(*) = 1
          FROM public.django_migrations
         WHERE app = %s AND name = %s
        """,
        migration,
    )
    return bool(cursor.fetchone()[0])


def inspect_platform_invitation_additive_catalog() -> PlatformInvitationAdditiveCatalog:
    """Inspect reviewed 0011 evidence and additive 0012 schema without row data.

    Returns
    -------
    PlatformInvitationAdditiveCatalog
        The PlatformInvitationAdditiveCatalog produced by inspect platform
        invitation additive catalog.
    """
    expected_function_identities = tuple(_FUNCTION_DEFINITION_SHA256)
    expected_index_names = tuple(_INDEX_CONTRACTS)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_catalog.current_setting('server_version_num')::integer / 10000"
        )
        server_version_supported = (
            cast("int", cursor.fetchone()[0]) == _SUPPORTED_POSTGRESQL_SERVER_MAJOR
        )
        cursor.execute("SELECT pg_catalog.current_schemas(TRUE)")
        effective_schemas = tuple(cast("Iterable[str]", cursor.fetchone()[0]))
        schema_order_safe = effective_schemas[:2] == (
            "pg_catalog",
            _SUPPORTED_DATABASE_SCHEMA,
        )

        migration_applied = _migration_is_applied(
            cursor,
            _REVIEWED_INTEGRITY_MIGRATION,
        )
        reconciliation_migration_applied = _migration_is_applied(
            cursor,
            _RECONCILIATION_SCHEMA_MIGRATION,
        )
        digest_key_migration_applied = _migration_is_applied(
            cursor,
            _DIGEST_KEY_SCHEMA_MIGRATION,
        )
        hardened_integrity_migration_applied = _migration_is_applied(
            cursor,
            _HARDENED_INTEGRITY_MIGRATION,
        )
        audit_cardinality_migration_applied = _migration_is_applied(
            cursor,
            _AUDIT_CARDINALITY_MIGRATION,
        )
        scheduler_heartbeat_migration_applied = _migration_is_applied(
            cursor,
            _SCHEDULER_HEARTBEAT_MIGRATION,
        )
        prefix_index_migration_applied = _migration_is_applied(
            cursor,
            _PREFIX_INDEX_MIGRATION,
        )
        retention_audit_cardinality_migration_applied = _migration_is_applied(
            cursor,
            _RETENTION_AUDIT_CARDINALITY_MIGRATION,
        )
        retention_workflow_migration_applied = _migration_is_applied(
            cursor,
            _RETENTION_WORKFLOW_MIGRATION,
        )

        cursor.execute(
            """
            SELECT count(*) = 1
              FROM pg_catalog.pg_attribute AS attribute
              JOIN pg_catalog.pg_class AS relation
                ON relation.oid = attribute.attrelid
              JOIN pg_catalog.pg_namespace AS namespace
                ON namespace.oid = relation.relnamespace
              LEFT JOIN pg_catalog.pg_attrdef AS default_record
                ON default_record.adrelid = relation.oid
               AND default_record.adnum = attribute.attnum
             WHERE namespace.nspname = 'public'
               AND relation.relname = 'identity_identitychallenge'
               AND attribute.attname = 'token_digest_key_id'
               AND NOT attribute.attisdropped
               AND attribute.atttypid = 'pg_catalog.varchar'::regtype
               AND attribute.atttypmod = 68
               AND attribute.attnotnull
               AND default_record.oid IS NULL
            """
        )
        digest_key_column_installed = bool(cursor.fetchone()[0])

        cursor.execute(
            """
            SELECT required.identity,
                   pg_catalog.to_regclass('public.' || required.identity) IS NOT NULL
              FROM pg_catalog.unnest(%s::text[]) AS required(identity)
             ORDER BY required.identity
            """,
            [
                [
                    *_REVIEWED_INTEGRITY_RELATIONS,
                    *_RECONCILIATION_RELATIONS,
                    *_SCHEDULER_HEARTBEAT_RELATIONS,
                    *_RETENTION_RELATIONS,
                ]
            ],
        )
        relation_rows = cursor.fetchall()
        installed_relations = {str(row[0]) for row in relation_rows if bool(row[1])}
        relations_installed = set(_REVIEWED_INTEGRITY_RELATIONS) <= installed_relations
        reconciliation_relations_installed = (
            set(_RECONCILIATION_RELATIONS) <= installed_relations
        )
        scheduler_heartbeat_relation_installed = (
            set(_SCHEDULER_HEARTBEAT_RELATIONS) <= installed_relations
        )
        retention_relations_installed = set(_RETENTION_RELATIONS) <= installed_relations

        cursor.execute(
            """
            SELECT required.identity,
                   procedure.oid IS NOT NULL,
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
                   pg_catalog.pg_get_function_result(procedure.oid),
                   NOT EXISTS (
                       SELECT 1
                         FROM pg_catalog.aclexplode(
                             COALESCE(
                                 procedure.proacl,
                                 pg_catalog.acldefault('f', procedure.proowner)
                             )
                         ) AS privilege
                        WHERE privilege.grantee = 0
                          AND privilege.privilege_type = 'EXECUTE'
                   )
              FROM pg_catalog.unnest(%s::text[]) AS required(identity)
              LEFT JOIN pg_catalog.pg_proc AS procedure
                ON procedure.oid = pg_catalog.to_regprocedure(
                    'public.' || required.identity
                )
              LEFT JOIN pg_catalog.pg_language AS language
                ON language.oid = procedure.prolang
             ORDER BY required.identity
            """,
            [list(expected_function_identities)],
        )
        function_rows = cursor.fetchall()
        cursor.execute(
            """
            SELECT procedure.proname || '(' ||
                   pg_catalog.oidvectortypes(procedure.proargtypes) || ')'
              FROM pg_catalog.pg_proc AS procedure
              JOIN pg_catalog.pg_namespace AS namespace
                ON namespace.oid = procedure.pronamespace
             WHERE namespace.nspname = 'public'
               AND procedure.proname LIKE 'identity_page10_%'
             ORDER BY 1
            """
        )
        installed_function_identities = {str(row[0]) for row in cursor.fetchall()}

        cursor.execute(
            """
            SELECT trigger.tgname::text,
                   relation.relname::text,
                   procedure.proname || '(' ||
                       pg_catalog.oidvectortypes(procedure.proargtypes) || ')',
                   trigger.tgtype,
                   trigger.tgenabled,
                   trigger.tgdeferrable,
                   trigger.tginitdeferred,
                   CASE WHEN trigger.tgqual IS NULL THEN NULL ELSE
                       pg_catalog.encode(
                           pg_catalog.sha256(
                               pg_catalog.convert_to(trigger.tgqual::text, 'UTF8')
                           ),
                           'hex'
                       )
                   END,
                   trigger.tgnargs,
                   ARRAY(
                       SELECT attribute.attname::text
                         FROM pg_catalog.unnest(trigger.tgattr::smallint[])
                              WITH ORDINALITY AS selected(attnum, position)
                         JOIN pg_catalog.pg_attribute AS attribute
                           ON attribute.attrelid = trigger.tgrelid
                          AND attribute.attnum = selected.attnum
                        ORDER BY selected.position
                   )
              FROM pg_catalog.pg_trigger AS trigger
              JOIN pg_catalog.pg_class AS relation
                ON relation.oid = trigger.tgrelid
              JOIN pg_catalog.pg_namespace AS relation_namespace
                ON relation_namespace.oid = relation.relnamespace
              JOIN pg_catalog.pg_proc AS procedure
                ON procedure.oid = trigger.tgfoid
              JOIN pg_catalog.pg_namespace AS procedure_namespace
                ON procedure_namespace.oid = procedure.pronamespace
             WHERE NOT trigger.tgisinternal
               AND relation_namespace.nspname = 'public'
               AND procedure_namespace.nspname = 'public'
               AND trigger.tgname LIKE 'identity_page10_%'
             ORDER BY trigger.tgname
            """
        )
        trigger_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT index_relation.relname::text,
                   table_relation.relname::text,
                   access_method.amname::text,
                   index_record.indisunique,
                   index_record.indisvalid,
                   index_record.indisready,
                   index_record.indislive,
                   index_record.indnkeyatts,
                   index_record.indnatts,
                   index_record.indexprs IS NULL,
                   pg_catalog.pg_get_expr(
                       index_record.indpred,
                       index_record.indrelid,
                       TRUE
                   ),
                   constraint_record.contype::text,
                   constraint_record.condeferrable,
                   constraint_record.condeferred,
                   constraint_record.convalidated,
                   ARRAY(
                       SELECT opclass_namespace.nspname::text || '.' ||
                              opclass.opcname::text
                         FROM pg_catalog.unnest(
                                  index_record.indclass::oid[]
                              ) WITH ORDINALITY AS selected(opclass_oid, position)
                         JOIN pg_catalog.pg_opclass AS opclass
                           ON opclass.oid = selected.opclass_oid
                         JOIN pg_catalog.pg_namespace AS opclass_namespace
                           ON opclass_namespace.oid = opclass.opcnamespace
                        ORDER BY selected.position
                   ),
                   index_record.indoption::smallint[],
                   ARRAY(
                       SELECT pg_catalog.pg_get_indexdef(
                           index_record.indexrelid,
                           key_position,
                           TRUE
                       )
                         FROM pg_catalog.generate_series(
                             1,
                             index_record.indnkeyatts
                         ) AS key_position
                        ORDER BY key_position
                   )
              FROM pg_catalog.pg_index AS index_record
              JOIN pg_catalog.pg_class AS index_relation
                ON index_relation.oid = index_record.indexrelid
              JOIN pg_catalog.pg_namespace AS index_namespace
                ON index_namespace.oid = index_relation.relnamespace
              JOIN pg_catalog.pg_class AS table_relation
                ON table_relation.oid = index_record.indrelid
              JOIN pg_catalog.pg_namespace AS table_namespace
                ON table_namespace.oid = table_relation.relnamespace
              JOIN pg_catalog.pg_am AS access_method
                ON access_method.oid = index_relation.relam
              LEFT JOIN pg_catalog.pg_constraint AS constraint_record
                ON constraint_record.conindid = index_record.indexrelid
               AND constraint_record.contype = 'u'
             WHERE index_namespace.nspname = 'public'
               AND table_namespace.nspname = 'public'
               AND index_relation.relname = ANY(%s::text[])
             ORDER BY index_relation.relname
            """,
            [list(expected_index_names)],
        )
        index_rows = cursor.fetchall()

    function_hashes = {
        str(row[0]): _function_definition_fingerprint(tuple(row[2:13]))
        for row in function_rows
        if bool(row[1])
    }
    functions_fingerprinted = function_hashes == _FUNCTION_DEFINITION_SHA256
    function_execute_boundary_closed = len(function_rows) == len(
        expected_function_identities
    ) and all(bool(row[1]) and bool(row[13]) for row in function_rows)

    trigger_counts = Counter(str(row[0]) for row in trigger_rows)
    reviewed_triggers = {
        str(row[0]): (*tuple(row[1:9]), tuple(row[9] or ()))
        for row in trigger_rows
        if str(row[0]) in _TRIGGER_CONTRACTS
    }
    expected_triggers = {
        name: (
            contract.table,
            contract.function,
            contract.trigger_type,
            "O",
            contract.deferrable,
            contract.initially_deferred,
            contract.when_sha256,
            0,
            contract.columns,
        )
        for name, contract in _TRIGGER_CONTRACTS.items()
    }
    triggers_attached = (
        all(trigger_counts[name] == 1 for name in _TRIGGER_CONTRACTS)
        and reviewed_triggers == expected_triggers
    )
    uncataloged_function_identities = tuple(
        sorted(installed_function_identities - set(expected_function_identities))
    )
    uncataloged_trigger_names = tuple(
        sorted(set(trigger_counts) - set(_TRIGGER_CONTRACTS))
    )

    installed_indexes = {
        str(row[0]): (
            str(row[1]),
            tuple(row[2:15]),
            tuple(row[15] or ()),
            tuple(row[16] or ()),
            tuple(row[17] or ()),
        )
        for row in index_rows
    }
    expected_indexes = {
        name: (
            contract.table,
            (
                "btree",
                contract.unique,
                True,
                True,
                True,
                len(contract.keys),
                len(contract.keys),
                not contract.has_expressions,
                contract.predicate,
                *(contract.constraint or (None, None, None, None)),
            ),
            contract.opclasses,
            contract.options,
            contract.keys,
        )
        for name, contract in _INDEX_CONTRACTS.items()
    }
    indexes_installed = installed_indexes == expected_indexes

    return PlatformInvitationAdditiveCatalog(
        server_version_supported=server_version_supported,
        schema_order_safe=schema_order_safe,
        migration_applied=migration_applied,
        relations_installed=relations_installed,
        reconciliation_migration_applied=reconciliation_migration_applied,
        reconciliation_relations_installed=reconciliation_relations_installed,
        digest_key_migration_applied=digest_key_migration_applied,
        digest_key_column_installed=digest_key_column_installed,
        hardened_integrity_migration_applied=(hardened_integrity_migration_applied),
        audit_cardinality_migration_applied=(audit_cardinality_migration_applied),
        scheduler_heartbeat_migration_applied=(scheduler_heartbeat_migration_applied),
        scheduler_heartbeat_relation_installed=(scheduler_heartbeat_relation_installed),
        prefix_index_migration_applied=prefix_index_migration_applied,
        retention_audit_cardinality_migration_applied=(
            retention_audit_cardinality_migration_applied
        ),
        retention_workflow_migration_applied=retention_workflow_migration_applied,
        retention_relations_installed=retention_relations_installed,
        functions_fingerprinted=functions_fingerprinted,
        function_execute_boundary_closed=function_execute_boundary_closed,
        triggers_attached=triggers_attached,
        indexes_installed=indexes_installed,
        uncataloged_function_identities=uncataloged_function_identities,
        uncataloged_trigger_names=uncataloged_trigger_names,
    )


def _unavailable_catalog() -> PlatformInvitationAdditiveCatalog:
    return PlatformInvitationAdditiveCatalog(
        server_version_supported=False,
        schema_order_safe=False,
        migration_applied=False,
        relations_installed=False,
        reconciliation_migration_applied=False,
        reconciliation_relations_installed=False,
        digest_key_migration_applied=False,
        digest_key_column_installed=False,
        hardened_integrity_migration_applied=False,
        audit_cardinality_migration_applied=False,
        scheduler_heartbeat_migration_applied=False,
        scheduler_heartbeat_relation_installed=False,
        prefix_index_migration_applied=False,
        retention_audit_cardinality_migration_applied=False,
        retention_workflow_migration_applied=False,
        retention_relations_installed=False,
        functions_fingerprinted=False,
        function_execute_boundary_closed=False,
        triggers_attached=False,
        indexes_installed=False,
        uncataloged_function_identities=(),
        uncataloged_trigger_names=(),
    )


def platform_invitation_additive_contract_is_ready() -> bool:
    """Return a safe boolean for the additive schema, never cutover state.

    Returns
    -------
    bool
        `True` when Return a safe boolean for the additive schema, never cutover
        state; otherwise `False`.
    """
    try:
        return inspect_platform_invitation_additive_catalog().additive_contract_ready
    except (DatabaseError, IndexError, KeyError, TypeError, ValueError):
        return False


def platform_invitation_digest_key_coverage_is_ready() -> bool:
    """Prove every live invitation digest remains reachable after rotation.

    Returns
    -------
    bool
        `True` when Prove every live invitation digest remains reachable after
        rotation; otherwise `False`.
    """
    try:
        key_ids = list(invitation_token_keyring().key_ids)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT NOT EXISTS (
                    SELECT 1
                      FROM public.identity_identitychallenge
                     WHERE purpose = 'account_invitation'
                       AND consumed_at IS NULL
                       AND invalidated_at IS NULL
                       AND NOT (token_digest_key_id = ANY(%s::varchar[]))
                )
                """,
                [key_ids],
            )
            return bool(cursor.fetchone()[0])
    except (
        DatabaseError,
        IndexError,
        InvitationTokenKeyConfigurationError,
        TypeError,
        ValueError,
    ):
        return False


def platform_invitation_runtime_contract_is_ready() -> bool:
    """Use the exact same complete gate set exposed by the operator report.

    Returns
    -------
    bool
        `True` when Use the exact same complete gate set exposed by the operator
        report; otherwise `False`.
    """
    try:
        catalog = inspect_platform_invitation_additive_catalog()
    except (DatabaseError, IndexError, KeyError, TypeError, ValueError):
        catalog = _unavailable_catalog()
    return all(_platform_invitation_production_gates(catalog).values())


def _configured_runtime_database_role_is_safe() -> bool:
    role_name = getattr(settings, "RUNTIME_DATABASE_ROLE", "")
    if not isinstance(role_name, str) or not role_name:
        return False
    try:
        from maru.authorization.database_role_safety import (  # noqa: PLC0415
            RuntimeDatabaseRoleProbeError,
            probe_runtime_database_role_safety,
        )

        return probe_runtime_database_role_safety(
            role_name=role_name
        ).target_role_is_safe
    except (DatabaseError, RuntimeDatabaseRoleProbeError):
        return False


def platform_invitation_delivery_heartbeat_is_ready() -> bool:
    """Require one fresh successful worker run and a bounded global backlog.

    Returns
    -------
    bool
        `True` when Require one fresh successful worker run and a bounded global
        backlog; otherwise `False`.
    """
    try:
        now = _database_now()
        heartbeat = (
            PlatformInvitationSchedulerRun.objects.filter(
                kind=PlatformInvitationSchedulerRun.Kind.DELIVERY,
            )
            .order_by("-ran_at", "-id")
            .values(
                "generation",
                "ran_at",
                "private_key_coverage_complete",
            )
            .first()
        )
        if (
            heartbeat is None
            or heartbeat["generation"]
            != PlatformInvitationSchedulerRun.Generation.DELIVERY_V1
            or heartbeat["private_key_coverage_complete"] is not True
            or heartbeat["ran_at"] > now
            or heartbeat["ran_at"] < now - _DELIVERY_HEARTBEAT_MAX_AGE
        ):
            return False
        from maru.identity.invitation_delivery import (  # noqa: PLC0415
            platform_identity_delivery_backlog_snapshot,
        )

        backlog = platform_identity_delivery_backlog_snapshot(at=now)
        return backlog.oldest_eligible_at is None or (
            backlog.oldest_eligible_at >= now - _DELIVERY_BACKLOG_MAX_AGE
        )
    except (DatabaseError, KeyError, TypeError, ValueError):
        return False


def platform_invitation_expiry_heartbeat_is_ready() -> bool:
    """Require one fresh successful expiry run and no overdue old backlog.

    Returns
    -------
    bool
        `True` when Require one fresh successful expiry run and no overdue old
        backlog; otherwise `False`.
    """
    try:
        now = _database_now()
        heartbeat = (
            PlatformInvitationSchedulerRun.objects.filter(
                kind=PlatformInvitationSchedulerRun.Kind.EXPIRY,
            )
            .order_by("-ran_at", "-id")
            .values("generation", "ran_at", "private_key_coverage_complete")
            .first()
        )
        if (
            heartbeat is None
            or heartbeat["generation"]
            != PlatformInvitationSchedulerRun.Generation.EXPIRY_V1
            or heartbeat["private_key_coverage_complete"] is not False
            or heartbeat["ran_at"] > now
            or heartbeat["ran_at"] < now - _EXPIRY_HEARTBEAT_MAX_AGE
        ):
            return False
        oldest_overdue = (
            PlatformAccountInvitation.objects.filter(
                status=PlatformAccountInvitation.Status.PENDING,
                expires_at__lte=now,
            )
            .order_by("expires_at", "id")
            .values_list("expires_at", flat=True)
            .first()
        )
        return oldest_overdue is None or (
            oldest_overdue >= now - _EXPIRY_BACKLOG_MAX_AGE
        )
    except (DatabaseError, KeyError, TypeError, ValueError):
        return False


def platform_invitation_retention_heartbeat_is_ready() -> bool:
    """Require the approved policy, fresh worker proof, and bounded backlog.

    Returns
    -------
    bool
        `True` when Require the approved policy, fresh worker proof, and bounded
        backlog; otherwise `False`.
    """
    try:
        policy = configured_invitation_retention_policy()
        if (
            not invitation_retention_policy_control_is_ready()
            or not terminal_invitation_payloads_are_destroyed()
        ):
            return False
        now = _database_now()
        heartbeat = (
            PlatformInvitationSchedulerRun.objects.filter(
                kind=PlatformInvitationSchedulerRun.Kind.RETENTION,
            )
            .order_by("-ran_at", "-id")
            .values(
                "generation",
                "ran_at",
                "private_key_coverage_complete",
                "policy_digest",
            )
            .first()
        )
        if (
            heartbeat is None
            or heartbeat["generation"]
            != PlatformInvitationSchedulerRun.Generation.RETENTION_V2
            or heartbeat["private_key_coverage_complete"] is not False
            or heartbeat["policy_digest"] != policy.digest
            or heartbeat["ran_at"] > now
            or heartbeat["ran_at"] < now - _RETENTION_HEARTBEAT_MAX_AGE
        ):
            return False
        cutoff = now - timedelta(days=policy.period_days)
        oldest_trigger = (
            PlatformAccountInvitation.objects.filter(
                status__in=(
                    PlatformAccountInvitation.Status.REVOKED,
                    PlatformAccountInvitation.Status.EXPIRED,
                ),
                last_transition_at__lte=cutoff,
                retention_receipt__isnull=True,
            )
            .exclude(retention_holds__active=True)
            .order_by("last_transition_at", "id")
            .values_list("last_transition_at", flat=True)
            .first()
        )
        if oldest_trigger is None:
            return True
        oldest_due_at = oldest_trigger + timedelta(days=policy.period_days)
        return oldest_due_at >= now - _RETENTION_BACKLOG_MAX_AGE
    except (
        DatabaseError,
        InvitationRetentionConfigurationError,
        KeyError,
        TypeError,
        ValueError,
    ):
        return False


def platform_account_prefix_query_plan_is_ready() -> bool:
    """Prove the deployed Django predicate is backed by all three indexes.

    Returns
    -------
    bool
        `True` when Prove the deployed Django predicate is backed by all three
        indexes; otherwise `False`.
    """
    sql = """
        EXPLAIN (FORMAT JSON, COSTS FALSE)
        SELECT id
          FROM public.identity_account
         WHERE UPPER(email::text) LIKE UPPER(%s)
            OR UPPER(login_handle::text) LIKE UPPER(%s)
            OR UPPER(display_name::text) LIKE UPPER(%s)
         ORDER BY date_joined, id
         LIMIT 101
    """
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET LOCAL enable_seqscan = off")
            cursor.execute("SET LOCAL enable_indexscan = off")
            cursor.execute(sql, ["zz%", "zz%", "zz%"])
            row = cursor.fetchone()
        if row is None or not isinstance(row[0], list) or not row[0]:
            return False
        root = row[0][0].get("Plan")
        if not isinstance(root, dict):
            return False
        index_names: set[str] = set()
        node_types: set[str] = set()
        pending: list[dict[str, object]] = [root]
        while pending:
            node = pending.pop()
            node_type = node.get("Node Type")
            if isinstance(node_type, str):
                node_types.add(node_type)
            index_name = node.get("Index Name")
            if isinstance(index_name, str):
                index_names.add(index_name)
            children = node.get("Plans", [])
            if not isinstance(children, list):
                return False
            pending.extend(child for child in children if isinstance(child, dict))
    except (DatabaseError, KeyError, TypeError, ValueError):
        return False
    return index_names >= _ACCOUNT_PREFIX_INDEX_NAMES and "Seq Scan" not in node_types


def _platform_invitation_production_gates(
    catalog: PlatformInvitationAdditiveCatalog,
) -> dict[str, bool]:
    return {
        "additive_schema": catalog.additive_contract_ready,
        "runtime_database_role": _configured_runtime_database_role_is_safe(),
        "public_encryption_key": invitation_encryption_is_ready(),
        "versioned_token_digest_keys": invitation_token_keys_are_ready(),
        "live_token_digest_key_coverage": (
            platform_invitation_digest_key_coverage_is_ready()
        ),
        "normalized_invitation_origin": (
            normalized_https_origin(getattr(settings, "MARU_PUBLIC_BASE_URL", None))
            is not None
        ),
        "delivery_worker_key_and_heartbeat": (
            platform_invitation_delivery_heartbeat_is_ready()
        ),
        "expiry_scheduler_heartbeat": (platform_invitation_expiry_heartbeat_is_ready()),
        "invitation_retention_policy_and_job": (
            platform_invitation_retention_heartbeat_is_ready()
        ),
        "stopped_writer_generation": (
            PAGE10_INVITATION_STOPPED_WRITER_GENERATION is not None
        ),
        "account_prefix_search_query_plan": (
            platform_account_prefix_query_plan_is_ready()
        ),
    }


def build_platform_invitation_readiness_report() -> dict[str, object]:
    """Build a stable, data-free report for additive and production gates.

    Returns
    -------
    dict[str, object]
        A mapping containing the resolved build platform invitation readiness
        report data.
    """
    try:
        catalog = inspect_platform_invitation_additive_catalog()
    except (DatabaseError, IndexError, KeyError, TypeError, ValueError):
        catalog = _unavailable_catalog()
    additive_gates = {
        "postgresql_server_major": catalog.server_version_supported,
        "effective_schema_order": catalog.schema_order_safe,
        "reviewed_integrity_migration": catalog.migration_applied,
        "reviewed_integrity_relations": catalog.relations_installed,
        "reconciliation_schema_migration": (catalog.reconciliation_migration_applied),
        "reconciliation_relations": catalog.reconciliation_relations_installed,
        "digest_key_schema_migration": catalog.digest_key_migration_applied,
        "digest_key_column": catalog.digest_key_column_installed,
        "hardened_integrity_migration": (catalog.hardened_integrity_migration_applied),
        "reconciliation_audit_cardinality_migration": (
            catalog.audit_cardinality_migration_applied
        ),
        "scheduler_heartbeat_migration": (
            catalog.scheduler_heartbeat_migration_applied
        ),
        "scheduler_heartbeat_relation": (
            catalog.scheduler_heartbeat_relation_installed
        ),
        "prefix_index_migration": catalog.prefix_index_migration_applied,
        "retention_audit_cardinality_migration": (
            catalog.retention_audit_cardinality_migration_applied
        ),
        "retention_workflow_migration": catalog.retention_workflow_migration_applied,
        "retention_relations": catalog.retention_relations_installed,
        "reviewed_function_fingerprints": catalog.functions_fingerprinted,
        "reviewed_function_execute_boundary": (
            catalog.function_execute_boundary_closed
        ),
        "reviewed_trigger_attachments": catalog.triggers_attached,
        "supporting_indexes": catalog.indexes_installed,
    }
    additive_status = "ready" if all(additive_gates.values()) else "blocked"
    production_gates = _platform_invitation_production_gates(catalog)
    return {
        "schema_generation": PAGE10_INVITATION_ADDITIVE_SCHEMA_GENERATION,
        "status": additive_status,
        "production_status": ("ready" if all(production_gates.values()) else "blocked"),
        "writer_cutover_status": (
            "active"
            if PAGE10_INVITATION_STOPPED_WRITER_GENERATION is not None
            else "inactive"
        ),
        "integrity_review_scope": {
            "reviewed_migration": ".".join(_REVIEWED_INTEGRITY_MIGRATION),
            "reconciliation_schema_migration": ".".join(
                _RECONCILIATION_SCHEMA_MIGRATION
            ),
            "digest_key_schema_migration": ".".join(_DIGEST_KEY_SCHEMA_MIGRATION),
            "hardened_integrity_migration": ".".join(_HARDENED_INTEGRITY_MIGRATION),
            "reconciliation_audit_cardinality_migration": ".".join(
                _AUDIT_CARDINALITY_MIGRATION
            ),
            "scheduler_heartbeat_migration": ".".join(_SCHEDULER_HEARTBEAT_MIGRATION),
            "prefix_index_migration": ".".join(_PREFIX_INDEX_MIGRATION),
            "retention_audit_cardinality_migration": ".".join(
                _RETENTION_AUDIT_CARDINALITY_MIGRATION
            ),
            "retention_workflow_migration": ".".join(_RETENTION_WORKFLOW_MIGRATION),
            "uncataloged_later_generation_functions": list(
                catalog.uncataloged_function_identities
            ),
            "uncataloged_later_generation_triggers": list(
                catalog.uncataloged_trigger_names
            ),
        },
        "additive_gates": {
            key: _RESOLVED if value else _UNRESOLVED
            for key, value in additive_gates.items()
        },
        "known_production_gates": {
            key: _RESOLVED if value else _UNRESOLVED
            for key, value in production_gates.items()
        },
    }


__all__ = [
    "PAGE10_INVITATION_ADDITIVE_SCHEMA_GENERATION",
    "PAGE10_INVITATION_STOPPED_WRITER_GENERATION",
    "PlatformInvitationAdditiveCatalog",
    "build_platform_invitation_readiness_report",
    "inspect_platform_invitation_additive_catalog",
    "platform_account_prefix_query_plan_is_ready",
    "platform_invitation_additive_contract_is_ready",
    "platform_invitation_delivery_heartbeat_is_ready",
    "platform_invitation_digest_key_coverage_is_ready",
    "platform_invitation_expiry_heartbeat_is_ready",
    "platform_invitation_retention_heartbeat_is_ready",
    "platform_invitation_runtime_contract_is_ready",
]
