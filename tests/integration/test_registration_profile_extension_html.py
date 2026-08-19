"""Same-shell browser journeys for governed profile-extension values."""

from __future__ import annotations

from datetime import date, timedelta
from importlib import import_module
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth.models import Permission
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.participation.models import Participation
from maru.registration.configuration_lifecycle import (
    activate_registration_configuration,
    review_registration_configuration,
)
from maru.registration.models import (
    AdmissionProduct,
    AttendeeRegistrationProfile,
    ProfileExtensionAudience,
    ProfileExtensionReviewStatus,
    ProfileExtensionStatus,
    ProfileExtensionWriter,
    QuestionClassification,
    QuestionFieldType,
    Registration,
    RegistrationConfiguration,
    RegistrationProfileExtensionField,
    RegistrationProfileExtensionValueRevision,
    RegistrationSetupControl,
    RegistrationSetupOrigin,
    RegistrationSubmission,
)
from maru.registration.profile_extension_values import append_profile_extension_value
from maru.registration.profile_policy import DIRECTORY_CONSENT_VERSION
from maru.registration.setup_commands import start_registration_setup
from maru.registration.setup_definition_commands import create_admission_product
from maru.workforce.models import Department
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
)
from tests.workforce_helpers import create_department_for_test

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


def _grant(
    actor: Account,
    edition: EventEdition,
    capability: str,
    *,
    department: Department | None = None,
) -> None:
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        department=department,
        principal=actor,
        capability_code=capability,
        effective_from=timezone.now() - timedelta(minutes=1),
    )


