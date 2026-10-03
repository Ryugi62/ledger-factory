# Stage 2 — reviewer blind re-derivation

Written by the reviewer before opening `factory/ledger/stage-2.md`. The two longest sections of the
stage-2 specification are "API" and "Model". Every normative statement in them is listed below.
IDs are reviewer-local (BM-xx, BA-xx).

## Model

- BM-01 The fixture gains `authorization_ttl_seconds` (service-wide default lifetime) and an `authorizations` array.
- BM-02 `authorization_ttl_seconds` applies to every authorization created through the API.
- BM-03 It defaults to 600 when omitted.
- BM-04 If supplied it must be a positive integer number of seconds (otherwise a reset error, 422).
- BM-05 Seeded authorizations carry their own absolute `expires_at`; the TTL does not apply to them.
- BM-06 Seeded authorization shape: id, from_user_id, to_user_id, amount, note, visibility, status, expires_at.
- BM-07 A user's seeded `balance` is `total`.
- BM-08 `available` is derived, never seeded: the service subtracts seeded open holds itself.
- BM-09 Seeded unexpired open holds summing above that user's balance → reset 422 `validation_failed`, nothing changes.
- BM-10 Seeded status is `open`, `captured`, `voided` or `expired`; only `open` holds funds.
- BM-11 A fixture may omit `authorizations`; omission means an empty list (stage-1 fixtures still load).
- BM-12 An authorization whose `expires_at` is at or before now is `expired` and holds no funds (boundary: equal = expired).
- BM-13 Reads and writes reflect expiry even if no request occurred at the deadline (lazy expiry is fine, but must be applied on every read/write).
- BM-14 `GET /authorizations` shows `status: "expired"` for clock-expired ones.
- BM-15 `GET /me` includes the released remainder in `available` after expiry.
- BM-16 Seeded expiry times are ≥ 1 h from reset time, past or future (a seeded open hold with past expires_at is expired at reset and does not count toward BM-09).
- BM-17 Newly created authorizations may have shorter lifetimes (TTL may be small, e.g. 1-2 s).

## API

### GET /me
- BA-01 Returns user_id, display_name, handle, balance, total, available, held, currency, minor_units.
- BA-02 `balance` and `total` are always equal.
- BA-03 `held` is the sum of open (unexpired) holds.
- BA-04 `available` = total − held, never negative.

### POST /authorizations
- BA-05 Requires `Idempotency-Key` (§7 replay rules apply; the 6th idempotent path).
- BA-06 The caller is the payer.
- BA-07 Body to_handle, amount, optional note (default ""), optional visibility (default public).
- BA-08 201 body: authorization_id, from_user_id, from_handle, to_user_id, to_handle, amount, captured_amount 0, currency, note, visibility, status open, expires_at, payment_id null, created_at (+ remaining_amount, payment_ids per extended mode).
- BA-09 expires_at = created_at + authorization_ttl_seconds.
- BA-10 Caller `available` below amount → 409 `insufficient_funds` (held funds cannot fund it).
- BA-11 amount < 1, > 1e9, non-integer → 422 `validation_failed`.
- BA-12 to_handle = own handle → 422 `self_payment`.
- BA-13 note > 200 or bad visibility → 422 `validation_failed`.
- BA-14 Unknown handle → 404 `not_found`.
- BA-15 Creating a hold moves no money: total unchanged, held += amount, available −= amount.
- BA-16 An open authorization is not a feed item and never appears in GET /activity.

### POST /authorizations/{id}/capture
- BA-17 Requires `Idempotency-Key` (7th idempotent path).
- BA-18 Only the receiver (`to`) may capture.
- BA-19 Body optional `amount`, default = remaining amount.
- BA-20 Replay must send identical body; `{}` vs `{"amount": N}` with one key → 409 `idempotency_key_reuse`.
- BA-21 201 returns a payment exactly in the POST /payments shape, with authorization_id set and request_id null.
- BA-22 Payment amount = captured amount; note and visibility copied from the authorization.
- BA-23 The capture payment appears in the feed by the ordinary visibility rule.
- BA-24 Payments created without an authorization carry `authorization_id: null` (all payment representations, incl. stage-1 paths and settlements); request_id semantics unchanged.
- BA-25 Default capture is final: status `captured`, captured_amount and payment_id set, uncaptured remainder released immediately in the same step.
- BA-26 Second capture after a final capture → 409 `authorization_not_open`.
- BA-27 `final` boolean, default true.
- BA-28 `final: false` with a remainder keeps status `open`; further captures up to that remainder.
- BA-29 Capturing the entire remainder closes it even with `final: false`.
- BA-30 A final capture closes it and releases any remainder.
- BA-31 `capture_exceeds_authorization` compares with the remaining amount; omitted amount = remainder.
- BA-32 captured_amount is cumulative; payment_id is the latest capture; payment_ids lists every capture in order.
- BA-33 Every authorization response includes remaining_amount (amount still held; 0 when closed).
- BA-34 Void and expiry can close a partially captured authorization, releasing only the remainder and preserving capture records.
- BA-35 New fields (final etc.) do not change idempotency body equality (canonical JSON value comparison as before).
- BA-36 Not open → 409 `authorization_not_open`.
- BA-37 expires_at at or before now → 409 `authorization_expired`.
- BA-38 amount above remainder → 422 `capture_exceeds_authorization`.
- BA-39 amount < 1 or non-integer → 422 `validation_failed`.
- BA-40 Caller not receiver → 403 `forbidden` (including non-parties).
- BA-41 Unknown authorization → 404 `not_found`.
- BA-42 Captures may spend the money reserved for them (capture never fails on available funds for its own hold); total moves payer→receiver; held decreases.
- BA-43 Each idempotent capture moves money once; cumulative captures never exceed the authorized amount (concurrent captures included).
- BA-44 `final` of the wrong JSON type → 400 `malformed_request` (§5 wrong type rule).

### POST /authorizations/{id}/void
- BA-45 Only the payer (`from`) may void; no idempotency key.
- BA-46 200 with the authorization, status voided, hold released.
- BA-47 Voiding an already-voided authorization → 200 with current state.
- BA-48 captured or expired → 409 `authorization_not_open`.
- BA-49 Caller not payer (including non-parties) → 403 `forbidden`; unknown id → 404.

### GET /authorizations
- BA-50 Only authorizations where the caller is payer or receiver.
- BA-51 Newest first by created_at.
- BA-52 direction outgoing (caller is payer), incoming (caller is receiver), absent = both; unknown value → 422.
- BA-53 status one of four or absent; clock-expired matches `expired`, never `open`; unknown value → 422.
- BA-54 limit/offset/has_more exactly as GET /requests (defaults 50/0, ranges, plain-digit rule, 422).
- BA-55 Body `{ "authorizations": [...], "has_more": bool }` (by analogy with /requests and /activity).
- BA-56 `/authorizations` serves HTML for `Accept: text/html` and JSON otherwise (UI section; shared path).
