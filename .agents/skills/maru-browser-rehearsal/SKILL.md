---
name: maru-browser-rehearsal
description: "Rehearse a Maru browser journey across roles, states, responsive widths, keyboard behavior, accessibility, and disclosure boundaries, then record evidence honestly. Use for visible UX acceptance or browser-based diagnosis; do not use for API-only testing or visual styling without a journey."
---

# Maru Browser Rehearsal

Test what a person can actually discover, understand, and complete. A rendered
page is not accepted merely because its route responds or its backend tests
pass.

## Define the rehearsal

1. Read the current page contract, requirements, relevant ADRs, module guide,
   code, and existing browser/integration tests.
2. Name the exact synthetic roles, organization and edition, starting state,
   task sequence, expected decisions, protected information, and stopping
   point.
3. Separate read, mutation, denial, and recovery evidence. One privileged
   account cannot stand in for every role.
4. Use only synthetic accounts and records. Never put production personal data,
   credentials, or identifying screenshots into evidence.

Read [the evidence matrix](references/evidence-matrix.md) and select every row
that matters to the contract. Do not claim the complete UX-029 or release
matrix from a narrower rehearsal.

## Exercise the visible journey

Use the available browser controls to navigate through ordinary links and
forms. Inspect visible purpose, current scope, task continuations, state and
error language, access explanations, field labels, keyboard behavior, focus,
landmarks, overflow, and console output. Reauthorize at each destination and
confirm that denied or other-tenant states disclose no hidden person or record.

When the task asks for diagnosis or evidence only, report findings without
editing. When it asks for a fix, correct the smallest owning contract, rerun
focused automated checks, and repeat the affected browser path.

## Record evidence honestly

Capture the roles, data source, viewport or zoom, states exercised, browser
behavior, defects found and corrected, automated checks, and remaining gaps.
Distinguish:

- synthetic browser rehearsal;
- automated component, integration, or accessibility evidence;
- representative owner or two-human acceptance;
- deployment, recovery, and production approval.

Update the affected contract, current handoff, and checkpoint when the
rehearsal materially changes accepted behavior or project evidence.
