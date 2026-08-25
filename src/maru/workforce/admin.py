"""Bootstrap administration for workforce structure and reviewed evidence."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, cast, override
from uuid import UUID

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from maru.events.admin_context import EditionContextAdmin
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.workforce.edition_write_scope import (
    LockedWorkforceEditionWriteScope,
    lock_active_department_write_target,
    lock_workforce_edition_write_scope,
)
from maru.workforce.models import (
    Department,
    OnboardingDocumentRequest,
    OnboardingDocumentType,
    PersonAvailabilityCommandReceipt,
    PersonAvailabilityPlan,
    PersonAvailabilityWindow,
    Position,
    PositionAssignment,
    PositionAssignmentCommandReceipt,
    PositionTemplate,
    ShiftCommitment,
    ShiftCommitmentCommandReceipt,
    ShiftDemand,
    ShiftDemandCommandReceipt,
    VolunteerApplication,
    VolunteerOpportunity,
)
from maru.workforce.services import review_onboarding_document

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django import forms
    from django.http import HttpRequest
    from django.utils.safestring import SafeString


def _position_scope_reference(
    *,
    position: Position,
    change: bool,
) -> tuple[UUID, UUID, UUID, UUID]:
    """Resolve an identifier-only candidate scope before taking outer locks.

    Parameters
    ----------
    position : Position
        The workforce position within the exact edition structure.
    change : bool
        The change evaluated while position scope reference.

    Returns
    -------
    tuple[UUID, UUID, UUID, UUID]
        The matching position scope reference records in deterministic order.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    if change:
        row = (
            Position.objects.filter(id=position.id)
            .order_by()
            .values_list(
                "organization_id",
                "edition__series_id",
                "edition_id",
                "department_id",
            )
            .first()
        )
    else:
        edition_row = (
            EventEdition.objects.filter(id=position.edition_id)
            .order_by()
            .values_list("organization_id", "series_id", "id")
            .first()
        )
        row = (
            None
            if edition_row is None
            else (
                position.organization_id,
                edition_row[1],
                edition_row[2],
                position.department_id,
            )
        )
    if row is None or any(value is None for value in row):
        raise ValidationError(
            "The workforce Position target is unavailable.",
            code="workforce_position_unavailable",
        )
    return row


def _lock_position_admin_target(
    *,
    position: Position,
    change: bool,
) -> LockedWorkforceEditionWriteScope:
    organization_id, series_id, edition_id, department_id = _position_scope_reference(
        position=position, change=change
    )
    scope = lock_workforce_edition_write_scope(
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    lock_active_department_write_target(
        scope=scope,
        department_id=department_id,
    )
    if change:
        persisted = (
            Position.objects.select_for_update()
            .filter(id=position.id)
            .order_by()
            .values_list("organization_id", "edition_id", "department_id")
            .first()
        )
        if persisted is None or persisted != (
            scope.organization_id,
            scope.edition_id,
            department_id,
        ):
            raise ValidationError(
                "The workforce Position target is unavailable.",
                code="workforce_position_unavailable",
            )
        if (
            position.organization_id != scope.organization_id
            or position.edition_id != scope.edition_id
            or position.department_id != department_id
        ):
            raise ValidationError(
                "A bound workforce Position cannot move to another scope.",
                code="workforce_position_scope_immutable",
            )
    return scope


@admin.register(Department)
class DepartmentAdmin(EditionContextAdmin):
    """Inspection-only registry; Organization structure owns every mutation."""

    edition_context_lookup = "edition_id"
    list_display = ("name", "edition", "parent", "display_order")
    list_filter = ("organization", "edition")
    search_fields = ("name", "code", "edition__name")
    autocomplete_fields = ("organization", "edition", "parent")

    @override
    def has_add_permission(self, request: HttpRequest) -> bool:
        del request
        return False

    @override
    def has_change_permission(
        self,
        request: HttpRequest,
        obj: Department | None = None,
    ) -> bool:
        del request, obj
        return False

    @override
    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: Department | None = None,
    ) -> bool:
        del request, obj
        return False


