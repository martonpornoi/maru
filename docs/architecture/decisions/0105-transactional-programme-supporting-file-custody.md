# ADR 0105: Commit bounded Programme supporting files with their first answer

- Status: Accepted
- Date: 2026-09-16
- Extends: ADRs 0051, 0082 and 0104; current profiles remain unchanged
- Requirements: PRG-001, PRG-002, PRG-003, PRG-006, AUD-001, AUD-003,
  PRI-001, PRI-003, NFR-003, NFR-008, NFR-010 and NFR-013
- Issue: #108 under #48

## Context

The existing generic clean file receipt records scope, uploader, exact digest and
storage reference but cannot prove a Programme proposal/question purpose. The
bounded scanner preparer is implemented; it grants neither storage nor access.
Implementing external object storage now would add uncertain object writes and
orphan cleanup across a non-transactional boundary before a provider is selected.

## Decision

Use Applications-owned private database byte storage for this first bounded
supporting-document workflow, not a general media service or replacement for
commodity object storage. Keep bytes in a separate relation so ordinary receipt,
answer and provenance queries need not fetch content. No public/default media URL,
filesystem path or original filename is retained. The generic receipt's code-owned
opaque storage reference uses `programme-db/<intake UUID>`; generic receipt
normalization remains exact account/organization/edition/CLEAN.

An explicit **Upload and use this file** intent authorizes the actual contributor,
exact applicable private safe-file question and observed proposal/call/schema
versions before body reading. Scan outside the write transaction. Reauthorize
under canonical locks afterward; atomically create the clean generic receipt,
immutable exact-purpose intake, private bytes and first existing answer revision
with its canonical command receipt/audit/event/outbox. Scanning alone performs no
durable write or version advance. Only the explicit answer command advances the
existing submission cursor, once; no new proposal cursor or parallel file-answer
lifecycle is introduced. Uncertain retries retain the original intent and use the
canonical answer receipt, never new bytes or freshly substituted source versions.

The intake binds proposal, immutable question, uploader through its generic
receipt, original proposal/call/schema versions, retry identity and scan time.
Deferred guards require the exact first answer and canonical success evidence in
the same transaction. Every later use must bind that same proposal/question and
retain existing uploader selection restrictions. Independent shared/sealed/review
read authority remains separate from uploading or selecting someone else's file.

Each object is at most 10 MiB. A proposal retains at most 64 file intakes and
64 MiB of supporting bytes, including historical versions; count/byte quotas are
serialized with canonical proposal writes and enforced by database guards. Reject
overflow before creating success artifacts, with no silent deletion or oldest-file
replacement. Larger collections and an external store require a reviewed successor.

Failed scan/authorization/quota/transaction leaves no durable bytes or receipt;
there is no committed unreferenced staging object. Rejection retains no quarantine
copy. Byte digest and length are checked at persistence and before private
attachment-only delivery. Generic clean receipts alone cannot fabricate this
Programme custody path. The new relations are read-only for the current runtime;
their functions remain owner-only. No current profile, route or authority expands.

## Privacy, recovery and acceptance

Bytes inherit the exact question's purpose/classification and existing restricted
Applications retention contract. They are not logged, indexed for global search,
included in generic DTOs, exported to unrelated modules or rendered inline.
Metadata and byte reads require independent exact-answer authority and minimized
sensitive-read audit; anonymous omission precedes identifying lookup.

Retained bytes, intakes and answer/seal links are immutable. Clearing an answer is
not deletion or release of a privacy hold. No automatic pruning, hold override or
self-service destruction is enabled. Policy-approved retention/hold/disposal
execution and backup-expiry procedures remain activation gates; this foundation
does not authorize indefinite retention of production data. Synthetic data only.

Recovery uses one mutually consistent whole-database backup, including private
bytes, source/answer lineage, audit/outbox and migration history. Logical restore
acceptance remains #97. Storage growth, backup/restore time, private read load,
scanner health and deployment limits must pass #109/#102 before reliance. Empty
schema reversal is permitted; populated contraction is refused before guards or
bytes can be removed. Fix forward after durable intake.

The maintainer's 2026-09-16 approval permits a bounded disposable schema-only
migration/catalog check for this file work. It does not authorize PostgreSQL suite
collection/execution or native workflow acceptance. Maintain those cases under
#102; #109/#92 and final profile promotion remain separately gated.

## Alternatives and consequences

- External object storage stays a valid later scale option, but needs a chosen
  provider, immutable-write/retry/orphan protocol and consistent recovery proof.
- Filesystem storage adds custody/ACL/path/platform and split-commit concerns;
  it is not selected for this first supporting-document path.
- Receipt-only selection cannot prove stored bytes or purpose; rejected.
- Database custody simplifies atomicity and recovery but increases database,
  replication and backup size. Hard proposal quotas and deployment capacity
  acceptance are therefore part of the contract, not optional tuning.
