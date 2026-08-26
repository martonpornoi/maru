"""Public and attendee-facing server-rendered registration entry."""

from __future__ import annotations

import mimetypes
from collections import defaultdict
from pathlib import Path
from typing import cast
from urllib.parse import urlencode
from uuid import UUID, uuid4

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import DatabaseError, IntegrityError
from django.db.models import Prefetch, QuerySet
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import decide, resolve_edition_target
from maru.events.adoption import profile_codes_for_module
from maru.events.models import EventEdition
from maru.identity.models import Account, IdentityChallenge
from maru.identity.services import (
    bootstrap_account,
    issue_identity_challenge,
    request_fingerprint,
)
from maru.participation.models import ParticipationCapacity
from maru.registration.availability import (
    OCCUPIED_REGISTRATION_STATES,
    assess_product_availability,
)
from maru.registration.commerce import (
    effective_product_capacity,
    pending_target_capacity_holds,
    reserve_admission_tier_replacement,
)
from maru.registration.commerce_forms import (
    DemoPaymentForm,
    HostedPaymentStartForm,
    TierReplacementReservationForm,
)
from maru.registration.forms import (
    AttendeeProfileForm,
    BaseAttendeeFursuitFormSet,
    GuardianConsentForm,
    PublicAccountBootstrapForm,
    PublicRegistrationForm,
    StaffAssistedRegistrationForm,
    attendee_fursuit_formset,
)
from maru.registration.guardians import accept_guardian_consent
from maru.registration.media import media_is_safe
from maru.registration.models import (
    AdmissionProduct,
    AdmissionTierReplacement,
    AttendeeFursuit,
    AttendeeRegistrationProfile,
    ConfigurationStatus,
    Entitlement,
    MediaReviewStatus,
    PaymentProviderAccount,
    Registration,
    RegistrationConfiguration,
    RegistrationTimelineEntry,
)
from maru.registration.payments import create_payment_intent
from maru.registration.presentation import attendance_labels
from maru.registration.profile_choices import language_labels
from maru.registration.profile_extension_values import (
    ProfileExtensionValueError,
    read_directory_profile_extension_values,
    read_profile_extension_values,
)
from maru.registration.profile_policy import (
    DIRECTORY_CONSENT_VERSION,
    PROFILE_FIELD_POLICY,
)
from maru.registration.services import (
    AttendeeFursuitInput,
    AttendeeProfileInput,
    confirm_demo_payment,
    latest_profile_suggestion,
    profile_is_editable,
    submit_public_registration,
    update_attendee_profile,
)

PAID_REGISTRATION_STATES = (
    Registration.State.CONFIRMED,
    Registration.State.CHECKED_IN,
)
REGISTER_ON_BEHALF = "registration.register_on_behalf"


def guardian_consent(request: HttpRequest) -> HttpResponse:
    """Human-facing completion page for a guardian's single-use link.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.
    """
    form = GuardianConsentForm(
        request.POST or None,
        initial={"token": request.GET.get("token", "")},
    )
    registration = None
    if request.method == "POST" and form.is_valid():
        try:
            registration = accept_guardian_consent(
                raw_token=cast("str", form.cleaned_data["token"]),
                guardian_name=cast("str", form.cleaned_data["guardian_name"]),
            )
        except ValidationError as error:
            form.add_error(None, error.messages[0])
    return TemplateResponse(
        request,
        "registration/guardian_consent.html",
        {"form": form, "registration": registration},
    )


def _open_configurations() -> QuerySet[RegistrationConfiguration]:
    now = timezone.now()
    return (
        RegistrationConfiguration.objects.filter(
            status=ConfigurationStatus.ACTIVE,
            opens_at__lte=now,
            closes_at__gt=now,
            edition__adoption_profile_code__in=profile_codes_for_module("registration"),
        )
        .exclude(edition__lifecycle__in=("archived", "cancelled"))
        .select_related("organization", "edition", "edition__series")
        .prefetch_related(
            "sections",
            "questions__section",
            Prefetch(
                "products",
                queryset=AdmissionProduct.objects.filter(
                    status=AdmissionProduct.Status.AVAILABLE
                ).order_by("position", "id"),
            ),
        )
        .order_by("edition__starts_on", "edition__name")
    )


def _account(request: HttpRequest) -> Account | None:
    return request.user if isinstance(request.user, Account) else None


def public_registration_index(request: HttpRequest) -> TemplateResponse:
    """Show open editions and returning-attendee registration history.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.

    Returns
    -------
    TemplateResponse
        The HTTP response for the requested operation.
    """
    account = _account(request)
    open_configurations = list(_open_configurations())
    registrations: list[Registration] = []
    registered_edition_ids: set[UUID] = set()
    if account is not None:
        registrations = list(
            Registration.objects.filter(account=account)
            .select_related("edition", "product")
            .order_by("-edition__starts_on", "edition__name")
        )
        registered_edition_ids = {
            registration.edition_id for registration in registrations
        }
    cards = [
        {
            "configuration": configuration,
            "already_registered": configuration.edition_id in registered_edition_ids,
        }
        for configuration in open_configurations
    ]
    return TemplateResponse(
        request,
        "registration/public_index.html",
        {
            "cards": cards,
            "registrations": registrations,
            "account": account,
            "sign_in_url": (
                f"{reverse('staff-login')}?"
                f"{urlencode({'next': reverse('public-registration-index')})}"
            ),
        },
    )


