from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.identity import models
from maru.identity.models import (
    Account,
    IdentityChallenge,
    PlatformAccountInvitation,
    PlatformAccountInvitationTransition,
    PlatformIdentityDelivery,
    PlatformIdentityDeliveryAttempt,
    PlatformIdentityDeliveryLateOutcome,
    PlatformIdentityDeliveryReconciliationReceipt,
    PlatformInvitationRetentionHold,
    PlatformInvitationRetentionPolicyControl,
    PlatformInvitationSchedulerRun,
    validate_login_handle,
)

NOW = datetime(2027, 8, 1, 12, tzinfo=UTC)


def _code(error: ValidationError) -> str:
    error_dict = getattr(error, "error_dict", None)
    if error_dict:
        return next(iter(error_dict.values()))[0].code or ""
    return error.error_list[0].code or ""


_FIELD_BY_CODE = {
    "invalid_invitation_envelope": {
        "payload",
        "encrypted_payload",
        "wrapped_data_key",
    },
    "invitation_acceptance_after_expiry": {"accepted_at"},
    "invitation_expiry_before_deadline": {"expired_at"},
    "invitation_current_challenge_invalid": {"current_challenge"},
    "identity_challenge_invitation_version_invalid": {"invitation_version"},
    "invitation_transition_reason_required": {"reason"},
    "invitation_transition_version_invalid": {"version"},
    "invitation_transition_actor_required": {"actor"},
    "invitation_transition_actor_inactive": {"actor"},
    "invitation_acceptance_actor_mismatch": {"actor"},
    "invitation_transition_actor_invalid": {"actor"},
    "identity_delivery_lease_invalid": {"lease_expires_at"},
    "identity_delivery_reconciliation_time_invalid": {"reconciled_at"},
    "identity_delivery_cancellation_time_invalid": {"cancelled_at"},
    "identity_delivery_provider_reference_invalid": {"provider_reference"},
    "identity_delivery_algorithm_invalid": {"encryption_algorithm"},
    "identity_delivery_nonce_invalid": {"payload_nonce"},
    "identity_delivery_attempt_limit": {"attempt_number"},
    "identity_delivery_retry_time_invalid": {"next_retry_at"},
    "identity_delivery_late_attempt_limit": {"attempt_number"},
    "identity_delivery_reconcile_scope_invalid": {"inventory_control"},
    "identity_delivery_reconcile_reason_required": {"reason"},
    "identity_delivery_reconcile_actor_invalid": {"actor"},
    "identity_delivery_reconcile_result_invalid": {"result_version"},
    "invitation_retention_hold_actor_invalid": {"placed_by"},
    "invitation_retention_release_actor_invalid": {"released_by"},
    "invitation_retention_hold_chronology_invalid": {"released_at"},
    "invitation_scheduler_generation_invalid": {"generation"},
    "invitation_scheduler_key_coverage_invalid": {"private_key_coverage_complete"},
    "invitation_scheduler_policy_digest_required": {"policy_digest"},
    "invitation_scheduler_retention_cursor_invalid": {"inspected_count"},
    "invitation_scheduler_retention_cursor_time_invalid": {
        "retention_cursor_transition_at"
    },
    "invitation_scheduler_retention_counts_invalid": {"inspected_count"},
    "invitation_scheduler_policy_digest_invalid": {"policy_digest"},
}


def _account(
    *,
    admin: bool = False,
    active: bool = True,
    email: str | None = None,
) -> Account:
    account = Account(
        id=uuid4(),
        email=email or f"person-{uuid4()}@example.invalid",
        display_name="Synthetic Person",
        account_kind=(
            Account.Kind.PLATFORM_ADMINISTRATOR if admin else Account.Kind.PERSON
        ),
        is_active=active,
        is_staff=admin,
        is_superuser=admin,
    )
    account.set_unusable_password()
    return account


