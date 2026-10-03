"""Stage 4: refunds."""
import json
import time
from kit4 import *


@probe("S4-010", "S4-011", "S4-012", "S4-013", "S4-014", "S4-015", "S4-016", "S4-017", "S4-019", "S4-003", "S4-059", "S4-020")
def refund_basics_shape_replay_limits_and_errors():
    w = refund_world()
    # an API payment with a note and private visibility: the refund copies both
    k = K()
    orig_resp = w.pay("ada", "bob", 300, key=k, note="dinner ☕", visibility="private")
    orig = T(orig_resp, 201)
    w.h.add(orig["payment_id"], "ada", "bob", 300, P(orig["created_at"]), "private")
    pid = orig["payment_id"]
    before = {n: w.me(n)["balance"] for n in w.balances}
    kr = K()
    r = w.refund("bob", pid, 100, key=kr)
    j = T(r, 201)
    for key in PAYMENT_KEYS + ["refund_of", "authorization_id"]:
        assert key in j, "refund payment lacks %s: %r" % (key, j)
    assert j["refund_of"] == pid and j["request_id"] is None and j["authorization_id"] is None and j["settlement_id"] is None, j
    assert j["from_handle"] == "bob" and j["to_handle"] == "ada" and j["amount"] == 100, j
    assert j["note"] == "dinner ☕" and j["visibility"] == "private", j
    assert TS_RE.match(j["created_at"]) and j["payment_id"] != pid
    w.h.add(j["payment_id"], "bob", "ada", 100, P(j["created_at"]), "private")
    assert w.me("ada")["balance"] == before["ada"] + 100 and w.me("bob")["balance"] == before["bob"] - 100
    # replay: 200 with the original body, no further money
    for _ in range(2):
        rr = w.refund("bob", pid, 100, key=kr)
        expect(rr, 200)
        assert rr.json == j
    assert w.me("bob")["balance"] == before["bob"] - 100
    expect(w.refund("bob", pid, 101, key=kr), 409, "idempotency_key_reuse")
    # the original receipt and feed item are unchanged; other payments have refund_of null
    assert [p for p in w.all_activity("ada") if p["payment_id"] == pid][0] == orig
    replay = call("POST", "/payments", token=w.tok["ada"], key=k, body={"to_handle": "bob", "amount": 300, "note": "dinner ☕", "visibility": "private"})
    expect(replay, 200)
    assert replay.json == orig
    for n in ("ada", "bob", "cy"):
        for p in w.all_activity(n):
            assert "refund_of" in p and (p["refund_of"] is None) == (p["payment_id"] != j["payment_id"]), p
    # private: the refund inherits the original's privacy
    assert j["payment_id"] in w.activity_ids("ada") and j["payment_id"] in w.activity_ids("bob") and j["payment_id"] not in w.activity_ids("cy")
    # statements treat it as an ordinary payment
    for n in ("ada", "bob"):
        check_vs_oracle(w, n, label="refund statement")
    # cumulative limit: 100 + 200 = 300 fits, one more unit does not
    j2 = w.refund_ok("bob", pid, 200)
    expect(w.refund("bob", pid, 1), 422, "refund_exceeds_payment")
    assert total_refunded(w, pid) == 300
    # errors: sender, third party, unknown, no key, no token, invalid amounts
    m = Multi()
    with m.case("sender"):
        expect(w.refund("ada", pid, 1), 403, "forbidden")
    with m.case("third party"):
        expect(w.refund("cy", pid, 1), 403, "forbidden")
    with m.case("unknown"):
        expect(w.refund("bob", "p_missing", 1), 404, "not_found")
    with m.case("no key"):
        expect(call("POST", "/payments/%s/refunds" % pid, token=w.tok["bob"], body={"amount": 1}), 400, "missing_idempotency_key")
    with m.case("no token"):
        expect(call("POST", "/payments/%s/refunds" % pid, key=K(), body={"amount": 1}), 401, "unauthenticated")
    for bad in (0, -1, 1.5, "5", True, 1000000001, None):
        with m.case("amount %r" % (bad,)):
            r = call("POST", "/payments/r_1/refunds", token=w.tok["bob"], key=K(), body={"amount": bad})
            assert r.status in (422, 400) and r.code in ("validation_failed", "malformed_request"), r
            if bad is not None:
                expect(r, 422, "validation_failed")
    with m.case("missing amount"):
        expect(call("POST", "/payments/r_1/refunds", token=w.tok["bob"], key=K(), body={}), 422, "validation_failed")
    with m.case("unknown fields ignored"):
        T(call("POST", "/payments/r_1/refunds", token=w.tok["bob"], key=K(), body={"amount": 5, "note": "ignored", "visibility": "private", "refund_of": "x"}), 201)
    with m.case("unparseable"):
        expect(call("POST", "/payments/r_1/refunds", token=w.tok["bob"], key=K(), raw="{x"), 400, "malformed_request")
    m.done()
    # refunds of refunds, and refund payments cannot be corrected
    expect(w.refund("ada", j["payment_id"], 10), 422, "invalid_refund_target")     # the receiver of a refund may not refund it
    expect(w.refund("ada", j2["payment_id"], 1), 422, "invalid_refund_target")
    body = {"expected_revision": 1, "amount": 50, "effective_at": iso(P(j["created_at"])), "reason": "no"}
    expect(call("POST", "/payments/%s/corrections" % j["payment_id"], token=w.tok["bob"], key=K(), body=body), 422, "linked_payment_immutable")
    expect(call("POST", "/payments/%s/corrections" % j["payment_id"], token=w.tok["ada"], key=K(), body=body), 403, "forbidden")
    assert w.me("ada")["balance"] == before["ada"] + 300 + 5      # 100 + 200 refunded, plus the 5 refunded of r_1 above


