"""Private terminal facilitator for a fresh, finite synthetic Programme session.

Run directly in a terminal, never through a transcript or redirected output.
The child retains the existing native setup, encrypted pipe and owned cleanup.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import queue
import re
import subprocess
import sys
import threading
from contextlib import suppress
from pathlib import Path
from uuid import UUID

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from tests.rehearsals.programme_local_session import _AAD


def open_handoff(envelope, private_key):
    """Authenticate the private pipe envelope before displaying any account."""
    key = private_key.decrypt(
        base64.b64decode(envelope["sealed_key"], validate=True),
        padding.OAEP(
            mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None
        ),
    )
    plaintext = AESGCM(key).decrypt(
        base64.b64decode(envelope["nonce"], validate=True),
        base64.b64decode(envelope["ciphertext"], validate=True),
        _AAD,
    )
    return json.loads(plaintext)


def session_card(document):
    """Render only the session's ephemeral browser accounts for its local owner."""
    origin = document["url"]
    organization = document["organization_id"]
    edition = document["edition_id"]
    lines = [
        "READY - fictional local test environment",
        "Automated preparation is not a passed manual test.",
        f"Stage: {document['stage']}",
        f"Time remaining: {document['remaining_seconds'] // 60} minutes",
        f"Administration: {origin}/admin/",
        f"Stop Programme: {origin}/admin/programme/stop/{organization}/{edition}/",
    ]
    if document["stage"] == "published":
        lines.extend(
            (
                f"Public programme: {origin}/programme/{organization}/{edition}/now/",
                f"My programme: {origin}/my/{organization}/{edition}/programme-now/",
            )
        )
    lines.extend(("", "PRIVATE TEST ACCOUNTS - do not copy these into issue reports:"))
    for person in document["people"]:
        lines.extend(
            (
                f"  Role: {person['role']}",
                f"  Email: {person['email']}",
                f"  Password: {person['password']}",
                "",
            )
        )
    lines.extend(
        (
            "Keep this terminal open. Type stop and press Enter to finish.",
            "The original one-hour lease includes preparation; it cannot be renewed.",
            "Stopping or expiry deletes this disposable session's progress.",
            "Restart the same command for a NEW session, URL and passwords.",
        )
    )
    return "\n".join(lines)


def provision_public_trust(document):
    """Preserve independent public trust separately from downloaded bytes."""
    if document["stage"] != "published":
        return ""
    from maru.scheduling.continuity_offline import (  # noqa: PLC0415
        decode_continuity_trust_policy,
    )

    run_id = document["run_id"]
    if re.fullmatch(r"[0-9a-f]{32}", run_id) is None:
        raise ValueError("invalid_handoff_scope")
    policy = document["continuity_trust_policy"].encode("utf-8")
    keys = decode_continuity_trust_policy(policy)
    if len(keys) != 1 or (
        keys[0].organization_id != UUID(document["organization_id"])
        or keys[0].edition_id != UUID(document["edition_id"])
        or keys[0].key_id != "fixture-" + run_id
    ):
        raise ValueError("invalid_handoff_scope")
    directory = Path(".tools/programme-hands-on") / run_id
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "trust.json").write_bytes(policy)
    directory_text = str(directory.resolve()).replace("'", "''")
    return "\n".join(
        (
            "PUBLIC OFFLINE CHECK - this does not download or approve a snapshot:",
            "Copy the new public snapshot to: "
            f"{directory.resolve() / 'incoming.maru.json'}",
            "Then run in a SECOND PowerShell terminal from the Maru folder:",
            f"$programmeFiles = '{directory_text}'",
            ".\\.venv\\Scripts\\python.exe -m maru.scheduling.continuity_offline "
            '--package "$programmeFiles/incoming.maru.json" '
            '--trust "$programmeFiles/trust.json" '
            '--known-state "$programmeFiles/known.json" '
            '--output "$programmeFiles/initial.html" '
            f"--organization {keys[0].organization_id} "
            f"--edition {keys[0].edition_id} "
            "--audience public --kind public --initialize",
            "The synthetic snapshot expires after five minutes; act promptly.",
            "Keep known.json. Later checks omit --initialize; use a NEW output name.",
            "Refusal means stop using the file; do not reset history to bypass it.",
            "This folder retains public verification material after the session ends.",
        )
    )


def ready_card(envelope, private_key):
    """Validate and provision before making any ephemeral account visible."""
    document = open_handoff(envelope, private_key)
    trust_instructions = provision_public_trust(document)
    return session_card(document) + "\n" + trust_instructions + "\n"


