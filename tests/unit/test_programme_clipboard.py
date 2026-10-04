"""Privacy-format failure and clipboard ownership races at the Windows boundary."""

import ctypes
from unittest.mock import Mock

import pytest

from tests.rehearsals.programme_clipboard import PrivateClipboard


@pytest.fixture
def clipboard():
    clipboard = PrivateClipboard.__new__(PrivateClipboard)
    clipboard.window = 123
    clipboard.sequence = None
    clipboard.open = Mock(return_value=True)
    clipboard.close = Mock(return_value=True)
    clipboard.empty = Mock(return_value=True)
    clipboard.serial = Mock(return_value=17)
    clipboard.owner = Mock(return_value=123)
    clipboard.formats = (49152, 49153, 49154)
    clipboard._put_bytes = Mock()
    return clipboard


def test_all_exclusions_must_precede_text(clipboard):
    clipboard.close.side_effect = lambda: setattr(clipboard.serial, "return_value", 20)
    clipboard.copy("fictional")
    calls = clipboard._put_bytes.call_args_list
    assert [call.args for call in calls[:3]] == [
        (49152, bytes(4)),
        (49153, bytes(4)),
        (49154, bytes(4)),
    ]
    assert calls[3].args == (13, "fictional\0".encode("utf-16-le"))
    assert clipboard.sequence == 20
    clipboard.close.assert_called_once()


@pytest.mark.parametrize("failed_index", [0, 1, 2])
def test_missing_exclusion_never_publishes_plaintext(clipboard, failed_index):
    clipboard._put_bytes.side_effect = [None] * failed_index + [OSError("failed")]
    with pytest.raises(OSError, match="failed"):
        clipboard.copy("private-canary")
    assert all(call.args[0] != 13 for call in clipboard._put_bytes.call_args_list)
    assert clipboard.sequence is None
    clipboard.close.assert_called_once()


def test_busy_clipboard_never_overwrites_current_content(clipboard):
    clipboard.open.return_value = False
    with pytest.raises(OSError, match="busy"):
        clipboard.copy("private-canary")
    clipboard.empty.assert_not_called()
    clipboard._put_bytes.assert_not_called()


@pytest.mark.parametrize(("owner", "sequence"), [(987, 17), (123, 18)])
def test_later_or_foreign_copy_survives_cleanup(clipboard, owner, sequence):
    clipboard.sequence = 17
    clipboard.owner.return_value = owner
    clipboard.serial.return_value = sequence
    clipboard.clear()
    clipboard.empty.assert_not_called()
    assert clipboard.sequence is None
    clipboard.close.assert_called_once()


def test_only_unchanged_owned_copy_is_cleared(clipboard):
    clipboard.copy("private-canary")
    clipboard.empty.reset_mock()
    clipboard.clear()
    clipboard.empty.assert_called_once()
    assert clipboard.sequence is None


def test_failed_clear_retains_ownership_for_retry(clipboard):
    clipboard.sequence = 17
    clipboard.empty.side_effect = [False, True]
    with pytest.raises(OSError, match="could not be cleared"):
        clipboard.clear()
    assert clipboard.sequence == 17
    clipboard.clear()
    assert clipboard.sequence is None


@pytest.mark.parametrize("transferred", [False, True])
def test_native_memory_is_freed_only_without_ownership_transfer(transferred):
    clipboard = PrivateClipboard.__new__(PrivateClipboard)
    memory = ctypes.create_string_buffer(16)
    clipboard.allocate = Mock(return_value=987)
    clipboard.lock = Mock(return_value=ctypes.addressof(memory))
    clipboard.unlock = Mock()
    clipboard.put = Mock(return_value=987 if transferred else 0)
    clipboard.free = Mock()
    if transferred:
        clipboard._put_bytes(13, b"test")
        clipboard.free.assert_not_called()
    else:
        with pytest.raises(OSError, match="transfer failed"):
            clipboard._put_bytes(13, b"test")
        clipboard.free.assert_called_once_with(987)
    assert memory.raw[:4] == b"test"
    clipboard.unlock.assert_called_once_with(987)
