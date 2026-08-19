# Logistics operations runbook

Last updated: 2026-08-09

## Operating boundary

Logistics records declared equipment, stock, boxes, containers, vehicles,
custody, and operational contacts. Do not use it for live person tracking,
GPS telemetry, general participant dossiers, free-form incident casework, or
supplier invoices. A keyholder is a physical responsibility and receives no
software access from that fact.

Use the exact organization and edition in every command. Organization-global
storage and edition-allocated storage are distinct scopes. Never copy private
contact values into party profiles, event reasons, labels, generic audit
metadata, manifests, logs, or support tickets.

## Routine workflow

1. Register a reusable external owner/provider identity with only legal/public
   facts and its declared role.
2. Add a purpose-bound restricted address only when pickup, storage, return,
   delivery, or provider coordination requires it. Choose the shortest lawful
   retention horizon that still covers the operational obligation.
3. Register the physical storage graph. Use sites/areas/racks/containers/boxes,
   vehicles/loading/staging nodes, or an active exact-edition venue room. Do
   not create a node for a person or postal address.
4. Register serialized assets, bulk lots, physical key copies, reusable kits,
   and opaque QR labels. Each physical key copy is a separate record.
5. Record loan/rental intervals and return obligations. A return address must
   remain retained through the due time.
6. Build and seal a manifest from current catalog and location data. Resolve
   discrepancies before loading or receipt; do not edit a sealed line or
   current state directly.
7. Append receive/pack/unpack/move/load/unload/handover/count/condition/damage/
   return events using the displayed expected sequence. Re-read the workspace
   after a version conflict.
8. Stage Tech uses the receiving view to reconcile expected boxes and contents
   on site. Record differences as count/condition/damage facts and owned
   discrepancies.

Equipment offers stay Pending and person-owned until an authorized Logistics
review. Reject an offer when ownership, availability, contact retention, or
return terms are insufficient. Acceptance creates governed inventory/contract
facts but never workforce membership or access.

`Completed` freezes manifest definition and route facts. It does not claim that
all late physical reconciliation is finished: Stage Tech may append one
canonical manifested receipt/reconciliation event per line and event type after
completion. Do not repeat a traversal event or edit a completed manifest line.

## Operational and contract retention

- Restricted contact values have their own purpose and horizon and are disposed
  independently from custody or contract evidence.
- Offer title/description, item facts, and ownership statements are visible only
  to the offerer and authorized Logistics staff. The organizer owns their
  retention policy; the trigger is closure of the offer, return, dispute,
  audit, and legal-evidence relationship. Minimize free text and never copy it
  into audit metadata, labels, or logs.
- Provider/business records contain legal/public identity only and are visible
  to authorized catalog/operations staff. The organizer owns retention and
  reviews them when the supplier/owner/rental relationship closes. There is no
  governed Party-retirement command yet, so retirement and final relationship
  disposal remain open work rather than a manual database edit.
- Immutable movement, manifest, agreement, acceptance, and command evidence may
  outlive disposed contact values where the organizer's operational, audit, or
  legal basis requires it. Preserve identifiers and closed facts; redact or
  avoid duplicating contact content.

## Restricted contact reads

Select one closed access-purpose code: pickup coordination, provider contact,
return coordination, inventory verification, or incident response. Maru
reauthorizes the exact address, validates purpose and retention, and appends a
sensitive-read audit before showing values. The result token contains only an
opaque audit/reference ID and expiry. Responses are private, no-store,
no-referrer, and must not be shared or bookmarked.

If an address is expired or disposed, obtain a newly supplied lawful contact;
do not restore redacted values from application logs or generic history.

## Contact-retention scheduler

Run global and edition records separately. Use canonical lower-case UUIDs.

```powershell
python manage.py dispose_expired_logistics_contacts `
  --organization-id 11111111-1111-4111-8111-111111111111 `
  --edition-id 22222222-2222-4222-8222-222222222222 `
  --limit 100
```

For organization-global addresses, replace `--edition-id ...` with
`--global-scope`. A scheduler may supply `--correlation-id` for stable job
traceability. The command is bounded and idempotent; rerunning a completed
scope returns `disposed=0`.

Disposal redacts person/party links, recipient, email, phone, postal address,
and access instructions. It retains minimal UUID/scope/purpose/version evidence
and produces an audited outbox fact. A record is held when an active offer or
return obligation still needs the address. Investigate a persistently held
expired record by correcting the obligation horizon through a governed
command; do not force-delete it.

## Offline scanning

- Distribute only a bounded, expiring snapshot for the exact edition and
  device code.
- Every operation needs an ordered sequence, canonical idempotency UUID,
  expected subject sequence, and known label.
- A device never becomes source of truth. Upload batches for server-side
  reconciliation before relying on the current projection.
- Review stale sequence, unknown label, cross-edition, containment-cycle,
  quantity, condition, and source/destination discrepancies.
- Never place contact values, free-text operator reasons, or person locations
  in offline labels or operation payloads.

## Monitoring and incident response

Monitor, by organization and edition:

- denied and unavailable exact-scope decisions;
- retry/version/state/containment conflicts;
- manifest discrepancies and overdue returns;
- offline batches in Review;
- retention records held past their configured horizon;
- `logistics.record.changed.v1` outbox age, retries, and quarantine; and
- authorization binding/readiness fingerprint failures.

Log only UUIDs, closed reason/action codes, counts, versions, and correlation
IDs. Do not log contact/address values, manifest contents, provider terms,
ownership statements, or free-text reasons.

For a suspected custody error, preserve the append-only event and audit trail,
stop unsafe physical movement, verify the real item/key/box, and append the
correct count/condition/movement event. Open and investigate a new discrepancy
when the correction needs evidence; no discrepancy-resolution command exists.
For an immediate
real-world safety or security issue, follow the convention incident plan;
software reconciliation must not delay action.

## Backup, restore, and deployment

Before deployment or restore, verify:

- Venues migration `0001` is applied before Logistics `0001` as the single
  migration owner of the shared PostgreSQL `btree_gist` extension;
- keyholder and agreement exclusion constraints exist;
- authorization minimum-scope and typed-binding functions match their pinned
  authorization readiness fingerprints;
- Logistics trigger, function, constraint, extension, owner, search-path, ACL,
  and relation-privilege contracts match the separate Logistics schema
  readiness inventory;
- the capability catalog contains exactly the supported Logistics codes and
  minimum scopes; and
- event registry and internal handler acknowledge
  `logistics.record.changed.v1`.

Run focused migration drift, authorization readiness, URL reversal, template,
and adversarial PostgreSQL tests. Roll back application code only when its
schema and capability contract remain compatible. Authorization downgrade is
fenced once Logistics capabilities or manifest bindings are durably used.
