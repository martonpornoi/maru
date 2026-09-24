"""Closed original intent for Programme stop confirmation, never stop authority.

No profile, route or command is enabled here. The owner command must authorize
the actual actor, lock the complete scope, rebuild the preview and compare its
fingerprint before performing any terminal transition or owner consequence.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, replace
from typing import Never
from uuid import UUID

from django.core.exceptions import ValidationError

_FINGERPRINT = re.compile(r"[0-9a-f]{64}", re.ASCII)
_MAX_VERSION = 2_147_483_647
_MAX_REASON = 240
_MAX_RAW_REASON = 4096


@dataclass(frozen=True, slots=True)
class ProgrammeStopInput:
    """Bind explicit stop intent to the original complete owner preview.

    Attributes
    ----------
    expected_aggregate_version, expected_lifecycle_version
        Exact Events versions shown at preview; not replacement server values.
    preview_fingerprint
        Owner-produced complete impact identity, not a permission or token.
    reason
        Required minimized accountable rationale, retained with the receipt.
    """

    expected_aggregate_version: int
    expected_lifecycle_version: int
    preview_fingerprint: str
    reason: str


def _invalid(field: str, message: str, code: str) -> Never:
    raise ValidationError({field: ValidationError(message, code=code)})


def normalize_programme_stop_input(  # noqa: DOC502 - shared validator raises field errors.
    details: ProgrammeStopInput,
) -> ProgrammeStopInput:
    """Validate without coercing versions or accepting a partial preview identity.

    Parameters
    ----------
    details : ProgrammeStopInput
        Untrusted confirmation values, without authority or discovered owner IDs.

    Returns
    -------
    ProgrammeStopInput
        Immutable normalized intent; the submitted object remains unchanged.

    Raises
    ------
    ValidationError
        If the container, versions, fingerprint or bounded rationale is invalid.
    """
    if type(details) is not ProgrammeStopInput:
        _invalid("intent", "Reload the stop preview.", "programme_stop_intent_invalid")
    for field, minimum in (
        ("expected_aggregate_version", 1),
        ("expected_lifecycle_version", 0),
    ):
        value = getattr(details, field)
        if type(value) is not int or not minimum <= value <= _MAX_VERSION:
            _invalid(
                field, "Reload the stop preview.", "programme_stop_version_invalid"
            )
    if (
        type(details.preview_fingerprint) is not str
        or _FINGERPRINT.fullmatch(details.preview_fingerprint) is None
    ):
        _invalid(
            "preview_fingerprint",
            "Reload the complete stop preview.",
            "programme_stop_preview_invalid",
        )
    if type(details.reason) is not str or len(details.reason) > _MAX_RAW_REASON:
        _invalid("reason", "Enter bounded text.", "programme_stop_reason_invalid")
    if any(
        unicodedata.category(character).startswith("C") for character in details.reason
    ):
        _invalid(
            "reason", "Control characters are not allowed.", "programme_stop_control"
        )
    reason = " ".join(unicodedata.normalize("NFC", details.reason).split())
    if not reason or len(reason) > _MAX_REASON:
        _invalid(
            "reason",
            f"Enter a reason of at most {_MAX_REASON} characters.",
            "programme_stop_reason_invalid",
        )
    return replace(details, reason=reason)


def programme_stop_request_digest(  # noqa: DOC502 - normalization and identity helpers raise.
    details: ProgrammeStopInput,
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    idempotency_key: UUID,
) -> str:
    """Bind canonical intent and exact actual attribution to one retry identity.

    Parameters
    ----------
    details : ProgrammeStopInput
        Original confirmation values, validated again before hashing.
    actor_id : UUID
        Actual authenticated controller, never a submitted alternate approver.
    organization_id : UUID
        Exact explicitly selected tenant, never discovered through private records.
    edition_id : UUID
        Exact independently resolved tenant and edition scope.
    idempotency_key : UUID
        Original non-nil retry identity, not regenerated after a lost response.

    Returns
    -------
    str
        Lowercase SHA-256 identity for comparison, not authorization or a receipt.

    Raises
    ------
    ValidationError
        If intent or any exact attribution identifier is malformed.

    Notes
    -----
    Correlation IDs and transport channels are deliberately absent: a deliberate
    authorized retry may arrive on another transport with a fresh trace. The
    receipt retains its original trace; this digest never proves current access.
    """
    normalized = normalize_programme_stop_input(details)
    identities = {
        "actor_id": actor_id,
        "organization_id": organization_id,
        "edition_id": edition_id,
        "idempotency_key": idempotency_key,
    }
    for field, value in identities.items():
        if type(value) is not UUID or value.int == 0:
            _invalid(field, "Use an exact identity.", "programme_stop_identity_invalid")
    payload = {
        "contract": "events.programme-stop@1",
        "profile": ["programme_operations", 1],
        **{field: str(value) for field, value in identities.items()},
        "expected_aggregate_version": normalized.expected_aggregate_version,
        "expected_lifecycle_version": normalized.expected_lifecycle_version,
        "preview_fingerprint": normalized.preview_fingerprint,
        "reason": normalized.reason,
    }
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
