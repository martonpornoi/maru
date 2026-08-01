"""Closed, versioned domain-event schema registry."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ValidationError

PayloadValidator = Callable[[dict[str, object]], None]
MAX_EVENT_PAYLOAD_TEXT_LENGTH = 240


@dataclass(frozen=True, slots=True)
class EventDefinition:
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
        fields=frozenset({"aggregate_version", "lifecycle"}),
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
        or payload["representation_code"] != "executive_board"
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


def _validate_registration_profile_changed(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"action", "reference"}),
    )


def _validate_registration_media_reviewed(payload: dict[str, object]) -> None:
    _require_exact_string_fields(
        payload,
        fields=frozenset({"decision", "media_kind", "reference"}),
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
        name="registration.profile.media_reviewed.v1",
        schema_version=1,
        description="An organizer reviewed an attendee profile or fursuit image.",
        validator=_validate_registration_media_reviewed,
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
)

DEFINITIONS_BY_NAME = {definition.name: definition for definition in EVENT_DEFINITIONS}

if len(DEFINITIONS_BY_NAME) != len(EVENT_DEFINITIONS):
    raise RuntimeError("Domain event names must be unique.")


def event_definition(name: str) -> EventDefinition | None:
    return DEFINITIONS_BY_NAME.get(name)


def validate_event_payload(
    *,
    event_name: str,
    schema_version: int,
    payload: Any,
) -> None:
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
