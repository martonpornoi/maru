"""Bootstrap-only administration for organizer structure."""

from collections.abc import Sequence
from typing import ClassVar, cast

from django.contrib import admin
from django.db.models import Count, QuerySet
from django.http import HttpRequest

from maru.core.admin import ReadOnlyAdminMixin
from maru.events.admin_context import EditionContextAdmin
from maru.organizations.forms import OrganizationAdminForm
from maru.organizations.models import (
    ConventionSeries,
    Organization,
    OrganizationMembership,
    OrganizationRepresentation,
    RepresentationAppointment,
)


@admin.register(Organization)
class OrganizationAdmin(
    ReadOnlyAdminMixin,
    EditionContextAdmin,
):
    """Configure Django administration for organization."""

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
        """Enumerate supported media values."""

        js = ("core/filterable-select.js",)

    @admin.display(description="Default languages")
    def default_languages(self, obj: Organization) -> str:
        """Return default languages.

        Parameters
        ----------
        obj : Organization
            The model instance being validated or presented.

        Returns
        -------
        str
            The normalized text for default languages.
        """
        return ", ".join(obj.default_language_codes)

    def get_queryset(self, request: HttpRequest) -> QuerySet[Organization]:
        """Return the permission-scoped queryset.

        Parameters
        ----------
        request : HttpRequest
            The incoming HTTP request and authenticated principal context.

        Returns
        -------
        QuerySet[Organization]
            The matching get queryset records in deterministic order.
        """
        queryset = cast(
            "QuerySet[Organization]",
            super().get_queryset(request),
        )
        return queryset.annotate(
            _series_count=Count("convention_series", distinct=True),
            _edition_count=Count("event_editions", distinct=True),
            _member_count=Count("memberships", distinct=True),
        )

    @admin.display(ordering="_series_count", description="Series")
    def series_count(self, obj: Organization) -> int:
        """Return series count.

        Parameters
        ----------
        obj : Organization
            The model instance being validated or presented.

        Returns
        -------
        int
            The computed number of series records.
        """
        return int(getattr(obj, "_series_count", 0))

    @admin.display(ordering="_edition_count", description="Editions")
    def edition_count(self, obj: Organization) -> int:
        """Return edition count.

        Parameters
        ----------
        obj : Organization
            The model instance being validated or presented.

        Returns
        -------
        int
            The computed number of edition records.
        """
        return int(getattr(obj, "_edition_count", 0))

    @admin.display(ordering="_member_count", description="Members")
    def member_count(self, obj: Organization) -> int:
        """Return member count.

        Parameters
        ----------
        obj : Organization
            The model instance being validated or presented.

        Returns
        -------
        int
            The computed number of member records.
        """
        return int(getattr(obj, "_member_count", 0))


@admin.register(ConventionSeries)
class ConventionSeriesAdmin(
    ReadOnlyAdminMixin,
    EditionContextAdmin,
):
    """Configure Django administration for convention series."""

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
        """Return the permission-scoped queryset.

        Parameters
        ----------
        request : HttpRequest
            The incoming HTTP request and authenticated principal context.

        Returns
        -------
        QuerySet[ConventionSeries]
            The matching get queryset records in deterministic order.
        """
        queryset = cast(
            "QuerySet[ConventionSeries]",
            super().get_queryset(request),
        )
        return queryset.annotate(_edition_count=Count("event_editions", distinct=True))

    @admin.display(ordering="_edition_count", description="Editions")
    def edition_count(self, obj: ConventionSeries) -> int:
        """Return edition count.

        Parameters
        ----------
        obj : ConventionSeries
            The model instance being validated or presented.

        Returns
        -------
        int
            The computed number of edition records.
        """
        return int(getattr(obj, "_edition_count", 0))


@admin.register(OrganizationMembership)
class OrganizationMembershipAdmin(
    ReadOnlyAdminMixin,
    EditionContextAdmin,
):
    """Configure Django administration for organization membership."""

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


@admin.register(OrganizationRepresentation)
class OrganizationRepresentationAdmin(
    ReadOnlyAdminMixin,
    EditionContextAdmin,
):
    """Configure Django administration for organization representation."""

    edition_context_lookup = "organization_id"
    edition_context_value_attribute = "organization_id"
    list_display = (
        "name",
        "organization",
        "state",
        "aggregate_version",
        "activated_at",
    )
    list_filter = ("state",)
    search_fields = ("organization__name", "organization__slug", "name")
    list_select_related = ("organization", "provisioned_by", "activated_by")
    ordering = ("organization__name",)
    readonly_fields = (
        "id",
        "organization",
        "code",
        "name",
        "state",
        "aggregate_version",
        "provisioned_by",
        "provisioning_reason",
        "activated_by",
        "activation_reason",
        "activated_at",
        "created_at",
        "updated_at",
    )


@admin.register(RepresentationAppointment)
class RepresentationAppointmentAdmin(
    ReadOnlyAdminMixin,
    EditionContextAdmin,
):
    """Configure Django administration for representation appointment."""

    edition_context_lookup = "representation__organization_id"
    edition_context_value_attribute = "organization_id"
    list_display = (
        "account",
        "representation",
        "role",
        "state",
        "invited_at",
        "activated_at",
    )
    list_filter = ("role", "state")
    search_fields = (
        "account__display_name",
        "account__email",
        "representation__organization__name",
    )
    list_select_related = (
        "account",
        "representation",
        "representation__organization",
        "role_assignment",
    )
    ordering = ("representation__organization__name", "account__display_name")
    readonly_fields = (
        "id",
        "representation",
        "account",
        "role",
        "state",
        "invitation_version",
        "invited_by",
        "invited_at",
        "responded_at",
        "activated_at",
        "ended_at",
        "reason",
        "role_assignment",
        "created_at",
        "updated_at",
    )
