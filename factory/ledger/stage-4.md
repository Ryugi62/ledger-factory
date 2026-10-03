# Pocketful — Stage 4 requirement ledger (refunds and batch corrections)

Source: the stage-4 specification text handed over by @coordinator (single message), read only from that text; no
shipped checks were opened. Stage 4 *extends* stages 1–3: `factory/ledger/stage-1.md`, `stage-2.md` and `stage-3.md`
remain in force. IDs are `S4-nnn`. `★` marks statements a quick reading would miss (error precedence of batches,
combined-effect affordability, offset spellings of identical instants, `incomplete_settlement`, distinct payment ids,
the refund limit against the *current corrected* amount, correction below the refunded amount, refunds from
*available* funds, refund of a refund / capture / settlement member, replay semantics, races, the shared
`recorded_at`, frozen snapshots after a batch). `probe` names the black-box probe(s) in `factory/probes/stage-4/`
(`module.function`); `manual` rows say why. Rows tagged "(derived)" / "Reading:" make an implied consequence explicit.

## Everything earlier still holds

Row S4-001 stands for all of the stage-1 ledger (S1-001…S1-224), the stage-2 ledger (S2-001…S2-236) and the stage-3
ledger (S3-001…S3-154). The stage-4 runner re-runs the stage-1 suite, the stage-2 non-UI suite, the stage-3 suite
(`--with-ui` adds the stage-2 browser probes and the stage-3 review-note browser probes) unchanged, **except** five
earlier probes that stage 4 deliberately supersedes (`SUPERSEDED` in `run_all.py`):

| superseded earlier probe | why |
|---|---|
| `p01_runtime.currency_and_minor_units_are_reported_per_fixture`, `s2_01_fixture_me.me_has_total_available_held_and_agrees_without_holds` | pin the exact shape of `GET /me` (stage 3 added `as_of` / `known_at` echoes); the money fields stay checked by S3-021 / S3-120 |
| `s3_03_corrections.settlement_members_and_captures_are_immutable_linked_payments` | asserts 422 `linked_payment_immutable` for a single-payment correction of a settlement member (S3-111); stage 4 makes members batch-only (single endpoint → 422 `incomplete_settlement`). The capture part (S3-114) is re-covered by S4-020 |
| `s3_07_export.a_stage1_export_is_accepted_and_accounted_for` | also asserts `linked_payment_immutable` for an imported settlement member; replaced by S4-053/S4-064 (`a_stage1_export_is_accepted_with_membership_and_refundable_payments`) |
| `s2_04_export.a_stage1_export_is_accepted_and_clients_survive_the_upgrade` | compares imported feed items with the stage-1 receipts modulo `authorization_id` only; every payment now also carries `refund_of: null`. Replaced by the same stage-4 probe (S4-053, S4-069) |

### Earlier rows that stage 4 changes or extends