@probe("S4-011", "S4-015", "S4-018", "S4-051", "S4-017", "S4-110")
def refunds_of_request_capture_and_settlement_payments_change_no_links_and_use_available_funds():
    w = refund_world()
    # request payment
    rq = T(w.req("bob", "ada", 100))
    pr = T(w.payreq("ada", rq["request_id"]))
    w.h.add(pr["payment_id"], "ada", "bob", 100, P(pr["created_at"]), pr["visibility"])
    # capture
    a = T(w.auth("ada", "bob", 400, note="deposit", visibility="private"))
    cap = T(w.capture("bob", a["authorization_id"], {"amount": 250, "final": False}))
    w.h.add(cap["payment_id"], "ada", "bob", 250, P(cap["created_at"]), "private")
    # settlement member
    sj = w.settlement("eve", [{"from_handle": "dee", "to_handle": "bob", "amount": 60}, {"from_handle": "dee", "to_handle": "ada", "amount": 40}])
    member = sj["payments"][0]
    held0 = w.me("ada")["held"]
    # refund each kind
    rf1 = w.refund_ok("bob", pr["payment_id"], 30)
    rf2 = w.refund_ok("bob", cap["payment_id"], 100)
    rf3 = w.refund_ok("bob", member["payment_id"], 20)
    assert rf1["refund_of"] == pr["payment_id"] and rf1["request_id"] is None
    assert rf2["refund_of"] == cap["payment_id"] and rf2["authorization_id"] is None and rf2["visibility"] == "private" and rf2["note"] == "deposit"
    assert rf3["refund_of"] == member["payment_id"] and rf3["settlement_id"] is None
    # nothing reopened: request stays paid, authorization keeps its state and its hold, settlement membership is unchanged
    q = w.request_by_id("bob", rq["request_id"])
    assert q["status"] == "paid" and q["payment_id"] == pr["payment_id"]
    g = w.auth_by_id("ada", a["authorization_id"])
    assert g["status"] == "open" and g["captured_amount"] == 250 and g["remaining_amount"] == 150 and g["payment_ids"] == [cap["payment_id"]], g
    assert w.me("ada")["held"] == held0
    m_after = [p for p in w.all_activity("bob") if p["payment_id"] == member["payment_id"]][0]
    assert m_after == member, "the settlement member's receipt must not change"
    # captures stay immutable, ordinary and request payments stay correctable by their sender
    body = {"expected_revision": 1, "amount": 200, "effective_at": iso(P(cap["created_at"])), "reason": "no"}
    expect(call("POST", "/payments/%s/corrections" % cap["payment_id"], token=w.tok["ada"], key=K(), body=body), 422, "linked_payment_immutable")
    expect(call("POST", "/payments/%s/corrections" % cap["payment_id"], token=w.tok["bob"], key=K(), body=body), 403, "forbidden")
    w.fix_ok("ada", pr["payment_id"], 1, 90, P(pr["created_at"]))                  # refunded 30 so far: 90 is allowed
    expect(w.fix("ada", pr["payment_id"], 2, 29, iso(P(pr["created_at"]))), 422, "refund_exceeds_payment")
    # a voided hold is not restored by refunding its capture
    T(w.void("ada", a["authorization_id"]), 200)
    held1 = w.me("ada")["held"]
    w.refund_ok("bob", cap["payment_id"], 50)
    assert w.me("ada")["held"] == held1 and w.auth_by_id("ada", a["authorization_id"])["status"] == "voided"
    # refunds come from the receiver's AVAILABLE funds: bob holds money elsewhere
    w2 = refund_world()
    p = T(w2.pay("ada", "bob", 300))
    w2.h.add(p["payment_id"], "ada", "bob", 300, P(p["created_at"]), "public")
    bal = w2.me("bob")["balance"]
    h = T(w2.auth("bob", "cy", bal - 100))                 # leaves 100 available although the total is large
    assert w2.me("bob")["available"] == 100 and w2.me("bob")["total"] == bal
    before = {n: w2.me(n) for n in ("ada", "bob")}
    expect(w2.refund("bob", p["payment_id"], 101), 409, "insufficient_funds")
    assert {n: w2.me(n) for n in ("ada", "bob")} == before and total_refunded(w2, p["payment_id"]) == 0, "a failed refund must change nothing"
    w2.refund_ok("bob", p["payment_id"], 100)
    assert w2.me("bob")["available"] == 0 and w2.me("bob")["held"] == bal - 100
    expect(w2.refund("bob", p["payment_id"], 1), 409, "insufficient_funds")
    T(w2.void("bob", h["authorization_id"]), 200)
    w2.refund_ok("bob", p["payment_id"], 150)
    assert total_refunded(w2, p["payment_id"]) == 250
    for n in ("ada", "bob"):
        check_vs_oracle(w2, n, label="refund with holds")
    sums = sum(w2.me(n)["balance"] for n in w2.balances)
    assert sums == sum(w2.h.opening.values())


