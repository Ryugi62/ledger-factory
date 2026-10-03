# Stage 3 — review round 1

- Commit checked: `425311d76bb7130713dca4a888513ad25a84504a` (branch main; tracked tree clean; the only untracked
  path was `factory/probes/stage-4/`, the analyst's work)
- Ledger: `factory/ledger/stage-3.md` (106 rows at f1055c3); stage-1 and stage-2 ledgers still in force
- **Verdict: ACCEPT** (one strongly recommended non-blocking fix, note 1)

## 1. Blind re-derivation

Committed as `factory/reviews/stage-3-blind.md` (e4b3a5d) before the ledger was opened. It covers the two longest
sections: "Effective time, recorded time, and corrections" (BC-01..49) and "`GET /statement`" (BS-01..15). Every
statement maps to a ledger row; BS-14 (invalid from/to) is covered by the S3-030 Reading. No ledger gaps.
`check_ledger.py`: 106 rows, agree.

## 2. Clean build and start

`docker build -t rv-s3 stage-3` OK. Runs with `--cpus 2 --memory 2g` on the default 8080 and with `-e PORT`; `/health`
200 at once. Upgrade sources were built from the accepted `stage-1/` and `stage-2/` folders.

## 3. Checks (all on 425311d)

| Command | Result |
|---|---|
| `docker run --rm --network none --cpus 2 --memory 2g rv-s3 node --test` | 21 / 21 pass |
| Probes from a Linux container on a Docker network (macOS runs out of ephemeral ports): `run_all.py http://r3a:8080 --peer http://r3b:9302 --stage1-url http://r1u:8080 --stage2-url http://r2u:8080` | 132 passed, 0 failed, 2 skipped (browser probes; no Playwright in that container) |
| Browser probes from the host: `stage-3/run_all.py … --no-prior --with-ui -k ui` | 2 / 2 pass |
| Browser probes from the host: `stage-2/run_all.py … --no-stage1 -k ui` | 19 / 19 pass |
| `.venv/bin/python -m harness run … --stage 3 --mode isolated --out …/checks/r3-s3-reviewer-1` | stage 1: 147 / 147, stage 2: 35 / 35, stage 3: 6 / 6, "claimed stage: 3" (stage 4 fails as expected) |

Reviewer script; all results as specified:
- Reset with a seeded `created_at` in the future → 422.
- `as_of` before, at, just after and between payments is inclusive and echoed exactly. Naive time, bare date, empty
  value and a space instead of the offset sign → 422. An unencoded `+` is accepted.
- The statement window, deltas and balance chain are correct. A third party's statement does not show public
  payments.
- Corrections:
  - 403 for a non-sender, 404 for an unknown payment, 400 without a key.
  - Seven invalid field values → 422.
  - 201 with `recorded_at` set by the server; replay 200; key reuse 409; stale revision 409.
  - Money moves between the same two wallets.
  - Current `/me`, `as_of` and `known_at` views and statements match hand-computed values, before and after the
    correction.
  - The activity feed keeps the original amount. Revisions: 404 for a third party, 401 without a token.
  - `insufficient_funds` takes precedence. `historical_overdraft` triggers when a past boundary goes negative and
    leaves state and the key untouched; the key is then reusable.
- Snapshots: paging works; adding `from` → 422; another user's token → 404; an offset past the end gives
  `has_more: false`.
- A settlement member → 422 `linked_payment_immutable`, and its revision 1 is at `committed_at`.
- 8 concurrent corrections with the same expected revision → exactly one 201.
- Σ balances = seeded total, now and at three `as_of` instants.

## 4. Reading

- Bitemporal logic sits in `services/history.js` (121 lines): revision selection by `known_at`, effective-time
  application, hold timelines, and a solvency check over combined boundaries for both total and available.
  Corrections live in `services/corrections.js`; their check order is documented and matches the spec.
- All writes are still synchronous.
- Opening balances are derived once (fixture or import) and never touched by corrections.
- Export carries revisions, hold events and opening balances. Stage-1 and stage-2 exports import, verified by the
  upgrade probes.
- No special-casing was found, and no file is over 215 lines.

## 5. Earlier stages

`git diff d1be8d8 425311d -- stage-1` and `git diff 4d44098 425311d -- stage-2` are both empty.

## Non-blocking notes

1. **Statement snapshots are kept fully materialized forever, and memory can be exhausted.** Every fresh
   `GET /statement` stores the full list of entries (payment views included) in `state.snapshots`. Measured with
   `--memory 2g`: a 200-entry statement costs about 42 KB per read (3000 reads → +137 MiB). With a 3000-payment wallet
   and 2000 reads at 50 in flight, the Node heap reached about 1 GB and the process died with exit 139, "JavaScript
   heap out of memory". That loses all state; the requirements say "Requests must not produce 5xx responses,
   including under concurrent load" and give a 2 GiB limit.
   - The spec sets no history size, so this is not a rejection. The fix is cheap, though: store snapshots compactly
     (the window plus a per-read revision/sequence cut-off, or just `[payment id, revision, delta, balance_after]`
     tuples), and/or raise `--max-old-space-size` to use the 2 GiB.
   - Repro: reset a fixture with 3000 seeded payments for one user, then call `GET /statement?limit=10` 2000 times
     with 50 in flight.
2. Implementer judgement calls (a)–(e) are acceptable readings of the spec.
