# Programme notice schema-only observation and dormant preview

Date: 2026-09-13. Local work on `codex/programme-change-communication`, based on
protected PR #106 / `1f4ea840d25ed2571dbc78052398f1cd9c612f70`.
This records an intermediate #104 boundary, not a separate delivery item,
completed #104, certification, protected merge or Programme activation.

## Narrow execution authority and result

The maintainer explicitly allowed a bounded disposable schema-only migration
and metadata check while retaining ADR 0100's PostgreSQL test-suite deferral.
The check used fresh synthetic database `maru_issue104_schema` in exact container
`maru-issue104-schema-20260913`, ID
`2a9693d808d9734d401760cb2f1e12934c2d1bcfdefbffbd83fced140e9a31b5`,
with disposable/task labels, loopback port 62050 and tmpfs-only database storage.
Image: `postgres:17.11-alpine` pinned to
`sha256:18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73`.

Fresh forward migrations through Scheduling 0022 succeeded in **153.578s**;
the metadata collection completed in **153.609s** total. Exact Scheduling schema
catalog comparison returned true. Native metadata checks returned true for
installed relations, required migrations, source contracts, function definitions,
trigger definitions, function/relation ownership and closed owner-only execution.
No test suite, feature workflow, runtime provisioning, populated recovery or
database-certification command ran.

After inspecting its exact ID, labels and tmpfs mount, the task stopped that
container and its `--rm` lifecycle removed it. Only this disposable empty schema
database was discarded; existing containers were untouched. Local ignored logs
remain in `.tools/issue104-schema-metadata.log` and
`.tools/issue104-schema-metadata-verification.log`. The schema collection and
verification scripts remain alongside them for provenance, not certification.

## Observed metadata and source distinction

Changed relation fingerprints:

- `scheduling_schedulingchangenotice`:
  `03dff3e21873790c372bb6f8b14a59eeede1e6d54709dc8bbb4e94c592f52033`.
- `scheduling_schedulingchangenoticeevidence`:
  `2808e91ea662e17dd44a4a6021d659639f63c497beb83722da36d073b79c1f22`.
- `scheduling_schedulingcommandreceipt`:
  `f780a30dd23c8bd3b703fb8bd964a1c1d37ca36127620556bbd3af5e84c99c04`.

The native capability-floor function fingerprint is
`7e7d5042e16b12d8792da14e5871a5a52663c2491bf336db01711e063e9b5d3a`.
Scheduling 0021 source SHA-256 at execution and at this checkpoint:
`f69449e859b1f67fd664a4f5697b06384cdd6f21bea9345402f0760a6d22937f`.
Scheduling 0022 source at execution:
`5cd83ba0e8b2e90c6a81b36fd1fbed8b6a8d4813545eccf144a2282c29ded4bc`.
Its subsequent Python downgrade fence was extended to protect retained notice,
operator-authority and prior release history before any successor guards are
removed. The forward SQL was unchanged. The current source pin is
`bcdda00256d8955799ed4a6015c9f944d51ac4119bd943e3f20b8ff292b81918`.
The observed forward metadata is not evidence that those later reverse-fence
paths ran on PostgreSQL; their real reverse/reapply tests remain unexecuted.

## Local implementation and non-database evidence

The dormant tables retain immutable scoped notice/evidence references and bind
the existing receipt, audit and minimized event stream. They remain runtime
SELECT-only and unpinned by current profiles. Native lifecycle/scope/receipt
guards, exact readiness catalogs, provisioning examples, historical inventory,
privacy ownership and ADR 0102 are updated together.

The sender preview independently admits notice fields and current owner purpose,
composes only one affected occurrence and repeats its source before audit and
disclosure. It never invokes personal reads as another actor. Exact current or
latest-withdrawn publication, purpose and complete dependency generations bind
the fingerprint; suppression returns no old content. Internal genuine-self
composition has matching fingerprints, but no personal notice entrypoint is yet
exposed. Unit checks cover host/work/operator symmetry, attribution, moving and
incomplete sources, suppressed content, malformed selection and final denial or
audit failure. Real operator preview assertions reuse existing synthetic
integration fixtures but were **not executed**.

- Full units: **5,472 passed**, two existing URLField warnings, **35.96s**.
  Report: `.tools/issue104-notice-source-all-unit-final.xml`.
- The preceding run had 5,471 passes and one missing diagnostic timing-inventory
  entry. That entry now uses the existing **29.955s median estimate**, explicitly
  not a measurement. Active group costs and provenance were not modified; new
  authoritative groups retain the conservative unknown-group fallback.
- Strict types: 572 source files. Ruff and focused docstrings pass.
- Semantic documentation: 593 source files. Documentation structure passes.

These are focused development checks, not an exact-commit full certification.
PostgreSQL workflow, rollback/race, weakened-metadata, reverse/reapply and runtime
cases remain maintained #102 verification debt. Logical restore #97, human
acceptance #92 and integrated proof #109 remain mandatory.

## Remaining #104 work

Implement persisted preparation, independent review, manual handoff and exact
recipient acknowledgement, protected personal notice queries and same-shell
surfaces. Mutation composition must serialize its final source-generation
observation after complete owner/person locks and revalidate current purpose and
source on exact receipt replay. Existing generic replay is not sufficient.
Do not mount a notice writer or close #104/#48 on this supporting increment.
Continue #48's visible delivery decomposition before unrelated improvements.
