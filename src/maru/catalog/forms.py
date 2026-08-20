"""Closed browser forms for catalog configuration, orders, and stock."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from django import forms
from django.core.exceptions import ValidationError

from maru.catalog.models import CatalogProduct
from maru.charities.models import CharitySelection
from maru.core.forms import (
    CanonicalUUIDField,
    StrictBase10IntegerField,
    StrictInputForm,
)

if TYPE_CHECKING:
    from django.db.models import QuerySet

_DATE_TIME_FORMAT = "%Y-%m-%dT%H:%M"
_LOCAL_DATE_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}\Z")


class CatalogEditionLocalDateTimeField(forms.Field):
    """Parse one exact, real, unambiguous minute in the edition time zone."""

    default_error_messages: ClassVar[dict[str, Any]] = {
        "invalid": "Enter a valid local date and time.",
        "ambiguous": (
            "Choose an unambiguous local time outside the daylight-saving change."
        ),
    }

    def __init__(self, *args: Any, zone_name: str = "UTC", **kwargs: Any) -> None:
        """Initialize the CatalogEditionLocalDateTimeField instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        zone_name : str, default='UTC'
            The human-readable zone name shown to authorized readers.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
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
        """Set zone.

        Parameters
        ----------
        zone_name : str
            The human-readable zone name shown to authorized readers.
        """
        self.zone = ZoneInfo(zone_name)

    def to_python(self, value: object) -> datetime | None:
        """Convert submitted input to its normalized Python representation.

        Parameters
        ----------
        value : object
            The untrusted input to normalize, validate, or compare.

        Returns
        -------
        datetime | None
            The canonical Python representation, or `None` for empty input.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        if value in self.empty_values:
            return None
        if not isinstance(value, str) or _LOCAL_DATE_TIME.fullmatch(value) is None:
            raise ValidationError(self.error_messages["invalid"], code="invalid")
        try:
            first = datetime.strptime(value, _DATE_TIME_FORMAT).replace(
                tzinfo=self.zone,
                fold=0,
            )
        except ValueError as error:
            raise ValidationError(
                self.error_messages["invalid"],
                code="invalid",
            ) from error
        local = first.replace(tzinfo=None)
        second = local.replace(tzinfo=self.zone, fold=1)
        if first.utcoffset() != second.utcoffset():
            raise ValidationError(
                self.error_messages["ambiguous"],
                code="ambiguous",
            )
        round_trip = first.astimezone(UTC).astimezone(self.zone).replace(tzinfo=None)
        if round_trip != local:
            raise ValidationError(
                self.error_messages["ambiguous"],
                code="nonexistent",
            )
        return first

    def prepare_value(self, value: object) -> object:
        """Prepare value.

        Parameters
        ----------
        value : object
            The untrusted input to normalize, validate, or compare.

        Returns
        -------
        object
            A widget-ready representation of the stored value.
        """
        if isinstance(value, datetime):
            local = value.astimezone(self.zone) if value.tzinfo else value
            return local.strftime(_DATE_TIME_FORMAT)
        return value


class CharitySelectionChoiceField(forms.ModelChoiceField):  # type: ignore[type-arg]
    """Expose only the confirmed partner's public label in staff HTML."""

    def label_from_instance(self, obj: CharitySelection) -> str:
        """Return label from instance.

        Parameters
        ----------
        obj : CharitySelection
            The model instance being validated or presented.

        Returns
        -------
        str
            The normalized text for label from instance.
        """
        return obj.partner.public_name


class IdempotentCatalogForm(StrictInputForm):
    """Collect and validate idempotent catalog input."""

    idempotency_key = CanonicalUUIDField(widget=forms.HiddenInput)

    def __init__(
        self,
        *args: Any,
        idempotency_key: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the IdempotentCatalogForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        idempotency_key : UUID | None, default=None
            The stable key that makes an exact retry idempotent.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        initial = dict(kwargs.pop("initial", {}) or {})
        initial.setdefault("idempotency_key", idempotency_key or uuid4())
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)


