"""Actual reviewed notices with genuine self acknowledgement, never email delivery."""

from dataclasses import replace
from uuid import uuid4

from tests.rehearsals.programme_planning_scenario import _request
from tests.rehearsals.programme_release_preparation import (
    _command_request as _release_request,
)
from tests.rehearsals.programme_release_preparation import (
    _require,
    _retry_equal,
)
from tests.rehearsals.programme_setup_scenarios import approve_synthetic_role


def _command_request(setup, person):
    return replace(
        _release_request(setup, person),
        reason=(
            "Synthetic exact change-notice decision; no real-person delivery evidence."
        ),
    )


def _rejects(error, code, command, *args, **kwargs):
    try:
        command(*args, **kwargs)
    except error:
        return
    raise RuntimeError(code)


def approve_notice_roles(setup, planning, physical, release):
    """Approve existing separate sender/source roles and one exact-room operator."""
    from maru.authorization.catalog import ScopeLevel  # noqa: PLC0415
    from maru.authorization.programme_role_scope_choices import (  # noqa: PLC0415
        load_programme_role_scope_choices,
    )
    from maru.venues.bindings import edition_space_binding_id  # noqa: PLC0415

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
                ("hosting", "notice-preparation", "notice-review", "notice-handoff"),
            ),
            (
                release.reviewer,
                ("hosting", "run-sheet", "notice-preparation", "notice-review"),
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
    matching = [
        row.scope
        for row in choices.choices
        if row.scope.level == ScopeLevel.RESOURCE
        and row.scope.department_id == setup.department_id
        and row.scope.resource_kind == "venue.edition_space"
        and row.scope.resource_binding_id
        == edition_space_binding_id(planning.room_ids[0])
    ]
    _require(len(matching) == 1, "notice_room_scope_unavailable")
    scope = matching[0]
    grants.append(
        approve_synthetic_role(
            setup,
            people=setup.controllers,
            recipient=physical.reviewer,
            code="run-sheet",
            level=scope.level,
            department_id=scope.department_id,
            resource_binding_id=scope.resource_binding_id,
            resource_kind=scope.resource_kind,
        )
    )
    return tuple(grants)


def prepare_review_handoff_ack(
    setup, planning, reviewer, person, selection, release_id
):
    """Keep suppression, independent review, manual handoff and own ack separate."""
    from maru.scheduling.change_catalogs import (  # noqa: PLC0415
        ChangeNoticeAction,
        ChangeNoticeReview,
        ChangeNoticeSourceState,
    )
    from maru.scheduling.change_inputs import (  # noqa: PLC0415
        ChangeNoticeDecisionIntent,
        PrepareChangeNoticeIntent,
    )
    from maru.scheduling.change_notice_commands import (  # noqa: PLC0415
        acknowledge_programme_change_notice,
        handoff_programme_change_notice,
        prepare_programme_change_notice,
        review_programme_change_notice,
    )
    from maru.scheduling.change_notice_queries import (  # noqa: PLC0415
        load_personal_programme_change_notice,
        load_programme_change_notice,
        preview_programme_change_notice,
    )
    from maru.scheduling.command_support import (  # noqa: PLC0415
        SchedulingLifecycleConflictError,
        SchedulingUnavailableError,
        SchedulingVersionConflictError,
    )

    sender = planning.planner
    preview = preview_programme_change_notice(
        _request(setup, sender, read=True),
        release_id=release_id,
        occurrence_id=planning.occurrence_ids[0],
        recipient=selection,
    )
    _require(
        preview.release_id == release_id
        and preview.pointer_version == 2
        and preview.recipient_id == person.account_id
        and preview.recipient == selection
        and preview.source_state == ChangeNoticeSourceState.COMPARISON_SUPPRESSED
        and preview.change is None,
        "notice_restored_suppressed_comparison",
    )
    intent = PrepareChangeNoticeIntent(
        release_id, planning.occurrence_ids[0], 2, selection, preview.snapshot_digest
    )
    request = _command_request(setup, sender)
    prepared = prepare_programme_change_notice(request, intent)
    _retry_equal(prepared, prepare_programme_change_notice(request, intent))
    decision = ChangeNoticeDecisionIntent(
        prepared.object_id, 1, preview.snapshot_digest
    )
    own = _request(setup, person, read=True)
    _rejects(
        SchedulingUnavailableError,
        "notice_unreviewed_disclosed",
        load_personal_programme_change_notice,
        own,
        notice_id=prepared.object_id,
    )
    for operation in ("handoff", "self_review"):
        try:
            if operation == "handoff":
                handoff_programme_change_notice(
                    _command_request(setup, sender), decision
                )
            else:
                review_programme_change_notice(
                    _command_request(setup, sender),
                    decision,
                    action=ChangeNoticeAction.APPROVE,
                )
        except SchedulingLifecycleConflictError:
            pass
        else:
            raise RuntimeError("notice_independence_bypassed")
    request = _command_request(setup, reviewer)
    approved = review_programme_change_notice(
        request, decision, action=ChangeNoticeAction.APPROVE
    )
    _retry_equal(
        approved,
        review_programme_change_notice(
            request, decision, action=ChangeNoticeAction.APPROVE
        ),
    )
    visible = load_personal_programme_change_notice(own, notice_id=prepared.object_id)
    _require(
        visible.version == 2
        and not visible.handed_off
        and not visible.acknowledged
        and visible.preview.snapshot_digest == preview.snapshot_digest
        and visible.preview.change is None,
        "notice_review_implied_delivery",
    )
    _rejects(
        SchedulingUnavailableError,
        "notice_acknowledged_for_someone_else",
        acknowledge_programme_change_notice,
        _request(setup, sender, read=True),
        replace(decision, expected_version=2),
        idempotency_key=uuid4(),
    )
    handoff_request = replace(
        _command_request(setup, sender),
        reason=(
            "Simulated manual handoff of this exact synthetic notice; "
            "no provider delivery."
        ),
    )
    handed = handoff_programme_change_notice(
        handoff_request, replace(decision, expected_version=2)
    )
    _retry_equal(
        handed,
        handoff_programme_change_notice(
            handoff_request, replace(decision, expected_version=2)
        ),
    )
    visible = load_personal_programme_change_notice(own, notice_id=prepared.object_id)
    _require(
        visible.version == 3 and visible.handed_off and not visible.acknowledged,
        "notice_handoff_implied_acknowledgement",
    )
    _rejects(
        SchedulingVersionConflictError,
        "notice_stale_acknowledgement_accepted",
        acknowledge_programme_change_notice,
        own,
        replace(decision, expected_version=2),
        idempotency_key=uuid4(),
    )
    ack = replace(decision, expected_version=3)
    key = uuid4()
    acknowledged = acknowledge_programme_change_notice(own, ack, idempotency_key=key)
    _retry_equal(
        acknowledged, acknowledge_programme_change_notice(own, ack, idempotency_key=key)
    )
    visible = load_personal_programme_change_notice(own, notice_id=prepared.object_id)
    detail = load_programme_change_notice(
        _request(setup, sender, read=True), notice_id=prepared.object_id
    )
    _require(
        visible.version == detail.state.version == 4
        and visible.handed_off
        and visible.acknowledged
        and detail.state.preparer_id == sender.account_id
        and detail.state.review == ChangeNoticeReview.APPROVED
        and detail.state.reviewer_id == reviewer.account_id
        and detail.state.handed_off_by_id == sender.account_id
        and detail.state.acknowledged_by_id == person.account_id
        and visible.preview.recipient_id == person.account_id
        and visible.preview.source_state
        == ChangeNoticeSourceState.COMPARISON_SUPPRESSED
        and visible.preview.change is None,
        "notice_final_evidence_changed",
    )
    return prepared.object_id
