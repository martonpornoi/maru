# ADR 0020: Guided bootstrap and localized data entry

- Status: Partially superseded by ADR 0022 (web first-authority adapter only)
- Date: 2026-07-29
- Requirements: IDN-001, IDN-002, IDN-007, EVT-001, EVT-005, AUD-001,
  AUD-002, REG-001, REG-008, REG-012, REG-021, UX-003, UX-005, UX-006,
  NFR-001, NFR-003

## Context

The first clean-database rehearsal exposed several avoidable operator errors.
Language and time-zone values were free-form technical strings, the tenant
meaning of Organization was easy to confuse with the public Convention Series
brand, establishing first authority required a carefully quoted PowerShell
command, draft registration items could be added but not removed in admin, and
staff-assisted intake stopped when the attendee email had no prior account.
Telephone fields also expected the attendee to know how to type a usable
international number.

These are data-entry and bootstrap problems, not reasons to weaken domain
validation or create parallel workflows.

## Decision

### Organization, series, and edition meaning

Keep the three-level model:

- Organization is the independently governed tenant and accountable organizer.
- Convention Series is a recurring public convention brand owned by exactly
  one organization.
- Event Edition is one dated operational occurrence of that series.

Organizations store legal/public identity, contact, country, multiple default
languages, and time-zone suggestions. Series store their public description,
contact, and website. An edition continues to own its actual dates, locale,
currency, lifecycle, and operational records.

### Code-backed localization

Persist ISO 639-1 language codes, ISO 3166-1 country codes, and IANA time-zone
identifiers. Generate human-readable choices from code-owned reference
libraries:

- pin `en (English)` as a common convention default;
- allow several organization defaults;
- group languages by broad discovery region without claiming that a language
  belongs exclusively to one continent;
- show time zones with current January/July UTC offsets so daylight-saving
  behavior is visible while the IANA identifier remains authoritative; and
- show telephone regions as initials, flag, international prefix, and country
  name, then normalize possible numbers to E.164.

Dropdowns and search reduce error but do not replace server validation because
imports, APIs, and crafted requests bypass HTML controls.

### Web first-authority adapter

Expose the existing one-shot workforce-bootstrap service through a superuser-
only, password-confirmed admin form. The logged-in superuser is the controller,
so the browser does not ask an operator to retype its email. The form requires
the organization, matching non-closed edition, distinct active Chair account,
reason, exact organization slug, and current controller password. It delegates
to the same transaction and fail-closed empty-authority checks as
`bootstrap_convention`; the management command remains an operator fallback.

### Draft removal

Allow deletion of inline sections, questions, and products only while their
configuration or template is draft. Published templates, active
configurations, submissions, products with history, and financial evidence
retain their existing immutable/versioned behavior.

### Staff-created account

Staff-assisted registration exact-matches an active account by normalized
email. If no account exists, the authorized staff actor must explicitly
provide a display name and policy-valid temporary password after seeing the
new-account warning. Maru creates the unverified account, participation,
registration, profile, deadline, timeline, and audit evidence atomically. An
inactive or raced existing identity is never replaced. The ordinary
restriction, eligibility, capacity, price, payment, and duplicate rules still
apply, and a paid ticket remains payment pending.

## Consequences

Operators can complete ordinary first-convention setup after the initial
environment and superuser setup without PowerShell. Stable stored codes remain
portable while labels can improve independently. Organization and Series stay
separate because governance and public-brand continuity have different
lifecycle and access meaning.

The language grouping is an aid, not geographic truth. UTC is the offset
standard shown to operators; IANA identifiers, not a fixed `GMT+1` string, are
stored because they preserve regional clock-change rules. New staff-created
accounts need a future invitation/password-setup delivery workflow before this
temporary-password rehearsal experience is considered production-complete.

## Alternatives considered

- Merge Organization and Convention Series: rejected because an organizer may
  govern several brands and governance changes must not rewrite edition-brand
  history.
- Store friendly time-zone labels: rejected because labels and current offsets
  change, while IANA identifiers preserve rules.
- Trust dropdowns without validation: rejected because non-browser clients can
  submit arbitrary values.
- Reimplement bootstrap in the view: rejected because it would split safety,
  audit, and one-shot behavior from the tested application service.
- Let staff silently create any missing account: rejected because identity
  creation needs visible intent, password validation, exact-match behavior,
  and separate audit evidence.
- Delete active form items: rejected because it would corrupt submitted schema,
  eligibility, price, and financial history.
