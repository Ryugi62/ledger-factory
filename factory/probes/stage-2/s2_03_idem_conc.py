"""Stage 2: idempotency of the two new write paths (authorizations, captures) and concurrency."""
import json
import random
import time
from kit import *

PATHS2 = ["authorizations", "capture"]


def scramble(o):
    if isinstance(o, dict):
        return {k: scramble(v) for k, v in reversed(list(o.items()))}
    return o


def snap(w):
    pays, auths = set(), {}
    for n in w.balances:
        pays |= {p["payment_id"] for p in w.all_activity(n)}
        for a in w.all_auths(n):
            auths[a["authorization_id"]] = (a["status"], a["captured_amount"], a["remaining_amount"])
    return {n: w.me(n)["total"] for n in w.balances}, {n: w.me(n)["held"] for n in w.balances}, len(pays), auths


class Sc2:
    def __init__(self, name):
        self.name = name
        w = self.w = World2()
        if name == "authorizations":
            self.tokA, self.pathA, self.bodyA = w.tok["ada"], "/authorizations", {"to_handle": "bob", "amount": 100}
            self.tokB, self.pathB, self.bodyB = w.tok["bob"], "/authorizations", {"to_handle": "ada", "amount": 100}
            self.diff = {"to_handle": "bob", "amount": 101}
            self.invalid = [{"to_handle": "bob", "amount": 0}, {"to_handle": "nobody", "amount": 100}, {"to_handle": "ada", "amount": 100}]
        else:
            self.aA = T(w.auth("ada", "bob", 2000))["authorization_id"]
            self.aB = T(w.auth("bob", "ada", 2000))["authorization_id"]
            self.tokA, self.pathA, self.bodyA = w.tok["bob"], "/authorizations/%s/capture" % self.aA, {"amount": 700, "final": False}
            self.tokB, self.pathB, self.bodyB = w.tok["ada"], "/authorizations/%s/capture" % self.aB, {"amount": 700, "final": False}
            self.diff = {"amount": 701, "final": False}
            self.invalid = [{"amount": 0}, {"amount": "x"}, {"amount": 5000}, {"amount": 700, "final": "maybe"}]

    def send(self, key, body=None, raw=None, who="A", tok=None):
        t = tok or (self.tokA if who == "A" else self.tokB)
        p = self.pathA if who == "A" else self.pathB
        b = self.bodyA if who == "A" else self.bodyB
        if raw is not None:
            return call("POST", p, token=t, key=key, raw=raw)
        return call("POST", p, token=t, key=key, body=b if body is None else body)

    def drain(self):
        """Change the world so the original request would now fail, using fresh keys."""
        w = self.w
        if self.name == "authorizations":
            T(w.pay("ada", "fay", w.avail("ada")))
        else:
            T(w.capture("bob", self.aA, {}))        # closes it: a replay must still return the original capture


@probe("S2-103", "S2-150", "S2-132")
def key_is_required_on_both_new_paths():
    m = Multi()
    for name in PATHS2:
        with m.case(name):
            sc = Sc2(name)
            before = snap(sc.w)
            expect(call("POST", sc.pathA, token=sc.tokA, body=sc.bodyA), 400, "missing_idempotency_key")
            expect(sc.send(""), 400, "missing_idempotency_key")
            expect(sc.send("x" * 256), 422, "validation_failed")
            assert snap(sc.w) == before
    m.done()


@probe("S2-103", "S2-164", "S2-152")
def replays_return_200_with_the_identical_body_and_no_new_effect():
    m = Multi()
    for name in PATHS2:
        with m.case(name):
            sc = Sc2(name)
            k = K()
            first = sc.first = sc.send(k)
            expect(first, 201)
            after = snap(sc.w)
            for raw in (None, json.dumps(scramble(sc.bodyA), indent=3), json.dumps(sc.bodyA, separators=(",", ":")),
                        "\n " + json.dumps(sc.bodyA) + " \n"):
                r = sc.send(k) if raw is None else sc.send(k, raw=raw)
                expect(r, 200)
                assert r.json == first.json, "replay differs:\n%r\n%r" % (first.json, r.json)
            # a different body is a conflict, even an invalid one (resolved before validation)
            expect(sc.send(k, body=sc.diff), 409, "idempotency_key_reuse")
            for bad in sc.invalid:
                expect(sc.send(k, body=bad), 409, "idempotency_key_reuse")
            assert len(sc.w.all_activity("bob")) <= 1
            expect(sc.send(k), 200)
    m.done()


