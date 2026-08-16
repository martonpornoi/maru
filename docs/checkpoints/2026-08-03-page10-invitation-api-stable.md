# Page 10 invitation API stable

Date: 2026-08-03

This checkpoint records the completed and independently reviewed versioned API
surface for Page 10 platform accounts and account invitations. It does not
activate production invitation delivery or remove the remaining retention,
writer-cutover, deployment, or partner-approval gates.

## Outcome

- `GET /api/v1/platform/accounts` exposes one audited, bounded, minimized
  account inventory with strict search, kind/state filters, signed cursor, and
  page-size contracts.
- Platform invitation create, audited detail, reissue, and revoke use the same
  canonical command/query boundary as HTML. Mutations require one canonical
  lower-case UUID `Idempotency-Key` header and reject retry metadata in JSON.
- Public acceptance treats the bearer challenge as its only authority and
  ignores ambient session cookies. It accepts no secret in a URL, remains
  non-enumerating, and lets only the recipient choose the password.
- Authorization and required step-up occur before protected query, header, or
  body parsing. Sensitive account labels are released only after the read audit
  succeeds.
- Inputs and outputs are closed in OpenAPI. Errors use RFC 9457 problem details,
  no-store responses, stable codes, exact-origin CORS, and code-owned password
  guidance. Arbitrary deployment password-validator messages and exception
  causes cannot be reflected to the caller.

## Verification

- Fresh PostgreSQL invitation API suite: 42 tests passed.
- Adjacent command, query, API, problem-handler, CORS, and input-normalization
  suite: 135 tests passed.
- Independent adversarial verdict: `STABLE` after adding the missing inventory
  route and eliminating validator-message reflection.
- Ruff, formatting, strict mypy, and whitespace checks passed.
- OpenAPI validation reported zero errors. Seven enum-component naming warnings
  in the combined uncommitted Page 10 schema remain cleanup work, not runtime
  ambiguity.
- Documentation validation passed with 184 Markdown files and 198 unique
  requirement identifiers.

## Still open

- Invitation retention v7, supervised production schedules, delivery keys and
  provider certification, stopped-writer cutover, runtime-role transition,
  representative restore/PITR and load evidence, authenticated responsive and
  accessibility evidence, and owner rehearsal remain required.
- Registration preview/activation and compatibility-writer reconciliation are
  separate Page 10 stages.
