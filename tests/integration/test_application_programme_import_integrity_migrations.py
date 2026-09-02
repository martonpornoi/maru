"""Database-enforced integrity attacks for Programme import adoption evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from maru.applications.models import (
    ProgrammeCall,
    ProgrammeCommandReceipt,
    ProgrammeImportAppliedCommand,
    ProgrammeImportBatch,
    ProgrammeImportBatchState,
    ProgrammeImportCommandAction,
    ProgrammeImportCommandReceipt,
    ProgrammeImportItem,
    ProgrammeImportItemKind,
    ProgrammeImportItemState,
    ProgrammeImportSourceBinding,
)
from maru.applications.programme_commands import (
    activate_programme_call,
    create_programme_call,
)
from maru.applications.programme_import_commands import (
    commit_programme_import_call,
    preview_programme_import,
    stage_programme_import,
)
from maru.applications.programme_import_inputs import (
    ProgrammeImportCallItemInput,
    parse_programme_import_document,
)
from maru.applications.programme_import_retention import (
    ProgrammeImportRetentionDecision,
)
from maru.applications.programme_import_writer_boundary import (
    programme_import_database_writer,
)
from maru.authorization.policy import PolicyDecision
from tests.factories import AccountFactory, EventEditionFactory
from tests.workforce_helpers import create_department_for_test

if TYPE_CHECKING:
    from maru.events.models import EventEdition
    from maru.identity.models import Account
    from maru.workforce.models import Department

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]

_IMPORT_REASON = "Adopt the reviewed import with exact nested evidence."


class _AllowAuthorizer:
    """Return complete policy decisions for the isolated dormant test seam."""

    def authorize_department(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        department_id: UUID,
        capability_code: str,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        del (
            principal_id,
            organization_id,
            edition_id,
            department_id,
            capability_code,
        )
        return self._decision(requested_fields)

    def authorize_edition(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        capability_code: str,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        del principal_id, organization_id, edition_id, capability_code
        return self._decision(requested_fields)

    def authorize_self(
        self,
        *,
        principal_id: UUID,
        owner_account_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        capability_code: str,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        del (
            principal_id,
            owner_account_id,
            organization_id,
            edition_id,
            capability_code,
        )
        return self._decision(requested_fields)

    def authorize_retry(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
    ) -> PolicyDecision:
        del principal_id, organization_id, edition_id
        return self._decision(frozenset())

    @staticmethod
    def _decision(requested_fields: frozenset[str] | None) -> PolicyDecision:
        return PolicyDecision(
            allowed=True,
            fields=requested_fields or frozenset(),
            obligations=frozenset({"audit"}),
            reason_code="programme_import_integrity_test",
        )


@dataclass(frozen=True, slots=True)
class _RetentionProvider:
    """Resolve a deterministic bounded staging lifetime for test imports."""

    lifetime: timedelta = timedelta(days=1)

    def resolve(self, *, staged_at: datetime) -> ProgrammeImportRetentionDecision:
        return ProgrammeImportRetentionDecision(
            policy_code="applications.programme-import-staging.test-v1",
            expires_at=staged_at + self.lifetime,
        )


@dataclass(frozen=True, slots=True)
class _CallPreview:
    """Retain the exact staged call preview used by one integrity attack."""

    edition: EventEdition
    manager: Account
    department: Department
    now: datetime
    item_id: UUID
    preview_result_id: UUID


@dataclass(frozen=True, slots=True)
class _CommittedCall:
    """Retain the applied call and its outer import evidence."""

    preview: _CallPreview
    call: ProgrammeCall
    binding: ProgrammeImportSourceBinding
    receipt: ProgrammeImportCommandReceipt


_AUTHORIZER = _AllowAuthorizer()


@pytest.fixture(autouse=True)
def _admit_dormant_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    """Admit only otherwise-dormant event publication in these tests."""

    monkeypatch.setattr(
        "maru.effects.services.require_effect_delivery_allowed",
        lambda **_kwargs: None,
    )


def _instant(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _call_document(now: datetime) -> bytes:
    document = {
        "schema": "applications.programme_import",
        "version": 1,
        "items": [
            {
                "kind": "call",
                "source_key": "programme-integrity-call",
                "definition": {
                    "code": "programme-integrity-call",
                    "name": "Programme integrity call",
                    "description": "Collect one integrity-test proposal.",
                    "purpose": "Exercise retained import evidence.",
                    "classification": "C2",
                    "maximum_submissions_per_person": 2,
                    "opens_at": _instant(now - timedelta(days=1)),
                    "applicant_edit_until": _instant(now + timedelta(days=6)),
                    "closes_at": _instant(now + timedelta(days=7)),
                    "audience_policy_code": None,
                    "retention_policy_code": None,
                    "sections": [
                        {
                            "key": "proposal",
                            "title": "Proposal",
                            "help_text": "Describe the proposed session.",
                            "questions": [
                                {
                                    "key": "title",
                                    "field_type": "short_text",
                                    "label": "Session title",
                                    "help_text": "Use the public title.",
                                    "required": True,
                                    "purpose": "Identify the session.",
                                    "classification": "C2",
                                    "retention_policy_code": None,
                                    "condition": None,
                                    "constraints": {
                                        "minimum_length": 3,
                                        "maximum_length": 160,
                                    },
                                }
                            ],
                        }
                    ],
                },
                "configuration": {
                    "maximum_collaborators": 2,
                    "content_policy_code": "applications.programme.content.v1",
                    "contributor_consent_policy_code": (
                        "applications.programme.import-consent.v1"
                    ),
                    "collaboration_retention_policy_code": (
                        "applications.programme.collaboration-retention.v1"
                    ),
                    "tracks": [
                        {
                            "code": "community",
                            "label": "Community",
                            "description": "Community-created sessions.",
                        }
                    ],
                    "formats": [
                        {
                            "code": "talk",
                            "label": "Talk",
                            "description": "One scheduled presentation.",
                            "minimum_duration_minutes": 30,
                            "default_duration_minutes": 45,
                            "maximum_duration_minutes": 60,
                        }
                    ],
                    "contributor_fields": [
                        {
                            "field_code": "public_name",
                            "lead_requirement": "required",
                            "collaborator_requirement": "optional",
                        }
                    ],
                },
            }
        ],
    }
    return json.dumps(document, separators=(",", ":")).encode()


def _prepare_call_preview() -> _CallPreview:
    edition = EventEditionFactory()
    manager = AccountFactory(display_name="Programme integrity manager")
    department = create_department_for_test(
        edition=edition,
        name="Programme",
        expected_code="programme",
    )
    now = timezone.now()
    staged = stage_programme_import(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        owner_department_id=department.id,
        source_system="legacy.programme.integrity",
        raw_payload=_call_document(now),
        expected_version=0,
        reason="Stage one call for a database-integrity attack.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_AUTHORIZER,
        retention_policy_provider=_RetentionProvider(),
    )
    preview = preview_programme_import(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        batch_id=staged.batch_id,
        expected_batch_version=1,
        reason="Preview the exact call before the integrity attack.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_AUTHORIZER,
    )
    assert len(preview.items) == 1
    item = preview.items[0]
    return _CallPreview(
        edition=edition,
        manager=manager,
        department=department,
        now=now,
        item_id=item.item_id,
        preview_result_id=item.result_id,
    )


def _commit_call(
    preview: _CallPreview,
    *,
    correlation_id: UUID,
) -> _CommittedCall:
    result = commit_programme_import_call(
        actor_id=preview.manager.id,
        organization_id=preview.edition.organization_id,
        edition_id=preview.edition.id,
        item_id=preview.item_id,
        preview_item_result_id=preview.preview_result_id,
        expected_version=1,
        reason=_IMPORT_REASON,
        retry_key=uuid4(),
        correlation_id=correlation_id,
        source_channel="test",
        now=preview.now,
        authorizer=_AUTHORIZER,
        programme_authorizer=_AUTHORIZER,
    )
    binding = ProgrammeImportSourceBinding.objects.select_related("call").get(
        item_id=result.item_id
    )
    assert binding.call is not None
    return _CommittedCall(
        preview=preview,
        call=binding.call,
        binding=binding,
        receipt=ProgrammeImportCommandReceipt.objects.get(id=result.receipt_id),
    )


@pytest.mark.parametrize("forged_dimension", ["actor", "reason"])
def test_raw_applied_link_rejects_forged_nested_attribution(
    forged_dimension: str,
) -> None:
    """Reject nested evidence whose actor or reason differs from the import."""

    preview = _prepare_call_preview()
    correlation_id = uuid4()
    committed = _commit_call(preview, correlation_id=correlation_id)
    nested_actor = (
        AccountFactory(display_name="Forged Programme actor")
        if forged_dimension == "actor"
        else preview.manager
    )
    nested_reason = (
        "Use a different reason than the retained import command."
        if forged_dimension == "reason"
        else _IMPORT_REASON
    )
    activation = activate_programme_call(
        actor_id=nested_actor.id,
        organization_id=preview.edition.organization_id,
        edition_id=preview.edition.id,
        call_id=committed.call.id,
        owner_department_id=preview.department.id,
        expected_version=1,
        reason=nested_reason,
        retry_key=uuid4(),
        correlation_id=correlation_id,
        source_channel="test",
        now=preview.now,
        authorizer=_AUTHORIZER,
    )
    nested_receipt = ProgrammeCommandReceipt.objects.get(id=activation.receipt_id)

    with (
        transaction.atomic(),
        programme_import_database_writer(),
        pytest.raises(
            DatabaseError,
            match=("nested command scope, actor, correlation, or version mismatch"),
        ),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            INSERT INTO public.applications_programmeimportappliedcommand (
                id, organization_id, edition_id, binding_id,
                import_receipt_id, sequence, programme_receipt_id,
                created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                uuid4(),
                preview.edition.organization_id,
                preview.edition.id,
                committed.binding.id,
                committed.receipt.id,
                2,
                nested_receipt.id,
                preview.now,
                preview.now,
            ],
        )

    assert (
        ProgrammeImportAppliedCommand.objects.filter(
            import_receipt=committed.receipt
        ).count()
        == 1
    )


def _force_truncated_call_commit(preview: _CallPreview) -> None:
    with transaction.atomic():
        with patch.object(
            ProgrammeImportAppliedCommand.objects,
            "create",
            return_value=None,
        ):
            result = commit_programme_import_call(
                actor_id=preview.manager.id,
                organization_id=preview.edition.organization_id,
                edition_id=preview.edition.id,
                item_id=preview.item_id,
                preview_item_result_id=preview.preview_result_id,
                expected_version=1,
                reason=_IMPORT_REASON,
                retry_key=uuid4(),
                correlation_id=uuid4(),
                source_channel="test",
                now=preview.now,
                authorizer=_AUTHORIZER,
                programme_authorizer=_AUTHORIZER,
            )
        assert not ProgrammeImportAppliedCommand.objects.filter(
            import_receipt_id=result.receipt_id
        ).exists()
        with connection.cursor() as cursor:
            cursor.execute(
                "SET CONSTRAINTS applications_prg_imp_receipt_contract IMMEDIATE"
            )


def test_deferred_contract_rejects_truncated_nested_chain_at_commit() -> None:
    """Reject an applied import when its only nested receipt link is omitted."""

    preview = _prepare_call_preview()
    with pytest.raises(
        DatabaseError,
        match="nested command evidence is missing or non-contiguous",
    ):
        _force_truncated_call_commit(preview)

    item = ProgrammeImportItem.objects.get(id=preview.item_id)
    assert item.state == ProgrammeImportItemState.STAGED
    assert item.canonical_payload is not None
    assert not ProgrammeImportSourceBinding.objects.filter(item=item).exists()
    assert not ProgrammeImportCommandReceipt.objects.filter(
        item=item,
        action=ProgrammeImportCommandAction.CALL_COMMITTED,
    ).exists()
    assert not ProgrammeCall.objects.filter(edition=preview.edition).exists()


def _force_unreceipted_item_discard(preview: _CallPreview) -> None:
    with (
        transaction.atomic(),
        programme_import_database_writer(),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        item = ProgrammeImportItem.objects.select_for_update().get(
            id=preview.item_id,
        )
        item.state = ProgrammeImportItemState.DISCARDED
        item.aggregate_version = 2
        item.canonical_payload = None
        item.save(
            update_fields=(
                "state",
                "aggregate_version",
                "canonical_payload",
                "updated_at",
            )
        )
        cursor.execute("SET CONSTRAINTS applications_prg_imp_item_contract IMMEDIATE")


def test_deferred_contract_rejects_unreceipted_item_only_discard() -> None:
    """Reject a scrubbed item unless its complete batch disposal is receipted."""

    preview = _prepare_call_preview()

    with pytest.raises(
        DatabaseError,
        match="Discarded Programme-import items require batch receipt evidence",
    ):
        _force_unreceipted_item_discard(preview)

    item = ProgrammeImportItem.objects.get(id=preview.item_id)
    assert item.state == ProgrammeImportItemState.STAGED
    assert item.aggregate_version == 1
    assert item.canonical_payload is not None


def _force_item_apply_after_batch_discard(preview: _CallPreview) -> None:
    with (
        transaction.atomic(),
        programme_import_database_writer(),
        transaction.atomic(),
    ):
        batch = ProgrammeImportBatch.objects.select_for_update().get(
            items__id=preview.item_id,
        )
        batch.state = ProgrammeImportBatchState.DISCARDED
        batch.aggregate_version = 2
        batch.discarded_by = preview.manager
        batch.discarded_at = preview.now
        batch.discard_reason = "Dispose before attempting a forged adoption."
        batch.save(
            update_fields=(
                "state",
                "aggregate_version",
                "discarded_by",
                "discarded_at",
                "discard_reason",
                "updated_at",
            )
        )
        item = ProgrammeImportItem.objects.select_for_update().get(
            id=preview.item_id,
        )
        item.state = ProgrammeImportItemState.APPLIED
        item.aggregate_version = 2
        item.canonical_payload = None
        item.save(
            update_fields=(
                "state",
                "aggregate_version",
                "canonical_payload",
                "updated_at",
            )
        )


def test_item_apply_is_rejected_after_parent_batch_is_discarded() -> None:
    """A disposed batch can never resume adoption through a raw item write."""

    preview = _prepare_call_preview()

    with pytest.raises(DatabaseError, match="exact terminal scrub"):
        _force_item_apply_after_batch_discard(preview)

    batch = ProgrammeImportBatch.objects.get(items__id=preview.item_id)
    item = ProgrammeImportItem.objects.get(id=preview.item_id)
    assert batch.state == ProgrammeImportBatchState.STAGED
    assert item.state == ProgrammeImportItemState.STAGED
    assert item.canonical_payload is not None


def _force_call_binding_to_other_department(
    *,
    preview: _CallPreview,
    other_call: ProgrammeCall,
) -> None:
    with (
        transaction.atomic(),
        programme_import_database_writer(),
        transaction.atomic(),
    ):
        item = ProgrammeImportItem.objects.select_for_update().get(
            id=preview.item_id,
        )
        item.state = ProgrammeImportItemState.APPLIED
        item.aggregate_version = 2
        item.canonical_payload = None
        item.save(
            update_fields=(
                "state",
                "aggregate_version",
                "canonical_payload",
                "updated_at",
            )
        )
        ProgrammeImportSourceBinding.objects.create(
            organization_id=preview.edition.organization_id,
            edition_id=preview.edition.id,
            source_system=item.batch.source_system,
            kind=ProgrammeImportItemKind.CALL,
            source_key=item.source_key,
            source_digest=item.source_digest,
            item=item,
            call=other_call,
            proposal=None,
            created_by=preview.manager,
        )


def test_database_rejects_imported_call_owned_by_other_department() -> None:
    """A call binding must target the exact Department that owned staging."""

    preview = _prepare_call_preview()
    other_department = create_department_for_test(
        edition=preview.edition,
        name="Alternate Programme",
        expected_code="alternate-programme",
    )
    parsed = parse_programme_import_document(_call_document(preview.now)).items[0]
    assert isinstance(parsed, ProgrammeImportCallItemInput)
    created = create_programme_call(
        actor_id=preview.manager.id,
        organization_id=preview.edition.organization_id,
        edition_id=preview.edition.id,
        definition_input=parsed.definition_input,
        configuration=parsed.configuration_for_owner_department(
            other_department.id,
        ),
        expected_version=0,
        reason="Create a same-edition call under another Department.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=preview.now,
        authorizer=_AUTHORIZER,
    )
    other_call = ProgrammeCall.objects.get(id=created.target_id)

    with pytest.raises(DatabaseError, match="call binding owner mismatch"):
        _force_call_binding_to_other_department(
            preview=preview,
            other_call=other_call,
        )

    item = ProgrammeImportItem.objects.get(id=preview.item_id)
    assert item.state == ProgrammeImportItemState.STAGED
    assert item.canonical_payload is not None
    assert not ProgrammeImportSourceBinding.objects.filter(item=item).exists()