@probe("S4-013", "S4-021", "S4-020", "S4-022", "S4-023", "S4-056")
def refund_limit_follows_the_current_corrected_amount_and_corrections_cannot_go_below_refunds():
    w = refund_world()
    t = lambda pid: w.h.pays[pid].revs[0][2]
    # r_1: ada -> bob 300. Correct to 200: refunds are limited by 200 now
    w.fix_ok("ada", "r_1", 1, 200, t("r_1"))
    rf = w.refund_ok("bob", "r_1", 150)
    expect(w.refund("bob", "r_1", 51), 422, "refund_exceeds_payment")
    # correcting below what was already refunded: refund_exceeds_payment (also zero), correcting to exactly the refunded amount is fine
    body = lambda amt, rev: {"expected_revision": rev, "amount": amt, "effective_at": iso(t("r_1")), "reason": "x"}
    expect(call("POST", "/payments/r_1/corrections", token=w.tok["ada"], key=K(), body=body(149, 2)), 422, "refund_exceeds_payment")
    expect(call("POST", "/payments/r_1/corrections", token=w.tok["ada"], key=K(), body=body(0, 2)), 422, "refund_exceeds_payment")
    assert len(parjson(w.revisions("ada", "r_1"), 200)["revisions"]) == 2
    w.fix_ok("ada", "r_1", 2, 150, t("r_1"))                      # equals the refunded amount: allowed
    expect(w.refund("bob", "r_1", 1), 422, "refund_exceeds_payment")
    # raising the payment raises the refund limit again
    w.fix_ok("ada", "r_1", 3, 400, t("r_1"))
    w.refund_ok("bob", "r_1", 250)
    expect(w.refund("bob", "r_1", 1), 422, "refund_exceeds_payment")
    # a payment corrected to zero with no refunds cannot be refunded at all
    w.fix_ok("dee", "r_2", 1, 0, t("r_2"))
    expect(w.refund("bob", "r_2", 1), 422, "refund_exceeds_payment")
    for n in ("ada", "bob"):
        check_vs_oracle(w, n, label="corrected refunds")
    # correction debits are checked against AVAILABLE funds: ada's money is held elsewhere
    w2 = refund_world()
    bal = w2.me("ada")["balance"]
    T(w2.auth("ada", "cy", bal - 50))                              # ada keeps 50 available
    assert w2.me("ada")["available"] == 50
    t2 = w2.h.pays["r_1"].revs[0][2]
    expect(w2.fix("ada", "r_1", 1, 351, iso(t2)), 409, "insufficient_funds")           # +51 > 50 available
    j = w2.fix_ok("ada", "r_1", 1, 350, t2)                                              # +50 fits exactly
    assert w2.me("ada")["available"] == 0
    # decreasing debits the receiver's available funds as well
    T(w2.auth("bob", "cy", w2.me("bob")["balance"] - 10))
    expect(w2.fix("ada", "r_1", 2, 300, iso(t2)), 409, "insufficient_funds")           # bob would pay back 50 with 10 available
    for n in ("ada", "bob"):
        check_vs_oracle(w2, n, label="corrected with holds")


