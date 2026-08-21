# ADR 0067: Bounded public-history and secret-validity audit

- Status: Accepted
- Date: 2026-08-21
- Requirements: PRI-001, PRI-007, NFR-001, NFR-002, NFR-003, NFR-011
- Implements: GH-003
- Relates to: ADR 0042, ADR 0063, ADR 0064, and ADR 0066

## Context

Maru became public before every item in the pre-publication history review had
fresh evidence. Standard GitHub secret scanning and push protection were live,
but that did not by itself inspect the repository-controlled Git refs, exported
issue and discussion metadata, currently tracked assets and dependencies, or
historical author records covered by this decision. A current-tree search would
also miss a secret removed by a later commit. GitHub-hosted workflow logs and
artifact bytes are a separate, server-generated surface.

Secret-validation and generic-pattern controls have different trust and
availability implications from ordinary secret scanning. Validity checks may
contact the issuing provider, and the relevant repository controls are not
available to Maru under its current user-owned public-repository shape. A
history scanner can complement GitHub's protection, but making another broad
pull-request job permanent would add recurring noise and supply-chain surface
without replacing provider revocation or human triage.

Raw scanner reports are themselves sensitive. A true finding can contain the
credential, nearby personal data, a historical path, and a usable commit link.
Durable evidence therefore needs scope, tool provenance, counts, decisions, and
sanitized conclusions rather than matched values.

## Decision

1. Complete GH-003 as a bounded, one-time launch audit. Audit the public remote
   namespace, including all four branch heads and eight pull-request heads, as
   one 46-commit graph. Verify the mirrored object database with strict Git
   integrity checks and scan the current repository candidate separately so
   unpushed work is not omitted.
2. Use Gitleaks 8.30.1 from a checksum-verified release archive for the
   history, current-tree, and exported public-metadata scans. Manually review
   every result in context. Commit no raw report, secret value, matching text,
   or reusable fingerprint. The checkpoint records one false-positive category
   and zero unresolved secret findings without reproducing the matched prose.
3. Keep standard GitHub secret scanning and push protection enabled. Do not
   attempt to enable validity checks or generic-pattern scanning while the
   repository is user-owned and those controls are unavailable. Reassess their
   eligibility, provider-contact consequences, expected fixture noise, and
   value before any future ownership or plan change. No GitHub setting changes
   are authorized by this decision.
4. Treat public Git author name and email metadata as intentional publication,
   not as Maru identity or account data. The owner accepts the already-public
   historical personal Gmail address without rewriting history. New commits
   use the GitHub-provided no-reply address unless an author knowingly chooses
   another public address.
5. Review tracked binary assets for provenance and embedded metadata and review
   the locked Python and Node dependency inventories for distributable-license
   compatibility and notice obligations. Maru-owned source remains Apache-2.0;
   because the compiled Staff Console embeds MIT components, Python distribution
   metadata and the release application manifest declare
   `Apache-2.0 AND MIT`. Release assets and the OCI image carry `LICENSE` and
   `THIRD_PARTY_NOTICES.md`; the image also carries its SBOM and provenance, but
   GH-003 does not assign one aggregate image-wide license expression. Browser-
   delivered Staff Console output serves Maru's Apache-2.0 license and the
   bundled MIT notice; generated contributor documentation serves complete
   license texts for Maru and every copied Sphinx/sphinxcontrib-mermaid/Furo/
   Pygments/normalize.css/Gumshoe asset. The owner attests that the seven
   currently tracked brand assets are project-controlled. The audit reviews
   those files and accepts
   non-sensitive editor provenance in two images; it does not independently
   prove ownership or cover assets present only in historical or server-
   generated artifacts.
6. Do not add a permanent full-history scanner to pull-request CI. GitHub's
   standard scanning and push protection remain continuous controls; ordinary
   review and release checks cover changes after this audit. Repeat a full
   history audit only after a material visibility, ownership, imported-history,
   or incident boundary.
