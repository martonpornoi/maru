"""Typed adapters from closed staff forms to logistics commands."""
# ruff: noqa: PLR0911, PLR0912

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict, cast
from uuid import UUID, uuid4

from django import forms
from django.utils import timezone

from .queries import (
    LogisticsFormChoices,
    ManifestProjection,
    NamedLogisticsChoice,
    NamedLogisticsCodeChoice,
    OfferQueueProjection,
)
from .services import (
    KitLineInput,
    LogisticsCommandResult,
    ManifestLineInput,
    MovementInput,
    OfflineOperationInput,
    PartyProfile,
    SubjectLocator,
    add_manifest_line,
    assign_keyholder_responsibility,
    change_manifest_state,
    create_logistics_label,
    create_logistics_manifest,
    create_logistics_node,
    create_logistics_party,
    create_restricted_logistics_address,
    create_reusable_kit,
    ingest_offline_scan_batch,
    record_asset_agreement,
    record_logistics_event,
    register_physical_key,
    register_serialized_asset,
    register_stock_lot,
    review_equipment_offer,
)
from .staff_forms import (
    AgreementCreateForm,
    AssetCreateForm,
    KeyholderAssignForm,
    KitCreateForm,
    LabelCreateForm,
    ManifestCreateForm,
    ManifestLineAddForm,
    ManifestStateForm,
    MovementEventForm,
    NodeCreateForm,
    OfferReviewForm,
    OfflineBatchForm,
    PartyCreateForm,
    PhysicalKeyCreateForm,
    RestrictedAddressCreateForm,
    StockLotCreateForm,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from maru.identity.models import Account

    from .forms import LogisticsStrictForm


@dataclass(frozen=True, slots=True)
class StaffCommandDefinition:
    """Describe staff command definition.

    Attributes
    ----------
    action
        The stable action code describing the requested transition.
    title
        The human-readable title shown to authorized readers.
    form_class
        The form class retained in this immutable projection.
    """

    action: str
    title: str
    form_class: type[LogisticsStrictForm]


class _CommonCommandArgs(TypedDict):
    actor: Account
    organization_id: UUID
    reason: str
    idempotency_key: UUID
    correlation_id: UUID
    source_channel: str


_NamedChoice = NamedLogisticsChoice | NamedLogisticsCodeChoice


OFFER_REVIEW_COMMAND = StaffCommandDefinition(
    "offer-review", "Accept or reject an offer", OfferReviewForm
)
MANIFEST_STATE_COMMAND = StaffCommandDefinition(
    "manifest-state", "Change manifest state", ManifestStateForm
)
MANIFEST_LINE_COMMAND = StaffCommandDefinition(
    "manifest-line-add", "Add a manifest line", ManifestLineAddForm
)
STAFF_COMMANDS = (
    StaffCommandDefinition(
        "party-create", "Register provider or owner", PartyCreateForm
    ),
    StaffCommandDefinition(
        "address-create", "Register restricted address", RestrictedAddressCreateForm
    ),
    StaffCommandDefinition(
        "node-create", "Register location, box, or vehicle", NodeCreateForm
    ),
    StaffCommandDefinition(
        "asset-create", "Register serialized asset", AssetCreateForm
    ),
    StaffCommandDefinition(
        "stock-create", "Register bulk stock lot", StockLotCreateForm
    ),
    StaffCommandDefinition(
        "key-create", "Register physical key", PhysicalKeyCreateForm
    ),
    StaffCommandDefinition(
        "keyholder-assign", "Assign physical keyholder", KeyholderAssignForm
    ),
    StaffCommandDefinition(
        "label-create", "Create label / QR identifier", LabelCreateForm
    ),
    StaffCommandDefinition(
        "agreement-create", "Record loan or rental", AgreementCreateForm
    ),
    StaffCommandDefinition("kit-create", "Register reusable kit", KitCreateForm),
    StaffCommandDefinition(
        "manifest-create", "Create manifest and first line", ManifestCreateForm
    ),
    StaffCommandDefinition(
        "event-record", "Record custody or movement event", MovementEventForm
    ),
    StaffCommandDefinition(
        "offline-reconcile", "Reconcile offline scan", OfflineBatchForm
    ),
)
STAFF_COMMAND_BY_ACTION = {
    definition.action: definition
    for definition in (
        OFFER_REVIEW_COMMAND,
        MANIFEST_LINE_COMMAND,
        MANIFEST_STATE_COMMAND,
        *STAFF_COMMANDS,
    )
}


def _named_choices(
    records: Iterable[_NamedChoice], *, empty_label: str = "Select one"
) -> tuple[tuple[str, str], ...]:
    return (
        ("", empty_label),
        *((str(record.value), record.label) for record in records),
    )


def configure_staff_form_choices[FormT: forms.Form](
    form: FormT, *, choices: LogisticsFormChoices
) -> FormT:
    """Configure staff form choices.

    Parameters
    ----------
    form : FormT
        The form applied within the audited domain transition.
    choices : LogisticsFormChoices
        The permitted closed choices.

    Returns
    -------
    FormT
        The configured staff form choices.
    """
    field_sources = {
        "responsible_department_id": choices.departments,
        "subject_account_id": choices.people,
        "owner_account_id": choices.people,
        "provider_account_id": choices.people,
        "borrower_account_id": choices.people,
        "responsible_account_id": choices.people,
        "to_custodian_account_id": choices.people,
        "party_id": choices.parties,
        "owner_party_id": choices.parties,
        "provider_party_id": choices.parties,
        "borrower_party_id": choices.parties,
        "external_owner_id": choices.parties,
        "provider_id": choices.parties,
        "to_custodian_party_id": choices.parties,
        "storage_address_id": choices.addresses,
        "return_address_id": choices.addresses,
        "address_id": choices.addresses,
        "opens_node_id": choices.nodes,
        "source_node_id": choices.nodes,
        "destination_node_id": choices.nodes,
        "vehicle_id": choices.vehicles,
        "venue_space_selection_id": choices.venue_space_selections,
        "key_id": choices.physical_keys,
        "subject_id": choices.tracked_subjects,
        "line_subject_id": choices.tracked_subjects,
        "line_packed_in_node_id": choices.packing_nodes,
        "manifest_id": choices.manifests,
    }
    for field_name, records in field_sources.items():
        field = form.fields.get(field_name)
        if isinstance(field, forms.ChoiceField):
            field.choices = _named_choices(records)
    label_choices = _named_choices(choices.labels)
    for field_name in (
        "label_code",
        "source_label_code",
        "destination_label_code",
    ):
        field = form.fields.get(field_name)
        if isinstance(field, forms.ChoiceField):
            field.choices = label_choices
    return form


def staff_command_forms(
    *, zone_name: str, choices: LogisticsFormChoices
) -> tuple[tuple[StaffCommandDefinition, LogisticsStrictForm], ...]:
    """Return staff command forms.

    Parameters
    ----------
    zone_name : str
        The IANA time-zone name.
    choices : LogisticsFormChoices
        The permitted closed choices.

    Returns
    -------
    tuple[tuple[StaffCommandDefinition, LogisticsStrictForm], ...]
        The authorized staff command forms records in deterministic order.
    """
    return tuple(
        (
            definition,
            configure_staff_form_choices(
                definition.form_class(
                    zone_name=zone_name,
                    initial={
                        "idempotency_key": uuid4(),
                        "reason": f"Run {definition.title.lower()}.",
                        "occurred_at": timezone.now(),
                        "starts_at": timezone.now(),
                        "operation_idempotency_key": uuid4(),
                    },
                ),
                choices=choices,
            ),
        )
        for definition in STAFF_COMMANDS
    )


def offer_review_forms(
    *,
    offers: Iterable[OfferQueueProjection],
    choices: LogisticsFormChoices,
    zone_name: str,
) -> tuple[tuple[OfferQueueProjection, str, str, OfferReviewForm], ...]:
    """Return offer review forms.

    Parameters
    ----------
    offers : Iterable[OfferQueueProjection]
        The offers applied within the audited domain transition.
    choices : LogisticsFormChoices
        The permitted closed choices.
    zone_name : str
        The IANA time-zone name.

    Returns
    -------
    tuple[tuple[OfferQueueProjection, str, str, OfferReviewForm], ...]
        The offer queue projection.
    """
    rendered: list[tuple[OfferQueueProjection, str, str, OfferReviewForm]] = []
    for offer in offers:
        if offer.status != "pending":
            continue
        for outcome, label in (("accepted", "Accept"), ("rejected", "Reject")):
            form = configure_staff_form_choices(
                OfferReviewForm(
                    zone_name=zone_name,
                    initial={
                        "idempotency_key": uuid4(),
                        "reason": f"{label} the pending equipment offer.",
                        "offer_id": offer.id,
                        "expected_version": offer.aggregate_version,
                        "outcome": outcome,
                    },
                ),
                choices=choices,
            )
            rendered.append((offer, outcome, label, form))
    return tuple(rendered)


def manifest_state_forms(
    *, manifests: Iterable[ManifestProjection], zone_name: str
) -> tuple[tuple[ManifestProjection, str, str, ManifestStateForm], ...]:
    """Return manifest state forms.

    Parameters
    ----------
    manifests : Iterable[ManifestProjection]
        The manifests applied within the audited domain transition.
    zone_name : str
        The IANA time-zone name.

    Returns
    -------
    tuple[tuple[ManifestProjection, str, str, ManifestStateForm], ...]
        The manifest projection.
    """
    actions_by_status: dict[str, tuple[tuple[str, str], ...]] = {
        "draft": (("seal", "Seal"), ("cancel_draft", "Cancel")),
        "sealed": (("complete", "Complete"), ("cancel_sealed", "Cancel")),
    }
    rendered: list[tuple[ManifestProjection, str, str, ManifestStateForm]] = []
    for manifest in manifests:
        for action, label in actions_by_status.get(manifest.status, ()):
            form = ManifestStateForm(
                zone_name=zone_name,
                initial={
                    "idempotency_key": uuid4(),
                    "reason": f"{label} this manifest.",
                    "manifest_id": manifest.id,
                    "expected_version": manifest.aggregate_version,
                    "action": action,
                },
            )
            rendered.append((manifest, action, label, form))
    return tuple(rendered)


def manifest_line_forms(
    *,
    manifests: Iterable[ManifestProjection],
    choices: LogisticsFormChoices,
    zone_name: str,
) -> tuple[tuple[ManifestProjection, ManifestLineAddForm], ...]:
    """Return manifest line forms.

    Parameters
    ----------
    manifests : Iterable[ManifestProjection]
        The manifests applied within the audited domain transition.
    choices : LogisticsFormChoices
        The permitted closed choices.
    zone_name : str
        The IANA time-zone name.

    Returns
    -------
    tuple[tuple[ManifestProjection, ManifestLineAddForm], ...]
        The manifest projection.
    """
    rendered: list[tuple[ManifestProjection, ManifestLineAddForm]] = []
    for manifest in manifests:
        if manifest.status != "draft":
            continue
        form = configure_staff_form_choices(
            ManifestLineAddForm(
                zone_name=zone_name,
                initial={
                    "idempotency_key": uuid4(),
                    "reason": "Add this tracked item to the draft manifest.",
                    "manifest_id": manifest.id,
                    "expected_version": manifest.aggregate_version,
                    "line_quantity": 1,
                },
            ),
            choices=choices,
        )
        rendered.append((manifest, form))
    return tuple(rendered)


def _edition_id(data: dict[str, object], edition_id: UUID) -> UUID | None:
    return edition_id if bool(data.get("edition_specific")) else None


def _locator(data: dict[str, object], *, prefix: str = "subject") -> SubjectLocator:
    return SubjectLocator(
        kind=cast("str", data[f"{prefix}_kind"]),
        object_id=cast("UUID", data[f"{prefix}_id"]),
    )


def execute_staff_command(
    *,
    action: str,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    data: dict[str, object],
    correlation_id: UUID,
) -> LogisticsCommandResult:
    """Return execute staff command.

    Parameters
    ----------
    action : str
        The requested lifecycle action.
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    data : dict[str, object]
        The input data to validate or transform.
    correlation_id : UUID
        The correlation identifier for audit tracing.

    Returns
    -------
    LogisticsCommandResult
        The logistics command result.

    Raises
    ------
    LookupError
        If the operation encounters a lookup condition.
    """
    common: _CommonCommandArgs = {
        "actor": actor,
        "organization_id": organization_id,
        "reason": cast("str", data["reason"]),
        "idempotency_key": cast("UUID", data["idempotency_key"]),
        "correlation_id": correlation_id,
        "source_channel": "browser",
    }
    if action == "offer-review":
        return review_equipment_offer(
            edition_id=edition_id,
            offer_id=cast("UUID", data["offer_id"]),
            expected_version=cast("int", data["expected_version"]),
            outcome=cast("str", data["outcome"]),
            responsible_department_id=cast(
                "UUID | None", data.get("responsible_department_id")
            ),
            **common,
        )
    if action == "party-create":
        return create_logistics_party(
            code=cast("str", data["code"]),
            profile=PartyProfile(
                kind=cast("str", data["kind"]),
                role=cast("str", data["role"]),
                legal_name=cast("str", data["legal_name"]),
                public_name=cast("str", data["public_name"]),
                provider_reference=cast("str", data["provider_reference"]),
                website_url=cast("str", data["website_url"]),
            ),
            **common,
        )
    if action == "address-create":
        return create_restricted_logistics_address(
            edition_id=edition_id,
            subject_account_id=cast("UUID | None", data.get("subject_account_id")),
            party_id=cast("UUID | None", data.get("party_id")),
            purpose=cast("str", data["purpose"]),
            label=cast("str", data["label"]),
            recipient_name=cast("str", data["recipient_name"]),
            contact_email=cast("str", data["contact_email"]),
            contact_phone=cast("str", data["contact_phone"]),
            postal_address=cast("str", data["postal_address"]),
            access_instructions=cast("str", data["access_instructions"]),
            retention_until=cast("datetime | None", data.get("retention_until")),
            **common,
        )
    if action == "node-create":
        return create_logistics_node(
            kind=cast("str", data["kind"]),
            code=cast("str", data["code"]),
            name=cast("str", data["name"]),
            description=cast("str", data["description"]),
            edition_id=_edition_id(data, edition_id),
            storage_address_id=cast("UUID | None", data.get("storage_address_id")),
            external_owner_id=cast("UUID | None", data.get("external_owner_id")),
            provider_id=cast("UUID | None", data.get("provider_id")),
            vehicle_registration=cast("str", data["vehicle_registration"]),
            venue_space_selection_id=cast(
                "UUID | None", data.get("venue_space_selection_id")
            ),
            capacity_note=cast("str", data["capacity_note"]),
            **common,
        )
    if action == "asset-create":
        return register_serialized_asset(
            edition_id=_edition_id(data, edition_id),
            catalog_code=cast("str", data["catalog_code"]),
            name=cast("str", data["name"]),
            asset_type=cast("str", data["asset_type"]),
            manufacturer=cast("str", data["manufacturer"]),
            model_name=cast("str", data["model_name"]),
            serial_number=cast("str", data["serial_number"]),
            acquisition=cast("str", data["acquisition"]),
            value_class=cast("str", data["value_class"]),
            owner_kind=cast("str", data["owner_kind"]),
            owner_account_id=cast("UUID | None", data.get("owner_account_id")),
            owner_party_id=cast("UUID | None", data.get("owner_party_id")),
            **common,
        )
    if action == "stock-create":
        return register_stock_lot(
            edition_id=_edition_id(data, edition_id),
            catalog_code=cast("str", data["catalog_code"]),
            name=cast("str", data["name"]),
            stock_type=cast("str", data["stock_type"]),
            unit=cast("str", data["unit"]),
            initial_quantity=cast("int", data["initial_quantity"]),
            value_class=cast("str", data["value_class"]),
            owner_kind=cast("str", data["owner_kind"]),
            owner_account_id=cast("UUID | None", data.get("owner_account_id")),
            owner_party_id=cast("UUID | None", data.get("owner_party_id")),
            **common,
        )
    if action == "key-create":
        return register_physical_key(
            edition_id=_edition_id(data, edition_id),
            code=cast("str", data["code"]),
            label=cast("str", data["label"]),
            opens_node_id=cast("UUID", data["opens_node_id"]),
            provider_id=cast("UUID | None", data.get("provider_id")),
            **common,
        )
    if action == "keyholder-assign":
        return assign_keyholder_responsibility(
            key_id=cast("UUID", data["key_id"]),
            responsible_account_id=cast("UUID", data["responsible_account_id"]),
            starts_at=cast("datetime", data["starts_at"]),
            ends_at=cast("datetime | None", data.get("ends_at")),
            expected_version=cast("int", data["expected_version"]),
            **common,
        )
    if action == "label-create":
        return create_logistics_label(
            subject=_locator(data),
            label_code=cast("str", data["label_code"]),
            qr_identifier=cast("str", data["qr_identifier"]),
            **common,
        )
    if action == "agreement-create":
        return record_asset_agreement(
            edition_id=edition_id,
            subject=_locator(data),
            kind=cast("str", data["kind"]),
            provider_account_id=cast("UUID | None", data.get("provider_account_id")),
            provider_party_id=cast("UUID | None", data.get("provider_party_id")),
            borrower_account_id=cast("UUID | None", data.get("borrower_account_id")),
            borrower_party_id=cast("UUID | None", data.get("borrower_party_id")),
            starts_at=cast("datetime", data["starts_at"]),
            ends_at=cast("datetime", data["ends_at"]),
            return_due_at=cast("datetime", data["return_due_at"]),
            return_address_id=cast("UUID | None", data.get("return_address_id")),
            provider_reference=cast("str", data["provider_reference"]),
            terms_reference=cast("str", data["terms_reference"]),
            **common,
        )
    if action == "kit-create":
        return create_reusable_kit(
            code=cast("str", data["code"]),
            name=cast("str", data["name"]),
            description=cast("str", data["description"]),
            lines=(
                KitLineInput(
                    subject=_locator(data),
                    quantity=cast("int", data["quantity"]),
                    notes=cast("str", data["notes"]),
                ),
            ),
            **common,
        )
    if action == "manifest-create":
        return create_logistics_manifest(
            edition_id=edition_id,
            responsible_department_id=cast("UUID", data["responsible_department_id"]),
            manifest_number=cast("str", data["manifest_number"]),
            kind=cast("str", data["kind"]),
            title=cast("str", data["title"]),
            source_node_id=cast("UUID | None", data.get("source_node_id")),
            destination_node_id=cast("UUID | None", data.get("destination_node_id")),
            vehicle_id=cast("UUID | None", data.get("vehicle_id")),
            provider_id=cast("UUID | None", data.get("provider_id")),
            loading_starts_at=cast("datetime | None", data.get("loading_starts_at")),
            loading_ends_at=cast("datetime | None", data.get("loading_ends_at")),
            lines=(
                ManifestLineInput(
                    subject=_locator(data, prefix="line_subject"),
                    quantity=cast("int", data["line_quantity"]),
                    packed_in_node_id=cast(
                        "UUID | None", data.get("line_packed_in_node_id")
                    ),
                    notes=cast("str", data["line_notes"]),
                ),
            ),
            **common,
        )
    if action == "manifest-state":
        return change_manifest_state(
            edition_id=edition_id,
            manifest_id=cast("UUID", data["manifest_id"]),
            expected_version=cast("int", data["expected_version"]),
            action=cast("str", data["action"]),
            **common,
        )
    if action == "manifest-line-add":
        return add_manifest_line(
            edition_id=edition_id,
            manifest_id=cast("UUID", data["manifest_id"]),
            expected_version=cast("int", data["expected_version"]),
            line=ManifestLineInput(
                subject=_locator(data, prefix="line_subject"),
                quantity=cast("int", data["line_quantity"]),
                packed_in_node_id=cast(
                    "UUID | None", data.get("line_packed_in_node_id")
                ),
                notes=cast("str", data["line_notes"]),
            ),
            **common,
        )
    if action == "event-record":
        return record_logistics_event(
            edition_id=edition_id,
            movement=MovementInput(
                event_type=cast("str", data["event_type"]),
                subject=_locator(data),
                occurred_at=cast("datetime", data["occurred_at"]),
                source_node_id=cast("UUID | None", data.get("source_node_id")),
                destination_node_id=cast(
                    "UUID | None", data.get("destination_node_id")
                ),
                to_custodian_account_id=cast(
                    "UUID | None", data.get("to_custodian_account_id")
                ),
                to_custodian_party_id=cast(
                    "UUID | None", data.get("to_custodian_party_id")
                ),
                quantity=cast("int | None", data.get("quantity")),
                condition_before=cast("str", data["condition_before"]),
                condition_after=cast("str", data["condition_after"]),
                manifest_id=cast("UUID | None", data.get("manifest_id")),
                evidence_reference=cast("str", data["evidence_reference"]),
            ),
            expected_sequence=cast("int", data["expected_sequence"]),
            **common,
        )
    if action == "offline-reconcile":
        return ingest_offline_scan_batch(
            edition_id=edition_id,
            device_code=cast("str", data["device_code"]),
            snapshot_version=cast("int", data["snapshot_version"]),
            policy_version=cast("str", data["policy_version"]),
            expires_at=cast("datetime", data["expires_at"]),
            operations=(
                OfflineOperationInput(
                    sequence=1,
                    idempotency_key=cast("UUID", data["operation_idempotency_key"]),
                    expected_subject_sequence=cast(
                        "int", data["expected_subject_sequence"]
                    ),
                    action=cast("str", data["action"]),
                    label_code=cast("str", data["label_code"]),
                    occurred_at=cast("datetime", data["occurred_at"]),
                    source_label_code=cast("str", data["source_label_code"]),
                    destination_label_code=cast("str", data["destination_label_code"]),
                    quantity=cast("int | None", data.get("quantity")),
                    observed_condition=cast("str", data["observed_condition"]),
                ),
            ),
            **common,
        )
    raise LookupError(action)
