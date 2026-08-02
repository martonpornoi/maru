"""Pin organization runtime helpers to trusted objects.

The runtime login may execute these functions directly.  Their historical
bodies resolved relations (and one internal helper) through the caller's
``search_path``.  Rewrite only those code-owned identifiers, set a fixed
function-local path, and preserve each function's OID, owner, and ACL.
"""

from __future__ import annotations

import hashlib
import re
from typing import ClassVar

from django.db import migrations

_SAFE_SEARCH_PATH = ("search_path=pg_catalog, public, pg_temp",)


def _trigger_ddl(name: str) -> str:
    return f"""
        CREATE OR REPLACE FUNCTION public.{name}()
        RETURNS trigger
        LANGUAGE plpgsql
        VOLATILE
        CALLED ON NULL INPUT
        SECURITY INVOKER
        PARALLEL UNSAFE
        SET search_path = pg_catalog, public, pg_temp
        AS %s
    """


_FUNCTIONS = (
    {
        "identity": "public.maru_assert_active_board_membership_provenance(uuid)",
        "old_source_sha256": (
            "7b44a9bb47c148bf14168162ab631a6d2f065ad2e7f6c3903ccb1b77580cdea8"
        ),
        "new_source_sha256": (
            "9443b498d6f5b28e01d7d977f0b3fb12f61adf59cf811972a06409b8cf56fe6c"
        ),
        "identifiers": (
            ("organizations_organizationmembership", 2),
            ("organizations_organizationrepresentation", 1),
            ("organizations_representationappointment", 2),
        ),
        "ddl": """
            CREATE OR REPLACE FUNCTION
                public.maru_assert_active_board_membership_provenance(
                    target_representation_id uuid
                )
            RETURNS void
            LANGUAGE plpgsql
            VOLATILE
            CALLED ON NULL INPUT
            SECURITY INVOKER
            PARALLEL UNSAFE
            SET search_path = pg_catalog, public, pg_temp
            AS %s
        """,
    },
    {
        "identity": "public.maru_assert_active_executive_board(uuid)",
        "old_source_sha256": (
            "b80fb3d6422ba467a857135fa02616623085837ac6ae640ee937beccea32aed4"
        ),
        "new_source_sha256": (
            "d659418aa83b08677cb7e13044d7d9a85c64dd70a3db66feb2454f59b18289b1"
        ),
        "identifiers": (
            ("organizations_organizationmembership", 3),
            ("organizations_organizationrepresentation", 1),
            ("organizations_representationappointment", 10),
            ("organizations_organization", 1),
            ("authorization_roleassignment", 4),
            ("authorization_rolebundle", 2),
            ("identity_account", 4),
            ("audit_auditevent", 5),
            ("effects_domainevent", 2),
            ("effects_outboxmessage", 2),
            ("maru_assert_active_executive_board_v0009", 1),
        ),
        "ddl": """
            CREATE OR REPLACE FUNCTION
                public.maru_assert_active_executive_board(
                    target_representation_id uuid
                )
            RETURNS void
            LANGUAGE plpgsql
            VOLATILE
            CALLED ON NULL INPUT
            SECURITY INVOKER
            PARALLEL UNSAFE
            SET search_path = pg_catalog, public, pg_temp
            AS %s
        """,
    },
    {
        "identity": "public.maru_assert_active_executive_board_v0009(uuid)",
        "old_source_sha256": (
            "e977c59cb426857b9a93667d62bd0ac28ee5936818cd820c980751dcc3ff0a9c"
        ),
        "new_source_sha256": (
            "606f7a86e7a1dcbbdc076ef835860ead4dd51e369ba718868b4cde6117bcce27"
        ),
        "identifiers": (
            ("organizations_organizationmembership", 1),
            ("organizations_organizationrepresentation", 1),
            ("organizations_representationappointment", 7),
            ("organizations_organization", 1),
            ("authorization_roleassignment", 2),
            ("authorization_rolebundle", 2),
            ("identity_account", 2),
            ("audit_auditevent", 2),
            ("effects_domainevent", 1),
            ("effects_outboxmessage", 1),
        ),
        "ddl": """
            CREATE OR REPLACE FUNCTION
                public.maru_assert_active_executive_board_v0009(
                    target_representation_id uuid
                )
            RETURNS void
            LANGUAGE plpgsql
            VOLATILE
            CALLED ON NULL INPUT
            SECURITY INVOKER
            PARALLEL UNSAFE
            SET search_path = pg_catalog, public, pg_temp
            AS %s
        """,
    },
    {
        "identity": (
            "public.maru_deferred_validate_board_membership_from_representation()"
        ),
        "old_source_sha256": (
            "82a510863333d38deb18dd319771d3a980d038a0e18b6b4c168f61dc0d9a5b74"
        ),
        "new_source_sha256": (
            "17168c0a0ccb5f9c49160602667aa701c97615a96572b1fec1dbc4ca17c13314"
        ),
        "identifiers": (("maru_assert_active_board_membership_provenance", 2),),
        "ddl": _trigger_ddl(
            "maru_deferred_validate_board_membership_from_representation"
        ),
    },
    {
        "identity": "public.maru_deferred_validate_board_membership_from_appointment()",
        "old_source_sha256": (
            "8834cd245cd439a0d0aa6b0e08819df810400eaa50d71cf0a7d800e52f4a67a5"
        ),
        "new_source_sha256": (
            "445fbe9a8f79e88e9c46ef6418c70cdf7f871b4acd3eafbf3b1f7070b2e2fe7e"
        ),
        "identifiers": (("maru_assert_active_board_membership_provenance", 3),),
        "ddl": _trigger_ddl("maru_deferred_validate_board_membership_from_appointment"),
    },
    {
        "identity": "public.maru_deferred_validate_board_membership()",
        "old_source_sha256": (
            "145b54e9cfd34b56acd6124cbc4f754853b6cf79d12cc20a5be3be211cc641d0"
        ),
        "new_source_sha256": (
            "97ab40c8568f96b4fa7a975678deb32f42766bf12e6f9619796ef3babecb97b8"
        ),
        "identifiers": (
            ("organizations_organizationrepresentation", 2),
            ("maru_assert_active_board_membership_provenance", 2),
        ),
        "ddl": _trigger_ddl("maru_deferred_validate_board_membership"),
    },
    {
        "identity": "public.maru_deferred_validate_representation()",
        "old_source_sha256": (
            "9dabe743abbcbcdc2342525c5bfd0c9f56edd663bc233970bef938dffe03369d"
        ),
        "new_source_sha256": (
            "8d4953827ee58c3573d6297f5ed76c6e3b08010fc2f12fefd4201d8bb54f40e1"
        ),
        "identifiers": (("maru_assert_active_executive_board", 2),),
        "ddl": _trigger_ddl("maru_deferred_validate_representation"),
    },
    {
        "identity": "public.maru_deferred_validate_appointment()",
        "old_source_sha256": (
            "a0902e91e9d52f2851885fcbd7a00b0ac7774db7987b1e2a3c5bcffaff726ad2"
        ),
        "new_source_sha256": (
            "13e8a9e1fd10d902a60a0d55709840d9be70617d8628df80493398e405dc0a46"
        ),
        "identifiers": (("maru_assert_active_executive_board", 3),),
        "ddl": _trigger_ddl("maru_deferred_validate_appointment"),
    },
    {
        "identity": "public.maru_deferred_validate_role_assignment()",
        "old_source_sha256": (
            "516579307544051887951905f194e59234228f5f570256968465b10766a87bb3"
        ),
        "new_source_sha256": (
            "ef5aacf3c41bfca4947abf76cb4ec357bac8b0b665c8985d382a8a570c953bb4"
        ),
        "identifiers": (
            ("authorization_rolebundle", 1),
            ("organizations_organizationrepresentation", 1),
            ("organizations_representationappointment", 1),
            ("maru_assert_active_executive_board", 2),
        ),
        "ddl": _trigger_ddl("maru_deferred_validate_role_assignment"),
    },
    {
        "identity": "public.maru_deferred_validate_role_bundle()",
        "old_source_sha256": (
            "865adf680b71c476a4645a374a16b27dc221c6b2d92660dd1a0933219d687361"
        ),
        "new_source_sha256": (
            "33fc31b40d5b80595a7206fc50b094cec86b80129c241830f6b3102ae7dd082a"
        ),
        "identifiers": (
            ("organizations_organizationrepresentation", 1),
            ("maru_assert_active_executive_board", 1),
        ),
        "ddl": _trigger_ddl("maru_deferred_validate_role_bundle"),
    },
    {
        "identity": "public.maru_deferred_validate_membership()",
        "old_source_sha256": (
            "c8c2aceb7b9465177fe07f9446b004fcddb69914d53296402621a7c5a3c8eb77"
        ),
        "new_source_sha256": (
            "9c0fa765b0d3be88937b404bda1f82cbe743b7c692eee249da406f2f72011903"
        ),
        "identifiers": (
            ("organizations_organizationrepresentation", 1),
            ("organizations_representationappointment", 1),
            ("maru_assert_active_executive_board", 1),
        ),
        "ddl": _trigger_ddl("maru_deferred_validate_membership"),
    },
    {
        "identity": "public.maru_deferred_validate_board_account()",
        "old_source_sha256": (
            "a777adb431723806e3ae0eb2ef61f45fb6cf33d543c43c3b472774f884e74c43"
        ),
        "new_source_sha256": (
            "32ba3484c85ffff6fa82656e6a91995736920d53d351a4ae39a2469bf4828c41"
        ),
        "identifiers": (
            ("identity_account", 1),
            ("organizations_organizationrepresentation", 2),
            ("organizations_representationappointment", 2),
            ("maru_assert_active_executive_board", 1),
        ),
        "ddl": _trigger_ddl("maru_deferred_validate_board_account"),
    },
    {
        "identity": "public.maru_deferred_validate_board_organization()",
        "old_source_sha256": (
            "d50321cdd27a23672add18c594abf8470d38ec24601dc471cc3b2afeb8789793"
        ),
        "new_source_sha256": (
            "568a800702395541474fc56731895201be1803893e6f5a749deb6965190c3401"
        ),
        "identifiers": (
            ("organizations_organizationrepresentation", 1),
            ("maru_assert_active_executive_board", 1),
        ),
        "ddl": _trigger_ddl("maru_deferred_validate_board_organization"),
    },
)