def _governed_configuration(
    edition: EventEdition,
) -> tuple[RegistrationConfiguration, AdmissionProduct]:
    organizer = AccountFactory()
    _grant(organizer, edition, "registration.manage_configuration")
    started = start_registration_setup(
        actor=organizer,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        source_kind=RegistrationSetupOrigin.BLANK,
        source_id=None,
        name="Synthetic profile-value registration",
        opens_at=timezone.now() + timedelta(days=1),
        closes_at=timezone.now() + timedelta(days=30),
        capacity=100,
        currency="EUR",
        minimum_age=18,
        default_payment_window_minutes=1_440,
        waitlist_enabled=True,
        automatic_waitlist_promotion=True,
        expected_version=0,
        reason="Start the governed profile-value browser fixture.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    control = RegistrationSetupControl.objects.get(pk=started.setup_id)
    configuration = RegistrationConfiguration.objects.get(pk=started.configuration_id)
    product_result = create_admission_product(
        actor=organizer,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        configuration_id=configuration.id,
        code="profile-browser",
        name="Profile browser admission",
        description="Synthetic admission for the profile-value browser journey.",
        price_minor=0,
        capacity=100,
        entitlement_code="profile-browser-admission",
        entitlement_name="Profile browser admission",
        sales_open_at=None,
        sales_close_at=None,
        required_capacity_codes=[],
        eligibility_explanation="",
        waitlist_enabled=True,
        payment_window_minutes=None,
        after_product_id=None,
        expected_version=control.aggregate_version,
        reason="Add the governed profile-value admission product.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    configuration.refresh_from_db()
    reviewed = review_registration_configuration(
        actor=organizer,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        configuration_id=configuration.id,
        content_digest=configuration.content_digest,
        review_note="",
        expected_version=product_result.resulting_version,
        reason="Review the governed profile-value browser fixture.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    activate_registration_configuration(
        actor=organizer,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        configuration_id=configuration.id,
        content_digest=configuration.content_digest,
        edition_name_confirmation=edition.name,
        expected_version=reviewed.resulting_version,
        reason="Activate the governed profile-value browser fixture.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    configuration.refresh_from_db()
    return configuration, AdmissionProduct.objects.get(pk=product_result.target_id)


def _registration_world() -> tuple[Registration, Account]:
    edition = EventEditionFactory()
    configuration, product = _governed_configuration(edition)
    owner = AccountFactory()
    participation = Participation.objects.create(
        account=owner,
        organization=edition.organization,
        edition=edition,
        status=Participation.Status.CONFIRMED,
        edition_name_snapshot=edition.name,
        series_name_snapshot=edition.series.name,
    )
    registration = Registration.objects.create(
        organization=edition.organization,
        edition=edition,
        participation=participation,
        account=owner,
        configuration=configuration,
        product=product,
        reference=f"HTML-{uuid4().hex[:12]}",
        state=Registration.State.CONFIRMED,
        product_name_snapshot=product.name,
        price_minor_snapshot=product.price_minor,
        currency_snapshot=configuration.currency,
        submitted_at=timezone.now(),
        confirmed_at=timezone.now(),
        confirmation_basis=Registration.ConfirmationBasis.PROVIDER,
    )
    RegistrationSubmission.objects.create(
        registration=registration,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        configuration_version=configuration.version,
        schema_snapshot=[
            {
                "key": "original",
                "label": "Original answer",
                "field_type": QuestionFieldType.SHORT_TEXT,
                "purpose": "Preserve the synthetic submitted snapshot.",
            }
        ],
        answers={"original": "unchanged"},
        submitted_at=registration.submitted_at,
    )
    return registration, owner


def _directory_profile(registration: Registration) -> AttendeeRegistrationProfile:
    return AttendeeRegistrationProfile.objects.create(
        registration=registration,
        organization=registration.organization,
        edition=registration.edition,
        account=registration.account,
        real_name="Synthetic Directory Person",
        date_of_birth=date(1990, 1, 1),
        address_line_1="1 Synthetic Street",
        locality="Test City",
        postal_code="1000",
        region="Test Region",
        country_code="HU",
        emergency_contact_name="Synthetic Contact",
        emergency_contact_phone="+3610000000",
        phone_number="+3610000001",
        pronoun_code="they_them",
        pronouns="They/them",
        spoken_language_codes=["en"],
        directory_visible=True,
        directory_country_code="HU",
        directory_consent_version=DIRECTORY_CONSENT_VERSION,
        directory_consent_at=timezone.now(),
        collection_notice_version="synthetic-profile-v1",
    )


def _field(
    registration: Registration,
    *,
    key: str,
    field_type: str = QuestionFieldType.SHORT_TEXT,
    options: list[str] | None = None,
    required: bool = False,
    audience: str = ProfileExtensionAudience.SELF,
    department: Department | None = None,
    writer: str = ProfileExtensionWriter.ATTENDEE_AND_STAFF,
    position: int = 0,
) -> RegistrationProfileExtensionField:
    attendee_visible = audience in {
        ProfileExtensionAudience.SELF,
        ProfileExtensionAudience.CONFIRMED_ATTENDEES,
        ProfileExtensionAudience.PUBLIC,
    }
    return RegistrationProfileExtensionField.objects.create(
        organization=registration.organization,
        edition=registration.edition,
        key=key,
        version=1,
        label=f"Synthetic {key}",
        help_text="Provide one synthetic current profile detail.",
        field_type=field_type,
        options=options or [],
        purpose="Exercise the governed profile-value browser journey.",
        classification=QuestionClassification.PERSONAL,
        attendee_visible=attendee_visible,
        audience_policy=audience,
        audience_department=department,
        writer_policy=writer,
        required=required,
        position=position,
        review_status=ProfileExtensionReviewStatus.APPROVED,
        status=ProfileExtensionStatus.ACTIVE,
        created_by=registration.account,
        approved_by=registration.account,
        approved_at=timezone.now() - timedelta(minutes=1),
    )


def _client(actor: Account) -> Client:
    client = Client()
    client.force_login(actor)
    return client


def _assert_private(response: Any) -> None:
    directives = {
        item.strip().casefold()
        for item in response.headers.get("Cache-Control", "").split(",")
    }
    assert {"private", "no-store"}.issubset(directives)


def _self_url(registration: Registration) -> str:
    return reverse("my-profile-extension-values", args=(registration.edition_id,))


def _staff_url(registration: Registration) -> str:
    return reverse(
        "staff-profile-extension-values",
        kwargs={
            "organization_slug": registration.organization.slug,
            "series_slug": registration.edition.series.slug,
            "edition_slug": registration.edition.slug,
            "registration_id": registration.id,
        },
    )


def _editor(response: Any, field: RegistrationProfileExtensionField) -> Any:
    return next(
        editor
        for editor in response.context["profile_extension_editors"]
        if editor.field.field_id == field.id
    )


def _form_data(form: Any, value: str, *, reason: str | None = None) -> dict[str, str]:
    data = {
        "value": value,
        "expected_sequence": str(form["expected_sequence"].value()),
        "retry_key": str(form["retry_key"].value()),
    }
    if reason is not None:
        data["reason"] = reason
    return data


def _self_post_url(
    registration: Registration,
    field: RegistrationProfileExtensionField,
) -> str:
    return reverse(
        "update-my-profile-extension-value",
        args=(registration.edition_id, field.id),
    )


def _staff_post_url(
    registration: Registration,
    field: RegistrationProfileExtensionField,
) -> str:
    return reverse(
        "update-staff-profile-extension-value",
        kwargs={
            "organization_slug": registration.organization.slug,
            "series_slug": registration.edition.series.slug,
            "edition_slug": registration.edition.slug,
            "registration_id": registration.id,
            "field_id": field.id,
        },
    )


def test_self_browser_appends_replays_rejects_stale_and_keeps_personal_nav() -> None:
    registration, owner = _registration_world()
    field = _field(registration, key="arrival-note")
    client = _client(owner)

    workspace = client.get(_self_url(registration))
    assert workspace.status_code == 200
    _assert_private(workspace)
    body = workspace.content.decode()
    assert 'aria-label="Registration navigation"' in body
    assert 'class="baseline-sidebar"' not in body
    form = _editor(workspace, field).form
    data = _form_data(form, "Synthetic arrival detail")

    created = client.post(_self_post_url(registration, field), data)
    replayed = client.post(_self_post_url(registration, field), data)
    changed_retry = client.post(
        _self_post_url(registration, field),
        {**data, "value": "Changed retry intent"},
    )
    stale = client.post(
        _self_post_url(registration, field),
        {
            "value": "Stale write",
            "expected_sequence": "0",
            "retry_key": str(uuid4()),
        },
    )

    assert created.status_code == replayed.status_code == 302
    _assert_private(created)
    _assert_private(replayed)
    assert changed_retry.status_code == 409
    assert stale.status_code == 409
    _assert_private(changed_retry)
    _assert_private(stale)
    assert (
        RegistrationProfileExtensionValueRevision.objects.filter(
            registration=registration,
            field=field,
        ).count()
        == 1
    )
    profile = client.get(
        reverse("public-registration-profile", args=(registration.edition_id,))
    )
    assert profile.status_code == 200
    _assert_private(profile)
    assert "Edit current profile details" in profile.content.decode()


def test_optional_typed_clear_reappend_directory_removal_and_api_null_parity() -> None:
    registration, owner = _registration_world()
    _directory_profile(registration)
    public_boolean = _field(
        registration,
        key="public-bool",
        field_type=QuestionFieldType.BOOLEAN,
        audience=ProfileExtensionAudience.PUBLIC,
    )
    integer = _field(
        registration,
        key="optional-integer",
        field_type=QuestionFieldType.INTEGER,
        position=10,
    )
    choice = _field(
        registration,
        key="optional-choice",
        field_type=QuestionFieldType.SINGLE_CHOICE,
        options=["alpha", "beta"],
        position=20,
    )
    client = _client(owner)
    directory_url = reverse(
        "paid-attendee-directory",
        args=(registration.edition_id,),
    )

    for field, first, replacement in (
        (public_boolean, "true", "false"),
        (integer, "-4", "7"),
        (choice, "alpha", "beta"),
    ):
        workspace = client.get(_self_url(registration))
        form = _editor(workspace, field).form
        assert (
            client.post(
                _self_post_url(registration, field),
                _form_data(form, first),
            ).status_code
            == 302
        )
        if field == public_boolean:
            assert field.label in client.get(directory_url).content.decode()

        workspace = client.get(_self_url(registration))
        form = _editor(workspace, field).form
        assert (
            client.post(
                _self_post_url(registration, field),
                _form_data(form, ""),
            ).status_code
            == 302
        )
        latest = RegistrationProfileExtensionValueRevision.objects.filter(
            registration=registration,
            field=field,
        ).latest("sequence")
        assert latest.value is None
        if field == public_boolean:
            assert field.label not in client.get(directory_url).content.decode()

        workspace = client.get(_self_url(registration))
        form = _editor(workspace, field).form
        assert (
            client.post(
                _self_post_url(registration, field),
                _form_data(form, replacement),
            ).status_code
            == 302
        )
        latest = RegistrationProfileExtensionValueRevision.objects.filter(
            registration=registration,
            field=field,
        ).latest("sequence")
        assert latest.value in {False, 7, "beta"}

    api_url = reverse(
        "api-my-registration-profile-extensions",
        kwargs={
            "organization_id": registration.organization_id,
            "edition_id": registration.edition_id,
        },
    )
    cleared = client.post(
        api_url,
        data={
            "field_id": str(choice.id),
            "value": None,
            "expected_sequence": 3,
        },
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert cleared.status_code == 200
    choice_payload = next(
        item for item in cleared.json()["fields"] if item["id"] == str(choice.id)
    )
    assert choice_payload["current_value"] is None


def test_exact_department_staff_workspace_writes_and_admin_link_is_governed() -> None:
    registration, _owner = _registration_world()
    self_field = _field(registration, key="owner-only")
    staff_field = _field(
        registration,
        key="registration-staff",
        audience=ProfileExtensionAudience.REGISTRATION_STAFF,
        writer=ProfileExtensionWriter.REGISTRATION_STAFF,
    )
    department = create_department_for_test(
        edition=registration.edition,
        name="Registration Support",
        expected_code="registration-support",
    )
    sibling = create_department_for_test(
        edition=registration.edition,
        name="Convention Programme",
        expected_code="convention-programme",
    )
    department_field = _field(
        registration,
        key="department-note",
        audience=ProfileExtensionAudience.DEPARTMENT,
        department=department,
        writer=ProfileExtensionWriter.REGISTRATION_STAFF,
        position=10,
    )
    exact_staff = AccountFactory(is_staff=True)
    _grant(
        exact_staff,
        registration.edition,
        "registration.view_profile_extensions",
        department=department,
    )
    _grant(
        exact_staff,
        registration.edition,
        "registration.update_profile_extensions",
    )
    django_view = Permission.objects.get(
        content_type__app_label="registration",
        codename="view_registration",
    )
    exact_staff.user_permissions.add(django_view)
    client = _client(exact_staff)

    workspace = client.get(_staff_url(registration))
    assert workspace.status_code == 200
    _assert_private(workspace)
    body = workspace.content.decode()
    assert department_field.label in body
    assert staff_field.label not in body
    assert self_field.label not in body
    assert 'class="maru-admin-brand"' in body
    assert 'aria-label="Registration navigation"' not in body
    form = _editor(workspace, department_field).form
    changed = client.post(
        _staff_post_url(registration, department_field),
        _form_data(form, "Synthetic staff detail", reason="Verified at help desk."),
    )
    assert changed.status_code == 302
    _assert_private(changed)
    revision = RegistrationProfileExtensionValueRevision.objects.get(
        registration=registration,
        field=department_field,
    )
    assert revision.actor == exact_staff
    assert revision.reason == "Verified at help desk."

    admin_page = client.get(
        reverse("admin:registration_registration_change", args=(registration.id,))
    )
    assert admin_page.status_code == 200
    assert _staff_url(registration) in admin_page.content.decode()

    sibling_staff = AccountFactory(is_staff=True)
    sibling_staff.user_permissions.add(django_view)
    _grant(
        sibling_staff,
        registration.edition,
        "registration.view_profile_extensions",
        department=sibling,
    )
    _grant(
        sibling_staff,
        registration.edition,
        "registration.update_profile_extensions",
    )
    sibling_client = _client(sibling_staff)
    assert sibling_client.get(_staff_url(registration)).status_code == 404
    sibling_admin = sibling_client.get(
        reverse("admin:registration_registration_change", args=(registration.id,))
    )
    assert sibling_admin.status_code == 200
    assert _staff_url(registration) not in sibling_admin.content.decode()

    platform_admin = AccountFactory(is_staff=True, is_superuser=True)
    platform_client = _client(platform_admin)
    assert platform_client.get(_staff_url(registration)).status_code == 404
    platform_admin_page = platform_client.get(
        reverse("admin:registration_registration_change", args=(registration.id,))
    )
    assert platform_admin_page.status_code == 200
    assert _staff_url(registration) not in platform_admin_page.content.decode()


def test_writer_policy_and_foreign_denials_happen_before_form_binding() -> None:
    registration, owner = _registration_world()
    self_field = _field(registration, key="attendee-managed")
    staff_field = _field(
        registration,
        key="staff-managed",
        audience=ProfileExtensionAudience.REGISTRATION_STAFF,
        writer=ProfileExtensionWriter.REGISTRATION_STAFF,
        position=10,
    )
    staff = AccountFactory()
    _grant(staff, registration.edition, "registration.view_profile_extensions")
    _grant(staff, registration.edition, "registration.update_profile_extensions")
    outsider = AccountFactory()
    platform_admin = AccountFactory(is_staff=True, is_superuser=True)
    foreign_edition = EventEditionFactory()

    with patch(
        "maru.registration.profile_extension_views.ProfileExtensionValueForm",
        side_effect=AssertionError("self form bound before denial"),
    ):
        assert (
            _client(owner)
            .post(
                _self_post_url(registration, staff_field),
                {"unexpected": "value"},
            )
            .status_code
            == 404
        )
        assert (
            _client(outsider)
            .post(
                _self_post_url(registration, self_field),
                {"unexpected": "value"},
            )
            .status_code
            == 404
        )

    with patch(
        "maru.registration.profile_extension_views.StaffProfileExtensionValueForm",
        side_effect=AssertionError("staff form bound before denial"),
    ):
        assert (
            _client(staff)
            .post(
                _staff_post_url(registration, self_field),
                {"unexpected": "value"},
            )
            .status_code
            == 404
        )
        assert (
            _client(outsider)
            .post(
                _staff_post_url(registration, staff_field),
                {"unexpected": "value"},
            )
            .status_code
            == 404
        )
        assert (
            _client(platform_admin)
            .post(
                _staff_post_url(registration, staff_field),
                {"unexpected": "value"},
            )
            .status_code
            == 404
        )
        foreign_url = reverse(
            "update-staff-profile-extension-value",
            kwargs={
                "organization_slug": foreign_edition.organization.slug,
                "series_slug": foreign_edition.series.slug,
                "edition_slug": foreign_edition.slug,
                "registration_id": registration.id,
                "field_id": staff_field.id,
            },
        )
        assert (
            _client(staff)
            .post(
                foreign_url,
                {"unexpected": "value"},
            )
            .status_code
            == 404
        )


def test_optional_clear_database_guard_and_reverse_fence() -> None:
    registration, owner = _registration_world()
    optional = _field(
        registration,
        key="guard-optional-bool",
        field_type=QuestionFieldType.BOOLEAN,
    )
    required = _field(
        registration,
        key="guard-required-bool",
        field_type=QuestionFieldType.BOOLEAN,
        required=True,
        position=10,
    )
    insert_sql = """
        INSERT INTO registration_registrationprofileextensionvaluerevision (
            id, registration_id, organization_id, edition_id, field_id,
            field_key, sequence, value, actor_id, source_channel, reason,
            created_at, updated_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s, 1, %s::jsonb, %s, 'test', '',
            statement_timestamp(), statement_timestamp()
        )
    """
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "AND table_name = "
            "'registration_registrationprofileextensionvaluerevision' "
            "AND column_name = 'value'"
        )
        assert cursor.fetchone() == ("NO",)
        cursor.execute(
            insert_sql,
            [
                uuid4(),
                registration.id,
                registration.organization_id,
                registration.edition_id,
                optional.id,
                optional.key,
                "null",
                owner.id,
            ],
        )
        cursor.execute(
            "SELECT jsonb_typeof(value) FROM "
            "registration_registrationprofileextensionvaluerevision "
            "WHERE registration_id = %s AND field_key = %s",
            [registration.id, optional.key],
        )
        assert cursor.fetchone() == ("null",)
        transaction.set_rollback(True)

    with (
        pytest.raises(IntegrityError),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            insert_sql,
            [
                uuid4(),
                registration.id,
                registration.organization_id,
                registration.edition_id,
                optional.id,
                optional.key,
                None,
                owner.id,
            ],
        )

    with (
        pytest.raises(IntegrityError),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            insert_sql,
            [
                uuid4(),
                registration.id,
                registration.organization_id,
                registration.edition_id,
                required.id,
                required.key,
                "null",
                owner.id,
            ],
        )

    result = append_profile_extension_value(
        actor=owner,
        organization_id=registration.organization_id,
        edition_id=registration.edition_id,
        registration_id=registration.id,
        field_id=optional.id,
        value=None,
        expected_sequence=0,
        retry_key=uuid4(),
        correlation_id=uuid4(),
        request_id=uuid4(),
        source_channel="test",
    )
    assert result.value is None
    migration = import_module(
        "maru.registration.migrations.0040_optional_profile_value_clear"
    )
    with (
        pytest.raises(DatabaseError) as exc_info,
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(migration.REVERSE_SQL)
    assert "cannot reverse optional profile-value clear" in str(exc_info.value)
