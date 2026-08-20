from io import BytesIO
from uuid import uuid4

import pytest
from rest_framework.exceptions import ParseError

from maru.logistics.models import MAX_LOGISTICS_REASON_LENGTH
from maru.logistics.parsers import ClosedLogisticsJSONParser
from maru.logistics.serializers import (
    ManifestCreateSerializer,
    MovementCommandSerializer,
    OfferReviewSerializer,
    OfflineBatchSerializer,
    RestrictedContactReadSerializer,
    SelfOfferSubmitSerializer,
    VersionedReasonSerializer,
)


def _minimal_offer_payload() -> dict[str, object]:
    return {
        "title": "Offered cables",
        "pickup_label": "Workshop",
        "pickup_postal_address": "Example address",
        "pickup_retention_until": "2026-09-01T00:00:00Z",
        "available_from": "2026-08-10T00:00:00Z",
        "available_until": "2026-08-20T00:00:00Z",
        "items": [
            {
                "kind": "bulk",
                "name": "Cables",
                "quantity": 3,
                "condition": "working",
                "ownership_statement": "I own these items.",
            }
        ],
        "reason": "Offer equipment.",
    }


@pytest.mark.parametrize(
    ("serializer_class", "payload", "nested_path"),
    [
        (
            SelfOfferSubmitSerializer,
            {
                "title": "Offered cables",
                "description": "",
                "pickup_label": "Workshop",
                "pickup_recipient_name": "",
                "pickup_postal_address": "Example address",
                "pickup_access_instructions": "",
                "pickup_retention_until": "2026-09-01T00:00:00Z",
                "available_from": "2026-08-10T00:00:00Z",
                "available_until": "2026-08-20T00:00:00Z",
                "items": [
                    {
                        "kind": "bulk",
                        "name": "Cables",
                        "description": "",
                        "quantity": 3,
                        "manufacturer": "",
                        "model_name": "",
                        "serial_number": "",
                        "condition": "working",
                        "value_class": "",
                        "ownership_statement": "I own these items.",
                        "foreign_owner": "must not be ignored",
                    }
                ],
                "reason": "Offer equipment.",
            },
            ("items", 0, "foreign_owner"),
        ),
        (
            MovementCommandSerializer,
            {
                "movement": {
                    "event_type": "move",
                    "subject": {
                        "kind": "asset",
                        "object_id": str(uuid4()),
                        "foreign_scope": str(uuid4()),
                    },
                    "occurred_at": "2026-08-09T12:00:00Z",
                },
                "expected_sequence": 0,
                "reason": "Move the asset.",
            },
            ("movement", "subject", "foreign_scope"),
        ),
        (
            OfflineBatchSerializer,
            {
                "device_code": "scanner-1",
                "snapshot_version": 1,
                "policy_version": "2026.08.09",
                "expires_at": "2026-08-09T13:00:00Z",
                "operations": [
                    {
                        "sequence": 1,
                        "idempotency_key": str(uuid4()),
                        "expected_subject_sequence": 0,
                        "action": "count",
                        "label_code": "BOX-1",
                        "occurred_at": "2026-08-09T12:00:00Z",
                        "foreign_payload": "must not be ignored",
                    }
                ],
                "reason": "Reconcile the offline scan.",
            },
            ("operations", 0, "foreign_payload"),
        ),
    ],
)
def test_nested_logistics_payloads_reject_unknown_fields(
    serializer_class: type,
    payload: dict[str, object],
    nested_path: tuple[object, ...],
) -> None:
    serializer = serializer_class(data=payload)

    assert serializer.is_valid() is False
    error: object = serializer.errors
    for key in nested_path:
        error = error[key]  # type: ignore[index]
    assert error


def test_manifest_nested_subject_rejects_uuid_alias() -> None:
    subject_id = "123e4567-e89b-42d3-a456-426614174000"
    serializer = ManifestCreateSerializer(
        data={
            "responsible_department_id": str(uuid4()),
            "manifest_number": "IN-001",
            "kind": "inbound",
            "title": "Stage delivery",
            "lines": [
                {
                    "subject": {
                        "kind": "asset",
                        "object_id": subject_id.upper(),
                    },
                    "quantity": 1,
                }
            ],
            "reason": "Create the checked manifest.",
        }
    )

    assert serializer.is_valid() is False
    assert "object_id" in serializer.errors["lines"][0]["subject"]


@pytest.mark.parametrize("alias", [True, "1", 1.0])
def test_logistics_json_integers_reject_alternate_types(alias: object) -> None:
    serializer = VersionedReasonSerializer(
        data={"expected_version": alias, "reason": "Advance the record."}
    )

    assert serializer.is_valid() is False
    assert "expected_version" in serializer.errors


def test_restricted_contact_access_purpose_is_closed() -> None:
    serializer = RestrictedContactReadSerializer(
        data={"purpose": "pickup", "access_purpose": "free text"}
    )

    assert serializer.is_valid() is False
    assert "access_purpose" in serializer.errors


def test_reason_fields_use_the_domain_limit() -> None:
    serializer = VersionedReasonSerializer(
        data={
            "expected_version": 1,
            "reason": "x" * (MAX_LOGISTICS_REASON_LENGTH + 1),
        }
    )

    assert serializer.is_valid() is False
    assert serializer.errors["reason"][0].code == "max_length"


def test_blank_backed_offer_fields_are_optional() -> None:
    serializer = SelfOfferSubmitSerializer(data=_minimal_offer_payload())

    assert serializer.is_valid(), serializer.errors
    assert "description" not in serializer.validated_data
    assert "manufacturer" not in serializer.validated_data["items"][0]


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        (
            {"outcome": "accepted", "expected_version": 1, "reason": "Accept."},
            "responsible_department_id",
        ),
        (
            {
                "outcome": "rejected",
                "responsible_department_id": str(uuid4()),
                "expected_version": 1,
                "reason": "Reject.",
            },
            "responsible_department_id",
        ),
    ],
)
def test_offer_review_enforces_action_specific_department_shape(
    payload: dict[str, object], field: str
) -> None:
    serializer = OfferReviewSerializer(data=payload)

    assert serializer.is_valid() is False
    assert field in serializer.errors


def test_logistics_datetime_inputs_require_explicit_offset() -> None:
    payload = _minimal_offer_payload()
    payload["available_from"] = "2026-10-25T02:30:00"
    serializer = SelfOfferSubmitSerializer(data=payload)

    assert serializer.is_valid() is False
    assert serializer.errors["available_from"][0].code == "explicit_offset"


def test_logistics_json_parser_rejects_duplicate_members() -> None:
    parser = ClosedLogisticsJSONParser()

    with pytest.raises(ParseError, match="duplicate object member"):
        parser.parse(BytesIO(b'{"reason":"first","reason":"second"}'))


def test_logistics_json_parser_does_not_expose_decoder_details() -> None:
    parser = ClosedLogisticsJSONParser()

    with pytest.raises(ParseError) as caught:
        parser.parse(BytesIO(b'{"private-field":"unfinished"'))

    assert str(caught.value.detail) == "JSON parse error - malformed document"
    assert "private-field" not in str(caught.value.detail)
