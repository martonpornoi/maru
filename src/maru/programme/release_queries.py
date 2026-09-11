"""Current release facts without private copy or publication authority."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from django.db.models import Exists, OuterRef, Q, Subquery

from maru.events.adoption import profile_allows_adapter
from maru.events.queries import edition_adoption_profile_reference
from maru.identity.queries import (
    MAX_PERSON_REFERENCE_BATCH,
    resolve_active_verified_person_references,
)
from maru.workforce.programme_references import lock_programme_staffing_scope

from .adoption import PROGRAMME_RELEASE_SOURCE_ADAPTER
from .authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_VIEW_PUBLIC_COPY,
    PROGRAMME_VIEW_READINESS,
    PROGRAMME_VIEW_SCHEDULING_DEPENDENCIES,
    ProgrammeAuthorizationDeniedError,
    ProgrammeAuthorizer,
    authorize_programme_scope,
)
from .catalogs import ProgrammeReadinessConcern
from .inputs import canonical_digest, require_uuid
from .models import (
    ProgrammeHostRelationship,
    ProgrammeItem,
    ProgrammePublicRendition,
    ProgrammePublicRenditionWithdrawal,
    ProgrammeWorkingRevision,
)
from .queries import (
    ProgrammeQueryUnavailableError,
    ProgrammeReadinessConcernProjection,
    _authorized_query,
    load_programme_readiness,
)
from .scheduling_queries import (
    MAX_SCHEDULING_SOURCE_HOSTS,
    MAX_SCHEDULING_SOURCE_ITEMS,
    _identifiers,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from .placement_queries import ProgrammePlacementReadRequest


@dataclass(frozen=True, slots=True)
class _CopyMetadata:
    id: UUID
    item_id: UUID
    source_working_revision_id: UUID
    reviewed_by_id: UUID
    reviewer_authored: bool
    current_working_id: UUID | None
    withdrawn: bool


@dataclass(frozen=True, slots=True)
class ProgrammeReleaseHostReference:
    """Opaque exact selected host reference for a separately authorized conflict owner.

    Attributes
    ----------
    host_id
        Selected retained Programme purpose, not any proposal contributor.
    item_id
        Exact owning item already admitted for this release purpose.
    account_id
        Ephemeral opaque Identity reference; never persist in Scheduling findings.
    """

    host_id: UUID
    item_id: UUID
    account_id: UUID


@dataclass(frozen=True, slots=True)
class ProgrammeReleasePeople:
    """Complete canonical lock closure and exact selected host identity references.

    Attributes
    ----------
    account_ids
        Actor, current selected-item hosts and latest public-copy reviewers; includes
        inactive references so their absence cannot masquerade as availability.
    selected_hosts
        Exactly requested purpose/account mappings under an independent field ceiling.
    source_account_ids
        Complete host/reviewer identities excluding only caller-only locking needs.
        A caller who also owns a source remains included for source freshness.
    """

    account_ids: tuple[UUID, ...]
    selected_hosts: tuple[ProgrammeReleaseHostReference, ...]
    source_account_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class ProgrammeReleaseItemSource:
    """Complete seven-concern readiness and current independent-copy consequence.

    Attributes
    ----------
    item_id
        Exact retained Programme item.
    item_version
        Current Programme command version.
    lifecycle
        Current active or retained retired state.
    readiness
        Exactly the complete closed concern set, including unavailable/required states.
    public_copy_state
        Satisfied only for current working-copy source with an independent current
        reviewer; missing, stale and non-independent copy remain distinct failures.
    public_rendition_id
        Exact current approved-copy identity, or None when none exists.
    evidence_digest
        Complete minimized owner-version and consequence fingerprint without text.
    """

    item_id: UUID
    item_version: int
    lifecycle: str
    readiness: tuple[ProgrammeReadinessConcernProjection, ...]
    public_copy_state: str
    public_rendition_id: UUID | None
    evidence_digest: str


def _admit(
    request: ProgrammePlacementReadRequest, authorizer: ProgrammeAuthorizer
) -> None:
    for capability, fields in (
        (PROGRAMME_VIEW_READINESS, frozenset({"readiness_summary"})),
        (PROGRAMME_VIEW_PUBLIC_COPY, frozenset({"release_copy_consequences"})),
        (
            PROGRAMME_VIEW_SCHEDULING_DEPENDENCIES,
            frozenset({"release_person_references"}),
        ),
    ):
        authorize_programme_scope(
            actor_id=request.actor_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            capability_code=capability,
            requested_fields=fields,
            authorizer=authorizer,
        )
    profile = edition_adoption_profile_reference(
        organization_id=request.organization_id, edition_id=request.edition_id
    )
    if profile is None or not profile_allows_adapter(
        profile.code, profile.version, PROGRAMME_RELEASE_SOURCE_ADAPTER
    ):
        raise ProgrammeAuthorizationDeniedError


def _items(
    request: ProgrammePlacementReadRequest, identifiers: tuple[UUID, ...]
) -> tuple[ProgrammeItem, ...]:
    rows = tuple(
        ProgrammeItem.objects.filter(
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            id__in=identifiers,
        )
        .order_by("id")
        .only("id", "aggregate_version", "lifecycle")
    )
    if len(rows) != len(identifiers):
        raise ProgrammeQueryUnavailableError
    return rows


def _renditions(
    request: ProgrammePlacementReadRequest, identifiers: tuple[UUID, ...]
) -> tuple[_CopyMetadata, ...]:
    latest = (
        ProgrammePublicRendition.objects.filter(
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            item_id=OuterRef("item_id"),
        )
        .order_by("-rendition_number")
        .values("id")[:1]
    )
    authorship = ProgrammeWorkingRevision.objects.filter(
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        item_id=OuterRef("item_id"),
        actor_id=OuterRef("reviewed_by_id"),
    )
    current_working = (
        ProgrammeWorkingRevision.objects.filter(
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            item_id=OuterRef("item_id"),
        )
        .order_by("-sequence")
        .values("id")[:1]
    )
    rows = (
        ProgrammePublicRendition.objects.filter(
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            item_id__in=identifiers,
            id=Subquery(latest),
        )
        .annotate(
            reviewer_authored=Exists(authorship),
            current_working_id=Subquery(current_working),
            withdrawn=Exists(
                ProgrammePublicRenditionWithdrawal.objects.filter(
                    rendition_id=OuterRef("id"),
                    organization_id=request.organization_id,
                    edition_id=request.edition_id,
                    item_id=OuterRef("item_id"),
                )
            ),
        )
        .order_by("item_id")
        .values(
            "id",
            "item_id",
            "source_working_revision_id",
            "reviewed_by_id",
            "reviewer_authored",
            "current_working_id",
            "withdrawn",
        )
    )
    return tuple(_CopyMetadata(**row) for row in rows)


def _people(
    request: ProgrammePlacementReadRequest,
    item_ids: tuple[UUID, ...],
    host_ids: tuple[UUID, ...],
    renditions: tuple[_CopyMetadata, ...],
) -> ProgrammeReleasePeople:
    hosts = tuple(
        ProgrammeHostRelationship.objects.filter(
            Q(state__in=("invited", "confirmed")) | Q(id__in=host_ids),
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            item_id__in=item_ids,
        )
        .order_by("id")
        .only("id", "item_id", "account_id")[: MAX_SCHEDULING_SOURCE_HOSTS + 1]
    )
    selected = tuple(
        ProgrammeReleaseHostReference(row.id, row.item_id, row.account_id)
        for row in hosts
        if row.id in host_ids
    )
    source_accounts = tuple(
        sorted(
            {
                *(row.account_id for row in hosts),
                *(row.reviewed_by_id for row in renditions),
            },
            key=str,
        )
    )
    accounts = tuple(sorted({request.actor_id, *source_accounts}, key=str))
    if (
        len(hosts) > MAX_SCHEDULING_SOURCE_HOSTS
        or len(selected) != len(host_ids)
        or len(accounts) > MAX_PERSON_REFERENCE_BATCH
    ):
        raise ProgrammeQueryUnavailableError
    return ProgrammeReleasePeople(accounts, selected, source_accounts)


def _read[ResultT](
    request: ProgrammePlacementReadRequest,
    item_ids: tuple[UUID, ...],
    host_ids: tuple[UUID, ...],
    authorizer: ProgrammeAuthorizer,
    loader: Callable[[tuple[UUID, ...], tuple[UUID, ...]], ResultT],
    *,
    operation: str,
) -> ResultT:
    for field in ("actor_id", "organization_id", "edition_id", "correlation_id"):
        require_uuid(getattr(request, field), field=field)
    _admit(request, authorizer)
    items = _identifiers(item_ids, MAX_SCHEDULING_SOURCE_ITEMS)
    hosts = _identifiers(host_ids, MAX_SCHEDULING_SOURCE_HOSTS)
    if not items:
        raise ProgrammeQueryUnavailableError

    def load() -> ResultT:
        lock_programme_staffing_scope(
            organization_id=request.organization_id, edition_id=request.edition_id
        )
        _admit(request, authorizer)
        result = loader(items, hosts)
        _admit(request, authorizer)
        return result

    return _authorized_query(
        actor_id=request.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        capability_code=PROGRAMME_VIEW_SCHEDULING_DEPENDENCIES,
        requested_fields=frozenset({"release_person_references"}),
        operation=operation,
        loader=load,
        target_type="programme.scope",
        target_id=request.edition_id,
        target_count=lambda _: len(items),
        reason="Complete Programme release source",
        correlation_id=request.correlation_id,
        source_channel=request.source_channel,
        authorizer=authorizer,
    )


def collect_programme_release_person_references(
    request: ProgrammePlacementReadRequest,
    *,
    item_ids: tuple[UUID, ...],
    host_ids: tuple[UUID, ...],
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeReleasePeople:
    """Resolve complete owner person closure before any compositor person lock.

    Parameters
    ----------
    request : ProgrammePlacementReadRequest
        Trusted exact-scope caller and sensitive-read attribution.
    item_ids : tuple[UUID, ...]
        Complete candidate item selection; absence is not a usable source.
    host_ids : tuple[UUID, ...]
        Complete explicitly selected host purposes, possibly empty.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Independent current Programme readiness, copy and person-reference fields.

    Returns
    -------
    ProgrammeReleasePeople
        Complete bounded ephemeral opaque references, not names or private calendars.

    Notes
    -----
    Holds shared parent locks in the caller's transaction but takes no actor-only
    person lock. A cross-owner compositor must combine this set with Workforce's
    complete selected person set, sort globally, then lock through Identity.
    Current profiles omit the exact source adapter. References are not permissions.
    """

    def load(
        items: tuple[UUID, ...], hosts: tuple[UUID, ...]
    ) -> ProgrammeReleasePeople:
        _items(request, items)
        return _people(request, items, hosts, _renditions(request, items))

    return _read(
        request,
        item_ids,
        host_ids,
        authorizer,
        load,
        operation="programme.release.person_references",
    )


def load_programme_release_item_sources(
    request: ProgrammePlacementReadRequest,
    *,
    item_ids: tuple[UUID, ...],
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> tuple[ProgrammeReleaseItemSource, ...]:
    """Collect complete readiness and independently reviewed current-copy consequences.

    Parameters
    ----------
    request : ProgrammePlacementReadRequest
        Trusted actor, tenant, edition and mandatory audit correlation.
    item_ids : tuple[UUID, ...]
        Complete exact selected items, with no partial authorized filtering.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Independent current owner fields and exact release adapter admission.

    Returns
    -------
    tuple[ProgrammeReleaseItemSource, ...]
        Complete facts without working copy, public text or private rationale.

    Notes
    -----
    Collects this owner's complete person closure before taking any person lock.
    A cross-owner caller must first prelock its complete union in canonical order.
    Retained authorship disqualifies self-review even if the author is now inactive.
    No old rendition is rewritten, and only the current rendition is evaluated.
    Missing concern membership is unavailable, not an abbreviated success.
    """

    def load(
        identifiers: tuple[UUID, ...], _hosts: tuple[UUID, ...]
    ) -> tuple[ProgrammeReleaseItemSource, ...]:
        items = _items(request, identifiers)
        renditions = _renditions(request, identifiers)
        people = _people(request, identifiers, (), renditions)
        current = resolve_active_verified_person_references(
            account_ids=people.account_ids, lock=True
        )
        if current is None:
            raise ProgrammeQueryUnavailableError
        verified = {row.account_id for row in current}
        if request.actor_id not in verified:
            raise ProgrammeAuthorizationDeniedError
        by_item = {row.item_id: row for row in renditions}
        results = []
        for item in items:
            readiness = load_programme_readiness(
                actor_id=request.actor_id,
                organization_id=request.organization_id,
                edition_id=request.edition_id,
                item_id=item.id,
                reason="Current release-readiness source",
                correlation_id=request.correlation_id,
                source_channel=request.source_channel,
                authorizer=authorizer,
            )
            if {row.concern for row in readiness} != {
                concern.value for concern in ProgrammeReadinessConcern
            }:
                raise ProgrammeQueryUnavailableError
            rendition = by_item.get(item.id)
            if rendition is None:
                state = "unavailable"
            elif rendition.withdrawn:
                state = "withdrawn"
            elif rendition.reviewer_authored:
                state = "blocked"
            elif rendition.source_working_revision_id != rendition.current_working_id:
                state = "stale"
            elif rendition.reviewed_by_id not in verified:
                state = "unavailable"
            else:
                state = "satisfied"
            rendition_id = rendition.id if rendition else None
            digest = canonical_digest(
                {
                    "schema": "programme-release-item@1",
                    "organization_id": request.organization_id,
                    "edition_id": request.edition_id,
                    "item_id": item.id,
                    "item_version": item.aggregate_version,
                    "lifecycle": item.lifecycle,
                    "readiness": tuple(asdict(row) for row in readiness),
                    "public_rendition_id": rendition_id,
                    "copy_state": state,
                }
            )
            results.append(
                ProgrammeReleaseItemSource(
                    item.id,
                    item.aggregate_version,
                    item.lifecycle,
                    readiness,
                    state,
                    rendition_id,
                    digest,
                )
            )
        return tuple(results)

    return _read(
        request,
        item_ids,
        (),
        authorizer,
        load,
        operation="programme.release.item_sources",
    )
