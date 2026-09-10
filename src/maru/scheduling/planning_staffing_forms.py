"""Native staffing intent forms; only the owning commands may change work."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django import forms
from django.core.exceptions import ValidationError

from maru.core.forms import CanonicalUUIDField, StrictBase10IntegerField
from maru.programme.staffing_inputs import (
    MAX_STAFFING_BREAK_MINUTES,
    MAX_STAFFING_HEADCOUNT,
    MAX_STAFFING_REST_MINUTES,
    ProgrammeStaffingChange,
    ProgrammeStaffingExpectation,
    ProgrammeStaffingSource,
)
from maru.workforce.programme_impact import ProgrammeStaffingAction
from maru.workforce.programme_staffing_inputs import ProgrammeStaffingBindingChange

from .planning_forms import (
    PlanningCommandForm,
    _PlanningChoiceField,
    _PlanningMinuteField,
    _version_field,
)

if TYPE_CHECKING:
    from uuid import UUID

    from .planning_forms import PlanningChoices

REQUIREMENT_ACTIONS = frozenset(
    {"staffing_create", "staffing_revise", "staffing_retire"}
)
BINDING_ACTIONS = frozenset({"staffing_preview", "staffing_apply"})
BINDING_MODES = {
    "staffing_create_work": "create",
    "staffing_link_work": "link",
    "staffing_reconcile_work": "reconcile",
    "staffing_successor_work": "successor",
}
STAFFING_MODE_LABELS = {
    "staffing": "Staffing requirements and coverage",
    "staffing_create": "Create staffing requirement",
    "staffing_revise": "Revise staffing requirement",
    "staffing_retire": "Retire staffing requirement",
    "staffing_create_work": "Create draft work",
    "staffing_link_work": "Link identical draft work",
    "staffing_reconcile_work": "Reconcile uncommitted draft work",
    "staffing_successor_work": "Create separate successor work",
    "staffing_requirement_history": "Requirement history",
    "staffing_binding_history": "Work binding history",
}
STAFFING_WRITE_MODES = REQUIREMENT_ACTIONS | BINDING_MODES.keys()


class PlanningStaffingRequirementForm(PlanningCommandForm):
    """Exact occurrence work terms or a separately confirmed retirement intent."""

    action = forms.ChoiceField(widget=forms.HiddenInput)
    requirement_id = CanonicalUUIDField(required=False, widget=forms.HiddenInput)
    expected_item_version = _version_field()
    expected_requirement_version = _version_field(initial=True)
    expected_occurrence_version = _version_field()
    expected_edition_version = _version_field()

    def __init__(
        self,
        *args: Any,
        operation: str,
        zone_name: str,
        position_choices: PlanningChoices = (),
        **kwargs: Any,
    ) -> None:
        """Declare only the selected action's explicit fields without reading owners.

        Parameters
        ----------
        *args : Any
            Ordinary Django form inputs, retaining the original pending intent.
        operation : str
            Closed create, revise or retire action selected by the native controller.
        zone_name : str
            Trusted edition zone for explicit local-minute parsing.
        position_choices : PlanningChoices, default=()
            Complete independently authorized Position labels and identifiers.
        **kwargs : Any
            Ordinary form configuration; never actor or owner authority.

        Raises
        ------
        ValueError
            If a controller requests an unsupported requirement operation.
        """
        if operation not in REQUIREMENT_ACTIONS:
            raise ValueError("Choose a closed staffing requirement action.")
        self.operation = operation
        super().__init__(*args, **kwargs)
        self.fields["action"].choices = [(operation, operation)]  # type: ignore[attr-defined]
        self.fields["requirement_id"].required = operation != "staffing_create"
        if operation == "staffing_retire":
            self.fields["confirm"] = forms.BooleanField(
                label="Retire this requirement and retain its history. "
                "Workforce work is not cancelled."
            )
            return
        self.fields.update(
            {
                "position_id": _PlanningChoiceField(
                    choices=position_choices, label="Workforce Position"
                ),
                "title": forms.CharField(max_length=160, label="Work title"),
                "location_label": forms.CharField(
                    max_length=160, label="Reporting place"
                ),
                "briefing": forms.CharField(
                    max_length=1000,
                    label="Work instructions",
                    widget=forms.Textarea(attrs={"rows": 4}),
                ),
                "supervision_note": forms.CharField(
                    max_length=500,
                    required=False,
                    label="Supervision instructions",
                    widget=forms.Textarea(attrs={"rows": 2}),
                ),
                "starts_at": _PlanningMinuteField(
                    zone_name=zone_name, label="Work starts, including preparation"
                ),
                "ends_at": _PlanningMinuteField(
                    zone_name=zone_name, label="Work ends, including teardown"
                ),
                "required_headcount": StrictBase10IntegerField(
                    min_value=1,
                    max_value=MAX_STAFFING_HEADCOUNT,
                    label="People required",
                ),
                "break_minutes": StrictBase10IntegerField(
                    max_value=MAX_STAFFING_BREAK_MINUTES,
                    label="Planned break in minutes",
                ),
                "minimum_rest_minutes": StrictBase10IntegerField(
                    max_value=MAX_STAFFING_REST_MINUTES,
                    label="Rest after work in minutes",
                ),
            }
        )

    def change(
        self, *, item_id: UUID, occurrence_id: UUID
    ) -> ProgrammeStaffingChange | None:
        """Normalize an exact owner intent without replacing submitted versions.

        Parameters
        ----------
        item_id : UUID
            Independently resolved selected Programme item, never read from this form.
        occurrence_id : UUID
            Independently resolved selected occurrence in the same item and edition.

        Returns
        -------
        ProgrammeStaffingChange | None
            Complete normalized intent or None with action-local form errors.
        """
        if not self.is_valid():
            return None
        data = self.cleaned_data
        if self.operation == "staffing_create" and (
            data["requirement_id"] is not None
            or data["expected_requirement_version"] != 0
        ):
            self.add_error(None, "Creation cannot revise an existing requirement.")
            return None
        try:
            return ProgrammeStaffingChange(
                item_id=item_id,
                occurrence_id=occurrence_id,
                requirement_id=data["requirement_id"],
                expected_item_version=data["expected_item_version"],
                expected_requirement_version=data["expected_requirement_version"],
                expected_occurrence_version=data["expected_occurrence_version"],
                expected_edition_version=data["expected_edition_version"],
                expectation=None
                if self.operation == "staffing_retire"
                else ProgrammeStaffingExpectation(
                    **{
                        name: data[name]
                        for name in ProgrammeStaffingExpectation.__dataclass_fields__
                    }
                ),
                retire=self.operation == "staffing_retire",
            ).normalized()
        except ValidationError as error:
            self.add_error(None, error)
            return None


class PlanningStaffingBindingForm(PlanningCommandForm):
    """Explicit source and work action with separate preview and deliberate apply."""

    action = forms.ChoiceField(
        choices=(
            ("staffing_preview", "Preview work impact"),
            ("staffing_apply", "Apply reviewed work request"),
        ),
        widget=forms.HiddenInput,
    )
    reason = forms.CharField(
        max_length=240,
        label="Reason shared with Workforce",
        help_text="This is retained with work decisions, "
        "not a private Programme discussion note.",
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    operation = forms.ChoiceField(
        choices=[
            ("create", "Create draft work"),
            ("link", "Link identical draft work"),
            ("reconcile", "Reconcile uncommitted draft"),
            ("successor", "Create separate successor"),
        ]
    )
    requirement_id = CanonicalUUIDField(widget=forms.HiddenInput)
    requirement_revision_id = CanonicalUUIDField(widget=forms.HiddenInput)
    requirement_version = _version_field()
    occurrence_id = CanonicalUUIDField(widget=forms.HiddenInput)
    occurrence_version = _version_field()
    candidate_id = CanonicalUUIDField(widget=forms.HiddenInput)
    candidate_revision_id = CanonicalUUIDField(widget=forms.HiddenInput)
    placement_id = CanonicalUUIDField(widget=forms.HiddenInput)
    binding_id = CanonicalUUIDField(required=False, widget=forms.HiddenInput)
    expected_binding_version = _version_field(initial=True)
    demand_id = CanonicalUUIDField(required=False)
    expected_demand_version = _version_field(initial=True)
    preview_digest = forms.RegexField(
        r"\A[0-9a-f]{64}\Z", required=False, widget=forms.HiddenInput
    )
    confirm = forms.BooleanField(
        required=False,
        label="I reviewed the impact and explicitly approve this work request "
        "and any predecessor cancellation.",
    )

    def clean(self) -> dict[str, Any]:
        """Require affirmative impact review and an exact token only for apply.

        Returns
        -------
        dict[str, Any]
            Closed normalized form values without inventing review or authority.
        """
        cleaned = super().clean()
        if cleaned.get("action") == "staffing_apply":
            if not cleaned.get("preview_digest"):
                self.add_error(
                    "preview_digest", "Preview this exact work request first."
                )
            if not cleaned.get("confirm"):
                self.add_error(
                    "confirm", "Explicitly confirm the reviewed work impact."
                )
        return cleaned

    def change(self) -> ProgrammeStaffingBindingChange | None:
        """Return the exact validated source/action without automatic draft recovery.

        Returns
        -------
        ProgrammeStaffingBindingChange | None
            Typed intent or None with retained fields and a form-local error.
        """
        if not self.is_valid():
            return None
        data = self.cleaned_data
        try:
            return ProgrammeStaffingBindingChange(
                action=ProgrammeStaffingAction(data["operation"]),
                source=ProgrammeStaffingSource(
                    **{
                        name: data[name]
                        for name in ProgrammeStaffingSource.__dataclass_fields__
                    }
                ),
                binding_id=data["binding_id"],
                expected_binding_version=data["expected_binding_version"],
                demand_id=data["demand_id"],
                expected_demand_version=data["expected_demand_version"],
            ).validated()
        except ValidationError as error:
            self.add_error(None, error)
            return None
