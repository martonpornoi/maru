"""Complete own-purpose discovery boundaries, lock order and late failure safety."""

from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.db import DatabaseError

from maru.authorization.policy import PolicyDecision
from maru.events.personal_timetable_queries import PersonalTimetableEditionChoice
from maru.events.queries import EditionAdoptionProfileReference
from maru.identity.queries import ActiveVerifiedPersonReference
from maru.organizations.personal_timetable_references import (
    PersonalTimetableOrganizerLabels,
)
from maru.programme.personal_scope_references import (
    PersonalHostScopeProof,
    PersonalHostScopeSet,
)
from maru.scheduling import personal_discovery_queries as queries
from maru.workforce.personal_scope_references import (
    PersonalShiftScopeProof,
    PersonalShiftScopeSet,
)


def decision(fields):
    return PolicyDecision(
        allowed=True,
        fields=frozenset(fields),
        obligations=frozenset({"audit_sensitive_read"}),
        reason_code="exact_self",
    )


@pytest.fixture
def world(monkeypatch):
    actor, organization, edition, series, correlation = (
        UUID(int=value) for value in range(1, 6)
    )
    scopes = ((organization, edition),)
    trace = []
    mocks = {
        "resolve_active_verified_person_reference": Mock(
            side_effect=lambda **kwargs: (
                trace.append(("person", kwargs.get("lock", False)))
                or ActiveVerifiedPersonReference(actor)
            )
        ),
        "personal_host_scope_candidates": Mock(
            return_value=PersonalHostScopeSet(actor, scopes)
        ),
        "personal_shift_scope_candidates": Mock(
            return_value=PersonalShiftScopeSet(actor, scopes)
        ),
        "authorize_personal_timetable_scope": Mock(),
        "_adopted_layers": Mock(return_value=(True, True)),
        "edition_adoption_profile_reference": Mock(
            return_value=EditionAdoptionProfileReference("synthetic", 1)
        ),
        "authorize_scheduling_scope": Mock(
            return_value=SimpleNamespace(
                actor_id=actor,
                organization_id=organization,
                edition_id=edition,
                decision=decision({"own_host_schedule"}),
            )
        ),
        "lock_edition_ownership": Mock(
            side_effect=lambda **kwargs: (
                trace.append(
                    ("parent", kwargs["organization_id"], kwargs["edition_id"])
                )
                or True
            )
        ),
        "personal_host_scope_proof": Mock(
            return_value=PersonalHostScopeProof(
                actor,
                organization,
                edition,
                present=True,
                decision=decision({"own_host_relationship", "own_host_invitation"}),
            )
        ),
        "personal_shift_scope_proof": Mock(
            return_value=PersonalShiftScopeProof(
                actor,
                organization,
                edition,
                present=True,
                decision=decision({"shifts"}),
            )
        ),
        "resolve_personal_timetable_edition_choice": Mock(
            return_value=PersonalTimetableEditionChoice(
                organization, edition, series, "Example 2026", "2026", 1
            )
        ),
        "resolve_personal_timetable_organizer_labels": Mock(
            return_value=PersonalTimetableOrganizerLabels(
                organization,
                series,
                "Example organizer",
                "example",
                "Example con",
                "con",
            )
        ),
        "append_audit": Mock(),
    }
    for name, mock in mocks.items():
        monkeypatch.setattr(queries, name, mock)
    monkeypatch.setattr(queries.transaction, "atomic", nullcontext)
    return SimpleNamespace(
        actor=actor,
        organization=organization,
        edition=edition,
        series=series,
        correlation=correlation,
        trace=trace,
        mocks=mocks,
    )


def load(world):
    return queries.load_personal_timetable_editions(
        actor_id=world.actor, correlation_id=world.correlation
    )


