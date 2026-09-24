"""Real PostgreSQL reparsing keeps exact owner hashes, never weakened guards."""

import pytest
from django.apps import apps
from django.db import connection, transaction
from psycopg import sql

from maru.applications import readiness as applications_readiness
from maru.authorization.programme_role_readiness import PROGRAMME_ROLE_SCHEMA_SHA256
from maru.authorization.provenance_readiness import _inspect_cutover_catalog
from maru.core.relation_schema_readiness import relation_schema_is_current
from maru.events.programme_setup_readiness import PROGRAMME_SETUP_SCHEMA_SHA256
from maru.identity.invitation_readiness import (
    inspect_platform_invitation_additive_catalog,
)
from maru.logistics import readiness as logistics_readiness
from maru.programme import readiness as programme_readiness
from maru.scheduling.readiness import SCHEDULING_SCHEMA_SHA256
from maru.venues.readiness import VENUE_BINDING_SCHEMA_SHA256
from maru.workforce.programme_starter_readiness import PROGRAMME_STARTER_SCHEMA_SHA256

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.mark.parametrize(
    "catalog",
    [
        PROGRAMME_ROLE_SCHEMA_SHA256,
        PROGRAMME_SETUP_SCHEMA_SHA256,
        PROGRAMME_STARTER_SCHEMA_SHA256,
        SCHEDULING_SCHEMA_SHA256,
        VENUE_BINDING_SCHEMA_SHA256,
    ],
    ids=["authorization", "events", "workforce", "scheduling", "venues"],
)
def test_all_pinned_owner_shapes_survive_real_constraint_and_index_reparse(catalog):
    _assert_reparse_preserves(catalog, lambda: relation_schema_is_current(catalog))


def _assert_reparse_preserves(catalog, check):
    assert check()
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT t.relname,c.conname,"
                "pg_catalog.pg_get_constraintdef(c.oid,false) "
                "FROM pg_catalog.pg_constraint c "
                "JOIN pg_catalog.pg_class t ON t.oid=c.conrelid "
                "JOIN pg_catalog.pg_namespace n ON n.oid=t.relnamespace "
                "WHERE n.nspname='public' AND t.relname=ANY(%s::text[]) "
                "AND c.contype IN ('c','x') ORDER BY t.relname,c.conname",
                [list(catalog)],
            )
            constraints = cursor.fetchall()
            for table, name, definition in constraints:
                cursor.execute(
                    sql.SQL("ALTER TABLE public.{} DROP CONSTRAINT {}").format(
                        sql.Identifier(table), sql.Identifier(name)
                    )
                )
                # Definition comes from this exact test-owned PostgreSQL catalog,
                # not arbitrary input. All DDL is rolled back before this case exits.
                cursor.execute(
                    sql.SQL("ALTER TABLE public.{} ADD CONSTRAINT {} ").format(
                        sql.Identifier(table), sql.Identifier(name)
                    )
                    + sql.SQL(definition)
                )
            cursor.execute(
                "SELECT i.relname,pg_catalog.pg_get_indexdef(i.oid,0,false) "
                "FROM pg_catalog.pg_index x "
                "JOIN pg_catalog.pg_class t ON t.oid=x.indrelid "
                "JOIN pg_catalog.pg_namespace n ON n.oid=t.relnamespace "
                "JOIN pg_catalog.pg_class i ON i.oid=x.indexrelid "
                "WHERE n.nspname='public' AND t.relname=ANY(%s::text[]) "
                "AND x.indpred IS NOT NULL "
                "AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_constraint c "
                "WHERE c.conindid=i.oid) ORDER BY i.relname",
                [list(catalog)],
            )
            for name, definition in cursor.fetchall():
                cursor.execute(
                    sql.SQL("DROP INDEX public.{}").format(sql.Identifier(name))
                )
                cursor.execute(definition)
        assert check()
        transaction.set_rollback(True)
    assert check()


@pytest.mark.parametrize("owner", ["applications", "programme", "logistics"])
def test_legacy_pretty_catalogs_preserve_existing_pins_after_real_reparse(owner):
    collectors = {
        "applications": (
            applications_readiness.collect_applications_schema_object_sha256
        ),
        "programme": programme_readiness.collect_programme_schema_object_sha256,
        "logistics": logistics_readiness.collect_logistics_schema_definition_sha256,
    }
    collect = collectors[owner]
    before = collect()
    assert before
    if owner == "applications":
        assert applications_readiness.inspect_applications_schema_catalog().ready
    elif owner == "programme":
        assert programme_readiness.inspect_programme_schema_catalog().ready
    else:
        assert before == dict(logistics_readiness.SCHEMA_DEFINITION_SHA256)
    relations = [
        model._meta.db_table for model in apps.get_app_config(owner).get_models()
    ]
    _assert_reparse_preserves(relations, lambda: collect() == before)


