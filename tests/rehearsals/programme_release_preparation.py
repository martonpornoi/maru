"""Actual independent release decisions; never substitute successful owner evidence."""

from dataclasses import replace
from uuid import uuid4

from tests.rehearsals.programme_planning_scenario import _request
from tests.rehearsals.programme_setup_scenarios import approve_synthetic_role

REASON = "Synthetic exact timetable release; no production or human acceptance."


class ProgrammeReleasePreparationError(RuntimeError):
    """Expose a stable preparation failure without private source detail."""


def _require(condition, code):
    if not condition:
        raise ProgrammeReleasePreparationError(code)


def approve_release_roles(setup, planning, reviewer):
    """Use existing explicit recipes and independently approved real assignments."""
    from maru.authorization.catalog import ScopeLevel  # noqa: PLC0415
    from maru.authorization.programme_role_scope_choices import (  # noqa: PLC0415
        load_programme_role_scope_choices,
    )
    from maru.venues.bindings import edition_space_binding_id  # noqa: PLC0415

    # Both people deliberately receive the decision capabilities so the negative
    # cases exercise owner independence, not merely a missing permission. This is
    # a synthetic test arrangement, not a recommended production role allocation.
    grants = [
        approve_synthetic_role(
            setup,
            people=setup.controllers,
            recipient=person,
            code=code,
            level=ScopeLevel.EDITION,
        )
        for person, codes in (
            (
                planning.planner,
                ("content", "release-approval", "publisher", "run-sheet"),
            ),
            (
                reviewer,
                (
                    "planner",
                    "content",
                    "delivery",
                    "staffing",
                    "coverage-reader",
                    "release-approval",
                    "publisher",
                ),
            ),
        )
        for code in codes
    ]
    choices = load_programme_role_scope_choices(
        actor=setup.controllers[0].authenticate(),
        organization_id=setup.organization_id,
        edition_id=setup.edition_id,
        correlation_id=uuid4(),
        source_channel="programme_rehearsal",
    )
    for room in planning.room_ids:
        matches = [
            row.scope
            for row in choices.choices
            if row.scope.level == ScopeLevel.RESOURCE
            and row.scope.department_id == setup.department_id
            and row.scope.resource_kind == "venue.edition_space"
            and row.scope.resource_binding_id == edition_space_binding_id(room)
        ]
        _require(len(matches) == 1, "release_room_scope_unavailable")
        scope = matches[0]
        grants.append(
            approve_synthetic_role(
                setup,
                people=setup.controllers,
                recipient=reviewer,
                code="room-dependencies",
                level=scope.level,
                department_id=scope.department_id,
                resource_binding_id=scope.resource_binding_id,
                resource_kind=scope.resource_kind,
            )
        )
    return tuple(grants)


def _command_request(setup, person):
    return replace(_request(setup, person), reason=REASON)


def _manifest(setup, person):
    from maru.scheduling.release_queries import (  # noqa: PLC0415
        load_programme_release_manifest,
    )

    return load_programme_release_manifest(_request(setup, person, read=True))


def _preflight(setup, person, planning):
    from maru.scheduling.release_eligibility import (  # noqa: PLC0415
        ReleaseCheck,
        ReleaseCheckState,
    )
    from maru.scheduling.release_preflight import (  # noqa: PLC0415
        load_release_preflight,
    )

    result = load_release_preflight(
        _request(setup, person, read=True),
        candidate_id=planning.candidate_id,
        candidate_revision_id=planning.candidate_revision_id,
        expected_candidate_version=planning.candidate_version,
    )
    _require(
        result.candidate_revision_id == planning.candidate_revision_id
        and len(result.checks) == len(ReleaseCheck)
        and {row.check for row in result.checks} == set(ReleaseCheck)
        and all(
            row.state == ReleaseCheckState.SATISFIED
            and row.snapshot_digest == result.snapshot_digest
            for row in result.checks
        )
        and result.eligibility.snapshot_digest == result.snapshot_digest
        and result.eligibility.eligible_for_review
        and not result.findings,
        "release_complete_sources_required",
    )
    # This fixed conflict-free scenario acknowledges nothing automatically.
    # An unexpected warning or inapplicability is a failed fixture assumption.
    return result


