"""End-to-end acceptance for preview-first Programme import staging."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from threading import Barrier, Event
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from django.db import DatabaseError, close_old_connections, connections, transaction
from django.db.models import F
from django.utils import timezone

from maru.applications import programme_import_commands
from maru.applications.models import (
    ApplicationQuestion,
    ApplicationSubmission,
    ProgrammeCall,
    ProgrammeCommandAction,
    ProgrammeCommandReceipt,
    ProgrammeImportAppliedCommand,
    ProgrammeImportBatch,
    ProgrammeImportBatchState,
    ProgrammeImportCommandAction,
    ProgrammeImportCommandReceipt,
    ProgrammeImportItem,
    ProgrammeImportItemKind,
    ProgrammeImportItemState,
    ProgrammeImportPreviewAction,
    ProgrammeImportPreviewStatus,
    ProgrammeImportSourceBinding,
    ProgrammeProposal,
)
from maru.applications.programme_commands import (
    activate_programme_call,
    append_programme_proposal_answer,
    create_programme_call,
    reassign_programme_call,
)
from maru.applications.programme_import_commands import (
    ApplicationsProgrammeImportClaimUnavailableError,
    ApplicationsProgrammeImportIdempotencyConflictError,
    ApplicationsProgrammeImportOperationFailedError,
    ApplicationsProgrammeImportPreviewStaleError,
    ApplicationsProgrammeImportStateConflictError,
    ApplicationsProgrammeImportUnavailableError,
    claim_programme_import_proposal,
    commit_programme_import_call,
    discard_programme_import,
    preview_programme_import,
    preview_programme_import_proposal_claim,
    reassign_programme_import_batch,
    stage_programme_import,
)
from maru.applications.programme_import_inputs import (
    ProgrammeImportCallItemInput,
    ProgrammeImportInputError,
    parse_programme_import_document,
)
from maru.applications.programme_import_retention import (
    ProgrammeImportRetentionDecision,
)
from maru.applications.programme_import_writer_boundary import (
    programme_import_database_writer,
)
from maru.applications.programme_inputs import (
    ProgrammeProposalContributorProfileInput,
)
from maru.applications.retry_namespace import lock_applications_retry_namespace
from maru.audit.models import AuditEvent
from maru.authorization.policy import PolicyDecision
from maru.effects.models import DomainEvent, OutboxMessage
from maru.events.models import EventEdition
from tests.factories import AccountFactory, EventEditionFactory
from tests.workforce_helpers import (
    create_department_for_test,
)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]

_CONSENT_POLICY = "applications.programme.import-consent.v1"


@dataclass(frozen=True, slots=True)
class _AllowImportAuthorizer:
    """Return complete test decisions after production scope resolution."""

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
        if requested_fields:
            assert capability_code == "applications.view_programme_proposal_self"
        else:
            assert capability_code == "applications.edit_programme_proposal_self"
        del (
            principal_id,
            owner_account_id,
            organization_id,
            edition_id,
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
            reason_code="programme_import_service_test",
        )


@dataclass(frozen=True, slots=True)
class _AllowProgrammeAuthorizer:
    """Return complete test decisions for nested Programme commands."""

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
            reason_code="programme_nested_service_test",
        )


@dataclass(frozen=True, slots=True)
class _DenyImportTargetAuthorizer:
    """Allow retry preflight while denying target-scoped import authority."""

    denied_department_id: UUID | None = None

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
        if (
            self.denied_department_id is None
            or department_id == self.denied_department_id
        ):
            return self._denial()
        return _IMPORT_AUTHORIZER.authorize_department(
            principal_id=principal_id,
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=department_id,
            capability_code=capability_code,
            requested_fields=requested_fields,
        )

    def authorize_edition(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        capability_code: str,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        del (
            principal_id,
            organization_id,
            edition_id,
            capability_code,
            requested_fields,
        )
        return self._denial()

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
        return _IMPORT_AUTHORIZER.authorize_self(
            principal_id=principal_id,
            owner_account_id=owner_account_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=capability_code,
            requested_fields=requested_fields,
        )

    def authorize_retry(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
    ) -> PolicyDecision:
        return _IMPORT_AUTHORIZER.authorize_retry(
            principal_id=principal_id,
            organization_id=organization_id,
            edition_id=edition_id,
        )

    @staticmethod
    def _denial() -> PolicyDecision:
        return PolicyDecision(
            allowed=False,
            fields=frozenset(),
            obligations=frozenset(),
            reason_code="synthetic_target_denial",
        )


@dataclass(slots=True)
class _RevokeClaimDisclosureAuthorizer:
    """Withdraw claim-field disclosure during the locked authority recheck."""

    view_calls: int = 0

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
        return _IMPORT_AUTHORIZER.authorize_department(
            principal_id=principal_id,
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=department_id,
            capability_code=capability_code,
            requested_fields=requested_fields,
        )

    def authorize_edition(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        capability_code: str,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        return _IMPORT_AUTHORIZER.authorize_edition(
            principal_id=principal_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=capability_code,
            requested_fields=requested_fields,
        )

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
        if capability_code == "applications.view_programme_proposal_self":
            self.view_calls += 1
            if self.view_calls == 2:
                return PolicyDecision(
                    allowed=True,
                    fields=frozenset(),
                    obligations=frozenset({"audit"}),
                    reason_code="synthetic_claim_disclosure_revoked",
                )
        return _IMPORT_AUTHORIZER.authorize_self(
            principal_id=principal_id,
            owner_account_id=owner_account_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=capability_code,
            requested_fields=requested_fields,
        )

    def authorize_retry(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
    ) -> PolicyDecision:
        return _IMPORT_AUTHORIZER.authorize_retry(
            principal_id=principal_id,
            organization_id=organization_id,
            edition_id=edition_id,
        )


@dataclass(slots=True)
class _DenyFirstAnswerProgrammeAuthorizer:
    """Deny the first answer only after observing the nested start write."""

    retry_calls: int = 0
    saw_started_proposal: bool = False

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
        return _PROGRAMME_AUTHORIZER.authorize_department(
            principal_id=principal_id,
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=department_id,
            capability_code=capability_code,
            requested_fields=requested_fields,
        )

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
        return _PROGRAMME_AUTHORIZER.authorize_self(
            principal_id=principal_id,
            owner_account_id=owner_account_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=capability_code,
            requested_fields=requested_fields,
        )

    def authorize_retry(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
    ) -> PolicyDecision:
        self.retry_calls += 1
        if self.retry_calls == 2:
            self.saw_started_proposal = (
                ProgrammeProposal.objects.filter(edition_id=edition_id).exists()
                and ProgrammeCommandReceipt.objects.filter(
                    edition_id=edition_id,
                    action="proposal_started",
                ).exists()
            )
            return PolicyDecision(
                allowed=False,
                fields=frozenset(),
                obligations=frozenset(),
                reason_code="synthetic_first_answer_denied",
            )
        return _PROGRAMME_AUTHORIZER.authorize_retry(
            principal_id=principal_id,
            organization_id=organization_id,
            edition_id=edition_id,
        )


@dataclass(frozen=True, slots=True)
class _RetentionProvider:
    """Derive a bounded test expiry without changing deployment settings."""

    lifetime: timedelta = timedelta(days=1)

    def resolve(self, *, staged_at: datetime) -> ProgrammeImportRetentionDecision:
        return ProgrammeImportRetentionDecision(
            policy_code="applications.programme-import-staging.test-v1",
            expires_at=staged_at + self.lifetime,
        )


_IMPORT_AUTHORIZER = _AllowImportAuthorizer()
_PROGRAMME_AUTHORIZER = _AllowProgrammeAuthorizer()


@pytest.fixture(autouse=True)
def _admit_dormant_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    """Admit only otherwise-dormant event publication in service tests."""

    monkeypatch.setattr(
        "maru.effects.services.require_effect_delivery_allowed",
        lambda **_kwargs: None,
    )


def _instant(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _call_item(
    now: datetime,
    *,
    name: str = "Programme proposals",
) -> dict[str, object]:
    return {
        "kind": "call",
        "source_key": "programme-call-2027",
        "definition": {
            "code": "programme-call-2027",
            "name": name,
            "description": "Submit a session for the on-site Programme.",
            "purpose": "Collect proposals for Programme review.",
            "classification": "C2",
            "maximum_submissions_per_person": 4,
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
                            "help_text": "Use the public session title.",
                            "required": True,
                            "purpose": "Identify the proposed session.",
                            "classification": "C2",
                            "retention_policy_code": None,
                            "condition": None,
                            "constraints": {
                                "minimum_length": 3,
                                "maximum_length": 160,
                            },
                        },
                        {
                            "key": "estimated-attendance",
                            "field_type": "decimal",
                            "label": "Estimated attendance",
                            "help_text": "A planning estimate.",
                            "required": False,
                            "purpose": "Support room planning after claim.",
                            "classification": "C1",
                            "retention_policy_code": None,
                            "condition": None,
                            "constraints": {
                                "minimum_value": "0",
                                "maximum_value": "10000",
                            },
                        },
                    ],
                }
            ],
        },
        "configuration": {
            "maximum_collaborators": 4,
            "content_policy_code": "applications.programme.content.v1",
            "contributor_consent_policy_code": _CONSENT_POLICY,
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


def _proposal_item(*, lead_email: str) -> dict[str, object]:
    return {
        "kind": "proposal",
        "source_key": "proposal-42",
        "call_source_key": "programme-call-2027",
        "lead_email": lead_email,
        "selection": {
            "track_code": "community",
            "format_code": "talk",
            "requested_duration_minutes": 45,
        },
        "answers": [
            {
                "question_key": "title",
                "field_type": "short_text",
                "value": "Community meetup",
            },
            {
                "question_key": "estimated-attendance",
                "field_type": "decimal",
                "value": "1",
            },
        ],
    }


def _document(items: list[dict[str, object]]) -> bytes:
    return json.dumps(
        {
            "schema": "applications.programme_import",
            "version": 1,
            "items": items,
        },
        separators=(",", ":"),
    ).encode()


def _profile() -> ProgrammeProposalContributorProfileInput:
    return ProgrammeProposalContributorProfileInput(
        public_name="Imported presenter",
        biography="",
        pronouns="",
        website="",
        proposed_for_publication=True,
        consent_acknowledged=True,
        consent_policy_code=_CONSENT_POLICY,
    )


def _nested_retry_key(
    *,
    outer_retry_key: UUID,
    item_id: UUID,
    sequence: int,
    action: str,
) -> UUID:
    namespace = ":".join(
        (
            "maru:applications:programme-import:nested:v1",
            str(outer_retry_key).lower(),
            str(item_id).lower(),
            str(sequence),
            action,
        )
    )
    return UUID(
        hashlib.md5(namespace.encode("ascii"), usedforsecurity=False).hexdigest()
    )


def _nested_call_retry_key(*, outer_retry_key: UUID, item_id: UUID) -> UUID:
    return _nested_retry_key(
        outer_retry_key=outer_retry_key,
        item_id=item_id,
        sequence=1,
        action=ProgrammeCommandAction.CALL_CREATED,
    )


def _stage(
    *,
    actor: object,
    edition: object,
    department_id: UUID,
    payload: bytes,
    now: datetime,
    retention: _RetentionProvider | None = None,
) -> UUID:
    result = stage_programme_import(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        owner_department_id=department_id,
        source_system="legacy.programme",
        raw_payload=payload,
        expected_version=0,
        reason="Stage reviewed legacy Programme data.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
        retention_policy_provider=retention or _RetentionProvider(),
    )
    return result.batch_id


def _create_active_direct_call(
    *,
    edition: object,
    manager: object,
    department_id: UUID,
    now: datetime,
    code: str,
) -> ProgrammeCall:
    call_item = deepcopy(_call_item(now, name="Alternate Programme call"))
    call_item["source_key"] = code
    definition = call_item["definition"]
    assert isinstance(definition, dict)
    definition["code"] = code
    parsed = parse_programme_import_document(_document([call_item])).items[0]
    assert isinstance(parsed, ProgrammeImportCallItemInput)
    created = create_programme_call(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        definition_input=parsed.definition_input,
        configuration=parsed.configuration_for_owner_department(department_id),
        expected_version=0,
        reason="Create an alternate call for an import-integrity regression.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_PROGRAMME_AUTHORIZER,
    )
    call = ProgrammeCall.objects.get(id=created.target_id)
    activate_programme_call(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        call_id=call.id,
        owner_department_id=department_id,
        expected_version=1,
        reason="Activate the alternate integrity-test call.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_PROGRAMME_AUTHORIZER,
    )
    return ProgrammeCall.objects.select_related("definition").get(id=call.id)


def _scope_row_counts(*, edition_id: UUID) -> dict[str, int]:
    return {
        "submissions": ApplicationSubmission.objects.filter(
            edition_id=edition_id
        ).count(),
        "calls": ProgrammeCall.objects.filter(edition_id=edition_id).count(),
        "proposals": ProgrammeProposal.objects.filter(edition_id=edition_id).count(),
        "bindings": ProgrammeImportSourceBinding.objects.filter(
            edition_id=edition_id
        ).count(),
        "applied_commands": ProgrammeImportAppliedCommand.objects.filter(
            edition_id=edition_id
        ).count(),
        "programme_receipts": ProgrammeCommandReceipt.objects.filter(
            edition_id=edition_id
        ).count(),
        "import_receipts": ProgrammeImportCommandReceipt.objects.filter(
            edition_id=edition_id
        ).count(),
        "audits": AuditEvent.objects.filter(event_edition_id=edition_id).count(),
        "events": DomainEvent.objects.filter(event_edition_id=edition_id).count(),
        "outbox": OutboxMessage.objects.filter(
            event__event_edition_id=edition_id
        ).count(),
    }


def _prepare_claimable_import(
    *,
    edition: object,
    manager: object,
    lead: object,
    department_id: UUID,
    now: datetime,
) -> tuple[UUID, UUID, str]:
    batch_id = _stage(
        actor=manager,
        edition=edition,
        department_id=department_id,
        payload=_document([_proposal_item(lead_email=lead.email), _call_item(now)]),
        now=now,
    )
    preview = preview_programme_import(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        batch_id=batch_id,
        expected_batch_version=1,
        reason="Review the staged Programme items before a rollback test.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
    )
    by_kind = {item.kind: item for item in preview.items}
    call_preview = by_kind[ProgrammeImportItemKind.CALL]
    committed = commit_programme_import_call(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=call_preview.item_id,
        preview_item_result_id=call_preview.result_id,
        expected_version=1,
        reason="Adopt the call dependency for a proposal rollback test.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
        programme_authorizer=_PROGRAMME_AUTHORIZER,
    )
    call_binding = ProgrammeImportSourceBinding.objects.get(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=committed.item_id,
        call__isnull=False,
    )
    call = ProgrammeCall.objects.get(id=call_binding.call_id)
    activate_programme_call(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        call_id=call.id,
        owner_department_id=department_id,
        expected_version=1,
        reason="Activate the imported call for a proposal rollback test.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_PROGRAMME_AUTHORIZER,
    )
    refreshed = preview_programme_import(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        batch_id=batch_id,
        expected_batch_version=1,
        reason="Refresh the proposal dependency before the rollback test.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
    )
    proposal_preview = next(
        item
        for item in refreshed.items
        if item.kind == ProgrammeImportItemKind.PROPOSAL
    )
    claim_preview_correlation_id = uuid4()
    private_preview = preview_programme_import_proposal_claim(
        actor_id=lead.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=proposal_preview.item_id,
        correlation_id=claim_preview_correlation_id,
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
    )
    return batch_id, proposal_preview.item_id, private_preview.adoption_digest


def test_call_then_proposal_import_is_previewed_claimed_and_scrubbed(  # noqa: PLR0915
) -> None:
    """Exercise the complete modular path without registration or payments."""

    edition = EventEditionFactory()
    manager = AccountFactory(display_name="Programme manager")
    lead = AccountFactory(
        display_name="Imported presenter",
        email="presenter@example.test",
    )
    department = create_department_for_test(
        edition=edition,
        name="Programme",
        expected_code="programme",
    )
    now = timezone.now()
    call_item = _call_item(now)
    batch_id = _stage(
        actor=manager,
        edition=edition,
        department_id=department.id,
        payload=_document([_proposal_item(lead_email=lead.email), call_item]),
        now=now,
    )

    first_preview = preview_programme_import(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        batch_id=batch_id,
        expected_batch_version=1,
        reason="Review every staged Programme item before adoption.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
    )
    by_kind = {item.kind: item for item in first_preview.items}
    call_preview = by_kind[ProgrammeImportItemKind.CALL]
    assert call_preview.status == ProgrammeImportPreviewStatus.READY
    assert call_preview.action == ProgrammeImportPreviewAction.COMMIT_CALL
    assert by_kind[ProgrammeImportItemKind.PROPOSAL].status == (
        ProgrammeImportPreviewStatus.BLOCKED
    )

    committed = commit_programme_import_call(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=call_preview.item_id,
        preview_item_result_id=call_preview.result_id,
        expected_version=1,
        reason="Adopt the reviewed Programme call as a Draft.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
        programme_authorizer=_PROGRAMME_AUTHORIZER,
    )
    assert not hasattr(committed, "source_binding_id")
    assert (
        ProgrammeImportCommandReceipt.objects.get(
            id=committed.receipt_id,
        ).applied_command_count
        == 1
    )
    call_binding = ProgrammeImportSourceBinding.objects.get(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=committed.item_id,
        call__isnull=False,
    )
    call = ProgrammeCall.objects.get(id=call_binding.call_id)
    assert call.definition.status == "draft"
    assert (
        ProgrammeImportItem.objects.get(id=call_preview.item_id).canonical_payload
        is None
    )

    activate_programme_call(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        call_id=call.id,
        owner_department_id=department.id,
        expected_version=1,
        reason="Activate the reviewed imported call for claims.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_PROGRAMME_AUTHORIZER,
    )
    second_preview = preview_programme_import(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        batch_id=batch_id,
        expected_batch_version=1,
        reason="Refresh dependencies after activating the imported call.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
    )
    second_by_kind = {item.kind: item for item in second_preview.items}
    assert second_by_kind[ProgrammeImportItemKind.CALL].status == (
        ProgrammeImportPreviewStatus.NO_OP
    )
    proposal_preview = second_by_kind[ProgrammeImportItemKind.PROPOSAL]
    assert proposal_preview.status == ProgrammeImportPreviewStatus.READY
    assert proposal_preview.action == ProgrammeImportPreviewAction.CLAIM_PROPOSAL

    claim_preview_correlation_id = uuid4()
    private_preview = preview_programme_import_proposal_claim(
        actor_id=lead.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=proposal_preview.item_id,
        correlation_id=claim_preview_correlation_id,
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
    )
    assert not hasattr(private_preview, "source_key")
    assert not hasattr(private_preview, "call_source_key")
    assert [answer.field_type for answer in private_preview.answers] == [
        "short_text",
        "decimal",
    ]
    assert [
        (answer.question_key, answer.value) for answer in private_preview.answers
    ] == [
        ("title", "Community meetup"),
        ("estimated-attendance", "1"),
    ]
    with pytest.raises(ApplicationsProgrammeImportClaimUnavailableError):
        claim_programme_import_proposal(
            actor_id=lead.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            item_id=proposal_preview.item_id,
            lead_profile=_profile(),
            adopted_preview_digest="0" * 64,
            expected_version=1,
            reason="Reject a claim that does not adopt the fresh preview.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            now=now,
            authorizer=_IMPORT_AUTHORIZER,
            programme_authorizer=_PROGRAMME_AUTHORIZER,
        )
    assert not ProgrammeProposal.objects.filter(edition_id=edition.id).exists()

    claimed = claim_programme_import_proposal(
        actor_id=lead.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=proposal_preview.item_id,
        lead_profile=_profile(),
        adopted_preview_digest=private_preview.adoption_digest,
        expected_version=1,
        reason="Claim the imported proposal with current profile and consent.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
        programme_authorizer=_PROGRAMME_AUTHORIZER,
    )
    assert not hasattr(claimed, "source_binding_id")
    assert (
        ProgrammeImportCommandReceipt.objects.get(
            id=claimed.receipt_id,
        ).applied_command_count
        == 3
    )
    proposal_binding = ProgrammeImportSourceBinding.objects.get(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=claimed.item_id,
        proposal__isnull=False,
    )
    proposal = ProgrammeProposal.objects.select_related("submission").get(
        id=proposal_binding.proposal_id
    )
    assert proposal.submission.account_id == lead.id
    assert proposal.submission.aggregate_version == 3
    assert list(
        ProgrammeImportAppliedCommand.objects.filter(
            binding=proposal_binding
        ).values_list("sequence", flat=True)
    ) == [1, 2, 3]
    proposal_item = ProgrammeImportItem.objects.get(id=proposal_preview.item_id)
    assert proposal_item.state == ProgrammeImportItemState.APPLIED
    assert proposal_item.canonical_payload is None

    duplicate_batch_id = _stage(
        actor=manager,
        edition=edition,
        department_id=department.id,
        payload=_document([call_item]),
        now=now,
    )
    duplicate_preview = preview_programme_import(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        batch_id=duplicate_batch_id,
        expected_batch_version=1,
        reason="Confirm a same-digest source identity is a permanent no-op.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
    )
    assert duplicate_preview.items[0].status == ProgrammeImportPreviewStatus.NO_OP
    assert (
        ProgrammeImportItem.objects.get(id=duplicate_preview.items[0].item_id).state
        == ProgrammeImportItemState.STAGED
    )
    discard_programme_import(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        batch_id=duplicate_batch_id,
        expected_version=1,
        reason="Dispose the explicit duplicate after review.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
    )
    duplicate_batch = ProgrammeImportBatch.objects.get(id=duplicate_batch_id)
    assert duplicate_batch.state == ProgrammeImportBatchState.DISCARDED
    assert duplicate_batch.items.get().canonical_payload is None
    assert ProgrammeCall.objects.filter(id=call.id).exists()

    changed_batch_id = _stage(
        actor=manager,
        edition=edition,
        department_id=department.id,
        payload=_document([_call_item(now, name="Changed source value")]),
        now=now,
    )
    changed_preview = preview_programme_import(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        batch_id=changed_batch_id,
        expected_batch_version=1,
        reason="Detect changed content behind a permanent source identity.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
    )
    assert changed_preview.items[0].status == ProgrammeImportPreviewStatus.CONFLICT
    assert changed_preview.items[0].reason_codes == ("source_digest_conflict",)
    discard_programme_import(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        batch_id=changed_batch_id,
        expected_version=1,
        reason="Dispose changed source content after recording its conflict.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
    )

    import_events = DomainEvent.objects.filter(
        event_name="applications.programme_import.changed.v1"
    )
    assert import_events.count() == 11
    serialized_events = json.dumps(
        list(import_events.values_list("payload", flat=True)),
        sort_keys=True,
    )
    assert "presenter@example.test" not in serialized_events
    assert "Community meetup" not in serialized_events
    assert "Stage reviewed legacy Programme data" not in serialized_events
    claim_preview_audit = AuditEvent.objects.get(
        operation="applications.programme_import.query.proposal_claim_preview",
        principal_id=lead.id,
        correlation_id=claim_preview_correlation_id,
    )
    assert claim_preview_audit.source_channel == "test"
    assert claim_preview_audit.outcome == "allow"


def test_database_rejects_proposal_dependency_source_outside_batch_source() -> None:
    """A forged proposal dependency cannot cross the batch source namespace."""

    edition = EventEditionFactory()
    manager = AccountFactory(display_name="Programme manager")
    lead = AccountFactory(email="dependency-source@example.test")
    department = create_department_for_test(
        edition=edition,
        name="Programme",
        expected_code="programme",
    )
    now = timezone.now()
    original_create = ProgrammeImportItem.objects.create

    def create_with_forged_dependency(**kwargs: Any) -> ProgrammeImportItem:
        if kwargs.get("kind") == ProgrammeImportItemKind.PROPOSAL:
            kwargs["dependency_source_system"] = "alternate.programme"
        return original_create(**kwargs)

    with (
        patch.object(
            ProgrammeImportItem.objects,
            "create",
            side_effect=create_with_forged_dependency,
        ),
        pytest.raises(ApplicationsProgrammeImportOperationFailedError),
    ):
        _stage(
            actor=manager,
            edition=edition,
            department_id=department.id,
            payload=_document([_proposal_item(lead_email=lead.email), _call_item(now)]),
            now=now,
        )

    assert not ProgrammeImportBatch.objects.filter(edition=edition).exists()
    assert not ProgrammeImportItem.objects.filter(edition=edition).exists()


def test_database_rejects_proposal_target_for_wrong_source_dependency() -> None:
    """A claim cannot bind a proposal to a different same-edition call."""

    edition = EventEditionFactory()
    manager = AccountFactory(display_name="Programme manager")
    lead = AccountFactory(email="wrong-call@example.test")
    department = create_department_for_test(
        edition=edition,
        name="Programme",
        expected_code="programme",
    )
    now = timezone.now()
    _batch_id, item_id, _adoption_digest = _prepare_claimable_import(
        edition=edition,
        manager=manager,
        lead=lead,
        department_id=department.id,
        now=now,
    )
    alternate_call = _create_active_direct_call(
        edition=edition,
        manager=manager,
        department_id=department.id,
        now=now,
        code="alternate-import-dependency",
    )
    forged_dependency = SimpleNamespace(
        id=uuid4(),
        source_digest="f" * 64,
        call=alternate_call,
    )

    with patch.object(
        programme_import_commands,
        "_proposal_dependency_binding",
        return_value=forged_dependency,
    ):
        private_preview = preview_programme_import_proposal_claim(
            actor_id=lead.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            item_id=item_id,
            correlation_id=uuid4(),
            source_channel="test",
            now=now,
            authorizer=_IMPORT_AUTHORIZER,
        )
        with pytest.raises(ApplicationsProgrammeImportOperationFailedError):
            claim_programme_import_proposal(
                actor_id=lead.id,
                organization_id=edition.organization_id,
                edition_id=edition.id,
                item_id=item_id,
                lead_profile=_profile(),
                adopted_preview_digest=private_preview.adoption_digest,
                expected_version=1,
                reason="Attempt to bind through the wrong call dependency.",
                retry_key=uuid4(),
                correlation_id=uuid4(),
                source_channel="test",
                now=now,
                authorizer=_IMPORT_AUTHORIZER,
                programme_authorizer=_PROGRAMME_AUTHORIZER,
            )

    item = ProgrammeImportItem.objects.get(id=item_id)
    assert item.state == ProgrammeImportItemState.STAGED
    assert item.canonical_payload is not None
    assert not ProgrammeImportSourceBinding.objects.filter(item=item).exists()
    assert not ProgrammeProposal.objects.filter(edition=edition).exists()


def test_database_rejects_proposal_answer_chain_out_of_definition_order() -> None:
    """Nested answer receipts must follow the definition's stable question order."""

    edition = EventEditionFactory()
    manager = AccountFactory(display_name="Programme manager")
    lead = AccountFactory(email="answer-order@example.test")
    department = create_department_for_test(
        edition=edition,
        name="Programme",
        expected_code="programme",
    )
    now = timezone.now()
    _batch_id, item_id, _adoption_digest = _prepare_claimable_import(
        edition=edition,
        manager=manager,
        lead=lead,
        department_id=department.id,
        now=now,
    )
    original_resolver = programme_import_commands._resolve_proposal_mapping

    def reverse_resolved_answers(**kwargs: Any) -> object:
        resolved = original_resolver(**kwargs)
        return replace(resolved, answers=tuple(reversed(resolved.answers)))

    with patch.object(
        programme_import_commands,
        "_resolve_proposal_mapping",
        side_effect=reverse_resolved_answers,
    ):
        private_preview = preview_programme_import_proposal_claim(
            actor_id=lead.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            item_id=item_id,
            correlation_id=uuid4(),
            source_channel="test",
            now=now,
            authorizer=_IMPORT_AUTHORIZER,
        )
        with pytest.raises(ApplicationsProgrammeImportOperationFailedError):
            claim_programme_import_proposal(
                actor_id=lead.id,
                organization_id=edition.organization_id,
                edition_id=edition.id,
                item_id=item_id,
                lead_profile=_profile(),
                adopted_preview_digest=private_preview.adoption_digest,
                expected_version=1,
                reason="Attempt an out-of-order nested answer chain.",
                retry_key=uuid4(),
                correlation_id=uuid4(),
                source_channel="test",
                now=now,
                authorizer=_IMPORT_AUTHORIZER,
                programme_authorizer=_PROGRAMME_AUTHORIZER,
            )

    item = ProgrammeImportItem.objects.get(id=item_id)
    assert item.state == ProgrammeImportItemState.STAGED
    assert item.canonical_payload is not None
    assert not ProgrammeProposal.objects.filter(edition=edition).exists()


