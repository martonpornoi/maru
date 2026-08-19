"""Value-minimized mandatory audit adapter for platform identity reads."""

from __future__ import annotations

from typing import Final

from maru.audit.services import AuditRecord, append_audit
from maru.identity.invitation_commands import INVITATION_CONTRACT_VERSION
from maru.identity.invitation_queries import (
    MAX_INVITATION_DETAIL_TIMELINE_ROWS,
    PlatformAccountSensitiveReadAudit,
)

_READ_OPERATIONS: Final = frozenset(
    {
        "identity.account_inventory.read",
        "identity.account_invitation.read",
    }
)


def append_platform_account_read_audit(
    evidence: PlatformAccountSensitiveReadAudit,
) -> None:
    """Persist one allow event before a protected account label is released."""

    if evidence.operation not in _READ_OPERATIONS:
        raise ValueError("Use a supported platform account read operation.")
    if evidence.source_channel not in {"web", "api"}:
        raise ValueError("Use a supported platform-account read channel.")
    if (
        evidence.aggregate_version < 0
        or not 0 <= evidence.result_count <= MAX_INVITATION_DETAIL_TIMELINE_ROWS
    ):
        raise ValueError("The platform account read evidence is out of bounds.")
    target_type = (
        "identity.platform_account_invitation"
        if evidence.target_id is not None
        else "identity.platform_account_inventory"
    )
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=evidence.actor_id,
            principal_context_id=None,
            organization_id=None,
            event_edition_id=None,
            capability_code="identity.manage_account_invitations",
            operation=evidence.operation,
            target_type=target_type,
            target_id=evidence.target_id,
            outcome="allow",
            reason_code="platform_administration",
            correlation_id=evidence.correlation_id,
            request_id=evidence.correlation_id,
            source_channel=evidence.source_channel,
            obligations=("audit_sensitive_read",),
            changed_fields=(),
            safe_metadata={
                "contract_version": INVITATION_CONTRACT_VERSION,
                "target_count": evidence.result_count,
            },
            retention_class="identity-restricted",
        )
    )


__all__ = ["append_platform_account_read_audit"]