def _invitation(
    *,
    account: Account | None = None,
    creator: Account | None = None,
    status: str = PlatformAccountInvitation.Status.PENDING,
) -> PlatformAccountInvitation:
    account = account or _account(active=False)
    return PlatformAccountInvitation(
        id=uuid4(),
        account=account,
        created_by=creator or _account(admin=True),
        status=status,
        aggregate_version=2,
        expires_at=NOW + timedelta(days=1),
        last_transition_at=NOW,
    )


def _challenge(
    *,
    invitation: PlatformAccountInvitation | None = None,
    account: Account | None = None,
) -> IdentityChallenge:
    invitation = invitation or _invitation(account=account)
    account = account or invitation.account
    return IdentityChallenge(
        id=uuid4(),
        account=account,
        purpose=IdentityChallenge.Purpose.ACCOUNT_INVITATION,
        token_digest="a" * 64,
        token_digest_key_id="digest-v1",
        email_snapshot=account.email,
        expires_at=NOW + timedelta(days=1),
        invitation=invitation,
        invitation_version=invitation.aggregate_version,
        request_fingerprint="b" * 64,
        delivery_status=IdentityChallenge.DeliveryStatus.SUPPRESSED,
    )


def _canonical_bytes(size: int, byte: bytes = b"x") -> bytes:
    return base64.urlsafe_b64encode(byte * size).rstrip(b"=")


def _delivery() -> PlatformIdentityDelivery:
    invitation = _invitation()
    challenge = _challenge(invitation=invitation)
    return PlatformIdentityDelivery(
        id=uuid4(),
        invitation=invitation,
        challenge=challenge,
        status=PlatformIdentityDelivery.Status.PENDING,
        aggregate_version=2,
        max_attempts=3,
        available_at=NOW,
        encryption_algorithm=models.INVITATION_DELIVERY_ENCRYPTION_ALGORITHM,
        encryption_key_id="envelope-v1",
        encrypted_payload=_canonical_bytes(models.INVITATION_PAYLOAD_MIN_DECODED_BYTES),
        wrapped_data_key=_canonical_bytes(
            models.INVITATION_WRAPPED_KEY_MIN_DECODED_BYTES,
            b"k",
        ),
        payload_nonce=b"n" * models.INVITATION_PAYLOAD_NONCE_BYTES,
        payload_aad_digest="c" * 64,
    )


def _assert_clean_error(instance: object, code: str) -> None:
    with pytest.raises(ValidationError) as error:
        instance.clean()  # type: ignore[attr-defined]
    actual_code = _code(error.value)
    if actual_code:
        assert actual_code == code
        return
    error_dict = getattr(error.value, "error_dict", {})
    assert set(error_dict) & _FIELD_BY_CODE[code]


@pytest.mark.parametrize(
    "value", ["name@example.invalid", "line\nbreak", "bad\x00name"]
)
def test_login_handle_rejects_email_ambiguity_and_controls(value: str) -> None:
    with pytest.raises(ValidationError):
        validate_login_handle(value)
    validate_login_handle("Synthetic Person")


def test_envelope_components_require_bounded_canonical_unpadded_base64url() -> None:
    models._validate_canonical_base64url(
        None,
        field_name="payload",
        minimum_decoded=1,
        maximum_decoded=4,
    )
    models._validate_canonical_base64url(
        b"eA",
        field_name="payload",
        minimum_decoded=1,
        maximum_decoded=4,
    )
    for value in (b"", b"eA==", b"*", b"eHh4eA"):
        with pytest.raises(ValidationError) as error:
            models._validate_canonical_base64url(
                value,
                field_name="payload",
                minimum_decoded=1,
                maximum_decoded=3,
            )
        assert "payload" in error.value.message_dict


