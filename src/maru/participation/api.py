"""Self-service and policy-scoped staff participation endpoints."""

from typing import cast
from uuid import UUID

from django.db.models import Prefetch, Q, QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.generics import GenericAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.enforcement import (
    FieldProjectionDeniedError,
    require_complete_projection,
)
from maru.authorization.policy import (
    PolicyDecision,
    decide,
    project_active_authority_scopes,
    resolve_edition_target,
)
from maru.core.pagination import StandardPageNumberPagination
from maru.events.adoption import adoption_profile
from maru.events.models import EventEdition
from maru.events.queries import platform_editions
from maru.identity.models import Account
from maru.organizations.queries import memberships_for_account
from maru.participation.models import Participation, ParticipationCapacity
from maru.participation.queries import (
    archived_participations_for_account,
    participations_for_account,
)
from maru.participation.serializers import (
    MyContextSerializer,
    ParticipationHistorySerializer,
    StaffParticipationListQuerySerializer,
    StaffParticipationSummarySerializer,
)

_FULL_DESTINATIONS = (
    "today",
    "my-registration",
    "people",
    "workforce",
    "commerce",
    "reports",
    "setup",
    "security",
)
_WORKFORCE_DESTINATIONS = ("today", "workforce", "setup", "security")


def _edition_context_payload(
    *,
    account: Account,
    edition: EventEdition,
    participation: Participation | None,
) -> dict[str, object]:
    """Build a purpose-bounded workspace without participation side effects.

    Parameters
    ----------
    account : Account
        The authenticated account viewing the edition workspace.
    edition : EventEdition
        The exact event edition whose product boundary is being rendered.
    participation : Participation | None
        Existing attendee participation, when that module is adopted.

    Returns
    -------
    dict[str, object]
        Disclosure-safe edition context and available destinations.

    Raises
    ------
    RuntimeError
        If the edition references an unsupported adoption profile.
    """
    profile = adoption_profile(edition.adoption_profile_code)
    if profile is None:
        raise RuntimeError("The event edition has an unsupported adoption profile.")
    return {
        "organization_id": edition.organization_id,
        "organization_slug": edition.organization.slug,
        "series_id": edition.series_id,
        "series_slug": edition.series.slug,
        "series_name": edition.series.name,
        "edition_id": edition.id,
        "edition_slug": edition.slug,
        "edition_name": edition.name,
        "lifecycle": edition.lifecycle,
        "adoption_profile_code": edition.adoption_profile_code,
        "adoption_profile_version": edition.adoption_profile_version,
        "adoption_profile_label": profile.label,
        "adopted_modules": sorted(profile.modules),
        "available_destinations": (
            _WORKFORCE_DESTINATIONS
            if edition.adoption_profile_code == "workforce_only"
            else _FULL_DESTINATIONS
        ),
        "time_zone": edition.time_zone,
        "language_codes": edition.language_codes,
        "currency_codes": edition.currency_codes,
        "starts_on": edition.starts_on,
        "ends_on": edition.ends_on,
        "participation_status": (
            participation.status if participation is not None else "not_participating"
        ),
        "capacities": (
            participation.capacities.all() if participation is not None else []
        ),
        "can_transition": decide(
            principal=account,
            capability_code="events.transition",
            resource=resolve_edition_target(
                organization_id=edition.organization_id,
                edition_id=edition.id,
            ),
        ).allowed,
    }


class MyContextView(APIView):
    """Expose my context through the HTTP API."""

    @extend_schema(
        operation_id="identity_retrieve_my_context",
        responses=MyContextSerializer,
    )
    def get(self, request: Request) -> Response:
        """Retrieve my context.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.

        Returns
        -------
        Response
            The HTTP response for the requested operation.

        Raises
        ------
        TypeError
            If the caller supplies an object of an unsupported type.
        """
        account = request.user
        if not isinstance(account, Account):
            raise TypeError("Authenticated principal is not a platform account")

        participation_by_edition = {
            participation.edition_id: participation
            for participation in participations_for_account(account)
        }
        if account.is_platform_administrator:
            edition_records = list(platform_editions())
            memberships: object = []
        else:
            authority_scopes = project_active_authority_scopes(principal=account)
            organization_ids = {
                scope.organization_id
                for scope in authority_scopes
                if scope.edition_id is None
                and scope.department_id is None
                and scope.resource_binding_id is None
                and "events.view_basic" in scope.capability_codes
            }
            edition_ids = {
                scope.edition_id
                for scope in authority_scopes
                if scope.edition_id is not None
                and "events.view_basic" in scope.capability_codes
            }
            edition_records = list(
                EventEdition.objects.filter(
                    Q(id__in=participation_by_edition)
                    | Q(id__in=edition_ids)
                    | Q(organization_id__in=organization_ids)
                )
                .select_related("organization", "series")
                .order_by("-starts_on", "name", "id")
            )
            memberships = memberships_for_account(account)

        editions = [
            _edition_context_payload(
                account=account,
                edition=edition,
                participation=participation_by_edition.get(edition.id),
            )
            for edition in edition_records
        ]

        payload = {
            "account_id": account.id,
            "display_name": account.display_name,
            "preferred_language": account.preferred_language,
            "can_access_advanced_records": account.is_staff,
            "memberships": memberships,
            "editions": editions,
        }
        serializer = MyContextSerializer(payload, context={"account": account})
        return Response(serializer.data)


