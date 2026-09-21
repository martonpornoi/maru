"""Exact native stop receipt and reciprocal terminal-transition readiness."""

from collections import Counter
from dataclasses import replace
from typing import Final

from django.db import DatabaseError, connection

from maru.core.database_integrity_readiness import (
    DatabaseIntegrityContract,
    database_integrity_contract_is_ready,
    extend_database_integrity_contract,
)
from maru.core.relation_schema_readiness import relation_schema_is_current

PROGRAMME_STOP_RELATION: Final = "events_programmestopreceipt"
PROGRAMME_STOP_SCHEMA_SHA256: Final = {
    PROGRAMME_STOP_RELATION: (
        "e1139a40de720f1e8ef27292aac62be3ce41e5a97e00aeb52a489c34a71766c2"
    ),
}
# The first migration combines storage, guards and an unused-only reverse fence.
# Use the full-file-pinned additive parser, not the SQL-only base builder. This
# empty seed is never exported or inspected; every attachment below is mandatory.
_BASE = DatabaseIntegrityContract(
    status_key="programme_stop_preparation_integrity",
    app_label="events",
    source_migration=("events", "0015_programme_stop_receipt"),
    terminal_migration=("events", "0015_programme_stop_receipt"),
    source_migration_module="maru.events.migrations.0015_programme_stop_receipt",
    triggers={},
    functions={},
    source_contract_current=True,
    owned_relations=(PROGRAMME_STOP_RELATION,),
)
_SOURCES = (
    (
        "events.0015_programme_stop_receipt",
        "f7c9264a81dd150c92db6aa6558671feb8921c355096309d82aa33f7ffa6c288",
    ),
    (
        "scheduling.0023_programme_stop_boundary",
        "bd394658be8748c2e973203f0d8ceeb7f3e53a46d86f8f8325272e038c5544a5",
    ),
    (
        "workforce.0030_programme_stop_boundary",
        "941e61a22e56dab7129df2a5ef35445752d93f92e2a5814f73489af778d46eb5",
    ),
    (
        "authorization.0040_programme_stop_boundary",
        "c727e2e7f73bcb45f7e30a82733423f84a24f553549a508cc41053d4934e96bf",
    ),
    (
        "venues.0009_programme_stop_boundary",
        "2c06618a0dc345ea992ef8698bf89b5b5079a69eaa5f61def59d09aa8dc3a083",
    ),
    (
        "programme.0022_programme_stop_boundary",
        "3165ab6aa857a62ae26c388a8bd4988bffecbf4c37d816efc6b3065f8dc95699",
    ),
    (
        "applications.0023_programme_stop_boundary",
        "75a144aa28cde54510e643f825ca52680841883b25ce631c6922f1fa746e54f8",
    ),
    (
        "events.0016_programme_stop_integrity",
        "54a4c23cf03a920b685681e841493ada2119046032165cccb73af167cad71068",
    ),
    (
        "events.0017_programme_exit_recovery_fence",
        "13233baff44ad2855d4163771162619c90fb47bd5bf178810fc26cdc7e86eaf4",
    ),
)
for _source, _digest in _SOURCES:
    _owner, _migration = _source.split(".", 1)
    _BASE = extend_database_integrity_contract(
        _BASE,
        migration_module=f"maru.{_owner}.migrations.{_migration}",
        source_sha256=_digest,
    )
PROGRAMME_STOP_TRANSITION_TRIGGERS = {
    name: trigger
    for name, trigger in _BASE.triggers.items()
    if trigger.table == "events_eventedition"
}
# Receipt integrity remains a complete relation contract. The two new edition
# attachments are checked separately: this purpose does not pretend to describe
# every unrelated legacy Events trigger with the generic whole-relation checker.
PROGRAMME_STOP_PREPARATION_CONTRACT = replace(
    _BASE,
    triggers={
        name: trigger
        for name, trigger in _BASE.triggers.items()
        if trigger.table == PROGRAMME_STOP_RELATION
    },
)


def _transition_attachments_are_current() -> bool:
    expected = PROGRAMME_STOP_TRANSITION_TRIGGERS
    if set(expected) != {
        "events_lifecycle_version_guard",
        "events_programme_stop_transition",
    }:
        return False
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT t.tgname::text, r.relname::text,
                   pn.nspname || '.' || p.proname || '(' ||
                       pg_catalog.oidvectortypes(p.proargtypes) || ')',
                   t.tgtype, t.tgenabled, t.tgconstraint <> 0,
                   t.tgdeferrable, t.tginitdeferred, t.tgqual IS NULL,
                   t.tgnargs, cardinality(t.tgattr::smallint[]) = 0, t.tgargs,
                   p.proowner = r.relowner AND rn.nspname = 'public'
                       AND r.relkind IN ('r', 'p')
              FROM pg_catalog.pg_trigger t
              JOIN pg_catalog.pg_class r ON r.oid = t.tgrelid
              JOIN pg_catalog.pg_namespace rn ON rn.oid = r.relnamespace
              JOIN pg_catalog.pg_proc p ON p.oid = t.tgfoid
              JOIN pg_catalog.pg_namespace pn ON pn.oid = p.pronamespace
             WHERE NOT t.tgisinternal AND (
                 t.tgname = ANY(%s::text[]) OR t.tgfoid IN (
                     pg_catalog.to_regprocedure('public.maru_validate_edition_lifecycle_version()'),
                     pg_catalog.to_regprocedure('public.maru_programme_stop_transition_guard()')
                 ))
        """,
            [sorted(expected)],
        )
        rows = cursor.fetchall()
    return Counter(tuple(row) for row in rows) == Counter(
        trigger.catalog_row for trigger in expected.values()
    )


def programme_stop_preparation_is_ready() -> bool:
    """Check installed receipt and prepared owner fences without enabling stop.

    Returns
    -------
    bool
        Whether the exact preparation catalog is installed. Other owner guards,
        complete preview, authorization, terminal evidence and acceptance remain
        separate prerequisites; this result must never authorize stopping alone.
    """
    try:
        return (
            set(PROGRAMME_STOP_SCHEMA_SHA256) == {PROGRAMME_STOP_RELATION}
            and database_integrity_contract_is_ready(
                PROGRAMME_STOP_PREPARATION_CONTRACT
            )
            and relation_schema_is_current(PROGRAMME_STOP_SCHEMA_SHA256)
            and _transition_attachments_are_current()
        )
    except (DatabaseError, LookupError, RuntimeError, TypeError, ValueError):
        return False


def programme_stop_command_is_ready() -> bool:
    """Require the exact terminal receipt closure as well as every owner fence.

    Returns
    -------
    bool
        Complete native closure, never controller authority or preview acceptance.
    """
    return (
        ("events", "0017_programme_exit_recovery_fence")
        in PROGRAMME_STOP_PREPARATION_CONTRACT.required_migrations
        and programme_stop_preparation_is_ready()
    )
