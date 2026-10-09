"""Closed Guidance authority recipes; no generic cross-purpose control registry."""

from dataclasses import dataclass
from types import MappingProxyType

GUIDANCE_CONTROL_CAPABILITY = "authorization.manage_guidance_access"
GUIDANCE_CONTENT_CAPABILITIES = (
    "knowledge.view_current",
    "knowledge.view_working",
    "knowledge.compose",
    "knowledge.review",
    "knowledge.withdraw",
    "knowledge.manage_settings",
    "knowledge.export_evidence",
)
GUIDANCE_PROTECTED_CAPABILITIES = frozenset(
    (*GUIDANCE_CONTENT_CAPABILITIES, GUIDANCE_CONTROL_CAPABILITY)
)
GUIDANCE_BOOTSTRAP_CAPABILITY = "organizations.manage_representation"
GUIDANCE_PROFILE_KEYS = frozenset((("guidance_only", 1), ("announcements_guidance", 1)))
GUIDANCE_CONTROLLER_ROLE_CODE = "guidance-access-controller"
GUIDANCE_OPERATOR_ROLE_CODE = "guidance-operator"
GUIDANCE_TEAM_LABEL = "Guidance team"


@dataclass(frozen=True, slots=True)
class GuidanceRoleRecipe:
    """Pin one understandable role to its exact immutable capability tuple.

    Attributes
    ----------
    code, name
        Stable role code and the human responsibility label.
    capability_codes
        Exact capabilities; control and content never share one recipe.
    version
        Immutable recipe version, currently one.
    """

    code: str
    name: str
    capability_codes: tuple[str, ...]
    version: int = 1


GUIDANCE_ROLE_RECIPES = MappingProxyType(
    {
        "guidance-access-controller": GuidanceRoleRecipe(
            "guidance-access-controller",
            "Manage Guidance access",
            (GUIDANCE_CONTROL_CAPABILITY,),
        ),
        "guidance-operator": GuidanceRoleRecipe(
            "guidance-operator", "Guidance operator", GUIDANCE_CONTENT_CAPABILITIES
        ),
        "guidance-reader": GuidanceRoleRecipe(
            "guidance-reader", "Read approved Guidance", ("knowledge.view_current",)
        ),
        "guidance-editor": GuidanceRoleRecipe(
            "guidance-editor",
            "Write Guidance",
            ("knowledge.view_current", "knowledge.view_working", "knowledge.compose"),
        ),
        "guidance-reviewer": GuidanceRoleRecipe(
            "guidance-reviewer",
            "Review Guidance",
            ("knowledge.view_current", "knowledge.view_working", "knowledge.review"),
        ),
    }
)
"""Code-owned recipes; role selection is never an authority grant."""
