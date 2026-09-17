"""Strict deliberate role-request input with literal UTC minute semantics."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from django import forms

from maru.authorization.programme_role_selection import (
    MAX_PROGRAMME_ROLE_SELECTION_BYTES,
    ProgrammeRoleRequestDraft,
    _selectors,
)
from maru.core.forms import CanonicalUUIDField, StrictInputForm

if TYPE_CHECKING:
    from maru.authorization.programme_role_recipes import ProgrammeRoleRecipe


class ProgrammeRoleUTCMinuteField(forms.Field):
    """Interpret an explicitly UTC-labelled native minute, never the active zone."""

    def __init__(self, **kwargs: Any) -> None:
        """Configure a literal UTC minute control.

        Parameters
        ----------
        **kwargs : Any
            Standard field options including visible label and optional meaning.
        """
        super().__init__(
            widget=forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local", "step": "60"}
            ),
            **kwargs,
        )

    def to_python(self, value: object) -> datetime | None:
        """Parse a strict native minute and attach only the explicitly named UTC.

        Parameters
        ----------
        value : object
            Original browser input, with no inferred offset or daylight-saving fold.

        Returns
        -------
        datetime | None
            Exact UTC minute, or None for an optional empty control.

        Raises
        ------
        forms.ValidationError
            For malformed, offset-bearing or impossible date/minute input.
        """
        if value in self.empty_values:
            return None
        if (
            not isinstance(value, str)
            or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}", value)
            is None
        ):
            raise forms.ValidationError("Enter an exact UTC date and minute.")
        try:
            return datetime.fromisoformat(value).replace(tzinfo=UTC)
        except ValueError as error:
            raise forms.ValidationError("Enter a valid UTC date and minute.") from error


class ProgrammeRoleCreationForm(StrictInputForm):
    """Keep original retry/selection and deliberate confirmation separate."""

    recipe = forms.ChoiceField(label="Exact operational task", choices=())
    recipient_email = forms.EmailField(label="Recipient's known email", max_length=254)
    approver_email = forms.EmailField(
        label="Independent approver's known email", max_length=254
    )
    not_before = ProgrammeRoleUTCMinuteField(
        label="Earliest start (UTC, optional)",
        required=False,
        help_text="Blank means actual approval time; access is never backdated.",
    )
    expires_at = ProgrammeRoleUTCMinuteField(
        label="End (UTC, optional)",
        required=False,
        help_text=(
            "Blank requests unbounded access only if both controllers' "
            "authority permits it."
        ),
    )
    reason = forms.CharField(max_length=240, widget=forms.Textarea(attrs={"rows": 3}))
    idempotency_key = CanonicalUUIDField(widget=forms.HiddenInput)
    selection_proof = forms.CharField(
        required=False,
        max_length=MAX_PROGRAMME_ROLE_SELECTION_BYTES,
        strip=False,
        widget=forms.HiddenInput,
    )
    action = forms.ChoiceField(
        choices=(("preview", "Preview"), ("confirm", "Confirm")),
        widget=forms.HiddenInput,
    )
    confirmed = forms.BooleanField(
        label=(
            "I reviewed this exact recipient, approver, scope, role and interval. "
            "Submit a request only."
        )
    )

    def __init__(
        self,
        *args: Any,
        recipes: tuple[ProgrammeRoleRecipe, ...],
        confirming: bool = False,
        **kwargs: Any,
    ) -> None:
        """Offer exact admitted recipes and hide immutable terms after selection.

        Parameters
        ----------
        *args : Any
            Standard Django form input.
        recipes : tuple[ProgrammeRoleRecipe, ...]
            Current server-admitted choices, never arbitrary capability input.
        confirming : bool, default=False
            Whether the original signed preview is being deliberately submitted.
        **kwargs : Any
            Standard form options, including the original retry identity.
        """
        super().__init__(*args, **kwargs)
        self.recipes = {recipe.catalog_entry: recipe for recipe in recipes}
        self.draft: ProgrammeRoleRequestDraft | None = None
        cast("forms.ChoiceField", self.fields["recipe"]).choices = (
            ("", "Choose one exact task"),
            *((recipe.catalog_entry, recipe.name) for recipe in recipes),
        )
        if confirming:
            for name in (
                "recipe",
                "recipient_email",
                "approver_email",
                "not_before",
                "expires_at",
                "reason",
            ):
                self.fields[name].widget = forms.HiddenInput()
        else:
            self.fields["confirmed"].required = False
            self.fields["confirmed"].widget = forms.HiddenInput()

    def clean(self) -> dict[str, Any] | None:
        """Validate complete original intent before any purpose-limited selection.

        Returns
        -------
        dict[str, Any] | None
            Closed validated fields with an immutable draft available on the form.

        Raises
        ------
        forms.ValidationError
            For missing/nonempty retry identity, unsupported transport state,
            malformed terms or an attempt to replace an existing preview silently.
        """
        values = super().clean()
        if self.errors or values is None:
            return values
        action, proof = values["action"], values["selection_proof"]
        if action == "confirm" and not values["confirmed"]:
            raise forms.ValidationError(
                "Confirm the exact original request deliberately."
            )
        if (action == "preview" and proof) or (action == "confirm" and not proof):
            raise forms.ValidationError(
                "Keep the original preview or start a deliberate new intent."
            )
        recipe = self.recipes[values["recipe"]]
        draft = ProgrammeRoleRequestDraft(
            recipe.code,
            recipe.version,
            values["recipient_email"],
            values["approver_email"],
            values["not_before"],
            values["expires_at"],
            values["reason"],
            values["idempotency_key"],
        )
        _selectors(draft)
        # Pure normalization only; these distinct sentinels are never selected people.
        draft.intent(UUID(int=1), UUID(int=2))
        self.draft = draft
        return values
