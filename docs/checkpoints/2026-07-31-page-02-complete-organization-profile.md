# Checkpoint: Complete Page 2 organization profile and navigation

Date: 2026-07-31
Branch: `codex/page-02-create-organization`
Outcome: Revised Page 2 implemented and verified; product-owner inspection
pending

## Why Page 2 was revised

Owner inspection of the first Page 2 implementation identified two gaps:
creation appeared only as an inventory action instead of a stable menu item,
and the name-only form forced a follow-up even when the complete organization
profile was already known.

ADR 0033 supersedes ADR 0032 only for those presentation and field-scope
decisions. The original platform authorization, generated slug, Draft,
atomic-audit, and no-participation boundaries remain.

## Delivered behavior

Page 1 and Page 2 now share a persistent **Platform administration** side
navigation with **Organizations** and **+ Add**. The current destination uses
`aria-current`; at narrow widths the same navigation becomes a compact
horizontal block.

Page 2 keeps organization name as the only required operator value and adds
optional sections for:

- public description;
- registered legal name and formatted legal address;
- responsible representative, registration authority/identifier, and tax
  identifier;
- bounded additional imprint wording;
- website, general contact email, and E.164 telephone number; and
- ISO country/language plus IANA time-zone defaults.

The page shows that the resulting status is Draft. Slug and lifecycle are not
submitted fields and crafted values cannot override them. English and UTC
remain fallbacks when locale values are omitted.

The Awoostria imprint referenced during product discussion was used only to
identify common fact categories: legal name, address, representative, contact,
and registration reference. Tests and fixtures continue to use synthetic data.

## Security, privacy, and domain boundaries

Only an active platform administrator can load or submit Page 2. The service
repeats authorization and complete model validation. The organization and
successful audit event remain one transaction.

Legal, address, representative, registry, tax, contact, and imprint values are
organization-owned C1 data until a separate publication workflow exists. Audit
evidence lists field names without copying those values into metadata. The
additional imprint field explicitly excludes payment, identity-document, and
private case data.

Page 2 still creates no organization membership, Executive Board, convention
authority, series, edition, participation, registration, volunteer, or
workforce record. Activation remains unavailable until the IDN-012 governance
workflow exists.

## Migration and local data

`organizations.0004_organization_complete_profile` adds blank optional columns
and does not rewrite existing values. It applied successfully to
`maru_rebuild_empty`. The owner-created `MaruCon` record remains a Draft with
slug `marucon`; no browser-verification organization was added. The preserved
`maru` and `marucon_rehearsal` databases were not migrated or reset.

## Verification evidence

- 56 focused Page 2, baseline, and tenant-model checks are collected; the
  focused execution passed before the final full run.
- 482 complete PostgreSQL tests pass with 90.13% branch-aware coverage.
- Ruff format/lint pass for 256 files and strict mypy passes for 182 source
  files.
- Django system check, production-shaped deployment check, migration drift,
  and OpenAPI validation pass.
- Generated TypeScript is synchronized; preserved frontend typecheck, 20
  component tests, and production build pass.
- Browser QA covers both side-navigation destinations, Page 2 initial and
  optional-field validation states, the populated MaruCon inventory, desktop
  layout, and 390-by-844 layouts. Page 1 and Page 2 have no horizontal overflow
  and emitted no runtime warning/error.

The suite retains the known Django 6 URL-field default-scheme transition
warning from existing model-generated forms.

## Next action

The product owner should inspect the revised Page 2. Do not begin Page 3 until
that response. MaruCon's newly added optional fields are blank because Page 2
is a creation command, not an editor; Page 3 will own edits to that existing
record under the future platform-administrator/Executive-Board boundary.
