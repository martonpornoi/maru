from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from django.db import DatabaseError
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.authorization.models import RoleAssignment
from maru.events.models import EventEdition
from maru.organizations.models import (
    ConventionSeries,
    Organization,
    OrganizationRepresentation,
    RepresentationAppointment,
)
from maru.organizations.representation import (
    activate_executive_board,
    invite_representation_controller,
    provision_executive_board,
    respond_to_representation_invitation,
)
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    OrganizationFactory,
    RepresentationAppointmentFactory,
)

if TYPE_CHECKING:
    from maru.identity.models import Account

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _administrator() -> Account:
    return AccountFactory(
        display_name="Synthetic Platform Administrator",
        is_staff=True,
        is_superuser=True,
    )


def _client(account: Account) -> APIClient:
    client = APIClient()
    client.force_login(account)
    return client


def _provision(
    administrator: Account,
    organization: Organization,
) -> OrganizationRepresentation:
    return provision_executive_board(
        actor=administrator,
        organization_id=organization.id,
        reason="Establish synthetic accountable governance.",
        correlation_id=uuid4(),
        source_channel="test",
    )


def _invite(
    administrator: Account,
    representation: OrganizationRepresentation,
    account: Account,
) -> RepresentationAppointment:
    return invite_representation_controller(
        actor=administrator,
        representation_id=representation.id,
        account_id=account.id,
        reason="Invite a synthetic accountable controller.",
        correlation_id=uuid4(),
        source_channel="test",
    )


def _accept(appointment: RepresentationAppointment) -> RepresentationAppointment:
    return respond_to_representation_invitation(
        actor=appointment.account,
        appointment_id=appointment.id,
        expected_version=appointment.invitation_version,
        accept=True,
        correlation_id=uuid4(),
        source_channel="test",
    )


def _accepted_board() -> tuple[
    Account,
    Organization,
    OrganizationRepresentation,
    tuple[RepresentationAppointment, RepresentationAppointment],
]:
    administrator = _administrator()
    organization = OrganizationFactory(
        name="Synthetic Maru Organizers",
        slug="synthetic-maru",
        lifecycle=Organization.Lifecycle.DRAFT,
    )
    representation = _provision(administrator, organization)
    appointments = tuple(
        _accept(
            _invite(
                administrator,
                representation,
                AccountFactory(display_name=display_name),
            )
        )
        for display_name in (
            "Synthetic Board Controller One",
            "Synthetic Board Controller Two",
        )
    )
    representation.refresh_from_db()
    return administrator, organization, representation, appointments


def _activated_board() -> tuple[
    Account,
    Organization,
    OrganizationRepresentation,
    tuple[RepresentationAppointment, RepresentationAppointment],
]:
    administrator, organization, representation, appointments = _accepted_board()
    result = activate_executive_board(
        actor=administrator,
        representation_id=representation.id,
        expected_version=representation.aggregate_version,
        reason="Activate the synthetic Executive Board.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    return administrator, organization, result.representation, appointments


def _representation_url(organization: Organization) -> str:
    return reverse(
        "organization-representation",
        kwargs={"organization_slug": organization.slug},
    )


def _organization_payload(
    organization: Organization,
    **changes: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": organization.name,
        "description": organization.description,
        "legal_name": organization.legal_name,
        "legal_address": organization.legal_address,
        "legal_representative": organization.legal_representative,
        "registration_authority": organization.registration_authority,
        "registration_identifier": organization.registration_identifier,
        "tax_identifier": organization.tax_identifier,
        "imprint_text": organization.imprint_text,
        "website_url": organization.website_url,
        "contact_email": organization.contact_email,
        "contact_phone": organization.contact_phone,
        "country_code": organization.country_code,
        "default_language_codes": list(organization.default_language_codes),
        "default_time_zone": organization.default_time_zone,
    }
    payload.update(changes)
    return payload


def _series_payload(
    series: ConventionSeries,
    **changes: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": series.name,
        "description": series.description,
        "website_url": series.website_url,
        "contact_email": series.contact_email,
        "availability": "active" if series.is_active else "inactive",
        "expected_profile_version": series.profile_version,
    }
    payload.update(changes)
    return payload


def _edition_payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Synthetic MaruCon 2032",
        "starts_on": "2032-08-12",
        "ends_on": "2032-08-15",
        "time_zone": "Europe/Vienna",
        "language_codes": ["de", "en"],
        "currency_codes": "EUR",
        "idempotency_key": str(uuid4()),
    }
    payload.update(changes)
    return payload


