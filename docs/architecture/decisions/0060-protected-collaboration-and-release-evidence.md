# ADR 0060: Protected collaboration and evidence-bearing releases

- Status: Accepted
- Date: 2026-08-19
- Requirements: NFR-001, NFR-002, NFR-003, SEC-001, OPS-001

## Context

Maru is currently private and maintained by one person, but is intended to
become a public collaborative project. Direct default-branch work, mutable tags,
undifferentiated pull-request testing, and source-only GitHub archives would not
provide a safe collaboration or release boundary. The prior GitHub workflow
also created twelve PostgreSQL integration services for every change and used
source size as a poor duration proxy. One accepted run consumed hundreds of
billed PostgreSQL runner-minutes even though most pull requests do not change
database behavior.

Maru is deployable application source, not primarily a reusable Python library.
Its useful distributable is therefore a configured Django application/worker
image plus contracts and operational evidence. A wheel alone would neither
provision PostgreSQL nor supply the environment, migrations, workers, media,
telemetry, recovery, and governance needed for production use.

## Decision

1. Use protected GitHub flow. Work happens on branches, enters `main` through a
   pull request, resolves review conversations, passes one stable `PR gate`, and
   squash-merges into linear history. Deletion, force-push, and release-tag
   mutation are blocked by repository rules with no bypass actors. A mass or
   protected-path deletion additionally requires an explicit maintainer label.
2. Keep required approvals at zero while only one maintainer exists; otherwise
   the maintainer could not merge an emergency fix. `CODEOWNERS` identifies the
   current owner. Before or with a second maintainer, require one independent
   approval and CODEOWNER review.
3. Make pull-request CI change-aware. Documentation-only changes use no
   PostgreSQL service. Ordinary Python module changes run unit tests and a
   bounded affected integration selection. Migrations, models, settings,
   dependencies, security/authority boundaries, workflows, and test harnesses
   fail closed to full acceptance.
4. Separate full certification into a reusable workflow. Six isolated
   PostgreSQL shards use checked-in file-level durations from an accepted JUnit
   run, preserve whole files and serial execution within a shard, combine branch
   coverage once, and expose `Full CI gate`. It runs for high-risk changes,
   merge queues when available, manual certification, and every release.
5. Use release CalVer ``YYYY.MM.PR`` from the dedicated release pull request's
   merge month and number. Example: pull request 2 merged in August 2026 is
   ``2026.08.2`` (PEP 440 project form ``2026.8.2``). A rehearsal candidate is
   ``v2026.08.2-rc.1``; gold is ``v2026.08.2``. Candidate fixes increment the
   candidate sequence; a fix after gold uses a new pull request and therefore a
   new CalVer. Branch names do not enter stable versions.
6. Publish only through a manually invoked workflow at the exact current
   `main` merge commit. It rejects an unmerged or non-release PR, version drift,
   and any existing Git tag, GitHub Release, or OCI image tag. Concurrency is
   serialized by complete release identity.
7. Treat GHCR as the primary artifact. Publish a non-root, digest-pinned-base
   Django/Gunicorn image with collected static assets, immutable tag and digest,
   OCI SBOM and provenance attestations. Attach the contributor HTML archive,
   OpenAPI schema, dependency locks, manifest, license, and checksums to the
   GitHub Release. Candidate and gold environments remain separate approval
   boundaries.
8. License future public contributions under Apache-2.0 and maintain community,
   security, support, contribution, ownership, issue, pull-request, dependency,
   and release-note contracts in the repository.

## Consequences

- Most pull requests start zero to two PostgreSQL services instead of twelve;
  full certification starts seven total services (unit plus six integration).
- High-risk classification favors safety over savings. A maintainer may narrow
  an overly broad classifier only by changing and reviewing its repository
  contract, never by an ad hoc workflow bypass.
- A release is a reproducible deployment input and evidence bundle, not a claim
  that external infrastructure or production gates have passed.
- The repository can prepare rules while private, but GitHub may require a paid
  plan or public visibility before rulesets and other security features can be
  enforced. Visibility is never changed automatically.
- The current single maintainer can merge without self-approval. Public launch
  must revisit approval count, conduct/security contacts, ownership succession,
  secret scanning, and CodeQL triggers.
- A failed release after the immutable image push requires documented recovery
  with a new candidate number; an existing artifact is never overwritten.

## Alternatives considered

### Run all PostgreSQL tests on every pull request

Rejected because it spends the Actions budget regardless of relevance and
delays feedback. The full workflow remains mandatory where classification,
merge queue, or release risk warrants it.

### Publish a Python wheel as the primary artifact

Rejected for now because Maru is a Django service, not a stable embeddable
library. A wheel may be added if a supported Python API emerges, but it would
not replace the application image or operational evidence.

### Use year, day-of-month, and pull request

Rejected because a value such as ``26.19.2`` obscures the century and month.
``YYYY.MM.PR`` is readable, sortable, valid for GitHub/OCI, and collision-free
for one repository because pull request numbers never repeat.

### Require one approval immediately

Rejected until there is a second trusted maintainer. A nominal protection that
makes every legitimate merge impossible is not a usable security control.
