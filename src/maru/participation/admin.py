"""Human-readable bootstrap administration for participation history."""

from typing import ClassVar, cast

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils.html import format_html

from maru.core.admin import NoDeleteAdminMixin
from maru.events.admin_context import EditionContextAdmin
from maru.participation.models import Participation, ParticipationCapacity

VISIBLE_CAPACITY_COUNT = 3


class ParticipationCapacityInline(
    NoDeleteAdminMixin,
    admin.TabularInline,  # type: ignore[type-arg]
):
    """Configure the participation capacity inline in Django administration."""

    model = ParticipationCapacity
    fields = (
        "label_snapshot",
        "code",
        "status",
        "contribution_summary",
        "public_history_visible",
        "started_at",
        "ended_at",
    )
    extra = 0
    show_change_link = True

    def has_add_permission(
        self,
        request: HttpRequest,
        obj: Participation | None = None,
    ) -> bool:
        """Return whether add permission.

        Parameters
        ----------
        request : HttpRequest
            The incoming HTTP request and authenticated principal context.
        obj : Participation | None, default=None
            The model instance being validated or presented.

        Returns
        -------
        bool
            `True` when add permission; otherwise `False`.
        """
        if obj is not None and obj.edition.lifecycle == "archived":
            return False
        return super().has_add_permission(request, obj)

    def get_readonly_fields(
        self,
        request: HttpRequest,
        obj: Participation | None = None,
    ) -> tuple[str, ...]:
        """Return readonly fields.

        Parameters
        ----------
        request : HttpRequest
            The incoming HTTP request and authenticated principal context.
        obj : Participation | None, default=None
            The model instance being validated or presented.

        Returns
        -------
        tuple[str, ...]
            The matching get readonly fields records in deterministic order.
        """
        _ = request
        if obj is not None and obj.edition.lifecycle == "archived":
            return self.fields
        return ()


@admin.register(Participation)
class ParticipationAdmin(
    NoDeleteAdminMixin,
    EditionContextAdmin,
):
    """Configure Django administration for participation."""

    list_display = (
        "person",
        "edition",
        "status",
        "capacity_labels",
        "organization",
    )
    list_display_links = ("person", "edition")
    list_filter = (
        "status",
        "public_history_visible",
        "organization",
        "edition",
    )
    search_fields = (
        "account__display_name",
        "account__email",
        "edition__name",
        "edition__slug",
        "series_name_snapshot",
        "capacities__label_snapshot",
        "capacities__code",
    )
    ordering = ("-edition__starts_on", "account__display_name", "account__email")
    list_select_related = ("account", "organization", "edition")
    list_per_page = 50
    autocomplete_fields = ("account", "organization", "edition")
    readonly_fields = (
        "edition_name_snapshot",
        "series_name_snapshot",
        "id",
        "created_at",
        "updated_at",
    )
    date_hierarchy = "created_at"
    inlines = (ParticipationCapacityInline,)
    fieldsets = (
        (
            "Participation",
            {
                "fields": (
                    "account",
                    "organization",
                    "edition",
                    "status",
                    "public_history_visible",
                )
            },
        ),
        (
            "Historical labels",
            {"fields": ("series_name_snapshot", "edition_name_snapshot")},
        ),
        (
            "Technical details",
            {
                "classes": ("collapse",),
                "fields": ("id", "created_at", "updated_at"),
            },
        ),
    )

    def get_queryset(self, request: HttpRequest) -> QuerySet[Participation]:
        """Return the permission-scoped queryset.

        Parameters
        ----------
        request : HttpRequest
            The incoming HTTP request and authenticated principal context.

        Returns
        -------
        QuerySet[Participation]
            The matching get queryset records in deterministic order.
        """
        queryset = cast(
            "QuerySet[Participation]",
            super().get_queryset(request),
        )
        return queryset.select_related(
            "account", "organization", "edition"
        ).prefetch_related("capacities")

    @admin.display(description="Person", ordering="account__display_name")
    def person(self, obj: Participation) -> str:
        """Return a disclosure-safe label for the referenced person.

        Parameters
        ----------
        obj : Participation
            The model instance being validated or presented.

        Returns
        -------
        str
            A display-safe person label using the configured fallback.
        """
        return str(obj.account)

    @admin.display(description="Capacities")
    def capacity_labels(self, obj: Participation) -> str:
        """Return capacity labels.

        Parameters
        ----------
        obj : Participation
            The model instance being validated or presented.

        Returns
        -------
        str
            The normalized text for capacity labels.
        """
        labels = [capacity.label_snapshot for capacity in obj.capacities.all()]
        full_label = ", ".join(labels)
        visible_labels = labels[:VISIBLE_CAPACITY_COUNT]
        compact_label = ", ".join(visible_labels)
        remaining = len(labels) - len(visible_labels)
        if remaining:
            compact_label = f"{compact_label} +{remaining}"
        return format_html(
            '<span title="{}">{}</span>',
            full_label,
            compact_label,
        )

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: Participation | None = None,
    ) -> bool:
        """Return whether change permission.

        Parameters
        ----------
        request : HttpRequest
            The incoming HTTP request and authenticated principal context.
        obj : Participation | None, default=None
            The model instance being validated or presented.

        Returns
        -------
        bool
            `True` when change permission; otherwise `False`.
        """
        if obj is not None and obj.edition.lifecycle == "archived":
            return False
        return super().has_change_permission(request, obj)


