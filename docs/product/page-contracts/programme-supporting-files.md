# Programme supporting-file tasks

- Status: Dormant #108 controls delivered through protected PR #150; final
  integrated/native/human acceptance and activation remain gated.
- Requirements: PRG-001/002/003/006, AUD-001/003, PRI-001/003, NFR-003/008/010/013,
  UX-003/005/006/007/008/012/013/020/027/029.
- Decisions: ADRs 0051, 0082, 0085, 0100, 0104 and 0105; no new ownership,
  schema, current profile, runtime grant or production route.

## Purpose and owning journey

Enter from the labelled safe-file answer card in the proposal task or permitted
current/sealed/review answer list. Use the existing personal or independent review
shell, one H1/main, scope/Access explanation and ordinary labelled links. A contributor
selects a local PDF, explicitly uploads and uses it as this answer, checks an uncertain
original outcome, inspects/downloads an independently admitted answer, or deliberately
clears the current answer. Do not offer raw receipt IDs, a generic file directory,
arbitrary storage URLs or a path into Registration/Workforce media.

Selecting a PDF is not an upload until the explicit **Upload and use this PDF** action.
Explain PDF-only, 10-MiB maximum, private question purpose/classification, retained
history/quotas and that scanning is not a benign-document guarantee. Original filenames
remain local to the browser's native control and are not transmitted as metadata or
retained. A successful upload advances the existing answer version once; no duplicate
file-answer lifecycle, profile or public rendition is created.

## Authority and transport

The owning command admits genuine lead/accepted collaborator, independent answer view
and write authority, exact applicable private question, original proposal/call/schema
versions, active Draft edit window and capacity before reading. It scans without a
database transaction, repeats locked source/authority/quota checks and commits receipt,
intake, bytes and the canonical answer atomically. Invalid, denied, stale, quota and
scanner states fail closed. Current-profile policy remains unchanged.

Use a bounded raw-PDF **PUT** task endpoint with ordinary Django CSRF protection and
the normal `X-CSRFToken` header. Do not add a CSRF exemption. The installed framework
checks unsafe non-POST requests using the header without parsing multipart input;
unsupported PUT types and malformed original intent are rejected before the
application reads bytes. Unsupported POST is not an upload path; ordinary framework
CSRF may parse POST before rejecting it, so this is not a generic network-ingress
resource guarantee. A trusted reader bounds actual reads, checks declared versus
actual length, rejects content encoding and never trusts filename/MIME/size assertions
as scan or custody evidence. No enclosing transaction may span reading/scanning.
Network, proxy and server buffering happen outside this application guarantee and
require deployment resource limits; do not claim a view prevents receiving network data.

The visible upload uses a labelled native file input and keyboard-operable button with
same-origin fetch. The upload/recovery page alone adds `connect-src 'self'` to the
existing default-deny content security policy; clear and attachment pages do not need
fetch. Without scripting, explain that uploading is unavailable; retain ordinary
server-rendered answer viewing/download and clear controls. No drag-and-drop,
pointer-only or animation-only operation is required. A browser MIME hint is not proof.

## Original intent and uncertainty

Bind original actor/organization/edition/proposal/question, all three source versions
and retry identity in a bounded purpose-signed proof. It is integrity evidence, not
permission. Preserve it through failures and page history; do not replace original
versions, regenerate a key, silently send different bytes or retry automatically.
No file bytes go into browser persistent storage, URL parameters or telemetry.

After an attempted upload, retain the chosen file and original intent until a confirmed
outcome or deliberate departure. **Check previous upload result** is body-free and
uses only the original retry authority, never new answer or download permission. A
missing recorded result may mean an earlier request is still running; it is not proof
that nothing can commit. After reload, a retained intent is a recovery task, not
permission to automatically resend a body. Starting a new upload is an explicit
navigation from current independently admitted proposal state.

Use visible status/error text and preserve focus/input on local validation, stale,
quota, dependency and uncertain-network outcomes. A new file cannot silently replace
the bytes associated with an attempted intent. Pending input receives the existing
discard-warning semantics; no navigation or automatic success refresh erases it.

## Clear and private attachment viewers

Clearing is a separate CSRF-protected original-intent confirmation through the existing
answer command. Explain that it clears only the current answer, does not delete retained
bytes/history/holds/backups, and does not satisfy a required question at sealing. It
does not restore a prior receipt through a raw identifier control. Historical receipt
reuse remains governed by the existing same-proposal/question/uploader command guards,
not a new attachment directory or unapproved historical download purpose.

Current and exact-current-seal contributors and independent reviewer/moderator/decider
pages use the delivered owner queries. Review remains exact-stage/assignment/conflict/
sensitive-field scoped; anonymous omission precedes links and file lookup, including
direct URLs. An upload, result receipt, navigation link or management-only context grants
no read authority. Metadata pages show authorized question text, presence and size;
bytes are requested only by an explicit attachment download.

Downloads use a code-owned fixed PDF filename, attachment disposition, no-store and
nosniff. No inline renderer, original filename, digest, storage reference or public URL
is exposed. Verify exact bounded bytes through the owner, prepare the response, then
repeat independent source/authority checks; withhold the whole response on change or
audit failure. Empty answers have no download link; missing/corrupt custody is honestly
unavailable with no generic-media fallback. Return links reauthorize at their destination.

## Evidence and remaining gates

Cover invalid/duplicate/oversized/tampered inputs, normal CSRF/origin/token denial before
body access, raw byte bounds, disabled scanner, original-key replay/conflict, stale
sources, late permission loss, no automatic resend, pending inputs, uncertain results,
clear/history preservation, exact attachment headers and anonymous no-lookup behavior.
Use synthetic desktop/narrow/keyboard/error/recovery browser journeys and automated
accessibility checks. Genuine native zoom, screen-reader, discard and representative
human comprehension remain explicit unchecked #92 tasks unless actually observed.

Maintain native tests but do not collect/run PostgreSQL under ADR 0100. Mocked UI/scan
seams are not native custody, real scanner health or integrated acceptance. #102 native
restoration, #97 logical recovery, #92 human and #109 integrated evidence remain mandatory
before final #108 promotion. These controls do not activate current profiles or close
#48 by themselves.