@login_required(login_url="staff-login")
def staff_assisted_registration(
    request: HttpRequest,
    edition_id: UUID,
) -> HttpResponse:
    """Reasoned staff client for the ordinary registration command.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    edition_id : UUID
        The event edition identifier that scopes the operation.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    """
    actor = _account(request)
    if actor is None:
        raise Http404
    configuration = (
        RegistrationConfiguration.objects.filter(
            edition_id=edition_id,
            status=ConfigurationStatus.ACTIVE,
        )
        .exclude(edition__lifecycle__in=("archived", "cancelled"))
        .select_related("organization", "edition", "edition__series")
        .prefetch_related("sections", "questions__section", "products")
        .first()
    )
    if configuration is None:
        raise Http404
    decision = decide(
        principal=actor,
        capability_code=REGISTER_ON_BEHALF,
        resource=resolve_edition_target(
            organization_id=configuration.organization_id,
            edition_id=configuration.edition_id,
        ),
    )
    if not decision.allowed:
        raise Http404
    posted_email = str(request.POST.get("account_email", "")).strip()
    subject = (
        Account.objects.filter(email__iexact=posted_email).first()
        if posted_email
        else None
    )
    form = StaffAssistedRegistrationForm(
        request.POST or None,
        request.FILES or None,
        configuration=configuration,
        account=subject,
    )
    raw_brings_fursuits = request.POST.get("brings_fursuits") in (
        "on",
        "true",
        "1",
    )
    fursuit_formset = attendee_fursuit_formset(
        request.POST or None,
        request.FILES or None,
        prefix="fursuits",
        brings_fursuits=raw_brings_fursuits,
    )
    form_valid = form.is_valid() if request.method == "POST" else False
    fursuits_valid = fursuit_formset.is_valid() if request.method == "POST" else False
    if request.method == "POST" and form_valid and fursuits_valid:
        try:
            result = submit_public_registration(
                organization_id=configuration.organization_id,
                edition_id=configuration.edition_id,
                product_id=cast("AdmissionProduct", form.cleaned_data["product"]).id,
                answers=form.registration_answers(),
                profile_input=_profile_input(form, fursuit_formset),
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
                account=subject,
                email=(
                    ""
                    if subject is not None
                    else cast("str", form.cleaned_data["account_email"])
                ),
                display_name=(
                    ""
                    if subject is not None
                    else cast("str", form.cleaned_data["new_account_display_name"])
                ),
                password=(
                    ""
                    if subject is not None
                    else cast("str", form.cleaned_data["new_account_password1"])
                ),
                source_channel="staff_web",
                staff_actor=actor,
                staff_reason=cast("str", form.cleaned_data["staff_reason"]),
                bypass_sale_windows=True,
            )
        except (IntegrityError, ObjectDoesNotExist, ValidationError) as error:
            message = (
                error.messages[0]
                if isinstance(error, ValidationError) and error.messages
                else "The staff-assisted registration could not be created."
            )
            form.add_error(None, message)
        else:
            return redirect(
                f"{reverse('management-console')}?registration={result.registration.id}"
            )
    products = list(
        configuration.products.filter(
            status=AdmissionProduct.Status.AVAILABLE
        ).order_by("position", "id")
    )
    return TemplateResponse(
        request,
        "registration/public_form.html",
        {
            "configuration": configuration,
            "form": form,
            "fursuit_formset": fursuit_formset,
            "dynamic_groups": _dynamic_groups(form),
            "product_choices": [
                {
                    "product": product,
                    "availability": assess_product_availability(
                        product=product,
                        account=subject,
                        ignore_sale_window=True,
                    ),
                }
                for product in products
            ],
            "account": subject,
            "suggested_profile": None,
            "staff_assisted": True,
            "staff_actor": actor,
            "account_will_be_created": bool(posted_email and subject is None),
        },
    )


def _dynamic_groups(
    form: PublicRegistrationForm,
) -> list[dict[str, object]]:
    groups: dict[str, dict[str, object]] = {}
    order: list[str] = []
    for question in form.dynamic_questions:
        section = question.section
        key = section.key if section is not None else "convention-questions"
        if key not in groups:
            groups[key] = {
                "key": key,
                "title": (
                    section.title if section is not None else "Convention questions"
                ),
                "description": section.description if section is not None else "",
                "fields": [],
            }
            order.append(key)
        fields = cast("list[object]", groups[key]["fields"])
        fields.append(form[form.question_field_name(question)])
    return [groups[key] for key in order]


