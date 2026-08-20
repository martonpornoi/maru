"""Strict v1 HTTP adapters for typed application workflows."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Never, TypedDict, cast
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    PolymorphicProxySerializer,
    extend_schema,
)
from rest_framework import serializers, status
from rest_framework.exceptions import APIException, NotFound, PermissionDenied
from rest_framework.exceptions import ValidationError as ApiValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from maru.applications.commands import (
    ApplicationAuthorizationDenied,
    ApplicationCommandError,
    ApplicationCommandResult,
    ApplicationEligibilityDenied,
    ApplicationUnavailable,
    activate_definition,
    add_question,
    add_section,
    append_answer_revision,
    configure_definition,
    create_definition_from_starter,
    create_successor_definition,
    record_review_decision,
    retire_definition,
    start_submission,
    submit_application,
)
from maru.applications.queries import (
    authorize_application_edition_api_scope,
    authorize_application_review_submission_api_scope,
    authorize_application_self_api_scope,
    authorize_application_self_submission_api_scope,
    available_applications,
    definition_workspace,
    my_submissions,
    review_queue,
)
from maru.applications.serializers import (
    DEFINITION_COMMAND_SERIALIZERS,
    ApplicationCommandResultSerializer,
    ApplicationDefinitionSerializer,
    ApplicationReviewSubmissionProjectionSerializer,
    ApplicationStarterSummarySerializer,
    DefinitionConfigureSerializer,
    DefinitionLifecycleSerializer,
    DefinitionSuccessorSerializer,
    MyApplicationWorkspaceSerializer,
    QuestionAddSerializer,
    ReviewDecisionSerializer,
    SectionAddSerializer,
    StarterCreateSerializer,
    SubmissionAnswerSerializer,
    SubmissionTransitionSerializer,
    decision_history,
    latest_answers,
)
from maru.applications.starters import starter_catalog
from maru.audit.services import AuditRecord, append_audit
from maru.core.api_input import reject_unknown_fields
from maru.identity.models import Account

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal

    from rest_framework.request import Request

    from maru.applications.models import (
        ApplicationDefinition,
        ApplicationQuestion,
        ApplicationSubmission,
    )

IDEMPOTENCY_HEADER = "Idempotency-Key"
CANONICAL_UUID_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}$"
)

_APPLICATION_IDEMPOTENCY_PARAMETER = OpenApiParameter(
    name=IDEMPOTENCY_HEADER,
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.HEADER,
    required=True,
    pattern=CANONICAL_UUID_PATTERN,
    description=(
        "Canonical lower-case UUID. An exact same-intent retry recovers the "
        "original command result."
    ),
)

_APPLICATION_DEFINITION_COMMAND_REQUEST = PolymorphicProxySerializer(
    component_name="ApplicationDefinitionCommandRequest",
    serializers={
        "definition.configure": DefinitionConfigureSerializer,
        "section.add": SectionAddSerializer,
        "question.add": QuestionAddSerializer,
        "definition.activate": DefinitionLifecycleSerializer,
        "definition.retire": DefinitionLifecycleSerializer,
        "definition.successor": DefinitionSuccessorSerializer,
    },
    resource_type_field_name="operation",
)


class _DefinitionConfigurePayload(TypedDict):
    expected_version: int
    name: str
    description: str
    purpose: str
    classification: str
    eligibility_kind: str
    maximum_submissions: int
    opens_at: datetime
    closes_at: datetime
    applicant_edit_until: datetime
    minimum_age: int
    audience_policy_code: str
    retention_policy_code: str
    age_policy_code: str
    owner_department_ids: list[UUID]
    reviewer_role_bundle_ids: list[UUID]
    reviewer_account_ids: list[UUID]
    reason: str


class _SectionAddPayload(TypedDict):
    expected_version: int
    key: str
    title: str
    help_text: str
    reason: str


class _QuestionAddPayload(TypedDict):
    expected_version: int
    section_id: UUID
    key: str
    field_type: str
    label: str
    help_text: str
    required: bool
    options: list[dict[str, str]]
    minimum_length: int | None
    maximum_length: int | None
    minimum_value: Decimal | None
    maximum_value: Decimal | None
    maximum_choices: int | None
    reference_kind: str
    condition: dict[str, object]
    purpose: str
    classification: str
    applicant_visible: bool
    applicant_writable: bool
    staff_visible: bool
    staff_writable: bool
    reviewer_visible: bool
    public_after_approval: bool
    api_projection: bool
    retention_policy_code: str
    reason: str


class _DefinitionLifecyclePayload(TypedDict):
    expected_version: int
    reason: str


class _DefinitionSuccessorPayload(TypedDict):
    reason: str


class ApplicationConflict(APIException):
    """Signal application conflict."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "The application workflow changed; reload before retrying."
    default_code = "application_conflict"


