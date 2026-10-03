# Pocketful — Stage 1 requirement ledger

Source: the stage-1 specification text handed over by @coordinator (parts 1/2 and 2/2), read only from that
text; no shipped checks were opened. Every row below is one normative statement (or one table row / state
kind). `★` marks statements a quick reading would miss. `probe` names the black-box probe(s) in
`factory/probes/stage-1/` that exercise the row (`module.function`); `manual` rows say why and what the reviewer
does instead. Rows tagged "(derived)" or "Reading:" make an implied consequence explicit.

## Earlier stages

Stage 1 is the first stage: no earlier ledger rows exist, none are changed, and no review notes were forwarded
(row S1-224). Row S1-220 is the placeholder for "everything earlier still holds": from stage 2 on, the stage-2
ledger must point back at this file and re-run `run_all.py` from `factory/probes/stage-1/` unchanged.

## Readings chosen where the specification is silent or ambiguous

1. **Timestamps** (§3.4): `Z` and `±hh:mm` are both accepted as an "explicit offset"; fractional seconds allowed.
2. **Key scope** (§7): a claimed key is identified by (user, method+path, key). Same key + different path is a
   first use even with a different body ("a different request, not a replay").
3. **Email vs handle collision** (§6): when a signup collides on both, `email_taken` is expected (first table
   row); `handle_taken` is only asserted when the email is new.
4. **Wrong JSON types** (§5): array/object `amount`, non-object body, non-string handles → 400
   `malformed_request`; string/boolean/number-with-fraction `amount`, non-string `note`, bad `visibility` → 422.
   `null` for a required string or number is accepted as 400 or 422 (not asserted tighter).
5. **Settlement batch shape** (§11 overrides §5): `transfers` missing / not an array / containing a non-object →
   422 `validation_failed`, not 400. A wrongly typed inner field (e.g. numeric `from_handle`) is accepted as 400 or 422.
6. **`note` length** (§8): 200 *characters* (Unicode code points); 200 × `é` and 200 × emoji must pass, 201 fail.
7. **Optional `note`** on `POST /requests`, `POST /splits` defaults to `""` (stated only for payments); the
   payment created by paying a request carries an unspecified note — probes do not assert it.
8. **Third party** calling pay/decline/cancel on a request they are not party to: 403 or 404 both accepted;
   the other party (requester paying, payer cancelling) must get 403. Order of checks: permission (403) before
   state (409 `request_not_pending`) before funds (409 `insufficient_funds`).
9. **Splits**: `n` is the number of listed handles (the caller counts only if listed); a split moves no money.
   Paying a 0-share request is unspecified; probes never do it.
10. **Same-second ordering**: `GET /activity` ties are unspecified (§8); `GET /requests` is "newest first" and is
    asserted only for writes ≥1.1 s apart. Round-trip probes compare lists as id-keyed sets.
11. **Unknown route / `minor_units` values other than 0/2/3 / duplicate emails differing in case**: unspecified, not probed.
12. **`settlement_id` key** is present (null) on every payment representation (payments, pay, activity, settlement
    members), per "nonmembers expose null for that field".
13. **Export** may be any JSON object; probes only require `track`, `format_version`, `state` and that it contains
    no plaintext password (S1-079).
14. **Latency**: every probe call is timed; any response slower than 5 s (10 s for `/_test/*`) fails the run via the
    global convention check (S1-015). Start-to-healthy (S1-013) can only be measured from the moment the runner
    starts polling `/health`.

## Ledger