def test_page_8_uses_the_shared_shell_and_strict_post_only_provisioning() -> None:
    organization = OrganizationFactory(
        name="Synthetic Maru Organizers",
        slug="synthetic-maru",
        lifecycle=Organization.Lifecycle.DRAFT,
    )
    url = _representation_url(organization)
    administrator = _administrator()
    client = _client(administrator)

    anonymous = APIClient().get(url)
    page = client.get(url)

    assert anonymous.status_code == 302
    assert anonymous["Location"] == f"/accounts/login/?next={url}"
    assert page.status_code == 200
    content = page.content.decode()
    assert 'data-page="organization-representation"' in content
    assert content.count('class="maru-admin-brand"') == 1
    assert 'id="nav-sidebar"' in content
    assert "Representation &amp; access" in content
    assert "Organization record" in content
    assert "Governance invitations" not in content
    assert "My Maru" in content
    assert 'data-navigation-group="personal"' not in content
    assert "Board setup" in content
    assert "Step 1 of 3" in content
    assert "1. Create the Executive Board" in content
    assert "2. Invite at least two controllers" in content
    assert "3. Activate governance" in content
    assert f'href="{reverse("platform-account-inventory")}"' in content
    assert f'href="{reverse("platform-account-invite")}"' in content
    assert "Quick Start" not in content
    assert 'name="reason"' in content
    assert 'name="organization"' not in content
    assert client.get(f"{url}provision/").status_code == 405

    rejected = client.post(
        f"{url}provision/",
        {
            "reason": "Create accountable governance.",
            "organization_id": str(organization.id),
        },
    )
    assert rejected.status_code == 400
    assert "Remove unsupported input fields: organization_id" in (
        rejected.content.decode()
    )
    assert not OrganizationRepresentation.objects.exists()

    created = client.post(
        f"{url}provision/",
        {"reason": "Create accountable governance."},
    )
    assert created.status_code == 302
    assert created["Location"] == url
    assert (
        OrganizationRepresentation.objects.filter(organization=organization).count()
        == 1
    )
    progressed = client.get(url).content.decode()
    assert "Step 2 of 3" in progressed
    assert "Invite a Board controller" in progressed


def test_invitation_lookup_is_exact_generic_and_strict() -> None:
    administrator = _administrator()
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    representation = _provision(administrator, organization)
    client = _client(administrator)
    invite_url = f"{_representation_url(organization)}invite/"
    inactive = AccountFactory(is_active=False)

    unknown = client.post(
        invite_url,
        {
            "account_email": "missing@example.invalid",
            "reason": "Invite a controller.",
        },
    )
    ineligible = client.post(
        invite_url,
        {
            "account_email": inactive.email.upper(),
            "reason": "Invite a controller.",
        },
    )

    for response in (unknown, ineligible):
        assert response.status_code == 400
        content = response.content.decode()
        assert "No eligible active account matches that exact email address." in content
        assert "inactive" not in content.lower()
        assert "unverified" not in content.lower()
    assert not RepresentationAppointment.objects.exists()

    invitee = AccountFactory(email="exact-controller@example.invalid")
    forged = client.post(
        invite_url,
        {
            "account_email": invitee.email,
            "reason": "Invite a controller.",
            "role": "owner",
        },
    )
    assert forged.status_code == 400
    assert "Remove unsupported input fields: role" in forged.content.decode()
    assert not RepresentationAppointment.objects.exists()

    created = client.post(
        invite_url,
        {
            "account_email": invitee.email.upper(),
            "reason": "Invite a controller.",
        },
    )
    assert created.status_code == 302
    assert (
        RepresentationAppointment.objects.filter(
            representation=representation,
            account=invitee,
        ).count()
        == 1
    )

    duplicate = client.post(
        invite_url,
        {
            "account_email": invitee.email,
            "reason": "Try the same relationship again.",
        },
    )
    assert duplicate.status_code == 409
    assert "No eligible active account matches that exact email address." in (
        duplicate.content.decode()
    )
    assert RepresentationAppointment.objects.count() == 1


