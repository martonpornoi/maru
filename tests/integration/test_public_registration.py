from dataclasses import replace
from datetime import date, timedelta
from io import BytesIO
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.db.models import F
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.participation.models import Participation
from maru.registration.models import (
    AdmissionProduct,
    AttendeeFursuit,
    AttendeeRegistrationProfile,
    ConfigurationStatus,
    MediaReviewStatus,
    Registration,
    RegistrationQuestion,
    RegistrationSection,
    RegistrationSubmission,
)
from maru.registration.profile_policy import (
    MAX_FURSUIT_PHOTO_BYTES,
    PROFILE_FIELD_POLICY,
)
from maru.registration.services import (
    AttendeeFursuitInput,
    AttendeeProfileInput,
    review_attendee_media,
    update_attendee_profile,
)
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    ConventionSeriesFactory,
    EventEditionFactory,
    ParticipationCapacityFactory,
    ParticipationFactory,
    RegistrationConfigurationFactory,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]


def _valid_image_bytes(image_format: str = "PNG") -> bytes:
    output = BytesIO()
    Image.new("RGB", (4, 4), "#446688").save(output, format=image_format)
    return output.getvalue()


def _open_public_world(
    *,
    price_minor: int = 0,
    edition: EventEdition | None = None,
):
    edition = edition or EventEditionFactory()
    configuration = RegistrationConfigurationFactory(
        edition=edition,
        opens_at=timezone.now() - timedelta(days=1),
        closes_at=timezone.now() + timedelta(days=30),
        minimum_age=18,
    )
    section = RegistrationSection.objects.create(
        configuration=configuration,
        key="about-you",
        title="About your convention visit",
        description="Questions selected by this convention.",
        position=10,
    )
    RegistrationQuestion.objects.create(
        configuration=configuration,
        section=section,
        key="badge-name",
        label="Name on your badge",
        field_type="short_text",
        required=True,
        position=10,
        purpose="Print the attendee badge.",
    )
    optional_questions = (
        ("visit-notes", "Anything else?", "long_text", [], 20),
        ("first-convention", "Is this your first convention?", "boolean", [], 30),
        ("party-size", "People in your party", "integer", [], 40),
        (
            "visit-kind",
            "What kind of visit is this?",
            "single_choice",
            ["Newcomer", "Returning attendee"],
            50,
        ),
        (
            "interests",
            "What interests you?",
            "multiple_choice",
            ["Art", "Dance", "Gaming"],
            60,
        ),
    )
    for key, label, field_type, options, position in optional_questions:
        RegistrationQuestion.objects.create(
            configuration=configuration,
            section=section,
            key=key,
            label=label,
            field_type=field_type,
            options=options,
            required=False,
            position=position,
            purpose="Tailor the attendee experience.",
        )
    product = AdmissionProduct.objects.create(
        configuration=configuration,
        code="weekend",
        name="Weekend admission",
        description="Admission for the complete convention.",
        price_minor=price_minor,
        capacity=100,
        position=10,
        entitlement_code="infinity-admission",
        entitlement_name="Infinity ticket holder",
    )
    configuration.status = ConfigurationStatus.ACTIVE
    configuration.review_required = False
    configuration.review_note = "Public registration fixture reviewed."
    configuration.activated_at = timezone.now()
    configuration.save(
        update_fields=(
            "status",
            "review_required",
            "review_note",
            "activated_at",
            "updated_at",
        )
    )
    return edition, configuration, product


def _public_payload(
    product: AdmissionProduct, **overrides: object
) -> dict[str, object]:
    payload: dict[str, object] = {
        "email": "new.attendee@example.invalid",
        "display_name": "Moss Otter",
        "password1": "Distinct public password 927!",
        "password2": "Distinct public password 927!",
        "product": str(product.id),
        "real_name": "Morgan Example",
        "date_of_birth": "2000-05-20",
        "pronoun_code": "they_them",
        "other_pronouns": "",
        "bio": "A friendly river otter.",
        "spoken_language_codes": ["en", "hu"],
        "phone_number": "+36 30 555 0123",
        "telegram_handle": "@moss_otter",
        "address_line_1": "12 Example Street",
        "address_line_2": "Apartment 4",
        "locality": "Budapest",
        "postal_code": "1051",
        "region": "Budapest",
        "country_code": "hu",
        "emergency_contact_name": "River Example",
        "emergency_contact_phone": "+36 20 555 0199",
        "brings_fursuits": "on",
        "fursuits-TOTAL_FORMS": "1",
        "fursuits-INITIAL_FORMS": "0",
        "fursuits-MIN_NUM_FORMS": "0",
        "fursuits-MAX_NUM_FORMS": "10",
        "fursuits-0-name": "Moss",
        "fursuits-0-species": "River otter",
        "fursuits-0-keep_photo": "on",
        "directory_visible": "on",
        "directory_country_code": "hu",
        "question__badge-name": "Moss",
    }
    payload.update(overrides)
    if not payload.get("directory_visible"):
        payload["directory_country_code"] = ""
    return payload


