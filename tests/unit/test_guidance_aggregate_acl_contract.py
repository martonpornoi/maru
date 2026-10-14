"""Guides must harden the inherited trigger without reopening it on reversal."""

import hashlib
import inspect
from importlib import import_module

from maru.authorization.database_role_safety import (
    RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V6,
)
from maru.events import guidance_setup_readiness


def test_inherited_trigger_revoke_is_not_a_reverse_drop_or_public_regrant():
    migration = import_module("maru.events.migrations.0023_guidance_adoption_integrity")
    forward = [" ".join(sql.split()) for sql in migration.FORWARD_SQL.split(";")]
    assert (
        forward.count(
            "REVOKE ALL ON FUNCTION "
            "public.maru_validate_edition_aggregate_version() FROM PUBLIC"
        )
        == 1
    )
    # The reverse SQL removes only newly introduced functions. The inherited
    # aggregate remains installed with its safe ACL, even after Guides is unused.
    assert "maru_validate_edition_aggregate_version" not in migration.REVERSE_SQL
    assert (
        "public.maru_validate_edition_aggregate_version()"
        not in RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V6
    )


def test_hardened_migration_pin_and_owner_only_composed_contract_remain_exact(
    monkeypatch,
):
    observed = []

    def capture(contract):
        observed.append(contract)
        return True

    monkeypatch.setattr(
        guidance_setup_readiness, "database_integrity_contract_is_ready", capture
    )
    monkeypatch.setattr(
        guidance_setup_readiness, "relation_schema_is_current", lambda _expected: True
    )
    assert guidance_setup_readiness.guidance_setup_database_integrity_is_ready()
    (contract,) = observed
    assert contract.source_contract_current
    assert "maru_validate_edition_aggregate_version()" in contract.functions
    assert contract.runtime_executable_functions == frozenset()
    assert contract.supporting_triggers[
        "events_aggregate_version_guard"
    ].function_identity == ("public.maru_validate_edition_aggregate_version()")
    migration = import_module("maru.events.migrations.0023_guidance_adoption_integrity")
    assert (
        hashlib.sha256(
            inspect.getsource(migration).replace("\r\n", "\n").encode()
        ).hexdigest()
        == guidance_setup_readiness._GUIDANCE_SOURCE_SHA256[migration.__name__]
    )
