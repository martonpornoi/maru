# Contributing to Maru

Thank you for improving Maru. The project is preparing for public collaboration,
but its security, privacy, tenant-isolation, and audit boundaries already apply
to every change.

## Before you start

1. Search existing issues and discussions before proposing overlapping work.
2. Open an issue for behavior changes or architectural work. Small documentation
   and clearly isolated fixes may go directly to a pull request.
3. Never report a vulnerability in a public issue; follow [SECURITY.md](SECURITY.md).
4. Read [the development setup](docs/development/setup.md),
   [testing strategy](docs/quality/testing-strategy.md), and
   [documentation standards](docs/quality/documentation-standards.md).

## Development workflow

- Branch from current `main`; do not work directly on `main`.
- Use a descriptive branch name such as `feature/registration-export` or
  `fix/readiness-timeout`.
- Keep one coherent outcome per pull request and include tests and documentation.
- Add or update a stable product requirement identifier for product behavior.
- Record durable architecture decisions as ADRs; never rewrite an accepted ADR.
- Use synthetic data only. Never commit production data, secrets, credentials,
  private keys, tokens, or customer-identifying examples.
- Use NumPy-style Python docstrings and keep parameters, returns, yields, raises,
  notes, and examples meaningful where they help a contributor.

Run the local acceptance command before requesting review:

```powershell
./scripts/check.ps1
```

For a focused change, run the smallest relevant tests during development, but
the pull request must still satisfy the repository-owned `PR gate`. High-risk
changes are automatically routed to full PostgreSQL acceptance.

## Pull requests

Complete the pull request template. Explain the user or operator outcome,
security/privacy implications, migrations and recovery, tests, documentation,
and any intentionally deferred work. Resolve review conversations and use
squash merge so `main` remains linear.

Large or protected-path deletions require the `destructive-change-reviewed`
label from a maintainer. Automation must not be weakened merely to make a check
green. If a check is wrong, fix its contract and explain why.

By submitting a contribution, you agree that it is licensed under the
[Apache License 2.0](LICENSE) and that the [Code of Conduct](CODE_OF_CONDUCT.md)
applies to project spaces.
