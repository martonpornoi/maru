"""Locale-independent date and 24-hour time controls for application deadlines."""

from __future__ import annotations

from typing import Any

from django import forms


class EditionLocalMinuteWidget(forms.MultiWidget):
    """Keep the native calendar while making the clock explicitly 00:00-23:59."""

    template_name = "applications/widgets/local_minute.html"
    use_fieldset = False
    widgets_names: list[str]

    def __init__(self, *, label: str) -> None:
        """Configure two labelled controls without browser-dependent clock rendering.

        Parameters
        ----------
        label : str
            Deadline name used to distinguish the controls for assistive technology.
        """
        self.label = label
        super().__init__(
            widgets={
                "date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
                "time": forms.TextInput(
                    attrs={
                        "placeholder": "HH:MM",
                        "pattern": "([01][0-9]|2[0-3]):[0-5][0-9]",
                        "maxlength": "5",
                        "size": "5",
                    }
                ),
            }
        )

    def decompress(self, value: Any) -> list[Any]:
        """Split the field's already localized minute for initial and error rendering.

        Parameters
        ----------
        value : Any
            Canonical local-minute string prepared by the owning field.

        Returns
        -------
        list[Any]
            Date and clock text, retaining malformed clock text for correction.
        """
        if isinstance(value, str) and "T" in value:
            return value.split("T", 1)
        return [value, ""]

    def id_for_label(self, id_: str) -> str:
        """Focus the calendar when the existing deadline label is activated.

        Parameters
        ----------
        id_ : str
            Base identifier assigned to the combined field.

        Returns
        -------
        str
            Identifier of the first visible control, or an empty identifier.
        """
        return f"{id_}_0" if id_ else ""

    def get_context(
        self, name: str, value: Any, attrs: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Give each date and clock a unique, deadline-specific accessible name.

        Parameters
        ----------
        name : str
            Form field's transport name.
        value : Any
            Initial or submitted local-minute value.
        attrs : dict[str, Any] | None
            Framework-supplied identifiers, requirements and error descriptions.

        Returns
        -------
        dict[str, Any]
            Template context with both labelled native form controls.
        """
        context = super().get_context(name, value, attrs)
        widget = context["widget"]
        widget["label"] = self.label
        for child, label in zip(
            widget["subwidgets"], ("Date", "Time (24-hour)"), strict=True
        ):
            child["label"] = label
            child["attrs"]["aria-label"] = f"{self.label}: {label}"
        return context

    def value_from_datadict(self, data: Any, files: Any, name: str) -> Any:
        """Join visible controls without interpreting or normalizing the local time.

        Parameters
        ----------
        data : Any
            Submitted form values, validated separately for exact cardinality.
        files : Any
            Framework file mapping; this widget never reads uploaded files.
        name : str
            Deadline's canonical transport name.

        Returns
        -------
        Any
            Local-minute text for the existing zone-aware validator. Earlier scalar
            submissions remain supported only when split controls are absent.
        """
        if not any(f"{name}{suffix}" in data for suffix in self.widgets_names):
            return data.get(name)
        date, time = super().value_from_datadict(data, files, name)
        if not date and not time:
            return ""
        if not isinstance(date, str) or not isinstance(time, str):
            return None if date is None and time is None else "invalid"
        return f"{date}T{time}"

    def value_omitted_from_data(self, data: Any, files: Any, name: str) -> bool:
        """Distinguish omitted deadlines from an explicitly submitted empty value.

        Parameters
        ----------
        data : Any
            Submitted form values.
        files : Any
            Framework file mapping, unused by these text controls.
        name : str
            Deadline's canonical transport name.

        Returns
        -------
        bool
            Whether neither a scalar nor either split control was submitted.
        """
        return name not in data and super().value_omitted_from_data(data, files, name)
