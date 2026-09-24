# ADR 0113: Exact enum-cast comparison after PostgreSQL logical restore

- Status: Accepted
- Date: 2026-09-20
- Extends: ADRs 0044, 0096 and the owning schema-readiness contracts
- Partially supersedes: literal deparser spelling only for the equivalence below
- Requirements: NFR-001, NFR-008, NFR-010, NFR-013, ARC-003, SCH-006
- Issue: #97 within #48; this does not complete #109 recovery acceptance

## Context

The retained #96 reproducer restores a populated release with exact functions,
triggers, ACLs and migration records, but the relation fingerprint rejects a
PostgreSQL 17 deparser change. An array-level cast of non-null unbounded varchar
constants to `text[]` is reparsed as element-level varchar-to-text casts. CHECK
and partial-index/exclusion predicates can exhibit the same difference.

A fresh 297-relation synthetic schema round-trip finds 90 raw shape differences.
The narrow comparison below reconciles 87. The other three are physical dropped-
column slots in `django_content_type`, `organizations_organization` and
`registration_attendeeregistrationprofile`, none of which is in a current pinned
relation-shape catalog. Those differences remain rejected, not normalized. This
observation does not certify populated runtime behavior, backups or all future
PostgreSQL representations.

## Decision

For exact CHECK/exclusion definitions and index definitions, map only this form:

```sql
ARRAY[('draft'::character varying)::text, ('archived'::character varying)::text]
```

to its original migration-built spelling:

```sql
(ARRAY['draft'::character varying, 'archived'::character varying])::text[]
```

The older Applications, Programme and Logistics definition catalogs request
PostgreSQL's pretty CHECK rendering. For that explicitly selected format only,
the same equivalence is rendered as:

```sql
ARRAY['draft'::character varying::text, 'archived'::character varying::text]
-- becomes the original pretty spelling:
ARRAY['draft'::character varying, 'archived'::character varying]::text[]
```

The two parser modes never mix. Index catalogs retain their existing non-pretty
format. Authorization's two conditional Workforce receipt trigger definitions
use the same pretty enum rule while retaining their complete original text and
all independent attachment metadata. These owners now hash the narrowly
canonicalized raw definition in Python
instead of hashing its uncanonicalized spelling in SQL. Every other catalog
metadata field and every reviewed definition/catalog digest remains unchanged.
This is a recovery compatibility correction, not adoption of Logistics or an
additional Programme source, command, event or permission.

Only nonempty ASCII code constants beginning with a letter and then letters,
digits, underscore, dot, colon, at-sign or hyphen are admitted. Preserve case,
order, multiplicity and every surrounding token. Both forms use exactly the
same non-null unbounded varchar constants and built-in text coercion; no domain,
typmod, expression, null, custom type, collation or extra cast is normalized.

Consume complete ordinary SQL string literals before recognizing an array, so
lookalike text inside a value cannot be rewritten. Backslashes or unhandled
quoted identifiers, dollar quoting or comments make the definition ineligible.
Ordinary literal contents such as a regex end-anchor remain untouched. Unsupported
forms continue to fail exact comparison and require explicit investigation.

Canonicalize only the definition field before its existing definition or JSON hash.
Retain every other relation, column, constraint and index metadata field exactly,
including validation, uniqueness, predicate, exclusion, ownership-related shape,
storage and physical column order. Do not ignore dropped-column slots, rebuild
objects, alter source data or update any pinned hash from an observed database.
The current fresh-schema fingerprints remain unchanged.

All independent native function/trigger, runtime role/ACL, migration, activation,
journal and owner-data checks remain required. A hash match neither repairs nor
authorizes a database. Runtime processes remain stopped until the complete
supported restore passes their actual readiness boundary.

## Consequences

No migration or new privilege is needed. Logical recovery can retain its exact
reviewed semantics without manually adopting restored hashes. Physical recovery
is unchanged. Later unsupported PostgreSQL formatting, physical layouts or type
forms fail closed rather than being treated as equivalent by a broad SQL parser.

The supported procedure restores one mutually consistent full custom-format dump
into a new isolated target, retaining migration records, native guards, role
ownership/ACLs and original evidence. It must separately restore required external
key/artifact material. Do not use data-only loading with disabled guards, fake
migrations or constraint deletion as a substitute. Existing restore tooling and
least-privilege runtime reauthorization still apply; no production restore is
performed or authorized by this implementation record.

## Alternatives considered

- Whitelisting arbitrary restored hashes: conceals unreviewed schema drift.
- General SQL simplification or cast stripping: can erase meaningful type,
  collation, predicate or validation differences.
- Rebuilding constraints after each restore: adds privileged recovery mutations
  where a precisely bounded representation comparison is sufficient.
- Discarding physical column positions globally: not needed by the affected
  current catalogs and broadens the contract beyond the reproduced issue.

## Required verification

Compare all current owner-pinned catalogs before/after real SQL reparsing and a
logical round-trip. Preserve raw evidence of the original failure. Test lookalike
quoted text, unsupported types/expressions, changed operators/literals/order,
weakened checks, invalid validation state and altered index predicates. Run the
populated release replay/withdrawal/invalidation scenario and genuine restricted-
runtime recovery, preserving original artifact bytes and denial after changed
authority. Missing journal/activation, unsafe ACLs and changed functions/triggers
must remain unavailable. #97 remains open until that complete evidence and
protected delivery exist.
