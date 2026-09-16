"""Maintained native custody acceptance; execution is deferred to issue #102.

The fixture exercises the closed owner persistence boundary, not an activated
upload route, a trusted scanner deployment or runtime upload permission.
"""

import hashlib
from dataclasses import replace
from importlib import import_module
from unittest.mock import Mock
from uuid import uuid4

import pytest
from django.apps import apps
from django.conf import settings
from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from maru.applications import programme_file_commands as file_commands
from maru.applications.models import (
    ApplicationAnswerRevision,
    ApplicationDefinition,
    ApplicationFileReceipt,
    ProgrammeCommandReceipt,
    ProgrammeFileContent,
    ProgrammeFileIntake,
    ProgrammeProposal,
)
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError,
)
from maru.applications.programme_commands import (
    ApplicationsProgrammeIdempotencyConflictError,
    ApplicationsProgrammeUnavailableError,
    ApplicationsProgrammeVersionConflictError,
    append_programme_proposal_answer,
    revise_programme_proposal_selection,
)
from maru.applications.programme_inputs import (
    ProgrammeCallQuestionType,
    ProgrammeProposalSelectionInput,
)
from maru.applications.programme_reference_sources import (
    ProgrammeAnswerReferenceIntent,
    ProgrammeAnswerReferenceRequest,
)
from maru.applications.programme_writer_boundary import (
    programme_application_database_writer,
)
from maru.applications.readiness import applications_database_integrity_is_ready
from tests.integration import test_application_programme_services as fixtures
from tests.integration.test_application_programme_services import (
    _admit_future_programme_effects,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.django_db(transaction=True),
    pytest.mark.usefixtures(_admit_future_programme_effects.__name__),
]
PDF = b"%PDF-1.7\nSynthetic file-custody fixture only.\n%%EOF\n"


@pytest.fixture
def world(monkeypatch):
    original = fixtures._definition

    def definition(now, *, code):
        result = original(now, code=code)
        section = result.sections[0]
        question = replace(
            section.questions[0],
            field_type=ProgrammeCallQuestionType.SAFE_FILE,
            minimum_length=None,
            maximum_length=None,
        )
        return replace(result, sections=(replace(section, questions=(question,)),))

    monkeypatch.setattr(fixtures, "_definition", definition)
    return fixtures._start_proposal(fixtures._active_call(code="private-file-custody"))


def _answer(world, receipt_id, retry_key, *, version=None):
    return append_programme_proposal_answer(
        actor_id=world.lead.id,
        organization_id=world.call.edition.organization_id,
        edition_id=world.call.edition.id,
        proposal_id=world.proposal_id,
        question_id=world.call.question_id,
        value=str(receipt_id),
        expected_version=world.version if version is None else version,
        expected_call_version=2,
        expected_definition_version=1,
        reason="Use the synthetic supporting file.",
        retry_key=retry_key,
        correlation_id=uuid4(),
        source_channel="test",
        authorizer=fixtures._AUTHORIZER,
    )


def _persist(
    world, *, omit=None, content=PDF, intake_changes=None, receipt_changes=None
):
    """Create exact owner evidence atomically; this is not a public upload service."""
    intake_id, retry_key = uuid4(), uuid4()
    definition = ApplicationDefinition.objects.get(id=world.call.definition_id)
    receipt_values = {
        "organization_id": world.call.edition.organization_id,
        "edition_id": world.call.edition.id,
        "account_id": world.lead.id,
        "status": "clean",
        "sha256": hashlib.sha256(PDF).hexdigest(),
        "size_bytes": len(PDF),
        "media_type": "application/pdf",
        "storage_key": f"programme-db/{intake_id}",
        "scanner_receipt": "clamav-instream@1",
    }
    receipt_values.update(receipt_changes or {})
    with transaction.atomic(), programme_application_database_writer():
        receipt = ApplicationFileReceipt.objects.create(**receipt_values)
        values = {
            "id": intake_id,
            "organization_id": world.call.edition.organization_id,
            "edition_id": world.call.edition.id,
            "actor_id": world.lead.id,
            "proposal_id": world.proposal_id,
            "question_id": world.call.question_id,
            "file_receipt": receipt,
            "source_version": world.version,
            "call_version": definition.aggregate_version,
            "definition_version": definition.version,
            "retry_key": retry_key,
            "scanned_at": timezone.now(),
        }
        values.update(intake_changes or {})
        intake = ProgrammeFileIntake(**values)
        # Bypass ORM validation intentionally so negatives reach PostgreSQL guards.
        ProgrammeFileIntake.objects.bulk_create([intake])
        if omit != "content":
            ProgrammeFileContent.objects.bulk_create(
                [ProgrammeFileContent(intake=intake, payload=content)]
            )
        if omit != "answer":
            _answer(
                world, receipt.id, uuid4() if omit == "matching_retry" else retry_key
            )
    return intake, receipt


