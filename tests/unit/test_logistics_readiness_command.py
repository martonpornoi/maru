from __future__ import annotations

import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


def test_logistics_readiness_command_emits_identifier_free_ready_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = {
        "status": "ready",
        "gates": {"triggers": "resolved", "functions": "resolved"},
    }
    monkeypatch.setattr(
        "maru.logistics.management.commands.check_logistics_readiness."
        "build_logistics_readiness_report",
        lambda: report,
    )
    stdout = StringIO()

    call_command("check_logistics_readiness", stdout=stdout)

    assert json.loads(stdout.getvalue()) == report


def test_logistics_readiness_command_fails_closed_unless_explicitly_inspecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = {
        "status": "blocked",
        "gates": {"catalog_inspection": "unresolved"},
    }
    monkeypatch.setattr(
        "maru.logistics.management.commands.check_logistics_readiness."
        "build_logistics_readiness_report",
        lambda: report,
    )

    with pytest.raises(CommandError, match="production readiness is blocked"):
        call_command("check_logistics_readiness", stdout=StringIO())

    stdout = StringIO()
    call_command("check_logistics_readiness", no_fail=True, stdout=stdout)
    assert json.loads(stdout.getvalue()) == report
