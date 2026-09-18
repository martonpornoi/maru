"""Purpose-signed original approver selection; never their approval or authority."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from hmac import compare_digest
from uuid import UUID

from django.core import signing
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from maru.workforce.programme_starter_inputs import (
    ProgrammeStarterIntent,
    ProgrammeStarterScope,
    _identifier,
    normalize_programme_starter_intent,
    programme_starter_intent_digest,
)

MAX_PROGRAMME_STARTER_PROOF_BYTES = 2048
_MAX_ADDRESS_LENGTH = 254
_SALT = "workforce.programme-starter-selection.v1"


@dataclass(frozen=True, slots=True)
class ProgrammeStarterDraft:
    """Retain deliberate original input before choosing a known approver.

    Attributes
    ----------
    approver_email
        Exact known selector, not a contact inventory or proof of approval.
    reason
        Bounded original administrative rationale.
    idempotency_key
        Original author-bound request identity retained through uncertainty.
    """

    approver_email: str
    reason: str
    idempotency_key: UUID

    def intent(self, approver_id: UUID) -> ProgrammeStarterIntent:
        """Normalize original terms with the selected immutable person identity.

        Parameters
        ----------
        approver_id : UUID
            Previously selected identity; current eligibility is checked elsewhere.

        Returns
        -------
        ProgrammeStarterIntent
            Canonical owner input without resolving a mutable email again.
        """
        return normalize_programme_starter_intent(
            ProgrammeStarterIntent(approver_id, self.reason)
        )


@dataclass(frozen=True, slots=True)
class ProgrammeStarterSelection:
    """Keep original command intent and its purpose-bound signature together.

    Attributes
    ----------
    details
        Exact selected person and normalized original rationale.
    proof
        Bounded signature, never current admission or the approver's own decision.
    """

    details: ProgrammeStarterIntent
    proof: str


def _selector(draft: ProgrammeStarterDraft) -> str:
    _identifier(draft.idempotency_key)
    if (
        not isinstance(draft.approver_email, str)
        or len(draft.approver_email) > _MAX_ADDRESS_LENGTH
    ):
        raise ValidationError("Use one bounded known exact approver address.")
    result = draft.approver_email.strip()
    validate_email(result)
    return result


def _digest(
    actor_id: UUID,
    scope: ProgrammeStarterScope,
    draft: ProgrammeStarterDraft,
    details: ProgrammeStarterIntent,
) -> str:
    _identifier(actor_id)
    if actor_id == details.approver_id:
        raise ValidationError("The approver must be a different person.")
    values = {
        "actor": str(actor_id),
        "intent": programme_starter_intent_digest(scope=scope, details=details),
        "key": str(draft.idempotency_key),
        "selector": _selector(draft),
    }
    return hashlib.sha256(
        json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _sign_selection(
    actor_id: UUID,
    scope: ProgrammeStarterScope,
    draft: ProgrammeStarterDraft,
    approver_id: UUID,
) -> ProgrammeStarterSelection:
    details = draft.intent(approver_id)
    return ProgrammeStarterSelection(
        details,
        signing.dumps(
            {
                "approver_id": str(approver_id),
                "intent": _digest(actor_id, scope, draft, details),
            },
            salt=_SALT,
        ),
    )


def _verified(
    actor_id: UUID,
    scope: ProgrammeStarterScope,
    draft: ProgrammeStarterDraft,
    proof: str,
) -> ProgrammeStarterSelection:
    if (
        not isinstance(proof, str)
        or len(proof.encode()) > MAX_PROGRAMME_STARTER_PROOF_BYTES
    ):
        raise ValueError
    payload = signing.loads(proof, salt=_SALT)
    if not isinstance(payload, dict) or set(payload) != {"approver_id", "intent"}:
        raise ValueError
    details = draft.intent(UUID(payload["approver_id"]))
    if not isinstance(payload["intent"], str) or not compare_digest(
        payload["intent"], _digest(actor_id, scope, draft, details)
    ):
        raise ValueError
    return ProgrammeStarterSelection(details, proof)


def verify_programme_starter_selection(
    *,
    actor_id: UUID,
    scope: ProgrammeStarterScope,
    draft: ProgrammeStarterDraft,
    proof: str,
) -> ProgrammeStarterSelection:
    """Recover exact original person/terms without a new lookup or authority claim.

    Parameters
    ----------
    actor_id : UUID
        Actual authenticated author, never a submitted alternate principal.
    scope : ProgrammeStarterScope
        Original complete route-owned context.
    draft : ProgrammeStarterDraft
        Original known selector, rationale and retry identity.
    proof : str
        Bounded purpose signature using configured signing fallback behavior.

    Returns
    -------
    ProgrammeStarterSelection
        Original normalized command input; owning commands independently authorize.

    Raises
    ------
    ValidationError
        For malformed/foreign/changed proof or input; never silently selects again.
    """
    try:
        return _verified(actor_id, scope, draft, proof)
    except (
        signing.BadSignature,
        ValueError,
        TypeError,
        UnicodeError,
        AttributeError,
        ValidationError,
    ) as error:
        raise ValidationError(
            "The original approver selection cannot be verified. Keep the original "
            "input and key after uncertainty; inspect retained requests before "
            "starting another. Changed input requires a deliberate new preview."
        ) from error
