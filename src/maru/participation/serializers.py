"""Explicit self-service API projections."""

from rest_framework import serializers

from maru.events.adoption import PERSISTED_ADOPTION_PROFILE_CHOICES
from maru.events.models import EventEdition
from maru.organizations.models import OrganizationMembership
from maru.participation.models import Participation, ParticipationCapacity


class MembershipContextSerializer(serializers.ModelSerializer[OrganizationMembership]):
    """Serialize and validate membership context data."""

    organization_id = serializers.UUIDField(source="organization.id")
    organization_slug = serializers.CharField(source="organization.slug")
    organization_name = serializers.CharField(source="organization.name")

    class Meta:
        """Configure Django's declarative class metadata."""

        model = OrganizationMembership
        fields = (
            "organization_id",
            "organization_slug",
            "organization_name",
            "state",
            "relationship_label",
        )
        read_only_fields = fields


class CapacityContextSerializer(serializers.ModelSerializer[ParticipationCapacity]):
    """Serialize and validate capacity context data."""

    class Meta:
        """Configure Django's declarative class metadata."""

        model = ParticipationCapacity
        fields = (
            "code",
            "label_snapshot",
            "status",
            "contribution_summary",
            "public_history_visible",
        )
        read_only_fields = fields


class EditionContextSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate edition context data."""

    organization_id = serializers.UUIDField()
    organization_slug = serializers.CharField()
    series_id = serializers.UUIDField()
    series_slug = serializers.CharField()
    series_name = serializers.CharField()
    edition_id = serializers.UUIDField()
    edition_slug = serializers.CharField()
    edition_name = serializers.CharField()
    lifecycle = serializers.ChoiceField(
        choices=EventEdition.Lifecycle.choices,
    )
    adoption_profile_code = serializers.ChoiceField(
        choices=PERSISTED_ADOPTION_PROFILE_CHOICES,
        read_only=True,
    )
    adoption_profile_version = serializers.IntegerField(min_value=1, read_only=True)
    adoption_profile_label = serializers.CharField(read_only=True)
    adopted_modules = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
    )
    available_destinations = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
    )
    assignment_uses_participation_evidence = serializers.BooleanField(
        read_only=True,
    )
    time_zone = serializers.CharField()
    language_codes = serializers.ListField(
        child=serializers.CharField(),
    )
    currency_codes = serializers.ListField(
        child=serializers.CharField(),
    )
    starts_on = serializers.DateField()
    ends_on = serializers.DateField()
    participation_status = serializers.CharField()
    capacities = CapacityContextSerializer(many=True)
    can_transition = serializers.BooleanField(read_only=True)


class ParticipationHistorySerializer(serializers.ModelSerializer[Participation]):
    """Serialize and validate participation history data."""

    edition_id = serializers.UUIDField(source="edition.id")
    starts_on = serializers.DateField(source="edition.starts_on")
    ends_on = serializers.DateField(source="edition.ends_on")
    capacities = CapacityContextSerializer(many=True)

    class Meta:
        """Configure Django's declarative class metadata."""

        model = Participation
        fields = (
            "edition_id",
            "series_name_snapshot",
            "edition_name_snapshot",
            "starts_on",
            "ends_on",
            "status",
            "public_history_visible",
            "capacities",
        )
        read_only_fields = fields


class MyContextSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate my context data."""

    account_id = serializers.UUIDField()
    display_name = serializers.CharField()
    preferred_language = serializers.CharField()
    can_access_advanced_records = serializers.BooleanField()
    memberships = MembershipContextSerializer(many=True)
    editions = EditionContextSerializer(many=True)


class StaffParticipationSummarySerializer(serializers.ModelSerializer[Participation]):
    """Serialize and validate staff participation summary data."""

    account_id = serializers.UUIDField(source="account.id")
    display_name = serializers.CharField(source="account.display_name")
    participation_status = serializers.CharField(source="status")
    capacity_labels = serializers.SerializerMethodField()

    class Meta:
        """Configure Django's declarative class metadata."""

        model = Participation
        fields = (
            "account_id",
            "display_name",
            "participation_status",
            "capacity_labels",
        )
        read_only_fields = fields

    def get_capacity_labels(self, obj: Participation) -> list[str]:
        """Return capacity labels.

        Parameters
        ----------
        obj : Participation
            The model instance being validated or presented.

        Returns
        -------
        list[str]
            The matching get capacity labels records in deterministic order.
        """
        return [
            capacity.label_snapshot
            for capacity in obj.capacities.all()
            if capacity.status
            in (
                ParticipationCapacity.Status.PROPOSED,
                ParticipationCapacity.Status.ACTIVE,
            )
        ]


class StaffParticipationListQuerySerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate staff participation list query data."""

    search = serializers.CharField(
        required=False,
        allow_blank=False,
        trim_whitespace=True,
        max_length=100,
    )
    status = serializers.ChoiceField(
        required=False,
        choices=Participation.Status.choices,
    )
    capacity = serializers.CharField(
        required=False,
        allow_blank=False,
        trim_whitespace=True,
        max_length=80,
    )
    page = serializers.IntegerField(required=False, min_value=1)
    page_size = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=100,
    )
