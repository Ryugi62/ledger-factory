"""Requests: create, pay, decline, cancel, list (ledger §4 lifecycle, §8 requests)."""
from lib import *


@probe("S1-120", "S1-125", "S1-036", "S1-040", "S1-034")
def request_creation_shape_and_no_balance_check():
    w = World(balances={"ada": 100, "bob": 0, "cy": 0, "dee": 0})
    r = w.req("bob", "ada", 1200, note="taxi")
    q = T(r, 201)
    check_request(q, "bob", "ada", 1200, "taxi", "pending")
    # payer has only 100: creation is still fine, and moves no money
    assert w.bal("ada") == 100 and w.bal("bob") == 0
    # payer with zero balance, and a note default
    q2 = T(w.req("ada", "cy", 999_999_999), 201)
    check_request(q2, "ada", "cy", 999_999_999, "", "pending")
    # visible to exactly requester and payer
    for who, n in (("ada", 2), ("bob", 1), ("cy", 1), ("dee", 0)):
        assert len(w.all_requests(who)) == n, (who, n)
    assert w.request_by_id("ada", q["request_id"]) == q
    assert w.request_by_id("bob", q["request_id"]) == q


@probe("S1-121", "S1-122", "S1-123", "S1-124", "S1-057", "S1-059")
def request_validation_errors():
    w = World()
    t = w.tok["ada"]
    m = Multi()
    cases = [
        ("amount 0", {"payer_handle": "bob", "amount": 0}, 422, "validation_failed"),
        ("amount too big", {"payer_handle": "bob", "amount": 1000000001}, 422, "validation_failed"),
        ("amount float", {"payer_handle": "bob", "amount": 1.5}, 422, "validation_failed"),
        ("amount string", {"payer_handle": "bob", "amount": "5"}, 422, "validation_failed"),
        ("amount bool", {"payer_handle": "bob", "amount": True}, 422, "validation_failed"),
        ("self", {"payer_handle": "ada", "amount": 5}, 422, "self_request"),
        ("unknown", {"payer_handle": "nobody", "amount": 5}, 404, "not_found"),
        ("note long", {"payer_handle": "bob", "amount": 5, "note": "n" * 201}, 422, "validation_failed"),
        ("note null", {"payer_handle": "bob", "amount": 5, "note": None}, 422, "validation_failed"),
        ("note int", {"payer_handle": "bob", "amount": 5, "note": 3}, 422, "validation_failed"),
        ("missing payer", {"amount": 5}, 422, "validation_failed"),
        ("missing amount", {"payer_handle": "bob"}, 422, "validation_failed"),
        ("payer int", {"payer_handle": 5, "amount": 5}, 400, "malformed_request"),
    ]
    for name, body, st, code in cases:
        with m.case(name):
            expect(call("POST", "/requests", token=t, key=K(), body=body), st, code)
    with m.case("note 200 ok"):
        T(call("POST", "/requests", token=t, key=K(), body={"payer_handle": "bob", "amount": 5, "note": "n" * 200}), 201)
    with m.case("unparseable"):
        expect(call("POST", "/requests", token=t, key=K(), raw="{bad"), 400, "malformed_request")
    m.done()
    assert len(w.all_requests("ada")) == 1, "only the valid request may exist"


@probe("S1-126", "S1-127", "S1-038", "S1-042", "S1-039", "S1-035", "S1-007")
def paying_a_request_creates_a_payment_with_payer_chosen_visibility():
    w = World()
    # default public
    q = T(w.req("bob", "ada", 1200, note="taxi"))
    pay = T(w.payreq("ada", q["request_id"]), 201)
    check_payment(pay, "ada", "bob", 1200, pay["note"], "public", request_id=q["request_id"])
    assert w.bal("ada") == 8800 and w.bal("bob") == 3700
    got = w.request_by_id("bob", q["request_id"])
    check_request(got, "bob", "ada", 1200, "taxi", "paid", payment_id=pay["payment_id"])
    assert w.request_by_id("ada", q["request_id"]) == got
    # payer chooses private; requester (receiver) still sees it; third party does not
    q2 = T(w.req("bob", "ada", 100))
    pay2 = T(w.payreq("ada", q2["request_id"], {"visibility": "private"}), 201)
    check_payment(pay2, "ada", "bob", 100, pay2["note"], "private", request_id=q2["request_id"])
    assert pay2["payment_id"] in w.activity_ids("ada")
    assert pay2["payment_id"] in w.activity_ids("bob")
    assert pay2["payment_id"] not in w.activity_ids("cy")
    assert pay["payment_id"] in w.activity_ids("cy")  # public one is visible to everyone
    seen_a = [p for p in w.all_activity("ada") if p["payment_id"] == pay2["payment_id"]][0]
    seen_b = [p for p in w.all_activity("bob") if p["payment_id"] == pay2["payment_id"]][0]
    assert seen_a == seen_b == pay2, "one visibility value, seen identically by both parties"
    # the request itself never shows up in anyone's feed
    for who in ("ada", "bob", "cy"):
        ids = w.activity_ids(who)
        assert q["request_id"] not in ids and q2["request_id"] not in ids
        for p in w.all_activity(who):
            assert p["request_id"] in (None, q["request_id"], q2["request_id"])
    # visibility invalid in pay body
    q3 = T(w.req("bob", "ada", 100))
    expect(w.payreq("ada", q3["request_id"], {"visibility": "secret"}), 422, "validation_failed")
    expect(w.payreq("ada", q3["request_id"], {"visibility": None}), 422, "validation_failed")
    expect(w.payreq("ada", q3["request_id"], {"visibility": 5}), 422, "validation_failed")
    assert w.request_by_id("ada", q3["request_id"])["status"] == "pending"
    # the requester cannot choose visibility: a requests carries none
    assert w.sum_now() == w.total


