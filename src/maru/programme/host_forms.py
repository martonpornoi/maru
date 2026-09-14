"""Explicit organizer hosting and person-owned response/availability forms."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from django import forms
from django.forms import BaseFormSet, formset_factory

from maru.core.forms import (
    CanonicalUUIDField,
    StrictBase10IntegerField,
    StrictInputForm,
)

from .host_catalogs import (
    MAX_HOST_AVAILABILITY_PERIODS,
    MAX_HOST_BRIEFING,
    MAX_HOST_INVITATION_TITLE,
)
from .workbench_forms import ProgrammeWorkbenchForm

_MINUTE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}\Z")


def _version() -> StrictBase10IntegerField:
    return StrictBase10IntegerField(
        min_value=1, max_value=2**63 - 2, widget=forms.HiddenInput
    )


class ProgrammeHostCopyForm(ProgrammeWorkbenchForm):
    """Write deliberate host-visible copy, never private-source prefilling."""

    expected_version = _version()
    role = forms.ChoiceField(choices=(("host", "Host"), ("co_host", "Co-host")))
    title = forms.CharField(
        label="Host-visible invitation title", max_length=MAX_HOST_INVITATION_TITLE
    )
    briefing = forms.CharField(
        label="Host-visible briefing",
        required=False,
        max_length=MAX_HOST_BRIEFING,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text=(
            "Write this deliberately. "
            "Private working and review text is not copied here."
        ),
    )
    field_order: tuple[str, ...] = ("role", "title", "briefing", "reason")


class ProgrammeHostInvitationForm(ProgrammeHostCopyForm):
    """Invite one known current person by an exact, purpose-limited address."""

    recipient_email = forms.EmailField(
        label="Existing person's verified login email",
        max_length=254,
        help_text=(
            "Exact invitation address only; "
            "this does not search a directory or create an account."
        ),
    )
    field_order = ("recipient_email", "role", "title", "briefing", "reason")


class ProgrammeHostReinvitationForm(ProgrammeHostCopyForm):
    """Reinvite the exact retained relationship selected from an authorized roster."""

    expected_host_version = _version()
    field_order = ("role", "title", "briefing", "reason")


class ProgrammeHostRemovalForm(ProgrammeWorkbenchForm):
    """Confirm a reasoned organizer removal, not a fabricated personal withdrawal."""

    expected_version = _version()
    expected_host_version = _version()
    confirm_removal = forms.BooleanField(
        label="Remove this hosting relationship and clear its current availability",
    )
    field_order = ("confirm_removal", "reason")


class ProgrammeHostPersonalForm(StrictInputForm):
    """Preserve own original source versions without collecting a private reason."""

    expected_item_version = _version()
    expected_host_version = _version()
    idempotency_key = CanonicalUUIDField(widget=forms.HiddenInput)


class ProgrammeHostResponseForm(ProgrammeHostPersonalForm):
    """Record only the authenticated person's exact invitation response."""

    invitation_sequence = _version()
    response = forms.ChoiceField(
        choices=(
            ("", "Choose your response"),
            ("confirm", "Confirm my hosting"),
            ("decline", "Decline this invitation"),
            ("withdraw", "Withdraw my confirmed hosting"),
        )
    )


class ProgrammeHostAvailabilityForm(ProgrammeHostPersonalForm):
    """Choose draft or explicit sharing for a complete purpose-owned replacement."""

    expected_edition_version = _version()
    state = forms.ChoiceField(
        choices=(
            ("", "Choose how to save these periods"),
            ("draft", "Save privately — not shared with organizers"),
            ("shared", "Share this complete availability with Programme"),
        ),
        help_text=(
            "Sharing an empty set means explicitly unavailable. "
            "A private draft is not shared."
        ),
    )


class ProgrammeHostAvailabilityWithdrawalForm(ProgrammeHostPersonalForm):
    """Clear current exact periods as a personal privacy exit, with no reason field."""

    confirm_withdrawal = forms.BooleanField(
        label=(
            "Withdraw my availability for this item and clear its current exact periods"
        ),
    )