def _profile_input(
    form: AttendeeProfileForm,
    fursuit_formset: BaseAttendeeFursuitFormSet,
) -> AttendeeProfileInput:
    profile_upload = form.cleaned_data.get("profile_photo")
    fursuits: list[AttendeeFursuitInput] = []
    for fursuit_form in fursuit_formset.forms:
        if (
            not fursuit_form.cleaned_data
            or fursuit_form.cleaned_data.get("DELETE")
            or not str(fursuit_form.cleaned_data.get("name", "")).strip()
        ):
            continue
        upload = fursuit_form.cleaned_data.get("photo")
        fursuits.append(
            AttendeeFursuitInput(
                fursuit_id=cast("UUID | None", fursuit_form.cleaned_data["fursuit_id"]),
                reuse_from_id=cast(
                    "UUID | None",
                    fursuit_form.cleaned_data["reuse_from_id"],
                ),
                name=cast("str", fursuit_form.cleaned_data["name"]),
                species=cast("str", fursuit_form.cleaned_data["species"]),
                photo=upload if isinstance(upload, UploadedFile) else None,
                keep_photo=not bool(fursuit_form.cleaned_data["remove_photo"]),
            )
        )
    return AttendeeProfileInput(
        real_name=cast("str", form.cleaned_data["real_name"]),
        date_of_birth=form.cleaned_data["date_of_birth"],
        address_line_1=cast("str", form.cleaned_data["address_line_1"]),
        address_line_2=cast("str", form.cleaned_data["address_line_2"]),
        locality=cast("str", form.cleaned_data["locality"]),
        postal_code=cast("str", form.cleaned_data["postal_code"]),
        region=cast("str", form.cleaned_data["region"]),
        country_code=cast("str", form.cleaned_data["country_code"]),
        emergency_contact_name=cast(
            "str",
            form.cleaned_data["emergency_contact_name"],
        ),
        emergency_contact_phone=cast(
            "str",
            form.cleaned_data["emergency_contact_phone"],
        ),
        phone_number=cast("str", form.cleaned_data["phone_number"]),
        telegram_handle=cast("str", form.cleaned_data["telegram_handle"]),
        pronoun_code=cast("str", form.cleaned_data["pronoun_code"]),
        other_pronouns=cast("str", form.cleaned_data["other_pronouns"]),
        bio=cast("str", form.cleaned_data["bio"]),
        spoken_language_codes=tuple(
            cast("list[str]", form.cleaned_data["spoken_language_codes"])
        ),
        profile_photo=(
            profile_upload if isinstance(profile_upload, UploadedFile) else None
        ),
        reuse_profile_photo_id=cast(
            "UUID | None",
            form.cleaned_data["reuse_profile_photo_id"],
        ),
        keep_profile_photo=not bool(form.cleaned_data["remove_profile_photo"]),
        brings_fursuits=bool(form.cleaned_data["brings_fursuits"]),
        fursuits=tuple(fursuits),
        directory_visible=bool(form.cleaned_data["directory_visible"]),
        directory_country_code=cast(
            "str",
            form.cleaned_data["directory_country_code"],
        ),
        guardian_name=cast("str", form.cleaned_data["guardian_name"]),
        guardian_email=cast("str", form.cleaned_data["guardian_email"]),
        guardian_relationship=cast(
            "str",
            form.cleaned_data["guardian_relationship"],
        ),
        guardian_notice_version=cast(
            "str",
            form.cleaned_data["guardian_notice_version"],
        ),
    )


def _profile_initial(
    profile: AttendeeRegistrationProfile,
    *,
    reuse_approved_media: bool,
) -> dict[str, object]:
    return {
        "real_name": profile.real_name,
        "date_of_birth": profile.date_of_birth,
        "address_line_1": profile.address_line_1,
        "address_line_2": profile.address_line_2,
        "locality": profile.locality,
        "postal_code": profile.postal_code,
        "region": profile.region,
        "country_code": profile.country_code,
        "emergency_contact_name": profile.emergency_contact_name,
        "emergency_contact_phone": profile.emergency_contact_phone,
        "phone_number": profile.phone_number,
        "telegram_handle": profile.telegram_handle,
        "pronoun_code": profile.pronoun_code,
        "other_pronouns": profile.other_pronouns,
        "bio": profile.bio,
        "spoken_language_codes": profile.spoken_language_codes,
        "brings_fursuits": profile.brings_fursuits,
        "reuse_profile_photo_id": (
            profile.id
            if reuse_approved_media
            and profile.profile_photo
            and profile.profile_photo_status == MediaReviewStatus.APPROVED
            else None
        ),
        "keep_profile_photo": not reuse_approved_media,
        # Public-list consent is edition-specific and is never preselected.
        "directory_visible": (
            profile.directory_visible if not reuse_approved_media else False
        ),
        "directory_country_code": (
            profile.directory_country_code if not reuse_approved_media else ""
        ),
    }


