# Stage 4 — reviewer blind re-derivation

Written by the reviewer before opening `factory/ledger/stage-4.md`. The two longest sections of the stage-4
specification are "Batch corrections" and "Refunds and corrected history". Every normative statement in them is
listed below. IDs are reviewer-local (BB-xx, BR-xx).

## Refunds and corrected history

- BR-01 `POST /payments/{id}/refunds` with body `{"amount": N}` requires an Idempotency-Key (§7 rules; 9th path).
- BR-02 Only the original receiver may refund; anyone else (sender, third party) → 403 `forbidden`.
- BR-03 Unknown payment → 404 `not_found`; no token → 401.
- BR-04 The target may be a direct payment, a request payment or a capture (and, by the batch section, a settlement member).
- BR-05 The target may never be a refund → 422 `invalid_refund_target`.
- BR-06 Invalid amount (< 1, > 1e9, non-integer, string, boolean, missing) → 422 `validation_failed`.
- BR-07 Cumulative refunds ≤ the payment's current corrected amount, else 422 `refund_exceeds_payment` (boundary: equal is allowed).
- BR-08 A refund is a new payment in the opposite direction (receiver → sender).
- BR-09 Refund payment: `refund_of` = target id, `request_id: null`, `authorization_id: null`, note and visibility copied from the target.
- BR-10 201 with the refund payment; replay → 200 with the original body.
- BR-11 It moves money from the receiver's available funds (held funds excluded), else 409 `insufficient_funds`, atomically.
- BR-12 Refunds never reopen a request or authorization, nor restore a released hold.
- BR-13 Every other payment carries `refund_of: null` (all payment representations).
- BR-14 Refund payments appear in the feed and in statements as ordinary payments (derived: they are payments).
- BR-15 Stage-3 single corrections stay available for ordinary direct and request payments.
- BR-16 Captures and refund payments cannot be corrected → 422 `linked_payment_immutable`.
- BR-17 A correction cannot reduce a payment below its already-refunded amount → 422 `refund_exceeds_payment`.
- BR-18 Correction debits are checked against available funds.
- BR-19 Single corrections of settlement members → 422 `incomplete_settlement` (via batch rule; superseding stage 3's `linked_payment_immutable`).

## Batch corrections

- BB-01 `POST /correction-batches` requires a settlement operator and an Idempotency-Key; no token → 401, non-operator → 403 (same rules as settlements).
- BB-02 Body `{"corrections": [...]}` with 1..32 objects, else 422 `validation_failed`.
- BB-03 payment_ids must be distinct, else 422 `validation_failed`.
- BB-04 Every item has the ordinary correction fields and validation (expected_revision, amount 0..1e9, effective_at ≤ now, reason 1..200) → 422.
- BB-05 Unknown payment → 404; stale expected revision → 409 `stale_revision`.
- BB-06 The operator may correct ordinary, request and settlement payments of any wallets.
- BB-07 Captures and refunds stay immutable → 422 `linked_payment_immutable`.
- BB-08 Correcting any settlement member requires every member of that settlement in the batch, else 422 `incomplete_settlement`.
- BB-09 Members of one settlement must share identical effective instants (offset spellings may differ), else 422 `validation_failed`.
- BB-10 Single-payment corrections remain available for nonmembers.
- BB-11 Unknown fields are ignored.
- BB-12 Precedence: item errors in input order → settlement completeness (and member instant equality) → current available funds (`insufficient_funds`) → historical total/available at every boundary (`historical_overdraft`).
- BB-13 Item errors include linked_payment_immutable and refund_exceeds_payment.
- BB-14 Affordability uses the combined effect of all proposed revisions (net per wallet), not item by item.
- BB-15 A rejected batch changes no history, balances or idempotency records (key stays reusable).
- BB-16 201 with `correction_batch_id`, `recorded_at` and `revisions` in input order.
- BB-17 All new revisions share recorded_at, strictly later than the previous recorded_at of every member.
- BB-18 Each revision exposes correction_batch_id (and the ordinary revision fields; GET /revisions shows it).
- BB-19 Effective times cannot be later than now.
- BB-20 Original payments and receipts never change; original payment and settlement retries return their original bodies.
- BB-21 New statements reflect the new revisions; earlier snapshot tokens keep paging their frozen entries.
- BB-22 Replays → 200 with the original batch response; different body → 409.
- BB-23 A settlement payment may be refunded under the ordinary refund rules; refunds never change settlement membership.
- BB-24 Concurrent corrections (single or batch) sharing any expected payment revision cannot both succeed.
- BB-25 A stage-4 service accepts exports from stages 1–3, retaining settlement membership, corrections and snapshots.
- BB-26 Correction batches are the 10th idempotent write path; all §7 replay rules apply.
