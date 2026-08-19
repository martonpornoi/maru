"""One-way activation of exact authority-lineage enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.conf import settings
from django.db import connection, transaction

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.models import (
    AUTHORITY_PROVENANCE_ACTIVATION_LOCK_KEY,
    AUTHORITY_PROVENANCE_CONTRACT_VERSION,
    AuthorityProvenanceActivation,
)
from maru.authorization.policy import (
    EXACT_LINEAGE_POLICY_CONTRACT_VERSION,
    EXACT_LINEAGE_POLICY_VERSION,
)
from maru.authorization.provenance_readiness import (
    build_authority_provenance_readiness_report,
)
from maru.identity.models import Account

MAX_ACTIVATION_REASON_LENGTH = 240
MAX_SOURCE_CHANNEL_LENGTH = 40


class AuthorityProvenanceActivationError(ValueError):
    """Base class for privacy-safe activation failures."""


class ProcessesStoppedAcknowledgementRequiredError(AuthorityProvenanceActivationError):
    """Raised when the operator did not confirm the maintenance boundary."""


class AuthorityProvenanceActivationBlockedError(AuthorityProvenanceActivationError):
    """Raised when the count-only preflight is not activation-ready."""


class AuthorityProvenanceActivationVerificationError(
    AuthorityProvenanceActivationError
):
    """Raised when the durable postcondition cannot be proved."""


class AuthorityProvenanceActivationEnvironmentError(AuthorityProvenanceActivationError):
    """Raised when the release or database session cannot safely cut over."""


class AuthorityProvenanceActivationTransactionError(AuthorityProvenanceActivationError):
    """Raised when activation does not own the required transaction boundary."""


@dataclass(frozen=True, slots=True)
class AuthorityProvenanceActivationResult:
    """Identifier-minimized result suitable for an operator command.

    Attributes
    ----------
    activated
        The activated retained in this immutable projection.
    contract_version
        The expected contract version used to reject stale updates.
    policy_version
        The expected policy version used to reject stale updates.
    correlation_id
        The request correlation identifier used for audit tracing.
    blocker_total
        The blocker total retained in this immutable projection.
    production_status
        The closed production status discriminator defined by the domain catalog.
    """

    activated: bool
    contract_version: str
    policy_version: str
    correlation_id: UUID
    blocker_total: int
    production_status: str


def _normalized_text(value: str, *, maximum: int, label: str) -> str:
    if not isinstance(value, str):
        raise AuthorityProvenanceActivationError(
            f"{label} must contain between 1 and {maximum} characters."
        )
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or not normalized.isprintable():
        raise AuthorityProvenanceActivationError(
            f"{label} must contain between 1 and {maximum} characters."
        )
    return normalized


def _lock_activation_boundary() -> None:
    """Serialize cutover against every compatible authority writer."""
    with connection.cursor() as cursor:
        cursor.execute("SHOW lock_timeout")
        previous_lock_timeout = str(cursor.fetchone()[0])
        cursor.execute("SELECT set_config('lock_timeout', '10s', TRUE)")
        cursor.execute(
            "SELECT pg_advisory_xact_lock(%s)",
            [AUTHORITY_PROVENANCE_ACTIVATION_LOCK_KEY],
        )
        cursor.execute(
            "SELECT set_config('lock_timeout', %s, TRUE)",
            [previous_lock_timeout],
        )


def _pin_activation_search_path() -> None:
    """Keep every cutover read and write on the supported public schema.

    ``pg_catalog`` is intentionally omitted from the explicit path: PostgreSQL
    searches it first when it is not named, while ``pg_temp`` is named last so
    temporary relations cannot silently shadow the durable cutover tables.
    The setting is transaction-local and therefore cannot leak into the
    connection pool after the maintenance transaction commits or rolls back.
    """
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL search_path = public, pg_temp")


def _require_read_committed() -> None:
    """Keep the post-barrier eligibility read on a fresh MVCC snapshot.

    Raises
    ------
    AuthorityProvenanceActivationTransactionError
        If the operation encounters a authority provenance activation
        transaction condition.
    """
    with connection.cursor() as cursor:
        cursor.execute("SHOW transaction_isolation")
        row = cursor.fetchone()
    if row != ("read committed",):
        raise AuthorityProvenanceActivationTransactionError(
            "Activation requires the database READ COMMITTED isolation level."
        )


def _platform_actor(actor: Account) -> Account:
    if actor.pk is None:
        raise AuthorityProvenanceActivationError(
            "Activation requires a persisted platform administrator."
        )
    try:
        persisted = Account.objects.get(pk=actor.pk)
    except Account.DoesNotExist as error:
        raise AuthorityProvenanceActivationError(
            "Activation requires a persisted platform administrator."
        ) from error
    if not persisted.is_active or not persisted.is_platform_administrator:
        raise AuthorityProvenanceActivationError(
            "Activation requires an active platform administrator."
        )
    return persisted


def _count(report: dict[str, object], key: str) -> int:
    value = report.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise AuthorityProvenanceActivationVerificationError(
            "Authority provenance readiness returned an invalid count."
        )
    return value


def _result(
    *,
    marker: AuthorityProvenanceActivation,
    report: dict[str, object],
    activated: bool,
) -> AuthorityProvenanceActivationResult:
    production_status = report.get("production_status")
    if not isinstance(production_status, str) or production_status not in {
        "ready",
        "blocked",
    }:
        raise AuthorityProvenanceActivationVerificationError(
            "Authority provenance readiness returned an invalid status."
        )
    return AuthorityProvenanceActivationResult(
        activated=activated,
        contract_version=marker.contract_version,
        policy_version=marker.policy_version,
        correlation_id=marker.correlation_id,
        blocker_total=_count(report, "blocker_total"),
        production_status=production_status,
    )


def _activate_authority_provenance_locked(
    *,
    actor: Account,
    normalized_reason: str,
    correlation_id: UUID,
    normalized_channel: str,
) -> AuthorityProvenanceActivationResult:
    # The exclusive boundary drains every earlier authority or actor mutation
    # and blocks every later one until this transaction commits.  Actor
    # UPDATE/DELETE statements take the matching shared boundary before they
    # mutate, so a plain read after this lock is stable without introducing an
    # account-row/advisory-lock inversion with either application or raw SQL
    # authority writers.
    _require_read_committed()
    _pin_activation_search_path()
    _lock_activation_boundary()
    persisted_actor = _platform_actor(actor)

    marker = AuthorityProvenanceActivation.objects.filter(singleton=True).first()
    if marker is not None:
        if (
            marker.contract_version != EXACT_LINEAGE_POLICY_CONTRACT_VERSION
            or marker.policy_version != EXACT_LINEAGE_POLICY_VERSION
        ):
            raise AuthorityProvenanceActivationVerificationError(
                "The durable provenance marker is incompatible with this runtime."
            )
        report = build_authority_provenance_readiness_report()
        if report.get("production_status") != "ready":
            raise AuthorityProvenanceActivationVerificationError(
                "Exact authority provenance is active but not production-ready."
            )
        return _result(marker=marker, report=report, activated=False)

    report = build_authority_provenance_readiness_report()
    if report.get("activation_status") != "ready" or _count(report, "blocker_total"):
        raise AuthorityProvenanceActivationBlockedError(
            "Authority provenance activation is blocked by count-only readiness."
        )

    marker = AuthorityProvenanceActivation.objects.create(
        singleton=True,
        contract_version=EXACT_LINEAGE_POLICY_CONTRACT_VERSION,
        policy_version=EXACT_LINEAGE_POLICY_VERSION,
        activated_by=persisted_actor,
        reason=normalized_reason,
        correlation_id=correlation_id,
    )
    # The database trigger owns the cutover timestamp. Reload it so audit
    # ordering does not depend on application/database clock agreement.
    marker.refresh_from_db(fields=("activated_at",))
    append_audit(
        AuditRecord(
            principal_kind=persisted_actor.account_kind,
            principal_id=persisted_actor.id,
            principal_context_id=None,
            organization_id=None,
            event_edition_id=None,
            capability_code="authorization.manage_roles",
            operation="authorization.authority_provenance.activate",
            target_type="authorization.authority_provenance_activation",
            target_id=None,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code="exact_lineage_cutover",
            correlation_id=correlation_id,
            source_channel=normalized_channel,
            obligations=("reason", "audit", "stopped_processes"),
            changed_fields=("authority_provenance_activation",),
            elevated=True,
            safe_metadata={
                "contract_version": EXACT_LINEAGE_POLICY_CONTRACT_VERSION,
                "policy_version": EXACT_LINEAGE_POLICY_VERSION,
            },
            retention_class="security-extended",
        ),
        occurred_at=marker.activated_at,
    )

    postflight = build_authority_provenance_readiness_report()
    if postflight.get("production_status") != "ready" or _count(
        postflight, "blocker_total"
    ):
        raise AuthorityProvenanceActivationVerificationError(
            "Authority provenance activation failed closed postflight."
        )
    return _result(marker=marker, report=postflight, activated=True)


def activate_authority_provenance(
    *,
    actor: Account,
    reason: str,
    correlation_id: UUID,
    acknowledge_processes_stopped: bool,
    source_channel: str = "service",
) -> AuthorityProvenanceActivationResult:
    """Irreversibly select exact lineage after a locked, zero-blocker proof.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    reason : str
        The operator-supplied rationale recorded with the change.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    acknowledge_processes_stopped : bool
        The acknowledge processes stopped evaluated while activate authority provenance.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.

    Returns
    -------
    AuthorityProvenanceActivationResult
        The AuthorityProvenanceActivationResult produced by activate authority
        provenance.

    Raises
    ------
    AuthorityProvenanceActivationEnvironmentError
        If the operation encounters a authority provenance activation
        environment condition.
    AuthorityProvenanceActivationError
        If the operation encounters a authority provenance activation condition.
    AuthorityProvenanceActivationTransactionError
        If the operation encounters a authority provenance activation
        transaction condition.
    ProcessesStoppedAcknowledgementRequiredError
        If the operation encounters a processes stopped acknowledgement required
        condition.
    """
    if acknowledge_processes_stopped is not True:
        raise ProcessesStoppedAcknowledgementRequiredError(
            "Activation requires explicit stopped-process acknowledgement."
        )
    if not isinstance(actor, Account):
        raise AuthorityProvenanceActivationError(
            "Activation requires a persisted platform administrator."
        )
    normalized_reason = _normalized_text(
        reason,
        maximum=MAX_ACTIVATION_REASON_LENGTH,
        label="Activation reason",
    )
    normalized_channel = _normalized_text(
        source_channel,
        maximum=MAX_SOURCE_CHANNEL_LENGTH,
        label="Source channel",
    )
    if not isinstance(correlation_id, UUID):
        raise AuthorityProvenanceActivationError(
            "Activation requires a valid correlation identifier."
        )
    if EXACT_LINEAGE_POLICY_CONTRACT_VERSION != AUTHORITY_PROVENANCE_CONTRACT_VERSION:
        raise AuthorityProvenanceActivationEnvironmentError(
            "The runtime and schema provenance contracts disagree."
        )
    if settings.REQUIRE_EXACT_AUTHORITY_PROVENANCE is not True:
        raise AuthorityProvenanceActivationEnvironmentError(
            "Activation requires the exact-provenance recovery fence."
        )
    if connection.in_atomic_block or not connection.get_autocommit():
        raise AuthorityProvenanceActivationTransactionError(
            "Activation must own a top-level maintenance transaction."
        )

    with transaction.atomic():
        return _activate_authority_provenance_locked(
            actor=actor,
            normalized_reason=normalized_reason,
            correlation_id=correlation_id,
            normalized_channel=normalized_channel,
        )
