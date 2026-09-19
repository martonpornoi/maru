"""Host-only call-to-private-item composition; uncollected/unexecuted while deferred."""

from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from tests.rehearsals.programme_runner import isolated_programme_application
from tests.rehearsals.programme_runtime_environment import (
    require_programme_rehearsal_request,
)

require_programme_rehearsal_request()
pytestmark = pytest.mark.integration


def test_native_real_proposal_items_planning_and_independent_physical_approval(
    monkeypatch,
):
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL_RUN_ID", uuid4().hex)
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL_LEASE_SECONDS", "3600")
    with isolated_programme_application(
        setup_mode="new_foundation", with_scanner=True
    ) as fixture:
        result = fixture.prepare_proposal()
        assert result.organization_id == fixture.scenario.organization_id
        assert result.lead.account_id != result.collaborator.account_id
        # Independent read under genuine runtime login; no SQL/factory writes.
        with psycopg.connect(
            fixture.runtime.database_url, connect_timeout=5
        ) as connection:
            assert connection.execute(
                "SELECT session_user, current_user"
            ).fetchone() == ("maru_runtime", "maru_runtime")
            assert connection.execute(
                "SELECT state, submitted_revision_id "
                "FROM public.applications_programmeproposal "
                "WHERE id = %s AND organization_id = %s AND edition_id = %s",
                (result.proposal_id, result.organization_id, result.edition_id),
            ).fetchone() == ("submitted", result.revision_id)
            assert connection.execute(
                "SELECT count(*) FROM public.applications_programmefileintake "
                "WHERE proposal_id = %s",
                (result.proposal_id,),
            ).fetchone() == (1,)
        assert result.lead.password not in repr(result)
        reviewed = fixture.prepare_review(result)
        with psycopg.connect(
            fixture.runtime.database_url, connect_timeout=5
        ) as connection:
            assert connection.execute(
                "SELECT revision_id, decision_id, programme_item_id "
                "FROM public.applications_programmeacceptedtransition "
                "WHERE id = %s AND organization_id = %s AND edition_id = %s",
                (reviewed.transition_id, reviewed.organization_id, reviewed.edition_id),
            ).fetchone() == (result.revision_id, reviewed.decision_id, reviewed.item_id)
            assert connection.execute(
                "SELECT count(*) FROM public.programme_programmereadinessrequirement "
                "WHERE item_id = %s",
                (reviewed.item_id,),
            ).fetchone() == (7,)
            assert connection.execute(
                "SELECT count(*) FROM public.applications_programmeacceptedtransition "
                "WHERE revision_id = %s",
                (result.revision_id,),
            ).fetchone() == (1,)
        items = fixture.prepare_items(result, reviewed)
        with psycopg.connect(
            fixture.runtime.database_url, connect_timeout=5
        ) as connection:
            for item, kind in (
                (items.accepted, "accepted_proposal"),
                (items.ceremony, "ceremony"),
            ):
                assert connection.execute(
                    "SELECT kind, aggregate_version "
                    "FROM public.programme_programmeitem "
                    "WHERE id = %s AND organization_id = %s AND edition_id = %s",
                    (item.item_id, items.organization_id, items.edition_id),
                ).fetchone() == (kind, item.version)
                assert connection.execute(
                    "SELECT state, version, availability_state "
                    "FROM public.programme_programmehostrelationship WHERE id = %s",
                    (item.host_id,),
                ).fetchone() == ("confirmed", item.host_version, "shared")
            assert connection.execute(
                "SELECT count(*) FROM public.applications_programmeacceptedtransition "
                "WHERE programme_item_id = %s",
                (items.ceremony.item_id,),
            ).fetchone() == (0,)
        planning = fixture.prepare_planning(result, reviewed, items)
        with psycopg.connect(
            fixture.runtime.database_url, connect_timeout=5
        ) as connection:
            assert connection.execute(
                "SELECT aggregate_version, lifecycle "
                "FROM public.scheduling_schedulingcandidate "
                "WHERE id = %s AND organization_id = %s AND edition_id = %s",
                (planning.candidate_id, planning.organization_id, planning.edition_id),
            ).fetchone() == (planning.candidate_version, "draft")
            assert connection.execute(
                "SELECT placement_count "
                "FROM public.scheduling_schedulingcandidaterevision "
                "WHERE id = %s AND candidate_id = %s AND sequence = %s",
                (
                    planning.candidate_revision_id,
                    planning.candidate_id,
                    planning.candidate_version,
                ),
            ).fetchone() == (3,)
            assert connection.execute(
                "SELECT placement_count "
                "FROM public.scheduling_schedulingcandidaterevision "
                "WHERE id = %s AND candidate_id = %s",
                (planning.conflicted_revision_id, planning.conflicted_candidate_id),
            ).fetchone() == (3,)
            for table in (
                "scheduling_schedulingreservationintent",
                "scheduling_schedulingreleaseapproval",
                "scheduling_schedulingrelease",
                "venues_venuebooking",
            ):
                assert connection.execute(
                    sql.SQL(
                        "SELECT count(*) FROM public.{} "
                        "WHERE organization_id = %s AND edition_id = %s"
                    ).format(sql.Identifier(table)),
                    (planning.organization_id, planning.edition_id),
                ).fetchone() == (0,)
        physical = fixture.prepare_physical(result, reviewed, items, planning)
        with psycopg.connect(
            fixture.runtime.database_url, connect_timeout=5
        ) as connection:
            for booking, version in zip(
                physical.booking_ids, physical.booking_versions, strict=True
            ):
                assert connection.execute(
                    "SELECT aggregate_version, review_state, publication_state, "
                    "approved_by_id FROM public.venues_venuebooking "
                    "WHERE id = %s AND organization_id = %s AND edition_id = %s",
                    (booking, physical.organization_id, physical.edition_id),
                ).fetchone() == (
                    version,
                    "approved",
                    "unpublished",
                    physical.reviewer.account_id,
                )
            for placement, blocked, accepted, digest in zip(
                physical.placement_ids,
                physical.blocked_decision_ids,
                physical.fit_decision_ids,
                physical.fit_source_digests,
                strict=True,
            ):
                assert connection.execute(
                    "SELECT id, sequence, state, source_digest, actor_id "
                    "FROM public.programme_programmeplacementdecision "
                    "WHERE placement_id = %s AND organization_id = %s "
                    "AND edition_id = %s AND kind = 'accessibility_fit' "
                    "ORDER BY sequence",
                    (placement, physical.organization_id, physical.edition_id),
                ).fetchall() == [
                    (blocked, 1, "blocked", digest, planning.planner.account_id),
                    (accepted, 2, "satisfied", digest, planning.planner.account_id),
                ]
            for table in (
                "scheduling_schedulingreleaseapproval",
                "scheduling_schedulingrelease",
            ):
                assert connection.execute(
                    sql.SQL(
                        "SELECT count(*) FROM public.{} "
                        "WHERE organization_id = %s AND edition_id = %s"
                    ).format(sql.Identifier(table)),
                    (physical.organization_id, physical.edition_id),
                ).fetchone() == (0,)
        staffing = fixture.prepare_staffing(result, reviewed, items, planning, physical)
        with psycopg.connect(
            fixture.runtime.database_url, connect_timeout=5
        ) as connection:
            assert connection.execute(
                "SELECT r.author_id, r.approver_id, d.actor_id, "
                "d.action, d.template_id "
                "FROM public.workforce_programmestarterrequest r "
                "JOIN public.workforce_programmestarterdecision d "
                "ON d.request_id = r.id "
                "WHERE r.id = %s AND r.organization_id = %s AND r.edition_id = %s",
                (
                    staffing.starter_request_id,
                    staffing.organization_id,
                    staffing.edition_id,
                ),
            ).fetchone() == (
                fixture.scenario.controllers[0].account_id,
                fixture.scenario.controllers[1].account_id,
                fixture.scenario.controllers[1].account_id,
                "approve",
                staffing.template_id,
            )
            assert connection.execute(
                "SELECT account_id, position_id, status, participation_capacity_id "
                "FROM public.workforce_positionassignment "
                "WHERE id = %s AND organization_id = %s AND edition_id = %s",
                (staffing.assignment_id, staffing.organization_id, staffing.edition_id),
            ).fetchone() == (
                staffing.volunteer.account_id,
                staffing.position_id,
                "active",
                None,
            )
            for work in staffing.work:
                assert connection.execute(
                    "SELECT status, command_version, required_headcount "
                    "FROM public.workforce_shiftdemand "
                    "WHERE id = %s AND organization_id = %s AND edition_id = %s",
                    (work.demand_id, staffing.organization_id, staffing.edition_id),
                ).fetchone() == ("locked", work.demand_version, 1)
                assert connection.execute(
                    "SELECT account_id, demand_id, status, "
                    "command_version, confirmed_by_id "
                    "FROM public.workforce_shiftcommitment "
                    "WHERE id = %s AND organization_id = %s AND edition_id = %s",
                    (work.commitment_id, staffing.organization_id, staffing.edition_id),
                ).fetchone() == (
                    staffing.volunteer.account_id,
                    work.demand_id,
                    "confirmed",
                    work.commitment_version,
                    planning.planner.account_id,
                )
            for table in (
                "participation_participation",
                "participation_participationcapacity",
                "scheduling_schedulingreleaseapproval",
                "scheduling_schedulingrelease",
            ):
                assert connection.execute(
                    sql.SQL("SELECT count(*) FROM public.{}").format(
                        sql.Identifier(table)
                    )
                ).fetchone() == (0,)
        released = fixture.prepare_release(
            result, reviewed, items, planning, physical, staffing
        )
        with psycopg.connect(
            fixture.runtime.database_url, connect_timeout=5
        ) as connection:
            assert connection.execute(
                "SELECT a.actor_id, a.candidate_revision_id, a.source_snapshot_digest, "
                "a.placement_count, r.actor_id, r.previous_release_id, "
                "r.pointer_version "
                "FROM public.scheduling_schedulingrelease r "
                "JOIN public.scheduling_schedulingreleaseapproval a "
                "ON a.id = r.approval_id "
                "WHERE r.id = %s AND a.id = %s "
                "AND r.organization_id = %s AND r.edition_id = %s",
                (
                    released.release_id,
                    released.approval_id,
                    released.organization_id,
                    released.edition_id,
                ),
            ).fetchone() == (
                released.reviewer.account_id,
                planning.candidate_revision_id,
                released.source_digest,
                3,
                planning.planner.account_id,
                None,
                1,
            )
            assert connection.execute(
                "SELECT active_release_id, version "
                "FROM public.scheduling_schedulingreleasepointer "
                "WHERE organization_id = %s AND edition_id = %s",
                (released.organization_id, released.edition_id),
            ).fetchone() == (released.release_id, 1)
            assert connection.execute(
                "SELECT count(*) FROM public.scheduling_schedulingreleaseartifact "
                "WHERE release_id = %s AND organization_id = %s AND edition_id = %s",
                (released.release_id, released.organization_id, released.edition_id),
            ).fetchone() == (1,)
            for work in staffing.work:
                assert connection.execute(
                    "SELECT status, command_version "
                    "FROM public.workforce_shiftcommitment "
                    "WHERE id = %s AND organization_id = %s AND edition_id = %s",
                    (work.commitment_id, released.organization_id, released.edition_id),
                ).fetchone() == ("confirmed", work.commitment_version)
            for table in (
                "participation_participation",
                "participation_participationcapacity",
            ):
                assert connection.execute(
                    sql.SQL("SELECT count(*) FROM public.{}").format(
                        sql.Identifier(table)
                    )
                ).fetchone() == (0,)
        changed = fixture.prepare_change(
            result, reviewed, items, planning, physical, staffing, released
        )
        _assert_native_change(
            fixture, changed, planning, staffing, items, physical, released
        )
    # This proves no actual HTTP/browser/print journey, real venue fitness,
    # representative human, complete cross-tenant inventory or P09-P12 acceptance.