def test_exact_invitees_see_only_their_term_and_can_accept_or_decline() -> None:
    administrator = _administrator()
    organization = OrganizationFactory(
        name="Visible Synthetic Organization",
        lifecycle=Organization.Lifecycle.DRAFT,
    )
    representation = _provision(administrator, organization)
    first = AccountFactory(
        display_name="Exact Visible Invitee",
        email="visible-invitee@example.invalid",
    )
    second = AccountFactory(
        display_name="Private Other Invitee",
        email="private-other@example.invalid",
    )
    first_appointment = _invite(administrator, representation, first)
    second_appointment = _invite(administrator, representation, second)
    page_url = _representation_url(organization)
    first_client = _client(first)

    inbox = first_client.get(reverse("my-representation-invitations"))
    page = first_client.get(page_url)

    assert inbox.status_code == 200
    assert organization.name in inbox.content.decode()
    assert page.status_code == 200
    content = page.content.decode()
    assert "Exact Visible Invitee" in content
    assert "Private Other Invitee" not in content
    assert second.email not in content
    assert "Organization record" not in content
    assert "Convention work" not in content
    assert "My Maru" in content
    assert '<table class="baseline-table">' in content
    assert 'data-label="Person"' in content
    assert content.count('class="maru-admin-brand"') == 1

    wrong_subject = _client(second).post(
        reverse(
            "respond-organization-controller-invitation",
            kwargs={
                "organization_slug": organization.slug,
                "appointment_id": first_appointment.id,
            },
        ),
        {"expected_version": 1, "decision": "accept"},
    )
    wrong_organization = OrganizationFactory(slug="wrong-synthetic-owner")
    wrong_scope = first_client.post(
        reverse(
            "respond-organization-controller-invitation",
            kwargs={
                "organization_slug": wrong_organization.slug,
                "appointment_id": first_appointment.id,
            },
        ),
        {"expected_version": 1, "decision": "accept"},
    )
    forged = first_client.post(
        reverse(
            "respond-organization-controller-invitation",
            kwargs={
                "organization_slug": organization.slug,
                "appointment_id": first_appointment.id,
            },
        ),
        {
            "expected_version": first_appointment.invitation_version,
            "decision": "accept",
            "account_id": str(first.id),
        },
    )
    assert wrong_subject.status_code == 404
    assert wrong_scope.status_code == 404
    assert forged.status_code == 400
    assert "Remove unsupported input fields: account_id" in forged.content.decode()

    accepted = first_client.post(
        reverse(
            "respond-organization-controller-invitation",
            kwargs={
                "organization_slug": organization.slug,
                "appointment_id": first_appointment.id,
            },
        ),
        {
            "expected_version": first_appointment.invitation_version,
            "decision": "accept",
        },
    )
    declined = _client(second).post(
        reverse(
            "respond-organization-controller-invitation",
            kwargs={
                "organization_slug": organization.slug,
                "appointment_id": second_appointment.id,
            },
        ),
        {
            "expected_version": second_appointment.invitation_version,
            "decision": "decline",
        },
    )
    assert accepted.status_code == 302
    assert accepted["Location"] == reverse("my-representation-invitations")
    assert declined.status_code == 302
    first_appointment.refresh_from_db()
    second_appointment.refresh_from_db()
    assert first_appointment.state == RepresentationAppointment.State.ACCEPTED
    assert second_appointment.state == RepresentationAppointment.State.DECLINED
    assert not RoleAssignment.objects.filter(principal=first).exists()


