"""Value-safe Django checks for invitation-delivery encryption readiness."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.core.checks import (
    CheckMessage,
    Error,
    Tags,
    register,
)
from django.core.checks import Warning as CheckWarning

from maru.identity.invitation_crypto import InvitationCryptoConfigurationError
from maru.identity.invitation_key_config import active_invitation_encryption_key
from maru.identity.invitation_token_keys import invitation_token_keys_are_ready
from maru.settings.environment import normalized_https_origin

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.apps import AppConfig

_CONFIGURATION_HINT = (
    "Set MARU_IDENTITY_INVITATION_ENCRYPTION_KEY_ID and "
    "MARU_IDENTITY_INVITATION_PUBLIC_KEY_B64 to one supported RSA public key. "
    "Private keys belong only in the invitation delivery-worker environment."
)
_UNAVAILABLE_MESSAGE = (
    "Invitation delivery encryption is unavailable; invitation commands fail closed."
)
_ORIGIN_UNAVAILABLE_MESSAGE = (
    "Invitation delivery origin is unavailable; invitation links fail closed."
)
_ORIGIN_HINT = (
    "Set MARU_PUBLIC_BASE_URL to one normalized HTTPS origin without userinfo, "
    "path, query, fragment, or an explicit default port."
)
_DIGEST_KEYS_UNAVAILABLE_MESSAGE = (
    "Invitation token protection is unavailable; invitation lookup fails closed."
)
_DIGEST_KEYS_HINT = (
    "Set MARU_IDENTITY_INVITATION_DIGEST_ACTIVE_KEY_ID and "
    "MARU_IDENTITY_INVITATION_DIGEST_KEYS_JSON to one bounded versioned HMAC keyring."
)


@register(Tags.security)
def check_invitation_encryption_configuration(
    app_configs: Iterable[AppConfig] | None = None,
    **kwargs: object,
) -> list[CheckMessage]:
    """Require a valid public key in production and warn elsewhere.

    Parameters
    ----------
    app_configs : Iterable[AppConfig] | None, default=None
        The installed Django application configurations to inspect.
    **kwargs : object
        Keyword arguments forwarded to the framework implementation.

    Returns
    -------
    list[CheckMessage]
        The matching check invitation encryption configuration records in
        deterministic order.
    """
    del app_configs, kwargs
    try:
        active_invitation_encryption_key()
    except InvitationCryptoConfigurationError:
        if bool(getattr(settings, "IDENTITY_INVITATION_ENCRYPTION_REQUIRED", False)):
            return [
                Error(
                    _UNAVAILABLE_MESSAGE,
                    hint=_CONFIGURATION_HINT,
                    id="identity.E001",
                )
            ]
        return [
            CheckWarning(
                _UNAVAILABLE_MESSAGE,
                hint=_CONFIGURATION_HINT,
                id="identity.W001",
            )
        ]
    return []


@register(Tags.security)
def check_invitation_public_origin_configuration(
    app_configs: Iterable[AppConfig] | None = None,
    **kwargs: object,
) -> list[CheckMessage]:
    """Require the bearer-link origin whenever invitation delivery is required.

    Parameters
    ----------
    app_configs : Iterable[AppConfig] | None, default=None
        The installed Django application configurations to inspect.
    **kwargs : object
        Keyword arguments forwarded to the framework implementation.

    Returns
    -------
    list[CheckMessage]
        The matching check invitation public origin configuration records in
        deterministic order.
    """
    del app_configs, kwargs
    if not bool(getattr(settings, "IDENTITY_INVITATION_ENCRYPTION_REQUIRED", False)):
        return []
    if normalized_https_origin(getattr(settings, "MARU_PUBLIC_BASE_URL", None)) is None:
        return [
            Error(
                _ORIGIN_UNAVAILABLE_MESSAGE,
                hint=_ORIGIN_HINT,
                id="identity.E002",
            )
        ]
    return []


@register(Tags.security)
def check_invitation_digest_key_configuration(
    app_configs: Iterable[AppConfig] | None = None,
    **kwargs: object,
) -> list[CheckMessage]:
    """Require dedicated versioned token-digest keys in production.

    Parameters
    ----------
    app_configs : Iterable[AppConfig] | None, default=None
        The installed Django application configurations to inspect.
    **kwargs : object
        Keyword arguments forwarded to the framework implementation.

    Returns
    -------
    list[CheckMessage]
        The matching check invitation digest key configuration records in
        deterministic order.
    """
    del app_configs, kwargs
    if not bool(getattr(settings, "IDENTITY_INVITATION_ENCRYPTION_REQUIRED", False)):
        return []
    if not invitation_token_keys_are_ready():
        return [
            Error(
                _DIGEST_KEYS_UNAVAILABLE_MESSAGE,
                hint=_DIGEST_KEYS_HINT,
                id="identity.E003",
            )
        ]
    return []


__all__ = [
    "check_invitation_digest_key_configuration",
    "check_invitation_encryption_configuration",
    "check_invitation_public_origin_configuration",
]
