from datetime import timedelta
from uuid import uuid4

import pytest
from django.core import mail
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from maru.registration.models import (
    AdmissionProduct,
    ConfigurationStatus,
    Registration,
    RegistrationQuestion,
)
from maru.registration.profile_policy import (
    COLLECTION_NOTICE_VERSION,
    DIRECTORY_CONSENT_VERSION,
)
from tests.factories import (
    AccountFactory,
    EventEditionFactory,
    RegistrationConfigurationFactory,
)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


def _world():
    now = timezone.now()
    edition = EventEditionFactory()
    configuration = RegistrationConfigurationFactory(
        edition=edition,
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=30),
    )
    RegistrationQuestion.objects.create(
        configuration=configuration,
        key="accessibility",
        label="Accessibility notes",
        field_type="long_text",
        required=False,
        position=10,
        purpose="Prepare requested attendee support.",
    )
    product = AdmissionProduct.objects.create(
        configuration=configuration,
        code="weekend",
        name="Weekend admission",
        description="Synthetic headless product.",
        price_minor=12_500,
        capacity=50,
        position=10,
        entitlement_code="admission",
        entitlement_name="Weekend admission",
    )
    configuration.status = ConfigurationStatus.ACTIVE
    configuration.review_required = False
    configuration.review_note = "Reviewed."
    configuration.activated_at = now
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


def _payload(configuration, product):
    return {
        "idempotency_key": str(uuid4()),
        "configuration_version": configuration.version,
        "product_id": str(product.id),
        "answers": {"accessibility": "Quiet queue if possible."},
        "profile": {
            "real_name": "Headless Attendee",
            "date_of_birth": "1990-01-01",
            "address_line_1": "1 API Street",
            "address_line_2": "",
            "locality": "Client City",
            "postal_code": "1000",
            "region": "Client Region",
            "country_code": "HU",
            "emergency_contact_name": "Emergency Person",
            "emergency_contact_phone": "+361234567",
            "phone_number": "+361234568",
            "telegram_handle": "headless_user",
            "pronoun_code": "they_them",
            "other_pronouns": "",
            "bio": "A frontend-independent attendee.",
            "spoken_language_codes": ["en", "hu"],
            "brings_fursuits": False,
            "directory_visible": True,
            "directory_country_code": "HU",
        },
        "collection_notice_version": COLLECTION_NOTICE_VERSION,
        "directory_consent_version": DIRECTORY_CONSENT_VERSION,
    }


def test_headless_definition_submission_idempotency_and_self_profile() -> None:
    edition, configuration, product = _world()
    account = AccountFactory()
    client = APIClient()
    client.force_authenticate(account)
    definition = client.get(f"/api/v1/public/editions/{edition.id}/registration")
    assert definition.status_code == 200
    assert definition.data["client_contract"]["submission_api"]
    assert (
        "explicitly approved"
        in (definition.data["client_contract"]["browser_origin_policy"])
    )
    assert definition.data["profile_contract"]["spoken_language_limit"] == 5
    assert (
        definition.data["profile_contract"]["public_attendee_country_is_optional"]
        is True
    )
    assert (
        definition.data["profile_contract"]["public_attendee_labels_are_authoritative"]
        is True
    )
    payload = _payload(configuration, product)
    submitted = client.post(
        f"/api/v1/public/editions/{edition.id}/registration/submissions",
        payload,
        format="json",
    )
    assert submitted.status_code == 201
    assert submitted.data["replayed"] is False
    assert submitted.data["registration"]["amount_minor"] == 12_500
    assert submitted.data["profile"]["directory_visible"] is True
    assert submitted.data["profile"]["directory_country_code"] == "HU"
    repeated = client.post(
        f"/api/v1/public/editions/{edition.id}/registration/submissions",
        payload,
        format="json",
    )
    assert repeated.status_code == 200
    assert repeated.data["replayed"] is True
    assert Registration.objects.filter(account=account, edition=edition).count() == 1

    profile = client.get(
        f"/api/v1/organizations/{edition.organization_id}/editions/"
        f"{edition.id}/registration/me/profile"
    )
    assert profile.status_code == 200
    assert profile.data["bio"] == "A frontend-independent attendee."

    conflicting = dict(payload)
    conflicting["answers"] = {"accessibility": "Different request."}
    conflict = client.post(
        f"/api/v1/public/editions/{edition.id}/registration/submissions",
        conflicting,
        format="json",
    )
    assert conflict.status_code == 400
    assert conflict.data["code"] == "registration_idempotency_conflict"


def test_headless_rejects_stale_notices_and_invalid_conditional_profile() -> None:
    edition, configuration, product = _world()
    client = APIClient()
    client.force_authenticate(AccountFactory())
    payload = _payload(configuration, product)
    payload["configuration_version"] = 999
    stale = client.post(
        f"/api/v1/public/editions/{edition.id}/registration/submissions",
        payload,
        format="json",
    )
    assert stale.status_code == 400
    payload = _payload(configuration, product)
    payload["collection_notice_version"] = "obsolete"
    notice = client.post(
        f"/api/v1/public/editions/{edition.id}/registration/submissions",
        payload,
        format="json",
    )
    assert notice.status_code == 400
    payload = _payload(configuration, product)
    payload["profile"]["pronoun_code"] = "other"
    payload["profile"]["other_pronouns"] = ""
    invalid = client.post(
        f"/api/v1/public/editions/{edition.id}/registration/submissions",
        payload,
        format="json",
    )
    assert invalid.status_code == 400


@override_settings(ALLOW_PROVISIONAL_PUBLIC_REGISTRATION=False)
def test_reference_client_uses_verified_account_gate() -> None:
    edition, _configuration, _product = _world()
    client = APIClient()
    gate = client.get(f"/register/{edition.id}/")
    assert gate.status_code == 200
    assert b"Verify your email first" in gate.content
    posted = client.post(
        f"/register/{edition.id}/",
        {
            "email": "reference-new@example.invalid",
            "display_name": "Reference New",
            "password1": "Reference-password-482!",
            "password2": "Reference-password-482!",
        },
    )
    assert posted.status_code == 200
    assert b"Check your email" in posted.content
    assert len(mail.outbox) == 1

    account = AccountFactory(email_verified_at=None)
    client.force_login(account)
    signed_in_gate = client.get(f"/register/{edition.id}/")
    assert b"waiting for email verification" in signed_in_gate.content
    resent = client.post(f"/register/{edition.id}/")
    assert resent.status_code == 200
    assert b"Check your email" in resent.content