def test_native_custody_commits_only_with_exact_first_answer_and_canonical_receipt(
    world,
):
    intake, receipt = _persist(world)
    answer = ApplicationAnswerRevision.objects.get(value=str(receipt.id))
    command = ProgrammeCommandReceipt.objects.get(target_id=answer.id)
    assert command.retry_key == intake.retry_key
    assert command.resulting_version == world.version + 1
    assert bytes(ProgrammeFileContent.objects.get(intake=intake).payload) == PDF
    assert (
        ProgrammeProposal.objects.get(id=world.proposal_id).submission.aggregate_version
        == world.version + 1
    )
    reused = _answer(world, receipt.id, uuid4(), version=world.version + 1)
    assert reused.resulting_version == world.version + 2
    assert ProgrammeFileIntake.objects.count() == 1
    assert applications_database_integrity_is_ready()


@pytest.mark.parametrize("omit", ["content", "answer", "matching_retry"])
def test_native_deferred_custody_rejects_partial_commit_and_rolls_back(world, omit):
    with pytest.raises(DatabaseError, match="atomic content"):
        _persist(world, omit=omit)
    assert not ProgrammeFileIntake.objects.exists()
    assert not ProgrammeFileContent.objects.exists()
    assert not ApplicationFileReceipt.objects.exists()
    assert (
        ProgrammeProposal.objects.get(id=world.proposal_id).submission.aggregate_version
        == world.version
    )


@pytest.mark.parametrize(
    "field",
    [
        "organization_id",
        "edition_id",
        "actor_id",
        "proposal_id",
        "question_id",
        "source_version",
        "call_version",
        "definition_version",
    ],
)
def test_native_intake_rejects_wrong_scope_actor_question_or_cursor(world, field):
    value = 99 if field.endswith("version") else uuid4()
    with pytest.raises(DatabaseError):
        _persist(world, intake_changes={field: value})
    assert not ProgrammeFileIntake.objects.exists()
    assert not ApplicationFileReceipt.objects.exists()


@pytest.mark.parametrize(
    "content", [b"", PDF + b"extra", PDF.replace(b"fixture", b"changed")]
)
def test_native_content_rejects_length_or_digest_mismatch(world, content):
    with pytest.raises(DatabaseError, match="exact receipt evidence"):
        _persist(world, content=content)
    assert not ProgrammeFileContent.objects.exists()
    assert not ApplicationFileReceipt.objects.exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "rejected"},
        {"media_type": "text/plain"},
        {"scanner_receipt": "untrusted"},
        {"size_bytes": 10485761},
        {"storage_key": "another-provider/object"},
    ],
)
def test_native_intake_rejects_generic_receipt_without_exact_scan_and_custody(
    world, changes
):
    with pytest.raises(DatabaseError, match="exact current private purpose"):
        _persist(world, receipt_changes=changes)
    assert not ApplicationFileReceipt.objects.exists()


def test_native_reserved_receipt_cannot_commit_without_intake(world):
    with (
        pytest.raises(DatabaseError, match="exact private custody"),
        transaction.atomic(),
    ):
        ApplicationFileReceipt.objects.create(
            organization_id=world.call.edition.organization_id,
            edition_id=world.call.edition.id,
            account_id=world.lead.id,
            status="clean",
            sha256=hashlib.sha256(PDF).hexdigest(),
            size_bytes=len(PDF),
            media_type="application/pdf",
            storage_key=f"programme-db/{uuid4()}",
            scanner_receipt="clamav-instream@1",
        )
    assert not ApplicationFileReceipt.objects.exists()