@pytest.mark.parametrize(
    "definition",
    [
        "CHECK (true)",
        "CHECK (aggregate_version >= 0)",
        "CHECK (aggregate_version > 0) NOT VALID",
        "CHECK (aggregate_version > 0) NO INHERIT",
        "CHECK ((aggregate_version > 0) AND lifecycle::text = ANY "
        "(ARRAY[('draft'::character varying)::text, "
        "('archived'::character varying)::text, "
        "('unknown'::character varying)::text]))",
    ],
)
def test_canonicalization_still_rejects_weakened_or_unvalidated_check(definition):
    assert relation_schema_is_current(SCHEDULING_SCHEMA_SHA256)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE public.scheduling_schedulingcandidate "
                "DROP CONSTRAINT sch_candidate_shape"
            )
            cursor.execute(
                "ALTER TABLE public.scheduling_schedulingcandidate "
                "ADD CONSTRAINT sch_candidate_shape " + definition
            )
        assert not relation_schema_is_current(SCHEDULING_SCHEMA_SHA256)
        transaction.set_rollback(True)
    assert relation_schema_is_current(SCHEDULING_SCHEMA_SHA256)


def test_canonicalization_does_not_hide_changed_unique_index_predicate():
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("DROP INDEX public.sch_change_evidence_review_uq")
            cursor.execute(
                "CREATE UNIQUE INDEX sch_change_evidence_review_uq ON "
                "public.scheduling_schedulingchangenoticeevidence (notice_id) "
                "WHERE action::text = ANY (ARRAY[('approve'::character varying)::text])"
            )
        assert not relation_schema_is_current(SCHEDULING_SCHEMA_SHA256)
        transaction.set_rollback(True)
    assert relation_schema_is_current(SCHEDULING_SCHEMA_SHA256)


_TRIGGERS = (
    "ac_workforce_page9_receipt_guard",
    "ac_workforce_position_receipt_guard",
    "identity_page10_delivery_version",
    "identity_page10_hardened_delivery_update",
)


def _trigger_ready(name):
    if name.startswith("identity_"):
        return inspect_platform_invitation_additive_catalog().triggers_attached
    return _inspect_cutover_catalog().guards_installed


def _trigger_definition(cursor, name):
    cursor.execute(
        "SELECT c.relname,pg_get_triggerdef(t.oid,true) FROM pg_trigger t "
        "JOIN pg_class c ON c.oid=t.tgrelid "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND NOT t.tgisinternal AND t.tgname=%s",
        [name],
    )
    rows = cursor.fetchall()
    assert len(rows) == 1
    return rows[0]


@pytest.mark.parametrize("name", _TRIGGERS)
def test_conditional_trigger_reparse_preserves_exact_reviewed_contract(name):
    assert _trigger_ready(name)
    with transaction.atomic():
        with connection.cursor() as cursor:
            table, definition = _trigger_definition(cursor, name)
            cursor.execute(
                sql.SQL("DROP TRIGGER {} ON public.{}").format(
                    sql.Identifier(name), sql.Identifier(table)
                )
            )
            cursor.execute(definition)
        assert _trigger_ready(name)
        transaction.set_rollback(True)
    assert _trigger_ready(name)


@pytest.mark.parametrize("name", _TRIGGERS[2:])
@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("<> ''", "= ''"),
        ("{32}", "{31}"),
        ("old.provider_reference", "new.provider_reference"),
        ("BEFORE UPDATE", "AFTER UPDATE"),
        ("BEFORE UPDATE", "BEFORE INSERT"),
    ],
)
def test_identity_deparsed_contract_rejects_predicate_or_attachment_change(
    name, before, after
):
    assert _trigger_ready(name)
    with transaction.atomic():
        with connection.cursor() as cursor:
            table, definition = _trigger_definition(cursor, name)
            changed = definition.replace(before, after)
            assert changed != definition
            # INSERT triggers cannot reference OLD; retain a valid but different
            # SQL predicate so rejection comes from the catalog, not DDL parsing.
            if "BEFORE INSERT" in changed:
                changed = changed.replace(
                    "old.provider_reference", "new.provider_reference"
                )
            cursor.execute(
                sql.SQL("DROP TRIGGER {} ON public.{}").format(
                    sql.Identifier(name), sql.Identifier(table)
                )
            )
            cursor.execute(changed)
        assert not _trigger_ready(name)
        transaction.set_rollback(True)
    assert _trigger_ready(name)