@probe("S1-128", "S1-129", "S1-130", "S1-131", "S1-037", "S1-152")
def pay_error_cases_and_late_funds():
    w = World(balances={"ada": 100, "bob": 0, "cy": 10000, "dee": 0})
    q = T(w.req("bob", "ada", 500))
    rid = q["request_id"]
    # short -> 409 and nothing changes
    expect(w.payreq("ada", rid), 409, "insufficient_funds")
    assert w.bal("ada") == 100 and w.bal("bob") == 0
    assert w.request_by_id("ada", rid)["status"] == "pending"
    assert w.activity_ids("bob") == []
    # not the payer: requester, third party
    expect(w.payreq("bob", rid), 403, "forbidden")
    r = w.payreq("cy", rid)
    assert r.status in (403, 404) and r.code in ("forbidden", "not_found"), r
    expect(w.payreq("ada", "rq_missing"), 404, "not_found")
    # money arrives later: the same request becomes payable
    T(w.pay("cy", "ada", 400))
    pay = T(w.payreq("ada", rid), 201)
    assert pay["amount"] == 500 and w.bal("ada") == 0 and w.bal("bob") == 500
    # now paid: a new pay attempt is not_pending, even by an unaffordable payer
    expect(w.payreq("ada", rid), 409, "request_not_pending")
    # non-pending is checked before affordability: declined request, short payer
    q2 = T(w.req("bob", "ada", 5_000))
    T(w.decline("ada", q2["request_id"]), 200)
    expect(w.payreq("ada", q2["request_id"]), 409, "request_not_pending")
    q3 = T(w.req("bob", "ada", 5_000))
    T(w.cancel("bob", q3["request_id"]), 200)
    expect(w.payreq("ada", q3["request_id"]), 409, "request_not_pending")
    # permission is checked before state: requester paying a paid request is forbidden
    expect(w.payreq("bob", rid), 403, "forbidden")
    assert w.sum_now() == w.total


@probe("S1-134", "S1-135", "S1-138", "S1-036")
def decline_semantics():
    w = World()
    q = T(w.req("bob", "ada", 100))
    rid = q["request_id"]
    expect(w.decline("bob", rid), 403, "forbidden")           # requester may not decline
    assert w.request_by_id("ada", rid)["status"] == "pending"
    r = w.decline("cy", rid)
    assert r.status in (403, 404), r
    expect(w.decline("ada", "rq_missing"), 404, "not_found")
    j = T(w.decline("ada", rid), 200)
    check_request(j, "bob", "ada", 100, "", "declined")
    j2 = T(w.decline("ada", rid), 200)       # declining twice is not an error
    assert j2 == j
    assert w.request_by_id("bob", rid)["status"] == "declined"
    expect(w.cancel("bob", rid), 409, "request_not_pending")
    expect(w.payreq("ada", rid), 409, "request_not_pending")
    # paid and cancelled requests cannot be declined
    q2 = T(w.req("bob", "ada", 100))
    T(w.payreq("ada", q2["request_id"]))
    expect(w.decline("ada", q2["request_id"]), 409, "request_not_pending")
    q3 = T(w.req("bob", "ada", 100))
    T(w.cancel("bob", q3["request_id"]), 200)
    expect(w.decline("ada", q3["request_id"]), 409, "request_not_pending")
    # no Idempotency-Key needed
    q4 = T(w.req("bob", "ada", 100))
    expect(call("POST", "/requests/%s/decline" % q4["request_id"], token=w.tok["ada"]), 200)
    assert w.bal("ada") == 10000 - 100 and w.sum_now() == w.total


