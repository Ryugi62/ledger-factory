"""GET /_test/export and POST /_test/import (ledger §10)."""
import json
from lib import *

NOTE = "café \U0001F355 <b>&</b>  "


def build():
    """A service holding every kind of state."""
    pays = [{"id": "p_seed", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "seeded", "visibility": "private"}]
    reqs = [{"id": "rq_seed", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"},
            {"id": "rq_seed_dec", "requester_id": "u_cy", "payer_id": "u_dee", "amount": 5, "note": "", "status": "declined"}]
    w = World(operators=["u_dee"], payments=pays, requests=reqs)
    st = {}
    sg = T(call("POST", "/auth/signup", body={"email": "sam@example.com", "password": "longenough1", "display_name": "Sam"}), 201)
    w.tok["sam"], w.balances["sam"] = sg["token"], 0
    st["ada2"] = login("ada@example.com")
    st["k"] = {}

    def keyed(name, fn):
        k = K()
        r = fn(k)
        st["k"][name] = (k, r)
        return r

    keyed("pay1", lambda k: w.pay("ada", "bob", 1500, key=k, note=NOTE, visibility="public"))
    keyed("pay2", lambda k: w.pay("bob", "sam", 100, key=k, visibility="private"))
    keyed("req1", lambda k: w.req("sam", "ada", 321, key=k, note="from sam"))
    rq = T(w.req("bob", "cy", 40))
    keyed("paycy", lambda k: w.payreq("ada", w.request_by_id("ada", "rq_seed")["request_id"], {"visibility": "private"}, key=k))
    rq3 = T(w.req("cy", "dee", 70))
    T(w.cancel("cy", rq3["request_id"]), 200)
    rq4 = T(w.req("cy", "dee", 71))
    T(w.decline("dee", rq4["request_id"]), 200)
    keyed("split", lambda k: w.split("ada", 1000, ["ada", "bob", "sam"], key=k, note="split"))
    keyed("settle", lambda k: w.settle("dee", [{"from_handle": "ada", "to_handle": "bob", "amount": 100, "note": "s1"},
                                               {"from_handle": "bob", "to_handle": "cy", "amount": 50, "visibility": "private"}], key=k))
    # a key that failed with 4xx (cy cannot afford it yet)
    kf = K()
    expect(w.pay("fay", "ada", 500, key=kf), 409, "insufficient_funds")
    st["failed_key"] = kf
    st["pending_req"] = rq["request_id"]
    st["w"] = w
    return st


def observe(w):
    obs = {}
    for n in list(w.balances):
        # same-second order is unspecified, so compare as sets keyed by id
        obs[n] = (w.me(n), sorted(w.all_activity(n), key=lambda p: p["payment_id"]),
                  sorted(w.all_requests(n), key=lambda q: q["request_id"]))
    return obs


@probe("S1-170", "S1-171", "S1-177")
def export_envelope_is_unauthenticated_and_read_only():
    w = World()
    T(w.pay("ada", "bob", 10))
    before = observe(w)
    r = call("GET", "/_test/export")
    j = T(r, 200)
    assert j["track"] == "pocketful" and j["format_version"] == 1 and isinstance(j["state"], dict), list(j)
    assert observe(w) == before, "export changed the observable state"
    # later writes never alter an export already taken
    snap1 = json.dumps(j, sort_keys=True)
    T(w.pay("ada", "bob", 20))
    assert json.dumps(j, sort_keys=True) == snap1
    # the first export restores the earlier state: ada paid 10, not 30
    expect(call("POST", "/_test/import", body=j), 204)
    assert w.bal("ada") == 9990 and w.bal("bob") == 2510


def round_trip(target):
    """Export from the source (BASE_URL); dirty and replace the target; import; verify everything.
    target None means: the same instance, after a reset to an unrelated fresh fixture."""
    import lib
    src_base = lib.BASE
    st = build()
    w = st["w"]
    before = observe(w)
    total = w.sum_now()
    exp = T(call("GET", "/_test/export"), 200)
    assert observe(w) == before
    # state that must be erased by import (created after the export)
    late = T(call("POST", "/auth/signup", body={"email": "late@example.com", "password": "longenough1", "display_name": "L"}), 201)
    T(w.pay("ada", "bob", 777))
    late_key = K()
    expect(w.pay("ada", "cy", 5, key=late_key), 201)
    if target:
        expect(call("POST", "/_test/reset", body=fixture({"other": 5}), base=target), 204)
    else:
        reset(fixture({"kim": 700, "lee": 300}))   # a fresh fixture is not a restore
    expect(call("POST", "/_test/import", body=exp, base=target), 204)
    if target:
        lib.BASE = target       # from here on every call (same tokens!) goes to the other process
    try:
        after = observe(w)
        for n in after:
            assert after[n] == before[n], "%s differs after import:\n before %r\n after  %r" % (n, before[n], after[n])
        assert w.sum_now() == total, "balances replayed against an already-net state"
        for em, pw in (("ada@example.com", PASSWORD), ("sam@example.com", "longenough1"), ("cy@example.com", PASSWORD)):
            expect(call("POST", "/auth/login", body={"email": em, "password": pw}), 200)
        expect(call("POST", "/auth/login", body={"email": "ada@example.com", "password": "nope nope"}), 401)
        assert T(call("GET", "/me", token=st["ada2"]), 200)["user_id"] == "u_ada"
        assert T(call("GET", "/me", token=w.tok["sam"]), 200)["handle"] == "sam"
        expect(call("POST", "/auth/login", body={"email": "late@example.com", "password": "longenough1"}), 401)
        expect(call("GET", "/me", token=late["token"]), 401)
        sent = {"pay1": ("/payments", "ada", {"to_handle": "bob", "amount": 1500, "note": NOTE, "visibility": "public"}),
                "pay2": ("/payments", "bob", {"to_handle": "sam", "amount": 100, "visibility": "private"}),
                "req1": ("/requests", "sam", {"payer_handle": "ada", "amount": 321, "note": "from sam"}),
                "paycy": ("/requests/rq_seed/pay", "ada", {"visibility": "private"}),
                "split": ("/splits", "ada", {"amount": 1000, "participant_handles": ["ada", "bob", "sam"], "note": "split"}),
                "settle": ("/settlements", "dee", {"transfers": [
                    {"from_handle": "ada", "to_handle": "bob", "amount": 100, "note": "s1"},
                    {"from_handle": "bob", "to_handle": "cy", "amount": 50, "visibility": "private"}]})}
        for name, (k, orig) in st["k"].items():
            path, who, body = sent[name]
            rr = call("POST", path, token=w.tok[who], key=k, body=body)
            expect(rr, 200)
            assert rr.json == orig.json, "%s replay differs after import" % name
            if name != "paycy":
                other = json.loads(json.dumps(body))
                if "amount" in other:
                    other["amount"] += 1
                else:
                    other["transfers"][0]["amount"] += 1
                expect(call("POST", path, token=w.tok[who], key=k, body=other), 409, "idempotency_key_reuse")
            else:
                expect(call("POST", path, token=w.tok[who], key=k, body={}), 409, "idempotency_key_reuse")
        assert observe(w) == before, "replays after import moved money or created records"
        # a key first used after the export is unknown again
        expect(w.pay("ada", "cy", 5, key=late_key), 201)
        # failed keys remain reusable: fund the payer, retry the very same key and body
        T(w.pay("dee", "fay", 600))
        expect(w.pay("fay", "ada", 500, key=st["failed_key"]), 201)
        # permissions preserved
        expect(w.settle("dee", [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]), 201)
        expect(w.settle("ada", [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]), 403, "forbidden")
        # new identities never collide with imported ones
        known = set()
        for n in w.balances:
            known |= {p["payment_id"] for p in w.all_activity(n)}
            known |= {q["request_id"] for q in w.all_requests(n)}
        p = T(w.pay("ada", "bob", 1))
        q = T(w.req("ada", "bob", 1))
        assert p["payment_id"] not in known and q["request_id"] not in known, "id reused after import"
        assert w.request_by_id("ada", "rq_seed")["status"] == "paid"
        expect(w.payreq("ada", "rq_seed"), 409, "request_not_pending")
        T(w.payreq("cy", st["pending_req"]), 201)       # the still-pending request is still payable, once
        expect(w.payreq("cy", st["pending_req"]), 409, "request_not_pending")
    finally:
        lib.BASE = src_base


@probe("S1-172", "S1-174", "S1-178", "S1-179", "S1-180", "S1-181", "S1-182", "S1-183", "S1-184", "S1-185", "S1-186",
       "S1-187", "S1-188", "S1-190", "S1-191", "S1-192", "S1-079")
def full_round_trip_preserves_every_kind_of_state():
    round_trip(None)


@probe("S1-173", "S1-172")
def export_imports_into_a_different_instance():
    if not PEER:
        return "skip"   # needs --peer URL of a second, independent container
    round_trip(PEER)


@probe("S1-174", "S1-189", "S1-188", "S1-186")
def import_is_replacement_repeatable_and_reset_clears_it():
    st = build()
    w = st["w"]
    before = observe(w)
    exp = T(call("GET", "/_test/export"), 200)
    for _ in range(3):
        expect(call("POST", "/_test/import", body=exp), 204)
        assert observe(w) == before, "repeated import must restore, not accumulate"
    # import over a different fixture removes it entirely
    reset(fixture({"kim": 1}))
    expect(call("POST", "/_test/import", body=exp), 204)
    expect(call("POST", "/auth/login", body={"email": "kim@example.com", "password": PASSWORD}), 401)
    assert observe(w) == before
    # reset clears all state, including imported state
    reset(fixture({"kim": 1000, "lee": 0}))
    for n in ("ada", "sam"):
        expect(call("GET", "/me", token=w.tok[n]), 401)
    expect(call("POST", "/auth/login", body={"email": "sam@example.com", "password": "longenough1"}), 401)
    t = login("kim@example.com")
    assert T(call("GET", "/activity", token=t), 200)["payments"] == []
    assert T(call("GET", "/me", token=t), 200)["balance"] == 1000


@probe("S1-175")
def invalid_imports_are_rejected_and_change_nothing():
    w = World()
    T(w.pay("ada", "bob", 100))
    before = observe(w)
    good = T(call("GET", "/_test/export"), 200)
    m = Multi()
    bads = [
        ("wrong track", dict(good, track="other")),
        ("no track", {k: v for k, v in good.items() if k != "track"}),
        ("wrong version", dict(good, format_version=2)),
        ("version 0", dict(good, format_version=0)),
        ("no version", {k: v for k, v in good.items() if k != "format_version"}),
        ("no state", {k: v for k, v in good.items() if k != "state"}),
        ("state null", dict(good, state=None)),
        ("state string", dict(good, state="nope")),
        ("state number", dict(good, state=7)),
        ("state list", dict(good, state=[1, 2])),
        ("empty object", {}),
    ]
    for name, body in bads:
        with m.case(name):
            expect(call("POST", "/_test/import", body=body), 422, "validation_failed")
            assert observe(w) == before, "rejected import changed the state"
    for name, raw in (("not json", "{nope"), ("truncated", json.dumps(good)[:40])):
        with m.case(name):
            expect(call("POST", "/_test/import", raw=raw), 400, "malformed_request")
            assert observe(w) == before
    with m.case("state with garbage content"):
        r = call("POST", "/_test/import", body=dict(good, state={"nonsense": True, "users": "x"}))
        assert r.status in (422,), "an invalid state must be 422, not 204/5xx: %r" % r
        assert observe(w) == before
    m.done()
    # unknown extra fields beside a valid envelope are ignored
    expect(call("POST", "/_test/import", body=dict(good, extra="x")), 204)
    assert observe(w) == before


@probe("S1-176", "S1-015")
def reset_export_and_import_of_a_larger_state_fit_in_10_seconds():
    n = 50
    names = ["u%02d" % i for i in range(n)]
    fx = fixture({x: 1_000_000 for x in names})
    fx["payments"] = [{"id": "sp%d" % i, "from_user_id": "u_" + names[i % n], "to_user_id": "u_" + names[(i + 1) % n],
                       "amount": 1 + i % 50, "note": "n%d" % i, "visibility": "public" if i % 3 else "private"} for i in range(3000)]
    fx["requests"] = [{"id": "sr%d" % i, "requester_id": "u_" + names[i % n], "payer_id": "u_" + names[(i + 7) % n],
                       "amount": 1 + i, "note": "", "status": ["pending", "paid", "declined", "cancelled"][i % 4]} for i in range(600)]
    t0 = time.time()
    r = call("POST", "/_test/reset", body=fx)
    expect(r, 204)
    assert r.elapsed < 10, "reset took %.1fs" % r.elapsed
    e = call("GET", "/_test/export")
    expect(e, 200)
    assert e.elapsed < 10, "export took %.1fs" % e.elapsed
    i = call("POST", "/_test/import", raw=e.raw)
    expect(i, 204)
    assert i.elapsed < 10, "import took %.1fs" % i.elapsed
    t = login("u00@example.com")
    assert T(call("GET", "/me", token=t), 200)["balance"] == 1_000_000
