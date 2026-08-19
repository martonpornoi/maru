"""Code-owned, immutable starter blueprints for edition registration setup.

The catalog is not tenant data.  A starter is useful only after an authorized
organizer explicitly copies one exact version into an edition-owned draft.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from maru.registration.setup_content import (
    canonical_digest,
    product_payload,
    section_payload,
)


@dataclass(frozen=True, slots=True)
class StarterSection:
    id: UUID
    key: str
    title: str
    description: str
    position: int


@dataclass(frozen=True, slots=True)
class StarterProduct:
    id: UUID
    code: str
    name: str
    description: str
    price_minor: int
    capacity: int
    capacity_ceiling: int | None
    position: int
    entitlement_code: str
    entitlement_name: str
    sales_open_at: None = None
    sales_close_at: None = None
    required_capacity_codes: tuple[str, ...] = ()
    eligibility_explanation: str = ""
    waitlist_enabled: bool = True
    payment_window_minutes: int | None = None
    status: str = "available"


@dataclass(frozen=True, slots=True)
class PlatformRegistrationStarter:
    source_id: UUID
    code: str
    version: int
    name: str
    description: str
    content_digest: str
    sections: tuple[StarterSection, ...]
    questions: tuple[object, ...]
    products: tuple[StarterProduct, ...]


def _catalog_id(*, code: str, version: int, row: str = "source") -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"https://maru.example/catalog/registration/{code}/v{version}/{row}",
    )


def _build_convention_starter() -> PlatformRegistrationStarter:
    code = "convention-registration"
    version = 1
    sections = (
        StarterSection(
            id=_catalog_id(code=code, version=version, row="section/questions"),
            key="convention-questions",
            title="Convention questions",
            description=(
                "Add only edition-specific questions that have a documented "
                "purpose, audience, and retention need."
            ),
            position=0,
        ),
    )
    products = (
        StarterProduct(
            id=_catalog_id(code=code, version=version, row="product/standard"),
            code="standard",
            name="Standard admission",
            description=(
                "Baseline attendee admission. Review price, capacity, sales "
                "window, eligibility, and entitlement before activation."
            ),
            price_minor=0,
            capacity=1_000,
            capacity_ceiling=1_000,
            position=0,
            entitlement_code="attendee",
            entitlement_name="Attendee",
            eligibility_explanation="Open to eligible convention attendees.",
        ),
    )
    digest = canonical_digest(
        {
            "contract": "maru.platform-registration-starter.v1",
            "code": code,
            "version": version,
            "name": "Convention registration baseline",
            "description": (
                "A minimized base for a typical convention registration with "
                "one editable general-admission product."
            ),
            "sections": [section_payload(section) for section in sections],
            "questions": [],
            "products": [
                product_payload(product, include_status=True) for product in products
            ],
        }
    )
    return PlatformRegistrationStarter(
        source_id=_catalog_id(code=code, version=version),
        code=code,
        version=version,
        name="Convention registration baseline",
        description=(
            "A minimized base for a typical convention registration with one "
            "editable general-admission product."
        ),
        content_digest=digest,
        sections=sections,
        questions=(),
        products=products,
    )


_STARTERS = (_build_convention_starter(),)

if len({item.source_id for item in _STARTERS}) != len(_STARTERS):  # pragma: no cover
    raise RuntimeError("Platform registration starter IDs must be unique.")
if len({(item.version, item.content_digest) for item in _STARTERS}) != len(_STARTERS):
    raise RuntimeError("Platform registration starter provenance must be unique.")


def platform_registration_starters() -> tuple[PlatformRegistrationStarter, ...]:
    """Return every retained catalog version in stable display order."""

    return tuple(sorted(_STARTERS, key=lambda item: (item.code, -item.version)))


def platform_registration_starter(
    source_id: UUID,
) -> PlatformRegistrationStarter | None:
    """Resolve one exact immutable version without label-based lookup."""

    return next((item for item in _STARTERS if item.source_id == source_id), None)


def platform_registration_starter_by_provenance(
    *, version: int, content_digest: str
) -> PlatformRegistrationStarter | None:
    """Resolve persisted provenance even after newer catalog versions exist."""

    return next(
        (
            item
            for item in _STARTERS
            if item.version == version and item.content_digest == content_digest
        ),
        None,
    )


__all__ = [
    "PlatformRegistrationStarter",
    "platform_registration_starter",
    "platform_registration_starter_by_provenance",
    "platform_registration_starters",
]