@probe("S2-152", "S2-164", "S2-103")
def capture_bodies_are_compared_as_json_values():
    w = World2()
    # {} and {"amount": 2000} are different bodies even when they mean the same capture
    aid = T(w.auth("ada", "bob", 2000))["authorization_id"]
    k = K()
    T(w.capture("bob", aid, {}, key=k))
    expect(w.capture("bob", aid, {"amount": 2000}, key=k), 409, "idempotency_key_reuse")
    expect(w.capture("bob", aid, {}, key=k), 200)
    # {"amount": 700} and {"amount": 700, "final": true} are different JSON values too
    bid = T(w.auth("ada", "bob", 2000))["authorization_id"]
    k = K()
    T(w.capture("bob", bid, {"amount": 700}, key=k))
    expect(w.capture("bob", bid, {"amount": 700, "final": True}, key=k), 409, "idempotency_key_reuse")
    expect(w.capture("bob", bid, {"amount": 700, "final": False}, key=k), 409, "idempotency_key_reuse")
    expect(w.capture("bob", bid, {"amount": 700}, key=k), 200)
    # key order and whitespace do not matter
    cid = T(w.auth("ada", "bob", 2000))["authorization_id"]
    k = K()
    T(w.capture("bob", cid, {"amount": 700, "final": False}, key=k))
    r = call("POST", "/authorizations/%s/capture" % cid, token=w.tok["bob"], key=k, raw='{ "final" : false,\n "amount":700 }')
    expect(r, 200)
    assert w.auth_by_id("bob", cid)["captured_amount"] == 700


