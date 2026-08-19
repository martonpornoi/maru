"""Closed API schemas for venue catalogs and edition scheduling."""

from typing import TYPE_CHECKING, Any, cast

from drf_spectacular.extensions import OpenApiSerializerExtension
from rest_framework import serializers

from maru.core.serializers import StrictInputSerializer

from .models import (
    VenueBooking,
    VenueLayoutVersion,
    VenueProperty,
    VenuePropertyMedia,
    VenueSpace,
)

if TYPE_CHECKING:
    from drf_spectacular.openapi import AutoSchema
    from drf_spectacular.utils import Direction


class _VenueClosedInputSerializer(StrictInputSerializer):
    """Marker for Venue request objects that reject unknown properties."""


class _VenueClosedInputSchema(OpenApiSerializerExtension):
    """Expose the runtime closed-object contract in generated OpenAPI."""

    target_class = "maru.venues.serializers._VenueClosedInputSerializer"
    match_subclasses = True

    def map_serializer(
        self,
        auto_schema: "AutoSchema",
        direction: "Direction",
    ) -> dict[str, Any]:
        schema = auto_schema._map_serializer(  # type: ignore[no-untyped-call]
            self.target,
            direction,
            bypass_extensions=True,
        )
        schema["additionalProperties"] = False
        return cast("dict[str, Any]", schema)


class VenueCommandResultSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate venue command result data."""

    object_id = serializers.UUIDField()
    receipt_id = serializers.UUIDField()
    resulting_version = serializers.IntegerField(min_value=1)
    replayed = serializers.BooleanField()


class VenuePropertyCreateSerializer(_VenueClosedInputSerializer):
    """Serialize and validate venue property create data."""

    slug = serializers.SlugField(max_length=80)
    kind = serializers.ChoiceField(choices=VenueProperty.Kind.choices)
    legal_name = serializers.CharField(max_length=240)
    public_name = serializers.CharField(max_length=200)
    provider_name = serializers.CharField(
        max_length=240, allow_blank=True, required=False
    )
    public_description = serializers.CharField(
        max_length=5_000, allow_blank=True, required=False
    )
    internal_notes = serializers.CharField(
        max_length=5_000, allow_blank=True, required=False
    )
    location_name = serializers.CharField(max_length=240)
    postal_address = serializers.CharField(max_length=1_000)
    country_code = serializers.CharField(max_length=2)
    website_url = serializers.URLField(allow_blank=True, required=False)
    public_contact = serializers.CharField(
        max_length=240, allow_blank=True, required=False
    )
    contact_name = serializers.CharField(
        max_length=240, allow_blank=True, required=False
    )
    contact_email = serializers.EmailField(allow_blank=True, required=False)
    contact_phone = serializers.CharField(
        max_length=16, allow_blank=True, required=False
    )
    reason = serializers.CharField(max_length=1_000)


class VenuePropertyUpdateSerializer(_VenueClosedInputSerializer):
    """Serialize and validate venue property update data."""

    expected_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=1_000)
    legal_name = serializers.CharField(max_length=240, required=False)
    public_name = serializers.CharField(max_length=200, required=False)
    provider_name = serializers.CharField(
        max_length=240, allow_blank=True, required=False
    )
    public_description = serializers.CharField(
        max_length=5_000, allow_blank=True, required=False
    )
    internal_notes = serializers.CharField(
        max_length=5_000, allow_blank=True, required=False
    )
    location_name = serializers.CharField(max_length=240, required=False)
    postal_address = serializers.CharField(max_length=1_000, required=False)
    country_code = serializers.CharField(max_length=2, required=False)
    website_url = serializers.URLField(allow_blank=True, required=False)
    public_contact = serializers.CharField(
        max_length=240, allow_blank=True, required=False
    )
    contact_name = serializers.CharField(
        max_length=240, allow_blank=True, required=False
    )
    contact_email = serializers.EmailField(allow_blank=True, required=False)
    contact_phone = serializers.CharField(
        max_length=16, allow_blank=True, required=False
    )
    lifecycle = serializers.ChoiceField(
        choices=VenueProperty.Lifecycle.choices,
        required=False,
    )

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
        if set(attrs) <= {"expected_version", "reason"}:
            raise serializers.ValidationError(
                {"changes": ["Change at least one supported field."]}
            )
        return attrs


class VenueSpaceCatalogCreateSerializer(_VenueClosedInputSerializer):
    """Serialize and validate venue space catalog create data."""

    site_code = serializers.SlugField(max_length=80)
    site_name = serializers.CharField(max_length=200)
    building_code = serializers.SlugField(max_length=80)
    building_name = serializers.CharField(max_length=200)
    space_code = serializers.SlugField(max_length=80)
    space_name = serializers.CharField(max_length=200)
    space_kind = serializers.ChoiceField(choices=VenueSpace.Kind.choices)
    configuration_code = serializers.SlugField(max_length=80)
    configuration_name = serializers.CharField(max_length=200)
    seated_capacity = serializers.IntegerField(min_value=0)
    standing_capacity = serializers.IntegerField(min_value=0)
    table_capacity = serializers.IntegerField(min_value=0)
    fire_capacity = serializers.IntegerField(min_value=1)
    public_description = serializers.CharField(
        max_length=2_000, allow_blank=True, required=False
    )
    accessibility_features = serializers.CharField(
        max_length=2_000, allow_blank=True, required=False
    )
    known_barriers = serializers.CharField(
        max_length=2_000, allow_blank=True, required=False
    )
    equipment_facts = serializers.CharField(
        max_length=2_000, allow_blank=True, required=False
    )
    reason = serializers.CharField(max_length=1_000)


class VenueCombinationCreateSerializer(_VenueClosedInputSerializer):
    """Serialize and validate venue combination create data."""

    code = serializers.SlugField(max_length=80)
    name = serializers.CharField(max_length=200)
    member_space_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=2,
        max_length=32,
    )
    reason = serializers.CharField(max_length=1_000)


class VenueMediaAddSerializer(_VenueClosedInputSerializer):
    """Serialize and validate venue media add data."""

    kind = serializers.ChoiceField(choices=VenuePropertyMedia.Kind.choices)
    source_reference = serializers.CharField(max_length=1_000)
    owner_name = serializers.CharField(max_length=240)
    license_basis = serializers.CharField(max_length=500)
    usage_scope = serializers.CharField(max_length=500)
    attribution = serializers.CharField(
        max_length=500, allow_blank=True, required=False
    )
    expires_at = serializers.DateTimeField(allow_null=True, required=False)
    reason = serializers.CharField(max_length=1_000)


class VenueMediaApproveSerializer(_VenueClosedInputSerializer):
    """Serialize and validate venue media approve data."""

    expected_version = serializers.IntegerField(min_value=1)
    public_reference = serializers.CharField(max_length=1_000)
    reason = serializers.CharField(max_length=1_000)


class VenueLayoutApproveSerializer(_VenueClosedInputSerializer):
    """Serialize and validate venue layout approve data."""

    expected_version = serializers.IntegerField(min_value=1)
    approved_reference = serializers.CharField(
        max_length=1_000,
        allow_blank=True,
        required=False,
        help_text="Required by the service when approving a public layout.",
    )
    reason = serializers.CharField(max_length=1_000)


class VenueLayoutAddSerializer(_VenueClosedInputSerializer):
    """Serialize and validate venue layout add data."""

    layout_code = serializers.SlugField(max_length=80)
    version = serializers.IntegerField(min_value=1)
    title = serializers.CharField(max_length=200)
    visibility = serializers.ChoiceField(choices=VenueLayoutVersion.Visibility.choices)
    source_reference = serializers.CharField(max_length=1_000)
    checksum_sha256 = serializers.RegexField(r"[0-9a-fA-F]{64}")
    notes = serializers.CharField(max_length=2_000, allow_blank=True, required=False)
    reason = serializers.CharField(max_length=1_000)


class VenueRoomTypeCreateSerializer(_VenueClosedInputSerializer):
    """Serialize and validate venue room type create data."""

    code = serializers.SlugField(max_length=80)
    public_name = serializers.CharField(max_length=200)
    description = serializers.CharField(
        max_length=2_000, allow_blank=True, required=False
    )
    accessible_features = serializers.CharField(
        max_length=2_000, allow_blank=True, required=False
    )
    minimum_occupants = serializers.IntegerField(min_value=1)
    maximum_occupants = serializers.IntegerField(min_value=1)
    provider_reference = serializers.CharField(
        max_length=240, allow_blank=True, required=False
    )
    reason = serializers.CharField(max_length=1_000)


class VenueNightInventorySetSerializer(_VenueClosedInputSerializer):
    """Serialize and validate venue night inventory set data."""

    night = serializers.DateField()
    room_capacity = serializers.IntegerField(min_value=0)
    release_at = serializers.DateTimeField()
    provider_reference = serializers.CharField(
        max_length=240, allow_blank=True, required=False
    )
    expected_version = serializers.IntegerField(
        min_value=1, allow_null=True, required=False
    )
    reason = serializers.CharField(max_length=1_000)


class VenueSelectionCreateSerializer(_VenueClosedInputSerializer):
    """Serialize and validate venue selection create data."""

    property_id = serializers.UUIDField()
    responsible_department_id = serializers.UUIDField()
    local_name = serializers.CharField(max_length=200)
    public_description_override = serializers.CharField(
        max_length=2_000, allow_blank=True, required=False
    )
    public_contact_override = serializers.CharField(
        max_length=240, allow_blank=True, required=False
    )
    opening_restrictions = serializers.CharField(
        max_length=2_000, allow_blank=True, required=False
    )
    reason = serializers.CharField(max_length=1_000)


class VenueCapacitySerializer(_VenueClosedInputSerializer):
    """Serialize and validate venue capacity data."""

    configuration_name = serializers.CharField(max_length=200)
    seated_capacity = serializers.IntegerField(min_value=0)
    standing_capacity = serializers.IntegerField(min_value=0)
    table_capacity = serializers.IntegerField(min_value=0)
    fire_capacity = serializers.IntegerField(min_value=1)


class VenueSpaceSelectionCreateSerializer(_VenueClosedInputSerializer):
    """Serialize and validate venue space selection create data."""

    venue_selection_id = serializers.UUIDField()
    source_space_id = serializers.UUIDField(allow_null=True, required=False)
    source_combination_id = serializers.UUIDField(allow_null=True, required=False)
    selected_configuration_id = serializers.UUIDField(allow_null=True, required=False)
    local_name = serializers.CharField(max_length=200)
    capacity = VenueCapacitySerializer(allow_null=True, required=False)
    public_access_info = serializers.CharField(
        max_length=2_000, allow_blank=True, required=False
    )
    opening_restrictions = serializers.CharField(
        max_length=2_000, allow_blank=True, required=False
    )
    reason = serializers.CharField(max_length=1_000)

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
        if (attrs.get("source_space_id") is None) == (
            attrs.get("source_combination_id") is None
        ):
            raise serializers.ValidationError(
                {"source": ["Select exactly one physical space or combination."]}
            )
        return attrs


class VenueAvailabilityIntervalSerializer(_VenueClosedInputSerializer):
    """Serialize and validate venue availability interval data."""

    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    opening_restriction = serializers.CharField(
        max_length=500, allow_blank=True, required=False
    )


class VenueAvailabilitySetSerializer(_VenueClosedInputSerializer):
    """Serialize and validate venue availability set data."""

    expected_version = serializers.IntegerField(min_value=1)
    intervals = VenueAvailabilityIntervalSerializer(many=True, allow_empty=False)
    reason = serializers.CharField(max_length=1_000)


class _VenueBookingWriteSerializer(_VenueClosedInputSerializer):
    kind = serializers.ChoiceField(choices=VenueBooking.Kind.choices)
    external_reference = serializers.CharField(
        max_length=240, allow_blank=True, required=False
    )
    internal_title = serializers.CharField(max_length=240)
    public_title = serializers.CharField(
        max_length=240, allow_blank=True, required=False
    )
    public_description = serializers.CharField(
        max_length=2_000, allow_blank=True, required=False
    )
    capacity_mode = serializers.ChoiceField(choices=VenueBooking.CapacityMode.choices)
    expected_attendance = serializers.IntegerField(min_value=1)
    setup_starts_at = serializers.DateTimeField()
    effective_starts_at = serializers.DateTimeField()
    effective_ends_at = serializers.DateTimeField()
    teardown_ends_at = serializers.DateTimeField()
    public_layout_id = serializers.UUIDField(allow_null=True, required=False)
    reason = serializers.CharField(max_length=1_000)


class VenueBookingCreateSerializer(_VenueBookingWriteSerializer):
    """Serialize and validate venue booking create data."""


class VenueBookingUpdateSerializer(_VenueBookingWriteSerializer):
    """Serialize and validate venue booking update data."""

    expected_version = serializers.IntegerField(min_value=1)


class VenueBookingStateSerializer(_VenueClosedInputSerializer):
    """Serialize and validate venue booking state data."""

    expected_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=1_000)


class VenuePropertySummarySerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate venue property summary data."""

    id = serializers.UUIDField()
    slug = serializers.CharField()
    kind = serializers.CharField()
    legal_name = serializers.CharField()
    provider_name = serializers.CharField()
    public_name = serializers.CharField()
    public_description = serializers.CharField()
    internal_notes = serializers.CharField()
    location_name = serializers.CharField()
    postal_address = serializers.CharField()
    country_code = serializers.CharField()
    website_url = serializers.URLField(allow_blank=True)
    public_contact = serializers.CharField()
    contact_name = serializers.CharField()
    contact_email = serializers.EmailField(allow_blank=True)
    contact_phone = serializers.CharField()
    lifecycle = serializers.CharField()
    aggregate_version = serializers.IntegerField()


class VenueWorkspaceSpaceSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate venue workspace space data."""

    id = serializers.UUIDField()
    venue_selection_id = serializers.UUIDField()
    venue_name = serializers.CharField()
    local_name = serializers.CharField()
    configuration_name = serializers.CharField()
    seated_capacity = serializers.IntegerField()
    standing_capacity = serializers.IntegerField()
    table_capacity = serializers.IntegerField()
    fire_capacity = serializers.IntegerField()
    availability_version = serializers.IntegerField()
    active_booking_count = serializers.IntegerField()
    aggregate_version = serializers.IntegerField()


class VenueAvailabilityProjectionSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate venue availability projection data."""

    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    opening_restriction = serializers.CharField()


class VenueBookingProjectionSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate venue booking projection data."""

    id = serializers.UUIDField()
    kind = serializers.CharField()
    external_reference = serializers.CharField()
    internal_title = serializers.CharField()
    public_title = serializers.CharField()
    public_description = serializers.CharField()
    capacity_mode = serializers.CharField()
    expected_attendance = serializers.IntegerField()
    setup_starts_at = serializers.DateTimeField()
    effective_starts_at = serializers.DateTimeField()
    effective_ends_at = serializers.DateTimeField()
    teardown_ends_at = serializers.DateTimeField()
    review_state = serializers.CharField()
    publication_state = serializers.CharField()
    lifecycle = serializers.CharField()
    public_layout_reference = serializers.CharField()
    aggregate_version = serializers.IntegerField()


class VenueSpaceScheduleSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate venue space schedule data."""

    space = VenueWorkspaceSpaceSerializer()
    availability = VenueAvailabilityProjectionSerializer(many=True)
    bookings = VenueBookingProjectionSerializer(many=True)


class PublicVenueScheduleItemSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate public venue schedule item data."""

    booking_id = serializers.UUIDField()
    space_selection_id = serializers.UUIDField()
    venue_name = serializers.CharField()
    space_name = serializers.CharField()
    kind = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    access_info = serializers.CharField()
    layout_reference = serializers.CharField()
    layout_title = serializers.CharField()