def _fursuit_initial(
    profile: AttendeeRegistrationProfile,
    *,
    reuse_approved_media: bool,
) -> list[dict[str, object]]:
    return [
        {
            "fursuit_id": None if reuse_approved_media else fursuit.id,
            "reuse_from_id": (
                fursuit.id
                if reuse_approved_media
                and fursuit.photo
                and fursuit.photo_status == MediaReviewStatus.APPROVED
                else None
            ),
            "name": fursuit.name,
            "species": fursuit.species,
            "keep_photo": not reuse_approved_media,
        }
        for fursuit in profile.fursuits.all()
        if fursuit.is_active
    ]


def public_registration_form(
    request: HttpRequest,
    edition_id: UUID,
) -> HttpResponse:
    """Create an account if needed and submit one edition registration.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    edition_id : UUID
        The event edition identifier that scopes the operation.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    """
    configuration = _open_configurations().filter(edition_id=edition_id).first()
    if configuration is None:
        raise Http404("Registration is not available.")
    account = _account(request)
    if not settings.ALLOW_PROVISIONAL_PUBLIC_REGISTRATION and (
        account is None or not account.has_verified_email
    ):
        if account is None:
            account_form = PublicAccountBootstrapForm(request.POST or None)
            if request.method == "POST" and account_form.is_valid():
                bootstrap_account(
                    email=cast("str", account_form.cleaned_data["email"]),
                    display_name=cast("str", account_form.cleaned_data["display_name"]),
                    password=cast("str", account_form.cleaned_data["password1"]),
                    fingerprint=request_fingerprint(
                        request,
                        contact=cast("str", account_form.cleaned_data["email"]),
                    ),
                    source_channel="reference_client",
                )
                return TemplateResponse(
                    request,
                    "registration/account_verification_sent.html",
                    {"edition": configuration.edition},
                )
        else:
            account_form = None
            if request.method == "POST":
                issue_identity_challenge(
                    account=account,
                    purpose=IdentityChallenge.Purpose.VERIFY_EMAIL,
                    fingerprint=request_fingerprint(
                        request,
                        contact=account.email,
                    ),
                    source_channel="reference_client",
                )
                return TemplateResponse(
                    request,
                    "registration/account_verification_sent.html",
                    {"edition": configuration.edition},
                )
        return TemplateResponse(
            request,
            "registration/account_verification_gate.html",
            {
                "configuration": configuration,
                "account": account,
                "account_form": account_form,
                "sign_in_url": (
                    f"{reverse('staff-login')}?{urlencode({'next': request.path})}"
                ),
            },
        )
    if (
        account is not None
        and Registration.objects.filter(
            account=account,
            edition_id=edition_id,
        ).exists()
    ):
        return redirect("public-registration-profile", edition_id=edition_id)

    suggested_profile = (
        latest_profile_suggestion(
            account=account,
            organization_id=configuration.organization_id,
            target_edition=configuration.edition,
        )
        if account is not None
        else None
    )
    profile_initial = (
        _profile_initial(suggested_profile, reuse_approved_media=True)
        if suggested_profile is not None
        else None
    )
    fursuit_initial = (
        _fursuit_initial(suggested_profile, reuse_approved_media=True)
        if suggested_profile is not None
        else None
    )
    form = PublicRegistrationForm(
        request.POST or None,
        request.FILES or None,
        configuration=configuration,
        include_account_fields=account is None,
        account=account,
        initial=profile_initial,
    )
    raw_brings_fursuits = (
        request.POST.get("brings_fursuits") in ("on", "true", "1")
        if request.method == "POST"
        else bool(profile_initial and profile_initial.get("brings_fursuits"))
    )
    fursuit_formset = attendee_fursuit_formset(
        request.POST or None,
        request.FILES or None,
        initial=fursuit_initial,
        prefix="fursuits",
        brings_fursuits=raw_brings_fursuits,
    )
    form_valid = form.is_valid() if request.method == "POST" else False
    fursuits_valid = fursuit_formset.is_valid() if request.method == "POST" else False
    if request.method == "POST" and form_valid and fursuits_valid:
        product = cast("AdmissionProduct", form.cleaned_data["product"])
        try:
            result = submit_public_registration(
                organization_id=configuration.organization_id,
                edition_id=configuration.edition_id,
                product_id=product.id,
                answers=form.registration_answers(),
                profile_input=_profile_input(form, fursuit_formset),
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
                account=account,
                email=cast("str", form.cleaned_data.get("email", "")),
                display_name=cast("str", form.cleaned_data.get("display_name", "")),
                password=cast("str", form.cleaned_data.get("password1", "")),
            )
        except (IntegrityError, ObjectDoesNotExist, ValidationError) as error:
            message = (
                error.messages[0]
                if isinstance(error, ValidationError) and error.messages
                else "Registration could not be completed. Review the form or sign in."
            )
            form.add_error(None, message)
        else:
            if result.account_created:
                login(request, result.account)
            return redirect(
                "public-registration-profile",
                edition_id=configuration.edition_id,
            )

    return TemplateResponse(
        request,
        "registration/public_form.html",
        {
            "configuration": configuration,
            "form": form,
            "fursuit_formset": fursuit_formset,
            "account": account,
            "suggested_profile": suggested_profile,
            "product_choices": [
                {
                    "product": product,
                    "availability": assess_product_availability(
                        product=product,
                        account=account,
                    ),
                }
                for product in configuration.products.all()
            ],
            "dynamic_groups": _dynamic_groups(form),
            "field_policy": PROFILE_FIELD_POLICY,
            "sign_in_url": (
                f"{reverse('staff-login')}?{urlencode({'next': request.path})}"
            ),
        },
    )


