"""Stage 4: races, export/import (own round trip; stage-1/2/3 exports)."""
import copy
import json
import random
import time
from kit4 import *
from s4_02_batches import batch_world, eff_of, state_of
import s3_07_export as s37
import s2_04_export as s24


@probe("S4-052", "S4-057", "S4-041", "S4-050")
def batches_sharing_an_expected_revision_cannot_both_succeed_and_never_apply_partially():
    for rnd in range(5):
        w = batch_world()
        e = lambda pid: eff_of(w, pid)
        b3, b4, b1 = e("b_3"), e("b_4"), e("b_1")
        before = {n: w.me(n)["balance"] for n in w.balances}
        r1, r2 = par([lambda: w.batch("eve", [item("b_3", 1, 101, b3), item("b_4", 1, 51, b4)]),
                      lambda: w.batch("eve", [item("b_4", 1, 52, b4), item("b_1", 1, 501, b1)])])
        assert sorted([r1.status, r2.status]) == [201, 409], (r1, r2)
        loser = r1 if r1.status == 409 else r2
        expect(loser, 409, "stale_revision")
        # the loser did not touch its other payment
        if r1.status == 201:
            assert len(parjson(w.revisions("ada", "b_1"), 200)["revisions"]) == 1 and w.me("dee")["balance"] == before["dee"] - 1 - 1
        else:
            assert len(parjson(w.revisions("dee", "b_3"), 200)["revisions"]) == 1, "the losing batch must not touch b_3"
        assert len(parjson(w.revisions("dee", "b_4"), 200)["revisions"]) == 2, "the shared payment got exactly one new revision"
        assert sum(w.me(n)["balance"] for n in w.balances) == sum(w.h.opening.values())
    # a batch racing a single correction on the same payment, and many batches on the same revision
    w = batch_world()
    e4 = eff_of(w, "b_4")
    rb, rs = par([lambda: w.batch("eve", [item("b_4", 1, 40, e4)]), lambda: w.fix("dee", "b_4", 1, 30, iso(e4))])
    assert sorted([rb.status, rs.status]) == [201, 409], (rb, rs)
    expect(rb if rb.status == 409 else rs, 409, "stale_revision")
    w = batch_world()
    e4 = eff_of(w, "b_4")
    rs = par([(lambda i=i: w.batch("eve", [item("b_4", 1, 10 + i, e4)])) for i in range(12)])
    codes = sorted(r.status for r in rs)
    assert codes.count(201) == 1 and codes.count(409) == 11, codes
    assert len(parjson(w.revisions("dee", "b_4"), 200)["revisions"]) == 2
    # disjoint batches both succeed concurrently
    w = batch_world()
    r1, r2 = par([lambda: w.batch("eve", [item("b_3", 1, 101, eff_of(w, "b_3"))]), lambda: w.batch("eve", [item("b_4", 1, 49, eff_of(w, "b_4"))])])
    assert r1.status == 201 and r2.status == 201, (r1, r2)
    assert r1.json["correction_batch_id"] != r2.json["correction_batch_id"]


