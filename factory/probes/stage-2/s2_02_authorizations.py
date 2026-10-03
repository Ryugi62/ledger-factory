"""Stage 2: POST /authorizations, capture, void, GET /authorizations and the funds rules."""
import time
from kit import *


@probe("S2-132", "S2-133", "S2-134", "S2-141", "S2-091", "S2-162", "S2-175", "S2-176", "S2-135")
def create_authorization_shape_defaults_and_hold():
    w = World2()
    r = w.auth("ada", "bob", 2000, note="deposit", visibility="private")
    a = T(r, 201)
    check_auth(a, "ada", "bob", 2000, "open", 0, 2000, "deposit", "private", payment_ids=[])
    assert a["payment_id"] is None
    assert (parse_ts(a["expires_at"]) - parse_ts(a["created_at"])).total_seconds() == 600
    # defaults
    d = T(w.auth("ada", "cy", 100))
    check_auth(d, "ada", "cy", 100, "open", 0, 100, "", "public", payment_ids=[])
    assert d["authorization_id"] != a["authorization_id"]
    # a hold moves no money: total unchanged, held up, available down, receiver untouched
    check_me(w.me("ada"), total=10000, held=2100)
    assert w.me("ada")["available"] == 7900 and w.me("ada")["balance"] == 10000
    check_me(w.me("bob"), total=2500, held=0)
    assert w.total_now() == w.total
    # an open authorisation is not a feed item
    for n in w.balances:
        assert w.all_activity(n) == [], "open authorization appeared in the feed of %s" % n
    # visible to payer and receiver only
    assert w.auth_by_id("ada", a["authorization_id"]) == a
    assert w.auth_by_id("bob", a["authorization_id"]) == a
    assert w.auth_by_id("cy", a["authorization_id"]) is None and w.auth_by_id("dee", a["authorization_id"]) is None
    # unknown fields are ignored
    T(w.auth("ada", "bob", 5, junk=1, captured_amount=99, status="captured"))


@probe("S2-136", "S2-137", "S2-138", "S2-139", "S2-140", "S2-132", "S2-096", "S2-095", "S2-051", "S2-003")
def create_authorization_errors_and_available_funds():
    w = World2()
    t = w.tok["ada"]
    m = Multi()
    cases = [
        ("amount 0", {"to_handle": "bob", "amount": 0}, 422, "validation_failed"),
        ("amount neg", {"to_handle": "bob", "amount": -1}, 422, "validation_failed"),
        ("amount too big", {"to_handle": "bob", "amount": 1000000001}, 422, "validation_failed"),
        ("amount float", {"to_handle": "bob", "amount": 1.5}, 422, "validation_failed"),
        ("amount str", {"to_handle": "bob", "amount": "5"}, 422, "validation_failed"),
        ("amount bool", {"to_handle": "bob", "amount": True}, 422, "validation_failed"),
        ("missing amount", {"to_handle": "bob"}, 422, "validation_failed"),
        ("missing to", {"amount": 5}, 422, "validation_failed"),
        ("self", {"to_handle": "ada", "amount": 5}, 422, "self_payment"),
        ("unknown", {"to_handle": "nobody", "amount": 5}, 404, "not_found"),
        ("note 201", {"to_handle": "bob", "amount": 5, "note": "n" * 201}, 422, "validation_failed"),
        ("note null", {"to_handle": "bob", "amount": 5, "note": None}, 422, "validation_failed"),
        ("note int", {"to_handle": "bob", "amount": 5, "note": 3}, 422, "validation_failed"),
        ("visibility", {"to_handle": "bob", "amount": 5, "visibility": "friends"}, 422, "validation_failed"),
        ("to int", {"to_handle": 5, "amount": 5}, 400, "malformed_request"),
    ]
    for name, body, st, code in cases:
        with m.case(name):
            expect(call("POST", "/authorizations", token=t, key=K(), body=body), st, code)
    with m.case("unparseable"):
        expect(call("POST", "/authorizations", token=t, key=K(), raw="{"), 400, "malformed_request")
    with m.case("no key"):
        expect(call("POST", "/authorizations", token=t, body={"to_handle": "bob", "amount": 5}), 400, "missing_idempotency_key")
        expect(call("POST", "/authorizations", token=t, key="", body={"to_handle": "bob", "amount": 5}), 400, "missing_idempotency_key")
    with m.case("no token"):
        expect(call("POST", "/authorizations", key=K(), body={"to_handle": "bob", "amount": 5}), 401, "unauthenticated")
    with m.case("note 200 ok"):
        T(w.auth("ada", "bob", 1, note="n" * 200))
    m.done()
    assert w.all_auths("cy") == [] and w.held("ada") == 1
    # insufficient funds are judged against `available`, not `total`
    w = World2()
    T(w.auth("ada", "bob", 6000))
    expect(w.auth("ada", "cy", 4001), 409, "insufficient_funds")
    assert w.held("ada") == 6000
    T(w.auth("ada", "cy", 4000))
    assert w.avail("ada") == 0 and w.me("ada")["total"] == 10000
    expect(w.auth("ada", "cy", 1), 409, "insufficient_funds")
    expect(w.auth("cy", "ada", 1), 409, "insufficient_funds")     # cy holds nothing and owns nothing