def _actor(request: Request) -> Account:
    if not isinstance(request.user, Account) or not request.user.is_authenticated:
        raise PermissionDenied("Applications are unavailable.")
    return request.user


def _preauthorize_edition(
    request: Request,
    *,
    organization_id: UUID,
    edition_id: UUID,
    capability_code: str,
) -> Account:
    actor = _actor(request)
    try:
        authorize_application_edition_api_scope(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=capability_code,
        )
    except Exception as error:  # noqa: BLE001
        _failure(error)
    return actor


def _preauthorize_self(
    request: Request,
    *,
    organization_id: UUID,
    edition_id: UUID,
    capability_code: str,
) -> Account:
    actor = _actor(request)
    try:
        authorize_application_self_api_scope(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=capability_code,
        )
    except Exception as error:  # noqa: BLE001
        _failure(error)
    return actor


def _preauthorize_self_submission(
    request: Request,
    *,
    organization_id: UUID,
    edition_id: UUID,
    submission_id: UUID,
) -> Account:
    actor = _actor(request)
    try:
        authorize_application_self_submission_api_scope(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            submission_id=submission_id,
        )
    except Exception as error:  # noqa: BLE001
        _failure(error)
    return actor


def _preauthorize_review_submission(
    request: Request,
    *,
    organization_id: UUID,
    edition_id: UUID,
    submission_id: UUID,
) -> Account:
    actor = _actor(request)
    try:
        authorize_application_review_submission_api_scope(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            submission_id=submission_id,
        )
    except Exception as error:  # noqa: BLE001
        _failure(error)
    return actor


def _correlation(request: Request) -> UUID:
    return UUID(request._request.correlation_id)  # type: ignore[attr-defined]  # noqa: SLF001


def _retry_key(request: Request) -> UUID:
    raw = request.headers.get(IDEMPOTENCY_HEADER)
    try:
        value = UUID(raw or "")
    except ValueError:
        value = None
    if value is None or raw != str(value):
        raise ApiValidationError(
            {IDEMPOTENCY_HEADER: ["Provide one canonical lower-case UUID."]},
            code="invalid_idempotency_key",
        )
    return value


def _audit_workspace_read(
    *,
    request: Request,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    capability_code: str,
    operation: str,
    record_count: int,
) -> None:
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code=capability_code,
            operation=operation,
            target_type="applications.edition_workspace",
            target_id=edition_id,
            outcome="allow",
            reason_code="applications_workspace_read",
            correlation_id=_correlation(request),
            source_channel="api",
            obligations=("audit_sensitive_read",),
            safe_metadata={"target_count": record_count},
        )
    )


def _validated(
    request: Request,
    serializer_class: type[serializers.Serializer[dict[str, Any]]],
) -> dict[str, Any]:
    reject_unknown_fields(request.query_params, allowed_fields=frozenset())
    serializer = serializer_class(data=request.data)
    reject_unknown_fields(request.data, allowed_fields=frozenset(serializer.fields))
    serializer.is_valid(raise_exception=True)
    return cast("dict[str, Any]", serializer.validated_data)


def _failure(error: Exception) -> Never:
    if isinstance(error, ApplicationAuthorizationDenied):
        raise PermissionDenied(
            "Applications are unavailable.", code=error.reason_code
        ) from error
    if isinstance(error, ApplicationUnavailable):
        raise NotFound(
            "Applications are unavailable.", code=error.reason_code
        ) from error
    if isinstance(error, ApplicationEligibilityDenied):
        raise PermissionDenied(
            "This application is not available to this account.", code=error.reason_code
        ) from error
    if isinstance(error, DjangoValidationError):
        if hasattr(error, "message_dict"):
            raise ApiValidationError(error.message_dict) from error
        raise ApiValidationError(error.messages) from error
    if isinstance(error, ApplicationCommandError):
        raise ApplicationConflict(code=error.reason_code) from error
    raise error