@admin.register(ParticipationCapacity)
class ParticipationCapacityAdmin(
    NoDeleteAdminMixin,
    EditionContextAdmin,
):
    """Configure Django administration for participation capacity."""

    edition_context_lookup = "participation__edition_id"
    edition_context_foreign_key_lookups: ClassVar[dict[str, str]] = {
        "participation": "edition_id",
    }
    list_display = (
        "person",
        "edition",
        "label_snapshot",
        "status",
        "term",
    )
    list_display_links = ("person", "label_snapshot")
    list_filter = (
        "status",
        "public_history_visible",
        "participation__organization",
        "participation__edition",
        "code",
    )
    search_fields = (
        "participation__account__display_name",
        "participation__account__email",
        "participation__edition__name",
        "label_snapshot",
        "code",
        "contribution_summary",
    )
    ordering = (
        "-participation__edition__starts_on",
        "participation__account__display_name",
        "label_snapshot",
    )
    list_select_related = (
        "participation",
        "participation__account",
        "participation__organization",
        "participation__edition",
    )
    list_per_page = 50
    autocomplete_fields = ("participation",)
    readonly_fields = ("id", "created_at", "updated_at")
    date_hierarchy = "created_at"
    fieldsets = (
        (
            "Capacity",
            {
                "fields": (
                    "participation",
                    "label_snapshot",
                    "code",
                    "status",
                    "contribution_summary",
                    "public_history_visible",
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

    @admin.display(
        description="Person",
        ordering="participation__account__display_name",
    )
    def person(self, obj: ParticipationCapacity) -> str:
        """Return a disclosure-safe label for the referenced person.

        Parameters
        ----------
        obj : ParticipationCapacity
            The model instance being validated or presented.

        Returns
        -------
        str
            A display-safe person label using the configured fallback.
        """
        return str(obj.participation.account)

    @admin.display(description="Edition", ordering="participation__edition__name")
    def edition(self, obj: ParticipationCapacity) -> str:
        """Return edition.

        Parameters
        ----------
        obj : ParticipationCapacity
            The model instance being validated or presented.

        Returns
        -------
        str
            The normalized text for edition.
        """
        return obj.participation.edition.name

    @admin.display(description="Term", ordering="started_at")
    def term(self, obj: ParticipationCapacity) -> str:
        """Return term.

        Parameters
        ----------
        obj : ParticipationCapacity
            The model instance being validated or presented.

        Returns
        -------
        str
            The normalized text for term.
        """
        if obj.started_at is None and obj.ended_at is None:
            return "Not recorded"
        started = obj.started_at.date().isoformat() if obj.started_at else "Unknown"
        ended = obj.ended_at.date().isoformat() if obj.ended_at else "Present"
        return f"{started} → {ended}"

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: ParticipationCapacity | None = None,
    ) -> bool:
        """Return whether change permission.

        Parameters
        ----------
        request : HttpRequest
            The incoming HTTP request and authenticated principal context.
        obj : ParticipationCapacity | None, default=None
            The model instance being validated or presented.

        Returns
        -------
        bool
            `True` when change permission; otherwise `False`.
        """
        if obj is not None and obj.participation.edition.lifecycle == "archived":
            return False
        return super().has_change_permission(request, obj)
