"""Adversarial PostgreSQL coverage for dormant Programme write guards."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

import maru.effects.services as effect_services
from maru.authorization.policy import PolicyDecision
from maru.events.models import EventEdition
from maru.events.services import transition_edition
from maru.programme.commands import (
    configure_programme_readiness,
    create_organizer_core_item,
    revise_programme_working,
)
from maru.programme.models import (
    ProgrammeCommandReceipt,
    ProgrammeEditionControl,
    ProgrammeItem,
    ProgrammeItemSourceBinding,
    ProgrammePublicRendition,
    ProgrammeReadinessRequirement,
    ProgrammeReadinessRequirementRevision,
    ProgrammeWorkingRevision,
)
from tests.factories import AccountFactory, CapabilityGrantFactory, EventEditionFactory

if TYPE_CHECKING:
    from maru.identity.models import Account

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


class _PermitProgrammeAuthorizer:
    """Admit the sealed future capability without changing adoption profiles."""

    def authorize(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        capability_code: str,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        del principal_id, organization_id, edition_id, capability_code
        return PolicyDecision(
            allowed=True,
            fields=requested_fields or frozenset(),
            obligations=frozenset({"audit", "reason"}),
            reason_code="sealed_future_profile_harness",
        )


@pytest.fixture(autouse=True)
def admits_exact_effect(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep these tests focused on database-owned Programme integrity."""
    monkeypatch.setattr(
        effect_services,
        "require_effect_delivery_allowed",
        lambda **_kwargs: None,
    )


def _create_item(*, actor: Account, edition: EventEdition) -> ProgrammeItem:
    result = create_organizer_core_item(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        kind="ceremony",
        internal_title="Integrity-test working title",
        working_summary="Private integrity-test notes.",
        expected_version=0,
        reason="Create a valid baseline for raw database tamper tests.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=_PermitProgrammeAuthorizer(),
    )
    return ProgrammeItem.objects.get(id=result.item_id)


@pytest.mark.parametrize("tampered_column", ["organization_id", "edition_id"])
def test_raw_item_scope_tampering_is_atomic(tampered_column: str) -> None:
    """Reject both tenant and edition reassignment below the ORM boundary."""
    actor = AccountFactory()
    edition = EventEditionFactory()
    foreign_edition = EventEditionFactory()
    item = _create_item(actor=actor, edition=edition)
    foreign_value = (
        foreign_edition.organization_id
        if tampered_column == "organization_id"
        else foreign_edition.id
    )

    with (
        pytest.raises(DatabaseError, match="scope mismatch"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            f"""
            UPDATE public.programme_programmeitem
               SET {tampered_column} = %s,
                   aggregate_version = 2,
                   updated_at = %s
             WHERE id = %s
            """,  # noqa: S608
            [foreign_value, timezone.now(), item.id],
        )

    item.refresh_from_db()
    assert item.organization_id == edition.organization_id
    assert item.edition_id == edition.id
    assert item.aggregate_version == 1


def _insert_source_binding(
    *,
    item: ProgrammeItem,
    binding_code: str,
    source_object_id: UUID | None,
    source_version: int | None,
) -> None:
    now = timezone.now()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO public.programme_programmeitemsourcebinding(
                id, created_at, updated_at, item_id, organization_id,
                edition_id, binding_code, source_object_id, source_version
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                uuid4(),
                now,
                now,
                item.id,
                item.organization_id,
                item.edition_id,
                binding_code,
                source_object_id,
                source_version,
            ],
        )


def test_raw_malformed_provenance_is_atomic() -> None:
    """Reject a foreign-source shape invented for an organizer-owned item."""
    actor = AccountFactory()
    item = _create_item(actor=actor, edition=EventEditionFactory())

    with (
        pytest.raises(DatabaseError, match="cannot invent a foreign source"),
        transaction.atomic(),
    ):
        _insert_source_binding(
            item=item,
            binding_code="programme.source.applications-accepted@1",
            source_object_id=None,
            source_version=None,
        )

    assert ProgrammeItemSourceBinding.objects.filter(item=item).count() == 1


