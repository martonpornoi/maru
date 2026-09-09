"""Explainable, score-free Programme readiness projection."""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass, replace
from importlib import import_module
from typing import TYPE_CHECKING, Final

from django.apps import apps
from django.db import DatabaseError, connection, migrations
from django.db.models.fields import NOT_PROVIDED

from maru.core.database_integrity_readiness import (
    DatabaseIntegrityContract,
    build_database_integrity_contract,
    database_integrity_contract_is_ready,
    parse_database_integrity_sql_contracts,
)

from .catalogs import (
    ProgrammeReadinessDisposition,
    ProgrammeReadinessEvidenceState,
    ProgrammeReadinessProjectionState,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from django.db.backends.utils import CursorWrapper
    from django.db.models import Model

_BASE_INTEGRITY_CONTRACT = build_database_integrity_contract(
    status_key="programme_integrity",
    app_label="programme",
    source_migration=("programme", "0002_integrity_guards"),
    terminal_migration=("programme", "0003_downgrade_fence"),
    source_migration_module="maru.programme.migrations.0002_integrity_guards",
)

_ACCEPTED_MIGRATION = import_module(
    "maru.programme.migrations.0005_accepted_item_integrity"
)
_ACCEPTED_FENCE = import_module(
    "maru.programme.migrations.0006_accepted_item_downgrade_fence"
)
_ACCEPTED_FENCE_SOURCE_SHA256: Final = (
    "980d2951c6a09c7e8ab7a6ebf926701782556eae0f68d874867b2c2022cec299"
)


def _accepted_migration_contract_is_current() -> bool:
    operations = tuple(_ACCEPTED_MIGRATION.Migration.operations)
    fences = tuple(_ACCEPTED_FENCE.Migration.operations)
    reverse = _ACCEPTED_FENCE.refuse_populated_accepted_item_downgrade
    source = inspect.getsource(reverse).replace("\r\n", "\n")
    return (
        len(operations) == len(fences) == 1
        and isinstance(operations[0], migrations.RunSQL)
        and operations[0].sql == _ACCEPTED_MIGRATION.FORWARD_SQL
        and operations[0].reverse_sql == _ACCEPTED_MIGRATION.REVERSE_SQL
        and tuple(_ACCEPTED_MIGRATION.Migration.dependencies)
        == (("programme", "0004_accepted_item_source"),)
        and isinstance(fences[0], migrations.RunPython)
        and fences[0].code is migrations.RunPython.noop
        and fences[0].reverse_code is reverse
        and tuple(_ACCEPTED_FENCE.Migration.dependencies)
        == (
            ("programme", "0005_accepted_item_integrity"),
            ("applications", "0018_programme_conversion_downgrade_fence"),
        )
        and hashlib.sha256(source.encode()).hexdigest() == _ACCEPTED_FENCE_SOURCE_SHA256
    )


_ACCEPTED_TRIGGERS, _ACCEPTED_FUNCTIONS = parse_database_integrity_sql_contracts(
    _ACCEPTED_MIGRATION.FORWARD_SQL
)
_ACCEPTED_INTEGRITY_CONTRACT: Final[DatabaseIntegrityContract] = replace(
    _BASE_INTEGRITY_CONTRACT,
    source_migration=("programme", "0005_accepted_item_integrity"),
    source_migration_module="maru.programme.migrations.0005_accepted_item_integrity",
    terminal_migration=("programme", "0006_accepted_item_downgrade_fence"),
    functions={**_BASE_INTEGRITY_CONTRACT.functions, **_ACCEPTED_FUNCTIONS},
    source_contract_current=(
        _BASE_INTEGRITY_CONTRACT.source_contract_current
        and _accepted_migration_contract_is_current()
    ),
)


_HOST_MIGRATION = import_module("maru.programme.migrations.0008_host_integrity")
_HOST_FENCE = import_module("maru.programme.migrations.0009_host_downgrade_fence")
_HOST_FENCE_SOURCE_SHA256: Final = (
    "aa1280fc75722119cdc55e9ee260edb119455f332a71d200629a58a0610c41ef"
)


def _host_migration_contract_is_current() -> bool:
    operations = tuple(_HOST_MIGRATION.Migration.operations)
    fences = tuple(_HOST_FENCE.Migration.operations)
    reverse = _HOST_FENCE.refuse_used_host_downgrade
    source = inspect.getsource(reverse).replace("\r\n", "\n")
    return (
        len(operations) == len(fences) == 1
        and isinstance(operations[0], migrations.RunSQL)
        and operations[0].sql == _HOST_MIGRATION.FORWARD_SQL
        and operations[0].reverse_sql == _HOST_MIGRATION.REVERSE_SQL
        and tuple(_HOST_MIGRATION.Migration.dependencies)
        == (
            ("programme", "0007_host_relationships"),
            ("authorization", "0026_programme_host_capabilities"),
        )
        and isinstance(fences[0], migrations.RunPython)
        and fences[0].code is migrations.RunPython.noop
        and fences[0].reverse_code is reverse
        and tuple(_HOST_FENCE.Migration.dependencies)
        == (("programme", "0008_host_integrity"),)
        and hashlib.sha256(source.encode()).hexdigest() == _HOST_FENCE_SOURCE_SHA256
    )


_HOST_TRIGGERS, _HOST_FUNCTIONS = parse_database_integrity_sql_contracts(
    _HOST_MIGRATION.FORWARD_SQL
)
_HOST_INTEGRITY_CONTRACT: Final[DatabaseIntegrityContract] = replace(
    _ACCEPTED_INTEGRITY_CONTRACT,
    source_migration=("programme", "0008_host_integrity"),
    source_migration_module="maru.programme.migrations.0008_host_integrity",
    terminal_migration=("programme", "0009_host_downgrade_fence"),
    triggers={**_ACCEPTED_INTEGRITY_CONTRACT.triggers, **_HOST_TRIGGERS},
    functions={**_ACCEPTED_INTEGRITY_CONTRACT.functions, **_HOST_FUNCTIONS},
    source_contract_current=(
        _ACCEPTED_INTEGRITY_CONTRACT.source_contract_current
        and _host_migration_contract_is_current()
    ),
)


_STAFFING_MIGRATION = import_module("maru.programme.migrations.0011_staffing_integrity")
_STAFFING_FENCE = import_module(
    "maru.programme.migrations.0012_staffing_downgrade_fence"
)
_STAFFING_FENCE_SOURCE_SHA256: Final = (
    "e3abc764fd33ff4671525442e8871659ddf3cda10877dc208f39c52f4a5e4d99"
)


def _staffing_migration_contract_is_current() -> bool:
    operations = tuple(_STAFFING_MIGRATION.Migration.operations)
    fences = tuple(_STAFFING_FENCE.Migration.operations)
    reverse = _STAFFING_FENCE.refuse_used_staffing_downgrade
    source = inspect.getsource(reverse).replace("\r\n", "\n")
    return (
        len(operations) == len(fences) == 1
        and isinstance(operations[0], migrations.RunSQL)
        and operations[0].sql == _STAFFING_MIGRATION.FORWARD_SQL
        and operations[0].reverse_sql == _STAFFING_MIGRATION.REVERSE_SQL
        and tuple(_STAFFING_MIGRATION.Migration.dependencies)
        == (
            ("programme", "0010_staffing_requirements"),
            ("authorization", "0028_programme_staffing_capabilities"),
        )
        and isinstance(fences[0], migrations.RunPython)
        and fences[0].code is migrations.RunPython.noop
        and fences[0].reverse_code is reverse
        and tuple(_STAFFING_FENCE.Migration.dependencies)
        == (("programme", "0011_staffing_integrity"),)
        and hashlib.sha256(source.encode()).hexdigest() == _STAFFING_FENCE_SOURCE_SHA256
    )


_STAFFING_TRIGGERS, _STAFFING_FUNCTIONS = parse_database_integrity_sql_contracts(
    _STAFFING_MIGRATION.FORWARD_SQL
)
PROGRAMME_INTEGRITY_CONTRACT: Final[DatabaseIntegrityContract] = replace(
    _HOST_INTEGRITY_CONTRACT,
    source_migration=("programme", "0011_staffing_integrity"),
    source_migration_module="maru.programme.migrations.0011_staffing_integrity",
    terminal_migration=("programme", "0012_staffing_downgrade_fence"),
    triggers={**_HOST_INTEGRITY_CONTRACT.triggers, **_STAFFING_TRIGGERS},
    functions={**_HOST_INTEGRITY_CONTRACT.functions, **_STAFFING_FUNCTIONS},
    source_contract_current=(
        _HOST_INTEGRITY_CONTRACT.source_contract_current
        and _staffing_migration_contract_is_current()
    ),
)


@dataclass(frozen=True, slots=True)
class ProgrammeSchemaCatalog:
    """Data-free result of the Programme-owned relation-shape inspection.

    Attributes
    ----------
    schema_fingerprints_finalized
        Whether the immutable constraint/index digest catalog is complete.
    relations_current
        Whether every Programme relation has the exact declared table
        semantics and no unexpected Programme relation exists.
    columns_current
        Whether every column matches its declared type, nullability, default,
        generation, identity, and collation semantics.
    constraints_current
        Whether the complete constraint set and canonical definitions match.
    indexes_current
        Whether the complete index set, canonical definitions, and operational
        metadata match.
    """

    schema_fingerprints_finalized: bool
    relations_current: bool
    columns_current: bool
    constraints_current: bool
    indexes_current: bool

    @property
    def ready(self) -> bool:
        """Return whether every Programme relation shape is exact."""
        return all(
            (
                self.schema_fingerprints_finalized,
                self.relations_current,
                self.columns_current,
                self.constraints_current,
                self.indexes_current,
            )
        )


PROGRAMME_RELATION_SEMANTICS: Final[
    Mapping[str, tuple[str, str, bool, bool, bool, str]]
] = {
    "programme_programmecommandreceipt": ("r", "p", False, False, False, "d"),
    "programme_programmedeliveryrevision": ("r", "p", False, False, False, "d"),
    "programme_programmedepartmentdiscussionentry": (
        "r",
        "p",
        False,
        False,
        False,
        "d",
    ),
    "programme_programmeeditioncontrol": ("r", "p", False, False, False, "d"),
    "programme_programmehostrelationship": ("r", "p", False, False, False, "d"),
    "programme_programmehostinvitation": ("r", "p", False, False, False, "d"),
    "programme_programmehostrevision": ("r", "p", False, False, False, "d"),
    "programme_programmehostavailabilitywindow": ("r", "p", False, False, False, "d"),
    "programme_programmestaffingrequirement": ("r", "p", False, False, False, "d"),
    "programme_programmestaffingrevision": ("r", "p", False, False, False, "d"),
    "programme_programmeitem": ("r", "p", False, False, False, "d"),
    "programme_programmeitemsourcebinding": (
        "r",
        "p",
        False,
        False,
        False,
        "d",
    ),
    "programme_programmepublicrendition": ("r", "p", False, False, False, "d"),
    "programme_programmereadinessevidence": (
        "r",
        "p",
        False,
        False,
        False,
        "d",
    ),
    "programme_programmereadinessrequirement": (
        "r",
        "p",
        False,
        False,
        False,
        "d",
    ),
    "programme_programmereadinessrequirementrevision": (
        "r",
        "p",
        False,
        False,
        False,
        "d",
    ),
    "programme_programmeworkingrevision": ("r", "p", False, False, False, "d"),
}

_NO_COLLATION_IDENTITY: Final = (None,) * 10
_DEFAULT_COLLATION_IDENTITY: Final = (
    "pg_catalog",
    "default",
    "d",
    True,
    -1,
    None,
    None,
    None,
    None,
    None,
)


# Finalized only from a freshly migrated PostgreSQL catalog. Each value is the
# SHA-256 of immutable catalog metadata followed by the canonical definition
# digest from pg_get_constraintdef(..., TRUE) or pg_get_indexdef(...).
# An incomplete mapping deliberately keeps Programme readiness blocked.
PROGRAMME_SCHEMA_OBJECT_SHA256: Final[Mapping[str, tuple[str, str]]] = {
    (
        "constraint:programme_programmestaffingrequirement:"
        "programme_programmes_edition_id_3b76c76c_fk_events_ev"
    ): (
        "6a31c0acb039c132e7b20c6f77f541a14ebb47451a3c4fdb0c7cf4ae9762b46c",
        "03a7996ab8afb527585471eb2cbfd7058942319058cc05e3f26732b9ade4e0cc",
    ),
    (
        "constraint:programme_programmestaffingrequirement:"
        "programme_programmes_item_id_4af55129_fk_programme"
    ): (
        "6a31c0acb039c132e7b20c6f77f541a14ebb47451a3c4fdb0c7cf4ae9762b46c",
        "29bc9e574fb186040bcedd470867b5969bfc9cfe526c4fac8fc4a66bc20d7c84",
    ),
    (
        "constraint:programme_programmestaffingrequirement:"
        "programme_programmes_last_modified_by_id_28482e46_fk_identity_"
    ): (
        "6a31c0acb039c132e7b20c6f77f541a14ebb47451a3c4fdb0c7cf4ae9762b46c",
        "2c0aff8c19e72bf6f121c9bed55c36858f7a7d671ccee0e376cd614e2dbf22ac",
    ),
    (
        "constraint:programme_programmestaffingrequirement:"
        "programme_programmes_occurrence_id_65d49afc_fk_schedulin"
    ): (
        "6a31c0acb039c132e7b20c6f77f541a14ebb47451a3c4fdb0c7cf4ae9762b46c",
        "1f83f28297660944358326a5e1f402dcf15a53d73511e0f1cd639c8b8b9cf32c",
    ),
    (
        "constraint:programme_programmestaffingrequirement:"
        "programme_programmes_organization_id_f8bd728d_fk_organizat"
    ): (
        "6a31c0acb039c132e7b20c6f77f541a14ebb47451a3c4fdb0c7cf4ae9762b46c",
        "07f454abd16b9f770cd0320efd71f154b0187daf9dbe65e3e6e57121eacd062f",
    ),
    (
        "constraint:programme_programmestaffingrequirement:"
        "programme_programmestaffingrequirement_item_version_check"
    ): (
        "266529509becaec155c88070ee9269179d92af1fe916647111917b724d479ed1",
        "7b6d65d5670d3436adcbd8cae1a19da73177498534211163b7ab24ccb9fc8a50",
    ),
    (
        "constraint:programme_programmestaffingrequirement:"
        "programme_programmestaffingrequirement_pkey"
    ): (
        "7f34a8c8922eb6dfb3caa97a32808b68a380d0e1d58433df5dfc0f943e5ed402",
        "8c8464f42472e42ee190fc91ca8db79b5351d3a4609040516578d229c56f6fa5",
    ),
    (
        "constraint:programme_programmestaffingrequirement:"
        "programme_programmestaffingrequirement_version_check"
    ): (
        "266529509becaec155c88070ee9269179d92af1fe916647111917b724d479ed1",
        "ce468a9ec0ef7e34f6871d17c4cebc8cbb55944458fb50f5898e0a0cc9beb809",
    ),
    (
        "constraint:programme_programmestaffingrequirement:"
        "programme_staffing_lifecycle_closed"
    ): (
        "266529509becaec155c88070ee9269179d92af1fe916647111917b724d479ed1",
        "880b8febbfb7419537d3b00d8eb0bea81d6fe34ba51690d08b89d2aae092f1bc",
    ),
    (
        "constraint:programme_programmestaffingrequirement:"
        "programme_staffing_versions_valid"
    ): (
        "266529509becaec155c88070ee9269179d92af1fe916647111917b724d479ed1",
        "ebd1698c561048ad82f5491883eccb8f1546ca43ee130b38db3b4b82d2aee813",
    ),
    (
        "constraint:programme_programmestaffingrequirement:"
        "programme_staffingrequirement_evidence"
    ): (
        "71e2226f085937dbb5f6cd59196c8d2082220987a6704d095df108d9de91948b",
        "698fc09045e7267eeb19c5b09473ec8c40f237145be8c1cbd97b9dde2451ddc1",
    ),
    (
        "constraint:programme_programmestaffingrevision:"
        "programme_programmes_actor_id_363fce8d_fk_identity_"
    ): (
        "cbb505cd693ddea6a1e614306d7aed4731223ea8b5d078f33ab3fabf4e5b59b8",
        "4ed87fd0d94daa63ad880b35b54252ad3f58c69aabfdc3065c99dda56093b807",
    ),
    (
        "constraint:programme_programmestaffingrevision:"
        "programme_programmes_edition_id_a82800da_fk_events_ev"
    ): (
        "cbb505cd693ddea6a1e614306d7aed4731223ea8b5d078f33ab3fabf4e5b59b8",
        "03a7996ab8afb527585471eb2cbfd7058942319058cc05e3f26732b9ade4e0cc",
    ),
    (
        "constraint:programme_programmestaffingrevision:"
        "programme_programmes_item_id_16e6c0ef_fk_programme"
    ): (
        "cbb505cd693ddea6a1e614306d7aed4731223ea8b5d078f33ab3fabf4e5b59b8",
        "29bc9e574fb186040bcedd470867b5969bfc9cfe526c4fac8fc4a66bc20d7c84",
    ),
    (
        "constraint:programme_programmestaffingrevision:"
        "programme_programmes_organization_id_9d4957d6_fk_organizat"
    ): (
        "cbb505cd693ddea6a1e614306d7aed4731223ea8b5d078f33ab3fabf4e5b59b8",
        "07f454abd16b9f770cd0320efd71f154b0187daf9dbe65e3e6e57121eacd062f",
    ),
    (
        "constraint:programme_programmestaffingrevision:"
        "programme_programmes_position_id_83cbaab3_fk_workforce"
    ): (
        "cbb505cd693ddea6a1e614306d7aed4731223ea8b5d078f33ab3fabf4e5b59b8",
        "20744d41eadf7288467299431f8a55a71a3c187c6403b981379361bff25b4aed",
    ),
    (
        "constraint:programme_programmestaffingrevision:"
        "programme_programmes_requirement_id_72579c99_fk_programme"
    ): (
        "cbb505cd693ddea6a1e614306d7aed4731223ea8b5d078f33ab3fabf4e5b59b8",
        "715139466aab91ed3d47e9c6e580d47f545a7a0b26c06d45184ee1f7843605fb",
    ),
    (
        "constraint:programme_programmestaffingrevision:"
        "programme_programmestaffingrevision_break_minutes_check"
    ): (
        "62601de95b52e0d0013a3325131fa69afb2d9d3934c225d7273e381ee562d4d4",
        "8e2a36b04c5d7865cd8815b8d1f0b370f866625441308663fc1c73f3560f1f6c",
    ),
    (
        "constraint:programme_programmestaffingrevision:"
        "programme_programmestaffingrevision_item_version_check"
    ): (
        "62601de95b52e0d0013a3325131fa69afb2d9d3934c225d7273e381ee562d4d4",
        "7b6d65d5670d3436adcbd8cae1a19da73177498534211163b7ab24ccb9fc8a50",
    ),
    (
        "constraint:programme_programmestaffingrevision:"
        "programme_programmestaffingrevision_minimum_rest_minutes_check"
    ): (
        "62601de95b52e0d0013a3325131fa69afb2d9d3934c225d7273e381ee562d4d4",
        "197c7d44d76b1bfdda2d4e1c60f5cdeb401399bfd88e20462edd369997df9094",
    ),
    (
        "constraint:programme_programmestaffingrevision:"
        "programme_programmestaffingrevision_occurrence_version_check"
    ): (
        "62601de95b52e0d0013a3325131fa69afb2d9d3934c225d7273e381ee562d4d4",
        "3bcb1500c3df52a97912d7c6f64eeb9e6a95dbe81ed9cabe44c65de48ade81d8",
    ),
    (
        "constraint:programme_programmestaffingrevision:"
        "programme_programmestaffingrevision_pkey"
    ): (
        "a7212cb713d36f204c0e5c17de51bbb34ba0e7ad8ce1f4b474ccbf828f357ae5",
        "8c8464f42472e42ee190fc91ca8db79b5351d3a4609040516578d229c56f6fa5",
    ),
    (
        "constraint:programme_programmestaffingrevision:"
        "programme_programmestaffingrevision_required_headcount_check"
    ): (
        "62601de95b52e0d0013a3325131fa69afb2d9d3934c225d7273e381ee562d4d4",
        "1c1325909e122f7e2b10d4a4c5d64cc83e5207f34f4975781e70c6b01b00f3ae",
    ),
    (
        "constraint:programme_programmestaffingrevision:"
        "programme_programmestaffingrevision_sequence_check"
    ): (
        "62601de95b52e0d0013a3325131fa69afb2d9d3934c225d7273e381ee562d4d4",
        "8f426ab72466a993c9c30383cb064c0d9e1286aed4585cb08cb0ccdec86be0aa",
    ),
    (
        "constraint:programme_programmestaffingrevision:"
        "programme_staffing_revision_interval"
    ): (
        "62601de95b52e0d0013a3325131fa69afb2d9d3934c225d7273e381ee562d4d4",
        "f7f53564896884f1edf5917820a7ba41f7cffde42c77a1d84f965bcfaa474baf",
    ),
    (
        "constraint:programme_programmestaffingrevision:"
        "programme_staffing_revision_lifecycle"
    ): (
        "62601de95b52e0d0013a3325131fa69afb2d9d3934c225d7273e381ee562d4d4",
        "880b8febbfb7419537d3b00d8eb0bea81d6fe34ba51690d08b89d2aae092f1bc",
    ),
    (
        "constraint:programme_programmestaffingrevision:"
        "programme_staffing_revision_limits"
    ): (
        "62601de95b52e0d0013a3325131fa69afb2d9d3934c225d7273e381ee562d4d4",
        "9d260cf6c5bf0a3d01d373c2884d93c98a904b2427e5a3c13e31abc489942926",
    ),
    (
        "constraint:programme_programmestaffingrevision:"
        "programme_staffing_revision_operation"
    ): (
        "62601de95b52e0d0013a3325131fa69afb2d9d3934c225d7273e381ee562d4d4",
        "6acd16153731241c96d175a2735df7e8ea1ab78518394991c22648f171f62ae8",
    ),
    (
        "constraint:programme_programmestaffingrevision:"
        "programme_staffing_revision_seq_uq"
    ): (
        "eb0bd34803c4e0486ad16cb934ee227f3164dcfed8eba4843f19798ebb2d4df1",
        "f13cd5112aa855b20572eb148d50223b5c16c4b6b18967512e41c682f112175b",
    ),
    (
        "constraint:programme_programmestaffingrevision:"
        "programme_staffing_revision_versions"
    ): (
        "62601de95b52e0d0013a3325131fa69afb2d9d3934c225d7273e381ee562d4d4",
        "41f09f59c8875a17c9d160ad0e74f2e8bd97fad2ca05dd9fc7a31f739a1339bd",
    ),
    (
        "constraint:programme_programmestaffingrevision:"
        "programme_staffingrevision_evidence"
    ): (
        "9ac31761324d7a0d899e8253266c64453a6fc9497991912c26a8a9f33eec3d1e",
        "698fc09045e7267eeb19c5b09473ec8c40f237145be8c1cbd97b9dde2451ddc1",
    ),
    (
        "index:programme_programmestaffingrequirement:"
        "programme_programmestaffin_last_modified_by_id_28482e46"
    ): (
        "9ff6178f739ea0bade109d51e196980e3462646b2ce5ac3e3aed283c5316eaad",
        "f189a7c50a7ce7ad3bc3048944ccdf14059c124e01f23aa2b08d556406378137",
    ),
    (
        "index:programme_programmestaffingrequirement:"
        "programme_programmestaffingrequirement_edition_id_3b76c76c"
    ): (
        "9ff6178f739ea0bade109d51e196980e3462646b2ce5ac3e3aed283c5316eaad",
        "047bc830901f6b3fa383519275afdb38b4c568729689ba53741e88e07f9bee84",
    ),
    (
        "index:programme_programmestaffingrequirement:"
        "programme_programmestaffingrequirement_item_id_4af55129"
    ): (
        "9ff6178f739ea0bade109d51e196980e3462646b2ce5ac3e3aed283c5316eaad",
        "4d35dfe0ddd8f17c1779086c10c8137866ae56101b0b927c5f403b9ed60021bf",
    ),
    (
        "index:programme_programmestaffingrequirement:"
        "programme_programmestaffingrequirement_occurrence_id_65d49afc"
    ): (
        "9ff6178f739ea0bade109d51e196980e3462646b2ce5ac3e3aed283c5316eaad",
        "368f59807c755ad61cbee3602755f6c9f6dd3c4b5f9768ec2aa35b86dc8b2b5a",
    ),
    (
        "index:programme_programmestaffingrequirement:"
        "programme_programmestaffingrequirement_organization_id_f8bd728d"
    ): (
        "9ff6178f739ea0bade109d51e196980e3462646b2ce5ac3e3aed283c5316eaad",
        "c191bf1ef32fba8790c706a1abdfcf209ae91a938d17ac1339fdbc3a21f51822",
    ),
    (
        "index:programme_programmestaffingrequirement:"
        "programme_programmestaffingrequirement_pkey"
    ): (
        "4e6fc037b645905409769e49803891e967a9e6a72e89c4a98b563e53f4cd8948",
        "690b800c97e2d0c7754f756246d1a92500a66f0ddd16fef227a8fe4f99ce0f59",
    ),
    "index:programme_programmestaffingrequirement:programme_staffing_scope_idx": (
        "5fb168b0b92be9c351bfed2ee64583d580469da885426decc678831bd7353620",
        "e8e5e1a8414ca0fa7568a06dac2e83d2d2d9a3a33ff549dbeab6589050849140",
    ),
    (
        "index:programme_programmestaffingrevision:"
        "programme_programmestaffingrevision_actor_id_363fce8d"
    ): (
        "6b811c1c0a2e3274bac3b94117983e8dd502e4f7e7b4bef6e1a4b369fd7861c2",
        "9add77aef6c34505a577daa5d5d332e589c3ba82284f2a9441a22f18834bc077",
    ),
    (
        "index:programme_programmestaffingrevision:"
        "programme_programmestaffingrevision_edition_id_a82800da"
    ): (
        "6b811c1c0a2e3274bac3b94117983e8dd502e4f7e7b4bef6e1a4b369fd7861c2",
        "68c201244552c2a0f16f0ef830b35bec368518a2cf6f225f938aa9104e0a425a",
    ),
    (
        "index:programme_programmestaffingrevision:"
        "programme_programmestaffingrevision_item_id_16e6c0ef"
    ): (
        "6b811c1c0a2e3274bac3b94117983e8dd502e4f7e7b4bef6e1a4b369fd7861c2",
        "e92f5d15771e0bbd1039df31bebc652257b0c78b35f07d1ab4656a62f58636d1",
    ),
    (
        "index:programme_programmestaffingrevision:"
        "programme_programmestaffingrevision_organization_id_9d4957d6"
    ): (
        "6b811c1c0a2e3274bac3b94117983e8dd502e4f7e7b4bef6e1a4b369fd7861c2",
        "f88dbd66509e27e61df103a3cd4b882d4a7ef3c891d5287d5a5d1335c9e34540",
    ),
    (
        "index:programme_programmestaffingrevision:"
        "programme_programmestaffingrevision_pkey"
    ): (
        "2970ef18cd561d1f4dd6047bb5d637401b18edbbff61ba0639567ed28c7705fd",
        "62b8cfb9dc04344016e1cd40d755193a86c88802bbffc4b49a8c024a285c232a",
    ),
    (
        "index:programme_programmestaffingrevision:"
        "programme_programmestaffingrevision_position_id_83cbaab3"
    ): (
        "6b811c1c0a2e3274bac3b94117983e8dd502e4f7e7b4bef6e1a4b369fd7861c2",
        "7fffd5bd76916cb758faf70a163d28eba7c208f365a5fa40b8cb0335d2369e0a",
    ),
    (
        "index:programme_programmestaffingrevision:"
        "programme_programmestaffingrevision_requirement_id_72579c99"
    ): (
        "6b811c1c0a2e3274bac3b94117983e8dd502e4f7e7b4bef6e1a4b369fd7861c2",
        "f6e191617f0626684c3396e3b3226d571b5418a1902d0387cd6495b530ba1cde",
    ),
    "index:programme_programmestaffingrevision:programme_staffing_revision_seq_uq": (
        "31b65a9f573a13fb33a018a6c97f5c75df9f60123b414e0e2a36f93706620abc",
        "dec670e9d441a40433067ee03901c5087691b46ae3a74e3d830766fc0c919908",
    ),
    "constraint:programme_programmehostavailabilitywindow:programme_host_window_kind": (
        "e188a63e47ce088fcd4f16a36e7dc94a59d959fe3dee823a8b199813514fb412",
        "b8fecad9f486094b4b5139578c093b82bd8f09d558e7df1435ca62ff5a29a220",
    ),
    (
        "constraint:programme_programmehostavailabilitywindow:"
        "programme_host_window_positive"
    ): (
        "e188a63e47ce088fcd4f16a36e7dc94a59d959fe3dee823a8b199813514fb412",
        "f7f53564896884f1edf5917820a7ba41f7cffde42c77a1d84f965bcfaa474baf",
    ),
    (
        "constraint:programme_programmehostavailabilitywindow:"
        "programme_host_window_start_uq"
    ): (
        "5cc97e7803bd8f7a51052493949639710f4595571a86488e62055a7a9ff4d19b",
        "9d61f58c80175276cbd7e6608500201726e24857cc3dbbafab003228cc7e3d26",
    ),
    (
        "constraint:programme_programmehostavailabilitywindow:"
        "programme_hostavailabilitywindow_evidence"
    ): (
        "722a47fd5e87cb6a8cdcc524277ad118fee3b001eba1ec009c43a88850f5d302",
        "698fc09045e7267eeb19c5b09473ec8c40f237145be8c1cbd97b9dde2451ddc1",
    ),
    (
        "constraint:programme_programmehostavailabilitywindow:"
        "programme_programmeh_edition_id_d1ca6d27_fk_events_ev"
    ): (
        "e40047b7e7174304ca27815e66102608230dbc805728c56f778d799ceab9475f",
        "03a7996ab8afb527585471eb2cbfd7058942319058cc05e3f26732b9ade4e0cc",
    ),
    (
        "constraint:programme_programmehostavailabilitywindow:"
        "programme_programmeh_host_id_217228db_fk_programme"
    ): (
        "e40047b7e7174304ca27815e66102608230dbc805728c56f778d799ceab9475f",
        "9f62bfc4b71c3ece8230a5fb8e3d1c9a2c5c46d60b477cdf13f300f3b1d974e2",
    ),
    (
        "constraint:programme_programmehostavailabilitywindow:"
        "programme_programmeh_item_id_bbe28f80_fk_programme"
    ): (
        "e40047b7e7174304ca27815e66102608230dbc805728c56f778d799ceab9475f",
        "29bc9e574fb186040bcedd470867b5969bfc9cfe526c4fac8fc4a66bc20d7c84",
    ),
    (
        "constraint:programme_programmehostavailabilitywindow:"
        "programme_programmeh_organization_id_3c97849a_fk_organizat"
    ): (
        "e40047b7e7174304ca27815e66102608230dbc805728c56f778d799ceab9475f",
        "07f454abd16b9f770cd0320efd71f154b0187daf9dbe65e3e6e57121eacd062f",
    ),
    (
        "constraint:programme_programmehostavailabilitywindow:"
        "programme_programmehostavailabilitywindow_pkey"
    ): (
        "e7924b2f23e3a3e0973b1ff96dd980e79d9139aca66d61b85c1c5cafd60d9924",
        "8c8464f42472e42ee190fc91ca8db79b5351d3a4609040516578d229c56f6fa5",
    ),
    "constraint:programme_programmehostinvitation:programme_host_invitation_role": (
        "9b740b525b9f59fbe6efe8e0fa2c6a62a766aa2e713c9500d830752dfd54eecf",
        "f3f644878f636187ca3191575e23614bf0ee0cf932d48c391c714074476f0e51",
    ),
    "constraint:programme_programmehostinvitation:programme_host_invitation_seq_uq": (
        "754ea3a2c043b001ac540be205af7e38c760320c495e68e546394ee68b229a3e",
        "1e063b5fc8d3a9cdbe93652145814bef999a0f40ecd608561d328881870c5c14",
    ),
    "constraint:programme_programmehostinvitation:programme_host_invitation_versions": (
        "9b740b525b9f59fbe6efe8e0fa2c6a62a766aa2e713c9500d830752dfd54eecf",
        "6c5c6d1e4e49750615138f2687d67ca0731ea2cb0bb38d9acc7be2a57ef9cab0",
    ),
    "constraint:programme_programmehostinvitation:programme_hostinvitation_evidence": (
        "29c731d89afe62f62fd11b046afb026e7fca8998c6814da43617c4f0c7bb8d2e",
        "698fc09045e7267eeb19c5b09473ec8c40f237145be8c1cbd97b9dde2451ddc1",
    ),
    (
        "constraint:programme_programmehostinvitation:"
        "programme_programmeh_actor_id_5b3d0a05_fk_identity_"
    ): (
        "055332a35312ded8ee45b089512dcb89cbf05a93d95a6987ca49ec52f5885dda",
        "4ed87fd0d94daa63ad880b35b54252ad3f58c69aabfdc3065c99dda56093b807",
    ),
    (
        "constraint:programme_programmehostinvitation:"
        "programme_programmeh_edition_id_d1349294_fk_events_ev"
    ): (
        "055332a35312ded8ee45b089512dcb89cbf05a93d95a6987ca49ec52f5885dda",
        "03a7996ab8afb527585471eb2cbfd7058942319058cc05e3f26732b9ade4e0cc",
    ),
    (
        "constraint:programme_programmehostinvitation:"
        "programme_programmeh_host_id_0c121527_fk_programme"
    ): (
        "055332a35312ded8ee45b089512dcb89cbf05a93d95a6987ca49ec52f5885dda",
        "9f62bfc4b71c3ece8230a5fb8e3d1c9a2c5c46d60b477cdf13f300f3b1d974e2",
    ),
    (
        "constraint:programme_programmehostinvitation:"
        "programme_programmeh_item_id_8aa18352_fk_programme"
    ): (
        "055332a35312ded8ee45b089512dcb89cbf05a93d95a6987ca49ec52f5885dda",
        "29bc9e574fb186040bcedd470867b5969bfc9cfe526c4fac8fc4a66bc20d7c84",
    ),
    (
        "constraint:programme_programmehostinvitation:"
        "programme_programmeh_organization_id_034ebd09_fk_organizat"
    ): (
        "055332a35312ded8ee45b089512dcb89cbf05a93d95a6987ca49ec52f5885dda",
        "07f454abd16b9f770cd0320efd71f154b0187daf9dbe65e3e6e57121eacd062f",
    ),
    (
        "constraint:programme_programmehostinvitation:"
        "programme_programmehostinvitation_host_version_check"
    ): (
        "9b740b525b9f59fbe6efe8e0fa2c6a62a766aa2e713c9500d830752dfd54eecf",
        "de77166d351c9e6562464d29596e211fcf44606c7ed4c0e11777d2bac7e362a4",
    ),
    (
        "constraint:programme_programmehostinvitation:"
        "programme_programmehostinvitation_item_version_check"
    ): (
        "9b740b525b9f59fbe6efe8e0fa2c6a62a766aa2e713c9500d830752dfd54eecf",
        "7b6d65d5670d3436adcbd8cae1a19da73177498534211163b7ab24ccb9fc8a50",
    ),
    (
        "constraint:programme_programmehostinvitation:"
        "programme_programmehostinvitation_pkey"
    ): (
        "d3bae9b27a5d14a0f7614e29648b688a2c40c7a4b70ddc7ffce6fa1d6059bc12",
        "8c8464f42472e42ee190fc91ca8db79b5351d3a4609040516578d229c56f6fa5",
    ),
    (
        "constraint:programme_programmehostinvitation:"
        "programme_programmehostinvitation_sequence_check"
    ): (
        "9b740b525b9f59fbe6efe8e0fa2c6a62a766aa2e713c9500d830752dfd54eecf",
        "8f426ab72466a993c9c30383cb064c0d9e1286aed4585cb08cb0ccdec86be0aa",
    ),
    (
        "constraint:programme_programmehostrelationship:"
        "programme_host_availability_closed"
    ): (
        "554872b216bca24c17d1669c44310d9d96d7275ffd25512a8ad3c192881587b7",
        "57f29d30c3fa0d864ba06d371719f810bda835e418962d63f164ceca4f68816b",
    ),
    "constraint:programme_programmehostrelationship:programme_host_item_person_uq": (
        "515ced7c5b49cc460d750b7e50df9ff1b58e8169529adcd815a2b4eaf65a06c4",
        "36db1a691011bf19f5ec7a1f324c621a64d77832a954fe35608dbca3d3fddba7",
    ),
    "constraint:programme_programmehostrelationship:programme_host_role_closed": (
        "554872b216bca24c17d1669c44310d9d96d7275ffd25512a8ad3c192881587b7",
        "f3f644878f636187ca3191575e23614bf0ee0cf932d48c391c714074476f0e51",
    ),
    "constraint:programme_programmehostrelationship:programme_host_state_closed": (
        "554872b216bca24c17d1669c44310d9d96d7275ffd25512a8ad3c192881587b7",
        "4eaf6d0e27af97b3eb4371fbaa0dae01c99ae473ff76b6c186ad0ed50ca46f9b",
    ),
    "constraint:programme_programmehostrelationship:programme_host_versions_valid": (
        "554872b216bca24c17d1669c44310d9d96d7275ffd25512a8ad3c192881587b7",
        "5ae08f8538cf8f1f12a30bdfae0552530b28d15eaf6e2ae378e388d40e3b5c2b",
    ),
    (
        "constraint:programme_programmehostrelationship:"
        "programme_hostrelationship_evidence"
    ): (
        "12353d0a4126841d3e07646775e366388047d52fad93b5306499b5ac3dba214a",
        "698fc09045e7267eeb19c5b09473ec8c40f237145be8c1cbd97b9dde2451ddc1",
    ),
    (
        "constraint:programme_programmehostrelationship:"
        "programme_programmeh_account_id_999f5299_fk_identity_"
    ): (
        "b97b192bdd129171f1e0e6be3b1965bb82e693c295c30808d6a30632ffb2276d",
        "107afbd4f60d403b5110ded573fffbb13319289421561848fbf7786843e11d9a",
    ),
    (
        "constraint:programme_programmehostrelationship:"
        "programme_programmeh_edition_id_81577e8a_fk_events_ev"
    ): (
        "b97b192bdd129171f1e0e6be3b1965bb82e693c295c30808d6a30632ffb2276d",
        "03a7996ab8afb527585471eb2cbfd7058942319058cc05e3f26732b9ade4e0cc",
    ),
    (
        "constraint:programme_programmehostrelationship:"
        "programme_programmeh_item_id_ce341248_fk_programme"
    ): (
        "b97b192bdd129171f1e0e6be3b1965bb82e693c295c30808d6a30632ffb2276d",
        "29bc9e574fb186040bcedd470867b5969bfc9cfe526c4fac8fc4a66bc20d7c84",
    ),
    (
        "constraint:programme_programmehostrelationship:"
        "programme_programmeh_last_modified_by_id_abce55cb_fk_identity_"
    ): (
        "b97b192bdd129171f1e0e6be3b1965bb82e693c295c30808d6a30632ffb2276d",
        "2c0aff8c19e72bf6f121c9bed55c36858f7a7d671ccee0e376cd614e2dbf22ac",
    ),
    (
        "constraint:programme_programmehostrelationship:"
        "programme_programmeh_organization_id_34b8651d_fk_organizat"
    ): (
        "b97b192bdd129171f1e0e6be3b1965bb82e693c295c30808d6a30632ffb2276d",
        "07f454abd16b9f770cd0320efd71f154b0187daf9dbe65e3e6e57121eacd062f",
    ),
    (
        "constraint:programme_programmehostrelationship:"
        "programme_programmehostrelationship_availability_version_check"
    ): (
        "554872b216bca24c17d1669c44310d9d96d7275ffd25512a8ad3c192881587b7",
        "4d035e0519f09b467fa70b930c3c68fd7a97ec5e3d8aace4653322ec7147d630",
    ),
    (
        "constraint:programme_programmehostrelationship:"
        "programme_programmehostrelationship_invitation_sequence_check"
    ): (
        "554872b216bca24c17d1669c44310d9d96d7275ffd25512a8ad3c192881587b7",
        "86835eaeba5f687d07332f8002f5aae8e4675a958303fe8d2e1104d9becd0922",
    ),
    (
        "constraint:programme_programmehostrelationship:"
        "programme_programmehostrelationship_item_version_check"
    ): (
        "554872b216bca24c17d1669c44310d9d96d7275ffd25512a8ad3c192881587b7",
        "7b6d65d5670d3436adcbd8cae1a19da73177498534211163b7ab24ccb9fc8a50",
    ),
    (
        "constraint:programme_programmehostrelationship:"
        "programme_programmehostrelationship_pkey"
    ): (
        "6170c6f4b17f70275517230ad7bd08a6ef131848da02276e640dea8570f8d002",
        "8c8464f42472e42ee190fc91ca8db79b5351d3a4609040516578d229c56f6fa5",
    ),
    (
        "constraint:programme_programmehostrelationship:"
        "programme_programmehostrelationship_version_check"
    ): (
        "554872b216bca24c17d1669c44310d9d96d7275ffd25512a8ad3c192881587b7",
        "ce468a9ec0ef7e34f6871d17c4cebc8cbb55944458fb50f5898e0a0cc9beb809",
    ),
    "constraint:programme_programmehostrevision:programme_host_revision_operation": (
        "14d8487a1a979b3bd0d5295909f2713101a72aa8bc57a8f5c9ca641ff4dd0943",
        "f5acaeba66ec031a2cbecd458128527dd13c58ce3690433b9145c612d7ceab79",
    ),
    "constraint:programme_programmehostrevision:programme_host_revision_role": (
        "14d8487a1a979b3bd0d5295909f2713101a72aa8bc57a8f5c9ca641ff4dd0943",
        "f3f644878f636187ca3191575e23614bf0ee0cf932d48c391c714074476f0e51",
    ),
    "constraint:programme_programmehostrevision:programme_host_revision_seq_uq": (
        "39367d42e382ea1812b8def6258d0e95ca29645eb9eacefc4ba0b7750353fe71",
        "1e063b5fc8d3a9cdbe93652145814bef999a0f40ecd608561d328881870c5c14",
    ),
    "constraint:programme_programmehostrevision:programme_host_revision_sharing": (
        "14d8487a1a979b3bd0d5295909f2713101a72aa8bc57a8f5c9ca641ff4dd0943",
        "57f29d30c3fa0d864ba06d371719f810bda835e418962d63f164ceca4f68816b",
    ),
    "constraint:programme_programmehostrevision:programme_host_revision_state": (
        "14d8487a1a979b3bd0d5295909f2713101a72aa8bc57a8f5c9ca641ff4dd0943",
        "4eaf6d0e27af97b3eb4371fbaa0dae01c99ae473ff76b6c186ad0ed50ca46f9b",
    ),
    "constraint:programme_programmehostrevision:programme_host_revision_versions": (
        "14d8487a1a979b3bd0d5295909f2713101a72aa8bc57a8f5c9ca641ff4dd0943",
        "1a76ae4f441b8580f649ebac1941b5a2ff7ba6ef8d60307df7cbc28d577dbc34",
    ),
    "constraint:programme_programmehostrevision:programme_hostrevision_evidence": (
        "c2139125470af915e90ffc4cfe882a0f32c89e804ea8896ed022eb80404df4a6",
        "698fc09045e7267eeb19c5b09473ec8c40f237145be8c1cbd97b9dde2451ddc1",
    ),
    (
        "constraint:programme_programmehostrevision:"
        "programme_programmeh_actor_id_eb53efe5_fk_identity_"
    ): (
        "ddd214dca615e024a0fe9d85754041ce79be09f65cfc4907cbca8dcb95645890",
        "4ed87fd0d94daa63ad880b35b54252ad3f58c69aabfdc3065c99dda56093b807",
    ),
    (
        "constraint:programme_programmehostrevision:"
        "programme_programmeh_edition_id_13e8f248_fk_events_ev"
    ): (
        "ddd214dca615e024a0fe9d85754041ce79be09f65cfc4907cbca8dcb95645890",
        "03a7996ab8afb527585471eb2cbfd7058942319058cc05e3f26732b9ade4e0cc",
    ),
    (
        "constraint:programme_programmehostrevision:"
        "programme_programmeh_host_id_3d675b51_fk_programme"
    ): (
        "ddd214dca615e024a0fe9d85754041ce79be09f65cfc4907cbca8dcb95645890",
        "9f62bfc4b71c3ece8230a5fb8e3d1c9a2c5c46d60b477cdf13f300f3b1d974e2",
    ),
    (
        "constraint:programme_programmehostrevision:"
        "programme_programmeh_item_id_0adad59c_fk_programme"
    ): (
        "ddd214dca615e024a0fe9d85754041ce79be09f65cfc4907cbca8dcb95645890",
        "29bc9e574fb186040bcedd470867b5969bfc9cfe526c4fac8fc4a66bc20d7c84",
    ),
    (
        "constraint:programme_programmehostrevision:"
        "programme_programmeh_organization_id_9034f51f_fk_organizat"
    ): (
        "ddd214dca615e024a0fe9d85754041ce79be09f65cfc4907cbca8dcb95645890",
        "07f454abd16b9f770cd0320efd71f154b0187daf9dbe65e3e6e57121eacd062f",
    ),
    (
        "constraint:programme_programmehostrevision:"
        "programme_programmehostrevision_availability_version_check"
    ): (
        "14d8487a1a979b3bd0d5295909f2713101a72aa8bc57a8f5c9ca641ff4dd0943",
        "4d035e0519f09b467fa70b930c3c68fd7a97ec5e3d8aace4653322ec7147d630",
    ),
    (
        "constraint:programme_programmehostrevision:"
        "programme_programmehostrevision_invitation_sequence_check"
    ): (
        "14d8487a1a979b3bd0d5295909f2713101a72aa8bc57a8f5c9ca641ff4dd0943",
        "86835eaeba5f687d07332f8002f5aae8e4675a958303fe8d2e1104d9becd0922",
    ),
    (
        "constraint:programme_programmehostrevision:"
        "programme_programmehostrevision_item_version_check"
    ): (
        "14d8487a1a979b3bd0d5295909f2713101a72aa8bc57a8f5c9ca641ff4dd0943",
        "7b6d65d5670d3436adcbd8cae1a19da73177498534211163b7ab24ccb9fc8a50",
    ),
    (
        "constraint:programme_programmehostrevision:"
        "programme_programmehostrevision_period_count_check"
    ): (
        "14d8487a1a979b3bd0d5295909f2713101a72aa8bc57a8f5c9ca641ff4dd0943",
        "6d3005031b712d7d22721a8ab40e8f0e53f50a6c87551dd9913990b0e8ec0759",
    ),
    "constraint:programme_programmehostrevision:programme_programmehostrevision_pkey": (
        "d888e5d8181ad0defa0d6e4e35017be7b51becab6037ed20e6b5fab3fc38bbcc",
        "8c8464f42472e42ee190fc91ca8db79b5351d3a4609040516578d229c56f6fa5",
    ),
    (
        "constraint:programme_programmehostrevision:"
        "programme_programmehostrevision_sequence_check"
    ): (
        "14d8487a1a979b3bd0d5295909f2713101a72aa8bc57a8f5c9ca641ff4dd0943",
        "8f426ab72466a993c9c30383cb064c0d9e1286aed4585cb08cb0ccdec86be0aa",
    ),
    "index:programme_programmehostavailabilitywindow:programme_host_window_start_uq": (
        "94bfae1353d941d5956004c37bb1277d4c9a29ea39fd8d614af804d0d4b39cc0",
        "cb429bec2071bcf187f9c648d205f483532cfa64f4033514381d1ea63320fd0f",
    ),
    (
        "index:programme_programmehostavailabilitywindow:"
        "programme_programmehostava_organization_id_3c97849a"
    ): (
        "89c3b282d41b162e3c94e87c9e8ead7652817b0448168124067230e1cad11bfb",
        "57db84d9ab6c87303668de572d73a79ab8d3d6b58962ce7ed895775607354b4e",
    ),
    (
        "index:programme_programmehostavailabilitywindow:"
        "programme_programmehostavailabilitywindow_edition_id_d1ca6d27"
    ): (
        "89c3b282d41b162e3c94e87c9e8ead7652817b0448168124067230e1cad11bfb",
        "52a5634ac2899247ac6733e84e23cc7a8f28c072bfc9ad482923913746365797",
    ),
    (
        "index:programme_programmehostavailabilitywindow:"
        "programme_programmehostavailabilitywindow_host_id_217228db"
    ): (
        "89c3b282d41b162e3c94e87c9e8ead7652817b0448168124067230e1cad11bfb",
        "e2b52f3a243975e9659553250d9aea3efdbd02d1cd8c9a9191d5461458478da8",
    ),
    (
        "index:programme_programmehostavailabilitywindow:"
        "programme_programmehostavailabilitywindow_item_id_bbe28f80"
    ): (
        "89c3b282d41b162e3c94e87c9e8ead7652817b0448168124067230e1cad11bfb",
        "7de56589652191e42cf7e8f874e21a233333c945a758b74fd8f364cc39c3b202",
    ),
    (
        "index:programme_programmehostavailabilitywindow:"
        "programme_programmehostavailabilitywindow_pkey"
    ): (
        "4c0a8b82440cc44d18f3a3692254cab9fe1e16cd2794dc8d6ab40fbc6204a0b8",
        "a78eaed34e342b8fa377bb3ee6ec56f3fd4f592e7303d4dcad0c2d5fae572aef",
    ),
    "index:programme_programmehostinvitation:programme_host_invitation_seq_uq": (
        "527d3419525af50529576bfaf0b79fe81efacd695f3028e67c09ee2ea636b94e",
        "8c85eba9835a8e82b9e40bf8882b9fa7b1ccd55c6a759c1cd55136a13621f0a5",
    ),
    (
        "index:programme_programmehostinvitation:"
        "programme_programmehostinvitation_actor_id_5b3d0a05"
    ): (
        "7d12de2734782f1a7f916dc8fad47286e47a2fc57b4837cf7fa55194b1e129cf",
        "d274bc19eb0155fc3d11bf836d33760f00092e22b3016b070e5d72e9780b2fbf",
    ),
    (
        "index:programme_programmehostinvitation:"
        "programme_programmehostinvitation_edition_id_d1349294"
    ): (
        "7d12de2734782f1a7f916dc8fad47286e47a2fc57b4837cf7fa55194b1e129cf",
        "a8887ee763516c3b403d9d5680884478ab93873ae6febee584fbb3cc5ac038e1",
    ),
    (
        "index:programme_programmehostinvitation:"
        "programme_programmehostinvitation_host_id_0c121527"
    ): (
        "7d12de2734782f1a7f916dc8fad47286e47a2fc57b4837cf7fa55194b1e129cf",
        "d859f78b4b8d9507491125a4c196c5dfcbbd6928b0d8fa640a3c4197a5ede803",
    ),
    (
        "index:programme_programmehostinvitation:"
        "programme_programmehostinvitation_item_id_8aa18352"
    ): (
        "7d12de2734782f1a7f916dc8fad47286e47a2fc57b4837cf7fa55194b1e129cf",
        "9124596882541e1f6ad28d2f0c0540dd46efed4ca70957440c56e9fcb534d8c7",
    ),
    (
        "index:programme_programmehostinvitation:"
        "programme_programmehostinvitation_organization_id_034ebd09"
    ): (
        "7d12de2734782f1a7f916dc8fad47286e47a2fc57b4837cf7fa55194b1e129cf",
        "7e61e6b9819b9feb4a0083595d983260392e985a35fcdc785c9b4ecaad59da04",
    ),
    "index:programme_programmehostinvitation:programme_programmehostinvitation_pkey": (
        "280e112ee6677d85d464d369572de23c9fd9e13a08eb82455ca6af7bca0734c4",
        "019f0758f7059eb37cc7a69b6a33d487067ed68a25b6425abd9a7eeaf2c5faf0",
    ),
    "index:programme_programmehostrelationship:programme_host_item_person_uq": (
        "73e2ff8f32a0076cefbe2ccbb0c068626ed2a5630ff7454b92c10dbd0a27efd4",
        "eb83bb1c9c36db29d4788d9ab11e694ac1e098648c8a21e6aedd54e62a942068",
    ),
    "index:programme_programmehostrelationship:programme_host_self_scope_idx": (
        "73c33213cbcba18125bd59d608dad82aea7f7e66de2bde505e4b0c64c3c0c383",
        "8d98293cb67402fc265cbc4d7a5284f2e3486119b550491c584479baef3efe99",
    ),
    (
        "index:programme_programmehostrelationship:"
        "programme_programmehostrel_last_modified_by_id_abce55cb"
    ): (
        "e55fc984e406161c771d81925deab234cd5022d323ec5f5e204ef47c8ecc9443",
        "5a38e957787fdda45d79237adce99cfd12062e6e2430a7e7af30f08eb25c47d8",
    ),
    (
        "index:programme_programmehostrelationship:"
        "programme_programmehostrelationship_account_id_999f5299"
    ): (
        "e55fc984e406161c771d81925deab234cd5022d323ec5f5e204ef47c8ecc9443",
        "c2a78f1e0bde446ce79dacd1014776439e4ab5611bac8f63e27fcdf211ed776b",
    ),
    (
        "index:programme_programmehostrelationship:"
        "programme_programmehostrelationship_edition_id_81577e8a"
    ): (
        "e55fc984e406161c771d81925deab234cd5022d323ec5f5e204ef47c8ecc9443",
        "3d74a4971784bd02468051918e5ce0a5cf45a34f38f9deb55f771a2279b938aa",
    ),
    (
        "index:programme_programmehostrelationship:"
        "programme_programmehostrelationship_item_id_ce341248"
    ): (
        "e55fc984e406161c771d81925deab234cd5022d323ec5f5e204ef47c8ecc9443",
        "644067b1a4431f2cfbe0ff1c6731d726f9f504655e7a6d2ef94e8610174c404b",
    ),
    (
        "index:programme_programmehostrelationship:"
        "programme_programmehostrelationship_organization_id_34b8651d"
    ): (
        "e55fc984e406161c771d81925deab234cd5022d323ec5f5e204ef47c8ecc9443",
        "8eae4df197a026524562b6744fe5971d544dea709e36f7168ff054dc34f9ec25",
    ),
    (
        "index:programme_programmehostrelationship:"
        "programme_programmehostrelationship_pkey"
    ): (
        "dac2ec62fdd6bb5b551a019c01ffe52893578fb4c04cf2f85a173d8ef7d773e2",
        "cbe9094c288a7789b7659f5937702649f670b77bf9ac5c4140c3ee3b570f9645",
    ),
    "index:programme_programmehostrevision:programme_host_revision_seq_uq": (
        "0a823622b58b1f0e0753f059be92167da2b1d44a558ea723ed96dc039e2e24fc",
        "24ec5f1b43039cf0b91f14d1b5b6096e96978d8f227dd5725af191a25bd26b19",
    ),
    (
        "index:programme_programmehostrevision:"
        "programme_programmehostrevision_actor_id_eb53efe5"
    ): (
        "0b5d75100105a3543a1f52a3d80a1b024c9616527e4bd3b5de2a684c196dcf31",
        "75e673e7c459227e98fe5dac9f0ebc2a7162c4b32b77cb2345258fb03ac83497",
    ),
    (
        "index:programme_programmehostrevision:"
        "programme_programmehostrevision_edition_id_13e8f248"
    ): (
        "0b5d75100105a3543a1f52a3d80a1b024c9616527e4bd3b5de2a684c196dcf31",
        "b6b2b11ec21b6d7cf0595835d75255da70675f26a8b0dc2869a29d75a9617a79",
    ),
    (
        "index:programme_programmehostrevision:"
        "programme_programmehostrevision_host_id_3d675b51"
    ): (
        "0b5d75100105a3543a1f52a3d80a1b024c9616527e4bd3b5de2a684c196dcf31",
        "3f8d842d4fb5aec060c8fa5f66c03832582afa83a5d88dec872f1c5793b233ee",
    ),
    (
        "index:programme_programmehostrevision:"
        "programme_programmehostrevision_item_id_0adad59c"
    ): (
        "0b5d75100105a3543a1f52a3d80a1b024c9616527e4bd3b5de2a684c196dcf31",
        "8b430c1b3fc296e9f5c1e4448ad00e9b71e66c37ea5ca50d2e24e9dfac90fc34",
    ),
    (
        "index:programme_programmehostrevision:"
        "programme_programmehostrevision_organization_id_9034f51f"
    ): (
        "0b5d75100105a3543a1f52a3d80a1b024c9616527e4bd3b5de2a684c196dcf31",
        "46d528120bfc7a2d1570eba3829c90af73089367958f1faff34ffebb4b45a222",
    ),
    "index:programme_programmehostrevision:programme_programmehostrevision_pkey": (
        "891bed9f88e884f5278e9b8abe6e595fd52b22bb5f7b0b870c82d79108b5d2a7",
        "cdf93c2292e03752a0ff18551f061819ad89df25660049ad2d5e06ec9e15a8d8",
    ),
    (
        "constraint:programme_programmeitemsourcebinding:"
        "programme_programmei_source_object_id_919ad627_fk_applicati"
    ): (
        "1d99d998543b658a76114c747712ad9947af6cb05134fa10ca882284c9b1c4c7",
        "33791eeb3cf79961f4634c48201a4bb4abb6a4f28199bdedb0b9e8cdfc163c9b",
    ),
    (
        "index:programme_programmeitemsourcebinding:"
        "programme_programmeitemsourcebinding_source_object_id_919ad627"
    ): (
        "c118375dbfd58692d1c7d38c1152ef682aae2bbdc25b4cb661e03cf482140221",
        "8d05c175d02edfaac63a18c03866f6a8503ad1620d9ed305dc603400266d4df0",
    ),
    "constraint:programme_programmecommandreceipt:programme_command_control_shape": (
        "69d64ca9ff30b925a62e5ceda594c1aba7aebf94d273e697efce3721c42b6513",
        "9c040a483e76b5d0f519a40bbb578048cb8928370309d17f5ba000deff553235",
    ),
    "constraint:programme_programmecommandreceipt:programme_command_evidence_valid": (
        "69d64ca9ff30b925a62e5ceda594c1aba7aebf94d273e697efce3721c42b6513",
        "22d0079f947cebccbb36873062591d3cf5747ba53a19cc3a0b4a14c0d4a88e00",
    ),
    "constraint:programme_programmecommandreceipt:programme_command_operation_closed": (
        "69d64ca9ff30b925a62e5ceda594c1aba7aebf94d273e697efce3721c42b6513",
        "aa96039cefbfc326195765d17ec2244785cbf1b7a9653fad4315f1e3ca3d80ed",
    ),
    "constraint:programme_programmecommandreceipt:programme_command_retry_uq": (
        "6358fdf321257554281d71cf9659bff2557f29bff35c778c4126a1ec8b077945",
        "694469bf91b8d94c79aad6f8f45558ed39affca5271e28ebcd007341b0dee063",
    ),
    (
        "constraint:programme_programmecommandreceipt:programme_"
        "programmec_actor_id_12a81572_fk_identity_"
    ): (
        "6e9d582e41d464df5be1faa910947c762e6c4d4631217e0ea6e000bdf47f636c",
        "4ed87fd0d94daa63ad880b35b54252ad3f58c69aabfdc3065c99dda56093b807",
    ),
    (
        "constraint:programme_programmecommandreceipt:programme_"
        "programmec_control_id_02a3a2e7_fk_programme"
    ): (
        "6e9d582e41d464df5be1faa910947c762e6c4d4631217e0ea6e000bdf47f636c",
        "1c43be5fd4136fcf1d94b2c425c4b0a3b53bf4faaf61a0ae2cd418834ed77cf0",
    ),
    (
        "constraint:programme_programmecommandreceipt:programme_"
        "programmec_edition_id_2ae19f67_fk_events_ev"
    ): (
        "6e9d582e41d464df5be1faa910947c762e6c4d4631217e0ea6e000bdf47f636c",
        "03a7996ab8afb527585471eb2cbfd7058942319058cc05e3f26732b9ade4e0cc",
    ),
    (
        "constraint:programme_programmecommandreceipt:programme_"
        "programmec_item_id_6d8b054d_fk_programme"
    ): (
        "6e9d582e41d464df5be1faa910947c762e6c4d4631217e0ea6e000bdf47f636c",
        "29bc9e574fb186040bcedd470867b5969bfc9cfe526c4fac8fc4a66bc20d7c84",
    ),
    (
        "constraint:programme_programmecommandreceipt:programme_"
        "programmec_organization_id_30289ff1_fk_organizat"
    ): (
        "6e9d582e41d464df5be1faa910947c762e6c4d4631217e0ea6e000bdf47f636c",
        "07f454abd16b9f770cd0320efd71f154b0187daf9dbe65e3e6e57121eacd062f",
    ),
    (
        "constraint:programme_programmecommandreceipt:programme_"
        "programmecommandrecei_resulting_control_version_check"
    ): (
        "69d64ca9ff30b925a62e5ceda594c1aba7aebf94d273e697efce3721c42b6513",
        "6acdf2feedcc7bd854fd64e9d221dc258d0b6bb4bf76bff0c0043f625df04cdc",
    ),
    (
        "constraint:programme_programmecommandreceipt:programme_"
        "programmecommandreceipt_expected_version_check"
    ): (
        "69d64ca9ff30b925a62e5ceda594c1aba7aebf94d273e697efce3721c42b6513",
        "719afd7822a46e0475088570d7018db912ae2fc1cfc04ce8313fe2aadf5f8176",
    ),
    (
        "constraint:programme_programmecommandreceipt:programme_"
        "programmecommandreceipt_pkey"
    ): (
        "fa9e3173791563f5629a741700a25a4ac6d013df69ddf8f5d96d4e927460085a",
        "8c8464f42472e42ee190fc91ca8db79b5351d3a4609040516578d229c56f6fa5",
    ),
    (
        "constraint:programme_programmecommandreceipt:programme_"
        "programmecommandreceipt_resulting_item_version_check"
    ): (
        "69d64ca9ff30b925a62e5ceda594c1aba7aebf94d273e697efce3721c42b6513",
        "6865ac06c4283f839dce5c87a0fd831440aa4f514d6d59184ea46b8e61995180",
    ),
    (
        "constraint:programme_programmecommandreceipt:programme_receipt_"
        "control_evidence_guard"
    ): (
        "10b2a0b352900ef0fca94ea78e2276c8609a569a7ca425b31f6823ff65c3c2c1",
        "698fc09045e7267eeb19c5b09473ec8c40f237145be8c1cbd97b9dde2451ddc1",
    ),
    (
        "constraint:programme_programmecommandreceipt:programme_receipt_"
        "dependency_cursor_guard"
    ): (
        "10b2a0b352900ef0fca94ea78e2276c8609a569a7ca425b31f6823ff65c3c2c1",
        "698fc09045e7267eeb19c5b09473ec8c40f237145be8c1cbd97b9dde2451ddc1",
    ),
    (
        "constraint:programme_programmecommandreceipt:programme_receipt_"
        "item_evidence_guard"
    ): (
        "10b2a0b352900ef0fca94ea78e2276c8609a569a7ca425b31f6823ff65c3c2c1",
        "698fc09045e7267eeb19c5b09473ec8c40f237145be8c1cbd97b9dde2451ddc1",
    ),
    (
        "constraint:programme_programmedeliveryrevision:programme_"
        "delivery_command_evidence_guard"
    ): (
        "b9f51869f5828c4538635b0f1d4cbd2f8cf4f499c0fccf71c12bec642c825413",
        "698fc09045e7267eeb19c5b09473ec8c40f237145be8c1cbd97b9dde2451ddc1",
    ),
    (
        "constraint:programme_programmedeliveryrevision:programme_"
        "delivery_evidence_required"
    ): (
        "52808d2c9b2e6c87e015f5d50d2c2c48dbeafaa066875e49cbb5d59567f028aa",
        "cb9072c9acac8fd9f113633561aa7b71e036d45b5d67a222d03cc5192d20dd0a",
    ),
    (
        "constraint:programme_programmedeliveryrevision:programme_"
        "delivery_item_version_uq"
    ): (
        "a0a4c030ded27cc15d709644a2403ed14f8fd54633f16cead748a19edbe3ba54",
        "faa9207274210b222038d4ac808df78daf495224b312fa56e73524f428e2a68d",
    ),
    "constraint:programme_programmedeliveryrevision:programme_delivery_sequence_uq": (
        "a0a4c030ded27cc15d709644a2403ed14f8fd54633f16cead748a19edbe3ba54",
        "df78fffecbf6b3d7d406200f1ed8da34f0e7e2fa318a3abf144de10e4a56a1b8",
    ),
    "constraint:programme_programmedeliveryrevision:programme_delivery_versions_pos": (
        "52808d2c9b2e6c87e015f5d50d2c2c48dbeafaa066875e49cbb5d59567f028aa",
        "7b68a2cc798f515ab3ff18082a21541d2808b3d663f330110aff302c755ea8cf",
    ),
    (
        "constraint:programme_programmedeliveryrevision:programme_"
        "programmed_actor_id_4ba2d418_fk_identity_"
    ): (
        "51481999587c4a39f251c6aac34697c5893ea3b89509b0ccb4be5f1898251fbe",
        "4ed87fd0d94daa63ad880b35b54252ad3f58c69aabfdc3065c99dda56093b807",
    ),
    (
        "constraint:programme_programmedeliveryrevision:programme_"
        "programmed_edition_id_83776863_fk_events_ev"
    ): (
        "51481999587c4a39f251c6aac34697c5893ea3b89509b0ccb4be5f1898251fbe",
        "03a7996ab8afb527585471eb2cbfd7058942319058cc05e3f26732b9ade4e0cc",
    ),
    (
        "constraint:programme_programmedeliveryrevision:programme_"
        "programmed_item_id_1c553bd1_fk_programme"
    ): (
        "51481999587c4a39f251c6aac34697c5893ea3b89509b0ccb4be5f1898251fbe",
        "29bc9e574fb186040bcedd470867b5969bfc9cfe526c4fac8fc4a66bc20d7c84",
    ),
    (
        "constraint:programme_programmedeliveryrevision:programme_"
        "programmed_organization_id_8f831315_fk_organizat"
    ): (
        "51481999587c4a39f251c6aac34697c5893ea3b89509b0ccb4be5f1898251fbe",
        "07f454abd16b9f770cd0320efd71f154b0187daf9dbe65e3e6e57121eacd062f",
    ),
    (
        "constraint:programme_programmedeliveryrevision:programme_"
        "programmedeliveryrevision_item_version_check"
    ): (
        "52808d2c9b2e6c87e015f5d50d2c2c48dbeafaa066875e49cbb5d59567f028aa",
        "7b6d65d5670d3436adcbd8cae1a19da73177498534211163b7ab24ccb9fc8a50",
    ),
    (
        "constraint:programme_programmedeliveryrevision:programme_"
        "programmedeliveryrevision_pkey"
    ): (
        "48881eabafc3b3dc7b6ae0e2f87cdaa2b961c4e459e6e474fd1411583659db69",
        "8c8464f42472e42ee190fc91ca8db79b5351d3a4609040516578d229c56f6fa5",
    ),
    (
        "constraint:programme_programmedeliveryrevision:programme_"
        "programmedeliveryrevision_sequence_check"
    ): (
        "52808d2c9b2e6c87e015f5d50d2c2c48dbeafaa066875e49cbb5d59567f028aa",
        "8f426ab72466a993c9c30383cb064c0d9e1286aed4585cb08cb0ccdec86be0aa",
    ),
    (
        "constraint:programme_programmedepartmentdiscussionentry:programm"
        "e_discussion_command_evidence_guard"
    ): (
        "3e44fddaa397e57d72d14664625f21566e8de7ed07b6bc7700ad455c946b71be",
        "698fc09045e7267eeb19c5b09473ec8c40f237145be8c1cbd97b9dde2451ddc1",
    ),
    (
        "constraint:programme_programmedepartmentdiscussionentry:programm"
        "e_discussion_evidence_required"
    ): (
        "9a25a13a142dcebbe5e8ca169843974f3653a7b1eb463c02406c94a8d61dbbaa",
        "c03b3b41ecd25a5fde7d52c7fb8b0239bb6371750eadbee6bec3a604486e61bd",
    ),
    (
        "constraint:programme_programmedepartmentdiscussionentry:programm"
        "e_discussion_item_version_uq"
    ): (
        "f874fca73dbe3febe5cd5cd40394f24476a6afd6b0e9ae77e33336504a26e668",
        "faa9207274210b222038d4ac808df78daf495224b312fa56e73524f428e2a68d",
    ),
    (
        "constraint:programme_programmedepartmentdiscussionentry:programm"
        "e_discussion_sequence_uq"
    ): (
        "f874fca73dbe3febe5cd5cd40394f24476a6afd6b0e9ae77e33336504a26e668",
        "df78fffecbf6b3d7d406200f1ed8da34f0e7e2fa318a3abf144de10e4a56a1b8",
    ),
    (
        "constraint:programme_programmedepartmentdiscussionentry:programm"
        "e_programmed_actor_id_18999228_fk_identity_"
    ): (
        "a3732a90c6130f9cd03aa7bca3fa0f054ba128a30319ac127ab954ef95ab0103",
        "4ed87fd0d94daa63ad880b35b54252ad3f58c69aabfdc3065c99dda56093b807",
    ),
    (
        "constraint:programme_programmedepartmentdiscussionentry:programm"
        "e_programmed_edition_id_e186d2a1_fk_events_ev"
    ): (
        "a3732a90c6130f9cd03aa7bca3fa0f054ba128a30319ac127ab954ef95ab0103",
        "03a7996ab8afb527585471eb2cbfd7058942319058cc05e3f26732b9ade4e0cc",
    ),
    (
        "constraint:programme_programmedepartmentdiscussionentry:programm"
        "e_programmed_item_id_3489d68f_fk_programme"
    ): (
        "a3732a90c6130f9cd03aa7bca3fa0f054ba128a30319ac127ab954ef95ab0103",
        "29bc9e574fb186040bcedd470867b5969bfc9cfe526c4fac8fc4a66bc20d7c84",
    ),
    (
        "constraint:programme_programmedepartmentdiscussionentry:programm"
        "e_programmed_organization_id_bd1cbf09_fk_organizat"
    ): (
        "a3732a90c6130f9cd03aa7bca3fa0f054ba128a30319ac127ab954ef95ab0103",
        "07f454abd16b9f770cd0320efd71f154b0187daf9dbe65e3e6e57121eacd062f",
    ),
    (
        "constraint:programme_programmedepartmentdiscussionentry:programm"
        "e_programmedepartmentdiscussionentry_item_version_check"
    ): (
        "9a25a13a142dcebbe5e8ca169843974f3653a7b1eb463c02406c94a8d61dbbaa",
        "7b6d65d5670d3436adcbd8cae1a19da73177498534211163b7ab24ccb9fc8a50",
    ),
    (
        "constraint:programme_programmedepartmentdiscussionentry:programm"
        "e_programmedepartmentdiscussionentry_pkey"
    ): (
        "62951ff59f38ddd8472f3430af0410e22f9a63c70f73a7cd77d83e3986794823",
        "8c8464f42472e42ee190fc91ca8db79b5351d3a4609040516578d229c56f6fa5",
    ),
    (
        "constraint:programme_programmedepartmentdiscussionentry:programm"
        "e_programmedepartmentdiscussionentry_sequence_check"
    ): (
        "9a25a13a142dcebbe5e8ca169843974f3653a7b1eb463c02406c94a8d61dbbaa",
        "8f426ab72466a993c9c30383cb064c0d9e1286aed4585cb08cb0ccdec86be0aa",
    ),
    "constraint:programme_programmeeditioncontrol:programme_control_evidence_guard": (
        "cba674dd9ae3f57481d1bf3527c850d63c2e3711a4c1c0bc081c4bfefdfe1f74",
        "698fc09045e7267eeb19c5b09473ec8c40f237145be8c1cbd97b9dde2451ddc1",
    ),
    "constraint:programme_programmeeditioncontrol:programme_control_version_pos": (
        "f7b159c29a6e049711fcb6925e4474220126ecde1ff6f14774c4edeb183796f4",
        "eff5a1c1622da30175eeef5347ec7f15d20253dc5970b72392c83e10f98c4c15",
    ),
    (
        "constraint:programme_programmeeditioncontrol:programme_"
        "programmee_edition_id_b2cf1e7b_fk_events_ev"
    ): (
        "18d85c63f012c02b2a00379db63fa25777c17038a6b25ad7a96956ebcd7312be",
        "03a7996ab8afb527585471eb2cbfd7058942319058cc05e3f26732b9ade4e0cc",
    ),
    (
        "constraint:programme_programmeeditioncontrol:programme_"
        "programmee_organization_id_9bd6d210_fk_organizat"
    ): (
        "18d85c63f012c02b2a00379db63fa25777c17038a6b25ad7a96956ebcd7312be",
        "07f454abd16b9f770cd0320efd71f154b0187daf9dbe65e3e6e57121eacd062f",
    ),
    (
        "constraint:programme_programmeeditioncontrol:programme_"
        "programmeeditioncontrol_aggregate_version_check"
    ): (
        "f7b159c29a6e049711fcb6925e4474220126ecde1ff6f14774c4edeb183796f4",
        "01921d33d4976ea1189950f22141254fc647c2067eefb1b63ea8595ce2a59f8c",
    ),
    (
        "constraint:programme_programmeeditioncontrol:programme_"
        "programmeeditioncontrol_edition_id_key"
    ): (
        "982d768e48726d44442ef1e727653fb00db3054b33b5b9b0ee9b530cad580180",
        "365145bdaccd3b9c004c0fd9b5dca343c7df4c1cecdf349afb443800f16ebb7a",
    ),
    (
        "constraint:programme_programmeeditioncontrol:programme_"
        "programmeeditioncontrol_pkey"
    ): (
        "a60ede4beda184380e2567f2a2862f1a4c2e5dd1da4ce5cbe62ae66681ce614e",
        "8c8464f42472e42ee190fc91ca8db79b5351d3a4609040516578d229c56f6fa5",
    ),
    "constraint:programme_programmeitem:programme_item_evidence_guard": (
        "bbf4b5d78de32a5afa6224d1fea8895c94b2909eede6b94d130b8c00f6fef2af",
        "698fc09045e7267eeb19c5b09473ec8c40f237145be8c1cbd97b9dde2451ddc1",
    ),
    "constraint:programme_programmeitem:programme_item_kind_closed": (
        "f6ff47b87e06c3dd5ff0b267ccc8a85dd03a866af86155869acc95e8e0f29f0c",
        "476823dda5bd4612e4bf0e1c0cad121e0c57e4b44b7e6df1ec37a8d3f8637c55",
    ),
    "constraint:programme_programmeitem:programme_item_lifecycle_closed": (
        "f6ff47b87e06c3dd5ff0b267ccc8a85dd03a866af86155869acc95e8e0f29f0c",
        "880b8febbfb7419537d3b00d8eb0bea81d6fe34ba51690d08b89d2aae092f1bc",
    ),
    "constraint:programme_programmeitem:programme_item_provenance_closed": (
        "f6ff47b87e06c3dd5ff0b267ccc8a85dd03a866af86155869acc95e8e0f29f0c",
        "b11b2cfc21673d234ba59c5cbe99b37f4584d05503fadb9edb6afdb8464f8931",
    ),
    "constraint:programme_programmeitem:programme_item_source_shape_guard": (
        "bbf4b5d78de32a5afa6224d1fea8895c94b2909eede6b94d130b8c00f6fef2af",
        "698fc09045e7267eeb19c5b09473ec8c40f237145be8c1cbd97b9dde2451ddc1",
    ),
    "constraint:programme_programmeitem:programme_item_version_pos": (
        "f6ff47b87e06c3dd5ff0b267ccc8a85dd03a866af86155869acc95e8e0f29f0c",
        "eff5a1c1622da30175eeef5347ec7f15d20253dc5970b72392c83e10f98c4c15",
    ),
    (
        "constraint:programme_programmeitem:programme_programmei_created_"
        "by_id_597cd50c_fk_identity_"
    ): (
        "9a2277b5f0462e5031de2a47b9be9415b3fc3bb2040ae6aadd8e8e167d21680f",
        "cbfe6216ddb24223d2da362df236323769cadcccfba9baa45d1fbd5a2b8a6d2d",
    ),
    (
        "constraint:programme_programmeitem:programme_programmei_edition_"
        "id_82b841c1_fk_events_ev"
    ): (
        "9a2277b5f0462e5031de2a47b9be9415b3fc3bb2040ae6aadd8e8e167d21680f",
        "03a7996ab8afb527585471eb2cbfd7058942319058cc05e3f26732b9ade4e0cc",
    ),
    (
        "constraint:programme_programmeitem:programme_programmei_last_"
        "modified_by_id_2ea0384b_fk_identity_"
    ): (
        "9a2277b5f0462e5031de2a47b9be9415b3fc3bb2040ae6aadd8e8e167d21680f",
        "2c0aff8c19e72bf6f121c9bed55c36858f7a7d671ccee0e376cd614e2dbf22ac",
    ),
    (
        "constraint:programme_programmeitem:programme_programmei_"
        "organization_id_bb9d3009_fk_organizat"
    ): (
        "9a2277b5f0462e5031de2a47b9be9415b3fc3bb2040ae6aadd8e8e167d21680f",
        "07f454abd16b9f770cd0320efd71f154b0187daf9dbe65e3e6e57121eacd062f",
    ),
    (
        "constraint:programme_programmeitem:programme_programmeitem_"
        "aggregate_version_check"
    ): (
        "f6ff47b87e06c3dd5ff0b267ccc8a85dd03a866af86155869acc95e8e0f29f0c",
        "01921d33d4976ea1189950f22141254fc647c2067eefb1b63ea8595ce2a59f8c",
    ),
    "constraint:programme_programmeitem:programme_programmeitem_pkey": (
        "5386988d956007b913ac8a9416a6808fccca89cd1b866da759b4bd8c108d4601",
        "8c8464f42472e42ee190fc91ca8db79b5351d3a4609040516578d229c56f6fa5",
    ),
    (
        "constraint:programme_programmeitemsourcebinding:programme_"
        "binding_source_shape_guard"
    ): (
        "4cf6eb580503bdabbe6d4d8feb818cc5104de32405ecb018225604ed977e365f",
        "698fc09045e7267eeb19c5b09473ec8c40f237145be8c1cbd97b9dde2451ddc1",
    ),
    "constraint:programme_programmeitemsourcebinding:programme_item_source_shape": (
        "53e118bbc4df672aaf0918695c018216470785307e54f108ff1b091c820a7e9e",
        "3aee272a8de2f56d20d6f055ae0066d68311318f1283dc48acb06d6bf6109fcc",
    ),
    (
        "constraint:programme_programmeitemsourcebinding:programme_"
        "programmei_edition_id_f64f7b7e_fk_events_ev"
    ): (
        "1d99d998543b658a76114c747712ad9947af6cb05134fa10ca882284c9b1c4c7",
        "03a7996ab8afb527585471eb2cbfd7058942319058cc05e3f26732b9ade4e0cc",
    ),
    (
        "constraint:programme_programmeitemsourcebinding:programme_"
        "programmei_item_id_2d17a8e3_fk_programme"
    ): (
        "1d99d998543b658a76114c747712ad9947af6cb05134fa10ca882284c9b1c4c7",
        "29bc9e574fb186040bcedd470867b5969bfc9cfe526c4fac8fc4a66bc20d7c84",
    ),
    (
        "constraint:programme_programmeitemsourcebinding:programme_"
        "programmei_organization_id_5b47ab3b_fk_organizat"
    ): (
        "1d99d998543b658a76114c747712ad9947af6cb05134fa10ca882284c9b1c4c7",
        "07f454abd16b9f770cd0320efd71f154b0187daf9dbe65e3e6e57121eacd062f",
    ),
    (
        "constraint:programme_programmeitemsourcebinding:programme_"
        "programmeitemsourcebinding_item_id_key"
    ): (
        "dd0aeaed8d3976c382d52cf9bce54b2d1867a17d62c734c73ad700cb009aecc8",
        "fc910f7b9bec695540b229befceb69dc0665e10551a89a8fff602455ead0f7b1",
    ),
    (
        "constraint:programme_programmeitemsourcebinding:programme_"
        "programmeitemsourcebinding_pkey"
    ): (
        "4ea3fbe981118c7761dcd0cb7241ef1311a112839cf9187d4d7538a05fa4f875",
        "8c8464f42472e42ee190fc91ca8db79b5351d3a4609040516578d229c56f6fa5",
    ),
    (
        "constraint:programme_programmeitemsourcebinding:programme_"
        "programmeitemsourcebinding_source_version_check"
    ): (
        "53e118bbc4df672aaf0918695c018216470785307e54f108ff1b091c820a7e9e",
        "850d11fe81a415626d36a4304a58e84063e1195c3397b1865030b2ce1b2a40c0",
    ),
    (
        "constraint:programme_programmepublicrendition:programme_"
        "programmep_edition_id_c1e38616_fk_events_ev"
    ): (
        "7f9c061eb87675bfa60a036201f2413c2f7c3bd74b28e2ce177dd23d70fd1c56",
        "03a7996ab8afb527585471eb2cbfd7058942319058cc05e3f26732b9ade4e0cc",
    ),
    (
        "constraint:programme_programmepublicrendition:programme_"
        "programmep_item_id_17c152b8_fk_programme"
    ): (
        "7f9c061eb87675bfa60a036201f2413c2f7c3bd74b28e2ce177dd23d70fd1c56",
        "29bc9e574fb186040bcedd470867b5969bfc9cfe526c4fac8fc4a66bc20d7c84",
    ),
    (
        "constraint:programme_programmepublicrendition:programme_"
        "programmep_organization_id_3b0eb36c_fk_organizat"
    ): (
        "7f9c061eb87675bfa60a036201f2413c2f7c3bd74b28e2ce177dd23d70fd1c56",
        "07f454abd16b9f770cd0320efd71f154b0187daf9dbe65e3e6e57121eacd062f",
    ),
    (
        "constraint:programme_programmepublicrendition:programme_"
        "programmep_reviewed_by_id_c8d4e78f_fk_identity_"
    ): (
        "7f9c061eb87675bfa60a036201f2413c2f7c3bd74b28e2ce177dd23d70fd1c56",
        "4e18df881adc29689dfab4c9425408e4c932e10304896a5bf94370f325ad6dee",
    ),
    (
        "constraint:programme_programmepublicrendition:programme_"
        "programmep_source_working_revis_08681379_fk_programme"
    ): (
        "7f9c061eb87675bfa60a036201f2413c2f7c3bd74b28e2ce177dd23d70fd1c56",
        "f13bb8af78280f38ec985790a23d58de515a906301b4e4a429f917da13656d64",
    ),
    (
        "constraint:programme_programmepublicrendition:programme_"
        "programmep_supersedes_id_a89dcb43_fk_programme"
    ): (
        "7f9c061eb87675bfa60a036201f2413c2f7c3bd74b28e2ce177dd23d70fd1c56",
        "c0c92296f6cbf38ef49de9d4fe8884784504e9cab53e5798bac64d85b6203b25",
    ),
    (
        "constraint:programme_programmepublicrendition:programme_"
        "programmepublicrendition_pkey"
    ): (
        "2903b9ced8dba593745a60d46bd2541d0f5d76e13cfd7e13d8faf1340a3cee36",
        "8c8464f42472e42ee190fc91ca8db79b5351d3a4609040516578d229c56f6fa5",
    ),
    (
        "constraint:programme_programmepublicrendition:programme_"
        "programmepublicrendition_rendition_number_check"
    ): (
        "56e225e4712ceb85a70fdbd282ddfe5dcf588e1c09f5cd064a3e2e157245d2f0",
        "7ffb5c79491c12813d047790c5eb4a28faf583d70fa4f86c1abd65568f42a4bf",
    ),
    (
        "constraint:programme_programmepublicrendition:programme_"
        "programmepublicrendition_source_item_version_check"
    ): (
        "56e225e4712ceb85a70fdbd282ddfe5dcf588e1c09f5cd064a3e2e157245d2f0",
        "d1b4d90158c0befebabd1526ac7317da8bf8b5dadf11f85ec87d871db1d3e857",
    ),
    (
        "constraint:programme_programmepublicrendition:programme_"
        "programmepublicrendition_supersedes_id_key"
    ): (
        "8d602ff4357b5eecaf274cf5a0c39cd7a6c7155422eab6655812c9f6dbc52d8d",
        "d76f92539a34cb984ee1d7f4a8164118e1470c08291be2efd4ecc0b026b3eba1",
    ),
    (
        "constraint:programme_programmepublicrendition:programme_public_"
        "rendition_command_evidence_guard"
    ): (
        "bf903e68f1c262dc857f7b7354dc74f19e55ecaef367d8ebb061cf59f21f0996",
        "698fc09045e7267eeb19c5b09473ec8c40f237145be8c1cbd97b9dde2451ddc1",
    ),
    (
        "constraint:programme_programmepublicrendition:programme_public_"
        "rendition_number_uq"
    ): (
        "8d602ff4357b5eecaf274cf5a0c39cd7a6c7155422eab6655812c9f6dbc52d8d",
        "790914df67062367d539c3afc98903ef6ab579f17ad7034cbaf0fffc6dd4264d",
    ),
    "constraint:programme_programmepublicrendition:programme_public_rendition_valid": (
        "56e225e4712ceb85a70fdbd282ddfe5dcf588e1c09f5cd064a3e2e157245d2f0",
        "e94f1b0803b05a950d73486502a2ee86673330d815ae188e97617463d6fd8db1",
    ),
    (
        "constraint:programme_programmereadinessevidence:programme_"
        "programmer_actor_id_a9395030_fk_identity_"
    ): (
        "e10906ef5b8cf2be45a20f7e3f7505bbdf5ecb5901d42334f696be6355afaf45",
        "4ed87fd0d94daa63ad880b35b54252ad3f58c69aabfdc3065c99dda56093b807",
    ),
    (
        "constraint:programme_programmereadinessevidence:programme_"
        "programmer_edition_id_d51d9ce3_fk_events_ev"
    ): (
        "e10906ef5b8cf2be45a20f7e3f7505bbdf5ecb5901d42334f696be6355afaf45",
        "03a7996ab8afb527585471eb2cbfd7058942319058cc05e3f26732b9ade4e0cc",
    ),
    (
        "constraint:programme_programmereadinessevidence:programme_"
        "programmer_item_id_7f3c0a9b_fk_programme"
    ): (
        "e10906ef5b8cf2be45a20f7e3f7505bbdf5ecb5901d42334f696be6355afaf45",
        "29bc9e574fb186040bcedd470867b5969bfc9cfe526c4fac8fc4a66bc20d7c84",
    ),
    (
        "constraint:programme_programmereadinessevidence:programme_"
        "programmer_organization_id_b69a753f_fk_organizat"
    ): (
        "e10906ef5b8cf2be45a20f7e3f7505bbdf5ecb5901d42334f696be6355afaf45",
        "07f454abd16b9f770cd0320efd71f154b0187daf9dbe65e3e6e57121eacd062f",
    ),
    (
        "constraint:programme_programmereadinessevidence:programme_"
        "programmer_requirement_id_36740c6f_fk_programme"
    ): (
        "e10906ef5b8cf2be45a20f7e3f7505bbdf5ecb5901d42334f696be6355afaf45",
        "125b80470de5e77df92898cfa55a0a11733e185c9a142c359e65c5fbbc3e4b41",
    ),
    (
        "constraint:programme_programmereadinessevidence:programme_"
        "programmereadinessevidence_dependency_version_check"
    ): (
        "28d7947cca76ba42359797d6fc106da8dd24982eb35c9ab7c04ac9b3c44e7548",
        "793ddb1fafd7b59721a080fe374e93fd749b3ba74faf34b94ba0720d2c337142",
    ),
    (
        "constraint:programme_programmereadinessevidence:programme_"
        "programmereadinessevidence_item_version_check"
    ): (
        "28d7947cca76ba42359797d6fc106da8dd24982eb35c9ab7c04ac9b3c44e7548",
        "7b6d65d5670d3436adcbd8cae1a19da73177498534211163b7ab24ccb9fc8a50",
    ),
    (
        "constraint:programme_programmereadinessevidence:programme_"
        "programmereadinessevidence_pkey"
    ): (
        "e595454c8896fe54fce5b174213a7138aabdf6d662150855e468919506def870",
        "8c8464f42472e42ee190fc91ca8db79b5351d3a4609040516578d229c56f6fa5",
    ),
    (
        "constraint:programme_programmereadinessevidence:programme_"
        "programmereadinessevidence_requirement_version_check"
    ): (
        "28d7947cca76ba42359797d6fc106da8dd24982eb35c9ab7c04ac9b3c44e7548",
        "a7091257cb67493df53b3a480c8b3fd9e7c1e8569fa84b35dabbe8ebfa720445",
    ),
    (
        "constraint:programme_programmereadinessevidence:programme_"
        "programmereadinessevidence_sequence_check"
    ): (
        "28d7947cca76ba42359797d6fc106da8dd24982eb35c9ab7c04ac9b3c44e7548",
        "8f426ab72466a993c9c30383cb064c0d9e1286aed4585cb08cb0ccdec86be0aa",
    ),
    (
        "constraint:programme_programmereadinessevidence:programme_"
        "programmereadinessevidence_source_version_check"
    ): (
        "28d7947cca76ba42359797d6fc106da8dd24982eb35c9ab7c04ac9b3c44e7548",
        "850d11fe81a415626d36a4304a58e84063e1195c3397b1865030b2ce1b2a40c0",
    ),
    (
        "constraint:programme_programmereadinessevidence:programme_"
        "readiness_evidence_command_evidence_guard"
    ): (
        "037b815256280a1ad33d68a3b96a335045a64e13693d121e0600050e9d66d81a",
        "698fc09045e7267eeb19c5b09473ec8c40f237145be8c1cbd97b9dde2451ddc1",
    ),
    (
        "constraint:programme_programmereadinessevidence:programme_"
        "readiness_evidence_sequence_uq"
    ): (
        "34e972cb24967f21911c9c033ad1480632fa452f661d9be3b2d43b5ce5664ee6",
        "f13cd5112aa855b20572eb148d50223b5c16c4b6b18967512e41c682f112175b",
    ),
    (
        "constraint:programme_programmereadinessevidence:programme_"
        "readiness_evidence_source_shape"
    ): (
        "28d7947cca76ba42359797d6fc106da8dd24982eb35c9ab7c04ac9b3c44e7548",
        "892ff3c4da2d81eeef156eb88f92cddc0064a6c8266adc59e8a4008d9638bc37",
    ),
    (
        "constraint:programme_programmereadinessevidence:programme_"
        "readiness_evidence_state_closed"
    ): (
        "28d7947cca76ba42359797d6fc106da8dd24982eb35c9ab7c04ac9b3c44e7548",
        "83710028766cb9d609a9cea207e4549d67ab9611d6f2bc440452f09be4d67b5a",
    ),
    (
        "constraint:programme_programmereadinessevidence:programme_"
        "readiness_evidence_versions_valid"
    ): (
        "28d7947cca76ba42359797d6fc106da8dd24982eb35c9ab7c04ac9b3c44e7548",
        "08c489f3a8b06301d896c93918c91ae56741e4a913cbb816d3dacd51e3e7c02a",
    ),
    (
        "constraint:programme_programmereadinessrequirement:programme_"
        "programmer_edition_id_46f041f6_fk_events_ev"
    ): (
        "97743762e975f920081eae8b858a118be8846afacbe9fb435cb390a7a9eded4c",
        "03a7996ab8afb527585471eb2cbfd7058942319058cc05e3f26732b9ade4e0cc",
    ),
    (
        "constraint:programme_programmereadinessrequirement:programme_"
        "programmer_item_id_094a483f_fk_programme"
    ): (
        "97743762e975f920081eae8b858a118be8846afacbe9fb435cb390a7a9eded4c",
        "29bc9e574fb186040bcedd470867b5969bfc9cfe526c4fac8fc4a66bc20d7c84",
    ),
    (
        "constraint:programme_programmereadinessrequirement:programme_"
        "programmer_last_modified_by_id_90aff63d_fk_identity_"
    ): (
        "97743762e975f920081eae8b858a118be8846afacbe9fb435cb390a7a9eded4c",
        "2c0aff8c19e72bf6f121c9bed55c36858f7a7d671ccee0e376cd614e2dbf22ac",
    ),
    (
        "constraint:programme_programmereadinessrequirement:programme_"
        "programmer_organization_id_f4793d64_fk_organizat"
    ): (
        "97743762e975f920081eae8b858a118be8846afacbe9fb435cb390a7a9eded4c",
        "07f454abd16b9f770cd0320efd71f154b0187daf9dbe65e3e6e57121eacd062f",
    ),
    (
        "constraint:programme_programmereadinessrequirement:programme_"
        "programmereadinessrequireme_requirement_version_check"
    ): (
        "29f3de401416214239623df998097fcbcd3ea45cb884d0d47d8e3f255f885942",
        "a7091257cb67493df53b3a480c8b3fd9e7c1e8569fa84b35dabbe8ebfa720445",
    ),
    (
        "constraint:programme_programmereadinessrequirement:programme_"
        "programmereadinessrequiremen_dependency_version_check"
    ): (
        "29f3de401416214239623df998097fcbcd3ea45cb884d0d47d8e3f255f885942",
        "793ddb1fafd7b59721a080fe374e93fd749b3ba74faf34b94ba0720d2c337142",
    ),
    (
        "constraint:programme_programmereadinessrequirement:programme_"
        "programmereadinessrequirement_item_version_check"
    ): (
        "29f3de401416214239623df998097fcbcd3ea45cb884d0d47d8e3f255f885942",
        "7b6d65d5670d3436adcbd8cae1a19da73177498534211163b7ab24ccb9fc8a50",
    ),
    (
        "constraint:programme_programmereadinessrequirement:programme_"
        "programmereadinessrequirement_pkey"
    ): (
        "2129622805113cfd7c4868af42cea8129f1c5a8633d04003e18103570caecb1b",
        "8c8464f42472e42ee190fc91ca8db79b5351d3a4609040516578d229c56f6fa5",
    ),
    (
        "constraint:programme_programmereadinessrequirement:programme_"
        "readiness_concern_closed"
    ): (
        "29f3de401416214239623df998097fcbcd3ea45cb884d0d47d8e3f255f885942",
        "5c8fbcebb2a01a483a01c94868a328a623f26822bf5ec5a5c2363ff73a557e5f",
    ),
    (
        "constraint:programme_programmereadinessrequirement:programme_"
        "readiness_concern_uq"
    ): (
        "196b24c85f6811fbadbd32e1446d9880cadfd1702e8272eb6fd8d63ab16b0a2f",
        "4452b5f490df95c8cbee26324ae445b014ca0b23fbddab4c2fc22c8487f0296c",
    ),
    (
        "constraint:programme_programmereadinessrequirement:programme_"
        "readiness_disposition_closed"
    ): (
        "29f3de401416214239623df998097fcbcd3ea45cb884d0d47d8e3f255f885942",
        "326de70e6b2483c3f690c1d85a003b8c84b44fcd924b7fc6851cbfba9c400000",
    ),
    (
        "constraint:programme_programmereadinessrequirement:programme_"
        "readiness_versions_valid"
    ): (
        "29f3de401416214239623df998097fcbcd3ea45cb884d0d47d8e3f255f885942",
        "c54e6fd47e28b901dff86f3d5616613e4cbe5cf8b0f9f51190967d348c7a6d0e",
    ),
    (
        "constraint:programme_programmereadinessrequirement:programme_"
        "requirement_dependency_cursor_guard"
    ): (
        "301b9f40ca0e5b9f6ed37e35fe2af83452a3bc7239f7709e3e9db27c217ba524",
        "698fc09045e7267eeb19c5b09473ec8c40f237145be8c1cbd97b9dde2451ddc1",
    ),
    (
        "constraint:programme_programmereadinessrequirement:programme_"
        "requirement_history_guard"
    ): (
        "301b9f40ca0e5b9f6ed37e35fe2af83452a3bc7239f7709e3e9db27c217ba524",
        "698fc09045e7267eeb19c5b09473ec8c40f237145be8c1cbd97b9dde2451ddc1",
    ),
    (
        "constraint:programme_programmereadinessrequirementrevision:progr"
        "amme_programmer_actor_id_5d17d91e_fk_identity_"
    ): (
        "6d88303f9798e452a3a90baffb10e483bad1c5f225d0ca58d21319fc24b2cad8",
        "4ed87fd0d94daa63ad880b35b54252ad3f58c69aabfdc3065c99dda56093b807",
    ),
    (
        "constraint:programme_programmereadinessrequirementrevision:progr"
        "amme_programmer_edition_id_cb8b46e0_fk_events_ev"
    ): (
        "6d88303f9798e452a3a90baffb10e483bad1c5f225d0ca58d21319fc24b2cad8",
        "03a7996ab8afb527585471eb2cbfd7058942319058cc05e3f26732b9ade4e0cc",
    ),
    (
        "constraint:programme_programmereadinessrequirementrevision:progr"
        "amme_programmer_item_id_79ba9cb4_fk_programme"
    ): (
        "6d88303f9798e452a3a90baffb10e483bad1c5f225d0ca58d21319fc24b2cad8",
        "29bc9e574fb186040bcedd470867b5969bfc9cfe526c4fac8fc4a66bc20d7c84",
    ),
    (
        "constraint:programme_programmereadinessrequirementrevision:progr"
        "amme_programmer_organization_id_c8603821_fk_organizat"
    ): (
        "6d88303f9798e452a3a90baffb10e483bad1c5f225d0ca58d21319fc24b2cad8",
        "07f454abd16b9f770cd0320efd71f154b0187daf9dbe65e3e6e57121eacd062f",
    ),
    (
        "constraint:programme_programmereadinessrequirementrevision:progr"
        "amme_programmer_requirement_id_5432cfe0_fk_programme"
    ): (
        "6d88303f9798e452a3a90baffb10e483bad1c5f225d0ca58d21319fc24b2cad8",
        "125b80470de5e77df92898cfa55a0a11733e185c9a142c359e65c5fbbc3e4b41",
    ),
    (
        "constraint:programme_programmereadinessrequirementrevision:progr"
        "amme_programmereadinessrequirementrevis_item_version_check"
    ): (
        "6165f760d1deb9a8ed06a4bdac48bcb48f3cfd7824809b7b7507716c47bebd73",
        "7b6d65d5670d3436adcbd8cae1a19da73177498534211163b7ab24ccb9fc8a50",
    ),
    (
        "constraint:programme_programmereadinessrequirementrevision:progr"
        "amme_programmereadinessrequirementrevision_pkey"
    ): (
        "0951c7519829572ba619c100c4a66e5a708bac34948de236cff662f77e8d5a4f",
        "8c8464f42472e42ee190fc91ca8db79b5351d3a4609040516578d229c56f6fa5",
    ),
    (
        "constraint:programme_programmereadinessrequirementrevision:progr"
        "amme_programmereadinessrequirementrevision_sequence_check"
    ): (
        "6165f760d1deb9a8ed06a4bdac48bcb48f3cfd7824809b7b7507716c47bebd73",
        "8f426ab72466a993c9c30383cb064c0d9e1286aed4585cb08cb0ccdec86be0aa",
    ),
    (
        "constraint:programme_programmereadinessrequirementrevision:progr"
        "amme_requirement_revision_closed"
    ): (
        "6165f760d1deb9a8ed06a4bdac48bcb48f3cfd7824809b7b7507716c47bebd73",
        "326de70e6b2483c3f690c1d85a003b8c84b44fcd924b7fc6851cbfba9c400000",
    ),
    (
        "constraint:programme_programmereadinessrequirementrevision:progr"
        "amme_requirement_revision_command_evidence_guard"
    ): (
        "f9dcc0d36184af1549b1e21c865ceca9e85ce2f55aea2c60751b9213974fe4a6",
        "698fc09045e7267eeb19c5b09473ec8c40f237145be8c1cbd97b9dde2451ddc1",
    ),
    (
        "constraint:programme_programmereadinessrequirementrevision:progr"
        "amme_requirement_revision_history_guard"
    ): (
        "f9dcc0d36184af1549b1e21c865ceca9e85ce2f55aea2c60751b9213974fe4a6",
        "698fc09045e7267eeb19c5b09473ec8c40f237145be8c1cbd97b9dde2451ddc1",
    ),
    (
        "constraint:programme_programmereadinessrequirementrevision:progr"
        "amme_requirement_revision_sequence_uq"
    ): (
        "582099a6f1e159afa9e3e204669dd6d95a6e6308e7ec288da9f037b578d2a82c",
        "f13cd5112aa855b20572eb148d50223b5c16c4b6b18967512e41c682f112175b",
    ),
    (
        "constraint:programme_programmereadinessrequirementrevision:progr"
        "amme_requirement_revision_valid"
    ): (
        "6165f760d1deb9a8ed06a4bdac48bcb48f3cfd7824809b7b7507716c47bebd73",
        "dd1c312d4aa5f0ef724a65e4d3613461264d784092e25f8f6c083a4d12302dee",
    ),
    (
        "constraint:programme_programmeworkingrevision:programme_"
        "programmew_actor_id_b1a96dd9_fk_identity_"
    ): (
        "a5715fc529e47594f170239689015d701f87e87aabc3c86e6e10bb8d4a2b2c43",
        "4ed87fd0d94daa63ad880b35b54252ad3f58c69aabfdc3065c99dda56093b807",
    ),
    (
        "constraint:programme_programmeworkingrevision:programme_"
        "programmew_edition_id_b552a0c2_fk_events_ev"
    ): (
        "a5715fc529e47594f170239689015d701f87e87aabc3c86e6e10bb8d4a2b2c43",
        "03a7996ab8afb527585471eb2cbfd7058942319058cc05e3f26732b9ade4e0cc",
    ),
    (
        "constraint:programme_programmeworkingrevision:programme_"
        "programmew_item_id_387db1b9_fk_programme"
    ): (
        "a5715fc529e47594f170239689015d701f87e87aabc3c86e6e10bb8d4a2b2c43",
        "29bc9e574fb186040bcedd470867b5969bfc9cfe526c4fac8fc4a66bc20d7c84",
    ),
    (
        "constraint:programme_programmeworkingrevision:programme_"
        "programmew_organization_id_b32d189d_fk_organizat"
    ): (
        "a5715fc529e47594f170239689015d701f87e87aabc3c86e6e10bb8d4a2b2c43",
        "07f454abd16b9f770cd0320efd71f154b0187daf9dbe65e3e6e57121eacd062f",
    ),
    (
        "constraint:programme_programmeworkingrevision:programme_"
        "programmeworkingrevision_item_version_check"
    ): (
        "b98ffd34df5d85c5ad14def33612ca4be01b5202c6362f1b0f7225ee1c0e639c",
        "7b6d65d5670d3436adcbd8cae1a19da73177498534211163b7ab24ccb9fc8a50",
    ),
    (
        "constraint:programme_programmeworkingrevision:programme_"
        "programmeworkingrevision_pkey"
    ): (
        "b0f7ebd64b8c610a3102d4f16cdf90e4f899b20ea0d04abab8718a6aef3fbeb8",
        "8c8464f42472e42ee190fc91ca8db79b5351d3a4609040516578d229c56f6fa5",
    ),
    (
        "constraint:programme_programmeworkingrevision:programme_"
        "programmeworkingrevision_sequence_check"
    ): (
        "b98ffd34df5d85c5ad14def33612ca4be01b5202c6362f1b0f7225ee1c0e639c",
        "8f426ab72466a993c9c30383cb064c0d9e1286aed4585cb08cb0ccdec86be0aa",
    ),
    (
        "constraint:programme_programmeworkingrevision:programme_working_"
        "command_evidence_guard"
    ): (
        "f2bf7be630d27571dff72efaa1370e2bcf95d24206156185a1ea7d4d1f4830a2",
        "698fc09045e7267eeb19c5b09473ec8c40f237145be8c1cbd97b9dde2451ddc1",
    ),
    (
        "constraint:programme_programmeworkingrevision:programme_working_"
        "evidence_required"
    ): (
        "b98ffd34df5d85c5ad14def33612ca4be01b5202c6362f1b0f7225ee1c0e639c",
        "1013a2a0ae6f75c845deb41f3e8656994624c30af71adb73b51d020c863efe1a",
    ),
    "constraint:programme_programmeworkingrevision:programme_working_item_version_uq": (
        "228d74eec8c2b9758f5d2ae5270fc412c667f2212c1418e4bf56bace4e6c7905",
        "faa9207274210b222038d4ac808df78daf495224b312fa56e73524f428e2a68d",
    ),
    "constraint:programme_programmeworkingrevision:programme_working_sequence_uq": (
        "228d74eec8c2b9758f5d2ae5270fc412c667f2212c1418e4bf56bace4e6c7905",
        "df78fffecbf6b3d7d406200f1ed8da34f0e7e2fa318a3abf144de10e4a56a1b8",
    ),
    "constraint:programme_programmeworkingrevision:programme_working_versions_pos": (
        "b98ffd34df5d85c5ad14def33612ca4be01b5202c6362f1b0f7225ee1c0e639c",
        "7b68a2cc798f515ab3ff18082a21541d2808b3d663f330110aff302c755ea8cf",
    ),
    "index:programme_programmecommandreceipt:programme_command_control_version_uq": (
        "f6cd0da22b210bce57f842c047259cd69149838bbd0dfcd86c48309902823b0e",
        "29347c7093ba17710147a72e1a0db44e944b0a8debd92ef2420cefc3bea3e339",
    ),
    "index:programme_programmecommandreceipt:programme_command_item_version_uq": (
        "f6cd0da22b210bce57f842c047259cd69149838bbd0dfcd86c48309902823b0e",
        "005e5455d05ed36799e001fdb9828ce13cd25d6921131d07317f9148b8a99f3f",
    ),
    "index:programme_programmecommandreceipt:programme_command_retry_uq": (
        "c808a3e796941af76de9d4dbc309b140526c1037d45c2e85fcfacd27653886e6",
        "6592ce8c30b23593149ad813077f63ad6c964136ef40692f8922585772b83418",
    ),
    (
        "index:programme_programmecommandreceipt:programme_"
        "programmecommandreceipt_actor_id_12a81572"
    ): (
        "e4a371653b3d20f5a2af497414dd9d4a6ceaf0df6ee60f5be3f9893fa692b593",
        "d0eca46bd7adb0922277ac9f21dd4285a1ee58c21f2584e247c970ddd2f64ce5",
    ),
    (
        "index:programme_programmecommandreceipt:programme_"
        "programmecommandreceipt_control_id_02a3a2e7"
    ): (
        "e4a371653b3d20f5a2af497414dd9d4a6ceaf0df6ee60f5be3f9893fa692b593",
        "8f181a2632ee15291ef08ffc1a3d361442663493f13f993d738bda60e509a4e7",
    ),
    (
        "index:programme_programmecommandreceipt:programme_"
        "programmecommandreceipt_edition_id_2ae19f67"
    ): (
        "e4a371653b3d20f5a2af497414dd9d4a6ceaf0df6ee60f5be3f9893fa692b593",
        "31f2a738fbfd6d3117a9b4313bc7bfe90735b19f418fd1adf6a351f3e5fcf8fc",
    ),
    (
        "index:programme_programmecommandreceipt:programme_"
        "programmecommandreceipt_item_id_6d8b054d"
    ): (
        "e4a371653b3d20f5a2af497414dd9d4a6ceaf0df6ee60f5be3f9893fa692b593",
        "c0f1e88a55910c512d864e5a72493f0bf7b15c9031a1007ba8284344680603b6",
    ),
    (
        "index:programme_programmecommandreceipt:programme_"
        "programmecommandreceipt_organization_id_30289ff1"
    ): (
        "e4a371653b3d20f5a2af497414dd9d4a6ceaf0df6ee60f5be3f9893fa692b593",
        "e643ef6497451184727aac9e74d14c7c6ff3e6c16964dd677fdc97b576b03a68",
    ),
    "index:programme_programmecommandreceipt:programme_programmecommandreceipt_pkey": (
        "d9d31b1bc2e5abdb7694722cdd33b78aa2c595e7ee3435bc3c53f23025f645a8",
        "c5a7b7efd808d71b829964d51568e595457e7ec30ea8fa596f6f42f06ee15a72",
    ),
    "index:programme_programmedeliveryrevision:programme_delivery_item_version_uq": (
        "e88c6f969844e570ce9290937900fe4907431b48825921c4796e54984d7c7fb2",
        "8c6dfd7c810e824cd48a9e6ada5e5b38c66edaa41e5ff296b55608d1ca1ddb3e",
    ),
    "index:programme_programmedeliveryrevision:programme_delivery_sequence_uq": (
        "e88c6f969844e570ce9290937900fe4907431b48825921c4796e54984d7c7fb2",
        "2c042a772437b852a2bd99eb197ac0a2c48407eba1f77193fc9c73245fd7914a",
    ),
    (
        "index:programme_programmedeliveryrevision:programme_"
        "programmedeliveryrevision_actor_id_4ba2d418"
    ): (
        "72f06c258b51373c6041e68c0c6a69cd0baa31bf70232588b284a40e49e08f33",
        "bd6ded134b2eaa11ecc5935007753da0818ff4462ff68785dd067458447da4cb",
    ),
    (
        "index:programme_programmedeliveryrevision:programme_"
        "programmedeliveryrevision_edition_id_83776863"
    ): (
        "72f06c258b51373c6041e68c0c6a69cd0baa31bf70232588b284a40e49e08f33",
        "1d181081c025cd3261a38ff868469631fff6d6f6be34018722e28ed9f977d3b0",
    ),
    (
        "index:programme_programmedeliveryrevision:programme_"
        "programmedeliveryrevision_item_id_1c553bd1"
    ): (
        "72f06c258b51373c6041e68c0c6a69cd0baa31bf70232588b284a40e49e08f33",
        "26acf71a79caccf9ecb0df4c4d21d901111747b647cb689779cbc684dbe89c4c",
    ),
    (
        "index:programme_programmedeliveryrevision:programme_"
        "programmedeliveryrevision_organization_id_8f831315"
    ): (
        "72f06c258b51373c6041e68c0c6a69cd0baa31bf70232588b284a40e49e08f33",
        "a979b946439deb623c0a75abce72a90502e759c3060d117c00dd36d5094eea61",
    ),
    (
        "index:programme_programmedeliveryrevision:programme_"
        "programmedeliveryrevision_pkey"
    ): (
        "fc10378cc508c24c2a10bd1155adfa372c9b742a6091ff6c35c649f277e9c1bf",
        "23a4e46f8a10de74d0c7ccd6e56f2e331489d4dfe3cc06b5faf2bdb672c32010",
    ),
    (
        "index:programme_programmedepartmentdiscussionentry:programme_"
        "discussion_item_version_uq"
    ): (
        "48e328c7fc54ef234e587b2617718fb45d0e3f5cd89cb6588cd8adfa003139f7",
        "a20e70957ca00018e1ea3dceb5c9c49a981de4e28238704d8dd552ac0d000bf6",
    ),
    (
        "index:programme_programmedepartmentdiscussionentry:programme_"
        "discussion_sequence_uq"
    ): (
        "48e328c7fc54ef234e587b2617718fb45d0e3f5cd89cb6588cd8adfa003139f7",
        "5baaafd4250844d7f5378b6f6a7b0a70dd3b43d5a2df61e61bcbacb2c3db600a",
    ),
    (
        "index:programme_programmedepartmentdiscussionentry:programme_"
        "programmedepartm_edition_id_e186d2a1"
    ): (
        "d5647669dad34f2cc989756167cc0ab69556fef13e9332fb62b45cde22bbcbac",
        "dd74ea191e8520c5472aecba09e2ce6f77cc38eb93e26900dce899294a214592",
    ),
    (
        "index:programme_programmedepartmentdiscussionentry:programme_"
        "programmedepartm_organization_id_bd1cbf09"
    ): (
        "d5647669dad34f2cc989756167cc0ab69556fef13e9332fb62b45cde22bbcbac",
        "075d09b9885aca876e9889cbd9690bf33112dd9bd78ba60f1ebdb66e95e48937",
    ),
    (
        "index:programme_programmedepartmentdiscussionentry:programme_"
        "programmedepartmentdiscussionentry_actor_id_18999228"
    ): (
        "d5647669dad34f2cc989756167cc0ab69556fef13e9332fb62b45cde22bbcbac",
        "b6307e453bd378090210271b5efcd729a556ad396a4da79f6c86ee8dbe38e6cb",
    ),
    (
        "index:programme_programmedepartmentdiscussionentry:programme_"
        "programmedepartmentdiscussionentry_item_id_3489d68f"
    ): (
        "d5647669dad34f2cc989756167cc0ab69556fef13e9332fb62b45cde22bbcbac",
        "fd54c5460600bc34a1d05137788fa72b1513439dc26861c4c94c8e86b2e511b9",
    ),
    (
        "index:programme_programmedepartmentdiscussionentry:programme_"
        "programmedepartmentdiscussionentry_pkey"
    ): (
        "238fdefa08b7c6e88c28c2144dd0b38aa158dab9e75fea8bae553a3d23a4df63",
        "b42c32fb8c4853f6fa8333e9e88b3a8d561f6702e572d42461b727c7a333c684",
    ),
    "index:programme_programmeeditioncontrol:programme_control_scope_idx": (
        "b1b4e17d308dfa9227993068781379b188d845285eaebfc03a4adba7c8b34e96",
        "fe1f91c32d5da506e236cc03bd1a7a4d0cc9920857deda4526146035f8b58349",
    ),
    (
        "index:programme_programmeeditioncontrol:programme_"
        "programmeeditioncontrol_edition_id_key"
    ): (
        "00d7f625f6c2a79d60e2060ad821fdfe8bc1019125bd7c9d1d47eb658621ccbf",
        "562636b76f9563f6f23a9b0984f31855cc6f39d01623eee0d7565a036febf784",
    ),
    (
        "index:programme_programmeeditioncontrol:programme_"
        "programmeeditioncontrol_organization_id_9bd6d210"
    ): (
        "a0bf05d43696479bbaf25da93e599b6509a432218db5594225f8615f4094cd98",
        "e9a5c2666074d90ffcea82a65e7896af1271c4887f14b44197d9e8c0bbef9857",
    ),
    "index:programme_programmeeditioncontrol:programme_programmeeditioncontrol_pkey": (
        "f31422c6c0ec5b37a5dc872d12c19f70b12908d4c47d7a769a996da8a18a80f8",
        "cf9876334fcf669729ad2b7a9229b6efbe429a0f5b29df7ae18cf72195256e68",
    ),
    "index:programme_programmeitem:programme_item_scope_idx": (
        "5bf0ff42c83b4cf63a09e2ec8c19dc09dca245550a85d593d82bb3fc9d5ef20a",
        "315e13b910b49594ff0eaae251af3d3233804a6df305b171d0a278dca87dcb8d",
    ),
    "index:programme_programmeitem:programme_programmeitem_created_by_id_597cd50c": (
        "292c0f02b1b1d24bb0004cd7a79056a5e04e08726f01223d56bc374e88ecf8ec",
        "9c83b25f0e7e3f93cefcdac69fc0f2640c7878633ea34b161d2aa4b6e73a319c",
    ),
    "index:programme_programmeitem:programme_programmeitem_edition_id_82b841c1": (
        "292c0f02b1b1d24bb0004cd7a79056a5e04e08726f01223d56bc374e88ecf8ec",
        "2737049bbe51b475d35bde63811b87e09082a1f8eaa8dbc3e4433df8a0a9c4d2",
    ),
    (
        "index:programme_programmeitem:programme_programmeitem_last_"
        "modified_by_id_2ea0384b"
    ): (
        "292c0f02b1b1d24bb0004cd7a79056a5e04e08726f01223d56bc374e88ecf8ec",
        "bbecb7cf7308e67e681db9088cc3fe77c134cf3d1cce676939422939fd822ec2",
    ),
    "index:programme_programmeitem:programme_programmeitem_organization_id_bb9d3009": (
        "292c0f02b1b1d24bb0004cd7a79056a5e04e08726f01223d56bc374e88ecf8ec",
        "95baef1e40ac1a4bd7f68c89a215b3ed59e7572bc1dd49b6a7f5e5c83186c325",
    ),
    "index:programme_programmeitem:programme_programmeitem_pkey": (
        "e1d0a27480999bb3e6716d214b0829c9014fd3f519f3b7c51e599b18deea562a",
        "96e49fd03daa8bd2a361e23cb3422d617a7bcacd1560a278b17c39e2d4247be8",
    ),
    "index:programme_programmeitemsourcebinding:programme_item_source_object_uq": (
        "431b5fcbf7ba85bb0f88819c40eca844b93dbd228d862887faa462d78eee6df4",
        "4865c46ed2622c4e2f743e47f3b198039fc08f4c49f2a07b1477245a3544e39b",
    ),
    (
        "index:programme_programmeitemsourcebinding:programme_"
        "programmeitemsourcebinding_edition_id_f64f7b7e"
    ): (
        "c118375dbfd58692d1c7d38c1152ef682aae2bbdc25b4cb661e03cf482140221",
        "cf9e4b1f24967a98537ee1bb68a54bc22802ac07ea34cd31f9b989d038753cc5",
    ),
    (
        "index:programme_programmeitemsourcebinding:programme_"
        "programmeitemsourcebinding_item_id_key"
    ): (
        "38626d5f6341da141d945e1be71c107170202442230517c79492ccbc96d39362",
        "9293bd03a78b337cd2920b2b6dda5ad84ecf41bc85523eb3d54330cafb71000b",
    ),
    (
        "index:programme_programmeitemsourcebinding:programme_"
        "programmeitemsourcebinding_organization_id_5b47ab3b"
    ): (
        "c118375dbfd58692d1c7d38c1152ef682aae2bbdc25b4cb661e03cf482140221",
        "22231b66efbca6401112c555eae0c9d6faa29f4161d88d37a94ab6be3466835a",
    ),
    (
        "index:programme_programmeitemsourcebinding:programme_"
        "programmeitemsourcebinding_pkey"
    ): (
        "30a1649be9efcfa463582d8e09573833c661c77586531ce7a33ff239147b661a",
        "9be952bdcfc5d3adfb76c9b519d5be60152f6db0fe8aeceaa68bd74277f0fc28",
    ),
    (
        "index:programme_programmepublicrendition:programme_"
        "programmepublicr_source_working_revision_id_08681379"
    ): (
        "2949ae947d4a776691aa7244180320954412b29e7ec3d93581909a9077c38df5",
        "0b7e7968c3273128bd2a6106e891ac778262848dcf9d8ecdb598befdce3c5aaf",
    ),
    (
        "index:programme_programmepublicrendition:programme_"
        "programmepublicrendition_edition_id_c1e38616"
    ): (
        "2949ae947d4a776691aa7244180320954412b29e7ec3d93581909a9077c38df5",
        "9badbb86cf06da28df73a3d231047e4fecadff710a51a315bd8277ea0b1f10fa",
    ),
    (
        "index:programme_programmepublicrendition:programme_"
        "programmepublicrendition_item_id_17c152b8"
    ): (
        "2949ae947d4a776691aa7244180320954412b29e7ec3d93581909a9077c38df5",
        "19b7a3abe1362b04a9a39d131f790fb179ad977deb7f9974b0701624995ac91a",
    ),
    (
        "index:programme_programmepublicrendition:programme_"
        "programmepublicrendition_organization_id_3b0eb36c"
    ): (
        "2949ae947d4a776691aa7244180320954412b29e7ec3d93581909a9077c38df5",
        "0e991fbfad8806622e7277e6bc842033c6338ae96280fd1db0e2b89be218efb5",
    ),
    (
        "index:programme_programmepublicrendition:programme_"
        "programmepublicrendition_pkey"
    ): (
        "9236a685b509fcd66c2c6a7593af7aac4a5c3cb79d52035d309d9f3f86d49de2",
        "faae0914def4a787c70153c4184199f3c907cf1e7ad4f46f70bdee43b125aa42",
    ),
    (
        "index:programme_programmepublicrendition:programme_"
        "programmepublicrendition_reviewed_by_id_c8d4e78f"
    ): (
        "2949ae947d4a776691aa7244180320954412b29e7ec3d93581909a9077c38df5",
        "71dc2a9c8863a08c9582be719f69ad605c1b4ddf38ffb5547edc2bf3bf1a71d5",
    ),
    (
        "index:programme_programmepublicrendition:programme_"
        "programmepublicrendition_supersedes_id_key"
    ): (
        "322e70f50af92a739c9aed3de7866209b90374754de37f12fed002250b5aeca5",
        "af2c950fdddd3289a4cce2f1c8114500352202a770e4bf04a00c0c865ebf504c",
    ),
    "index:programme_programmepublicrendition:programme_public_rendition_number_uq": (
        "929d584ffc906916e2885a5d7f4f2a981cd407a1c2d223dee4708776e71635a2",
        "8f7af5ac04ceb25fd3a843fd081d11a18be93d1a782af5527c04f82ea8ff7dcb",
    ),
    (
        "index:programme_programmereadinessevidence:programme_"
        "programmereadinessevidence_actor_id_a9395030"
    ): (
        "6110c5d725e7e3f73ce711a0dff5669f3ba01c1bcb73c1fc4c46ceaf75a0e313",
        "522e9579390ec4565f6dd68e13c735cf4555caf99c0d14738e2d59e59dc33b8e",
    ),
    (
        "index:programme_programmereadinessevidence:programme_"
        "programmereadinessevidence_edition_id_d51d9ce3"
    ): (
        "6110c5d725e7e3f73ce711a0dff5669f3ba01c1bcb73c1fc4c46ceaf75a0e313",
        "091a6c6f2674d01619d810ec138cb60d7b6c706c8e057c1583fa48d4b2922b01",
    ),
    (
        "index:programme_programmereadinessevidence:programme_"
        "programmereadinessevidence_item_id_7f3c0a9b"
    ): (
        "6110c5d725e7e3f73ce711a0dff5669f3ba01c1bcb73c1fc4c46ceaf75a0e313",
        "4ad702e60ea82cf06147f0c98bec66b66f8041f8bc5218318bfbcb709f272623",
    ),
    (
        "index:programme_programmereadinessevidence:programme_"
        "programmereadinessevidence_organization_id_b69a753f"
    ): (
        "6110c5d725e7e3f73ce711a0dff5669f3ba01c1bcb73c1fc4c46ceaf75a0e313",
        "acee510c63fa644f7057169c584601f0d7331b77ac6042d80476b48dce872b6f",
    ),
    (
        "index:programme_programmereadinessevidence:programme_"
        "programmereadinessevidence_pkey"
    ): (
        "ae30a9a4365dc13cea85a071b45225c24eb167179a98d0e28d10855c915ccf05",
        "6b5f534539b61a51c420dd76208f9787cf1b243bbd26a97f4493cdab2ef5e876",
    ),
    (
        "index:programme_programmereadinessevidence:programme_"
        "programmereadinessevidence_requirement_id_36740c6f"
    ): (
        "6110c5d725e7e3f73ce711a0dff5669f3ba01c1bcb73c1fc4c46ceaf75a0e313",
        "4760b1a88e1a691328adaafca598286a89679ac8c6c04878e3d55c71ab56ffcc",
    ),
    (
        "index:programme_programmereadinessevidence:programme_readiness_"
        "evidence_sequence_uq"
    ): (
        "be0820e9556e2837d4a963037532c6b574e68e90d49b5659992068461a2da2a5",
        "62f1e7fa4e0832386cd0c52b3db6905d1fb92bcf9ec1db96a2d963d736356e85",
    ),
    (
        "index:programme_programmereadinessrequirement:programme_"
        "programmereadine_last_modified_by_id_90aff63d"
    ): (
        "fa6a88b68c3e8aceaa34132b20fbb99f881e29d9e306ec20b5e35df52c132ef9",
        "e15998fff7fce375343dac245623374403234c39234d393a61e2a3126e8af842",
    ),
    (
        "index:programme_programmereadinessrequirement:programme_"
        "programmereadine_organization_id_f4793d64"
    ): (
        "fa6a88b68c3e8aceaa34132b20fbb99f881e29d9e306ec20b5e35df52c132ef9",
        "c2e90e2ed7abce3b2a6c94f58d34f597f1312b32fa00d3625480a5c627564bf9",
    ),
    (
        "index:programme_programmereadinessrequirement:programme_"
        "programmereadinessrequirement_edition_id_46f041f6"
    ): (
        "fa6a88b68c3e8aceaa34132b20fbb99f881e29d9e306ec20b5e35df52c132ef9",
        "2e1e2f0a0f950415fa4b3cde82b2676f6efe7d9e03a52ae8fc797f08a47202ca",
    ),
    (
        "index:programme_programmereadinessrequirement:programme_"
        "programmereadinessrequirement_item_id_094a483f"
    ): (
        "fa6a88b68c3e8aceaa34132b20fbb99f881e29d9e306ec20b5e35df52c132ef9",
        "ac15bff785062e88dae095905d43e9ce7a91f9ca1ee94497da33b00434f070ea",
    ),
    (
        "index:programme_programmereadinessrequirement:programme_"
        "programmereadinessrequirement_pkey"
    ): (
        "3fef4855935bdab324b6d92741666166369fd7b13329869b011cbf23eff1b0ed",
        "a41176d2a4cf9ac171af02cb0a51423282035c5513c0c57137a2f9ab01754f3c",
    ),
    "index:programme_programmereadinessrequirement:programme_readiness_concern_uq": (
        "b4876f0838abe6556176dba3e3ef87ee857fca072066e382465ff2319d940f56",
        "d01dbc00ca6e22ab963cd6f03d99113ba39b5bf41d3bd5652e998ce51d864686",
    ),
    (
        "index:programme_programmereadinessrequirementrevision:programme_"
        "programmereadine_actor_id_5d17d91e"
    ): (
        "99af3c8dce5a9bbd8cef8cf7edd9405c4d873553d1753f7bb50f7208aa9e1074",
        "bc9c6d165c10f9bb7526f57a55d090d6c04b8220f0f1c9fb0203fb986c66d2d0",
    ),
    (
        "index:programme_programmereadinessrequirementrevision:programme_"
        "programmereadine_edition_id_cb8b46e0"
    ): (
        "99af3c8dce5a9bbd8cef8cf7edd9405c4d873553d1753f7bb50f7208aa9e1074",
        "098b8fd5027068de32325d170326900631757ea307c253363e5d65124b77c590",
    ),
    (
        "index:programme_programmereadinessrequirementrevision:programme_"
        "programmereadine_item_id_79ba9cb4"
    ): (
        "99af3c8dce5a9bbd8cef8cf7edd9405c4d873553d1753f7bb50f7208aa9e1074",
        "2ea0b088a751876653d2cfa821a85f42764f315b855124b8f9d3de21be8c7913",
    ),
    (
        "index:programme_programmereadinessrequirementrevision:programme_"
        "programmereadine_organization_id_c8603821"
    ): (
        "99af3c8dce5a9bbd8cef8cf7edd9405c4d873553d1753f7bb50f7208aa9e1074",
        "52d5d873c856ec8a9ad8b1ea96f6419d8ee0c35a97e95227cb989457cdd67a48",
    ),
    (
        "index:programme_programmereadinessrequirementrevision:programme_"
        "programmereadine_requirement_id_5432cfe0"
    ): (
        "99af3c8dce5a9bbd8cef8cf7edd9405c4d873553d1753f7bb50f7208aa9e1074",
        "817483ad3c35778fafb0ca0ff51507a847f487f4fdf9caa3d1d66100918e08b4",
    ),
    (
        "index:programme_programmereadinessrequirementrevision:programme_"
        "programmereadinessrequirementrevision_pkey"
    ): (
        "79a9de92167dc9b1a7d6844bb7c995de75f920d9da0756c9dacdcbff83347efe",
        "7038fe402330f0190624766ac08eec3a83b429281567fa216812734d914a62e3",
    ),
    (
        "index:programme_programmereadinessrequirementrevision:programme_"
        "requirement_revision_sequence_uq"
    ): (
        "f211fa28a63f253388c25f1a6c4fe6d076fcef030a732d7a0ad1a25783969b77",
        "93e70d61ccc934aecee0f5c90556f2259b5527078359a934656878098b629d6f",
    ),
    (
        "index:programme_programmeworkingrevision:programme_"
        "programmeworkingrevision_actor_id_b1a96dd9"
    ): (
        "9f5be2cfbe997f6513fb9681ce1b62ba8690151264d44a751f22e1e6a720eb9c",
        "6b5f0f46da4f78bef54928a801ab4ac308e962a6497a0811ce6d7d7d20ecf2d6",
    ),
    (
        "index:programme_programmeworkingrevision:programme_"
        "programmeworkingrevision_edition_id_b552a0c2"
    ): (
        "9f5be2cfbe997f6513fb9681ce1b62ba8690151264d44a751f22e1e6a720eb9c",
        "0bf13100dfb71c08c40b9cca38b65ff71cbd2b82c56a2b88d028a89b23c5e0af",
    ),
    (
        "index:programme_programmeworkingrevision:programme_"
        "programmeworkingrevision_item_id_387db1b9"
    ): (
        "9f5be2cfbe997f6513fb9681ce1b62ba8690151264d44a751f22e1e6a720eb9c",
        "dcf6aac7bd9c18a286ff7cc42c54311158d6eba865b207120d1fa82a78232363",
    ),
    (
        "index:programme_programmeworkingrevision:programme_"
        "programmeworkingrevision_organization_id_b32d189d"
    ): (
        "9f5be2cfbe997f6513fb9681ce1b62ba8690151264d44a751f22e1e6a720eb9c",
        "824c82dc979b3bb124138297f567eb916907134323ac0a66f9b061c82585f9fd",
    ),
    (
        "index:programme_programmeworkingrevision:programme_"
        "programmeworkingrevision_pkey"
    ): (
        "46784488c03a0bcd7fa1d3b35b7793f5f2d91660de80ab2802fc3363ac65810c",
        "bb42c7eb484bb0b559880e1552cd40ae5d6453c54ef8b3d2dc7334f169830ba6",
    ),
    "index:programme_programmeworkingrevision:programme_working_item_version_uq": (
        "063c535212f169b6a63c2a75bb4969ade9b47f28b8d7c5a9e054fe6ee943a38e",
        "8301bb912155b1e6c942d317c452f7de2f21e30e6755d334164cca5cc786d4ba",
    ),
    "index:programme_programmeworkingrevision:programme_working_sequence_uq": (
        "063c535212f169b6a63c2a75bb4969ade9b47f28b8d7c5a9e054fe6ee943a38e",
        "fd3badd68e5ecd7efc64dcde694b9e7d1e0913bcecbdb1d3e82580df8a01b1f2",
    ),
}

_REQUIRED_SCHEMA_OBJECT_KEYS: Final = frozenset(
    {
        ("constraint:programme_programmecommandreceipt:programme_command_retry_uq"),
        (
            "constraint:programme_programmeworkingrevision:"
            "programme_working_item_version_uq"
        ),
        "constraint:programme_programmeitem:programme_item_version_pos",
        ("index:programme_programmecommandreceipt:programme_command_item_version_uq"),
    }
)


def _programme_models() -> tuple[type[Model], ...]:
    return tuple(
        model
        for model in apps.get_app_config("programme").get_models()
        if model._meta.managed and not model._meta.proxy  # noqa: SLF001
    )


def _programme_relation_names() -> tuple[str, ...]:
    return tuple(sorted(model._meta.db_table for model in _programme_models()))  # noqa: SLF001


def _canonical_database_type(value: object) -> str:
    return " ".join(str(value).lower().split()).replace(
        "character varying",
        "varchar",
    )


def _expected_column_collation(
    database_type: str,
    explicit: str | None,
) -> tuple[object, ...]:
    base_type = database_type.partition("(")[0]
    if base_type not in {"char", "text", "varchar"}:
        return _NO_COLLATION_IDENTITY
    if explicit is not None:
        raise RuntimeError(
            "Programme column collation is not finalized in the schema catalog"
        )
    return _DEFAULT_COLLATION_IDENTITY


def _expected_programme_columns() -> set[tuple[object, ...]]:
    expected: set[tuple[object, ...]] = set()
    for model in _programme_models():
        for field in model._meta.local_fields:  # noqa: SLF001
            database_type = _canonical_database_type(field.db_type(connection))
            expected.add(
                (
                    model._meta.db_table,  # noqa: SLF001
                    field.column,
                    database_type,
                    not field.null,
                    field.db_default is not NOT_PROVIDED,
                    "",
                    "",
                    *_expected_column_collation(
                        database_type,
                        getattr(field, "db_collation", None),
                    ),
                )
            )
    return expected


def _nullable_text(value: object) -> str | None:
    return None if value is None else str(value)


def _metadata_sha256(metadata: tuple[object, ...]) -> str:
    canonical = json.dumps(
        metadata,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _schema_definition_rows(
    cursor: CursorWrapper,
    relations: tuple[str, ...],
) -> dict[str, tuple[str, str]]:
    rows: dict[str, tuple[str, str]] = {}
    cursor.execute(
        """
        SELECT relation.relname::text,
               constraint_record.conname::text,
               constraint_record.contype::text,
               constraint_record.condeferrable,
               constraint_record.condeferred,
               constraint_record.convalidated,
               constraint_record.confupdtype::text,
               constraint_record.confdeltype::text,
               constraint_record.confmatchtype::text,
               pg_catalog.encode(
                   pg_catalog.sha256(
                       pg_catalog.convert_to(
                           pg_catalog.pg_get_constraintdef(
                               constraint_record.oid,
                               TRUE
                           ),
                           'UTF8'
                       )
                   ),
                   'hex'
               )
          FROM pg_catalog.pg_constraint AS constraint_record
          JOIN pg_catalog.pg_class AS relation
            ON relation.oid = constraint_record.conrelid
          JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
         WHERE namespace.nspname = 'public'
           AND relation.relname = ANY(%s::text[])
         ORDER BY relation.relname, constraint_record.conname
        """,
        [list(relations)],
    )
    for row in cursor.fetchall():
        key = f"constraint:{row[0]}:{row[1]}"
        constraint_metadata = (
            str(row[0]),
            str(row[2]),
            bool(row[3]),
            bool(row[4]),
            bool(row[5]),
            str(row[6]),
            str(row[7]),
            str(row[8]),
        )
        rows[key] = (_metadata_sha256(constraint_metadata), str(row[9]))

    cursor.execute(
        """
        SELECT table_relation.relname::text,
               index_relation.relname::text,
               access_method.amname::text,
               index_record.indisunique,
               index_record.indisvalid,
               index_record.indisready,
               index_record.indislive,
               index_record.indisprimary,
               index_record.indisexclusion,
               index_record.indisclustered,
               index_record.indisreplident,
               index_record.indexprs IS NOT NULL,
               index_record.indpred IS NOT NULL,
               index_record.indnkeyatts,
               index_record.indnatts,
               pg_catalog.encode(
                   pg_catalog.sha256(
                       pg_catalog.convert_to(
                           pg_catalog.pg_get_indexdef(index_record.indexrelid),
                           'UTF8'
                       )
                   ),
                   'hex'
               )
          FROM pg_catalog.pg_index AS index_record
          JOIN pg_catalog.pg_class AS index_relation
            ON index_relation.oid = index_record.indexrelid
          JOIN pg_catalog.pg_namespace AS index_namespace
            ON index_namespace.oid = index_relation.relnamespace
          JOIN pg_catalog.pg_class AS table_relation
            ON table_relation.oid = index_record.indrelid
          JOIN pg_catalog.pg_namespace AS table_namespace
            ON table_namespace.oid = table_relation.relnamespace
          JOIN pg_catalog.pg_am AS access_method
            ON access_method.oid = index_relation.relam
         WHERE index_namespace.nspname = 'public'
           AND table_namespace.nspname = 'public'
           AND table_relation.relname = ANY(%s::text[])
         ORDER BY table_relation.relname, index_relation.relname
        """,
        [list(relations)],
    )
    for row in cursor.fetchall():
        key = f"index:{row[0]}:{row[1]}"
        index_metadata = (
            str(row[0]),
            str(row[2]),
            bool(row[3]),
            bool(row[4]),
            bool(row[5]),
            bool(row[6]),
            bool(row[7]),
            bool(row[8]),
            bool(row[9]),
            bool(row[10]),
            bool(row[11]),
            bool(row[12]),
            int(row[13]),
            int(row[14]),
        )
        rows[key] = (_metadata_sha256(index_metadata), str(row[15]))
    return rows


def collect_programme_schema_object_sha256() -> dict[str, tuple[str, str]]:
    """Return installed data-free fingerprints for migration finalization.

    Returns
    -------
    dict[str, tuple[str, str]]
        Complete constraint and index metadata/definition digests keyed by
        catalog kind, Programme relation, and object name.
    """
    with connection.cursor() as cursor:
        return _schema_definition_rows(
            cursor,
            tuple(sorted(PROGRAMME_RELATION_SEMANTICS)),
        )


def _schema_object_rows_are_current(
    rows: Mapping[str, tuple[str, str]],
    expected_rows: Mapping[str, tuple[str, str]],
    *,
    prefix: str,
) -> bool:
    installed = {key: value for key, value in rows.items() if key.startswith(prefix)}
    expected = {
        key: value for key, value in expected_rows.items() if key.startswith(prefix)
    }
    return bool(expected) and installed == expected


def inspect_programme_schema_catalog() -> ProgrammeSchemaCatalog:
    """Inspect exact relations, columns, and constraint/index definitions.

    Returns
    -------
    ProgrammeSchemaCatalog
        Data-free readiness evidence for every Programme-owned schema layer.
    """
    relations = tuple(sorted(PROGRAMME_RELATION_SEMANTICS))
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT relation.relname::text,
                   relation.relkind::text,
                   relation.relpersistence::text,
                   relation.relrowsecurity,
                   relation.relforcerowsecurity,
                   relation.relispartition,
                   relation.relreplident::text
              FROM pg_catalog.pg_class AS relation
              JOIN pg_catalog.pg_namespace AS namespace
                ON namespace.oid = relation.relnamespace
             WHERE namespace.nspname = 'public'
               AND relation.relname LIKE 'programme\\_%' ESCAPE '\\'
               AND relation.relkind IN ('r', 'p', 'f', 'v', 'm')
             ORDER BY relation.relname
            """
        )
        installed_relations = {
            str(row[0]): (
                str(row[1]),
                str(row[2]),
                bool(row[3]),
                bool(row[4]),
                bool(row[5]),
                str(row[6]),
            )
            for row in cursor.fetchall()
        }
        cursor.execute(
            """
            SELECT relation.relname::text,
                   attribute.attname::text,
                   pg_catalog.format_type(attribute.atttypid, attribute.atttypmod),
                   attribute.attnotnull,
                   attribute.atthasdef,
                   attribute.attidentity::text,
                   attribute.attgenerated::text,
                   collation_namespace.nspname::text,
                   collation_record.collname::text,
                   collation_record.collprovider::text,
                   collation_record.collisdeterministic,
                   collation_record.collencoding,
                   collation_record.collcollate,
                   collation_record.collctype,
                   collation_record.colllocale,
                   collation_record.collicurules,
                   collation_record.collversion
              FROM pg_catalog.pg_attribute AS attribute
              JOIN pg_catalog.pg_class AS relation
                ON relation.oid = attribute.attrelid
              JOIN pg_catalog.pg_namespace AS namespace
                ON namespace.oid = relation.relnamespace
              LEFT JOIN pg_catalog.pg_collation AS collation_record
                ON collation_record.oid = attribute.attcollation
              LEFT JOIN pg_catalog.pg_namespace AS collation_namespace
                ON collation_namespace.oid = collation_record.collnamespace
             WHERE namespace.nspname = 'public'
               AND relation.relname = ANY(%s::text[])
               AND attribute.attnum > 0
               AND NOT attribute.attisdropped
             ORDER BY relation.relname, attribute.attnum
            """,
            [list(relations)],
        )
        installed_columns = {
            (
                str(row[0]),
                str(row[1]),
                _canonical_database_type(row[2]),
                bool(row[3]),
                bool(row[4]),
                str(row[5]),
                str(row[6]),
                _nullable_text(row[7]),
                _nullable_text(row[8]),
                _nullable_text(row[9]),
                None if row[10] is None else bool(row[10]),
                None if row[11] is None else int(row[11]),
                _nullable_text(row[12]),
                _nullable_text(row[13]),
                _nullable_text(row[14]),
                _nullable_text(row[15]),
                _nullable_text(row[16]),
            )
            for row in cursor.fetchall()
        }
        schema_rows = _schema_definition_rows(cursor, relations)

    fingerprints_finalized = all(
        (
            _REQUIRED_SCHEMA_OBJECT_KEYS.issubset(PROGRAMME_SCHEMA_OBJECT_SHA256),
            any(
                key.startswith("constraint:") for key in PROGRAMME_SCHEMA_OBJECT_SHA256
            ),
            any(key.startswith("index:") for key in PROGRAMME_SCHEMA_OBJECT_SHA256),
        )
    )
    return ProgrammeSchemaCatalog(
        schema_fingerprints_finalized=fingerprints_finalized,
        relations_current=(
            _programme_relation_names() == relations
            and installed_relations == PROGRAMME_RELATION_SEMANTICS
        ),
        columns_current=installed_columns == _expected_programme_columns(),
        constraints_current=(
            fingerprints_finalized
            and _schema_object_rows_are_current(
                schema_rows,
                PROGRAMME_SCHEMA_OBJECT_SHA256,
                prefix="constraint:",
            )
        ),
        indexes_current=(
            fingerprints_finalized
            and _schema_object_rows_are_current(
                schema_rows,
                PROGRAMME_SCHEMA_OBJECT_SHA256,
                prefix="index:",
            )
        ),
    )


@dataclass(frozen=True, slots=True)
class ProgrammeReadinessProjection:
    """One concern's projected state and retained version explanation.

    Attributes
    ----------
    state
        The explainable current readiness state without a derived score.
    requirement_version
        The current positive version of the concern's requirement.
    dependency_version
        The current non-negative cursor for its dependent information layer.
    evidence_requirement_version
        The requirement version evaluated by the latest evidence, if present.
    evidence_dependency_version
        The dependency cursor evaluated by the latest evidence, if present.
    """

    state: ProgrammeReadinessProjectionState
    requirement_version: int
    dependency_version: int
    evidence_requirement_version: int | None
    evidence_dependency_version: int | None


def project_readiness_state(
    *,
    disposition: ProgrammeReadinessDisposition | str,
    requirement_version: int,
    dependency_version: int,
    evidence_state: ProgrammeReadinessEvidenceState | str | None,
    evidence_requirement_version: int | None,
    evidence_dependency_version: int | None,
) -> ProgrammeReadinessProjection:
    """Project one concern without hiding absent, stale, or blocked evidence.

    Parameters
    ----------
    disposition : ProgrammeReadinessDisposition | str
        Current applicability of the concern.
    requirement_version : int
        Current positive requirement revision.
    dependency_version : int
        Current non-negative revision of the dependent information layer.
    evidence_state : ProgrammeReadinessEvidenceState | str | None
        State on the latest retained evidence, when one exists.
    evidence_requirement_version : int | None
        Requirement version evaluated by the latest evidence.
    evidence_dependency_version : int | None
        Dependency version evaluated by the latest evidence.

    Returns
    -------
    ProgrammeReadinessProjection
        Explainable projected state with both current and evidence versions.

    Raises
    ------
    ValueError
        If the current or evidence version tuple is incomplete or invalid.
    """
    resolved_disposition = ProgrammeReadinessDisposition(disposition)
    resolved_evidence_state = (
        ProgrammeReadinessEvidenceState(evidence_state)
        if evidence_state is not None
        else None
    )
    if requirement_version <= 0 or dependency_version < 0:
        raise ValueError("Current readiness versions are invalid.")
    evidence_versions = (
        evidence_requirement_version,
        evidence_dependency_version,
    )
    if resolved_evidence_state is None and evidence_versions != (None, None):
        raise ValueError("Evidence versions require an evidence state.")
    if resolved_evidence_state is not None and (
        evidence_requirement_version is None
        or evidence_requirement_version <= 0
        or evidence_dependency_version is None
        or evidence_dependency_version < 0
    ):
        raise ValueError("Evidence state requires complete valid versions.")

    if resolved_disposition is ProgrammeReadinessDisposition.NOT_APPLICABLE:
        state = ProgrammeReadinessProjectionState.NOT_APPLICABLE
    elif resolved_evidence_state is None:
        state = ProgrammeReadinessProjectionState.REQUIRED
    elif (
        evidence_requirement_version != requirement_version
        or evidence_dependency_version != dependency_version
    ):
        state = ProgrammeReadinessProjectionState.STALE
    else:
        state = ProgrammeReadinessProjectionState(resolved_evidence_state.value)

    return ProgrammeReadinessProjection(
        state=state,
        requirement_version=requirement_version,
        dependency_version=dependency_version,
        evidence_requirement_version=evidence_requirement_version,
        evidence_dependency_version=evidence_dependency_version,
    )


def programme_database_integrity_is_ready() -> bool:
    """Return whether the exact dormant Programme database contract is ready.

    Returns
    -------
    bool
        Whether every Programme migration, relation shape, constraint, index,
        trigger, function, owner, and execute boundary matches the code-owned
        contract.
    """
    try:
        return all(
            (
                database_integrity_contract_is_ready(PROGRAMME_INTEGRITY_CONTRACT),
                inspect_programme_schema_catalog().ready,
            )
        )
    except (DatabaseError, LookupError, RuntimeError, TypeError, ValueError):
        return False


__all__ = [
    "PROGRAMME_INTEGRITY_CONTRACT",
    "ProgrammeReadinessProjection",
    "ProgrammeSchemaCatalog",
    "inspect_programme_schema_catalog",
    "programme_database_integrity_is_ready",
    "project_readiness_state",
]
