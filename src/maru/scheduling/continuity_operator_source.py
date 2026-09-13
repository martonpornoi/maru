"""Private operator continuity from independent owners, never a public fallback."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from .continuity_payload import (
    ContinuityEntry,
    ContinuityFact,
    ContinuityProjection,
    encode_continuity_payload,
)
from .continuity_protocol import (
    ContinuityInvalidError,
    ContinuityScope,
    _scope_document,
    _utc,
)
from .continuity_sources import _context, _reviewed_copy, _service_day, _wayfinding
from .operator_output_rendering import (
    OPERATOR_RUN_SHEET_CONTRACT,
    render_operator_run_sheet_json,
)

if TYPE_CHECKING:
    from uuid import UUID

    from maru.workforce.operator_queries import (
        OperatorStaffingDemand,
        OperatorStaffingSnapshot,
    )

    from .operator_output_queries import OperatorRunSheet, OperatorRunSheetEntry


def _event(row: OperatorRunSheetEntry, layers: frozenset[str]) -> ContinuityEntry:
    placement = row.placement
    facts = [
        *_reviewed_copy(row.copy),
        *_wayfinding(row.room),
        _service_day(placement.day_id, placement.day_starts_at, placement.day_ends_at),
    ]
    if row.delivery is not None:
        fields = {
            "technical": row.delivery.technical,
            "accessibility": row.delivery.accessibility,
            "media": row.delivery.media,
        }
        for field in sorted(layers - {"staffing"}):
            value = fields[field]
            if value is None:
                raise ContinuityInvalidError
            facts.append(ContinuityFact(field, value))
        facts.append(
            ContinuityFact(
                "delivery_version",
                f"item {row.delivery.item_id}; revision {row.delivery.revision_id}; "
                f"version {row.delivery.version}; recorded "
                + (
                    _utc(row.delivery.occurred_at).isoformat()
                    if row.delivery.occurred_at is not None
                    else "not yet recorded"
                ),
            )
        )
    return ContinuityEntry(
        f"operator:{placement.occurrence_id}",
        "operator_event",
        row.copy.title,
        placement.envelope.setup_starts_at,
        placement.envelope.teardown_ends_at,
        placement.space_id,
        placement.day_id,
        _context(placement.envelope),
        tuple(facts),
    )


def _demand(
    row: OperatorStaffingDemand, links: tuple[ContinuityFact, ...]
) -> ContinuityEntry:
    return ContinuityEntry(
        f"demand:{row.demand_id}",
        "staffing_demand",
        row.title,
        row.starts_at,
        row.ends_at,
        None,
        None,
        None,
        (
            ContinuityFact("status", row.state),
            ContinuityFact("location", row.location),
            ContinuityFact("briefing", row.briefing),
            ContinuityFact("supervision", row.supervision),
            ContinuityFact("demand_version", str(row.version)),
            ContinuityFact("required_headcount", str(row.required_headcount)),
            *links,
            *(
                ContinuityFact(
                    "retained_work",
                    f"{work.count} {work.state}: {_utc(work.starts_at).isoformat()} to "
                    f"{_utc(work.ends_at).isoformat()}; rest until "
                    f"{_utc(work.rest_ends_at).isoformat()}. Not attendance evidence.",
                )
                for work in row.retained_work
            ),
        ),
    )


def _staffing(layer: OperatorStaffingSnapshot | None) -> tuple[ContinuityEntry, ...]:
    if layer is None:
        return ()
    links: dict[UUID, list[ContinuityFact]] = {
        row.demand_id: [] for row in layer.demands
    }
    for link in layer.links:
        links[link.demand_id].append(
            ContinuityFact(
                "programme_link",
                f"occurrence {link.occurrence_id}; binding {link.binding_id} "
                f"version {link.binding_version}; "
                + (
                    "current selection"
                    if link.current
                    else "retained predecessor, not cancelled"
                ),
            )
        )
    return tuple(_demand(row, tuple(links[row.demand_id])) for row in layer.demands)


def operator_continuity_projection(
    source: OperatorRunSheet, *, scope: ContinuityScope
) -> ContinuityProjection:
    """Minimize a complete private run sheet at the exact authenticated field ceiling.

    Parameters
    ----------
    source : OperatorRunSheet
        Fresh source whose owners independently admitted the same operator request.
    scope : ContinuityScope
        Authenticated actor and exact tenant, edition, target and requested layers.

    Returns
    -------
    ContinuityProjection
        Full preparation/delivery/teardown and separately versioned work cards.

    Raises
    ------
    ContinuityInvalidError
        If source organization, edition, target or field selection differs from scope.

    Notes
    -----
    Complete owner validation errors propagate. This transformation grants no access
    and cannot independently attest which actor obtained a caller-provided DTO.
    The authorized query wrapper supplies the actor and source together. Work demands
    appear once, retaining all current/predecessor links and anonymous interval counts.
    """
    _scope_document(scope)
    raw = render_operator_run_sheet_json(source)
    if (
        scope.audience != "private_operator"
        or scope.organization_id != source.organization_id
        or scope.edition_id != source.edition_id
        or scope.kind != source.kind.value
        or scope.target_id != source.target_id
        or frozenset(scope.layers) != source.layers
    ):
        raise ContinuityInvalidError
    reference = source.reference
    result = ContinuityProjection(
        scope,
        OPERATOR_RUN_SHEET_CONTRACT,
        hashlib.sha256(raw).hexdigest(),
        source.checked_at,
        reference.zone_name,
        reference.state.value,
        reference.pointer_version,
        reference.release_id,
        reference.published_at,
        "not_applicable",
        ("available" if source.staffing.adopted else "unadopted")
        if source.staffing is not None
        else "unrequested",
        (
            *(_event(row, source.layers) for row in source.entries),
            *_staffing(source.staffing),
        ),
    )
    encode_continuity_payload(result)
    return result