def _submitted_groups(registration: Registration) -> list[dict[str, object]]:
    submission = registration.submission
    groups: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "title": "Convention questions",
            "description": "",
            "answers": [],
        }
    )
    order: list[str] = []
    for item in submission.schema_snapshot:
        if not isinstance(item, dict):
            continue
        section = item.get("section")
        key = "convention-questions"
        if isinstance(section, dict):
            key = str(section.get("key", key))
            groups[key]["title"] = str(section.get("title", "Convention questions"))
            groups[key]["description"] = str(section.get("description", ""))
        if key not in order:
            order.append(key)
        answer = submission.answers.get(item.get("key"))
        if answer is not None:
            if isinstance(answer, list):
                display_value = ", ".join(str(value) for value in answer)
            elif isinstance(answer, bool):
                display_value = "Yes" if answer else "No"
            else:
                display_value = str(answer)
            cast("list[dict[str, object]]", groups[key]["answers"]).append(
                {
                    "label": str(item.get("label", item.get("key", "Question"))),
                    "value": display_value,
                }
            )
    return [groups[key] for key in order if groups[key]["answers"]]


@login_required(login_url="staff-login")
def confirm_local_demo_payment(
    request: HttpRequest,
    edition_id: UUID,
) -> HttpResponse:
    """Offer the local-only payment simulator through the reference frontend.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    edition_id : UUID
        The event edition identifier that scopes the operation.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    """
    if request.method != "POST" or not settings.DEMO_PAYMENT_ADAPTER_ENABLED:
        raise Http404
    account = _account(request)
    if account is None:
        raise Http404
    registration = get_object_or_404(
        Registration,
        account=account,
        edition_id=edition_id,
    )
    form = DemoPaymentForm(request.POST)
    if form.is_valid():
        idempotency_key = cast("UUID", form.cleaned_data["idempotency_key"])
    elif set(request.POST) <= {"csrfmiddlewaretoken"}:
        # Backward-compatible local test control; rendered forms always submit
        # the retained key so browser retries remain deterministic.
        idempotency_key = uuid4()
    else:
        raise Http404
    try:
        confirm_demo_payment(
            organization_id=registration.organization_id,
            edition_id=registration.edition_id,
            actor=account,
            registration_id=registration.id,
            idempotency_key=idempotency_key,
            correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            source_channel="reference_web",
        )
    except ValidationError:
        raise Http404 from None
    return redirect("public-registration-profile", edition_id=edition_id)


@login_required(login_url="staff-login")
def reserve_local_tier_replacement(
    request: HttpRequest,
    edition_id: UUID,
) -> HttpResponse:
    """Reserve one higher admission tier from the attendee's profile page.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    edition_id : UUID
        The event edition identifier that scopes the operation.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    """
    if request.method != "POST":
        raise Http404
    account = _account(request)
    if account is None:
        raise Http404
    registration = get_object_or_404(
        Registration,
        account=account,
        edition_id=edition_id,
    )
    form = TierReplacementReservationForm(request.POST)
    if not form.is_valid():
        messages.error(request, "The admission upgrade request was invalid.")
        return redirect("public-registration-profile", edition_id=edition_id)
    try:
        result = reserve_admission_tier_replacement(
            organization_id=registration.organization_id,
            edition_id=registration.edition_id,
            registration_id=registration.id,
            target_product_id=cast("UUID", form.cleaned_data["target_product_id"]),
            actor=account,
            expected_registration_version=cast(
                "int",
                form.cleaned_data["expected_registration_version"],
            ),
            idempotency_key=cast("UUID", form.cleaned_data["idempotency_key"]),
            correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            source_channel="reference_web",
        )
    except (ObjectDoesNotExist, ValidationError):
        messages.error(request, "That admission upgrade is no longer available.")
    else:
        messages.success(
            request,
            (
                "Your admission upgrade is already reserved."
                if result.replayed
                else "Your admission upgrade is reserved until its payment deadline."
            ),
        )
    return redirect("public-registration-profile", edition_id=edition_id)


