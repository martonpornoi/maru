"""Closed browser forms for governed charity partner workflows."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from django import forms
from django.core.exceptions import ValidationError

from maru.core.forms import (
    CanonicalUUIDField,
    HttpsURLField,
    StrictBase10IntegerField,
    StrictInputForm,
)
from maru.workforce.models import Department

from .models import CharityPartner, CharityPartnerMedia

if TYPE_CHECKING:
    from django.db.models import QuerySet

_DATE_TIME_FORMAT = "%Y-%m-%dT%H:%M"
_LOCAL_DATE_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}\Z")


class CharityEditionLocalDateTimeField(forms.Field):
    """Parse one exact, real, unambiguous minute in the edition time zone."""

    default_error_messages: ClassVar[dict[str, Any]] = {
        "invalid": "Enter a valid local date and time.",
        "ambiguous": (
            "Choose an unambiguous local time outside the daylight-saving change."
        ),
    }

    def __init__(self, *args: Any, zone_name: str = "UTC", **kwargs: Any) -> None:
        """Initialize the CharityEditionLocalDateTimeField instance.

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


class IdempotentCharityForm(StrictInputForm):
    """Collect and validate idempotent charity input."""

    idempotency_key = CanonicalUUIDField(widget=forms.HiddenInput)

    def __init__(
        self,
        *args: Any,
        idempotency_key: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the IdempotentCharityForm instance.

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


class ReasonedCharityForm(IdempotentCharityForm):
    """Collect and validate reasoned charity input."""

    reason = forms.CharField(
        min_length=1,
        max_length=1_000,
        widget=forms.Textarea(attrs={"rows": 2, "maxlength": "1000"}),
    )


class VersionedReasonedCharityForm(ReasonedCharityForm):
    """Collect and validate versioned reasoned charity input."""

    expected_version = StrictBase10IntegerField(
        min_value=1,
        widget=forms.HiddenInput,
    )


class CharityPartnerCreateForm(ReasonedCharityForm):
    """Collect and validate charity partner create input."""

    slug = forms.SlugField(max_length=80)
    legal_name = forms.CharField(max_length=240)
    imprint_name = forms.CharField(max_length=240, required=False)
    public_name = forms.CharField(max_length=200)
    short_description = forms.CharField(
        max_length=500,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "maxlength": "500"}),
    )
    description = forms.CharField(
        max_length=5_000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 4, "maxlength": "5000"}),
    )
    location_name = forms.CharField(max_length=240, required=False)
    postal_address = forms.CharField(
        max_length=1_000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "maxlength": "1000"}),
    )
    country_code = forms.CharField(max_length=2, required=False)
    website_url = HttpsURLField(max_length=200, required=False)
    contact_email = forms.EmailField(max_length=254, required=False)
    contact_phone = forms.CharField(max_length=16, required=False)


class CharityPartnerUpdateForm(CharityPartnerCreateForm):
    """Collect and validate charity partner update input."""

    expected_version = StrictBase10IntegerField(
        min_value=1,
        widget=forms.HiddenInput,
    )
    lifecycle = forms.ChoiceField(choices=CharityPartner.Lifecycle.choices)


class CharityMediaAddForm(ReasonedCharityForm):
    """Collect and validate charity media add input."""

    kind = forms.ChoiceField(choices=CharityPartnerMedia.Kind.choices)
    source_reference = forms.CharField(max_length=1_000)
    owner_name = forms.CharField(max_length=240)
    license_basis = forms.CharField(
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 2, "maxlength": "500"}),
    )
    usage_scope = forms.CharField(
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 2, "maxlength": "500"}),
    )
    attribution = forms.CharField(max_length=500, required=False)
    expires_at = CharityEditionLocalDateTimeField(
        required=False,
    )

    def __init__(
        self,
        *args: Any,
        edition_time_zone: str,
        **kwargs: Any,
    ) -> None:
        """Initialize the CharityMediaAddForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        edition_time_zone : str
            The IANA time-zone name used for localization and validation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        super().__init__(*args, **kwargs)
        cast("CharityEditionLocalDateTimeField", self.fields["expires_at"]).set_zone(
            edition_time_zone
        )


class CharityMediaReviewForm(VersionedReasonedCharityForm):
    """Collect and validate charity media review input."""

    public_reference = forms.CharField(max_length=1_000, required=False)


class CharitySelectionProposeForm(ReasonedCharityForm):
    """Collect and validate charity selection propose input."""

    partner_id = forms.ModelChoiceField(
        label="Charity partner",
        queryset=CharityPartner.objects.none(),
    )
    responsible_department_id = forms.ModelChoiceField(
        label="Responsible Department",
        queryset=Department.objects.none(),
    )

    def __init__(
        self,
        *args: Any,
        partners: QuerySet[CharityPartner] | None = None,
        departments: QuerySet[Department] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the CharitySelectionProposeForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        partners : QuerySet[CharityPartner] | None, default=None
            The partners used to configure and validate this form.
        departments : QuerySet[Department] | None, default=None
            The departments used to configure and validate this form.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        super().__init__(*args, **kwargs)
        if partners is not None:
            cast("Any", self.fields["partner_id"]).queryset = partners
        if departments is not None:
            cast("Any", self.fields["responsible_department_id"]).queryset = departments


class CharitySelectionDecisionForm(VersionedReasonedCharityForm):
    """Collect and validate charity selection decision input."""


class CharitySelectionCommentForm(IdempotentCharityForm):
    """Collect and validate charity selection comment input."""

    expected_version = StrictBase10IntegerField(
        min_value=1,
        widget=forms.HiddenInput,
    )
    private_comment = forms.CharField(
        min_length=1,
        max_length=5_000,
        widget=forms.Textarea(attrs={"rows": 3, "maxlength": "5000"}),
    )


class _MediaChoiceField(forms.ModelMultipleChoiceField):  # type: ignore[type-arg]
    def label_from_instance(self, obj: CharityPartnerMedia) -> str:
        return f"{obj.get_kind_display()}: {obj.attribution or obj.owner_name}"


class CharitySelectionPublishForm(VersionedReasonedCharityForm):
    """Collect and validate charity selection publish input."""

    media_ids = _MediaChoiceField(
        label="Approved public media",
        queryset=CharityPartnerMedia.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(
        self,
        *args: Any,
        media: QuerySet[CharityPartnerMedia] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the CharitySelectionPublishForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        media : QuerySet[CharityPartnerMedia] | None, default=None
            The media used to configure and validate this form.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        super().__init__(*args, **kwargs)
        if media is not None:
            cast("Any", self.fields["media_ids"]).queryset = media