def child_environment():
    """Opt in only the owned loopback fixture; retain every native startup fence."""
    return {
        **os.environ,
        "MARU_PROGRAMME_REHEARSAL": "isolated",
        "MARU_PROGRAMME_REHEARSAL_LEASE_SECONDS": "3600",
        "MARU_PROGRAMME_SCANNER_REFRESH": "isolated",
        "MARU_PROGRAMME_LOCAL_HTTP": "synthetic-loopback-only",
    }


def interruptible_messages(stream, send):
    """Request cleanup on Ctrl+C without interrupting a Windows pipe read."""
    messages = queue.Queue()

    def read():
        try:
            for line in stream:
                messages.put(line)
        except OSError as error:
            messages.put(error)
        finally:
            messages.put(None)

    threading.Thread(target=read, daemon=True).start()
    while True:
        try:
            message = messages.get(timeout=0.5)
        except queue.Empty:
            continue
        except KeyboardInterrupt:
            sys.stdout.write("Stopping; wait for owned cleanup to finish.\n")
            sys.stdout.flush()
            send("stop")
            continue
        if message is None:
            return
        if isinstance(message, OSError):
            raise message
        yield message


def recipient_keypair():
    """Create one ephemeral private recipient and its child-safe public encoding."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = base64.b64encode(
        private_key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    ).decode("ascii")
    return private_key, public_key


def supervise(stage):
    """Keep the encrypted child alive until normal stop, EOF or original expiry."""
    private_key, public_key = recipient_keypair()
    command = [
        sys.executable,
        "-m",
        "tests.rehearsals.programme_local_session",
        "--stage",
        stage,
        "--recipient-public-key",
        public_key,
    ]
    # A terminal interrupt must request the child's ordinary owned cleanup,
    # not terminate its database/scanner processes mid-transaction.
    options = (
        {"creationflags": subprocess.CREATE_NO_WINDOW}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    with subprocess.Popen(  # noqa: S603 - fixed module in this interpreter
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        env=child_environment(),
        **options,
    ) as child:
        write_lock = threading.Lock()

        def send(value):
            with write_lock:
                if child.poll() is None:
                    try:
                        child.stdin.write(value + "\n")
                        child.stdin.flush()
                    except (OSError, ValueError):
                        pass
                # EOF lets the child's input reader finish before interpreter
                # shutdown; leaving it blocked can race Python's finalization.
                with suppress(OSError, ValueError):
                    child.stdin.close()

        def receive():
            # A raw terminal reader holds no BufferedReader shutdown lock when
            # the finite child expires or the main thread handles Ctrl+C.
            for line in iter(sys.stdin.buffer.raw.readline, b""):
                value = line.strip()
                if value == b"stop":
                    send("stop")
                    return
                sys.stdout.write("Type stop to finish; other input is ignored.\n")
                sys.stdout.flush()
            send("stop")

        threading.Thread(target=receive, daemon=True).start()
        disposed = False
        try:
            for line in interruptible_messages(child.stdout, send):
                message = json.loads(line)
                state = message.get("state")
                if state == "ready":
                    sys.stdout.write(ready_card(message, private_key))
                elif state == "preparing":
                    sys.stdout.write("Preparing fresh test data; wait for READY.\n")
                elif state == "disposed":
                    disposed = True
                    with write_lock, suppress(BrokenPipeError):
                        child.stdin.close()
                    sys.stdout.write("DISPOSED - the test session has ended.\n")
                elif state == "failed":
                    sys.stdout.write("Session failed; save the stage and report it.\n")
                sys.stdout.flush()
        finally:
            if not disposed:
                send("stop")
            # An exited child no longer consumes the stop request.
            with write_lock, suppress(BrokenPipeError):
                child.stdin.close()
        result = child.wait()
    if result != 0 or not disposed:
        sys.stderr.write("Session did not complete normally; record this message.\n")
        return 1
    sys.stdout.write("COMPLETE - child exited normally and disposal was confirmed.\n")
    return 0


def main():
    """Refuse redirected credentials and launch the selected synthetic stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage", choices=("team", "items", "published"), default="team"
    )
    args = parser.parse_args()
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        parser.error("Use a private interactive terminal without output redirection.")
    return supervise(args.stage)


if __name__ == "__main__":
    try:
        exit_code = main()
    except Exception as error:  # noqa: BLE001 - no account material in a traceback
        sys.stderr.write(
            f"Hands-on session failed ({type(error).__name__}); "
            "no success or cleanup is claimed.\n"
        )
        raise SystemExit(1) from None
    raise SystemExit(exit_code)
