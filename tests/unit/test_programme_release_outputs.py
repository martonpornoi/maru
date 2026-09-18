"""Mocked owner reads with actual typed audience serializers; no database evidence."""

import json
from dataclasses import replace
from unittest.mock import create_autospec
from uuid import uuid4

import pytest

from maru.scheduling import (
    operator_output_queries,
    output_queries,
    personal_output_queries,
)
from maru.scheduling.operator_scope import OperatorScopeKind
from maru.scheduling.release_queries import ProgrammeReleaseState
from tests.rehearsals import programme_release_outputs as outputs
from tests.rehearsals.programme_release_preparation import (
    ProgrammeReleasePreparationError,
)
from tests.unit.test_personal_timetable_rendering import (
    personal as personal,  # noqa: PLC0414
)
from tests.unit.test_programme_operator_rendering import (
    full_sheet as full_sheet,  # noqa: PLC0414
)
from tests.unit.test_programme_operator_rendering import sheet as sheet  # noqa: PLC0414
from tests.unit.test_programme_physical_preparation import _snapshot
from tests.unit.test_programme_release_scenario import _result, _sources
from tests.unit.test_programme_review_scenario import _authentication
from tests.unit.test_scheduling_output_rendering import (
    snapshot as snapshot,  # noqa: PLC0414
)


@pytest.mark.parametrize("fault", [None, "source", "membership", "copy"])
def test_public_owner_and_real_formats_share_exact_released_membership(
    monkeypatch, snapshot, fault
):
    setup, _, _, items, planning, _, _ = _sources()
    released = _result(setup, planning)
    entries = tuple(
        replace(
            snapshot.entries[0],
            occurrence_id=occurrence,
            copy=replace(
                snapshot.entries[0].copy,
                rendition_id=item.public_rendition_id,
            ),
        )
        for occurrence, item in zip(
            planning.occurrence_ids,
            (items.ceremony, items.accepted, items.accepted),
            strict=True,
        )
    )
    snapshot = replace(snapshot, release_id=released.release_id, entries=entries)
    if fault == "source":
        snapshot = replace(snapshot, release_id=uuid4())
    elif fault == "membership":
        snapshot = replace(snapshot, entries=entries[:-1])
    elif fault == "copy":
        snapshot = replace(
            snapshot,
            entries=(
                replace(
                    entries[0], copy=replace(entries[0].copy, rendition_id=uuid4())
                ),
                *entries[1:],
            ),
        )
    read = create_autospec(
        output_queries.load_public_programme_timetable, return_value=snapshot
    )
    monkeypatch.setattr(output_queries, "load_public_programme_timetable", read)
    if fault:
        with pytest.raises(ProgrammeReleasePreparationError):
            outputs.verify_public_output(setup, items, planning, released)
    else:
        outputs.verify_public_output(setup, items, planning, released)
    assert read.call_args.kwargs == {
        "organization_id": setup.organization_id,
        "edition_id": setup.edition_id,
    }


@pytest.mark.parametrize("fault", [None, "host", "private", "work", "time", "missing"])
def test_personal_outputs_use_actual_people_and_never_invent_volunteer_hosting(
    monkeypatch, personal, fault
):
    _authentication(monkeypatch)
    setup, proposal, _, items, planning, _, staffing = _sources()
    released = _result(setup, planning)
    geometry = _snapshot(planning, items)
    monkeypatch.setattr(outputs, "_snapshot", lambda *_a: geometry)
    base = replace(
        personal, organization_id=setup.organization_id, edition_id=setup.edition_id
    )
    by_person = {}
    for person, item, placements in (
        (items.ceremony_host, items.ceremony, geometry.placements[:1]),
        (proposal.lead, items.accepted, geometry.placements[1:]),
    ):
        reference = replace(
            base.hosting.reference,
            release_id=released.release_id,
            purposes=(
                replace(
                    base.hosting.reference.purposes[0],
                    host_id=item.host_id,
                    item_id=item.item_id,
                ),
            ),
            presences=tuple(
                replace(
                    base.hosting.reference.presences[0],
                    host_id=item.host_id,
                    occurrence_id=row.occurrence_id,
                    placement_id=row.id,
                )
                for row in placements
            ),
        )
        by_person[person.account_id] = replace(
            base,
            actor_id=person.account_id,
            hosting=replace(base.hosting, reference=reference),
            shifts=(),
        )
    shifts = tuple(
        replace(
            base.shifts[0],
            commitment_id=work.commitment_id,
            version=work.commitment_version,
            starts_at=row.envelope.setup_starts_at,
            ends_at=row.envelope.teardown_ends_at,
            rest_ends_at=row.envelope.teardown_ends_at,
            instructions=replace(
                base.shifts[0].instructions,
                demand_id=work.demand_id,
                version=work.demand_version,
                status="locked",
            ),
        )
        for work, row in zip(staffing.work, geometry.placements, strict=True)
    )
    volunteer = replace(
        base,
        actor_id=staffing.volunteer.account_id,
        shifts=shifts,
        hosting=replace(
            base.hosting,
            rooms=(),
            reference=replace(
                base.hosting.reference,
                state=None,
                pointer_version=None,
                release_id=None,
                published_at=None,
                purposes=(),
                presences=(),
            ),
        ),
    )
    if fault == "host":
        host = by_person[proposal.lead.account_id]
        by_person[proposal.lead.account_id] = replace(
            host,
            hosting=replace(
                host.hosting,
                reference=replace(host.hosting.reference, release_id=uuid4()),
            ),
        )
    elif fault == "private":
        volunteer = replace(
            volunteer,
            hosting=replace(
                volunteer.hosting,
                reference=replace(
                    volunteer.hosting.reference, release_id=released.release_id
                ),
            ),
        )
    elif fault == "work":
        volunteer = replace(
            volunteer, shifts=(replace(shifts[0], version=99), *shifts[1:])
        )
    elif fault == "time":
        volunteer = replace(
            volunteer,
            shifts=(replace(shifts[0], starts_at=shifts[0].ends_at), *shifts[1:]),
        )
    elif fault == "missing":
        volunteer = replace(volunteer, shifts=shifts[:-1])
    by_person[staffing.volunteer.account_id] = volunteer
    read = create_autospec(
        personal_output_queries.load_personal_timetable,
        side_effect=lambda **kw: by_person[kw["actor_id"]],
    )
    monkeypatch.setattr(personal_output_queries, "load_personal_timetable", read)
    if fault:
        with pytest.raises(ProgrammeReleasePreparationError):
            outputs.verify_personal_outputs(
                setup, proposal, items, planning, staffing, released
            )
    else:
        outputs.verify_personal_outputs(
            setup, proposal, items, planning, staffing, released
        )
        assert [call.kwargs["actor_id"] for call in read.call_args_list] == [
            items.ceremony_host.account_id,
            proposal.lead.account_id,
            staffing.volunteer.account_id,
        ]
        assert all(
            set(call.kwargs)
            == {"actor_id", "organization_id", "edition_id", "correlation_id"}
            for call in read.call_args_list
        )


