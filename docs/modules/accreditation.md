# Accreditation module

Status: Revocable credentials and bounded offline check-in implemented  
Last updated: 2026-07-28

## Purpose and requirements

`maru.accreditation` implements the credential and degraded-arrival core of
REG-009, REG-020, ACC-001, ACC-004, ACC-005, NFR-005, and NFR-008. It owns
credential identity, credential events, authorized relay devices, signed
offline manifests, and reconciled offline operations.

## Owned data and invariants

- A credential belongs to exactly one organization, edition, account,
  registration, and active admission entitlement.
- Raw credential tokens are returned only at issue time in explicit test
  settings; Maru persists a verifier digest.
- Issue, check, reissue, and revoke append credential events. Revocation is
  durable and propagates into later manifests.
- A relay device is edition scoped and independently revocable.
- An offline manifest is signed with a deployment secret, expires, and contains
  only the minimum credential decision data.
- Each device operation ID is idempotent. Invalid, stale, revoked, duplicated,
  or contradictory arrivals are rejected or retained as reconciliation
  conflicts.

## Contracts

```text
GET  /api/v1/organizations/{organization_id}/editions/{edition_id}/accreditation/me/credentials
POST /api/v1/organizations/{organization_id}/editions/{edition_id}/registrations/{registration_id}/credentials
POST /api/v1/organizations/{organization_id}/editions/{edition_id}/credentials/{credential_id}/revoke
POST /api/v1/organizations/{organization_id}/editions/{edition_id}/offline/manifests
POST /api/v1/public/organizations/{organization_id}/editions/{edition_id}/offline/devices/{device_code}/check-ins
GET  /api/v1/organizations/{organization_id}/editions/{edition_id}/offline/conflicts
```

Issuance and revocation require edition-scoped accreditation authority and a
recent privileged step-up in production. Offline ingest authenticates the
device and validates its manifest instead of using a staff browser session.

## Operations, recovery, and limits

Before doors open, issue and inventory devices, rotate and protect
`MARU_OFFLINE_MANIFEST_SECRET`, generate a fresh manifest, rehearse a lost
network, revoke one credential, ingest operations twice, and resolve the
conflict queue. Conflicting or rejected operations block edition closure.

Automated integration tests cover issue, self-list minimization, signed
manifest creation, valid and duplicate ingest, revoked/missing device,
conflicts, revocation, authorization, and tenant isolation. Badge layout,
printer drivers, stock custody, zone policy, and a distributable relay client
remain operational/product work; the API and evidence boundary are present.
