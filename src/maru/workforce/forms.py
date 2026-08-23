"""Closed browser forms for workforce self-service and structure commands."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar, override
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from django import forms

from maru.core.forms import (
    CanonicalUUIDField,
    StrictBase10IntegerField,
    StrictInputForm,
)
from maru.workforce.models import VolunteerOpportunity
from maru.workforce.structure_inputs import (
    MAX_DEPARTMENT_DESCRIPTION_LENGTH,
    MAX_DEPARTMENT_NAME_LENGTH,
    MAX_OPPORTUNITY_DESCRIPTION_LENGTH,
    MAX_OPPORTUNITY_HEADLINE_LENGTH,
    MAX_POSITION_DESCRIPTION_LENGTH,
    MAX_POSITION_HEADCOUNT,
    MAX_POSITION_TITLE_LENGTH,
    MAX_STRUCTURE_REASON_LENGTH,
    MIN_POSITION_HEADCOUNT,
    normalize_department_description,
    normalize_department_name,
    normalize_opportunity_description,
    normalize_opportunity_headline,
    normalize_position_description,
    normalize_position_title,
    normalize_structure_reason,
    validate_exact_confirmation,
)
from maru.workforce.structure_templates import BUILTIN_STRUCTURE_TEMPLATES

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

DepartmentParentChoices = tuple[tuple[str, str], ...]
PositionTemplateChoices = tuple[tuple[str, str], ...]
PositionDepartmentChoices = tuple[tuple[str, str], ...]
PositionReportingChoices = tuple[tuple[str, str], ...]
_DATE_TIME_FORMAT = "%Y-%m-%dT%H:%M"
_LOCAL_DATE_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}\Z")


def _field_local_result(field_name: str, operation: Callable[[], str]) -> str:
    """Translate a pure dict-shaped domain error for one Django form field.

    Parameters
    ----------
    field_name : str
        The canonical field name whose policy or value is requested.
    operation : Callable[[], str]
        The callback invoked to operation.

    Returns
    -------
    str
        The normalized text for field local result.

    Raises
    ------
    forms.ValidationError
        If the submitted state or input violates a domain invariant.
    """
    try:
        return operation()
    except forms.ValidationError as error:
        field_errors = getattr(error, "error_dict", {}).get(field_name)
        if not field_errors:
            raise forms.ValidationError(
                "Review this value and try again.",
                code="structure_field_invalid",
            ) from error
        raise forms.ValidationError(field_errors) from error


class DepartmentParentSelect(forms.Select):
    """Mark a retained, concurrently unavailable selection as non-submittable."""

    unavailable_values: frozenset[str] = frozenset()

    @override
    def create_option(
        self,
        name: str,
        value: object,
        label: int | str,
        selected: bool,
        index: int,
        subindex: int | None = None,
        attrs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        option = super().create_option(
            name,
            value,
            label,
            selected,
            index,
            subindex=subindex,
            attrs=attrs,
        )
        if value is not None and str(value) in self.unavailable_values:
            option["attrs"]["disabled"] = True
        return option


class CanonicalUUIDChoiceField(CanonicalUUIDField):
    """Render a select while validating only a closed identifier allowlist."""

    widget = DepartmentParentSelect
    default_error_messages: ClassVar[dict[str, Any]] = {
        **CanonicalUUIDField.default_error_messages,
        "invalid_choice": "Choose an available Department in this edition.",
    }

    def __init__(
        self,
        *args: Any,
        choices: Iterable[tuple[str, str]] = (),
        **kwargs: Any,
    ) -> None:
        """Initialize the CanonicalUUIDChoiceField instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        choices : Iterable[tuple[str, str]], default=()
            The choices used to configure and validate this form.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        self.choices = tuple(choices)
        self.unavailable_values: frozenset[str] = frozenset()
        kwargs.setdefault("widget", self.widget(choices=self.choices))
        super().__init__(*args, **kwargs)

    def set_choices(
        self,
        choices: Iterable[tuple[str, str]],
        *,
        unavailable_values: Iterable[str] = (),
    ) -> None:
        """Set choices.

        Parameters
        ----------
        choices : Iterable[tuple[str, str]]
            The choices used to configure and validate this form.
        unavailable_values : Iterable[str], default=()
            The canonical unavailable values accepted by the versioned definition.
        """
        self.choices = tuple(choices)
        self.unavailable_values = frozenset(unavailable_values)
        self.widget.choices = self.choices
        self.widget.unavailable_values = self.unavailable_values

    def validate(self, value: UUID | None) -> None:
        """Validate the supplied data.

        Parameters
        ----------
        value : UUID | None
            The untrusted input to normalize, validate, or compare.

        Raises
        ------
        forms.ValidationError
            If the submitted state or input violates a domain invariant.
        """
        super().validate(value)
        if value is None:
            return
        allowed = {candidate for candidate, _label in self.choices if candidate}
        if str(value) not in allowed or str(value) in self.unavailable_values:
            raise forms.ValidationError(
                self.error_messages["invalid_choice"],
                code="invalid_choice",
            )


