"""Splits and money rounding (ledger §8 splits, §9)."""
from lib import *

POOL = ["bob", "cy", "dee", "eve", "fay"]


def shares_of(j):
    return [(s["handle"], s["amount"]) for s in j["shares"]]


@probe("S1-144", "S1-145", "S1-041", "S1-148", "S1-001")
def split_shape_requests_and_no_money_moves():
    w = World()
    j = T(w.split("ada", 3000, ["ada", "bob", "cy"], note="dinner"), 201)
    assert isinstance(j["split_id"], str) and 0 < len(j["split_id"]) <= 64, j
    assert j["amount"] == 3000 and j["currency"] == "EUR" and j["note"] == "dinner", j
    assert TS_RE.match(j["created_at"]), j
    assert j["shares"] == [{"handle": "ada", "amount": 1000}, {"handle": "bob", "amount": 1000},
                           {"handle": "cy", "amount": 1000}], j["shares"]
    assert len(j["requests"]) == 2, j["requests"]
    check_request(j["requests"][0], "ada", "bob", 1000, ANY)
    check_request(j["requests"][1], "ada", "cy", 1000, ANY)
    # nothing about a split moves or checks money
    assert w.balances_now() == w.balances
    # requests are real: visible to their two parties only, pending
    assert w.request_by_id("bob", j["requests"][0]["request_id"]) == j["requests"][0]
    assert w.request_by_id("ada", j["requests"][1]["request_id"]) == j["requests"][1]
    assert w.request_by_id("cy", j["requests"][1]["request_id"]) == j["requests"][1]
    assert w.request_by_id("bob", j["requests"][1]["request_id"]) is None
    assert w.request_by_id("dee", j["requests"][0]["request_id"]) is None
    assert len(w.all_requests("ada")) == 2
    # a split is not a feed item, and neither are its requests
    for who in w.balances:
        assert w.all_activity(who) == [], "split created a feed item for %s" % who
    # paying a split request creates an ordinary payment that follows the feed rule
    pay = T(w.payreq("bob", j["requests"][0]["request_id"], {"visibility": "private"}))
    check_payment(pay, "bob", "ada", 1000, ANY, "private", request_id=j["requests"][0]["request_id"])
    assert w.activity_ids("cy") == [] and w.activity_ids("ada") == [pay["payment_id"]]
    # a split with no note
    j2 = T(w.split("ada", 10, ["bob"]), 201)
    assert j2["note"] == ""


@probe("S1-145", "S1-160", "S1-161", "S1-162", "S1-163", "S1-165", "S1-166", "S1-167", "S1-168", "S1-169")
def equal_split_rounding_table_and_ordering():
    w = World(balances={n: 0 for n in ["ada"] + POOL + ["gus"]})
    table = [(1000, 3, [334, 333, 333]), (1, 3, [1, 0, 0]), (10, 3, [4, 3, 3]), (999, 3, [333, 333, 333]),
             (5, 5, [1, 1, 1, 1, 1]), (7, 4, [2, 2, 2, 1]), (100, 6, [17, 17, 17, 17, 16, 16]),
             (2, 5, [1, 1, 0, 0, 0]), (1000000000, 7, [142857143] * 6 + [142857142]),
             (1000, 1, [1000]), (3, 2, [2, 1])]
    m = Multi()
    for amount, n, want in table:
        # n participants are exactly the listed handles (caller included only if listed)
        names = (POOL + ["gus", "ada"])[:n]
        with m.case("%d/%d omitted" % (amount, n)):
            j = T(w.split("ada", amount, names), 201)
            assert [a for _, a in shares_of(j)] == want, (shares_of(j), want)
            assert [h for h, _ in shares_of(j)] == names
            assert sum(a for _, a in shares_of(j)) == amount
            assert [q["payer_handle"] for q in j["requests"]] == [h for h in names if h != "ada"]
            assert [q["amount"] for q in j["requests"]] == [a for h, a in shares_of(j) if h != "ada"]
            assert len(j["requests"]) == len([h for h in names if h != "ada"])
    with m.case("caller in the middle"):
        j = T(w.split("ada", 1000, ["bob", "ada", "cy"]), 201)
        assert shares_of(j) == [("bob", 334), ("ada", 333), ("cy", 333)], j["shares"]
        assert [(q["payer_handle"], q["amount"]) for q in j["requests"]] == [("bob", 334), ("cy", 333)], j["requests"]
    with m.case("order gives the extra unit to someone else"):
        j = T(w.split("ada", 1000, ["cy", "bob", "ada"]), 201)
        assert shares_of(j) == [("cy", 334), ("bob", 333), ("ada", 333)]
        j = T(w.split("ada", 1000, ["cy", "ada", "bob"]), 201)
        assert shares_of(j) == [("cy", 334), ("ada", 333), ("bob", 333)]
        j = T(w.split("ada", 1000, ["ada", "bob", "cy"]), 201)
        assert shares_of(j) == [("ada", 334), ("bob", 333), ("cy", 333)]
        assert [(q["payer_handle"], q["amount"]) for q in j["requests"]] == [("bob", 333), ("cy", 333)]
    with m.case("zero share still produces a request"):
        j = T(w.split("ada", 1, ["ada", "bob", "cy"]), 201)
        assert shares_of(j) == [("ada", 1), ("bob", 0), ("cy", 0)], j["shares"]
        assert [(q["payer_handle"], q["amount"]) for q in j["requests"]] == [("bob", 0), ("cy", 0)]
        assert w.request_by_id("bob", j["requests"][0]["request_id"])["amount"] == 0
    m.done()


