"""Bounded Logistics contact-retention command boundary."""

from __future__ import annotations

from argparse import ArgumentTypeError
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.core.management.base import CommandError, CommandParser
from django.db import DatabaseError

from maru.logistics.management.commands import dispose_expired_logistics_contacts


def test_canonical_uuid_parser_rejects_ambiguous_spellings() -> None:
    value = uuid4()
    assert dispose_expired_logistics_contacts._canonical_uuid(str(value)) == value

    for invalid in ("not-a-uuid", str(value).upper(), value.hex):
        with pytest.raises(ArgumentTypeError):
            dispose_expired_logistics_contacts._canonical_uuid(invalid)


def test_retention_command_arguments_require_one_explicit_scope() -> None:
    command = dispose_expired_logistics_contacts.Command()
    parser = CommandParser()
    command.add_arguments(parser)
    organization_id = uuid4()
    edition_id = uuid4()

    edition = parser.parse_args(
        [
            "--organization-id",
            str(organization_id),
            "--edition-id",
            str(edition_id),
            "--limit",
            "12",
        ]
    )
    assert edition.organization_id == organization_id
    assert edition.edition_id == edition_id
    assert edition.limit == 12

    global_scope = parser.parse_args(
        ["--organization-id", str(organization_id), "--global-scope"]
    )
    assert global_scope.global_scope
    assert global_scope.edition_id is None


@pytest.mark.parametrize(
    ("options", "message"),
    [
        (
            {"organization_id": "not-a-uuid", "edition_id": None, "limit": 1},
            "organization UUID",
        ),
        (
            {"organization_id": uuid4(), "edition_id": "bad", "limit": 1},
            "canonical edition UUID",
        ),
        (
            {"organization_id": uuid4(), "edition_id": None, "limit": True},
            "must be an integer",
        ),
    ],
)
def test_retention_command_rejects_untyped_programmatic_options(
    options: dict[str, object], message: str
) -> None:
    with pytest.raises(CommandError, match=message):
        dispose_expired_logistics_contacts.Command().handle(**options)


def test_retention_command_forwards_exact_scope_and_reports_bounded_count() -> None:
    organization_id = uuid4()
    edition_id = uuid4()
    correlation_id = uuid4()
    command = dispose_expired_logistics_contacts.Command()
    command.stdout = MagicMock()
    with patch(
        "maru.logistics.management.commands.dispose_expired_logistics_contacts."
        "dispose_expired_restricted_addresses",
        return_value=(uuid4(), uuid4()),
    ) as dispose:
        command.handle(
            organization_id=organization_id,
            edition_id=edition_id,
            limit=25,
            correlation_id=correlation_id,
        )
    dispose.assert_called_once_with(
        organization_id=organization_id,
        edition_id=edition_id,
        correlation_id=correlation_id,
        limit=25,
    )
    assert "disposed=2" in command.stdout.write.call_args.args[0]


@pytest.mark.parametrize(
    "error",
    [
        DatabaseError("database unavailable"),
        ValidationError("invalid batch"),
        ValueError("invalid limit"),
    ],
)
def test_retention_command_maps_expected_failures_to_command_error(
    error: Exception,
) -> None:
    with (
        patch(
            "maru.logistics.management.commands.dispose_expired_logistics_contacts."
            "dispose_expired_restricted_addresses",
            side_effect=error,
        ),
        pytest.raises(CommandError),
    ):
        dispose_expired_logistics_contacts.Command().handle(
            organization_id=uuid4(),
            edition_id=None,
            limit=1,
        )
