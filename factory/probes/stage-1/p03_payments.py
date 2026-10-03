"""POST /payments and shared error handling (ledger §5, §8 payments)."""
from lib import *


@probe("S1-001", "S1-035", "S1-111", "S1-118")
def payment_happy_path_moves_money_atomically():
    w = World()
    r = w.pay("ada", "bob", 1500, note="dinner", visibility="public")
    p = T(r, 201)
    check_payment(p, "ada", "bob", 1500, "dinner", "public")
    assert w.bal("ada") == 8500 and w.bal("bob") == 4000
    assert w.sum_now() == w.total
    # defaults: note "" and visibility public
    p = T(w.pay("bob", "ada", 10))
    check_payment(p, "bob", "ada", 10, "", "public")
    # the payment is visible in both wallets' feeds (never one without the other)
    for who in ("ada", "bob"):
        assert p["payment_id"] in w.activity_ids(who)
    # distinct payments get distinct ids
    p2 = T(w.pay("bob", "ada", 10))
    assert p2["payment_id"] != p["payment_id"]
    # JSON number forms in the response are integral
    assert isinstance(p["amount"], int)


@probe("S1-112", "S1-118", "S1-006")
def insufficient_funds_boundary_and_no_trace():
    w = World(balances={"ada": 1000, "bob": 0, "cy": 0})
    expect(w.pay("ada", "bob", 1001), 409, "insufficient_funds")
    assert w.bal("ada") == 1000 and w.bal("bob") == 0
    assert w.activity_ids("ada") == [] and w.activity_ids("bob") == [], "failed payment left a trace"
    expect(w.pay("cy", "bob", 1), 409, "insufficient_funds")
    # exactly the balance succeeds and leaves zero (never negative)
    T(w.pay("ada", "bob", 1000))
    assert w.bal("ada") == 0 and w.bal("bob") == 1000
    expect(w.pay("ada", "bob", 1), 409, "insufficient_funds")
    assert w.bal("ada") == 0
    assert w.sum_now() == w.total


@probe("S1-113", "S1-114", "S1-115", "S1-116", "S1-117", "S1-057", "S1-058", "S1-059", "S1-009", "S1-049", "S1-062")
def payment_validation_errors():
    w = World()
    m = Multi()
    cases = [
        ("self", {"to_handle": "ada", "amount": 10}, 422, "self_payment"),
        ("unknown handle", {"to_handle": "nobody", "amount": 10}, 404, "not_found"),
        ("missing to_handle", {"amount": 10}, 422, "validation_failed"),
        ("missing amount", {"to_handle": "bob"}, 422, "validation_failed"),
        ("note 201 chars", {"to_handle": "bob", "amount": 10, "note": "n" * 201}, 422, "validation_failed"),
        ("note int", {"to_handle": "bob", "amount": 10, "note": 5}, 422, "validation_failed"),
        ("note null", {"to_handle": "bob", "amount": 10, "note": None}, 422, "validation_failed"),
        ("note list", {"to_handle": "bob", "amount": 10, "note": ["x"]}, 422, "validation_failed"),
        ("note bool", {"to_handle": "bob", "amount": 10, "note": True}, 422, "validation_failed"),
        ("vis other", {"to_handle": "bob", "amount": 10, "visibility": "friends"}, 422, "validation_failed"),
        ("vis case", {"to_handle": "bob", "amount": 10, "visibility": "PUBLIC"}, 422, "validation_failed"),
        ("vis empty", {"to_handle": "bob", "amount": 10, "visibility": ""}, 422, "validation_failed"),
        ("vis int", {"to_handle": "bob", "amount": 10, "visibility": 1}, 422, "validation_failed"),
        ("vis null", {"to_handle": "bob", "amount": 10, "visibility": None}, 422, "validation_failed"),
        ("to_handle int", {"to_handle": 5, "amount": 10}, 400, "malformed_request"),
        ("to_handle list", {"to_handle": ["bob"], "amount": 10}, 400, "malformed_request"),
        ("to_handle obj", {"to_handle": {}, "amount": 10}, 400, "malformed_request"),
    ]
    for name, body, st, code in cases:
        with m.case(name):
            expect(call("POST", "/payments", token=w.tok["ada"], key=K(), body=body), st, code)
    with m.case("to_handle null"):
        r = call("POST", "/payments", token=w.tok["ada"], key=K(), body={"to_handle": None, "amount": 10})
        assert r.status in (400, 422), r
    for raw in ("{nope", "", "[]", '"str"', "5", "null", '{"to_handle":"bob","amount":10'):
        with m.case("raw %r" % raw):
            r = call("POST", "/payments", token=w.tok["ada"], key=K(), raw=raw)
            if raw == "":
                assert r.status in (400, 422), r
            else:
                expect(r, 400, "malformed_request")
    # boundaries that are valid
    with m.case("note exactly 200"):
        T(w.pay("ada", "bob", 1, note="n" * 200), 201)
    with m.case("note 200 multibyte chars"):
        T(w.pay("ada", "bob", 1, note="é" * 200), 201)
        expect(w.pay("ada", "bob", 1, note="é" * 201), 422, "validation_failed")
    with m.case("note 200 astral chars"):
        T(w.pay("ada", "bob", 1, note="\U0001F600" * 200), 201)
        expect(w.pay("ada", "bob", 1, note="\U0001F600" * 201), 422, "validation_failed")
    m.done()
    # nothing in the failed cases moved money
    assert w.sum_now() == w.total
    # money moves only between existing wallets: no deposit-like endpoints exist
    before = w.bal("ada")
    for path in ("/deposits", "/topups", "/withdrawals", "/_test/balance", "/admin/balance"):
        r = call("POST", path, token=w.tok["ada"], key=K(), body={"amount": 1000, "handle": "ada"})
        assert r.status >= 400 and r.status < 500, r
    assert w.bal("ada") == before and w.sum_now() == w.total


