"""Release readiness is complete evidence, never an empty planning all-clear."""

from dataclasses import FrozenInstanceError, replace
from itertools import product

import pytest
from django.core.exceptions import ValidationError

from maru.scheduling.catalogs import (
    MAX_CONFLICTS,
)
from maru.scheduling.catalogs import (
    SchedulingConflictSeverity as Severity,
)
from maru.scheduling.release_eligibility import (
    RELEASE_ELIGIBILITY_POLICY,
    ReleaseCheckEvidence,
    ReleaseFinding,
    ReleaseWarningAcknowledgement,
    evaluate_release_eligibility,
)
from maru.scheduling.release_eligibility import (
    ReleaseCheck as Check,
)
from maru.scheduling.release_eligibility import (
    ReleaseCheckState as State,
)

SNAPSHOT = "a" * 64
OTHER = "b" * 64
FINGERPRINT = "c" * 64
ALL_CHECKS = tuple(
    ReleaseCheckEvidence(SNAPSHOT, check, State.SATISFIED) for check in Check
)
OPTIONAL = {Check.HOSTS, Check.STAFFING, Check.PERSON_CONFLICTS, Check.REST}


def evaluate(*, checks=ALL_CHECKS, findings=(), acknowledgements=(), snapshot=SNAPSHOT):
    return evaluate_release_eligibility(
        snapshot_digest=snapshot,
        checks=checks,
        findings=findings,
        acknowledgements=acknowledgements,
    )


def finding(severity=Severity.WARNING, fingerprint=FINGERPRINT):
    return ReleaseFinding(SNAPSHOT, Check.PHYSICAL_CONSTRAINTS, fingerprint, severity)


def acknowledgement(fingerprint=FINGERPRINT):
    return ReleaseWarningAcknowledgement(SNAPSHOT, fingerprint)


def assert_invalid(**kwargs):
    with pytest.raises(ValidationError) as exc:
        evaluate(**kwargs)
    assert exc.value.code == "scheduling_release_evidence_invalid"
    assert SNAPSHOT not in str(exc.value)
    assert FINGERPRINT not in str(exc.value)


def test_complete_current_sources_allow_review_without_approval_or_writes():
    result = evaluate()
    assert result.eligible_for_review
    assert result.snapshot_digest == SNAPSHOT
    assert RELEASE_ELIGIBILITY_POLICY == "scheduling.release-eligibility@1"
    assert not hasattr(result, "approved")
    assert not hasattr(result, "published")
    with pytest.raises(FrozenInstanceError):
        result.snapshot_digest = OTHER


def test_empty_evidence_is_unavailable_not_vacuously_eligible():
    result = evaluate(checks=())
    assert not result.eligible_for_review
    assert result.unavailable_checks == tuple(Check)


@pytest.mark.parametrize("missing", list(Check))
def test_every_missing_category_prevents_review(missing):
    result = evaluate(
        checks=tuple(row for row in ALL_CHECKS if row.check is not missing)
    )
    assert not result.eligible_for_review
    assert result.unavailable_checks == (missing,)


@pytest.mark.parametrize(("check", "state"), tuple(product(Check, State)))
def test_complete_category_state_truth_table(check, state):
    checks = tuple(
        replace(row, state=state) if row.check is check else row for row in ALL_CHECKS
    )
    result = evaluate(checks=checks)
    permitted = state is State.SATISFIED or (
        state is State.NOT_APPLICABLE and check in OPTIONAL
    )
    assert result.eligible_for_review is permitted
    assert result.stale_checks == ((check,) if state is State.STALE else ())
    assert result.unavailable_checks == ((check,) if state is State.UNAVAILABLE else ())
    blocked = state is State.BLOCKED or (
        state is State.NOT_APPLICABLE and check not in OPTIONAL
    )
    assert result.blocked_checks == ((check,) if blocked else ())


def test_planning_only_sources_cannot_stand_in_for_release_readiness():
    result = evaluate(
        checks=tuple(
            row
            for row in ALL_CHECKS
            if row.check
            in {
                Check.CANDIDATE,
                Check.HOSTS,
                Check.PHYSICAL_CONSTRAINTS,
            }
        )
    )
    assert not result.eligible_for_review
    assert set(result.unavailable_checks) == set(Check) - {
        Check.CANDIDATE,
        Check.HOSTS,
        Check.PHYSICAL_CONSTRAINTS,
    }


@pytest.mark.parametrize("severity", list(Severity))
def test_findings_prevent_review_even_if_category_claims_satisfied(severity):
    result = evaluate(findings=(finding(severity),))
    assert not result.eligible_for_review
    assert result.blocking_findings == (
        (FINGERPRINT,) if severity is Severity.BLOCKER else ()
    )
    assert result.unavailable_findings == (
        (FINGERPRINT,) if severity is Severity.UNAVAILABLE else ()
    )
    assert result.unacknowledged_warnings == (
        (FINGERPRINT,) if severity is Severity.WARNING else ()
    )


def test_exact_warning_acknowledgement_only_resolves_that_warning():
    warnings = (finding(), finding(fingerprint=OTHER))
    result = evaluate(findings=warnings, acknowledgements=(acknowledgement(),))
    assert not result.eligible_for_review
    assert result.unacknowledged_warnings == (OTHER,)
    result = evaluate(
        findings=warnings, acknowledgements=(acknowledgement(), acknowledgement(OTHER))
    )
    assert result.eligible_for_review


@pytest.mark.parametrize("severity", [Severity.BLOCKER, Severity.UNAVAILABLE])
def test_acknowledgement_never_waives_hard_or_unavailable_findings(severity):
    assert_invalid(findings=(finding(severity),), acknowledgements=(acknowledgement(),))