| earlier row | what changes in stage 4 | stage-4 rows |
|---|---|---|
| S3-111 "single-payment corrections reject settlement members with 422 `linked_payment_immutable`" | **superseded**: settlement members are corrected only through a batch that includes every member (identical effective instants); the single endpoint answers `incomplete_settlement` | S4-033…S4-036 |
| S3-114 captures immutable | unchanged, now also refund payments are immutable; captures and refunds stay immutable in batches | S4-020, S4-033 |
| S3-050…S3-066 single corrections | additional rules: cannot reduce a payment below its already-refunded amount (`refund_exceeds_payment`); debits checked against *available* funds | S4-021, S4-022 |
| S3-063 / S3-064 / S3-129 `insufficient_funds` before `historical_overdraft` | the same precedence now also governs batches, judged on the combined effect of all proposed revisions | S4-038, S4-040 |
| S3-056 / S3-070 revision objects | gain `correction_batch_id` (null for single corrections, the batch id for batch revisions) | S4-044 |
| S3-066 failures preserve history/balances/idempotency | extended to rejected batches | S4-041 |
| S3-109 same expected revision cannot both succeed | extended to concurrent batches sharing *any* expected payment revision, atomically | S4-052, S4-057 |
| S3-110 settlement members' original revision | members can now receive new revisions (batch) with a `recorded_at` strictly later than `committed_at`; originals and settlement retries stay unchanged | S4-043, S4-046, S4-047 |
| S3-100…S3-108, S3-147 snapshots ("not part of the exported state", reading) | **superseded**: saved statements must remain available after export/import; reset still discards them | S4-003, S4-048, S4-065 |
| S3-112 / S3-113 import of stage-1/2 exports | now exports of stages 1–3, retaining settlement membership, corrections and snapshots | S4-053, S4-060…S4-069 |
| S2-153 / S2-155 captures | refundable by their receiver (refund of a capture), never corrected | S4-011, S4-020 |
| S1-212 / S1-213 settlement members | refundable under the ordinary refund rules; the refund is a separate payment with `settlement_id: null`, membership never changes | S4-051 |
| S1-111 payment shape | every payment carries `refund_of` (null except for refunds) | S4-015, S4-019 |
| S1-112 / S1-129 / S2-100 `insufficient_funds` | refunds move money from the receiver's *available* funds | S4-017 |
| S1-090 / S2-103 / S3-061 idempotent write paths | ten now: + refunds and correction batches | S4-004, S4-050 |
| S1-005 / S2-094 / S3-005 invariants | re-checked through refunds, corrections and batches | S4-090 |

## Readings chosen where the specification is silent or ambiguous

1. **Single correction of a settlement member**: 422 `incomplete_settlement` for a member of a multi-member
   settlement (a non-sender still gets 403 first). A one-member settlement is not asserted on the single endpoint.
2. **Refund check order**: 404 unknown payment; 403 non-receiver; 422 `validation_failed` for the amount; then
   `invalid_refund_target`, `refund_exceeds_payment`, `insufficient_funds`. Only separable cases are asserted: the receiver
   of a refund refunding it gets `invalid_refund_target`; the sender, a stranger get 403.
