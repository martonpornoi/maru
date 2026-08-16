"""Closed browser-command adapter coverage for the Logistics workspace."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from django import forms

from maru.identity.models import Account
from maru.logistics import html_commands
from maru.logistics.queries import (
    LogisticsFormChoices,
    ManifestProjection,
    NamedLogisticsChoice,
    NamedLogisticsCodeChoice,
    OfferQueueProjection,
)
from maru.logistics.services import LogisticsCommandResult


def _actor() -> Account:
    return Account(
        id=uuid4(),
        email="logistics-browser-command@example.test",
        is_active=True,
    )


def _result() -> LogisticsCommandResult:
    return LogisticsCommandResult(
        object_id=uuid4(),
        receipt_id=uuid4(),
        resulting_version=2,
        replayed=False,
    )


def _choices() -> LogisticsFormChoices:
    item = (NamedLogisticsChoice(value=uuid4(), label="Synthetic choice"),)
    return LogisticsFormChoices(
        departments=item,
        parties=item,
        addresses=item,
        nodes=item,
        packing_nodes=item,
        vehicles=item,
        venue_rooms=item,
        venue_space_selections=item,
        assets=item,
        stock_lots=item,
        physical_keys=item,
        tracked_subjects=item,
        people=item,
        manifests=item,
        labels=(NamedLogisticsCodeChoice(value="label-1", label="Label 1"),),
    )


def _manifest(*, status: str) -> ManifestProjection:
    return ManifestProjection(
        id=uuid4(),
        manifest_number="IN-BROWSER-1",
        kind="inbound",
        title="Browser manifest",
        status=status,
        responsible_department_id=uuid4(),
        source_node_id=None,
        source_name="",
        destination_node_id=None,
        destination_name="",
        vehicle_id=None,
        vehicle_name="",
        loading_starts_at=None,
        loading_ends_at=None,
        box_count=0,
        line_count=0,
        aggregate_version=3,
        lines=(),
    )


class _AllChoiceForm(forms.Form):
    responsible_department_id = forms.ChoiceField()
    subject_account_id = forms.ChoiceField()
    owner_account_id = forms.ChoiceField()
    provider_account_id = forms.ChoiceField()
    borrower_account_id = forms.ChoiceField()
    responsible_account_id = forms.ChoiceField()
    to_custodian_account_id = forms.ChoiceField()
    party_id = forms.ChoiceField()
    owner_party_id = forms.ChoiceField()
    provider_party_id = forms.ChoiceField()
    borrower_party_id = forms.ChoiceField()
    external_owner_id = forms.ChoiceField()
    provider_id = forms.ChoiceField()
    to_custodian_party_id = forms.ChoiceField()
    storage_address_id = forms.ChoiceField()
    return_address_id = forms.ChoiceField()
    address_id = forms.ChoiceField()
    opens_node_id = forms.ChoiceField()
    source_node_id = forms.ChoiceField()
    destination_node_id = forms.ChoiceField()
    vehicle_id = forms.ChoiceField()
    venue_space_selection_id = forms.ChoiceField()
    key_id = forms.ChoiceField()
    subject_id = forms.ChoiceField()
    line_subject_id = forms.ChoiceField()
    line_packed_in_node_id = forms.ChoiceField()
    manifest_id = forms.ChoiceField()
    label_code = forms.ChoiceField()
    source_label_code = forms.ChoiceField()
    destination_label_code = forms.ChoiceField()
    ignored_text = forms.CharField()


def test_form_choice_configuration_uses_only_bounded_projection_values() -> None:
    form = html_commands.configure_staff_form_choices(
        _AllChoiceForm(), choices=_choices()
    )

    for field_name, field in form.fields.items():
        if field_name == "ignored_text":
            continue
        values = [value for value, _label in field.choices]
        assert values[0] == ""
        assert len(values) == 2
    assert list(form.fields["label_code"].choices)[1] == ("label-1", "Label 1")


def test_workspace_form_factories_render_only_available_actions() -> None:
    choices = _choices()
    command_forms = html_commands.staff_command_forms(
        zone_name="Europe/Budapest", choices=choices
    )
    assert len(command_forms) == len(html_commands.STAFF_COMMANDS)
    assert all(form.initial["reason"] for _definition, form in command_forms)

    pending = OfferQueueProjection(
        id=uuid4(),
        offered_by_id=uuid4(),
        title="Pending offer",
        status="pending",
        item_count=1,
        total_units=1,
        available_from=datetime(2026, 8, 9, tzinfo=UTC),
        available_until=datetime(2026, 8, 10, tzinfo=UTC),
        requested_return_at=None,
        responsible_department_id=None,
        aggregate_version=2,
    )
    accepted = OfferQueueProjection(
        id=uuid4(),
        offered_by_id=uuid4(),
        title="Accepted offer",
        status="accepted",
        item_count=1,
        total_units=1,
        available_from=datetime(2026, 8, 9, tzinfo=UTC),
        available_until=datetime(2026, 8, 10, tzinfo=UTC),
        requested_return_at=None,
        responsible_department_id=uuid4(),
        aggregate_version=3,
    )
    review_forms = html_commands.offer_review_forms(
        offers=(accepted, pending), choices=choices, zone_name="Europe/Budapest"
    )
    assert [(outcome, label) for _offer, outcome, label, _form in review_forms] == [
        ("accepted", "Accept"),
        ("rejected", "Reject"),
    ]

    draft = _manifest(status="draft")
    sealed = _manifest(status="sealed")
    completed = _manifest(status="completed")
    state_forms = html_commands.manifest_state_forms(
        manifests=(draft, sealed, completed), zone_name="Europe/Budapest"
    )
    assert [action for _manifest, action, _label, _form in state_forms] == [
        "seal",
        "cancel_draft",
        "complete",
        "cancel_sealed",
    ]
    line_forms = html_commands.manifest_line_forms(
        manifests=(sealed, draft), choices=choices, zone_name="Europe/Budapest"
    )
    assert len(line_forms) == 1
    assert line_forms[0][0].id == draft.id


def _command_data() -> dict[str, object]:
    now = datetime(2026, 8, 9, 12, tzinfo=UTC)
    identifier = uuid4()
    return {
        "reason": "Run the governed browser command.",
        "idempotency_key": uuid4(),
        "edition_specific": True,
        "offer_id": identifier,
        "expected_version": 2,
        "outcome": "accepted",
        "responsible_department_id": identifier,
        "code": "synthetic-code",
        "kind": "asset",
        "role": "provider",
        "legal_name": "Synthetic Provider Kft.",
        "public_name": "Synthetic Provider",
        "provider_reference": "SUP-1",
        "website_url": "https://provider.example.test/",
        "subject_account_id": identifier,
        "party_id": identifier,
        "purpose": "storage",
        "label": "Synthetic label",
        "recipient_name": "Synthetic Recipient",
        "contact_email": "recipient@example.test",
        "contact_phone": "+3610000000",
        "postal_address": "Synthetic address",
        "access_instructions": "Use the signed entrance.",
        "retention_until": now,
        "name": "Synthetic item",
        "description": "Synthetic description",
        "storage_address_id": identifier,
        "external_owner_id": identifier,
        "provider_id": identifier,
        "vehicle_registration": "SYN-001",
        "venue_space_selection_id": identifier,
        "capacity_note": "One item",
        "catalog_code": "synthetic-item",
        "asset_type": "control-desk",
        "manufacturer": "Example",
        "model_name": "LX-1",
        "serial_number": "SYNTHETIC-1",
        "acquisition": "owned",
        "value_class": "high",
        "owner_kind": "organization",
        "owner_account_id": identifier,
        "owner_party_id": identifier,
        "stock_type": "cable",
        "unit": "piece",
        "initial_quantity": 5,
        "opens_node_id": identifier,
        "key_id": identifier,
        "responsible_account_id": identifier,
        "starts_at": now,
        "ends_at": now,
        "subject_kind": "asset",
        "subject_id": identifier,
        "label_code": "asset-label",
        "qr_identifier": "synthetic-opaque-label-token",
        "provider_account_id": identifier,
        "provider_party_id": identifier,
        "borrower_account_id": identifier,
        "borrower_party_id": identifier,
        "return_due_at": now,
        "return_address_id": identifier,
        "terms_reference": "TERMS-1",
        "quantity": 1,
        "notes": "Synthetic line",
        "manifest_number": "IN-BROWSER-1",
        "title": "Synthetic manifest",
        "source_node_id": identifier,
        "destination_node_id": identifier,
        "vehicle_id": identifier,
        "loading_starts_at": now,
        "loading_ends_at": now,
        "line_subject_kind": "asset",
        "line_subject_id": identifier,
        "line_quantity": 1,
        "line_packed_in_node_id": identifier,
        "line_notes": "Synthetic manifest line",
        "manifest_id": identifier,
        "action": "receive",
        "event_type": "move",
        "occurred_at": now,
        "to_custodian_account_id": identifier,
        "to_custodian_party_id": identifier,
        "condition_before": "intact",
        "condition_after": "intact",
        "evidence_reference": "scan-1",
        "expected_sequence": 0,
        "device_code": "stage-scanner-1",
        "snapshot_version": 1,
        "policy_version": "offline-v1",
        "expires_at": now,
        "operation_idempotency_key": uuid4(),
        "expected_subject_sequence": 0,
        "source_label_code": "source-label",
        "destination_label_code": "destination-label",
        "observed_condition": "intact",
    }


@pytest.mark.parametrize(
    ("action", "command_name"),
    [
        ("offer-review", "review_equipment_offer"),
        ("party-create", "create_logistics_party"),
        ("address-create", "create_restricted_logistics_address"),
        ("node-create", "create_logistics_node"),
        ("asset-create", "register_serialized_asset"),
        ("stock-create", "register_stock_lot"),
        ("key-create", "register_physical_key"),
        ("keyholder-assign", "assign_keyholder_responsibility"),
        ("label-create", "create_logistics_label"),
        ("agreement-create", "record_asset_agreement"),
        ("kit-create", "create_reusable_kit"),
        ("manifest-create", "create_logistics_manifest"),
        ("manifest-state", "change_manifest_state"),
        ("manifest-line-add", "add_manifest_line"),
        ("event-record", "record_logistics_event"),
        ("offline-reconcile", "ingest_offline_scan_batch"),
    ],
)
def test_every_browser_action_maps_to_one_typed_domain_command(
    action: str,
    command_name: str,
) -> None:
    actor = _actor()
    organization_id = uuid4()
    edition_id = uuid4()
    correlation_id = uuid4()
    with patch.object(
        html_commands,
        command_name,
        return_value=_result(),
    ) as command:
        result = html_commands.execute_staff_command(
            action=action,
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            data=_command_data(),
            correlation_id=correlation_id,
        )

    assert result.resulting_version == 2
    kwargs = command.call_args.kwargs
    assert kwargs["actor"] is actor
    assert kwargs["organization_id"] == organization_id
    assert kwargs["correlation_id"] == correlation_id
    assert kwargs["source_channel"] == "browser"


def test_unknown_browser_action_never_falls_through_to_a_domain_writer() -> None:
    with pytest.raises(LookupError, match="unsupported-action"):
        html_commands.execute_staff_command(
            action="unsupported-action",
            actor=_actor(),
            organization_id=uuid4(),
            edition_id=uuid4(),
            data=_command_data(),
            correlation_id=uuid4(),
        )


def test_global_browser_catalog_records_drop_the_edition_scope() -> None:
    data = _command_data()
    data["edition_specific"] = False
    with patch.object(
        html_commands,
        "create_logistics_node",
        return_value=_result(),
    ) as command:
        html_commands.execute_staff_command(
            action="node-create",
            actor=_actor(),
            organization_id=uuid4(),
            edition_id=uuid4(),
            data=data,
            correlation_id=uuid4(),
        )

    assert command.call_args.kwargs["edition_id"] is None
    locator = html_commands._locator(data)
    assert isinstance(locator.object_id, UUID)
