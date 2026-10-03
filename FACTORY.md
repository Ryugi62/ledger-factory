# FACTORY.md — Ledger Factory

A four-seat software factory for Band Desktop that builds a service from a written
specification with no human in the loop. Its one idea: **the verifier, not the generator,
is the bottleneck.** The shipped checks cover only part of each stage (pocketful: 79 %,
35 %, 9 %, 16 %), and "every one of [the hidden tests] is written in the specification".
So before any code exists, one seat turns the specification into a numbered **requirement
ledger**, and the judge refuses a revision that cannot show evidence against it.

```
human ──(one task message for the whole run)──▶ @coordinator
                                                   │  full spec, pasted in numbered parts
                       ┌───────────────────────────┤
                       ▼                           ▼
                  @analyst                    @implementer ◀── findings / notes, by ID ──┐
      ledger: every normative sentence          stage-N/: modules + unit tests,            │
      (★ = what a minimal build skips),         one commit per group of ledger rows        │
      export rows per kind of state,                  │ full revision + requirements       │
      review notes as rows; black-box probes          ▼                                    │
      from the spec only ───────────────────▶  @reviewer: blind list (committed) · clean ──┘
                                                build · unit tests · isolated checks ·
                                                probes · diff reading → ACCEPT / REJECT
```

## Seats

| Seat | Harness | Model | Owns | Never does |
|---|---|---|---|---|
| coordinator | Claude Code | claude-sonnet-5-5 | dispatch, self-contained handoffs, stop / silence / notes rules, `factory/run-log.md` | write product code, accept work |
| analyst | Claude Code | claude-sonnet-5-5 | `factory/ledger/stage-N.md`, `factory/probes/stage-N/` | open the shipped checks, write product code |
| implementer | Claude Code | claude-opus-5-5 | `stage-N/`: modules, unit tests, Dockerfile, RUN.md | open the shipped checks' source, accept its own work, edit an accepted stage |
| reviewer | Claude Code | claude-opus-5-5 | `factory/reviews/stage-N-blind.md`, `stage-N-rK.md`, ACCEPT / REJECT | fix code, accept on anything but the exact commit |

Standing instructions: `mandates/<seat>.md`. They name no endpoint, field or error code;
`harness check` finds no track vocabulary in them. Everything track-specific arrived in the
single task message — the first message in `room.json`, the only human message there.

## Design choices and what they cost

1. **Ledger before code.** The analyst quotes every normative sentence of a stage as a row
   with an ID, a kind and the probe that exercises it. This run: **559 rows** (192 / 199 /
   106 / 62), **344 ★**, 519 with a probe, 40 with a manual component (container limits,
   provenance, visual judgement), **0 known gaps**. Cost: the analyst is the most expensive
   seat (42 % of spend) and starts every stage; the coordinator pipelines the next ledger
   while a stage is in review.
2. **Probes from the spec, never from the shipped checks.** The analyst never opens them;
   the implementer may read the probes (the spec in executable form) but **must not open the
   shipped checks' source** — only their failure output. In this run the room log shows no
   tool call that opened a shipped test file. When a failing check pointed at something the
   ledger did not state, the implementer reported it as a ledger gap and implemented it from
   the spec (twice in stage 2, recorded in the run log).
3. **A reviewer that does not trust the ledger or the implementer.** It commits its own
   blind list of the two longest sections before opening the ledger (`stage-N-blind.md`),
   then rebuilds on a clean clone, runs unit tests, isolated checks and probes **on the exact
   commit in the repository**, and reads the diff, including for files too large to
   maintain and state that an export would drop.
4. **Every review note gets an owner.** Non-blocking notes are numbered; the coordinator
   sends each to the implementer as its own fix commit or waives it with a reason, and the
   analyst turns it into a row and probe of the next stage's ledger. Five notes were fixed
   this way; two were waived with reasons.
5. **Code a maintainer can work in.** Modules for domain rules, state, services, transport
   and UI; no file over ~250 lines; unit tests inside each stage folder, runnable offline
   (`docker run --rm --network none <image> node --test`).
6. **Stop rule and silence rule.** At most four review rounds per stage; the coordinator
   waits on the git log after each handoff and resends after 45 min of silence (a lesson from
   an earlier run — see "what failed").

## Measured run (the submitted one)

One dispatch at 2026-10-03 10:10:35 UTC; final report 12:49:44 UTC — **2 h 39 min, no
human message in between.**

| Stage | Window (UTC) | Rounds | What review changed | Ledger rows (★) | Unit tests | Isolated harness (shipped checks) | Accepted |
|---|---|---|---|---|---|---|---|
| 1 | 10:10–10:49 | 1 + fix confirmation | notes 1–2 → `d1be8d8` | 192 (94) | 12 | s1 147/147 · claimed 1 | `d1be8d8` |
| 2 | 10:50–11:44 | 1 + fix confirmation | notes 1–2 → `4d44098` | 199 (107) | 17 | 147/147 · 35/35 · claimed 2 | `4d44098` |
| 3 | 11:44–12:34 | 1 + fix confirmation | note 1 (memory) → `88070ae` | 106 (89) | 21 | + 6/6 · claimed 3 | `88070ae` |
| 4 | 12:34–12:49 | 1 | — | 62 (54) | 24 | + 5/5 · claimed 4 | `b39bad5` |

`harness run --all --mode isolated` on a fresh clone: **every folder claims its own stage**
(chain 1 → 4). On top of the shipped checks the reviewer ran, on the final stage: 24 unit
tests, 148 probe assertions (offline, with upgrades from stage-1/2/3 exports and a second
instance), 21 browser probes, and a 3,000-payment load scenario (77 MiB).

