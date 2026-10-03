# Stage 2 — review round 2

- Commit checked: `4d44098c61189db50126c0151276aca3524da292` (branch main; tracked tree clean; the only untracked
  path was `factory/probes/stage-3/`, the analyst's work)
- Change since r1 (b9dd8bd), confined to `stage-2/src/ui/assets/` (requests.js, authorizations.js, app.css):
  - The Pay action on `/requests` gains a public/private choice (`request-visibility-{id}`). The pay retry keeps
    the same key and body after an uncertain outcome, and an unchanged body is not resent after success.
  - Hold headlines now follow direction and status.
- **Verdict: ACCEPT**

## Checks (all on 4d44098)

| Command | Result |
|---|---|
| `docker build -t rv-s2-r2 stage-2`; run with `--cpus 2 --memory 2g`, `-e PORT=9201` and default 8080 | build OK; `/health` 200 on both |
| `docker run --rm --network none --cpus 2 --memory 2g rv-s2-r2 node --test` | 17 / 17 pass |
| `python3 factory/probes/stage-2/run_all.py http://127.0.0.1:19211 --peer http://127.0.0.1:19212 --stage1-url http://127.0.0.1:19213 --shots /tmp/rv-s2-shots2` | 122 passed, 0 failed, 0 skipped; `check_ledger.py` agree |
| `.venv/bin/python -m harness run … --stage 2 --mode isolated --out …/checks/r3-s2-reviewer-2` | stage 1: 147 / 147, stage 2: 35 / 35, "claimed stage: 2" (stage 3 fails as expected) |
| Reviewer API script from r1 (holds, captures, races, expiry) | identical results, all as specified |
| Reviewer Playwright check at 375 px: pay seeded request `rq_9` with "private" chosen on `/requests` | the request becomes `paid`, the Pay button disappears, no horizontal scroll; the receiver's feed shows the payment with `visibility: "private"` |

## Visual check

`mobile_requests` (375 px) shows the labelled Visibility select above Pay / Decline, on brand and within the card.
`desktop_authorizations` headlines read "Your hold for @bob expired", "You released your hold for @bob",
"You collected a hold from @bob" and "You're holding money for @bob", matching each status pill. Both r1 notes are
resolved.

## Earlier stages

`git diff d1be8d8 4d44098 -- stage-1` is empty.

## Non-blocking notes

None.
