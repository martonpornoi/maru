"""Extend existing item guards only for reciprocal accepted-source creation."""

from __future__ import annotations

import importlib
import re
from typing import ClassVar

from django.db import migrations

_previous = importlib.import_module("maru.programme.migrations.0002_integrity_guards")


def _function(name: str) -> str:
    match = re.search(
        rf"CREATE FUNCTION public\.{re.escape(name)}\(\).*?"
        r"SET search_path = pg_catalog, public, pg_temp;",
        _previous.FORWARD_SQL, re.DOTALL,
    )
    if match is None:
        raise RuntimeError(f"Missing pinned Programme function: {name}")
    return match.group().replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


FUNCTION_NAMES = (
    "maru_guard_programme_item", "maru_guard_programme_source_binding",
    "maru_guard_programme_receipt", "maru_validate_programme_item_evidence",
)
REVERSE_SQL = "\n".join(_function(name) for name in FUNCTION_NAMES)
_item = _function("maru_guard_programme_item").replace(
    "'announcement', 'organizer_core')",
    "'announcement', 'organizer_core', 'accepted_proposal')",
).replace(
    "OR NEW.lifecycle NOT IN ('active', 'retired')",
    "OR (NEW.kind = 'accepted_proposal') IS DISTINCT FROM "
    "(NEW.provenance_kind = 'applications_accepted')\n"
    "       OR NEW.lifecycle NOT IN ('active', 'retired')",
)
_source = _function("maru_guard_programme_source_binding").replace(
    "AND NEW.source_version > 0",
    """AND NEW.source_version = 1
        AND EXISTS (
            SELECT 1 FROM public.applications_programmeacceptedtransition t
            WHERE t.id = NEW.source_object_id AND t.programme_item_id = NEW.item_id
              AND t.organization_id = NEW.organization_id AND t.edition_id = NEW.edition_id
        )""",
)
_receipt = _function("maru_guard_programme_receipt").replace(
    "NEW.operation = 'item_create'", "NEW.operation IN ('item_create', 'item_accept')",
).replace(
    "'item_create', 'working_revise'", "'item_create', 'item_accept', 'working_revise'",
).replace(
    "item_row.provenance_kind <> 'organizer_core'",
    "item_row.provenance_kind IS DISTINCT FROM (CASE WHEN NEW.operation = 'item_accept' "
    "THEN 'applications_accepted' ELSE 'organizer_core' END)",
).replace(
    "    RETURN NEW;",
    """    IF NEW.operation = 'item_accept' AND NOT EXISTS (
        SELECT 1 FROM public.applications_programmeacceptedtransition t
        WHERE t.id = NEW.idempotency_key AND t.programme_item_id = NEW.item_id
          AND t.organization_id = NEW.organization_id AND t.edition_id = NEW.edition_id
          AND t.actor_id = NEW.actor_id AND t.reason = NEW.reason
          AND t.correlation_id = NEW.correlation_id AND t.source_channel = NEW.source_channel
          AND t.expected_programme_version = NEW.expected_version
          AND t.resulting_programme_version = NEW.resulting_control_version
    ) THEN
        RAISE EXCEPTION 'Accepted creation must bind its reciprocal Applications receipt'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;""",
)
_evidence = _function("maru_validate_programme_item_evidence").replace(
    "receipt.operation = 'item_create'", "receipt.operation IN ('item_create', 'item_accept')",
).replace(
    "WHERE receipt.operation = 'readiness_configure'\n           AND receipt.result_object_id = NEW.id",
    """WHERE (
               (receipt.operation = 'readiness_configure' AND receipt.result_object_id = NEW.id)
               OR (receipt.operation = 'item_accept' AND receipt.result_object_id = NEW.item_id
                   AND NEW.sequence = 1 AND NEW.item_version = 1 AND NEW.disposition = 'required')
           )""",
)
FORWARD_SQL = "\n".join((_item, _source, _receipt, _evidence))


class Migration(migrations.Migration):
    """Keep all existing item mutation contracts and add exact accepted creation."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("programme", "0004_accepted_item_source"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
