import pytest
from django.core.exceptions import ValidationError

from maru.audit.models import validate_safe_metadata


def test_safe_audit_metadata_accepts_only_bounded_typed_values() -> None:
    validate_safe_metadata(
        {
            "client_kind": "staff-console",
            "http_method": "POST",
            "policy_version": "2026-07-26.1",
            "target_count": 2,
        }
    )


@pytest.mark.parametrize(
    "metadata",
    [
        {"message_body": "classified content"},
        {"target_count": True},
        {"target_count": -1},
        {"route_name": ["not", "scalar"]},
        {"remote_provider": "x" * 161},
    ],
)
def test_safe_audit_metadata_rejects_unbounded_or_protected_payloads(
    metadata: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="Audit"):
        validate_safe_metadata(metadata)
