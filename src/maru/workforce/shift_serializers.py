"""Closed request and minimized response serializers for Workforce Shifts."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, ClassVar
from uuid import UUID

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from maru.workforce.models import (
    MAX_SHIFT_BREAK_MINUTES,
    MAX_SHIFT_HEADCOUNT,
    MAX_SHIFT_REST_MINUTES,
    ShiftCommitment,
    ShiftDemand,
)
from maru.workforce.shift_inputs import (
    MAX_SHIFT_BRIEFING_LENGTH,
    MAX_SHIFT_LOCATION_LENGTH,
    MAX_SHIFT_REASON_LENGTH,
    MAX_SHIFT_SUPERVISION_LENGTH,
    MAX_SHIFT_TITLE_LENGTH,
)
from maru.workforce.structure_inputs import CANONICAL_UUID_PATTERN

if TYPE_CHECKING:
    from datetime import datetime

_EXPLICIT_OFFSET_DATE_TIME = re.compile(r".+(?:[zZ]|[+-][0-9]{2}:[0-9]{2})\Z")


class _StrictShiftTextField(serializers.CharField):
    """Accept only a JSON string without primitive coercion."""

    default_error_messages: ClassVar[dict[str, Any]] = {
        "invalid_type": "Enter a JSON string for this field.",
    }

    def to_internal_value(self, data: object) -> str:
        if not isinstance(data, str):
            self.fail("invalid_type")
        return super().to_internal_value(data)


class _StrictShiftIntegerField(serializers.IntegerField):
    """Accept an exact JSON integer, excluding bool, float, and string values."""

    default_error_messages: ClassVar[dict[str, Any]] = {
        "invalid_type": "Enter a JSON integer for this field.",
    }

    def to_internal_value(self, data: object) -> int:
        if type(data) is not int:
            self.fail("invalid_type")
        return super().to_internal_value(data)


class _StrictShiftBooleanField(serializers.BooleanField):
    """Accept only a JSON boolean without integer or string coercion."""

    default_error_messages: ClassVar[dict[str, Any]] = {
        "invalid_type": "Enter a JSON boolean for this field.",
    }

    def to_internal_value(self, data: object) -> bool:
        if type(data) is not bool:
            self.fail("invalid_type")
        return super().to_internal_value(data)


class _AwareShiftDateTimeField(serializers.DateTimeField):
    """Require an ISO date-time JSON string with an explicit UTC offset."""

    default_error_messages: ClassVar[dict[str, Any]] = {
        "timezone_required": "Enter a date and time with an explicit timezone.",
    }

    def to_internal_value(self, data: object) -> datetime:
        if (
            not isinstance(data, str)
            or _EXPLICIT_OFFSET_DATE_TIME.fullmatch(data) is None
        ):
            self.fail("timezone_required")
        return super().to_internal_value(data)


@extend_schema_field(
    {
        "type": "string",
        "format": "uuid",
        "pattern": CANONICAL_UUID_PATTERN,
    }
)
class _CanonicalShiftUUIDField(serializers.UUIDField):
    """Accept only Maru's lower-case hyphenated UUID representation."""

    default_error_messages: ClassVar[dict[str, Any]] = {
        "non_canonical": "Enter a canonical lower-case hyphenated UUID.",
    }

    def to_internal_value(self, data: object) -> UUID:
        if not isinstance(data, str):
            self.fail("invalid")
        try:
            value = UUID(data)
        except (AttributeError, ValueError):
            self.fail("invalid")
        if str(value) != data:
            self.fail("non_canonical")
        return value


class ShiftDemandWriteSerializer(serializers.Serializer[dict[str, object]]):
    """Validate one complete organizer Shift-demand representation."""

    position_id = _CanonicalShiftUUIDField()
    title = _StrictShiftTextField(
        max_length=MAX_SHIFT_TITLE_LENGTH,
        trim_whitespace=False,
    )
    location_label = _StrictShiftTextField(
        max_length=MAX_SHIFT_LOCATION_LENGTH,
        trim_whitespace=False,
    )
    briefing = _StrictShiftTextField(
        max_length=MAX_SHIFT_BRIEFING_LENGTH,
        trim_whitespace=False,
    )
    supervision_note = _StrictShiftTextField(
        max_length=MAX_SHIFT_SUPERVISION_LENGTH,
        trim_whitespace=False,
        allow_blank=True,
        required=False,
        default="",
    )
    starts_at = _AwareShiftDateTimeField()
    ends_at = _AwareShiftDateTimeField()
    required_headcount = _StrictShiftIntegerField(
        min_value=1,
        max_value=MAX_SHIFT_HEADCOUNT,
    )
    break_minutes = _StrictShiftIntegerField(
        min_value=0,
        max_value=MAX_SHIFT_BREAK_MINUTES,
    )
    minimum_rest_minutes = _StrictShiftIntegerField(
        min_value=0,
        max_value=MAX_SHIFT_REST_MINUTES,
    )
    reason = _StrictShiftTextField(
        max_length=MAX_SHIFT_REASON_LENGTH,
        trim_whitespace=False,
    )


class ShiftDemandUpdateSerializer(ShiftDemandWriteSerializer):
    """Validate a versioned complete replacement of a Shift draft."""

    expected_version = _StrictShiftIntegerField(min_value=1)


class ShiftReasonCommandSerializer(serializers.Serializer[dict[str, object]]):
    """Validate a versioned reasoned Shift state command."""

    expected_version = _StrictShiftIntegerField(min_value=1)
    reason = _StrictShiftTextField(
        max_length=MAX_SHIFT_REASON_LENGTH,
        trim_whitespace=False,
    )


