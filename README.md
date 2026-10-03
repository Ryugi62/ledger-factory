# Ledger Factory — Dark Factory hackathon, `pocketful` track

**Team:** Ledger Factory (solo — Taegeol Kim, GitHub [@Ryugi62](https://github.com/Ryugi62))
**Track:** `pocketful` — a wallet and payments app
**Factory:** four Band Desktop seats — coordinator, analyst, implementer, reviewer — that
turn each specification into a numbered requirement ledger *before* any code is written,
and accept only a commit that shows evidence for it.

## Result at a glance

| Folder | Isolated-mode harness (shipped checks) | Unit tests | Review rounds | Accepted |
|---|---|---|---|---|
| `stage-1/` | suite 1 147/147 · claims stage 1 | 12 | 1 + fix confirmation | `d1be8d8` |
| `stage-2/` | suites 1–2 147/147 · 35/35 · claims stage 2 | 17 | 1 + fix confirmation | `4d44098` |
| `stage-3/` | suites 1–3 + 6/6 · claims stage 3 | 21 | 1 + fix confirmation | `88070ae` |
| `stage-4/` | suites 1–4 + 5/5 · claims stage 4 | 24 | 1 | `b39bad5` |

`harness run --all --mode isolated` on a fresh clone: every folder claims its own stage.
One human message started the run (`room.json`, its only human message); 2 h 39 min later
the coordinator posted the run summary. Model spend $60.32 (Band's list-price estimate; $0
cash — existing subscriptions). The room log shows no tool call that opened a shipped test
file. Ledger: 559 rows, 344 ★, 0 known gaps. Stages 3 and 4 of pocketful specify API
behaviour only; the stage-2 screens carry forward.

## How to read this repository

| Path | What it is |
|---|---|
| `FACTORY.md` | The factory: seats, design choices and their cost, measured time and spend, how it catches bad work, what failed in earlier runs, how to stand it up |
| `mandates/` | One standing instruction per seat, each naming its harness and model. Generic — no track vocabulary |
| `room.json` | The Band room of the submitted run, downloaded unchanged (Download full session) |
| `stage-N/` | The service as accepted at stage N: `src/` modules, `test/` unit tests, Dockerfile, RUN.md |
| `factory/ledger/stage-N.md` | The analyst's requirement ledger (★ = what a minimal build skips) |
| `factory/probes/stage-N/` | Black-box and browser probes written from the spec only |
| `factory/reviews/` | The reviewer's blind lists and every verdict, committed by the reviewer |
| `factory/run-log.md` | The coordinator's per-stage reports, including every note's decision |
| `factory/history/run-2/` | The previous full run of this factory and the mandate diff it led to |
| `factory/genericity/` | The rehearsal on the organizers' unrelated toy track |
| `factory/setup/` | The two scripts that create the seats and the room |

## Run a stage

```sh
cd stage-4 && docker build -t pocketful-s4 . && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-s4
# unit tests, offline:  docker run --rm --network none pocketful-s4 node --test
# browser: open http://localhost:8080/signup (new accounts start at 0), or seed users with
# POST /_test/reset (stage-1 spec fixture) and open /login
```

Every commit under `stage-N/` was made by a seat in the room (git authors `analyst`,
`implementer`, `reviewer`, `coordinator`). The human — Taegeol Kim, git author
"Ryugi62 (human)" — committed the mandates and license before the run, and this README,
`FACTORY.md`, `room.json` and `factory/history|genericity|setup` after it.

License: MIT.
