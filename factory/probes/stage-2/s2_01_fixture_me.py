"""Stage 2: fixture (authorizations, ttl), GET /me, expiry by the clock, unchanged stage-1 flows."""
import time
from kit import *


@probe("S2-098", "S2-130", "S2-131", "S2-117", "S2-114", "S2-027")
def me_has_total_available_held_and_agrees_without_holds():
    for cur, mu in (("EUR", 2), ("JPY", 0), ("BHD", 3)):
        w = World2(balances={"ada": 5000, "bob": 0}, currency=cur, minor_units=mu)   # fixture omits `authorizations`
        me = w.me("ada")
        assert me == {"user_id": "u_ada", "display_name": "Ada", "handle": "ada", "balance": 5000, "total": 5000,
                      "available": 5000, "held": 0, "currency": cur, "minor_units": mu}, me
        assert w.auths("ada").json == {"authorizations": [], "has_more": False}, "omitted authorizations = empty list"
    # an explicit empty list is the same
    w = World2(authorizations=[])
    check_me(w.me("ada"), total=10000, held=0)


@probe("S2-114", "S2-116", "S2-118", "S2-113", "S2-120", "S2-131", "S2-178", "S2-176")
def seeded_open_holds_reduce_available_and_other_statuses_hold_nothing():
    auths = [seed_auth("a_1", "ada", "bob", 2000, "open", expires_in=7200, note="deposit", visibility="public"),
             seed_auth("a_2", "ada", "bob", 500, "captured", expires_in=7200),
             seed_auth("a_3", "ada", "bob", 600, "voided", expires_in=7200),
             seed_auth("a_4", "ada", "bob", 700, "expired", expires_in=-7200),
             seed_auth("a_5", "ada", "cy", 800, "open", expires_in=-7200),       # open but past its deadline: expired
             seed_auth("a_6", "dee", "ada", 900, "open", expires_in=9000)]
    w = World2(authorizations=auths)
    check_me(w.me("ada"), total=10000, held=2000)
    assert w.me("ada")["available"] == 8000 and w.me("ada")["balance"] == 10000
    check_me(w.me("dee"), total=5000, held=900)
    for n in ("bob", "cy", "eve"):
        check_me(w.me(n), total=w.balances[n], held=0)
    assert w.total_now() == w.total
    by = {a["authorization_id"]: a for a in w.all_auths("ada")}
    assert set(by) == {"a_1", "a_2", "a_3", "a_4", "a_5", "a_6"}, set(by)
    check_auth(by["a_1"], "ada", "bob", 2000, "open", note="deposit")
    assert parse_ts(by["a_1"]["expires_at"]) == parse_ts(auths[0]["expires_at"]), "seeded expires_at must be kept"
    for aid, st in (("a_2", "captured"), ("a_3", "voided"), ("a_4", "expired"), ("a_5", "expired"), ("a_6", "open")):
        assert by[aid]["status"] == st, (aid, by[aid])
    for aid in ("a_2", "a_3", "a_4", "a_5"):
        assert by[aid]["remaining_amount"] == 0, by[aid]
    # status filter: expired by the clock matches `expired`, never `open`
    op = {a["authorization_id"] for a in parjson(w.auths("ada", status="open"), 200)["authorizations"]}
    ex = {a["authorization_id"] for a in parjson(w.auths("ada", status="expired"), 200)["authorizations"]}
    assert op == {"a_1", "a_6"} and ex == {"a_4", "a_5"}, (op, ex)
    # the hold really limits spending: exactly `available` can be spent
    expect(w.pay("ada", "cy", 8001), 409, "insufficient_funds")
    T(w.pay("ada", "cy", 8000))
    check_me(w.me("ada"), total=2000, held=2000)
    assert w.me("ada")["available"] == 0
    # a seeded open hold can be captured and one can be voided; closed/expired ones cannot
    T(w.capture("bob", "a_1", {"amount": 2000}))
    expect(w.capture("bob", "a_2"), 409, "authorization_not_open")
    expect(w.void("ada", "a_2"), 409, "authorization_not_open")        # captured
    assert T(w.void("ada", "a_3"), 200)["status"] == "voided"           # voiding a voided one is 200
    assert w.total_now() == w.total


