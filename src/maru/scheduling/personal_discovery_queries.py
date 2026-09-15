"""Complete purpose-based personal edition discovery without timetable contents."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from uuid import UUID

from django.db import DatabaseError, transaction

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import PolicyDecision
from maru.events.personal_timetable_queries import (
    PersonalTimetableEditionChoice,
    resolve_personal_timetable_edition_choice,
)
from maru.events.queries import (
    EditionAdoptionProfileReference,
    edition_adoption_profile_reference,
)
from maru.events.write_references import lock_edition_ownership
from maru.identity.queries import (
    ActiveVerifiedPersonReference,
    resolve_active_verified_person_reference,
)
from maru.organizations.personal_timetable_references import (
    PersonalTimetableOrganizerLabels,
    resolve_personal_timetable_organizer_labels,
)
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.personal_scope_references import (
    PersonalHostScopeProof,
    PersonalHostScopeSet,
    personal_host_scope_candidates,
    personal_host_scope_proof,
)
from maru.programme.queries import ProgrammeQueryUnavailableError
from maru.workforce.personal_scope_references import (
    PersonalShiftScopeProof,
    PersonalShiftScopeSet,
    personal_shift_scope_candidates,
    personal_shift_scope_proof,
)
from maru.workforce.shift_commands import (
    ShiftAuthorizationDeniedError,
    ShiftUnavailableError,
)

from .authorization import SchedulingAuthorizationDeniedError as Denied
from .authorization import authorize_scheduling_scope
from .command_support import SchedulingUnavailableError as Unavailable
from .personal_output_queries import _adopted_layers, authorize_personal_timetable_scope

MAX_PERSONAL_TIMETABLE_EDITIONS = 256
_SCOPE_PAIR_SIZE = 2


@dataclass(frozen=True, slots=True)
class PersonalEditionChoice:
    """Current minimal owner labels for one independently proven own purpose.

    Attributes
    ----------
    edition
        Exact edition/series attribution, human name/code and source version.
    organizer
        Current organization/series names and disambiguating human codes only.
    """

    edition: PersonalTimetableEditionChoice
    organizer: PersonalTimetableOrganizerLabels


@dataclass(frozen=True, slots=True)
class PersonalEditionCatalog:
    """Complete personal choices with private comparison evidence.

    Attributes
    ----------
    actor_id
        Exact authenticated verified person; never a client-selected subject.
    choices
        Complete own-purpose choices, without timetable, invitation or work content.
    source_fingerprint
        Server-only evidence comparison; not an access token or browser value.
    """

    actor_id: UUID
    choices: tuple[PersonalEditionChoice, ...]
    source_fingerprint: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class _Admission:
    organization_id: UUID
    edition_id: UUID
    profile: EditionAdoptionProfileReference
    hosting: bool
    workforce: bool
    scheduling: PolicyDecision | None


@dataclass(frozen=True, slots=True)
class _Purpose:
    admission: _Admission
    hosting: PersonalHostScopeProof | None
    workforce: PersonalShiftScopeProof | None
    choice: PersonalEditionChoice | None


def _uuid(value: object) -> bool:
    return type(value) is UUID and bool(value.int)


def _person(actor_id: UUID, *, lock: bool = False) -> None:
    reference = resolve_active_verified_person_reference(account_id=actor_id, lock=lock)
    if (
        not isinstance(reference, ActiveVerifiedPersonReference)
        or reference.account_id != actor_id
    ):
        raise Denied


def _candidates(actor_id: UUID) -> tuple[PersonalHostScopeSet, PersonalShiftScopeSet]:
    hosting = personal_host_scope_candidates(actor_id=actor_id)
    workforce = personal_shift_scope_candidates(actor_id=actor_id)
    if not isinstance(hosting, PersonalHostScopeSet) or not isinstance(
        workforce, PersonalShiftScopeSet
    ):
        raise Unavailable
    for source in (hosting, workforce):
        if (
            source.actor_id != actor_id
            or type(source.scopes) is not tuple
            or len(source.scopes) > MAX_PERSONAL_TIMETABLE_EDITIONS
        ):
            raise Unavailable
        if any(
            type(pair) is not tuple
            or len(pair) != _SCOPE_PAIR_SIZE
            or not all(_uuid(value) for value in pair)
            for pair in source.scopes
        ):
            raise Unavailable
        if tuple(sorted(set(source.scopes))) != source.scopes:
            raise Unavailable
    if (
        len(set(hosting.scopes) | set(workforce.scopes))
        > MAX_PERSONAL_TIMETABLE_EDITIONS
    ):
        raise Unavailable
    return hosting, workforce


def _admissions(
    actor_id: UUID, candidates: tuple[PersonalHostScopeSet, PersonalShiftScopeSet]
) -> tuple[_Admission, ...]:
    result = []
    for organization_id, edition_id in sorted(
        set(candidates[0].scopes) | set(candidates[1].scopes)
    ):
        try:
            authorize_personal_timetable_scope(
                actor_id=actor_id,
                organization_id=organization_id,
                edition_id=edition_id,
            )
            hosting, workforce = _adopted_layers(organization_id, edition_id)
            profile = edition_adoption_profile_reference(
                organization_id=organization_id, edition_id=edition_id
            )
            if not isinstance(profile, EditionAdoptionProfileReference):
                raise Unavailable
            scheduling = None
            if hosting:
                scope = authorize_scheduling_scope(
                    actor_id=actor_id,
                    organization_id=organization_id,
                    edition_id=edition_id,
                    capability_code="scheduling.view_host_self",
                    requested_fields=frozenset({"own_host_schedule"}),
                )
                if (scope.actor_id, scope.organization_id, scope.edition_id) != (
                    actor_id,
                    organization_id,
                    edition_id,
                ):
                    raise Unavailable
                scheduling = scope.decision
                if (
                    not isinstance(scheduling, PolicyDecision)
                    or scheduling.allowed is not True
                    or not frozenset({"own_host_schedule"}) <= scheduling.fields
                ):
                    raise Unavailable
            result.append(
                _Admission(
                    organization_id, edition_id, profile, hosting, workforce, scheduling
                )
            )
        except Denied:
            continue
    return tuple(result)


def _text(value: object, maximum: int) -> bool:
    return (
        type(value) is str
        and 0 < len(value) <= maximum
        and value.strip() == value
        and value.isprintable()
    )


def _choice(admission: _Admission) -> PersonalEditionChoice:
    edition = resolve_personal_timetable_edition_choice(
        organization_id=admission.organization_id, edition_id=admission.edition_id
    )
    if (
        not isinstance(edition, PersonalTimetableEditionChoice)
        or (edition.organization_id, edition.edition_id)
        != (admission.organization_id, admission.edition_id)
        or not _uuid(edition.series_id)
    ):
        raise Unavailable
    organizer = resolve_personal_timetable_organizer_labels(
        organization_id=admission.organization_id, series_id=edition.series_id
    )
    if not isinstance(organizer, PersonalTimetableOrganizerLabels) or (
        organizer.organization_id,
        organizer.series_id,
    ) != (admission.organization_id, edition.series_id):
        raise Unavailable
    if (
        not all(
            _text(value, 160)
            for value in (
                edition.name,
                organizer.organization_name,
                organizer.series_name,
            )
        )
        or not all(
            _text(value, 80)
            for value in (
                edition.code,
                organizer.organization_code,
                organizer.series_code,
            )
        )
        or type(edition.version) is not int
        or edition.version < 1
    ):
        raise Unavailable
    return PersonalEditionChoice(edition, organizer)


def _purposes(
    actor_id: UUID, admissions: tuple[_Admission, ...]
) -> tuple[_Purpose, ...]:
    result = []
    for admission in admissions:
        arguments = {
            "actor_id": actor_id,
            "organization_id": admission.organization_id,
            "edition_id": admission.edition_id,
        }
        hosting = personal_host_scope_proof(**arguments) if admission.hosting else None
        workforce = (
            personal_shift_scope_proof(**arguments) if admission.workforce else None
        )
        for proof, expected, adopted, fields in (
            (
                hosting,
                PersonalHostScopeProof,
                admission.hosting,
                frozenset({"own_host_relationship", "own_host_invitation"}),
            ),
            (
                workforce,
                PersonalShiftScopeProof,
                admission.workforce,
                frozenset({"shifts"}),
            ),
        ):
            if not adopted:
                continue
            if (
                proof is None
                or not isinstance(proof, expected)
                or any(getattr(proof, key) != value for key, value in arguments.items())
                or type(proof.present) is not bool
                or not isinstance(proof.decision, PolicyDecision)
                or proof.decision.allowed is not True
                or not fields <= proof.decision.fields
            ):
                raise Unavailable
        present = (hosting is not None and hosting.present) or (
            workforce is not None and workforce.present
        )
        result.append(
            _Purpose(
                admission, hosting, workforce, _choice(admission) if present else None
            )
        )
    return tuple(result)


def _audit(
    actor_id: UUID, correlation_id: UUID, purposes: tuple[_Purpose, ...]
) -> None:
    for purpose in purposes:
        if purpose.choice is None:
            continue
        for proof, capability, retention in (
            (purpose.hosting, "programme.view_host_self", "programme-restricted"),
            (purpose.workforce, "workforce.view_self", "workforce-personal"),
        ):
            if proof is None or not proof.present:
                continue
            append_audit(
                AuditRecord(
                    principal_kind="account",
                    principal_id=actor_id,
                    principal_context_id=None,
                    organization_id=proof.organization_id,
                    event_edition_id=proof.edition_id,
                    capability_code=capability,
                    operation="scheduling.personal_editions.read",
                    target_type="events.event_edition",
                    target_id=proof.edition_id,
                    outcome="allow",
                    reason_code=proof.decision.reason_code,
                    correlation_id=correlation_id,
                    request_id=correlation_id,
                    source_channel="personal-timetable-discovery",
                    obligations=tuple(
                        sorted(proof.decision.obligations | {"audit_sensitive_read"})
                    ),
                    safe_metadata={
                        "policy_version": POLICY_VERSION,
                        "access_purpose": "own_retained_timetable_edition",
                    },
                    retention_class=retention,
                )
            )


def load_personal_timetable_editions(
    *, actor_id: UUID, correlation_id: UUID
) -> PersonalEditionCatalog:
    """List only independently authorized editions with actual own retained purposes.

    Parameters
    ----------
    actor_id : UUID
        Actual authenticated verified person; no separate owner selector exists.
    correlation_id : UUID
        Trusted trace for mandatory minimized own-purpose label disclosure audit.

    Returns
    -------
    PersonalEditionCatalog
        Complete bounded choices and server-only revalidation evidence.

    Raises
    ------
    Denied
        If the actual person or trusted identifiers are unavailable or malformed.
    Unavailable
        If bounded source, ownership, permission or audit evidence cannot complete.

    Notes
    -----
    Denied candidate scopes are omitted without labels/counts. All admitted parents
    are locked in stable order before the person; later discovery comparisons never
    lock a new scope. The final view must repeat this complete query after rendering.
    No timetable contents, suitability, other-person records, Participation or
    proposal authorship are consulted. Current production routes remain dormant.
    """
    if not _uuid(actor_id) or not _uuid(correlation_id):
        raise Denied
    try:
        with transaction.atomic():
            _person(actor_id)
            candidates = _candidates(actor_id)
            admissions = _admissions(actor_id, candidates)
            for scope in admissions:
                if not lock_edition_ownership(
                    organization_id=scope.organization_id, edition_id=scope.edition_id
                ):
                    raise Unavailable
            _person(actor_id, lock=True)
            if (
                _candidates(actor_id) != candidates
                or _admissions(actor_id, candidates) != admissions
            ):
                raise Unavailable
            purposes = _purposes(actor_id, admissions)
            if (
                _candidates(actor_id) != candidates
                or _admissions(actor_id, candidates) != admissions
                or _purposes(actor_id, admissions) != purposes
            ):
                raise Unavailable
            _audit(actor_id, correlation_id, purposes)
            _person(actor_id)
            if (
                _candidates(actor_id) != candidates
                or _admissions(actor_id, candidates) != admissions
                or _purposes(actor_id, admissions) != purposes
            ):
                raise Unavailable
            evidence = {
                "candidates": [asdict(item) for item in candidates],
                "purposes": [asdict(item) for item in purposes],
            }
            fingerprint = hashlib.sha256(
                json.dumps(evidence, sort_keys=True, default=str).encode()
            ).hexdigest()
            choices = tuple(item.choice for item in purposes if item.choice is not None)
            return PersonalEditionCatalog(actor_id, choices, fingerprint)
    except (ProgrammeAuthorizationDeniedError, ShiftAuthorizationDeniedError) as error:
        raise Denied from error
    except (
        DatabaseError,
        ProgrammeQueryUnavailableError,
        ShiftUnavailableError,
    ) as error:
        raise Unavailable from error
