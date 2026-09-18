# Programme setup-to-on-site rehearsal

**Audience:** Maintainers preparing #108, independent Programme evaluators and recovery operators\
**Outcome:** Prepare one reproducible journey and collect evidence for #109/#92 without confusing component delivery with acceptance\
**Status:** Preparation protocol; the complete fixture and setup are not yet implemented or accepted

## Entry conditions and authority

This protocol implements the acceptance plan for [#48](https://github.com/martonpornoi/maru/issues/48),
not a new product scope. Use the [setup contract](../product/page-contracts/programme-operations-adoption-setup.md),
ADR 0081, NFR-013, IDN-011/012, PRG-001 through PRG-011, SCH-001 through SCH-012,
OPS-009, INT-007 and UX-029 as the owning boundaries. Current status belongs in
[CURRENT](../project/CURRENT.md), not in a copied readiness percentage.

While ADR 0100 defers PostgreSQL, prepare fixture code, role scripts, assertions
and documentation, but do not collect or execute database tests. Mocked browser
observations remain component evidence. A fixture lease ending successfully is
cleanup evidence, not a successful journey. Do not enable the production profile,
add runtime grants, provision production keys or use personal data to make a demo.

Before executing final acceptance:

- pin the candidate commit, dependency locks, supported PostgreSQL image and
  exact isolated candidate profile/role definitions;
- restore required PostgreSQL verification under #102 and establish #97's
  supported logical-recovery procedure;
- provide an explicit opt-in launcher with a dedicated database, loopback URL,
  bounded lease and verified task-owned cleanup; **no complete integrated launcher
  exists yet**, so there is no launch command in this protocol;
- use real owning commands and permissions for acceptance, not an always-allow
  authorizer, direct status edits, disabled guards or fabricated approval;
- record synthetic scanner/signing/delivery adapters and their limits separately
  from any evidence obtained with real supported adapters; and
- preserve existing profiles and the unadopted product boundaries throughout.

Existing `tests/rehearsals/programme_*.py` files exercise individual components.
Some require PostgreSQL and synthetic authority substitutions. They must not be
launched during deferral or relabelled as the complete fixture.

## Prepare the fixture and distinct sessions

Fixture preparation starts with a closed test-only candidate definition: literal
capabilities, shell destinations, registered effect routes, versioned catalogs,
adapters, conflict sources and unchanged root-role codes. Do not derive its
authority by accepting every current or future capability in a module, or inherit
unrelated full-convention destinations/effects. Importing the candidate must not
register a runtime/selectable/persisted profile, mount routes, change model choices,
alter guards, open a database or create records. Validate it independently against
the owners' declared catalogs and the current manifest containment guards.

Prepared components live in `tests/rehearsals/programme_candidate.py`,
`programme_effects.py` and `programme_urls.py`. The candidate preserves the
Workforce/foundation pins and admits the explicit Programme owner adapters and
role recipes, without assigning those roles to anyone. Its independent Effects
registry uses the real internal-fact acknowledgement handler, not a notification
or invitation-delivery substitute. The joined URLconf includes all ten dormant
owner route modules plus the unchanged shared application routes. It changes
neither `ROOT_URLCONF` nor either current profile. Existing unrelated routes stay
available for denial probes; routing alone proves neither admission nor isolation.

Database-free tests check every included owner route for exact name, handler and
scope round trips, collisions and continued absence from current URLconfs. They
also validate catalog completeness, explicit exclusions and import purity. These
are preparation checks, not requests against a running server, native authority,
schema installation, genuine-person acceptance or P01–P12 results.

The eventual opt-in fixture must separately establish its disposable database and
actual approved runtime boundary. A test-only candidate object is neither a launcher
nor a migration, and does not satisfy P01–P12 by itself. Never launch it under the
deferred policy; retain explicit not-run status until restored acceptance.

### Prepared runtime resource boundary

`tests/rehearsals/programme_runtime_environment.py` checks the tracked PostgreSQL
policy before reading connection configuration. Native entry requires explicit
`MARU_PROGRAMME_REHEARSAL=isolated`, a nonzero lowercase 32-hex
`MARU_PROGRAMME_REHEARSAL_RUN_ID`, and a canonical
`MARU_PROGRAMME_REHEARSAL_LEASE_SECONDS` value from 60 through 3600. The application
environment additionally requires a credential-bearing `MARU_DATABASE_URL` for
`maru_runtime` at `127.0.0.1` on an explicit nonprivileged port, with exact database
name `maru_programme_<run-id>` and `MARU_RUNTIME_DATABASE_ROLE=maru_runtime`.
Query/fragment overrides, foreign databases and ambient libpq targeting/options
are rejected. Error messages and object representations omit connection secrets;
callers must never log or serialize the credential-bearing field.

`programme_database.py` prepares an owned disposable database transport, not a
complete runner. It uses the existing pinned PostgreSQL 17 image, a local Docker
socket/pipe, one loopback-only ephemeral port, tmpfs data and auto-removal. The
pinned image must already be cached: startup uses `--pull never`, preventing
creation delayed by an image download. A fresh
ownership nonce distinguishes even concurrent attempts with the same run identity.
Startup/teardown recheck name, labels, image and full container ID. Uncertain start
failure recovers only that exact owned resource; changed ownership or unverified
cleanup fails closed. No Docker-wide cleanup or existing-container adoption occurs.
The internal supervisor requests fast shutdown at lease expiry and force-stops
its database child after ten further seconds. These process/expiry semantics
remain **unexecuted native debt**, not a guarantee inferred from mocked tests.

The returned `postgres` administrator transport is only for isolated provisioning;
it must never serve application traffic or count as runtime-role proof. Separate
migration/runtime roles, candidate schema installation, guarded application startup,
realistic setup/roles and P01–P12 remain unfinished. No complete launch command is
available. The current deferred policy refuses native resource startup.

Four maintained host-only cases in `programme_database_native.py` cover real
database identity/normal cleanup, body-failure cleanup, live-controller expiry and
abrupt-controller-exit expiry. The last case also cleans its exact resource if
expiry fails. They are outside routine discovery and the eight-worker application
pool, and refuse explicit collection without required policy and opt-in. Under
#102, run them serially on the supported host after restoring policy, record exact
head/environment/results and add their evidence to fixture acceptance. They have
not been collected or executed during preparation. Transport checks cannot replace
native owner-command, schema, runtime-role, recovery or human acceptance.

### Prepared migration/runtime boundary

`programme_provisioning.py` is a test-only current-schema provisioner, not the
complete application launcher. Within a still-live owned transport context it
rechecks resource identity and port, validates actual administrator/database/server
identity, refuses existing migration/runtime roles and generates separate
credentials. Migrations execute through a genuine non-superuser migration login.
The containing resource deadline is unchanged; partial failure requires disposal,
not adoption or automatic repair of an existing installation.

The canonical operations runtime-role SQL is hash-pinned. Only its five example
database-name references become the exact run-scoped database; the reviewed ACLs
are otherwise unchanged. When that source changes, review and deliberately update
the fixture pin rather than silently consuming new grants. Runtime verification
uses its own real login and the existing owner role-safety probe before returning
a credential-bearing endpoint. Its explicit `candidate_schema=True` option adds
the fixture-only migration below between current migrations and unchanged ACLs.
The default remains current-schema-only. Neither mock execution nor configuration validation
is proof that this native check has passed.

Dedicated child settings inherit `maru.settings.base`, never local/test settings;
they preserve exact authority, step-up and closure gates with no test authorizers
or silenced checks. Child environments exclude ambient libpq targeting, provider
credentials and Python/settings overrides. Their in-memory email backend prevents
external delivery and supplies no invitation acceptance evidence. These are
non-serving migration/verification processes, not a candidate application server.

`programme_provisioning_native.py` maintains six host-only #102 cases: current,
candidate-schema and candidate-write provisioning, empty candidate
forward/reverse/reapply, physical-constraint drift refusal and stopped foundation/
worker/application construction. Provisioning variants inspect genuine
runtime/DDL-owner identities, denied runtime DDL, actual constraint/history and
refusal to re-provision existing roles. The candidate variant additionally
checks fresh-child registration, owner catalogs and the continued production
dormancy rejection. All remain uncollected/unexecuted during deferral and must
be run separately after policy restoration. No complete launcher command is
available yet.

### Prepared candidate installation boundary

`programme_candidate_schema_settings.py` is a non-serving, explicit migration
child. It inherits the guarded provisioning settings and uses an Events-only
migration overlay in `programme_event_migrations/`. The overlay discovers every
unchanged owner migration, then appends `0015_isolated_programme_candidate` after
the current `0014` leaf. It registers no application profile, so normal owner
checks still run against the unchanged current profiles; no check is skipped or
silenced. Production migration files/settings remain unchanged.

The atomic overlay extends only the exact profile constraint and field choices
with `programme_operations@1`. Its guard requires tracked required policy,
explicit synthetic scope, actual PostgreSQL 17 database identity and genuine
`maru_migration` session/current user. An exclusive edition-table lock serializes
the empty-database check against writes. Before any forward or reverse schema
mutation it compares the actual validated constraint to a separately literal
reference parsed by the same server, using a transaction-local temporary table;
missing, weakened or unvalidated definitions fail closed. Lock and statement
timeouts bound the guard. Any edition, regardless of profile, fences both
installation and reversal. Once used, dispose the owned synthetic fixture or
fix forward; never fake a migration or rewrite history. Partial provisioning
still requires exact owned-resource cleanup, not a retry/adoption path.

`programme_registration.py` separately prepares explicit pre-model registration
for a fresh runtime child. Import alone is pure; calling it first checks the
tracked policy and isolated runtime environment, rejects previously loaded Events
consumers/models and changed baseline keys/choices/selectors, and preserves both
current manifest objects while extending immutable mappings with the closed
candidate. No route, handler, authority, role or check is changed by this function.
The isolated runtime settings invoke it before model imports. The three owner
dormancy checks remain intact: registration alone is **not** successful startup,
schema proof or acceptance. Genuine setup/role scenarios, native startup evidence
and P01–P12 are still required.

Database-free checks compare the entire migration graph and canonical historical
model state, preserve every unrelated model/constraint, and exercise installation,
reversal, scope, drift, import-order and failure fences with doubles. They do not
prove PostgreSQL DDL or runtime behavior. The six maintained native cases above
remain #102 debt, including five added cases relative to PR #166; populated
owner-command/recovery acceptance also remains mandatory in the complete fixture.

### Prepared guarded application construction

`programme_runtime_settings.py` derives from base settings, never test settings.
It requires the isolated policy/environment and actual runtime process role,
keeps exact provenance, privileged step-up, closure and invitation encryption
required, and admits only the literal loopback host. Synthetic email is retained
in process; it is not external invitation-delivery evidence. No test tokens,
demo payments or silenced system checks are enabled.

`programme_runtime.build_candidate_application()` is the prepared construction
boundary, not a launcher or a command to run during deferral. Before returning
WSGI it checks those settings, installs the explicit candidate privilege contract
below and real candidate internal Effects handlers
while preserving every existing handler, runs isolated compatibility, and demands
actual native readiness. It opens no socket and creates no account, authority,
approval or provenance activation. A future owned runner must call this boundary;
ordinary `runserver` is not the supported fixture entrypoint.

`programme_compatibility.py` invokes every ordinary registered Django check without
changing the registry. Only the exact three known owner functions' exact expected
dormancy results have an explicit alternative contract: the two original immutable
manifests are independently checked as dormant, and the literal candidate is
validated against the real owner catalog. Missing/replaced checks, changed
problem sets, extra messages and any other warning/error refuse construction.
The returned three IDs are reported as explicitly accounted-for dormant checks,
not as passed production checks. Deployment/production transport is not certified.

Programme, Scheduling and Applications' read-only dormancy validators accept
explicit manifest snapshots for that independent baseline inspection. Programme
also accepts explicit declared profile codes and persistence pairs. Their default
arguments and registered production checks still inspect the actual installed
registries; no production profile gains an exemption or new adoption authority.

Native readiness requires the exact run database and actual `maru_runtime` login,
candidate migration history and a validated exact physical profile constraint,
then genuine core health, Programme setup integrity and role integrity. The
declared PG17 constraint expression is **not an observed fingerprint**: native
acceptance must confirm it, and any mismatch fails without normalization. The
maintained candidate provisioning case additionally expects unactivated authority
to refuse startup. That case and positive startup remain unexecuted #102 debt;
database-free doubles prove control flow only. Restore the tracked PostgreSQL
policy through protected delivery after preparation, before any native run.

### Prepared candidate runtime privileges

Canonical production ACLs intentionally leave dormant Programme relations
read-only. `programme_runtime_privileges.py` declares 82 literal candidate tables
and their INSERT, UPDATE or DELETE operations. This is a reviewed fixture contract,
not permissions derived automatically from all installed models or capabilities.
UPDATE includes the owner's actual row-lock requirements, including joined retained
sources; native immutable-history guards still forbid rewriting that evidence.
Only draft call tracks/formats require all three operations. Native execution must
verify the declared boundary and the complete command journey before acceptance.

The closed `candidate_writes=True` provisioning option requires candidate schema
installation. After the canonical ACL and genuine baseline role probe, the grant
plane rechecks the exact live lease, database/admin identity, PostgreSQL major,
candidate migration history, empty edition table and initially read-only targets.
An exclusive edition-table lock prevents racing first use. It grants only the
literal table operations in one transaction, then rechecks resource ownership.
Any partial failure requires disposal of the owned fixture, never adoption/retry.
It changes no production SQL, owner, DDL, function allowlist or grant option.

A fresh runtime child installs five explicit relation-class declarations for the
candidate and calls the **unchanged real native role-safety query** through its
genuine `maru_runtime` login. Installation requires the exact candidate object,
unchanged baseline classes/query/function allowlist and the isolated policy fence.
No probe, result, authorization or native guard is replaced. Startup additionally
denies table/column REFERENCES across current and SET-reachable roles, including
the two candidate tables using the probe's ordinary CRUD class. Six protected
relations remain SELECT-only: migration history, provenance activation and latch,
invitation retention policy, native audit witnesses and Scheduling's native
dependency change journal. Production classes remain unchanged outside this child.

Six host-only provisioning cases include the write-enabled variant and the
stopped-bootstrap/worker/construction path described below. All
three provisioning variants inspect all 82 actual table privilege matrices, real
runtime identity and denied DDL. They remain uncollected/unexecuted under #102.
The installed privilege matrix is necessary, not proof of a working user journey.
The complete fixture still needs native proof of provenance/invitation setup,
real-person role actions, owned HTTPS serving and P01–P12 execution. No successful native
startup or production promotion follows from database-free preparation tests.

Applications retry inspection also retains its shared transaction advisory lock
while reading immutable receipts without FOR UPDATE. This avoids requiring UPDATE
on read-only cross-family receipts; admission and retry collision semantics remain
unchanged. A maintained case in `test_database_role_safety.py` will verify genuine
runtime receipt permissions and the denied old lookup after #102 restoration.
It too remains uncollected/unexecuted, and does not replace full workflow acceptance.

### Prepared stopped foundation and invitation worker

`programme_fixture_material.py` generates ephemeral material only after the tracked
policy/explicit run fence: independent session secret, random bootstrap credential,
RSA-3072 invitation keys and versioned HMAC key. It opens no socket or database.
The frozen configuration declares a future literal loopback HTTPS origin, not
proof of a served/trusted certificate. Web configuration contains only the public
invitation key and required HMAC material. The owner receives the bootstrap
password but no delivery private key; only the separate worker receives that key.
Secret fields are excluded from representation and must never be logged/serialized.
Web construction rejects even empty owner/worker secret variables.

An explicitly fictional one-day retention policy uses jurisdiction `SYNTHETIC`
and approver reference `isolated-fixture-only`. This is not a real controller's
legal retention decision or evidence of human approval. Real policy activation
and worker evidence retain the native database clock. A clock/configuration
mismatch fails rather than backdating native evidence.

The provisioner's optional same-run `fixture_material` requires candidate schema
and writes. After canonical runtime verification, before candidate grants and
before any serving/worker process, a fixed migration-login child invokes
`programme_foundation_bootstrap.bootstrap_stopped_foundation()`. It requires the
exact provisioning settings, isolated run identity, PG17, autocommit and genuine
migration user; rejects private worker keys, weakened controls, invalid loopback
origin, absent candidate history, any account/organization/edition, prior
provenance activation or retained invitation policy. Real key/policy parsers
validate configuration before account creation.

It then calls `AccountManager.create_superuser`, public
`activate_authority_provenance` with the genuine stopped-fixture acknowledgement,
and public `activate_configured_invitation_retention_policy`. Both actual owner
postconditions must pass. It creates no person, Department, edition, role,
representation acceptance or privileged approval on someone else's behalf.
Owners keep their own transaction boundaries; partial failure requires disposal
of the whole owned fixture, never clearing or rewriting evidence to retry.

`programme_invitation_worker.run_invitation_worker_cycle()` prepares one fresh
runtime child. It rejects owner credentials, validates strict candidate settings,
installs candidate declarations/real handlers, and runs complete isolated system
checks. Actual database/session identity, the unchanged runtime-role safety probe
and REFERENCES denial precede any write. It invokes the existing bounded delivery,
expiry and retention commands, which own their real transactions, native-clock
heartbeats and backlog checks; the fixture writes no substitute scheduler rows.
Then genuine full native readiness must pass. In-memory email is explicitly
synthetic transport and provides no external delivery/recipient acceptance proof.

The sixth host-only provisioning case maintains real bootstrap and owner
postconditions, one actual worker cycle and separate secret-free WSGI construction.
It starts no web socket. It and all other native cases remain uncollected/unexecuted
during deferral. Database-free tests exercise real ephemeral cryptographic parsers
and mocked control flow, not native activation or successful startup. The complete
owned HTTPS runner and setup composition are prepared below, but successful native
startup and P01–P12 remain unfinished. There is still no complete journey launcher.

### Owned HTTPS and genuine setup composition

`programme_runner.isolated_programme_application(setup_mode=...)` is an explicit
host-only preparation boundary. It first checks tracked required policy and run
opt-in, reserves a literal loopback port, creates separate ephemeral material, owns
the disposable database, and provisions real stopped foundations/candidate grants.
An actual invitation-worker cycle precedes serving. The optional closed modes are
`new_foundation`, `existing_organization` and `existing_series`; omit the option for
foundation/transport diagnostics without people or editions. This is not a CLI for
the complete P01–P12 journey, production hosting or a human acceptance receipt.

The fixed setup child receives its administrator password only through a dedicated
stdin pipe, not command-line arguments, environment, persistent files or logs.
It constructs the genuinely guarded application before setup, authenticates the
actual administrator and requires an empty organization/edition world with only
the bootstrap account. Partial failure disposes the database; it does not rewrite
immutable evidence or adopt an existing fixture. Three separate synthetic people
use real Identity bootstrap, recipient-specific in-memory verification mail,
single-use challenge consumption and actual password authentication. Verification
flags and challenge tokens are never manufactured. Synthetic mail is not evidence
of external delivery, and direct owner calls are not browser/human acceptance.

Two distinct synthetic controllers accept their own representation invitations
through the owner command before platform activation. New setup creates Maru
operators; existing-organization setup deliberately preserves a fictional existing
Executive Board, while existing-series setup preserves Maru operators. The exact
setup retry recovers the original receipt. Existing root identity, code and version
must remain unchanged. An independently authenticated second controller then
approves two explicit initial recipes: Edition coordination for the first controller
and Department intake for the third ordinary person. No catch-all role, room
permission, review assignment, volunteer or host relationship is inferred.
Further purpose-specific people/roles and cross-edition/organization negatives
remain part of P02–P12 preparation. Separate synthetic accounts do not satisfy #92.

The serving child receives no owner password or worker private key. It binds only
the reserved `127.0.0.1` port, uses a short-lived self-signed server-only certificate
for that IP, TLS 1.2 or later, secure session/CSRF cookies and HTTPS redirects.
Public app static assets are served without exposing media or fixture files.
No Windows/browser certificate trust store is changed. The parent verifies
`/health/ready` with only this fixture certificate trusted, no proxy, no redirects,
bounded response size and every reported dependency healthy before yielding a
handle. Native browser trust interstitials, cookies and rendered journeys are still
unverified; do not bypass browser security or describe mocked tests as a rehearsal.

All phases consume the original monotonic deadline. The web child arms expiry and
parent-pipe EOF self-exit before native readiness, including blocked request/startup
cases. Normal exit/failure closes the owned keepalive, then bounded terminate/kill
fallback precedes temporary certificate and verified database disposal. A controller
crash can leave an expired synthetic certificate directory under `.tools`; remove
only that exact recorded owned directory after confirming no live process. No
other container, listener, database or user's file is adopted or cleaned up.
Explicit `refresh_workers()` runs real delivery/expiry/retention before long
checkpoints; it neither renews the lease nor fabricates heartbeats.

`programme_https_native.py` maintains three host-only #102 scenarios covering all
setup modes, actual HTTPS/native readiness, genuine runtime identity, expected
people/editions and narrow independently attributed decisions. Like the six
provisioning and four transport cases, they remain uncollected and unexecuted
while PostgreSQL is deferred. Policy restoration, measured native budget evidence,
logical recovery #97, integrated #109 and representative humans #92 remain required.

### Real scanner prerequisite

The optional `with_scanner=True` runner preparation supplies the real dependency
required by P02/ADR 0104. It uses a cached immutable official ClamAV 1.5.4 image,
an owned internal bridge, loopback publication and an independently expiring,
non-root/read-only resource-bounded daemon. There is no test-clean implementation,
external endpoint, persistent host data or automatic image/signature download.
Actual bounded PING/VERSION evidence requires the pinned engine and signatures no
older than seven days; every PDF still passes through the unchanged owner scanner.
An old pin must be deliberately refreshed and verified, not accepted through a
stale-signature exception. Budget 4 GiB for the daemon plus the database/application.
Normal cleanup verifies exact nonce/IDs and empty network; controller-crash recovery
may need removal of that exact labelled empty network after auto-expiry, not pruning.

Both fixture transports now require a recognized stable Docker engine version 28
or newer and pin commands to the inspected local endpoint. This prevents the older
localhost-publication exposure and a concurrent default-context switch. These
preconditions change no Docker configuration or unrelated resources. One host-only
`programme_scanner_native.py` actual daemon/public-preparer case is maintained but
uncollected/unexecuted. See the
[scanner checkpoint](../checkpoints/2026-09-18-programme-real-scanner-preparation.md)
for source metadata, limits and unverified native debt.

### Scenario people and sessions

Use repository-owned fictional convention names, synthetic people and reserved
example domains. Do not copy an actual convention roster. Provide one primary
organization with two editions and a second organization to exercise isolation.
The setup scenarios must cover a blank foundation, existing organization and
existing convention series. Reset scenarios in isolated databases rather than
rewriting immutable history to reuse one world.

| Session | Purpose and separation |
| --- | --- |
| Platform administrator | Provision foundations; never become a controller, member, host or volunteer. |
| Two accountable people | Accept their own invitations in separate sessions; reuse truthful existing representation where present. |
| Programme organizer | Configure a call or core item, readiness and deliberate host invitations. |
| Proposal lead and collaborator | Independently own profiles/consent and acknowledge the exact sealed proposal. Neither is automatically a host. |
| Reviewer, moderator and decision maker | Exercise exact assignments, field ceilings, recusal and independent decisions. |
| Planner, Venue owner and release approver/publisher | Use separately admitted owner tasks; preserve every required independent approval. |
| Volunteer and Workforce organizer | Own claim versus independent confirmation; neither becomes an attendee. |
| Room/Department operator, outsider and anonymous reader | Prove each output ceiling and denial, not just organizer success. |

Give each participant a role card with a goal, entry link and fictional inputs,
but no hidden identifiers or explanation of how to pass. Distinct sessions are
not themselves evidence of representative humans: #92 requires actual people.
Where one synthetic account holds several purposes, test each purpose separately
and prove one relationship does not silently grant another.

## Journey checkpoints

All rows below start **not run**. Record results against the exact candidate;
do not inherit a pass from a component PR. Repair failures through the owning
module and replay affected checkpoints, including downstream consequences.

| ID | Task | Required observable evidence |
| --- | --- | --- |
| P01 | Establish accountable setup | Blank/reused foundations, first Programme Department, two genuine-person acceptances, safe incomplete setup, no platform-administrator subject or excluded product state. Exact retries do not duplicate foundations. |
| P02 | Open a call and collaborate | Labelled call discovery, typed answers and private supporting file, independent collaborator profile/consent, seal/acknowledgement, submission and revision history without an attendee relationship. |
| P03 | Review and decide | Assigned field-limited reviewer access, conflict/recusal, moderation and accountable decision; no anonymous identifying lookup or private review leakage to hosts. |
| P04 | Prepare accepted and core items | Exact acceptance converts once; organizer-created core items need no fabricated submission. Readiness, working/delivery/discussion/public layers and host confirmation remain distinct. |
| P05 | Plan a timetable | Service days, occurrences and alternative drafts; explain room/combination, availability, capacity, setup/teardown, host, accessibility, staffing, overlap and rest conflicts. Pointer, keyboard and explicit forms preserve the same versions and commands. |
| P06 | Staff the work | Explicit demand becomes a Workforce-owned Shift; volunteer claims, another organizer confirms, and coverage locks. No other volunteer's private data or Participation is created. |
| P07 | Approve and publish | Current owner evidence, independent approval and atomic publication. Preparation failure leaves the prior release intact. Public, personal, room, Department, API, calendar and print outputs identify the same release. |
| P08 | Change published work | A reasoned successor retains history and previews retained work impact. Existing claims/confirmations are not silently rewritten. Notice preparation, independent review, manual handoff, failure and exact-recipient acknowledgement remain separate. |
| P09 | Operate on site | Now/next and run sheets expose only authorized current instructions and immutable release facts. Print includes scope, version, time zone and freshness/expiry warnings. No check-in or actual-time claim is inferred. |
| P10 | Lose connectivity or a dependency | Fail closed on partial/unavailable sources; use only the bounded read-only fallback. Independently trusted packs, expiry, newer withdrawal, lost history, reconnection and disposal behave as documented. |
| P11 | Export, recover and stop | Retain authorized history and archive evidence; restore a mutually consistent database/artifacts through #97's supported procedure and reauthorize reads. Stop-use prevents new work/access as contracted without erasing required evidence. |
| P12 | Verify isolation and excluded effects | Cross-organization/edition/role/object/field attempts disclose nothing outside scope. Compare owner-controlled baseline and final state/effect inventories: no Registration, Participation, payment, attendance, accreditation, catalog, charity, Logistics or general Communications side effects. |

P12 is an assertion at every relevant checkpoint, not just a final count. Absence
of a navigation link does not prove absence of writes, authority, jobs or effects.
Include wrong-tenant direct requests, revoked authority, stale versions, exact
retries, unavailable dependencies, rollback and empty/overflow responses. Retain
both positive and denial/audit evidence without logging private answer contents.

## Human and accessibility session (#92)

Prepare a short participant script from P01 through P11. A representative organizer
and distinct host/volunteer must complete their own tasks without developer
narration. Record misunderstanding as a defect, not a pass after explanation.
Ask participants to explain private versus public content, incomplete readiness,
approval versus publication, retained Shift commitments, and fallback freshness.

Rehearse the newly connected paths with a representative screen reader, keyboard
and visible focus, semantic labels/errors/status, native discard/leave dialogs,
and genuine browser 200% zoom. Include empty, validation, denied, stale,
dependency-failure, review, release, read-only and degraded states. Check relevant
surfaces at 320, 390, 768, 958, 1024, 1280 and 1920 CSS pixels, long content,
print pagination and scope warnings. CSS widths are not native zoom evidence.
Automated accessibility scans complement, but never replace, these observations.

Reuse valid unchanged #87 observations. Recheck only materially changed paths and
record why. Preserve the maintainer's disabled Windows Animation effects; do not
change personal browser/OS settings without permission. Include #92's notice,
private-file and continuity follow-ups and obtain independent operational-owner
acceptance. Assistant-operated synthetic roles cannot supply this acceptance.

## Evidence record and completion

For each checkpoint retain: candidate commit, fixture/environment identity,
role/session purpose, initial state, exact action, expected result, observed
result, pass/fail/not-run, evidence location and linked defect. Record adapter
substitutions, source versions, release identifiers and fixture limits. Do not
put passwords, invitation tokens, signing keys, private files or raw personal
answers in public issues, logs or screenshots.

Use separate evidence labels:

- **Preparation:** protocol, fixture implementation or assertions exist; no execution implied.
- **Component:** isolated or mocked checks; no native or integrated acceptance implied.
- **Native automated:** exact-head PostgreSQL reports and unchanged coverage/timing gates under #102.
- **Recovery:** supported logical restore plus weakened-guard negative tests under #97.
- **Human:** observed representative-person/screen-reader work under #92.
- **Integrated:** complete joined evidence and failure/recovery/stop-use proof under #109.

Protect failed-attempt records and relate repairs to their tested revisions. A
later commit needs fresh appropriate evidence; do not copy an earlier receipt.
After the session stop only verified fixture-owned processes/resources, dispose
of private synthetic downloads according to the fixture recipe, and verify
unrelated worktrees, containers and browser preferences are untouched.

Close #109 only when its native, recovery and human prerequisites and this joined
journey pass. Then deliver #108's separately verified profile promotion through
the protected PR flow. Close #48 only after its complete delivery decomposition
and integrated checklist are supported by evidence. This protocol, a green
documentation PR, or successful component tests complete none of those gates.
Production infrastructure, provider provisioning, privacy/safeguarding, training
and operational go/no-go remain separate from repository Programme completion.