@login_required(login_url="staff-login")
def create_local_hosted_payment(
    request: HttpRequest,
    edition_id: UUID,
) -> HttpResponse:
    """Start hosted checkout for ordinary admission or a pending upgrade.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    edition_id : UUID
        The event edition identifier that scopes the operation.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    """
    if request.method != "POST":
        raise Http404
    account = _account(request)
    if account is None:
        raise Http404
    registration = get_object_or_404(
        Registration,
        account=account,
        edition_id=edition_id,
    )
    form = HostedPaymentStartForm(request.POST)
    if not form.is_valid():
        messages.error(request, "The payment request was invalid.")
        return redirect("public-registration-profile", edition_id=edition_id)
    try:
        intent = create_payment_intent(
            registration=registration,
            provider_account_id=cast(
                "UUID",
                form.cleaned_data["provider_account_id"],
            ),
            idempotency_key=cast("UUID", form.cleaned_data["idempotency_key"]),
            return_url=request.build_absolute_uri(
                reverse("public-registration-profile", args=(edition_id,))
            ),
        )
    except (ObjectDoesNotExist, ValidationError):
        messages.error(request, "Hosted payment is not available right now.")
        return redirect("public-registration-profile", edition_id=edition_id)
    if not intent.checkout_url:
        messages.error(request, "Hosted payment is waiting for reconciliation.")
        return redirect("public-registration-profile", edition_id=edition_id)
    return redirect(intent.checkout_url)


def _tier_replacement_options(
    *,
    registration: Registration,
    account: Account,
) -> tuple[dict[str, object], ...]:
    if (
        registration.state not in PAID_REGISTRATION_STATES
        or registration.confirmation_basis != Registration.ConfirmationBasis.PROVIDER
    ):
        return ()
    now = timezone.now()
    options: list[dict[str, object]] = []
    products = registration.configuration.products.filter(
        status=AdmissionProduct.Status.AVAILABLE,
        price_minor__gt=registration.product.price_minor,
    ).order_by("price_minor", "position", "id")
    for product in products:
        availability = assess_product_availability(
            product=product,
            account=account,
            at=now,
        )
        if not availability.selectable and availability.code != "capacity_reached":
            continue
        occupied = Registration.objects.filter(
            product=product,
            state__in=OCCUPIED_REGISTRATION_STATES,
        ).count()
        if occupied + pending_target_capacity_holds(
            product, at=now
        ) >= effective_product_capacity(product):
            continue
        options.append(
            {
                "product": product,
                "amount_due_minor": product.price_minor
                - registration.product.price_minor,
                "form": TierReplacementReservationForm(
                    initial={
                        "target_product_id": product.id,
                        "expected_registration_version": (
                            registration.aggregate_version
                        ),
                    }
                ),
            }
        )
    return tuple(options)


@login_required(login_url="staff-login")
def public_registration_profile(
    request: HttpRequest,
    edition_id: UUID,
) -> TemplateResponse:
    """Render public registration profile.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.

    Returns
    -------
    TemplateResponse
        The HTTP response for this request.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    """
    account = _account(request)
    if account is None:
        raise Http404
    registration = (
        Registration.objects.filter(account=account, edition_id=edition_id)
        .select_related(
            "edition",
            "edition__series",
            "product",
            "configuration",
            "participation",
            "submission",
        )
        .prefetch_related(
            "entitlements",
            "participation__capacities",
            Prefetch(
                "timeline",
                queryset=RegistrationTimelineEntry.objects.filter(
                    audience=RegistrationTimelineEntry.Audience.ATTENDEE_AND_STAFF
                ).order_by("sequence", "id"),
            ),
        )
        .first()
    )
    if registration is None:
        raise Http404
    profile = (
        AttendeeRegistrationProfile.objects.filter(
            registration=registration,
            account=account,
            edition_id=edition_id,
        )
        .select_related("account", "edition")
        .prefetch_related(
            Prefetch(
                "fursuits",
                queryset=AttendeeFursuit.objects.filter(is_active=True).order_by(
                    "position",
                    "id",
                ),
            )
        )
        .first()
    )
    capacities = [
        capacity
        for capacity in registration.participation.capacities.all()
        if capacity.status
        in (
            ParticipationCapacity.Status.PROPOSED,
            ParticipationCapacity.Status.ACTIVE,
        )
    ]
    entitlements = [
        entitlement
        for entitlement in registration.entitlements.all()
        if entitlement.status == Entitlement.Status.ACTIVE
    ]
    tier_replacement = (
        AdmissionTierReplacement.objects.filter(
            registration=registration,
            status=AdmissionTierReplacement.Status.PAYMENT_PENDING,
            payment_due_at__gt=timezone.now(),
        )
        .select_related("target_product")
        .first()
    )
    payment_available = (
        registration.state == Registration.State.PAYMENT_PENDING
        or tier_replacement is not None
    )
    providers = tuple(
        PaymentProviderAccount.objects.filter(
            organization_id=registration.organization_id,
            enabled=True,
        ).order_by("display_name", "id")
    )
    try:
        profile_extensions = read_profile_extension_values(
            actor=account,
            organization_id=registration.organization_id,
            edition_id=registration.edition_id,
            registration_id=registration.id,
            correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            source_channel="web",
        )
    except (DatabaseError, ProfileExtensionValueError):
        profile_extensions = None
    response = TemplateResponse(
        request,
        "registration/public_profile.html",
        {
            "registration": registration,
            "profile": profile,
            "profile_extensions": (
                profile_extensions.fields if profile_extensions is not None else ()
            ),
            "profile_extensions_editable": bool(
                profile_extensions is not None
                and any(field.can_write for field in profile_extensions.fields)
            ),
            "spoken_language_labels": (
                language_labels(profile.spoken_language_codes) if profile else []
            ),
            "profile_editable": (
                profile_is_editable(profile) if profile is not None else False
            ),
            "capacities": capacities,
            "entitlements": entitlements,
            "tier_replacement": tier_replacement,
            "tier_replacement_options": (
                ()
                if tier_replacement is not None
                else _tier_replacement_options(
                    registration=registration,
                    account=account,
                )
            ),
            "hosted_payment_options": tuple(
                {
                    "provider": provider,
                    "form": HostedPaymentStartForm(
                        initial={"provider_account_id": provider.id}
                    ),
                }
                for provider in providers
            )
            if payment_available
            else (),
            "demo_payment_form": DemoPaymentForm(),
            "submitted_groups": _submitted_groups(registration),
            "directory_allowed": registration.state in PAID_REGISTRATION_STATES,
            "local_demo_payment_available": (
                settings.DEMO_PAYMENT_ADAPTER_ENABLED and payment_available
            ),
            "waitlist_position": (
                Registration.objects.filter(
                    product=registration.product,
                    state=Registration.State.WAITLISTED,
                    waitlisted_at__lt=registration.waitlisted_at,
                ).count()
                + 1
                if registration.state == Registration.State.WAITLISTED
                and registration.waitlisted_at is not None
                else None
            ),
        },
    )
    response["Cache-Control"] = "private, no-store"
    response["Pragma"] = "no-cache"
    return response


