from dataclasses import replace
from datetime import date
from uuid import uuid4

import pytest
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from maru.authorization.commands import create_role_bundle_version
from maru.authorization.models import CapabilityGrant, RoleAssignment, RoleBundle
from maru.authorization.policy import (
    decide,
    resolve_edition_target,
    resolve_organization_target,
)
from maru.events.admin_context import ADMIN_EDITION_SESSION_KEY
from maru.events.adoption import AdoptionProfileCode
from maru.events.models import EventEdition, WorkforceAdoptionSetupReceipt
from maru.events.services import (
    EventEditionDetails,
    create_event_edition,
    update_event_edition,
)
from maru.events.workforce_adoption import (
    WorkforceAdoptionSetupInput,
    set_up_workforce_adoption,
)
from maru.organizations.models import (
    ConventionSeries,
    Organization,
    OrganizationMembership,
    OrganizationRepresentation,
    RepresentationAppointment,
)
from maru.organizations.representation import (
    MARU_OPERATOR_CAPABILITIES,
    activate_representation,
    invite_representation_controller,
    respond_to_representation_invitation,
)
from maru.participation.models import Participation
from maru.workforce.models import PositionTemplate
from maru.workforce.starter_templates import (
    WORKFORCE_VOLUNTEER_ROLE_CAPABILITIES,
    WORKFORCE_VOLUNTEER_TEMPLATE_CODE,
)
from tests.factories import (
    AccountFactory,
    ConventionSeriesFactory,
    OrganizationFactory,
)
from tests.support.authority import activate_synthetic_board
from tests.workforce_helpers import create_department_for_test

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

_UNADOPTED_APP_LABELS = (
    "accreditation",
    "applications",
    "catalog",
    "charities",
    "communications",
    "logistics",
    "registration",
    "venues",
)


def _administrator():
    return AccountFactory(is_staff=True, is_superuser=True)


def _setup_details(
    *,
    mode: str = WorkforceAdoptionSetupReceipt.Mode.NEW_FOUNDATION,
    organization_id=None,
    series_id=None,
) -> WorkforceAdoptionSetupInput:
    return WorkforceAdoptionSetupInput(
        mode=mode,
        organization_id=organization_id,
        series_id=series_id,
        organization_name="Synthetic Volunteer Association",
        series_name="HelperCon",
        edition_name="HelperCon 2032",
        starts_on=date(2032, 8, 12),
        ends_on=date(2032, 8, 15),
        time_zone="Europe/Budapest",
    )


def _set_up_new_foundation():
    administrator = _administrator()
    key = uuid4()
    result = set_up_workforce_adoption(
        actor=administrator,
        details=_setup_details(),
        idempotency_key=key,
        correlation_id=uuid4(),
        source_channel="test",
    )
    return administrator, key, result