def test_raw_duplicate_provenance_is_atomic() -> None:
    """Reject even a well-shaped second source for the same item."""
    actor = AccountFactory()
    item = _create_item(actor=actor, edition=EventEditionFactory())

    with pytest.raises(DatabaseError), transaction.atomic():
        _insert_source_binding(
            item=item,
            binding_code="programme.source.organizer-core@1",
            source_object_id=None,
            source_version=None,
        )

    assert ProgrammeItemSourceBinding.objects.filter(item=item).count() == 1


def test_raw_update_of_append_only_revision_is_atomic() -> None:
    """Keep private working evidence immutable below Django model methods."""
    actor = AccountFactory()
    item = _create_item(actor=actor, edition=EventEditionFactory())
    revision = ProgrammeWorkingRevision.objects.get(item=item, sequence=1)

    with (
        pytest.raises(DatabaseError, match="append-only"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            UPDATE public.programme_programmeworkingrevision
               SET working_summary = %s
             WHERE id = %s
            """,
            ["Raw tampering must not survive.", revision.id],
        )

    revision.refresh_from_db()
    assert revision.working_summary == "Private integrity-test notes."


def test_raw_delete_of_command_receipt_is_atomic() -> None:
    """Keep receipt-backed command evidence immutable below Django methods."""
    actor = AccountFactory()
    item = _create_item(actor=actor, edition=EventEditionFactory())
    receipt = ProgrammeCommandReceipt.objects.get(item=item)

    with (
        pytest.raises(DatabaseError, match="receipts are immutable"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "DELETE FROM public.programme_programmecommandreceipt WHERE id = %s",
            [receipt.id],
        )

    assert ProgrammeCommandReceipt.objects.filter(id=receipt.id).exists()


def test_new_requirement_rejects_cursor_older_than_existing_working_source() -> None:
    """Require raw public-copy setup to bind the latest working dependency."""
    actor = AccountFactory()
    item = _create_item(actor=actor, edition=EventEditionFactory())
    now = timezone.now()

    with (
        pytest.raises(DatabaseError, match="initial dependency cursor is invalid"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            INSERT INTO public.programme_programmereadinessrequirement(
                id, created_at, updated_at, item_id, organization_id,
                edition_id, concern, disposition, requirement_version,
                dependency_version, item_version, last_modified_by_id
            ) VALUES (%s, %s, %s, %s, %s, %s, 'public_copy', 'required',
                      1, 0, 1, %s)
            """,
            [
                uuid4(),
                now,
                now,
                item.id,
                item.organization_id,
                item.edition_id,
                actor.id,
            ],
        )

    assert not ProgrammeReadinessRequirement.objects.filter(item=item).exists()


def _programme_item_guard_exists() -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                  FROM pg_catalog.pg_trigger
                 WHERE tgname = 'programme_item_guard'
                   AND NOT tgisinternal
            )
            """
        )
        row = cursor.fetchone()
    return bool(row and row[0])


def test_populated_0002_reverse_refuses_before_removing_guards() -> None:
    """Keep guard teardown atomic with its own populated-data preflight."""
    actor = AccountFactory()
    item = _create_item(actor=actor, edition=EventEditionFactory())
    guards = import_module("maru.programme.migrations.0002_integrity_guards")

    with (
        pytest.raises(DatabaseError, match="Cannot remove Programme integrity"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(guards.REVERSE_SQL)

    assert ProgrammeItem.objects.filter(id=item.id).exists()
    assert _programme_item_guard_exists()


def test_populated_0001_reverse_preflight_refuses_before_table_removal() -> None:
    """Fence CreateModel reversal even after a separate 0002 transaction."""
    actor = AccountFactory()
    item = _create_item(actor=actor, edition=EventEditionFactory())
    initial = import_module("maru.programme.migrations.0001_initial")

    with (
        pytest.raises(DatabaseError, match="Cannot remove Programme tables"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(initial.REVERSE_PREFLIGHT_SQL)

    assert ProgrammeItem.objects.filter(id=item.id).exists()
    assert _programme_item_guard_exists()


def test_item_advance_without_receipt_fails_at_commit_atomically() -> None:
    """Reject an otherwise-shaped version advance lacking command evidence."""
    actor = AccountFactory()
    item = _create_item(actor=actor, edition=EventEditionFactory())

    with (
        pytest.raises(DatabaseError, match="lacks exact immutable command evidence"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            UPDATE public.programme_programmeitem
               SET aggregate_version = 2,
                   updated_at = %s
             WHERE id = %s
            """,
            [timezone.now(), item.id],
        )

    item.refresh_from_db()
    assert item.aggregate_version == 1
    assert ProgrammeCommandReceipt.objects.filter(item=item).count() == 1


