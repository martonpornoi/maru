"""Real independent review and private conversion composition, not human evidence."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field, replace
from uuid import UUID, uuid4

from tests.rehearsals.programme_proposal_scenario import (
    CHANNEL,
    _query_scope,
    proposal_from_document,
)
from tests.rehearsals.programme_runtime_environment import (
    require_programme_runtime_environment,
)
from tests.rehearsals.programme_setup_scenarios import (
    SyntheticProgrammePerson,
    _create_person,
    approve_synthetic_role,
    person_from_document,
    scenario_from_document,
)

REASON = "Independent fictional Programme assessment for isolated acceptance."
PERSON_ROLES = (
    ("review-coordinator", "review-setup"),
    ("recusing-reviewer", "reviewer"),
    ("reviewer", "reviewer"),
    ("moderator", "moderator"),
    ("decider", "decision-maker"),
    ("converter", "conversion"),
)


class ProgrammeReviewScenarioError(RuntimeError):
    """Expose only stable stage codes at the private child boundary."""


@dataclass(frozen=True, slots=True)
class ProgrammeReviewScenario:
    """Keep exact review/conversion evidence and private independent personas."""

    organization_id: UUID
    edition_id: UUID
    department_id: UUID
    proposal_id: UUID
    revision_id: UUID
    case_id: UUID
    decision_id: UUID
    review_version: int
    transition_id: UUID
    item_id: UUID
    item_version: int
    control_version: int
    people: tuple[SyntheticProgrammePerson, ...] = field(repr=False)
    role_assignment_ids: tuple[UUID, ...]


def _people(setup, run_id):
    from maru.authorization.catalog import ScopeLevel  # noqa: PLC0415

    people, grants = [], []
    for label, code in PERSON_ROLES:
        person = _create_person(label, run_id=run_id)
        people.append(person)
        grants.append(
            approve_synthetic_role(
                setup,
                people=setup.controllers,
                recipient=person,
                code=code,
                level=ScopeLevel.DEPARTMENT,
                department_id=setup.department_id,
            )
        )
    grants.append(
        approve_synthetic_role(
            setup,
            people=setup.controllers,
            recipient=people[-1],
            code="content",
            level=ScopeLevel.EDITION,
        )
    )
    return tuple(people), tuple(grants)


def _policy():
    from maru.applications.programme_review_inputs import (  # noqa: PLC0415
        DECISION_OUTCOMES,
        ProgrammeDecisionTemplateInput,
        ProgrammeReviewCriterionInput,
        ProgrammeReviewPolicyInput,
        ProgrammeReviewStageInput,
    )

    # These explicit fictional choices are a rehearsal scenario, not product defaults.
    return ProgrammeReviewPolicyInput(
        stages=tuple(
            ProgrammeReviewStageInput(
                code=code,
                required_reviews=1,
                criteria=(
                    ProgrammeReviewCriterionInput(
                        "suitability", "Fictional suitability", 0, 5
                    ),
                ),
                question_keys=("session-title", "supporting-pdf"),
                anonymous=anonymous,
                discussion=not anonymous,
            )
            for code, anonymous in (
                ("anonymous-assessment", True),
                ("delivery-review", False),
            )
        ),
        templates=tuple(
            ProgrammeDecisionTemplateInput(
                outcome=outcome,
                text=f"Synthetic Programme outcome: {outcome}.",
                acknowledgement_required=True,
            )
            for outcome in sorted(DECISION_OUTCOMES)
        ),
    ).normalized()


def _apply(setup, person, command, version, *, recipient=False):
    from maru.applications.programme_review_commands import (  # noqa: PLC0415
        apply_programme_review_command,
    )

    return apply_programme_review_command(
        **_query_scope(setup, person),
        department_id=None if recipient else setup.department_id,
        command=command,
        expected_version=version,
        retry_key=uuid4(),
        reason=REASON,
    )


def _review_detail(setup, reviewer, case_id):
    from maru.applications.programme_review_authorization import REVIEW  # noqa: PLC0415
    from maru.applications.programme_review_queries import (  # noqa: PLC0415
        ProgrammeReviewReadRequest,
        get_programme_review_detail,
    )

    return get_programme_review_detail(
        request=ProgrammeReviewReadRequest(
            **_query_scope(setup, reviewer),
            department_id=setup.department_id,
            capability_code=REVIEW,
            requested_fields=frozenset({"review_context", "review_answers"}),
        ),
        case_id=case_id,
    )


def _require_review_denial(setup, reviewer, case_id):
    from maru.applications.programme_authorization import (  # noqa: PLC0415
        ApplicationsProgrammeAuthorizationDeniedError,
    )

    try:
        _review_detail(setup, reviewer, case_id)
    except ApplicationsProgrammeAuthorizationDeniedError:
        return
    raise ProgrammeReviewScenarioError("synthetic_private_review_not_denied")


def _inspect_review(setup, reviewer, *, case_id, version, anonymous):
    detail = _review_detail(setup, reviewer, case_id)
    context, answers = json.loads(detail.context_json), json.loads(detail.answers_json)
    if (
        detail.version != version
        or ("contributors" not in context) != anonymous
        or {answer["key"] for answer in answers}
        != ({"session-title"} if anonymous else {"session-title", "supporting-pdf"})
    ):
        raise ProgrammeReviewScenarioError("synthetic_review_disclosure_changed")


def _inspect_decision(setup, proposal, person, *, decision_id, version, acknowledged):
    from maru.applications.programme_review_authorization import (  # noqa: PLC0415
        VIEW_DECISION_SELF,
    )
    from maru.applications.programme_review_queries import (  # noqa: PLC0415
        ProgrammeReviewReadRequest,
        get_self_programme_decision,
    )

    message = get_self_programme_decision(
        request=ProgrammeReviewReadRequest(
            **_query_scope(setup, person),
            department_id=None,
            capability_code=VIEW_DECISION_SELF,
            requested_fields=frozenset({"decision_message", "own_acknowledgement"}),
        ),
        decision_id=decision_id,
    )
    if (
        message.decision_id != decision_id
        or message.case_version != version
        or message.outcome != "accepted"
        or message.source is None
        or message.source.revision_id != proposal.revision_id
        or message.own_acknowledged is not acknowledged
        or message.acknowledgement_required is not True
        or not message.message
        or REASON in message.message
    ):
        raise ProgrammeReviewScenarioError("synthetic_decision_disclosure_changed")


def _review(setup, proposal, people):
    from maru.applications.models import (  # noqa: PLC0415
        ProgrammeReviewAction as Action,
    )
    from maru.applications.programme_review_inputs import (  # noqa: PLC0415
        ProgrammeReviewCommandInput as Intent,
    )

    coordinator, recuser, reviewer, moderator, decider, _converter = people
    policy = _apply(
        setup,
        coordinator,
        Intent(Action.POLICY_CREATED, proposal.call_id, policy=_policy()),
        0,
    )
    case = _apply(
        setup,
        coordinator,
        Intent(
            Action.CASE_OPENED,
            proposal.proposal_id,
            policy_id=policy.target_id,
            reference_id=proposal.revision_id,
        ),
        0,
    )
    version = case.version
    assignment = _apply(
        setup,
        coordinator,
        Intent(Action.REVIEWER_ASSIGNED, case.case_id, reference_id=recuser.account_id),
        version,
    )
    recusal = _apply(
        setup,
        recuser,
        Intent(
            Action.REVIEWER_RECUSED, case.case_id, reference_id=assignment.target_id
        ),
        assignment.version,
    )
    version = recusal.version
    _require_review_denial(setup, recuser, case.case_id)
    for stage in range(2):
        assignment = _apply(
            setup,
            coordinator,
            Intent(
                Action.REVIEWER_ASSIGNED, case.case_id, reference_id=reviewer.account_id
            ),
            version,
        )
        _require_review_denial(setup, reviewer, case.case_id)
        cleared = _apply(
            setup,
            reviewer,
            Intent(
                Action.CONFLICT_CLEARED, case.case_id, reference_id=assignment.target_id
            ),
            assignment.version,
        )
        _inspect_review(
            setup,
            reviewer,
            case_id=case.case_id,
            version=cleared.version,
            anonymous=stage == 0,
        )
        scored = _apply(
            setup,
            reviewer,
            Intent(
                Action.SCORED,
                case.case_id,
                reference_id=assignment.target_id,
                scores=(("suitability", 4),),
            ),
            cleared.version,
        )
        version = scored.version
        if stage == 1:
            discussed = _apply(
                setup,
                reviewer,
                Intent(
                    Action.DISCUSSED,
                    case.case_id,
                    reference_id=assignment.target_id,
                    text="Fictional session has suitable supporting material.",
                ),
                version,
            )
            version = discussed.version
        moderated = _apply(
            setup, moderator, Intent(Action.MODERATED, case.case_id), version
        )
        version = moderated.version
        if stage == 0:
            advanced = _apply(
                setup, moderator, Intent(Action.STAGE_ADVANCED, case.case_id), version
            )
            version = advanced.version
    decision = _apply(
        setup,
        decider,
        Intent(
            Action.DECIDED,
            case.case_id,
            outcome="accepted",
            text="Your fictional proposal is accepted for private preparation.",
        ),
        version,
    )
    version = decision.version
    for person in (proposal.lead, proposal.collaborator):
        _inspect_decision(
            setup,
            proposal,
            person,
            decision_id=decision.target_id,
            version=version,
            acknowledged=False,
        )
        acknowledged = _apply(
            setup,
            person,
            Intent(Action.ACKNOWLEDGED, case.case_id, reference_id=decision.target_id),
            version,
            recipient=True,
        )
        version = acknowledged.version
        _inspect_decision(
            setup,
            proposal,
            person,
            decision_id=decision.target_id,
            version=version,
            acknowledged=True,
        )
    return case.case_id, decision.target_id, version


def _convert(setup, proposal, converter, *, decision_id, review_version):
    from maru.applications.programme_conversion_commands import (  # noqa: PLC0415
        convert_accepted_programme_proposal,
    )
    from maru.applications.programme_conversion_inputs import (  # noqa: PLC0415
        ProgrammeConversionInput,
    )
    from maru.applications.programme_conversion_queries import (  # noqa: PLC0415
        ProgrammeConversionReadRequest,
        get_programme_conversion_source,
    )
    from maru.programme.creation_queries import (  # noqa: PLC0415
        load_programme_creation_state,
    )
    from maru.programme.workbench_queries import (  # noqa: PLC0415
        ProgrammeWorkbenchRequest,
    )

    scope = _query_scope(setup, converter)
    scope.pop("source_channel")
    source = get_programme_conversion_source(
        request=ProgrammeConversionReadRequest(
            **scope, department_id=setup.department_id
        ),
        decision_id=decision_id,
    )
    creation = load_programme_creation_state(ProgrammeWorkbenchRequest(**scope))
    if (
        not source.eligible
        or source.consumed
        or not source.writable
        or not creation.writable
        or source.choice.revision_id != proposal.revision_id
        or source.choice.review_version != review_version
    ):
        raise ProgrammeReviewScenarioError("synthetic_conversion_source_changed")
    intent = ProgrammeConversionInput(
        decision_id=decision_id,
        revision_id=proposal.revision_id,
        expected_review_version=review_version,
        expected_programme_version=creation.control_version,
        internal_title="Synthetic accepted opening workshop",
        working_summary="Deliberate private copy, not copied proposal answers.",
    )
    retry_key = uuid4()
    converter.authenticate()
    values = dict(
        **scope,
        source_channel=CHANNEL,
        department_id=setup.department_id,
        command=intent,
        retry_key=retry_key,
        reason=REASON,
    )
    result = convert_accepted_programme_proposal(**values)
    converter.authenticate()
    replay = convert_accepted_programme_proposal(
        **(values | {"correlation_id": uuid4()})
    )
    if replay != replace(result, replayed=True):
        raise ProgrammeReviewScenarioError("synthetic_conversion_replay_changed")
    return result


def prepare_review_scenario(setup, proposal):
    """Run real review and private conversion with narrow independently approved roles.

    Parameters
    ----------
    setup
        Same owned foundation and two separate accountable synthetic controllers.
    proposal
        Exact submitted P02 result, including each contributor's private login.

    Returns
    -------
    ProgrammeReviewScenario
        Exact decision, private item and persona handles. Not hosting, publication,
        browser acceptance, human approval or completion of all P04 requirements.
    """
    environment = require_programme_runtime_environment()
    # Validate same-scope/person shape before any Django initialization or command.
    proposal = proposal_from_document(
        json.loads(json.dumps(asdict(proposal), default=str)), setup=setup
    )
    from tests.rehearsals.programme_runtime import (  # noqa: PLC0415
        build_candidate_application,
    )

    build_candidate_application()
    people, grants = _people(setup, environment.run_id)
    case_id, decision_id, version = _review(setup, proposal, people)
    converted = _convert(
        setup, proposal, people[-1], decision_id=decision_id, review_version=version
    )
    return ProgrammeReviewScenario(
        setup.organization_id,
        setup.edition_id,
        setup.department_id,
        proposal.proposal_id,
        proposal.revision_id,
        case_id,
        decision_id,
        version,
        converted.transition_id,
        converted.programme_item_id,
        converted.programme_item_version,
        converted.programme_control_version,
        people,
        grants,
    )


def _decode_review(document, setup, proposal):
    result = ProgrammeReviewScenario(
        **{
            key: UUID(value) if key.endswith("_id") else value
            for key, value in document.items()
            if key not in {"people", "role_assignment_ids"}
        },
        people=tuple(person_from_document(value) for value in document["people"]),
        role_assignment_ids=tuple(
            UUID(value) for value in document["role_assignment_ids"]
        ),
    )
    if (
        (
            result.organization_id,
            result.edition_id,
            result.department_id,
            result.proposal_id,
            result.revision_id,
        )
        != (
            setup.organization_id,
            setup.edition_id,
            setup.department_id,
            proposal.proposal_id,
            proposal.revision_id,
        )
        or len(result.people) != 6
        or len(result.role_assignment_ids) != 7
        or len(
            {
                p.account_id
                for p in (
                    *result.people,
                    *setup.controllers,
                    setup.intake_person,
                    proposal.lead,
                    proposal.collaborator,
                )
            }
        )
        != 11
        or any(
            type(value) is not int or value < 1
            for value in (
                result.review_version,
                result.item_version,
                result.control_version,
            )
        )
    ):
        raise ValueError
    return result


def review_from_document(document, *, setup, proposal):
    """Decode only exact same-source private review results and independent people."""
    try:
        return _decode_review(document, setup, proposal)
    except (KeyError, ValueError, TypeError, AttributeError):
        raise ProgrammeReviewScenarioError("synthetic_review_result_invalid") from None


def _read_input():
    raw = sys.stdin.read(32_769)
    if len(raw) > 32_768:
        raise ValueError
    document = json.loads(raw)
    if set(document) != {"setup", "proposal"}:
        raise ValueError
    setup = scenario_from_document(document["setup"], mode=document["setup"]["mode"])
    proposal = proposal_from_document(document["proposal"], setup=setup)
    return setup, proposal


def _main():
    require_programme_runtime_environment()
    try:
        result = prepare_review_scenario(*_read_input())
    except Exception:  # noqa: BLE001 - fixed private child protocol boundary
        raise SystemExit(2) from None
    sys.stdout.write(json.dumps(asdict(result), default=str))
    sys.stdout.flush()


if __name__ == "__main__":
    _main()
