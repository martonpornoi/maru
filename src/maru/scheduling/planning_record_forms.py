"""Strict explicit lifecycle, history and physical-hold planning controls."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django import forms
from django.core.exceptions import ValidationError

from maru.core.forms import CanonicalUUIDField, StrictBase10IntegerField

from .catalogs import MAX_OCCURRENCES, MAX_TITLE_LENGTH, SchedulingOperation
from .inputs import SchedulingOccurrenceInput, normalized_text
from .planning_forms import PlanningCommandForm, _PlanningChoiceField, _version_field
from .reservation_commands import SchedulingReservationInput

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .planning_forms import PlanningChoices

_SUPPORTED = frozenset(
    {
        SchedulingOperation.DAY_RETIRE,
        SchedulingOperation.OCCURRENCE_CREATE,
        SchedulingOperation.OCCURRENCE_REVISE,
        SchedulingOperation.OCCURRENCE_RETIRE,
        SchedulingOperation.CANDIDATE_CREATE,
        SchedulingOperation.CANDIDATE_COPY,
        SchedulingOperation.CANDIDATE_RESTORE,
        SchedulingOperation.CANDIDATE_ARCHIVE,
        SchedulingOperation.PLACEMENT_REMOVE,
        SchedulingOperation.EVALUATION_RECORD,
        SchedulingOperation.WARNING_ACKNOWLEDGE,
        SchedulingOperation.RESERVATION_REPLACE,
        SchedulingOperation.RESERVATION_CANCEL,
    }
)
_INITIAL_CONTROL = {
    SchedulingOperation.CANDIDATE_CREATE,
    SchedulingOperation.OCCURRENCE_CREATE,
}
_OCCURRENCE_INPUT = {
    SchedulingOperation.OCCURRENCE_CREATE,
    SchedulingOperation.OCCURRENCE_REVISE,
}
_RESERVATION = {
    SchedulingOperation.RESERVATION_REPLACE,
    SchedulingOperation.RESERVATION_CANCEL,
}
_CONFIRMATION = {
    SchedulingOperation.DAY_RETIRE: (
        "Retire this service day; retain its history. Room holds stay unchanged."
    ),
    SchedulingOperation.OCCURRENCE_RETIRE: (
        "Retire this occurrence; retain its history. Room holds stay unchanged."
    ),
    SchedulingOperation.CANDIDATE_RESTORE: (
        "Restore this exact revision as a new draft revision. "
        "Room holds stay unchanged."
    ),
    SchedulingOperation.CANDIDATE_ARCHIVE: (
        "Archive this draft permanently. It can be copied; room holds stay unchanged."
    ),
    SchedulingOperation.PLACEMENT_REMOVE: (
        "Unplace this occurrence in this draft only. Any room hold stays unchanged."
    ),
    SchedulingOperation.RESERVATION_REPLACE: (
        "Request this physical hold, replacing the selected old hold if present. "
        "This does not approve the room or publish the programme."
    ),
    SchedulingOperation.RESERVATION_CANCEL: (
        "Cancel the selected physical hold. The draft and reservation history remain."
    ),
}
_IDENTIFIERS = {
    SchedulingOperation.DAY_RETIRE: ("day_id",),
    SchedulingOperation.OCCURRENCE_REVISE: ("occurrence_id",),
    SchedulingOperation.OCCURRENCE_RETIRE: ("occurrence_id",),
    SchedulingOperation.CANDIDATE_COPY: ("source_revision_id",),
    SchedulingOperation.CANDIDATE_RESTORE: ("candidate_id", "source_revision_id"),
    SchedulingOperation.CANDIDATE_ARCHIVE: ("candidate_id",),
    SchedulingOperation.PLACEMENT_REMOVE: ("candidate_id", "occurrence_id"),
    SchedulingOperation.EVALUATION_RECORD: ("candidate_id",),
    SchedulingOperation.WARNING_ACKNOWLEDGE: ("conflict_id",),
    SchedulingOperation.RESERVATION_REPLACE: ("candidate_id", "placement_id"),
    SchedulingOperation.RESERVATION_CANCEL: ("candidate_id", "placement_id"),
}


class PlanningRecordForm(PlanningCommandForm):
    """Bind one server-selected operation without adding a parallel domain writer.

    Only fields relevant to the selected operation are accepted. Identifiers and
    optimistic versions remain untrusted until the existing owner command runs.
    Item/group choices must already be authorized before constructing the form.
    """

    def __init__(
        self,
        *args: Any,
        operation: SchedulingOperation,
        choices: Mapping[str, PlanningChoices] | None = None,
        **kwargs: Any,
    ) -> None:
        """Configure the closed action and its complete native input fields.

        Parameters
        ----------
        *args : Any
            Ordinary Django form binding arguments.
        operation : SchedulingOperation
            Server-selected record operation, excluding day and placement editors.
        choices : Mapping[str, PlanningChoices] | None, default=None
            Independently authorized item and explicit group selections, if needed.
        **kwargs : Any
            Ordinary Django form options, including retained initial input.

        Raises
        ------
        ValueError
            If the operation is not a supported typed record action.
        """
        if (
            not isinstance(operation, SchedulingOperation)
            or operation not in _SUPPORTED
        ):
            raise ValueError("Select a supported planning record operation.")
        super().__init__(*args, **kwargs)
        self.operation = operation
        self.occurrence_intent: SchedulingOccurrenceInput | None = None
        self.reservation_intent: SchedulingReservationInput | None = None
        self.fields["action"] = forms.ChoiceField(
            choices=((operation.value, operation.value),), widget=forms.HiddenInput
        )
        for name in _IDENTIFIERS.get(operation, ()):
            self.fields[name] = CanonicalUUIDField(widget=forms.HiddenInput)
        if operation not in _RESERVATION | {SchedulingOperation.WARNING_ACKNOWLEDGE}:
            self.fields["expected_version"] = _version_field(
                initial=operation in _INITIAL_CONTROL
            )
        if operation in {
            SchedulingOperation.CANDIDATE_CREATE,
            SchedulingOperation.CANDIDATE_COPY,
        }:
            self.fields["label"] = forms.CharField(
                label="Draft name", max_length=MAX_TITLE_LENGTH
            )
        if operation in _OCCURRENCE_INPUT:
            selected = choices or {}
            self.fields["item_id"] = _PlanningChoiceField(
                label="Programme item", choices=selected.get("item_id", ())
            )
            self.fields["group_key"] = _PlanningChoiceField(
                label="Explicit occurrence group",
                choices=selected.get("group_key", ()),
                required=False,
                help_text="Leave group and sequence blank for an ungrouped occurrence.",
            )
            self.fields["group_sequence"] = StrictBase10IntegerField(
                label="Sequence in group",
                min_value=1,
                max_value=MAX_OCCURRENCES,
                required=False,
            )
        if operation in _RESERVATION:
            self.fields["candidate_version"] = _version_field()
            self.fields["previous_booking_id"] = CanonicalUUIDField(
                widget=forms.HiddenInput,
                required=operation == SchedulingOperation.RESERVATION_CANCEL,
            )
            self.fields["expected_booking_version"] = _version_field(initial=True)
            self.fields["reason"].help_text = (
                "This reason is shared with Venues. "
                "Do not include private host details."
            )
        if operation in _CONFIRMATION:
            self.fields["confirm"] = forms.ChoiceField(
                label="Confirm consequence",
                choices=(("", "Choose confirmation"), ("confirmed", "I confirm")),
                help_text=_CONFIRMATION[operation],
            )

    def clean(self) -> dict[str, Any]:
        """Build normalized owner input without resolving or mutating any records.

        Returns
        -------
        dict[str, Any]
            Strict cleaned values; invalid input remains on this bound form.
        """
        cleaned = super().clean()
        if self.errors:
            return cleaned
        try:
            if "label" in cleaned:
                cleaned["label"] = normalized_text(
                    cleaned["label"], maximum=MAX_TITLE_LENGTH
                )
            if self.operation in _OCCURRENCE_INPUT:
                self.occurrence_intent = SchedulingOccurrenceInput(
                    cleaned["item_id"], cleaned["group_key"], cleaned["group_sequence"]
                ).normalized()
            if self.operation in _RESERVATION:
                self.reservation_intent = SchedulingReservationInput(
                    cleaned["candidate_id"],
                    cleaned["candidate_version"],
                    cleaned["placement_id"],
                    cleaned["previous_booking_id"],
                    cleaned["expected_booking_version"],
                ).normalized()
        except ValidationError as error:
            self.add_error(None, error)
        return cleaned