def test_account_labels_never_fall_back_to_email() -> None:
    account = _account(email="private@example.invalid")
    account.display_name = ""
    account.login_handle = ""
    assert str(account) == str(account.id)
    account.login_handle = "public-handle"
    assert str(account) == "public-handle"
    account.display_name = "Public label"
    assert str(account) == "Public label"
    assert account.has_verified_email is False
    assert account.is_platform_administrator is False
    operator = _account(admin=True)
    operator.email_verified_at = NOW
    assert operator.has_verified_email is True
    assert operator.is_platform_administrator is True


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (
            lambda invitation: setattr(
                invitation.account,
                "account_kind",
                Account.Kind.PLATFORM_ADMINISTRATOR,
            ),
            "invitation_subject_kind_invalid",
        ),
        (
            lambda invitation: setattr(invitation.account, "is_active", True),
            "invitation_subject_state_invalid",
        ),
        (
            lambda invitation: setattr(invitation, "created_by", _account(admin=False)),
            "invitation_creator_invalid",
        ),
        (
            lambda invitation: setattr(
                invitation,
                "accepted_at",
                invitation.expires_at + timedelta(seconds=1),
            ),
            "invitation_acceptance_after_expiry",
        ),
        (
            lambda invitation: (
                setattr(invitation, "status", PlatformAccountInvitation.Status.EXPIRED),
                setattr(
                    invitation,
                    "expired_at",
                    invitation.expires_at - timedelta(seconds=1),
                ),
            ),
            "invitation_expiry_before_deadline",
        ),
    ],
)
def test_invitation_integrity_rejects_invalid_subject_provenance_and_time(
    mutate: object,
    code: str,
) -> None:
    invitation = _invitation()
    mutate(invitation)  # type: ignore[operator]
    _assert_clean_error(invitation, code)


def test_invitation_current_challenge_must_match_exact_active_generation() -> None:
    invitation = _invitation()
    challenge = _challenge(invitation=invitation)
    invitation.current_challenge = challenge
    invitation.clean()
    challenge.invitation_version = invitation.aggregate_version - 1
    _assert_clean_error(invitation, "invitation_current_challenge_invalid")


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (
            lambda challenge: setattr(challenge, "token_digest_key_id", ""),
            "identity_challenge_digest_key_required",
        ),
        (
            lambda challenge: (
                setattr(challenge, "purpose", IdentityChallenge.Purpose.VERIFY_EMAIL),
                setattr(challenge, "invitation", None),
                setattr(challenge, "invitation_version", None),
            ),
            "identity_challenge_digest_key_not_allowed",
        ),
        (
            lambda challenge: setattr(
                challenge, "email_snapshot", "other@example.invalid"
            ),
            "identity_challenge_contact_mismatch",
        ),
        (
            lambda challenge: setattr(
                challenge,
                "invitation_version",
                challenge.invitation.aggregate_version + 1,
            ),
            "identity_challenge_invitation_version_invalid",
        ),
    ],
)
def test_challenge_integrity_rejects_stale_or_ambiguous_lineage(
    mutate: object,
    code: str,
) -> None:
    challenge = _challenge()
    mutate(challenge)  # type: ignore[operator]
    _assert_clean_error(challenge, code)


