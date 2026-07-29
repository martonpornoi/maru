"""Readable inspection for command-owned scoped authorization records."""

from datetime import datetime
from typing import cast

from django.contrib import admin
from django.db.models import Count, Q, QuerySet
from django.http import HttpRequest
from django.utils import timezone
from django.utils.html import format_html

from maru.authorization.models import CapabilityGrant, RoleAssignment, RoleBundle
from maru.core.admin import ReadOnlyAdminMixin
from maru.events.admin_context import EditionContextAdmin
from maru.events.models import EventEdition

VISIBLE_CAPABILITY_COUNT = 3


class EditionApplicableAuthorityAdmin(EditionContextAdmin):
    """Show edition-specific and organization-wide authority that applies."""

    def edition_context_q(
        self,
        request: HttpRequest,
        edition: EventEdition,
    ) -> Q:
        del request
        return Q(organization_id=edition.organization_id) & (
            Q(edition_id=edition.id) | Q(edition__isnull=True)
        )


def _authority_state(
    *,
    effective_from: datetime,
    expires_at: datetime | None,
    revoked_at: datetime | None,
) -> str:
    now = timezone.now()
    if revoked_at is not None:
        return "Revoked"
    if effective_from > now:
        return "Scheduled"
    if expires_at is not None and expires_at <= now:
        return "Expired"
    return "Active"


def _term_label(*, effective_from: datetime, expires_at: datetime | None) -> str:
    if expires_at is None:
        return f"Since {effective_from.year}"
    if expires_at.year == effective_from.year:
        return str(effective_from.year)
    return f"{effective_from.year}-{expires_at.year}"


def _full_term_label(*, effective_from: datetime, expires_at: datetime | None) -> str:
    start = effective_from.date().isoformat()
    end = expires_at.date().isoformat() if expires_at is not None else "Present"
    return f"{start} → {end}"


