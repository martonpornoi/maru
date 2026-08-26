"""Policy-scoped REST adapters for Shift demand and person-owned commitments."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Never, cast
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError
from django.utils.decorators import method_decorator
from django.utils.timezone import now as timezone_now
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import APIException, NotFound, PermissionDenied
from rest_framework.exceptions import ValidationError as ApiValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from maru.authorization.enforcement import (
    FieldProjectionDeniedError,
    require_complete_projection,
)
from maru.authorization.policy import (
    PolicyDecision,
    decide,
    resolve_edition_target,
    resolve_self_target,
)
from maru.core.api_input import reject_unknown_fields
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.workforce.shift_audit import append_shift_read_audit
from maru.workforce.shift_commands import (
    ShiftAuthorizationDeniedError,
    ShiftAvailabilityConflictError,
    ShiftCapacityConflictError,
    ShiftCommandError,
    ShiftCommitmentCommandResult,
    ShiftDemandCommandResult,
    ShiftLifecycleConflictError,
    ShiftOverlapConflictError,
    ShiftQualificationConflictError,
    ShiftRetryConflictError,
    ShiftStateConflictError,
    ShiftUnavailableError,
    ShiftVersionConflictError,
    authorize_shift_organizer_command,
    authorize_shift_self_command,
    cancel_shift_demand,
    claim_shift,
    complete_shift_demand,
    confirm_shift_commitment,
    create_shift_demand,
    lock_shift_demand,
    open_shift_demand,
    remove_shift_commitment,
    reopen_shift_demand,
    update_shift_demand,
    withdraw_shift_claim,
)
from maru.workforce.shift_queries import (
    SHIFT_ORGANIZER_REQUIRED_FIELDS,
    OrganizerShiftDemandItem,
    ShiftProjectionIntegrityError,
    ShiftReadLimitExceededError,
    load_my_shift_overview,
    load_organizer_shift_overview,
    person_has_shift_relationship,
)
from maru.workforce.shift_serializers import (
    MyShiftOverviewSerializer,
    OrganizerShiftDemandSerializer,
    OrganizerShiftOverviewSerializer,
    ShiftClaimCommandSerializer,
    ShiftDemandUpdateSerializer,
    ShiftDemandWriteSerializer,
    ShiftLockCommandSerializer,
    ShiftMutationResultSerializer,
    ShiftReasonCommandSerializer,
    ShiftWithdrawCommandSerializer,
)
from maru.workforce.structure_snapshot import repeatable_read_only_snapshot

logger = logging.getLogger(__name__)
IDEMPOTENCY_HEADER = "Idempotency-Key"
MAX_IDEMPOTENCY_HEADER_LENGTH = 36

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from rest_framework.request import Request


class WorkforceShiftConflict(APIException):
    """RFC 9457-style, name-free Shift command conflict."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "The Shift action conflicts with current state."
    default_code = "shift_conflict"

    def __init__(self, *, code: str, errors: dict[str, list[str]]) -> None:
        """Initialize a stable conflict payload.

        Parameters
        ----------
        code : str
            Stable machine-readable conflict code.
        errors : dict[str, list[str]]
            Safe field-oriented recovery messages.
        """
        super().__init__(
            detail=cast(
                "Any",
                {
                    "detail": self.default_detail,
                    "code": code,
                    "errors": errors,
                },
            ),
            code=code,
        )


