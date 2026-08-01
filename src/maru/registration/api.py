"""Policy-scoped registration configuration, self-service, and staff APIs."""

import hashlib
import json
from datetime import date, datetime
from typing import cast
from urllib.parse import urlsplit
from uuid import UUID

from django.conf import settings
from django.core.exceptions import (
    ObjectDoesNotExist,
)
from django.core.exceptions import (
    ValidationError as DjangoValidationError,
)
from django.core.files.uploadedfile import UploadedFile
from django.db.models import Count, Max, Model, Prefetch, Q, QuerySet, Sum
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import (
    NotFound,
    PermissionDenied,
)
from rest_framework.exceptions import (
    ValidationError as ApiValidationError,
)
from rest_framework.generics import GenericAPIView
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.enforcement import (
    FieldProjectionDeniedError,
    require_complete_projection,
)
from maru.authorization.policy import (
    PolicyDecision,
    decide,
    resolve_edition_target,
    resolve_owned_target,
    resolve_self_target,
)
from maru.authorization.services import AuthorizationDenied
from maru.communications.models import NotificationDelivery
from maru.core.pagination import StandardPageNumberPagination
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.identity.services import require_recent_step_up
from maru.participation.models import Participation
from maru.registration.availability import assess_product_availability
from maru.registration.finance import (
    approve_financial_operation,
    propose_financial_operation,
    reconcile_provider_settlement,
)
from maru.registration.guardians import accept_guardian_consent
from maru.registration.media import media_is_safe
from maru.registration.models import (
    AttendeeFursuit,
    AttendeeRegistrationProfile,
    ConfigurationStatus,
    FinancialOperation,
    MediaReviewStatus,
    PaymentException,
    PaymentIntent,
    PaymentProviderAccount,
    ProfileExtensionStatus,
    ProfileExtensionWriter,
    QuestionVisibility,
    ReceiptRecord,
    Registration,
    RegistrationConfiguration,
    RegistrationProfileExtensionField,
    RegistrationTemplate,
    RegistrationTimelineEntry,
    SettlementBatch,
    TemplateStatus,
)
from maru.registration.payments import (
    create_payment_intent,
    parse_verified_payment_event,
    reconcile_verified_payment_event,
    resolve_payment_exception,
)
from maru.registration.presentation import attendance_labels
from maru.registration.profile_choices import (
    LANGUAGE_CHOICES,
    LANGUAGE_LABELS,
    MAX_BIO_LENGTH,
    MAX_FURSUITS,
    MAX_SPOKEN_LANGUAGES,
    OTHER_PRONOUN_CODE,
    PRONOUN_CHOICES,
)
from maru.registration.profile_policy import (
    COLLECTION_NOTICE_VERSION,
    DIRECTORY_CONSENT_VERSION,
)
from maru.registration.reporting import (
    COMING_STATES,
    MAX_SYNCHRONOUS_REPORT_ROWS,
    AttendeeReportFilters,
    attendee_report_queryset,
    attendee_report_rows,
    attendee_report_summary,
    badge_export_csv,
    filter_attendee_report_rows,
)
from maru.registration.serializers import (
    ActionItemSerializer,
    ActivateConfigurationSerializer,
    ApproveFinancialOperationSerializer,
    AttendeeReportQuerySerializer,
    AttendeeReportSerializer,
    ChangePaymentDeadlineSerializer,
    CheckInSerializer,
    CreateConfigurationDraftSerializer,
    CreatePaymentIntentSerializer,
    DemoPaymentSerializer,
    FinancialOperationSerializer,
    GuardianConsentAcceptSerializer,
    HeadlessRegistrationSubmissionSerializer,
    MyRegistrationWorkspaceSerializer,
    PaymentExceptionSerializer,
    PaymentIntentSerializer,
    ProfileExtensionWorkspaceSerializer,
    ProfileMediaReviewDecisionSerializer,
    ProfileMediaReviewItemSerializer,
    ProposeFinancialOperationSerializer,
    PublicAttendeeSerializer,
    PublicRegistrationDefinitionSerializer,
    PublicRegistrationEditionSerializer,
    PublishTemplateSerializer,
    ReceiptRecordSerializer,
    ReconcileSettlementSerializer,
    RegistrationConfigurationSerializer,
    RegistrationConfigurationWorkspaceSerializer,
    RegistrationReconciliationSerializer,
    RegistrationTemplateSummarySerializer,
    ResolvePaymentExceptionSerializer,
    SelfAttendeeProfileSerializer,
    SelfProfileImageUploadSerializer,
    SelfProfileSuggestionSerializer,
    SelfRegistrationSerializer,
    SettlementBatchSerializer,
    StaffRegistrationListQuerySerializer,
    StaffRegistrationSerializer,
    SubmitRegistrationSerializer,
    UpdateSelfAttendeeProfileSerializer,
    WaivePaymentSerializer,
    WriteProfileExtensionValueSerializer,
)
from maru.registration.services import (
    AttendeeFursuitInput,
    AttendeeProfileInput,
    activate_configuration,
    check_in_registration,
    confirm_demo_payment,
    create_configuration_draft,
    current_profile_extension_values,
    extend_payment_deadline,
    latest_profile_suggestion,
    profile_is_editable,
    publish_configuration_as_template,
    review_attendee_media,
    submit_public_registration,
    submit_registration,
    update_attendee_profile,
    waive_registration_payment,
    write_registration_profile_extension_value,
)

MANAGE_CONFIGURATION = "registration.manage_configuration"
VIEW_SERVICE = "registration.view_service_summary"
VIEW_SELF = "registration.view_self"
VIEW_PAYMENT_SUMMARY = "registration.view_payment_summary"
VIEW_ATTENDEE_REPORTING = "registration.view_attendee_reporting"
MODERATE_PUBLIC_PROFILE = "registration.moderate_public_profile"
VIEW_SELF_PROFILE = "registration.view_self_profile"
REGISTER_ON_BEHALF = "registration.register_on_behalf"


def _open_public_configurations() -> QuerySet[RegistrationConfiguration]:
    now = timezone.now()
    return (
        RegistrationConfiguration.objects.filter(
            status=ConfigurationStatus.ACTIVE,
            opens_at__lte=now,
            closes_at__gt=now,
        )
        .exclude(edition__lifecycle__in=("archived", "cancelled"))
        .select_related("organization", "edition", "edition__series")
        .prefetch_related("sections", "questions__section", "products")
    )