@probe("S4-041", "S4-040", "S4-017", "S4-054", "S4-052", "S4-059", "S4-050", "S4-054")
def mixed_refunds_batches_corrections_and_reads_keep_every_invariant():
    t = now_dt().replace(microsecond=0)
    names = ["ada", "bob", "cy", "dee"]
    pays = []
    for i in range(12):
        a, b = names[i % 4], names[(i + 1) % 4]
        pays.append(("m_%02d" % i, a, b, 20 + i, t - timedelta(hours=30 - i)))
    w = build4({n: 5000 for n in names} | {"eve": 0, "fay": 0}, pays)
    rnd = random.Random(21)
    pids = [p[0] for p in pays]
    fns = []
    for i in range(120):
        kind = rnd.choice(["refund", "refund", "batch", "batch", "fix", "read", "stmt", "pay"])
        pid = rnd.choice(pids)
        p = w.h.pays[pid]
        if kind == "refund":
            fns.append(lambda pid=pid, p=p: w.refund(p.to, pid, rnd.randint(1, 15)))
        elif kind == "batch":
            sel = rnd.sample(pids, rnd.randint(1, 3))
            fns.append(lambda sel=sel: w.batch("eve", [item(x, rnd.randint(1, 3), rnd.randint(0, 60), eff_of(w, x) + timedelta(minutes=rnd.randint(-120, 0))) for x in sel]))
        elif kind == "fix":
            fns.append(lambda pid=pid, p=p: w.fix(p.frm, pid, rnd.randint(1, 3), rnd.randint(0, 60), iso(eff_of(w, pid))))
        elif kind == "read":
            fns.append(lambda: w.me3(rnd.choice(names), as_of=iso(now_dt() - timedelta(minutes=rnd.randint(0, 1900)))))
        elif kind == "stmt":
            fns.append(lambda: w.stmt(rnd.choice(names), limit=200))
        else:
            a, b = rnd.sample(names, 2)
            fns.append(lambda a=a, b=b: w.pay(a, b, rnd.randint(1, 30)))
    results = []
    for i in range(0, len(fns), 40):
        results += par(fns[i:i + 40])
    assert all(r.status < 500 for r in results)
    for r in results:
        if r.status in (409, 422, 404):
            assert r.code in ("stale_revision", "insufficient_funds", "historical_overdraft", "refund_exceeds_payment", "validation_failed", "not_found", "forbidden"), r
    total = sum(w.h.opening.values())
    now_bal = {n: w.me(n)["balance"] for n in w.balances}
    assert sum(now_bal.values()) == total and all(b >= 0 for b in now_bal.values()), now_bal
    # refunds never exceed the current corrected amount of their target
    allp = {}
    for n in names:
        for p in w.all_activity(n):
            allp[p["payment_id"]] = p
    for pid in pids:
        cur = parjson(w.revisions(w.h.pays[pid].frm, pid), 200)["revisions"][-1]["amount"]
        refunded = sum(p["amount"] for p in allp.values() if p.get("refund_of") == pid)
        assert refunded <= cur, "payment %s: refunded %d exceeds the current corrected amount %d" % (pid, refunded, cur)
    for n in names:
        j = stmt_full(w, n)
        check_statement_shape(j)
        assert j["closing_balance"] == now_bal[n]
        run, by_t = j["opening_balance"], {}
        for e in j["entries"]:
            by_t[P(e["effective_at"])] = by_t.get(P(e["effective_at"]), 0) + e["delta"]
        for k in sorted(by_t):
            run += by_t[k]
            assert run >= 0, "%s negative at %s" % (n, k)
    for a in (now_dt() - timedelta(hours=10), now_dt() + timedelta(days=1)):
        assert sum_over_users(w, a) == total


def build_round_trip_world():
    w = batch_world()
    t = lambda pid: eff_of(w, pid)
    keys = {}
    sj = T(w.settle("eve", [{"from_handle": "dee", "to_handle": "ada", "amount": 30}, {"from_handle": "dee", "to_handle": "bob", "amount": 20}], key=(ks := K())), 201)
    for p in sj["payments"]:
        w.h.add(p["payment_id"], p["from_handle"], p["to_handle"], p["amount"], P(p["created_at"]), p["visibility"])
    keys["settle"] = (ks, {"transfers": [{"from_handle": "dee", "to_handle": "ada", "amount": 30}, {"from_handle": "dee", "to_handle": "bob", "amount": 20}]}, sj)
    m1, m2 = [p["payment_id"] for p in sj["payments"]]
    time.sleep(0.05)
    kr = K()
    rf = T(w.refund("ada", m1, 7, key=kr), 201)
    w.h.add(rf["payment_id"], "ada", "dee", 7, P(rf["created_at"]), rf["visibility"])
    keys["refund"] = (kr, {"amount": 7}, rf)
    kf = K()
    fbody = {"expected_revision": 1, "amount": 60, "effective_at": iso(t("b_4"), 0, micro=True), "reason": "single"}
    fj = T(call("POST", "/payments/b_4/corrections", token=w.tok["dee"], key=kf, body=fbody), 201)
    w.h.add_rev("b_4", 2, 60, P(fj["effective_at"]), P(fj["recorded_at"]))
    keys["fix"] = (kf, fbody, fj)
    kb = K()
    ebody = {"corrections": [item("b_3", 1, 130, t("b_3")), item("b_4", 2, 20, t("b_4"))]}
    bj = T(call("POST", "/correction-batches", token=w.tok["eve"], key=kb, body=ebody), 201)
    for x in bj["revisions"]:
        w.h.add_rev(x["payment_id"], x["revision"], x["amount"], P(x["effective_at"]), P(x["recorded_at"]))
    keys["batch"] = (kb, ebody, bj)
    snaps = {}
    for u in ("ada", "dee"):
        full = stmt_full(w, u)
        snaps[u] = (parjson(w.stmt(u, limit=3), 200)["snapshot"], full)
    # a change after the snapshots, so that "frozen" is observable
    w.batch_ok("eve", [item("b_1", 1, 520, t("b_1"))])
    return w, keys, snaps, (m1, m2)


