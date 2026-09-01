"""Closed, immutable catalogs for the dormant Programme bounded context."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

MAX_PROGRAMME_TITLE_LENGTH: Final = 240
MAX_PROGRAMME_SUMMARY_LENGTH: Final = 2_000
MAX_PROGRAMME_PRIVATE_TEXT_LENGTH: Final = 5_000
MAX_PROGRAMME_EVIDENCE_NOTE_LENGTH: Final = 2_000
MAX_PROGRAMME_PUBLIC_CONTENT_NOTE_LENGTH: Final = 500
MAX_PROGRAMME_REASON_LENGTH: Final = 1_000
MAX_PROGRAMME_SOURCE_CHANNEL_LENGTH: Final = 32
MAX_PROGRAMME_SOURCE_CODE_LENGTH: Final = 80

MAX_PROGRAMME_ITEMS_PER_EDITION: Final = 1_000
MAX_PROGRAMME_LAYER_REVISIONS: Final = 1_000
MAX_PROGRAMME_DISCUSSION_ENTRIES: Final = 2_000
MAX_PROGRAMME_PUBLIC_RENDITIONS: Final = 1_000
MAX_PROGRAMME_READINESS_EVIDENCE: Final = 2_000


class ProgrammeItemKind(StrEnum):
    """Kinds supported by the organizer-core creation command."""

    CEREMONY = "ceremony"
    BREAK = "break"
    ANNOUNCEMENT = "announcement"
    ORGANIZER_CORE = "organizer_core"


class ProgrammeProvenanceKind(StrEnum):
    """Structural origins for canonical Programme items."""

    ORGANIZER_CORE = "organizer_core"
    APPLICATIONS_ACCEPTED = "applications_accepted"


class ProgrammeItemLifecycle(StrEnum):
    """Lifecycle states independent from readiness and future publication."""

    ACTIVE = "active"
    RETIRED = "retired"


class ProgrammeReadinessConcern(StrEnum):
    """Configured concerns whose evidence is evaluated independently."""

    PUBLIC_COPY = "public_copy"
    HOST_CONFIRMATION = "host_confirmation"
    TECHNICAL_NEEDS = "technical_needs"
    ACCESSIBILITY_DELIVERY = "accessibility_delivery"
    MEDIA_CONSENT = "media_consent"
    SCHEDULE_AVAILABILITY = "schedule_availability"
    REQUIRED_FILES = "required_files"


class ProgrammeReadinessDisposition(StrEnum):
    """Whether one configured readiness concern applies to an item."""

    REQUIRED = "required"
    NOT_APPLICABLE = "not_applicable"


class ProgrammeReadinessEvidenceState(StrEnum):
    """Evidence states retained without deriving a score or percentage."""

    SATISFIED = "satisfied"
    BLOCKED = "blocked"
    UNAVAILABLE = "unavailable"


class ProgrammeReadinessProjectionState(StrEnum):
    """Complete explainable states returned by readiness projections."""

    REQUIRED = "required"
    SATISFIED = "satisfied"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


class ProgrammeInformationLayer(StrEnum):
    """Structurally separated Programme information layers."""

    ITEM = "item"
    WORKING = "working"
    DELIVERY = "delivery"
    DEPARTMENT_DISCUSSION = "department_discussion"
    READINESS = "readiness"
    PUBLIC_RENDITION = "public_rendition"


class ProgrammeCommandOperation(StrEnum):
    """Successful mutations represented by immutable command receipts."""

    ITEM_CREATE = "item_create"
    WORKING_REVISE = "working_revise"
    DELIVERY_REVISE = "delivery_revise"
    DISCUSSION_APPEND = "discussion_append"
    READINESS_CONFIGURE = "readiness_configure"
    READINESS_RECORD = "readiness_record"
    PUBLIC_RENDITION_RECORD = "public_rendition_record"


PROGRAMME_ORGANIZER_CORE_SOURCE: Final = "programme.source.organizer-core@1"
PROGRAMME_ACCEPTED_APPLICATION_SOURCE: Final = (
    "programme.source.applications-accepted@1"
)

PROGRAMME_OPERATOR_ATTESTATION_SOURCE: Final = (
    "programme.evidence.operator-attestation@1"
)
PROGRAMME_PUBLIC_RENDITION_SOURCE: Final = "programme.evidence.public-rendition@1"
PROGRAMME_WORKING_REVISION_SOURCE: Final = "programme.evidence.working-revision@1"
PROGRAMME_DELIVERY_REVISION_SOURCE: Final = "programme.evidence.delivery-revision@1"


@dataclass(frozen=True, slots=True)
class ProgrammeSourceDefinition:
    """Describe one exact structural source contract.

    Attributes
    ----------
    code
        Stable versioned source code.
    provenance_kind
        Required item provenance for structural sources, when applicable.
    requires_object
        Whether the source must carry an exact object and version.
    """

    code: str
    provenance_kind: ProgrammeProvenanceKind | None
    requires_object: bool


PROGRAMME_ITEM_SOURCE_DEFINITIONS = MappingProxyType(
    {
        PROGRAMME_ORGANIZER_CORE_SOURCE: ProgrammeSourceDefinition(
            code=PROGRAMME_ORGANIZER_CORE_SOURCE,
            provenance_kind=ProgrammeProvenanceKind.ORGANIZER_CORE,
            requires_object=False,
        ),
        PROGRAMME_ACCEPTED_APPLICATION_SOURCE: ProgrammeSourceDefinition(
            code=PROGRAMME_ACCEPTED_APPLICATION_SOURCE,
            provenance_kind=ProgrammeProvenanceKind.APPLICATIONS_ACCEPTED,
            requires_object=True,
        ),
    }
)

PROGRAMME_EVIDENCE_SOURCE_DEFINITIONS = MappingProxyType(
    {
        PROGRAMME_OPERATOR_ATTESTATION_SOURCE: ProgrammeSourceDefinition(
            code=PROGRAMME_OPERATOR_ATTESTATION_SOURCE,
            provenance_kind=None,
            requires_object=False,
        ),
        PROGRAMME_PUBLIC_RENDITION_SOURCE: ProgrammeSourceDefinition(
            code=PROGRAMME_PUBLIC_RENDITION_SOURCE,
            provenance_kind=None,
            requires_object=True,
        ),
        PROGRAMME_WORKING_REVISION_SOURCE: ProgrammeSourceDefinition(
            code=PROGRAMME_WORKING_REVISION_SOURCE,
            provenance_kind=None,
            requires_object=True,
        ),
        PROGRAMME_DELIVERY_REVISION_SOURCE: ProgrammeSourceDefinition(
            code=PROGRAMME_DELIVERY_REVISION_SOURCE,
            provenance_kind=None,
            requires_object=True,
        ),
    }
)

PROGRAMME_EVIDENCE_SOURCE_ALLOWED_CONCERNS = MappingProxyType(
    {
        PROGRAMME_OPERATOR_ATTESTATION_SOURCE: frozenset(
            concern.value for concern in ProgrammeReadinessConcern
        ),
        PROGRAMME_WORKING_REVISION_SOURCE: frozenset(
            {ProgrammeReadinessConcern.PUBLIC_COPY.value}
        ),
        PROGRAMME_PUBLIC_RENDITION_SOURCE: frozenset(
            {ProgrammeReadinessConcern.PUBLIC_COPY.value}
        ),
        PROGRAMME_DELIVERY_REVISION_SOURCE: frozenset(
            {
                ProgrammeReadinessConcern.TECHNICAL_NEEDS.value,
                ProgrammeReadinessConcern.ACCESSIBILITY_DELIVERY.value,
                ProgrammeReadinessConcern.MEDIA_CONSENT.value,
            }
        ),
    }
)

PROGRAMME_LAYER_READINESS_DEPENDENCIES = MappingProxyType(
    {
        ProgrammeInformationLayer.ITEM.value: frozenset(),
        ProgrammeInformationLayer.WORKING.value: frozenset(
            {ProgrammeReadinessConcern.PUBLIC_COPY.value}
        ),
        ProgrammeInformationLayer.DELIVERY.value: frozenset(
            {
                ProgrammeReadinessConcern.TECHNICAL_NEEDS.value,
                ProgrammeReadinessConcern.ACCESSIBILITY_DELIVERY.value,
                ProgrammeReadinessConcern.MEDIA_CONSENT.value,
            }
        ),
        ProgrammeInformationLayer.DEPARTMENT_DISCUSSION.value: frozenset(),
        ProgrammeInformationLayer.READINESS.value: frozenset(),
        ProgrammeInformationLayer.PUBLIC_RENDITION.value: frozenset(),
    }
)

PROGRAMME_LAYER_FIELD_CEILINGS = MappingProxyType(
    {
        ProgrammeInformationLayer.ITEM.value: frozenset(
            {"id", "kind", "provenance_kind", "lifecycle", "aggregate_version"}
        ),
        ProgrammeInformationLayer.WORKING.value: frozenset(
            {"internal_title", "working_summary", "item_version"}
        ),
        ProgrammeInformationLayer.DELIVERY.value: frozenset(
            {
                "technical_requirements",
                "accessibility_delivery",
                "media_consent_notes",
                "item_version",
            }
        ),
        ProgrammeInformationLayer.DEPARTMENT_DISCUSSION.value: frozenset(
            {
                "sequence",
                "body",
                "actor_id",
                "reason",
                "occurred_at",
                "item_version",
            }
        ),
        ProgrammeInformationLayer.READINESS.value: frozenset(
            {
                "concern",
                "state",
                "requirement_version",
                "dependency_version",
                "evidence_requirement_version",
                "evidence_dependency_version",
                "source_code",
                "source_version",
            }
        ),
        ProgrammeInformationLayer.PUBLIC_RENDITION.value: frozenset(
            {
                "rendition_number",
                "public_title",
                "public_summary",
                "public_content_note",
            }
        ),
    }
)

PROGRAMME_READINESS_HISTORY_FIELD_CEILING = frozenset(
    {
        "concern",
        "kind",
        "sequence",
        "item_version",
        "requirement_version",
        "dependency_version",
        "disposition",
        "state",
        "source_code",
        "source_version",
        "note",
        "actor_id",
        "reason",
        "occurred_at",
    }
)

PROGRAMME_WORKING_HISTORY_FIELD_CEILING = frozenset(
    {
        "sequence",
        "internal_title",
        "working_summary",
        "actor_id",
        "reason",
        "occurred_at",
        "item_version",
    }
)

PROGRAMME_DELIVERY_HISTORY_FIELD_CEILING = frozenset(
    {
        "sequence",
        "technical_requirements",
        "accessibility_delivery",
        "media_consent_notes",
        "actor_id",
        "reason",
        "occurred_at",
        "item_version",
    }
)

PROGRAMME_PUBLIC_COPY_REVIEW_HISTORY_FIELD_CEILING = frozenset(
    {
        "rendition_number",
        "source_item_version",
        "public_title",
        "public_summary",
        "public_content_note",
        "actor_id",
        "reason",
        "occurred_at",
    }
)


def text_choices[ChoiceT: StrEnum](
    enum_type: type[ChoiceT],
) -> tuple[tuple[str, str], ...]:
    """Return deterministic Django choices for one closed string enum.

    Parameters
    ----------
    enum_type : type[ChoiceT]
        Closed string enum whose literals become Django choices.

    Returns
    -------
    tuple[tuple[str, str], ...]
        Ordered value and human-readable label pairs.
    """
    return tuple(
        (member.value, member.name.replace("_", " ").title()) for member in enum_type
    )


__all__ = [
    "MAX_PROGRAMME_DISCUSSION_ENTRIES",
    "MAX_PROGRAMME_EVIDENCE_NOTE_LENGTH",
    "MAX_PROGRAMME_ITEMS_PER_EDITION",
    "MAX_PROGRAMME_LAYER_REVISIONS",
    "MAX_PROGRAMME_PRIVATE_TEXT_LENGTH",
    "MAX_PROGRAMME_PUBLIC_CONTENT_NOTE_LENGTH",
    "MAX_PROGRAMME_PUBLIC_RENDITIONS",
    "MAX_PROGRAMME_READINESS_EVIDENCE",
    "MAX_PROGRAMME_REASON_LENGTH",
    "MAX_PROGRAMME_SOURCE_CHANNEL_LENGTH",
    "MAX_PROGRAMME_SOURCE_CODE_LENGTH",
    "MAX_PROGRAMME_SUMMARY_LENGTH",
    "MAX_PROGRAMME_TITLE_LENGTH",
    "PROGRAMME_ACCEPTED_APPLICATION_SOURCE",
    "PROGRAMME_DELIVERY_HISTORY_FIELD_CEILING",
    "PROGRAMME_DELIVERY_REVISION_SOURCE",
    "PROGRAMME_EVIDENCE_SOURCE_ALLOWED_CONCERNS",
    "PROGRAMME_EVIDENCE_SOURCE_DEFINITIONS",
    "PROGRAMME_ITEM_SOURCE_DEFINITIONS",
    "PROGRAMME_LAYER_FIELD_CEILINGS",
    "PROGRAMME_LAYER_READINESS_DEPENDENCIES",
    "PROGRAMME_OPERATOR_ATTESTATION_SOURCE",
    "PROGRAMME_ORGANIZER_CORE_SOURCE",
    "PROGRAMME_PUBLIC_COPY_REVIEW_HISTORY_FIELD_CEILING",
    "PROGRAMME_PUBLIC_RENDITION_SOURCE",
    "PROGRAMME_READINESS_HISTORY_FIELD_CEILING",
    "PROGRAMME_WORKING_HISTORY_FIELD_CEILING",
    "PROGRAMME_WORKING_REVISION_SOURCE",
    "ProgrammeCommandOperation",
    "ProgrammeInformationLayer",
    "ProgrammeItemKind",
    "ProgrammeItemLifecycle",
    "ProgrammeProvenanceKind",
    "ProgrammeReadinessConcern",
    "ProgrammeReadinessDisposition",
    "ProgrammeReadinessEvidenceState",
    "ProgrammeReadinessProjectionState",
    "ProgrammeSourceDefinition",
    "text_choices",
]
