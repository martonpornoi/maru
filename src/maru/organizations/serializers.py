"""Bounded API projections for organization-owned convention series."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from maru.core.serializers import StrictInputSerializer
from maru.organizations.models import ConventionSeries
from maru.organizations.services import (
    MAX_SERIES_DESCRIPTION_LENGTH,
    MAX_SERIES_NAME_LENGTH,
)


class ConventionSeriesReadSerializer(serializers.ModelSerializer[ConventionSeries]):
    """Stable identity and complete editable profile for one series."""

    class Meta:
        """Configure Django's declarative class metadata."""

        model = ConventionSeries
        fields = (
            "id",
            "organization_id",
            "slug",
            "name",
            "description",
            "website_url",
            "contact_email",
            "is_active",
            "profile_version",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class ConventionSeriesProblemSerializer(serializers.Serializer[dict[str, object]]):
    """RFC 9457 response shape used at this API boundary."""

    type = serializers.URLField(read_only=True)
    title = serializers.CharField(read_only=True)
    status = serializers.IntegerField(read_only=True)
    detail = serializers.CharField(read_only=True)
    code = serializers.CharField(read_only=True)
    request_id = serializers.UUIDField(required=False)
    errors = serializers.JSONField(  # type: ignore[assignment]
        required=False,
    )


class HttpsAssumingURLField(serializers.URLField):
    """Match the HTML form's convenient, deterministic HTTPS assumption."""

    def to_internal_value(self, data: Any) -> str:
        """Parse and validate API input.

        Parameters
        ----------
        data : Any
            The untrusted input payload to validate or transform.

        Returns
        -------
        str
            The canonical value accepted by the serializer.
        """
        if isinstance(data, str):
            value = data.strip()
            if value:
                scheme, separator, _remainder = value.partition(":")
                if (
                    not separator
                    or not scheme
                    or not scheme[0].isascii()
                    or not scheme[0].isalpha()
                    or "/" in scheme
                ):
                    value = (
                        f"https:{value}"
                        if value.startswith("//")
                        else f"https://{value}"
                    )
            data = value
        return super().to_internal_value(data)


class ConventionSeriesUpdateSerializer(StrictInputSerializer):
    """Complete, strict convention-series profile replacement input."""

    name = serializers.CharField(
        max_length=MAX_SERIES_NAME_LENGTH,
        allow_blank=False,
        trim_whitespace=True,
    )
    description = serializers.CharField(
        max_length=MAX_SERIES_DESCRIPTION_LENGTH,
        allow_blank=True,
        trim_whitespace=True,
    )
    website_url = HttpsAssumingURLField(
        max_length=200,
        allow_blank=True,
    )
    contact_email = serializers.EmailField(
        max_length=254,
        allow_blank=True,
        trim_whitespace=True,
    )
    is_active = serializers.BooleanField()
    expected_profile_version = serializers.IntegerField(min_value=1)

    def validate_name(self, value: str) -> str:
        """Validate name.

        Parameters
        ----------
        value : str
            The untrusted input to normalize, validate, or compare.

        Returns
        -------
        str
            The normalized text for validate name.
        """
        return " ".join(value.split())


class ConventionSeriesListQuerySerializer(StrictInputSerializer):
    """Serialize and validate convention series list query data."""

    page = serializers.IntegerField(required=False, min_value=1)
    page_size = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=100,
    )
