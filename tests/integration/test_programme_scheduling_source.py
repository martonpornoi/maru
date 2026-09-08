"""Current owner evidence and disclosure boundaries for Scheduling dependencies."""

from dataclasses import asdict, replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

import maru.effects.services as effect_services
from maru.audit.models import AuditEvent
from maru.authorization.policy import PolicyDecision
from maru.events.queries import resolve_edition_time_envelope_reference
from maru.programme import scheduling_queries as source
from maru.programme.authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    ProgrammeAuthorizationDeniedError,
)
from maru.programme.commands import configure_programme_readiness
from maru.programme.host_inputs import ProgrammeHostAvailabilityPeriod
from maru.programme.queries import ProgrammeQueryUnavailableError
from tests.factories import AccountFactory, EventEditionFactory
from tests.integration.test_programme_commands import (
    _AllowThenDenyProgrammeAuthorizer,
    _create,
    _TrustedProgrammeAuthorizer,
)
from tests.integration.test_programme_hosts import invite, remove, respond, share

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(
        effect_services, "require_effect_delivery_allowed", lambda **_kwargs: None
    )
    manager, person = AccountFactory(), AccountFactory()
    edition = EventEditionFactory()
    policy = _TrustedProgrammeAuthorizer()
    item, _, _ = _create(actor=manager, edition=edition, authorizer=policy)
    return (
        manager,
        person,
        {
            "organization_id": edition.organization_id,
            "edition_id": edition.id,
            "item_id": item.item_id,
            "authorizer": policy,
            "source_channel": "test",
        },
    )


@pytest.fixture
def pinned(monkeypatch):
    monkeypatch.setattr(source, "profile_allows_conflict_source", lambda *_args: True)


def query(world, *hosts, **overrides):
    manager, _, common = world
    arguments = {
        "actor_id": manager.id,
        "organization_id": common["organization_id"],
        "edition_id": common["edition_id"],
        "item_ids": (common["item_id"],),
        "host_ids": tuple(hosts),
        "correlation_id": uuid4(),
        "authorizer": common["authorizer"],
    }
    arguments.update(overrides)
    return source.load_programme_scheduling_dependencies(**arguments)


def test_current_profile_denies_even_with_capability_substitute(world):
    with pytest.raises(ProgrammeQueryUnavailableError):
        query(world)
    assert not AuditEvent.objects.filter(
        operation="programme.query.scheduling_dependencies", outcome="allow"
    ).exists()


def test_real_policy_cannot_read_dormant_source(world, pinned):
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        query(world, authorizer=DEFAULT_PROGRAMME_AUTHORIZER)


def test_current_person_shared_periods_and_minimized_read_audit(world, pinned):
    invited = invite(world)
    shared = share(world, respond(world, invited))
    snapshot = query(world, invited.host_id)
    host = snapshot.hosts[0]
    assert snapshot.items[0].item_version == shared.resulting_item_version
    assert snapshot.items[0].hosting_required is True
    assert host.status == "shared"
    assert host.availability_version == 1
    assert host.person_key is not None
    assert host.person_key != world[1].id
    assert host.periods == (
        ProgrammeHostAvailabilityPeriod(
            datetime(2030, 8, 2, 8, tzinfo=UTC), datetime(2030, 8, 2, 10, tzinfo=UTC)
        ),
    )
    serialized = str(asdict(snapshot))
    assert all(
        value not in serialized
        for value in (
            "Host-only briefing",
            "Private organizer rationale",
            "Private organizer notes.",
            str(world[1].id),
            world[1].email,
        )
    )
    audit = AuditEvent.objects.get(
        operation="programme.query.scheduling_dependencies", outcome="allow"
    )
    assert audit.safe_metadata["target_count"] == 2
    assert "2030" not in str(audit.safe_metadata)
    assert str(host.person_key) not in str(audit.safe_metadata)


@pytest.mark.parametrize("state", ["draft", "withdrawn", "unknown", "empty"])
def test_withheld_and_empty_availability_are_not_free(world, pinned, state):
    invited = invite(world)
    confirmed = respond(world, invited)
    if state == "draft":
        share(world, confirmed, state="draft")
    elif state == "withdrawn":
        share(world, share(world, confirmed), state="withdrawn", periods=())
    elif state == "empty":
        share(world, confirmed, periods=())
    host = query(world, invited.host_id).hosts[0]
    assert host.status == ("unavailable" if state == "empty" else "not_shared")
    assert host.periods == ()


@pytest.mark.parametrize("state", ["invited", "declined", "removed", "inactive"])
def test_noncurrent_host_has_no_person_key_or_periods(world, pinned, state):
    invited = invite(world)
    if state == "declined":
        respond(world, invited, "decline")
    elif state in {"removed", "inactive"}:
        shared = share(world, respond(world, invited))
        if state == "removed":
            remove(world, shared)
        else:
            person = world[1]
            person.is_active = False
            person.save(update_fields=("is_active",))
    host = query(world, invited.host_id).hosts[0]
    expected = {
        "invited": "unconfirmed",
        "declined": "ended",
        "removed": "ended",
        "inactive": "inactive",
    }
    assert host.status == expected[state]
    assert host.person_key is None
    assert host.periods == ()