def _assert_native_change(
    fixture, changed, planning, staffing, items, physical, released
):
    with psycopg.connect(fixture.runtime.database_url, connect_timeout=5) as connection:
        scope = (changed.organization_id, changed.edition_id)
        assert connection.execute(
            "SELECT active_release_id, version "
            "FROM public.scheduling_schedulingreleasepointer "
            "WHERE organization_id = %s AND edition_id = %s",
            scope,
        ).fetchone() == (changed.release_id, 2)
        assert connection.execute(
            "SELECT previous_release_id, approval_id, actor_id "
            "FROM public.scheduling_schedulingrelease "
            "WHERE id = %s AND organization_id = %s AND edition_id = %s",
            (changed.release_id, *scope),
        ).fetchone() == (
            released.release_id,
            changed.approval_id,
            planning.planner.account_id,
        )
        assert connection.execute(
            "SELECT status FROM public.workforce_shiftdemand "
            "WHERE id = %s AND organization_id = %s AND edition_id = %s",
            (changed.predecessor_demand_id, *scope),
        ).fetchone() == ("cancelled",)
        assert connection.execute(
            "SELECT status, removal_kind, command_version "
            "FROM public.workforce_shiftcommitment "
            "WHERE id = %s AND organization_id = %s AND edition_id = %s",
            (changed.predecessor_commitment_id, *scope),
        ).fetchone() == (
            "removed",
            "cancelled",
            staffing.work[0].commitment_version + 1,
        )
        for work in (changed.work, *staffing.work[1:]):
            assert connection.execute(
                "SELECT account_id, demand_id, status, command_version "
                "FROM public.workforce_shiftcommitment "
                "WHERE id = %s AND organization_id = %s AND edition_id = %s",
                (work.commitment_id, *scope),
            ).fetchone() == (
                staffing.volunteer.account_id,
                work.demand_id,
                "confirmed",
                work.commitment_version,
            )
        recipients = (
            items.ceremony_host.account_id,
            staffing.volunteer.account_id,
            physical.reviewer.account_id,
        )
        for notice, recipient, purpose in zip(
            changed.notice_ids, recipients, ("host", "work", "room"), strict=True
        ):
            assert connection.execute(
                "SELECT actor_id, recipient_id, recipient_purpose, "
                "pointer_version, source_state "
                "FROM public.scheduling_schedulingchangenotice "
                "WHERE id = %s AND organization_id = %s AND edition_id = %s",
                (notice, *scope),
            ).fetchone() == (
                planning.planner.account_id,
                recipient,
                purpose,
                2,
                "comparison_suppressed",
            )
            assert connection.execute(
                "SELECT action, actor_id, sequence "
                "FROM public.scheduling_schedulingchangenoticeevidence "
                "WHERE notice_id = %s AND organization_id = %s "
                "AND edition_id = %s ORDER BY sequence",
                (notice, *scope),
            ).fetchall() == [
                ("approve", released.reviewer.account_id, 2),
                ("handoff", planning.planner.account_id, 3),
                ("acknowledge", recipient, 4),
            ]
        for table in (
            "participation_participation",
            "participation_participationcapacity",
        ):
            assert connection.execute(
                sql.SQL("SELECT count(*) FROM public.{}").format(sql.Identifier(table))
            ).fetchone() == (0,)