def test_applied_import_receipt_rejects_post_import_chain_extension() -> None:
    """Later legitimate proposal edits cannot be attached to an old import."""

    edition = EventEditionFactory()
    manager = AccountFactory(display_name="Programme manager")
    lead = AccountFactory(email="sealed-chain@example.test")
    department = create_department_for_test(
        edition=edition,
        name="Programme",
        expected_code="programme",
    )
    now = timezone.now()
    _batch_id, item_id, adoption_digest = _prepare_claimable_import(
        edition=edition,
        manager=manager,
        lead=lead,
        department_id=department.id,
        now=now,
    )
    claim_reason = "Claim the imported proposal before a later ordinary edit."
    claim_retry_key = uuid4()
    claim_correlation_id = uuid4()
    claimed = claim_programme_import_proposal(
        actor_id=lead.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item_id,
        lead_profile=_profile(),
        adopted_preview_digest=adoption_digest,
        expected_version=1,
        reason=claim_reason,
        retry_key=claim_retry_key,
        correlation_id=claim_correlation_id,
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
        programme_authorizer=_PROGRAMME_AUTHORIZER,
    )
    binding = ProgrammeImportSourceBinding.objects.select_related(
        "proposal__submission",
        "proposal__call__definition",
    ).get(item_id=claimed.item_id)
    assert binding.proposal is not None
    receipt = ProgrammeImportCommandReceipt.objects.get(id=claimed.receipt_id)
    assert receipt.applied_command_count == 3
    question = ApplicationQuestion.objects.get(
        section__definition=binding.proposal.call.definition,
        key="title",
    )
    later_edit = append_programme_proposal_answer(
        actor_id=lead.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        proposal_id=binding.proposal.id,
        question_id=question.id,
        value="A later legitimate title",
        expected_version=3,
        reason=claim_reason,
        retry_key=_nested_retry_key(
            outer_retry_key=claim_retry_key,
            item_id=item_id,
            sequence=4,
            action=ProgrammeCommandAction.PROPOSAL_ANSWER_REVISED,
        ),
        correlation_id=claim_correlation_id,
        source_channel="test",
        now=now,
        authorizer=_PROGRAMME_AUTHORIZER,
    )

    with (
        pytest.raises(
            DatabaseError,
            match="nested command scope, actor, correlation, or version mismatch",
        ),
        transaction.atomic(),
        programme_import_database_writer(),
    ):
        ProgrammeImportAppliedCommand.objects.create(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            binding=binding,
            import_receipt=receipt,
            sequence=4,
            programme_receipt_id=later_edit.receipt_id,
        )

    binding.proposal.submission.refresh_from_db()
    assert binding.proposal.submission.aggregate_version == 4
    assert (
        ProgrammeImportAppliedCommand.objects.filter(import_receipt=receipt).count()
        == 3
    )


