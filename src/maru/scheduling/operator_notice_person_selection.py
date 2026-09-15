"""Purpose-bound exact-known-person selection, never a recipient directory."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.core import signing

from maru.identity.queries import (
    lock_account_references_for_evidence,
    resolve_active_verified_person_reference_by_email,
)

from .authorization import (
    DEFAULT_SCHEDULING_AUTHORIZER,
    VIEW_CHANGE_RECIPIENTS,
    SchedulingAuthorizationDeniedError,
)
from .change_recipient_queries import (
    OperatorChangeRecipient,
    OperatorChangeRecipientIneligibleError,
    OperatorChangeRecipientRequest,
    load_operator_change_recipient,
)
from .command_support import SchedulingUnavailableError, SchedulingVersionConflictError
from .operator_notice_choices import (
    NoticeOperatorChoices,
    admit_notice_operator_selection,
    load_notice_operator_choices,
)
from .operator_scope import OperatorScopeKind
from .planning_queries import SchedulingReadRequest, _read

_SALT = "maru.scheduling.operator-notice-person.v1"
_MAX_TOKEN = 2048
_KEYS = frozenset(
    {
        "actor",
        "organization",
        "edition",
        "release",
        "occurrence",
        "pointer",
        "kind",
        "target",
        "person",
        "retry",
    }
)


@dataclass(frozen=True, slots=True)
class OperatorNoticeIntent:
    """Original deliberate source and purpose, not current authorization.

    Attributes
    ----------
    release_id
        Original current or withdrawn publication under consideration.
    occurrence_id
        Exact original current occurrence.
    pointer_version
        Original publication pointer; never refreshed during a retained retry.
    kind
        Closed operator purpose.
    target_id
        Original owner target within the chosen purpose.
    lookup_retry_key
        Fresh lookup intent identity, separate from the later native command key.
    """

    release_id: UUID
    occurrence_id: UUID
    pointer_version: int
    kind: OperatorScopeKind
    target_id: UUID
    lookup_retry_key: UUID


@dataclass(frozen=True, slots=True)
class OperatorNoticePersonSelection:
    """Current eligible person with an identifier-only original-intent signature.

    Attributes
    ----------
    intent
        Original source, purpose and lookup intent, not a rebased command.
    recipient
        Independently proven current person and exact operator eligibility.
    token
        Bounded purpose-specific signature containing no email or labels.
    choices
        Complete source and target observation to compare after rendering.
    """

    intent: OperatorNoticeIntent
    recipient: OperatorChangeRecipient
    token: str
    choices: NoticeOperatorChoices


def _validate(intent: OperatorNoticeIntent) -> None:
    if (
        not isinstance(intent, OperatorNoticeIntent)
        or not isinstance(intent.kind, OperatorScopeKind)
        or type(intent.pointer_version) is not int
        or not 1 <= intent.pointer_version < 2**63 - 1
        or any(
            type(value) is not UUID or not value.int
            for value in (
                intent.release_id,
                intent.occurrence_id,
                intent.target_id,
                intent.lookup_retry_key,
            )
        )
    ):
        raise SchedulingAuthorizationDeniedError


def _choices(
    request: SchedulingReadRequest, intent: OperatorNoticeIntent
) -> NoticeOperatorChoices:
    _validate(intent)
    choices = load_notice_operator_choices(
        request,
        occurrence_id=intent.occurrence_id,
        kind=intent.kind,
        target_id=intent.target_id,
    )
    if (
        choices.source.release_id != intent.release_id
        or choices.source.pointer_version != intent.pointer_version
    ):
        raise SchedulingVersionConflictError
    return choices


def _payload(
    request: SchedulingReadRequest, intent: OperatorNoticeIntent, person: UUID
) -> dict[str, str | int]:
    return {
        "actor": str(request.actor_id),
        "organization": str(request.organization_id),
        "edition": str(request.edition_id),
        "release": str(intent.release_id),
        "occurrence": str(intent.occurrence_id),
        "pointer": intent.pointer_version,
        "kind": intent.kind.value,
        "target": str(intent.target_id),
        "person": str(person),
        "retry": str(intent.lookup_retry_key),
    }


def _decode(
    request: SchedulingReadRequest, token: str
) -> tuple[OperatorNoticeIntent, UUID]:
    if (
        type(token) is not str
        or not token.isascii()
        or not 0 < len(token) <= _MAX_TOKEN
        or token.startswith(".")
    ):
        raise SchedulingAuthorizationDeniedError
    try:
        payload = signing.loads(token, salt=_SALT)
        if type(payload) is not dict or payload.keys() != _KEYS:
            raise SchedulingAuthorizationDeniedError
        identifiers = {key: UUID(payload[key]) for key in _KEYS - {"pointer", "kind"}}
        if any(
            str(value) != payload[key] or not value.int
            for key, value in identifiers.items()
        ):
            raise SchedulingAuthorizationDeniedError
        intent = OperatorNoticeIntent(
            identifiers["release"],
            identifiers["occurrence"],
            payload["pointer"],
            OperatorScopeKind(payload["kind"]),
            identifiers["target"],
            identifiers["retry"],
        )
        _validate(intent)
        if _payload(request, intent, identifiers["person"]) != payload:
            raise SchedulingAuthorizationDeniedError
        return intent, identifiers["person"]
    except (signing.BadSignature, ValueError, TypeError, AttributeError) as error:
        raise SchedulingAuthorizationDeniedError from error


def _recipient(
    request: SchedulingReadRequest, intent: OperatorNoticeIntent, person: UUID
) -> OperatorChangeRecipient:
    return load_operator_change_recipient(
        OperatorChangeRecipientRequest(
            request,
            person,
            intent.kind,
            intent.target_id,
        )
    )


def prepare_operator_notice_person_selection(  # noqa: DOC503 - nested owner loader
    request: SchedulingReadRequest,
    *,
    intent: OperatorNoticeIntent,
    email: str,
) -> OperatorNoticePersonSelection | None:
    """Resolve one exact known email after independently admitting source and purpose.

    Parameters
    ----------
    request : SchedulingReadRequest
        Actual notice-admitted sender and trusted exact owner scope.
    intent : OperatorNoticeIntent
        Original deliberate current source, purpose and fresh lookup intent.
    email : str
        Exact known login email, never a directory search or retained command field.

    Returns
    -------
    OperatorNoticePersonSelection | None
        Current eligible selection, or the same audited empty result for unknown,
        inactive, unverified and independently ineligible people.

    Raises
    ------
    SchedulingUnavailableError
        If identity moves, complete locking fails or a dependency is unavailable.
    SchedulingVersionConflictError
        If the original source or target choices move before disclosure.

    Notes
    -----
    All single-person owner transactions finish before complete canonical person
    locks. Lookup is repeated under those locks; failures are never empty success.
    The actual sender's mandatory positive/empty audit is the only attribution.
    Native preview and commands remain independently authoritative and unchanged.
    """
    choices = _choices(request, intent)

    def load(_scope: object) -> OperatorChangeRecipient | None:
        found = resolve_active_verified_person_reference_by_email(email=email)
        people = tuple(
            sorted({request.actor_id} | ({found.account_id} if found else set()))
        )
        if lock_account_references_for_evidence(account_ids=people) != people:
            raise SchedulingUnavailableError
        if resolve_active_verified_person_reference_by_email(email=email) != found:
            raise SchedulingUnavailableError
        if found is None:
            return None
        try:
            return _recipient(request, intent, found.account_id)
        except OperatorChangeRecipientIneligibleError:
            return None

    recipient = _read(
        request,
        capability=VIEW_CHANGE_RECIPIENTS,
        fields=frozenset({"operator_recipients"}),
        purpose="operator_notice_known_person",
        authorizer=DEFAULT_SCHEDULING_AUTHORIZER,
        loader=load,
    )
    if _choices(request, intent) != choices:
        raise SchedulingVersionConflictError
    if recipient is None:
        return None
    token = signing.dumps(
        _payload(request, intent, recipient.account_id), salt=_SALT, compress=False
    )
    return OperatorNoticePersonSelection(intent, recipient, token, choices)


def load_operator_notice_person_selection(
    request: SchedulingReadRequest,
    *,
    token: str,
) -> OperatorNoticePersonSelection:
    """Recheck the signed original person without resolving a mutable email again.

    Parameters
    ----------
    request : SchedulingReadRequest
        Current actual sender; independent admission precedes signature decoding.
    token : str
        Original bounded purpose-specific identifier-only selection signature.

    Returns
    -------
    OperatorNoticePersonSelection
        Original intent and independently refreshed current recipient and labels.

    Raises
    ------
    SchedulingVersionConflictError
        If the original publication pointer, source or owner target choices move.

    Notes
    -----
    Invalid signatures and wrong actor/tenant context are denied. Original-person
    ineligibility, owner denial, audit and dependency failures remain unavailable;
    a reassigned email never selects a replacement. Compare again after rendering.
    """
    admit_notice_operator_selection(request)
    intent, person = _decode(request, token)
    choices = _choices(request, intent)
    recipient = _recipient(request, intent, person)
    if _choices(request, intent) != choices:
        raise SchedulingVersionConflictError
    return OperatorNoticePersonSelection(intent, recipient, token, choices)
