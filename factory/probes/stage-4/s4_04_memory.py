"""Stage-3 review note carried into stage 4: memory must stay bounded under repeated statement reads (snapshots)."""
import os
import threading
import time
from kit4 import *

N_PAY = int(os.environ.get("PF_MEM_PAYMENTS", "3000"))      # a wallet with ~3000 payments
N_CALLS = int(os.environ.get("PF_MEM_CALLS", "2000"))       # 2000 statement reads ...
IN_FLIGHT = 50                                              # ... at 50 in flight


@probe("S4-071", "S4-065", "S4-014", "S4-066")
def two_thousand_statement_reads_at_50_in_flight_keep_the_service_alive_and_snapshots_valid():
    t = now_dt().replace(microsecond=0)
    pays = []
    for i in range(N_PAY):
        frm, to = ("ada", "bob") if i % 3 else ("bob", "ada")
        pays.append(("m%05d" % i, frm, to, 1 + i % 5, t - timedelta(minutes=2 * (N_PAY - i))))
    w = build4({"ada": 1000000, "bob": 1000000, "cy": 0, "dee": 0, "eve": 0, "fay": 0}, pays)
    bal0 = {n: w.me(n)["balance"] for n in ("ada", "bob")}
    # a snapshot taken before the flood, with its first pages
    first = parjson(w.stmt("ada", limit=10), 200)
    tok0 = first["snapshot"]
    pages0 = {off: parjson(w.stmt("ada", snapshot=tok0, limit=10, offset=off), 200) for off in (0, 10, 1500, 2990)}
    full0 = stmt_full(w, "ada")
    assert len(full0["entries"]) == sum(1 for p in pays if "ada" in (p[1], p[2]))

    done, lock = [0], threading.Lock()
    problems, tokens = [], []
    t_start = time.time()

    def worker(k):
        who = "ada" if k % 2 == 0 else "bob"
        while True:
            with lock:
                if done[0] >= N_CALLS:
                    return
                i = done[0]
                done[0] += 1
            r = w.stmt(who, limit=10, offset=(i * 7) % 200)
            if r.status != 200:
                problems.append(r)
            elif i % 97 == 0 and len(tokens) < 12:
                tokens.append((who, r.json["snapshot"], r.json["opening_balance"], r.json["closing_balance"]))

    ths = [threading.Thread(target=worker, args=(k,)) for k in range(IN_FLIGHT)]
    for x in ths:
        x.start()
    for x in ths:
        x.join(timeout=max(1, 120 - (time.time() - t_start)))
    elapsed = time.time() - t_start
    assert not any(x.is_alive() for x in ths), "the %d statement reads did not finish within 120 s" % N_CALLS
    assert not problems, "statement reads failed under load (service crashed or refused?): %r" % problems[:3]
    assert elapsed < 90, "%d statement reads took %.1f s; the probe expects the service to keep up (< ~60 s)" % (N_CALLS, elapsed)
    # the service is alive and has lost nothing
    expect(call("GET", "/health"), 200)
    assert {n: w.me(n)["balance"] for n in ("ada", "bob")} == bal0, "balances changed during read-only load"
    full1 = stmt_full(w, "ada")
    assert entries_view(full1["entries"]) == entries_view(full0["entries"]), "state lost or changed under read load"
    # the snapshot taken before the flood is still valid and frozen, page by page
    for off, pg in pages0.items():
        again = parjson(w.stmt("ada", snapshot=tok0, limit=10, offset=off), 200)
        assert entries_view(again["entries"]) == entries_view(pg["entries"]) and again["closing_balance"] == pg["closing_balance"], \
            "snapshot taken before the flood changed or vanished at offset %d" % off
    # snapshots taken during the flood are valid: consistent pages, same content as a fresh read
    assert tokens, "no snapshot tokens were collected"
    for who, tok, opening, closing in tokens:
        entries, off = [], 0
        while True:
            j = parjson(w.stmt(who, snapshot=tok, limit=200, offset=off), 200)
            entries += j["entries"]
            assert j["opening_balance"] == opening and j["closing_balance"] == closing
            if not j["has_more"]:
                break
            off += 200
        check_statement_shape({"opening_balance": opening, "closing_balance": closing, "entries": entries})
        if who == "ada":
            assert entries_view(entries) == entries_view(full0["entries"])
    # writes still work and old snapshots stay frozen afterwards
    w.p("ada", "bob", 1)
    again = parjson(w.stmt("ada", snapshot=tok0, limit=10, offset=0), 200)
    assert entries_view(again["entries"]) == entries_view(pages0[0]["entries"])
