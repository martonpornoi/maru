from __future__ import annotations

import json

import pytest
from scripts import oci_runtime_bootstrap as bootstrap

from maru.authorization.models import CapabilityGrant, RoleAssignment, RoleBundle
from maru.identity.models import Account
from maru.organizations.models import Organization

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


def _enable_synthetic_fence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "maru.settings.test")
    monkeypatch.setenv("MARU_SYNTHETIC_OCI_REHEARSAL", "true")


def _output(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    return json.loads(capsys.readouterr().out)


def test_bootstrap_creates_one_non_login_actor_and_replays_idempotently(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _enable_synthetic_fence(monkeypatch)

    assert bootstrap.main() == 0
    first = _output(capsys)
    assert bootstrap.main() == 0
    replay = _output(capsys)

    account = Account.objects.get(pk=bootstrap.ACTOR_ID)
    assert account.email == bootstrap.ACTOR_EMAIL
    assert account.is_active
    assert account.is_platform_administrator
    assert account.is_staff
    assert account.is_superuser
    assert not account.has_usable_password()
    assert first == {
        "schema_version": 1,
        "status": "created",
        "synthetic_only": True,
        "login_enabled": False,
        "created": {"platform_administrators": 1},
        "totals": {
            "accounts": 1,
            "platform_administrators": 1,
            "organizations": 0,
            "ordinary_authority_records": 0,
        },
    }
    assert replay["status"] == "already_present"
    assert replay["created"] == {"platform_administrators": 0}
    assert Account.objects.count() == 1
    assert not Organization.objects.exists()
    assert not CapabilityGrant.objects.exists()
    assert not RoleAssignment.objects.exists()
    assert not RoleBundle.objects.exists()
    serialized = json.dumps(replay)
    assert bootstrap.ACTOR_EMAIL not in serialized
    assert str(bootstrap.ACTOR_ID) not in serialized


def test_bootstrap_refuses_reserved_identity_collision_without_repair(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _enable_synthetic_fence(monkeypatch)
    collision = Account.objects.create_user(
        id=bootstrap.ACTOR_ID,
        email="different.synthetic.actor@maru.invalid",
        password=None,
    )

    assert bootstrap.main() == 3

    assert _output(capsys) == {"status": "failed", "code": "fixture_conflict"}
    collision.refresh_from_db()
    assert collision.email == "different.synthetic.actor@maru.invalid"
    assert Account.objects.count() == 1


def test_bootstrap_refuses_modified_expected_actor_without_repair(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _enable_synthetic_fence(monkeypatch)
    assert bootstrap.main() == 0
    _output(capsys)
    account = Account.objects.get(pk=bootstrap.ACTOR_ID)
    account.set_password("Synthetic-only-but-still-not-allowed-2026!")
    account.save(update_fields=("password",))

    assert bootstrap.main() == 3

    assert _output(capsys) == {"status": "failed", "code": "fixture_conflict"}
    account.refresh_from_db()
    assert account.has_usable_password()


def test_bootstrap_requires_explicit_local_or_test_synthetic_fence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "maru.settings.production")
    monkeypatch.delenv("MARU_SYNTHETIC_OCI_REHEARSAL", raising=False)

    assert bootstrap.main() == 2

    assert _output(capsys) == {"status": "failed", "code": "environment_invalid"}
    assert not Account.objects.exists()
