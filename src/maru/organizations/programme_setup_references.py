"""Minimized owner references for independently admitted Programme setup.

These queries are not a directory or an authorization decision. Their platform
consumer must admit the exact organization before calling and revalidate under
the owning command locks before any write or final identifying disclosure.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TypedDict, cast
from uuid import UUID

from .models import ConventionSeries, Organization, OrganizationRepresentation
from .representation_catalog import representation_definition


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
