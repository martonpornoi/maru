"""Fail-closed native clock validation for new controller provenance."""

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.db import DatabaseError, models
from django.db.models.functions import Now

from maru.authorization import commands
from maru.authorization.fields import ProgrammeRequestTimeField
from maru.authorization.programme_role_writer import _programme_role_writer
from maru.authorization.services import AuthorizationDenied

NOW = datetime(2030, 8, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    "row",
    [
        (NOW,),
        None,
        (),
        (NOW, NOW),
        (None,),
        ("2030-08-01",),
        (NOW.replace(tzinfo=None),),
    ],
)
def test_new_controller_provenance_requires_one_aware_database_instant(
    monkeypatch, row
):
    database = MagicMock()
    cursor = database.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = row
    monkeypatch.setattr(commands, "connection", database)
    if row == (NOW,):
        assert commands._database_control_time() == NOW
    else:
        with pytest.raises(AuthorizationDenied, match="unavailable"):
            commands._database_control_time()
    cursor.execute.assert_called_once_with("SELECT pg_catalog.clock_timestamp()")


def test_new_controller_provenance_does_not_fall_back_after_clock_failure(monkeypatch):
    database = MagicMock()
    database.cursor.side_effect = DatabaseError("synthetic unavailable clock")
    monkeypatch.setattr(commands, "connection", database)
    with pytest.raises(DatabaseError, match="synthetic unavailable clock"):
        commands._database_control_time()


@pytest.mark.parametrize("deadline", [False, True])
@pytest.mark.parametrize("owning_writer", [False, True])
def test_proposal_clock_is_owned_but_raw_guard_inputs_remain_exact(
    deadline, owning_writer
):
    field = ProgrammeRequestTimeField(deadline=deadline)
    field.set_attributes_from_name("observed")
    supplied = NOW + timedelta(days=1)
    record = SimpleNamespace(observed=supplied)
    with _programme_role_writer() if owning_writer else nullcontext():
        value = field.pre_save(record, add=True)
    if not owning_writer:
        assert value is supplied
        assert record.observed is supplied
    else:
        assert isinstance(value, models.Func if deadline else Now)
        assert record.observed is value
    assert field.db_returning
    _name, _path, _args, kwargs = field.deconstruct()
    assert kwargs.get("deadline", False) is deadline
