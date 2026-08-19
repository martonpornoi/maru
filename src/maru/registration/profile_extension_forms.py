"""Strict browser forms for governed profile-extension value revisions."""

from __future__ import annotations

import re
from typing import Any, ClassVar
from uuid import uuid4

from django import forms

from maru.core.forms import (
    CanonicalUUIDField,
    StrictBase10IntegerField,
    StrictInputForm,
)
from maru.registration.models import QuestionFieldType
from maru.registration.profile_extension_values import (
    MAX_STAFF_REASON_LENGTH,
    ProfileExtensionValueFieldProjection,
)

MAX_SHORT_PROFILE_VALUE_LENGTH = 500
MAX_LONG_PROFILE_VALUE_LENGTH = 4_000
MAX_PROFILE_VALUE_CHOICES = 64
MIN_SIGNED_32_BIT_INTEGER = -(2**31)
MAX_SIGNED_32_BIT_INTEGER = (2**31) - 1
_STRICT_SIGNED_BASE10 = re.compile(r"(?:0|-?[1-9][0-9]*)\Z")
_MAX_SIGNED_BASE10_DIGITS = 11


class StrictSignedBase10IntegerField(forms.Field):
    """Accept one canonical signed base-10 integer inside explicit bounds."""

    default_error_messages: ClassVar[dict[str, Any]] = {
        "invalid": "Enter a whole number using canonical base-10 digits.",
    }

    def __init__(
        self,
        *args: Any,
        min_value: int = MIN_SIGNED_32_BIT_INTEGER,
        max_value: int = MAX_SIGNED_32_BIT_INTEGER,
        **kwargs: Any,
    ) -> None:
        """Initialize the StrictSignedBase10IntegerField instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        min_value : int, default=MIN_SIGNED_32_BIT_INTEGER
            The min value evaluated while strict signed base10 integer field.
        max_value : int, default=MAX_SIGNED_32_BIT_INTEGER
            The max value evaluated while strict signed base10 integer field.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        super().__init__(*args, **kwargs)
        self.min_value = min_value
        self.max_value = max_value

    def to_python(self, value: object) -> int | None:
        """Convert submitted input to its normalized Python representation.

        Parameters
        ----------
        value : object
            The untrusted input to normalize, validate, or compare.

        Returns
        -------
        int | None
            The canonical Python representation, or `None` for empty input.

        Raises
        ------
        forms.ValidationError
            If the submitted state or input violates a domain invariant.
        """
        if value in self.empty_values:
            return None
        if (
            not isinstance(value, str)
            or len(value) > _MAX_SIGNED_BASE10_DIGITS
            or _STRICT_SIGNED_BASE10.fullmatch(value) is None
        ):
            raise forms.ValidationError(
                self.error_messages["invalid"],
                code="invalid",
            )
        parsed = int(value, 10)
        if not self.min_value <= parsed <= self.max_value:
            raise forms.ValidationError(
                "Enter a signed 32-bit whole number.",
                code="out_of_range",
            )
        return parsed


def _boolean_value(value: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise forms.ValidationError("Choose yes or no.", code="invalid")


def _value_initial(field: ProfileExtensionValueFieldProjection) -> object:
    value = field.current_value
    if field.field_type == QuestionFieldType.BOOLEAN:
        if value is True:
            return "true"
        if value is False:
            return "false"
        return ""
    return value if value is not None else ""


def _value_form_field(
    field: ProfileExtensionValueFieldProjection,
) -> forms.Field:
    if field.field_type == QuestionFieldType.SHORT_TEXT:
        return forms.CharField(
            label=field.label,
            help_text=field.help_text,
            required=field.required,
            max_length=MAX_SHORT_PROFILE_VALUE_LENGTH,
            strip=True,
        )
    if field.field_type == QuestionFieldType.LONG_TEXT:
        return forms.CharField(
            label=field.label,
            help_text=field.help_text,
            required=field.required,
            max_length=MAX_LONG_PROFILE_VALUE_LENGTH,
            strip=True,
            widget=forms.Textarea(attrs={"rows": 5}),
        )
    if field.field_type == QuestionFieldType.BOOLEAN:
        return forms.TypedChoiceField(
            label=field.label,
            help_text=field.help_text,
            required=field.required,
            choices=(("", "Choose one"), ("true", "Yes"), ("false", "No")),
            coerce=_boolean_value,
            empty_value=None,
        )
    if field.field_type == QuestionFieldType.INTEGER:
        return StrictSignedBase10IntegerField(
            label=field.label,
            help_text=field.help_text,
            required=field.required,
        )
    if field.field_type == QuestionFieldType.SINGLE_CHOICE:
        return forms.TypedChoiceField(
            label=field.label,
            help_text=field.help_text,
            required=field.required,
            choices=(("", "Choose one"), *((value, value) for value in field.options)),
            coerce=str,
            empty_value=None,
        )
    if field.field_type == QuestionFieldType.MULTIPLE_CHOICE:
        return forms.MultipleChoiceField(
            label=field.label,
            help_text=field.help_text,
            required=field.required,
            choices=tuple((value, value) for value in field.options),
            widget=forms.CheckboxSelectMultiple,
        )
    raise ValueError("Unsupported profile-extension field type.")


class ProfileExtensionValueForm(StrictInputForm):
    """Closed attendee command input for one route-selected field."""

    value = forms.Field()
    expected_sequence = StrictBase10IntegerField(
        min_value=0,
        max_value=2_147_483_647,
        widget=forms.HiddenInput,
    )
    retry_key = CanonicalUUIDField(widget=forms.HiddenInput)

    def __init__(
        self,
        *args: Any,
        profile_field: ProfileExtensionValueFieldProjection,
        **kwargs: Any,
    ) -> None:
        """Initialize the ProfileExtensionValueForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        profile_field : ProfileExtensionValueFieldProjection
            The profile field evaluated while profile extension value form.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        self.profile_field = profile_field
        initial = dict(kwargs.pop("initial", {}) or {})
        initial.setdefault("value", _value_initial(profile_field))
        initial.setdefault("expected_sequence", profile_field.current_sequence)
        initial.setdefault("retry_key", uuid4())
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        self.fields["value"] = _value_form_field(profile_field)
        self.order_fields(("value", "expected_sequence", "retry_key"))

    def clean_value(self) -> object:
        """Validate and normalize the value field.

        Returns
        -------
        object
            The validated and normalized value.

        Raises
        ------
        forms.ValidationError
            If the submitted state or input violates a domain invariant.
        """
        value = self.cleaned_data["value"]
        if (
            self.profile_field.field_type == QuestionFieldType.MULTIPLE_CHOICE
            and isinstance(value, list)
            and (
                len(value) > MAX_PROFILE_VALUE_CHOICES or len(value) != len(set(value))
            )
        ):
            raise forms.ValidationError(
                "Choose no more than 64 available options without duplicates.",
                code="invalid_choice_cardinality",
            )
        return value


class StaffProfileExtensionValueForm(ProfileExtensionValueForm):
    """Closed staff command input with one mandatory, value-free reason."""

    reason = forms.CharField(
        max_length=MAX_STAFF_REASON_LENGTH,
        strip=True,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Required evidence for a registration-staff change.",
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the StaffProfileExtensionValueForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        super().__init__(*args, **kwargs)
        self.order_fields(("value", "reason", "expected_sequence", "retry_key"))


__all__ = [
    "ProfileExtensionValueForm",
    "StaffProfileExtensionValueForm",
    "StrictSignedBase10IntegerField",
]
