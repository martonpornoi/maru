import re
from collections.abc import Iterable
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from django.contrib import admin
from django.db import connection
from django.http import HttpResponse
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from maru.authorization.models import CapabilityGrant, RoleAssignment, RoleBundle
from maru.events.admin_context import (
    ADMIN_EDITION_SESSION_KEY,
    EditionContextAdmin,
    admin_edition_options,
)
from maru.events.models import (
    ArchiveAmendment,
    EditionLifecycleTransition,
    EventEdition,
)
from maru.identity.models import Account
from maru.organizations.models import (
    ConventionSeries,
    Organization,
    OrganizationMembership,
)
from maru.participation.models import Participation, ParticipationCapacity
from maru.registration.models import (
    AttendeeRegistrationProfile,
    CheckInRecord,
    Entitlement,
    PaymentAttempt,
    Registration,
    RegistrationConfiguration,
    RegistrationSubmission,
    RegistrationTemplate,
    RegistrationTimelineEntry,
)
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    ConventionSeriesFactory,
    EventEditionFactory,
    RegistrationConfigurationFactory,
    RegistrationTemplateFactory,
    RoleAssignmentFactory,
    RoleBundleFactory,
    create_reference_convention,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _admin_client() -> Client:
    administrator = AccountFactory(
        is_staff=True,
        is_superuser=True,
    )
    client = Client()
    client.force_login(administrator)
    return client


def _result_ids(response: HttpResponse) -> set[object]:
    return {item.id for item in response.context["cl"].result_list}


def _selector_edition_ids(response: HttpResponse) -> set[UUID]:
    return {
        UUID(value)
        for value in re.findall(
            r'<option\s+value="([0-9a-f-]{36})"',
            response.content.decode(),
        )
    }


def _select_edition(client: Client, edition: EventEdition) -> None:
    response = client.post(
        reverse("admin-edition-context"),
        {
            "edition_id": str(edition.id),
            "next": reverse("admin:index"),
        },
    )
    assert response.status_code == 302


def test_platform_admin_lists_and_selects_all_editions_without_participation() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    client = Client()
    client.force_login(administrator)
    first = EventEditionFactory(name="Synthetic Platform Scope One")
    second = EventEditionFactory(name="Synthetic Platform Scope Two")

    response = client.get(reverse("admin:index"))

    assert response.status_code == 200
    assert _selector_edition_ids(response) == {first.id, second.id}
    assert not Participation.objects.filter(account=administrator).exists()

    _select_edition(client, second)
    assert client.session[ADMIN_EDITION_SESSION_KEY] == str(second.id)


