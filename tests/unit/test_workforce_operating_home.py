"""Operating-home admission, partial failure, freshness and route presentation."""

from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError
from django.test import RequestFactory

from maru.core import home_guidance as presentation
from maru.events.adoption import adoption_profile
from maru.events.queries import EditionWorkPhaseReference
from maru.identity.models import Account
from maru.workforce import operating_home as owner
from maru.workforce.home_guidance import WorkforceSetupGuidance
from maru.workforce.home_states import OperatingHomeItem

NOW = datetime(2030, 8, 1, 12, tzinfo=UTC)
ACTOR, ORGANIZATION, EDITION, CORRELATION, RECORD = (UUID(int=n) for n in range(1, 6))
REFERENCE = EditionWorkPhaseReference(
    EDITION, ORGANIZATION, 1, "planning", "Europe/Budapest"
)


def _context():
    return owner._Context(
        SimpleNamespace(id=ACTOR), ORGANIZATION, EDITION, CORRELATION, "GET"
    )


def _arguments():
    context = _context()
    return {
        "actor": context.actor,
        "organization_id": ORGANIZATION,
        "edition_id": EDITION,
        "correlation_id": CORRELATION,
        "http_method": "GET",
    }


def _snapshot(code="shift_complete", priority=5, flags=(True,)):
    return owner._Snapshot(
        OperatingHomeItem(code, priority, RECORD, NOW), "stable", REFERENCE, flags
    )


def _isolate(monkeypatch):
    monkeypatch.setattr(owner, "_adopted", lambda _context: True)
    monkeypatch.setattr(owner, "_load_setup", lambda _context: None)
    monkeypatch.setattr(owner, "_recheck_setup", lambda _context, value: value)
    monkeypatch.setattr(owner, "_reference", lambda _context: REFERENCE)
    monkeypatch.setattr(
        owner,
        "_flags",
        lambda _context, area: {
            "assignments": (True, True),
            "availability": (),
            "shifts": (True,),
        }[area],
    )
    monkeypatch.setattr(
        owner, "_authorize", Mock(return_value=SimpleNamespace(allowed=True))
    )
    monkeypatch.setattr(
        owner, "_require", Mock(return_value=SimpleNamespace(allowed=True))
    )
    audit = Mock()
    monkeypatch.setattr(owner, "_audit", audit)
    return audit


def test_verified_principal_policy_receives_identity_and_exact_scope(monkeypatch):
    decision = Mock(return_value=SimpleNamespace(allowed=True))
    monkeypatch.setattr(owner, "decide_verified_principal_exact_edition", decision)
    fields = frozenset({"coverage_states"})
    owner._decision(_context(), "workforce.view_shifts", fields)
    arguments = decision.call_args.kwargs
    assert arguments["principal_id"] == ACTOR
    assert arguments["organization_id"] == ORGANIZATION
    assert arguments["edition_id"] == EDITION
    assert arguments["requested_fields"] == fields
    assert "principal" not in arguments


@pytest.mark.parametrize("area", ["assignments", "availability", "shifts"])
def test_incomplete_source_field_authority_stops_before_fact_queries(monkeypatch, area):
    context = _context()
    calls = []

    def decide(_context, code, fields):
        calls.append(code)
        return SimpleNamespace(
            allowed=True, fields=frozenset() if code != "events.view_basic" else fields
        )

    monkeypatch.setattr(owner, "_decision", decide)
    monkeypatch.setattr(owner, "repeatable_read_only_snapshot", nullcontext)
    source = Mock(side_effect=AssertionError("Private facts must not be queried"))
    for name in ["_assignments", "_availability", "_shifts"]:
        monkeypatch.setattr(owner, name, source)
    with pytest.raises(PermissionDenied):
        owner._read(context, area)
    source.assert_not_called()
    assert calls[0] == "events.view_basic"


def test_unadopted_owner_never_reads_setup_or_operating_state(monkeypatch):
    monkeypatch.setattr(owner, "_adopted", lambda _context: False)
    read = Mock(side_effect=AssertionError("Unadopted source queried"))
    monkeypatch.setattr(owner, "_load_setup", read)
    monkeypatch.setattr(owner, "_stable", read)
    assert owner.load_workforce_home_guidance(**_arguments()) is None
    read.assert_not_called()