@pytest.mark.parametrize("state", [State.BLOCKED, State.STALE, State.UNAVAILABLE])
def test_acknowledged_warning_does_not_override_failed_category(state):
    checks = (replace(ALL_CHECKS[0], state=state), *ALL_CHECKS[1:])
    assert not evaluate(
        checks=checks, findings=(finding(),), acknowledgements=(acknowledgement(),)
    ).eligible_for_review


@pytest.mark.parametrize("part", ["checks", "findings", "acknowledgements"])
def test_every_piece_must_bind_the_exact_snapshot(part):
    kwargs = {
        "checks": ALL_CHECKS,
        "findings": (finding(),),
        "acknowledgements": (acknowledgement(),),
    }
    rows = kwargs[part]
    kwargs[part] = (replace(rows[0], snapshot_digest=OTHER), *rows[1:])
    assert_invalid(**kwargs)


def test_changed_scope_candidate_policy_or_dependency_requires_new_evidence():
    # The owner collector hashes each of these into the snapshot. The policy
    # refuses retained evidence for any different exact fingerprint.
    assert_invalid(snapshot=OTHER)
    fresh = tuple(replace(row, snapshot_digest=OTHER) for row in ALL_CHECKS)
    assert evaluate(checks=fresh, snapshot=OTHER).eligible_for_review
    assert_invalid(checks=fresh, snapshot=OTHER, findings=(finding(),))


@pytest.mark.parametrize("part", ["checks", "findings", "acknowledgements"])
def test_duplicate_evidence_is_rejected_not_deduplicated(part):
    kwargs = {
        "checks": ALL_CHECKS,
        "findings": (finding(),),
        "acknowledgements": (acknowledgement(),),
    }
    rows = kwargs[part]
    kwargs[part] = (rows[0], rows[0])
    assert_invalid(**kwargs)


def test_warning_from_missing_category_is_not_a_complete_source_result():
    assert_invalid(checks=(), findings=(finding(),))


@pytest.mark.parametrize("severity", list(Severity))
def test_inapplicable_category_cannot_also_supply_findings(severity):
    checks = tuple(
        replace(row, state=State.NOT_APPLICABLE) if row.check is Check.HOSTS else row
        for row in ALL_CHECKS
    )
    assert_invalid(
        checks=checks,
        findings=(replace(finding(severity), check=Check.HOSTS),),
    )


def test_orphaned_or_changed_warning_acknowledgement_is_rejected():
    assert_invalid(acknowledgements=(acknowledgement(),))
    assert_invalid(
        findings=(finding(fingerprint=OTHER),), acknowledgements=(acknowledgement(),)
    )


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        1,
        "",
        "a" * 63,
        "a" * 65,
        "A" * 64,
        "g" * 64,
        SNAPSHOT + "\n",
        [],
        {},
    ],
)
def test_digest_input_contract_is_closed(value):
    assert_invalid(snapshot=value)
    assert_invalid(checks=(replace(ALL_CHECKS[0], snapshot_digest=value),))
    assert_invalid(findings=(replace(finding(), fingerprint=value),))
    assert_invalid(
        findings=(finding(),),
        acknowledgements=(replace(acknowledgement(), finding_fingerprint=value),),
    )


@pytest.mark.parametrize("part", ["checks", "findings", "acknowledgements"])
@pytest.mark.parametrize("value", [None, True, [], {}, "", iter(())])
def test_collections_are_bounded_immutable_tuples_not_streams(part, value):
    assert_invalid(**{part: value})


@pytest.mark.parametrize("part", ["checks", "findings", "acknowledgements"])
def test_collection_limits_are_checked_before_any_rows(part):
    maximum = len(Check) if part == "checks" else MAX_CONFLICTS
    assert_invalid(**{part: (None,) * (maximum + 1)})


@pytest.mark.parametrize("part", ["checks", "findings", "acknowledgements"])
def test_rows_require_exact_closed_types(part):
    assert_invalid(**{part: (object(),)})


@pytest.mark.parametrize("value", [None, "candidate", "unknown", [], True])
def test_category_requires_the_closed_enum(value):
    assert_invalid(checks=(replace(ALL_CHECKS[0], check=value),))
    assert_invalid(findings=(replace(finding(), check=value),))


@pytest.mark.parametrize(
    "value", [None, "satisfied", "not_evaluated", "unknown", [], True]
)
def test_state_requires_the_closed_enum(value):
    assert_invalid(checks=(replace(ALL_CHECKS[0], state=value),))


@pytest.mark.parametrize("value", [None, "warning", "unknown", [], True])
def test_severity_requires_the_closed_enum(value):
    assert_invalid(findings=(replace(finding(), severity=value),))


def test_exact_limit_is_complete_and_cannot_hide_the_last_warning():
    warnings = tuple(
        finding(fingerprint=f"{index:064x}") for index in range(MAX_CONFLICTS)
    )
    receipts = tuple(acknowledgement(row.fingerprint) for row in warnings)
    result = evaluate(findings=warnings, acknowledgements=receipts[:-1])
    assert not result.eligible_for_review
    assert result.unacknowledged_warnings == (warnings[-1].fingerprint,)
    assert evaluate(findings=warnings, acknowledgements=receipts).eligible_for_review


def test_order_does_not_change_results_and_input_objects_are_unchanged():
    checks = tuple(replace(row, state=State.STALE) for row in ALL_CHECKS)
    findings = (finding(fingerprint=OTHER), finding())
    receipts = (acknowledgement(),)
    before = (checks, findings, receipts)
    forward = evaluate(checks=checks, findings=findings, acknowledgements=receipts)
    reverse = evaluate(
        checks=checks[::-1], findings=findings[::-1], acknowledgements=receipts[::-1]
    )
    assert forward == reverse
    assert before == (checks, findings, receipts)
    assert forward.stale_checks == tuple(Check)
