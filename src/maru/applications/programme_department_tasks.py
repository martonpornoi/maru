"""Complete purpose-scoped Department entry without a Workforce directory grant."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import PolicyDecision
from maru.events.queries import (
    EditionAdoptionProfileReference,
    PrivatePlanningEditionReference,
    edition_adoption_profile_reference,
    resolve_private_planning_edition_reference,
)
from maru.identity.queries import (
    ActiveVerifiedPersonReference,
    resolve_active_verified_person_reference,
)
from maru.workforce.queries import (
    MAX_STRUCTURE_DEPARTMENTS,
    CurrentDepartmentChoiceReference,
    CurrentDepartmentSetReference,
    resolve_current_department_set_reference,
)

from .adoption import profile_allows_application_target
from .programme_adoption import APPLICATION_PROGRAMME_ITEM_TARGET_KIND
from .programme_authorization import (
    APPLICATIONS_MANAGE_PROGRAMME_CALLS,
    DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER,
    _require_test_authorizer,
)
from .programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from .programme_call_departments import _choice
from .programme_inputs import require_programme_uuid
from .programme_queries import _audit_inputs
from .programme_review_authorization import DECIDE, MANAGE_REVIEW, MODERATE, REVIEW

if TYPE_CHECKING:
    from collections.abc import Iterator

    from .programme_authorization import ApplicationsProgrammeAuthorizer

_DEFAULT_AUTHORIZER = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER
_REASONS = frozenset({"direct_grant", "role_assignment", "platform_administration"})
_POLICY_LABELS = {
    "direct_grant": "Direct permission",
    "role_assignment": "Assigned role",
    "platform_administration": "Platform administration",
}


@dataclass(frozen=True, slots=True)
class _Task:
    code: str
    label: str
    capability: str
    fields: frozenset[str]
    suffix: str

    @property
    def obligations(self) -> frozenset[str]:
        return frozenset({"reason", "audit"}) | (
            frozenset({"audit_sensitive_read"}) if self.fields else frozenset()
        )


_TASKS = (
    _Task(
        "calls", "Manage calls", APPLICATIONS_MANAGE_PROGRAMME_CALLS, frozenset(), ""
    ),
    _Task("setup", "Set up review", MANAGE_REVIEW, frozenset({"review_setup"}), ""),
    _Task(
        "reviewers",
        "Manage reviewers",
        MANAGE_REVIEW,
        frozenset({"review_context"}),
        "cases/",
    ),
    _Task(
        "mine", "My assigned reviews", REVIEW, frozenset({"review_context"}), "mine/"
    ),
    _Task(
        "moderation",
        "Moderate reviews",
        MODERATE,
        frozenset({"review_context"}),
        "moderation/",
    ),
    _Task(
        "decisions",
        "Make decisions",
        DECIDE,
        frozenset({"review_context"}),
        "decisions/",
    ),
)

type _Snapshot = tuple[
    PrivatePlanningEditionReference,
    tuple[UUID, ...],
    tuple[tuple[PolicyDecision, ...], ...],
    tuple[CurrentDepartmentChoiceReference, ...],
    EditionAdoptionProfileReference,
]


@dataclass(frozen=True, slots=True)
class ProgrammeDepartmentTask:
    """Describe one independently admitted task, never an authority token.

    Attributes
    ----------
    department_id
        Exact current Department whose label was independently admitted.
    department_code
        Stable readable disambiguator for duplicate Department labels.
    department_label
        Current authorized owner-supplied label.
    task_code
        Closed Applications-owned entry purpose.
    task_label
        Human task name, not a model or capability identifier.
    url
        Exact owning route whose destination authorizes again.
    policy_label
        Current capability source without a named-principal directory.
    """

    department_id: UUID
    department_code: str
    department_label: str
    task_code: str
    task_label: str
    url: str
    policy_label: str


@dataclass(frozen=True, slots=True)
class ProgrammeDepartmentTaskCatalog:
    """Retain complete visible choices and server-only source comparison evidence.

    Attributes
    ----------
    tasks
        Complete authorized choices, grouped by readable Department order.
    accepts_private_planning_writes
        Current edition lifecycle hint; destination commands decide eligibility.
    source_fingerprint
        Server-only complete source comparison, not a credential or client field.
    """

    tasks: tuple[ProgrammeDepartmentTask, ...]
    accepts_private_planning_writes: bool
    source_fingerprint: str = field(repr=False)


def _require(*, condition: bool) -> None:
    if not condition:
        raise Denied


def _decision(value: object, task: _Task) -> PolicyDecision:
    if not isinstance(value, PolicyDecision):
        raise Denied
    _require(
        condition=type(value.allowed) is bool
        and value.policy_version == POLICY_VERSION
        and type(value.fields) is frozenset
        and value.fields <= task.fields
        and type(value.obligations) is frozenset
        and type(value.reason_code) is str
        and (
            (
                value.allowed
                and value.reason_code in _REASONS
                and value.obligations == task.obligations
            )
            or (
                not value.allowed
                and value.reason_code == "permission_absent"
                and not value.fields
                and not value.obligations
            )
        )
    )
    return value


def _admitted(decision: PolicyDecision, task: _Task) -> bool:
    return decision.allowed and decision.fields == task.fields


def _audit(
    values: dict[str, UUID | str],
    task: _Task,
    department_id: UUID | None,
    decision: PolicyDecision | None,
) -> None:
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=UUID(str(values["actor_id"])),
            principal_context_id=None,
            organization_id=UUID(str(values["organization_id"])),
            event_edition_id=UUID(str(values["edition_id"])),
            capability_code=task.capability,
            operation="applications.programme.query.department_tasks." + task.code,
            target_type="workforce.department",
            target_id=department_id,
            outcome="allow" if decision is not None else "deny",
            reason_code=(
                decision.reason_code if decision is not None else "task_unavailable"
            ),
            correlation_id=UUID(str(values["correlation_id"])),
            request_id=UUID(str(values["correlation_id"])),
            source_channel=str(values["source_channel"]),
            obligations=tuple(sorted(task.obligations | {"audit_sensitive_read"})),
            retention_class="applications-programme-restricted",
        ),
        occurred_at=timezone.now(),
    )


@contextmanager
def _denial_audit(values: dict[str, UUID | str]) -> Iterator[None]:
    try:
        yield
    except Denied:
        # Outside the failed read transaction: no target, label or hidden count.
        for task in _TASKS:
            _audit(values, task, None, None)
        raise


def list_programme_department_tasks(  # noqa: DOC502 -- Delegated source proofs deny.
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    source_channel: str,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> ProgrammeDepartmentTaskCatalog:
    """Discover independently admitted task links from an exact edition context.

    Parameters
    ----------
    actor_id : UUID
        Authenticated active verified person, not caller-selected impersonation.
    organization_id : UUID
        Exact expected owner of the edition and every Department.
    edition_id : UUID
        Exact private-planning edition whose current tasks are requested.
    correlation_id : UUID
        Mandatory protected-read evidence identifier.
    source_channel : str
        Bounded registered request-channel spelling.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real policy adapter or the existing two-factor isolated-test seam.

    Returns
    -------
    ProgrammeDepartmentTaskCatalog
        Complete admitted links and private final-render comparison evidence.

    Raises
    ------
    Denied
        If owner, policy, bounds or repeated source evidence is incoherent.
    """
    actor_id = require_programme_uuid(actor_id, field="actor_id")
    organization_id = require_programme_uuid(organization_id, field="organization_id")
    edition_id = require_programme_uuid(edition_id, field="edition_id")
    correlation_id, source_channel = _audit_inputs(
        correlation_id=correlation_id, source_channel=source_channel
    )
    _require_test_authorizer(authorizer)

    def snapshot() -> _Snapshot:
        actor = resolve_active_verified_person_reference(account_id=actor_id)
        edition = resolve_private_planning_edition_reference(
            organization_id=organization_id, edition_id=edition_id
        )
        _require(
            condition=isinstance(actor, ActiveVerifiedPersonReference)
            and actor.account_id == actor_id
        )
        _require(
            condition=isinstance(edition, PrivatePlanningEditionReference)
            and edition.organization_id == organization_id
            and edition.edition_id == edition_id
            and type(edition.accepts_private_planning_writes) is bool
        )
        if not isinstance(edition, PrivatePlanningEditionReference):
            raise Denied
        profile = edition_adoption_profile_reference(
            organization_id=organization_id, edition_id=edition_id
        )
        _require(
            condition=isinstance(profile, EditionAdoptionProfileReference)
            and profile_allows_application_target(
                profile.code, profile.version, APPLICATION_PROGRAMME_ITEM_TARGET_KIND
            )
        )
        if not isinstance(profile, EditionAdoptionProfileReference):
            raise Denied
        members = resolve_current_department_set_reference(
            organization_id=organization_id, edition_id=edition_id
        )
        _require(
            condition=isinstance(members, CurrentDepartmentSetReference)
            and members.organization_id == organization_id
            and members.edition_id == edition_id
            and type(members.department_ids) is tuple
            and len(members.department_ids) <= MAX_STRUCTURE_DEPARTMENTS
            and all(
                isinstance(item, UUID) and item.int for item in members.department_ids
            )
            and len(set(members.department_ids)) == len(members.department_ids)
        )
        if not isinstance(members, CurrentDepartmentSetReference):
            raise Denied
        ids = tuple(sorted(members.department_ids))
        decisions = tuple(
            tuple(
                _decision(
                    authorizer.authorize_department(
                        principal_id=actor_id,
                        organization_id=organization_id,
                        edition_id=edition_id,
                        department_id=identifier,
                        capability_code=task.capability,
                        requested_fields=task.fields or None,
                    ),
                    task,
                )
                for task in _TASKS
            )
            for identifier in ids
        )
        labels = tuple(
            _choice(organization_id, edition_id, identifier)
            for identifier, row in zip(ids, decisions, strict=True)
            if any(
                _admitted(value, task) for value, task in zip(row, _TASKS, strict=True)
            )
        )
        _require(condition=len({item.code for item in labels}) == len(labels))
        return edition, ids, decisions, labels, profile

    values: dict[str, UUID | str] = {
        "actor_id": actor_id,
        "organization_id": organization_id,
        "edition_id": edition_id,
        "correlation_id": correlation_id,
        "source_channel": source_channel,
    }
    with _denial_audit(values), transaction.atomic():
        initial = snapshot()
        edition, ids, decisions, labels, profile = initial
        by_id = {label.department_id: label for label in labels}
        choices: list[ProgrammeDepartmentTask] = []
        for task_index, task in enumerate(_TASKS):
            available = False
            for identifier, row in zip(ids, decisions, strict=True):
                decision = row[task_index]
                if not _admitted(decision, task):
                    continue
                available = True
                label = by_id[identifier]
                root = "programme-calls" if task.code == "calls" else "programme-review"
                url = (
                    f"/admin/applications/{root}/{organization_id}/"
                    f"{edition_id}/{identifier}/"
                )
                choices.append(
                    ProgrammeDepartmentTask(
                        identifier,
                        label.code,
                        label.label,
                        task.code,
                        task.label,
                        url + task.suffix,
                        _POLICY_LABELS[decision.reason_code],
                    )
                )
                _audit(values, task, identifier, decision)
            if not available:
                _audit(values, task, None, None)
        _require(condition=snapshot() == initial)
        # Structured JSON avoids process-dependent frozenset repr ordering.
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "actor": str(actor_id),
                    "organization": str(organization_id),
                    "edition": str(edition_id),
                    "planning": edition.accepts_private_planning_writes,
                    "profile": (profile.code, profile.version),
                    "departments": [str(identifier) for identifier in ids],
                    "decisions": [
                        [
                            (
                                value.allowed,
                                sorted(value.fields),
                                sorted(value.obligations),
                                value.reason_code,
                                value.policy_version,
                            )
                            for value in row
                        ]
                        for row in decisions
                    ],
                    "labels": [
                        (str(value.department_id), value.code, value.label)
                        for value in labels
                    ],
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return ProgrammeDepartmentTaskCatalog(
            tuple(
                sorted(
                    choices,
                    key=lambda item: (
                        item.department_label.casefold(),
                        item.department_code,
                        next(
                            index
                            for index, task in enumerate(_TASKS)
                            if task.code == item.task_code
                        ),
                    ),
                )
            ),
            edition.accepts_private_planning_writes,
            fingerprint,
        )
