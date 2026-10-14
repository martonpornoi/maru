"""Minimal Events metadata for an independently admitted Knowledge page."""

from dataclasses import dataclass
from uuid import UUID

from django.db.models import Q

from maru.events.models import EventEdition


@dataclass(frozen=True, slots=True)
class KnowledgeWorkspaceReference:
    """Coherent owner labels and profile metadata, never an authorization grant.

    Attributes
    ----------
    organization_id, edition_id
        Exact owner locators.
    organization_name, series_name, edition_name
        Current names disclosed only after the caller admits its page policy.
    time_zone
        The edition time zone used for displayed timestamps.
    profile_code, profile_version
        Exact adoption manifest for shared navigation.
    """

    organization_id: UUID
    edition_id: UUID
    organization_name: str
    series_name: str
    edition_name: str
    time_zone: str
    profile_code: str
    profile_version: int


def knowledge_workspace_reference(
    *, organization_id: UUID, edition_id: UUID
) -> KnowledgeWorkspaceReference | None:
    """Resolve same-parent labels after the caller's independent task admission.

    Parameters
    ----------
    organization_id : UUID
        Exact organization already admitted by Knowledge.
    edition_id : UUID
        Exact edition already admitted by Knowledge.

    Returns
    -------
    KnowledgeWorkspaceReference | None
        Complete current scope labels, or no coherent scope. The caller must
        reauthorize and repeat this reference before disclosing rendered bytes.
    """
    if any(
        not isinstance(value, UUID) or value.int == 0
        for value in (organization_id, edition_id)
    ):
        return None
    row = (
        EventEdition.objects.filter(
            Q(adoption_profile_code="guidance_only", adoption_profile_version=1)
            | Q(
                adoption_profile_code="announcements_guidance",
                adoption_profile_version=1,
            ),
            id=edition_id,
            organization_id=organization_id,
            series__organization_id=organization_id,
        )
        .values_list(
            "organization__name",
            "series__name",
            "name",
            "time_zone",
            "adoption_profile_code",
            "adoption_profile_version",
        )
        .first()
    )
    if row is None:
        return None
    return KnowledgeWorkspaceReference(organization_id, edition_id, *row)
