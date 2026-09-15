"""Release-task presentation composed from independently admitted owner projections."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from django import forms

from .authorization import (
    ACKNOWLEDGE_RELEASE_WARNINGS,
    APPROVE_RELEASE,
    PUBLISH_RELEASE,
    VIEW_CONFLICTS,
    VIEW_HISTORY,
    VIEW_PLANNING,
    WITHDRAW_RELEASE,
    SchedulingAuthorizationDeniedError,
    authorize_scheduling_scope,
)
from .catalogs import MAX_CONFLICTS, SchedulingConflictSeverity
from .command_support import SchedulingUnavailableError
from .planning_queries import HISTORY_FIELDS
from .release_eligibility import (
    ReleaseCheck,
    ReleaseFinding,
    ReleaseWarningAcknowledgement,
    evaluate_release_eligibility,
)
from .release_inputs import ReleaseCandidateSelection
from .release_preflight import load_release_preflight
from .release_queries import RELEASE_MANIFEST_FIELDS
from .release_workspace_forms import (
    ReleaseApprovalSelectionForm,
    ReleaseApproveForm,
    ReleaseCandidateForm,
    ReleaseOlderApprovalsForm,
    ReleaseOlderHistoryForm,
    ReleasePublishForm,
    ReleaseWarningForm,
    ReleaseWithdrawForm,
)
from .release_workspace_queries import (
    RELEASE_CANDIDATE_FIELDS,
    list_release_approvals,
    list_release_candidates,
    list_release_history,
    list_release_warning_evidence,
    load_release_approval,
    load_release_pointer,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import QueryDict

    from .planning_queries import SchedulingReadRequest

TASK_LABELS = {
    "review": "Review a private candidate",
    "publish": "Publish an approved timetable",
    "withdraw": "Withdraw the active timetable",
    "history": "Release and withdrawal history",
}
COMMAND_CAPABILITIES = {
    "acknowledge": ACKNOWLEDGE_RELEASE_WARNINGS,
    "approve": APPROVE_RELEASE,
    "publish": PUBLISH_RELEASE,
    "withdraw": WITHDRAW_RELEASE,
}
TASK_READS = {
    "review": (
        (VIEW_PLANNING, RELEASE_CANDIDATE_FIELDS),
        (VIEW_CONFLICTS, frozenset({"release_preflight"})),
        (VIEW_HISTORY, HISTORY_FIELDS),
    ),
    "publish": (
        (VIEW_HISTORY, HISTORY_FIELDS),
        (VIEW_PLANNING, RELEASE_MANIFEST_FIELDS),
    ),
    "withdraw": ((VIEW_PLANNING, RELEASE_MANIFEST_FIELDS),),
    "history": ((VIEW_HISTORY, HISTORY_FIELDS | RELEASE_MANIFEST_FIELDS),),
}
CHECK_GUIDANCE = {
    ReleaseCheck.CANDIDATE: (
        "Exact timetable candidate",
        "Review the selected draft, service days and every retained placement.",
    ),
    ReleaseCheck.PROGRAMME_READINESS: (
        "Programme readiness",
        "Resolve each item's current requirements and readiness evidence.",
    ),
    ReleaseCheck.PUBLIC_COPY: (
        "Independently reviewed public copy",
        "Obtain current reviewed copy from someone other than its retained authors.",
    ),
    ReleaseCheck.HOSTS: (
        "Confirmed hosting",
        "Resolve required hosts, selected presence and deliberately "
        "shared availability.",
    ),
    ReleaseCheck.PHYSICAL_APPROVAL: (
        "Independent room approval",
        "Ask the authorized Venue reviewer to approve the exact physical reservation.",
    ),
    ReleaseCheck.PHYSICAL_CONSTRAINTS: (
        "Room capacity and availability",
        "Resolve capacity, availability and conflicting physical occupancy.",
    ),
    ReleaseCheck.ACCESSIBILITY_FIT: (
        "Accessibility fit",
        "Record the Programme assessment for the exact placement "
        "and physical configuration.",
    ),
    ReleaseCheck.STAFFING: (
        "Programme staffing",
        "Resolve current staffing coverage, or an explicit owner-approved "
        "no-staffing decision.",
    ),
    ReleaseCheck.PERSON_CONFLICTS: (
        "People's retained commitments",
        "Resolve conflicting hosting or work; do not infer "
        "someone else's availability.",
    ),
    ReleaseCheck.REST: (
        "Required rest",
        "Resolve rest conflicts against the combined current host and work sources.",
    ),
}


def authorize_release_task(scope: SchedulingReadRequest, task: str) -> None:
    """Check every field ceiling independently before a task discloses any sources.

    Parameters
    ----------
    scope : SchedulingReadRequest
        Trusted exact actor, organization and edition.
    task : str
        Closed human task selected by the route, not an authority-bearing URL.
    """
    for capability, fields in TASK_READS[task]:
        authorize_scheduling_scope(
            actor_id=scope.actor_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            capability_code=capability,
            requested_fields=fields,
        )


def authorize_release_action(
    scope: SchedulingReadRequest,
    action: str,
    *,
    fresh: bool = False,
) -> None:
    """Check action authority without requiring a refreshed private source read.

    Parameters
    ----------
    scope : SchedulingReadRequest
        Current independently resolved command actor and scope.
    action : str
        Closed release command action.
    fresh : bool, default=False
        Require writable lifecycle only when offering a new intent. Retried
        commands reach their canonical receipt before lifecycle preparation.

    Raises
    ------
    SchedulingAuthorizationDeniedError
        If current authority or lifecycle does not allow a command attempt.
    """
    admitted = authorize_scheduling_scope(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        capability_code=COMMAND_CAPABILITIES[action],
    )
    if fresh and not admitted.accepts_writes:
        raise SchedulingAuthorizationDeniedError


def _allowed(
    scope: SchedulingReadRequest,
    action: str,
    guards: list[Callable[[], None]],
) -> bool:
    try:
        authorize_release_action(scope, action, fresh=True)
    except SchedulingAuthorizationDeniedError:
        return False
    guards.append(lambda: authorize_release_action(scope, action, fresh=True))
    return True


def _checked_form(form: forms.Form) -> dict[str, Any]:
    if not form.is_valid():
        raise ValueError
    return form.cleaned_data


def _observed[T](loader: Callable[[], T], guards: list[Callable[[], None]]) -> T:
    result = loader()

    def unchanged() -> None:
        if loader() != result:
            raise SchedulingUnavailableError

    guards.append(unchanged)
    return result


def _review(
    scope: SchedulingReadRequest,
    data: QueryDict | None,
    guards: list[Callable[[], None]],
) -> dict[str, Any]:
    candidates = _observed(lambda: list_release_candidates(scope), guards)
    form = ReleaseCandidateForm(data, initial={"action": "inspect"})
    form.fields["candidate_id"].widget = forms.Select(
        choices=[
            ("", "Choose a private timetable candidate"),
            *(
                (
                    str(row.id),
                    f"Alternative {index}: {row.label} · version {row.version} · "
                    f"{row.placement_count} placements · {row.lifecycle}",
                )
                for index, row in enumerate(candidates, 1)
            ),
        ]
    )
    context: dict[str, Any] = {
        "candidate_form": form,
        "has_candidates": bool(candidates),
    }
    if data is None:
        return context
    selected = _checked_form(form)["candidate_id"]
    candidate = next((row for row in candidates if row.id == selected), None)
    if candidate is None:
        raise SchedulingUnavailableError
    if candidate.lifecycle != "draft" or candidate.placement_count == 0:
        context["message"] = (
            "This retained alternative is archived or has no placements. "
            "Select a nonempty current draft before complete release review. "
            "No release action is offered for this selection."
        )
        return context
    preflight = _observed(
        lambda: load_release_preflight(
            scope,
            candidate_id=candidate.id,
            candidate_revision_id=candidate.revision_id,
            expected_candidate_version=candidate.version,
        ),
        guards,
    )
    if (
        len(preflight.checks) != len(ReleaseCheck)
        or {row.check for row in preflight.checks} != set(ReleaseCheck)
        or preflight.candidate_revision_id != candidate.revision_id
        or len(preflight.findings) > MAX_CONFLICTS
    ):
        raise SchedulingUnavailableError
    selection = ReleaseCandidateSelection(
        candidate.id,
        candidate.revision_id,
        candidate.version,
        preflight.snapshot_digest,
    ).validated()
    evidence = _observed(
        lambda: list_release_warning_evidence(scope, selection=selection), guards
    )
    warnings = {
        row.fingerprint: row
        for row in preflight.findings
        if row.severity is SchedulingConflictSeverity.WARNING
    }
    finding_numbers = {
        row.fingerprint: number for number, row in enumerate(preflight.findings, 1)
    }
    if len(finding_numbers) != len(preflight.findings):
        raise SchedulingUnavailableError
    chosen = {}
    for row in evidence:
        finding = warnings.get(row.fingerprint)
        if finding is None or (row.check, row.code) != (
            finding.check.value,
            finding.code,
        ):
            raise SchedulingUnavailableError
        # The complete oldest-first inventory makes this deterministic. Every
        # selected exact reason/reference is shown before deliberate approval.
        chosen[row.fingerprint] = row
    selected_evidence = tuple(chosen[key] for key in sorted(chosen))
    eligibility = evaluate_release_eligibility(
        snapshot_digest=preflight.snapshot_digest,
        checks=preflight.checks,
        findings=tuple(
            ReleaseFinding(
                preflight.snapshot_digest, row.check, row.fingerprint, row.severity
            )
            for row in preflight.findings
        ),
        acknowledgements=tuple(
            ReleaseWarningAcknowledgement(preflight.snapshot_digest, row.fingerprint)
            for row in selected_evidence
        ),
    )
    context.update(
        candidate=candidate,
        preflight=preflight,
        check_rows=tuple(
            {
                "label": CHECK_GUIDANCE[row.check][0],
                "guidance": CHECK_GUIDANCE[row.check][1],
                "state": row.state.value.replace("_", " "),
            }
            for row in preflight.checks
        ),
        findings=tuple(
            {
                "number": finding_numbers[row.fingerprint],
                "label": row.code.replace("_", " ").capitalize(),
                "category": CHECK_GUIDANCE[row.check][0],
                "severity": row.severity.value,
                "occurrence_id": row.occurrence_id,
                "other_occurrence_id": row.other_occurrence_id,
            }
            for row in preflight.findings
        ),
        warning_evidence=selected_evidence,
        review_eligible=eligibility.eligible_for_review,
    )
    initial = asdict(selection)
    if warnings and _allowed(scope, "acknowledge", guards):
        warning_form = ReleaseWarningForm(
            initial=initial | {"action": "acknowledge", "retry_key": uuid4()},
            auto_id="id_warning_%s",
        )
        warning_form.fields["finding_fingerprint"].widget = forms.Select(
            choices=[
                ("", "Choose the warning you are acknowledging"),
                *(
                    (
                        row.fingerprint,
                        f"{CHECK_GUIDANCE[row.check][0]} · "
                        f"{row.code.replace('_', ' ')} · "
                        f"Finding {finding_numbers[row.fingerprint]}",
                    )
                    for row in warnings.values()
                ),
            ]
        )
        context["warning_form"] = warning_form
    if eligibility.eligible_for_review and _allowed(scope, "approve", guards):
        context["approval_form"] = ReleaseApproveForm(
            initial=initial
            | {
                "action": "approve",
                "retry_key": uuid4(),
                "acknowledgement_ids": json.dumps(
                    [str(row.id) for row in selected_evidence]
                ),
            },
            auto_id="id_approval_%s",
        )
    return context


def _publication(
    scope: SchedulingReadRequest,
    data: QueryDict | None,
    guards: list[Callable[[], None]],
) -> dict[str, Any]:
    if data is not None and data.get("action") == "prepare":
        identifier = _checked_form(ReleaseApprovalSelectionForm(data))["approval_id"]
        approval = _observed(
            lambda: load_release_approval(scope, approval_id=identifier), guards
        )
        pointer = _observed(lambda: load_release_pointer(scope), guards)
        context: dict[str, Any] = {"approval": approval, "pointer": pointer}
        if _allowed(scope, "publish", guards):
            context["publication_form"] = ReleasePublishForm(
                initial={
                    "action": "publish",
                    "retry_key": uuid4(),
                    "approval_id": approval.id,
                    "source_snapshot_digest": approval.snapshot_digest,
                    "expected_active_release_id": pointer.active_release_id,
                    "expected_release_version": pointer.version,
                }
            )
        return context
    before_id = (
        _checked_form(ReleaseOlderApprovalsForm(data))["before_id"]
        if data is not None
        else None
    )
    page = _observed(lambda: list_release_approvals(scope, before_id=before_id), guards)
    return {
        "approvals": tuple(
            (
                entry,
                ReleaseApprovalSelectionForm(
                    initial={"action": "prepare", "approval_id": entry.id},
                    auto_id=False,
                ),
            )
            for entry in page.entries
        ),
        "approval_inventory": True,
        "older_form": ReleaseOlderApprovalsForm(
            initial={"action": "older", "before_id": page.next_before_id}
        )
        if page.next_before_id
        else None,
    }


def compose_release_task(
    scope: SchedulingReadRequest,
    task: str,
    data: QueryDict | None,
) -> tuple[dict[str, Any], tuple[Callable[[], None], ...]]:
    """Compose one admitted native task and its final source-disclosure checks.

    Parameters
    ----------
    scope : SchedulingReadRequest
        Trusted actor/scope; each owner source still authorizes independently.
    task : str
        Closed review, publication, withdrawal or history task.
    data : QueryDict | None
        Bounded read-only POST selection; mutations never enter this function.

    Returns
    -------
    tuple[dict[str, Any], tuple[Callable[[], None], ...]]
        Template projections and mandatory post-render current-source checks.

    Raises
    ------
    ValueError
        If a task or read-only selection is malformed.
    """
    guards: list[Callable[[], None]] = []
    if task == "review":
        context = _review(scope, data, guards)
    elif task == "publish":
        context = _publication(scope, data, guards)
    elif task == "withdraw" and data is None:
        pointer = _observed(lambda: load_release_pointer(scope), guards)
        context = {"pointer": pointer}
        if pointer.active_release_id and _allowed(scope, "withdraw", guards):
            context["withdrawal_form"] = ReleaseWithdrawForm(
                initial={
                    "action": "withdraw",
                    "retry_key": uuid4(),
                    "active_release_id": pointer.active_release_id,
                    "expected_release_version": pointer.version,
                }
            )
    elif task == "history":
        before = (
            _checked_form(ReleaseOlderHistoryForm(data))["before_version"]
            if data is not None
            else None
        )
        page = _observed(
            lambda: list_release_history(scope, before_version=before), guards
        )
        context = {
            "history": page.entries,
            "history_loaded": True,
            "older_form": ReleaseOlderHistoryForm(
                initial={"action": "older", "before_version": page.next_before_version}
            )
            if page.next_before_version
            else None,
        }
    else:
        raise ValueError
    return context, tuple(guards)