@pytest.mark.parametrize("native_guard", [False, True])
def test_native_file_cannot_be_reused_for_another_proposal_by_the_same_uploader(
    monkeypatch,
    world,
    native_guard,
):
    _, receipt = _persist(world)
    other = fixtures._start_proposal(world.call, lead=world.lead)
    if native_guard:
        # Bypass only the Python convenience check to retain native guard proof.
        # Never disable a database trigger or runtime permission boundary.
        monkeypatch.setattr(
            file_commands.commands, "_require_registered_reference", Mock()
        )
    with pytest.raises(
        DatabaseError if native_guard else ApplicationsProgrammeUnavailableError
    ):
        _answer(other, receipt.id, uuid4())
    assert (
        ProgrammeProposal.objects.get(id=other.proposal_id).submission.aggregate_version
        == other.version
    )


@pytest.mark.parametrize("kind", ["intake", "content"])
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_native_custody_rejects_mutation_even_with_owner_latch(world, kind, operation):
    _persist(world)
    sql = {
        ("intake", "UPDATE"): (
            "UPDATE public.applications_programmefileintake SET updated_at = updated_at"
        ),
        ("content", "UPDATE"): (
            "UPDATE public.applications_programmefilecontent "
            "SET updated_at = updated_at"
        ),
        ("intake", "DELETE"): "DELETE FROM public.applications_programmefileintake",
        ("content", "DELETE"): "DELETE FROM public.applications_programmefilecontent",
    }[kind, operation]
    with (
        pytest.raises(DatabaseError),
        transaction.atomic(),
        programme_application_database_writer(),
        connection.cursor() as cursor,
    ):
        cursor.execute(sql)
    assert (
        ProgrammeFileIntake.objects.count() == ProgrammeFileContent.objects.count() == 1
    )


def test_populated_file_fence_preserves_bytes_and_guards(world):
    _persist(world)
    module = import_module(
        "maru.applications.migrations.0021_programme_file_downgrade_fence"
    )
    with (
        pytest.raises(RuntimeError, match="fix forward"),
        transaction.atomic(),
        connection.schema_editor() as editor,
    ):
        module.refuse_populated_programme_file_downgrade(apps, editor)
    assert ProgrammeFileContent.objects.count() == 1
    assert applications_database_integrity_is_ready()


@pytest.mark.usefixtures("restores_current_migration_graph")
def test_unused_file_schema_reverses_and_reinstalls_exact_readiness():
    executor = MigrationExecutor(connection)
    current = executor.loader.graph.leaf_nodes()
    executor.migrate([("applications", "0018_programme_conversion_downgrade_fence")])
    assert not applications_database_integrity_is_ready()
    MigrationExecutor(connection).migrate(current)
    assert applications_database_integrity_is_ready()


@pytest.fixture
def command_scanner(monkeypatch):
    """Mock transport only; never claim a real scanner or deployment proof."""
    monkeypatch.setattr(settings, "MARU_PROGRAMME_FILE_SCANNER", "clamav")
    monkeypatch.setattr(settings, "MARU_PROGRAMME_FILE_SCANNER_HOST", "127.0.0.1")

    def scan(data, _endpoint):
        assert data == PDF
        assert not connection.in_atomic_block

    scanner = Mock(side_effect=scan)
    monkeypatch.setattr(file_commands.preparation, "_scan", scanner)
    return scanner


def _command_context(world):
    return (
        ProgrammeAnswerReferenceRequest(
            world.lead.id,
            world.call.edition.organization_id,
            world.call.edition.id,
            world.proposal_id,
            world.call.question_id,
            uuid4(),
            "test",
        ),
        ProgrammeAnswerReferenceIntent(world.version, 2, 1, uuid4()),
    )