def test_terminal_legacy_invitation_challenge_may_retain_blank_digest_lineage() -> None:
    challenge = _challenge()
    challenge.token_digest_key_id = ""
    challenge.invalidated_at = NOW
    challenge.invalidation_reason = "superseded"
    challenge.clean()


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (
            lambda transition: setattr(transition, "reason", "   "),
            "invitation_transition_reason_required",
        ),
        (
            lambda transition: setattr(
                transition,
                "version",
                transition.invitation.aggregate_version + 1,
            ),
            "invitation_transition_version_invalid",
        ),
        (
            lambda transition: setattr(transition, "actor", None),
            "invitation_transition_actor_required",
        ),
        (
            lambda transition: setattr(transition.actor, "is_active", False),
            "invitation_transition_actor_inactive",
        ),
        (
            lambda transition: (
                setattr(
                    transition,
                    "operation",
                    PlatformAccountInvitationTransition.Operation.ACCEPTED,
                ),
                setattr(transition, "actor", _account(active=True)),
            ),
            "invitation_acceptance_actor_mismatch",
        ),
        (
            lambda transition: setattr(transition, "actor", _account(active=True)),
            "invitation_transition_actor_invalid",
        ),
    ],
)
def test_invitation_transition_requires_current_exact_actor_and_version(
    mutate: object,
    code: str,
) -> None:
    transition = PlatformAccountInvitationTransition(
        invitation=_invitation(),
        version=1,
        operation=PlatformAccountInvitationTransition.Operation.REISSUED,
        actor=_account(admin=True),
        occurred_at=NOW,
        reason="Refresh the recipient-owned challenge.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    mutate(transition)  # type: ignore[operator]
    _assert_clean_error(transition, code)


def test_expiry_transition_allows_system_actor_absence() -> None:
    transition = PlatformAccountInvitationTransition(
        invitation=_invitation(),
        version=1,
        operation=PlatformAccountInvitationTransition.Operation.EXPIRED,
        actor=None,
        occurred_at=NOW,
        reason="Invitation expired.",
        correlation_id=uuid4(),
        source_channel="scheduler",
    )
    transition.clean()


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (
            lambda delivery: setattr(delivery.challenge, "invitation", _invitation()),
            "identity_delivery_challenge_mismatch",
        ),
        (
            lambda delivery: (
                setattr(delivery, "claimed_at", NOW),
                setattr(delivery, "lease_expires_at", NOW),
            ),
            "identity_delivery_lease_invalid",
        ),
        (
            lambda delivery: (
                setattr(delivery, "reconciliation_required_at", NOW),
                setattr(delivery, "reconciled_at", NOW - timedelta(seconds=1)),
            ),
            "identity_delivery_reconciliation_time_invalid",
        ),
        (
            lambda delivery: (
                setattr(delivery, "cancellation_requested_at", NOW),
                setattr(delivery, "cancelled_at", NOW - timedelta(seconds=1)),
            ),
            "identity_delivery_cancellation_time_invalid",
        ),
        (
            lambda delivery: setattr(delivery, "provider_reference", "bad\x00ref"),
            "identity_delivery_provider_reference_invalid",
        ),
        (
            lambda delivery: setattr(delivery, "encryption_algorithm", "legacy"),
            "identity_delivery_algorithm_invalid",
        ),
        (
            lambda delivery: setattr(delivery, "payload_nonce", b"short"),
            "identity_delivery_nonce_invalid",
        ),
        (
            lambda delivery: setattr(delivery, "encrypted_payload", b"not*base64"),
            "invalid_invitation_envelope",
        ),
        (
            lambda delivery: setattr(delivery, "wrapped_data_key", b"not*base64"),
            "invalid_invitation_envelope",
        ),
    ],
)
def test_delivery_envelope_and_lifecycle_validation_fail_closed(
    mutate: object,
    code: str,
) -> None:
    delivery = _delivery()
    mutate(delivery)  # type: ignore[operator]
    _assert_clean_error(delivery, code)


