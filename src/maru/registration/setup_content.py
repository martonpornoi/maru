"""Canonical Page 10 request and registration-definition digests."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(UTC)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def canonical_digest(payload: Mapping[str, object]) -> str:
    """Return deterministic lower-case SHA-256 over canonical UTF-8 JSON.

    Parameters
    ----------
    payload : Mapping[str, object]
        The untrusted payload to validate before domain use.

    Returns
    -------
    str
        The normalized text for canonical digest.
    """
    encoded = json.dumps(
        dict(payload),
        default=_json_default,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def section_payload(section: Any) -> dict[str, object]:
    """Return section payload.

    Parameters
    ----------
    section : Any
        The section evaluated while section payload.

    Returns
    -------
    dict[str, object]
        A disclosure-safe mapping for section payload.
    """
    return {
        "key": section.key,
        "title": section.title,
        "description": section.description,
        "position": section.position,
    }


def question_payload(
    question: Any,
    *,
    section_key: str | None,
) -> dict[str, object]:
    """Return question payload.

    Parameters
    ----------
    question : Any
        The versioned question defining type, bounds, and ownership.
    section_key : str | None
        The stable section key used to authenticate or deduplicate the operation.

    Returns
    -------
    dict[str, object]
        A disclosure-safe mapping for question payload.
    """
    return {
        "key": question.key,
        "label": question.label,
        "help_text": question.help_text,
        "field_type": question.field_type,
        "required": question.required,
        "position": question.position,
        "options": list(question.options),
        "purpose": question.purpose,
        "visibility": question.visibility,
        "classification": question.classification,
        "condition_question_key": question.condition_question_key,
        "condition_value": question.condition_value,
        "section_key": section_key,
    }


def product_payload(product: Any, *, include_status: bool) -> dict[str, object]:
    """Return product payload.

    Parameters
    ----------
    product : Any
        The edition-owned product whose policy or capacity is evaluated.
    include_status : bool
        Whether to include status.

    Returns
    -------
    dict[str, object]
        A disclosure-safe mapping for product payload.
    """
    payload: dict[str, object] = {
        "code": product.code,
        "name": product.name,
        "description": product.description,
        "price_minor": product.price_minor,
        "capacity": product.capacity,
        "position": product.position,
        "entitlement_code": product.entitlement_code,
        "entitlement_name": product.entitlement_name,
        "sales_open_at": product.sales_open_at,
        "sales_close_at": product.sales_close_at,
        "required_capacity_codes": list(product.required_capacity_codes),
        "eligibility_explanation": product.eligibility_explanation,
        "waitlist_enabled": product.waitlist_enabled,
        "payment_window_minutes": product.payment_window_minutes,
    }
    if product.capacity_ceiling is not None:
        payload["capacity_ceiling"] = product.capacity_ceiling
    if include_status:
        payload["status"] = product.status
    return payload


def minor_policy_payload(policy: Any | None) -> dict[str, object] | None:
    """Return minor policy payload.

    Parameters
    ----------
    policy : Any | None
        The closed policy definition governing the requested decision.

    Returns
    -------
    dict[str, object] | None
        A disclosure-safe mapping for minor policy payload.
    """
    if policy is None:
        return None
    return {
        "enabled": policy.enabled,
        "minor_age_threshold": policy.minor_age_threshold,
        "guardian_notice_version": policy.guardian_notice_version,
        "jurisdiction_code": policy.jurisdiction_code,
        "review_reference": policy.review_reference,
        "reviewed_by_id": policy.reviewed_by_id,
        "reviewed_at": policy.reviewed_at,
    }


def configuration_source_binding_digest(configuration: Any) -> str:
    """Bind one configuration to its immutable setup-start provenance tuple.

    Parameters
    ----------
    configuration : Any
        The versioned configuration governing validation and behavior.

    Returns
    -------
    str
        The normalized text for configuration source binding digest.
    """
    return canonical_digest(
        {
            "contract": "maru.registration-configuration-source-binding.v1",
            "configuration_id": configuration.id,
            "organization_id": configuration.organization_id,
            "edition_id": configuration.edition_id,
            "origin": configuration.origin,
            "source_template_id": configuration.source_template_id,
            "source_edition_id": configuration.source_edition_id,
            "source_configuration_id": configuration.source_configuration_id,
            "source_version": configuration.source_version,
            "source_content_digest": configuration.source_content_digest,
            "source_imported_at": configuration.source_imported_at,
            "source_imported_by_id": configuration.source_imported_by_id,
        }
    )


def profile_extension_payload(field: Any) -> dict[str, object]:
    """Project definition metadata only; attendee values never enter setup evidence.

    Parameters
    ----------
    field : Any
        The model or form field whose contract is being evaluated.

    Returns
    -------
    dict[str, object]
        A mapping containing the resolved profile extension payload data.
    """
    return {
        "key": field.key,
        "version": field.version,
        "supersedes_id": field.supersedes_id,
        "label": field.label,
        "help_text": field.help_text,
        "field_type": field.field_type,
        "options": list(field.options),
        "purpose": field.purpose,
        "classification": field.classification,
        "attendee_visible": field.attendee_visible,
        "audience_policy": field.audience_policy,
        "audience_department_id": field.audience_department_id,
        "writer_policy": field.writer_policy,
        "required": field.required,
        "position": field.position,
        "source_template_id": field.source_template_id,
        "source_prior_edition_id": field.source_prior_edition_id,
        "review_status": field.review_status,
        "status": field.status,
    }


def template_content_digest(
    *,
    template: Any,
    sections: Sequence[Any],
    questions: Sequence[Any],
    products: Sequence[Any],
) -> str:
    """Return template content digest.

    Parameters
    ----------
    template : Any
        The immutable starter or template used as the copy source.
    sections : Sequence[Any]
        The ordered sections included in the rendered or persisted definition.
    questions : Sequence[Any]
        The ordered questions to process.
    products : Sequence[Any]
        The products evaluated while template content digest.

    Returns
    -------
    str
        The normalized text for template content digest.
    """
    section_keys = {section.id: section.key for section in sections}
    return canonical_digest(
        {
            "contract": "maru.registration-template-content.v1",
            "code": template.code,
            "name": template.name,
            "description": template.description,
            "version": template.version,
            "sections": [section_payload(section) for section in sections],
            "questions": [
                question_payload(
                    question,
                    section_key=section_keys.get(question.section_id),
                )
                for question in questions
            ],
            "products": [
                product_payload(product, include_status=False) for product in products
            ],
        }
    )


def configuration_content_digest(
    *,
    name: str,
    schema_version: int,
    opens_at: datetime,
    closes_at: datetime,
    capacity: int,
    currency: str,
    minimum_age: int,
    default_payment_window_minutes: int,
    waitlist_enabled: bool,
    automatic_waitlist_promotion: bool,
    sections: Sequence[Any],
    questions: Sequence[Any],
    products: Sequence[Any],
    minor_policy: Any | None,
    capacity_ceiling: int | None = None,
) -> str:
    """Return configuration content digest.

    Parameters
    ----------
    name : str
        The human-readable name.
    schema_version : int
        The expected schema version used to reject stale updates.
    opens_at : datetime
        The time at which the window opens.
    closes_at : datetime
        The time at which the window closes.
    capacity : int
        The capacity applied by the operation.
    currency : str
        The ISO currency code.
    minimum_age : int
        The minimum age evaluated while configuration content digest.
    default_payment_window_minutes : int
        The default payment window minutes evaluated while configuration content digest.
    waitlist_enabled : bool
        Whether wait-list enrollment is enabled.
    automatic_waitlist_promotion : bool
        The automatic waitlist promotion evaluated while configuration content digest.
    sections : Sequence[Any]
        The ordered sections included in the rendered or persisted definition.
    questions : Sequence[Any]
        The ordered questions to process.
    products : Sequence[Any]
        The products evaluated while configuration content digest.
    minor_policy : Any | None
        The closed minor policy governing validation or disclosure.
    capacity_ceiling : int | None, default=None
        The hard upper capacity bound.

    Returns
    -------
    str
        The normalized text for configuration content digest.
    """
    section_keys = {section.id: section.key for section in sections}
    payload: dict[str, object] = {
        "contract": "maru.registration-configuration-content.v1",
        "name": name,
        "schema_version": schema_version,
        "opens_at": opens_at,
        "closes_at": closes_at,
        "capacity": capacity,
        "currency": currency,
        "minimum_age": minimum_age,
        "default_payment_window_minutes": default_payment_window_minutes,
        "waitlist_enabled": waitlist_enabled,
        "automatic_waitlist_promotion": automatic_waitlist_promotion,
        "sections": [section_payload(section) for section in sections],
        "questions": [
            question_payload(
                question,
                section_key=section_keys.get(question.section_id),
            )
            for question in questions
        ],
        "products": [
            product_payload(product, include_status=True) for product in products
        ],
        "minor_policy": minor_policy_payload(minor_policy),
    }
    if capacity_ceiling is not None:
        payload["capacity_ceiling"] = capacity_ceiling
    return canonical_digest(payload)


def target_content_digest(*, kind: str, payload: Mapping[str, object]) -> str:
    """Return target content digest.

    Parameters
    ----------
    kind : str
        The closed kind code.
    payload : Mapping[str, object]
        The validated payload to process.

    Returns
    -------
    str
        The normalized text for target content digest.
    """
    return canonical_digest(
        {
            "contract": "maru.registration-setup-target.v1",
            "kind": kind,
            "content": dict(payload),
        }
    )
