# Charities module

Status: governed beneficiary directory and edition review/publication vertical implemented
Last updated: 2026-08-08

## Purpose and boundary

`maru.charities` owns organizer-reusable beneficiary profiles and the decision
to select and publish them for a particular edition. A beneficiary is not a
Maru `Organization` tenant. Every record remains owned by the organizing
tenant, and edition records are additionally scoped to one exact edition and
responsible Department.

This directly implements the bounded governed-partner workflow in FUR-011. It
is also the directory, review, and publication slice of the broader FUR-005
stewardship requirement, with governed media implementing the applicable part
of FUR-010. Campaign accounting, donations, settlement, and public financial
reporting remain future FUR-005 work and must not use this module as a ledger.

## Records and lifecycle

- `CharityPartner` holds legal/imprint and public names, public descriptions,
  location, website, restricted contact details, and `draft`, `active`, or
  `retired` lifecycle state.
- `CharityPartnerMedia` records owner, license basis, usage scope, attribution,
  expiry, review state, and an approved public reference. A submitter cannot
  approve their own media.
- `CharitySelection` connects one reusable partner to one edition and
  responsible Department. It moves through `proposed`, `submitted`, and an
  attributed `confirmed` or `rejected` decision.
- `CharitySelectionTimelineEntry` is append-only. Status reasons and private
  comments remain restricted to exact-selection review access.
- `CharityPublicationSnapshot` is append-only and separate from confirmation.
  An independent publisher approves a minimized immutable public rendition;
  withdrawal does not rewrite its history.
- `CharityCommandReceipt` provides scope-bound idempotency evidence.

Only an active partner with a confirmed and currently published selection
appears publicly. The projection reads the current immutable snapshot and only
currently approved, unexpired media owned by that selected partner. Legal
contacts, postal address, rejection reasons, private comments, actor identity,
and review history are never included.

## Authorization and evidence

The capability catalog provides organization-scoped partner view/manage,
edition-scoped queue view/propose, and exact-resource selection
view/review/comment/publish capabilities. Exact selection targets resolve
through a deterministic typed binding to the responsible Department. A Maru
platform administrator receives no automatic convention-subject authority;
an explicit in-scope grant is required.

Commands are closed, transactional, optimistic-versioned, and idempotent.
Privileged mutations append minimized audit, domain-event, and outbox evidence
in the same transaction. Restricted partner-directory and private timeline
reads are audited with an explicit access purpose. Decision reasons and private
comments stay in purpose-scoped append-only records and are excluded from
event/outbox payloads.

## Interfaces

The same authenticated shell exposes the edition charity workspace and exact
selection review page under the selected convention context. The navigation
item is projected only after `charities.view_review_queue` is authorized.

Versioned APIs expose:

- a public minimized edition charity list;
- organizer-scoped partner and governed-media commands; and
- edition/exact-selection proposal, review, comment, publication, and
  withdrawal commands.

Staff APIs authorize before parsing, reject unknown fields and query
parameters, require canonical `Idempotency-Key` UUIDs for mutations, and map
unavailable resources without cross-tenant disclosure.

## Data handling, recovery, and operations

Public snapshots are public data. Organizer contact details and ordinary
decision reasons are restricted operational data; private comments are
purpose-scoped restricted data. Retention and deletion policy must account for
the append-only audit/decision evidence and any legal reporting duty before a
partner is retired. Retirement and publication withdrawal are the supported
non-destructive controls.

Migrations `charities.0001` and `charities.0002` create the schema and database
write-integrity guards. `authorization.0013` adds the capability minimum-scope
catalog, charity resource kind, typed binding validation, and downgrade fences.
Rollback is permitted only while no added capability or resource binding is in
use; otherwise operators must revoke/migrate authority deliberately before
contracting the catalog. Monitor command failures, denied policy decisions,
outbox delivery, and migration/readiness checks without logging private fields.
