# Catalog commerce operations runbook

Status: repository workflow implemented; production provider and fulfilment approval pending
Last updated: 2026-08-09

Never edit catalog, stock, order, payment, receipt, timeline, audit, or outbox
rows directly. Use the shared commands through **Catalog commerce** or the
strict API.

## Prepare and open a catalog

1. Select the exact edition and assign separate least-authority owners for
   definition, stock, payment reconciliation, charity review, fulfilment, and
   accounting export.
2. Open **Catalog commerce** in the selected edition. Create the draft catalog
   with its three-letter currency and operational reason. The browser carries
   a canonical idempotency key and current aggregate version with each command.
3. Add products and variants one command at a time. For charity lines, first
   confirm the exact edition charity selection; only its public label is shown
   as a beneficiary choice. Enter sale windows in the displayed edition time
   zone. Ambiguous or nonexistent daylight-saving times are rejected. For
   limited supporter products, configure finite stock and a hard ceiling; do
   not enable preorder.
4. Review sale windows, minor-unit prices, beneficiary, fulfilment, per-order
   limit, initial stock, and ceiling. Activate only after an independent
   operational review. Active definitions are intentionally immutable.
5. Verify My Maru with a synthetic attendee and verify that catalog payment
   never changes the attendee's admission entitlement. Confirm that My Maru,
   checkout, history, and staff responses carry private `no-store` controls and
   that an unrelated edition label is not rendered.

## Operate stock and orders

- Use **Catalog commerce** for a reasoned finite-stock adjustment. Reload after
  a stale-version response. A ceiling failure or committed-stock-floor failure
  means nothing changed; investigate before retrying.
- Use the purpose-scoped activity projection for who/when/action oversight.
  Command reasons remain in restricted evidence, not the broad projection.
- Reconcile hosted results only from an authenticated provider workflow owned
  by Finance. A redirect or browser return is never evidence of payment.
- Use deterministic demo payment only with synthetic data outside production.
- Monitor failed commands, provider exceptions, unpaid order age, outbox lag,
  and stock approaching zero. This slice does not yet expire unpaid orders
  automatically or complete fulfilment handover.

## Incident and recovery

If price, beneficiary, or stock was configured incorrectly, stop sales by
closing the sale window through a future governed definition version or by
operational containment; do not rewrite active rows. Preserve receipts,
payment events, timeline, audit, and outbox evidence. Restore tests must include
the catalog migrations, database guards, capability downgrade fences, and a
reconciliation comparison with the external provider/accounting system.

Do not approve production use until real hosted-provider authentication,
scheduled unpaid-order expiry/cancellation, refund policy, fulfilment custody,
accounting export, retention, alerting, and recovery rehearsal are complete for
the convention's actual operating model.