def test_valid_live_and_destroyed_delivery_envelopes_pass_model_validation() -> None:
    delivery = _delivery()
    delivery.clean()
    delivery.payload_destroyed_at = NOW
    delivery.encryption_algorithm = ""
    delivery.encryption_key_id = ""
    delivery.encrypted_payload = None
    delivery.wrapped_data_key = None
    delivery.payload_nonce = None
    delivery.payload_aad_digest = ""
    delivery.payload_destruction_reason = (
        PlatformIdentityDelivery.PayloadDestructionReason.REVOKED
    )
    delivery.clean()


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (
            lambda attempt: setattr(attempt, "attempt_number", 4),
            "identity_delivery_attempt_limit",
        ),
        (
            lambda attempt: setattr(attempt, "next_retry_at", attempt.finished_at),
            "identity_delivery_retry_time_invalid",
        ),
        (
            lambda attempt: setattr(attempt, "provider_reference", "bad\nref"),
            "identity_delivery_provider_reference_invalid",
        ),
    ],
)
def test_delivery_attempt_validation_enforces_bounds_and_safe_evidence(
    mutate: object,
    code: str,
) -> None:
    attempt = PlatformIdentityDeliveryAttempt(
        delivery=_delivery(),
        attempt_number=1,
        lease_token=uuid4(),
        started_at=NOW,
        finished_at=NOW + timedelta(seconds=1),
        outcome=PlatformIdentityDeliveryAttempt.Outcome.DELIVERED,
    )
    mutate(attempt)  # type: ignore[operator]
    _assert_clean_error(attempt, code)


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (
            lambda outcome: setattr(outcome, "attempt_number", 4),
            "identity_delivery_late_attempt_limit",
        ),
        (
            lambda outcome: setattr(outcome, "provider_reference", "bad\x7fref"),
            "identity_delivery_provider_reference_invalid",
        ),
    ],
)
def test_late_delivery_outcome_validation_enforces_bounds_and_safe_evidence(
    mutate: object,
    code: str,
) -> None:
    outcome = PlatformIdentityDeliveryLateOutcome(
        delivery=_delivery(),
        attempt_number=1,
        lease_token=uuid4(),
        observed_at=NOW,
        outcome=PlatformIdentityDeliveryLateOutcome.Outcome.DELIVERED,
        classification=(
            PlatformIdentityDeliveryLateOutcome.Classification.LEASE_SUPERSEDED
        ),
        provider_reference="provider-1",
    )
    mutate(outcome)  # type: ignore[operator]
    _assert_clean_error(outcome, code)


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (
            lambda receipt: setattr(receipt, "inventory_control_id", False),
            "identity_delivery_reconcile_scope_invalid",
        ),
        (
            lambda receipt: setattr(receipt, "reason", " "),
            "identity_delivery_reconcile_reason_required",
        ),
        (
            lambda receipt: setattr(receipt.actor, "is_active", False),
            "identity_delivery_reconcile_actor_invalid",
        ),
        (
            lambda receipt: setattr(
                receipt, "result_version", receipt.delivery.aggregate_version + 1
            ),
            "identity_delivery_reconcile_result_invalid",
        ),
    ],
)
def test_reconciliation_receipt_is_exact_scoped_and_operator_owned(
    mutate: object,
    code: str,
) -> None:
    delivery = _delivery()
    receipt = PlatformIdentityDeliveryReconciliationReceipt(
        inventory_control_id=True,
        delivery=delivery,
        actor=_account(admin=True),
        operation=(
            PlatformIdentityDeliveryReconciliationReceipt.Operation.RESOLVE_DELIVERED
        ),
        reason="Provider confirmed delivery.",
        retry_key=uuid4(),
        request_digest="d" * 64,
        expected_version=1,
        result_version=2,
        correlation_id=uuid4(),
        source_channel="test",
    )
    mutate(receipt)  # type: ignore[operator]
    _assert_clean_error(receipt, code)


def test_retention_policy_control_requires_complete_approved_contract() -> None:
    control = PlatformInvitationRetentionPolicyControl(
        singleton=True,
        generation="retention-policy-v1",
        policy_id="synthetic-policy",
        policy_version=1,
        policy_digest="e" * 64,
        jurisdiction_code="HU",
        policy_approved_by_reference="approval-1",
        policy_approved_at=NOW,
        trigger="terminal_transition",
        retention_period_days=30,
        action="anonymize_abandoned_invitation_contact",
        activated_at=NOW,
    )
    control.clean()
    for attribute, value in [
        ("generation", "legacy"),
        ("trigger", "created"),
        ("action", "delete"),
        ("policy_approved_at", NOW + timedelta(seconds=1)),
    ]:
        invalid = PlatformInvitationRetentionPolicyControl(
            **{
                field.name: getattr(control, field.name)
                for field in control._meta.concrete_fields
                if field.name not in {"created_at", "updated_at"}
            }
        )
        setattr(invalid, attribute, value)
        _assert_clean_error(invalid, "invitation_retention_policy_control_invalid")


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (
            lambda hold: setattr(hold.placed_by, "is_active", False),
            "invitation_retention_hold_actor_invalid",
        ),
        (
            lambda hold: (
                setattr(hold, "released_by", _account(admin=False)),
                setattr(hold, "released_at", NOW + timedelta(seconds=1)),
            ),
            "invitation_retention_release_actor_invalid",
        ),
        (
            lambda hold: setattr(hold, "released_at", NOW - timedelta(seconds=1)),
            "invitation_retention_hold_chronology_invalid",
        ),
    ],
)
def test_retention_hold_requires_current_operator_and_valid_chronology(
    mutate: object,
    code: str,
) -> None:
    hold = PlatformInvitationRetentionHold(
        invitation=_invitation(),
        reference_code="case-1",
        reason_code="legal-hold",
        placed_at=NOW,
        placed_by=_account(admin=True),
        place_correlation_id=uuid4(),
        active=True,
    )
    mutate(hold)  # type: ignore[operator]
    _assert_clean_error(hold, code)


