"""Explicit public-signature refresh, separate from the offline scanning daemon."""

import json
import os
import re
from contextlib import contextmanager

from tests.rehearsals.programme_https import remaining_lease

_RUN = "io.maru.programme-signature-run"
_OWNER = "io.maru.programme-signature-owner"


class ScannerSignatureError(RuntimeError):
    """Report closed refresh/ownership failures without raw daemon output."""


def _volume(docker, name):
    result = docker.call("volume", "inspect", name, allow_failure=True)
    if result.returncode:
        if "no such volume" in result.stderr.lower():
            return None
        raise ScannerSignatureError("signature_volume_inspection_unavailable")
    try:
        values = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise ScannerSignatureError("signature_volume_inspection_invalid") from None
    if (
        not isinstance(values, list)
        or len(values) != 1
        or not isinstance(values[0], dict)
    ):
        raise ScannerSignatureError("signature_volume_inspection_invalid")
    return values[0]


def _owned_volume(value, *, name, run_id, owner):
    if (
        not isinstance(value, dict)
        or value.get("Name") != name
        or value.get("Driver") != "local"
        or value.get("Scope") != "local"
        or value.get("Options") not in (None, {})
        or not isinstance(value.get("Labels"), dict)
        or value["Labels"].get(_RUN) != run_id
        or value["Labels"].get(_OWNER) != owner
    ):
        raise ScannerSignatureError("signature_volume_ownership_changed")


def _remove_updater(docker, *, name, run_id, owner, image):
    value = docker.inspect(name)
    if value is None:
        return
    if (
        not isinstance(value.get("id"), str)
        or re.fullmatch(r"[0-9a-f]{64}", value["id"]) is None
        or value.get("name") != "/" + name
        or value.get("image") != image
        or not isinstance(value.get("labels"), dict)
        or value["labels"].get(_RUN) != run_id
        or value["labels"].get(_OWNER) != owner
    ):
        raise ScannerSignatureError("signature_updater_ownership_changed")
    docker.call("container", "rm", "--force", value["id"])
    if docker.inspect(name) is not None:
        raise ScannerSignatureError("signature_updater_cleanup_incomplete")


@contextmanager
def refreshed_signatures(docker, *, image, run_id, owner, deadline):
    """Opt in to one bounded FreshClam update in an owned public-only volume.

    The updater has networking but no application data, credential or host mount.
    It finishes before scanning. The scanner receives only a read-only mount;
    its original image, internal-only network and freshness gate stay unchanged.
    """
    choice = os.environ.get("MARU_PROGRAMME_SCANNER_REFRESH", "")
    if not choice:
        yield None
        return
    if choice != "isolated":
        raise ScannerSignatureError("signature_refresh_opt_in_invalid")
    name = f"maru-programme-signatures-{run_id}"
    updater = name + "-updater"
    if _volume(docker, name) is not None or docker.inspect(updater) is not None:
        raise ScannerSignatureError("signature_resources_already_exist")
    try:
        docker.call(
            "volume",
            "create",
            "--driver",
            "local",
            "--label",
            f"{_RUN}={run_id}",
            "--label",
            f"{_OWNER}={owner}",
            name,
        )
        _owned_volume(_volume(docker, name), name=name, run_id=run_id, owner=owner)
        seconds = min(180, int(remaining_lease(deadline)) - 10)
        if seconds < 1:
            raise ScannerSignatureError("signature_refresh_lease_expired")
        # Docker copies only the pinned image's existing public signatures into
        # this new volume. FreshClam verifies signed updates; no file is scanned.
        docker.call(
            "run",
            "--pull",
            "never",
            "--rm",
            "--name",
            updater,
            "--label",
            f"{_RUN}={run_id}",
            "--label",
            f"{_OWNER}={owner}",
            "--network",
            "bridge",
            "--read-only",
            "--user",
            "clamav",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--memory",
            "2g",
            "--cpus",
            "2",
            "--pids-limit",
            "64",
            "--log-driver",
            "none",
            "--no-healthcheck",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m,mode=1777",  # noqa: S108 - owned tmpfs
            "--tmpfs",
            "/var/log/clamav:rw,noexec,nosuid,size=1m,uid=100,mode=0700",
            "--mount",
            f"type=volume,source={name},target=/var/lib/clamav",
            "--entrypoint",
            "sh",
            image,
            "-c",
            f"timeout {seconds} freshclam --stdout >/dev/null 2>&1",
            timeout=min(seconds + 10, remaining_lease(deadline)),
        )
        if docker.inspect(updater) is not None:
            raise ScannerSignatureError("signature_updater_still_running")
        _owned_volume(_volume(docker, name), name=name, run_id=run_id, owner=owner)
        yield name
    finally:
        _remove_updater(docker, name=updater, run_id=run_id, owner=owner, image=image)
        value = _volume(docker, name)
        if value is not None:
            _owned_volume(value, name=name, run_id=run_id, owner=owner)
            docker.call("volume", "rm", name)
            if _volume(docker, name) is not None:
                raise ScannerSignatureError("signature_volume_cleanup_incomplete")
