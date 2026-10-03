"""Idempotency on the five write paths (ledger §7, plus §8/§11 per-path rules)."""
import json
from lib import *

PATHS = ["payments", "requests", "pay", "splits", "settlements"]
DELTA = {"payments": (1, 0), "requests": (0, 1), "pay": (1, 0), "splits": (0, 2), "settlements": (1, 0)}


def scramble(o):
    if isinstance(o, dict):
        return {k: scramble(v) for k, v in reversed(list(o.items()))}
    if isinstance(o, list):
        return [scramble(x) for x in o]
    return o


def reformat(body):
    if not body:
        return "{ \n\t}"
    return json.dumps(scramble(body), indent=3, ensure_ascii=False)


def snap(w):
    pays, reqs = set(), set()
    for n in w.balances:
        pays |= {p["payment_id"] for p in w.all_activity(n)}
        reqs |= {q["request_id"] for q in w.all_requests(n)}
    return w.balances_now(), len(pays), len(reqs)


class Sc:
    """One idempotent write path, fully set up. Two actors (A, B) are different users."""

    def __init__(self, name):
        self.name = name
        w = self.w = World(operators=["u_dee", "u_eve"])
        if name == "payments":
            self.tokA, self.pathA, self.bodyA = w.tok["ada"], "/payments", {"to_handle": "bob", "amount": 100}
            self.tokB, self.pathB, self.bodyB = w.tok["bob"], "/payments", {"to_handle": "bob2", "amount": 100}
            self.bodyB = {"to_handle": "ada", "amount": 100}
            self.diff = {"to_handle": "bob", "amount": 101}
            self.invalid = [{"to_handle": "bob", "amount": 0}, {"to_handle": "nobody", "amount": 100},
                            {"to_handle": "ada", "amount": 100}, {"to_handle": "bob", "amount": 100, "visibility": "x"}]
        elif name == "requests":
            self.tokA, self.pathA, self.bodyA = w.tok["bob"], "/requests", {"payer_handle": "ada", "amount": 100}
            self.tokB, self.pathB, self.bodyB = w.tok["ada"], "/requests", {"payer_handle": "bob", "amount": 100}
            self.diff = {"payer_handle": "ada", "amount": 101}
            self.invalid = [{"payer_handle": "ada", "amount": 0}, {"payer_handle": "nobody", "amount": 100},
                            {"payer_handle": "bob", "amount": 100}]
        elif name == "pay":
            self.rq1 = T(w.req("bob", "ada", 100))["request_id"]
            self.rqB = T(w.req("ada", "bob", 100))["request_id"]
            self.tokA, self.pathA, self.bodyA = w.tok["ada"], "/requests/%s/pay" % self.rq1, {}
            self.tokB, self.pathB, self.bodyB = w.tok["bob"], "/requests/%s/pay" % self.rqB, {}
            self.diff = {"visibility": "private"}
            self.invalid = [{"visibility": "bogus"}, {"visibility": 3}]
        elif name == "splits":
            self.tokA, self.pathA = w.tok["ada"], "/splits"
            self.bodyA = {"amount": 300, "participant_handles": ["ada", "bob", "cy"]}
            self.tokB, self.pathB, self.bodyB = w.tok["bob"], "/splits", dict(self.bodyA)
            self.diff = {"amount": 301, "participant_handles": ["ada", "bob", "cy"]}
            self.invalid = [{"amount": 0, "participant_handles": ["bob"]}, {"amount": 300, "participant_handles": ["nobody"]},
                            {"amount": 300, "participant_handles": []}]
        else:
            tr = [{"from_handle": "ada", "to_handle": "bob", "amount": 100}]
            self.tokA, self.pathA, self.bodyA = w.tok["dee"], "/settlements", {"transfers": tr}
            self.tokB, self.pathB, self.bodyB = w.tok["eve"], "/settlements", {"transfers": [dict(tr[0])]}
            self.diff = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 101}]}
            self.invalid = [{"transfers": []}, {"transfers": [{"from_handle": "ada", "to_handle": "nobody", "amount": 1}]},
                            {"transfers": [{"from_handle": "ada", "to_handle": "ada", "amount": 1}]}]

    def send(self, key, body=None, raw=None, tok=None, path=None, who="A"):
        t = tok or (self.tokA if who == "A" else self.tokB)
        p = path or (self.pathA if who == "A" else self.pathB)
        b = self.bodyA if who == "A" else self.bodyB
        if raw is not None:
            return call("POST", p, token=t, key=key, raw=raw)
        return call("POST", p, token=t, key=key, body=b if body is None else body)

    def drain(self):
        """Make the original request no longer affordable / valid, with fresh keys."""
        w = self.w
        if self.name in ("payments", "splits", "settlements"):
            T(w.pay("ada", "fay", w.bal("ada")))
        elif self.name == "requests":
            rid = self.first.json["request_id"]
            T(w.cancel("bob", rid), 200)