class PublicRegistrationEditionListView(APIView):
    permission_classes = (AllowAny,)

    @extend_schema(
        operation_id="registration_list_public_editions",
        responses=PublicRegistrationEditionSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        del request
        items = [
            {
                "edition_id": configuration.edition_id,
                "organization_name": configuration.organization.name,
                "series_name": configuration.edition.series.name,
                "edition_name": configuration.edition.name,
                "starts_on": configuration.edition.starts_on,
                "ends_on": configuration.edition.ends_on,
                "time_zone": configuration.edition.time_zone,
                "registration_api_path": (
                    f"/api/v1/public/editions/{configuration.edition_id}/registration"
                ),
                "registration_web_path": f"/register/{configuration.edition_id}/",
                "attendee_api_path": (
                    f"/api/v1/public/editions/{configuration.edition_id}/attendees"
                ),
                "attendee_web_path": (
                    f"/register/{configuration.edition_id}/attendees/"
                ),
            }
            for configuration in _open_public_configurations().order_by(
                "edition__starts_on",
                "edition__name",
            )
        ]
        return Response(
            PublicRegistrationEditionSerializer(
                instance=items,  # type: ignore[arg-type]
                many=True,
            ).data
        )


class PublicRegistrationDefinitionView(APIView):
    permission_classes = (AllowAny,)

    @extend_schema(
        operation_id="registration_retrieve_public_definition",
        responses=PublicRegistrationDefinitionSerializer,
    )
    def get(self, request: Request, edition_id: UUID) -> Response:
        configuration = (
            _open_public_configurations().filter(edition_id=edition_id).first()
        )
        if configuration is None:
            raise NotFound(
                "Registration is unavailable.",
                code="registration_unavailable",
            )
        account = request.user if isinstance(request.user, Account) else None
        minor_policy = getattr(configuration, "minor_policy", None)
        products = []
        for product in configuration.products.all():
            availability = assess_product_availability(
                product=product,
                account=account,
            )
            products.append(
                {
                    "id": product.id,
                    "name": product.name,
                    "description": product.description,
                    "price_minor": product.price_minor,
                    "currency": configuration.currency,
                    "sales_open_at": product.sales_open_at,
                    "sales_close_at": product.sales_close_at,
                    "selectable": availability.selectable,
                    "availability_code": availability.code,
                    "availability_explanation": availability.explanation,
                    "waitlist": availability.waitlist,
                }
            )
        payload = {
            "edition_id": configuration.edition_id,
            "organization_name": configuration.organization.name,
            "series_name": configuration.edition.series.name,
            "edition_name": configuration.edition.name,
            "starts_on": configuration.edition.starts_on,
            "ends_on": configuration.edition.ends_on,
            "time_zone": configuration.edition.time_zone,
            "configuration_version": configuration.version,
            "opens_at": configuration.opens_at,
            "closes_at": configuration.closes_at,
            "minimum_age": configuration.minimum_age,
            "default_payment_window_minutes": (
                configuration.default_payment_window_minutes
            ),
            "waitlist_enabled": configuration.waitlist_enabled,
            "client_contract": {
                "api_version": "v1",
                "csrf_api": "/api/v1/public/csrf",
                "account_bootstrap_api": "/api/v1/public/accounts",
                "session_api": "/api/v1/public/sessions",
                "submission_api": (
                    f"/api/v1/public/editions/{configuration.edition_id}/"
                    "registration/submissions"
                ),
                "authentication": (
                    "Cookie session plus CSRF token for browser clients"
                ),
                "browser_origin_policy": (
                    "Use the Maru origin or an HTTPS origin explicitly approved "
                    "by the deployment; wildcard credentialed access is forbidden"
                ),
                "payment_return_is_proof": False,
            },
            "profile_contract": {
                "snapshot_scope": "one immutable historical profile per edition",
                "suggestion_mode": (
                    "authenticated clients may offer the latest prior profile "
                    "for explicit review; submission creates a separate snapshot"
                ),
                "pronoun_choices": [
                    {"code": code, "label": label} for code, label in PRONOUN_CHOICES
                ],
                "other_pronoun_code": OTHER_PRONOUN_CODE,
                "bio_max_length": MAX_BIO_LENGTH,
                "language_standard": "ISO 639-1",
                "language_choices": [
                    {"code": code, "label": label} for code, label in LANGUAGE_CHOICES
                ],
                "spoken_language_limit": MAX_SPOKEN_LANGUAGES,
                "fursuit_limit": MAX_FURSUITS,
                "multiple_fursuits": True,
                "new_media_review_status": MediaReviewStatus.PENDING,
                "approved_media_reusable": True,
                "public_attendee_list_requires_consent": True,
                "public_attendee_list_requires_confirmation": True,
                "public_attendee_country_is_optional": True,
                "public_attendee_labels_are_authoritative": True,
                "guardian_consent_supported": bool(
                    minor_policy is not None and minor_policy.enabled
                ),
                "guardian_age_threshold": (
                    minor_policy.minor_age_threshold
                    if minor_policy is not None and minor_policy.enabled
                    else None
                ),
                "guardian_notice_version": (
                    minor_policy.guardian_notice_version
                    if minor_policy is not None and minor_policy.enabled
                    else ""
                ),
            },
            "sections": configuration.sections.all(),
            "questions": configuration.questions.filter(
                visibility=QuestionVisibility.ATTENDEE_AND_STAFF
            ),
            "products": products,
        }
        return Response(PublicRegistrationDefinitionSerializer(payload).data)


class HeadlessRegistrationSubmissionView(APIView):
    """Complete JSON submission command for independently designed frontends."""

    @extend_schema(
        operation_id="registration_submit_headless",
        request=HeadlessRegistrationSubmissionSerializer,
        responses=dict,
    )
    def post(self, request: Request, edition_id: UUID) -> Response:
        account = _account(request)
        serializer = HeadlessRegistrationSubmissionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        configuration = (
            _open_public_configurations().filter(edition_id=edition_id).first()
        )
        if configuration is None:
            raise NotFound(
                "Registration is unavailable.",
                code="registration_unavailable",
            )
        if values["collection_notice_version"] != COLLECTION_NOTICE_VERSION:
            raise ApiValidationError(
                {
                    "detail": "Review the current registration privacy notice.",
                    "code": "collection_notice_changed",
                }
            )
        profile_values = cast(dict[str, object], values["profile"])
        directory_visible = bool(profile_values.get("directory_visible", False))
        supplied_directory_version = str(values.get("directory_consent_version", ""))
        if directory_visible and (
            supplied_directory_version != DIRECTORY_CONSENT_VERSION
        ):
            raise ApiValidationError(
                {
                    "detail": "Review the current public attendee-list consent.",
                    "code": "directory_consent_changed",
                }
            )
        if not directory_visible and supplied_directory_version:
            raise ApiValidationError(
                {
                    "detail": "Do not send attendee-list consent when it is off.",
                    "code": "directory_consent_not_applicable",
                }
            )
        canonical = json.dumps(
            values,
            default=str,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        fursuits = tuple(
            AttendeeFursuitInput(
                name=str(item["name"]),
                species=str(item.get("species", "")),
                reuse_from_id=cast(UUID | None, item.get("reuse_from_id")),
            )
            for item in cast(
                list[dict[str, object]],
                profile_values.get("fursuits", []),
            )
        )
        profile_input = AttendeeProfileInput(
            real_name=str(profile_values["real_name"]),
            date_of_birth=cast(date, profile_values["date_of_birth"]),
            address_line_1=str(profile_values["address_line_1"]),
            address_line_2=str(profile_values.get("address_line_2", "")),
            locality=str(profile_values["locality"]),
            postal_code=str(profile_values["postal_code"]),
            region=str(profile_values["region"]),
            country_code=str(profile_values["country_code"]),
            emergency_contact_name=str(profile_values["emergency_contact_name"]),
            emergency_contact_phone=str(profile_values["emergency_contact_phone"]),
            phone_number=str(profile_values["phone_number"]),
            telegram_handle=str(profile_values.get("telegram_handle", "")),
            pronoun_code=str(profile_values["pronoun_code"]),
            other_pronouns=str(profile_values.get("other_pronouns", "")),
            bio=str(profile_values.get("bio", "")),
            spoken_language_codes=tuple(
                cast(list[str], profile_values["spoken_language_codes"])
            ),
            profile_photo=None,
            reuse_profile_photo_id=cast(
                UUID | None,
                profile_values.get("reuse_profile_photo_id"),
            ),
            keep_profile_photo=False,
            brings_fursuits=bool(profile_values["brings_fursuits"]),
            fursuits=fursuits,
            directory_visible=directory_visible,
            directory_country_code=str(
                profile_values.get("directory_country_code", "")
            ).upper(),
            guardian_name=str(
                cast(dict[str, object], profile_values.get("guardian", {})).get(
                    "name",
                    "",
                )
            ),
            guardian_email=str(
                cast(dict[str, object], profile_values.get("guardian", {})).get(
                    "email",
                    "",
                )
            ),
            guardian_relationship=str(
                cast(dict[str, object], profile_values.get("guardian", {})).get(
                    "relationship",
                    "",
                )
            ),
            guardian_notice_version=str(
                cast(dict[str, object], profile_values.get("guardian", {})).get(
                    "notice_version",
                    "",
                )
            ),
        )
        try:
            result = submit_public_registration(
                organization_id=configuration.organization_id,
                edition_id=edition_id,
                product_id=cast(UUID, values["product_id"]),
                answers=values["answers"],
                profile_input=profile_input,
                correlation_id=_correlation_id(request),
                account=account,
                source_channel="public_api",
                idempotency_key=cast(UUID, values["idempotency_key"]),
                request_digest=digest,
                expected_configuration_version=cast(
                    int,
                    values["configuration_version"],
                ),
            )
        except AuthorizationDenied as error:
            raise PermissionDenied(
                "Registration is unavailable.",
                code=error.reason_code,
            ) from error
        except ObjectDoesNotExist as error:
            raise NotFound(
                "Registration is unavailable.",
                code="registration_unavailable",
            ) from error
        except DjangoValidationError as error:
            raise ApiValidationError(
                {
                    "detail": "The registration could not be submitted.",
                    "code": error.code or "invalid_registration_submission",
                }
            ) from error
        return Response(
            {
                "replayed": result.replayed,
                "registration": SelfRegistrationSerializer(result.registration).data,
                "profile": SelfAttendeeProfileSerializer(
                    _self_profile_payload(result.profile)
                ).data,
                "guardian_consent_required": result.guardian_consent_required,
                "guardian_test_token": result.guardian_test_token,
            },
            status=200 if result.replayed else 201,
        )


class PublicGuardianConsentView(APIView):
    permission_classes = (AllowAny,)

    @extend_schema(
        operation_id="registration_accept_guardian_consent",
        request=GuardianConsentAcceptSerializer,
        responses=dict,
    )
    def post(self, request: Request) -> Response:
        serializer = GuardianConsentAcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            registration = accept_guardian_consent(
                raw_token=serializer.validated_data["token"],
                guardian_name=serializer.validated_data["guardian_name"],
            )
        except DjangoValidationError as error:
            raise ApiValidationError(
                {
                    "detail": "Guardian consent could not be accepted.",
                    "code": error.code or "guardian_consent_invalid",
                }
            ) from error
        return Response(
            {
                "accepted": True,
                "registration_reference": registration.reference,
                "state": registration.state,
                "payment_due_at": registration.payment_due_at,
            }
        )


class PublicAttendeeListView(APIView):
    permission_classes = (AllowAny,)

    @extend_schema(
        operation_id="registration_list_public_attendees",
        responses=PublicAttendeeSerializer(many=True),
    )
    def get(self, request: Request, edition_id: UUID) -> Response:
        del request
        if (
            not EventEdition.objects.filter(id=edition_id)
            .exclude(
                lifecycle__in=(
                    EventEdition.Lifecycle.ARCHIVED,
                    EventEdition.Lifecycle.CANCELLED,
                )
            )
            .exists()
        ):
            raise NotFound("The attendee list is unavailable.")
        profiles = (
            AttendeeRegistrationProfile.objects.filter(
                edition_id=edition_id,
                directory_visible=True,
                registration__state__in=(
                    Registration.State.CONFIRMED,
                    Registration.State.CHECKED_IN,
                ),
            )
            .select_related(
                "account",
                "registration",
                "registration__participation",
                "registration__product",
            )
            .prefetch_related(
                Prefetch(
                    "fursuits",
                    queryset=AttendeeFursuit.objects.filter(is_active=True).order_by(
                        "position", "id"
                    ),
                ),
                "registration__entitlements",
                "registration__participation__capacities",
            )
            .order_by("account__display_name", "id")
        )
        payload = [
            {
                "display_name": profile.account.display_name,
                "pronouns": profile.pronouns,
                "bio": profile.bio,
                "spoken_languages": [
                    {"code": code, "label": LANGUAGE_LABELS[code]}
                    for code in profile.spoken_language_codes
                    if code in LANGUAGE_LABELS
                ],
                "profile_photo_url": (
                    f"/register/media/profile/{profile.id}/"
                    if profile.profile_photo
                    and profile.profile_photo_status == MediaReviewStatus.APPROVED
                    and media_is_safe(
                        media_kind="profile_photo",
                        media_id=profile.id,
                        storage_name=profile.profile_photo.name,
                    )
                    else None
                ),
                "country_code": (
                    profile.directory_country_code
                    if profile.directory_consent_version == DIRECTORY_CONSENT_VERSION
                    else ""
                ),
                "attendance_labels": (
                    [
                        label.as_dict()
                        for label in attendance_labels(profile.registration)
                    ]
                    if profile.directory_consent_version == DIRECTORY_CONSENT_VERSION
                    else []
                ),
                "fursuits": [
                    {
                        "name": fursuit.name,
                        "species": fursuit.species,
                        "photo_url": (
                            f"/register/media/fursuit/{fursuit.id}/"
                            if fursuit.photo
                            and fursuit.photo_status == MediaReviewStatus.APPROVED
                            and media_is_safe(
                                media_kind="fursuit_photo",
                                media_id=fursuit.id,
                                storage_name=fursuit.photo.name,
                            )
                            else None
                        ),
                    }
                    for fursuit in profile.fursuits.all()
                ],
            }
            for profile in profiles
        ]
        return Response(
            PublicAttendeeSerializer(instance=payload, many=True).data  # type: ignore[arg-type]
        )


class SelfProfileSuggestionView(APIView):
    @extend_schema(
        operation_id="registration_retrieve_self_profile_suggestion",
        responses={200: SelfProfileSuggestionSerializer, 204: None},
    )
    def get(self, request: Request, edition_id: UUID) -> Response:
        account = _account(request)
        configuration = (
            _open_public_configurations().filter(edition_id=edition_id).first()
        )
        if configuration is None:
            raise NotFound(
                "Registration is unavailable.",
                code="registration_unavailable",
            )
        requested_fields = frozenset(
            {
                "source_profile_id",
                "source_edition_id",
                "source_edition_name",
                "notice",
                "registration_identity",
                "address",
                "emergency_contact",
                "contact",
                "pronouns",
                "bio",
                "spoken_languages",
                "profile_media",
                "fursuits",
                "directory_visible",
                "directory_country",
            }
        )
        decision = _scope_decision(
            account=account,
            capability_code=VIEW_SELF_PROFILE,
            organization_id=configuration.organization_id,
            edition_id=edition_id,
            requested_fields=requested_fields,
            self_intent=True,
        )
        if not decision.allowed:
            raise PermissionDenied(
                "Your profile suggestion is unavailable.",
                code=decision.reason_code,
            )
        source = latest_profile_suggestion(
            account=account,
            organization_id=configuration.organization_id,
            target_edition=configuration.edition,
        )
        correlation_id = _correlation_id(request)
        _read_audit(
            account=account,
            organization_id=configuration.organization_id,
            edition_id=edition_id,
            correlation_id=correlation_id,
            capability_code=VIEW_SELF_PROFILE,
            operation="registration.profile_suggestion.retrieve",
            target_type="registration.attendee_profile",
            target_id=source.id if source is not None else None,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=decision.reason_code,
            obligations=decision.obligations,
            target_count=1 if source is not None else 0,
        )
        if source is None:
            return Response(status=204)
        reusable_profile_photo = bool(
            source.profile_photo
            and source.profile_photo_status == MediaReviewStatus.APPROVED
        )
        payload = {
            "source_profile_id": source.id,
            "source_edition_id": source.edition_id,
            "source_edition_name": source.edition.name,
            "notice": (
                "These are suggestions from a prior convention. Review them "
                "before submitting; the prior profile will not be changed."
            ),
            "real_name": source.real_name,
            "date_of_birth": source.date_of_birth,
            "address_line_1": source.address_line_1,
            "address_line_2": source.address_line_2,
            "locality": source.locality,
            "postal_code": source.postal_code,
            "region": source.region,
            "country_code": source.country_code,
            "emergency_contact_name": source.emergency_contact_name,
            "emergency_contact_phone": source.emergency_contact_phone,
            "phone_number": source.phone_number,
            "telegram_handle": source.telegram_handle,
            "pronoun_code": source.pronoun_code,
            "other_pronouns": source.other_pronouns,
            "bio": source.bio,
            "spoken_language_codes": source.spoken_language_codes,
            "brings_fursuits": source.brings_fursuits,
            "reuse_profile_photo_id": (source.id if reusable_profile_photo else None),
            "profile_photo_review_status": source.profile_photo_status,
            "profile_photo_url": (
                f"/register/media/profile/{source.id}/"
                if source.profile_photo
                else None
            ),
            "fursuits": [
                {
                    "reuse_from_id": (
                        fursuit.id
                        if fursuit.photo
                        and fursuit.photo_status == MediaReviewStatus.APPROVED
                        else None
                    ),
                    "name": fursuit.name,
                    "species": fursuit.species,
                    "photo_review_status": fursuit.photo_status,
                    "photo_url": (
                        f"/register/media/fursuit/{fursuit.id}/"
                        if fursuit.photo
                        else None
                    ),
                }
                for fursuit in source.fursuits.all()
            ],
            # Consent is always a fresh edition decision.
            "directory_visible": False,
            "directory_country_code": "",
        }
        return Response(SelfProfileSuggestionSerializer(payload).data)


def _account(request: Request) -> Account:
    if not isinstance(request.user, Account):
        raise TypeError("Authenticated principal is not a platform account")
    return request.user


def _require_step_up(request: Request, account: Account) -> None:
    if not settings.REQUIRE_PRIVILEGED_STEP_UP:
        return
    try:
        require_recent_step_up(account=account, request=request._request)
    except DjangoValidationError as error:
        raise ApiValidationError(
            {
                "detail": "Complete an extra sign-in check before this action.",
                "code": error.code or "step_up_required",
            }
        ) from error


def _correlation_id(request: Request) -> UUID:
    return UUID(request.correlation_id)  # type: ignore[attr-defined]


def _scope_decision(
    *,
    account: Account,
    capability_code: str,
    organization_id: UUID,
    edition_id: UUID,
    requested_fields: frozenset[str] | None = None,
    owned_resource: Model | None = None,
    self_intent: bool = False,
) -> PolicyDecision:
    if owned_resource is not None and self_intent:
        raise ValueError("Choose an owning record or a self-service intent.")
    if owned_resource is not None:
        target = resolve_owned_target(resource=owned_resource)
    elif self_intent:
        target = resolve_self_target(
            principal=account,
            organization_id=organization_id,
            edition_id=edition_id,
        )
    else:
        target = resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        )
    return decide(
        principal=account,
        capability_code=capability_code,
        resource=target,
        requested_fields=requested_fields,
    )


def _read_audit(
    *,
    account: Account,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    capability_code: str,
    operation: str,
    target_type: str,
    target_id: UUID | None,
    outcome: str,
    reason_code: str,
    obligations: frozenset[str],
    target_count: int | None = None,
) -> None:
    safe_metadata: dict[str, object] = {"policy_version": POLICY_VERSION}
    if target_count is not None:
        safe_metadata["target_count"] = target_count
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=account.id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code=capability_code,
            operation=operation,
            target_type=target_type,
            target_id=target_id,
            outcome=outcome,
            reason_code=reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="api",
            obligations=tuple(sorted(obligations)),
            safe_metadata=safe_metadata,
            retention_class="security-extended",
        )
    )


