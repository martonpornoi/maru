"""Add truthful room authority without rewriting retained recipe meanings."""

import json
from typing import ClassVar

from django.db import migrations

# Historical definitions copied literally; no imports from the live catalog.
_OLD_RECIPES = r"""{
  "edition-coordination@1": {
    "digest": "b15c36577ee33bdcb7160e99705fced70b6b5c3227cff3ee95976b40b5c205c1",
    "role_code": "programme-edition-coordination",
    "version": 1,
    "name": "Programme edition coordination",
    "capabilities": [
      "events.view_basic",
      "events.change_profile",
      "events.transition",
      "workforce.view_structure",
      "workforce.manage_structure"
    ],
    "scopes": [
      "edition"
    ],
    "resource_kind": ""
  },
  "intake@1": {
    "digest": "f7ecc37318e4fe7a58afd78535a2019a68daceb9c98666d1cabb9874fc1a35e9",
    "role_code": "programme-intake",
    "version": 1,
    "name": "Programme call and import editing",
    "capabilities": [
      "applications.manage_programme_calls",
      "applications.import_programme"
    ],
    "scopes": [
      "department"
    ],
    "resource_kind": ""
  },
  "import-disposal@1": {
    "digest": "999a29376e7856da0d2305688c99207f66edc153b40f2f12f8acfa12039cd3c3",
    "role_code": "programme-import-disposal",
    "version": 1,
    "name": "Programme import disposal",
    "capabilities": [
      "applications.dispose_programme_import"
    ],
    "scopes": [
      "edition"
    ],
    "resource_kind": ""
  },
  "review-setup@1": {
    "digest": "fe5d06c5eb10509e1f5963e20c75ecfd10f1b0d8caa899d507bf4fbd03e21929",
    "role_code": "programme-review-setup",
    "version": 1,
    "name": "Programme review coordination",
    "capabilities": [
      "applications.manage_programme_review"
    ],
    "scopes": [
      "department"
    ],
    "resource_kind": ""
  },
  "reviewer@1": {
    "digest": "d237d51cccef7ce85f6a661b5f11d6a3681c6dd6df6d9b088283ed058b2a1216",
    "role_code": "programme-reviewer",
    "version": 1,
    "name": "Programme reviewer",
    "capabilities": [
      "applications.review_programme"
    ],
    "scopes": [
      "department"
    ],
    "resource_kind": ""
  },
  "moderator@1": {
    "digest": "49f72f434c77f75d16677cc76d2f8bb3205ce809c0839c2463beed6e0fa665de",
    "role_code": "programme-moderator",
    "version": 1,
    "name": "Programme review moderation",
    "capabilities": [
      "applications.moderate_programme_review"
    ],
    "scopes": [
      "department"
    ],
    "resource_kind": ""
  },
  "decision-maker@1": {
    "digest": "eb79b2e317f9a103ff790023838dcf6cf1b4b5372b2ca0322f5ac0924858b00b",
    "role_code": "programme-decision-maker",
    "version": 1,
    "name": "Programme decisions",
    "capabilities": [
      "applications.decide_programme"
    ],
    "scopes": [
      "department"
    ],
    "resource_kind": ""
  },
  "conversion@1": {
    "digest": "b55db9463463d50a8762acb28f3cab33dc569082fde8a092dc7d864b5ed7b048",
    "role_code": "programme-conversion",
    "version": 1,
    "name": "Accepted Programme conversion",
    "capabilities": [
      "applications.convert_programme_acceptance"
    ],
    "scopes": [
      "department"
    ],
    "resource_kind": ""
  },
  "content@1": {
    "digest": "74922c27fc319b53b05480a9ec5ebc0e4cea6b5fccfaa6da39d91f17a9813963",
    "role_code": "programme-content",
    "version": 1,
    "name": "Programme content and readiness",
    "capabilities": [
      "programme.view_private",
      "programme.manage_items",
      "programme.view_readiness",
      "programme.manage_readiness",
      "programme.view_discussion",
      "programme.view_public_copy",
      "programme.approve_public_copy"
    ],
    "scopes": [
      "edition"
    ],
    "resource_kind": ""
  },
  "delivery@1": {
    "digest": "a4c61167f08e14118c917f528f5422fb273faf88dec601e581aa4906eaeda3af",
    "role_code": "programme-delivery",
    "version": 1,
    "name": "Programme delivery information",
    "capabilities": [
      "programme.view_delivery",
      "programme.manage_delivery"
    ],
    "scopes": [
      "edition"
    ],
    "resource_kind": ""
  },
  "hosting@1": {
    "digest": "5924c6e15da93cc063c1a1adf84dd7e3886f3b2f27c5368ccd38f8e41de1cc08",
    "role_code": "programme-hosting",
    "version": 1,
    "name": "Programme hosting coordination",
    "capabilities": [
      "programme.view_hosts",
      "programme.manage_hosts"
    ],
    "scopes": [
      "edition"
    ],
    "resource_kind": ""
  },
  "staffing@1": {
    "digest": "9615397a06d7f7466c38bd40cf4ffcbd60b266c029038bda6687c9be28fb9025",
    "role_code": "programme-staffing",
    "version": 1,
    "name": "Programme staffing requirements",
    "capabilities": [
      "programme.view_staffing",
      "programme.manage_staffing"
    ],
    "scopes": [
      "edition"
    ],
    "resource_kind": ""
  },
  "workforce@1": {
    "digest": "c57231df77e00fc14b1da2c486c5400cd7f8e7a82613c1b7206065e11429a9b3",
    "role_code": "programme-workforce",
    "version": 1,
    "name": "Programme Workforce organizing",
    "capabilities": [
      "events.view_basic",
      "workforce.view_structure",
      "workforce.manage_structure",
      "workforce.manage_applications",
      "workforce.manage_documents",
      "workforce.manage_assignments",
      "workforce.view_availability",
      "workforce.view_shifts",
      "workforce.manage_shifts"
    ],
    "scopes": [
      "edition"
    ],
    "resource_kind": ""
  },
  "coverage-reader@1": {
    "digest": "9914a842dfecc95884498be6ed22d66a621b02990ca27e357c65e2cda9438189",
    "role_code": "programme-coverage-reader",
    "version": 1,
    "name": "Programme coverage reader",
    "capabilities": [
      "workforce.view_structure",
      "workforce.view_shifts"
    ],
    "scopes": [
      "edition"
    ],
    "resource_kind": ""
  },
  "planner@1": {
    "digest": "8b78b3b55adfebfdb2904c5c9809175373ae950b2e2562c1622b494c8f70f2a8",
    "role_code": "programme-planner",
    "version": 1,
    "name": "Programme timetable planning",
    "capabilities": [
      "scheduling.view_planning",
      "scheduling.view_history",
      "scheduling.view_conflicts",
      "scheduling.manage_service_days",
      "scheduling.manage_occurrences",
      "scheduling.manage_candidates",
      "scheduling.evaluate_candidates",
      "scheduling.acknowledge_warnings",
      "scheduling.manage_reservations",
      "programme.view_scheduling_dependencies"
    ],
    "scopes": [
      "edition"
    ],
    "resource_kind": ""
  },
  "release-approval@1": {
    "digest": "53794f023c22d4a81bac809eb2ffce4f43e5b75bdd66e7e03d06437ccdaa1ebc",
    "role_code": "programme-release-approval",
    "version": 1,
    "name": "Programme release approval",
    "capabilities": [
      "scheduling.view_planning",
      "scheduling.view_history",
      "scheduling.view_conflicts",
      "scheduling.acknowledge_release_warnings",
      "scheduling.approve_release"
    ],
    "scopes": [
      "edition"
    ],
    "resource_kind": ""
  },
  "publisher@1": {
    "digest": "b1606969c7201fe85144257d33dc399761641fb6291dc3b344181e509e8dd69b",
    "role_code": "programme-publisher",
    "version": 1,
    "name": "Programme release publication",
    "capabilities": [
      "scheduling.view_planning",
      "scheduling.view_history",
      "scheduling.view_conflicts",
      "scheduling.publish_release",
      "scheduling.withdraw_release"
    ],
    "scopes": [
      "edition"
    ],
    "resource_kind": ""
  },
  "venue-catalog@1": {
    "digest": "51e89b0f1f15bed5a5db702b1b4693d6c41cc59b0b3315bd1dd7d75c9d7a89b5",
    "role_code": "programme-venue-catalog",
    "version": 1,
    "name": "Shared Venue facts",
    "capabilities": [
      "venues.view_properties",
      "venues.manage_properties"
    ],
    "scopes": [
      "organization"
    ],
    "resource_kind": ""
  },
  "venue-selection@1": {
    "digest": "e218e99e09e11a9a57b48a93797ab983b8cf460f41be17ed61ffbf53672347e6",
    "role_code": "programme-venue-selection",
    "version": 1,
    "name": "Programme Venue selection",
    "capabilities": [
      "venues.view_workspace",
      "venues.select_for_edition"
    ],
    "scopes": [
      "edition"
    ],
    "resource_kind": ""
  },
  "room-planning@1": {
    "digest": "e1dd802607539898b3bdeab0ea286dc12507044ef9da65706328035e2bb7d3f1",
    "role_code": "programme-room-planning",
    "version": 1,
    "name": "Exact room planning",
    "capabilities": [
      "venues.view_space_schedule",
      "venues.manage_space_schedule",
      "venues.view_scheduling_dependencies"
    ],
    "scopes": [
      "resource"
    ],
    "resource_kind": "venue.edition_space"
  },
  "room-approval@1": {
    "digest": "95eb2e837edc0794ece09b58a275cb9e595da5074ed980c24e6a1156dacbea86",
    "role_code": "programme-room-approval",
    "version": 1,
    "name": "Exact room physical approval",
    "capabilities": [
      "venues.view_space_schedule",
      "venues.publish_space_schedule",
      "venues.view_scheduling_dependencies"
    ],
    "scopes": [
      "resource"
    ],
    "resource_kind": "venue.edition_space"
  },
  "room-dependencies@1": {
    "digest": "6f72b70822a56f6c8887041687b695b7e34c620df200ba358ac448e53485c3cc",
    "role_code": "programme-room-dependencies",
    "version": 1,
    "name": "Exact room constraint reading",
    "capabilities": [
      "venues.view_scheduling_dependencies"
    ],
    "scopes": [
      "resource"
    ],
    "resource_kind": "venue.edition_space"
  },
  "notice-preparation@1": {
    "digest": "e3d4480c2c6b197d72e6ae951ffd69462f1c3da6c2a2a3cf9501e56f23e48d0b",
    "role_code": "programme-notice-preparation",
    "version": 1,
    "name": "Programme notice preparation",
    "capabilities": [
      "scheduling.view_change_recipients",
      "scheduling.view_change_notices",
      "scheduling.prepare_change_notices"
    ],
    "scopes": [
      "edition"
    ],
    "resource_kind": ""
  },
  "notice-review@1": {
    "digest": "b48bf39e9e117c71f0b3023f204ce234c39124028871b8f0c8c774f358caa570",
    "role_code": "programme-notice-review",
    "version": 1,
    "name": "Programme notice review",
    "capabilities": [
      "scheduling.view_change_notices",
      "scheduling.review_change_notices"
    ],
    "scopes": [
      "edition"
    ],
    "resource_kind": ""
  },
  "notice-handoff@1": {
    "digest": "a8d0ddf39c8004cfe3d713adb1e7c9edbdaea5ad31c045e8049832523cd72f4b",
    "role_code": "programme-notice-handoff",
    "version": 1,
    "name": "Programme notice handoff",
    "capabilities": [
      "scheduling.view_change_notices",
      "scheduling.handoff_change_notices"
    ],
    "scopes": [
      "edition"
    ],
    "resource_kind": ""
  },
  "run-sheet@1": {
    "digest": "efd138a77c89eaadaec2116b4a947133979d52e45bfd1cd8f85db89672b648f5",
    "role_code": "programme-run-sheet",
    "version": 1,
    "name": "Programme on-site run sheet",
    "capabilities": [
      "scheduling.view_operator_output",
      "programme.view_operator_copy",
      "venues.view_operator_wayfinding",
      "workforce.view_operator_staffing"
    ],
    "scopes": [
      "edition",
      "department",
      "resource"
    ],
    "resource_kind": "venue.edition_space"
  },
  "run-sheet-delivery@1": {
    "digest": "2cc048cce0d52591d97b1275ad091f561a64bfbe063b45fb91e3ba7cd3e55ff4",
    "role_code": "programme-run-sheet-delivery",
    "version": 1,
    "name": "Programme on-site delivery layers",
    "capabilities": [
      "programme.view_operator_delivery"
    ],
    "scopes": [
      "edition",
      "department",
      "resource"
    ],
    "resource_kind": "venue.edition_space"
  }
}"""
_NEW_RECIPE = r"""{
  "room-operations@1": {
    "digest": "240c680373fef31ce1d782518a3a7c2c67834f9281f2825edfb3217daf9964a0",
    "role_code": "programme-room-operations",
    "version": 1,
    "name": "Exact room operations and independent physical approval",
    "capabilities": [
      "venues.view_space_schedule",
      "venues.manage_space_schedule",
      "venues.view_scheduling_dependencies"
    ],
    "scopes": [
      "resource"
    ],
    "resource_kind": "venue.edition_space"
  }
}"""
_FROZEN_RECIPES = json.dumps(
    {**json.loads(_OLD_RECIPES), **json.loads(_NEW_RECIPE)}, indent=2
)
_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_programme_role_recipe(
    definition_code text, definition_version integer
)
RETURNS jsonb AS $$
BEGIN
    RETURN '__RECIPES__'::jsonb
        -> (definition_code || '@' || definition_version::text);