**Model spend** (Band's list-price estimate for this room; the seats ran on existing
subscriptions, so cash cost $0): analyst $25.12 · implementer $23.27 · reviewer $9.51 ·
coordinator $2.42 · **total $60.32**, about $15 per accepted stage.

Work split (git): implementer 25 commits, analyst 9 (ledgers, probes, review-note rows),
reviewer 12 (4 blind lists, 7 verdicts, 1 addendum), coordinator 4 reports. Nothing under
`stage-N/` was written by the human (Taegeol Kim; git author "Ryugi62 (human)").

## How the factory caught bad work in this run

| What | Found by | Fixed by |
|---|---|---|
| A non-party paying, declining or cancelling someone else's request got 404, the spec says 403 | implementer's own probe run (S1-152) | `3f766d4`; analyst tightened the probe `07b53b2` |
| Reset time grew with the number of distinct seeded passwords; a signup racing a reset could land in the wrong state | reviewer, stage 1 notes 1–2 | `d1be8d8`, then stage-2 ledger rows + probes `68d4beb` |
| Request lists missing when empty; `/login` and `/signup` not rendered for a signed-in browser | implementer, ledger gaps from failing checks' output | `50a09fa` (implemented from the spec route table and "current-user visible on every screen when signed in") |
| A literal `null` rendered in the requests and balance cards | implementer, before review | `b9dd8bd` |
| Paying a request from `/requests` was always public; hold headlines ignored the hold's status | reviewer, stage 2 notes 1–2 | `4d44098`, then stage-3 rows `f1055c3` |
| Statement snapshots kept fully materialised forever — heap exhaustion under load | reviewer, stage 3 note 1 | `88070ae` (compact, recomputed on demand), stage-4 row S4-071 + memory probe |
| A lost response on request-pay removed the Pay button, so the retry could not reuse the key | implementer | `425311d` |

Waived with reasons (run log): `minor_units` accepted 0–8 though the spec lists 0/2/3;
seeded password hashes use a lower scrypt cost (still salted scrypt).

## What we tried that failed (earlier runs of this factory)

- **Run 1 — two providers.** Codex for the analyst and reviewer, so the judge would not
  share the builder's blind spots. 21 minutes in, the analyst hit its ChatGPT plan's usage
  limit and went silent; the coordinator waited forever. → silence rule; all seats on
  Claude Code; independence now comes from the reviewer's method.
- **Run 2 — same factory, mandates v2.** All four stages claimed on the shipped checks
  (3 h 59 min, $57.61), but the post-run audit found four process faults, each now a
  mandate line:
  - the implementer opened a shipped test once to fix a failing check → *never open the
    checks' source; report a ledger gap*;
  - the reviewer accepted stage 4 on a probe it had patched in a scratch copy → *verify
    only the exact commit*;
  - one non-blocking note was never decided → *every note gets an owner and a ledger row*;
  - one 1,748-line server file, no unit tests → *modules, ≤ ~500 lines, unit tests*.
  Its export also dropped statement snapshots (S4-045) → *export rows per kind of state*.
  Run 2's room and history are in `factory/history/run-2/`.
- **Toy rehearsal** (organizers' counter track): duplicate review handoffs and review
  evidence left outside the repository → single handoff rule, reviews as commits.
- Forbidding the ask-the-human tool on headless Claude Code seats: Band refuses to start
  the runtime. Autonomy is enforced by the mandates; no seat asked.

## Code map (stage-4)

`src/domain/` pure rules: money and rounding, instants, canonical JSON, errors, split and
settlement rules · `src/state/` the in-memory store, fixture validation, export/import
(`snapshot.js`), passwords · `src/services/` one module per capability: wallet, requests,
settlements, authorizations, history (`as_of`/`known_at`), statements, corrections,
refunds, batches, idempotency · `src/transport/` HTTP plumbing, the route table, HTML/JSON
negotiation · `src/ui/` static screens (no framework, system fonts). Every write runs
synchronously on the event loop, which is the concurrency story. Unit tests: `test/`,
`node --test`. Regression suite: `factory/probes/stage-N/run_all.py <base-url>`.

## Stand it up yourself

1. Band Desktop 0.4.12+ signed in; a Docker daemon; Python 3.12 for the event harness;
   Claude Code signed in.
2. `factory/setup/create-seats.sh` — one `band agent create` per seat, instructions linked
   live to `mandates/<seat>.md`, `--claude-permission-mode bypassPermissions` so no seat
   waits for an approval.
3. `factory/setup/new-room.sh` — a room with the four seats and you.
4. Send @coordinator one message: spec file paths, result repository, folder rules, check
   command (ours is the first message in `room.json`). Send nothing else.
5. When the coordinator posts its run summary: Band console → Sessions → the room → ⋮ →
   Download → Download full session → `room.json`.

Point the same mandates at another problem by changing only that one message.
`factory/genericity/` holds the toy-track rehearsal room and the mandate diff since then.

## Limitations

- Green shipped checks are not proof; stages 3 and 4 ship 6 and 5 checks. The ledger,
  probes and reviewer scripts are our answer to the rest, and could still miss what both
  readings of the spec missed.
- No rejection in this run: every round accepted, with notes fixed as follow-up commits
  and re-verified. Review changed the code through those notes, not through REJECTs.
- Implementer and reviewer run the same model; the reviewer's independence is procedural.
- The analyst dominates spend; a ★-rows-only ledger would be cheaper and weaker.
- UI quality is judged by the reviewer and headless-browser probes, not by a designer.