def _source_sha256(source: str) -> str:
    return hashlib.sha256(source.encode()).hexdigest()


def _rewrite_source(
    source: str,
    identifiers: tuple[tuple[str, int], ...],
    *,
    qualify: bool,
) -> str:
    rewritten = source
    for identifier, expected_count in identifiers:
        source_name = identifier if qualify else f"public.{identifier}"
        target_name = f"public.{identifier}" if qualify else identifier
        pattern = re.compile(
            rf"(?<![A-Za-z0-9_.]){re.escape(source_name)}(?![A-Za-z0-9_])"
        )
        matches = pattern.findall(rewritten)
        if len(matches) != expected_count:
            direction = "upgrade" if qualify else "downgrade"
            raise RuntimeError(
                f"Refusing organization runtime function {direction}: "
                f"{source_name} occurred {len(matches)} times, expected "
                f"{expected_count}."
            )
        rewritten = pattern.sub(target_name, rewritten)
    return rewritten


def _function_state(  # type: ignore[no-untyped-def]
    cursor,
    identity: str,
) -> tuple[object, str, tuple[str, ...], object, object]:
    cursor.execute(
        """
        SELECT procedure.oid,
               procedure.prosrc,
               procedure.proconfig,
               procedure.proowner,
               procedure.proacl
          FROM pg_catalog.pg_proc AS procedure
          JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = procedure.pronamespace
         WHERE procedure.oid = pg_catalog.to_regprocedure(%s)
           AND namespace.nspname = 'public'
        """,
        [identity],
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError(f"Required runtime function {identity} is missing.")
    return (row[0], str(row[1]), tuple(row[2] or ()), row[3], row[4])


def _rewrite_functions(schema_editor, *, qualify: bool) -> None:  # type: ignore[no-untyped-def]
    with schema_editor.connection.cursor() as cursor:
        for contract in _FUNCTIONS:
            before = _function_state(cursor, contract["identity"])
            expected_hash = (
                contract["old_source_sha256"]
                if qualify
                else contract["new_source_sha256"]
            )
            expected_config = () if qualify else _SAFE_SEARCH_PATH
            if _source_sha256(before[1]) != expected_hash:
                raise RuntimeError(
                    "Refusing to rewrite an unrecognized organization runtime "
                    f"function: {contract['identity']}."
                )
            if before[2] != expected_config:
                raise RuntimeError(
                    "Refusing to rewrite an organization runtime function with "
                    f"unexpected configuration: {contract['identity']}."
                )

            rewritten = _rewrite_source(
                before[1],
                contract["identifiers"],
                qualify=qualify,
            )
            rewritten_hash = _source_sha256(rewritten)
            target_hash = (
                contract["new_source_sha256"]
                if qualify
                else contract["old_source_sha256"]
            )
            if rewritten_hash != target_hash:
                raise RuntimeError(
                    "Organization runtime function rewrite did not produce the "
                    f"code-owned definition: {contract['identity']}."
                )

            cursor.execute(contract["ddl"], [rewritten])
            if not qualify:
                cursor.execute(
                    f"ALTER FUNCTION {contract['identity']} RESET search_path"
                )

            after = _function_state(cursor, contract["identity"])
            target_config = _SAFE_SEARCH_PATH if qualify else ()
            if (
                after[0] != before[0]
                or after[2] != target_config
                or after[3] != before[3]
                or after[4] != before[4]
                or _source_sha256(after[1]) != target_hash
            ):
                raise RuntimeError(
                    "Organization runtime function identity, ACL, or definition "
                    f"changed unexpectedly: {contract['identity']}."
                )


def harden_runtime_functions(apps, schema_editor) -> None:  # type: ignore[no-untyped-def]
    del apps
    _rewrite_functions(schema_editor, qualify=True)


def restore_runtime_functions(apps, schema_editor) -> None:  # type: ignore[no-untyped-def]
    del apps
    _rewrite_functions(schema_editor, qualify=False)


def refuse_activated_downgrade(apps, schema_editor) -> None:  # type: ignore[no-untyped-def]
    """Do not weaken runtime helpers once durable cutover evidence exists."""

    del apps
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                to_regclass(
                    'public.authorization_authorityprovenanceactivation'
                ),
                to_regclass('public.authorization_provenanceactivationlatch'),
                to_regclass('public.audit_auditevent')
            """
        )
        relations = cursor.fetchone()
        if relations is None:
            raise RuntimeError(
                "Cannot prove dormant authority provenance state before downgrade."
            )
        marker_table, latch_table, audit_table = relations
        if marker_table is None and latch_table is None:
            if audit_table is None:
                return
            cursor.execute(
                """
                SELECT COUNT(*)
                  FROM public.audit_auditevent
                 WHERE operation =
                       'authorization.authority_provenance.activate'
                """
            )
            if int(cursor.fetchone()[0]) == 0:
                return
            raise RuntimeError(
                "Cannot reverse runtime-executable function hardening while "
                "activation audit evidence exists."
            )
        if marker_table is None or latch_table is None or audit_table is None:
            raise RuntimeError(
                "Cannot prove complete authority provenance state before downgrade."
            )

    schema_editor.execute(
        """
        LOCK TABLE
            public.audit_auditevent,
            public.authorization_authorityprovenanceactivation,
            public.authorization_provenanceactivationlatch
        IN ACCESS EXCLUSIVE MODE
        """
    )
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                (SELECT COUNT(*)
                   FROM public.authorization_authorityprovenanceactivation),
                (SELECT COUNT(*)
                   FROM public.audit_auditevent
                  WHERE operation =
                        'authorization.authority_provenance.activate'),
                (SELECT COUNT(*)
                   FROM public.authorization_provenanceactivationlatch),
                EXISTS (
                    SELECT 1
                      FROM public.authorization_provenanceactivationlatch
                     WHERE singleton IS TRUE AND generation = 0
                )
            """
        )
        row = cursor.fetchone()
    if row is None or not (
        int(row[0]) == 0 and int(row[1]) == 0 and int(row[2]) == 1 and bool(row[3])
    ):
        raise RuntimeError(
            "Cannot reverse runtime-executable function hardening after "
            "authority provenance activation. Keep compatible code and fix "
            "forward, or restore the whole database to one consistent "
            "pre-activation point."
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("organizations", "0012_idn011_convention_subject_guards"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunPython(
            harden_runtime_functions,
            reverse_code=restore_runtime_functions,
        ),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_activated_downgrade,
        ),
    ]
