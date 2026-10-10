"""Exact native Announcements schema and evidence-guard readiness."""

import hashlib
import inspect
from importlib import import_module

from django.db import DatabaseError

from maru.core.database_integrity_readiness import (
    build_database_integrity_contract,
    database_integrity_contract_is_ready,
)
from maru.core.relation_schema_readiness import relation_schema_is_current

from .errors import AnnouncementError

ANNOUNCEMENTS_SCHEMA_SHA256 = {
    "announcements_announcement": (
        "31ce6f139925309beb6bbf4beb834159b3e3e004713a87f4e68d2df4683a4eaa"
    ),
    "announcements_announcementcommandreceipt": (
        "25b8f847847e6ac2bfc171f944ab5fa53fe6c60d5a5c0a53dd74e910963b4a86"
    ),
    "announcements_announcementcontrol": (
        "b2c5eb6d003a3f11519621b457b47a57944891b6b398af438d82cda5aae44328"
    ),
    "announcements_announcementpublicationreport": (
        "76ebc63b88773e6ec9a47d7f84034ec28f5b7daf9297139014aefca586bcb37d"
    ),
    "announcements_announcementreview": (
        "5ac5c3c823642731ecd8436e06d948d0bb5550ff7f83ac2fd1c1c10d436b55ec"
    ),
    "announcements_announcementrevision": (
        "5e15d2d5028f27ef24ee64225d6b0a4751cb83ebdf85ef513e89ea2712ba5727"
    ),
    "announcements_announcementsettingsrevision": (
        "0d38080bc2e849ff6278d44623553db03e777757cec225734b94591c730606d6"
    ),
    "announcements_announcementvariant": (
        "35d5ff9e836a2aa4caf4ef52a2f69f634abf1c0171eb5e9e0c3dd5d3d4d40c00"
    ),
}
_FENCE_SHA256 = "28ac8350a5c4e2bc5719c10fef33aafc59b5253b7714345839ed636fb322a0b2"


def announcements_database_integrity_is_ready() -> bool:
    """Fail closed unless the current owning native guard contract is installed.

    Returns
    -------
    bool
        The complete validated result; failures do not return partial evidence.
    """
    try:
        contract = build_database_integrity_contract(
            status_key="announcements_integrity",
            app_label="announcements",
            source_migration=("announcements", "0002_integrity"),
            terminal_migration=("announcements", "0003_downgrade_fence"),
            source_migration_module="maru.announcements.migrations.0002_integrity",
        )
        fence = import_module("maru.announcements.migrations.0003_downgrade_fence")
        return (
            database_integrity_contract_is_ready(contract)
            and relation_schema_is_current(ANNOUNCEMENTS_SCHEMA_SHA256)
            and hashlib.sha256(
                inspect.getsource(fence).replace("\r\n", "\n").encode()
            ).hexdigest()
            == _FENCE_SHA256
        )
    except (DatabaseError, ImportError, LookupError, TypeError, ValueError):
        return False


def require_announcements_integrity() -> None:
    """Refuse access when the current native evidence protection is unavailable.

    Raises
    ------
    AnnouncementError
        If schema, migration, function or trigger evidence differs from the
        owner contract.
    """
    if not announcements_database_integrity_is_ready():
        raise AnnouncementError
