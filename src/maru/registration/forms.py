"""Server-rendered public registration form."""

from __future__ import annotations

from datetime import date
from typing import Any, cast

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.utils import timezone

from maru.core.localization import (
    DEFAULT_PHONE_REGION,
    parse_phone_number,
    phone_region_choices,
    split_phone_number,
)
from maru.identity.models import Account
from maru.registration.availability import assess_product_availability
from maru.registration.models import (
    AdmissionProduct,
    QuestionFieldType,
    RegistrationConfiguration,
    RegistrationQuestion,
)
from maru.registration.profile_choices import (
    LANGUAGE_CHOICES,
    MAX_BIO_LENGTH,
    MAX_FURSUITS,
    MAX_SPOKEN_LANGUAGES,
    OTHER_PRONOUN_CODE,
    PRONOUN_CHOICES,
)
from maru.registration.profile_policy import (
    ALLOWED_FURSUIT_PHOTO_CONTENT_TYPES,
    MAX_FURSUIT_PHOTO_BYTES,
)

TELEGRAM_VALIDATOR = RegexValidator(
    regex=r"^@?[A-Za-z0-9_]{5,32}$",
    message="Use a Telegram username with 5-32 letters, numbers, or underscores.",
)
MAX_REASONABLE_AGE = 120


class PublicAccountBootstrapForm(forms.Form):
    """Small first step used when verified email is required."""

    email = forms.EmailField(
        max_length=254,
        help_text="Used only for your Maru login and registration service.",
    )
    display_name = forms.CharField(
        max_length=120,
        help_text="Your fandom, badge, or preferred attendee name.",
    )
    password1 = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput,
        help_text="Use at least eight characters and avoid common passwords.",
    )
    password2 = forms.CharField(
        label="Confirm password",
        strip=False,
        widget=forms.PasswordInput,
    )

    def clean(self) -> dict[str, object]:
        cleaned = super().clean() or {}
        password = str(cleaned.get("password1", ""))
        if password and password != cleaned.get("password2"):
            self.add_error("password2", "The passwords do not match.")
        if password:
            validate_password(password)
        return cleaned


class GuardianConsentForm(forms.Form):
    token = forms.CharField(widget=forms.HiddenInput, max_length=200)
    guardian_name = forms.CharField(
        label="Guardian full name",
        max_length=200,
        help_text="Enter your own name as evidence of this authorization.",
    )


def _validate_profile_image(upload: Any) -> Any:
    if upload is None:
        return None
    if upload.size > MAX_FURSUIT_PHOTO_BYTES:
        raise ValidationError("Use an image no larger than 5 MB.")
    if upload.content_type not in ALLOWED_FURSUIT_PHOTO_CONTENT_TYPES:
        raise ValidationError("Upload a JPEG, PNG, or WebP image.")
    return upload


