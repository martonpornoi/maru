# Guides integration: historical event fixture order

- Date: 2026-10-11
- Requirements: REG-022, NFR-001; existing adoption and authority contracts.

Full certification of `f9c91480` failed after 8332.141 seconds. Fifty-one database
batches passed; shard 52 passed nine cases and failed the Registration audience
backfill fixture because EventEditionFactory inserted adoption_revision after
that column was reversed. Seven other active batches were interrupted, not
independently failed. All 59 owned containers were removed. Complete evidence is
retained under `.tools/guides-certification-f9c9148/failed-local-ci-evidence/`.
No certification success receipt exists.

The Registration fixture now creates ordinary synthetic event/account records
before the genuine rollback and continues to seed profile fields through the
historical registry. A static scan of migration tests found the same ordering in
the retired-Department authority preflight fixture; its ordinary event/account
setup moves before rollback too. No historical data under test moves across the
boundary. Audience backfill, active-field immutability, compatible reversal,
retired-authority preflight and reverse-fence assertions remain intact. There are
no production schema, permission, pin or function changes.

The preceding Workforce Programme FK reversal, original Registration audience
case and matching retired-authority case all passed: three native cases in
1679.85 seconds (1687.562-second wrapper), with no skips or errors. Before/after
source inventories matched digest
`5dd2b34a4bdf0b0afd0b0c4bb332760ad9b8b91d402731012feaee1b2a019728`;
the exact owned container was removed. Evidence remains under
`.tools/guides-event-fixtures-20261011/native-reserve-20261011T195626Z-7768a885/`.
Scoped lint, formatting, documentation validation and whitespace checks passed.
A changed head requires fresh full certification. Browser acceptance
and the V6 credential refusal remain separate; demo coverage is unchanged.
