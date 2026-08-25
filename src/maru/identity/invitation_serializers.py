"""Closed API contracts for platform account invitations."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar, Never, cast

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.extensions import OpenApiSerializerExtension
from rest_framework import serializers

from maru.identity.invitation_commands import MAX_INVITATION_PASSWORD_LENGTH
from maru.identity.invitation_delivery_payload import INVITATION_TOKEN_LENGTH
from maru.identity.invitation_inputs import (
    MAX_INVITATION_DISPLAY_NAME_LENGTH,
    MAX_INVITATION_EMAIL_LENGTH,
    MAX_INVITATION_LOGIN_HANDLE_LENGTH,
    MAX_INVITATION_REASON_LENGTH,
    SUPPORTED_INVITATION_LANGUAGE_CODES,
    normalize_invitation_display_name,
    normalize_invitation_email,
    normalize_invitation_login_handle,
    normalize_invitation_preferred_language,
    normalize_invitation_reason,
)
from maru.identity.invitation_queries import (
    ACCOUNT_INVENTORY_KINDS,
    ACCOUNT_INVENTORY_SEARCH_MODES,
    ACCOUNT_INVENTORY_STATES,
    MAX_ACCOUNT_INVENTORY_CURSOR_LENGTH,
    MAX_ACCOUNT_INVENTORY_PAGE_SIZE,
    MAX_ACCOUNT_INVENTORY_SEARCH_LENGTH,
    MIN_ACCOUNT_INVENTORY_SEARCH_LENGTH,
    PlatformAccountInventoryInputError,
    normalize_account_inventory_search,
)
from maru.identity.models import (
    Account,
    PlatformAccountInvitation,
    PlatformIdentityDelivery,
)

if TYPE_CHECKING:
    from drf_spectacular.openapi import AutoSchema
    from drf_spectacular.utils import Direction


_INVITATION_TOKEN_PATTERN = re.compile(
    rf"^[A-Za-z0-9_-]{{{INVITATION_TOKEN_LENGTH}}}$",
    flags=re.ASCII,
)


def _django_validation_code(
    error: DjangoValidationError,
    *,
    field_name: str,
    fallback: str,
) -> str:
    if hasattr(error, "error_dict"):
        field_errors = error.error_dict.get(field_name, ())
        if field_errors:
            return str(field_errors[0].code or fallback)
    if hasattr(error, "error_list") and error.error_list:
        return str(error.error_list[0].code or fallback)
    return fallback


def _raise_serializer_validation(
    error: DjangoValidationError,
    *,
    field_name: str,
    fallback: str,
) -> Never:
    messages = getattr(error, "message_dict", {}).get(field_name, error.messages)
    raise serializers.ValidationError(
        messages,
        code=_django_validation_code(
            error,
            field_name=field_name,
            fallback=fallback,
        ),
    ) from error


class _StrictInvitationTextField(serializers.CharField):
    """Accept a JSON string without DRF's number-to-text coercion."""

    default_error_messages: ClassVar[dict[str, Any]] = {
        "invalid_type": "Enter a JSON string for this field.",
    }

    def to_internal_value(self, data: object) -> str:
        if not isinstance(data, str):
            self.fail("invalid_type")
        return super().to_internal_value(data)


class _StrictInvitationIntegerField(serializers.IntegerField):
    """Accept a JSON integer, excluding booleans, strings, and floats."""

    default_error_messages: ClassVar[dict[str, Any]] = {
        "invalid_type": "Enter a JSON integer for this field.",
    }

    def to_internal_value(self, data: object) -> int:
        if type(data) is not int:
            self.fail("invalid_type")
        return super().to_internal_value(data)


class _NormalizedInvitationEmailField(_StrictInvitationTextField):
    def to_internal_value(self, data: object) -> str:
        value = super().to_internal_value(data)
        try:
            return normalize_invitation_email(value)
        except DjangoValidationError as error:
            _raise_serializer_validation(
                error,
                field_name="email",
                fallback="invitation_email_invalid",
            )