class _StructureReasonForm(StrictInputForm):
    reason = forms.CharField(
        label="Reason",
        strip=False,
        help_text=(
            "Record why this structure change is needed. This administrative "
            "rationale is retained but is not published in the hierarchy."
        ),
        widget=forms.Textarea(
            attrs={"rows": 3, "maxlength": MAX_STRUCTURE_REASON_LENGTH}
        ),
    )

    def clean_reason(self) -> str:
        return _field_local_result(
            "reason",
            lambda: normalize_structure_reason(str(self.cleaned_data["reason"])),
        )


class StructureTemplateApplicationForm(_StructureReasonForm):
    """Collect and validate structure template application input."""

    template = forms.ChoiceField(
        label="Built-in reference",
        choices=tuple(
            (identifier, "MaruCon fictional starter, version 1")
            for identifier in BUILTIN_STRUCTURE_TEMPLATES
        ),
        help_text=(
            "Copies 22 independent Departments into this edition. It creates "
            "no people, roles, authority, registration, or participation."
        ),
    )
    expected_version = StrictBase10IntegerField(
        max_value=0,
        widget=forms.HiddenInput,
    )
    confirmation_name = forms.CharField(
        label="Edition name",
        strip=False,
        help_text="Enter the current edition name exactly to copy all Departments.",
        widget=forms.TextInput(
            attrs={"autocomplete": "off", "maxlength": MAX_DEPARTMENT_NAME_LENGTH}
        ),
    )
    retry_key = CanonicalUUIDField(widget=forms.HiddenInput)

    def __init__(
        self,
        *args: Any,
        edition_name: str,
        expected_version: int,
        retry_key: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the StructureTemplateApplicationForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        edition_name : str
            The human-readable edition name shown to authorized readers.
        expected_version : int
            The aggregate version required for optimistic concurrency control.
        retry_key : UUID | None, default=None
            The stable key that makes an exact command retry idempotent.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        kwargs.setdefault("auto_id", "id_structure_template_%s")
        initial = dict(kwargs.pop("initial", {}) or {})
        initial.setdefault("template", next(iter(BUILTIN_STRUCTURE_TEMPLATES)))
        initial.setdefault("expected_version", expected_version)
        initial.setdefault("retry_key", retry_key or uuid4())
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        self.edition_name = edition_name

    def clean_confirmation_name(self) -> str:
        """Validate and normalize the confirmation name field.

        Returns
        -------
        str
            The validated and normalized confirmation name.
        """
        return _field_local_result(
            "confirmation_name",
            lambda: validate_exact_confirmation(
                str(self.cleaned_data["confirmation_name"]),
                expected=self.edition_name,
            ),
        )


class _DepartmentDetailsForm(_StructureReasonForm):
    name = forms.CharField(
        label="Department name",
        strip=False,
        help_text=(
            "Use the operational name people recognize. Executive Board is "
            "reserved for the separate governance record."
        ),
        widget=forms.TextInput(
            attrs={"autocomplete": "off", "maxlength": MAX_DEPARTMENT_NAME_LENGTH}
        ),
    )
    description = forms.CharField(
        label="Description",
        required=False,
        strip=False,
        help_text=(
            "Optional operational purpose, up to 1,000 characters. Do not add "
            "private HR or personal information."
        ),
        widget=forms.Textarea(
            attrs={"rows": 5, "maxlength": MAX_DEPARTMENT_DESCRIPTION_LENGTH}
        ),
    )
    parent_department_id = CanonicalUUIDChoiceField(
        label="Parent Department",
        required=False,
        choices=(("", "No parent — top-level Department"),),
        help_text=(
            "Choose an active Department in this edition. Nesting explains "
            "operations and never grants access. Maru places new or moved "
            "Departments after the existing Departments at that level."
        ),
    )
    expected_version = StrictBase10IntegerField(widget=forms.HiddenInput)

    def __init__(
        self,
        *args: Any,
        parent_choices: DepartmentParentChoices,
        expected_version: int,
        **kwargs: Any,
    ) -> None:
        """Initialize the _DepartmentDetailsForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        parent_choices : DepartmentParentChoices
            The departments that may be selected as the parent.
        expected_version : int
            The structure version used for optimistic concurrency control.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        initial = dict(kwargs.pop("initial", {}) or {})
        initial.setdefault("expected_version", expected_version)
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        self.set_parent_choices(parent_choices)

    def set_parent_choices(
        self,
        choices: DepartmentParentChoices,
        *,
        retain_bound_unavailable: bool = False,
    ) -> None:
        field = self.fields["parent_department_id"]
        if not isinstance(field, CanonicalUUIDChoiceField):
            raise TypeError("The Department parent field contract changed.")
        unavailable_values: tuple[str, ...] = ()
        rendered_choices = (("", "No parent — top-level Department"), *choices)
        raw_value = (
            self.data.get("parent_department_id")
            if retain_bound_unavailable and self.is_bound
            else None
        )
        available_values = {value for value, _label in rendered_choices}
        if (
            isinstance(raw_value, str)
            and raw_value
            and raw_value not in available_values
        ):
            unavailable_values = (raw_value,)
            rendered_choices = (
                *rendered_choices,
                (
                    raw_value,
                    "Previous selection unavailable — reload or choose another parent",
                ),
            )
        field.set_choices(
            rendered_choices,
            unavailable_values=unavailable_values,
        )

    def clean_name(self) -> str:
        return _field_local_result(
            "name",
            lambda: normalize_department_name(str(self.cleaned_data["name"])),
        )

    def clean_description(self) -> str:
        return _field_local_result(
            "description",
            lambda: normalize_department_description(
                str(self.cleaned_data.get("description", ""))
            ),
        )


class DepartmentCreationForm(_DepartmentDetailsForm):
    """Collect and validate department creation input."""

    retry_key = CanonicalUUIDField(widget=forms.HiddenInput)

    def __init__(
        self,
        *args: Any,
        retry_key: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the DepartmentCreationForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        retry_key : UUID | None, default=None
            The stable key that makes an exact command retry idempotent.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        kwargs.setdefault("auto_id", "id_department_create_%s")
        initial = dict(kwargs.pop("initial", {}) or {})
        initial.setdefault("retry_key", retry_key or uuid4())
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)


class DepartmentUpdateForm(_DepartmentDetailsForm):
    """Collect and validate department update input."""

    expected_version = StrictBase10IntegerField(
        min_value=1,
        widget=forms.HiddenInput,
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the DepartmentUpdateForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        kwargs.setdefault("auto_id", "id_department_update_%s")
        super().__init__(*args, **kwargs)


class DepartmentRetirementForm(_StructureReasonForm):
    """Collect and validate department retirement input."""

    expected_version = StrictBase10IntegerField(
        min_value=1,
        widget=forms.HiddenInput,
    )

    def __init__(
        self,
        *args: Any,
        expected_version: int,
        **kwargs: Any,
    ) -> None:
        """Initialize the DepartmentRetirementForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        expected_version : int
            The aggregate version required for optimistic concurrency control.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        kwargs.setdefault("auto_id", "id_department_retire_%s")
        initial = dict(kwargs.pop("initial", {}) or {})
        initial.setdefault("expected_version", expected_version)
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)