@login_required(login_url="staff-login")
def edit_attendee_profile(
    request: HttpRequest,
    edition_id: UUID,
) -> HttpResponse:
    """Render edit attendee profile.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    """
    account = _account(request)
    if account is None:
        raise Http404
    profile = (
        AttendeeRegistrationProfile.objects.filter(
            account=account,
            edition_id=edition_id,
        )
        .select_related(
            "account",
            "edition",
            "registration",
            "registration__configuration",
        )
        .prefetch_related(
            Prefetch(
                "fursuits",
                queryset=AttendeeFursuit.objects.filter(is_active=True).order_by(
                    "position",
                    "id",
                ),
            )
        )
        .first()
    )
    if profile is None:
        raise Http404
    if not profile_is_editable(profile):
        return TemplateResponse(
            request,
            "registration/profile_edit_closed.html",
            {"profile": profile},
            status=409,
        )
    configuration = profile.registration.configuration
    initial = _profile_initial(profile, reuse_approved_media=False)
    fursuit_initial = _fursuit_initial(profile, reuse_approved_media=False)
    form = AttendeeProfileForm(
        request.POST or None,
        request.FILES or None,
        configuration=configuration,
        initial=initial,
    )
    raw_brings_fursuits = (
        request.POST.get("brings_fursuits") in ("on", "true", "1")
        if request.method == "POST"
        else profile.brings_fursuits
    )
    fursuit_formset = attendee_fursuit_formset(
        request.POST or None,
        request.FILES or None,
        initial=fursuit_initial,
        prefix="fursuits",
        brings_fursuits=raw_brings_fursuits,
    )
    form_valid = form.is_valid() if request.method == "POST" else False
    fursuits_valid = fursuit_formset.is_valid() if request.method == "POST" else False
    if request.method == "POST" and form_valid and fursuits_valid:
        try:
            update_attendee_profile(
                organization_id=profile.organization_id,
                edition_id=profile.edition_id,
                actor=account,
                profile_input=_profile_input(form, fursuit_formset),
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            )
        except (ObjectDoesNotExist, ValidationError) as error:
            message = (
                error.messages[0]
                if isinstance(error, ValidationError) and error.messages
                else "Your profile could not be updated. Review the form."
            )
            form.add_error(None, message)
        else:
            return redirect("public-registration-profile", edition_id=edition_id)

    return TemplateResponse(
        request,
        "registration/profile_edit.html",
        {
            "profile": profile,
            "configuration": configuration,
            "form": form,
            "fursuit_formset": fursuit_formset,
        },
    )


