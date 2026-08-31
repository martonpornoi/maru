"""Purpose-scoped read contracts owned by Catalog."""

from __future__ import annotations

from typing import TYPE_CHECKING

from maru.catalog.services import available_catalogs_for_actor

if TYPE_CHECKING:
    from maru.identity.models import Account


def catalog_shell_profile_pairs(*, actor: Account) -> tuple[tuple[str, int], ...]:
    """Return exact profiles from catalogs already authorized for the actor.

    Parameters
    ----------
    actor : Account
        Active account whose self-service Catalog scopes are queried.

    Returns
    -------
    tuple[tuple[str, int], ...]
        Sorted, distinct exact profile pairs.
    """
    return tuple(
        sorted(
            {
                (
                    catalog.edition.adoption_profile_code,
                    catalog.edition.adoption_profile_version,
                )
                for catalog in available_catalogs_for_actor(actor=actor)
            }
        )
    )
