"""Stage 3: concurrency of corrections, snapshots under writes, per-read invariants."""
import json
import random
import threading
import time
from kit3 import *


@probe("S3-109", "S3-058", "S3-062", "S3-067", "S3-066")
def concurrent_corrections_with_the_same_expected_revision_cannot_both_succeed():
    w = std_history()
    t = w.h.pays["p_001"].revs[0][2]
    for rnd in range(3):
        before_rev = len(parjson(w.revisions("ada", "p_001"), 200)["revisions"])
        amounts = [301 + rnd * 20 + i for i in range(12)]
        rs = par([(lambda a=a: w.fix("ada", "p_001", before_rev, a, iso(t))) for a in amounts])      # distinct keys
        codes = sorted(r.status for r in rs)
        assert codes.count(201) == 1 and codes.count(409) == 11, codes
        for r in rs:
            if r.status == 409:
                expect(r, 409, "stale_revision")
        win = [r for r in rs if r.status == 201][0].json
        w.h.add_rev("p_001", win["revision"], win["amount"], P(win["effective_at"]), P(win["recorded_at"]))
        rv = parjson(w.revisions("ada", "p_001"), 200)["revisions"]
        assert len(rv) == before_rev + 1 and rv[-1]["amount"] == win["amount"]
        assert w.me("ada")["balance"] == w.h.balance("ada") and w.me("bob")["balance"] == w.h.balance("bob"), "exactly one correction moved money"
    # the same key, concurrently: one 201, the rest replays with the same body
    k = K()
    rev = len(parjson(w.revisions("ada", "p_001"), 200)["revisions"])
    body = {"expected_revision": rev, "amount": 500, "effective_at": iso(t), "reason": "same key"}
    rs = par([(lambda: call("POST", "/payments/p_001/corrections", token=w.tok["ada"], key=k, body=body)) for _ in range(12)])
    assert sorted(r.status for r in rs) == [200] * 11 + [201], [r.status for r in rs]
    first = [r for r in rs if r.status == 201][0].json
    assert all(r.json == first for r in rs)
    w.h.add_rev("p_001", first["revision"], first["amount"], P(first["effective_at"]), P(first["recorded_at"]))
    assert len(parjson(w.revisions("ada", "p_001"), 200)["revisions"]) == rev + 1
    assert w.me("ada")["balance"] == w.h.balance("ada")
    # same key, different bodies: one wins, the others conflict or replay
    k = K()
    bodies = [dict(body, expected_revision=rev + 1, amount=600), dict(body, expected_revision=rev + 1, amount=700)] * 4
    rs = par([(lambda b=b: call("POST", "/payments/p_001/corrections", token=w.tok["ada"], key=k, body=b)) for b in bodies])
    codes = [r.status for r in rs]
    assert codes.count(201) == 1, codes
    winner = bodies[codes.index(201)]
    for r, b in zip(rs, bodies):
        if r.status != 201:
            assert (r.status == 200 and b == winner) or (r.status == 409 and r.code == "idempotency_key_reuse" and b != winner), r


@probe("S3-063", "S3-062", "S3-006", "S3-066")
def a_correction_and_a_payment_compete_for_the_same_funds():
    t = now_dt().replace(microsecond=0)
    fx, h = hist_fixture({"ada": 150, "bob": 0, "cy": 0}, [("p_1", "ada", "bob", 50, t - timedelta(hours=2))])
    for rnd in range(4):
        w = World3(fx, h)
        assert w.me("ada")["balance"] == 100
        r_fix, r_pay = par([lambda: w.fix("ada", "p_1", 1, 150, iso(t - timedelta(hours=2))), lambda: w.pay("ada", "cy", 100)])
        assert sorted([r_fix.status, r_pay.status]) == [201, 409], (r_fix, r_pay)
        loser = r_fix if r_fix.status == 409 else r_pay
        expect(loser, 409, "insufficient_funds")
        assert w.me("ada")["balance"] == 0
        h = Hist(h.opening)
        h.add("p_1", "ada", "bob", 50, t - timedelta(hours=2))


