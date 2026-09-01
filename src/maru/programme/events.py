"""Minimized domain-event contracts owned by Programme."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, cast

from django.core.exceptions import ValidationError

from maru.programme.catalogs import (
    ProgrammeItemKind,
    ProgrammeItemLifecycle,
    ProgrammeProvenanceKind,
    ProgrammeReadinessConcern,
)

PROGRAMME_ITEM_CHANGED_EVENT: Final = "programme.item.changed.v1"
PROGRAMME_ITEM_CHANGED_SCHEMA_VERSION: Final = 1

PROGRAMME_EVENT_ACTIONS: Final = frozenset(
    {
        "create_core_item",
        "revise_working",
        "revise_delivery",
        "append_discussion",
        "configure_readiness",
        "record_readiness",
        "approve_public_copy",
    }
)
PROGRAMME_EVENT_LAYERS: Final = frozenset(
    {"item", "working", "delivery", "discussion", "readiness", "public_copy"}
)
PROGRAMME_EVENT_CONCERNS: Final = frozenset(
    {"none", *(member.value for member in ProgrammeReadinessConcern)}
)
PROGRAMME_EVENT_ITEM_KINDS: Final = frozenset(
    member.value for member in ProgrammeItemKind
)
PROGRAMME_EVENT_PROVENANCE_KINDS: Final = frozenset(
    member.value for member in ProgrammeProvenanceKind
)
PROGRAMME_EVENT_LIFECYCLES: Final = frozenset(
    member.value for member in ProgrammeItemLifecycle
)
PROGRAMME_EVENT_FIELDS: Final = frozenset(
    {"action", "layer", "item_kind", "provenance", "lifecycle", "concern"}
)

_ACTION_LAYERS: Final = MappingProxyType(
    {
        "create_core_item": "item",
        "revise_working": "working",
        "revise_delivery": "delivery",
        "append_discussion": "discussion",
        "configure_readiness": "readiness",
        "record_readiness": "readiness",
        "approve_public_copy": "public_copy",
    }
)


def validate_programme_item_changed_payload(payload: dict[str, object]) -> None:
    """Validate the exact, content-free Programme item event schema.

    Parameters
    ----------
    payload : dict[str, object]
        Untrusted event payload proposed for durable delivery.

    Raises
    ------
    ValidationError
        If fields, types, closed codes, or action semantics differ from the
        registered version-one contract.
    """
    if set(payload) != PROGRAMME_EVENT_FIELDS or any(
        not isinstance(payload[field], str) or not payload[field]
        for field in PROGRAMME_EVENT_FIELDS
    ):
        raise ValidationError(
            "Programme event payload fields must match the registered schema.",
            code="invalid_domain_event_payload",
        )

    action = cast("str", payload["action"])
    layer = cast("str", payload["layer"])
    concern = cast("str", payload["concern"])
    if (
        action not in PROGRAMME_EVENT_ACTIONS
        or layer not in PROGRAMME_EVENT_LAYERS
        or payload["item_kind"] not in PROGRAMME_EVENT_ITEM_KINDS
        or payload["provenance"] not in PROGRAMME_EVENT_PROVENANCE_KINDS
        or payload["lifecycle"] not in PROGRAMME_EVENT_LIFECYCLES
        or concern not in PROGRAMME_EVENT_CONCERNS
        or _ACTION_LAYERS.get(action) != layer
        or (action in {"configure_readiness", "record_readiness"} and concern == "none")
        or (
            action == "approve_public_copy"
            and concern != ProgrammeReadinessConcern.PUBLIC_COPY.value
        )
        or (
            action
            not in {
                "configure_readiness",
                "record_readiness",
                "approve_public_copy",
            }
            and concern != "none"
        )
    ):
        raise ValidationError(
            "Programme event values do not match a registered action.",
            code="invalid_domain_event_payload",
        )


@dataclass(frozen=True, slots=True)
class ProgrammeItemChanged:
    """Freeze one minimized Programme change before it enters the outbox.

    Attributes
    ----------
    action
        Registered mutation action.
    layer
        Information layer derived from the action.
    item_kind
        Closed Programme item kind.
    provenance
        Closed Programme provenance kind.
    lifecycle
        Closed Programme item lifecycle.
    concern
        Readiness concern, or ``none`` for unrelated actions.
    """

    action: str
    layer: str
    item_kind: str
    provenance: str
    lifecycle: str
    concern: str = "none"

    def __post_init__(self) -> None:
        """Reject an invalid combination at the typed boundary."""
        validate_programme_item_changed_payload(self.as_payload())

    def as_payload(self) -> dict[str, object]:
        """Return a fresh payload containing only registered string codes.

        Returns
        -------
        dict[str, object]
            The exact version-one event payload.
        """
        return {
            "action": self.action,
            "layer": self.layer,
            "item_kind": self.item_kind,
            "provenance": self.provenance,
            "lifecycle": self.lifecycle,
            "concern": self.concern,
        }


def programme_item_changed_payload(
    *,
    action: str,
    item_kind: str,
    provenance: str,
    lifecycle: str,
    concern: str = "none",
) -> dict[str, object]:
    """Build the strict payload and derive its layer from the action.

    Parameters
    ----------
    action : str
        The registered Programme mutation action.
    item_kind : str
        The closed Programme item kind.
    provenance : str
        The closed Programme provenance kind.
    lifecycle : str
        The closed Programme item lifecycle.
    concern : str, default="none"
        The readiness concern for readiness and public-copy actions.

    Returns
    -------
    dict[str, object]
        The validated content-free version-one event payload.
    """
    layer = _ACTION_LAYERS.get(action, "")
    return ProgrammeItemChanged(
        action=action,
        layer=layer,
        item_kind=item_kind,
        provenance=provenance,
        lifecycle=lifecycle,
        concern=concern,
    ).as_payload()


__all__ = [
    "PROGRAMME_EVENT_ACTIONS",
    "PROGRAMME_EVENT_CONCERNS",
    "PROGRAMME_EVENT_FIELDS",
    "PROGRAMME_EVENT_ITEM_KINDS",
    "PROGRAMME_EVENT_LAYERS",
    "PROGRAMME_EVENT_LIFECYCLES",
    "PROGRAMME_EVENT_PROVENANCE_KINDS",
    "PROGRAMME_ITEM_CHANGED_EVENT",
    "PROGRAMME_ITEM_CHANGED_SCHEMA_VERSION",
    "ProgrammeItemChanged",
    "programme_item_changed_payload",
    "validate_programme_item_changed_payload",
]
