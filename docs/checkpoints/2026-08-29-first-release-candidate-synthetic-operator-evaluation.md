# First release-candidate synthetic operator evaluation

- Date: 2026-08-29
- Phase: First public release-candidate evaluation
- Status: Complete synthetic evaluation; retained as a pre-production candidate
  with six bounded follow-up defects
- Related issue:
  [#29](https://github.com/martonpornoi/maru/issues/29)
- Candidate: `v2026.08.27-rc.1`
- Source commit: `be0b21db9ba2d2a956bd192a1d66c537d702c4c4`
- OCI digest:
  `sha256:a44de03a4fe7bd5b3a5aaf73dd83b565b727a98bf895bf80416981e869eeb445`
- Related requirements: HR-007, HR-009, HR-011 through HR-014, OPS-008,
  UX-029, UX-030, NFR-001 through NFR-004, NFR-008, and NFR-010 through
  NFR-013
- Related ADRs: 0042, 0044, 0046, 0060, 0065, 0073, 0075, 0076, 0077,
  0078, and 0080
- New ADRs: None

## Outcome and disposition

Issue #29 evaluated Maru's first immutable release candidate from a public
consumer boundary with synthetic data only. Fourteen recorded areas passed,
two failed, none were blocked, and two broad acceptance areas were deliberately
deferred.

The public Release, assets, source tag, OCI digest, SBOM, and strict provenance
relationships passed independent consumer verification. The exact image also
migrated and started against a fresh PostgreSQL 17 database, accepted the
repository-owned synthetic demo dataset, served build identity and liveness,
and persisted a completed Workforce-only journey through an ordinary ordered
stop and restart.

Two deployment-facing areas failed:

- `/health/ready` returned `503` because Logistics rejected an absent named
  runtime database role under the bounded local synthetic settings; and
- the default Gunicorn topology returned `404` for the page's collected static
  assets because the repository supplies no accepted edge/static composition.

The Workforce-only semantic journey itself passed from foundation setup
through completed Shift work, including distinct-account decisions, a
volunteer-owned action, two expected authorization denials, and an exact-edition
database boundary with no Participation, Registration, or directly scoped
unadopted-module state. One assignment interval exposed a fail-closed but
unhelpful approval conflict before a corrected proposal succeeded.

Six actionable findings are tracked separately in issues #37 through #42. This
evidence change does not alter the immutable candidate or combine its defects
with their fixes.

The candidate is retained as an immutable pre-production evaluation artifact.
It is not promoted to gold, production deployment, supported hosting,
production personal-data use, provider acceptance, owner acceptance, or
production readiness. Its tag, Release, assets, image, and attestations must
not be deleted or overwritten to repair a finding.

## Evaluation boundary

The evaluation began at `2026-08-29T16:45:28+02:00` with:

- Windows `10.0.26200`, x64;
- PowerShell `7.6.4`;
- GitHub CLI `2.96.0`;
- Git `2.46.0.windows.1`;
- Docker Engine `29.0.1`;
- Docker Buildx `0.29.1-desktop.1`;
- Chrome `151.0.7922.175` through the in-app browser;
- PostgreSQL image `postgres:17-alpine` at repository digest
  `sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193`
  on a fresh local volume;
- evaluation edition time zone `Europe/Budapest` with calendar horizon
  2026-08-28 through 2026-08-29; and
- only Maru-owned fictional identities, `.invalid` addresses, and
  repository-owned synthetic fixture data.

The public Release page was inspected without an authenticated browser
session. GitHub CLI Release and attestation verification used an authenticated
CLI session after a clean session exposed the undocumented authentication
prerequisite. No real convention data, production secret, payment, mail
delivery, or production infrastructure was used. Synthetic credentials are
intentionally excluded from this checkpoint.

One evaluator operated the distinct synthetic accounts and browser sessions.
That separation exercises the product's dual-control boundary but is not a
two-human owner acceptance rehearsal.

## Evidence summary

| Area | Result | Evidence type | Observation |
| --- | --- | --- | --- |
| Public Release presentation | Passed | Human observation | The anonymous page loaded with HTTP 200 and identified the Release as immutable, prerelease, and synthetic-only. |
| Release state and source | Passed | Automated consumer verification | GitHub reported immutable, non-draft prerelease state; the tag resolves exactly to `be0b21d`, and PR #27 is the exact merged source. |
| Release assets and checksums | Passed | Automated consumer verification | All eight assets downloaded and passed attestation verification; all seven payload hashes matched `SHA256SUMS`. |
| Manifest reconciliation | Passed | Automated consumer verification | The manifest matched the tag, PR, source commit, candidate identity, and OCI digest. |
| OCI identity | Passed | Automated consumer verification | The candidate image tag resolved to the recorded immutable index digest. |
| Provenance | Passed | Automated consumer verification | SLSA v1 verification constrained the signer to Maru's Release workflow, `refs/heads/main`, exact source digest, and GitHub-hosted runners. |
| SBOM | Passed | Automated inspection | The SPDX 2.3 SBOM described 179 packages and recorded Syft `1.51.0` and BuildKit `0.32.2` generators. |
| Image metadata | Passed | Automated inspection | Labels recorded exact revision `be0b21d`; the image is `linux/amd64`, runs as `10001:10001`, and defaults to production settings and Gunicorn. |
| Fresh database migration | Passed | Automated runtime observation | The complete migration graph applied to fresh PostgreSQL 17 through Workforce `0014`; no migration remained planned after restart. |
| Synthetic fixture load | Passed | Automated runtime observation | `maru-fictional-two-convention-v6` loaded successfully with 80 synthetic accounts. |
| Liveness and build identity | Passed | Automated HTTP observation | `/health/live` returned 200 and build metadata returned version `2026.08.27` and exact commit `be0b21d` before and after restart. |
| Readiness | Failed | Automated HTTP observation and source inspection | `/health/ready` returned 503 with only Logistics unavailable because the local runtime did not name a configured runtime database role. |
| Static delivery | Failed | Automated HTTP and human browser observation | Dynamic HTML returned 200, but five sampled referenced brand assets returned 404 and the default-Gunicorn page rendered unstyled. |
| Workforce-only journey | Passed | Human browser plus scoped database observation | Distinct synthetic roles completed setup, governed structure, assignment, Availability, and Shift work; a sanitized structured browser extract is retained below. |
| Denial and state boundary | Passed | Human browser plus scoped database observation | Organizer controls and unadopted Registration each returned a name-free 403 to the wrong actor; sanitized denial extracts and zero-row evidence are retained below. |
| Stop and restart | Passed | Automated runtime plus human browser observation | Ordered stop made the service unavailable; the same image and retained database restarted with persisted sessions and completed work. |
| Broad UX-029 matrix | Deferred | Explicit scope boundary | One unstyled synthetic path cannot prove every width, zoom, keyboard, screen-reader, motion, empty, denied, stale, or failure state. |
| Real-owner and production acceptance | Deferred | Explicit scope boundary | Real-human, provider, recovery, privacy, safeguarding, performance, training, and operational approvals remain required. |

The `SHA256SUMS` asset itself had SHA-256 digest
`c21b098b75ec173294192c206c976acdbfcb245b20c333e0b4e76b6687126b`.
Detailed publication evidence remains in the
[first-candidate publication checkpoint](2026-08-27-first-immutable-release-candidate-published.md).

## Supply-chain verification

The consumer-side sequence established:

1. the anonymous Release page was publicly reachable;
2. the Release was immutable, non-draft, and prerelease;
3. the tag resolved to exact source commit `be0b21d` and exact merged PR #27;
4. all eight Release assets downloaded and passed `gh release verify-asset`;
5. every one of the seven payloads listed in `SHA256SUMS` matched;
6. `release-manifest.json` reconciled the source, PR, tag, candidate, and image;
7. the GHCR tag resolved to the recorded immutable digest;
8. strict SLSA v1 provenance matched the exact workflow, main ref, source,
   GitHub-hosted builder, and expected predicate; and
9. the SPDX 2.3 SBOM was readable and internally identified its generators.

The artifacts passed. The inability to reproduce that complete sequence from
the maintained consumer instructions is tracked in
[#40](https://github.com/martonpornoi/maru/issues/40).

## Exact-image runtime

The image ran on private network `maru-issue29-net` with database container
`maru-issue29-db`, application container `maru-issue29-web`, and local binding
`127.0.0.1:8929`. The application used `maru.settings.local` only to provide a
bounded synthetic runtime that could not perform real delivery. That override
is not production-shaped deployment evidence.

Fresh migrations and seeding passed. Invitation encryption emitted the
expected local-settings warning and remained fail-closed; the rehearsal used
existing verified synthetic accounts and does not prove real invitation
delivery.

Readiness returned:

```json
{
  "status": "unavailable",
  "dependencies": {
    "database": "ok",
    "applications_integrity": "ok",
    "charities_integrity": "ok",
    "catalog_integrity": "ok",
    "venues_integrity": "ok",
    "logistics": "unavailable"
  }
}
```

`MARU_RUNTIME_DATABASE_ROLE` was empty in this local synthetic topology.
Current consumer documentation does not compose exact-image startup,
migration-owner/runtime separation, provenance cutover, runtime-role
activation, readiness, restart, and recovery into one executable contract.
That defect is tracked in
[#37](https://github.com/martonpornoi/maru/issues/37).

The image contained collected static output, but its default Gunicorn process
did not serve it and no accepted edge composition is supplied. The favicon,
Apple touch icon, manifest, brand stylesheet, and logo each returned 404 before
and after restart. The missing accepted and smoke-tested static topology is
tracked in [#38](https://github.com/martonpornoi/maru/issues/38).

## Synthetic Workforce-only journey

The browser evaluation used distinct sessions and fictional people for the
platform administrator, two accountable Maru operators, and the volunteer. It
observed:

1. **Passed:** a platform administrator created one new Workforce-only
   Organization, Convention series, and Event edition through **Set up
   Workforce**.
2. **Passed:** two distinct invitation records were created for existing
   synthetic people. Each account separately accepted its own invitation in an
   authenticated session before the administrator activated the appointments
   as Maru operators. Real delivery was not exercised.
3. **Passed:** the exact-edition route focused on Today, Workforce, and Setup,
   without Registration, payments, attendance, or unrelated-module pressure.
4. **Passed:** one operator created the **Volunteer Operations** Department,
   and the other independently approved the code-owned Volunteer starter.
5. **Passed:** an operator created the **Rota Volunteer** Position with a
   one-person headcount and published its bounded opportunity.
6. **Passed:** a separate volunteer session discovered the public opportunity
   and submitted one Workforce-owned application without creating
   Participation or Registration.
7. **Failed safely, then passed:** two assignment proposals whose effective
   interval began before controlling operator authority were rejected during
   independent approval. The page collapsed the authority interval cause into
   a generic state conflict. A corrected proposal starting inside current
   authority then passed independent approval and created one RoleAssignment
   with no Participation-capacity link.
8. **Passed:** the volunteer deliberately shared one exact Availability period,
   and the organizer saw exactly one shared period and person.
9. **Passed:** an operator published one **Rehearsal desk** Shift, the volunteer
   claimed it, a distinct operator confirmed it, and the first operator locked
   complete coverage.
10. **Passed:** only after the recorded `17:20` local end did the organizer
    complete the Shift; the volunteer's separate My Shifts page then showed
    **Completed**.
11. **Passed:** the volunteer's direct organizer Shift URL and an operator's
    direct unadopted Registration URL each returned a name-free `403 Forbidden`
    page without controls.
12. **Passed:** the same sessions, exact profile, active assignment, shared
    Availability, and completed Shift remained inspectable after restart.

The approval conflict is tracked in
[#39](https://github.com/martonpornoi/maru/issues/39). The contradiction between
profile-aware implementation and profile-unaware current documents is tracked
in [#41](https://github.com/martonpornoi/maru/issues/41). The missing
reproducible multi-role tutorial is tracked in
[#42](https://github.com/martonpornoi/maru/issues/42).

No broad claim of a clean browser console is made. Browser-extension
message-channel errors were not treated as application evidence; the
application's missing-static network responses are explicitly recorded as a
failure. Styling, responsive behavior, and the full accessibility matrix remain
deferred.

## Sanitized browser evidence extract

The following bounded structured-DOM observations were captured through the
in-app browser after the completed Shift and repeated after the container
restart. They contain no credential, token, raw database row, real identity, or
production data.

Organizer Shift page after the recorded end:

```text
main
  status: Shift completed.
  heading level=1: Rehearsal desk
  state: Completed; Version 4
  coverage item: Completed; Version 3
  completion decision:
    Record the synthetic release-candidate rehearsal as completed after its
    scheduled end. · 08/29/2026 5:20 p.m.
  next action: This Shift is retained and no longer accepts ordinary planning
    changes.
```

Volunteer My Shifts page in its separate session:

```text
main
  heading level=1: My shifts
  article heading: Rehearsal desk
  time: Sat, Aug 29, 17:10-17:20
  status: Completed
  text: This work is complete.
```

Volunteer session opening the exact organizer Shift URL:

```text
heading level=1: 403 Forbidden
paragraph: empty
```

Operator session opening the exact unadopted Registration setup URL:

```text
heading level=1: 403 Forbidden
paragraph: empty
```

The empty denial paragraphs are relevant evidence: neither response disclosed
the edition name, Shift, volunteer, operator, or authorization source, and no
organizer or Registration control was present.

## Exact-edition state boundary

The evaluation edition is `29a2eeda-e4aa-4c3a-b46b-bb0c43fcd2a6` with
immutable profile `workforce_only@1`.

Final scoped inspection after restart recorded:

| State | Result |
| --- | --- |
| Organization | 1 |
| Convention series | 1 |
| Event edition | 1, `workforce_only@1` |
| Organization representation | 1 active Maru-operator representation |
| Active appointments | 2 distinct active appointments |
| Department | 1 |
| Position template | 1 code-owned Volunteer starter |
| Position | 1 |
| Volunteer opportunity | 1, published |
| Volunteer application | 1, submitted |
| Position assignments | 3 total: 2 rejected interval attempts and 1 active |
| Active assignment authority | 1 RoleAssignment link; 0 Participation-capacity links |
| Availability | 1 submitted plan with 1 current window |
| Shift demand | 1, completed, command version 4 |
| Shift commitment | 1, completed, command version 3 |
| Participation | 0 |
| Participation capacity | 0 |
| Registration | 0 |
| Direct payment or commerce roots | 0 Registration, 0 CatalogOrder, and 0 edition-scoped PaymentProviderAccount rows; therefore no target-edition payment chain existed |
| Attendance or check-in | 0; the target edition had no Registration or Participation root from which attendance/check-in state could exist |
| Directly scoped Applications, Catalog, Charity, Communications, Logistics, Registration, and Venue records | 0 across every inspected Organization- or edition-owned model |

Counts are scoped to the evaluation Organization or exact Event edition as
appropriate. Global fixture counts are not modularity evidence because the
shared synthetic database contains unrelated full-convention editions.

## Stop and restart evidence

The ordered rehearsal passed:

1. the exact web container was stopped and `127.0.0.1:8929` became
   unreachable;
2. PostgreSQL was then stopped;
3. PostgreSQL restarted first and reported healthy;
4. the web container restarted from the same immutable digest as non-root user
   `10001:10001` and reported healthy;
5. build identity and `/health/live = 200` remained exact;
6. readiness remained the same known Logistics-only `503`, without a new
   dependency failure;
7. both organizer and volunteer sessions persisted and showed the completed
   Shift;
8. both authorization denials remained name-free 403 responses;
9. the scoped database audit matched the governed state above; and
10. `migrate --plan` reported no planned operations.

After the final inspection, both named containers were stopped. The stopped
containers, private network, PostgreSQL volume, and ignored local evidence
directory were retained temporarily for bounded follow-up; no production or
personal data is present.

No backup restore, PITR, runtime-role activation, worker supervision, outbound
mail, object storage, payment provider, or production rollback was exercised.

## Bounded follow-up issues

The actionable findings are separated by owner and remediation boundary:

1. [#37](https://github.com/martonpornoi/maru/issues/37) — exact-image
   PostgreSQL, authority, readiness, and restart rehearsal;
2. [#38](https://github.com/martonpornoi/maru/issues/38) — accepted and
   smoke-tested static delivery;
3. [#39](https://github.com/martonpornoi/maru/issues/39) — actionable
   assignment controlling-authority interval conflicts;
4. [#40](https://github.com/martonpornoi/maru/issues/40) — complete public
   consumer integrity verification;
5. [#41](https://github.com/martonpornoi/maru/issues/41) — profile-aware
   Participation evidence contracts; and
6. [#42](https://github.com/martonpornoi/maru/issues/42) — reproducible
   Workforce-only operator-and-volunteer tutorial.

The evaluation priority is #37, #38, #39, #40, #41, then #42. Each must enter
protected `main` through its own focused pull request. Source-changing repairs
do not mutate this candidate and require a new candidate identity if another
release is separately authorized.

## Data, migration, and deployment notes

This evidence change adds no model, migration, API, browser behavior, runtime
permission, release identity, or external deployment mutation. The local
database contains only repository-owned synthetic data.

The observed readiness and static failures are deployment/runbook inputs, not
authorization to silently select production infrastructure. The assignment
conflict remained atomic and granted no authority. No destructive cleanup or
recovery path was exercised.

## Verification of this checkpoint change

- public Release, asset, source, OCI, SBOM, and strict provenance verification
  passed as recorded above;
- fresh-image migration, synthetic seed, liveness, browser journey, scoped
  database inspection, and restart were repeated without broadening their
  acceptance boundary;
- the six actionable findings were opened as separate sanitized issues; and
- documentation policy, warning-fatal Sphinx/AutoAPI, clean-tree
  certification, and hosted PR acceptance are recorded separately for the
  exact evidence pull-request head.

## Known risks and incomplete work

- Issues #37 and #38 must be resolved before claiming a supported
  production-shaped image startup or browser surface.
- Issue #39 leaves a fail-closed but confusing Assignment recovery path.
- Issues #40 through #42 leave public verification, normative profile
  documentation, and the product rehearsal non-reproducible from one maintained
  path.
- UX-029's complete responsive, zoom, keyboard, screen-reader, reduced-motion,
  disclosure, mutation-role, and failure-state matrix remains open under #23.
- Workforce continuity export, print/manual fallback, reconciliation, and
  stop/expand procedures remain open under #22.
- Check-in, late/absent escalation, handover, actual time, and schedule
  publication remain contract-first work under #24.
- Real convention owners have not accepted the two-person Assignment and Shift
  ceremonies.
- Production deployment, role activation, restore/PITR, retention execution,
  provider certification, privacy, safeguarding, telemetry, performance, and
  training remain explicit gates.

## Recommended next actions

1. Resolve #37 through #42 in the priority recorded above, one focused
   protected pull request at a time.
2. Complete #22's continuity and reversible-adoption package.
3. Complete #23's full Workforce and Shift accessibility matrix.
4. Accept #24's attendance, handover, and actual-time contract before
   implementation.
5. Rehearse a new candidate identity only after source-changing defects merge
   and a separate release is explicitly authorized.
