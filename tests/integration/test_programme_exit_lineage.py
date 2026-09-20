"""Prove archive-only lineage against real scoped Programme history and audit."""

import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from maru.audit.models import AuditEvent
from maru.authorization.policy import PolicyDecision
from maru.events import programme_exit_queries as event_exit
from maru.identity.models import Account
from maru.programme import (
    archive_authorization,
    archive_generation,
    archive_queries,
    archive_worker,
    exit_lineage_queries,
    exit_owner_queries,
    placement_queries,
)
from maru.programme import queries as programme_queries
from maru.programme.archive_tasks import (
    ProgrammeArchiveScope,
    ProgrammeArchiveUnavailableError,
    cancel_programme_archive,
    request_programme_archive,
)
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.commands import create_organizer_core_item
from maru.programme.exit_archive_protocol import (
    OWNERS,
    ProgrammeArchiveContext,
    encode_programme_exit_archive,
)
from maru.programme.exit_archive_stream import write_programme_exit_archive
from maru.programme.exit_composition import collect_programme_exit
from maru.programme.exit_owner_queries import load_programme_exit_owner
from maru.programme.exit_serialization import serialize_programme_exit_owner
from maru.programme.host_commands import invite_programme_host
from maru.programme.host_inputs import ProgrammeHostInvitationInput
from maru.programme.models import (
    ProgrammeArchiveChunk,
    ProgrammeArchiveTask,
    ProgrammeEditionControl,
    ProgrammeItem,
)
from maru.programme.public_copy_commands import withdraw_programme_public_rendition
from maru.workforce import programme_staffing_queries
from tests.factories import AccountFactory, CapabilityGrantFactory, EventEditionFactory
from tests.integration.test_application_programme_services import _AUTHORIZER
from tests.integration.test_programme_commands import _excluded_module_counts
from tests.integration.test_programme_queries import (
    _create_layered_item,
    _TrustedAuthorizer,
)
from tests.integration.test_scheduling_days import TrustedSchedulingPolicy

pytestmark = pytest.mark.django_db(transaction=True)


def test_native_worker_owns_one_session_lock_and_restores_statement_limits(
    archive_workflow,
):
    from django.db import connection  # noqa: PLC0415

    _, task_id, _, _ = archive_workflow
    with connection.cursor() as cursor:
        cursor.execute("SHOW statement_timeout")
        original = cursor.fetchone()[0]
    assert archive_worker.process_archive_queue_once() == "ready"
    assert ProgrammeArchiveTask.objects.get(id=task_id).state == "ready"
    assert archive_worker.process_archive_queue_once() == "idle"
    with connection.cursor() as cursor:
        cursor.execute("SHOW statement_timeout")
        assert cursor.fetchone()[0] == original


def test_native_worker_cannot_run_alongside_another_archive_child(archive_workflow):
    from django.db import connection  # noqa: PLC0415

    _, task_id, _, _ = archive_workflow
    other = connection.copy(alias="programme_archive_lock_probe")
    try:
        with other.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_lock(hashtextextended(%s, 0))",
                [archive_worker.WORKER_LOCK],
            )
        assert archive_worker.process_archive_queue_once() == "busy"
        assert ProgrammeArchiveTask.objects.get(id=task_id).state == "queued"
    finally:
        other.close()


@pytest.fixture
def archive_workflow(source, monkeypatch):
    request, item, edition = source
    actor = Account.objects.get(id=request["actor_id"])
    for code in (
        "audit.view_security",
        "events.view_basic",
        "venues.view_workspace",
        "workforce.view_shifts",
    ):
        CapabilityGrantFactory(
            principal=actor,
            organization=edition.organization,
            capability_code=code,
            edition=edition if code != "audit.view_security" else None,
        )
    monkeypatch.setattr(
        programme_staffing_queries, "profile_allows_adapter", lambda *_: True
    )

    def collect(**args):
        return collect_programme_exit(
            **args,
            programme_authorizer=request["authorizer"],
            applications_authorizer=_AUTHORIZER,
            scheduling_authorizer=TrustedSchedulingPolicy(),
        )

    for module in (archive_generation, archive_queries):
        monkeypatch.setattr(
            module, "DEFAULT_PROGRAMME_AUTHORIZER", request["authorizer"]
        )
        monkeypatch.setattr(module, "collect_programme_exit", collect)
    scope = ProgrammeArchiveScope(actor.id, edition.organization_id, edition.id)
    task_id = request_programme_archive(
        scope=scope, request_key=uuid4(), authorizer=request["authorizer"]
    )
    return scope, task_id, request, item