class DepartmentDeletionForm(_StructureReasonForm):
    """Collect and validate department deletion input."""

    expected_version = StrictBase10IntegerField(
        min_value=1,
        widget=forms.HiddenInput,
    )
    confirmation_name = forms.CharField(
        label="Department name",
        strip=False,
        help_text=(
            "Enter the current Department name exactly. Deletion succeeds only "
            "for a provably unused leaf and never cascades."
        ),
        widget=forms.TextInput(
            attrs={"autocomplete": "off", "maxlength": MAX_DEPARTMENT_NAME_LENGTH}
        ),
    )

    def __init__(
        self,
        *args: Any,
        expected_version: int,
        department_name: str,
        **kwargs: Any,
    ) -> None:
        """Initialize the DepartmentDeletionForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        expected_version : int
            The aggregate version required for optimistic concurrency control.
        department_name : str
            The human-readable department name shown to authorized readers.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        kwargs.setdefault("auto_id", "id_department_delete_%s")
        initial = dict(kwargs.pop("initial", {}) or {})
        initial.setdefault("expected_version", expected_version)
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        self.department_name = department_name

    def clean_confirmation_name(self) -> str:
        """Validate and normalize the confirmation name field.

        Returns
        -------
        str
            The validated and normalized confirmation name.
        """
        return _field_local_result(
            "confirmation_name",
            lambda: validate_exact_confirmation(
                str(self.cleaned_data["confirmation_name"]),
                expected=self.department_name,
            ),
        )


class PositionUUIDChoiceField(CanonicalUUIDChoiceField):
    """Validate a scoped Position-workflow selector without model leakage."""

    default_error_messages: ClassVar[dict[str, Any]] = {
        **CanonicalUUIDChoiceField.default_error_messages,
        "invalid_choice": "Choose an available option for this edition.",
    }


class WorkforceEditionLocalDateTimeField(forms.Field):
    """Parse one real, unambiguous minute in the edition time zone."""

    default_error_messages: ClassVar[dict[str, Any]] = {
        "invalid": "Enter a valid local date and time.",
        "ambiguous": (
            "Choose an unambiguous local time outside the daylight-saving change."
        ),
    }

    def __init__(self, *args: Any, zone_name: str = "UTC", **kwargs: Any) -> None:
        """Configure local-minute parsing for one IANA time zone.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to Django's form field.
        zone_name : str, default='UTC'
            IANA time-zone name used for parsing and widget display.
        **kwargs : Any
            Keyword arguments forwarded to Django's form field.
        """
        kwargs.setdefault(
            "widget",
            forms.DateTimeInput(
                format=_DATE_TIME_FORMAT,
                attrs={"type": "datetime-local", "step": "60"},
            ),
        )
        super().__init__(*args, **kwargs)
        self.zone = ZoneInfo(zone_name)

    def set_zone(self, zone_name: str) -> None:
        """Use the event edition's IANA time zone for parsing and display.

        Parameters
        ----------
        zone_name : str
            Validated IANA time-zone name owned by the event edition.
        """
        self.zone = ZoneInfo(zone_name)

    def to_python(self, value: object) -> datetime | None:
        """Return one aware instant or reject gaps and ambiguous local minutes.

        Parameters
        ----------
        value : object
            Untrusted local-minute form value.

        Returns
        -------
        datetime | None
            Aware edition-local instant, or ``None`` for an empty optional value.

        Raises
        ------
        forms.ValidationError
            If the value is malformed, nonexistent, or ambiguous in the zone.
        """
        if value in self.empty_values:
            return None
        if not isinstance(value, str) or _LOCAL_DATE_TIME.fullmatch(value) is None:
            raise forms.ValidationError(
                self.error_messages["invalid"],
                code="invalid",
            )
        try:
            first = datetime.strptime(value, _DATE_TIME_FORMAT).replace(
                tzinfo=self.zone,
                fold=0,
            )
        except ValueError as error:
            raise forms.ValidationError(
                self.error_messages["invalid"],
                code="invalid",
            ) from error
        local = first.replace(tzinfo=None)
        second = local.replace(tzinfo=self.zone, fold=1)
        first_valid = (
            first.astimezone(UTC).astimezone(self.zone).replace(tzinfo=None) == local
        )
        second_valid = (
            second.astimezone(UTC).astimezone(self.zone).replace(tzinfo=None) == local
        )
        if not first_valid and not second_valid:
            raise forms.ValidationError(
                self.error_messages["ambiguous"],
                code="nonexistent",
            )
        if first_valid and second_valid and first.utcoffset() != second.utcoffset():
            raise forms.ValidationError(
                self.error_messages["ambiguous"],
                code="ambiguous",
            )
        return first if first_valid else second

    def prepare_value(self, value: object) -> object:
        """Render stored instants in the edition's local wall time.

        Parameters
        ----------
        value : object
            Stored aware instant or an unconverted widget value.

        Returns
        -------
        object
            Local-minute text for a datetime, otherwise the original value.
        """
        if isinstance(value, datetime):
            local = value.astimezone(self.zone) if value.tzinfo else value
            return local.strftime(_DATE_TIME_FORMAT)
        return value


class PositionCreationForm(_StructureReasonForm):
    """Collect one governed Position and draft-opportunity creation request."""

    template_id = PositionUUIDChoiceField(
        label="Position template",
        choices=(),
        help_text=(
            "Choose a published, independently approved template. It pins the "
            "immutable role bundle and volunteer capacity labels."
        ),
    )
    department_id = PositionUUIDChoiceField(
        label="Department",
        choices=(),
        help_text=(
            "Choose the Position's permanent Department. Moving it later would "
            "change its exact authorization scope, so Maru keeps this choice immutable."
        ),
    )
    reports_to_id = PositionUUIDChoiceField(
        label="Reports to",
        required=False,
        choices=(("", "No reporting Position"),),
        help_text="Optional operational reporting line; this never grants access.",
    )
    title = forms.CharField(
        label="Position title",
        strip=False,
        widget=forms.TextInput(
            attrs={"autocomplete": "off", "maxlength": MAX_POSITION_TITLE_LENGTH}
        ),
    )
    description = forms.CharField(
        label="Purpose and responsibilities",
        strip=False,
        widget=forms.Textarea(
            attrs={"rows": 6, "maxlength": MAX_POSITION_DESCRIPTION_LENGTH}
        ),
        help_text=(
            "Explain the work in language organizers and applicants can understand. "
            "Do not include personal or private HR information."
        ),
    )
    headcount = StrictBase10IntegerField(
        label="Approved headcount",
        min_value=MIN_POSITION_HEADCOUNT,
        max_value=MAX_POSITION_HEADCOUNT,
        help_text="The maximum number of current or proposed holders.",
    )
    expected_version = StrictBase10IntegerField(min_value=1, widget=forms.HiddenInput)
    retry_key = CanonicalUUIDField(widget=forms.HiddenInput)

    def __init__(
        self,
        *args: Any,
        template_choices: PositionTemplateChoices,
        department_choices: PositionDepartmentChoices,
        reporting_choices: PositionReportingChoices,
        expected_version: int,
        retry_key: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Bind exact-edition choices and fresh command controls.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the strict form.
        template_choices : PositionTemplateChoices
            Bounded published templates valid for the organization.
        department_choices : PositionDepartmentChoices
            Active Departments in the exact edition.
        reporting_choices : PositionReportingChoices
            Current same-edition Positions available as reporting parents.
        expected_version : int
            Structure aggregate version rendered with the form.
        retry_key : UUID | None, default=None
            Stable creation retry identifier, generated when omitted.
        **kwargs : Any
            Keyword arguments forwarded to the strict form.
        """
        kwargs.setdefault("auto_id", "id_position_create_%s")
        initial = dict(kwargs.pop("initial", {}) or {})
        initial.setdefault("expected_version", expected_version)
        initial.setdefault("retry_key", retry_key or uuid4())
        initial.setdefault("headcount", 1)
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        self._set_choices("template_id", template_choices)
        self._set_choices("department_id", department_choices)
        self._set_choices(
            "reports_to_id",
            (("", "No reporting Position"), *reporting_choices),
        )

    def _set_choices(
        self,
        field_name: str,
        choices: tuple[tuple[str, str], ...],
    ) -> None:
        field = self.fields[field_name]
        if not isinstance(field, PositionUUIDChoiceField):
            raise TypeError("The Position selector contract changed.")
        field.set_choices(choices)

    def clean_title(self) -> str:
        """Normalize the human-readable Position title.

        Returns
        -------
        str
            Bounded canonical title retained by the command.
        """
        return _field_local_result(
            "title",
            lambda: normalize_position_title(str(self.cleaned_data["title"])),
        )

    def clean_description(self) -> str:
        """Normalize the Position purpose and responsibilities.

        Returns
        -------
        str
            Bounded canonical applicant- and organizer-facing description.
        """
        return _field_local_result(
            "description",
            lambda: normalize_position_description(
                str(self.cleaned_data["description"])
            ),
        )


