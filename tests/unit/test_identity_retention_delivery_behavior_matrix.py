from __future__ import annotations

import json
import smtplib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError

from maru.identity import invitation_delivery as delivery
from maru.identity import invitation_retention as retention
from maru.identity.invitation_crypto import (
    InvitationCryptoPayloadError,
    InvitationDecryptionKeyUnavailableError,
)
from maru.identity.models import (
    PlatformAccountInvitation,
    PlatformIdentityDelivery,
    PlatformIdentityDeliveryAttempt,
)

_NOW = datetime(2027, 2, 1, tzinfo=UTC)


def _valid_policy_document() -> dict[str, object]:
    return {
        "policy_id": "platform.invitation.retention",
        "version": 1,
        "jurisdiction_code": "EU",
        "trigger": retention.RETENTION_POLICY_TRIGGER,
        "period_days": 30,
        "action": retention.RETENTION_POLICY_ACTION,
        "approved_by_reference": "legal.review.2027",
        "approved_at": "2027-01-01T00:00:00Z",
    }


def _configure_policy(settings: object, document: object) -> None:
    setattr(
        settings,
        retention.RETENTION_POLICY_SETTING,
        json.dumps(document, separators=(",", ":")),
    )


def test_retention_policy_is_closed_versioned_and_digest_stable(
    monkeypatch: pytest.MonkeyPatch,
    settings: object,
) -> None:
    _configure_policy(settings, _valid_policy_document())
    monkeypatch.setattr(retention, "_database_now", lambda: _NOW)

    first = retention.configured_invitation_retention_policy()
    second = retention.configured_invitation_retention_policy()

    assert first == second
    assert first.policy_id == "platform.invitation.retention"
    assert first.period_days == 30
    assert first.due_at(_NOW) == _NOW + timedelta(days=30)
    assert len(first.digest) == 64
    assert retention.invitation_retention_policy_is_ready()


def test_database_time_boundary_rejects_missing_or_untyped_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCursor:
        def __enter__(self) -> FakeCursor:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, _sql: str) -> None:
            return None

        def fetchone(self) -> None:
            return None

    class FakeConnection:
        def cursor(self) -> FakeCursor:
            return FakeCursor()

    monkeypatch.setattr(retention, "connection", FakeConnection())
    with pytest.raises(retention.InvitationRetentionUnavailableError):
        retention._database_now()


@pytest.mark.parametrize(
    "document",
    [
        None,
        "not-an-object",
        {},
        {**_valid_policy_document(), "unknown": True},
        {**_valid_policy_document(), "policy_id": "UPPER CASE"},
        {**_valid_policy_document(), "version": True},
        {**_valid_policy_document(), "version": 0},
        {**_valid_policy_document(), "jurisdiction_code": "eu"},
        {**_valid_policy_document(), "trigger": "created_at"},
        {**_valid_policy_document(), "period_days": True},
        {**_valid_policy_document(), "period_days": -1},
        {**_valid_policy_document(), "action": "delete_everything"},
        {**_valid_policy_document(), "approved_by_reference": ""},
    ],
)
def test_retention_policy_rejects_partial_ambiguous_or_unapproved_contracts(
    monkeypatch: pytest.MonkeyPatch,
    settings: object,
    document: object,
) -> None:
    _configure_policy(settings, document)
    monkeypatch.setattr(retention, "_database_now", lambda: _NOW)
    with pytest.raises(retention.InvitationRetentionConfigurationError):
        retention.configured_invitation_retention_policy()


def test_retention_policy_rejects_duplicate_members_and_oversized_input(
    monkeypatch: pytest.MonkeyPatch,
    settings: object,
) -> None:
    monkeypatch.setattr(retention, "_database_now", lambda: _NOW)
    duplicate = json.dumps(_valid_policy_document())[:-1] + ',"version":2}'
    setattr(settings, retention.RETENTION_POLICY_SETTING, duplicate)
    with pytest.raises(retention.InvitationRetentionConfigurationError):
        retention.configured_invitation_retention_policy()

    setattr(settings, retention.RETENTION_POLICY_SETTING, "x" * 4_097)
    with pytest.raises(retention.InvitationRetentionConfigurationError):
        retention.configured_invitation_retention_policy()


