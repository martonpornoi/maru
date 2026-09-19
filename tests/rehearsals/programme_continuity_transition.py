"""Actual-owner withdrawal and fresh recovery publication for the P10 fixture."""

import json
import sys
from dataclasses import asdict, dataclass, replace
from uuid import UUID

from tests.rehearsals.programme_change_scenario import (
    change_from_document,
    change_sources,
)
from tests.rehearsals.programme_release_preparation import (
    _command_request,
    _manifest,
    _preflight,
    _require,
    _retry_equal,
)
from tests.rehearsals.programme_runtime_environment import (
    require_programme_runtime_environment,
)
from tests.rehearsals.programme_successor_work import _own_work


@dataclass(frozen=True, slots=True)
class ProgrammeContinuityTransition:
    """Scoped native result identities, not acceptance or production authority."""

    operation: str
    organization_id: UUID
    edition_id: UUID
    object_id: UUID
    approval_id: UUID | None
    pointer_version: int


def transition_from_document(document, *, setup, operation):
    """Reject mismatched scope, operation or versions in the private child result."""
    try:
        result = ProgrammeContinuityTransition(
            document["operation"],
            UUID(document["organization_id"]),
            UUID(document["edition_id"]),
            UUID(document["object_id"]),
            UUID(document["approval_id"])
            if document["approval_id"] is not None
            else None,
            document["pointer_version"],
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValueError("fixture_continuity_result_invalid") from None
    if (
        set(document) != set(asdict(result))
        or operation not in {"withdraw", "republish"}
        or result.operation != operation
        or (result.organization_id, result.edition_id)
        != (setup.organization_id, setup.edition_id)
        or result.object_id.int == 0
        or type(result.pointer_version) is not int
        or result.pointer_version != (3 if operation == "withdraw" else 4)
        or (result.approval_id is None) != (operation == "withdraw")
        or (result.approval_id is not None and result.approval_id.int == 0)
    ):
        raise ValueError("fixture_continuity_result_invalid")
    return result


def _withdraw(setup, planning, changed):
    from maru.scheduling import command_support  # noqa: PLC0415
    from maru.scheduling import (  # noqa: PLC0415
        release_publication_commands as commands,
    )
    from maru.scheduling.release_inputs import ReleaseWithdrawalIntent  # noqa: PLC0415

    before = _manifest(setup, planning.planner)
    _require(
        before.state == "available"
        and before.is_active
        and before.release_id == changed.release_id
        and before.pointer_version == 2,
        "continuity_original_release_changed",
    )
    intent = ReleaseWithdrawalIntent(changed.release_id, 2)
    try:
        commands.withdraw_programme_release(
            _command_request(setup, planning.planner),
            intent=replace(intent, expected_release_version=1),
        )
    except command_support.SchedulingVersionConflictError:
        pass
    else:
        raise RuntimeError("continuity_stale_withdrawal_accepted")
    _require(
        _manifest(setup, planning.planner) == before,
        "continuity_stale_withdrawal_mutated",
    )
    request = _command_request(setup, planning.planner)
    result = commands.withdraw_programme_release(request, intent=intent)
    _retry_equal(result, commands.withdraw_programme_release(request, intent=intent))
    after = _manifest(setup, planning.planner)
    _require(
        result.version == 3
        and after.pointer_version == 3
        and after.state == "withdrawn"
        and after.release_id is None
        and not after.is_active
        and not after.selections,
        "continuity_withdrawal_not_observed",
    )
    return result.object_id, None


def _republish(setup, planning, release, changed):
    from maru.scheduling import (  # noqa: PLC0415
        command_support,
        release_review_commands,
    )
    from maru.scheduling import (  # noqa: PLC0415
        release_publication_commands as commands,
    )
    from maru.scheduling.release_inputs import (  # noqa: PLC0415
        ReleaseApprovalIntent,
        ReleaseCandidateSelection,
        ReleasePublicationIntent,
    )

    publisher, reviewer = planning.planner, release.reviewer
    _require(
        publisher.account_id != reviewer.account_id, "continuity_independence_lost"
    )
    before = _manifest(setup, publisher)
    _require(
        before.state == "withdrawn"
        and before.pointer_version == 3
        and before.release_id is None
        and not before.selections,
        "continuity_withdrawn_source_required",
    )
    evidence = _preflight(setup, publisher, planning)
    _require(
        _preflight(setup, reviewer, planning) == evidence,
        "continuity_recovery_sources_changed",
    )
    intent = ReleaseApprovalIntent(
        ReleaseCandidateSelection(
            planning.candidate_id,
            planning.candidate_revision_id,
            planning.candidate_version,
            evidence.snapshot_digest,
        )
    )
    request = _command_request(setup, reviewer)
    approval = release_review_commands.approve_programme_release(request, intent=intent)
    _retry_equal(
        approval,
        release_review_commands.approve_programme_release(request, intent=intent),
    )
    _require(
        approval.object_id not in {release.approval_id, changed.approval_id},
        "continuity_previous_approval_reused",
    )
    _require(_manifest(setup, publisher) == before, "continuity_approval_published")
    publication = ReleasePublicationIntent(
        approval.object_id, None, 3, evidence.snapshot_digest
    )
    try:
        commands.publish_programme_release(
            _command_request(setup, publisher),
            intent=replace(publication, expected_release_version=0),
        )
    except command_support.SchedulingVersionConflictError:
        pass
    else:
        raise RuntimeError("continuity_stale_recovery_accepted")
    _require(_manifest(setup, publisher) == before, "continuity_stale_recovery_mutated")
    request = _command_request(setup, publisher)
    result = commands.publish_programme_release(request, intent=publication)
    _retry_equal(
        result, commands.publish_programme_release(request, intent=publication)
    )
    after = _manifest(setup, publisher)
    _require(
        result.version == 4
        and after.pointer_version == 4
        and after.state == "available"
        and after.is_active
        and after.release_id == result.object_id
        and result.object_id != changed.release_id
        and len(after.selections) == 3,
        "continuity_recovery_not_observed",
    )
    return result.object_id, approval.object_id


def prepare_continuity_transition(document):
    """Validate the full original chain, then call only actual authorized owner APIs."""
    require_programme_runtime_environment()
    if set(document) != {"sources", "change", "operation"} or document[
        "operation"
    ] not in {"withdraw", "republish"}:
        raise ValueError("fixture_continuity_transition_invalid")
    setup, _, _, _, planning, _, staffing, release = change_sources(document["sources"])
    changed = change_from_document(
        document["change"], setup=setup, staffing=staffing, release=release
    )
    from tests.rehearsals import programme_runtime  # noqa: PLC0415

    programme_runtime.build_candidate_application()
    before = _own_work(setup, staffing.volunteer)
    _require(
        set(before)
        == {
            changed.work.commitment_id,
            changed.predecessor_commitment_id,
            *(row.commitment_id for row in staffing.work[1:]),
        },
        "continuity_retained_work_changed",
    )
    operation = document["operation"]
    identifier, approval = (
        _withdraw(setup, planning, changed)
        if operation == "withdraw"
        else _republish(setup, planning, release, changed)
    )
    _require(
        _own_work(setup, staffing.volunteer) == before,
        "continuity_changed_retained_work",
    )
    return ProgrammeContinuityTransition(
        operation,
        setup.organization_id,
        setup.edition_id,
        identifier,
        approval,
        3 if operation == "withdraw" else 4,
    )


def _main():
    try:
        require_programme_runtime_environment()
        raw = sys.stdin.buffer.read(65_537)
        if len(raw) > 65_536:
            return 2
        result = prepare_continuity_transition(json.loads(raw))
    except Exception:  # noqa: BLE001 - fixed private child boundary
        return 2
    sys.stdout.write(json.dumps(asdict(result), default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
