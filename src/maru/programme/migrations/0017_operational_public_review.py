"""Allow independent Ready/Live public review without reopening private editing."""

import re
from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations

_base = import_module("maru.programme.migrations.0002_integrity_guards")
_decisions = import_module(
    "maru.programme.migrations.0014_placement_decision_integrity"
)
_match = re.search(
    r"CREATE FUNCTION public\.maru_guard_programme_public_rendition\(\).*?"
    r"SET search_path = pg_catalog, public, pg_temp;",
    _base.FORWARD_SQL,
    re.DOTALL,
)
if _match is None:
    raise RuntimeError("The frozen Programme public review guard was not found.")
_old_public = _match.group().replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
_lifecycle = "OR edition_lifecycle NOT IN ('draft', 'preparing')"
if _old_public.count(_lifecycle) != 1:
    raise RuntimeError("The frozen public-review lifecycle branch changed.")
_public = _old_public.replace(
    _lifecycle,
    """OR edition_lifecycle NOT IN ('draft', 'preparing', 'ready', 'live')
       OR (edition_lifecycle IN ('ready', 'live') AND (
           NOT EXISTS (SELECT 1 FROM public.identity_account
               WHERE id = NEW.reviewed_by_id AND is_active
                 AND email_verified_at IS NOT NULL AND account_kind = 'person')
           OR EXISTS (SELECT 1 FROM public.programme_programmeworkingrevision
               WHERE item_id = NEW.item_id AND actor_id = NEW.reviewed_by_id)
       ))""",
)
_old_receipt = _decisions._receipt  # noqa: SLF001 - exact frozen historical SQL
_operational = (
    "NEW.operation IN ('accessibility_fit_record', 'staffing_absence_record')"
)
# The exact operation list occurs twice: one result branch and one lifecycle
# exception. Extend only the latter; public-copy result proof must stay unchanged.
_lifecycle_marker = "    ) AND NOT (\n        " + _operational
if _old_receipt.count(_lifecycle_marker) != 1:
    raise RuntimeError("The frozen operational receipt lifecycle branch changed.")
_receipt = _old_receipt.replace(
    _lifecycle_marker,
    "    ) AND NOT (\n        NEW.operation IN "
    "('accessibility_fit_record', 'staffing_absence_record', "
    "'public_rendition_record')",
)
FORWARD_SQL = _public + "\n" + _receipt
REVERSE_SQL = _old_receipt + "\n" + _old_public


def refuse_used_public_review_downgrade(apps: Any, schema_editor: Any) -> None:
    """Retain reviewed-copy history after the operational review contract is used."""
    schema_editor.execute(
        "LOCK TABLE public.programme_programmepublicrendition IN ACCESS EXCLUSIVE MODE"
    )
    if apps.get_model("programme", "ProgrammePublicRendition").objects.exists():
        raise RuntimeError("Reviewed Programme public copy exists; fix forward.")


class Migration(migrations.Migration):
    """Keep public review independent from private-planning lifecycle admission."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("programme", "0016_release_dependency_mutations"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_used_public_review_downgrade
        ),
    ]
