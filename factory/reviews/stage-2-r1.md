# Stage 2 — review round 1

- Commit checked: `b9dd8bd2e1d1aa0a01e29985fd5036f41490ada8` (branch main; tracked tree clean; the only untracked
  path was `factory/probes/stage-3/`, the analyst's work, outside the stage folders)
- Ledger: `factory/ledger/stage-2.md` (199 rows at 68d4beb); stage-1 ledger still in force
- **Verdict: ACCEPT**

## 1. Blind re-derivation

Committed as `factory/reviews/stage-2-blind.md` (ad0c2e6) before the ledger was opened. It covers the two longest
sections, "API" (BA-01..56) and "Model" (BM-01..17). Every statement maps to a ledger row or a stated Reading
(e.g. BA-44 `final` wrong type → Reading 3; BM-16 → S2-121). No ledger gaps. `check_ledger.py`: 199 rows,
54 stage-2 probes, agree.

## 2. Clean build and start

`docker build -t rv-s2 stage-2` OK (node:22-alpine, no dependencies; UI assets served from the image, system
fonts). Two runs with `--cpus 2 --memory 2g`, one with `-e PORT=9201` and one on the default 8080: both `/health`
200 within ~1 s. The stage-1 image built from `stage-1/` was used as the upgrade source.

## 3. Checks (all on b9dd8bd)

| Command | Result |
|---|---|
| `docker run --rm --network none --cpus 2 --memory 2g rv-s2 node --test` | 17 / 17 pass |
| `python3 factory/probes/stage-2/run_all.py http://127.0.0.1:19211 --peer http://127.0.0.1:19212 --stage1-url http://127.0.0.1:19213 --shots /tmp/rv-s2-shots` (stage-1 regression + API + Playwright browser + cross-instance + stage-1 upgrade) | 122 passed, 0 failed, 0 skipped |
| `.venv/bin/python -m harness run --track pocketful … --stage 2 --mode isolated --out …/checks/r3-s2-reviewer-1` | stage 1: 147 / 147, stage 2: 35 / 35, "claimed stage: 2" (stage 3 fails as expected) |
| Reviewer API script (JPY fixture, ttl 3 s; seeded open/expired-in-past/voided holds; holds > balance reset 422; invalid TTLs 0/−1/1.5/"5"/true all 422; available-based 409 on payment, settlement, authorization; party rules 403/404 on capture and void; `final:"no"` 422, amount 0 422, exceeds → `capture_exceeds_authorization`; 10 concurrent non-final 100-captures of 500 → exactly 5 × 201 and 5 × `authorization_not_open`, captured 500, 5 payment_ids; capture-vs-void race consistent; Σ totals = 1000; partial capture then clock expiry releases only the remainder and keeps the capture record; expired capture → `authorization_expired`, void → `authorization_not_open`; `status=open` excludes clock-expired; `authorization_id: null` on plain payments; `/authorizations` HTML for `Accept: text/html`) | all as specified |

## 4. Reading

- Server changes since stage 1 are small and targeted. Payment, request-pay and settlement funding checks now use
  `available`. Holds live on the user and are recomputed on reset and import. Expiry is applied at the start of
  every authenticated request and every export, and capture re-checks the clock. All mutation remains synchronous,
  so operations are serialisable.
- Export carries authorizations with absolute deadlines and capture records, plus the TTL. A stage-1 export imports
  with defaults (verified by the probes' upgrade path and by the harness upgrade source).
- No fixture or test special-casing was found. The largest file is 200 lines.
- UI, reviewed from screenshots at 375 px and 1280 px:
  - The visual system is calm and coherent: one accent colour, cards, consistent navigation (Wallet / Requests /
    Split a bill / Holds).
  - "Available to spend" is the headline; total and on-hold amounts are secondary, and on-hold has its own colour.
  - Status pills are distinct (pending, paid, declined, cancelled, open, captured, voided, expired), as are the
    public/private badges.
  - Labels are visible, errors are inline, and empty states are worded with care. Amounts are formatted with the
    sign outside the `activity-amount` span. Timestamps read as "Today, 08:32 PM", with the raw RFC 3339 value
    only where the spec requires it.
  - Long unbroken notes wrap with no horizontal scroll.

## 5. Earlier stages

`git diff d1be8d8 b9dd8bd -- stage-1` is empty: stage-1/ is unchanged since it was accepted.

## Non-blocking notes

1. The request-screen "Pay" button always pays with public visibility. The spec says the payer chooses visibility
   when money moves; the API supports it, but the UI gives no choice (implementer judgement call b). Consider a
   small public/private choice next to Pay.
2. On `/authorizations`, closed outgoing holds keep the headline "You're holding money for @bob" even when they are
   voided or expired (the status pill is right). A status-aware headline such as "Hold for @bob released" would read
   better.
