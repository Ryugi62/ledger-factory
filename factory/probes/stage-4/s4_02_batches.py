"""Stage 4: POST /correction-batches."""
import json
import time
from kit4 import *


def batch_world(extra=(), auths=None):
    t = now_dt().replace(microsecond=0)
    at = lambda h: t - timedelta(hours=h)
    pays = [("b_1", "ada", "bob", 500, at(6)), ("b_2", "bob", "cy", 500, at(4)), ("b_3", "dee", "ada", 100, at(3)),
            ("b_4", "dee", "fay", 50, at(2))] + list(extra)
    return build4({"ada": 1000, "bob": 0, "cy": 0, "dee": 2000, "eve": 0, "fay": 0}, pays, auths=auths)


def eff_of(w, pid):
    return w.h.pays[pid].revs[0][2]


def state_of(w, users=("ada", "bob", "cy", "dee", "fay")):
    return ({u: w.me(u)["balance"] for u in users}, {u: entries_view(stmt_full(w, u)["entries"]) for u in users},
            {p: len(parjson(w.revisions(w.h.pays[p].frm, p), 200)["revisions"]) for p in w.h.pays})


@probe("S4-002", "S4-030", "S4-033", "S4-041", "S4-042", "S4-043", "S4-044", "S4-045", "S4-046", "S4-047", "S4-049", "S4-050", "S4-037", "S4-023", "S4-090")
def batch_authorization_shape_shared_recorded_at_originals_and_replay():
    w = batch_world()
    # a prior single correction on b_4, so the batch must record strictly after it
    prior = w.fix_ok("dee", "b_4", 1, 40, eff_of(w, "b_4"))
    time.sleep(0.01)
    items = [item("b_3", 1, 150, eff_of(w, "b_3"), "raise", tz=2), item("b_4", 2, 0, eff_of(w, "b_4"), "reverse", tz=-5)]
    body = {"corrections": items}
    # who may call
    expect(call("POST", "/correction-batches", key=K(), body=body), 401, "unauthenticated")
    expect(call("POST", "/correction-batches", token=w.tok["ada"], key=K(), body=body), 403, "forbidden")
    expect(call("POST", "/correction-batches", token=w.tok["dee"], key=K(), body=body), 403, "forbidden")
    expect(call("POST", "/correction-batches", token=w.tok["eve"], body=body), 400, "missing_idempotency_key")
    expect(call("POST", "/correction-batches", token=w.tok["eve"], key="", body=body), 400, "missing_idempotency_key")
    assert len(parjson(w.revisions("dee", "b_3"), 200)["revisions"]) == 1, "refused batches changed history"
    before = {n: w.me(n)["balance"] for n in w.balances}
    feed_before = {p["payment_id"]: p for p in w.all_activity("dee")}
    k = K()
    t0 = now_dt()
    r = w.batch("eve", items, key=k)
    j = T(r, 201)
    assert isinstance(j["correction_batch_id"], str) and j["correction_batch_id"] and TS_RE.match(j["recorded_at"])
    assert [x["payment_id"] for x in j["revisions"]] == ["b_3", "b_4"], "revisions must be in input order"
    rec = P(j["recorded_at"])
    for x, (amt, rev) in zip(j["revisions"], ((150, 2), (0, 3))):
        for key in ("payment_id", "revision", "amount", "effective_at", "recorded_at", "reason", "correction_batch_id"):
            assert key in x, "batch revision lacks %s: %r" % (key, x)
        assert x["amount"] == amt and x["revision"] == rev and x["correction_batch_id"] == j["correction_batch_id"], x
        assert P(x["recorded_at"]) == rec, "all revisions of a batch share recorded_at"
    assert rec > P(prior["recorded_at"]), "recorded_at must be strictly later than the previous recorded_at of every member"
    assert rec > w.h.pays["b_3"].revs[0][3] and rec >= t0 - timedelta(seconds=1)
    for x in j["revisions"]:
        w.h.add_rev(x["payment_id"], x["revision"], x["amount"], P(x["effective_at"]), P(x["recorded_at"]))
    # the operator corrected payments of others: dee pays 50 more to ada, fay's 40 comes back
    assert w.me("ada")["balance"] == before["ada"] + 50 and w.me("fay")["balance"] == before["fay"] - 40 and w.me("dee")["balance"] == before["dee"] - 10
    assert w.me("eve")["balance"] == 0
    # revision lists show the batch revisions with their batch id; the original receipts are untouched
    rv = parjson(w.revisions("dee", "b_4"), 200)["revisions"]
    assert [x["revision"] for x in rv] == [1, 2, 3] and rv[-1]["amount"] == 0 and rv[-1].get("correction_batch_id") == j["correction_batch_id"], rv
    assert rv[0].get("correction_batch_id") in (None,) and rv[1].get("correction_batch_id") in (None,)
    feed_after = {p["payment_id"]: p for p in w.all_activity("dee")}
    assert feed_after == feed_before, "original payments and receipts must never change"
    assert feed_after["b_3"]["amount"] == 100 and feed_after["b_4"]["amount"] == 50
    # statements reflect the new revisions (oracle) and an operator gains no access to others' statements/feed
    for u in ("ada", "dee", "fay"):
        check_vs_oracle(w, u, label="batch")
    assert [x for x in stmt_full(w, "eve")["entries"]] == []
    # replay: 200 with the original response, no further effect; a different body with the key is a conflict
    for _ in range(2):
        rr = w.batch("eve", items, key=k)
        expect(rr, 200)
        assert rr.json == j, "replay must return the original batch response"
    assert w.me("ada")["balance"] == before["ada"] + 50
    expect(w.batch("eve", items[:1], key=k), 409, "idempotency_key_reuse")
    expect(w.batch("eve", [item("b_3", 2, -1, eff_of(w, "b_3"))], key=k), 409, "idempotency_key_reuse")
    expect(call("POST", "/correction-batches", token=w.tok["eve"], key=k, raw="{x"), 400, "malformed_request")
    expect(call("POST", "/correction-batches", key=k, body=body), 401, "unauthenticated")
    # stale after the batch: the same expected revisions now conflict
    expect(w.batch("eve", items), 409, "stale_revision")
    # key scope: another operator-less user may not use it; a fresh key works with the new revisions
    j2 = w.batch_ok("eve", [item("b_3", 2, 120, eff_of(w, "b_3"))])
    assert j2["revisions"][0]["revision"] == 3 and P(j2["recorded_at"]) > rec
    # an operator is not special for single corrections: only the original sender may use them
    expect(w.fix("eve", "b_3", 3, 110, iso(eff_of(w, "b_3"))), 403, "forbidden")
    # batch is the tenth idempotent path: concurrent identical requests take effect once
    kc = K()
    cur = len(parjson(w.revisions("dee", "b_3"), 200)["revisions"])
    rs = par([(lambda: w.batch("eve", [item("b_3", cur, 111, eff_of(w, "b_3"))], key=kc)) for _ in range(10)])
    assert sorted(r.status for r in rs) == [200] * 9 + [201], [r.status for r in rs]
    assert all(r.json == [x for x in rs if x.status == 201][0].json for r in rs)
    assert len(parjson(w.revisions("dee", "b_3"), 200)["revisions"]) == cur + 1


