# ADR 0127: Export a bounded Workforce rota through existing source authority

- Status: Accepted
- Date: 2026-10-22
- Extends: ADRs 0003, 0078 and 0080; does not change their authority or profile meanings
- Requirements: HR-009, HR-016, AUD-001, AUD-005, PRI-001, PRI-003, NFR-002 and NFR-013

## Context

Issue #22 covers a complete reversible Workforce adoption package. A convention
also needs a smaller useful operating copy before the import, reconciliation,
full history and decommissioning contracts exist. Existing Shift planning already
loads a complete bounded edition projection. A generic model dump would disclose
private calendars, account identifiers and decision evidence beyond that purpose.

## Decision

Provide one versioned `maru.workforce-rota` package and one accessible print
representation for exact `workforce_only@1` editions. This is a captured Shift
and retained-commitment projection, not a complete Workforce archive, importer,
backup, restore or offline write-back facility.

Require current `events.view_basic` with every exported edition metadata field,
current `workforce.view_shifts` with its complete organizer field ceiling, and
separate `workforce.manage_shifts` authority. Read authority alone cannot export;
management alone cannot disclose personal fields. These already-declared
capabilities retain their meanings. No capability, role, profile, adapter pin,
grant or schema is added or expanded. Other profiles remain outside this first
contract. A later richer archive must define its own purpose and field ceiling.

Resolve the full route within admitted candidates before owner discovery. Events
provides a minimized, coherent edition metadata reference; Workforce owns Shift
and commitment inventory. Read metadata and the complete existing organizer
projection in one short repeatable-read read-only transaction. Keep the existing
1,024-demand and 4,096-total-commitment bounds. Overflow or integrity failure
produces no partial package.

Every demand and retained commitment carries its source UUID and command
version. Dates include UTC instants, offset-bearing edition-local instants and
the edition's IANA zone. Claims, confirmations, removals and completed work remain
distinct. Suitability booleans describe the captured check only. Names are not
unique person keys; the rota includes no platform account identifiers or person
registry. It excludes exact Availability windows, identity contacts, applications,
onboarding documents, decision reasons, authority records and unrelated modules.

Fully render and serialize before final admission. Then reread the current
account and repeat exact scope, profile, complete-field and management policy;
compare current edition metadata to the captured reference and append required
minimized audit before releasing bytes. An audit failure fails closed. Shift
changes after capture do not turn the copy into current coverage: the capture
time, versions and visible stale-copy warning make this limitation explicit.

The download contains `rota.json`, a closed versioned `schema.json`, a standalone
escaped `rota.html`, `README.txt` and a SHA256 `manifest.json` for the other four
members. The total uncompressed package is bounded at 16 MiB. Fixed ZIP member
names and metadata avoid path injection and unnecessary nondeterminism. Hashes
detect corruption; they do not attest authenticity or confer authority.

Print HTML uses one H1/main, semantic headings, ordinary links, wrapping content
and print styles. It loads no external asset or script. HTTP output is private
and no-store, varies on Cookie, uses no-referrer and nosniff, and disallows remote
content, forms and framing. A saved copy remains personal data: current server
policy cannot recall it, and its holder must follow approved storage, sharing,
retention and disposal procedures.

## Recovery and consequences

There is no domain mutation, notification, migration or runtime grant change.
Removing the adapters requires no database downgrade. A broken package or stale
copy is replaced by a newly authorized capture; neither edits nor imports it.
Keep separately approved incumbent fallback and restore procedures. Import,
manual reconciliation, complete Workforce history, stopped-operation/restart,
profile expansion and decommissioning remain open under #22. No CI result grants
human, accessibility, deployment, recovery-owner or production acceptance.

## Offline integrity check — 29 October 2026

Issue #223 adds a read-only command over a holder's saved version-one package.
It checks the five fixed members, closed manifest, byte lengths and SHA256 hashes
in memory, without extraction, HTML execution, network or Django initialization.
It does not trust or execute the supplied schema. Schema validation remains a
separate step, and matching attacker-controlled hashes never authenticates content.

Retain the 16 MiB complete uncompressed limit. The checker additionally bounds the
archive to 16 MiB plus 64 KiB, the manifest to 8 KiB and central-directory metadata
to 4 KiB before constructing ZIP entries. Require one terminal ordinary ZIP end
record for five entries on one disk; refuse ZIP64, comments, encrypted entries,
duplicate or unexpected paths and non-regular members. These limits include all
current producer output and provide a documented refusal rather than attempting
to interpret repackaged or ambiguous inputs. Only stored and deflated members are
supported. CRC, size or hash failure returns a fixed code and no payload details.

The command never contacts Maru, grants access, writes domain or audit records,
imports data or proves current state. A failed copy is replaced through the
existing authorized capture; this checker supplies no repair or extraction mode.
No migration, runtime privilege, profile, format version or dependency changes.

## Alternatives considered

- A complete cross-module archive now: too broad for this operating-copy outcome
  and would require new source-history, custody and purpose contracts.
- Export for every reader: rejected because saved personal copies have a wider
  retention consequence than an ordinary read; current management is also needed.
- Add a capability to an existing exact profile: rejected; no authority expansion
  is needed to render a stricter subset of its current bounded planning page.
- Serialize ORM objects: rejected; fields must be explicitly selected for this
  purpose and must not inherit private fields added later.
