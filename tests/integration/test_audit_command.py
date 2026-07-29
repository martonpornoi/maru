import json
from io import StringIO
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from maru.audit.models import AuditEvent, AuditIntegrityBatch
from maru.audit.services import GENESIS_DIGEST, AuditRecord, append_audit

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _append_probe() -> None:
    append_audit(
        AuditRecord(
            principal_kind="system",
            principal_id=None,
            principal_context_id=None,
            organization_id=None,
            event_edition_id=None,
            capability_code="audit.integrity",
            operation="audit.integrity.probe",
            target_type="audit.integrity",
            target_id=None,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code="test_probe",
            correlation_id=uuid4(),
            source_channel="management_command",
        )
    )


def test_integrity_command_seals_and_reports_machine_readable_state() -> None:
    _append_probe()
    output = StringIO()

    call_command("audit_integrity", "--seal", stdout=output)

    result = json.loads(output.getvalue())
    assert result["valid"] is True
    assert result["sealed_batch"]
    assert result["batch_count"] == 1
    assert result["pending_event_count"] == 0


def test_integrity_command_exits_nonzero_for_invalid_chain() -> None:
    AuditIntegrityBatch.objects.create(
        sequence=2,
        previous_digest=GENESIS_DIGEST,
        digest=GENESIS_DIGEST,
        event_count=0,
    )

    with pytest.raises(CommandError, match="verification failed"):
        call_command("audit_integrity", stdout=StringIO())
