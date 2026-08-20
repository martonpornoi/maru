# ADR 0062: Local exact-commit certification

- Status: Accepted
- Date: 2026-08-20
- Requirements: NFR-001, NFR-002, NFR-003, SEC-001, OPS-001
- Supersedes: ADR 0060 decisions 3 and 4, and ADR 0061's hosted full-
  acceptance topology

## Context

Accepted GitHub run `32304152005` proved the complete eight-shard acceptance
boundary, but its 14 jobs consumed approximately 392 rounded Linux runner-
minutes. The preceding failed attempt consumed approximately 379. At the
current GitHub rate those two runs explain almost all of the observed USD 4.63
charge. Repeating the matrix for ordinary pull requests would make normal
collaboration dependent on a small monthly Actions budget.

Skipping static, documentation, security, contract, or PostgreSQL evidence
would lower cost by weakening the definition of done. A local command alone is
also insufficient as a repository gate: Git hooks are intentionally
bypassable, and GitHub cannot know that a command ran for the submitted commit.
A GitHub-managed self-hosted job can execute on maintainer-owned compute while
GitHub records its result against the pull request.

The repository remains private on a plan for which both rulesets and classic
branch protection return HTTP 403. Repository-side protection can therefore be
prepared and tested, but it cannot become non-bypassable until GitHub Pro is
enabled or the separately reviewed public transition occurs.

## Decision

1. Every ready pull request runs one stable `PR gate` on the repository-scoped
   self-hosted Windows runner labelled `maru-certifier`. GitHub-hosted jobs no
   longer run Ruff, documentation, frontend, security, or PostgreSQL tests for
   pull requests.
2. The runner invokes `scripts/certify.ps1` for the checked-out Git commit. The
   command refuses a dirty tree, installs the locked environment, runs every
   static, NumPy documentation, Sphinx, Django, OpenAPI, frontend, and
   dependency-security gate, runs all Python tests, and enforces combined
   branch-aware coverage at 90 percent.
3. Preserve database isolation. One local process runs unit tests and eight
   measured whole-file integration shards concurrently against nine separate,
   digest-pinned PostgreSQL containers. Integration tests are not distributed
   with pytest-xdist because migration, database-role, trigger, historical-
   schema, and concurrency tests must not share a PostgreSQL server.
4. Retain exact-commit evidence for seven days: JUnit reports, per-process logs,
   combined coverage, a machine-readable certification receipt, and the
   warning-fatal Sphinx HTML site. `Full CI gate` reuses the same command for
   manual, merge-queue, and release certification.
5. Keep repository deletion analysis before the expensive command. Protected-
   path or mass deletion still requires the maintainer-applied
   `destructive-change-reviewed` label. A tracked pre-push hook blocks ordinary
   direct pushes to `main`, remote branch deletion, and non-fast-forward branch
   updates. It is defense in depth, not a server security boundary.
6. Apply the checked-in no-bypass `main` and release-tag rulesets as soon as the
   plan or visibility supports them. The required status remains `PR gate`;
   pull requests, squash-only linear history, resolved conversations,
   deletion prevention, and force-push prevention remain unchanged.
7. Before making Maru public, remove the personal persistent self-hosted runner
   from pull-request triggers and return public fork pull requests to GitHub-
   hosted standard runners, which GitHub does not bill for public repositories.
   An isolated disposable runner may replace them only after a separate
   security design. Untrusted fork code must never execute on a maintainer's
   workstation or a runner with local secrets or trusted network access.

## Consequences

- A complete pull-request certification consumes no GitHub-hosted compute and
  should retain approximately the eight-shard wall-clock critical path instead
  of serializing the four-hour suite on one database.
- The local machine must be online with Docker Desktop and the repository-
  scoped runner active. Otherwise the required check remains queued rather
  than silently passing.
- One host now bears the CPU, memory, storage, and network cost. Nine isolated
  containers are expected during certification, but they are removed in an
  outer cleanup block even when a gate fails.
- GitHub can certify only commits it has received. Feature-branch upload must
  precede the check; the protected merge into `main`, not the first branch
  upload, is the enforceable trust boundary.
- Until GitHub enables rules for this private repository, an owner can still
  bypass the prepared policy through GitHub. The tracked hook reduces
  accidental damage but cannot honestly be described as non-bypassable.
- Static and documentation failures remain fully enforced even though GitHub
  presents one aggregate check instead of separate hosted jobs.

## Alternatives considered

### Trust a local success receipt without running a GitHub job

Rejected because a contributor can edit or fabricate an unsigned receipt, and
GitHub cannot establish that it represents the submitted source and complete
test command.

### Require the full command in a pre-push hook

Rejected as the primary boundary because hooks are not installed automatically
when a repository is cloned and `--no-verify` bypasses them. A pre-push command
also cannot publish a trusted status for a commit GitHub has not received.

### Run pytest-xdist against one PostgreSQL service

Rejected because separate Django test databases do not isolate server-global
roles and other PostgreSQL catalog behavior. The repository's integration
contract requires separate PostgreSQL servers.

### Keep the hosted change-aware matrix

Rejected for the current private phase because even infrequent full runs use
hundreds of billed minutes. Public visibility can restore hosted execution at
no standard-runner charge when fork security becomes the higher priority.
