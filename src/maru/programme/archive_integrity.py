"""Pin the dormant archive schema and guard sources to inspected native metadata."""

from typing import Final

from maru.core.database_integrity_readiness import (
    DatabaseIntegrityContract,
    extend_database_integrity_contract,
)

ARCHIVE_MIGRATION_SOURCES: Final = (
    (
        "maru.programme.migrations.0020_exit_archive_records",
        "c7377dd330d5ad3e0803c03bb8bc8fba3c6acbe4c5e22dbabbb73898a98304ef",
    ),
    (
        "maru.programme.migrations.0021_exit_archive_integrity",
        "35947539fc458e1836ad3e275980dcbe499165e9ad343c23c52da55d0e60430c",
    ),
)

# Collected from actual PostgreSQL 17.11 migration output, not inferred from models.
ARCHIVE_SCHEMA_OBJECT_SHA256: Final[dict[str, tuple[str, str]]] = {
    "constraint:programme_programmearchivechunk:programme_archive_chunk_evidence": (
        "c099f29e0a40e741803ff3ecb26c2c5d2944508b77e852fb6cf6df803348b0fc",
        "698fc09045e7267eeb19c5b09473ec8c40f237145be8c1cbd97b9dde2451ddc1",
    ),
    "constraint:programme_programmearchivechunk:programme_archive_chunk_seq": (
        "bb5bdaf9246cc8926150a804588612a8f3db8f7c4a80decc451974d481f36304",
        "e37d2cc8c61be69f9dad127e77fa2f3750c9f2f988f8dca766d2ff7b33c9c6b6",
    ),
    "constraint:programme_programmearchivechunk:programme_archive_chunk_size": (
        "bb5bdaf9246cc8926150a804588612a8f3db8f7c4a80decc451974d481f36304",
        "433ba0996e7a67f7dc2331df6239852f26da99b59ec79a51a469a1cad7501da6",
    ),
    "constraint:programme_programmearchivechunk:programme_archive_chunk_uq": (
        "0b068b99eeb36ec3e43e301b5bf40889f49fbd803de84cc95716ffc8e10b817b",
        "39c978c0cd3f5dd5ef521a035812a4fa06a778e0e9943325c4c8263469dfee22",
    ),
    (
        "constraint:programme_programmearchivechunk:"
        "programme_programmea_task_id_38e0f7eb_fk_programme"
    ): (
        "36231f1569e69284995b0e3d589f6b5e6236d2183fc37871bced71b80d707725",
        "5e0345e54e9868880e38538a0f49620e5badb9b0386504301ec88a39000eda5e",
    ),
    "constraint:programme_programmearchivechunk:programme_programmearchivechunk_pkey": (
        "bfd7fcbb9ccf76f58dbac719d27e3aa418abcacb65458915f364158f523b52e2",
        "8c8464f42472e42ee190fc91ca8db79b5351d3a4609040516578d229c56f6fa5",
    ),
    (
        "constraint:programme_programmearchivechunk:"
        "programme_programmearchivechunk_sequence_check"
    ): (
        "bb5bdaf9246cc8926150a804588612a8f3db8f7c4a80decc451974d481f36304",
        "8f426ab72466a993c9c30383cb064c0d9e1286aed4585cb08cb0ccdec86be0aa",
    ),
    (
        "constraint:programme_programmearchivechunk:"
        "programme_programmearchivechunk_size_bytes_check"
    ): (
        "bb5bdaf9246cc8926150a804588612a8f3db8f7c4a80decc451974d481f36304",
        "4a1fcb9b6bc2b4d0f32d4aeecba142e7f018d6609c9d63a17b8fe5ea048db74f",
    ),
    "constraint:programme_programmearchivetask:programme_archive_byte_limits": (
        "e15c51c8b1e7a03c4339c4b30f73340faccc78d15ca9035d3a96c8fe42d2cb1d",
        "66c6996d42c3584ec831f9ac3ddba9827804cefafee79f8b90a7c691d2fc650f",
    ),
    "constraint:programme_programmearchivetask:programme_archive_contract": (
        "e15c51c8b1e7a03c4339c4b30f73340faccc78d15ca9035d3a96c8fe42d2cb1d",
        "66a2440fb46fd69df0e5a3a4b1b53f12d06febf79c465699570690e342481808",
    ),
    "constraint:programme_programmearchivetask:programme_archive_request_uq": (
        "2a49f258834bdbfd9405e54398481d3b1ef96b09a441e9e8a811781502bbb180",
        "5cd63bb21f4d77de62f528de4443d2cb0a3cecb247bb654050281dbfd35db1be",
    ),
    "constraint:programme_programmearchivetask:programme_archive_state_closed": (
        "e15c51c8b1e7a03c4339c4b30f73340faccc78d15ca9035d3a96c8fe42d2cb1d",
        "171440b96b32c0003e9af3492f123000c96b5888599f80326cfe6ae739f2ca47",
    ),
    "constraint:programme_programmearchivetask:programme_archive_task_evidence": (
        "9b6cff1d5d2165e8acd92cabde8a9f8b228f13d1d7fdc864ff1cb0cfe7158a0e",
        "698fc09045e7267eeb19c5b09473ec8c40f237145be8c1cbd97b9dde2451ddc1",
    ),
    "constraint:programme_programmearchivetask:programme_archive_version_pos": (
        "e15c51c8b1e7a03c4339c4b30f73340faccc78d15ca9035d3a96c8fe42d2cb1d",
        "3d68fb756a2b833a7000f5c66086429afe13f7a681f92fa282e7fe289038a88c",
    ),
    (
        "constraint:programme_programmearchivetask:"
        "programme_programmea_actor_id_d34a5df6_fk_identity_"
    ): (
        "67c1f458dad34bb7b352b0fc7e99bae244d6e7dbc9f78d930f8aba479a7663cb",
        "4ed87fd0d94daa63ad880b35b54252ad3f58c69aabfdc3065c99dda56093b807",
    ),
    (
        "constraint:programme_programmearchivetask:"
        "programme_programmea_edition_id_c4e9bee6_fk_events_ev"
    ): (
        "67c1f458dad34bb7b352b0fc7e99bae244d6e7dbc9f78d930f8aba479a7663cb",
        "03a7996ab8afb527585471eb2cbfd7058942319058cc05e3f26732b9ade4e0cc",
    ),
    (
        "constraint:programme_programmearchivetask:"
        "programme_programmea_organization_id_1b53e94f_fk_organizat"
    ): (
        "67c1f458dad34bb7b352b0fc7e99bae244d6e7dbc9f78d930f8aba479a7663cb",
        "07f454abd16b9f770cd0320efd71f154b0187daf9dbe65e3e6e57121eacd062f",
    ),
    (
        "constraint:programme_programmearchivetask:"
        "programme_programmea_previous_task_id_3c06275e_fk_programme"
    ): (
        "67c1f458dad34bb7b352b0fc7e99bae244d6e7dbc9f78d930f8aba479a7663cb",
        "822284cced6b37a10c20a68a4e891a3023f99b1488c0399f30b94b475b9b6d91",
    ),
    (
        "constraint:programme_programmearchivetask:"
        "programme_programmearchivetask_artifact_bytes_check"
    ): (
        "e15c51c8b1e7a03c4339c4b30f73340faccc78d15ca9035d3a96c8fe42d2cb1d",
        "73b37ee7dee43254f7a6d193459b255d29bfc51d7171b7766766c1f081970db2",
    ),
    (
        "constraint:programme_programmearchivetask:"
        "programme_programmearchivetask_chunk_count_check"
    ): (
        "e15c51c8b1e7a03c4339c4b30f73340faccc78d15ca9035d3a96c8fe42d2cb1d",
        "e0bba0f5478bd7696fbf5f0e147f3728215a32c5204e304bf7085aeb0f694181",
    ),
    "constraint:programme_programmearchivetask:programme_programmearchivetask_pkey": (
        "d4ff0945cabe42ad3b491b3260cc71c12abf3328df410d0667c2e4b137451ce9",
        "8c8464f42472e42ee190fc91ca8db79b5351d3a4609040516578d229c56f6fa5",
    ),
    (
        "constraint:programme_programmearchivetask:"
        "programme_programmearchivetask_version_check"
    ): (
        "e15c51c8b1e7a03c4339c4b30f73340faccc78d15ca9035d3a96c8fe42d2cb1d",
        "ce468a9ec0ef7e34f6871d17c4cebc8cbb55944458fb50f5898e0a0cc9beb809",
    ),
    "constraint:programme_programmearchivetaskevent:programme_archive_event_pos": (
        "c32b9ac6edbe8d2ce66f58a00c70eac0f9dfb6c1ea4d25b8f389573eab455d16",
        "3d68fb756a2b833a7000f5c66086429afe13f7a681f92fa282e7fe289038a88c",
    ),
    "constraint:programme_programmearchivetaskevent:programme_archive_event_state": (
        "c32b9ac6edbe8d2ce66f58a00c70eac0f9dfb6c1ea4d25b8f389573eab455d16",
        "171440b96b32c0003e9af3492f123000c96b5888599f80326cfe6ae739f2ca47",
    ),
    "constraint:programme_programmearchivetaskevent:programme_archive_event_uq": (
        "bd2e77fc37bf91c946006fb2b41bfa028e7e7d0b8cba4fb5c428a9560202d6fe",
        "a8761452dda6e734f7c2c97865bf87363ff9000a0257c19ab833fc3e056ae17a",
    ),
    (
        "constraint:programme_programmearchivetaskevent:"
        "programme_programmea_audit_event_id_cad38c53_fk_audit_aud"
    ): (
        "0ef73d68dbdc23f3a88ae92197dcb09aa22a2234c89e7ab3c097da3d8c1742e1",
        "9f89328ab795cf8830b3f1d3f335b48c79932b7433e1d21ec8396b65298729fb",
    ),
    (
        "constraint:programme_programmearchivetaskevent:"
        "programme_programmea_task_id_cbe97bd3_fk_programme"
    ): (
        "0ef73d68dbdc23f3a88ae92197dcb09aa22a2234c89e7ab3c097da3d8c1742e1",
        "5e0345e54e9868880e38538a0f49620e5badb9b0386504301ec88a39000eda5e",
    ),
    (
        "constraint:programme_programmearchivetaskevent:"
        "programme_programmearchivetaskevent_audit_event_id_key"
    ): (
        "bd2e77fc37bf91c946006fb2b41bfa028e7e7d0b8cba4fb5c428a9560202d6fe",
        "a2bae6ed1ee31cc5a0079ceffb5ca452093c4a8e2c0d58d6fe85eafac5d18800",
    ),
    (
        "constraint:programme_programmearchivetaskevent:"
        "programme_programmearchivetaskevent_pkey"
    ): (
        "55d1539ebcaab1845a2cfce300c45747e7af3649478cac75ae00d2d05c48a093",
        "8c8464f42472e42ee190fc91ca8db79b5351d3a4609040516578d229c56f6fa5",
    ),
    (
        "constraint:programme_programmearchivetaskevent:"
        "programme_programmearchivetaskevent_version_check"
    ): (
        "c32b9ac6edbe8d2ce66f58a00c70eac0f9dfb6c1ea4d25b8f389573eab455d16",
        "ce468a9ec0ef7e34f6871d17c4cebc8cbb55944458fb50f5898e0a0cc9beb809",
    ),
    "index:programme_programmearchivechunk:programme_archive_chunk_uq": (
        "e729f99681cd00a3b3003038f68dfeffb2206c50ed050238879a7925adee19ba",
        "73eb06d21edfe3973e54cdf09cc78dbc8d65c32d79124f9bb78c8770089a6db1",
    ),
    "index:programme_programmearchivechunk:programme_programmearchivechunk_pkey": (
        "602539986aa9fc752434024ec459b9eb9db9ca800a4d5f8bc5e0d05c3f83cce1",
        "f9baa2b9f31d265a84ae8f7615a125aaf7e03630e7df2f499c0105cddc8744d2",
    ),
    (
        "index:programme_programmearchivechunk:"
        "programme_programmearchivechunk_task_id_38e0f7eb"
    ): (
        "389216b8d83c343f8d2544405d75a706331017565b100bfbfa686f325ba73294",
        "5f5fc16095ed9f43820a4f083bc93c5d3bab29aa4f79b89f5ee062306d5d209d",
    ),
    "index:programme_programmearchivetask:prg_archive_scope_idx": (
        "47b9a79d17188c68754a8a2f847c027a6d4ff1c759b7195b2a21c8748d5d237f",
        "0fe6036ea2f8f432cfeb5bfa0c06a062b014ff49b3d1855180b22bcc506fd4dc",
    ),
    "index:programme_programmearchivetask:prg_archive_worker_idx": (
        "dd905334f956111abf36619e0bf64fb2509e87fa984d1f25a3e302bbf10555ad",
        "1138e6240db07322e85b48cdd0bc90051d3f4c01997bb3864f847dfea5a8d492",
    ),
    "index:programme_programmearchivetask:programme_archive_request_uq": (
        "1fe3c4310becdbdf21b6d5c9fbb74f199c8b620f02cbcd4b79e063faef9a2941",
        "48811bbf54cc45ba7ed859bc3f5dfd33440f67a1db4dddeb4b28a4bd36c02266",
    ),
    (
        "index:programme_programmearchivetask:"
        "programme_programmearchivetask_actor_id_d34a5df6"
    ): (
        "4e3d2afb08b8fa2fd783e240ca6379e0617b1e8cb979f8f688faf91b53b49ed7",
        "9ccf934a442db948a1e03300c565a1cc1cec2eb0d5bef69939d1cc925ecfd68e",
    ),
    (
        "index:programme_programmearchivetask:"
        "programme_programmearchivetask_edition_id_c4e9bee6"
    ): (
        "4e3d2afb08b8fa2fd783e240ca6379e0617b1e8cb979f8f688faf91b53b49ed7",
        "ceeefb0d919ca94e7de76b343b8c806ee59b38a64ad8b6413bd0977ce565986c",
    ),
    (
        "index:programme_programmearchivetask:"
        "programme_programmearchivetask_organization_id_1b53e94f"
    ): (
        "4e3d2afb08b8fa2fd783e240ca6379e0617b1e8cb979f8f688faf91b53b49ed7",
        "7a4def4c3e7d3a604e4663efc0a37467c9e8c8afd3f007d44c4d1c2f90e4e9dc",
    ),
    "index:programme_programmearchivetask:programme_programmearchivetask_pkey": (
        "eb40b5b5b723f83376940f5d34ce2d80d269fa81f208efae794088cb0c03bd59",
        "ee9e876bdcf99f833b23329e653fc13661854fcba4b6a5e2fba3a6f676154f76",
    ),
    (
        "index:programme_programmearchivetask:"
        "programme_programmearchivetask_previous_task_id_3c06275e"
    ): (
        "4e3d2afb08b8fa2fd783e240ca6379e0617b1e8cb979f8f688faf91b53b49ed7",
        "af8b499baf2fa78e47b9ba8b37ab3f2b7bee0b30d9ccc2cce821ca92ebc7630c",
    ),
    "index:programme_programmearchivetaskevent:programme_archive_event_uq": (
        "bbf012c767d4fd68912d5245a680376b92b986771f2c44d2193ef4f6e812a3c0",
        "faea588ef9b47e06859421e6d6a5105026275095abdc70f93c44bf8241b8709d",
    ),
    (
        "index:programme_programmearchivetaskevent:"
        "programme_programmearchivetaskevent_audit_event_id_key"
    ): (
        "9e20596b23a69ed854ecd9313e072929c73a97e071d80e859f6dc3d352af92ed",
        "e30a559cd78d00e963f3fe2e45381727937ea7069eda8739ba90b5d2fd45dd0d",
    ),
    (
        "index:programme_programmearchivetaskevent:"
        "programme_programmearchivetaskevent_pkey"
    ): (
        "1bb4b76acc972fe3066921b39d9389de7f621cbc84a94da1d174c6e42cfaf794",
        "f0aca729bd3edcf70f4effafb865dc9c5c63378e4543417c0e0b4fa83373117f",
    ),
    (
        "index:programme_programmearchivetaskevent:"
        "programme_programmearchivetaskevent_task_id_cbe97bd3"
    ): (
        "80895bdca4ea8afc966a4d181a250acc0aa37776e95df13f113acd5d6042f013",
        "2fa53e10d6f9fec25d38dc456e32011bbd2c5f932bac0198bdb2494129fa81f7",
    ),
}


def with_archive_integrity(
    contract: DatabaseIntegrityContract,
) -> DatabaseIntegrityContract:
    """Extend existing Programme integrity with exact dormant archive custody.

    Parameters
    ----------
    contract : DatabaseIntegrityContract
        Complete existing Programme/native-release contract, never replaced.

    Returns
    -------
    DatabaseIntegrityContract
        All earlier invariants plus source-pinned archive schema/guards and fences.
    """
    for module, digest in ARCHIVE_MIGRATION_SOURCES:
        contract = extend_database_integrity_contract(
            contract,
            migration_module=module,
            source_sha256=digest,
        )
    return contract
