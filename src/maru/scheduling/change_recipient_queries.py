"""Sender-authorized operator eligibility without an impersonated output read."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from maru.identity.queries import (
    active_verified_person_account_display_labels,
    resolve_active_verified_person_reference,
)
from maru.workforce.operator_links import operator_staffing_adopted

from .authorization import (
    DEFAULT_SCHEDULING_AUTHORIZER,
    VIEW_CHANGE_RECIPIENTS,
    SchedulingAuthorizationDeniedError,
)
from .command_support import SchedulingUnavailableError
from .operator_scope import (
    OperatorReadRequest,
    OperatorScopeKind,
    authorize_operator_scope,
)
from .planning_queries import SchedulingReadRequest, _read

if TYPE_CHECKING:
    from maru.authorization.policy import PolicyDecision


@dataclass(frozen=True, slots=True)
class OperatorChangeRecipientRequest:
    """Deliberately select one recipient and scope under authenticated sender authority.

    Attributes
    ----------
    sender
        Trusted actual actor, tenant, edition and correlation; never the recipient.
    account_id
        Selected potential operator, not an address or an impersonation credential.
    kind
        Exact room, Department or edition purpose being considered for a change.
    target_id
        Persisted exact purpose identity, independently resolved by normal policy.
    """

    sender: SchedulingReadRequest
    account_id: UUID
    kind: OperatorScopeKind
    target_id: UUID


@dataclass(frozen=True, slots=True)
class OperatorChangeRecipient:
    """Current minimized eligibility reference, not a portable permission or notice.

    Attributes
    ----------
    account_id
        Exact current verified person selected under sender recipient authority.
    display_label
        Current operational label, not contact information or a historical snapshot.
    kind
        Independently admitted exact operator purpose.
    target_id
        Exact persisted purpose target, not an inherited directory or audience.
    staffing_adopted
        Whether optional staffing membership was independently required and admitted.
    policy_version
        Current policy contract; it is not a retained grant version or sending proof.
    """

    account_id: UUID
    display_label: str
    kind: OperatorScopeKind
    target_id: UUID
    staffing_adopted: bool
    policy_version: str


def _eligibility(
    request: OperatorReadRequest,
) -> tuple[bool, tuple[PolicyDecision, ...]]:
    try:
        decisions = [
            authorize_operator_scope(
                request,
                capability="scheduling.view_operator_output",
                fields=frozenset({"released_geometry"}),
            ),
            authorize_operator_scope(
                request,
                capability="venues.view_operator_wayfinding",
                fields=frozenset({"scope_links"}),
            ),
        ]
        staffing = (
            request.kind is OperatorScopeKind.DEPARTMENT
            and operator_staffing_adopted(request)
        )
        if staffing:
            decisions.append(
                authorize_operator_scope(
                    request,
                    capability="workforce.view_operator_staffing",
                    fields=frozenset({"scope_links"}),
                )
            )
        return staffing, tuple(decisions)
    except SchedulingAuthorizationDeniedError as error:
        # Missing, foreign, inactive and ineligible selections share one result.
        raise SchedulingUnavailableError from error


def _load(request: OperatorChangeRecipientRequest) -> OperatorChangeRecipient:
    sender = request.sender
    for account_id in sorted({sender.actor_id, request.account_id}, key=str):
        if (
            resolve_active_verified_person_reference(account_id=account_id, lock=True)
            is None
        ):
            if account_id == sender.actor_id:
                raise SchedulingAuthorizationDeniedError
            raise SchedulingUnavailableError
    subject = OperatorReadRequest(
        request.account_id,
        sender.organization_id,
        sender.edition_id,
        sender.correlation_id,
        request.kind,
        request.target_id,
    )
    eligibility = _eligibility(subject)
    labels = active_verified_person_account_display_labels({request.account_id})
    if set(labels) != {request.account_id} or _eligibility(subject) != eligibility:
        raise SchedulingUnavailableError
    return OperatorChangeRecipient(
        request.account_id,
        labels[request.account_id],
        request.kind,
        request.target_id,
        eligibility[0],
        eligibility[1][0].policy_version,
    )


def load_operator_change_recipient(  # noqa: DOC503 - delegated owner/source checks
    request: OperatorChangeRecipientRequest,
) -> OperatorChangeRecipient:
    """Resolve one eligible operator under a distinct real-sender read capability.

    Parameters
    ----------
    request : OperatorChangeRecipientRequest
        Trusted sender attribution with a deliberately selected exact person/purpose.

    Returns
    -------
    OperatorChangeRecipient
        Current minimized eligibility; no permission to serve or send any content.

    Raises
    ------
    SchedulingAuthorizationDeniedError
        If trusted routing or actual sender recipient-field authority is invalid.
    SchedulingUnavailableError
        If selected identity, purpose, owner authority or required audit is unavailable.

    Notes
    -----
    Canonical scope and actual sender authorization precede identity discovery.
    Complete sorted sender/recipient locks precede any actor-only final check.
    Ordinary policy checks the selected subject's geometry and owner membership
    eligibility, but no operator/personal output is read as that subject and no
    audit is attributed to them. The actual sender's mandatory audit precedes
    disclosure. No release, contact, instructions, recipient directory, grant,
    message or acknowledgement is read or written. A composing notice must
    independently prove affected occurrence membership, content authority and
    current exact release/purpose state; this reference cannot substitute for it.
    """
    if (
        not isinstance(request, OperatorChangeRecipientRequest)
        or not isinstance(request.sender, SchedulingReadRequest)
        or not isinstance(request.kind, OperatorScopeKind)
        or any(
            type(value) is not UUID or value.int == 0
            for value in (
                request.sender.actor_id,
                request.sender.organization_id,
                request.sender.edition_id,
                request.sender.correlation_id,
                request.account_id,
                request.target_id,
            )
        )
    ):
        raise SchedulingAuthorizationDeniedError
    return _read(
        request.sender,
        capability=VIEW_CHANGE_RECIPIENTS,
        fields=frozenset({"operator_recipients"}),
        purpose="operator_change_recipient",
        authorizer=DEFAULT_SCHEDULING_AUTHORIZER,
        loader=lambda _scope: _load(request),
    )