@probe("S2-096", "S2-100", "S2-095", "S2-001", "S2-094", "S2-097")
def held_funds_cannot_fund_payments_requests_authorizations_or_settlements():
    w = World2(operators=["u_mia"], balances={"ada": 10000, "bob": 2500, "cy": 0, "dee": 5000, "mia": 0})
    T(w.auth("ada", "bob", 7000))
    check_me(w.me("ada"), total=10000, held=7000)
    expect(w.pay("ada", "cy", 3001), 409, "insufficient_funds")
    assert w.me("ada")["total"] == 10000
    rq = T(w.req("bob", "ada", 3001))
    expect(w.payreq("ada", rq["request_id"]), 409, "insufficient_funds")
    assert w.request_by_id("ada", rq["request_id"])["status"] == "pending"
    expect(w.settle("mia", [{"from_handle": "ada", "to_handle": "cy", "amount": 3001}]), 409, "insufficient_funds")
    # a settlement whose net debit stays within `available` is fine, and incoming money counts
    T(w.settle("mia", [{"from_handle": "ada", "to_handle": "cy", "amount": 3500}, {"from_handle": "dee", "to_handle": "ada", "amount": 500}]), 201)
    assert w.me("ada")["total"] == 10000 - 3500 + 500 and w.held("ada") == 7000 and w.avail("ada") == 0
    # exactly `available` is spendable; then nothing more
    w2 = World2()
    T(w2.auth("ada", "bob", 7000))
    T(w2.pay("ada", "cy", 3000))
    assert w2.avail("ada") == 0 and w2.me("ada")["total"] == 7000
    expect(w2.pay("ada", "cy", 1), 409, "insufficient_funds")
    # releasing the hold returns the money to `available` at once
    aid = [a for a in w2.all_auths("ada")][0]["authorization_id"]
    T(w2.void("ada", aid), 200)
    check_me(w2.me("ada"), total=7000, held=0)
    T(w2.pay("ada", "cy", 7000))
    assert w2.total_now() == w2.total


@probe("S2-090", "S2-097", "S2-092", "S2-153", "S2-155", "S2-151", "S2-150", "S2-091", "S2-154", "S2-162")
def capture_default_is_one_final_capture_and_releases_the_remainder():
    w = World2()
    a = T(w.auth("ada", "bob", 2000, note="deposit", visibility="private"))
    aid = a["authorization_id"]
    r = w.capture("bob", aid, {"amount": 1500})
    p = T(r, 201)
    check_payment2(p, "ada", "bob", 1500, "deposit", "private", authorization_id=aid)
    assert p["request_id"] is None and p["settlement_id"] is None
    # the remainder is released in the same step; money moved
    check_me(w.me("ada"), total=8500, held=0)
    assert w.me("ada")["available"] == 8500
    check_me(w.me("bob"), total=4000)
    assert w.total_now() == w.total
    got = w.auth_by_id("ada", aid)
    check_auth(got, "ada", "bob", 2000, "captured", 1500, 0, "deposit", "private", payment_ids=[p["payment_id"]])
    assert got["payment_id"] == p["payment_id"] and got == w.auth_by_id("bob", aid)
    # the captured payment follows the ordinary feed rule: private -> parties only
    assert p["payment_id"] in w.activity_ids("ada") and p["payment_id"] in w.activity_ids("bob")
    assert p["payment_id"] not in w.activity_ids("cy")
    item = [x for x in w.all_activity("bob") if x["payment_id"] == p["payment_id"]][0]
    assert item == p, "feed item must equal the capture receipt"
    # one final capture per authorisation
    expect(w.capture("bob", aid, {"amount": 1}), 409, "authorization_not_open")
    expect(w.capture("bob", aid), 409, "authorization_not_open")
    expect(w.void("ada", aid), 409, "authorization_not_open")
    assert w.me("bob")["total"] == 4000
    # amount omitted -> the whole remaining amount, public visibility copied
    b = T(w.auth("ada", "cy", 700))
    p2 = T(w.capture("cy", b["authorization_id"], {}))
    check_payment2(p2, "ada", "cy", 700, "", "public", authorization_id=b["authorization_id"])
    assert p2["payment_id"] in w.activity_ids("dee")
    check_auth(w.auth_by_id("cy", b["authorization_id"]), "ada", "cy", 700, "captured", 700, 0, payment_ids=[p2["payment_id"]])


