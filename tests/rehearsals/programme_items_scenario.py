"""Real Programme item/layer/hosting preparation; never production or human evidence."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from tests.rehearsals.programme_proposal_scenario import (
    _query_scope,
    proposal_from_document,
)
from tests.rehearsals.programme_review_scenario import review_from_document
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

REASON = "Synthetic Programme item preparation; no real on-site readiness approval."
PRIVATE_NOTE = "Private fictional organizer discussion; never public or host copy."
DELIVERY_CONCERNS = ("technical_needs", "accessibility_delivery", "media_consent")


class ProgrammeItemsScenarioError(RuntimeError):
    """Expose only a stable fixture-stage failure without private layer contents."""


@dataclass(frozen=True, slots=True)
class PreparedProgrammeItem:
    """Retain exact final item, host and reviewed-copy versions for scheduling."""

    item_id: UUID
    version: int
    host_id: UUID
    host_version: int
    public_rendition_id: UUID
    public_rendition_number: int


@dataclass(frozen=True, slots=True)
class ProgrammeItemsScenario:
    """Two separately sourced items and explicit synthetic hosting availability."""

    organization_id: UUID
    edition_id: UUID
    accepted: PreparedProgrammeItem
    ceremony: PreparedProgrammeItem
    availability_starts_at: datetime
    availability_ends_at: datetime
    public_reviewer: SyntheticProgrammePerson = field(repr=False)
    ceremony_host: SyntheticProgrammePerson = field(repr=False)
    role_assignment_ids: tuple[UUID, ...]


def _command(command, setup, person, item_id, version, *, reason=REASON, **values):
    return command(
        **_query_scope(setup, person),
        item_id=item_id,
        expected_version=version,
        idempotency_key=uuid4(),
        reason=reason,
        **values,
    )


def _private_item(setup, person, item_id):
    from maru.programme.workbench_queries import (  # noqa: PLC0415
        ProgrammeWorkbenchRequest,
        load_programme_workbench_item,
    )

    scope = _query_scope(setup, person)
    scope.pop("source_channel")
    return load_programme_workbench_item(
        ProgrammeWorkbenchRequest(**scope), item_id=item_id
    )


def _readiness(setup, person, item_id):
    from maru.programme.queries import load_programme_readiness  # noqa: PLC0415

    return {
        row.concern: row.state
        for row in load_programme_readiness(
            **_query_scope(setup, person),
            item_id=item_id,
            reason=REASON,
        )
    }


def _delivery(setup, editor, item_id, version, *, corrected=False):
    from maru.programme.commands import revise_programme_delivery  # noqa: PLC0415

    return _command(
        revise_programme_delivery,
        setup,
        editor,
        item_id,
        version,
        technical_requirements="One handheld microphone and one optional projector.",
        accessibility_delivery=(
            "Keep clear wheelchair access and a quiet exit; check seating before entry."
            if corrected
            else "Keep clear wheelchair access and a quiet exit."
        ),
        media_consent_notes="No photography or recording in this fictional session.",
    )


def _attest(setup, editor, item_id, version, concern, *, source=None, sequence=None):
    from maru.programme.commands import (  # noqa: PLC0415
        record_programme_readiness_evidence,
    )

    values = {}
    if source is not None:
        values = {
            "source_code": "programme.evidence.public-rendition@1"
            if concern == "public_copy"
            else "programme.evidence.delivery-revision@1",
            "source_object_id": source,
            "source_version": sequence,
        }
    return _command(
        record_programme_readiness_evidence,
        setup,
        editor,
        item_id,
        version,
        concern=concern,
        state="satisfied",
        evidence_note="Synthetic evidence checked against the exact prepared source.",
        **values,
    ).resulting_item_version


def _host_read(setup, person, item_id, *, organizer=False):
    from maru.programme.host_queries import (  # noqa: PLC0415
        ProgrammeHostReadRequest,
        load_programme_host_dependencies,
        load_programme_host_self,
    )

    request = ProgrammeHostReadRequest(**_query_scope(setup, person), item_id=item_id)
    return (
        load_programme_host_dependencies(request)
        if organizer
        else load_programme_host_self(request)
    )


def _require_private_denial(setup, host, item_id):
    from maru.programme.authorization import (  # noqa: PLC0415
        ProgrammeAuthorizationDeniedError,
    )

    try:
        _private_item(setup, host, item_id)
    except ProgrammeAuthorizationDeniedError:
        return
    raise ProgrammeItemsScenarioError("synthetic_host_private_layer_not_denied")


def _require_no_host_relationship(setup, person, item_id):
    from maru.programme.authorization import (  # noqa: PLC0415
        ProgrammeAuthorizationDeniedError,
    )

    try:
        _host_read(setup, person, item_id)
    except ProgrammeAuthorizationDeniedError:
        return
    raise ProgrammeItemsScenarioError("synthetic_host_relationship_already_exists")


def _confirm_host(setup, editor, host, item_id, version, period):
    from maru.programme.host_commands import (  # noqa: PLC0415
        invite_programme_host,
        replace_programme_host_availability,
        respond_to_programme_host_invitation,
    )
    from maru.programme.host_inputs import (  # noqa: PLC0415
        ProgrammeHostAvailabilityInput,
        ProgrammeHostInvitationInput,
        ProgrammeHostResponseInput,
    )

    _require_no_host_relationship(setup, host, item_id)
    invitation = invite_programme_host(
        **_query_scope(setup, editor),
        item_id=item_id,
        invitation=ProgrammeHostInvitationInput(
            account_id=host.account_id,
            role="host",
            title="Host a fictional Programme item",
            briefing="Please arrive early and check the microphone with the room team.",
            expected_item_version=version,
        ),
        reason=REASON,
        idempotency_key=uuid4(),
    )
    own = _host_read(setup, host, item_id)
    if (
        own.relationship.host_id != invitation.host_id
        or own.relationship.state != "invited"
    ):
        raise ProgrammeItemsScenarioError("synthetic_host_invitation_changed")
    _require_private_denial(setup, host, item_id)
    confirmed = respond_to_programme_host_invitation(
        **_query_scope(setup, host),
        item_id=item_id,
        response=ProgrammeHostResponseInput(
            host_id=invitation.host_id,
            response="confirm",
            expected_item_version=own.item_version,
            expected_host_version=own.relationship.version,
            invitation_sequence=own.relationship.invitation_sequence,
        ),
        idempotency_key=uuid4(),
    )
    result = confirmed
    for state in ("draft", "shared"):
        result = replace_programme_host_availability(
            **_query_scope(setup, host),
            item_id=item_id,
            availability=ProgrammeHostAvailabilityInput(
                host_id=result.host_id,
                state=state,
                periods=(period,),
                expected_item_version=result.resulting_item_version,
                expected_host_version=result.resulting_host_version,
            ),
            idempotency_key=uuid4(),
        )
        visible = _host_read(setup, editor, item_id, organizer=True)
        if (
            len(visible.hosts) != 1
            or visible.hosts[0].status
            != ("not_shared" if state == "draft" else "shared")
            or visible.hosts[0].periods != (() if state == "draft" else (period,))
        ):
            raise ProgrammeItemsScenarioError(
                "synthetic_host_availability_disclosure_changed"
            )
    _require_private_denial(setup, host, item_id)
    return result


def _prepare_item(setup, editor, reviewer, host, item_id, title, period):
    from maru.programme import commands  # noqa: PLC0415
    from maru.programme.catalogs import ProgrammeReadinessConcern  # noqa: PLC0415
    from maru.programme.queries import load_programme_public_copy  # noqa: PLC0415

    source = _private_item(setup, editor, item_id)
    working = _command(
        commands.revise_programme_working,
        setup,
        editor,
        item_id,
        source.private.item.aggregate_version,
        internal_title=f"Working: {title}",
        working_summary="Private organizer preparation, not public wording.",
    )
    discussion = _command(
        commands.append_programme_discussion,
        setup,
        editor,
        item_id,
        working.resulting_item_version,
        body=PRIVATE_NOTE,
    )
    version = discussion.resulting_item_version
    for concern in ProgrammeReadinessConcern:
        # Private proposal evidence stays Applications-owned. Neither on-site item
        # in this deliberate scenario needs a Programme delivery file or handout.
        configured = _command(
            commands.configure_programme_readiness,
            setup,
            editor,
            item_id,
            version,
            concern=concern,
            disposition="not_applicable"
            if concern.value == "required_files"
            else "required",
            reason=(
                "No on-site file or handout is needed; private proposal evidence "
                "remains Applications-owned."
                if concern.value == "required_files"
                else REASON
            ),
        )
        version = configured.resulting_item_version
    delivery = _delivery(setup, editor, item_id, version)
    version = delivery.resulting_item_version
    for concern in DELIVERY_CONCERNS:
        version = _attest(
            setup,
            editor,
            item_id,
            version,
            concern,
            source=delivery.result_object_id,
            sequence=1,
        )
    corrected = _delivery(setup, editor, item_id, version, corrected=True)
    states = _readiness(setup, editor, item_id)
    if any(states.get(concern) != "stale" for concern in DELIVERY_CONCERNS):
        raise ProgrammeItemsScenarioError("synthetic_delivery_edit_not_stale")
    hosted = _confirm_host(
        setup, editor, host, item_id, corrected.resulting_item_version, period
    )
    current = _private_item(setup, reviewer, item_id)
    approved = _command(
        commands.approve_programme_public_rendition,
        setup,
        reviewer,
        item_id,
        current.private.item.aggregate_version,
        source_working_revision_id=current.working_revision_id,
        public_title=title,
        public_summary="A fictional session for synthetic Programme acceptance.",
        public_content_note="No recording or photography.",
    )
    public = load_programme_public_copy(
        **_query_scope(setup, reviewer), item_id=item_id
    )
    if public is None or public.public_title != title:
        raise ProgrammeItemsScenarioError("synthetic_reviewed_copy_unavailable")
    version = _attest(
        setup,
        editor,
        item_id,
        approved.resulting_item_version,
        "public_copy",
        source=approved.result_object_id,
        sequence=public.rendition_number,
    )
    for concern in DELIVERY_CONCERNS:
        version = _attest(
            setup,
            editor,
            item_id,
            version,
            concern,
            source=corrected.result_object_id,
            sequence=2,
        )
    for concern in ("host_confirmation", "schedule_availability"):
        version = _attest(setup, editor, item_id, version, concern)
    states = _readiness(setup, editor, item_id)
    expected = {
        concern.value: "not_applicable"
        if concern.value == "required_files"
        else "satisfied"
        for concern in ProgrammeReadinessConcern
    }
    if states != expected:
        raise ProgrammeItemsScenarioError("synthetic_item_readiness_incomplete")
    own = _host_read(setup, host, item_id)
    if own.public_copy != public or own.relationship.state != "confirmed":
        raise ProgrammeItemsScenarioError("synthetic_host_copy_unavailable")
    return PreparedProgrammeItem(
        item_id,
        version,
        hosted.host_id,
        hosted.resulting_host_version,
        approved.result_object_id,
        public.rendition_number,
    )


def prepare_items_scenario(setup, proposal, review):
    """Prepare two genuine-source items with independently reviewed copy and hosts.

    Parameters
    ----------
    setup
        Exact original owned foundation and controllers.
    proposal
        Exact submitted call result and independent contributor accounts.
    review
        Exact accepted conversion and ordinary converter with existing content role.

    Returns
    -------
    ProgrammeItemsScenario
        Prepared source versions and private personas; not a published timetable,
        browser/human acceptance or an attestation about a real convention.
    """
    environment = require_programme_runtime_environment()
    proposal = proposal_from_document(
        json.loads(json.dumps(asdict(proposal), default=str)), setup=setup
    )
    review = review_from_document(
        json.loads(json.dumps(asdict(review), default=str)),
        setup=setup,
        proposal=proposal,
    )
    from tests.rehearsals.programme_runtime import (  # noqa: PLC0415
        build_candidate_application,
    )

    build_candidate_application()
    from maru.authorization.catalog import ScopeLevel  # noqa: PLC0415
    from maru.events.queries import (  # noqa: PLC0415
        resolve_edition_time_envelope_reference,
    )
    from maru.programme.commands import create_organizer_core_item  # noqa: PLC0415
    from maru.programme.creation_queries import (  # noqa: PLC0415
        load_programme_creation_state,
    )
    from maru.programme.host_inputs import (  # noqa: PLC0415
        ProgrammeHostAvailabilityPeriod,
    )
    from maru.programme.workbench_queries import (  # noqa: PLC0415
        ProgrammeWorkbenchRequest,
    )

    editor = review.people[-1]
    reviewer = _create_person("public-copy-reviewer", run_id=environment.run_id)
    ceremony_host = _create_person("ceremony-host", run_id=environment.run_id)
    grants = tuple(
        approve_synthetic_role(
            setup,
            people=setup.controllers,
            recipient=person,
            code=code,
            level=ScopeLevel.EDITION,
        )
        for person, code in (
            (editor, "hosting"),
            (editor, "delivery"),
            (reviewer, "content"),
        )
    )
    # Real Programme authorization precedes the public internal Events fact read.
    scope = _query_scope(setup, editor)
    scope.pop("source_channel")
    creation = load_programme_creation_state(ProgrammeWorkbenchRequest(**scope))
    envelope = resolve_edition_time_envelope_reference(
        organization_id=setup.organization_id, edition_id=setup.edition_id
    )
    if not creation.writable or envelope is None:
        raise ProgrammeItemsScenarioError("synthetic_item_edition_unavailable")
    period = ProgrammeHostAvailabilityPeriod(
        envelope.starts_at + timedelta(hours=9),
        envelope.starts_at + timedelta(hours=18),
    ).normalized()
    core = create_organizer_core_item(
        **_query_scope(setup, editor),
        kind="ceremony",
        internal_title="Synthetic opening ceremony",
        working_summary="Organizer-created core item without proposal provenance.",
        expected_version=creation.control_version,
        reason=REASON,
        idempotency_key=uuid4(),
    )
    accepted = _prepare_item(
        setup,
        editor,
        reviewer,
        proposal.lead,
        review.item_id,
        "Fictional convention workshop",
        period,
    )
    ceremony = _prepare_item(
        setup,
        editor,
        reviewer,
        ceremony_host,
        core.item_id,
        "Fictional opening ceremony",
        period,
    )
    return ProgrammeItemsScenario(
        setup.organization_id,
        setup.edition_id,
        accepted,
        ceremony,
        period.starts_at,
        period.ends_at,
        reviewer,
        ceremony_host,
        grants,
    )


def _decode_items(document, setup, proposal, review):
    def item(value):
        result = PreparedProgrammeItem(
            **{
                key: UUID(raw) if key.endswith("_id") else raw
                for key, raw in value.items()
            }
        )
        if any(
            type(raw) is not int or raw < 1
            for raw in (
                result.version,
                result.host_version,
                result.public_rendition_number,
            )
        ):
            raise ValueError
        return result

    result = ProgrammeItemsScenario(
        organization_id=UUID(document["organization_id"]),
        edition_id=UUID(document["edition_id"]),
        accepted=item(document["accepted"]),
        ceremony=item(document["ceremony"]),
        availability_starts_at=datetime.fromisoformat(
            document["availability_starts_at"]
        ),
        availability_ends_at=datetime.fromisoformat(document["availability_ends_at"]),
        public_reviewer=person_from_document(document["public_reviewer"]),
        ceremony_host=person_from_document(document["ceremony_host"]),
        role_assignment_ids=tuple(
            UUID(value) for value in document["role_assignment_ids"]
        ),
    )
    if (
        set(document) != set(asdict(result))
        or (result.organization_id, result.edition_id)
        != (setup.organization_id, setup.edition_id)
        or result.accepted.item_id != review.item_id
        or result.ceremony.item_id == review.item_id
        or len(result.role_assignment_ids) != 3
        or len(
            {
                p.account_id
                for p in (
                    *setup.controllers,
                    setup.intake_person,
                    proposal.lead,
                    proposal.collaborator,
                    *review.people,
                    result.public_reviewer,
                    result.ceremony_host,
                )
            }
        )
        != 13
        or result.availability_starts_at.utcoffset() is None
        or result.availability_ends_at.utcoffset() is None
        or result.availability_starts_at >= result.availability_ends_at
    ):
        raise ValueError
    return result


def items_from_document(document, *, setup, proposal, review):
    """Decode exact source and distinct people without renewing authority."""
    try:
        return _decode_items(document, setup, proposal, review)
    except (KeyError, ValueError, TypeError, AttributeError):
        raise ProgrammeItemsScenarioError("synthetic_items_result_invalid") from None


def _read_input():
    raw = sys.stdin.read(49_153)
    if len(raw) > 49_152:
        raise ValueError
    document = json.loads(raw)
    if set(document) != {"setup", "proposal", "review"}:
        raise ValueError
    setup = scenario_from_document(document["setup"], mode=document["setup"]["mode"])
    proposal = proposal_from_document(document["proposal"], setup=setup)
    review = review_from_document(document["review"], setup=setup, proposal=proposal)
    return setup, proposal, review


def _main():
    require_programme_runtime_environment()
    try:
        result = prepare_items_scenario(*_read_input())
    except Exception:  # noqa: BLE001 - fixed private child protocol boundary
        raise SystemExit(2) from None
    sys.stdout.write(json.dumps(asdict(result), default=str))
    sys.stdout.flush()


if __name__ == "__main__":
    _main()
