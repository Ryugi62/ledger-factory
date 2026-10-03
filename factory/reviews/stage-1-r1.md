# Stage 1 — review round 1

- Commit checked: `3f766d43f941bd4bc2b465991635574f7f3b0313` (branch main; tracked tree clean at that commit;
  the only untracked path was `factory/probes/stage-2/`, the analyst's in-progress stage-2 work, outside `stage-1/`)
- Ledger: `factory/ledger/stage-1.md` @ bc54358 (192 rows)
- **Verdict: ACCEPT**

## 1. Blind re-derivation

Committed as `factory/reviews/stage-1-blind.md` (8cc20e2) before the ledger was opened: §8 API (B8-01..67) and
§4 Model (B4-01..50). Compared with the ledger: every blind statement maps to a ledger row (or an explicit
"Reading"). No ledger gaps. `check_ledger.py`: 192 rows, 68 probes, "ledger and probes agree".

## 2. Clean build and start

- `docker build -t rv-pocketful-s1 stage-1` — OK (node:22-alpine, no third-party dependencies).
- `docker run --cpus 2 --memory 2g -e PORT=9101 -p 19101:9101` → `/health` 200 `{"status":"ok"}` within ~1 s.
- `docker run --cpus 2 --memory 2g -p 19102:8080` (no PORT) → `/health` 200, so the default 8080 works.

## 3. Checks (all on 3f766d4)

| Command | Result |
|---|---|
| `docker run --rm --network none rv-pocketful-s1 node --test` | 8 / 8 pass |
| `python3 factory/probes/stage-1/run_all.py http://127.0.0.1:19101 --peer http://127.0.0.1:19102` | 69 passed, 0 failed, 0 skipped |
| `.venv/bin/python -m harness run --track pocketful --repo …/result-r3 --stage 1 --mode isolated --out …/checks/r3-s1-reviewer-1` | stage 1: 147 / 147 pass, "claimed stage: 1" (stage 2: fails as expected) |
| Reviewer edge script (BHD fixture, case-mixed seeded email, private seeded payment, seeded declined request, pay/decline/cancel party rules, `{}` vs empty vs `{"visibility":"public"}` replays, amount `1e3`/`10.5`/`[1]`, key 255/256, query `+4`/`0`/`200`/`-1`/empty, split order 10/3 with caller in the middle, caller-only split, settlement 403/400/422/409, operator sees no foreign requests, signup derivation `Zed.Q+1@ex.com` → `zed_q_1` and `handle_taken`, negative-balance reset leaves state) | all as specified |

## 4. Reading

No fixture- or test-name special-casing; no sign of shaping by the shipped checks' source. All mutations are
synchronous on the single event loop after validation, so payments, request payment, idempotency claims and
settlements are atomic and race-free; signup re-checks uniqueness after the async hash. Export carries every
state kind (users + hashes, tokens, operators, payments, requests, splits, settlements, idempotency records,
counters) and is deep-copied. Largest file 162 lines. Every ★ row has a probe.

## 5. Earlier stages

Stage 1 is the first stage; nothing to compare.

## Non-blocking notes

1. Reset time grows with distinct fixture passwords (scrypt N=16384 per distinct password on 2 vCPU): 100 users
   1.4 s, 300 users 3.9 s, 1000 users 12.9 s — over the 10 s reset limit. The spec gives no fixture size, and
   shared passwords are hashed once, so normal fixtures are fast. Lowering the cost for seeded users, or hashing
   lazily on first login, would remove the risk. Repro: reset with 1000 users `password-<i>`.
2. Signup awaits hashing and then writes into whatever state is live. A signup that overlaps a `POST /_test/reset`
   can insert its account into the freshly reset state ("subsequent requests must see only that fixture").
   Balance 0, so money is unaffected. Same pattern: two overlapping resets finish in hashing order, not request order.
3. Fixtures accept `minor_units` 0..8; the spec names 0, 2, 3. Harmless (no rejection is required).