@probe("S1-147", "S1-148")
def split_with_only_the_caller_is_valid():
    w = World(balances={"ada": 0, "bob": 0})
    j = T(w.split("ada", 3000, ["ada"], note="solo"), 201)
    assert j["shares"] == [{"handle": "ada", "amount": 3000}] and j["requests"] == [], j
    assert w.all_requests("ada") == [] and w.all_requests("bob") == []
    # not affordable for anybody, still fine: no balance check anywhere
    j = T(w.split("ada", 999999999, ["bob"]), 201)
    assert len(j["requests"]) == 1 and w.bal("ada") == 0 and w.bal("bob") == 0


@probe("S1-146", "S1-057", "S1-059", "S1-051")
def split_validation_errors_leave_no_trace():
    w = World()
    t = w.tok["ada"]
    m = Multi()
    cases = [
        ("amount 0", {"amount": 0, "participant_handles": ["bob"]}, 422, "validation_failed"),
        ("amount too big", {"amount": 1000000001, "participant_handles": ["bob"]}, 422, "validation_failed"),
        ("amount float", {"amount": 10.5, "participant_handles": ["bob"]}, 422, "validation_failed"),
        ("amount string", {"amount": "10", "participant_handles": ["bob"]}, 422, "validation_failed"),
        ("empty handles", {"amount": 10, "participant_handles": []}, 422, "validation_failed"),
        ("duplicate handles", {"amount": 10, "participant_handles": ["bob", "cy", "bob"]}, 422, "validation_failed"),
        ("caller twice", {"amount": 10, "participant_handles": ["ada", "bob", "ada"]}, 422, "validation_failed"),
        ("note long", {"amount": 10, "participant_handles": ["bob"], "note": "n" * 201}, 422, "validation_failed"),
        ("note null", {"amount": 10, "participant_handles": ["bob"], "note": None}, 422, "validation_failed"),
        ("unknown handle", {"amount": 10, "participant_handles": ["bob", "nobody", "cy"]}, 404, "not_found"),
        ("missing handles", {"amount": 10}, 422, "validation_failed"),
        ("missing amount", {"participant_handles": ["bob"]}, 422, "validation_failed"),
        ("handles string", {"amount": 10, "participant_handles": "bob"}, 400, "malformed_request"),
        ("handles ints", {"amount": 10, "participant_handles": [1, 2]}, 400, "malformed_request"),
        ("handles object", {"amount": 10, "participant_handles": {"a": "bob"}}, 400, "malformed_request"),
    ]
    for name, body, st, code in cases:
        with m.case(name):
            expect(call("POST", "/splits", token=t, key=K(), body=body), st, code)
    with m.case("note 200 ok"):
        T(call("POST", "/splits", token=t, key=K(), body={"amount": 10, "participant_handles": ["bob"], "note": "n" * 200}), 201)
    with m.case("unparseable"):
        expect(call("POST", "/splits", token=t, key=K(), raw="{"), 400, "malformed_request")
    m.done()
    assert len(w.all_requests("bob")) == 1, "only the one valid split may have created a request"
    assert w.all_requests("cy") == [], "failed splits (unknown handle) must create no requests at all"


@probe("S1-164", "S1-005", "S1-160")
def many_splits_paid_in_full_conserve_the_total():
    w = World(balances={"ada": 100000, "bob": 100000, "cy": 100000, "dee": 100000, "eve": 100000})
    total0 = w.total
    plan = [("ada", 1000, ["ada", "bob", "cy"]), ("bob", 1, ["ada", "bob", "cy"]), ("cy", 10, ["dee", "cy", "eve"]),
            ("dee", 999, ["eve", "ada", "bob"]), ("eve", 5, ["ada", "bob", "cy", "dee", "eve"]),
            ("ada", 7, ["bob", "cy", "dee", "eve"])]
    expected = {n: w.balances[n] for n in w.balances}
    for caller, amount, handles in plan:
        j = T(w.split(caller, amount, handles), 201)
        assert sum(a for _, a in shares_of(j)) == amount
        for q in j["requests"]:
            if q["amount"] == 0:
                continue  # paying a zero-share request is unspecified
            T(w.payreq(q["payer_handle"], q["request_id"]))
            expected[q["payer_handle"]] -= q["amount"]
            expected[caller] += q["amount"]
    assert w.balances_now() == expected
    assert w.sum_now() == total0
