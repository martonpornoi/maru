"""Transaction and process guards for Applications-owned Programme writes."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.core.exceptions import ValidationError

from maru.applications import programme_writer_boundary as writer_boundary


def _connection(*, in_atomic_block: bool, previous: str | None = None) -> MagicMock:
    cursor = MagicMock()
    cursor.fetchone.return_value = (previous,)
    cursor_context = MagicMock()
    cursor_context.__enter__.return_value = cursor
    return SimpleNamespace(
        in_atomic_block=in_atomic_block,
        needs_rollback=False,
        cursor=MagicMock(return_value=cursor_context),
        _cursor=cursor,
    )


def test_database_writer_requires_an_atomic_transaction() -> None:
    connection = _connection(in_atomic_block=False)
    with (
        patch.object(writer_boundary, "connection", connection),
        pytest.raises(RuntimeError, match="atomic transaction"),
        writer_boundary.programme_application_database_writer(),
    ):
        pytest.fail("The writer must not open outside a transaction.")


def test_database_writer_sets_and_restores_the_exact_local_guc() -> None:
    connection = _connection(in_atomic_block=True, previous="prior")
    with patch.object(writer_boundary, "connection", connection):
        with writer_boundary.programme_application_database_writer():
            writer_boundary.require_programme_application_writer()
        with pytest.raises(ValidationError) as outside:
            writer_boundary.require_programme_application_writer()

    assert outside.value.code == "programme_application_writer_required"
    assert connection._cursor.execute.call_args_list == [
        (
            (
                "SELECT pg_catalog.current_setting(%s, true)",
                [writer_boundary.PROGRAMME_APPLICATION_WRITER_SETTING],
            ),
        ),
        (
            (
                "SELECT pg_catalog.set_config(%s, 'on', true)",
                [writer_boundary.PROGRAMME_APPLICATION_WRITER_SETTING],
            ),
        ),
        (
            (
                "SELECT pg_catalog.set_config(%s, %s, true)",
                [writer_boundary.PROGRAMME_APPLICATION_WRITER_SETTING, "prior"],
            ),
        ),
    ]


def test_database_writer_restores_a_missing_setting_after_an_error() -> None:
    connection = _connection(in_atomic_block=True)
    with (
        patch.object(writer_boundary, "connection", connection),
        pytest.raises(LookupError),
        writer_boundary.programme_application_database_writer(),
    ):
        raise LookupError

    assert connection._cursor.execute.call_args_list[-1].args[1] == [
        writer_boundary.PROGRAMME_APPLICATION_WRITER_SETTING,
        "",
    ]


def test_database_writer_does_not_mask_a_broken_transaction_error() -> None:
    """Let the original database integrity error escape unchanged."""
    connection = _connection(in_atomic_block=True, previous="prior")

    def exercise_broken_transaction() -> None:
        with writer_boundary.programme_application_database_writer():
            connection.needs_rollback = True
            raise LookupError("original integrity error")

    with (
        patch.object(writer_boundary, "connection", connection),
        pytest.raises(LookupError, match="original integrity error"),
    ):
        exercise_broken_transaction()

    assert len(connection._cursor.execute.call_args_list) == 2