class _NormalizedInvitationHandleField(_StrictInvitationTextField):
    def to_internal_value(self, data: object) -> str:
        value = super().to_internal_value(data)
        try:
            return normalize_invitation_login_handle(value) or ""
        except DjangoValidationError as error:
            _raise_serializer_validation(
                error,
                field_name="login_handle",
                fallback="invitation_login_handle_invalid",
            )


class _NormalizedInvitationDisplayNameField(_StrictInvitationTextField):
    def to_internal_value(self, data: object) -> str:
        value = super().to_internal_value(data)
        try:
            return normalize_invitation_display_name(value) or ""
        except DjangoValidationError as error:
            _raise_serializer_validation(
                error,
                field_name="display_name",
                fallback="invitation_display_name_invalid",
            )


class _NormalizedInvitationReasonField(_StrictInvitationTextField):
    def to_internal_value(self, data: object) -> str:
        value = super().to_internal_value(data)
        try:
            return normalize_invitation_reason(value)
        except DjangoValidationError as error:
            _raise_serializer_validation(
                error,
                field_name="reason",
                fallback="invitation_reason_invalid",
            )


class _NormalizedAccountInventorySearchField(_StrictInvitationTextField):
    """Apply the documented after-normalization search length contract."""

    def to_internal_value(self, data: object) -> str:
        value = super().to_internal_value(data)
        try:
            return normalize_account_inventory_search(value) or ""
        except PlatformAccountInventoryInputError as error:
            raise serializers.ValidationError(
                "Enter either a blank search or 2 to 120 characters.",
                code=error.detail_code,
            ) from error

    def run_validators(self, value: str) -> None:
        if value == "":
            return
        super().run_validators(value)


class _InvitationClosedSerializer(serializers.Serializer[dict[str, object]]):
    """Reject undeclared platform invitation request properties."""

    reflect_unknown_field_names = True

    def to_internal_value(self, data: Any) -> dict[str, object]:
        if isinstance(data, Mapping):
            unknown_fields = sorted(
                str(field_name)
                for field_name in data
                if str(field_name) not in self.fields
            )
            if unknown_fields:
                if self.reflect_unknown_field_names:
                    errors: object = {
                        field_name: ["This field is not allowed."]
                        for field_name in unknown_fields[:5]
                    }
                else:
                    # The public C4 boundary never reflects an attacker-chosen
                    # property name: a bearer code or password could otherwise
                    # be submitted as the key itself and copied into a response.
                    errors = {"non_field_errors": ["Remove unsupported input fields."]}
                raise serializers.ValidationError(
                    cast("Any", errors),
                    code="unknown_input_field",
                )
        return cast("dict[str, object]", super().to_internal_value(data))


class _InvitationClosedRequestSchema(OpenApiSerializerExtension):
    """Expose the runtime closed-object contract in generated OpenAPI."""

    target_class = "maru.identity.invitation_serializers._InvitationClosedSerializer"
    match_subclasses = True

    def map_serializer(
        self,
        auto_schema: AutoSchema,
        direction: Direction,
    ) -> dict[str, Any]:
        schema = auto_schema._map_serializer(  # type: ignore[no-untyped-call]  # noqa: SLF001
            self.target,
            direction,
            bypass_extensions=True,
        )
        schema["additionalProperties"] = False
        return cast("dict[str, Any]", schema)


