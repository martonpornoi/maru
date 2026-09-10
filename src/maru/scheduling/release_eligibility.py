"""Pure, fail-closed release-review rules; never authority or publication proof.

Only a future independently authorized owner-source collector may supply these
facts to an approval command. This module authenticates no caller, performs no
queries or writes, and does not promote a planning evaluation into a release.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from django.core.exceptions import ValidationError

from .catalogs import MAX_CONFLICTS, SchedulingConflictSeverity

RELEASE_ELIGIBILITY_POLICY: Final = "scheduling.release-eligibility@1"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class ReleaseCheck(StrEnum):
    """Every mandatory category in a complete release-source collection."""

    CANDIDATE = "candidate"
    PROGRAMME_READINESS = "programme_readiness"
    PUBLIC_COPY = "public_copy"
    HOSTS = "hosts"
    PHYSICAL_APPROVAL = "physical_approval"
    PHYSICAL_CONSTRAINTS = "physical_constraints"
    ACCESSIBILITY_FIT = "accessibility_fit"
    STAFFING = "staffing"
    PERSON_CONFLICTS = "person_conflicts"
    REST = "rest"


class ReleaseCheckState(StrEnum):
    """Current evidence, explicit inapplicability and failures stay distinct."""

    SATISFIED = "satisfied"
    NOT_APPLICABLE = "not_applicable"
    BLOCKED = "blocked"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


_OPTIONALLY_APPLICABLE: Final = frozenset(
    {
        ReleaseCheck.HOSTS,
        ReleaseCheck.STAFFING,
        ReleaseCheck.PERSON_CONFLICTS,
        ReleaseCheck.REST,
    }
)


@dataclass(frozen=True, slots=True)
class ReleaseCheckEvidence:
    """One minimized complete-category result from the trusted source collector.

    Attributes
    ----------
    snapshot_digest
        Exact scope, candidate manifest, policy and dependency fingerprint.
    check
        Mandatory category; never an arbitrary provider or caller label.
    state
        Complete current category result, not a human-entered success flag.
    """

    snapshot_digest: str
    check: ReleaseCheck
    state: ReleaseCheckState


@dataclass(frozen=True, slots=True)
class ReleaseFinding:
    """One exact source finding without people, calendars or private rationale.

    Attributes
    ----------
    snapshot_digest
        Exact release-review fingerprint, not the old planning-only digest.
    check
        Owning release category whose collector supplied this finding.
    fingerprint
        Digest of the exact finding and its current source identity.
    severity
        Blocker, warning or unavailable; only a warning can be acknowledged.
    """

    snapshot_digest: str
    check: ReleaseCheck
    fingerprint: str
    severity: SchedulingConflictSeverity


@dataclass(frozen=True, slots=True)
class ReleaseWarningAcknowledgement:
    """Minimized reference to already authorized, reasoned warning evidence.

    Attributes
    ----------
    snapshot_digest
        Exact fingerprint to which the retained acknowledgement was given.
    finding_fingerprint
        One current warning; the collector separately verifies its receipt.
    """

    snapshot_digest: str
    finding_fingerprint: str


@dataclass(frozen=True, slots=True)
class ReleaseEligibility:
    """Deterministic review blockers, not an approval or a reusable permit.

    Attributes
    ----------
    snapshot_digest
        Exact independently collected snapshot evaluated by this policy.
    blocked_checks
        Explicit failures, including inapplicability on mandatory categories.
    stale_checks
        Categories requiring fresh source evidence.
    unavailable_checks
        Missing or unavailable categories; an empty source set is not success.
    blocking_findings
        Current hard findings which no acknowledgement can waive.
    unavailable_findings
        Current incomplete findings even if their category claimed success.
    unacknowledged_warnings
        Exact current warning fingerprints still requiring retained rationale.
    """

    snapshot_digest: str
    blocked_checks: tuple[ReleaseCheck, ...]
    stale_checks: tuple[ReleaseCheck, ...]
    unavailable_checks: tuple[ReleaseCheck, ...]
    blocking_findings: tuple[str, ...]
    unavailable_findings: tuple[str, ...]
    unacknowledged_warnings: tuple[str, ...]

    @property
    def eligible_for_review(self) -> bool:
        """Return whether complete supplied evidence permits independent review.

        Returns
        -------
        bool
            True only when no category or finding remains unresolved. This is
            neither independently authenticated evidence nor approval authority.
        """
        return not any(
            (
                self.blocked_checks,
                self.stale_checks,
                self.unavailable_checks,
                self.blocking_findings,
                self.unavailable_findings,
                self.unacknowledged_warnings,
            )
        )


class ReleaseEvidenceInvalidError(ValidationError):
    """Reject malformed evidence without disclosing its private source identity."""

    def __init__(self) -> None:
        """Use one stable content-free validation reason."""
        super().__init__(
            "Complete exact-snapshot release evidence is required.",
            code="scheduling_release_evidence_invalid",
        )


def _digest(value: str) -> None:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise ReleaseEvidenceInvalidError


def _bounded_tuple(value: object, maximum: int) -> None:
    # Reject streams and mutable containers before traversing caller evidence.
    if type(value) is not tuple or len(value) > maximum:
        raise ReleaseEvidenceInvalidError


def _same_snapshot(actual: str, expected: str) -> None:
    _digest(actual)
    if actual != expected:
        raise ReleaseEvidenceInvalidError


def evaluate_release_eligibility(
    *,
    snapshot_digest: str,
    checks: tuple[ReleaseCheckEvidence, ...],
    findings: tuple[ReleaseFinding, ...] = (),
    acknowledgements: tuple[ReleaseWarningAcknowledgement, ...] = (),
) -> ReleaseEligibility:
    """Require every release category and every exact warning to be resolved.

    Parameters
    ----------
    snapshot_digest : str
        Canonical SHA-256 of the independently collected scope, immutable
        candidate, complete dependencies and exact eligibility policy.
    checks : tuple[ReleaseCheckEvidence, ...]
        At most one result per closed category. Missing categories are unavailable.
    findings : tuple[ReleaseFinding, ...], default=()
        Complete bounded source findings; partial collection is never permitted.
    acknowledgements : tuple[ReleaseWarningAcknowledgement, ...], default=()
        Retained same-snapshot warnings authenticated by the future collector.

    Returns
    -------
    ReleaseEligibility
        Stable category-order and fingerprint-order unresolved evidence.

    Raises
    ------
    ReleaseEvidenceInvalidError
        If evidence is malformed, duplicated, over-bound, foreign-snapshot or
        acknowledges anything other than an exact supplied warning.

    Notes
    -----
    This pure policy is intentionally unmounted. It does not verify an owner
    signature, authorize disclosure, acquire locks, persist approval, validate
    artifacts or change a release. Those are mandatory application-service
    successors, not guarantees inferred from an eligible result.
    """
    _digest(snapshot_digest)
    _bounded_tuple(checks, len(ReleaseCheck))
    _bounded_tuple(findings, MAX_CONFLICTS)
    _bounded_tuple(acknowledgements, MAX_CONFLICTS)
    by_check: dict[ReleaseCheck, ReleaseCheckState] = {}
    for row in checks:
        if (
            type(row) is not ReleaseCheckEvidence
            or type(row.check) is not ReleaseCheck
            or type(row.state) is not ReleaseCheckState
            or row.check in by_check
        ):
            raise ReleaseEvidenceInvalidError
        _same_snapshot(row.snapshot_digest, snapshot_digest)
        by_check[row.check] = row.state

    by_fingerprint: dict[str, SchedulingConflictSeverity] = {}
    for finding in findings:
        if (
            type(finding) is not ReleaseFinding
            or type(finding.check) is not ReleaseCheck
            or finding.check not in by_check
            or by_check[finding.check] is ReleaseCheckState.NOT_APPLICABLE
            or type(finding.severity) is not SchedulingConflictSeverity
        ):
            raise ReleaseEvidenceInvalidError
        _same_snapshot(finding.snapshot_digest, snapshot_digest)
        _digest(finding.fingerprint)
        if finding.fingerprint in by_fingerprint:
            raise ReleaseEvidenceInvalidError
        by_fingerprint[finding.fingerprint] = finding.severity

    acknowledged: set[str] = set()
    for acknowledgement in acknowledgements:
        if type(acknowledgement) is not ReleaseWarningAcknowledgement:
            raise ReleaseEvidenceInvalidError
        _same_snapshot(acknowledgement.snapshot_digest, snapshot_digest)
        fingerprint = acknowledgement.finding_fingerprint
        _digest(fingerprint)
        if (
            fingerprint in acknowledged
            or by_fingerprint.get(fingerprint) is not SchedulingConflictSeverity.WARNING
        ):
            raise ReleaseEvidenceInvalidError
        acknowledged.add(fingerprint)

    blocked: list[ReleaseCheck] = []
    stale: list[ReleaseCheck] = []
    unavailable: list[ReleaseCheck] = []
    for check in ReleaseCheck:
        state = by_check.get(check, ReleaseCheckState.UNAVAILABLE)
        if state is ReleaseCheckState.BLOCKED or (
            state is ReleaseCheckState.NOT_APPLICABLE
            and check not in _OPTIONALLY_APPLICABLE
        ):
            blocked.append(check)
        elif state is ReleaseCheckState.STALE:
            stale.append(check)
        elif state is ReleaseCheckState.UNAVAILABLE:
            unavailable.append(check)
    return ReleaseEligibility(
        snapshot_digest,
        tuple(blocked),
        tuple(stale),
        tuple(unavailable),
        tuple(
            sorted(
                key
                for key, value in by_fingerprint.items()
                if value is SchedulingConflictSeverity.BLOCKER
            )
        ),
        tuple(
            sorted(
                key
                for key, value in by_fingerprint.items()
                if value is SchedulingConflictSeverity.UNAVAILABLE
            )
        ),
        tuple(
            sorted(
                key
                for key, value in by_fingerprint.items()
                if value is SchedulingConflictSeverity.WARNING
                and key not in acknowledged
            )
        ),
    )
