# Shared every-page Access and preview

Date: 2026-08-09

Maru now has one disclosure-safe page Access contract instead of page-local
sharing state. The administration, baseline management, and registration
shells mount the same component. It computes organization, edition, exact
Department, and registered typed-resource targets from persisted scope and
shows a contextual **Manage access** action only when the current account may
manage the canonical person/immutable-role assignments.

Fixed platform, self, public/attendee, representation, safeguarding, and
security policies explain their audience and intentionally omit mutation.
Attendee and public are never rendered as staff roles. Named relationship
reads require current scoped authority and append minimized security-retained
audit evidence.

The signed, no-store workspace supports exact-person and immutable-role
preview. Preview remains a policy simulation: it preserves the real session
principal and audit actor, caps detail by the viewer's own disclosure ceiling,
shows a persistent read-only banner, and removes mutation controls. POST
assignment/revocation independently rejects preview-shaped inputs and evaluates
the real principal.

Verification completed:

- Ruff passed all new Access resolver, form, view, workspace, template-tag,
  and focused test files.
- Root URL import/reverse, all five mounted templates, and raw UTF-8/mojibake
  assertions passed.
- `tests/integration/test_page_access_experience.py`: 6 passed in 7.24s on
  PostgreSQL, covering mounted page families, exact Department resolution,
  fixed policies, signed-token tenant/tamper denial, audited named reads, both
  preview modes, closed inputs, and real-principal mutations.

Future typed-resource modules must add a deterministic binding resolver before
the component offers access mutation. New shells should mount the stable
template tag rather than creating a local access summary or ACL.