def public_attendee_directory(
    request: HttpRequest,
    edition_id: UUID,
) -> TemplateResponse:
    """Render public attendee directory.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.

    Returns
    -------
    TemplateResponse
        The HTTP response for this request.
    """
    edition = get_object_or_404(
        EventEdition.objects.select_related("organization", "series").exclude(
            lifecycle__in=(
                EventEdition.Lifecycle.ARCHIVED,
                EventEdition.Lifecycle.CANCELLED,
            )
        ),
        id=edition_id,
    )
    profiles = (
        AttendeeRegistrationProfile.objects.filter(
            edition_id=edition_id,
            directory_visible=True,
            registration__state__in=PAID_REGISTRATION_STATES,
        )
        .select_related(
            "account",
            "edition",
            "registration",
            "registration__participation",
            "registration__product",
        )
        .prefetch_related(
            Prefetch(
                "fursuits",
                queryset=AttendeeFursuit.objects.filter(is_active=True).order_by(
                    "position",
                    "id",
                ),
            ),
            "registration__entitlements",
            "registration__participation__capacities",
        )
        .order_by("account__display_name", "id")
    )
    try:
        extension_values = read_directory_profile_extension_values(
            actor=_account(request),
            organization_id=edition.organization_id,
            edition_id=edition.id,
            correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            source_channel="web",
        )
    except (DatabaseError, ProfileExtensionValueError):
        extension_values = {}
    public_profiles = [
        {
            "profile": profile,
            "language_labels": language_labels(profile.spoken_language_codes),
            "attendance_labels": (
                attendance_labels(profile.registration)
                if profile.directory_consent_version == DIRECTORY_CONSENT_VERSION
                else ()
            ),
            "extension_values": extension_values.get(profile.registration_id, ()),
        }
        for profile in profiles
    ]
    return TemplateResponse(
        request,
        "registration/paid_directory.html",
        {"edition": edition, "public_profiles": public_profiles},
    )


def _moderator_access(
    *,
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    target_type: str,
    target_id: UUID,
) -> bool:
    account = _account(request)
    if account is None:
        return False
    decision = decide(
        principal=account,
        capability_code="registration.moderate_public_profile",
        resource=resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
        requested_fields=frozenset({"image"}),
    )
    if not decision.allowed:
        return False
    correlation_id = UUID(request.correlation_id)  # type: ignore[attr-defined]
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=account.id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code="registration.moderate_public_profile",
            operation="registration.profile_media.preview",
            target_type=target_type,
            target_id=target_id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=decision.reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="public_web",
            obligations=tuple(sorted(decision.obligations)),
            safe_metadata={"policy_version": POLICY_VERSION},
            retention_class="security-extended",
        )
    )
    return True


def _image_response(
    *,
    image: object,
    public: bool,
) -> FileResponse:
    image_name = str(image.name)  # type: ignore[attr-defined]
    content_type = mimetypes.guess_type(image_name)[0] or "application/octet-stream"
    response = FileResponse(
        image.open("rb"),  # type: ignore[attr-defined]
        content_type=content_type,
        as_attachment=False,
        filename=Path(image_name).name,
    )
    response["Cache-Control"] = (
        "public, max-age=3600" if public else "private, no-store"
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response


def protected_profile_photo(
    request: HttpRequest,
    profile_id: UUID,
) -> FileResponse:
    """Render protected profile photo.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    profile_id : UUID
        The identifier of the profile.

    Returns
    -------
    FileResponse
        The HTTP response for this request.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    """
    account = _account(request)
    profile = (
        AttendeeRegistrationProfile.objects.filter(id=profile_id)
        .select_related("account", "registration")
        .first()
    )
    if profile is None or not profile.profile_photo:
        raise Http404
    self_access = account is not None and profile.account_id == account.id
    public_access = (
        profile.directory_visible
        and profile.registration.state in PAID_REGISTRATION_STATES
        and profile.profile_photo_status == MediaReviewStatus.APPROVED
        and media_is_safe(
            media_kind="profile_photo",
            media_id=profile.id,
            storage_name=profile.profile_photo.name,
        )
    )
    moderator_access = False
    if not self_access and not public_access:
        moderator_access = _moderator_access(
            request=request,
            organization_id=profile.organization_id,
            edition_id=profile.edition_id,
            target_type="registration.attendee_profile",
            target_id=profile.id,
        )
    if not self_access and not public_access and not moderator_access:
        raise Http404
    return _image_response(
        image=profile.profile_photo,
        public=public_access,
    )


def protected_fursuit_photo(
    request: HttpRequest,
    fursuit_id: UUID,
) -> FileResponse:
    """Render protected fursuit photo.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    fursuit_id : UUID
        The identifier of the fursuit.

    Returns
    -------
    FileResponse
        The HTTP response for this request.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    """
    account = _account(request)
    fursuit = (
        AttendeeFursuit.objects.filter(id=fursuit_id)
        .select_related("profile", "account", "registration")
        .first()
    )
    if fursuit is None or not fursuit.photo:
        raise Http404
    self_access = account is not None and fursuit.account_id == account.id
    public_access = (
        fursuit.is_active
        and fursuit.profile.directory_visible
        and fursuit.registration.state in PAID_REGISTRATION_STATES
        and fursuit.photo_status == MediaReviewStatus.APPROVED
        and media_is_safe(
            media_kind="fursuit_photo",
            media_id=fursuit.id,
            storage_name=fursuit.photo.name,
        )
    )
    moderator_access = False
    if not self_access and not public_access:
        moderator_access = _moderator_access(
            request=request,
            organization_id=fursuit.organization_id,
            edition_id=fursuit.edition_id,
            target_type="registration.attendee_fursuit",
            target_id=fursuit.id,
        )
    if not self_access and not public_access and not moderator_access:
        raise Http404
    return _image_response(image=fursuit.photo, public=public_access)