def test_activation_form_is_versioned_strict_and_reveals_active_authority() -> None:
    administrator, organization, representation, appointments = _accepted_board()
    client = _client(administrator)
    activate_url = f"{_representation_url(organization)}activate/"

    page = client.get(_representation_url(organization))
    content = page.content.decode()
    assert page.status_code == 200
    assert "Activate Executive Board" in content
    assert 'name="expected_version"' in content
    assert 'name="confirmation_name"' in content
    assert "Private Other Invitee" not in content

    forged = client.post(
        activate_url,
        {
            "expected_version": representation.aggregate_version,
            "confirmation_name": organization.name,
            "reason": "Activate accountable governance.",
            "lifecycle": "active",
        },
    )
    assert forged.status_code == 400
    assert "Remove unsupported input fields: lifecycle" in forged.content.decode()

    stale = client.post(
        activate_url,
        {
            "expected_version": representation.aggregate_version - 1,
            "confirmation_name": organization.name,
            "reason": "Activate accountable governance.",
        },
    )
    assert stale.status_code == 409
    organization.refresh_from_db()
    assert organization.lifecycle == Organization.Lifecycle.DRAFT

    activated = client.post(
        activate_url,
        {
            "expected_version": representation.aggregate_version,
            "confirmation_name": organization.name,
            "reason": "Activate accountable governance.",
        },
    )
    assert activated.status_code == 302
    organization.refresh_from_db()
    representation.refresh_from_db()
    assert organization.lifecycle == Organization.Lifecycle.ACTIVE
    assert representation.state == OrganizationRepresentation.State.ACTIVE

    controller = appointments[0].account
    controller_page = _client(controller).get(_representation_url(organization))
    controller_content = controller_page.content.decode()
    assert controller_page.status_code == 200
    assert "Active Executive Board controllers" in controller_content
    assert appointments[1].account.email in controller_content
    assert "Active role assignment" in controller_content
    assert "Board setup" in controller_content
    assert "Complete" in controller_content
    assert "Review user accounts" not in controller_content
    assert "Activate Executive Board" not in controller_content
    assert "Invite controller" not in controller_content


def test_page_8_sensitive_reads_and_privileged_denials_are_audited() -> None:
    _, organization, representation, appointments = _activated_board()
    controller = appointments[0].account
    basic_viewer = AccountFactory()
    CapabilityGrantFactory(
        organization=organization,
        principal=basic_viewer,
        capability_code="organizations.view_basic",
    )

    manager_page = _client(controller).get(_representation_url(organization))
    basic_page = _client(basic_viewer).get(_representation_url(organization))
    denied_provision = _client(basic_viewer).post(
        f"{_representation_url(organization)}provision/",
        {"reason": "Forbidden synthetic attempt."},
    )
    foreign = OrganizationFactory(slug="audit-private-foreign")
    denied_foreign = _client(controller).get(_representation_url(foreign))

    assert manager_page.status_code == 200
    assert basic_page.status_code == 200
    assert appointments[1].account.email in manager_page.content.decode()
    assert appointments[0].account.email not in basic_page.content.decode()
    assert denied_provision.status_code == 403
    assert denied_foreign.status_code == 403

    sensitive_read = AuditEvent.objects.get(
        principal_id=controller.id,
        organization_id=organization.id,
        operation="organizations.representation.appointment_directory.read",
    )
    assert sensitive_read.outcome == AuditEvent.Outcome.ALLOW
    assert sensitive_read.target_type == "organizations.organization_representation"
    assert sensitive_read.target_id == representation.id
    assert sensitive_read.obligations == ["audit_sensitive_read"]
    assert sensitive_read.safe_metadata["target_count"] == 2

    denials = AuditEvent.objects.filter(
        outcome=AuditEvent.Outcome.DENY,
        operation__in=(
            "organizations.representation.provision",
            "organizations.representation.route.authorize",
        ),
    )
    assert set(denials.values_list("organization_id", flat=True)) == {
        organization.id,
        foreign.id,
    }
    evidence = "|".join(
        str(
            (
                event.operation,
                event.reason_code,
                event.safe_metadata,
                event.changed_fields,
            )
        )
        for event in AuditEvent.objects.filter(
            operation__startswith="organizations.representation."
        )
    )
    for account in (appointments[0].account, appointments[1].account, basic_viewer):
        assert account.email not in evidence
        assert account.display_name not in evidence


