from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.contrib import admin
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils import timezone

from maru.authorization.admin import (
    _authority_state,
    _full_term_label,
    _term_label,
)
from maru.authorization.models import CapabilityGrant, RoleAssignment, RoleBundle
from maru.core.templatetags.admin_help import (
    FUNCTION_GROUP_BY_APP,
    MODEL_PAGE_HELP,
)
from maru.events.models import (
    ArchiveAmendment,
    EditionLifecycleTransition,
    EditionReadinessGate,
    EventEdition,
)
from maru.identity.models import Account, AccountSecurityEvent
from maru.organizations.models import (
    ConventionSeries,
    Organization,
    OrganizationMembership,
)
from maru.participation.models import Participation, ParticipationCapacity
from maru.privacyops.models import RetentionPolicy
from maru.registration.admin import (
    AdmissionProductInline,
    RegistrationQuestionInline,
    RegistrationSectionInline,
    TemplateProductInline,
    TemplateQuestionInline,
    TemplateSectionInline,
)
from maru.registration.models import (
    AttendeeRegistrationProfile,
    CheckInRecord,
    Entitlement,
    PaymentAttempt,
    Registration,
    RegistrationAdjustment,
    RegistrationConfiguration,
    RegistrationSubmission,
    RegistrationTemplate,
    RegistrationTimelineEntry,
    TemplateStatus,
)
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    RegistrationConfigurationFactory,
    RegistrationTemplateFactory,
    RoleAssignmentFactory,
    RoleBundleFactory,
    create_reference_convention,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _admin_client() -> tuple[Client, Account]:
    administrator = AccountFactory(
        email="bootstrap-admin@example.invalid",
        display_name="Bootstrap Administrator",
        is_staff=True,
        is_superuser=True,
    )
    client = Client()
    client.force_login(administrator)
    return client, administrator


def test_every_registered_maru_changelist_loads() -> None:
    client, _ = _admin_client()
    create_reference_convention()
    registered_models = [
        model for model in admin.site._registry if model._meta.app_label != "auth"
    ]

    for model in registered_models:
        url_name = f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist"
        response = client.get(reverse(url_name))
        assert response.status_code == 200, url_name
        content = response.content.decode()
        assert 'class="maru-page-help"' in content, url_name
        assert "For example:" in content, url_name


