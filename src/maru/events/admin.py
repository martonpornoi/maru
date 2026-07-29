"""Readable, safety-aligned bootstrap administration for event editions."""

from collections.abc import Sequence
from typing import ClassVar, cast

from django import forms
from django.contrib import admin
from django.db.models import OuterRef, Q, QuerySet, Subquery
from django.http import HttpRequest

from maru.core.admin import NoDeleteAdminMixin, ReadOnlyAdminMixin
from maru.core.localization import grouped_language_choices, grouped_time_zone_choices
from maru.events.admin_context import EditionContextAdmin
from maru.events.models import (
    ArchiveAmendment,
    EditionClosureManifest,
    EditionLifecycleTransition,
    EditionReadinessGate,
    EventEdition,
)
from maru.identity.models import Account

PREVIEW_LENGTH = 80
PREVIEW_CONTENT_LENGTH = PREVIEW_LENGTH - 3


class EventEditionAdminForm(
    forms.ModelForm,  # type: ignore[type-arg]
):
    language_codes = forms.MultipleChoiceField(
        label="Languages",
        choices=grouped_language_choices,
        help_text="Select every language officially supported by this edition.",
        widget=forms.SelectMultiple(
            attrs={
                "size": 12,
                "data-filterable-select": "",
                "data-filter-placeholder": "Start typing a language or code",
            }
        ),
    )
    time_zone = forms.ChoiceField(
        choices=grouped_time_zone_choices,
        help_text="IANA time zone with UTC and daylight-saving offset information.",
        widget=forms.Select(
            attrs={
                "data-filterable-select": "",
                "data-filter-placeholder": "Start typing a city, region, or UTC offset",
            }
        ),
    )

    class Meta:
        model = EventEdition
        fields = (
            "organization",
            "series",
            "slug",
            "name",
            "time_zone",
            "language_codes",
            "currency_codes",
            "starts_on",
            "ends_on",
        )


def _actor_name_subquery() -> Subquery:
    return Subquery(
        Account.objects.filter(id=OuterRef("actor_id")).values("display_name")[:1]
    )


def _actor_label(obj: EditionLifecycleTransition | ArchiveAmendment) -> str:
    display_name = str(getattr(obj, "_actor_display_name", "")).strip()
    if display_name:
        return display_name
    return f"Account {str(obj.actor_id)[:8]}…"


@admin.register(EventEdition)
class EventEditionAdmin(
    NoDeleteAdminMixin,
    EditionContextAdmin,
):
    form = EventEditionAdminForm
    edition_context_lookup = "id"
    list_display = (
        "name",
        "organization",
        "series",
        "lifecycle",
        "date_range",
        "time_zone",
        "lifecycle_version",
    )
    list_display_links = ("name",)
    list_filter = ("lifecycle", "organization", "series", "time_zone")
    search_fields = (
        "name",
        "slug",
        "organization__name",
        "organization__slug",
        "series__name",
        "series__slug",
    )
    ordering = ("-starts_on", "name")
    list_select_related = ("organization", "series")
    list_per_page = 50
    autocomplete_fields = ("organization", "series")
    exclude = ("lifecycle",)
    readonly_fields = (
        "lifecycle_display",
        "lifecycle_version",
        "id",
        "created_at",
        "updated_at",
    )
    prepopulated_fields: ClassVar[dict[str, Sequence[str]]] = {"slug": ("name",)}
    fieldsets = (
        (
            "Edition",
            {
                "fields": (
                    "name",
                    "slug",
                    "organization",
                    "series",
                    "lifecycle_display",
                    "lifecycle_version",
                )
            },
        ),
        ("Dates and time", {"fields": ("starts_on", "ends_on", "time_zone")}),
        (
            "Languages and currencies",
            {"fields": ("language_codes", "currency_codes")},
        ),
        (
            "Technical details",
            {
                "classes": ("collapse",),
                "fields": ("id", "created_at", "updated_at"),
            },
        ),
    )

    class Media:
        js = ("core/filterable-select.js",)

    @admin.display(description="Lifecycle", ordering="lifecycle")
    def lifecycle_display(self, obj: EventEdition | None) -> str:
        if obj is None:
            return EventEdition.Lifecycle.DRAFT.label
        return obj.get_lifecycle_display()

    @admin.display(description="Dates", ordering="starts_on")
    def date_range(self, obj: EventEdition) -> str:
        return f"{obj.starts_on:%Y-%m-%d} → {obj.ends_on:%Y-%m-%d}"

    def edition_context_q(
        self,
        request: HttpRequest,
        edition: EventEdition,
    ) -> Q:
        if (
            request.path == "/admin/autocomplete/"
            and request.GET.get("app_label") == "registration"
            and request.GET.get("model_name") == "registrationconfiguration"
            and request.GET.get("field_name") == "source_edition"
        ):
            return Q(organization_id=edition.organization_id) & ~Q(id=edition.id)
        return super().edition_context_q(request, edition)

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: EventEdition | None = None,
    ) -> bool:
        if obj is not None and obj.lifecycle == EventEdition.Lifecycle.ARCHIVED:
            return False
        return super().has_change_permission(request, obj)


