"""Exact-profile composition for the unscoped My Maru home."""

from __future__ import annotations

from typing import TYPE_CHECKING

from maru.applications.queries import application_shell_profile_pairs
from maru.catalog.queries import catalog_shell_profile_pairs
from maru.logistics.queries import equipment_offer_shell_profile_pairs
from maru.participation.queries import participations_for_account
from maru.registration.queries import registration_shell_profile_pairs
from maru.workforce.queries import workforce_shell_profile_pairs

if TYPE_CHECKING:
    from maru.identity.models import Account


def personal_shell_profile_pairs(*, actor: Account) -> tuple[tuple[str, int], ...]:
    """Return exact profile pairs from authorized or public personal scopes.

    The shell is a composition boundary: owning modules perform their own
    purpose and policy discovery, and this function retains only the immutable
    profile identity needed to gate identifier-free destination kinds.

    Parameters
    ----------
    actor : Account
        Active signed-in account viewing the My Maru home.

    Returns
    -------
    tuple[tuple[str, int], ...]
        Sorted, distinct exact profile identities. Unsupported pairs remain
        harmless because every destination is checked against the manifest.
    """
    pairs = set(registration_shell_profile_pairs(account=actor))
    pairs.update(workforce_shell_profile_pairs(account=actor))
    pairs.update(
        participations_for_account(actor).values_list(
            "edition__adoption_profile_code",
            "edition__adoption_profile_version",
        )
    )
    pairs.update(application_shell_profile_pairs(actor=actor))
    pairs.update(catalog_shell_profile_pairs(actor=actor))
    pairs.update(equipment_offer_shell_profile_pairs(actor=actor))
    return tuple(sorted(pairs))
