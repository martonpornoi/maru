"""Bootstrap-only administration for organizer structure."""

from collections.abc import Sequence
from typing import ClassVar, cast

from django.contrib import admin
from django.db.models import Count, QuerySet
from django.http import HttpRequest

from maru.core.admin import NoDeleteAdminMixin
from maru.events.admin_context import EditionContextAdmin
from maru.organizations.forms import OrganizationAdminForm
from maru.organizations.models import (
    ConventionSeries,
    Organization,
    OrganizationMembership,
)


@admin.register(Organization)
class OrganizationAdmin(
    NoDeleteAdminMixin,
    EditionContextAdmin,
):
    form = OrganizationAdminForm
    edition_context_lookup = "id"
    edition_context_value_attribute = "organization_id"
    list_display = (
        "name",
        "slug",
        "lifecycle",
        "default_languages",
        "default_time_zone",
        "series_count",
        "edition_count",
        "member_count",
    )
    list_display_links = ("name", "slug")
    list_filter = ("lifecycle", "country_code", "default_time_zone")
    search_fields = ("name", "slug")
    ordering = ("name",)
    list_per_page = 50
    readonly_fields = ("id", "created_at", "updated_at")
    prepopulated_fields: ClassVar[dict[str, Sequence[str]]] = {"slug": ("name",)}
    fieldsets = (
        (
            "Accountable organizer",
            {
                "description": (
                    "The organization is the independently governed tenant and "
                    "data controller. It may own several convention brands."
                ),
                "fields": (
                    "name",
                    "legal_name",
                    "slug",
                    "lifecycle",
                    "description",
                    "website_url",
                    "contact_email",
                    "country_code",
                ),
            },
        ),
        (
            "Regional defaults",
            {"fields": ("default_language_codes", "default_time_zone")},
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

    @admin.display(description="Default languages")
    def default_languages(self, obj: Organization) -> str:
        return ", ".join(obj.default_language_codes)

    def get_queryset(self, request: HttpRequest) -> QuerySet[Organization]:
        queryset = cast(
            QuerySet[Organization],
            super().get_queryset(request),
        )
        return queryset.annotate(
            _series_count=Count("convention_series", distinct=True),
            _edition_count=Count("event_editions", distinct=True),
            _member_count=Count("memberships", distinct=True),
        )

    @admin.display(ordering="_series_count", description="Series")
    def series_count(self, obj: Organization) -> int:
        return int(getattr(obj, "_series_count", 0))

    @admin.display(ordering="_edition_count", description="Editions")
    def edition_count(self, obj: Organization) -> int:
        return int(getattr(obj, "_edition_count", 0))

    @admin.display(ordering="_member_count", description="Members")
    def member_count(self, obj: Organization) -> int:
        return int(getattr(obj, "_member_count", 0))


@admin.register(ConventionSeries)
class ConventionSeriesAdmin(
    NoDeleteAdminMixin,
    EditionContextAdmin,
):
    edition_context_lookup = "id"
    edition_context_value_attribute = "series_id"
    list_display = (
        "name",
        "organization",
        "slug",
        "is_active",
        "edition_count",
    )
    list_display_links = ("name", "slug")
    list_filter = ("is_active", "organization")
    search_fields = ("name", "slug", "organization__name", "organization__slug")
    ordering = ("organization__name", "name")
    list_select_related = ("organization",)
    list_per_page = 50
    autocomplete_fields = ("organization",)
    readonly_fields = ("id", "created_at", "updated_at")
    prepopulated_fields: ClassVar[dict[str, Sequence[str]]] = {"slug": ("name",)}
    fieldsets = (
        (
            "Recurring convention brand",
            {
                "description": (
                    "A series is the public convention identity that continues "
                    "across yearly editions; it is not a separate tenant."
                ),
                "fields": (
                    "name",
                    "slug",
                    "organization",
                    "description",
                    "website_url",
                    "contact_email",
                    "is_active",
                ),
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

    def get_queryset(self, request: HttpRequest) -> QuerySet[ConventionSeries]:
        queryset = cast(
            QuerySet[ConventionSeries],
            super().get_queryset(request),
        )
        return queryset.annotate(_edition_count=Count("event_editions", distinct=True))

    @admin.display(ordering="_edition_count", description="Editions")
    def edition_count(self, obj: ConventionSeries) -> int:
        return int(getattr(obj, "_edition_count", 0))


@admin.register(OrganizationMembership)
class OrganizationMembershipAdmin(
    NoDeleteAdminMixin,
    EditionContextAdmin,
):
    edition_context_lookup = "organization_id"
    edition_context_value_attribute = "organization_id"
    list_display = (
        "account",
        "relationship_label",
        "organization",
        "state",
        "started_at",
        "ended_at",
    )
    list_display_links = ("account", "relationship_label")
    list_filter = ("state", "organization")
    search_fields = (
        "account__display_name",
        "account__email",
        "relationship_label",
        "organization__name",
        "organization__slug",
    )
    ordering = ("organization__name", "account__display_name", "account__email")
    list_select_related = ("account", "organization")
    list_per_page = 50
    autocomplete_fields = ("account", "organization")
    readonly_fields = ("id", "created_at", "updated_at")
    fieldsets = (
        (
            "Membership",
            {
                "fields": (
                    "account",
                    "organization",
                    "relationship_label",
                    "state",
                )
            },
        ),
        ("Term", {"fields": ("started_at", "ended_at")}),
        (
            "Technical details",
            {
                "classes": ("collapse",),
                "fields": ("id", "created_at", "updated_at"),
            },
        ),
    )
