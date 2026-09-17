# Dormant actual-person Programme approval commands (#108)

- Phase: Programme Operations implementation, not activation.
- Requirements: IDN-002, IDN-004, IDN-005, IDN-012, IDN-014, EVT-006,
  EVT-007, AUD-001 and NFR-013.
- Decisions: ADRs 0041, 0044, 0080, 0081, 0100 and 0106; no new ADR.
- Owner: [Authorization](../modules/authorization.md#actual-person-operational-approval-commands),
  within #108's existing accountable-setup item under #48.

## Outcome and scope

The dormant public application commands retain a current controller's exact
request and the named independent person's actual approve/decline action, or the
author's cancellation. A request grants nothing. Approval composes existing
immutable role creation and exact assignment commands rather than introducing
another authority model. Original assignment rationale and separate decision
rationale are retained. Current profiles still reject before database work.

Shared authority fences and actor/key serialization precede canonical foundation,
edition, target, request, UUID-ordered person and source locks. Every recipe,
capability, organization/edition/Department/resource scope, genuine active person,
current controller horizon and integrity boundary is rechecked. Organization-wide
Venue authority keeps an exact Programme context; typed-resource intent cannot
substitute another binding kind. Truthful representation and both fixed root roles
remain unchanged.

Approval starts no earlier than its actual decision, preserves the original end,
and cannot pass the seven-day deadline. Exact historically proven role definitions
are reused; existing conflicting versions are never silently upgraded. A new
definition still needs both controllers' organization-level role authority.
Assignment, provenance, owner effects/audits and terminal evidence commit together.
Any final-record failure rolls back earlier owner writes. Exact retries require
the actual caller's current source and return the original result, not renewed or
regranted authority. Decline/cancel creates no grant. Current scope/recipe admission
also applies to terminal retries and cancellation; unavailable state retains history.

## Verification at implementation checkpoint

- Focused database-free command/boundary tests: **87 passed in 0.50 seconds**.
  Existing approval storage regressions also passed in the earlier 110-case run.
- Complete unit feedback before the final two resource-kind negatives:
  **9,408 passed in 66.86 seconds**, with three existing Django URL warnings.
- Strict mypy: **703 source files passed**. Ruff, strict NumPy contracts and
  semantic documentation checks passed after correcting explicit exception docs.
- The first complete unit attempt used pytest's inaccessible shared Windows temp
  directory: **9,145 passed, 263 setup errors**, not a successful run. A focused
  reproduction confirmed `PermissionError` on `Temp/pytest-of-TheMw`. The complete
  successful rerun used a fresh task-owned repository temp directory, with no skips,
  permission changes or deletion of another run's files.
- Fresh clean exact-commit certification and hosted protected delivery remain
  separate pending evidence at this checkpoint.
- The first certification attempt selected the app fallback's pnpm 11.19.0,
  rather than the repository-pinned 11.9.0. Its verified task-only process tree
  was stopped before completion; its log is retained and no receipt is accepted.
  The corrected run must prepend the existing local 11.9.0 installation to PATH
  and verify its version before starting. No dependency or lockfile was changed.

Ten maintained PostgreSQL command scenarios extend the existing schema test file:
actual request/no-grant and independently approved assignment with exact replay;
decline/cancel terminal exclusion; complete bundle/assignment/audit/effect rollback;
unrelated actors; existing foreign owner scope; revocation of either ordinary
controller; and replay of an already revoked output without regranting it. They
use a transaction-local single-recipe candidate and real owner commands/guards,
not a complete Programme profile. **None was collected or executed.**

## Migration, recovery and remaining acceptance

No migration, metadata fingerprint, runtime grant, root role, profile, browser
route, provider or notification change. Existing direct-write protection remains;
only a private command context can append via model save. Native guards and runtime
SELECT-only provisioning are unchanged. No Docker container was needed or started.
Existing downgrade fences, retained evidence and fix-forward rules remain.

#102 retains native behavior, all scope variants, concurrent request/decision
arbitration, expiry while waiting, runtime-role and exhaustive migration/recovery
acceptance. No new test timings or coverage/headroom are inferred from deferred
cases. Current-profile denial and orchestration tests do not replace that proof.
#97 logical recovery, #92 human checks and #109 integrated evidence remain required.

Next deliver this command increment through protected checks, then add protected
approval readers and genuine-person guided setup continuation. Complete the isolated
setup-to-on-site fixture before restoring final database acceptance. Neither this
increment nor a green development PR closes #108 or #48 or activates Programme.
