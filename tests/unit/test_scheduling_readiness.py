"""Closed schema catalogs and fail-closed dormant runtime boundaries."""

from unittest.mock import MagicMock

import pytest
from django.apps import apps
from django.db import DatabaseError

from maru.authorization.database_role_safety import (
    RUNTIME_DATABASE_SELECT_ONLY_RELATIONS,
)
from maru.core import relation_schema_readiness as schema
from maru.scheduling import readiness
from maru.venues import readiness as venue_readiness


def test_every_new_owned_relation_is_runtime_select_only():
    names = {
        "public." + model._meta.db_table
        for model in apps.get_app_config("scheduling").get_models()
    } | {"public.venues_venueschedulingbinding"}
    assert len(names) == 26
    assert names <= set(RUNTIME_DATABASE_SELECT_ONLY_RELATIONS)


def test_empty_expected_schema_never_reports_success_or_queries_database(monkeypatch):
    collect = MagicMock()
    monkeypatch.setattr(schema, "collect_relation_schema_fingerprints", collect)
    assert not schema.relation_schema_is_current({})
    collect.assert_not_called()


def test_schema_collector_normalizes_json_adapters_and_binds_relation_names(
    monkeypatch,
):
    cursor = MagicMock()
    cursor.fetchall.return_value = [("example", {"columns": [], "relation": ["r"]})]
    manager = MagicMock()
    manager.__enter__.return_value = cursor
    monkeypatch.setattr(schema.connection, "cursor", lambda: manager)
    first = schema.collect_relation_schema_fingerprints(("untrusted' text",))
    cursor.fetchall.return_value = [("example", '{"relation":["r"],"columns":[]}')]
    assert schema.collect_relation_schema_fingerprints(("untrusted' text",)) == first
    query, values = cursor.execute.call_args.args
    assert "untrusted' text" not in query
    assert values == [["untrusted' text"]]
    assert len(first["example"]) == 64


@pytest.mark.parametrize("module", [readiness, venue_readiness])
def test_owner_readiness_fails_closed_when_catalog_access_fails(module, monkeypatch):
    def unavailable():
        raise DatabaseError("synthetic inaccessible catalog")

    monkeypatch.setattr(schema.connection, "cursor", unavailable)
    probe = (
        module.scheduling_database_integrity_is_ready
        if module is readiness
        else module.venues_database_integrity_is_ready
    )
    assert not probe()