def test_active_staff_selector_scopes_grants_and_role_assignments_in_one_query() -> (
    None
):
    staff = AccountFactory(is_staff=True)
    client = Client()
    client.force_login(staff)
    now = timezone.now()

    organization_grant_edition = EventEditionFactory(name="Organization Grant Primary")
    organization_grant_sibling = EventEditionFactory(
        organization=organization_grant_edition.organization,
        series=organization_grant_edition.series,
        slug="organization-grant-sibling",
        name="Organization Grant Sibling",
    )
    CapabilityGrantFactory(
        principal=staff,
        organization=organization_grant_edition.organization,
        edition=None,
        effective_from=now - timedelta(minutes=5),
    )

    edition_grant = EventEditionFactory(name="Matching Edition Grant")
    edition_grant_sibling = EventEditionFactory(
        organization=edition_grant.organization,
        series=edition_grant.series,
        slug="edition-grant-sibling",
        name="Edition Grant Sibling",
    )
    CapabilityGrantFactory(
        principal=staff,
        organization=edition_grant.organization,
        edition=edition_grant,
        effective_from=now - timedelta(minutes=5),
    )

    organization_role_edition = EventEditionFactory(name="Organization Role Primary")
    organization_role_sibling = EventEditionFactory(
        organization=organization_role_edition.organization,
        series=organization_role_edition.series,
        slug="organization-role-sibling",
        name="Organization Role Sibling",
    )
    organization_role = RoleBundleFactory(
        organization=organization_role_edition.organization,
    )
    RoleAssignmentFactory(
        principal=staff,
        organization=organization_role_edition.organization,
        edition=None,
        role_bundle=organization_role,
        effective_from=now - timedelta(minutes=5),
    )

    edition_role = EventEditionFactory(name="Matching Edition Role")
    edition_role_sibling = EventEditionFactory(
        organization=edition_role.organization,
        series=edition_role.series,
        slug="edition-role-sibling",
        name="Edition Role Sibling",
    )
    edition_role_bundle = RoleBundleFactory(organization=edition_role.organization)
    RoleAssignmentFactory(
        principal=staff,
        organization=edition_role.organization,
        edition=edition_role,
        role_bundle=edition_role_bundle,
        effective_from=now - timedelta(minutes=5),
    )
    foreign = EventEditionFactory(name="Foreign Edition")

    response = client.get(reverse("admin:index"))
    options = admin_edition_options(response.wsgi_request)
    with CaptureQueriesContext(connection) as queries:
        rows = [
            (edition.id, edition.organization.name, edition.series.name)
            for edition in options["editions"]
        ]

    expected = {
        organization_grant_edition.id,
        organization_grant_sibling.id,
        edition_grant.id,
        organization_role_edition.id,
        organization_role_sibling.id,
        edition_role.id,
    }
    assert {row[0] for row in rows} == expected
    assert len(queries) == 1
    assert _selector_edition_ids(response) == expected

    _select_edition(client, organization_grant_sibling)
    for unavailable in (edition_grant_sibling, edition_role_sibling, foreign):
        denied = client.post(
            reverse("admin-edition-context"),
            {
                "edition_id": str(unavailable.id),
                "next": reverse("admin:index"),
            },
        )
        assert denied.status_code == 404
        assert client.session[ADMIN_EDITION_SESSION_KEY] == str(
            organization_grant_sibling.id
        )


def test_admin_selector_persists_and_clears_the_selected_edition() -> None:
    client = _admin_client()
    reference = create_reference_convention()

    response = client.post(
        reverse("admin-edition-context"),
        {
            "edition_id": str(reference.current_edition.id),
            "next": reverse("admin:participation_participation_changelist"),
        },
    )

    assert response.status_code == 302
    assert response["Location"] == reverse(
        "admin:participation_participation_changelist"
    )
    assert client.session[ADMIN_EDITION_SESSION_KEY] == str(
        reference.current_edition.id
    )

    index_response = client.get(reverse("admin:index"))
    content = index_response.content.decode()
    assert "Convention workspace" in content
    assert re.search(
        rf'value="{reference.current_edition.id}"\s+selected',
        content,
    )

    clear_response = client.post(
        reverse("admin-edition-context"),
        {
            "edition_id": "",
            "next": "https://example.invalid/not-allowed",
        },
    )

    assert clear_response.status_code == 302
    assert clear_response["Location"] == reverse("admin:index")
    assert ADMIN_EDITION_SESSION_KEY not in client.session


def test_selected_edition_scopes_foundation_people_and_event_records() -> None:
    client = _admin_client()
    reference = create_reference_convention()
    _select_edition(client, reference.current_edition)
    primary_participation = Participation.objects.get(
        account=reference.primary_account,
        edition=reference.current_edition,
    )
    other_participation = Participation.objects.get(
        account=reference.other_account,
        edition=reference.other_edition,
    )

    expectations: Iterable[tuple[str, object, object]] = (
        (
            "admin:identity_account_changelist",
            reference.primary_account.id,
            reference.other_account.id,
        ),
        (
            "admin:organizations_organization_changelist",
            reference.primary_organization.id,
            reference.other_organization.id,
        ),
        (
            "admin:organizations_conventionseries_changelist",
            reference.current_edition.series_id,
            reference.other_edition.series_id,
        ),
        (
            "admin:events_eventedition_changelist",
            reference.current_edition.id,
            reference.other_edition.id,
        ),
        (
            "admin:participation_participation_changelist",
            primary_participation.id,
            other_participation.id,
        ),
        (
            "admin:participation_participationcapacity_changelist",
            primary_participation.capacities.get().id,
            other_participation.capacities.get().id,
        ),
    )

    for url_name, included_id, excluded_id in expectations:
        response = client.get(reverse(url_name))
        assert response.status_code == 200
        result_ids = _result_ids(response)
        assert included_id in result_ids, url_name
        assert excluded_id not in result_ids, url_name

    other_change = client.get(
        reverse(
            "admin:participation_participation_change",
            args=(other_participation.id,),
        )
    )
    assert other_change.status_code == 302


