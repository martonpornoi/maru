"""Bootstrap administration for workforce structure and reviewed evidence."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, cast, override
from uuid import UUID

from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from maru.authorization.bindings import ensure_workforce_position_binding
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
    Position,
    PositionAssignment,
    PositionDocumentRequirement,
    PositionTemplate,
    VolunteerApplication,
    VolunteerOpportunity,
)
from maru.workforce.services import (
    activate_position_assignment,
    review_onboarding_document,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

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


def _lock_assignment_admin_target(
    *,
    assignment: PositionAssignment,
    change: bool,
) -> PositionAssignment | None:
    if change:
        reference = (
            PositionAssignment.objects.filter(id=assignment.id)
            .order_by()
            .values_list(
                "organization_id",
                "edition__series_id",
                "edition_id",
                "position_id",
                "position__department_id",
            )
            .first()
        )
    else:
        reference = (
            Position.objects.filter(id=assignment.position_id)
            .order_by()
            .values_list(
                "organization_id",
                "edition__series_id",
                "edition_id",
                "id",
                "department_id",
            )
            .first()
        )
    if reference is None:
        raise ValidationError(
            "The workforce assignment target is unavailable.",
            code="workforce_assignment_unavailable",
        )
    organization_id, series_id, edition_id, position_id, department_id = reference
    scope = lock_workforce_edition_write_scope(
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    lock_active_department_write_target(
        scope=scope,
        department_id=department_id,
    )
    position_scope = (
        Position.objects.select_for_update()
        .filter(id=position_id)
        .order_by()
        .values_list("organization_id", "edition_id", "department_id")
        .first()
    )
    if position_scope != (
        scope.organization_id,
        scope.edition_id,
        department_id,
    ):
        raise ValidationError(
            "The workforce assignment target is unavailable.",
            code="workforce_assignment_unavailable",
        )
    if assignment.position_id != position_id:
        raise ValidationError(
            "A workforce assignment cannot move to another Position.",
            code="workforce_assignment_position_immutable",
        )
    if not change:
        return None
    locked_assignment = (
        PositionAssignment.objects.select_for_update()
        .filter(
            id=assignment.id,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            position_id=position_id,
        )
        .order_by()
        .first()
    )
    if locked_assignment is None:
        raise ValidationError(
            "The workforce assignment target is unavailable.",
            code="workforce_assignment_unavailable",
        )
    return locked_assignment


class PositionAdminForm(forms.ModelForm):  # type: ignore[type-arg]
    """Collect and validate position admin input."""

    class Meta:
        """Configure Django's declarative class metadata."""

        model = Position
        fields = (
            "organization",
            "edition",
            "template",
            "department",
            "reports_to",
            "role_bundle",
            "code",
            "title",
            "description",
            "headcount",
            "capacity_codes",
            "status",
            "created_by",
        )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the PositionAdminForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        super().__init__(*args, **kwargs)
        self.fields["role_bundle"].required = False
        self.fields["description"].required = False
        self.fields["capacity_codes"].required = False

    def clean(self) -> dict[str, Any]:
        """Validate and normalize the record.

        Returns
        -------
        dict[str, Any]
            A mapping containing the resolved clean data.
        """
        cleaned = super().clean() or {}
        template = cleaned.get("template")
        if isinstance(template, PositionTemplate):
            if not cleaned.get("role_bundle"):
                cleaned["role_bundle"] = template.role_bundle
                self.instance.role_bundle = template.role_bundle
            if not str(cleaned.get("description", "")).strip():
                cleaned["description"] = template.description
                self.instance.description = template.description
            if not cleaned.get("capacity_codes"):
                values = list(template.default_capacity_codes)
                cleaned["capacity_codes"] = values
                self.instance.capacity_codes = values
        return cleaned