3. **Batch check order**: array-level checks first (1..32 items, objects, distinct payment ids → 422); then the items in
   input order (an item's 404 / 409 `stale_revision` / 422 `linked_payment_immutable` / `refund_exceeds_payment` / field
   validation beats every later item's error and every later stage); then settlement completeness
   (`incomplete_settlement`, and mismatched effective instants as 422 `validation_failed`); then *resulting current
   available funds* (every involved wallet must stay ≥ 0 after all proposed revisions); then history (total and available
   ≥ 0 at every past effective/event boundary). Order of checks *within one item* is not asserted.
4. **Offset spellings**: instants are compared as instants (`+00:00`, `+02:00`, `Z`, fractions); a 1 s or 1 ms difference
   between members of one settlement is a mismatch.
5. **Refund payment**: `created_at` is the refund time; `note`/`visibility` are copied from the target payment;
   `settlement_id` is null even for a refund of a settlement member; it is an ordinary payment in feed (per its visibility),
   statements and historical views. The refund limit uses the target's *selected latest revision* amount.
6. **Snapshots survive export/import** of a stage-4 service (supersedes the stage-3 reading); for an imported stage-3
   export a token is retained only if the source exported it (404 tolerated, wrong entries are not).
7. **`correction_batch_id`** appears on every revision object returned by the batch and by the revisions endpoint (null for
   revisions that were not made in a batch).
8. **`recorded_at` of a batch** is strictly later than the previous `recorded_at` of every member, including a settlement's
   `committed_at` for members never corrected before.
9. **Operator**: need not be a party to the corrected payments; any non-operator (sender, receiver, stranger) gets 403,
   no token 401, missing key 400 (as for settlements).
10. **Wrong JSON types** in a batch or refund body: 400 `malformed_request` or 422; amounts that are strings, booleans,
    fractions or out of range are 422 (stage-1 §5).
11. **Timestamp resolution / sleeps**: as in stage 3 (events that must be ordered are ≥1.1 s apart; instants probed at ±0.4 s).

## Ledger

| ID | section | requirement (verbatim excerpt) | kind | probe |
|---|---|---|---|---|
| S4-001 | §intro | ★ All requirements from stages 1–3 continue to apply. (everything earlier still holds: every row of factory/ledger/stage-1.md, stage-2.md and stage-3.md, minus the rows listed under "Earlier rows that stage 4 changes") | behaviour | manual — re-run of the earlier stages' probe suites by this runner (see the table of changed earlier rows) |
| S4-002 | §intro | Recipients can refund payments. Settlement operators can correct several payments in one request, including payments that belong to a settlement. | behaviour | `s4_02_batches.batch_authorization_shape_shared_recorded_at_originals_and_replay` |
| S4-003 | §intro | ★ Existing receipts and saved statements must remain available in their original form. | behaviour | `s4_01_refunds.refund_basics_shape_replay_limits_and_errors` |
| S4-004 | §intro | ★ There are ten idempotent write paths: stage 1's five, authorizations and captures from stage 2, corrections from stage 3, and refunds and correction batches in this stage. | idempotency | `s4_01_refunds.refund_idempotency_scope_and_failed_keys` |
| S4-010 | §refunds | ★ `POST /payments/{payment_id}/refunds`, body `{"amount": 200}`, requires an idempotency key. Only the original receiver may refund, else 403 `forbidden`; unknown payment is 404. | error | `s4_01_refunds.refund_basics_shape_replay_limits_and_errors`, `s4_01_refunds.refund_idempotency_scope_and_failed_keys` |
| S4-011 | §refunds | ★ The target may be a direct payment, request payment or capture, but never a refund. (and, per the settlement paragraph, a settlement payment) | behaviour | `s4_01_refunds.refund_basics_shape_replay_limits_and_errors`, `s4_01_refunds.refunds_of_request_capture_and_settlement_payments_change_no_links_and_use_available_funds`, `s4_03_races_export.a_stage1_export_is_accepted_with_membership_and_refundable_payments`, `s4_03_races_export.a_stage2_export_is_accepted_and_captures_stay_refundable_but_immutable` |
| S4-012 | §refunds | Invalid amount is 422 `validation_failed`. | error | `s4_01_refunds.refund_basics_shape_replay_limits_and_errors` |
| S4-013 | §refunds | ★ Refunds cumulatively may not exceed the payment's current corrected amount: 422 `refund_exceeds_payment`. | error | `s4_01_refunds.refund_basics_shape_replay_limits_and_errors`, `s4_01_refunds.refund_limit_follows_the_current_corrected_amount_and_corrections_cannot_go_below_refunds`, `s4_01_refunds.refund_races_never_break_limits_or_overdraw` |
| S4-014 | §refunds | ★ Refunds of refunds give 422 `invalid_refund_target`. | error | `s4_01_refunds.refund_basics_shape_replay_limits_and_errors` |
| S4-015 | §refunds | ★ A refund is a new payment in the opposite direction, with `refund_of` naming the target, `request_id: null`, `authorization_id: null`, and the original note/visibility. | behaviour | `s4_01_refunds.refund_basics_shape_replay_limits_and_errors`, `s4_01_refunds.refunds_of_request_capture_and_settlement_payments_change_no_links_and_use_available_funds` |
| S4-016 | §refunds | ★ Return 201 with that payment; replay returns 200 with the original body. | idempotency | `s4_01_refunds.refund_basics_shape_replay_limits_and_errors`, `s4_01_refunds.refund_idempotency_scope_and_failed_keys` |
| S4-017 | §refunds | ★ It moves existing money from the receiver's **available** funds, or fails 409 `insufficient_funds`, atomically. | error | `s4_01_refunds.refund_basics_shape_replay_limits_and_errors`, `s4_01_refunds.refunds_of_request_capture_and_settlement_payments_change_no_links_and_use_available_funds`, `s4_01_refunds.refund_races_never_break_limits_or_overdraw`, `s4_03_races_export.mixed_refunds_batches_corrections_and_reads_keep_every_invariant` |
| S4-018 | §refunds | ★ Refunds never reopen a request or authorization or restore a released hold. | behaviour | `s4_01_refunds.refunds_of_request_capture_and_settlement_payments_change_no_links_and_use_available_funds` |
| S4-019 | §refunds | Other payments have `refund_of: null`. | behaviour | `s4_01_refunds.refund_basics_shape_replay_limits_and_errors` |
| S4-020 | §refunds | ★ Captures and refund payments cannot themselves be corrected: 422 `linked_payment_immutable`. | error | `s4_01_refunds.refund_basics_shape_replay_limits_and_errors`, `s4_01_refunds.refund_limit_follows_the_current_corrected_amount_and_corrections_cannot_go_below_refunds`, `s4_02_batches.batch_validation_item_errors_and_immutable_payments`, `s4_02_batches.settlement_members_are_corrected_only_as_a_complete_set_with_identical_instants`, `s4_03_races_export.a_stage2_export_is_accepted_and_captures_stay_refundable_but_immutable` |
| S4-021 | §refunds | ★ A correction cannot reduce a payment below its already-refunded amount: 422 `refund_exceeds_payment`. | error | `s4_01_refunds.refund_limit_follows_the_current_corrected_amount_and_corrections_cannot_go_below_refunds`, `s4_02_batches.batch_validation_item_errors_and_immutable_payments` |
| S4-022 | §refunds | ★ Correction debits are checked against available funds. | error | `s4_01_refunds.refund_limit_follows_the_current_corrected_amount_and_corrections_cannot_go_below_refunds`, `s4_02_batches.affordability_and_history_are_judged_on_the_combined_effect_of_the_whole_batch` |
| S4-023 | §refunds | Stage-3 corrections remain available for ordinary direct/request payments. | behaviour | `s4_01_refunds.refund_limit_follows_the_current_corrected_amount_and_corrections_cannot_go_below_refunds`, `s4_02_batches.batch_authorization_shape_shared_recorded_at_originals_and_replay` |
| S4-030 | §batches | ★ `POST /correction-batches` requires a settlement operator and an idempotency key, with the same 401/403 rules as settlements. | error | `s4_02_batches.batch_authorization_shape_shared_recorded_at_originals_and_replay` |
| S4-031 | §batches | ★ corrections contains 1..32 objects with distinct payment_ids, else 422 `validation_failed`. | error | `s4_02_batches.batch_validation_item_errors_and_immutable_payments` |
| S4-032 | §batches | ★ Every item has the ordinary correction fields and validation. Unknown payment is 404; a stale expected revision is 409 `stale_revision`. | error | `s4_02_batches.batch_validation_item_errors_and_immutable_payments`, `s4_02_batches.batch_error_precedence_item_errors_then_settlement_then_funds_then_history` |
| S4-033 | §batches | ★ The operator may correct ordinary, request and settlement payments, but captures and refunds remain immutable. | behaviour | `s4_02_batches.batch_authorization_shape_shared_recorded_at_originals_and_replay`, `s4_02_batches.batch_validation_item_errors_and_immutable_payments`, `s4_02_batches.settlement_members_are_corrected_only_as_a_complete_set_with_identical_instants`, `s4_02_batches.batch_error_precedence_item_errors_then_settlement_then_funds_then_history` |
| S4-034 | §batches | ★ Correcting any settlement member requires including every member of that settlement, else 422 `incomplete_settlement`. | error | `s4_02_batches.settlement_members_are_corrected_only_as_a_complete_set_with_identical_instants`, `s4_03_races_export.a_stage1_export_is_accepted_with_membership_and_refundable_payments` |
| S4-035 | §batches | ★ Members of one settlement must have identical effective instants (offset spellings may differ), else 422 `validation_failed`. | error | `s4_02_batches.settlement_members_are_corrected_only_as_a_complete_set_with_identical_instants` |
| S4-036 | §batches | ★ Ordinary single-payment corrections remain available for nonmembers. (Reading: a settlement member is corrected only through a batch; the single-payment endpoint answers 422 `incomplete_settlement` for a member of a multi-member settlement, 403 for a non-sender.) | error | `s4_02_batches.settlement_members_are_corrected_only_as_a_complete_set_with_identical_instants`, `s4_03_races_export.a_stage1_export_is_accepted_with_membership_and_refundable_payments` |
| S4-037 | §batches | Unknown fields are ignored. | behaviour | `s4_02_batches.batch_authorization_shape_shared_recorded_at_originals_and_replay`, `s4_02_batches.batch_validation_item_errors_and_immutable_payments` |
| S4-038 | §batches | ★ Error precedence is: item errors in input order, settlement completeness, resulting current available funds, then historical total and available funds at every effective/event boundary. | error | `s4_02_batches.batch_error_precedence_item_errors_then_settlement_then_funds_then_history`, `s4_02_batches.affordability_and_history_are_judged_on_the_combined_effect_of_the_whole_batch` |
| S4-039 | §batches | ★ The existing codes apply: `linked_payment_immutable`, `refund_exceeds_payment`, `insufficient_funds`, `historical_overdraft`. | error | `s4_02_batches.batch_error_precedence_item_errors_then_settlement_then_funds_then_history` |
| S4-040 | §batches | ★ Affordability is determined by the combined effect of all proposed revisions. (current available funds and historical boundaries are both judged on the whole batch) | behaviour | `s4_02_batches.affordability_and_history_are_judged_on_the_combined_effect_of_the_whole_batch`, `s4_03_races_export.mixed_refunds_batches_corrections_and_reads_keep_every_invariant` |
| S4-041 | §batches | ★ A rejected batch leaves history, balances and idempotency records unchanged. | behaviour | `s4_02_batches.batch_authorization_shape_shared_recorded_at_originals_and_replay`, `s4_02_batches.batch_validation_item_errors_and_immutable_payments`, `s4_02_batches.batch_error_precedence_item_errors_then_settlement_then_funds_then_history`, `s4_02_batches.affordability_and_history_are_judged_on_the_combined_effect_of_the_whole_batch`, `s4_03_races_export.batches_sharing_an_expected_revision_cannot_both_succeed_and_never_apply_partially`, `s4_03_races_export.mixed_refunds_batches_corrections_and_reads_keep_every_invariant` |
| S4-042 | §batches | ★ Return 201 with `correction_batch_id`, `recorded_at` and `revisions` in input order. | behaviour | `s4_02_batches.batch_authorization_shape_shared_recorded_at_originals_and_replay`, `s4_02_batches.batch_recorded_at_is_strictly_after_a_correction_made_just_before` |
| S4-043 | §batches | ★ All new revisions share recorded_at, strictly later than the previous recorded_at of every member; | behaviour | `s4_02_batches.batch_authorization_shape_shared_recorded_at_originals_and_replay`, `s4_02_batches.settlement_members_are_corrected_only_as_a_complete_set_with_identical_instants`, `s4_02_batches.batch_recorded_at_is_strictly_after_a_correction_made_just_before` |
| S4-044 | §batches | each revision also exposes correction_batch_id. | behaviour | `s4_02_batches.batch_authorization_shape_shared_recorded_at_originals_and_replay` |
| S4-045 | §batches | Effective times cannot be later than now. | error | `s4_02_batches.batch_authorization_shape_shared_recorded_at_originals_and_replay`, `s4_02_batches.batch_validation_item_errors_and_immutable_payments` |
| S4-046 | §batches | ★ Original payments and receipts never change. | behaviour | `s4_02_batches.batch_authorization_shape_shared_recorded_at_originals_and_replay`, `s4_02_batches.settlement_members_are_corrected_only_as_a_complete_set_with_identical_instants`, `s4_02_batches.snapshots_stay_frozen_after_a_batch_and_new_statements_show_it` |
| S4-047 | §batches | ★ Original payment and settlement retries return their original bodies. | idempotency | `s4_02_batches.batch_authorization_shape_shared_recorded_at_originals_and_replay`, `s4_02_batches.settlement_members_are_corrected_only_as_a_complete_set_with_identical_instants`, `s4_03_races_export.round_trip_keeps_refunds_batches_membership_snapshots_and_replays` |
| S4-048 | §batches | ★ New statements reflect the new revisions; earlier snapshot tokens continue to page their frozen entries. | behaviour | `s4_02_batches.snapshots_stay_frozen_after_a_batch_and_new_statements_show_it`, `s4_03_races_export.round_trip_keeps_refunds_batches_membership_snapshots_and_replays` |
| S4-049 | §batches | ★ Replays return the original batch response with 200. | idempotency | `s4_02_batches.batch_authorization_shape_shared_recorded_at_originals_and_replay` |
| S4-050 | §batches | ★ This adds one idempotent write path. | idempotency | `s4_02_batches.batch_authorization_shape_shared_recorded_at_originals_and_replay`, `s4_03_races_export.batches_sharing_an_expected_revision_cannot_both_succeed_and_never_apply_partially`, `s4_03_races_export.mixed_refunds_batches_corrections_and_reads_keep_every_invariant` |
| S4-051 | §settlement | ★ A settlement payment may be refunded under the existing refund rules, but refunds never change settlement membership. | behaviour | `s4_01_refunds.refunds_of_request_capture_and_settlement_payments_change_no_links_and_use_available_funds`, `s4_02_batches.settlement_members_are_corrected_only_as_a_complete_set_with_identical_instants` |
| S4-052 | §settlement | ★ Concurrent corrections sharing any expected payment revision cannot both succeed. | concurrency | `s4_01_refunds.refund_races_never_break_limits_or_overdraw`, `s4_03_races_export.batches_sharing_an_expected_revision_cannot_both_succeed_and_never_apply_partially`, `s4_03_races_export.mixed_refunds_batches_corrections_and_reads_keep_every_invariant` |
| S4-053 | §settlement | ★ A stage-4 service must accept exports produced by the same team's stages 1–3, retaining settlement membership, corrections and snapshots. | data-migration | `s4_03_races_export.round_trip_keeps_refunds_batches_membership_snapshots_and_replays`, `s4_03_races_export.a_stage1_export_is_accepted_with_membership_and_refundable_payments`, `s4_03_races_export.a_stage2_export_is_accepted_and_captures_stay_refundable_but_immutable`, `s4_03_races_export.a_stage3_export_is_accepted_with_corrections_membership_and_snapshots`; plus manual — stage-1 export: needs a running stage-1 service of the same team: --stage1-url URL; without it that probe reports SKIP and the reviewer runs it once; stage-2 export: needs a running stage-2 service of the same team: --stage2-url URL; without it that probe reports SKIP and the reviewer runs it once; stage-3 export: needs a running stage-3 service of the same team: --stage3-url URL; without it that probe reports SKIP and the reviewer runs it once |
| S4-054 | §derived | ★ (derived, concurrency) concurrent refunds are cumulatively limited by the payment's corrected amount (10 × 40 on 300 → exactly 7 succeed); a refund and a correction that would go below it race: exactly one wins and refunded ≤ current amount holds afterwards. | concurrency | `s4_01_refunds.refund_idempotency_scope_and_failed_keys`, `s4_01_refunds.refund_races_never_break_limits_or_overdraw`, `s4_03_races_export.mixed_refunds_batches_corrections_and_reads_keep_every_invariant` |
| S4-055 | §derived | ★ (derived, concurrency) a refund and another payment compete for the receiver's available funds: exactly one succeeds; no balance or available goes negative. | concurrency | `s4_01_refunds.refund_races_never_break_limits_or_overdraw` |
| S4-056 | §derived | ★ (derived, concurrency) a refund racing a correction below the refunded amount (see 54): the loser is `refund_exceeds_payment`. | concurrency | `s4_01_refunds.refund_limit_follows_the_current_corrected_amount_and_corrections_cannot_go_below_refunds`, `s4_01_refunds.refund_races_never_break_limits_or_overdraw` |
| S4-057 | §derived | ★ (derived, concurrency) a batch that loses a race on one shared payment applies nothing at all — its other payments keep their revision history and money. | concurrency | `s4_03_races_export.batches_sharing_an_expected_revision_cannot_both_succeed_and_never_apply_partially` |
| S4-059 | §derived | ★ (derived) refund payments are ordinary payments for statements, `as_of`/`known_at` views and the activity feed (visibility copied from the target). | behaviour | `s4_01_refunds.refund_basics_shape_replay_limits_and_errors`, `s4_03_races_export.mixed_refunds_batches_corrections_and_reads_keep_every_invariant` |
| S4-060 | §migration | ★ (state kind: refunds) refund payments with `refund_of` and the cumulative refunded amounts survive import; the refund limit keeps counting across import. | data-migration | `s4_03_races_export.round_trip_keeps_refunds_batches_membership_snapshots_and_replays` |
| S4-061 | §migration | ★ (state kind: correction batches) batch records — `correction_batch_id`, shared `recorded_at`, per-revision batch ids and the original batch response for replays — survive import; new batch ids do not collide. | data-migration | `s4_03_races_export.round_trip_keeps_refunds_batches_membership_snapshots_and_replays`, `s4_03_races_export.a_stage1_export_is_accepted_with_membership_and_refundable_payments`, `s4_03_races_export.a_stage3_export_is_accepted_with_corrections_membership_and_snapshots` |
| S4-062 | §migration | ★ (state kind: revisions) revision histories of every payment travel with the export (stage-3 exports included); stage-4 revision objects add `correction_batch_id`. | data-migration | `s4_03_races_export.round_trip_keeps_refunds_batches_membership_snapshots_and_replays`, `s4_03_races_export.a_stage3_export_is_accepted_with_corrections_membership_and_snapshots` |
| S4-063 | §migration | ★ (state kind: recorded_at / effective_at) times are not regenerated: historical `as_of`/`known_at` views, statements and revision lists are identical after import; new recorded times are later than imported ones. | data-migration | `s4_03_races_export.round_trip_keeps_refunds_batches_membership_snapshots_and_replays`, `s4_03_races_export.a_stage3_export_is_accepted_with_corrections_membership_and_snapshots` |
| S4-064 | §migration | ★ (state kind: settlement membership) which payments belong to which settlement survives import (also from stage-1/stage-3 exports): partial corrections are still `incomplete_settlement`, the full set is accepted, settlement retries return their original body. | data-migration | `s4_03_races_export.round_trip_keeps_refunds_batches_membership_snapshots_and_replays`, `s4_03_races_export.a_stage1_export_is_accepted_with_membership_and_refundable_payments`, `s4_03_races_export.a_stage3_export_is_accepted_with_corrections_membership_and_snapshots` |
| S4-065 | §migration | ★ (state kind: snapshots) statement snapshot tokens are part of the state: a token taken before export pages the same frozen entries after import; reset discards them. (Reading: for a stage-3 export a token is retained if the source exported it; a 404 is tolerated there, wrong data is not.) | data-migration | `s4_03_races_export.round_trip_keeps_refunds_batches_membership_snapshots_and_replays`, `s4_03_races_export.a_stage3_export_is_accepted_with_corrections_membership_and_snapshots` |
| S4-066 | §migration | ★ (state kind: tokens/sessions) bearer tokens issued before export stay valid after import; tokens issued after export are gone. | data-migration | `s4_03_races_export.round_trip_keeps_refunds_batches_membership_snapshots_and_replays`, `s4_03_races_export.a_stage3_export_is_accepted_with_corrections_membership_and_snapshots` |
| S4-067 | §migration | ★ (state kind: idempotency records) completed keys of all ten write paths (incl. refunds and correction batches) replay 200 with their original bodies after import; a different body is still 409. | data-migration | `s4_03_races_export.round_trip_keeps_refunds_batches_membership_snapshots_and_replays`, `s4_03_races_export.a_stage3_export_is_accepted_with_corrections_membership_and_snapshots` |
| S4-068 | §migration | ★ (state kind: authorizations, holds, captures, opening balances, earlier kinds) every earlier state kind still survives export/import; the stage-1/2/3 round-trip probes are re-run by this runner. | data-migration | `s4_03_races_export.round_trip_keeps_refunds_batches_membership_snapshots_and_replays`; plus manual — re-run of the earlier stages' probe suites by this runner (see the table of changed earlier rows) |
| S4-069 | §migration | ★ (derived) imported stage-1/2/3 payments are refundable by their receiver, imported captures are refundable but immutable, imported opening balances and revisions keep `as_of`/statement views consistent. | data-migration | `s4_03_races_export.a_stage1_export_is_accepted_with_membership_and_refundable_payments`, `s4_03_races_export.a_stage2_export_is_accepted_and_captures_stay_refundable_but_immutable`, `s4_03_races_export.a_stage3_export_is_accepted_with_corrections_membership_and_snapshots` |
| S4-070 | §review | Review notes forwarded for stage 4: none yet. | review-note | manual — none forwarded |
| S4-090 | §earlier | ★ (earlier invariant, re-checked) the sum of balances equals the seeded total and no `total`/`available` is ever negative at any read or past boundary, through refunds, corrections and batches. | concurrency | `s4_02_batches.batch_authorization_shape_shared_recorded_at_originals_and_replay` |
| S4-102 | §derived | ★ (derived, with S4-048) a saved statement taken before a batch pages the same entries afterwards for both parties; `known_at` just before the batch's `recorded_at` still reproduces the old statement. | behaviour | `s4_02_batches.snapshots_stay_frozen_after_a_batch_and_new_statements_show_it` |
| S4-110 | §derived | ★ (derived, with S4-017/S4-018) a refund never changes the target request's `paid` state, the authorization's status/captured amount/hold, or the settlement member's receipt. | behaviour | `s4_01_refunds.refunds_of_request_capture_and_settlement_payments_change_no_links_and_use_available_funds` |

## Summary

Row counts by kind: behaviour 21, error 17, data-migration 11, concurrency 6, idempotency 5, review-note 1 (61 rows).
★ rows: 53. Rows with a `manual` component: 4 (the three earlier-stage export imports that need the earlier services, the
earlier-suite re-run, and the not-yet-forwarded review notes).

Data-migration rows by state kind: refunds (S4-060), correction batches (S4-061), revisions (S4-062), recorded/effective
times (S4-063), settlement membership (S4-064), snapshots (S4-065), tokens (S4-066), idempotency records (S4-067),
earlier kinds (S4-068), stage-1/2/3 exports accepted (S4-053, S4-069).
Concurrency rows: S4-052/057 (batches sharing a revision, atomicity), S4-054/055/056 (refund races), S4-090 (invariants).

## Running the probes

    python3 factory/probes/stage-4/run_all.py http://127.0.0.1:8080                       # stage-4 + all earlier non-UI probes
    python3 factory/probes/stage-4/run_all.py http://127.0.0.1:8080 --no-prior             # stage-4 probes only
    python3 factory/probes/stage-4/run_all.py http://127.0.0.1:8080 --stage1-url http://127.0.0.1:8081 --stage2-url http://127.0.0.1:8082 --stage3-url http://127.0.0.1:8083
    python3 factory/probes/stage-4/run_all.py http://127.0.0.1:8080 --with-ui --peer http://127.0.0.1:8084
    python3 factory/probes/stage-4/check_ledger.py                                         # ledger <-> probe cross-check (no service)

Python 3.8+ standard library; `--with-ui` needs Playwright + Chromium (otherwise those probes report SKIP).
`--stageN-url` are running stage-N services of the same team whose exports are imported into the service under test
(without them the three import probes report SKIP, not PASS). Probes wipe all service state; use a disposable
container. Exit status 0 only if nothing fails.