@probe("S2-115", "S2-114", "S2-116", "S2-046")
def reset_rejects_holds_larger_than_the_balance():
    w = World2()
    T(w.pay("ada", "bob", 100))
    before = (w.me("ada"), w.me("bob"))
    two = [seed_auth("a_1", "ada", "bob", 600), seed_auth("a_2", "ada", "cy", 500)]
    fx = fixture2({"ada": 1000, "bob": 0, "cy": 0}, authorizations=two)
    expect(call("POST", "/_test/reset", body=fx), 422, "validation_failed")
    assert (w.me("ada"), w.me("bob")) == before, "failed reset must change nothing"
    fx = fixture2({"ada": 1000, "bob": 0}, authorizations=[seed_auth("a_1", "ada", "bob", 1001)])
    expect(call("POST", "/_test/reset", body=fx), 422, "validation_failed")
    # exactly the balance is fine: available 0
    fx = fixture2({"ada": 1000, "bob": 0, "cy": 0}, authorizations=[seed_auth("a_1", "ada", "bob", 600), seed_auth("a_2", "ada", "cy", 400)])
    reset(fx)
    t = login("ada@example.com")
    check_me(T(call("GET", "/me", token=t), 200), total=1000, held=1000)
    # closed or expired holds do not count towards the limit
    fx = fixture2({"ada": 100, "bob": 0}, authorizations=[
        seed_auth("a_1", "ada", "bob", 5000, "open", expires_in=-7200), seed_auth("a_2", "ada", "bob", 5000, "captured"),
        seed_auth("a_3", "ada", "bob", 5000, "voided"), seed_auth("a_4", "ada", "bob", 5000, "expired", expires_in=-9000)])
    reset(fx)
    t = login("ada@example.com")
    check_me(T(call("GET", "/me", token=t), 200), total=100, held=0)
    # a negative balance is still a reset error
    expect(call("POST", "/_test/reset", body=fixture2({"ada": -1})), 422, "validation_failed")


@probe("S2-111", "S2-112", "S2-135", "S2-110")
def authorization_ttl_default_custom_and_validation():
    w = World2()
    a = T(w.auth("ada", "bob", 100))
    assert (parse_ts(a["expires_at"]) - parse_ts(a["created_at"])).total_seconds() == 600, a
    for ttl in (1, 30, 3600):
        w = World2(ttl=ttl)
        a = T(w.auth("ada", "bob", 100))
        assert (parse_ts(a["expires_at"]) - parse_ts(a["created_at"])).total_seconds() == ttl, (ttl, a)
        # applies to every authorisation created through the API
        b = T(w.auth("bob", "ada", 100))
        assert (parse_ts(b["expires_at"]) - parse_ts(b["created_at"])).total_seconds() == ttl, (ttl, b)
    w = World2()
    T(w.pay("ada", "bob", 100))
    before = w.me("ada")
    m = Multi()
    for bad in (0, -1, -600, 1.5, "60", True, False, [], {}):
        with m.case(repr(bad)):
            fx = fixture2({"zed": 5})
            fx["authorization_ttl_seconds"] = bad
            r = call("POST", "/_test/reset", body=fx)
            if isinstance(bad, (int, float)) and not isinstance(bad, bool):
                expect(r, 422, "validation_failed")      # a number that is not a positive integer
            else:                                         # wrong JSON type: 422 or 400 (not applied either way)
                assert r.status in (400, 422) and r.code in ("validation_failed", "malformed_request"), r
            assert w.me("ada") == before, "rejected reset changed state"
    m.done()