class PositionAssignmentAdminForm(forms.ModelForm):  # type: ignore[type-arg]
    """Collect and validate position assignment admin input."""

    activate_now = forms.BooleanField(
        required=False,
        label="Activate immediately after independent approval",
        help_text=(
            "Maru checks headcount, approved agreements, both controllers' "
            "authority, and then creates the scoped role and capacity."
        ),
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        model = PositionAssignment
        fields = (
            "position",
            "account",
            "effective_from",
            "expires_at",
            "approved_by",
            "reason",
        )

    def clean(self) -> dict[str, Any]:
        """Validate and normalize the record.

        Returns
        -------
        dict[str, Any]
            A mapping containing the resolved clean data.
        """
        cleaned = super().clean() or {}
        if cleaned.get("activate_now") and not cleaned.get("approved_by"):
            self.add_error(
                "approved_by",
                "Choose the distinct controller who independently approved this.",
            )
        return cleaned


class PositionDocumentRequirementInline(admin.TabularInline):  # type: ignore[type-arg]
    """Configure the position document requirement inline in Django administration."""

    model = PositionDocumentRequirement
    extra = 0
    autocomplete_fields = ("document_type",)


class VolunteerOpportunityInline(admin.StackedInline):  # type: ignore[type-arg]
    """Configure the volunteer opportunity inline in Django administration."""

    model = VolunteerOpportunity
    extra = 0
    max_num = 1
    can_delete = False
    fields = (
        "status",
        "headline",
        "description",
        "applications_open_at",
        "applications_close_at",
        "visible_when_filled",
        "acceptance_state",
    )
    readonly_fields = ("acceptance_state",)

    @admin.display(description="Current application state")
    def acceptance_state(self, obj: VolunteerOpportunity) -> str:
        """Return the application's current acceptance state.

        Parameters
        ----------
        obj : VolunteerOpportunity
            The model instance being validated or presented.

        Returns
        -------
        str
            The normalized text for acceptance state.
        """
        occupancy = "Filled" if obj.is_filled else "Vacant"
        availability = (
            "accepting applications" if obj.accepts_applications else "not accepting"
        )
        return f"{occupancy}; {availability}"


@admin.register(Department)
class DepartmentAdmin(EditionContextAdmin):
    """Inspection-only legacy registry; Page 9 owns every Department mutation."""

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
    """Configure Django administration for position."""

    form = PositionAdminForm
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
    prepopulated_fields: ClassVar[dict[str, Sequence[str]]] = {"code": ("title",)}
    inlines = (PositionDocumentRequirementInline, VolunteerOpportunityInline)

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
    @transaction.atomic
    def save_model(
        self,
        request: HttpRequest,
        obj: Position,
        form: forms.ModelForm,  # type: ignore[type-arg]
        change: bool,
    ) -> None:
        _ = form, change
        _lock_position_admin_target(position=obj, change=change)
        if not obj.created_by_id and isinstance(request.user, Account):
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        ensure_workforce_position_binding(position=obj)


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
    """Configure Django administration for position assignment."""

    form = PositionAssignmentAdminForm
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
    autocomplete_fields = ("position", "account", "approved_by")
    readonly_fields = (
        "organization",
        "edition",
        "status",
        "proposed_by",
        "role_assignment",
        "participation_capacity",
        "ended_at",
        "id",
        "created_at",
        "updated_at",
    )

    @override
    @transaction.atomic
    def save_model(
        self,
        request: HttpRequest,
        obj: PositionAssignment,
        form: forms.ModelForm,  # type: ignore[type-arg]
        change: bool,
    ) -> None:
        actor = cast("Account", request.user)
        previous = _lock_assignment_admin_target(assignment=obj, change=change)
        if previous is not None and previous.status == PositionAssignment.Status.ACTIVE:
            obj.__dict__.update(previous.__dict__)
            return
        obj.organization = obj.position.organization
        obj.edition = obj.position.edition
        if not change:
            obj.proposed_by = actor
            obj.status = PositionAssignment.Status.PROPOSED
            super().save_model(request, obj, form, change)
        if bool(form.cleaned_data.get("activate_now")):
            approved_by = cast("Account", form.cleaned_data["approved_by"])
            activated = activate_position_assignment(
                position_id=obj.position_id,
                account=obj.account,
                actor=actor,
                approver=approved_by,
                effective_from=obj.effective_from,
                expires_at=obj.expires_at,
                reason=obj.reason,
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
                proposed_assignment_id=obj.id,
            )
            obj.__dict__.update(activated.__dict__)
        elif change:
            super().save_model(request, obj, form, change)


@admin.register(VolunteerOpportunity)
class VolunteerOpportunityAdmin(EditionContextAdmin):
    """Configure Django administration for volunteer opportunity."""

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