def test_native_upload_command_and_body_free_result_preserve_one_canonical_answer(
    world, command_scanner
):
    request, intent = _command_context(world)
    reader = Mock(return_value=PDF)
    result = file_commands.upload_and_use_programme_file(
        request=request,
        intent=intent,
        read_bytes=reader,
        authorizer=fixtures._AUTHORIZER,
    )
    assert not result.replayed
    assert result.resulting_version == world.version + 1
    intake = ProgrammeFileIntake.objects.get(proposal_id=world.proposal_id)
    assert bytes(ProgrammeFileContent.objects.get(intake=intake).payload) == PDF
    replay = file_commands.get_programme_file_upload_result(
        request=request,
        intent=intent,
        authorizer=fixtures._AUTHORIZER,
    )
    assert replay.replayed
    assert replay.receipt_id == result.receipt_id
    assert (
        ApplicationAnswerRevision.objects.filter(
            value=str(intake.file_receipt_id)
        ).count()
        == 1
    )
    reader.assert_called_once_with()
    command_scanner.assert_called_once()
    replacement = Mock(return_value=b"different file must not be read")
    with pytest.raises(ApplicationsProgrammeIdempotencyConflictError):
        file_commands.upload_and_use_programme_file(
            request=request,
            intent=intent,
            read_bytes=replacement,
            authorizer=fixtures._AUTHORIZER,
        )
    replacement.assert_not_called()
    assert ProgrammeFileIntake.objects.count() == 1
    with pytest.raises(ApplicationsProgrammeIdempotencyConflictError):
        file_commands.get_programme_file_upload_result(
            request=request,
            intent=replace(intent, expected_version=result.resulting_version),
            authorizer=fixtures._AUTHORIZER,
        )


def test_native_upload_cross_scope_denial_happens_before_body_and_scanner(
    world, command_scanner
):
    request, intent = _command_context(world)
    reader = Mock(return_value=PDF)
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        file_commands.upload_and_use_programme_file(
            request=replace(request, organization_id=uuid4()),
            intent=intent,
            read_bytes=reader,
            authorizer=fixtures._AUTHORIZER,
        )
    reader.assert_not_called()
    command_scanner.assert_not_called()
    assert not ApplicationFileReceipt.objects.exists()


def test_native_scan_does_not_hold_transaction_and_changed_source_leaves_no_custody(
    world, command_scanner
):
    request, intent = _command_context(world)

    def competing_edit(_data, _endpoint):
        assert not connection.in_atomic_block
        revise_programme_proposal_selection(
            actor_id=world.lead.id,
            organization_id=world.call.edition.organization_id,
            edition_id=world.call.edition.id,
            proposal_id=world.proposal_id,
            selection=ProgrammeProposalSelectionInput(
                track_id=world.call.track_id,
                format_id=world.call.format_id,
                requested_duration_minutes=90,
            ),
            expected_version=world.version,
            reason="Concurrent synthetic edit.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            authorizer=fixtures._AUTHORIZER,
        )

    command_scanner.side_effect = competing_edit
    with pytest.raises(ApplicationsProgrammeVersionConflictError):
        file_commands.upload_and_use_programme_file(
            request=request,
            intent=intent,
            read_bytes=lambda: PDF,
            authorizer=fixtures._AUTHORIZER,
        )
    assert not ProgrammeFileIntake.objects.exists()
    assert not ProgrammeFileContent.objects.exists()
    assert not ApplicationFileReceipt.objects.exists()
    assert (
        ProgrammeProposal.objects.get(id=world.proposal_id).submission.aggregate_version
        == world.version + 1
    )


def test_native_first_answer_failure_rolls_back_all_private_bytes_and_evidence(
    monkeypatch, world, command_scanner
):
    request, intent = _command_context(world)
    before = ProgrammeCommandReceipt.objects.count()
    monkeypatch.setattr(
        file_commands.commands,
        "append_programme_proposal_answer",
        Mock(side_effect=RuntimeError("Synthetic canonical answer failure")),
    )
    with pytest.raises(RuntimeError, match="Synthetic canonical answer failure"):
        file_commands.upload_and_use_programme_file(
            request=request,
            intent=intent,
            read_bytes=lambda: PDF,
            authorizer=fixtures._AUTHORIZER,
        )
    assert not ProgrammeFileIntake.objects.exists()
    assert not ProgrammeFileContent.objects.exists()
    assert not ApplicationFileReceipt.objects.exists()
    assert ProgrammeCommandReceipt.objects.count() == before
    assert (
        ProgrammeProposal.objects.get(id=world.proposal_id).submission.aggregate_version
        == world.version
    )