def test_selected_edition_prefills_and_limits_ordinary_relationship_choices() -> None:
    client = _admin_client()
    reference = create_reference_convention()
    _select_edition(client, reference.current_edition)
    primary_participation = Participation.objects.get(
        account=reference.primary_account,
        edition=reference.current_edition,
    )

    participation_response = client.get(
        reverse("admin:participation_participation_add")
    )
    participation_form = participation_response.context["adminform"].form
    assert participation_form.initial["edition"] == str(reference.current_edition.id)
    assert participation_form.initial["organization"] == str(
        reference.primary_organization.id
    )
    assert set(participation_form.fields["edition"].queryset) == {
        reference.current_edition
    }
    assert set(participation_form.fields["organization"].queryset) == {
        reference.primary_organization
    }

    capacity_response = client.get(
        reverse("admin:participation_participationcapacity_add")
    )
    capacity_form = capacity_response.context["adminform"].form
    assert set(capacity_form.fields["participation"].queryset) == {
        primary_participation
    }

    edition_response = client.get(reverse("admin:events_eventedition_add"))
    edition_form = edition_response.context["adminform"].form
    assert set(edition_form.fields["organization"].queryset) == {
        reference.primary_organization
    }
    assert set(edition_form.fields["series"].queryset) == {
        reference.current_edition.series
    }


