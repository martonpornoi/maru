"""Real PostgreSQL coverage for explicit host ownership and lifecycle evidence."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from importlib import import_module
from threading import Barrier
from uuid import uuid4

import pytest
from django.apps import apps
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.test.utils import CaptureQueriesContext
from psycopg import sql

import maru.effects.services as effect_services
from maru.audit.models import AuditEvent, AuditNativeMutationWitness
from maru.core.database_integrity_readiness import inspect_database_integrity_catalog
from maru.events.models import EventEdition
from maru.events.services import transition_edition
from maru.programme import host_queries
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.commands import (
    ProgrammeLifecycleConflictError,
    ProgrammeUnavailableError,
    ProgrammeVersionConflictError,
    approve_programme_public_rendition,
    configure_programme_readiness,
    record_programme_readiness_evidence,
)
from maru.programme.host_commands import (
    invite_programme_host,
    remove_programme_host,
    replace_programme_host_availability,
    respond_to_programme_host_invitation,
)
from maru.programme.host_inputs import (
    ProgrammeHostAvailabilityInput,
    ProgrammeHostAvailabilityPeriod,
    ProgrammeHostInvitationInput,
    ProgrammeHostResponseInput,
)
from maru.programme.host_queries import (
    ProgrammeHostReadRequest,
    load_programme_host_dependencies,
    load_programme_host_history,
    load_programme_host_roster,
    load_programme_host_self,
)
from maru.programme.models import (
    ProgrammeHostAvailabilityWindow,
    ProgrammeHostRelationship,
    ProgrammeHostRevision,
    ProgrammeItem,
    ProgrammePublicRendition,
    ProgrammeReadinessRequirement,
    ProgrammeWorkingRevision,
)
from maru.programme.public_copy_commands import withdraw_programme_public_rendition
from maru.programme.queries import (
    ProgrammeQueryUnavailableError,
    load_programme_readiness,
)
from maru.programme.readiness import (
    PROGRAMME_INTEGRITY_CONTRACT,
    programme_database_integrity_is_ready,
)
from tests.factories import AccountFactory, CapabilityGrantFactory, EventEditionFactory
from tests.integration.test_programme_commands import (
    _AllowThenDenyProgrammeAuthorizer,
    _create,
    _TrustedProgrammeAuthorizer,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def world(monkeypatch):
    """Create one real organizer item while substituting only dormant profile policy."""
    monkeypatch.setattr(
        effect_services, "require_effect_delivery_allowed", lambda **_kwargs: None
    )
    manager, person = AccountFactory(), AccountFactory()
    edition = EventEditionFactory()
    policy = _TrustedProgrammeAuthorizer()
    item, _, _ = _create(actor=manager, edition=edition, authorizer=policy)
    common = {
        "organization_id": edition.organization_id,
        "edition_id": edition.id,
        "item_id": item.item_id,
        "authorizer": policy,
        "source_channel": "test",
    }
    return manager, person, common


def invite(world, *, key=None):
    """Issue one deliberate host-visible invitation through the real boundary."""
    manager, person, common = world
    return invite_programme_host(
        **common,
        actor_id=manager.id,
        idempotency_key=key or uuid4(),
        correlation_id=uuid4(),
        invitation=ProgrammeHostInvitationInput(
            person.id, "host", "Visible session", "Host-only briefing", 1
        ),
        reason="Private organizer rationale",
    )


def respond(world, result, action="confirm"):
    """Record a current person-owned response with exact optimistic versions."""
    _, person, common = world
    return respond_to_programme_host_invitation(
        **common,
        actor_id=person.id,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        response=ProgrammeHostResponseInput(
            result.host_id,
            action,
            result.resulting_item_version,
            result.resulting_host_version,
            result.invitation_sequence,
        ),
    )


def test_explicit_invitation_confirmation_sharing_withdrawal(world):
    """Erase exact periods while retaining minimized confirmation history."""
    first = invite(world)
    assert first.resulting_item_version == 2
    assert ProgrammeHostRelationship.objects.get(id=first.host_id).state == "invited"
    confirmed = respond(world, first)
    _, person, common = world
    intent = ProgrammeHostAvailabilityInput(
        first.host_id,
        "shared",
        (
            ProgrammeHostAvailabilityPeriod(
                datetime(2030, 8, 2, 8, tzinfo=UTC),
                datetime(2030, 8, 2, 10, tzinfo=UTC),
            ),
        ),
        confirmed.resulting_item_version,
        confirmed.resulting_host_version,
    )
    shared = replace_programme_host_availability(
        **common,
        actor_id=person.id,
        availability=intent,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
    )
    assert ProgrammeHostAvailabilityWindow.objects.count() == 1
    withdrawn = replace_programme_host_availability(
        **common,
        actor_id=person.id,
        availability=replace(
            intent,
            state="withdrawn",
            periods=(),
            expected_item_version=shared.resulting_item_version,
            expected_host_version=shared.resulting_host_version,
        ),
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
    )
    assert withdrawn.resulting_host_version == 4
    assert ProgrammeHostAvailabilityWindow.objects.count() == 0
    assert ProgrammeHostRevision.objects.count() == 4
    assert list(
        ProgrammeHostRevision.objects.values_list("period_count", flat=True)
    ) == [0, 0, 1, 0]


def test_host_invitation_retry_returns_only_original_identifiers(world):
    """Retained retries neither reinvite nor require current optimistic versions."""
    key = uuid4()
    first = invite(world, key=key)
    respond(world, first)
    replay = invite(world, key=key)
    assert replay == replace(first, replayed=True)
    assert ProgrammeHostRevision.objects.count() == 2


def test_organizer_cannot_respond_as_another_person(world):
    """Host-management scope does not confer person-owned consent authority."""
    first = invite(world)
    manager, _, common = world
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        respond_to_programme_host_invitation(
            **common,
            actor_id=manager.id,
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            response=ProgrammeHostResponseInput(first.host_id, "confirm", 2, 1, 1),
        )
    assert ProgrammeHostRevision.objects.count() == 1


def test_removed_host_stale_response_cannot_restore_confirmation(world):
    """Manager removal invalidates a previously loaded personal confirmation."""
    first = invite(world)
    manager, _, common = world
    remove_programme_host(
        **common,
        actor_id=manager.id,
        host_id=first.host_id,
        expected_item_version=2,
        expected_host_version=1,
        reason="Synthetic roster correction",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
    )
    with pytest.raises(ProgrammeVersionConflictError):
        respond(world, first)
    assert ProgrammeHostRelationship.objects.get(id=first.host_id).state == "removed"


@pytest.mark.parametrize(
    "table",
    ["programmehostrelationship", "programmehostinvitation", "programmehostrevision"],
)
def test_raw_host_history_deletion_is_rejected(world, table):
    """PostgreSQL protects retained history independently of the ORM writer flag."""
    invite(world)
    with (
        pytest.raises(DatabaseError),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            sql.SQL("DELETE FROM {}").format(sql.Identifier("programme_" + table))
        )
    assert ProgrammeHostRevision.objects.count() == 1
    assert ProgrammeItem.objects.get(id=world[2]["item_id"]).aggregate_version == 2


def read_request(world, *, personal=False):
    manager, person, common = world
    return ProgrammeHostReadRequest(
        (person if personal else manager).id,
        common["organization_id"],
        common["edition_id"],
        common["item_id"],
        uuid4(),
        "test",
    )


def share(world, result, *, state="shared", periods=None):
    _, person, common = world
    return replace_programme_host_availability(
        **common,
        actor_id=person.id,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        availability=ProgrammeHostAvailabilityInput(
            result.host_id,
            state,
            (
                ProgrammeHostAvailabilityPeriod(
                    datetime(2030, 8, 2, 8, tzinfo=UTC),
                    datetime(2030, 8, 2, 10, tzinfo=UTC),
                ),
            )
            if periods is None
            else periods,
            result.resulting_item_version,
            result.resulting_host_version,
        ),
    )


def remove(world, result):
    manager, _, common = world
    return remove_programme_host(
        **common,
        actor_id=manager.id,
        host_id=result.host_id,
        expected_item_version=result.resulting_item_version,
        expected_host_version=result.resulting_host_version,
        reason="Private organizer removal rationale",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
    )


def test_roster_labels_are_current_related_display_names_without_contact_data(world):
    invite(world)
    result = load_programme_host_roster(
        read_request(world), authorizer=world[2]["authorizer"]
    )
    assert result.entries[0].display_label == world[1].display_name.strip()
    assert world[1].email not in repr(result)
    assert "availability" not in repr(result)
    assert "Private organizer" not in repr(result)


def test_roster_does_not_display_an_inactive_persons_retained_name(world):
    invite(world)
    world[1].is_active = False
    world[1].save(update_fields=("is_active",))
    result = load_programme_host_roster(
        read_request(world), authorizer=world[2]["authorizer"]
    )
    assert not result.entries[0].person_current
    assert result.entries[0].display_label == "Unavailable person"


def test_roster_missing_current_identity_label_is_unavailable(world, monkeypatch):
    invite(world)
    monkeypatch.setattr(
        host_queries, "active_verified_person_account_display_labels", lambda _ids: {}
    )
    with pytest.raises(ProgrammeQueryUnavailableError):
        load_programme_host_roster(
            read_request(world), authorizer=world[2]["authorizer"]
        )


def test_roster_labels_are_not_queried_before_field_authorization(world, monkeypatch):
    invite(world)
    policy = world[2]["authorizer"]
    authorize = policy.authorize
    monkeypatch.setattr(
        policy,
        "authorize",
        lambda **kwargs: replace(authorize(**kwargs), fields=frozenset()),
    )

    def forbidden(_ids):
        pytest.fail("Denied roster read reached Identity display labels")

    monkeypatch.setattr(
        host_queries, "active_verified_person_account_display_labels", forbidden
    )
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        load_programme_host_roster(read_request(world), authorizer=policy)


def test_roster_final_revocation_withholds_looked_up_names(world, monkeypatch):
    invite(world)
    policy = world[2]["authorizer"]
    authorize = policy.authorize
    labels = host_queries.active_verified_person_account_display_labels

    def revoke_after_labels(ids):
        result = labels(ids)
        monkeypatch.setattr(
            policy,
            "authorize",
            lambda **kwargs: replace(authorize(**kwargs), allowed=False),
        )
        return result

    monkeypatch.setattr(
        host_queries,
        "active_verified_person_account_display_labels",
        revoke_after_labels,
    )
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        load_programme_host_roster(read_request(world), authorizer=policy)
    assert not AuditEvent.objects.filter(
        operation="programme.query.host_roster", outcome="allow"
    ).exists()


def test_self_roster_history_and_availability_have_independent_field_ceilings(world):
    first = invite(world)
    policy = world[2]["authorizer"]
    personal = load_programme_host_self(
        read_request(world, personal=True), authorizer=policy
    )
    assert personal.invitations[0].title == "Visible session"
    assert personal.invitations[0].briefing == "Host-only briefing"
    assert "Private organizer" not in repr(personal)
    assert world[0].email not in repr(personal)
    assert world[1].email not in repr(personal)
    assert "Private organizer notes" not in repr(personal)
    roster = load_programme_host_roster(read_request(world), authorizer=policy)
    assert roster.entries[0].account_id == world[1].id
    assert roster.entries[0].display_label == world[1].display_name.strip()
    assert "briefing" not in repr(roster)
    history = load_programme_host_history(
        read_request(world), host_id=first.host_id, authorizer=policy
    )
    assert history[0].reason == "Private organizer rationale"
    assert not hasattr(history[0], "periods")
    assert ("programme.view_hosts", frozenset({"host_history"})) in policy.calls
    assert ("programme.view_hosts", frozenset({"host_roster"})) in policy.calls
    assert (
        AuditEvent.objects.filter(
            operation="programme.query.host_self", outcome="allow"
        ).count()
        == 1
    )


def test_private_draft_is_not_shared_and_shared_empty_is_explicitly_unavailable(world):
    confirmed = respond(world, invite(world))
    policy = world[2]["authorizer"]
    unknown = load_programme_host_dependencies(read_request(world), authorizer=policy)
    assert unknown.hosts[0].status == "not_shared"
    drafted = share(world, confirmed, state="draft")
    draft = load_programme_host_dependencies(read_request(world), authorizer=policy)
    assert (draft.hosts[0].status, draft.hosts[0].periods) == ("not_shared", ())
    assert load_programme_host_self(
        read_request(world, personal=True), authorizer=policy
    ).periods
    share(world, drafted, periods=())
    empty = load_programme_host_dependencies(read_request(world), authorizer=policy)
    assert (empty.hosts[0].status, empty.hosts[0].periods) == ("unavailable", ())
    assert empty.contract == "programme.host-dependencies@1"


def test_inactive_person_sharing_disappears_and_manager_can_still_remove(world):
    shared = share(world, respond(world, invite(world)))
    person = world[1]
    person.is_active = False
    person.save(update_fields=("is_active",))
    policy = world[2]["authorizer"]
    projection = load_programme_host_dependencies(
        read_request(world), authorizer=policy
    )
    assert (projection.hosts[0].status, projection.hosts[0].periods) == ("inactive", ())
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        load_programme_host_self(read_request(world, personal=True), authorizer=policy)
    remove(world, shared)
    assert not ProgrammeHostAvailabilityWindow.objects.exists()


@pytest.mark.parametrize("action", ["decline", "withdraw"])
def test_ended_relationship_reinvitation_requires_new_response(world, action):
    first = invite(world)
    if action == "withdraw":
        first = respond(world, first)
    ended = respond(world, first, action)
    manager, person, common = world
    again = invite_programme_host(
        **common,
        actor_id=manager.id,
        invitation=ProgrammeHostInvitationInput(
            person.id,
            "co_host",
            "New invitation",
            "New briefing",
            ended.resulting_item_version,
            ended.resulting_host_version,
        ),
        reason="New explicit invitation",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
    )
    assert again.host_id == first.host_id
    assert again.invitation_sequence == 2
    assert ProgrammeHostRelationship.objects.get(id=again.host_id).state == "invited"
    with pytest.raises(ProgrammeVersionConflictError):
        respond(world, first)
    respond(world, again)
    assert ProgrammeHostRelationship.objects.get(id=again.host_id).role == "co_host"


def test_own_privacy_exit_remains_available_after_planning_closes(world):
    shared = share(world, respond(world, invite(world)))
    manager, _, common = world
    edition = EventEdition.objects.get(id=common["edition_id"])
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=manager,
        capability_code="events.transition",
    )
    for state in ("preparing", "ready"):
        transition_edition(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            to_state=state,
            actor=manager,
            reason="Synthetic planning closure",
            correlation_id=uuid4(),
        )
    with pytest.raises(ProgrammeLifecycleConflictError):
        share(world, shared)
    with pytest.raises(ProgrammeLifecycleConflictError):
        remove(world, shared)
    withdrawn = share(world, shared, state="withdrawn", periods=())
    assert not ProgrammeHostAvailabilityWindow.objects.exists()
    respond(world, withdrawn, "withdraw")
    assert ProgrammeHostRelationship.objects.get(id=shared.host_id).state == "withdrawn"
    with (
        pytest.raises(DatabaseError),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE programme_programmeitem "
            "SET aggregate_version = aggregate_version + 1 WHERE id = %s",
            [common["item_id"]],
        )


def test_raw_availability_mutations_cannot_reuse_completed_host_evidence(world):
    share(world, respond(world, invite(world)))
    with (
        pytest.raises(DatabaseError),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute("DELETE FROM programme_programmehostavailabilitywindow")
    with (
        pytest.raises(DatabaseError),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE programme_programmehostavailabilitywindow "
            "SET ends_at=ends_at + interval '1 minute'"
        )
    assert ProgrammeHostAvailabilityWindow.objects.count() == 1


def test_late_event_failure_rolls_back_host_item_receipt_and_success_audit(
    world, monkeypatch
):
    def fail(*_args, **_kwargs):
        raise RuntimeError("Synthetic event failure")

    monkeypatch.setattr("maru.programme.commands.publish_domain_event", fail)
    with pytest.raises(RuntimeError, match="Synthetic event failure"):
        invite(world)
    assert not ProgrammeHostRelationship.objects.exists()
    assert ProgrammeItem.objects.get(id=world[2]["item_id"]).aggregate_version == 1
    assert not AuditEvent.objects.filter(
        operation="programme.command.host_invite", outcome="allow"
    ).exists()


@pytest.mark.parametrize("confirmed", [False, True])
def test_response_or_availability_racing_removal_has_one_versioned_winner(
    world, confirmed
):
    first = invite(world)
    if confirmed:
        first = respond(world, first)
    barrier = Barrier(2)

    def compete(manager_action):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return (
                remove(world, first)
                if manager_action
                else (share(world, first) if confirmed else respond(world, first))
            )
        except ProgrammeVersionConflictError:
            return "stale"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(compete, (False, True)))
    assert results.count("stale") == 1
    current = ProgrammeHostRelationship.objects.get(id=first.host_id)
    assert current.version == first.resulting_host_version + 1
    assert current.state in {"confirmed", "removed"}
    if current.state == "removed":
        assert not ProgrammeHostAvailabilityWindow.objects.exists()


def test_exact_host_database_contract_is_ready():
    assert programme_database_integrity_is_ready()


def test_confirmed_person_sees_only_approved_copy_and_ended_history_sees_no_later_copy(
    world,
):
    confirmed = respond(world, invite(world))
    manager, _, common = world
    working = ProgrammeWorkingRevision.objects.get(item_id=common["item_id"])
    approve_programme_public_rendition(
        **common,
        actor_id=manager.id,
        source_working_revision_id=working.id,
        public_title="Approved host-facing title",
        expected_version=confirmed.resulting_item_version,
        reason="Explicit safe public copy",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
    )
    snapshot = load_programme_host_self(
        read_request(world, personal=True), authorizer=common["authorizer"]
    )
    assert snapshot.public_copy.public_title == "Approved host-facing title"
    assert "Private organizer notes" not in repr(snapshot)
    ended = respond(world, confirmed, "withdraw")
    approve_programme_public_rendition(
        **common,
        actor_id=manager.id,
        source_working_revision_id=working.id,
        public_title="Later approved item copy",
        expected_version=ended.resulting_item_version,
        reason="New reviewed copy",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
    )
    history = load_programme_host_self(
        read_request(world, personal=True), authorizer=common["authorizer"]
    )
    assert history.public_copy is None
    assert "Later approved item copy" not in repr(history)
    assert history.invitations[0].title == "Visible session"


@pytest.mark.parametrize("withdraw_latest", [False, True])
def test_host_copy_respects_exact_withdrawal_without_fallback(world, withdraw_latest):
    confirmed = respond(world, invite(world))
    manager, _, common = world
    working = ProgrammeWorkingRevision.objects.get(item_id=common["item_id"])

    def approve(title):
        return approve_programme_public_rendition(
            **common,
            actor_id=manager.id,
            source_working_revision_id=working.id,
            public_title=title,
            expected_version=confirmed.resulting_item_version,
            reason="Explicit synthetic host-visible public copy",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
        )

    first = approve("First reviewed title")
    second = approve("Second reviewed title")
    request = read_request(world, personal=True)
    with CaptureQueriesContext(connection) as captured:
        before = load_programme_host_self(request, authorizer=common["authorizer"])
    assert before.public_copy.public_title == "Second reviewed title"
    content_queries = [
        row["sql"]
        for row in captured
        if 'FROM "programme_programmepublicrendition"' in row["sql"]
    ]
    assert len(content_queries) == 1
    assert all(
        field not in content_queries[0]
        for field in (
            "review_reason",
            "reviewed_by_id",
            "reviewed_at",
            "source_working_revision_id",
        )
    )
    withdraw_programme_public_rendition(
        **common,
        actor_id=manager.id,
        rendition_id=(second if withdraw_latest else first).result_object_id,
        expected_version=confirmed.resulting_item_version,
        reason="Private synthetic withdrawal explanation",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
    )
    after = load_programme_host_self(request, authorizer=common["authorizer"])
    if withdraw_latest:
        assert after.public_copy is None
        assert "First reviewed title" not in repr(after)
        assert "Second reviewed title" not in repr(after)
    else:
        assert after.public_copy.public_title == "Second reviewed title"
    assert "Private synthetic withdrawal explanation" not in repr(after)
    assert after.invitations == before.invitations
    assert (
        ProgrammePublicRendition.objects.filter(
            id__in=(first.result_object_id, second.result_object_id)
        ).count()
        == 2
    )

    approve("Fresh third reviewed title")
    fresh = load_programme_host_self(request, authorizer=common["authorizer"])
    assert fresh.public_copy.public_title == "Fresh third reviewed title"
    assert fresh.public_copy.rendition_number == 3


def test_roster_locks_actor_and_hosts_in_one_identifier_order(world, monkeypatch):
    invite(world)

    original = host_queries.resolve_active_verified_person_reference
    locked = []

    def resolve(*, account_id, lock=False):
        if lock:
            locked.append(account_id)
        return original(account_id=account_id, lock=lock)

    monkeypatch.setattr(
        host_queries, "resolve_active_verified_person_reference", resolve
    )
    load_programme_host_roster(read_request(world), authorizer=world[2]["authorizer"])
    assert locked == sorted({world[0].id, world[1].id}, key=str)


def test_host_and_availability_cursors_invalidate_only_their_dependent_concerns(world):
    shared = share(world, respond(world, invite(world)))
    manager, person, common = world
    for concern in ("host_confirmation", "schedule_availability", "technical_needs"):
        configured = configure_programme_readiness(
            **common,
            actor_id=manager.id,
            concern=concern,
            disposition="required",
            expected_version=ProgrammeItem.objects.get(
                id=common["item_id"]
            ).aggregate_version,
            reason="Synthetic separate concern",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
        )
        record_programme_readiness_evidence(
            **common,
            actor_id=manager.id,
            concern=concern,
            state="satisfied",
            expected_version=configured.resulting_item_version,
            reason="Synthetic reviewed evidence",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
        )

    def states():
        return {
            r.concern: r.state
            for r in load_programme_readiness(
                **common,
                actor_id=manager.id,
                reason="Synthetic current readiness check",
            )
        }

    assert set(states().values()) == {"satisfied"}
    cursors = dict(
        ProgrammeReadinessRequirement.objects.values_list(
            "concern", "dependency_version"
        )
    )
    assert cursors == {
        "host_confirmation": 3,
        "schedule_availability": 4,
        "technical_needs": 0,
    }
    shared = replace(
        shared,
        resulting_item_version=ProgrammeItem.objects.get(
            id=common["item_id"]
        ).aggregate_version,
    )
    drafted = share(world, shared, state="draft")
    assert states() == {
        "host_confirmation": "satisfied",
        "schedule_availability": "stale",
        "technical_needs": "satisfied",
    }
    cursors = dict(
        ProgrammeReadinessRequirement.objects.values_list(
            "concern", "dependency_version"
        )
    )
    assert cursors == {
        "host_confirmation": 3,
        "schedule_availability": drafted.resulting_item_version,
        "technical_needs": 0,
    }
    person.is_active = False
    person.save(update_fields=("is_active",))
    assert states()["host_confirmation"] == "stale"


def test_missing_hosts_cannot_turn_operator_attestation_into_current_host_proof(world):
    manager, _, common = world
    configured = configure_programme_readiness(
        **common,
        actor_id=manager.id,
        concern="host_confirmation",
        disposition="required",
        expected_version=1,
        reason="Explicit hosting requirement",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
    )
    record_programme_readiness_evidence(
        **common,
        actor_id=manager.id,
        concern="host_confirmation",
        state="satisfied",
        expected_version=configured.resulting_item_version,
        reason="Retained operator attestation",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
    )
    summary = load_programme_readiness(
        **common, actor_id=manager.id, reason="Check current host proof"
    )
    assert summary[0].state == "stale"


@pytest.mark.parametrize(
    "loader",
    [
        load_programme_host_self,
        load_programme_host_roster,
        load_programme_host_dependencies,
    ],
)
def test_partial_field_decision_fails_before_disclosure(world, loader, monkeypatch):
    invite(world)
    policy = world[2]["authorizer"]
    original = policy.authorize
    monkeypatch.setattr(
        policy,
        "authorize",
        lambda **kwargs: replace(original(**kwargs), fields=frozenset()),
    )
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        loader(read_request(world, personal=True), authorizer=policy)


def test_same_intent_retry_does_not_require_new_host_management_authority(
    world, monkeypatch
):
    key = uuid4()
    first = invite(world, key=key)
    policy = world[2]["authorizer"]
    original = policy.authorize
    monkeypatch.setattr(
        policy, "authorize", lambda **kwargs: replace(original(**kwargs), allowed=False)
    )
    assert invite(world, key=key) == replace(first, replayed=True)
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        invite(world)


@pytest.mark.parametrize("change", ["absent_item", "other_person"])
def test_unrelated_person_and_absent_item_have_same_denial(world, change):
    invite(world)
    request = read_request(world, personal=True)
    if change == "absent_item":
        request = replace(request, item_id=uuid4())
    else:
        request = replace(request, actor_id=AccountFactory().id)
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        load_programme_host_self(request, authorizer=world[2]["authorizer"])


@pytest.mark.usefixtures("restores_current_migration_graph")
def test_empty_host_schema_reverses_and_reapplies_exactly():
    executor = MigrationExecutor(connection)
    executor.migrate([("programme", "0006_accepted_item_downgrade_fence")])
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT to_regclass('public.programme_programmehostrelationship'), "
            "to_regprocedure('public.maru_guard_programme_host()'), "
            "to_regclass('public.programme_programmeplacementdecision'), "
            "to_regprocedure('public.maru_guard_programme_placement_decision()'), "
            "to_regclass('public.programme_programmestaffingrequirement'), "
            "to_regprocedure('public.maru_guard_programme_staffing()'), "
            "to_regclass('public.workforce_programmeshiftbinding'), "
            "to_regprocedure('public.maru_guard_workforce_programme_binding()')"
        )
        assert cursor.fetchone() == (None,) * 8
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
    assert programme_database_integrity_is_ready()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT to_regclass('public.workforce_programmeshiftbinding') IS NOT NULL, "
            "to_regprocedure('public.maru_guard_workforce_programme_binding()') "
            "IS NOT NULL"
        )
        assert cursor.fetchone() == (True, True)


@pytest.mark.usefixtures("restores_current_migration_graph")
def test_retained_host_history_fences_downgrade_before_any_guard_removal(world):
    first = invite(world)
    before = MigrationRecorder(connection).applied_migrations()
    host_fence = import_module("maru.programme.migrations.0009_host_downgrade_fence")
    with (
        pytest.raises(RuntimeError, match="Cannot remove Programme host integrity"),
        connection.schema_editor() as editor,
    ):
        host_fence.refuse_used_host_downgrade(apps, editor)
    assert AuditNativeMutationWitness.objects.exists()
    with pytest.raises(RuntimeError, match="retain its execution boundary"):
        MigrationExecutor(connection).migrate(
            [("programme", "0007_host_relationships")]
        )
    assert MigrationRecorder(connection).applied_migrations() == before
    assert ProgrammeHostRelationship.objects.get(id=first.host_id).version == 1
    # Native evidence now fences the entire extension before any supposedly
    # unused successor can reverse. Retain the complete current owner contract.
    guards = inspect_database_integrity_catalog(PROGRAMME_INTEGRITY_CONTRACT)
    assert guards.ready
    assert guards.function_execute_owner_only
    assert programme_database_integrity_is_ready()
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
    assert ProgrammeHostRelationship.objects.get(id=first.host_id).version == 1
    assert programme_database_integrity_is_ready()


def test_retained_host_grant_fences_capability_vocabulary_contraction(world):
    manager, _, common = world
    edition = EventEdition.objects.get(id=common["edition_id"])
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=manager,
        capability_code="programme.manage_hosts",
    )
    migration = import_module(
        "maru.authorization.migrations.0026_programme_host_capabilities"
    )
    with (
        pytest.raises(
            RuntimeError, match="Cannot remove retained Programme host authority"
        ),
        connection.schema_editor() as editor,
    ):
        migration.refuse_used_host_capability_downgrade(apps, editor)


def test_lost_fresh_host_authority_rolls_back_before_mutation(world):
    manager, person, common = world
    changed = (
        manager,
        person,
        {**common, "authorizer": _AllowThenDenyProgrammeAuthorizer()},
    )
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        invite(changed)
    assert not ProgrammeHostRelationship.objects.exists()
    assert ProgrammeItem.objects.get(id=common["item_id"]).aggregate_version == 1


def test_identity_deactivation_racing_confirmation_never_leaves_current_host_proof(
    world,
):
    first = invite(world)
    barrier = Barrier(2)

    def compete(deactivate):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            if deactivate:
                person = world[1]
                person.is_active = False
                person.save(update_fields=("is_active",))
                return "inactive"
            try:
                return respond(world, first)
            except (ProgrammeAuthorizationDeniedError, ProgrammeUnavailableError):
                return "denied"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(compete, (False, True)))
    assert "inactive" in results
    snapshot = load_programme_host_dependencies(
        read_request(world), authorizer=world[2]["authorizer"]
    )
    assert (snapshot.hosts[0].status, snapshot.hosts[0].periods) == ("inactive", ())
    current = ProgrammeHostRelationship.objects.get(id=first.host_id)
    assert current.version == (1 if "denied" in results else 2)