def test_proposal_answer_type_mismatch_is_blocked_without_writes() -> None:
    """Require each staged answer tag to match the resolved call question type."""

    edition = EventEditionFactory()
    manager = AccountFactory(display_name="Programme manager")
    lead = AccountFactory(
        display_name="Imported presenter",
        email="typed-presenter@example.test",
    )
    department = create_department_for_test(
        edition=edition,
        name="Programme",
        expected_code="programme",
    )
    now = timezone.now()
    proposal = _proposal_item(lead_email=lead.email)
    proposal_answers = proposal["answers"]
    assert isinstance(proposal_answers, list)
    decimal_answer = next(
        answer
        for answer in proposal_answers
        if isinstance(answer, dict)
        and answer.get("question_key") == "estimated-attendance"
    )
    decimal_answer["field_type"] = "integer"
    decimal_answer["value"] = 1
    batch_id = _stage(
        actor=manager,
        edition=edition,
        department_id=department.id,
        payload=_document([proposal, _call_item(now)]),
        now=now,
    )
    initial = preview_programme_import(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        batch_id=batch_id,
        expected_batch_version=1,
        reason="Preview the tagged proposal before resolving its call.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
    )
    call_preview = next(
        item for item in initial.items if item.kind == ProgrammeImportItemKind.CALL
    )
    committed = commit_programme_import_call(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=call_preview.item_id,
        preview_item_result_id=call_preview.result_id,
        expected_version=1,
        reason="Adopt the dependency call for the typed-answer check.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
        programme_authorizer=_PROGRAMME_AUTHORIZER,
    )
    binding = ProgrammeImportSourceBinding.objects.get(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=committed.item_id,
        call__isnull=False,
    )
    call = ProgrammeCall.objects.get(id=binding.call_id)
    activate_programme_call(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        call_id=call.id,
        owner_department_id=department.id,
        expected_version=1,
        reason="Activate the dependency for typed-answer validation.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_PROGRAMME_AUTHORIZER,
    )

    refreshed = preview_programme_import(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        batch_id=batch_id,
        expected_batch_version=1,
        reason="Resolve every tagged proposal answer against the active call.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
    )
    proposal_preview = next(
        item
        for item in refreshed.items
        if item.kind == ProgrammeImportItemKind.PROPOSAL
    )

    assert proposal_preview.status == ProgrammeImportPreviewStatus.BLOCKED
    assert proposal_preview.action == ProgrammeImportPreviewAction.NONE
    assert proposal_preview.reason_codes == ("proposal_mapping_invalid",)
    with pytest.raises(ApplicationsProgrammeImportClaimUnavailableError):
        preview_programme_import_proposal_claim(
            actor_id=lead.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            item_id=proposal_preview.item_id,
            correlation_id=uuid4(),
            source_channel="test",
            now=now,
            authorizer=_IMPORT_AUTHORIZER,
        )
    assert not ProgrammeProposal.objects.filter(edition_id=edition.id).exists()
    assert not ProgrammeImportSourceBinding.objects.filter(
        item_id=proposal_preview.item_id
    ).exists()
    staged_proposal = ProgrammeImportItem.objects.get(id=proposal_preview.item_id)
    assert staged_proposal.state == ProgrammeImportItemState.STAGED
    assert staged_proposal.canonical_payload is not None