@probe("S4-004", "S4-016", "S4-010", "S4-054")
def refund_idempotency_scope_and_failed_keys():
    w = refund_world()
    m = Multi()
    k = K()
    with m.case("scope per user and path"):
        a = T(w.refund("bob", "r_1", 10, key=k), 201)
        b = T(call("POST", "/payments/r_2/refunds", token=w.tok["bob"], key=k, body={"amount": 10}), 201)
        assert a["payment_id"] != b["payment_id"] and a["refund_of"] == "r_1" and b["refund_of"] == "r_2"
        expect(w.refund("bob", "r_1", 10, key=k), 200)
    with m.case("same key, other user's own payment"):
        p = T(w.pay("ada", "dee", 20))
        kk = K()
        T(w.refund("dee", p["payment_id"], 5, key=kk), 201)
        T(call("POST", "/payments/r_1/refunds", token=w.tok["bob"], key=kk, body={"amount": 5}), 201)
    with m.case("claimed key is resolved before validation"):
        kz = K()
        T(w.refund("bob", "r_1", 7, key=kz), 201)
        expect(w.refund("bob", "r_1", 0, key=kz), 409, "idempotency_key_reuse")
        expect(w.refund("bob", "r_1", 7000, key=kz), 409, "idempotency_key_reuse")
        expect(call("POST", "/payments/r_1/refunds", token=w.tok["bob"], key=kz, raw="{x"), 400, "malformed_request")
        expect(call("POST", "/payments/r_1/refunds", key=kz, body={"amount": 7}), 401, "unauthenticated")
    with m.case("failed key is reusable once the cause is gone"):
        kf = K()
        pbig = T(w.pay("ada", "bob", 300))
        # refund more than bob can afford... bob has money; use a refund over the cumulative limit instead
        expect(w.refund("bob", pbig["payment_id"], 301, key=kf), 422, "refund_exceeds_payment")
        expect(w.refund("bob", pbig["payment_id"], 300, key=kf), 201)        # first use: different body is fine after a 4xx
        expect(w.refund("bob", pbig["payment_id"], 300, key=kf), 200)
    with m.case("concurrent identical requests take effect once"):
        pc = T(w.pay("ada", "bob", 120))
        kc = K()
        before = w.me("bob")["balance"]
        rs = par([(lambda: w.refund("bob", pc["payment_id"], 40, key=kc)) for _ in range(12)])
        assert sorted(r.status for r in rs) == [200] * 11 + [201], [r.status for r in rs]
        first = [r for r in rs if r.status == 201][0].json
        assert all(r.json == first for r in rs)
        assert w.me("bob")["balance"] == before - 40
    m.done()


@probe("S4-054", "S4-055", "S4-056", "S4-013", "S4-017", "S4-052")
def refund_races_never_break_limits_or_overdraw():
    # (a) cumulative limit: 10 concurrent refunds of 40 against a payment of 300
    w = refund_world()
    p = T(w.pay("ada", "bob", 300))
    before = {n: w.me(n)["balance"] for n in ("ada", "bob")}
    rs = par([(lambda: w.refund("bob", p["payment_id"], 40)) for _ in range(10)])        # distinct keys
    codes = sorted(r.status for r in rs)
    assert codes.count(201) == 7 and codes.count(422) == 3, codes
    for r in rs:
        if r.status == 422:
            expect(r, 422, "refund_exceeds_payment")
    assert total_refunded(w, p["payment_id"]) == 280
    assert w.me("bob")["balance"] == before["bob"] - 280 and w.me("ada")["balance"] == before["ada"] + 280
    # (b) a refund and a payment compete for the receiver's available funds
    for rnd in range(4):
        w = refund_world()
        p = T(w.pay("ada", "bob", 300))
        bal = w.me("bob")["balance"]
        T(w.auth("bob", "dee", bal - 100))                                               # 100 available
        r_ref, r_pay = par([lambda: w.refund("bob", p["payment_id"], 100), lambda: w.pay("bob", "cy", 100)])
        assert sorted([r_ref.status, r_pay.status]) == [201, 409], (r_ref, r_pay)
        expect(r_ref if r_ref.status == 409 else r_pay, 409, "insufficient_funds")
        assert w.me("bob")["available"] == 0 and w.me("bob")["total"] >= w.me("bob")["held"]
    # (c) a refund and a correction below the refunded amount race: exactly one succeeds, the invariant holds
    for rnd in range(6):
        w = refund_world()
        t = w.h.pays["r_1"].revs[0][2]
        r_ref, r_fix = par([lambda: w.refund("bob", "r_1", 150), lambda: w.fix("ada", "r_1", 1, 100, iso(t))])
        assert sorted([r_ref.status, r_fix.status]) == [201, 422], (r_ref, r_fix)
        assert not (r_ref.status == 201 and r_fix.status == 201), "a refund above the corrected amount and the correction both succeeded"
        cur = parjson(w.revisions("ada", "r_1"), 200)["revisions"][-1]["amount"]
        assert total_refunded(w, "r_1") <= cur, "refunded %d exceeds the current corrected amount %d" % (total_refunded(w, "r_1"), cur)
        loser = r_ref if r_ref.status != 201 else r_fix
        expect(loser, 422, "refund_exceeds_payment")
        assert sum(w.me(n)["balance"] for n in w.balances) == sum(w.h.opening.values())