@probe("S1-119")
def note_is_stored_verbatim():
    w = World(balances={"ada": 100000, "bob": 0})
    notes = ["  leading and trailing  ", "tabs\tand\nnewlines", "<b>html & \"quotes\" 'x'</b>", "héllo wörld ñ 日本語",
             "emoji \U0001F355\U0001F600 and ZWJ \U0001F468‍\U0001F469‍\U0001F467", "é (decomposed) vs é",
             "back\\slash \\n literal", " nbsp ", "%20 &amp; \\u0041", "", " "]
    m = Multi()
    for n in notes:
        with m.case(repr(n)):
            p = T(w.pay("ada", "bob", 1, note=n), 201)
            assert p["note"] == n, "note changed: sent %r got %r" % (n, p["note"])
            got = [x for x in w.all_activity("bob") if x["payment_id"] == p["payment_id"]][0]
            assert got["note"] == n, "feed note changed: sent %r got %r" % (n, got["note"])
    m.done()
    # same for requests
    rq = T(w.req("bob", "ada", 5, note=notes[4]))
    assert rq["note"] == notes[4]
    assert w.request_by_id("ada", rq["request_id"])["note"] == notes[4]


@probe("S1-054", "S1-055", "S1-056", "S1-052", "S1-063", "S1-064", "S1-065", "S1-061")
def shared_ranges_and_query_parameters():
    w = World()
    t = w.tok["ada"]
    m = Multi()
    body = {"to_handle": "bob", "amount": 1}
    with m.case("key 255 ok, 256 fails"):
        T(call("POST", "/payments", token=t, key="x" * 255, body=body), 201)
        expect(call("POST", "/payments", token=t, key="y" * 256, body=body), 422, "validation_failed")
        expect(call("POST", "/payments", token=t, key="z" * 1000, body=body), 422, "validation_failed")
        T(call("POST", "/payments", token=t, key="1", body=body), 201)
    with m.case("key missing / empty"):
        expect(call("POST", "/payments", token=t, body=body), 400, "missing_idempotency_key")
        expect(call("POST", "/payments", token=t, key="", body=body), 400, "missing_idempotency_key")
    for path in ("/activity", "/requests"):
        for q, ok in (("limit=1", True), ("limit=200", True), ("limit=0", False), ("limit=201", False),
                      ("limit=-1", False), ("limit=abc", False), ("limit=", False), ("limit=1e2", False),
                      ("limit=4.0", False), ("limit=%2B4", False), ("limit=+4", False), ("limit=1e9", False),
                      ("limit=007", None), ("offset=0", True), ("offset=5", True), ("offset=-1", False),
                      ("offset=abc", False), ("offset=1.0", False), ("offset=1e1", False), ("offset=%2B1", False),
                      ("offset=", False), ("limit=50&offset=0", True)):
            with m.case("%s?%s" % (path, q)):
                r = call("GET", path + "?" + q, token=t)
                if ok is True:
                    expect(r, 200)
                elif ok is False:
                    expect(r, 422, "validation_failed")
                else:
                    assert r.status in (200, 422), r
    m.done()
    # error statuses elsewhere in this ledger: 403 / 404 / 409 reuse
    q = T(w.req("bob", "ada", 5))
    expect(call("POST", "/requests/%s/cancel" % q["request_id"], token=t, body={}), 403, "forbidden")
    expect(call("POST", "/requests/rq_doesnotexist/cancel", token=t, body={}), 404, "not_found")
    k = K()
    T(call("POST", "/payments", token=t, key=k, body=body), 201)
    expect(call("POST", "/payments", token=t, key=k, body={"to_handle": "bob", "amount": 2}), 409, "idempotency_key_reuse")