@probe("S4-043", "S4-042")
def batch_recorded_at_is_strictly_after_a_correction_made_just_before():
    w = batch_world()
    e = eff_of(w, "b_4")
    rev = 1
    for i in range(20):                               # back-to-back: no sleeping between the correction and the batch
        j1 = w.fix_ok("dee", "b_4", rev, 49 - i, e)
        j2 = w.batch_ok("eve", [item("b_4", rev + 1, 30 + i, e), item("b_3", 1 + i, 100 + i, eff_of(w, "b_3"))])
        assert P(j2["recorded_at"]) > P(j1["recorded_at"]), "batch %d recorded_at %s is not strictly after %s" % (i, j2["recorded_at"], j1["recorded_at"])
        assert all(P(x["recorded_at"]) == P(j2["recorded_at"]) for x in j2["revisions"])
        rev += 2


@probe("S4-031", "S4-032", "S4-033", "S4-037", "S4-045", "S4-041", "S4-020", "S4-021")
def batch_validation_item_errors_and_immutable_payments():
    t = now_dt().replace(microsecond=0)
    pays = [("n_%02d" % i, "ada", "bob", 10 + i, t - timedelta(hours=40 - i)) for i in range(33)]
    w = build4({"ada": 100000, "bob": 0, "cy": 0, "dee": 0, "eve": 0, "fay": 0}, pays)
    eff = lambda i: eff_of(w, "n_%02d" % i)
    ok_item = lambda i, rev=1, amt=None: item("n_%02d" % i, rev, (10 + i + 1) if amt is None else amt, eff(i))
    # a capture and a refund exist as immutable payments
    a = T(w.auth("ada", "bob", 300))
    cap = T(w.capture("bob", a["authorization_id"], {"amount": 100, "final": False}))
    w.h.add(cap["payment_id"], "ada", "bob", 100, P(cap["created_at"]), cap["visibility"])
    rf = w.refund_ok("bob", "n_05", 5)
    before = state_of(w, ("ada", "bob"))
    m = Multi()
    cases = [
        ("empty", [], 422, "validation_failed"),
        ("33 items", [ok_item(i) for i in range(33)], 422, "validation_failed"),
        ("duplicate ids", [ok_item(1), ok_item(2), ok_item(1)], 422, "validation_failed"),
        ("duplicate ids, other fields differ", [ok_item(1), dict(ok_item(1), amount=5)], 422, "validation_failed"),
        ("item not an object", [ok_item(1), 5], 422, "validation_failed"),
        ("item without payment_id", [{k: v for k, v in ok_item(1).items() if k != "payment_id"}], 422, "validation_failed"),
        ("amount negative", [ok_item(1, amt=-1)], 422, "validation_failed"),
        ("amount too big", [ok_item(1, amt=1000000001)], 422, "validation_failed"),
        ("amount string", [ok_item(1, amt="5")], 422, "validation_failed"),
        ("reason empty", [dict(ok_item(1), reason="")], 422, "validation_failed"),
        ("reason 201", [dict(ok_item(1), reason="r" * 201)], 422, "validation_failed"),
        ("effective naive", [dict(ok_item(1), effective_at="2026-09-20T12:00:00")], 422, "validation_failed"),
        ("effective future", [dict(ok_item(1), effective_at=iso(now_dt() + timedelta(hours=1)))], 422, "validation_failed"),
        ("missing expected_revision", [{k: v for k, v in ok_item(1).items() if k != "expected_revision"}], 422, "validation_failed"),
        ("revision 0", [ok_item(1, rev=0)], 422, "validation_failed"),
        ("unknown payment", [ok_item(1), item("p_nope", 1, 5, eff(1))], 404, "not_found"),
        ("stale revision", [ok_item(1), ok_item(2, rev=2)], 409, "stale_revision"),
        ("capture is immutable", [ok_item(1), item(cap["payment_id"], 1, 50, P(cap["created_at"]))], 422, "linked_payment_immutable"),
        ("refund is immutable", [item(rf["payment_id"], 1, 1, P(rf["created_at"]))], 422, "linked_payment_immutable"),
        ("below the refunded amount", [item("n_05", 1, 4, eff(5))], 422, "refund_exceeds_payment"),
    ]
    for name, items, st, code in cases:
        with m.case(name):
            k = K()
            body = {"corrections": items} if name != "not-array" else {}
            expect(call("POST", "/correction-batches", token=w.tok["eve"], key=k, body=body), st, code)
    with m.case("corrections not an array / missing"):
        for body in ({}, {"corrections": "x"}, {"corrections": {"a": 1}}, {"corrections": None}):
            r = call("POST", "/correction-batches", token=w.tok["eve"], key=K(), body=body)
            assert r.status in (400, 422) and r.code in ("validation_failed", "malformed_request"), (body, r)
    with m.case("unparseable"):
        expect(call("POST", "/correction-batches", token=w.tok["eve"], key=K(), raw="{x"), 400, "malformed_request")
    m.done()
    assert state_of(w, ("ada", "bob")) == before, "a rejected batch must leave history, balances and statements unchanged"
    # a failed key is reusable
    kf = K()
    expect(w.batch("eve", [ok_item(1, rev=9)], key=kf), 409, "stale_revision")
    j = T(w.batch("eve", [ok_item(1)], key=kf), 201)
    for x in j["revisions"]:
        w.h.add_rev(x["payment_id"], x["revision"], x["amount"], P(x["effective_at"]), P(x["recorded_at"]))
    # exactly 32 items work, unknown item fields are ignored
    items32 = [dict(ok_item(i, rev=(2 if i == 1 else 1)), junk=1) for i in range(1, 33)]
    j32 = T(w.batch("eve", items32), 201)
    assert len(j32["revisions"]) == 32 and [x["payment_id"] for x in j32["revisions"]] == ["n_%02d" % i for i in range(1, 33)]
    assert len({x["payment_id"] for x in j32["revisions"]}) == 32
    for x in j32["revisions"]:
        w.h.add_rev(x["payment_id"], x["revision"], x["amount"], P(x["effective_at"]), P(x["recorded_at"]))
    for u in ("ada", "bob"):
        check_vs_oracle(w, u, label="32-item batch")
    assert sum(w.me(n)["balance"] for n in w.balances) == sum(w.h.opening.values())