class MyParticipationHistoryView(APIView):
    """Expose my participation history through the HTTP API."""

    @extend_schema(
        operation_id="participation_list_my_history",
        responses=ParticipationHistorySerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        """List my history.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.

        Returns
        -------
        Response
            The HTTP response for the requested operation.

        Raises
        ------
        TypeError
            If the caller supplies an object of an unsupported type.
        """
        account = request.user
        if not isinstance(account, Account):
            raise TypeError("Authenticated principal is not a platform account")

        serializer = ParticipationHistorySerializer(
            archived_participations_for_account(account),
            many=True,
        )
        return Response(serializer.data)


def _append_staff_participation_audit(
    *,
    account: Account,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    operation: str,
    target_type: str,
    target_id: UUID | None,
    outcome: str,
    reason_code: str,
    obligations: tuple[str, ...],
    target_count: int | None = None,
) -> None:
    safe_metadata: dict[str, object] = {"policy_version": POLICY_VERSION}
    if target_count is not None:
        safe_metadata["target_count"] = target_count
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=account.id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code="participation.view_staff_summary",
            operation=operation,
            target_type=target_type,
            target_id=target_id,
            outcome=outcome,
            reason_code=reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="api",
            obligations=obligations,
            safe_metadata=safe_metadata,
            retention_class="security-extended",
        )
    )


def _staff_summary_decision(
    *,
    account: Account,
    organization_id: UUID,
    edition_id: UUID,
) -> PolicyDecision:
    return decide(
        principal=account,
        capability_code="participation.view_staff_summary",
        resource=resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
        requested_fields=frozenset(StaffParticipationSummarySerializer.Meta.fields),
    )


def _staff_participations(
    *,
    organization_id: UUID,
    edition_id: UUID,
) -> QuerySet[Participation]:
    active_capacities = ParticipationCapacity.objects.filter(
        status__in=(
            ParticipationCapacity.Status.PROPOSED,
            ParticipationCapacity.Status.ACTIVE,
        )
    ).order_by("label_snapshot", "id")
    return (
        Participation.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .select_related("account")
        .prefetch_related(
            Prefetch("capacities", queryset=active_capacities),
        )
    )