@probe("S4-053", "S4-060", "S4-061", "S4-062", "S4-063", "S4-064", "S4-065", "S4-066", "S4-067", "S4-068", "S4-047", "S4-048")
def round_trip_keeps_refunds_batches_membership_snapshots_and_replays():
    w, keys, snaps, (m1, m2) = build_round_trip_world()
    users = ["ada", "bob", "cy", "dee", "fay"]
    h0 = copy.deepcopy(w.h)
    before = s37.views(w, users, h0)
    exp = T(call("GET", "/_test/export"), 200)
    assert s37.views(w, users, h0) == before
    late = T(call("POST", "/auth/signup", body={"email": "late@example.com", "password": "longenough1", "display_name": "L"}), 201)
    w.p("ada", "bob", 3)
    reset(fixture2({"kim": 700, "lee": 300}))
    expect(call("POST", "/_test/import", body=exp), 204)
    after = s37.views(w, users, h0)
    for key in before:
        assert after[key] == before[key], "view %r differs after import" % (key,)
    expect(call("GET", "/me", token=late["token"]), 401, "unauthenticated")
    # saved statements (snapshots) are still available and frozen
    for u, (tok, full) in snaps.items():
        got, off = [], 0
        while True:
            j = parjson(w.stmt(u, snapshot=tok, limit=3, offset=off), 200)
            got += j["entries"]
            if not j["has_more"]:
                break
            off += 3
        assert entries_view(got) == entries_view(full["entries"]), "snapshot of %s changed or vanished across export/import" % u
    # replays of every write path used, with their original bodies
    kk, body, orig = keys["settle"]
    rr = call("POST", "/settlements", token=w.tok["eve"], key=kk, body=body)
    expect(rr, 200)
    assert rr.json == orig
    kk, body, orig = keys["refund"]
    rr = call("POST", "/payments/%s/refunds" % m1, token=w.tok["ada"], key=kk, body=body)
    expect(rr, 200)
    assert rr.json == orig and rr.json["refund_of"] == m1
    kk, body, orig = keys["fix"]
    rr = call("POST", "/payments/b_4/corrections", token=w.tok["dee"], key=kk, body=body)
    expect(rr, 200)
    assert rr.json == orig
    kk, body, orig = keys["batch"]
    rr = call("POST", "/correction-batches", token=w.tok["eve"], key=kk, body=body)
    expect(rr, 200)
    assert rr.json == orig, "batch replay differs after import"
    expect(call("POST", "/correction-batches", token=w.tok["eve"], key=kk, body={"corrections": body["corrections"][:1]}), 409, "idempotency_key_reuse")
    # refund limit continues across import (cumulative), settlement membership is still enforced
    expect(w.refund("ada", m1, 24), 422, "refund_exceeds_payment")
    w.refund_ok("ada", m1, 23)
    e = eff_of(w, "b_1") - timedelta(minutes=5)
    expect(w.batch("eve", [item(m2, 1, 21, e)]), 422, "incomplete_settlement")
    cur = lambda pid: len(parjson(w.revisions(w.h.pays[pid].frm if pid in w.h.pays else "dee", pid), 200)["revisions"])
    j = T(w.batch("eve", [item(m1, cur(m1), 30, e), item(m2, cur(m2), 21, e)]), 201)
    # new recorded times are later than everything imported, new batch ids do not collide
    assert P(j["recorded_at"]) > max(P(x["recorded_at"]) for x in keys["batch"][2]["revisions"])
    assert j["correction_batch_id"] != keys["batch"][2]["correction_batch_id"]
    assert sum(w.me(n)["balance"] for n in w.balances) == sum(w.h.opening.values())
    # reset discards snapshots
    tok0 = snaps["ada"][0]
    reset(w.fx)
    t2 = login("ada@example.com")
    expect(call("GET", "/statement?snapshot=" + tok0, token=t2), 404, "not_found")


