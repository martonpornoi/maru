"""Bootstrap administration for workforce structure and reviewed evidence."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar, cast, override
from uuid import UUID

from django import forms
from django.contrib import admin
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import SafeString

from maru.events.admin_context import EditionContextAdmin
from maru.identity.models import Account
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


class PositionAdminForm(forms.ModelForm):  # type: ignore[type-arg]
    class Meta:
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
        super().__init__(*args, **kwargs)
        self.fields["role_bundle"].required = False
        self.fields["description"].required = False
        self.fields["capacity_codes"].required = False

    def clean(self) -> dict[str, Any]:
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
    activate_now = forms.BooleanField(
        required=False,
        label="Activate immediately after independent approval",
        help_text=(
            "Maru checks headcount, approved agreements, both controllers' "
            "authority, and then creates the scoped role and capacity."
        ),
    )

    class Meta:
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
        cleaned = super().clean() or {}
        if cleaned.get("activate_now") and not cleaned.get("approved_by"):
            self.add_error(
                "approved_by",
                "Choose the distinct controller who independently approved this.",
            )
        return cleaned


class PositionDocumentRequirementInline(admin.TabularInline):  # type: ignore[type-arg]
    model = PositionDocumentRequirement
    extra = 0
    autocomplete_fields = ("document_type",)


class VolunteerOpportunityInline(admin.StackedInline):  # type: ignore[type-arg]
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
        occupancy = "Filled" if obj.is_filled else "Vacant"
        availability = (
            "accepting applications" if obj.accepts_applications else "not accepting"
        )
        return f"{occupancy}; {availability}"


@admin.register(Department)
class DepartmentAdmin(EditionContextAdmin):
    edition_context_lookup = "edition_id"
    list_display = ("name", "edition", "parent", "position")
    list_filter = ("organization", "edition")
    search_fields = ("name", "code", "edition__name")
    autocomplete_fields = ("organization", "edition", "parent")
    prepopulated_fields: ClassVar[dict[str, Sequence[str]]] = {"code": ("name",)}


@admin.register(PositionTemplate)
class PositionTemplateAdmin(EditionContextAdmin):
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
        count = obj.assignments.filter(status=PositionAssignment.Status.ACTIVE).count()
        return f"{count} / {obj.headcount}"

    @admin.display(description="Applications")
    def application_state(self, obj: Position) -> str:
        opportunity = obj.opportunity
        if opportunity.status == VolunteerOpportunity.Status.PUBLISHED:
            return (
                "Published · accepting"
                if opportunity.accepts_applications
                else "Published · visible, not accepting"
            )
        return opportunity.get_status_display()

    @override
    def save_model(
        self,
        request: HttpRequest,
        obj: Position,
        form: forms.ModelForm,  # type: ignore[type-arg]
        change: bool,
    ) -> None:
        _ = form, change
        if not obj.created_by_id and isinstance(request.user, Account):
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(OnboardingDocumentType)
class OnboardingDocumentTypeAdmin(EditionContextAdmin):
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
        account = cast(Account, request.user)
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
    def save_model(
        self,
        request: HttpRequest,
        obj: PositionAssignment,
        form: forms.ModelForm,  # type: ignore[type-arg]
        change: bool,
    ) -> None:
        actor = cast(Account, request.user)
        if change:
            previous = PositionAssignment.objects.get(id=obj.id)
            if previous.status == PositionAssignment.Status.ACTIVE:
                obj.__dict__.update(previous.__dict__)
                return
        obj.organization = obj.position.organization
        obj.edition = obj.position.edition
        if not change:
            obj.proposed_by = actor
            obj.status = PositionAssignment.Status.PROPOSED
            super().save_model(request, obj, form, change)
        if bool(form.cleaned_data.get("activate_now")):
            approved_by = cast(Account, form.cleaned_data["approved_by"])
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
