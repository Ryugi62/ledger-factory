# Stage 3 — reviewer blind re-derivation

Written by the reviewer before opening `factory/ledger/stage-3.md`. The two longest sections of the stage-3
specification are "Effective time, recorded time, and corrections" and "`GET /statement`". Every normative
statement in them is listed below. IDs are reviewer-local (BC-xx, BS-xx).

## Effective time, recorded time, and corrections

- BC-01 The service distinguishes effective time (when money took effect) from recorded time (when it learned it).
- BC-02 Every payment has a revision history.
- BC-03 Revision 1: original amount, effective_at = recorded_at = created_at.
- BC-04 A seeded payment's supplied created_at is its original recorded/effective time; omission uses reset time.
- BC-05 Opening balance = seeded ending balance − net effect of the original seeded payments.
- BC-06 Corrections never change opening balances.
- BC-07 New accounts open at zero.
- BC-08 Seeded history is consistent and nonnegative (no validation required).
- BC-09 `POST /payments/{id}/corrections` requires an Idempotency-Key (§7 rules: missing → 400, replay 200, reuse 409).
- BC-10 Only the original sender may correct; an authenticated non-sender (including the receiver) → 403 `forbidden`.
- BC-11 Unknown payment → 404 `not_found`; no token → 401.
- BC-12 Body fields expected_revision, amount, effective_at, reason are all required (missing → 422).
- BC-13 expected_revision is a positive integer (0, negative, fraction → 422).
- BC-14 amount is an integer 0..1000000000; 0 reverses the whole payment; outside the range → 422.
- BC-15 reason is a string of 1..200 characters ("" or 201 → 422).
- BC-16 effective_at is an RFC 3339 instant with an offset, not later than now (future, naive or bare date → 422).
- BC-17 Invalid input → 422 `validation_failed`.
- BC-18 A correction changes neither parties nor visibility.
- BC-19 A correction appends an immutable revision.
- BC-20 201 body: payment_id, revision, amount, effective_at, recorded_at (server-assigned), reason.
- BC-21 Recorded times for one payment strictly increase (two corrections within one second still increase).
- BC-22 expected_revision ≠ current revision → 409 `stale_revision`.
- BC-23 A successful replay returns that original revision with 200, even after newer revisions.
- BC-24 Same key, different body → 409 `idempotency_key_reuse`.
- BC-25 The difference from the previous amount moves between the same two wallets, atomically.
- BC-26 An increase debits the original sender; a decrease debits the original receiver.
- BC-27 A currently unaffordable debit (against current available, given stage-2 holds) → 409 `insufficient_funds`.
- BC-28 Otherwise, any user's corrected balance negative at any effective-time boundary → 409 `historical_overdraft`.
- BC-29 Boundary balances include the combined effect of all movements at that instant.
- BC-30 Either failure preserves balances, revision history, statements and idempotency state (key not claimed).
- BC-31 The sum of balances equals the seeded total in every historical view.
- BC-32 The original payment and every original idempotent response remain unchanged.
- BC-33 `GET /activity` keeps showing the original payment; corrections are not new feed payments.
- BC-34 `GET /payments/{id}/revisions` → `{"revisions": [...]}` in revision order, including revision 1 with `reason: ""`.
- BC-35 Only the two parties can read revisions; a third party gets 404 even for a public payment; no token → 401.
- BC-36 `GET /me` and `GET /statement` accept optional `known_at` (RFC 3339 with offset).
- BC-37 Per payment, select its latest revision recorded at or before known_at; none recorded yet → the payment contributes nothing.
- BC-38 Omitted known_at = everything known when the read begins.
- BC-39 Selected revisions apply at their effective times.
- BC-40 as_of stays inclusive; the statement window stays half-open.
- BC-41 Both query instants may be in the future.
- BC-42 Invalid or empty instants → 422.
- BC-43 Supplied known_at is echoed exactly.
- BC-44 Statement order: selected effective_at, then payment id.
- BC-45 Entries keep payment, delta, balance_after and add the selected revision, effective_at and recorded_at.
- BC-46 `payment.amount` in an entry is the selected amount.
- BC-47 Zero-amount revisions appear as entries with zero delta.
- BC-48 No correction is counted alongside the revision it replaces.
- BC-49 With no corrections and no known_at, behaviour is unchanged.

## GET /statement

- BS-01 `GET /statement?from=&to=&limit=&offset=`; from and to optional.
- BS-02 from defaults to the opening of the wallet; to defaults to now.
- BS-03 limit/offset exactly as GET /requests (default 50, 1..200, offset ≥ 0, plain digits, 422).
- BS-04 Returns payments the caller sent or received in the half-open window [from, to).
- BS-05 Oldest first.
- BS-06 Each entry carries the caller's balance immediately after it (balance_after) and a delta.
- BS-07 Body: opening_balance, entries[{payment, delta, balance_after, …}], closing_balance, has_more (+ snapshot).
- BS-08 Order by created_at ascending (effective_at once corrected), ties by payment id ascending.
- BS-09 opening_balance = balance immediately before from; closing_balance = balance immediately before to.
- BS-10 opening_balance + Σ delta over the full window = closing_balance.
- BS-11 Sent payment → negative delta; received → positive.
- BS-12 Pagination changes neither balance_after nor opening/closing balances; they describe the full window.
- BS-13 Only payments sent or received by the caller appear, even when others' payments are public.
- BS-14 Invalid from/to (naive, bare date, empty) → 422 (by the instant rule).
- BS-15 has_more as on GET /requests.