@probe("S4-053", "S4-064", "S4-069", "S4-061", "S4-036", "S4-034", "S4-011")
def a_stage1_export_is_accepted_with_membership_and_refundable_payments():
    if not STAGE1_URL:
        return "skip"                # needs --stage1-url (a running stage-1 service of the same team)
    src = lib.BASE
    lib.BASE = STAGE1_URL
    try:
        pays = [{"id": "p_seed", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "seeded", "visibility": "private"}]
        w1 = World(operators=["u_dee"], payments=pays)
        k = K()
        p1 = T(w1.pay("ada", "bob", 1500, key=k, note="one", visibility="public"), 201)
        ks = K()
        tr = [{"from_handle": "ada", "to_handle": "cy", "amount": 10}, {"from_handle": "bob", "to_handle": "cy", "amount": 5}]
        sj = T(w1.settle("dee", tr, key=ks), 201)
        bal = {n: w1.me(n)["balance"] for n in w1.balances}
        exp = T(call("GET", "/_test/export"), 200)
    finally:
        lib.BASE = src
    reset(fixture2({"kim": 1}))
    expect(call("POST", "/_test/import", body=exp), 204)
    w = Adopted4(w1.tok, w1.balances)
    for n, b in bal.items():
        assert T(call("GET", "/me", token=w.tok[n]), 200)["balance"] == b
        check_statement_shape(stmt_full(w, n))
    # stage-1 payments can be refunded by their receiver and stay corrected-amount limited
    r = T(w.refund("bob", p1["payment_id"], 100), 201)
    assert r["refund_of"] == p1["payment_id"] and r["note"] == "one" and r["visibility"] == "public"
    expect(w.refund("bob", p1["payment_id"], 1401), 422, "refund_exceeds_payment")
    # imported settlement membership: single correction and partial batches are refused, the whole set is accepted
    m1, m2 = [p["payment_id"] for p in sj["payments"]]
    e = iso(now_dt() - timedelta(minutes=30), 0, micro=True)
    expect(w.fix("ada", m1, 1, 11, e), 422, "incomplete_settlement")
    expect(w.batch("dee", [item(m1, 1, 11, e)]), 422, "incomplete_settlement")
    j = T(w.batch("dee", [item(m1, 1, 11, e), item(m2, 1, 4, e)]), 201)
    assert j["revisions"][0]["revision"] == 2
    rr = call("POST", "/settlements", token=w.tok["dee"], key=ks, body={"transfers": tr})
    expect(rr, 200)
    strip = lambda d: {x: y for x, y in d.items() if x not in ("authorization_id", "refund_of")}
    assert [strip(x) for x in rr.json["payments"]] == [strip(x) for x in sj["payments"]], "settlement retry must return the original body"
    rr = call("POST", "/payments", token=w.tok["ada"], key=k, body={"to_handle": "bob", "amount": 1500, "note": "one", "visibility": "public"})
    expect(rr, 200)
    assert strip(rr.json) == strip(p1)