@admin.register(PositionTemplate)
class PositionTemplateAdmin(EditionContextAdmin):
    """Configure Django administration for position template."""

    edition_context_lookup = "organization_id"
    edition_context_value_attribute = "organization_id"
    list_display = (
        "name",
        "organization",
        "version",
        "default_headcount",
        "role_bundle",
        "status",
    )
    list_filter = ("organization", "status")
    search_fields = ("name", "code", "description")
    autocomplete_fields = ("organization", "role_bundle", "created_by")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Position)
class PositionAdmin(EditionContextAdmin):
    """Inspection-only registry; the Workforce Position workflow owns writes."""

    edition_context_lookup = "edition_id"
    list_display = (
        "title",
        "department",
        "reports_to",
        "headcount",
        "active_count",
        "status",
        "application_state",
    )
    list_filter = ("organization", "edition", "department", "status")
    search_fields = ("title", "code", "description")
    autocomplete_fields = (
        "organization",
        "edition",
        "template",
        "department",
        "reports_to",
        "role_bundle",
        "created_by",
    )

    @admin.display(description="Assigned")
    def active_count(self, obj: Position) -> str:
        """Return the number of active related records.

        Parameters
        ----------
        obj : Position
            The model instance being validated or presented.

        Returns
        -------
        str
            The normalized text for active count.
        """
        count = obj.assignments.filter(status=PositionAssignment.Status.ACTIVE).count()
        return f"{count} / {obj.headcount}"

    @admin.display(description="Applications")
    def application_state(self, obj: Position) -> str:
        """Return the application's current lifecycle state.

        Parameters
        ----------
        obj : Position
            The model instance being validated or presented.

        Returns
        -------
        str
            The normalized text for application state.
        """
        opportunity = obj.opportunity
        if opportunity.status == VolunteerOpportunity.Status.PUBLISHED:
            return (
                "Published · accepting"
                if opportunity.accepts_applications
                else "Published · visible, not accepting"
            )
        return opportunity.get_status_display()

    @override
    def has_add_permission(self, request: HttpRequest) -> bool:
        del request
        return False

    @override
    def has_change_permission(
        self,
        request: HttpRequest,
        obj: Position | None = None,
    ) -> bool:
        del request, obj
        return False

    @override
    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: Position | None = None,
    ) -> bool:
        del request, obj
        return False


