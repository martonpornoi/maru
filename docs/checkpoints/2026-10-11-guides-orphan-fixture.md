# Guides integration: historical orphan fixture

- Date: 2026-10-11
- Requirement: NFR-001; existing Programme recovery and Guides schema boundaries.

Full certification of `6d732f5` failed after 3176.875 seconds. The repaired Guides
foundation batch passed. Shard 19 passed its Knowledge downgrade-fence case, then
failed during historical orphan setup: a current ApplicationDefinition validation
loaded EventEdition after its adoption_revision column had been reversed.
The complete failed evidence is preserved under
`.tools/guides-certification-6d732f5/failed-local-ci-evidence/`.
No success receipt exists; all owned containers were removed.

A first focused repair attempt created calls before reversal. The unchanged
retained-evidence downgrade fence correctly rejected that approach: one case
passed and one failed in 290.53 seconds (300.797-second wrapper), with owned
cleanup. Its evidence remains under `.tools/guides-orphan-repair-20261011/`.

The revised fixture instead creates call definitions, children and exact creation
and activation receipts through the migration executor's historical model registry,
after the genuine empty downgrade. It uses the existing transaction-local writer
boundary and explicitly checks all deferred constraints. No trigger is disabled,
no migration is faked, and no retained fence is bypassed. Department retirement
occurs through historical models with native structure version and receipt
constraints; no dependency-probe monkeypatch remains. All current migration leaves are restored before current recovery commands.
Existing exact-ID, break-glass, Audit, event, replay and recovery evidence assertions
remain intact. Historical synthetic setup is not proof of current command or
restricted-runtime acceptance. No production code changes.

The first historical-model attempt passed creation but failed activation because
`asdict()` omits the input contract's fixed visibility properties, leaving generic
historical question defaults. One case passed and one failed in 414.31 seconds
(420.735-second wrapper); source identity and owned cleanup were verified. Evidence
remains under `.tools/guides-orphan-history-20261011/`. The seed now explicitly
sets the existing closed Programme visibility flags; the native rule is unchanged.

The explicit-visibility attempt reached the lifecycle evidence constraint and
failed because historical activation lacked its actor and timestamp. One case
passed and one failed in 409.07 seconds (415.532-second wrapper); unchanged
source and owned cleanup were verified. Evidence remains under
`.tools/guides-orphan-flags-20261011/`. The fixture now retains both activation
fields as the existing command does, alongside its version and exact receipt.

The lifecycle-corrected attempt passed call creation and activation, then failed
when the current retirement helper loaded EventEdition against the old schema.
One case passed and one failed in 419.34 seconds (425.765-second wrapper), with
unchanged source and owned cleanup. Evidence remains under
`.tools/guides-orphan-lifecycle-20261011/`. Retirement now seeds historical
Department, structure control and exact retirement receipt together, retaining
actor/time and one version step. All deferred constraints are explicitly checked.
The existing dependency-probe monkeypatch is removed. This old synthetic setup
is not current retirement-command, Audit or runtime-role acceptance; current
recovery assertions remain unchanged.

The final focused run passed both the Knowledge used-downgrade fence and
historical orphan recovery in 418.60 seconds (424.968-second wrapper), with no
skips or errors. Source inventories matched digest
`7ffe6500417a7f10876dcd9472ded018a67e8ee709b37aa820391f56e694d7ed`;
the exact owned container was removed. Evidence is retained under
`.tools/guides-orphan-retirement-20261011/native-reserve-20261011T125859Z-0fb04b12/`.
Scoped lint, formatting, documentation validation and whitespace checks passed.
All earlier failed attempts remain preserved. A changed commit needs fresh full
certification. Browser acceptance remains open and ongoing/future demo coverage
is unaffected by this historical fixture repair.
