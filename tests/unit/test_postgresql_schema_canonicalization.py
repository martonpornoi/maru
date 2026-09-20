"""Exact enum-cast equivalence must not hide other constraint differences."""

import hashlib

import pytest

from maru.core.postgresql_schema_canonicalization import (
    canonical_schema_definition as canonical_check_definition,
)
from maru.core.postgresql_schema_canonicalization import (
    schema_definition_sha256,
)

ORIGINAL = (
    "CHECK (((aggregate_version > 0) AND ((lifecycle)::text = ANY "
    "((ARRAY['draft'::character varying, 'archived'::character varying])::text[]))))"
)
RESTORED = (
    "CHECK (((aggregate_version > 0) AND ((lifecycle)::text = ANY "
    "(ARRAY[('draft'::character varying)::text, "
    "('archived'::character varying)::text]))))"
)


def test_exact_pg17_round_trip_recovers_original_without_rebaselining():
    assert canonical_check_definition(ORIGINAL) == ORIGINAL
    assert canonical_check_definition(RESTORED) == ORIGINAL
    assert canonical_check_definition(canonical_check_definition(RESTORED)) == ORIGINAL


PRETTY_ORIGINAL = (
    "CHECK (state::text = ANY (ARRAY['draft'::character varying, "
    "'archived'::character varying]::text[]))"
)
PRETTY_RESTORED = (
    "CHECK (state::text = ANY (ARRAY['draft'::character varying::text, "
    "'archived'::character varying::text]))"
)


def test_pretty_deparser_preserves_its_existing_hash_without_mixing_formats():
    assert canonical_check_definition(PRETTY_RESTORED, pretty=True) == PRETTY_ORIGINAL
    assert canonical_check_definition(PRETTY_ORIGINAL, pretty=True) == PRETTY_ORIGINAL
    assert canonical_check_definition(PRETTY_RESTORED) == PRETTY_RESTORED
    assert canonical_check_definition(RESTORED, pretty=True) == RESTORED
    assert (
        schema_definition_sha256(PRETTY_RESTORED, pretty=True)
        == hashlib.sha256(PRETTY_ORIGINAL.encode()).hexdigest()
    )


@pytest.mark.parametrize(
    "replacement",
    [
        "'draft'::character varying(10)::text",
        "'draft'::public.enum_domain::text",
        "NULL::character varying::text",
        "lower('draft')::character varying::text",
        "'draft'::character varying::public.text",
        "'draft'::character varying COLLATE public.custom::text",
    ],
)
def test_pretty_deparser_does_not_simplify_other_types_or_expressions(replacement):
    definition = PRETTY_RESTORED.replace(
        "'draft'::character varying::text", replacement
    )
    assert canonical_check_definition(definition, pretty=True) == definition


def test_pretty_array_text_inside_literal_remains_untouched():
    payload = PRETTY_RESTORED.replace("'", "''")
    definition = f"CHECK (description <> '{payload}')"
    assert canonical_check_definition(definition, pretty=True) == definition


@pytest.mark.parametrize(
    ("old", "new"), [("ANY", "ALL"), ("'draft'", "'unknown'"), ("=", "<>")]
)
def test_pretty_deparser_keeps_changed_semantics_distinct(old, new):
    assert schema_definition_sha256(
        PRETTY_RESTORED.replace(old, new), pretty=True
    ) != schema_definition_sha256(PRETTY_ORIGINAL, pretty=True)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("aggregate_version > 0", "aggregate_version >= 0"),
        ("AND", "OR"),
        ("lifecycle", "another_column"),
        ("'draft'", "'approved'"),
        ("= ANY", "<> ANY"),
        ("= ANY", "= ALL"),
        ("::text =", "::citext ="),
        ("'archived'", "'draft'"),
    ],
)
def test_changed_semantics_never_match_original_fingerprint(old, new):
    assert canonical_check_definition(RESTORED.replace(old, new)) != ORIGINAL


@pytest.mark.parametrize(
    "expression",
    [
        "ARRAY['draft'::text]",
        "ARRAY[('draft'::character varying(10))::text]",
        "ARRAY[('draft'::public.enum_domain)::text]",
        "ARRAY[(NULL::character varying)::text]",
        "ARRAY[(lower('draft')::character varying)::text]",
        "ARRAY[('draft'::character varying)::text, NULL]",
        "ARRAY[('contains spaces'::character varying)::text]",
        "ARRAY[('árvíz'::character varying)::text]",
        "ARRAY[(''::character varying)::text]",
        "ARRAY[(E'draft'::character varying)::text]",
        "ARRAY[('draft'::character varying)::public.text]",
        "ARRAY[('draft'::character varying COLLATE public.custom)::text]",
        "ARRAY [ ('draft'::character varying)::text ]",
    ],
)
def test_other_sql_forms_are_not_normalized(expression):
    definition = f"CHECK (lifecycle::text = ANY ({expression}))"
    assert canonical_check_definition(definition) == definition


def test_array_shaped_content_inside_ordinary_literal_is_untouched():
    payload = "ARRAY[('draft'::character varying)::text]".replace("'", "''")
    definition = f"CHECK (description <> '{payload}')"
    assert canonical_check_definition(definition) == definition


@pytest.mark.parametrize("marker", ["\\", '"', "$", "--", "/*"])
def test_unhandled_quoting_or_escape_forms_disable_all_normalization(marker):
    definition = RESTORED[:-1] + f" AND {marker}unsupported)"
    assert canonical_check_definition(definition) == definition


def test_multiple_arrays_preserve_member_order_and_duplicates():
    expression = (
        "ARRAY[('read-only'::character varying)::text, "
        "('scope.v1'::character varying)::text, "
        "('read-only'::character varying)::text]"
    )
    expected = (
        "(ARRAY['read-only'::character varying, 'scope.v1'::character varying, "
        "'read-only'::character varying])::text[]"
    )
    assert (
        canonical_check_definition(
            f"CHECK (first = ANY ({expression}) AND second = ANY ({expression}))"
        )
        == f"CHECK (first = ANY ({expected}) AND second = ANY ({expected}))"
    )


def test_non_check_definitions_are_unchanged():
    definition = RESTORED.replace("CHECK", "DEFAULT", 1)
    assert canonical_check_definition(definition) == definition


@pytest.mark.parametrize("value", ["C1", "programme.evidence.public-rendition@1"])
def test_code_case_and_version_punctuation_are_preserved(value):
    assert (
        canonical_check_definition(
            f"CHECK (value = ANY (ARRAY[('{value}'::character varying)::text]))"
        )
        == f"CHECK (value = ANY ((ARRAY['{value}'::character varying])::text[]))"
    )


def test_literal_regex_anchor_is_not_confused_with_dollar_quoting():
    prefix = "CHECK ((digest ~ '^[0-9a-f]{64}$') AND "
    assert canonical_check_definition(prefix + RESTORED[7:]) == prefix + ORIGINAL[7:]


@pytest.mark.parametrize(
    "prefix",
    [
        "CREATE UNIQUE INDEX exact_name ON public.example USING btree (id) WHERE ",
        "CREATE INDEX exact_name ON public.example USING gist (id) WHERE ",
        "EXCLUDE USING gist (id WITH =) WHERE ",
    ],
)
def test_same_enum_equivalence_preserves_complete_index_and_exclusion_definition(
    prefix,
):
    assert canonical_check_definition(prefix + RESTORED[6:]) == prefix + ORIGINAL[6:]
