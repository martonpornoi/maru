from datetime import date
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from maru.registration.profile_choices import (
    LANGUAGE_CHOICES,
    MAX_SPOKEN_LANGUAGES,
    language_labels,
    pronoun_display,
    validate_spoken_language_codes,
)
from maru.registration.profile_policy import MAX_FURSUIT_PHOTO_BYTES
from maru.registration.serializers import (
    SelfProfileImageUploadSerializer,
    UpdateSelfAttendeeProfileSerializer,
)


def _profile_payload() -> dict[str, object]:
    return {
        "real_name": "Synthetic Attendee",
        "date_of_birth": date(1995, 5, 20),
        "address_line_1": "Example Street 1",
        "address_line_2": "",
        "locality": "Example City",
        "postal_code": "1234",
        "region": "Example Region",
        "country_code": "HU",
        "emergency_contact_name": "Synthetic Contact",
        "emergency_contact_phone": "+36 30 555 0101",
        "phone_number": "+36 30 555 0102",
        "telegram_handle": "@synthetic_user",
        "pronoun_code": "they_them",
        "other_pronouns": "must be cleared",
        "bio": "Synthetic profile.",
        "spoken_language_codes": ["en", "hu"],
        "brings_fursuits": False,
        "profile_photo_action": "keep",
        "fursuits": [],
        "directory_visible": False,
    }


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("en", "must be a list"),
        (["en", 3], "must be a list"),
        (
            ["en", "hu", "de", "fr", "es", "it"],
            f"no more than {MAX_SPOKEN_LANGUAGES}",
        ),
        (["en", "EN"], "must be unique"),
        (["zz"], "Unknown spoken language"),
    ],
)
def test_spoken_language_validator_rejects_invalid_contracts(
    value: object,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        validate_spoken_language_codes(value)


def test_profile_choice_helpers_are_bounded_and_tolerant() -> None:
    validate_spoken_language_codes(["EN", "hu"])
    assert pronoun_display("other", "  xe/xem  ") == "xe/xem"
    assert pronoun_display("unknown") == ""
    assert language_labels(["en", "zz", "hu"]) == ["English", "Hungarian"]
    assert len(LANGUAGE_CHOICES) > 180


@pytest.mark.parametrize(
    "changes",
    [
        {"profile_photo_action": "reuse"},
        {
            "profile_photo_action": "keep",
            "reuse_profile_photo_id": str(uuid4()),
        },
        {"brings_fursuits": True, "fursuits": []},
        {"pronoun_code": "other", "other_pronouns": ""},
        {
            "brings_fursuits": True,
            "fursuits": [
                {"name": f"Suit {index}", "keep_photo": True} for index in range(11)
            ],
        },
    ],
)
def test_self_profile_serializer_rejects_cross_field_mismatches(
    changes: dict[str, object],
) -> None:
    serializer = UpdateSelfAttendeeProfileSerializer(
        data={**_profile_payload(), **changes}
    )
    assert not serializer.is_valid()


def test_self_profile_serializer_normalizes_non_other_pronouns() -> None:
    serializer = UpdateSelfAttendeeProfileSerializer(data=_profile_payload())
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["other_pronouns"] == ""


def test_profile_image_upload_serializer_enforces_size_and_type() -> None:
    wrong_type = SelfProfileImageUploadSerializer(
        data={
            "image": SimpleUploadedFile(
                "profile.pdf",
                b"not-an-image",
                content_type="application/pdf",
            )
        }
    )
    assert not wrong_type.is_valid()

    too_large = SelfProfileImageUploadSerializer(
        data={
            "image": SimpleUploadedFile(
                "profile.png",
                b"x" * (MAX_FURSUIT_PHOTO_BYTES + 1),
                content_type="image/png",
            )
        }
    )
    assert not too_large.is_valid()

    valid = SelfProfileImageUploadSerializer(
        data={
            "image": SimpleUploadedFile(
                "profile.webp",
                b"synthetic-webp",
                content_type="image/webp",
            )
        }
    )
    assert valid.is_valid(), valid.errors
