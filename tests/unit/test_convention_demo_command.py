import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.core.management.base import CommandError
from scripts import convention_preview

from maru.demo.management.commands import prepare_convention_demo


def test_preparation_failure_keeps_private_exception_text_out_of_command_output(
    monkeypatch,
):
    secret = "Private-fixture-password-never-print"
    monkeypatch.setenv("MARU_DEMO_PASSWORDS", json.dumps({"password": secret}))
    monkeypatch.setattr(
        prepare_convention_demo,
        "bootstrap_demo_accounts",
        Mock(side_effect=RuntimeError(secret)),
    )
    with pytest.raises(CommandError) as result:
        prepare_convention_demo.Command().handle(phase="accounts")
    message = str(result.value)
    assert "Convention demo preparation failed (RuntimeError;" in message
    assert secret not in message
    assert "No ready preview was exposed" in message


def test_launcher_withholds_untrusted_command_error_and_stdout(monkeypatch):
    secret = "do-not-print-this-secret"
    run = Mock(return_value=SimpleNamespace(returncode=1, stdout=secret, stderr=secret))
    monkeypatch.setattr(convention_preview.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="command unavailable") as result:
        convention_preview._manage_json(
            SimpleNamespace(environment={}), "prepare_convention_demo", "content"
        )
    assert secret not in str(result.value)


@pytest.mark.parametrize("output", ["[]", "null", '"secret"'])
def test_launcher_requires_object_result(monkeypatch, output):
    monkeypatch.setattr(
        convention_preview.subprocess,
        "run",
        Mock(return_value=SimpleNamespace(returncode=0, stdout=output)),
    )
    with pytest.raises(RuntimeError, match="invalid result"):
        convention_preview._manage_json(
            SimpleNamespace(environment={}), "prepare_convention_demo", "content"
        )