class AttendeeProfileForm(forms.Form):
    """Profile fields shared by the reference registration and edit surfaces."""

    real_name = forms.CharField(
        label="Real name",
        max_length=200,
        help_text="Restricted registration identity data; never shown publicly.",
    )
    date_of_birth = forms.DateField(
        label="Date of birth",
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Restricted data used only to evaluate this edition's age policy.",
    )
    pronoun_code = forms.ChoiceField(
        label="Pronouns",
        choices=(("", "Choose pronouns"), *PRONOUN_CHOICES),
    )
    other_pronouns = forms.CharField(
        label="Other pronouns",
        max_length=80,
        required=False,
        help_text="Shown only when you choose Other pronouns.",
        widget=forms.TextInput(attrs={"data-other-pronouns-input": ""}),
    )
    bio = forms.CharField(
        label="Public bio",
        max_length=MAX_BIO_LENGTH,
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "maxlength": MAX_BIO_LENGTH,
                "data-character-count": "bio",
            }
        ),
        help_text=f"Optional. Up to {MAX_BIO_LENGTH} characters.",
    )
    spoken_language_codes = forms.MultipleChoiceField(
        label="Spoken languages",
        choices=LANGUAGE_CHOICES,
        required=False,
        widget=forms.SelectMultiple(
            attrs={
                "size": 8,
                "data-language-select": "",
            }
        ),
        help_text=(
            f"Choose up to {MAX_SPOKEN_LANGUAGES}. These codes are available "
            "to the future badge/credential renderer."
        ),
    )
    phone_region_code = forms.ChoiceField(
        label="Calling country",
        choices=phone_region_choices,
        required=False,
        help_text="Choose by country initials, flag, or international dialling code.",
    )
    phone_number = forms.CharField(
        label="Telephone number",
        max_length=40,
        widget=forms.TextInput(
            attrs={
                "type": "tel",
                "inputmode": "tel",
                "autocomplete": "tel-national",
            }
        ),
    )
    telegram_handle = forms.CharField(
        label="Telegram handle",
        max_length=64,
        required=False,
        validators=(TELEGRAM_VALIDATOR,),
        help_text="Optional. Registration staff only; never published.",
    )
    address_line_1 = forms.CharField(label="Address", max_length=200)
    address_line_2 = forms.CharField(
        label="Address line 2",
        max_length=200,
        required=False,
    )
    locality = forms.CharField(label="City or locality", max_length=120)
    postal_code = forms.CharField(max_length=32)
    region = forms.CharField(label="State, province, or region", max_length=120)
    country_code = forms.RegexField(
        label="Country code",
        regex=r"^[A-Za-z]{2}$",
        max_length=2,
        help_text="Two-letter country code, for example HU, AT, DE, or US.",
        error_messages={"invalid": "Enter a two-letter country code."},
    )
    emergency_contact_name = forms.CharField(max_length=200)
    emergency_phone_region_code = forms.ChoiceField(
        label="Emergency calling country",
        choices=phone_region_choices,
        required=False,
        help_text="Choose by country initials, flag, or international dialling code.",
    )
    emergency_contact_phone = forms.CharField(
        label="Emergency telephone number",
        max_length=40,
        widget=forms.TextInput(
            attrs={
                "type": "tel",
                "inputmode": "tel",
                "autocomplete": "off",
            }
        ),
    )
    guardian_name = forms.CharField(
        label="Guardian name",
        max_length=200,
        required=False,
    )
    guardian_email = forms.EmailField(
        label="Guardian email",
        required=False,
    )
    guardian_relationship = forms.CharField(
        label="Relationship to attendee",
        max_length=80,
        required=False,
    )
    guardian_notice_version = forms.CharField(
        required=False,
        widget=forms.HiddenInput,
    )
    profile_photo = forms.FileField(
        required=False,
        help_text=(
            "Optional JPEG, PNG, or WebP up to 5 MB. A new image stays private "
            "until an organizer approves it."
        ),
    )
    reuse_profile_photo_id = forms.UUIDField(
        required=False,
        widget=forms.HiddenInput,
    )
    keep_profile_photo = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.HiddenInput,
    )
    remove_profile_photo = forms.BooleanField(
        required=False,
        label="Remove the current profile image",
        help_text=("The image will no longer be attached to this convention profile."),
    )
    brings_fursuits = forms.BooleanField(
        required=False,
        label="I plan to bring one or more fursuits",
        help_text="Turn this on to add the fursuits you expect to bring.",
        widget=forms.CheckboxInput(attrs={"data-fursuit-toggle": ""}),
    )
    directory_visible = forms.BooleanField(
        required=False,
        label="Show my attendance on this convention's public attendee list",
        help_text=(
            "Anyone may see only your display name, pronouns, bio, spoken "
            "languages, approved profile/fursuit images, authoritative attendee "
            "labels, and the optional public country you enter below. Contact, "
            "address, real name, birth date, emergency contact, product, price, "
            "and payment details are never published."
        ),
        widget=forms.CheckboxInput(attrs={"data-directory-toggle": ""}),
    )
    directory_country_code = forms.RegexField(
        required=False,
        label="Country shown on my public attendee card",
        regex=r"^[A-Za-z]{2}$",
        max_length=2,
        help_text=(
            "Optional. Enter the two-letter country code you want to represent, "
            "for example HU, AT, DE, or US. This is separate from your address "
            "and is never copied from a prior convention."
        ),
        error_messages={"invalid": "Enter a two-letter country code."},
        widget=forms.TextInput(attrs={"data-directory-country-input": ""}),
    )

    def __init__(
        self,
        *args: Any,
        configuration: RegistrationConfiguration,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.configuration = configuration
        available_phone_regions = {choice[0] for choice in phone_region_choices()}
        organization_region = configuration.organization.country_code.upper()
        default_phone_region = (
            organization_region
            if organization_region in available_phone_regions
            else DEFAULT_PHONE_REGION
        )
        for region_field_name, number_field_name in (
            ("phone_region_code", "phone_number"),
            ("emergency_phone_region_code", "emergency_contact_phone"),
        ):
            self.fields[region_field_name].initial = default_phone_region
            raw_number = str(self.initial.get(number_field_name, ""))
            if raw_number:
                region, national_number = split_phone_number(raw_number)
                self.initial[region_field_name] = region
                self.initial[number_field_name] = national_number
        self.default_phone_region = default_phone_region
        policy = getattr(configuration, "minor_policy", None)
        if policy is not None and policy.enabled:
            self.fields[
                "guardian_notice_version"
            ].initial = policy.guardian_notice_version

    def clean_country_code(self) -> str:
        return str(self.cleaned_data["country_code"]).upper()

    def clean_telegram_handle(self) -> str:
        return str(self.cleaned_data.get("telegram_handle", "")).lstrip("@")

    def clean_directory_country_code(self) -> str:
        return str(self.cleaned_data.get("directory_country_code", "")).upper()

    def clean_date_of_birth(self) -> date:
        birth_date = cast(date, self.cleaned_data["date_of_birth"])
        relevant_date = self.configuration.edition.starts_on
        age = (
            relevant_date.year
            - birth_date.year
            - (
                (relevant_date.month, relevant_date.day)
                < (birth_date.month, birth_date.day)
            )
        )
        if birth_date > timezone.localdate():
            raise ValidationError("Date of birth cannot be in the future.")
        if age < self.configuration.minimum_age:
            raise ValidationError(
                "This edition's public registration currently supports attendees "
                f"aged {self.configuration.minimum_age} or older at the event. "
                "A guardian workflow has not been configured."
            )
        if age > MAX_REASONABLE_AGE:
            raise ValidationError("Check the date of birth.")
        return birth_date

    def clean_profile_photo(self) -> Any:
        return _validate_profile_image(self.cleaned_data.get("profile_photo"))

    def clean_spoken_language_codes(self) -> list[str]:
        codes = [
            str(code).lower()
            for code in self.cleaned_data.get(
                "spoken_language_codes",
                [],
            )
        ]
        if len(codes) > MAX_SPOKEN_LANGUAGES:
            raise ValidationError(
                f"Choose no more than {MAX_SPOKEN_LANGUAGES} spoken languages."
            )
        return codes

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        for region_field_name, number_field_name in (
            ("phone_region_code", "phone_number"),
            ("emergency_phone_region_code", "emergency_contact_phone"),
        ):
            raw_number = str(cleaned.get(number_field_name, "")).strip()
            if not raw_number:
                continue
            region_code = str(
                cleaned.get(region_field_name) or self.default_phone_region
            )
            try:
                cleaned[number_field_name] = parse_phone_number(
                    region_code=region_code,
                    national_number=raw_number,
                )
            except ValidationError as error:
                self.add_error(number_field_name, error)
        pronoun_code = str(cleaned.get("pronoun_code", ""))
        other_pronouns = str(cleaned.get("other_pronouns", "")).strip()
        if pronoun_code == OTHER_PRONOUN_CODE and not other_pronouns:
            self.add_error(
                "other_pronouns",
                "Enter the pronouns you want displayed.",
            )
        elif pronoun_code != OTHER_PRONOUN_CODE:
            cleaned["other_pronouns"] = ""
        if cleaned.get("directory_country_code") and not cleaned.get(
            "directory_visible"
        ):
            self.add_error(
                "directory_country_code",
                "Join the public attendee list before adding a public country.",
            )
        if cleaned.get("remove_profile_photo"):
            cleaned["reuse_profile_photo_id"] = None
        return cleaned


class AttendeeFursuitForm(forms.Form):
    fursuit_id = forms.UUIDField(required=False, widget=forms.HiddenInput)
    reuse_from_id = forms.UUIDField(required=False, widget=forms.HiddenInput)
    name = forms.CharField(label="Fursuit name", max_length=120, required=False)
    species = forms.CharField(max_length=120, required=False)
    photo = forms.FileField(
        required=False,
        help_text=(
            "Optional JPEG, PNG, or WebP up to 5 MB. A new image needs approval."
        ),
    )
    keep_photo = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.HiddenInput,
    )
    remove_photo = forms.BooleanField(
        required=False,
        label="Remove this fursuit image",
    )

    def clean_photo(self) -> Any:
        return _validate_profile_image(self.cleaned_data.get("photo"))

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        if cleaned.get("remove_photo"):
            cleaned["reuse_from_id"] = None
        if (
            any(
                cleaned.get(name)
                for name in ("photo", "reuse_from_id", "fursuit_id", "species")
            )
            and not str(cleaned.get("name", "")).strip()
        ):
            self.add_error("name", "Enter a name for this fursuit.")
        return cleaned