@admin.register(OnboardingDocumentType)
class OnboardingDocumentTypeAdmin(EditionContextAdmin):
    """Configure Django administration for onboarding document type."""

    edition_context_lookup = "edition_id"
    list_display = ("name", "edition", "version", "status", "max_bytes")
    list_filter = ("organization", "edition", "status")
    search_fields = ("name", "code", "description")
    autocomplete_fields = ("organization", "edition", "created_by")
    prepopulated_fields: ClassVar[dict[str, Sequence[str]]] = {"code": ("name",)}

    @override
    def save_model(
        self,
        request: HttpRequest,
        obj: OnboardingDocumentType,
        form: forms.ModelForm,  # type: ignore[type-arg]
        change: bool,
    ) -> None:
        _ = form, change
        if not obj.created_by_id and isinstance(request.user, Account):
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(OnboardingDocumentRequest)
class OnboardingDocumentRequestAdmin(EditionContextAdmin):
    """Configure Django administration for onboarding document request."""

    edition_context_lookup = "edition_id"
    list_display = (
        "account",
        "document_type",
        "edition",
        "status",
        "due_at",
        "submitted_at",
        "reviewed_at",
    )
    list_filter = ("organization", "edition", "status", "document_type")
    search_fields = (
        "account__display_name",
        "account__email",
        "document_type__name",
        "document_type__code",
    )
    autocomplete_fields = (
        "organization",
        "edition",
        "document_type",
        "account",
    )
    readonly_fields = (
        "requested_by",
        "requested_at",
        "document_download",
        "original_filename",
        "content_type",
        "byte_count",
        "sha256",
        "scanner_code",
        "submitted_at",
        "reviewed_by",
        "reviewed_at",
        "id",
        "created_at",
        "updated_at",
    )
    fields = (
        "organization",
        "edition",
        "document_type",
        "account",
        "status",
        "instructions",
        "due_at",
        "requested_by",
        "requested_at",
        "document_download",
        "original_filename",
        "content_type",
        "byte_count",
        "sha256",
        "scanner_code",
        "submitted_at",
        "review_reason",
        "reviewed_by",
        "reviewed_at",
        "id",
        "created_at",
        "updated_at",
    )

    @admin.display(description="Protected submitted file")
    def document_download(self, obj: OnboardingDocumentRequest) -> SafeString | str:
        """Return a protected onboarding-document download response.

        Parameters
        ----------
        obj : OnboardingDocumentRequest
            The model instance being validated or presented.

        Returns
        -------
        SafeString | str
            Escaped HTML safe for rendering document download.
        """
        if not obj.id or not obj.document:
            return "No document submitted"
        return format_html(
            '<a href="{}">Open submitted PDF through access control</a>',
            reverse("workforce-document-download", args=(obj.id,)),
        )

    @override
    def save_model(
        self,
        request: HttpRequest,
        obj: OnboardingDocumentRequest,
        form: forms.ModelForm,  # type: ignore[type-arg]
        change: bool,
    ) -> None:
        account = cast("Account", request.user)
        if not change:
            obj.requested_by = account
            obj.requested_at = timezone.now()
            obj.status = OnboardingDocumentRequest.Status.REQUESTED
            super().save_model(request, obj, form, change)
            return
        previous = OnboardingDocumentRequest.objects.get(id=obj.id)
        if (
            previous.status == OnboardingDocumentRequest.Status.SUBMITTED
            and obj.status
            in {
                OnboardingDocumentRequest.Status.APPROVED,
                OnboardingDocumentRequest.Status.REJECTED,
            }
        ):
            reviewed = review_onboarding_document(
                actor=account,
                request_id=obj.id,
                decision=obj.status,
                reason=obj.review_reason,
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            )
            obj.__dict__.update(reviewed.__dict__)
            return
        if previous.status == OnboardingDocumentRequest.Status.APPROVED:
            obj.__dict__.update(previous.__dict__)
            return
        obj.status = previous.status
        super().save_model(request, obj, form, change)


@admin.register(PositionAssignment)
class PositionAssignmentAdmin(EditionContextAdmin):
    """Inspect retained records; the purpose-built assignment journey owns writes."""

    edition_context_lookup = "edition_id"
    list_display = (
        "account",
        "position",
        "edition",
        "status",
        "effective_from",
        "expires_at",
        "approved_by",
    )
    list_filter = ("organization", "edition", "status", "position")
    search_fields = (
        "account__display_name",
        "account__email",
        "position__title",
        "position__code",
    )
    readonly_fields = (
        "position",
        "organization",
        "edition",
        "account",
        "status",
        "effective_from",
        "expires_at",
        "proposed_by",
        "approved_by",
        "reason",
        "command_version",
        "decision_by",
        "decision_at",
        "decision_reason",
        "role_assignment",
        "participation_capacity",
        "ended_at",
        "ended_by",
        "end_reason",
        "id",
        "created_at",
        "updated_at",
    )

    @override
    def has_add_permission(self, request: HttpRequest) -> bool:
        del request
        return False

    @override
    def has_change_permission(
        self,
        request: HttpRequest,
        obj: PositionAssignment | None = None,
    ) -> bool:
        del request, obj
        return False

    @override
    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: PositionAssignment | None = None,
    ) -> bool:
        del request, obj
        return False


