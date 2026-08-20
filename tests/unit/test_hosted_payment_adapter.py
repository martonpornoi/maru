import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Never
from urllib.error import URLError
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings

from maru.registration.payments import JsonHostedPaymentAdapter


class _Response:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, size: int) -> bytes:
        assert size == 32_768
        if isinstance(self.payload, bytes):
            return self.payload
        return json.dumps(self.payload).encode()


def _objects():
    provider = SimpleNamespace(
        credential_env_var="HOSTED_PROVIDER_KEY",
        api_base_url="https://payments.example/api",
    )
    intent = SimpleNamespace(
        id=uuid4(),
        amount_minor=12_500,
        currency="EUR",
        registration=SimpleNamespace(reference="REG-TEST-1"),
    )
    return provider, intent


@override_settings(
    MARU_PAYMENT_PROVIDER_HOSTS=("payments.example", "checkout.example"),
)
def test_json_hosted_payment_adapter_builds_minimized_checkout_request(
    monkeypatch,
) -> None:
    provider, intent = _objects()
    monkeypatch.setenv("HOSTED_PROVIDER_KEY", "synthetic-secret")
    expires_at = datetime.now(tz=UTC) + timedelta(minutes=20)
    captured = {}

    def success(request, *, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response(
            {
                "id": "provider-intent-1",
                "checkout_url": "https://checkout.example/session/1",
                "expires_at": expires_at.isoformat(),
            }
        )

    monkeypatch.setattr("maru.registration.payments.urlopen", success)
    checkout = JsonHostedPaymentAdapter().create_checkout(
        provider=provider,
        intent=intent,
        return_url="https://registration.example/payment-return",
    )

    assert checkout.provider_reference == "provider-intent-1"
    assert checkout.checkout_url == "https://checkout.example/session/1"
    assert checkout.expires_at == expires_at
    request = captured["request"]
    assert request.full_url == "https://payments.example/api/payment-intents"
    assert request.get_method() == "POST"
    assert json.loads(request.data)["amount_minor"] == 12_500
    assert request.get_header("Authorization") == "Bearer synthetic-secret"
    assert captured["timeout"] == 8


@override_settings(
    MARU_PAYMENT_PROVIDER_HOSTS=("payments.example", "checkout.example"),
)
def test_json_hosted_payment_adapter_fails_closed_for_provider_errors(
    monkeypatch,
) -> None:
    provider, intent = _objects()
    adapter = JsonHostedPaymentAdapter()
    monkeypatch.delenv("HOSTED_PROVIDER_KEY", raising=False)
    with pytest.raises(ValidationError, match="credential"):
        adapter.create_checkout(
            provider=provider,
            intent=intent,
            return_url="https://registration.example/return",
        )

    monkeypatch.setenv("HOSTED_PROVIDER_KEY", "synthetic-secret")

    def unavailable(*_args, **_kwargs) -> Never:
        raise URLError("unavailable")

    monkeypatch.setattr("maru.registration.payments.urlopen", unavailable)
    with pytest.raises(ValidationError, match="temporarily unavailable"):
        adapter.create_checkout(
            provider=provider,
            intent=intent,
            return_url="https://registration.example/return",
        )

    monkeypatch.setattr(
        "maru.registration.payments.urlopen",
        lambda *_args, **_kwargs: _Response(b"not-json"),
    )
    with pytest.raises(ValidationError, match="temporarily unavailable"):
        adapter.create_checkout(
            provider=provider,
            intent=intent,
            return_url="https://registration.example/return",
        )

    monkeypatch.setattr(
        "maru.registration.payments.urlopen",
        lambda *_args, **_kwargs: _Response({"id": "missing-fields"}),
    )
    with pytest.raises(ValidationError, match="invalid response"):
        adapter.create_checkout(
            provider=provider,
            intent=intent,
            return_url="https://registration.example/return",
        )

    monkeypatch.setattr(
        "maru.registration.payments.urlopen",
        lambda *_args, **_kwargs: _Response(
            {
                "id": "naive-expiry",
                "checkout_url": "https://checkout.example/session/2",
                "expires_at": "2030-01-01T10:00:00",
            }
        ),
    )
    with pytest.raises(ValidationError, match="invalid expiry"):
        adapter.create_checkout(
            provider=provider,
            intent=intent,
            return_url="https://registration.example/return",
        )
