"""Fresh independent republication after an explicit retained-work change."""

from dataclasses import replace
from uuid import uuid4

from tests.rehearsals.programme_planning_scenario import _request
from tests.rehearsals.programme_release_preparation import (
    _command_request,
    _manifest,
    _preflight,
    _require,
    _retry_equal,
)


def republish_after_work_change(setup, planning, release):
    """Require new owner evidence; never recover an invalidated predecessor's copy."""
    from maru.scheduling.authorization import (  # noqa: PLC0415
        SchedulingAuthorizationDeniedError,
    )
    from maru.scheduling.command_support import (  # noqa: PLC0415
        SchedulingVersionConflictError,
    )
    from maru.scheduling.release_impact_queries import (  # noqa: PLC0415
        load_programme_release_impact,
    )
    from maru.scheduling.release_inputs import (  # noqa: PLC0415
        ReleaseApprovalIntent,
        ReleaseCandidateSelection,
        ReleasePublicationIntent,
    )
    from maru.scheduling.release_publication_commands import (  # noqa: PLC0415
        publish_programme_release,
    )
    from maru.scheduling.release_queries import ProgrammeReleaseState  # noqa: PLC0415
    from maru.scheduling.release_review_commands import (  # noqa: PLC0415
        approve_programme_release,
    )

    publisher, reviewer = planning.planner, release.reviewer
    before = _manifest(setup, publisher)
    _require(
        before.state == ProgrammeReleaseState.INVALIDATED
        and before.release_id == release.release_id
        and before.pointer_version == 1
        and before.is_active
        and not before.selections,
        "successor_requires_invalidated_original",
    )
    evidence = _preflight(setup, publisher, planning)
    _require(
        evidence.snapshot_digest != release.source_digest
        and _preflight(setup, reviewer, planning) == evidence,
        "successor_requires_fresh_owner_evidence",
    )
    intent = ReleaseApprovalIntent(
        ReleaseCandidateSelection(
            planning.candidate_id,
            planning.candidate_revision_id,
            planning.candidate_version,
            evidence.snapshot_digest,
        )
    )
    try:
        approve_programme_release(_command_request(setup, publisher), intent=intent)
    except SchedulingAuthorizationDeniedError:
        pass
    else:
        raise RuntimeError("successor_author_approval_accepted")
    request = _command_request(setup, reviewer)
    approved = approve_programme_release(request, intent=intent)
    _retry_equal(approved, approve_programme_release(request, intent=intent))
    _require(_manifest(setup, publisher) == before, "successor_approval_published")
    publication = ReleasePublicationIntent(
        approved.object_id, release.release_id, 1, evidence.snapshot_digest
    )
    try:
        publish_programme_release(_command_request(setup, reviewer), intent=publication)
    except SchedulingAuthorizationDeniedError:
        pass
    else:
        raise RuntimeError("successor_approver_publication_accepted")
    try:
        publish_programme_release(
            _command_request(setup, publisher),
            intent=replace(publication, expected_release_version=2),
        )
    except SchedulingVersionConflictError:
        pass
    else:
        raise RuntimeError("successor_stale_pointer_accepted")
    _require(_manifest(setup, publisher) == before, "successor_failure_moved_pointer")
    request = _command_request(setup, publisher)
    published = publish_programme_release(request, intent=publication)
    _retry_equal(published, publish_programme_release(request, intent=publication))
    after = _manifest(setup, publisher)
    impact = load_programme_release_impact(
        _request(setup, publisher, read=True), release_id=published.object_id
    )
    _require(
        published.version == 2
        and published.object_id != release.release_id
        and after.state == ProgrammeReleaseState.AVAILABLE
        and after.release_id == published.object_id
        and after.is_active
        and after.pointer_version == 2
        and impact.release_id == published.object_id
        and impact.previous_release_id == release.release_id
        and impact.release_version == impact.observed_pointer_version == 2
        and impact.is_active
        and impact.before_state == ProgrammeReleaseState.INVALIDATED
        and impact.after_state == ProgrammeReleaseState.AVAILABLE
        and impact.changes is None,
        "successor_publication_or_history_changed",
    )
    return approved.object_id, published.object_id, evidence.snapshot_digest


def verify_successor_operator_output(setup, planning, staffing, change):
    """Expose cancelled predecessor distinctly from three currently covered shifts."""
    from maru.scheduling.operator_output_queries import (  # noqa: PLC0415
        load_operator_run_sheet,
    )
    from maru.scheduling.operator_scope import (  # noqa: PLC0415
        OperatorReadRequest,
        OperatorScopeKind,
    )
    from tests.rehearsals.programme_release_outputs import _available  # noqa: PLC0415

    for kind, target in (
        (OperatorScopeKind.EDITION, setup.edition_id),
        (OperatorScopeKind.DEPARTMENT, setup.department_id),
        (OperatorScopeKind.ROOM, planning.room_ids[0]),
    ):
        result = load_operator_run_sheet(
            OperatorReadRequest(
                planning.planner.authenticate().id,
                setup.organization_id,
                setup.edition_id,
                uuid4(),
                kind,
                target,
            ),
            layers=frozenset({"staffing"}),
        )
        _available(result.reference, change)
        expected = (
            change.work,
            *staffing.work[1 : 2 if kind == OperatorScopeKind.ROOM else 3],
        )
        current = {row.demand_id: row for row in expected}
        layer = result.staffing
        _require(layer is not None and layer.adopted, "successor_operator_work_missing")
        _require(
            len(layer.links) == len(expected) + 1
            and {row.demand_id for row in layer.links if row.current} == set(current)
            and {row.demand_id for row in layer.links if not row.current}
            == {change.predecessor_demand_id}
            and all(
                row.demand_version == current[row.demand_id].demand_version
                for row in layer.links
                if row.current
            )
            and len(layer.demands) == len(expected) + 1
            and {row.demand_id for row in layer.demands if row.state == "locked"}
            == set(current)
            and {row.demand_id for row in layer.demands if row.state == "cancelled"}
            == {change.predecessor_demand_id}
            and all(row.delivery is None for row in result.entries),
            "successor_operator_history_changed",
        )
