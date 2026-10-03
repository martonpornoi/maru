"""Account confidentiality and shutdown boundaries of the local facilitator."""

import base64
import io
import json
import queue
from unittest.mock import Mock

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric import rsa

from tests.rehearsals import programme_hands_on as hands_on
from tests.rehearsals.programme_local_session import seal_handoff


@pytest.fixture
def synchronous_child(monkeypatch):
    monkeypatch.setattr(hands_on.threading, "Thread", Mock())
    monkeypatch.setattr(
        hands_on, "interruptible_messages", lambda stream, _send: stream
    )


def test_interrupt_requests_stop_and_still_reads_disposal(monkeypatch):
    messages = Mock()
    messages.get.side_effect = [
        queue.Empty,
        KeyboardInterrupt,
        '{"state":"disposed"}\n',
        None,
    ]
    monkeypatch.setattr(hands_on.queue, "Queue", Mock(return_value=messages))
    monkeypatch.setattr(hands_on.threading, "Thread", Mock())
    send = Mock()
    assert list(hands_on.interruptible_messages(Mock(), send)) == [
        '{"state":"disposed"}\n'
    ]
    send.assert_called_once_with("stop")


def _public_handoff():
    organization = "10000000-0000-4000-8000-000000000001"
    edition = "20000000-0000-4000-8000-000000000002"
    policy = {
        "contract": "scheduling.programme-continuity-trust@1",
        "keys": [
            {
                "organization_id": organization,
                "edition_id": edition,
                "key_id": "fixture-" + "a" * 32,
                "public_key_b64": base64.b64encode(b"p" * 32).decode(),
                "not_before": "2026-10-03T08:00:00+00:00",
                "not_after": "2026-10-03T09:00:00+00:00",
            }
        ],
    }
    return {
        "stage": "published",
        "run_id": "a" * 32,
        "organization_id": organization,
        "edition_id": edition,
        "continuity_trust_policy": json.dumps(
            policy, sort_keys=True, separators=(",", ":")
        ),
    }


def test_public_trust_is_separate_and_never_overwrites_history(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    document = _public_handoff()
    instructions = hands_on.provision_public_trust(document)
    directory = tmp_path / ".tools/programme-hands-on" / document["run_id"]
    assert (directory / "trust.json").read_text() == document["continuity_trust_policy"]
    (directory / "known.json").write_text("retained high-water evidence")
    assert "--initialize" in instructions
    assert "--audience public --kind public" in instructions
    with pytest.raises(FileExistsError):
        hands_on.provision_public_trust(document)
    assert (directory / "known.json").read_text() == "retained high-water evidence"


def test_foreign_trust_fails_before_writing_any_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    document = _public_handoff()
    document["edition_id"] = "30000000-0000-4000-8000-000000000003"
    with pytest.raises(ValueError, match="invalid_handoff_scope"):
        hands_on.provision_public_trust(document)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("stage", ["team", "items"])
def test_unpublished_session_does_not_create_trust_files(tmp_path, monkeypatch, stage):
    monkeypatch.chdir(tmp_path)
    assert hands_on.provision_public_trust({"stage": stage}) == ""
    assert list(tmp_path.iterdir()) == []


def test_encrypted_handoff_authenticates_before_disclosing_accounts():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    document = {"people": [{"password": "fictional-private-value"}]}
    envelope = seal_handoff(document, key.public_key())
    assert hands_on.open_handoff(envelope, key) == document
    payload = bytearray(base64.b64decode(envelope["ciphertext"]))
    payload[0] ^= 1
    envelope["ciphertext"] = base64.b64encode(payload).decode("ascii")
    with pytest.raises(InvalidTag):
        hands_on.open_handoff(envelope, key)


@pytest.mark.parametrize(("input_tty", "output_tty"), [(False, True), (True, False)])
def test_redirected_terminal_never_launches_or_discloses(
    monkeypatch, input_tty, output_tty
):
    monkeypatch.setattr(hands_on.sys, "argv", ["programme_hands_on"])
    monkeypatch.setattr(hands_on.sys.stdin, "isatty", lambda: input_tty)
    monkeypatch.setattr(hands_on.sys.stdout, "isatty", lambda: output_tty)
    launch = Mock()
    monkeypatch.setattr(hands_on, "supervise", launch)
    with pytest.raises(SystemExit) as failure:
        hands_on.main()
    assert failure.value.code == 2
    launch.assert_not_called()


def test_card_never_exposes_issuer_or_private_handoff_keys():
    card = hands_on.session_card(
        {
            "url": "http://127.0.0.1:54321",
            "organization_id": "organization",
            "edition_id": "edition",
            "stage": "team",
            "remaining_seconds": 2400,
            "people": [
                {
                    "role": "organizer",
                    "email": "test@example.invalid",
                    "password": "synthetic",
                }
            ],
            "private_key": "must-not-render",
            "continuity_trust_policy": "not-account-material",
        }
    )
    assert "test@example.invalid" in card
    assert "Password: synthetic" in card
    assert "must-not-render" not in card
    assert "not-account-material" not in card
    assert "40 minutes" in card
    assert "deletes this disposable session's progress" in card


@pytest.mark.parametrize(
    ("disposed", "exit_code", "expected"), [(True, 0, 0), (False, 0, 1), (True, 1, 1)]
)
def test_exit_requires_normal_child_completion_and_disposal(
    monkeypatch, synchronous_child, disposed, exit_code, expected
):
    child = Mock()
    child.__enter__ = Mock(return_value=child)
    child.__exit__ = Mock(return_value=False)
    child.stdout = io.StringIO(
        json.dumps({"state": "disposed" if disposed else "failed"}) + "\n"
    )
    child.poll.return_value = None
    child.wait.return_value = exit_code
    monkeypatch.setattr(hands_on.subprocess, "Popen", Mock(return_value=child))
    monkeypatch.setattr(hands_on.threading, "Thread", Mock())
    assert hands_on.supervise("team") == expected
    if disposed:
        child.stdin.write.assert_not_called()
    else:
        child.stdin.write.assert_called_with("stop\n")
    assert child.stdin.close.called


def test_already_disposed_child_broken_input_pipe_is_not_failed_cleanup(
    monkeypatch, synchronous_child
):
    child = Mock()
    child.__enter__ = Mock(return_value=child)
    child.__exit__ = Mock(return_value=False)
    child.stdout = io.StringIO('{"state":"disposed"}\n')
    child.stdin.close.side_effect = BrokenPipeError
    child.wait.return_value = 0
    monkeypatch.setattr(hands_on.subprocess, "Popen", Mock(return_value=child))
    monkeypatch.setattr(hands_on.threading, "Thread", Mock())
    assert hands_on.supervise("team") == 0


def test_malformed_child_output_still_requests_owned_cleanup(
    monkeypatch, synchronous_child
):
    child = Mock()
    child.__enter__ = Mock(return_value=child)
    child.__exit__ = Mock(return_value=False)
    child.stdout = io.StringIO("not a handoff\n")
    child.poll.return_value = None
    monkeypatch.setattr(hands_on.subprocess, "Popen", Mock(return_value=child))
    monkeypatch.setattr(hands_on.threading, "Thread", Mock())
    with pytest.raises(json.JSONDecodeError):
        hands_on.supervise("team")
    child.stdin.write.assert_called_with("stop\n")
    assert child.stdin.close.called
