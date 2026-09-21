"""Real independent controller and Events authority for stop-impact admission."""

from uuid import uuid4

import pytest
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.authorization import programme_stop_queries as queries
from maru.authorization.catalog import ScopeLevel
from maru.authorization.commands import grant_capability_direct, revoke_capability_grant
from maru.authorization.policy import (
    resolve_edition_target,
    resolve_organization_target,
)
from maru.authorization.programme_role_inputs import (
    ProgrammeRoleIntent,
    ProgrammeRoleScope,
)
from maru.authorization.programme_stop_authorization import (
    require_programme_stop_controller,
)
from maru.authorization.services import AuthorizationDenied
from maru.events import adoption
from tests.factories import AccountFactory
from tests.integration.test_programme_role_schema import (
    _command_decision,
    _command_request,
    _foundation,
)
from tests.rehearsals.programme_candidate import PROGRAMME_REHEARSAL_PROFILE
from tests.support.programme_schema import admit_transaction_local_schema_candidate

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


@pytest.fixture
def world(monkeypatch):
    admit_transaction_local_schema_candidate(monkeypatch)
    monkeypatch.setattr(
        adoption,
        "ADOPTION_PROFILES",
        {
            **adoption.ADOPTION_PROFILES,
            ("programme_operations", 1): PROGRAMME_REHEARSAL_PROFILE,
        },
    )
    return _foundation("programme_operations")


def _scope(world, actor=None, **overrides):
    return {
        "actor_id": (actor or world[2]).id,
        "organization_id": world[0].id,
        "edition_id": world[1].id,
        **overrides,
    }


def _grant(world, recipient, capability):
    return grant_capability_direct(
        actor=world[2],
        approver=world[3],
        recipient=recipient,
        capability_code=capability,
        target=resolve_edition_target(
            organization_id=world[0].id, edition_id=world[1].id
        ),
        effective_from=timezone.now(),
        expires_at=None,
        reason="Synthetic independent stop-purpose authority.",
        correlation_id=uuid4(),
        source_channel="test",
    )


def test_actual_ordinary_controller_with_events_authority_is_admitted(world):
    recipient = world[4]
    for capability in ("authorization.manage_roles", "events.transition"):
        _grant(world, recipient, capability)
    assert require_programme_stop_controller(**_scope(world, recipient)) is None


@pytest.mark.parametrize("kind", ["stranger", "platform", "root_without_events"])
def test_identity_status_never_substitutes_for_ordinary_controller(world, kind):
    person = (
        AccountFactory(is_staff=True, is_superuser=True)
        if kind == "platform"
        else world[2]
        if kind == "root_without_events"
        else world[4]
    )
    with pytest.raises(AuthorizationDenied):
        require_programme_stop_controller(**_scope(world, person))


@pytest.mark.parametrize(
    "capability", ["authorization.manage_roles", "events.transition"]
)
def test_each_single_capability_is_insufficient(world, capability):
    recipient = world[4]
    _grant(world, recipient, capability)
    with pytest.raises(AuthorizationDenied):
        require_programme_stop_controller(**_scope(world, recipient))


