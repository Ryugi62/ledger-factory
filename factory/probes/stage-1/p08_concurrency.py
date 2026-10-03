"""Concurrency: invariants under bursts of writes (ledger §1 invariants, §5 no 5xx, §7)."""
import random
import threading
from lib import *


class Poller:
    """Poll /me for some users in the background; record every balance seen."""

    def __init__(self, w, users):
        self.w, self.users, self.seen, self.stop = w, users, [], False
        self.threads = [threading.Thread(target=self.run, args=(u,)) for u in users]

    def run(self, u):
        while not self.stop:
            r = call("GET", "/me", token=self.w.tok[u])
            if r.status == 200 and isinstance(r.json, dict):
                self.seen.append((u, r.json["balance"]))

    def __enter__(self):
        for t in self.threads:
            t.start()
        return self

    def __exit__(self, *a):
        self.stop = True
        for t in self.threads:
            t.join()

    def assert_never_negative(self):
        assert self.seen, "poller observed nothing"
        neg = [s for s in self.seen if s[1] < 0]
        assert not neg, "negative balance observed: %r" % neg[:5]


@probe("S1-006", "S1-005", "S1-014", "S1-066", "S1-112")
def overdraft_race_never_goes_negative():
    w = World(balances={"ada": 10000, "bob": 0, "cy": 0, "dee": 0})
    targets = ["bob", "cy", "dee"]
    with Poller(w, ["ada", "bob"]) as pl:
        rs = par([(lambda i=i: w.pay("ada", targets[i % 3], 300)) for i in range(50)])
    pl.assert_never_negative()
    ok = [r for r in rs if r.status == 201]
    bad = [r for r in rs if r.status != 201]
    assert len(ok) == 33, "expected exactly 33 payments of 300 to fit in 10000, got %d" % len(ok)
    for r in bad:
        expect(r, 409, "insufficient_funds")
    assert w.bal("ada") == 100
    assert w.sum_now() == w.total
    assert sum(w.bal(t) for t in targets) == 33 * 300
    # failed payments left no trace
    all_ids = set()
    for n in w.balances:
        all_ids |= set(w.activity_ids(n))
    assert len(all_ids) == 33


@probe("S1-006", "S1-005", "S1-066")
def spending_the_whole_balance_many_times_succeeds_once():
    w = World(balances={"ada": 1000, "bob": 0, "cy": 0, "dee": 0, "eve": 0})
    names = ["bob", "cy", "dee", "eve"]
    with Poller(w, ["ada", "bob", "cy"]) as pl:
        rs = par([(lambda i=i: w.pay("ada", names[i % 4], 1000)) for i in range(40)])
    pl.assert_never_negative()
    assert sorted(r.status for r in rs).count(201) == 1
    assert w.bal("ada") == 0 and w.sum_now() == 1000


@probe("S1-005", "S1-006", "S1-066", "S1-014")
def opposing_transfers_do_not_deadlock_or_lose_money():
    w = World(balances={"ada": 5000, "bob": 5000, "cy": 0})
    fns = []
    for i in range(25):
        fns.append(lambda: w.pay("ada", "bob", 100))
        fns.append(lambda: w.pay("bob", "ada", 100))
    with Poller(w, ["ada", "bob"]) as pl:
        rs = par(fns)
    pl.assert_never_negative()
    assert all(r.status == 201 for r in rs), [r for r in rs if r.status != 201][:3]
    assert w.bal("ada") == 5000 and w.bal("bob") == 5000


@probe("S1-007", "S1-129")
def a_request_moves_money_at_most_once():
    w = World()
    for rnd in range(3):
        rid = T(w.req("bob", "ada", 1000))["request_id"]
        before = (w.bal("ada"), w.bal("bob"))
        rs = par([(lambda: w.payreq("ada", rid)) for _ in range(12)])    # distinct keys
        codes = sorted(r.status for r in rs)
        assert codes.count(201) == 1 and codes.count(409) == 11, codes
        for r in rs:
            if r.status == 409:
                expect(r, 409, "request_not_pending")
        assert (w.bal("ada"), w.bal("bob")) == (before[0] - 1000, before[1] + 1000)
        assert w.request_by_id("ada", rid)["status"] == "paid"
    assert w.sum_now() == w.total