class PositionUpdateForm(_StructureReasonForm):
    """Collect the complete editable details of one current Position."""

    reports_to_id = PositionUUIDChoiceField(
        label="Reports to",
        required=False,
        choices=(("", "No reporting Position"),),
        help_text="Optional operational reporting line; this never grants access.",
    )
    title = forms.CharField(
        label="Position title",
        strip=False,
        widget=forms.TextInput(
            attrs={"autocomplete": "off", "maxlength": MAX_POSITION_TITLE_LENGTH}
        ),
    )
    description = forms.CharField(
        label="Purpose and responsibilities",
        strip=False,
        widget=forms.Textarea(
            attrs={"rows": 6, "maxlength": MAX_POSITION_DESCRIPTION_LENGTH}
        ),
    )
    headcount = StrictBase10IntegerField(
        label="Approved headcount",
        min_value=MIN_POSITION_HEADCOUNT,
        max_value=MAX_POSITION_HEADCOUNT,
    )
    expected_version = StrictBase10IntegerField(min_value=1, widget=forms.HiddenInput)

    def __init__(
        self,
        *args: Any,
        reporting_choices: PositionReportingChoices,
        expected_version: int,
        **kwargs: Any,
    ) -> None:
        """Bind a complete Position replacement to current reporting choices.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the strict form.
        reporting_choices : PositionReportingChoices
            Acyclic current same-edition reporting candidates.
        expected_version : int
            Structure aggregate version rendered with the form.
        **kwargs : Any
            Keyword arguments forwarded to the strict form.

        Raises
        ------
        TypeError
            If the declared reporting field no longer has the scoped type.
        """
        kwargs.setdefault("auto_id", "id_position_update_%s")
        initial = dict(kwargs.pop("initial", {}) or {})
        initial.setdefault("expected_version", expected_version)
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        field = self.fields["reports_to_id"]
        if not isinstance(field, PositionUUIDChoiceField):
            raise TypeError("The Position reporting selector contract changed.")
        field.set_choices((("", "No reporting Position"), *reporting_choices))

    def clean_title(self) -> str:
        """Normalize the replacement Position title.

        Returns
        -------
        str
            Bounded canonical title retained by the command.
        """
        return _field_local_result(
            "title",
            lambda: normalize_position_title(str(self.cleaned_data["title"])),
        )

    def clean_description(self) -> str:
        """Normalize the replacement purpose and responsibilities.

        Returns
        -------
        str
            Bounded canonical description retained by the command.
        """
        return _field_local_result(
            "description",
            lambda: normalize_position_description(
                str(self.cleaned_data["description"])
            ),
        )