def _scheduler_run(**overrides: object) -> PlatformInvitationSchedulerRun:
    values: dict[str, object] = {
        "kind": PlatformInvitationSchedulerRun.Kind.RETENTION,
        "generation": PlatformInvitationSchedulerRun.Generation.RETENTION_V2,
        "ran_at": NOW,
        "processed_count": 1,
        "remaining_count": 0,
        "private_key_coverage_complete": False,
        "policy_digest": "f" * 64,
        "inspected_count": 3,
        "blocked_count": 1,
        "held_count": 1,
        "retention_cursor_transition_at": NOW,
        "retention_cursor_invitation_id": uuid4(),
    }
    values.update(overrides)
    return PlatformInvitationSchedulerRun(**values)


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        (
            {"generation": PlatformInvitationSchedulerRun.Generation.EXPIRY_V1},
            "invitation_scheduler_generation_invalid",
        ),
        (
            {"private_key_coverage_complete": True},
            "invitation_scheduler_key_coverage_invalid",
        ),
        ({"policy_digest": ""}, "invitation_scheduler_policy_digest_required"),
        (
            {"inspected_count": 0},
            "invitation_scheduler_retention_cursor_invalid",
        ),
        (
            {"retention_cursor_transition_at": NOW + timedelta(seconds=1)},
            "invitation_scheduler_retention_cursor_time_invalid",
        ),
        (
            {"processed_count": 2, "blocked_count": 2, "held_count": 1},
            "invitation_scheduler_retention_counts_invalid",
        ),
        (
            {
                "kind": PlatformInvitationSchedulerRun.Kind.EXPIRY,
                "generation": PlatformInvitationSchedulerRun.Generation.EXPIRY_V1,
                "private_key_coverage_complete": False,
                "policy_digest": "f" * 64,
                "inspected_count": 0,
                "blocked_count": 0,
                "held_count": 0,
                "processed_count": 0,
                "retention_cursor_transition_at": None,
                "retention_cursor_invitation_id": None,
            },
            "invitation_scheduler_policy_digest_invalid",
        ),
    ],
)
def test_scheduler_heartbeat_evidence_matches_its_exact_run_kind(
    overrides: dict[str, object],
    code: str,
) -> None:
    _assert_clean_error(_scheduler_run(**overrides), code)


def test_delivery_expiry_and_retention_scheduler_shapes_are_distinct() -> None:
    _scheduler_run().clean()
    PlatformInvitationSchedulerRun(
        kind=PlatformInvitationSchedulerRun.Kind.DELIVERY,
        generation=PlatformInvitationSchedulerRun.Generation.DELIVERY_V1,
        ran_at=NOW,
        private_key_coverage_complete=True,
    ).clean()
    PlatformInvitationSchedulerRun(
        kind=PlatformInvitationSchedulerRun.Kind.EXPIRY,
        generation=PlatformInvitationSchedulerRun.Generation.EXPIRY_V1,
        ran_at=NOW,
        private_key_coverage_complete=False,
    ).clean()
