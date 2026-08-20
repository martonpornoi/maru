"""Domain-neutral form contracts shared by controlled browser workflows."""

from __future__ import annotations

import re
from typing import Any, ClassVar
from uuid import UUID

from django import forms

MAX_REPORTED_UNKNOWN_FIELDS = 5
MAX_REPORTED_FIELD_NAME_LENGTH = 60
CANONICAL_UUID_PATTERN = (
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}\Z"
)
_CANONICAL_UUID = re.compile(CANONICAL_UUID_PATTERN)
_MAX_STRICT_BASE10_DIGITS = 19


class StrictBase10IntegerField(forms.Field):
    """Accept one canonical, non-negative base-10 integer string."""

    default_error_messages: ClassVar[dict[str, Any]] = {
        "invalid": "Enter a whole number using base-10 digits only.",
    }

    def __init__(
        self,
        *args: Any,
        min_value: int = 0,
        max_value: int | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the StrictBase10IntegerField instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        min_value : int, default=0
            The min value used to configure and validate this form.
        max_value : int | None, default=None
            The max value used to configure and validate this form.
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
            or len(value) > _MAX_STRICT_BASE10_DIGITS
            or not value.isascii()
            or not value.isdecimal()
            or (len(value) > 1 and value.startswith("0"))
        ):
            raise forms.ValidationError(
                self.error_messages["invalid"],
                code="invalid",
            )
        try:
            parsed = int(value, 10)
        except ValueError as error:
            raise forms.ValidationError(
                self.error_messages["invalid"],
                code="invalid",
            ) from error
        if parsed < self.min_value or (
            self.max_value is not None and parsed > self.max_value
        ):
            if self.max_value is None:
                message = f"Enter a whole number of {self.min_value} or greater."
            else:
                message = (
                    f"Enter a whole number from {self.min_value} through "
                    f"{self.max_value}."
                )
            raise forms.ValidationError(message, code="out_of_range")
        return parsed


class CanonicalUUIDField(forms.Field):
    """Reject UUID aliases such as braces, compact form, or upper-case hex."""

    default_error_messages: ClassVar[dict[str, Any]] = {
        "invalid": "Enter a canonical lower-case UUID.",
    }

    def to_python(self, value: object) -> UUID | None:
        """Convert submitted input to its normalized Python representation.

        Parameters
        ----------
        value : object
            The untrusted input to normalize, validate, or compare.

        Returns
        -------
        UUID | None
            The canonical Python representation, or `None` for empty input.

        Raises
        ------
        forms.ValidationError
            If the submitted state or input violates a domain invariant.
        """
        if value in self.empty_values:
            return None
        if not isinstance(value, str) or _CANONICAL_UUID.fullmatch(value) is None:
            raise forms.ValidationError(
                self.error_messages["invalid"],
                code="invalid",
            )
        try:
            parsed = UUID(value)
        except ValueError as error:
            raise forms.ValidationError(
                self.error_messages["invalid"],
                code="invalid",
            ) from error
        if str(parsed) != value:
            raise forms.ValidationError(
                self.error_messages["invalid"],
                code="invalid",
            )
        return parsed


class StrictInputForm(forms.Form):
    """Reject undeclared request keys instead of silently discarding them."""

    transport_field_names = frozenset({"csrfmiddlewaretoken"})

    def clean(self) -> dict[str, Any] | None:
        """Validate and normalize the record.

        Returns
        -------
        dict[str, Any] | None
            A mapping containing the resolved clean data.

        Raises
        ------
        forms.ValidationError
            If the submitted state or input violates a domain invariant.
        """
        cleaned = super().clean()
        getlist = getattr(self.data, "getlist", None)
        if getlist is not None:
            invalid_cardinality = sorted(
                field_name
                for field_name, field in self.fields.items()
                if not isinstance(
                    field,
                    (forms.MultipleChoiceField, forms.ModelMultipleChoiceField),
                )
                and len(getlist(field_name)) > 1
            )
            if invalid_cardinality:
                visible = ", ".join(invalid_cardinality)
                raise forms.ValidationError(
                    f"Submit each single-value field at most once: {visible}.",
                    code="invalid_input_cardinality",
                )
        unknown = sorted(
            str(field_name)
            for field_name in self.data
            if field_name not in self.fields
            and field_name not in self.transport_field_names
        )
        if unknown:
            visible = ", ".join(
                field_name[:MAX_REPORTED_FIELD_NAME_LENGTH]
                for field_name in unknown[:MAX_REPORTED_UNKNOWN_FIELDS]
            )
            if len(unknown) > MAX_REPORTED_UNKNOWN_FIELDS:
                visible = (
                    f"{visible}, and {len(unknown) - MAX_REPORTED_UNKNOWN_FIELDS} more"
                )
            raise forms.ValidationError(
                f"Remove unsupported input fields: {visible}.",
                code="unknown_input_field",
            )
        return cleaned


class HttpsURLField(forms.URLField):
    """Use Django 6's secure URL default explicitly on every supported version."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the HttpsURLField instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        kwargs.setdefault("assume_scheme", "https")
        super().__init__(*args, **kwargs)
