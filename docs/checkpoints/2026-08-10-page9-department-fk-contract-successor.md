# Page 9 Department FK contract successor

Date: 2026-08-10
Status: Focused repository and PostgreSQL acceptance complete; deployment not
performed

## Outcome

Workforce `0008_department_fk_contract_successor` additively updates the
Page 9 hard-deletion guard for every current foreign key to
`workforce_department`. The original `0007` helper knew only the five
Workforce/Authorization references, so the later Applications, Charities,
Logistics, Registration, and Venues FKs made every otherwise valid unused-leaf
deletion fail closed.

The successor recognizes exactly these 13 relation/column pairs:

- `workforce_department.parent_id`;
- `workforce_position.department_id`;
- `authorization_scopedresourcebinding.department_id`;
- `authorization_capabilitygrant.department_id`;
- `authorization_roleassignment.department_id`;
- `applications_applicationownerdepartment.department_id`;
- `charities_charityselection.responsible_department_id`;
- `logistics_equipmentoffer.responsible_department_id`;
- `logistics_logisticsmanifest.responsible_department_id`;
- `registration_registrationprofileextensionfield.audience_department_id`;
- `venues_editionspaceselection.responsible_department_id`;
- `venues_editionvenueselection.responsible_department_id`; and
- `venues_venuebooking.responsible_department_id`.

All references must still target `workforce_department.id` and use a
non-cascading PostgreSQL delete action. An unknown or changed reference keeps
hard deletion unavailable.

## Migration and recovery decision

The new migration depends on Workforce `0007` plus the exact five migrations
that create the successor references: Registration `0039`, Applications
`0001`, Charities `0001`, Logistics `0001`, and Venues `0001`. Every creator
already descends from Workforce `0007`, so the graph is acyclic and does not
couple unrelated later guards.

Forward migration uses `CREATE OR REPLACE FUNCTION`, retains the pinned
`SECURITY DEFINER` search path and closed `PUBLIC` ACL, and changes no table or
data. Reversal restores the byte-exact `0007` function body. Because the later
FKs remain installed until their creator migrations reverse, that older helper
returns false and deletion stays fail closed during a partial downgrade.

Readiness now requires both Workforce `0007` and `0008` recorder rows, the
forward function fingerprint, and the exact 13-FK installed catalog. The
forward fingerprint is
`83e5707405156ec49bd70059a1cdcdf78c7d6472a198ea0151bc63efd84fa935`;
the reverse body restores
`378a3cf2cb86f8d91967be6355fa9dadde4244fd68e4a867f6548b1bfa516d3b`.

Historical Registration migration tests now share one graph-aware target
planner. Targets before Registration `0039` select Workforce `0007`; targets
at or after `0039` retain Workforce `0008`. This prevents Django from building
an invalid mixed backward/forward migration plan.

## Verification

- Ruff, Python byte-compilation, and strict focused mypy: green.
- Migration-target support unit tests: 5 passed.
- Affected historical-migration collection: 84 nodes collected.
- Workforce `0008`, readiness, successful/unknown-reference deletion, and raw
  tombstone PostgreSQL matrix: 9 passed.
- One representative forward/reverse node from each affected Registration
  historical suite: 6 passed.
- `makemigrations --check --dry-run`: no changes detected.

The PostgreSQL runs used pytest's isolated test database. No development or
production database was migrated by this work.

## Remaining gates

Apply migrations in graph order in each deployment, then run the Page 9
readiness probe before enabling writers. Whole-repository, browser,
accessibility, representative restore/PITR, and production cutover acceptance
remain separate gates.
