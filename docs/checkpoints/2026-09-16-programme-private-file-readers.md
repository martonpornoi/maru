# Dormant independently authorized Programme private-file readers

Date: 2026-09-16. Scope: #108 supporting-file prerequisite under #48,
based on protected PR #148 (`9f27d707a021e7f5dbe2bc826c97352301cc7d6b`).

## Contract and outcome

Applications supplies `get_self_programme_file` and `get_programme_review_file`.
Requests name independently authorized current/sealed questions or exact review
cases/allowlisted question keys, never arbitrary receipt/storage references.
Current contributors and exact-seal included contributors retain existing separate
summary/answer and summary/frozen field ceilings. Reviewers, moderators and deciders
retain exact role, Department, current seal, assignment/conflict, stage and sensitive
content policy. Anonymous review omits identifying file queries before custody lookup.

Exact organization/edition/proposal/question/answer-version and immutable clean
receipt evidence bind custody. Metadata returns presence/size and authorized question
text without reading byte content. Explicit byte reads verify bounded exact length
and digest, then repeat source admission and require minimized sensitive-read audit
before release. Neither storage key nor digest is exposed; private bytes and source
proof are excluded from repr. Shared read access is independent of uploading and
does not permit selecting another uploader's file. Empty metadata is an audited
absence without file lookup; empty downloads and missing/corrupt custody are unavailable.

PRG-002/003/006, AUD-003, PRI-001/003 and ADRs 0104/0105 remain the contract. No new
schema, ACL, dependency, current profile, URL, browser UI, inline renderer, scanner
deployment or unrelated product effect is introduced. Applications, privacy and
file-handling documentation describe the actual boundary. CURRENT is condensed to
current work and links; historical implementation/evidence stays in its checkpoints.

## Verification

- Complete database-free feedback: **8,851 passing units in 53.33 seconds**.
- **100 new cases** exercise exact metadata predicates, same-purpose shared access,
  malformed/absent references, metadata-only byte omission, immutable byte integrity,
  current/sealed field ceilings, source/authority/audit failures, three review roles,
  actual canonical review projection, anonymous SQL omission before file binding,
  stage-sensitive admission and original sealed answer binding.
- Strict typing, Ruff/format and configured public NumPy docstrings passed. Initial
  static feedback corrected Optional byte narrowing and documented the explicit
  empty-download failure; no acceptance policy was changed.
- Native custody file now maintains **37 cases**, uncollected/unexecuted. Four added
  cases cover exact current/sealed content, foreign-scope/unknown-question denial
  before custody, and genuine shared contributor/reviewer/moderator/decider reads
  under nonanonymous and anonymous review. Fixture construction uses the real upload
  command; scanner transport alone is mocked. No real scanner claim is made.
- Clean exact-commit eight-gate certification and independent protected hosted
  acceptance remain required before delivery. Any local receipt must remain
  `postgresql_deferred`, not full certification.
- No PostgreSQL test collection/execution, new schema observation, native coverage,
  timing measurements, browser acceptance or production data was used.

A feedback-only invocation of `validate_python_docstrings.py` without paths failed:
its argparse default is a tuple of strings, but `_python_files` expects `Path`
objects. The maintained explicit `src scripts` invocation passed for 706 files.
This pre-existing CLI-default defect is a non-blocking tooling follow-up after the
priority #48 work; no validation was bypassed and the validator is unchanged here.

## Remaining work

These owner queries are not an HTTP delivery implementation. Upload/selection/clear
and private viewer adapters must preserve original intent, CSRF and pre-body admission,
bounded reads, fixed-filename attachment-only responses, no-store/nosniff and final
source/authority checks after response preparation. Native behavior remains #102
debt; logical recovery #97, human #92 and integrated #109 gates remain mandatory.
#108/#48 are not closed by this prerequisite, and no current profile is activated.