def _result_response(
    result: ApplicationCommandResult, *, created: bool = False
) -> Response:
    data = {
        "receipt_id": str(result.receipt_id),
        "definition_id": str(result.definition_id) if result.definition_id else None,
        "submission_id": str(result.submission_id) if result.submission_id else None,
        "target_id": str(result.target_id) if result.target_id else None,
        "resulting_version": result.resulting_version,
    }
    response = Response(
        data,
        status=status.HTTP_201_CREATED
        if created and not result.replayed
        else status.HTTP_200_OK,
    )
    response["Idempotent-Replay"] = "true" if result.replayed else "false"
    return response


def _question_data(
    question: ApplicationQuestion, *, applicant: bool
) -> dict[str, object]:
    data = {
        "id": str(question.id),
        "key": question.key,
        "field_type": question.field_type,
        "label": question.label,
        "help_text": question.help_text,
        "required": question.required,
        "options": question.options,
        "minimum_length": question.minimum_length,
        "maximum_length": question.maximum_length,
        "minimum_value": question.minimum_value,
        "maximum_value": question.maximum_value,
        "maximum_choices": question.maximum_choices,
        "condition": question.condition,
        "applicant_writable": question.applicant_writable,
        "source_binding": question.source_binding,
    }
    if not applicant:
        data.update(
            purpose=question.purpose,
            classification=question.classification,
            applicant_visible=question.applicant_visible,
            staff_visible=question.staff_visible,
            staff_writable=question.staff_writable,
            reviewer_visible=question.reviewer_visible,
            public_after_approval=question.public_after_approval,
            api_projection=question.api_projection,
            retention_policy_code=question.retention_policy_code,
        )
    return data


def _definition_data(
    definition: ApplicationDefinition, *, applicant: bool
) -> dict[str, object]:
    sections = []
    for section in definition.sections.all():
        questions = [
            _question_data(question, applicant=applicant)
            for question in section.questions.all()
            if not applicant or question.applicant_visible
        ]
        sections.append(
            {
                "id": str(section.id),
                "key": section.key,
                "title": section.title,
                "help_text": section.help_text,
                "questions": questions,
            }
        )
    result: dict[str, object] = {
        "id": str(definition.id),
        "code": definition.code,
        "version": definition.version,
        "aggregate_version": definition.aggregate_version,
        "status": definition.status,
        "target_adapter_kind": definition.target_adapter_kind,
        "name": definition.name,
        "description": definition.description,
        "purpose": definition.purpose,
        "eligibility_kind": definition.eligibility_kind,
        "maximum_submissions": definition.max_submissions_per_person,
        "opens_at": definition.opens_at,
        "closes_at": definition.closes_at,
        "applicant_edit_until": definition.applicant_edit_until,
        "minimum_age": definition.minimum_age,
        "sections": sections,
    }
    if not applicant:
        result.update(
            classification=definition.classification,
            audience_policy_code=definition.audience_policy_code,
            retention_policy_code=definition.retention_policy_code,
            age_policy_code=definition.age_policy_code,
            owner_departments=[
                {"id": str(link.department_id), "name": link.department.name}
                for link in definition.owner_department_links.all()
            ],
            reviewer_roles=[
                {
                    "id": str(link.role_bundle_id),
                    "name": link.role_bundle.name,
                    "version": link.role_bundle.version,
                }
                for link in definition.reviewer_roles.all()
            ],
            reviewer_people=[
                {"id": str(link.account_id), "display_name": link.account.display_name}
                for link in definition.reviewer_people.all()
            ],
        )
    return result


def _submission_data(
    submission: ApplicationSubmission, *, reviewer: bool = False
) -> dict[str, object]:
    result: dict[str, object] = {
        "id": str(submission.id),
        "definition_id": str(submission.definition_id),
        "definition_name": submission.definition.name,
        "definition_version": submission.definition.version,
        "target_adapter_kind": submission.definition.target_adapter_kind,
        "ordinal": submission.ordinal,
        "state": submission.state,
        "aggregate_version": submission.aggregate_version,
        "submitted_at": submission.submitted_at,
        "decided_at": submission.decided_at,
        "answers": latest_answers(
            submission, audience="reviewer" if reviewer else "applicant"
        ),
        "decisions": decision_history(submission),
    }
    if reviewer:
        result["applicant"] = {
            "id": str(submission.account_id),
            "display_name": submission.account.display_name,
        }
    return result


@method_decorator(never_cache, name="dispatch")
class PrivateApplicationsAPIView(APIView):
    """Keep authenticated application data and safe errors out of shared caches."""


