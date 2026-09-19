"""Guarded retained-work change and notices; native proof remains deferred."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from uuid import UUID

from tests.rehearsals.programme_release_scenario import (
    release_from_document,
    release_sources,
)
from tests.rehearsals.programme_runtime_environment import (
    require_programme_runtime_environment,
)
from tests.rehearsals.programme_staffing_scenario import PreparedProgrammeWork

SOURCE_KEYS = (
    "setup",
    "proposal",
    "review",
    "items",
    "planning",
    "physical",
    "staffing",
    "release",
)


class ProgrammeChangeScenarioError(RuntimeError):
    """Expose only a fixed private-child failure code."""


@dataclass(frozen=True, slots=True)
class ProgrammeChangeScenario:
    """Original lineage, new acceptance and exact notices; never portable authority."""

    organization_id: UUID
    edition_id: UUID
    previous_release_id: UUID
    predecessor_demand_id: UUID
    predecessor_commitment_id: UUID
    work: PreparedProgrammeWork
    approval_id: UUID
    release_id: UUID
    source_digest: str
    pointer_version: int
    role_assignment_ids: tuple[UUID, ...]
    notice_ids: tuple[UUID, ...]


def change_sources(document):
    """Validate all eight original private source documents before owner actions."""
    if set(document) != set(SOURCE_KEYS):
        raise ProgrammeChangeScenarioError("change_sources_invalid")
    previous = release_sources({key: document[key] for key in SOURCE_KEYS[:-1]})
    release = release_from_document(
        document["release"], **dict(zip(SOURCE_KEYS[:-1], previous, strict=True))
    )
    return (*previous, release)


def _reject_invalid(condition):
    if condition:
        raise ProgrammeChangeScenarioError("synthetic_change_result_invalid")


def _decode(document, *, setup, staffing, release):
    """Require exact original lineage and closed new handles without granting access."""
    try:
        values = dict(document)
        values["work"] = PreparedProgrammeWork(
            **{
                key: UUID(value) if key.endswith("_id") else value
                for key, value in values["work"].items()
            }
        )
        for key in tuple(values):
            if key.endswith("_ids"):
                values[key] = tuple(UUID(value) for value in values[key])
            elif key.endswith("_id"):
                values[key] = UUID(values[key])
        result = ProgrammeChangeScenario(**values)
        original = staffing.work[0]
        _reject_invalid(
            (result.organization_id, result.edition_id)
            != (setup.organization_id, setup.edition_id)
            or result.previous_release_id != release.release_id
            or result.predecessor_demand_id != original.demand_id
            or result.predecessor_commitment_id != original.commitment_id
            or (result.work.requirement_id, result.work.binding_id)
            != (original.requirement_id, original.binding_id)
            or result.work.requirement_revision_id == original.requirement_revision_id
            or result.work.demand_id in {row.demand_id for row in staffing.work}
            or result.work.commitment_id in {row.commitment_id for row in staffing.work}
            or any(
                type(value) is not int or value < 1
                for value in (
                    result.work.demand_version,
                    result.work.commitment_version,
                )
            )
            or any(
                isinstance(value, UUID) and not value.int
                for value in (*values.values(), *asdict(result.work).values())
            )
            or len(result.role_assignment_ids) != 9
            or len(set(result.role_assignment_ids)) != 9
            or len(result.notice_ids) != 3
            or len(set(result.notice_ids)) != 3
            or any(
                not value.int
                for value in (*result.role_assignment_ids, *result.notice_ids)
            )
            or len(
                {
                    result.release_id,
                    result.previous_release_id,
                    result.approval_id,
                    release.approval_id,
                }
            )
            != 4
            or type(result.pointer_version) is not int
            or result.pointer_version != 2
            or type(result.source_digest) is not str
            or re.fullmatch(r"[0-9a-f]{64}", result.source_digest) is None
            or result.source_digest == release.source_digest
        )
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ProgrammeChangeScenarioError("synthetic_change_result_invalid") from None
    else:
        return result


def change_from_document(document, *, setup, staffing, release):
    """Decode the bounded closed original lineage without consulting owner state."""
    return _decode(document, setup=setup, staffing=staffing, release=release)


def prepare_change_scenario(
    setup, proposal, review, items, planning, physical, staffing, release
):
    """Use original real people and owner boundaries; do not renew the fixture lease."""
    require_programme_runtime_environment()
    documents = json.loads(
        json.dumps(
            dict(
                zip(
                    SOURCE_KEYS,
                    map(
                        asdict,
                        (
                            setup,
                            proposal,
                            review,
                            items,
                            planning,
                            physical,
                            staffing,
                            release,
                        ),
                    ),
                    strict=True,
                )
            ),
            default=str,
        )
    )
    setup, proposal, review, items, planning, physical, staffing, release = (
        change_sources(documents)
    )
    from tests.rehearsals.programme_runtime import (  # noqa: PLC0415
        build_candidate_application,
    )

    build_candidate_application()
    from maru.scheduling.change_catalogs import ChangeRecipientPurpose  # noqa: PLC0415
    from maru.scheduling.change_inputs import ChangeRecipientSelection  # noqa: PLC0415
    from tests.rehearsals.programme_notice_preparation import (  # noqa: PLC0415
        approve_notice_roles,
        prepare_review_handoff_ack,
    )
    from tests.rehearsals.programme_release_outputs import (  # noqa: PLC0415
        verify_public_output,
    )
    from tests.rehearsals.programme_release_preparation import _require  # noqa: PLC0415
    from tests.rehearsals.programme_successor_release import (  # noqa: PLC0415
        republish_after_work_change,
        verify_successor_operator_output,
    )
    from tests.rehearsals.programme_successor_work import (  # noqa: PLC0415
        _own_work,
        prepare_successor_work,
    )

    grants = approve_notice_roles(setup, planning, physical, release)
    work = prepare_successor_work(setup, items, planning, staffing, release)
    approval, publication, digest = republish_after_work_change(
        setup, planning, release
    )
    own_before = _own_work(setup, staffing.volunteer)
    notices = tuple(
        prepare_review_handoff_ack(
            setup, planning, release.reviewer, person, selection, publication
        )
        for person, selection in (
            (
                items.ceremony_host,
                ChangeRecipientSelection(
                    ChangeRecipientPurpose.HOST, items.ceremony.host_id
                ),
            ),
            (
                staffing.volunteer,
                ChangeRecipientSelection(
                    ChangeRecipientPurpose.WORK, work.commitment_id
                ),
            ),
            (
                physical.reviewer,
                ChangeRecipientSelection(
                    ChangeRecipientPurpose.ROOM,
                    planning.room_ids[0],
                    physical.reviewer.account_id,
                ),
            ),
        )
    )
    _require(
        _own_work(setup, staffing.volunteer) == own_before,
        "notice_mutated_retained_work",
    )
    result = ProgrammeChangeScenario(
        setup.organization_id,
        setup.edition_id,
        release.release_id,
        staffing.work[0].demand_id,
        staffing.work[0].commitment_id,
        work,
        approval,
        publication,
        digest,
        2,
        grants,
        notices,
    )
    verify_public_output(setup, items, planning, result)
    verify_successor_operator_output(setup, planning, staffing, result)
    return change_from_document(
        json.loads(json.dumps(asdict(result), default=str)),
        setup=setup,
        staffing=staffing,
        release=release,
    )


def _read_input():
    raw = sys.stdin.read(65_537)
    if len(raw) > 65_536:
        raise ValueError
    return change_sources(json.loads(raw))


def _main():
    require_programme_runtime_environment()
    try:
        result = prepare_change_scenario(*_read_input())
    except Exception:  # noqa: BLE001 - fixed private child boundary
        raise SystemExit(2) from None
    sys.stdout.write(json.dumps(asdict(result), default=str))
    sys.stdout.flush()


if __name__ == "__main__":
    _main()