def test_manager_appointment_history_is_tenant_scoped_bounded_and_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrator = _administrator()
    organization = OrganizationFactory(
        name="Bounded Synthetic Organization",
        slug="bounded-synthetic-organization",
        lifecycle=Organization.Lifecycle.DRAFT,
    )
    representation = _provision(administrator, organization)
    foreign = OrganizationFactory(
        name="Foreign Synthetic Organization",
        slug="foreign-synthetic-organization",
        lifecycle=Organization.Lifecycle.DRAFT,
    )
    foreign_representation = _provision(administrator, foreign)
    invited_at = timezone.now()
    first = RepresentationAppointmentFactory(
        id=UUID(int=101),
        representation=representation,
        invited_by=administrator,
        invited_at=invited_at,
        account=AccountFactory(
            display_name="Bounded Controller One",
            email="bounded-controller-one@example.invalid",
        ),
    )
    second = RepresentationAppointmentFactory(
        id=UUID(int=102),
        representation=representation,
        invited_by=administrator,
        invited_at=invited_at,
        account=AccountFactory(
            display_name="Bounded Controller Two",
            email="bounded-controller-two@example.invalid",
        ),
    )
    omitted = RepresentationAppointmentFactory(
        id=UUID(int=103),
        representation=representation,
        invited_by=administrator,
        invited_at=invited_at,
        account=AccountFactory(
            display_name="Bounded Controller Omitted",
            email="bounded-controller-omitted@example.invalid",
        ),
    )
    foreign_appointment = RepresentationAppointmentFactory(
        representation=foreign_representation,
        invited_by=administrator,
        invited_at=invited_at,
        account=AccountFactory(
            display_name="Foreign Controller Must Stay Hidden",
            email="foreign-controller-hidden@example.invalid",
        ),
    )
    monkeypatch.setattr(
        "maru.organizations.views._REPRESENTATION_APPOINTMENT_HISTORY_LIMIT",
        2,
    )

    response = _client(administrator).get(_representation_url(organization))

    assert response.status_code == 200
    assert tuple(item.id for item in response.context_data["appointments"]) == (
        first.id,
        second.id,
    )
    assert response.context_data["appointment_history_limit"] == 2
    assert response.context_data["appointment_history_truncated"] is True
    content = response.content.decode()
    assert content.index(first.account.display_name) < content.index(
        second.account.display_name
    )
    assert omitted.account.display_name not in content
    assert omitted.account.email not in content
    assert foreign_appointment.account.display_name not in content
    assert foreign_appointment.account.email not in content
    assert "Showing the 2 most recently invited appointments." in content
    sensitive_read = AuditEvent.objects.get(
        principal_id=administrator.id,
        organization_id=organization.id,
        operation="organizations.representation.appointment_directory.read",
    )
    assert sensitive_read.safe_metadata["target_count"] == 2