@probe("S2-096", "S2-097", "S2-155")
def capture_may_spend_money_reserved_for_it():
    w = World2(balances={"ada": 2000, "bob": 0})
    a = T(w.auth("ada", "bob", 2000))
    assert w.avail("ada") == 0
    expect(w.pay("ada", "bob", 1), 409, "insufficient_funds")
    p = T(w.capture("bob", a["authorization_id"], {"amount": 2000}))
    check_me(w.me("ada"), total=0, held=0)
    check_me(w.me("bob"), total=2000)
    assert w.total_now() == w.total


@probe("S2-157", "S2-158", "S2-159", "S2-160", "S2-161", "S2-162", "S2-167", "S2-092", "S2-097")
def extended_capture_mode_keeps_the_remainder_held():
    w = World2()
    a = T(w.auth("ada", "bob", 2000, note="n", visibility="private"))
    aid = a["authorization_id"]
    p1 = T(w.capture("bob", aid, {"amount": 700, "final": False}))
    check_payment2(p1, "ada", "bob", 700, "n", "private", authorization_id=aid)
    g = w.auth_by_id("ada", aid)
    check_auth(g, "ada", "bob", 2000, "open", 700, 1300, "n", "private", payment_ids=[p1["payment_id"]])
    check_me(w.me("ada"), total=9300, held=1300)
    assert w.avail("ada") == 8000
    p2 = T(w.capture("bob", aid, {"amount": 600, "final": False}))
    g = w.auth_by_id("bob", aid)
    check_auth(g, "ada", "bob", 2000, "open", 1300, 700, "n", "private", payment_ids=[p1["payment_id"], p2["payment_id"]])
    assert g["payment_id"] == p2["payment_id"]
    check_me(w.me("ada"), total=8700, held=700)
    # capture_exceeds_authorization compares with the REMAINING amount
    expect(w.capture("bob", aid, {"amount": 701, "final": False}), 422, "capture_exceeds_authorization")
    expect(w.capture("bob", aid, {"amount": 701}), 422, "capture_exceeds_authorization")
    expect(w.capture("bob", aid, {"amount": 2000}), 422, "capture_exceeds_authorization")
    check_me(w.me("ada"), total=8700, held=700)
    # omitted amount defaults to the remainder and closes it
    p3 = T(w.capture("bob", aid, {}))
    assert p3["amount"] == 700
    g = w.auth_by_id("ada", aid)
    check_auth(g, "ada", "bob", 2000, "captured", 2000, 0, "n", "private",
               payment_ids=[p1["payment_id"], p2["payment_id"], p3["payment_id"]])
    check_me(w.me("ada"), total=8000, held=0)
    check_me(w.me("bob"), total=4500)
    expect(w.capture("bob", aid, {"amount": 1, "final": False}), 409, "authorization_not_open")
    assert w.total_now() == w.total
    # capturing the entire remainder closes it even with final:false
    b = T(w.auth("ada", "cy", 1000))["authorization_id"]
    T(w.capture("cy", b, {"amount": 400, "final": False}))
    T(w.capture("cy", b, {"amount": 600, "final": False}))
    g = w.auth_by_id("ada", b)
    assert g["status"] == "captured" and g["captured_amount"] == 1000 and g["remaining_amount"] == 0 and len(g["payment_ids"]) == 2, g
    expect(w.capture("cy", b, {"amount": 1, "final": False}), 409, "authorization_not_open")
    # `final:false` with no amount captures the whole remainder and closes
    c = T(w.auth("ada", "dee", 500))["authorization_id"]
    T(w.capture("dee", c, {"final": False}))
    assert w.auth_by_id("ada", c)["status"] == "captured"
    # a final capture of less than the remainder releases the rest
    before = w.me("ada")["total"]
    d = T(w.auth("ada", "eve", 1000))["authorization_id"]
    T(w.capture("eve", d, {"amount": 300, "final": False}))
    T(w.capture("eve", d, {"amount": 200}))
    g = w.auth_by_id("ada", d)
    check_auth(g, "ada", "eve", 1000, "captured", 500, 0, payment_ids=g["payment_ids"])
    assert len(g["payment_ids"]) == 2
    assert w.me("ada")["total"] == before - 500 and w.held("ada") == 0
    e = T(w.auth("ada", "fay", 1000))["authorization_id"]
    T(w.capture("fay", e, {"amount": 100, "final": True}))
    check_auth(w.auth_by_id("ada", e), "ada", "fay", 1000, "captured", 100, 0, payment_ids=w.auth_by_id("ada", e)["payment_ids"])
    assert w.held("ada") == 0
    assert w.total_now() == w.total