@pytest.mark.parametrize(
    "approved_at",
    [None, "", "not-a-date", "2027-01-01T00:00:00", "2028-01-01T00:00:00Z"],
)
def test_policy_approval_time_requires_bounded_past_aware_database_time(
    monkeypatch: pytest.MonkeyPatch,
    approved_at: object,
) -> None:
    monkeypatch.setattr(retention, "_database_now", lambda: _NOW)
    with pytest.raises(retention.InvitationRetentionConfigurationError):
        retention._normalized_approved_at(approved_at)

    monkeypatch.setattr(
        retention, "_database_now", lambda: (_ for _ in ()).throw(DatabaseError())
    )
    with pytest.raises(retention.InvitationRetentionConfigurationError):
        retention._normalized_approved_at("2027-01-01T00:00:00Z")


def test_policy_readiness_returns_false_without_releasing_configuration_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        retention,
        "configured_invitation_retention_policy",
        lambda: (_ for _ in ()).throw(
            retention.InvitationRetentionConfigurationError()
        ),
    )
    assert not retention.invitation_retention_policy_is_ready()


@pytest.mark.parametrize("value", [None, 1, "", "UPPER CASE", "bad/value"])
def test_policy_codes_are_normalized_or_rejected(value: object) -> None:
    with pytest.raises(ValidationError):
        retention._normalize_policy_code(value, field="policy_code")
    assert retention._normalize_policy_code(
        " Review.Policy-1 ", field="policy_code"
    ) == ("review.policy-1")


def test_terminal_trigger_uses_only_revocation_or_expiry_evidence() -> None:
    revoked_at = _NOW - timedelta(days=5)
    expired_at = _NOW - timedelta(days=4)
    invitation = SimpleNamespace(
        status=PlatformAccountInvitation.Status.REVOKED,
        revoked_at=revoked_at,
        expired_at=expired_at,
    )
    assert retention._terminal_trigger_at(invitation) == revoked_at
    invitation.status = PlatformAccountInvitation.Status.EXPIRED
    assert retention._terminal_trigger_at(invitation) == expired_at
    invitation.status = PlatformAccountInvitation.Status.ACCEPTED
    assert retention._terminal_trigger_at(invitation) is None


def test_retention_tombstones_are_bounded_irreversible_and_target_specific(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = b"k" * 32
    challenge_a = SimpleNamespace(id=UUID(int=1))
    challenge_b = SimpleNamespace(id=UUID(int=2))
    token_a, fingerprint_a = retention._challenge_tombstone(key, challenge_a)
    token_b, fingerprint_b = retention._challenge_tombstone(key, challenge_b)
    assert len(token_a) == len(fingerprint_a) == 64
    assert (token_a, fingerprint_a) != (token_b, fingerprint_b)
    provider = retention._provider_tombstone(key, UUID(int=3))
    assert provider.startswith("disposed-provider-")
    assert len(provider) <= 160

    monkeypatch.setattr(
        retention,
        "_PROVIDER_TOMBSTONE",
        SimpleNamespace(fullmatch=lambda _value: None),
    )
    with pytest.raises(retention.InvitationRetentionUnavailableError):
        retention._provider_tombstone(key, UUID(int=3))


class FakeExistsQuery:
    def __init__(self, *, value: bool = False, error: Exception | None = None) -> None:
        self.value = value
        self.error = error

    def filter(self, **_kwargs: object) -> FakeExistsQuery:
        if self.error is not None:
            raise self.error
        return self

    def exists(self) -> bool:
        return self.value


def test_terminal_payload_readiness_fails_closed_on_database_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        retention.PlatformAccountInvitation,
        "objects",
        FakeExistsQuery(value=False),
    )
    assert retention.terminal_invitation_payloads_are_destroyed()
    monkeypatch.setattr(
        retention.PlatformAccountInvitation,
        "objects",
        FakeExistsQuery(error=DatabaseError()),
    )
    assert not retention.terminal_invitation_payloads_are_destroyed()


def _claim() -> SimpleNamespace:
    return SimpleNamespace(attempt_number=3)


def _message() -> delivery.InvitationDeliveryMessage:
    return delivery.InvitationDeliveryMessage(
        to_email="invitee@example.invalid",
        subject="Invitation",
        body="Synthetic invitation body.",
        headers={"X-Maru-Idempotency-Key": str(UUID(int=8))},
    )