| ID | section | requirement (verbatim excerpt) | kind | probe |
|---|---|---|---|---|
| S1-001 | §1 | Users can send money by handle, request money and split bills. | behaviour | `p03_payments.payment_happy_path_moves_money_atomically`, `p05_splits_money.split_shape_requests_and_no_money_moves` |
| S1-002 | §1 | Payments appear in an activity feed with public or private visibility. | behaviour | `p06_feed.feed_contract_public_or_party` |
| S1-003 | §1 | Authorized operators can submit groups of transfers as settlements. | behaviour | `p10_settlements.settlement_response_members_and_feed` |
| S1-004 | §1 | Only the HTTP API is required. | behaviour | manual — nothing to probe beyond the HTTP API; no screens exist in stage 1 |
| S1-005 | §1 | ★ The sum of wallet balances always equals the total seeded by the last `POST /_test/reset`. | concurrency | `p01_runtime.reset_replaces_all_state_and_is_repeatable`, `p05_splits_money.many_splits_paid_in_full_conserve_the_total`, `p07_idempotency.concurrent_identical_requests_take_effect_once`, `p08_concurrency.overdraft_race_never_goes_negative`, `p08_concurrency.spending_the_whole_balance_many_times_succeeds_once`, `p08_concurrency.opposing_transfers_do_not_deadlock_or_lose_money`, `p08_concurrency.mixed_load_at_50_in_flight_keeps_invariants`, `p10_settlements.settlement_never_shows_a_transient_negative_balance`, `p10_settlements.competing_settlements_and_payments_stay_atomic` |
| S1-006 | §1 | ★ No wallet balance may be negative, including transiently. | concurrency | `p03_payments.insufficient_funds_boundary_and_no_trace`, `p08_concurrency.overdraft_race_never_goes_negative`, `p08_concurrency.spending_the_whole_balance_many_times_succeeds_once`, `p08_concurrency.opposing_transfers_do_not_deadlock_or_lose_money`, `p08_concurrency.mixed_load_at_50_in_flight_keeps_invariants`, `p10_settlements.affordability_is_net_and_all_or_nothing`, `p10_settlements.settlement_never_shows_a_transient_negative_balance`, `p10_settlements.competing_settlements_and_payments_stay_atomic` |
| S1-007 | §1 | ★ A payment request may move money at most once. | concurrency | `p04_requests.paying_a_request_creates_a_payment_with_payer_chosen_visibility`, `p07_idempotency.concurrent_identical_requests_take_effect_once`, `p08_concurrency.a_request_moves_money_at_most_once`, `p08_concurrency.pay_versus_cancel_and_decline_race_is_consistent` |
| S1-008 | §1 | All amounts are exact integer counts of minor units. | behaviour | `p01_runtime.amount_accepts_integral_numbers_only`, `p01_runtime.large_balances_stay_exact_below_2_pow_53` |
| S1-009 | §1 | Deposits, top-ups, withdrawals, cards and bank integrations are out of scope. Money moves only between existing wallets. | behaviour | `p03_payments.payment_validation_errors` |
| S1-010 | §2 | Deliver an HTTP service, a `Dockerfile` and a `RUN.md` with a command that builds and starts the service without manual setup. | behaviour | manual — reviewer builds the image and follows RUN.md; probes only need a base URL |
| S1-011 | §2 | The image must run on its own with `-e PORT=<port>` and a port mapping. | behaviour | manual — reviewer runs `docker run -e PORT=… -p …`; the probes are run against that mapped URL |
| S1-012 | §2 | Runtime networking has no outbound access. All runtime dependencies, initialization and seed data must work within that single container. | limit | manual — reviewer runs the container with `--network none` (plus a port mapping) and re-runs the probes |
| S1-013 | §2 | Start to first healthy response \| 60 s | time | `p01_runtime.health` |
| S1-014 | §2 | Concurrent requests \| up to 50 in flight | limit | `p08_concurrency.overdraft_race_never_goes_negative`, `p08_concurrency.opposing_transfers_do_not_deadlock_or_lose_money`, `p08_concurrency.mixed_load_at_50_in_flight_keeps_invariants`, `p08_concurrency.concurrent_signups_with_the_same_email_or_handle`, `p08_concurrency.fifty_requests_in_flight_all_answered_in_time`, `p10_settlements.competing_settlements_and_payments_stay_atomic` |
| S1-015 | §2 | ★ Per-request timeout \| 5 s (10 s for `POST /_test/reset`) | time | `run_all.global_conventions`, `p08_concurrency.mixed_load_at_50_in_flight_keeps_invariants`, `p08_concurrency.fifty_requests_in_flight_all_answered_in_time`, `p09_export.reset_export_and_import_of_a_larger_state_fit_in_10_seconds` |
| S1-016 | §2 | CPU \| 2 vCPU … Memory \| 2 GiB | limit | manual — reviewer runs the image with `--cpus 2 --memory 2g`; the 50-in-flight probes then run under those limits (a failure shows as 5xx/timeouts) |
| S1-017 | §2 | Runtime assets and dependencies must be included in the image. … Disk \| ephemeral; state need not survive a container restart | limit | manual — build-time property; checked by running with no network (row 12) |
| S1-018 | §3.1 | Listen on `0.0.0.0` using the `PORT` environment variable, default `8080`. | behaviour | manual — the probes choose the port via the base URL; reviewer also starts once without PORT and checks 8080, and once with another PORT |
| S1-019 | §3.2 | GET /health  ->  200  {"status": "ok"} | behaviour | `p01_runtime.health`, `p08_concurrency.fifty_requests_in_flight_all_answered_in_time` |
| S1-020 | §3.3 | ★ Replace all service state with the fixture in the request body (§4). When reset returns 204, subsequent requests must see only that fixture. | behaviour | `p01_runtime.reset_replaces_all_state_and_is_repeatable`, `p01_runtime.reset_with_negative_balance_is_rejected_and_changes_nothing` |
| S1-021 | §3.3 | Repeated resets are supported. This test endpoint must be enabled in the delivered image and requires no authentication. | behaviour | `p01_runtime.reset_replaces_all_state_and_is_repeatable` |
| S1-022 | §3.4 | Requests and responses are `application/json; charset=utf-8`. | behaviour | `run_all.global_conventions`, `p01_runtime.conventions_unknown_fields_and_query_params_are_ignored` |
| S1-023 | §3.4 | Timestamps in responses are RFC 3339 with an explicit offset, e.g. `2026-09-24T19:00:00+02:00`. | behaviour | `p01_runtime.seeded_users_can_log_in_and_keep_their_handles` |
| S1-024 | §3.4 | Unknown fields in a request body are ignored, never an error. | behaviour | `p01_runtime.conventions_unknown_fields_and_query_params_are_ignored`, `p10_settlements.settlement_validation_errors_claim_no_key_and_leave_no_trace` |
| S1-025 | §3.4 | Unknown query parameters are ignored. | behaviour | `p01_runtime.conventions_unknown_fields_and_query_params_are_ignored` |
| S1-026 | §3.4 | IDs are opaque strings of at most 64 characters. | limit | `p01_runtime.seeded_users_can_log_in_and_keep_their_handles` |
| S1-027 | §4 | The service has **one currency**, declared in the fixture. Every amount in the API is an integer count of its minor units | behaviour | `p01_runtime.currency_and_minor_units_are_reported_per_fixture` |
| S1-028 | §4 | ★ API amounts must have an integral numeric value: JSON `1000`, `1000.0` and `1e3` all represent the same valid minor-unit amount. | behaviour | `p01_runtime.amount_accepts_integral_numbers_only` |
| S1-029 | §4 | Booleans and strings are not numbers here. | error | `p01_runtime.amount_rejections_are_422` |
| S1-030 | §4 | Every user has a **handle**: unique across the service, matching `^[a-z0-9_]{1,20}$`, and never changing once set. | behaviour | `p01_runtime.seeded_users_can_log_in_and_keep_their_handles`, `p02_auth.derived_handle_follows_the_rule`, `p02_auth.handle_and_email_conflicts` |
| S1-031 | §4 | Seeded users take their handle from the fixture. | behaviour | `p01_runtime.seeded_users_can_log_in_and_keep_their_handles` |
| S1-032 | §4 | ★ A user created through `POST /auth/signup` … has one **derived** from their email: take the local part, lowercase it, replace every character outside `[a-z0-9_]` with `_`, and truncate to 20 characters. | behaviour | `p02_auth.derived_handle_follows_the_rule` |
| S1-033 | §4 | ★ If that handle is already taken the signup fails; see the signup table in §6. | error | `p02_auth.handle_and_email_conflicts`, `p08_concurrency.concurrent_signups_with_the_same_email_or_handle` |
| S1-034 | §4 | ★ New users start with a balance of `0`. They can receive money and be asked for money immediately. | behaviour | `p02_auth.signup_then_login_and_new_user_starts_empty`, `p04_requests.request_creation_shape_and_no_balance_check` |
| S1-035 | §4 | A **payment** moves money from one wallet to another, immediately and atomically. It is either sent directly or created by paying a request. | behaviour | `p03_payments.payment_happy_path_moves_money_atomically`, `p04_requests.paying_a_request_creates_a_payment_with_payer_chosen_visibility` |
| S1-036 | §4 | A request is `pending`, and then exactly one of `paid`, `declined` or `cancelled`. Only the payer may pay or decline it; only the requester may cancel it. | behaviour | `p04_requests.request_creation_shape_and_no_balance_check`, `p04_requests.decline_semantics`, `p04_requests.cancel_semantics`, `p08_concurrency.pay_versus_cancel_and_decline_race_is_consistent` |
| S1-037 | §4 | ★ **A request may exceed the payer's balance.** … an attempt to pay it while short is `409 insufficient_funds` and changes nothing. Money can arrive later and the same request then becomes payable. | behaviour | `p04_requests.pay_error_cases_and_late_funds`, `p07_idempotency.key_reused_after_a_4xx_failure_is_a_first_use` |
| S1-038 | §4 | ★ **Visibility belongs to the payment, not the request.** The payer chooses it when the money moves. A request carries no visibility of its own and never appears in anyone else's feed. | behaviour | `p04_requests.paying_a_request_creates_a_payment_with_payer_chosen_visibility`, `p06_feed.requests_and_splits_never_appear_in_the_feed` |
| S1-039 | §4 | ★ A payment appears for a caller **if and only if** its `visibility` is `public`, **or** the caller is its sender or its receiver. There is no other rule, no follow graph and no mute list. | behaviour | `p01_runtime.seeded_payments_and_requests_follow_feed_contract_and_balances_are_not_replayed`, `p04_requests.paying_a_request_creates_a_payment_with_payer_chosen_visibility`, `p06_feed.feed_contract_public_or_party` |
| S1-040 | §4 | ★ Requests never appear in the activity feed; they are read through `GET /requests`, which returns only requests where the caller is the requester or the payer. | behaviour | `p01_runtime.seeded_payments_and_requests_follow_feed_contract_and_balances_are_not_replayed`, `p04_requests.request_creation_shape_and_no_balance_check`, `p04_requests.request_listing_filters_pagination_and_visibility`, `p06_feed.feed_contract_public_or_party`, `p06_feed.requests_and_splits_never_appear_in_the_feed` |
| S1-041 | §4 | ★ A split is not a feed item. The requests it creates are visible to their own two parties, and the payments that eventually fulfil them follow the rule above. | behaviour | `p05_splits_money.split_shape_requests_and_no_money_moves`, `p06_feed.requests_and_splits_never_appear_in_the_feed` |
| S1-042 | §4 | ★ Visibility is **one value on the payment**, seen identically by both parties and by everyone else. A `private` payment is hidden from third parties, not from its own receiver. | behaviour | `p01_runtime.seeded_payments_and_requests_follow_feed_contract_and_balances_are_not_replayed`, `p04_requests.paying_a_request_creates_a_payment_with_payer_chosen_visibility`, `p06_feed.feed_contract_public_or_party` |
| S1-043 | §4 | ★ `amount` is at most `1000000000` on any single request, and no operation produces a balance outside ±2⁵³. Monetary arithmetic must preserve exact minor-unit values without rounding error. | limit | `p01_runtime.amount_accepts_integral_numbers_only`, `p01_runtime.amount_rejections_are_422`, `p01_runtime.large_balances_stay_exact_below_2_pow_53` |
| S1-044 | §4 | Seeded users must be able to log in with the given password immediately. | behaviour | `p01_runtime.seeded_users_can_log_in_and_keep_their_handles` |
| S1-045 | §4 | ★ `balance` is the wallet balance **after** every seeded payment has been applied. Seeded numbers are consistent; you do not replay seeded payments against balances. | behaviour | `p01_runtime.seeded_payments_and_requests_follow_feed_contract_and_balances_are_not_replayed` |
| S1-046 | §4 | ★ A `balance` below zero in a fixture is a reset error: return `422 validation_failed` from `POST /_test/reset` and change nothing. | error | `p01_runtime.reset_with_negative_balance_is_rejected_and_changes_nothing` |
| S1-047 | §4 | `minor_units` is `0`, `2` or `3`. Fixtures use `EUR` (2), `JPY` (0) and `BHD` (3). | behaviour | `p01_runtime.currency_and_minor_units_are_reported_per_fixture` |
| S1-048 | §4 | ★ "payments": [ { "id": "p_1", "from_user_id": … } ], "requests": [ { "id": "rq_1", … "status": "pending" } ] (fixture format). Reading: seeded payments/requests keep their ids, statuses and visibility and obey the feed rule from the first request after reset. | behaviour | `p01_runtime.seeded_payments_and_requests_follow_feed_contract_and_balances_are_not_replayed` |
| S1-049 | §4 | An administrative balance endpoint is out of scope. | behaviour | `p03_payments.payment_validation_errors` |
| S1-050 | §5 | ★ Every 4xx and 5xx response carries this body: `{ "error": { "code": "insufficient_funds", "message": "human readable, any wording" } }` | error | `run_all.global_conventions` |
| S1-051 | §5 | ★ 400 \| `malformed_request` \| Unparseable body, or a field of the wrong JSON type | error | `p02_auth.signup_login_validation_and_failures`, `p05_splits_money.split_validation_errors_leave_no_trace` |
| S1-052 | §5 | 400 \| `missing_idempotency_key` \| Required `Idempotency-Key` header absent or empty | error | `p03_payments.shared_ranges_and_query_parameters`, `p07_idempotency.key_is_required_on_all_five_paths` |
| S1-053 | §5 | 401 \| `unauthenticated` \| Missing, malformed or unknown bearer token | error | `p02_auth.endpoints_require_a_bearer_token` |
| S1-054 | §5 | 403 \| `forbidden` \| Authenticated, but not permitted to touch this resource | error | `p03_payments.shared_ranges_and_query_parameters` |
| S1-055 | §5 | 404 \| `not_found` \| No such resource, or not visible to this caller | error | `p03_payments.shared_ranges_and_query_parameters` |
| S1-056 | §5 | 409 \| `idempotency_key_reuse` \| Key already used by this caller with a different request body | error | `p03_payments.shared_ranges_and_query_parameters`, `p07_idempotency.same_key_different_body_is_409_before_any_validation` |
| S1-057 | §5 | 422 \| `validation_failed` \| A required field or query parameter is missing, or a stated rule is violated with no more specific code | error | `p02_auth.signup_login_validation_and_failures`, `p03_payments.payment_validation_errors`, `p04_requests.request_validation_errors`, `p05_splits_money.split_validation_errors_leave_no_trace`, `p10_settlements.settlement_validation_errors_claim_no_key_and_leave_no_trace` |
| S1-058 | §5 | ★ A field of the correct JSON type with an invalid format or out-of-range value gives 422 `validation_failed`, unless an endpoint specifies a different error. | error | `p01_runtime.amount_rejections_are_422`, `p03_payments.payment_validation_errors` |
| S1-059 | §5 | ★ invalid `amount` values (including strings and booleans), non-string `note` values (including `null`), and any `visibility` other than `public` or `private` are 422 `validation_failed`. Omission alone selects the optional-field defaults. Other wrong JSON types follow the rule below. | error | `p01_runtime.amount_rejections_are_422`, `p03_payments.payment_validation_errors`, `p04_requests.request_validation_errors`, `p05_splits_money.split_validation_errors_leave_no_trace`, `p10_settlements.settlement_validation_errors_claim_no_key_and_leave_no_trace` |
| S1-060 | §5 | Omission alone selects the optional-field defaults. | behaviour | `p01_runtime.conventions_unknown_fields_and_query_params_are_ignored` |
| S1-061 | §5 | ★ An integer-valued **query parameter** is written as plain decimal digits: `1e9`, `4.0` and `+4` are 422 `validation_failed` whatever their numeric value. | error | `p03_payments.shared_ranges_and_query_parameters` |
| S1-062 | §5 | ★ Reserve 400 `malformed_request` for a body that does not parse or a field of the wrong type. (Reading: a body that parses but is not a JSON object, and array/object-valued `amount`, are also 400; `null` for a required string/number field is accepted as 400 or 422.) | error | `p01_runtime.amount_rejections_are_422`, `p03_payments.payment_validation_errors` |
| S1-063 | §5 | ★ `Idempotency-Key` \| 1 to 255 characters \| 422 `validation_failed` | limit | `p03_payments.shared_ranges_and_query_parameters` |
| S1-064 | §5 | `limit` \| integer 1 to 200 \| 422 `validation_failed` | limit | `p03_payments.shared_ranges_and_query_parameters` |
| S1-065 | §5 | `offset` \| integer 0 or more \| 422 `validation_failed` | limit | `p03_payments.shared_ranges_and_query_parameters` |
| S1-066 | §5 | ★ Requests must not produce 5xx responses, including under concurrent load. | concurrency | `run_all.global_conventions`, `p08_concurrency.overdraft_race_never_goes_negative`, `p08_concurrency.spending_the_whole_balance_many_times_succeeds_once`, `p08_concurrency.opposing_transfers_do_not_deadlock_or_lose_money`, `p08_concurrency.mixed_load_at_50_in_flight_keeps_invariants`, `p08_concurrency.concurrent_signups_with_the_same_email_or_handle`, `p08_concurrency.fifty_requests_in_flight_all_answered_in_time`, `p10_settlements.competing_settlements_and_payments_stay_atomic` |
| S1-070 | §6 | POST /auth/signup { "email": …, "password": …, "display_name": … } ->  201  { "user_id": "u_1", "display_name": "Ada", "token": "..." } | behaviour | `p02_auth.signup_then_login_and_new_user_starts_empty` |
| S1-071 | §6 | POST /auth/login { "email": …, "password": … } ->  200  { "user_id": "u_1", "display_name": "Ada", "token": "..." } | behaviour | `p02_auth.signup_then_login_and_new_user_starts_empty` |
| S1-072 | §6 | Email already registered \| 409 `email_taken` | error | `p02_auth.handle_and_email_conflicts`, `p08_concurrency.concurrent_signups_with_the_same_email_or_handle` |
| S1-073 | §6 | ★ Password shorter than 8 characters \| 422 `validation_failed` (boundary: 7 fails, 8 passes; length counts characters) | error | `p02_auth.signup_login_validation_and_failures` |
| S1-074 | §6 | ★ `email` not of the form `local@domain` \| 422 `validation_failed` | error | `p02_auth.signup_login_validation_and_failures` |
| S1-075 | §6 | Wrong password or unknown email on login \| 401 `unauthenticated` | error | `p02_auth.signup_login_validation_and_failures` |
| S1-076 | §6 | ★ The handle derived from the email (§4) is already taken \| 409 `handle_taken`, and no account is created | error | `p02_auth.handle_and_email_conflicts` |
| S1-077 | §6 | Every other endpoint requires a bearer token, except `/health`, `/_test/reset` and the two above. Wallet API endpoints require authentication. | behaviour | `p02_auth.endpoints_require_a_bearer_token` |
| S1-078 | §6 | ★ Tokens do not expire. An account may have multiple valid tokens and concurrent sessions. | behaviour | `p02_auth.tokens_do_not_expire_and_sessions_are_concurrent` |
| S1-079 | §6 | ★ Plaintext password storage is not permitted. | behaviour | `p02_auth.plaintext_passwords_are_not_stored`, `p09_export.full_round_trip_preserves_every_kind_of_state` |
| S1-080 | §6 | ★ Authentication supports signup and login. (Reading: after signup the returned token works at once and the password logs in; email uniqueness is checked before handle uniqueness when both collide.) | behaviour | `p02_auth.signup_then_login_and_new_user_starts_empty` |
| S1-090 | §7 | Five write paths require an idempotency key (§8 and §11): **`POST /payments`**, **`POST /requests`**, **`POST /requests/{id}/pay`**, **`POST /splits`** and **`POST /settlements`**. Everything below applies to each of them independently. | idempotency | `p07_idempotency.key_is_required_on_all_five_paths`, `p07_idempotency.first_use_201_then_replays_are_200_with_identical_body` |
| S1-091 | §7 | ★ The key is scoped to **the authenticated user**. Two different users may use the same key string with no interaction between them. | idempotency | `p07_idempotency.key_is_scoped_to_the_user_and_to_the_path` |
| S1-092 | §7 | ★ A replay means the same user sending the **same method, the same path and the same body**. The same key with the same body on a different path is a different request, not a replay, and must succeed normally. | idempotency | `p07_idempotency.key_is_scoped_to_the_user_and_to_the_path` |
| S1-093 | §7 | Header absent or empty \| 400 `missing_idempotency_key` | idempotency | `p07_idempotency.key_is_required_on_all_five_paths` |
| S1-094 | §7 | First use of the key \| The normal response, **201** | idempotency | `p07_idempotency.first_use_201_then_replays_are_200_with_identical_body` |
| S1-095 | §7 | ★ Replay: same key, same body \| **200**, body identical to the original response as a JSON value | idempotency | `p07_idempotency.first_use_201_then_replays_are_200_with_identical_body` |
| S1-096 | §7 | ★ Same key, different body \| 409 `idempotency_key_reuse` | idempotency | `p07_idempotency.same_key_different_body_is_409_before_any_validation`, `p07_idempotency.concurrent_same_key_different_bodies_one_wins` |
| S1-097 | §7 | ★ Key reused after the original request failed with 4xx \| Treated as a first use | idempotency | `p07_idempotency.key_reused_after_a_4xx_failure_is_a_first_use` |
| S1-098 | §7 | ★ "Same body" means the same JSON value after parsing — key order and whitespace do not matter. | idempotency | `p07_idempotency.first_use_201_then_replays_are_200_with_identical_body` |
| S1-099 | §7 | ★ For concurrent identical requests with an unused key, exactly one returns 201. The others return 200 with the same body. The operation takes effect only once. | concurrency | `p07_idempotency.concurrent_identical_requests_take_effect_once`, `p07_idempotency.concurrent_same_key_different_bodies_one_wins`, `p10_settlements.settlement_replay_returns_the_complete_original_response` |
| S1-100 | §7 | ★ A successful replay returns the original response, even after the resource changes or is cancelled. It makes no further state changes. | idempotency | `p07_idempotency.first_use_201_then_replays_are_200_with_identical_body`, `p07_idempotency.concurrent_identical_requests_take_effect_once`, `p07_idempotency.replay_returns_original_even_after_the_world_changed` |
| S1-101 | §7 | ★ an already claimed key is resolved before endpoint field validation or current-resource checks. Thus changing a successful request to an invalid body with the same key still returns `409 idempotency_key_reuse`. | idempotency | `p07_idempotency.same_key_different_body_is_409_before_any_validation`, `p07_idempotency.claimed_key_edge_cases_unparseable_body_and_missing_token` |
| S1-102 | §7 | ★ After the body has parsed as a JSON object and the caller is authenticated, an already claimed key is resolved… Reading: before that point (unparseable body → 400 `malformed_request`, bad token → 401) those errors win over the claimed key. | idempotency | `p07_idempotency.claimed_key_edge_cases_unparseable_body_and_missing_token` |
| S1-103 | §7 | ★ (derived) concurrent requests with the same key but different bodies: exactly one first use wins; every other request is a replay (same body → 200) or a conflict (different body → 409); the operation takes effect once. | concurrency | `p07_idempotency.concurrent_same_key_different_bodies_one_wins` |
| S1-110 | §8 | GET /me → { "user_id": "u_ada", "display_name": "Ada", "handle": "ada", "balance": 10000, "currency": "EUR", "minor_units": 2 } | behaviour | `p01_runtime.currency_and_minor_units_are_reported_per_fixture` |
| S1-111 | §8 | POST /payments { "to_handle", "amount", "note", "visibility" } → 201 { payment_id, from_user_id, from_handle, to_user_id, to_handle, amount, currency, note, visibility, request_id: null, created_at }. `note` is optional and defaults to `""`. `visibility` is optional and defaults to `"public"`. | behaviour | `p03_payments.payment_happy_path_moves_money_atomically` |
| S1-112 | §8 | ★ The caller's balance is below `amount` \| 409 `insufficient_funds` (boundary: paying exactly the balance succeeds) | error | `p03_payments.insufficient_funds_boundary_and_no_trace`, `p08_concurrency.overdraft_race_never_goes_negative` |
| S1-113 | §8 | `amount` below 1, above 1000000000, or not an integer \| 422 `validation_failed` | error | `p03_payments.payment_validation_errors` |
| S1-114 | §8 | `to_handle` is the caller's own handle \| 422 `self_payment` | error | `p03_payments.payment_validation_errors` |
| S1-115 | §8 | ★ `note` longer than 200 characters \| 422 `validation_failed` (200 passes; length is in characters, not bytes or UTF-16 units) | error | `p03_payments.payment_validation_errors` |
| S1-116 | §8 | `visibility` is neither `public` nor `private` \| 422 `validation_failed` | error | `p03_payments.payment_validation_errors` |
| S1-117 | §8 | No user has that handle \| 404 `not_found` | error | `p03_payments.payment_validation_errors` |
| S1-118 | §8 | ★ The debit and the credit are one atomic step. A payment is never visible in one wallet and not the other, and a failed payment leaves no trace in either. | concurrency | `p03_payments.payment_happy_path_moves_money_atomically`, `p03_payments.insufficient_funds_boundary_and_no_trace` |
| S1-119 | §8 | ★ `note` is stored and returned verbatim: no trimming, no escaping, no normalisation. Unicode and emoji survive a round trip byte for byte. | behaviour | `p03_payments.note_is_stored_verbatim` |
| S1-120 | §8 | POST /requests { "payer_handle", "amount", "note" } → 201 { request_id, requester_id, requester_handle, payer_id, payer_handle, amount, currency, note, status: "pending", payment_id: null, created_at }. The caller is the requester. | behaviour | `p04_requests.request_creation_shape_and_no_balance_check` |
| S1-121 | §8 | `amount` below 1, above 1000000000, or not an integer \| 422 `validation_failed` (requests) | error | `p04_requests.request_validation_errors` |
| S1-122 | §8 | `payer_handle` is the caller's own handle \| 422 `self_request` | error | `p04_requests.request_validation_errors` |
| S1-123 | §8 | `note` longer than 200 characters \| 422 `validation_failed` (requests) | error | `p04_requests.request_validation_errors` |
| S1-124 | §8 | No user has that handle \| 404 `not_found` (requests) | error | `p04_requests.request_validation_errors` |
| S1-125 | §8 | ★ **The payer's balance is not checked here.** A request for more than the payer holds is created normally and sits `pending`. | behaviour | `p04_requests.request_creation_shape_and_no_balance_check` |
| S1-126 | §8 | ★ The body carries `visibility` only, optional, default `"public"`. It is the payer's choice, not the requester's. | behaviour | `p04_requests.paying_a_request_creates_a_payment_with_payer_chosen_visibility` |
| S1-127 | §8 | ★ Returns `201` with the created **payment**, exactly as `POST /payments` returns one, with `request_id` set to this request. The request becomes `paid` and carries the new `payment_id`. | behaviour | `p04_requests.paying_a_request_creates_a_payment_with_payer_chosen_visibility` |
| S1-128 | §8 | The request is not `pending` \| 409 `request_not_pending` | error | `p04_requests.pay_error_cases_and_late_funds` |
| S1-129 | §8 | The payer's balance is below `amount` \| 409 `insufficient_funds` (pay) | error | `p04_requests.pay_error_cases_and_late_funds`, `p08_concurrency.a_request_moves_money_at_most_once` |
| S1-130 | §8 | The caller is not the request's payer \| 403 `forbidden` | error | `p04_requests.pay_error_cases_and_late_funds` |
| S1-131 | §8 | Unknown request \| 404 `not_found` | error | `p04_requests.pay_error_cases_and_late_funds` |
| S1-132 | §8 | ★ **A replay must send the identical body** — `{}` and `{"visibility": "public"}` are different JSON values, so reusing a key across the two is `409 idempotency_key_reuse` | idempotency | `p07_idempotency.replay_returns_original_even_after_the_world_changed` |
| S1-133 | §8 | ★ Replaying a successful payment returns 200 with its original payment body, including when the request is already `paid`. It moves no additional money and must not return `409 request_not_pending`. | idempotency | `p07_idempotency.replay_returns_original_even_after_the_world_changed` |
| S1-134 | §8 | ★ Declining … Only the payer. No idempotency key. Returns `200` with the request, `status: "declined"`. Declining an already-declined request is `200` with the current state — declining twice is not an error. | behaviour | `p04_requests.decline_semantics` |
| S1-135 | §8 | A `paid` or `cancelled` request is `409 request_not_pending`. Not the payer is `403 forbidden`. (decline) | error | `p04_requests.decline_semantics` |
| S1-136 | §8 | ★ Cancelling … Only the requester. No idempotency key. Returns `200` with the request, `status: "cancelled"`. Cancelling an already-cancelled request is `200`. | behaviour | `p04_requests.cancel_semantics` |
| S1-137 | §8 | A `paid` or `declined` request is `409 request_not_pending`. Not the requester is `403 forbidden`. (cancel) | error | `p04_requests.cancel_semantics` |
| S1-138 | §8 | ★ (implied) decline and cancel work without an `Idempotency-Key`, and an unknown request id is `404 not_found` for them as for pay. | behaviour | `p04_requests.decline_semantics`, `p04_requests.cancel_semantics` |
| S1-139 | §8 | Requests where the caller is the requester or the payer, and no others. Newest first by `created_at`. | behaviour | `p04_requests.request_listing_filters_pagination_and_visibility` |
| S1-140 | §8 | `direction` is `incoming` (the caller is the payer), `outgoing` (the caller is the requester) or absent for both. | behaviour | `p04_requests.request_listing_filters_pagination_and_visibility` |
| S1-141 | §8 | `status` is one of the four statuses, or absent for all. | behaviour | `p04_requests.request_listing_filters_pagination_and_visibility` |
| S1-142 | §8 | ★ `limit` defaults to 50, range 1 to 200. `offset` defaults to 0 and must be 0 or more. Outside either range is 422 `validation_failed`. An unknown `direction` or `status` value is also 422. | error | `p04_requests.request_listing_filters_pagination_and_visibility`, `p06_feed.feed_order_limit_offset_has_more` |
| S1-143 | §8 | `has_more` is true when items exist beyond the last one returned. | behaviour | `p04_requests.request_listing_filters_pagination_and_visibility`, `p06_feed.feed_order_limit_offset_has_more` |
| S1-144 | §8 | POST /splits { "amount", "participant_handles", "note" } → 201 { split_id, amount, currency, note, shares, requests, created_at } | behaviour | `p05_splits_money.split_shape_requests_and_no_money_moves` |
| S1-145 | §8 | ★ **A request is created for every participant except the caller**, each for that participant's share, with the caller as requester. `shares` covers every participant including the caller, in the order given, and always sums to `amount`. `requests` covers every participant except the caller, in the same order. | behaviour | `p05_splits_money.split_shape_requests_and_no_money_moves`, `p05_splits_money.equal_split_rounding_table_and_ordering` |
| S1-146 | §8 | `amount` below 1, above 1000000000, or not an integer \| 422; `participant_handles` empty, or containing a duplicate handle \| 422; `note` longer than 200 characters \| 422; Any handle is unknown \| 404 `not_found` (a failed split creates nothing) | error | `p05_splits_money.split_validation_errors_leave_no_trace` |
| S1-147 | §8 | ★ A split whose only participant is the caller is **valid**: it computes one share, creates zero requests, and returns `"requests": []`. | behaviour | `p05_splits_money.split_with_only_the_caller_is_valid` |
| S1-148 | §8 | ★ Nothing about a split checks anyone's balance. (Reading: a split moves no money; it only asks for shares of an amount the caller already paid.) | behaviour | `p05_splits_money.split_shape_requests_and_no_money_moves`, `p05_splits_money.split_with_only_the_caller_is_valid` |
| S1-149 | §8 | Payments visible to the caller by the feed contract in §4, newest first by `created_at`. { "payments": [ { ...payment... } ], "has_more": false } | behaviour | `p06_feed.feed_contract_public_or_party`, `p06_feed.feed_order_limit_offset_has_more` |
| S1-150 | §8 | `limit` and `offset` behave exactly as in `GET /requests`. | behaviour | `p06_feed.feed_order_limit_offset_has_more` |
| S1-151 | §8 | The relative order of two payments created within the same second is unspecified. Stable pagination during concurrent writes is not required for this endpoint. (not asserted: probes space writes ≥1.1 s apart when order matters) | behaviour | manual — unspecified by the spec; deliberately not asserted |
| S1-152 | §8 | ★ (derived readings, §4/§8 tables) a non-party calling pay/decline/cancel gets 403 or 404; `request_not_pending` is decided before `insufficient_funds`; `forbidden` is decided before `request_not_pending`. | error | `p04_requests.pay_error_cases_and_late_funds` |
| S1-160 | §9 | Shares must be whole minor units, sum exactly to `amount` and differ by at most one minor unit. | behaviour | `p05_splits_money.equal_split_rounding_table_and_ordering`, `p05_splits_money.many_splits_paid_in_full_conserve_the_total` |
| S1-161 | §9 | ★ When the amount does not divide evenly, the larger shares go to the first participants in `participant_handles` order. | behaviour | `p05_splits_money.equal_split_rounding_table_and_ordering` |
| S1-162 | §9 | ★ Splitting the same amount among the same people in a different `participant_handles` order gives the extra unit to a different person. | behaviour | `p05_splits_money.equal_split_rounding_table_and_ordering` |
| S1-163 | §9 | ★ A share of `0` is legal and still produces a request for that participant. | behaviour | `p05_splits_money.equal_split_rounding_table_and_ordering` |
| S1-164 | §9 | ★ Each split's shares are independent of previous splits. After any number of splits have been paid in full, wallet balances must still sum exactly to the seeded total. | behaviour | `p05_splits_money.many_splits_paid_in_full_conserve_the_total` |
| S1-165 | §9 | \| 1000 \| 3 \| 334, 333, 333 \| | behaviour | `p05_splits_money.equal_split_rounding_table_and_ordering` |
| S1-166 | §9 | \| 1 \| 3 \| 1, 0, 0 \| | behaviour | `p05_splits_money.equal_split_rounding_table_and_ordering` |
| S1-167 | §9 | \| 10 \| 3 \| 4, 3, 3 \| | behaviour | `p05_splits_money.equal_split_rounding_table_and_ordering` |
| S1-168 | §9 | \| 999 \| 3 \| 333, 333, 333 \| | behaviour | `p05_splits_money.equal_split_rounding_table_and_ordering` |
| S1-169 | §9 | \| 5 \| 5 \| 1, 1, 1, 1, 1 \| | behaviour | `p05_splits_money.equal_split_rounding_table_and_ordering` |
| S1-170 | §10 | The service must support `GET /_test/export` and `POST /_test/import`. Like reset, these are unauthenticated test endpoints. | data-migration | `p09_export.export_envelope_is_unauthenticated_and_read_only` |
| S1-171 | §10 | Return 200 from export with a JSON object containing `track: "pocketful"`, `format_version: 1` and `state` (an implementation-defined JSON object). | data-migration | `p09_export.export_envelope_is_unauthenticated_and_read_only` |
| S1-172 | §10 | The state format is opaque to the caller and must be accepted unchanged by import. Import takes that entire object and atomically replaces the service's state, returning 204. It must accept an unchanged export produced by this service. | data-migration | `p09_export.full_round_trip_preserves_every_kind_of_state`, `p09_export.export_imports_into_a_different_instance` |
| S1-173 | §10 | ★ No dependency on the source process, files, volume, port or network address is allowed. | data-migration | `p09_export.export_imports_into_a_different_instance`; plus manual — needs a second independent container: run_all.py `--peer URL` exercises it; without --peer that probe reports SKIP and the reviewer must run it once |
| S1-174 | §10 | ★ Import is replacement, not merge; repeating it restores the exported state without duplicating anything. | data-migration | `p09_export.full_round_trip_preserves_every_kind_of_state`, `p09_export.import_is_replacement_repeatable_and_reset_clears_it` |
| S1-175 | §10 | ★ Invalid JSON follows §5; missing fields, wrong track/version or an invalid state give 422 `validation_failed` without changing the destination. | error | `p09_export.invalid_imports_are_rejected_and_change_nothing` |
| S1-176 | §10 | ★ Test control calls have a 10-second timeout. | time | `p09_export.reset_export_and_import_of_a_larger_state_fit_in_10_seconds` |
| S1-177 | §10 | ★ Export is an atomic, read-only snapshot; subsequent source writes do not change it. | data-migration | `p09_export.export_envelope_is_unauthenticated_and_read_only` |
| S1-178 | §10 | ★ Preserve accounts and hashed-password login — state kind: user accounts (id, email, display_name, handle) and password hashes; no plaintext in the export. | data-migration | `p02_auth.plaintext_passwords_are_not_stored`, `p09_export.full_round_trip_preserves_every_kind_of_state` |
| S1-179 | §10 | ★ existing bearer tokens — state kind: issued tokens (seeded-login, extra sessions, signup tokens) | data-migration | `p09_export.full_round_trip_preserves_every_kind_of_state` |
| S1-180 | §10 | currency — state kind: currency code and `minor_units` | data-migration | `p09_export.full_round_trip_preserves_every_kind_of_state` |
| S1-181 | §10 | balances — state kind: wallet balances, restored exactly (not replayed) | data-migration | `p09_export.full_round_trip_preserves_every_kind_of_state` |
| S1-182 | §10 | payments — state kind: payments with ids, notes (verbatim), visibility, timestamps | data-migration | `p09_export.full_round_trip_preserves_every_kind_of_state` |
| S1-183 | §10 | requests — state kind: requests with status and `payment_id` | data-migration | `p09_export.full_round_trip_preserves_every_kind_of_state` |
| S1-184 | §10 | ★ permissions — state kind: settlement operators (`settlement_operator_ids`) | data-migration | `p09_export.full_round_trip_preserves_every_kind_of_state` |
| S1-185 | §10 | ★ all completed idempotent request bodies and original responses — state kind: claimed idempotency keys (user, path, body, response) for all five write paths | data-migration | `p09_export.full_round_trip_preserves_every_kind_of_state` |
| S1-186 | §10 | ★ Identities, timestamps and monetary records must not be regenerated or replayed against an already-net balance. | data-migration | `p09_export.full_round_trip_preserves_every_kind_of_state`, `p09_export.import_is_replacement_repeatable_and_reset_clears_it` |
| S1-187 | §10 | ★ Failed request keys remain reusable. | data-migration | `p09_export.full_round_trip_preserves_every_kind_of_state` |
| S1-188 | §10 | ★ Existing receipts, tokens and retries must remain valid after import; replacing the state with a fresh fixture does not satisfy this requirement. Import removes all previous destination data and credentials. | data-migration | `p09_export.full_round_trip_preserves_every_kind_of_state`, `p09_export.import_is_replacement_repeatable_and_reset_clears_it` |
| S1-189 | §10 | ★ Reset clears all state, including imported state. | data-migration | `p09_export.import_is_replacement_repeatable_and_reset_clears_it` |
| S1-190 | §11 | ★ A reset/import must preserve settlement operator permissions, original payments, requests, settlement membership and retry responses. — state kind: settlements (settlement ids and which payments belong to each) | data-migration | `p09_export.full_round_trip_preserves_every_kind_of_state` |
| S1-191 | §10 | ★ (derived) state kind: id/sequence counters — after import, newly created payments/requests/settlements must not reuse an existing id ("Identities … must not be regenerated"). | data-migration | `p09_export.full_round_trip_preserves_every_kind_of_state` |
| S1-192 | §10 | ★ Export … `state`: kinds of state the service holds (inventory, one probe-covered row each above): accounts 178, password hashes 178/79, tokens 179, currency 180, balances 181, payments 182, requests 183, operators 184, idempotency records 185, failed keys 187, settlements 190, counters 191. | data-migration | `p09_export.full_round_trip_preserves_every_kind_of_state` |
| S1-193 | §10 | Exports may contain credentials and session tokens; handle them as private test artifacts. | data-migration | manual — handling guidance only |
| S1-200 | §11 | The reset fixture may include `settlement_operator_ids`, an array of user ids, default []. | behaviour | `p10_settlements.only_operators_may_settle_and_operators_gain_nothing_else` |
| S1-201 | §11 | An operator may execute a settlement across any wallets. | behaviour | `p10_settlements.only_operators_may_settle_and_operators_gain_nothing_else` |
| S1-202 | §11 | ★ This permission does not grant access to another user's requests or private activity items. | behaviour | `p10_settlements.only_operators_may_settle_and_operators_gain_nothing_else` |
| S1-203 | §11 | `POST /settlements` requires an operator and an idempotency key. No token gives 401; authenticated non-operator gives 403 `forbidden`. | error | `p10_settlements.only_operators_may_settle_and_operators_gain_nothing_else` |
| S1-204 | §11 | transfers contains 1..32 objects. | limit | `p10_settlements.settlement_validation_errors_claim_no_key_and_leave_no_trace` |
| S1-205 | §11 | Each uses ordinary payment amount, note and visibility rules (defaults: empty note, public). … Unknown fields are ignored. | behaviour | `p10_settlements.settlement_response_members_and_feed`, `p10_settlements.settlement_validation_errors_claim_no_key_and_leave_no_trace` |
| S1-206 | §11 | ★ Unknown handle is 404; self-transfer is 422 `self_payment`; malformed batch shape is 422 `validation_failed`. | error | `p10_settlements.settlement_validation_errors_claim_no_key_and_leave_no_trace` |
| S1-207 | §11 | ★ Entry errors take precedence in input order, before insufficient funds. | error | `p10_settlements.entry_errors_come_first_in_input_order_before_insufficient_funds` |
| S1-208 | §11 | ★ A settlement is affordable when every wallet's balance after all incoming and outgoing transfers is nonnegative. | behaviour | `p10_settlements.affordability_is_net_and_all_or_nothing` |
| S1-209 | §11 | Insufficient collective funds gives 409 `insufficient_funds`. | error | `p10_settlements.entry_errors_come_first_in_input_order_before_insufficient_funds`, `p10_settlements.affordability_is_net_and_all_or_nothing` |
| S1-210 | §11 | ★ Either all movements commit together or none do; failed validation claims no idempotency key and creates no payment or revision. | concurrency | `p10_settlements.settlement_validation_errors_claim_no_key_and_leave_no_trace`, `p10_settlements.affordability_is_net_and_all_or_nothing` |
| S1-211 | §11 | Return 201 with `settlement_id`, `committed_at` and `payments` in input order. | behaviour | `p10_settlements.settlement_response_members_and_feed` |
| S1-212 | §11 | ★ Every member is an ordinary payment with `settlement_id` linking the batch; nonmembers expose null for that field. | behaviour | `p10_settlements.settlement_response_members_and_feed` |
| S1-213 | §11 | ★ Members have null request_id and the same server-assigned created_at, equal to committed_at. | behaviour | `p10_settlements.settlement_response_members_and_feed` |
| S1-214 | §11 | ★ Constituents follow ordinary activity-feed visibility. The settlement response contains every member's receipt. | behaviour | `p10_settlements.settlement_response_members_and_feed` |
| S1-215 | §11 | ★ Replays return 200 with the original complete response. | idempotency | `p10_settlements.settlement_replay_returns_the_complete_original_response` |
| S1-216 | §11 | ★ This is the fifth idempotent write path in stage 1. (all §7 rows apply: missing key 400, user scope, replay 200, conflict 409, concurrency) | idempotency | `p07_idempotency.key_is_required_on_all_five_paths`, `p07_idempotency.first_use_201_then_replays_are_200_with_identical_body`, `p07_idempotency.same_key_different_body_is_409_before_any_validation`, `p07_idempotency.key_is_scoped_to_the_user_and_to_the_path`, `p07_idempotency.key_reused_after_a_4xx_failure_is_a_first_use`, `p07_idempotency.concurrent_identical_requests_take_effect_once`, `p07_idempotency.concurrent_same_key_different_bodies_one_wins`, `p07_idempotency.replay_returns_original_even_after_the_world_changed`, `p10_settlements.only_operators_may_settle_and_operators_gain_nothing_else`, `p10_settlements.settlement_replay_returns_the_complete_original_response` |
| S1-218 | §1/§11 | ★ (derived from §1 rule 2 and §11 'affordable') a settlement whose transfers would drive a wallet negative if applied one by one, but is net-affordable, must succeed and must never expose a negative balance to a concurrent reader. | concurrency | `p10_settlements.affordability_is_net_and_all_or_nothing`, `p10_settlements.settlement_never_shows_a_transient_negative_balance` |
| S1-219 | §1/§11 | ★ (derived) competing settlements and payments against the same wallet: only as many succeed as fit; never negative; money conserved; each settlement all-or-nothing. | concurrency | `p10_settlements.competing_settlements_and_payments_stay_atomic` |
| S1-220 | — | This stage defines the initial service and its API. (Earlier stages: none. Nothing earlier holds yet; later stages must re-run this ledger's probes.) | behaviour | manual — stage 1 has no predecessor |
| S1-221 | — | UI-state: stage 1 specifies no screens ("Only the HTTP API is required."), so there are no user-visible screen states to enumerate. | UI-state | manual — no screens in stage 1 |
| S1-222 | §8 | ★ (derived) `GET /activity` without parameters returns at most 50 items (default `limit` 50) and pages walk every item exactly once. | limit | `p06_feed.feed_order_limit_offset_has_more` |
| S1-223 | §header | Source code, API documentation and schemas from existing products in this domain must not be used. | behaviour | manual — provenance rule for the implementer; not observable over HTTP |
| S1-224 | — | Review notes from earlier stages: none forwarded. | review-note | manual — none exist for stage 1 |

## Summary

Row counts by kind: behaviour 84, error 44, idempotency 16, data-migration 22, limit 11, concurrency 10, time 3,
UI-state 1, review-note 1 (192 rows). ★ rows: 94. Rows with a `manual` component: 14 (container/Docker/resource
properties, provenance, and the cross-instance import which needs `--peer`).

State inventory for "state that leaves the service" (§10): accounts (178), password hashes (178, 79), bearer tokens
(179), currency + minor units (180), balances (181), payments (182), requests (183), settlement operators (184),
completed idempotent responses of all five paths (185), failed keys not recorded (187), settlements and membership
(190), id/sequence counters (191). All are exercised by `p09_export.full_round_trip_preserves_every_kind_of_state`
and, with `--peer`, `p09_export.export_imports_into_a_different_instance`.

## Running the probes

    python3 factory/probes/stage-1/run_all.py http://127.0.0.1:8080
    python3 factory/probes/stage-1/run_all.py http://127.0.0.1:8080 --peer http://127.0.0.1:8081   # adds cross-instance import
    python3 factory/probes/stage-1/run_all.py http://127.0.0.1:8080 -k idempotency -v              # subset, tracebacks
    python3 factory/probes/stage-1/check_ledger.py                                                  # ledger <-> probe cross-check

Python 3.8+ standard library only. The runner waits up to 60 s for `/health`, resets the service itself, exits 0
only if every probe passes. Probes wipe all service state; run them against a disposable container.