@probe("S2-168", "S2-169", "S2-170", "S2-165", "S2-150", "S2-174", "S2-167", "S2-157")
def capture_errors_and_permissions():
    w = World2()
    a = T(w.auth("ada", "bob", 2000))
    aid = a["authorization_id"]
    m = Multi()
    with m.case("payer cannot capture"):
        expect(w.capture("ada", aid), 403, "forbidden")
    with m.case("third party gets 403, not 404"):
        expect(w.capture("cy", aid), 403, "forbidden")
    with m.case("unknown"):
        expect(w.capture("bob", "a_missing"), 404, "not_found")
    with m.case("no key"):
        expect(call("POST", "/authorizations/%s/capture" % aid, token=w.tok["bob"], body={}), 400, "missing_idempotency_key")
    with m.case("no token"):
        expect(call("POST", "/authorizations/%s/capture" % aid, key=K(), body={}), 401, "unauthenticated")
    for bad in (0, -5, 1.5, "100", True):
        with m.case("amount %r" % (bad,)):
            expect(w.capture("bob", aid, {"amount": bad}), 422, "validation_failed")
    with m.case("amount above authorized"):
        expect(w.capture("bob", aid, {"amount": 2001}), 422, "capture_exceeds_authorization")
    with m.case("unparseable"):
        expect(call("POST", "/authorizations/%s/capture" % aid, token=w.tok["bob"], key=K(), raw="{x"), 400, "malformed_request")
    with m.case("final wrong type"):
        for bad in ("false", 0, 1, None):
            r = w.capture("bob", aid, {"amount": 100, "final": bad})
            assert r.status in (400, 422) and r.code in ("malformed_request", "validation_failed"), (bad, r)
    m.done()
    assert w.auth_by_id("ada", aid)["status"] == "open" and w.held("ada") == 2000 and w.me("bob")["total"] == 2500, "refused captures changed state"
    # permission is checked before state: payer/third party get 403 even on a closed authorization
    T(w.capture("bob", aid, {}))
    expect(w.capture("ada", aid), 403, "forbidden")
    expect(w.capture("cy", aid), 403, "forbidden")
    expect(w.capture("bob", aid), 409, "authorization_not_open")
    v = T(w.auth("ada", "bob", 100))["authorization_id"]
    T(w.void("ada", v), 200)
    expect(w.capture("bob", v), 409, "authorization_not_open")


@probe("S2-171", "S2-172", "S2-173", "S2-174", "S2-163", "S2-165")
def void_semantics():
    w = World2()
    a = T(w.auth("ada", "bob", 2000, note="n"))
    aid = a["authorization_id"]
    expect(w.void("bob", aid), 403, "forbidden")          # the receiver may not void
    expect(w.void("cy", aid), 403, "forbidden")           # nor may a stranger
    expect(w.void("ada", "a_missing"), 404, "not_found")
    expect(call("POST", "/authorizations/%s/void" % aid, key=K(), body={}), 401, "unauthenticated")
    assert w.held("ada") == 2000
    j = T(w.void("ada", aid), 200)
    check_auth(j, "ada", "bob", 2000, "voided", 0, 0, "n")
    check_me(w.me("ada"), total=10000, held=0)
    assert w.me("bob")["total"] == 2500
    assert T(w.void("ada", aid), 200) == j                 # voiding twice is 200 with the current state
    expect(w.capture("bob", aid), 409, "authorization_not_open")
    assert w.all_activity("ada") == []
    # no Idempotency-Key needed
    b = T(w.auth("ada", "bob", 100))["authorization_id"]
    expect(call("POST", "/authorizations/%s/void" % b, token=w.tok["ada"]), 200)
    # captured -> not open
    c = T(w.auth("ada", "bob", 100))["authorization_id"]
    T(w.capture("bob", c, {}))
    expect(w.void("ada", c), 409, "authorization_not_open")
    # void after a partial capture: only the remainder is released, capture records preserved
    d = T(w.auth("ada", "bob", 2000))["authorization_id"]
    p = T(w.capture("bob", d, {"amount": 500, "final": False}))
    before = w.me("ada")
    check_me(before, total=10000 - 100 - 500, held=1500)
    j = T(w.void("ada", d), 200)
    check_auth(j, "ada", "bob", 2000, "voided", 500, 0, payment_ids=[p["payment_id"]])
    check_me(w.me("ada"), total=10000 - 100 - 500, held=0)
    assert w.me("bob")["total"] == 2500 + 100 + 500, "the capture stays paid"
    assert p["payment_id"] in w.activity_ids("ada")
    expect(w.capture("bob", d, {"amount": 1}), 409, "authorization_not_open")
    assert w.total_now() == w.total


