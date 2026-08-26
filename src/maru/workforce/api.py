"""Policy-scoped workforce management and self-service API boundaries."""

import logging
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Never, cast
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.utils.timezone import now as timezone_now
from django.views.decorators.cache import never_cache
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import APIException, NotFound, PermissionDenied
from rest_framework.exceptions import ValidationError as ApiValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
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
from maru.core.problems import DependencyUnavailable
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.identity.services import require_recent_step_up
from maru.organizations.queries import (
    OrganizationGovernanceAnchor,
    organization_governance_anchor,
)
from maru.workforce.assignment_commands import (
    AssignmentAuthorizationDeniedError,
    AssignmentCandidateUnavailableError,
    AssignmentCommandError,
    AssignmentCommandResult,
    AssignmentHeadcountConflictError,
    AssignmentLifecycleConflictError,
    AssignmentReadinessConflictError,
    AssignmentRetryConflictError,
    AssignmentStateConflictError,
    AssignmentUnavailableError,
    AssignmentVersionConflictError,
    approve_position_assignment,
    end_position_assignment,
    propose_position_assignment,
    reject_position_assignment,
)
from maru.workforce.availability_audit import append_availability_read_audit
from maru.workforce.availability_commands import (
    AvailabilityAuthorizationDeniedError,
    AvailabilityCommandError,
    AvailabilityCommandResult,
    AvailabilityLifecycleConflictError,
    AvailabilityRelationshipRequiredError,
    AvailabilityRetryConflictError,
    AvailabilityStateConflictError,
    AvailabilityVersionConflictError,
    authorize_person_availability_command,
    save_person_availability,
    withdraw_person_availability,
)
from maru.workforce.availability_queries import (
    AVAILABILITY_ORGANIZER_REQUIRED_FIELDS,
    AvailabilityProjectionIntegrityError,
    AvailabilityReadLimitExceededError,
    AvailabilityWindowProjection,
    load_organizer_availability_overview,
    load_person_availability,
    person_can_edit_availability,
    person_has_availability_relationship,
)
from maru.workforce.models import (
    OnboardingDocumentRequest,
    VolunteerOpportunity,
)
from maru.workforce.queries import (
    WORKFORCE_STRUCTURE_REQUIRED_FIELDS,
    EditionStructureProjection,
    project_edition_structure,
)
from maru.workforce.serializers import (
    OnboardingDocumentRequestSerializer,
    OnboardingDocumentUploadSerializer,
    VolunteerApplicationSerializer,
    VolunteerApplicationSubmitSerializer,
    VolunteerOpportunitySerializer,
    WorkforceAssignmentDecisionSerializer,
    WorkforceAssignmentMutationResultSerializer,
    WorkforceAssignmentProposalSerializer,
    WorkforceAvailabilityMutationResultSerializer,
    WorkforceAvailabilityReplaceSerializer,
    WorkforceAvailabilityWithdrawSerializer,
    WorkforceDepartmentCreateSerializer,
    WorkforceDepartmentDeleteSerializer,
    WorkforceDepartmentMutationResultSerializer,
    WorkforceDepartmentRetireSerializer,
    WorkforceDepartmentUpdateSerializer,
    WorkforceMyAvailabilitySerializer,
    WorkforceOrganizerAvailabilitySerializer,
    WorkforcePositionCloseSerializer,
    WorkforcePositionCreateSerializer,
    WorkforcePositionMutationResultSerializer,
    WorkforcePositionOpportunityUpdateSerializer,
    WorkforcePositionUpdateSerializer,
    WorkforceProblemSerializer,
    WorkforceStructureSerializer,
    WorkforceStructureTemplateApplySerializer,
    WorkforceStructureTemplateMutationResultSerializer,
)
from maru.workforce.services import (
    submit_volunteer_application,
    upload_onboarding_document,
)
from maru.workforce.shift_queries import SHIFT_ORGANIZER_REQUIRED_FIELDS
from maru.workforce.structure_audit import append_structure_read_audit
from maru.workforce.structure_commands import (
    BuiltinStructureTemplateResult,
    DepartmentStructureResult,
    PositionStructureResult,
    StructureAuthorizationDeniedError,
    StructureCommandError,
    StructureDepartmentUnavailableError,
    StructureDependencyConflictError,
    StructureLifecycleConflictError,
    StructureLimitConflictError,
    StructurePositionUnavailableError,
    StructureRetryConflictError,
    StructureStateConflictError,
    StructureVersionConflictError,
    apply_builtin_structure_template,
    close_position,
    create_department,
    create_position,
    delete_unused_department,
    retire_department,
    update_department,
    update_position,
    update_position_opportunity,
)
from maru.workforce.structure_inputs import CANONICAL_UUID_PATTERN
from maru.workforce.structure_snapshot import (
    StructureSnapshotRead,
    load_version_fenced_snapshot,
    repeatable_read_only_snapshot,
)

if TYPE_CHECKING:
    from django.core.files.uploadedfile import UploadedFile

logger = logging.getLogger(__name__)
PROBLEM_CONTENT_TYPE = "application/problem+json"
IDEMPOTENCY_HEADER_NAME = "Idempotency-Key"
MAX_IDEMPOTENCY_HEADER_LENGTH = 64
_STRUCTURE_MUTATION_UNAVAILABLE_DETAIL = "The requested structure is unavailable."


def _problem_response(description: str) -> OpenApiResponse:
    return OpenApiResponse(
        response=WorkforceProblemSerializer,
        description=description,
    )


def _account(request: Request) -> Account:
    if not isinstance(request.user, Account):
        raise PermissionDenied("Sign in to use workforce self-service.")
    return request.user


def _raise_dependency_unavailable(message: str, error: Exception) -> Never:
    logger.exception(message)
    raise DependencyUnavailable from error


class WorkforceStructureConflict(APIException):
    """Name-free RFC 9457 boundary for current-state command conflicts."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "The structure change conflicts with current state."
    default_code = "structure_conflict"

    def __init__(
        self,
        *,
        code: str,
        errors: Mapping[str, list[str]],
    ) -> None:
        """Initialize the WorkforceStructureConflict instance.

        Parameters
        ----------
        code : str
            The stable domain code to resolve or validate.
        errors : Mapping[str, list[str]]
            The errors resolved from the authorized request.
        """
        super().__init__(
            detail=cast(
                "Any",
                {
                    "detail": self.default_detail,
                    "code": code,
                    "errors": dict(errors),
                },
            ),
            code=code,
        )


class WorkforceAssignmentConflict(APIException):
    """Name-free RFC 9457 boundary for assignment command conflicts."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "The assignment action conflicts with current state."
    default_code = "assignment_conflict"

    def __init__(
        self,
        *,
        code: str,
        errors: Mapping[str, list[str]],
    ) -> None:
        """Initialize one stable assignment conflict response.

        Parameters
        ----------
        code : str
            Stable assignment conflict code.
        errors : Mapping[str, list[str]]
            Minimized field-safe errors for the authorized request.
        """
        super().__init__(
            detail=cast(
                "Any",
                {
                    "detail": self.default_detail,
                    "code": code,
                    "errors": dict(errors),
                },
            ),
            code=code,
        )


_STRUCTURE_CONFLICT_ERRORS: dict[
    type[StructureCommandError],
    tuple[str, dict[str, list[str]]],
] = {
    StructureVersionConflictError: (
        StructureVersionConflictError.reason_code,
        {"expected_version": ["Reload the structure and try the change again."]},
    ),
    StructureRetryConflictError: (
        StructureRetryConflictError.reason_code,
        {
            IDEMPOTENCY_HEADER_NAME: [
                "Use a new Idempotency-Key for a different request."
            ]
        },
    ),
    StructureLifecycleConflictError: (
        StructureLifecycleConflictError.reason_code,
        {"non_field_errors": ["This structure is currently read-only."]},
    ),
    StructureStateConflictError: (
        StructureStateConflictError.reason_code,
        {"non_field_errors": ["Reload the complete structure before retrying."]},
    ),
    StructureDependencyConflictError: (
        StructureDependencyConflictError.reason_code,
        {"non_field_errors": ["Retained dependencies protect this record."]},
    ),
    StructureLimitConflictError: (
        StructureLimitConflictError.reason_code,
        {"non_field_errors": ["The bounded structure limit has been reached."]},
    ),
}


def _raise_structure_mutation_unavailable() -> Never:
    raise PermissionDenied(
        _STRUCTURE_MUTATION_UNAVAILABLE_DETAIL,
        code=StructureAuthorizationDeniedError.reason_code,
    )


def _raise_structure_department_unavailable() -> Never:
    raise NotFound(
        _STRUCTURE_MUTATION_UNAVAILABLE_DETAIL,
        code=StructureDepartmentUnavailableError.reason_code,
    )


def _raise_structure_position_unavailable() -> Never:
    raise NotFound(
        _STRUCTURE_MUTATION_UNAVAILABLE_DETAIL,
        code=StructurePositionUnavailableError.reason_code,
    )


@dataclass(frozen=True, slots=True)
class _StructureMutationScope:
    account: Account
    series_id: UUID


def _authorize_structure_mutation(
    *,
    request: Request,
    organization_id: UUID,
    edition_id: UUID,
) -> _StructureMutationScope:
    """Require exact view and manage authority before parsing header or body.

    Parameters
    ----------
    request : Request
        The incoming HTTP request and authenticated principal context.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.

    Returns
    -------
    _StructureMutationScope
        The resolved _StructureMutationScope for authorize structure mutation.
    """
    account = request.user
    if not isinstance(account, Account) or not account.is_active:
        _raise_structure_mutation_unavailable()
    try:
        target = resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        if target is None:
            _raise_structure_mutation_unavailable()
        evaluated_at = timezone_now()
        view = decide(
            principal=account,
            capability_code="workforce.view_structure",
            resource=target,
            at=evaluated_at,
        )
        manage = decide(
            principal=account,
            capability_code="workforce.manage_structure",
            resource=target,
            at=evaluated_at,
        )
        if not view.allowed or not manage.allowed:
            _raise_structure_mutation_unavailable()
        edition = (
            EventEdition.objects.only("series_id")
            .filter(
                id=edition_id,
                organization_id=organization_id,
                series__organization_id=organization_id,
            )
            .first()
        )
        if edition is None:
            _raise_structure_mutation_unavailable()
    except (DatabaseError, RuntimeError) as error:
        _raise_dependency_unavailable(
            "Unable to authorize a workforce structure mutation",
            error,
        )
    return _StructureMutationScope(account=account, series_id=edition.series_id)


