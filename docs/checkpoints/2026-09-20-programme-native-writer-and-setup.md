# Programme native writer cutover and setup prerequisite

Date: 2026-09-20. Local continuation of #48/#109/#189; no protected delivery.

## Identity #196

Identity migration 0023 adds a source-pinned, least-privilege invoker guard and
post-use downgrade refusal. Observed migration, sole trigger, source and metadata
drive the writer-generation readiness gate; keys, workers and all existing native
requirements remain intact. Generic challenge issuance and consumption accept
only public verification/recovery. Registration remains independently gated.

Audit correction: the existing `identity_invitation_legacy_delivery_suppressed`
constraint already required inert legacy delivery fields. ADR 0110 now accurately
describes this, rather than claiming those fields were previously unguarded.
Two initial migration-test failures were test defects: model validation prevented
a direct-native invalid insert, and an alleged historical pending-delivery row
violated the pre-existing constraint. The corrected tests use native bulk insert
for rejection and preserve a genuine existing invitation unchanged during upgrade.
No constraints were weakened or invalid historical data manufactured.

Evidence: 280 adjacent native cases passed in 50.57s; 10 public/retention cases in
10.40s; corrected writer/migration cases 17 in 4.00s. These overlap and must not
be summed as unique acceptance. Expanded fail-closed units passed 46 in 0.29s;
the preceding full fast suite passed 12,575 in 71.88s. Changed-source mypy and
Ruff passed. Documentation validation passed 656 files before this checkpoint.

## Actual runtime progression and #197

The fresh isolated candidate now passes unchanged full readiness and reaches
foundation setup. It then fails at genuine Maru-operator activation commit.
Content-free diagnostics identify SQLSTATE 23514 in deferred authority-bundle
validation; the primary-message hash resolves to the source literal
`ordinary authority issuance requires persistent controls`.

The native completeness, historical bundle and assignment functions retain
Executive-Board-only ceremony recognition even though the accepted Python
boundary and insertion guards support Maru operators. #197 records correction
under IDN-012/NFR-013 and ADR 0080, preserving independent approval, exact
capabilities, profile scope, immutable evidence and current/historical boundaries.

The diagnostic run failed in 190.32s before any archive generation. It changed
only child diagnostics, not commands/authority, but is not final native acceptance.
Temporary databases were task-owned, synthetic and disposed by the fixture.
No production profile, user data, outgoing email or protection was changed.
Next: correct native representation lineage, rerun unmodified setup/archive and
continue P11/stop-use/recovery through the protected coherent bundle.
