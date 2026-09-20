"""One exact PostgreSQL 17 enum-cast deparser equivalence, not SQL normalization."""

import hashlib
import re

_ENUM_VALUE = r"[a-zA-Z][a-zA-Z0-9_.:@-]*"
_STRING = re.compile(r"'(?:''|[^'])*'")
_RESTORED_MEMBER = rf"\('({_ENUM_VALUE})'::character varying\)::text"
_MEMBERS = re.compile(_RESTORED_MEMBER)
_TOKENS = re.compile(
    # Consume complete ordinary string literals first so text inside one can
    # never be mistaken for an SQL array expression. Doubled quotes stay literal.
    r"'(?:''|[^'])*'|"
    rf"(?<![a-zA-Z0-9_.])(?P<array>ARRAY\[{_RESTORED_MEMBER}"
    rf"(?:, {_RESTORED_MEMBER})*\])"
)
_PRETTY_MEMBER = rf"'({_ENUM_VALUE})'::character varying::text"
_PRETTY_MEMBERS = re.compile(_PRETTY_MEMBER)
_PRETTY_TOKENS = re.compile(
    r"'(?:''|[^'])*'|"
    rf"(?<![a-zA-Z0-9_.])(?P<array>ARRAY\[{_PRETTY_MEMBER}"
    rf"(?:, {_PRETTY_MEMBER})*\])"
)


def canonical_schema_definition(definition: str, *, pretty: bool = False) -> str:
    """Recover the reviewed array-level form of constant enum schema casts.

    PostgreSQL 17 reparses ``(ARRAY['x'::character varying])::text[]`` as
    ``ARRAY[('x'::character varying)::text]`` during logical restore. Both
    expressions cast exactly the same non-null, unbounded-varchar constants to
    text, in the same order. This maps only that element-level form back to the
    original spelling. It does not parse or simplify other SQL expressions.

    Parameters
    ----------
    definition : str
        Exact CHECK/exclusion or index definition from PostgreSQL's deparser.
    pretty : bool, default=False
        The exact deparser format used by the owning catalog. True handles only
        its corresponding unparenthesized constant casts; formats never mix.

    Returns
    -------
    str
        Original text with only recognized constant enum array casts restored to
        their array-level spelling. Other operators, terms, types, identifiers,
        literal order and multiplicity are unchanged.

    Notes
    -----
    Only ASCII code literals and exact unbounded built-in cast syntax are
    admitted. Definitions containing backslashes or unhandled quoted identifiers,
    dollar quoting or comment syntax are left completely unchanged. Unknown
    forms therefore fail existing exact fingerprints, not an inferred semantic
    comparison. This is not a database repair or permission to adopt new hashes.
    """
    if (
        not definition.startswith(
            (
                "CHECK (",
                "EXCLUDE USING ",
                "CREATE INDEX ",
                "CREATE UNIQUE INDEX ",
                "CREATE TRIGGER ",
            )
        )
        or "\\" in definition
    ):
        return definition
    outside_literals = _STRING.sub("", definition)
    if any(marker in outside_literals for marker in ('"', "$", "--", "/*")):
        return definition

    def replace_array(match: re.Match[str]) -> str:
        array = match.group("array")
        if array is None:
            return match.group()
        matcher = _PRETTY_MEMBERS if pretty else _MEMBERS
        values = (member.group(1) for member in matcher.finditer(array))
        members = ", ".join(f"'{value}'::character varying" for value in values)
        if pretty:
            return "ARRAY[" + members + "]::text[]"
        return "(ARRAY[" + members + "])::text[]"

    tokens = _PRETTY_TOKENS if pretty else _TOKENS
    return tokens.sub(replace_array, definition)


def schema_definition_sha256(definition: str, *, pretty: bool = False) -> str:
    """Hash exact schema text after the sole reviewed enum-cast equivalence.

    Parameters
    ----------
    definition : str
        Data-free PostgreSQL constraint or index definition.
    pretty : bool, default=False
        Exact deparser format requested by the owning catalog.

    Returns
    -------
    str
        Lowercase SHA-256 matching the unchanged migration-built definition pin.
    """
    canonical = canonical_schema_definition(definition, pretty=pretty)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
