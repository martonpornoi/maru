from __future__ import annotations

import pytest

from maru.programme.catalogs import (
    PROGRAMME_ACCEPTED_APPLICATION_SOURCE,
    PROGRAMME_ITEM_SOURCE_DEFINITIONS,
    PROGRAMME_LAYER_FIELD_CEILINGS,
    PROGRAMME_LAYER_READINESS_DEPENDENCIES,
    PROGRAMME_ORGANIZER_CORE_SOURCE,
    ProgrammeCommandOperation,
    ProgrammeInformationLayer,
    ProgrammeItemKind,
    ProgrammeItemLifecycle,
    ProgrammeProvenanceKind,
    ProgrammeReadinessConcern,
    ProgrammeReadinessDisposition,
    ProgrammeReadinessEvidenceState,
    ProgrammeReadinessProjectionState,
    text_choices,
)


def _values(enum_type):
    return tuple(member.value for member in enum_type)


def test_programme_catalogs_are_exact_and_closed() -> None:
    assert _values(ProgrammeItemKind) == (
        "ceremony",
        "break",
        "announcement",
        "organizer_core",
    )
    assert _values(ProgrammeProvenanceKind) == (
        "organizer_core",
        "applications_accepted",
    )
    assert _values(ProgrammeItemLifecycle) == ("active", "retired")
    assert _values(ProgrammeReadinessDisposition) == (
        "required",
        "not_applicable",
    )
    assert _values(ProgrammeReadinessEvidenceState) == (
        "satisfied",
        "blocked",
        "unavailable",
    )
    assert _values(ProgrammeReadinessProjectionState) == (
        "required",
        "satisfied",
        "blocked",
        "not_applicable",
        "stale",
        "unavailable",
    )
    assert _values(ProgrammeCommandOperation) == (
        "item_create",
        "working_revise",
        "delivery_revise",
        "discussion_append",
        "readiness_configure",
        "readiness_record",
        "public_rendition_record",
    )


def test_item_source_catalog_rejects_free_external_identity() -> None:
    organizer = PROGRAMME_ITEM_SOURCE_DEFINITIONS[PROGRAMME_ORGANIZER_CORE_SOURCE]
    accepted = PROGRAMME_ITEM_SOURCE_DEFINITIONS[PROGRAMME_ACCEPTED_APPLICATION_SOURCE]
    assert organizer.provenance_kind is ProgrammeProvenanceKind.ORGANIZER_CORE
    assert organizer.requires_object is False
    assert accepted.provenance_kind is ProgrammeProvenanceKind.APPLICATIONS_ACCEPTED
    assert accepted.requires_object is True
    with pytest.raises(TypeError):
        PROGRAMME_ITEM_SOURCE_DEFINITIONS["unregistered"] = organizer


def test_layer_catalog_separates_private_public_and_readiness_fields() -> None:
    working = PROGRAMME_LAYER_FIELD_CEILINGS[ProgrammeInformationLayer.WORKING]
    delivery = PROGRAMME_LAYER_FIELD_CEILINGS[ProgrammeInformationLayer.DELIVERY]
    public = PROGRAMME_LAYER_FIELD_CEILINGS[ProgrammeInformationLayer.PUBLIC_RENDITION]
    assert "internal_title" in working
    assert "public_title" not in working
    assert "technical_requirements" in delivery
    assert "technical_requirements" not in public
    assert {"public_title", "public_summary"} <= public


def test_readiness_dependencies_are_explicit_and_immutable() -> None:
    working = PROGRAMME_LAYER_READINESS_DEPENDENCIES[ProgrammeInformationLayer.WORKING]
    delivery = PROGRAMME_LAYER_READINESS_DEPENDENCIES[
        ProgrammeInformationLayer.DELIVERY
    ]
    assert working == frozenset({ProgrammeReadinessConcern.PUBLIC_COPY})
    assert delivery == frozenset(
        {
            ProgrammeReadinessConcern.TECHNICAL_NEEDS,
            ProgrammeReadinessConcern.ACCESSIBILITY_DELIVERY,
            ProgrammeReadinessConcern.MEDIA_CONSENT,
        }
    )
    assert (
        PROGRAMME_LAYER_READINESS_DEPENDENCIES[
            ProgrammeInformationLayer.PUBLIC_RENDITION
        ]
        == frozenset()
    )
    with pytest.raises(TypeError):
        PROGRAMME_LAYER_READINESS_DEPENDENCIES["future"] = frozenset()


def test_text_choices_preserves_catalog_order_and_labels() -> None:
    assert text_choices(ProgrammeItemLifecycle) == (
        ("active", "Active"),
        ("retired", "Retired"),
    )
