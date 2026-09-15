# Programme readable typed review answers

Date: 2026-09-15. Partial implementation of #108's structured-answer outcome
within #48. Base: protected PR #129, `9f7aed18bf26bd62883fe2502e6fead210b60ca6`.

## Outcome and boundaries

Reviewer, moderator and decision-maker answer pages share one bounded plain-text
presenter. The owner adds only selected code/label pairs from the exact sealed
question, in retained selection order, using the already eager-loaded relation.
It does not read a current call schema, project unselected options or resolve
identities. Addresses have labelled components; optional empty components are
omitted. Absent answers, explicit empty selections, false and zero are distinct.
Temporal values retain explicit offsets without timezone inference. Email, phone,
HTTPS and free text remain escaped, non-actionable content. Unknown types,
malformed values and incoherent selected metadata fail the entire prepared answer
page rather than returning raw objects, invented labels or partial content.

Exact tenant/edition/seal, role/assignment, stage question allowlist, structured
anonymity, independent sensitive-read admission, mandatory audit and render-time
reauthorization remain unchanged. Person/domain/file references remain protected
placeholders. Their separate authorized selectors/viewers are still #108 work;
this increment cannot complete that whole checkbox. No migration, canonical
writer, permission catalog, profile, production route or CI policy changes.

Requirements PRG-003/006, QRY-005 through QRY-008, AUD-001 and UX-005 through
UX-008/029; ADR 0085 is refined without reversal. ADR 0100 continues native
deferral. Requirements, three page contracts, module/recovery documentation,
CHANGELOG and CURRENT are updated together.

## Verification at this checkpoint

- Complete database-free preflight: 7,454 passed in 45.48s with three existing
  Django URLField warnings. Focused suite: 288 passed in 2.77s. Focused Ruff,
  strict typing and NumPy/semantic docstrings passed. Early preflight fixed two
  oversized/unencodable pytest parameter IDs and an old fixture's unsupported
  `text` kind (canonical kind is `short_text`); no production type was removed.
- Pure and real-template tests cover every supported kind, bounds, malformed
  values/metadata, false/zero/absence, exact option order, escaped text, no unsafe
  links or protected payloads, whole-page unavailable behavior and all three role
  consumers. Owner tests preserve exact query binding, stage/anonymity filters,
  eager loading, extra sensitive admission, non-answer exclusion and mandatory
  audit failure. These isolated tests do not prove native SQL execution.
- Database-forbidden synthetic browser used actual views/templates/CSS/JavaScript
  and stub authority/owner queries. Readable choice/address output, retained order,
  false/zero/absence, escaped content, explicit offset and protected placeholders
  were observed in all three role pages. Each had one H1/main and no page-level
  horizontal overflow at 1280 CSS pixels. Reviewer screenshot visually inspected.
  Malformed address yielded each role's generic unavailable response without
  earlier answer content. An initial fixture omitted classification metadata and
  failed before the intended shape check; corrected fixture then passed. No
  claim of native query, persistence, full responsive, zoom, keyboard or screen-
  reader acceptance. Owned tabs and servers were closed/stopped.
- Two existing parametrizations of the native structured anonymity scenario now
  retain a real multiple-choice answer and assert exact original selected labels,
  selection order and absence of unselected labels alongside existing anonymity
  assertions. No extra native scenario, file, writer count or timing weight;
  neither collected nor run. This remains #102 debt under ADR 0100.
- Clean exact-commit canonical certification and protected hosted acceptance are
  pending. Later evidence must identify its actual head; preflight is not a
  certification receipt or permission to merge.

#108 and #48 remain incomplete. Complete the recorded authorized selectors/viewers,
connections and accountable setup next. Integrated journey #109, native/full
coverage and measured budgets #102, logical recovery #97 and genuine human matrix
#92 remain mandatory final gates before promotion.