def test_background_request_generation_and_private_retrieval_use_real_owner_collection(
    archive_workflow,
):
    scope, task_id, _, item = archive_workflow
    excluded_before = _excluded_module_counts()
    queued = archive_queries.inspect_programme_archive(scope=scope, task_id=task_id)
    assert queued.state == "queued"
    assert queued.chunks == ()
    assert archive_generation.generate_programme_archive(task_id=task_id) == "ready"
    result = archive_queries.inspect_programme_archive(
        scope=scope, task_id=task_id, download=True
    )
    assert result.state == "ready"
    assert result.version == 3
    assert result.size_bytes == sum(map(len, result.chunks))
    with zipfile.ZipFile(io.BytesIO(b"".join(result.chunks))) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        programme = json.loads(archive.read("records/programme.json"))
    assert programme["items"][0]["lineage"]["item_id"] == str(item.id)
    assert manifest["scope"]["requester_id"] == str(scope.actor_id)
    assert (
        AuditEvent.objects.filter(operation="programme.exit.task.download").count() == 1
    )
    assert archive_generation.generate_programme_archive(task_id=task_id) == "skipped"
    assert _excluded_module_counts() == excluded_before


def test_cancelled_claim_cannot_publish_bytes_when_generation_resumes(archive_workflow):
    scope, task_id, request, item = archive_workflow
    assert archive_generation._claim(scope, task_id)
    cancel_programme_archive(
        scope=scope,
        task_id=task_id,
        expected_version=2,
        authorizer=request["authorizer"],
    )
    with pytest.raises(ProgrammeArchiveUnavailableError):
        archive_generation._generate(scope, task_id)
    assert ProgrammeArchiveTask.objects.get(id=task_id).state == "cancelled"
    assert not ProgrammeArchiveChunk.objects.filter(task_id=task_id).exists()
    assert ProgrammeItem.objects.filter(id=item.id).exists()


def test_retrieval_rechecks_an_independent_owner_after_success(
    archive_workflow, monkeypatch
):
    from django.core.exceptions import PermissionDenied  # noqa: PLC0415

    scope, task_id, _, _ = archive_workflow
    assert archive_generation.generate_programme_archive(task_id=task_id) == "ready"
    monkeypatch.setattr(
        event_exit,
        "decide_verified_principal_exact_edition",
        lambda **_: PolicyDecision(
            allowed=False,
            fields=frozenset(),
            obligations=frozenset(),
            reason_code="synthetic_revocation",
        ),
    )
    with pytest.raises(PermissionDenied):
        archive_queries.inspect_programme_archive(
            scope=scope, task_id=task_id, download=True
        )
    assert not AuditEvent.objects.filter(
        operation="programme.exit.task.download"
    ).exists()


def test_private_task_read_audit_outage_withholds_all_bytes(
    archive_workflow, monkeypatch
):
    scope, task_id, _, _ = archive_workflow
    assert archive_generation.generate_programme_archive(task_id=task_id) == "ready"

    def unavailable(*_, **__):
        raise RuntimeError("PRIVATE synthetic audit outage")

    monkeypatch.setattr(archive_queries, "append_audit", unavailable)
    with pytest.raises(RuntimeError, match="synthetic audit"):
        archive_queries.inspect_programme_archive(
            scope=scope, task_id=task_id, download=True
        )
    assert not AuditEvent.objects.filter(
        operation="programme.exit.task.download"
    ).exists()