@probe("S2-093", "S2-118", "S2-119", "S2-120", "S2-166", "S2-173", "S2-222", "S2-223", "S2-163", "S2-178")
def expiry_happens_without_any_request_at_the_deadline():
    ttl = 4
    payers = ["ada", "bob", "cy", "dee", "eve", "fay", "nat"]
    payees = ["gus", "hal", "ivy", "jon", "kay", "lee", "oli"]
    bal = {n: 5000 for n in payers}
    bal.update({n: 0 for n in payees})
    bal["mia"] = 0
    w = World2(balances=bal, operators=["u_mia"], ttl=ttl)
    made = {}
    for p, r in zip(payers, payees):
        made[p] = T(w.auth(p, r, 3000))
    # partially captured, still open: 1000 of 3000 captured, 2000 still held
    first = T(w.capture("oli", made["nat"]["authorization_id"], {"amount": 1000, "final": False}))
    assert w.me("ada")["held"] == 3000 and w.auth_by_id("ada", made["ada"]["authorization_id"])["status"] == "open"
    assert w.me("nat")["held"] == 2000 and w.me("nat")["total"] == 4000
    time.sleep(ttl + 1.8)        # no request of any kind at the deadline
    # 1. GET /me is the first request: the released remainder is in `available`
    m = w.me("ada")
    check_me(m, total=5000, held=0)
    assert m["available"] == 5000, m
    # 2. GET /authorizations is the first request: status expired
    a = [x for x in w.all_auths("bob") if x["authorization_id"] == made["bob"]["authorization_id"]][0]
    assert a["status"] == "expired" and a["remaining_amount"] == 0, a
    assert parse_ts(a["expires_at"]) == parse_ts(made["bob"]["expires_at"])
    # 3. a payment is the first request: it may spend the whole released amount
    check_payment2(T(w.pay("cy", "ivy", 5000)), "cy", "ivy", 5000)
    # 4. a capture is the first request: authorization_expired
    expect(w.capture("jon", made["dee"]["authorization_id"]), 409, "authorization_expired")
    # 5. a void is the first request: not open (it is expired)
    expect(w.void("eve", made["eve"]["authorization_id"]), 409, "authorization_not_open")
    # 6. a settlement is the first request: its net debit may use the released funds
    T(w.settle("mia", [{"from_handle": "fay", "to_handle": "lee", "amount": 5000}]), 201)
    # 7. partially captured authorization: remainder released, capture record preserved
    n = [x for x in w.all_auths("nat") if x["authorization_id"] == made["nat"]["authorization_id"]][0]
    assert n["status"] == "expired" and n["captured_amount"] == 1000 and n["remaining_amount"] == 0, n
    assert n["payment_ids"] == [first["payment_id"]] and n["payment_id"] == first["payment_id"], n
    check_me(w.me("nat"), total=4000, held=0)
    assert w.me("nat")["available"] == 4000
    expect(w.capture("oli", made["nat"]["authorization_id"], {"amount": 1}), 409, "authorization_expired")
    check_me(w.me("oli"), total=1000)
    # everything is conserved and none of the expired holds is still counted anywhere
    assert w.total_now() == w.total
    for p in payers:
        assert w.me(p)["held"] == 0
    # expired authorisations are never `open`
    for p in payers:
        assert parjson(w.auths(p, status="open"), 200)["authorizations"] == []
        assert len(parjson(w.auths(p, status="expired"), 200)["authorizations"]) == 1


@probe("S2-093", "S2-135", "S2-118")
def a_fresh_authorization_is_open_until_its_deadline():
    w = World2(ttl=3)
    a = T(w.auth("ada", "bob", 1000))
    assert a["status"] == "open" and w.held("ada") == 1000
    time.sleep(3.6)
    assert w.held("ada") == 0 and w.avail("ada") == 10000
    assert w.auth_by_id("ada", a["authorization_id"])["status"] == "expired"


@probe("S2-099", "S2-154", "S2-101", "S2-102", "S2-141")
def payments_requests_splits_settlements_stay_immediate_and_carry_null_authorization_id():
    w = World2(operators=["u_dee"])
    p = T(w.pay("ada", "bob", 1500, note="x"))
    check_payment2(p, "ada", "bob", 1500, "x")
    # no intermediate hold, nothing to capture
    check_me(w.me("ada"), total=8500, held=0)
    assert w.me("bob")["total"] == 4000
    assert w.all_auths("ada") == [] and w.all_auths("bob") == []
    rq = T(w.req("bob", "ada", 100))
    pr = T(w.payreq("ada", rq["request_id"]))
    check_payment2(pr, "ada", "bob", 100, pr["note"], request_id=rq["request_id"])
    j = T(w.settle("dee", [{"from_handle": "ada", "to_handle": "bob", "amount": 10}]))
    check_payment2(j["payments"][0], "ada", "bob", 10, settlement_id=j["settlement_id"])
    sp = T(w.split("ada", 300, ["ada", "bob", "cy"]))
    assert len(sp["requests"]) == 2 and w.all_auths("ada") == []
    for n in ("ada", "bob", "cy"):
        for item in w.all_activity(n):
            assert "authorization_id" in item and item["authorization_id"] is None, item
    assert w.total_now() == w.total
    # authorizing a request is out of scope: the body's request_id is ignored, nothing is paid
    a = T(w.auth("ada", "bob", 50, request_id="rq_x"))
    check_auth(a, "ada", "bob", 50)
