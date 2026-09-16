"""Maintained native custody acceptance; execution is deferred to issue #102.

The fixture exercises the closed owner persistence boundary, not an activated
upload route, a trusted scanner deployment or runtime upload permission.
"""

import hashlib
from dataclasses import replace
from importlib import import_module
from uuid import uuid4

import pytest
from django.apps import apps
from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from maru.applications.models import (
    ApplicationAnswerRevision,
    ApplicationDefinition,
    ApplicationFileReceipt,
    ProgrammeCommandReceipt,
    ProgrammeFileContent,
    ProgrammeFileIntake,
    ProgrammeProposal,
)
from maru.applications.programme_commands import append_programme_proposal_answer
from maru.applications.programme_inputs import ProgrammeCallQuestionType
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


def test_native_file_cannot_be_reused_for_another_proposal_by_the_same_uploader(world):
    _, receipt = _persist(world)
    other = fixtures._start_proposal(world.call, lead=world.lead)
    with pytest.raises(DatabaseError, match="exact proposal, question and uploader"):
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
