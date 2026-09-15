# Programme person references

- Status: Dormant bounded #108 implementation; protected delivery and final gates pending
- Requirements: PRG-001, PRG-002, PRG-003, PRG-009, IDN-014, AUD-001, AUD-003,
  PRI-001, UX-005 through UX-008, UX-019, UX-020, UX-027, UX-029 and NFR-013
- Decisions: ADRs 0051, 0082, 0085 and 0100 remain authoritative; no ownership,
  schema or adoption-policy change is introduced

## Meaning and scope

The registered pair `person_reference` / `programme.person` identifies an existing
Maru person mentioned in one private proposal answer. It is not an invitation,
contributor/host assignment, consent, public profile, attendance or other relationship.
Only Identity supplies active-verified-person references and minimized non-email
account display labels. No generic model resolver, directory, contact lookup or
client-selected viewer account is permitted. Other kind/type pairs remain unavailable
until their owning contracts and controls exist; domain references and safe files
remain separate #108 work.

Applications keeps the existing append-only answer and sole proposal aggregate
version. A label is current presentation of that exact retained account reference,
not the name frozen into a contributor's proposed-public profile. Explain that
distinction beside the label. An unavailable account retains its original reference
with neutral feedback, without claiming current identity eligibility or role.

## Personal selection

The dormant edit route is below the authorized proposal task:
`/my/applications/programme/<organization>/<edition>/<proposal>/work/answer/<question>/person/`.
The preceding shared-answer card is labelled with the question, not a pasted UUID.

Require independently authorized actual-person `proposal_summary`/`answers` read
and proposal-edit authority, a lead or accepted collaborator relationship, the
exact current applicable applicant-writable question, Draft state, open planning,
active call and inclusive editing window. Compare the original proposal aggregate,
call aggregate and immutable schema version before lookup. A deliberately entered
exact known login email is normalized only by Identity; unknown, inactive,
unverified and non-person accounts share one empty result. Required positive/empty
audit is minimized, uses existing Applications restricted retention, and precedes
label disclosure. Email is request-only, never stored in an answer, audit or proof.

Selection and confirmation are separate explicit actions. A bounded uncompressed
purpose-specific signed proof binds actor, tenant, edition, proposal, question,
original source versions, person-or-explicit-empty intent and retry key. It is not
authority. Subsequent reads refresh only that account's permitted label; they never
repeat email discovery or substitute a new account/version. All scalar/proof fields
are single-valued; unknown fields, extra query parameters, files and oversized input
are refused. Preserve original proof, reason and confirmation through validation
and stale feedback. Use distinct form IDs when lookup and confirmation coexist.

Only deliberate confirmation invokes `append_programme_proposal_answer`. Fresh
nonempty writes revalidate the registered meaning and current active verified
Identity reference inside the existing transaction. Successful canonical receipt
replay remains before fresh source validation and never re-resolves email. Do not
redispatch the writer when rendering fails. Explicit clearing writes `None`, not
an inferred different person; required questions may be blank in Draft but block
sealing. History and original command evidence are not rewritten.

The command's optional `expected_call_version` and `expected_definition_version`
must be supplied together as positive bounded integers. They bind the digest and
are compared with the locked original call/schema only after canonical replay;
legacy callers omitting both retain their original digest shape. The dedicated
selector always supplies both. These fences add no database column or new receipt.

## Independently authorized viewers

Current personal viewing uses the proposal's `references/person/<question>/` route;
frozen viewing uses `revisions/<revision>/references/person/<question>/`. Both derive
the account only from the owner's authorized answer, never a URL account parameter.
Frozen viewing requires the existing current exact seal and genuine contributor
inclusion and does not grant another person's private profile.

Reviewer, moderator and decider viewers live below their own existing case/assignment
answer task at `answers/person/<question-key>/`. Each retains that role's exact
tenant/Department/case/assignment, current seal, allowed-question and field ceiling.
Anonymous stage exclusions run before reference or identity resolution, including
direct URL attempts. Extra sensitive-content authority remains mandatory. Manager
context, assignment permission or a visible link never substitutes for content access.

Read and audit the permitted source before selecting the account, independently
resolve only its minimized label, and reauthorize/recompare complete source and
label evidence before releasing rendered bytes. No partial or cached old label is
shown after a source, role, field or policy change. Body failures distinguish
invalid input, generic denied/not-found, original-source conflict and unavailable
dependencies without exposing names, hidden counts or another account.

## Interaction, verification and remaining gates

Use the existing personal/admin shells, one H1/main, ordinary labelled forms and
links, explicit consequences, visible focus, error/status announcements and the
existing pending-input guard. Long labels wrap; no custom animation or pointer-only
interaction is needed. Viewing and preparation create no answer; confirmation does.
Every newly prepared selection starts with confirmation unchecked, including when
a hidden input posts the string `False`. Failed confirmation retains its original
checked state and reason; preparing a different intent is a separate step.
Return links independently authorize their destination. Key rotation may invalidate
old browser proof; consult authorized history before deliberately creating new intent.

Cover exact actor/tenant/edition/question and role/field admission, all empty cases,
tampered/oversized/cross-purpose proofs, email reassignment without retry rebasing,
clear/null semantics, original-version conflict, replay, late source/label loss,
auditor/dependency failure and anonymous no-lookup behavior. Maintain native cases
under #102 without collecting/running them during ADR 0100. Record bounded synthetic
browser results separately from #92's real zoom, widths, keyboard/assistive-technology
and human comprehension. #109/#97/#102/#92 remain mandatory before promotion.

This component mounts no production route, activates no profile, sends no invitation
or notice and creates no unrelated-module record. It does not complete #108 or #48.

No schema or runtime-grant change is needed. Preserve retained answers/receipts
during recovery; never reinterpret existing kinds or rewrite immutable seals.
Prefer fix-forward for a deployed defect rather than reverting the fresh-identity
validation contract. New native acceptance and repeated owner-read cost remain #102
debt, without invented timings, shard weights or combined coverage.