def test_selected_edition_keeps_applicable_authority_and_reuse_sources() -> None:
    client = _admin_client()
    reference = create_reference_convention()
    prior_edition = EventEditionFactory(
        organization=reference.primary_organization,
        series=reference.current_edition.series,
        slug="pawprint-2029",
        name="Pawprint Convention 2029",
    )
    unrelated_series = ConventionSeriesFactory(
        organization=reference.primary_organization,
        slug="side-event",
        name="Side Event",
    )
    _select_edition(client, reference.current_edition)

    organization_grant = CapabilityGrantFactory(
        organization=reference.primary_organization,
        edition=None,
        principal=reference.primary_account,
        granted_by=reference.primary_account,
    )
    edition_grant = CapabilityGrantFactory(
        organization=reference.primary_organization,
        edition=reference.current_edition,
        principal=reference.primary_account,
        granted_by=reference.primary_account,
    )
    prior_grant = CapabilityGrantFactory(
        organization=reference.primary_organization,
        edition=prior_edition,
        principal=reference.primary_account,
        granted_by=reference.primary_account,
    )

    role = RoleBundleFactory(organization=reference.primary_organization)
    other_role = RoleBundleFactory(organization=reference.other_organization)
    organization_assignment = RoleAssignmentFactory(
        organization=reference.primary_organization,
        edition=None,
        principal=reference.primary_account,
        role_bundle=role,
        granted_by=reference.primary_account,
    )
    edition_assignment = RoleAssignmentFactory(
        organization=reference.primary_organization,
        edition=reference.current_edition,
        principal=reference.primary_account,
        role_bundle=role,
        granted_by=reference.primary_account,
    )
    prior_assignment = RoleAssignmentFactory(
        organization=reference.primary_organization,
        edition=prior_edition,
        principal=reference.primary_account,
        role_bundle=role,
        granted_by=reference.primary_account,
    )

    grant_ids = _result_ids(
        client.get(reverse("admin:authorization_capabilitygrant_changelist"))
    )
    assert organization_grant.id in grant_ids
    assert edition_grant.id in grant_ids
    assert prior_grant.id not in grant_ids

    role_ids = _result_ids(
        client.get(reverse("admin:authorization_rolebundle_changelist"))
    )
    assert role.id in role_ids
    assert other_role.id not in role_ids

    assignment_ids = _result_ids(
        client.get(reverse("admin:authorization_roleassignment_changelist"))
    )
    assert organization_assignment.id in assignment_ids
    assert edition_assignment.id in assignment_ids
    assert prior_assignment.id not in assignment_ids

    selected_configuration = RegistrationConfigurationFactory(
        edition=reference.current_edition,
        name="Selected edition registration",
    )
    prior_configuration = RegistrationConfigurationFactory(
        edition=prior_edition,
        name="Prior edition registration",
    )
    other_configuration = RegistrationConfigurationFactory(
        edition=reference.other_edition,
        name="Other tenant registration",
    )
    configuration_response = client.get(
        reverse("admin:registration_registrationconfiguration_changelist")
    )
    configuration_ids = _result_ids(configuration_response)
    assert selected_configuration.id in configuration_ids
    assert prior_configuration.id not in configuration_ids
    assert other_configuration.id not in configuration_ids
    filter_titles = {
        specification.title
        for specification in configuration_response.context["cl"].filter_specs
    }
    assert "organization" not in filter_titles
    assert "edition" not in filter_titles
    assert "status" in filter_titles

    organization_template = RegistrationTemplateFactory(
        organization=reference.primary_organization,
        series=None,
        name="Organization registration template",
    )
    series_template = RegistrationTemplateFactory(
        organization=reference.primary_organization,
        series=reference.current_edition.series,
        name="Pawprint registration template",
    )
    unrelated_series_template = RegistrationTemplateFactory(
        organization=reference.primary_organization,
        series=unrelated_series,
        name="Side Event registration template",
    )
    other_tenant_template = RegistrationTemplateFactory(
        organization=reference.other_organization,
        series=None,
        name="Other tenant template",
    )
    template_ids = _result_ids(
        client.get(reverse("admin:registration_registrationtemplate_changelist"))
    )
    assert organization_template.id in template_ids
    assert series_template.id in template_ids
    assert unrelated_series_template.id not in template_ids
    assert other_tenant_template.id not in template_ids

    source_response = client.get(
        reverse("admin:autocomplete"),
        {
            "app_label": "registration",
            "model_name": "registrationconfiguration",
            "field_name": "source_edition",
            "term": "Convention",
        },
    )
    source_ids = {item["id"] for item in source_response.json()["results"]}
    assert str(prior_edition.id) in source_ids
    assert str(reference.current_edition.id) not in source_ids
    assert str(reference.other_edition.id) not in source_ids


def test_every_edition_related_admin_declares_context_scoping() -> None:
    scoped_models = (
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
        RegistrationTemplate,
        RegistrationConfiguration,
        Registration,
        RegistrationSubmission,
        AttendeeRegistrationProfile,
        PaymentAttempt,
        Entitlement,
        CheckInRecord,
        RegistrationTimelineEntry,
    )

    assert all(
        isinstance(admin.site._registry[model], EditionContextAdmin)
        for model in scoped_models
    )
    assert not isinstance(admin.site._registry[Account], EditionContextAdmin)