class BaseAttendeeFursuitFormSet(forms.BaseFormSet):  # type: ignore[type-arg]
    def __init__(
        self,
        *args: Any,
        brings_fursuits: bool,
        **kwargs: Any,
    ) -> None:
        self.brings_fursuits = brings_fursuits
        super().__init__(*args, **kwargs)

    def clean(self) -> None:
        if any(self.errors):
            return
        active = [
            form
            for form in self.forms
            if form.cleaned_data
            and not form.cleaned_data.get("DELETE")
            and str(form.cleaned_data.get("name", "")).strip()
        ]
        if self.brings_fursuits and not active:
            raise ValidationError(
                "Add at least one fursuit, or clear the fursuit checkbox."
            )
        if not self.brings_fursuits and active:
            raise ValidationError(
                "Select the fursuit checkbox before adding fursuit details."
            )


_AttendeeFursuitFormSet = forms.formset_factory(
    AttendeeFursuitForm,
    formset=BaseAttendeeFursuitFormSet,
    extra=1,
    can_delete=True,
    max_num=MAX_FURSUITS,
    validate_max=True,
)


def attendee_fursuit_formset(
    *args: Any,
    brings_fursuits: bool,
    **kwargs: Any,
) -> BaseAttendeeFursuitFormSet:
    return cast(
        BaseAttendeeFursuitFormSet,
        _AttendeeFursuitFormSet(
            *args,
            brings_fursuits=brings_fursuits,  # type: ignore[call-arg]
            **kwargs,
        ),
    )