@pytest.mark.parametrize("fault", ["source", "partial_sink", "resource"])
def test_background_failure_never_commits_partial_custody(
    archive_workflow, monkeypatch, fault
):
    _, task_id, _, _ = archive_workflow

    def fail(**args):
        if fault == "partial_sink":
            args["sink"].write(b"x" * 1_048_576)
        if fault == "resource":
            raise MemoryError
        raise RuntimeError("PRIVATE synthetic source outage")

    monkeypatch.setattr(
        archive_generation,
        "collect_programme_exit"
        if fault == "source"
        else "write_programme_exit_archive",
        fail,
    )
    assert archive_generation.generate_programme_archive(task_id=task_id) == "failed"
    task = ProgrammeArchiveTask.objects.get(id=task_id)
    assert task.failure_code == (
        "resource_limit" if fault == "resource" else "source_unavailable"
    )
    assert task.version == 3
    assert not ProgrammeArchiveChunk.objects.filter(task_id=task_id).exists()
    assert not AuditEvent.objects.filter(reason_code__contains="PRIVATE").exists()


def test_background_claim_denial_fails_closed_without_reading_sources(
    archive_workflow, monkeypatch
):
    _, task_id, _, _ = archive_workflow
    monkeypatch.setattr(
        archive_authorization, "profile_allows_adapter", lambda *_: False
    )
    assert archive_generation.generate_programme_archive(task_id=task_id) == "failed"
    assert ProgrammeArchiveTask.objects.get(id=task_id).version == 2
    assert not AuditEvent.objects.filter(
        operation="programme.query.exit_owner"
    ).exists()


def test_retrieval_rejects_source_drift_independent_of_original_success(
    archive_workflow,
):
    scope, task_id, request, item = archive_workflow
    assert archive_generation.generate_programme_archive(task_id=task_id) == "ready"
    rendition = item.public_renditions.get()
    withdraw_programme_public_rendition(
        **{
            key: value
            for key, value in request.items()
            if key not in {"reason", "item_id"}
        },
        item_id=item.id,
        rendition_id=rendition.id,
        idempotency_key=uuid4(),
        expected_version=item.aggregate_version,
        source_channel="programme-exit",
        reason="Synthetic withdrawal after generation",
    )
    with pytest.raises(ProgrammeArchiveUnavailableError):
        archive_queries.inspect_programme_archive(
            scope=scope, task_id=task_id, download=True
        )
    assert not AuditEvent.objects.filter(
        operation="programme.exit.task.download"
    ).exists()
    current = archive_queries.inspect_programme_archive(scope=scope, task_id=task_id)
    assert current.source_changed
    assert current.size_bytes == 0
    assert current.chunks == ()


def test_retrieval_rechecks_actual_disclosure_expiry_after_verifying_chunks(
    archive_workflow,
    monkeypatch,
):
    scope, task_id, _, _ = archive_workflow
    assert archive_generation.generate_programme_archive(task_id=task_id) == "ready"
    task = ProgrammeArchiveTask.objects.get(id=task_id)
    instants = iter((task.requested_at, task.expires_at))
    monkeypatch.setattr(archive_queries, "_now", lambda: next(instants))
    with pytest.raises(ProgrammeArchiveUnavailableError):
        archive_queries.inspect_programme_archive(
            scope=scope, task_id=task_id, download=True
        )
    assert not AuditEvent.objects.filter(
        operation="programme.exit.task.download"
    ).exists()


def test_crashed_worker_deadline_disposes_only_derived_custody(
    archive_workflow, monkeypatch
):
    scope, task_id, _, item = archive_workflow
    assert archive_generation._claim(scope, task_id)
    assert not archive_generation.dispose_due_programme_archive(task_id=task_id)
    task = ProgrammeArchiveTask.objects.get(id=task_id)
    monkeypatch.setattr(
        archive_generation, "_now", lambda: task.started_at + timedelta(minutes=21)
    )
    assert archive_generation.dispose_due_programme_archive(task_id=task_id)
    task.refresh_from_db()
    assert task.state == "failed"
    assert task.failure_code == "worker_deadline"
    assert ProgrammeItem.objects.filter(id=item.id).exists()
    assert not archive_generation.dispose_due_programme_archive(task_id=task_id)