@probe("S1-090", "S1-093", "S1-052", "S1-216")
def key_is_required_on_all_five_paths():
    m = Multi()
    for name in PATHS:
        with m.case(name):
            sc = Sc(name)
            before = snap(sc.w)
            expect(call("POST", sc.pathA, token=sc.tokA, body=sc.bodyA), 400, "missing_idempotency_key")
            expect(sc.send(""), 400, "missing_idempotency_key")
            expect(call("POST", sc.pathA, token=sc.tokA, key="", body=sc.bodyA), 400, "missing_idempotency_key")
            assert snap(sc.w) == before, "request without key had an effect"
    m.done()


@probe("S1-094", "S1-095", "S1-098", "S1-100", "S1-216", "S1-090")
def first_use_201_then_replays_are_200_with_identical_body():
    m = Multi()
    for name in PATHS:
        with m.case(name):
            sc = Sc(name)
            before = snap(sc.w)
            k = K()
            first = sc.first = sc.send(k)
            expect(first, 201)
            after = snap(sc.w)
            dp, dr = DELTA[name]
            assert (after[1] - before[1], after[2] - before[2]) == (dp, dr), (before, after)
            for body_raw in (None, reformat(sc.bodyA), json.dumps(sc.bodyA, separators=(",", ":")), "  " + json.dumps(sc.bodyA) + "\n"):
                r = sc.send(k) if body_raw is None else sc.send(k, raw=body_raw)
                expect(r, 200)
                assert r.json == first.json, "replay body differs:\n%r\n%r" % (first.json, r.json)
            assert snap(sc.w) == after, "replay changed state"
    m.done()


@probe("S1-096", "S1-101", "S1-216", "S1-056")
def same_key_different_body_is_409_before_any_validation():
    m = Multi()
    for name in PATHS:
        with m.case(name):
            sc = Sc(name)
            k = K()
            expect(sc.send(k), 201)
            state = snap(sc.w)
            expect(sc.send(k, body=sc.diff), 409, "idempotency_key_reuse")
            for bad in sc.invalid:
                r = sc.send(k, body=bad)
                expect(r, 409, "idempotency_key_reuse")
            assert snap(sc.w) == state
            # the original body is still a replay
            expect(sc.send(k), 200)
    m.done()


@probe("S1-102", "S1-101")
def claimed_key_edge_cases_unparseable_body_and_missing_token():
    m = Multi()
    for name in PATHS:
        with m.case(name):
            sc = Sc(name)
            k = K()
            expect(sc.send(k), 201)
            expect(sc.send(k, raw="{not json"), 400, "malformed_request")
            r = call("POST", sc.pathA, key=k, body=sc.bodyA)
            expect(r, 401, "unauthenticated")
            r = call("POST", sc.pathA, auth="Bearer bogus", key=k, body=sc.bodyA)
            expect(r, 401, "unauthenticated")
    m.done()


