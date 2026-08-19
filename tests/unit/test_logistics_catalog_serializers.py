from typing import Any, cast
from uuid import uuid4

from maru.logistics.catalog_serializers import (
    LogisticsPartyCreateSerializer,
    ManifestLineAddSerializer,
    ManifestReceiptSerializer,
    RestrictedAddressCreateSerializer,
    ReusableKitCreateSerializer,
    StockLotCreateSerializer,
)


def test_party_serializer_rejects_unknown_nested_profile_field() -> None:
    serializer = LogisticsPartyCreateSerializer(
        data={
            "code": "road-haulage",
            "profile": {
                "kind": "business",
                "role": "provider",
                "legal_name": "Example Road Haulage Kft.",
                "public_name": "Example Haulage",
                "undeclared_contact": "must not be ignored",
            },
            "reason": "Register the transport provider.",
        }
    )

    assert not serializer.is_valid()
    assert "undeclared_contact" in serializer.errors["profile"]


def test_party_serializer_matches_model_website_length_bound() -> None:
    serializer = LogisticsPartyCreateSerializer()
    profile = cast(Any, serializer.fields["profile"])

    assert profile.fields["website_url"].max_length == 2_000


def test_restricted_contact_serializer_matches_minimized_contact_bounds() -> None:
    serializer = RestrictedAddressCreateSerializer(
        data={
            "purpose": "storage",
            "label": "Off-site storage",
            "contact_email": f"{'a' * 245}@example.test",
            "contact_phone": "06 1 555 0100",
            "postal_address": "Synthetic Logistics Park 1, Budapest",
            "reason": "Register a bounded storage contact.",
        }
    )

    assert not serializer.is_valid()
    assert "contact_email" in serializer.errors
    assert "contact_phone" in serializer.errors

    field = cast(Any, RestrictedAddressCreateSerializer().fields["contact_email"])
    assert field.max_length == 254


def test_kit_serializer_rejects_uuid_alias_and_unknown_deep_field() -> None:
    object_id = uuid4()
    serializer = ReusableKitCreateSerializer(
        data={
            "code": "stage-left-audio",
            "name": "Stage-left audio kit",
            "lines": [
                {
                    "subject": {
                        "kind": "asset",
                        "object_id": str(object_id).upper(),
                        "foreign_tenant_id": str(uuid4()),
                    },
                    "quantity": 1,
                }
            ],
            "reason": "Register the reusable stage kit.",
        }
    )

    assert not serializer.is_valid()
    subject_errors = serializer.errors["lines"][0]["subject"]
    assert "foreign_tenant_id" in subject_errors

    alias_serializer = ReusableKitCreateSerializer(
        data={
            "code": "stage-left-audio",
            "name": "Stage-left audio kit",
            "lines": [
                {
                    "subject": {
                        "kind": "asset",
                        "object_id": str(object_id).upper(),
                    },
                    "quantity": 1,
                }
            ],
            "reason": "Register the reusable stage kit.",
        }
    )

    assert not alias_serializer.is_valid()
    assert "object_id" in alias_serializer.errors["lines"][0]["subject"]


def test_manifest_line_serializer_accepts_only_json_integer_versions() -> None:
    serializer = ManifestLineAddSerializer(
        data={
            "expected_version": "1",
            "line": {
                "subject": {
                    "kind": "stock_lot",
                    "object_id": str(uuid4()),
                },
                "quantity": True,
            },
            "reason": "Pack the counted stock lot.",
        }
    )

    assert not serializer.is_valid()
    assert "expected_version" in serializer.errors
    assert "quantity" in serializer.errors["line"]


def test_manifest_line_serializer_rejects_client_authored_label_snapshot() -> None:
    serializer = ManifestLineAddSerializer(
        data={
            "expected_version": 1,
            "line": {
                "subject": {
                    "kind": "asset",
                    "object_id": str(uuid4()),
                },
                "label_snapshot": "Client-authored label",
                "quantity": 1,
            },
            "reason": "The service derives authoritative display labels.",
        }
    )

    assert not serializer.is_valid()
    assert "label_snapshot" in serializer.errors["line"]


def test_manifest_receipt_serializer_is_closed_and_canonical() -> None:
    unknown = ManifestReceiptSerializer(
        data={
            "expected_sequence": 2,
            "occurred_at": "2026-08-09T14:00:00+02:00",
            "condition_after": "Received intact",
            "reason": "Receive the checked Stage Tech box.",
            "destination_override": str(uuid4()),
        }
    )
    assert not unknown.is_valid()
    assert "destination_override" in unknown.errors

    noncanonical = ManifestReceiptSerializer(
        data={
            "expected_sequence": "2",
            "occurred_at": "2026-08-09T14:00:00+02:00",
            "condition_after": "Received intact",
            "reason": "Receive the checked Stage Tech box.",
        }
    )
    assert not noncanonical.is_valid()
    assert "expected_sequence" in noncanonical.errors


def test_stock_serializer_accepts_closed_canonical_payload() -> None:
    serializer = StockLotCreateSerializer(
        data={
            "catalog_code": "cable-ties",
            "name": "Reusable cable ties",
            "stock_type": "fastener",
            "unit": "piece",
            "initial_quantity": 120,
            "owner": {"kind": "organization"},
            "reason": "Register the logistics consumable.",
        }
    )

    assert serializer.is_valid(), serializer.errors
