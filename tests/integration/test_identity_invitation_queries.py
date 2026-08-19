from __future__ import annotations

import base64
from dataclasses import asdict
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from maru.identity import invitation_queries
from maru.identity.invitation_queries import (
    MAX_ACCOUNT_INVENTORY_PAGE_SIZE,
    AccountInventoryPage,
    PlatformAccountInventoryCursorStaleError,
    PlatformAccountInventoryDeniedError,
    PlatformAccountInventoryInputError,
    PlatformAccountInventoryLimitExceededError,
    PlatformAccountInventoryUnavailableError,
    PlatformAccountInvitationNotFoundError,
    PlatformAccountSensitiveReadAudit,
    load_platform_account_inventory,
    load_platform_account_invitation_detail,
    normalize_account_inventory_search,
)
from maru.identity.models import (
    Account,
    IdentityChallenge,
    PlatformAccountInventoryControl,
    PlatformAccountInvitation,
    PlatformAccountInvitationCommandReceipt,
    PlatformAccountInvitationTransition,
    PlatformIdentityDelivery,
    PlatformIdentityDeliveryAttempt,
)

pytestmark = pytest.mark.django_db


def _account(
    *,
    email: str,
    display_name: str = "",
    login_handle: str = "",
    password: str | None = None,
    is_active: bool = True,
    is_staff: bool = False,
    is_superuser: bool = False,
    email_verified: bool = True,
    account_kind: str = Account.Kind.PERSON,
) -> Account:
    return Account.objects.create_user(
        email=email,
        display_name=display_name,
        login_handle=login_handle,
        password=password,
        is_active=is_active,
        is_staff=is_staff,
        is_superuser=is_superuser,
        email_verified_at=timezone.now() if email_verified else None,
        account_kind=account_kind,
    )


def _platform_administrator() -> Account:
    return _account(
        email="platform@example.invalid",
        display_name="Platform Operator",
        is_active=True,
        is_staff=True,
        is_superuser=True,
        account_kind=Account.Kind.PLATFORM_ADMINISTRATOR,
    )


def _advance_inventory_version() -> int:
    control = PlatformAccountInventoryControl.objects.get(singleton=True)
    control.aggregate_version += 1
    control.save(update_fields=("aggregate_version", "updated_at"))
    return control.aggregate_version


def _encoded(value: bytes) -> bytes:
    return base64.urlsafe_b64encode(value).rstrip(b"=")


def _invitation_with_delivery(
    *,
    actor: Account,
    max_attempts: int = 8,
) -> tuple[Account, PlatformAccountInvitation, PlatformIdentityDelivery]:
    now = timezone.now()
    subject = _account(
        email="cafe.person@example.invalid",
        login_handle="Caf\u00e9Fox",
        display_name="Caf\u00e9 Fox",
        password=None,
        is_active=False,
        email_verified=False,
    )
    invitation_id = uuid4()
    challenge_id = uuid4()
    transition_at = now
    invitation = PlatformAccountInvitation(
        id=invitation_id,
        account=subject,
        status=PlatformAccountInvitation.Status.PENDING,
        aggregate_version=1,
        expires_at=now + timedelta(days=2),
        last_transition_at=transition_at,
        current_challenge_id=challenge_id,
        created_by=actor,
    )
    PlatformAccountInvitation.objects.bulk_create([invitation])
    correlation_id = uuid4()
    PlatformAccountInvitationTransition.objects.create(
        invitation=invitation,
        version=1,
        operation=PlatformAccountInvitationTransition.Operation.CREATED,
        actor=actor,
        occurred_at=transition_at,
        reason="Synthetic onboarding rehearsal",
        correlation_id=correlation_id,
        source_channel="test",
    )
    PlatformAccountInvitationCommandReceipt.objects.create(
        inventory_control=PlatformAccountInventoryControl.objects.get(singleton=True),
        invitation=invitation,
        actor=actor,
        operation=PlatformAccountInvitationCommandReceipt.Operation.CREATE,
        retry_key=uuid4(),
        request_digest="4" * 64,
        expected_version=0,
        result_version=1,
        correlation_id=correlation_id,
        source_channel="test",
    )
    challenge = IdentityChallenge.objects.create(
        id=challenge_id,
        account=subject,
        purpose=IdentityChallenge.Purpose.ACCOUNT_INVITATION,
        delivery_status=IdentityChallenge.DeliveryStatus.SUPPRESSED,
        token_digest=uuid4().hex + uuid4().hex,
        token_digest_key_id="query-projection-digest-v1",
        email_snapshot=subject.email,
        expires_at=invitation.expires_at,
        invitation=invitation,
        invitation_version=1,
        request_fingerprint=uuid4().hex + uuid4().hex,
    )
    delivery = PlatformIdentityDelivery.objects.create(
        invitation=invitation,
        challenge=challenge,
        encryption_algorithm="aes-256-gcm+rsa-oaep-sha256-v1",
        encryption_key_id="test-key-v1",
        encrypted_payload=_encoded(b"e" * 17),
        wrapped_data_key=_encoded(b"k" * 256),
        payload_nonce=b"n" * 12,
        payload_aad_digest="a" * 64,
        max_attempts=8,
    )
    if max_attempts != 8:
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute(
                "ALTER TABLE identity_platformidentitydelivery DISABLE TRIGGER "
                "identity_page10_hardened_delivery_update"
            )
            cursor.execute(
                "ALTER TABLE identity_platformidentitydelivery DISABLE TRIGGER "
                "identity_page10_hardened_delivery_complete"
            )
            try:
                cursor.execute(
                    "UPDATE identity_platformidentitydelivery "
                    "SET max_attempts = %s, "
                    "aggregate_version = aggregate_version + 1, "
                    "updated_at = clock_timestamp() WHERE id = %s",
                    [max_attempts, delivery.id],
                )
            finally:
                cursor.execute(
                    "ALTER TABLE identity_platformidentitydelivery ENABLE TRIGGER "
                    "identity_page10_hardened_delivery_complete"
                )
                cursor.execute(
                    "ALTER TABLE identity_platformidentitydelivery ENABLE TRIGGER "
                    "identity_page10_hardened_delivery_update"
                )
                cursor.execute("SET CONSTRAINTS ALL DEFERRED")
        delivery.refresh_from_db()
    return subject, invitation, delivery