def test_sensitive_read_audit_append_failure_is_safe_and_discloses_no_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrator = _administrator()
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    representation = _provision(administrator, organization)
    appointment = RepresentationAppointmentFactory(
        representation=representation,
        invited_by=administrator,
        account=AccountFactory(
            display_name="Private Controller Hidden On Audit Failure",
            email="private-controller-hidden@example.invalid",
        ),
    )
    audit_count = AuditEvent.objects.count()

    def unavailable(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise DatabaseError("synthetic private audit append failure")

    monkeypatch.setattr("maru.organizations.views.append_audit", unavailable)
    response = _client(administrator).get(_representation_url(organization))

    assert response.status_code == 503
    content = response.content.decode()
    assert "Representation &amp; access is temporarily unavailable" in content
    assert "synthetic private audit append failure" not in content
    assert appointment.account.display_name not in content
    assert appointment.account.email not in content
    assert AuditEvent.objects.count() == audit_count


def test_representation_database_failures_are_generic_and_non_mutating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrator = _administrator()
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    representation = _provision(administrator, organization)
    invitee = AccountFactory()
    appointment = _invite(administrator, representation, invitee)

    def unavailable(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise DatabaseError("synthetic private database detail")

    monkeypatch.setattr("maru.organizations.views._own_open_appointment", unavailable)
    failed_page = _client(administrator).get(_representation_url(organization))
    assert failed_page.status_code == 503
    failed_content = failed_page.content.decode()
    assert "temporarily unavailable" in failed_content
    assert "synthetic private database detail" not in failed_content
    monkeypatch.undo()

    monkeypatch.setattr(
        "maru.organizations.views.respond_to_representation_invitation",
        unavailable,
    )
    response = _client(invitee).post(
        reverse(
            "respond-organization-controller-invitation",
            kwargs={
                "organization_slug": organization.slug,
                "appointment_id": appointment.id,
            },
        ),
        {
            "expected_version": appointment.invitation_version,
            "decision": "accept",
        },
    )
    assert response.status_code == 503
    assert "No partial change was kept" in response.content.decode()
    assert "synthetic private database detail" not in response.content.decode()
    appointment.refresh_from_db()
    assert appointment.state == RepresentationAppointment.State.INVITED


def test_activated_controller_can_complete_pages_3_through_7() -> None:
    _, organization, _, appointments = _activated_board()
    controller = appointments[0].account
    client = _client(controller)
    organization_url = reverse(
        "baseline-organization-record",
        kwargs={"organization_slug": organization.slug},
    )

    record = client.get(organization_url)
    assert record.status_code == 200
    record_content = record.content.decode()
    assert 'data-page="organization-record"' in record_content
    assert "Organization record" in record_content
    assert "Representation &amp; access" in record_content
    assert "Convention work" in record_content
    assert "Save changes" in record_content
    assert "Delete organization" not in record_content

    updated = client.post(
        organization_url,
        _organization_payload(
            organization,
            description="Maintained by the synthetic Executive Board.",
        ),
    )
    assert updated.status_code == 302
    organization.refresh_from_db()
    assert organization.description == "Maintained by the synthetic Executive Board."

    create_series_url = reverse(
        "baseline-create-convention-series",
        kwargs={"organization_slug": organization.slug},
    )
    assert client.get(create_series_url).status_code == 200
    created_series = client.post(
        create_series_url,
        {"name": "Synthetic MaruCon"},
    )
    assert created_series.status_code == 302
    series = ConventionSeries.objects.get(organization=organization)

    series_url = reverse(
        "baseline-convention-series-record",
        kwargs={
            "organization_slug": organization.slug,
            "series_slug": series.slug,
        },
    )
    assert client.get(series_url).status_code == 200
    changed_series = client.post(
        series_url,
        _series_payload(series, description="A Board-maintained recurring event."),
    )
    assert changed_series.status_code == 302
    series.refresh_from_db()
    assert series.description == "A Board-maintained recurring event."

    create_edition_url = reverse(
        "baseline-create-event-edition",
        kwargs={
            "organization_slug": organization.slug,
            "series_slug": series.slug,
        },
    )
    assert client.get(create_edition_url).status_code == 200
    created_edition = client.post(create_edition_url, _edition_payload())
    assert created_edition.status_code == 302
    edition = EventEdition.objects.get(series=series)
    edition_url = reverse(
        "baseline-event-edition-record",
        kwargs={
            "organization_slug": organization.slug,
            "series_slug": series.slug,
            "edition_slug": edition.slug,
        },
    )
    edition_page = client.get(edition_url)
    assert edition_page.status_code == 200
    edition_content = edition_page.content.decode()
    assert 'data-page="event-edition-record"' in edition_content
    assert edition.name in edition_content
    assert "Save changes" not in edition_content

    denied_update = client.post(
        edition_url,
        {
            "name": "Forged title",
            "starts_on": edition.starts_on.isoformat(),
            "ends_on": edition.ends_on.isoformat(),
            "time_zone": edition.time_zone,
            "language_codes": list(edition.language_codes),
            "currency_codes": "EUR",
            "expected_aggregate_version": edition.aggregate_version,
        },
    )
    assert denied_update.status_code == 403
    edition.refresh_from_db()
    assert edition.name != "Forged title"


def test_unrelated_controller_is_denied_before_unscoped_lookup_and_conflicts_stay_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, _, appointments = _activated_board()
    controller = appointments[0].account
    unrelated = OrganizationFactory(
        slug="private-other-tenant",
        lifecycle=Organization.Lifecycle.ACTIVE,
    )
    unrelated_series = ConventionSeries.objects.create(
        organization=unrelated,
        slug="private-other-series",
        name="Private Other Series",
    )
    unrelated_edition = EventEdition.objects.create(
        organization=unrelated,
        series=unrelated_series,
        slug="private-other-edition",
        name="Private Other Edition",
        starts_on="2033-08-01",
        ends_on="2033-08-04",
        time_zone="Europe/Vienna",
        language_codes=["en"],
        currency_codes=["EUR"],
    )

    def unexpected_unscoped_lookup(slug: str) -> Organization:
        del slug
        raise AssertionError("unrelated controllers must not use unscoped lookup")

    monkeypatch.setattr(
        "maru.core.views._organization_for_record",
        unexpected_unscoped_lookup,
    )
    client = _client(controller)
    denied_urls = (
        reverse(
            "baseline-organization-record",
            kwargs={"organization_slug": unrelated.slug},
        ),
        reverse(
            "baseline-create-convention-series",
            kwargs={"organization_slug": unrelated.slug},
        ),
        reverse(
            "baseline-convention-series-record",
            kwargs={
                "organization_slug": unrelated.slug,
                "series_slug": unrelated_series.slug,
            },
        ),
        reverse(
            "baseline-create-event-edition",
            kwargs={
                "organization_slug": unrelated.slug,
                "series_slug": unrelated_series.slug,
            },
        ),
        reverse(
            "baseline-event-edition-record",
            kwargs={
                "organization_slug": unrelated.slug,
                "series_slug": unrelated_series.slug,
                "edition_slug": unrelated_edition.slug,
            },
        ),
    )
    assert {client.get(url).status_code for url in denied_urls} == {403}
    assert client.get(_representation_url(unrelated)).status_code == 403
    monkeypatch.undo()

    closed = OrganizationFactory(
        slug="closed-governed-organization",
        lifecycle=Organization.Lifecycle.CLOSED,
    )
    CapabilityGrantFactory(
        organization=closed,
        principal=controller,
        capability_code="organizations.create_series",
    )
    closed_series_url = reverse(
        "baseline-create-convention-series",
        kwargs={"organization_slug": closed.slug},
    )
    assert client.get(closed_series_url).status_code == 409
    assert client.post(closed_series_url, {"name": "Too Late"}).status_code == 409
