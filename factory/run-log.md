# Run log

## Stage 1 — payments and settlements — ACCEPTED

- Start / end (UTC): 2026-10-03 10:10 / 10:49
- Review rounds: 1 (r1 accept at 3f766d4; r2 accept of the follow-up fix commit d1be8d8)
- Rejections: none
- Ledger: 192 rows (factory/ledger/stage-1.md, analyst bc54358; S1-152 tightened in 07b53b2). 94 ★ rows. All rows have a probe except 14 rows with a manual component (Docker build, RUN.md, PORT default, no-network, resources, provenance, cross-instance import). Known gaps: 0
- Reviewer's final check: unit tests 12/12; analyst probes 69 passed / 0 failed / 0 skipped (with --peer); shipped checks, isolated mode: stage 1 147/147 (the next-stage line fails as expected); clean build and run under 2 vCPU / 2 GiB; reset with 1000 distinct passwords 0.75 s; signup-vs-reset and reset-vs-reset race tests clean
- Review notes and decisions: (1) reset time grows with distinct seeded passwords — fixed in d1be8d8; (2) signup/reset/import race — fixed in d1be8d8; (3) minor_units accepted 0..8 — waived, harmless (spec lists 0/2/3); (4) seeded hashes use scrypt N=1024 — waived, still salted scrypt (§6), recorded for transparency. Notes 1-3 forwarded to the analyst as stage-2 ledger rows
- Accepted commit: d1be8d8d16d4b784cca179be44abb5b9fccaf3da
