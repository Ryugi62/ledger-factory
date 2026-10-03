# Stage 1 — reviewer blind re-derivation

Written by the reviewer before opening `factory/ledger/stage-1.md`. The two longest sections of
the stage-1 specification are §8 (API) and §4 (Model). Every normative statement in them is listed
below. IDs are reviewer-local (B4-xx, B8-xx).

## §4 Model

- B4-01 The service has one currency, declared in the fixture.
- B4-02 Every API amount is an integer count of the currency's minor units.
- B4-03 Amounts with an integral numeric value are valid whatever their JSON spelling: `1000`, `1000.0`, `1e3`.
- B4-04 Booleans and strings are not numbers for amounts.
- B4-05 Every user has a handle, unique across the service.
- B4-06 Handles match `^[a-z0-9_]{1,20}$`.
- B4-07 A handle never changes once set.
- B4-08 Recipients are identified by handle.
- B4-09 Directory and user-search endpoints are out of scope (none required).
- B4-10 Seeded users take their handle from the fixture.
- B4-11 Signup derives the handle from the email: local part, lowercased.
- B4-12 Derivation replaces every character outside `[a-z0-9_]` with `_`.
- B4-13 Derivation truncates to 20 characters.
- B4-14 A derived handle that is already taken makes signup fail (409 `handle_taken`, §6).
- B4-15 New users start with balance 0.
- B4-16 New users can receive money immediately.
- B4-17 New users can be asked for money immediately.
- B4-18 A payment moves money from one wallet to another, immediately and atomically.
- B4-19 A payment is either sent directly or created by paying a request.
- B4-20 Request: requester receives, payer is asked.
- B4-21 Request lifecycle: `pending`, then exactly one of `paid`, `declined`, `cancelled` (terminal).
- B4-22 Only the payer may pay a request.
- B4-23 Only the payer may decline a request.
- B4-24 Only the requester may cancel a request.
- B4-25 A request may exceed the payer's balance; creation is not an error.
- B4-26 Such a request stays `pending` until paid/declined/cancelled.
- B4-27 Paying while short is 409 `insufficient_funds` and changes nothing.
- B4-28 Once money arrives, the same request becomes payable.
- B4-29 Visibility belongs to the payment; the payer chooses it when money moves.
- B4-30 A request carries no visibility field of its own.
- B4-31 A request never appears in anyone's activity feed.
- B4-32 `GET /activity` returns payments only.
- B4-33 A payment appears for a caller iff visibility is `public` or the caller is sender or receiver.
- B4-34 No other feed rule: no follow graph, no mute list.
- B4-35 `GET /requests` returns only requests where the caller is requester or payer.
- B4-36 A split is not a feed item.
- B4-37 Split-created requests are visible to their own two parties (only).
- B4-38 Payments fulfilling split requests follow the feed rule.
- B4-39 Visibility is one value, seen identically by both parties and third parties.
- B4-40 A private payment is hidden from third parties but visible to its own receiver (and sender).
- B4-41 `amount` at most 1000000000 on any single request.
- B4-42 No operation produces a balance outside ±2^53.
- B4-43 Monetary arithmetic is exact (no rounding error).
- B4-44 Fixture shape: `currency`, `minor_units`, `users[]` (id, email, password, display_name, handle, balance), `payments[]` (id, from_user_id, to_user_id, amount, note, visibility), `requests[]` (id, requester_id, payer_id, amount, note, status).
- B4-45 Seeded users can log in with the fixture password immediately.
- B4-46 Fixture `balance` is the post-payment balance; seeded payments are not replayed.
- B4-47 A negative fixture balance makes reset return 422 `validation_failed` and change nothing.
- B4-48 `minor_units` is 0, 2 or 3 (EUR 2, JPY 0, BHD 3).
- B4-49 No administrative balance endpoint is required.
- B4-50 Seeded payments/requests are visible through the API with their fixture ids (feed, request list, pay/decline/cancel of seeded pending requests).

## §8 API

### GET /me
- B8-01 Returns `user_id`, `display_name`, `handle`, `balance`, `currency`, `minor_units` for the caller.
- B8-02 Requires a bearer token (§6).

