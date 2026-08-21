# Public-history and secret-validity audit

Date: 2026-08-21
Status: GH-003 one-time audit complete; no live setting mutation
Requirements: PRI-001, PRI-007, NFR-001, NFR-002, NFR-003, NFR-011
Decision: ADR 0067

## Outcome

Within its stated repository-controlled scope, Maru's bounded public-launch
audit found no unresolved credential, production-personal-data, public-metadata,
current-asset, copyright, or dependency-license blocker. Standard GitHub secret
scanning and push protection remain enabled. Validity checks and generic-pattern
scanning are unavailable for the current user-owned repository shape and remain
deferred; no repository setting was changed.

The audit evidence is intentionally sanitized. No matched string, secret value,
reusable scanner fingerprint, raw metadata export, or full detector report is
committed.

## Audited scope

The public remote namespace contained four branch heads and eight pull-request
heads. Their union contained 46 unique commits. A bare audit mirror fetched
those refs explicitly, and `git fsck --full --strict` exited successfully with
no reachable-object corruption. Unreachable objects in the maintainer's working
clone were outside the server-visible graph and did not change that result.

The current repository candidate was copied without its ignored local tooling
and scanned independently. This covered committed Step 2 work even where it was
not yet part of the audited public-ref graph.

GitHub-hosted Actions log and artifact bytes were not downloaded or scanned. A
drift-prone API inventory snapshot observed 62 workflow runs and 188 unexpired
artifacts. Those server-generated objects remain governed by short retention;
their inventory is not evidence that GH-003 examined all public server-generated
bytes.

## Secret and metadata evidence

Gitleaks 8.30.1 was obtained as the Windows x64 release archive. Its SHA-256 was
verified before execution as
`d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e`.

- The complete 46-commit public graph produced one generic-key detector result.
  Manual contextual review classified it as ordinary documentation prose with
  no credential syntax, issuer, account, endpoint, or usable secret. No broad
  allowlist was added for it.
- The current candidate-tree scan produced zero findings.
- Sanitized exports of public issue and pull-request metadata and public
  discussion metadata produced zero findings. Manual review found no production
  personal data or confidential incident material.
- Standard GitHub secret scanning and push protection were read as enabled. The
  public repository reported no unresolved secret-scanning alert at the audit
  boundary.

Historical Git metadata contains the repository owner's personal Gmail address
on earlier commits. The owner accepts that already-public author attribution
without a destructive rewrite. Future maintainer commits use GitHub's no-reply
address by default. This exception does not authorize real-person data in
fixtures, examples, issues, logs, or application records.

## Asset and dependency evidence

All seven currently tracked raster/icon brand assets were reviewed. The owner
attests that they are project-controlled; the audit did not independently prove
ownership or examine assets found only in historical or server-generated
artifacts. Five contain no EXIF or XMP metadata. Two logo images retain
non-sensitive orientation, editor, document-history, and timestamp metadata;
neither contains an email address, GPS coordinate, or identified person.

The locked Python and Node direct and transitive dependency inventories,
bundled documentation assets, compiled frontend, container inputs, and pinned
GitHub Actions were reviewed for license and notice obligations. The compiled
Staff Console embeds React, React DOM, and Scheduler under MIT terms. The
remediation keeps Maru-owned source Apache-2.0, declares packaged distributions
as `Apache-2.0 AND MIT`, and records that expression in the release application
manifest. The browser-delivered Staff Console carries an Apache-2.0 license and
the complete MIT notice beside every generated JavaScript chunk. The generated
contributor site serves complete Maru, Sphinx, sphinxcontrib-mermaid, Furo,
Pygments, normalize.css, and Gumshoe license texts. Package metadata, release
assets, and the application image include `LICENSE` and
`THIRD_PARTY_NOTICES.md`; the image also has SBOM and provenance evidence, but
no aggregate image-wide license expression is
asserted. No unlicensed third-party asset or remaining dependency-license
blocker was identified. This is a repository publication review, not legal
advice or a substitute for reviewing future dependency changes.

## Control decision

Validity checks can contact a detected secret's issuing provider. Generic
patterns can also add fixture and documentation noise that must be understood
before enablement. The reviewed controls are not available on Maru's current
user-owned public repository, so both remain deferred rather than simulated by
a custom permanent workflow. Reassess them after an organization transfer,
plan or eligibility change, imported history, or a credential incident.

No permanent pull-request history scanner was added. Continuous protection
remains GitHub's standard secret scanning and push protection, ordinary review,
and release-delta reconciliation. Any future real credential is revoked or
rotated first; history rewriting or ref deletion requires separate destructive
authorization.

## Verification and limits

- Public scope: four branches, eight pull-request heads, 46 unique commits.
- Git integrity: strict full object verification exited successfully.
- Scanner: checksum-verified Gitleaks 8.30.1; one sanitized false positive and
  zero unresolved public-history findings.
- Current candidate, issue/pull-request metadata, and discussion metadata:
  zero scanner findings. The final repository-candidate scan covered 1,270
  tracked and candidate files and also produced zero findings.
- Seven currently tracked, owner-attested project-controlled brand assets and
  their embedded metadata reviewed; ownership and historical-only assets were
  outside the audit proof.
- Locked Python and Node dependency licenses and third-party publication inputs
  reviewed; the MIT notice plus Python-distribution and release-manifest
  metadata remediate the identified bundled-runtime obligation, with no
  remaining release blocker.
- A clean PEP 517 build produced a 643-member wheel and 746-member source
  archive with both legal files and all 124 tracked Django template/static
  assets. Neither archive contained `.uv-cache` or Sphinx doctree content. A
  durable verifier now rebuilds and checks that exact inventory whenever
  package inputs change.
- The Staff Console typecheck and 20 tests pass; two identical builds reproduce
  the same four generated files. Both hosted paths and `scripts/check.ps1`
  reject tracked differences and untracked generated assets.
- Seventy-four focused release/package/classifier/workflow contracts and all
  1,935 unit tests pass. Ruff, strict mypy, PyDocLint, semantic docstring
  validation, Actionlint, lock validation, and the immutable-Action allowlist
  pass. A warning-fatal Sphinx build and 2,388-entry release-archive rehearsal
  preserve all seven site license texts, both root legal files, and no doctrees.
- Hosted Actions log and artifact bytes excluded; the drift-prone snapshot saw
  62 workflow runs and 188 unexpired artifacts under short retention.

This one-time audit does not prove future commits, deployment secrets,
production data handling, hosted Actions log or artifact contents, historical-
only asset ownership, partner permissions, or legal readiness. GH-004's durable
contacts, succession, repository metadata, and broader public-policy work remain
separate. The first candidate release still requires its dedicated pull request
and every ADR 0065 verification step.
