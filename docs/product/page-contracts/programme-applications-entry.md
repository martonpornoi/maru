# Find Programme calls and review tasks

Status: dormant #108 implementation contract. Owner: Applications.
Requirements: PRG-001, PRG-003, PRG-006, NFR-013, AUD-001, AUD-003,
UX-006, UX-007, UX-019, UX-020, UX-027 and UX-029.
ADRs 0082, 0085 and 0100 remain unchanged.

## Purpose, route and independent authority

From an already selected exact organization/edition, an active verified person
can choose a labelled current Department and an independently admitted owning
task without knowing its database identifier. The reserved entry is
`/admin/applications/programme-calls/{organization_id}/{edition_id}/`.
It remains unmounted in production and absent from both current profile menus.
Final shared-shell registration and accountable setup remain separate #108 work.

| Task | Exact Department capability after `applications.` | Requested fields |
| --- | --- | --- |
| Manage calls | `manage_programme_calls` | None |
| Set up review | `manage_programme_review` | `review_setup` |
| Manage reviewers | `manage_programme_review` | `review_context` |
| My assigned reviews | `review_programme` | `review_context` |
| Moderate reviews | `moderate_programme_review` | `review_context` |
| Make decisions | `decide_programme` | `review_context` |

No sibling capability, broad staff flag or Workforce structure permission grants
entry to another task. Review setup and manager context are separate field
ceilings. Own assignments, conflict clearance, independent moderator/decider
eligibility and sensitive-answer authority remain destination-owned checks.
This catalog reads no proposals, answers, people, assignments, decisions or totals.
Direct conversion-only entry is still separate: its existing continuation needs
both Applications conversion authority/adapters and Programme item management.

## Complete protected discovery

Identity and Events resolve exact active-person and private-planning edition
references first. Workforce supplies at most 256 current Department identifiers,
not a directory grant. Evaluate every code-owned task decision before resolving
any admitted Department label/code. Hidden Departments and tasks expose no labels,
identifiers, counts, guessed destinations or reasons about other people.

Validate policy version, type, reason, field subset and exact obligations.
Ordinary absent permission and a well-formed insufficient granted field ceiling
omit only that task. Invalid/nonordinary policy, owner mismatch, overflow,
dependency/audit failure or changed source withholds the complete response.
Recheck the complete source, decisions and admitted labels around audit and
rendering, including changes that leave the visible list superficially unchanged.
Any comparison fingerprint remains server-only, never a browser permission token.

Audit admitted purpose/Department reads before disclosure under existing restricted
Applications retention, without names, hidden totals or activity analytics. Empty
purpose results record only non-disclosing unavailable-task evidence, not an
invented successful capability grant. A required audit failure releases no catalog.

## Shared-shell states and recovery

Reuse the management shell's one H1/main and compact Access disclosure. Group
ordinary task links under readable Department labels with stable codes to
disambiguate duplicate names. Explain the current policy source for each permitted
task without a principal directory. Link destinations authorize again.

Empty: no tasks currently available; accountable setup manages access separately,
with no claim about hidden Departments. Read-only planning retains inspection
links and explains that destination owners decide which actions remain possible.
Unknown scope or invalid permission gets neutral not-found guidance; malformed
query controls are rejected; unavailable dependencies return a safe retry response.
No browser POST, mutation confirmation, draft state or silent retry rebasing exists
on this read-only entry. Existing destination form recovery is unchanged.

Ordinary labels, lists and links must wrap without page-level overflow, retain
keyboard activation and visible focus, and avoid motion or color-only meaning.
Automated tests cover heterogeneous capabilities/field ceilings, hidden-label
nonlookup, wrong scope, lifecycle, complete bounds, policy/source changes, required
audit failure, real HTML, closed transport and production containment. Maintain
native owner/policy scenarios without collecting or running them under ADR 0100.
Synthetic browser evidence does not replace #92's full widths, native zoom,
screen-reader and genuine-role comprehension or #109 integrated acceptance.
