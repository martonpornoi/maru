"""Closed same-call target projections, only after owning answer admission."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from .models import ProgrammeCallFormat, ProgrammeCallTrack
from .programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from django.db.models import QuerySet

DOMAIN_REFERENCE_KINDS = frozenset({"programme.call-track", "programme.call-format"})
_MAX_CODE = 80
_MAX_LABEL = 160
_MAX_DESCRIPTION = 4000


@dataclass(frozen=True, slots=True)
class ProgrammeDomainOption:
    """Describe one entry from an independently admitted immutable call catalog.

    Attributes
    ----------
    target_id : UUID
        Exact same-call target, never a global code match.
    code : str
        Immutable source code for disambiguation.
    label : str
        Applicant-facing label.
    description : str
        Applicant-facing catalog guidance.
    """

    target_id: UUID
    code: str
    label: str
    description: str


def _target_query(
    *, organization_id: UUID, edition_id: UUID, call_id: UUID, kind: str
) -> QuerySet[ProgrammeCallTrack] | QuerySet[ProgrammeCallFormat]:
    if kind not in DOMAIN_REFERENCE_KINDS:
        raise Denied
    model = (
        ProgrammeCallTrack if kind == "programme.call-track" else ProgrammeCallFormat
    )
    return model.objects.filter(
        organization_id=organization_id,
        edition_id=edition_id,
        call_id=call_id,
        call__organization_id=organization_id,
        call__edition_id=edition_id,
    )


def _options(rows: Iterable[Mapping[str, object]]) -> tuple[ProgrammeDomainOption, ...]:
    result = []
    for row in rows:
        target, code, label, description = (
            row["id"],
            row["code"],
            row["label"],
            row["description"],
        )
        if (
            not isinstance(target, UUID)
            or not target.int
            or not isinstance(code, str)
            or not 1 <= len(code) <= _MAX_CODE
            or not isinstance(label, str)
            or not 1 <= len(label) <= _MAX_LABEL
            or not isinstance(description, str)
            or len(description) > _MAX_DESCRIPTION
        ):
            raise Denied
        result.append(ProgrammeDomainOption(target, code, label, description))
    if len({row.target_id for row in result}) != len(result):
        raise Denied
    return tuple(result)


def _domain_options(
    *, organization_id: UUID, edition_id: UUID, call_id: UUID, kind: str
) -> tuple[ProgrammeDomainOption, ...]:
    maximum = 64 if kind == "programme.call-track" else 32
    rows = tuple(
        _target_query(
            organization_id=organization_id,
            edition_id=edition_id,
            call_id=call_id,
            kind=kind,
        )
        .order_by("position", "id")
        .values("id", "code", "label", "description")[: maximum + 1]
    )
    if len(rows) > maximum:
        raise Denied
    return _options(rows)


def _domain_target(
    *,
    organization_id: UUID,
    edition_id: UUID,
    call_id: UUID,
    kind: str,
    target_id: UUID,
) -> ProgrammeDomainOption | None:
    rows = tuple(
        _target_query(
            organization_id=organization_id,
            edition_id=edition_id,
            call_id=call_id,
            kind=kind,
        )
        .filter(id=target_id)
        .values("id", "code", "label", "description")[:2]
    )
    if len(rows) > 1:
        raise Denied
    result = _options(rows)
    if result and result[0].target_id != target_id:
        raise Denied
    return result[0] if result else None


def _valid_domain_answer(
    *,
    organization_id: UUID,
    edition_id: UUID,
    call_id: UUID,
    kind: str,
    value: object,
) -> bool:
    if kind not in DOMAIN_REFERENCE_KINDS:
        return False
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    try:
        target = UUID(value)
    except ValueError:
        return False
    if not target.int or str(target) != value:
        return False
    return (
        _domain_target(
            organization_id=organization_id,
            edition_id=edition_id,
            call_id=call_id,
            kind=kind,
            target_id=target,
        )
        is not None
    )
