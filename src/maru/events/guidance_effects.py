"""Minimized retained evidence for the single Guides pre-adoption effect route."""

from dataclasses import dataclass
from uuid import UUID

from django.db import DatabaseError

from maru.events.adoption import adoption_profile
from maru.events.guidance_activation_models import (
    GuidanceActivationDecision,
    GuidanceActivationReceipt,
    GuidanceActivationRequest,
)
from maru.events.guidance_activation_references import guidance_manifest_digest
from maru.events.guidance_setup_readiness import (
    guidance_setup_database_integrity_is_ready,
)

_PLAN_FIELDS = (
    "organization_id",
    "edition_id",
    "purpose",
    "source_profile_code",
    "source_profile_version",
    "target_profile_code",
    "target_profile_version",
    "source_manifest_digest",
    "target_manifest_digest",
    "request_digest",
    "operator_a_id",
    "operator_b_id",
    "expected_edition_version",
    "expected_adoption_revision",
)
_REQUEST = "events.guidance_activation_request"
_DECISION = "events.guidance_activation_decision"
_RECEIPT = "events.guidance_activation_receipt"


@dataclass(frozen=True, slots=True)
class GuidanceAdoptionEffectReference:
    """Describe a native-protected historical fact, without granting authority.

    Attributes
    ----------
    operation
        Exact version-one operation of the immutable evidence row.
    actor_id
        Person who actually performed that recorded operation.
    source_audit_id
        Original accepted mutation audit, protected by the owning native graph.
    correlation_id
        Original correlation identifier, never that of a later delivery attempt.
    """

    operation: str
    actor_id: UUID
    source_audit_id: UUID
    correlation_id: UUID


def guidance_adoption_effect_reference(
    *,
    organization_id: UUID,
    edition_id: UUID,
    aggregate_type: str,
    aggregate_id: UUID,
) -> GuidanceAdoptionEffectReference | None:
    """Resolve only exact Announcements-to-Guides retained transition evidence.

    This is machine routing of an existing fact, not a current mutation or a
    disclosure of people, reasons or content. Installed native integrity proves
    the original audit and evidence graph. Expiry, current roots and lifecycle
    are deliberately not rechecked: they cannot undo a recorded historical act.
    Before publication the owner row already exists in the same transaction;
    deferred native guards require its exact event and internal outbox at commit.

    Parameters
    ----------
    organization_id : UUID
        Exact tenant owning the candidate event.
    edition_id : UUID
        Exact non-null edition within that tenant.
    aggregate_type : str
        Closed request, decision or receipt family.
    aggregate_id : UUID
        Actual evidence row identity, not a caller-supplied parent substitution.

    Returns
    -------
    GuidanceAdoptionEffectReference | None
        Content-free original identity, or no proof for missing, mismatched or
        unavailable installed evidence. Schema and aggregate versions are one.
    """
    if (
        not isinstance(aggregate_type, str)
        or aggregate_type not in {_REQUEST, _DECISION, _RECEIPT}
        or not all(
            isinstance(value, UUID)
            for value in (organization_id, edition_id, aggregate_id)
        )
        or not guidance_setup_database_integrity_is_ready()
    ):
        return None
    try:
        return _reference(
            organization_id=organization_id,
            edition_id=edition_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
        )
    except DatabaseError:
        # An unavailable owner table is not permission to deliver the event.
        return None


def _reference(
    *,
    organization_id: UUID,
    edition_id: UUID,
    aggregate_type: str,
    aggregate_id: UUID,
) -> GuidanceAdoptionEffectReference | None:
    """Read only closed identity and source metadata from the exact owner row.

    Parameters
    ----------
    organization_id : UUID
        Exact retained tenant identifier.
    edition_id : UUID
        Exact retained edition identifier.
    aggregate_type : str
        Previously checked immutable evidence family.
    aggregate_id : UUID
        Exact immutable evidence identifier.

    Returns
    -------
    GuidanceAdoptionEffectReference | None
        Native-backed reference when the saved edge and identity match.
    """
    common = ("source_audit_id", "correlation_id")
    if aggregate_type == _REQUEST:
        row = (
            GuidanceActivationRequest.objects.filter(
                id=aggregate_id,
                organization_id=organization_id,
                edition_id=edition_id,
            )
            .values(*_PLAN_FIELDS, *common, "proposed_by_id")
            .first()
        )
        prefix, actor_field, operation = "", "proposed_by_id", "proposed"
    elif aggregate_type == _DECISION:
        row = (
            GuidanceActivationDecision.objects.filter(
                id=aggregate_id,
                request__organization_id=organization_id,
                request__edition_id=edition_id,
            )
            .values(
                *(f"request__{field}" for field in _PLAN_FIELDS),
                *common,
                "actor_id",
                "accepted",
                "request_digest",
            )
            .first()
        )
        prefix, actor_field = "request__", "actor_id"
        operation = "accepted" if row is not None and row["accepted"] else "declined"
    else:
        row = (
            GuidanceActivationReceipt.objects.filter(
                id=aggregate_id,
                organization_id=organization_id,
                edition_id=edition_id,
                request__organization_id=organization_id,
                request__edition_id=edition_id,
            )
            .values(
                *(f"request__{field}" for field in _PLAN_FIELDS),
                *common,
                "applied_by_id",
                "result_edition_version",
                "result_adoption_revision",
            )
            .first()
        )
        prefix, actor_field, operation = "request__", "applied_by_id", "activated"
    if row is None:
        return None
    plan = {field: row[f"{prefix}{field}"] for field in _PLAN_FIELDS}
    source = adoption_profile("announcements_only", 1)
    target = adoption_profile("announcements_guidance", 1)
    if (
        source is None
        or target is None
        or plan["purpose"] != "initial"
        or (plan["source_profile_code"], plan["source_profile_version"])
        != ("announcements_only", 1)
        or (plan["target_profile_code"], plan["target_profile_version"])
        != ("announcements_guidance", 1)
        or plan["source_manifest_digest"] != guidance_manifest_digest(source)
        or plan["target_manifest_digest"] != guidance_manifest_digest(target)
    ):
        return None
    if aggregate_type == _DECISION and (
        row["actor_id"] not in (plan["operator_a_id"], plan["operator_b_id"])
        or row["request_digest"] != plan["request_digest"]
        or type(row["accepted"]) is not bool
    ):
        return None
    if aggregate_type == _RECEIPT and (
        row["result_edition_version"] != plan["expected_edition_version"] + 1
        or row["result_adoption_revision"] != plan["expected_adoption_revision"] + 1
    ):
        return None
    return GuidanceAdoptionEffectReference(
        operation=operation,
        actor_id=row[actor_field],
        source_audit_id=row["source_audit_id"],
        correlation_id=row["correlation_id"],
    )
