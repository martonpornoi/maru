"""Native writer retirement and observed readiness, not integrated acceptance."""

from importlib import import_module
from uuid import uuid4

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from maru.identity.invitation_writer_readiness import (
    invitation_writer_generation_is_ready,
)
from maru.identity.models import IdentityChallenge
from tests.integration.test_identity_invitation_commands import (
    _create,
)
from tests.integration.test_identity_invitation_commands import (
    configured_invitation_crypto as configured_invitation_crypto,  # noqa: PLC0414
)
from tests.integration.test_identity_invitation_commands import (
    inventory_control as inventory_control,  # noqa: PLC0414
)
from tests.integration.test_identity_invitation_commands import (
    invitation_private_key as invitation_private_key,  # noqa: PLC0414
)
from tests.integration.test_identity_invitation_commands import (
    platform_actor as platform_actor,  # noqa: PLC0414
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]
_MIGRATION = import_module("maru.identity.migrations.0023_invitation_writer_cutover")


@pytest.fixture
def invitation(configured_invitation_crypto, platform_actor):
    result = _create(actor=platform_actor, email="writer-cutover@example.invalid")
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    return result.invitation


def test_real_creation_preserves_canonical_delivery_and_readiness(invitation):
    assert invitation_writer_generation_is_ready()
    challenge = IdentityChallenge.objects.get(id=invitation.current_challenge_id)
    assert challenge.delivery_status == "suppressed"
    assert challenge.delivery_attempt_count == 0
    assert challenge.last_delivery_attempt_at is None
    assert challenge.delivered_at is None
    assert challenge.delivery_error_code == ""


@pytest.mark.parametrize(
    "field",
    [
        "delivery_status",
        "delivery_attempt_count",
        "last_delivery_attempt_at",
        "delivered_at",
        "delivery_error_code",
    ],
)
def test_legacy_invitation_delivery_writer_is_rejected_atomically(invitation, field):
    values = {
        "delivery_status": "succeeded",
        "delivery_attempt_count": 1,
        "last_delivery_attempt_at": timezone.now(),
        "delivered_at": timezone.now(),
        "delivery_error_code": "obsolete_writer",
    }
    with (
        pytest.raises(IntegrityError, match="legacy invitation delivery writers"),
        transaction.atomic(),
    ):
        IdentityChallenge.objects.filter(id=invitation.current_challenge_id).update(
            **{field: values[field]}
        )
    assert invitation_writer_generation_is_ready()
    assert (
        IdentityChallenge.objects.get(
            id=invitation.current_challenge_id
        ).delivery_status
        == "suppressed"
    )


def test_used_generation_refuses_reverse_before_removing_guard(invitation):
    with (
        pytest.raises(IntegrityError, match="requires fix-forward recovery"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(_MIGRATION.REVERSE_SQL)
    assert invitation_writer_generation_is_ready()


@pytest.mark.parametrize(
    "defect",
    ["disable", "drop", "public_execute", "function", "migration", "duplicate"],
)
def test_native_drift_never_becomes_ready(defect):
    assert invitation_writer_generation_is_ready()
    statements = {
        "disable": (
            "ALTER TABLE public.identity_identitychallenge "
            "DISABLE TRIGGER maru_identity_invitation_writer"
        ),
        "drop": (
            "DROP TRIGGER maru_identity_invitation_writer "
            "ON public.identity_identitychallenge"
        ),
        "public_execute": (
            "GRANT EXECUTE ON FUNCTION "
            "public.maru_identity_invitation_writer_guard() TO PUBLIC"
        ),
        "function": (
            "ALTER FUNCTION public.maru_identity_invitation_writer_guard() "
            "SECURITY DEFINER"
        ),
        "migration": (
            "DELETE FROM public.django_migrations WHERE app='identity' "
            "AND name='0023_invitation_writer_cutover'"
        ),
        "duplicate": (
            "CREATE TRIGGER rogue_writer BEFORE INSERT ON "
            "public.identity_identitychallenge FOR EACH ROW EXECUTE "
            "FUNCTION public.maru_identity_invitation_writer_guard()"
        ),
    }
    with connection.cursor() as cursor:
        cursor.execute(statements[defect])
    assert not invitation_writer_generation_is_ready()


def test_unused_generation_reverse_and_reapply_preserves_source():
    with connection.cursor() as cursor:
        cursor.execute(_MIGRATION.REVERSE_SQL)
    assert not invitation_writer_generation_is_ready()
    with connection.cursor() as cursor:
        cursor.execute(_MIGRATION.FORWARD_SQL)
    assert invitation_writer_generation_is_ready()


def test_new_invitation_challenge_cannot_select_a_legacy_delivery_writer(invitation):
    current = IdentityChallenge.objects.get(id=invitation.current_challenge_id)
    values = {
        field.attname: getattr(current, field.attname)
        for field in IdentityChallenge._meta.concrete_fields
    }
    values.update(id=uuid4(), token_digest="a" * 64, delivery_status="pending")
    with (
        pytest.raises(IntegrityError, match="canonical durable delivery"),
        transaction.atomic(),
    ):
        IdentityChallenge.objects.bulk_create([IdentityChallenge(**values)])


def test_existing_public_challenge_cannot_become_an_invitation(invitation):
    current = IdentityChallenge.objects.get(id=invitation.current_challenge_id)
    other = IdentityChallenge.objects.create(
        account_id=current.account_id,
        purpose="verify_email",
        token_digest="b" * 64,
        email_snapshot=current.email_snapshot,
        expires_at=current.expires_at,
        request_fingerprint="c" * 64,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        IdentityChallenge.objects.filter(id=other.id).update(
            purpose="account_invitation",
            invitation_id=invitation.id,
            invitation_version=current.invitation_version,
            token_digest_key_id=current.token_digest_key_id,
            delivery_status="suppressed",
        )
    other.refresh_from_db()
    assert other.purpose == "verify_email"
    assert other.invitation_id is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("restores_current_migration_graph")
def test_populated_upgrade_preserves_existing_inert_delivery_and_identity(
    configured_invitation_crypto,
    platform_actor,
):
    previous = ("identity", "0022_person_obligation_source_identity")
    current = ("identity", "0023_invitation_writer_cutover")
    MigrationExecutor(connection).migrate([previous])
    assert not invitation_writer_generation_is_ready()
    result = _create(actor=platform_actor, email="legacy-writer@example.invalid")
    challenge_id = result.invitation.current_challenge_id
    before = IdentityChallenge.objects.filter(id=challenge_id).values().get()
    MigrationExecutor(connection).migrate([current])
    assert invitation_writer_generation_is_ready()
    assert IdentityChallenge.objects.filter(id=challenge_id).values().get() == before
    assert before["delivery_status"] == "suppressed"
    with (
        pytest.raises(IntegrityError, match="legacy invitation delivery writers"),
        transaction.atomic(),
    ):
        IdentityChallenge.objects.filter(id=challenge_id).update(
            delivery_status="succeeded"
        )
    with pytest.raises(IntegrityError, match="requires fix-forward recovery"):
        MigrationExecutor(connection).migrate([previous])
    assert invitation_writer_generation_is_ready()
