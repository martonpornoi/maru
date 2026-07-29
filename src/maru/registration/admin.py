"""Readable bootstrap editing and inspection for registration."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import suppress
from typing import Any, ClassVar, override

from django import forms
from django.contrib import admin
from django.db import models
from django.db.models import Q
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.safestring import SafeString, mark_safe

from maru.core.admin import NoDeleteAdminMixin, ReadOnlyAdminMixin
from maru.events.admin_context import EditionContextAdmin
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.registration.models import (
    AdmissionProduct,
    AttendeeFursuit,
    AttendeeRegistrationProfile,
    CheckInRecord,
    ConfigurationStatus,
    Entitlement,
    FinancialLedgerEntry,
    FinancialOperation,
    GuardianConsent,
    MediaSafetyReceipt,
    MinorRegistrationPolicy,
    PaymentAttempt,
    PaymentException,
    PaymentIntent,
    PaymentProviderAccount,
    PaymentWebhookReceipt,
    ReceiptRecord,
    Registration,
    RegistrationAdjustment,
    RegistrationConfiguration,
    RegistrationLifecycleRun,
    RegistrationQuestion,
    RegistrationSection,
    RegistrationSubmission,
    RegistrationTemplate,
    RegistrationTemplateProduct,
    RegistrationTemplateQuestion,
    RegistrationTemplateSection,
    RegistrationTimelineEntry,
    SettlementAllocation,
    SettlementBatch,
    TemplateStatus,
)


def _admin_change_link(obj: models.Model, label: str) -> SafeString:
    model_meta = obj._meta
    url = reverse(
        f"admin:{model_meta.app_label}_{model_meta.model_name}_change",
        args=(obj.pk,),
    )
    return format_html('<a href="{}">{}</a>', url, label)


def _display_answer(value: object) -> str:
    if value is None or value == "":
        return "Not answered"
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) or "Not answered"
    if isinstance(value, dict):
        return ", ".join(f"{key}: {item}" for key, item in value.items())
    return str(value)


def _submitted_answers_table(
    submission: RegistrationSubmission | None,
) -> SafeString:
    if submission is None:
        return mark_safe("<p>No submitted form is attached.</p>")

    questions = {
        question.get("key"): question
        for question in submission.schema_snapshot
        if isinstance(question, dict) and question.get("key")
    }
    answer_keys = list(questions)
    answer_keys.extend(key for key in submission.answers if key not in questions)
    rows = []
    for key in answer_keys:
        question = questions.get(key, {})
        section = question.get("section") or {}
        rows.append(
            (
                section.get("title", "Other"),
                question.get("label", key),
                _display_answer(submission.answers.get(key)),
                question.get("purpose", "No purpose snapshot"),
                question.get("visibility", "not recorded"),
            )
        )
    rendered_rows = format_html_join(
        "",
        (
            '<tr><td>{}</td><th scope="row">{}</th><td>{}</td>'
            "<td>{}</td><td>{}</td></tr>"
        ),
        rows,
    )
    return format_html(
        (
            '<table class="listing"><thead><tr><th>Section</th>'
            "<th>Question</th><th>Submitted answer</th><th>Purpose</th>"
            "<th>Visibility</th></tr></thead><tbody>{}</tbody></table>"
        ),
        rendered_rows,
    )


def _linked_list(items: list[tuple[models.Model, str]]) -> SafeString:
    if not items:
        return mark_safe("<span>None</span>")
    return format_html(
        "<ul>{}</ul>",
        format_html_join(
            "",
            "<li>{}</li>",
            ((_admin_change_link(item, label),) for item, label in items),
        ),
    )


class TemplateSectionInline(
    admin.StackedInline,  # type: ignore[type-arg]
):
    model = RegistrationTemplateSection
    extra = 0
    fields = ("position", "key", "title", "description")

    def has_add_permission(
        self,
        request: HttpRequest,
        obj: RegistrationTemplate | None = None,
    ) -> bool:
        return bool(
            obj is not None
            and obj.status == TemplateStatus.DRAFT
            and super().has_add_permission(request, obj)
        )

    def get_readonly_fields(
        self,
        request: HttpRequest,
        obj: RegistrationTemplate | None = None,
    ) -> tuple[str, ...]:
        del request
        return self.fields if obj and obj.status != TemplateStatus.DRAFT else ()

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: RegistrationTemplate | None = None,
    ) -> bool:
        return bool(
            obj is not None
            and obj.status == TemplateStatus.DRAFT
            and super().has_delete_permission(request, obj)
        )


class TemplateQuestionInline(
    admin.StackedInline,  # type: ignore[type-arg]
):
    model = RegistrationTemplateQuestion
    extra = 0
    fields = (
        "position",
        "section",
        "key",
        "label",
        "help_text",
        "field_type",
        "required",
        "options",
        "purpose",
        "visibility",
        "classification",
        "condition_question_key",
        "condition_value",
    )

    def formfield_for_foreignkey(
        self,
        db_field: models.ForeignKey[Any, Any],
        request: HttpRequest,
        **kwargs: Any,
    ) -> forms.ModelChoiceField[Any] | None:
        if db_field.name == "section":
            resolver_match = request.resolver_match
            template_id = (
                resolver_match.kwargs.get("object_id")
                if resolver_match is not None
                else None
            )
            if template_id:
                kwargs["queryset"] = RegistrationTemplateSection.objects.filter(
                    template_id=template_id
                )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def has_add_permission(
        self,
        request: HttpRequest,
        obj: RegistrationTemplate | None = None,
    ) -> bool:
        return bool(
            obj is not None
            and obj.status == TemplateStatus.DRAFT
            and super().has_add_permission(request, obj)
        )

    def get_readonly_fields(
        self,
        request: HttpRequest,
        obj: RegistrationTemplate | None = None,
    ) -> tuple[str, ...]:
        del request
        return self.fields if obj and obj.status != TemplateStatus.DRAFT else ()

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: RegistrationTemplate | None = None,
    ) -> bool:
        return bool(
            obj is not None
            and obj.status == TemplateStatus.DRAFT
            and super().has_delete_permission(request, obj)
        )


class TemplateProductInline(
    admin.StackedInline,  # type: ignore[type-arg]
):
    model = RegistrationTemplateProduct
    extra = 0
    fields = (
        "position",
        "code",
        "name",
        "description",
        "price_minor",
        "capacity",
        "entitlement_code",
        "entitlement_name",
        "sales_open_at",
        "sales_close_at",
        "required_capacity_codes",
        "eligibility_explanation",
        "waitlist_enabled",
        "payment_window_minutes",
    )

    def has_add_permission(
        self,
        request: HttpRequest,
        obj: RegistrationTemplate | None = None,
    ) -> bool:
        return bool(
            obj is not None
            and obj.status == TemplateStatus.DRAFT
            and super().has_add_permission(request, obj)
        )

    def get_readonly_fields(
        self,
        request: HttpRequest,
        obj: RegistrationTemplate | None = None,
    ) -> tuple[str, ...]:
        del request
        return self.fields if obj and obj.status != TemplateStatus.DRAFT else ()

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: RegistrationTemplate | None = None,
    ) -> bool:
        return bool(
            obj is not None
            and obj.status == TemplateStatus.DRAFT
            and super().has_delete_permission(request, obj)
        )


@admin.register(RegistrationTemplate)
class RegistrationTemplateAdmin(
    NoDeleteAdminMixin,
    EditionContextAdmin,
):
    list_display = (
        "name",
        "version",
        "status",
        "scope",
        "organization",
        "published_at",
    )
    list_display_links = ("name",)
    list_filter = ("status", "organization", "series")
    search_fields = (
        "name",
        "code",
        "description",
        "organization__name",
        "series__name",
    )
    ordering = ("organization__name", "name", "-version")
    list_select_related = ("organization", "series")
    autocomplete_fields = ("organization", "series")
    readonly_fields = ("published_at", "id", "created_at", "updated_at")
    prepopulated_fields: ClassVar[dict[str, Sequence[str]]] = {"code": ("name",)}
    inlines = (
        TemplateSectionInline,
        TemplateQuestionInline,
        TemplateProductInline,
    )
    fieldsets = (
        (
            "Reusable registration template",
            {
                "fields": (
                    "name",
                    "code",
                    "version",
                    "description",
                    "organization",
                    "series",
                    "status",
                )
            },
        ),
        ("Publication", {"fields": ("created_by_id", "published_at")}),
        (
            "Technical details",
            {
                "classes": ("collapse",),
                "fields": ("id", "created_at", "updated_at"),
            },
        ),
    )

    def edition_context_q(
        self,
        request: HttpRequest,
        edition: EventEdition,
    ) -> Q:
        del request
        return Q(organization_id=edition.organization_id) & (
            Q(series__isnull=True) | Q(series_id=edition.series_id)
        )

    @admin.display(description="Scope")
    def scope(self, obj: RegistrationTemplate) -> str:
        return (
            obj.series.name
            if obj.series_id and obj.series is not None
            else "All organization conventions"
        )

    def get_readonly_fields(
        self,
        request: HttpRequest,
        obj: RegistrationTemplate | None = None,
    ) -> tuple[str, ...]:
        _ = request
        if obj is not None and obj.status != TemplateStatus.DRAFT:
            return tuple(
                field.name for field in obj._meta.fields if field.name not in {"status"}
            )
        return self.readonly_fields

    @override
    def save_model(
        self,
        request: HttpRequest,
        obj: RegistrationTemplate,
        form: forms.ModelForm,  # type: ignore[type-arg]
        change: bool,
    ) -> None:
        _ = form
        if not change and not obj.created_by_id and isinstance(request.user, Account):
            obj.created_by_id = request.user.id
        super().save_model(request, obj, form, change)


class RegistrationQuestionInline(
    admin.StackedInline,  # type: ignore[type-arg]
):
    model = RegistrationQuestion
    extra = 0
    fields = (
        "position",
        "section",
        "key",
        "label",
        "help_text",
        "field_type",
        "required",
        "options",
        "purpose",
        "visibility",
        "classification",
        "condition_question_key",
        "condition_value",
    )

    def formfield_for_foreignkey(
        self,
        db_field: models.ForeignKey[Any, Any],
        request: HttpRequest,
        **kwargs: Any,
    ) -> forms.ModelChoiceField[Any] | None:
        if db_field.name == "section":
            resolver_match = request.resolver_match
            configuration_id = (
                resolver_match.kwargs.get("object_id")
                if resolver_match is not None
                else None
            )
            if configuration_id:
                kwargs["queryset"] = RegistrationSection.objects.filter(
                    configuration_id=configuration_id
                )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def has_add_permission(
        self,
        request: HttpRequest,
        obj: RegistrationConfiguration | None = None,
    ) -> bool:
        return bool(
            obj is not None
            and obj.status == ConfigurationStatus.DRAFT
            and super().has_add_permission(request, obj)
        )

    def get_readonly_fields(
        self,
        request: HttpRequest,
        obj: RegistrationConfiguration | None = None,
    ) -> tuple[str, ...]:
        del request
        return self.fields if obj and obj.status != ConfigurationStatus.DRAFT else ()

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: RegistrationConfiguration | None = None,
    ) -> bool:
        return bool(
            obj is not None
            and obj.status == ConfigurationStatus.DRAFT
            and super().has_delete_permission(request, obj)
        )


class AdmissionProductInline(
    admin.StackedInline,  # type: ignore[type-arg]
):
    model = AdmissionProduct
    extra = 0
    fields = (
        "position",
        "code",
        "name",
        "description",
        "price_minor",
        "capacity",
        "entitlement_code",
        "entitlement_name",
        "sales_open_at",
        "sales_close_at",
        "required_capacity_codes",
        "eligibility_explanation",
        "waitlist_enabled",
        "payment_window_minutes",
        "status",
    )

    def has_add_permission(
        self,
        request: HttpRequest,
        obj: RegistrationConfiguration | None = None,
    ) -> bool:
        return bool(
            obj is not None
            and obj.status == ConfigurationStatus.DRAFT
            and super().has_add_permission(request, obj)
        )

    def get_readonly_fields(
        self,
        request: HttpRequest,
        obj: RegistrationConfiguration | None = None,
    ) -> tuple[str, ...]:
        del request
        return self.fields if obj and obj.status != ConfigurationStatus.DRAFT else ()

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: RegistrationConfiguration | None = None,
    ) -> bool:
        return bool(
            obj is not None
            and obj.status == ConfigurationStatus.DRAFT
            and super().has_delete_permission(request, obj)
        )


class RegistrationSectionInline(
    admin.StackedInline,  # type: ignore[type-arg]
):
    model = RegistrationSection
    extra = 0
    fields = ("position", "key", "title", "description")

    def has_add_permission(
        self,
        request: HttpRequest,
        obj: RegistrationConfiguration | None = None,
    ) -> bool:
        return bool(
            obj is not None
            and obj.status == ConfigurationStatus.DRAFT
            and super().has_add_permission(request, obj)
        )

    def get_readonly_fields(
        self,
        request: HttpRequest,
        obj: RegistrationConfiguration | None = None,
    ) -> tuple[str, ...]:
        del request
        return self.fields if obj and obj.status != ConfigurationStatus.DRAFT else ()

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: RegistrationConfiguration | None = None,
    ) -> bool:
        return bool(
            obj is not None
            and obj.status == ConfigurationStatus.DRAFT
            and super().has_delete_permission(request, obj)
        )


@admin.register(RegistrationConfiguration)
class RegistrationConfigurationAdmin(
    NoDeleteAdminMixin,
    EditionContextAdmin,
):
    list_display = (
        "edition",
        "name",
        "version",
        "status",
        "review_required",
        "source_label",
        "registration_period",
        "capacity",
        "currency",
    )
    list_display_links = ("edition", "name")
    list_filter = (
        "status",
        "review_required",
        "organization",
        "edition",
        "currency",
    )
    search_fields = (
        "edition__name",
        "edition__slug",
        "name",
        "source_template__name",
        "source_edition__name",
    )
    ordering = ("-edition__starts_on", "-version")
    list_select_related = (
        "organization",
        "edition",
        "source_template",
        "source_edition",
    )
    autocomplete_fields = (
        "organization",
        "edition",
        "source_template",
        "source_edition",
    )
    readonly_fields = (
        "status",
        "review_required",
        "review_note",
        "source_template",
        "source_edition",
        "created_by_id",
        "activated_at",
        "id",
        "created_at",
        "updated_at",
    )
    inlines = (
        RegistrationSectionInline,
        RegistrationQuestionInline,
        AdmissionProductInline,
    )
    fieldsets = (
        (
            "Edition registration",
            {
                "fields": (
                    "organization",
                    "edition",
                    "name",
                    "version",
                    "status",
                    "opens_at",
                    "closes_at",
                    "capacity",
                    "currency",
                    "minimum_age",
                    "default_payment_window_minutes",
                    "waitlist_enabled",
                    "automatic_waitlist_promotion",
                )
            },
        ),
        (
            "Inheritance and review",
            {
                "fields": (
                    "source_template",
                    "source_edition",
                    "review_required",
                    "review_note",
                    "created_by_id",
                    "activated_at",
                )
            },
        ),
        (
            "Technical details",
            {
                "classes": ("collapse",),
                "fields": ("id", "created_at", "updated_at"),
            },
        ),
    )

    @admin.display(description="Source")
    def source_label(self, obj: RegistrationConfiguration) -> str:
        if obj.source_template_id and obj.source_template is not None:
            return f"Template: {obj.source_template.name}"
        if obj.source_edition_id and obj.source_edition is not None:
            return f"Edition: {obj.source_edition.name}"
        return "New"

    @admin.display(description="Registration period", ordering="opens_at")
    def registration_period(self, obj: RegistrationConfiguration) -> str:
        return f"{obj.opens_at:%Y-%m-%d} → {obj.closes_at:%Y-%m-%d}"

    def get_readonly_fields(
        self,
        request: HttpRequest,
        obj: RegistrationConfiguration | None = None,
    ) -> tuple[str, ...]:
        _ = request
        if obj is not None and obj.status != ConfigurationStatus.DRAFT:
            return tuple(field.name for field in obj._meta.fields)
        return self.readonly_fields

    @override
    def save_model(
        self,
        request: HttpRequest,
        obj: RegistrationConfiguration,
        form: forms.ModelForm,  # type: ignore[type-arg]
        change: bool,
    ) -> None:
        _ = form
        if not change and not obj.created_by_id and isinstance(request.user, Account):
            obj.created_by_id = request.user.id
        super().save_model(request, obj, form, change)


@admin.register(Registration)
class RegistrationAdmin(
    ReadOnlyAdminMixin,
    EditionContextAdmin,
):
    list_display = (
        "reference",
        "person",
        "edition",
        "state",
        "account_state",
        "is_infinity_holder",
        "product_name_snapshot",
        "paid_amount",
        "payment_due_at",
        "confirmation_basis",
        "submitted_at",
    )
    list_display_links = ("reference", "person")
    list_filter = (
        "state",
        "submission_source",
        "organization",
        "edition",
        "currency_snapshot",
    )
    search_fields = (
        "reference",
        "account__display_name",
        "account__email",
        "edition__name",
        "product_name_snapshot",
    )
    ordering = ("-submitted_at",)
    list_select_related = ("account", "organization", "edition", "product")
    date_hierarchy = "submitted_at"
    fieldsets = (
        (
            "Attendee registration",
            {
                "fields": (
                    "reference",
                    "account",
                    "edition",
                    "state",
                    "product_name_snapshot",
                    "price_minor_snapshot",
                    "currency_snapshot",
                    "submitted_at",
                    "waitlisted_at",
                    "offered_at",
                    "payment_due_at",
                    "confirmed_at",
                    "checked_in_at",
                    "expired_at",
                    "cancelled_at",
                    "confirmation_basis",
                    "submission_source",
                    "submitted_by",
                    "staff_submission_reason",
                )
            },
        ),
        (
            "Staff overview",
            {
                "description": (
                    "Account state, organizer-assigned roles, capacities, "
                    "entitlements, finance, and staff-only notes are not "
                    "attendee-submitted form answers."
                ),
                "fields": (
                    "account_status",
                    "roles_and_capacities",
                    "entitlements_summary",
                    "payment_summary",
                    "internal_comments",
                ),
            },
        ),
        (
            "Submitted registration answers",
            {
                "description": (
                    "This is the immutable answer and question snapshot from "
                    "the form version the attendee actually submitted."
                ),
                "fields": ("submitted_answers",),
            },
        ),
        (
            "Attached records",
            {
                "description": (
                    "Direct links to the profile, fursuits, consent, finance, "
                    "credentials, messages, and other records attached to this "
                    "registration."
                ),
                "fields": ("attached_records",),
            },
        ),
        (
            "Exact source",
            {"fields": ("configuration", "product", "participation")},
        ),
        (
            "Technical details",
            {
                "classes": ("collapse",),
                "fields": (
                    "id",
                    "organization",
                    "aggregate_version",
                    "created_at",
                    "updated_at",
                ),
            },
        ),
    )

    @admin.display(description="Person", ordering="account__display_name")
    def person(self, obj: Registration) -> str:
        return str(obj.account)

    @admin.display(description="Ticket price", ordering="price_minor_snapshot")
    def price(self, obj: Registration) -> str:
        return f"{obj.price_minor_snapshot / 100:.2f} {obj.currency_snapshot}"

    @admin.display(description="User status", ordering="account__is_active")
    def account_state(self, obj: Registration) -> str:
        if not obj.account.is_active:
            return "Inactive"
        if obj.account.restrictions.filter(status="active").exists():
            return "Restricted"
        return "Active"

    @admin.display(description="Infinity", boolean=True)
    def is_infinity_holder(self, obj: Registration) -> bool:
        return obj.entitlements.filter(
            code="infinity-ticket",
            status=Entitlement.Status.ACTIVE,
        ).exists()

    @admin.display(description="Paid")
    def paid_amount(self, obj: Registration) -> str:
        received = sum(
            entry.amount_minor
            for entry in obj.financial_ledger.all()
            if entry.kind == FinancialLedgerEntry.Kind.PAYMENT
            and entry.direction == FinancialLedgerEntry.Direction.INFLOW
        )
        if not received:
            received = sum(
                attempt.amount_minor
                for attempt in obj.payment_attempts.all()
                if attempt.status == PaymentAttempt.Status.SUCCEEDED
            )
        return f"{received / 100:.2f} {obj.currency_snapshot}"

    @admin.display(description="Account and restriction status")
    def account_status(self, obj: Registration) -> SafeString:
        verification = (
            "email verified"
            if obj.account.email_verified_at is not None
            else "email not verified"
        )
        restrictions = list(
            obj.account.restrictions.filter(
                organization=obj.organization,
            ).order_by("-effective_at")
        )
        if not restrictions:
            restriction_text = "No organizer restrictions."
        else:
            restriction_text = "; ".join(
                f"{restriction.get_kind_display()}: "
                f"{restriction.get_status_display()} ({restriction.reason_code})"
                for restriction in restrictions
            )
        return format_html(
            "<strong>{}</strong> — {}.<br>{}",
            "Active sign-in" if obj.account.is_active else "Sign-in disabled",
            verification,
            restriction_text,
        )

    @admin.display(description="Organizer roles and convention capacities")
    def roles_and_capacities(self, obj: Registration) -> SafeString:
        assignments = obj.account.role_assignments.filter(
            organization=obj.organization,
        ).filter(Q(edition__isnull=True) | Q(edition=obj.edition))
        roles = [
            (f"{assignment.role_bundle.name} (v{assignment.role_bundle.version})")
            for assignment in assignments.select_related("role_bundle")
            if assignment.revoked_at is None
        ]
        capacities = [
            capacity.label_snapshot
            for capacity in obj.participation.capacities.all()
            if capacity.status != "withdrawn"
        ]
        return format_html(
            "<strong>Roles:</strong> {}<br><strong>Capacities:</strong> {}",
            ", ".join(roles) or "None assigned",
            ", ".join(capacities) or "None recorded",
        )

    @admin.display(description="Entitlements and special ticket status")
    def entitlements_summary(self, obj: Registration) -> SafeString:
        entitlements = list(obj.entitlements.all())
        if not entitlements:
            return mark_safe("<span>No entitlements granted.</span>")
        return format_html(
            "{}",
            "; ".join(
                f"{entitlement.label_snapshot} ({entitlement.get_status_display()})"
                for entitlement in entitlements
            ),
        )

    @admin.display(description="Payment and finance summary")
    def payment_summary(self, obj: Registration) -> SafeString:
        received = sum(
            entry.amount_minor
            for entry in obj.financial_ledger.all()
            if entry.kind == FinancialLedgerEntry.Kind.PAYMENT
            and entry.direction == FinancialLedgerEntry.Direction.INFLOW
        )
        returned = sum(
            entry.amount_minor
            for entry in obj.financial_ledger.all()
            if entry.kind
            in {
                FinancialLedgerEntry.Kind.REFUND,
                FinancialLedgerEntry.Kind.CHARGEBACK,
                FinancialLedgerEntry.Kind.DISPUTE,
            }
            and entry.direction == FinancialLedgerEntry.Direction.OUTFLOW
        )
        attempts = list(obj.payment_attempts.all())
        successful_attempt_total = sum(
            attempt.amount_minor
            for attempt in attempts
            if attempt.status == PaymentAttempt.Status.SUCCEEDED
        )
        gross = received or successful_attempt_total
        return format_html(
            (
                "<strong>{} {} received</strong>; {} {} "
                "returned or disputed; ticket price {} {}.<br>"
                "{} payment attempt(s), {} ledger movement(s), "
                "{} receipt(s), {} financial operation(s)."
            ),
            f"{gross / 100:.2f}",
            obj.currency_snapshot,
            f"{returned / 100:.2f}",
            obj.currency_snapshot,
            f"{obj.price_minor_snapshot / 100:.2f}",
            obj.currency_snapshot,
            len(attempts),
            obj.financial_ledger.count(),
            obj.receipt_records.count(),
            obj.financial_operations.count(),
        )

    @admin.display(description="Internal comments")
    def internal_comments(self, obj: Registration) -> SafeString:
        notes = obj.timeline.filter(
            audience=RegistrationTimelineEntry.Audience.STAFF_ONLY
        )
        if not notes:
            return mark_safe("<span>No staff-only comments.</span>")
        return format_html(
            "<ul>{}</ul>",
            format_html_join(
                "",
                "<li><strong>{}</strong>: {} <small>({:%Y-%m-%d %H:%M})</small></li>",
                ((note.title, note.summary, note.occurred_at) for note in notes),
            ),
        )

    @admin.display(description="Answers")
    def submitted_answers(self, obj: Registration) -> SafeString:
        try:
            submission = obj.submission
        except RegistrationSubmission.DoesNotExist:
            submission = None
        return _submitted_answers_table(submission)

    @admin.display(description="Related records")
    def attached_records(self, obj: Registration) -> SafeString:
        items: list[tuple[models.Model, str]] = []
        items.extend(
            (assignment, f"Organizer role: {assignment.role_bundle.name}")
            for assignment in obj.account.role_assignments.filter(
                organization=obj.organization,
            )
            .filter(Q(edition__isnull=True) | Q(edition=obj.edition))
            .select_related("role_bundle")
        )
        items.extend(
            (
                restriction,
                f"Restriction: {restriction.get_kind_display()} "
                f"({restriction.get_status_display()})",
            )
            for restriction in obj.account.restrictions.filter(
                organization=obj.organization,
            ).filter(Q(edition__isnull=True) | Q(edition=obj.edition))
        )
        items.extend(
            (message, f"Message: {message.subject}")
            for message in obj.account.notification_messages.filter(
                organization_id=obj.organization_id,
                edition_id=obj.edition_id,
            )
        )
        with suppress(RegistrationSubmission.DoesNotExist):
            items.append((obj.submission, "Submitted form snapshot"))
        media_ids = []
        with suppress(AttendeeRegistrationProfile.DoesNotExist):
            items.append((obj.attendee_profile, "Attendee profile"))
            media_ids.append(obj.attendee_profile.id)
        fursuits = list(obj.attendee_fursuits.all())
        items.extend((fursuit, f"Fursuit: {fursuit.name}") for fursuit in fursuits)
        media_ids.extend(fursuit.id for fursuit in fursuits)
        items.extend(
            (receipt, f"Media safety: {receipt.get_media_kind_display()}")
            for receipt in MediaSafetyReceipt.objects.filter(
                organization_id=obj.organization_id,
                edition_id=obj.edition_id,
                account_id=obj.account_id,
                media_id__in=media_ids,
            )
        )
        with suppress(GuardianConsent.DoesNotExist):
            items.append((obj.guardian_consent, "Guardian consent"))
        items.extend(
            (attempt, f"Payment attempt: {attempt.get_status_display()}")
            for attempt in obj.payment_attempts.all()
        )
        for intent in obj.payment_intents.all():
            items.append((intent, f"Payment intent: {intent.get_status_display()}"))
            items.extend(
                (webhook, "Authenticated payment webhook")
                for webhook in intent.webhook_receipts.all()
            )
            items.extend(
                (
                    exception,
                    f"Payment exception: {exception.get_kind_display()}",
                )
                for exception in intent.exceptions.all()
            )
        for entry in obj.financial_ledger.all():
            items.append((entry, f"Ledger: {entry.get_kind_display()}"))
            with suppress(SettlementAllocation.DoesNotExist):
                allocation = entry.settlement_allocation
                items.append((allocation, "Settlement allocation"))
                items.append(
                    (
                        allocation.settlement,
                        (f"Settlement: {allocation.settlement.provider_reference}"),
                    )
                )
        items.extend(
            (
                operation,
                f"Financial operation: {operation.get_kind_display()} "
                f"({operation.get_status_display()})",
            )
            for operation in obj.financial_operations.all()
        )
        items.extend(
            (receipt, f"Receipt: {receipt.document_number}")
            for receipt in obj.receipt_records.all()
        )
        items.extend(
            (adjustment, f"Adjustment: {adjustment.get_kind_display()}")
            for adjustment in obj.adjustments.all()
        )
        items.extend(
            (entitlement, f"Entitlement: {entitlement.label_snapshot}")
            for entitlement in obj.entitlements.all()
        )
        with suppress(CheckInRecord.DoesNotExist):
            items.append((obj.check_in, "Online check-in record"))
        for credential in obj.credentials.all():
            items.append((credential, f"Credential: {credential.label_snapshot}"))
            items.extend(
                (event, f"Credential event: {event.get_kind_display()}")
                for event in credential.events.all()
            )
        items.extend(
            (entry, f"Timeline: {entry.title}") for entry in obj.timeline.all()
        )
        return _linked_list(items)


@admin.register(RegistrationSubmission)
class RegistrationSubmissionAdmin(
    ReadOnlyAdminMixin,
    EditionContextAdmin,
):
    edition_context_lookup = "registration__edition_id"
    list_display = (
        "registration",
        "configuration_version",
        "answer_count",
        "submitted_at",
    )
    list_display_links = ("registration",)
    list_filter = ("configuration_version", "submitted_at")
    search_fields = (
        "registration__reference",
        "registration__account__display_name",
        "registration__edition__name",
    )
    ordering = ("-submitted_at",)
    list_select_related = ("registration", "registration__account")
    date_hierarchy = "submitted_at"
    fieldsets = (
        (
            "Submitted form",
            {
                "fields": (
                    "registration",
                    "configuration_version",
                    "submitted_at",
                    "submitted_answers",
                )
            },
        ),
        (
            "Immutable source snapshot",
            {
                "classes": ("collapse",),
                "fields": (
                    "schema_snapshot",
                    "answers",
                    "organization_id",
                    "edition_id",
                    "id",
                    "created_at",
                    "updated_at",
                ),
            },
        ),
    )

    @admin.display(description="Answers")
    def answer_count(self, obj: RegistrationSubmission) -> int:
        return len(obj.answers)

    @admin.display(description="Submitted questions and answers")
    def submitted_answers(self, obj: RegistrationSubmission) -> SafeString:
        return _submitted_answers_table(obj)


@admin.register(AttendeeRegistrationProfile)
class AttendeeRegistrationProfileAdmin(
    ReadOnlyAdminMixin,
    EditionContextAdmin,
):
    list_display = (
        "registration",
        "person",
        "edition",
        "country_code",
        "directory_country_code",
        "directory_visible",
        "created_at",
    )
    list_display_links = ("registration", "person")
    list_filter = (
        "directory_visible",
        "profile_photo_status",
        "country_code",
        "directory_country_code",
        "edition",
    )
    search_fields = (
        "registration__reference",
        "account__display_name",
        "account__email",
        "bio",
        "pronouns",
    )
    ordering = ("-created_at",)
    list_select_related = ("registration", "account", "edition")
    date_hierarchy = "created_at"
    fieldsets = (
        (
            "Registration profile",
            {
                "fields": (
                    "registration",
                    "account",
                    "edition",
                    "real_name",
                    "date_of_birth",
                    "pronoun_code",
                    "other_pronouns",
                    "pronouns",
                    "phone_number",
                    "telegram_handle",
                )
            },
        ),
        (
            "Address",
            {
                "fields": (
                    "address_line_1",
                    "address_line_2",
                    "locality",
                    "postal_code",
                    "region",
                    "country_code",
                )
            },
        ),
        (
            "Restricted emergency contact",
            {"fields": ("emergency_contact_name", "emergency_contact_phone")},
        ),
        (
            "Public profile and attendee list",
            {
                "fields": (
                    "bio",
                    "spoken_language_codes",
                    "brings_fursuits",
                    "profile_photo",
                    "profile_photo_status",
                    "profile_photo_reviewed_by",
                    "profile_photo_reviewed_at",
                    "profile_photo_review_note",
                    "profile_photo_reused_from_id",
                    "directory_visible",
                    "directory_country_code",
                    "directory_consent_version",
                    "directory_consent_at",
                )
            },
        ),
        (
            "Technical and governance details",
            {
                "classes": ("collapse",),
                "fields": (
                    "id",
                    "organization",
                    "collection_notice_version",
                    "created_at",
                    "updated_at",
                ),
            },
        ),
    )

    @admin.display(description="Person", ordering="account__display_name")
    def person(self, obj: AttendeeRegistrationProfile) -> str:
        return str(obj.account)


@admin.register(AttendeeFursuit)
class AttendeeFursuitAdmin(
    ReadOnlyAdminMixin,
    EditionContextAdmin,
):
    list_display = (
        "name",
        "person",
        "edition",
        "species",
        "is_active",
        "photo_status",
        "updated_at",
    )
    list_display_links = ("name", "person")
    list_filter = ("is_active", "photo_status", "edition")
    search_fields = (
        "name",
        "species",
        "registration__reference",
        "account__display_name",
        "account__email",
    )
    ordering = ("-updated_at",)
    list_select_related = ("registration", "account", "edition", "profile")
    date_hierarchy = "updated_at"

    @admin.display(description="Person", ordering="account__display_name")
    def person(self, obj: AttendeeFursuit) -> str:
        return str(obj.account)


@admin.register(PaymentAttempt)
class PaymentAttemptAdmin(
    ReadOnlyAdminMixin,
    EditionContextAdmin,
):
    edition_context_lookup = "registration__edition_id"
    list_display = (
        "registration",
        "provider",
        "status",
        "amount",
        "safe_result_code",
        "occurred_at",
    )
    list_display_links = ("registration", "provider")
    list_filter = ("provider", "status", "currency", "occurred_at")
    search_fields = (
        "registration__reference",
        "registration__account__display_name",
        "provider_reference",
        "safe_result_code",
    )
    ordering = ("-occurred_at",)
    list_select_related = ("registration", "registration__account")
    date_hierarchy = "occurred_at"

    @admin.display(description="Amount", ordering="amount_minor")
    def amount(self, obj: PaymentAttempt) -> str:
        return f"{obj.amount_minor / 100:.2f} {obj.currency}"


@admin.register(RegistrationAdjustment)
class RegistrationAdjustmentAdmin(
    ReadOnlyAdminMixin,
    EditionContextAdmin,
):
    edition_context_lookup = "registration__edition_id"
    list_display = (
        "registration",
        "kind",
        "actor_kind",
        "occurred_at",
    )
    list_display_links = ("registration", "kind")
    list_filter = ("kind", "actor_kind", "occurred_at")
    search_fields = (
        "registration__reference",
        "registration__account__display_name",
        "reason",
    )
    ordering = ("-occurred_at",)
    list_select_related = ("registration", "registration__account")
    date_hierarchy = "occurred_at"


@admin.register(Entitlement)
class EntitlementAdmin(
    ReadOnlyAdminMixin,
    EditionContextAdmin,
):
    edition_context_lookup = "registration__edition_id"
    list_display = (
        "registration",
        "label_snapshot",
        "code",
        "status",
        "granted_at",
    )
    list_display_links = ("registration", "label_snapshot")
    list_filter = ("status", "code", "granted_at")
    search_fields = (
        "registration__reference",
        "registration__account__display_name",
        "label_snapshot",
        "code",
    )
    ordering = ("-granted_at",)
    list_select_related = ("registration", "registration__account")
    date_hierarchy = "granted_at"


@admin.register(CheckInRecord)
class CheckInRecordAdmin(
    ReadOnlyAdminMixin,
    EditionContextAdmin,
):
    edition_context_lookup = "registration__edition_id"
    list_display = ("registration", "person", "method", "checked_in_at")
    list_display_links = ("registration", "person")
    list_filter = ("method", "checked_in_at")
    search_fields = (
        "registration__reference",
        "registration__account__display_name",
        "reason",
    )
    ordering = ("-checked_in_at",)
    list_select_related = ("registration", "registration__account")
    date_hierarchy = "checked_in_at"

    @admin.display(description="Person", ordering="registration__account__display_name")
    def person(self, obj: CheckInRecord) -> str:
        return str(obj.registration.account)


@admin.register(RegistrationTimelineEntry)
class RegistrationTimelineEntryAdmin(
    ReadOnlyAdminMixin,
    EditionContextAdmin,
):
    edition_context_lookup = "registration__edition_id"
    list_display = (
        "registration",
        "sequence",
        "title",
        "audience",
        "occurred_at",
    )
    list_display_links = ("registration", "title")
    list_filter = ("kind", "audience", "occurred_at")
    search_fields = (
        "registration__reference",
        "registration__account__display_name",
        "title",
        "summary",
    )
    ordering = ("-occurred_at",)
    list_select_related = ("registration", "registration__account")
    date_hierarchy = "occurred_at"


@admin.register(PaymentProviderAccount)
class PaymentProviderAccountAdmin(
    NoDeleteAdminMixin,
    admin.ModelAdmin,  # type: ignore[type-arg]
):
    list_display = ("code", "display_name", "organization", "adapter", "enabled")
    list_filter = ("organization", "adapter", "enabled")
    search_fields = ("code", "display_name", "api_base_url")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(MinorRegistrationPolicy)
class MinorRegistrationPolicyAdmin(
    NoDeleteAdminMixin,
    EditionContextAdmin,
):
    edition_context_lookup = "configuration__edition_id"
    list_display = (
        "configuration",
        "enabled",
        "minor_age_threshold",
        "jurisdiction_code",
        "reviewed_at",
    )
    list_filter = ("enabled", "jurisdiction_code", "reviewed_at")
    search_fields = ("configuration__edition__name", "review_reference")


@admin.register(GuardianConsent)
class GuardianConsentAdmin(
    ReadOnlyAdminMixin,
    EditionContextAdmin,
):
    list_display = (
        "registration",
        "status",
        "guardian_name",
        "relationship",
        "expires_at",
        "decided_at",
    )
    list_filter = ("status", "expires_at", "decided_at")
    search_fields = ("registration__reference", "guardian_email", "guardian_name")
    exclude = ("token_digest",)


def _register_read_only_operational_model(
    model: type[models.Model],
    *,
    list_display: tuple[str, ...],
    list_filter: tuple[str, ...] = (),
    search_fields: tuple[str, ...] = (),
) -> None:
    admin.site.register(
        model,
        type(
            f"{model.__name__}Admin",
            (ReadOnlyAdminMixin, EditionContextAdmin),
            {
                "list_display": list_display,
                "list_filter": list_filter,
                "search_fields": search_fields,
            },
        ),
    )


_register_read_only_operational_model(
    PaymentIntent,
    list_display=(
        "registration",
        "provider_account",
        "status",
        "amount_minor",
        "currency",
        "expires_at",
    ),
    list_filter=("status", "currency", "provider_account"),
    search_fields=("registration__reference", "provider_reference"),
)
_register_read_only_operational_model(
    PaymentWebhookReceipt,
    list_display=(
        "provider_account",
        "remote_event_id",
        "outcome",
        "safe_result_code",
        "received_at",
    ),
    list_filter=("outcome", "provider_account", "received_at"),
    search_fields=("remote_event_id", "safe_result_code"),
)
_register_read_only_operational_model(
    PaymentException,
    list_display=("kind", "status", "provider_account", "opened_at", "resolved_at"),
    list_filter=("kind", "status", "provider_account"),
    search_fields=("safe_summary", "resolution_reason"),
)
_register_read_only_operational_model(
    FinancialOperation,
    list_display=("registration", "kind", "status", "amount_minor", "requested_at"),
    list_filter=("kind", "status", "currency"),
    search_fields=("registration__reference", "request_reason", "approval_reason"),
)
_register_read_only_operational_model(
    FinancialLedgerEntry,
    list_display=("kind", "direction", "amount_minor", "currency", "occurred_at"),
    list_filter=("kind", "direction", "currency"),
    search_fields=("registration__reference", "provider_reference"),
)
_register_read_only_operational_model(
    ReceiptRecord,
    list_display=(
        "document_number",
        "registration",
        "kind",
        "amount_minor",
        "issued_at",
    ),
    list_filter=("kind", "currency", "issued_at"),
    search_fields=("document_number", "registration__reference"),
)
_register_read_only_operational_model(
    SettlementBatch,
    list_display=(
        "provider_account",
        "provider_reference",
        "status",
        "net_minor",
        "currency",
        "settled_at",
    ),
    list_filter=("status", "currency", "provider_account"),
    search_fields=("provider_reference",),
)
_register_read_only_operational_model(
    SettlementAllocation,
    list_display=("settlement", "ledger_entry", "amount_minor"),
)
_register_read_only_operational_model(
    MediaSafetyReceipt,
    list_display=("media_kind", "media_id", "scanner_code", "scanned_at"),
    list_filter=("media_kind", "scanner_code"),
)
_register_read_only_operational_model(
    RegistrationLifecycleRun,
    list_display=(
        "edition_id",
        "ran_at",
        "expired",
        "promoted",
        "restrictions_applied",
    ),
    list_filter=("ran_at",),
)