@probe("S2-175", "S2-176", "S2-177", "S2-178", "S2-179", "S2-053", "S2-134")
def authorization_listing_filters_order_and_pagination():
    w = World2()
    a1 = T(w.auth("ada", "bob", 100, note="first"))
    time.sleep(1.1)
    a2 = T(w.auth("bob", "ada", 200, note="second"))
    time.sleep(1.1)
    a3 = T(w.auth("ada", "cy", 300, note="third"))
    other = T(w.auth("dee", "cy", 50))
    T(w.capture("bob", a1["authorization_id"], {}))
    T(w.void("bob", a2["authorization_id"]), 200)
    ids = lambda who, **q: [a["authorization_id"] for a in parjson(w.auths(who, **q), 200)["authorizations"]]
    A1, A2, A3 = a1["authorization_id"], a2["authorization_id"], a3["authorization_id"]
    j = parjson(w.auths("ada"), 200)
    assert set(j) >= {"authorizations", "has_more"} and j["has_more"] is False
    assert ids("ada") == [A3, A2, A1], "newest first, parties only: %r" % ids("ada")
    assert ids("bob") == [A2, A1]
    assert set(ids("cy")) == {A3, other["authorization_id"]} and ids("eve") == [] and ids("fay") == []
    assert ids("ada", direction="outgoing") == [A3, A1] and ids("ada", direction="incoming") == [A2]
    assert ids("bob", direction="incoming") == [A1] and ids("bob", direction="outgoing") == [A2]
    assert ids("ada", status="open") == [A3] and ids("ada", status="captured") == [A1] and ids("ada", status="voided") == [A2]
    assert ids("ada", status="expired") == []
    assert ids("ada", status="open", direction="incoming") == []
    got = parjson(w.auths("ada"), 200)["authorizations"][0]
    assert got == a3
    # pagination
    j = parjson(w.auths("ada", limit=1), 200)
    assert [a["authorization_id"] for a in j["authorizations"]] == [A3] and j["has_more"] is True
    j = parjson(w.auths("ada", limit=1, offset=2), 200)
    assert [a["authorization_id"] for a in j["authorizations"]] == [A1] and j["has_more"] is False
    j = parjson(w.auths("ada", limit=2), 200)
    assert len(j["authorizations"]) == 2 and j["has_more"] is True
    j = parjson(w.auths("ada", offset=3), 200)
    assert j["authorizations"] == [] and j["has_more"] is False
    assert parjson(w.auths("ada", offset=500), 200)["authorizations"] == []
    m = Multi()
    for q in ("direction=sideways", "direction=INCOMING", "status=done", "status=OPEN", "limit=0", "limit=201", "limit=-1",
              "limit=1e2", "limit=4.0", "limit=%2B4", "offset=-1", "offset=1.0", "limit=x"):
        with m.case(q):
            expect(call("GET", "/authorizations?" + q, token=w.tok["ada"]), 422, "validation_failed")
    with m.case("unknown params ignored"):
        expect(call("GET", "/authorizations?nonsense=1", token=w.tok["ada"]), 200)
    with m.case("auth required"):
        expect(call("GET", "/authorizations"), 401, "unauthenticated")
    m.done()
    # default limit 50 / max 200
    w = World2(balances={"ada": 100000, "bob": 0})
    for i in range(55):
        T(w.auth("ada", "bob", 1))
    j = parjson(w.auths("bob"), 200)
    assert len(j["authorizations"]) == 50 and j["has_more"] is True
    j = parjson(w.auths("bob", offset=50), 200)
    assert len(j["authorizations"]) == 5 and j["has_more"] is False
    assert len(parjson(w.auths("bob", limit=200), 200)["authorizations"]) == 55