class ShiftLockCommandSerializer(ShiftReasonCommandSerializer):
    """Validate explicit underfill acceptance for coverage locking."""

    allow_understaffed = _StrictShiftBooleanField(default=False)


class ShiftClaimCommandSerializer(serializers.Serializer[dict[str, object]]):
    """Validate one person-owned versioned Shift claim."""

    expected_version = _StrictShiftIntegerField(min_value=1)


class ShiftWithdrawCommandSerializer(serializers.Serializer[dict[str, object]]):
    """Require an explicit withdrawal confirmation without personal rationale."""

    expected_version = _StrictShiftIntegerField(min_value=1)
    confirm = _StrictShiftBooleanField()

    def validate_confirm(self, value: bool) -> bool:  # noqa: FBT001
        """Require an affirmative choice so accidental submissions fail closed.

        Parameters
        ----------
        value : bool
            Candidate strict JSON confirmation flag supplied by the person.

        Returns
        -------
        bool
            Validated affirmative withdrawal confirmation.

        Raises
        ------
        serializers.ValidationError
            If the person did not explicitly confirm withdrawal.
        """
        if not value:
            raise serializers.ValidationError(
                "Confirm that you want to withdraw from this Shift."
            )
        return value


class ShiftMutationResultSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize minimized demand or commitment command evidence."""

    id = serializers.UUIDField()
    demand_id = serializers.UUIDField(required=False)
    receipt_id = serializers.UUIDField()
    resulting_version = serializers.IntegerField(min_value=1)
    status = serializers.CharField()
    replayed = serializers.BooleanField()


class OrganizerShiftCommitmentSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize one authorized organizer coverage row."""

    id = serializers.UUIDField()
    account_label = serializers.CharField()
    status = serializers.ChoiceField(choices=ShiftCommitment.Status.choices)
    command_version = serializers.IntegerField(min_value=1)
    availability_version = serializers.IntegerField(min_value=1)
    availability_current = serializers.BooleanField()
    qualification_current = serializers.BooleanField()
    claimed_at = serializers.DateTimeField()
    confirmed_at = serializers.DateTimeField(allow_null=True)
    confirmation_reason = serializers.CharField(allow_blank=True)
    removed_at = serializers.DateTimeField(allow_null=True)
    removal_kind = serializers.ChoiceField(
        choices=ShiftCommitment.RemovalKind.choices,
        allow_blank=True,
    )
    removal_reason = serializers.CharField(allow_blank=True)
    completed_at = serializers.DateTimeField(allow_null=True)
    completion_reason = serializers.CharField(allow_blank=True)


class OrganizerShiftDemandSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize one demand and its complete minimized coverage."""

    id = serializers.UUIDField()
    position_id = serializers.UUIDField()
    department_name = serializers.CharField()
    position_title = serializers.CharField()
    title = serializers.CharField()
    location_label = serializers.CharField()
    briefing = serializers.CharField()
    supervision_note = serializers.CharField(allow_blank=True)
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    required_headcount = serializers.IntegerField(min_value=1)
    break_minutes = serializers.IntegerField(min_value=0)
    minimum_rest_minutes = serializers.IntegerField(min_value=0)
    status = serializers.ChoiceField(choices=ShiftDemand.Status.choices)
    command_version = serializers.IntegerField(min_value=1)
    claimed_count = serializers.IntegerField(min_value=0)
    confirmed_count = serializers.IntegerField(min_value=0)
    active_count = serializers.IntegerField(min_value=0)
    remaining_count = serializers.IntegerField(min_value=0)
    commitments = OrganizerShiftCommitmentSerializer(many=True)


class OrganizerShiftOverviewSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize complete exact-edition Shift planning."""

    open_count = serializers.IntegerField(min_value=0)
    locked_count = serializers.IntegerField(min_value=0)
    attention_count = serializers.IntegerField(min_value=0)
    can_manage = serializers.BooleanField()
    demands = OrganizerShiftDemandSerializer(many=True)


class MySuitableShiftSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize one currently claimable person-owned opportunity."""

    id = serializers.UUIDField()
    position_title = serializers.CharField()
    department_name = serializers.CharField()
    title = serializers.CharField()
    location_label = serializers.CharField()
    briefing = serializers.CharField()
    supervision_note = serializers.CharField(allow_blank=True)
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    break_minutes = serializers.IntegerField(min_value=0)
    minimum_rest_minutes = serializers.IntegerField(min_value=0)
    command_version = serializers.IntegerField(min_value=1)
    preference = serializers.CharField()
    remaining_count = serializers.IntegerField(min_value=1)


class MyShiftCommitmentSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize one retained commitment without other people or reasons."""

    id = serializers.UUIDField()
    demand_id = serializers.UUIDField()
    position_title = serializers.CharField()
    department_name = serializers.CharField()
    title = serializers.CharField()
    location_label = serializers.CharField()
    briefing = serializers.CharField()
    supervision_note = serializers.CharField(allow_blank=True)
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    break_minutes = serializers.IntegerField(min_value=0)
    minimum_rest_minutes = serializers.IntegerField(min_value=0)
    demand_status = serializers.ChoiceField(choices=ShiftDemand.Status.choices)
    status = serializers.ChoiceField(choices=ShiftCommitment.Status.choices)
    command_version = serializers.IntegerField(min_value=1)
    availability_current = serializers.BooleanField()
    qualification_current = serializers.BooleanField()
    can_withdraw = serializers.BooleanField()


class MyShiftOverviewSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize one person's suitable work and retained commitments."""

    suitable = MySuitableShiftSerializer(many=True)
    commitments = MyShiftCommitmentSerializer(many=True)
