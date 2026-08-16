"""Closed browser forms for governed charity partner workflows."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, ClassVar, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import QuerySet

from maru.core.forms import (
    CanonicalUUIDField,
    HttpsURLField,
    StrictBase10IntegerField,
    StrictInputForm,
)
from maru.workforce.models import Department

from .models import CharityPartner, CharityPartnerMedia

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
        self.zone = ZoneInfo(zone_name)

    def to_python(self, value: object) -> datetime | None:
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
        if isinstance(value, datetime):
            local = value.astimezone(self.zone) if value.tzinfo else value
            return local.strftime(_DATE_TIME_FORMAT)
        return value


class IdempotentCharityForm(StrictInputForm):
    idempotency_key = CanonicalUUIDField(widget=forms.HiddenInput)

    def __init__(
        self,
        *args: Any,
        idempotency_key: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        initial = dict(kwargs.pop("initial", {}) or {})
        initial.setdefault("idempotency_key", idempotency_key or uuid4())
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)


class ReasonedCharityForm(IdempotentCharityForm):
    reason = forms.CharField(
        min_length=1,
        max_length=1_000,
        widget=forms.Textarea(attrs={"rows": 2, "maxlength": "1000"}),
    )


class VersionedReasonedCharityForm(ReasonedCharityForm):
    expected_version = StrictBase10IntegerField(
        min_value=1,
        widget=forms.HiddenInput,
    )


class CharityPartnerCreateForm(ReasonedCharityForm):
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
    expected_version = StrictBase10IntegerField(
        min_value=1,
        widget=forms.HiddenInput,
    )
    lifecycle = forms.ChoiceField(choices=CharityPartner.Lifecycle.choices)


class CharityMediaAddForm(ReasonedCharityForm):
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
        super().__init__(*args, **kwargs)
        cast(CharityEditionLocalDateTimeField, self.fields["expires_at"]).set_zone(
            edition_time_zone
        )


class CharityMediaReviewForm(VersionedReasonedCharityForm):
    public_reference = forms.CharField(max_length=1_000, required=False)


class CharitySelectionProposeForm(ReasonedCharityForm):
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
        super().__init__(*args, **kwargs)
        if partners is not None:
            cast(Any, self.fields["partner_id"]).queryset = partners
        if departments is not None:
            cast(Any, self.fields["responsible_department_id"]).queryset = departments


class CharitySelectionDecisionForm(VersionedReasonedCharityForm):
    pass


class CharitySelectionCommentForm(IdempotentCharityForm):
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
        super().__init__(*args, **kwargs)
        if media is not None:
            cast(Any, self.fields["media_ids"]).queryset = media