class PublicRegistrationForm(AttendeeProfileForm):
    email = forms.EmailField(
        max_length=254,
        help_text="Used only for your Maru login and registration service.",
    )
    display_name = forms.CharField(
        max_length=120,
        help_text="Your fandom, badge, or preferred attendee name.",
    )
    password1 = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput,
        help_text="Use at least eight characters and avoid common passwords.",
    )
    password2 = forms.CharField(
        label="Confirm password",
        strip=False,
        widget=forms.PasswordInput,
    )
    product = forms.ModelChoiceField(
        queryset=AdmissionProduct.objects.none(),
        empty_label=None,
        widget=forms.RadioSelect,
    )

    def __init__(
        self,
        *args: Any,
        configuration: RegistrationConfiguration,
        include_account_fields: bool,
        account: Account | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, configuration=configuration, **kwargs)
        self.dynamic_questions = list(
            configuration.questions.select_related("section").order_by(
                "section__position",
                "position",
                "id",
            )
        )
        if not include_account_fields:
            for name in ("email", "display_name", "password1", "password2"):
                self.fields.pop(name)
        product_field = cast(
            "forms.ModelChoiceField[AdmissionProduct]",
            self.fields["product"],
        )
        products = list(
            configuration.products.filter(
                status=AdmissionProduct.Status.AVAILABLE
            ).order_by("position", "id")
        )
        selectable_ids = [
            product.id
            for product in products
            if assess_product_availability(product=product, account=account).selectable
        ]
        product_field.queryset = configuration.products.filter(id__in=selectable_ids)
        for question in self.dynamic_questions:
            field_name = self.question_field_name(question)
            self.fields[field_name] = self._question_form_field(question)
            self.fields[field_name].widget.attrs.update(
                {
                    "data-question-key": question.key,
                    "data-condition-key": question.condition_question_key,
                    "data-condition-value": question.condition_value,
                }
            )

    @staticmethod
    def question_field_name(question: RegistrationQuestion) -> str:
        return f"question__{question.key}"

    @staticmethod
    def _question_form_field(question: RegistrationQuestion) -> forms.Field:
        common: dict[str, Any] = {
            "label": question.label,
            "help_text": (
                f"{question.help_text} Purpose: {question.purpose}"
                if question.help_text
                else f"Purpose: {question.purpose}"
            ),
            "required": False,
        }
        if question.field_type == QuestionFieldType.LONG_TEXT:
            return forms.CharField(widget=forms.Textarea(attrs={"rows": 4}), **common)
        if question.field_type == QuestionFieldType.BOOLEAN:
            return forms.TypedChoiceField(
                choices=(("", "Choose"), ("true", "Yes"), ("false", "No")),
                coerce=lambda value: value == "true",
                empty_value=None,
                **common,
            )
        if question.field_type == QuestionFieldType.INTEGER:
            return forms.IntegerField(**common)
        if question.field_type == QuestionFieldType.SINGLE_CHOICE:
            return forms.ChoiceField(
                choices=(
                    ("", "Choose"),
                    *[(option, option) for option in question.options],
                ),
                **common,
            )
        if question.field_type == QuestionFieldType.MULTIPLE_CHOICE:
            return forms.MultipleChoiceField(
                choices=[(option, option) for option in question.options],
                widget=forms.CheckboxSelectMultiple,
                **common,
            )
        return forms.CharField(max_length=500, **common)

    def clean_email(self) -> str:
        email = Account.objects.normalize_login_email(self.cleaned_data["email"])
        if Account.objects.filter(email__iexact=email).exists():
            raise ValidationError(
                "This email cannot start a new account here. Sign in to continue."
            )
        return email

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1 is not None or password2 is not None:
            if password1 != password2:
                self.add_error("password2", "The passwords do not match.")
            elif password1:
                candidate = Account(
                    email=str(cleaned.get("email", "")),
                    display_name=str(cleaned.get("display_name", "")),
                )
                try:
                    validate_password(str(password1), user=candidate)
                except ValidationError as error:
                    self.add_error("password1", error)
        return cleaned

    def registration_answers(self) -> dict[str, object]:
        answers: dict[str, object] = {}
        for question in self.dynamic_questions:
            value = self.cleaned_data.get(self.question_field_name(question))
            if value not in (None, "", []):
                answers[question.key] = value
        return answers


