# Programme supporting-file handling

Status: dormant byte/scanner preparation only under #108 / ADR 0104. No Programme
upload, private storage, selection or download is enabled by these settings.
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

## Remaining intake and recovery work

The later Applications command must independently admit the exact contributor,
proposal/question and current version/lifecycle before reading an upload. It must
reauthorize under canonical locks after slow scan/storage, bind exact bytes and
original retry intent, and atomically retain provenance without replacing the
existing answer/seal command. No caller can supply a prepared result as permission.

Private immutable storage, uncertain writes, resumption, rejected/quarantined
objects, orphan cleanup, retained-answer/seal references, privacy holds, disposal
and mutually consistent recovery need their own completed owner implementation.
Do not delete referenced objects or discard history to recover an upload. Ordinary
rollback of this preparation-only code removes no persisted data.

Future personal/sealed/reviewer/moderator/decider downloads require independent
exact-answer authority before any file lookup. Anonymous review must omit identifying
file lookup entirely. Delivery is attachment-only with no public object URL, no-store,
type-sniffing protection and final source/authority checks; none is implemented by
the preparer alone. Source keys, filenames and scanner findings are not a directory.

Unit tests use mocked sockets, not a real ClamAV scan. Real daemon/signature and
private-storage failure/recovery evidence remains #109 and deployment acceptance.
Native provenance/guard tests and schema metadata remain #102 and the separately
approved schema-only process; PostgreSQL suites stay skipped under ADR 0100.
#108/#48 remain incomplete until intake, selection, viewers and all final gates pass.
