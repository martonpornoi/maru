# ADR 0104: Keep Programme supporting files purpose-bound in Applications

- Status: Accepted
- Date: 2026-09-16
- Extends: ADRs 0051, 0082 and 0085; does not widen current profiles or writers
- Requirements: PRG-001 through PRG-003, PRG-006, IDN-014, AUD-001, AUD-003,
  PRI-001, PRI-003, NFR-003, NFR-008, NFR-010 and NFR-013
- Issue: #108 under #48

## Context

The typed Applications `safe_file` value references an immutable clean
`ApplicationFileReceipt`. Its organization, edition, account, digest and scanner
fields do not implement Programme upload, exact proposal/question provenance,
private object custody, retry or independently authorized byte delivery. A receipt
dropdown or caller-supplied scanner result cannot complete that workflow.

Registration and Workforce have separate media/document boundaries. Programme
must not import their private adapters, create their product records or treat
local/test unscanned success as clean evidence. File bytes can identify a person
even when a proposal's scalar fields are anonymous.

## Decision

Applications owns the complete Programme file purpose. Initial intake supports
PDF supporting documents only, at most 10 MiB, and eventual downloads are private
attachments, never inline active-document previews. Further formats need an
explicit reviewed contract; arbitrary archives, Office documents and HTML are not
silently admitted. Checking a PDF envelope is not full PDF interpretation, content
sanitization, accessibility remediation or a guarantee that a document is benign.

Separate technical byte preparation from durable authorized intake. The preparer
accepts bounded actual bytes, checks the supported PDF envelope, and sends those
exact bytes to a dedicated configured ClamAV INSTREAM endpoint. Only a complete
exact NUL-framed `stream: OK` reply succeeds. Fragmented replies are assembled under
a small bound; findings reject the input, while partial, extra, unknown, errored,
oversized or timed-out evidence is unavailable. There is no test-clean, rehearsal-
clean, caller-supplied scanner, endpoint, digest or receipt override.

The initial transport accepts only configured literal loopback IPv4/IPv6 addresses.
No hostname resolution or public/other private-network endpoint is enabled. One
absolute deadline bounds connection, all chunk transfers and response reads, not
one renewable timeout per chunk. The socket closes on success and every failure.
ClamAV's TCP interface has no authentication or encryption, so trusted same-network-
namespace custody and signature/daemon health remain deployment prerequisites.
No real service, credentials or runtime provisioning is performed by this change.
The [official protocol](https://docs.clamav.net/manual/Usage/ClamdProtocol.html)
defines the framing and transport limitation; the additional closure is Maru policy.

The prepared result is ephemeral immutable bytes with a server-computed digest,
byte length, fixed MIME type and code-owned scanner protocol identifier. It is not
a database receipt, provenance proof or permission. Never display or log its bytes,
original filename, scanner findings or raw exception text. Preparation itself
performs no ORM, storage, role, owner-command, event or audit write.

Before a later command reads an uploaded body, it must independently authorize the
actual contributor and exact proposal/question/lifecycle/version. After slow scan
or storage work, reauthorize under canonical locks before atomic publication of
durable provenance and existing answer-command evidence. Bind request/retry intent
to scope, exact bytes and observed source versions. Do not advance or rewrite the
submission, seal, acknowledgement or accepted Programme item merely by scanning.

Future immutable storage and provenance must account for uncertain object writes,
retries, quarantine/rejection, unreferenced orphans, retained current/sealed answers,
privacy holds and recovery. Never delete referenced bytes during orphan cleanup.
Receipt IDs, storage keys or a successful prior scan grant no later download.
Current/sealed/reviewer/moderator/decider readers independently prove the exact
answer and field ceiling before any identifying metadata or byte lookup; anonymous
omission precedes lookup. No public storage URL or generic file directory is added.

## Implementation and acceptance boundary

The first increment implements only byte/scanner preparation with database-free
protocol and failure tests. Durable proposal/question provenance, receipt/native
guards, storage, selection, private viewers and custody/recovery remain unfinished
under #108. The unanswered schema-only exception is not assumed. PostgreSQL suites
remain uncollected/unexecuted under ADR 0100; #102/#97/#92/#109 remain mandatory
before promotion. This ADR neither adds a current profile nor activates upload.

## Alternatives considered

- A selector over arbitrary clean receipts lacks exact Programme provenance and
  a real intake/custody path; rejected.
- Sharing Registration/Workforce private adapters couples unadopted products and
  their compatibility modes; rejected. A future genuinely neutral service would
  require a separate reviewed migration, not a new dumping-ground utility.
- Trusting a MIME label, filename, `OK` substring or unframed response cannot prove
  exact bounded scanner evidence; rejected.
- Inline rendering or arbitrary document types adds an interpreter/security
  surface before the core private journey exists; deferred.
- Treating a clean scan as permanent permission confuses byte evidence with current
  relationship, field and retention authority; rejected.

## Consequences and requirements affected

PRG-001/002 gain a bounded supporting-file contract without duplicate answer state.
PRG-003/006 retain exact independent review/private-source ceilings. IDN-014 and
NFR-013 preserve separate purposes and excluded products. AUD/PRI and NFR safety
requirements retain minimized disclosure, honest dependency failures, private
custody and recovery gates. Some deployment configurations must provide a trusted
loopback scanner; remote scanning and additional formats remain unsupported.