@probe("S2-103", "S2-091", "S2-092")
def key_is_scoped_to_user_and_path_on_the_new_paths():
    m = Multi()
    for name in PATHS2:
        with m.case(name):
            sc = Sc2(name)
            k = K()
            a = sc.send(k)
            expect(a, 201)
            b = sc.send(k, who="B")        # other user, same key string
            expect(b, 201)
            assert b.json != a.json
            expect(sc.send(k), 200)
            rb = sc.send(k, who="B")
            expect(rb, 200)
            assert rb.json == b.json
    m.done()
    # same key + same body on a different path is not a replay: two captures by the same receiver
    w2 = World2(balances={"ada": 5000, "bob": 0, "cy": 5000})
    a1 = T(w2.auth("ada", "bob", 1000))["authorization_id"]
    a2 = T(w2.auth("cy", "bob", 1000))["authorization_id"]
    k = K()
    p1 = w2.capture("bob", a1, {}, key=k)
    p2 = w2.capture("bob", a2, {}, key=k)
    expect(p1, 201)
    expect(p2, 201)
    assert p1.json["payment_id"] != p2.json["payment_id"] and w2.me("bob")["total"] == 2000
    # the same key on the seven different paths, same user, is seven first uses
    w3 = World2(operators=["u_ada"])
    k = K()
    body = {"to_handle": "bob", "amount": 10}
    expect(call("POST", "/payments", token=w3.tok["ada"], key=k, body=body), 201)
    expect(call("POST", "/authorizations", token=w3.tok["ada"], key=k, body=body), 201)
    expect(call("POST", "/requests", token=w3.tok["ada"], key=k, body={"payer_handle": "bob", "amount": 10}), 201)
    expect(call("POST", "/splits", token=w3.tok["ada"], key=k, body={"amount": 3, "participant_handles": ["bob"]}), 201)
    expect(call("POST", "/settlements", token=w3.tok["ada"], key=k, body={"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]}), 201)
    # a replay of the authorization is still a replay of the authorization
    expect(call("POST", "/authorizations", token=w3.tok["ada"], key=k, body=body), 200)


@probe("S2-097", "S2-103", "S2-100")
def key_reused_after_a_4xx_failure_is_a_first_use_on_the_new_paths():
    m = Multi()
    with m.case("authorization: insufficient available then funded"):
        w = World2(balances={"ada": 100, "bob": 0, "cy": 1000})
        k, body = K(), {"to_handle": "bob", "amount": 500}
        expect(call("POST", "/authorizations", token=w.tok["ada"], key=k, body=body), 409, "insufficient_funds")
        T(w.pay("cy", "ada", 1000))
        expect(call("POST", "/authorizations", token=w.tok["ada"], key=k, body=body), 201)
        expect(call("POST", "/authorizations", token=w.tok["ada"], key=k, body=body), 200)
        assert w.held("ada") == 500, "hold taken exactly once"
    with m.case("authorization: held funds do not count as available for the retry"):
        w = World2(balances={"ada": 1000, "bob": 0})
        T(w.auth("ada", "bob", 800))
        k, body = K(), {"to_handle": "bob", "amount": 500}
        expect(call("POST", "/authorizations", token=w.tok["ada"], key=k, body=body), 409, "insufficient_funds")
        T(w.void("ada", w.all_auths("ada")[0]["authorization_id"]), 200)
        expect(call("POST", "/authorizations", token=w.tok["ada"], key=k, body=body), 201)
    with m.case("authorization: validation then valid"):
        w = World2()
        k = K()
        expect(w.auth("ada", "bob", 0, key=k), 422)
        expect(w.auth("ada", "nobody", 5, key=k), 404)
        expect(w.auth("ada", "ada", 5, key=k), 422)
        expect(w.auth("ada", "bob", 5, key=k), 201)
        expect(w.auth("ada", "bob", 5, key=k), 200)
        assert w.held("ada") == 5
    with m.case("capture: exceeds then valid, same key"):
        w = World2()
        aid = T(w.auth("ada", "bob", 1000))["authorization_id"]
        k = K()
        expect(w.capture("bob", aid, {"amount": 5000}, key=k), 422, "capture_exceeds_authorization")
        expect(w.capture("bob", aid, {"amount": 0}, key=k), 422, "validation_failed")
        expect(w.capture("bob", "a_nope", {"amount": 5}, key=k), 404)
        expect(w.capture("bob", aid, {"amount": 400, "final": False}, key=k), 201)
        expect(w.capture("bob", aid, {"amount": 400, "final": False}, key=k), 200)
        assert w.auth_by_id("bob", aid)["captured_amount"] == 400
    with m.case("capture: wrong party then receiver (different users, same key string)"):
        w = World2()
        aid = T(w.auth("ada", "bob", 1000))["authorization_id"]
        k = K()
        expect(w.capture("ada", aid, {}, key=k), 403)
        expect(w.capture("bob", aid, {}, key=k), 201)
    with m.case("capture: not open then another open authorization"):
        w = World2()
        a1 = T(w.auth("ada", "bob", 1000))["authorization_id"]
        T(w.void("ada", a1), 200)
        k = K()
        expect(w.capture("bob", a1, {}, key=k), 409, "authorization_not_open")
        a2 = T(w.auth("ada", "bob", 1000))["authorization_id"]
        expect(w.capture("bob", a2, {}, key=k), 201)
    m.done()


@probe("S2-100", "S2-103", "S2-097")
def replays_return_the_original_even_after_the_world_changed():
    m = Multi()
    for name in PATHS2:
        with m.case(name):
            sc = Sc2(name)
            k = K()
            first = sc.first = sc.send(k)
            expect(first, 201)
            sc.drain()
            state = snap(sc.w)
            r = sc.send(k)
            expect(r, 200)
            assert r.json == first.json
            assert snap(sc.w) == state, "replay changed state"
    with m.case("authorization replay after void shows the original response"):
        w = World2()
        k = K()
        first = w.auth("ada", "bob", 100, key=k)
        a = T(first)
        T(w.void("ada", a["authorization_id"]), 200)
        r = w.auth("ada", "bob", 100, key=k)
        expect(r, 200)
        assert r.json == first.json and r.json["status"] == "open"
        assert w.held("ada") == 0, "replay must not take a new hold"
    with m.case("capture replay after the authorization closed is not authorization_not_open"):
        w = World2()
        aid = T(w.auth("ada", "bob", 1000))["authorization_id"]
        k = K()
        first = w.capture("bob", aid, {}, key=k)
        T(first)
        r = w.capture("bob", aid, {}, key=k)
        expect(r, 200)
        assert r.json == first.json
        assert w.me("bob")["total"] == 3500
    with m.case("capture replay after payer spent everything else"):
        w = World2(balances={"ada": 1000, "bob": 0, "cy": 0})
        aid = T(w.auth("ada", "bob", 600))["authorization_id"]
        k = K()
        first = w.capture("bob", aid, {"amount": 100, "final": False}, key=k)
        T(first)
        T(w.pay("ada", "cy", w.avail("ada")))
        expect(w.capture("bob", aid, {"amount": 100, "final": False}, key=k), 200)
        assert w.auth_by_id("ada", aid)["captured_amount"] == 100
    m.done()


@probe("S2-099", "S2-103", "S2-097", "S2-094", "S2-201")
def concurrent_identical_new_path_requests_take_effect_once():
    m = Multi()
    for name in PATHS2:
        with m.case(name):
            sc = Sc2(name)
            before = snap(sc.w)
            k = K()
            n = 12
            rs = par([(lambda: sc.send(k)) for _ in range(n)])
            codes = sorted(r.status for r in rs)
            assert codes == [200] * (n - 1) + [201], codes
            first = [r for r in rs if r.status == 201][0]
            assert all(r.json == first.json for r in rs)
            after = snap(sc.w)
            if name == "authorizations":
                assert after[1]["ada"] == 100 and after[0] == before[0], "hold taken once, no money moved"
            else:
                assert after[0]["bob"] == before[0]["bob"] + 700 and after[0]["ada"] == before[0]["ada"] - 700, "captured once"
                assert sc.w.auth_by_id("ada", sc.aA)["captured_amount"] == 700
            assert sum(after[0].values()) == sc.w.total
    m.done()


@probe("S2-103", "S2-096", "S2-201")
def concurrent_same_key_different_bodies_one_wins_on_new_paths():
    m = Multi()
    for name in PATHS2:
        with m.case(name):
            sc = Sc2(name)
            k = K()
            bodies = [sc.bodyA, sc.diff] * 6
            rs = par([(lambda b=b: sc.send(k, body=b)) for b in bodies])
            codes = [r.status for r in rs]
            assert codes.count(201) == 1, codes
            winner = bodies[codes.index(201)]
            for r, b in zip(rs, bodies):
                if r.status == 201:
                    continue
                if b == winner:
                    assert r.status == 200, r
                else:
                    expect(r, 409, "idempotency_key_reuse")
            if name == "capture":
                assert sc.w.auth_by_id("ada", sc.aA)["captured_amount"] == winner["amount"]
    m.done()


@probe("S2-095", "S2-094", "S2-201", "S2-096", "S2-066")
def overdraft_race_on_authorizations_and_payments_over_available():
    w = World2(balances={"ada": 10000, "bob": 0, "cy": 0, "dee": 0})
    targets = ["bob", "cy", "dee"]
    with InvariantPoller(w, ["ada", "bob"]) as pl:
        rs = par([(lambda i=i: w.auth("ada", targets[i % 3], 300)) for i in range(50)])
    pl.check()
    ok = [r for r in rs if r.status == 201]
    assert len(ok) == 33, "exactly 33 holds of 300 fit in 10000, got %d" % len(ok)
    for r in rs:
        if r.status != 201:
            expect(r, 409, "insufficient_funds")
    check_me(w.me("ada"), total=10000, held=9900)
    assert w.avail("ada") == 100
    # authorizations and payments compete for the same available amount
    w = World2(balances={"ada": 10000, "bob": 0, "cy": 0})
    fns = [(lambda: w.auth("ada", "bob", 600)) for _ in range(20)] + [(lambda: w.pay("ada", "cy", 600)) for _ in range(20)]
    with InvariantPoller(w, ["ada", "cy"]) as pl:
        rs = par(fns)
    pl.check()
    ok = [r for r in rs if r.status == 201]
    assert len(ok) == 16, "exactly 16 operations of 600 fit in 10000, got %d" % len(ok)
    me = w.me("ada")
    assert me["available"] == 400 and me["total"] + 0 == 10000 - 600 * len([1 for r in ok if "status" not in r.json])
    assert w.total_now() == w.total


@probe("S2-097", "S2-094", "S2-201", "S2-156")
def concurrent_captures_never_exceed_the_authorization():
    w = World2()
    aid = T(w.auth("ada", "bob", 2000))["authorization_id"]
    with InvariantPoller(w, ["ada", "bob"]) as pl:
        rs = par([(lambda: w.capture("bob", aid, {"amount": 300, "final": False})) for _ in range(10)])   # distinct keys
    pl.check()
    codes = sorted(r.status for r in rs)
    assert codes.count(201) == 6 and codes.count(422) == 4, codes
    for r in rs:
        if r.status == 422:
            expect(r, 422, "capture_exceeds_authorization")
    g = w.auth_by_id("ada", aid)
    assert g["status"] == "open" and g["captured_amount"] == 1800 and g["remaining_amount"] == 200 and len(g["payment_ids"]) == 6, g
    check_me(w.me("ada"), total=8200, held=200)
    assert w.me("bob")["total"] == 4300
    # default (final) captures racing: exactly one wins, the rest see a closed authorization
    bid = T(w.auth("ada", "cy", 1000))["authorization_id"]
    rs = par([(lambda: w.capture("cy", bid, {})) for _ in range(10)])
    codes = sorted(r.status for r in rs)
    assert codes.count(201) == 1 and codes.count(409) == 9, codes
    for r in rs:
        if r.status == 409:
            expect(r, 409, "authorization_not_open")
    assert w.me("cy")["total"] == 1000
    assert w.total_now() == w.total


@probe("S2-097", "S2-201", "S2-171")
def capture_versus_void_race_is_consistent():
    w = World2()
    for rnd in range(8):
        aid = T(w.auth("ada", "bob", 1000))["authorization_id"]
        before = (w.me("ada")["total"], w.me("bob")["total"])
        c, v = par([lambda: w.capture("bob", aid, {}), lambda: w.void("ada", aid)])
        g = w.auth_by_id("ada", aid)
        if c.status == 201:
            expect(v, 409, "authorization_not_open")
            assert g["status"] == "captured" and w.me("bob")["total"] == before[1] + 1000
        else:
            expect(c, 409, "authorization_not_open")
            expect(v, 200)
            assert g["status"] == "voided" and w.me("bob")["total"] == before[1] and w.me("ada")["total"] == before[0]
        assert w.held("ada") == 0
    assert w.total_now() == w.total


@probe("S2-096", "S2-095", "S2-201", "S2-094")
def holds_limit_concurrent_settlements_and_payments_but_not_captures():
    w = World2(balances={"ada": 1000, "bob": 0, "cy": 0, "mia": 0}, operators=["u_mia"])
    aid = T(w.auth("ada", "bob", 600))["authorization_id"]          # available 400
    with InvariantPoller(w, ["ada", "cy"]) as pl:
        rs = par([(lambda: w.settle("mia", [{"from_handle": "ada", "to_handle": "cy", "amount": 300}])) for _ in range(5)])
    pl.check()
    assert sorted(r.status for r in rs).count(201) == 1, [r.status for r in rs]
    for r in rs:
        if r.status != 201:
            expect(r, 409, "insufficient_funds")
    check_me(w.me("ada"), total=700, held=600)
    # a capture may spend the reserved money while payments are refused
    fns = [lambda: w.capture("bob", aid, {})] + [(lambda: w.pay("ada", "cy", 100)) for _ in range(3)]
    with InvariantPoller(w, ["ada", "bob"]) as pl:
        rs = par(fns)
    pl.check()
    assert rs[0].status == 201, rs[0]
    me = w.me("ada")
    assert me["available"] >= 0 and me["held"] == 0 and w.total_now() == w.total


@probe("S2-094", "S2-095", "S2-201", "S2-066", "S2-103")
def mixed_stage2_load_keeps_every_invariant_at_every_read():
    names = ["ada", "bob", "cy", "dee", "eve", "fay"]
    w = World2(balances={n: 20000 for n in names}, operators=["u_dee"])
    rnd = random.Random(11)
    made = []
    # seed some authorizations to act on
    for i in range(12):
        a, b = rnd.sample(names, 2)
        r = w.auth(a, b, rnd.randint(100, 3000))
        if r.status == 201:
            made.append((r.json["authorization_id"], a, b))
    fns = []
    for i in range(150):
        kind = rnd.choice(["auth", "pay", "capture", "capture", "partial", "void", "settle", "read", "list"])
        a, b = rnd.sample(names, 2)
        amt = rnd.randint(1, 2500)
        if kind == "auth":
            fns.append(lambda a=a, b=b, amt=amt: w.auth(a, b, amt))
        elif kind == "pay":
            fns.append(lambda a=a, b=b, amt=amt: w.pay(a, b, amt))
        elif kind in ("capture", "partial") and made:
            aid, p, r_ = rnd.choice(made)
            body = {"amount": amt, "final": False} if kind == "partial" else {}
            fns.append(lambda aid=aid, r_=r_, body=body: w.capture(r_, aid, body))
        elif kind == "void" and made:
            aid, p, r_ = rnd.choice(made)
            fns.append(lambda aid=aid, p=p: w.void(p, aid))
        elif kind == "settle":
            fns.append(lambda a=a, b=b, amt=amt: w.settle("dee", [{"from_handle": a, "to_handle": b, "amount": amt}]))
        elif kind == "read":
            fns.append(lambda a=a: w.get(a, "/me"))
        else:
            fns.append(lambda a=a: w.auths(a, limit=20))
    results = []
    with InvariantPoller(w, ["ada", "bob", "cy"]) as pl:
        for i in range(0, len(fns), 50):
            results += par(fns[i:i + 50])
    pl.check()
    assert all(r.status < 500 for r in results)
    for n in names:
        check_me(w.me(n))
        assert w.me(n)["total"] >= 0
    assert w.total_now() == w.total, "money created or destroyed"
    # every open authorisation is fully covered by its payer's held amount
    held = {n: 0 for n in names}
    for n in names:
        for a in w.all_auths(n):
            if a["status"] == "open" and a["from_handle"] == n:
                held[n] += a["remaining_amount"]
    for n in names:
        assert w.held(n) == held[n], "held %s: me says %d, open authorizations say %d" % (n, w.held(n), held[n])
