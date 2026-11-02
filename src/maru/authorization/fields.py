"""Database clock fields for retained authority creation evidence."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, override

from django.db import models
from django.db.models.functions import Now

from maru.authorization.programme_role_writer import _programme_role_writer_is_active

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    _DateTimeField = models.DateTimeField[Any, datetime]
else:
    _DateTimeField = models.DateTimeField


class DatabaseCreatedAtField(_DateTimeField):
    """Stamp new authority records in their actual INSERT statement.

    PostgreSQL renders ``Now`` as ``STATEMENT_TIMESTAMP()``, rather than the
    transaction start. Returning the stored column also keeps ordinary create
    and bulk-create results as actual aware datetimes, without a second read.
    The pinned Django INSERT returning protocol is covered by native tests.
    """

    @property
    def db_returning(self) -> bool:
        """Include the generated creation time in INSERT's returned columns.

        Returns
        -------
        bool
            True so PostgreSQL returns the actual stored timestamp.
        """
        return True

    @override
    def pre_save(self, model_instance: models.Model, add: bool) -> Any:
        """Prepare the database creation expression for a new record only.

        Parameters
        ----------
        model_instance : models.Model
            Record being persisted through Django's normal INSERT protocol.
        add : bool
            Whether this operation creates the record.

        Returns
        -------
        Any
            The native Now expression on creation, otherwise the ordinary field
            value. Django replaces the expression with the INSERT return value.
        """
        if self.auto_now_add and add:
            value = Now()
            setattr(model_instance, self.attname, value)
            return value
        return super().pre_save(model_instance, add)


class ProgrammeRequestTimeField(_DateTimeField):
    """Generate an owning proposal's durable clock in its actual INSERT.

    Explicit raw native probes outside the owner scope retain supplied values,
    so future/pre-transaction rejection remains exercised by the real guards.
    """

    def __init__(self, *args: Any, deadline: bool = False, **kwargs: Any) -> None:
        """Configure either the request instant or its elapsed approval deadline.

        Parameters
        ----------
        *args : Any
            Positional Django field configuration.
        deadline : bool, default=False
            Add the fixed elapsed 168-hour approval window to the INSERT instant.
        **kwargs : Any
            Remaining Django field configuration.
        """
        self.deadline = deadline
        super().__init__(*args, **kwargs)

    @property
    def db_returning(self) -> bool:
        """Return the stored native value after the ordinary INSERT.

        Returns
        -------
        bool
            True so callers receive an aware datetime rather than an expression.
        """
        return True

    @override
    def deconstruct(self) -> tuple[str, str, Sequence[Any], dict[str, Any]]:
        """Retain the closed deadline flag in ORM migration state.

        Returns
        -------
        tuple[str, str, Sequence[Any], dict[str, Any]]
            Django's field name, type path, positional and keyword configuration.
        """
        name, path, args, kwargs = super().deconstruct()
        if self.deadline:
            kwargs["deadline"] = True
        return name, path, args, kwargs

    @override
    def pre_save(self, model_instance: models.Model, add: bool) -> Any:
        """Prepare native time only for an already admitted owning append.

        Parameters
        ----------
        model_instance : models.Model
            Proposal being inserted through its existing owning writer.
        add : bool
            Whether this operation creates the record.

        Returns
        -------
        Any
            The native statement expression inside the owner scope, otherwise
            the unchanged supplied value for direct native guard probes.
        """
        if add and _programme_role_writer_is_active():
            value = (
                models.Func(
                    Now(),
                    template="(%(expressions)s + interval '168 hours')",
                    output_field=models.DateTimeField(),
                )
                if self.deadline
                else Now()
            )
            setattr(model_instance, self.attname, value)
            return value
        return super().pre_save(model_instance, add)