def _raise_idempotency_header_error(*, detail: str, code: str) -> Never:
    raise ApiValidationError(
        cast(
            "Any",
            {
                "detail": detail,
                "code": code,
                "errors": {IDEMPOTENCY_HEADER_NAME: [detail]},
            },
        ),
        code=code,
    )


def _structure_idempotency_key(request: Request) -> UUID:
    """Parse exactly one canonical lower-case, hyphenated UUID header.

    Parameters
    ----------
    request : Request
        The incoming HTTP request and authenticated principal context.

    Returns
    -------
    UUID
        The resolved UUID for structure idempotency key.
    """
    raw_value = request.headers.get(IDEMPOTENCY_HEADER_NAME)
    if raw_value is None or not raw_value.strip():
        _raise_idempotency_header_error(
            detail="The Idempotency-Key header is required.",
            code="missing_idempotency_key",
        )
    if len(raw_value) > MAX_IDEMPOTENCY_HEADER_LENGTH:
        _raise_idempotency_header_error(
            detail="The Idempotency-Key header must contain one canonical UUID.",
            code="invalid_idempotency_key",
        )
    canonical_candidate = raw_value.strip()
    try:
        value = UUID(canonical_candidate)
    except (AttributeError, ValueError):
        _raise_idempotency_header_error(
            detail="The Idempotency-Key header must contain one canonical UUID.",
            code="invalid_idempotency_key",
        )
    if str(value) != canonical_candidate:
        _raise_idempotency_header_error(
            detail="The Idempotency-Key header must contain one canonical UUID.",
            code="invalid_idempotency_key",
        )
    return value