class ReasonedCatalogForm(IdempotentCatalogForm):
    """Collect and validate reasoned catalog input."""

    reason = forms.CharField(
        min_length=1,
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 2, "maxlength": "500"}),
    )


class VersionedReasonedCatalogForm(ReasonedCatalogForm):
    """Collect and validate versioned reasoned catalog input."""

    expected_version = StrictBase10IntegerField(
        min_value=1,
        widget=forms.HiddenInput,
    )


class CatalogCreateForm(ReasonedCatalogForm):
    """Collect and validate catalog create input."""

    currency = forms.RegexField(
        regex=r"[A-Z]{3}\Z",
        max_length=3,
        strip=False,
        help_text="Three-letter ISO-style currency code, for example EUR.",
    )


class CatalogProductAddForm(VersionedReasonedCatalogForm):
    """Collect and validate catalog product add input."""

    code = forms.RegexField(
        regex=r"[a-z0-9]+(?:-[a-z0-9]+)*\Z",
        max_length=80,
        strip=False,
    )
    kind = forms.ChoiceField(choices=CatalogProduct.Kind.choices)
    name = forms.CharField(min_length=1, max_length=160)
    description = forms.CharField(
        max_length=2_000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "maxlength": "2000"}),
    )
    beneficiary = forms.ChoiceField(choices=CatalogProduct.Beneficiary.choices)
    charity_selection_id = CharitySelectionChoiceField(
        label="Confirmed charity beneficiary",
        queryset=CharitySelection.objects.none(),
        required=False,
        empty_label="No charity beneficiary",
    )
    sale_opens_at = CatalogEditionLocalDateTimeField(required=False)
    sale_closes_at = CatalogEditionLocalDateTimeField(required=False)
    preorder_allowed = forms.BooleanField(required=False)
    fulfilment_mode = forms.ChoiceField(choices=CatalogProduct.Fulfilment.choices)
    per_order_limit = StrictBase10IntegerField(min_value=1, max_value=1_000)

    def __init__(
        self,
        *args: Any,
        edition_time_zone: str,
        charity_selections: QuerySet[CharitySelection] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the CatalogProductAddForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        edition_time_zone : str
            The IANA time-zone name used for localization and validation.
        charity_selections : QuerySet[CharitySelection] | None, default=None
            The charity selections used to configure and validate this form.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        initial = dict(kwargs.pop("initial", {}) or {})
        initial.setdefault("beneficiary", CatalogProduct.Beneficiary.CONVENTION)
        initial.setdefault("fulfilment_mode", CatalogProduct.Fulfilment.PICKUP)
        initial.setdefault("per_order_limit", 10)
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        cast("Any", self.fields["charity_selection_id"]).queryset = (
            charity_selections
            if charity_selections is not None
            else CharitySelection.objects.none()
        )
        for name in ("sale_opens_at", "sale_closes_at"):
            cast("CatalogEditionLocalDateTimeField", self.fields[name]).set_zone(
                edition_time_zone
            )

    def clean(self) -> dict[str, Any] | None:
        """Validate and normalize the record.

        Returns
        -------
        dict[str, Any] | None
            A mapping containing the resolved clean data.
        """
        cleaned = super().clean()
        if not cleaned:
            return cleaned
        beneficiary = cleaned.get("beneficiary")
        selection = cleaned.get("charity_selection_id")
        if beneficiary == CatalogProduct.Beneficiary.CHARITY and selection is None:
            self.add_error(
                "charity_selection_id",
                "Choose one confirmed charity beneficiary for this edition.",
            )
        elif (
            beneficiary == CatalogProduct.Beneficiary.CONVENTION
            and selection is not None
        ):
            self.add_error(
                "charity_selection_id",
                "Convention products cannot name a charity beneficiary.",
            )
        opens_at = cleaned.get("sale_opens_at")
        closes_at = cleaned.get("sale_closes_at")
        if opens_at is not None and closes_at is not None and closes_at <= opens_at:
            self.add_error("sale_closes_at", "Sale closing must follow sale opening.")
        kind = cleaned.get("kind")
        preorder = cleaned.get("preorder_allowed")
        fulfilment = cleaned.get("fulfilment_mode")
        if kind == CatalogProduct.Kind.DONATION and (
            preorder or fulfilment != CatalogProduct.Fulfilment.NONE
        ):
            self.add_error(
                "kind",
                "Donations cannot use fulfilment or preorder.",
            )
        if kind == CatalogProduct.Kind.SUPPORTER and preorder:
            self.add_error("preorder_allowed", "Supporter products cannot oversell.")
        return cleaned


class CatalogVariantAddForm(VersionedReasonedCatalogForm):
    """Collect and validate catalog variant add input."""

    sku = forms.CharField(min_length=1, max_length=80)
    name = forms.CharField(min_length=1, max_length=120)
    price_minor = StrictBase10IntegerField(
        min_value=0,
        max_value=10_000_000_000,
        help_text="Price in the catalog currency's smallest unit.",
    )
    initial_stock = StrictBase10IntegerField(
        min_value=0,
        max_value=10_000_000,
        required=False,
    )
    stock_ceiling = StrictBase10IntegerField(
        min_value=0,
        max_value=10_000_000,
        required=False,
        help_text="Hard ceiling for every later governed stock adjustment.",
    )

    def __init__(
        self,
        *args: Any,
        product_kind: str,
        **kwargs: Any,
    ) -> None:
        """Initialize the CatalogVariantAddForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        product_kind : str
            The closed product kind discriminator defined by the domain catalog.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        super().__init__(*args, **kwargs)
        self.product_kind = product_kind

    def clean(self) -> dict[str, Any] | None:
        """Validate and normalize the record.

        Returns
        -------
        dict[str, Any] | None
            A mapping containing the resolved clean data.
        """
        cleaned = super().clean()
        if not cleaned:
            return cleaned
        stock = cleaned.get("initial_stock")
        ceiling = cleaned.get("stock_ceiling")
        if (stock is None) != (ceiling is None):
            self.add_error(
                "stock_ceiling",
                "Set both initial stock and its hard ceiling, or leave both blank.",
            )
        elif stock is not None and ceiling is not None and ceiling < stock:
            self.add_error(
                "stock_ceiling",
                "The hard ceiling cannot be lower than initial stock.",
            )
        if self.product_kind == CatalogProduct.Kind.DONATION and stock is not None:
            self.add_error("initial_stock", "Donation price options cannot have stock.")
        if self.product_kind == CatalogProduct.Kind.SUPPORTER and stock is None:
            self.add_error(
                "initial_stock",
                "Limited supporter variants require finite stock and a hard ceiling.",
            )
        return cleaned


class CatalogActivateForm(VersionedReasonedCatalogForm):
    """Collect and validate catalog activate input."""


class CatalogOrderForm(IdempotentCatalogForm):
    """Collect and validate catalog order input."""

    variant_id = CanonicalUUIDField(widget=forms.HiddenInput)
    quantity = StrictBase10IntegerField(min_value=1, max_value=1_000)
    expected_version = StrictBase10IntegerField(min_value=1, widget=forms.HiddenInput)


class CatalogPaymentForm(IdempotentCatalogForm):
    """Collect and validate catalog payment input."""

    expected_catalog_version = StrictBase10IntegerField(
        min_value=1, widget=forms.HiddenInput
    )
    expected_order_version = StrictBase10IntegerField(
        min_value=1, widget=forms.HiddenInput
    )


class CatalogStockForm(IdempotentCatalogForm):
    """Collect and validate catalog stock input."""

    variant_id = CanonicalUUIDField(widget=forms.HiddenInput)
    expected_version = StrictBase10IntegerField(min_value=1, widget=forms.HiddenInput)
    new_stock = StrictBase10IntegerField(
        label="New governed stock", min_value=0, max_value=10_000_000
    )
    reason = forms.CharField(
        min_length=1,
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 2, "maxlength": "500"}),
    )
