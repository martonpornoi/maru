"""Prepare fictional existing sign-ins for the optional short software rehearsal.

Real invitation commands and local delivery are used. This is facilitator setup,
not browser credential-creation evidence. No convention authority is prepared.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sys
from email import policy
from email.parser import BytesParser
from pathlib import Path
from uuid import uuid4

import django
from django.conf import settings
from django.db import connection

NAMES = ("alex", "blake", "casey")


def _rehearsal_directory() -> Path:
    directory = Path(os.environ["MARU_WORKFORCE_REHEARSAL_DIRECTORY"]).resolve()
    if not (
        settings.SETTINGS_MODULE == "scripts.workforce_rehearsal_settings"
        and os.environ.get("MARU_WORKFORCE_REHEARSAL") == "owned-loopback"
        and (directory / "resource.json").is_file()
        and not (directory / "identities.private.json").exists()
        and not settings.DEBUG
        and settings.REQUIRE_EXACT_AUTHORITY_PROVENANCE
        and settings.REQUIRE_PRIVILEGED_STEP_UP
        and settings.ENFORCE_EDITION_CLOSURE_GATES
        and not settings.IDENTITY_EXPOSE_TEST_TOKENS
        and not settings.MARU_EXPOSE_TEST_CREDENTIAL_TOKENS
        and not settings.SILENCED_SYSTEM_CHECKS
    ):
        raise RuntimeError("Prepared sign-ins require the new owned strict rehearsal.")
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), session_user, current_user")
        identity = cursor.fetchone()
    if identity != ("maru", "maru_runtime", "maru_runtime"):
        raise RuntimeError("Prepared sign-ins require the restricted rehearsal role.")
    return directory


def main() -> int:
    """Prepare only the exact dedicated rehearsal's three fictional accounts.

    Returns
    -------
    int
        Zero after the requested preparation phase completes.

    Raises
    ------
    RuntimeError
        If ownership, runtime identity, delivery or account state is unexpected.
    """
    django.setup()
    from maru.identity.invitation_commands import (  # noqa: PLC0415
        accept_platform_account_invitation,
        create_platform_account_invitation,
    )
    from maru.identity.models import Account  # noqa: PLC0415

    directory = _rehearsal_directory()
    phase = sys.argv[1]
    actor = Account.objects.get(email="workforce-platform@example.invalid")
    if phase == "queue":
        if Account.objects.count() != 1:
            raise RuntimeError(
                "Identity preparation requires only the bootstrap account."
            )
        for name in NAMES:
            create_platform_account_invitation(
                actor=actor,
                email=f"workforce-{name}@example.invalid",
                login_handle="",
                display_name=name.title(),
                preferred_language="en",
                reason="Prepare a fictional sign-in for the short software rehearsal.",
                expected_version=0,
                retry_key=uuid4(),
                correlation_id=uuid4(),
                source_channel="operator",
            )
    elif phase == "accept":
        credentials = {
            "platform": json.loads(
                (directory / "bootstrap.private.json").read_text(encoding="utf-8")
            )
        }
        for name in NAMES:
            address = f"workforce-{name}@example.invalid"
            tokens = set()
            for path in (directory / "mail.private").iterdir():
                letter = BytesParser(policy=policy.default).parsebytes(
                    path.read_bytes()
                )
                if address not in str(letter.get("To", "")):
                    continue
                body = (
                    letter.get_body(preferencelist=("plain",))
                    if letter.is_multipart()
                    else letter
                )
                if body is not None:
                    tokens.update(
                        re.findall(r"#code=([A-Za-z0-9_-]{43})", body.get_content())
                    )
            if len(tokens) != 1:
                raise RuntimeError(
                    "Exactly one delivered fictional invitation is required."
                )
            password = secrets.token_urlsafe(32)
            accept_platform_account_invitation(
                raw_token=tokens.pop(),
                new_password=password,
                retry_key=uuid4(),
                correlation_id=uuid4(),
                request_fingerprint=hashlib.sha256(
                    ("short-workforce-guide-" + name).encode()
                ).hexdigest(),
                source_channel="operator",
            )
            account = Account.objects.get(email=address)
            if not (
                account.is_active
                and account.has_verified_email
                and not account.is_staff
            ):
                raise RuntimeError(
                    "A prepared fictional account has unexpected access."
                )
            credentials[name] = {"email": address, "password": password}
        with (directory / "identities.private.json").open(
            "x", encoding="utf-8"
        ) as stream:
            json.dump(credentials, stream, indent=2)
        (directory / "identities.private.json").chmod(0o600)
        print(
            "Three fictional sign-ins prepared; browser account creation is untested."
        )
    else:
        raise RuntimeError("Unknown identity preparation phase.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
