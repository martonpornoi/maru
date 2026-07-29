# ADR 0016: Minors, media, and privacy operations

Status: Accepted  
Date: 2026-07-28

## Context

Attendee profiles combine ordinary public-presentation fields with restricted
identity, emergency, guardian, and image data. Image approval alone does not
prove a file is safe. Historical correction and retention must not rewrite
accepted submissions or erase finance and audit evidence.

## Decision

- Each edition either remains adult-only or activates one immutable,
  jurisdiction-reviewed minor policy defining age bands, guardian rules,
  notice, consent version, and check-in requirements.
- A registration requiring guardian consent stays `guardian_pending`; it cannot
  reserve payment or confirm until an expiring guardian challenge accepts the
  exact policy version.
- Uploaded profile and fursuit images pass byte/size/type/decode checks, malware
  scanning, metadata stripping, and safe-rendition encoding before moderation.
  A safety receipt binds the source digest and rendition.
- Public media still requires scoped human approval. Exact approved reuse is
  limited to the same account and organization and copies safety evidence.
- Current-edition profile changes preserve the immutable submission.
  Post-edition correction uses proposal and independent decision.
- Subject-rights requests are tracked by controller scope. Exports are
  minimized to authorized account data.
- Retention minimization runs only against an approved policy and emits a
  disposal receipt. Files are removed only when no protected reference remains.
- Retention policy rows are read-only in bootstrap administration until an
  approved provisioning workflow is implemented.

## Consequences

Public media has both technical and editorial evidence, minors cannot silently
bypass consent, and historical meaning survives correction. Production still
needs the convention's lawful age/guardian rules, scanner service, storage
lifecycle, controller register, and approved retention-policy provisioning.

## Alternatives considered

- Treating image moderation as malware scanning was rejected.
- Editing historical submissions in place was rejected because it changes what
  the attendee originally accepted.
- Deleting a shared object whenever one profile removes it was rejected because
  another approved reference may still require it.

## Requirements affected

IDN-006, REG-002, REG-012, REG-015, REG-016, REG-019, PRI-001 through
PRI-009, NFR-007.
