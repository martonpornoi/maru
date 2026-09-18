"""Dormant exact operational recipes, never a grant or profile activation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from types import MappingProxyType

from maru.authorization.catalog import ScopeLevel, capability

_SCOPE_DEPTH = {value: index for index, value in enumerate(ScopeLevel)}
_ALLOWED_OWNERS = frozenset(
    {"events", "applications", "programme", "scheduling", "venues", "workforce"}
)
_ROOM_KIND = "venue.edition_space"
_MAX_ROLE_CODE = 80
_MAX_ROLE_NAME = 120


@dataclass(frozen=True, slots=True)
class ProgrammeRoleRecipe:
    """Describe one reviewed immutable starting role, not inferred responsibility.

    Attributes
    ----------
    code, version
        Stable purpose and exact definition version, independent of current roles.
    name, purpose
        Human review label and explicit consequences of the selected authority.
    capability_codes
        Literal persistable capabilities; no wildcard or self relationship.
    target_scopes
        Exact allowed assignment levels, never organization-wide by convenience.
    resource_kind
        Required typed binding kind for a resource-level choice, otherwise blank.
    """

    code: str
    version: int
    name: str
    purpose: str
    capability_codes: tuple[str, ...]
    target_scopes: tuple[ScopeLevel, ...]
    resource_kind: str = ""

    @property
    def catalog_entry(self) -> str:
        """Return the exact manifest entry required before this recipe is usable."""
        return f"authorization.programme_role.{self.code}@{self.version}"

    @property
    def role_code(self) -> str:
        """Return the ordinary role code; this is not a representation root."""
        return f"programme-{self.code}"

    @property
    def digest(self) -> str:
        """Return canonical complete definition identity, never authorization."""
        payload = {
            "contract": "authorization.programme-role-recipe@1",
            "code": self.code,
            "version": self.version,
            "name": self.name,
            "purpose": self.purpose,
            "capability_codes": self.capability_codes,
            "target_scopes": tuple(scope.value for scope in self.target_scopes),
            "resource_kind": self.resource_kind,
        }
        return hashlib.sha256(
            json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()


def _recipe(
    code: str,
    name: str,
    purpose: str,
    scope: ScopeLevel,
    capabilities: tuple[str, ...],
    *,
    resource_kind: str = "",
) -> ProgrammeRoleRecipe:
    return ProgrammeRoleRecipe(
        code, 1, name, purpose, capabilities, (scope,), resource_kind
    )


_RECIPES = (
    _recipe(
        "edition-coordination",
        "Programme edition coordination",
        (
            "Review and change edition details/lifecycle and the complete "
            "Department/Position structure; this grants no Programme content or "
            "operational approval."
        ),
        ScopeLevel.EDITION,
        (
            "events.view_basic",
            "events.change_profile",
            "events.transition",
            "workforce.view_structure",
            "workforce.manage_structure",
        ),
    ),
    _recipe(
        "intake",
        "Programme call and import editing",
        (
            "Configure calls and preview/apply Programme imports owned by one "
            "Department; no review, decision or sibling Department access."
        ),
        ScopeLevel.DEPARTMENT,
        ("applications.manage_programme_calls", "applications.import_programme"),
    ),
    _recipe(
        "import-disposal",
        "Programme import disposal",
        (
            "Explicitly dispose eligible Programme staging payloads in one edition; "
            "retained lineage remains and this grants no import or private "
            "review access."
        ),
        ScopeLevel.EDITION,
        ("applications.dispose_programme_import",),
    ),
    _recipe(
        "review-setup",
        "Programme review coordination",
        (
            "Configure review policies, open exact sealed cases and manage named "
            "reviewers in one Department; no automatic personal review or final "
            "decision."
        ),
        ScopeLevel.DEPARTMENT,
        ("applications.manage_programme_review",),
    ),
    _recipe(
        "reviewer",
        "Programme reviewer",
        (
            "Read and review only actually assigned eligible cases after own "
            "conflict clearance; the role itself creates no case assignment."
        ),
        ScopeLevel.DEPARTMENT,
        ("applications.review_programme",),
    ),
    _recipe(
        "moderator",
        "Programme review moderation",
        (
            "Read permitted review evidence and independently moderate stages in "
            "one Department; owner separation-of-duty checks still apply."
        ),
        ScopeLevel.DEPARTMENT,
        ("applications.moderate_programme_review",),
    ),
    _recipe(
        "decision-maker",
        "Programme decisions",
        (
            "Read permitted sealed answers and review evidence and record "
            "independent final decisions in one Department; no conversion or "
            "publication."
        ),
        ScopeLevel.DEPARTMENT,
        ("applications.decide_programme",),
    ),
    _recipe(
        "conversion",
        "Accepted Programme conversion",
        (
            "Convert effective accepted proposals owned by one Department; "
            "separately authorized Programme item creation remains necessary."
        ),
        ScopeLevel.DEPARTMENT,
        ("applications.convert_programme_acceptance",),
    ),
    _recipe(
        "content",
        "Programme content and readiness",
        (
            "Manage edition-wide private working information, readiness, retained "
            "discussion and reviewed public copy; no delivery instructions, host "
            "details or release publication."
        ),
        ScopeLevel.EDITION,
        (
            "programme.view_private",
            "programme.manage_items",
            "programme.view_readiness",
            "programme.manage_readiness",
            "programme.view_discussion",
            "programme.view_public_copy",
            "programme.approve_public_copy",
        ),
    ),
    _recipe(
        "delivery",
        "Programme delivery information",
        (
            "Read and revise technical, accessibility-delivery and media-consent "
            "instructions and history throughout the edition; no medical record or "
            "general review answers."
        ),
        ScopeLevel.EDITION,
        ("programme.view_delivery", "programme.manage_delivery"),
    ),
    _recipe(
        "hosting",
        "Programme hosting coordination",
        (
            "Read permitted host details and manage explicit host "
            "invitations/removals in the edition; never accept, respond or share "
            "availability for another person."
        ),
        ScopeLevel.EDITION,
        ("programme.view_hosts", "programme.manage_hosts"),
    ),
    _recipe(
        "staffing",
        "Programme staffing requirements",
        (
            "Review and revise Programme staffing requirements; Workforce source "
            "access and Shift actions remain separately authorized."
        ),
        ScopeLevel.EDITION,
        ("programme.view_staffing", "programme.manage_staffing"),
    ),
    _recipe(
        "workforce",
        "Programme Workforce organizing",
        (
            "Operate the edition Workforce journey, including private "
            "application/document evidence, assignments, shared availability, "
            "holder labels and Shifts; no attendee Participation or "
            "authority-management grant."
        ),
        ScopeLevel.EDITION,
        (
            "events.view_basic",
            "workforce.view_structure",
            "workforce.manage_structure",
            "workforce.manage_applications",
            "workforce.manage_documents",
            "workforce.manage_assignments",
            "workforce.view_availability",
            "workforce.view_shifts",
            "workforce.manage_shifts",
        ),
    ),
    _recipe(
        "coverage-reader",
        "Programme coverage reader",
        (
            "Read edition-wide Workforce structure, Shift coverage and permitted "
            "holder labels/suitability consequences; this is broader than an "
            "anonymous coverage count, and grants no Shift mutation."
        ),
        ScopeLevel.EDITION,
        ("workforce.view_structure", "workforce.view_shifts"),
    ),
    _recipe(
        "planner",
        "Programme timetable planning",
        (
            "Manage private timetable alternatives and inspect minimized "
            "Programme/host dependencies; exact Venue and Workforce source access "
            "remain separate. No release approval or publication."
        ),
        ScopeLevel.EDITION,
        (
            "scheduling.view_planning",
            "scheduling.view_history",
            "scheduling.view_conflicts",
            "scheduling.manage_service_days",
            "scheduling.manage_occurrences",
            "scheduling.manage_candidates",
            "scheduling.evaluate_candidates",
            "scheduling.acknowledge_warnings",
            "scheduling.manage_reservations",
            "programme.view_scheduling_dependencies",
        ),
    ),
    _recipe(
        "release-approval",
        "Programme release approval",
        (
            "Inspect release preflight, acknowledge current release warnings and "
            "independently approve an exact release; source permissions remain "
            "separate and this role cannot publish."
        ),
        ScopeLevel.EDITION,
        (
            "scheduling.view_planning",
            "scheduling.view_history",
            "scheduling.view_conflicts",
            "scheduling.acknowledge_release_warnings",
            "scheduling.approve_release",
        ),
    ),
    _recipe(
        "publisher",
        "Programme release publication",
        (
            "Inspect and publish independently approved releases or deliberately "
            "withdraw the active release; no approval on another person's behalf."
        ),
        ScopeLevel.EDITION,
        (
            "scheduling.view_planning",
            "scheduling.view_history",
            "scheduling.view_conflicts",
            "scheduling.publish_release",
            "scheduling.withdraw_release",
        ),
    ),
    _recipe(
        "venue-catalog",
        "Shared Venue facts",
        (
            "Read and manage reusable venue facts, layouts, media and permitted "
            "provider contacts across the WHOLE organization, not just this "
            "edition. No accommodation inventory or room publication."
        ),
        ScopeLevel.ORGANIZATION,
        ("venues.view_properties", "venues.manage_properties"),
    ),
    _recipe(
        "venue-selection",
        "Programme Venue selection",
        (
            "Read the edition Venue workspace and select venues/spaces with "
            "edition-owned overrides; shared property and exact-space authority "
            "remain separate."
        ),
        ScopeLevel.EDITION,
        ("venues.view_workspace", "venues.select_for_edition"),
    ),
    _recipe(
        "room-planning",
        "Exact room planning",
        (
            "Read physical constraints and manage operational bookings for one "
            "selected room only; no independent physical approval or public "
            "Programme release."
        ),
        ScopeLevel.RESOURCE,
        (
            "venues.view_space_schedule",
            "venues.manage_space_schedule",
            "venues.view_scheduling_dependencies",
        ),
        resource_kind=_ROOM_KIND,
    ),
    _recipe(
        "room-approval",
        "Exact room physical approval",
        (
            "Read and independently approve the physical schedule for one selected "
            "room. Programme-linked bookings still cannot publish a second "
            "Programme timetable."
        ),
        ScopeLevel.RESOURCE,
        (
            "venues.view_space_schedule",
            "venues.publish_space_schedule",
            "venues.view_scheduling_dependencies",
        ),
        resource_kind=_ROOM_KIND,
    ),
    _recipe(
        "room-dependencies",
        "Exact room constraint reading",
        (
            "Read one selected room's minimized physical/accessibility constraints "
            "for independently authorized timetable work; no booking, property or "
            "approval changes."
        ),
        ScopeLevel.RESOURCE,
        ("venues.view_scheduling_dependencies",),
        resource_kind=_ROOM_KIND,
    ),
    _recipe(
        "room-operations",
        "Exact room operations and independent physical approval",
        (
            "Read constraints, change availability and operational bookings, and "
            "independently approve physical use of one selected room. This is "
            "room-management authority, not approval-only access. You cannot "
            "approve your own booking or source placement. No Venue publication "
            "or Programme release authority."
        ),
        ScopeLevel.RESOURCE,
        (
            "venues.view_space_schedule",
            "venues.manage_space_schedule",
            "venues.view_scheduling_dependencies",
        ),
        resource_kind=_ROOM_KIND,
    ),
    _recipe(
        "notice-preparation",
        "Programme notice preparation",
        (
            "Select eligible operator recipients and prepare bounded change "
            "notices; host/Workforce recipient sources require their own access. "
            "No independent review or handoff."
        ),
        ScopeLevel.EDITION,
        (
            "scheduling.view_change_recipients",
            "scheduling.view_change_notices",
            "scheduling.prepare_change_notices",
        ),
    ),
    _recipe(
        "notice-review",
        "Programme notice review",
        (
            "Read and independently review permitted change-notice packages; no "
            "preparation, manual handoff or recipient acknowledgement."
        ),
        ScopeLevel.EDITION,
        ("scheduling.view_change_notices", "scheduling.review_change_notices"),
    ),
    _recipe(
        "notice-handoff",
        "Programme notice handoff",
        (
            "Read and manually hand off independently reviewed notices to exact "
            "permitted recipients; never acknowledge for another person or claim "
            "delivery from inventory alone."
        ),
        ScopeLevel.EDITION,
        ("scheduling.view_change_notices", "scheduling.handoff_change_notices"),
    ),
    ProgrammeRoleRecipe(
        "run-sheet",
        1,
        "Programme on-site run sheet",
        (
            "Read approved released geometry/copy, room wayfinding and minimized "
            "staffing instructions for one explicit edition, Department or "
            "selected-room purpose; no working/review/host-contact layers or live "
            "mutation."
        ),
        (
            "scheduling.view_operator_output",
            "programme.view_operator_copy",
            "venues.view_operator_wayfinding",
            "workforce.view_operator_staffing",
        ),
        (ScopeLevel.EDITION, ScopeLevel.DEPARTMENT, ScopeLevel.RESOURCE),
        _ROOM_KIND,
    ),
    ProgrammeRoleRecipe(
        "run-sheet-delivery",
        1,
        "Programme on-site delivery layers",
        (
            "Add explicitly requested current technical, accessibility and "
            "media-delivery layers to an independently authorized run sheet at the "
            "same purpose scope; not a historical approval or grant to other "
            "purposes."
        ),
        ("programme.view_operator_delivery",),
        (ScopeLevel.EDITION, ScopeLevel.DEPARTMENT, ScopeLevel.RESOURCE),
        _ROOM_KIND,
    ),
)


def _validate(recipe: ProgrammeRoleRecipe) -> None:
    if (
        not isinstance(recipe.code, str)
        or re.fullmatch(r"[a-z][a-z0-9-]*", recipe.code) is None
        or len(recipe.role_code) > _MAX_ROLE_CODE
        or isinstance(recipe.version, bool)
        or not isinstance(recipe.version, int)
        or recipe.version < 1
        or not isinstance(recipe.name, str)
        or not recipe.name.strip()
        or len(recipe.name) > _MAX_ROLE_NAME
        or not isinstance(recipe.purpose, str)
        or not recipe.purpose.strip()
        or not isinstance(recipe.capability_codes, tuple)
        or not recipe.capability_codes
        or any(not isinstance(code, str) for code in recipe.capability_codes)
        or len(set(recipe.capability_codes)) != len(recipe.capability_codes)
        or not isinstance(recipe.target_scopes, tuple)
        or not recipe.target_scopes
        or any(not isinstance(scope, ScopeLevel) for scope in recipe.target_scopes)
        or len(set(recipe.target_scopes)) != len(recipe.target_scopes)
        or not isinstance(recipe.resource_kind, str)
        or bool(recipe.resource_kind) != (ScopeLevel.RESOURCE in recipe.target_scopes)
        or (recipe.resource_kind and recipe.resource_kind != _ROOM_KIND)
    ):
        raise ValueError("Malformed Programme role recipe.")
    for code in recipe.capability_codes:
        definition = capability(code)
        if (
            definition is None
            or not definition.persistable
            or definition.allow_self
            or code.partition(".")[0] not in _ALLOWED_OWNERS
            or code == "applications.recover_programme_department_ownership"
            or any(
                _SCOPE_DEPTH[scope] < _SCOPE_DEPTH[definition.maximum_scope]
                for scope in recipe.target_scopes
            )
        ):
            raise ValueError(
                "Programme role recipe violates the capability/scope boundary."
            )


for _value in _RECIPES:
    _validate(_value)
if len({(item.code, item.version) for item in _RECIPES}) != len(_RECIPES):
    raise ValueError("Programme role recipes must have unique exact identities.")

PROGRAMME_ROLE_RECIPES = MappingProxyType(
    {(item.code, item.version): item for item in _RECIPES}
)
PROGRAMME_ROLE_CATALOG_ENTRIES = tuple(item.catalog_entry for item in _RECIPES)


def programme_role_recipe(code: str, version: int) -> ProgrammeRoleRecipe | None:
    """Resolve an exact dormant definition without granting or discovering access.

    Parameters
    ----------
    code : str
        Exact role-purpose code, not a user-controlled capability expression.
    version : int
        Positive immutable definition version; Boolean aliases are rejected.

    Returns
    -------
    ProgrammeRoleRecipe | None
        Code-owned recipe or unavailable. Callers must separately require the exact
        Programme profile/catalog entry and authorize the actual scope and people.
    """
    if (
        not isinstance(code, str)
        or isinstance(version, bool)
        or not isinstance(version, int)
    ):
        return None
    return PROGRAMME_ROLE_RECIPES.get((code, version))