def _insert_projection_attempts(
    attempts: list[PlatformIdentityDeliveryAttempt],
) -> None:
    """Create deliberately historical read-fixture rows as the test DB owner."""

    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute(
            "ALTER TABLE identity_platformidentitydeliveryattempt "
            "DISABLE TRIGGER identity_page10_hardened_attempt_insert"
        )
        cursor.execute(
            "ALTER TABLE identity_platformidentitydeliveryattempt "
            "DISABLE TRIGGER identity_page10_hardened_attempt_complete"
        )
        try:
            PlatformIdentityDeliveryAttempt.objects.bulk_create(attempts)
        finally:
            cursor.execute(
                "ALTER TABLE identity_platformidentitydeliveryattempt "
                "ENABLE TRIGGER identity_page10_hardened_attempt_complete"
            )
            cursor.execute(
                "ALTER TABLE identity_platformidentitydeliveryattempt "
                "ENABLE TRIGGER identity_page10_hardened_attempt_insert"
            )
            cursor.execute("SET CONSTRAINTS ALL DEFERRED")


def _add_delivery_attempt(delivery: PlatformIdentityDelivery) -> None:
    now = timezone.now()
    _insert_projection_attempts(
        [
            PlatformIdentityDeliveryAttempt(
                delivery=delivery,
                attempt_number=1,
                lease_token=uuid4(),
                started_at=now,
                finished_at=now + timedelta(seconds=1),
                outcome=PlatformIdentityDeliveryAttempt.Outcome.UNCERTAIN,
                provider_reference="provider-internal-reference",
                safe_error_code="provider_result_uncertain",
            )
        ]
    )


def test_inventory_is_bounded_minimized_versioned_and_constant_query_count() -> None:
    actor = _platform_administrator()
    subject, invitation, _delivery = _invitation_with_delivery(actor=actor)
    inventory_version = _advance_inventory_version()
    audits: list[PlatformAccountSensitiveReadAudit] = []

    with CaptureQueriesContext(connection) as queries:
        page = load_platform_account_inventory(
            actor=actor,
            audit_hook=audits.append,
            correlation_id=uuid4(),
            source_channel="test",
        )

    assert len(queries) == 7
    inventory_sql = " ".join(query["sql"] for query in queries.captured_queries)
    for forbidden_relation in (
        "organization_membership",
        "participation_participation",
        "registration_registration",
        "workforce_",
    ):
        assert forbidden_relation not in inventory_sql.casefold()
    assert page.aggregate_version == inventory_version
    projected = next(item for item in page.items if item.account_id == subject.id)
    assert projected.email == subject.email
    assert projected.current_invitation is not None
    assert projected.current_invitation.invitation_id == invitation.id
    assert projected.current_invitation.status == "pending"
    assert projected.current_invitation.delivery_state == "pending"
    assert set(asdict(projected)) == {
        "account_id",
        "email",
        "login_handle",
        "display_name",
        "account_kind",
        "is_active",
        "is_email_verified",
        "date_joined",
        "current_invitation",
    }
    assert len(audits) == 1
    assert asdict(audits[0]).keys() == {
        "actor_id",
        "operation",
        "target_id",
        "aggregate_version",
        "result_count",
        "correlation_id",
        "source_channel",
    }
    assert subject.email not in repr(audits[0])


