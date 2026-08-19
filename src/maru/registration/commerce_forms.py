"""Closed browser command forms for registration commerce actions."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from django import forms

from maru.core.forms import (
    CanonicalUUIDField,
    StrictBase10IntegerField,
    StrictInputForm,
)


class _IdempotentCommandForm(StrictInputForm):
    idempotency_key = CanonicalUUIDField(widget=forms.HiddenInput)

    def __init__(
        self,
        *args: Any,
        idempotency_key: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the _IdempotentCommandForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        idempotency_key : UUID | None, default=None
            The key used to deduplicate repeated command submissions.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        initial = dict(kwargs.pop("initial", {}) or {})
        initial.setdefault("idempotency_key", idempotency_key or uuid4())
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)


class TierReplacementReservationForm(_IdempotentCommandForm):
    """Collect and validate tier replacement reservation input."""

    target_product_id = CanonicalUUIDField(widget=forms.HiddenInput)
    expected_registration_version = StrictBase10IntegerField(
        min_value=1,
        widget=forms.HiddenInput,
    )


class HostedPaymentStartForm(_IdempotentCommandForm):
    """Collect and validate hosted payment start input."""

    provider_account_id = CanonicalUUIDField(widget=forms.HiddenInput)


class DemoPaymentForm(_IdempotentCommandForm):
    """Collect and validate demo payment input."""


class CapacityAdjustmentForm(_IdempotentCommandForm):
    """Collect and validate capacity adjustment input."""

    product_id = CanonicalUUIDField(required=False, widget=forms.HiddenInput)
    new_capacity = StrictBase10IntegerField(
        label="New effective capacity",
        min_value=1,
        max_value=1_000_000,
    )
    expected_control_version = StrictBase10IntegerField(
        min_value=1,
        widget=forms.HiddenInput,
    )
    reason = forms.CharField(
        label="Reason",
        strip=True,
        min_length=1,
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 3, "maxlength": "500"}),
    )


class WaitlistBatchOfferForm(_IdempotentCommandForm):
    """Collect and validate waitlist batch offer input."""

    product_id = CanonicalUUIDField(widget=forms.HiddenInput)
    batch_size = StrictBase10IntegerField(
        label="Next eligible registrations",
        min_value=1,
        max_value=100,
    )
    expected_control_version = StrictBase10IntegerField(
        min_value=1,
        widget=forms.HiddenInput,
    )
    reason = forms.CharField(
        label="Reason",
        strip=True,
        min_length=1,
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 3, "maxlength": "500"}),
    )


__all__ = [
    "CapacityAdjustmentForm",
    "DemoPaymentForm",
    "HostedPaymentStartForm",
    "TierReplacementReservationForm",
    "WaitlistBatchOfferForm",
]