def test_inactive_authority_neither_discloses_nor_selects_editions() -> None:
    staff = AccountFactory(is_staff=True)
    client = Client()
    client.force_login(staff)
    now = timezone.now()

    future_grant = EventEditionFactory(name="Future Organization Grant")
    CapabilityGrantFactory(
        principal=staff,
        organization=future_grant.organization,
        edition=None,
        effective_from=now + timedelta(days=1),
    )

    expired_grant = EventEditionFactory(name="Expired Edition Grant")
    CapabilityGrantFactory(
        principal=staff,
        organization=expired_grant.organization,
        edition=expired_grant,
        effective_from=now - timedelta(days=2),
        expires_at=now - timedelta(days=1),
    )

    revoked_grant = EventEditionFactory(name="Revoked Organization Grant")
    CapabilityGrantFactory(
        principal=staff,
        organization=revoked_grant.organization,
        edition=None,
        effective_from=now - timedelta(days=2),
        revoked_at=now - timedelta(days=1),
        revoked_by=AccountFactory(),
        revocation_reason="Synthetic revocation.",
    )

    future_assignment = EventEditionFactory(name="Future Edition Assignment")
    future_role = RoleBundleFactory(organization=future_assignment.organization)
    RoleAssignmentFactory(
        principal=staff,
        organization=future_assignment.organization,
        edition=future_assignment,
        role_bundle=future_role,
        effective_from=now + timedelta(days=1),
    )

    expired_assignment = EventEditionFactory(name="Expired Organization Assignment")
    expired_role = RoleBundleFactory(organization=expired_assignment.organization)
    RoleAssignmentFactory(
        principal=staff,
        organization=expired_assignment.organization,
        edition=None,
        role_bundle=expired_role,
        effective_from=now - timedelta(days=2),
        expires_at=now - timedelta(days=1),
    )

    revoked_assignment = EventEditionFactory(name="Revoked Edition Assignment")
    revoked_role = RoleBundleFactory(organization=revoked_assignment.organization)
    RoleAssignmentFactory(
        principal=staff,
        organization=revoked_assignment.organization,
        edition=revoked_assignment,
        role_bundle=revoked_role,
        effective_from=now - timedelta(days=2),
        revoked_at=now - timedelta(days=1),
        revoked_by=AccountFactory(),
        revocation_reason="Synthetic revocation.",
    )

    active = EventEditionFactory(name="Active Authority Control")
    CapabilityGrantFactory(
        principal=staff,
        organization=active.organization,
        edition=active,
        effective_from=now - timedelta(minutes=5),
    )

    response = client.get(reverse("admin:index"))

    assert response.status_code == 200
    assert _selector_edition_ids(response) == {active.id}
    for unavailable in (
        future_grant,
        expired_grant,
        revoked_grant,
        future_assignment,
        expired_assignment,
        revoked_assignment,
    ):
        denied = client.post(
            reverse("admin-edition-context"),
            {
                "edition_id": str(unavailable.id),
                "next": reverse("admin:index"),
            },
        )
        assert denied.status_code == 404
        assert ADMIN_EDITION_SESSION_KEY not in client.session


def test_selected_context_clears_when_staff_authority_is_revoked() -> None:
    staff = AccountFactory(is_staff=True)
    client = Client()
    client.force_login(staff)
    edition = EventEditionFactory(name="Revoked Selected Context")
    grant = CapabilityGrantFactory(
        principal=staff,
        organization=edition.organization,
        edition=edition,
        effective_from=timezone.now() - timedelta(minutes=5),
    )
    _select_edition(client, edition)

    CapabilityGrant.objects.filter(id=grant.id).update(
        revoked_at=timezone.now(),
        revoked_by=AccountFactory(),
        revocation_reason="Synthetic selected-context revocation.",
    )
    response = client.get(reverse("admin:index"))

    assert response.status_code == 200
    assert ADMIN_EDITION_SESSION_KEY not in client.session
    assert _selector_edition_ids(response) == set()