class PositionOpportunityForm(_StructureReasonForm):
    """Collect the publication settings paired with one Position."""

    status = forms.ChoiceField(
        label="Publication status",
        choices=VolunteerOpportunity.Status.choices,
        help_text=(
            "Draft is private. Published may accept applications inside the "
            "date window. Closed remains historical; Withdrawn is final."
        ),
    )
    headline = forms.CharField(
        label="Applicant-facing headline",
        strip=False,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
                "maxlength": MAX_OPPORTUNITY_HEADLINE_LENGTH,
            }
        ),
    )
    description = forms.CharField(
        label="Applicant-facing description",
        strip=False,
        widget=forms.Textarea(
            attrs={"rows": 6, "maxlength": MAX_OPPORTUNITY_DESCRIPTION_LENGTH}
        ),
    )
    applications_open_at = WorkforceEditionLocalDateTimeField(
        label="Applications open",
        required=False,
        help_text="Optional. Blank means publication is effective immediately.",
    )
    applications_close_at = WorkforceEditionLocalDateTimeField(
        label="Applications close",
        required=False,
        help_text="Optional. Blank means no scheduled closing time.",
    )
    visible_when_filled = forms.BooleanField(
        label="Keep this opportunity visible when headcount is filled",
        required=False,
        help_text=(
            "The public page will say applications are not being accepted; "
            "the role remains understandable to future volunteers."
        ),
    )
    expected_version = StrictBase10IntegerField(min_value=1, widget=forms.HiddenInput)

    def __init__(
        self,
        *args: Any,
        edition_time_zone: str,
        expected_version: int,
        **kwargs: Any,
    ) -> None:
        """Bind opportunity fields to the edition zone and structure version.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the strict form.
        edition_time_zone : str
            Event edition IANA zone used for local-minute inputs.
        expected_version : int
            Structure aggregate version rendered with the form.
        **kwargs : Any
            Keyword arguments forwarded to the strict form.

        Raises
        ------
        TypeError
            If either declared time field no longer has the zone-aware type.
        """
        kwargs.setdefault("auto_id", "id_position_opportunity_%s")
        initial = dict(kwargs.pop("initial", {}) or {})
        initial.setdefault("expected_version", expected_version)
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        for field_name in ("applications_open_at", "applications_close_at"):
            field = self.fields[field_name]
            if not isinstance(field, WorkforceEditionLocalDateTimeField):
                raise TypeError("The opportunity time-zone contract changed.")
            field.set_zone(edition_time_zone)
        self.fields["applications_open_at"].help_text = (
            f"Optional, in {edition_time_zone}. Blank means publication is "
            "effective immediately."
        )
        self.fields[
            "applications_close_at"
        ].help_text = (
            f"Optional, in {edition_time_zone}. Blank means no scheduled closing time."
        )

    def clean_headline(self) -> str:
        """Normalize the applicant-facing headline.

        Returns
        -------
        str
            Bounded canonical opportunity headline.
        """
        return _field_local_result(
            "headline",
            lambda: normalize_opportunity_headline(str(self.cleaned_data["headline"])),
        )

    def clean_description(self) -> str:
        """Normalize the applicant-facing description.

        Returns
        -------
        str
            Bounded canonical opportunity description.
        """
        return _field_local_result(
            "description",
            lambda: normalize_opportunity_description(
                str(self.cleaned_data["description"])
            ),
        )

    def clean(self) -> dict[str, Any]:
        """Validate the optional publication window.

        Returns
        -------
        dict[str, Any]
            Cleaned complete opportunity replacement with ordered aware times.
        """
        cleaned = super().clean() or {}
        opens = cleaned.get("applications_open_at")
        closes = cleaned.get("applications_close_at")
        if opens is not None and closes is not None and closes <= opens:
            self.add_error("applications_close_at", "Closing must be after opening.")
        return cleaned