@probe("S1-136", "S1-137", "S1-138", "S1-036")
def cancel_semantics():
    w = World()
    q = T(w.req("bob", "ada", 100))
    rid = q["request_id"]
    expect(w.cancel("ada", rid), 403, "forbidden")             # payer may not cancel
    r = w.cancel("cy", rid)
    assert r.status in (403, 404), r
    expect(w.cancel("bob", "rq_missing"), 404, "not_found")
    j = T(w.cancel("bob", rid), 200)
    check_request(j, "bob", "ada", 100, "", "cancelled")
    assert T(w.cancel("bob", rid), 200) == j                    # cancelling twice is 200
    assert w.request_by_id("ada", rid)["status"] == "cancelled"
    expect(w.decline("ada", rid), 409, "request_not_pending")
    expect(w.payreq("ada", rid), 409, "request_not_pending")
    q2 = T(w.req("bob", "ada", 100))
    T(w.payreq("ada", q2["request_id"]))
    expect(w.cancel("bob", q2["request_id"]), 409, "request_not_pending")
    q3 = T(w.req("bob", "ada", 100))
    T(w.decline("ada", q3["request_id"]), 200)
    expect(w.cancel("bob", q3["request_id"]), 409, "request_not_pending")
    q4 = T(w.req("bob", "ada", 100))
    expect(call("POST", "/requests/%s/cancel" % q4["request_id"], token=w.tok["bob"]), 200)
    assert w.sum_now() == w.total and w.bal("ada") == 9900


@probe("S1-139", "S1-140", "S1-141", "S1-142", "S1-143", "S1-040")
def request_listing_filters_pagination_and_visibility():
    w = World()
    ids = []
    # bob->ada x2, ada->bob x1, cy->dee x1 (third party), spaced so created_at differs
    ids.append(T(w.req("bob", "ada", 10, note="first"))["request_id"])
    time.sleep(1.1)
    ids.append(T(w.req("ada", "bob", 20, note="second"))["request_id"])
    time.sleep(1.1)
    ids.append(T(w.req("bob", "ada", 30, note="third"))["request_id"])
    other = T(w.req("cy", "dee", 40))["request_id"]
    T(w.decline("ada", ids[0]), 200)
    T(w.payreq("ada", ids[2]))

    def listing(who, **q):
        return parjson(w.requests(who, **q), 200)

    j = listing("ada")
    assert set(j) >= {"requests", "has_more"} and j["has_more"] is False
    got = [q["request_id"] for q in j["requests"]]
    assert got == [ids[2], ids[1], ids[0]], "newest first, parties only: %r" % got
    assert other not in got
    assert [q["request_id"] for q in listing("bob")["requests"]] == [ids[2], ids[1], ids[0]]
    assert [q["request_id"] for q in listing("cy")["requests"]] == [other]
    assert listing("eve")["requests"] == []
    inc = [q["request_id"] for q in listing("ada", direction="incoming")["requests"]]
    out = [q["request_id"] for q in listing("ada", direction="outgoing")["requests"]]
    assert inc == [ids[2], ids[0]] and out == [ids[1]], (inc, out)
    inc_b = [q["request_id"] for q in listing("bob", direction="incoming")["requests"]]
    assert inc_b == [ids[1]]
    for st, want in (("pending", [ids[1]]), ("declined", [ids[0]]), ("paid", [ids[2]]), ("cancelled", [])):
        got = [q["request_id"] for q in listing("ada", status=st)["requests"]]
        assert got == want, (st, got)
    got = [q["request_id"] for q in listing("ada", status="declined", direction="incoming")["requests"]]
    assert got == [ids[0]]
    assert listing("ada", status="pending", direction="incoming")["requests"] == []
    # pagination and has_more
    j = listing("ada", limit=1)
    assert [q["request_id"] for q in j["requests"]] == [ids[2]] and j["has_more"] is True
    j = listing("ada", limit=1, offset=1)
    assert [q["request_id"] for q in j["requests"]] == [ids[1]] and j["has_more"] is True
    j = listing("ada", limit=1, offset=2)
    assert [q["request_id"] for q in j["requests"]] == [ids[0]] and j["has_more"] is False
    j = listing("ada", limit=3)
    assert len(j["requests"]) == 3 and j["has_more"] is False
    j = listing("ada", limit=2)
    assert len(j["requests"]) == 2 and j["has_more"] is True
    j = listing("ada", offset=3)
    assert j["requests"] == [] and j["has_more"] is False
    j = listing("ada", offset=500)
    assert j["requests"] == [] and j["has_more"] is False
    assert len(listing("ada", limit=200)["requests"]) == 3
    # created_at never increases down the list, and has a proper offset
    ts = [q["created_at"] for q in listing("ada")["requests"]]
    assert all(TS_RE.match(t) for t in ts)
    m = Multi()
    for q in ("direction=sideways", "direction=INCOMING", "status=done", "status=PENDING",
              "limit=0", "limit=201", "offset=-1", "limit=x"):
        with m.case(q):
            expect(call("GET", "/requests?" + q, token=w.tok["ada"]), 422, "validation_failed")
    m.done()
    # default limit is 50 and range holds: create 55 and list
    for i in range(55):
        T(w.req("cy", "eve", 1 + i))
    j = listing("eve")
    assert len(j["requests"]) == 50 and j["has_more"] is True
    j = listing("eve", offset=50)
    assert len(j["requests"]) == 5 and j["has_more"] is False
    j = listing("eve", limit=200)
    assert len(j["requests"]) == 55 and j["has_more"] is False