class ProgrammeHostLocalMinuteField(forms.Field):
    """Resolve native local-minute controls in the explicitly displayed edition zone."""

    def __init__(self, *, zone_name: str, **kwargs: Any) -> None:
        """Configure a native minute control using an Events-owned IANA zone.

        Parameters
        ----------
        zone_name : str
            Current independently resolved edition zone.
        **kwargs : Any
            Standard Django field options, including the visible label.
        """
        self.zone = ZoneInfo(zone_name)
        super().__init__(
            widget=forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M",
                attrs={"type": "datetime-local", "step": "60"},
            ),
            **kwargs,
        )

    def to_python(self, value: object) -> datetime | None:
        """Reject invalid, nonexistent and ambiguous local minutes without guessing.

        Parameters
        ----------
        value : object
            Untrusted native control value.

        Returns
        -------
        datetime | None
            Exact UTC minute, or no optional value.

        Raises
        ------
        forms.ValidationError
            If the value is malformed, nonexistent or ambiguous in the edition zone.
        """
        if value in self.empty_values:
            return None
        if not isinstance(value, str) or _MINUTE.fullmatch(value) is None:
            raise forms.ValidationError("Enter an exact local date and minute.")
        try:
            local = datetime.fromisoformat(value)
            choices = {
                aware.astimezone(UTC)
                for fold in (0, 1)
                if (aware := local.replace(tzinfo=self.zone, fold=fold))
                .astimezone(UTC)
                .astimezone(self.zone)
                .replace(tzinfo=None)
                == local
            }
        except (ValueError, OverflowError) as error:
            raise forms.ValidationError(
                "Enter a representable local minute."
            ) from error
        if len(choices) != 1:
            raise forms.ValidationError(
                "This minute is missing or repeated during a clock change. "
                "Choose an unambiguous local minute.",
                code="programme_host_local_minute_ambiguous",
            )
        return choices.pop()

    def prepare_value(self, value: object) -> object:
        """Display current stored periods in the explicit edition zone.

        Parameters
        ----------
        value : object
            Stored aware instant or original bound form text.

        Returns
        -------
        object
            Edition-local minute text, or unchanged original input.
        """
        if isinstance(value, datetime):
            return value.astimezone(self.zone).strftime("%Y-%m-%dT%H:%M")
        return value


class ProgrammeHostPeriodForm(forms.Form):
    """One explicit availability interval, never a general calendar record."""

    kind = forms.ChoiceField(
        choices=(("available", "Available"), ("preferred", "Preferred")),
        initial="available",
    )

    def __init__(self, *args: Any, zone_name: str, **kwargs: Any) -> None:
        """Bind both native time controls to the independently resolved edition zone.

        Parameters
        ----------
        *args : Any
            Standard Django form arguments.
        zone_name : str
            Events-owned IANA zone for both endpoints.
        **kwargs : Any
            Formset binding and initial values.
        """
        super().__init__(*args, **kwargs)
        self.fields["starts_at"] = ProgrammeHostLocalMinuteField(
            zone_name=zone_name, label="Start"
        )
        self.fields["ends_at"] = ProgrammeHostLocalMinuteField(
            zone_name=zone_name, label="End"
        )
        self.order_fields(("starts_at", "ends_at", "kind"))


class ProgrammeHostPeriodFormSet(BaseFormSet):  # type: ignore[type-arg]
    """Use explicit removal language for the complete replacement decision."""

    def add_fields(self, form: forms.Form, index: int | None) -> None:
        """Label deletion as a pending change, not immediate history erasure.

        Parameters
        ----------
        form : forms.Form
            Period row receiving its standard deletion control.
        index : int | None
            Concrete row number, or no number for the empty template.
        """
        super().add_fields(form, index)
        form.fields["DELETE"].label = "Remove this period from the saved set"


ProgrammeHostAvailabilityFormSet = formset_factory(
    ProgrammeHostPeriodForm,
    formset=ProgrammeHostPeriodFormSet,
    extra=1,
    can_delete=True,
    max_num=MAX_HOST_AVAILABILITY_PERIODS,
    validate_max=True,
    absolute_max=MAX_HOST_AVAILABILITY_PERIODS,
)