def _retry_equal(result, replay):
    _require(
        replay.replayed and replace(replay, replayed=False) == result,
        "release_retry_changed",
    )


def prepare_first_release(setup, items, planning, reviewer):
    """Recollect ten owners, reject self decisions and publish one exact approval."""
    from maru.scheduling.authorization import (  # noqa: PLC0415
        SchedulingAuthorizationDeniedError,
    )
    from maru.scheduling.command_support import (  # noqa: PLC0415
        SchedulingVersionConflictError,
    )
    from maru.scheduling.release_artifacts import (  # noqa: PLC0415
        ReleaseArtifactSelection,
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

    publisher = planning.planner
    before = _manifest(setup, publisher)
    _require(
        before.state == ProgrammeReleaseState.ABSENT
        and before.pointer_version == 0
        and before.release_id is None
        and not before.is_active
        and not before.selections,
        "release_requires_unpublished_edition",
    )
    evidence = _preflight(setup, publisher, planning)
    _require(
        _preflight(setup, reviewer, planning) == evidence,
        "release_reviewer_sources_changed",
    )
    approval_intent = ReleaseApprovalIntent(
        ReleaseCandidateSelection(
            planning.candidate_id,
            planning.candidate_revision_id,
            planning.candidate_version,
            evidence.snapshot_digest,
        )
    )
    try:
        approve_programme_release(
            _command_request(setup, publisher), intent=approval_intent
        )
    except SchedulingAuthorizationDeniedError:
        pass
    else:
        raise ProgrammeReleasePreparationError("release_author_approval_accepted")
    _require(_manifest(setup, publisher) == before, "release_denial_mutated_pointer")
    approval_request = _command_request(setup, reviewer)
    approved = approve_programme_release(approval_request, intent=approval_intent)
    _retry_equal(
        approved, approve_programme_release(approval_request, intent=approval_intent)
    )
    _require(_manifest(setup, publisher) == before, "release_approval_published")
    publication = ReleasePublicationIntent(
        approved.object_id,
        before.release_id,
        before.pointer_version,
        evidence.snapshot_digest,
    )
    try:
        publish_programme_release(_command_request(setup, reviewer), intent=publication)
    except SchedulingAuthorizationDeniedError:
        pass
    else:
        raise ProgrammeReleasePreparationError("release_approver_publication_accepted")
    try:
        publish_programme_release(
            _command_request(setup, publisher),
            intent=replace(publication, expected_release_version=1),
        )
    except SchedulingVersionConflictError:
        pass
    else:
        raise ProgrammeReleasePreparationError("release_stale_pointer_accepted")
    _require(_manifest(setup, publisher) == before, "release_failure_mutated_pointer")
    request = _command_request(setup, publisher)
    published = publish_programme_release(request, intent=publication)
    _retry_equal(published, publish_programme_release(request, intent=publication))
    after = _manifest(setup, publisher)
    expected = tuple(
        ReleaseArtifactSelection(occurrence, placement, item.public_rendition_id)
        for occurrence, placement, item in zip(
            planning.occurrence_ids,
            planning.placement_ids,
            (items.ceremony, items.accepted, items.accepted),
            strict=True,
        )
    )
    _require(
        published.version == 1
        and after.state == ProgrammeReleaseState.AVAILABLE
        and after.pointer_version == 1
        and after.is_active
        and after.release_id == published.object_id
        and len(after.selections) == 3
        and set(after.selections) == set(expected),
        "release_checked_manifest_changed",
    )
    return (
        approved.object_id,
        published.object_id,
        published.version,
        evidence.snapshot_digest,
    )
