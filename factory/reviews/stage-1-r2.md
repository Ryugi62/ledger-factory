# Stage 1 — review round 2

- Commit checked: `d1be8d8d16d4b784cca179be44abb5b9fccaf3da` (branch main; tracked tree clean; the only untracked
  path was `factory/probes/stage-2/`, the analyst's stage-2 work, outside `stage-1/`)
- Change since r1 (3f766d4): `stage-1/` only. Seeded fixture passwords are hashed with scrypt N=1024, while
  signups keep N=16384. Reset and import now replace the state one at a time in arrival order. A signup is bound
  to the state that was live when it arrived. Four new unit tests.
- **Verdict: ACCEPT**

## Checks (all on d1be8d8)

| Command | Result |
|---|---|
| `docker build -t rv-pocketful-s1-r2 stage-1`; run `--cpus 2 --memory 2g -e PORT=9101 -p 19101:9101`, and again without PORT on 8080 | build OK; `/health` 200 on both within ~1 s |
| `docker run --rm --network none --cpus 2 --memory 2g rv-pocketful-s1-r2 node --test` | 12 / 12 pass |
| `python3 factory/probes/stage-1/run_all.py http://127.0.0.1:19101 --peer http://127.0.0.1:19102` (probes at HEAD, including 07b53b2) | 69 passed, 0 failed, 0 skipped; `check_ledger.py` agree |
| `.venv/bin/python -m harness run … --stage 1 --mode isolated --out …/checks/r3-s1-reviewer-2` | stage 1: 147 / 147 pass, "claimed stage: 1" (stage 2: fails as expected) |
| Reviewer reset timing (users with distinct passwords) | 100 → 0.15 s, 300 → 0.22 s, 1000 → 0.75 s (r1: 12.9 s at 1000) |
| Reviewer race: 8 signups in flight, then reset, ×20 | 160 signups returned 201 before the reset; 0 leaked into the new state; the fresh fixture user logs in |
| Reviewer race: slow 300-user reset, then a 1-user reset sent 20 ms later, ×15 | 0 order violations (the later reset always wins) |
| Reviewer edge script from r1 | identical behaviour, all as specified |

## Reading

The diff is small and confined to the two notes. Seeded hashes stay salted scrypt, and their parameters are stored
inside each hash, so verification and export/import handle both kinds. A failed reset or import (422) rejects
inside the queue and leaves the state unchanged. The queue recovers after a failure. Unparseable JSON is still a
400, raised before anything is queued. No earlier stages exist.

## Non-blocking notes

1. Seeded users' hashes use a lower scrypt cost (N=1024) than signups (N=16384). This is still a salted
   password-hashing function as §6 requires; recorded for transparency only.
