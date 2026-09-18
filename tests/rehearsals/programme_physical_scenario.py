"""Private bounded handoff for actual physical approval and synthetic fit decisions."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass, field
from uuid import UUID

from tests.rehearsals.programme_items_scenario import items_from_document
from tests.rehearsals.programme_physical_preparation import (
    approve_room_roles,
    assess_accessibility,
    reserve_and_approve,
)
from tests.rehearsals.programme_planning_scenario import planning_from_document
from tests.rehearsals.programme_proposal_scenario import proposal_from_document
from tests.rehearsals.programme_review_scenario import review_from_document
from tests.rehearsals.programme_runtime_environment import (
    require_programme_runtime_environment,
)
from tests.rehearsals.programme_setup_scenarios import (
    SyntheticProgrammePerson,
    _create_person,
    person_from_document,
    scenario_from_document,
)


class ProgrammePhysicalScenarioError(RuntimeError):
    """Return stable fixture-stage failures without private source data."""


@dataclass(frozen=True, slots=True)
class ProgrammePhysicalScenario:
    """Exact physical/fit handles, never Programme release or real safety evidence."""

    organization_id: UUID
    edition_id: UUID
    candidate_id: UUID
    candidate_revision_id: UUID
    placement_ids: tuple[UUID, ...]
    reservation_intent_ids: tuple[UUID, ...]
    booking_ids: tuple[UUID, ...]
    booking_versions: tuple[int, ...]
    blocked_decision_ids: tuple[UUID, ...]
    fit_decision_ids: tuple[UUID, ...]
    fit_source_digests: tuple[str, ...]
    reviewer: SyntheticProgrammePerson = field(repr=False)
    role_assignment_ids: tuple[UUID, ...]


def physical_sources(document):
    """Validate the complete same-source chain without starting or authorizing it."""
    if set(document) != {"setup", "proposal", "review", "items", "planning"}:
        raise ProgrammePhysicalScenarioError("physical_sources_invalid")
    setup = scenario_from_document(document["setup"], mode=document["setup"]["mode"])
    proposal = proposal_from_document(document["proposal"], setup=setup)
    review = review_from_document(document["review"], setup=setup, proposal=proposal)
    items = items_from_document(
        document["items"], setup=setup, proposal=proposal, review=review
    )
    planning = planning_from_document(
        document["planning"], setup=setup, proposal=proposal, review=review, items=items
    )
    return setup, proposal, review, items, planning


def _decode_physical(document, *, setup, proposal, review, items, planning):
    values = dict(document)
    values["reviewer"] = person_from_document(values["reviewer"])
    for key in tuple(values):
        if key.endswith("_ids"):
            values[key] = tuple(UUID(value) for value in values[key])
        elif key.endswith("_id"):
            values[key] = UUID(values[key])
    for key in ("booking_versions", "fit_source_digests"):
        values[key] = tuple(values[key])
    result = ProgrammePhysicalScenario(**values)
    people = (
        *setup.controllers,
        setup.intake_person,
        proposal.lead,
        proposal.collaborator,
        *review.people,
        items.public_reviewer,
        items.ceremony_host,
        planning.planner,
        planning.catalog_person,
        result.reviewer,
    )
    if (
        (
            result.organization_id,
            result.edition_id,
            result.candidate_id,
            result.candidate_revision_id,
        )
        != (
            setup.organization_id,
            setup.edition_id,
            planning.candidate_id,
            planning.candidate_revision_id,
        )
        or result.placement_ids != planning.placement_ids
        or len({p.account_id for p in people}) != 16
        or any(
            len(value) != 3 or len(set(value)) != 3 or any(not v.int for v in value)
            for key, value in values.items()
            if key.endswith("_ids")
        )
        or set(result.blocked_decision_ids) & set(result.fit_decision_ids)
        or len(result.booking_versions) != 3
        or any(type(v) is not int or v < 2 for v in result.booking_versions)
        or len(result.fit_source_digests) != 3
        or any(
            not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v)
            for v in result.fit_source_digests
        )
        or any(isinstance(v, UUID) and not v.int for v in values.values())
    ):
        raise ValueError
    return result


def physical_from_document(document, *, setup, proposal, review, items, planning):
    """Decode bounded opaque results, never treat them as current owner authority."""
    try:
        return _decode_physical(
            document,
            setup=setup,
            proposal=proposal,
            review=review,
            items=items,
            planning=planning,
        )
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ProgrammePhysicalScenarioError(
            "synthetic_physical_result_invalid"
        ) from None


def prepare_physical_scenario(setup, proposal, review, items, planning):
    """Use the guarded application, genuine grants and exact public owner seams."""
    environment = require_programme_runtime_environment()
    sources = physical_sources(
        json.loads(
            json.dumps(
                {
                    key: asdict(value)
                    for key, value in zip(
                        ("setup", "proposal", "review", "items", "planning"),
                        (setup, proposal, review, items, planning),
                        strict=True,
                    )
                },
                default=str,
            )
        )
    )
    setup, proposal, review, items, planning = sources
    from tests.rehearsals.programme_runtime import (  # noqa: PLC0415
        build_candidate_application,
    )

    build_candidate_application()
    reviewer = _create_person("physical-reviewer", run_id=environment.run_id)
    grants = approve_room_roles(setup, planning, reviewer)
    intents, bookings, versions = reserve_and_approve(setup, planning, reviewer)
    blocked, satisfied, digests = assess_accessibility(setup, items, planning)
    return ProgrammePhysicalScenario(
        setup.organization_id,
        setup.edition_id,
        planning.candidate_id,
        planning.candidate_revision_id,
        planning.placement_ids,
        intents,
        bookings,
        versions,
        blocked,
        satisfied,
        digests,
        reviewer,
        grants,
    )


def _read_input():
    raw = sys.stdin.read(65_537)
    if len(raw) > 65_536:
        raise ValueError
    return physical_sources(json.loads(raw))


def _main():
    require_programme_runtime_environment()
    try:
        result = prepare_physical_scenario(*_read_input())
    except Exception:  # noqa: BLE001 - private fixed child boundary
        raise SystemExit(2) from None
    sys.stdout.write(json.dumps(asdict(result), default=str))
    sys.stdout.flush()


if __name__ == "__main__":
    _main()
