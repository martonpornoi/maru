"""Closed isolated-rehearsal candidate data, never runtime profile registration.

Importing this module performs no database, settings, URL or authority changes.
This is preparation for #108/#109, not an executable or accepted Programme profile.
Every pin is literal so later owner-catalog growth cannot silently widen it.
"""

from enum import StrEnum
from typing import TYPE_CHECKING, cast

from maru.events.adoption import AdoptionProfile, EffectRoute

if TYPE_CHECKING:
    from maru.events.adoption import AdoptionProfileCode


class RehearsalProfileCode(StrEnum):
    """Name only the isolated candidate; never replace the production enum."""

    PROGRAMME_OPERATIONS = "programme_operations"


MODULES = (
    "audit",
    "authorization",
    "effects",
    "events",
    "identity",
    "organizations",
    "privacy",
    "applications",
    "programme",
    "scheduling",
    "venues",
    "workforce",
)

# Preserve the complete current Workforce/foundation journey, not a copied
# full-convention profile whose attendee or other product behavior could leak in.
CAPABILITIES = (
    "audit.view_security",
    "authorization.delegate",
    "authorization.grant_direct",
    "authorization.manage_roles",
    "authorization.revoke",
    "effects.replay",
    "events.change_profile",
    "events.create",
    "events.transition",
    "events.view_basic",
    "identity.manage_restrictions",
    "organizations.change_profile",
    "organizations.change_series",
    "organizations.create_series",
    "organizations.manage_representation",
    "organizations.view_basic",
    "privacy.manage_requests",
    "workforce.apply_self",
    "workforce.manage_applications",
    "workforce.manage_assignments",
    "workforce.manage_documents",
    "workforce.manage_self_availability",
    "workforce.manage_self_shifts",
    "workforce.manage_shifts",
    "workforce.manage_structure",
    "workforce.view_availability",
    "workforce.view_self",
    "workforce.view_shifts",
    "workforce.view_structure",
    "workforce.view_operator_staffing",
    "applications.manage_programme_calls",
    "applications.manage_programme_review",
    "applications.review_programme",
    "applications.moderate_programme_review",
    "applications.decide_programme",
    "applications.convert_programme_acceptance",
    "applications.view_programme_decision_self",
    "applications.acknowledge_programme_decision_self",
    "applications.import_programme",
    "applications.dispose_programme_import",
    "applications.recover_programme_department_ownership",
    "applications.view_programme_proposal_self",
    "applications.edit_programme_proposal_self",
    "applications.respond_programme_invitation_self",
    "applications.manage_programme_proposal_self",
    "applications.submit_programme_proposal_self",
    "programme.manage_hosts",
    "programme.manage_staffing",
    "programme.view_staffing",
    "programme.view_scheduling_dependencies",
    "programme.view_operator_copy",
    "programme.view_operator_delivery",
    "programme.view_hosts",
    "programme.view_host_self",
    "programme.respond_host_self",
    "programme.manage_host_availability_self",
    "programme.view_private",
    "programme.manage_items",
    "programme.view_readiness",
    "programme.manage_readiness",
    "programme.view_delivery",
    "programme.manage_delivery",
    "programme.view_discussion",
    "programme.view_public_copy",
    "programme.approve_public_copy",
    "scheduling.view_change_recipients",
    "scheduling.view_change_notices",
    "scheduling.prepare_change_notices",
    "scheduling.review_change_notices",
    "scheduling.handoff_change_notices",
    "scheduling.view_change_self",
    "scheduling.acknowledge_change_self",
    "scheduling.view_operator_output",
    "scheduling.view_host_self",
    "scheduling.view_work_self",
    "scheduling.view_planning",
    "scheduling.view_history",
    "scheduling.view_conflicts",
    "scheduling.manage_service_days",
    "scheduling.manage_occurrences",
    "scheduling.manage_candidates",
    "scheduling.evaluate_candidates",
    "scheduling.acknowledge_warnings",
    "scheduling.manage_reservations",
    "scheduling.acknowledge_release_warnings",
    "scheduling.approve_release",
    "scheduling.publish_release",
    "scheduling.withdraw_release",
    "venues.view_properties",
    "venues.manage_properties",
    "venues.view_workspace",
    "venues.select_for_edition",
    "venues.view_space_schedule",
    "venues.manage_space_schedule",
    "venues.publish_space_schedule",
    "venues.view_scheduling_dependencies",
    "venues.view_operator_wayfinding",
)

SHELL_KINDS = (
    "edition.overview",
    "edition.structure",
    "edition.venues",
    "edition.programme-access",
    "edition.programme-applications",
    "edition.programme-items",
    "edition.programme-notices",
    "edition.programme-operators",
    "edition.programme-release",
    "edition.programme-timetable",
    "my.applications",
    "my.schedule",
    "my.workforce",
    "work.security",
    "work.setup",
    "work.today",
    "work.workforce",
)

