"""Purpose-signed original person selection, never authority or an approval."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from hmac import compare_digest
from typing import TYPE_CHECKING
from uuid import UUID

from django.core import signing
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from maru.authorization.programme_role_inputs import (
    ProgrammeRoleIntent,
    normalize_programme_role_intent,
    programme_role_intent_digest,
)

if TYPE_CHECKING:
    from datetime import datetime

    from maru.authorization.programme_role_inputs import ProgrammeRoleScope

MAX_PROGRAMME_ROLE_SELECTION_BYTES = 2048
_SALT = "authorization.programme-role-selection.v1"
_MAX_ADDRESS_LENGTH = 254
_INVALID = (
    "This original person selection cannot be verified. Keep the original input "
    "after uncertainty and inspect retained requests before starting a new intent. "
    "Changed input requires a deliberate new preview."
)


@dataclass(frozen=True, slots=True)
class ProgrammeRoleRequestDraft:
    """Describe deliberate input before exact people have been selected.

    Attributes
    ----------
    recipe_code, recipe_version
        Exact code-owned role definition, never a submitted capability list.
    recipient_email, approver_email
        Known exact selectors used only for fresh preview, not contact inventory.
    not_before, expires_at
        Optional aware instants with the owning command's unchanged meaning.
    reason
        Bounded original rationale, separate from the approver's future decision.
    idempotency_key
        Nonempty original author-bound retry identity, retained through uncertainty.
    """

    recipe_code: str
    recipe_version: int
    recipient_email: str
    approver_email: str
    not_before: datetime | None
    expires_at: datetime | None
    reason: str
    idempotency_key: UUID

    def intent(self, recipient_id: UUID, approver_id: UUID) -> ProgrammeRoleIntent:
        """Normalize exact terms without looking up either mutable selector.

        Parameters
        ----------
        recipient_id : UUID
            Exact selected recipient, not proof of current eligibility.
        approver_id : UUID
            Exact selected independent approver, not proof of their decision.

        Returns
        -------
        ProgrammeRoleIntent
            Canonical owner input; current authority remains the command's concern.
        """
        return normalize_programme_role_intent(
            ProgrammeRoleIntent(
                self.recipe_code,
                self.recipe_version,
                recipient_id,
                approver_id,
                self.not_before,
                self.expires_at,
                self.reason,
            )
        )


@dataclass(frozen=True, slots=True)
class ProgrammeRoleSelection:
    """Bind exact selected people and original terms without granting anything.

    Attributes
    ----------
    details
        Canonical original command input containing the exact selected people.
    proof
        Bounded purpose signature, never read authority, consent or a grant.
    """

    details: ProgrammeRoleIntent
    proof: str


def _selectors(draft: ProgrammeRoleRequestDraft) -> tuple[str, str]:
    if not isinstance(draft.idempotency_key, UUID) or draft.idempotency_key.int == 0:
        raise ValidationError("Keep a nonempty original retry identity.")
    values = (draft.recipient_email, draft.approver_email)
    for value in values:
        if not isinstance(value, str) or len(value) > _MAX_ADDRESS_LENGTH:
            raise ValidationError("Use two bounded known exact addresses.")
        validate_email(value.strip())
    return values[0].strip(), values[1].strip()


def _digest(
    actor_id: UUID,
    scope: ProgrammeRoleScope,
    draft: ProgrammeRoleRequestDraft,
    details: ProgrammeRoleIntent,
) -> str:
    if (
        not isinstance(actor_id, UUID)
        or actor_id.int == 0
        or actor_id == details.approver_id
    ):
        raise ValidationError("The approver must be a different person.")
    recipient, approver = _selectors(draft)
    payload = {
        "actor": str(actor_id),
        "intent": programme_role_intent_digest(scope=scope, details=details),
        "key": str(draft.idempotency_key),
        "recipient_selector": recipient,
        "approver_selector": approver,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _sign_selection(
    actor_id: UUID,
    scope: ProgrammeRoleScope,
    draft: ProgrammeRoleRequestDraft,
    recipient_id: UUID,
    approver_id: UUID,
) -> ProgrammeRoleSelection:
    details = draft.intent(recipient_id, approver_id)
    proof = signing.dumps(
        {
            "recipient_id": str(recipient_id),
            "approver_id": str(approver_id),
            "intent": _digest(actor_id, scope, draft, details),
        },
        salt=_SALT,
    )
    return ProgrammeRoleSelection(details, proof)


def _verified_selection(
    actor_id: UUID,
    scope: ProgrammeRoleScope,
    draft: ProgrammeRoleRequestDraft,
    proof: str,
) -> ProgrammeRoleSelection:
    if (
        not isinstance(proof, str)
        or len(proof.encode("utf-8")) > MAX_PROGRAMME_ROLE_SELECTION_BYTES
    ):
        raise ValueError
    payload = signing.loads(proof, salt=_SALT)
    if not isinstance(payload, dict) or set(payload) != {
        "recipient_id",
        "approver_id",
        "intent",
    }:
        raise ValueError
    details = draft.intent(UUID(payload["recipient_id"]), UUID(payload["approver_id"]))
    if not isinstance(payload["intent"], str) or not compare_digest(
        payload["intent"], _digest(actor_id, scope, draft, details)
    ):
        raise ValueError
    return ProgrammeRoleSelection(details, proof)


def verify_programme_role_selection(
    *,
    actor_id: UUID,
    scope: ProgrammeRoleScope,
    draft: ProgrammeRoleRequestDraft,
    proof: str,
) -> ProgrammeRoleSelection:
    """Verify exact original intent without re-resolving people or authorizing.

    Parameters
    ----------
    actor_id : UUID
        Actual authenticated original author, never a submitted alternate actor.
    scope : ProgrammeRoleScope
        Original complete route-owned Programme context and actual grant scope.
    draft : ProgrammeRoleRequestDraft
        Original selectors, recipe, interval, rationale and retry identity.
    proof : str
        Purpose-signed bounded selection, subject to configured signing fallbacks.

    Returns
    -------
    ProgrammeRoleSelection
        Original normalized intent ready for the independently authorizing command.

    Raises
    ------
    ValidationError
        For malformed, foreign or changed input/proof. Verification never refreshes
        the people, key, interval or authority and does not create a request.
    """
    try:
        return _verified_selection(actor_id, scope, draft, proof)
    except (
        signing.BadSignature,
        ValueError,
        TypeError,
        UnicodeError,
        AttributeError,
        ValidationError,
    ) as error:
        raise ValidationError(_INVALID) from error
