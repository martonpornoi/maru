"""Closed browser forms for workforce self-service and structure commands."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, override
from uuid import UUID, uuid4

from django import forms

from maru.core.forms import (
    CanonicalUUIDField,
    StrictBase10IntegerField,
    StrictInputForm,
)
from maru.workforce.structure_inputs import (
    MAX_DEPARTMENT_DESCRIPTION_LENGTH,
    MAX_DEPARTMENT_NAME_LENGTH,
    MAX_STRUCTURE_REASON_LENGTH,
    normalize_department_description,
    normalize_department_name,
    normalize_structure_reason,
    validate_exact_confirmation,
)
from maru.workforce.structure_templates import BUILTIN_STRUCTURE_TEMPLATES

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

DepartmentParentChoices = tuple[tuple[str, str], ...]


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
            (identifier, "Awoostria reference, version 1")
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
