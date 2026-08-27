"""Code-owned accountable organization-representation definitions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RepresentationDefinition:
    """Describe one truthful organization stewardship root.

    Attributes
    ----------
    code
        The stable representation type stored on the organization.
    name
        The human-readable representation name.
    controller_label
        The singular label used for one accountable person.
    membership_label
        The exact organization-membership evidence label.
    role_code
        The reserved organization-scoped authority bundle code.
    role_name
        The human-readable authority bundle name.
    role_version
        The immutable bundle-definition version.
    capability_codes
        The exact capability set granted by initial activation.
    purpose
        The plain-language responsibility boundary shown to people.
    """

    code: str
    name: str
    controller_label: str
    membership_label: str
    role_code: str
    role_name: str
    role_version: int
    capability_codes: tuple[str, ...]
    purpose: str


EXECUTIVE_BOARD_CAPABILITIES = (
    "organizations.view_basic",
    "organizations.change_profile",
    "organizations.create_series",
    "organizations.change_series",
    "organizations.manage_representation",
    "events.view_basic",
    "events.create",
    "authorization.delegate",
    "authorization.grant_direct",
    "authorization.revoke",
    "authorization.manage_roles",
    "audit.view_security",
)

MARU_OPERATOR_CAPABILITIES = (
    *EXECUTIVE_BOARD_CAPABILITIES,
    "events.change_profile",
    "events.transition",
    "workforce.view_structure",
    "workforce.manage_structure",
    "workforce.manage_applications",
    "workforce.manage_documents",
    "workforce.manage_assignments",
    "workforce.view_availability",
    "workforce.view_shifts",
    "workforce.manage_shifts",
)

EXECUTIVE_BOARD = RepresentationDefinition(
    code="executive_board",
    name="Executive Board",
    controller_label="Executive Board controller",
    membership_label="Executive Board controller",
    role_code="executive-board",
    role_name="Executive Board",
    role_version=1,
    capability_codes=EXECUTIVE_BOARD_CAPABILITIES,
    purpose=(
        "Represents the organization's real accountable Executive Board and "
        "controls delegated Maru authority."
    ),
)

MARU_OPERATORS = RepresentationDefinition(
    code="maru_operators",
    name="Maru operators",
    controller_label="Maru operator",
    membership_label="Maru operator",
    role_code="maru-operators",
    role_name="Maru operators",
    role_version=1,
    capability_codes=MARU_OPERATOR_CAPABILITIES,
    purpose=(
        "Identifies the people accountable for operating Maru and Workforce. "
        "It does not claim that they hold a legal or constitutional office in "
        "the organization."
    ),
)

REPRESENTATION_DEFINITIONS = {
    EXECUTIVE_BOARD.code: EXECUTIVE_BOARD,
    MARU_OPERATORS.code: MARU_OPERATORS,
}

REPRESENTATION_CODE_CHOICES = tuple(
    (definition.code, definition.name)
    for definition in REPRESENTATION_DEFINITIONS.values()
)

REPRESENTATION_ROLE_CODES = frozenset(
    definition.role_code for definition in REPRESENTATION_DEFINITIONS.values()
)

ACCOUNTABLE_REPRESENTATION_NAMES = frozenset(
    definition.name.casefold() for definition in REPRESENTATION_DEFINITIONS.values()
)


def representation_definition(code: str) -> RepresentationDefinition | None:
    """Return the code-owned definition for a representation type.

    Parameters
    ----------
    code : str
        The persisted organization-representation code.

    Returns
    -------
    RepresentationDefinition | None
        The matching definition, or ``None`` for an unknown code.
    """
    return REPRESENTATION_DEFINITIONS.get(code)


def representation_definition_for_role(
    role_code: str,
) -> RepresentationDefinition | None:
    """Return the representation definition that owns a reserved role.

    Parameters
    ----------
    role_code : str
        The persisted role-bundle code.

    Returns
    -------
    RepresentationDefinition | None
        The matching definition, or ``None`` for an ordinary role.
    """
    return next(
        (
            definition
            for definition in REPRESENTATION_DEFINITIONS.values()
            if definition.role_code == role_code
        ),
        None,
    )