@admin.register(EditionLifecycleTransition)
class EditionLifecycleTransitionAdmin(
    ReadOnlyAdminMixin,
    EditionContextAdmin,
):
    list_display = (
        "edition",
        "from_state",
        "to_state",
        "actor",
        "reason_preview",
        "created_at",
    )
    list_display_links = ("edition",)
    list_filter = ("from_state", "to_state", "edition", "created_at")
    search_fields = ("edition__name", "edition__slug", "reason", "=actor_id")
    ordering = ("-created_at",)
    list_select_related = ("edition",)
    date_hierarchy = "created_at"
    list_per_page = 50
    fieldsets = (
        (
            "Transition",
            {
                "fields": (
                    "edition",
                    "from_state",
                    "to_state",
                    "actor",
                    "reason",
                    "created_at",
                )
            },
        ),
        (
            "Technical details",
            {
                "classes": ("collapse",),
                "fields": ("id", "actor_id", "updated_at"),
            },
        ),
    )
    readonly_fields = (
        "edition",
        "from_state",
        "to_state",
        "actor",
        "reason",
        "id",
        "actor_id",
        "created_at",
        "updated_at",
    )

    def get_queryset(
        self,
        request: HttpRequest,
    ) -> QuerySet[EditionLifecycleTransition]:
        queryset = cast(
            QuerySet[EditionLifecycleTransition],
            super().get_queryset(request),
        )
        return queryset.select_related("edition").annotate(
            _actor_display_name=_actor_name_subquery()
        )

    @admin.display(description="Actor", ordering="_actor_display_name")
    def actor(self, obj: EditionLifecycleTransition) -> str:
        return _actor_label(obj)

    @admin.display(description="Reason")
    def reason_preview(self, obj: EditionLifecycleTransition) -> str:
        reason = obj.reason.strip()
        if len(reason) <= PREVIEW_LENGTH:
            return reason
        return f"{reason[:PREVIEW_CONTENT_LENGTH]}…"


@admin.register(EditionReadinessGate)
class EditionReadinessGateAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = (
        "edition",
        "code",
        "status",
        "evidence_reference",
        "reviewed_at",
    )
    list_filter = ("organization_id", "edition", "code", "status")
    search_fields = ("edition__name", "evidence_reference", "review_summary")


@admin.register(EditionClosureManifest)
class EditionClosureManifestAdmin(
    ReadOnlyAdminMixin,
    admin.ModelAdmin,  # type: ignore[type-arg]
):
    list_display = (
        "edition",
        "generated_at",
        "generated_by_id",
        "manifest_digest",
    )
    list_filter = ("organization_id", "generated_at")
    exclude = ("counts",)


@admin.register(ArchiveAmendment)
class ArchiveAmendmentAdmin(
    ReadOnlyAdminMixin,
    EditionContextAdmin,
):
    list_display = (
        "edition",
        "actor",
        "summary_preview",
        "reason_preview",
        "created_at",
    )

    list_display_links = ("edition", "summary_preview")
    list_filter = ("edition", "created_at")
    search_fields = (
        "edition__name",
        "edition__slug",
        "summary",
        "reason",
        "=actor_id",
    )
    ordering = ("-created_at",)
    list_select_related = ("edition",)
    date_hierarchy = "created_at"
    list_per_page = 50
    fieldsets = (
        (
            "Amendment",
            {
                "fields": (
                    "edition",
                    "actor",
                    "summary",
                    "reason",
                    "created_at",
                )
            },
        ),
        (
            "Technical details",
            {
                "classes": ("collapse",),
                "fields": ("id", "actor_id", "updated_at"),
            },
        ),
    )
    readonly_fields = (
        "edition",
        "actor",
        "summary",
        "reason",
        "id",
        "actor_id",
        "created_at",
        "updated_at",
    )

    def get_queryset(self, request: HttpRequest) -> QuerySet[ArchiveAmendment]:
        queryset = cast(
            QuerySet[ArchiveAmendment],
            super().get_queryset(request),
        )
        return queryset.select_related("edition").annotate(
            _actor_display_name=_actor_name_subquery()
        )

    @admin.display(description="Actor", ordering="_actor_display_name")
    def actor(self, obj: ArchiveAmendment) -> str:
        return _actor_label(obj)

    @admin.display(description="Summary")
    def summary_preview(self, obj: ArchiveAmendment) -> str:
        summary = obj.summary.strip()
        if len(summary) <= PREVIEW_LENGTH:
            return summary
        return f"{summary[:PREVIEW_CONTENT_LENGTH]}…"

    @admin.display(description="Reason")
    def reason_preview(self, obj: ArchiveAmendment) -> str:
        reason = obj.reason.strip()
        if len(reason) <= PREVIEW_LENGTH:
            return reason
        return f"{reason[:PREVIEW_CONTENT_LENGTH]}…"
