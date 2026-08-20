"""Bounded, version-fenced projections for platform account invitations."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Never, cast
from uuid import UUID

from django.core import signing
from django.db import DatabaseError
from django.db.models import Q
from django.utils.dateparse import parse_datetime

from maru.identity.invitation_inputs import (
    validate_correlation_id,
    validate_source_channel,
)
from maru.identity.models import (
    Account,
    PlatformAccountInventoryControl,
    PlatformAccountInvitation,
    PlatformAccountInvitationTransition,
    PlatformIdentityDelivery,
    PlatformIdentityDeliveryAttempt,
)

if TYPE_CHECKING:
    from datetime import datetime

MAX_ACCOUNT_INVENTORY_PAGE_SIZE = 100
MAX_ACCOUNT_INVENTORY_SEARCH_LENGTH = 120
MIN_ACCOUNT_INVENTORY_SEARCH_LENGTH = 2
MAX_INVITATION_DETAIL_TIMELINE_ROWS = 100
MAX_ACCOUNT_INVENTORY_READ_ATTEMPTS = 2
MAX_ACCOUNT_INVENTORY_CURSOR_LENGTH = 768
ACCOUNT_INVENTORY_CURSOR_MAX_AGE_SECONDS = 86_400

ACCOUNT_INVENTORY_KINDS = frozenset(Account.Kind.values)
ACCOUNT_INVENTORY_STATES = frozenset({"active", "inactive"})
ACCOUNT_INVENTORY_SEARCH_MODES = frozenset({"exact", "prefix"})

AccountInventorySearchMode = Literal["exact", "prefix"]
AccountInventoryState = Literal["active", "inactive"]

_CURSOR_SALT = "maru.identity.platform-account-inventory.cursor.v1"
_SAFE_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_SEARCH_CATEGORIES = frozenset({"Cc", "Cf", "Cs"})


class PlatformAccountInventoryError(RuntimeError):
    """Base typed error for the account-inventory query boundary."""

    code: ClassVar[str] = "account_inventory_error"


class PlatformAccountInventoryDeniedError(PlatformAccountInventoryError):
    """Signal platform account inventory denied."""

    code = "account_inventory_denied"


class PlatformAccountInventoryInputError(PlatformAccountInventoryError):
    """Signal platform account inventory input."""

    code = "account_inventory_input_invalid"

    def __init__(self, *, field_name: str, detail_code: str) -> None:
        """Initialize the PlatformAccountInventoryInputError instance.

        Parameters
        ----------
        field_name : str
            The canonical field name whose policy or value is requested.
        detail_code : str
            The stable detail code from the relevant closed catalog.
        """
        self.field_name = field_name
        self.detail_code = detail_code
        super().__init__("The account inventory input is invalid.")


class PlatformAccountInventoryCursorStaleError(PlatformAccountInventoryError):
    """Signal platform account inventory cursor stale."""

    code = "account_inventory_cursor_stale"


class PlatformAccountInventoryLimitExceededError(PlatformAccountInventoryError):
    """Signal platform account inventory limit exceeded."""

    code = "account_inventory_limit_exceeded"


class PlatformAccountInventoryUnavailableError(PlatformAccountInventoryError):
    """Signal platform account inventory unavailable."""

    code = "account_inventory_unavailable"


class PlatformAccountInvitationNotFoundError(PlatformAccountInventoryError):
    """Signal platform account invitation not found."""

    code = "account_invitation_not_found"


@dataclass(frozen=True, slots=True)
class AccountInvitationSummary:
    """Describe account invitation summary.

    Attributes
    ----------
    invitation_id
        The invitation identifier within the requested scope.
    status
        The closed status value to evaluate or expose.
    aggregate_version
        The expected aggregate version used to reject stale updates.
    expires_at
        The timezone-aware timestamp for expires.
    last_transition_at
        The timezone-aware timestamp for last transition.
    delivery_state
        The closed delivery state discriminator defined by the domain catalog.
    """

    invitation_id: UUID
    status: str
    aggregate_version: int
    expires_at: datetime
    last_transition_at: datetime
    delivery_state: str | None


@dataclass(frozen=True, slots=True)
class AccountInventoryItem:
    """Describe account inventory item.

    Attributes
    ----------
    account_id
        The platform account identifier within the requested scope.
    email
        The normalized email address used for delivery or identity matching.
    login_handle
        The login handle retained in this immutable projection.
    display_name
        The human-readable display name shown to authorized readers.
    account_kind
        The closed account kind discriminator defined by the domain catalog.
    is_active
        Whether to is active.
    is_email_verified
        Whether to is email verified.
    date_joined
        The date joined retained in this immutable projection.
    current_invitation
        The current invitation retained in this immutable projection.
    """

    account_id: UUID
    email: str
    login_handle: str
    display_name: str
    account_kind: str
    is_active: bool
    is_email_verified: bool
    date_joined: datetime
    current_invitation: AccountInvitationSummary | None


@dataclass(frozen=True, slots=True)
class AccountInventoryPage:
    """Describe account inventory page.

    Attributes
    ----------
    aggregate_version
        The expected aggregate version used to reject stale updates.
    items
        The items retained in this immutable projection.
    next_cursor
        The next cursor retained in this immutable projection.
    """

    aggregate_version: int
    items: tuple[AccountInventoryItem, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class InvitationDeliverySummary:
    """Describe invitation delivery summary.

    Attributes
    ----------
    delivery_id
        The delivery identifier within the requested scope.
    aggregate_version
        The expected aggregate version used to reject stale updates.
    status
        The closed status value to evaluate or expose.
    attempt_count
        The bounded number of attempt records.
    max_attempts
        The max attempts retained in this immutable projection.
    last_attempt_at
        The timezone-aware timestamp for last attempt.
    next_retry_at
        The timezone-aware timestamp for next retry.
    delivered_at
        The timezone-aware timestamp for delivered.
    safe_error_code
        The stable safe error code from the relevant closed catalog.
    reconciliation_state
        The closed reconciliation state discriminator defined by the domain catalog.
    """

    delivery_id: UUID
    aggregate_version: int
    status: str
    attempt_count: int
    max_attempts: int
    last_attempt_at: datetime | None
    next_retry_at: datetime | None
    delivered_at: datetime | None
    safe_error_code: str
    reconciliation_state: str


@dataclass(frozen=True, slots=True)
class InvitationTransitionItem:
    """Describe invitation transition item.

    Attributes
    ----------
    version
        The version number associated with the supplied record or contract.
    operation
        The stable operation code recorded in audit evidence.
    actor_id
        The immutable identifier of the account authorizing the operation.
    actor_display_name
        The human-readable actor display name shown to authorized readers.
    occurred_at
        The timezone-aware timestamp for occurred.
    reason
        The operator-supplied rationale recorded with the change.
    source_channel
        The closed channel code identifying where the request originated.
    """

    version: int
    operation: str
    actor_id: UUID | None
    actor_display_name: str
    occurred_at: datetime
    reason: str
    source_channel: str


@dataclass(frozen=True, slots=True)
class InvitationDeliveryAttemptItem:
    """Describe invitation delivery attempt item.

    Attributes
    ----------
    delivery_id
        The delivery identifier within the requested scope.
    attempt_number
        The attempt number retained in this immutable projection.
    started_at
        The timezone-aware timestamp for started.
    finished_at
        The timezone-aware timestamp for finished.
    outcome
        The outcome retained in this immutable projection.
    safe_error_code
        The stable safe error code from the relevant closed catalog.
    next_retry_at
        The timezone-aware timestamp for next retry.
    """

    delivery_id: UUID
    attempt_number: int
    started_at: datetime
    finished_at: datetime
    outcome: str
    safe_error_code: str
    next_retry_at: datetime | None


@dataclass(frozen=True, slots=True)
class AccountInvitationDetail:
    """Describe account invitation detail.

    Attributes
    ----------
    aggregate_version
        The expected aggregate version used to reject stale updates.
    invitation_id
        The invitation identifier within the requested scope.
    account_id
        The platform account identifier within the requested scope.
    email
        The normalized email address used for delivery or identity matching.
    login_handle
        The login handle retained in this immutable projection.
    display_name
        The human-readable display name shown to authorized readers.
    account_kind
        The closed account kind discriminator defined by the domain catalog.
    is_active
        Whether to is active.
    is_email_verified
        Whether to is email verified.
    status
        The closed status value to evaluate or expose.
    invitation_version
        The expected invitation version used to reject stale updates.
    expires_at
        The timezone-aware timestamp for expires.
    created_at
        The timezone-aware timestamp for created.
    last_transition_at
        The timezone-aware timestamp for last transition.
    created_by_id
        The created by identifier within the requested scope.
    created_by_display_name
        The human-readable created by display name shown to authorized readers.
    current_delivery
        The current delivery retained in this immutable projection.
    transitions
        The transitions retained in this immutable projection.
    delivery_attempts
        The delivery attempts retained in this immutable projection.
    """

    aggregate_version: int
    invitation_id: UUID
    account_id: UUID
    email: str
    login_handle: str
    display_name: str
    account_kind: str
    is_active: bool
    is_email_verified: bool
    status: str
    invitation_version: int
    expires_at: datetime
    created_at: datetime
    last_transition_at: datetime
    created_by_id: UUID
    created_by_display_name: str
    current_delivery: InvitationDeliverySummary | None
    transitions: tuple[InvitationTransitionItem, ...]
    delivery_attempts: tuple[InvitationDeliveryAttemptItem, ...]


@dataclass(frozen=True, slots=True)
class PlatformAccountSensitiveReadAudit:
    """Describe platform account sensitive read audit.

    Attributes
    ----------
    actor_id
        The immutable identifier of the account authorizing the operation.
    operation
        The stable operation code recorded in audit evidence.
    target_id
        The target identifier within the requested scope.
    aggregate_version
        The expected aggregate version used to reject stale updates.
    result_count
        The bounded number of result records.
    correlation_id
        The request correlation identifier used for audit tracing.
    source_channel
        The closed channel code identifying where the request originated.
    """

    actor_id: UUID
    operation: str
    target_id: UUID | None
    aggregate_version: int
    result_count: int
    correlation_id: UUID
    source_channel: str


PlatformAccountAuditHook = Callable[[PlatformAccountSensitiveReadAudit], None]


@dataclass(frozen=True, slots=True)
class _DecodedCursor:
    query_digest: str
    aggregate_version: int
    date_joined: datetime
    account_id: UUID


def _raise_input(*, field_name: str, detail_code: str) -> Never:
    raise PlatformAccountInventoryInputError(
        field_name=field_name,
        detail_code=detail_code,
    )


def normalize_account_inventory_search(value: object | None) -> str | None:
    """Normalize optional exact/prefix search without permitting controls.

    Parameters
    ----------
    value : object | None
        The untrusted input to normalize, validate, or compare.

    Returns
    -------
    str | None
        The normalized text for normalize account inventory search.
    """
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        _raise_input(field_name="search", detail_code="search_type_invalid")
    if any(
        unicodedata.category(character) in _FORBIDDEN_SEARCH_CATEGORIES
        for character in value
    ):
        _raise_input(field_name="search", detail_code="search_control_character")
    normalized = " ".join(unicodedata.normalize("NFC", value).split()).casefold()
    if not normalized:
        return None
    if not (
        MIN_ACCOUNT_INVENTORY_SEARCH_LENGTH
        <= len(normalized)
        <= MAX_ACCOUNT_INVENTORY_SEARCH_LENGTH
    ):
        _raise_input(field_name="search", detail_code="search_length_invalid")
    return normalized


def _validate_page_size(value: object) -> int:
    if type(value) is not int or not 1 <= value <= MAX_ACCOUNT_INVENTORY_PAGE_SIZE:
        _raise_input(field_name="page_size", detail_code="page_size_invalid")
    return value


def _validate_choice(
    value: object | None,
    *,
    field_name: str,
    choices: frozenset[str],
) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or value not in choices:
        _raise_input(field_name=field_name, detail_code=f"{field_name}_invalid")
    return value


def _require_platform_administrator(actor_id: UUID) -> None:
    allowed = Account.objects.filter(
        id=actor_id,
        is_active=True,
        is_staff=True,
        is_superuser=True,
        account_kind=Account.Kind.PLATFORM_ADMINISTRATOR,
    ).exists()
    if not allowed:
        raise PlatformAccountInventoryDeniedError(
            "Platform account inventory access is denied."
        )


def _inventory_version() -> int:
    version = (
        PlatformAccountInventoryControl.objects.filter(singleton=True)
        .values_list("aggregate_version", flat=True)
        .first()
    )
    if version is None:
        raise PlatformAccountInventoryUnavailableError(
            "The account inventory is temporarily unavailable."
        )
    return int(version)


def _query_digest(
    *,
    search: str | None,
    search_mode: str,
    kind: str | None,
    state: str | None,
    page_size: int,
) -> str:
    canonical = (
        f"search={search or ''}\nmode={search_mode}\nkind={kind or ''}\n"
        f"state={state or ''}\npage_size={page_size}"
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _encode_cursor(
    *,
    query_digest: str,
    aggregate_version: int,
    item: AccountInventoryItem,
) -> str:
    return signing.dumps(
        {
            "v": 1,
            "q": query_digest,
            "aggregate_version": aggregate_version,
            "date_joined": item.date_joined.isoformat(),
            "account_id": str(item.account_id),
        },
        salt=_CURSOR_SALT,
        compress=False,
    )


def _decode_cursor(value: object | None, *, query_digest: str) -> _DecodedCursor | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > MAX_ACCOUNT_INVENTORY_CURSOR_LENGTH:
        _raise_input(field_name="cursor", detail_code="cursor_invalid")
    try:
        payload = signing.loads(
            value,
            salt=_CURSOR_SALT,
            max_age=ACCOUNT_INVENTORY_CURSOR_MAX_AGE_SECONDS,
        )
    except signing.BadSignature:
        _raise_input(field_name="cursor", detail_code="cursor_invalid")
    if not isinstance(payload, dict) or set(payload) != {
        "v",
        "q",
        "aggregate_version",
        "date_joined",
        "account_id",
    }:
        _raise_input(field_name="cursor", detail_code="cursor_invalid")
    if payload["v"] != 1 or payload["q"] != query_digest:
        _raise_input(field_name="cursor", detail_code="cursor_invalid")
    aggregate_version = payload["aggregate_version"]
    if type(aggregate_version) is not int or aggregate_version < 0:
        _raise_input(field_name="cursor", detail_code="cursor_invalid")
    date_joined_value = payload["date_joined"]
    account_id_value = payload["account_id"]
    if not isinstance(date_joined_value, str) or not isinstance(account_id_value, str):
        _raise_input(field_name="cursor", detail_code="cursor_invalid")
    date_joined = parse_datetime(date_joined_value)
    try:
        account_id = UUID(account_id_value)
    except ValueError:
        _raise_input(field_name="cursor", detail_code="cursor_invalid")
    if (
        date_joined is None
        or date_joined.tzinfo is None
        or str(account_id) != account_id_value
        or _SAFE_DIGEST.fullmatch(payload["q"]) is None
    ):
        _raise_input(field_name="cursor", detail_code="cursor_invalid")
    return _DecodedCursor(
        query_digest=query_digest,
        aggregate_version=aggregate_version,
        date_joined=date_joined,
        account_id=account_id,
    )


def _account_search_query(*, search: str, mode: str) -> Q:
    lookup = "iexact" if mode == "exact" else "istartswith"
    return (
        Q(**{f"email__{lookup}": search})
        | Q(**{f"login_handle__{lookup}": search})
        | Q(**{f"display_name__{lookup}": search})
    )


def _latest_invitations(account_ids: tuple[UUID, ...]) -> dict[UUID, Any]:
    if not account_ids:
        return {}
    rows = (
        PlatformAccountInvitation.objects.filter(account_id__in=account_ids)
        .order_by("account_id", "-last_transition_at", "-created_at", "-id")
        .distinct("account_id")
        .values(
            "id",
            "account_id",
            "status",
            "aggregate_version",
            "expires_at",
            "last_transition_at",
        )
    )
    return {row["account_id"]: row for row in rows}


def _latest_delivery_states(invitation_ids: tuple[UUID, ...]) -> dict[UUID, str]:
    if not invitation_ids:
        return {}
    rows = (
        PlatformIdentityDelivery.objects.filter(invitation_id__in=invitation_ids)
        .order_by("invitation_id", "-created_at", "-id")
        .distinct("invitation_id")
        .values("invitation_id", "status")
    )
    return {row["invitation_id"]: str(row["status"]) for row in rows}


def _load_inventory_attempt(
    *,
    search: str | None,
    search_mode: str,
    kind: str | None,
    state: str | None,
    page_size: int,
    cursor: _DecodedCursor | None,
    query_digest: str,
) -> AccountInventoryPage | None:
    before_version = _inventory_version()
    if cursor is not None and cursor.aggregate_version != before_version:
        raise PlatformAccountInventoryCursorStaleError(
            "The account inventory changed after this cursor was issued."
        )

    accounts = Account.objects.all()
    if search is not None:
        accounts = accounts.filter(
            _account_search_query(search=search, mode=search_mode)
        )
    if kind is not None:
        accounts = accounts.filter(account_kind=kind)
    if state is not None:
        accounts = accounts.filter(is_active=(state == "active"))
    if cursor is not None:
        accounts = accounts.filter(
            Q(date_joined__gt=cursor.date_joined)
            | Q(date_joined=cursor.date_joined, id__gt=cursor.account_id)
        )

    rows = list(
        accounts.order_by("date_joined", "id").values(
            "id",
            "email",
            "login_handle",
            "display_name",
            "account_kind",
            "is_active",
            "email_verified_at",
            "date_joined",
        )[: page_size + 1]
    )
    page_rows = rows[:page_size]
    account_ids = tuple(row["id"] for row in page_rows)
    invitation_rows = _latest_invitations(account_ids)
    invitation_ids = tuple(cast("UUID", row["id"]) for row in invitation_rows.values())
    delivery_states = _latest_delivery_states(invitation_ids)

    items: list[AccountInventoryItem] = []
    for row in page_rows:
        account_id = row["id"]
        invitation_row = invitation_rows.get(account_id)
        invitation = None
        if invitation_row is not None:
            invitation_id = cast("UUID", invitation_row["id"])
            invitation = AccountInvitationSummary(
                invitation_id=invitation_id,
                status=str(invitation_row["status"]),
                aggregate_version=int(invitation_row["aggregate_version"]),
                expires_at=cast("datetime", invitation_row["expires_at"]),
                last_transition_at=cast(
                    "datetime",
                    invitation_row["last_transition_at"],
                ),
                delivery_state=delivery_states.get(invitation_id),
            )
        items.append(
            AccountInventoryItem(
                account_id=account_id,
                email=str(row["email"]),
                login_handle=str(row["login_handle"]),
                display_name=str(row["display_name"]),
                account_kind=str(row["account_kind"]),
                is_active=bool(row["is_active"]),
                is_email_verified=row["email_verified_at"] is not None,
                date_joined=row["date_joined"],
                current_invitation=invitation,
            )
        )

    after_version = _inventory_version()
    if before_version != after_version:
        return None
    next_cursor = None
    if len(rows) > page_size:
        next_cursor = _encode_cursor(
            query_digest=query_digest,
            aggregate_version=before_version,
            item=items[-1],
        )
    return AccountInventoryPage(
        aggregate_version=before_version,
        items=tuple(items),
        next_cursor=next_cursor,
    )


def _load_stable_inventory(
    *,
    search: str | None,
    search_mode: str,
    kind: str | None,
    state: str | None,
    page_size: int,
    cursor: _DecodedCursor | None,
    query_digest: str,
) -> AccountInventoryPage:
    for _attempt in range(MAX_ACCOUNT_INVENTORY_READ_ATTEMPTS):
        projection = _load_inventory_attempt(
            search=search,
            search_mode=search_mode,
            kind=kind,
            state=state,
            page_size=page_size,
            cursor=cursor,
            query_digest=query_digest,
        )
        if projection is not None:
            return projection
    raise PlatformAccountInventoryUnavailableError(
        "The account inventory is temporarily unavailable."
    )


def load_platform_account_inventory(
    *,
    actor: Account,
    audit_hook: PlatformAccountAuditHook,
    correlation_id: UUID,
    source_channel: str,
    search: object | None = None,
    search_mode: object = "prefix",
    kind: object | None = None,
    state: object | None = None,
    cursor: object | None = None,
    page_size: object = MAX_ACCOUNT_INVENTORY_PAGE_SIZE,
) -> AccountInventoryPage:
    """Return one complete, audited platform account inventory page.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    audit_hook : PlatformAccountAuditHook
        The audit hook evaluated while load platform account inventory.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    source_channel : str
        The closed channel code identifying where the request originated.
    search : object | None, default=None
        The search evaluated while load platform account inventory.
    search_mode : object, default='prefix'
        The closed search mode discriminator defined by the domain catalog.
    kind : object | None, default=None
        The closed discriminator selecting the requested behavior.
    state : object | None, default=None
        The lifecycle state to evaluate or expose.
    cursor : object | None, default=None
        The cursor evaluated while load platform account inventory.
    page_size : object, default=MAX_ACCOUNT_INVENTORY_PAGE_SIZE
        The page size evaluated while load platform account inventory.

    Returns
    -------
    AccountInventoryPage
        The resolved AccountInventoryPage for the requested scope.

    Raises
    ------
    PlatformAccountInventoryError
        If the requested operation violates this domain contract.
    PlatformAccountInventoryUnavailableError
        If the scoped target does not exist or cannot be disclosed.
    """
    try:
        _require_platform_administrator(actor.id)
        normalized_search = normalize_account_inventory_search(search)
        normalized_mode = _validate_choice(
            search_mode,
            field_name="search_mode",
            choices=ACCOUNT_INVENTORY_SEARCH_MODES,
        )
        if normalized_mode is None:
            _raise_input(
                field_name="search_mode",
                detail_code="search_mode_invalid",
            )
        normalized_kind = _validate_choice(
            kind,
            field_name="kind",
            choices=ACCOUNT_INVENTORY_KINDS,
        )
        normalized_state = _validate_choice(
            state,
            field_name="state",
            choices=ACCOUNT_INVENTORY_STATES,
        )
        normalized_page_size = _validate_page_size(page_size)
        validated_correlation_id = validate_correlation_id(correlation_id)
        validated_source_channel = validate_source_channel(source_channel)
        query_digest = _query_digest(
            search=normalized_search,
            search_mode=normalized_mode,
            kind=normalized_kind,
            state=normalized_state,
            page_size=normalized_page_size,
        )
        decoded_cursor = _decode_cursor(cursor, query_digest=query_digest)
        projection = _load_stable_inventory(
            search=normalized_search,
            search_mode=normalized_mode,
            kind=normalized_kind,
            state=normalized_state,
            page_size=normalized_page_size,
            cursor=decoded_cursor,
            query_digest=query_digest,
        )
        _require_platform_administrator(actor.id)
    except PlatformAccountInventoryError:
        raise
    except DatabaseError:
        raise PlatformAccountInventoryUnavailableError(
            "The account inventory is temporarily unavailable."
        ) from None

    try:
        audit_hook(
            PlatformAccountSensitiveReadAudit(
                actor_id=actor.id,
                operation="identity.account_inventory.read",
                target_id=None,
                aggregate_version=projection.aggregate_version,
                result_count=len(projection.items),
                correlation_id=validated_correlation_id,
                source_channel=validated_source_channel,
            )
        )
    except Exception:  # noqa: BLE001 - every audit-hook failure must fail closed.
        raise PlatformAccountInventoryUnavailableError(
            "The account inventory is temporarily unavailable."
        ) from None
    return projection


def _delivery_summary(row: Any | None) -> InvitationDeliverySummary | None:
    if row is None:
        return None
    return InvitationDeliverySummary(
        delivery_id=cast("UUID", row["id"]),
        aggregate_version=int(row["aggregate_version"]),
        status=str(row["status"]),
        attempt_count=int(row["attempt_count"]),
        max_attempts=int(row["max_attempts"]),
        last_attempt_at=cast("datetime | None", row["last_attempt_at"]),
        next_retry_at=cast("datetime | None", row["next_retry_at"]),
        delivered_at=cast("datetime | None", row["delivered_at"]),
        safe_error_code=str(row["safe_error_code"]),
        reconciliation_state=str(row["reconciliation_state"]),
    )


def _load_invitation_detail_attempt(
    *,
    invitation_id: UUID,
) -> AccountInvitationDetail | None:
    before_version = _inventory_version()
    row = (
        PlatformAccountInvitation.objects.filter(id=invitation_id)
        .values(
            "id",
            "account_id",
            "account__email",
            "account__login_handle",
            "account__display_name",
            "account__account_kind",
            "account__is_active",
            "account__email_verified_at",
            "status",
            "aggregate_version",
            "expires_at",
            "created_at",
            "last_transition_at",
            "created_by_id",
            "created_by__display_name",
            "created_by__login_handle",
        )
        .first()
    )
    if row is None:
        raise PlatformAccountInvitationNotFoundError(
            "The account invitation does not exist."
        )

    delivery_row = (
        PlatformIdentityDelivery.objects.filter(invitation_id=invitation_id)
        .order_by("-created_at", "-id")
        .values(
            "id",
            "aggregate_version",
            "status",
            "attempt_count",
            "max_attempts",
            "last_attempt_at",
            "next_retry_at",
            "delivered_at",
            "safe_error_code",
            "reconciliation_state",
        )
        .first()
    )
    transition_rows = list(
        PlatformAccountInvitationTransition.objects.filter(invitation_id=invitation_id)
        .order_by("version", "id")
        .values(
            "version",
            "operation",
            "actor_id",
            "actor__display_name",
            "actor__login_handle",
            "occurred_at",
            "reason",
            "source_channel",
        )[: MAX_INVITATION_DETAIL_TIMELINE_ROWS + 1]
    )
    attempt_rows = list(
        PlatformIdentityDeliveryAttempt.objects.filter(
            delivery__invitation_id=invitation_id
        )
        .order_by("started_at", "id")
        .values(
            "delivery_id",
            "attempt_number",
            "started_at",
            "finished_at",
            "outcome",
            "safe_error_code",
            "next_retry_at",
        )[: MAX_INVITATION_DETAIL_TIMELINE_ROWS + 1]
    )
    if len(transition_rows) + len(attempt_rows) > MAX_INVITATION_DETAIL_TIMELINE_ROWS:
        raise PlatformAccountInventoryLimitExceededError(
            "The invitation timeline exceeds the account inventory limit."
        )

    transitions = tuple(
        InvitationTransitionItem(
            version=int(item["version"]),
            operation=str(item["operation"]),
            actor_id=item["actor_id"],
            actor_display_name=str(
                item["actor__display_name"] or item["actor__login_handle"] or ""
            ),
            occurred_at=item["occurred_at"],
            reason=str(item["reason"]),
            source_channel=str(item["source_channel"]),
        )
        for item in transition_rows
    )
    delivery_attempts = tuple(
        InvitationDeliveryAttemptItem(
            delivery_id=item["delivery_id"],
            attempt_number=int(item["attempt_number"]),
            started_at=item["started_at"],
            finished_at=item["finished_at"],
            outcome=str(item["outcome"]),
            safe_error_code=str(item["safe_error_code"]),
            next_retry_at=item["next_retry_at"],
        )
        for item in attempt_rows
    )

    after_version = _inventory_version()
    if before_version != after_version:
        return None
    return AccountInvitationDetail(
        aggregate_version=before_version,
        invitation_id=row["id"],
        account_id=row["account_id"],
        email=str(row["account__email"]),
        login_handle=str(row["account__login_handle"]),
        display_name=str(row["account__display_name"]),
        account_kind=str(row["account__account_kind"]),
        is_active=bool(row["account__is_active"]),
        is_email_verified=row["account__email_verified_at"] is not None,
        status=str(row["status"]),
        invitation_version=int(row["aggregate_version"]),
        expires_at=row["expires_at"],
        created_at=row["created_at"],
        last_transition_at=row["last_transition_at"],
        created_by_id=row["created_by_id"],
        created_by_display_name=str(
            row["created_by__display_name"] or row["created_by__login_handle"] or ""
        ),
        current_delivery=_delivery_summary(delivery_row),
        transitions=transitions,
        delivery_attempts=delivery_attempts,
    )


def load_platform_account_invitation_detail(
    *,
    actor: Account,
    invitation_id: object,
    audit_hook: PlatformAccountAuditHook,
    correlation_id: UUID,
    source_channel: str,
) -> AccountInvitationDetail:
    """Return one complete, audited invitation detail projection.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    invitation_id : object
        The invitation identifier within the requested scope.
    audit_hook : PlatformAccountAuditHook
        The audit hook evaluated while load platform account invitation detail.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    source_channel : str
        The closed channel code identifying where the request originated.

    Returns
    -------
    AccountInvitationDetail
        The resolved AccountInvitationDetail for the requested scope.

    Raises
    ------
    PlatformAccountInventoryError
        If the requested operation violates this domain contract.
    PlatformAccountInventoryUnavailableError
        If the scoped target does not exist or cannot be disclosed.
    """
    try:
        _require_platform_administrator(actor.id)
        if not isinstance(invitation_id, UUID):
            _raise_input(
                field_name="invitation_id",
                detail_code="invitation_id_invalid",
            )
        validated_correlation_id = validate_correlation_id(correlation_id)
        validated_source_channel = validate_source_channel(source_channel)
        validated_invitation_id = invitation_id
        projection = None
        for _attempt in range(MAX_ACCOUNT_INVENTORY_READ_ATTEMPTS):
            projection = _load_invitation_detail_attempt(
                invitation_id=validated_invitation_id
            )
            if projection is not None:
                break
        if projection is None:
            raise PlatformAccountInventoryUnavailableError(
                "The account inventory is temporarily unavailable."
            )
        _require_platform_administrator(actor.id)
    except PlatformAccountInventoryError:
        raise
    except DatabaseError:
        raise PlatformAccountInventoryUnavailableError(
            "The account inventory is temporarily unavailable."
        ) from None

    try:
        audit_hook(
            PlatformAccountSensitiveReadAudit(
                actor_id=actor.id,
                operation="identity.account_invitation.read",
                target_id=projection.invitation_id,
                aggregate_version=projection.aggregate_version,
                result_count=(
                    len(projection.transitions) + len(projection.delivery_attempts)
                ),
                correlation_id=validated_correlation_id,
                source_channel=validated_source_channel,
            )
        )
    except Exception:  # noqa: BLE001 - every audit-hook failure must fail closed.
        raise PlatformAccountInventoryUnavailableError(
            "The account inventory is temporarily unavailable."
        ) from None
    return projection