def test_native_all_eight_owner_sections_compose_with_actual_independent_grants(
    source, monkeypatch
):
    request, item, edition = source
    actor = Account.objects.get(id=request["actor_id"])
    for code in (
        "audit.view_security",
        "events.view_basic",
        "venues.view_workspace",
        "workforce.view_shifts",
    ):
        CapabilityGrantFactory(
            principal=actor,
            organization=edition.organization,
            capability_code=code,
            edition=edition if code != "audit.view_security" else None,
        )
    monkeypatch.setattr(
        programme_staffing_queries, "profile_allows_adapter", lambda *_: True
    )
    args = {
        "actor_id": actor.id,
        "organization_id": edition.organization_id,
        "edition_id": edition.id,
        "correlation_id": uuid4(),
        "programme_authorizer": request["authorizer"],
        "applications_authorizer": _AUTHORIZER,
        "scheduling_authorizer": TrustedSchedulingPolicy(),
    }
    result = collect_programme_exit(**args)
    assert {row.owner for row in result.sections} == set(OWNERS)
    assert result.files == ()
    assert len(result.source_digest) == 64
    content = {row.owner: json.loads(row.data) for row in result.sections}
    assert content["programme"]["items"][0]["lineage"]["item_id"] == str(item.id)
    assert len(content["audit"]["receipts"]) == 8  # Venue source and final read.
    archive = encode_programme_exit_archive(
        context=ProgrammeArchiveContext(
            edition.organization_id,
            edition.id,
            actor.id,
            args["correlation_id"],
            datetime.now(UTC),
        ),
        sections=result.sections,
        files=result.files,
    )
    assert archive.startswith(b"PK")
    private_sink = io.BytesIO()
    encoded = write_programme_exit_archive(
        context=ProgrammeArchiveContext(
            edition.organization_id,
            edition.id,
            actor.id,
            args["correlation_id"],
            datetime.now(UTC),
        ),
        sections=result.sections,
        files=result.files,
        source_digest=result.source_digest,
        sink=private_sink,
    )
    assert encoded.size_bytes == len(private_sink.getvalue())
    with zipfile.ZipFile(private_sink) as background_archive:
        manifest = json.loads(background_archive.read("manifest.json"))
    assert manifest["profile"] == {"code": "full_convention", "version": 1}
    assert manifest["source_digest"] == result.source_digest
    fresh = collect_programme_exit(**{**args, "correlation_id": uuid4()})
    assert fresh.source_digest == result.source_digest
    assert (
        fresh.sections[-1].data != result.sections[-1].data
    )  # Fresh audit, same sources.


def test_native_events_archive_uses_real_configuration_and_independent_fields(
    source, monkeypatch
):
    request, _item, edition = source
    source_policy = PolicyDecision(
        allowed=True,
        fields=event_exit._FIELDS,
        obligations=frozenset(),
        reason_code="sealed_future_profile_harness",
    )
    monkeypatch.setattr(
        event_exit, "decide_verified_principal_exact_edition", lambda **_: source_policy
    )
    section = event_exit.load_programme_exit_configuration(
        actor_id=request["actor_id"],
        organization_id=edition.organization_id,
        edition_id=edition.id,
        correlation_id=request["correlation_id"],
        programme_authorizer=request["authorizer"],
    )
    document = json.loads(section.data)
    assert document["id"] == str(edition.id)
    assert document["time_zone"] == edition.time_zone
    assert document["starts_on"] == edition.starts_on.isoformat()
    assert document["aggregate_version"] == edition.aggregate_version
    assert "currency_codes" not in document
    audit = AuditEvent.objects.get(
        operation="events.query.programme_exit", outcome="allow"
    )
    assert audit.event_edition_id == edition.id


def test_native_events_source_policy_is_not_replaced_by_archive_authorizer(source):
    from django.core.exceptions import PermissionDenied  # noqa: PLC0415

    request, _item, edition = source
    with pytest.raises(PermissionDenied):
        event_exit.load_programme_exit_configuration(
            actor_id=request["actor_id"],
            organization_id=edition.organization_id,
            edition_id=edition.id,
            correlation_id=request["correlation_id"],
            programme_authorizer=request["authorizer"],
        )
    assert not AuditEvent.objects.filter(
        operation="events.query.programme_exit", outcome="allow"
    ).exists()