END;
$$ LANGUAGE plpgsql IMMUTABLE SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION public.maru_programme_role_recipe(text, integer) FROM PUBLIC;
"""
_LOCKS = """
LOCK TABLE public.authorization_rolebundle,
    public.authorization_programmerolerequest,
    public.authorization_programmeroledecisionrecord IN ACCESS EXCLUSIVE MODE;
"""
_UNUSED_ONLY = """
DO $unused_room_recipe_reverse$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.authorization_programmerolerequest
        WHERE recipe_code = 'room-operations' AND recipe_version = 1
    ) OR EXISTS (
        SELECT 1 FROM public.authorization_rolebundle
        WHERE code = 'programme-room-operations'
    ) THEN
        RAISE EXCEPTION 'Room operations evidence exists; retain it and fix forward'
            USING ERRCODE = '23514';
    END IF;
END;
$unused_room_recipe_reverse$;
"""
FORWARD_SQL = _LOCKS + _FUNCTION_SQL.replace("__RECIPES__", _FROZEN_RECIPES)
REVERSE_SQL = _LOCKS + _UNUSED_ONLY + _FUNCTION_SQL.replace("__RECIPES__", _OLD_RECIPES)


class Migration(migrations.Migration):
    """Preserve old intent and fence removal once the new recipe is retained."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0035_programme_role_approval_audit"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