@probe("S4-034", "S4-035", "S4-036", "S4-051", "S4-046", "S4-047", "S4-043", "S4-033", "S4-020")
def settlement_members_are_corrected_only_as_a_complete_set_with_identical_instants():
    w = batch_world()
    ks = K()
    tr = [{"from_handle": "dee", "to_handle": "ada", "amount": 30}, {"from_handle": "dee", "to_handle": "bob", "amount": 20},
          {"from_handle": "ada", "to_handle": "cy", "amount": 10}]
    sj_resp = w.settle("eve", tr, key=ks)
    sj = T(sj_resp, 201)
    for p in sj["payments"]:
        w.h.add(p["payment_id"], p["from_handle"], p["to_handle"], p["amount"], P(p["created_at"]), p["visibility"])
    m1, m2, m3 = [p["payment_id"] for p in sj["payments"]]
    committed = P(sj["committed_at"])
    sj2 = w.settlement("eve", [{"from_handle": "dee", "to_handle": "fay", "amount": 5}, {"from_handle": "ada", "to_handle": "fay", "amount": 5}])
    n1, n2 = [p["payment_id"] for p in sj2["payments"]]
    e = committed - timedelta(minutes=30)
    before = state_of(w)
    m = Multi()
    with m.case("one member only"):
        expect(w.batch("eve", [item(m1, 1, 31, e)]), 422, "incomplete_settlement")
    with m.case("two of three"):
        expect(w.batch("eve", [item(m1, 1, 31, e), item(m2, 1, 21, e)]), 422, "incomplete_settlement")
    with m.case("members of two settlements, one settlement incomplete"):
        expect(w.batch("eve", [item(m1, 1, 31, e), item(m2, 1, 21, e), item(m3, 1, 11, e), item(n1, 1, 6, e)]), 422, "incomplete_settlement")
    with m.case("mismatched effective instants"):
        expect(w.batch("eve", [item(m1, 1, 31, e), item(m2, 1, 21, e + timedelta(seconds=1)), item(m3, 1, 11, e)]), 422, "validation_failed")
        expect(w.batch("eve", [item(m1, 1, 31, e), item(m2, 1, 21, e + timedelta(milliseconds=1)), item(m3, 1, 11, e)]), 422, "validation_failed")
    with m.case("single correction of a member"):
        for pid in (m1, m2, m3):
            body = {"expected_revision": 1, "amount": 12, "effective_at": iso(e), "reason": "x"}
            r = call("POST", "/payments/%s/corrections" % pid, token=w.tok[w.h.pays[pid].frm], key=K(), body=body)
            expect(r, 422, "incomplete_settlement")
            # a stranger and the receiver still get 403
            expect(call("POST", "/payments/%s/corrections" % pid, token=w.tok["fay"], key=K(), body=body), 403, "forbidden")
    m.done()
    assert state_of(w) == before, "rejected batches must change nothing"
    # complete set, the same instant spelled with different offsets/precision: accepted
    spell = [iso(e, 0, micro=True), iso(e, 2, micro=True), iso(e, 0, micro=True).replace("+00:00", "Z")]
    items = [item(m1, 1, 31, spell[0]), item(m2, 1, 21, spell[1]), item(m3, 1, 11, spell[2])]
    j = T(w.batch("eve", items), 201)
    for x in j["revisions"]:
        w.h.add_rev(x["payment_id"], x["revision"], x["amount"], P(x["effective_at"]), P(x["recorded_at"]))
    assert [x["payment_id"] for x in j["revisions"]] == [m1, m2, m3] and len({x["recorded_at"] for x in j["revisions"]}) == 1
    assert P(j["recorded_at"]) > committed, "recorded_at must be strictly later than the members' previous recorded_at (committed_at)"
    assert all(P(x["effective_at"]) == e for x in j["revisions"])
    # membership, receipts and retries are unchanged
    after = {p["payment_id"]: p for p in w.all_activity("dee")}
    for p in sj["payments"]:
        if p["payment_id"] in after:
            assert after[p["payment_id"]] == p, "a settlement member's original receipt must not change"
    rr = call("POST", "/settlements", token=w.tok["eve"], key=ks, body={"transfers": tr})
    expect(rr, 200)
    assert rr.json == sj, "the original settlement retry must return its original body"
    for u in ("ada", "bob", "cy", "dee"):
        check_vs_oracle(w, u, label="settlement batch")
    # a second correction of the whole set, and two settlements in one batch with different instants per settlement
    j2 = w.batch_ok("eve", [item(m1, 2, 30, e + timedelta(minutes=1)), item(m2, 2, 20, e + timedelta(minutes=1)), item(m3, 2, 10, e + timedelta(minutes=1)),
                            item(n1, 1, 4, e - timedelta(minutes=5)), item(n2, 1, 4, e - timedelta(minutes=5), tz=3)])
    assert len(j2["revisions"]) == 5
    # refunds never change membership: refund a member, then correction still needs the whole set; going below the refund is refused
    rf = w.refund_ok(w.h.pays[m1].to, m1, 12)
    assert rf["settlement_id"] is None and rf["refund_of"] == m1
    expect(w.batch("eve", [item(m1, 3, 40, e)]), 422, "incomplete_settlement")
    expect(w.batch("eve", [item(m1, 3, 11, e), item(m2, 3, 20, e), item(m3, 3, 10, e)]), 422, "refund_exceeds_payment")
    j3 = w.batch_ok("eve", [item(m1, 3, 12, e), item(m2, 3, 25, e), item(m3, 3, 10, e)])
    expect(w.batch("eve", [item(rf["payment_id"], 1, 1, e)]), 422, "linked_payment_immutable")
    sm = [p for p in w.all_activity(w.h.pays[m1].frm) if p["payment_id"] == m1][0]
    assert sm["settlement_id"] == sj["settlement_id"] and sm["amount"] == 30
    # members' revision 1 is the settlement's committed_at as both times
    rv = parjson(w.revisions("ada", m3), 200)["revisions"]
    assert P(rv[0]["effective_at"]) == P(rv[0]["recorded_at"]) == committed
    for u in ("ada", "bob", "cy", "dee", "fay"):
        check_vs_oracle(w, u, label="settlement batches")


