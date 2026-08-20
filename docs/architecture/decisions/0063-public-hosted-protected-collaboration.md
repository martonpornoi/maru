# ADR 0063: Public hosted protected collaboration

- Status: Accepted
- Date: 2026-08-20
- Requirements: NFR-001, NFR-002, NFR-003, SEC-001, OPS-001
- Supersedes: ADR 0062's self-hosted pull-request and release execution

## Context

ADR 0062 moved exact-commit acceptance to a persistent maintainer-owned runner
because hundreds of private-repository hosted minutes made each high-risk pull
request expensive. It also required that runner to be removed before public
visibility: a fork author can submit application or test code that a normal
pull-request workflow executes, even when the workflow definition itself is
unchanged.

Maru became public on 2026-08-20. Standard GitHub-hosted Actions for a public
repository no longer have the private-repository billing constraint that drove
ADR 0062. Public visibility also made repository rulesets available. Retaining
the personal runner would therefore add a serious trust risk without retaining
a cost advantage.

A locally generated receipt cannot become the required server result. The
contributor controls the machine, command, workspace, and receipt. GitHub must
evaluate the submitted head commit independently before the protected branch
accepts it.

## Decision

1. Unregister the persistent `maru-local-certifier` before public Actions run.
   Public pull requests, manual full acceptance, merge groups, and releases use
   only standard GitHub-hosted Linux runners. Do not use `pull_request_target`
   to execute contribution code.
2. Restore ADR 0060 and ADR 0061's fail-closed hosted topology. Documentation-
   only changes require no PostgreSQL service; ordinary source changes run
   static checks, unit tests, and bounded affected whole-file integration tests;
   dependencies, workflows, models, migrations, settings, security boundaries,
   and test infrastructure invoke the complete reusable eight-shard matrix.
3. Keep one stable `PR gate` as the required status. It evaluates the exact
   current pull-request head on GitHub-managed compute. Fork pull requests use
   read-only workflow permissions and receive no environment, package, release,
   or repository-secret authority.
4. Retain `scripts/certify.ps1` as the required contributor pre-review command.
   It supplies complete local feedback and clean-commit evidence across nine
   isolated PostgreSQL containers, but its unsigned receipt never replaces the
   hosted required status.
5. Enforce the checked-in `main` ruleset with no bypass actors: pull requests,
   up-to-date `PR gate`, resolved conversations, squash-only linear history,
   deletion prevention, and non-fast-forward prevention. Enforce a separate
   no-bypass immutable `v*` release-tag ruleset.
6. Run Actions in selected-only mode with SHA pinning. The exact external
   references in `.github/actions-allowlist.json` must equal those used by all
   workflow files; repository tests reject drift in either direction.
7. Enable public security controls: secret scanning, push protection,
   Dependabot security updates, private vulnerability reporting, and GitHub-
   managed default CodeQL for Actions, Python, and JavaScript/TypeScript.
   Review generated alerts before claiming public-launch completion.

## Consequences

- Untrusted contribution code runs on ephemeral GitHub infrastructure, not a
  maintainer workstation or trusted network.
- Public standard-runner use removes the private Actions charge that motivated
  local execution. High-risk acceptance can still take roughly one hour, while
  ordinary and documentation-only pull requests retain the faster selected
  path.
- `git push --no-verify` may upload a feature branch because GitHub must receive
  code before checking it. It cannot make that commit enter protected `main`
  without the up-to-date hosted `PR gate`.
- A local complete green result remains valuable and required process evidence,
  but server enforcement depends only on GitHub-recorded checks and active
  rulesets.
- A future self-hosted runner requires a separate disposable-isolation decision;
  a persistent personal runner is not an acceptable public pull-request target.
- Rulesets and security settings are external state. Maintainers re-query them
  after visibility, ownership, or plan changes and keep repository documentation
  synchronized with the observed result.

## Alternatives considered

### Keep the persistent runner but reject fork pull requests with a job condition

Rejected because skipped checks are easy to misconfigure, same-repository
credentials can still be compromised, and a maintainer can accidentally approve
untrusted execution. Removing the trust path is simpler and safer.

### Trust the local certification receipt

Rejected because the contributor controls its creation and GitHub cannot prove
that it represents the submitted commit or complete command.

### Run complete acceptance for every pull request

Rejected because the existing fail-closed classifier already routes risky
changes to full evidence while keeping documentation and ordinary module work
responsive. Full acceptance remains mandatory for release and high-risk paths.

### Keep Actions disabled permanently

Rejected because local hooks and receipts are bypassable and cannot enforce an
exact-commit merge boundary for public collaboration.
