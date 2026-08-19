from __future__ import annotations

import base64
import json

import pytest
from django.test import override_settings

from maru.identity.invitation_token_keys import (
    InvitationTokenKeyConfigurationError,
    InvitationTokenKeyring,
    invitation_token_keyring,
    invitation_token_keys_are_ready,
)


def _encoded(character: bytes) -> str:
    return base64.b64encode(character * 32).decode("ascii")


def _json(**values: str) -> str:
    return json.dumps(values, sort_keys=True, separators=(",", ":"))


def test_active_and_fallback_keys_produce_stable_separate_candidates() -> None:
    keyring = InvitationTokenKeyring.from_json(
        active_key_id="digest-2026-08",
        keyring_json=_json(
            **{
                "digest-2026-07": _encoded(b"a"),
                "digest-2026-08": _encoded(b"b"),
            }
        ),
    )

    candidates = keyring.candidates(
        "synthetic-bearer-token",
        purpose="account-invitation-challenge",
    )

    assert tuple(key_id for key_id, _digest in candidates) == (
        "digest-2026-08",
        "digest-2026-07",
    )
    assert len({digest for _key_id, digest in candidates}) == 2
    assert all(len(digest) == 64 for _key_id, digest in candidates)
    assert candidates == keyring.candidates(
        "synthetic-bearer-token",
        purpose="account-invitation-challenge",
    )
    assert candidates[0][1] != keyring.digest(
        "synthetic-bearer-token",
        purpose="account-invitation-abuse-subject",
    )


@pytest.mark.parametrize(
    ("active_key_id", "keyring_json"),
    [
        ("", _json(valid=_encoded(b"a"))),
        ("missing", _json(valid=_encoded(b"a"))),
        ("unsafe/key", _json(**{"unsafe/key": _encoded(b"a")})),
        ("valid", "not-json"),
        ("valid", "{}"),
        ("valid", _json(valid="not-base64")),
        ("valid", _json(valid=base64.b64encode(b"short").decode("ascii"))),
        (
            "key-0",
            _json(
                **{f"key-{index}": _encoded(bytes([65 + index])) for index in range(5)}
            ),
        ),
    ],
)
def test_malformed_key_configuration_fails_without_releasing_values(
    active_key_id: str,
    keyring_json: str,
) -> None:
    with pytest.raises(InvitationTokenKeyConfigurationError) as captured:
        InvitationTokenKeyring.from_json(
            active_key_id=active_key_id,
            keyring_json=keyring_json,
        )

    message = str(captured.value)
    if active_key_id:
        assert active_key_id not in message
    assert keyring_json not in message


@override_settings(
    MARU_IDENTITY_INVITATION_DIGEST_ACTIVE_KEY_ID="digest-active",
    MARU_IDENTITY_INVITATION_DIGEST_KEYS_JSON=_json(
        **{"digest-active": _encoded(b"z")}
    ),
)
def test_settings_loader_and_readiness_are_value_safe() -> None:
    assert invitation_token_keyring().active_key_id == "digest-active"
    assert invitation_token_keys_are_ready()


@override_settings(
    MARU_IDENTITY_INVITATION_DIGEST_ACTIVE_KEY_ID="",
    MARU_IDENTITY_INVITATION_DIGEST_KEYS_JSON="",
)
def test_missing_settings_are_not_ready() -> None:
    assert not invitation_token_keys_are_ready()
