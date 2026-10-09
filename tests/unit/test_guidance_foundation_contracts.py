"""Closed Guidance adoption and independently qualified responsibility recipes."""

from importlib import import_module

from maru.authorization.guidance_catalog import (
    GUIDANCE_CONTROL_CAPABILITY,
    GUIDANCE_PROTECTED_CAPABILITIES,
    GUIDANCE_ROLE_RECIPES,
)
from maru.events.adoption import adoption_profile, selectable_adoption_profile
from maru.events.guidance_activation_references import guidance_manifest_digest
from maru.organizations.representation_catalog import WORKSPACE_OPERATORS


def test_fresh_guidance_is_selectable_but_combined_requires_the_expansion_ceremony():
    assert selectable_adoption_profile("guidance_only") is not None
    assert selectable_adoption_profile("announcements_guidance") is None
    assert adoption_profile("announcements_guidance", 1) is not None
    for code in ("guidance_only", "announcements_guidance"):
        profile = adoption_profile(code, 1)
        assert (
            not {"workforce", "registration", "participation", "programme"}
            & profile.modules
        )


def test_canonical_recipes_keep_controller_reader_and_private_evidence_distinct():
    assert GUIDANCE_ROLE_RECIPES["guidance-access-controller"].capability_codes == (
        GUIDANCE_CONTROL_CAPABILITY,
    )
    assert GUIDANCE_ROLE_RECIPES["guidance-reader"].capability_codes == (
        "knowledge.view_current",
    )
    for code, recipe in GUIDANCE_ROLE_RECIPES.items():
        if code != "guidance-access-controller":
            assert GUIDANCE_CONTROL_CAPABILITY not in recipe.capability_codes
    assert set(
        GUIDANCE_ROLE_RECIPES["guidance-operator"].capability_codes
    ) == GUIDANCE_PROTECTED_CAPABILITIES - {GUIDANCE_CONTROL_CAPABILITY}
    assert len(WORKSPACE_OPERATORS.capability_codes) == 10
    assert not any(
        code.startswith(("authorization.", "knowledge.", "announcements."))
        for code in WORKSPACE_OPERATORS.capability_codes
    )


def test_native_adoption_manifest_pins_match_all_three_real_accepted_manifests():
    migration = import_module("maru.events.migrations.0023_guidance_adoption_integrity")
    for code, expected in migration.MANIFEST_DIGESTS.items():
        assert guidance_manifest_digest(adoption_profile(code, 1)) == expected
