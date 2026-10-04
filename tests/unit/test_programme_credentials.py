"""Copy-only credential delivery, expiry and failure isolation."""

from unittest.mock import Mock

import pytest

from tests.rehearsals import programme_credentials as credentials


@pytest.fixture
def window():
    window = credentials.CredentialWindow.__new__(credentials.CredentialWindow)
    window.root = Mock()
    window.clipboard = Mock()
    window.status = Mock()
    window.role = Mock()
    window.role.current.return_value = 0
    window.email = Mock()
    window.copy_email = Mock()
    window.copy_password = Mock()
    window.stop_requested = False
    window.failed = False
    window.deadline = None
    window.people = []
    return window


def accounts():
    return [
        {
            "role": "organizer",
            "email": "local@example.invalid",
            "password": "private-canary",
        }
    ]


def test_ready_only_displays_role_and_email_without_copying(window):
    window.show_accounts(accounts())
    window.clipboard.copy.assert_not_called()
    window.role.configure.assert_called_once_with(values=["organizer"])
    window.email.set.assert_called_once_with("local@example.invalid")
    window.root.deiconify.assert_called_once()


def test_deliberate_copy_expires_at_deadline(window, monkeypatch):
    window.show_accounts(accounts())
    clock = Mock(return_value=10)
    monkeypatch.setattr(credentials.time, "monotonic", clock)
    window.copy("password")
    window.clipboard.copy.assert_called_once_with("private-canary")
    assert window.deadline == 40
    window.clipboard.clear.reset_mock()
    clock.return_value = 39
    window.pump()
    window.clipboard.clear.assert_not_called()
    clock.return_value = 40
    window.pump()
    window.clipboard.clear.assert_called_once()
    assert window.deadline is None


def test_failed_copy_never_reports_copied_or_retries_automatically(window):
    window.show_accounts(accounts())
    window.clipboard.copy.side_effect = OSError("private-canary")
    window.copy("password")
    assert window.deadline is None
    assert window.status.set.call_args.args == (
        "Copy failed. Close other clipboard tools and try again.",
    )
    window.pump()
    window.clipboard.copy.assert_called_once()


def test_stop_drops_accounts_and_disables_copy_and_late_ready(window):
    window.show_accounts(accounts())
    window.copy("password")
    window.request_stop()
    assert window.people == []
    assert window.stop_requested
    assert window.deadline is None
    window.copy_password.state.assert_called_with(["disabled"])
    window.clipboard.copy.reset_mock()
    window.copy("password")
    window.show_accounts(accounts())
    assert window.people == []
    window.clipboard.copy.assert_not_called()


def test_clipboard_busy_retries_cleanup_without_copying(window):
    window.show_accounts(accounts())
    window.clipboard.clear.side_effect = [OSError("busy"), None]
    assert not window.expire_copy()
    assert window.deadline == 0
    window.pump()
    assert window.deadline is None
    window.clipboard.copy.assert_not_called()


def test_role_change_clears_previous_copy(window):
    window.show_accounts(accounts())
    window.copy("password")
    window.clipboard.clear.reset_mock()
    window._selected()
    window.clipboard.clear.assert_called_once()
    assert window.deadline is None


def test_callback_exception_never_logs_exception_arguments(window, capsys):
    window.show_accounts(accounts())
    window._callback_failed(ValueError, ValueError("private-canary"), None)
    assert window.failed
    assert window.stop_requested
    assert window.people == []
    assert "private-canary" not in str(window.status.set.call_args)
    assert capsys.readouterr() == ("", "")
    with pytest.raises(OSError, match="Account window failed"):
        window.close()


def test_close_reports_uncleared_clipboard_without_claiming_cleanup(
    window, monkeypatch
):
    window.clipboard.clear.side_effect = OSError("busy")
    monkeypatch.setattr(credentials.time, "monotonic", Mock(side_effect=[0, 6]))
    with pytest.raises(OSError, match="Clipboard cleanup failed"):
        window.close()
    window.root.destroy.assert_called_once()
