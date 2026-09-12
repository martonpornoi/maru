"""Real exact-self policy and minimized owner rows for personal hosting outputs."""

from dataclasses import asdict, replace
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection
from django.test.utils import CaptureQueriesContext

from maru.audit.models import AuditEvent
from maru.authorization import policy
from maru.programme import queries
from maru.programme import timetable_queries as outputs
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.models import ProgrammeHostInvitation
from maru.programme.queries import ProgrammeQueryUnavailableError
from tests.factories import AccountFactory, EventEditionFactory
from tests.integration.test_programme_hosts import invite, respond
from tests.integration.test_programme_hosts import world as world  # noqa: PLC0414

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def personal_world(world, monkeypatch):
    original = policy.profile_allows_capability
    # Admit only dormant host-self reading; keep real Identity/self/field policy.
    monkeypatch.setattr(
        policy,
        "profile_allows_capability",
        lambda code, version, capability: (
            capability == "programme.view_host_self"
            or original(code, version, capability)
        ),
    )
    return world


def arguments(world):
    return {
        "actor_id": world[1].id,
        "organization_id": world[2]["organization_id"],
        "edition_id": world[2]["edition_id"],
        "correlation_id": uuid4(),
    }


def test_real_personal_host_read_is_minimized_and_audited(personal_world):
    invited = invite(personal_world)
    confirmed = respond(personal_world, invited)
    with CaptureQueriesContext(connection) as captured:
        (entry,) = outputs.load_personal_host_purposes(**arguments(personal_world))
    assert entry.host_id == invited.host_id
    assert entry.item_id == personal_world[2]["item_id"]
    assert entry.state == "confirmed"
    assert entry.version == confirmed.resulting_host_version
    assert entry.title == "Visible session"
    assert entry.briefing == "Host-only briefing"
    assert set(asdict(entry)) == {
        "host_id",
        "item_id",
        "role",
        "state",
        "version",
        "invitation_sequence",
        "title",
        "briefing",
    }
    statements = "\n".join(row["sql"] for row in captured)
    for excluded in (
        'FROM "programme_programmehostavailabilitywindow"',
        'FROM "programme_programmehostrevision"',
        'FROM "programme_programmeworkingrevision"',
        'FROM "programme_programmepublicrendition"',
        'FROM "participation_',
        'FROM "registration_',
        'FROM "scheduling_',
    ):
        assert excluded not in statements
    selected = "\n".join(
        row["sql"].split(" FROM ", 1)[0]
        for row in captured
        if row["sql"].startswith("SELECT")
        and 'FROM "programme_programmehost' in row["sql"]
    )
    for excluded in ("reason", "actor_id", "availability", "last_modified_by"):
        assert excluded not in selected
    evidence = AuditEvent.objects.get(
        operation="programme.query.personal_host_timetable"
    )
    assert evidence.principal_id == personal_world[1].id
    assert evidence.capability_code == "programme.view_host_self"


@pytest.mark.parametrize("action", [None, "decline", "confirm", "withdraw"])
def test_retained_purpose_states_are_not_silently_promoted_to_work(
    personal_world, action
):
    invitation = invite(personal_world)
    if action == "withdraw":
        confirmed = respond(personal_world, invitation)
        respond(personal_world, confirmed, "withdraw")
    elif action:
        respond(personal_world, invitation, action)
    (result,) = outputs.load_personal_host_purposes(**arguments(personal_world))
    assert (
        result.state
        == {
            None: "invited",
            "decline": "declined",
            "confirm": "confirmed",
            "withdraw": "withdrawn",
        }[action]
    )


def test_other_persons_purpose_is_not_loaded(personal_world):
    invite(personal_world)
    inputs = arguments(personal_world) | {"actor_id": AccountFactory().id}
    with CaptureQueriesContext(connection) as captured:
        assert outputs.load_personal_host_purposes(**inputs) == ()
    assert not any(
        'FROM "programme_programmehostinvitation"' in row["sql"] for row in captured
    )


def test_unadopted_profile_denies_before_private_rows(world):
    invite(world)
    with (
        CaptureQueriesContext(connection) as captured,
        pytest.raises(ProgrammeAuthorizationDeniedError),
    ):
        outputs.load_personal_host_purposes(**arguments(world))
    assert not any('FROM "programme_programmehost' in row["sql"] for row in captured)


def test_foreign_edition_scope_denies(personal_world):
    invite(personal_world)
    foreign = EventEditionFactory()
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        outputs.load_personal_host_purposes(
            **(arguments(personal_world) | {"edition_id": foreign.id})
        )


def test_final_field_reauthorization_withholds_materialized_purposes(
    personal_world, monkeypatch
):
    invite(personal_world)
    original = outputs._purposes

    def moving(*args):
        result = original(*args)
        decide = policy.decide_verified_principal_exact_self
        monkeypatch.setattr(
            "maru.programme.authorization.decide_verified_principal_exact_self",
            lambda **kwargs: replace(decide(**kwargs), fields=frozenset()),
        )
        return result

    monkeypatch.setattr(outputs, "_purposes", moving)
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        outputs.load_personal_host_purposes(**arguments(personal_world))
    assert not AuditEvent.objects.filter(
        operation="programme.query.personal_host_timetable", outcome="allow"
    ).exists()


def test_audit_failure_does_not_disclose_a_result(personal_world):
    invite(personal_world)
    with (
        patch.object(
            queries, "_append_query_audit", side_effect=RuntimeError("audit down")
        ),
        pytest.raises(RuntimeError, match="audit down"),
    ):
        outputs.load_personal_host_purposes(**arguments(personal_world))


def test_bound_and_database_failure_do_not_return_partial_purposes(
    personal_world, monkeypatch
):
    invite(personal_world)
    monkeypatch.setattr(outputs, "MAX_PERSONAL_HOST_PURPOSES", 0)
    with pytest.raises(ProgrammeQueryUnavailableError):
        outputs.load_personal_host_purposes(**arguments(personal_world))
    with (
        patch.object(outputs, "_purposes", side_effect=DatabaseError),
        pytest.raises(ProgrammeQueryUnavailableError),
    ):
        outputs.load_personal_host_purposes(**arguments(personal_world))


def test_missing_exact_invitation_withholds_whole_purpose_list(personal_world):
    invite(personal_world)
    with (
        patch.object(
            ProgrammeHostInvitation.objects,
            "filter",
            return_value=ProgrammeHostInvitation.objects.none(),
        ),
        pytest.raises(ProgrammeQueryUnavailableError),
    ):
        outputs.load_personal_host_purposes(**arguments(personal_world))


@pytest.mark.parametrize("value", [None, "not-a-uuid", UUID(int=0)])
def test_malformed_personal_scope_is_rejected_without_reads(personal_world, value):
    with CaptureQueriesContext(connection) as captured, pytest.raises(ValidationError):
        outputs.load_personal_host_purposes(
            **(arguments(personal_world) | {"actor_id": value})
        )
    assert not captured
