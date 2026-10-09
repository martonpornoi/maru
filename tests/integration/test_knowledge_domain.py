"""Native Guides workflow, exact review, reader boundaries and reciprocal evidence."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
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

from maru.audit.models import AuditEvent
from maru.effects.models import DomainEvent
from maru.events.services import EventEditionDetails, update_event_edition
from maru.knowledge import authorization, commands, evidence_bound, queries
from maru.knowledge.contracts import (
    GuidanceCommandRequest,
    GuidanceDraftInput,
    GuidanceReadRequest,
    GuidanceSettingsInput,
)
from maru.knowledge.errors import (
    GuidanceDeniedError,
    GuidanceError,
    GuidanceIdempotencyConflictError,
    GuidanceLimitError,
    GuidanceNotAvailableError,
    GuidanceStateConflictError,
    GuidanceVersionConflictError,
)
from maru.knowledge.models import (
    GuidanceCommandReceipt,
    GuidanceControl,
    GuidanceItem,
    GuidanceReview,
    GuidanceRevision,
)
from maru.knowledge.readiness import knowledge_database_integrity_is_ready
from tests.integration.guidance_test_support import (
    create_guidance_workspace,
    guidance_runtime,
)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]

__all__ = ["guidance_runtime"]


def native(call, *args, **kwargs):
    """Evaluate every deferred owning constraint at a real command boundary."""
    with transaction.atomic():
        result = call(*args, **kwargs)
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute("SET CONSTRAINTS ALL DEFERRED")
        return result


@pytest.fixture
def world(guidance_runtime):
    return create_guidance_workspace(platform=guidance_runtime)


def request(world, actor=None):
    _platform, edition, author, _reviewer = world
    return GuidanceCommandRequest(
        actor_id=(actor or author).id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        correlation_id=uuid4(),
        idempotency_key=uuid4(),
        source_channel="test",
    )


def read_request(world, actor=None):
    value = request(world, actor)
    return GuidanceReadRequest(
        value.actor_id, value.organization_id, value.edition_id, value.correlation_id
    )


def rules(**changes):
    return replace(
        GuidanceSettingsInput(
            policy_name="Synthetic record rules",
            record_owner="Synthetic records team",
            review_on=date(2090, 1, 1),
            confirmed=True,
            policy_description="Fictional isolated Guides records only.",
        ),
        **changes,
    )


def draft(**changes):
    return replace(
        GuidanceDraftInput(
            "Finding help",
            "Ask the event help desk.",
            "en",
            date(2090, 1, 1),
            ("knowledge.compose",),
        ),
        **changes,
    )


def configured(world):
    return native(
        commands.update_guidance_settings,
        request(world),
        settings=rules(),
        expected_version=0,
    )


def created(world, **changes):
    configured(world)
    return native(
        commands.create_guidance,
        request(world),
        draft=draft(**changes),
        expected_settings_version=1,
    )


def submit(world, result):
    return native(
        commands.request_guidance_review,
        request(world),
        item_id=result.item_id,
        expected_version=result.version,
    )


def approve(world, result, *, actor=None):
    return native(
        commands.review_guidance,
        request(world, actor or world[3]),
        item_id=result.item_id,
        revision_id=result.object_id,
        expected_version=result.version,
        decision="approve",
    )


def approved(world):
    return approve(world, submit(world, created(world)))


def test_independent_approval_binds_complete_copy_and_minimized_evidence(world):
    assert knowledge_database_integrity_is_ready()
    item = created(world)
    submitted = submit(world, item)
    with pytest.raises(GuidanceStateConflictError):
        approve(world, submitted, actor=world[2])
    result = approve(world, submitted)
    current = queries.load_current_guidance(read_request(world), item_id=result.item_id)
    assert current.body == draft().body
    assert current.summary.number == 1
    assert current.summary.review_by == draft().review_by
    assert current.placements == ("knowledge.compose",)
    assert current.summary.owner_label == "Guides team for this event"
    receipts = GuidanceCommandReceipt.objects.filter(edition_id=world[1].id)
    events = DomainEvent.objects.filter(
        event_name="knowledge.changed.v1", event_edition_id=world[1].id
    )
    assert receipts.count() == events.count() == 4
    assert set(events.values_list("aggregate_version", flat=True)) == {1, 2, 3, 4}
    assert all(
        set(payload) == {"operation"}
        for payload in events.values_list("payload", flat=True)
    )
    assert AuditEvent.objects.filter(
        event_edition_id=world[1].id,
        operation="knowledge.query.current_copy",
        outcome="allow",
    ).exists()


def test_review_date_can_be_blank_in_draft_but_not_in_submission(world):
    result = created(world, review_by=None)
    with pytest.raises(ValidationError, match="review date"):
        submit(world, result)
    assert GuidanceReview.objects.count() == 0
    assert GuidanceItem.objects.get(id=result.item_id).status == "draft"


def test_replacement_retains_current_and_new_round_allows_writer_reviewer_swap(world):
    original = approved(world)
    result = native(
        commands.revise_guidance,
        request(world, world[3]),
        item_id=original.item_id,
        draft=draft(body="Ask the entrance information desk."),
        expected_version=original.version,
        expected_settings_version=1,
        reason="Correct the responsible desk.",
    )
    assert (
        queries.load_current_guidance(read_request(world), item_id=result.item_id).body
        == draft().body
    )
    submitted = native(
        commands.request_guidance_review,
        request(world, world[3]),
        item_id=result.item_id,
        expected_version=result.version,
    )
    final = approve(world, submitted, actor=world[2])
    view = queries.load_current_guidance(read_request(world), item_id=final.item_id)
    revisions = list(
        GuidanceRevision.objects.filter(item_id=final.item_id).order_by("number")
    )
    assert view.body == "Ask the entrance information desk."
    assert view.summary.number == 2
    assert revisions[1].base_approved_revision_id == revisions[0].id
    assert revisions[1].round_id != revisions[0].round_id


def test_requested_changes_preserve_all_editors_in_the_same_round(world):
    result = submit(world, created(world))
    result = native(
        commands.review_guidance,
        request(world, world[3]),
        item_id=result.item_id,
        revision_id=result.object_id,
        expected_version=result.version,
        decision="changes_requested",
        note="Explain which help desk.",
    )
    with pytest.raises(GuidanceStateConflictError):
        submit(world, result)
    result = native(
        commands.revise_guidance,
        request(world, world[3]),
        item_id=result.item_id,
        draft=draft(body="Ask the entrance help desk."),
        expected_version=result.version,
        expected_settings_version=1,
        reason="Clarify the location.",
    )
    submitted = submit(world, result)
    for author in world[2:]:
        with pytest.raises(GuidanceStateConflictError):
            approve(world, submitted, actor=author)
    assert (
        GuidanceRevision.objects.filter(item_id=result.item_id)
        .values("round_id")
        .distinct()
        .count()
        == 1
    )


def test_withdrawal_invalidates_pending_review_and_requires_fresh_review(world):
    result = approved(world)
    result = native(
        commands.revise_guidance,
        request(world),
        item_id=result.item_id,
        draft=draft(body="Check the entrance sign."),
        expected_version=result.version,
        expected_settings_version=1,
        reason="Prepare replacement instructions.",
    )
    submitted = submit(world, result)
    withdrawn = native(
        commands.withdraw_guidance,
        request(world),
        item_id=result.item_id,
        expected_version=submitted.version,
        reason="The desk is temporarily closed.",
    )
    with pytest.raises(GuidanceVersionConflictError):
        approve(world, submitted)
    with pytest.raises(GuidanceStateConflictError):
        submit(world, withdrawn)
    with pytest.raises(GuidanceNotAvailableError):
        queries.load_current_guidance(read_request(world), item_id=result.item_id)
    result = native(
        commands.revise_guidance,
        request(world),
        item_id=result.item_id,
        draft=draft(body="Ask the reopened desk."),
        expected_version=withdrawn.version,
        expected_settings_version=1,
        reason="Confirm restored assistance.",
    )
    result = approve(world, submit(world, result))
    assert not GuidanceItem.objects.get(id=result.item_id).withdrawn
    assert (
        queries.load_current_guidance(read_request(world), item_id=result.item_id).body
        == "Ask the reopened desk."
    )


def test_stop_hides_readers_and_stale_resume_cannot_restore_withdrawn_copy(world):
    first = approved(world)
    second = native(
        commands.create_guidance,
        request(world),
        draft=draft(title="Other guide"),
        expected_settings_version=1,
    )
    second = approve(world, submit(world, second))
    control = GuidanceControl.objects.get(edition_id=world[1].id)
    native(
        commands.stop_guidance,
        request(world),
        expected_control_version=control.sequence,
        reason="Pause these guides.",
    )
    preview = queries.load_guidance_resume_preview(read_request(world))
    assert {row.id for row in preview.items} == {first.item_id, second.item_id}
    assert queries.list_current_guidance(read_request(world)).items == ()
    assert all(
        item.current_number is None
        for item in queries.list_working_guidance(read_request(world)).items
    )
    assert (
        queries.load_context_guidance(
            read_request(world), context="knowledge.compose"
        ).items
        == ()
    )
    with pytest.raises(GuidanceNotAvailableError):
        queries.download_current_guidance(read_request(world), item_id=first.item_id)
    with pytest.raises(GuidanceStateConflictError):
        native(
            commands.create_guidance,
            request(world),
            draft=draft(),
            expected_settings_version=2,
        )
    assert queries.load_working_guidance(
        read_request(world), item_id=first.item_id
    ).history
    assert queries.export_guidance_evidence(
        read_request(world), item_id=first.item_id
    ).content
    native(
        commands.withdraw_guidance,
        request(world),
        item_id=first.item_id,
        expected_version=first.version,
        reason="Do not restore this guide.",
    )
    with pytest.raises(GuidanceVersionConflictError):
        native(
            commands.resume_guidance,
            request(world),
            expected_control_version=preview.control_version,
            preview_digest=preview.preview_digest,
            confirmed=True,
            reason="Resume confirmed guides.",
        )
    updated = queries.load_guidance_resume_preview(read_request(world))
    assert [row.id for row in updated.items] == [second.item_id]
    native(
        commands.resume_guidance,
        request(world),
        expected_control_version=updated.control_version,
        preview_digest=updated.preview_digest,
        confirmed=True,
        reason="Resume the remaining guide.",
    )
    assert [
        row.id for row in queries.list_current_guidance(read_request(world)).items
    ] == [second.item_id]


def test_exact_retry_precedes_settings_choices_but_changed_cursor_is_different_intent(
    world,
):
    configured(world)
    original = request(world)
    result = native(
        commands.create_guidance, original, draft=draft(), expected_settings_version=1
    )
    native(
        commands.update_guidance_settings,
        request(world),
        settings=rules(policy_name="Updated synthetic rules"),
        expected_version=1,
    )
    replay = native(
        commands.create_guidance, original, draft=draft(), expected_settings_version=1
    )
    assert replay.replayed
    assert replay.receipt_id == result.receipt_id
    with pytest.raises(GuidanceIdempotencyConflictError):
        native(
            commands.create_guidance,
            original,
            draft=draft(),
            expected_settings_version=2,
        )
    with pytest.raises(GuidanceVersionConflictError):
        native(
            commands.revise_guidance,
            request(world),
            item_id=result.item_id,
            draft=draft(body="Changed text"),
            expected_version=result.version,
            expected_settings_version=1,
            reason="Stale rules form.",
        )
    assert GuidanceRevision.objects.filter(item_id=result.item_id).count() == 1


def test_platform_and_foreign_scope_cannot_read_or_compose_current_copy(world):
    result = approved(world)
    for actor in (world[0],):
        with pytest.raises(GuidanceDeniedError):
            queries.load_current_guidance(
                read_request(world, actor), item_id=result.item_id
            )
        with pytest.raises(GuidanceDeniedError):
            commands.create_guidance(
                request(world, actor), draft=draft(), expected_settings_version=1
            )
    with pytest.raises(GuidanceDeniedError):
        queries.load_current_guidance(
            replace(read_request(world), edition_id=uuid4()), item_id=result.item_id
        )
    with pytest.raises(GuidanceNotAvailableError):
        queries.load_current_guidance(read_request(world), item_id=uuid4())


def test_summary_reader_never_loads_copy_private_reviews_or_rule_descriptions(
    world, monkeypatch
):
    result = approved(world)
    ordinary = authorization.decide_verified_principal_exact_edition

    def restricted(**kwargs):
        decision = ordinary(**kwargs)
        if kwargs["capability_code"] == "knowledge.view_current":
            return replace(decision, fields=decision.fields & {"current_summary"})
        return replace(decision, allowed=False, fields=frozenset())

    monkeypatch.setattr(
        authorization, "decide_verified_principal_exact_edition", restricted
    )
    with CaptureQueriesContext(connection) as captured:
        page = queries.load_context_guidance(
            read_request(world), context="knowledge.compose"
        )
    assert [row.id for row in page.items] == [result.item_id]
    with CaptureQueriesContext(connection) as searched:
        title_only = queries.list_current_guidance(read_request(world), query="desk")
    assert title_only.items == ()
    assert not any(
        '"body"' in row["sql"] for row in searched if 'FROM "knowledge_' in row["sql"]
    )
    owner_sql = [row["sql"] for row in captured if 'FROM "knowledge_' in row["sql"]]
    assert owner_sql
    for sql in owner_sql:
        assert '"body"' not in sql
        assert '"note"' not in sql
        assert '"actor_id"' not in sql
        assert '"current_revision_id"' not in sql
        assert '"policy_description"' not in sql
    with pytest.raises(GuidanceDeniedError):
        queries.load_current_guidance(read_request(world), item_id=result.item_id)
    with pytest.raises(GuidanceDeniedError):
        queries.export_guidance_evidence(read_request(world), item_id=result.item_id)


def test_current_copy_never_loads_an_unapproved_replacement_or_review_note(world):
    result = approved(world)
    native(
        commands.revise_guidance,
        request(world),
        item_id=result.item_id,
        draft=draft(body="Private replacement"),
        expected_version=result.version,
        expected_settings_version=1,
        reason="Prepare a private replacement.",
    )
    with CaptureQueriesContext(connection) as captured:
        current = queries.load_current_guidance(
            read_request(world), item_id=result.item_id
        )
    assert current.body == draft().body
    for sql in (row["sql"] for row in captured if 'FROM "knowledge_' in row["sql"]):
        assert '"current_revision_id"' not in sql
        assert '"note"' not in sql
        assert '"actor_id"' not in sql
        assert '"policy_description"' not in sql


def test_export_keeps_complete_review_and_rules_lineage_separate_from_copy(world):
    result = approved(world)
    artifact = json.loads(
        queries.export_guidance_evidence(
            read_request(world), item_id=result.item_id
        ).content
    )
    evidence = artifact["content"]
    assert (
        len(evidence["revisions"])
        == len(evidence["reviews"])
        == len(evidence["settings"])
        == 1
    )
    assert {row["operation"] for row in evidence["receipts"]} == {
        "settings_update",
        "create",
        "request_review",
        "approve",
    }
    copy = json.loads(
        queries.download_current_guidance(
            read_request(world), item_id=result.item_id
        ).content
    )["content"]
    assert "settings" not in copy
    assert "reviews" not in copy
    assert "receipts" not in copy
    assert "actor_id" not in json.dumps(copy)
    assert copy["saved_copy_notice"]


def test_private_export_includes_stopped_and_resumed_edition_controls_only(world):
    result = approved(world)
    unrelated = native(
        commands.create_guidance,
        request(world),
        draft=draft(body="Unrelated guide body must stay outside this artifact."),
        expected_settings_version=1,
    )
    foreign_world = create_guidance_workspace(platform=world[0])
    foreign = created(foreign_world, body="Foreign guide evidence stays foreign.")
    options = queries.load_guidance_options(read_request(world))
    stopped = native(
        commands.stop_guidance,
        request(world),
        expected_control_version=options.control_version,
        reason="Pause Guides for a records handover.",
    )
    artifact = queries.export_guidance_evidence(
        read_request(world), item_id=result.item_id
    )
    stopped_payload = json.loads(artifact.content)["content"]
    assert stopped_payload["edition_control"]["stopped"] is True
    assert stopped_payload["export_scope"]["kind"] == "one-guide-and-edition-controls"
    assert (
        "not a complete edition command journal"
        in stopped_payload["export_scope"]["sequence_notice"]
    )
    for excluded in (unrelated.item_id, foreign.item_id, foreign_world[1].id):
        assert str(excluded).encode() not in artifact.content
    assert b"Unrelated guide body" not in artifact.content
    assert b"Foreign guide evidence" not in artifact.content
    changed_rules = native(
        commands.update_guidance_settings,
        request(world),
        settings=rules(
            policy_name="Updated handover rules without a new guide revision"
        ),
        expected_version=stopped.version,
    )
    preview = queries.load_guidance_resume_preview(read_request(world))
    resumed = native(
        commands.resume_guidance,
        request(world),
        expected_control_version=preview.control_version,
        preview_digest=preview.preview_digest,
        confirmed=True,
        reason="Return the confirmed retained guides after handover.",
    )
    payload = json.loads(
        queries.export_guidance_evidence(
            read_request(world), item_id=result.item_id
        ).content
    )["content"]
    assert payload["edition_control"]["stopped"] is False
    assert payload["edition_control"]["settings_version"] == resumed.version
    assert {row["id"] for row in payload["settings"]} == {
        stopped_payload["settings"][0]["id"],
        str(changed_rules.object_id),
    }
    controls = [row for row in payload["receipts"] if row["item_id"] is None]
    assert [row["operation"] for row in controls] == [
        "settings_update",
        "stop",
        "settings_update",
        "resume",
    ]
    assert all(
        row["item_id"] in (None, str(result.item_id)) for row in payload["receipts"]
    )
    assert all(row["edition_id"] == str(world[1].id) for row in payload["receipts"])
    with pytest.raises(GuidanceNotAvailableError):
        queries.export_guidance_evidence(read_request(world), item_id=foreign.item_id)


@pytest.mark.parametrize("bound", ["controls", "bytes"])
def test_private_export_refuses_complete_control_history_overflow(
    world, monkeypatch, bound
):
    result = approved(world)
    native(
        commands.update_guidance_settings,
        request(world),
        settings=rules(
            policy_name="Second rules confirmation retained without another edit"
        ),
        expected_version=1,
    )
    if bound == "controls":
        monkeypatch.setattr(evidence_bound, "MAX_CONTROL_HISTORY", 1)
    else:
        monkeypatch.setattr(evidence_bound, "MAX_EXPORT_BYTES", 1)
    with pytest.raises(GuidanceLimitError):
        queries.export_guidance_evidence(read_request(world), item_id=result.item_id)
    assert GuidanceCommandReceipt.objects.filter(item_id=result.item_id).count() == 3
    assert (
        queries.load_current_guidance(read_request(world), item_id=result.item_id).body
        == draft().body
    )


def test_readiness_failure_refuses_new_commands_and_exact_retry(world, monkeypatch):
    configured(world)
    original = request(world)
    result = native(
        commands.create_guidance, original, draft=draft(), expected_settings_version=1
    )
    before = GuidanceCommandReceipt.objects.count()
    monkeypatch.setattr(
        "maru.knowledge.readiness.knowledge_database_integrity_is_ready", lambda: False
    )
    with pytest.raises(GuidanceError):
        commands.create_guidance(original, draft=draft(), expected_settings_version=1)
    with pytest.raises(GuidanceError):
        queries.load_working_guidance(read_request(world), item_id=result.item_id)
    assert GuidanceCommandReceipt.objects.count() == before


@pytest.mark.parametrize("missing", ["item", "control"])
def test_native_inverse_guard_refuses_receipt_without_saved_head(
    world, monkeypatch, missing
):
    result = created(world)
    before = GuidanceCommandReceipt.objects.count()
    if missing == "item":

        def forget(item):
            item.version += 1

        monkeypatch.setattr(commands, "_advance", forget)
    else:
        monkeypatch.setattr(GuidanceControl, "save", lambda *_args, **_kwargs: None)
    with pytest.raises(DatabaseError):
        native(
            commands.withdraw_guidance,
            request(world),
            item_id=result.item_id,
            expected_version=result.version,
            reason="Probe missing persisted transition.",
        )
    item = GuidanceItem.objects.get(id=result.item_id)
    assert (item.version, item.status, item.withdrawn) == (1, "draft", False)
    assert GuidanceCommandReceipt.objects.count() == before


def test_native_guards_refuse_raw_unreviewed_initial_availability_and_evidence_rewrite(
    world,
):
    result = created(world)
    with pytest.raises(DatabaseError), transaction.atomic():
        GuidanceItem.objects.bulk_create(
            [
                GuidanceItem(
                    organization_id=world[1].organization_id,
                    edition_id=world[1].id,
                    language_code="en",
                    status="approved",
                )
            ]
        )
    with pytest.raises(DatabaseError), transaction.atomic():
        GuidanceRevision.objects.filter(item_id=result.item_id).update(
            body="Rewritten immutable evidence"
        )
    with (
        pytest.raises(DatabaseError),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "DELETE FROM knowledge_guidancecommandreceipt WHERE item_id=%s",
            [result.item_id],
        )


@pytest.mark.parametrize("stage", ["request", "review", "retained"])
def test_removed_event_language_blocks_new_review_but_keeps_current_copy(
    world, monkeypatch, stage
):
    result = created(world)
    if stage in {"review", "retained"}:
        result = submit(world, result)
    if stage == "retained":
        result = approve(world, result)
    edition = world[1]
    edition.refresh_from_db()
    native(
        update_event_edition,
        actor=world[2],
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        expected_aggregate_version=edition.aggregate_version,
        details=EventEditionDetails(
            name=edition.name,
            time_zone=edition.time_zone,
            language_codes=("hu",),
            currency_codes=tuple(edition.currency_codes),
            starts_on=edition.starts_on,
            ends_on=edition.ends_on,
        ),
        correlation_id=uuid4(),
    )
    if stage == "retained":
        current = queries.load_current_guidance(
            read_request(world), item_id=result.item_id
        )
        assert current.summary.language_code == "en"
        assert current.body == draft().body
        return
    call = (
        commands.request_guidance_review
        if stage == "request"
        else commands.review_guidance
    )
    kwargs = {"item_id": result.item_id, "expected_version": result.version}
    if stage == "review":
        kwargs.update(revision_id=result.object_id, decision="approve")
    actor = world[2] if stage == "request" else world[3]
    before = GuidanceCommandReceipt.objects.count()
    with pytest.raises(ValidationError, match="Restore this guide's event language"):
        call(request(world, actor), **kwargs)
    detail = queries.load_working_guidance(
        read_request(world, actor), item_id=result.item_id
    )
    assert not detail.actions.can_compose
    assert not detail.actions.can_review
    monkeypatch.setattr(commands, "_require_current_language", lambda *_args: None)
    with pytest.raises(DatabaseError):
        native(call, request(world, actor), **kwargs)
    assert GuidanceCommandReceipt.objects.count() == before
    assert GuidanceReview.objects.filter(revision__item_id=result.item_id).count() == 0


def test_current_json_generation_time_changes_without_changing_exact_content(world):
    result = approved(world)
    first = queries.download_current_guidance(
        read_request(world), item_id=result.item_id
    )
    final = queries.download_current_guidance(
        read_request(world), item_id=result.item_id
    )
    first_data, final_data = json.loads(first.content), json.loads(final.content)
    assert first_data["generated_at"] <= final_data["generated_at"]
    assert first_data["content"] == final_data["content"]
    assert (
        first.content_fingerprint == final.content_fingerprint == first_data["sha256"]
    )
    assert len(first.content_fingerprint) == 64
    assert "Saved copies" in final_data["content"]["saved_copy_notice"]


def test_native_correction_cannot_reuse_approved_round_authorship(world, monkeypatch):
    result = approved(world)
    item = GuidanceItem.objects.get(id=result.item_id)
    previous = GuidanceRevision.objects.get(id=item.approved_revision_id)
    before = GuidanceCommandReceipt.objects.count()
    monkeypatch.setattr(commands, "uuid4", lambda: previous.round_id)
    with pytest.raises(DatabaseError):
        native(
            commands.revise_guidance,
            request(world, world[3]),
            item_id=result.item_id,
            draft=draft(body="A new correction needs its own authorship round."),
            expected_version=result.version,
            expected_settings_version=1,
            reason="Probe attempted reuse of the reviewed authorship round.",
        )
    item.refresh_from_db()
    assert item.current_revision_id == previous.id
    assert item.published_revision_id == previous.id
    assert GuidanceRevision.objects.filter(item_id=item.id).count() == 1
    assert GuidanceCommandReceipt.objects.count() == before


def test_native_multiple_commands_keep_final_current_and_withdrawal_heads(world):
    result = created(world)
    with transaction.atomic():
        result = commands.request_guidance_review(
            request(world), item_id=result.item_id, expected_version=result.version
        )
        result = commands.review_guidance(
            request(world, world[3]),
            item_id=result.item_id,
            revision_id=result.object_id,
            expected_version=result.version,
            decision="approve",
        )
        result = commands.withdraw_guidance(
            request(world),
            item_id=result.item_id,
            expected_version=result.version,
            reason="Withdraw in the same transaction.",
        )
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute("SET CONSTRAINTS ALL DEFERRED")
    item = GuidanceItem.objects.get(id=result.item_id)
    assert (item.version, item.status, item.withdrawn, item.published_revision_id) == (
        4,
        "withdrawn",
        True,
        None,
    )
    assert item.approved_revision_id is not None


@pytest.mark.django_db(transaction=True)
def test_concurrent_exact_retry_and_competing_edits_preserve_one_result(world):
    configured(world)
    original = request(world)
    barrier = Barrier(2)

    def create():
        close_old_connections()
        try:
            barrier.wait(timeout=30)
            return native(
                commands.create_guidance,
                original,
                draft=draft(),
                expected_settings_version=1,
            )
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(create) for _ in range(2)]
        created_results = [future.result(timeout=120) for future in futures]
    assert created_results[0].receipt_id == created_results[1].receipt_id
    assert sorted(row.replayed for row in created_results) == [False, True]
    result = created_results[0]
    barrier = Barrier(2)

    def revise(body):
        close_old_connections()
        try:
            barrier.wait(timeout=30)
            try:
                return native(
                    commands.revise_guidance,
                    request(world),
                    item_id=result.item_id,
                    draft=draft(body=body),
                    expected_version=1,
                    expected_settings_version=1,
                    reason="Competing complete edit.",
                )
            except GuidanceVersionConflictError:
                return None
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(revise, body)
            for body in ("First complete edit", "Second complete edit")
        ]
        edits = [future.result(timeout=120) for future in futures]
    assert sum(edit is not None for edit in edits) == 1
    assert GuidanceRevision.objects.filter(item_id=result.item_id).count() == 2
    assert GuidanceCommandReceipt.objects.filter(item_id=result.item_id).count() == 2
    assert GuidanceItem.objects.get(id=result.item_id).version == 2


def test_overdue_content_remains_current_without_claiming_fresh_review(world):
    result = approve(world, submit(world, created(world, review_by=date(2000, 1, 1))))
    current = queries.load_current_guidance(read_request(world), item_id=result.item_id)
    assert current.summary.review_due
    assert current.summary.review_by == date(2000, 1, 1)
    assert [
        row.id for row in queries.list_current_guidance(read_request(world)).items
    ] == [result.item_id]


def test_native_stop_guard_survives_bypassed_application_settings_check(
    world, monkeypatch
):
    result = created(world)
    control = GuidanceControl.objects.get(edition_id=world[1].id)
    native(
        commands.stop_guidance,
        request(world),
        expected_control_version=control.sequence,
        reason="Pause native test.",
    )
    monkeypatch.setattr(
        commands, "_settings", lambda _context: control.current_settings
    )
    before = GuidanceRevision.objects.count()
    with pytest.raises(DatabaseError):
        native(
            commands.revise_guidance,
            request(world),
            item_id=result.item_id,
            draft=draft(body="Bypass attempt"),
            expected_version=result.version,
            expected_settings_version=2,
            reason="Probe native stop enforcement.",
        )
    assert GuidanceRevision.objects.count() == before


def test_later_same_transaction_coauthor_does_not_invalidate_previous_review(world):
    pending = submit(world, created(world))
    with transaction.atomic():
        decision = commands.review_guidance(
            request(world, world[3]),
            item_id=pending.item_id,
            revision_id=pending.object_id,
            expected_version=pending.version,
            decision="changes_requested",
            note="Clarify where the help desk is.",
        )
        edited = commands.revise_guidance(
            request(world, world[3]),
            item_id=pending.item_id,
            expected_version=decision.version,
            expected_settings_version=1,
            draft=draft(body="Ask the help desk beside the main entrance."),
        )
        # Validate both decisions together: deferred review checks must preserve
        # who had edited at that review, rather than including later coauthors.
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute("SET CONSTRAINTS ALL DEFERRED")
    retained = GuidanceReview.objects.get(id=decision.object_id)
    later = GuidanceRevision.objects.get(id=edited.object_id)
    reviewed = GuidanceRevision.objects.get(id=pending.object_id)
    assert retained.decision == "changes_requested"
    assert retained.revision_id == reviewed.id
    assert later.round_id == reviewed.round_id
    assert later.actor_id == retained.actor_id == world[3].id
    assert later.number == reviewed.number + 1
    next_review = submit(world, edited)
    before = GuidanceReview.objects.count()
    for author in (world[2], world[3]):
        with pytest.raises(GuidanceStateConflictError):
            approve(world, next_review, actor=author)
    assert GuidanceReview.objects.count() == before