def test_delegated_grant_requires_every_ancestor_to_remain_active() -> None:
    staff = AccountFactory(is_staff=True)
    client = Client()
    client.force_login(staff)
    now = timezone.now()

    revoked_ancestor_edition = EventEditionFactory(name="Revoked Delegation Ancestor")
    revoked_delegator = AccountFactory()
    revoked_ancestor = CapabilityGrantFactory(
        principal=revoked_delegator,
        organization=revoked_ancestor_edition.organization,
        edition=revoked_ancestor_edition,
        effective_from=now - timedelta(days=2),
    )
    CapabilityGrantFactory(
        principal=staff,
        organization=revoked_ancestor_edition.organization,
        edition=revoked_ancestor_edition,
        capability_code=revoked_ancestor.capability_code,
        effective_from=now - timedelta(days=1),
        granted_by=revoked_delegator,
        delegated_from=revoked_ancestor,
    )
    _select_edition(client, revoked_ancestor_edition)
    CapabilityGrant.objects.filter(id=revoked_ancestor.id).update(
        revoked_at=now,
        revoked_by=AccountFactory(),
        revocation_reason="Synthetic ancestor revocation.",
    )

    deep_ancestor_edition = EventEditionFactory(name="Deep Delegation Ancestor")
    root_delegator = AccountFactory()
    intermediate_delegator = AccountFactory()
    root_ancestor = CapabilityGrantFactory(
        principal=root_delegator,
        organization=deep_ancestor_edition.organization,
        edition=deep_ancestor_edition,
        effective_from=now - timedelta(days=2),
        expires_at=now + timedelta(days=3),
    )
    intermediate_ancestor = CapabilityGrantFactory(
        principal=intermediate_delegator,
        organization=deep_ancestor_edition.organization,
        edition=deep_ancestor_edition,
        capability_code=root_ancestor.capability_code,
        effective_from=now - timedelta(days=1),
        expires_at=now + timedelta(days=2),
        granted_by=root_delegator,
        delegated_from=root_ancestor,
    )
    CapabilityGrantFactory(
        principal=staff,
        organization=deep_ancestor_edition.organization,
        edition=deep_ancestor_edition,
        capability_code=root_ancestor.capability_code,
        effective_from=now - timedelta(hours=12),
        expires_at=now + timedelta(days=1),
        granted_by=intermediate_delegator,
        delegated_from=intermediate_ancestor,
    )
    CapabilityGrant.objects.filter(id=root_ancestor.id).update(
        revoked_at=now,
        revoked_by=AccountFactory(),
        revocation_reason="Synthetic root-ancestor revocation.",
    )

    response = client.get(reverse("admin:index"))

    assert response.status_code == 200
    assert ADMIN_EDITION_SESSION_KEY not in client.session
    assert _selector_edition_ids(response) == set()
    for unavailable in (revoked_ancestor_edition, deep_ancestor_edition):
        denied = client.post(
            reverse("admin-edition-context"),
            {
                "edition_id": str(unavailable.id),
                "next": reverse("admin:index"),
            },
        )
        assert denied.status_code == 403
        assert ADMIN_EDITION_SESSION_KEY not in client.session


def test_non_staff_active_scope_can_use_selector_without_staff_promotion() -> None:
    account = AccountFactory(is_staff=False)
    client = Client()
    client.force_login(account)
    edition = EventEditionFactory(name="Non-staff Authority")
    CapabilityGrantFactory(
        principal=account,
        organization=edition.organization,
        edition=edition,
        effective_from=timezone.now() - timedelta(minutes=5),
    )

    index_response = client.get(reverse("admin:index"))
    options = admin_edition_options(index_response.wsgi_request)
    selection_response = client.post(
        reverse("admin-edition-context"),
        {
            "edition_id": str(edition.id),
            "next": reverse("admin:index"),
        },
    )

    assert index_response.status_code == 200
    assert "Convention workspace" in index_response.content.decode()
    assert options["available"] is True
    assert {item.id for item in options["editions"]} == {edition.id}
    assert selection_response.status_code == 302
    assert client.session[ADMIN_EDITION_SESSION_KEY] == str(edition.id)
    assert not account.is_staff


@pytest.mark.parametrize("edition_id", ["not-a-uuid", pytest.param(str(uuid4()))])
def test_invalid_edition_selection_is_unavailable(edition_id: str) -> None:
    client = _admin_client()

    response = client.post(
        reverse("admin-edition-context"),
        {
            "edition_id": edition_id,
            "next": reverse("admin:index"),
        },
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "stored_value",
    ["not-a-uuid", pytest.param(str(uuid4())), 7],
)
def test_stale_session_context_is_cleared(stored_value: object) -> None:
    client = _admin_client()
    session = client.session
    session[ADMIN_EDITION_SESSION_KEY] = stored_value
    session.save()

    response = client.get(reverse("admin:index"))

    assert response.status_code == 200
    assert ADMIN_EDITION_SESSION_KEY not in client.session
