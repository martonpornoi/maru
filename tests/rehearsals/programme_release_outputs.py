"""Same-release owner/format composition, not browser, print-dialog or offline proof."""

import json
from uuid import uuid4

from tests.rehearsals.programme_planning_scenario import _snapshot
from tests.rehearsals.programme_release_preparation import _require


def _available(source, release):
    _require(
        source.state == "available"
        and source.release_id == release.release_id
        and source.pointer_version == release.pointer_version,
        "release_output_source_changed",
    )


def _formats(snapshot, release, render_json, render_calendar, *, personal=False):
    document = json.loads(render_json(snapshot))
    source = document["hosting"] if personal else document
    _require(
        source["release_id"] == str(release.release_id)
        and source["pointer_version"] == release.pointer_version
        and f"X-MARU-RELEASE-ID:{release.release_id}".encode()
        in render_calendar(snapshot),
        "release_output_format_changed",
    )


def verify_public_output(setup, items, planning, release):
    """Resolve anonymous approved copy, not planner data or a latest-copy fallback."""
    from maru.scheduling.output_queries import (  # noqa: PLC0415
        load_public_programme_timetable,
    )
    from maru.scheduling.output_rendering import (  # noqa: PLC0415
        render_public_timetable_calendar,
        render_public_timetable_json,
    )

    snapshot = load_public_programme_timetable(
        organization_id=setup.organization_id,
        edition_id=setup.edition_id,
    )
    _available(snapshot, release)
    expected = dict(
        zip(
            planning.occurrence_ids,
            (
                items.ceremony.public_rendition_id,
                items.accepted.public_rendition_id,
                items.accepted.public_rendition_id,
            ),
            strict=True,
        )
    )
    _require(
        len(snapshot.entries) == 3
        and {row.occurrence_id: row.copy.rendition_id for row in snapshot.entries}
        == expected,
        "release_public_membership_changed",
    )
    _formats(
        snapshot,
        release,
        render_public_timetable_json,
        render_public_timetable_calendar,
    )


def verify_personal_outputs(setup, proposal, items, planning, staffing, release):
    """Keep own published hosting and retained work separate without Participation."""
    from maru.scheduling.personal_output_queries import (  # noqa: PLC0415
        load_personal_timetable,
    )
    from maru.scheduling.personal_output_rendering import (  # noqa: PLC0415
        render_personal_timetable_calendar,
        render_personal_timetable_json,
    )

    def own(person):
        return load_personal_timetable(
            actor_id=person.authenticate().id,
            organization_id=setup.organization_id,
            edition_id=setup.edition_id,
            correlation_id=uuid4(),
        )

    for person, occurrences in (
        (items.ceremony_host, planning.occurrence_ids[:1]),
        (proposal.lead, planning.occurrence_ids[1:]),
    ):
        snapshot = own(person)
        _require(snapshot.hosting is not None, "release_host_layer_missing")
        reference = snapshot.hosting.reference
        _available(reference, release)
        _require(
            snapshot.actor_id == person.account_id
            and snapshot.shifts == ()
            and len(reference.presences) == len(occurrences)
            and {row.occurrence_id for row in reference.presences} == set(occurrences),
            "release_host_membership_changed",
        )
        _formats(
            snapshot,
            release,
            render_personal_timetable_json,
            render_personal_timetable_calendar,
            personal=True,
        )
    snapshot = own(staffing.volunteer)
    _require(
        snapshot.actor_id == staffing.volunteer.account_id
        and snapshot.hosting is not None
        and snapshot.hosting.reference.state is None
        and snapshot.hosting.reference.release_id is None
        and not snapshot.hosting.reference.purposes
        and not snapshot.hosting.reference.presences,
        "release_unrelated_host_disclosed",
    )
    work = {row.commitment_id: row for row in staffing.work}
    geometry = _snapshot(setup, planning.planner, planning.candidate_id)
    envelopes = {row.id: row.envelope for row in geometry.placements}
    expected = {
        row.commitment_id: envelopes[placement]
        for row, placement in zip(staffing.work, planning.placement_ids, strict=True)
    }
    _require(
        snapshot.shifts is not None
        and len(snapshot.shifts) == 3
        and {row.commitment_id for row in snapshot.shifts} == set(work),
        "release_volunteer_membership_changed",
    )
    for row in snapshot.shifts:
        original, envelope = work[row.commitment_id], expected[row.commitment_id]
        _require(
            row.version == original.commitment_version
            and row.status == "confirmed"
            and row.instructions.demand_id == original.demand_id
            and row.instructions.version == original.demand_version
            and row.starts_at == envelope.setup_starts_at
            and row.ends_at == envelope.teardown_ends_at,
            "release_rewrote_retained_work",
        )
    document = json.loads(render_personal_timetable_json(snapshot))
    _require(
        document["hosting"]["release_id"] is None
        and len(document["shifts"]) == 3
        and str(release.release_id).encode()
        not in render_personal_timetable_calendar(snapshot),
        "release_volunteer_format_changed",
    )


