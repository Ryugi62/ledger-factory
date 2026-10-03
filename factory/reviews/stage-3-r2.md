# Stage 3 — review round 2

- Commit checked: `88070ae781bba8153539138f315f8f72de822952`. The tracked stage folders were clean. The working tree
  held only the analyst's uncommitted `factory/probes/stage-4/` edits, outside the stage folders.
- Change since r1 (425311d), confined to `stage-3/`:
  - Snapshots are stored compactly as `{ userId, fromUs, toUs, knownUs, cut }`, where `cut` is a global revision
    sequence. They are recomputed on demand, and a 16-entry cache of materialized results serves paging.
  - The Node heap is raised to `--max-old-space-size=1536`.
  - One unit-test assertion was added: a snapshot is frozen against a later correction.
- **Verdict: ACCEPT**

## Checks (all on 88070ae)

| Command | Result |
|---|---|
| `docker build -t rv-s3-r2 stage-3`; run with `--cpus 2 --memory 2g` | build OK; `/health` 200 |
| `docker run --rm --network none --cpus 2 --memory 2g rv-s3-r2 node --test` | 21 / 21 pass |
| Probes from a Linux container on a Docker network: `run_all.py http://r3a:8080 --peer http://r3b:9302 --stage1-url http://r1u:8080 --stage2-url http://r2u:8080` | 132 passed, 0 failed, 2 skipped (browser probes) |
| Browser probes from the host: `stage-3/run_all.py … --no-prior --with-ui -k ui` | 2 / 2 pass |
| Browser probes from the host: `stage-2/run_all.py … --no-stage1 -k ui` | 19 / 19 pass, three runs in a row |
| `.venv/bin/python -m harness run … --stage 3 --mode isolated --out …/checks/r3-s3-reviewer-2` | stage 1: 147 / 147, stage 2: 35 / 35, stage 3: 6 / 6, "claimed stage: 3" (stage 4 fails as expected) |
| r1 memory scenario (`--memory 2g`): reset with 3000 seeded payments for one user, then 2000 × `GET /statement?limit=10` at 50 in flight | no crash; container memory 70 MiB afterwards (r1: heap out of memory around 1 GB); p50 36 ms, p99 46 ms, max 61 ms; export 0.03 s |
| Snapshot freeze: snapshot taken, then a new payment, a zero-amount correction of an entry in it, an authorization create + void, and 40 other statements to evict the cache; every page re-read | identical pages: balances, entries, `revision`, `effective_at`, `has_more`. A fresh statement shows the zero-amount revision with delta 0. After reset, the old token gives 404 |

The first host UI runs showed 1 and 2 failures. The implementer reported that their probe run had hit my container's
port at the same moment, resetting its state. On a container nobody else was using, three consecutive runs passed
19 / 19 and 2 / 2.

## Reading

The recomputation is correct because revisions are append-only and each one gets a global `rseq` when appended,
payments and their first revisions included. A cut-off therefore excludes both later payments and later corrections.
Payment parties, notes and visibility never change. The window and `known_at` are stored with the snapshot.
Import rebuilds `rseq` and replaces state, which drops snapshots, as before. The snapshot map now holds small fixed-size
records.

## Earlier stages

`git diff d1be8d8 88070ae -- stage-1` and `git diff 4d44098 88070ae -- stage-2` are both empty.

## Non-blocking notes

None.
