"""Exact current physical access facts for accountable Programme fit decisions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Final
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Q

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import (
    PolicyDecision,
    decide_verified_principal_exact_resource,
)
from maru.events.adoption import profile_allows_adapter
from maru.events.queries import edition_adoption_profile_reference
from maru.identity.queries import resolve_active_verified_person_reference
from maru.workforce.programme_references import lock_programme_staffing_scope

from .adoption import VENUES_ACCESSIBILITY_SOURCE_ADAPTER
from .bindings import edition_space_binding_id
from .inputs import canonical_digest, normalized_source_channel
from .models import EditionSpaceMember, EditionSpaceSelection
from .scheduling_queries import (
    MAX_SCHEDULING_PHYSICAL_MEMBERS,
    MAX_SCHEDULING_SPACE_SELECTIONS,
    VENUES_VIEW_SCHEDULING_DEPENDENCIES,
    VenueSchedulingSourceDeniedError,
    VenueSchedulingSourceUnavailableError,
    _load_spaces,
)

ACCESSIBILITY_SOURCE_FIELDS: Final = frozenset({"accessibility_configuration"})


@dataclass(frozen=True, slots=True)
class VenueAccessibilityMember:
    """One selected physical member's current access facts, not a fit judgment.

    Attributes
    ----------
    member_id
        Exact physical component of the authorized selected space.
    version
        Current owner version, including access-fact and lifecycle changes.
    name
        Component name needed to distinguish a combined space's access paths.
    features
        Bounded current physical accessibility features, never a person's diagnosis.
    barriers
        Bounded known physical barriers that the assessor must consider.
    """

    member_id: UUID
    version: int
    name: str
    features: str
    barriers: str


@dataclass(frozen=True, slots=True)
class VenueAccessibilitySource:
    """Explicit selected configuration facts without unrelated operational data.

    Attributes
    ----------
    selection_id
        Exact edition-owned space selected for the placement.
    selection_version
        Current aggregate version of that selection.
    configuration_name
        Explicit edition configuration label, including locally configured combinations.
    configuration_features
        Access features of the selected catalog configuration, when one is pinned.
    public_access_info
        Current selected-space access guidance.
    members
        Complete deterministic physical membership with current access facts.
    evidence_digest
        Exact owner-derived configuration/version/content proof, not authority.
    """

    selection_id: UUID
    selection_version: int
    configuration_name: str
    configuration_features: str
    public_access_info: str
    members: tuple[VenueAccessibilityMember, ...]
    evidence_digest: str


def _admit(actor_id: UUID, organization_id: UUID, edition_id: UUID) -> None:
    if resolve_active_verified_person_reference(account_id=actor_id) is None:
        raise VenueSchedulingSourceDeniedError
    profile = edition_adoption_profile_reference(
        organization_id=organization_id, edition_id=edition_id
    )
    if profile is None or not profile_allows_adapter(
        profile.code, profile.version, VENUES_ACCESSIBILITY_SOURCE_ADAPTER
    ):
        raise VenueSchedulingSourceDeniedError


def _authorize(actor_id: UUID, space: EditionSpaceSelection) -> PolicyDecision:
    decision = decide_verified_principal_exact_resource(
        principal_id=actor_id,
        organization_id=space.organization_id,
        edition_id=space.edition_id,
        department_id=space.responsible_department_id,
        resource_binding_id=edition_space_binding_id(space.id),
        capability_code=VENUES_VIEW_SCHEDULING_DEPENDENCIES,
        requested_fields=ACCESSIBILITY_SOURCE_FIELDS,
    )
    if (
        not isinstance(decision, PolicyDecision)
        or not decision.allowed
        or not decision.fields.issuperset(ACCESSIBILITY_SOURCE_FIELDS)
    ):
        raise VenueSchedulingSourceDeniedError
    return decision


def _facts(
    spaces: tuple[EditionSpaceSelection, ...],
    *,
    organization_id: UUID,
    edition_id: UUID,
) -> tuple[VenueAccessibilitySource, ...]:
    ids = tuple(space.id for space in spaces)
    memberships = tuple(
        EditionSpaceMember.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            space_selection_id__in=ids,
        )
        .order_by("space_selection_id", "source_space_id")
        .values_list("space_selection_id", "source_space_id")[
            : MAX_SCHEDULING_PHYSICAL_MEMBERS + 1
        ]
    )
    if len(memberships) > MAX_SCHEDULING_PHYSICAL_MEMBERS:
        raise VenueSchedulingSourceUnavailableError
    members = tuple(
        EditionSpaceMember.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            space_selection_id__in=ids,
            source_space__organization_id=organization_id,
            source_space__property_id=F(
                "space_selection__venue_selection__property_id"
            ),
            source_space__is_active=True,
        )
        .order_by("space_selection_id", "source_space_id")
        .values_list(
            "space_selection_id",
            "source_space_id",
            "source_space__aggregate_version",
            "source_space__name",
            "source_space__accessibility_features",
            "source_space__known_barriers",
        )[: MAX_SCHEDULING_PHYSICAL_MEMBERS + 1]
    )
    if {(row[0], row[1]) for row in members} != set(memberships):
        raise VenueSchedulingSourceUnavailableError
    rows = tuple(
        EditionSpaceSelection.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            id__in=ids,
            lifecycle="active",
            venue_selection__lifecycle="active",
            venue_selection__property__lifecycle="active",
        )
        .filter(
            Q(selected_configuration__isnull=True)
            | Q(
                selected_configuration__organization_id=organization_id,
                selected_configuration__space_id=F("source_space_id"),
                selected_configuration__lifecycle="active",
            )
        )
        .order_by("id")
        .values(
            "id",
            "aggregate_version",
            "configuration_name",
            "public_access_info",
            "selected_configuration_id",
            "selected_configuration__aggregate_version",
            "selected_configuration__accessibility_features",
            "seated_capacity",
            "standing_capacity",
            "table_capacity",
            "fire_capacity",
            "venue_selection__aggregate_version",
            "venue_selection__property__aggregate_version",
        )
    )
    if {row["id"] for row in rows} != set(ids):
        raise VenueSchedulingSourceUnavailableError
    grouped: dict[UUID, list[VenueAccessibilityMember]] = {}
    for selection_id, member_id, version, name, features, barriers in members:
        grouped.setdefault(selection_id, []).append(
            VenueAccessibilityMember(member_id, version, name, features, barriers)
        )
    result = []
    for row in rows:
        components = tuple(grouped.get(row["id"], ()))
        if not components:
            raise VenueSchedulingSourceUnavailableError
        digest = canonical_digest(
            {
                "contract": VENUES_ACCESSIBILITY_SOURCE_ADAPTER,
                "organization_id": organization_id,
                "edition_id": edition_id,
                "configuration": row,
                "members": [asdict(member) for member in components],
            }
        )
        result.append(
            VenueAccessibilitySource(
                row["id"],
                row["aggregate_version"],
                row["configuration_name"],
                row["selected_configuration__accessibility_features"] or "",
                row["public_access_info"],
                components,
                digest,
            )
        )
    return tuple(result)


def load_venue_accessibility_sources(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    selection_ids: tuple[UUID, ...],
    correlation_id: UUID,
    source_channel: str = "programme-fit",
) -> tuple[VenueAccessibilitySource, ...]:
    """Read complete selected access facts under independent resource/field admission.

    Parameters
    ----------
    actor_id : UUID
        Current verified assessor, independently authorized by Venues.
    organization_id : UUID
        Exact expected physical owner.
    edition_id : UUID
        Exact edition owning every requested selection.
    selection_ids : tuple[UUID, ...]
        Complete distinct bounded selected-space identifiers, not a discovery filter.
    correlation_id : UUID
        Trusted attribution for required sensitive-read evidence.
    source_channel : str, default="programme-fit"
        Bounded provenance code, never a private explanation.

    Returns
    -------
    tuple[VenueAccessibilitySource, ...]
        Current exact configuration/member facts, without contacts or private bookings.

    Raises
    ------
    ValidationError
        If scope, correlation, channel or selected identifiers are malformed.

    Notes
    -----
    No current profile pins this source. Every selection requires the separate
    accessibility-configuration field, not just physical conflict permission.
    Partial, inactive, foreign or unavailable physical sources fail closed.
    Required audit failure propagates before disclosure. Callers compare source
    fingerprints again before retaining an assessment; these facts never infer
    an accessibility decision or authorize a Programme release.
    """
    if any(
        not isinstance(value, UUID)
        for value in (actor_id, organization_id, edition_id, correlation_id)
    ):
        raise ValidationError("Use typed physical source scope and correlation.")
    _admit(actor_id, organization_id, edition_id)
    if (
        not isinstance(selection_ids, tuple)
        or not 1 <= len(selection_ids) <= MAX_SCHEDULING_SPACE_SELECTIONS
        or any(not isinstance(value, UUID) for value in selection_ids)
        or len(set(selection_ids)) != len(selection_ids)
    ):
        raise ValidationError("Use a complete bounded exact space selection.")
    source_channel = normalized_source_channel(source_channel)
    with transaction.atomic():
        lock_programme_staffing_scope(
            organization_id=organization_id, edition_id=edition_id
        )
        _admit(actor_id, organization_id, edition_id)
        spaces = _load_spaces(organization_id, edition_id, tuple(sorted(selection_ids)))
        for space in spaces:
            _authorize(actor_id, space)
        result = _facts(spaces, organization_id=organization_id, edition_id=edition_id)
        _admit(actor_id, organization_id, edition_id)
        obligations = {"audit_sensitive_read"}
        for space in spaces:
            obligations.update(_authorize(actor_id, space).obligations)
        append_audit(
            AuditRecord(
                principal_kind="account",
                principal_id=actor_id,
                principal_context_id=None,
                organization_id=organization_id,
                event_edition_id=edition_id,
                capability_code=VENUES_VIEW_SCHEDULING_DEPENDENCIES,
                operation="venues.query.accessibility_configuration",
                target_type="venues.edition_spaces",
                target_id=edition_id,
                outcome="allow",
                reason_code="accessibility_configuration_authorized",
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel=source_channel,
                obligations=tuple(sorted(obligations)),
                safe_metadata={
                    "policy_version": POLICY_VERSION,
                    "target_count": len(result),
                },
                retention_class="venue-operational",
            )
        )
        return result
