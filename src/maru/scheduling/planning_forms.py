"""Native strict timetable controls shared by keyboard and pointer-prefilled input."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from django import forms
from django.core.exceptions import ValidationError

from maru.core.forms import (
    CanonicalUUIDField,
    StrictBase10IntegerField,
    StrictInputForm,
)

from .catalogs import MAX_REASON_LENGTH, MAX_TITLE_LENGTH
from .inputs import (
    SchedulingPlacementInput,
    SchedulingServiceDayInput,
    normalized_text,
)
from .planning_interactions import parse_planning_minute
from .time_rules import (
    MAX_HOSTS_PER_OCCURRENCE,
    SchedulingEnvelope,
    SchedulingHostPresence,
    SchedulingWindow,
)

_MAX_MINUTE_INPUT_LENGTH = 32

if TYPE_CHECKING:
    from uuid import UUID

    type PlanningChoices = tuple[tuple[UUID, str], ...]


class _PlanningMinuteField(forms.Field):
    def __init__(self, *, zone_name: str, **kwargs: Any) -> None:
        self.zone_name = zone_name
        super().__init__(
            widget=forms.TextInput(attrs={"placeholder": "2030-08-02T10:00+02:00"}),
            help_text=(
                f"Exact minute in {zone_name}. Include an offset for a repeated hour."
            ),
            **kwargs,
        )

    def to_python(self, value: object) -> datetime | None:
        if value in self.empty_values:
            return None
        if not isinstance(value, str) or len(value) > _MAX_MINUTE_INPUT_LENGTH:
            raise ValidationError(
                "Enter an exact local minute or minute with UTC offset."
            )
        return parse_planning_minute(value, zone_name=self.zone_name)

    def prepare_value(self, value: object) -> object:
        if isinstance(value, datetime):
            return value.astimezone(ZoneInfo(self.zone_name)).isoformat(
                timespec="minutes"
            )
        return value


class _PlanningChoiceField(CanonicalUUIDField):
    def __init__(self, *, choices: PlanningChoices, **kwargs: Any) -> None:
        self.identifiers = frozenset(identifier for identifier, _ in choices)
        super().__init__(
            widget=forms.Select(
                choices=[
                    ("", "Choose a selection"),
                    *((str(identifier), label) for identifier, label in choices),
                ]
            ),
            **kwargs,
        )

    def to_python(self, value: object) -> UUID | None:
        identifier = super().to_python(value)
        if identifier is not None and identifier not in self.identifiers:
            raise ValidationError("Choose a selection from this edition.")
        return identifier


def _version_field(*, initial: bool = False) -> StrictBase10IntegerField:
    return StrictBase10IntegerField(
        min_value=0 if initial else 1, max_value=2**63 - 2, widget=forms.HiddenInput
    )


class PlanningCommandForm(StrictInputForm):
    """Preserve explicit retry attribution and a bounded human mutation reason."""

    retry_key = CanonicalUUIDField(widget=forms.HiddenInput)
    reason = forms.CharField(
        label="Reason for this change",
        max_length=MAX_REASON_LENGTH,
        widget=forms.Textarea(attrs={"rows": 2}),
    )

    def clean(self) -> dict[str, Any]:
        """Normalize rationale with the same bounded command text contract.

        Returns
        -------
        dict[str, Any]
            Strict cleaned input without minting a new retry key or writing state.
        """
        cleaned = super().clean() or {}
        if cleaned.get("reason"):
            try:
                cleaned["reason"] = normalized_text(
                    cleaned["reason"], maximum=MAX_REASON_LENGTH
                )
            except ValidationError as error:
                self.add_error("reason", error)
        return cleaned


class PlanningPlacementForm(PlanningCommandForm):
    """Complete explicit room, envelope and selected-host intent without autosave."""

    action = forms.ChoiceField(
        choices=(
            ("preview_placement", "Preview changes"),
            ("save_placement", "Save private draft"),
        ),
        widget=forms.HiddenInput,
    )
    candidate_id = CanonicalUUIDField(widget=forms.HiddenInput)
    expected_version = _version_field()
    occurrence_id = CanonicalUUIDField(label="Occurrence")
    occurrence_version = _version_field()
    day_id = CanonicalUUIDField(label="Service day")
    day_version = _version_field()
    space_selection_id = CanonicalUUIDField(label="Room or room combination")
    capacity_mode = forms.ChoiceField(
        label="Capacity configuration",
        choices=(
            ("seated", "Seated"),
            ("standing", "Standing"),
            ("table", "Table"),
        ),
    )
    expected_attendance = StrictBase10IntegerField(
        label="Expected attendance",
        min_value=1,
        max_value=2**31 - 1,
        widget=forms.NumberInput(attrs={"min": 1}),
    )
    reason = forms.CharField(
        label="Reason for saving this change",
        max_length=MAX_REASON_LENGTH,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Required for Save. A preview does not record a change reason.",
    )

    def __init__(
        self,
        *args: Any,
        zone_name: str,
        occurrences: PlanningChoices,
        days: PlanningChoices,
        spaces: PlanningChoices,
        hosts: PlanningChoices,
        **kwargs: Any,
    ) -> None:
        """Bind only owner-authorized choices and the trusted edition time zone.

        Parameters
        ----------
        *args : Any
            Django form data, retaining original values on validation failure.
        zone_name : str
            Events-owned edition IANA time zone, never a browser preference.
        occurrences : PlanningChoices
            Already authorized complete occurrence choices.
        days : PlanningChoices
            Already authorized service-day choices.
        spaces : PlanningChoices
            Independently authorized Venue selection labels.
        hosts : PlanningChoices
            Complete independently authorized roster for this occurrence's item.
        **kwargs : Any
            Ordinary Django form construction options.

        Raises
        ------
        ValueError
            If trusted roster choices are duplicated or exceed the domain bound.
        """
        super().__init__(*args, **kwargs)
        if len(hosts) > MAX_HOSTS_PER_OCCURRENCE or len(
            {row[0] for row in hosts}
        ) != len(hosts):
            raise ValueError("Supply one complete bounded distinct host roster.")
        self.host_choices = hosts
        self.placement_intent: SchedulingPlacementInput | None = None
        for name, choices in (
            ("occurrence_id", occurrences),
            ("day_id", days),
            ("space_selection_id", spaces),
        ):
            self.fields[name] = _PlanningChoiceField(
                choices=choices, label=self.fields[name].label
            )
        for name, label in (
            ("setup_starts_at", "Preparation starts"),
            ("effective_starts_at", "Delivery starts"),
            ("effective_ends_at", "Delivery ends"),
            ("teardown_ends_at", "Teardown ends"),
        ):
            self.fields[name] = _PlanningMinuteField(zone_name=zone_name, label=label)
        for identifier, label in hosts:
            prefix = f"host_{identifier.hex}"
            self.fields[f"{prefix}_required"] = forms.ChoiceField(
                label=f"Required presence: {label}",
                required=False,
                choices=(
                    ("", "Not required in this placement"),
                    ("required", "Required presence"),
                ),
            )
            for suffix, time_label in (("starts_at", "Starts"), ("ends_at", "Ends")):
                self.fields[f"{prefix}_{suffix}"] = _PlanningMinuteField(
                    zone_name=zone_name, label=f"{label}: {time_label}", required=False
                )

    def clean(self) -> dict[str, Any]:
        """Build the shared placement intent, preserving every invalid entered value.

        Returns
        -------
        dict[str, Any]
            Cleaned fields; ``placement_intent`` is set only for valid structure.
        """
        cleaned = super().clean()
        self.placement_intent = None
        if cleaned.get("action") == "save_placement" and not cleaned.get("reason"):
            self.add_error("reason", "Explain this private draft change before saving.")
        presences = []
        for identifier, _label in self.host_choices:
            prefix = f"host_{identifier.hex}"
            if cleaned.get(f"{prefix}_required") != "required":
                continue
            for suffix in ("starts_at", "ends_at"):
                if cleaned.get(f"{prefix}_{suffix}") is None:
                    self.add_error(
                        f"{prefix}_{suffix}", "Enter the required presence time."
                    )
            if all(
                cleaned.get(f"{prefix}_{suffix}") is not None
                for suffix in ("starts_at", "ends_at")
            ):
                presences.append(
                    SchedulingHostPresence(
                        identifier,
                        cleaned[f"{prefix}_starts_at"],
                        cleaned[f"{prefix}_ends_at"],
                    )
                )
        if self.errors:
            return cleaned
        try:
            self.placement_intent = SchedulingPlacementInput(
                cleaned["occurrence_id"],
                cleaned["occurrence_version"],
                cleaned["day_id"],
                cleaned["day_version"],
                cleaned["space_selection_id"],
                SchedulingEnvelope(
                    cleaned["setup_starts_at"],
                    cleaned["effective_starts_at"],
                    cleaned["effective_ends_at"],
                    cleaned["teardown_ends_at"],
                ),
                cleaned["capacity_mode"],
                cleaned["expected_attendance"],
                tuple(presences),
            ).normalized()
        except ValidationError as error:
            self.add_error(None, error)
        return cleaned


class PlanningServiceDayForm(PlanningCommandForm):
    """Create or revise explicit overnight-capable service days with native fields."""

    action = forms.ChoiceField(
        choices=(
            ("create_day", "Create service day"),
            ("revise_day", "Revise service day"),
        ),
        widget=forms.HiddenInput,
    )
    day_id = CanonicalUUIDField(required=False, widget=forms.HiddenInput)
    expected_version = _version_field(initial=True)
    label = forms.CharField(label="Service day label", max_length=MAX_TITLE_LENGTH)
    precision_minutes = StrictBase10IntegerField(
        label="Grid precision in minutes",
        min_value=1,
        max_value=60,
        help_text="Use a divisor of 60, such as 1, 5, 10, 15 or 30.",
    )

    def __init__(self, *args: Any, zone_name: str, **kwargs: Any) -> None:
        """Use the trusted edition zone without deriving service days from midnight.

        Parameters
        ----------
        *args : Any
            Ordinary Django form data or initial state.
        zone_name : str
            Events-owned IANA time zone for both explicit boundary controls.
        **kwargs : Any
            Ordinary Django form options.
        """
        super().__init__(*args, **kwargs)
        self.day_intent: SchedulingServiceDayInput | None = None
        for name, label in (
            ("starts_at", "Service day starts"),
            ("ends_at", "Service day ends"),
        ):
            self.fields[name] = _PlanningMinuteField(zone_name=zone_name, label=label)

    def clean(self) -> dict[str, Any]:
        """Require explicit create/revise preconditions and the shared day contract.

        Returns
        -------
        dict[str, Any]
            Cleaned fields; ``day_intent`` is set only for valid structure.
        """
        cleaned = super().clean()
        self.day_intent = None
        if cleaned.get("action") == "revise_day":
            if not cleaned.get("day_id"):
                self.add_error("day_id", "Select the exact day to revise.")
            if cleaned.get("expected_version") == 0:
                self.add_error(
                    "expected_version", "Refresh the current service-day version."
                )
        elif cleaned.get("action") == "create_day" and cleaned.get("day_id"):
            self.add_error(
                "day_id", "A new service day must not replace an existing day."
            )
        if self.errors:
            return cleaned
        try:
            self.day_intent = SchedulingServiceDayInput(
                cleaned["label"],
                SchedulingWindow(cleaned["starts_at"], cleaned["ends_at"]),
                cleaned["precision_minutes"],
            ).normalized()
        except ValidationError as error:
            self.add_error(None, error)
        return cleaned
