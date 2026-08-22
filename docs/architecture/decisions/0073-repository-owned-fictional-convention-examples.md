# ADR 0073: Repository-owned fictional convention examples

- Status: Accepted
- Date: 2026-08-22
- Supersedes in part: ADRs 0042 and 0045
- Requirements: IDN-013, HR-011, PRI-001, PRI-007, INT-005, NFR-002,
  NFR-003, NFR-009, and NFR-012

## Context

Maru already prohibited production personal data in tests and had retired its
live public-roster import path. The current tree nevertheless retained a real
convention identity, public URL, parser, compatibility command, and a
22-Department starter whose exact taxonomy came from public organizational
material. Other current examples used repository-authored names that were
fictional but not visibly part of Maru's own example namespace.

Failing before network access protected people, but retaining another
organization's brand and copied taxonomy was unnecessary. A text-only rename
would also be dishonest: the template code, canonical digest, exact rows,
database receipt guard, API enum, UI, generated clients, and immutable receipt
provenance form one contract.

## Decision

1. Named repository-controlled conventions use the fictional Maru example
   namespace. The canonical examples are **MaruCon** and **MaruDance**. They
   are documentation and test identities, not customers, partners, real
   events, endorsements, or claims of global trademark availability.
2. Examples, fixtures, screenshots, tests, generated contracts, and tutorials
   use synthetic people and RFC-reserved contact domains. They do not fetch,
   parse, snapshot, or translate a real convention roster, people directory,
   organization chart, or people-to-role mapping.
3. Remove the obsolete public-roster parser, URL, and compatibility management
   command. Unsupported old automation receives Django's ordinary unknown-
   command failure; preserving an otherwise unnecessary adapter is no longer a
   safety benefit.
4. Replace the source-derived structure template with
   `marucon-reference@1`. Its one root and 21 child Departments are authored
   from Maru's own product requirements and recorded in the
   [fictional operating model](../../research/marucon-operating-model.md). The
   canonical SHA-256 digest is
   `55f4091787215fd9eef5cc1266806a1450dd6e5449d50864340601f5ec2398ee`.
5. Preserve copy-on-write and provenance. Do not relabel an immutable receipt
   or rewrite an organizer's copied and potentially edited Department tree.
   Workforce migration `0009` locks and checks the receipt table, refuses an
   upgrade when any non-current built-in-template receipt exists, and installs
   the new receipt guard only when that check passes. Affected unreleased
   local/test workspaces must rebuild from synthetic data.
6. Refresh `seed_demo_data` as
   `maru-fictional-two-convention-v6`. Stable fixture keys, slugs, display
   names, and emails now use MaruCon or MaruDance. Earlier fixture databases
   are not upgraded or silently renamed; use a new disposable database.
7. General product research may synthesize a requirement from reviewed public
   material, but it must not retain convention branding as example data or
   imply affiliation. Partner-specific research and migration require an
   explicit purpose, consent or lawful basis, provenance, minimization,
   correction, access, retention, and removal contract.
8. Preserve accurate attribution for third-party software, standards,
   dependencies, licenses, and security advisories. The fictional-convention
   rule must not erase legally or technically necessary credit.
9. Sanitize current rendered historical prose where a convention brand or
   source-derived label is unnecessary. This is a one-time ethical terminology
   correction, not a claim that the earlier decision used the new starter.
   Public Git history remains unchanged and retains the exact earlier wording;
   no destructive history rewrite is authorized.
10. Extend the existing documentation validator rather than adding a CI job.
    It enforces the fictional-example registry, blocks known retired brands in
    current content, rejects non-reserved external people-directory URLs, and
    verifies that all documentation remains reachable through the curated
    hierarchy.

The rule governs repository-controlled material. It does not prevent an
authorized organizer from entering its own real legal identity and convention
records into a properly governed deployment.

## Consequences

- New contributors receive coherent examples without needing to distinguish
  copied research from fictional data.
- The demo and built-in template are deterministic, offline, and independent
  of another convention's public site or taxonomy.
- Existing local databases containing retired template receipts fail the
  migration deliberately. Rebuilding disposable synthetic data is safer than
  falsifying immutable provenance.
- Generated OpenAPI and TypeScript contracts expose only
  `marucon-reference@1`.
- Historical Git commits still contain earlier terminology. Removing it would
  require a separately authorized destructive public-history rewrite with
  consequences for commit, pull-request, release, and verification evidence.
- Naming something MaruCon or MaruDance is a project example convention, not
  legal clearance for commercial branding in every jurisdiction.

## Alternatives considered

### Rename only the visible label

Rejected because the copied taxonomy and immutable digest would still derive
from an external organization while the new label concealed that provenance.

### Preserve the retired adapter because it fails closed

Rejected because unknown-command failure is equally safe and removes URL,
parser, maintenance, and accidental-revival surface.

### Rewrite existing template receipts and Department rows

Rejected because receipts are immutable evidence and copied trees may contain
organizer edits. A fail-closed local rebuild is the honest unreleased boundary.

### Ban all external names everywhere

Rejected for dependencies, standards, licenses, advisories, and factual legal
attribution. Those names serve necessary credit rather than example identity.