def _activate_maru_operators(administrator, representation):
    appointments = []
    for _index in range(2):
        operator = AccountFactory()
        invitation = invite_representation_controller(
            actor=administrator,
            representation_id=representation.id,
            account_id=operator.id,
            reason="Invite an accountable Workforce operator.",
            correlation_id=uuid4(),
            source_channel="test",
        )
        appointments.append(
            respond_to_representation_invitation(
                actor=operator,
                appointment_id=invitation.id,
                expected_version=invitation.invitation_version,
                accept=True,
                correlation_id=uuid4(),
                source_channel="test",
            )
        )
    representation.refresh_from_db()
    activation = activate_representation(
        actor=administrator,
        representation_id=representation.id,
        expected_version=representation.aggregate_version,
        reason="Activate accountable Workforce operation.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    return activation.appointments


def _validation_codes(error: ValidationError) -> set[str | None]:
    if hasattr(error, "error_dict"):
        return {
            item.code
            for field_errors in error.error_dict.values()
            for item in field_errors
        }
    return {item.code for item in error.error_list}


def test_guided_setup_creates_only_the_minimum_workforce_foundation() -> None:
    administrator, key, result = _set_up_new_foundation()

    edition = result.edition
    organization = edition.organization
    representation = result.representation
    assert result.created_organization
    assert result.created_series
    assert result.created_edition
    assert not result.replayed
    assert organization.lifecycle == Organization.Lifecycle.DRAFT
    assert edition.lifecycle == EventEdition.Lifecycle.DRAFT
    assert edition.adoption_profile_code == AdoptionProfileCode.WORKFORCE_ONLY
    assert edition.adoption_profile_version == 1
    assert edition.language_codes == ["en"]
    assert edition.currency_codes == ["XXX"]
    assert representation.code == OrganizationRepresentation.MARU_OPERATORS_CODE
    assert representation.name == OrganizationRepresentation.MARU_OPERATORS_NAME
    assert representation.state == OrganizationRepresentation.State.PROVISIONING
    assert not OrganizationMembership.objects.filter(account=administrator).exists()
    assert not Participation.objects.exists()

    for app_label in _UNADOPTED_APP_LABELS:
        for model in apps.get_app_config(app_label).get_models():
            assert not model.objects.exists(), model._meta.label

    replay = set_up_workforce_adoption(
        actor=administrator,
        details=replace(
            _setup_details(),
            organization_id=uuid4(),
            series_id=uuid4(),
        ),
        idempotency_key=key,
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert replay.replayed
    assert replay.edition.id == edition.id
    assert Organization.objects.count() == 1
    assert ConventionSeries.objects.count() == 1
    assert EventEdition.objects.count() == 1
    assert WorkforceAdoptionSetupReceipt.objects.count() == 1


def test_guided_setup_rejects_a_changed_idempotent_retry() -> None:
    administrator, key, _result = _set_up_new_foundation()
    changed = replace(
        _setup_details(),
        edition_name="Different HelperCon 2032",
    )

    with pytest.raises(ValidationError) as captured:
        set_up_workforce_adoption(
            actor=administrator,
            details=changed,
            idempotency_key=key,
            correlation_id=uuid4(),
            source_channel="test",
        )

    assert "workforce_setup_idempotency_conflict" in _validation_codes(captured.value)
    assert EventEdition.objects.count() == 1


def test_existing_governed_series_is_reused_without_replacing_its_board() -> None:
    organization = OrganizationFactory()
    activate_synthetic_board(organization)
    series = ConventionSeriesFactory(organization=organization)
    administrator = _administrator()

    result = set_up_workforce_adoption(
        actor=administrator,
        details=_setup_details(
            mode=WorkforceAdoptionSetupReceipt.Mode.EXISTING_SERIES,
            series_id=series.id,
        ),
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )

    assert not result.created_organization
    assert not result.created_series
    assert result.created_edition
    assert result.edition.series_id == series.id
    assert result.representation.code == "executive_board"
    assert (
        OrganizationRepresentation.objects.filter(
            organization=organization,
            code="executive_board",
        ).count()
        == 1
    )
    assert not OrganizationRepresentation.objects.filter(
        organization=organization,
        code="maru_operators",
    ).exists()


def test_active_ungoverned_foundation_is_rejected_without_partial_series() -> None:
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.ACTIVE)

    with pytest.raises(ValidationError) as captured:
        set_up_workforce_adoption(
            actor=_administrator(),
            details=_setup_details(
                mode=WorkforceAdoptionSetupReceipt.Mode.EXISTING_ORGANIZATION,
                organization_id=organization.id,
            ),
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )

    assert "workforce_setup_representation_required" in _validation_codes(
        captured.value
    )
    assert not ConventionSeries.objects.exists()
    assert not EventEdition.objects.exists()


def test_workforce_profile_and_setup_receipt_are_database_immutable() -> None:
    _administrator_account, _key, result = _set_up_new_foundation()
    receipt = WorkforceAdoptionSetupReceipt.objects.get(edition=result.edition)

    with pytest.raises(DatabaseError), transaction.atomic():
        EventEdition.objects.filter(pk=result.edition.id).update(
            adoption_profile_code=AdoptionProfileCode.FULL_CONVENTION
        )
    with pytest.raises(DatabaseError), transaction.atomic():
        WorkforceAdoptionSetupReceipt.objects.filter(pk=receipt.id).update(
            mode=WorkforceAdoptionSetupReceipt.Mode.EXISTING_SERIES
        )
    with pytest.raises(DatabaseError), transaction.atomic():
        WorkforceAdoptionSetupReceipt.objects.filter(pk=receipt.id).delete()

    result.edition.refresh_from_db()
    receipt.refresh_from_db()
    assert result.edition.adoption_profile_code == AdoptionProfileCode.WORKFORCE_ONLY
    assert receipt.mode == WorkforceAdoptionSetupReceipt.Mode.NEW_FOUNDATION


def test_workforce_profile_rejects_payment_currency_configuration() -> None:
    administrator, _key, result = _set_up_new_foundation()
    edition = result.edition

    with pytest.raises(ValidationError) as captured:
        update_event_edition(
            actor=administrator,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            expected_aggregate_version=edition.aggregate_version,
            details=EventEditionDetails(
                name=edition.name,
                starts_on=edition.starts_on,
                ends_on=edition.ends_on,
                time_zone=edition.time_zone,
                language_codes=tuple(edition.language_codes),
                currency_codes=("EUR",),
            ),
            correlation_id=uuid4(),
            request_id=uuid4(),
            source_channel="test",
        )

    assert "edition_module_not_adopted" in _validation_codes(captured.value)
    edition.refresh_from_db()
    assert edition.currency_codes == ["XXX"]


def test_two_accepted_maru_operators_receive_workforce_not_registration() -> None:
    administrator, _key, result = _set_up_new_foundation()
    appointments = _activate_maru_operators(administrator, result.representation)
    result.edition.organization.refresh_from_db()
    result.representation.refresh_from_db()

    assert result.edition.organization.lifecycle == Organization.Lifecycle.ACTIVE
    assert result.representation.state == OrganizationRepresentation.State.ACTIVE
    assert {appointment.account_id for appointment in appointments} == {
        appointment.account_id
        for appointment in RepresentationAppointment.objects.filter(
            representation=result.representation,
            state=RepresentationAppointment.State.ACTIVE,
        )
    }
    bundle = RoleBundle.objects.get(
        organization=result.edition.organization,
        code="maru-operators",
    )
    assert tuple(bundle.capability_codes) == MARU_OPERATOR_CAPABILITIES
    assert RoleAssignment.objects.filter(role_bundle=bundle).count() == 2
    assert set(
        OrganizationMembership.objects.filter(
            organization=result.edition.organization,
            state=OrganizationMembership.State.ACTIVE,
        ).values_list("relationship_label", flat=True)
    ) == {"Maru operator"}

    target = resolve_edition_target(
        organization_id=result.edition.organization_id,
        edition_id=result.edition.id,
    )
    operator = appointments[0].account
    workforce = decide(
        principal=operator,
        capability_code="workforce.view_structure",
        resource=target,
    )
    registration = decide(
        principal=operator,
        capability_code="registration.view_service_summary",
        resource=target,
    )
    attendance = decide(
        principal=operator,
        capability_code="participation.view_staff_summary",
        resource=target,
    )
    platform_registration = decide(
        principal=administrator,
        capability_code="registration.view_service_summary",
        resource=target,
    )
    platform_attendance = decide(
        principal=administrator,
        capability_code="participation.view_staff_summary",
        resource=target,
    )
    assert workforce.allowed
    assert workforce.reason_code == "role_assignment"
    assert not registration.allowed
    assert registration.reason_code == "module_not_adopted"
    assert not attendance.allowed
    assert attendance.reason_code == "module_not_adopted"
    assert not platform_registration.allowed
    assert platform_registration.reason_code == "module_not_adopted"
    assert not platform_attendance.allowed
    assert platform_attendance.reason_code == "module_not_adopted"


def test_accountable_operator_can_create_the_safe_volunteer_starter() -> None:
    administrator, _key, result = _set_up_new_foundation()
    appointments = _activate_maru_operators(administrator, result.representation)
    actor, approver = (appointment.account for appointment in appointments[:2])
    create_department_for_test(
        edition=result.edition,
        actor=actor,
        name="Volunteer Operations",
        expected_code="volunteer-operations",
    )
    client = Client()
    client.force_login(actor)
    route_args = (
        result.edition.organization.slug,
        result.edition.series.slug,
        result.edition.slug,
    )
    overview_url = reverse("organization-structure-positions", args=route_args)
    starter_url = reverse(
        "create-workforce-starter-position-template",
        args=route_args,
    )

    page = client.get(overview_url)

    assert page.status_code == 200
    content = page.content.decode()
    assert "Create the safe Volunteer starter" in content
    assert "creates no Position, assignment, Registration" in content
    assert starter_url.endswith("/structure/positions/volunteer-starter/")
    assert client.get(starter_url).status_code == 405

    response = client.post(
        starter_url,
        {
            "approver_email": approver.email,
            "reason": "Create the minimum reusable Volunteer meaning.",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"] == reverse(
        "organization-structure-position-create",
        args=route_args,
    )
    role = RoleBundle.objects.get(
        organization=result.edition.organization,
        code=WORKFORCE_VOLUNTEER_TEMPLATE_CODE,
    )
    template = PositionTemplate.objects.get(
        organization=result.edition.organization,
        code=WORKFORCE_VOLUNTEER_TEMPLATE_CODE,
    )
    assert tuple(role.capability_codes) == WORKFORCE_VOLUNTEER_ROLE_CAPABILITIES
    assert hasattr(role, "authority_issuance")
    assert template.role_bundle_id == role.id
    assert template.status == PositionTemplate.Status.PUBLISHED
    assert template.default_capacity_codes == ["volunteer"]
    assert not RoleAssignment.objects.filter(role_bundle=role).exists()
    assert not Participation.objects.exists()

    replay = client.post(
        starter_url,
        {
            "approver_email": approver.email,
            "reason": "Create the minimum reusable Volunteer meaning.",
        },
    )
    assert replay.status_code == 302
    assert (
        RoleBundle.objects.filter(
            organization=result.edition.organization,
            code=WORKFORCE_VOLUNTEER_TEMPLATE_CODE,
        ).count()
        == 1
    )
    assert (
        PositionTemplate.objects.filter(
            organization=result.edition.organization,
            code=WORKFORCE_VOLUNTEER_TEMPLATE_CODE,
        ).count()
        == 1
    )


def test_workforce_position_choices_exclude_unadopted_role_meaning() -> None:
    administrator, _key, result = _set_up_new_foundation()
    appointments = _activate_maru_operators(administrator, result.representation)
    actor, approver = (appointment.account for appointment in appointments[:2])
    create_department_for_test(
        edition=result.edition,
        actor=actor,
        name="Volunteer Operations",
        expected_code="volunteer-operations",
    )
    target = resolve_organization_target(
        organization_id=result.edition.organization_id,
    )
    assert target is not None
    incompatible_role = create_role_bundle_version(
        actor=actor,
        approver=approver,
        target=target,
        code="registration-shaped-position",
        name="Registration-shaped position",
        capability_codes=("registration.view_service_summary",),
        reason="Create an incompatible template for the boundary test.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    PositionTemplate.objects.create(
        organization=result.edition.organization,
        code="registration-shaped-position",
        name="Registration-shaped position",
        description="Must not cross into a Workforce-only edition.",
        default_headcount=1,
        default_capacity_codes=["volunteer"],
        role_bundle=incompatible_role,
        status=PositionTemplate.Status.PUBLISHED,
        created_by=actor,
    )
    client = Client()
    client.force_login(actor)

    response = client.get(
        reverse(
            "organization-structure-positions",
            args=(
                result.edition.organization.slug,
                result.edition.series.slug,
                result.edition.slug,
            ),
        )
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert "Create the safe Volunteer starter" in content
    assert "Registration-shaped position" not in content


def test_volunteer_starter_rejects_self_approval_without_partial_role() -> None:
    administrator, _key, result = _set_up_new_foundation()
    appointments = _activate_maru_operators(administrator, result.representation)
    actor = appointments[0].account
    create_department_for_test(
        edition=result.edition,
        actor=actor,
        name="Volunteer Operations",
        expected_code="volunteer-operations",
    )
    client = Client()
    client.force_login(actor)

    response = client.post(
        reverse(
            "create-workforce-starter-position-template",
            args=(
                result.edition.organization.slug,
                result.edition.series.slug,
                result.edition.slug,
            ),
        ),
        {
            "approver_email": actor.email,
            "reason": "Attempt to approve the starter alone.",
        },
    )

    assert response.status_code == 400
    assert "Choose a different active accountable controller" in (
        response.content.decode()
    )
    assert not RoleBundle.objects.filter(
        organization=result.edition.organization,
        code=WORKFORCE_VOLUNTEER_TEMPLATE_CODE,
    ).exists()
    assert not PositionTemplate.objects.filter(
        organization=result.edition.organization,
        code=WORKFORCE_VOLUNTEER_TEMPLATE_CODE,
    ).exists()


def test_maru_operator_cannot_expand_the_organization_to_full_convention() -> None:
    administrator, _key, result = _set_up_new_foundation()
    operator = _activate_maru_operators(
        administrator,
        result.representation,
    )[0].account
    edition_count = EventEdition.objects.count()

    with pytest.raises(ValidationError) as captured:
        create_event_edition(
            actor=operator,
            organization_id=result.edition.organization_id,
            series_id=result.edition.series_id,
            details=EventEditionDetails(
                name="HelperCon 2033",
                starts_on=date(2033, 8, 11),
                ends_on=date(2033, 8, 14),
                time_zone="Europe/Budapest",
                language_codes=("en",),
                currency_codes=("EUR",),
            ),
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            adoption_profile_code=AdoptionProfileCode.FULL_CONVENTION,
        )

    assert "edition_adoption_expansion_requires_platform_oversight" in (
        _validation_codes(captured.value)
    )
    assert EventEdition.objects.count() == edition_count

    broader_result = create_event_edition(
        actor=administrator,
        organization_id=result.edition.organization_id,
        series_id=result.edition.series_id,
        details=EventEditionDetails(
            name="HelperCon full 2033",
            starts_on=date(2033, 8, 11),
            ends_on=date(2033, 8, 14),
            time_zone="Europe/Budapest",
            language_codes=("en",),
            currency_codes=("EUR",),
        ),
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        adoption_profile_code=AdoptionProfileCode.FULL_CONVENTION,
    )
    broader_edition = broader_result.edition
    broader_target = resolve_edition_target(
        organization_id=broader_edition.organization_id,
        edition_id=broader_edition.id,
    )

    operator_decision = decide(
        principal=operator,
        capability_code="events.view_basic",
        resource=broader_target,
    )
    platform_decision = decide(
        principal=administrator,
        capability_code="events.view_basic",
        resource=broader_target,
    )

    assert not operator_decision.allowed
    assert operator_decision.reason_code == "permission_absent"
    assert platform_decision.allowed
    assert platform_decision.reason_code == "platform_administration"


def test_database_rejects_generic_organization_wide_workforce_authority() -> None:
    administrator, _key, result = _set_up_new_foundation()
    principal = AccountFactory()
    now = timezone.now()
    direct_grant = CapabilityGrant(
        organization=result.edition.organization,
        edition=None,
        principal=principal,
        capability_code="workforce.view_structure",
        effective_from=now,
        granted_by=administrator,
        reason="Attempt an over-broad Workforce grant.",
    )

    with (
        transaction.atomic(),
        pytest.raises(
            DatabaseError,
            match="requires exact edition scope",
        ),
    ):
        CapabilityGrant.objects.bulk_create([direct_grant])

    generic_bundle = RoleBundle.objects.create(
        organization=result.edition.organization,
        code="over-broad-workforce",
        name="Over-broad Workforce",
        version=1,
        capability_codes=["workforce.view_structure"],
        created_by=administrator,
        approved_by=administrator,
        reason="Exercise the database scope boundary.",
    )
    generic_assignment = RoleAssignment(
        organization=result.edition.organization,
        edition=None,
        principal=principal,
        role_bundle=generic_bundle,
        effective_from=now,
        granted_by=administrator,
        reason="Attempt an over-broad Workforce role.",
    )

    with (
        transaction.atomic(),
        pytest.raises(
            DatabaseError,
            match="requires exact edition scope",
        ),
    ):
        RoleAssignment.objects.bulk_create([generic_assignment])


def test_operator_context_and_menu_are_focused_without_participation_side_effects() -> (
    None
):
    administrator, _key, result = _set_up_new_foundation()
    appointments = _activate_maru_operators(administrator, result.representation)
    operator = appointments[0].account
    api_client = APIClient()
    api_client.force_authenticate(operator)

    response = api_client.get(reverse("api-my-context"))

    assert response.status_code == 200
    payload = response.json()
    edition = next(
        item
        for item in payload["editions"]
        if item["edition_id"] == str(result.edition.id)
    )
    assert edition["adoption_profile_code"] == "workforce_only"
    assert edition["adoption_profile_label"] == "Workforce only"
    assert edition["participation_status"] == "not_participating"
    assert edition["available_destinations"] == [
        "today",
        "workforce",
        "setup",
        "security",
    ]
    assert "workforce" in edition["adopted_modules"]
    assert "registration" not in edition["adopted_modules"]
    assert "participation" not in edition["adopted_modules"]
    assert not Participation.objects.filter(account=operator).exists()

    web_client = Client()
    web_client.force_login(operator)
    deep_link = web_client.get(
        reverse(
            "organization-structure",
            args=(
                result.edition.organization.slug,
                result.edition.series.slug,
                result.edition.slug,
            ),
        )
    )
    deep_link_content = deep_link.content.decode()
    assert deep_link.status_code == 200
    assert "Workforce" in deep_link_content
    assert "Registration desk" not in deep_link_content
    assert "Reports &amp; badges" not in deep_link_content

    session = web_client.session
    session[ADMIN_EDITION_SESSION_KEY] = str(result.edition.id)
    session.save()
    menu = web_client.get(reverse("admin:index"))
    content = menu.content.decode()
    assert menu.status_code == 200
    assert "Workforce" in content
    assert "Setup guide" in content
    assert "Registration desk" not in content
    assert "Reports &amp; badges" not in content
    assert f'data-navigation-code="edition.{result.edition.id}.registration"' not in (
        content
    )

    volunteer_page = web_client.get(
        reverse("workforce-opportunities", args=(result.edition.id,))
    )
    volunteer_content = volunteer_page.content.decode()
    assert volunteer_page.status_code == 200
    assert 'aria-label="Volunteer navigation"' in volunteer_content
    assert "Volunteer opportunities" in volunteer_content
    assert "My Workforce" in volunteer_content
    assert "Registration navigation" not in volunteer_content
    assert "Registration data belongs" not in volunteer_content
    assert "does not create attendee registration" in volunteer_content


def test_workforce_access_workspace_excludes_unadopted_groups() -> None:
    administrator, _key, result = _set_up_new_foundation()
    appointments = _activate_maru_operators(administrator, result.representation)
    actor, approver = (appointment.account for appointment in appointments[:2])
    target = resolve_organization_target(
        organization_id=result.edition.organization_id,
    )
    assert target is not None
    workforce_role = create_role_bundle_version(
        actor=actor,
        approver=approver,
        target=target,
        code="workforce-coordinator",
        name="Workforce coordinator",
        capability_codes=("workforce.view_structure",),
        reason="Create a focused Workforce access group.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    registration_role = create_role_bundle_version(
        actor=actor,
        approver=approver,
        target=target,
        code="registration-service",
        name="Registration service",
        capability_codes=("registration.view_service_summary",),
        reason="Create an unadopted comparison group.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    client = APIClient()
    client.force_authenticate(actor)
    url = reverse(
        "api-edition-access-workspace",
        kwargs={
            "organization_id": result.edition.organization_id,
            "edition_id": result.edition.id,
        },
    )

    workspace = client.get(url)

    assert workspace.status_code == 200
    assert {group["code"] for group in workspace.data["groups"]} == {
        workforce_role.code
    }
    recipient = AccountFactory(email="focused-volunteer@example.invalid")
    rejected = client.post(
        url,
        {
            "person_email": recipient.email,
            "group_code": registration_role.code,
            "approver_email": approver.email,
            "reason": "Attempt to assign an unadopted module.",
        },
        format="json",
    )
    assert rejected.status_code == 400
    assert not RoleAssignment.objects.filter(
        principal=recipient,
        role_bundle=registration_role,
    ).exists()


def test_guided_setup_page_explains_the_boundary_and_redirects_to_accountability() -> (
    None
):
    administrator = _administrator()
    client = Client()
    client.force_login(administrator)
    url = reverse("workforce-adoption-setup")

    page = client.get(url)

    assert page.status_code == 200
    content = page.content.decode()
    assert "Set up Workforce" in content
    assert "Only Workforce is adopted" in content
    assert "Maru operators" in content
    assert "Executive Board" in content
    assert "does not claim" in content
    assert 'name="currency_codes"' not in content
    assert 'name="language_codes"' not in content
    assert 'name="mode"' in content
    assert 'aria-live="polite"' in content

    key = uuid4()
    malformed = client.post(
        url,
        {
            "mode": WorkforceAdoptionSetupReceipt.Mode.NEW_FOUNDATION,
            "organization_name": "Synthetic Volunteer Association",
            "series_name": "HelperCon",
            "edition_name": "HelperCon 2032",
            "starts_on": "2032-08-12",
            "ends_on": "2032-08-15",
            "time_zone": "Europe/Budapest",
            "idempotency_key": str(key),
            "currency_codes": "EUR",
        },
    )
    assert malformed.status_code == 400
    assert "Remove unsupported input fields: currency_codes" in (
        malformed.content.decode()
    )
    assert not EventEdition.objects.exists()

    created = client.post(
        url,
        {
            "mode": WorkforceAdoptionSetupReceipt.Mode.NEW_FOUNDATION,
            "organization_name": "Synthetic Volunteer Association",
            "series_name": "HelperCon",
            "edition_name": "HelperCon 2032",
            "starts_on": "2032-08-12",
            "ends_on": "2032-08-15",
            "time_zone": "Europe/Budapest",
            "idempotency_key": str(key),
        },
    )

    edition = EventEdition.objects.get()
    assert created.status_code == 302
    assert created["Location"] == reverse(
        "organization-representation",
        kwargs={"organization_slug": edition.organization.slug},
    )
    follow = client.get(created["Location"])
    follow_content = follow.content.decode()
    assert "Set up Maru operators" in follow_content
    assert "Step 2 of 3" in follow_content
    assert "Invite a controller" in follow_content

    record = client.get(
        reverse(
            "baseline-event-edition-record",
            kwargs={
                "organization_slug": edition.organization.slug,
                "series_slug": edition.series.slug,
                "edition_slug": edition.slug,
            },
        )
    )
    record_content = record.content.decode()
    assert record.status_code == 200
    assert "Adoption boundary" in record_content
    assert "Workforce only" in record_content
    assert "Payments and attendee registration" in record_content
    assert "Not adopted" in record_content
    assert 'name="currency_codes"' not in record_content

    session = client.session
    session[ADMIN_EDITION_SESSION_KEY] = str(edition.id)
    session.save()
    focused_home = client.get(reverse("admin:index"))
    specialist_home = client.get(f"{reverse('admin:index')}?records=open")
    assert "Need a technical record?" not in focused_home.content.decode()
    assert "Need a technical record?" in specialist_home.content.decode()


def test_guided_setup_requires_platform_administration() -> None:
    client = Client()
    client.force_login(AccountFactory())

    response = client.get(reverse("workforce-adoption-setup"))

    assert response.status_code == 403
