# ADR 0018: Attendee directory labels and reporting preset

Status: Accepted  
Date: 2026-07-29

## Context

ADR 0012 intentionally kept address country, admission product, price, and
payment out of the public attendee rendition. Organizers nevertheless need an
accessible public indication of attendee level, while registration and badge
teams need a quick answer to questions such as how many confirmed people are
coming from each country and a minimized file for badge preparation.

Using the address country in public would change its purpose without consent.
Letting an attendee type their own sponsor or volunteer status would make the
directory contradict authoritative registration and participation records.
Giving report users raw model access or a database export would expose more
personal and financial information than the task requires.

## Decision

- A profile may hold an optional two-letter `directory_country_code` collected
  only beside the edition's public-directory consent. It is not copied from the
  address, not included in a later-edition suggestion, and is cleared when
  consent is withdrawn or an applicable restriction hides the directory row.
- Existing directory consent does not silently expand. Country and
  authoritative attendee labels appear only under the new consent version.
- Public attendee labels are derived from current admission entitlements and
  active or proposed participation capacity. The public projection uses broad
  labels—attendee, sponsor, super sponsor, guest, and volunteer—and never
  exposes exact product, price, payment, legal identity, or address.
- Labels always include readable text. Color is a redundant semantic cue, not
  the sole representation.
- Registration staff receive a separate edition-scoped reporting preset under
  `registration.view_attendee_reporting`. Its population is confirmed and
  checked-in registrations. It reports internal registration-country counts
  and minimized badge fields, and supports search, country, attendee-level,
  and bounded pagination filters.
- The CSV uses the same trusted projection and filters, records edition and
  generation metadata, neutralizes spreadsheet formulas, and is audited as a
  sensitive read. It excludes payment detail, legal name, full address,
  contact, emergency contact, form answers other than a purpose-identified
  badge name, and internal comments.
- Synchronous reporting is limited to 5,000 source rows. Larger editions must
  use the future asynchronous export pipeline with execution/download
  reauthorization and expiring artifacts.
- The export prepares data; badge layout, printing, stock custody, and reprint
  workflows remain separate accreditation/fulfilment work.

## Consequences

The public page can show country and convention status without reusing a
restricted address field or accepting self-asserted benefits. Organizers can
answer common attendance questions and hand a reproducible, minimized CSV to
an authorized badge workflow. A new profile migration, consent version, policy
field, capability, audit path, and test/demo data are required.

The first report is a code-owned preset rather than the general safe query
builder described in the reporting architecture. It must not become an excuse
for adding arbitrary fields or joins. Large exports, saved reports, XLSX,
layout versioning, and physical fulfilment remain future work.

## Alternatives considered

- Publishing address country was rejected because its collection purpose and
  audience differ from the public directory.
- Asking attendees to choose sponsor or volunteer status was rejected because
  those facts belong to entitlements and participation.
- Reusing the full staff registration dossier or an admin database export was
  rejected because badge preparation does not require its financial,
  restricted, or internal-comment fields.

## Requirements affected

REG-009, REG-012, REG-013, REG-016, QRY-001, QRY-004, QRY-005, QRY-006,
QRY-007, QRY-008, UX-001, UX-003, UX-007, UX-008, UX-009.
