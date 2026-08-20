# ADR 0064: Repository supply-chain and code-scanning policy

- Status: Accepted
- Date: 2026-08-20
- Requirements: NFR-001, NFR-002, NFR-003, NFR-011
- Refines: ADR 0063 decisions 6 and 7

## Context

ADR 0063 established public hosted exact-commit acceptance, immutable Action
references, an exact Actions allowlist, Dependabot security updates, and
GitHub-managed CodeQL. The first public maintenance cycle exposed three gaps in
that broad direction.

Routine Dependabot updates did not preserve Maru's complete reviewed inputs.
The former Python updater could change `pyproject.toml` without rebuilding
`uv.lock`, a broad npm group crossed an incompatible TypeScript major version,
and the GitHub Actions updater could not update both workflow SHAs and the
separate exact allowlist. Those pull requests were routine version updates, not
responses to open security alerts.

The complete hosted matrix also installed dependencies and fanned out before
proving that `uv.lock` matched the manifest or that every external workflow
reference exactly matched the selected Actions policy. These cheap, objective
failures should stop acceptance before costly static, documentation, security,
unit, and PostgreSQL jobs begin.

GitHub-managed CodeQL was enabled, but ADR 0063 did not define an explicit
merge-blocking threshold. Public pull-request experience showed that medium-
severity exception and redirect findings can identify real defects at Maru's
personal-data and authorization boundary. Requiring only high-severity
security findings would therefore be too permissive.

Repository rulesets and security configuration remain external state. GitHub's
read API can add server-managed or undocumented response fields that do not
belong in a reviewed update payload. A checked-in ruleset must express the
supported desired inputs and be reconciled with live state; it is not a blind
serialization of every API response.

## Decision

1. Configure Dependabot for grouped security updates only in the native `uv`,
   npm, and GitHub Actions ecosystems. Each ecosystem keeps
   `open-pull-requests-limit: 0` so routine version-update pull requests remain
   suppressed without disabling security updates. A maintainer performs
   ordinary dependency maintenance at least quarterly and before a release
   when material dependency drift exists. Manifests and locks, and workflow
   SHAs and the Actions allowlist, change together on that branch.
2. Make locked inputs and Actions policy the first job of complete hosted
   acceptance. It runs `uv lock --check` and the repository-owned exact
   allowlist validator before any expensive fan-out. Every external Action
   reference must use a full immutable commit SHA; selected broad GitHub-owned
   or verified-publisher trust remains disabled; missing, duplicate, mutable,
   and unused allowlist entries fail the job.
3. Keep `PR gate` as the sole required status check and add the native
   `code_scanning` rule for CodeQL. General alerts block at `errors`; security
   alerts block at `medium_or_higher`. Default CodeQL analysis remains the
   provider-managed result consumed by that rule rather than a duplicate
   repository workflow.
4. Treat `.github/rulesets/main.json` as normalized supported desired state.
   Tests assert its exact CodeQL tool and thresholds. Before any authorized
   live mutation, read the current ruleset and compare all relevant
   protections. Submit only documented desired inputs. Read the result again
   afterward and verify the CodeQL thresholds, required status, pull-request
   rules, deletion and non-fast-forward protection, enforcement, and empty
   bypass list. Do not copy an undocumented or server-supplied field into a
   write payload merely because it appeared in a read response.
5. Repository setting changes require authorization separate from accepting or
   merging repository files. Record the intended value, observed pre-change
   value, applied value, and post-change verification in the milestone
   checkpoint. Unexplained drift fails closed and remains incomplete until the
   live state and reviewed desired state are reconciled.

## Consequences

- Security advisories can still produce grouped Dependabot pull requests,
  while routine upgrade noise and incompatible cross-major batching move into
  an intentional maintainer-owned maintenance cycle.
- A stale Python lock or Actions-policy mismatch fails in minutes instead of
  consuming a full acceptance matrix. This preflight supplements rather than
  replaces locked installation, dependency audits, or exact-commit tests.
- Workflow Action upgrades require a deliberate paired allowlist update. The
  stricter coupling is intentional evidence of reviewed executable automation.
- Medium-or-higher CodeQL security findings and error-level general findings
  block merging even when `PR gate` itself is green. Lower-severity findings
  remain visible for review without becoming an automatic repository rule.
- The checked-in ruleset is reviewable and testable but cannot prove the live
  setting by itself. Maintainers must re-query GitHub after changes and after
  material ownership, visibility, or plan changes.
- External settings are not smuggled into a code commit's authority. A branch
  can contain the desired state while the live mutation remains separately
  pending or verified.

## Alternatives considered

### Keep routine Dependabot version pull requests

Rejected because the bot could not update all of Maru's coupled inputs and its
broad groups obscured compatibility risk. Security updates remain automated;
routine updates move to a scheduled branch where locks and policy files can be
reviewed together.

### Allow mutable or publisher-wide Actions references

Rejected because a tag or broad trust rule can change executable workflow code
without a Maru commit. Exact immutable SHAs and exact allowlist equality keep
the reviewed repository tree authoritative.

### Let CodeQL influence merging only through conversations

Rejected because conversation behavior is indirect and can change without
expressing Maru's risk threshold. A native code-scanning rule makes the merge
boundary explicit while reusing the existing managed analysis.

### Block only high-severity CodeQL security findings

Rejected because medium-severity findings have already exposed actionable
defects at authorization and personal-data boundaries.

### Store and replay the complete live ruleset response

Rejected because read responses can contain server-managed or undocumented
fields that are unsuitable for write payloads. A normalized desired-state file
plus pre- and post-change comparison is safer and reviewable.

## Requirements affected

- NFR-001 gains executable contracts for the preflight, Dependabot policy,
  Actions allowlist, and normalized CodeQL rule.
- NFR-002 requires the maintenance and live-reconciliation procedures to stay
  synchronized with the repository controls.
- NFR-003 requires a checkpoint that distinguishes committed desired state from
  separately authorized GitHub mutations and their observed result.
- NFR-011 defines the protected repository and supply-chain boundary refined by
  this decision.