def _registration_queryset(
    *,
    organization_id: UUID,
    edition_id: UUID,
) -> QuerySet[Registration]:
    return (
        Registration.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .select_related("account", "product")
        .prefetch_related(
            "entitlements",
            Prefetch(
                "timeline",
                queryset=RegistrationTimelineEntry.objects.order_by(
                    "sequence",
                    "id",
                ),
            ),
        )
    )


def _self_profile(
    *,
    organization_id: UUID,
    edition_id: UUID,
    account: Account,
) -> AttendeeRegistrationProfile:
    profile = (
        AttendeeRegistrationProfile.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            account=account,
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
        raise NotFound("Your attendee profile is unavailable.")
    return profile


def _self_profile_payload(
    profile: AttendeeRegistrationProfile,
) -> dict[str, object]:
    return {
        "id": profile.id,
        "edition_id": profile.edition_id,
        "editable": profile_is_editable(profile),
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
        "pronouns": profile.pronouns,
        "bio": profile.bio,
        "spoken_language_codes": profile.spoken_language_codes,
        "brings_fursuits": profile.brings_fursuits,
        "profile_photo_review_status": profile.profile_photo_status,
        "profile_photo_review_note": profile.profile_photo_review_note,
        "profile_photo_url": (
            f"/register/media/profile/{profile.id}/" if profile.profile_photo else None
        ),
        "fursuits": [
            {
                "id": fursuit.id,
                "name": fursuit.name,
                "species": fursuit.species,
                "photo_review_status": fursuit.photo_status,
                "photo_review_note": fursuit.photo_review_note,
                "photo_url": (
                    f"/register/media/fursuit/{fursuit.id}/" if fursuit.photo else None
                ),
            }
            for fursuit in profile.fursuits.all()
        ],
        "directory_visible": profile.directory_visible,
        "directory_country_code": profile.directory_country_code,
    }


def _update_input(values: dict[str, object]) -> AttendeeProfileInput:
    photo_action = cast(str, values["profile_photo_action"])
    return AttendeeProfileInput(
        real_name=cast(str, values["real_name"]),
        date_of_birth=cast(date, values["date_of_birth"]),
        address_line_1=cast(str, values["address_line_1"]),
        address_line_2=cast(str, values["address_line_2"]),
        locality=cast(str, values["locality"]),
        postal_code=cast(str, values["postal_code"]),
        region=cast(str, values["region"]),
        country_code=cast(str, values["country_code"]).upper(),
        emergency_contact_name=cast(str, values["emergency_contact_name"]),
        emergency_contact_phone=cast(str, values["emergency_contact_phone"]),
        phone_number=cast(str, values["phone_number"]),
        telegram_handle=cast(str, values.get("telegram_handle", "")).lstrip("@"),
        pronoun_code=cast(str, values["pronoun_code"]),
        other_pronouns=cast(str, values.get("other_pronouns", "")),
        bio=cast(str, values.get("bio", "")),
        spoken_language_codes=tuple(cast(list[str], values["spoken_language_codes"])),
        profile_photo=None,
        reuse_profile_photo_id=cast(
            UUID | None,
            values.get("reuse_profile_photo_id"),
        ),
        keep_profile_photo=photo_action == "keep",
        brings_fursuits=cast(bool, values["brings_fursuits"]),
        fursuits=tuple(
            AttendeeFursuitInput(
                fursuit_id=cast(UUID | None, item.get("id")),
                reuse_from_id=cast(UUID | None, item.get("reuse_from_id")),
                name=cast(str, item["name"]),
                species=cast(str, item.get("species", "")),
                keep_photo=cast(bool, item.get("keep_photo", True)),
            )
            for item in cast(list[dict[str, object]], values["fursuits"])
        ),
        directory_visible=cast(bool, values["directory_visible"]),
        directory_country_code=cast(
            str,
            values.get("directory_country_code", ""),
        ).upper(),
    )


def _existing_input_with_upload(
    profile: AttendeeRegistrationProfile,
    *,
    profile_photo: UploadedFile | None = None,
    fursuit_photo_id: UUID | None = None,
    fursuit_photo: UploadedFile | None = None,
) -> AttendeeProfileInput:
    fursuits = tuple(
        AttendeeFursuitInput(
            fursuit_id=fursuit.id,
            name=fursuit.name,
            species=fursuit.species,
            photo=(fursuit_photo if fursuit.id == fursuit_photo_id else None),
            keep_photo=True,
        )
        for fursuit in profile.fursuits.all()
    )
    if fursuit_photo_id is not None and all(
        fursuit.fursuit_id != fursuit_photo_id for fursuit in fursuits
    ):
        raise NotFound("The fursuit is unavailable.")
    return AttendeeProfileInput(
        real_name=profile.real_name,
        date_of_birth=profile.date_of_birth,
        address_line_1=profile.address_line_1,
        address_line_2=profile.address_line_2,
        locality=profile.locality,
        postal_code=profile.postal_code,
        region=profile.region,
        country_code=profile.country_code,
        emergency_contact_name=profile.emergency_contact_name,
        emergency_contact_phone=profile.emergency_contact_phone,
        phone_number=profile.phone_number,
        telegram_handle=profile.telegram_handle,
        pronoun_code=profile.pronoun_code,
        other_pronouns=profile.other_pronouns,
        bio=profile.bio,
        spoken_language_codes=tuple(profile.spoken_language_codes),
        profile_photo=profile_photo,
        reuse_profile_photo_id=None,
        keep_profile_photo=True,
        brings_fursuits=profile.brings_fursuits,
        fursuits=fursuits,
        directory_visible=profile.directory_visible,
        directory_country_code=profile.directory_country_code,
    )


class MyAttendeeProfileView(APIView):
    @extend_schema(
        operation_id="registration_retrieve_self_attendee_profile",
        responses=SelfAttendeeProfileSerializer,
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        account = _account(request)
        profile = _self_profile(
            organization_id=organization_id,
            edition_id=edition_id,
            account=account,
        )
        decision = _scope_decision(
            account=account,
            capability_code=VIEW_SELF_PROFILE,
            organization_id=organization_id,
            edition_id=edition_id,
            owned_resource=profile,
        )
        if not decision.allowed:
            raise PermissionDenied(
                "Your attendee profile is unavailable.",
                code=decision.reason_code,
            )
        _read_audit(
            account=account,
            organization_id=organization_id,
            edition_id=edition_id,
            correlation_id=_correlation_id(request),
            capability_code=VIEW_SELF_PROFILE,
            operation="registration.profile.retrieve",
            target_type="registration.attendee_profile",
            target_id=profile.id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=decision.reason_code,
            obligations=decision.obligations,
            target_count=1,
        )
        return Response(
            SelfAttendeeProfileSerializer(_self_profile_payload(profile)).data
        )

    @extend_schema(
        operation_id="registration_update_self_attendee_profile",
        request=UpdateSelfAttendeeProfileSerializer,
        responses=SelfAttendeeProfileSerializer,
    )
    def put(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        serializer = UpdateSelfAttendeeProfileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            profile = update_attendee_profile(
                organization_id=organization_id,
                edition_id=edition_id,
                actor=_account(request),
                profile_input=_update_input(serializer.validated_data),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        except DjangoValidationError as error:
            raise ApiValidationError(error.messages) from error
        profile = _self_profile(
            organization_id=organization_id,
            edition_id=edition_id,
            account=profile.account,
        )
        return Response(
            SelfAttendeeProfileSerializer(_self_profile_payload(profile)).data
        )


class MyProfilePhotoUploadView(APIView):
    parser_classes = (MultiPartParser, FormParser)

    @extend_schema(
        operation_id="registration_upload_self_profile_photo",
        request=SelfProfileImageUploadSerializer,
        responses=SelfAttendeeProfileSerializer,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        serializer = SelfProfileImageUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = _account(request)
        profile = _self_profile(
            organization_id=organization_id,
            edition_id=edition_id,
            account=account,
        )
        try:
            update_attendee_profile(
                organization_id=organization_id,
                edition_id=edition_id,
                actor=account,
                profile_input=_existing_input_with_upload(
                    profile,
                    profile_photo=cast(
                        UploadedFile,
                        serializer.validated_data["image"],
                    ),
                ),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        except DjangoValidationError as error:
            raise ApiValidationError(error.messages) from error
        refreshed = _self_profile(
            organization_id=organization_id,
            edition_id=edition_id,
            account=account,
        )
        return Response(
            SelfAttendeeProfileSerializer(_self_profile_payload(refreshed)).data
        )


class MyFursuitPhotoUploadView(APIView):
    parser_classes = (MultiPartParser, FormParser)

    @extend_schema(
        operation_id="registration_upload_self_fursuit_photo",
        request=SelfProfileImageUploadSerializer,
        responses=SelfAttendeeProfileSerializer,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        fursuit_id: UUID,
    ) -> Response:
        serializer = SelfProfileImageUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = _account(request)
        profile = _self_profile(
            organization_id=organization_id,
            edition_id=edition_id,
            account=account,
        )
        try:
            update_attendee_profile(
                organization_id=organization_id,
                edition_id=edition_id,
                actor=account,
                profile_input=_existing_input_with_upload(
                    profile,
                    fursuit_photo_id=fursuit_id,
                    fursuit_photo=cast(
                        UploadedFile,
                        serializer.validated_data["image"],
                    ),
                ),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        except DjangoValidationError as error:
            raise ApiValidationError(error.messages) from error
        refreshed = _self_profile(
            organization_id=organization_id,
            edition_id=edition_id,
            account=account,
        )
        return Response(
            SelfAttendeeProfileSerializer(_self_profile_payload(refreshed)).data
        )


class RegistrationConfigurationWorkspaceView(APIView):
    @extend_schema(
        operation_id="registration_retrieve_configuration_workspace",
        responses=RegistrationConfigurationWorkspaceSerializer,
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        account = _account(request)
        decision = _scope_decision(
            account=account,
            capability_code=MANAGE_CONFIGURATION,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        if not decision.allowed:
            raise PermissionDenied(
                "Registration configuration is unavailable.",
                code=decision.reason_code,
            )
        configurations = list(
            RegistrationConfiguration.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
            )
            .select_related("source_template", "source_edition")
            .prefetch_related("sections", "questions__section", "products")
            .order_by("-version")
        )
        active = next(
            (
                configuration
                for configuration in configurations
                if configuration.status == ConfigurationStatus.ACTIVE
            ),
            None,
        )
        drafts = [
            configuration
            for configuration in configurations
            if configuration.status == ConfigurationStatus.DRAFT
        ]
        templates = (
            RegistrationTemplate.objects.filter(
                organization_id=organization_id,
                status=TemplateStatus.PUBLISHED,
            )
            .filter(Q(series__isnull=True) | Q(series__event_editions__id=edition_id))
            .select_related("series")
            .annotate(
                question_count=Count("questions", distinct=True),
                product_count=Count("products", distinct=True),
            )
            .order_by("name", "-version")
            .distinct()
        )
        source_editions = list(
            RegistrationConfiguration.objects.filter(
                organization_id=organization_id,
                status__in=(
                    ConfigurationStatus.ACTIVE,
                    ConfigurationStatus.RETIRED,
                ),
            )
            .exclude(edition_id=edition_id)
            .values(
                "edition_id",
                "edition__name",
            )
            .annotate(latest_version=Max("version"))
            .order_by("-edition__starts_on")
        )
        return Response(
            {
                "active_configuration": (
                    RegistrationConfigurationSerializer(active).data
                    if active is not None
                    else None
                ),
                "drafts": RegistrationConfigurationSerializer(drafts, many=True).data,
                "templates": RegistrationTemplateSummarySerializer(
                    templates,
                    many=True,
                ).data,
                "source_editions": source_editions,
                "bootstrap_editor_path": "/admin/registration/",
            }
        )


class RegistrationConfigurationDraftView(APIView):
    @extend_schema(
        operation_id="registration_create_configuration_draft",
        request=CreateConfigurationDraftSerializer,
        responses={201: RegistrationConfigurationSerializer},
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        serializer = CreateConfigurationDraftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        try:
            configuration = create_configuration_draft(
                organization_id=organization_id,
                edition_id=edition_id,
                actor=_account(request),
                name=cast(str, values["name"]),
                correlation_id=_correlation_id(request),
                reason=cast(str, values["reason"]),
                source_template_id=cast(
                    UUID | None,
                    values.get("source_template_id"),
                ),
                source_edition_id=cast(
                    UUID | None,
                    values.get("source_edition_id"),
                ),
                opens_at=cast(object, values.get("opens_at")),  # type: ignore[arg-type]
                closes_at=cast(object, values.get("closes_at")),  # type: ignore[arg-type]
                capacity=cast(int | None, values.get("capacity")),
                currency=cast(str | None, values.get("currency")),
                minimum_age=cast(int | None, values.get("minimum_age")),
                default_payment_window_minutes=cast(
                    int | None,
                    values.get("default_payment_window_minutes"),
                ),
                waitlist_enabled=cast(
                    bool | None,
                    values.get("waitlist_enabled"),
                ),
                automatic_waitlist_promotion=cast(
                    bool | None,
                    values.get("automatic_waitlist_promotion"),
                ),
                source_channel="api",
            )
        except AuthorizationDenied as error:
            raise PermissionDenied(
                "Registration configuration is unavailable.",
                code=error.reason_code,
            ) from error
        except ObjectDoesNotExist as error:
            raise NotFound(
                "The registration configuration source is unavailable.",
                code="registration_configuration_source_unavailable",
            ) from error
        except DjangoValidationError as error:
            raise ApiValidationError(
                {
                    "detail": "The registration draft could not be created.",
                    "code": "invalid_registration_configuration",
                }
            ) from error
        configuration = (
            RegistrationConfiguration.objects.select_related(
                "source_template",
                "source_edition",
            )
            .prefetch_related("sections", "questions__section", "products")
            .get(id=configuration.id)
        )
        return Response(
            RegistrationConfigurationSerializer(configuration).data,
            status=201,
        )


class RegistrationConfigurationActivateView(APIView):
    @extend_schema(
        operation_id="registration_activate_configuration",
        request=ActivateConfigurationSerializer,
        responses=RegistrationConfigurationSerializer,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        serializer = ActivateConfigurationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            configuration = activate_configuration(
                organization_id=organization_id,
                edition_id=edition_id,
                configuration_id=serializer.validated_data["configuration_id"],
                actor=_account(request),
                reason=serializer.validated_data["reason"],
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        except AuthorizationDenied as error:
            raise PermissionDenied(
                "Registration configuration is unavailable.",
                code=error.reason_code,
            ) from error
        except ObjectDoesNotExist as error:
            raise NotFound(
                "The registration configuration is unavailable.",
                code="registration_configuration_unavailable",
            ) from error
        except DjangoValidationError as error:
            raise ApiValidationError(
                {
                    "detail": "The registration version could not be activated.",
                    "code": "invalid_registration_configuration",
                }
            ) from error
        configuration = (
            RegistrationConfiguration.objects.select_related(
                "source_template",
                "source_edition",
            )
            .prefetch_related("sections", "questions__section", "products")
            .get(id=configuration.id)
        )
        return Response(RegistrationConfigurationSerializer(configuration).data)


class RegistrationTemplatePublishView(APIView):
    @extend_schema(
        operation_id="registration_publish_template",
        request=PublishTemplateSerializer,
        responses={201: RegistrationTemplateSummarySerializer},
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        serializer = PublishTemplateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        try:
            template = publish_configuration_as_template(
                organization_id=organization_id,
                edition_id=edition_id,
                configuration_id=values["configuration_id"],
                actor=_account(request),
                code=values["code"],
                name=values["name"],
                description=values.get("description", ""),
                series_limited=values["series_limited"],
                reason=values["reason"],
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        except AuthorizationDenied as error:
            raise PermissionDenied(
                "Registration template publication is unavailable.",
                code=error.reason_code,
            ) from error
        except ObjectDoesNotExist as error:
            raise NotFound(
                "The registration configuration is unavailable.",
                code="registration_configuration_unavailable",
            ) from error
        except DjangoValidationError as error:
            raise ApiValidationError(
                {
                    "detail": "The registration template could not be published.",
                    "code": "invalid_registration_template",
                }
            ) from error
        template = (
            RegistrationTemplate.objects.filter(id=template.id)
            .select_related("series")
            .annotate(
                question_count=Count("questions", distinct=True),
                product_count=Count("products", distinct=True),
            )
            .get()
        )
        return Response(
            RegistrationTemplateSummarySerializer(template).data,
            status=201,
        )


def _profile_extension_registration(
    *,
    organization_id: UUID,
    edition_id: UUID,
    account: Account | None = None,
    registration_id: UUID | None = None,
) -> Registration:
    queryset = Registration.objects.filter(
        organization_id=organization_id,
        edition_id=edition_id,
    ).select_related("account")
    if account is not None:
        queryset = queryset.filter(account=account)
    if registration_id is not None:
        queryset = queryset.filter(id=registration_id)
    registration = queryset.first()
    if registration is None:
        raise NotFound(
            "The registration profile is unavailable.",
            code="registration_unavailable",
        )
    return registration


def _profile_extension_workspace_payload(
    *,
    registration: Registration,
    staff_view: bool,
) -> dict[str, object]:
    fields = RegistrationProfileExtensionField.objects.filter(
        organization_id=registration.organization_id,
        edition_id=registration.edition_id,
        status=ProfileExtensionStatus.ACTIVE,
    )
    if not staff_view:
        fields = fields.filter(attendee_visible=True)
    current_values = current_profile_extension_values(registration=registration)
    payload_fields = []
    for field in fields.order_by("position", "key", "id"):
        revision = current_values.get(field.key)
        can_write = (
            field.writer_policy
            in {
                ProfileExtensionWriter.REGISTRATION_STAFF,
                ProfileExtensionWriter.ATTENDEE_AND_STAFF,
            }
            if staff_view
            else field.writer_policy
            in {
                ProfileExtensionWriter.ATTENDEE,
                ProfileExtensionWriter.ATTENDEE_AND_STAFF,
            }
        )
        payload_fields.append(
            {
                "id": field.id,
                "key": field.key,
                "version": field.version,
                "label": field.label,
                "help_text": field.help_text,
                "field_type": field.field_type,
                "options": field.options,
                "purpose": field.purpose,
                "classification": field.classification,
                "required": field.required,
                "writer_policy": field.writer_policy,
                "can_write": can_write,
                "current_value": revision.value if revision is not None else None,
                "updated_at": revision.created_at if revision is not None else None,
            }
        )
    return {
        "registration_id": registration.id,
        "fields": payload_fields,
    }


class MyRegistrationProfileExtensionsView(APIView):
    """Current post-submission profile fields visible to the registration owner."""

    @extend_schema(
        operation_id="registration_retrieve_my_profile_extensions",
        responses=ProfileExtensionWorkspaceSerializer,
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        account = _account(request)
        registration = _profile_extension_registration(
            organization_id=organization_id,
            edition_id=edition_id,
            account=account,
        )
        decision = _scope_decision(
            account=account,
            capability_code=VIEW_SELF_PROFILE,
            organization_id=organization_id,
            edition_id=edition_id,
            owned_resource=registration,
        )
        if not decision.allowed:
            raise PermissionDenied(
                "Your registration profile is unavailable.",
                code=decision.reason_code,
            )
        payload = _profile_extension_workspace_payload(
            registration=registration,
            staff_view=False,
        )
        return Response(ProfileExtensionWorkspaceSerializer(payload).data)

    @extend_schema(
        operation_id="registration_write_my_profile_extension",
        request=WriteProfileExtensionValueSerializer,
        responses=ProfileExtensionWorkspaceSerializer,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        account = _account(request)
        registration = _profile_extension_registration(
            organization_id=organization_id,
            edition_id=edition_id,
            account=account,
        )
        serializer = WriteProfileExtensionValueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        field = RegistrationProfileExtensionField.objects.filter(
            id=serializer.validated_data["field_id"],
            organization_id=organization_id,
            edition_id=edition_id,
            status=ProfileExtensionStatus.ACTIVE,
            attendee_visible=True,
        ).first()
        if field is None:
            raise NotFound(
                "The profile field is unavailable.",
                code="profile_extension_field_unavailable",
            )
        try:
            write_registration_profile_extension_value(
                registration=registration,
                field=field,
                actor=account,
                value=serializer.validated_data["value"],
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        except AuthorizationDenied as error:
            raise PermissionDenied(str(error), code=error.reason_code) from error
        except DjangoValidationError as error:
            raise ApiValidationError(
                error.message_dict if hasattr(error, "message_dict") else error.messages
            ) from error
        payload = _profile_extension_workspace_payload(
            registration=registration,
            staff_view=False,
        )
        return Response(ProfileExtensionWorkspaceSerializer(payload).data)


class StaffRegistrationProfileExtensionsView(APIView):
    """Reasoned registration-staff projection and profile-field write."""

    def _registration_and_decision(
        self,
        *,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        registration_id: UUID,
    ) -> tuple[Account, Registration, PolicyDecision]:
        account = _account(request)
        decision = _scope_decision(
            account=account,
            capability_code=VIEW_SERVICE,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        if not decision.allowed:
            raise PermissionDenied(
                "The registration profile is unavailable.",
                code=decision.reason_code,
            )
        registration = _profile_extension_registration(
            organization_id=organization_id,
            edition_id=edition_id,
            registration_id=registration_id,
        )
        return account, registration, decision

    @extend_schema(
        operation_id="registration_retrieve_staff_profile_extensions",
        responses=ProfileExtensionWorkspaceSerializer,
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        registration_id: UUID,
    ) -> Response:
        account, registration, decision = self._registration_and_decision(
            request=request,
            organization_id=organization_id,
            edition_id=edition_id,
            registration_id=registration_id,
        )
        correlation_id = _correlation_id(request)
        _read_audit(
            account=account,
            organization_id=organization_id,
            edition_id=edition_id,
            correlation_id=correlation_id,
            capability_code=VIEW_SERVICE,
            operation="registration.profile_extensions.retrieve",
            target_type="registration.registration",
            target_id=registration.id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=decision.reason_code,
            obligations=decision.obligations,
        )
        payload = _profile_extension_workspace_payload(
            registration=registration,
            staff_view=True,
        )
        return Response(ProfileExtensionWorkspaceSerializer(payload).data)

    @extend_schema(
        operation_id="registration_write_staff_profile_extension",
        request=WriteProfileExtensionValueSerializer,
        responses=ProfileExtensionWorkspaceSerializer,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        registration_id: UUID,
    ) -> Response:
        account, registration, _ = self._registration_and_decision(
            request=request,
            organization_id=organization_id,
            edition_id=edition_id,
            registration_id=registration_id,
        )
        serializer = WriteProfileExtensionValueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        field = RegistrationProfileExtensionField.objects.filter(
            id=serializer.validated_data["field_id"],
            organization_id=organization_id,
            edition_id=edition_id,
            status=ProfileExtensionStatus.ACTIVE,
        ).first()
        if field is None:
            raise NotFound(
                "The profile field is unavailable.",
                code="profile_extension_field_unavailable",
            )
        try:
            write_registration_profile_extension_value(
                registration=registration,
                field=field,
                actor=account,
                value=serializer.validated_data["value"],
                correlation_id=_correlation_id(request),
                source_channel="api",
                reason=str(serializer.validated_data.get("reason", "")),
            )
        except AuthorizationDenied as error:
            raise PermissionDenied(str(error), code=error.reason_code) from error
        except DjangoValidationError as error:
            raise ApiValidationError(
                error.message_dict if hasattr(error, "message_dict") else error.messages
            ) from error
        payload = _profile_extension_workspace_payload(
            registration=registration,
            staff_view=True,
        )
        return Response(ProfileExtensionWorkspaceSerializer(payload).data)


class MyRegistrationView(APIView):
    @extend_schema(
        operation_id="registration_retrieve_my_registration",
        responses=MyRegistrationWorkspaceSerializer,
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        account = _account(request)
        decision = _scope_decision(
            account=account,
            capability_code=VIEW_SELF,
            organization_id=organization_id,
            edition_id=edition_id,
            self_intent=True,
        )
        if not decision.allowed:
            raise PermissionDenied(
                "Your registration is unavailable.",
                code=decision.reason_code,
            )
        participation = Participation.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            account=account,
        ).first()
        if participation is None:
            raise NotFound(
                "Your registration is unavailable.",
                code="registration_unavailable",
            )
        configuration = (
            RegistrationConfiguration.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
                status=ConfigurationStatus.ACTIVE,
            )
            .prefetch_related("sections", "questions__section", "products")
            .first()
        )
        registration = (
            _registration_queryset(
                organization_id=organization_id,
                edition_id=edition_id,
            )
            .filter(account=account)
            .first()
        )
        return Response(
            {
                "configuration": (
                    RegistrationConfigurationSerializer(configuration).data
                    if configuration is not None
                    else None
                ),
                "registration": (
                    SelfRegistrationSerializer(registration).data
                    if registration is not None
                    else None
                ),
                "demo_payment_enabled": settings.DEMO_PAYMENT_ADAPTER_ENABLED,
                "server_time": timezone.now(),
            }
        )

    @extend_schema(
        operation_id="registration_submit_my_registration",
        request=SubmitRegistrationSerializer,
        responses={201: SelfRegistrationSerializer},
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        serializer = SubmitRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            registration = submit_registration(
                organization_id=organization_id,
                edition_id=edition_id,
                actor=_account(request),
                product_id=serializer.validated_data["product_id"],
                answers=serializer.validated_data["answers"],
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        except AuthorizationDenied as error:
            raise PermissionDenied(
                "Registration is unavailable.",
                code=error.reason_code,
            ) from error
        except ObjectDoesNotExist as error:
            raise NotFound(
                "Registration is unavailable.",
                code="registration_unavailable",
            ) from error
        except DjangoValidationError as error:
            raise ApiValidationError(
                {
                    "detail": "The registration could not be submitted.",
                    "code": "invalid_registration_submission",
                }
            ) from error
        registration = _registration_queryset(
            organization_id=organization_id,
            edition_id=edition_id,
        ).get(id=registration.id)
        return Response(SelfRegistrationSerializer(registration).data, status=201)


class MyRegistrationDemoPaymentView(APIView):
    @extend_schema(
        operation_id="registration_confirm_my_demo_payment",
        request=DemoPaymentSerializer,
        responses=SelfRegistrationSerializer,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        registration_id: UUID,
    ) -> Response:
        serializer = DemoPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            registration = confirm_demo_payment(
                organization_id=organization_id,
                edition_id=edition_id,
                actor=_account(request),
                registration_id=registration_id,
                idempotency_key=serializer.validated_data["idempotency_key"],
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        except (AuthorizationDenied, Registration.DoesNotExist) as error:
            reason_code = (
                error.reason_code
                if isinstance(error, AuthorizationDenied)
                else "registration_unavailable"
            )
            raise NotFound(
                "The registration is unavailable.",
                code=reason_code,
            ) from error
        except DjangoValidationError as error:
            raise ApiValidationError(
                {
                    "detail": "The demo payment could not be confirmed.",
                    "code": "invalid_payment_state",
                }
            ) from error
        registration = _registration_queryset(
            organization_id=organization_id,
            edition_id=edition_id,
        ).get(id=registration.id)
        return Response(SelfRegistrationSerializer(registration).data)


class MyRegistrationPaymentIntentView(APIView):
    @extend_schema(
        operation_id="registration_create_my_payment_intent",
        request=CreatePaymentIntentSerializer,
        responses={200: PaymentIntentSerializer, 201: PaymentIntentSerializer},
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        registration_id: UUID,
    ) -> Response:
        account = _account(request)
        serializer = CreatePaymentIntentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        return_url = str(values["return_url"])
        parsed_return = urlsplit(return_url)
        return_origin = f"{parsed_return.scheme}://{parsed_return.netloc}"
        if return_origin not in set(settings.MARU_PAYMENT_RETURN_ORIGINS):
            raise ApiValidationError(
                {
                    "detail": "The payment return URL is not approved.",
                    "code": "payment_return_url_denied",
                }
            )
        try:
            registration = Registration.objects.get(
                id=registration_id,
                organization_id=organization_id,
                edition_id=edition_id,
                account=account,
            )
            existing = PaymentIntent.objects.filter(
                provider_account_id=values["provider_account_id"],
                idempotency_key=values["idempotency_key"],
            ).first()
            intent = create_payment_intent(
                registration=registration,
                provider_account_id=cast(UUID, values["provider_account_id"]),
                idempotency_key=cast(UUID, values["idempotency_key"]),
                return_url=return_url,
            )
        except ObjectDoesNotExist as error:
            raise NotFound(
                "The registration is unavailable.",
                code="registration_unavailable",
            ) from error
        except DjangoValidationError as error:
            raise ApiValidationError(
                {
                    "detail": "Hosted checkout could not be started.",
                    "code": error.code or "payment_intent_failed",
                }
            ) from error
        refreshed = PaymentIntent.objects.select_related("provider_account").get(
            id=intent.id
        )
        return Response(
            PaymentIntentSerializer(refreshed).data,
            status=200 if existing is not None else 201,
        )


class MyRegistrationPaymentIntentStatusView(APIView):
    @extend_schema(
        operation_id="registration_retrieve_my_payment_intent",
        responses=PaymentIntentSerializer,
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        registration_id: UUID,
        intent_id: UUID,
    ) -> Response:
        account = _account(request)
        intent = (
            PaymentIntent.objects.select_related("provider_account")
            .filter(
                id=intent_id,
                registration_id=registration_id,
                registration__account=account,
                organization_id=organization_id,
                edition_id=edition_id,
            )
            .first()
        )
        if intent is None:
            raise NotFound(
                "The payment attempt is unavailable.",
                code="payment_intent_unavailable",
            )
        return Response(PaymentIntentSerializer(intent).data)


class PaymentProviderWebhookView(APIView):
    permission_classes = (AllowAny,)
    authentication_classes: tuple[()] = ()

    @extend_schema(
        operation_id="registration_receive_payment_webhook",
        request=None,
        responses=dict,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        provider_code: str,
    ) -> Response:
        provider = PaymentProviderAccount.objects.filter(
            organization_id=organization_id,
            code=provider_code,
            enabled=True,
        ).first()
        if provider is None:
            raise NotFound("The payment endpoint is unavailable.")
        try:
            event, signed_at, payload_digest = parse_verified_payment_event(
                provider=provider,
                body=request.body,
                signature=request.headers.get("X-Maru-Signature", ""),
                timestamp=request.headers.get("X-Maru-Timestamp", ""),
            )
            receipt = reconcile_verified_payment_event(
                provider=provider,
                event=event,
                signed_at=signed_at,
                payload_digest=payload_digest,
                correlation_id=_correlation_id(request),
            )
        except DjangoValidationError as error:
            raise ApiValidationError(
                {
                    "detail": "The payment message was rejected.",
                    "code": error.code or "payment_webhook_rejected",
                }
            ) from error
        return Response(
            {
                "accepted": True,
                "outcome": receipt.outcome,
                "result_code": receipt.safe_result_code,
            }
        )


class StaffPaymentExceptionListView(APIView):
    @extend_schema(
        operation_id="registration_list_payment_exceptions",
        responses=PaymentExceptionSerializer(many=True),
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        account = _account(request)
        decision = _scope_decision(
            account=account,
            capability_code=VIEW_PAYMENT_SUMMARY,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        if not decision.allowed:
            raise PermissionDenied(
                "Payment exceptions are unavailable.",
                code=decision.reason_code,
            )
        items = (
            PaymentException.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
            )
            .select_related("provider_account", "payment_intent")
            .order_by("-opened_at", "-id")[:250]
        )
        return Response(PaymentExceptionSerializer(items, many=True).data)


class StaffPaymentExceptionResolveView(APIView):
    @extend_schema(
        operation_id="registration_resolve_payment_exception",
        request=ResolvePaymentExceptionSerializer,
        responses=PaymentExceptionSerializer,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        exception_id: UUID,
    ) -> Response:
        account = _account(request)
        _require_step_up(request, account)
        serializer = ResolvePaymentExceptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            item = resolve_payment_exception(
                actor=account,
                organization_id=organization_id,
                edition_id=edition_id,
                exception_id=exception_id,
                reason=serializer.validated_data["reason"],
                correlation_id=_correlation_id(request),
            )
        except AuthorizationDenied as error:
            raise PermissionDenied(
                "Payment exception resolution is unavailable.",
                code=error.reason_code,
            ) from error
        except ObjectDoesNotExist as error:
            raise NotFound("The payment exception is unavailable.") from error
        except DjangoValidationError as error:
            raise ApiValidationError(
                {
                    "detail": "The payment exception could not be resolved.",
                    "code": error.code or "payment_exception_invalid",
                }
            ) from error
        return Response(PaymentExceptionSerializer(item).data)


class MyRegistrationReceiptListView(APIView):
    @extend_schema(
        operation_id="registration_list_my_receipts",
        responses=ReceiptRecordSerializer(many=True),
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        registration_id: UUID,
    ) -> Response:
        account = _account(request)
        if not Registration.objects.filter(
            id=registration_id,
            organization_id=organization_id,
            edition_id=edition_id,
            account=account,
        ).exists():
            raise NotFound("The registration is unavailable.")
        items = ReceiptRecord.objects.filter(
            registration_id=registration_id,
            organization_id=organization_id,
            edition_id=edition_id,
        ).order_by("issued_at", "id")
        return Response(ReceiptRecordSerializer(items, many=True).data)


class StaffFinancialOperationListCreateView(APIView):
    @extend_schema(
        operation_id="registration_list_financial_operations",
        responses=FinancialOperationSerializer(many=True),
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        registration_id: UUID,
    ) -> Response:
        account = _account(request)
        decision = _scope_decision(
            account=account,
            capability_code=VIEW_PAYMENT_SUMMARY,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        if not decision.allowed:
            raise PermissionDenied(
                "Financial operations are unavailable.",
                code=decision.reason_code,
            )
        items = FinancialOperation.objects.filter(
            registration_id=registration_id,
            organization_id=organization_id,
            edition_id=edition_id,
        ).order_by("-requested_at", "-id")
        return Response(FinancialOperationSerializer(items, many=True).data)

    @extend_schema(
        operation_id="registration_propose_financial_operation",
        request=ProposeFinancialOperationSerializer,
        responses={201: FinancialOperationSerializer},
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        registration_id: UUID,
    ) -> Response:
        account = _account(request)
        _require_step_up(request, account)
        serializer = ProposeFinancialOperationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        try:
            operation = propose_financial_operation(
                organization_id=organization_id,
                edition_id=edition_id,
                registration_id=registration_id,
                actor=account,
                kind=str(values["kind"]),
                amount_minor=cast(int, values["amount_minor"]),
                target_account_id=cast(
                    UUID | None,
                    values.get("target_account_id"),
                ),
                target_product_id=cast(
                    UUID | None,
                    values.get("target_product_id"),
                ),
                reason=str(values["reason"]),
                correlation_id=_correlation_id(request),
            )
        except AuthorizationDenied as error:
            raise PermissionDenied(
                "Financial operations are unavailable.",
                code=error.reason_code,
            ) from error
        except ObjectDoesNotExist as error:
            raise NotFound("The registration is unavailable.") from error
        except DjangoValidationError as error:
            raise ApiValidationError(
                {
                    "detail": "The financial operation could not be proposed.",
                    "code": error.code or "financial_operation_invalid",
                }
            ) from error
        return Response(FinancialOperationSerializer(operation).data, status=201)


class StaffFinancialOperationApproveView(APIView):
    @extend_schema(
        operation_id="registration_approve_financial_operation",
        request=ApproveFinancialOperationSerializer,
        responses=FinancialOperationSerializer,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        operation_id: UUID,
    ) -> Response:
        account = _account(request)
        _require_step_up(request, account)
        serializer = ApproveFinancialOperationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            operation = approve_financial_operation(
                organization_id=organization_id,
                edition_id=edition_id,
                operation_id=operation_id,
                actor=account,
                reason=serializer.validated_data["reason"],
                correlation_id=_correlation_id(request),
            )
        except AuthorizationDenied as error:
            raise PermissionDenied(
                "Financial operations are unavailable.",
                code=error.reason_code,
            ) from error
        except ObjectDoesNotExist as error:
            raise NotFound("The financial operation is unavailable.") from error
        except DjangoValidationError as error:
            raise ApiValidationError(
                {
                    "detail": "The financial operation could not be approved.",
                    "code": error.code or "financial_operation_invalid",
                }
            ) from error
        return Response(FinancialOperationSerializer(operation).data)


class StaffSettlementListCreateView(APIView):
    @extend_schema(
        operation_id="registration_list_settlements",
        responses=SettlementBatchSerializer(many=True),
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        account = _account(request)
        decision = _scope_decision(
            account=account,
            capability_code=VIEW_PAYMENT_SUMMARY,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        if not decision.allowed:
            raise PermissionDenied(
                "Provider settlements are unavailable.",
                code=decision.reason_code,
            )
        items = SettlementBatch.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
        ).order_by("-settled_at", "-id")[:250]
        return Response(SettlementBatchSerializer(items, many=True).data)

    @extend_schema(
        operation_id="registration_reconcile_settlement",
        request=ReconcileSettlementSerializer,
        responses={201: SettlementBatchSerializer},
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        account = _account(request)
        _require_step_up(request, account)
        serializer = ReconcileSettlementSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        try:
            batch = reconcile_provider_settlement(
                actor=account,
                organization_id=organization_id,
                edition_id=edition_id,
                provider_account_id=cast(UUID, values["provider_account_id"]),
                provider_reference=str(values["provider_reference"]),
                currency=str(values["currency"]),
                gross_minor=cast(int, values["gross_minor"]),
                fee_minor=cast(int, values["fee_minor"]),
                refund_minor=cast(int, values["refund_minor"]),
                dispute_minor=cast(int, values["dispute_minor"]),
                net_minor=cast(int, values["net_minor"]),
                settled_at=cast(datetime, values["settled_at"]),
                ledger_entry_ids=tuple(cast(list[UUID], values["ledger_entry_ids"])),
                reason=str(values["reason"]),
                correlation_id=_correlation_id(request),
            )
        except AuthorizationDenied as error:
            raise PermissionDenied(
                "Provider settlement reconciliation is unavailable.",
                code=error.reason_code,
            ) from error
        except ObjectDoesNotExist as error:
            raise NotFound("The settlement provider is unavailable.") from error
        except DjangoValidationError as error:
            raise ApiValidationError(
                {
                    "detail": "The settlement could not be reconciled.",
                    "code": error.code or "settlement_invalid",
                }
            ) from error
        return Response(SettlementBatchSerializer(batch).data, status=201)


class StaffRegistrationListView(GenericAPIView[Registration]):
    serializer_class = StaffRegistrationSerializer
    pagination_class = StandardPageNumberPagination

    @extend_schema(
        operation_id="registration_list_service_summaries",
        parameters=[StaffRegistrationListQuerySerializer],
        responses=StaffRegistrationSerializer(many=True),
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        account = _account(request)
        correlation_id = _correlation_id(request)
        decision = _scope_decision(
            account=account,
            capability_code=VIEW_SERVICE,
            organization_id=organization_id,
            edition_id=edition_id,
            requested_fields=frozenset(StaffRegistrationSerializer.Meta.fields),
        )
        if not decision.allowed:
            _read_audit(
                account=account,
                organization_id=organization_id,
                edition_id=edition_id,
                correlation_id=correlation_id,
                capability_code=VIEW_SERVICE,
                operation="registration.service_summary.list",
                target_type="registration.registration_set",
                target_id=None,
                outcome=AuditEvent.Outcome.DENY,
                reason_code=decision.reason_code,
                obligations=decision.obligations,
            )
            raise PermissionDenied(
                "Registration service summaries are unavailable.",
                code=decision.reason_code,
            )
        try:
            require_complete_projection(
                required_fields=frozenset(StaffRegistrationSerializer.Meta.fields),
                permitted_fields=decision.fields,
            )
        except FieldProjectionDeniedError as error:
            raise PermissionDenied(
                "The permitted registration projection is incomplete.",
                code="field_projection_denied",
            ) from error
        query = StaffRegistrationListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        values = query.validated_data
        registrations = _registration_queryset(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        if search := values.get("search"):
            registrations = registrations.filter(
                Q(account__display_name__icontains=cast(str, search))
                | Q(reference__icontains=cast(str, search))
            )
        if state := values.get("state"):
            registrations = registrations.filter(state=cast(str, state))
        registrations = registrations.order_by("-submitted_at", "id")
        page = self.paginate_queryset(registrations)
        if page is None:
            raise RuntimeError("Registration list pagination is required.")
        payload = self.get_serializer(page, many=True).data
        _read_audit(
            account=account,
            organization_id=organization_id,
            edition_id=edition_id,
            correlation_id=correlation_id,
            capability_code=VIEW_SERVICE,
            operation="registration.service_summary.list",
            target_type="registration.registration_set",
            target_id=None,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=decision.reason_code,
            obligations=decision.obligations,
            target_count=len(page),
        )
        return self.get_paginated_response(payload)


ATTENDEE_REPORT_FIELDS = frozenset(
    {
        "generated_at",
        "status_scope",
        "summary",
        "count",
        "page",
        "page_size",
        "has_next",
        "has_previous",
        "results",
    }
)


def _authorize_attendee_reporting(
    *,
    request: Request,
    account: Account,
    organization_id: UUID,
    edition_id: UUID,
    requested_fields: frozenset[str],
    operation: str,
) -> PolicyDecision:
    correlation_id = _correlation_id(request)
    decision = _scope_decision(
        account=account,
        capability_code=VIEW_ATTENDEE_REPORTING,
        organization_id=organization_id,
        edition_id=edition_id,
        requested_fields=requested_fields,
    )
    if not decision.allowed:
        _read_audit(
            account=account,
            organization_id=organization_id,
            edition_id=edition_id,
            correlation_id=correlation_id,
            capability_code=VIEW_ATTENDEE_REPORTING,
            operation=operation,
            target_type="registration.attendee_report",
            target_id=None,
            outcome=AuditEvent.Outcome.DENY,
            reason_code=decision.reason_code,
            obligations=decision.obligations,
        )
        raise PermissionDenied(
            "Attendee reporting is unavailable.",
            code=decision.reason_code,
        )
    try:
        require_complete_projection(
            required_fields=requested_fields,
            permitted_fields=decision.fields,
        )
    except FieldProjectionDeniedError as error:
        raise PermissionDenied(
            "The permitted attendee-report projection is incomplete.",
            code="field_projection_denied",
        ) from error
    return decision


def _attendee_reporting_source(
    *,
    organization_id: UUID,
    edition_id: UUID,
) -> tuple[EventEdition, list[dict[str, object]]]:
    edition = EventEdition.objects.filter(
        id=edition_id,
        organization_id=organization_id,
    ).first()
    if edition is None:
        raise NotFound("Attendee reporting is unavailable.")
    queryset = attendee_report_queryset(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    if queryset.count() > MAX_SYNCHRONOUS_REPORT_ROWS:
        raise ApiValidationError(
            {
                "detail": (
                    "This edition is too large for the synchronous report. "
                    "Use an approved asynchronous export job."
                ),
                "code": "attendee_report_too_large",
            }
        )
    return edition, attendee_report_rows(list(queryset))


class StaffAttendeeReportView(APIView):
    @extend_schema(
        operation_id="registration_retrieve_attendee_report",
        parameters=[AttendeeReportQuerySerializer],
        responses=AttendeeReportSerializer,
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        account = _account(request)
        operation = "registration.attendee_report.retrieve"
        decision = _authorize_attendee_reporting(
            request=request,
            account=account,
            organization_id=organization_id,
            edition_id=edition_id,
            requested_fields=ATTENDEE_REPORT_FIELDS,
            operation=operation,
        )
        query = AttendeeReportQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        values = query.validated_data
        _edition, all_rows = _attendee_reporting_source(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        filtered_rows = filter_attendee_report_rows(
            all_rows,
            AttendeeReportFilters(
                search=str(values.get("search", "")),
                country_code=str(values.get("country_code", "")),
                level=str(values.get("level", "")),
            ),
        )
        page = cast(int, values["page"])
        page_size = cast(int, values["page_size"])
        start = (page - 1) * page_size
        end = start + page_size
        page_rows = filtered_rows[start:end]
        payload = {
            "generated_at": timezone.now(),
            "status_scope": list(COMING_STATES),
            "summary": attendee_report_summary(all_rows),
            "count": len(filtered_rows),
            "page": page,
            "page_size": page_size,
            "has_next": end < len(filtered_rows),
            "has_previous": page > 1,
            "results": page_rows,
        }
        _read_audit(
            account=account,
            organization_id=organization_id,
            edition_id=edition_id,
            correlation_id=_correlation_id(request),
            capability_code=VIEW_ATTENDEE_REPORTING,
            operation=operation,
            target_type="registration.attendee_report",
            target_id=None,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=decision.reason_code,
            obligations=decision.obligations,
            target_count=len(page_rows),
        )
        return Response(AttendeeReportSerializer(instance=payload).data)


class StaffBadgeExportView(APIView):
    @extend_schema(
        operation_id="registration_export_badge_data",
        parameters=[AttendeeReportQuerySerializer],
        responses={(200, "text/csv"): OpenApiTypes.BINARY},
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> HttpResponse:
        account = _account(request)
        operation = "registration.badge_data.export"
        decision = _authorize_attendee_reporting(
            request=request,
            account=account,
            organization_id=organization_id,
            edition_id=edition_id,
            requested_fields=frozenset({"badge_export"}),
            operation=operation,
        )
        query = AttendeeReportQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        values = query.validated_data
        edition, all_rows = _attendee_reporting_source(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        rows = filter_attendee_report_rows(
            all_rows,
            AttendeeReportFilters(
                search=str(values.get("search", "")),
                country_code=str(values.get("country_code", "")),
                level=str(values.get("level", "")),
            ),
        )
        generated_at = timezone.now()
        response = HttpResponse(
            badge_export_csv(
                rows=rows,
                edition_name=edition.name,
                edition_id=edition.id,
                generated_at=generated_at.isoformat(),
            ),
            content_type="text/csv; charset=utf-8",
        )
        response["Content-Disposition"] = (
            f'attachment; filename="{edition.slug}-badge-data.csv"'
        )
        response["X-Content-Type-Options"] = "nosniff"
        _read_audit(
            account=account,
            organization_id=organization_id,
            edition_id=edition_id,
            correlation_id=_correlation_id(request),
            capability_code=VIEW_ATTENDEE_REPORTING,
            operation=operation,
            target_type="registration.attendee_report",
            target_id=None,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=decision.reason_code,
            obligations=decision.obligations,
            target_count=len(rows),
        )
        return response


class StaffProfileMediaReviewListView(APIView):
    @extend_schema(
        operation_id="registration_list_profile_media_reviews",
        responses=ProfileMediaReviewItemSerializer(many=True),
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        account = _account(request)
        correlation_id = _correlation_id(request)
        requested_fields = frozenset(
            {
                "id",
                "account_id",
                "display_name",
                "media_kind",
                "image",
                "review_status",
                "submitted_at",
            }
        )
        decision = _scope_decision(
            account=account,
            capability_code=MODERATE_PUBLIC_PROFILE,
            organization_id=organization_id,
            edition_id=edition_id,
            requested_fields=requested_fields,
        )
        if not decision.allowed:
            _read_audit(
                account=account,
                organization_id=organization_id,
                edition_id=edition_id,
                correlation_id=correlation_id,
                capability_code=MODERATE_PUBLIC_PROFILE,
                operation="registration.profile_media_review.list",
                target_type="registration.profile_media_set",
                target_id=None,
                outcome=AuditEvent.Outcome.DENY,
                reason_code=decision.reason_code,
                obligations=decision.obligations,
            )
            raise PermissionDenied(
                "Profile media review is unavailable.",
                code=decision.reason_code,
            )
        if (
            not EventEdition.objects.filter(
                id=edition_id,
                organization_id=organization_id,
            )
            .exclude(
                lifecycle__in=(
                    EventEdition.Lifecycle.ARCHIVED,
                    EventEdition.Lifecycle.CANCELLED,
                )
            )
            .exists()
        ):
            raise NotFound("Profile media review is unavailable.")
        profile_items = [
            {
                "id": profile.id,
                "profile_id": profile.id,
                "account_id": profile.account_id,
                "display_name": profile.account.display_name,
                "media_kind": "profile_photo",
                "label": "Profile image",
                "review_status": profile.profile_photo_status,
                "preview_path": (f"/register/media/profile/{profile.id}/"),
                "submitted_at": profile.updated_at,
            }
            for profile in AttendeeRegistrationProfile.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
                profile_photo_status=MediaReviewStatus.PENDING,
            ).select_related("account")
        ]
        fursuit_items = [
            {
                "id": fursuit.id,
                "profile_id": fursuit.profile_id,
                "account_id": fursuit.account_id,
                "display_name": fursuit.account.display_name,
                "media_kind": "fursuit_photo",
                "label": f"{fursuit.name} · {fursuit.species}".rstrip(" ·"),
                "review_status": fursuit.photo_status,
                "preview_path": (f"/register/media/fursuit/{fursuit.id}/"),
                "submitted_at": fursuit.updated_at,
            }
            for fursuit in AttendeeFursuit.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
                photo_status=MediaReviewStatus.PENDING,
                is_active=True,
            ).select_related("account")
        ]
        items = sorted(
            [*profile_items, *fursuit_items],
            key=lambda item: (cast(datetime, item["submitted_at"]), str(item["id"])),
        )
        _read_audit(
            account=account,
            organization_id=organization_id,
            edition_id=edition_id,
            correlation_id=correlation_id,
            capability_code=MODERATE_PUBLIC_PROFILE,
            operation="registration.profile_media_review.list",
            target_type="registration.profile_media_set",
            target_id=None,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=decision.reason_code,
            obligations=decision.obligations,
            target_count=len(items),
        )
        return Response(
            ProfileMediaReviewItemSerializer(
                instance=items,  # type: ignore[arg-type]
                many=True,
            ).data
        )


class StaffProfileMediaReviewDecisionView(APIView):
    @extend_schema(
        operation_id="registration_review_profile_media",
        request=ProfileMediaReviewDecisionSerializer,
        responses=ProfileMediaReviewItemSerializer,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        media_id: UUID,
    ) -> Response:
        serializer = ProfileMediaReviewDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        try:
            item = review_attendee_media(
                organization_id=organization_id,
                edition_id=edition_id,
                actor=_account(request),
                media_kind=cast(str, values["media_kind"]),
                media_id=media_id,
                decision=cast(str, values["decision"]),
                reason=cast(str, values["reason"]),
                correlation_id=_correlation_id(request),
            )
        except DjangoValidationError as error:
            raise ApiValidationError(error.messages) from error
        if isinstance(item, AttendeeRegistrationProfile):
            payload = {
                "id": item.id,
                "profile_id": item.id,
                "account_id": item.account_id,
                "display_name": item.account.display_name,
                "media_kind": "profile_photo",
                "label": "Profile image",
                "review_status": item.profile_photo_status,
                "preview_path": f"/register/media/profile/{item.id}/",
                "submitted_at": item.updated_at,
            }
        else:
            payload = {
                "id": item.id,
                "profile_id": item.profile_id,
                "account_id": item.account_id,
                "display_name": item.account.display_name,
                "media_kind": "fursuit_photo",
                "label": f"{item.name} · {item.species}".rstrip(" ·"),
                "review_status": item.photo_status,
                "preview_path": f"/register/media/fursuit/{item.id}/",
                "submitted_at": item.updated_at,
            }
        return Response(ProfileMediaReviewItemSerializer(payload).data)


class StaffRegistrationDetailView(APIView):
    @extend_schema(
        operation_id="registration_retrieve_service_summary",
        responses=StaffRegistrationSerializer,
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        registration_id: UUID,
    ) -> Response:
        account = _account(request)
        correlation_id = _correlation_id(request)
        decision = _scope_decision(
            account=account,
            capability_code=VIEW_SERVICE,
            organization_id=organization_id,
            edition_id=edition_id,
            requested_fields=frozenset(StaffRegistrationSerializer.Meta.fields),
        )
        if not decision.allowed:
            _read_audit(
                account=account,
                organization_id=organization_id,
                edition_id=edition_id,
                correlation_id=correlation_id,
                capability_code=VIEW_SERVICE,
                operation="registration.service_summary.retrieve",
                target_type="registration.registration",
                target_id=registration_id,
                outcome=AuditEvent.Outcome.DENY,
                reason_code=decision.reason_code,
                obligations=decision.obligations,
            )
            raise PermissionDenied(
                "The registration is unavailable.",
                code=decision.reason_code,
            )
        registration = (
            _registration_queryset(
                organization_id=organization_id,
                edition_id=edition_id,
            )
            .filter(id=registration_id)
            .first()
        )
        if registration is None:
            raise NotFound(
                "The registration is unavailable.",
                code="registration_unavailable",
            )
        _read_audit(
            account=account,
            organization_id=organization_id,
            edition_id=edition_id,
            correlation_id=correlation_id,
            capability_code=VIEW_SERVICE,
            operation="registration.service_summary.retrieve",
            target_type="registration.registration",
            target_id=registration.id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=decision.reason_code,
            obligations=decision.obligations,
            target_count=1,
        )
        return Response(StaffRegistrationSerializer(registration).data)


class StaffRegistrationCheckInView(APIView):
    @extend_schema(
        operation_id="registration_check_in",
        request=CheckInSerializer,
        responses=StaffRegistrationSerializer,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        registration_id: UUID,
    ) -> Response:
        serializer = CheckInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            registration = check_in_registration(
                organization_id=organization_id,
                edition_id=edition_id,
                registration_id=registration_id,
                actor=_account(request),
                reason=serializer.validated_data["reason"],
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        except AuthorizationDenied as error:
            raise PermissionDenied(
                "Check-in is unavailable.",
                code=error.reason_code,
            ) from error
        except Registration.DoesNotExist as error:
            raise NotFound(
                "The registration is unavailable.",
                code="registration_unavailable",
            ) from error
        except DjangoValidationError as error:
            raise ApiValidationError(
                {
                    "detail": "Check-in could not be completed.",
                    "code": "invalid_check_in_state",
                }
            ) from error
        registration = _registration_queryset(
            organization_id=organization_id,
            edition_id=edition_id,
        ).get(id=registration.id)
        return Response(StaffRegistrationSerializer(registration).data)


class StaffRegistrationPaymentDeadlineView(APIView):
    @extend_schema(
        operation_id="registration_change_payment_deadline",
        request=ChangePaymentDeadlineSerializer,
        responses=StaffRegistrationSerializer,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        registration_id: UUID,
    ) -> Response:
        account = _account(request)
        _require_step_up(request, account)
        serializer = ChangePaymentDeadlineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            registration = extend_payment_deadline(
                organization_id=organization_id,
                edition_id=edition_id,
                registration_id=registration_id,
                actor=account,
                new_deadline=serializer.validated_data["new_deadline"],
                reason=serializer.validated_data["reason"],
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        except AuthorizationDenied as error:
            raise PermissionDenied(
                "The payment deadline cannot be changed.",
                code=error.reason_code,
            ) from error
        except Registration.DoesNotExist as error:
            raise NotFound(
                "The registration is unavailable.",
                code="registration_unavailable",
            ) from error
        except DjangoValidationError as error:
            raise ApiValidationError(
                {
                    "detail": error.messages[0],
                    "code": "invalid_payment_deadline_change",
                }
            ) from error
        registration = _registration_queryset(
            organization_id=organization_id,
            edition_id=edition_id,
        ).get(id=registration.id)
        return Response(StaffRegistrationSerializer(registration).data)


class StaffRegistrationWaivePaymentView(APIView):
    @extend_schema(
        operation_id="registration_waive_payment",
        request=WaivePaymentSerializer,
        responses=StaffRegistrationSerializer,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        registration_id: UUID,
    ) -> Response:
        account = _account(request)
        _require_step_up(request, account)
        serializer = WaivePaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            registration = waive_registration_payment(
                organization_id=organization_id,
                edition_id=edition_id,
                registration_id=registration_id,
                actor=account,
                reason=serializer.validated_data["reason"],
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        except AuthorizationDenied as error:
            raise PermissionDenied(
                "The payment cannot be waived.",
                code=error.reason_code,
            ) from error
        except Registration.DoesNotExist as error:
            raise NotFound(
                "The registration is unavailable.",
                code="registration_unavailable",
            ) from error
        except DjangoValidationError as error:
            raise ApiValidationError(
                {
                    "detail": error.messages[0],
                    "code": "invalid_payment_waiver",
                }
            ) from error
        registration = _registration_queryset(
            organization_id=organization_id,
            edition_id=edition_id,
        ).get(id=registration.id)
        return Response(StaffRegistrationSerializer(registration).data)


class RegistrationReconciliationView(APIView):
    @extend_schema(
        operation_id="registration_retrieve_reconciliation",
        responses=RegistrationReconciliationSerializer,
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        account = _account(request)
        decision = _scope_decision(
            account=account,
            capability_code=VIEW_PAYMENT_SUMMARY,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        if not decision.allowed:
            raise PermissionDenied(
                "Registration reconciliation is unavailable.",
                code=decision.reason_code,
            )
        grouped = (
            Registration.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
            )
            .values(
                "product_name_snapshot",
                "currency_snapshot",
                "state",
                "confirmation_basis",
            )
            .annotate(
                registrations=Count("id"),
                amount_minor=Sum("price_minor_snapshot"),
            )
            .order_by("product_name_snapshot", "currency_snapshot")
        )
        products: dict[tuple[str, str], dict[str, object]] = {}
        for row in grouped:
            key = (
                cast(str, row["product_name_snapshot"]),
                cast(str, row["currency_snapshot"]),
            )
            product = products.setdefault(
                key,
                {
                    "product_name": key[0],
                    "currency": key[1],
                    "registrations": 0,
                    "waitlisted": 0,
                    "payment_pending": 0,
                    "provider_paid": 0,
                    "provider_paid_minor": 0,
                    "waived": 0,
                    "waived_minor": 0,
                    "free_confirmed": 0,
                    "expired": 0,
                    "cancelled": 0,
                },
            )
            count = cast(int, row["registrations"])
            amount = cast(int, row["amount_minor"] or 0)
            product["registrations"] = cast(int, product["registrations"]) + count
            state = cast(str, row["state"])
            basis = cast(str, row["confirmation_basis"])
            if state == Registration.State.WAITLISTED:
                product["waitlisted"] = cast(int, product["waitlisted"]) + count
            elif state == Registration.State.PAYMENT_PENDING:
                product["payment_pending"] = (
                    cast(int, product["payment_pending"]) + count
                )
            elif state == Registration.State.EXPIRED:
                product["expired"] = cast(int, product["expired"]) + count
            elif state == Registration.State.CANCELLED:
                product["cancelled"] = cast(int, product["cancelled"]) + count
            if basis == Registration.ConfirmationBasis.PROVIDER:
                product["provider_paid"] = cast(int, product["provider_paid"]) + count
                product["provider_paid_minor"] = (
                    cast(int, product["provider_paid_minor"]) + amount
                )
            elif basis == Registration.ConfirmationBasis.WAIVER:
                product["waived"] = cast(int, product["waived"]) + count
                product["waived_minor"] = cast(int, product["waived_minor"]) + amount
            elif basis == Registration.ConfirmationBasis.FREE:
                product["free_confirmed"] = cast(int, product["free_confirmed"]) + count
        _read_audit(
            account=account,
            organization_id=organization_id,
            edition_id=edition_id,
            correlation_id=_correlation_id(request),
            capability_code=VIEW_PAYMENT_SUMMARY,
            operation="registration.reconciliation.retrieve",
            target_type="registration.reconciliation",
            target_id=None,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=decision.reason_code,
            obligations=decision.obligations,
            target_count=sum(
                cast(int, product["registrations"]) for product in products.values()
            ),
        )
        payload = {
            "generated_at": timezone.now(),
            "products": list(products.values()),
        }
        return Response(RegistrationReconciliationSerializer(payload).data)


class StaffActionListView(APIView):
    @extend_schema(
        operation_id="staff_list_assigned_actions",
        responses=ActionItemSerializer(many=True),
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        account = _account(request)
        manage = _scope_decision(
            account=account,
            capability_code=MANAGE_CONFIGURATION,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        service = _scope_decision(
            account=account,
            capability_code=VIEW_SERVICE,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        exceptions = _scope_decision(
            account=account,
            capability_code="registration.manage_exceptions",
            organization_id=organization_id,
            edition_id=edition_id,
        )
        finance = _scope_decision(
            account=account,
            capability_code="registration.manage_finance",
            organization_id=organization_id,
            edition_id=edition_id,
        )
        moderation = _scope_decision(
            account=account,
            capability_code=MODERATE_PUBLIC_PROFILE,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        if not any(
            decision.allowed
            for decision in (manage, service, exceptions, finance, moderation)
        ):
            raise PermissionDenied(
                "Assigned actions are unavailable.",
                code="permission_absent",
            )
        actions: list[dict[str, object]] = []
        now = timezone.now()
        if manage.allowed:
            active_exists = RegistrationConfiguration.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
                status=ConfigurationStatus.ACTIVE,
            ).exists()
            latest_draft = (
                RegistrationConfiguration.objects.filter(
                    organization_id=organization_id,
                    edition_id=edition_id,
                    status=ConfigurationStatus.DRAFT,
                )
                .order_by("-version")
                .first()
            )
            if latest_draft is not None and latest_draft.review_required:
                actions.append(
                    {
                        "key": f"registration-config-review:{latest_draft.id}",
                        "level": "action",
                        "title": "Review inherited registration setup",
                        "summary": (
                            f"{latest_draft.name} v{latest_draft.version} must be "
                            "reviewed before it can open."
                        ),
                        "object_type": "registration.configuration",
                        "object_id": latest_draft.id,
                        "destination": "commerce",
                        "owner_label": "Convention leadership",
                        "due_at": latest_draft.opens_at,
                        "created_at": latest_draft.created_at,
                    }
                )
            elif not active_exists:
                actions.append(
                    {
                        "key": "registration-config-missing",
                        "level": "blocking",
                        "title": "Create registration setup",
                        "summary": (
                            "This edition has no active registration configuration."
                        ),
                        "object_type": "registration.configuration",
                        "object_id": None,
                        "destination": "commerce",
                        "owner_label": "Convention leadership",
                        "due_at": None,
                        "created_at": now,
                    }
                )
        if service.allowed:
            confirmed = list(
                Registration.objects.filter(
                    organization_id=organization_id,
                    edition_id=edition_id,
                    state=Registration.State.CONFIRMED,
                )
                .select_related("account")
                .order_by("confirmed_at", "id")[:20]
            )
            actions.extend(
                [
                    {
                        "key": f"registration-check-in:{registration.id}",
                        "level": "action",
                        "title": f"Arrival ready: {registration.account}",
                        "summary": (
                            f"{registration.reference} is paid and ready for "
                            "Front Desk check-in."
                        ),
                        "object_type": "registration.registration",
                        "object_id": registration.id,
                        "destination": "commerce",
                        "owner_label": "Registration and Front Desk",
                        "due_at": None,
                        "created_at": registration.confirmed_at
                        or registration.submitted_at,
                    }
                    for registration in confirmed
                ]
            )
            _read_audit(
                account=account,
                organization_id=organization_id,
                edition_id=edition_id,
                correlation_id=_correlation_id(request),
                capability_code=VIEW_SERVICE,
                operation="registration.assigned_actions.list",
                target_type="registration.registration_set",
                target_id=None,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code=service.reason_code,
                obligations=service.obligations,
                target_count=len(confirmed),
            )
        if exceptions.allowed:
            overdue = list(
                Registration.objects.filter(
                    organization_id=organization_id,
                    edition_id=edition_id,
                    state=Registration.State.PAYMENT_PENDING,
                    payment_due_at__lte=now,
                )
                .select_related("account")
                .order_by("payment_due_at", "id")[:20]
            )
            inactive_confirmed = list(
                Registration.objects.filter(
                    organization_id=organization_id,
                    edition_id=edition_id,
                    state__in=(
                        Registration.State.CONFIRMED,
                        Registration.State.CHECKED_IN,
                    ),
                    account__is_active=False,
                )
                .select_related("account")
                .order_by("confirmed_at", "id")[:20]
            )
            actions.extend(
                {
                    "key": f"registration-payment-overdue:{registration.id}",
                    "level": "blocking",
                    "title": f"Payment deadline elapsed: {registration.reference}",
                    "summary": (
                        "Run the registration lifecycle processor or extend the "
                        "deadline with a recorded reason."
                    ),
                    "object_type": "registration.registration",
                    "object_id": registration.id,
                    "destination": "commerce",
                    "owner_label": "Registration exceptions",
                    "due_at": registration.payment_due_at,
                    "created_at": registration.submitted_at,
                }
                for registration in overdue
            )
            actions.extend(
                {
                    "key": f"registration-inactive-confirmed:{registration.id}",
                    "level": "urgent",
                    "title": (
                        f"Inactive account has admission: {registration.reference}"
                    ),
                    "summary": (
                        "Do not silently erase financial history. Review refund, "
                        "entitlement, and credential consequences."
                    ),
                    "object_type": "registration.registration",
                    "object_id": registration.id,
                    "destination": "commerce",
                    "owner_label": "Registration and account safety",
                    "due_at": None,
                    "created_at": registration.confirmed_at
                    or registration.submitted_at,
                }
                for registration in inactive_confirmed
            )
            delivery_failures = NotificationDelivery.objects.filter(
                message__organization_id=organization_id,
                message__edition_id=edition_id,
                status=NotificationDelivery.Status.PERMANENT_FAILED,
            ).count()
            if delivery_failures:
                actions.append(
                    {
                        "key": "registration-delivery-failures",
                        "level": "urgent",
                        "title": f"{delivery_failures} attendee messages failed",
                        "summary": (
                            "Use the delivery-failure queue and an approved fallback "
                            "contact route. Registration state has not changed."
                        ),
                        "object_type": "communications.notification_delivery",
                        "object_id": None,
                        "destination": "commerce",
                        "owner_label": "Registration communications",
                        "due_at": None,
                        "created_at": now,
                    }
                )
        if finance.allowed:
            payment_exception_count = PaymentException.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
                status=PaymentException.Status.OPEN,
            ).count()
            financial_operation_count = FinancialOperation.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
                status__in=(
                    FinancialOperation.Status.PROPOSED,
                    FinancialOperation.Status.APPROVED,
                    FinancialOperation.Status.PROVIDER_PENDING,
                ),
            ).count()
            if payment_exception_count:
                actions.append(
                    {
                        "key": "registration-provider-exceptions",
                        "level": "urgent",
                        "title": (
                            f"{payment_exception_count} provider outcomes need review"
                        ),
                        "summary": (
                            "Reconcile amount, currency, timing, dispute, or unknown "
                            "provider evidence before resolving the queue item."
                        ),
                        "object_type": "registration.payment_exception",
                        "object_id": None,
                        "destination": "commerce",
                        "owner_label": "Registration finance",
                        "due_at": None,
                        "created_at": now,
                    }
                )
            if financial_operation_count:
                actions.append(
                    {
                        "key": "registration-financial-operations",
                        "level": "blocking",
                        "title": (
                            f"{financial_operation_count} financial changes are open"
                        ),
                        "summary": (
                            "Review dual-control approvals and provider-pending "
                            "refund evidence."
                        ),
                        "object_type": "registration.financial_operation",
                        "object_id": None,
                        "destination": "commerce",
                        "owner_label": "Registration finance",
                        "due_at": None,
                        "created_at": now,
                    }
                )
        if moderation.allowed:
            pending_media = (
                AttendeeRegistrationProfile.objects.filter(
                    organization_id=organization_id,
                    edition_id=edition_id,
                    profile_photo_status=MediaReviewStatus.PENDING,
                ).count()
                + AttendeeFursuit.objects.filter(
                    organization_id=organization_id,
                    edition_id=edition_id,
                    photo_status=MediaReviewStatus.PENDING,
                ).count()
            )
            if pending_media:
                actions.append(
                    {
                        "key": "registration-profile-media-review",
                        "level": "action",
                        "title": f"{pending_media} attendee images await review",
                        "summary": (
                            "Review safe renditions and record an approval or "
                            "rejection reason before anything becomes public."
                        ),
                        "object_type": "registration.profile_media",
                        "object_id": None,
                        "destination": "commerce",
                        "owner_label": "Attendee profile moderation",
                        "due_at": None,
                        "created_at": now,
                    }
                )

        def action_sort_key(item: dict[str, object]) -> tuple[int, str]:
            level_order = {"urgent": 0, "blocking": 1, "action": 2, "fyi": 3}
            return (
                level_order[cast(str, item["level"])],
                cast(datetime, item["created_at"]).isoformat(),
            )

        actions.sort(key=action_sort_key)
        return Response(
            ActionItemSerializer(
                instance=actions,  # type: ignore[arg-type]
                many=True,
            ).data
        )