def test_call_commit_exact_replay_and_cross_family_retry_collision() -> None:
    """Replay one import receipt and reject a nested Programme retry key."""

    edition = EventEditionFactory()
    manager = AccountFactory(display_name="Programme manager")
    department = create_department_for_test(
        edition=edition,
        name="Programme",
        expected_code="programme",
    )
    now = timezone.now()
    batch_id = _stage(
        actor=manager,
        edition=edition,
        department_id=department.id,
        payload=_document([_call_item(now)]),
        now=now,
    )
    preview = preview_programme_import(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        batch_id=batch_id,
        expected_batch_version=1,
        reason="Review the exact call before testing receipt replay.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
    )
    call_preview = preview.items[0]
    commit_retry_key = uuid4()
    commit_correlation_id = uuid4()
    commit_reason = "Adopt this exact reviewed call once."
    committed = commit_programme_import_call(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=call_preview.item_id,
        preview_item_result_id=call_preview.result_id,
        expected_version=1,
        reason=commit_reason,
        retry_key=commit_retry_key,
        correlation_id=commit_correlation_id,
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
        programme_authorizer=_PROGRAMME_AUTHORIZER,
    )
    assert committed.replayed is False
    after_commit = _scope_row_counts(edition_id=edition.id)

    replayed = commit_programme_import_call(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=call_preview.item_id,
        preview_item_result_id=call_preview.result_id,
        expected_version=1,
        reason=commit_reason,
        retry_key=commit_retry_key,
        correlation_id=commit_correlation_id,
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
        programme_authorizer=_PROGRAMME_AUTHORIZER,
    )

    assert replayed.replayed is True
    assert replayed.receipt_id == committed.receipt_id
    assert not hasattr(committed, "source_binding_id")
    assert not hasattr(replayed, "source_binding_id")
    assert replayed.resulting_version == committed.resulting_version
    assert _scope_row_counts(edition_id=edition.id) == after_commit
    assert (
        ProgrammeImportCommandReceipt.objects.filter(
            edition_id=edition.id,
            actor_id=manager.id,
            retry_key=commit_retry_key,
        ).count()
        == 1
    )

    nested_link = ProgrammeImportAppliedCommand.objects.select_related(
        "programme_receipt"
    ).get(
        import_receipt_id=committed.receipt_id,
        binding__item_id=committed.item_id,
        binding__call__isnull=False,
    )
    before_collision = _scope_row_counts(edition_id=edition.id)
    collision_correlation_id = uuid4()
    with pytest.raises(ApplicationsProgrammeImportIdempotencyConflictError):
        discard_programme_import(
            actor_id=manager.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            batch_id=batch_id,
            expected_version=1,
            reason="A Programme-family retry key cannot dispose an import.",
            retry_key=nested_link.programme_receipt.retry_key,
            correlation_id=collision_correlation_id,
            source_channel="test",
            now=now,
            authorizer=_IMPORT_AUTHORIZER,
        )
    after_collision = _scope_row_counts(edition_id=edition.id)
    assert after_collision == {
        **before_collision,
        "audits": before_collision["audits"] + 1,
    }
    collision_audit = AuditEvent.objects.get(
        correlation_id=collision_correlation_id,
        operation="applications.programme_import.command.batch_discarded",
    )
    assert collision_audit.outcome == "error"
    assert collision_audit.target_id is None
    batch = ProgrammeImportBatch.objects.get(id=batch_id)
    assert batch.state == ProgrammeImportBatchState.STAGED
    assert batch.aggregate_version == 1
    assert batch.items.get().state == ProgrammeImportItemState.APPLIED