class PositionClosureForm(_StructureReasonForm):
    """Collect exact confirmation for one dependency-safe Position closure."""

    expected_version = StrictBase10IntegerField(min_value=1, widget=forms.HiddenInput)
    confirmation_name = forms.CharField(
        label="Position title",
        strip=False,
        help_text=(
            "Enter the current Position title exactly. Maru will preserve the "
            "record and close its opportunity; nothing is deleted."
        ),
        widget=forms.TextInput(
            attrs={"autocomplete": "off", "maxlength": MAX_POSITION_TITLE_LENGTH}
        ),
    )

    def __init__(
        self,
        *args: Any,
        expected_version: int,
        position_title: str,
        **kwargs: Any,
    ) -> None:
        """Bind exact-title confirmation to the current Position version.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the strict form.
        expected_version : int
            Structure aggregate version rendered with the form.
        position_title : str
            Exact current title required for protected closure.
        **kwargs : Any
            Keyword arguments forwarded to the strict form.
        """
        kwargs.setdefault("auto_id", "id_position_close_%s")
        initial = dict(kwargs.pop("initial", {}) or {})
        initial.setdefault("expected_version", expected_version)
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        self.position_title = position_title

    def clean_confirmation_name(self) -> str:
        """Require the exact current Position title.

        Returns
        -------
        str
            Exact confirmed title accepted by the closure command.
        """
        return _field_local_result(
            "confirmation_name",
            lambda: validate_exact_confirmation(
                str(self.cleaned_data["confirmation_name"]),
                expected=self.position_title,
            ),
        )


class VolunteerApplicationForm(forms.Form):
    """Collect and validate volunteer application input."""

    motivation = forms.CharField(
        label="Why would you like to help in this position?",
        max_length=2_000,
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text=(
            "Describe relevant interests or experience. Do not include medical, "
            "conduct, identity-document, or unrelated sensitive information."
        ),
    )


class OnboardingDocumentUploadForm(forms.Form):
    """Collect and validate onboarding document upload input."""

    document = forms.FileField(
        label="Signed PDF",
        help_text=(
            "PDF only, up to the limit shown for the request. The file remains "
            "private until retention removes it."
        ),
    )