_RAW_ITEM_CREATE_REASON = (
    "Attempt direct item creation without canonical complete evidence."
)


def _attempt_raw_item_create(
    *,
    actor: Account,
    edition: EventEdition,
    include_working: bool,
    working_reason: str | None = None,
    final_control_version: int = 1,
) -> None:
    now = timezone.now()
    control_id = uuid4()
    item_id = uuid4()
    reason = _RAW_ITEM_CREATE_REASON
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO public.programme_programmeeditioncontrol(
                id, created_at, updated_at, organization_id, edition_id,
                aggregate_version
            ) VALUES (%s, %s, %s, %s, %s, 1)
            """,
            [control_id, now, now, edition.organization_id, edition.id],
        )
        for control_version in range(2, final_control_version + 1):
            cursor.execute(
                """
                UPDATE public.programme_programmeeditioncontrol
                   SET aggregate_version = %s, updated_at = %s
                 WHERE id = %s
                """,
                [control_version, now, control_id],
            )
        cursor.execute(
            """
            INSERT INTO public.programme_programmeitem(
                id, created_at, updated_at, organization_id, edition_id,
                kind, provenance_kind, lifecycle, aggregate_version,
                created_by_id, last_modified_by_id
            ) VALUES (
                %s, %s, %s, %s, %s, 'ceremony', 'organizer_core',
                'active', 1, %s, %s
            )
            """,
            [
                item_id,
                now,
                now,
                edition.organization_id,
                edition.id,
                actor.id,
                actor.id,
            ],
        )
        cursor.execute(
            """
            INSERT INTO public.programme_programmeitemsourcebinding(
                id, created_at, updated_at, item_id, organization_id,
                edition_id, binding_code, source_object_id, source_version
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                'programme.source.organizer-core@1', NULL, NULL
            )
            """,
            [
                uuid4(),
                now,
                now,
                item_id,
                edition.organization_id,
                edition.id,
            ],
        )
        if include_working:
            cursor.execute(
                """
                INSERT INTO public.programme_programmeworkingrevision(
                    id, created_at, updated_at, item_id, organization_id,
                    edition_id, sequence, item_version, internal_title,
                    working_summary, actor_id, reason, occurred_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, 1, 1,
                    'Raw initial title', '', %s, %s, %s
                )
                """,
                [
                    uuid4(),
                    now,
                    now,
                    item_id,
                    edition.organization_id,
                    edition.id,
                    actor.id,
                    working_reason,
                    now,
                ],
            )
        cursor.execute(
            """
            INSERT INTO public.programme_programmecommandreceipt(
                id, created_at, updated_at, control_id, item_id,
                organization_id, edition_id, operation, actor_id, reason,
                idempotency_key, request_digest, correlation_id,
                source_channel, result_object_id, expected_version,
                resulting_control_version, resulting_item_version
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, 'item_create', %s, %s,
                %s, %s, %s, 'service', %s, %s, %s, 1
            )
            """,
            [
                uuid4(),
                now,
                now,
                control_id,
                item_id,
                edition.organization_id,
                edition.id,
                actor.id,
                reason,
                uuid4(),
                "b" * 64,
                uuid4(),
                item_id,
                final_control_version - 1,
                final_control_version,
            ],
        )


@pytest.mark.parametrize(
    ("include_working", "working_reason"),
    [(False, None), (True, "A reason different from the creation receipt.")],
)
def test_raw_item_create_requires_exact_initial_working_evidence(
    include_working: bool,
    working_reason: str | None,
) -> None:
    """Refuse a creation receipt without its exact actor/reason-bound revision."""
    actor = AccountFactory()
    edition = EventEditionFactory()

    with pytest.raises(DatabaseError, match="command receipt evidence mismatch"):
        _attempt_raw_item_create(
            actor=actor,
            edition=edition,
            include_working=include_working,
            working_reason=working_reason,
        )

    assert not ProgrammeEditionControl.objects.filter(edition=edition).exists()
    assert not ProgrammeItem.objects.filter(edition=edition).exists()


def test_raw_control_multi_update_requires_every_transition_receipt() -> None:
    """Reject one final creation receipt reused for prior control versions."""
    actor = AccountFactory()
    edition = EventEditionFactory()

    with pytest.raises(DatabaseError, match="control lacks exact immutable"):
        _attempt_raw_item_create(
            actor=actor,
            edition=edition,
            include_working=True,
            working_reason=_RAW_ITEM_CREATE_REASON,
            final_control_version=3,
        )

    assert not ProgrammeEditionControl.objects.filter(edition=edition).exists()
    assert not ProgrammeItem.objects.filter(edition=edition).exists()


def _attempt_raw_item_multi_update_without_intermediate_evidence(
    *,
    actor: Account,
    item: ProgrammeItem,
) -> None:
    now = timezone.now()
    revision_id = uuid4()
    reason = "Attempt to cover two item transitions with only the final evidence."
    control_id = ProgrammeCommandReceipt.objects.get(
        item=item,
        operation="item_create",
    ).control_id
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE public.programme_programmeitem
               SET aggregate_version = 2, last_modified_by_id = %s,
                   updated_at = %s
             WHERE id = %s
            """,
            [actor.id, now, item.id],
        )
        cursor.execute(
            """
            UPDATE public.programme_programmeitem
               SET aggregate_version = 3, last_modified_by_id = %s,
                   updated_at = %s
             WHERE id = %s
            """,
            [actor.id, now, item.id],
        )
        cursor.execute(
            """
            INSERT INTO public.programme_programmeworkingrevision(
                id, created_at, updated_at, item_id, organization_id,
                edition_id, sequence, item_version, internal_title,
                working_summary, actor_id, reason, occurred_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, 2, 3,
                'Only final transition evidence', '', %s, %s, %s
            )
            """,
            [
                revision_id,
                now,
                now,
                item.id,
                item.organization_id,
                item.edition_id,
                actor.id,
                reason,
                now,
            ],
        )
        cursor.execute(
            """
            INSERT INTO public.programme_programmecommandreceipt(
                id, created_at, updated_at, control_id, item_id,
                organization_id, edition_id, operation, actor_id, reason,
                idempotency_key, request_digest, correlation_id,
                source_channel, result_object_id, expected_version,
                resulting_control_version, resulting_item_version
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, 'working_revise', %s, %s,
                %s, %s, %s, 'service', %s, 2, NULL, 3
            )
            """,
            [
                uuid4(),
                now,
                now,
                control_id,
                item.id,
                item.organization_id,
                item.edition_id,
                actor.id,
                reason,
                uuid4(),
                "e" * 64,
                uuid4(),
                revision_id,
            ],
        )


