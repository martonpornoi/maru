# PR #222: hosted security and interface findings

- Date: 2026-10-28
- Requirements: UX-007, UX-024, UX-029, UX-031, NFR-001–003 and NFR-011.
- Decisions: retain ADRs 0039, 0049, 0055, 0063 and 0064; no new domain authority.

## Failed hosted candidate

The maintainer authorized marking PR #222 ready and completing automated
acceptance and review while leaving it unmerged. The unchanged clean candidate
`61197159cf4372d5a8fb2cff2993b4e6389579fa` had already passed complete ordinary Auto
certification against `7bd59c0bf1130a7ebc8b202d0f47b2bc26c9182b`. Fresh preflight
matched all 3,266 tracked file hashes, the local/remote head and protected base.

Hosted run 40744143867 checked merge candidate `713a4c640de019a8a57206d8451a3f5eeac6ab9e`.
Its security job reported msgpack 1.2.1 affected by CVE-2026-114613. The remaining
quality job was cancelled after this known failure. The completed run retained
five successful jobs, three failed audit/downstream gates, one cancelled job and
six skipped alternatives/dependencies; no unit/native or coverage success is
claimed. Complete API pages, log ZIP and 89 safely extracted log files were
preserved with SHA-256 readback, with no published artifacts. The original local
certification outputs and all earlier failed/interrupted evidence remain intact.

## Bounded security repair

[GHSA-j586-36cw-2gc2](https://github.com/advisories/GHSA-j586-36cw-2gc2) entered
GitHub's global database on 27 October, after the successful local run. The
upstream [1.2.3 release](https://github.com/msgpack/msgpack-python/releases/tag/v1.2.3)
corrects C-extension ownership on rejected map keys, failing container hooks and
incomplete streaming operations. The development-tool constraint now requires
`msgpack>=1.2.3,<2`; the normal resolver selects 1.2.3. No audit exemption,
fallback switch or threshold changes. All 107 other Python package records and
all other lock policy remain exact; the sole added constraint sets this security floor.

Official old/fixed Python 3.12 Windows wheels and source archives were checked
against published PyPI hashes, and the upstream fix was inspected. Both versions
require Python 3.10 or later. The actual CacheControl consumer retained identical
serialized response bytes, old-cache readability, binary bodies/headers, Vary
refusal, empty/old-format cache misses and invalid-map-key refusal. These checks
do not claim a measured memory-leak reproduction. Fresh Python and all-severity
frontend audits report no known vulnerabilities.

## Supported review findings

One requested Copilot review completed on the old exact head with three findings:

1. Access sharing and replacement discarded typed expiry parsing failures before
   calling the API. Field-associated alerts now retain the expiry and reason,
   prevent the invalid request, clear on correction and permit resubmission.
   API failure handling, independent approval and authorization remain unchanged.
2. Unified-admin panel badges inherited a light foreground over a fixed light
   background. Their foreground/background now use the paired theme variables.
3. Suspended accountable representations received initial provisioning guidance.
   Their workspace now explains suspension and points to representation review
   and the approved recovery process. Active/provisioning states retain their
   separate destinations; missing/unknown state is unavailable. No recovery
   command, grant, activation or cross-organizer access is introduced.

The complete review pages, three comments/threads and review run logs are
preserved separately. The manual-test accounts, records, services and saved
checklist remain unchanged. The maintained demos are unaffected; supplied-state
verification is separate from a signed-in human journey.

## Verification boundary

Focused typed-input and state-template feedback passes 117 cases. All 128 frontend
cases pass; the four expiry regressions pass again after the final accessible-label
adjustment. Type checking and normal generated frontend build pass. Documentation
policy validates 778 Markdown files, four skills and 223 requirement identifiers.

Supplied-state browser checks at actual 320, 768 and 1,280 CSS pixels show no
page overflow in either theme, the paired badge colors and separate workspace
states. The dark badge's measured contrast is 16.45:1. The real built access
drawer displayed invalid share-expiry feedback, retained the input/reason and
accepted a corrected synthetic request; there was no database or domain writer.
One Change click required a recorded keyboard fallback. Automatic approval review
blocked the replacement-submit step, interpreting it as an access change; that
browser path is unclaimed and covered by component tests instead. Both preview
tabs and the owned preview server were closed and temporary viewport overrides
were reset. No real login, independent person, true zoom, screen reader, printer,
operational or production acceptance is claimed.

New complete exact-head certification is still required. Earlier success certifies
only its original head. The new clean candidate must pass ordinary Auto and
fresh hosted acceptance without weakening selection/history, native guards,
90% coverage, timing headroom, eight-worker limits, hooks or protections.

A collector's output helper failed because system Python 3.9 lacks the requested
newline argument; its intact downloads were verified by a separate finalizer.
An isolated wheel install and the first frontend attempt encountered sandbox
temporary-directory rename denial. Those originals remain preserved; fresh owned
temporary paths address the environment issue without changing application gates.
Two new frontend regressions initially expected POST for replacement; they now
assert the existing PATCH contract. A query option unsupported by the installed
Testing Library types was replaced by an exact-name regular expression. These
new-test assumptions, the failed helper and unexecuted temporary-path attempt
remain distinct from successful application evidence; old assertions are retained.

Record final run outcomes in PR #222 and ignored evidence while the certified
source stays pinned. Leave the PR unmerged. Human invitation acceptance,
independent browser/accessibility, operational, recovery and production gates
remain open.
