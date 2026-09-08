"""Live physical proof requires both exact receipt identity and owner scope."""

from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.scheduling.writer_boundary import (
    _command_receipt_scope,
    _require_active_receipt,
    require_scheduling_writer,
    scheduling_writer,
)


def test_receipt_identity_does_not_itself_grant_writer_authority():
    receipt_id = uuid4()
    with _command_receipt_scope(receipt_id), pytest.raises(ValidationError):
        _require_active_receipt(receipt_id)


def test_owner_scope_requires_exact_live_receipt():
    receipt_id = uuid4()
    with scheduling_writer():
        with pytest.raises(ValidationError):
            _require_active_receipt(receipt_id)
        with _command_receipt_scope(receipt_id):
            _require_active_receipt(receipt_id)
            with pytest.raises(ValidationError):
                _require_active_receipt(uuid4())
        with pytest.raises(ValidationError):
            _require_active_receipt(receipt_id)


def test_nested_scopes_restore_outer_proof_and_reset_after_failure():
    outer, inner = uuid4(), uuid4()

    def fail_inner_command():
        with scheduling_writer(), _command_receipt_scope(inner):
            _require_active_receipt(inner)
            raise RuntimeError("synthetic command rollback")

    with scheduling_writer(), _command_receipt_scope(outer):
        with pytest.raises(RuntimeError):
            fail_inner_command()
        _require_active_receipt(outer)
        require_scheduling_writer()
    with pytest.raises(ValidationError):
        require_scheduling_writer()
    with scheduling_writer(), pytest.raises(ValidationError):
        _require_active_receipt(outer)
