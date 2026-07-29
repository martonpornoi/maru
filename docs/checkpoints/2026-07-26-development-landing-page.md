# Checkpoint: Development landing page

Date: 2026-07-26  
Phase: Platform foundation V02  
Related requirements: NFR-002, UX-001

## Outcome

The local root URL now renders a small, accessible development landing page
instead of Django's debug 404. It confirms that the backend is running and
links to readiness, the OpenAPI contract, and bootstrap administration.

## Boundary

This is an operational first-run page, not the attendee or staff application.
Those frontends remain separately deployable products as required by ADR 0001.
The page does not query or expose tenant, account, audit, or event data.

## Verification

- root response is HTML and status 200;
- readiness, schema, and admin links are present;
- Ruff and strict mypy pass; and
- focused view tests pass.
