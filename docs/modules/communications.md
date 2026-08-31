# Communications module

Status: Exact-profile Registration inbox and email delivery implemented
Last updated: 2026-08-31

## Purpose and requirements

`maru.communications` implements the registration-service subset of MSG-001,
MSG-004, MSG-005, MSG-007, and NFR-004. It owns canonical account inbox
messages, per-organization delivery preferences, and channel delivery
evidence. It does not yet implement team conversations or announcements.

## Owned data and invariants

- `NotificationPreference` separates operational email from optional
  marketing email for one account and organization.
- `NotificationMessage` is the canonical localized inbox item, scoped to an
  organization and optional edition and account.
- `NotificationDelivery` records one idempotent channel projection, attempts,
  safe result, provider identity, retry time, and terminal failure.
- Domain-event identity plus account and message kind prevent duplicate
  attendee messages.
- Email address and rendered content stay out of audit metadata and metrics.

Registration notifications cover submission, guardian request, wait-list
offer, payment confirmation, payment expiry, deadline change, waiver,
cancellation, and restriction consequence. Operational notifications remain
eligible when marketing is disabled; an account can separately disable
operational email while retaining the canonical inbox.

Edition-scoped delivery is part of an immutable adoption manifest, not a
consequence of a retained message or a handler registration. The complete
`full_convention@1` profile pins Registration and account-restriction
notification routes. `workforce_only@1` pins only the internal Identity
restriction fact and creates no Communications message or delivery. The
separate non-edition catalog continues to permit an explicitly organization-
scoped account-restriction notice.

## Contracts and operation

Attendee APIs:

```text
GET /api/v1/me/notifications
POST /api/v1/me/notifications/{message_id}/read
GET|PUT /api/v1/me/notification-preferences/{organization_id}
```

Staff failure queue:

```text
GET /api/v1/organizations/{organization_id}/editions/{edition_id}/communication-delivery-failures
```

The transactional outbox invokes idempotent delivery services. Enqueue, worker,
replay, and the handler itself recheck the exact event/destination route before
rendered Communications state is loaded or written. Production must run the
effects workers, configure SMTP, monitor delivery age and permanent failure,
and assign the edition failure queue. Replaying an outbox message does not
create a second canonical message.

## Permissions, privacy, and archive

An attendee sees and marks read only their own messages whose originating
domain event still resolves the explicit organization-wide route or the
edition's exact profile route. A retained incompatible message is neither
listed nor mutable through the direct read URL. Failure-queue access is edition
scoped and omits body and protected profile fields. Sensitive
registration state changes remain in their owning modules; this module is a
projection, never the authority for payment or admission.

Pending or permanently failed edition deliveries block the closure manifest.
Retention follows the underlying operational purpose and approved policy.

## Verification and limits

Automated tests cover localization, preference behavior, deduplication,
transient retry, permanent failure, account scoping, read state, staff
authorization, and the rule that delivery failure cannot change registration.
Production SMTP credentials, provider reputation, bounce processing, and
operator ownership are deployment responsibilities. Team inboxes, arbitrary
conversations, SMS/push, and marketing campaigns are not implemented.