### POST /payments
- B8-03 Requires `Idempotency-Key` (§7 semantics).
- B8-04 Body `to_handle`, `amount`, optional `note` (default `""`), optional `visibility` (default `"public"`).
- B8-05 201 body fields: payment_id, from_user_id, from_handle, to_user_id, to_handle, amount, currency, note, visibility, request_id (null), created_at.
- B8-06 Caller balance below amount → 409 `insufficient_funds`.
- B8-07 amount < 1, > 1000000000, or non-integer → 422 `validation_failed`.
- B8-08 to_handle = caller's own handle → 422 `self_payment`.
- B8-09 note longer than 200 characters → 422 `validation_failed` (200 is valid).
- B8-10 visibility not `public`/`private` → 422 `validation_failed`.
- B8-11 Unknown handle → 404 `not_found`.
- B8-12 Debit and credit are one atomic step; never visible in one wallet only.
- B8-13 A failed payment leaves no trace in either wallet (balance, feed).
- B8-14 note stored and returned verbatim: no trimming/escaping/normalisation; Unicode and emoji round-trip byte for byte.

### POST /requests
- B8-15 Requires `Idempotency-Key`.
- B8-16 Body `payer_handle`, `amount`, `note`; caller is requester.
- B8-17 201 body fields: request_id, requester_id, requester_handle, payer_id, payer_handle, amount, currency, note, status `pending`, payment_id null, created_at.
- B8-18 amount < 1, > 1e9, non-integer → 422 `validation_failed`.
- B8-19 payer_handle = own handle → 422 `self_request`.
- B8-20 note > 200 → 422 `validation_failed`.
- B8-21 Unknown handle → 404 `not_found`.
- B8-22 Payer balance not checked; over-balance request is created pending.

### POST /requests/{id}/pay
- B8-23 Requires `Idempotency-Key`; only the payer may call it.
- B8-24 Body carries optional `visibility`, default `public`; payer's choice.
- B8-25 Replay must send identical body; `{}` vs `{"visibility":"public"}` with one key → 409 `idempotency_key_reuse`.
- B8-26 201 returns a payment exactly like POST /payments, with request_id set.
- B8-27 The request becomes `paid` and carries the new `payment_id`.
- B8-28 Request not pending → 409 `request_not_pending`.
- B8-29 Payer balance below amount → 409 `insufficient_funds`.
- B8-30 Caller not payer → 403 `forbidden`.
- B8-31 Unknown request → 404 `not_found`.
- B8-32 Replay of a successful pay returns 200 with the original payment body even when already paid; no extra money; never 409 `request_not_pending`.

### POST /requests/{id}/decline
- B8-33 Only the payer; no idempotency key; 200 with the request, status `declined`.
- B8-34 Declining an already-declined request → 200 with current state.
- B8-35 paid or cancelled → 409 `request_not_pending`.
- B8-36 Not the payer → 403 `forbidden`.

### POST /requests/{id}/cancel
- B8-37 Only the requester; no key; 200 with the request, status `cancelled`.
- B8-38 Already-cancelled → 200.
- B8-39 paid or declined → 409 `request_not_pending`.
- B8-40 Not the requester → 403 `forbidden`.

### GET /requests
- B8-41 Returns only requests where caller is requester or payer.
- B8-42 Newest first by created_at.
- B8-43 direction `incoming` (caller is payer), `outgoing` (caller is requester), absent = both.
- B8-44 status one of four, absent = all.
- B8-45 limit default 50, range 1..200; offset default 0, ≥ 0; otherwise 422.
- B8-46 Unknown direction or status value → 422.
- B8-47 has_more true iff items exist beyond the last returned.
- B8-48 Body `{ "requests": [...], "has_more": bool }`; items in the request shape.

### POST /splits
- B8-49 Requires `Idempotency-Key`.
- B8-50 Body amount, participant_handles, note.
- B8-51 Caller may be included or omitted in participant_handles.
- B8-52 Shares follow §9 equal split in given order.
- B8-53 One pending request per participant except the caller, for that share, caller as requester.
- B8-54 201 body: split_id, amount, currency, note, shares[{handle, amount}], requests[], created_at.
- B8-55 shares covers every participant incl. caller, given order, sums to amount.
- B8-56 requests covers every participant except caller, same order.
- B8-57 amount < 1, > 1e9, non-integer → 422.
- B8-58 participant_handles empty or with duplicates → 422.
- B8-59 note > 200 → 422.
- B8-60 Any unknown handle → 404 `not_found`.
- B8-61 Caller-only split is valid: one share, zero requests, `"requests": []`.
- B8-62 Split checks nobody's balance.
- B8-63 Share of 0 still produces a request (§9, applies to split).

### GET /activity
- B8-64 Payments visible by the §4 feed contract, newest first by created_at.
- B8-65 Body `{ "payments": [...], "has_more": bool }`.
- B8-66 Same-second order unspecified; stable pagination under concurrent writes not required.
- B8-67 limit/offset behave exactly as in GET /requests (defaults, ranges, 422, plain-digit rule).