@admin.register(PositionAssignmentCommandReceipt)
class PositionAssignmentCommandReceiptAdmin(EditionContextAdmin):
    """Inspect immutable assignment command evidence without offering writes."""

    edition_context_lookup = "edition_id"
    list_display = (
        "assignment",
        "action",
        "resulting_version",
        "actor",
        "edition",
        "created_at",
    )
    list_filter = ("organization", "edition", "action")
    search_fields = ("assignment__position__title", "actor__display_name", "reason")
    readonly_fields = (
        "assignment",
        "organization",
        "edition",
        "position",
        "actor",
        "action",
        "resulting_version",
        "reason",
        "retry_key",
        "request_digest",
        "correlation_id",
        "source_channel",
        "id",
        "created_at",
        "updated_at",
    )

    @override
    def has_add_permission(self, request: HttpRequest) -> bool:
        del request
        return False

    @override
    def has_change_permission(
        self,
        request: HttpRequest,
        obj: PositionAssignmentCommandReceipt | None = None,
    ) -> bool:
        del request, obj
        return False

    @override
    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: PositionAssignmentCommandReceipt | None = None,
    ) -> bool:
        del request, obj
        return False


class _AvailabilityReadOnlyAdmin(EditionContextAdmin):
    """Keep Availability storage inspectable but outside ordinary write paths."""

    @override
    def has_add_permission(self, request: HttpRequest) -> bool:
        del request
        return False

    @override
    def has_change_permission(self, request: HttpRequest, obj: object = None) -> bool:
        del request, obj
        return False

    @override
    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        del request, obj
        return False


@admin.register(PersonAvailabilityPlan)
class PersonAvailabilityPlanAdmin(_AvailabilityReadOnlyAdmin):
    """Inspect current plan state without offering organizer edits."""

    edition_context_lookup = "edition_id"
    list_display = (
        "account",
        "edition",
        "status",
        "window_count",
        "command_version",
        "updated_at",
    )
    list_filter = ("organization", "edition", "status")
    search_fields = ("account__display_name",)
    readonly_fields = (
        "organization",
        "edition",
        "account",
        "status",
        "time_zone",
        "command_version",
        "window_count",
        "window_set_digest",
        "submitted_at",
        "withdrawn_at",
        "id",
        "created_at",
        "updated_at",
    )


@admin.register(PersonAvailabilityWindow)
class PersonAvailabilityWindowAdmin(_AvailabilityReadOnlyAdmin):
    """Inspect exact current periods only through specialist administration."""

    edition_context_lookup = "plan__edition_id"
    list_display = (
        "plan",
        "starts_at",
        "ends_at",
        "preference",
        "created_by_version",
    )
    list_filter = ("plan__organization", "plan__edition", "preference")
    search_fields = ("plan__account__display_name",)
    readonly_fields = (
        "plan",
        "starts_at",
        "ends_at",
        "preference",
        "created_by_version",
        "id",
        "created_at",
        "updated_at",
    )


@admin.register(PersonAvailabilityCommandReceipt)
class PersonAvailabilityCommandReceiptAdmin(_AvailabilityReadOnlyAdmin):
    """Inspect minimized immutable Availability command evidence."""

    edition_context_lookup = "edition_id"
    list_display = (
        "plan",
        "action",
        "resulting_version",
        "window_count",
        "actor",
        "created_at",
    )
    list_filter = ("organization", "edition", "action")
    search_fields = ("actor__display_name",)
    readonly_fields = (
        "plan",
        "organization",
        "edition",
        "actor",
        "action",
        "resulting_version",
        "resulting_status",
        "window_count",
        "window_set_digest",
        "retry_key",
        "request_digest",
        "correlation_id",
        "source_channel",
        "id",
        "created_at",
        "updated_at",
    )


