"""Bootstrap administration for platform accounts."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.db import models
from django.db.models import QuerySet
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.safestring import SafeString, mark_safe

from maru.core.admin import ReadOnlyAdminMixin
from maru.events.admin_context import selected_admin_edition
from maru.identity.models import (
    Account,
    AccountRestriction,
    AccountSecurityEvent,
    AccountSession,
    IdentityAbuseBucket,
    IdentityChallenge,
    RestrictionAppeal,
)


def _admin_change_link(obj: models.Model, label: str) -> SafeString:
    model_meta = obj._meta
    url = reverse(
        f"admin:{model_meta.app_label}_{model_meta.model_name}_change",
        args=(obj.pk,),
    )
    return format_html('<a href="{}">{}</a>', url, label)


@admin.register(Account)
class AccountAdmin(UserAdmin):  # type: ignore[type-arg]
    ordering = ("display_name", "email")
    list_display = (
        "person",
        "login_handle",
        "email",
        "account_kind",
        "preferred_language",
        "convention_record_count",
        "restriction_state",
        "email_verified_at",
        "is_active",
        "is_staff",
        "is_superuser",
        "date_joined",
    )
    list_display_links = ("person", "login_handle", "email")
    list_filter = (
        "is_active",
        "is_staff",
        "is_superuser",
        "account_kind",
        "preferred_language",
        "email_verified_at",
    )
    search_fields = ("email", "login_handle", "display_name")
    date_hierarchy = "date_joined"
    list_per_page = 50
    readonly_fields = (
        "id",
        "date_joined",
        "last_login",
        "email_verified_at",
        "account_kind",
        "organizer_relationships",
        "registration_history",
    )
    fieldsets = (
        ("Sign-in", {"fields": ("email", "login_handle", "password")}),
        (
            "Profile",
            {"fields": ("display_name", "preferred_language", "email_verified_at")},
        ),
        (
            "Bootstrap administration access",
            {
                "fields": (
                    "account_kind",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                )
            },
        ),
        (
            "Organizer-managed relationships",
            {
                "description": (
                    "These roles, participation records, restrictions, and "
                    "registrations are managed by organizers rather than being "
                    "editable profile claims."
                ),
                "fields": (
                    "organizer_relationships",
                    "registration_history",
                ),
            },
        ),
        (
            "Technical details",
            {
                "classes": ("collapse",),
                "fields": ("id", "date_joined", "last_login"),
            },
        ),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "login_handle",
                    "display_name",
                    "password1",
                    "password2",
                    "is_active",
                    "is_staff",
                ),
            },
        ),
    )

    @admin.display(description="Person", ordering="display_name")
    def person(self, obj: Account) -> str:
        return obj.display_name or obj.email

    @admin.display(description="Registrations")
    def convention_record_count(self, obj: Account) -> int:
        return obj.registrations.count()

    @admin.display(description="Status")
    def restriction_state(self, obj: Account) -> str:
        if not obj.is_active:
            return "Inactive"
        if obj.restrictions.filter(status="active").exists():
            return "Restricted"
        return "Active"

    @admin.display(description="Roles, capacities, and restrictions")
    def organizer_relationships(self, obj: Account) -> SafeString:
        roles = list(
            obj.role_assignments.select_related(
                "organization",
                "edition",
                "role_bundle",
            ).order_by("organization__name", "role_bundle__name")
        )
        capacities = [
            capacity
            for participation in obj.event_participations.prefetch_related(
                "capacities",
            ).select_related("edition")
            for capacity in participation.capacities.all()
        ]
        restrictions = list(
            obj.restrictions.select_related(
                "organization",
                "edition",
            ).order_by("-effective_at")
        )
        role_links = format_html_join(
            "",
            "<li>{} — {}</li>",
            (
                (
                    _admin_change_link(
                        assignment,
                        assignment.role_bundle.name,
                    ),
                    assignment.edition or assignment.organization,
                )
                for assignment in roles
            ),
        ) or mark_safe("<li>None assigned</li>")
        capacity_links = format_html_join(
            "",
            "<li>{} — {}</li>",
            (
                (
                    _admin_change_link(
                        capacity,
                        capacity.label_snapshot,
                    ),
                    capacity.participation.edition,
                )
                for capacity in capacities
            ),
        ) or mark_safe("<li>None recorded</li>")
        restriction_links = format_html_join(
            "",
            "<li>{} — {} ({})</li>",
            (
                (
                    _admin_change_link(
                        restriction,
                        restriction.get_kind_display(),
                    ),
                    restriction.get_status_display(),
                    restriction.reason_code,
                )
                for restriction in restrictions
            ),
        ) or mark_safe("<li>No organizer restrictions</li>")
        return format_html(
            (
                "<strong>Roles</strong><ul>{}</ul>"
                "<strong>Convention capacities</strong><ul>{}</ul>"
                "<strong>Restrictions</strong><ul>{}</ul>"
            ),
            role_links,
            capacity_links,
            restriction_links,
        )

    @admin.display(description="Registration, ticket, and payment history")
    def registration_history(self, obj: Account) -> SafeString:
        registrations = list(
            obj.registrations.select_related("edition").prefetch_related(
                "entitlements",
                "financial_ledger",
                "payment_attempts",
            )
        )
        if not registrations:
            return mark_safe("<span>No convention registrations.</span>")
        rows = []
        for registration in registrations:
            paid_minor = sum(
                entry.amount_minor
                for entry in registration.financial_ledger.all()
                if entry.kind == "payment" and entry.direction == "inflow"
            )
            if not paid_minor:
                paid_minor = sum(
                    attempt.amount_minor
                    for attempt in registration.payment_attempts.all()
                    if attempt.status == "succeeded"
                )
            infinity = registration.entitlements.filter(
                code="infinity-ticket",
                status="active",
            ).exists()
            rows.append(
                (
                    _admin_change_link(registration, registration.reference),
                    registration.edition.name,
                    registration.get_state_display(),
                    registration.product_name_snapshot,
                    (f"{paid_minor / 100:.2f} {registration.currency_snapshot}"),
                    "Yes" if infinity else "No",
                )
            )
        return format_html(
            (
                '<table class="listing"><thead><tr><th>Registration</th>'
                "<th>Edition</th><th>Status</th><th>Ticket</th>"
                "<th>Paid</th><th>Infinity holder</th></tr></thead>"
                "<tbody>{}</tbody></table>"
            ),
            format_html_join(
                "",
                (
                    '<tr><th scope="row">{}</th><td>{}</td><td>{}</td>'
                    "<td>{}</td><td>{}</td><td>{}</td></tr>"
                ),
                rows,
            ),
        )

    def get_queryset(self, request: HttpRequest) -> QuerySet[Account]:
        queryset = super().get_queryset(request)
        edition = selected_admin_edition(request)
        if edition is None or request.path == "/admin/autocomplete/":
            return queryset
        return queryset.filter(event_participations__edition_id=edition.id).distinct()


@admin.register(AccountSecurityEvent)
class AccountSecurityEventAdmin(
    ReadOnlyAdminMixin,
    admin.ModelAdmin,  # type: ignore[type-arg]
):
    list_display = (
        "account",
        "event_type",
        "outcome",
        "occurred_at",
        "source_channel",
    )
    list_display_links = ("account", "event_type")
    list_filter = ("event_type", "outcome", "source_channel", "occurred_at")
    search_fields = ("account__display_name", "account__email", "detail_code")
    ordering = ("-occurred_at",)
    list_select_related = ("account",)
    date_hierarchy = "occurred_at"
    readonly_fields = (
        "account",
        "event_type",
        "outcome",
        "occurred_at",
        "source_channel",
        "detail_code",
        "id",
        "created_at",
        "updated_at",
    )


@admin.register(IdentityChallenge)
class IdentityChallengeAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = (
        "account",
        "purpose",
        "delivery_status",
        "delivery_attempt_count",
        "expires_at",
        "consumed_at",
    )
    list_filter = ("purpose", "delivery_status", "expires_at", "consumed_at")
    search_fields = ("account__email",)
    readonly_fields = (
        "account",
        "purpose",
        "token_digest",
        "email_snapshot",
        "expires_at",
        "consumed_at",
        "attempt_count",
        "request_fingerprint",
        "delivery_status",
        "delivery_attempt_count",
        "last_delivery_attempt_at",
        "delivered_at",
        "delivery_error_code",
        "id",
        "created_at",
        "updated_at",
    )


@admin.register(AccountSession)
class AccountSessionAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = (
        "account",
        "label",
        "last_seen_at",
        "step_up_verified_at",
        "revoked_at",
    )
    list_filter = ("created_channel", "revoked_at", "step_up_verified_at")
    search_fields = ("account__email", "account__display_name", "label")
    exclude = ("session_key_digest", "session")


@admin.register(IdentityAbuseBucket)
class IdentityAbuseBucketAdmin(
    ReadOnlyAdminMixin,
    admin.ModelAdmin,  # type: ignore[type-arg]
):
    list_display = (
        "flow",
        "window_started_at",
        "attempt_count",
        "blocked_until",
    )
    list_filter = ("flow", "window_started_at", "blocked_until")
    exclude = ("subject_digest",)


class RestrictionAppealInline(admin.TabularInline):  # type: ignore[type-arg]
    model = RestrictionAppeal
    extra = 0
    can_delete = False
    readonly_fields = (
        "account",
        "statement",
        "status",
        "submitted_at",
        "decided_at",
        "decided_by",
        "decision_summary",
    )


@admin.register(AccountRestriction)
class AccountRestrictionAdmin(
    ReadOnlyAdminMixin,
    admin.ModelAdmin,  # type: ignore[type-arg]
):
    list_display = (
        "account",
        "organization",
        "edition",
        "kind",
        "status",
        "effective_at",
        "expires_at",
    )
    list_filter = ("organization", "edition", "kind", "status")
    search_fields = (
        "account__email",
        "account__display_name",
        "reason_code",
        "internal_reference",
    )
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "revoked_at",
        "revoked_by",
        "revocation_reason",
    )
    inlines = (RestrictionAppealInline,)
