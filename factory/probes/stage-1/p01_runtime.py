"""Runtime contract, reset/seed, conventions, fixture format (ledger §2-§4)."""
import json
from lib import *


@probe("S1-013", "S1-019")
def health():
    r = call("GET", "/health")
    expect(r, 200)
    assert r.json == {"status": "ok"}, r
    import lib
    assert getattr(lib, "STARTUP", 0) <= 60, "service took more than 60s to become healthy"


@probe("S1-020", "S1-021", "S1-005")
def reset_replaces_all_state_and_is_repeatable():
    w = World()
    old_ada = w.tok["ada"]
    # create state of every kind: signup, payment, request, split
    s = call("POST", "/auth/signup", body={"email": "newbie@example.com", "password": "longenough1", "display_name": "N"})
    expect(s, 201)
    T(w.pay("ada", "bob", 100))
    T(w.req("bob", "ada", 50))
    T(w.split("ada", 90, ["ada", "bob", "cy"]))
    # second fixture, entirely different users; no Authorization on reset
    fx2 = fixture({"kim": 700, "lee": 300})
    expect(call("POST", "/_test/reset", body=fx2), 204)
    expect(call("GET", "/me", token=old_ada), 401, "unauthenticated")
    expect(call("GET", "/me", token=s.json["token"]), 401, "unauthenticated")
    expect(call("POST", "/auth/login", body={"email": "ada@example.com", "password": PASSWORD}), 401, "unauthenticated")
    expect(call("POST", "/auth/login", body={"email": "newbie@example.com", "password": "longenough1"}), 401, "unauthenticated")
    t = login("kim@example.com")
    j = call("GET", "/activity", token=t)
    assert T(j, 200)["payments"] == [], "fixture without payments must give empty feed: %r" % j
    assert T(call("GET", "/requests", token=t), 200)["requests"] == []
    assert T(call("GET", "/me", token=t), 200)["balance"] == 700
    # the previous handle is free again: signup can claim 'ada'
    expect(call("POST", "/auth/signup", body={"email": "ada@elsewhere.org", "password": "longenough1", "display_name": "A"}), 201)
    # repeated resets (same fixture twice) restore the same state
    for _ in range(3):
        expect(call("POST", "/_test/reset", body=fx2), 204)
        t = login("lee@example.com")
        assert T(call("GET", "/me", token=t), 200)["balance"] == 300
    # sum of balances equals the total seeded by the last reset
    w = World(balances={"ada": 123, "bob": 456, "cy": 789})
    T(w.pay("ada", "bob", 100))
    T(w.pay("cy", "ada", 700))
    assert w.sum_now() == 123 + 456 + 789


@probe("S1-046", "S1-020")
def reset_with_negative_balance_is_rejected_and_changes_nothing():
    w = World()
    T(w.pay("ada", "bob", 100))
    bad = fixture({"zed": 100, "yan": -1})
    r = call("POST", "/_test/reset", body=bad)
    expect(r, 422, "validation_failed")
    # nothing changed: old users, tokens, balances and payments are intact
    assert w.bal("ada") == 9900 and w.bal("bob") == 2600
    assert len(w.all_activity("ada")) == 1
    expect(call("POST", "/auth/login", body={"email": "zed@example.com", "password": PASSWORD}), 401)


@probe("S1-027", "S1-047", "S1-110")
def currency_and_minor_units_are_reported_per_fixture():
    for cur, mu in (("EUR", 2), ("JPY", 0), ("BHD", 3)):
        w = World(balances={"ada": 5000, "bob": 0}, currency=cur, minor_units=mu)
        me = w.me("ada")
        assert me == {"user_id": "u_ada", "display_name": "Ada", "handle": "ada", "balance": 5000,
                      "currency": cur, "minor_units": mu}, me
        p = T(w.pay("ada", "bob", 1234))
        assert p["currency"] == cur, p
        assert w.bal("ada") == 5000 - 1234 and w.bal("bob") == 1234
        rq = T(w.req("bob", "ada", 77))
        assert rq["currency"] == cur, rq