def test_native_multi_item_host_set_is_locked_before_any_child_audit(
    source, monkeypatch
):
    request, original_item, edition = source
    common = {
        key: request[key]
        for key in (
            "actor_id",
            "organization_id",
            "edition_id",
            "correlation_id",
            "authorizer",
        )
    }
    created = create_organizer_core_item(
        **common,
        kind="announcement",
        internal_title="Second synthetic item",
        working_summary="Synthetic",
        expected_version=ProgrammeEditionControl.objects.get(
            edition_id=edition.id
        ).aggregate_version,
        reason="Exercise complete person closure",
        idempotency_key=uuid4(),
        source_channel="programme-exit",
    )
    items = sorted(
        [original_item, ProgrammeItem.objects.get(id=created.item_id)],
        key=lambda item: item.id,
    )
    people = [AccountFactory(id=UUID(int=2**128 - 1)), AccountFactory(id=UUID(int=1))]
    for item, person in zip(items, people, strict=True):
        invite_programme_host(
            **common,
            item_id=item.id,
            invitation=ProgrammeHostInvitationInput(
                person.id,
                "host",
                "Synthetic invitation",
                "PRIVATE invitation-only secret",
                item.aggregate_version,
            ),
            reason="Exercise reversed item/person ordering",
            idempotency_key=uuid4(),
        )
    expected = tuple(sorted({request["actor_id"], *(person.id for person in people)}))
    original_lock = exit_owner_queries.lock_account_references_for_evidence
    original_audit = programme_queries._append_query_audit
    locked, audited = [], []

    def lock(*, account_ids):
        result = original_lock(account_ids=account_ids)
        locked.append(result)
        assert result == expected
        return result

    def audit(**kwargs):
        assert locked == [expected]
        audited.append(kwargs["operation"])
        return original_audit(**kwargs)

    monkeypatch.setattr(
        exit_owner_queries, "lock_account_references_for_evidence", lock
    )
    monkeypatch.setattr(programme_queries, "_append_query_audit", audit)
    result = load_programme_exit_owner(**common, reason=request["reason"])
    assert len(result.items) == 2
    assert audited[-1] == "programme.query.exit_owner"
    section = serialize_programme_exit_owner(result)
    assert b"PRIVATE invitation-only secret" not in section.data
    assert all(len(entry.content.roster.entries) == 1 for entry in result.items)


def test_native_complete_programme_owner_composes_actual_readers(source):
    request, item, _edition = source
    result = load_programme_exit_owner(
        **{key: value for key, value in request.items() if key != "item_id"}
    )
    assert len(result.items) == 1
    entry = result.items[0]
    assert entry.lineage.item_id == entry.content.core.private.item.id == item.id
    assert (
        entry.lineage.item_version == entry.content.core.private.item.aggregate_version
    )
    assert len(entry.content.core.working) == 1
    assert entry.content.roster.entries == entry.content.staffing.requirements == ()
    assert entry.placements == ()
    audit = AuditEvent.objects.get(
        operation="programme.query.exit_owner", outcome="allow"
    )
    assert audit.safe_metadata["target_count"] == 1
    assert "PRIVATE" not in repr(result)
    section = serialize_programme_exit_owner(result)
    document = json.loads(section.data)
    assert document["items"][0]["content"]["core"]["working"][0]["internal_title"] == (
        "PRIVATE unreleased announcement"
    )
    assert document["items"][0]["lineage"]["item_id"] == str(item.id)
    assert "PRIVATE" not in repr(section)


@pytest.fixture
def source(monkeypatch):
    from maru.effects import services  # noqa: PLC0415

    # A dormant candidate fixture, not activation or a production-policy bypass.
    monkeypatch.setattr(services, "require_effect_delivery_allowed", lambda **_: None)
    monkeypatch.setattr(
        archive_authorization, "profile_allows_adapter", lambda *_: True
    )
    monkeypatch.setattr(placement_queries, "profile_allows_adapter", lambda *_: True)
    actor, edition, policy = (
        AccountFactory(),
        EventEditionFactory(),
        _TrustedAuthorizer(),
    )
    item = _create_layered_item(actor_id=actor.id, edition=edition, authorizer=policy)
    request = {
        "actor_id": actor.id,
        "organization_id": edition.organization_id,
        "edition_id": edition.id,
        "item_id": item.id,
        "correlation_id": uuid4(),
        "reason": "Inspect synthetic Programme lineage",
        "authorizer": policy,
    }
    return request, item, edition


