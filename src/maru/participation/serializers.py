"""Explicit self-service API projections."""

from rest_framework import serializers

from maru.authorization.policy import ResourceScope, decide
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import OrganizationMembership
from maru.participation.models import Participation, ParticipationCapacity


class MembershipContextSerializer(serializers.ModelSerializer[OrganizationMembership]):
    organization_id = serializers.UUIDField(source="organization.id")
    organization_slug = serializers.CharField(source="organization.slug")
    organization_name = serializers.CharField(source="organization.name")

    class Meta:
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
    class Meta:
        model = ParticipationCapacity
        fields = (
            "code",
            "label_snapshot",
            "status",
            "contribution_summary",
            "public_history_visible",
        )
        read_only_fields = fields


class EditionContextSerializer(serializers.ModelSerializer[Participation]):
    organization_id = serializers.UUIDField(source="organization.id")
    organization_slug = serializers.CharField(source="organization.slug")
    series_id = serializers.UUIDField(source="edition.series.id")
    series_slug = serializers.CharField(source="edition.series.slug")
    series_name = serializers.CharField(source="edition.series.name")
    edition_id = serializers.UUIDField(source="edition.id")
    edition_slug = serializers.CharField(source="edition.slug")
    edition_name = serializers.CharField(source="edition.name")
    lifecycle = serializers.ChoiceField(
        source="edition.lifecycle",
        choices=EventEdition.Lifecycle.choices,
    )
    time_zone = serializers.CharField(source="edition.time_zone")
    language_codes = serializers.ListField(
        source="edition.language_codes",
        child=serializers.CharField(),
    )
    currency_codes = serializers.ListField(
        source="edition.currency_codes",
        child=serializers.CharField(),
    )
    starts_on = serializers.DateField(source="edition.starts_on")
    ends_on = serializers.DateField(source="edition.ends_on")
    participation_status = serializers.CharField(source="status")
    capacities = CapacityContextSerializer(many=True)
    can_transition = serializers.SerializerMethodField()

    class Meta:
        model = Participation
        fields = (
            "organization_id",
            "organization_slug",
            "series_id",
            "series_slug",
            "series_name",
            "edition_id",
            "edition_slug",
            "edition_name",
            "lifecycle",
            "time_zone",
            "language_codes",
            "currency_codes",
            "starts_on",
            "ends_on",
            "participation_status",
            "capacities",
            "can_transition",
        )
        read_only_fields = fields

    def get_can_transition(self, obj: Participation) -> bool:
        account = self.context.get("account")
        if not isinstance(account, Account):
            return False
        return decide(
            principal=account,
            capability_code="events.transition",
            resource=ResourceScope(
                organization_id=obj.organization_id,
                edition_id=obj.edition_id,
            ),
        ).allowed


class ParticipationHistorySerializer(serializers.ModelSerializer[Participation]):
    edition_id = serializers.UUIDField(source="edition.id")
    starts_on = serializers.DateField(source="edition.starts_on")
    ends_on = serializers.DateField(source="edition.ends_on")
    capacities = CapacityContextSerializer(many=True)

    class Meta:
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
    account_id = serializers.UUIDField()
    display_name = serializers.CharField()
    preferred_language = serializers.CharField()
    can_access_advanced_records = serializers.BooleanField()
    can_bootstrap_convention = serializers.BooleanField()
    memberships = MembershipContextSerializer(many=True)
    editions = EditionContextSerializer(many=True)


class StaffParticipationSummarySerializer(serializers.ModelSerializer[Participation]):
    account_id = serializers.UUIDField(source="account.id")
    display_name = serializers.CharField(source="account.display_name")
    participation_status = serializers.CharField(source="status")
    capacity_labels = serializers.SerializerMethodField()

    class Meta:
        model = Participation
        fields = (
            "account_id",
            "display_name",
            "participation_status",
            "capacity_labels",
        )
        read_only_fields = fields

    def get_capacity_labels(self, obj: Participation) -> list[str]:
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