@probe("S4-038", "S4-039", "S4-041", "S4-032", "S4-033")
def batch_error_precedence_item_errors_then_settlement_then_funds_then_history():
    w = batch_world()
    sj = w.settlement("eve", [{"from_handle": "dee", "to_handle": "ada", "amount": 30}, {"from_handle": "dee", "to_handle": "bob", "amount": 20}])
    m1, m2 = [p["payment_id"] for p in sj["payments"]]
    a = T(w.auth("ada", "bob", 100))
    cap = T(w.capture("bob", a["authorization_id"], {}))
    w.h.add(cap["payment_id"], "ada", "bob", 100, P(cap["created_at"]), cap["visibility"])
    e = eff_of(w, "b_3")
    before = state_of(w)
    stale = lambda pid="b_3": item(pid, 5, 1, eff_of(w, pid))
    unknown = item("p_nope", 1, 1, e)
    capture = item(cap["payment_id"], 1, 1, P(cap["created_at"]))
    okb = lambda pid, amt: item(pid, 1, amt, eff_of(w, pid))
    cases = [
        ("stale before unknown", [stale(), unknown], 409, "stale_revision"),
        ("unknown before stale", [unknown, stale()], 404, "not_found"),
        ("capture before stale", [capture, stale()], 422, "linked_payment_immutable"),
        ("stale before capture", [stale(), capture], 409, "stale_revision"),
        ("invalid amount before unknown", [dict(okb("b_3", 1), amount=-1), unknown], 422, "validation_failed"),
        ("unknown before invalid effective", [unknown, dict(okb("b_3", 1), effective_at=iso(now_dt() + timedelta(hours=1)))], 404, "not_found"),
        ("item error beats incomplete settlement", [item(m1, 1, 31, e), unknown], 404, "not_found"),
        ("item error beats incomplete settlement (stale)", [item(m1, 1, 31, e), stale()], 409, "stale_revision"),
        ("incomplete settlement beats unaffordable", [item(m1, 1, 31, e), okb("b_1", 900000)], 422, "incomplete_settlement"),
        ("mismatched instants beat unaffordable", [item(m1, 1, 31, e), item(m2, 1, 21, e + timedelta(seconds=2)), okb("b_1", 900000)], 422, "validation_failed"),
        ("unaffordable beats historical", [okb("b_1", 0), okb("b_2", 700)], 409, "insufficient_funds"),
    ]
    m = Multi()
    for name, items, st, code in cases:
        with m.case(name):
            expect(w.batch("eve", items), st, code)
    m.done()
    assert state_of(w) == before
    # refund_exceeds_payment is an item error: it comes in input order too
    rf = w.refund_ok("bob", "b_1", 100)
    expect(w.batch("eve", [item("b_1", 1, 50, eff_of(w, "b_1")), stale("b_3")]), 422, "refund_exceeds_payment")
    expect(w.batch("eve", [stale("b_3"), item("b_1", 1, 50, eff_of(w, "b_1"))]), 409, "stale_revision")
    # a passing batch after all those failures: nothing was claimed or half-applied
    k = K()
    expect(w.batch("eve", [stale()], key=k), 409, "stale_revision")
    j = T(w.batch("eve", [okb("b_3", 101)], key=k), 201)
    assert j["revisions"][0]["amount"] == 101


