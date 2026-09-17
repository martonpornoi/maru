"""Minimized owner references for independently admitted Programme setup.

These queries are not a directory or an authorization decision. Their platform
consumer must admit the exact organization before calling and revalidate under
the owning command locks before any write or final identifying disclosure.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import TypedDict, cast
from uuid import UUID

from django.db import connection
from django.db.models import Q

from .models import ConventionSeries, Organization, OrganizationRepresentation
from .representation_catalog import (
    REPRESENTATION_DEFINITIONS,
    representation_definition,
)
from .write_references import lock_organization_ownership, lock_series_ownership

MAX_PROGRAMME_FOUNDATION_CHOICES = 100


@dataclass(frozen=True, slots=True)
class ProgrammeFoundationChoice:
    """Label a foundation candidate without contacts or controller information.

    Attributes
    ----------
    id
        Exact owner locator, never a grant or a source snapshot.
    name, code
        Human name and stable code distinguishing duplicate names.
    """

    id: UUID
    name: str
    code: str


def programme_setup_organization_choices() -> (
    tuple[ProgrammeFoundationChoice, ...] | None
):
    """List bounded coherent roots for an independently admitted platform consumer.

    Returns
    -------
    tuple[ProgrammeFoundationChoice, ...] | None
        Complete eligible choices, or unavailable on overflow without partial data.

    Notes
    -----
    The consumer must admit current platform Identity before this internal read,
    audit disclosure and revalidate its projection after rendering. Selection must
    resolve the exact full foundation again; this inventory is not a snapshot.
    """
    roots = Q(pk__in=[])
    for definition in REPRESENTATION_DEFINITIONS.values():
        roots |= Q(
            representation__code=definition.code,
            representation__name=definition.name,
        )
    eligible = Q(lifecycle="draft") & (
        Q(representation__isnull=True)
        | (roots & Q(representation__state="provisioning"))
    )
    eligible |= Q(lifecycle="active", representation__state="active") & roots
    rows = tuple(
        Organization.objects.filter(eligible)
        .order_by("name", "slug", "id")
        .values_list("id", "name", "slug")[: MAX_PROGRAMME_FOUNDATION_CHOICES + 1]
    )
    if len(rows) > MAX_PROGRAMME_FOUNDATION_CHOICES:
        return None
    return tuple(ProgrammeFoundationChoice(*row) for row in rows)


def programme_setup_series_choices(
    *, organization_id: UUID
) -> tuple[ProgrammeFoundationChoice, ...] | None:
    """List only active series in one independently admitted exact parent.

    Parameters
    ----------
    organization_id : UUID
        Exact owner whose complete foundation the consumer has already admitted.

    Returns
    -------
    tuple[ProgrammeFoundationChoice, ...] | None
        Complete bounded choices, or unavailable for malformed scope or overflow.

    Notes
    -----
    No cross-organization series inventory or permission is supplied. The consumer
    owns current admission, final source comparison and disclosure audit.
    """
    if not isinstance(organization_id, UUID) or organization_id.int == 0:
        return None
    rows = tuple(
        ConventionSeries.objects.filter(organization_id=organization_id, is_active=True)
        .order_by("name", "slug", "id")
        .values_list("id", "name", "slug")[: MAX_PROGRAMME_FOUNDATION_CHOICES + 1]
    )
    if len(rows) > MAX_PROGRAMME_FOUNDATION_CHOICES:
        return None
    return tuple(ProgrammeFoundationChoice(*row) for row in rows)


class _OrganizationRow(TypedDict):
    """Account for nullable representation values introduced by the outer join."""

    id: UUID
    name: str
    lifecycle: str
    default_language_codes: list[str]
    default_time_zone: str
    representation__id: UUID | None
    representation__code: str | None
    representation__name: str | None
    representation__aggregate_version: int | None
    representation__state: str | None


@dataclass(frozen=True, slots=True)
class ProgrammeSetupFoundationReference:
    """Describe a complete reusable foundation without controller identities.

    Attributes
    ----------
    organization_id, organization_name, organization_lifecycle
        Exact admitted parent and current setup-relevant labels/state.
    default_language_codes, default_time_zone
        Current organization defaults; no organization property is changed.
    representation_id, representation_code, representation_version, representation_state
        Exact existing truthful root, or all absent for a Draft organization.
        No appointment, person, membership or authority value is exposed.
    series_id, series_name, series_version
        Exact active series and original version when reusing a series.
    fingerprint
        Canonical current source comparison, not permission, approval or a lock.
    """

    organization_id: UUID
    organization_name: str
    organization_lifecycle: str
    default_language_codes: tuple[str, ...]
    default_time_zone: str
    representation_id: UUID | None
    representation_code: str | None
    representation_version: int | None
    representation_state: str | None
    series_id: UUID | None
    series_name: str | None
    series_version: int | None
    fingerprint: str


def resolve_programme_setup_foundation(
    *, organization_id: UUID, series_id: UUID | None = None
) -> ProgrammeSetupFoundationReference | None:
    """Read one exact admitted organization and optional same-parent active series.

    Parameters
    ----------
    organization_id : UUID
        Organization independently authorized by the platform setup consumer.
    series_id : UUID | None, default=None
        Exact same-organization series, or no series for new-series setup.

    Returns
    -------
    ProgrammeSetupFoundationReference | None
        Complete scope-bound facts, or unavailable without foreign labels or IDs.

    Notes
    -----
    The two source reads do not promise a locked snapshot. This is preview input:
    the future setup command must lock/reload owner state and compare the complete
    fingerprint. A matching digest alone never grants authority or allows writes.
    Existing representation definitions are not upgraded or inferred here.
    """
    if (
        not isinstance(organization_id, UUID)
        or organization_id.int == 0
        or (
            series_id is not None
            and (not isinstance(series_id, UUID) or series_id.int == 0)
        )
    ):
        return None
    organization = cast(
        "_OrganizationRow | None",
        (
            Organization.objects.filter(
                id=organization_id,
                lifecycle__in=(
                    Organization.Lifecycle.DRAFT,
                    Organization.Lifecycle.ACTIVE,
                ),
            )
            .order_by()
            .values(
                "id",
                "name",
                "lifecycle",
                "default_language_codes",
                "default_time_zone",
                "representation__id",
                "representation__code",
                "representation__name",
                "representation__aggregate_version",
                "representation__state",
            )
            .first()
        ),
    )
    if organization is None:
        return None
    representation_id = organization["representation__id"]
    if representation_id is None:
        if organization["lifecycle"] != Organization.Lifecycle.DRAFT:
            return None
    else:
        definition = representation_definition(
            organization["representation__code"] or ""
        )
        expected_state = (
            OrganizationRepresentation.State.PROVISIONING
            if organization["lifecycle"] == Organization.Lifecycle.DRAFT
            else OrganizationRepresentation.State.ACTIVE
        )
        if (
            definition is None
            or organization["representation__name"] != definition.name
            or organization["representation__state"] != expected_state
        ):
            return None
    series = None
    if series_id is not None:
        series = (
            ConventionSeries.objects.filter(
                id=series_id, organization_id=organization_id, is_active=True
            )
            .order_by()
            .values("id", "name", "profile_version")
            .first()
        )
        if series is None:
            return None
    payload = {
        "source": "organizations.programme-setup-foundation@1",
        "organization": {
            "id": str(organization["id"]),
            "name": organization["name"],
            "lifecycle": organization["lifecycle"],
            "default_language_codes": organization["default_language_codes"],
            "default_time_zone": organization["default_time_zone"],
        },
        "representation": {
            "id": str(representation_id) if representation_id else None,
            "code": organization["representation__code"],
            "name": organization["representation__name"],
            "version": organization["representation__aggregate_version"],
            "state": organization["representation__state"],
        },
        "series": {
            "id": str(series["id"]),
            "name": series["name"],
            "version": series["profile_version"],
        }
        if series is not None
        else None,
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    return ProgrammeSetupFoundationReference(
        organization_id=organization["id"],
        organization_name=organization["name"],
        organization_lifecycle=organization["lifecycle"],
        default_language_codes=tuple(organization["default_language_codes"]),
        default_time_zone=organization["default_time_zone"],
        representation_id=representation_id,
        representation_code=organization["representation__code"],
        representation_version=organization["representation__aggregate_version"],
        representation_state=organization["representation__state"],
        series_id=series["id"] if series else None,
        series_name=series["name"] if series else None,
        series_version=series["profile_version"] if series else None,
        fingerprint=fingerprint,
    )


def lock_programme_setup_foundation(
    *,
    organization_id: UUID,
    expected_fingerprint: str,
    series_id: UUID | None = None,
) -> ProgrammeSetupFoundationReference | None:
    """Lock and recheck a previously admitted complete foundation snapshot.

    Parameters
    ----------
    organization_id : UUID
        Independently admitted exact organization.
    expected_fingerprint : str
        Original complete preview fingerprint, never permission.
    series_id : UUID | None, default=None
        Exact same-parent series when that level is reused.

    Returns
    -------
    ProgrammeSetupFoundationReference | None
        Current matching facts under representation, organization and series locks,
        or unavailable. The caller must already hold shared authority fences.
        A representation appearing after preview fails stale, without acquiring
        its row after the parent and reversing the canonical lock order.
    """
    if (
        not connection.in_atomic_block
        or not isinstance(expected_fingerprint, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_fingerprint) is None
    ):
        return None
    initial = resolve_programme_setup_foundation(
        organization_id=organization_id, series_id=series_id
    )
    if initial is None or initial.fingerprint != expected_fingerprint:
        return None
    if initial.representation_id is not None:
        representation_id = (
            OrganizationRepresentation.objects.select_for_update(of=("self",))
            .filter(id=initial.representation_id, organization_id=organization_id)
            .order_by()
            .values_list("id", flat=True)
            .first()
        )
        if representation_id != initial.representation_id:
            return None
    locked = (
        lock_organization_ownership(organization_id=organization_id)
        if series_id is None
        else lock_series_ownership(organization_id=organization_id, series_id=series_id)
    )
    if not locked:
        return None
    current = resolve_programme_setup_foundation(
        organization_id=organization_id, series_id=series_id
    )
    return current if current and current.fingerprint == expected_fingerprint else None