CATALOG_ENTRIES = (
    "workforce.position-template.workforce-volunteer@1",
    "workforce.structure-template.marucon-reference@1",
    "authorization.programme_role.edition-coordination@1",
    "authorization.programme_role.intake@1",
    "authorization.programme_role.import-disposal@1",
    "authorization.programme_role.review-setup@1",
    "authorization.programme_role.reviewer@1",
    "authorization.programme_role.moderator@1",
    "authorization.programme_role.decision-maker@1",
    "authorization.programme_role.conversion@1",
    "authorization.programme_role.content@1",
    "authorization.programme_role.delivery@1",
    "authorization.programme_role.hosting@1",
    "authorization.programme_role.staffing@1",
    "authorization.programme_role.workforce@1",
    "authorization.programme_role.coverage-reader@1",
    "authorization.programme_role.planner@1",
    "authorization.programme_role.release-approval@1",
    "authorization.programme_role.publisher@1",
    "authorization.programme_role.venue-catalog@1",
    "authorization.programme_role.venue-selection@1",
    "authorization.programme_role.room-planning@1",
    "authorization.programme_role.room-approval@1",
    "authorization.programme_role.room-dependencies@1",
    "authorization.programme_role.notice-preparation@1",
    "authorization.programme_role.notice-review@1",
    "authorization.programme_role.notice-handoff@1",
    "authorization.programme_role.run-sheet@1",
    "authorization.programme_role.run-sheet-delivery@1",
)

ADAPTERS = (
    "applications.self.programme_proposal@1",
    "applications.target.programme_item@1",
    "applications.import.programme_call_proposal@1",
    "programme.accepted-application-source@1",
    "programme.placement-decisions@1",
    "programme.release-source@1",
    "scheduling.venue-reservation@1",
    "scheduling.release-candidate-source@1",
    "scheduling.release-preflight@1",
    "scheduling.public-release-output@1",
    "scheduling.operator-release-output@1",
    "scheduling.programme-continuity@1",
    "venues.scheduling-reservation@1",
    "venues.accessibility-configuration-source@1",
    "workforce.assignment.participation-excluded@1",
    "workforce.self@1",
    "workforce.programme-coverage@1",
    "workforce.programme-staffing@1",
    "workforce.programme-release-source@1",
)

CONFLICT_SOURCES = (
    "programme.item-and-host-availability@1",
    "scheduling.service-day-and-placement@1",
    "venues.physical-scheduling-dependencies@1",
)

# Internal owner events retain transactional evidence; no generic notifications
# handler or Communications-owned message is admitted by this candidate.
INTERNAL_EVENTS = (
    "authorization.capability.delegated.v1",
    "authorization.capability.direct_granted.v1",
    "authorization.capability.revoked.v1",
    "authorization.role.assigned.v1",
    "authorization.role.revoked.v1",
    "authorization.role_bundle.version_created.v1",
    "events.edition.created.v1",
    "events.edition.details_updated.v1",
    "events.edition.lifecycle_transitioned.v1",
    "identity.account_restriction.applied.v1",
    "organizations.convention_series.created.v1",
    "organizations.convention_series.updated.v1",
    "organizations.representation.changed.v1",
    "system.effect.probe_requested.v1",
    "applications.programme_call.changed.v1",
    "applications.programme_proposal.changed.v1",
    "applications.programme_import.changed.v1",
    "applications.programme_review.changed.v1",
    "applications.programme_conversion.completed.v1",
    "programme.item.changed.v1",
    "scheduling.planning.changed.v1",
    "scheduling.release.changed.v1",
    "scheduling.change_notice.changed.v1",
    "venues.record.changed.v1",
    "workforce.application.submitted.v1",
    "workforce.document.reviewed.v1",
    "workforce.person_availability.changed.v1",
    "workforce.position_assignment.activated.v1",
    "workforce.position_assignment.ended.v1",
    "workforce.position_assignment.proposed.v1",
    "workforce.position_assignment.rejected.v1",
    "workforce.programme_staffing.changed.v1",
    "workforce.shift_commitment.changed.v1",
    "workforce.shift_demand.changed.v1",
    "workforce.structure.changed.v1",
)


def _unique(values: tuple[str, ...]) -> frozenset[str]:
    if len(values) != len(set(values)):
        raise ValueError("Rehearsal manifest contains duplicate literal declarations.")
    return frozenset(values)


PROGRAMME_REHEARSAL_PROFILE = AdoptionProfile(
    code=cast("AdoptionProfileCode", RehearsalProfileCode.PROGRAMME_OPERATIONS),
    version=1,
    label="Programme Operations — isolated candidate, not accepted",
    description="Synthetic setup-to-on-site preparation; never runtime registration.",
    modules=_unique(MODULES),
    capability_codes=_unique(CAPABILITIES),
    destination_codes=("today", "workforce", "setup", "security"),
    shell_destination_kinds=_unique(SHELL_KINDS),
    effect_routes=frozenset(
        EffectRoute(name, "internal") for name in _unique(INTERNAL_EVENTS)
    ),
    catalog_entries=_unique(CATALOG_ENTRIES),
    adapter_codes=_unique(ADAPTERS),
    conflict_source_codes=_unique(CONFLICT_SOURCES),
    root_role_codes=frozenset({"executive-board", "maru-operators"}),
    primary_module="programme",
)
