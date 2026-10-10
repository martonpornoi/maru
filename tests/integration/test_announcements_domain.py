"""Exact native announcement workflow, authority and retained-copy evidence."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import (
    DatabaseError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from psycopg import sql

from maru.announcements import authorization, commands, queries
from maru.announcements.contracts import (
    AnnouncementCommandRequest,
    AnnouncementDraftInput,
    AnnouncementReadRequest,
    AnnouncementSettingsInput,
    AnnouncementVariantInput,
    ManualChannel,
)
from maru.announcements.errors import (
    AnnouncementDeniedError,
    AnnouncementError,
    AnnouncementIdempotencyConflictError,
    AnnouncementSettingsRequiredError,
    AnnouncementStateConflictError,
    AnnouncementVersionConflictError,
)
from maru.announcements.models import (
    Announcement,
    AnnouncementCommandReceipt,
    AnnouncementControl,
    AnnouncementPublicationReport,
    AnnouncementReview,
    AnnouncementRevision,
    AnnouncementSettingsRevision,
    AnnouncementVariant,
)
from maru.announcements.readiness import announcements_database_integrity_is_ready
from maru.audit.models import AuditEvent
from maru.authorization.commands import grant_capability_direct
from maru.authorization.policy import resolve_edition_target
from maru.effects.models import DomainEvent, OutboxMessage
from maru.organizations.models import OrganizationRepresentation
from tests.factories import AccountFactory
from tests.integration.test_announcements_adoption import setup_announcements
from tests.integration.test_workforce_only_adoption import _activate_maru_operators

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def native(call, *args, **kwargs):
    """Evaluate deferred owning graph constraints at each command boundary."""
    with transaction.atomic():
        result = call(*args, **kwargs)
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute("SET CONSTRAINTS ALL DEFERRED")
        return result


@pytest.fixture
def world(proves_safe_runtime_database_role):
    administrator, _key, result = setup_announcements()
    representation = OrganizationRepresentation.objects.get(id=result.representation_id)
    appointments = _activate_maru_operators(administrator, representation)
    return administrator, result, appointments[0].account, appointments[1].account


def request(world, actor=None):
    _administrator, scope, writer, _reviewer = world
    return AnnouncementCommandRequest(
        actor_id=(actor or writer).id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        correlation_id=uuid4(),
        idempotency_key=uuid4(),
        source_channel="test",
    )


def read_request(world, actor=None):
    value = request(world, actor)
    return AnnouncementReadRequest(
        value.actor_id, value.organization_id, value.edition_id, value.correlation_id
    )


def rules(**changes):
    return replace(
        AnnouncementSettingsInput(
            policy_name="Synthetic rehearsal record rules",
            record_owner="Synthetic records team",
            review_on=date(2090, 1, 1),
            confirmed=True,
            channels=(
                ManualChannel(
                    "website", "Convention website", "https://example.test/news"
                ),
                ManualChannel("noticeboard", "Entrance noticeboard"),
            ),
            policy_description="Fictional rules for isolated test records only.",
        ),
        **changes,
    )


def draft(body="Doors open at 10:00.", *, board_body=None):
    return AnnouncementDraftInput(
        "Opening information",
        body,
        "en",
        (
            AnnouncementVariantInput("website", "en", "Opening information", body),
            AnnouncementVariantInput(
                "noticeboard", "en", "Opening information", board_body or body
            ),
        ),
    )


def configured(world):
    return native(
        commands.update_announcement_settings,
        request(world),
        settings=rules(),
        expected_version=0,
    )


def created(world):
    configured(world)
    return native(
        commands.create_announcement,
        request(world),
        draft=draft(),
        expected_settings_version=1,
    )


def approved(world):
    result = created(world)
    result = native(
        commands.request_announcement_review,
        request(world),
        announcement_id=result.announcement_id,
        expected_version=result.version,
    )
    return native(
        commands.review_announcement,
        request(world, world[3]),
        announcement_id=result.announcement_id,
        revision_id=result.object_id,
        expected_version=result.version,
        decision="approve",
    )


def test_complete_two_person_copy_correction_and_manual_publication(world):
    result = approved(world)
    item_id = result.announcement_id
    first = queries.load_announcement(read_request(world), announcement_id=item_id)
    assert first.status == "approved"
    assert first.approved.id == first.draft.id
    for variant in first.approved.variants:
        result = native(
            commands.record_announcement_publication,
            request(world),
            announcement_id=item_id,
            variant_id=variant.id,
            expected_version=result.version,
            publication_url="https://example.test/posted",
            published_at=timezone.now() - timedelta(minutes=2),
        )
    result = native(
        commands.revise_announcement,
        request(world, world[3]),
        announcement_id=item_id,
        draft=draft("Doors open at 11:00.", board_body="Doors open at 10:00."),
        expected_version=result.version,
        reason="Correct the website opening time.",
        expected_settings_version=1,
    )
    pending = queries.load_announcement(read_request(world), announcement_id=item_id)
    assert pending.approved.id == first.approved.id
    assert {v.publication_status for v in pending.approved.variants} == {"reported"}
    result = native(
        commands.request_announcement_review,
        request(world, world[3]),
        announcement_id=item_id,
        expected_version=result.version,
    )
    result = native(
        commands.review_announcement,
        request(world),
        announcement_id=item_id,
        revision_id=result.object_id,
        expected_version=result.version,
        decision="approve",
    )
    current = queries.load_announcement(read_request(world), announcement_id=item_id)
    by_channel = {v.channel_code: v for v in current.approved.variants}
    assert by_channel["website"].publication_status == "update_needed"
    assert by_channel["website"].reported_body == "Doors open at 10:00."
    assert by_channel["noticeboard"].publication_status == "reported"
    assert by_channel["website"].publication_reporter_label == world[2].display_name
    assert by_channel["website"].publication_published_at is not None
    public = json.loads(
        queries.load_approved_announcement_copy(
            read_request(world), announcement_id=item_id
        ).content
    )
    assert public["payload"]["copy"]["body"] == "Doors open at 11:00."
    assert "actor_id" not in json.dumps(public)
    private = json.loads(
        queries.export_announcement_evidence(
            read_request(world), announcement_id=item_id
        ).content
    )
    assert len(private["payload"]["revisions"]) == 2
    assert len(private["payload"]["reviews"]) == 2
    assert len(private["payload"]["publication_reports"]) == 2
    receipts = AnnouncementCommandReceipt.objects.filter(edition_id=world[1].edition_id)
    assert (
        DomainEvent.objects.filter(
            event_name="announcements.changed.v1", event_edition_id=world[1].edition_id
        ).count()
        == receipts.count()
    )
    assert (
        OutboxMessage.objects.filter(
            event__event_name="announcements.changed.v1",
            event__event_edition_id=world[1].edition_id,
            destination="internal",
        ).count()
        == receipts.count()
    )


def test_round_keeps_all_editors_across_requested_changes_and_revisions(world):
    result = created(world)
    item_id = result.announcement_id
    result = native(
        commands.request_announcement_review,
        request(world),
        announcement_id=item_id,
        expected_version=result.version,
    )
    with pytest.raises(AnnouncementDeniedError):
        native(
            commands.review_announcement,
            request(world),
            announcement_id=item_id,
            revision_id=result.object_id,
            expected_version=result.version,
            decision="approve",
        )
    result = native(
        commands.review_announcement,
        request(world, world[3]),
        announcement_id=item_id,
        revision_id=result.object_id,
        expected_version=result.version,
        decision="changes_requested",
        note="Check the time.",
    )
    result = native(
        commands.revise_announcement,
        request(world, world[3]),
        announcement_id=item_id,
        draft=draft("Doors open at 11:00."),
        expected_version=result.version,
        reason="Correct the time.",
        expected_settings_version=1,
    )
    result = native(
        commands.request_announcement_review,
        request(world, world[3]),
        announcement_id=item_id,
        expected_version=result.version,
    )
    for actor in world[2:]:
        with pytest.raises(AnnouncementDeniedError):
            native(
                commands.review_announcement,
                request(world, actor),
                announcement_id=item_id,
                revision_id=result.object_id,
                expected_version=result.version,
                decision="approve",
            )
    # IDN-011 admits a currently authorized platform administrator as attributed,
    # independent reviewer without creating a participant relationship.
    result = native(
        commands.review_announcement,
        request(world, world[0]),
        announcement_id=item_id,
        revision_id=result.object_id,
        expected_version=result.version,
        decision="approve",
    )
    assert AnnouncementReview.objects.filter(
        revision_id=Announcement.objects.get(id=item_id).approved_revision_id,
        actor=world[0],
    ).exists()
    assert (
        AnnouncementRevision.objects.filter(announcement_id=item_id)
        .values("round_id")
        .distinct()
        .count()
        == 1
    )


def test_exact_retry_version_conflict_and_atomic_audit_failure(world, monkeypatch):
    configured(world)
    original = request(world)
    result = native(
        commands.create_announcement,
        original,
        draft=draft(),
        expected_settings_version=1,
    )
    replay = native(
        commands.create_announcement,
        replace(original, correlation_id=uuid4()),
        draft=draft(),
        expected_settings_version=1,
    )
    assert replay.replayed
    assert replay.receipt_id == result.receipt_id
    with pytest.raises(AnnouncementIdempotencyConflictError):
        commands.create_announcement(
            original, draft=draft("Different intent"), expected_settings_version=1
        )
    with pytest.raises(AnnouncementVersionConflictError):
        commands.revise_announcement(
            request(world),
            announcement_id=result.announcement_id,
            draft=draft(),
            expected_version=99,
            reason="Edit",
            expected_settings_version=1,
        )
    before = (
        Announcement.objects.count(),
        AnnouncementCommandReceipt.objects.count(),
        DomainEvent.objects.count(),
    )

    def unavailable(*args, **kwargs):
        raise RuntimeError("Synthetic event writer failure")

    monkeypatch.setattr(
        "maru.announcements.command_support.publish_domain_event", unavailable
    )
    with pytest.raises(RuntimeError, match="Synthetic event"):
        commands.create_announcement(
            request(world), draft=draft(), expected_settings_version=1
        )
    assert (
        Announcement.objects.count(),
        AnnouncementCommandReceipt.objects.count(),
        DomainEvent.objects.count(),
    ) == before


def test_absent_rules_stop_and_stale_rules_preserve_reporting_and_reads(
    world, monkeypatch
):
    with pytest.raises(AnnouncementSettingsRequiredError):
        commands.create_announcement(
            request(world), draft=draft(), expected_settings_version=1
        )
    result = approved(world)
    detail = queries.load_announcement(
        read_request(world), announcement_id=result.announcement_id
    )
    native(
        commands.set_announcements_stopped,
        request(world),
        stopped=True,
        expected_version=1,
        reason="Pause new copy while records are checked.",
    )
    with pytest.raises(AnnouncementStateConflictError):
        commands.revise_announcement(
            request(world),
            announcement_id=result.announcement_id,
            draft=draft(),
            expected_version=result.version,
            reason="Edit",
            expected_settings_version=1,
        )
    result = native(
        commands.record_announcement_publication,
        request(world),
        announcement_id=result.announcement_id,
        variant_id=detail.approved.variants[0].id,
        expected_version=result.version,
    )
    assert queries.export_announcement_evidence(
        read_request(world), announcement_id=result.announcement_id
    ).content
    native(
        commands.set_announcements_stopped,
        request(world),
        stopped=False,
        expected_version=2,
        reason="Resume confirmed rules.",
    )
    future = timezone.now().replace(year=2091)
    monkeypatch.setattr(
        "maru.announcements.command_support.timezone.now", lambda: future
    )
    with pytest.raises(AnnouncementSettingsRequiredError):
        commands.revise_announcement(
            request(world),
            announcement_id=result.announcement_id,
            draft=draft(),
            expected_version=result.version,
            reason="Edit",
            expected_settings_version=1,
        )
    result = native(
        commands.record_announcement_publication,
        request(world),
        announcement_id=result.announcement_id,
        variant_id=detail.approved.variants[1].id,
        expected_version=result.version,
    )
    assert result.version > detail.version


def test_report_correction_is_append_only_and_withdrawal_is_not_external_removal(world):
    result = approved(world)
    item_id = result.announcement_id
    detail = queries.load_announcement(read_request(world), announcement_id=item_id)
    variant = detail.approved.variants[0]
    original = native(
        commands.record_announcement_publication,
        request(world),
        announcement_id=item_id,
        variant_id=variant.id,
        expected_version=result.version,
        publication_url="https://example.test/wrong",
    )
    corrected = native(
        commands.correct_announcement_publication,
        request(world, world[3]),
        announcement_id=item_id,
        report_id=original.object_id,
        expected_version=original.version,
        withdrawn=False,
        reason="Recorded the wrong link.",
        publication_url="https://example.test/right",
    )
    withdrawn = native(
        commands.correct_announcement_publication,
        request(world),
        announcement_id=item_id,
        report_id=corrected.object_id,
        expected_version=corrected.version,
        withdrawn=True,
        reason="Publication could not be verified.",
    )
    assert AnnouncementPublicationReport.objects.get(
        id=original.object_id
    ).publication_url.endswith("wrong")
    assert (
        AnnouncementPublicationReport.objects.get(
            id=corrected.object_id
        ).supersedes_report_id
        == original.object_id
    )
    assert (
        AnnouncementPublicationReport.objects.get(
            id=withdrawn.object_id
        ).supersedes_report_id
        == corrected.object_id
    )
    current = queries.load_announcement(read_request(world), announcement_id=item_id)
    assert current.approved.variants[0].publication_status == "report_withdrawn"
    assert current.approved.variants[0].publication_url == ""
    assert current.approved.id == detail.approved.id


@pytest.mark.parametrize(
    "model",
    [
        AnnouncementSettingsRevision,
        AnnouncementRevision,
        AnnouncementVariant,
        AnnouncementReview,
        AnnouncementCommandReceipt,
    ],
)
def test_native_evidence_cannot_be_changed_or_deleted(world, model):
    approved(world)
    row = model.objects.first()
    with pytest.raises(DatabaseError), transaction.atomic():
        model.objects.filter(id=row.id).update(updated_at=timezone.now())
    with (
        pytest.raises(DatabaseError),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            sql.SQL("DELETE FROM {} WHERE id=%s").format(
                sql.Identifier(model._meta.db_table)
            ),
            [row.id],
        )


def test_native_missing_command_graph_and_orm_writer_boundary_fail_closed(world):
    result = created(world)
    item = Announcement.objects.get(id=result.announcement_id)
    with pytest.raises(ValidationError):
        item.save()

    def bypass():
        Announcement.objects.filter(id=item.id).update(
            version=item.version + 1, status="cancelled"
        )
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

    with pytest.raises(DatabaseError), transaction.atomic():
        bypass()
    item.refresh_from_db()
    assert item.status == "draft"

    def truncate_without_test_reset():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL maru.authority_provenance_test_reset=off")
            cursor.execute("TRUNCATE announcements_announcementcommandreceipt CASCADE")

    with pytest.raises(DatabaseError), transaction.atomic():
        truncate_without_test_reset()
    assert AnnouncementControl.objects.get(edition_id=world[1].edition_id).sequence == 2


def test_field_limited_public_copy_and_writer_choices_are_independently_admitted(
    world, monkeypatch
):
    result = approved(world)
    public_reader = AccountFactory()
    writer = AccountFactory()
    target = resolve_edition_target(
        organization_id=world[1].organization_id, edition_id=world[1].edition_id
    )
    for account, capability in (
        (public_reader, "announcements.view"),
        (writer, "announcements.view"),
        (writer, "announcements.compose"),
    ):
        grant_capability_direct(
            actor=world[2],
            approver=world[3],
            recipient=account,
            capability_code=capability,
            target=target,
            effective_from=timezone.now(),
            expires_at=None,
            reason="Synthetic least-privilege journey.",
            correlation_id=uuid4(),
            source_channel="test",
        )
    decide = authorization.decide_verified_principal_exact_edition

    def restricted_fields(**kwargs):
        decision = decide(**kwargs)
        if kwargs["principal_id"] == public_reader.id:
            return replace(decision, fields=decision.fields & {"approved_copy"})
        return decision

    # Current grants inherit static capability ceilings. This explicit admission
    # double proves the query honours a narrower returned field set as well.
    monkeypatch.setattr(
        authorization, "decide_verified_principal_exact_edition", restricted_fields
    )
    assert queries.load_approved_announcement_copy(
        read_request(world, public_reader), announcement_id=result.announcement_id
    ).content
    with CaptureQueriesContext(connection) as captured:
        preview = queries.load_approved_announcement_preview(
            read_request(world, public_reader), announcement_id=result.announcement_id
        )
    copy_queries = [
        row["sql"] for row in captured if 'FROM "announcements_' in row["sql"]
    ]
    assert copy_queries
    assert not any(
        '"current_revision_id"' in query
        or '"actor_id"' in query
        or '"command_receipt_id"' in query
        for query in copy_queries
    )
    assert not any(
        v.publication_reporter_label or v.publication_report_id
        for v in preview.variants
    )
    with pytest.raises(AnnouncementDeniedError):
        queries.load_announcement(
            read_request(world, public_reader), announcement_id=result.announcement_id
        )
    with pytest.raises(AnnouncementDeniedError):
        queries.export_announcement_evidence(
            read_request(world, public_reader), announcement_id=result.announcement_id
        )
    with CaptureQueriesContext(connection) as captured:
        settings = queries.load_announcement_settings(read_request(world, writer))
    settings_queries = [
        row["sql"] for row in captured if 'FROM "announcements_' in row["sql"]
    ]
    assert settings_queries
    assert not any(
        '"policy_description"' in query
        or '"record_owner"' in query
        or '"policy_name"' in query
        or '"policy_url"' in query
        for query in settings_queries
    )
    assert not settings.can_manage
    assert settings.channels
    assert settings.language_codes
    assert not settings.policy_description
    assert not settings.record_owner
    assert not settings.policy_name
    native(
        commands.create_announcement,
        request(world, writer),
        draft=draft(),
        expected_settings_version=settings.version,
    )
    allowed_queries = AuditEvent.objects.filter(
        principal_id=public_reader.id,
        operation="announcements.query.approved_copy",
        outcome="allow",
    )
    assert allowed_queries.count() == 2


def test_cross_edition_ids_and_unverified_actor_do_not_disclose_copy(world):
    result = approved(world)
    attacker = AccountFactory()
    with pytest.raises(AnnouncementDeniedError):
        queries.load_announcement(
            read_request(world, attacker), announcement_id=result.announcement_id
        )
    with pytest.raises(AnnouncementDeniedError):
        queries.load_announcement(
            replace(read_request(world), edition_id=uuid4()),
            announcement_id=result.announcement_id,
        )
    with transaction.atomic():
        type(world[2]).objects.filter(id=world[2].id).update(email_verified_at=None)
        with pytest.raises(AnnouncementDeniedError):
            commands.cancel_announcement(
                request(world),
                announcement_id=result.announcement_id,
                expected_version=result.version,
                reason="Not currently verified.",
            )
        # The separately enforced representation contract also forbids retaining
        # an unverified active controller; discard this transient actor probe.
        transaction.set_rollback(True)


def test_false_integrity_blocks_writes_exact_replays_and_reads(world, monkeypatch):
    configured(world)
    original = request(world)
    result = native(
        commands.create_announcement,
        original,
        draft=draft(),
        expected_settings_version=1,
    )
    before = AnnouncementCommandReceipt.objects.count()
    monkeypatch.setattr(
        "maru.announcements.readiness.announcements_database_integrity_is_ready",
        lambda: False,
    )
    with pytest.raises(AnnouncementError):
        commands.create_announcement(
            original, draft=draft(), expected_settings_version=1
        )
    with pytest.raises(AnnouncementError):
        commands.create_announcement(
            request(world), draft=draft(), expected_settings_version=1
        )
    with pytest.raises(AnnouncementError):
        queries.load_announcement(
            read_request(world), announcement_id=result.announcement_id
        )
    assert AnnouncementCommandReceipt.objects.count() == before


def test_native_stop_and_initial_state_guard_python_validation_bypass(
    world, monkeypatch
):
    result = created(world)
    native(
        commands.set_announcements_stopped,
        request(world),
        stopped=True,
        expected_version=1,
        reason="Pause synthetic work.",
    )
    rules_row = AnnouncementSettingsRevision.objects.get(edition_id=world[1].edition_id)
    monkeypatch.setattr(commands, "_settings", lambda _context: rules_row)
    before = AnnouncementRevision.objects.count()
    with pytest.raises(DatabaseError):
        native(
            commands.revise_announcement,
            request(world),
            announcement_id=result.announcement_id,
            draft=draft("Bypass attempt"),
            expected_version=result.version,
            reason="Test native stop enforcement.",
            expected_settings_version=2,
        )
    assert AnnouncementRevision.objects.count() == before
    with pytest.raises(DatabaseError), transaction.atomic():
        Announcement.objects.bulk_create(
            [
                Announcement(
                    organization_id=world[1].organization_id,
                    edition_id=world[1].edition_id,
                    status="approved",
                )
            ]
        )


def test_native_receipt_requires_its_persisted_announcement_transition(
    world, monkeypatch
):
    result = created(world)
    before = AnnouncementCommandReceipt.objects.count()

    def forget_to_save(item):
        item.version += 1

    monkeypatch.setattr(commands, "_advance", forget_to_save)
    with pytest.raises(DatabaseError):
        native(
            commands.cancel_announcement,
            request(world),
            announcement_id=result.announcement_id,
            expected_version=result.version,
            reason="Probe a receipt without its persisted aggregate transition.",
        )
    retained = Announcement.objects.get(id=result.announcement_id)
    assert (retained.version, retained.status) == (1, "draft")
    assert AnnouncementCommandReceipt.objects.count() == before


def test_native_receipt_requires_its_persisted_control_transition(world, monkeypatch):
    result = created(world)
    before = AnnouncementCommandReceipt.objects.count()
    monkeypatch.setattr(AnnouncementControl, "save", lambda *_args, **_kwargs: None)
    with pytest.raises(DatabaseError):
        native(
            commands.cancel_announcement,
            request(world),
            announcement_id=result.announcement_id,
            expected_version=result.version,
            reason="Probe a receipt without its persisted edition transition.",
        )
    retained = Announcement.objects.get(id=result.announcement_id)
    assert (retained.version, retained.status) == (1, "draft")
    assert AnnouncementCommandReceipt.objects.count() == before


def test_native_settings_receipt_cannot_advance_an_announcement(world, monkeypatch):
    result = created(world)
    before = AnnouncementCommandReceipt.objects.count()
    manager = AnnouncementCommandReceipt.objects
    original_create = manager.create

    def rebound_receipt(**fields):
        fields["announcement_id"] = result.announcement_id
        Announcement.objects.filter(id=result.announcement_id).update(version=2)
        return original_create(**fields)

    monkeypatch.setattr(manager, "create", rebound_receipt)
    with pytest.raises(DatabaseError):
        native(
            commands.update_announcement_settings,
            request(world),
            settings=rules(policy_name="Changed synthetic rules"),
            expected_version=1,
        )
    retained = Announcement.objects.get(id=result.announcement_id)
    assert (retained.version, retained.status) == (1, "draft")
    assert AnnouncementCommandReceipt.objects.count() == before


def test_native_multiple_commands_in_one_transaction_keep_final_head(world):
    result = created(world)
    with transaction.atomic():
        result = commands.revise_announcement(
            request(world),
            announcement_id=result.announcement_id,
            expected_version=result.version,
            expected_settings_version=1,
            draft=draft("Doors open at 11:00."),
            reason="Correct the synthetic opening time.",
        )
        result = commands.request_announcement_review(
            request(world),
            announcement_id=result.announcement_id,
            expected_version=result.version,
        )
        result = commands.review_announcement(
            request(world, world[3]),
            announcement_id=result.announcement_id,
            revision_id=result.object_id,
            expected_version=result.version,
            decision="approve",
        )
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute("SET CONSTRAINTS ALL DEFERRED")
    retained = Announcement.objects.get(id=result.announcement_id)
    assert (retained.version, retained.status) == (4, "approved")
    assert retained.current_revision_id == retained.approved_revision_id
    assert (
        AnnouncementCommandReceipt.objects.filter(
            announcement_id=result.announcement_id
        ).count()
        == 4
    )


@pytest.mark.django_db(transaction=True)
def test_concurrent_retry_and_competing_edits_preserve_one_version(world):
    configured(world)
    original = request(world)
    barrier = Barrier(2)

    def create_once():
        close_old_connections()
        try:
            barrier.wait(timeout=30)
            return commands.create_announcement(
                original, draft=draft(), expected_settings_version=1
            )
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: create_once(), range(2)))
    assert results[0].receipt_id == results[1].receipt_id
    assert sorted(row.replayed for row in results) == [False, True]
    assert Announcement.objects.count() == 1
    barrier = Barrier(2)

    def edit_once(index):
        close_old_connections()
        try:
            barrier.wait(timeout=30)
            return commands.revise_announcement(
                request(world),
                announcement_id=results[0].announcement_id,
                draft=draft(f"Concurrent edit {index}."),
                expected_version=1,
                reason="Synthetic competing edit.",
                expected_settings_version=1,
            )
        except AnnouncementVersionConflictError:
            return None
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        edits = list(pool.map(edit_once, range(2)))
    assert sum(row is not None for row in edits) == 1
    assert Announcement.objects.get().version == 2
    assert AnnouncementRevision.objects.count() == 2
    assert AnnouncementCommandReceipt.objects.count() == 3


@pytest.mark.parametrize(
    "statement",
    [
        "ALTER TABLE announcements_announcementcontrol "
        "DISABLE TRIGGER ann_0_graph_guard",
        "DROP INDEX ann_receipt_object_version_uq",
        "CREATE OR REPLACE FUNCTION public.maru_announcements_no_truncate() "
        "RETURNS trigger AS $$ BEGIN RETURN NULL; END; $$ LANGUAGE plpgsql "
        "VOLATILE SET search_path=pg_catalog,public,pg_temp",
    ],
)
def test_native_catalog_drift_blocks_command_admission(world, statement):
    configured(world)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(statement)
        assert not announcements_database_integrity_is_ready()
        with pytest.raises(AnnouncementError):
            commands.create_announcement(
                request(world), draft=draft(), expected_settings_version=1
            )
        assert not Announcement.objects.exists()
        transaction.set_rollback(True)
    assert announcements_database_integrity_is_ready()


def test_settings_cursor_guards_edits_while_retries_survive_removed_channels(
    world,
):
    configured(world)
    original = request(world)
    first = native(
        commands.create_announcement,
        original,
        draft=draft(),
        expected_settings_version=1,
    )
    edit_request = request(world)
    edited = native(
        commands.revise_announcement,
        edit_request,
        announcement_id=first.announcement_id,
        draft=draft("Saved correction."),
        expected_version=1,
        expected_settings_version=1,
        reason="Saved before settings changed.",
    )
    native(
        commands.update_announcement_settings,
        request(world),
        settings=rules(
            channels=(
                ManualChannel(
                    "website", "Moved website", "https://example.test/new-destination"
                ),
            )
        ),
        expected_version=1,
    )
    assert native(
        commands.create_announcement,
        original,
        draft=draft(),
        expected_settings_version=1,
    ).replayed
    assert native(
        commands.revise_announcement,
        edit_request,
        announcement_id=first.announcement_id,
        draft=draft("Saved correction."),
        expected_version=1,
        expected_settings_version=1,
        reason="Saved before settings changed.",
    ).replayed
    with pytest.raises(AnnouncementIdempotencyConflictError):
        commands.revise_announcement(
            edit_request,
            announcement_id=first.announcement_id,
            draft=draft("Saved correction."),
            expected_version=1,
            expected_settings_version=2,
            reason="Saved before settings changed.",
        )
    with pytest.raises(AnnouncementVersionConflictError):
        commands.revise_announcement(
            request(world),
            announcement_id=first.announcement_id,
            draft=draft(),
            expected_version=edited.version,
            expected_settings_version=1,
            reason="Stale destination choice.",
        )
    with pytest.raises(ValidationError, match="current event languages"):
        commands.revise_announcement(
            request(world),
            announcement_id=first.announcement_id,
            draft=draft(),
            expected_version=edited.version,
            expected_settings_version=2,
            reason="Removed channel is not authorized by preserving its form value.",
        )
    assert Announcement.objects.get(id=first.announcement_id).version == edited.version
    assert (
        AnnouncementRevision.objects.filter(
            announcement_id=first.announcement_id
        ).count()
        == 2
    )


def test_retained_report_correction_and_exact_retry_keep_later_post_current(world):
    result = approved(world)
    item_id = result.announcement_id
    first = queries.load_announcement(read_request(world), announcement_id=item_id)
    website = next(
        copy for copy in first.approved.variants if copy.channel_code == "website"
    )
    old_report = native(
        commands.record_announcement_publication,
        request(world),
        announcement_id=item_id,
        variant_id=website.id,
        expected_version=result.version,
    )
    result = native(
        commands.revise_announcement,
        request(world, world[3]),
        announcement_id=item_id,
        draft=draft("Updated public text."),
        expected_version=old_report.version,
        expected_settings_version=1,
        reason="Prepare fresh independent correction.",
    )
    result = native(
        commands.request_announcement_review,
        request(world, world[3]),
        announcement_id=item_id,
        expected_version=result.version,
    )
    result = native(
        commands.review_announcement,
        request(world),
        announcement_id=item_id,
        revision_id=result.object_id,
        expected_version=result.version,
        decision="approve",
    )
    updated = queries.load_announcement(read_request(world), announcement_id=item_id)
    website = next(
        copy for copy in updated.approved.variants if copy.channel_code == "website"
    )
    result = native(
        commands.record_announcement_publication,
        request(world),
        announcement_id=item_id,
        variant_id=website.id,
        expected_version=result.version,
    )
    latest_report_id = result.object_id
    before = queries.load_announcement(read_request(world), announcement_id=item_id)
    retained = next(
        row for row in before.publication_history if row.id == old_report.object_id
    )
    assert retained.can_correct
    assert retained.revision_number == 1
    assert retained.channel_label == "Convention website"
    correction_request = request(world)
    expected = result.version
    result = native(
        commands.correct_announcement_publication,
        correction_request,
        announcement_id=item_id,
        report_id=retained.id,
        expected_version=expected,
        withdrawn=True,
        reason="Earlier posting could not be verified.",
    )
    replay = native(
        commands.correct_announcement_publication,
        correction_request,
        announcement_id=item_id,
        report_id=retained.id,
        expected_version=expected,
        withdrawn=True,
        reason="Earlier posting could not be verified.",
    )
    assert replay.replayed
    assert replay.receipt_id == result.receipt_id
    after = queries.load_announcement(read_request(world), announcement_id=item_id)
    website = next(
        copy for copy in after.approved.variants if copy.channel_code == "website"
    )
    assert website.publication_status == "reported"
    assert website.publication_report_id == latest_report_id
    assert not next(
        row for row in after.publication_history if row.id == retained.id
    ).can_correct
    assert next(
        row for row in after.publication_history if row.id == result.object_id
    ).can_correct
    result = native(
        commands.cancel_announcement,
        request(world),
        announcement_id=item_id,
        expected_version=result.version,
        reason="End new announcement work.",
    )
    native(
        commands.set_announcements_stopped,
        request(world),
        stopped=True,
        expected_version=1,
        reason="Stop new work for the event.",
    )
    board = next(
        copy for copy in after.approved.variants if copy.channel_code == "noticeboard"
    )
    result = native(
        commands.record_announcement_publication,
        request(world),
        announcement_id=item_id,
        variant_id=board.id,
        expected_version=result.version,
    )
    native(
        commands.correct_announcement_publication,
        request(world),
        announcement_id=item_id,
        report_id=result.object_id,
        expected_version=result.version,
        withdrawn=True,
        reason="Correct the earlier report while stopped.",
    )
    stopped = queries.load_announcement(read_request(world), announcement_id=item_id)
    assert stopped.status == "cancelled"
    assert stopped.stopped
    assert stopped.can_record_publication
    assert any(row.can_correct for row in stopped.publication_history)
