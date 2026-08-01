# Legacy Maru capability map

Status: Consolidated behavior reference
Last updated: 2026-08-01
Decision: ADR 0021

## Source reviewed

Two read-only sources were inspected:

1. private GitHub `martonpornoi/maru`, whose `main` branch ended at
   `462e7ba1ba09128fa628c5fb05ecb5dcb817e302`; and
2. `C:\Users\TheMw\Desktop\pretalx\maru`, based on the same commit with newer
   uncommitted code, migrations, templates, and tests.

The local delta included a volunteer hierarchy, visual timetable days and
layers, project archive snapshots, project-scoped social posts, and extensive
interaction tests. It remains a reference only. No legacy Python, model,
migration, template, database, or personal/runtime media was copied.

## Capability disposition

| Legacy behavior | Current requirement or decision | Disposition |
| --- | --- | --- |
| Gmail allowlist, global roles, project role presets | IDN-001 through IDN-008, ADR 0003 | Do not port. Current verified identity and scoped authority are stronger. |
| Project and subproject setup | EVT-001 through EVT-005, REG-001, PRG-001 | Translate to organization-owned series and editions with typed domain configuration. |
| Repeatable YAML project import | EVT-003, INT-005 | Retain idempotency, provenance and original source labels; add validation, mapping, preview, duplicate policy and reversible staging before applying. |
| Google-style forms and copied drafts | REG-001, REG-002, KNO-004, KNO-005 | Current registration copy-on-write is stronger. Reuse the draft-copy interaction for future generic and programme forms. |
| Versioned application reopening and review | PRG-001 through PRG-006, AUD-003 | Preserve every submitted revision, accountable request and decision; derive public programme data separately. |
| Approved applications becoming panels | PRG-005 through PRG-007, SCH-001 | Implement as an explicit application-service transition with readiness work, not an admin/model side effect. |
| Timetable visibility rounds | SCH-004, SCH-008 | Preserve staged internal review and publication using immutable schedule versions rather than a mutable global enum. |
| Service days, layers, recurrence, groups and print | SCH-001 through SCH-008 | Carry forward explicit day windows, precision, layer order/visibility/locks, group order, recurrence and shared projections. |
| Room and person conflict warnings | SCH-001, SCH-003, SCH-007, VEN-008 | Include people, room availability, setup, travel, rest and resource constraints; reasoned override cannot bypass hard safety. |
| Volunteer capacity, claim, confirm, remove and lock | HR-009, SCH-003, SCH-005 | Implement transactional demand and commitment states with self-only privacy and authoritative work records. |
| Persistent hotels, rooms, combinations and floor plans | VEN-001 through VEN-008 | Reuse stable venue facts through explicit edition selection and independent local overrides. |
| User directory tiles with attendee and volunteer colors | IDN-003, REG-016, UX-007, UX-010 | Current public directory uses authoritative multi-label chips. Keep multiple simultaneous labels and text; constrain future custom palettes. |
| Statistics by country and attendee type | QRY-001 through QRY-008, ADR 0018 | Already implemented more safely with separate public country and minimized badge export. |
| Social drafts, schedule, immutable versions and delivery rows | ANN-001 through ANN-006, INT-003 | Retain canonical content, approval, schedule, adapter isolation and per-channel evidence; ordinary registration grants no publishing authority. |
| Token-scoped timetable, profile, shift and signage JSON | INT-001 through INT-004, INT-008, QRY-007 | Implement typed, expiring, rotatable credentials and minimized projections. Avoid routine secrets in URLs. |
| Token rotation, one-time display, health and access logs | INT-003, INT-008, AUD-001 | Retain as required operational behavior with credential vaulting and safe telemetry. |
| Read-only closed-project snapshots | ARC-001 through ARC-005, REG-020 | Current closure manifest and archive gates are stronger. Never freeze unnecessary email, notes or sensitive media merely for convenience. |
| Account CSV import preview and rejected-row download | INT-005, QRY-005, QRY-007 | Reuse preview and all-or-nothing safety where identity import is approved; do not revive an email allowlist. |
| Edition-aware sidebar context | UX-001 through UX-009, ADR 0008 | Preserved in the pre-reset `/admin/` shell, embedded Convention work, and specialist records; ADR 0039 is reusing this grammar in the unified shell, with current verification still required. |
| Demo journeys with hosts, volunteers and scheduled work | NFR-001 through NFR-003, OPS-008 | Extend the synthetic fixture when each owning module ships; never use production personal data. |
| Navy, gold and ivory identity assets | UX-010, FUR-010, ADR 0021 | Adopted for Maru platform surfaces with accessible tonal scales. |

## Accepted interaction details for future work

### Programme and schedule

- A proposal retains source-form version, each submitted revision and decision.
- Grouped or recurring sessions retain stable group identity, intended order,
  recurrence meaning and independent occurrences.
- One approved schedule version feeds room, person, attendee, volunteer,
  signage, API, calendar and print projections.
- Visibility and layer locks are explicit versioned publication controls.

### Workforce shifts

- Required headcount is separate from claimed, confirmed, removed and completed
  commitments.
- Self-service suitability explains qualification, availability, overlap,
  breaks, capacity and lock state.
- Volunteers see their own state; coordinators see only the fields needed to
  staff and supervise the work.
- Removed assignments remain historical evidence and immediately free future
  capacity when policy allows.

### Venues

- A reusable room does not imply that every edition uses it.
- Edition selection creates local naming, opening, blocking and availability
  state without rewriting the source property.
- Combined spaces declare their component rooms and cannot be scheduled
  independently at conflicting times.
- Floor-plan files are versioned governed references, not arbitrary public
  uploads.

### Announcements and read projections

- A canonical announcement survives connector failure or removal.
- Published content retains the exact approved version and per-destination
  delivery result.
- Website and signage access is least-privilege, expiring, rotatable,
  revocable, observable and separately scoped by projection.
- Public schedule and profile output derives from approved publication state,
  never private proposal, contact, HR or authority records.

## Rejected assumptions

The following legacy assumptions are not carried forward:

- Gmail-only authentication or an email allowlist as authorization;
- SQLite as the production-shaped database;
- one global `Project` as both tenant and edition;
- cross-domain writes hidden in model saves or Django admin;
- arbitrary hex colors without contrast and text meaning;
- URL credentials as the normal integration contract;
- archives containing unnecessary account email, notes or private profile data;
- user-visible labels as stable permission or database identifiers; and
- outbound publication authority granted merely because a person can sign in.
