"""Private same-source P06 handoff; no native or human acceptance is implied."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from uuid import UUID

from tests.rehearsals.programme_physical_scenario import (
    physical_from_document,
    physical_sources,
)
from tests.rehearsals.programme_runtime_environment import (
    require_programme_runtime_environment,
)
from tests.rehearsals.programme_setup_scenarios import (
    SyntheticProgrammePerson,
    _create_person,
    person_from_document,
)
from tests.rehearsals.programme_staffing_preparation import (
    approve_staffing_roles,
    approve_starter,
    prepare_bound_shifts,
    prepare_position_and_assignment,
)

SOURCE_KEYS = ("setup", "proposal", "review", "items", "planning", "physical")


class ProgrammeStaffingScenarioError(RuntimeError):
    """Expose a stable private fixture failure without credentials or personnel."""


@dataclass(frozen=True, slots=True)
class PreparedProgrammeWork:
    """Exact requirement/binding and retained locked-work identities."""

    requirement_id: UUID
    requirement_revision_id: UUID
    binding_id: UUID
    demand_id: UUID
    demand_version: int
    commitment_id: UUID
    commitment_version: int


@dataclass(frozen=True, slots=True)
class ProgrammeStaffingScenario:
    """Retain same-source work handles, never grant authority from a document."""

    organization_id: UUID
    edition_id: UUID
    candidate_id: UUID
    candidate_revision_id: UUID
    placement_ids: tuple[UUID, ...]
    starter_request_id: UUID
    template_id: UUID
    position_id: UUID
    assignment_id: UUID
    volunteer: SyntheticProgrammePerson = field(repr=False)
    role_assignment_ids: tuple[UUID, ...]
    work: tuple[PreparedProgrammeWork, ...]


def staffing_sources(document):
    """Validate the complete exact predecessor chain before any framework action."""
    if set(document) != set(SOURCE_KEYS):
        raise ProgrammeStaffingScenarioError("staffing_sources_invalid")
    previous = {key: document[key] for key in SOURCE_KEYS[:-1]}
    sources = physical_sources(previous)
    physical = physical_from_document(
        document["physical"], **dict(zip(SOURCE_KEYS[:-1], sources, strict=True))
    )
    return (*sources, physical)


def _decode(document, *, setup, proposal, review, items, planning, physical):
    values = dict(document)
    values["volunteer"] = person_from_document(values["volunteer"])
    for key in tuple(values):
        if key.endswith("_ids"):
            values[key] = tuple(UUID(value) for value in values[key])
        elif key.endswith("_id"):
            values[key] = UUID(values[key])
    values["work"] = tuple(
        PreparedProgrammeWork(
            **{
                key: UUID(value) if key.endswith("_id") else value
                for key, value in row.items()
            }
        )
        for row in values["work"]
    )
    result = ProgrammeStaffingScenario(**values)
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
        physical.reviewer,
        result.volunteer,
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
        or len({person.account_id for person in people}) != 17
        or len(result.role_assignment_ids) != 2
        or len(set(result.role_assignment_ids)) != 2
        or len(result.work) != 3
        or any(isinstance(value, UUID) and not value.int for value in values.values())
        or any(not value.int for value in result.role_assignment_ids)
        or any(
            len({getattr(row, key) for row in result.work}) != 3
            or any(not getattr(row, key).int for row in result.work)
            for key in (
                "requirement_id",
                "requirement_revision_id",
                "binding_id",
                "demand_id",
                "commitment_id",
            )
        )
        or any(
            type(v) is not int or v < 2
            for row in result.work
            for v in (row.demand_version, row.commitment_version)
        )
    ):
        raise ValueError
    return result


def staffing_from_document(document, **sources):
    """Decode bounded original handles without treating them as current authority."""
    try:
        return _decode(document, **sources)
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ProgrammeStaffingScenarioError(
            "synthetic_staffing_result_invalid"
        ) from None


def prepare_staffing_scenario(setup, proposal, review, items, planning, physical):
    """Use genuine guarded owners and separately authenticated people's decisions."""
    environment = require_programme_runtime_environment()
    documents = json.loads(
        json.dumps(
            dict(
                zip(
                    SOURCE_KEYS,
                    map(asdict, (setup, proposal, review, items, planning, physical)),
                    strict=True,
                )
            ),
            default=str,
        )
    )
    setup, proposal, review, items, planning, physical = staffing_sources(documents)
    from tests.rehearsals.programme_runtime import (  # noqa: PLC0415
        build_candidate_application,
    )

    build_candidate_application()
    volunteer = _create_person("staffing-volunteer", run_id=environment.run_id)
    original, template = approve_starter(setup)
    position, assignment = prepare_position_and_assignment(
        setup, items, volunteer, template
    )
    grants = approve_staffing_roles(setup, planning.planner)
    work = tuple(
        PreparedProgrammeWork(*row)
        for row in prepare_bound_shifts(setup, planning, volunteer, position)
    )
    result = ProgrammeStaffingScenario(
        setup.organization_id,
        setup.edition_id,
        planning.candidate_id,
        planning.candidate_revision_id,
        planning.placement_ids,
        original,
        template,
        position,
        assignment,
        volunteer,
        grants,
        work,
    )
    return staffing_from_document(
        json.loads(json.dumps(asdict(result), default=str)),
        **dict(
            zip(
                SOURCE_KEYS,
                (setup, proposal, review, items, planning, physical),
                strict=True,
            )
        ),
    )


def _read_input():
    raw = sys.stdin.read(65_537)
    if len(raw) > 65_536:
        raise ValueError
    return staffing_sources(json.loads(raw))


def _main():
    require_programme_runtime_environment()
    try:
        result = prepare_staffing_scenario(*_read_input())
    except Exception:  # noqa: BLE001 - private fixed child boundary
        raise SystemExit(2) from None
    sys.stdout.write(json.dumps(asdict(result), default=str))
    sys.stdout.flush()


if __name__ == "__main__":
    _main()