class ApplicationStarterCatalogView(PrivateApplicationsAPIView):
    """Expose application starter catalog through the HTTP API."""

    @extend_schema(
        operation_id="applications_list_starters",
        responses={200: ApplicationStarterSummarySerializer(many=True)},
    )
    def get(
        self, request: Request, organization_id: UUID, edition_id: UUID
    ) -> Response:
        """List the starters.

        Keep authenticated application data and safe errors out of shared caches.

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
        try:
            definition_workspace(
                actor=_actor(request),
                organization_id=organization_id,
                edition_id=edition_id,
            )
        except Exception as error:  # noqa: BLE001
            _failure(error)
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        return Response(
            [
                {
                    "code": starter.code,
                    "name": starter.name,
                    "description": starter.description,
                    "owner_module": starter.owner_module,
                    "target_adapter_kind": starter.target_adapter_kind,
                    "classification": starter.classification,
                    "requires_local_policy": not bool(
                        starter.audience_policy_code and starter.retention_policy_code
                    ),
                }
                for starter in starter_catalog()
            ]
        )


class ApplicationDefinitionCollectionView(PrivateApplicationsAPIView):
    """Expose application definition collection through the HTTP API."""

    @extend_schema(
        operation_id="applications_list_definitions",
        responses={200: ApplicationDefinitionSerializer(many=True)},
    )
    def get(
        self, request: Request, organization_id: UUID, edition_id: UUID
    ) -> Response:
        """List the definitions.

        Keep authenticated application data and safe errors out of shared caches.

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
        try:
            definitions = definition_workspace(
                actor=_actor(request),
                organization_id=organization_id,
                edition_id=edition_id,
            )
        except Exception as error:  # noqa: BLE001
            _failure(error)
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        return Response(
            [
                _definition_data(definition, applicant=False)
                for definition in definitions
            ]
        )

    @extend_schema(
        operation_id="applications_create_definition",
        parameters=[_APPLICATION_IDEMPOTENCY_PARAMETER],
        request=StarterCreateSerializer,
        responses={
            200: ApplicationCommandResultSerializer,
            201: ApplicationCommandResultSerializer,
        },
    )
    def post(
        self, request: Request, organization_id: UUID, edition_id: UUID
    ) -> Response:
        """Create the definition.

        Keep authenticated application data and safe errors out of shared caches.

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
        _preauthorize_edition(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code="applications.manage_definitions",
        )
        payload = _validated(request, StarterCreateSerializer)
        try:
            result = create_definition_from_starter(
                actor=_actor(request),
                organization_id=organization_id,
                edition_id=edition_id,
                retry_key=_retry_key(request),
                correlation_id=_correlation(request),
                source_channel="api",
                **payload,
            )
        except Exception as error:  # noqa: BLE001
            _failure(error)
        return _result_response(result, created=True)


class ApplicationDefinitionCommandView(PrivateApplicationsAPIView):
    """Expose application definition command through the HTTP API."""

    @extend_schema(
        operation_id="applications_command_definition",
        parameters=[_APPLICATION_IDEMPOTENCY_PARAMETER],
        request=_APPLICATION_DEFINITION_COMMAND_REQUEST,
        responses={
            200: ApplicationCommandResultSerializer,
            201: ApplicationCommandResultSerializer,
        },
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        definition_id: UUID,
    ) -> Response:
        """Apply the requested application-definition command.

        Keep authenticated application data and safe errors out of shared caches.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.
        edition_id : UUID
            The event edition identifier that scopes the operation.
        definition_id : UUID
            The definition identifier within the requested scope.

        Returns
        -------
        Response
            The HTTP response for the requested operation.

        Raises
        ------
        ApiValidationError
            If the request payload violates the endpoint contract.
        """
        _preauthorize_edition(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code="applications.manage_definitions",
        )
        if not isinstance(request.data, Mapping):
            raise ApiValidationError("The command body must be an object.")
        operation = request.data.get("operation")
        serializer_class = (
            DEFINITION_COMMAND_SERIALIZERS.get(operation)
            if isinstance(operation, str)
            else None
        )
        if serializer_class is None:
            raise ApiValidationError(
                {"operation": ["Choose one documented operation."]}
            )
        payload = _validated(request, serializer_class)
        payload.pop("operation")
        actor = _actor(request)
        retry_key = _retry_key(request)
        correlation_id = _correlation(request)
        try:
            if operation == "definition.configure":
                result = configure_definition(
                    actor=actor,
                    organization_id=organization_id,
                    edition_id=edition_id,
                    definition_id=definition_id,
                    retry_key=retry_key,
                    correlation_id=correlation_id,
                    source_channel="api",
                    **cast("_DefinitionConfigurePayload", payload),
                )
            elif operation == "section.add":
                result = add_section(
                    actor=actor,
                    organization_id=organization_id,
                    edition_id=edition_id,
                    definition_id=definition_id,
                    retry_key=retry_key,
                    correlation_id=correlation_id,
                    source_channel="api",
                    **cast("_SectionAddPayload", payload),
                )
            elif operation == "question.add":
                result = add_question(
                    actor=actor,
                    organization_id=organization_id,
                    edition_id=edition_id,
                    definition_id=definition_id,
                    retry_key=retry_key,
                    correlation_id=correlation_id,
                    source_channel="api",
                    **cast("_QuestionAddPayload", payload),
                )
            elif operation == "definition.activate":
                result = activate_definition(
                    actor=actor,
                    organization_id=organization_id,
                    edition_id=edition_id,
                    definition_id=definition_id,
                    retry_key=retry_key,
                    correlation_id=correlation_id,
                    source_channel="api",
                    **cast("_DefinitionLifecyclePayload", payload),
                )
            elif operation == "definition.retire":
                result = retire_definition(
                    actor=actor,
                    organization_id=organization_id,
                    edition_id=edition_id,
                    definition_id=definition_id,
                    retry_key=retry_key,
                    correlation_id=correlation_id,
                    source_channel="api",
                    **cast("_DefinitionLifecyclePayload", payload),
                )
            else:
                result = create_successor_definition(
                    actor=actor,
                    organization_id=organization_id,
                    edition_id=edition_id,
                    definition_id=definition_id,
                    retry_key=retry_key,
                    correlation_id=correlation_id,
                    source_channel="api",
                    **cast("_DefinitionSuccessorPayload", payload),
                )
        except Exception as error:  # noqa: BLE001
            _failure(error)
        return _result_response(
            result,
            created=operation
            in {"section.add", "question.add", "definition.successor"},
        )


class MyApplicationWorkspaceView(PrivateApplicationsAPIView):
    """Expose my application workspace through the HTTP API."""

    @extend_schema(
        operation_id="applications_retrieve_my_workspace",
        responses={200: MyApplicationWorkspaceSerializer},
    )
    def get(
        self, request: Request, organization_id: UUID, edition_id: UUID
    ) -> Response:
        """Retrieve my workspace.

        Keep authenticated application data and safe errors out of shared caches.

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
        actor = _actor(request)
        try:
            available = available_applications(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
            )
            submissions = my_submissions(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
            )
        except Exception as error:  # noqa: BLE001
            _failure(error)
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        _audit_workspace_read(
            request=request,
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code="applications.view_self",
            operation="applications.self_workspace.read",
            record_count=len(available) + len(submissions),
        )
        return Response(
            {
                "available": [
                    _definition_data(item, applicant=True) for item in available
                ],
                "submissions": [_submission_data(item) for item in submissions],
            }
        )