@pytest.mark.parametrize("fault", [None, "source", "membership", "layer", "work"])
def test_operator_purposes_keep_exact_membership_and_linked_work(
    monkeypatch, full_sheet, fault
):
    _authentication(monkeypatch)
    setup, _, _, items, planning, _, staffing = _sources()
    released = _result(setup, planning)
    geometry = _snapshot(planning, items)
    monkeypatch.setattr(outputs, "_snapshot", lambda *_a: geometry)
    originals = dict(zip(planning.occurrence_ids, staffing.work, strict=True))

    def source(request, *, layers):
        selected = tuple(
            row
            for row in geometry.placements
            if request.kind != OperatorScopeKind.ROOM
            or row.space_id == request.target_id
        )
        entries = tuple(
            replace(
                full_sheet.entries[0],
                delivery=None,
                placement=replace(
                    full_sheet.entries[0].placement,
                    occurrence_id=row.occurrence_id,
                    placement_id=row.id,
                    space_id=row.space_id,
                ),
                room=replace(full_sheet.entries[0].room, space_id=row.space_id),
            )
            for row in selected
        )
        links = tuple(
            replace(
                full_sheet.staffing.links[0],
                occurrence_id=row.occurrence_id,
                binding_id=originals[row.occurrence_id].binding_id,
                demand_id=originals[row.occurrence_id].demand_id,
                demand_version=originals[row.occurrence_id].demand_version,
                current=True,
            )
            for row in selected
        )
        demands = tuple(
            replace(
                full_sheet.staffing.demands[0],
                demand_id=link.demand_id,
                version=link.demand_version,
                state="locked",
            )
            for link in links
        )
        result = replace(
            full_sheet,
            organization_id=setup.organization_id,
            edition_id=setup.edition_id,
            kind=request.kind,
            target_id=request.target_id,
            layers=layers,
            entries=entries,
            reference=replace(
                full_sheet.reference,
                release_id=released.release_id,
                occurrences=tuple(row.placement for row in entries),
            ),
            staffing=replace(full_sheet.staffing, links=links, demands=demands),
        )
        if fault == "source":
            result = replace(
                result,
                reference=replace(
                    result.reference, state=ProgrammeReleaseState.INVALIDATED
                ),
            )
        elif fault == "membership":
            result = replace(result, entries=entries[:-1])
        elif fault == "layer":
            result = replace(
                result,
                entries=(
                    replace(entries[0], delivery=full_sheet.entries[0].delivery),
                    *entries[1:],
                ),
            )
        elif fault == "work":
            result = replace(
                result,
                staffing=replace(
                    result.staffing,
                    links=(replace(links[0], current=False), *links[1:]),
                ),
            )
        return result

    read = create_autospec(
        operator_output_queries.load_operator_run_sheet, side_effect=source
    )
    monkeypatch.setattr(operator_output_queries, "load_operator_run_sheet", read)
    if fault:
        with pytest.raises(ProgrammeReleasePreparationError):
            outputs.verify_operator_outputs(setup, planning, staffing, released)
    else:
        outputs.verify_operator_outputs(setup, planning, staffing, released)
        assert [call.args[0].target_id for call in read.call_args_list] == [
            setup.edition_id,
            setup.department_id,
            *planning.room_ids,
        ]
        assert all(
            call.kwargs == {"layers": frozenset({"staffing"})}
            for call in read.call_args_list
        )


def test_format_mismatch_is_not_hidden_by_successful_owner_read():
    sources = _sources()
    released = _result(sources[0], sources[4])
    with pytest.raises(ProgrammeReleasePreparationError, match="format_changed"):
        outputs._formats(
            None,
            released,
            lambda _: json.dumps(
                {"release_id": str(released.release_id), "pointer_version": 1}
            ),
            lambda _: b"wrong calendar",
        )