@admin.register(CapabilityGrant)
class CapabilityGrantAdmin(
    ReadOnlyAdminMixin,
    EditionApplicableAuthorityAdmin,
):
    list_display = (
        "principal",
        "capability_code",
        "scope",
        "state",
        "term",
        "is_delegated",
    )
    list_display_links = ("principal", "capability_code")
    list_filter = (
        "capability_code",
        "organization",
        "edition",
        "revoked_at",
        "effective_from",
        "expires_at",
    )
    search_fields = (
        "principal__display_name",
        "principal__email",
        "capability_code",
        "organization__name",
        "organization__slug",
        "edition__name",
        "edition__slug",
        "granted_by__display_name",
        "approved_by__display_name",
        "revoked_by__display_name",
        "reason",
        "revocation_reason",
    )
    ordering = ("organization__name", "principal__display_name", "capability_code")
    list_select_related = (
        "organization",
        "edition",
        "principal",
        "granted_by",
        "approved_by",
        "revoked_by",
        "delegated_from",
    )
    list_per_page = 50
    date_hierarchy = "effective_from"
    readonly_fields = (
        "organization",
        "edition",
        "principal",
        "capability_code",
        "state",
        "effective_from",
        "expires_at",
        "revoked_at",
        "granted_by",
        "approved_by",
        "revoked_by",
        "delegated_from",
        "reason",
        "revocation_reason",
        "id",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            "Authority",
            {
                "fields": (
                    "principal",
                    "capability_code",
                    "organization",
                    "edition",
                    "state",
                )
            },
        ),
        (
            "Term and provenance",
            {
                "fields": (
                    "effective_from",
                    "expires_at",
                    "revoked_at",
                    "granted_by",
                    "approved_by",
                    "revoked_by",
                    "delegated_from",
                    "reason",
                    "revocation_reason",
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

    @admin.display(description="Scope", ordering="edition__name")
    def scope(self, obj: CapabilityGrant) -> str:
        if obj.edition is not None:
            return obj.edition.name
        return f"{obj.organization.name} (organization-wide)"

    @admin.display(description="State", ordering="revoked_at")
    def state(self, obj: CapabilityGrant) -> str:
        return _authority_state(
            effective_from=obj.effective_from,
            expires_at=obj.expires_at,
            revoked_at=obj.revoked_at,
        )

    @admin.display(description="Term", ordering="effective_from")
    def term(self, obj: CapabilityGrant) -> str:
        return format_html(
            '<span title="{}">{}</span>',
            _full_term_label(
                effective_from=obj.effective_from,
                expires_at=obj.expires_at,
            ),
            _term_label(
                effective_from=obj.effective_from,
                expires_at=obj.expires_at,
            ),
        )

    @admin.display(boolean=True, description="Delegated")
    def is_delegated(self, obj: CapabilityGrant) -> bool:
        return obj.delegated_from_id is not None


@admin.register(RoleBundle)
class RoleBundleAdmin(
    ReadOnlyAdminMixin,
    EditionContextAdmin,
):
    edition_context_lookup = "organization_id"
    edition_context_value_attribute = "organization_id"
    list_display = (
        "name",
        "code",
        "version",
        "organization",
        "capabilities",
        "assignment_count",
    )
    list_display_links = ("name", "code")
    list_filter = ("organization", "code", "version")
    search_fields = (
        "name",
        "code",
        "organization__name",
        "organization__slug",
        "capability_codes",
        "created_by__display_name",
        "approved_by__display_name",
        "reason",
    )
    ordering = ("organization__name", "name", "-version")
    list_select_related = ("organization", "created_by", "approved_by")
    list_per_page = 50
    readonly_fields = (
        "organization",
        "code",
        "name",
        "version",
        "capabilities",
        "created_by",
        "approved_by",
        "reason",
        "id",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            "Role version",
            {"fields": ("name", "code", "version", "organization")},
        ),
        ("Capabilities", {"fields": ("capabilities",)}),
        (
            "Provenance",
            {"fields": ("created_by", "approved_by", "reason")},
        ),
        (
            "Technical details",
            {
                "classes": ("collapse",),
                "fields": ("id", "created_at", "updated_at"),
            },
        ),
    )

    def get_queryset(self, request: HttpRequest) -> QuerySet[RoleBundle]:
        queryset = cast(
            QuerySet[RoleBundle],
            super().get_queryset(request),
        )
        return queryset.select_related(
            "organization",
            "created_by",
            "approved_by",
        ).annotate(_assignment_count=Count("assignments", distinct=True))

    @admin.display(description="Capabilities")
    def capabilities(self, obj: RoleBundle) -> str:
        full_label = ", ".join(obj.capability_codes)
        visible_codes = obj.capability_codes[:VISIBLE_CAPABILITY_COUNT]
        compact_label = ", ".join(visible_codes)
        remaining = len(obj.capability_codes) - len(visible_codes)
        if remaining:
            compact_label = f"{compact_label} +{remaining}"
        return format_html(
            '<span title="{}">{}</span>',
            full_label,
            compact_label,
        )

    @admin.display(ordering="_assignment_count", description="Assignments")
    def assignment_count(self, obj: RoleBundle) -> int:
        return int(getattr(obj, "_assignment_count", 0))


@admin.register(RoleAssignment)
class RoleAssignmentAdmin(
    ReadOnlyAdminMixin,
    EditionApplicableAuthorityAdmin,
):
    list_display = (
        "principal",
        "role",
        "scope",
        "state",
        "term",
    )
    list_display_links = ("principal", "role")
    list_filter = (
        "organization",
        "edition",
        "role_bundle",
        "revoked_at",
        "effective_from",
        "expires_at",
    )
    search_fields = (
        "principal__display_name",
        "principal__email",
        "role_bundle__name",
        "role_bundle__code",
        "organization__name",
        "organization__slug",
        "edition__name",
        "edition__slug",
        "granted_by__display_name",
        "approved_by__display_name",
        "revoked_by__display_name",
        "reason",
        "revocation_reason",
    )
    ordering = ("organization__name", "principal__display_name", "role_bundle__name")
    list_select_related = (
        "organization",
        "edition",
        "principal",
        "role_bundle",
        "granted_by",
        "approved_by",
        "revoked_by",
    )
    list_per_page = 50
    date_hierarchy = "effective_from"
    readonly_fields = (
        "organization",
        "edition",
        "principal",
        "role_bundle",
        "state",
        "effective_from",
        "expires_at",
        "revoked_at",
        "granted_by",
        "approved_by",
        "revoked_by",
        "reason",
        "revocation_reason",
        "id",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            "Assignment",
            {
                "fields": (
                    "principal",
                    "role_bundle",
                    "organization",
                    "edition",
                    "state",
                )
            },
        ),
        (
            "Term and provenance",
            {
                "fields": (
                    "effective_from",
                    "expires_at",
                    "revoked_at",
                    "granted_by",
                    "approved_by",
                    "revoked_by",
                    "reason",
                    "revocation_reason",
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

    @admin.display(description="Scope", ordering="edition__name")
    def scope(self, obj: RoleAssignment) -> str:
        if obj.edition is not None:
            return obj.edition.name
        return f"{obj.organization.name} (organization-wide)"

    @admin.display(description="Role", ordering="role_bundle__name")
    def role(self, obj: RoleAssignment) -> str:
        return f"{obj.role_bundle.name} v{obj.role_bundle.version}"

    @admin.display(description="State", ordering="revoked_at")
    def state(self, obj: RoleAssignment) -> str:
        return _authority_state(
            effective_from=obj.effective_from,
            expires_at=obj.expires_at,
            revoked_at=obj.revoked_at,
        )

    @admin.display(description="Term", ordering="effective_from")
    def term(self, obj: RoleAssignment) -> str:
        return format_html(
            '<span title="{}">{}</span>',
            _full_term_label(
                effective_from=obj.effective_from,
                expires_at=obj.expires_at,
            ),
            _term_label(
                effective_from=obj.effective_from,
                expires_at=obj.expires_at,
            ),
        )