class ApplicationSubmissionCreateView(PrivateApplicationsAPIView):
    """Expose application submission create through the HTTP API."""

    @extend_schema(
        operation_id="applications_start_submission",
        parameters=[_APPLICATION_IDEMPOTENCY_PARAMETER],
        request=None,
        responses={
            200: ApplicationCommandResultSerializer,
            201: ApplicationCommandResultSerializer,
        },
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        definition_id: UUID,
    ) -> Response:
        """Start the submission.

        Keep authenticated application data and safe errors out of shared caches.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.
        edition_id : UUID
            The event edition identifier that scopes the operation.
        definition_id : UUID
            The definition identifier within the requested scope.

        Returns
        -------
        Response
            The HTTP response for the requested operation.
        """
        _preauthorize_self(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code="applications.apply_self",
        )
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        reject_unknown_fields(request.data, allowed_fields=frozenset())
        try:
            result = start_submission(
                actor=_actor(request),
                organization_id=organization_id,
                edition_id=edition_id,
                definition_id=definition_id,
                retry_key=_retry_key(request),
                correlation_id=_correlation(request),
                source_channel="api",
            )
        except Exception as error:  # noqa: BLE001
            _failure(error)
        return _result_response(result, created=True)


class ApplicationAnswerRevisionView(PrivateApplicationsAPIView):
    """Expose application answer revision through the HTTP API."""

    @extend_schema(
        operation_id="applications_append_answer",
        parameters=[_APPLICATION_IDEMPOTENCY_PARAMETER],
        request=SubmissionAnswerSerializer,
        responses={
            200: ApplicationCommandResultSerializer,
            201: ApplicationCommandResultSerializer,
        },
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        submission_id: UUID,
    ) -> Response:
        """Append the answer.

        Keep authenticated application data and safe errors out of shared caches.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.
        edition_id : UUID
            The event edition identifier that scopes the operation.
        submission_id : UUID
            The submission identifier within the requested scope.

        Returns
        -------
        Response
            The HTTP response for the requested operation.
        """
        _preauthorize_self_submission(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            submission_id=submission_id,
        )
        payload = _validated(request, SubmissionAnswerSerializer)
        try:
            result = append_answer_revision(
                actor=_actor(request),
                organization_id=organization_id,
                edition_id=edition_id,
                submission_id=submission_id,
                retry_key=_retry_key(request),
                correlation_id=_correlation(request),
                source_channel="api",
                **payload,
            )
        except Exception as error:  # noqa: BLE001
            _failure(error)
        return _result_response(result, created=True)


