"""Locale-independent, directly typed civil date and time browser inputs."""

from __future__ import annotations

import re
from typing import Any

from django import forms

_LOCAL_TIME = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}(?::[0-9]{2})?\Z"
)


_MINUTE_TEXT_LENGTH = 16
_SECOND_TEXT_LENGTH = 19


class ISODateInput(forms.DateInput):
    """Display a directly editable YYYY-MM-DD without browser locale controls."""

    input_type = "text"

    def __init__(self, attrs: dict[str, Any] | None = None, **kwargs: Any) -> None:
        """Keep a fixed display while retaining caller accessibility attributes.

        Parameters
        ----------
        attrs : dict[str, Any] | None, default=None
            Additional HTML attributes for the field.
        **kwargs : Any
            Framework options; legacy format yields to the shared ISO display.
        """
        kwargs.pop("format", None)
        attributes = {
            **(attrs or {}),
            "placeholder": "YYYY-MM-DD",
            "autocomplete": "off",
        }
        attributes.pop("type", None)
        attributes.pop("step", None)
        super().__init__(attrs=attributes, format="%Y-%m-%d", **kwargs)


class ISODateTimeInput(forms.DateTimeInput):
    """Type 24-hour civil time while preserving each owning field's precision."""

    input_type = "text"

    def __init__(self, attrs: dict[str, Any] | None = None, **kwargs: Any) -> None:
        """Use a common visible local-time format with seconds.

        Parameters
        ----------
        attrs : dict[str, Any] | None, default=None
            Additional HTML attributes for the field.
        **kwargs : Any
            Framework options; legacy format yields to the shared ISO display.
        """
        kwargs.pop("format", None)
        attributes = {
            **(attrs or {}),
            "placeholder": "YYYY-MM-DD HH:mm:ss",
            "autocomplete": "off",
        }
        attributes.pop("type", None)
        attributes.pop("step", None)
        super().__init__(attrs=attributes, format="%Y-%m-%d %H:%M:%S", **kwargs)

    def format_value(self, value: Any) -> str | None:
        """Redisplay both canonical transport and typed civil strings consistently.

        Parameters
        ----------
        value : Any
            Prepared field value, including invalid input retained after an error.

        Returns
        -------
        str | None
            ISO display text, leaving invalid input untouched.
        """
        if isinstance(value, str) and _LOCAL_TIME.fullmatch(value):
            display = value.replace("T", " ")
            return display + ":00" if len(display) == _MINUTE_TEXT_LENGTH else display
        return super().format_value(value)

    def value_from_datadict(self, data: Any, files: Any, name: str) -> Any:
        """Adapt presentation only; owning fields still validate zone and precision.

        Parameters
        ----------
        data : Any
            Submitted browser field mapping.
        files : Any
            Submitted upload mapping.
        name : str
            Bound field name.

        Returns
        -------
        Any
            Canonical local input; nonzero seconds are never truncated.
        """
        value = super().value_from_datadict(data, files, name)
        if isinstance(value, str) and _LOCAL_TIME.fullmatch(value):
            value = value.replace(" ", "T")
            if len(value) == _SECOND_TEXT_LENGTH and value.endswith(":00"):
                value = value[:-3]
        return value
