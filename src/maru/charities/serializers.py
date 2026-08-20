"""Closed API schemas for charity management and public projection."""

from rest_framework import serializers

from .models import CharityPartner, CharityPartnerMedia


class CharityCommandResultSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate charity command result data."""

    object_id = serializers.UUIDField()
    receipt_id = serializers.UUIDField()
    resulting_version = serializers.IntegerField(min_value=1)
    replayed = serializers.BooleanField()


class CharityPartnerCreateSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate charity partner create data."""

    slug = serializers.SlugField(max_length=80)
    legal_name = serializers.CharField(max_length=240)
    imprint_name = serializers.CharField(
        max_length=240,
        allow_blank=True,
        required=False,
    )
    public_name = serializers.CharField(max_length=200)
    short_description = serializers.CharField(
        max_length=500, allow_blank=True, required=False
    )
    description = serializers.CharField(
        max_length=5_000, allow_blank=True, required=False
    )
    location_name = serializers.CharField(
        max_length=240, allow_blank=True, required=False
    )
    postal_address = serializers.CharField(
        max_length=1_000, allow_blank=True, required=False
    )
    country_code = serializers.CharField(max_length=2, allow_blank=True, required=False)
    website_url = serializers.URLField(allow_blank=True, required=False)
    contact_email = serializers.EmailField(allow_blank=True, required=False)
    contact_phone = serializers.CharField(
        max_length=16, allow_blank=True, required=False
    )
    reason = serializers.CharField(max_length=1_000)


class CharityPartnerUpdateSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate charity partner update data."""

    expected_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=1_000)
    slug = serializers.SlugField(max_length=80, required=False)
    legal_name = serializers.CharField(max_length=240, required=False)
    imprint_name = serializers.CharField(
        max_length=240,
        allow_blank=True,
        required=False,
    )
    public_name = serializers.CharField(max_length=200, required=False)
    short_description = serializers.CharField(
        max_length=500, allow_blank=True, required=False
    )
    description = serializers.CharField(
        max_length=5_000, allow_blank=True, required=False
    )
    location_name = serializers.CharField(
        max_length=240, allow_blank=True, required=False
    )
    postal_address = serializers.CharField(
        max_length=1_000, allow_blank=True, required=False
    )
    country_code = serializers.CharField(max_length=2, allow_blank=True, required=False)
    website_url = serializers.URLField(allow_blank=True, required=False)
    contact_email = serializers.EmailField(allow_blank=True, required=False)
    contact_phone = serializers.CharField(
        max_length=16, allow_blank=True, required=False
    )
    lifecycle = serializers.ChoiceField(
        choices=CharityPartner.Lifecycle.choices,
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
                {"changes": ["Change at least one supported field."]},
                code="charity_no_changes",
            )
        return attrs


class CharityMediaAddSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate charity media add data."""

    kind = serializers.ChoiceField(choices=CharityPartnerMedia.Kind.choices)
    source_reference = serializers.CharField(max_length=1_000)
    owner_name = serializers.CharField(max_length=240)
    license_basis = serializers.CharField(max_length=500)
    usage_scope = serializers.CharField(max_length=500)
    attribution = serializers.CharField(
        max_length=500,
        allow_blank=True,
        required=False,
    )
    expires_at = serializers.DateTimeField(allow_null=True, required=False)
    reason = serializers.CharField(max_length=1_000)


class CharityMediaApproveSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate charity media approve data."""

    expected_version = serializers.IntegerField(min_value=1)
    public_reference = serializers.CharField(max_length=1_000)
    reason = serializers.CharField(max_length=1_000)


class CharityMediaWithdrawSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate charity media withdraw data."""

    expected_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=1_000)


class CharitySelectionProposeSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate charity selection propose data."""

    partner_id = serializers.UUIDField()
    responsible_department_id = serializers.UUIDField()
    reason = serializers.CharField(max_length=1_000)


class CharitySelectionDecisionSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate charity selection decision data."""

    expected_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=1_000)


class CharitySelectionCommentSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate charity selection comment data."""

    expected_version = serializers.IntegerField(min_value=1)
    private_comment = serializers.CharField(max_length=5_000)


class CharitySelectionPublishSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate charity selection publish data."""

    expected_version = serializers.IntegerField(min_value=1)
    media_ids = serializers.ListField(
        child=serializers.UUIDField(),
        max_length=24,
        allow_empty=True,
        required=False,
    )
    reason = serializers.CharField(max_length=1_000)


class PublicCharityMediaSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate public charity media data."""

    kind = serializers.CharField()
    reference = serializers.CharField()
    attribution = serializers.CharField()


class PublicCharitySerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate public charity data."""

    selection_id = serializers.UUIDField()
    public_name = serializers.CharField()
    imprint_name = serializers.CharField()
    short_description = serializers.CharField()
    location_name = serializers.CharField()
    country_code = serializers.CharField()
    website_url = serializers.URLField(allow_blank=True)
    media = PublicCharityMediaSerializer(many=True)


class CharityPartnerSummarySerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate charity partner summary data."""

    id = serializers.UUIDField()
    slug = serializers.CharField()
    legal_name = serializers.CharField()
    imprint_name = serializers.CharField()
    public_name = serializers.CharField()
    short_description = serializers.CharField()
    description = serializers.CharField()
    location_name = serializers.CharField()
    postal_address = serializers.CharField()
    country_code = serializers.CharField()
    website_url = serializers.URLField(allow_blank=True)
    contact_email = serializers.EmailField(allow_blank=True)
    contact_phone = serializers.CharField()
    lifecycle = serializers.CharField()
    aggregate_version = serializers.IntegerField()


class CharitySelectionSummarySerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate charity selection summary data."""

    id = serializers.UUIDField()
    partner_id = serializers.UUIDField()
    partner_name = serializers.CharField()
    responsible_department_id = serializers.UUIDField()
    responsible_department_name = serializers.CharField()
    status = serializers.CharField()
    publication_state = serializers.CharField()
    aggregate_version = serializers.IntegerField()


class CharityTimelineSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate charity timeline data."""

    sequence = serializers.IntegerField()
    kind = serializers.CharField()
    actor_id = serializers.UUIDField()
    occurred_at = serializers.DateTimeField()
    from_status = serializers.CharField()
    to_status = serializers.CharField()
    from_publication_state = serializers.CharField()
    to_publication_state = serializers.CharField()
    reason = serializers.CharField()
    private_comment = serializers.CharField()


class CharitySelectionReviewSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate charity selection review data."""

    summary = CharitySelectionSummarySerializer()
    timeline = CharityTimelineSerializer(many=True)