def test_moving_source_is_bounded_and_never_audited_as_a_quiet_success(monkeypatch):
    audit = _isolate(monkeypatch)
    moving = [replace(_snapshot(), signature=str(n)) for n in range(4)]
    read = Mock(side_effect=moving)
    monkeypatch.setattr(owner, "_read", read)
    with pytest.raises(owner.OperatingHomeUnavailableError):
        owner._stable(_context(), "shifts")
    assert read.call_count == 4
    audit.assert_not_called()


def test_one_complete_retry_can_recover_from_source_movement(monkeypatch):
    _isolate(monkeypatch)
    read = Mock(
        side_effect=[
            replace(_snapshot(), signature="old"),
            _snapshot(),
            _snapshot(),
            _snapshot(),
        ]
    )
    monkeypatch.setattr(owner, "_read", read)
    result = owner._stable(_context(), "shifts")
    assert result.item.code == "shift_complete"
    assert read.call_count == 4


def test_revoked_read_authority_discards_prepared_item_and_target(monkeypatch):
    audit = _isolate(monkeypatch)
    monkeypatch.setattr(owner, "_authorize", Mock(side_effect=PermissionDenied))
    assert (
        owner._release_area(_context(), ("shifts", _snapshot().item, _snapshot()))
        is None
    )
    audit.assert_not_called()


@pytest.mark.parametrize("change", ["phase", "version", "management"])
def test_final_owner_or_action_movement_becomes_generic_unavailable(
    monkeypatch, change
):
    audit = _isolate(monkeypatch)
    if change == "management":
        monkeypatch.setattr(owner, "_flags", lambda *_args: (False,))
    else:
        reference = replace(
            REFERENCE,
            **(
                {"phase": "retained"} if change == "phase" else {"aggregate_version": 2}
            ),
        )
        monkeypatch.setattr(owner, "_reference", lambda *_args: reference)
    item = owner._release_area(_context(), ("shifts", _snapshot().item, _snapshot()))
    assert item.code == "shifts_unavailable"
    assert item.object_id is item.due_at is item.checked_at is None
    audit.assert_not_called()


def test_one_failed_area_preserves_other_areas_and_minimizes_logs(monkeypatch, caplog):
    _isolate(monkeypatch)

    def stable(_context, area):
        if area == "availability":
            raise DatabaseError("PRIVATE-PERSON-AND-WINDOW")
        return (
            _snapshot("assignment_review", 25, (True, True))
            if area == "assignments"
            else _snapshot()
        )

    monkeypatch.setattr(owner, "_stable", stable)
    result = owner.load_workforce_home_guidance(**_arguments())
    assert [item.code for item in result.operating] == [
        "assignment_review",
        "availability_unavailable",
        "shift_complete",
    ]
    assert "PRIVATE-PERSON-AND-WINDOW" not in repr(result)
    assert "PRIVATE-PERSON-AND-WINDOW" not in caplog.text


def test_audit_failure_keeps_that_area_unavailable_and_other_area_usable(monkeypatch):
    _isolate(monkeypatch)

    def stable(_context, area):
        if area == "availability":
            raise PermissionDenied
        return (
            _snapshot("assignment_review", 25, (True, True))
            if area == "assignments"
            else _snapshot()
        )

    def audit(_context, area, _decision, _at):
        if area == "assignments":
            raise RuntimeError("PRIVATE AUDIT FAILURE")

    monkeypatch.setattr(owner, "_stable", stable)
    monkeypatch.setattr(owner, "_audit", audit)
    result = owner.load_workforce_home_guidance(**_arguments())
    assert [item.code for item in result.operating] == [
        "assignments_unavailable",
        "shift_complete",
    ]
    assert result.operating[1].checked_at is not None