7. If a future audit finds a real credential, revoke or rotate it at the
   provider before relying on repository cleanup. History rewriting, ref
   deletion, and forced updates are destructive incident operations requiring
   separate authorization, impact review, and public coordination.
8. Do not characterize GH-003 as an audit of every public byte. GitHub-hosted
   Actions log and artifact bytes were inventoried but not downloaded or scanned.
   The 2026-08-21 snapshot observed 62 workflow runs and 188 unexpired artifacts;
   those counts are drift-prone and the data remains governed by short retention.

## Consequences

- Maru has sanitized evidence for the audited public Git-ref graph and current
  candidate, not merely a current-tree assertion.
- No raw finding becomes another public disclosure through documentation,
  artifacts, CI logs, or a committed scanner allowlist.
- The accepted historical author address remains visible. This is an explicit
  owner decision, not a claim that Git metadata is anonymous.
- After adding the required bundled-component notice and the composite Python-
  distribution and release-manifest expression, the audit found no unresolved
  secret, production-personal-data, current-asset, copyright, or dependency-
  license blocker within its scope. It does not certify future commits or
  production operations.
- CI treats checked-in browser output, Django templates/static, and root legal
  files as tested publication inputs. Generated-output checks include untracked
  files, package-relevant changes build and inspect both Python distributions,
  and full database fan-out waits for the focused license/static gate.
- Validity and generic-pattern controls remain deferred without weakening the
  live standard scan and push-protection boundary.
- The first candidate release can rely on this one-time baseline, while later
  releases review the delta and current security alerts rather than paying for
  another complete history scan.
- Hosted Actions logs and artifact bytes remain outside the scan conclusion;
  their bounded retention does not turn an inventory snapshot into content
  assurance.

## Alternatives considered

### Run Gitleaks on every pull request

Rejected for the launch-history requirement. Pull-request scanning would not
prove old refs were clean, would duplicate GitHub's continuous controls, and
would introduce another tool download and false-positive path into every
contribution. A future lightweight delta scanner needs separate evidence.

### Commit the raw scanner reports

Rejected because a report can reproduce precisely the credential or personal
context the audit is intended to contain. Sanitized scope and conclusion are
sufficient durable evidence.

### Rewrite history to remove the maintainer's email address

Rejected because the address was knowingly used by its owner, no credential or
production record was exposed, and rewriting public commits and pull-request
references would create disproportionate integrity and coordination cost.

### Enable every enhanced secret-detection control

Rejected because the current ownership shape does not expose the reviewed
validity and generic-pattern controls, validity checks may contact providers,
and enhanced controls need a separate noise, privacy, availability, and support
decision.

## References

- [GitHub validity checks](https://docs.github.com/en/code-security/concepts/secret-security/validity-checks)
- [GitHub supported secret-scanning patterns](https://docs.github.com/en/code-security/reference/secret-security/supported-secret-scanning-patterns)
- [GitHub sensitive-history removal](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)
- [Gitleaks v8.30.1 release](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1)
- [PEP 639: Improving License Clarity with Better Package Metadata](https://peps.python.org/pep-0639/)
- [PyPA license-expression specification](https://packaging.python.org/en/latest/specifications/license-expression/)
- [PyPA project-metadata licensing specification](https://packaging.python.org/en/latest/specifications/declaring-project-metadata/#license)
- [GitHub Actions artifact and log retention](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/remove-workflow-artifacts)

## Requirements affected

- PRI-001 records public repository metadata and audit outputs as distinct data
  classes with explicit publication and retention decisions.
- PRI-007 keeps durable evidence sanitized instead of copying sensitive matches.
- NFR-001 gains a verified, bounded Git-history, worktree, metadata, current-
  asset, and dependency-license audit boundary.
- NFR-002 requires security, public-readiness, release, and retention guidance
  to describe the resulting controls accurately.
- NFR-003 is satisfied by the append-only checkpoint and maintained hardening
  state.
- NFR-011 retains continuous standard scanning and separately authorized live
  settings while rejecting an unreviewed permanent scanner dependency.
