"""Events-owned historical qualification facts for Guidance responsibility issuance."""

import hashlib
import json
from dataclasses import asdict, dataclass, is_dataclass
from uuid import UUID

from maru.events.adoption import AdoptionProfile, adoption_profile
from maru.events.guidance_activation_models import GuidanceActivationReceipt

_INDEPENDENT_PAIR_SIZE = 2


def _canonical(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return _canonical(asdict(value))
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (set, frozenset)):
        return sorted(
            (_canonical(item) for item in value),
            key=lambda item: json.dumps(item, sort_keys=True),
        )
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    return value


def guidance_manifest_digest(profile: AdoptionProfile) -> str:
    """Hash the complete exact code-owned manifest used in a retained preview.

    Parameters
    ----------
    profile : AdoptionProfile
        The complete immutable adoption manifest to fingerprint.

    Returns
    -------
    str
        The admitted immutable result; it grants no additional authority.
    """
    return hashlib.sha256(
        json.dumps(
            _canonical(asdict(profile)),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class GuidanceActivationQualification:
    """Retain the exact accepted principals and edition without granting authority.

    Attributes
    ----------
    activation_id : UUID
        Exact activation receipt whose accepted terms qualify this issuance.
    request_id : UUID
        Opaque identity of the retained immutable request.
    organization_id : UUID
        Exact organization owning this event and its evidence.
    edition_id : UUID
        Exact event edition within the owning organization.
    representation_id : UUID
        Identity of the organization accountable representation.
    operator_a_id : UUID
        First person named by the retained two-person ceremony.
    operator_b_id : UUID
        Second person named by the retained two-person ceremony.
    purpose : str
        Whether the ceremony establishes initial authority or recovers lost
        authority.
    reason : str
        Private accountable explanation retained with the request.
    correlation_id : UUID
        Audit trace linking this qualification to the activation attempt.
    """

    activation_id: UUID
    request_id: UUID
    organization_id: UUID
    edition_id: UUID
    representation_id: UUID
    operator_a_id: UUID
    operator_b_id: UUID
    purpose: str
    reason: str
    correlation_id: UUID


def guidance_activation_qualification(
    *, activation_id: UUID
) -> GuidanceActivationQualification | None:
    """Resolve the original accepted responsibility evidence.

    Resolve original authenticated decisions; current lineage is checked separately.

    Parameters
    ----------
    activation_id : UUID
        Exact retained adoption receipt qualifying this issuance.

    Returns
    -------
    GuidanceActivationQualification | None
        The admitted immutable result; it grants no additional authority.
    """
    row = (
        GuidanceActivationReceipt.objects.select_related("request")
        .filter(id=activation_id)
        .first()
    )
    if row is None:
        return None
    request = row.request
    source = adoption_profile(
        request.source_profile_code, request.source_profile_version
    )
    target = adoption_profile(
        request.target_profile_code, request.target_profile_version
    )
    decisions = tuple(
        request.decisions.order_by("actor_id").values(
            "actor_id", "accepted", "request_digest", "created_at"
        )
    )
    if (
        source is None
        or target is None
        or request.organization_id != row.organization_id
        or request.edition_id != row.edition_id
        or row.applied_by_id != request.proposed_by_id
        or len(decisions) != _INDEPENDENT_PAIR_SIZE
        or {decision["actor_id"] for decision in decisions}
        != {request.operator_a_id, request.operator_b_id}
        or any(
            not decision["accepted"]
            or decision["request_digest"] != request.request_digest
            or decision["created_at"] > request.expires_at
            for decision in decisions
        )
        or row.created_at > request.expires_at
        or row.result_adoption_revision != request.expected_adoption_revision + 1
        or row.result_edition_version != request.expected_edition_version + 1
        or guidance_manifest_digest(source) != request.source_manifest_digest
        or guidance_manifest_digest(target) != request.target_manifest_digest
    ):
        return None
    return GuidanceActivationQualification(
        activation_id=row.id,
        request_id=request.id,
        organization_id=row.organization_id,
        edition_id=row.edition_id,
        representation_id=request.representation_id,
        operator_a_id=request.operator_a_id,
        operator_b_id=request.operator_b_id,
        purpose=request.purpose,
        reason=request.reason,
        correlation_id=row.correlation_id,
    )