@probe("S1-007", "S1-036")
def pay_versus_cancel_and_decline_race_is_consistent():
    w = World()
    for rnd in range(8):
        rid = T(w.req("bob", "ada", 100))["request_id"]
        before = (w.bal("ada"), w.bal("bob"))
        pay_r, other_r = par([lambda: w.payreq("ada", rid),
                              (lambda: w.cancel("bob", rid)) if rnd % 2 == 0 else (lambda: w.decline("ada", rid))])
        final = w.request_by_id("ada", rid)["status"]
        if pay_r.status == 201:
            expect(other_r, 409, "request_not_pending")
            assert final == "paid" and w.bal("ada") == before[0] - 100 and w.bal("bob") == before[1] + 100
        else:
            expect(pay_r, 409, "request_not_pending")
            expect(other_r, 200)
            assert final in ("cancelled", "declined")
            assert (w.bal("ada"), w.bal("bob")) == before
    # decline vs cancel: exactly one of them wins
    for rnd in range(6):
        rid = T(w.req("bob", "ada", 100))["request_id"]
        a, b = par([lambda: w.decline("ada", rid), lambda: w.cancel("bob", rid)])
        assert sorted([a.status, b.status]) == [200, 409], (a, b)
        final = w.request_by_id("ada", rid)["status"]
        assert final == ("declined" if a.status == 200 else "cancelled")
    assert w.sum_now() == w.total


@probe("S1-005", "S1-006", "S1-066", "S1-014", "S1-015")
def mixed_load_at_50_in_flight_keeps_invariants():
    names = ["ada", "bob", "cy", "dee", "eve", "fay"]
    w = World(balances={"ada": 20000, "bob": 20000, "cy": 20000, "dee": 20000, "eve": 20000, "fay": 20000})
    rnd = random.Random(7)
    fns = []
    for i in range(150):
        a, b = rnd.sample(names, 2)
        kind = rnd.choice(["pay", "pay", "pay", "req", "split", "read", "feed", "reqs"])
        amt = rnd.randint(1, 3000)
        if kind == "pay":
            fns.append(lambda a=a, b=b, amt=amt: w.pay(a, b, amt, visibility=rnd.choice(["public", "private"])))
        elif kind == "req":
            fns.append(lambda a=a, b=b, amt=amt: w.req(a, b, amt))
        elif kind == "split":
            fns.append(lambda a=a, b=b, amt=amt: w.split(a, amt, [a, b, "cy" if "cy" not in (a, b) else "dee"]))
        elif kind == "read":
            fns.append(lambda a=a: w.get(a, "/me"))
        elif kind == "feed":
            fns.append(lambda a=a: w.activity(a, limit=20))
        else:
            fns.append(lambda a=a: w.requests(a, limit=20))
    results = []
    # 3 waves of 50 simultaneous requests
    with Poller(w, ["ada", "bob"]) as pl:
        for i in range(0, 150, 50):
            results += par(fns[i:i + 50])
    pl.assert_never_negative()
    assert all(r.status < 500 for r in results)
    assert w.sum_now() == w.total
    assert all(b >= 0 for b in w.balances_now().values())
    # pay every pending request addressed to cy: still conserves
    for q in w.all_requests("cy"):
        if q["payer_handle"] == "cy" and q["status"] == "pending" and q["amount"] > 0:
            r = w.payreq("cy", q["request_id"])
            assert r.status in (201, 409), r
    assert w.sum_now() == w.total


@probe("S1-072", "S1-033", "S1-066", "S1-014")
def concurrent_signups_with_the_same_email_or_handle():
    World()
    rs = par([(lambda: call("POST", "/auth/signup", body={"email": "dup@example.com", "password": "longenough1", "display_name": "D"}))
              for _ in range(10)])
    codes = sorted(r.status for r in rs)
    assert codes == [201] + [409] * 9, codes
    for r in rs:
        if r.status == 409:
            expect(r, 409, "email_taken")
    # different emails that derive the same handle: exactly one account
    emails = ["Race@a.example", "race@b.example", "RACE@c.example", "race@d.example", "race@e.example", "race@f.example"]
    rs = par([(lambda e=e: call("POST", "/auth/signup", body={"email": e, "password": "longenough1", "display_name": "R"}))
              for e in emails])
    codes = sorted(r.status for r in rs)
    assert codes == [201] + [409] * 5, codes
    for r in rs:
        if r.status == 409:
            expect(r, 409, "handle_taken")
    winner = [e for e, r in zip(emails, rs) if r.status == 201][0]
    expect(call("POST", "/auth/login", body={"email": winner, "password": "longenough1"}), 200)
    for e, r in zip(emails, rs):
        if r.status != 201:
            expect(call("POST", "/auth/login", body={"email": e, "password": "longenough1"}), 401)


@probe("S1-014", "S1-015", "S1-066", "S1-019")
def fifty_requests_in_flight_all_answered_in_time():
    w = World()
    rs = par([(lambda: call("GET", "/health")) for _ in range(25)] + [(lambda: w.get("ada", "/me")) for _ in range(25)])
    assert all(r.status == 200 for r in rs), [r for r in rs if r.status != 200][:3]
    assert max(r.elapsed for r in rs) < 5.0
    rs = par([(lambda i=i: w.pay("ada", "bob", 1, key="burst-%d" % i)) for i in range(50)])
    assert all(r.status == 201 for r in rs)
    assert w.bal("ada") == 9950 and w.bal("bob") == 2550