@probe("S3-108", "S3-102", "S3-036", "S3-035", "S3-106", "S3-150")
def snapshots_and_reads_stay_consistent_while_writers_run():
    w = std_history()
    t = lambda pid: w.h.pays[pid].revs[0][2]
    stop = threading.Event()
    errors = []

    def pay_loop(frm, to):
        while not stop.is_set():
            r = w.pay(frm, to, 1)
            if r.status not in (201, 409):
                errors.append(r)

    def fix_loop():
        n = 0
        while not stop.is_set():
            rv = call("GET", "/payments/p_001/revisions", token=w.tok["ada"])
            if rv.status != 200:
                errors.append(rv)
                continue
            cur = len(rv.json["revisions"])
            r = w.fix("ada", "p_001", cur, 300 + (n % 7), iso(t("p_001") + timedelta(minutes=n % 5)))
            n += 1
            if r.status not in (201, 409):
                errors.append(r)

    th = [threading.Thread(target=pay_loop, args=("ada", "bob")), threading.Thread(target=pay_loop, args=("bob", "cy")),
          threading.Thread(target=pay_loop, args=("cy", "ada")), threading.Thread(target=fix_loop)]
    for x in th:
        x.start()
    snaps = []
    try:
        t_end = time.time() + 3.0
        while time.time() < t_end:
            for who in ("ada", "bob"):
                j = parjson(w.stmt(who, limit=3), 200)
                snaps.append((who, j["snapshot"], frozen_copy(w, who, j["snapshot"])))
            check_statement_shape(consistent_read(w, "ada"))      # a plain read under load is internally consistent
    finally:
        stop.set()
        for x in th:
            x.join()
    assert not errors, errors[:2]
    assert snaps
    for who, tok, before in snaps:
        after = frozen_copy(w, who, tok)
        assert after == before, "a snapshot changed while writers ran"
        assert before["opening"] + sum(e[1] for e in before["entries"]) == before["closing"], "snapshot not internally consistent"
    total = sum(w.h.opening.values())
    assert sum(w.me(n)["balance"] for n in w.balances) == total
    for n in w.balances:
        assert w.me(n)["balance"] >= 0


def consistent_read(w, who):
    first = parjson(w.stmt(who, limit=200), 200)
    if not first["has_more"]:
        return first
    entries, off = [], 0
    while True:                                       # more than one page: walk the snapshot of the very same read
        j = parjson(w.stmt(who, snapshot=first["snapshot"], limit=200, offset=off), 200)
        entries += j["entries"]
        if not j["has_more"]:
            return {"opening_balance": j["opening_balance"], "closing_balance": j["closing_balance"], "entries": entries}
        off += 200


def frozen_copy(w, who, tok):
    entries, off = [], 0
    while True:
        j = parjson(w.stmt(who, snapshot=tok, limit=4, offset=off), 200)
        entries += entries_view(j["entries"])
        if not j["has_more"]:
            return {"opening": j["opening_balance"], "closing": j["closing_balance"], "entries": entries}
        off += 4


@probe("S3-066", "S3-067", "S3-064", "S3-006", "S3-005", "S3-150")
def mixed_corrections_payments_and_reads_keep_every_invariant():
    w = std_history()
    rnd = random.Random(5)
    t = lambda pid: w.h.pays[pid].revs[0][2]
    pids = ["p_001", "p_002", "p_003", "p_004", "p_005"]
    fns = []
    for i in range(120):
        kind = rnd.choice(["pay", "fix", "fix", "stmt", "me", "rev"])
        pid = rnd.choice(pids)
        sender = w.h.pays[pid].frm
        if kind == "pay":
            a, b = rnd.sample(["ada", "bob", "cy", "dee"], 2)
            fns.append(lambda a=a, b=b: w.pay(a, b, rnd.randint(1, 30)))
        elif kind == "fix":
            fns.append(lambda pid=pid, sender=sender: w.fix(sender, pid, 1 + rnd.randint(0, 2), rnd.randint(0, 400),
                                                           iso(t(pid) + timedelta(minutes=rnd.randint(-300, 0)))))
        elif kind == "stmt":
            fns.append(lambda: w.stmt(rnd.choice(["ada", "bob", "cy", "dee"]), limit=200))
        elif kind == "me":
            fns.append(lambda: w.me3(rnd.choice(["ada", "bob", "cy", "dee"]), as_of=iso(now_dt() - timedelta(minutes=rnd.randint(0, 900)))))
        else:
            fns.append(lambda pid=pid, sender=sender: w.revisions(sender, pid))
    results = []
    for i in range(0, len(fns), 40):
        results += par(fns[i:i + 40])
    assert all(r.status < 500 for r in results)
    for r in results:
        if r.status == 409:
            assert r.code in ("stale_revision", "insufficient_funds", "historical_overdraft"), r
    total = sum(w.h.opening.values())
    now_bal = {n: w.me(n)["balance"] for n in w.balances}
    assert sum(now_bal.values()) == total and all(b >= 0 for b in now_bal.values()), now_bal
    # every user's statement is self-consistent, ends at the current balance, and no historical balance went negative
    for n in ("ada", "bob", "cy", "dee"):
        j = stmt_full(w, n)
        check_statement_shape(j)
        assert j["closing_balance"] == now_bal[n]
        # the history of a user is nonnegative at every boundary (combined per instant)
        run, by_t = j["opening_balance"], {}
        for e in j["entries"]:
            by_t[P(e["effective_at"])] = by_t.get(P(e["effective_at"]), 0) + e["delta"]
        for k in sorted(by_t):
            run += by_t[k]
            assert run >= 0, "%s negative at %s after the concurrent corrections" % (n, k)
    for a in (now_dt() - timedelta(hours=5), now_dt() - timedelta(hours=1), now_dt() + timedelta(days=1)):
        assert sum_over_users(w, a) == total