def test_participation_admin_is_human_readable_and_searchable() -> None:
    client, _ = _admin_client()
    reference = create_reference_convention()

    response = client.get(reverse("admin:participation_participation_changelist"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Person" in content
    assert "Edition" in content
    assert "Capacities" in content
    assert "Alex Fox" in content
    assert "Pawprint Convention 2030" in content
    assert "Volunteer" in content
    assert str(reference.primary_account.id) not in content
    assert "Delete selected participations" not in content

    search_response = client.get(
        reverse("admin:participation_participation_changelist"),
        {"q": "Alex Fox"},
    )
    search_content = search_response.content.decode()
    assert search_response.status_code == 200
    assert "Alex Fox" in search_content
    assert "River Wolf" not in search_content


def test_readiness_gate_admin_is_read_only_and_hides_account_ids() -> None:
    client, _ = _admin_client()
    reference = create_reference_convention()
    reviewer = AccountFactory(display_name="Finance Reviewer")
    EditionReadinessGate.objects.create(
        organization_id=reference.primary_organization.id,
        edition=reference.current_edition,
        code=EditionReadinessGate.Code.FINANCE,
        status=EditionReadinessGate.Status.APPROVED,
        evidence_reference="Finance reconciliation report 2030-08-31",
        review_summary="Payments, refunds, and disputes were reconciled.",
        reviewed_by_id=reviewer.id,
        reviewed_at=timezone.now(),
    )

    changelist = client.get(reverse("admin:events_editionreadinessgate_changelist"))

    assert changelist.status_code == 200
    content = changelist.content.decode()
    assert "Finance Reviewer" in content
    assert str(reviewer.id) not in content
    assert "Add edition readiness gate" not in content

    add_response = client.get(reverse("admin:events_editionreadinessgate_add"))
    assert add_response.status_code == 403


def test_admin_branding_and_domain_language_are_clear() -> None:
    client, _ = _admin_client()

    response = client.get(reverse("admin:index"))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Maru Administration" in content
    assert "Convention work" in content
    assert "Specialist records" in content
    assert content.count('aria-label="Administration"') == 1
    assert content.index("/static/admin/css/responsive.css") < content.index(
        "/static/core/admin-responsive.css"
    )
    assert "Continue convention setup" in content
    assert f"{reverse('management-console')}?view=setup" in content
    assert "Quick start" not in content
    assert 'class="maru-admin-quick-start"' not in content
    assert "Need a technical record?" in content
    assert "Open specialist records" in content
    assert "Recent work" in content
    assert "All administration areas" not in content
    assert "First convention setup" not in content
    assert "/admin/auth/group/" not in content


def test_global_quick_start_is_absent_from_other_admin_views() -> None:
    client, _ = _admin_client()

    response = client.get(reverse("admin:identity_account_changelist"))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'class="maru-admin-quick-start"' not in content
    assert "Build a convention in a safe order" not in content
    assert "Open guide" not in content
    assert "All administration areas" not in content


def test_admin_home_keeps_one_specialist_gateway_without_duplicating_directory() -> (
    None
):
    client, _ = _admin_client()

    response = client.get(reverse("admin:index"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Quick start" not in content
    assert "All administration areas" not in content
    assert content.count("Open specialist records") == 1
    assert "Need a technical record?" in content
    assert f"{reverse('management-console')}?view=setup" in content
    assert reverse("management-console") in content

    app_list = response.context["app_list"]
    app_names = [app["name"] for app in app_list]
    assert app_names == sorted(app_names, key=lambda value: str(value).casefold())
    for app in app_list:
        model_names = [model["name"] for model in app["models"]]
        assert model_names == sorted(
            model_names,
            key=lambda value: str(value).casefold(),
        )


def test_specialist_gateway_replaces_directory_and_help_covers_registered_items() -> (
    None
):
    client, _ = _admin_client()

    response = client.get(reverse("admin:index"))

    registered_models = {
        (model._meta.app_label, model._meta.model_name)
        for model in admin.site._registry
        if model._meta.app_label != "auth"
    }
    registered_apps = {app_label for app_label, _ in registered_models}
    assert registered_models <= MODEL_PAGE_HELP.keys()
    assert registered_apps <= FUNCTION_GROUP_BY_APP.keys()
    assert all("For example:" in MODEL_PAGE_HELP[key] for key in registered_models)

    content = response.content.decode()
    assert "Need a technical record?" in content
    assert "data-navigation-specialist-gateway" in content
    assert 'data-navigation-group="specialist-records"' in content
    assert "maru-admin-app--foundation" not in content


def test_removed_first_convention_setup_route_is_not_available() -> None:
    client, _ = _admin_client()

    response = client.get("/admin/workforce/bootstrap/")

    assert response.status_code == 404


def test_admin_app_change_and_login_pages_explain_their_purpose() -> None:
    client, administrator = _admin_client()

    app_response = client.get(reverse("admin:app_list", args=("registration",)))
    change_response = client.get(
        reverse("admin:identity_account_change", args=(administrator.id,))
    )
    client.logout()
    login_response = client.get(reverse("admin:login"))

    assert "Use this area for registration setup" in app_response.content.decode()
    assert "Use this read-only specialist page to inspect minimized identity" in (
        change_response.content.decode()
    )
    assert "Use this page to enter bootstrap administration" in (
        login_response.content.decode()
    )
    assert all(
        'class="maru-page-help"' in response.content.decode()
        for response in (app_response, change_response, login_response)
    )


def test_model_labels_prefer_people_and_scope_over_identifiers() -> None:
    reference = create_reference_convention()
    membership = OrganizationMembership.objects.get(
        account=reference.primary_account,
        organization=reference.primary_organization,
    )
    participation = Participation.objects.get(
        account=reference.primary_account,
        edition=reference.current_edition,
    )
    capacity = participation.capacities.get(code="volunteer")
    grant = CapabilityGrantFactory(
        organization=reference.primary_organization,
        principal=reference.primary_account,
        granted_by=reference.primary_account,
    )
    role = RoleBundleFactory(
        organization=reference.primary_organization,
        code="demo-reader",
        name="Demo reader",
    )
    assignment = RoleAssignmentFactory(
        organization=reference.primary_organization,
        principal=reference.primary_account,
        role_bundle=role,
        granted_by=reference.primary_account,
    )
    transition = EditionLifecycleTransition(
        edition=reference.current_edition,
        from_state=EventEdition.Lifecycle.DRAFT,
        to_state=EventEdition.Lifecycle.PREPARING,
        actor_id=reference.primary_account.id,
        reason="Begin preparation.",
    )
    amendment = ArchiveAmendment(
        edition=reference.current_edition,
        actor_id=reference.primary_account.id,
        reason="Correct a historical label.",
        summary="Corrected the public convention label.",
    )

    assert str(reference.current_edition.series) == (
        "Pawprint Convention — Northstar Events"
    )
    assert str(membership) == ("Alex Fox — Operations volunteer at Northstar Events")
    assert str(participation) == "Alex Fox — Pawprint Convention 2030"
    assert str(capacity) == ("Volunteer — Alex Fox — Pawprint Convention 2030")
    assert str(grant) == ("Alex Fox — events.view_basic for Northstar Events")
    assert str(role) == "Demo reader v1 — Northstar Events"
    assert str(assignment) == ("Alex Fox — Demo reader for Northstar Events")
    assert str(transition) == ("Pawprint Convention 2030: Draft → Preparing")
    assert str(amendment) == (
        "Pawprint Convention 2030: Corrected the public convention label."
    )


def test_command_owned_history_and_authority_are_view_only() -> None:
    _, administrator = _admin_client()
    request = RequestFactory().get("/admin/")
    request.user = administrator

    for model in (
        CapabilityGrant,
        RoleBundle,
        RoleAssignment,
        EditionLifecycleTransition,
        ArchiveAmendment,
        RetentionPolicy,
    ):
        model_admin = admin.site._registry[model]
        assert not model_admin.has_add_permission(request)
        assert not model_admin.has_change_permission(request)
        assert not model_admin.has_delete_permission(request)


def test_registration_bootstrap_admin_records_the_creator_on_new_drafts() -> None:
    _, administrator = _admin_client()
    reference = create_reference_convention()
    request = RequestFactory().post("/admin/registration/")
    request.user = administrator
    form = SimpleNamespace()

    template = RegistrationTemplate(
        organization=reference.primary_organization,
        series=reference.current_edition.series,
        code="manual-registration",
        name="Manual registration",
        description="Created through bootstrap administration.",
        version=1,
    )
    admin.site._registry[RegistrationTemplate].save_model(
        request,
        template,
        form,  # type: ignore[arg-type]
        change=False,
    )
    assert template.created_by_id == administrator.id

    configuration = RegistrationConfiguration(
        organization=reference.primary_organization,
        edition=reference.current_edition,
        name="Manual registration",
        version=1,
        opens_at=timezone.now() + timedelta(days=30),
        closes_at=timezone.now() + timedelta(days=60),
        capacity=100,
        currency="HUF",
    )
    admin.site._registry[RegistrationConfiguration].save_model(
        request,
        configuration,
        form,  # type: ignore[arg-type]
        change=False,
    )
    assert configuration.created_by_id == administrator.id


def test_draft_registration_builder_items_can_be_removed_safely() -> None:
    _, administrator = _admin_client()
    request = RequestFactory().get("/admin/registration/")
    request.user = administrator
    draft_template = RegistrationTemplateFactory()
    published_template = RegistrationTemplateFactory(
        status=TemplateStatus.PUBLISHED,
        published_at=timezone.now(),
    )
    draft_configuration = RegistrationConfigurationFactory()
    active_configuration = RegistrationConfigurationFactory(
        status="active",
        activated_at=timezone.now(),
        edition__series__organization__slug="active-inline-organization",
    )

    for inline_class in (
        TemplateSectionInline,
        TemplateQuestionInline,
        TemplateProductInline,
    ):
        inline = inline_class(RegistrationTemplate, admin.site)
        assert inline.has_delete_permission(request, draft_template)
        assert not inline.has_delete_permission(request, published_template)

    for inline_class in (
        RegistrationSectionInline,
        RegistrationQuestionInline,
        AdmissionProductInline,
    ):
        inline = inline_class(RegistrationConfiguration, admin.site)
        assert inline.has_delete_permission(request, draft_configuration)
        assert not inline.has_delete_permission(request, active_configuration)


def test_archived_records_are_presented_as_view_only() -> None:
    _, administrator = _admin_client()
    request = RequestFactory().get("/admin/")
    request.user = administrator
    reference = create_reference_convention()
    participation = Participation.objects.get(
        account=reference.primary_account,
        edition=reference.current_edition,
    )
    capacity = participation.capacities.get(code="volunteer")
    reference.current_edition.lifecycle = EventEdition.Lifecycle.ARCHIVED
    participation.edition.lifecycle = EventEdition.Lifecycle.ARCHIVED
    capacity.participation.edition.lifecycle = EventEdition.Lifecycle.ARCHIVED

    edition_admin = admin.site._registry[EventEdition]
    participation_admin = admin.site._registry[Participation]
    capacity_admin = admin.site._registry[ParticipationCapacity]

    assert not edition_admin.has_change_permission(
        request,
        reference.current_edition,
    )
    assert not participation_admin.has_change_permission(request, participation)
    assert not capacity_admin.has_change_permission(request, capacity)


def test_all_expected_models_use_custom_admin_classes() -> None:
    expected_models = (
        Account,
        Organization,
        ConventionSeries,
        OrganizationMembership,
        EventEdition,
        EditionLifecycleTransition,
        ArchiveAmendment,
        Participation,
        ParticipationCapacity,
        CapabilityGrant,
        RoleBundle,
        RoleAssignment,
        AccountSecurityEvent,
        RegistrationTemplate,
        RegistrationConfiguration,
        Registration,
        RegistrationSubmission,
        AttendeeRegistrationProfile,
        PaymentAttempt,
        RegistrationAdjustment,
        Entitlement,
        CheckInRecord,
        RegistrationTimelineEntry,
    )

    assert all(model in admin.site._registry for model in expected_models)
    assert all(
        type(admin.site._registry[model]) is not admin.ModelAdmin
        for model in expected_models
    )


def test_compact_admin_summaries_keep_exact_context_available() -> None:
    reference = create_reference_convention()
    now = timezone.now()
    later = now + timedelta(days=400)
    earlier = now - timedelta(days=400)

    assert (
        _authority_state(
            effective_from=later,
            expires_at=None,
            revoked_at=None,
        )
        == "Scheduled"
    )
    assert (
        _authority_state(
            effective_from=earlier,
            expires_at=now,
            revoked_at=None,
        )
        == "Expired"
    )
    assert (
        _authority_state(
            effective_from=earlier,
            expires_at=None,
            revoked_at=now,
        )
        == "Revoked"
    )
    assert (
        _authority_state(
            effective_from=earlier,
            expires_at=None,
            revoked_at=None,
        )
        == "Active"
    )
    assert _term_label(effective_from=earlier, expires_at=None).startswith("Since ")
    assert _term_label(effective_from=now, expires_at=now) == str(now.year)
    assert "-" in _term_label(effective_from=earlier, expires_at=later)
    assert "Present" in _full_term_label(
        effective_from=earlier,
        expires_at=None,
    )

    role = RoleBundleFactory(
        organization=reference.primary_organization,
        capability_codes=[
            "events.view_basic",
            "events.transition",
            "participation.view_staff_summary",
            "audit.view_security",
        ],
    )
    role_admin = admin.site._registry[RoleBundle]
    role_summary = str(role_admin.capabilities(role))
    assert "events.view_basic" in role_summary
    assert "participation.view_staff_summary" in role_summary
    assert "+1" in role_summary

    grant = CapabilityGrantFactory(
        organization=reference.primary_organization,
        edition=reference.current_edition,
        principal=reference.primary_account,
        granted_by=reference.primary_account,
        effective_from=earlier,
    )
    grant_admin = admin.site._registry[CapabilityGrant]
    assert grant_admin.scope(grant) == "Pawprint Convention 2030"
    assert grant_admin.state(grant) == "Active"
    assert "Since" in str(grant_admin.term(grant))
    assert not grant_admin.is_delegated(grant)

    assignment = RoleAssignmentFactory(
        organization=reference.primary_organization,
        edition=reference.current_edition,
        principal=reference.primary_account,
        role_bundle=role,
        granted_by=reference.primary_account,
        effective_from=earlier,
    )
    assignment_admin = admin.site._registry[RoleAssignment]
    assert assignment_admin.scope(assignment) == "Pawprint Convention 2030"
    assignment.edition = None
    assert assignment_admin.scope(assignment) == "Northstar Events (organization-wide)"
    assert assignment_admin.role(assignment).endswith("v1")
    assert assignment_admin.state(assignment) == "Active"
    assert "Since" in str(assignment_admin.term(assignment))

    participation = Participation.objects.get(
        account=reference.primary_account,
        edition=reference.current_edition,
    )
    capacity = participation.capacities.get(code="volunteer")
    capacity_admin = admin.site._registry[ParticipationCapacity]
    assert capacity_admin.term(capacity) == "Not recorded"
    capacity.started_at = earlier
    assert capacity_admin.term(capacity).endswith("→ Present")
    capacity.started_at = None
    capacity.ended_at = now
    assert capacity_admin.term(capacity).startswith("Unknown →")
