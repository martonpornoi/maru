"""Authorized edition API projections."""

from typing import TYPE_CHECKING, cast
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from maru.core.validators import (
    validate_currency_codes,
    validate_language_codes,
    validate_time_zone,
)
from maru.events.adoption import ADOPTION_PROFILE_CHOICES, AdoptionProfileCode
from maru.events.models import (
    MAX_EDITION_SPAN_DAYS,
    EditionClosureManifest,
    EditionReadinessGate,
    EventEdition,
)

if TYPE_CHECKING:
    from datetime import date

MAX_AUTOCOMPLETE_RESULTS = 20
MAX_BULK_EDITION_TRANSITIONS = 25


def _django_validation_code(
    error: DjangoValidationError,
    *,
    fallback: str,
) -> str:
    if hasattr(error, "error_list") and error.error_list:
        return str(error.error_list[0].code or fallback)
    return fallback


class EditionBasicSerializer(serializers.ModelSerializer[EventEdition]):
    """Serialize and validate edition basic data."""

    class Meta:
        """Configure Django's declarative class metadata."""

        model = EventEdition
        fields = (
            "id",
            "organization_id",
            "series_id",
            "slug",
            "name",
            "lifecycle",
            "aggregate_version",
            "adoption_profile_code",
            "adoption_profile_version",
            "time_zone",
            "language_codes",
            "currency_codes",
            "starts_on",
            "ends_on",
        )
        read_only_fields = fields


class EditionProblemSerializer(serializers.Serializer[dict[str, object]]):
    """RFC 9457 response shape used by edition management endpoints."""

    type = serializers.URLField(read_only=True)
    title = serializers.CharField(read_only=True)
    status = serializers.IntegerField(read_only=True)
    detail = serializers.CharField(read_only=True)
    code = serializers.CharField(read_only=True)
    request_id = serializers.UUIDField(required=False)
    errors = serializers.JSONField(  # type: ignore[assignment]
        required=False,
    )


class EditionDetailsRequestSerializer(serializers.Serializer[dict[str, object]]):
    """Complete bounded edition-profile input shared by create and update."""

    name = serializers.CharField(max_length=160, trim_whitespace=True)
    starts_on = serializers.DateField()
    ends_on = serializers.DateField()
    time_zone = serializers.CharField(max_length=63, trim_whitespace=True)
    language_codes = serializers.ListField(
        child=serializers.CharField(max_length=35, trim_whitespace=True),
        min_length=1,
        max_length=16,
    )
    currency_codes = serializers.ListField(
        child=serializers.CharField(max_length=3, trim_whitespace=True),
        min_length=1,
        max_length=8,
    )

    def validate_time_zone(self, value: str) -> str:
        """Validate time zone.

        Parameters
        ----------
        value : str
            The untrusted input to normalize, validate, or compare.

        Returns
        -------
        str
            The normalized text for validate time zone.

        Raises
        ------
        serializers.ValidationError
            If the submitted state or input violates a domain invariant.
        """
        try:
            validate_time_zone(value)
        except DjangoValidationError as error:
            raise serializers.ValidationError(
                error.messages,
                code=_django_validation_code(
                    error,
                    fallback="invalid_time_zone",
                ),
            ) from error
        return value

    def validate_language_codes(self, value: list[str]) -> list[str]:
        """Validate language codes.

        Parameters
        ----------
        value : list[str]
            The untrusted input to normalize, validate, or compare.

        Returns
        -------
        list[str]
            The matching validate language codes records in deterministic order.

        Raises
        ------
        serializers.ValidationError
            If the submitted state or input violates a domain invariant.
        """
        normalized = [code.lower() for code in value]
        try:
            validate_language_codes(normalized)
        except DjangoValidationError as error:
            raise serializers.ValidationError(
                error.messages,
                code=_django_validation_code(
                    error,
                    fallback="invalid_language",
                ),
            ) from error
        return normalized

    def validate_currency_codes(self, value: list[str]) -> list[str]:
        """Validate currency codes.

        Parameters
        ----------
        value : list[str]
            The untrusted input to normalize, validate, or compare.

        Returns
        -------
        list[str]
            The matching validate currency codes records in deterministic order.

        Raises
        ------
        serializers.ValidationError
            If the submitted state or input violates a domain invariant.
        """
        normalized = [code.upper() for code in value]
        try:
            validate_currency_codes(normalized)
        except DjangoValidationError as error:
            raise serializers.ValidationError(
                error.messages,
                code=_django_validation_code(
                    error,
                    fallback="invalid_currency",
                ),
            ) from error
        return normalized

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        """Validate the supplied data.

        Parameters
        ----------
        attrs : dict[str, object]
            The attrs mapping to validate or transform.

        Returns
        -------
        dict[str, object]
            A mapping containing the resolved validate data.

        Raises
        ------
        serializers.ValidationError
            If the submitted state or input violates a domain invariant.
        """
        starts_on = cast("date", attrs["starts_on"])
        ends_on = cast("date", attrs["ends_on"])
        if ends_on < starts_on:
            raise serializers.ValidationError(
                {"ends_on": "The end date cannot be before the start date."},
                code="edition_end_before_start",
            )
        if (ends_on - starts_on).days > MAX_EDITION_SPAN_DAYS:
            raise serializers.ValidationError(
                {
                    "ends_on": (
                        "An edition date range cannot exceed "
                        f"{MAX_EDITION_SPAN_DAYS} days."
                    )
                },
                code="edition_date_range_too_long",
            )
        return attrs


