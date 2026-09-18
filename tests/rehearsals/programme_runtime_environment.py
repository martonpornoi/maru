"""Database-free startup fence for the future native Programme fixture.

This validates configuration, not Docker ownership, database privileges or native
readiness. It starts nothing and installs no profile. The eventual launcher must
also prove ownership of its disposable resources and the actual runtime role.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from scripts import ci_development_policy

_RUN_ID = re.compile(r"[0-9a-f]{32}\Z")
_SECONDS = re.compile(r"[1-9][0-9]{1,3}\Z")
_LIBPQ_OVERRIDES = (
    "PGSERVICE",
    "PGSERVICEFILE",
    "PGHOST",
    "PGHOSTADDR",
    "PGPORT",
    "PGDATABASE",
    "PGUSER",
    "PGPASSWORD",
    "PGPASSFILE",
    "PGOPTIONS",
)


class ProgrammeRehearsalEnvironmentError(RuntimeError):
    """Report only a stable code, never a connection string or secret value."""


@dataclass(frozen=True, slots=True)
class ProgrammeRehearsalRequest:
    """Explicit run identity and maximum lease, not permission to use existing data."""

    run_id: str
    lease_seconds: int


@dataclass(frozen=True, slots=True)
class ProgrammeRuntimeEnvironment:
    """Validated startup inputs, not evidence of resource or role ownership."""

    run_id: str
    database_name: str
    port: int
    lease_seconds: int
    database_url: str = field(repr=False)


def require_programme_rehearsal_request() -> ProgrammeRehearsalRequest:
    """Read the tracked execution policy before any resource configuration.

    Returns
    -------
    ProgrammeRehearsalRequest
        Explicit synthetic run identity and bounded lease.

    Raises
    ------
    ProgrammeRehearsalEnvironmentError
        When tracked policy is unavailable/deferred, opt-in or run identity is
        absent, or the requested lease is outside 60-3600 seconds.
    """
    try:
        mode = ci_development_policy.postgresql_policy_mode()
    except (OSError, ValueError, UnicodeError):
        raise ProgrammeRehearsalEnvironmentError("policy_unavailable") from None
    if mode != "required":
        raise ProgrammeRehearsalEnvironmentError("postgresql_deferred")
    if os.environ.get("MARU_PROGRAMME_REHEARSAL") != "isolated":
        raise ProgrammeRehearsalEnvironmentError("explicit_opt_in_required")

    run_id = os.environ.get("MARU_PROGRAMME_REHEARSAL_RUN_ID", "")
    if _RUN_ID.fullmatch(run_id) is None or run_id == "0" * 32:
        raise ProgrammeRehearsalEnvironmentError("invalid_run_identity")
    lease = os.environ.get("MARU_PROGRAMME_REHEARSAL_LEASE_SECONDS", "")
    if _SECONDS.fullmatch(lease) is None or not 60 <= int(lease) <= 3600:
        raise ProgrammeRehearsalEnvironmentError("invalid_lease")
    return ProgrammeRehearsalRequest(run_id, int(lease))


def require_programme_runtime_environment() -> ProgrammeRuntimeEnvironment:
    """Fence application startup before Django, a connection or process is opened.

    Returns
    -------
    ProgrammeRuntimeEnvironment
        Exact run-scoped loopback inputs. The URI contains a credential: pass it
        only to the owned fixture process and never log or serialize it.

    Raises
    ------
    ProgrammeRehearsalEnvironmentError
        For invalid policy, opt-in, run identity, lease, connection scope or
        ambient libpq overrides. No resources are started.
    """
    request = require_programme_rehearsal_request()
    run_id = request.run_id
    if any(os.environ.get(name) for name in _LIBPQ_OVERRIDES):
        raise ProgrammeRehearsalEnvironmentError("ambient_database_override")

    uri = os.environ.get("MARU_DATABASE_URL", "")
    if not uri or any(ord(char) < 33 or ord(char) > 126 for char in uri):
        raise ProgrammeRehearsalEnvironmentError("invalid_database_scope")
    try:
        parsed = urlsplit(uri)
        port = parsed.port
        valid = (
            parsed.scheme == "postgresql"
            and parsed.hostname == "127.0.0.1"
            and port is not None
            and 1024 <= port <= 65535
            and parsed.username == "maru_runtime"
            and bool(parsed.password)
            and parsed.path == f"/maru_programme_{run_id}"
            and not parsed.query
            and not parsed.fragment
            and os.environ.get("MARU_RUNTIME_DATABASE_ROLE") == "maru_runtime"
        )
    except ValueError:
        raise ProgrammeRehearsalEnvironmentError("invalid_database_scope") from None
    if not valid or port is None:
        raise ProgrammeRehearsalEnvironmentError("invalid_database_scope")

    return ProgrammeRuntimeEnvironment(
        run_id=run_id,
        database_name=f"maru_programme_{run_id}",
        port=port,
        lease_seconds=request.lease_seconds,
        database_url=uri,
    )
