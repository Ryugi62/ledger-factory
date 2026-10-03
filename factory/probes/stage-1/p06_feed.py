"""GET /activity: the feed contract (ledger §4 feed, §8 activity)."""
from lib import *


@probe("S1-002", "S1-039", "S1-042", "S1-149", "S1-040")
def feed_contract_public_or_party():
    w = World()
    pub = T(w.pay("ada", "bob", 100, note="pub", visibility="public"))["payment_id"]
    prv = T(w.pay("ada", "bob", 200, note="prv", visibility="private"))["payment_id"]
    xx = T(w.pay("dee", "cy", 50, note="x", visibility="private"))["payment_id"]
    dflt = T(w.pay("bob", "cy", 10, note="d"))["payment_id"]
    view = {n: {p["payment_id"]: p for p in w.all_activity(n)} for n in w.balances}
    want = {"ada": {pub, prv, dflt}, "bob": {pub, prv, dflt}, "cy": {pub, dflt, xx}, "dee": {pub, dflt, xx},
            "eve": {pub, dflt}, "fay": {pub, dflt}}
    for n, ids in want.items():
        assert set(view[n]) == ids, "%s sees %s, want %s" % (n, sorted(view[n]), sorted(ids))
    prv = view["ada"][prv]["payment_id"]
    pub = view["ada"][pub]["payment_id"]
    # identical value for everybody who can see it
    assert view["ada"][prv] == view["bob"][prv]
    assert view["eve"][pub] == view["ada"][pub] == view["bob"][pub]
    assert view["ada"][prv]["visibility"] == "private" and view["eve"][pub]["visibility"] == "public"
    # shape
    j = parjson(w.activity("ada"), 200)
    assert set(j) >= {"payments", "has_more"} and isinstance(j["has_more"], bool)
    for p in j["payments"]:
        for k in PAYMENT_KEYS:
            assert k in p, (k, p)


@probe("S1-149", "S1-150", "S1-222", "S1-143", "S1-142")
def feed_order_limit_offset_has_more():
    w = World(balances={"ada": 1000000, "bob": 0, "cy": 0})
    ids = []
    for i in range(3):
        ids.append(T(w.pay("ada", "bob", 10 + i))["payment_id"])
        time.sleep(1.1)  # same-second order is unspecified; space them out
    j = parjson(w.activity("bob"), 200)
    assert [p["payment_id"] for p in j["payments"]] == ids[::-1], "newest first"
    assert j["has_more"] is False
    j = parjson(w.activity("bob", limit=1), 200)
    assert [p["payment_id"] for p in j["payments"]] == [ids[2]] and j["has_more"] is True
    j = parjson(w.activity("bob", limit=1, offset=2), 200)
    assert [p["payment_id"] for p in j["payments"]] == [ids[0]] and j["has_more"] is False
    j = parjson(w.activity("bob", limit=2, offset=1), 200)
    assert [p["payment_id"] for p in j["payments"]] == [ids[1], ids[0]] and j["has_more"] is False
    j = parjson(w.activity("bob", offset=3), 200)
    assert j["payments"] == [] and j["has_more"] is False
    j = parjson(w.activity("bob", offset=99), 200)
    assert j["payments"] == [] and j["has_more"] is False
    ts = [p["created_at"] for p in parjson(w.activity("bob"), 200)["payments"]]
    assert all(TS_RE.match(t) for t in ts)
    m = Multi()
    for q in ("limit=0", "limit=201", "limit=-5", "offset=-1", "limit=1.0", "offset=1e0", "limit=%2B3", "limit=abc"):
        with m.case(q):
            expect(call("GET", "/activity?" + q, token=w.tok["bob"]), 422, "validation_failed")
    m.done()
    # default page is 50, max page 200
    for i in range(60):
        T(w.pay("ada", "cy", 1))
    # cy receives 60 and also sees the 3 earlier public payments (public items are visible to everyone)
    j = parjson(w.activity("cy"), 200)
    assert len(j["payments"]) == 50 and j["has_more"] is True
    j = parjson(w.activity("cy", offset=50), 200)
    assert len(j["payments"]) == 13 and j["has_more"] is False
    j = parjson(w.activity("cy", limit=200), 200)
    assert len(j["payments"]) == 63 and j["has_more"] is False
    # paging walks every item exactly once
    seen = []
    for off in range(0, 70, 7):
        seen += [p["payment_id"] for p in parjson(w.activity("cy", limit=7, offset=off), 200)["payments"]]
    assert len(seen) == 63 and len(set(seen)) == 63


@probe("S1-040", "S1-041", "S1-038")
def requests_and_splits_never_appear_in_the_feed():
    w = World()
    T(w.req("bob", "ada", 100))
    T(w.split("ada", 300, ["ada", "bob", "cy"]))
    for who in w.balances:
        assert w.all_activity(who) == []
    q = T(w.req("cy", "dee", 7))
    T(w.payreq("dee", q["request_id"], {"visibility": "private"}))
    assert len(w.all_activity("cy")) == 1 and len(w.all_activity("dee")) == 1
    assert w.all_activity("ada") == [] and w.all_activity("eve") == []