def test_profile_loss_after_preparation_releases_nothing(monkeypatch):
    audit = _isolate(monkeypatch)
    adopted = [True]
    monkeypatch.setattr(owner, "_adopted", lambda _context: adopted[0])

    def stable(_context, area):
        if area == "shifts":
            adopted[0] = False
        return _snapshot()

    monkeypatch.setattr(owner, "_stable", stable)
    assert owner.load_workforce_home_guidance(**_arguments()) is None
    audit.assert_not_called()


def test_setup_recheck_failure_does_not_discard_other_admitted_areas(monkeypatch):
    original = owner._recheck_setup
    _isolate(monkeypatch)
    monkeypatch.setattr(
        owner, "_require", Mock(side_effect=DatabaseError("private setup failure"))
    )
    result = original(_context(), WorkforceSetupGuidance("published", NOW))
    assert result.step == "unavailable"
    assert not result.can_manage


def test_grant_revocation_during_required_audit_discards_the_prepared_item(monkeypatch):
    _isolate(monkeypatch)
    revoked = [False]

    def authorize(_context, _area):
        if revoked[0]:
            raise PermissionDenied
        return SimpleNamespace(allowed=True)

    monkeypatch.setattr(owner, "_authorize", authorize)

    def revoke(*_args):
        revoked[0] = True

    monkeypatch.setattr(owner, "_audit", revoke)
    assert (
        owner._release_area(_context(), ("shifts", _snapshot().item, _snapshot()))
        is None
    )


def test_lifecycle_movement_during_audit_cannot_release_an_action(monkeypatch):
    _isolate(monkeypatch)
    changed = [False]
    monkeypatch.setattr(
        owner,
        "_reference",
        lambda _context: (
            replace(REFERENCE, aggregate_version=2) if changed[0] else REFERENCE
        ),
    )

    def change(*_args):
        changed[0] = True

    monkeypatch.setattr(owner, "_audit", change)
    result = owner._release_area(_context(), ("shifts", _snapshot().item, _snapshot()))
    assert result.code == "shifts_unavailable"
    assert result.object_id is result.due_at is result.checked_at is None


def test_exact_clock_boundary_invalidates_prepared_work_without_guessing(monkeypatch):
    audit = _isolate(monkeypatch)
    monkeypatch.setattr(owner.timezone, "now", lambda: NOW)
    snapshot = replace(_snapshot(), valid_until=NOW)
    result = owner._release_area(_context(), ("shifts", snapshot.item, snapshot))
    assert result.code == "shifts_unavailable"
    assert result.object_id is result.due_at is result.checked_at is None
    audit.assert_not_called()


def test_later_area_audit_revocation_filters_an_earlier_area_at_final_release(
    monkeypatch,
):
    _isolate(monkeypatch)
    revoked = set()

    def authorize(_context, area):
        if area in revoked:
            raise PermissionDenied
        return SimpleNamespace(allowed=True)

    def audit(_context, area, *_args):
        if area == "shifts":
            revoked.add("availability")

    monkeypatch.setattr(owner, "_authorize", authorize)
    monkeypatch.setattr(owner, "_audit", audit)
    monkeypatch.setattr(
        owner,
        "_stable",
        lambda _context, area: (
            _snapshot("availability_wait", flags=())
            if area == "availability"
            else _snapshot("assignment_review", flags=(True, True))
            if area == "assignments"
            else _snapshot()
        ),
    )
    result = owner.load_workforce_home_guidance(**_arguments())
    assert [item.code for item in result.operating] == [
        "assignment_review",
        "shift_complete",
    ]


def test_profile_loss_during_final_area_checks_releases_no_contribution(monkeypatch):
    _isolate(monkeypatch)
    adopted = [True]
    monkeypatch.setattr(owner, "_adopted", lambda _context: adopted[0])
    monkeypatch.setattr(owner, "_stable", lambda *_args: _snapshot())

    def finalize(_context, _prepared, item):
        adopted[0] = False
        return item

    monkeypatch.setattr(owner, "_finalize_area", finalize)
    assert owner.load_workforce_home_guidance(**_arguments()) is None