def _edit_payload(
    profile: AttendeeRegistrationProfile,
    **overrides: object,
) -> dict[str, object]:
    fursuits = list(profile.fursuits.filter(is_active=True).order_by("position"))
    payload: dict[str, object] = {
        "real_name": profile.real_name,
        "date_of_birth": profile.date_of_birth.isoformat(),
        "pronoun_code": profile.pronoun_code,
        "other_pronouns": profile.other_pronouns,
        "bio": profile.bio,
        "spoken_language_codes": profile.spoken_language_codes,
        "phone_number": profile.phone_number,
        "telegram_handle": profile.telegram_handle,
        "address_line_1": profile.address_line_1,
        "address_line_2": profile.address_line_2,
        "locality": profile.locality,
        "postal_code": profile.postal_code,
        "region": profile.region,
        "country_code": profile.country_code,
        "emergency_contact_name": profile.emergency_contact_name,
        "emergency_contact_phone": profile.emergency_contact_phone,
        "keep_profile_photo": "on",
        "brings_fursuits": "on" if fursuits else "",
        "directory_visible": "on" if profile.directory_visible else "",
        "directory_country_code": profile.directory_country_code,
        "fursuits-TOTAL_FORMS": str(len(fursuits) + 1),
        "fursuits-INITIAL_FORMS": str(len(fursuits)),
        "fursuits-MIN_NUM_FORMS": "0",
        "fursuits-MAX_NUM_FORMS": "10",
    }
    for index, fursuit in enumerate(fursuits):
        payload.update(
            {
                f"fursuits-{index}-fursuit_id": str(fursuit.id),
                f"fursuits-{index}-name": fursuit.name,
                f"fursuits-{index}-species": fursuit.species,
                f"fursuits-{index}-keep_photo": "on",
            }
        )
    payload.update(overrides)
    if not payload.get("directory_visible"):
        payload["directory_country_code"] = ""
    return payload


def test_staff_assistance_creates_audited_new_account_without_admin_detour() -> None:
    edition, _configuration, product = _open_public_world(price_minor=2_500)
    actor = AccountFactory(
        email="registration-lead@example.invalid",
        display_name="Registration Lead",
    )
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=actor,
        capability_code="registration.register_on_behalf",
    )
    client = Client()
    client.force_login(actor)
    account_email = "new-volunteer@example.invalid"
    payload = _public_payload(
        product,
        account_email=account_email,
        new_account_display_name="New Volunteer",
        new_account_password1="Distinct temporary password 492!",
        new_account_password2="Distinct temporary password 492!",
        staff_reason="Approved volunteer added before the public registration window.",
    )

    response = client.post(
        reverse("management-assisted-registration", args=(edition.id,)),
        payload,
    )

    assert response.status_code == 302
    account = Account.objects.get(email=account_email)
    assert account.display_name == "New Volunteer"
    assert account.check_password("Distinct temporary password 492!")
    registration = Registration.objects.get(account=account, edition=edition)
    assert registration.state == Registration.State.PAYMENT_PENDING
    assert (
        registration.submission_source == Registration.SubmissionSource.STAFF_ASSISTED
    )
    assert registration.submitted_by == actor
    assert registration.attendee_profile.phone_number == "+36305550123"
    assert AuditEvent.objects.filter(
        operation="identity.account.create_for_registration",
        target_id=account.id,
        principal_id=actor.id,
        reason_code="staff_assisted_account_creation",
    ).exists()


