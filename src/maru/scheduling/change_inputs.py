"""Closed exact-change selections, never recipient or delivery authority."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from django.core.exceptions import ValidationError

from .inputs import require_version


class ChangeRecipientPurpose(StrEnum):
    """An exact owner relationship or operational scope, not an audience list."""

    HOST = "host"
    WORK = "work"
    ROOM = "room"
    DEPARTMENT = "department"
    EDITION = "edition"


def _identifier(value: object) -> None:
    if type(value) is not UUID or value.int == 0:
        raise ValidationError(
            "Select an exact Programme change reference.",
            code="scheduling_change_input_invalid",
        )


def _digest(value: str) -> None:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValidationError(
            "Refresh the exact Programme change preview.",
            code="scheduling_change_input_invalid",
        )


@dataclass(frozen=True, slots=True)
class ChangeRecipientSelection:
    """Select one purpose without substituting a person for an owner relationship.

    Attributes
    ----------
    purpose
        Closed host, work, room, Department or edition purpose.
    target_id
        Exact host relationship, work commitment or operational scope identity.
    operator_account_id
        Explicit person only for an operator purpose. Host and work recipients
        must instead be resolved by their owners, never supplied by the caller.
    """

    purpose: ChangeRecipientPurpose
    target_id: UUID
    operator_account_id: UUID | None = None

    def validated(self) -> ChangeRecipientSelection:
        """Require a closed purpose and its exact, non-interchangeable selector.

        Returns
        -------
        ChangeRecipientSelection
            Unchanged immutable intent, not verified recipient eligibility.

        Raises
        ------
        ValidationError
            If purpose or identifiers are malformed or the account is misplaced.
        """
        if type(self.purpose) is not ChangeRecipientPurpose:
            raise ValidationError("Select a closed Programme recipient purpose.")
        _identifier(self.target_id)
        if self.purpose in {ChangeRecipientPurpose.HOST, ChangeRecipientPurpose.WORK}:
            if self.operator_account_id is not None:
                raise ValidationError("The owning relationship selects its recipient.")
        else:
            _identifier(self.operator_account_id)
        return self

    def payload(self) -> dict[str, object]:
        """Serialize validated selector intent without labels or contact details.

        Returns
        -------
        dict[str, object]
            Canonical JSON-compatible intent for a command's retry digest.

        Notes
        -----
        ValidationError from validation propagates before serialization.
        """
        self.validated()
        return {
            "purpose": self.purpose.value,
            "target_id": str(self.target_id),
            "operator_account_id": (
                str(self.operator_account_id)
                if self.operator_account_id is not None
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class PrepareChangeNoticeIntent:
    """Select one freshly previewed transition, occurrence and recipient purpose.

    Attributes
    ----------
    release_id
        Exact retained publication, never a private draft or arbitrary baseline.
    occurrence_id
        Exact affected occurrence, independently proven by the owning command.
    expected_pointer_version
        Observed publication/withdrawal sequence; zero has no published change.
    recipient
        Exact purpose selection, whose current person is independently resolved.
    snapshot_digest
        Fingerprint of the complete authorized preview, including current source
        and purpose versions. The command recollects it; this is not a permission.
    """

    release_id: UUID
    occurrence_id: UUID
    expected_pointer_version: int
    recipient: ChangeRecipientSelection
    snapshot_digest: str

    def validated(self) -> PrepareChangeNoticeIntent:
        """Reject incomplete, untyped or coercible notice preparation input.

        Returns
        -------
        PrepareChangeNoticeIntent
            Unchanged closed intent without asserting source or recipient truth.

        Raises
        ------
        ValidationError
            If an identifier, selection, version or digest is malformed.
        """
        _identifier(self.release_id)
        _identifier(self.occurrence_id)
        require_version(self.expected_pointer_version)
        _digest(self.snapshot_digest)
        if type(self.recipient) is not ChangeRecipientSelection:
            raise ValidationError("Select one exact Programme change recipient.")
        self.recipient.validated()
        return self

    def payload(self) -> dict[str, object]:
        """Serialize exact retry intent without accepting content or safety flags.

        Returns
        -------
        dict[str, object]
            Code-owned JSON-compatible command input, not the prepared notice.

        Notes
        -----
        ValidationError from validation propagates before serialization.
        """
        self.validated()
        return {
            "release_id": str(self.release_id),
            "occurrence_id": str(self.occurrence_id),
            "expected_pointer_version": self.expected_pointer_version,
            "recipient": self.recipient.payload(),
            "snapshot_digest": self.snapshot_digest,
        }


@dataclass(frozen=True, slots=True)
class ChangeNoticeDecisionIntent:
    """Select the exact prepared package and observed evidence sequence.

    Attributes
    ----------
    notice_id
        Exact retained notice, not a caller-supplied recipient or release.
    expected_version
        Observed notice evidence version, checked under the command's locks.
    snapshot_digest
        Exact prepared content/source/purpose fingerprint. A new material change
        requires another notice and cannot inherit this acknowledgement.
    """

    notice_id: UUID
    expected_version: int
    snapshot_digest: str

    def validated(self) -> ChangeNoticeDecisionIntent:
        """Validate a decision selection without granting review or self authority.

        Returns
        -------
        ChangeNoticeDecisionIntent
            The unchanged immutable selection.

        Notes
        -----
        Shared validators raise ValidationError before a malformed selection is
        used. No actor, review result, delivery claim or recipient is accepted.
        """
        _identifier(self.notice_id)
        require_version(self.expected_version)
        _digest(self.snapshot_digest)
        return self

    def payload(self) -> dict[str, object]:
        """Serialize exact decision intent independently of the operation name.

        Returns
        -------
        dict[str, object]
            Minimized JSON-compatible input; the command adds its closed action.

        Notes
        -----
        ValidationError from validation propagates before serialization.
        """
        self.validated()
        return {
            "notice_id": str(self.notice_id),
            "expected_version": self.expected_version,
            "snapshot_digest": self.snapshot_digest,
        }