def test_delivery_binary_boundary_accepts_only_bytes_or_memoryview() -> None:
    assert delivery._as_bytes(b"value") == b"value"
    assert delivery._as_bytes(memoryview(b"value")) == b"value"
    with pytest.raises(delivery.InvitationDeliveryDependencyError):
        delivery._as_bytes("value")


def test_delivery_link_quotes_fragment_secret_and_strips_base_slash(
    settings: object,
) -> None:
    settings.MARU_PUBLIC_BASE_URL = "https://maru.example/"  # type: ignore[attr-defined]
    link = delivery._delivery_link("secret+/=")
    assert link.startswith("https://maru.example/accounts/invitations/accept/#code=")
    assert "secret+/=" not in link


@pytest.mark.parametrize("sent", [0, 1])
def test_default_delivery_adapter_requires_exact_provider_acceptance(
    monkeypatch: pytest.MonkeyPatch,
    sent: int,
) -> None:
    class FakeEmail:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def send(self, *, fail_silently: bool) -> int:
            assert not fail_silently
            return sent

    monkeypatch.setattr(delivery, "EmailMessage", FakeEmail)
    if sent == 0:
        with pytest.raises(OSError, match="did not accept"):
            delivery._default_delivery_adapter(_message())
    else:
        assert delivery._default_delivery_adapter(_message()) == str(UUID(int=8))


def test_delivery_keyring_failures_are_typed_dependency_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        delivery,
        "worker_invitation_private_keyring",
        lambda: (_ for _ in ()).throw(InvitationCryptoPayloadError()),
    )
    with pytest.raises(delivery.InvitationDeliveryDependencyError):
        delivery.deliver_platform_identity_invitation(UUID(int=1))
    with pytest.raises(delivery.InvitationDeliveryDependencyError):
        delivery.deliver_pending_platform_identity_invitations()


def test_missing_inventory_control_is_a_typed_delivery_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MissingControlQuery:
        def select_for_update(self) -> MissingControlQuery:
            return self

        def get(self, **_kwargs: object) -> object:
            raise delivery.PlatformAccountInventoryControl.DoesNotExist

    monkeypatch.setattr(
        delivery.PlatformAccountInventoryControl,
        "objects",
        MissingControlQuery(),
    )
    with pytest.raises(delivery.InvitationDeliveryDependencyError):
        delivery._lock_control()


@pytest.mark.parametrize(
    ("provider_reference", "outcome", "uncertain"),
    [
        (None, PlatformIdentityDeliveryAttempt.Outcome.UNCERTAIN, True),
        ("", PlatformIdentityDeliveryAttempt.Outcome.UNCERTAIN, True),
        ("x" * 161, PlatformIdentityDeliveryAttempt.Outcome.UNCERTAIN, True),
        ("bad\nreference", PlatformIdentityDeliveryAttempt.Outcome.UNCERTAIN, True),
        (
            "provider-safe-reference",
            PlatformIdentityDeliveryAttempt.Outcome.DELIVERED,
            False,
        ),
    ],
)
def test_provider_result_requires_bounded_printable_reference(
    provider_reference: object,
    outcome: str,
    uncertain: bool,
) -> None:
    result = delivery._provider_result(provider_reference, claim=_claim())
    assert result.attempt_outcome == outcome
    assert result.uncertain is uncertain