def test_inventory_search_filters_and_inputs_are_closed_and_normalized() -> None:
    actor = _platform_administrator()
    subject, _invitation, _delivery = _invitation_with_delivery(actor=actor)
    _account(
        email="other@example.invalid",
        display_name="Other Person",
        is_active=True,
    )
    _advance_inventory_version()

    page = load_platform_account_inventory(
        actor=actor,
        audit_hook=lambda _event: None,
        correlation_id=uuid4(),
        source_channel="test",
        search="  CAFE\u0301  ",
        search_mode="prefix",
        kind="person",
        state="inactive",
    )
    assert [item.account_id for item in page.items] == [subject.id]
    assert normalize_account_inventory_search("  CAFE\u0301  ") == "caf\u00e9"

    for field, value in (
        ("search", "x"),
        ("search", "bad\u200bsearch"),
        ("search_mode", "contains"),
        ("kind", "staff"),
        ("state", "enabled"),
        ("page_size", True),
        ("page_size", MAX_ACCOUNT_INVENTORY_PAGE_SIZE + 1),
    ):
        kwargs = {field: value}
        with pytest.raises(PlatformAccountInventoryInputError):
            load_platform_account_inventory(
                actor=actor,
                audit_hook=lambda _event: None,
                correlation_id=uuid4(),
                source_channel="test",
                **kwargs,
            )


def test_inventory_uses_signed_version_cursor_and_one_hundred_row_probe() -> None:
    actor = _platform_administrator()
    accounts = []
    for index in range(101):
        account = Account(
            email=f"bounded-{index:03d}@example.invalid",
            display_name=f"Bounded Person {index:03d}",
            is_active=True,
            email_verified_at=timezone.now(),
        )
        account.set_unusable_password()
        accounts.append(account)
    Account.objects.bulk_create(accounts)
    _advance_inventory_version()

    with CaptureQueriesContext(connection) as first_queries:
        first = load_platform_account_inventory(
            actor=actor,
            audit_hook=lambda _event: None,
            correlation_id=uuid4(),
            source_channel="test",
        )
    assert len(first_queries) == 6
    assert len(first.items) == 100
    assert first.next_cursor is not None

    second = load_platform_account_inventory(
        actor=actor,
        audit_hook=lambda _event: None,
        correlation_id=uuid4(),
        source_channel="test",
        cursor=first.next_cursor,
    )
    assert len(second.items) == 2
    assert second.next_cursor is None
    assert not (
        {item.account_id for item in first.items}
        & {item.account_id for item in second.items}
    )

    replacement = "a" if first.next_cursor[-1] != "a" else "b"
    tampered = f"{first.next_cursor[:-1]}{replacement}"
    with pytest.raises(PlatformAccountInventoryInputError):
        load_platform_account_inventory(
            actor=actor,
            audit_hook=lambda _event: None,
            correlation_id=uuid4(),
            source_channel="test",
            cursor=tampered,
        )

    _advance_inventory_version()
    with pytest.raises(PlatformAccountInventoryCursorStaleError):
        load_platform_account_inventory(
            actor=actor,
            audit_hook=lambda _event: None,
            correlation_id=uuid4(),
            source_channel="test",
            cursor=first.next_cursor,
        )


def test_non_admin_final_auth_and_audit_failure_release_no_projection() -> None:
    actor = _platform_administrator()
    subject, _invitation, _delivery = _invitation_with_delivery(actor=actor)
    ordinary = _account(email="ordinary@example.invalid")
    _advance_inventory_version()
    audit_calls: list[PlatformAccountSensitiveReadAudit] = []

    with pytest.raises(PlatformAccountInventoryDeniedError):
        load_platform_account_inventory(
            actor=ordinary,
            audit_hook=audit_calls.append,
            correlation_id=uuid4(),
            source_channel="test",
        )
    assert audit_calls == []

    real_load = invitation_queries._load_stable_inventory

    def deactivate_after_load(**kwargs: object) -> AccountInventoryPage:
        projection = real_load(**kwargs)  # type: ignore[arg-type]
        Account.objects.filter(id=actor.id).update(is_active=False)
        return projection

    with (
        patch.object(
            invitation_queries,
            "_load_stable_inventory",
            side_effect=deactivate_after_load,
        ),
        pytest.raises(PlatformAccountInventoryDeniedError),
    ):
        load_platform_account_inventory(
            actor=actor,
            audit_hook=audit_calls.append,
            correlation_id=uuid4(),
            source_channel="test",
        )
    assert audit_calls == []

    Account.objects.filter(id=actor.id).update(is_active=True)

    def broken_audit(_event: object) -> None:
        raise RuntimeError(f"must remain hidden: {subject.email}")

    with pytest.raises(PlatformAccountInventoryUnavailableError) as caught:
        load_platform_account_inventory(
            actor=actor,
            audit_hook=broken_audit,
            correlation_id=uuid4(),
            source_channel="test",
        )
    assert subject.email not in str(caught.value)
    assert caught.value.__cause__ is None


