"""Read-only excluded-owner checkpoint inventory, not complete P12 acceptance."""

from dataclasses import dataclass, field

import psycopg
from django.apps import apps
from psycopg import sql

from tests.rehearsals.programme_candidate import INTERNAL_EVENTS, MODULES
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRuntimeEnvironment,
    require_programme_rehearsal_request,
)

EXCLUDED_OWNERS = (
    "participation",
    "registration",
    "accreditation",
    "catalog",
    "charities",
    "communications",
    "logistics",
)
MAX_ROWS = 10_000


class ProgrammeExcludedStateError(RuntimeError):
    """Report only a stable code, never row contents, credentials or private IDs."""


@dataclass(frozen=True, slots=True)
class ExcludedStateSnapshot:
    """Bind bounded native row fingerprints to this one synthetic database."""

    run_id: str
    tables: tuple[tuple[str, int, str], ...] = field(repr=False)


def excluded_tables():
    """Cover each excluded owner's managed and automatic join tables."""
    if set(EXCLUDED_OWNERS) & set(MODULES):
        raise ProgrammeExcludedStateError("excluded_owner_was_adopted")
    return tuple(
        sorted(
            {
                model._meta.db_table
                for owner in EXCLUDED_OWNERS
                for model in apps.get_app_config(owner).get_models(
                    include_auto_created=True
                )
                if model._meta.managed and not model._meta.proxy
            }
        )
    )


def _fingerprint(connection, table):
    # Individual rows are hashed inside PostgreSQL. At most 10,001 fixed-length
    # hashes enter the aggregate; no private row or payload leaves the database.
    row = connection.execute(
        sql.SQL(
            "SELECT count(*), encode(sha256(convert_to(COALESCE("
            "string_agg(fingerprint, '' ORDER BY fingerprint), ''), 'UTF8')), 'hex') "
            "FROM (SELECT encode(sha256(convert_to(to_jsonb(source)::text, 'UTF8')), "
            "'hex') AS fingerprint FROM (SELECT * FROM public.{} LIMIT %s) "
            "AS source) AS fingerprints"
        ).format(sql.Identifier(table)),
        [MAX_ROWS + 1],
    ).fetchone()
    if row is None or row[0] > MAX_ROWS:
        raise ProgrammeExcludedStateError("excluded_inventory_overflow")
    return table, row[0], row[1]


def _require_closed_effects(connection):
    if connection.execute(
        "SELECT EXISTS(SELECT 1 FROM public.effects_domainevent "
        "WHERE event_name <> ALL(%s) OR schema_version <> 1), "
        "EXISTS(SELECT 1 FROM public.effects_outboxmessage "
        "WHERE destination <> 'internal')",
        [list(INTERNAL_EVENTS)],
    ).fetchone() != (False, False):
        raise ProgrammeExcludedStateError("excluded_effect_or_delivery")
    # No excluded-module authority may be created as a hidden setup side effect.
    pattern = "^(" + "|".join(EXCLUDED_OWNERS) + r")\."
    if connection.execute(
        "SELECT EXISTS(SELECT 1 FROM public.authorization_capabilitygrant "
        "WHERE capability_code ~ %s), EXISTS(SELECT 1 "
        "FROM public.authorization_rolebundle AS bundle, "
        "unnest(bundle.capability_codes) AS capability(code) "
        "WHERE capability.code ~ %s)",
        [pattern, pattern],
    ).fetchone() != (False, False):
        raise ProgrammeExcludedStateError("excluded_authority_created")


def capture_excluded_state(runtime):
    """Observe one coherent, read-only snapshot under the genuine runtime login."""
    request = require_programme_rehearsal_request()
    if (
        type(runtime) is not ProgrammeRuntimeEnvironment
        or runtime.run_id != request.run_id
        or runtime.database_name != "maru_programme_" + request.run_id
    ):
        raise ProgrammeExcludedStateError("excluded_inventory_wrong_fixture")
    tables = excluded_tables()
    try:
        with psycopg.connect(
            runtime.database_url,
            connect_timeout=5,
            options="-c statement_timeout=5000 -c lock_timeout=1000",
        ) as connection:
            connection.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
            )
            if connection.execute(
                "SELECT current_database(), session_user, current_user"
            ).fetchone() != (runtime.database_name, "maru_runtime", "maru_runtime"):
                raise ProgrammeExcludedStateError("excluded_inventory_wrong_session")
            observed = connection.execute(
                "SELECT c.relname FROM pg_catalog.pg_class c "
                "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='public' AND c.relkind IN ('r','p') "
                "AND split_part(c.relname, '_', 1) = ANY(%s) ORDER BY c.relname",
                [list(EXCLUDED_OWNERS)],
            ).fetchall()
            if tuple(row[0] for row in observed) != tables:
                raise ProgrammeExcludedStateError("excluded_table_inventory_changed")
            _require_closed_effects(connection)
            return ExcludedStateSnapshot(
                runtime.run_id,
                tuple(_fingerprint(connection, table) for table in tables),
            )
    except psycopg.Error:
        raise ProgrammeExcludedStateError("excluded_inventory_unavailable") from None


def verify_excluded_state(runtime, baseline):
    """Reject additions, removals or edits; never update the original baseline."""
    if type(baseline) is not ExcludedStateSnapshot or baseline.run_id != runtime.run_id:
        raise ProgrammeExcludedStateError("excluded_inventory_missing_baseline")
    if capture_excluded_state(runtime) != baseline:
        raise ProgrammeExcludedStateError("excluded_owner_state_changed")