def test_complete_labels_only_and_owner_bounded_audit(world):
    result = load(world)
    assert result.actor_id == world.actor
    assert len(result.choices) == 1
    assert result.choices[0].edition.name == "Example 2026"
    assert len(result.source_fingerprint) == 64
    assert "source_fingerprint" not in repr(result)
    assert world.trace.index(
        ("parent", world.organization, world.edition)
    ) < world.trace.index(("person", True))
    audits = [call.args[0] for call in world.mocks["append_audit"].call_args_list]
    assert {row.capability_code for row in audits} == {
        "programme.view_host_self",
        "workforce.view_self",
    }
    assert all(
        row.principal_id == world.actor and row.target_id == world.edition
        for row in audits
    )
    assert all(
        set(row.safe_metadata) == {"policy_version", "access_purpose"} for row in audits
    )


@pytest.mark.parametrize("layers", [(True, False), (False, True)])
def test_unadopted_layer_never_loads_its_proof_or_content(world, layers):
    world.mocks["_adopted_layers"].return_value = layers
    result = load(world)
    assert len(result.choices) == 1
    absent = "personal_shift_scope_proof" if layers[0] else "personal_host_scope_proof"
    world.mocks[absent].assert_not_called()
    assert world.mocks["append_audit"].call_count == 1


def test_no_actual_purpose_never_loads_label_or_audits(world):
    for name in ("personal_host_scope_proof", "personal_shift_scope_proof"):
        world.mocks[name].return_value = replace(
            world.mocks[name].return_value, present=False
        )
    assert load(world).choices == ()
    world.mocks["resolve_personal_timetable_edition_choice"].assert_not_called()
    world.mocks["resolve_personal_timetable_organizer_labels"].assert_not_called()
    world.mocks["append_audit"].assert_not_called()


def test_denied_scope_never_locks_or_loads_proof_or_labels(world):
    world.mocks["authorize_personal_timetable_scope"].side_effect = queries.Denied
    assert load(world).choices == ()
    for name in (
        "lock_edition_ownership",
        "personal_host_scope_proof",
        "personal_shift_scope_proof",
        "resolve_personal_timetable_edition_choice",
        "append_audit",
    ):
        world.mocks[name].assert_not_called()


@pytest.mark.parametrize(
    "name", ["personal_host_scope_candidates", "personal_shift_scope_candidates"]
)
@pytest.mark.parametrize(
    "defect",
    [
        "wrong_actor",
        "zero",
        "string",
        "duplicate",
        "unsorted",
        "overflow",
        "not_tuple",
        "not_dto",
    ],
)
def test_incomplete_or_foreign_candidates_fail_before_labels(world, name, defect):
    mock = world.mocks[name]
    original = mock.return_value
    changes = {
        "wrong_actor": replace(original, actor_id=UUID(int=99)),
        "zero": replace(original, scopes=((world.organization, UUID(int=0)),)),
        "string": replace(original, scopes=((world.organization, str(world.edition)),)),
        "duplicate": replace(original, scopes=original.scopes * 2),
        "unsorted": replace(
            original, scopes=((world.organization, UUID(int=99)), *original.scopes)
        ),
        "overflow": replace(
            original,
            scopes=tuple((world.organization, UUID(int=i)) for i in range(100, 357)),
        ),
        "not_tuple": replace(original, scopes=list(original.scopes)),
        "not_dto": None,
    }
    mock.return_value = changes[defect]
    with pytest.raises(queries.Unavailable):
        load(world)
    world.mocks["resolve_personal_timetable_edition_choice"].assert_not_called()


def test_combined_bound_is_not_a_per_owner_truncation(world):
    for name, start in (
        ("personal_host_scope_candidates", 100),
        ("personal_shift_scope_candidates", 300),
    ):
        mock = world.mocks[name]
        mock.return_value = replace(
            mock.return_value,
            scopes=tuple(
                (world.organization, UUID(int=i)) for i in range(start, start + 150)
            ),
        )
    with pytest.raises(queries.Unavailable):
        load(world)
    world.mocks["lock_edition_ownership"].assert_not_called()