class ApplicationSubmitView(PrivateApplicationsAPIView):
    """Expose application submit through the HTTP API."""

    @extend_schema(
        operation_id="applications_submit_submission",
        parameters=[_APPLICATION_IDEMPOTENCY_PARAMETER],
        request=SubmissionTransitionSerializer,
        responses={200: ApplicationCommandResultSerializer},
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        submission_id: UUID,
    ) -> Response:
        """Submit the submission.

        Keep authenticated application data and safe errors out of shared caches.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.
        edition_id : UUID
            The event edition identifier that scopes the operation.
        submission_id : UUID
            The submission identifier within the requested scope.

        Returns
        -------
        Response
            The HTTP response for the requested operation.
        """
        _preauthorize_self_submission(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            submission_id=submission_id,
        )
        payload = _validated(request, SubmissionTransitionSerializer)
        try:
            result = submit_application(
                actor=_actor(request),
                organization_id=organization_id,
                edition_id=edition_id,
                submission_id=submission_id,
                retry_key=_retry_key(request),
                correlation_id=_correlation(request),
                source_channel="api",
                **payload,
            )
        except Exception as error:  # noqa: BLE001
            _failure(error)
        return _result_response(result)


class ApplicationReviewQueueView(PrivateApplicationsAPIView):
    """Expose application review queue through the HTTP API."""

    @extend_schema(
        operation_id="applications_list_review_queue",
        responses={
            200: ApplicationReviewSubmissionProjectionSerializer(many=True),
        },
    )
    def get(
        self, request: Request, organization_id: UUID, edition_id: UUID
    ) -> Response:
        """List the review queue.

        Keep authenticated application data and safe errors out of shared caches.

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
        actor = _actor(request)
        try:
            submissions = review_queue(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
            )
        except Exception as error:  # noqa: BLE001
            _failure(error)
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        _audit_workspace_read(
            request=request,
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code="applications.review",
            operation="applications.review_queue.read",
            record_count=len(submissions),
        )
        return Response([_submission_data(item, reviewer=True) for item in submissions])


class ApplicationReviewDecisionView(PrivateApplicationsAPIView):
    """Expose application review decision through the HTTP API."""

    @extend_schema(
        operation_id="applications_record_review_decision",
        parameters=[_APPLICATION_IDEMPOTENCY_PARAMETER],
        request=ReviewDecisionSerializer,
        responses={200: ApplicationCommandResultSerializer},
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        submission_id: UUID,
    ) -> Response:
        """Record the review decision.

        Keep authenticated application data and safe errors out of shared caches.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.
        edition_id : UUID
            The event edition identifier that scopes the operation.
        submission_id : UUID
            The submission identifier within the requested scope.

        Returns
        -------
        Response
            The HTTP response for the requested operation.
        """
        _preauthorize_review_submission(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            submission_id=submission_id,
        )
        payload = _validated(request, ReviewDecisionSerializer)
        try:
            result = record_review_decision(
                actor=_actor(request),
                organization_id=organization_id,
                edition_id=edition_id,
                submission_id=submission_id,
                retry_key=_retry_key(request),
                correlation_id=_correlation(request),
                source_channel="api",
                **payload,
            )
        except Exception as error:  # noqa: BLE001
            _failure(error)
        return _result_response(result)
