from uuid import uuid4

import pytest

from maru.organizations.serializers import (
    ConventionSeriesListQuerySerializer,
    ConventionSeriesUpdateSerializer,
)


def _payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Synthetic Series",
        "description": "",
        "website_url": "",
        "contact_email": "",
        "is_active": True,
        "expected_profile_version": 1,
    }
    payload.update(changes)
    return payload


@pytest.mark.parametrize(
    ("website_url", "expected"),
    [
        ("series.example.invalid", "https://series.example.invalid"),
        ("//series.example.invalid", "https://series.example.invalid"),
        ("http://series.example.invalid", "http://series.example.invalid"),
        ("https://series.example.invalid", "https://series.example.invalid"),
        ("", ""),
    ],
)
def test_update_serializer_matches_form_url_normalization(
    website_url: str,
    expected: str,
) -> None:
    serializer = ConventionSeriesUpdateSerializer(
        data=_payload(
            name="  Synthetic    Convention  ",
            description="  A bounded description.  ",
            contact_email="  hello@example.invalid  ",
            website_url=website_url,
        )
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["name"] == "Synthetic Convention"
    assert serializer.validated_data["description"] == "A bounded description."
    assert serializer.validated_data["contact_email"] == "hello@example.invalid"
    assert serializer.validated_data["website_url"] == expected


def test_update_serializer_accepts_exact_text_boundaries() -> None:
    serializer = ConventionSeriesUpdateSerializer(
        data=_payload(name="n" * 160, description="d" * 2000)
    )

    assert serializer.is_valid(), serializer.errors


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("name", "n" * 161),
        ("description", "d" * 2001),
        ("website_url", "not a valid host"),
        ("contact_email", "invalid"),
        ("expected_profile_version", 0),
    ],
)
def test_update_serializer_rejects_invalid_bounded_values(
    field_name: str,
    value: object,
) -> None:
    serializer = ConventionSeriesUpdateSerializer(data=_payload(**{field_name: value}))

    assert not serializer.is_valid()
    assert field_name in serializer.errors


def test_strict_serializers_reject_undeclared_fields() -> None:
    update = ConventionSeriesUpdateSerializer(
        data=_payload(
            id=str(uuid4()),
            organization=str(uuid4()),
            organization_id=str(uuid4()),
            series_id=str(uuid4()),
            slug="cannot-change",
            profile_version=2,
            aggregate_version=2,
            version=2,
        )
    )
    query = ConventionSeriesListQuerySerializer(
        data={"page": 1, "search": "silently ignored otherwise"}
    )

    assert not update.is_valid()
    assert set(update.errors) == {
        "aggregate_version",
        "id",
        "organization",
        "organization_id",
        "profile_version",
        "series_id",
        "slug",
        "version",
    }
    assert not query.is_valid()
    assert set(query.errors) == {"search"}
