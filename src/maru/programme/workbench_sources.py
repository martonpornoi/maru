"""Audited, independently ceilinged source choices for item decisions."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from django.db.models import Exists, OuterRef

from .authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    ProgrammeAuthorizer,
    authorize_programme_scope,
)
from .catalogs import (
    MAX_PROGRAMME_PUBLIC_RENDITIONS,
    PROGRAMME_DELIVERY_REVISION_SOURCE,
    PROGRAMME_PUBLIC_RENDITION_SOURCE,
    PROGRAMME_WORKING_REVISION_SOURCE,
)
from .inputs import require_uuid
from .models import (
    ProgrammeDeliveryRevision,
    ProgrammeItem,
    ProgrammePublicRendition,
    ProgrammePublicRenditionWithdrawal,
    ProgrammeWorkingRevision,
)
from .queries import ProgrammeQueryUnavailableError, _authorized_query

if TYPE_CHECKING:
    from uuid import UUID

    from django.db.models import Manager

    from .workbench_queries import ProgrammeWorkbenchRequest

SOURCE_READS = MappingProxyType(
    {
        "working": (
            "programme.view_private",
            frozenset({"item_summaries", "working_information"}),
        ),
        "delivery": ("programme.view_delivery", frozenset({"delivery_information"})),
        "public-copy": (
            "programme.view_public_copy",
            frozenset({"latest_public_rendition"}),
        ),
    }
)


@dataclass(frozen=True, slots=True)
class ProgrammeEvidenceSourceChoice:
    """Name one exact source without copying private text into a readiness form.

    Attributes
    ----------
    code
        Closed registered source type, not client-declared permission.
    object_id
        Exact retained source object.
    version
        Source-owned sequence or rendition number.
    item_version
        Item dependency version retained by the source.
    label
        Code-owned human label; no source body or historical rationale.
    """

    code: str
    object_id: UUID
    version: int
    item_version: int
    label: str

    @property
    def key(self) -> str:
        """Return the exact closed selection value, never a permission token.

        Returns
        -------
        str
            Source type, object and immutable version joined for form selection.
        """
        return f"{self.code}|{self.object_id}|{self.version}"


@dataclass(frozen=True, slots=True)
class ProgrammeWithdrawalChoice:
    """Identify one retained, not-yet-withdrawn rendition under history authority.

    Attributes
    ----------
    rendition_id
        Exact withdrawal target, never an implicit latest selection.
    number
        Retained rendition number for a readable choice.
    title
        Historical reviewed title, not a claim of current publication.
    """

    rendition_id: UUID
    number: int
    title: str


def _lock_item(
    scope: ProgrammeWorkbenchRequest,
    item_id: UUID,
    capability: str,
    fields: frozenset[str],
    authorizer: ProgrammeAuthorizer,
) -> None:
    authorize_programme_scope(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        capability_code=capability,
        requested_fields=fields,
        authorizer=authorizer,
        lock=True,
    )
    if not ProgrammeItem.objects.filter(
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        id=item_id,
    ).exists():
        raise ProgrammeQueryUnavailableError


def load_programme_evidence_source(
    scope: ProgrammeWorkbenchRequest,
    *,
    item_id: UUID,
    layer: str,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeEvidenceSourceChoice | None:
    """Offer the exact latest independently readable source for a readiness decision.

    Parameters
    ----------
    scope : ProgrammeWorkbenchRequest
        Trusted exact scope and read-audit correlation.
    item_id : UUID
        Exact Programme item, never another edition's source.
    layer : str
        Closed working, delivery or public-copy source layer.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Real policy or the existing sealed isolated-test substitute.

    Returns
    -------
    ProgrammeEvidenceSourceChoice | None
        Minimized source reference, or no current optional source. Withdrawal of
        the latest public rendition never offers an older one as current.

    Raises
    ------
    ValueError
        If the requested source layer is not registered.

    Notes
    -----
    Owner authorization propagates non-disclosing denial. The guarded loader
    propagates ProgrammeQueryUnavailableError for absent item/working evidence.
    Source compatibility and freshness are still enforced by the evidence command.
    """
    item_id = require_uuid(item_id, field="item_id")
    if layer not in SOURCE_READS:
        raise ValueError("Choose a registered Programme source layer.")
    capability, fields = SOURCE_READS[layer]
    definitions: dict[
        str,
        tuple[
            Manager[ProgrammeWorkingRevision]
            | Manager[ProgrammeDeliveryRevision]
            | Manager[ProgrammePublicRendition],
            str,
            str,
            str,
            str,
        ],
    ] = {
        "working": (
            ProgrammeWorkingRevision.objects,
            "sequence",
            "item_version",
            PROGRAMME_WORKING_REVISION_SOURCE,
            "Working revision",
        ),
        "delivery": (
            ProgrammeDeliveryRevision.objects,
            "sequence",
            "item_version",
            PROGRAMME_DELIVERY_REVISION_SOURCE,
            "Delivery revision",
        ),
        "public-copy": (
            ProgrammePublicRendition.objects,
            "rendition_number",
            "source_item_version",
            PROGRAMME_PUBLIC_RENDITION_SOURCE,
            "Reviewed public rendition",
        ),
    }
    manager, number, source_version, code, label = definitions[layer]

    def load() -> ProgrammeEvidenceSourceChoice | None:
        _lock_item(scope, item_id, capability, fields, authorizer)
        row = (
            manager.filter(
                organization_id=scope.organization_id,
                edition_id=scope.edition_id,
                item_id=item_id,
            )
            .order_by(f"-{number}", "-id")
            .values("id", number, source_version)
            .first()
        )
        if row is None:
            if layer == "working":
                raise ProgrammeQueryUnavailableError
            return None
        if (
            layer == "public-copy"
            and ProgrammePublicRenditionWithdrawal.objects.filter(
                organization_id=scope.organization_id,
                edition_id=scope.edition_id,
                rendition_id=row["id"],
            ).exists()
        ):
            return None
        return ProgrammeEvidenceSourceChoice(
            code,
            row["id"],
            row[number],
            row[source_version],
            f"{label} {row[number]} (item source version {row[source_version]})",
        )

    return _authorized_query(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        capability_code=capability,
        requested_fields=fields,
        operation="programme.query.workbench_evidence_source",
        loader=load,
        target_type="programme.item",
        target_id=item_id,
        target_count=lambda result: int(result is not None),
        reason=f"Select exact {label.lower()} evidence for Programme readiness",
        correlation_id=scope.correlation_id,
        source_channel="programme-workbench",
        authorizer=authorizer,
    )


def list_programme_withdrawal_choices(
    scope: ProgrammeWorkbenchRequest,
    *,
    item_id: UUID,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> tuple[ProgrammeWithdrawalChoice, ...]:
    """Read complete retained withdrawal targets without inferring current publication.

    Parameters
    ----------
    scope : ProgrammeWorkbenchRequest
        Trusted exact scope and mandatory read-audit attribution.
    item_id : UUID
        Exact retained item; retirement does not prevent privacy withdrawal.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Real policy or the existing sealed isolated-test substitute.

    Returns
    -------
    tuple[ProgrammeWithdrawalChoice, ...]
        Complete bounded not-yet-withdrawn historical choices, newest first.

    Notes
    -----
    The guarded loader propagates ProgrammeQueryUnavailableError for missing
    item evidence or overflow, rather than returning partial choices.
    """
    item_id = require_uuid(item_id, field="item_id")
    fields = frozenset({"public_copy_review_history"})

    def load() -> tuple[ProgrammeWithdrawalChoice, ...]:
        _lock_item(scope, item_id, "programme.view_private", fields, authorizer)
        rows = tuple(
            ProgrammePublicRendition.objects.filter(
                organization_id=scope.organization_id,
                edition_id=scope.edition_id,
                item_id=item_id,
            )
            .order_by("-rendition_number", "-id")
            .annotate(
                withdrawn=Exists(
                    ProgrammePublicRenditionWithdrawal.objects.filter(
                        organization_id=scope.organization_id,
                        edition_id=scope.edition_id,
                        rendition_id=OuterRef("pk"),
                    )
                )
            )
            .values("id", "rendition_number", "public_title", "withdrawn")[
                : MAX_PROGRAMME_PUBLIC_RENDITIONS + 1
            ]
        )
        if len(rows) > MAX_PROGRAMME_PUBLIC_RENDITIONS:
            raise ProgrammeQueryUnavailableError
        return tuple(
            ProgrammeWithdrawalChoice(
                row["id"], row["rendition_number"], row["public_title"]
            )
            for row in rows
            if not row["withdrawn"]
        )

    return _authorized_query(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        capability_code="programme.view_private",
        requested_fields=fields,
        operation="programme.query.workbench_withdrawal_choices",
        loader=load,
        target_type="programme.item",
        target_id=item_id,
        target_count=len,
        reason="Select exact retained public copy for disclosure withdrawal",
        correlation_id=scope.correlation_id,
        source_channel="programme-workbench",
        authorizer=authorizer,
    )
