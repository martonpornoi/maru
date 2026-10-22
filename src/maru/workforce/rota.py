"""Bounded, audited Workforce-only rota snapshots over existing Shift authority."""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from datetime import UTC
from typing import TYPE_CHECKING, Any
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied
from django.utils import timezone

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.enforcement import (
    FieldProjectionDeniedError,
    require_complete_projection,
)
from maru.authorization.policy import (
    PolicyDecision,
    decide_verified_principal_exact_edition,
    resolve_edition_target,
)
from maru.events.queries import resolve_edition_rota_reference
from maru.workforce.rota_schema import rota_schema
from maru.workforce.shift_queries import (
    SHIFT_ORGANIZER_REQUIRED_FIELDS,
    OrganizerShiftDemandItem,
    load_organizer_shift_overview,
)
from maru.workforce.structure_snapshot import repeatable_read_only_snapshot

if TYPE_CHECKING:
    from datetime import datetime

    from maru.events.queries import EditionRotaReference
    from maru.identity.models import Account

MAX_ROTA_BYTES = 16_777_216
ROTA_EDITION_FIELDS = frozenset(
    {
        "id",
        "organization_id",
        "series_id",
        "name",
        "aggregate_version",
        "lifecycle",
        "starts_on",
        "ends_on",
        "time_zone",
        "adoption_profile_code",
        "adoption_profile_version",
    }
)
LIMITATIONS = (
    "A historical operating snapshot, not proof of current coverage or readiness.",
    "A claim is not confirmation; removed commitments do not cover a Shift.",
    (
        "Only Shifts and their retained commitments are included, not a "
        "complete Workforce archive."
    ),
    (
        "Private Availability windows, identity contact fields, "
        "application/documents and decision rationales are excluded."
    ),
    (
        "No import, automatic reconciliation, restore, profile expansion "
        "or decommissioning is provided."
    ),
    (
        "Keep incumbent fallback and approved retention/disposal "
        "procedures; protect copies as personal data."
    ),
)


class RotaUnavailableError(RuntimeError):
    """A coherent complete rota cannot be safely released."""


@dataclass(frozen=True, slots=True)
class RotaSnapshot:
    """Hold internal, undisclosed snapshot content until final read admission.

    Attributes
    ----------
    edition
        Owner-projected metadata, checked in the same snapshot as Shift rows.
    payload
        Explicit portable fields only; never raw ORM serialization.
    """

    edition: EditionRotaReference
    payload: dict[str, Any]


def _authorize(
    *, actor: Account, organization_id: UUID, edition_id: UUID
) -> PolicyDecision:
    target = resolve_edition_target(
        organization_id=organization_id, edition_id=edition_id
    )
    if target is None or (
        target.adoption_profile_code,
        target.adoption_profile_version,
    ) != (
        "workforce_only",
        1,
    ):
        raise PermissionDenied
    read_decision = None
    for capability_code, fields in (
        ("events.view_basic", ROTA_EDITION_FIELDS),
        ("workforce.view_shifts", SHIFT_ORGANIZER_REQUIRED_FIELDS),
        ("workforce.manage_shifts", frozenset()),
    ):
        decision = decide_verified_principal_exact_edition(
            principal_id=actor.id,
            capability_code=capability_code,
            organization_id=organization_id,
            edition_id=edition_id,
            requested_fields=fields,
            at=timezone.now(),
        )
        if not decision.allowed:
            raise PermissionDenied
        try:
            require_complete_projection(
                required_fields=fields, permitted_fields=decision.fields
            )
        except FieldProjectionDeniedError as error:
            raise PermissionDenied from error
        if capability_code == "workforce.view_shifts":
            read_decision = decision
    if read_decision is None:
        raise PermissionDenied
    return read_decision


