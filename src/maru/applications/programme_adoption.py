"""Dormant exact-adoption keys for Applications-owned Programme proposals."""

from typing import Final

from maru.events.adoption import profile_allows_adapter

APPLICATION_PROGRAMME_SELF_ADAPTER: Final = "applications.self.programme_proposal@1"
APPLICATION_PROGRAMME_ITEM_TARGET_ADAPTER: Final = (
    "applications.target.programme_item@1"
)
APPLICATION_PROGRAMME_IMPORT_ADAPTER: Final = (
    "applications.import.programme_call_proposal@1"
)
APPLICATION_PROGRAMME_ITEM_TARGET_KIND: Final = "programme_item"


def profile_allows_application_programme_self(
    profile_code: str,
    profile_version: int,
) -> bool:
    """Return whether an exact future profile admits proposal self-service.

    Parameters
    ----------
    profile_code : str
        The persisted adoption-profile code.
    profile_version : int
        The persisted adoption-profile version.

    Returns
    -------
    bool
        ``True`` only when the exact manifest pins the purpose-specific
        Programme proposal self adapter.
    """
    return profile_allows_adapter(
        profile_code,
        profile_version,
        APPLICATION_PROGRAMME_SELF_ADAPTER,
    )


def profile_allows_application_programme_import(
    profile_code: str,
    profile_version: int,
) -> bool:
    """Return whether an exact future profile admits Programme import.

    Parameters
    ----------
    profile_code : str
        Persisted adoption-profile code.
    profile_version : int
        Persisted adoption-profile version.

    Returns
    -------
    bool
        Whether the exact manifest pins the Programme import adapter.
    """
    return profile_allows_adapter(
        profile_code,
        profile_version,
        APPLICATION_PROGRAMME_IMPORT_ADAPTER,
    )


__all__ = [
    "APPLICATION_PROGRAMME_IMPORT_ADAPTER",
    "APPLICATION_PROGRAMME_ITEM_TARGET_ADAPTER",
    "APPLICATION_PROGRAMME_ITEM_TARGET_KIND",
    "APPLICATION_PROGRAMME_SELF_ADAPTER",
    "profile_allows_application_programme_import",
    "profile_allows_application_programme_self",
]
