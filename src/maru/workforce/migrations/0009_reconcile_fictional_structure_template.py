"""Reconcile the receipt guard with the fictional MaruCon starter."""

from __future__ import annotations

from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations

_structure_integrity = import_module(
    "maru.workforce.migrations.0007_structure_write_integrity"
)

INSTALL_FICTIONAL_TEMPLATE_RECEIPT_GUARDS_SQL = (
    _structure_integrity.INSTALL_RECEIPT_FUNCTIONS_SQL.replace(
        "CREATE FUNCTION",
        "CREATE OR REPLACE FUNCTION",
    )
)
MARUCON_TEMPLATE_CODE = "marucon-reference"
MARUCON_TEMPLATE_VERSION = 1
MARUCON_TEMPLATE_DIGEST = (
    "55f4091787215fd9eef5cc1266806a1450dd6e5449d50864340601f5ec2398ee"
)


def refuse_incompatible_template_evidence(apps: Any, schema_editor: Any) -> None:
    """Refuse to relabel receipts outside the exact fictional contract."""
    schema_editor.execute(
        "LOCK TABLE public.workforce_editionstructurecommandreceipt "
        "IN SHARE ROW EXCLUSIVE MODE"
    )
    receipt_model = apps.get_model(
        "workforce",
        "EditionStructureCommandReceipt",
    )
    incompatible_count = (
        receipt_model.objects.using(schema_editor.connection.alias)
        .filter(action="template_applied")
        .exclude(
            template_code=MARUCON_TEMPLATE_CODE,
            template_version=MARUCON_TEMPLATE_VERSION,
            template_digest=MARUCON_TEMPLATE_DIGEST,
        )
        .count()
    )
    if incompatible_count:
        raise RuntimeError(
            "Cannot install the fictional MaruCon starter while immutable "
            "receipts from a retired external starter remain. Rebuild this "
            "non-production workspace from synthetic data; do not relabel "
            f"the {incompatible_count} existing receipt(s)."
        )


class Migration(migrations.Migration):
    """Install the repository-owned starter contract on upgraded databases."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("workforce", "0008_department_fk_contract_successor"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunPython(
            refuse_incompatible_template_evidence,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.RunSQL(
            INSTALL_FICTIONAL_TEMPLATE_RECEIPT_GUARDS_SQL,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