@pytest.mark.parametrize(
    ("error", "outcome", "safe_code", "uncertain"),
    [
        (
            smtplib.SMTPRecipientsRefused({}),
            PlatformIdentityDeliveryAttempt.Outcome.PERMANENT_FAILURE,
            "email_recipient_rejected",
            False,
        ),
        (
            smtplib.SMTPConnectError(421, b"unavailable"),
            PlatformIdentityDeliveryAttempt.Outcome.TRANSIENT_FAILURE,
            "email_provider_unavailable",
            False,
        ),
        (
            smtplib.SMTPServerDisconnected("uncertain"),
            PlatformIdentityDeliveryAttempt.Outcome.UNCERTAIN,
            "email_delivery_uncertain",
            True,
        ),
        (
            smtplib.SMTPResponseException(450, b"transient"),
            PlatformIdentityDeliveryAttempt.Outcome.TRANSIENT_FAILURE,
            "email_provider_unavailable",
            False,
        ),
        (
            smtplib.SMTPResponseException(550, b"permanent"),
            PlatformIdentityDeliveryAttempt.Outcome.PERMANENT_FAILURE,
            "email_provider_rejected",
            False,
        ),
        (
            smtplib.SMTPResponseException(350, b"unknown"),
            PlatformIdentityDeliveryAttempt.Outcome.UNCERTAIN,
            "email_delivery_uncertain",
            True,
        ),
        (
            smtplib.SMTPException("unknown"),
            PlatformIdentityDeliveryAttempt.Outcome.UNCERTAIN,
            "email_delivery_uncertain",
            True,
        ),
        (
            OSError("unknown"),
            PlatformIdentityDeliveryAttempt.Outcome.UNCERTAIN,
            "email_delivery_uncertain",
            True,
        ),
    ],
)
def test_delivery_attempt_classifies_provider_failures_without_detail_leakage(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    outcome: str,
    safe_code: str,
    uncertain: bool,
) -> None:
    monkeypatch.setattr(
        delivery, "_message_for_claim", lambda *_args, **_kwargs: _message()
    )
    result = delivery._attempt_delivery(
        _claim(),
        private_keyring=SimpleNamespace(),
        adapter=lambda _message: (_ for _ in ()).throw(error),
    )
    assert result.attempt_outcome == outcome
    assert result.safe_error_code == safe_code
    assert result.uncertain is uncertain


@pytest.mark.parametrize(
    ("error", "outcome", "safe_code"),
    [
        (
            InvitationDecryptionKeyUnavailableError(),
            PlatformIdentityDeliveryAttempt.Outcome.TRANSIENT_FAILURE,
            "invitation_encryption_key_unavailable",
        ),
        (
            InvitationCryptoPayloadError(),
            PlatformIdentityDeliveryAttempt.Outcome.PERMANENT_FAILURE,
            "invitation_encrypted_payload_invalid",
        ),
        (
            ValueError(),
            PlatformIdentityDeliveryAttempt.Outcome.PERMANENT_FAILURE,
            "invitation_encrypted_payload_invalid",
        ),
    ],
)
def test_delivery_attempt_classifies_envelope_failures_without_secret_release(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    outcome: str,
    safe_code: str,
) -> None:
    monkeypatch.setattr(
        delivery,
        "_message_for_claim",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )
    result = delivery._attempt_delivery(
        _claim(),
        private_keyring=SimpleNamespace(),
        adapter=lambda _message: "unused",
    )
    assert result.attempt_outcome == outcome
    assert result.safe_error_code == safe_code


class FakeDeliveryIds:
    def __init__(self, values: tuple[UUID, ...]) -> None:
        self.values = values

    def order_by(self, *_args: str) -> FakeDeliveryIds:
        return self

    def values_list(self, *_args: object, **_kwargs: object) -> FakeDeliveryIds:
        return self

    def __getitem__(self, item: slice) -> tuple[UUID, ...]:
        return self.values[item]


@pytest.mark.parametrize("limit", [True, 0, 1_001])
def test_delivery_batch_limit_is_a_real_bounded_integer(limit: object) -> None:
    with pytest.raises(ValueError, match="between 1 and 1000"):
        delivery.deliver_pending_platform_identity_invitations(limit=limit)  # type: ignore[arg-type]


def test_delivery_batch_counts_attempted_and_still_pending_without_starvation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = (uuid4(), uuid4(), uuid4(), uuid4())
    monkeypatch.setattr(
        delivery, "_eligible_delivery_queryset", lambda **_: FakeDeliveryIds(ids)
    )
    outcomes: dict[UUID, object] = {
        ids[0]: PlatformIdentityDelivery.Status.DELIVERED,
        ids[1]: PlatformIdentityDelivery.Status.PENDING,
        ids[2]: PlatformIdentityDelivery.Status.PROCESSING,
        ids[3]: delivery.InvitationDeliveryDependencyError(),
    }

    def deliver_one(delivery_id: UUID, **_kwargs: object) -> str:
        outcome = outcomes[delivery_id]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(delivery, "deliver_platform_identity_invitation", deliver_one)
    attempted, pending = delivery.deliver_pending_platform_identity_invitations(
        private_keyring=SimpleNamespace()
    )
    assert attempted == 2
    assert pending == 3
