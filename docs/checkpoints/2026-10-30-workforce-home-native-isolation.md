# Workforce operating-home native isolation repair

Date: 2026-10-30
Scope: #225, child of #35; NFR-001, NFR-003, NFR-008 and NFR-010.
Applies the existing committed-history isolation boundary under ADRs 0090 and
0098. UX-032 and ADR 0128 retain the Workforce operating-home product contract.

The first exact-head ordinary Auto run passed all 14,621 unit cases, with eleven
existing warnings, and 56 native shards before shard 57 failed genuine-runtime
readiness. Seven other running shards were interrupted by normal pool cleanup;
the remaining planned shards did not run. Source and wrapper pins were unchanged,
all 64 exact owned containers were removed, and the ten original stopped fixtures
were retained. Complete failed and interrupted evidence is preserved in place.
No full local, hosted, review or delivery success is claimed for that run.

Two fresh isolated diagnostics retained the original historical and runtime test
bodies and reproduced the failure. All six Knowledge relation fingerprints were
unchanged. The failing dependency was the Guidance setup schema check: the
Programme import historical round-trip removed Events' `adoption_revision` at
physical position 18, left a dropped-column slot there, and re-added the field at
position 19. Constraints and indexes were unchanged; the exact current schema
fingerprint correctly refused that residue. Restoring migration leaves cannot
remove a dropped PostgreSQL column slot.

The orphan-retirement test now reuses `isolated_import_migration_graph`, already
used by the owning import migration suite. It creates a fresh empty owned test
database, applies real current and historical migrations with autocommit, restores
the history graph, and removes only that database after checking its identity.
The fixture checks exact setup schema fingerprints and readiness before and after
returning to the shared current database. The existing test body, independent
runtime login assertions and ordinary current-schema checks remain intact.

Production schema pins, migration sources, runtime permissions, historical
inventory, authoritative costs, coverage threshold, resource limits, timing
headroom, hooks and protected merge checks are unchanged. The maintained ongoing
and future Workforce practice journeys and their earlier browser evidence are
unaffected by this test-isolation repair. Human, accessibility, operational,
recovery and production acceptance remain open.

Next: verify the repaired historical/runtime sequence, commit the coherent
candidate, then run fresh complete ordinary Auto and independently verify the
new exact head before publication, review and protected delivery.

## Focused repair verification

The same two original tests now pass together using ordinary pytest without a
diagnostic observer. The historical body and genuine-runtime test are unchanged.
The fixture's exact setup schema and readiness assertions pass before and after
the isolated committed history, and the following genuine runtime login reports
healthy readiness. All 3,287 source files match before, after and live readback;
the exact owned container is absent and all ten original stopped fixtures remain.
The complete focused originals are preserved separately from the failed runs.

Selected lint and formatting, documentation policy over 784 Markdown files and a
fresh warning-fatal Sphinx build pass. Complete ordinary Auto for the final clean
commit and independent hosted/review acceptance are still required. This focused
result neither certifies the full repository nor changes any human or production
acceptance boundary.