@admin.register(ShiftDemand)
class ShiftDemandAdmin(_AvailabilityReadOnlyAdmin):
    """Inspect governed Shift demand outside its purpose-built workflow."""

    edition_context_lookup = "edition_id"
    list_display = (
        "title",
        "position",
        "edition",
        "starts_at",
        "required_headcount",
        "status",
        "command_version",
    )
    list_filter = ("organization", "edition", "status", "position")
    search_fields = ("title", "location_label", "position__title")
    readonly_fields = tuple(
        field.name
        for field in ShiftDemand._meta.concrete_fields  # noqa: SLF001
    )


@admin.register(ShiftDemandCommandReceipt)
class ShiftDemandCommandReceiptAdmin(_AvailabilityReadOnlyAdmin):
    """Inspect immutable Shift-demand command evidence."""

    edition_context_lookup = "edition_id"
    list_display = (
        "demand",
        "action",
        "resulting_version",
        "actor",
        "created_at",
    )
    list_filter = ("organization", "edition", "action")
    search_fields = ("demand__title", "actor__display_name", "reason")
    readonly_fields = tuple(
        field.name
        for field in ShiftDemandCommandReceipt._meta.concrete_fields  # noqa: SLF001
    )


@admin.register(ShiftCommitment)
class ShiftCommitmentAdmin(_AvailabilityReadOnlyAdmin):
    """Inspect retained Shift claims and confirmations without offering writes."""

    edition_context_lookup = "edition_id"
    list_display = (
        "account",
        "demand",
        "edition",
        "status",
        "starts_at",
        "command_version",
    )
    list_filter = ("organization", "edition", "status", "demand")
    search_fields = ("account__display_name", "demand__title")
    readonly_fields = tuple(
        field.name
        for field in ShiftCommitment._meta.concrete_fields  # noqa: SLF001
    )


@admin.register(ShiftCommitmentCommandReceipt)
class ShiftCommitmentCommandReceiptAdmin(_AvailabilityReadOnlyAdmin):
    """Inspect immutable Shift-commitment command evidence."""

    edition_context_lookup = "edition_id"
    list_display = (
        "commitment",
        "action",
        "resulting_version",
        "actor",
        "created_at",
    )
    list_filter = ("organization", "edition", "action")
    search_fields = (
        "commitment__demand__title",
        "actor__display_name",
        "reason",
    )
    readonly_fields = tuple(
        field.name
        for field in ShiftCommitmentCommandReceipt._meta.concrete_fields  # noqa: SLF001
    )


@admin.register(VolunteerOpportunity)
class VolunteerOpportunityAdmin(EditionContextAdmin):
    """Inspection-only registry; the Position workflow owns publication."""

    edition_context_lookup = "position__edition_id"
    list_display = (
        "position",
        "status",
        "is_filled",
        "accepts_applications",
        "visible_when_filled",
    )
    list_filter = ("status", "visible_when_filled", "position__edition")
    search_fields = ("position__title", "headline", "description")

    @override
    def has_add_permission(self, request: HttpRequest) -> bool:
        del request
        return False

    @override
    def has_change_permission(
        self,
        request: HttpRequest,
        obj: VolunteerOpportunity | None = None,
    ) -> bool:
        del request, obj
        return False

    @override
    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: VolunteerOpportunity | None = None,
    ) -> bool:
        del request, obj
        return False


@admin.register(VolunteerApplication)
class VolunteerApplicationAdmin(EditionContextAdmin):
    """Configure Django administration for volunteer application."""

    edition_context_lookup = "opportunity__position__edition_id"
    list_display = (
        "account",
        "opportunity",
        "status",
        "submitted_at",
        "reviewed_by",
        "reviewed_at",
    )
    list_filter = (
        "status",
        "opportunity__position__edition",
        "opportunity__position",
    )
    search_fields = (
        "account__display_name",
        "account__email",
        "opportunity__position__title",
        "motivation",
    )
    readonly_fields = ("submitted_at",)