def test_inventory_retries_once_then_fails_name_free_on_continuous_movement() -> None:
    actor = _platform_administrator()
    subject, _invitation, _delivery = _invitation_with_delivery(actor=actor)
    inventory_version = _advance_inventory_version()

    with patch.object(
        invitation_queries,
        "_inventory_version",
        side_effect=[
            inventory_version,
            inventory_version + 1,
            inventory_version + 1,
            inventory_version + 1,
        ],
    ) as version_read:
        page = load_platform_account_inventory(
            actor=actor,
            audit_hook=lambda _event: None,
            correlation_id=uuid4(),
            source_channel="test",
        )
    assert page.aggregate_version == inventory_version + 1
    assert version_read.call_count == 4

    audit_calls: list[PlatformAccountSensitiveReadAudit] = []
    with (
        patch.object(
            invitation_queries,
            "_inventory_version",
            side_effect=[
                inventory_version + 1,
                inventory_version + 2,
                inventory_version + 2,
                inventory_version + 3,
            ],
        ) as version_read,
        pytest.raises(PlatformAccountInventoryUnavailableError) as caught,
    ):
        load_platform_account_inventory(
            actor=actor,
            audit_hook=audit_calls.append,
            correlation_id=uuid4(),
            source_channel="test",
        )
    assert version_read.call_count == 4
    assert audit_calls == []
    assert subject.email not in str(caught.value)


def test_invitation_detail_is_minimized_bounded_and_constant_query_count() -> None:
    actor = _platform_administrator()
    subject, invitation, delivery = _invitation_with_delivery(actor=actor)
    _add_delivery_attempt(delivery)
    _advance_inventory_version()
    audits: list[PlatformAccountSensitiveReadAudit] = []

    with CaptureQueriesContext(connection) as queries:
        detail = load_platform_account_invitation_detail(
            actor=actor,
            invitation_id=invitation.id,
            audit_hook=audits.append,
            correlation_id=uuid4(),
            source_channel="test",
        )

    assert len(queries) == 8
    assert detail.account_id == subject.id
    assert detail.current_delivery is not None
    assert detail.current_delivery.status == "pending"
    assert detail.transitions[0].operation == "created"
    assert detail.delivery_attempts[0].outcome == "uncertain"
    assert "provider-internal-reference" not in repr(detail)
    assert len(audits) == 1
    assert audits[0].target_id == invitation.id

    with pytest.raises(PlatformAccountInvitationNotFoundError):
        load_platform_account_invitation_detail(
            actor=actor,
            invitation_id=uuid4(),
            audit_hook=audits.append,
            correlation_id=uuid4(),
            source_channel="test",
        )


def test_invitation_detail_rejects_a_one_hundred_and_one_row_timeline_whole() -> None:
    actor = _platform_administrator()
    subject, invitation, delivery = _invitation_with_delivery(
        actor=actor,
        max_attempts=100,
    )
    now = timezone.now()
    _insert_projection_attempts(
        [
            PlatformIdentityDeliveryAttempt(
                delivery=delivery,
                attempt_number=attempt_number,
                lease_token=uuid4(),
                started_at=now + timedelta(seconds=attempt_number),
                finished_at=now + timedelta(seconds=attempt_number + 1),
                outcome=PlatformIdentityDeliveryAttempt.Outcome.UNCERTAIN,
                safe_error_code="bounded_timeline_test",
            )
            for attempt_number in range(1, 101)
        ]
    )
    _advance_inventory_version()
    audit_calls: list[PlatformAccountSensitiveReadAudit] = []

    with pytest.raises(PlatformAccountInventoryLimitExceededError) as caught:
        load_platform_account_invitation_detail(
            actor=actor,
            invitation_id=invitation.id,
            audit_hook=audit_calls.append,
            correlation_id=uuid4(),
            source_channel="test",
        )
    assert audit_calls == []
    assert subject.email not in str(caught.value)
