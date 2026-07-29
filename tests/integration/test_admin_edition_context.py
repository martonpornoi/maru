import re
from collections.abc import Iterable
from uuid import uuid4

import pytest
from django.contrib import admin
from django.http import HttpResponse
from django.test import Client
from django.urls import reverse

from maru.authorization.models import CapabilityGrant, RoleAssignment, RoleBundle
from maru.events.admin_context import (
    ADMIN_EDITION_SESSION_KEY,
    EditionContextAdmin,
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


def _select_edition(client: Client, edition: EventEdition) -> None:
    response = client.post(
        reverse("admin-edition-context"),
        {
            "edition_id": str(edition.id),
            "next": reverse("admin:index"),
        },
    )
    assert response.status_code == 302


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


@pytest.mark.parametrize("stored_value", ["not-a-uuid", pytest.param(str(uuid4()))])
def test_stale_session_context_is_cleared(stored_value: str) -> None:
    client = _admin_client()
    session = client.session
    session[ADMIN_EDITION_SESSION_KEY] = stored_value
    session.save()

    response = client.get(reverse("admin:index"))

    assert response.status_code == 200
    assert ADMIN_EDITION_SESSION_KEY not in client.session