class _InvitationClosedResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Mark the fixed invitation response envelope as closed in OpenAPI."""


class _InvitationClosedResponseSchema(OpenApiSerializerExtension):
    target_class = (
        "maru.identity.invitation_serializers._InvitationClosedResponseSerializer"
    )
    match_subclasses = True

    def map_serializer(
        self,
        auto_schema: AutoSchema,
        direction: Direction,
    ) -> dict[str, Any]:
        schema = auto_schema._map_serializer(  # type: ignore[no-untyped-call]  # noqa: SLF001
            self.target,
            direction,
            bypass_extensions=True,
        )
        schema["additionalProperties"] = False
        return cast("dict[str, Any]", schema)


class PlatformAccountInventoryQuerySerializer(_InvitationClosedSerializer):
    """Closed, bounded query parameters for the platform account inventory."""

    search = _NormalizedAccountInventorySearchField(
        required=False,
        allow_blank=True,
        min_length=MIN_ACCOUNT_INVENTORY_SEARCH_LENGTH,
        max_length=MAX_ACCOUNT_INVENTORY_SEARCH_LENGTH,
        trim_whitespace=False,
    )
    search_mode = serializers.ChoiceField(
        required=False,
        default="prefix",
        choices=tuple(sorted(ACCOUNT_INVENTORY_SEARCH_MODES)),
    )
    kind = serializers.ChoiceField(
        required=False,
        allow_blank=True,
        choices=tuple(sorted(ACCOUNT_INVENTORY_KINDS)),
    )
    state = serializers.ChoiceField(
        required=False,
        allow_blank=True,
        choices=tuple(sorted(ACCOUNT_INVENTORY_STATES)),
    )
    cursor = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=MAX_ACCOUNT_INVENTORY_CURSOR_LENGTH,
        trim_whitespace=False,
    )
    page_size = serializers.IntegerField(
        required=False,
        default=MAX_ACCOUNT_INVENTORY_PAGE_SIZE,
        min_value=1,
        max_value=MAX_ACCOUNT_INVENTORY_PAGE_SIZE,
    )

    def to_internal_value(self, data: Any) -> dict[str, object]:
        """Parse and validate API input.

        Parameters
        ----------
        data : Any
            The untrusted input payload to validate or transform.

        Returns
        -------
        dict[str, object]
            A mapping containing the resolved to internal value data.

        Raises
        ------
        serializers.ValidationError
            If the submitted state or input violates a domain invariant.
        """
        lists = getattr(data, "lists", None)
        if callable(lists):
            repeated = sorted(
                str(field_name) for field_name, values in lists() if len(values) != 1
            )
            if repeated:
                raise serializers.ValidationError(
                    {
                        field_name: ["Submit this query parameter once."]
                        for field_name in repeated[:5]
                    },
                    code="duplicate_query_parameter",
                )
        return super().to_internal_value(data)


class PlatformAccountInvitationCreateSerializer(_InvitationClosedSerializer):
    """Reserve one inactive person identity; retry metadata stays header-only."""

    email = _NormalizedInvitationEmailField(
        max_length=MAX_INVITATION_EMAIL_LENGTH,
        trim_whitespace=False,
    )
    login_handle = _NormalizedInvitationHandleField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default=None,
        max_length=MAX_INVITATION_LOGIN_HANDLE_LENGTH,
        trim_whitespace=False,
    )
    display_name = _NormalizedInvitationDisplayNameField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default=None,
        max_length=MAX_INVITATION_DISPLAY_NAME_LENGTH,
        trim_whitespace=False,
    )
    preferred_language = _StrictInvitationTextField(
        required=False,
        allow_blank=False,
        default=None,
        max_length=35,
        trim_whitespace=False,
    )
    reason = _NormalizedInvitationReasonField(
        max_length=MAX_INVITATION_REASON_LENGTH,
        trim_whitespace=False,
    )
    expected_version = _StrictInvitationIntegerField(min_value=0, max_value=0)

    def validate_preferred_language(self, value: str | None) -> str:
        """Validate preferred language.

        Parameters
        ----------
        value : str | None
            The untrusted input to normalize, validate, or compare.

        Returns
        -------
        str
            The normalized text for validate preferred language.
        """
        try:
            return normalize_invitation_preferred_language(value)
        except DjangoValidationError as error:
            _raise_serializer_validation(
                error,
                field_name="preferred_language",
                fallback="invitation_preferred_language_unsupported",
            )


class PlatformAccountInvitationActionSerializer(_InvitationClosedSerializer):
    """Closed reason and expected-version input for reissue or revocation."""

    expected_version = _StrictInvitationIntegerField(min_value=1)
    reason = _NormalizedInvitationReasonField(
        max_length=MAX_INVITATION_REASON_LENGTH,
        trim_whitespace=False,
    )


class PublicAccountInvitationAcceptanceSerializer(_InvitationClosedSerializer):
    """C4 input whose field errors never redisplay submitted secret values."""

    reflect_unknown_field_names = False

    raw_token = _StrictInvitationTextField(
        min_length=INVITATION_TOKEN_LENGTH,
        max_length=INVITATION_TOKEN_LENGTH,
        trim_whitespace=False,
        write_only=True,
    )
    new_password1 = _StrictInvitationTextField(
        max_length=MAX_INVITATION_PASSWORD_LENGTH,
        trim_whitespace=False,
        write_only=True,
    )
    new_password2 = _StrictInvitationTextField(
        max_length=MAX_INVITATION_PASSWORD_LENGTH,
        trim_whitespace=False,
        write_only=True,
    )

    def validate_raw_token(self, value: str) -> str:
        """Validate raw token.

        Parameters
        ----------
        value : str
            The untrusted input to normalize, validate, or compare.

        Returns
        -------
        str
            The normalized text for validate raw token.

        Raises
        ------
        serializers.ValidationError
            If the submitted state or input violates a domain invariant.
        """
        if _INVITATION_TOKEN_PATTERN.fullmatch(value) is None:
            raise serializers.ValidationError(
                "Enter the complete invitation code.",
                code="account_invitation_challenge_invalid",
            )
        return value

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        """Validate the supplied data.

        Parameters
        ----------
        attrs : dict[str, object]
            The attrs mapping to validate or transform.

        Returns
        -------
        dict[str, object]
            A mapping containing the resolved validate data.

        Raises
        ------
        serializers.ValidationError
            If the submitted state or input violates a domain invariant.
        """
        if attrs["new_password1"] != attrs["new_password2"]:
            raise serializers.ValidationError(
                {"new_password2": ["The passwords do not match."]},
                code="invitation_password_mismatch",
            )
        return attrs


class PlatformAccountInvitationMutationSerializer(_InvitationClosedResponseSerializer):
    """Serialize and validate platform account invitation mutation data."""

    id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=PlatformAccountInvitation.Status.choices)
    aggregate_version = serializers.IntegerField(min_value=1)
    expires_at = serializers.DateTimeField()
    replayed = serializers.BooleanField()


class PublicAccountInvitationAcceptanceResultSerializer(
    _InvitationClosedResponseSerializer
):
    """Serialize and validate public account invitation acceptance result data."""

    accepted = serializers.BooleanField()
    next = serializers.ChoiceField(choices=("sign_in",))
    replayed = serializers.BooleanField()


class PlatformAccountInventoryInvitationSerializer(_InvitationClosedResponseSerializer):
    id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=PlatformAccountInvitation.Status.choices)
    aggregate_version = serializers.IntegerField(min_value=1)
    expires_at = serializers.DateTimeField()
    last_transition_at = serializers.DateTimeField()
    delivery_state = serializers.ChoiceField(
        choices=PlatformIdentityDelivery.Status.choices,
        allow_null=True,
    )


class PlatformAccountInventoryItemSerializer(_InvitationClosedResponseSerializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    login_handle = serializers.CharField(allow_blank=True)
    display_name = serializers.CharField(allow_blank=True)
    kind = serializers.ChoiceField(choices=Account.Kind.choices)
    active = serializers.BooleanField()
    email_verified = serializers.BooleanField()
    date_joined = serializers.DateTimeField()
    invitation = PlatformAccountInventoryInvitationSerializer(allow_null=True)


class PlatformAccountInventorySerializer(_InvitationClosedResponseSerializer):
    """Serialize and validate platform account inventory data."""

    inventory_version = serializers.IntegerField(min_value=0)
    items = PlatformAccountInventoryItemSerializer(many=True)
    next_cursor = serializers.CharField(allow_null=True)


class PlatformAccountInvitationAccountSerializer(_InvitationClosedResponseSerializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    login_handle = serializers.CharField(allow_blank=True)
    display_name = serializers.CharField(allow_blank=True)
    kind = serializers.ChoiceField(choices=Account.Kind.choices)
    active = serializers.BooleanField()
    email_verified = serializers.BooleanField()


class PlatformAccountInvitationActorSerializer(_InvitationClosedResponseSerializer):
    id = serializers.UUIDField(allow_null=True)
    display_name = serializers.CharField(allow_blank=True)


class PlatformAccountInvitationDeliverySerializer(_InvitationClosedResponseSerializer):
    status = serializers.ChoiceField(choices=PlatformIdentityDelivery.Status.choices)
    attempt_count = serializers.IntegerField(min_value=0)
    max_attempts = serializers.IntegerField(min_value=1)
    last_attempt_at = serializers.DateTimeField(allow_null=True)
    next_retry_at = serializers.DateTimeField(allow_null=True)
    delivered_at = serializers.DateTimeField(allow_null=True)
    safe_error_code = serializers.CharField(allow_blank=True)
    reconciliation_state = serializers.ChoiceField(
        choices=PlatformIdentityDelivery.ReconciliationState.choices
    )


class PlatformAccountInvitationTransitionSerializer(
    _InvitationClosedResponseSerializer
):
    version = serializers.IntegerField(min_value=1)
    operation = serializers.CharField()
    actor = PlatformAccountInvitationActorSerializer()
    occurred_at = serializers.DateTimeField()
    reason = serializers.CharField()
    source_channel = serializers.CharField()


class PlatformAccountInvitationDeliveryAttemptSerializer(
    _InvitationClosedResponseSerializer
):
    attempt_number = serializers.IntegerField(min_value=1)
    started_at = serializers.DateTimeField()
    finished_at = serializers.DateTimeField()
    outcome = serializers.CharField()
    safe_error_code = serializers.CharField(allow_blank=True)
    next_retry_at = serializers.DateTimeField(allow_null=True)


class PlatformAccountInvitationDetailSerializer(_InvitationClosedResponseSerializer):
    """Serialize and validate platform account invitation detail data."""

    inventory_version = serializers.IntegerField(min_value=0)
    id = serializers.UUIDField()
    account = PlatformAccountInvitationAccountSerializer()
    status = serializers.ChoiceField(choices=PlatformAccountInvitation.Status.choices)
    aggregate_version = serializers.IntegerField(min_value=1)
    expires_at = serializers.DateTimeField()
    created_at = serializers.DateTimeField()
    last_transition_at = serializers.DateTimeField()
    created_by = PlatformAccountInvitationActorSerializer()
    delivery = PlatformAccountInvitationDeliverySerializer(allow_null=True)
    transitions = PlatformAccountInvitationTransitionSerializer(many=True)
    delivery_attempts = PlatformAccountInvitationDeliveryAttemptSerializer(many=True)


class PlatformAccountInvitationProblemSerializer(_InvitationClosedResponseSerializer):
    """RFC 9457 response shape for every invitation API failure."""

    type = serializers.URLField(read_only=True)
    title = serializers.CharField(read_only=True)
    status = serializers.IntegerField(read_only=True)
    detail = serializers.CharField(read_only=True)
    code = serializers.CharField(read_only=True)
    request_id = serializers.UUIDField(required=False)
    errors = serializers.JSONField(required=False)  # type: ignore[assignment]


__all__ = [
    "SUPPORTED_INVITATION_LANGUAGE_CODES",
    "PlatformAccountInventoryQuerySerializer",
    "PlatformAccountInventorySerializer",
    "PlatformAccountInvitationActionSerializer",
    "PlatformAccountInvitationCreateSerializer",
    "PlatformAccountInvitationDetailSerializer",
    "PlatformAccountInvitationMutationSerializer",
    "PlatformAccountInvitationProblemSerializer",
    "PublicAccountInvitationAcceptanceResultSerializer",
    "PublicAccountInvitationAcceptanceSerializer",
]