def test_raw_item_multi_update_requires_every_transition_receipt_and_child() -> None:
    """Reject a final child/receipt pair reused for an intermediate item version."""
    actor = AccountFactory()
    item = _create_item(actor=actor, edition=EventEditionFactory())

    with pytest.raises(DatabaseError, match="lacks exact immutable command evidence"):
        _attempt_raw_item_multi_update_without_intermediate_evidence(
            actor=actor,
            item=item,
        )

    item.refresh_from_db()
    assert item.aggregate_version == 1
    assert ProgrammeWorkingRevision.objects.filter(item=item).count() == 1
    assert ProgrammeCommandReceipt.objects.filter(item=item).count() == 1


def test_raw_initial_readiness_configuration_rejects_split_attribution() -> None:
    """Bind initial requirement, revision, item, and receipt actor atomically."""
    item_actor = AccountFactory()
    receipt_actor = AccountFactory()
    item = _create_item(actor=item_actor, edition=EventEditionFactory())
    now = timezone.now()
    requirement_id = uuid4()
    revision_id = uuid4()
    reason = "Attempt initial readiness setup with split actor attribution."
    control_id = ProgrammeCommandReceipt.objects.get(
        item=item,
        operation="item_create",
    ).control_id

    with (  # noqa: PT012
        pytest.raises(DatabaseError, match="command receipt evidence mismatch"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
                UPDATE public.programme_programmeitem
                   SET aggregate_version = 2, last_modified_by_id = %s,
                       updated_at = %s
                 WHERE id = %s
                """,
            [receipt_actor.id, now, item.id],
        )
        cursor.execute(
            """
                INSERT INTO public.programme_programmereadinessrequirement(
                    id, created_at, updated_at, item_id, organization_id,
                    edition_id, concern, disposition, requirement_version,
                    dependency_version, item_version, last_modified_by_id
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, 'public_copy', 'required',
                    1, 1, 2, %s
                )
                """,
            [
                requirement_id,
                now,
                now,
                item.id,
                item.organization_id,
                item.edition_id,
                item_actor.id,
            ],
        )
        cursor.execute(
            """
                INSERT INTO public.programme_programmereadinessrequirementrevision(
                    id, created_at, updated_at, requirement_id, item_id,
                    organization_id, edition_id, sequence, item_version,
                    disposition, actor_id, reason, occurred_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, 1, 2,
                    'required', %s, %s, %s
                )
                """,
            [
                revision_id,
                now,
                now,
                requirement_id,
                item.id,
                item.organization_id,
                item.edition_id,
                item_actor.id,
                reason,
                now,
            ],
        )
        cursor.execute(
            """
                INSERT INTO public.programme_programmecommandreceipt(
                    id, created_at, updated_at, control_id, item_id,
                    organization_id, edition_id, operation, actor_id, reason,
                    idempotency_key, request_digest, correlation_id,
                    source_channel, result_object_id, expected_version,
                    resulting_control_version, resulting_item_version
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    'readiness_configure', %s, %s, %s, %s, %s,
                    'service', %s, 1, NULL, 2
                )
                """,
            [
                uuid4(),
                now,
                now,
                control_id,
                item.id,
                item.organization_id,
                item.edition_id,
                receipt_actor.id,
                reason,
                uuid4(),
                "c" * 64,
                uuid4(),
                revision_id,
            ],
        )

    item.refresh_from_db()
    assert item.aggregate_version == 1
    assert not ProgrammeReadinessRequirement.objects.filter(item=item).exists()
    assert ProgrammeCommandReceipt.objects.filter(item=item).count() == 1


def test_raw_readiness_reconfiguration_rejects_split_attribution() -> None:
    """Keep mutable requirement attribution bound on later rationale changes."""
    item_actor = AccountFactory()
    receipt_actor = AccountFactory()
    item = _create_item(actor=item_actor, edition=EventEditionFactory())
    configure_programme_readiness(
        actor_id=item_actor.id,
        organization_id=item.organization_id,
        edition_id=item.edition_id,
        item_id=item.id,
        concern="public_copy",
        disposition="required",
        expected_version=1,
        reason="Create a valid readiness baseline.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=_PermitProgrammeAuthorizer(),
    )
    requirement = ProgrammeReadinessRequirement.objects.get(item=item)
    now = timezone.now()
    revision_id = uuid4()
    reason = "Attempt reconfiguration with split actor attribution."
    control_id = ProgrammeCommandReceipt.objects.get(
        item=item,
        operation="item_create",
    ).control_id

    with (  # noqa: PT012
        pytest.raises(DatabaseError, match="command receipt evidence mismatch"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
                UPDATE public.programme_programmeitem
                   SET aggregate_version = 3, last_modified_by_id = %s,
                       updated_at = %s
                 WHERE id = %s
                """,
            [receipt_actor.id, now, item.id],
        )
        cursor.execute(
            """
                UPDATE public.programme_programmereadinessrequirement
                   SET requirement_version = 2, item_version = 3,
                       last_modified_by_id = %s, updated_at = %s
                 WHERE id = %s
                """,
            [item_actor.id, now, requirement.id],
        )
        cursor.execute(
            """
                INSERT INTO public.programme_programmereadinessrequirementrevision(
                    id, created_at, updated_at, requirement_id, item_id,
                    organization_id, edition_id, sequence, item_version,
                    disposition, actor_id, reason, occurred_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, 2, 3,
                    'required', %s, %s, %s
                )
                """,
            [
                revision_id,
                now,
                now,
                requirement.id,
                item.id,
                item.organization_id,
                item.edition_id,
                item_actor.id,
                reason,
                now,
            ],
        )
        cursor.execute(
            """
                INSERT INTO public.programme_programmecommandreceipt(
                    id, created_at, updated_at, control_id, item_id,
                    organization_id, edition_id, operation, actor_id, reason,
                    idempotency_key, request_digest, correlation_id,
                    source_channel, result_object_id, expected_version,
                    resulting_control_version, resulting_item_version
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    'readiness_configure', %s, %s, %s, %s, %s,
                    'service', %s, 2, NULL, 3
                )
                """,
            [
                uuid4(),
                now,
                now,
                control_id,
                item.id,
                item.organization_id,
                item.edition_id,
                receipt_actor.id,
                reason,
                uuid4(),
                "d" * 64,
                uuid4(),
                revision_id,
            ],
        )

    item.refresh_from_db()
    requirement.refresh_from_db()
    assert item.aggregate_version == 2
    assert requirement.requirement_version == 1
    assert (
        ProgrammeReadinessRequirementRevision.objects.filter(
            requirement=requirement
        ).count()
        == 1
    )
    assert ProgrammeCommandReceipt.objects.filter(item=item).count() == 2


def test_raw_public_rendition_rejects_non_latest_working_source() -> None:
    """Require approval to cite the deterministic latest working revision."""
    actor = AccountFactory()
    item = _create_item(actor=actor, edition=EventEditionFactory())
    first = ProgrammeWorkingRevision.objects.get(item=item, sequence=1)
    revise_programme_working(
        actor_id=actor.id,
        organization_id=item.organization_id,
        edition_id=item.edition_id,
        item_id=item.id,
        internal_title="Latest private working title",
        working_summary="Latest private working summary.",
        expected_version=1,
        reason="Create a later source for approval selection.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=_PermitProgrammeAuthorizer(),
    )
    now = timezone.now()

    with (
        pytest.raises(DatabaseError, match="public rendition evidence mismatch"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            INSERT INTO public.programme_programmepublicrendition(
                id, created_at, updated_at, item_id, organization_id,
                edition_id, rendition_number, source_item_version,
                source_working_revision_id, supersedes_id, public_title,
                public_summary, public_content_note, reviewed_by_id,
                reviewed_at, review_reason
            ) VALUES (
                %s, %s, %s, %s, %s, %s, 1, 1, %s, NULL,
                'Stale public title', 'Stale public summary.', '', %s, %s, %s
            )
            """,
            [
                uuid4(),
                now,
                now,
                item.id,
                item.organization_id,
                item.edition_id,
                first.id,
                actor.id,
                now,
                "Attempt approval from an older working source.",
            ],
        )

    assert not ProgrammePublicRendition.objects.filter(item=item).exists()


def test_raw_public_rendition_rejects_closed_edition_atomically() -> None:
    """Apply the stabilized edition lifecycle rule to non-item approvals."""
    actor = AccountFactory()
    edition = EventEditionFactory()
    item = _create_item(actor=actor, edition=edition)
    working = ProgrammeWorkingRevision.objects.get(item=item, sequence=1)
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=actor,
        capability_code="events.transition",
    )
    for state in (EventEdition.Lifecycle.PREPARING, EventEdition.Lifecycle.READY):
        edition = transition_edition(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            to_state=state,
            actor=actor,
            reason=f"Advance to {state} for the raw Programme lifecycle proof.",
            correlation_id=uuid4(),
        )
    now = timezone.now()

    with (
        pytest.raises(DatabaseError, match="public rendition evidence mismatch"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            INSERT INTO public.programme_programmepublicrendition(
                id, created_at, updated_at, item_id, organization_id,
                edition_id, rendition_number, source_item_version,
                source_working_revision_id, supersedes_id, public_title,
                public_summary, public_content_note, reviewed_by_id,
                reviewed_at, review_reason
            ) VALUES (
                %s, %s, %s, %s, %s, %s, 1, 1, %s, NULL,
                'Closed public title', 'Closed public summary.', '', %s, %s, %s
            )
            """,
            [
                uuid4(),
                now,
                now,
                item.id,
                item.organization_id,
                item.edition_id,
                working.id,
                actor.id,
                now,
                "Attempt approval after the edition is ready.",
            ],
        )

    assert not ProgrammePublicRendition.objects.filter(item=item).exists()
    assert ProgrammeCommandReceipt.objects.filter(item=item).count() == 1


def _attempt_cross_actor_working_commit(
    *,
    item: ProgrammeItem,
    item_actor: Account,
    receipt_actor: Account,
) -> None:
    now = timezone.now()
    revision_id = uuid4()
    reason = "Attempt a fully shaped command with split actor attribution."
    control_id = ProgrammeCommandReceipt.objects.get(
        item=item,
        operation="item_create",
    ).control_id

    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE public.programme_programmeitem
               SET aggregate_version = 2,
                   last_modified_by_id = %s,
                   updated_at = %s
             WHERE id = %s
            """,
            [item_actor.id, now, item.id],
        )
        cursor.execute(
            """
            INSERT INTO public.programme_programmeworkingrevision(
                id, created_at, updated_at, item_id, organization_id,
                edition_id, sequence, item_version, internal_title,
                working_summary, actor_id, reason, occurred_at
            ) VALUES (%s, %s, %s, %s, %s, %s, 2, 2, %s, %s, %s, %s, %s)
            """,
            [
                revision_id,
                now,
                now,
                item.id,
                item.organization_id,
                item.edition_id,
                "Cross-actor working title",
                "This candidate must roll back in full.",
                receipt_actor.id,
                reason,
                now,
            ],
        )
        cursor.execute(
            """
            INSERT INTO public.programme_programmecommandreceipt(
                id, created_at, updated_at, control_id, item_id,
                organization_id, edition_id, operation, actor_id, reason,
                idempotency_key, request_digest, correlation_id,
                source_channel, result_object_id, expected_version,
                resulting_control_version, resulting_item_version
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, 'working_revise', %s, %s,
                %s, %s, %s, 'service', %s, 1, NULL, 2
            )
            """,
            [
                uuid4(),
                now,
                now,
                control_id,
                item.id,
                item.organization_id,
                item.edition_id,
                receipt_actor.id,
                reason,
                uuid4(),
                "a" * 64,
                uuid4(),
                revision_id,
            ],
        )


def test_cross_actor_raw_commit_is_rejected_atomically() -> None:
    """Bind the item modifier, child author, and receipt actor together."""
    item_actor = AccountFactory()
    receipt_actor = AccountFactory()
    item = _create_item(actor=item_actor, edition=EventEditionFactory())

    with pytest.raises(
        DatabaseError,
        match="item mutation receipt does not match optimistic state",
    ):
        _attempt_cross_actor_working_commit(
            item=item,
            item_actor=item_actor,
            receipt_actor=receipt_actor,
        )

    item.refresh_from_db()
    assert item.aggregate_version == 1
    assert item.last_modified_by_id == item_actor.id
    assert ProgrammeWorkingRevision.objects.filter(item=item).count() == 1
    assert ProgrammeCommandReceipt.objects.filter(item=item).count() == 1