class EditionParticipationListView(GenericAPIView[Participation]):
    """Expose edition participation list through the HTTP API."""

    serializer_class = StaffParticipationSummarySerializer
    pagination_class = StandardPageNumberPagination

    @extend_schema(
        operation_id="participation_list_staff_summaries",
        parameters=[StaffParticipationListQuerySerializer],
        responses=StaffParticipationSummarySerializer(many=True),
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        """List the staff summaries.

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
        RuntimeError
            If a required runtime invariant or dependency is unavailable.
        TypeError
            If the caller supplies an object of an unsupported type.
        """
        account = request.user
        if not isinstance(account, Account):
            raise TypeError("Authenticated principal is not a platform account")
        correlation_id = UUID(request.correlation_id)  # type: ignore[attr-defined]
        decision = _staff_summary_decision(
            account=account,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        obligations = tuple(sorted(decision.obligations))
        if not decision.allowed:
            _append_staff_participation_audit(
                account=account,
                organization_id=organization_id,
                edition_id=edition_id,
                correlation_id=correlation_id,
                operation="participation.staff_summary.list",
                target_type="participation.participation_set",
                target_id=None,
                outcome=AuditEvent.Outcome.DENY,
                reason_code=decision.reason_code,
                obligations=obligations,
            )
            raise PermissionDenied(
                "Staff participation summaries are unavailable.",
                code=decision.reason_code,
            )
        try:
            require_complete_projection(
                required_fields=frozenset(
                    StaffParticipationSummarySerializer.Meta.fields
                ),
                permitted_fields=decision.fields,
            )
        except FieldProjectionDeniedError as error:
            _append_staff_participation_audit(
                account=account,
                organization_id=organization_id,
                edition_id=edition_id,
                correlation_id=correlation_id,
                operation="participation.staff_summary.list",
                target_type="participation.participation_set",
                target_id=None,
                outcome=AuditEvent.Outcome.ERROR,
                reason_code="field_projection_denied",
                obligations=obligations,
            )
            raise PermissionDenied(
                "The permitted participation projection is incomplete.",
                code="field_projection_denied",
            ) from error

        query = StaffParticipationListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        values = query.validated_data
        participations = _staff_participations(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        if search := values.get("search"):
            participations = participations.filter(
                account__display_name__icontains=cast("str", search)
            )
        if status := values.get("status"):
            participations = participations.filter(status=cast("str", status))
        if capacity := values.get("capacity"):
            participations = participations.filter(
                Q(capacities__code=cast("str", capacity))
                | Q(capacities__label_snapshot__iexact=cast("str", capacity)),
                capacities__status__in=(
                    ParticipationCapacity.Status.PROPOSED,
                    ParticipationCapacity.Status.ACTIVE,
                ),
            )
        participations = participations.distinct().order_by(
            "account__display_name",
            "account_id",
        )
        page = self.paginate_queryset(participations)
        if page is None:
            raise RuntimeError("Participation list pagination is required.")
        serializer = self.get_serializer(page, many=True)
        _append_staff_participation_audit(
            account=account,
            organization_id=organization_id,
            edition_id=edition_id,
            correlation_id=correlation_id,
            operation="participation.staff_summary.list",
            target_type="participation.participation_set",
            target_id=None,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=decision.reason_code,
            obligations=obligations,
            target_count=len(page),
        )
        return self.get_paginated_response(serializer.data)


class EditionParticipationDetailView(APIView):
    """Expose edition participation detail through the HTTP API."""

    @extend_schema(
        operation_id="participation_retrieve_staff_summary",
        responses=StaffParticipationSummarySerializer,
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        account_id: UUID,
    ) -> Response:
        """Retrieve the staff summary.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.
        edition_id : UUID
            The event edition identifier that scopes the operation.
        account_id : UUID
            The platform account identifier within the requested scope.

        Returns
        -------
        Response
            The HTTP response for the requested operation.

        Raises
        ------
        NotFound
            If the scoped resource is unavailable to the caller.
        PermissionDenied
            If the caller lacks permission for the requested scope.
        TypeError
            If the caller supplies an object of an unsupported type.
        """
        account = request.user
        if not isinstance(account, Account):
            raise TypeError("Authenticated principal is not a platform account")
        correlation_id = UUID(request.correlation_id)  # type: ignore[attr-defined]
        decision = _staff_summary_decision(
            account=account,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        obligations = tuple(sorted(decision.obligations))
        if not decision.allowed:
            _append_staff_participation_audit(
                account=account,
                organization_id=organization_id,
                edition_id=edition_id,
                correlation_id=correlation_id,
                operation="participation.staff_summary.retrieve",
                target_type="identity.account",
                target_id=account_id,
                outcome=AuditEvent.Outcome.DENY,
                reason_code=decision.reason_code,
                obligations=obligations,
            )
            raise PermissionDenied(
                "The staff participation summary is unavailable.",
                code=decision.reason_code,
            )
        try:
            require_complete_projection(
                required_fields=frozenset(
                    StaffParticipationSummarySerializer.Meta.fields
                ),
                permitted_fields=decision.fields,
            )
        except FieldProjectionDeniedError as error:
            _append_staff_participation_audit(
                account=account,
                organization_id=organization_id,
                edition_id=edition_id,
                correlation_id=correlation_id,
                operation="participation.staff_summary.retrieve",
                target_type="identity.account",
                target_id=account_id,
                outcome=AuditEvent.Outcome.ERROR,
                reason_code="field_projection_denied",
                obligations=obligations,
            )
            raise PermissionDenied(
                "The permitted participation projection is incomplete.",
                code="field_projection_denied",
            ) from error

        participation = (
            _staff_participations(
                organization_id=organization_id,
                edition_id=edition_id,
            )
            .filter(account_id=account_id)
            .first()
        )
        if participation is None:
            _append_staff_participation_audit(
                account=account,
                organization_id=organization_id,
                edition_id=edition_id,
                correlation_id=correlation_id,
                operation="participation.staff_summary.retrieve",
                target_type="identity.account",
                target_id=account_id,
                outcome=AuditEvent.Outcome.ERROR,
                reason_code="participation_unavailable",
                obligations=obligations,
            )
            raise NotFound(
                "The staff participation summary is unavailable.",
                code="participation_unavailable",
            )
        serializer = StaffParticipationSummarySerializer(participation)
        _append_staff_participation_audit(
            account=account,
            organization_id=organization_id,
            edition_id=edition_id,
            correlation_id=correlation_id,
            operation="participation.staff_summary.retrieve",
            target_type="identity.account",
            target_id=account_id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=decision.reason_code,
            obligations=obligations,
            target_count=1,
        )
        return Response(serializer.data)