@probe("S4-040", "S4-041", "S4-038", "S4-022")
def affordability_and_history_are_judged_on_the_combined_effect_of_the_whole_batch():
    # (1) pass-through wallet: b_1 alone would make bob pay back 500 he does not have; reversing both is net zero for bob
    t = now_dt().replace(microsecond=0)
    at = lambda h: t - timedelta(hours=h)
    w = build4({"ada": 1000, "bob": 0, "cy": 0, "dee": 0, "eve": 0, "fay": 0}, [("c_1", "ada", "bob", 500, at(5)), ("c_2", "bob", "cy", 500, at(3))])
    e1, e2 = eff_of(w, "c_1"), eff_of(w, "c_2")
    assert w.me("bob")["balance"] == 0
    expect(w.fix("ada", "c_1", 1, 0, iso(e1)), 409, "insufficient_funds")
    expect(w.batch("eve", [item("c_1", 1, 0, e1)]), 409, "insufficient_funds")
    expect(w.batch("eve", [item("c_1", 1, 0, e1), item("c_2", 1, 600, e2)]), 409, "insufficient_funds")   # bob needs 500 + 100
    before = state_of(w, ("ada", "bob", "cy"))
    j = w.batch_ok("eve", [item("c_1", 1, 0, e1, "reverse leg 1"), item("c_2", 1, 0, e2, "reverse leg 2")])
    assert {n: w.me(n)["balance"] for n in ("ada", "bob", "cy")} == {"ada": 1000, "bob": 0, "cy": 0}
    for u in ("ada", "bob", "cy"):
        check_vs_oracle(w, u, label="pass-through")
    # (2) the same wallet with later income: b_1 alone is fine today but was overdrawn in the past; both together are fine
    w = build4({"ada": 1000, "bob": 0, "cy": 0, "dee": 600, "eve": 0, "fay": 0},
               [("c_1", "ada", "bob", 500, at(5)), ("c_2", "bob", "cy", 500, at(3)), ("c_3", "dee", "bob", 600, at(1))])
    e1, e2 = eff_of(w, "c_1"), eff_of(w, "c_2")
    expect(w.fix("ada", "c_1", 1, 0, iso(e1)), 409, "historical_overdraft")
    expect(w.batch("eve", [item("c_1", 1, 0, e1)]), 409, "historical_overdraft")
    assert w.me("bob")["balance"] == 600
    w.batch_ok("eve", [item("c_1", 1, 0, e1), item("c_2", 1, 0, e2)])
    assert {n: w.me(n)["balance"] for n in ("ada", "bob", "cy", "dee")} == {"ada": 1000, "bob": 600, "cy": 0, "dee": 0}
    for u in ("ada", "bob", "cy", "dee"):
        check_vs_oracle(w, u, label="history combined")
    # (3) available funds: two increases that each fit but together exceed the sender's available funds
    t2 = now_dt().replace(microsecond=0)
    w = build4({"ada": 1000, "bob": 0, "cy": 0, "dee": 0, "eve": 0, "fay": 0},
               [("d_1", "ada", "bob", 100, t2 - timedelta(hours=5)), ("d_2", "ada", "cy", 100, t2 - timedelta(hours=4))])
    bal = w.me("ada")["balance"]
    T(w.auth("ada", "dee", bal - 50))                                    # 50 available
    assert w.me("ada")["available"] == 50
    for pid in ("d_1", "d_2"):
        r = w.fix("ada", pid, 1, 130, iso(eff_of(w, pid)))
        expect(r, 201)                                                      # +30 fits on its own ...
        w.h.add_rev(pid, 2, 130, P(r.json["effective_at"]), P(r.json["recorded_at"]))
        r = call("POST", "/payments/%s/corrections" % pid, token=w.tok["ada"], key=K(), body={"expected_revision": 2, "amount": 100, "effective_at": iso(eff_of(w, pid)), "reason": "undo"})
        w.h.add_rev(pid, 3, 100, P(r.json["effective_at"]), P(r.json["recorded_at"]))
    assert w.me("ada")["available"] == 50
    before = state_of(w, ("ada", "bob", "cy"))
    expect(w.batch("eve", [item("d_1", 3, 130, eff_of(w, "d_1")), item("d_2", 3, 130, eff_of(w, "d_2"))]), 409, "insufficient_funds")   # +60 > 50
    assert state_of(w, ("ada", "bob", "cy")) == before
    w.batch_ok("eve", [item("d_1", 3, 130, eff_of(w, "d_1")), item("d_2", 3, 120, eff_of(w, "d_2"))])      # +50 exactly
    assert w.me("ada")["available"] == 0
    # a batch that credits the sender back is affordable even though one item alone would not be
    w.batch_ok("eve", [item("d_1", 4, 160, eff_of(w, "d_1")), item("d_2", 4, 90, eff_of(w, "d_2"))])      # +30 -30
    for u in ("ada", "bob", "cy"):
        check_vs_oracle(w, u, label="available combined")
    assert sum(w.me(n)["balance"] for n in w.balances) == sum(w.h.opening.values())


