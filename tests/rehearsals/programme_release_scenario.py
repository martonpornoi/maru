"""Guarded same-source first-release preparation; not native or human acceptance."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass, field
from uuid import UUID

from tests.rehearsals.programme_release_preparation import (
    approve_release_roles,
    prepare_first_release,
)
from tests.rehearsals.programme_runtime_environment import (
    require_programme_runtime_environment,
)
from tests.rehearsals.programme_setup_scenarios import (
    SyntheticProgrammePerson,
    _create_person,
    person_from_document,
)
from tests.rehearsals.programme_staffing_scenario import (
    staffing_from_document,
    staffing_sources,
)

SOURCE_KEYS = (
    "setup",
    "proposal",
    "review",
    "items",
    "planning",
    "physical",
    "staffing",
)


class ProgrammeReleaseScenarioError(RuntimeError):
    """Keep private fixture errors content-free."""


@dataclass(frozen=True, slots=True)
class ProgrammeReleaseScenario:
    """Retain exact original publication and independent person, not authority."""

    organization_id: UUID
    edition_id: UUID
    candidate_id: UUID
    candidate_revision_id: UUID
    placement_ids: tuple[UUID, ...]
    reviewer: SyntheticProgrammePerson = field(repr=False)
    role_assignment_ids: tuple[UUID, ...]
    approval_id: UUID
    release_id: UUID
    pointer_version: int
    source_digest: str


def release_sources(document):
    """Validate every original predecessor before any owner or framework action."""
    if set(document) != set(SOURCE_KEYS):
        raise ProgrammeReleaseScenarioError("release_sources_invalid")
    sources = staffing_sources({key: document[key] for key in SOURCE_KEYS[:-1]})
    staffing = staffing_from_document(
        document["staffing"],
        **dict(zip(SOURCE_KEYS[:-1], sources, strict=True)),
    )
    return (*sources, staffing)


def _decode(document, *, setup, proposal, review, items, planning, physical, staffing):
    values = dict(document)
    values["reviewer"] = person_from_document(values["reviewer"])
    for key in tuple(values):
        if key.endswith("_ids"):
            values[key] = tuple(UUID(value) for value in values[key])
        elif key.endswith("_id"):
            values[key] = UUID(values[key])
    result = ProgrammeReleaseScenario(**values)
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
        staffing.volunteer,
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
        or len({person.account_id for person in people}) != 18
        or len(result.role_assignment_ids) != 13
        or len(set(result.role_assignment_ids)) != 13
        or any(not value.int for value in result.role_assignment_ids)
        or any(isinstance(value, UUID) and not value.int for value in values.values())
        or result.approval_id == result.release_id
        or type(result.pointer_version) is not int
        or result.pointer_version != 1
        or type(result.source_digest) is not str
        or re.fullmatch(r"[0-9a-f]{64}", result.source_digest) is None
    ):
        raise ValueError
    return result


def release_from_document(document, **sources):
    """Decode closed exact original handles; never use them as permission."""
    try:
        return _decode(document, **sources)
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ProgrammeReleaseScenarioError(
            "synthetic_release_result_invalid"
        ) from None


def prepare_release_scenario(
    setup, proposal, review, items, planning, physical, staffing
):
    """Compose authenticated owners under the unchanged genuine runtime guard."""
    environment = require_programme_runtime_environment()
    documents = json.loads(
        json.dumps(
            dict(
                zip(
                    SOURCE_KEYS,
                    map(
                        asdict,
                        (setup, proposal, review, items, planning, physical, staffing),
                    ),
                    strict=True,
                )
            ),
            default=str,
        )
    )
    sources = release_sources(documents)
    setup, proposal, review, items, planning, physical, staffing = sources
    from tests.rehearsals.programme_release_outputs import (  # noqa: PLC0415
        verify_release_outputs,
    )
    from tests.rehearsals.programme_runtime import (  # noqa: PLC0415
        build_candidate_application,
    )

    build_candidate_application()
    reviewer = _create_person("timetable-reviewer", run_id=environment.run_id)
    grants = approve_release_roles(setup, planning, reviewer)
    publication = prepare_first_release(setup, items, planning, reviewer)
    result = ProgrammeReleaseScenario(
        setup.organization_id,
        setup.edition_id,
        planning.candidate_id,
        planning.candidate_revision_id,
        planning.placement_ids,
        reviewer,
        grants,
        *publication,
    )
    verify_release_outputs(setup, proposal, items, planning, staffing, result)
    return release_from_document(
        json.loads(json.dumps(asdict(result), default=str)),
        **dict(zip(SOURCE_KEYS, sources, strict=True)),
    )


def _read_input():
    raw = sys.stdin.read(65_537)
    if len(raw) > 65_536:
        raise ValueError
    return release_sources(json.loads(raw))


def _main():
    require_programme_runtime_environment()
    try:
        result = prepare_release_scenario(*_read_input())
    except Exception:  # noqa: BLE001 - private fixed child boundary
        raise SystemExit(2) from None
    sys.stdout.write(json.dumps(asdict(result), default=str))
    sys.stdout.flush()


if __name__ == "__main__":
    _main()