@pytest.mark.parametrize(
    "name", ["personal_host_scope_proof", "personal_shift_scope_proof"]
)
@pytest.mark.parametrize(
    "defect",
    ["person", "organization", "edition", "presence", "denial", "fields", "missing"],
)
def test_every_owner_proof_is_independently_validated(world, name, defect):
    mock = world.mocks[name]
    original = mock.return_value
    wrong = UUID(int=99)
    mock.return_value = {
        "person": replace(original, actor_id=wrong),
        "organization": replace(original, organization_id=wrong),
        "edition": replace(original, edition_id=wrong),
        "presence": replace(original, present=1),
        "denial": replace(original, decision=replace(original.decision, allowed=False)),
        "fields": replace(
            original, decision=replace(original.decision, fields=frozenset())
        ),
        "missing": None,
    }[defect]
    with pytest.raises(queries.Unavailable):
        load(world)
    world.mocks["resolve_personal_timetable_edition_choice"].assert_not_called()


@pytest.mark.parametrize(
    "source",
    ["candidates", "profile", "proof", "label", "organizer", "person", "audit"],
)
def test_late_change_or_required_evidence_failure_never_releases_old_choices(
    world, source
):
    names = {
        "candidates": "personal_host_scope_candidates",
        "profile": "edition_adoption_profile_reference",
        "proof": "personal_host_scope_proof",
        "label": "resolve_personal_timetable_edition_choice",
        "organizer": "resolve_personal_timetable_organizer_labels",
        "person": "resolve_active_verified_person_reference",
        "audit": "append_audit",
    }
    mock = world.mocks[names[source]]
    initial = mock.return_value
    if source == "person":
        mock.side_effect = lambda **kwargs: (
            None if kwargs.get("lock") else ActiveVerifiedPersonReference(world.actor)
        )
    elif source == "audit":
        mock.side_effect = DatabaseError("required audit failed")
    else:
        altered = {
            "candidates": lambda: replace(initial, scopes=()),
            "profile": lambda: replace(initial, version=2),
            "proof": lambda: replace(initial, present=False),
            "label": lambda: replace(initial, name="Changed"),
            "organizer": lambda: replace(initial, series_name="Changed"),
        }[source]()
        mock.side_effect = [initial, altered]
    with pytest.raises((queries.Unavailable, queries.Denied)):
        load(world)


def test_new_scope_after_person_lock_is_not_locked(world):
    mock = world.mocks["personal_host_scope_candidates"]
    original = mock.return_value
    mock.side_effect = [
        original,
        replace(original, scopes=(*original.scopes, (UUID(int=80), UUID(int=90)))),
    ]
    with pytest.raises(queries.Unavailable):
        load(world)
    assert world.mocks["lock_edition_ownership"].call_count == 1


def test_all_distinct_parents_precede_person_lock_in_canonical_order(world):
    first = (world.organization, world.edition)
    second = (UUID(int=20), UUID(int=30))
    mock = world.mocks["personal_shift_scope_candidates"]
    mock.return_value = replace(mock.return_value, scopes=(first, second))
    world.mocks["_adopted_layers"].return_value = (False, True)
    world.mocks["personal_shift_scope_proof"].side_effect = lambda **kwargs: (
        PersonalShiftScopeProof(**kwargs, present=False, decision=decision({"shifts"}))
    )
    assert load(world).choices == ()
    locks = [
        row for row in world.trace if row[0] == "parent" or row == ("person", True)
    ]
    assert locks == [("parent", *first), ("parent", *second), ("person", True)]


@pytest.mark.parametrize("value", [UUID(int=0), "1", None])
@pytest.mark.parametrize("key", ["actor_id", "correlation_id"])
def test_malformed_trusted_scope_never_queries(world, key, value):
    arguments = {
        "actor_id": world.actor,
        "correlation_id": world.correlation,
        key: value,
    }
    with pytest.raises(queries.Denied):
        queries.load_personal_timetable_editions(**arguments)
    world.mocks["personal_host_scope_candidates"].assert_not_called()
