"""Minimal Events metadata for an independently admitted Announcements page."""

from dataclasses import dataclass
from uuid import UUID

from maru.events.models import EventEdition


@dataclass(frozen=True, slots=True)
class AnnouncementsWorkspaceReference:
    """Coherent owner labels and profile metadata, never an authorization grant.

    Attributes
    ----------
    organization_id, edition_id
        Exact owner locators.
    organization_name, series_name, edition_name
        Current names disclosed only after the caller admits its page policy.
    profile_code, profile_version
        Exact adoption manifest for shared navigation.
    """

    organization_id: UUID
    edition_id: UUID
    organization_name: str
    series_name: str
    edition_name: str
    profile_code: str
    profile_version: int


def announcements_workspace_reference(
    *, organization_id: UUID, edition_id: UUID
) -> AnnouncementsWorkspaceReference | None:
    """Resolve same-parent labels after the caller's independent task admission.

    Parameters
    ----------
    organization_id : UUID
        Exact organization already admitted by Announcements.
    edition_id : UUID
        Exact edition already admitted by Announcements.

    Returns
    -------
    AnnouncementsWorkspaceReference | None
        Complete current scope labels, or no coherent scope. The caller must
        reauthorize and repeat this reference before disclosing rendered bytes.
    """
    row = (
        EventEdition.objects.filter(
            id=edition_id,
            organization_id=organization_id,
            series__organization_id=organization_id,
        )
        .values_list(
            "organization__name",
            "series__name",
            "name",
            "adoption_profile_code",
            "adoption_profile_version",
        )
        .first()
    )
    if row is None:
        return None
    return AnnouncementsWorkspaceReference(organization_id, edition_id, *row)
