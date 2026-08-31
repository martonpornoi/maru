"""Explainable, score-free Programme readiness projection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from django.apps import apps
from django.db import DatabaseError, connection
from django.db.models.fields import NOT_PROVIDED

from maru.core.database_integrity_readiness import (
    DatabaseIntegrityContract,
    build_database_integrity_contract,
    database_integrity_contract_is_ready,
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

PROGRAMME_INTEGRITY_CONTRACT: Final[DatabaseIntegrityContract] = (
    build_database_integrity_contract(
        status_key="programme_integrity",
        app_label="programme",
        source_migration=("programme", "0002_integrity_guards"),
        terminal_migration=("programme", "0003_downgrade_fence"),
        source_migration_module="maru.programme.migrations.0002_integrity_guards",
    )
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
    "constraint:programme_programmecommandreceipt:programme_command_control_shape": (
        "69d64ca9ff30b925a62e5ceda594c1aba7aebf94d273e697efce3721c42b6513",
        "56e21ed63b76c17417bc159e81e09104f41840447b0502aaea23f550c82a7ad9",
    ),
    "constraint:programme_programmecommandreceipt:programme_command_evidence_valid": (
        "69d64ca9ff30b925a62e5ceda594c1aba7aebf94d273e697efce3721c42b6513",
        "22d0079f947cebccbb36873062591d3cf5747ba53a19cc3a0b4a14c0d4a88e00",
    ),
    "constraint:programme_programmecommandreceipt:programme_command_operation_closed": (
        "69d64ca9ff30b925a62e5ceda594c1aba7aebf94d273e697efce3721c42b6513",
        "d5c298fc780cd1fc8b6e8117f92bc7db1daf14b0db08dfa64a123fd2d39c816b",
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
        "6fc6db1a5eb0d470651e11af02d0419005e0e1b77d33416f6358e8cc7f44760b",
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
