"""Exact released reviewed copy and separately ceilinged operator instructions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db.models import Exists, OuterRef

from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.operator_release_references import load_operator_release_reference
from maru.scheduling.operator_scope import OperatorReadRequest, operator_read

from .models import (
    ProgrammeDeliveryRevision,
    ProgrammePublicRendition,
    ProgrammePublicRenditionWithdrawal,
)
from .output_queries import ReleasedProgrammeCopy

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

DELIVERY_COLUMNS = {
    "technical": "technical_requirements",
    "accessibility": "accessibility_delivery",
    "media": "media_consent_notes",
}


@dataclass(frozen=True, slots=True)
class OperatorDeliveryInstructions:
    """Current requested instruction layers, not a historical approval snapshot.

    Attributes
    ----------
    item_id
        Exact Programme item in the independently selected operator release.
    revision_id
        Current delivery revision, or None before any delivery instructions exist.
    version
        Current immutable sequence, zero before the first delivery revision.
    occurred_at
        Current revision creation time, not the release's approval time.
    technical
        Requested technical text; None means unrequested, not an empty instruction.
    accessibility
        Requested delivery accessibility text, never a person's medical record.
    media
        Requested operational media instructions, without consent-source records.
    """

    item_id: UUID
    revision_id: UUID | None
    version: int
    occurred_at: datetime | None
    technical: str | None
    accessibility: str | None
    media: str | None


def load_operator_programme_copy(
    request: OperatorReadRequest, *, expected_release_id: UUID | None
) -> tuple[ReleasedProgrammeCopy, ...]:
    """Read exact selected reviewed text under independent operator-copy authority.

    Parameters
    ----------
    request : OperatorReadRequest
        Exact purpose and attribution; its scope is independently resolved here.
    expected_release_id : UUID | None
        Optimistic current identity, never authority over arbitrary history.

    Returns
    -------
    tuple[ReleasedProgrammeCopy, ...]
        Complete distinct reviewed renditions in stable identity order.

    Raises
    ------
    SchedulingUnavailableError
        If selected copy is missing, withdrawn, inconsistent or the release moves.

    Notes
    -----
    Admission/field denial propagates SchedulingAuthorizationDeniedError even
    for an empty scope. No latest-copy fallback or working/reviewer/host read is
    allowed. Anonymous public admission is neither called nor substituted.
    """
    with operator_read(
        request,
        capability="programme.view_operator_copy",
        fields=frozenset({"reviewed_copy"}),
    ):
        reference = load_operator_release_reference(request)
        if reference.release_id != expected_release_id:
            raise SchedulingUnavailableError
        selected = {
            row.public_rendition_id: row.item_id for row in reference.occurrences
        }
        if any(
            selected[row.public_rendition_id] != row.item_id
            for row in reference.occurrences
        ):
            raise SchedulingUnavailableError
        rows = tuple(
            ProgrammePublicRendition.objects.filter(
                organization_id=request.organization_id,
                edition_id=request.edition_id,
                item__organization_id=request.organization_id,
                item__edition_id=request.edition_id,
                id__in=selected,
            )
            .annotate(
                is_withdrawn=Exists(
                    ProgrammePublicRenditionWithdrawal.objects.filter(
                        rendition_id=OuterRef("pk")
                    )
                )
            )
            .order_by("id")
            .values_list(
                "id",
                "item_id",
                "public_title",
                "public_summary",
                "public_content_note",
                "is_withdrawn",
            )[: len(selected) + 1]
        )
        if len(rows) != len(selected) or any(
            selected[identifier] != item or withdrawn
            for identifier, item, _title, _summary, _note, withdrawn in rows
        ):
            raise SchedulingUnavailableError
        if load_operator_release_reference(request) != reference:
            raise SchedulingUnavailableError
        return tuple(
            ReleasedProgrammeCopy(identifier, title, summary, note)
            for identifier, _item, title, summary, note, _withdrawn in rows
        )


def _delivery_rows(
    request: OperatorReadRequest, selected: set[UUID], fields: frozenset[str]
) -> tuple[OperatorDeliveryInstructions, ...]:
    columns = tuple(DELIVERY_COLUMNS[field] for field in sorted(fields))
    rows = {
        row["item_id"]: row
        for row in ProgrammeDeliveryRevision.objects.filter(
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            item__organization_id=request.organization_id,
            item__edition_id=request.edition_id,
            item_id__in=selected,
        )
        .order_by("item_id", "-sequence")
        .distinct("item_id")
        .values("id", "item_id", "sequence", "occurred_at", *columns)[
            : len(selected) + 1
        ]
    }
    result = []
    for item in sorted(selected, key=str):
        row = rows.get(item, {})
        result.append(
            OperatorDeliveryInstructions(
                item,
                row.get("id"),
                row.get("sequence", 0),
                row.get("occurred_at"),
                *(
                    row.get(DELIVERY_COLUMNS[field], "") if field in fields else None
                    for field in ("technical", "accessibility", "media")
                ),
            )
        )
    return tuple(result)


def load_operator_delivery_instructions(
    request: OperatorReadRequest,
    *,
    expected_release_id: UUID | None,
    fields: frozenset[str],
) -> tuple[OperatorDeliveryInstructions, ...]:
    """Read only explicitly requested current technical/accessibility/media fields.

    Parameters
    ----------
    request : OperatorReadRequest
        Exact operator scope, independently admitted before content selection.
    expected_release_id : UUID | None
        Optimistic current release identity, not a supplied item permission list.
    fields : frozenset[str]
        Nonempty subset of the three closed delivery fields, individually ceilinged.

    Returns
    -------
    tuple[OperatorDeliveryInstructions, ...]
        Complete selected items with current versions; unrequested fields are None.

    Raises
    ------
    SchedulingUnavailableError
        If release or current requested owner evidence changes during the read.

    Notes
    -----
    Malformed or insufficient field authority propagates a uniform
    SchedulingAuthorizationDeniedError. Empty approved membership still requires
    requested-layer authority. Actor/reason and every unrequested text column
    are excluded from the query, not merely removed after materialization.
    """
    with operator_read(
        request, capability="programme.view_operator_delivery", fields=fields
    ):
        reference = load_operator_release_reference(request)
        if reference.release_id != expected_release_id:
            raise SchedulingUnavailableError
        selected = {row.item_id for row in reference.occurrences}
        result = _delivery_rows(request, selected, fields)
        if (
            _delivery_rows(request, selected, fields) != result
            or load_operator_release_reference(request) != reference
        ):
            raise SchedulingUnavailableError
        return result