@probe("S1-091", "S1-092", "S1-216")
def key_is_scoped_to_the_user_and_to_the_path():
    m = Multi()
    for name in PATHS:
        with m.case(name):
            sc = Sc(name)
            k = K()
            a = sc.send(k)
            expect(a, 201)
            b = sc.send(k, who="B")      # other user, same key string (other path for `pay`)
            expect(b, 201)
            assert b.json != a.json
            expect(sc.send(k), 200)
            rb = sc.send(k, who="B")
            expect(rb, 200)
            assert rb.json == b.json
    m.done()
    # same key + same body on a different path is not a replay (two requests, same payer, same {} body)
    w = World()
    r1 = T(w.req("bob", "ada", 100))["request_id"]
    r2 = T(w.req("cy", "ada", 100))["request_id"]
    k = K()
    p1 = call("POST", "/requests/%s/pay" % r1, token=w.tok["ada"], key=k, body={})
    p2 = call("POST", "/requests/%s/pay" % r2, token=w.tok["ada"], key=k, body={})
    expect(p1, 201)
    expect(p2, 201)
    assert p1.json["payment_id"] != p2.json["payment_id"]
    assert w.bal("ada") == 9800
    # same key, a body valid for two different endpoints
    both = {"to_handle": "bob", "payer_handle": "bob", "amount": 10}
    k = K()
    a = call("POST", "/payments", token=w.tok["ada"], key=k, body=both)
    b = call("POST", "/requests", token=w.tok["ada"], key=k, body=both)
    expect(a, 201)
    expect(b, 201)
    assert "payment_id" in a.json and "request_id" in b.json and "payment_id" in b.json
    # key reuse across payments and splits with different bodies: different paths -> first uses
    k = K()
    expect(call("POST", "/payments", token=w.tok["ada"], key=k, body={"to_handle": "bob", "amount": 1}), 201)
    expect(call("POST", "/splits", token=w.tok["ada"], key=k, body={"amount": 3, "participant_handles": ["bob"]}), 201)


@probe("S1-097", "S1-037", "S1-216")
def key_reused_after_a_4xx_failure_is_a_first_use():
    m = Multi()
    # payments: insufficient funds, then money arrives, same key + same body
    with m.case("payments insufficient"):
        w = World(balances={"ada": 100, "bob": 0, "cy": 1000})
        k = K()
        body = {"to_handle": "bob", "amount": 500}
        expect(call("POST", "/payments", token=w.tok["ada"], key=k, body=body), 409, "insufficient_funds")
        T(w.pay("cy", "ada", 1000))
        r = call("POST", "/payments", token=w.tok["ada"], key=k, body=body)
        expect(r, 201)
        expect(call("POST", "/payments", token=w.tok["ada"], key=k, body=body), 200)
        assert w.bal("bob") == 500, "money moved exactly once"
    with m.case("payments validation then a different body"):
        w = World()
        for bad, st in (({"to_handle": "bob", "amount": 0}, 422), ({"to_handle": "nobody", "amount": 5}, 404),
                        ({"to_handle": "ada", "amount": 5}, 422)):
            k = K()
            expect(call("POST", "/payments", token=w.tok["ada"], key=k, body=bad), st)
            expect(call("POST", "/payments", token=w.tok["ada"], key=k, body={"to_handle": "bob", "amount": 7}), 201)
        assert w.bal("bob") == 2500 + 21
    with m.case("requests"):
        w = World()
        k = K()
        expect(call("POST", "/requests", token=w.tok["bob"], key=k, body={"payer_handle": "ada", "amount": 0}), 422)
        expect(call("POST", "/requests", token=w.tok["bob"], key=k, body={"payer_handle": "nobody", "amount": 5}), 404)
        r = call("POST", "/requests", token=w.tok["bob"], key=k, body={"payer_handle": "ada", "amount": 5})
        expect(r, 201)
        expect(call("POST", "/requests", token=w.tok["bob"], key=k, body={"payer_handle": "ada", "amount": 5}), 200)
        assert len(w.all_requests("ada")) == 1
    with m.case("pay: insufficient then funded"):
        w = World(balances={"ada": 100, "bob": 0, "cy": 1000})
        rid = T(w.req("bob", "ada", 500))["request_id"]
        k = K()
        expect(w.payreq("ada", rid, key=k), 409, "insufficient_funds")
        T(w.pay("cy", "ada", 1000))
        expect(w.payreq("ada", rid, key=k), 201)
        expect(w.payreq("ada", rid, key=k), 200)
        assert w.bal("bob") == 500 and w.bal("ada") == 600
    with m.case("pay: forbidden then permitted"):
        w = World()
        rid = T(w.req("bob", "ada", 100))["request_id"]
        k = K()
        expect(w.payreq("bob", rid, key=k), 403)
        expect(w.payreq("ada", rid, key=k), 201)
    with m.case("pay: unknown then real"):
        w = World()
        rid = T(w.req("bob", "ada", 100))["request_id"]
        k = K()
        expect(w.payreq("ada", "rq_nope", key=k), 404)
        expect(w.payreq("ada", rid, key=k), 201)
    with m.case("splits"):
        w = World()
        k = K()
        expect(w.split("ada", 0, ["bob"], key=k), 422)
        expect(w.split("ada", 30, ["bob", "nobody"], key=k), 404)
        expect(w.split("ada", 30, ["bob", "cy"], key=k), 201)
        expect(w.split("ada", 30, ["bob", "cy"], key=k), 200)
        assert len(w.all_requests("bob")) == 1
    with m.case("settlements"):
        w = World(balances={"ada": 100, "bob": 0, "cy": 1000, "dee": 0}, operators=["u_dee"])
        tr = [{"from_handle": "ada", "to_handle": "bob", "amount": 500}]
        k = K()
        expect(w.settle("dee", [], key=k), 422)
        expect(w.settle("dee", tr, key=k), 409, "insufficient_funds")
        T(w.pay("cy", "ada", 1000))
        expect(w.settle("dee", tr, key=k), 201)
        expect(w.settle("dee", tr, key=k), 200)
        assert w.bal("bob") == 500
    m.done()