@probe("S4-053", "S4-069", "S4-011", "S4-020")
def a_stage2_export_is_accepted_and_captures_stay_refundable_but_immutable():
    if not STAGE2_URL:
        return "skip"                # needs --stage2-url (a running stage-2 service of the same team)
    src = lib.BASE
    lib.BASE = STAGE2_URL
    try:
        st = s24.build2()
        w2 = st["w"]
        pays = {p["payment_id"]: p for n in w2.balances for p in w2.all_activity(n)}
        bal = {n: w2.me(n)["total"] for n in w2.balances}
        exp = T(call("GET", "/_test/export"), 200)
    finally:
        lib.BASE = src
    reset(fixture2({"kim": 1}))
    expect(call("POST", "/_test/import", body=exp), 204)
    w = Adopted4(w2.tok, w2.balances)
    for n, b in bal.items():
        assert T(call("GET", "/me", token=w.tok[n]), 200)["total"] == b
    caps = [p for p in pays.values() if p.get("authorization_id")]
    assert caps
    cap = caps[0]
    body = {"expected_revision": 1, "amount": 1, "effective_at": iso(P(cap["created_at"])), "reason": "x"}
    expect(call("POST", "/payments/%s/corrections" % cap["payment_id"], token=w.tok[cap["from_handle"]], key=K(), body=body), 422, "linked_payment_immutable")
    expect(w.batch("dee", [item(cap["payment_id"], 1, 1, P(cap["created_at"]))]), 422, "linked_payment_immutable")      # dee is the operator of the stage-2 state
    r = T(w.refund(cap["to_handle"], cap["payment_id"], 1), 201)
    assert r["refund_of"] == cap["payment_id"] and r["authorization_id"] is None
    ordinary = [p for p in pays.values() if not p.get("authorization_id") and not p.get("request_id")][0]
    T(w.refund(ordinary["to_handle"], ordinary["payment_id"], 1), 201)


@probe("S4-053", "S4-062", "S4-063", "S4-064", "S4-065", "S4-066", "S4-067", "S4-069", "S4-061")
def a_stage3_export_is_accepted_with_corrections_membership_and_snapshots():
    if not STAGE3_URL:
        return "skip"                # needs --stage3-url (a running stage-3 service of the same team)
    src = lib.BASE
    lib.BASE = STAGE3_URL
    try:
        w3, keys3, (k_api, api) = s37.build3()
        users = ["ada", "bob", "cy", "dee"]
        h0 = copy.deepcopy(w3.h)
        before = s37.views(w3, users, h0)
        tok = parjson(w3.stmt("ada", limit=2), 200)["snapshot"]
        full = stmt_full(w3, "ada")
        exp = T(call("GET", "/_test/export"), 200)
    finally:
        lib.BASE = src
    reset(fixture2({"kim": 1}))
    expect(call("POST", "/_test/import", body=exp), 204)
    w = Adopted4(w3.tok, w3.balances, h0)
    after = s37.views(w, users, h0)
    strip_batch = lambda v: [{k: x for k, x in r.items() if k != "correction_batch_id"} for r in v] if isinstance(v, list) and v and isinstance(v[0], dict) else v
    for key in before:      # stage 4 adds correction_batch_id to revision objects: everything else must be identical
        assert strip_batch(after[key]) == strip_batch(before[key]), "stage-3 view %r differs after import" % (key,)
    # corrections: key replays, stale revisions, revision history all intact
    for name, (pid, who, k, body, orig) in keys3.items():
        rr = call("POST", "/payments/%s/corrections" % pid, token=w.tok[who], key=k, body=body)
        expect(rr, 200)
        assert rr.json == orig
    # settlement membership from stage 3: the settlement had a single member; a batch with it is accepted, refunds work
    sm = [p for n in users for p in w.all_activity(n) if p.get("settlement_id")]
    assert sm
    m = sm[0]
    cur = len(parjson(w.revisions(m["from_handle"], m["payment_id"]), 200)["revisions"])
    j = T(w.batch("eve", [item(m["payment_id"], cur, m["amount"] + 1, P(m["created_at"]))]), 201)
    assert j["revisions"][0]["revision"] == cur + 1
    r = T(w.refund(m["to_handle"], m["payment_id"], 1), 201)
    assert r["refund_of"] == m["payment_id"]
    # a snapshot saved on the stage-3 service: if it is retained it must still page the same frozen entries
    pg = w.stmt("ada", snapshot=tok, limit=200)
    if pg.status == 200:
        assert entries_view(pg.json["entries"]) == entries_view(full["entries"]), "retained snapshot changed"
    else:
        expect(pg, 404, "not_found")      # not retained by the stage-3 export: tolerated, but never wrong data
