# Dormant Programme upload-and-use and original-result commands

Date: 2026-09-16. Scope: another #108 supporting-file prerequisite under #48,
based on protected PR #147 (`9324dade5ca25b69f084fa55c242716642164b26`).

## Outcome and contract

Applications owns `upload_and_use_programme_file`: validate exact request/intent,
admit current contributor/private applicable question/versions/lifecycle and capacity
before invoking a bounded transport reader, validate dedicated scanner configuration,
scan outside an enclosing database transaction, and then reacquire canonical locks.
Both current view-field and mutation authority, original source/version/applicability
and retained count/byte quotas are checked before writing. Receipt, intake and private
bytes commit with the existing answer command; there is no second cursor or success
event namespace. Routine rationale is the explicit upload-and-use intent, not an
extra private explanation. Existing minimized command failure audit follows rollback.

`get_programme_file_upload_result` resolves only the original canonical receipt,
without reading/scanning a body, substituting current versions, creating a missing
answer or granting attachment-read authority. Consumed keys refuse a new body;
concurrent admitted uploads compare exact bytes and original intent before replay.
Fresh file-answer selection checks exact intake purpose before the existing native
guard; clear-answer performs no file lookup or file deletion.

PRG-002 and ADR 0105 clarify this original-intent/result boundary. No new migration,
runtime permission, dependency, profile, scanner provision, transport route, public
file URL or visible UI is introduced. The byte reader, private viewers and transport
must still be implemented. In particular, a future HTTP adapter must ensure middleware
or multipart processing does not read the body before the intended admission, and
must bound bytes during reading. The command callback contract alone is not proof
of that future transport.

## Verification and deferrals

- Complete database-free feedback: **8,751 tests passed in 53.79 seconds**.
- Seventy new command cases cover ordering, disabled/unavailable phases, malformed
  intent, transaction boundary, repeated source, exact quota boundaries, immutable
  purpose/retry metadata, body-free results, concurrent same/different bytes,
  post-scan read/write denial, stale source/lifecycle and one canonical answer.
- Ruff/format, configured NumPy and semantic docstrings, and strict command-module
  type analysis passed. Early focused failures caught the required canonical rationale
  and keyword-only preparer contract; both were corrected before complete feedback.
- Clean exact-commit eight-gate certification and protected GitHub checks are still
  required before delivery; any local receipt must remain `postgresql_deferred`.
- The custody native file now maintains **33 cases**, uncollected/unexecuted. Four
  new command scenarios cover canonical upload/body-free result, cross-scope pre-body
  denial, actual source change during unlocked scan, and answer-failure rollback.
  A fifth added variant retains both service-level and native cross-proposal refusal;
  the native variant bypasses only the Python convenience check, never a DB guard.
  Command-native scenarios mock scanner transport only, not claim a real scanner.
- No PostgreSQL tests, new schema observation, byte-download exercise, UI/browser
  acceptance, real scanner health, native coverage or new timing measurement ran.

The unchanged #102 debt includes real database execution, quota/concurrency/runtime
proof and measured shard budgets; #97 logical restore and #109/#92 integrated/human
acceptance remain mandatory. Next add independently authorized exact-answer byte
readers and upload/selection/download surfaces without anonymous identifying lookup.
Neither this command prerequisite nor the preceding schema closes #108 or #48.