@probe("S4-048", "S4-046", "S4-102")
def snapshots_stay_frozen_after_a_batch_and_new_statements_show_it():
    w = batch_world()
    t = lambda pid: eff_of(w, pid)
    snaps = {}
    for u in ("ada", "dee"):
        full = stmt_full(w, u)
        snaps[u] = (full, parjson(w.stmt(u, limit=2), 200)["snapshot"])
    j = w.batch_ok("eve", [item("b_3", 1, 0, t("b_3") - timedelta(hours=1)), item("b_4", 1, 75, t("b_4"))])
    for u, (full, tok) in snaps.items():
        got, off = [], 0
        while True:
            pg = parjson(w.stmt(u, snapshot=tok, limit=2, offset=off), 200)
            got += pg["entries"]
            assert pg["opening_balance"] == full["opening_balance"] and pg["closing_balance"] == full["closing_balance"]
            if not pg["has_more"]:
                break
            off += 2
        assert entries_view(got) == entries_view(full["entries"]), "a saved statement must keep its frozen entries after a batch"
        fresh = stmt_full(w, u)
        assert entries_view(fresh["entries"]) != entries_view(full["entries"]), "new statements must reflect the batch"
        check_vs_oracle(w, u, label="after batch")
    # and the old view is still reachable through known_at before the batch
    ka = iso(P(j["recorded_at"]) - timedelta(milliseconds=1), 0, micro=True)
    old = stmt_full(w, "ada", known_at=ka)
    assert entries_view(old["entries"]) == entries_view(snaps["ada"][0]["entries"])