def test_call_import_and_direct_command_retry_race_cannot_deadlock(  # noqa: PLR0915
) -> None:
    """Acquire the nested retry lock before import-owned edition row locks."""

    edition = EventEditionFactory()
    manager = AccountFactory(display_name="Concurrent Programme manager")
    department = create_department_for_test(
        edition=edition,
        name="Programme",
        expected_code="programme",
    )
    now = timezone.now()
    staged_call = _call_item(now)
    batch_id = _stage(
        actor=manager,
        edition=edition,
        department_id=department.id,
        payload=_document([staged_call]),
        now=now,
    )
    preview = preview_programme_import(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        batch_id=batch_id,
        expected_batch_version=1,
        reason="Prepare the staged call for the retry-lock race.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
    )
    call_preview = preview.items[0]
    outer_retry_key = uuid4()
    nested_retry_key = _nested_call_retry_key(
        outer_retry_key=outer_retry_key,
        item_id=call_preview.item_id,
    )
    direct_call = deepcopy(staged_call)
    direct_definition = direct_call["definition"]
    assert isinstance(direct_definition, dict)
    direct_definition["code"] = "direct-concurrent-call"
    direct_definition["name"] = "Direct concurrent call"
    parsed_direct = parse_programme_import_document(_document([direct_call]))
    direct_input = parsed_direct.items[0]
    assert isinstance(direct_input, ProgrammeImportCallItemInput)
    direct_holds_nested_retry = Event()
    release_direct = Event()
    import_attempts_nested_retry = Event()
    import_correlation_id = uuid4()
    direct_correlation_id = uuid4()
    original_import_lock = programme_import_commands.lock_applications_retry_namespace

    def observed_import_lock(
        *,
        edition_id: UUID,
        actor_id: UUID,
        retry_key: UUID,
    ) -> None:
        if retry_key == nested_retry_key:
            import_attempts_nested_retry.set()
        original_import_lock(
            edition_id=edition_id,
            actor_id=actor_id,
            retry_key=retry_key,
        )

    def direct_worker() -> object:
        close_old_connections()
        try:
            with transaction.atomic():
                lock_applications_retry_namespace(
                    edition_id=edition.id,
                    actor_id=manager.id,
                    retry_key=nested_retry_key,
                )
                direct_holds_nested_retry.set()
                assert release_direct.wait(timeout=10)
                return create_programme_call(
                    actor_id=manager.id,
                    organization_id=edition.organization_id,
                    edition_id=edition.id,
                    definition_input=direct_input.definition_input,
                    configuration=direct_input.configuration_for_owner_department(
                        department.id
                    ),
                    expected_version=0,
                    reason="Create a distinct direct call under the nested retry key.",
                    retry_key=nested_retry_key,
                    correlation_id=direct_correlation_id,
                    source_channel="test",
                    now=now,
                    authorizer=_PROGRAMME_AUTHORIZER,
                )
        finally:
            connections.close_all()

    def import_worker() -> Exception | None:
        close_old_connections()
        try:
            try:
                commit_programme_import_call(
                    actor_id=manager.id,
                    organization_id=edition.organization_id,
                    edition_id=edition.id,
                    item_id=call_preview.item_id,
                    preview_item_result_id=call_preview.result_id,
                    expected_version=1,
                    reason="Adopt the staged call after winning every retry lock.",
                    retry_key=outer_retry_key,
                    correlation_id=import_correlation_id,
                    source_channel="test",
                    now=now,
                    authorizer=_IMPORT_AUTHORIZER,
                    programme_authorizer=_PROGRAMME_AUTHORIZER,
                )
            except Exception as error:  # noqa: BLE001 - inspect the service boundary
                return error
        finally:
            connections.close_all()
        return None

    with (
        patch.object(
            programme_import_commands,
            "lock_applications_retry_namespace",
            side_effect=observed_import_lock,
        ),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        direct_future = executor.submit(direct_worker)
        assert direct_holds_nested_retry.wait(timeout=10)
        import_future = executor.submit(import_worker)
        assert import_attempts_nested_retry.wait(timeout=10)
        release_direct.set()
        direct_result = direct_future.result(timeout=20)
        import_error = import_future.result(timeout=20)

    assert direct_result is not None
    assert isinstance(import_error, ApplicationsProgrammeImportOperationFailedError)
    assert import_error.correlation_id == import_correlation_id
    assert str(import_error) == import_error.reason_code
    assert import_error.__cause__ is None
    assert import_error.__context__ is None
    item = ProgrammeImportItem.objects.get(id=call_preview.item_id)
    assert item.state == ProgrammeImportItemState.STAGED
    assert item.aggregate_version == 1
    assert item.canonical_payload is not None
    assert ProgrammeCall.objects.filter(edition_id=edition.id).count() == 1
    assert (
        ProgrammeCommandReceipt.objects.filter(
            edition_id=edition.id,
            actor_id=manager.id,
            retry_key=nested_retry_key,
            action=ProgrammeCommandAction.CALL_CREATED,
        ).count()
        == 1
    )
    assert not ProgrammeImportCommandReceipt.objects.filter(
        edition_id=edition.id,
        actor_id=manager.id,
        retry_key=outer_retry_key,
        action=ProgrammeImportCommandAction.CALL_COMMITTED,
    ).exists()
    assert not ProgrammeImportSourceBinding.objects.filter(item=item).exists()
    assert not ProgrammeImportAppliedCommand.objects.filter(
        edition_id=edition.id,
        binding__item=item,
    ).exists()
    failure = AuditEvent.objects.get(
        correlation_id=import_correlation_id,
        operation="applications.programme_import.command.call_committed",
    )
    assert failure.outcome == "error"
    assert failure.reason_code == "applications_programme_idempotency_conflict"
    assert failure.target_id is None
    assert not DomainEvent.objects.filter(
        correlation_id=import_correlation_id,
    ).exists()
    assert not OutboxMessage.objects.filter(
        event__correlation_id=import_correlation_id,
    ).exists()


def test_denied_and_absent_organizer_targets_share_one_failure_shape() -> None:
    """Prevent batch and item identifiers from becoming authorization oracles."""

    edition = EventEditionFactory()
    manager = AccountFactory(display_name="Programme manager")
    department = create_department_for_test(
        edition=edition,
        name="Programme",
        expected_code="programme",
    )
    now = timezone.now()
    batch_id = _stage(
        actor=manager,
        edition=edition,
        department_id=department.id,
        payload=_document([_call_item(now)]),
        now=now,
    )
    preview = preview_programme_import(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        batch_id=batch_id,
        expected_batch_version=1,
        reason="Create one exact ready result before testing denial collapse.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
    )
    item = preview.items[0]
    denying_authorizer = _DenyImportTargetAuthorizer()
    before = _scope_row_counts(edition_id=edition.id)
    existing_audit_ids = set(
        AuditEvent.objects.filter(event_edition_id=edition.id).values_list(
            "id",
            flat=True,
        )
    )

    for candidate_batch_id in (batch_id, uuid4()):
        with pytest.raises(ApplicationsProgrammeImportUnavailableError):
            preview_programme_import(
                actor_id=manager.id,
                organization_id=edition.organization_id,
                edition_id=edition.id,
                batch_id=candidate_batch_id,
                expected_batch_version=1,
                reason="Collapse denied and absent preview targets.",
                retry_key=uuid4(),
                correlation_id=uuid4(),
                source_channel="test",
                now=now,
                authorizer=denying_authorizer,
            )
        with pytest.raises(ApplicationsProgrammeImportUnavailableError):
            discard_programme_import(
                actor_id=manager.id,
                organization_id=edition.organization_id,
                edition_id=edition.id,
                batch_id=candidate_batch_id,
                expected_version=1,
                reason="Collapse denied and absent disposal targets.",
                retry_key=uuid4(),
                correlation_id=uuid4(),
                source_channel="test",
                now=now,
                authorizer=denying_authorizer,
            )

    for candidate_item_id in (item.item_id, uuid4()):
        with pytest.raises(ApplicationsProgrammeImportUnavailableError):
            commit_programme_import_call(
                actor_id=manager.id,
                organization_id=edition.organization_id,
                edition_id=edition.id,
                item_id=candidate_item_id,
                preview_item_result_id=item.result_id,
                expected_version=1,
                reason="Collapse denied and absent call-import targets.",
                retry_key=uuid4(),
                correlation_id=uuid4(),
                source_channel="test",
                now=now,
                authorizer=denying_authorizer,
                programme_authorizer=_PROGRAMME_AUTHORIZER,
            )

    after = _scope_row_counts(edition_id=edition.id)
    assert after == {**before, "audits": before["audits"] + 6}
    failure_audits = AuditEvent.objects.filter(
        event_edition_id=edition.id,
    ).exclude(id__in=existing_audit_ids)
    assert failure_audits.filter(outcome="deny").count() == 4
    assert failure_audits.filter(outcome="error").count() == 2
    assert not failure_audits.exclude(target_id__isnull=True).exists()
    assert set(failure_audits.values_list("operation", flat=True)) == {
        "applications.programme_import.command.batch_previewed",
        "applications.programme_import.command.batch_discarded",
        "applications.programme_import.command.call_committed",
    }
    staged_item = ProgrammeImportItem.objects.get(id=item.item_id)
    assert staged_item.state == ProgrammeImportItemState.STAGED
    assert staged_item.canonical_payload is not None


def test_corrupt_staged_evidence_collapses_to_safe_operation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not expose parser diagnostics recovered from private stored bytes."""

    edition = EventEditionFactory()
    manager = AccountFactory(display_name="Programme manager")
    department = create_department_for_test(
        edition=edition,
        name="Programme",
        expected_code="programme",
    )
    now = timezone.now()
    batch_id = _stage(
        actor=manager,
        edition=edition,
        department_id=department.id,
        payload=_document([_call_item(now)]),
        now=now,
    )
    before = _scope_row_counts(edition_id=edition.id)
    correlation_id = uuid4()

    def corrupt_reload(_payload: bytes) -> ProgrammeImportCallItemInput:
        raise ProgrammeImportInputError(
            "applications_programme_import_json_invalid",
            item_index=0,
            pointer="/items/0/definition",
            field="definition",
        )

    monkeypatch.setattr(
        programme_import_commands,
        "parse_programme_import_item_payload",
        corrupt_reload,
    )

    with pytest.raises(
        ApplicationsProgrammeImportOperationFailedError
    ) as operation_failure:
        preview_programme_import(
            actor_id=manager.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            batch_id=batch_id,
            expected_batch_version=1,
            reason="Exercise safe handling of incompatible retained evidence.",
            retry_key=uuid4(),
            correlation_id=correlation_id,
            source_channel="test",
            now=now,
            authorizer=_IMPORT_AUTHORIZER,
        )

    assert operation_failure.value.correlation_id == correlation_id
    assert str(operation_failure.value) == operation_failure.value.reason_code
    assert operation_failure.value.__cause__ is None
    assert operation_failure.value.__context__ is None
    after = _scope_row_counts(edition_id=edition.id)
    assert after == {**before, "audits": before["audits"] + 1}
    failure = AuditEvent.objects.get(
        correlation_id=correlation_id,
        operation="applications.programme_import.command.batch_previewed",
    )
    assert failure.outcome == "error"
    assert failure.reason_code == "applications_programme_import_dependency_error"
    assert failure.target_id is None
    serialized = json.dumps(failure.safe_metadata, sort_keys=True)
    assert "json_invalid" not in serialized
    assert "/items/0/definition" not in serialized


def test_non_lead_claim_preview_is_minimized_and_audited() -> None:
    """Retain one source-accurate denial without exposing staged lead data."""

    edition = EventEditionFactory()
    manager = AccountFactory(display_name="Programme manager")
    lead = AccountFactory(
        display_name="Expected imported presenter",
        email="expected-presenter@example.test",
    )
    intruder = AccountFactory(
        display_name="Different presenter",
        email="different-presenter@example.test",
    )
    department = create_department_for_test(
        edition=edition,
        name="Programme",
        expected_code="programme",
    )
    now = timezone.now()
    _batch_id, proposal_item_id, _adoption_digest = _prepare_claimable_import(
        edition=edition,
        manager=manager,
        lead=lead,
        department_id=department.id,
        now=now,
    )
    before = _scope_row_counts(edition_id=edition.id)
    correlation_id = uuid4()

    with pytest.raises(ApplicationsProgrammeImportClaimUnavailableError):
        preview_programme_import_proposal_claim(
            actor_id=intruder.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            item_id=proposal_item_id,
            correlation_id=correlation_id,
            source_channel="test",
            now=now,
            authorizer=_IMPORT_AUTHORIZER,
        )

    after = _scope_row_counts(edition_id=edition.id)
    assert after == {**before, "audits": before["audits"] + 1}
    denial = AuditEvent.objects.get(
        correlation_id=correlation_id,
        operation="applications.programme_import.query.proposal_claim_preview",
    )
    assert denial.outcome == "deny"
    assert denial.source_channel == "test"
    assert denial.target_id is None
    serialized = json.dumps(denial.safe_metadata, sort_keys=True)
    assert lead.email not in serialized
    assert "Community meetup" not in serialized


def test_lead_preview_survives_planning_closure_but_claim_does_not() -> None:
    """Allow retained self disclosure while keeping proposal creation closed."""

    edition = EventEditionFactory()
    manager = AccountFactory(display_name="Programme manager")
    lead = AccountFactory(
        display_name="Imported presenter",
        email="planning-closed-presenter@example.test",
    )
    department = create_department_for_test(
        edition=edition,
        name="Programme",
        expected_code="programme",
    )
    now = timezone.now()
    _batch_id, proposal_item_id, _adoption_digest = _prepare_claimable_import(
        edition=edition,
        manager=manager,
        lead=lead,
        department_id=department.id,
        now=now,
    )
    for lifecycle in (
        EventEdition.Lifecycle.PREPARING,
        EventEdition.Lifecycle.READY,
    ):
        EventEdition.objects.filter(id=edition.id).update(
            lifecycle=lifecycle,
            lifecycle_version=F("lifecycle_version") + 1,
            aggregate_version=F("aggregate_version") + 1,
        )

    private_preview = preview_programme_import_proposal_claim(
        actor_id=lead.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=proposal_item_id,
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
    )

    assert private_preview.item_id == proposal_item_id
    with pytest.raises(ApplicationsProgrammeImportClaimUnavailableError):
        claim_programme_import_proposal(
            actor_id=lead.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            item_id=proposal_item_id,
            lead_profile=_profile(),
            adopted_preview_digest=private_preview.adoption_digest,
            expected_version=1,
            reason="Keep proposal creation closed after planning ends.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            now=now,
            authorizer=_IMPORT_AUTHORIZER,
            programme_authorizer=_PROGRAMME_AUTHORIZER,
        )
    assert not ProgrammeProposal.objects.filter(edition_id=edition.id).exists()


def test_proposal_claim_rechecks_private_field_disclosure_under_lock() -> None:
    """Leave staged evidence untouched when claim disclosure is withdrawn."""

    edition = EventEditionFactory()
    manager = AccountFactory(display_name="Programme manager")
    lead = AccountFactory(
        display_name="Imported presenter",
        email="revoked-disclosure-presenter@example.test",
    )
    department = create_department_for_test(
        edition=edition,
        name="Programme",
        expected_code="programme",
    )
    now = timezone.now()
    _batch_id, proposal_item_id, adoption_digest = _prepare_claimable_import(
        edition=edition,
        manager=manager,
        lead=lead,
        department_id=department.id,
        now=now,
    )
    item = ProgrammeImportItem.objects.get(id=proposal_item_id)
    original_payload = item.canonical_payload
    revoking_authorizer = _RevokeClaimDisclosureAuthorizer()

    with pytest.raises(ApplicationsProgrammeImportClaimUnavailableError):
        claim_programme_import_proposal(
            actor_id=lead.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            item_id=proposal_item_id,
            lead_profile=_profile(),
            adopted_preview_digest=adoption_digest,
            expected_version=1,
            reason="Do not claim after private field disclosure is withdrawn.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            now=now,
            authorizer=revoking_authorizer,
            programme_authorizer=_PROGRAMME_AUTHORIZER,
        )

    assert revoking_authorizer.view_calls == 2
    item.refresh_from_db()
    assert item.state == ProgrammeImportItemState.STAGED
    assert item.aggregate_version == 1
    assert item.canonical_payload == original_payload
    assert not ProgrammeProposal.objects.filter(edition_id=edition.id).exists()
    assert not ProgrammeImportSourceBinding.objects.filter(
        item_id=proposal_item_id,
    ).exists()


def test_proposal_claim_rolls_back_when_first_nested_answer_is_denied() -> None:
    """Roll back start, evidence, and import adoption after nested denial."""

    edition = EventEditionFactory()
    manager = AccountFactory(display_name="Programme manager")
    lead = AccountFactory(
        display_name="Imported presenter",
        email="rollback-presenter@example.test",
    )
    department = create_department_for_test(
        edition=edition,
        name="Programme",
        expected_code="programme",
    )
    now = timezone.now()
    batch_id, proposal_item_id, adoption_digest = _prepare_claimable_import(
        edition=edition,
        manager=manager,
        lead=lead,
        department_id=department.id,
        now=now,
    )
    proposal_item = ProgrammeImportItem.objects.get(id=proposal_item_id)
    original_payload = proposal_item.canonical_payload
    before_claim = _scope_row_counts(edition_id=edition.id)
    claim_retry_key = uuid4()
    claim_correlation_id = uuid4()
    denying_authorizer = _DenyFirstAnswerProgrammeAuthorizer()

    with pytest.raises(
        ApplicationsProgrammeImportOperationFailedError
    ) as operation_failure:
        claim_programme_import_proposal(
            actor_id=lead.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            item_id=proposal_item_id,
            lead_profile=_profile(),
            adopted_preview_digest=adoption_digest,
            expected_version=1,
            reason="Exercise atomic rollback after the nested proposal start.",
            retry_key=claim_retry_key,
            correlation_id=claim_correlation_id,
            source_channel="test",
            now=now,
            authorizer=_IMPORT_AUTHORIZER,
            programme_authorizer=denying_authorizer,
        )

    assert operation_failure.value.correlation_id == claim_correlation_id
    assert str(operation_failure.value) == operation_failure.value.reason_code
    assert lead.email not in repr(operation_failure.value)
    assert operation_failure.value.__cause__ is None
    assert operation_failure.value.__context__ is None
    assert denying_authorizer.saw_started_proposal is True
    after_claim = _scope_row_counts(edition_id=edition.id)
    assert after_claim == {**before_claim, "audits": before_claim["audits"] + 1}
    failure_audit = AuditEvent.objects.get(
        correlation_id=claim_correlation_id,
        operation="applications.programme_import.command.proposal_claimed",
    )
    assert failure_audit.outcome == "deny"
    assert failure_audit.target_id is None
    assert not ApplicationSubmission.objects.filter(edition_id=edition.id).exists()
    assert not ProgrammeProposal.objects.filter(edition_id=edition.id).exists()
    assert not ProgrammeImportSourceBinding.objects.filter(
        edition_id=edition.id,
        kind=ProgrammeImportItemKind.PROPOSAL,
    ).exists()
    assert not ProgrammeImportCommandReceipt.objects.filter(
        edition_id=edition.id,
        actor_id=lead.id,
        retry_key=claim_retry_key,
    ).exists()
    proposal_item.refresh_from_db()
    assert proposal_item.state == ProgrammeImportItemState.STAGED
    assert proposal_item.aggregate_version == 1
    assert proposal_item.canonical_payload == original_payload
    batch = ProgrammeImportBatch.objects.get(id=batch_id)
    assert batch.state == ProgrammeImportBatchState.STAGED
    assert batch.aggregate_version == 1


def test_expired_payload_can_only_be_disposed() -> None:
    """Block expired private values while preserving their minimization path."""

    edition = EventEditionFactory()
    manager = AccountFactory(display_name="Programme manager")
    department = create_department_for_test(
        edition=edition,
        name="Programme",
        expected_code="programme",
    )
    now = timezone.now()
    batch_id = _stage(
        actor=manager,
        edition=edition,
        department_id=department.id,
        payload=_document([_call_item(now)]),
        now=now,
        retention=_RetentionProvider(lifetime=timedelta(seconds=1)),
    )
    preview_retry_key = uuid4()
    preview_reason = "Review the private payload before its retention deadline."
    preview_programme_import(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        batch_id=batch_id,
        expected_batch_version=1,
        reason=preview_reason,
        retry_key=preview_retry_key,
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
    )

    with pytest.raises(ApplicationsProgrammeImportUnavailableError):
        preview_programme_import(
            actor_id=manager.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            batch_id=batch_id,
            expected_batch_version=1,
            reason="An expired private payload must not be disclosed.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            now=now + timedelta(seconds=2),
            authorizer=_IMPORT_AUTHORIZER,
        )

    with pytest.raises(ApplicationsProgrammeImportUnavailableError):
        preview_programme_import(
            actor_id=manager.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            batch_id=batch_id,
            expected_batch_version=1,
            reason=preview_reason,
            retry_key=preview_retry_key,
            correlation_id=uuid4(),
            source_channel="test",
            now=now + timedelta(seconds=2),
            authorizer=_IMPORT_AUTHORIZER,
        )

    discarded = discard_programme_import(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        batch_id=batch_id,
        expected_version=1,
        reason="Minimize the expired Programme staging payload.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now + timedelta(seconds=2),
        authorizer=_IMPORT_AUTHORIZER,
    )
    assert discarded.resulting_version == 2
    assert ProgrammeImportItem.objects.get(batch_id=batch_id).state == (
        ProgrammeImportItemState.DISCARDED
    )


def test_pristine_batch_reassignment_preserves_evidence_and_stales_previews(  # noqa: PLR0915
) -> None:
    """Transfer only pristine staging and advance every later batch cursor."""

    edition = EventEditionFactory()
    manager = AccountFactory(display_name="Programme continuity manager")
    source = create_department_for_test(
        edition=edition,
        name="Programme intake",
        expected_code="programme-intake",
    )
    destination = create_department_for_test(
        edition=edition,
        name="Programme review",
        expected_code="programme-review",
    )
    later_destination = create_department_for_test(
        edition=edition,
        name="Programme scheduling",
        expected_code="programme-scheduling",
    )
    now = timezone.now()
    batch_id = _stage(
        actor=manager,
        edition=edition,
        department_id=source.id,
        payload=_document([_call_item(now)]),
        now=now,
    )
    first_preview = preview_programme_import(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        batch_id=batch_id,
        expected_batch_version=1,
        reason="Review the staged call before transferring intake ownership.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
    )
    original_item = ProgrammeImportItem.objects.get(batch_id=batch_id)
    original_payload = bytes(original_item.canonical_payload or b"")
    retry_key = uuid4()
    reason = "Transfer untouched staging to the Programme review Department."

    with pytest.raises(ApplicationsProgrammeImportUnavailableError):
        reassign_programme_import_batch(
            actor_id=manager.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            batch_id=batch_id,
            source_department_id=source.id,
            destination_department_id=destination.id,
            expected_version=1,
            reason=reason,
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            now=now,
            authorizer=_DenyImportTargetAuthorizer(denied_department_id=destination.id),
        )
    denied_batch = ProgrammeImportBatch.objects.get(id=batch_id)
    assert denied_batch.owner_department_id == source.id
    assert denied_batch.aggregate_version == 1

    reassigned = reassign_programme_import_batch(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        batch_id=batch_id,
        source_department_id=source.id,
        destination_department_id=destination.id,
        expected_version=1,
        reason=reason,
        retry_key=retry_key,
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
    )

    assert reassigned.action == ProgrammeImportCommandAction.BATCH_REASSIGNED
    assert reassigned.resulting_version == 2
    batch = ProgrammeImportBatch.objects.get(id=batch_id)
    item = ProgrammeImportItem.objects.get(id=original_item.id)
    assert batch.owner_department_id == destination.id
    assert batch.aggregate_version == 2
    assert item.state == ProgrammeImportItemState.STAGED
    assert item.aggregate_version == 1
    assert bytes(item.canonical_payload or b"") == original_payload
    receipt = ProgrammeImportCommandReceipt.objects.get(id=reassigned.receipt_id)
    assert receipt.source_department_id == source.id
    assert receipt.destination_department_id == destination.id
    assert receipt.expected_version == 1
    assert receipt.resulting_version == 2
    event = DomainEvent.objects.get(
        aggregate_id=batch_id,
        payload__action=ProgrammeImportCommandAction.BATCH_REASSIGNED,
    )
    assert event.payload["batch_version"] == 2

    with patch.object(
        programme_import_commands,
        "lock_programme_edition_write_scope",
        side_effect=AssertionError("a successful replay must not lock the edition"),
    ):
        replayed = reassign_programme_import_batch(
            actor_id=manager.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            batch_id=batch_id,
            source_department_id=source.id,
            destination_department_id=destination.id,
            expected_version=1,
            reason=reason,
            retry_key=retry_key,
            correlation_id=uuid4(),
            source_channel="test",
            now=now,
            authorizer=_IMPORT_AUTHORIZER,
        )
    assert replayed.replayed is True
    assert replayed.receipt_id == reassigned.receipt_id

    first_call_preview = first_preview.items[0]
    with pytest.raises(ApplicationsProgrammeImportPreviewStaleError):
        commit_programme_import_call(
            actor_id=manager.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            item_id=first_call_preview.item_id,
            preview_item_result_id=first_call_preview.result_id,
            expected_version=1,
            reason="Do not accept an organizer preview from the former owner.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            now=now,
            authorizer=_IMPORT_AUTHORIZER,
            programme_authorizer=_PROGRAMME_AUTHORIZER,
        )

    fresh_preview = preview_programme_import(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        batch_id=batch_id,
        expected_batch_version=2,
        reason="Review the transferred staging under its current owner.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
    )
    committed = commit_programme_import_call(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=fresh_preview.items[0].item_id,
        preview_item_result_id=fresh_preview.items[0].result_id,
        expected_version=1,
        reason="Apply the freshly reviewed call for the current owner.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
        programme_authorizer=_PROGRAMME_AUTHORIZER,
    )
    binding = ProgrammeImportSourceBinding.objects.get(item_id=committed.item_id)
    assert binding.call is not None
    assert binding.call.owner_department_id == destination.id

    moved_call = reassign_programme_call(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        call_id=binding.call_id,
        source_department_id=destination.id,
        destination_department_id=later_destination.id,
        expected_version=1,
        reason="Move the imported call while retaining its original source evidence.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_PROGRAMME_AUTHORIZER,
    )
    assert moved_call.resulting_version == 2
    binding.refresh_from_db()
    assert binding.call.owner_department_id == later_destination.id
    assert (
        ProgrammeImportBatch.objects.get(id=batch_id).owner_department_id
        == destination.id
    )

    with pytest.raises(ApplicationsProgrammeImportStateConflictError):
        reassign_programme_import_batch(
            actor_id=manager.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            batch_id=batch_id,
            source_department_id=destination.id,
            destination_department_id=later_destination.id,
            expected_version=2,
            reason="Applied source evidence must make transfer disposal-only.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            now=now,
            authorizer=_IMPORT_AUTHORIZER,
        )

    discarded = discard_programme_import(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        batch_id=batch_id,
        expected_version=2,
        reason="Close retained staging after applying the reviewed call.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
    )
    assert discarded.resulting_version == 3


def test_batch_reassignment_rejects_receipt_with_a_different_valid_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid same-edition Department cannot stand in for the actual old owner."""
    edition = EventEditionFactory()
    manager = AccountFactory()
    source, destination, unrelated = (
        create_department_for_test(edition=edition, name=name, expected_code=name)
        for name in ("source", "destination", "unrelated")
    )
    now = timezone.now()
    batch_id = _stage(
        actor=manager,
        edition=edition,
        department_id=source.id,
        payload=_document([_call_item(now)]),
        now=now,
    )
    original_record = programme_import_commands._record_success

    def record_wrong_source(**kwargs):
        kwargs["source_department_id"] = unrelated.id
        return original_record(**kwargs)

    monkeypatch.setattr(
        programme_import_commands, "_record_success", record_wrong_source
    )
    with (
        patch.object(
            programme_import_commands,
            "_append_failure_audit_best_effort",
            wraps=programme_import_commands._append_failure_audit_best_effort,
        ) as failure_audit,
        pytest.raises(ApplicationsProgrammeImportOperationFailedError),
    ):
        reassign_programme_import_batch(
            actor_id=manager.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            batch_id=batch_id,
            source_department_id=source.id,
            destination_department_id=destination.id,
            expected_version=1,
            reason="Require the receipt to identify the real previous owner.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            now=now,
            authorizer=_IMPORT_AUTHORIZER,
        )
    database_error = failure_audit.call_args.kwargs["error"]
    assert isinstance(database_error, DatabaseError)
    assert "exact transition evidence" in str(database_error)
    batch = ProgrammeImportBatch.objects.get(id=batch_id)
    assert batch.owner_department_id == source.id
    assert batch.aggregate_version == 1
    assert not ProgrammeImportCommandReceipt.objects.filter(
        batch_id=batch_id, action=ProgrammeImportCommandAction.BATCH_REASSIGNED
    ).exists()


def test_proposal_claim_rejects_identity_change_after_preview() -> None:
    """Re-resolve the staged login email when its account owner changes."""

    edition = EventEditionFactory()
    manager = AccountFactory(display_name="Programme manager")
    lead = AccountFactory(
        display_name="Original imported presenter",
        email="original-presenter@example.test",
    )
    department = create_department_for_test(
        edition=edition,
        name="Programme",
        expected_code="programme",
    )
    now = timezone.now()
    _batch_id, proposal_item_id, adoption_digest = _prepare_claimable_import(
        edition=edition,
        manager=manager,
        lead=lead,
        department_id=department.id,
        now=now,
    )
    original_email = lead.email
    lead.email = "moved-presenter@example.test"
    lead.save(update_fields=("email",))
    replacement = AccountFactory(
        display_name="New login-email owner",
        email=original_email,
    )

    with pytest.raises(ApplicationsProgrammeImportClaimUnavailableError):
        claim_programme_import_proposal(
            actor_id=lead.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            item_id=proposal_item_id,
            lead_profile=_profile(),
            adopted_preview_digest=adoption_digest,
            expected_version=1,
            reason="Reject a claim after the staged login identity changes.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            now=now,
            authorizer=_IMPORT_AUTHORIZER,
            programme_authorizer=_PROGRAMME_AUTHORIZER,
        )

    assert replacement.id != lead.id
    item = ProgrammeImportItem.objects.get(id=proposal_item_id)
    assert item.state == ProgrammeImportItemState.STAGED
    assert item.canonical_payload is not None
    assert not ProgrammeProposal.objects.filter(edition_id=edition.id).exists()
    assert not ProgrammeImportSourceBinding.objects.filter(item=item).exists()


def test_concurrent_same_source_call_apply_commits_one_binding() -> None:
    """Serialize source-identical commits and retain one canonical target."""

    edition = EventEditionFactory()
    first_manager = AccountFactory(display_name="First Programme manager")
    second_manager = AccountFactory(display_name="Second Programme manager")
    first_department = create_department_for_test(
        edition=edition,
        name="First Programme",
        expected_code="first-programme",
    )
    second_department = create_department_for_test(
        edition=edition,
        name="Second Programme",
        expected_code="second-programme",
    )
    now = timezone.now()
    payload = _document([_call_item(now)])
    first_batch_id = _stage(
        actor=first_manager,
        edition=edition,
        department_id=first_department.id,
        payload=payload,
        now=now,
    )
    second_batch_id = _stage(
        actor=second_manager,
        edition=edition,
        department_id=second_department.id,
        payload=payload,
        now=now,
    )
    first_preview = preview_programme_import(
        actor_id=first_manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        batch_id=first_batch_id,
        expected_batch_version=1,
        reason="Review the first source-identical call before the race.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
    ).items[0]
    second_preview = preview_programme_import(
        actor_id=second_manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        batch_id=second_batch_id,
        expected_batch_version=1,
        reason="Review the second source-identical call before the race.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
    ).items[0]
    start = Barrier(2)

    def commit_worker(
        *,
        actor_id: UUID,
        item_id: UUID,
        preview_result_id: UUID,
    ) -> str:
        close_old_connections()
        try:
            start.wait(timeout=10)
            commit_programme_import_call(
                actor_id=actor_id,
                organization_id=edition.organization_id,
                edition_id=edition.id,
                item_id=item_id,
                preview_item_result_id=preview_result_id,
                expected_version=1,
                reason="Race one source-identical reviewed call adoption.",
                retry_key=uuid4(),
                correlation_id=uuid4(),
                source_channel="test",
                now=now,
                authorizer=_IMPORT_AUTHORIZER,
                programme_authorizer=_PROGRAMME_AUTHORIZER,
            )
        except ApplicationsProgrammeImportPreviewStaleError:
            return "stale"
        else:
            return "committed"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(
            commit_worker,
            actor_id=first_manager.id,
            item_id=first_preview.item_id,
            preview_result_id=first_preview.result_id,
        )
        second_future = executor.submit(
            commit_worker,
            actor_id=second_manager.id,
            item_id=second_preview.item_id,
            preview_result_id=second_preview.result_id,
        )
        outcomes = sorted(
            (
                first_future.result(timeout=30),
                second_future.result(timeout=30),
            )
        )

    assert outcomes == ["committed", "stale"]
    bindings = ProgrammeImportSourceBinding.objects.filter(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        source_system="legacy.programme",
        kind=ProgrammeImportItemKind.CALL,
        source_key="programme-call-2027",
    )
    assert bindings.count() == 1
    assert ProgrammeCall.objects.filter(edition_id=edition.id).count() == 1
    items = list(
        ProgrammeImportItem.objects.filter(
            id__in=(first_preview.item_id, second_preview.item_id),
        ).order_by("id")
    )
    assert sorted(item.state for item in items) == [
        ProgrammeImportItemState.APPLIED,
        ProgrammeImportItemState.STAGED,
    ]
    assert sum(item.canonical_payload is None for item in items) == 1


def test_partial_batch_disposal_preserves_applied_call() -> None:
    """Scrub only the staged remainder of a partially applied batch."""

    edition = EventEditionFactory()
    manager = AccountFactory(display_name="Programme manager")
    department = create_department_for_test(
        edition=edition,
        name="Programme",
        expected_code="programme",
    )
    now = timezone.now()
    second_call = deepcopy(_call_item(now, name="Secondary Programme proposals"))
    second_call["source_key"] = "programme-call-secondary-2027"
    second_definition = second_call["definition"]
    assert isinstance(second_definition, dict)
    second_definition["code"] = "programme-call-secondary-2027"
    batch_id = _stage(
        actor=manager,
        edition=edition,
        department_id=department.id,
        payload=_document([_call_item(now), second_call]),
        now=now,
    )
    preview = preview_programme_import(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        batch_id=batch_id,
        expected_batch_version=1,
        reason="Review both calls before applying only one.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
    )
    assert len(preview.items) == 2
    applied_preview = preview.items[0]
    staged_preview = preview.items[1]
    committed = commit_programme_import_call(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=applied_preview.item_id,
        preview_item_result_id=applied_preview.result_id,
        expected_version=1,
        reason="Apply one reviewed call before disposing the remainder.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
        programme_authorizer=_PROGRAMME_AUTHORIZER,
    )
    binding = ProgrammeImportSourceBinding.objects.get(item_id=committed.item_id)
    assert binding.call_id is not None

    discarded = discard_programme_import(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        batch_id=batch_id,
        expected_version=1,
        reason="Dispose only the unapplied private staging remainder.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
    )

    assert discarded.resulting_version == 2
    batch = ProgrammeImportBatch.objects.get(id=batch_id)
    assert batch.state == ProgrammeImportBatchState.DISCARDED
    applied_item = ProgrammeImportItem.objects.get(id=applied_preview.item_id)
    staged_item = ProgrammeImportItem.objects.get(id=staged_preview.item_id)
    assert applied_item.state == ProgrammeImportItemState.APPLIED
    assert staged_item.state == ProgrammeImportItemState.DISCARDED
    assert applied_item.canonical_payload is None
    assert staged_item.canonical_payload is None
    assert ProgrammeCall.objects.filter(id=binding.call_id).exists()
    assert ProgrammeImportSourceBinding.objects.filter(id=binding.id).exists()


def test_preview_replay_requires_current_department_authority() -> None:
    """Do not let retained retry evidence bypass current Department authority."""

    edition = EventEditionFactory()
    manager = AccountFactory(display_name="Former Programme manager")
    department = create_department_for_test(
        edition=edition,
        name="Programme",
        expected_code="programme",
    )
    now = timezone.now()
    batch_id = _stage(
        actor=manager,
        edition=edition,
        department_id=department.id,
        payload=_document([_call_item(now)]),
        now=now,
    )
    retry_key = uuid4()
    reason = "Review the staged Programme items while currently authorized."
    preview_programme_import(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        batch_id=batch_id,
        expected_batch_version=1,
        reason=reason,
        retry_key=retry_key,
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_IMPORT_AUTHORIZER,
    )

    with pytest.raises(ApplicationsProgrammeImportUnavailableError):
        preview_programme_import(
            actor_id=manager.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            batch_id=batch_id,
            expected_batch_version=1,
            reason=reason,
            retry_key=retry_key,
            correlation_id=uuid4(),
            source_channel="test",
            now=now,
            authorizer=_DenyImportTargetAuthorizer(),
        )
