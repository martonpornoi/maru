"""Window, cohort, audit/final-release and presentation boundaries without a DB."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError
from django.template.loader import render_to_string

from maru.core import home_guidance as shell
from maru.workforce import operating_home as owner
from maru.workforce.recent_outcomes import (
    OutcomeCandidate,
    RecentOutcomeFacts,
    RecentOutcomesUnavailableError,
    RecentShiftOutcome,
    RecentShiftOutcomes,
    select_outcome_candidates,
)
from tests.unit.test_workforce_operating_home import REFERENCE, _context

NOW = datetime(2030, 8, 1, 12, tzinfo=UTC)
ORG, EDITION = UUID(int=2), UUID(int=3)


def _row(number=1, **changes):
    return replace(
        OutcomeCandidate(
            UUID(int=number),
            4,
            "locked",
            UUID(int=number + 1000),
            ORG,
            EDITION,
            "locked",
            "locked",
            NOW,
        ),
        **changes,
    )


def _select(rows, at=NOW):
    return select_outcome_candidates(
        tuple(rows), organization_id=ORG, edition_id=EDITION, at=at
    )


@pytest.mark.parametrize("action", ["locked", "completed", "cancelled"])
def test_all_closed_outcomes_are_current_receipt_facts(action):
    row = _row(status=action, action=action, resulting_status=action)
    assert _select([row]) == (row,)


@pytest.mark.parametrize("count", [0, 5, 6, 128])
def test_complete_cohort_is_validated_before_presentation_selection(count):
    rows = [_row(n + 1) for n in range(count)]
    assert _select(rows) == tuple(reversed(rows))


def test_candidate_overflow_releases_no_sample():
    with pytest.raises(RecentOutcomesUnavailableError):
        _select([_row(n + 1) for n in range(129)])


@pytest.mark.parametrize(
    "changes",
    [
        {"version": 0},
        {"receipt_id": None},
        {"organization_id": UUID(int=99)},
        {"edition_id": UUID(int=99)},
        {"action": "reopened"},
        {"resulting_status": "open"},
        {"status": "open"},
        {"recorded_at": None},
        {"recorded_at": NOW.replace(tzinfo=None)},
        {"recorded_at": NOW + timedelta(microseconds=1)},
        {"recorded_at": NOW - timedelta(days=7, microseconds=1)},
    ],
    ids=[
        "version",
        "missing",
        "tenant",
        "edition",
        "reopened",
        "status",
        "parent",
        "time",
        "naive",
        "future",
        "expired",
    ],
)
def test_incoherent_evidence_withholds_even_other_valid_rows(changes):
    with pytest.raises(RecentOutcomesUnavailableError):
        _select([_row(), _row(2, **changes)])


def test_duplicate_demand_is_not_two_outcomes():
    with pytest.raises(RecentOutcomesUnavailableError):
        _select([_row(), _row(receipt_id=UUID(int=9999))])


def test_window_lower_boundary_is_inclusive_and_elapsed_utc():
    boundary = NOW - timedelta(days=7)
    assert _select([_row(recorded_at=boundary)])[0].recorded_at == boundary
    with pytest.raises(RecentOutcomesUnavailableError):
        _select([_row(recorded_at=boundary)], at=NOW + timedelta(microseconds=1))


@pytest.mark.parametrize(("month", "day"), [(4, 1), (10, 28)], ids=["spring", "autumn"])
def test_named_zone_dst_never_changes_the_seven_elapsed_utc_days(month, day):
    at = datetime(2026, month, day, 12, tzinfo=ZoneInfo("Europe/Budapest"))
    boundary = at.astimezone(UTC) - timedelta(days=7)
    assert _select([_row(recorded_at=boundary)], at=at)
    with pytest.raises(RecentOutcomesUnavailableError):
        _select([_row(recorded_at=boundary - timedelta(minutes=30))], at=at)


def test_deterministic_order_uses_receipt_then_demand_and_time_first():
    low = _row(1, receipt_id=UUID(int=8))
    high = _row(2, receipt_id=UUID(int=9))
    newest = _row(3, receipt_id=UUID(int=1), recorded_at=NOW + timedelta(seconds=1))
    assert _select([low, newest, high], at=newest.recorded_at) == (newest, high, low)


def _snapshot(**changes):
    item = RecentShiftOutcome(UUID(int=7), "Fictional <desk>", "locked", NOW)
    facts = RecentOutcomeFacts((item,), ("complete-cohort",), NOW + timedelta(days=7))
    return replace(owner._RecentSnapshot(facts, REFERENCE, NOW), **changes)


@pytest.mark.parametrize("elapsed", [5.0, 5.1])
def test_deadline_is_checked_after_source_probe(monkeypatch, elapsed):
    state = {"elapsed": 0.0}

    def read(*_args):
        state["elapsed"] = elapsed
        return _snapshot()

    monkeypatch.setattr(owner, "_read_recent", read)
    monkeypatch.setattr(owner, "monotonic", lambda: state["elapsed"])
    monkeypatch.setattr(owner.timezone, "now", lambda: NOW)
    with pytest.raises(owner.OperatingHomeUnavailableError):
        owner._check_recent(_context(), _snapshot(), owner._RecentBudget(5.0))


@pytest.mark.parametrize(
    "change", ["source", "lifecycle", "backward", "probe_clock", "expired"]
)
def test_fresh_probe_compares_whole_source_lifecycle_clock_and_window(
    monkeypatch, change
):
    snapshot = _snapshot()
    current = snapshot
    now = NOW
    if change == "source":
        current = replace(snapshot, facts=replace(snapshot.facts, signature=("moved",)))
    elif change == "lifecycle":
        current = replace(snapshot, reference=replace(REFERENCE, phase="retained"))
    elif change == "backward":
        current = replace(snapshot, at=NOW - timedelta(seconds=1))
    elif change == "probe_clock":
        now = NOW - timedelta(seconds=1)
    else:
        now = snapshot.facts.valid_until + timedelta(microseconds=1)
    monkeypatch.setattr(owner, "_read_recent", lambda *_args: current)
    monkeypatch.setattr(owner, "monotonic", lambda: 0.0)
    monkeypatch.setattr(owner.timezone, "now", lambda: now)
    with pytest.raises(owner.OperatingHomeUnavailableError):
        owner._check_recent(_context(), snapshot, owner._RecentBudget(5.0))


def test_expiry_equality_remains_eligible(monkeypatch):
    snapshot = _snapshot()
    monkeypatch.setattr(owner, "_read_recent", lambda *_args: snapshot)
    monkeypatch.setattr(owner, "monotonic", lambda: 0.0)
    monkeypatch.setattr(owner.timezone, "now", lambda: snapshot.facts.valid_until)
    assert (
        owner._check_recent(_context(), snapshot, owner._RecentBudget(5.0))
        == snapshot.facts.valid_until
    )


def test_backward_clock_between_successful_probes_cannot_relabel_old_facts(monkeypatch):
    snapshot = _snapshot()
    monkeypatch.setattr(owner, "_read_recent", lambda *_args: snapshot)
    monkeypatch.setattr(owner, "monotonic", lambda: 0.0)
    clock = Mock(side_effect=[NOW + timedelta(seconds=2), NOW + timedelta(seconds=1)])
    monkeypatch.setattr(owner.timezone, "now", clock)
    budget = owner._RecentBudget(5.0)
    assert owner._check_recent(_context(), snapshot, budget) == NOW + timedelta(
        seconds=2
    )
    with pytest.raises(owner.OperatingHomeUnavailableError):
        owner._check_recent(_context(), snapshot, budget)


def test_platform_shortcut_cannot_admit_recent_facts(monkeypatch):
    monkeypatch.setattr(
        owner,
        "_authorize",
        lambda *_args: SimpleNamespace(reason_code="platform_administration"),
    )
    with pytest.raises(PermissionDenied):
        owner._authorize_recent(_context())


def test_prepare_repeats_policy_and_source_around_mandatory_audit(monkeypatch):
    trace = []
    snapshot = _snapshot()
    monkeypatch.setattr(owner, "_read_recent", lambda *_args: snapshot)
    monkeypatch.setattr(owner, "_check_recent", lambda *_args: trace.append("source"))
    monkeypatch.setattr(
        owner, "_authorize_recent", lambda *_args: trace.append("policy")
    )
    monkeypatch.setattr(owner, "_audit_recent", lambda *_args: trace.append("audit"))
    assert owner._prepare_recent(_context(), owner._RecentBudget(5.0)) == snapshot
    assert trace == ["source", "policy", "audit", "policy", "source"]


def test_revocation_after_audit_omits_all_facts(monkeypatch):
    monkeypatch.setattr(owner, "_read_recent", lambda *_args: _snapshot())
    monkeypatch.setattr(owner, "_check_recent", Mock())
    monkeypatch.setattr(
        owner, "_authorize_recent", Mock(side_effect=[None, PermissionDenied])
    )
    audit = Mock()
    monkeypatch.setattr(owner, "_audit_recent", audit)
    assert owner._prepare_recent(_context(), owner._RecentBudget(5.0)) is None
    audit.assert_called_once()


def test_audit_failure_cannot_release_prepared_rows(monkeypatch):
    monkeypatch.setattr(owner, "_read_recent", lambda *_args: _snapshot())
    monkeypatch.setattr(owner, "_check_recent", Mock())
    monkeypatch.setattr(owner, "_authorize_recent", Mock())
    monkeypatch.setattr(owner, "_audit_recent", Mock(side_effect=DatabaseError))
    with pytest.raises(DatabaseError):
        owner._prepare_recent(_context(), owner._RecentBudget(5.0))


def test_recent_retry_precedes_all_other_final_fences_and_keeps_one_deadline(
    monkeypatch,
):
    trace, deadlines = [], []

    def prepare(_context, deadline):
        deadlines.append(deadline)
        trace.append("audit")
        return _snapshot()

    count = 0

    def finalize(*_args):
        nonlocal count
        count += 1
        trace.append("recent-final")
        if count == 1:
            raise owner._RecentMovedError
        return RecentShiftOutcomes("empty", (), NOW)

    monkeypatch.setattr(owner, "_prepare_recent", prepare)
    monkeypatch.setattr(owner, "_finalize_recent", finalize)
    monkeypatch.setattr(
        owner, "_recheck_setup", lambda _c, value: trace.append("setup-final") or value
    )
    monkeypatch.setattr(
        owner, "_finalize_area", lambda _c, _p, item: trace.append("area-final") or item
    )
    item = SimpleNamespace(code="shift_history")
    _setup, items, recent = owner._finalize_components(
        _context(), None, ((None, item),)
    )
    assert trace == ["audit", "area-final", "setup-final", "recent-final"] * 2
    assert deadlines[0] == deadlines[1]
    assert items == (item,)
    assert recent.state == "empty"


def test_read_audit_contains_only_existing_purpose_envelope(monkeypatch):
    append = Mock()
    monkeypatch.setattr(owner, "append_audit", append)
    decision = SimpleNamespace(allowed=True, reason_code="allowed", obligations=())
    owner._audit_recent(_context(), decision, NOW)
    record = append.call_args.args[0]
    assert record.operation == "workforce.shift_outcomes.read"
    assert record.retention_class == "workforce-personal"
    assert record.capability_code == "workforce.view_shifts"
    assert set(record.safe_metadata) == {"policy_version", "route_name", "http_method"}
    assert record.changed_fields == ()
    assert "desk" not in repr(record)


@pytest.mark.parametrize("state", ["present", "empty", "unavailable"])
def test_semantic_component_escapes_label_and_preserves_ordinary_targets(state):
    label = "Fictional <script>desk</script> " + "X" * 128
    assert len(label) == 160
    items = (
        (
            shell.HomeRecentOutcome(
                label,
                "Coverage locked",
                NOW,
                "/exact/shift/",
            ),
        )
        if state == "present"
        else ()
    )
    recent = shell.HomeRecentOutcomes(
        state,
        items,
        NOW if state != "unavailable" else None,
        "Europe/Budapest",
        "/exact/shifts/",
    )
    html = render_to_string("core/_recent_shift_outcomes.html", {"recent": recent})
    assert "Past 7 days · up to 5 Shifts" in html
    assert 'href="/exact/shifts/"' in html
    assert "attendance, actual time, complete history or event readiness" in html
    if state == "present":
        assert "<ol " in html
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "X" * 128 in html
        assert 'href="/exact/shift/"' in html
        assert "14:00 CEST" in html
    elif state == "empty":
        assert "No recent Shift outcomes in this checked scope." in html
    else:
        assert "Recent Shift outcomes are unavailable. Refresh or use Shifts." in html
        assert "Checked <time" not in html
