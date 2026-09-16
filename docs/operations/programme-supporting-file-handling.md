# Programme supporting-file handling

Status: dormant byte/scanner preparation and private custody schema under #108 /
ADRs 0104–0105. No Programme upload, selection or download route is enabled.
Use synthetic data only. This is not a deployment or production-scanner approval.

## Current technical boundary

`applications.programme_file_preparation.prepare_programme_pdf` accepts actual
immutable bytes, at most 10 MiB, with a supported PDF header and final EOF envelope.
It preserves every byte and computes its own SHA-256/length. It neither interprets
nor sanitizes PDF content. A clean malware scan is not a guarantee that a document
is benign, accessible or structurally valid. No inline PDF renderer is provided.

Only the dedicated configured scanner can supply the clean observation. The
preparer uses one non-session ClamAV INSTREAM request, bounded chunks, a complete
NUL-framed response through connection close, and one absolute deadline for all
connect/send/read operations. Exact clean evidence is required; finding, missing,
extra, truncated, oversized, unknown or timed-out replies never produce a prepared
value. Raw findings, input names, document bytes and scanner exceptions must not be
shown to users or placed in operational telemetry.

The returned value is ephemeral and is not a persisted receipt, question-binding
proof, safe-publication approval, permission or storage URL. No ORM/storage/audit/
event write occurs here. Existing generic `ApplicationFileReceipt` normalization
is unchanged; no registration or Workforce document adapter is called.

## Configuration, still disabled by default

| Setting | Default | Initial supported boundary |
| --- | --- | --- |
| `MARU_PROGRAMME_FILE_SCANNER` | `disabled` | Only explicit `clamav`; no unscanned test/rehearsal mode |
| `MARU_PROGRAMME_FILE_SCANNER_HOST` | empty | Literal loopback IPv4/IPv6, normally `127.0.0.1` or `::1`; no DNS or other network endpoint |
| `MARU_PROGRAMME_FILE_SCANNER_PORT` | `3310` | Integer 1–65535 |
| `MARU_PROGRAMME_FILE_SCANNER_TIMEOUT_SECONDS` | `5` | Finite positive seconds, at most 10 for the entire exchange |

These are separate from the existing Registration/Workforce `MARU_MEDIA_SCANNER`
settings. Their compatibility/test modes do not authorize Programme scanning.
Enabling the adapter is not enabling the Programme workflow.
IPv4-mapped IPv6 addresses are explicitly unsupported, including alternate textual
spellings; this policy does not depend on a Python patch version's loopback
classification. Use a literal IPv4 loopback address or native IPv6 `::1`.

Before a future deployment, the operator must establish trusted local scanner
custody, appropriately maintained signatures, sufficient daemon stream limits and
bounded resources, supervision, update/failure alerts and independent health
evidence. ClamAV TCP is neither encrypted nor authenticated; this initial adapter
therefore requires a loopback endpoint in the same trusted network namespace.
Do not expose that socket to untrusted users or networks. No production daemon,
key, network exception or container is provisioned here. See the
[official protocol](https://docs.clamav.net/manual/Usage/ClamdProtocol.html).

## Dormant transactional custody

Applications migrations 0019–0021 add exact-purpose `ProgrammeFileIntake` metadata
and separate `ProgrammeFileContent` bytes. The code-owned generic receipt key is
`programme-db/<intake UUID>`, never a caller-selected path, original filename or
public URL. Only the eventual **Upload and use this file** transaction may retain
bytes, receipt and provenance together with the first canonical answer and its
existing success evidence. The schema does not introduce a second answer cursor.
Generic receipts alone cannot support a non-null Programme file answer.

Database guards enforce scope, uploader, private question, applicability, current
versions/lifecycle, exact digest/length and first-answer evidence. Each PDF is at
most 10 MiB; the serialized proposal-wide retention limit is 64 intakes and 64 MiB,
including history. Overflow rejects the transaction, never evicts an old file.
Metadata queries must not load the byte relation. Current runtime provisioning
grants SELECT only on both new relations and no execution on their guard functions;
this is not an upload permission. Do not manually grant write access.

Schema installation refuses existing non-null Programme file answers or reserved
storage keys without this provenance. Investigate/reconcile explicitly; do not
fake scan or first-answer evidence, drop records, or disable guards to migrate.
Once any custody exists, contraction is blocked before guards or tables are
removed. Fix forward with compatible code. An approved empty-schema reverse and
reapply was observed; populated behavior remains unexecuted native acceptance.

Backups must contain mutually consistent bytes, provenance, answers/seals,
audit/outbox and migration history in one whole-database recovery boundary.
Restrict backup access as for the underlying question data. Clearing an answer
does not delete its retained file, release a hold or remove a backup copy. No
automatic pruning or disposal workflow is enabled. Retention/hold/disposal,
backup-expiry, storage growth and recovery-time acceptance are activation gates.
Logical dump/restore readiness remains blocked by #97; this schema-only check does
not resolve it. Use synthetic data only.

## Remaining intake and recovery work

The later Applications command must independently admit the exact contributor,
proposal/question and current version/lifecycle before reading an upload. It must
reauthorize under canonical locks after slow scan/storage, bind exact bytes and
original retry intent, and atomically retain provenance without replacing the
existing answer/seal command. No caller can supply a prepared result as permission.

The owning command, retry/resumption and exact-answer private read boundary still
need implementation. Database custody removes split external-object commit/orphan
handling from this first workflow; failed transactions retain no bytes, and failed
scans retain no quarantine copy. Privacy holds, authorized disposal and mutually
consistent recovery still require final acceptance. Do not delete referenced bytes
or discard history to recover an upload.

Future personal/sealed/reviewer/moderator/decider downloads require independent
exact-answer authority before any file lookup. Anonymous review must omit identifying
file lookup entirely. Delivery is attachment-only with no public object URL, no-store,
type-sniffing protection and final source/authority checks; none is implemented by
the preparer alone. Source keys, filenames and scanner findings are not a directory.

Unit tests use mocked sockets, not a real ClamAV scan. Real daemon/signature and
private-storage failure/recovery evidence remains #109 and deployment acceptance.
The separately approved schema-only process observed exact fingerprints, unchanged
pre-existing constraints/indexes, empty reverse/reapply and all Applications
catalog/readiness facets. It neither collected nor ran native tests. Maintained
provenance/guard cases remain #102 debt; PostgreSQL suites stay skipped under ADR 0100.
#108/#48 remain incomplete until intake, selection, viewers and all final gates pass.