class StaffAssistedRegistrationForm(PublicRegistrationForm):
    """Same attendee payload plus explicit staff actor/subject evidence."""

    account_email = forms.EmailField(
        label="Attendee email",
        max_length=254,
        help_text=(
            "An exact active-account match is used. If none exists, Maru creates "
            "a new account from the explicitly supplied details below."
        ),
    )
    new_account_display_name = forms.CharField(
        label="New account display name",
        max_length=120,
        required=False,
        help_text="Required only when the email has never belonged to an account.",
    )
    new_account_password1 = forms.CharField(
        label="Temporary password for a new account",
        strip=False,
        required=False,
        widget=forms.PasswordInput,
        help_text=(
            "Required only for a new account. Give it to the attendee through "
            "a separate secure channel."
        ),
    )
    new_account_password2 = forms.CharField(
        label="Confirm temporary password",
        strip=False,
        required=False,
        widget=forms.PasswordInput,
    )
    staff_reason = forms.CharField(
        label="Why registration is being created outside the public window",
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Staff-only evidence. The attendee sees that staff assisted them.",
    )

    def __init__(
        self,
        *args: Any,
        configuration: RegistrationConfiguration,
        account: Account | None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            *args,
            configuration=configuration,
            include_account_fields=False,
            account=account,
            **kwargs,
        )
        self.account = account
        product_field = cast(
            "forms.ModelChoiceField[AdmissionProduct]",
            self.fields["product"],
        )
        products = configuration.products.filter(
            status=AdmissionProduct.Status.AVAILABLE
        )
        selectable_ids = [
            product.id
            for product in products
            if assess_product_availability(
                product=product,
                account=account,
                ignore_sale_window=True,
            ).selectable
        ]
        product_field.queryset = products.filter(id__in=selectable_ids)

    def clean_account_email(self) -> str:
        return Account.objects.normalize_login_email(
            str(self.cleaned_data["account_email"])
        )

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        if self.account is not None:
            if not self.account.is_active:
                self.add_error(
                    "account_email",
                    "This email belongs to an inactive account and cannot register.",
                )
            cleaned["new_account_display_name"] = ""
            cleaned["new_account_password1"] = ""
            cleaned["new_account_password2"] = ""
            return cleaned

        display_name = str(cleaned.get("new_account_display_name", "")).strip()
        password1 = str(cleaned.get("new_account_password1", ""))
        password2 = str(cleaned.get("new_account_password2", ""))
        if not display_name:
            self.add_error(
                "new_account_display_name",
                "Enter a display name because this email has no Maru account.",
            )
        if not password1:
            self.add_error(
                "new_account_password1",
                "Set a temporary password because this email has no Maru account.",
            )
        elif password1 != password2:
            self.add_error("new_account_password2", "The passwords do not match.")
        else:
            candidate = Account(
                email=str(cleaned.get("account_email", "")),
                display_name=display_name,
            )
            try:
                validate_password(password1, user=candidate)
            except ValidationError as error:
                self.add_error("new_account_password1", error)
        cleaned["new_account_display_name"] = display_name
        return cleaned