@pytest.mark.parametrize("revoked", ["authorization.manage_roles", "events.transition"])
def test_actual_revocation_removes_stop_admission(world, revoked):
    recipient = world[4]
    grants = {
        code: _grant(world, recipient, code)
        for code in ("authorization.manage_roles", "events.transition")
    }
    require_programme_stop_controller(**_scope(world, recipient))
    revoke_capability_grant(
        actor=world[2],
        target=resolve_edition_target(
            organization_id=world[0].id, edition_id=world[1].id
        ),
        grant_id=grants[revoked].id,
        reason="End one independent synthetic prerequisite.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    with pytest.raises(AuthorizationDenied):
        require_programme_stop_controller(**_scope(world, recipient))


@pytest.mark.parametrize("field", ["organization_id", "edition_id"])
def test_exact_unknown_scope_is_not_discovered(world, field):
    with pytest.raises(AuthorizationDenied):
        require_programme_stop_controller(**_scope(world, **{field: uuid4()}))


@pytest.fixture
def reader(world):
    recipient = world[4]
    grants = tuple(
        _grant(world, recipient, code)
        for code in (
            "authorization.manage_roles",
            "events.transition",
        )
    )
    return recipient, grants


def _read(world, reader, **changes):
    return queries.load_programme_stop_authority(
        **{
            **_scope(world, reader[0]),
            "correlation_id": uuid4(),
            **changes,
        }
    )


def test_actual_impact_discloses_only_exact_outputs_and_audits_before_return(
    world, reader
):
    trace = uuid4()
    result = _read(world, reader, correlation_id=trace)
    assert {row.id for row in result.assignments} == {row.id for row in reader[1]}
    assert {row.disposition for row in result.assignments} == {"retained_historical"}
    assert str(reader[0].id) not in repr(result)
    assert (
        result.pending_requests,
        result.expired_requests,
        result.decided_requests,
    ) == (0, 0, 0)
    audit = AuditEvent.objects.get(correlation_id=trace)
    assert audit.operation == "authorization.query.programme_stop"
    assert audit.outcome == "allow"
    assert audit.safe_metadata == {}
    assert result == _read(world, reader)


def test_actual_pending_and_shared_outputs_remain_explicit_and_unchanged(world, reader):
    _command_request(world)
    requested = _command_request(
        world,
        scope=ProgrammeRoleScope(world[0].id, world[1].id, ScopeLevel.ORGANIZATION),
        details=ProgrammeRoleIntent(
            "venue-catalog",
            1,
            reader[0].id,
            world[3].id,
            None,
            None,
            "Synthetic shared venue purpose, deliberately retained.",
        ),
    )
    approved = _command_decision(
        world,
        requested,
        scope=ProgrammeRoleScope(world[0].id, world[1].id, ScopeLevel.ORGANIZATION),
    )
    result = _read(world, reader)
    assert (result.pending_requests, result.decided_requests) == (1, 1)
    shared = next(
        row for row in result.assignments if row.id == approved.role_assignment_id
    )
    assert (shared.scope_level, shared.disposition) == (
        "organization",
        "retained_shared",
    )
    assert "Synthetic shared venue purpose" not in repr(result)


def test_unrelated_organization_grants_and_other_editions_do_not_enter_the_preview(
    world, reader
):
    unrelated = grant_capability_direct(
        actor=world[2],
        approver=world[3],
        recipient=reader[0],
        capability_code="venues.view_properties",
        target=resolve_organization_target(organization_id=world[0].id),
        effective_from=timezone.now(),
        expires_at=None,
        reason="Synthetic unrelated shared access.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    result = _read(world, reader)
    assert unrelated.id not in {row.id for row in result.assignments}


def test_impact_overflow_and_audit_failure_release_no_partial_result(
    world, reader, monkeypatch
):
    with monkeypatch.context() as patch:
        patch.setattr(queries, "MAX_STOP_AUTHORITY_RECORDS", 1)
        with pytest.raises(queries.ProgrammeStopAuthorityUnavailableError):
            _read(world, reader)

    def audit_failure(*_args, **_kwargs):
        raise RuntimeError("Synthetic unavailable audit")

    monkeypatch.setattr(queries, "append_audit", audit_failure)
    with pytest.raises(RuntimeError, match="Synthetic unavailable audit"):
        _read(world, reader)


def test_denied_impact_never_discloses_a_target_or_counts(world):
    trace = uuid4()
    with pytest.raises(AuthorizationDenied):
        queries.load_programme_stop_authority(
            **_scope(world, world[4]), correlation_id=trace
        )
    audit = AuditEvent.objects.get(correlation_id=trace)
    assert audit.outcome == "deny"
    assert audit.target_id is None
    assert audit.safe_metadata == {}
