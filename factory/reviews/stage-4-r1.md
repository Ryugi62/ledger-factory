# Stage 4 — review round 1

- Commit checked: `b39bad590d1057330ef053ad7b38ac7e6f76d0b9` (branch main; tracked tree clean)
- Ledger: `factory/ledger/stage-4.md` (62 rows at 114cbaf); stage-1..3 ledgers still in force
- **Verdict: ACCEPT**

## 1. Blind re-derivation

Committed as `factory/reviews/stage-4-blind.md` (66eee80) before the ledger was opened. It covers the two longest
sections: "Batch corrections" (BB-01..26) and "Refunds and corrected history" (BR-01..19). Every statement maps to a
ledger row; for example BR-19 → S4-036 and BR-14 → S4-059. No ledger gaps. `check_ledger.py`: 62 rows, agree.

## 2. Clean build and start

`docker build -t rv-s4 stage-4` OK. Runs with `--cpus 2 --memory 2g` on the default 8080 and with `-e PORT`; `/health`
200 at once. Upgrade sources were built from the accepted `stage-1/`, `stage-2/` and `stage-3/` folders.

## 3. Checks (all on b39bad5)

| Command | Result |
|---|---|
| `docker run --rm --network none --cpus 2 --memory 2g rv-s4 node --test` | 24 / 24 pass |
| Probes from a Linux container on a private Docker network: `stage-4/run_all.py http://r4a:8080 --peer http://r4b:9402 --stage1-url … --stage2-url … --stage3-url …` | 148 passed, 0 failed, 0 skipped. The memory probe s4_04 passed in 2.0 s; r4a used 40 MiB afterwards |
| Browser probes from the host (port 19591, mine only): `stage-3/run_all.py --no-prior --with-ui -k ui` | 2 / 2 pass |
| Browser probes from the host: `stage-2/run_all.py --no-stage1 -k ui` | 19 / 19 pass |
| `.venv/bin/python -m harness run … --stage 4 --mode isolated --out …/checks/r3-s4-reviewer-1` | stage 1: 147 / 147, stage 2: 35 / 35, stage 3: 6 / 6, stage 4: 5 / 5, "claimed stage: 4" |
| Reviewer memory scenario (`--memory 2g`): 3000 seeded payments, 2000 × `GET /statement?limit=10` at 50 in flight | alive; 77 MiB; p99 54 ms |

Reviewer edge script; all results as specified:
- Refund permissions: refund by the sender or a third party → 403; unknown payment → 404; no key → 400; no token →
  401. Six invalid amounts → 422.
- Refund payment shape: opposite direction; note and visibility copied; `refund_of` set; request, authorization and
  settlement ids null. Replay → 200.
- Refund limits: a refund of a refund → `invalid_refund_target`. Cumulative limit → `refund_exceeds_payment`.
  Correcting to 99 with 100 refunded → `refund_exceeds_payment`; correcting to exactly 100 → 201, and the refund
  limit then counts the corrected amount. The feed still shows the original 300.
- Refund funding and links: a refund is judged on available funds, not held funds (60 with 50 available → 409; 50 →
  201). Refunding a capture leaves the authorization `captured` with no hold restored; the capture and the refund
  payment are both `linked_payment_immutable`.
- Settlement members: a single correction of a member → `incomplete_settlement`. A member can be refunded.
- Batch auth and shape: 401 without a token, 403 for a non-operator; empty, 33 items or duplicate ids → 422.
- Batch errors and precedence: `incomplete_settlement`; unequal member instants → 422; item errors win in input order
  (404 before immutable, immutable before 404, stale before completeness).
- Batch success: a member batch with different offset spellings for the same instant → 201, and all revisions share
  `recorded_at` and `correction_batch_id`. Replay → 200; changed body → 409. The settlement retry returns its
  original body, and `/revisions` shows the batch id.
- Combined effect: one item alone is unaffordable (409), but paired with an offsetting item at the same instant →
  201.
- Concurrency: one batch pair and singles racing on a shared revision → exactly one 201 and the rest 409; the loser's
  other payment is untouched.
- Σ totals = seeded total.

## 4. Reading

- Single corrections and batch items share `proposal` and `commit` in `services/corrections.js`.
- Commit checks current available funds on the net change per wallet, then historical solvency for every involved
  wallet with all proposed revisions overriding. It then appends revisions with one `recorded_at` and moves the net.
- Batches (`services/batches.js`, about 60 lines) follow the spec's precedence exactly.
- Refunds (`services/refunds.js`) are a single synchronous transfer with a running refunded total, which import
  recomputes from `refund_of`.
- Snapshots stay compact and now travel in the export, together with `rev_seq` and each revision's `rseq`.
- No special-casing was found. The largest file is 241 lines. The implementer's judgement calls (a)–(d) are
  acceptable.

## 5. Earlier stages

`git diff d1be8d8 b39bad5 -- stage-1`, `git diff 4d44098 b39bad5 -- stage-2` and `git diff 88070ae b39bad5 -- stage-3`
are all empty.

## Non-blocking notes

None.
