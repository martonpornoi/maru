"""Sender-authorized exact host recipients without impersonating personal readers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .host_queries import load_programme_host_roster
from .inputs import require_uuid
from .queries import ProgrammeQueryUnavailableError

if TYPE_CHECKING:
    from uuid import UUID

    from .host_queries import ProgrammeHostReadRequest, ProgrammeHostStateProjection


@dataclass(frozen=True, slots=True)
class ProgrammeHostChangeRecipient:
    """One currently confirmed recipient under the sender's roster authority.

    Attributes
    ----------
    item_id
        Exact Programme item selected under the sender's current scope.
    item_version
        Current item version, independent from immutable released placement.
    account_id
        Active verified account belonging to the selected host relationship.
    display_label
        Current operational person label, not an address or historical snapshot.
    relationship
        Exact current host identity, state, role, version and invitation sequence.
    """

    item_id: UUID
    item_version: int
    account_id: UUID
    display_label: str
    relationship: ProgrammeHostStateProjection


def load_host_change_recipient(
    request: ProgrammeHostReadRequest, *, host_id: UUID
) -> ProgrammeHostChangeRecipient:
    """Resolve one exact host using the authenticated sender's real roster authority.

    Parameters
    ----------
    request : ProgrammeHostReadRequest
        Trusted sender, tenant, edition, exact item and audit attribution.
    host_id : UUID
        Exact retained relationship, never a caller-selected destination account.

    Returns
    -------
    ProgrammeHostChangeRecipient
        Minimized current recipient proof; no portable permission or delivery claim.

    Raises
    ------
    ProgrammeQueryUnavailableError
        If no exact confirmed host with a current verified person can be selected.

    Notes
    -----
    The existing bounded roster query independently requires host_roster fields,
    canonical scope and complete sorted person locks, final authority and mandatory
    audit attributed to the sender. It is not called as the recipient and no
    personal query is used. Only one deliberately selected relationship leaves
    this boundary, without contact, invitation copy or availability. A composing
    command must hold its canonical outer scope and recheck this current proof
    before persisting or disclosing a version-bound communication.
    """
    roster = load_programme_host_roster(request)
    require_uuid(host_id, field="host_id")
    selected = tuple(
        row for row in roster.entries if row.relationship.host_id == host_id
    )
    if (
        host_id.int == 0
        or len(selected) != 1
        or not selected[0].person_current
        or selected[0].relationship.state != "confirmed"
    ):
        raise ProgrammeQueryUnavailableError
    recipient = selected[0]
    return ProgrammeHostChangeRecipient(
        request.item_id,
        roster.item_version,
        recipient.account_id,
        recipient.display_label,
        recipient.relationship,
    )