def test_staff_assistance_explains_new_account_fields() -> None:
    edition, _configuration, _product = _open_public_world()
    actor = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=actor,
        capability_code="registration.register_on_behalf",
    )
    client = Client()
    client.force_login(actor)

    response = client.get(
        reverse("management-assisted-registration", args=(edition.id,))
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert "New-email fallback" in content
    assert "New account display name" in content
    assert "temporary password" in content


def test_anonymous_attendee_creates_account_profile_and_registration(
    tmp_path,
    settings,
) -> None:
    settings.MEDIA_ROOT = tmp_path
    edition, _configuration, product = _open_public_world()
    photo = SimpleUploadedFile(
        "moss.webp",
        _valid_image_bytes("WEBP"),
        content_type="image/webp",
    )
    client = Client()

    response = client.post(
        reverse("public-registration-form", args=(edition.id,)),
        data=_public_payload(
            product,
            **{"fursuits-0-photo": photo},
            **{
                "question__visit-notes": "Looking forward to meeting everyone.",
                "question__first-convention": "true",
                "question__party-size": "3",
                "question__visit-kind": "Newcomer",
                "question__interests": ["Art", "Dance"],
            },
        ),
    )

    assert response.status_code == 302
    assert response["Location"] == reverse(
        "public-registration-profile",
        args=(edition.id,),
    )
    account = Account.objects.get(email="new.attendee@example.invalid")
    assert client.session["_auth_user_id"] == str(account.id)
    participation = Participation.objects.get(account=account, edition=edition)
    assert participation.status == Participation.Status.PENDING
    registration = Registration.objects.get(account=account, edition=edition)
    assert registration.state == Registration.State.CONFIRMED
    profile = AttendeeRegistrationProfile.objects.get(registration=registration)
    assert profile.real_name == "Morgan Example"
    assert profile.country_code == "HU"
    assert profile.directory_country_code == "HU"
    assert profile.telegram_handle == "moss_otter"
    assert profile.directory_visible is True
    assert profile.directory_consent_at is not None
    assert profile.spoken_language_codes == ["en", "hu"]
    assert profile.bio == "A friendly river otter."
    fursuit = AttendeeFursuit.objects.get(profile=profile, is_active=True)
    assert fursuit.photo.name.endswith(".jpg")
    assert fursuit.photo_status == "pending"
    submission = RegistrationSubmission.objects.get(registration=registration)
    assert submission.answers == {
        "badge-name": "Moss",
        "first-convention": True,
        "interests": ["Art", "Dance"],
        "party-size": 3,
        "visit-kind": "Newcomer",
        "visit-notes": "Looking forward to meeting everyone.",
    }
    assert submission.schema_snapshot[0]["section"]["title"] == (
        "About your convention visit"
    )

    profile_response = client.get(response["Location"])
    assert profile_response.status_code == 200
    content = profile_response.content.decode()
    assert "Morgan Example" in content
    assert "Infinity ticket holder" in content
    assert "Yes" in content
    assert "Art, Dance" in content
    assert "Real name, birth date, and emergency contact are restricted" in content

    directory_response = client.get(
        reverse("paid-attendee-directory", args=(edition.id,))
    )
    directory_content = directory_response.content.decode()
    assert directory_response.status_code == 200
    assert "Moss Otter" in directory_content
    assert "River otter" in directory_content
    assert "Morgan Example" not in directory_content
    assert "+36 30 555 0123" not in directory_content

    photo_response = client.get(reverse("protected-fursuit-photo", args=(fursuit.id,)))
    assert photo_response.status_code == 200
    assert photo_response["Cache-Control"] == "private, no-store"
    assert photo_response["X-Content-Type-Options"] == "nosniff"


def test_returning_attendee_chooses_between_open_editions() -> None:
    first_edition, _first_configuration, first_product = _open_public_world()
    second_edition, _second_configuration, _second_product = _open_public_world()
    account = AccountFactory(
        email="returning@example.invalid",
        display_name="Returning Attendee",
    )
    ParticipationFactory(account=account, edition=first_edition)
    client = Client()
    client.force_login(account)

    response = client.get(reverse("public-registration-index"))

    assert response.status_code == 200
    content = response.content.decode()
    assert first_edition.name in content
    assert second_edition.name in content
    assert "Register for this convention" in content
    assert "Choose your convention" in content
    form_response = client.get(
        reverse("public-registration-form", args=(second_edition.id,))
    )
    assert form_response.status_code == 200
    assert 'name="email"' not in form_response.content.decode()
    assert str(first_product.id) not in form_response.content.decode()


def test_existing_email_uses_sign_in_path_without_modifying_account() -> None:
    edition, _configuration, product = _open_public_world()
    existing = AccountFactory(
        email="new.attendee@example.invalid",
        display_name="Existing Person",
    )
    client = Client()

    response = client.post(
        reverse("public-registration-form", args=(edition.id,)),
        data=_public_payload(product),
    )

    assert response.status_code == 200
    assert "Sign in to continue" in response.content.decode()
    existing.refresh_from_db()
    assert existing.display_name == "Existing Person"
    assert not Participation.objects.filter(account=existing, edition=edition).exists()
    assert not Registration.objects.filter(account=existing, edition=edition).exists()


def test_age_boundary_fails_without_creating_account() -> None:
    edition, _configuration, product = _open_public_world()
    client = Client()

    response = client.post(
        reverse("public-registration-form", args=(edition.id,)),
        data=_public_payload(product, date_of_birth="2020-05-20"),
    )

    assert response.status_code == 200
    assert "guardian workflow has not been configured" in response.content.decode()
    assert not Account.objects.filter(email="new.attendee@example.invalid").exists()


def test_reference_profile_form_rejects_unsafe_or_inconsistent_input() -> None:
    edition, _configuration, product = _open_public_world()
    path = reverse("public-registration-form", args=(edition.id,))
    client = Client()
    cases = (
        (
            {
                "profile_photo": SimpleUploadedFile(
                    "profile.pdf",
                    b"not-an-image",
                    content_type="application/pdf",
                )
            },
            "Upload a JPEG, PNG, or WebP image.",
        ),
        (
            {
                "profile_photo": SimpleUploadedFile(
                    "profile.png",
                    b"x" * (MAX_FURSUIT_PHOTO_BYTES + 1),
                    content_type="image/png",
                )
            },
            "Use an image no larger than 5 MB.",
        ),
        ({"date_of_birth": "2099-01-01"}, "cannot be in the future"),
        ({"date_of_birth": "1800-01-01"}, "Check the date of birth"),
        (
            {
                "fursuits-0-name": "",
                "fursuits-0-species": "",
            },
            "Add at least one fursuit",
        ),
        (
            {"brings_fursuits": "", "fursuits-0-name": "Moss"},
            "Select the fursuit checkbox",
        ),
        (
            {"fursuits-0-name": "", "fursuits-0-species": "Otter"},
            "Enter a name for this fursuit",
        ),
        (
            {"password2": "Different public password 927!"},
            "The passwords do not match",
        ),
        (
            {"password1": "short", "password2": "short"},
            "password is too short",
        ),
    )
    for changes, expected in cases:
        response = client.post(path, data=_public_payload(product, **changes))
        assert response.status_code == 200
        assert expected in response.content.decode()

    assert not Account.objects.filter(email="new.attendee@example.invalid").exists()


def test_profile_suggestion_and_self_profile_missing_states_are_explicit() -> None:
    edition, _configuration, _product = _open_public_world()
    account = AccountFactory()
    client = APIClient()
    client.force_authenticate(account)

    suggestion = client.get(reverse("api-self-profile-suggestion", args=(edition.id,)))
    assert suggestion.status_code == 204
    missing_profile = client.get(
        f"/api/v1/organizations/{edition.organization_id}/editions/"
        f"{edition.id}/registration/me/profile"
    )
    assert missing_profile.status_code == 404


def test_public_list_is_anonymous_but_unapproved_media_remains_private(
    tmp_path,
    settings,
) -> None:
    settings.MEDIA_ROOT = tmp_path
    edition, _configuration, product = _open_public_world()
    owner_client = Client()
    owner_client.post(
        reverse("public-registration-form", args=(edition.id,)),
        data=_public_payload(
            product,
            **{
                "fursuits-0-photo": SimpleUploadedFile(
                    "moss.png",
                    _valid_image_bytes(),
                    content_type="image/png",
                )
            },
        ),
    )
    profile = AttendeeRegistrationProfile.objects.get(edition=edition)
    fursuit = AttendeeFursuit.objects.get(profile=profile)
    outsider = AccountFactory()
    outsider_client = Client()
    outsider_client.force_login(outsider)

    assert (
        outsider_client.get(
            reverse("paid-attendee-directory", args=(edition.id,))
        ).status_code
        == 200
    )
    assert (
        outsider_client.get(
            reverse("protected-fursuit-photo", args=(fursuit.id,))
        ).status_code
        == 404
    )

    peer = AccountFactory(display_name="Paid Peer")
    peer_client = Client()
    peer_client.force_login(peer)
    peer_response = peer_client.post(
        reverse("public-registration-form", args=(edition.id,)),
        data=_public_payload(
            product,
            directory_visible="",
            brings_fursuits="",
            **{
                "fursuits-0-name": "",
                "fursuits-0-species": "",
            },
            **{"question__badge-name": "Paid Peer"},
        ),
    )
    assert peer_response.status_code == 302
    assert (
        peer_client.get(
            reverse("paid-attendee-directory", args=(edition.id,))
        ).status_code
        == 200
    )
    assert (
        peer_client.get(
            reverse("protected-fursuit-photo", args=(fursuit.id,))
        ).status_code
        == 404
    )
    EventEdition.objects.filter(id=edition.id).update(
        lifecycle=EventEdition.Lifecycle.CANCELLED,
        lifecycle_version=F("lifecycle_version") + 1,
        aggregate_version=F("aggregate_version") + 1,
    )
    assert (
        outsider_client.get(
            reverse("paid-attendee-directory", args=(edition.id,))
        ).status_code
        == 404
    )
    assert (
        outsider_client.get(
            reverse("api-public-attendee-list", args=(edition.id,))
        ).status_code
        == 404
    )


def test_profile_policy_inventory_covers_every_collected_category() -> None:
    assert set(PROFILE_FIELD_POLICY) == {
        "real_name",
        "date_of_birth",
        "address",
        "emergency_contact",
        "phone_number",
        "telegram_handle",
        "pronouns",
        "bio",
        "spoken_languages",
        "profile_media",
        "fursuit_identity",
        "directory_visible",
        "directory_country_code",
    }
    assert PROFILE_FIELD_POLICY["real_name"].classification == "C3"
    assert PROFILE_FIELD_POLICY["emergency_contact"].classification == "C3"
    assert PROFILE_FIELD_POLICY["directory_visible"].visibility == (
        "Public after payment confirmation."
    )


def test_prior_directory_consent_does_not_expand_to_country_or_labels() -> None:
    edition, _configuration, product = _open_public_world()
    client = Client()
    created = client.post(
        reverse("public-registration-form", args=(edition.id,)),
        data=_public_payload(product),
    )
    assert created.status_code == 302
    profile = AttendeeRegistrationProfile.objects.get(edition=edition)
    profile.directory_consent_version = "paid-attendee-directory-v1"
    profile.aggregate_version += 1
    profile.save(
        update_fields=(
            "directory_consent_version",
            "aggregate_version",
            "updated_at",
        )
    )

    public_item = (
        Client().get(reverse("api-public-attendee-list", args=(edition.id,))).json()[0]
    )

    assert public_item["country_code"] == ""
    assert public_item["attendance_labels"] == []


def test_profile_scope_and_retention_are_database_guarded() -> None:
    edition, _configuration, product = _open_public_world()
    client = Client()
    response = client.post(
        reverse("public-registration-form", args=(edition.id,)),
        data=_public_payload(product, directory_visible=""),
    )
    assert response.status_code == 302
    profile = AttendeeRegistrationProfile.objects.get(edition=edition)
    other_edition = EventEditionFactory()

    with transaction.atomic(), pytest.raises(IntegrityError):
        AttendeeRegistrationProfile.objects.filter(id=profile.id).update(
            organization_id=other_edition.organization_id,
            edition_id=other_edition.id,
        )
    with pytest.raises(ValidationError, match="retention workflow"):
        profile.delete()
    with transaction.atomic(), pytest.raises(IntegrityError):
        AttendeeRegistrationProfile.objects.filter(id=profile.id).delete()


def test_profile_page_derives_volunteer_department_from_capacity() -> None:
    edition, _configuration, product = _open_public_world()
    account = AccountFactory()
    participation = ParticipationFactory(account=account, edition=edition)
    ParticipationCapacityFactory(
        participation=participation,
        code="volunteer.department.registration",
        label_snapshot="Registration volunteer",
    )
    client = Client()
    client.force_login(account)
    payload = _public_payload(product)

    response = client.post(
        reverse("public-registration-form", args=(edition.id,)),
        data=payload,
    )

    assert response.status_code == 302
    profile_response = client.get(response["Location"])
    assert "Registration volunteer" in profile_response.content.decode()


def test_prior_profile_is_a_suggestion_and_new_snapshot_does_not_rewrite_it() -> None:
    series = ConventionSeriesFactory()
    prior_edition = EventEditionFactory(
        series=series,
        starts_on=date(2029, 8, 1),
        ends_on=date(2029, 8, 4),
    )
    future_edition = EventEditionFactory(
        series=series,
        starts_on=date(2030, 8, 1),
        ends_on=date(2030, 8, 4),
    )
    _prior, _prior_configuration, prior_product = _open_public_world(
        edition=prior_edition
    )
    _future, _future_configuration, future_product = _open_public_world(
        edition=future_edition
    )
    client = Client()
    response = client.post(
        reverse("public-registration-form", args=(prior_edition.id,)),
        data=_public_payload(prior_product, address_line_1="Old Address 12"),
    )
    assert response.status_code == 302
    account = Account.objects.get(email="new.attendee@example.invalid")
    prior_profile = AttendeeRegistrationProfile.objects.get(
        account=account,
        edition=prior_edition,
    )
    suggestion = client.get(
        reverse("public-registration-form", args=(future_edition.id,))
    )
    content = suggestion.content.decode()
    assert suggestion.status_code == 200
    assert "We filled in suggestions" in content
    assert "Old Address 12" in content
    assert "Public-list consent is not carried over" in content

    submitted = client.post(
        reverse("public-registration-form", args=(future_edition.id,)),
        data=_public_payload(
            future_product,
            address_line_1="New Address 44",
            email="ignored-for-signed-in@example.invalid",
        ),
    )
    assert submitted.status_code == 302
    prior_profile.refresh_from_db()
    future_profile = AttendeeRegistrationProfile.objects.get(
        account=account,
        edition=future_edition,
    )
    assert prior_profile.address_line_1 == "Old Address 12"
    assert future_profile.address_line_1 == "New Address 44"
    assert prior_profile.id != future_profile.id


def test_pronoun_other_is_conditional_and_languages_are_limited_to_five() -> None:
    edition, _configuration, product = _open_public_world()
    client = Client()

    missing_other = client.post(
        reverse("public-registration-form", args=(edition.id,)),
        data=_public_payload(
            product,
            pronoun_code="other",
            other_pronouns="",
        ),
    )
    assert missing_other.status_code == 200
    assert "Enter the pronouns you want displayed" in missing_other.content.decode()

    too_many_languages = client.post(
        reverse("public-registration-form", args=(edition.id,)),
        data=_public_payload(
            product,
            spoken_language_codes=["en", "hu", "de", "fr", "es", "it"],
        ),
    )
    assert too_many_languages.status_code == 200
    assert "Choose no more than 5" in too_many_languages.content.decode()

    accepted = client.post(
        reverse("public-registration-form", args=(edition.id,)),
        data=_public_payload(
            product,
            pronoun_code="other",
            other_pronouns="star/stars",
            spoken_language_codes=["en", "hu", "de", "fr", "es"],
        ),
    )
    assert accepted.status_code == 302
    profile = AttendeeRegistrationProfile.objects.get(edition=edition)
    assert profile.pronouns == "star/stars"
    assert profile.spoken_language_codes == ["en", "hu", "de", "fr", "es"]


def test_multiple_fursuits_and_profile_edits_leave_submission_immutable() -> None:
    edition, _configuration, product = _open_public_world()
    account = AccountFactory()
    client = Client()
    client.force_login(account)
    payload = _public_payload(
        product,
        **{
            "fursuits-TOTAL_FORMS": "2",
            "fursuits-0-name": "Moss",
            "fursuits-0-species": "River otter",
            "fursuits-1-name": "Ember",
            "fursuits-1-species": "Red panda",
        },
    )
    response = client.post(
        reverse("public-registration-form", args=(edition.id,)),
        data=payload,
    )
    assert response.status_code == 302
    profile = AttendeeRegistrationProfile.objects.get(
        account=account,
        edition=edition,
    )
    assert list(
        profile.fursuits.filter(is_active=True).values_list("name", flat=True)
    ) == ["Moss", "Ember"]
    submission = RegistrationSubmission.objects.get(registration=profile.registration)
    original_answers = submission.answers.copy()

    edit_payload = _edit_payload(
        profile,
        address_line_1="Changed Address 99",
        bio="Updated after registration.",
        spoken_language_codes=["en"],
        directory_visible="",
    )
    edit_response = client.post(
        reverse("edit-attendee-profile", args=(edition.id,)),
        data=edit_payload,
    )
    assert edit_response.status_code == 302
    profile.refresh_from_db()
    submission.refresh_from_db()
    assert profile.address_line_1 == "Changed Address 99"
    assert profile.bio == "Updated after registration."
    assert profile.directory_visible is False
    assert submission.answers == original_answers

    EventEdition.objects.filter(id=edition.id).update(
        starts_on=date(2024, 8, 1),
        ends_on=date(2024, 8, 4),
        aggregate_version=F("aggregate_version") + 1,
    )
    closed_response = client.get(reverse("edit-attendee-profile", args=(edition.id,)))
    assert closed_response.status_code == 409


def test_media_moderation_public_projection_and_exact_reuse(  # noqa: PLR0915
    tmp_path,
    settings,
) -> None:
    settings.MEDIA_ROOT = tmp_path
    series = ConventionSeriesFactory()
    source_edition = EventEditionFactory(
        series=series,
        starts_on=date(2029, 8, 1),
        ends_on=date(2029, 8, 4),
    )
    target_edition = EventEditionFactory(
        series=series,
        starts_on=date(2030, 8, 1),
        ends_on=date(2030, 8, 4),
    )
    _, _, source_product = _open_public_world(edition=source_edition)
    _, _, target_product = _open_public_world(edition=target_edition)
    owner_client = Client()
    created = owner_client.post(
        reverse("public-registration-form", args=(source_edition.id,)),
        data=_public_payload(
            source_product,
            profile_photo=SimpleUploadedFile(
                "profile.png",
                _valid_image_bytes(),
                content_type="image/png",
            ),
            **{
                "fursuits-0-photo": SimpleUploadedFile(
                    "moss.png",
                    _valid_image_bytes(),
                    content_type="image/png",
                )
            },
        ),
    )
    assert created.status_code == 302
    source_profile = AttendeeRegistrationProfile.objects.get(edition=source_edition)
    source_fursuit = AttendeeFursuit.objects.get(profile=source_profile)
    anonymous = Client()
    assert (
        anonymous.get(
            reverse("protected-profile-photo", args=(source_profile.id,))
        ).status_code
        == 404
    )
    public_before = anonymous.get(
        reverse("api-public-attendee-list", args=(source_edition.id,))
    ).json()[0]
    assert public_before["profile_photo_url"] is None
    assert public_before["fursuits"][0]["photo_url"] is None
    assert set(public_before) == {
        "display_name",
        "pronouns",
        "bio",
        "spoken_languages",
        "profile_photo_url",
        "country_code",
        "attendance_labels",
        "fursuits",
    }
    assert public_before["country_code"] == "HU"
    assert public_before["attendance_labels"][0]["code"] == "super_sponsor"
    assert public_before["attendance_labels"][0]["label"] == "Super sponsor"

    moderator = AccountFactory()
    CapabilityGrantFactory(
        organization=source_edition.organization,
        edition=source_edition,
        principal=moderator,
        capability_code="registration.moderate_public_profile",
    )
    moderator_client = APIClient()
    moderator_client.force_authenticate(moderator)
    base = (
        f"/api/v1/organizations/{source_edition.organization_id}"
        f"/editions/{source_edition.id}/registration/profile-media-reviews"
    )
    unauthorized_queue = owner_client.get(base)
    assert unauthorized_queue.status_code == 403
    queue = moderator_client.get(base)
    assert queue.status_code == 200
    assert {item["media_kind"] for item in queue.json()} == {
        "profile_photo",
        "fursuit_photo",
    }
    for item in queue.json():
        reviewed = moderator_client.post(
            f"{base}/{item['id']}",
            {
                "media_kind": item["media_kind"],
                "decision": "approved",
                "reason": "Synthetic image is suitable for the public list.",
            },
            format="json",
        )
        assert reviewed.status_code == 200

    source_profile.refresh_from_db()
    source_fursuit.refresh_from_db()
    assert source_profile.profile_photo_status == MediaReviewStatus.APPROVED
    assert source_fursuit.photo_status == MediaReviewStatus.APPROVED

    assert (
        anonymous.get(
            reverse("protected-profile-photo", args=(source_profile.id,))
        ).status_code
        == 200
    )
    source_profile_name = source_profile.profile_photo.name
    source_fursuit_name = source_fursuit.photo.name

    suggestion = owner_client.get(
        reverse("api-self-profile-suggestion", args=(target_edition.id,))
    )
    assert suggestion.status_code == 200
    assert suggestion.json()["reuse_profile_photo_id"] == str(source_profile.id)
    submitted = owner_client.post(
        reverse("public-registration-form", args=(target_edition.id,)),
        data=_public_payload(
            target_product,
            reuse_profile_photo_id=str(source_profile.id),
            **{
                "fursuits-TOTAL_FORMS": "2",
                "fursuits-INITIAL_FORMS": "1",
                "fursuits-0-reuse_from_id": str(source_fursuit.id),
                "fursuits-0-keep_photo": "",
            },
        ),
    )
    assert submitted.status_code == 302
    target_profile = AttendeeRegistrationProfile.objects.get(edition=target_edition)
    target_fursuit = AttendeeFursuit.objects.get(profile=target_profile)
    assert target_profile.profile_photo_status == MediaReviewStatus.APPROVED
    assert target_profile.profile_photo.name == source_profile_name
    assert target_fursuit.photo_status == MediaReviewStatus.APPROVED
    assert target_fursuit.photo.name == source_fursuit_name

    removed = owner_client.post(
        reverse("edit-attendee-profile", args=(target_edition.id,)),
        data=_edit_payload(
            target_profile,
            remove_profile_photo="on",
            **{"fursuits-0-remove_photo": "on"},
        ),
    )
    assert removed.status_code == 302
    target_profile.refresh_from_db()
    target_fursuit.refresh_from_db()
    source_profile.refresh_from_db()
    source_fursuit.refresh_from_db()
    assert not target_profile.profile_photo
    assert target_profile.profile_photo_status == MediaReviewStatus.NONE
    assert not target_fursuit.photo
    assert target_fursuit.photo_status == MediaReviewStatus.NONE
    assert source_profile.profile_photo_status == MediaReviewStatus.APPROVED
    assert source_fursuit.photo_status == MediaReviewStatus.APPROVED

    EventEdition.objects.filter(id=source_edition.id).update(
        lifecycle=EventEdition.Lifecycle.CANCELLED,
        lifecycle_version=F("lifecycle_version") + 1,
        aggregate_version=F("aggregate_version") + 1,
    )
    assert moderator_client.get(base).status_code == 404
    historical_review = moderator_client.post(
        f"{base}/{source_profile.id}",
        {
            "media_kind": "profile_photo",
            "decision": "rejected",
            "reason": "Historical content should not be changed.",
        },
        format="json",
    )
    assert historical_review.status_code == 400


def test_cross_account_media_reuse_and_inactive_profile_edits_are_denied(
    tmp_path,
    settings,
) -> None:
    settings.MEDIA_ROOT = tmp_path
    edition, _configuration, product = _open_public_world()
    owner_client = Client()
    response = owner_client.post(
        reverse("public-registration-form", args=(edition.id,)),
        data=_public_payload(product),
    )
    assert response.status_code == 302
    profile = AttendeeRegistrationProfile.objects.get(edition=edition)
    profile.profile_photo = SimpleUploadedFile(
        "approved.png",
        b"approved",
        content_type="image/png",
    )
    profile.profile_photo_status = MediaReviewStatus.APPROVED
    profile.profile_photo_reviewed_by = AccountFactory()
    profile.profile_photo_reviewed_at = timezone.now()
    profile.profile_photo_review_note = "Approved synthetic image."
    profile.aggregate_version += 1
    profile.save()
    other_edition = EventEditionFactory(
        series=edition.series,
        starts_on=date(2031, 8, 1),
        ends_on=date(2031, 8, 4),
    )
    _, _, other_product = _open_public_world(edition=other_edition)
    attacker = AccountFactory()
    attacker_client = Client()
    attacker_client.force_login(attacker)
    denied = attacker_client.post(
        reverse("public-registration-form", args=(other_edition.id,)),
        data=_public_payload(
            other_product,
            reuse_profile_photo_id=str(profile.id),
        ),
    )
    assert denied.status_code == 200
    assert not Registration.objects.filter(
        edition=other_edition,
        account=attacker,
    ).exists()

    inactive_input = AttendeeProfileInput(
        real_name=profile.real_name,
        date_of_birth=profile.date_of_birth,
        address_line_1=profile.address_line_1,
        address_line_2=profile.address_line_2,
        locality=profile.locality,
        postal_code=profile.postal_code,
        region=profile.region,
        country_code=profile.country_code,
        emergency_contact_name=profile.emergency_contact_name,
        emergency_contact_phone=profile.emergency_contact_phone,
        phone_number=profile.phone_number,
        telegram_handle=profile.telegram_handle,
        pronoun_code=profile.pronoun_code,
        other_pronouns=profile.other_pronouns,
        bio=profile.bio,
        spoken_language_codes=tuple(profile.spoken_language_codes),
        profile_photo=None,
        reuse_profile_photo_id=None,
        keep_profile_photo=True,
        brings_fursuits=True,
        fursuits=tuple(
            AttendeeFursuitInput(
                fursuit_id=fursuit.id,
                name=fursuit.name,
                species=fursuit.species,
            )
            for fursuit in profile.fursuits.filter(is_active=True)
        ),
        directory_visible=profile.directory_visible,
    )
    with pytest.raises(ValidationError, match="no more than 10 fursuits"):
        update_attendee_profile(
            organization_id=profile.organization_id,
            edition_id=profile.edition_id,
            actor=profile.account,
            profile_input=replace(
                inactive_input,
                brings_fursuits=True,
                fursuits=tuple(
                    AttendeeFursuitInput(
                        name=f"Suit {index}",
                        species="Synthetic",
                    )
                    for index in range(11)
                ),
            ),
            correlation_id=uuid4(),
        )
    with pytest.raises(ValidationError, match="match the bring-fursuits"):
        update_attendee_profile(
            organization_id=profile.organization_id,
            edition_id=profile.edition_id,
            actor=profile.account,
            profile_input=replace(inactive_input, brings_fursuits=False),
            correlation_id=uuid4(),
        )
    profile.account.is_active = False
    profile.account.save(update_fields=("is_active",))
    with pytest.raises(ValidationError, match="Inactive accounts"):
        update_attendee_profile(
            organization_id=profile.organization_id,
            edition_id=profile.edition_id,
            actor=profile.account,
            profile_input=inactive_input,
            correlation_id=uuid4(),
        )


def test_fursuit_scope_and_retention_are_database_guarded() -> None:
    edition, _configuration, product = _open_public_world()
    client = Client()
    response = client.post(
        reverse("public-registration-form", args=(edition.id,)),
        data=_public_payload(product),
    )
    assert response.status_code == 302
    fursuit = AttendeeFursuit.objects.get(edition=edition)
    other_edition = EventEditionFactory()

    with transaction.atomic(), pytest.raises(IntegrityError):
        AttendeeFursuit.objects.filter(id=fursuit.id).update(
            organization_id=other_edition.organization_id,
            edition_id=other_edition.id,
        )
    with pytest.raises(ValidationError, match="deactivated"):
        fursuit.delete()
    with transaction.atomic(), pytest.raises(IntegrityError):
        AttendeeFursuit.objects.filter(id=fursuit.id).delete()


def test_self_profile_api_reads_updates_and_replaces_each_media_kind(
    tmp_path,
    settings,
) -> None:
    settings.MEDIA_ROOT = tmp_path
    edition, _configuration, product = _open_public_world()
    web_client = Client()
    response = web_client.post(
        reverse("public-registration-form", args=(edition.id,)),
        data=_public_payload(product),
    )
    assert response.status_code == 302
    profile = AttendeeRegistrationProfile.objects.get(edition=edition)
    fursuit = AttendeeFursuit.objects.get(profile=profile)
    api_client = APIClient()
    api_client.force_authenticate(profile.account)
    path = (
        f"/api/v1/organizations/{edition.organization_id}/editions/"
        f"{edition.id}/registration/me/profile"
    )

    read = api_client.get(path)
    assert read.status_code == 200
    assert read.json()["real_name"] == profile.real_name
    assert read.json()["directory_country_code"] == "HU"
    assert read.json()["fursuits"][0]["id"] == str(fursuit.id)

    update_payload = {
        key: read.json()[key]
        for key in (
            "real_name",
            "date_of_birth",
            "address_line_1",
            "address_line_2",
            "locality",
            "postal_code",
            "region",
            "country_code",
            "emergency_contact_name",
            "emergency_contact_phone",
            "phone_number",
            "telegram_handle",
            "pronoun_code",
            "other_pronouns",
            "bio",
            "spoken_language_codes",
            "brings_fursuits",
            "directory_visible",
            "directory_country_code",
        )
    }
    update_payload.update(
        {
            "address_line_1": "API Address 7",
            "bio": "Updated through the headless profile command.",
            "profile_photo_action": "keep",
            "fursuits": [
                {
                    "id": str(fursuit.id),
                    "name": "Moss API",
                    "species": fursuit.species,
                    "keep_photo": True,
                }
            ],
        }
    )
    updated = api_client.put(path, update_payload, format="json")
    assert updated.status_code == 200
    assert updated.json()["address_line_1"] == "API Address 7"
    assert updated.json()["fursuits"][0]["name"] == "Moss API"

    invalid_payload = {**update_payload, "pronoun_code": "made-up"}
    invalid = api_client.put(path, invalid_payload, format="json")
    assert invalid.status_code == 400
    profile.refresh_from_db()
    assert profile.pronoun_code != "made-up"

    profile_upload = api_client.post(
        f"{path}/photo",
        {
            "image": SimpleUploadedFile(
                "profile.webp",
                _valid_image_bytes("WEBP"),
                content_type="image/webp",
            )
        },
        format="multipart",
    )
    assert profile_upload.status_code == 200
    assert profile_upload.json()["profile_photo_review_status"] == "pending"

    fursuit_upload = api_client.post(
        f"{path}/fursuits/{fursuit.id}/photo",
        {
            "image": SimpleUploadedFile(
                "fursuit.webp",
                _valid_image_bytes("WEBP"),
                content_type="image/webp",
            )
        },
        format="multipart",
    )
    assert fursuit_upload.status_code == 200
    assert fursuit_upload.json()["fursuits"][0]["photo_review_status"] == ("pending")

    unknown_fursuit_upload = api_client.post(
        f"{path}/fursuits/{uuid4()}/photo",
        {
            "image": SimpleUploadedFile(
                "unknown.webp",
                _valid_image_bytes("WEBP"),
                content_type="image/webp",
            )
        },
        format="multipart",
    )
    assert unknown_fursuit_upload.status_code == 404


def test_profile_contract_rejects_invalid_media_review_inputs() -> None:
    edition, _configuration, product = _open_public_world()
    client = Client()
    response = client.post(
        reverse("public-registration-form", args=(edition.id,)),
        data=_public_payload(product),
    )
    assert response.status_code == 302
    profile = AttendeeRegistrationProfile.objects.get(edition=edition)
    fursuit = AttendeeFursuit.objects.get(profile=profile)
    moderator = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=moderator,
        capability_code="registration.moderate_public_profile",
    )
    common = {
        "organization_id": edition.organization_id,
        "edition_id": edition.id,
        "actor": moderator,
        "correlation_id": uuid4(),
    }

    with pytest.raises(ValidationError, match="approve or reject"):
        review_attendee_media(
            **common,
            media_kind="profile_photo",
            media_id=profile.id,
            decision="maybe",
            reason="A reason.",
        )
    with pytest.raises(ValidationError, match="requires a reason"):
        review_attendee_media(
            **common,
            media_kind="profile_photo",
            media_id=profile.id,
            decision="approved",
            reason=" ",
        )
    with pytest.raises(ValidationError, match="no profile image"):
        review_attendee_media(
            **common,
            media_kind="profile_photo",
            media_id=profile.id,
            decision="approved",
            reason="Synthetic review.",
        )
    with pytest.raises(ValidationError, match="no fursuit image"):
        review_attendee_media(
            **common,
            media_kind="fursuit_photo",
            media_id=fursuit.id,
            decision="approved",
            reason="Synthetic review.",
        )
    with pytest.raises(ValidationError, match="Unknown attendee media"):
        review_attendee_media(
            **common,
            media_kind="unknown",
            media_id=profile.id,
            decision="approved",
            reason="Synthetic review.",
        )

    AttendeeRegistrationProfile.objects.filter(id=profile.id).update(
        profile_photo="profiles/synthetic.png",
        profile_photo_status=MediaReviewStatus.NONE,
        aggregate_version=F("aggregate_version") + 1,
    )
    with pytest.raises(ValidationError, match="no attendee image"):
        review_attendee_media(
            **common,
            media_kind="profile_photo",
            media_id=profile.id,
            decision="approved",
            reason="Synthetic review.",
        )
