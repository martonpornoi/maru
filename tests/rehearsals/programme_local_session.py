"""Interactive owned rehearsal with encrypted account handoff, never a demo login."""

from __future__ import annotations

import argparse
import base64
import json
import os
import queue
import sys
import threading
import time
from uuid import uuid4

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from tests.rehearsals.programme_browser_gateway import (
    OPT_IN,
    local_programme_browser,
)
from tests.rehearsals.programme_runtime_environment import (
    require_programme_rehearsal_request,
)

_AAD = b"maru-local-programme-session-v1"


def _emit(document):
    sys.stdout.write(json.dumps(document) + "\n")
    sys.stdout.flush()


def load_recipient(value):
    """Accept only a bounded public RSA handoff key, never a path or private key."""
    if not isinstance(value, str) or len(value) > 1024:
        raise ValueError("invalid_handoff_key")
    key = serialization.load_der_public_key(base64.b64decode(value, validate=True))
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size != 2048:
        raise ValueError("invalid_handoff_key")
    return key


def seal_handoff(document, recipient):
    """Encrypt private account material for the supervising facilitator only."""
    key = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, json.dumps(document).encode("utf-8"), _AAD)
    sealed = recipient.encrypt(
        key,
        padding.OAEP(
            mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None
        ),
    )
    return {
        "state": "ready",
        "sealed_key": base64.b64encode(sealed).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
    }


def _person(role, person):
    return {
        "role": role,
        "account_id": str(person.account_id),
        "email": person.email,
        "password": person.password,
    }


def continuity_handoff(fixture, stage):
    """Hand off only this fixture's independent public policy, never issuer secrets."""
    if stage != "published":
        return {}
    from maru.scheduling.continuity_offline import (  # noqa: PLC0415
        decode_continuity_trust_policy,
    )
    from maru.scheduling.continuity_protocol import (  # noqa: PLC0415
        ContinuityInvalidError,
    )

    policy = fixture.continuity_trust_policy
    if type(policy) is not bytes:
        raise ValueError("invalid_continuity_handoff")
    try:
        keys = decode_continuity_trust_policy(policy)
        if len(keys) != 1 or (
            keys[0].organization_id != fixture.scenario.organization_id
            or keys[0].edition_id != fixture.scenario.edition_id
            or keys[0].key_id != "fixture-" + fixture.run_id
        ):
            raise ValueError("invalid_continuity_handoff")
        return {"continuity_trust_policy": policy.decode("utf-8")}
    except (ContinuityInvalidError, UnicodeError):
        raise ValueError("invalid_continuity_handoff") from None


def prepare_stage(fixture, stage):
    """Prepare explicitly labelled synthetic prerequisites, never human results."""
    setup = fixture.scenario
    people = [
        _person("organizer", setup.controllers[0]),
        _person("independent-approver", setup.controllers[1]),
        _person("intake-organizer", setup.intake_person),
    ]
    if stage == "team":
        return people
    if stage not in {"items", "published"}:
        raise ValueError("invalid_session_stage")
    proposal = fixture.prepare_proposal()
    reviewed = fixture.prepare_review(proposal)
    items = fixture.prepare_items(proposal, reviewed)
    from tests.rehearsals.programme_review_scenario import (  # noqa: PLC0415
        PERSON_ROLES,
    )

    # Hand off existing independently provisioned personas, not new authority.
    people.extend(
        _person(label, person)
        for (label, _code), person in zip(PERSON_ROLES, reviewed.people, strict=True)
    )
    people.extend(
        [
            _person("proposal-lead", proposal.lead),
            _person("collaborator", proposal.collaborator),
            _person("public-copy-reviewer", items.public_reviewer),
            _person("ceremony-host", items.ceremony_host),
        ]
    )
    if stage == "published":
        planning = fixture.prepare_planning(proposal, reviewed, items)
        physical = fixture.prepare_physical(proposal, reviewed, items, planning)
        staffing = fixture.prepare_staffing(
            proposal, reviewed, items, planning, physical
        )
        release = fixture.prepare_release(
            proposal, reviewed, items, planning, physical, staffing
        )
        people.extend(
            [
                _person("planner", planning.planner),
                _person("catalog-organizer", planning.catalog_person),
                _person("physical-reviewer", physical.reviewer),
                _person("volunteer", staffing.volunteer),
                _person("release-reviewer", release.reviewer),
            ]
        )
    fixture.verify_excluded_state()
    return people


def run_session(*, recipient, stage):
    """Keep one finite interactive fixture alive until stop, EOF or original expiry."""
    require_programme_rehearsal_request()
    if os.environ.get(OPT_IN) != "synthetic-loopback-only":
        raise ValueError("local_http_opt_in_required")
    if stage not in {"team", "items", "published"}:
        raise ValueError("invalid_session_stage")
    from tests.rehearsals.programme_runner import (  # noqa: PLC0415
        isolated_programme_application,
    )

    commands = queue.Queue()

    def receive():
        while True:
            line = sys.stdin.readline(80)
            if not line:
                commands.put("stop")
                return
            command = line.strip()
            if command not in {"stop", "refresh", "diagnostics"}:
                commands.put("stop")
                return
            commands.put(command)

    threading.Thread(target=receive, daemon=True).start()
    _emit({"state": "preparing", "stage": stage})
    with isolated_programme_application(
        setup_mode="new_foundation",
        with_scanner=stage != "team",
        with_continuity=stage == "published",
        with_isolation=True,
    ) as fixture:
        people = prepare_stage(fixture, stage)
        fixture.verify_excluded_state()
        with local_programme_browser(fixture) as browser:
            document = {
                "url": browser.url,
                "run_id": fixture.run_id,
                "stage": stage,
                "remaining_seconds": int(fixture.deadline - time.monotonic()),
                "organization_id": str(fixture.scenario.organization_id),
                "edition_id": str(fixture.scenario.edition_id),
                "entry_path": "/admin/",
                "people": people,
                "preparation": "Automated prerequisites; not human acceptance",
                **continuity_handoff(fixture, stage),
            }
            _emit(seal_handoff(document, recipient))
            next_refresh = time.monotonic() + 120
            while time.monotonic() < fixture.deadline - 20:
                try:
                    command = commands.get(timeout=5)
                except queue.Empty:
                    command = None
                if command == "stop":
                    break
                if command == "diagnostics":
                    _emit({"state": "diagnostics", "counts": browser.diagnostics()})
                if command == "refresh" or time.monotonic() >= next_refresh:
                    fixture.refresh_workers()
                    next_refresh = time.monotonic() + 120
            fixture.verify_excluded_state()
    _emit({"state": "disposed"})


def main():
    """Run the explicit private-pipe entry; report failures without secret details."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipient-public-key", required=True)
    parser.add_argument(
        "--stage", choices=("team", "items", "published"), default="team"
    )
    args = parser.parse_args()
    recipient = load_recipient(args.recipient_public_key)
    # The launcher owns a new run; caller opt-in and original finite lease remain
    # explicit. Never adopt an old database or add an impersonation endpoint.
    os.environ["MARU_PROGRAMME_REHEARSAL_RUN_ID"] = uuid4().hex
    require_programme_rehearsal_request()
    os.environ["DJANGO_SETTINGS_MODULE"] = "maru.settings.test"
    import django  # noqa: PLC0415

    django.setup()
    run_session(recipient=recipient, stage=args.stage)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - private protocol must not expose traceback
        _emit({"state": "failed", "kind": type(error).__name__})
        raise SystemExit(1) from None