def can_export_rota(*, actor: Account, organization_id: UUID, edition_id: UUID) -> bool:
    """Check current export navigation authority without loading rota data.

    Parameters
    ----------
    actor : Account
        Current authenticated person.
    organization_id : UUID
        Exact organization owning the operation.
    edition_id : UUID
        Exact destination scope; context alone grants no authority.

    Returns
    -------
    bool
        Whether all source-field and management permissions currently hold.
    """
    try:
        _authorize(actor=actor, organization_id=organization_id, edition_id=edition_id)
    except PermissionDenied:
        return False
    return True


def _instant(value: datetime) -> str:
    if timezone.is_naive(value):
        raise RotaUnavailableError
    return value.astimezone(UTC).isoformat()


def _shift(item: OrganizerShiftDemandItem, zone: ZoneInfo) -> dict[str, Any]:
    demand = item.demand
    return {
        "id": str(demand.id),
        "version": demand.command_version,
        "department_name": item.department_name,
        "position_id": str(demand.position_id),
        "position_title": item.position_title,
        "title": demand.title,
        "status": demand.status,
        "starts_at": _instant(demand.starts_at),
        "ends_at": _instant(demand.ends_at),
        "local_starts_at": demand.starts_at.astimezone(zone).isoformat(),
        "local_ends_at": demand.ends_at.astimezone(zone).isoformat(),
        "location": demand.location_label,
        "briefing": demand.briefing,
        "supervision": demand.supervision_note,
        "required_headcount": demand.required_headcount,
        "break_minutes": demand.break_minutes,
        "minimum_rest_minutes": demand.minimum_rest_minutes,
        "claimed_count": item.claimed_count,
        "confirmed_count": item.confirmed_count,
        "remaining_count": item.remaining_count,
        "commitments": [
            {
                "id": str(row.commitment.id),
                "version": row.commitment.command_version,
                "display_label": row.account_label,
                "status": row.commitment.status,
                "availability_current": row.availability_current,
                "qualification_current": row.qualification_current,
                "rest_ends_at": _instant(row.commitment.rest_ends_at),
            }
            for row in item.commitments
        ],
    }


def _prepare_rota(
    *, actor: Account, organization_id: UUID, edition_id: UUID
) -> RotaSnapshot:
    """Prepare internal snapshot bytes without granting disclosure authority.

    Parameters
    ----------
    actor : Account
        Actual requester; current account state is read for every admission.
    organization_id : UUID
        Exact organization owning the operation.
    edition_id : UUID
        Independently resolved exact route scope.

    Returns
    -------
    RotaSnapshot
        Internal snapshot requiring final admission and audit before disclosure.

    Raises
    ------
    PermissionDenied
        If exact profile, full source fields or separate management authority fail.
    RotaUnavailableError
        If the owner metadata is unavailable or incoherent.

    Notes
    -----
    The adapter must finish rendering, then call ``_release_rota``. This is not an
    unaudited public data query. Existing owner bounds reject partial inventory.
    """
    if any(
        type(value) is not UUID or not value.int
        for value in (organization_id, edition_id)
    ):
        raise PermissionDenied
    with repeatable_read_only_snapshot():
        _authorize(actor=actor, organization_id=organization_id, edition_id=edition_id)
        observed_at = timezone.now()
        edition = resolve_edition_rota_reference(
            organization_id=organization_id, edition_id=edition_id
        )
        if edition is None or (edition.profile_code, edition.profile_version) != (
            "workforce_only",
            1,
        ):
            raise RotaUnavailableError
        zone = ZoneInfo(edition.time_zone)
        overview = load_organizer_shift_overview(edition=edition)
        data = {
            "format": "maru.workforce-rota",
            "version": 1,
            "observed_at": _instant(observed_at),
            "scope": {
                "organization_id": str(organization_id),
                "series_id": str(edition.series_id),
                "edition_id": str(edition_id),
                "edition_name": edition.name,
                "edition_version": edition.aggregate_version,
                "edition_lifecycle": edition.lifecycle,
                "starts_on": edition.starts_on.isoformat(),
                "ends_on": edition.ends_on.isoformat(),
                "time_zone": edition.time_zone,
                "profile_code": edition.profile_code,
                "profile_version": edition.profile_version,
            },
            "limitations": list(LIMITATIONS),
            "shifts": [_shift(item, zone) for item in overview.demands],
        }
    return RotaSnapshot(edition, data)