class EditionCreateRequestSerializer(EditionDetailsRequestSerializer):
    """Serialize and validate edition create request data."""

    series_id = serializers.UUIDField()
    adoption_profile_code = serializers.ChoiceField(
        choices=ADOPTION_PROFILE_CHOICES,
        default=AdoptionProfileCode.FULL_CONVENTION,
    )


class EditionUpdateRequestSerializer(EditionDetailsRequestSerializer):
    """Serialize and validate edition update request data."""

    expected_aggregate_version = serializers.IntegerField(min_value=1)


class EditionListQuerySerializer(serializers.Serializer[dict[str, str]]):
    """Serialize and validate edition list query data."""

    lifecycle = serializers.ChoiceField(
        choices=EventEdition.Lifecycle.choices,
        required=False,
    )
    search = serializers.CharField(
        required=False,
        allow_blank=False,
        trim_whitespace=True,
        max_length=100,
    )
    page = serializers.IntegerField(required=False, min_value=1)
    page_size = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=100,
    )


class EditionAutocompleteSerializer(serializers.ModelSerializer[EventEdition]):
    """Serialize and validate edition autocomplete data."""

    class Meta:
        """Configure Django's declarative class metadata."""

        model = EventEdition
        fields = ("id", "name", "lifecycle", "starts_on")
        read_only_fields = fields


class EditionAutocompleteQuerySerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate edition autocomplete query data."""

    search = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
        min_length=1,
        max_length=100,
    )
    limit = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=MAX_AUTOCOMPLETE_RESULTS,
        default=10,
    )


class EditionAutocompleteResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate edition autocomplete response data."""

    results = EditionAutocompleteSerializer(many=True, read_only=True)


class EditionTransitionRequestSerializer(serializers.Serializer[dict[str, str]]):
    """Serialize and validate edition transition request data."""

    to_state = serializers.ChoiceField(choices=EventEdition.Lifecycle.choices)
    reason = serializers.CharField(
        max_length=500,
        allow_blank=False,
        trim_whitespace=True,
    )


class EditionTransitionResultSerializer(serializers.ModelSerializer[EventEdition]):
    """Serialize and validate edition transition result data."""

    class Meta:
        """Configure Django's declarative class metadata."""

        model = EventEdition
        fields = ("id", "lifecycle", "lifecycle_version")
        read_only_fields = fields


class EditionBulkTransitionRequestSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate edition bulk transition request data."""

    edition_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=MAX_BULK_EDITION_TRANSITIONS,
    )
    to_state = serializers.ChoiceField(choices=EventEdition.Lifecycle.choices)
    reason = serializers.CharField(
        max_length=500,
        allow_blank=False,
        trim_whitespace=True,
    )

    def validate_edition_ids(self, value: list[UUID]) -> list[UUID]:
        """Validate edition identifiers.

        Parameters
        ----------
        value : list[UUID]
            The untrusted input to normalize, validate, or compare.

        Returns
        -------
        list[UUID]
            The matching validate edition ids records in deterministic order.

        Raises
        ------
        serializers.ValidationError
            If the submitted state or input violates a domain invariant.
        """
        if len(value) != len(set(value)):
            raise serializers.ValidationError(
                "Edition identifiers must be unique.",
                code="duplicate_target",
            )
        return value


class EditionBulkTransitionResponseSerializer(
    serializers.Serializer[dict[str, object]]
):
    """Serialize and validate edition bulk transition response data."""

    results = EditionTransitionResultSerializer(many=True, read_only=True)


class EditionReadinessGateSerializer(serializers.ModelSerializer[EditionReadinessGate]):
    """Serialize and validate edition readiness gate data."""

    class Meta:
        """Configure Django's declarative class metadata."""

        model = EditionReadinessGate
        fields = (
            "id",
            "code",
            "status",
            "evidence_reference",
            "review_summary",
            "reviewed_at",
        )
        read_only_fields = fields


class EditionReadinessGateReviewSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate edition readiness gate review data."""

    approve = serializers.BooleanField()
    evidence_reference = serializers.CharField(max_length=240)
    summary = serializers.CharField(max_length=500)


class EditionClosureManifestCreateSerializer(serializers.Serializer[dict[str, str]]):
    """Serialize and validate edition closure manifest create data."""

    recovery_reference = serializers.CharField(max_length=240)


class EditionClosureManifestSerializer(
    serializers.ModelSerializer[EditionClosureManifest]
):
    """Serialize and validate edition closure manifest data."""

    class Meta:
        """Configure Django's declarative class metadata."""

        model = EditionClosureManifest
        fields = (
            "id",
            "generated_at",
            "counts",
            "manifest_digest",
            "recovery_reference",
        )
        read_only_fields = fields
