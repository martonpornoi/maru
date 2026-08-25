"""Closed browser forms for Shift planning and person-owned claims."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from django import forms

from maru.core.forms import (
    CanonicalUUIDField,
    StrictBase10IntegerField,
    StrictInputForm,
)
from maru.workforce.forms import (
    PositionUUIDChoiceField,
    WorkforceEditionLocalDateTimeField,
)
from maru.workforce.models import (
    MAX_SHIFT_BREAK_MINUTES,
    MAX_SHIFT_HEADCOUNT,
    MAX_SHIFT_REST_MINUTES,
)
from maru.workforce.shift_inputs import (
    MAX_SHIFT_BRIEFING_LENGTH,
    MAX_SHIFT_LOCATION_LENGTH,
    MAX_SHIFT_REASON_LENGTH,
    MAX_SHIFT_SUPERVISION_LENGTH,
    MAX_SHIFT_TITLE_LENGTH,
    normalize_shift_interval,
    validate_shift_numbers,
)

if TYPE_CHECKING:
    from datetime import date, datetime

PositionChoices = tuple[tuple[str, str], ...]


class ShiftDemandForm(StrictInputForm):
    """Collect one complete draft demand in the edition's local time zone."""

    position_id = PositionUUIDChoiceField(label="Position")
    title = forms.CharField(
        label="Shift name",
        max_length=MAX_SHIFT_TITLE_LENGTH,
        help_text="Use the name people will recognize in My shifts.",
    )
    location_label = forms.CharField(
        label="Where to report",
        max_length=MAX_SHIFT_LOCATION_LENGTH,
        help_text="Name an operational meeting point, room, or desk.",
    )
    starts_at = WorkforceEditionLocalDateTimeField(label="Starts")
    ends_at = WorkforceEditionLocalDateTimeField(label="Ends")
    required_headcount = StrictBase10IntegerField(
        label="People needed",
        min_value=1,
        max_value=MAX_SHIFT_HEADCOUNT,
    )
    break_minutes = StrictBase10IntegerField(
        label="Break minutes",
        min_value=0,
        max_value=MAX_SHIFT_BREAK_MINUTES,
        help_text="Enter zero when no planned break applies.",
    )
    minimum_rest_minutes = StrictBase10IntegerField(
        label="Required rest after this Shift",
        min_value=0,
        max_value=MAX_SHIFT_REST_MINUTES,
        help_text="Claims that would overlap this post-Shift rest are blocked.",
    )
    briefing = forms.CharField(
        label="What the person will do",
        max_length=MAX_SHIFT_BRIEFING_LENGTH,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    supervision_note = forms.CharField(
        label="Supervision or handover",
        max_length=MAX_SHIFT_SUPERVISION_LENGTH,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Optional. Do not record private accommodation reasons here.",
    )
    reason = forms.CharField(
        label="Planning reason",
        max_length=MAX_SHIFT_REASON_LENGTH,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Retained for organizers; never shown in My shifts.",
    )
    expected_version = StrictBase10IntegerField(
        min_value=0,
        widget=forms.HiddenInput,
    )
    retry_key = CanonicalUUIDField(widget=forms.HiddenInput)

    def __init__(
        self,
        *args: Any,
        position_choices: PositionChoices,
        starts_on: date,
        ends_on: date,
        time_zone: str,
        expected_version: int,
        retry_key: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Configure exact scope choices, calendar, version, and retry evidence.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the Django form.
        position_choices : PositionChoices
            Exact-edition active Positions available to the organizer.
        starts_on : date
            First local calendar date of the edition.
        ends_on : date
            Last local calendar date of the edition.
        time_zone : str
            Canonical IANA zone used to resolve local browser input.
        expected_version : int
            Current demand version, or zero for creation.
        retry_key : UUID | None, default=None
            Stable idempotency key, generated when omitted.
        **kwargs : Any
            Keyword arguments forwarded to the Django form.
        """
        initial = dict(kwargs.pop("initial", {}) or {})
        initial.setdefault("expected_version", expected_version)
        initial.setdefault("retry_key", retry_key or uuid4())
        initial.setdefault("break_minutes", 0)
        initial.setdefault("minimum_rest_minutes", 0)
        kwargs["initial"] = initial
        kwargs.setdefault("auto_id", "id_shift_demand_%s")
        super().__init__(*args, **kwargs)
        position_field = cast("PositionUUIDChoiceField", self.fields["position_id"])
        position_field.set_choices(position_choices)
        for name in ("starts_at", "ends_at"):
            field = cast("WorkforceEditionLocalDateTimeField", self.fields[name])
            field.set_zone(time_zone)
        self.starts_on = starts_on
        self.ends_on = ends_on
        self.zone = ZoneInfo(time_zone)

    def clean(self) -> dict[str, object]:
        """Validate demand timing and safety numbers as one coherent input.

        Returns
        -------
        dict[str, object]
            Cleaned values with field or non-field errors attached to the form.
        """
        cleaned = cast("dict[str, object]", super().clean() or {})
        if self.errors:
            return cleaned
        starts_at_value = cleaned.get("starts_at")
        ends_at_value = cleaned.get("ends_at")
        if starts_at_value is None or ends_at_value is None:
            return cleaned
        starts_at = cast("datetime", starts_at_value)
        ends_at = cast("datetime", ends_at_value)
        try:
            normalize_shift_interval(
                starts_at=starts_at,
                ends_at=ends_at,
                starts_on=self.starts_on,
                ends_on=self.ends_on,
                zone=self.zone,
            )
            validate_shift_numbers(
                required_headcount=cast("int", cleaned["required_headcount"]),
                break_minutes=cast("int", cleaned["break_minutes"]),
                minimum_rest_minutes=cast("int", cleaned["minimum_rest_minutes"]),
                starts_at=starts_at,
                ends_at=ends_at,
            )
        except forms.ValidationError as error:
            if hasattr(error, "error_dict"):
                for field_name, field_errors in error.error_dict.items():
                    target = field_name if field_name in self.fields else None
                    for field_error in field_errors:
                        self.add_error(target, field_error)
            else:
                self.add_error(None, error)
        return cleaned


class ShiftReasonCommandForm(StrictInputForm):
    """Collect optimistic version, retry key, and organizer rationale."""

    expected_version = StrictBase10IntegerField(min_value=1, widget=forms.HiddenInput)
    retry_key = CanonicalUUIDField(widget=forms.HiddenInput)
    reason = forms.CharField(
        label="Reason",
        max_length=MAX_SHIFT_REASON_LENGTH,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(
        self,
        *args: Any,
        expected_version: int,
        retry_key: UUID | None = None,
        action_code: str = "change",
        **kwargs: Any,
    ) -> None:
        """Seed the visible record version and stable browser retry key.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the Django form.
        expected_version : int
            Current aggregate version required by the command.
        retry_key : UUID | None, default=None
            Stable idempotency key, generated when omitted.
        action_code : str, default="change"
            Stable action fragment used to isolate generated control IDs.
        **kwargs : Any
            Keyword arguments forwarded to the Django form.
        """
        initial = dict(kwargs.pop("initial", {}) or {})
        initial.setdefault("expected_version", expected_version)
        initial.setdefault("retry_key", retry_key or uuid4())
        kwargs["initial"] = initial
        kwargs.setdefault("auto_id", f"id_shift_{action_code}_%s")
        super().__init__(*args, **kwargs)


class ShiftLockForm(ShiftReasonCommandForm):
    """Require an explicit choice before locking underfilled coverage."""

    allow_understaffed = forms.BooleanField(
        label="Lock even when fewer people are confirmed than requested",
        required=False,
        help_text="The retained reason must explain the accepted coverage risk.",
    )


class ShiftClaimForm(StrictInputForm):
    """Carry only demand version and idempotency evidence for a self claim."""

    expected_version = StrictBase10IntegerField(min_value=1, widget=forms.HiddenInput)
    retry_key = CanonicalUUIDField(widget=forms.HiddenInput)

    def __init__(
        self,
        *args: Any,
        expected_version: int,
        retry_key: UUID | None = None,
        action_code: str = "claim",
        **kwargs: Any,
    ) -> None:
        """Seed the current demand version and stable retry key.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the Django form.
        expected_version : int
            Current demand version required by the claim command.
        retry_key : UUID | None, default=None
            Stable idempotency key, generated when omitted.
        action_code : str, default="claim"
            Stable action fragment used to isolate generated control IDs.
        **kwargs : Any
            Keyword arguments forwarded to the Django form.
        """
        initial = dict(kwargs.pop("initial", {}) or {})
        initial.setdefault("expected_version", expected_version)
        initial.setdefault("retry_key", retry_key or uuid4())
        kwargs["initial"] = initial
        kwargs.setdefault("auto_id", f"id_shift_{action_code}_%s")
        super().__init__(*args, **kwargs)


class ShiftCommitmentReasonForm(ShiftReasonCommandForm):
    """Collect versioned organizer rationale for confirmation or removal."""


class ShiftWithdrawForm(StrictInputForm):
    """Confirm a person-owned withdrawal without collecting private rationale."""

    expected_version = StrictBase10IntegerField(min_value=1, widget=forms.HiddenInput)
    retry_key = CanonicalUUIDField(widget=forms.HiddenInput)
    confirm = forms.BooleanField(
        label="I understand this removes me from the Shift",
        help_text=(
            "You do not need to explain why. Organizers will only see that you "
            "withdrew."
        ),
    )

    def __init__(
        self,
        *args: Any,
        expected_version: int,
        retry_key: UUID | None = None,
        action_code: str = "withdraw",
        **kwargs: Any,
    ) -> None:
        """Seed current version and isolated idempotency evidence.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the Django form.
        expected_version : int
            Current commitment version required by withdrawal.
        retry_key : UUID | None, default=None
            Stable idempotency key, generated when omitted.
        action_code : str, default="withdraw"
            Stable action fragment used to isolate generated control IDs.
        **kwargs : Any
            Keyword arguments forwarded to the Django form.
        """
        initial = dict(kwargs.pop("initial", {}) or {})
        initial.setdefault("expected_version", expected_version)
        initial.setdefault("retry_key", retry_key or uuid4())
        kwargs["initial"] = initial
        kwargs.setdefault("auto_id", f"id_shift_{action_code}_%s")
        super().__init__(*args, **kwargs)
