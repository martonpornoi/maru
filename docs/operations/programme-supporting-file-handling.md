# Programme supporting-file handling

Status: dormant byte/scanner preparation, private custody schema and owning
upload/result commands and independent exact-answer readers under #108 / ADRs
0104–0105. No Programme upload, selection
or download route is enabled.
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

## Dormant owning upload and result commands

`programme_file_commands.upload_and_use_programme_file` admits the exact contributor,
applicable private question and original proposal/call/schema versions before it
calls a bounded transport reader. The caller cannot supply a prepared scan, MIME
type, filename, digest or receipt. Scanner configuration must be valid before body
reading. Enclosing transactions are refused before admission and after transport
reading; scanning holds no database transaction/locks. The trusted transport must
bound bytes while reading, not merely trust an uploaded size declaration.

After scanning, the command acquires canonical retry and edition/proposal locks,
reauthorizes both view fields and mutation, rechecks source/lifecycle/question/
versions and quotas, then creates exact receipt/intake/bytes and invokes the existing
answer command in one transaction. The answer command remains the sole cursor and
success evidence. The visible routine intent "Upload and use this supporting file."
is the canonical rationale; no extra private explanation is collected. Failure
uses existing minimized command audit, with no bytes/filename/findings in metadata.

Dormant transport and viewer surfaces use the owning commands below. Database custody
removes split external-object commit/orphan
handling from this first workflow; failed transactions retain no bytes, and failed
scans retain no quarantine copy. Privacy holds, authorized disposal and mutually
consistent recovery still require final acceptance. Do not delete referenced bytes
or discard history to recover an upload.

Preserve original intent through uncertainty. A consumed retry key rejects a fresh
upload before body reading. **Check previous upload result**, implemented by
`get_programme_file_upload_result`, accepts no file and retrieves only the original
canonical receipt under existing retry authority. Concurrent uploads admitted
before one wins compare exact bytes and intent before replay. Missing canonical
evidence is unavailable, never permission to recreate an answer. A result receipt
is not download permission. No production endpoint or current runtime write grant is enabled.

## Dormant independently authorized private readers

`programme_file_queries.get_self_programme_file` admits a current shared answer or
the exact current seal including the genuine contributor. It independently requires
the existing summary/answer or summary/frozen field ceiling; upload, retry or edit
authority is not sufficient. Another included contributor can read the same admitted
answer without becoming its uploader or acquiring permission to select their file.

`programme_review_file_queries.get_programme_review_file` independently admits
reviewer, moderator or decider scope, exact current seal, stage allowlist, assignment/
conflict and required sensitive-content authority. Anonymous omission occurs in the
canonical answer query, and direct file-reader access is refused before sealed-file
binding, intake metadata or bytes are queried. Management-only review context is not
content access.

Both query inputs identify an answer, never a receipt or storage key. Metadata binds
the exact organization, edition, proposal, immutable question, answer version and
clean receipt. The default minimized projection contains presence and size, not bytes,
digest, filename, storage reference or public URL. Only explicit `include_bytes=True`
loads the separate bounded byte relation and checks exact length and SHA-256. Missing
or inconsistent custody is unavailable with no generic-media fallback. Empty metadata
is an audited absence without file lookup; an empty-answer download is unavailable.
Required final source/authority comparison and sensitive-read audit must succeed
before any projection or bytes return. Private source and bytes are excluded from repr.

The dormant HTTP viewers deliberately request bytes only for an explicit download,
prepare a fixed-filename attachment-only response with no-store/nosniff, then repeat
source/authority checks before release. No inline PDF rendering, public URL, activation
or new runtime grant is implied. Source keys, filenames and scanner findings are not
a directory. The [supporting-file page contract](../product/page-contracts/programme-supporting-files.md)
owns local selection, original-intent recovery, deliberate clearing and viewer behavior.

## Dormant browser transport and recovery

Use a native local PDF choice and explicit upload-and-use action. The raw-PDF PUT
endpoint requires the normal CSRF header, a bounded purpose-signed original intent,
no query override/content encoding and an exact declared length up to 10 MiB. The
owner independently admits the source and scanner before calling a trusted bounded
reader. PUT avoids Django's POST multipart parsing during CSRF inspection; this does
not prevent proxy, server or ASGI buffering and is not deployment resource acceptance.
The upload/recovery page alone allows same-origin connections in its default-deny CSP.
Keep the existing framing, script and no-store restrictions.

After any attempted upload the browser retains its original intent and selected file,
disables resending and offers **Check previous upload result** without a body. Page
history stores only the bounded signed scope/version/retry proof, never bytes or a
filename. Reload is recovery-only. No result yet may mean a request is still running;
never treat it as permission to regenerate intent automatically. Start another upload
only through an explicit new task after checking the prior outcome and proposal history.
No-JavaScript viewing, attachment downloads and deliberate clear remain available;
upload and original-result checks explain their scripting requirement.

Original intent is not a bearer permission: every result, answer, clear and download
checks its own live authority. Clearing uses the existing answer command with a
routine fixed reason and original versions/key; it clears only the current answer,
not retained custody, seals, holds or backups. No receipt-directory or raw-ID editor
is exposed. Follow the organizer's safe-document guidance for downloaded attachments.

Unit tests use mocked sockets, not a real ClamAV scan. Real daemon/signature and
private-storage failure/recovery evidence remains #109 and deployment acceptance.
Maintained command-native cases mock only scanner transport to exercise database
behavior later; they do not claim a real malware scan or signature health.
The separately approved schema-only process observed exact fingerprints, unchanged
pre-existing constraints/indexes, empty reverse/reapply and all Applications
catalog/readiness facets. It neither collected nor ran native tests. Maintained
provenance/guard cases remain #102 debt; PostgreSQL suites stay skipped under ADR 0100.
#108/#48 remain incomplete until the integrated journey and all final gates pass.
