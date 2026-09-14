"""Complete exact-authority Department choices for dormant call management."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import PolicyDecision
from maru.workforce.queries import (
    MAX_STRUCTURE_DEPARTMENTS,
    CurrentDepartmentChoiceReference,
    CurrentDepartmentSetReference,
    resolve_current_department_choice_reference,
    resolve_current_department_set_reference,
)

from .programme_authorization import (
    APPLICATIONS_MANAGE_PROGRAMME_CALLS,
    DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER,
    ApplicationsProgrammeAuthorizationDeniedError,
    authorize_programme_call_scope,
)
from .programme_inputs import require_programme_uuid
from .programme_queries import (
    _append_managed_call_read_denial,
    _append_managed_call_sensitive_read,
    _audit_inputs,
)

if TYPE_CHECKING:
    from .programme_authorization import (
        ApplicationsProgrammeAuthorizer,
        AuthorizedProgrammeCallScope,
    )

_OPERATION = "applications.programme.query.managed_department_choices"
_DEFAULT_AUTHORIZER = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER
_MAX_CODE_LENGTH = 80
_MAX_LABEL_LENGTH = 160
_OBLIGATIONS = frozenset({"reason", "audit"})
_ALLOWED_REASONS = frozenset(
    {"direct_grant", "role_assignment", "platform_administration"}
)


def _require_coherence(*, condition: bool) -> None:
    if not condition:
        raise ApplicationsProgrammeAuthorizationDeniedError


def _require_decision(value: PolicyDecision) -> PolicyDecision:
    if (
        not isinstance(value, PolicyDecision)
        or type(value.allowed) is not bool
        or value.policy_version != POLICY_VERSION
        or value.fields != frozenset()
        or type(value.fields) is not frozenset
        or type(value.obligations) is not frozenset
        or type(value.reason_code) is not str
        or (
            value.allowed
            and (
                value.obligations != _OBLIGATIONS
                or value.reason_code not in _ALLOWED_REASONS
            )
        )
        or (
            not value.allowed
            and (value.reason_code != "permission_absent" or value.obligations)
        )
    ):
        raise ApplicationsProgrammeAuthorizationDeniedError
    return value


def _department_ids(
    organization_id: UUID, edition_id: UUID, anchor: UUID
) -> tuple[UUID, ...]:
    value = resolve_current_department_set_reference(
        organization_id=organization_id, edition_id=edition_id
    )
    if (
        not isinstance(value, CurrentDepartmentSetReference)
        or value.organization_id != organization_id
        or value.edition_id != edition_id
        or type(value.department_ids) is not tuple
        or not 1 <= len(value.department_ids) <= MAX_STRUCTURE_DEPARTMENTS
        or any(not isinstance(item, UUID) for item in value.department_ids)
        or len(set(value.department_ids)) != len(value.department_ids)
        or anchor not in value.department_ids
    ):
        raise ApplicationsProgrammeAuthorizationDeniedError
    return tuple(sorted(value.department_ids))


def _choice(
    organization_id: UUID, edition_id: UUID, department_id: UUID
) -> CurrentDepartmentChoiceReference:
    value = resolve_current_department_choice_reference(
        organization_id=organization_id,
        edition_id=edition_id,
        department_id=department_id,
    )
    if (
        not isinstance(value, CurrentDepartmentChoiceReference)
        or value.department_id != department_id
        or not isinstance(value.code, str)
        or not 1 <= len(value.code) <= _MAX_CODE_LENGTH
        or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value.code) is None
        or not isinstance(value.label, str)
        or not 1 <= len(value.label) <= _MAX_LABEL_LENGTH
        or not value.label.strip()
        or re.search(r"[\x00-\x1f\x7f]", value.label) is not None
    ):
        raise ApplicationsProgrammeAuthorizationDeniedError
    return value


def list_managed_programme_call_departments(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    correlation_id: UUID,
    source_channel: str,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> tuple[CurrentDepartmentChoiceReference, ...]:
    """Release complete independently authorized choices from an admitted anchor.

    Ordinary absent permission is the sole filtering denial. Invalid policy,
    changed membership or decisions, incomplete references and required audit
    failures discard the whole result. No hidden names or counts are disclosed.

    Parameters
    ----------
    actor_id : UUID
        Current verified person-account identifier.
    organization_id : UUID
        Exact organization owner.
    edition_id : UUID
        Exact event edition owner.
    department_id : UUID
        Already selected anchor, independently reauthorized here.
    correlation_id : UUID
        Mandatory protected-read evidence identity.
    source_channel : str
        Registered request channel.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed policy adapter; test replacements retain the existing double guard.

    Returns
    -------
    tuple[CurrentDepartmentChoiceReference, ...]
        Complete current choices, ordered by display name then stable code.

    Raises
    ------
    ApplicationsProgrammeAuthorizationDeniedError
        If authority, policy, owner coherence or mandatory evidence is incomplete.
    """
    actor_id = require_programme_uuid(actor_id, field="actor_id")
    organization_id = require_programme_uuid(organization_id, field="organization_id")
    edition_id = require_programme_uuid(edition_id, field="edition_id")
    department_id = require_programme_uuid(department_id, field="department_id")
    correlation_id, source_channel = _audit_inputs(
        correlation_id=correlation_id, source_channel=source_channel
    )
    occurred_at = timezone.now()

    def authorize(identifier: UUID) -> AuthorizedProgrammeCallScope:
        return authorize_programme_call_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=identifier,
            authorizer=authorizer,
        )

    def decisions(ids: tuple[UUID, ...]) -> tuple[PolicyDecision, ...]:
        return tuple(
            _require_decision(
                authorizer.authorize_department(
                    principal_id=actor_id,
                    organization_id=organization_id,
                    edition_id=edition_id,
                    department_id=identifier,
                    capability_code=APPLICATIONS_MANAGE_PROGRAMME_CALLS,
                    requested_fields=None,
                )
            )
            for identifier in ids
        )

    try:
        # This also seals the adapter before the first candidate-policy call.
        anchor = authorize(department_id)
        _require_coherence(condition=_require_decision(anchor.decision).allowed)
        with transaction.atomic():
            ids = _department_ids(organization_id, edition_id, department_id)
            initial = decisions(ids)
            _require_coherence(condition=initial[ids.index(department_id)].allowed)
            choices = tuple(
                _choice(organization_id, edition_id, identifier)
                for identifier, decision in zip(ids, initial, strict=True)
                if decision.allowed
            )
            _require_coherence(
                condition=len({item.code for item in choices}) == len(choices)
            )
            _require_coherence(
                condition=(
                    ids == _department_ids(organization_id, edition_id, department_id)
                    and initial == decisions(ids)
                )
            )
            for choice in choices:
                scope = authorize(choice.department_id)
                _require_coherence(
                    condition=(
                        _require_decision(scope.decision)
                        == initial[ids.index(choice.department_id)]
                    )
                )
                _append_managed_call_sensitive_read(
                    scope=scope,
                    operation=_OPERATION,
                    target_type="workforce.department",
                    target_id=choice.department_id,
                    target_count=1,
                    correlation_id=correlation_id,
                    source_channel=source_channel,
                    occurred_at=occurred_at,
                )
            final_anchor = authorize(department_id)
            _require_coherence(
                condition=_require_decision(final_anchor.decision) == anchor.decision
            )
            return tuple(
                sorted(choices, key=lambda item: (item.label.casefold(), item.code))
            )
    except ApplicationsProgrammeAuthorizationDeniedError:
        _append_managed_call_read_denial(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            operation=_OPERATION,
            correlation_id=correlation_id,
            source_channel=source_channel,
            occurred_at=occurred_at,
        )
        raise