def test_final_setup_check_does_not_upgrade_retained_read_only_guidance(monkeypatch):
    original = owner._recheck_setup
    _isolate(monkeypatch)
    monkeypatch.setattr(
        owner, "_decision", lambda *_args: SimpleNamespace(allowed=True)
    )
    result = original(
        _context(), WorkforceSetupGuidance("read_only", NOW, can_manage=False)
    )
    assert result.step == "read_only"
    assert not result.can_manage


def test_missing_area_authority_does_not_suppress_an_independent_shift_read(
    monkeypatch,
):
    _isolate(monkeypatch)

    def stable(_context, area):
        if area != "shifts":
            raise PermissionDenied
        return _snapshot()

    monkeypatch.setattr(owner, "_stable", stable)
    result = owner.load_workforce_home_guidance(**_arguments())
    assert result.setup is None
    assert len(result.operating) == 1
    assert result.operating[0].code == "shift_complete"


def _request_and_edition():
    request = RequestFactory().get("/admin/")
    request.user = Account(id=ACTOR, email="home@example.invalid", is_active=True)
    request.correlation_id = str(CORRELATION)
    edition = SimpleNamespace(
        id=EDITION,
        organization_id=ORGANIZATION,
        time_zone="Europe/Budapest",
        slug="edition",
        organization=SimpleNamespace(slug="organizer"),
        series=SimpleNamespace(slug="series"),
    )
    return request, edition


@pytest.mark.parametrize(
    ("code", "record", "suffix", "state"),
    [
        ("assignment_review", RECORD, f"assignments/{RECORD}/", "Review"),
        ("assignment_wait_authority", None, "assignments/", "Waiting"),
        ("availability_wait", None, "availability/", "Waiting"),
        ("availability_empty", None, "availability/", "Review"),
        ("shift_claims", RECORD, f"shifts/{RECORD}/", "Review"),
        ("shift_wait_manager", RECORD, f"shifts/{RECORD}/", "Waiting"),
        ("shift_complete", RECORD, f"shifts/{RECORD}/", "Review"),
        ("shift_history", None, "shifts/", "Retained"),
    ],
)
def test_operating_links_keep_exact_owner_scope_and_safe_state(
    monkeypatch, code, record, suffix, state
):
    item = OperatingHomeItem(code, 10, record, NOW, NOW, "Europe/Budapest")
    monkeypatch.setattr(
        presentation,
        "load_workforce_home_guidance",
        lambda **_kwargs: owner.WorkforceHomeGuidance(None, (item,)),
    )
    request, edition = _request_and_edition()
    result = presentation.project_home_guidance(
        request, edition, adoption_profile("workforce_only", 1)
    )
    assert result.state == state
    assert result.action_url.endswith(suffix)
    assert "/organizer/series/series/editions/edition/" in result.action_url
    assert result.time_zone == "Europe/Budapest"
    assert result.due_at == (None if code.startswith("availability") else NOW)


def test_priority_and_attention_are_bounded_without_hiding_partial_failure(monkeypatch):
    bundle = owner.WorkforceHomeGuidance(
        WorkforceSetupGuidance("published", NOW, can_manage=True),
        (
            OperatingHomeItem("shift_complete", 5, RECORD),
            OperatingHomeItem("assignment_review", 25, RECORD),
            OperatingHomeItem("availability_unavailable", 60),
        ),
    )
    monkeypatch.setattr(
        presentation, "load_workforce_home_guidance", lambda **_kwargs: bundle
    )
    request, edition = _request_and_edition()
    result = presentation.project_home_guidance(
        request, edition, adoption_profile("workforce_only", 1)
    )
    assert result.title == "Review an ended, locked Shift"
    assert len(result.attention) == 3
    assert [item.area for item in result.attention] == [
        "Assignments",
        "Availability",
        "Team setup",
    ]
    assert result.attention[1].state == "Unavailable"
    assert not result.attention[1].action_url
    assert result.attention[2].state == "Published"


def test_unknown_owner_code_is_minimized_and_has_no_target():
    _request, edition = _request_and_edition()
    result = presentation._operating_item(
        OperatingHomeItem("PRIVATE-CORRUPT-CODE", 1, RECORD), edition
    )
    assert result.state == "Unavailable"
    assert not result.action_url
    assert "PRIVATE" not in repr(result)
