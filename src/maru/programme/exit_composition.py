"""Compose the closed Programme archive owner set under complete canonical locks."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction

from maru.applications.programme_authorization import (
    DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER as DEFAULT_APPS,
)
from maru.applications.programme_exit_queries import (
    load_programme_exit_applications,
    programme_exit_department_references,
)
from maru.applications.programme_exit_serialization import (
    serialize_programme_exit_applications,
)
from maru.audit.programme_exit_queries import load_programme_exit_audit
from maru.authorization.programme_exit_queries import load_programme_exit_authorization
from maru.events.programme_exit_queries import load_programme_exit_configuration
from maru.identity.queries import (
    MAX_PERSON_REFERENCE_BATCH,
    lock_account_references_for_evidence,
)
from maru.scheduling.authorization import DEFAULT_SCHEDULING_AUTHORIZER
from maru.scheduling.exit_queries import load_scheduling_exit_owner
from maru.scheduling.exit_serialization import serialize_scheduling_exit_owner
from maru.scheduling.planning_queries import SchedulingReadRequest
from maru.venues.programme_exit_queries import load_programme_exit_venues
from maru.workforce.programme_exit_queries import load_programme_exit_bindings
from maru.workforce.programme_exit_serialization import (
    serialize_programme_exit_bindings,
)
from maru.workforce.programme_references import lock_programme_staffing_scope
from maru.workforce.queries import resolve_retained_department_reference

from .archive_authorization import authorize_programme_archive_scope
from .authorization import DEFAULT_PROGRAMME_AUTHORIZER
from .catalogs import MAX_PROGRAMME_ITEMS_PER_EDITION
from .exit_archive_protocol import (
    OWNERS,
    ProgrammeArchiveFile,
    ProgrammeArchiveInvalidError,
    ProgrammeArchiveSection,
)
from .exit_owner_queries import load_programme_exit_owner
from .exit_serialization import serialize_programme_exit_owner
from .models import ProgrammeHostRelationship, ProgrammeItem
from .queries import ProgrammeQueryUnavailableError

if TYPE_CHECKING:
    from maru.applications.programme_authorization import (
        ApplicationsProgrammeAuthorizer,
    )
    from maru.scheduling.authorization import SchedulingAuthorizer

    from .authorization import ProgrammeAuthorizer


@dataclass(frozen=True, slots=True)
class ProgrammeExitCollection:
    """Private complete bounded owner sections plus exact clean file bytes.

    Attributes
    ----------
    sections, files
        Independently admitted source projections, hidden from repr.
    source_digest
        Canonical content identity excluding per-read Audit receipt IDs/timestamps.
        Not a permission, grant, signature or proof that later sources still match.
    """

    sections: tuple[ProgrammeArchiveSection, ...] = field(repr=False)
    files: tuple[ProgrammeArchiveFile, ...] = field(repr=False)
    source_digest: str


def _source_digest(
    sections: tuple[ProgrammeArchiveSection, ...],
    files: tuple[ProgrammeArchiveFile, ...],
) -> str:
    if len(sections) != len(OWNERS) or {section.owner for section in sections} != set(
        OWNERS
    ):
        raise ProgrammeArchiveInvalidError
    if any(
        section.contract != f"{section.owner}.programme-exit@1" for section in sections
    ):
        raise ProgrammeArchiveInvalidError
    if len({file.file_id for file in files}) != len(files):
        raise ProgrammeArchiveInvalidError
    payload = {
        "contract": "programme.exit-source-identity@1",
        "owners": [
            {
                "owner": section.owner,
                "contract": section.contract,
                "data": hashlib.sha256(section.data).hexdigest(),
                "schema": hashlib.sha256(section.schema).hexdigest(),
            }
            for section in sorted(sections, key=lambda row: row.owner)
            if section.owner != "audit"
        ],
        "files": [
            {
                "id": str(file.file_id),
                "size": len(file.data),
                "sha256": hashlib.sha256(file.data).hexdigest(),
            }
            for file in sorted(files, key=lambda row: row.file_id)
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _lock_closure(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    applications_authorizer: ApplicationsProgrammeAuthorizer,
    programme_authorizer: ProgrammeAuthorizer,
) -> None:
    scope = {"organization_id": organization_id, "edition_id": edition_id}
    lock_programme_staffing_scope(**scope)
    # Identifier-only owner discovery while parents/mutex prevent membership writes.
    items = tuple(
        ProgrammeItem.objects.filter(**scope)
        .order_by("id")
        .values_list("id", flat=True)[: MAX_PROGRAMME_ITEMS_PER_EDITION + 1]
    )
    if len(items) > MAX_PROGRAMME_ITEMS_PER_EDITION:
        raise ProgrammeQueryUnavailableError
    departments = programme_exit_department_references(
        **scope,
        actor_id=actor_id,
        correlation_id=correlation_id,
        authorizer=applications_authorizer,
        programme_authorizer=programme_authorizer,
    )
    for identifier in departments:
        if (
            resolve_retained_department_reference(
                **scope, department_id=identifier, lock=True
            )
            is None
        ):
            raise ProgrammeQueryUnavailableError
    people = tuple(
        sorted(
            {
                actor_id,
                *ProgrammeHostRelationship.objects.filter(
                    **scope,
                    item_id__in=items,
                )
                .order_by("account_id")
                .values_list("account_id", flat=True)
                .distinct()[: MAX_PERSON_REFERENCE_BATCH + 1],
            }
        )
    )
    if (
        len(people) > MAX_PERSON_REFERENCE_BATCH
        or lock_account_references_for_evidence(account_ids=people) != people
    ):
        raise ProgrammeQueryUnavailableError


def collect_programme_exit(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    programme_authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
    applications_authorizer: ApplicationsProgrammeAuthorizer = DEFAULT_APPS,
    scheduling_authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> ProgrammeExitCollection:
    """Read every required owner under one whole-edition source boundary.

    Parameters
    ----------
    actor_id : UUID
        Actual requester whose current source and export rights remain mandatory.
    organization_id : UUID
        Independently selected expected tenant.
    edition_id : UUID
        Exact edition, not an optional Department-filtered partial archive.
    correlation_id : UUID
        Fresh server-generated trace shared by every collection audit.
    programme_authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Extra-purpose and ordinary Programme policy with sealed test substitution.
    applications_authorizer : ApplicationsProgrammeAuthorizer, default=DEFAULT_APPS
        Independent Applications current field/relationship policy.
    scheduling_authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Independent Scheduling current planning/history policy.

    Returns
    -------
    ProgrammeExitCollection
        Complete owner set, original files and source identity, not a stored task.

    Raises
    ------
    ProgrammeArchiveInvalidError
        If scope, owner identity or duplicate file bytes are incoherent.

    Notes
    -----
    Source-owner denial, missing data, audit failure or resource overflow propagates
    without returning a partial collection. No production profile is activated.
    """
    if any(
        type(value) is not UUID or not value.int
        for value in (
            actor_id,
            organization_id,
            edition_id,
            correlation_id,
        )
    ):
        raise ProgrammeArchiveInvalidError
    args = {
        "actor_id": actor_id,
        "organization_id": organization_id,
        "edition_id": edition_id,
        "correlation_id": correlation_id,
    }

    def admit() -> None:
        authorize_programme_archive_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            requested_fields=frozenset({"source_lineage"}),
            authorizer=programme_authorizer,
        )

    admit()
    with transaction.atomic():
        _lock_closure(
            **args,
            applications_authorizer=applications_authorizer,
            programme_authorizer=programme_authorizer,
        )
        admit()
        applications = load_programme_exit_applications(
            **args,
            authorizer=applications_authorizer,
            programme_authorizer=programme_authorizer,
        )
        file_bytes: dict[UUID, bytes] = {}
        for department in applications.departments:
            for case in department.cases:
                for file in case.files:
                    if (
                        file.file_id in file_bytes
                        and file_bytes[file.file_id] != file.data
                    ):
                        raise ProgrammeArchiveInvalidError
                    file_bytes[file.file_id] = file.data
        programme = load_programme_exit_owner(
            **args, reason="Programme exit archive", authorizer=programme_authorizer
        )
        scheduling = load_scheduling_exit_owner(
            SchedulingReadRequest(**args),
            authorizer=scheduling_authorizer,
            programme_authorizer=programme_authorizer,
        )
        bindings = load_programme_exit_bindings(**args, authorizer=programme_authorizer)
        sections = (
            serialize_programme_exit_applications(
                organization_id=organization_id,
                edition_id=edition_id,
                departments=applications.departments,
            ),
            load_programme_exit_authorization(
                **args, programme_authorizer=programme_authorizer
            ),
            load_programme_exit_configuration(
                **args, programme_authorizer=programme_authorizer
            ),
            serialize_programme_exit_owner(programme),
            serialize_scheduling_exit_owner(scheduling),
            load_programme_exit_venues(
                **args, programme_authorizer=programme_authorizer
            ),
            serialize_programme_exit_bindings(bindings),
            load_programme_exit_audit(
                **args, programme_authorizer=programme_authorizer
            ),
        )
        files = tuple(
            ProgrammeArchiveFile(identifier, data)
            for identifier, data in sorted(file_bytes.items())
        )
        admit()
        return ProgrammeExitCollection(sections, files, _source_digest(sections, files))