def _validated_structure_payload(
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


_SAFE_STRUCTURE_VALIDATION_FIELDS = frozenset(
    {
        "template",
        "expected_version",
        "confirmation_name",
        "name",
        "description",
        "parent_department_id",
        "display_order",
        "template_id",
        "department_id",
        "reports_to_id",
        "title",
        "headcount",
        "status",
        "headline",
        "applications_open_at",
        "applications_close_at",
        "visible_when_filled",
        "reason",
    }
)


def _django_structure_validation_code(error: DjangoValidationError) -> str:
    if hasattr(error, "error_dict"):
        for field_name, field_errors in error.error_dict.items():
            if field_name in _SAFE_STRUCTURE_VALIDATION_FIELDS and field_errors:
                return str(field_errors[0].code or "structure_input_invalid")
    if hasattr(error, "error_list") and error.error_list:
        return str(error.error_list[0].code or "structure_input_invalid")
    return "structure_input_invalid"


def _django_structure_validation_errors(
    error: DjangoValidationError,
) -> dict[str, list[str]]:
    if hasattr(error, "message_dict"):
        safe_errors = {
            field_name: messages
            for field_name, messages in error.message_dict.items()
            if field_name in _SAFE_STRUCTURE_VALIDATION_FIELDS
        }
        if safe_errors:
            return safe_errors
    return {"non_field_errors": ["The structure input is invalid."]}


def _is_safe_structure_input_validation(error: DjangoValidationError) -> bool:
    """Return whether every reported error belongs to submitted organizer input.

    Parameters
    ----------
    error : DjangoValidationError
        The error resolved from the authorized request.

    Returns
    -------
    bool
        `True` when every reported error belongs to submitted organizer input;
        otherwise `False`.
    """
    if not hasattr(error, "error_dict"):
        return False
    field_names = frozenset(error.error_dict)
    return bool(field_names) and field_names.issubset(_SAFE_STRUCTURE_VALIDATION_FIELDS)


def _execute_structure_command[
    CommandResult: (
        BuiltinStructureTemplateResult,
        DepartmentStructureResult,
        PositionStructureResult,
    )
](
    command: Callable[[], CommandResult],
) -> CommandResult:
    try:
        return command()
    except StructureAuthorizationDeniedError:
        _raise_structure_mutation_unavailable()
    except StructureDepartmentUnavailableError:
        _raise_structure_department_unavailable()
    except StructurePositionUnavailableError:
        _raise_structure_position_unavailable()
    except DjangoValidationError as error:
        if not _is_safe_structure_input_validation(error):
            _raise_dependency_unavailable(
                "A workforce structure command rejected server-owned input",
                error,
            )
        code = _django_structure_validation_code(error)
        raise ApiValidationError(
            cast(
                "Any",
                {
                    "detail": "The structure input is invalid.",
                    "code": code,
                    "errors": _django_structure_validation_errors(error),
                },
            ),
            code=code,
        ) from error
    except tuple(_STRUCTURE_CONFLICT_ERRORS) as error:
        code, errors = _STRUCTURE_CONFLICT_ERRORS[type(error)]
        raise WorkforceStructureConflict(code=code, errors=errors) from error
    except (DatabaseError, StructureCommandError, RuntimeError) as error:
        _raise_dependency_unavailable(
            "Unable to apply a workforce structure command",
            error,
        )


@dataclass(frozen=True, slots=True)
class _AssignmentMutationScope:
    """Minimized exact-edition authority proof for an assignment adapter."""

    account: Account
    series_id: UUID


def _raise_assignment_mutation_unavailable() -> Never:
    raise PermissionDenied(
        "The assignment route is unavailable.",
        code=AssignmentAuthorizationDeniedError.reason_code,
    )


def _authorize_assignment_mutation(
    *,
    request: Request,
    organization_id: UUID,
    edition_id: UUID,
    authority_capability: str,
) -> _AssignmentMutationScope:
    """Authorize assignment scope before parsing retry header or body.

    Parameters
    ----------
    request : Request
        Incoming API request with the authenticated principal.
    organization_id : UUID
        Untrusted organization route identifier.
    edition_id : UUID
        Untrusted edition route identifier.
    authority_capability : str
        Additional role-management or revocation capability required.

    Returns
    -------
    _AssignmentMutationScope
        Authorized account and persisted series identifier without labels.
    """
    account = request.user
    if not isinstance(account, Account) or not account.is_active:
        _raise_assignment_mutation_unavailable()
    try:
        target = resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        if target is None:
            _raise_assignment_mutation_unavailable()
        evaluated_at = timezone_now()
        decisions = tuple(
            decide(
                principal=account,
                capability_code=capability_code,
                resource=target,
                at=evaluated_at,
            )
            for capability_code in (
                "workforce.view_structure",
                "workforce.manage_assignments",
                authority_capability,
            )
        )
        if any(not decision.allowed for decision in decisions):
            _raise_assignment_mutation_unavailable()
        edition = (
            EventEdition.objects.only("series_id")
            .filter(
                id=edition_id,
                organization_id=organization_id,
                series__organization_id=organization_id,
            )
            .first()
        )
        if edition is None:
            _raise_assignment_mutation_unavailable()
    except (DatabaseError, RuntimeError) as error:
        _raise_dependency_unavailable(
            "Unable to authorize a Workforce assignment mutation",
            error,
        )
    return _AssignmentMutationScope(account=account, series_id=edition.series_id)


def _require_assignment_api_step_up(*, request: Request, account: Account) -> None:
    """Require a recent session check before reading a decision request body.

    Parameters
    ----------
    request : Request
        Incoming API request whose session proves recent authentication.
    account : Account
        Active assignment controller derived from the request.

    Raises
    ------
    PermissionDenied
        If the session has no sufficiently recent step-up evidence.
    """
    try:
        require_recent_step_up(account=account, request=request._request)  # noqa: SLF001
    except DjangoValidationError as error:
        raise PermissionDenied(
            "Complete an extra sign-in check before this assignment action.",
            code=error.code or "step_up_required",
        ) from error


_ASSIGNMENT_CONFLICT_ERRORS: dict[
    type[AssignmentCommandError],
    tuple[str, dict[str, list[str]]],
] = {
    AssignmentVersionConflictError: (
        AssignmentVersionConflictError.reason_code,
        {"expected_version": ["Reload the assignment and try again."]},
    ),
    AssignmentRetryConflictError: (
        AssignmentRetryConflictError.reason_code,
        {IDEMPOTENCY_HEADER_NAME: ["Use a new key for a different request."]},
    ),
    AssignmentLifecycleConflictError: (
        AssignmentLifecycleConflictError.reason_code,
        {"non_field_errors": ["This assignment action is currently read-only."]},
    ),
    AssignmentStateConflictError: (
        AssignmentStateConflictError.reason_code,
        {"non_field_errors": ["Reload the assignment before retrying."]},
    ),
    AssignmentReadinessConflictError: (
        AssignmentReadinessConflictError.reason_code,
        {"non_field_errors": ["Required onboarding is not fully approved."]},
    ),
    AssignmentHeadcountConflictError: (
        AssignmentHeadcountConflictError.reason_code,
        {"non_field_errors": ["The Position's approved headcount is reserved."]},
    ),
}


def _django_assignment_validation_code(error: DjangoValidationError) -> str:
    """Return the first stable code from already-vetted assignment input.

    Parameters
    ----------
    error : DjangoValidationError
        Validation failure raised by the shared command boundary.

    Returns
    -------
    str
        First stable validation code or the generic assignment input code.
    """
    if hasattr(error, "error_dict"):
        for field_errors in error.error_dict.values():
            if field_errors:
                return str(field_errors[0].code or "assignment_input_invalid")
    if hasattr(error, "error_list") and error.error_list:
        return str(error.error_list[0].code or "assignment_input_invalid")
    return "assignment_input_invalid"


def _execute_assignment_command(
    command: Callable[[], AssignmentCommandResult],
) -> AssignmentCommandResult:
    try:
        return command()
    except AssignmentAuthorizationDeniedError as error:
        raise PermissionDenied(
            "The assignment route is unavailable.",
            code=error.reason_code,
        ) from error
    except (
        AssignmentUnavailableError,
        AssignmentCandidateUnavailableError,
    ) as error:
        raise NotFound(
            "The assignment target is unavailable.",
            code=error.reason_code,
        ) from error
    except DjangoValidationError as error:
        safe_fields = frozenset(
            {
                "account_id",
                "effective_from",
                "expires_at",
                "expected_version",
                "reason",
                "retry_key",
            }
        )
        if not hasattr(error, "error_dict") or not set(error.error_dict).issubset(
            safe_fields
        ):
            _raise_dependency_unavailable(
                "A Workforce assignment command rejected server-owned input",
                error,
            )
        code = _django_assignment_validation_code(error)
        errors = {
            field_name: messages
            for field_name, messages in error.message_dict.items()
            if field_name in safe_fields
        }
        raise ApiValidationError(
            cast(
                "Any",
                {
                    "detail": "The assignment input is invalid.",
                    "code": code,
                    "errors": errors,
                },
            ),
            code=code,
        ) from error
    except tuple(_ASSIGNMENT_CONFLICT_ERRORS) as error:
        code, errors = _ASSIGNMENT_CONFLICT_ERRORS[type(error)]
        raise WorkforceAssignmentConflict(code=code, errors=errors) from error
    except (DatabaseError, AssignmentCommandError, RuntimeError) as error:
        _raise_dependency_unavailable(
            "Unable to apply a Workforce assignment command",
            error,
        )


def _assignment_mutation_response(
    result: AssignmentCommandResult,
    *,
    created: bool = False,
) -> Response:
    payload = {
        "assignment_id": result.assignment_id,
        "assignment_version": result.resulting_version,
        "status": result.status,
    }
    response_status = (
        status.HTTP_201_CREATED
        if created and not result.replayed
        else status.HTTP_200_OK
    )
    return Response(
        WorkforceAssignmentMutationResultSerializer(payload).data,
        status=response_status,
    )


_STRUCTURE_IDEMPOTENCY_PARAMETER = OpenApiParameter(
    name=IDEMPOTENCY_HEADER_NAME,
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.HEADER,
    required=True,
    pattern=CANONICAL_UUID_PATTERN,
    description=(
        "A canonical lower-case hyphenated UUID. Repeating the same request with "
        "the same key returns HTTP 200 and the original minimized result."
    ),
)


class _WorkforceStructureMutationAutoSchema(AutoSchema):
    """Keep runtime uniform denials without advertising anonymous mutation access."""

    def get_auth(self) -> list[dict[str, Any]]:
        return [requirement for requirement in super().get_auth() if requirement]


class _WorkforceStructureAutoSchema(_WorkforceStructureMutationAutoSchema):
    """Document the required JSON body on the contract's DELETE command.

    drf-spectacular intentionally omits DELETE bodies in its default schema
    builder. OpenAPI 3.1 permits this request body and protected Department
    deletion requires exact-name confirmation, so the affected view registers its
    closed serializer
    explicitly while every other method retains the library implementation.
    """

    def _get_request_body(self, direction: str = "request") -> dict[str, Any] | None:
        if self.method != "DELETE":
            return cast(
                "dict[str, Any] | None",
                super()._get_request_body(direction),  # type: ignore[no-untyped-call]
            )
        schema, required = self._get_request_for_media_type(  # type: ignore[no-untyped-call]
            WorkforceDepartmentDeleteSerializer(),
            direction,
        )
        if schema is None:
            return None
        request_body: dict[str, Any] = {
            "content": {"application/json": {"schema": schema}}
        }
        if required:
            request_body["required"] = True
        return request_body


def _authorize_structure(
    *,
    account: Account,
    organization_id: UUID,
    edition_id: UUID,
    at: datetime,
) -> PolicyDecision:
    decision = decide(
        principal=account,
        capability_code="workforce.view_structure",
        resource=resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
        requested_fields=WORKFORCE_STRUCTURE_REQUIRED_FIELDS,
        at=at,
    )
    if not decision.allowed:
        raise PermissionDenied(
            "This account cannot view the organization structure.",
            code=decision.reason_code,
        )
    try:
        require_complete_projection(
            required_fields=WORKFORCE_STRUCTURE_REQUIRED_FIELDS,
            permitted_fields=decision.fields,
        )
    except FieldProjectionDeniedError as error:
        raise PermissionDenied(
            "The permitted organization-structure projection is incomplete.",
            code="field_projection_denied",
        ) from error
    return decision


@dataclass(frozen=True, slots=True)
class _WorkforceStructureSnapshot:
    organization_name: str
    series_name: str
    edition_name: str
    governance: OrganizationGovernanceAnchor
    structure: EditionStructureProjection


def _load_workforce_structure_snapshot(
    *,
    account: Account,
    organization_id: UUID,
    edition_id: UUID,
) -> StructureSnapshotRead[_WorkforceStructureSnapshot]:
    """Read the complete authorized composition in the caller's snapshot.

    Parameters
    ----------
    account : Account
        The platform account whose state or access is being evaluated.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.

    Returns
    -------
    StructureSnapshotRead[_WorkforceStructureSnapshot]
        The StructureSnapshotRead[_WorkforceStructureSnapshot] produced by load
        workforce structure snapshot.
    """
    projection_at = timezone_now()
    _authorize_structure(
        account=account,
        organization_id=organization_id,
        edition_id=edition_id,
        at=projection_at,
    )
    edition = (
        EventEdition.objects.select_related("organization", "series")
        .only(
            "id",
            "name",
            "organization_id",
            "organization__name",
            "series_id",
            "series__name",
            "series__organization_id",
        )
        .get(
            id=edition_id,
            organization_id=organization_id,
            series__organization_id=organization_id,
        )
    )
    governance = organization_governance_anchor(
        organization_id=organization_id,
    )
    structure = project_edition_structure(
        organization_id=organization_id,
        edition_id=edition_id,
        at=projection_at,
    )
    return StructureSnapshotRead(
        value=_WorkforceStructureSnapshot(
            organization_name=edition.organization.name,
            series_name=edition.series.name,
            edition_name=edition.name,
            governance=governance,
            structure=structure,
        ),
        organization_id=edition.organization_id,
        edition_id=edition.id,
        aggregate_version=structure.aggregate_version,
    )


@method_decorator(never_cache, name="dispatch")
class WorkforceStructureView(APIView):
    """Return the current, human-readable edition organization hierarchy."""

    @extend_schema(
        operation_id="workforce_retrieve_structure",
        responses={
            200: WorkforceStructureSerializer,
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The structure query contains unsupported input."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "The caller cannot view this edition's organization structure."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "The complete structure projection is temporarily unavailable."
            ),
        },
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        """Retrieve the structure.

        Return the current, human-readable edition organization hierarchy.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.
        edition_id : UUID
            The event edition identifier that scopes the operation.

        Returns
        -------
        Response
            The HTTP response for the requested operation.

        Raises
        ------
        PermissionDenied
            If the caller lacks permission for the requested scope.
        """
        account = _account(request)
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        try:
            snapshot = load_version_fenced_snapshot(
                load=lambda: _load_workforce_structure_snapshot(
                    account=account,
                    organization_id=organization_id,
                    edition_id=edition_id,
                ),
            )
            # The snapshot is internally coherent. A fresh final decision
            # additionally prevents authority that expired or was revoked
            # during either read attempt from releasing its names or labels.
            response_authorized_at = timezone_now()
            final_decision = _authorize_structure(
                account=account,
                organization_id=organization_id,
                edition_id=edition_id,
                at=response_authorized_at,
            )
            manage_positions = decide(
                principal=account,
                capability_code="workforce.manage_structure",
                resource=resolve_edition_target(
                    organization_id=organization_id,
                    edition_id=edition_id,
                ),
                at=response_authorized_at,
            ).allowed
            assignment_target = resolve_edition_target(
                organization_id=organization_id,
                edition_id=edition_id,
            )
            manage_assignments = (
                decide(
                    principal=account,
                    capability_code="workforce.manage_assignments",
                    resource=assignment_target,
                    at=response_authorized_at,
                ).allowed
                and decide(
                    principal=account,
                    capability_code="authorization.manage_roles",
                    resource=assignment_target,
                    at=response_authorized_at,
                ).allowed
            )
            view_availability = decide(
                principal=account,
                capability_code="workforce.view_availability",
                resource=assignment_target,
                requested_fields=AVAILABILITY_ORGANIZER_REQUIRED_FIELDS,
                at=response_authorized_at,
            )
            can_view_availability = bool(
                view_availability.allowed
                and view_availability.fields == AVAILABILITY_ORGANIZER_REQUIRED_FIELDS
            )
            view_shifts = decide(
                principal=account,
                capability_code="workforce.view_shifts",
                resource=assignment_target,
                requested_fields=SHIFT_ORGANIZER_REQUIRED_FIELDS,
                at=response_authorized_at,
            )
            can_view_shifts = bool(
                view_shifts.allowed
                and view_shifts.fields == SHIFT_ORGANIZER_REQUIRED_FIELDS
            )
            can_manage_shifts = bool(
                can_view_shifts
                and decide(
                    principal=account,
                    capability_code="workforce.manage_shifts",
                    resource=assignment_target,
                    at=response_authorized_at,
                ).allowed
            )
            http_method = cast("str", request.method)
            append_structure_read_audit(
                actor=account,
                organization_id=organization_id,
                edition_id=edition_id,
                decision=final_decision,
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
                route_name="workforce-structure",
                http_method=http_method,
                source_channel="api",
                occurred_at=response_authorized_at,
            )
        except EventEdition.DoesNotExist as error:
            raise PermissionDenied(
                "This account cannot view the organization structure.",
                code="target_unavailable",
            ) from error
        except (DatabaseError, DjangoValidationError, RuntimeError) as error:
            _raise_dependency_unavailable(
                "Unable to project the workforce structure",
                error,
            )

        payload: dict[str, object] = {
            "organization_name": snapshot.organization_name,
            "series_name": snapshot.series_name,
            "edition_name": snapshot.edition_name,
            "can_manage_positions": manage_positions,
            "can_manage_assignments": manage_assignments,
            "can_view_availability": can_view_availability,
            "can_view_shifts": can_view_shifts,
            "can_manage_shifts": can_manage_shifts,
            "governance": asdict(snapshot.governance),
            "structure": asdict(snapshot.structure),
        }
        return Response(WorkforceStructureSerializer(payload).data)


@method_decorator(never_cache, name="dispatch")
class _WorkforceStructureMutationView(APIView):
    """Reach explicit uniform denials while retaining authenticated CSRF checks."""

    permission_classes = (AllowAny,)
    schema = _WorkforceStructureMutationAutoSchema()


class WorkforceStructureTemplateApplicationView(_WorkforceStructureMutationView):
    """Expose workforce structure template application through the HTTP API."""

    @extend_schema(
        operation_id="workforce_apply_structure_template",
        parameters=[_STRUCTURE_IDEMPOTENCY_PARAMETER],
        request=WorkforceStructureTemplateApplySerializer,
        responses={
            200: OpenApiResponse(
                response=WorkforceStructureTemplateMutationResultSerializer,
                description="The identical request was replayed.",
            ),
            201: OpenApiResponse(
                response=WorkforceStructureTemplateMutationResultSerializer,
                description="The built-in structure copy was created.",
            ),
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The closed request or Idempotency-Key is invalid."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "The mutation route or required authority is unavailable."
            ),
            (409, PROBLEM_CONTENT_TYPE): _problem_response(
                "The request conflicts with structure state or prior retry evidence."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "A canonical command dependency is temporarily unavailable."
            ),
        },
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        """Apply the structure template.

        Reach explicit uniform denials while retaining authenticated CSRF checks.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.
        edition_id : UUID
            The event edition identifier that scopes the operation.

        Returns
        -------
        Response
            The HTTP response for the requested operation.
        """
        scope = _authorize_structure_mutation(
            request=request,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        retry_key = _structure_idempotency_key(request)
        values = _validated_structure_payload(
            request,
            serializer_class=WorkforceStructureTemplateApplySerializer,
        )
        correlation_id = UUID(request.correlation_id)  # type: ignore[attr-defined]
        result = _execute_structure_command(
            lambda: apply_builtin_structure_template(
                actor=scope.account,
                organization_id=organization_id,
                series_id=scope.series_id,
                edition_id=edition_id,
                template_identifier=cast("str", values["template"]),
                expected_version=cast("int", values["expected_version"]),
                confirmation_name=cast("str", values["confirmation_name"]),
                reason=cast("str", values["reason"]),
                retry_key=retry_key,
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="api",
            )
        )
        payload: dict[str, object] = {"aggregate_version": result.resulting_version}
        return Response(
            WorkforceStructureTemplateMutationResultSerializer(payload).data,
            status=(status.HTTP_200_OK if result.replayed else status.HTTP_201_CREATED),
        )


class WorkforceDepartmentCollectionView(_WorkforceStructureMutationView):
    """Expose workforce department collection through the HTTP API."""

    @extend_schema(
        operation_id="workforce_create_department",
        parameters=[_STRUCTURE_IDEMPOTENCY_PARAMETER],
        request=WorkforceDepartmentCreateSerializer,
        responses={
            200: OpenApiResponse(
                response=WorkforceDepartmentMutationResultSerializer,
                description="The identical creation request was replayed.",
            ),
            201: OpenApiResponse(
                response=WorkforceDepartmentMutationResultSerializer,
                description="The Department was created.",
            ),
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The closed request or Idempotency-Key is invalid."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "The mutation route or required authority is unavailable."
            ),
            (404, PROBLEM_CONTENT_TYPE): _problem_response(
                "A submitted exact target is unavailable."
            ),
            (409, PROBLEM_CONTENT_TYPE): _problem_response(
                "The request conflicts with structure state or prior retry evidence."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "A canonical command dependency is temporarily unavailable."
            ),
        },
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        """Create the department.

        Reach explicit uniform denials while retaining authenticated CSRF checks.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.
        edition_id : UUID
            The event edition identifier that scopes the operation.

        Returns
        -------
        Response
            The HTTP response for the requested operation.
        """
        scope = _authorize_structure_mutation(
            request=request,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        retry_key = _structure_idempotency_key(request)
        values = _validated_structure_payload(
            request,
            serializer_class=WorkforceDepartmentCreateSerializer,
        )
        correlation_id = UUID(request.correlation_id)  # type: ignore[attr-defined]
        result = _execute_structure_command(
            lambda: create_department(
                actor=scope.account,
                organization_id=organization_id,
                series_id=scope.series_id,
                edition_id=edition_id,
                name=cast("str", values["name"]),
                description=cast("str", values["description"]),
                parent_department_id=cast(
                    "UUID | None",
                    values["parent_department_id"],
                ),
                display_order=cast("int", values["display_order"]),
                expected_version=cast("int", values["expected_version"]),
                reason=cast("str", values["reason"]),
                retry_key=retry_key,
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="api",
            )
        )
        payload = {
            "department_id": result.department_id,
            "aggregate_version": result.resulting_version,
        }
        return Response(
            WorkforceDepartmentMutationResultSerializer(payload).data,
            status=(status.HTTP_200_OK if result.replayed else status.HTTP_201_CREATED),
        )


class WorkforceDepartmentDetailView(_WorkforceStructureMutationView):
    """Expose workforce department detail through the HTTP API."""

    schema = _WorkforceStructureAutoSchema()

    @extend_schema(
        operation_id="workforce_update_department",
        request=WorkforceDepartmentUpdateSerializer,
        responses={
            200: WorkforceDepartmentMutationResultSerializer,
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The complete replacement request is invalid."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "The mutation route or required authority is unavailable."
            ),
            (404, PROBLEM_CONTENT_TYPE): _problem_response(
                "The exact Department or parent target is unavailable."
            ),
            (409, PROBLEM_CONTENT_TYPE): _problem_response(
                "The request conflicts with current structure state."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "A canonical command dependency is temporarily unavailable."
            ),
        },
    )
    def put(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        department_id: UUID,
    ) -> Response:
        """Update the department.

        Reach explicit uniform denials while retaining authenticated CSRF checks.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.
        edition_id : UUID
            The event edition identifier that scopes the operation.
        department_id : UUID
            The department identifier within the requested scope.

        Returns
        -------
        Response
            The HTTP response for the requested operation.
        """
        scope = _authorize_structure_mutation(
            request=request,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        values = _validated_structure_payload(
            request,
            serializer_class=WorkforceDepartmentUpdateSerializer,
        )
        correlation_id = UUID(request.correlation_id)  # type: ignore[attr-defined]
        result = _execute_structure_command(
            lambda: update_department(
                actor=scope.account,
                organization_id=organization_id,
                series_id=scope.series_id,
                edition_id=edition_id,
                department_id=department_id,
                name=cast("str", values["name"]),
                description=cast("str", values["description"]),
                parent_department_id=cast(
                    "UUID | None",
                    values["parent_department_id"],
                ),
                display_order=cast("int", values["display_order"]),
                expected_version=cast("int", values["expected_version"]),
                reason=cast("str", values["reason"]),
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="api",
            )
        )
        payload = {
            "department_id": result.department_id,
            "aggregate_version": result.resulting_version,
        }
        return Response(WorkforceDepartmentMutationResultSerializer(payload).data)

    @extend_schema(
        operation_id="workforce_delete_department",
        request=WorkforceDepartmentDeleteSerializer,
        responses={
            200: WorkforceDepartmentMutationResultSerializer,
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The protected deletion request is invalid."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "The mutation route or required authority is unavailable."
            ),
            (404, PROBLEM_CONTENT_TYPE): _problem_response(
                "The exact Department target is unavailable."
            ),
            (409, PROBLEM_CONTENT_TYPE): _problem_response(
                "The request conflicts with retained dependencies or current state."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "A canonical command dependency is temporarily unavailable."
            ),
        },
    )
    def delete(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        department_id: UUID,
    ) -> Response:
        """Delete the department.

        Reach explicit uniform denials while retaining authenticated CSRF checks.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.
        edition_id : UUID
            The event edition identifier that scopes the operation.
        department_id : UUID
            The department identifier within the requested scope.

        Returns
        -------
        Response
            The HTTP response for the requested operation.
        """
        scope = _authorize_structure_mutation(
            request=request,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        values = _validated_structure_payload(
            request,
            serializer_class=WorkforceDepartmentDeleteSerializer,
        )
        correlation_id = UUID(request.correlation_id)  # type: ignore[attr-defined]
        result = _execute_structure_command(
            lambda: delete_unused_department(
                actor=scope.account,
                organization_id=organization_id,
                series_id=scope.series_id,
                edition_id=edition_id,
                department_id=department_id,
                expected_version=cast("int", values["expected_version"]),
                confirmation_name=cast("str", values["confirmation_name"]),
                reason=cast("str", values["reason"]),
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="api",
            )
        )
        payload = {
            "department_id": result.department_id,
            "aggregate_version": result.resulting_version,
        }
        return Response(WorkforceDepartmentMutationResultSerializer(payload).data)


class WorkforceDepartmentRetireView(_WorkforceStructureMutationView):
    """Expose workforce department retire through the HTTP API."""

    @extend_schema(
        operation_id="workforce_retire_department",
        request=WorkforceDepartmentRetireSerializer,
        responses={
            200: WorkforceDepartmentMutationResultSerializer,
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The retirement request is invalid."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "The mutation route or required authority is unavailable."
            ),
            (404, PROBLEM_CONTENT_TYPE): _problem_response(
                "The exact Department target is unavailable."
            ),
            (409, PROBLEM_CONTENT_TYPE): _problem_response(
                "The request conflicts with retained dependencies or current state."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "A canonical command dependency is temporarily unavailable."
            ),
        },
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        department_id: UUID,
    ) -> Response:
        """Retire the department.

        Reach explicit uniform denials while retaining authenticated CSRF checks.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.
        edition_id : UUID
            The event edition identifier that scopes the operation.
        department_id : UUID
            The department identifier within the requested scope.

        Returns
        -------
        Response
            The HTTP response for the requested operation.
        """
        scope = _authorize_structure_mutation(
            request=request,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        values = _validated_structure_payload(
            request,
            serializer_class=WorkforceDepartmentRetireSerializer,
        )
        correlation_id = UUID(request.correlation_id)  # type: ignore[attr-defined]
        result = _execute_structure_command(
            lambda: retire_department(
                actor=scope.account,
                organization_id=organization_id,
                series_id=scope.series_id,
                edition_id=edition_id,
                department_id=department_id,
                expected_version=cast("int", values["expected_version"]),
                reason=cast("str", values["reason"]),
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="api",
            )
        )
        payload = {
            "department_id": result.department_id,
            "aggregate_version": result.resulting_version,
        }
        return Response(WorkforceDepartmentMutationResultSerializer(payload).data)


def _position_mutation_response(
    result: PositionStructureResult,
    *,
    created: bool = False,
) -> Response:
    payload = {
        "position_id": result.position_id,
        "aggregate_version": result.resulting_version,
    }
    response_status = (
        status.HTTP_200_OK
        if result.replayed or not created
        else status.HTTP_201_CREATED
    )
    return Response(
        WorkforcePositionMutationResultSerializer(payload).data,
        status=response_status,
    )


class WorkforcePositionCollectionView(_WorkforceStructureMutationView):
    """Create governed Positions in one exact edition."""

    @extend_schema(
        operation_id="workforce_create_position",
        request=WorkforcePositionCreateSerializer,
        parameters=[_STRUCTURE_IDEMPOTENCY_PARAMETER],
        responses={
            201: WorkforcePositionMutationResultSerializer,
            200: WorkforcePositionMutationResultSerializer,
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The Position request or idempotency key is invalid."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "The mutation route or required authority is unavailable."
            ),
            (404, PROBLEM_CONTENT_TYPE): _problem_response(
                "The exact Department or reporting Position is unavailable."
            ),
            (409, PROBLEM_CONTENT_TYPE): _problem_response(
                "The request conflicts with current structure state."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "A canonical command dependency is temporarily unavailable."
            ),
        },
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        """Create a Position and its private draft volunteer opportunity.

        Parameters
        ----------
        request : Request
            Authenticated strict JSON request with an idempotency header.
        organization_id : UUID
            Untrusted organization route identifier.
        edition_id : UUID
            Untrusted event-edition route identifier.

        Returns
        -------
        Response
            Minimized Position identifier and resulting structure version.
        """
        scope = _authorize_structure_mutation(
            request=request,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        retry_key = _structure_idempotency_key(request)
        values = _validated_structure_payload(
            request,
            serializer_class=WorkforcePositionCreateSerializer,
        )
        correlation_id = UUID(request.correlation_id)  # type: ignore[attr-defined]
        result = _execute_structure_command(
            lambda: create_position(
                actor=scope.account,
                organization_id=organization_id,
                series_id=scope.series_id,
                edition_id=edition_id,
                template_id=cast("UUID", values["template_id"]),
                department_id=cast("UUID", values["department_id"]),
                reports_to_id=cast("UUID | None", values["reports_to_id"]),
                title=cast("str", values["title"]),
                description=cast("str", values["description"]),
                headcount=cast("int", values["headcount"]),
                expected_version=cast("int", values["expected_version"]),
                reason=cast("str", values["reason"]),
                retry_key=retry_key,
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="api",
            )
        )
        return _position_mutation_response(result, created=True)


class WorkforcePositionDetailView(_WorkforceStructureMutationView):
    """Replace the editable details of one exact-edition Position."""

    @extend_schema(
        operation_id="workforce_update_position",
        request=WorkforcePositionUpdateSerializer,
        responses={
            200: WorkforcePositionMutationResultSerializer,
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The complete Position replacement is invalid."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "The mutation route or required authority is unavailable."
            ),
            (404, PROBLEM_CONTENT_TYPE): _problem_response(
                "The exact Position or reporting Position is unavailable."
            ),
            (409, PROBLEM_CONTENT_TYPE): _problem_response(
                "The request conflicts with current structure state."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "A canonical command dependency is temporarily unavailable."
            ),
        },
    )
    def put(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        position_id: UUID,
    ) -> Response:
        """Replace editable Position details through the shared command.

        Parameters
        ----------
        request : Request
            Authenticated strict complete-replacement JSON request.
        organization_id : UUID
            Untrusted organization route identifier.
        edition_id : UUID
            Untrusted event-edition route identifier.
        position_id : UUID
            Position identifier resolved after exact-edition authorization.

        Returns
        -------
        Response
            Minimized Position identifier and resulting structure version.
        """
        scope = _authorize_structure_mutation(
            request=request,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        values = _validated_structure_payload(
            request,
            serializer_class=WorkforcePositionUpdateSerializer,
        )
        correlation_id = UUID(request.correlation_id)  # type: ignore[attr-defined]
        result = _execute_structure_command(
            lambda: update_position(
                actor=scope.account,
                organization_id=organization_id,
                series_id=scope.series_id,
                edition_id=edition_id,
                position_id=position_id,
                reports_to_id=cast("UUID | None", values["reports_to_id"]),
                title=cast("str", values["title"]),
                description=cast("str", values["description"]),
                headcount=cast("int", values["headcount"]),
                expected_version=cast("int", values["expected_version"]),
                reason=cast("str", values["reason"]),
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="api",
            )
        )
        return _position_mutation_response(result)


class WorkforcePositionOpportunityView(_WorkforceStructureMutationView):
    """Replace the volunteer-opportunity settings paired to one Position."""

    @extend_schema(
        operation_id="workforce_update_position_opportunity",
        request=WorkforcePositionOpportunityUpdateSerializer,
        responses={
            200: WorkforcePositionMutationResultSerializer,
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The complete opportunity replacement is invalid."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "The mutation route or required authority is unavailable."
            ),
            (404, PROBLEM_CONTENT_TYPE): _problem_response(
                "The exact Position is unavailable."
            ),
            (409, PROBLEM_CONTENT_TYPE): _problem_response(
                "The request conflicts with current structure state."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "A canonical command dependency is temporarily unavailable."
            ),
        },
    )
    def put(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        position_id: UUID,
    ) -> Response:
        """Replace the applicant-facing opportunity through the shared command.

        Parameters
        ----------
        request : Request
            Authenticated strict complete-replacement JSON request.
        organization_id : UUID
            Untrusted organization route identifier.
        edition_id : UUID
            Untrusted event-edition route identifier.
        position_id : UUID
            Position identifier resolved after exact-edition authorization.

        Returns
        -------
        Response
            Minimized Position identifier and resulting structure version.
        """
        scope = _authorize_structure_mutation(
            request=request,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        values = _validated_structure_payload(
            request,
            serializer_class=WorkforcePositionOpportunityUpdateSerializer,
        )
        correlation_id = UUID(request.correlation_id)  # type: ignore[attr-defined]
        result = _execute_structure_command(
            lambda: update_position_opportunity(
                actor=scope.account,
                organization_id=organization_id,
                series_id=scope.series_id,
                edition_id=edition_id,
                position_id=position_id,
                status=cast("str", values["status"]),
                headline=cast("str", values["headline"]),
                description=cast("str", values["description"]),
                applications_open_at=cast(
                    "datetime | None", values["applications_open_at"]
                ),
                applications_close_at=cast(
                    "datetime | None", values["applications_close_at"]
                ),
                visible_when_filled=cast("bool", values["visible_when_filled"]),
                expected_version=cast("int", values["expected_version"]),
                reason=cast("str", values["reason"]),
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="api",
            )
        )
        return _position_mutation_response(result)


class WorkforcePositionCloseView(_WorkforceStructureMutationView):
    """Close one dependency-free Position while preserving its history."""

    @extend_schema(
        operation_id="workforce_close_position",
        request=WorkforcePositionCloseSerializer,
        responses={
            200: WorkforcePositionMutationResultSerializer,
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The Position closure request is invalid."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "The mutation route or required authority is unavailable."
            ),
            (404, PROBLEM_CONTENT_TYPE): _problem_response(
                "The exact Position is unavailable."
            ),
            (409, PROBLEM_CONTENT_TYPE): _problem_response(
                "Current dependencies or structure state prevent closure."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "A canonical command dependency is temporarily unavailable."
            ),
        },
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        position_id: UUID,
    ) -> Response:
        """Close the Position and its public opportunity through one command.

        Parameters
        ----------
        request : Request
            Authenticated strict Position-closure JSON request.
        organization_id : UUID
            Untrusted organization route identifier.
        edition_id : UUID
            Untrusted event-edition route identifier.
        position_id : UUID
            Position identifier resolved after exact-edition authorization.

        Returns
        -------
        Response
            Minimized Position identifier and resulting structure version.
        """
        scope = _authorize_structure_mutation(
            request=request,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        values = _validated_structure_payload(
            request,
            serializer_class=WorkforcePositionCloseSerializer,
        )
        correlation_id = UUID(request.correlation_id)  # type: ignore[attr-defined]
        result = _execute_structure_command(
            lambda: close_position(
                actor=scope.account,
                organization_id=organization_id,
                series_id=scope.series_id,
                edition_id=edition_id,
                position_id=position_id,
                expected_version=cast("int", values["expected_version"]),
                confirmation_name=cast("str", values["confirmation_name"]),
                reason=cast("str", values["reason"]),
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="api",
            )
        )
        return _position_mutation_response(result)


class WorkforceAssignmentProposalView(_WorkforceStructureMutationView):
    """Propose one known person for an exact-edition Position."""

    @extend_schema(
        operation_id="workforce_propose_position_assignment",
        request=WorkforceAssignmentProposalSerializer,
        parameters=[_STRUCTURE_IDEMPOTENCY_PARAMETER],
        responses={
            201: WorkforceAssignmentMutationResultSerializer,
            200: WorkforceAssignmentMutationResultSerializer,
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The closed proposal request or idempotency key is invalid."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "The route or required assignment and role authority is unavailable."
            ),
            (404, PROBLEM_CONTENT_TYPE): _problem_response(
                "The Position or known person is unavailable."
            ),
            (409, PROBLEM_CONTENT_TYPE): _problem_response(
                "Headcount, lifecycle, or current assignment state prevents proposal."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "A canonical command dependency is temporarily unavailable."
            ),
        },
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        position_id: UUID,
    ) -> Response:
        """Record a proposal without issuing role authority.

        Parameters
        ----------
        request : Request
            Incoming authenticated proposal request.
        organization_id : UUID
            Organization identifier from the route.
        edition_id : UUID
            Exact event edition identifier from the route.
        position_id : UUID
            Position identifier receiving the proposal.

        Returns
        -------
        Response
            Minimized assignment command result with creation or replay status.
        """
        scope = _authorize_assignment_mutation(
            request=request,
            organization_id=organization_id,
            edition_id=edition_id,
            authority_capability="authorization.manage_roles",
        )
        retry_key = _structure_idempotency_key(request)
        values = _validated_structure_payload(
            request,
            serializer_class=WorkforceAssignmentProposalSerializer,
        )
        correlation_id = UUID(request.correlation_id)  # type: ignore[attr-defined]
        result = _execute_assignment_command(
            lambda: propose_position_assignment(
                actor=scope.account,
                organization_id=organization_id,
                series_id=scope.series_id,
                edition_id=edition_id,
                position_id=position_id,
                account_id=cast("UUID", values["account_id"]),
                effective_from=cast("datetime", values["effective_from"]),
                expires_at=cast("datetime | None", values["expires_at"]),
                reason=cast("str", values["reason"]),
                retry_key=retry_key,
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="api",
            )
        )
        return _assignment_mutation_response(result, created=True)


def _run_assignment_decision(
    *,
    request: Request,
    organization_id: UUID,
    edition_id: UUID,
    assignment_id: UUID,
    authority_capability: str,
    command: Callable[..., AssignmentCommandResult],
) -> Response:
    """Apply the shared authorization, step-up, and strict decision boundary.

    Parameters
    ----------
    request : Request
        Incoming authenticated decision request.
    organization_id : UUID
        Organization identifier from the route.
    edition_id : UUID
        Exact event edition identifier from the route.
    assignment_id : UUID
        Assignment identifier receiving the decision.
    authority_capability : str
        Role-management or revocation capability required by the action.
    command : Callable[..., AssignmentCommandResult]
        Shared assignment application command to invoke.

    Returns
    -------
    Response
        Minimized assignment command result.
    """
    scope = _authorize_assignment_mutation(
        request=request,
        organization_id=organization_id,
        edition_id=edition_id,
        authority_capability=authority_capability,
    )
    _require_assignment_api_step_up(request=request, account=scope.account)
    retry_key = _structure_idempotency_key(request)
    values = _validated_structure_payload(
        request,
        serializer_class=WorkforceAssignmentDecisionSerializer,
    )
    correlation_id = UUID(request.correlation_id)  # type: ignore[attr-defined]
    result = _execute_assignment_command(
        lambda: command(
            actor=scope.account,
            organization_id=organization_id,
            series_id=scope.series_id,
            edition_id=edition_id,
            assignment_id=assignment_id,
            expected_version=cast("int", values["expected_version"]),
            reason=cast("str", values["reason"]),
            retry_key=retry_key,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="api",
        )
    )
    return _assignment_mutation_response(result)


_ASSIGNMENT_DECISION_RESPONSES = {
    200: WorkforceAssignmentMutationResultSerializer,
    (400, PROBLEM_CONTENT_TYPE): _problem_response(
        "The closed decision request or idempotency key is invalid."
    ),
    (403, PROBLEM_CONTENT_TYPE): _problem_response(
        "Fresh authentication or required scoped authority is unavailable."
    ),
    (404, PROBLEM_CONTENT_TYPE): _problem_response(
        "The exact assignment is unavailable."
    ),
    (409, PROBLEM_CONTENT_TYPE): _problem_response(
        "The decision conflicts with assignment state, readiness, or headcount."
    ),
    (503, PROBLEM_CONTENT_TYPE): _problem_response(
        "A canonical command dependency is temporarily unavailable."
    ),
}


class WorkforceAssignmentApproveView(_WorkforceStructureMutationView):
    """Approve and activate one proposal under independent control."""

    @extend_schema(
        operation_id="workforce_approve_position_assignment",
        request=WorkforceAssignmentDecisionSerializer,
        parameters=[_STRUCTURE_IDEMPOTENCY_PARAMETER],
        responses=_ASSIGNMENT_DECISION_RESPONSES,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        assignment_id: UUID,
    ) -> Response:
        """Approve a proposal after fresh authentication.

        Parameters
        ----------
        request : Request
            Incoming authenticated approval request.
        organization_id : UUID
            Organization identifier from the route.
        edition_id : UUID
            Exact event edition identifier from the route.
        assignment_id : UUID
            Proposed assignment identifier.

        Returns
        -------
        Response
            Minimized activated assignment result.
        """
        return _run_assignment_decision(
            request=request,
            organization_id=organization_id,
            edition_id=edition_id,
            assignment_id=assignment_id,
            authority_capability="authorization.manage_roles",
            command=approve_position_assignment,
        )


class WorkforceAssignmentRejectView(_WorkforceStructureMutationView):
    """Reject one proposal under independent control."""

    @extend_schema(
        operation_id="workforce_reject_position_assignment",
        request=WorkforceAssignmentDecisionSerializer,
        parameters=[_STRUCTURE_IDEMPOTENCY_PARAMETER],
        responses=_ASSIGNMENT_DECISION_RESPONSES,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        assignment_id: UUID,
    ) -> Response:
        """Reject a proposal after fresh authentication.

        Parameters
        ----------
        request : Request
            Incoming authenticated rejection request.
        organization_id : UUID
            Organization identifier from the route.
        edition_id : UUID
            Exact event edition identifier from the route.
        assignment_id : UUID
            Proposed assignment identifier.

        Returns
        -------
        Response
            Minimized rejected assignment result.
        """
        return _run_assignment_decision(
            request=request,
            organization_id=organization_id,
            edition_id=edition_id,
            assignment_id=assignment_id,
            authority_capability="authorization.manage_roles",
            command=reject_position_assignment,
        )


class WorkforceAssignmentEndView(_WorkforceStructureMutationView):
    """End one active assignment and its linked role authority."""

    @extend_schema(
        operation_id="workforce_end_position_assignment",
        request=WorkforceAssignmentDecisionSerializer,
        parameters=[_STRUCTURE_IDEMPOTENCY_PARAMETER],
        responses=_ASSIGNMENT_DECISION_RESPONSES,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        assignment_id: UUID,
    ) -> Response:
        """End responsibility and authority after fresh authentication.

        Parameters
        ----------
        request : Request
            Incoming authenticated ending request.
        organization_id : UUID
            Organization identifier from the route.
        edition_id : UUID
            Exact event edition identifier from the route.
        assignment_id : UUID
            Active assignment identifier.

        Returns
        -------
        Response
            Minimized ended assignment result.
        """
        return _run_assignment_decision(
            request=request,
            organization_id=organization_id,
            edition_id=edition_id,
            assignment_id=assignment_id,
            authority_capability="authorization.revoke",
            command=end_position_assignment,
        )


class WorkforceAvailabilityConflict(APIException):
    """Name-free RFC 9457 boundary for Availability state conflicts."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "The availability action conflicts with current state."
    default_code = "availability_conflict"

    def __init__(self, *, code: str, errors: Mapping[str, list[str]]) -> None:
        """Initialize one stable person-owned Availability conflict.

        Parameters
        ----------
        code : str
            Stable machine-readable conflict code.
        errors : Mapping[str, list[str]]
            Safe field-oriented recovery messages.
        """
        super().__init__(
            detail=cast(
                "Any",
                {
                    "detail": self.default_detail,
                    "code": code,
                    "errors": dict(errors),
                },
            ),
            code=code,
        )


_AVAILABILITY_CONFLICT_ERRORS: dict[
    type[AvailabilityCommandError],
    tuple[str, dict[str, list[str]]],
] = {
    AvailabilityVersionConflictError: (
        AvailabilityVersionConflictError.reason_code,
        {"expected_version": ["Reload availability and try again."]},
    ),
    AvailabilityRetryConflictError: (
        AvailabilityRetryConflictError.reason_code,
        {IDEMPOTENCY_HEADER_NAME: ["Use a new key for a different request."]},
    ),
    AvailabilityLifecycleConflictError: (
        AvailabilityLifecycleConflictError.reason_code,
        {"non_field_errors": ["Availability is currently read-only."]},
    ),
    AvailabilityRelationshipRequiredError: (
        AvailabilityRelationshipRequiredError.reason_code,
        {
            "non_field_errors": [
                "An open proposed or active Position is required for this change."
            ]
        },
    ),
    AvailabilityStateConflictError: (
        AvailabilityStateConflictError.reason_code,
        {"non_field_errors": ["Reload availability before retrying."]},
    ),
}


def _availability_person_scope(
    *,
    request: Request,
    organization_id: UUID,
    edition_id: UUID,
    require_edit: bool,
) -> tuple[Account, EventEdition]:
    """Authorize a self relationship before parsing request input.

    Parameters
    ----------
    request : Request
        Authenticated API request.
    organization_id : UUID
        Organization identifier from the route.
    edition_id : UUID
        Exact event edition identifier from the route.
    require_edit : bool
        Whether an open assignment must permit replacement.

    Returns
    -------
    tuple[Account, EventEdition]
        Authenticated person and exact authorized edition.

    Raises
    ------
    PermissionDenied
        If identity, scope, relationship, or requested editability is absent.
    """
    account = request.user
    if not isinstance(account, Account) or not account.is_active:
        raise PermissionDenied(
            "The availability route is unavailable.",
            code=AvailabilityAuthorizationDeniedError.reason_code,
        )
    try:
        authorize_person_availability_command(
            actor=account,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        related = person_has_availability_relationship(
            account=account,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        editable = person_can_edit_availability(
            account=account,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        if not related or (require_edit and not editable):
            raise PermissionDenied(
                "The availability route is unavailable.",
                code=AvailabilityAuthorizationDeniedError.reason_code,
            )
        edition = EventEdition.objects.select_related("organization", "series").get(
            id=edition_id,
            organization_id=organization_id,
            series__organization_id=organization_id,
        )
    except AvailabilityAuthorizationDeniedError as error:
        raise PermissionDenied(
            "The availability route is unavailable.",
            code=error.reason_code,
        ) from error
    except EventEdition.DoesNotExist as error:
        raise PermissionDenied(
            "The availability route is unavailable.",
            code=AvailabilityAuthorizationDeniedError.reason_code,
        ) from error
    except (DatabaseError, RuntimeError) as error:
        _raise_dependency_unavailable(
            "Unable to authorize personal Workforce availability",
            error,
        )
    return account, edition


def _availability_window_payload(
    window: AvailabilityWindowProjection,
) -> dict[str, object]:
    """Return one exact current period from a vetted projection object.

    Parameters
    ----------
    window : AvailabilityWindowProjection
        Canonical owner-visible or deliberately shared current period.

    Returns
    -------
    dict[str, object]
        Serializer-ready current-period fields.
    """
    return {
        "starts_at": window.starts_at,
        "ends_at": window.ends_at,
        "preference": window.preference,
        "preference_label": window.preference_label,
    }


def _my_availability_payload(
    *,
    account: Account,
    edition: EventEdition,
) -> dict[str, object]:
    """Load and compose the complete owner-visible current plan.

    Parameters
    ----------
    account : Account
        Authenticated person who owns the plan.
    edition : EventEdition
        Exact authorized edition with organization and series loaded.

    Returns
    -------
    dict[str, object]
        Serializer-ready owner projection, including private draft periods.
    """
    with repeatable_read_only_snapshot():
        projection = load_person_availability(
            account=account,
            organization_id=edition.organization_id,
            edition_id=edition.id,
        )
        can_edit = person_can_edit_availability(
            account=account,
            organization_id=edition.organization_id,
            edition_id=edition.id,
        )
    authorize_person_availability_command(
        actor=account,
        organization_id=edition.organization_id,
        edition_id=edition.id,
    )
    return {
        "organization_name": edition.organization.name,
        "series_name": edition.series.name,
        "edition_name": edition.name,
        "starts_on": edition.starts_on,
        "ends_on": edition.ends_on,
        "time_zone": edition.time_zone,
        "state": projection.state,
        "state_label": projection.state_label,
        "availability_version": projection.version,
        "can_edit": can_edit,
        "windows": [
            _availability_window_payload(window) for window in projection.windows
        ],
    }


def _execute_availability_command(
    command: Callable[[], AvailabilityCommandResult],
) -> AvailabilityCommandResult:
    """Map the shared Availability command boundary to stable API failures.

    Parameters
    ----------
    command : Callable[[], AvailabilityCommandResult]
        Deferred canonical command invocation.

    Returns
    -------
    AvailabilityCommandResult
        Minimized successful command result.

    Raises
    ------
    PermissionDenied
        If exact owner authority is unavailable.
    ApiValidationError
        If safe caller-owned command input is invalid.
    WorkforceAvailabilityConflict
        If current lifecycle, relationship, retry, or version state conflicts.
    """
    try:
        return command()
    except AvailabilityAuthorizationDeniedError as error:
        raise PermissionDenied(
            "The availability route is unavailable.",
            code=error.reason_code,
        ) from error
    except DjangoValidationError as error:
        safe_fields = frozenset({"expected_version", "status", "windows", "retry_key"})
        if not hasattr(error, "error_dict") or not set(error.error_dict).issubset(
            safe_fields
        ):
            _raise_dependency_unavailable(
                "A Workforce availability command rejected server-owned input",
                error,
            )
        code = _django_assignment_validation_code(error).replace(
            "assignment_",
            "availability_",
        )
        raise ApiValidationError(
            cast(
                "Any",
                {
                    "detail": "The availability input is invalid.",
                    "code": code,
                    "errors": {
                        field_name: messages
                        for field_name, messages in error.message_dict.items()
                        if field_name in safe_fields
                    },
                },
            ),
            code=code,
        ) from error
    except tuple(_AVAILABILITY_CONFLICT_ERRORS) as error:
        code, errors = _AVAILABILITY_CONFLICT_ERRORS[type(error)]
        raise WorkforceAvailabilityConflict(code=code, errors=errors) from error
    except (DatabaseError, AvailabilityCommandError, RuntimeError) as error:
        _raise_dependency_unavailable(
            "Unable to apply a Workforce availability command",
            error,
        )


def _availability_mutation_response(
    result: AvailabilityCommandResult,
    *,
    created: bool = False,
) -> Response:
    payload = {
        "plan_id": result.plan_id,
        "availability_version": result.resulting_version,
        "status": result.status,
        "window_count": result.window_count,
    }
    response_status = (
        status.HTTP_201_CREATED
        if created and not result.replayed
        else status.HTTP_200_OK
    )
    return Response(
        WorkforceAvailabilityMutationResultSerializer(payload).data,
        status=response_status,
    )


_AVAILABILITY_MUTATION_RESPONSES = {
    200: WorkforceAvailabilityMutationResultSerializer,
    201: WorkforceAvailabilityMutationResultSerializer,
    (400, PROBLEM_CONTENT_TYPE): _problem_response(
        "The closed Availability request or idempotency key is invalid."
    ),
    (403, PROBLEM_CONTENT_TYPE): _problem_response(
        "The exact person-owned Availability route is unavailable."
    ),
    (409, PROBLEM_CONTENT_TYPE): _problem_response(
        "The request conflicts with current Availability state."
    ),
    (503, PROBLEM_CONTENT_TYPE): _problem_response(
        "A canonical Availability dependency is temporarily unavailable."
    ),
}
_AVAILABILITY_WITHDRAW_RESPONSES = {
    key: value
    for key, value in _AVAILABILITY_MUTATION_RESPONSES.items()
    if key != status.HTTP_201_CREATED
}


@method_decorator(never_cache, name="dispatch")
class WorkforceMyAvailabilityView(_WorkforceStructureMutationView):
    """Read or completely replace the current person's edition Availability."""

    @extend_schema(
        operation_id="workforce_retrieve_my_availability",
        responses={
            200: WorkforceMyAvailabilitySerializer,
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The Availability query contains unsupported input."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "The exact person-owned Availability route is unavailable."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "Current Availability is temporarily unavailable."
            ),
        },
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        """Return the owner's current plan, including a private draft.

        Parameters
        ----------
        request : Request
            Authenticated owner request.
        organization_id : UUID
            Organization identifier from the route.
        edition_id : UUID
            Exact event edition identifier from the route.

        Returns
        -------
        Response
            Private current Availability projection.

        Raises
        ------
        PermissionDenied
            If current self authority disappears before disclosure.
        """
        account, edition = _availability_person_scope(
            request=request,
            organization_id=organization_id,
            edition_id=edition_id,
            require_edit=False,
        )
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        try:
            payload = _my_availability_payload(account=account, edition=edition)
        except AvailabilityAuthorizationDeniedError as error:
            raise PermissionDenied(
                "The availability route is unavailable.",
                code=error.reason_code,
            ) from error
        except (
            AvailabilityProjectionIntegrityError,
            AvailabilityReadLimitExceededError,
            DatabaseError,
            RuntimeError,
        ) as error:
            _raise_dependency_unavailable(
                "Unable to load personal Workforce availability",
                error,
            )
        return Response(WorkforceMyAvailabilitySerializer(payload).data)

    @extend_schema(
        operation_id="workforce_replace_my_availability",
        request=WorkforceAvailabilityReplaceSerializer,
        parameters=[_STRUCTURE_IDEMPOTENCY_PARAMETER],
        responses=_AVAILABILITY_MUTATION_RESPONSES,
    )
    def put(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        """Replace all current periods as a private draft or shared plan.

        Parameters
        ----------
        request : Request
            Authenticated owner request with closed replacement input.
        organization_id : UUID
            Organization identifier from the route.
        edition_id : UUID
            Exact event edition identifier from the route.

        Returns
        -------
        Response
            Minimized replacement result.
        """
        account, edition = _availability_person_scope(
            request=request,
            organization_id=organization_id,
            edition_id=edition_id,
            require_edit=True,
        )
        retry_key = _structure_idempotency_key(request)
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        payload = request.data
        serializer = WorkforceAvailabilityReplaceSerializer(
            data=payload,
            context={"edition": edition},
        )
        reject_unknown_fields(payload, allowed_fields=frozenset(serializer.fields))
        serializer.is_valid(raise_exception=True)
        values = cast("dict[str, object]", serializer.validated_data)
        correlation_id = UUID(request.correlation_id)  # type: ignore[attr-defined]
        result = _execute_availability_command(
            lambda: save_person_availability(
                actor=account,
                organization_id=organization_id,
                edition_id=edition_id,
                expected_version=cast("int", values["expected_version"]),
                status=cast("str", values["status"]),
                windows=cast("Any", values["windows"]),
                retry_key=retry_key,
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="api",
            )
        )
        return _availability_mutation_response(
            result,
            created=cast("int", values["expected_version"]) == 0,
        )


@method_decorator(never_cache, name="dispatch")
class WorkforceMyAvailabilityWithdrawView(_WorkforceStructureMutationView):
    """Withdraw the current person's plan and delete every exact period."""

    @extend_schema(
        operation_id="workforce_withdraw_my_availability",
        request=WorkforceAvailabilityWithdrawSerializer,
        parameters=[_STRUCTURE_IDEMPOTENCY_PARAMETER],
        responses=_AVAILABILITY_WITHDRAW_RESPONSES,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        """Withdraw current exact periods while retaining minimized evidence.

        Parameters
        ----------
        request : Request
            Authenticated owner request with closed withdrawal input.
        organization_id : UUID
            Organization identifier from the route.
        edition_id : UUID
            Exact event edition identifier from the route.

        Returns
        -------
        Response
            Minimized withdrawn-plan result.
        """
        account, _edition = _availability_person_scope(
            request=request,
            organization_id=organization_id,
            edition_id=edition_id,
            require_edit=False,
        )
        retry_key = _structure_idempotency_key(request)
        values = _validated_structure_payload(
            request,
            serializer_class=WorkforceAvailabilityWithdrawSerializer,
        )
        correlation_id = UUID(request.correlation_id)  # type: ignore[attr-defined]
        result = _execute_availability_command(
            lambda: withdraw_person_availability(
                actor=account,
                organization_id=organization_id,
                edition_id=edition_id,
                expected_version=cast("int", values["expected_version"]),
                retry_key=retry_key,
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="api",
            )
        )
        return _availability_mutation_response(result)


def _organizer_availability_decision(
    *,
    account: Account,
    organization_id: UUID,
    edition_id: UUID,
    at: datetime,
) -> PolicyDecision:
    """Authorize the complete exact-edition organizer projection.

    Parameters
    ----------
    account : Account
        Authenticated organizer.
    organization_id : UUID
        Exact owning organization.
    edition_id : UUID
        Exact event edition.
    at : datetime
        Policy evaluation instant.

    Returns
    -------
    PolicyDecision
        Allowed decision with the complete required field ceiling.

    Raises
    ------
    PermissionDenied
        If capability or any required projection field is absent.
    """
    decision = decide(
        principal=account,
        capability_code="workforce.view_availability",
        resource=resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
        requested_fields=AVAILABILITY_ORGANIZER_REQUIRED_FIELDS,
        at=at,
    )
    if not decision.allowed:
        raise PermissionDenied(
            "This account cannot view Workforce availability.",
            code=decision.reason_code,
        )
    try:
        require_complete_projection(
            required_fields=AVAILABILITY_ORGANIZER_REQUIRED_FIELDS,
            permitted_fields=decision.fields,
        )
    except FieldProjectionDeniedError as error:
        raise PermissionDenied(
            "The permitted Availability projection is incomplete.",
            code="field_projection_denied",
        ) from error
    return decision


@method_decorator(never_cache, name="dispatch")
class WorkforceOrganizerAvailabilityView(APIView):
    """Return shared current Availability for people with open assignments."""

    @extend_schema(
        operation_id="workforce_retrieve_availability",
        responses={
            200: WorkforceOrganizerAvailabilitySerializer,
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The Availability query contains unsupported input."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "The caller cannot view this edition's Availability."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "The complete Availability projection is temporarily unavailable."
            ),
        },
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        """Return current owner-shared planning consequences and periods.

        Parameters
        ----------
        request : Request
            Authenticated organizer request.
        organization_id : UUID
            Organization identifier from the route.
        edition_id : UUID
            Exact event edition identifier from the route.

        Returns
        -------
        Response
            Audited minimized organizer Availability projection.

        Raises
        ------
        PermissionDenied
            If the exact edition is unavailable after authorization.
        """
        account = _account(request)
        _organizer_availability_decision(
            account=account,
            organization_id=organization_id,
            edition_id=edition_id,
            at=timezone_now(),
        )
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        try:
            with repeatable_read_only_snapshot():
                edition = EventEdition.objects.select_related(
                    "organization",
                    "series",
                ).get(
                    id=edition_id,
                    organization_id=organization_id,
                    series__organization_id=organization_id,
                )
                overview = load_organizer_availability_overview(edition=edition)
            response_authorized_at = timezone_now()
            final_decision = _organizer_availability_decision(
                account=account,
                organization_id=organization_id,
                edition_id=edition_id,
                at=response_authorized_at,
            )
            append_availability_read_audit(
                actor=account,
                organization_id=organization_id,
                edition_id=edition_id,
                decision=final_decision,
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
                route_name="api-workforce-availability",
                http_method=cast("str", request.method),
                source_channel="api",
                occurred_at=response_authorized_at,
            )
        except EventEdition.DoesNotExist as error:
            raise PermissionDenied(
                "This account cannot view Workforce availability.",
                code="target_unavailable",
            ) from error
        except (
            AvailabilityProjectionIntegrityError,
            AvailabilityReadLimitExceededError,
            DatabaseError,
            DjangoValidationError,
            RuntimeError,
        ) as error:
            _raise_dependency_unavailable(
                "Unable to project Workforce availability",
                error,
            )
        payload: dict[str, object] = {
            "organization_name": edition.organization.name,
            "series_name": edition.series.name,
            "edition_name": edition.name,
            "time_zone": edition.time_zone,
            **asdict(overview),
        }
        return Response(WorkforceOrganizerAvailabilitySerializer(payload).data)


def _opportunity_payload(opportunity: VolunteerOpportunity) -> dict[str, object]:
    position = opportunity.position
    return {
        "id": opportunity.id,
        "position_code": position.code,
        "position_title": position.title,
        "department_name": position.department.name,
        "reports_to_title": (
            position.reports_to.title if position.reports_to is not None else None
        ),
        "headline": opportunity.headline,
        "description": opportunity.description,
        "headcount": position.headcount,
        "active_assignment_count": opportunity.active_assignment_count,
        "is_filled": opportunity.is_filled,
        "accepts_applications": opportunity.accepts_applications,
        "applications_open_at": opportunity.applications_open_at,
        "applications_close_at": opportunity.applications_close_at,
    }


def _document_payload(item: OnboardingDocumentRequest) -> dict[str, object]:
    return {
        "id": item.id,
        "document_type_code": item.document_type.code,
        "document_type_name": item.document_type.name,
        "document_type_version": item.document_type.version,
        "status": item.status,
        "instructions": item.instructions,
        "due_at": item.due_at,
        "requested_at": item.requested_at,
        "submitted_at": item.submitted_at,
        "reviewed_at": item.reviewed_at,
        "review_reason": item.review_reason,
        "original_filename": item.original_filename,
        "upload_available": item.status
        in {
            OnboardingDocumentRequest.Status.REQUESTED,
            OnboardingDocumentRequest.Status.REJECTED,
        },
    }


class PublicVolunteerOpportunityListView(APIView):
    """Expose public volunteer opportunity list through the HTTP API."""

    permission_classes = (AllowAny,)

    @extend_schema(
        operation_id="workforce_list_public_volunteer_opportunities",
        responses=VolunteerOpportunitySerializer(many=True),
    )
    def get(self, request: Request, edition_id: UUID) -> Response:
        """List public volunteer opportunities.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        edition_id : UUID
            The event edition identifier that scopes the operation.

        Returns
        -------
        Response
            The HTTP response for the requested operation.
        """
        del request
        edition = get_object_or_404(
            EventEdition.objects.exclude(lifecycle__in=("archived", "cancelled")),
            id=edition_id,
        )
        candidates = (
            VolunteerOpportunity.objects.filter(
                position__edition=edition,
                status=VolunteerOpportunity.Status.PUBLISHED,
            )
            .select_related(
                "position",
                "position__department",
                "position__reports_to",
            )
            .order_by("position__department__display_order", "position__title", "id")
        )
        payload = [
            _opportunity_payload(item)
            for item in candidates
            if not item.is_filled or item.visible_when_filled
        ]
        return Response(
            VolunteerOpportunitySerializer(
                instance=payload,  # type: ignore[arg-type]
                many=True,
            ).data
        )


class MyVolunteerApplicationCreateView(APIView):
    """Expose my volunteer application create through the HTTP API."""

    @extend_schema(
        operation_id="workforce_submit_my_volunteer_application",
        request=VolunteerApplicationSubmitSerializer,
        responses={201: VolunteerApplicationSerializer},
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        opportunity_id: UUID,
    ) -> Response:
        """Submit my volunteer application.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.
        edition_id : UUID
            The event edition identifier that scopes the operation.
        opportunity_id : UUID
            The opportunity identifier within the requested scope.

        Returns
        -------
        Response
            The HTTP response for the requested operation.

        Raises
        ------
        ApiValidationError
            If the request payload violates the endpoint contract.
        NotFound
            If the scoped resource is unavailable to the caller.
        """
        account = _account(request)
        serializer = VolunteerApplicationSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not VolunteerOpportunity.objects.filter(
            id=opportunity_id,
            position__organization_id=organization_id,
            position__edition_id=edition_id,
        ).exists():
            raise NotFound("The volunteer opportunity is unavailable.")
        try:
            application = submit_volunteer_application(
                actor=account,
                opportunity_id=opportunity_id,
                motivation=cast("str", serializer.validated_data["motivation"]),
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            )
        except (ObjectDoesNotExist, DjangoValidationError) as error:
            raise ApiValidationError(
                {
                    "detail": "The volunteer application could not be submitted.",
                    "code": "volunteer_application_invalid",
                }
            ) from error
        payload = {
            "id": application.id,
            "opportunity_id": application.opportunity_id,
            "status": application.status,
            "submitted_at": application.submitted_at,
        }
        return Response(
            VolunteerApplicationSerializer(
                instance=payload,
            ).data,
            status=201,
        )


class MyOnboardingDocumentListView(APIView):
    """Expose my onboarding document list through the HTTP API."""

    @extend_schema(
        operation_id="workforce_list_my_onboarding_documents",
        responses=OnboardingDocumentRequestSerializer(many=True),
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        """List my onboarding documents.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.
        edition_id : UUID
            The event edition identifier that scopes the operation.

        Returns
        -------
        Response
            The HTTP response for the requested operation.

        Raises
        ------
        NotFound
            If the scoped resource is unavailable to the caller.
        """
        account = _account(request)
        decision = decide(
            principal=account,
            capability_code="workforce.view_self",
            resource=resolve_self_target(
                principal=account,
                organization_id=organization_id,
                edition_id=edition_id,
            ),
        )
        if not decision.allowed:
            raise NotFound("Onboarding documents are unavailable.")
        items = (
            OnboardingDocumentRequest.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
                account=account,
            )
            .select_related("document_type")
            .order_by("status", "due_at", "id")
        )
        payload = [_document_payload(item) for item in items]
        return Response(
            OnboardingDocumentRequestSerializer(
                instance=payload,  # type: ignore[arg-type]
                many=True,
            ).data
        )


class MyOnboardingDocumentUploadView(APIView):
    """Expose my onboarding document upload through the HTTP API."""

    parser_classes = (MultiPartParser, FormParser)

    @extend_schema(
        operation_id="workforce_upload_my_onboarding_document",
        request=OnboardingDocumentUploadSerializer,
        responses=OnboardingDocumentRequestSerializer,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        document_request_id: UUID,
    ) -> Response:
        """Upload my onboarding document.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.
        edition_id : UUID
            The event edition identifier that scopes the operation.
        document_request_id : UUID
            The document request identifier within the requested scope.

        Returns
        -------
        Response
            The HTTP response for the requested operation.

        Raises
        ------
        ApiValidationError
            If the request payload violates the endpoint contract.
        NotFound
            If the scoped resource is unavailable to the caller.
        """
        account = _account(request)
        serializer = OnboardingDocumentUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not OnboardingDocumentRequest.objects.filter(
            id=document_request_id,
            organization_id=organization_id,
            edition_id=edition_id,
            account=account,
        ).exists():
            raise NotFound("The onboarding document request is unavailable.")
        try:
            item = upload_onboarding_document(
                actor=account,
                request_id=document_request_id,
                upload=cast("UploadedFile", serializer.validated_data["document"]),
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            )
        except (ObjectDoesNotExist, DjangoValidationError) as error:
            raise ApiValidationError(
                {
                    "detail": "The onboarding document could not be uploaded.",
                    "code": "onboarding_document_invalid",
                }
            ) from error
        return Response(
            OnboardingDocumentRequestSerializer(
                instance=_document_payload(item),
            ).data
        )
