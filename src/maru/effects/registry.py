"""Closed, versioned domain-event schema registry."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError

PayloadValidator = Callable[[dict[str, object]], None]
MAX_EVENT_PAYLOAD_TEXT_LENGTH = 240
MAX_EVENT_CODE_LENGTH = 80
MAX_WORKFORCE_AVAILABILITY_WINDOWS = 64


@dataclass(frozen=True, slots=True)
class EventDefinition:
    """Describe event definition.

    Attributes
    ----------
    name
        The human-readable name to normalize or persist.
    schema_version
        The expected schema version used to reject stale updates.
    description
        The human-readable description shown to authorized readers.
    validator
        The validator retained in this immutable projection.
    """

    name: str
    schema_version: int
    description: str
    validator: PayloadValidator


def _require_exact_string_fields(
    payload: dict[str, object],
    *,
    fields: frozenset[str],
) -> None:
    if set(payload) != fields:
        raise ValidationError(
            "Domain event payload fields do not match its registered schema.",
            code="invalid_domain_event_payload",
        )
    values = [payload[field] for field in fields]
    if any(not isinstance(value, str) or not value for value in values):
        raise ValidationError(
            "Domain event payload values must be non-empty strings.",
            code="invalid_domain_event_payload",
        )
    if any(
        isinstance(value, str) and len(value) > MAX_EVENT_PAYLOAD_TEXT_LENGTH
        for value in values
    ):
        raise ValidationError(
            "Domain event payload value is too long.",
            code="invalid_domain_event_payload",
        )


def _validate_edition_lifecycle_transitioned(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"from_state", "to_state"}),
    )


def _validate_edition_created(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset(
            {
                "aggregate_version",
                "adoption_profile_code",
                "adoption_profile_version",
                "lifecycle",
            }
        ),
    )


def _validate_edition_details_updated(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"aggregate_version", "changed_fields"}),
    )


def _validate_convention_series_created(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"availability", "profile_version"}),
    )


def _validate_convention_series_updated(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"availability", "changed_fields", "profile_version"}),
    )


def _validate_organization_representation_changed(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"action", "representation_code", "state"}),
    )
    expected_states = {
        "provisioned": "provisioning",
        "controller_invited": "invited",
        "controller_accepted": "accepted",
        "controller_declined": "declined",
        "controller_invitation_ended": "provisioning",
        "activated": "active",
        "controller_ended": "active",
        "representation_suspended": "suspended",
    }
    action = payload["action"]
    if (
        not isinstance(action, str)
        or payload["representation_code"] not in {"executive_board", "maru_operators"}
        or expected_states.get(action) != payload["state"]
    ):
        raise ValidationError(
            "Organization representation event values are not registered.",
            code="invalid_domain_event_payload",
        )


def _validate_effect_probe(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"probe"}),
    )


def _validate_capability_delegated(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"capability_code", "scope_level"}),
    )


def _validate_capability_authority_changed(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"capability_code", "scope_level"}),
    )


def _validate_role_bundle_version_created(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"role_code", "role_version"}),
    )


def _validate_role_assignment_changed(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"role_code", "role_version", "scope_level"}),
    )


def _validate_registration_configuration_changed(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"configuration_version", "source_kind"}),
    )


def _validate_registration_configuration_draft_changed(
    payload: dict[str, object],
) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"action", "configuration_version"}),
    )


def _validate_registration_template_published(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"template_code", "template_version"}),
    )


def _validate_registration_state_changed(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"from_state", "to_state", "reference"}),
    )


def _validate_registration_tier_replacement(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"registration_id", "target_product_id", "status"}),
    )


def _validate_registration_capacity_adjusted(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"scope", "target_id", "previous_capacity", "new_capacity"}),
    )


def _validate_registration_waitlist_batch(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"product_id", "requested_size", "offered_count"}),
    )


def _validate_registration_profile_changed(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"action", "reference"}),
    )


def _validate_registration_profile_extension_value_appended(
    payload: dict[str, object],
) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset(
            {
                "field_id",
                "field_version",
                "registration_id",
                "sequence",
                "writer_kind",
            }
        ),
    )
    try:
        UUID(str(payload["field_id"]))
        UUID(str(payload["registration_id"]))
    except (TypeError, ValueError) as error:
        raise ValidationError(
            "Profile-extension event identifiers must be UUIDs.",
            code="invalid_domain_event_payload",
        ) from error
    for field_name in ("field_version", "sequence"):
        value = payload[field_name]
        if not isinstance(value, str) or not (
            value.isascii() and value.isdecimal() and int(value) >= 1
        ):
            raise ValidationError(
                "Profile-extension event versions must be positive.",
                code="invalid_domain_event_payload",
            )
    if payload["writer_kind"] not in {"owner", "staff"}:
        raise ValidationError(
            "Profile-extension event writer kind is not registered.",
            code="invalid_domain_event_payload",
        )


def _validate_registration_media_reviewed(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"decision", "media_kind", "reference"}),
    )


def _validate_application_definition_changed(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"action", "definition_code", "definition_version"}),
    )
    if (
        not str(payload["definition_version"]).isdecimal()
        or int(str(payload["definition_version"])) < 1
    ):
        raise ValidationError(
            "Application definition versions must be positive.",
            code="invalid_domain_event_payload",
        )


def _validate_application_submission_changed(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"action", "state", "target_adapter_kind"}),
    )
    if payload["state"] not in {
        "draft",
        "submitted",
        "under_review",
        "changes_requested",
        "accepted",
        "rejected",
        "withdrawn",
    } or payload["target_adapter_kind"] not in {
        "merch_submission",
        "dj_set",
        "fursuit_dance_competition",
        "maid_cafe",
        "adult_fursuit_striptease",
        "volunteer",
        "feedback",
        "idea",
        "damage_report",
        "helper",
    }:
        raise ValidationError(
            "Application event values are not registered.",
            code="invalid_domain_event_payload",
        )


def _validate_application_programme_call_changed(
    payload: dict[str, object],
) -> None:
    from maru.applications.programme_events import (  # noqa: PLC0415
        validate_programme_call_changed_payload,
    )

    validate_programme_call_changed_payload(payload)


def _validate_application_programme_proposal_changed(
    payload: dict[str, object],
) -> None:
    from maru.applications.programme_events import (  # noqa: PLC0415
        validate_programme_proposal_changed_payload,
    )

    validate_programme_proposal_changed_payload(payload)


def _validate_programme_item_changed(payload: dict[str, object]) -> None:
    from maru.programme.events import (  # noqa: PLC0415
        validate_programme_item_changed_payload,
    )

    validate_programme_item_changed_payload(payload)


def _validate_charity_partner_changed(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"action", "lifecycle"}),
    )
    if payload["action"] not in {"created", "updated"} or payload["lifecycle"] not in {
        "draft",
        "active",
        "retired",
    }:
        raise ValidationError(
            "Charity partner event values are not registered.",
            code="invalid_domain_event_payload",
        )


def _validate_charity_media_changed(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"action", "kind", "review_status"}),
    )
    if (
        payload["action"] not in {"added", "approve", "withdraw"}
        or payload["kind"] not in {"logo", "photo"}
        or payload["review_status"] not in {"pending", "approved", "withdrawn"}
    ):
        raise ValidationError(
            "Charity media event values are not registered.",
            code="invalid_domain_event_payload",
        )


def _validate_charity_selection_changed(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"action", "status", "publication_state"}),
    )
    if (
        payload["action"]
        not in {
            "proposed",
            "submitted",
            "confirmed",
            "rejected",
            "commented",
            "published",
            "unpublished",
        }
        or payload["status"] not in {"proposed", "submitted", "confirmed", "rejected"}
        or payload["publication_state"] not in {"unpublished", "published"}
        or (
            payload["publication_state"] == "published"
            and payload["status"] != "confirmed"
        )
    ):
        raise ValidationError(
            "Charity selection event values are not registered.",
            code="invalid_domain_event_payload",
        )


def _validate_venue_record_changed(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"action", "record_type", "record_id"}),
    )
    try:
        UUID(str(payload["record_id"]))
    except (TypeError, ValueError) as error:
        raise ValidationError(
            "Venue event record must be a UUID.",
            code="invalid_domain_event_payload",
        ) from error
    if payload["record_type"] not in {
        "venues.property",
        "venues.space",
        "venues.space_combination",
        "venues.property_media",
        "venues.layout",
        "venues.accommodation_room_type",
        "venues.accommodation_night_inventory",
        "venues.edition_selection",
        "venues.edition_space",
        "venues.booking",
    } or payload["action"] not in {
        "created",
        "updated",
        "catalog_path_created",
        "submitted",
        "approved",
        "set",
        "selected",
        "availability_replaced",
        "rescheduled",
        "published",
        "withdrawn",
        "cancelled",
    }:
        raise ValidationError(
            "Venue event values are not registered.",
            code="invalid_domain_event_payload",
        )


_LOGISTICS_RECORD_TYPES = frozenset(
    {
        "logistics.party",
        "logistics.restricted_address",
        "logistics.node",
        "logistics.asset",
        "logistics.stock_lot",
        "logistics.physical_key",
        "logistics.label",
        "logistics.agreement",
        "logistics.kit",
        "logistics.manifest",
        "logistics.offline_batch",
        "logistics.equipment_offer",
        "logistics.event",
    }
)
_LOGISTICS_RECORD_ACTIONS = frozenset(
    {
        "created",
        "registered",
        "recorded",
        "responsibility_assigned",
        "line_added",
        "seal",
        "complete",
        "cancel_draft",
        "cancel_sealed",
        "applied",
        "review",
        "submitted",
        "withdrawn",
        "accepted",
        "rejected",
        "receive",
        "pack",
        "unpack",
        "move",
        "load",
        "unload",
        "handover",
        "count",
        "condition",
        "damage",
        "return",
        "disposed",
    }
)


def _validate_logistics_record_changed(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"action", "record_type", "record_id"}),
    )
    try:
        UUID(str(payload["record_id"]))
    except (TypeError, ValueError) as error:
        raise ValidationError(
            "Logistics event record must be a UUID.",
            code="invalid_domain_event_payload",
        ) from error
    if (
        payload["record_type"] not in _LOGISTICS_RECORD_TYPES
        or payload["action"] not in _LOGISTICS_RECORD_ACTIONS
    ):
        raise ValidationError(
            "Logistics event values are not registered.",
            code="invalid_domain_event_payload",
        )


def _validate_catalog_definition_changed(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"action", "target_kind", "state"}),
    )
    if (
        payload["action"]
        not in {"created", "product_added", "variant_added", "activated"}
        or payload["target_kind"] not in {"catalog", "product", "variant"}
        or payload["state"] not in {"draft", "active"}
    ):
        raise ValidationError(
            "Catalog definition event values are not registered.",
            code="invalid_domain_event_payload",
        )


def _validate_catalog_stock_adjusted(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"variant_id", "previous_stock", "new_stock"}),
    )
    try:
        UUID(str(payload["variant_id"]))
    except (TypeError, ValueError) as error:
        raise ValidationError(
            "Catalog stock event variant must be a UUID.",
            code="invalid_domain_event_payload",
        ) from error
    if any(
        not str(payload[field]).isascii() or not str(payload[field]).isdecimal()
        for field in ("previous_stock", "new_stock")
    ):
        raise ValidationError(
            "Catalog stock event values must be non-negative integers.",
            code="invalid_domain_event_payload",
        )


def _validate_catalog_order_changed(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"action", "status", "reference"}),
    )
    if payload["action"] not in {
        "placed",
        "payment_created",
        "payment_succeeded",
        "payment_failed",
    } or payload["status"] not in {
        "payment_pending",
        "paid",
        "cancelled",
        "expired",
        "refunded",
    }:
        raise ValidationError(
            "Catalog order event values are not registered.",
            code="invalid_domain_event_payload",
        )


def _validate_account_restriction_applied(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"restriction_kind", "status"}),
    )


def _validate_workforce_application_submitted(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"position_code", "status"}),
    )


def _validate_workforce_document_reviewed(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"document_type_code", "decision"}),
    )


def _validate_workforce_assignment_activated(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"position_code", "role_code", "status"}),
    )


def _validate_workforce_assignment_changed(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"position_code", "status"}),
    )


def _validate_workforce_availability_changed(payload: dict[str, object]) -> None:
    """Validate a minimized availability fact without accepting exact times.

    Parameters
    ----------
    payload : dict[str, object]
        Candidate state and count-only domain-event payload.

    Raises
    ------
    ValidationError
        If fields, state, or the bounded decimal count is invalid.
    """
    _require_exact_string_fields(
        payload,
        fields=frozenset({"status", "window_count"}),
    )
    if payload["status"] not in {"draft", "submitted", "withdrawn"}:
        raise ValidationError(
            "Availability event status is not registered.",
            code="invalid_domain_event_payload",
        )
    window_count = payload["window_count"]
    if (
        not isinstance(window_count, str)
        or re.fullmatch(r"0|[1-9][0-9]?", window_count) is None
        or int(window_count) > MAX_WORKFORCE_AVAILABILITY_WINDOWS
    ):
        raise ValidationError(
            "Availability event count is invalid.",
            code="invalid_domain_event_payload",
        )


def _validate_workforce_shift_demand_changed(payload: dict[str, object]) -> None:
    """Validate a minimized Shift-demand state change.

    Parameters
    ----------
    payload : dict[str, object]
        Candidate event payload containing only the resulting demand status.

    Raises
    ------
    ValidationError
        If the payload shape or status is not registered.
    """
    _require_exact_string_fields(payload, fields=frozenset({"status"}))
    if payload["status"] not in {"draft", "open", "locked", "completed", "cancelled"}:
        raise ValidationError(
            "Shift demand event status is not registered.",
            code="invalid_domain_event_payload",
        )


def _validate_workforce_shift_commitment_changed(payload: dict[str, object]) -> None:
    """Validate a minimized Shift-commitment state change.

    Parameters
    ----------
    payload : dict[str, object]
        Candidate event payload containing only the resulting commitment status.

    Raises
    ------
    ValidationError
        If the payload shape or status is not registered.
    """
    _require_exact_string_fields(payload, fields=frozenset({"status"}))
    if payload["status"] not in {"claimed", "confirmed", "removed", "completed"}:
        raise ValidationError(
            "Shift commitment event status is not registered.",
            code="invalid_domain_event_payload",
        )


_WORKFORCE_STRUCTURE_ACTIONS = frozenset(
    {
        "template_applied",
        "department_created",
        "department_updated",
        "department_retired",
        "department_deleted",
        "position_created",
        "position_updated",
        "position_closed",
        "opportunity_updated",
    }
)
_WORKFORCE_STRUCTURE_CHANGED_FIELDS = frozenset(
    {
        "departments",
        "name",
        "description",
        "parent_department",
        "display_order",
        "retirement",
        "position",
        "opportunity",
        "resource_binding",
        "headcount",
        "reports_to",
        "title",
        "status",
        "closure",
        "opportunity.applications_close_at",
        "opportunity.applications_open_at",
        "opportunity.description",
        "opportunity.headline",
        "opportunity.status",
        "opportunity.visible_when_filled",
    }
)
_WORKFORCE_STRUCTURE_DEPARTMENT_FIELDS = frozenset(
    {"name", "description", "parent_department", "display_order"}
)
_WORKFORCE_STRUCTURE_POSITION_FIELDS = frozenset(
    {"title", "description", "headcount", "reports_to"}
)
_WORKFORCE_STRUCTURE_OPPORTUNITY_FIELDS = frozenset(
    {
        "opportunity.applications_close_at",
        "opportunity.applications_open_at",
        "opportunity.description",
        "opportunity.headline",
        "opportunity.status",
        "opportunity.visible_when_filled",
        "status",
    }
)
_EVENT_SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def _validate_workforce_structure_changed(payload: dict[str, object]) -> None:
    action = payload.get("action")
    template_action = action == "template_applied"
    fields = frozenset(
        {"action", "aggregate_version", "changed_fields"}
        | ({"template_code", "template_version"} if template_action else set())
    )
    _require_exact_string_fields(payload, fields=fields)
    if action not in _WORKFORCE_STRUCTURE_ACTIONS:
        raise ValidationError(
            "Workforce structure event action is not registered.",
            code="invalid_domain_event_payload",
        )
    aggregate_version = payload["aggregate_version"]
    if not isinstance(aggregate_version, str) or not (
        aggregate_version.isascii()
        and aggregate_version.isdecimal()
        and int(aggregate_version) >= 1
    ):
        raise ValidationError(
            "Workforce structure event version must be positive.",
            code="invalid_domain_event_payload",
        )
    changed_fields = payload["changed_fields"]
    if not isinstance(changed_fields, str):
        raise ValidationError(
            "Workforce structure changed fields are invalid.",
            code="invalid_domain_event_payload",
        )
    changed_field_values = tuple(changed_fields.split(","))
    if (
        not changed_field_values
        or tuple(sorted(set(changed_field_values))) != changed_field_values
        or not set(changed_field_values).issubset(_WORKFORCE_STRUCTURE_CHANGED_FIELDS)
    ):
        raise ValidationError(
            "Workforce structure changed fields are not registered.",
            code="invalid_domain_event_payload",
        )
    changed_field_set = frozenset(changed_field_values)
    if (
        (
            action in {"template_applied", "department_created", "department_deleted"}
            and changed_field_set != {"departments"}
        )
        or (action == "department_retired" and changed_field_set != {"retirement"})
        or (
            action == "department_updated"
            and not changed_field_set.issubset(_WORKFORCE_STRUCTURE_DEPARTMENT_FIELDS)
        )
        or (
            action == "position_created"
            and changed_field_set != {"opportunity", "position", "resource_binding"}
        )
        or (
            action == "position_updated"
            and not changed_field_set.issubset(_WORKFORCE_STRUCTURE_POSITION_FIELDS)
        )
        or (
            action == "opportunity_updated"
            and not changed_field_set.issubset(_WORKFORCE_STRUCTURE_OPPORTUNITY_FIELDS)
        )
        or (
            action == "position_closed"
            and changed_field_set
            not in ({"closure"}, {"closure", "opportunity.status"})
        )
    ):
        raise ValidationError(
            "Workforce structure action and changed fields do not agree.",
            code="invalid_domain_event_payload",
        )
    if template_action:
        template_code = payload["template_code"]
        template_version = payload["template_version"]
        if (
            not isinstance(template_code, str)
            or len(template_code) > MAX_EVENT_CODE_LENGTH
            or _EVENT_SLUG_PATTERN.fullmatch(template_code) is None
            or not isinstance(template_version, str)
            or not template_version.isascii()
            or not template_version.isdecimal()
            or int(template_version) < 1
        ):
            raise ValidationError(
                "Workforce structure template reference is invalid.",
                code="invalid_domain_event_payload",
            )


EVENT_DEFINITIONS = (
    EventDefinition(
        name="organizations.representation.changed.v1",
        schema_version=1,
        description="An accountable Executive Board representation changed state.",
        validator=_validate_organization_representation_changed,
    ),
    EventDefinition(
        name="organizations.convention_series.created.v1",
        schema_version=1,
        description="A recurring convention brand was created.",
        validator=_validate_convention_series_created,
    ),
    EventDefinition(
        name="organizations.convention_series.updated.v1",
        schema_version=1,
        description="A recurring convention brand profile changed.",
        validator=_validate_convention_series_updated,
    ),
    EventDefinition(
        name="events.edition.created.v1",
        schema_version=1,
        description="A Draft event edition was created beneath a series.",
        validator=_validate_edition_created,
    ),
    EventDefinition(
        name="events.edition.details_updated.v1",
        schema_version=1,
        description="Editable event-edition details changed.",
        validator=_validate_edition_details_updated,
    ),
    EventDefinition(
        name="events.edition.lifecycle_transitioned.v1",
        schema_version=1,
        description="An event edition completed a valid lifecycle transition.",
        validator=_validate_edition_lifecycle_transitioned,
    ),
    EventDefinition(
        name="authorization.capability.delegated.v1",
        schema_version=1,
        description="A bounded capability grant was delegated to a principal.",
        validator=_validate_capability_delegated,
    ),
    EventDefinition(
        name="authorization.capability.direct_granted.v1",
        schema_version=1,
        description="A root capability grant was issued under dual control.",
        validator=_validate_capability_authority_changed,
    ),
    EventDefinition(
        name="authorization.capability.revoked.v1",
        schema_version=1,
        description="A capability grant was revoked.",
        validator=_validate_capability_authority_changed,
    ),
    EventDefinition(
        name="authorization.role_bundle.version_created.v1",
        schema_version=1,
        description="An immutable organizer role-bundle version was created.",
        validator=_validate_role_bundle_version_created,
    ),
    EventDefinition(
        name="authorization.role.assigned.v1",
        schema_version=1,
        description="An immutable role-bundle version was assigned to a principal.",
        validator=_validate_role_assignment_changed,
    ),
    EventDefinition(
        name="authorization.role.revoked.v1",
        schema_version=1,
        description="A role assignment was revoked.",
        validator=_validate_role_assignment_changed,
    ),
    EventDefinition(
        name="system.effect.probe_requested.v1",
        schema_version=1,
        description="A synthetic delivery probe used by readiness tests.",
        validator=_validate_effect_probe,
    ),
    EventDefinition(
        name="identity.account_restriction.applied.v1",
        schema_version=1,
        description=(
            "An organizer restriction reached its effective time and its scoped "
            "consequences were applied."
        ),
        validator=_validate_account_restriction_applied,
    ),
    EventDefinition(
        name="registration.configuration.draft_created.v1",
        schema_version=1,
        description="An edition-owned registration configuration draft was created.",
        validator=_validate_registration_configuration_changed,
    ),
    EventDefinition(
        name="registration.configuration.draft_changed.v1",
        schema_version=1,
        description="An edition-owned registration draft definition changed.",
        validator=_validate_registration_configuration_draft_changed,
    ),
    EventDefinition(
        name="registration.configuration.activated.v1",
        schema_version=1,
        description="A reviewed registration configuration version became active.",
        validator=_validate_registration_configuration_changed,
    ),
    EventDefinition(
        name="registration.template.published.v1",
        schema_version=1,
        description="An immutable reusable registration template was published.",
        validator=_validate_registration_template_published,
    ),
    EventDefinition(
        name="registration.submitted.v1",
        schema_version=1,
        description="An attendee submitted an edition registration.",
        validator=_validate_registration_state_changed,
    ),
    EventDefinition(
        name="registration.profile.updated.v1",
        schema_version=1,
        description="An attendee updated the mutable profile for an open edition.",
        validator=_validate_registration_profile_changed,
    ),
    EventDefinition(
        name="registration.profile_extension.value_appended.v1",
        schema_version=1,
        description=(
            "An authorized actor appended one current-profile extension value "
            "revision without changing the registration submission."
        ),
        validator=_validate_registration_profile_extension_value_appended,
    ),
    EventDefinition(
        name="registration.profile.media_reviewed.v1",
        schema_version=1,
        description="An organizer reviewed an attendee profile or fursuit image.",
        validator=_validate_registration_media_reviewed,
    ),
    EventDefinition(
        name="charities.partner.changed.v1",
        schema_version=1,
        description="An organizer-owned charity partner profile changed.",
        validator=_validate_charity_partner_changed,
    ),
    EventDefinition(
        name="charities.media.changed.v1",
        schema_version=1,
        description="A governed charity media reference changed review state.",
        validator=_validate_charity_media_changed,
    ),
    EventDefinition(
        name="charities.selection.changed.v1",
        schema_version=1,
        description="An edition charity selection changed review or publication state.",
        validator=_validate_charity_selection_changed,
    ),
    EventDefinition(
        name="venues.record.changed.v1",
        schema_version=1,
        description="A governed venue catalog or edition schedule record changed.",
        validator=_validate_venue_record_changed,
    ),
    EventDefinition(
        name="logistics.record.changed.v1",
        schema_version=1,
        description="A governed logistics catalog, offer, or custody record changed.",
        validator=_validate_logistics_record_changed,
    ),
    EventDefinition(
        name="catalog.definition.changed.v1",
        schema_version=1,
        description="An edition catalog definition or activation changed.",
        validator=_validate_catalog_definition_changed,
    ),
    EventDefinition(
        name="catalog.stock.adjusted.v1",
        schema_version=1,
        description="An operator appended stock within a configured hard ceiling.",
        validator=_validate_catalog_stock_adjusted,
    ),
    EventDefinition(
        name="catalog.order.changed.v1",
        schema_version=1,
        description="An attendee catalog order or exact-total payment advanced.",
        validator=_validate_catalog_order_changed,
    ),
    EventDefinition(
        name="applications.definition.changed.v1",
        schema_version=1,
        description="An edition-owned typed application definition changed.",
        validator=_validate_application_definition_changed,
    ),
    EventDefinition(
        name="applications.submission.changed.v1",
        schema_version=1,
        description=(
            "An applicant or accountable reviewer advanced a typed application."
        ),
        validator=_validate_application_submission_changed,
    ),
    EventDefinition(
        name="applications.programme_call.changed.v1",
        schema_version=1,
        description="An Applications-owned Programme call changed.",
        validator=_validate_application_programme_call_changed,
    ),
    EventDefinition(
        name="applications.programme_proposal.changed.v1",
        schema_version=1,
        description=("An Applications-owned collaborative Programme proposal changed."),
        validator=_validate_application_programme_proposal_changed,
    ),
    EventDefinition(
        name="programme.item.changed.v1",
        schema_version=1,
        description="A private Programme item or one of its governed layers changed.",
        validator=_validate_programme_item_changed,
    ),
    EventDefinition(
        name="registration.payment.reconciled.v1",
        schema_version=1,
        description="A provider payment result confirmed a registration.",
        validator=_validate_registration_state_changed,
    ),
    EventDefinition(
        name="registration.payment.deadline_changed.v1",
        schema_version=1,
        description="An authorized operator changed a payment deadline.",
        validator=_validate_registration_state_changed,
    ),
    EventDefinition(
        name="registration.payment.waived.v1",
        schema_version=1,
        description="An authorized operator waived a registration payment.",
        validator=_validate_registration_state_changed,
    ),
    EventDefinition(
        name="registration.payment.expired.v1",
        schema_version=1,
        description="A payment reservation expired and released capacity.",
        validator=_validate_registration_state_changed,
    ),
    EventDefinition(
        name="registration.waitlist.offered.v1",
        schema_version=1,
        description="A waitlisted attendee received an available place.",
        validator=_validate_registration_state_changed,
    ),
    EventDefinition(
        name="registration.admission_tier_replacement.reserved.v1",
        schema_version=1,
        description="A paid attendee reserved capacity in a higher admission tier.",
        validator=_validate_registration_tier_replacement,
    ),
    EventDefinition(
        name="registration.admission_tier_replacement.completed.v1",
        schema_version=1,
        description="Verified price-difference payment replaced an admission tier.",
        validator=_validate_registration_tier_replacement,
    ),
    EventDefinition(
        name="registration.admission_tier_replacement.expired.v1",
        schema_version=1,
        description="An unpaid higher-tier capacity hold expired safely.",
        validator=_validate_registration_tier_replacement,
    ),
    EventDefinition(
        name="registration.capacity.adjusted.v1",
        schema_version=1,
        description="An authorized operator appended an effective capacity change.",
        validator=_validate_registration_capacity_adjusted,
    ),
    EventDefinition(
        name="registration.waitlist.batch_offered.v1",
        schema_version=1,
        description="An authorized operator offered the next strict FIFO batch.",
        validator=_validate_registration_waitlist_batch,
    ),
    EventDefinition(
        name="registration.cancelled.v1",
        schema_version=1,
        description="An open registration was cancelled through policy.",
        validator=_validate_registration_state_changed,
    ),
    EventDefinition(
        name="registration.checked_in.v1",
        schema_version=1,
        description="A confirmed attendee was checked in.",
        validator=_validate_registration_state_changed,
    ),
    EventDefinition(
        name="registration.guardian.accepted.v1",
        schema_version=1,
        description="Guardian consent activated a minor registration.",
        validator=_validate_registration_state_changed,
    ),
    EventDefinition(
        name="workforce.application.submitted.v1",
        schema_version=1,
        description="A person submitted an application for a published position.",
        validator=_validate_workforce_application_submitted,
    ),
    EventDefinition(
        name="workforce.document.reviewed.v1",
        schema_version=1,
        description="An organizer reviewed an exact onboarding document version.",
        validator=_validate_workforce_document_reviewed,
    ),
    EventDefinition(
        name="workforce.position_assignment.activated.v1",
        schema_version=1,
        description="A dual-controlled position assignment activated scoped access.",
        validator=_validate_workforce_assignment_activated,
    ),
    EventDefinition(
        name="workforce.position_assignment.proposed.v1",
        schema_version=1,
        description="A controller proposed a known person for a Position.",
        validator=_validate_workforce_assignment_changed,
    ),
    EventDefinition(
        name="workforce.position_assignment.rejected.v1",
        schema_version=1,
        description="A distinct controller rejected a Position assignment proposal.",
        validator=_validate_workforce_assignment_changed,
    ),
    EventDefinition(
        name="workforce.position_assignment.ended.v1",
        schema_version=1,
        description="A controller ended a Position assignment and linked authority.",
        validator=_validate_workforce_assignment_changed,
    ),
    EventDefinition(
        name="workforce.person_availability.changed.v1",
        schema_version=1,
        description=(
            "A person replaced, shared, or withdrew current edition availability."
        ),
        validator=_validate_workforce_availability_changed,
    ),
    EventDefinition(
        name="workforce.shift_demand.changed.v1",
        schema_version=1,
        description="A governed Shift-demand lifecycle or definition changed.",
        validator=_validate_workforce_shift_demand_changed,
    ),
    EventDefinition(
        name="workforce.shift_commitment.changed.v1",
        schema_version=1,
        description="A person-owned Shift commitment changed retained state.",
        validator=_validate_workforce_shift_commitment_changed,
    ),
    EventDefinition(
        name="workforce.structure.changed.v1",
        schema_version=1,
        description="An edition-owned Department structure revision committed.",
        validator=_validate_workforce_structure_changed,
    ),
)

DEFINITIONS_BY_NAME = {definition.name: definition for definition in EVENT_DEFINITIONS}

if len(DEFINITIONS_BY_NAME) != len(EVENT_DEFINITIONS):
    raise RuntimeError("Domain event names must be unique.")


def event_definition(name: str) -> EventDefinition | None:
    """Return event definition.

    Parameters
    ----------
    name : str
        The human-readable name.

    Returns
    -------
    EventDefinition | None
        The matching EventDefinition, or `None` when no authorized record exists.
    """
    return DEFINITIONS_BY_NAME.get(name)


def validate_event_payload(
    *,
    event_name: str,
    schema_version: int,
    payload: Any,
) -> None:
    """Validate event payload.

    Parameters
    ----------
    event_name : str
        The human-readable event name shown to authorized readers.
    schema_version : int
        The expected schema version used to reject stale updates.
    payload : Any
        The validated payload to process.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    definition = event_definition(event_name)
    if definition is None:
        raise ValidationError(
            "Use a domain event declared by the platform.",
            code="unknown_domain_event",
        )
    if schema_version != definition.schema_version:
        raise ValidationError(
            "Domain event schema version does not match its registered version.",
            code="invalid_domain_event_version",
        )
    if not isinstance(payload, dict):
        raise ValidationError(
            "Domain event payload must be an object.",
            code="invalid_domain_event_payload",
        )
    definition.validator(payload)