def test_native_lineage_retains_exact_sources_without_private_contents(source):
    request, item, _edition = source
    snapshot = exit_lineage_queries.load_programme_exit_lineage(**request)
    groups = {group.name: group for group in snapshot.collections}
    assert snapshot.item_id == item.id
    assert snapshot.item_version == item.aggregate_version
    assert groups["source_bindings"].rows == (
        (item.source_binding.id, "programme.source.organizer-core@1", None, None),
    )
    working = item.working_revisions.get(sequence=1)
    rendition = item.public_renditions.get(rendition_number=1)
    assert groups["working"].rows == ((working.id, 1, 1),)
    assert groups["renditions"].rows == ((rendition.id, 1, 1, working.id, None),)
    assert groups["withdrawals"].rows == ()
    assert len(groups["readiness_revisions"].rows) == 1
    assert len(groups["readiness_evidence"].rows) == 1
    assert "PRIVATE" not in str(tuple(group.rows for group in snapshot.collections))
    audit = AuditEvent.objects.get(
        operation="programme.query.exit_lineage",
        correlation_id=request["correlation_id"],
        outcome="allow",
    )
    assert audit.safe_metadata["target_count"] == sum(
        len(group.rows) for group in snapshot.collections
    )
    assert "PRIVATE" not in repr(audit.safe_metadata)


def test_independent_withdrawal_is_not_lost_behind_item_version(source):
    request, item, _edition = source
    rendition = item.public_renditions.get()
    withdraw_programme_public_rendition(
        **{
            key: value
            for key, value in request.items()
            if key not in {"reason", "item_id"}
        },
        item_id=item.id,
        rendition_id=rendition.id,
        expected_version=item.aggregate_version,
        reason="Withdraw synthetic copy",
        idempotency_key=uuid4(),
        source_channel="programme-exit",
    )
    snapshot = exit_lineage_queries.load_programme_exit_lineage(**request)
    withdrawals = next(
        group for group in snapshot.collections if group.name == "withdrawals"
    )
    retained = item.public_copy_withdrawals.get()
    assert withdrawals.rows == ((retained.id, rendition.id, retained.item_version),)
    item.refresh_from_db()
    assert snapshot.item_version == item.aggregate_version


@pytest.mark.parametrize("wrong", ["item", "edition", "tenant"])
def test_native_wrong_scope_never_discovers_lineage(source, wrong):
    request, _item, edition = source
    if wrong == "item":
        request["item_id"] = uuid4()
    else:
        foreign = (
            EventEditionFactory(series=edition.series)
            if wrong == "edition"
            else EventEditionFactory()
        )
        request.update(organization_id=foreign.organization_id, edition_id=foreign.id)
    with pytest.raises(programme_queries.ProgrammeQueryUnavailableError):
        exit_lineage_queries.load_programme_exit_lineage(**request)
    assert not AuditEvent.objects.filter(
        operation="programme.query.exit_lineage"
    ).exists()


@pytest.mark.parametrize("adapter", [archive_authorization, placement_queries])
def test_native_dormant_or_revoked_adapter_refuses_lineage(
    source, monkeypatch, adapter
):
    request, _item, _edition = source
    monkeypatch.setattr(adapter, "profile_allows_adapter", lambda *_: False)
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        exit_lineage_queries.load_programme_exit_lineage(**request)
    assert not AuditEvent.objects.filter(
        operation="programme.query.exit_lineage", outcome="allow"
    ).exists()


def test_native_failed_audit_withholds_source_and_rolls_back(source, monkeypatch):
    request, _item, _edition = source

    def fail(**_kwargs):
        raise RuntimeError("synthetic lineage audit failure")

    monkeypatch.setattr(programme_queries, "_append_query_audit", fail)
    with pytest.raises(RuntimeError, match="synthetic lineage audit failure"):
        exit_lineage_queries.load_programme_exit_lineage(**request)
    assert not AuditEvent.objects.filter(
        operation="programme.query.exit_lineage"
    ).exists()