@probe("S1-099", "S1-100", "S1-007", "S1-216", "S1-005")
def concurrent_identical_requests_take_effect_once():
    m = Multi()
    for name in PATHS:
        with m.case(name):
            sc = Sc(name)
            before = snap(sc.w)
            k = K()
            n = 12
            rs = par([(lambda: sc.send(k)) for _ in range(n)])
            codes = sorted(r.status for r in rs)
            assert codes == [200] * (n - 1) + [201], "statuses %r" % codes
            first = [r for r in rs if r.status == 201][0]
            for r in rs:
                assert r.json == first.json, "replay body differs from original"
            after = snap(sc.w)
            dp, dr = DELTA[name]
            assert (after[1] - before[1], after[2] - before[2]) == (dp, dr), "effect repeated: %r -> %r" % (before, after)
            assert sum(after[0].values()) == sc.w.total
    m.done()


@probe("S1-096", "S1-099", "S1-103", "S1-216")
def concurrent_same_key_different_bodies_one_wins():
    m = Multi()
    for name in PATHS:
        with m.case(name):
            sc = Sc(name)
            before = snap(sc.w)
            k = K()
            bodies = [sc.bodyA, sc.diff] * 6
            rs = par([(lambda b=b: sc.send(k, body=b)) for b in bodies])
            codes = sorted(r.status for r in rs)
            # exactly one first use; same-body duplicates replay; other body conflicts
            assert codes.count(201) == 1, codes
            winner = bodies[[r.status for r in rs].index(201)]
            for r, b in zip(rs, bodies):
                if r.status == 201:
                    continue
                if b == winner:
                    assert r.status == 200, r
                else:
                    expect(r, 409, "idempotency_key_reuse")
            after = snap(sc.w)
            dp, dr = DELTA[name]
            assert (after[1] - before[1], after[2] - before[2]) == (dp, dr)
    m.done()


@probe("S1-100", "S1-132", "S1-133", "S1-216")
def replay_returns_original_even_after_the_world_changed():
    m = Multi()
    for name in ("payments", "requests", "splits", "settlements"):
        with m.case(name):
            sc = Sc(name)
            k = K()
            first = sc.first = sc.send(k)
            expect(first, 201)
            sc.drain()
            state = snap(sc.w)
            r = sc.send(k)
            expect(r, 200)
            assert r.json == first.json
            assert snap(sc.w) == state
    with m.case("pay replay when request already paid"):
        sc = Sc("pay")
        k = K()
        first = sc.send(k)
        expect(first, 201)
        # the request is now paid; a replay must not be request_not_pending
        before = snap(sc.w)
        r = sc.send(k)
        expect(r, 200)
        assert r.json == first.json
        assert snap(sc.w) == before
        # a fresh key against the paid request is request_not_pending
        expect(sc.send(K()), 409, "request_not_pending")
    with m.case("pay replay: {} vs explicit public are different bodies"):
        sc = Sc("pay")
        k = K()
        expect(sc.send(k, body={}), 201)
        expect(sc.send(k, body={"visibility": "public"}), 409, "idempotency_key_reuse")
        expect(sc.send(k, body={}), 200)
    with m.case("pay replay after cancelled elsewhere cannot happen; replay after payer is broke"):
        sc = Sc("pay")
        k = K()
        first = sc.send(k)
        expect(first, 201)
        T(sc.w.pay("ada", "fay", sc.w.bal("ada")))
        expect(sc.send(k), 200)
    m.done()
