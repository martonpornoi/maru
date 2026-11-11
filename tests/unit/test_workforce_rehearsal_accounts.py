from unittest.mock import MagicMock, patch

import pytest
from scripts import workforce_rehearsal_accounts as preparation


def test_prepared_sign_ins_refuse_a_different_settings_environment(
    tmp_path, monkeypatch
):
    directory = tmp_path / "owned"
    directory.mkdir()
    (directory / "resource.json").write_text("{}")
    monkeypatch.setenv("MARU_WORKFORCE_REHEARSAL_DIRECTORY", str(directory))
    monkeypatch.setenv("MARU_WORKFORCE_REHEARSAL", "owned-loopback")
    monkeypatch.setattr("sys.argv", ["prepare", "queue"])
    cursor = MagicMock()
    monkeypatch.setattr(preparation.connection, "cursor", cursor)
    with (
        patch("maru.identity.models.Account.objects.get") as get_account,
        pytest.raises(RuntimeError, match="new owned strict rehearsal"),
    ):
        preparation.main()
    cursor.assert_not_called()
    get_account.assert_not_called()
    assert not (directory / "identities.private.json").exists()