@pytest.mark.parametrize("missing", [False, True])
def test_current_envelope_change_invalidates_disclosure(
    world, pinned, monkeypatch, missing
):
    invited = invite(world)
    share(world, respond(world, invited))
    common = world[2]
    envelope = resolve_edition_time_envelope_reference(
        organization_id=common["organization_id"], edition_id=common["edition_id"]
    )
    monkeypatch.setattr(
        source,
        "resolve_edition_time_envelope_reference",
        lambda **_kwargs: (
            None
            if missing
            else replace(envelope, starts_at=datetime(2030, 8, 2, 9, tzinfo=UTC))
        ),
    )
    host = query(world, invited.host_id).hosts[0]
    assert host.status == "outside_edition"
    assert host.periods == ()


def test_no_selected_hosts_requires_explicit_not_applicable(world, pinned):
    assert query(world).items[0].hosting_required is True
    manager, _, common = world
    configure_programme_readiness(
        **common,
        actor_id=manager.id,
        concern="host_confirmation",
        disposition="not_applicable",
        expected_version=1,
        reason="An unstaffed transition needs no hosting purpose",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
    )
    result = query(world)
    assert result.items[0].hosting_required is False
    assert result.hosts == ()


@pytest.mark.parametrize("mismatch", ["organization", "edition", "item", "host"])
def test_scope_or_missing_selection_fails_as_a_whole(world, pinned, mismatch):
    invited = invite(world)
    values = {
        "organization": {"organization_id": uuid4()},
        "edition": {"edition_id": EventEditionFactory().id},
        "item": {"item_ids": (world[2]["item_id"], uuid4())},
        "host": {"host_ids": (invited.host_id, uuid4())},
    }
    with pytest.raises(
        (ProgrammeQueryUnavailableError, ProgrammeAuthorizationDeniedError)
    ):
        query(world, invited.host_id, **values[mismatch])


def test_existing_host_from_unselected_item_is_not_disclosed(world, pinned):
    invited = invite(world)
    manager, _, common = world
    edition = EventEditionFactory()
    other, _, _ = _create(
        actor=manager, edition=edition, authorizer=common["authorizer"]
    )
    with pytest.raises(ProgrammeQueryUnavailableError):
        query(
            world,
            invited.host_id,
            edition_id=edition.id,
            organization_id=edition.organization_id,
            item_ids=(other.item_id,),
        )


def test_actor_must_remain_current_after_source_lock(world, pinned, monkeypatch):
    monkeypatch.setattr(
        source, "resolve_active_verified_person_references", lambda **_kwargs: ()
    )
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        query(world)


def test_late_policy_denial_releases_no_projection_or_success_audit(world, pinned):
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        query(world, authorizer=_AllowThenDenyProgrammeAuthorizer())
    assert not AuditEvent.objects.filter(
        operation="programme.query.scheduling_dependencies", outcome="allow"
    ).exists()


def test_exact_field_ceiling_required(world, pinned):
    class IncompleteFields(_TrustedProgrammeAuthorizer):
        def authorize(self, **kwargs):
            decision = super().authorize(**kwargs)
            return PolicyDecision(
                allowed=True,
                fields=frozenset({"item_scheduling_facts"}),
                obligations=decision.obligations,
                reason_code=decision.reason_code,
            )

    with pytest.raises(ProgrammeAuthorizationDeniedError):
        query(world, authorizer=IncompleteFields())


def test_bounded_overflow_is_unavailable_not_truncated(world, pinned, monkeypatch):
    invited = invite(world)
    share(world, respond(world, invited))
    monkeypatch.setattr(source, "MAX_SCHEDULING_SOURCE_PERIODS", 0)
    with pytest.raises(ProgrammeQueryUnavailableError):
        query(world, invited.host_id)


def test_only_selected_host_people_are_resolved_in_one_batch(
    world, pinned, monkeypatch
):
    invited = invite(world)
    calls = []
    real = source.resolve_active_verified_person_references

    def capture(**kwargs):
        calls.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(source, "resolve_active_verified_person_references", capture)
    query(world)
    query(world, invited.host_id)
    assert calls == [
        {"account_ids": {world[0].id}, "lock": True},
        {"account_ids": {world[0].id, world[1].id}, "lock": True},
    ]


@pytest.mark.parametrize("bad_ids", [[uuid4()], (uuid4(), "invalid"), (None,)])
def test_untyped_selections_are_rejected(world, pinned, bad_ids):
    with pytest.raises(ValidationError):
        query(world, item_ids=bad_ids)


def test_empty_scope_is_complete_and_audited(world, pinned):
    result = query(world, item_ids=())
    assert result.items == result.hosts == ()


def test_audit_failure_releases_no_projection(world, pinned, monkeypatch):
    def failed_audit(*_args, **_kwargs):
        raise RuntimeError("Synthetic unavailable evidence sink")

    monkeypatch.setattr("maru.programme.queries.append_audit", failed_audit)
    with pytest.raises(RuntimeError, match="evidence sink"):
        query(world)


def test_inactive_actor_is_denied(world, pinned):
    actor = AccountFactory(is_active=False)
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        query(world, actor_id=actor.id)
