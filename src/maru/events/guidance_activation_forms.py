"""Explicit human choices for purpose-bounded Guides setup decisions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from django import forms

from maru.core.forms import (
    CanonicalUUIDField,
    StrictBase10IntegerField,
    StrictInputForm,
)

if TYPE_CHECKING:
    from .guidance_activation_queries import GuidanceOperatorChoice


class GuidanceActivationProposalForm(StrictInputForm):
    """Select two real current people without accepting any substitute actor."""

    operator_a_id = forms.ChoiceField(label="First person responsible for Guides")
    operator_b_id = forms.ChoiceField(label="Second person responsible for Guides")
    reason = forms.CharField(
        label="Why are you setting up these responsibilities?",
        max_length=240,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    confirmed = forms.BooleanField(
        label="I checked the event, both people and the responsibilities shown above.",
    )
    expected_edition_version = StrictBase10IntegerField(widget=forms.HiddenInput)
    idempotency_key = CanonicalUUIDField(widget=forms.HiddenInput)

    def __init__(
        self,
        *args: Any,
        operators: tuple[GuidanceOperatorChoice, ...],
        **kwargs: Any,
    ) -> None:
        """Offer only current people returned by the admitted setup query.

        Parameters
        ----------
        *args : Any
            Original bound input, if any.
        operators : tuple[GuidanceOperatorChoice, ...]
            Current owner-admitted responsibility choices.
        **kwargs : Any
            Ordinary form options and original version values.
        """
        super().__init__(*args, **kwargs)
        choices = [
            ("", "Choose a person"),
            *((str(person.account_id), person.label) for person in operators),
        ]
        if self.is_bound:
            for name in ("operator_a_id", "operator_b_id"):
                value = self.data.get(name, "")
                try:
                    reference = UUID(value)
                except (ValueError, TypeError, AttributeError):
                    continue
                if (
                    str(reference) == value
                    and reference.int
                    and value not in {choice[0] for choice in choices}
                ):
                    choices.append(
                        (value, "Previously selected person (no longer available)")
                    )
        for field in ("operator_a_id", "operator_b_id"):
            cast("forms.ChoiceField", self.fields[field]).choices = choices

    def clean(self) -> dict[str, Any] | None:
        """Keep a duplicated-person decision visible beside the second choice.

        Returns
        -------
        dict[str, Any] | None
            Validated original input with any actionable choice errors.
        """
        data = super().clean()
        if (
            data
            and data.get("operator_a_id") == data.get("operator_b_id")
            and data.get("operator_a_id")
        ):
            self.add_error("operator_b_id", "Choose a different second person.")
        return data

    def operator_ids(self) -> tuple[UUID, UUID]:
        """Return the explicitly selected pair after successful validation.

        Returns
        -------
        tuple[UUID, UUID]
            Two distinct current choice identifiers in original order.
        """
        return UUID(self.cleaned_data["operator_a_id"]), UUID(
            self.cleaned_data["operator_b_id"]
        )


class GuidanceActivationAnswerForm(StrictInputForm):
    """Require an actual named person's own decision, without a default answer."""

    decision = forms.ChoiceField(
        label="Your decision",
        widget=forms.RadioSelect,
        choices=(
            (
                "accept",
                "Accept my responsibilities and approve the other person's assignment",
            ),
            ("decline", "Decline this setup"),
        ),
    )
    confirmed = forms.BooleanField(
        label="I have read the event, people and responsibilities in this request."
    )
    expected_version = StrictBase10IntegerField(widget=forms.HiddenInput)


class GuidanceActivationApplyForm(StrictInputForm):
    """Confirm the exact accepted setup without replacing either person's answer."""

    confirmed = forms.BooleanField(
        label="Apply exactly this setup, accepted by both named people."
    )
    expected_version = StrictBase10IntegerField(widget=forms.HiddenInput)
