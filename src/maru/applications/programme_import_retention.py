"""Reviewed deployment policy for temporary Programme import payloads.

The staging lifetime is a deployment policy decision.  This module deliberately
has no fallback duration: staging fails closed until one versioned, reviewed
policy is configured.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Protocol

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

PROGRAMME_IMPORT_RETENTION_POLICY_SETTING: Final = (
    "MARU_APPLICATIONS_PROGRAMME_IMPORT_RETENTION_POLICY_JSON"
)
MAX_PROGRAMME_IMPORT_RETENTION_POLICY_BYTES: Final = 4_096
MAX_PROGRAMME_IMPORT_STAGING_SECONDS: Final = 31_536_000
_POLICY_CODE = re.compile(r"^[a-z][a-z0-9_.:-]{2,119}$", flags=re.ASCII)
_CONFIGURATION_ERROR_MESSAGE = (
    "Configure a complete reviewed Programme import staging-retention policy."
)
_POLICY_KEYS: Final = frozenset(
    {
        "approved_at",
        "approved_by_reference",
        "period_seconds",
        "policy_code",
    }
)


class ProgrammeImportRetentionConfigurationError(RuntimeError):
    """Signal that no complete reviewed staging policy is configured."""


@dataclass(frozen=True, slots=True)
class ProgrammeImportRetentionDecision:
    """Retain the versioned policy and server-derived staging expiry.

    Attributes
    ----------
    policy_code : str
        Reviewed versioned policy code governing staged import retention.
    expires_at : datetime
        Aware server-derived instant when private staging expires.
    """

    policy_code: str
    expires_at: datetime


class ProgrammeImportRetentionPolicyProvider(Protocol):
    """Resolve one reviewed policy at the authoritative staging instant."""

    def resolve(self, *, staged_at: datetime) -> ProgrammeImportRetentionDecision:
        """Return the configured policy decision or fail closed.

        Parameters
        ----------
        staged_at : datetime
            Authoritative aware instant at which staging begins.

        Returns
        -------
        ProgrammeImportRetentionDecision
            Versioned policy code and server-derived expiry.
        """
        ...


def _closed_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate policy member")
        document[key] = value
    return document


@dataclass(frozen=True, slots=True)
class ConfiguredProgrammeImportRetentionPolicyProvider:
    """Read the strict deployment setting without supplying a default period."""

    def resolve(self, *, staged_at: datetime) -> ProgrammeImportRetentionDecision:
        """Return a policy-bound expiry derived from ``staged_at``.

        Parameters
        ----------
        staged_at : datetime
            Authoritative aware instant at which staging begins.

        Returns
        -------
        ProgrammeImportRetentionDecision
            Reviewed policy code and expiry derived from the staging instant.

        Raises
        ------
        ProgrammeImportRetentionConfigurationError
            If the policy is missing, malformed, unreviewed, or unsafe.
        """
        if not isinstance(staged_at, datetime) or timezone.is_naive(staged_at):
            raise ProgrammeImportRetentionConfigurationError(
                _CONFIGURATION_ERROR_MESSAGE
            )
        raw = getattr(settings, PROGRAMME_IMPORT_RETENTION_POLICY_SETTING, "")
        if not isinstance(raw, str) or not raw:
            raise ProgrammeImportRetentionConfigurationError(
                _CONFIGURATION_ERROR_MESSAGE
            )
        try:
            encoded_size = len(raw.encode("utf-8"))
        except UnicodeEncodeError as error:
            raise ProgrammeImportRetentionConfigurationError(
                _CONFIGURATION_ERROR_MESSAGE
            ) from error
        if encoded_size > MAX_PROGRAMME_IMPORT_RETENTION_POLICY_BYTES:
            raise ProgrammeImportRetentionConfigurationError(
                _CONFIGURATION_ERROR_MESSAGE
            )
        try:
            document = json.loads(raw, object_pairs_hook=_closed_object)
        except (TypeError, ValueError) as error:
            raise ProgrammeImportRetentionConfigurationError(
                _CONFIGURATION_ERROR_MESSAGE
            ) from error
        if not isinstance(document, dict) or set(document) != _POLICY_KEYS:
            raise ProgrammeImportRetentionConfigurationError(
                _CONFIGURATION_ERROR_MESSAGE
            )
        policy_code = document["policy_code"]
        period_seconds = document["period_seconds"]
        approved_by_reference = document["approved_by_reference"]
        approved_at_value = document["approved_at"]
        approved_at = (
            parse_datetime(approved_at_value)
            if isinstance(approved_at_value, str)
            else None
        )
        if (
            not isinstance(policy_code, str)
            or _POLICY_CODE.fullmatch(policy_code) is None
            or type(period_seconds) is not int
            or not 1 <= period_seconds <= MAX_PROGRAMME_IMPORT_STAGING_SECONDS
            or not isinstance(approved_by_reference, str)
            or _POLICY_CODE.fullmatch(approved_by_reference) is None
            or approved_at is None
            or timezone.is_naive(approved_at)
            or approved_at > staged_at
        ):
            raise ProgrammeImportRetentionConfigurationError(
                _CONFIGURATION_ERROR_MESSAGE
            )
        return ProgrammeImportRetentionDecision(
            policy_code=policy_code,
            expires_at=staged_at + timedelta(seconds=period_seconds),
        )


DEFAULT_PROGRAMME_IMPORT_RETENTION_POLICY_PROVIDER: Final = (
    ConfiguredProgrammeImportRetentionPolicyProvider()
)


__all__ = [
    "DEFAULT_PROGRAMME_IMPORT_RETENTION_POLICY_PROVIDER",
    "MAX_PROGRAMME_IMPORT_STAGING_SECONDS",
    "PROGRAMME_IMPORT_RETENTION_POLICY_SETTING",
    "ConfiguredProgrammeImportRetentionPolicyProvider",
    "ProgrammeImportRetentionConfigurationError",
    "ProgrammeImportRetentionDecision",
    "ProgrammeImportRetentionPolicyProvider",
]