@probe("S1-031", "S1-044", "S1-030", "S1-026", "S1-023")
def seeded_users_can_log_in_and_keep_their_handles():
    w = World()
    r = call("POST", "/auth/login", body={"email": "bob@example.com", "password": PASSWORD})
    j = T(r, 200)
    assert j["user_id"] == "u_bob" and j["display_name"] == "Bob" and isinstance(j["token"], str) and j["token"]
    me = w.me("bob")
    assert me["handle"] == "bob" and me["user_id"] == "u_bob"
    import re
    for n in w.balances:
        h = w.me(n)["handle"]
        assert re.match(r"^[a-z0-9_]{1,20}$", h), h
    # payment created: ids opaque strings <= 64 chars, timestamps RFC 3339 with offset
    p = T(w.pay("ada", "bob", 1))
    assert isinstance(p["payment_id"], str) and 1 <= len(p["payment_id"]) <= 64
    assert TS_RE.match(p["created_at"]), p["created_at"]
    # handle immutability: re-login / more activity never changes it
    w.pay("bob", "ada", 1)
    assert w.me("bob")["handle"] == "bob"


@probe("S1-048", "S1-045", "S1-039", "S1-040", "S1-042")
def seeded_payments_and_requests_follow_feed_contract_and_balances_are_not_replayed():
    pays = [
        {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee", "visibility": "public"},
        {"id": "p_2", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 700, "note": "secret", "visibility": "private"},
        {"id": "p_3", "from_user_id": "u_cy", "to_user_id": "u_dee", "amount": 300, "note": "hidden", "visibility": "private"},
    ]
    reqs = [
        {"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"},
        {"id": "rq_2", "requester_id": "u_cy", "payer_id": "u_dee", "amount": 40, "note": "x", "status": "declined"},
        {"id": "rq_3", "requester_id": "u_dee", "payer_id": "u_eve", "amount": 41, "note": "y", "status": "cancelled"},
    ]
    w = World(balances={"ada": 10000, "bob": 2500, "cy": 50, "dee": 5000, "eve": 0}, payments=pays, requests=reqs)
    # balances are exactly the seeded ones: seeded payments are not replayed
    assert w.balances_now() == {"ada": 10000, "bob": 2500, "cy": 50, "dee": 5000, "eve": 0}
    assert w.sum_now() == 17550
    ids = lambda who: sorted(w.activity_ids(who))
    assert ids("ada") == ["p_1", "p_2"], ids("ada")
    assert ids("bob") == ["p_1", "p_2"], ids("bob")
    assert ids("cy") == ["p_1", "p_3"], ids("cy")
    assert ids("dee") == ["p_1", "p_3"], ids("dee")
    assert ids("eve") == ["p_1"], ids("eve")
    p2 = [p for p in w.all_activity("bob") if p["payment_id"] == "p_2"][0]
    check_payment(p2, "ada", "bob", 700, "secret", "private")
    p2a = [p for p in w.all_activity("ada") if p["payment_id"] == "p_2"][0]
    assert p2a == p2, "both parties must see the same payment value"
    # requests: only to their two parties, with their seeded ids and statuses
    rid = lambda who: sorted(q["request_id"] for q in w.all_requests(who))
    assert rid("ada") == ["rq_1"] and rid("bob") == ["rq_1"]
    assert rid("cy") == ["rq_2"] and rid("dee") == ["rq_2", "rq_3"] and rid("eve") == ["rq_3"]
    rq1 = w.request_by_id("ada", "rq_1")
    check_request(rq1, "bob", "ada", 1200, "taxi", "pending")
    assert w.request_by_id("dee", "rq_2")["status"] == "declined"
    assert w.request_by_id("eve", "rq_3")["status"] == "cancelled"
    # seeded non-pending request cannot be paid; the seeded pending one can
    expect(w.payreq("dee", "rq_2"), 409, "request_not_pending")
    pay = T(w.payreq("ada", "rq_1", {"visibility": "private"}))
    check_payment(pay, "ada", "bob", 1200, pay["note"], "private", request_id="rq_1")
    assert w.bal("ada") == 8800 and w.bal("bob") == 3700


@probe("S1-022", "S1-024", "S1-025", "S1-060")
def conventions_unknown_fields_and_query_params_are_ignored():
    w = World()
    r = call("POST", "/payments", token=w.tok["ada"], key=K(),
             body={"to_handle": "bob", "amount": 10, "bogus": {"x": [1, 2]}, "visibility": "public", "zzz": None})
    p = T(r, 201)
    check_payment(p, "ada", "bob", 10)
    assert r.headers.get("content-type", "").lower().replace(" ", "").startswith("application/json;charset=utf-8"), r.headers
    for path in ("/me", "/activity", "/requests"):
        expect(call("GET", path + "?nonsense=1&foo=bar&limit=5", token=w.tok["ada"]), 200)
    expect(call("POST", "/auth/login", body={"email": "ada@example.com", "password": PASSWORD, "extra": 1}), 200)
    r = call("POST", "/auth/signup", body={"email": "extra@example.com", "password": "longenough1",
                                            "display_name": "E", "handle": "chosen", "balance": 99999})
    j = T(r, 201)
    me = T(call("GET", "/me", token=j["token"]), 200)
    assert me["handle"] == "extra" and me["balance"] == 0, "signup ignores handle/balance fields: %r" % me
    q = T(w.req("bob", "ada", 5, bogus=True), 201)
    expect(w.payreq("ada", q["request_id"], {"visibility": "private", "junk": 1}), 201)


@probe("S1-028", "S1-008", "S1-043")
def amount_accepts_integral_numbers_only():
    w = World(balances={"ada": 5_000_000_000, "bob": 0})
    for raw_amt, val in (("1000", 1000), ("1000.0", 1000), ("1e3", 1000), ("1E3", 1000), ("2.5e2", 250),
                         ("1e9", 1000000000), ("1000000000", 1000000000), ("999999999", 999999999), ("1", 1)):
        raw = '{"to_handle":"bob","amount":%s}' % raw_amt
        r = call("POST", "/payments", token=w.tok["ada"], key=K(), raw=raw)
        p = T(r, 201)
        assert p["amount"] == val, (raw_amt, p)
    exp = 5_000_000_000 - (1000 * 4 + 250 + 1000000000 + 1000000000 + 999999999 + 1)
    assert w.bal("ada") == exp, (w.bal("ada"), exp)
    assert w.sum_now() == 5_000_000_000


@probe("S1-029", "S1-059", "S1-058", "S1-043", "S1-062")
def amount_rejections_are_422():
    w = World(balances={"ada": 5_000_000_000, "bob": 0})
    bad = ["0", "-1", "-1000", "0.5", "1000.5", "1e-1", "1000000001", "1e10", "true", "false", '"1000"', '"abc"', '""']
    m = Multi()
    for amt in bad:
        with m.case(amt):
            r = call("POST", "/payments", token=w.tok["ada"], key=K(), raw='{"to_handle":"bob","amount":%s}' % amt)
            expect(r, 422, "validation_failed")
        with m.case("req:" + amt):
            r = call("POST", "/requests", token=w.tok["ada"], key=K(), raw='{"payer_handle":"bob","amount":%s}' % amt)
            expect(r, 422, "validation_failed")
        with m.case("split:" + amt):
            r = call("POST", "/splits", token=w.tok["ada"], key=K(), raw='{"participant_handles":["bob"],"amount":%s}' % amt)
            expect(r, 422, "validation_failed")
    with m.case("missing"):
        expect(call("POST", "/payments", token=w.tok["ada"], key=K(), body={"to_handle": "bob"}), 422, "validation_failed")
    # arrays/objects are "other wrong JSON types": 400 malformed_request (S1-051); null is either
    for amt in ("[]", "{}", "[1000]"):
        with m.case("type:" + amt):
            expect(call("POST", "/payments", token=w.tok["ada"], key=K(), raw='{"to_handle":"bob","amount":%s}' % amt),
                   400, "malformed_request")
    with m.case("null"):
        r = call("POST", "/payments", token=w.tok["ada"], key=K(), raw='{"to_handle":"bob","amount":null}')
        assert r.status in (400, 422) and r.code in ("malformed_request", "validation_failed"), r
    m.done()
    assert w.bal("ada") == 5_000_000_000 and w.bal("bob") == 0, "rejected amounts must not move money"
    # the largest amount is accepted; balances stay exact
    T(w.pay("ada", "bob", 1_000_000_000))
    assert w.bal("ada") == 4_000_000_000 and w.bal("bob") == 1_000_000_000


@probe("S1-043", "S1-008")
def large_balances_stay_exact_below_2_pow_53():
    big = 9_000_000_000_000_000  # < 2**53 = 9007199254740992
    w = World(balances={"ada": big, "bob": 1})
    T(w.pay("ada", "bob", 999_999_999))
    T(w.pay("ada", "bob", 1))
    assert w.bal("ada") == big - 1_000_000_000, w.bal("ada")
    assert w.bal("bob") == 1_000_000_001
    assert w.sum_now() == big + 1
    T(w.pay("bob", "ada", 1_000_000_001 - 1))
    assert w.bal("ada") == big - 1_000_000_000 + 1_000_000_000 and w.bal("bob") == 1
