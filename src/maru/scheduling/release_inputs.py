"""Closed release command selections; no caller-supplied eligibility or authority."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError

from .catalogs import MAX_CONFLICTS
from .inputs import require_identifier, require_version

if TYPE_CHECKING:
    from uuid import UUID

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _require_digest(value: str) -> None:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise ValidationError(
            "Supply the exact release source fingerprint.",
            code="scheduling_release_input_invalid",
        )


@dataclass(frozen=True, slots=True)
class ReleaseCandidateSelection:
    """Select one exact candidate snapshot without claiming its eligibility.

    Attributes
    ----------
    candidate_id
        Exact private alternative selected after scope admission.
    candidate_revision_id
        Exact immutable manifest, not an instruction to find the latest.
    expected_candidate_version
        Caller-observed current alternative version.
    source_snapshot_digest
        Owner-collected complete snapshot to recollect under command locks.
    """

    candidate_id: UUID
    candidate_revision_id: UUID
    expected_candidate_version: int
    source_snapshot_digest: str

    def validated(self) -> ReleaseCandidateSelection:
        """Validate closed identifiers, current version and exact fingerprint.

        Returns
        -------
        ReleaseCandidateSelection
            The unchanged immutable selection; no source has been authenticated.

        Notes
        -----
        Shared validators raise ValidationError for malformed identifiers,
        versions or fingerprints.
        """
        require_identifier(self.candidate_id)
        require_identifier(self.candidate_revision_id)
        require_version(self.expected_candidate_version)
        _require_digest(self.source_snapshot_digest)
        return self


def _require_selection(value: ReleaseCandidateSelection) -> None:
    if type(value) is not ReleaseCandidateSelection:
        raise ValidationError(
            "Supply one exact release candidate selection.",
            code="scheduling_release_input_invalid",
        )
    value.validated()


@dataclass(frozen=True, slots=True)
class ReleaseWarningIntent:
    """Select a warning for reasoned acknowledgement, never a hard waiver.

    Attributes
    ----------
    selection
        Exact current candidate and complete source snapshot.
    finding_fingerprint
        Exact finding which the owner must freshly resolve as a warning.
    """

    selection: ReleaseCandidateSelection
    finding_fingerprint: str

    def validated(self) -> ReleaseWarningIntent:
        """Validate shape without authenticating the finding or its severity.

        Returns
        -------
        ReleaseWarningIntent
            The unchanged immutable intent.

        Notes
        -----
        Shared validators raise ValidationError for a malformed selection or
        exact finding fingerprint.
        """
        _require_selection(self.selection)
        _require_digest(self.finding_fingerprint)
        return self


@dataclass(frozen=True, slots=True)
class ReleaseApprovalIntent:
    """Select exact retained warning evidence for independent timetable review.

    Attributes
    ----------
    selection
        Exact current candidate and complete source snapshot.
    acknowledgement_ids
        Complete bounded explicit evidence selection, independently authenticated
        by the command. Empty is valid only when no current warning requires it.
    """

    selection: ReleaseCandidateSelection
    acknowledgement_ids: tuple[UUID, ...] = ()

    def validated(self) -> ReleaseApprovalIntent:
        """Reject streams and duplicates and canonicalize the evidence selection.

        Returns
        -------
        ReleaseApprovalIntent
            Immutable intent with acknowledgement identifiers in canonical order.

        Raises
        ------
        ValidationError
            If a selection, identifier, collection shape or bound is invalid.
        """
        _require_selection(self.selection)
        ids = self.acknowledgement_ids
        if type(ids) is not tuple or len(ids) > MAX_CONFLICTS:
            raise ValidationError(
                "Supply a complete bounded warning evidence selection.",
                code="scheduling_release_input_invalid",
            )
        for identifier in ids:
            require_identifier(identifier)
        if len(set(ids)) != len(ids):
            raise ValidationError(
                "Select each warning acknowledgement exactly once.",
                code="scheduling_release_input_invalid",
            )
        return replace(self, acknowledgement_ids=tuple(sorted(ids, key=str)))


@dataclass(frozen=True, slots=True)
class ReleasePublicationIntent:
    """Select approval and expected prior state without supplying artifact trust.

    Attributes
    ----------
    approval_id
        Exact immutable approval to freshly authorize and verify.
    expected_active_release_id
        Caller-observed active release, or explicit absence.
    expected_release_version
        Monotonic pointer version; zero is valid only before the first release.
        A withdrawn pointer may be absent at a later nonzero version.
    source_snapshot_digest
        Exact complete evidence required to still match the retained approval.
    """

    approval_id: UUID
    expected_active_release_id: UUID | None
    expected_release_version: int
    source_snapshot_digest: str

    def validated(self) -> ReleasePublicationIntent:
        """Validate optimistic pointer shape, not current approval or eligibility.

        Returns
        -------
        ReleasePublicationIntent
            The unchanged immutable intent.

        Raises
        ------
        ValidationError
            If identifiers, fingerprint or pointer-version shape is malformed.
        """
        require_identifier(self.approval_id)
        require_version(self.expected_release_version, initial=True)
        _require_digest(self.source_snapshot_digest)
        if self.expected_active_release_id is not None:
            require_identifier(self.expected_active_release_id)
            if self.expected_release_version == 0:
                raise ValidationError(
                    "An existing release requires a nonzero pointer version.",
                    code="scheduling_release_input_invalid",
                )
        return self


@dataclass(frozen=True, slots=True)
class ReleaseWithdrawalIntent:
    """Select one current whole release for explicit reasoned withdrawal.

    Attributes
    ----------
    active_release_id
        Exact current release, never an empty-candidate surrogate.
    expected_release_version
        Caller-observed nonzero pointer version.
    """

    active_release_id: UUID
    expected_release_version: int

    def validated(self) -> ReleaseWithdrawalIntent:
        """Validate a retained exact release and advanceable pointer version.

        Returns
        -------
        ReleaseWithdrawalIntent
            The unchanged immutable intent.

        Notes
        -----
        Shared validators raise ValidationError for a malformed identifier or
        pointer version.
        """
        require_identifier(self.active_release_id)
        require_version(self.expected_release_version)
        return self