class WorkforceShiftDependencyUnavailable(APIException):
    """Fail closed when complete Shift state cannot be produced."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Workforce Shifts are temporarily unavailable."
    default_code = "shift_dependency_unavailable"


@dataclass(frozen=True, slots=True)
class _OrganizerAPIScope:
    """Authorized exact-edition organizer scope before body parsing."""

    account: Account
    edition: EventEdition
    decision: PolicyDecision
    can_manage: bool


@dataclass(frozen=True, slots=True)
class _PersonalAPIScope:
    """Authorized person-owned exact-edition scope before body parsing."""

    account: Account
    edition: EventEdition


def _account(request: Request) -> Account:
    account = request.user
    if not isinstance(account, Account) or not account.is_active:
        raise PermissionDenied("Current Shift authority is unavailable.")
    return account


def _edition(*, organization_id: UUID, edition_id: UUID) -> EventEdition:
    edition = (
        EventEdition.objects.select_related("organization", "series")
        .filter(
            id=edition_id,
            organization_id=organization_id,
            series__organization_id=organization_id,
        )
        .order_by()
        .first()
    )
    if edition is None:
        raise PermissionDenied("Current Shift authority is unavailable.")
    return edition


def _organizer_scope(
    *, request: Request, organization_id: UUID, edition_id: UUID, manage: bool
) -> _OrganizerAPIScope:
    account = _account(request)
    edition = _edition(organization_id=organization_id, edition_id=edition_id)
    target = resolve_edition_target(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    evaluated_at = timezone_now()
    decision = decide(
        principal=account,
        capability_code="workforce.view_shifts",
        resource=target,
        requested_fields=SHIFT_ORGANIZER_REQUIRED_FIELDS,
        at=evaluated_at,
    )
    if not decision.allowed:
        raise PermissionDenied("Current Shift authority is unavailable.")
    try:
        require_complete_projection(
            required_fields=SHIFT_ORGANIZER_REQUIRED_FIELDS,
            permitted_fields=decision.fields,
        )
    except FieldProjectionDeniedError as error:
        raise PermissionDenied("Current Shift authority is unavailable.") from error
    manage_allowed = decide(
        principal=account,
        capability_code="workforce.manage_shifts",
        resource=target,
        at=evaluated_at,
    ).allowed
    if manage and not manage_allowed:
        raise PermissionDenied("Current Shift authority is unavailable.")
    if manage:
        try:
            authorize_shift_organizer_command(
                actor=account,
                organization_id=organization_id,
                edition_id=edition_id,
            )
        except ShiftAuthorizationDeniedError as error:
            raise PermissionDenied("Current Shift authority is unavailable.") from error
    return _OrganizerAPIScope(
        account=account,
        edition=edition,
        decision=decision,
        can_manage=manage_allowed,
    )


def _personal_scope(
    *, request: Request, organization_id: UUID, edition_id: UUID, manage: bool
) -> _PersonalAPIScope:
    account = _account(request)
    edition = _edition(organization_id=organization_id, edition_id=edition_id)
    target = resolve_self_target(
        principal=account,
        organization_id=organization_id,
        edition_id=edition_id,
    )
    decision = decide(
        principal=account,
        capability_code="workforce.view_self",
        resource=target,
        requested_fields=frozenset({"shifts"}),
    )
    if not decision.allowed or decision.fields != frozenset({"shifts"}):
        raise PermissionDenied("Current personal Shift access is unavailable.")
    if not person_has_shift_relationship(
        account=account,
        organization_id=organization_id,
        edition_id=edition_id,
    ):
        raise PermissionDenied("Current personal Shift access is unavailable.")
    if manage:
        try:
            authorize_shift_self_command(
                actor=account,
                organization_id=organization_id,
                edition_id=edition_id,
            )
        except ShiftAuthorizationDeniedError as error:
            raise PermissionDenied(
                "Current personal Shift access is unavailable."
            ) from error
    return _PersonalAPIScope(account=account, edition=edition)


def _idempotency_key(request: Request) -> UUID:
    raw_value = request.headers.get(IDEMPOTENCY_HEADER)
    if raw_value is None or not raw_value.strip():
        raise ApiValidationError(
            {
                "detail": "The Idempotency-Key header is required.",
                "code": "missing_idempotency_key",
                "errors": {IDEMPOTENCY_HEADER: ["Enter one canonical UUID."]},
            }
        )
    candidate = raw_value.strip()
    if len(candidate) > MAX_IDEMPOTENCY_HEADER_LENGTH:
        raise ApiValidationError({IDEMPOTENCY_HEADER: ["Enter one canonical UUID."]})
    try:
        value = UUID(candidate)
    except ValueError as error:
        raise ApiValidationError(
            {IDEMPOTENCY_HEADER: ["Enter one canonical UUID."]}
        ) from error
    if str(value) != candidate:
        raise ApiValidationError({IDEMPOTENCY_HEADER: ["Enter one canonical UUID."]})
    return value


def _payload(
    request: Request,
    *,
    serializer_class: type[serializers.Serializer[dict[str, object]]],
) -> dict[str, object]:
    reject_unknown_fields(request.query_params, allowed_fields=frozenset())
    payload = request.data
    serializer = serializer_class(data=payload)
    reject_unknown_fields(payload, allowed_fields=frozenset(serializer.fields))
    serializer.is_valid(raise_exception=True)
    return cast("dict[str, object]", serializer.validated_data)


def _raise_command_error(error: Exception) -> Never:
    if isinstance(error, ShiftAuthorizationDeniedError):
        raise PermissionDenied("Current Shift authority is unavailable.") from error
    if isinstance(error, ShiftUnavailableError):
        raise NotFound("The Shift target is unavailable.") from error
    conflict_fields: dict[type[ShiftCommandError], tuple[str, str]] = {
        ShiftVersionConflictError: (
            "expected_version",
            "Reload the Shift before retrying.",
        ),
        ShiftRetryConflictError: (
            IDEMPOTENCY_HEADER,
            "Use a new Idempotency-Key for different input.",
        ),
        ShiftAvailabilityConflictError: (
            "non_field_errors",
            "Current shared Availability does not cover this Shift.",
        ),
        ShiftQualificationConflictError: (
            "non_field_errors",
            "A current matching Position assignment is required.",
        ),
        ShiftCapacityConflictError: (
            "non_field_errors",
            str(error) or "The Shift has no remaining suitable capacity.",
        ),
        ShiftOverlapConflictError: (
            "non_field_errors",
            "The Shift overlaps active work or required rest.",
        ),
        ShiftLifecycleConflictError: (
            "non_field_errors",
            "This edition is read-only for the requested Shift action.",
        ),
        ShiftStateConflictError: (
            "non_field_errors",
            str(error) or "The Shift is in an incompatible state.",
        ),
    }
    for error_type, (field, message) in conflict_fields.items():
        if isinstance(error, error_type):
            raise WorkforceShiftConflict(
                code=error.reason_code,
                errors={field: [message]},
            ) from error
    if isinstance(error, DjangoValidationError):
        safe_fields = {
            "position_id",
            "title",
            "location_label",
            "briefing",
            "supervision_note",
            "starts_at",
            "ends_at",
            "required_headcount",
            "break_minutes",
            "minimum_rest_minutes",
            "reason",
            "expected_version",
        }
        if hasattr(error, "message_dict"):
            errors = {
                key: values
                for key, values in error.message_dict.items()
                if key in safe_fields
            }
            if errors:
                raise ApiValidationError(errors) from error
        raise WorkforceShiftDependencyUnavailable from error
    if isinstance(error, (DatabaseError, ShiftCommandError, RuntimeError)):
        raise WorkforceShiftDependencyUnavailable from error
    raise error


def _demand_payload(item: OrganizerShiftDemandItem) -> dict[str, object]:
    demand = item.demand
    return {
        "id": demand.id,
        "position_id": demand.position_id,
        "department_name": item.department_name,
        "position_title": item.position_title,
        "title": demand.title,
        "location_label": demand.location_label,
        "briefing": demand.briefing,
        "supervision_note": demand.supervision_note,
        "starts_at": demand.starts_at,
        "ends_at": demand.ends_at,
        "required_headcount": demand.required_headcount,
        "break_minutes": demand.break_minutes,
        "minimum_rest_minutes": demand.minimum_rest_minutes,
        "status": demand.status,
        "command_version": demand.command_version,
        "claimed_count": item.claimed_count,
        "confirmed_count": item.confirmed_count,
        "active_count": item.active_count,
        "remaining_count": item.remaining_count,
        "commitments": [
            {
                "id": commitment.commitment.id,
                "account_label": commitment.account_label,
                "status": commitment.commitment.status,
                "command_version": commitment.commitment.command_version,
                "availability_version": commitment.commitment.availability_version,
                "availability_current": commitment.availability_current,
                "qualification_current": commitment.qualification_current,
                "claimed_at": commitment.commitment.claimed_at,
                "confirmed_at": commitment.commitment.confirmed_at,
                "confirmation_reason": commitment.commitment.confirmation_reason,
                "removed_at": commitment.commitment.removed_at,
                "removal_kind": commitment.commitment.removal_kind,
                "removal_reason": commitment.commitment.removal_reason,
                "completed_at": commitment.commitment.completed_at,
                "completion_reason": commitment.commitment.completion_reason,
            }
            for commitment in item.commitments
        ],
    }


def _organizer_payload(*, scope: _OrganizerAPIScope) -> dict[str, object]:
    overview = load_organizer_shift_overview(edition=scope.edition)
    return {
        "open_count": overview.open_count,
        "locked_count": overview.locked_count,
        "attention_count": overview.attention_count,
        "can_manage": scope.can_manage,
        "demands": [_demand_payload(item) for item in overview.demands],
    }


def _audit_organizer_read(
    *, request: Request, scope: _OrganizerAPIScope, route_name: str
) -> None:
    evaluated_at = timezone_now()
    target = resolve_edition_target(
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
    )
    decision = decide(
        principal=scope.account,
        capability_code="workforce.view_shifts",
        resource=target,
        requested_fields=SHIFT_ORGANIZER_REQUIRED_FIELDS,
        at=evaluated_at,
    )
    if not decision.allowed or decision.fields != SHIFT_ORGANIZER_REQUIRED_FIELDS:
        raise PermissionDenied("Current Shift authority is unavailable.")
    append_shift_read_audit(
        actor=scope.account,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        decision=decision,
        correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
        route_name=route_name,
        http_method=cast("str", request.method),
        source_channel="api",
        occurred_at=evaluated_at,
    )


def _personal_payload(*, scope: _PersonalAPIScope) -> dict[str, object]:
    overview = load_my_shift_overview(account=scope.account, edition=scope.edition)
    return {
        "suitable": [
            {
                "id": item.demand.id,
                "position_title": item.position_title,
                "department_name": item.department_name,
                "title": item.demand.title,
                "location_label": item.demand.location_label,
                "briefing": item.demand.briefing,
                "supervision_note": item.demand.supervision_note,
                "starts_at": item.demand.starts_at,
                "ends_at": item.demand.ends_at,
                "break_minutes": item.demand.break_minutes,
                "minimum_rest_minutes": item.demand.minimum_rest_minutes,
                "command_version": item.demand.command_version,
                "preference": item.preference,
                "remaining_count": item.remaining_count,
            }
            for item in overview.suitable
        ],
        "commitments": [
            {
                "id": item.commitment.id,
                "demand_id": item.demand.id,
                "position_title": item.position_title,
                "department_name": item.department_name,
                "title": item.demand.title,
                "location_label": item.demand.location_label,
                "briefing": item.demand.briefing,
                "supervision_note": item.demand.supervision_note,
                "starts_at": item.demand.starts_at,
                "ends_at": item.demand.ends_at,
                "break_minutes": item.demand.break_minutes,
                "minimum_rest_minutes": item.demand.minimum_rest_minutes,
                "demand_status": item.demand.status,
                "status": item.commitment.status,
                "command_version": item.commitment.command_version,
                "availability_current": item.availability_current,
                "qualification_current": item.qualification_current,
                "can_withdraw": item.can_withdraw,
            }
            for item in overview.commitments
        ],
    }


def _demand_result_payload(result: ShiftDemandCommandResult) -> dict[str, object]:
    return {
        "id": result.demand_id,
        "receipt_id": result.receipt_id,
        "resulting_version": result.resulting_version,
        "status": result.status,
        "replayed": result.replayed,
    }


def _commitment_result_payload(
    result: ShiftCommitmentCommandResult,
) -> dict[str, object]:
    return {
        "id": result.commitment_id,
        "demand_id": result.demand_id,
        "receipt_id": result.receipt_id,
        "resulting_version": result.resulting_version,
        "status": result.status,
        "replayed": result.replayed,
    }


@method_decorator(never_cache, name="dispatch")
class WorkforceShiftDemandCollectionView(APIView):
    """List authorized Shift planning or create a draft demand."""

    @extend_schema(
        operation_id="workforce_list_shift_demands",
        responses={200: OrganizerShiftOverviewSerializer},
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        """Return complete audited organizer Shift planning.

        Parameters
        ----------
        request : Request
            Authenticated API request.
        organization_id : UUID
            Exact organization identifier from the route.
        edition_id : UUID
            Exact edition identifier from the route.

        Returns
        -------
        Response
            Complete serialized organizer Shift projection.

        Raises
        ------
        WorkforceShiftDependencyUnavailable
            If a complete, coherent, audited projection cannot be produced.
        """
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        try:
            with repeatable_read_only_snapshot():
                scope = _organizer_scope(
                    request=request,
                    organization_id=organization_id,
                    edition_id=edition_id,
                    manage=False,
                )
                payload = _organizer_payload(scope=scope)
            scope = _organizer_scope(
                request=request,
                organization_id=organization_id,
                edition_id=edition_id,
                manage=False,
            )
            payload["can_manage"] = scope.can_manage
            _audit_organizer_read(
                request=request,
                scope=scope,
                route_name="workforce-shift-demands",
            )
        except (
            DatabaseError,
            RuntimeError,
            ShiftReadLimitExceededError,
            ShiftProjectionIntegrityError,
        ) as error:
            logger.exception("Unable to project Shift planning API")
            raise WorkforceShiftDependencyUnavailable from error
        return Response(OrganizerShiftOverviewSerializer(payload).data)

    @extend_schema(
        operation_id="workforce_create_shift_demand",
        request=ShiftDemandWriteSerializer,
        responses={201: ShiftMutationResultSerializer},
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        """Create one draft Shift after authorization and strict parsing.

        Parameters
        ----------
        request : Request
            Authenticated API request with one closed JSON command object.
        organization_id : UUID
            Exact organization identifier from the route.
        edition_id : UUID
            Exact edition identifier from the route.

        Returns
        -------
        Response
            Minimized created-demand command result.
        """
        scope = _organizer_scope(
            request=request,
            organization_id=organization_id,
            edition_id=edition_id,
            manage=True,
        )
        retry_key = _idempotency_key(request)
        data = _payload(request, serializer_class=ShiftDemandWriteSerializer)
        try:
            result = create_shift_demand(
                actor=scope.account,
                organization_id=organization_id,
                series_id=scope.edition.series_id,
                edition_id=edition_id,
                position_id=cast("UUID", data["position_id"]),
                title=str(data["title"]),
                location_label=str(data["location_label"]),
                briefing=str(data["briefing"]),
                supervision_note=str(data["supervision_note"]),
                starts_at=cast("datetime", data["starts_at"]),
                ends_at=cast("datetime", data["ends_at"]),
                required_headcount=cast("int", data["required_headcount"]),
                break_minutes=cast("int", data["break_minutes"]),
                minimum_rest_minutes=cast("int", data["minimum_rest_minutes"]),
                reason=str(data["reason"]),
                retry_key=retry_key,
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
                request_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
                source_channel="api",
            )
        except Exception as error:  # noqa: BLE001 - centralized API translation
            _raise_command_error(error)
        payload = _demand_result_payload(result)
        return Response(
            ShiftMutationResultSerializer(payload).data,
            status=status.HTTP_201_CREATED,
        )


@method_decorator(never_cache, name="dispatch")
class WorkforceShiftDemandDetailView(APIView):
    """Read or replace one exact Shift draft."""

    @extend_schema(
        operation_id="workforce_retrieve_shift_demand",
        responses={200: OrganizerShiftDemandSerializer},
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        demand_id: UUID,
    ) -> Response:
        """Return one audited demand and its complete coverage.

        Parameters
        ----------
        request : Request
            Authenticated API request.
        organization_id : UUID
            Exact organization identifier from the route.
        edition_id : UUID
            Exact edition identifier from the route.
        demand_id : UUID
            Exact Shift demand identifier from the route.

        Returns
        -------
        Response
            Complete serialized demand, coverage, and history projection.

        Raises
        ------
        NotFound
            If the authorized projection does not contain the target demand.
        WorkforceShiftDependencyUnavailable
            If a complete, coherent, audited projection cannot be produced.
        """
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        try:
            with repeatable_read_only_snapshot():
                scope = _organizer_scope(
                    request=request,
                    organization_id=organization_id,
                    edition_id=edition_id,
                    manage=False,
                )
                overview = load_organizer_shift_overview(edition=scope.edition)
                item = next(
                    (row for row in overview.demands if row.demand.id == demand_id),
                    None,
                )
            scope = _organizer_scope(
                request=request,
                organization_id=organization_id,
                edition_id=edition_id,
                manage=False,
            )
            if item is None:
                raise NotFound("The Shift target is unavailable.")
            _audit_organizer_read(
                request=request,
                scope=scope,
                route_name="workforce-shift-demand",
            )
        except (
            DatabaseError,
            RuntimeError,
            ShiftReadLimitExceededError,
            ShiftProjectionIntegrityError,
        ) as error:
            raise WorkforceShiftDependencyUnavailable from error
        return Response(OrganizerShiftDemandSerializer(_demand_payload(item)).data)

    @extend_schema(
        operation_id="workforce_update_shift_demand",
        request=ShiftDemandUpdateSerializer,
        responses={200: ShiftMutationResultSerializer},
    )
    def put(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        demand_id: UUID,
    ) -> Response:
        """Replace one unpublished demand after strict version checking.

        Parameters
        ----------
        request : Request
            Authenticated API request with one closed JSON command object.
        organization_id : UUID
            Exact organization identifier from the route.
        edition_id : UUID
            Exact edition identifier from the route.
        demand_id : UUID
            Draft Shift demand identifier from the route.

        Returns
        -------
        Response
            Minimized updated-demand command result.
        """
        scope = _organizer_scope(
            request=request,
            organization_id=organization_id,
            edition_id=edition_id,
            manage=True,
        )
        retry_key = _idempotency_key(request)
        data = _payload(request, serializer_class=ShiftDemandUpdateSerializer)
        try:
            result = update_shift_demand(
                actor=scope.account,
                organization_id=organization_id,
                series_id=scope.edition.series_id,
                edition_id=edition_id,
                demand_id=demand_id,
                expected_version=cast("int", data["expected_version"]),
                title=str(data["title"]),
                location_label=str(data["location_label"]),
                briefing=str(data["briefing"]),
                supervision_note=str(data["supervision_note"]),
                starts_at=cast("datetime", data["starts_at"]),
                ends_at=cast("datetime", data["ends_at"]),
                required_headcount=cast("int", data["required_headcount"]),
                break_minutes=cast("int", data["break_minutes"]),
                minimum_rest_minutes=cast("int", data["minimum_rest_minutes"]),
                reason=str(data["reason"]),
                retry_key=retry_key,
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
                request_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
                source_channel="api",
            )
        except Exception as error:  # noqa: BLE001
            _raise_command_error(error)
        return Response(
            ShiftMutationResultSerializer(_demand_result_payload(result)).data
        )


_DEMAND_ACTION_COMMANDS: dict[str, Callable[..., ShiftDemandCommandResult]] = {
    "open": open_shift_demand,
    "lock": lock_shift_demand,
    "reopen": reopen_shift_demand,
    "complete": complete_shift_demand,
    "cancel": cancel_shift_demand,
}


@method_decorator(never_cache, name="dispatch")
class WorkforceShiftDemandActionView(APIView):
    """Apply one explicit organizer demand lifecycle action."""

    action = ""

    @extend_schema(
        request=ShiftReasonCommandSerializer,
        responses={200: ShiftMutationResultSerializer},
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        demand_id: UUID,
    ) -> Response:
        """Apply the route-bound action through the shared command service.

        Parameters
        ----------
        request : Request
            Authenticated API request with strict version and rationale.
        organization_id : UUID
            Exact organization identifier from the route.
        edition_id : UUID
            Exact edition identifier from the route.
        demand_id : UUID
            Exact Shift demand identifier from the route.

        Returns
        -------
        Response
            Minimized demand-transition command result.

        Raises
        ------
        NotFound
            If the mounted action code is unsupported.
        """
        scope = _organizer_scope(
            request=request,
            organization_id=organization_id,
            edition_id=edition_id,
            manage=True,
        )
        retry_key = _idempotency_key(request)
        serializer_class = (
            ShiftLockCommandSerializer
            if self.action == "lock"
            else ShiftReasonCommandSerializer
        )
        data = _payload(request, serializer_class=serializer_class)
        command = _DEMAND_ACTION_COMMANDS.get(self.action)
        if command is None:
            raise NotFound("The Shift action is unavailable.")
        kwargs: dict[str, object] = {
            "actor": scope.account,
            "organization_id": organization_id,
            "series_id": scope.edition.series_id,
            "edition_id": edition_id,
            "demand_id": demand_id,
            "expected_version": cast("int", data["expected_version"]),
            "reason": str(data["reason"]),
            "retry_key": retry_key,
            "correlation_id": UUID(request.correlation_id),  # type: ignore[attr-defined]
            "request_id": UUID(request.correlation_id),  # type: ignore[attr-defined]
            "source_channel": "api",
        }
        if self.action == "lock":
            kwargs["allow_understaffed"] = cast("bool", data["allow_understaffed"])
        try:
            result = command(**kwargs)
        except Exception as error:  # noqa: BLE001
            _raise_command_error(error)
        return Response(
            ShiftMutationResultSerializer(_demand_result_payload(result)).data
        )


@method_decorator(never_cache, name="dispatch")
class WorkforceShiftCommitmentActionView(APIView):
    """Confirm or remove one active commitment as an organizer."""

    action = ""

    @extend_schema(
        request=ShiftReasonCommandSerializer,
        responses={200: ShiftMutationResultSerializer},
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        commitment_id: UUID,
    ) -> Response:
        """Apply the route-bound commitment action.

        Parameters
        ----------
        request : Request
            Authenticated API request with strict version and rationale.
        organization_id : UUID
            Exact organization identifier from the route.
        edition_id : UUID
            Exact edition identifier from the route.
        commitment_id : UUID
            Exact Shift commitment identifier from the route.

        Returns
        -------
        Response
            Minimized commitment-transition command result.

        Raises
        ------
        NotFound
            If the mounted action code is unsupported.
        """
        scope = _organizer_scope(
            request=request,
            organization_id=organization_id,
            edition_id=edition_id,
            manage=True,
        )
        retry_key = _idempotency_key(request)
        data = _payload(request, serializer_class=ShiftReasonCommandSerializer)
        command = {
            "confirm": confirm_shift_commitment,
            "remove": remove_shift_commitment,
        }.get(self.action)
        if command is None:
            raise NotFound("The coverage action is unavailable.")
        try:
            result = command(
                actor=scope.account,
                organization_id=organization_id,
                series_id=scope.edition.series_id,
                edition_id=edition_id,
                commitment_id=commitment_id,
                expected_version=cast("int", data["expected_version"]),
                reason=str(data["reason"]),
                retry_key=retry_key,
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
                request_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
                source_channel="api",
            )
        except Exception as error:  # noqa: BLE001
            _raise_command_error(error)
        return Response(
            ShiftMutationResultSerializer(_commitment_result_payload(result)).data
        )


@method_decorator(never_cache, name="dispatch")
class WorkforceMyShiftsView(APIView):
    """Return suitable work and retained commitments for the current person."""

    @extend_schema(
        operation_id="workforce_retrieve_my_shifts",
        responses={200: MyShiftOverviewSerializer},
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        """Return the person-owned Shift projection without other people.

        Parameters
        ----------
        request : Request
            Authenticated personal API request.
        organization_id : UUID
            Exact related organization identifier from the route.
        edition_id : UUID
            Exact related edition identifier from the route.

        Returns
        -------
        Response
            Suitable open work and the person's retained commitments.

        Raises
        ------
        WorkforceShiftDependencyUnavailable
            If the complete personal projection cannot be produced.
        """
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        try:
            with repeatable_read_only_snapshot():
                scope = _personal_scope(
                    request=request,
                    organization_id=organization_id,
                    edition_id=edition_id,
                    manage=False,
                )
                payload = _personal_payload(scope=scope)
            _personal_scope(
                request=request,
                organization_id=organization_id,
                edition_id=edition_id,
                manage=False,
            )
        except (DatabaseError, RuntimeError, ShiftReadLimitExceededError) as error:
            raise WorkforceShiftDependencyUnavailable from error
        return Response(MyShiftOverviewSerializer(payload).data)


@method_decorator(never_cache, name="dispatch")
class WorkforceMyShiftClaimView(APIView):
    """Claim suitable work as the current person."""

    @extend_schema(
        operation_id="workforce_claim_shift",
        request=ShiftClaimCommandSerializer,
        responses={200: ShiftMutationResultSerializer},
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        demand_id: UUID,
    ) -> Response:
        """Claim one open Shift after strict self authorization.

        Parameters
        ----------
        request : Request
            Authenticated personal API request with a closed command object.
        organization_id : UUID
            Exact related organization identifier from the route.
        edition_id : UUID
            Exact related edition identifier from the route.
        demand_id : UUID
            Suitable open Shift demand identifier.

        Returns
        -------
        Response
            Minimized created-claim command result.
        """
        scope = _personal_scope(
            request=request,
            organization_id=organization_id,
            edition_id=edition_id,
            manage=True,
        )
        retry_key = _idempotency_key(request)
        data = _payload(request, serializer_class=ShiftClaimCommandSerializer)
        try:
            result = claim_shift(
                actor=scope.account,
                organization_id=organization_id,
                edition_id=edition_id,
                demand_id=demand_id,
                expected_version=cast("int", data["expected_version"]),
                retry_key=retry_key,
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
                request_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
                source_channel="api",
            )
        except Exception as error:  # noqa: BLE001
            _raise_command_error(error)
        return Response(
            ShiftMutationResultSerializer(_commitment_result_payload(result)).data
        )


@method_decorator(never_cache, name="dispatch")
class WorkforceMyShiftWithdrawView(APIView):
    """Withdraw one owned active commitment without collecting rationale."""

    @extend_schema(
        operation_id="workforce_withdraw_shift_claim",
        request=ShiftWithdrawCommandSerializer,
        responses={200: ShiftMutationResultSerializer},
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        commitment_id: UUID,
    ) -> Response:
        """Withdraw one current person's claim or confirmation.

        Parameters
        ----------
        request : Request
            Authenticated personal API request with explicit confirmation.
        organization_id : UUID
            Exact related organization identifier from the route.
        edition_id : UUID
            Exact related edition identifier from the route.
        commitment_id : UUID
            Person-owned active commitment identifier.

        Returns
        -------
        Response
            Minimized removed-commitment command result.
        """
        scope = _personal_scope(
            request=request,
            organization_id=organization_id,
            edition_id=edition_id,
            manage=True,
        )
        retry_key = _idempotency_key(request)
        data = _payload(request, serializer_class=ShiftWithdrawCommandSerializer)
        try:
            result = withdraw_shift_claim(
                actor=scope.account,
                organization_id=organization_id,
                edition_id=edition_id,
                commitment_id=commitment_id,
                expected_version=cast("int", data["expected_version"]),
                retry_key=retry_key,
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
                request_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
                source_channel="api",
            )
        except Exception as error:  # noqa: BLE001
            _raise_command_error(error)
        return Response(
            ShiftMutationResultSerializer(_commitment_result_payload(result)).data
        )