def _release_rota(
    *, actor: Account, snapshot: RotaSnapshot, correlation_id: UUID, representation: str
) -> None:
    """Reauthorize and append required evidence after all rendering succeeds.

    Parameters
    ----------
    actor : Account
        Original requester; never a worker or another principal.
    snapshot : RotaSnapshot
        Internal source snapshot prepared by this owner.
    correlation_id : UUID
        Server-generated request correlation, never an output payload field.
    representation : str
        Closed ``download`` or ``print`` adapter purpose.

    Raises
    ------
    RotaUnavailableError
        If source metadata moved or required adapter evidence is invalid.

    Notes
    -----
    Current read denials and audit persistence errors propagate; the adapter
    must return no content. Shift
    versions describe the captured snapshot rather than promising live freshness.
    """
    edition = snapshot.edition
    if (
        representation not in {"download", "print"}
        or type(correlation_id) is not UUID
        or not correlation_id.int
    ):
        raise RotaUnavailableError
    decision = _authorize(
        actor=actor, organization_id=edition.organization_id, edition_id=edition.id
    )
    if (
        resolve_edition_rota_reference(
            organization_id=edition.organization_id, edition_id=edition.id
        )
        != edition
    ):
        raise RotaUnavailableError
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=edition.organization_id,
            event_edition_id=edition.id,
            capability_code="workforce.view_shifts",
            operation="workforce.rota.export",
            target_type="events.event_edition",
            target_id=edition.id,
            outcome="allow",
            reason_code=decision.reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="web",
            obligations=("audit_sensitive_read",),
            changed_fields=(),
            safe_metadata={
                "policy_version": POLICY_VERSION,
                "route_name": f"{representation}-workforce-rota",
                "http_method": "GET",
            },
            retention_class="workforce-personal",
        ),
        occurred_at=timezone.now(),
    )


def _json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def rota_package(*, snapshot: RotaSnapshot, printable_html: str) -> bytes:
    """Build one bounded portable ZIP with schema, print copy and integrity hashes.

    Parameters
    ----------
    snapshot : RotaSnapshot
        Explicit owner DTO; raw model and audit serialization are prohibited.
    printable_html : str
        Fully escaped standalone print rendering with no remote assets or scripts.

    Returns
    -------
    bytes
        ZIP bytes; manifest hashes detect damage, not authenticity or authority.

    Raises
    ------
    RotaUnavailableError
        If the complete uncompressed package exceeds its 16 MiB hard ceiling.
    """
    files = {
        "rota.json": _json(snapshot.payload),
        "schema.json": _json(rota_schema()),
        "rota.html": printable_html.encode("utf-8"),
        "README.txt": (
            "Maru Workforce rota snapshot version 1\n\n"
            + "\n".join(LIMITATIONS)
            + "\n\nValidate rota.json with schema.json. Open rota.html locally and use "
            "your browser's Print command.\n"
            "UTC instants and offset-bearing local times are retained; "
            "scope.time_zone is the IANA zone.\n"
            "Identifiers are stable references, never credentials. "
            "Versions identify captured records.\n"
            "This is not an import, restore or complete history archive. "
            "Manifest SHA256 hashes detect damage, not authenticity.\n"
        ).encode("utf-8"),
    }
    files["manifest.json"] = _json(
        {
            "format": "maru.workforce-rota-manifest",
            "version": 1,
            "files": {
                name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                for name, data in sorted(files.items())
            },
        }
    )
    if sum(map(len, files.values())) > MAX_ROTA_BYTES:
        raise RotaUnavailableError
    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            entry = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            archive.writestr(entry, content)
    return output.getvalue()
