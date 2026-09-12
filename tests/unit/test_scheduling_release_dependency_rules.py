"""Complete journal interpretation separates approval, past work and privacy."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from itertools import product

import pytest
from django.core.exceptions import ValidationError

from maru.scheduling.release_dependency_rules import (
    ReleaseDependencyChangeWindow as Window,
)
from maru.scheduling.release_dependency_rules import (
    ReleaseDependencyConsequence as Consequence,
)
from maru.scheduling.release_dependency_rules import (
    ReleaseDependencyHorizon as Horizon,
)
from maru.scheduling.release_dependency_rules import (
    ReleaseDependencyUse as Use,
)
from maru.scheduling.release_dependency_rules import (
    evaluate_release_dependency,
)

END = datetime(2027, 1, 2, 12, tzinfo=UTC)


def evaluate(**overrides):
    values = {
        "captured_generation": 3,
        "current_generation": 5,
        "horizon": Horizon.OPERATIONAL,
        "use": Use.SERVING,
        "operational_ends_at": END,
        "changes": Window(2, 4, 5, END - timedelta(seconds=1)),
    }
    values.update(overrides)
    return evaluate_release_dependency(**values)


@pytest.mark.parametrize(("horizon", "use"), list(product(Horizon, Use)))
def test_unchanged_complete_dependency_is_current(horizon, use):
    assert (
        evaluate(
            current_generation=3,
            horizon=horizon,
            use=use,
            operational_ends_at=END if horizon is Horizon.OPERATIONAL else None,
            changes=Window(0, None, None, None),
        )
        is Consequence.CURRENT
    )


@pytest.mark.parametrize("horizon", list(Horizon))
def test_every_changed_dependency_stales_new_approval(horizon):
    assert (
        evaluate(
            horizon=horizon,
            use=Use.APPROVAL,
            operational_ends_at=END if horizon is Horizon.OPERATIONAL else None,
            changes=Window(2, 4, 5, END + timedelta(days=2)),
        )
        is Consequence.STALE
    )


def test_departed_approval_actor_does_not_rewrite_historical_approval():
    assert evaluate(horizon=Horizon.APPROVAL_ONLY, operational_ends_at=None) is (
        Consequence.CURRENT
    )


@pytest.mark.parametrize("delta", [-1, 0, 1, 100000])
def test_privacy_changes_have_no_operational_expiry(delta):
    assert (
        evaluate(
            horizon=Horizon.DISCLOSURE,
            operational_ends_at=None,
            changes=Window(2, 4, 5, END + timedelta(seconds=delta)),
        )
        is Consequence.INVALIDATED
    )


@pytest.mark.parametrize(
    ("delta", "expected"),
    [(-1, Consequence.INVALIDATED), (0, Consequence.CURRENT), (1, Consequence.CURRENT)],
)
def test_operational_change_uses_immutable_half_open_end(delta, expected):
    assert evaluate(changes=Window(2, 4, 5, END + timedelta(seconds=delta))) is expected


def test_operational_comparison_uses_instants_not_zone_labels():
    same_instant = END.astimezone(timezone(timedelta(hours=3)))
    assert evaluate(changes=Window(2, 4, 5, same_instant)) is Consequence.CURRENT


@pytest.mark.parametrize(
    "window",
    [
        Window(0, None, None, None),
        Window(1, 4, 5, END),
        Window(3, 4, 5, END),
        Window(2, 3, 5, END),
        Window(2, 4, 6, END),
        Window(2, None, 5, END),
        Window(2, 4, None, END),
        Window(2, 4, 5, None),
    ],
)
def test_missing_or_noncontiguous_journal_never_means_no_invalidation(window):
    assert evaluate(changes=window) is Consequence.UNAVAILABLE


def test_regressed_generation_and_nonempty_equal_range_are_unavailable():
    assert evaluate(current_generation=2) is Consequence.UNAVAILABLE
    assert evaluate(current_generation=3, changes=Window(0, 3, 3, END)) is (
        Consequence.UNAVAILABLE
    )


@pytest.mark.parametrize("field", ["captured_generation", "current_generation"])
@pytest.mark.parametrize("value", [True, 0, -1, 1.5, "3", 2**63 - 1])
def test_generations_are_positive_bounded_integers(field, value):
    with pytest.raises(ValidationError):
        evaluate(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("horizon", "operational"),
        ("use", "serving"),
        ("changes", {}),
        ("operational_ends_at", None),
        ("operational_ends_at", END.replace(tzinfo=None)),
    ],
)
def test_closed_purpose_and_aware_time_shape_are_required(field, value):
    with pytest.raises(ValidationError):
        evaluate(**{field: value})


@pytest.mark.parametrize("horizon", [Horizon.APPROVAL_ONLY, Horizon.DISCLOSURE])
def test_nonoperational_dependency_cannot_have_a_hidden_expiry(horizon):
    with pytest.raises(ValidationError):
        evaluate(horizon=horizon)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("count", True),
        ("count", -1),
        ("count", 2**63 - 1),
        ("first_generation", True),
        ("last_generation", 0),
        ("earliest_changed_at", END.replace(tzinfo=None)),
    ],
)
def test_journal_aggregation_rejects_malformed_metadata(field, value):
    with pytest.raises(ValidationError):
        evaluate(changes=replace(Window(2, 4, 5, END), **{field: value}))