def verify_operator_outputs(setup, planning, staffing, release):
    """Read each exact purpose independently; edition permission is not public data."""
    from maru.scheduling.operator_output_queries import (  # noqa: PLC0415
        load_operator_run_sheet,
    )
    from maru.scheduling.operator_output_rendering import (  # noqa: PLC0415
        render_operator_run_sheet_calendar,
        render_operator_run_sheet_json,
    )
    from maru.scheduling.operator_scope import (  # noqa: PLC0415
        OperatorReadRequest,
        OperatorScopeKind,
    )

    geometry = _snapshot(setup, planning.planner, planning.candidate_id)
    work = dict(zip(planning.occurrence_ids, staffing.work, strict=True))
    for kind, target in (
        (OperatorScopeKind.EDITION, setup.edition_id),
        (OperatorScopeKind.DEPARTMENT, setup.department_id),
        *((OperatorScopeKind.ROOM, room) for room in planning.room_ids),
    ):
        request = OperatorReadRequest(
            planning.planner.authenticate().id,
            setup.organization_id,
            setup.edition_id,
            uuid4(),
            kind,
            target,
        )
        snapshot = load_operator_run_sheet(request, layers=frozenset({"staffing"}))
        _available(snapshot.reference, release)
        expected = {
            row.occurrence_id
            for row in geometry.placements
            if kind != OperatorScopeKind.ROOM or row.space_id == target
        }
        _require(
            snapshot.kind == kind
            and snapshot.target_id == target
            and len(snapshot.entries) == len(expected)
            and {row.placement.occurrence_id for row in snapshot.entries} == expected
            and all(row.delivery is None for row in snapshot.entries)
            and snapshot.staffing is not None
            and snapshot.staffing.adopted,
            "release_operator_membership_changed",
        )
        layer = snapshot.staffing
        _require(
            len(layer.links) == len(expected)
            and {row.occurrence_id for row in layer.links} == expected
            and all(
                row.current
                and row.binding_id == work[row.occurrence_id].binding_id
                and row.demand_id == work[row.occurrence_id].demand_id
                and row.demand_version == work[row.occurrence_id].demand_version
                for row in layer.links
            )
            and len(layer.demands) == len(expected)
            and {row.demand_id for row in layer.demands}
            == {work[occurrence].demand_id for occurrence in expected}
            and all(row.state == "locked" for row in layer.demands),
            "release_operator_work_changed",
        )
        _formats(
            snapshot,
            release,
            render_operator_run_sheet_json,
            render_operator_run_sheet_calendar,
        )


def verify_release_outputs(setup, proposal, items, planning, staffing, release):
    """Exercise current owner queries and actual JSON/calendar serializers only."""
    verify_public_output(setup, items, planning, release)
    verify_personal_outputs(setup, proposal, items, planning, staffing, release)
    verify_operator_outputs(setup, planning, staffing, release)
